"""
08_captions_generator.py — 💬 Captions Generator & Sequence Video Studio
══════════════════════════════════════════════════════════════════════════════
- Natural Numerical Sequence Sorting (Scene_1 to Scene_N)
- Live Interactive Canvas with Drag & Drop Positioning & Lock Toggles for
  both Logo and Captions!
- Speech-to-Text Transcription via Whisper AI with Word Timestamps
- 15+ CapCut Viral Subtitle Styles + 🎲 Random Per Scene Intelligent Mode
- One-Click Fast Hardware Accelerated Video Export
══════════════════════════════════════════════════════════════════════════════
"""

import os
import sys
import re
import time
import shutil
import threading
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import customtkinter as ctk
import tkinter as tk
from tkinter import Canvas, filedialog, messagebox
from PIL import Image, ImageTk

# Safe import of captions_generator_engine with self-contained fallback definitions
try:
    import captions_generator_engine as ce
except Exception:
    ce = None

RANDOM_PER_SCENE_KEY = getattr(ce, "RANDOM_PER_SCENE_KEY", "🎲 Random Per Scene (Different Style Every Scene)")
RANDOM_PER_CHUNK_KEY = getattr(ce, "RANDOM_PER_CHUNK_KEY", "🎲 Random Per Line (Different Style Every Phrase)")
RANDOM_FONT_KEY = getattr(ce, "RANDOM_FONT_KEY", "🎲 Random Font (Different Font Per Scene)")
AUTO_FONT_KEY = getattr(ce, "AUTO_FONT_KEY", "✨ Auto (Preset Curated Font)")
PRESET_CHOICES = getattr(ce, "PRESET_CHOICES", [
    RANDOM_PER_SCENE_KEY, RANDOM_PER_CHUNK_KEY, "CapCut Bold Yellow"
])
FONT_CHOICES = getattr(ce, "FONT_CHOICES", [AUTO_FONT_KEY, "Impact", "Montserrat", "Arial", "Anton", "Poppins"])
CAPCUT_PRESETS = getattr(ce, "CAPCUT_PRESETS", {
    "CapCut Bold Yellow": {
        "name": "CapCut Bold Yellow",
        "font": "Impact",
        "primary": "#FFFFFF",
        "highlight": "#FFE600",
        "outline": "#000000",
        "outline_w": 10,
        "shadow": 2,
        "box": False,
        "category": "Viral",
        "description": "Viral TikTok/CapCut standard: Electric yellow pop with 10px thick dark stroke."
    }
})

def clean_font_name(f):
    if hasattr(ce, "clean_font_name"):
        return ce.clean_font_name(f)
    return str(f).split()[0] if f else "Impact"

def _get_safe_output_dir() -> str:
    """Returns a writable directory for output videos, guaranteed not to crash in Program Files."""
    try:
        p = os.path.join(os.getcwd(), "videos_output")
        os.makedirs(p, exist_ok=True)
        test_file = os.path.join(p, ".perm_test")
        with open(test_file, "w") as f: f.write("ok")
        os.remove(test_file)
        return p
    except Exception:
        pass
    try:
        p = os.path.join(os.path.expanduser("~"), "Videos", "StoriesStudio")
        os.makedirs(p, exist_ok=True)
        return p
    except Exception:
        pass
    p = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "StoriesStudio", "output")
    try:
        os.makedirs(p, exist_ok=True)
    except Exception:
        pass
    return p

# Plugin Metadata for AI Editor / stories_app.py
TAB_TITLE = "💬  Captions Generator"
TAB_ORDER = 28
TAB_GROUP = ""
TAB_COLOR = ("#06b6d4", "#0891b2")
TAB_ICON  = "💬"
LAZY_LOAD = True

# Theme Colors (Dark Glassmorphic Palette)
C = {
    "bg": "#0b1020",
    "card": "#131b2e",
    "card_border": "#1e293b",
    "inner_bg": "#090d1a",
    "text": "#f8fafc",
    "dim": "#94a3b8",
    "accent_cyan": "#06b6d4",
    "accent_cyan_hov": "#0891b2",
    "accent_purple": "#8b5cf6",
    "accent_purple_hov": "#7c3aed",
    "accent_green": "#10b981",
    "accent_green_hov": "#059669",
    "accent_amber": "#f59e0b",
    "accent_amber_hov": "#d97706",
    "accent_red": "#ef4444",
    "accent_red_hov": "#dc2626",
    "btn_glass": "#1e293b",
    "btn_glass_hov": "#334155",
}

