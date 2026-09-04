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

    # Add all potential root locations to sys.path so modules like Master_Tool, preset_manager, voice_cache can be imported
    for p in reversed([
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

    # Always ensure HOT_PATCH_DIR is at index 0 of sys.path
    _appdata = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or os.path.expanduser("~")
    hot_patch_root = os.path.join(_appdata, "StoriesStudio", "hot_patches")
    if os.path.isdir(hot_patch_root):
        if hot_patch_root in sys.path:
            sys.path.remove(hot_patch_root)
        sys.path.insert(0, hot_patch_root)

    plugins: list[TabPlugin] = []
    color_idx = 0

    # ── .PY files (Check base folder + hot_patches/tabs override) ──
    hot_tabs_dir = Path(hot_patch_root) / "tabs"
    all_py_files: dict[str, Path] = {}
    if folder.is_dir():
        for f in folder.glob("*.py"):
            all_py_files[f.name] = f
    if hot_tabs_dir.is_dir():
        for f in hot_tabs_dir.glob("*.py"):
            all_py_files[f.name] = f  # Hot-patch takes precedence

    for fname in sorted(all_py_files.keys()):
        py_file = all_py_files[fname]
        name = py_file.stem
        if name.startswith("_") or name.startswith("."):
            continue
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

# ═══════════════════════════════════════════════════════════════
# 🎭 HARMONIC DEEP DUOTONE PALETTES (Option 5 — Arc / Designer Studio)
# ═══════════════════════════════════════════════════════════════

TAB_CUSTOM_COLORS = {
    # Row 1 — Deep Jewels
    "STORIES": {
        "bg": "#0f1a2e", "hover": "#172744", "text": "#e0f2fe",
        "border": "#1d4ed8", "active_bg": "#1e3a8a", "active_border": "#60a5fa"
    },
    "RECAP STUDIO": {
        "bg": "#0c2024", "hover": "#13343a", "text": "#ccfbf1",
        "border": "#0f766e", "active_bg": "#115e59", "active_border": "#2dd4bf"
    },
    "STORY IMAGE VIDEO": {
        "bg": "#141836", "hover": "#1f2552", "text": "#e0e7ff",
        "border": "#4338ca", "active_bg": "#3730a3", "active_border": "#a5b4fc"
    },
    "QUEUE": {
        "bg": "#1c1236", "hover": "#2c1d54", "text": "#f3e8ff",
        "border": "#7e22ce", "active_bg": "#581c87", "active_border": "#c084fc"
    },
    "JESUS PRAYER": {
        "bg": "#181033", "hover": "#281b52", "text": "#faf5ff",
        "border": "#6b21a8", "active_bg": "#4c1d95", "active_border": "#d8b4fe"
    },
    "IMAGE TO VIDEO": {
        "bg": "#0d241c", "hover": "#14392c", "text": "#d1fae5",
        "border": "#047857", "active_bg": "#065f46", "active_border": "#34d399"
    },
    "SUFFIX TOOL": {
        "bg": "#221236", "hover": "#361c54", "text": "#fae8ff",
        "border": "#86198f", "active_bg": "#701a75", "active_border": "#e879f9"
    },

    # Row 2 — Warm & Vivid Jewels
    "SHORTS": {
        "bg": "#26160c", "hover": "#3c2313", "text": "#fef3c7",
        "border": "#b45309", "active_bg": "#78350f", "active_border": "#fbbf24"
    },
    "RHYMES": {
        "bg": "#26101c", "hover": "#3c192c", "text": "#fce7f3",
        "border": "#be185d", "active_bg": "#831843", "active_border": "#f472b6"
    },
    "YOUTUBE DATA FETCHER": {
        "bg": "#260e12", "hover": "#3c161c", "text": "#fee2e2",
        "border": "#b91c1c", "active_bg": "#7f1d1d", "active_border": "#f87171"
    },
    "PROMPT DRIVE": {
        "bg": "#0f1d33", "hover": "#172c4c", "text": "#e0f2fe",
        "border": "#0369a1", "active_bg": "#075985", "active_border": "#38bdf8"
    },
    "CHARACTER PROMPT FILLER": {
        "bg": "#0a222a", "hover": "#103642", "text": "#cffafe",
        "border": "#0e7490", "active_bg": "#155e75", "active_border": "#22d3ee"
    },
    "MUSIC": {
        "bg": "#260d16", "hover": "#3c1422", "text": "#ffe4e6",
        "border": "#be123c", "active_bg": "#881337", "active_border": "#fb7185"
    },
}

TAB_COLOR_PALETTES = list(TAB_CUSTOM_COLORS.values())


# ── Black Stroke Text Image Cache Helper ────────────────────────────────────
_STROKE_IMG_CACHE = {}

def _get_stroke_text_image(text: str, font_size: int = 14, text_color: str = "#ffffff", stroke_color: str = "#000000", stroke_width: int = 2):
    cache_key = (text, font_size, text_color, stroke_color, stroke_width)
    if cache_key in _STROKE_IMG_CACHE:
        return _STROKE_IMG_CACHE[cache_key]

    try:
        from PIL import Image, ImageDraw, ImageFont
        try:
            font = ImageFont.truetype("impact.ttf", font_size)
        except Exception:
            try: font = ImageFont.truetype("arialbd.ttf", font_size)
            except Exception: font = ImageFont.load_default()

        dummy_img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        dummy_draw = ImageDraw.Draw(dummy_img)
        bbox = dummy_draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)

        pad_x = 3
        pad_y = 2
        w = max(1, (bbox[2] - bbox[0]) + pad_x * 2)
        h = max(1, (bbox[3] - bbox[1]) + pad_y * 2)

        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        x = pad_x - bbox[0]
        y = pad_y - bbox[1]

        draw.text((x, y), text, font=font, fill=text_color, stroke_width=stroke_width, stroke_fill=stroke_color)
        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(w, h))
        _STROKE_IMG_CACHE[cache_key] = (ctk_img, w, h)
        return ctk_img, w, h
    except Exception:
        return None, 100, 32


