"""
studio_card_nav.py — 3D Card Navigation, Responsive Impact Bold Text & Button Color Customizer
════════════════════════════════════════════════════════════════════════════════════════════════
1. Dynamic Responsive Impact Bold Typography:
   - Auto-fits Impact Bold font (up to 18pt) to fill the maximum height & width of each button
   - Shorter titles (Stories, Queue, Shorts, Rhymes) render with huge 18pt Impact Bold text
   - Longer titles (YouTube Data Fetcher, Character Prompt Filler) scale smoothly without clipping
   - 3D Text Drop Shadow behind letters for maximum legibility and depth
2. Button Color Customizer:
   - 8 Curated Button Accent Color Presets (Royal Blue, Neon Violet, Emerald, Gold, Ruby, Magenta, Cyan, Titanium)
   - Custom Hex Color input with Live 3D Card Preview
   - Real-time reactive updates across all tool cards
3. High-Contrast 3D Telemetry HUD in Top Bar:
   - Discrete 3D Pill Capsules with Black Drop Shadows (#000000)
   - Bold Impactful Typography with All First Letters Capitalized ("Cpu", "Ram", "Gpu", "Net", "Health")
   - High-contrast neon colors (Lime Green, Electric Cyan, Neon Violet, Mint)
4. 100% Full-Screen Responsive Architecture:
   - Nested grid weights across every container tier
   - Zero background fluctuation ($O(1)$ instant tkraise)
"""

import os
import sys
import threading
import time
from typing import Callable, Dict, List, Optional, Any, Tuple
import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

from studio_theme_engine import THEME_ENGINE, STUDIO_THEMES, BUTTON_COLOR_PRESETS
import system_monitor
import plugin_loader
from stories_engine import (
    C, GPU, _OUTPUT_PRESETS, _OUTPUT_RES_CHOICE, _set_output_res,
    _open_theme_picker, SettingsManager
)

# Active background vibrant base + Accent highlight color mapping (13 Tools)
TOOL_ACCENTS = {
    "STORIES":                 ("#1d4ed8", "#60A5FA", "#2563eb"),  # Royal Blue
    "RECAP STUDIO":            ("#0f766e", "#2DD4BF", "#0d9488"),  # Teal
    "STORY IMAGE VIDEO":       ("#4338ca", "#A5B4FC", "#4f46e5"),  # Indigo
    "QUEUE":                   ("#6b21a8", "#C084FC", "#7c3aed"),  # Deep Purple
    "JESUS PRAYER":            ("#581c87", "#D8B4FE", "#6d28d9"),  # Sacred Lavender
    "IMAGE TO VIDEO":          ("#047857", "#34D399", "#059669"),  # Emerald Green
    "SUFFIX TOOL":             ("#86198f", "#E879F9", "#a21caf"),  # Fuchsia Magenta
    "SHORTS":                  ("#b45309", "#FBBF24", "#d97706"),  # Radiant Amber
    "RHYMES":                  ("#be185d", "#F472B6", "#db2777"),  # Rose Pink
    "YOUTUBE DATA FETCHER":    ("#b91c1c", "#F87171", "#dc2626"),  # Crimson Red
    "PROMPT DRIVE":            ("#0369a1", "#38BDF8", "#0284c7"),  # Sky Blue
    "CHARACTER PROMPT FILLER": ("#0e7490", "#22D3EE", "#0891b2"),  # Deep Cyan
    "MUSIC":                   ("#be123c", "#FB7185", "#e11d48"),  # Coral Red
    "MUSIC TOOL":              ("#be123c", "#FB7185", "#e11d48"),  # Coral Red
    "SONG VIDEO MAKER":        ("#9f1239", "#FDA4AF", "#be123c"),  # Deep Rose
}

CARD_W, CARD_H = 234, 50


def _hex_rgb(h: str):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lerp_color(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _load_font(bold_names: List[str], size: int):
    for name in bold_names:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _to_title_caps(text: str) -> str:
    """Format string with All First Letters Capitalized."""
    words = text.strip().split()
    caps_words = []
    for w in words:
        if w.lower() in ("to", "and", "by", "of", "in", "on", "for") and caps_words:
            caps_words.append(w.capitalize())
        else:
            caps_words.append(w.capitalize() if not (w.isupper() and len(w) <= 3) else w)
    return " ".join(caps_words)


def _get_responsive_impact_font(text: str, max_w: int, max_h: int, max_pt: int = 18, min_pt: int = 11, scale: int = 3) -> Tuple[ImageFont.FreeTypeFont, int]:
    """
    Dynamically auto-fit Impact Bold typography to maximize size and fill the button space.
    """
    font_names = ["impact.ttf", "arialbd.ttf", "segoeuib.ttf", "trebucbd.ttf"]
    for pt in range(max_pt, min_pt - 1, -1):
        size_px = int(pt * scale)
        font = None
        for fn in font_names:
            try:
                font = ImageFont.truetype(fn, size_px)
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()
            return font, pt

        dummy_img = Image.new("RGBA", (1, 1))
        draw = ImageDraw.Draw(dummy_img)
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]

        if w <= max_w and h <= max_h:
            return font, pt

    for fn in font_names:
        try:
            return ImageFont.truetype(fn, int(min_pt * scale)), min_pt
        except Exception:
            continue
    return ImageFont.load_default(), min_pt


