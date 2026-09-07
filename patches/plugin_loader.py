"""
plugin_loader.py — Auto-discovery tab plugin system for AI Editor
═══════════════════════════════════════════════════════════════════
tabs/ folder mein koi bhi .py YA .html daalo → automatic tab ban jayega.

.PY FILES:
    TAB_TITLE, TAB_ORDER, def create(parent, boot_data) chahiye.
    TAB_GROUP = "Music" → sub-tab banega Music parent ke andar.

.HTML FILES:
    HTML comment se metadata read hoti hai (top 20 lines mein):
        <!-- TAB_TITLE: My Dashboard -->
        <!-- TAB_ORDER: 60 -->
        <!-- TAB_GROUP: Tools -->
        <!-- TAB_COLOR: #3b82f6, #60a5fa -->
        <!-- TAB_ICON: 📊 -->
    Bina metadata ke bhi chalega — filename se title ban jayega.
    HTML tkinterweb.HtmlFrame mein render hota hai (fallback: browser button).

SUB-TABS (tab ke andar tab):
    Same TAB_GROUP wale → ek parent tab ke andar nested CTkTabview.
    Example:
        tabs/10_boomerang.py     (TAB_GROUP="Music", TAB_ORDER=10)
        tabs/11_yt_transcript.py (TAB_GROUP="Music", TAB_ORDER=20)
        tabs/12_audio_fetcher.py (TAB_GROUP="Music", TAB_ORDER=30)
    Result: "🎵 Music" tab → 3 sub-tabs andar

USAGE:
    from plugin_loader import discover_tabs, mount_tabs
    tabs = discover_tabs()
    mount_tabs(tabview, tabs, boot_data)
"""

import importlib
import importlib.util
import os
import re
import sys
import traceback
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable

import customtkinter as ctk
import tkinter as tk
import lazy_menu  # Win32 / TCL native menu limit fix

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        safe_args = [
            str(a).encode("ascii", errors="replace").decode("ascii") for a in args
        ]
        print(*safe_args, **kwargs)
    except Exception:
        pass



@dataclass
class TabPlugin:
    """Ek discovered tab plugin ki saari info."""
    module_name: str
    title: str
    order: int
    group: str                      # "" = top-level, "Music" = Music group mein sub-tab
    color: tuple                    # (normal_hex, hover_hex)
    icon: str
    lazy: bool
    create_fn: Callable             # def create(parent_frame, boot_data=None)
    source_path: str
    _mounted: bool = field(default=False, init=False)


_DEFAULT_COLORS = [
    ("#14b8a6", "#2dd4bf"),   # teal
    ("#a855f7", "#c084fc"),   # purple
    ("#f43f5e", "#fb7185"),   # rose
    ("#3b82f6", "#60a5fa"),   # blue
    ("#f97316", "#fb923c"),   # orange
    ("#22c55e", "#4ade80"),   # green
    ("#eab308", "#facc15"),   # yellow
    ("#64748b", "#94a3b8"),   # slate
]

_GROUP_ICONS = {
    "Music": "🎵", "Video": "🎬", "Audio": "🎧",
    "Tools": "🔧", "Utils": "⚙️", "Media": "📺",
}


def _tabs_dir() -> Path:
    """tabs/ folder dhundo — dev mode, frozen exe, aur installer sab handle."""
    candidates = []
    if getattr(sys, "frozen", False):
        # PyInstaller: exe ke bagal mein (installer copies here)
        candidates.append(Path(sys.executable).parent / "tabs")
        # PyInstaller: bundled data (_MEIPASS ke andar)
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidates.append(Path(meipass) / "tabs")
    else:
        # Dev mode: script ke bagal mein
        candidates.append(Path(__file__).resolve().parent / "tabs")
    # CWD fallback
    candidates.append(Path.cwd() / "tabs")

    for c in candidates:
        if c.is_dir():
            return c
    # Default — pehla candidate (error message mein dikhega)
    return candidates[0] if candidates else Path("tabs")


# ═══════════════════════════════════════════════════════════════
# HTML FILE SUPPORT
# ═══════════════════════════════════════════════════════════════
def _parse_html_metadata(html_path: Path) -> dict:
    """
    HTML file ke top 20 lines se metadata parse karo.
    Format:  <!-- TAB_TITLE: My Dashboard -->
    """
    meta = {}
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i > 20:
                    break
                m = re.search(r'<!--\s*TAB_(\w+)\s*:\s*(.+?)\s*-->', line)
                if m:
                    meta[m.group(1).upper()] = m.group(2).strip()
    except Exception:
        pass
    return meta


