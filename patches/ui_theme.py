"""
ui_theme.py — Shared design system

CustomTkinter mein by default gradients/glow nahi hote — isliye sab flat
aur sasta dikhta hai. Yahan PIL se asli mesh-gradient render karke usko
background image ki tarah lagate hain. Yahi "premium" look deta hai.
"""

import math

from PIL import Image, ImageDraw, ImageFilter

# ── Palette ───────────────────────────────────────────────────
INK        = "#070913"      # Deep cosmic space background
SURFACE    = "#0f1424"      # Glassmorphic card surface
SURFACE_HI = "#171f38"      # Raised hover surface
SURFACE_ACC = "#1c2646"     # Active accent surface
STROKE     = "#222c4a"      # Border line
STROKE_HI  = "#384776"      # Hover border line
STROKE_GLOW = "#6366f1"     # Glow border line

TEXT       = "#f8fafc"      # Crisp white
TEXT_DIM   = "#94a3b8"      # Slate gray
TEXT_FAINT = "#64748b"      # Muted slate

VIOLET     = "#8b5cf6"
VIOLET_HI  = "#a78bfa"
CYAN       = "#06b6d4"
CYAN_HI    = "#22d3ee"
EMERALD    = "#10b981"
EMERALD_HI = "#34d399"
GOLD       = "#f59e0b"
GOLD_HI    = "#fbbf24"
PINK       = "#f43f5e"
GOOD       = "#10b981"
BAD        = "#f43f5e"

FONT = "Segoe UI"



def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def mesh_gradient(w: int, h: int, blobs=None, seed_dark=INK) -> Image.Image:
    """
    Soft colour blobs ko blur karke mesh-gradient banata hai.
    Yahi cheez UI ko depth deti hai — flat dark ki jagah.

    blobs = [(x_frac, y_frac, radius_frac, "#hex", strength 0-1), ...]
    """
    if blobs is None:
        blobs = [
            (0.15, 0.10, 0.55, VIOLET, 0.55),
            (0.90, 0.25, 0.50, CYAN,   0.30),
            (0.70, 0.95, 0.60, PINK,   0.35),
            (0.05, 0.85, 0.45, VIOLET, 0.30),
        ]

    # Chhota render karke upscale — blur fast aur smooth
    sw, sh = max(w // 6, 40), max(h // 6, 40)
    img = Image.new("RGB", (sw, sh), _hex(seed_dark))
    d = ImageDraw.Draw(img, "RGBA")

    for xf, yf, rf, col, strength in blobs:
        cx, cy = xf * sw, yf * sh
        r = rf * max(sw, sh)
        rgb = _hex(col)
        # Concentric rings = soft falloff
        steps = 26
        for i in range(steps, 0, -1):
            t = i / steps
            rad = r * t
            alpha = int(255 * strength * (1 - t) ** 2.2)
            if alpha <= 0:
                continue
            d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                      fill=(*rgb, alpha))

    img = img.filter(ImageFilter.GaussianBlur(sw / 9))
    img = img.resize((w, h), Image.LANCZOS)

    # Vignette — kinare gehre, beech ubhra hua
    vig = Image.new("L", (w, h), 0)
    vd = ImageDraw.Draw(vig)
    vd.ellipse([-w * 0.25, -h * 0.35, w * 1.25, h * 1.35], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(min(w, h) / 5))
    img = Image.composite(img, Image.new("RGB", (w, h), _hex(INK)), vig)

    return img


def noise_overlay(img: Image.Image, amount=5) -> Image.Image:
    """Halka grain — banding hatata hai, film jaisa texture deta hai."""
    import random
    w, h = img.size
    px = img.load()
    rnd = random.Random(7)
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            n = rnd.randint(-amount, amount)
            r, g, b = px[x, y]
            px[x, y] = (max(0, min(255, r + n)),
                        max(0, min(255, g + n)),
                        max(0, min(255, b + n)))
    return img