def bake_card_image(title: str, icon: str, accent: str, active_bg: str, is_active: bool,
                     is_hover: bool = False, width: int = CARD_W, height: int = CARD_H) -> ctk.CTkImage:
    """
    Synthesize an attractive tactile 3D Card with multi-layer black drop shadow,
    top highlight bevel, full-to-button Impact Bold responsive typography, and vivid active fills.
    """
    # Check for user-selected button color overrides
    if is_active:
        active_bg, accent = THEME_ENGINE.get_active_button_colors(active_bg, accent)

    scale = 3
    sw, sh = width * scale, height * scale
    img = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad_l = 3 * scale
    pad_t = 2 * scale
    pad_r = sw - 4 * scale
    pad_b = sh - 5 * scale
    radius = 10 * scale

    # 1. 3D Black Drop Shadow Layers
    if is_active:
        shadow_steps = [(1, 170), (2, 140), (3, 100), (4, 70), (5, 35)]
    elif is_hover:
        shadow_steps = [(1, 150), (2, 110), (3, 80), (4, 40)]
    else:
        shadow_steps = [(1, 110), (2, 80), (3, 45)]

    for s_off, s_alpha in shadow_steps:
        draw.rounded_rectangle(
            [pad_l, pad_t + s_off * scale, pad_r, pad_b + s_off * scale],
            radius=radius,
            fill=(0, 0, 0, s_alpha)
        )

    # 2. Card Body Gradient Fill
    theme = THEME_ENGINE.get_current_theme()
    act_rgb = _hex_rgb(active_bg)
    acc_rgb = _hex_rgb(accent)

    if is_active:
        top_c = _lerp_color(act_rgb, (255, 255, 255), 0.22)
        bot_c = _lerp_color(act_rgb, (0, 0, 0), 0.28)
    elif is_hover:
        h_base = _hex_rgb(theme.get("card_bottom", "#161d33"))
        top_c = _lerp_color(h_base, (255, 255, 255), 0.14)
        bot_c = _lerp_color(h_base, (0, 0, 0), 0.18)
    else:
        s_base = _hex_rgb(theme.get("sidebar_bg", "#0f1424"))
        top_c = _lerp_color(s_base, (255, 255, 255), 0.09)
        bot_c = _lerp_color(s_base, (0, 0, 0), 0.25)

    grad_img = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(grad_img)
    for y in range(pad_t, pad_b + 1):
        t = (y - pad_t) / max(1, (pad_b - pad_t))
        c = _lerp_color(top_c, bot_c, t)
        grad_draw.line([(pad_l, y), (pad_r, y)], fill=(*c, 255))

    mask_img = Image.new("L", (sw, sh), 0)
    mask_draw = ImageDraw.Draw(mask_img)
    mask_draw.rounded_rectangle([pad_l, pad_t, pad_r, pad_b], radius=radius, fill=255)
    img.paste(grad_img, (0, 0), mask_img)

    # 3. 3D Bevel Highlights & Active Accents
    if is_active:
        # Brilliant outer border
        draw.rounded_rectangle([pad_l, pad_t, pad_r, pad_b], radius=radius, outline=(255, 255, 255, 210), width=2 * scale)
        # Top light bevel reflection line
        draw.line([pad_l + radius, pad_t + scale, pad_r - radius, pad_t + scale], fill=(255, 255, 255, 240), width=scale)
        # Bottom dark shadow bevel line
        draw.line([pad_l + radius, pad_b - scale, pad_r - radius, pad_b - scale], fill=(0, 0, 0, 190), width=scale)

        # Left Neon Indicator Bar
        draw.rounded_rectangle(
            [pad_l + 3 * scale, pad_t + 7 * scale, pad_l + 7 * scale, pad_b - 7 * scale],
            radius=2 * scale,
            fill=(255, 255, 255, 255)
        )
    else:
        if is_hover:
            draw.rounded_rectangle([pad_l, pad_t, pad_r, pad_b], radius=radius, outline=(*acc_rgb, 190), width=1 * scale)
            draw.rounded_rectangle(
                [pad_l + 3 * scale, pad_t + 11 * scale, pad_l + 6 * scale, pad_b - 11 * scale],
                radius=2 * scale,
                fill=(*acc_rgb, 240)
            )
        else:
            # 3D Inactive top light bevel
            draw.rounded_rectangle([pad_l, pad_t, pad_r, pad_b], radius=radius, outline=(255, 255, 255, 36), width=1 * scale)
            draw.line([pad_l + radius, pad_t + scale, pad_r - radius, pad_t + scale], fill=(255, 255, 255, 70), width=scale)
            draw.line([pad_l + radius, pad_b - scale, pad_r - radius, pad_b - scale], fill=(0, 0, 0, 160), width=scale)

    # 4. Icon Drawing
    icon_font = _load_font(["seguiemj.ttf", "segoeuiemoji.ttf", "arialbd.ttf"], 15 * scale)
    icon_col = (255, 255, 255, 255) if is_active else ((*acc_rgb, 255) if is_hover else (195, 200, 220, 255))
    draw.text((pad_l + 18 * scale, sh / 2.0 - scale), icon, font=icon_font, fill=icon_col, anchor="lm")

    # 5. Title Text Drawing with Dynamic Responsive Impact Bold Font
    display_title = _to_title_caps(title)
    icon_right_bound = pad_l + 40 * scale
    avail_w = (pad_r - 20 * scale) - icon_right_bound
    avail_h = int(height * 0.78 * scale)

    text_font, pt_size = _get_responsive_impact_font(display_title, avail_w, avail_h, max_pt=18, min_pt=11, scale=scale)

    if is_active:
        # Deep black drop shadow behind active Impact letters for 3D punch
        draw.text((icon_right_bound + 2 * scale, sh / 2.0 + scale), display_title, font=text_font, fill=(0, 0, 0, 250), anchor="lm")
        text_col = (255, 255, 255, 255)
    elif is_hover:
        draw.text((icon_right_bound + scale, sh / 2.0 + scale), display_title, font=text_font, fill=(0, 0, 0, 180), anchor="lm")
        text_col = (255, 255, 255, 255)
    else:
        text_col = (190, 195, 215, 255)

    draw.text((icon_right_bound, sh / 2.0 - scale), display_title, font=text_font, fill=text_col, anchor="lm")

    # 6. Active Right Glowing Dot
    if is_active:
        dot_r = 4 * scale
        cx = pad_r - 14 * scale
        cy = sh / 2.0 - scale
        draw.ellipse([cx - dot_r - scale, cy - dot_r - scale, cx + dot_r + scale, cy + dot_r + scale], fill=(255, 255, 255, 120))
        draw.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill=(255, 255, 255, 255))

    img = img.resize((width, height), Image.Resampling.LANCZOS)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(width, height))