def _make_html_create_fn(html_path: Path):
    """HTML file ke liye create() function banao — tkinterweb ya browser fallback."""

    def _create(parent_frame, boot_data=None):
        import customtkinter as ctk

        try:
            with open(str(html_path), "r", encoding="utf-8") as f:
                html_content = f.read()
        except Exception as e:
            ctk.CTkLabel(parent_frame, text=f"⚠️ HTML read fail: {e}",
                text_color="#fb7185", font=("Segoe UI", 14)).pack(pady=40)
            return

        container = ctk.CTkFrame(parent_frame, fg_color="transparent")
        container.grid(row=0, column=0, sticky="nsew")
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(1, weight=1)

        # Toolbar
        toolbar = ctk.CTkFrame(container, fg_color="#1a1a2e", height=36, corner_radius=0)
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.grid_propagate(False)

        ctk.CTkLabel(toolbar, text=f"📄  {html_path.name}",
            text_color="#8a8aa3", font=("Segoe UI", 10)).pack(side="left", padx=10)

        def _open_browser():
            import webbrowser
            webbrowser.open(str(html_path))

        ctk.CTkButton(toolbar, text="🌐 Browser", width=80, height=26,
            fg_color="#2d2d4a", hover_color="#3d3d5c", text_color="#a78bfa",
            font=("Segoe UI", 10), command=_open_browser).pack(side="right", padx=6, pady=5)

        _html_ref = [None]

        def _refresh():
            if _html_ref[0]:
                try: _html_ref[0].destroy()
                except: pass
            _render()

        ctk.CTkButton(toolbar, text="🔄 Refresh", width=80, height=26,
            fg_color="#2d2d4a", hover_color="#3d3d5c", text_color="#34d399",
            font=("Segoe UI", 10), command=_refresh).pack(side="right", padx=2, pady=5)

        html_area = ctk.CTkFrame(container, fg_color="#ffffff", corner_radius=0)
        html_area.grid(row=1, column=0, sticky="nsew")

        def _render():
            try:
                with open(str(html_path), "r", encoding="utf-8") as f:
                    content = f.read()
            except:
                content = html_content

            try:
                from tkinterweb import HtmlFrame
                import tkinter as tk
                inner = tk.Frame(html_area)
                inner.pack(fill="both", expand=True)
                hw = HtmlFrame(inner, messages_enabled=False)
                hw.load_html(content)
                hw.pack(fill="both", expand=True)
                _html_ref[0] = inner
                print(f"[HTML] ✓ {html_path.name} rendered via tkinterweb")
            except ImportError:
                inner = ctk.CTkFrame(html_area, fg_color="#0f0f17")
                inner.pack(fill="both", expand=True)
                msg = ctk.CTkFrame(inner, fg_color="#1a1a2e", corner_radius=12)
                msg.pack(pady=30, padx=30)
                ctk.CTkLabel(msg, text=f"📄  {html_path.name}",
                    text_color="#a78bfa", font=("Segoe UI", 16, "bold")).pack(pady=(20, 4))
                ctk.CTkLabel(msg,
                    text="In-app rendering ke liye install karo:\n"
                         "pip install tkinterweb\n\n"
                         "Ya 'Browser' button se browser mein dekho.",
                    text_color="#8a8aa3", font=("Segoe UI", 11), justify="center"
                ).pack(pady=(0, 10), padx=20)
                ctk.CTkButton(msg, text="🌐  Browser mein kholo",
                    width=200, height=40, fg_color="#3b82f6", hover_color="#2563eb",
                    text_color="#ffffff", font=("Segoe UI", 13, "bold"),
                    command=_open_browser).pack(pady=(4, 20))
                _html_ref[0] = inner

        _render()

    return _create