class CaptionsGeneratorTab(ctk.CTkFrame):
    """Full-featured, Crash-Proof Captions Generator Tab for AI Editor."""

    def __init__(self, parent, boot_data=None):
        super().__init__(parent, fg_color=C["bg"])
        self.boot_data = boot_data or {}

        # State Variables
        self.clip_paths: List[str] = []
        self.clip_metadata: List[Dict[str, Any]] = []
        self.transcribed_words: List[Dict[str, Any]] = []
        self.scene_boundaries: List[Dict[str, Any]] = []
        self.is_rendering = False
        self.last_merged_video: Optional[str] = None
        self.last_exported_video: Optional[str] = None

        # Interactive Drag & Drop Positions (fractions 0.0 to 1.0)
        # Default: Logo Top-Right (0.82, 0.07), Captions Bottom-Center (0.50, 0.82)
        self.custom_logo_pos: Tuple[float, float] = (0.82, 0.07)
        self.custom_caption_pos: Tuple[float, float] = (0.50, 0.82)
        self.logo_locked = False
        self.caption_locked = False

        # Canvas Dimensions & references
        self.cv_w = 280
        self.cv_h = 490
        self.active_drag_item = None
        self.bg_photo_ref = None

        # Build UI layout with fault protection
        try:
            self._build_ui()
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self._build_fallback_ui(str(ex))

    def _build_fallback_ui(self, err_msg: str):
        for w in self.winfo_children():
            try: w.destroy()
            except Exception: pass
        card = ctk.CTkFrame(self, fg_color="#181124", corner_radius=12, border_width=1, border_color="#e11d48")
        card.place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(card, text="⚠️ Captions Generator Notice", font=("Segoe UI", 14, "bold"), text_color="#fb7185").pack(padx=24, pady=(16, 6))
        ctk.CTkLabel(card, text=f"{err_msg}\n\nClick below to initialize.", font=("Consolas", 10), text_color="#cbd5e1", wraplength=480).pack(padx=24, pady=6)
        def _retry():
            try:
                card.destroy()
                self._build_ui()
            except Exception as e2:
                self._build_fallback_ui(str(e2))
        ctk.CTkButton(card, text="🔄 Retry", width=100, height=30, fg_color="#3b82f6", command=_retry).pack(pady=(6, 16))

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Main scrollable canvas container
        main_scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        main_scroll.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        main_scroll.grid_columnconfigure(0, weight=5)
        main_scroll.grid_columnconfigure(1, weight=6)

        # ── HEADER BAR ────────────────────────────────────────────────────────
        hdr_frame = ctk.CTkFrame(main_scroll, fg_color=C["card"], corner_radius=12, border_width=1, border_color=C["card_border"])
        hdr_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 10))

        hdr_box = ctk.CTkFrame(hdr_frame, fg_color="transparent")
        hdr_box.pack(fill="x", padx=16, pady=12)

        ctk.CTkLabel(
            hdr_box,
            text="💬  CAPTIONS GENERATOR & SEQUENCE STUDIO",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color=C["accent_cyan"]
        ).pack(side="left")

        ctk.CTkLabel(
            hdr_box,
            text="Scene Numerical Sorting • Live Canvas Drag & Lock • CapCut Viral Subtitles • GPU Export",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=C["dim"]
        ).pack(side="left", padx=14)

        # ══════════════════════════════════════════════════════════════════════
        # LEFT COLUMN (Clips Sequence + Logo Watermark)
        # ══════════════════════════════════════════════════════════════════════
        left_col = ctk.CTkFrame(main_scroll, fg_color="transparent")
        left_col.grid(row=1, column=0, sticky="nsew", padx=6, pady=0)
        left_col.grid_columnconfigure(0, weight=1)

        # ── CARD 1: SEQUENCE CLIPS ────────────────────────────────────────────
        clips_card = ctk.CTkFrame(left_col, fg_color=C["card"], corner_radius=12, border_width=1, border_color=C["card_border"])
        clips_card.pack(fill="x", pady=(0, 12))

        clips_hdr = ctk.CTkFrame(clips_card, fg_color="transparent")
        clips_hdr.pack(fill="x", padx=14, pady=(12, 6))

        ctk.CTkLabel(
            clips_hdr,
            text="🎬  1. Sequence Clips Manager",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=C["text"]
        ).pack(side="left")

        self.lbl_clips_count = ctk.CTkLabel(
            clips_hdr,
            text="0 Clips • 00:00 Total",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=C["accent_cyan"]
        )
        self.lbl_clips_count.pack(side="right")

        # Clips Action Bar (Add, Auto-Sort, Reverse, Clear)
        act_bar = ctk.CTkFrame(clips_card, fg_color="transparent")
        act_bar.pack(fill="x", padx=14, pady=4)

        ctk.CTkButton(
            act_bar,
            text="➕ Add Clips",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color=C["accent_cyan"],
            hover_color=C["accent_cyan_hov"],
            text_color="#000000",
            width=100,
            height=30,
            corner_radius=7,
            cursor="hand2",
            command=self._on_add_clips
        ).pack(side="left", padx=(0, 6))

        # 🔢 Numerical Sequence Auto-Sort Button (Scene_1 to Scene_N)
        ctk.CTkButton(
            act_bar,
            text="🔢 Sort: Scene_1 ➔ Scene_N",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#1e1b4b",
            hover_color="#312e81",
            text_color="#c7d2fe",
            border_width=1,
            border_color="#4338ca",
            height=30,
            corner_radius=7,
            cursor="hand2",
            command=self._on_sort_clips
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            act_bar,
            text="🔄 Flip",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=C["btn_glass"],
            hover_color=C["btn_glass_hov"],
            width=60,
            height=30,
            corner_radius=7,
            cursor="hand2",
            command=self._on_reverse_clips
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            act_bar,
            text="🧹 Clear",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=C["btn_glass"],
            hover_color=C["accent_red_hov"],
            text_color=C["dim"],
            width=60,
            height=30,
            corner_radius=7,
            cursor="hand2",
            command=self._on_clear_clips
        ).pack(side="left", padx=(0, 6))

        # Canvas Resolution Menu
        res_row = ctk.CTkFrame(clips_card, fg_color="transparent")
        res_row.pack(fill="x", padx=14, pady=(2, 6))

        ctk.CTkLabel(res_row, text="Canvas:", font=ctk.CTkFont(size=11), text_color=C["dim"]).pack(side="left", padx=(0, 6))
        self.res_var = ctk.StringVar(value="9:16 Vertical (1080x1920)")
        self.res_menu = ctk.CTkOptionMenu(
            res_row,
            variable=self.res_var,
            values=[
                "9:16 Vertical (1080x1920)",
                "16:9 Landscape (1920x1080)",
                "1:1 Square (1080x1080)",
                "Auto (Match First Clip)"
            ],
            width=210,
            height=28,
            fg_color=C["inner_bg"],
            button_color=C["btn_glass"],
            font=ctk.CTkFont(size=11),
            command=self._on_resolution_changed
        )
        self.res_menu.pack(side="left")

        # Scrollable list of clips
        self.clips_list_frame = ctk.CTkScrollableFrame(
            clips_card,
            fg_color=C["inner_bg"],
            height=210,
            corner_radius=8,
            border_width=1,
            border_color=C["card_border"]
        )
        self.clips_list_frame.pack(fill="x", padx=14, pady=(4, 14))

        self.lbl_empty_clips = ctk.CTkLabel(
            self.clips_list_frame,
            text="✨ No clips added yet.\nClick '➕ Add Clips' to load clips in Scene_1, Scene_2 order.",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=C["dim"],
            justify="center"
        )
        self.lbl_empty_clips.pack(pady=45)

        # ── CARD 2: LOGO WATERMARK ────────────────────────────────────────────
        logo_card = ctk.CTkFrame(left_col, fg_color=C["card"], corner_radius=12, border_width=1, border_color=C["card_border"])
        logo_card.pack(fill="x", pady=(0, 12))

        logo_hdr = ctk.CTkFrame(logo_card, fg_color="transparent")
        logo_hdr.pack(fill="x", padx=14, pady=(12, 6))

        ctk.CTkLabel(
            logo_hdr,
            text="🖼  2. Logo Watermark Settings",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=C["text"]
        ).pack(side="left")

        self.enable_logo_var = ctk.BooleanVar(value=True)
        self.switch_logo = ctk.CTkSwitch(
            logo_hdr,
            text="Enable Logo",
            variable=self.enable_logo_var,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=C["accent_cyan"],
            progress_color=C["accent_cyan"],
            command=self._on_toggle_logo
        )
        self.switch_logo.pack(side="right")

        # Logo file input row
        logo_row = ctk.CTkFrame(logo_card, fg_color="transparent")
        logo_row.pack(fill="x", padx=14, pady=4)

        self.entry_logo = ctk.CTkEntry(
            logo_row,
            placeholder_text="Select logo watermark file (.png, .jpg, .webp)...",
            fg_color=C["inner_bg"],
            border_color=C["card_border"],
            font=ctk.CTkFont(size=11),
            height=32
        )
        self.entry_logo.pack(side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(
            logo_row,
            text="📁 Browse",
            width=80,
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=C["btn_glass"],
            hover_color=C["btn_glass_hov"],
            cursor="hand2",
            command=self._on_browse_logo
        ).pack(side="right")

        # Sliders grid
        logo_grid = ctk.CTkFrame(logo_card, fg_color="transparent")
        logo_grid.pack(fill="x", padx=14, pady=(4, 6))
        logo_grid.grid_columnconfigure(0, weight=1)
        logo_grid.grid_columnconfigure(1, weight=1)

        self.lbl_logo_w = ctk.CTkLabel(logo_grid, text="Width: 160px", font=ctk.CTkFont(size=11), text_color=C["dim"])
        self.lbl_logo_w.grid(row=0, column=0, sticky="w", pady=2)
        self.slider_logo_w = ctk.CTkSlider(
            logo_grid,
            from_=40,
            to=400,
            number_of_steps=36,
            height=14,
            progress_color=C["accent_cyan"],
            command=self._on_logo_width_slider
        )
        self.slider_logo_w.set(160)
        self.slider_logo_w.grid(row=0, column=1, sticky="ew", pady=2)

        self.lbl_logo_op = ctk.CTkLabel(logo_grid, text="Opacity: 100%", font=ctk.CTkFont(size=11), text_color=C["dim"])
        self.lbl_logo_op.grid(row=1, column=0, sticky="w", pady=2)
        self.slider_logo_op = ctk.CTkSlider(
            logo_grid,
            from_=20,
            to=100,
            number_of_steps=16,
            height=14,
            progress_color=C["accent_cyan"],
            command=lambda v: self.lbl_logo_op.configure(text=f"Opacity: {int(v)}%")
        )
        self.slider_logo_op.set(100)
        self.slider_logo_op.grid(row=1, column=1, sticky="ew", pady=2)

        # ══════════════════════════════════════════════════════════════════════
        # RIGHT COLUMN (Interactive Canvas + Captions + Final Export)
        # ══════════════════════════════════════════════════════════════════════
        right_col = ctk.CTkFrame(main_scroll, fg_color="transparent")
        right_col.grid(row=1, column=1, sticky="nsew", padx=6, pady=0)
        right_col.grid_columnconfigure(0, weight=1)

        # ── CARD 3: LIVE INTERACTIVE CANVAS (DRAG & DROP + LOCK) ──────────────
        canvas_card = ctk.CTkFrame(right_col, fg_color=C["card"], corner_radius=12, border_width=1, border_color=C["card_border"])
        canvas_card.pack(fill="x", pady=(0, 12))

        cv_hdr = ctk.CTkFrame(canvas_card, fg_color="transparent")
        cv_hdr.pack(fill="x", padx=14, pady=(10, 4))

        ctk.CTkLabel(
            cv_hdr,
            text="🎯  3. Live Canvas: Drag & Lock Positions",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=C["accent_cyan"]
        ).pack(side="left")

        ctk.CTkLabel(
            cv_hdr,
            text="Click & drag Logo or Captions on video screen",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=C["dim"]
        ).pack(side="right")

        # Interactive Canvas Frame
        cv_wrapper = ctk.CTkFrame(canvas_card, fg_color="#070a14", corner_radius=8, border_width=1, border_color="#1e293b")
        cv_wrapper.pack(padx=14, pady=6)

        self.cv = Canvas(
            cv_wrapper,
            width=self.cv_w,
            height=self.cv_h,
            bg="#070a14",
            highlightthickness=0
        )
        self.cv.pack(padx=8, pady=8)

        # Bindings for mouse drag
        self.cv.bind("<Button-1>", self._on_canvas_press)
        self.cv.bind("<B1-Motion>", self._on_canvas_drag)
        self.cv.bind("<ButtonRelease-1>", self._on_canvas_release)

        # Interactive Canvas Controls Bar (Lock Toggles + Coordinate HUD)
        cv_ctrls = ctk.CTkFrame(canvas_card, fg_color="transparent")
        cv_ctrls.pack(fill="x", padx=14, pady=(2, 4))

        self.btn_lock_logo = ctk.CTkButton(
            cv_ctrls,
            text="🔓 Unlock Logo",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=C["btn_glass"],
            hover_color=C["btn_glass_hov"],
            width=115,
            height=28,
            command=self._toggle_lock_logo
        )
        self.btn_lock_logo.pack(side="left", padx=(0, 4))

        self.btn_lock_cap = ctk.CTkButton(
            cv_ctrls,
            text="🔓 Unlock Captions",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=C["btn_glass"],
            hover_color=C["btn_glass_hov"],
            width=125,
            height=28,
            command=self._toggle_lock_captions
        )
        self.btn_lock_cap.pack(side="left", padx=4)

        # Quick Alignment buttons for Logo & Captions
        q_row = ctk.CTkFrame(canvas_card, fg_color="transparent")
        q_row.pack(fill="x", padx=14, pady=(2, 6))

        ctk.CTkLabel(q_row, text="Quick Align:", font=ctk.CTkFont(size=10), text_color=C["dim"]).pack(side="left", padx=(0, 4))
        for lbl, qx, qy in [("Top-R", 0.82, 0.07), ("Top-L", 0.18, 0.07), ("Center", 0.50, 0.50), ("Bottom-R", 0.82, 0.85)]:
            ctk.CTkButton(
                q_row,
                text=lbl,
                width=50,
                height=24,
                font=ctk.CTkFont(size=9),
                fg_color=C["btn_glass"],
                hover_color=C["btn_glass_hov"],
                command=lambda x=qx, y=qy: self._set_quick_logo_pos(x, y)
            ).pack(side="left", padx=2)

        ctk.CTkLabel(q_row, text="| Cap:", font=ctk.CTkFont(size=10), text_color=C["dim"]).pack(side="left", padx=(6, 4))
        for lbl, qx, qy in [("Bottom", 0.50, 0.82), ("Mid", 0.50, 0.50), ("Top", 0.50, 0.15)]:
            ctk.CTkButton(
                q_row,
                text=lbl,
                width=50,
                height=24,
                font=ctk.CTkFont(size=9),
                fg_color=C["btn_glass"],
                hover_color=C["btn_glass_hov"],
                command=lambda x=qx, y=qy: self._set_quick_caption_pos(x, y)
            ).pack(side="left", padx=2)

        # Coordinate HUD readout
        self.lbl_hud_coords = ctk.CTkLabel(
            canvas_card,
            text=f"📍 Logo: (82% X, 7% Y) [🔓 Drag]  •  Captions: (50% X, 82% Y) [🔓 Drag]",
            font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
            text_color="#38bdf8"
        )
        self.lbl_hud_coords.pack(padx=14, pady=(2, 10))

        # ── CARD 4: CAPCUT STYLES & SPEECH TRANSCRIPTION ──────────────────────
        style_card = ctk.CTkFrame(right_col, fg_color=C["card"], corner_radius=12, border_width=1, border_color=C["card_border"])
        style_card.pack(fill="x", pady=(0, 12))

        st_hdr = ctk.CTkFrame(style_card, fg_color="transparent")
        st_hdr.pack(fill="x", padx=14, pady=(10, 4))

        ctk.CTkLabel(
            st_hdr,
            text="✨  4. CapCut Subtitle Styling & Whisper",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=C["text"]
        ).pack(side="left")

        # Preset Style Row
        p_row = ctk.CTkFrame(style_card, fg_color="transparent")
        p_row.pack(fill="x", padx=14, pady=3)

        ctk.CTkLabel(p_row, text="Preset Style:", font=ctk.CTkFont(size=11, weight="bold"), text_color=C["accent_amber"]).pack(side="left", padx=(0, 6))

        self.preset_var = ctk.StringVar(value="CapCut Bold Yellow")
        self.preset_menu = ctk.CTkOptionMenu(
            p_row,
            variable=self.preset_var,
            values=PRESET_CHOICES,
            width=280,
            height=28,
            fg_color="#1e1b4b",
            button_color="#312e81",
            button_hover_color="#4338ca",
            text_color="#f8fafc",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            command=self._on_preset_change
        )
        self.preset_menu.pack(side="left", fill="x", expand=True)

        self.lbl_preset_desc = ctk.CTkLabel(
            style_card,
            text="Viral TikTok/CapCut standard: Electric yellow pop with 10px thick dark stroke.",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=C["dim"],
            anchor="w"
        )
        self.lbl_preset_desc.pack(fill="x", padx=14, pady=(1, 4))

        # Typography grid (Words per line, case, font, size)
        typo_grid = ctk.CTkFrame(style_card, fg_color="transparent")
        typo_grid.pack(fill="x", padx=14, pady=2)
        typo_grid.grid_columnconfigure(0, weight=1)
        typo_grid.grid_columnconfigure(1, weight=1)
        typo_grid.grid_columnconfigure(2, weight=1)
        typo_grid.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(typo_grid, text="Words/Line:", font=ctk.CTkFont(size=10), text_color=C["dim"]).grid(row=0, column=0, sticky="w", pady=2)
        self.words_var = ctk.StringVar(value="3 Words")
        self.words_menu = ctk.CTkOptionMenu(
            typo_grid,
            variable=self.words_var,
            values=["1 Word (Rapid Pop)", "2 Words", "3 Words", "4 Words", "5 Words", "Auto (Full)"],
            height=24,
            fg_color=C["inner_bg"],
            button_color=C["btn_glass"],
            font=ctk.CTkFont(size=10)
        )
        self.words_menu.grid(row=0, column=1, sticky="ew", padx=2, pady=2)

        ctk.CTkLabel(typo_grid, text="Case:", font=ctk.CTkFont(size=10), text_color=C["dim"]).grid(row=0, column=2, sticky="w", padx=(6, 0), pady=2)
        self.case_var = ctk.StringVar(value="ALL CAPS")
        self.case_menu = ctk.CTkOptionMenu(
            typo_grid,
            variable=self.case_var,
            values=["ALL CAPS", "Title Case", "Normal"],
            height=24,
            fg_color=C["inner_bg"],
            button_color=C["btn_glass"],
            font=ctk.CTkFont(size=10),
            command=lambda v: self._redraw_canvas()
        )
        self.case_menu.grid(row=0, column=3, sticky="ew", padx=2, pady=2)

        ctk.CTkLabel(typo_grid, text="Font:", font=ctk.CTkFont(size=10), text_color=C["dim"]).grid(row=1, column=0, sticky="w", pady=2)
        self.font_var = ctk.StringVar(value="Impact")
        self.font_menu = ctk.CTkOptionMenu(
            typo_grid,
            variable=self.font_var,
            values=FONT_CHOICES,
            height=24,
            fg_color=C["inner_bg"],
            button_color=C["btn_glass"],
            font=ctk.CTkFont(size=10),
            command=lambda v: self._redraw_canvas()
        )
        self.font_menu.grid(row=1, column=1, sticky="ew", padx=2, pady=2)

        self.lbl_font_sz = ctk.CTkLabel(typo_grid, text="Size: 68pt", font=ctk.CTkFont(size=10), text_color=C["dim"])
        self.lbl_font_sz.grid(row=1, column=2, sticky="w", padx=(6, 0), pady=2)

        self.slider_font_sz = ctk.CTkSlider(
            typo_grid,
            from_=30,
            to=110,
            number_of_steps=40,
            height=12,
            progress_color=C["accent_amber"],
            command=self._on_font_size_slider
        )
        self.slider_font_sz.set(68)
        self.slider_font_sz.grid(row=1, column=3, sticky="ew", padx=2, pady=2)

        # 🛡 Anti-Shake & Zero-Jitter Protection Shield
        shake_row = ctk.CTkFrame(style_card, fg_color="transparent")
        shake_row.pack(fill="x", padx=14, pady=(4, 2))

        self.anti_shake_var = ctk.BooleanVar(value=True)
        self.chk_anti_shake = ctk.CTkCheckBox(
            shake_row,
            text="🛡  Anti-Shake Rock-Solid Captions (Zero Jitter & Flicker-Free)",
            variable=self.anti_shake_var,
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color="#10b981",
            fg_color="#10b981",
            hover_color="#059669",
            checkbox_width=16,
            checkbox_height=16,
            corner_radius=4
        )
        self.chk_anti_shake.pack(side="left")

        # Whisper AI Row
        w_row = ctk.CTkFrame(style_card, fg_color="transparent")
        w_row.pack(fill="x", padx=14, pady=(6, 2))

        ctk.CTkLabel(w_row, text="Whisper:", font=ctk.CTkFont(size=10), text_color=C["dim"]).pack(side="left", padx=(0, 4))
        self.model_var = ctk.StringVar(value="base")
        self.model_menu = ctk.CTkOptionMenu(w_row, variable=self.model_var, values=["base", "tiny", "small", "medium"], width=80, height=24, fg_color=C["inner_bg"], button_color=C["btn_glass"], font=ctk.CTkFont(size=10))
        self.model_menu.pack(side="left", padx=(0, 6))

        ctk.CTkLabel(w_row, text="Lang:", font=ctk.CTkFont(size=10), text_color=C["dim"]).pack(side="left", padx=(0, 4))
        self.lang_var = ctk.StringVar(value="Auto Detect")
        self.lang_menu = ctk.CTkOptionMenu(w_row, variable=self.lang_var, values=["Auto Detect", "Hindi", "English", "Hinglish/Urdu", "Spanish"], width=105, height=24, fg_color=C["inner_bg"], button_color=C["btn_glass"], font=ctk.CTkFont(size=10))
        self.lang_menu.pack(side="left", padx=(0, 6))

        self.btn_transcribe = ctk.CTkButton(
            w_row,
            text="🎙 Pre-Generate",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            fg_color=C["accent_purple"],
            hover_color=C["accent_purple_hov"],
            width=110,
            height=24,
            corner_radius=6,
            command=self._on_transcribe_click
        )
        self.btn_transcribe.pack(side="right")

        # Editable Captions text box
        self.txt_captions = ctk.CTkTextbox(
            style_card,
            height=60,
            fg_color=C["inner_bg"],
            border_color=C["card_border"],
            border_width=1,
            font=ctk.CTkFont(family="Consolas", size=10),
            text_color="#e2e8f0"
        )
        self.txt_captions.pack(fill="x", padx=14, pady=(4, 10))
        self.txt_captions.insert("1.0", "Captions extract automatically during export or click 'Pre-Generate'. You can also edit words here.")

        # ── CARD 5: FINAL EXPORT ──────────────────────────────────────────────
        export_card = ctk.CTkFrame(right_col, fg_color=C["card"], corner_radius=12, border_width=1, border_color=C["card_border"])
        export_card.pack(fill="x", pady=(0, 12))

        exp_hdr = ctk.CTkFrame(export_card, fg_color="transparent")
        exp_hdr.pack(fill="x", padx=14, pady=(10, 4))

        ctk.CTkLabel(
            exp_hdr,
            text="🚀  5. Video Export & Output",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=C["text"]
        ).pack(side="left")

        # Output folder row
        out_row = ctk.CTkFrame(export_card, fg_color="transparent")
        out_row.pack(fill="x", padx=14, pady=3)

        default_out_dir = _get_safe_output_dir()

        self.entry_out_dir = ctk.CTkEntry(
            out_row,
            placeholder_text="Output folder...",
            fg_color=C["inner_bg"],
            border_color=C["card_border"],
            font=ctk.CTkFont(size=11),
            height=30
        )
        self.entry_out_dir.insert(0, default_out_dir)
        self.entry_out_dir.pack(side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(
            out_row,
            text="📂 Open",
            width=65,
            height=30,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=C["btn_glass"],
            hover_color=C["btn_glass_hov"],
            command=self._open_exported_folder
        ).pack(side="right", padx=(4, 0))

        ctk.CTkButton(
            out_row,
            text="📁 Browse",
            width=70,
            height=30,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=C["btn_glass"],
            hover_color=C["btn_glass_hov"],
            command=self._on_choose_out_dir
        ).pack(side="right")

        # Filename row
        name_row = ctk.CTkFrame(export_card, fg_color="transparent")
        name_row.pack(fill="x", padx=14, pady=3)

        ctk.CTkLabel(name_row, text="Name:", font=ctk.CTkFont(size=11), text_color=C["dim"]).pack(side="left", padx=(0, 6))
        self.entry_filename = ctk.CTkEntry(
            name_row,
            fg_color=C["inner_bg"],
            border_color=C["card_border"],
            font=ctk.CTkFont(size=11),
            height=28
        )
        self.entry_filename.insert(0, f"Captions_Video_{time.strftime('%Y%m%d_%H%M%S')}.mp4")
        self.entry_filename.pack(side="left", fill="x", expand=True)

        # Big Glowing Action Button: EXPORT READY VIDEO
        self.btn_export = ctk.CTkButton(
            export_card,
            text="⚡ EXPORT FINAL VIDEO READY",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            fg_color=C["accent_green"],
            hover_color=C["accent_green_hov"],
            text_color="#ffffff",
            height=44,
            corner_radius=10,
            cursor="hand2",
            command=self._on_export_click
        )
        self.btn_export.pack(fill="x", padx=14, pady=(8, 4))

        # Progress bar & status
        self.progress_bar = ctk.CTkProgressBar(export_card, height=6, progress_color=C["accent_cyan"], fg_color=C["inner_bg"])
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", padx=14, pady=(2, 2))

        self.lbl_status = ctk.CTkLabel(
            export_card,
            text="Ready. Add clips in sequence and click '⚡ EXPORT FINAL VIDEO READY'.",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=C["dim"]
        )
        self.lbl_status.pack(padx=14, pady=(0, 4))

        # Completion Action Banner (embedded directly inside Card 5, 100% crash-proof)
        self.completion_banner = ctk.CTkFrame(
            export_card,
            fg_color="#064e3b",
            corner_radius=10,
            border_width=1,
            border_color="#059669"
        )

        self.lbl_done_title = ctk.CTkLabel(
            self.completion_banner,
            text="🎬  FINAL VIDEO EXPORT COMPLETE & READY!",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color="#34d399"
        )
        self.lbl_done_title.pack(pady=(8, 2))

        self.lbl_done_meta = ctk.CTkLabel(
            self.completion_banner,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color="#a7f3d0"
        )
        self.lbl_done_meta.pack(pady=(0, 6))

        btn_action_row = ctk.CTkFrame(self.completion_banner, fg_color="transparent")
        btn_action_row.pack(pady=(0, 8))

        ctk.CTkButton(
            btn_action_row,
            text="▶  Play Video",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            text_color="#ffffff",
            width=130,
            height=32,
            corner_radius=8,
            cursor="hand2",
            command=self._play_exported_video
        ).pack(side="left", padx=6)

        ctk.CTkButton(
            btn_action_row,
            text="📂 Open Output Folder",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="#1e293b",
            hover_color="#334155",
            text_color="#ffffff",
            width=150,
            height=32,
            corner_radius=8,
            cursor="hand2",
            command=self._open_exported_folder
        ).pack(side="left", padx=6)

        # Terminal log box
        self.log_box = ctk.CTkTextbox(
            export_card,
            height=75,
            fg_color=C["inner_bg"],
            border_color=C["card_border"],
            border_width=1,
            font=ctk.CTkFont(family="Consolas", size=9),
            text_color="#94a3b8"
        )
        self.log_box.pack(fill="x", padx=14, pady=(2, 10))

        # Initial Canvas Render
        self._redraw_canvas()

    # ══════════════════════════════════════════════════════════════════════════
    # INTERACTIVE CANVAS LOGIC (DRAG & DROP + REAL-TIME POSITION LOCK)
    # ══════════════════════════════════════════════════════════════════════════
    def _redraw_canvas(self):
        """Redraws background, rule-of-thirds grid, Logo box, and CapCut caption text safely."""
        try:
            self._do_redraw_canvas()
        except Exception as ex:
            print(f"[CANVAS ERROR] {ex}")

    def _do_redraw_canvas(self):
        self.cv.delete("all")

        # 1. Background image (from Clip 1 if available)
        first_clip = self.clip_paths[0] if self.clip_paths else None
        if first_clip and os.path.isfile(first_clip):
            try:
                temp_p = os.path.join(os.environ.get("TEMP", "temp"), "canvas_bg_thumb.jpg")
                ff_bin = getattr(ce, "FFMPEG_PATH", "ffmpeg") if ce else "ffmpeg"
                s_info = getattr(ce, "STARTUPINFO", None) if ce else None
                c_flags = getattr(ce, "CREATIONFLAGS", 0) if ce else 0
                subprocess.run([
                    ff_bin, "-y",
                    "-ss", "00:00:01",
                    "-i", first_clip,
                    "-vframes", "1",
                    "-s", f"{self.cv_w}x{self.cv_h}",
                    temp_p
                ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=s_info, creationflags=c_flags)
                if os.path.isfile(temp_p):
                    pil_img = Image.open(temp_p).resize((self.cv_w, self.cv_h))
                    self.bg_photo_ref = ImageTk.PhotoImage(pil_img)
                    self.cv.create_image(0, 0, anchor="nw", image=self.bg_photo_ref)
            except Exception:
                pass

        # 2. Rule of thirds grid lines
        for gx in (self.cv_w // 3, 2 * self.cv_w // 3):
            self.cv.create_line(gx, 0, gx, self.cv_h, fill="#1e293b", dash=(3, 3))
        for gy in (self.cv_h // 3, 2 * self.cv_h // 3):
            self.cv.create_line(0, gy, self.cv_w, gy, fill="#1e293b", dash=(3, 3))

        # 3. Logo Item
        if self.enable_logo_var.get():
            lx = self.custom_logo_pos[0] * self.cv_w
            ly = self.custom_logo_pos[1] * self.cv_h

            lw_scaled = max(40, min(100, int(int(self.slider_logo_w.get()) * (self.cv_w / 1080.0))))
            lh_scaled = int(lw_scaled * 0.5)

            border_c = "#10b981" if self.logo_locked else "#06b6d4"
            fill_c = "#0f231e" if self.logo_locked else "#081b29"

            self.cv.create_rectangle(
                lx - lw_scaled // 2, ly - lh_scaled // 2,
                lx + lw_scaled // 2, ly + lh_scaled // 2,
                fill=fill_c, outline=border_c, width=2,
                tags="logo_box"
            )
            lock_icon = "🔒" if self.logo_locked else "🖼"
            self.cv.create_text(
                lx, ly,
                text=f"{lock_icon} LOGO",
                fill=border_c, font=("Segoe UI", 9, "bold"),
                tags="logo_text"
            )

        # 4. Caption Item
        cx = self.custom_caption_pos[0] * self.cv_w
        cy = self.custom_caption_pos[1] * self.cv_h

        choice = self.preset_var.get()
        p_info = CAPCUT_PRESETS.get(choice, CAPCUT_PRESETS.get("CapCut Bold Yellow", {}))
        hl_color = p_info.get("highlight", "#FFE600")
        is_box = p_info.get("box", False)
        box_c = p_info.get("box_color", "#000000")

        sample_txt = "CAPCUT VIRAL POP"
        if choice == RANDOM_PER_SCENE_KEY:
            sample_txt = "🎲 RANDOM STYLE SCENE"
        elif choice == RANDOM_PER_CHUNK_KEY:
            sample_txt = "🎲 RANDOM STYLE LINE"

        user_t = self.txt_captions.get("1.0", "end").strip()
        if user_t and not user_t.startswith("Captions extract automatically"):
            sample_txt = " ".join(user_t.split()[:3])

        if "ALL" in self.case_var.get().upper():
            sample_txt = sample_txt.upper()

        fn_choice = self.font_var.get()
        if fn_choice in (AUTO_FONT_KEY, ""):
            fn = p_info.get("font", "Impact")
        elif fn_choice == RANDOM_FONT_KEY:
            fn = "Impact"
            sample_txt = f"🔤 {sample_txt}"
        else:
            fn = clean_font_name(fn_choice)

        fs = max(9, min(16, int(int(self.slider_font_sz.get()) * (self.cv_w / 1080.0))))

        text_color = hl_color
        fill_box = "#000000"
        if is_box:
            fill_box = box_c
            if str(box_c).upper() in ("#FFDE00", "#FFE600", "#FFFFFF"):
                text_color = "#000000"
            else:
                text_color = hl_color

        cap_t = self.cv.create_text(
            cx, cy,
            text=sample_txt,
            fill=text_color,
            font=(fn, fs, "bold"),
            tags="cap_text"
        )
        bb = self.cv.bbox(cap_t)
        if bb:
            cap_border = "#10b981" if self.caption_locked else ("#000000" if is_box and str(fill_box).upper() in ("#FFDE00", "#FFFFFF") else hl_color)
            cap_rect = self.cv.create_rectangle(
                bb[0] - 8, bb[1] - 4, bb[2] + 8, bb[3] + 4,
                fill=fill_box, outline=cap_border, width=2,
                tags="cap_box"
            )
            self.cv.tag_lower(cap_rect, cap_t)

        self._update_hud_label()

    def _update_hud_label(self):
        l_status = "🔒 Locked" if self.logo_locked else "🔓 Drag to move"
        c_status = "🔒 Locked" if self.caption_locked else "🔓 Drag to move"
        self.lbl_hud_coords.configure(
            text=f"📍 Logo: ({self.custom_logo_pos[0]*100:.0f}% X, {self.custom_logo_pos[1]*100:.0f}% Y) [{l_status}] • Captions: ({self.custom_caption_pos[0]*100:.0f}% X, {self.custom_caption_pos[1]*100:.0f}% Y) [{c_status}]"
        )

    def _on_canvas_press(self, e):
        lx = self.custom_logo_pos[0] * self.cv_w
        ly = self.custom_logo_pos[1] * self.cv_h
        cx = self.custom_caption_pos[0] * self.cv_w
        cy = self.custom_caption_pos[1] * self.cv_h

        dist_l = ((e.x - lx) ** 2 + (e.y - ly) ** 2) ** 0.5
        dist_c = ((e.x - cx) ** 2 + (e.y - cy) ** 2) ** 0.5

        if dist_l < 50 and not self.logo_locked and self.enable_logo_var.get():
            self.active_drag_item = "logo"
        elif dist_c < 60 and not self.caption_locked:
            self.active_drag_item = "caption"
        elif dist_l <= dist_c and not self.logo_locked and self.enable_logo_var.get():
            self.active_drag_item = "logo"
        elif not self.caption_locked:
            self.active_drag_item = "caption"
        else:
            self.active_drag_item = None

    def _on_canvas_drag(self, e):
        if self.active_drag_item == "logo" and not self.logo_locked:
            nx = max(20, min(self.cv_w - 20, e.x))
            ny = max(15, min(self.cv_h - 15, e.y))
            self.custom_logo_pos = (round(nx / float(self.cv_w), 4), round(ny / float(self.cv_h), 4))
            self._redraw_canvas()

        elif self.active_drag_item == "caption" and not self.caption_locked:
            nx = max(30, min(self.cv_w - 30, e.x))
            ny = max(15, min(self.cv_h - 15, e.y))
            self.custom_caption_pos = (round(nx / float(self.cv_w), 4), round(ny / float(self.cv_h), 4))
            self._redraw_canvas()

    def _on_canvas_release(self, e):
        self.active_drag_item = None

    def _toggle_lock_logo(self):
        self.logo_locked = not self.logo_locked
        self.btn_lock_logo.configure(
            text="🔒 Logo Locked" if self.logo_locked else "🔓 Unlock Logo",
            fg_color=C["accent_green"] if self.logo_locked else C["btn_glass"]
        )
        self._redraw_canvas()

    def _toggle_lock_captions(self):
        self.caption_locked = not self.caption_locked
        self.btn_lock_cap.configure(
            text="🔒 Captions Locked" if self.caption_locked else "🔓 Unlock Captions",
            fg_color=C["accent_green"] if self.caption_locked else C["btn_glass"]
        )
        self._redraw_canvas()

    def _set_quick_logo_pos(self, fx: float, fy: float):
        self.custom_logo_pos = (fx, fy)
        self._redraw_canvas()

    def _set_quick_caption_pos(self, fx: float, fy: float):
        self.custom_caption_pos = (fx, fy)
        self._redraw_canvas()

    def _on_resolution_changed(self, choice: str):
        if "16:9" in choice:
            self.cv_w, self.cv_h = 440, 248  # Landscape
        elif "1:1" in choice:
            self.cv_w, self.cv_h = 320, 320  # Square
        else:
            self.cv_w, self.cv_h = 280, 490  # 9:16 Vertical

        self.cv.configure(width=self.cv_w, height=self.cv_h)
        self._redraw_canvas()

    def _on_logo_width_slider(self, val):
        self.lbl_logo_w.configure(text=f"Width: {int(val)}px")
        self._redraw_canvas()

    def _on_font_size_slider(self, val):
        self.lbl_font_sz.configure(text=f"Size: {int(val)}pt")
        self._redraw_canvas()

    def _on_preset_change(self, choice: str):
        if choice == RANDOM_PER_SCENE_KEY:
            self.lbl_preset_desc.configure(
                text="🎲 Intelligent Mode: Har scene / clip pe alag CapCut viral style switch hoga!",
                text_color=C["accent_amber"]
            )
        elif choice == RANDOM_PER_CHUNK_KEY:
            self.lbl_preset_desc.configure(
                text="🎲 Dynamic Per Line: Har caption phrase pe naya CapCut viral style change hoga!",
                text_color=C["accent_cyan"]
            )
        else:
            p_info = CAPCUT_PRESETS.get(choice, {})
            self.lbl_preset_desc.configure(text=p_info.get("description", ""), text_color=C["dim"])
            # If on Auto font, sync to preset font
            if self.font_var.get() in (AUTO_FONT_KEY, "Impact", ""):
                self.font_var.set(p_info.get("font", "Impact"))
        self._redraw_canvas()

    # ══════════════════════════════════════════════════════════════════════════
    # CLIPS SEQUENCE MANAGEMENT & NATURAL NUMERICAL SORTING
    # ══════════════════════════════════════════════════════════════════════════
    def _on_add_clips(self):
        files = filedialog.askopenfilenames(
            title="Select Video Clips (Scene_1 to Scene_N)",
            filetypes=[("Video Files", "*.mp4;*.mov;*.mkv;*.avi;*.webm;*.flv;*.m4v"), ("All Files", "*.*")]
        )
        if not files:
            return

        import captions_generator_engine as ce
        # Natural alphanumeric sort: Scene_1 < Scene_2 < Scene_10
        sorted_files = sorted(files, key=ce.natural_sort_key)

        for f in sorted_files:
            p_abs = os.path.abspath(f)
            if p_abs not in self.clip_paths:
                self.clip_paths.append(p_abs)
                meta = ce.probe_clip(p_abs)
                self.clip_metadata.append(meta)

        self._refresh_clips_ui()
        self._redraw_canvas()
        self._log(f"✓ Added {len(sorted_files)} clips in natural sequence.")

    def _on_sort_clips(self):
        """Sort loaded clips strictly in mathematical sequence: Scene_1 to Scene_N."""
        if not self.clip_paths:
            return
        import captions_generator_engine as ce
        combined = list(zip(self.clip_paths, self.clip_metadata))
        combined.sort(key=lambda item: ce.natural_sort_key(item[0]))
        self.clip_paths = [c[0] for c in combined]
        self.clip_metadata = [c[1] for c in combined]
        self._refresh_clips_ui()
        self._redraw_canvas()
        self._log(f"🔢 Sequence Auto-Sorted: {len(self.clip_paths)} clips arranged numerically (Scene_1 to Scene_{len(self.clip_paths)}).")

    def _on_reverse_clips(self):
        if not self.clip_paths:
            return
        self.clip_paths.reverse()
        self.clip_metadata.reverse()
        self._refresh_clips_ui()
        self._redraw_canvas()
        self._log(f"🔄 Sequence Reversed: {len(self.clip_paths)} clips.")

    def _on_clear_clips(self):
        self.clip_paths.clear()
        self.clip_metadata.clear()
        self.transcribed_words.clear()
        self.scene_boundaries.clear()
        self._refresh_clips_ui()
        self._redraw_canvas()

    def _move_clip(self, idx: int, direction: int):
        new_idx = idx + direction
        if 0 <= new_idx < len(self.clip_paths):
            self.clip_paths[idx], self.clip_paths[new_idx] = self.clip_paths[new_idx], self.clip_paths[idx]
            self.clip_metadata[idx], self.clip_metadata[new_idx] = self.clip_metadata[new_idx], self.clip_metadata[idx]
            self._refresh_clips_ui()
            self._redraw_canvas()

    def _remove_clip(self, idx: int):
        if 0 <= idx < len(self.clip_paths):
            self.clip_paths.pop(idx)
            self.clip_metadata.pop(idx)
            self._refresh_clips_ui()
            self._redraw_canvas()

    def _refresh_clips_ui(self):
        for widget in self.clips_list_frame.winfo_children():
            widget.destroy()

        if not self.clip_paths:
            self.lbl_empty_clips = ctk.CTkLabel(
                self.clips_list_frame,
                text="✨ No clips added yet.\nClick '➕ Add Clips' to load clips in Scene_1, Scene_2 order.",
                font=ctk.CTkFont(family="Segoe UI", size=12),
                text_color=C["dim"],
                justify="center"
            )
            self.lbl_empty_clips.pack(pady=45)
            self.lbl_clips_count.configure(text="0 Clips • 00:00 Total")
            return

        import captions_generator_engine as ce
        total_sec = sum(m.get("duration", 0.0) for m in self.clip_metadata)
        self.lbl_clips_count.configure(text=f"{len(self.clip_paths)} Clips • {ce.format_seconds(total_sec)} Total")

        for idx, (path, meta) in enumerate(zip(self.clip_paths, self.clip_metadata)):
            row_card = ctk.CTkFrame(
                self.clips_list_frame,
                fg_color=C["card"],
                corner_radius=8,
                border_width=1,
                border_color=C["card_border"]
            )
            row_card.pack(fill="x", padx=4, pady=3)

            b_frame = ctk.CTkFrame(row_card, fg_color=C["btn_glass"], width=32, height=32, corner_radius=6)
            b_frame.pack(side="left", padx=(8, 8), pady=6)
            b_frame.pack_propagate(False)
            ctk.CTkLabel(b_frame, text=f"#{idx + 1}", font=ctk.CTkFont(size=11, weight="bold"), text_color=C["accent_cyan"]).pack(expand=True)

            info_box = ctk.CTkFrame(row_card, fg_color="transparent")
            info_box.pack(side="left", fill="both", expand=True, pady=4)

            fname = meta.get("filename", os.path.basename(path))
            if len(fname) > 34:
                fname = fname[:31] + "…"

            ctk.CTkLabel(info_box, text=f"Scene {idx + 1}: {fname}", font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), text_color=C["text"], anchor="w").pack(fill="x")
            detail_str = f"⏱ {meta.get('duration_str', '00:00')}  •  📐 {meta.get('width', 0)}x{meta.get('height', 0)}  •  📦 {meta.get('size_str', '0MB')}"
            ctk.CTkLabel(info_box, text=detail_str, font=ctk.CTkFont(family="Segoe UI", size=10), text_color=C["dim"], anchor="w").pack(fill="x")

            btn_box = ctk.CTkFrame(row_card, fg_color="transparent")
            btn_box.pack(side="right", padx=6, pady=4)

            ctk.CTkButton(
                btn_box, text="▲", width=26, height=26, font=ctk.CTkFont(size=10, weight="bold"),
                fg_color=C["btn_glass"], hover_color=C["btn_glass_hov"],
                state="normal" if idx > 0 else "disabled",
                command=lambda i=idx: self._move_clip(i, -1)
            ).pack(side="left", padx=2)

            ctk.CTkButton(
                btn_box, text="▼", width=26, height=26, font=ctk.CTkFont(size=10, weight="bold"),
                fg_color=C["btn_glass"], hover_color=C["btn_glass_hov"],
                state="normal" if idx < len(self.clip_paths) - 1 else "disabled",
                command=lambda i=idx: self._move_clip(i, 1)
            ).pack(side="left", padx=2)

            ctk.CTkButton(
                btn_box, text="🗑", width=26, height=26, font=ctk.CTkFont(size=11),
                fg_color="#3f1d24", hover_color=C["accent_red_hov"], text_color="#fca5a5",
                command=lambda i=idx: self._remove_clip(i)
            ).pack(side="left", padx=(4, 2))

    # ── LOGO & PRESET CONTROLS ────────────────────────────────────────────────
    def _on_toggle_logo(self):
        val = self.enable_logo_var.get()
        state = "normal" if val else "disabled"
        self.entry_logo.configure(state=state)
        self.slider_logo_w.configure(state=state)
        self.slider_logo_op.configure(state=state)
        self._redraw_canvas()

    def _on_browse_logo(self):
        f = filedialog.askopenfilename(
            title="Select Logo Image",
            filetypes=[("Image Files", "*.png;*.jpg;*.jpeg;*.webp;*.bmp"), ("All Files", "*.*")]
        )
        if f:
            self.entry_logo.delete(0, "end")
            self.entry_logo.insert(0, f)
            self._redraw_canvas()

    def _on_choose_out_dir(self):
        d = filedialog.askdirectory(title="Choose Output Folder")
        if d:
            self.entry_out_dir.delete(0, "end")
            self.entry_out_dir.insert(0, d)

    def _log(self, text: str):
        def _append():
            try:
                self.log_box.insert("end", f"{text}\n")
                self.log_box.see("end")
            except Exception:
                pass
        self.after(0, _append)

    def _set_status(self, text: str, progress: Optional[float] = None):
        def _update():
            try:
                self.lbl_status.configure(text=text)
                if progress is not None:
                    self.progress_bar.set(min(1.0, max(0.0, progress / 100.0)))
            except Exception:
                pass
        self.after(0, _update)

    # ── ON-DEMAND TRANSCRIBE ──────────────────────────────────────────────────
    def _on_transcribe_click(self):
        if not self.clip_paths:
            messagebox.showwarning("No Clips", "Please add video clips first.")
            return

        if self.is_rendering:
            return

        self.btn_transcribe.configure(state="disabled", text="⏳ Transcribing...")
        self.btn_export.configure(state="disabled")
        self.is_rendering = True

        def _worker():
            try:
                import importlib
                import captions_generator_engine as ce
                try: importlib.reload(ce)
                except Exception: pass
                self._log("🎙 Starting speech transcription with Whisper AI...")
                self._set_status("Extracting audio...", 20.0)

                temp_dir = os.path.join(os.environ.get("TEMP", "temp"), "captions_studio")
                os.makedirs(temp_dir, exist_ok=True)
                temp_merged = os.path.join(temp_dir, "temp_preview_merge.mp4")

                target_res = self._get_target_resolution_string()

                self._set_status("Merging clips sequence in numerical order...", 30.0)
                m_res = ce.merge_clips_sequence(
                    self.clip_paths,
                    temp_merged,
                    target_resolution=target_res,
                    log_callback=self._log,
                    progress_callback=lambda p, s: self._set_status(s, p)
                )

                if not m_res.get("success"):
                    self._log(f"❌ Error merging clips: {m_res.get('error')}")
                    self._set_status("Merge failed", 0.0)
                    return

                self.last_merged_video = m_res["output_path"]
                self.scene_boundaries = m_res.get("scene_boundaries", [])

                m_size = self.model_var.get()
                lang = self.lang_var.get()
                t_res = ce.transcribe_video_audio(
                    self.last_merged_video,
                    model_size=m_size,
                    language=lang,
                    log_callback=self._log,
                    progress_callback=lambda p, s: self._set_status(s, p)
                )

                if t_res.get("success"):
                    self.transcribed_words = t_res.get("words", [])
                    full_txt = t_res.get("text", "")
                    self._log(f"✓ Whisper finished successfully: {len(self.transcribed_words)} words.")
                    self._set_status(f"Transcribed {len(self.transcribed_words)} words ✓", 100.0)

                    def _populate_text():
                        self.txt_captions.delete("1.0", "end")
                        self.txt_captions.insert("1.0", full_txt)
                        self._redraw_canvas()
                    self.after(0, _populate_text)
                else:
                    self._log(f"⚠️ Transcription notice: {t_res.get('error')}")
                    self._set_status("Transcription notice", 0.0)

            except Exception as e:
                self._log(f"❌ Transcription exception: {e}")
                self._set_status("Error", 0.0)
            finally:
                self.is_rendering = False
                self.after(0, lambda: self.btn_transcribe.configure(state="normal", text="🎙 Pre-Generate"))
                self.after(0, lambda: self.btn_export.configure(state="normal"))

        threading.Thread(target=_worker, daemon=True).start()

    # ── FULL VIDEO EXPORT PIPELINE ────────────────────────────────────────────
    def _get_target_resolution_string(self) -> str:
        res_choice = self.res_var.get()
        if "16:9" in res_choice:
            return "1920x1080"
        elif "1:1" in res_choice:
            return "1080x1080"
        elif "Auto" in res_choice:
            return "original"
        return "1080x1920"

    def _on_export_click(self):
        if not self.clip_paths:
            messagebox.showwarning("No Clips", "Please add video clips before exporting.")
            return

        if self.is_rendering:
            return

        if hasattr(self, "completion_banner"):
            self.completion_banner.pack_forget()

        out_dir = self.entry_out_dir.get().strip()
        if not out_dir:
            out_dir = os.path.join(os.getcwd(), "videos_output")
        os.makedirs(out_dir, exist_ok=True)

        fname = self.entry_filename.get().strip()
        if not fname.endswith(".mp4"):
            fname += ".mp4"
        final_output_path = os.path.join(out_dir, fname)

        self.is_rendering = True
        self.btn_export.configure(state="disabled", text="⏳ EXPORTING VIDEO...")
        self.btn_transcribe.configure(state="disabled")

        def _export_thread():
            start_t = time.time()
            try:
                import importlib
                import captions_generator_engine as ce
                try: importlib.reload(ce)
                except Exception: pass
                self._log("═══════════════════════════════════════════════════════")
                self._log("⚡ STARTING CAPTIONS GENERATOR EXPORT PIPELINE")
                self._log("═══════════════════════════════════════════════════════")

                temp_dir = os.path.join(os.environ.get("TEMP", "temp"), "captions_studio")
                os.makedirs(temp_dir, exist_ok=True)
                merged_video_path = os.path.join(temp_dir, f"merged_seq_{int(time.time()*1000)}.mp4")

                target_res = self._get_target_resolution_string()

                # Step 1: Sequential Merge
                self._set_status("Step 1/4: Merging clips sequence in numerical order...", 10.0)
                m_res = ce.merge_clips_sequence(
                    self.clip_paths,
                    merged_video_path,
                    target_resolution=target_res,
                    log_callback=self._log,
                    progress_callback=lambda p, s: self._set_status(f"Step 1/4: {s}", p * 0.3)
                )

                if not m_res.get("success"):
                    raise RuntimeError(f"Clips merge failed: {m_res.get('error')}")

                merged_path = m_res["output_path"]
                total_duration = m_res["duration"]
                scene_boundaries = m_res.get("scene_boundaries", [])
                target_w = m_res.get("target_w", 1080)
                target_h = m_res.get("target_h", 1920)

                # Step 2: Speech Transcription (if not already transcribed)
                words = self.transcribed_words
                if not words:
                    self._set_status("Step 2/4: Transcribing speech with Whisper AI...", 35.0)
                    m_size = self.model_var.get()
                    lang = self.lang_var.get()
                    t_res = ce.transcribe_video_audio(
                        merged_path,
                        model_size=m_size,
                        language=lang,
                        log_callback=self._log,
                        progress_callback=lambda p, s: self._set_status(f"Step 2/4: {s}", 35.0 + p * 0.25)
                    )
                    if t_res.get("success"):
                        words = t_res.get("words", [])
                        self.transcribed_words = words
                    else:
                        self._log(f"⚠️ Speech transcription notice: {t_res.get('error')}")

                # Fallback words if silence / no speech detected
                if not words:
                    user_manual_text = self.txt_captions.get("1.0", "end").strip()
                    if user_manual_text and not user_manual_text.startswith("Captions extract automatically"):
                        manual_words = user_manual_text.split()
                        w_dur = max(0.4, total_duration / max(1, len(manual_words)))
                        words = [
                            {"word": mw, "start": round(idx_w * w_dur, 3), "end": round((idx_w + 1) * w_dur, 3)}
                            for idx_w, mw in enumerate(manual_words)
                        ]
                    else:
                        words = [
                            {"word": "CAPTIONS", "start": 0.5, "end": 1.5},
                            {"word": "READY", "start": 1.5, "end": 2.5}
                        ]

                # Step 3: Build CapCut ASS Subtitles (with custom dragged position)
                self._set_status("Step 3/4: Building CapCut viral subtitle script...", 65.0)
                ass_path = os.path.join(temp_dir, f"captions_{int(time.time()*1000)}.ass")
                preset_name = self.preset_var.get()

                w_str = self.words_var.get()
                w_per_line = 3
                if "1" in w_str: w_per_line = 1
                elif "2" in w_str: w_per_line = 2
                elif "3" in w_str: w_per_line = 3
                elif "4" in w_str: w_per_line = 4
                elif "5" in w_str: w_per_line = 5
                elif "Full" in w_str or "Auto" in w_str: w_per_line = 8

                c_case = self.case_var.get()
                c_font = self.font_var.get()
                c_size = int(self.slider_font_sz.get())

                ce.build_capcut_ass(
                    words=words,
                    total_duration=total_duration,
                    out_ass_path=ass_path,
                    video_w=target_w,
                    video_h=target_h,
                    preset_name=preset_name,
                    words_per_line=w_per_line,
                    text_case=c_case,
                    font_size_override=c_size,
                    font_name_override=c_font,
                    scene_boundaries=scene_boundaries,
                    custom_caption_pos=self.custom_caption_pos,
                    anti_shake=bool(self.anti_shake_var.get()) if hasattr(self, "anti_shake_var") else True,
                    log_callback=self._log
                )

                # Step 4: Burn Subtitles + Logo Watermark (with custom dragged position)
                self._set_status("Step 4/4: Burning captions & rendering final video...", 75.0)
                logo_p = self.entry_logo.get().strip() if self.enable_logo_var.get() else None
                logo_w = int(self.slider_logo_w.get())
                logo_op = float(self.slider_logo_op.get() / 100.0)

                b_res = ce.burn_logo_and_subtitles(
                    input_video=merged_path,
                    ass_path=ass_path,
                    output_video=final_output_path,
                    enable_logo=self.enable_logo_var.get(),
                    logo_path=logo_p,
                    logo_width=logo_w,
                    logo_opacity=logo_op,
                    custom_logo_pos=self.custom_logo_pos,
                    log_callback=self._log,
                    progress_callback=lambda p, s: self._set_status(f"Step 4/4: {s}", p)
                )

                if not b_res.get("success"):
                    raise RuntimeError(f"Burn pass failed: {b_res.get('error')}")

                for tf in [merged_video_path, ass_path]:
                    try:
                        if os.path.isfile(tf): os.remove(tf)
                    except Exception:
                        pass

                elapsed = time.time() - start_t
                self.last_exported_video = final_output_path
                self._log(f"🎉 EXPORT COMPLETE in {elapsed:.1f}s!")
                self._log(f"📁 Video Ready: {final_output_path}")
                self._set_status(f"✅ Video Ready! ({ce.format_bytes(os.path.getsize(final_output_path))})", 100.0)

                def _show_done_ui():
                    meta_str = f"Render Time: {elapsed:.1f}s  •  Size: {ce.format_bytes(os.path.getsize(final_output_path))}\nSaved: {os.path.basename(final_output_path)}"
                    self.lbl_done_meta.configure(text=meta_str)
                    self.completion_banner.pack(fill="x", padx=14, pady=(4, 6), before=self.log_box)

                self.after(0, _show_done_ui)

            except Exception as e:
                err_msg = str(e)
                self._log(f"❌ Export Failed: {err_msg}")
                self._set_status("Export Failed", 0.0)
                def _err(msg=err_msg):
                    messagebox.showerror("Export Failed", f"Video export failed:\n\n{msg}")
                self.after(0, _err)
            finally:
                self.is_rendering = False
                self.after(0, lambda: self.btn_export.configure(state="normal", text="⚡ EXPORT FINAL VIDEO READY"))
                self.after(0, lambda: self.btn_transcribe.configure(state="normal"))

        threading.Thread(target=_export_thread, daemon=True).start()

    def _play_exported_video(self):
        target = getattr(self, "last_exported_video", None)
        if not (target and os.path.isfile(target)):
            out_dir = self.entry_out_dir.get().strip() if hasattr(self, "entry_out_dir") else ""
            if not out_dir:
                out_dir = os.path.join(os.getcwd(), "videos_output")
            fname = self.entry_filename.get().strip() if hasattr(self, "entry_filename") else ""
            if fname:
                if not fname.endswith(".mp4"):
                    fname += ".mp4"
                cand = os.path.join(out_dir, fname)
                if os.path.isfile(cand):
                    target = cand
                    self.last_exported_video = cand

        if target and os.path.isfile(target):
            try:
                if hasattr(os, "startfile"):
                    os.startfile(os.path.normpath(target))
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", target])
                else:
                    subprocess.Popen(["xdg-open", target])
            except Exception as e:
                messagebox.showerror("Play Error", f"Could not launch video:\n{e}")
        else:
            messagebox.showinfo("Video Not Found", "Output video file not found.")

    def _open_exported_folder(self):
        target_video = getattr(self, "last_exported_video", None)
        out_dir = self.entry_out_dir.get().strip() if hasattr(self, "entry_out_dir") else ""
        if not out_dir:
            out_dir = os.path.join(os.getcwd(), "videos_output")

        target_file = None
        target_folder = None

        if target_video and os.path.isfile(target_video):
            target_file = os.path.abspath(target_video)
            target_folder = os.path.dirname(target_file)
        else:
            if hasattr(self, "entry_filename"):
                fname = self.entry_filename.get().strip()
                if fname:
                    if not fname.endswith(".mp4"):
                        fname += ".mp4"
                    cand = os.path.join(out_dir, fname)
                    if os.path.isfile(cand):
                        target_file = os.path.abspath(cand)
            target_folder = os.path.abspath(out_dir)

        if not target_folder:
            target_folder = os.path.abspath(os.path.join(os.getcwd(), "videos_output"))

        os.makedirs(target_folder, exist_ok=True)
        self._log(f"📂 Opening destination folder: {target_folder}")

        try:
            if sys.platform.startswith("win"):
                # If target file exists, highlight it in Explorer (token must be single without space after comma)
                if target_file and os.path.isfile(target_file):
                    try:
                        subprocess.Popen(f'explorer /select,"{os.path.normpath(target_file)}"')
                        return
                    except Exception:
                        pass

                # Direct folder open via native Windows ShellExecute
                if hasattr(os, "startfile"):
                    os.startfile(os.path.normpath(target_folder))
                else:
                    subprocess.Popen(f'explorer "{os.path.normpath(target_folder)}"')
            elif sys.platform == "darwin":
                if target_file and os.path.isfile(target_file):
                    subprocess.Popen(["open", "-R", target_file])
                else:
                    subprocess.Popen(["open", target_folder])
            else:
                subprocess.Popen(["xdg-open", target_folder])
        except Exception as e:
            try:
                if hasattr(os, "startfile") and os.path.isdir(target_folder):
                    os.startfile(os.path.normpath(target_folder))
                else:
                    messagebox.showerror("Folder Error", f"Could not open folder:\n{e}")
            except Exception as e2:
                messagebox.showerror("Folder Error", f"Could not open folder:\n{e2}")


def create(parent_frame, boot_data=None):
    """Factory mounting method called by plugin_loader.py."""
    tab = CaptionsGeneratorTab(parent_frame, boot_data=boot_data)
    tab.pack(fill="both", expand=True)
    return tab