class StudioCardSidebar:
    """
    Scrollable, 3D card navigation with unmistakable active color changes and responsive Impact bold text.
    """
    def __init__(self, parent, tabs: List[Dict],
                 on_tab_change: Optional[Callable[[str], None]] = None,
                 initial_active: str = ""):
        self.parent = parent
        self.tabs = tabs
        self.on_tab_change = on_tab_change
        self.active_id = initial_active or (tabs[0]["id"] if tabs else "")
        self._cards: Dict[str, ctk.CTkButton] = {}
        self._img_cache = {}
        self._build()
        THEME_ENGINE.subscribe(self._on_theme_changed)

    def _img(self, tab, state):
        theme_id = THEME_ENGINE.current_theme_id
        btn_color_id = THEME_ENGINE.current_button_color_id
        key = (tab["id"], state, theme_id, btn_color_id, THEME_ENGINE.custom_button_bg)
        if key not in self._img_cache:
            norm_title = tab["title"].upper()
            matched_accent = "#8B5CF6"
            matched_active_bg = "#4c1d95"
            for k, (bg_c, acc_c, act_bg) in TOOL_ACCENTS.items():
                if k in norm_title or any(w in norm_title for w in k.split()):
                    matched_accent = acc_c
                    matched_active_bg = act_bg
                    break

            self._img_cache[key] = bake_card_image(
                tab["title"], tab.get("icon", "◆"), matched_accent, matched_active_bg,
                is_active=(state == "active"), is_hover=(state == "hover")
            )
        return self._img_cache[key]

    def _build(self):
        theme = THEME_ENGINE.get_current_theme()
        self.outer = ctk.CTkFrame(self.parent, fg_color=theme["rail_bg"], width=CARD_W + 18, corner_radius=0)
        self.outer.pack_propagate(False)

        # Header Title in Sidebar
        hdr = ctk.CTkFrame(self.outer, fg_color="transparent")
        hdr.pack(fill="x", padx=10, pady=(12, 6))

        ctk.CTkLabel(
            hdr, text="⚡ Studio Tools",
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
            text_color=theme["accent_primary"]
        ).pack(side="left")

        ctk.CTkLabel(
            hdr, text=f"{len(self.tabs)} Tools",
            font=ctk.CTkFont("Segoe UI", 9, "bold"),
            text_color=theme["text_dim"]
        ).pack(side="right")

        # Separator line
        sep = ctk.CTkFrame(self.outer, fg_color=theme["card_border"], height=1)
        sep.pack(fill="x", padx=10, pady=(0, 4))

        # Scrollable Cards List
        self.scroll = ctk.CTkScrollableFrame(self.outer, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=2, pady=2)

        for tab in self.tabs:
            is_active = tab["id"] == self.active_id
            btn = ctk.CTkButton(
                self.scroll, text="", image=self._img(tab, "active" if is_active else "normal"),
                fg_color="transparent", hover=False,
                width=CARD_W, height=CARD_H, corner_radius=10, cursor="hand2",
                command=lambda t=tab: self._select(t)
            )
            btn.pack(pady=2)
            btn.bind("<Enter>", lambda e, t=tab: self._hover(t, True))
            btn.bind("<Leave>", lambda e, t=tab: self._hover(t, False))
            self._cards[tab["id"]] = btn

    def _hover(self, tab, entering):
        if tab["id"] == self.active_id:
            return
        if tab["id"] in self._cards and self._cards[tab["id"]].winfo_exists():
            self._cards[tab["id"]].configure(image=self._img(tab, "hover" if entering else "normal"))

    def _select(self, tab):
        if tab["id"] == self.active_id:
            return
        prev = next((t for t in self.tabs if t["id"] == self.active_id), None)
        if prev and prev["id"] in self._cards and self._cards[prev["id"]].winfo_exists():
            self._cards[prev["id"]].configure(image=self._img(prev, "normal"))

        self.active_id = tab["id"]
        if tab["id"] in self._cards and self._cards[tab["id"]].winfo_exists():
            self._cards[tab["id"]].configure(image=self._img(tab, "active"))

        if callable(self.on_tab_change):
            self.on_tab_change(tab["id"])

    def set_active(self, tab_id: str):
        target = next((t for t in self.tabs if t["id"] == tab_id or t["title"].upper() == tab_id.upper()), None)
        if target:
            self._select(target)

    def _on_theme_changed(self, theme: dict):
        self._img_cache.clear()
        if self.outer.winfo_exists():
            self.outer.configure(fg_color=theme["rail_bg"])
        for tab in self.tabs:
            tid = tab["id"]
            if tid in self._cards and self._cards[tid].winfo_exists():
                is_act = (tid == self.active_id)
                self._cards[tid].configure(image=self._img(tab, "active" if is_act else "normal"))

    def pack(self, **kw): self.outer.pack(**kw)
    def grid(self, **kw): self.outer.grid(**kw)