# ═══════════════════════════════════════════════════════════════
# DISCOVER
# ═══════════════════════════════════════════════════════════════
def discover_tabs(tabs_path: str = "", reload: bool = False) -> list[TabPlugin]:
    """tabs/ folder scan — .py AUR .html dono discover."""
    folder = Path(tabs_path) if tabs_path else _tabs_dir()
    if not folder.is_dir():
        print(f"[PLUGIN] tabs/ folder nahi mila: {folder}")
        return []

    # Check hot patches tabs directory
    _appdata = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or os.path.expanduser("~")
    hot_tabs_folder = Path(_appdata) / "StoriesStudio" / "hot_patches" / "tabs"

    # Add all potential root locations to sys.path so modules like Master_Tool, preset_manager, voice_cache can be imported
    for p in reversed([
        str(hot_tabs_folder.parent) if hot_tabs_folder.parent.is_dir() else "",
        str(hot_tabs_folder) if hot_tabs_folder.is_dir() else "",
        getattr(sys, "_MEIPASS", ""),
        os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else "",
        str(Path(__file__).resolve().parent),
        str(folder.parent),
        str(folder),
        str(Path.cwd()),
    ]):
        if p and os.path.isdir(p):
            if p in sys.path:
                sys.path.remove(p)
            sys.path.insert(0, p)

    plugins: list[TabPlugin] = []
    color_idx = 0

    # Collect all available .py files (hot_patches take precedence over bundled files)
    discovered_py_files = {}
    if folder.is_dir():
        for f in sorted(folder.glob("*.py")):
            if not f.stem.startswith("_") and not f.stem.startswith("."):
                discovered_py_files[f.name] = f
    if hot_tabs_folder.is_dir():
        for f in sorted(hot_tabs_folder.glob("*.py")):
            if not f.stem.startswith("_") and not f.stem.startswith("."):
                discovered_py_files[f.name] = f

    # ── .PY files ────────────────────────────────────────────
    for py_file in sorted(discovered_py_files.values(), key=lambda p: p.name):
        name = py_file.stem
        try:
            mod_key = f"tabs.{name}"
            if reload and mod_key in sys.modules:
                try:
                    mod = importlib.reload(sys.modules[mod_key])
                except Exception:
                    spec = importlib.util.spec_from_file_location(mod_key, str(py_file))
                    if spec is None or spec.loader is None: continue
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[mod_key] = mod
                    spec.loader.exec_module(mod)
            else:
                spec = importlib.util.spec_from_file_location(mod_key, str(py_file))
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                sys.modules[mod_key] = mod
                spec.loader.exec_module(mod)

            if not hasattr(mod, "TAB_TITLE"):
                print(f"[PLUGIN] SKIP {name}.py — TAB_TITLE nahi hai"); continue
            if not hasattr(mod, "create") or not callable(mod.create):
                print(f"[PLUGIN] SKIP {name}.py — create() nahi hai"); continue

            color = getattr(mod, "TAB_COLOR", None)
            if color is None:
                color = _DEFAULT_COLORS[color_idx % len(_DEFAULT_COLORS)]; color_idx += 1

            group = getattr(mod, "TAB_GROUP", "")
            plugins.append(TabPlugin(
                module_name=name, title=getattr(mod, "TAB_TITLE", name),
                order=getattr(mod, "TAB_ORDER", 50), group=group,
                color=color, icon=getattr(mod, "TAB_ICON", ""),
                lazy=getattr(mod, "LAZY_LOAD", True),
                create_fn=mod.create, source_path=str(py_file),
            ))
            g = f", group={group}" if group else ""
            _safe_print(f"[PLUGIN] [OK] {name}.py -> \"{getattr(mod, 'TAB_TITLE', name)}\" (order={getattr(mod, 'TAB_ORDER', 50)}{g})")
        except Exception:
            _safe_print(f"[PLUGIN] [X] {name}.py FAIL:"); traceback.print_exc()

    # ── .HTML files ──────────────────────────────────────────
    for html_file in sorted(folder.glob("*.html")):
        name = html_file.stem
        if name.startswith("_") or name.startswith("."):
            continue
        try:
            meta = _parse_html_metadata(html_file)
            raw_name = name.replace("_", " ").replace("-", " ").title()
            title = meta.get("TITLE", f"📄  {raw_name}")
            order = int(meta.get("ORDER", "50"))
            group = meta.get("GROUP", "")
            icon  = meta.get("ICON", "📄")
            color_str = meta.get("COLOR", "")
            if color_str and "," in color_str:
                parts = [c.strip() for c in color_str.split(",")]
                color = (parts[0], parts[1])
            # If a python plugin with similar title or stem already exists, skip duplicate html
            existing_titles = [re.sub(r'[^a-zA-Z0-9]', '', p.title.lower()) for p in plugins]
            check_title = re.sub(r'[^a-zA-Z0-9]', '', title.lower())
            if any(check_title in t or t in check_title for t in existing_titles):
                continue

            plugins.append(TabPlugin(
                module_name=name, title=title, order=order, group=group,
                color=color, icon=icon, lazy=True,
                create_fn=_make_html_create_fn(html_file), source_path=str(html_file),
            ))
            g = f", group={group}" if group else ""
            _safe_print(f"[PLUGIN] [OK] {name}.html -> \"{title}\" (order={order}{g})")
        except Exception:
            _safe_print(f"[PLUGIN] [X] {name}.html FAIL:"); traceback.print_exc()

    plugins.sort(key=lambda p: (p.order, p.title))
    print(f"[PLUGIN] {len(plugins)} tab(s) discovered")
    return plugins