class StudioScrollableTabview(ctk.CTkFrame):
    """
    Ultra-Modern Scalable & Multi-Row Tab Navigation System.
    - Single-Line Snug Content-Fitted Tab Buttons with Crisp Black Stroke Outline.
    - Real-time Tactile Press Down & Glow Effects on Click.
    - Persistent Session State Tracking.
    """
    def __init__(self, parent, fg_color="#070a14", corner_radius=10, **kwargs):
        super().__init__(parent, fg_color=fg_color, corner_radius=corner_radius, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._active_tab = None
        self._command = None
        self._tabs = {}  # title -> {frame, btn, color, base_color, is_group, group_items, ...}
        self._tab_order = []  # List of tab titles in insertion order
        self._row_frames = []
        self._last_width = 0

        # ── Header Navigation Bar (Multi-Row Container) ─────────────────────────
        self.header_bar = ctk.CTkFrame(
            self,
            fg_color="#080d1a",
            corner_radius=14,
            border_width=1,
            border_color="rgba(120,160,255,0.18)" if sys.platform != "win32" else "#1e283f"
        )
        self.header_bar.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 6))
        self.header_bar.grid_columnconfigure(0, weight=1)
        self.header_bar.bind("<Configure>", self._on_header_configure)

        # ── Main Content Area ──────────────────────────────────────────────────
        self.content_area = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.content_area.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self.content_area.grid_columnconfigure(0, weight=1)
        self.content_area.grid_rowconfigure(0, weight=1)

    @staticmethod
    def _format_tab_title(raw_title: str, is_group: bool = False) -> str:
        text = raw_title.strip().upper()
        return f"{text} ▾" if is_group else text

    def _on_header_configure(self, event):
        if not event or event.width <= 50:
            return
        if abs(event.width - self._last_width) > 30:
            self._last_width = event.width
            self._relayout_tabs(event.width)

    def _relayout_tabs(self, width=None):
        if not self._tab_order:
            return

        w = width or self.header_bar.winfo_width()
        if w <= 100:
            w = 1280

        tab_count = len(self._tab_order)

        if tab_count <= 6:
            num_rows = 1
        elif w < 850 or tab_count > 16:
            num_rows = 3
        else:
            num_rows = 2

        base_per_row = tab_count // num_rows
        rem = tab_count % num_rows
        row_counts = [base_per_row + (1 if r < rem else 0) for r in range(num_rows)]

        for rf in self._row_frames:
            try: rf.destroy()
            except Exception: pass
        self._row_frames = []

        tab_idx = 0
        for r, count in enumerate(row_counts):
            if count <= 0: continue
            rf = ctk.CTkFrame(self.header_bar, fg_color="transparent")
            rf.pack(fill="x", pady=2)
            self._row_frames.append(rf)

            # Centered container for buttons
            inner = ctk.CTkFrame(rf, fg_color="transparent")
            inner.pack(anchor="center")

            for col in range(count):
                if tab_idx < tab_count:
                    t_name = self._tab_order[tab_idx]
                    t_data = self._tabs[t_name]

                    is_active = (t_name == self._active_tab)
                    palette = t_data["palette"]

                    fg = palette.get("active_bg", "#2563eb") if is_active else palette.get("bg", "#0b1222")
                    b_width = 3 if is_active else 1
                    b_color = palette.get("active_border", "#ffffff") if is_active else palette.get("border", "#334155")

                    disp_text = t_data["display_text"]
                    ctk_img, img_w, img_h = _get_stroke_text_image(disp_text, font_size=14, text_color="#ffffff", stroke_color="#000000", stroke_width=2)
                    btn_width = max(img_w + 16, 50)

                    btn = ctk.CTkButton(
                        inner,
                        text="",
                        image=ctk_img,
                        width=btn_width,
                        height=36,
                        fg_color=fg,
                        hover_color=palette["active_bg"] if is_active else palette.get("hover", "#162038"),
                        border_width=b_width,
                        border_color=b_color,
                        corner_radius=8,
                        command=lambda t=t_name: self.set(t)
                    )
                    btn.pack(side="left", padx=3, pady=1)

                    # ── Tactile Press Down Effect ──
                    def _make_press_handlers(_btn, _t_name):
                        def _press(e):
                            _btn.configure(border_color="#ffffff", border_width=3)
                        def _release(e):
                            is_act = (_t_name == self._active_tab)
                            p = self._tabs.get(_t_name, {}).get("palette", {})
                            b_col = p.get("active_border", "#ffffff") if is_act else p.get("border", "#334155")
                            b_w = 3 if is_act else 1
                            _btn.configure(border_color=b_col, border_width=b_w)
                        return _press, _release

                    _on_pr, _on_rel = _make_press_handlers(btn, t_name)
                    btn.bind("<Button-1>", _on_pr, add="+")
                    btn.bind("<ButtonRelease-1>", _on_rel, add="+")

                    if t_data.get("is_group") and t_data.get("group_items"):
                        def _show_group_menu(event, _btn=btn, _items=t_data["group_items"], _cb=t_data.get("on_sub_select")):
                            try:
                                from lazy_menu import LazyDropdownMenu
                                menu = LazyDropdownMenu(_btn)
                                for item in _items:
                                    title_sub = item.title if hasattr(item, "title") else str(item)
                                    menu.add_command(label=title_sub, command=lambda s=title_sub: _cb(s) if _cb else None)
                                menu.show(event.x_root, event.y_root)
                            except Exception:
                                pass
                        btn.bind("<Button-3>", _show_group_menu)

                    t_data["btn"] = btn
                    tab_idx += 1

    def add(self, title, color=None, is_group=False, group_items=None, on_sub_select=None):
        if title in self._tabs:
            return self._tabs[title]["frame"]

        page_frame = ctk.CTkFrame(self.content_area, fg_color="transparent")
        page_frame.grid_columnconfigure(0, weight=1)
        page_frame.grid_rowconfigure(0, weight=1)

        # Match custom color by tab keyword if available
        norm_title = title.upper()
        matched_palette = None
        for k, v in TAB_CUSTOM_COLORS.items():
            if k in norm_title or any(w in norm_title for w in k.split()):
                matched_palette = dict(v)
                break

        if not matched_palette:
            idx = len(self._tab_order) % len(TAB_COLOR_PALETTES)
            matched_palette = dict(TAB_COLOR_PALETTES[idx])

        if color:
            c1 = color[0] if isinstance(color, (tuple, list)) else color
            matched_palette = {
                "bg": "#0b1222",
                "hover": "#162038",
                "text": "#ffffff",
                "border": c1,
                "active_bg": c1,
                "active_border": "#ffffff"
            }

        display_text = self._format_tab_title(title, is_group)

        self._tabs[title] = {
            "frame": page_frame,
            "palette": matched_palette,
            "base_color": matched_palette["bg"],
            "title": title,
            "display_text": display_text,
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

        prev_tab = self._active_tab
        if prev_tab == title:
            return

        self._active_tab = title

        # 1. Un-grid previous tab and restore its inactive button state ($O(1)$ instant)
        if prev_tab and prev_tab in self._tabs:
            p_data = self._tabs[prev_tab]
            p_pal = p_data["palette"]
            p_data["frame"].grid_forget()
            if "btn" in p_data and p_data["btn"].winfo_exists():
                p_data["btn"].configure(
                    fg_color=p_pal.get("bg", "#0b1222"),
                    hover_color=p_pal.get("hover", "#162038"),
                    border_width=1,
                    border_color=p_pal.get("border", "#334155"),
                )

        # 2. Show active tab and illuminate its button state (Radiant 3px Glowing Outline)
        c_data = self._tabs[title]
        c_pal = c_data["palette"]
        c_data["frame"].grid(row=0, column=0, sticky="nsew")
        if "btn" in c_data and c_data["btn"].winfo_exists():
            c_data["btn"].configure(
                fg_color=c_pal.get("active_bg", "#2563eb"),
                hover_color=c_pal.get("active_bg", "#2563eb"),
                border_width=3,
                border_color=c_pal.get("active_border", "#ffffff"),
            )

        # 3. Non-blocking background session state save
        try:
            import system_monitor
            system_monitor.save_session_state({"active_tab": title})
        except Exception:
            pass
            pass

        # 4. Trigger tab activation callback
        if callable(self._command):
            try:
                self._command()
            except Exception:
                pass

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
    - Lazy loads tabs smoothly on initial activation without freezing GUI thread.
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
        def _do_mount():
            if mounted.get(plugin.title): return
            try:
                for child in target_frame.winfo_children():
                    try: child.destroy()
                    except Exception: pass

                plugin.create_fn(target_frame, boot_data)
                mounted[plugin.title] = True
                plugin._mounted = True
                try: target_frame.update_idletasks()
                except Exception: pass
                print(f"[PLUGIN] mounted: {plugin.title}")
            except Exception as exc:
                print(f"[PLUGIN] mount FAIL: {plugin.title}")
                traceback.print_exc()
                try:
                    import system_health
                    system_health.HEALTH.report_error(plugin.title, f"Mount error: {exc}", traceback.format_exc())
                except Exception:
                    pass
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

        def _trigger_mount():
            if mounted.get(plugin.title): return
            _do_mount()

        if not plugin.lazy:
            _do_mount()
            return _do_mount
        return _trigger_mount

    # ── 1. Top-Level Tabs ────────────────────────────────────
    for p in top_level:
        if hasattr(tabview, "add"):
            tab_frame = tabview.add(p.title, color=p.color)
        else:
            tab_frame = tabview.tab(p.title)
        tab_frame.grid_columnconfigure(0, weight=1)
        tab_frame.grid_rowconfigure(0, weight=1)
        mount_fns[p.title] = _mount_plugin_frame(p, tab_frame)

    # ── 2. Grouped Master Tabs (e.g. 🎵 Music Tools) ─────────
    for group_name, gp in groups.items():
        first = gp[0]
        group_icon = first.icon or _GROUP_ICONS.get(group_name, "🎵")
        group_tab_title = f"{group_icon}  {group_name}"

        # Sub-tab selector callback
        sub_mount_map = {}
        sub_frames = {}
        sub_pills = {}
        active_sub_ref = [gp[0].title]

        def _switch_sub_tab(sub_title):
            active_sub_ref[0] = sub_title
            for st, sf in sub_frames.items():
                if st == sub_title:
                    sf.grid(row=1, column=0, sticky="nsew")
                    if st in sub_pills:
                        sub_pills[st].configure(
                            fg_color="#1e293b",
                            text_color="#ffffff",
                            border_width=2,
                            border_color=first.color[0]
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
            fn = sub_mount_map.get(sub_title)
            if fn: fn()

        if hasattr(tabview, "add"):
            group_frame = tabview.add(
                group_tab_title,
                color=first.color,
                is_group=True,
                group_items=gp,
                on_sub_select=_switch_sub_tab
            )
        else:
            group_frame = tabview.tab(group_tab_title)

        group_frame.grid_columnconfigure(0, weight=1)
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
                command=lambda t=sp.title: _switch_sub_tab(t)
            )
            pill_btn.pack(side="left", padx=4)
            sub_pills[sp.title] = pill_btn

            sub_mount_map[sp.title] = _mount_plugin_frame(sp, s_frame)

        # Initialize first sub tab
        _switch_sub_tab(gp[0].title)

        def _mount_group_first(_g=gp, _switch=_switch_sub_tab, _ref=active_sub_ref):
            _switch(_ref[0])
        mount_fns[group_tab_title] = _mount_group_first

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

    return mount_fns