class StudioMainWorkspace(ctk.CTkFrame):
    """
    Main Studio Shell: 100% Full-Screen Responsive, 3D Tactile Aesthetic, and High-Contrast Live Telemetry HUD.
    """
    def __init__(self, parent, plugins: List[Any], boot_data: Optional[Dict] = None, **kwargs):
        theme = THEME_ENGINE.get_current_theme()
        super().__init__(parent, fg_color=theme["bg_dark"], corner_radius=0, **kwargs)
        self.plugins = plugins
        self.boot_data = boot_data or {}
        self._plugin_frames: Dict[str, ctk.CTkFrame] = {}
        self._current_tab_id = ""

        self.tabs_meta = self._prepare_tabs_meta(plugins)

        # 100% Full-Screen Responsive Root Configuration
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)  # Top Bar (52px)
        self.grid_rowconfigure(1, weight=1)  # Body Workspace (Expands to 100% full-screen height)

        # 1. Top Bar: Live System Telemetry HUD & Controls
        self._build_top_telemetry_bar()

        # 2. Main Body Container (Sidebar + Tool Host)
        self.body_container = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.body_container.grid(row=1, column=0, sticky="nsew")
        self.body_container.grid_columnconfigure(0, weight=0, minsize=CARD_W + 18)
        self.body_container.grid_columnconfigure(1, weight=1)  # Stretches to fill entire screen width
        self.body_container.grid_rowconfigure(0, weight=1)     # Stretches full vertical height

        # Left 3D Card Sidebar
        initial_tab = self.tabs_meta[0]["id"] if self.tabs_meta else "01_stories"
        self.sidebar = StudioCardSidebar(
            self.body_container,
            tabs=self.tabs_meta,
            on_tab_change=self.on_tab_change,
            initial_active=initial_tab
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        # Tool Host Frame — Grid-Stack with 100% weights for Full-Screen Responsiveness
        self.tool_host = ctk.CTkFrame(self.body_container, fg_color="transparent", corner_radius=0)
        self.tool_host.grid(row=0, column=1, sticky="nsew")
        self.tool_host.grid_columnconfigure(0, weight=1)
        self.tool_host.grid_rowconfigure(0, weight=1)

        THEME_ENGINE.subscribe(self._on_theme_changed)

        # Mount initial tab with zero flicker
        self.after(20, lambda: self.on_tab_change(initial_tab))

    def _prepare_tabs_meta(self, plugins: List[Any]) -> List[Dict]:
        """Convert plugins to standard 13-tool sidebar navigation format with clean icons."""
        meta_list = []
        icon_defaults = {
            "STORIES": "🎬",
            "RECAP STUDIO": "🎥",
            "STORY IMAGE VIDEO": "🖼️",
            "QUEUE": "📋",
            "JESUS PRAYER": "✝️",
            "IMAGE TO VIDEO": "🎞️",
            "SUFFIX TOOL": "🔧",
            "SHORTS": "⚡",
            "RHYMES": "🎵",
            "YOUTUBE DATA FETCHER": "▶️",
            "PROMPT DRIVE": "☁️",
            "CHARACTER PROMPT FILLER": "🎭",
            "MUSIC": "🎸",
            "MUSIC TOOL": "🎸",
            "SONG VIDEO MAKER": "🎤",
        }

        if plugins:
            for p in plugins:
                raw_t = p.title.replace("🎬", "").replace("📖", "").replace("🗂", "").replace("🎨", "").replace("🙏", "").replace("🎤", "").replace("📱", "").replace("📄", "").replace("🎵", "").replace("📺", "").replace("📁", "").strip()
                norm_upper = raw_t.upper()
                ico = getattr(p, "icon", "") or icon_defaults.get(norm_upper, "◆")
                meta_list.append({
                    "id": p.module_name,
                    "title": raw_t,
                    "icon": ico,
                    "plugin": p
                })
        return meta_list

    # ═══════════════════════════════════════════════════════════════════
    # TOP BAR: HIGH-CONTRAST 3D TELEMETRY HUD & CONTROLS
    # ═══════════════════════════════════════════════════════════════════
    def _build_top_telemetry_bar(self):
        theme = THEME_ENGINE.get_current_theme()
        self.top_bar = ctk.CTkFrame(self, fg_color=theme["header_bg"], height=52, corner_radius=0)
        self.top_bar.grid(row=0, column=0, sticky="ew")
        self.top_bar.grid_propagate(False)

        # Left Section: Brand Logo & Version with All First Letter Caps
        left_box = ctk.CTkFrame(self.top_bar, fg_color="transparent")
        left_box.pack(side="left", padx=(12, 4), pady=6)

        ctk.CTkLabel(
            left_box, text="🎬🎵 Ai Studio Pro",
            font=("Segoe UI", 14, "bold"),
            text_color=theme["accent_primary"]
        ).pack(side="left", padx=(0, 6))

        ctk.CTkLabel(
            left_box, text="v2.8",
            font=("Segoe UI", 10, "bold"),
            text_color=theme["text_dim"]
        ).pack(side="left", padx=(0, 8))

        # ── CENTER: HIGH-CONTRAST 3D SYSTEM TELEMETRY HUD ────────────
        self.hw_box = ctk.CTkFrame(
            self.top_bar,
            fg_color="#060913",
            corner_radius=10,
            border_width=1,
            border_color="#000000"
        )
        self.hw_box.pack(side="left", padx=(6, 4), pady=6)

        # 1. CPU & RAM Capsule (Vivid Lime / Neon Emerald)
        self.pill_cpu_ram = ctk.CTkFrame(self.hw_box, fg_color="#08140f", corner_radius=8, border_width=1, border_color="#000000")
        self.pill_cpu_ram.pack(side="left", padx=(4, 3), pady=3)

        self.lbl_cpu_ram = ctk.CTkLabel(
            self.pill_cpu_ram,
            text="⚙️ Cpu: --%  |  🧠 Ram: -- Gb",
            font=("Segoe UI", 11, "bold"),
            text_color="#00ff88"
        )
        self.lbl_cpu_ram.pack(padx=8, pady=2)

        # 2. GPU Telemetry Capsule (Bright Electric Cyan)
        self.pill_gpu = ctk.CTkFrame(self.hw_box, fg_color="#071322", corner_radius=8, border_width=1, border_color="#000000")
        self.pill_gpu.pack(side="left", padx=3, pady=3)

        self.lbl_gpu = ctk.CTkLabel(
            self.pill_gpu,
            text="🎮 Gpu: Detecting...",
            font=("Segoe UI", 11, "bold"),
            text_color="#38bdf8"
        )
        self.lbl_gpu.pack(padx=8, pady=2)

        # 3. Network I/O Capsule (Vivid Orchid Violet)
        self.pill_net = ctk.CTkFrame(self.hw_box, fg_color="#120921", corner_radius=8, border_width=1, border_color="#000000")
        self.pill_net.pack(side="left", padx=3, pady=3)

        self.lbl_net = ctk.CTkLabel(
            self.pill_net,
            text="📶 Net: ⬇ 0.0 Kb/s  ⬆ 0.0 Kb/s",
            font=("Segoe UI", 11, "bold"),
            text_color="#c084fc"
        )
        self.lbl_net.pack(padx=8, pady=2)

        # 4. System Health Inspector Button Capsule (Emerald Mint)
        self.pill_health = ctk.CTkFrame(self.hw_box, fg_color="#064e3b", corner_radius=8, border_width=1, border_color="#000000")
        self.pill_health.pack(side="left", padx=(3, 4), pady=3)

        self.btn_health = ctk.CTkButton(
            self.pill_health,
            text="🛡️ Health: 100% Ok",
            font=("Segoe UI", 11, "bold"),
            text_color="#34d399",
            fg_color="transparent",
            hover_color="#047857",
            height=26,
            width=120,
            command=self._open_health_diagnostics_modal
        )
        self.btn_health.pack(padx=2, pady=0)

        # Start non-blocking background telemetry monitor thread
        system_monitor.start_hardware_monitor()
        self._start_telemetry_loop()

        # ── RIGHT SECTION: 3D ACTION BUTTONS & THEME/BUTTON CONTROLS ──
        right_box = ctk.CTkFrame(self.top_bar, fg_color="transparent")
        right_box.pack(side="right", padx=(4, 10), pady=6)

        # 1. 3D Admin Control Center Button (Exclusively for 8949400100)
        from auth_manager import is_current_user_admin
        u_data = self.boot_data.get("user_data") if hasattr(self, "boot_data") and isinstance(self.boot_data, dict) else None
        if is_current_user_admin(u_data):
            self.btn_admin = ctk.CTkButton(
                right_box,
                text="👑 Admin",
                font=("Segoe UI", 11, "bold"),
                width=95,
                height=34,
                corner_radius=8,
                border_width=1,
                border_color="#000000",
                fg_color="#6366f1",
                hover_color="#4f46e5",
                text_color="#ffffff",
                command=self._open_admin_portal
            )
            self.btn_admin.pack(side="right", padx=3)

        # 2. 3D Button & Theme Color Picker Button
        self.btn_theme = ctk.CTkButton(
            right_box,
            text="🎨 Button Color",
            font=("Segoe UI", 11, "bold"),
            width=120,
            height=34,
            corner_radius=8,
            border_width=1,
            border_color="#000000",
            fg_color=theme["accent_primary"],
            hover_color=theme["accent_secondary"],
            text_color="#ffffff",
            command=self._open_theme_modal
        )
        self.btn_theme.pack(side="right", padx=3)

        # 2. 3D Check Update Button
        self.btn_update = ctk.CTkButton(
            right_box,
            text="🚀 Check Update",
            font=("Segoe UI", 11, "bold"),
            width=115,
            height=34,
            corner_radius=8,
            border_width=1,
            border_color="#000000",
            fg_color="#10b981",
            hover_color="#059669",
            text_color="#ffffff",
            command=self._trigger_update_check
        )
        self.btn_update.pack(side="right", padx=3)

        # 3. Output Resolution Picker
        self._res_var = ctk.StringVar(value=_OUTPUT_RES_CHOICE)
        self.opt_res = ctk.CTkOptionMenu(
            right_box,
            variable=self._res_var,
            values=list(_OUTPUT_PRESETS.keys()),
            width=115,
            height=34,
            fg_color=theme["card_top"],
            button_color=theme["card_border"],
            font=("Segoe UI", 10, "bold"),
            corner_radius=8,
            command=lambda v: _set_output_res(v)
        )
        self.opt_res.pack(side="right", padx=3)

        ctk.CTkLabel(right_box, text="Output:", text_color=theme["text_dim"], font=("Segoe UI", 10, "bold")).pack(side="right", padx=(4, 2))

        # 4. User Profile Badge with All First Letter Caps
        user_data = self.boot_data.get("user_data") or {}
        user_name = user_data.get("name") or "Creator"
        user_val = user_data.get("validity_display") or "✨ Lifetime"
        user_name_cap = _to_title_caps(user_name)
        user_val_cap = _to_title_caps(user_val)

        self.btn_user_prof = ctk.CTkButton(
            right_box,
            text=f"👤 {user_name_cap} • {user_val_cap}",
            font=("Segoe UI", 10, "bold"),
            height=34,
            fg_color=theme["card_top"],
            hover_color=theme["card_border"],
            text_color="#38bdf8",
            border_width=1,
            border_color="#000000",
            corner_radius=16,
            command=self._open_user_profile_modal
        )
        self.btn_user_prof.pack(side="right", padx=(4, 8))

    def _start_telemetry_loop(self):
        def _telemetry_worker():
            while True:
                try:
                    if not self.winfo_exists():
                        break
                    stats = system_monitor.get_current_hw_stats()
                    cpu_pct = stats.get("cpu_pct", 0)
                    ram_used = stats.get("ram_used_gb", 0.0)
                    ram_tot = stats.get("ram_total_gb", 16.0)
                    is_cpu_high = stats.get("is_cpu_high", False)

                    gpu_name = stats.get("gpu_short_name") or stats.get("gpu_name", "Gpu")
                    gpu_name_cap = _to_title_caps(gpu_name)
                    if "Gtx" in gpu_name_cap: gpu_name_cap = gpu_name_cap.replace("Gtx", "GTX")
                    if "Rtx" in gpu_name_cap: gpu_name_cap = gpu_name_cap.replace("Rtx", "RTX")
                    if "Super" in gpu_name_cap: gpu_name_cap = gpu_name_cap.replace("Super", "SUPER")
                    if "Nvidia" in gpu_name_cap: gpu_name_cap = gpu_name_cap.replace("Nvidia", "NVIDIA")

                    temp = stats.get("gpu_temp_c", 0)
                    load = stats.get("gpu_load_pct", 0)
                    temp_str = f" • {temp}°C" if temp > 0 else ""
                    load_str = f" • {load}%" if load > 0 else ""
                    gpu_str = f"🎮 Gpu: {gpu_name_cap}{temp_str}{load_str}"

                    net_down = str(stats.get("net_down_str", "⬇ 0.0 Kb/s")).replace("KB/s", "Kb/s").replace("MB/s", "Mb/s")
                    net_up = str(stats.get("net_up_str", "⬆ 0.0 Kb/s")).replace("KB/s", "Kb/s").replace("MB/s", "Mb/s")
                    net_str = f"📶 Net: {net_down}  {net_up}"

                    cpu_ram_str = f"⚙️ Cpu: {cpu_pct}%  |  🧠 Ram: {ram_used:.1f} Gb / {ram_tot:.0f} Gb"

                    def _ui_update():
                        try:
                            if self.lbl_cpu_ram.winfo_exists():
                                cpu_col = "#ff3333" if is_cpu_high else "#00ff88"
                                self.lbl_cpu_ram.configure(
                                    text=cpu_ram_str,
                                    text_color=cpu_col
                                )
                            if self.lbl_gpu.winfo_exists():
                                self.lbl_gpu.configure(text=gpu_str)
                            if self.lbl_net.winfo_exists():
                                self.lbl_net.configure(text=net_str)
                        except Exception:
                            pass
                    self.after(0, _ui_update)
                except Exception:
                    pass
                time.sleep(1.5)

        threading.Thread(target=_telemetry_worker, daemon=True, name="TopTelemetryWorker").start()

    # ═══════════════════════════════════════════════════════════════════
    # ZERO-FLUCTUATION & 100% FULL-SCREEN RESPONSIVE TAB SWITCHING
    # ═══════════════════════════════════════════════════════════════════
    def on_tab_change(self, tab_id: str):
        self._current_tab_id = tab_id
        global current_active_tab_name
        plugin_loader.current_active_tab_name = tab_id

        matched_plugin = None
        for t in self.tabs_meta:
            if t["id"] == tab_id or t["title"].upper() == tab_id.upper():
                matched_plugin = t.get("plugin")
                break

        if not matched_plugin and self.plugins:
            norm = tab_id.lower().replace("_", "").replace("-", "").replace("tab", "").strip()
            for p in self.plugins:
                p_norm = p.module_name.lower().replace("_", "").replace("-", "").replace("tab", "").strip()
                if norm in p_norm or p_norm in norm:
                    matched_plugin = p
                    break

        if not matched_plugin and self.plugins:
            matched_plugin = self.plugins[0]

        if not matched_plugin:
            return

        p_title = matched_plugin.title

        if p_title in self._plugin_frames:
            target_f = self._plugin_frames[p_title]
            target_f.tkraise()
            return

        target_f = ctk.CTkFrame(self.tool_host, fg_color="transparent", corner_radius=0)
        target_f.grid(row=0, column=0, sticky="nsew")
        target_f.grid_columnconfigure(0, weight=1)
        target_f.grid_rowconfigure(0, weight=1)
        self._plugin_frames[p_title] = target_f
        target_f.tkraise()

        try:
            matched_plugin.create_fn(target_f, self.boot_data)
            matched_plugin._mounted = True
        except Exception as exc:
            import traceback
            for c in target_f.winfo_children():
                try: c.destroy()
                except Exception: pass
            err_card = ctk.CTkLabel(
                target_f,
                text=f"⚠️ {p_title} Load Failed:\n\n{traceback.format_exc()[:400]}",
                text_color="#ef4444",
                font=("Consolas", 11),
                justify="left"
            )
            err_card.pack(expand=True, padx=20, pady=20)

    # ═══════════════════════════════════════════════════════════════════
    # MODALS & BUTTON COLOR / THEME PICKERS
    # ═══════════════════════════════════════════════════════════════════
    def _open_theme_modal(self):
        theme = THEME_ENGINE.get_current_theme()
        top = self.winfo_toplevel()
        modal = ctk.CTkToplevel(top)
        modal.title("Button Color & Studio Theme Customizer")
        modal.geometry("560x540")
        modal.resizable(False, False)
        modal.configure(fg_color=theme["bg_dark"])
        modal.transient(top)
        modal.grab_set()

        modal.update_idletasks()
        mx = top.winfo_x() + (top.winfo_width() - 560) // 2
        my = top.winfo_y() + (top.winfo_height() - 540) // 2
        modal.geometry(f"560x540+{mx}+{my}")

        card = ctk.CTkFrame(modal, fg_color=theme["card_top"], corner_radius=16, border_width=1, border_color="#000000")
        card.pack(fill="both", expand=True, padx=14, pady=14)

        # Header Title
        ctk.CTkLabel(
            card, text="🎨 Button Color & Theme Customizer",
            font=("Segoe UI", 16, "bold"), text_color=theme["text_main"]
        ).pack(pady=(12, 2))

        ctk.CTkLabel(
            card, text="Choose button active accent colors and overall studio theme palettes",
            font=("Segoe UI", 10), text_color=theme["text_dim"]
        ).pack(pady=(0, 8))

        # Tabview: Button Color Presets vs Studio Themes
        tabview = ctk.CTkTabview(card, fg_color="transparent")
        tabview.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        tab_btn = tabview.add("🌈 Button Colors")
        tab_thm = tabview.add("🎨 Studio Themes")

        # ── TAB 1: BUTTON COLOR PRESETS & CUSTOM HEX ─────────────────
        btn_scroll = ctk.CTkScrollableFrame(tab_btn, fg_color="transparent")
        btn_scroll.pack(fill="both", expand=True, padx=4, pady=4)

        # Custom Hex Color Section
        custom_frame = ctk.CTkFrame(btn_scroll, fg_color=theme["card_bottom"], corner_radius=10, border_width=1, border_color="#000000")
        custom_frame.pack(fill="x", pady=(0, 8), padx=4)

        ctk.CTkLabel(custom_frame, text="✨ Custom Button Hex Color:", font=("Segoe UI", 11, "bold"), text_color="#38bdf8").pack(anchor="w", padx=10, pady=(8, 2))
        hex_row = ctk.CTkFrame(custom_frame, fg_color="transparent")
        hex_row.pack(fill="x", padx=10, pady=(0, 8))

        hex_entry = ctk.CTkEntry(hex_row, placeholder_text="#2563eb (e.g. #ff0055)", width=160, font=("Consolas", 11), fg_color="#070a12", border_color="#1e293b")
        hex_entry.pack(side="left", padx=(0, 6))
        if THEME_ENGINE.custom_button_bg:
            hex_entry.insert(0, THEME_ENGINE.custom_button_bg)

        def _apply_custom_hex():
            val = hex_entry.get().strip()
            if val and (val.startswith("#") and len(val) in (4, 7)):
                THEME_ENGINE.set_custom_button_color(val, "#ffffff")
                modal.destroy()

        ctk.CTkButton(hex_row, text="Apply Custom Hex", font=("Segoe UI", 10, "bold"), fg_color="#10b981", hover_color="#059669", width=130, command=_apply_custom_hex).pack(side="left")

        # Button Color Presets List
        ctk.CTkLabel(btn_scroll, text="Preset Button Accent Styles:", font=("Segoe UI", 11, "bold"), text_color=theme["text_main"]).pack(anchor="w", padx=6, pady=(4, 4))

        for bp in BUTTON_COLOR_PRESETS:
            is_active = (bp["id"] == THEME_ENGINE.current_button_color_id)
            row = ctk.CTkFrame(
                btn_scroll,
                fg_color=theme["card_bottom"],
                corner_radius=10,
                border_width=2 if is_active else 1,
                border_color=bp["acc"] if is_active else "#000000",
                height=46
            )
            row.pack(fill="x", pady=3, padx=4)
            row.pack_propagate(False)

            sw = ctk.CTkFrame(row, fg_color=bp["bg"], width=24, height=24, corner_radius=12, border_width=2, border_color=bp["acc"])
            sw.pack(side="left", padx=10, pady=10)

            t_box = ctk.CTkFrame(row, fg_color="transparent")
            t_box.pack(side="left", fill="both", expand=True, padx=6, pady=6)
            ctk.CTkLabel(t_box, text=bp["name"], font=("Segoe UI", 11, "bold"), text_color="#ffffff", anchor="w").pack(fill="x")

            def _apply_btn(pid=bp["id"]):
                THEME_ENGINE.set_button_color_preset(pid)
                modal.destroy()

            ctk.CTkButton(
                row,
                text="✓ Active" if is_active else "Select",
                font=("Segoe UI", 10, "bold"),
                width=75,
                height=26,
                corner_radius=13,
                fg_color=bp["bg"],
                hover_color=bp["acc"],
                text_color="#ffffff",
                command=_apply_btn
            ).pack(side="right", padx=10, pady=10)

        # ── TAB 2: STUDIO THEME PALETTES ──────────────────────────────
        thm_scroll = ctk.CTkScrollableFrame(tab_thm, fg_color="transparent")
        thm_scroll.pack(fill="both", expand=True, padx=4, pady=4)

        for th_id, th_info in STUDIO_THEMES.items():
            is_active = (th_id == THEME_ENGINE.current_theme_id)
            row = ctk.CTkFrame(
                thm_scroll,
                fg_color=th_info["card_bottom"],
                corner_radius=12,
                border_width=2 if is_active else 1,
                border_color=th_info["accent_primary"] if is_active else "#000000",
                height=52
            )
            row.pack(fill="x", pady=4, padx=4)
            row.pack_propagate(False)

            swatch_box = ctk.CTkFrame(row, fg_color="transparent")
            swatch_box.pack(side="left", padx=10, pady=10)
            for c_hex in (th_info["bg_dark"], th_info["sidebar_bg"], th_info["accent_primary"], th_info["accent_glow"]):
                sw = ctk.CTkFrame(swatch_box, fg_color=c_hex, width=16, height=16, corner_radius=8, border_width=1, border_color="#ffffff")
                sw.pack(side="left", padx=2)

            t_box = ctk.CTkFrame(row, fg_color="transparent")
            t_box.pack(side="left", fill="both", expand=True, padx=8, pady=6)
            ctk.CTkLabel(t_box, text=th_info["name"], font=("Segoe UI", 12, "bold"), text_color=th_info["text_main"], anchor="w").pack(fill="x")
            ctk.CTkLabel(t_box, text=th_info["subtitle"], font=("Segoe UI", 9), text_color=th_info["text_dim"], anchor="w").pack(fill="x")

            def _apply_th(tid=th_id):
                THEME_ENGINE.set_theme(tid)
                modal.destroy()

            ctk.CTkButton(
                row,
                text="✓ Active" if is_active else "Apply",
                font=("Segoe UI", 10, "bold"),
                width=80,
                height=28,
                corner_radius=14,
                fg_color=th_info["accent_primary"],
                hover_color=th_info["accent_secondary"],
                text_color="#ffffff",
                command=_apply_th
            ).pack(side="right", padx=12, pady=12)

        ctk.CTkButton(
            card, text="Close", font=("Segoe UI", 11, "bold"),
            width=100, height=32, corner_radius=8,
            fg_color=theme["card_bottom"], hover_color=theme["card_border"],
            text_color=theme["text_main"],
            command=modal.destroy
        ).pack(pady=(6, 10))

    def _open_admin_portal(self):
        try:
            import admin_tool
            import prompt_cloud_service

            if prompt_cloud_service.is_master_admin_active():
                admin_tool.launch_gui_admin(self.winfo_toplevel())
                return

            top = self.winfo_toplevel()
            modal = ctk.CTkToplevel(top)
            modal.title("👑 Super Admin Portal Unlock")
            modal.geometry("440x390")
            modal.resizable(False, False)
            modal.configure(fg_color="#070913")
            modal.transient(top)
            modal.grab_set()

            modal.update_idletasks()
            mx = top.winfo_x() + (top.winfo_width() - 440) // 2
            my = top.winfo_y() + (top.winfo_height() - 390) // 2
            modal.geometry(f"440x390+{mx}+{my}")

            card = ctk.CTkFrame(modal, fg_color="#0f1424", corner_radius=16, border_width=1, border_color="#000000")
            card.pack(fill="both", expand=True, padx=16, pady=16)

            ctk.CTkLabel(card, text="👑 SUPER ADMIN CONTROL CENTER", font=("Segoe UI", 15, "bold"), text_color="#a78bfa").pack(pady=(14, 4))
            ctk.CTkLabel(card, text="Enter Admin credentials to launch full management suite", font=("Segoe UI", 10), text_color="#94a3b8").pack(pady=(0, 10))

            ctk.CTkLabel(card, text="Admin User ID:", font=("Segoe UI", 11, "bold"), text_color="#cbd5e1", anchor="w").pack(fill="x", padx=20, pady=(2, 2))
            u_entry = ctk.CTkEntry(card, placeholder_text="e.g. 8949400100", font=("Segoe UI", 11), height=32, corner_radius=8, fg_color="#171f38", border_color="#222c4a")
            u_entry.insert(0, "8949400100")
            u_entry.pack(fill="x", padx=20, pady=(0, 6))

            ctk.CTkLabel(card, text="Admin Password:", font=("Segoe UI", 11, "bold"), text_color="#cbd5e1", anchor="w").pack(fill="x", padx=20, pady=(2, 2))
            p_entry = ctk.CTkEntry(card, placeholder_text="••••••••", show="*", font=("Segoe UI", 11), height=32, corner_radius=8, fg_color="#171f38", border_color="#222c4a")
            p_entry.pack(fill="x", padx=20, pady=(0, 6))

            rem_var = ctk.BooleanVar(value=True)
            rem_cb = ctk.CTkCheckBox(
                card,
                text="Remember Admin on this PC (Auto-Login)",
                variable=rem_var,
                font=("Segoe UI", 10),
                text_color="#94a3b8",
                fg_color="#6366f1",
                hover_color="#4f46e5",
                checkmark_color="#ffffff",
                border_color="#374151",
                height=18
            )
            rem_cb.pack(anchor="w", padx=20, pady=(0, 6))

            err_lbl = ctk.CTkLabel(card, text="", font=("Segoe UI", 10, "bold"), text_color="#ef4444")
            err_lbl.pack(fill="x", padx=20, pady=(0, 4))

            def _do_unlock():
                uid = u_entry.get().strip()
                pwd = p_entry.get().strip()
                if not uid or not pwd:
                    err_lbl.configure(text="Enter Admin ID and Password.")
                    return
                ok, msg = prompt_cloud_service.verify_admin_login(uid, pwd, remember_me=rem_var.get())
                if ok:
                    modal.destroy()
                    admin_tool.launch_gui_admin(top)
                else:
                    err_lbl.configure(text=f"❌ {msg}")

            p_entry.bind("<Return>", lambda e: _do_unlock())

            b_row = ctk.CTkFrame(card, fg_color="transparent")
            b_row.pack(fill="x", padx=20, pady=(4, 10))

            ctk.CTkButton(b_row, text="Cancel", width=80, height=32, fg_color="#1c2646", text_color="#94a3b8", command=modal.destroy).pack(side="left")
            ctk.CTkButton(b_row, text="🚀 Open Admin Panel", width=160, height=32, fg_color="#8b5cf6", hover_color="#7c3aed", font=("Segoe UI", 11, "bold"), command=_do_unlock).pack(side="right")
        except Exception as e:
            print("[ADMIN] Open error:", e)

    def _open_health_diagnostics_modal(self):
        try:
            import system_health
            summary = system_health.HEALTH.get_status_summary()
            top = self.winfo_toplevel()
            modal = ctk.CTkToplevel(top)
            modal.title("System Health & Diagnostics Inspector")
            modal.geometry("640x500")
            modal.resizable(False, False)
            modal.configure(fg_color="#080c16")
            modal.transient(top)
            modal.grab_set()

            card = ctk.CTkFrame(modal, fg_color="#0f1424", corner_radius=16, border_width=1, border_color="#000000")
            card.pack(fill="both", expand=True, padx=14, pady=14)

            thdr = ctk.CTkFrame(card, fg_color="transparent")
            thdr.pack(fill="x", padx=12, pady=(12, 6))
            ctk.CTkLabel(thdr, text="🛡️ System Health & Diagnostics Inspector", font=("Segoe UI", 15, "bold"), text_color="#38bdf8").pack(side="left")

            stat_col = "#10b981" if summary["is_healthy"] else "#ef4444"
            stat_txt = "● 100% Healthy • No Errors" if summary["is_healthy"] else f"● {summary['error_count']} Error(s) Detected"
            ctk.CTkLabel(thdr, text=stat_txt, font=("Segoe UI", 11, "bold"), text_color=stat_col).pack(side="right")

            ctk.CTkLabel(card, text=f"Diagnostics Log: {summary['log_file']}", font=("Consolas", 10), text_color="#94a3b8").pack(anchor="w", padx=12, pady=2)
            log_box = ctk.CTkTextbox(card, height=280, font=("Consolas", 10), fg_color="#070c18", border_width=1, border_color="#1e293b")
            log_box.pack(fill="both", expand=True, padx=12, pady=6)

            for ev in system_health.HEALTH.events:
                log_box.insert("end", str(ev) + "\n")
            log_box.see("end")

            btn_bar = ctk.CTkFrame(card, fg_color="transparent")
            btn_bar.pack(fill="x", padx=12, pady=(6, 12))

            def _clear_health_ui():
                system_health.HEALTH.clear_health()
                log_box.delete("1.0", "end")
                log_box.insert("end", "[Info] Health Cleared. 100% Ok.\n")
                self.btn_health.configure(text="🛡️ Health: 100% Ok", text_color="#34d399")

            ctk.CTkButton(btn_bar, text="🧹 Reset Health", width=120, fg_color="#1e293b", hover_color="#334155", command=_clear_health_ui).pack(side="left", padx=4)
            ctk.CTkButton(btn_bar, text="Close", width=90, fg_color="#38bdf8", text_color="#000", hover_color="#0ea5e9", command=modal.destroy).pack(side="right", padx=4)
        except Exception as e:
            print("[HEALTH] Modal error:", e)

    def _open_user_profile_modal(self):
        try:
            from auth_manager import get_user_profile, get_video_exports_count
            user_prof = self.boot_data.get("user_data") or get_user_profile()
            u_name = user_prof.get("name") or user_prof.get("user_id") or "Creator"
            u_val = user_prof.get("validity_display") or "✨ Lifetime"
            u_exp = user_prof.get("exports_count", get_video_exports_count(user_prof.get("user_id")))

            top = self.winfo_toplevel()
            modal = ctk.CTkToplevel(top)
            modal.title("User Profile & Studio Analytics")
            modal.geometry("480x420")
            modal.resizable(False, False)
            modal.configure(fg_color="#0b0e18")
            modal.transient(top)
            modal.grab_set()

            card = ctk.CTkFrame(modal, fg_color="#121829", corner_radius=16, border_width=1, border_color="#000000")
            card.pack(fill="both", expand=True, padx=16, pady=16)

            top_box = ctk.CTkFrame(card, fg_color="transparent")
            top_box.pack(fill="x", padx=16, pady=(16, 12))

            av = ctk.CTkFrame(top_box, fg_color="#1e1b4b", width=44, height=44, corner_radius=22, border_width=2, border_color="#8b5cf6")
            av.pack(side="left", padx=(0, 10))
            av.pack_propagate(False)
            ctk.CTkLabel(av, text="👤", font=("Segoe UI", 18)).pack(expand=True)

            u_info = ctk.CTkFrame(top_box, fg_color="transparent")
            u_info.pack(side="left", fill="both", expand=True)
            ctk.CTkLabel(u_info, text=_to_title_caps(u_name), font=("Segoe UI", 16, "bold"), text_color="#f8fafc", anchor="w").pack(fill="x")
            ctk.CTkLabel(u_info, text=f"User ID: @{user_prof.get('user_id', 'creator')}", font=("Segoe UI", 10), text_color="#38bdf8", anchor="w").pack(fill="x")

            met_grid = ctk.CTkFrame(card, fg_color="transparent")
            met_grid.pack(fill="x", padx=16, pady=8)

            c1 = ctk.CTkFrame(met_grid, fg_color="#171f38", corner_radius=10, border_width=1, border_color="#000000")
            c1.pack(fill="x", pady=4)
            r1 = ctk.CTkFrame(c1, fg_color="transparent")
            r1.pack(fill="x", padx=12, pady=8)
            ctk.CTkLabel(r1, text="🎬", font=("Segoe UI", 18)).pack(side="left", padx=(0, 10))
            inf1 = ctk.CTkFrame(r1, fg_color="transparent")
            inf1.pack(side="left", fill="both", expand=True)
            ctk.CTkLabel(inf1, text="Total Videos Exported", font=("Segoe UI", 9, "bold"), text_color="#94a3b8", anchor="w").pack(fill="x")
            ctk.CTkLabel(inf1, text=f"{u_exp} Videos Rendered", font=("Segoe UI", 13, "bold"), text_color="#38bdf8", anchor="w").pack(fill="x")

            c2 = ctk.CTkFrame(met_grid, fg_color="#171f38", corner_radius=10, border_width=1, border_color="#000000")
            c2.pack(fill="x", pady=4)
            r2 = ctk.CTkFrame(c2, fg_color="transparent")
            r2.pack(fill="x", padx=12, pady=8)
            ctk.CTkLabel(r2, text="🛡️", font=("Segoe UI", 18)).pack(side="left", padx=(0, 10))
            inf2 = ctk.CTkFrame(r2, fg_color="transparent")
            inf2.pack(side="left", fill="both", expand=True)
            ctk.CTkLabel(inf2, text="License Status", font=("Segoe UI", 9, "bold"), text_color="#94a3b8", anchor="w").pack(fill="x")
            ctk.CTkLabel(inf2, text=f"{_to_title_caps(str(u_val))}", font=("Segoe UI", 13, "bold"), text_color="#10b981", anchor="w").pack(fill="x")

            ctk.CTkButton(card, text="Close", height=36, fg_color="#334155", hover_color="#475569", text_color="#ffffff", font=("Segoe UI", 11, "bold"), command=modal.destroy).pack(pady=(12, 0))
        except Exception as e:
            print("[PROFILE] Modal error:", e)

    def _trigger_update_check(self):
        try:
            self.btn_update.configure(state="disabled", text="⏳ Checking...", fg_color="#047857")
        except Exception:
            pass

        def _worker():
            try:
                from updater import check_for_update, UpdateWindow, CURRENT_VERSION
                info = check_for_update()
                if info:
                    def _show_upd():
                        try:
                            self.btn_update.configure(state="normal", text=f"🔥 Update v{info['version']}", fg_color="#ef4444", hover_color="#dc2626")
                            UpdateWindow(self.winfo_toplevel(), info)
                        except Exception:
                            pass
                    self.after(0, _show_upd)
                else:
                    def _show_ok():
                        try:
                            self.btn_update.configure(state="normal", text="🚀 Check Update", fg_color="#10b981", hover_color="#059669")
                            from tkinter import messagebox
                            messagebox.showinfo("Software Update", f"You are running the latest version (v{CURRENT_VERSION}).")
                        except Exception:
                            pass
                    self.after(0, _show_ok)
            except Exception as e:
                def _show_err():
                    try:
                        self.btn_update.configure(state="normal", text="🚀 Check Update", fg_color="#10b981", hover_color="#059669")
                        from tkinter import messagebox
                        messagebox.showerror("Update Check Failed", f"Unable to check for updates:\n{e}")
                    except Exception:
                        pass
                self.after(0, _show_err)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_theme_changed(self, theme: dict):
        if self.winfo_exists():
            self.configure(fg_color=theme["bg_dark"])
        if self.top_bar.winfo_exists():
            self.top_bar.configure(fg_color=theme["header_bg"])
        if self.btn_theme.winfo_exists():
            self.btn_theme.configure(fg_color=theme["accent_primary"], hover_color=theme["accent_secondary"])
        if self.opt_res.winfo_exists():
            self.opt_res.configure(fg_color=theme["card_top"], button_color=theme["card_border"])
        if self.btn_user_prof.winfo_exists():
            self.btn_user_prof.configure(fg_color=theme["card_top"], hover_color=theme["card_border"])