# ═══════════════════════════════════════════════════════════════
# STUDIO SCROLLABLE TABVIEW & MODERN NAVIGATION SYSTEM
# ═══════════════════════════════════════════════════════════════

TAB_CUSTOM_COLORS = {
    # Row 1
    "RECAP STUDIO": {"bg": "#0e7490", "hover": "#155e75", "text": "#ffffff", "border": "#38bdf8", "active_bg": "#0284c7"},
    "STORY IMAGE VIDEO": {"bg": "#3730a3", "hover": "#312e81", "text": "#ffffff", "border": "#818cf8", "active_bg": "#4f46e5"},
    "QUEUE": {"bg": "#581c87", "hover": "#3b0764", "text": "#ffffff", "border": "#c084fc", "active_bg": "#7e22ce"},
    "JESUS PRAYER": {"bg": "#6b21a8", "hover": "#581c87", "text": "#ffffff", "border": "#d8b4fe", "active_bg": "#9333ea"},
    "IMAGE TO VIDEO": {"bg": "#065f46", "hover": "#064e3b", "text": "#ffffff", "border": "#34d399", "active_bg": "#059669"},
    "SUFFIX TOOL": {"bg": "#4c1d95", "hover": "#2e1065", "text": "#ffffff", "border": "#a78bfa", "active_bg": "#6d28d9"},

    # Row 2
    "SHORTS": {"bg": "#9a3412", "hover": "#7c2d12", "text": "#ffffff", "border": "#fb923c", "active_bg": "#ea580c"},
    "RHYMES": {"bg": "#9d174d", "hover": "#831843", "text": "#ffffff", "border": "#f472b6", "active_bg": "#db2777"},
    "YOUTUBE DATA FETCHER": {"bg": "#991b1b", "hover": "#7f1d1d", "text": "#ffffff", "border": "#f87171", "active_bg": "#dc2626"},
    "PROMPT DRIVE": {"bg": "#1e40af", "hover": "#1e3a8a", "text": "#ffffff", "border": "#60a5fa", "active_bg": "#2563eb"},
    "CHARACTER PROMPT FILLER": {"bg": "#155e75", "hover": "#164e63", "text": "#ffffff", "border": "#22d3ee", "active_bg": "#0891b2"},
    "MUSIC": {"bg": "#831843", "hover": "#701a75", "text": "#ffffff", "border": "#fb7185", "active_bg": "#be185d"},
    "STORIES": {"bg": "#0369a1", "hover": "#075985", "text": "#ffffff", "border": "#38bdf8", "active_bg": "#0284c7"},
    "SUNO MUSIC": {"bg": "#831843", "hover": "#500724", "text": "#ffffff", "border": "#f472b6", "active_bg": "#db2777"},
    "LIVE STREAM": {"bg": "#991b1b", "hover": "#450a0a", "text": "#ffffff", "border": "#fca5a5", "active_bg": "#ef4444"},
}

TAB_COLOR_PALETTES = list(TAB_CUSTOM_COLORS.values())