def glow_orb(size: int, color: str, strength=0.9) -> Image.Image:
    """Chamakta hua gol orb — logo/accent ke peeche lagane ke liye."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rgb = _hex(color)
    c = size / 2
    for i in range(40, 0, -1):
        t = i / 40
        r = c * t
        a = int(255 * strength * (1 - t) ** 2.5)
        d.ellipse([c - r, c - r, c + r, c + r], fill=(*rgb, a))
    return img.filter(ImageFilter.GaussianBlur(size / 12))


# ── Suno Studio Design System Compatibility ──────────────────────────────
THEME = {
    "bg": "#0f131d",
    "surface": "#161b29",
    "card": "#1d2335",
    "card_elevated": "#252c42",
    "card_border": "#353f5e",
    "card_border_glow": "#4d5b87",
    "input_bg": "#131724",
    "input_border": "#2e3752",
    "input_focus": "#38bdf8",
    "accent": "#22c55e",
    "accent_hover": "#4ade80",
    "accent_shadow": "#14532d",
    "accent_text": "#ffffff",
    "neon_lime": "#a3e635",
    "neon_lime_hover": "#bef264",
    "neon_lime_shadow": "#4d7c0f",
    "neon_lime_text": "#091403",
    "btn_indigo": "#6366f1",
    "btn_indigo_hover": "#818cf8",
    "btn_indigo_shadow": "#3730a3",
    "btn_indigo_text": "#ffffff",
    "btn_pink": "#ec4899",
    "btn_pink_hover": "#f472b6",
    "btn_pink_shadow": "#9d174d",
    "btn_pink_text": "#ffffff",
    "btn_amber": "#f59e0b",
    "btn_amber_hover": "#fbbf24",
    "btn_amber_shadow": "#b45309",
    "btn_amber_text": "#0f172a",
    "btn_cyan": "#0ea5e9",
    "btn_cyan_hover": "#38bdf8",
    "btn_cyan_shadow": "#0369a1",
    "btn_cyan_text": "#ffffff",
    "btn_purple": "#8b5cf6",
    "btn_purple_hover": "#a78bfa",
    "btn_purple_shadow": "#5b21b6",
    "btn_purple_text": "#ffffff",
    "btn_emerald": "#10b981",
    "btn_emerald_hover": "#34d399",
    "btn_emerald_shadow": "#065f46",
    "btn_emerald_text": "#ffffff",
    "secondary_btn": "#2b3248",
    "secondary_btn_hover": "#3a4462",
    "secondary_btn_border": "#4f5c84",
    "secondary_btn_shadow": "#171b28",
    "text": "#ffffff",
    "text_muted": "#a5b4cb",
    "text_dim": "#7c8ba6",
    "text_glow": "#ffffff",
    "success": "#22c55e",
    "success_shadow": "#14532d",
    "warning": "#f59e0b",
    "danger": "#ef4444",
    "danger_shadow": "#991b1b",
    "cyan": "#06b6d4",
    "pill_bg": "#1e293b",
    "pill_hover": "#334155",
    "pill_text": "#e2e8f0",
    "pill_border": "#475569",
    "accent_pill": "#14532d",
}

FONTS = {
    "brand": ("Segoe UI", 17, "bold"),
    "title": ("Segoe UI", 17, "bold"),
    "title_large": ("Segoe UI", 16, "bold"),
    "header": ("Segoe UI", 14, "bold"),
    "body": ("Segoe UI", 12),
    "body_bold": ("Segoe UI", 12, "bold"),
    "small": ("Segoe UI", 11),
    "small_bold": ("Segoe UI", 11, "bold"),
    "code": ("Consolas", 11),
    "btn_3d": ("Segoe UI", 14, "bold"),
    "btn_3d_large": ("Segoe UI", 15, "bold"),
    "btn_small": ("Segoe UI", 12, "bold")
}

def apply_app_theme():
    import customtkinter as ctk
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")

try:
    import customtkinter as ctk
    class CTk3DButton(ctk.CTkFrame):
        def __init__(self, master, text="BUTTON", command=None, width=140, height=42,
                     fg_color=None, hover_color=None, shadow_color=None, text_color="#ffffff",
                     font=None, corner_radius=10, border_width=1, border_color="", color=None, **kwargs):
            if color:
                c_key = f"btn_{color.lower()}"
                if c_key in THEME:
                    fg_color = fg_color or THEME[c_key]
                    hover_color = hover_color or THEME.get(f"{c_key}_hover", THEME[c_key])
                    shadow_color = shadow_color or THEME.get(f"{c_key}_shadow", "#1e1b4b")
                elif color.lower() in ("magenta", "pink"):
                    fg_color = fg_color or THEME.get("btn_pink", "#ec4899")
                    hover_color = hover_color or THEME.get("btn_pink_hover", "#f472b6")
                    shadow_color = shadow_color or THEME.get("btn_pink_shadow", "#9d174d")
                elif color.lower() == "emerald":
                    fg_color = fg_color or THEME.get("btn_emerald", "#10b981")
                    hover_color = hover_color or THEME.get("btn_emerald_hover", "#34d399")
                    shadow_color = shadow_color or THEME.get("btn_emerald_shadow", "#065f46")

            fg_color = fg_color or THEME.get("btn_indigo", "#6366f1")
            hover_color = hover_color or THEME.get("btn_indigo_hover", "#818cf8")
            shadow_color = shadow_color or THEME.get("btn_indigo_shadow", "#3730a3")
            font = font or FONTS.get("btn_3d", ("Segoe UI", 13, "bold"))

            frame_kwargs = {k: v for k, v in kwargs.items() if k in (
                "width", "height", "fg_color", "border_color", "border_width",
                "corner_radius", "bg_color"
            )}
            super().__init__(master, fg_color="transparent", width=width, height=height + 4, **frame_kwargs)
            self.grid_propagate(False)
            self.pack_propagate(False)
            self._cmd = command
            self._is_disabled = False

            self.shadow_frame = ctk.CTkFrame(self, fg_color=shadow_color, corner_radius=corner_radius, width=width, height=height)
            self.shadow_frame.place(x=0, y=4, relwidth=1.0, relheight=(height / (height + 4)))

            self.btn = ctk.CTkButton(self, text=text, command=self._on_click, width=width, height=height,
                                     fg_color=fg_color, hover_color=hover_color, text_color=text_color,
                                     font=font, corner_radius=corner_radius, border_width=border_width,
                                     border_color=border_color or hover_color)
            self.btn.place(x=0, y=0, relwidth=1.0, relheight=(height / (height + 4)))
            self.btn.bind("<ButtonPress-1>", self._on_press)
            self.btn.bind("<ButtonRelease-1>", self._on_release)

        def _on_press(self, event=None):
            if not self._is_disabled: self.btn.place_configure(y=2)
        def _on_release(self, event=None):
            if not self._is_disabled: self.btn.place_configure(y=0)
        def _on_click(self):
            if not self._is_disabled and self._cmd: self._cmd()
        def configure(self, **kwargs):
            if "text" in kwargs: self.btn.configure(text=kwargs.pop("text"))
            if "state" in kwargs:
                st = kwargs.pop("state")
                self._is_disabled = (st == "disabled")
                self.btn.configure(state=st)
            if "fg_color" in kwargs: self.btn.configure(fg_color=kwargs.pop("fg_color"))
            if "command" in kwargs: self._cmd = kwargs.pop("command")
            super().configure(**kwargs)
except Exception:
    pass