class StudioScrollableTabview(ctk.CTkFrame):
    """
    Ultra-Modern Master Studio Sidebar Navigation System.
    - Left Sidebar (270px) with Categorized Sections, Emojis & Glowing Active Pills.
    - Full-Viewport Main Area on the Right (100% Real Features, Timelines, Trimmers, Controls).
    - Buttery-Smooth Switching & Persistent State Tracking.
    """
    def __init__(self, parent, fg_color="#070a14", corner_radius=0, **kwargs):
        super().__init__(parent, fg_color=fg_color, corner_radius=corner_radius, **kwargs)
        self.grid_columnconfigure(0, weight=0)  # Left Sidebar
        self.grid_columnconfigure(1, weight=1)  # Main Content Viewport
        self.grid_rowconfigure(0, weight=1)

        self._active_tab = None
        self._command = None
        self._tabs = {}  # title -> {frame, btn, color, ...}
        self._tab_order = []

        # ── Left Sidebar Container (285px) ───────────────────────────────────
        self.sidebar = ctk.CTkFrame(
            self,
            width=285,
            fg_color="#0c101d",
            corner_radius=0,
            border_width=1,
            border_color="#1e283f"
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_rowconfigure(1, weight=1)
        self.sidebar.grid_columnconfigure(0, weight=1)

        # ── Sidebar Brand Header ──
        brand_card = ctk.CTkFrame(self.sidebar, fg_color="transparent", height=58)
        brand_card.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        brand_card.grid_propagate(False)

        logo_box = ctk.CTkFrame(brand_card, width=36, height=36, fg_color="#4f46e5", corner_radius=8)
        logo_box.pack(side="left", padx=(0, 10))
        ctk.CTkLabel(logo_box, text="⚡", font=("Segoe UI", 18)).pack(expand=True)

        brand_text_box = ctk.CTkFrame(brand_card, fg_color="transparent")
        brand_text_box.pack(side="left", fill="both", expand=True)

        ctk.CTkLabel(brand_text_box, text="ALL-TOOLS STUDIO", font=("Segoe UI", 13, "bold"), text_color="#f8fafc").pack(anchor="w")
        ctk.CTkLabel(brand_text_box, text="v3.0 Ultra Suite", font=("Segoe UI", 10), text_color="#94a3b8").pack(anchor="w")

        # ── Scrollable Tab Buttons Area ──
        self.nav_scroll = ctk.CTkScrollableFrame(
            self.sidebar,
            fg_color="transparent",
            corner_radius=0
        )
        self.nav_scroll.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 10))
        self.nav_scroll.grid_columnconfigure(0, weight=1)

        # ── Main Content Area on the Right ──────────────────────────────────
        self.content_area = ctk.CTkFrame(self, fg_color="#070a14", corner_radius=0)
        self.content_area.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        self.content_area.grid_columnconfigure(0, weight=1)
        self.content_area.grid_rowconfigure(0, weight=1)

    def _format_tab_btn_text(self, t_name: str, is_active: bool = False) -> str:
        clean = t_name.strip().upper()
        return f"  {clean}"

    def _get_tab_font(self, t_name: str, is_active: bool = False) -> tuple:
        # Responsive Impact font size covering the button nicely
        length = len(t_name.strip())
        if length <= 14:
            sz = 14 if is_active else 13
        elif length <= 20:
            sz = 13 if is_active else 12
        elif length <= 25:
            sz = 12 if is_active else 11
        else:
            sz = 11 if is_active else 10
        return ("Impact", sz)

    def _relayout_tabs(self):
        for widget in self.nav_scroll.winfo_children():
            try: widget.destroy()
            except Exception: pass

        sections = {
            "AI VIDEO STUDIOS": ["STORIES", "RECAP", "SUNO", "IMAGE TO VIDEO", "SHORTS"],
            "AUDIO & CREATIVE ENGINES": ["MUSIC", "RHYMES", "PRAYER", "SONG VIDEO"],
            "UTILITIES & CLOUD": ["QUEUE", "PROMPT", "CHARACTER", "FETCH", "SUFFIX"]
        }

        created_sections = set()
        row_counter = 0

        for t_name in self._tab_order:
            t_data = self._tabs[t_name]
            upper_name = t_name.upper()

            # Determine section
            current_sec = "AI VIDEO STUDIOS"
            for sec_name, keywords in sections.items():
                if any(kw in upper_name for kw in keywords):
                    current_sec = sec_name
                    break

            if current_sec not in created_sections:
                created_sections.add(current_sec)
                sec_lbl = ctk.CTkLabel(
                    self.nav_scroll,
                    text=current_sec,
                    font=("Segoe UI", 9, "bold"),
                    text_color="#64748b"
                )
                sec_lbl.pack(anchor="w", padx=10, pady=(12, 4))

            is_active = (t_name == self._active_tab)
            palette = t_data["palette"]
            btn_text = self._format_tab_btn_text(t_name, is_active)
            btn_font = self._get_tab_font(t_name, is_active)

            if is_active:
                fg_col = palette["active_bg"]
                txt_col = "#ffffff"
                border_col = "#000000"
                border_w = 2.5
                h_col = palette["hover"]
            else:
                fg_col = "#101726"
                txt_col = "#ffffff"
                border_col = "#000000"
                border_w = 2
                h_col = "#1e293b"

            btn = ctk.CTkButton(
                self.nav_scroll,
                text=btn_text,
                anchor="w",
                height=44,
                font=btn_font,
                fg_color=fg_col,
                hover_color=h_col,
                text_color=txt_col,
                border_width=border_w,
                border_color=border_col,
                corner_radius=10,
                cursor="hand2",
                command=lambda t=t_name: self.set(t)
            )
            btn.pack(fill="x", padx=4, pady=3.5)
            t_data["btn"] = btn

    def add(self, title, color=None, is_group=False, group_items=None, on_sub_select=None):
        if title in self._tabs:
            return self._tabs[title]["frame"]

        page_frame = ctk.CTkFrame(self.content_area, fg_color="transparent")
        page_frame.grid_columnconfigure(0, weight=1)
        page_frame.grid_rowconfigure(0, weight=1)

        norm_title = title.upper()
        matched_palette = None
        for k, v in TAB_CUSTOM_COLORS.items():
            if k in norm_title or any(w in norm_title for w in k.split()):
                matched_palette = v
                break

        if not matched_palette:
            idx = len(self._tab_order) % len(TAB_COLOR_PALETTES)
            matched_palette = TAB_COLOR_PALETTES[idx]

        if color:
            c1 = color[0] if isinstance(color, (tuple, list)) else color
            matched_palette = {"bg": c1, "hover": c1, "text": "#ffffff", "border": "#3b82f6", "active_bg": c1}

        self._tabs[title] = {
            "frame": page_frame,
            "palette": matched_palette,
            "base_color": matched_palette["bg"],
            "title": title,
            "is_group": is_group,
            "group_items": group_items or [],
            "on_sub_select": on_sub_select
        }
        self._tab_order.append(title)

        if self._active_tab is None:
            self._active_tab = title
            page_frame.grid(row=0, column=0, sticky="nsew")

        self._relayout_tabs()
        return page_frame

    def tab(self, title):
        if title in self._tabs:
            return self._tabs[title]["frame"]
        return self.add(title)

    def set(self, title):
        if title not in self._tabs:
            return

        old_title = self._active_tab
        if old_title == title:
            # Already active — still trigger command if needed
            if callable(self._command):
                try: self._command()
                except Exception: pass
            return

        self._active_tab = title

        # Fast 2-widget diffing instead of looping through all 16 tabs
        if old_title and old_title in self._tabs:
            old_data = self._tabs[old_title]
            try:
                old_data["frame"].grid_remove()
            except Exception:
                old_data["frame"].grid_forget()
            if "btn" in old_data and old_data["btn"].winfo_exists():
                old_data["btn"].configure(
                    text=self._format_tab_btn_text(old_title, is_active=False),
                    fg_color="#101726",
                    hover_color="#1e293b",
                    text_color="#ffffff",
                    border_width=2,
                    border_color="#000000",
                    font=self._get_tab_font(old_title, is_active=False)
                )

        new_data = self._tabs[title]
        new_data["frame"].grid(row=0, column=0, sticky="nsew")
        if "btn" in new_data and new_data["btn"].winfo_exists():
            new_palette = new_data["palette"]
            new_data["btn"].configure(
                text=self._format_tab_btn_text(title, is_active=True),
                fg_color=new_palette["active_bg"],
                hover_color=new_palette["hover"],
                text_color="#ffffff",
                border_width=2.5,
                border_color="#000000",
                font=self._get_tab_font(title, is_active=True)
            )

        # Force immediate visual update so clicking is instantaneous (<1ms)
        try:
            self.update_idletasks()
        except Exception:
            pass

        # Execute command asynchronously on next tick to prevent locking the click event
        if callable(self._command):
            def _deferred_cmd():
                try:
                    self._command()
                except Exception:
                    pass
            self.after(10, _deferred_cmd)

    def get(self):
        return self._active_tab

    def configure(self, **kwargs):
        if "command" in kwargs:
            self._command = kwargs.pop("command")
        super().configure(**kwargs)


# ═══════════════════════════════════════════════════════════════
# MOUNT
# ═══════════════════════════════════════════════════════════════
def mount_tabs(tabview, plugins: list[TabPlugin], boot_data: dict = None,
               theme_colors: dict = None):
    """
    Universal Tab Mounting Engine for StoriesStudio:
    - Automatically structures top-level and grouped sub-tabs (e.g. 🎵 Music Master Tab).
    - Injects modern sub-navigation pills and dropdown menus.
    - Lazy loads tabs smoothly on initial activation.
    """
    import customtkinter as ctk

    boot_data = boot_data or {}
    C = theme_colors or {}

    top_level = [p for p in plugins if not p.group]
    groups: dict[str, list[TabPlugin]] = {}
    for p in plugins:
        if p.group:
            groups.setdefault(p.group, []).append(p)

    mounted = {}
    mount_fns = {}

    def _mount_plugin_frame(plugin, target_frame):
        mounted[plugin.title] = False

        def _do_mount():
            if mounted.get(plugin.title): return
            loading_card = None
            try:
                loading_card = ctk.CTkFrame(target_frame, fg_color="#0b1020", corner_radius=12, border_width=1, border_color="#1e293b")
                loading_card.place(relx=0.5, rely=0.5, anchor="center")
                ctk.CTkLabel(
                    loading_card,
                    text=f"⚡ Initializing {plugin.title}...",
                    font=("Segoe UI", 12, "bold"),
                    text_color="#38bdf8"
                ).pack(padx=28, pady=16)
                target_frame.update_idletasks()
            except Exception:
                pass

            try:
                plugin.create_fn(target_frame, boot_data)
                mounted[plugin.title] = True
                plugin._mounted = True
                print(f"[PLUGIN] mounted: {plugin.title}")
            except Exception:
                print(f"[PLUGIN] mount FAIL: {plugin.title}")
                traceback.print_exc()
                lbl = ctk.CTkLabel(target_frame,
                    text=f"⚠️ {plugin.title} load fail\n\n{traceback.format_exc()[:500]}",
                    text_color="#fb7185", font=("Consolas", 11),
                    wraplength=600, justify="left"
                )
                try: lbl.pack(expand=True, fill="both", padx=20, pady=20)
                except Exception:
                    try: lbl.grid(row=0, column=0, padx=20, pady=20)
                    except Exception: pass
                mounted[plugin.title] = True
            finally:
                if loading_card:
                    try: loading_card.destroy()
                    except Exception: pass
        if not plugin.lazy:
            _do_mount()
        return _do_mount

    all_lazy_tasks = []

    # ── 1. Top-Level Tabs ────────────────────────────────────
    for p in top_level:
        if hasattr(tabview, "add"):
            tab_frame = tabview.add(p.title, color=p.color)
        else:
            tab_frame = tabview.tab(p.title)
        tab_frame.grid_columnconfigure(0, weight=1)
        tab_frame.grid_rowconfigure(0, weight=1)
        m_fn = _mount_plugin_frame(p, tab_frame)
        mount_fns[p.title] = m_fn
        all_lazy_tasks.append((p.title, m_fn))

    # ── 2. Grouped Master Tabs (e.g. 🎵 Music Tools) ─────────
    def _mount_single_group(group_name, gp):
        first = gp[0]
        group_icon = first.icon or _GROUP_ICONS.get(group_name, "🎵")
        group_tab_title = f"{group_icon}  {group_name}"

        # Sub-tab selector callback with isolated closure scope
        sub_mount_map = {}
        sub_frames = {}
        sub_pills = {}
        active_sub_ref = [gp[0].title]

        def _switch_sub_tab(sub_title, mount=True):
            active_sub_ref[0] = sub_title
            accent_col = first.color[0] if isinstance(first.color, (list, tuple)) else (first.color or "#f43f5e")
            for st, sf in sub_frames.items():
                if st == sub_title:
                    sf.grid(row=1, column=0, sticky="nsew")
                    if st in sub_pills:
                        sub_pills[st].configure(
                            fg_color="#1e293b",
                            text_color="#ffffff",
                            border_width=2,
                            border_color=accent_col
                        )
                else:
                    sf.grid_forget()
                    if st in sub_pills:
                        sub_pills[st].configure(
                            fg_color="#12182c",
                            text_color="#94a3b8",
                            border_width=1,
                            border_color="#243054"
                        )
            try:
                group_frame.update_idletasks()
            except Exception:
                pass

            if mount:
                fn = sub_mount_map.get(sub_title)
                if fn:
                    group_frame.after(10, fn)

        if hasattr(tabview, "add"):
            group_frame = tabview.add(
                group_tab_title,
                color=first.color,
                is_group=True,
                group_items=gp,
                on_sub_select=lambda t: _switch_sub_tab(t, mount=True)
            )
        else:
            group_frame = tabview.tab(group_tab_title)

        group_frame.grid_columnconfigure(0, weight=1)
        group_frame.grid_rowconfigure(0, weight=0)
        group_frame.grid_rowconfigure(1, weight=1)

        # ── Group Sub-Navigation Header Bar ──
        sub_nav_bar = ctk.CTkFrame(
            group_frame,
            fg_color="#0b1020",
            height=46,
            corner_radius=10,
            border_width=1,
            border_color="#1a243e"
        )
        sub_nav_bar.grid(row=0, column=0, sticky="ew", padx=6, pady=(4, 6))
        sub_nav_bar.grid_propagate(False)

        # Badge
        badge_box = ctk.CTkFrame(sub_nav_bar, fg_color="transparent")
        badge_box.pack(side="left", padx=12, pady=6)
        ctk.CTkLabel(
            badge_box,
            text=f"{group_icon}  {group_name.upper()} SUITE",
            font=("Segoe UI", 12, "bold"),
            text_color="#fca5a5"
        ).pack(side="left")

        # Sub-pills
        pills_box = ctk.CTkFrame(sub_nav_bar, fg_color="transparent")
        pills_box.pack(side="right", padx=10, pady=4)

        for sp in gp:
            s_frame = ctk.CTkFrame(group_frame, fg_color="transparent")
            s_frame.grid_columnconfigure(0, weight=1)
            s_frame.grid_rowconfigure(0, weight=1)
            sub_frames[sp.title] = s_frame

            pill_btn = ctk.CTkButton(
                pills_box,
                text=sp.title,
                height=32,
                font=("Segoe UI", 11, "bold"),
                fg_color="#12182c",
                hover_color="#1e274a",
                text_color="#94a3b8",
                border_width=1,
                border_color="#243054",
                corner_radius=8,
                command=lambda t=sp.title, sw=_switch_sub_tab: sw(t, mount=True)
            )
            pill_btn.pack(side="left", padx=4)
            sub_pills[sp.title] = pill_btn

            s_mount = _mount_plugin_frame(sp, s_frame)
            sub_mount_map[sp.title] = s_mount
            all_lazy_tasks.append((sp.title, s_mount))

        # Pre-position first sub-tab layout without eagerly forcing lazy mount at boot
        _switch_sub_tab(gp[0].title, mount=False)

        def _mount_group_first(_switch=_switch_sub_tab, _ref=active_sub_ref):
            _switch(_ref[0], mount=True)
        mount_fns[group_tab_title] = _mount_group_first

    for group_name, gp in groups.items():
        _mount_single_group(group_name, gp)

    # ── 3. Top-level activation ──────────────────────────────
    def _on_tab_change():
        try:
            fn = mount_fns.get(tabview.get())
            if fn: fn()
        except Exception:
            pass
    tabview.configure(command=_on_tab_change)

    if top_level and top_level[0].lazy:
        mount_fns[top_level[0].title]()

    # ── 4. Progressive Idle Pre-Warming (Makhan Smoothness) ────
    # In background, progressively mounts all remaining tabs during idle cycles.
    # Result: User never experiences a freeze or lag on click!
    _prewarm_idx = [0]
    def _prewarm_tick():
        if _prewarm_idx[0] < len(all_lazy_tasks):
            t_name, t_fn = all_lazy_tasks[_prewarm_idx[0]]
            _prewarm_idx[0] += 1
            try:
                if not mounted.get(t_name):
                    t_fn()
            except Exception:
                pass
            if _prewarm_idx[0] < len(all_lazy_tasks) and hasattr(tabview, "after"):
                try:
                    tabview.after(800, _prewarm_tick)
                except Exception:
                    pass

    if hasattr(tabview, "after"):
        try:
            tabview.after(1500, _prewarm_tick)
        except Exception:
            pass

    return mount_fns

