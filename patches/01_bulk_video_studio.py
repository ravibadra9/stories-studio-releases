"""
01_bulk_video_studio.py — Vibrant Studio, Emoji Supported & Collapsible Static Dashboard
Features:
- Collapsible Accordion Blocks with "▼ Extend" / "▲ Collapse" & Master "Expand All / Collapse All" Toggles
- 100% Emoji Support (Segoe UI Emoji seguiemj.ttf) — No Tofu Boxes for 👍, 🙏, ❤️, ✨, ⚡, 🎬, 🎵
- Remove / Clear Buttons for Floating CTA Banner, Uploaded Media, and Cutout Subjects
- Vibrant Modern Slate UI (Bright, Energetic & High-Contrast — Non-Gloomy Palette)
- Colorful 3D Floating Action Buttons (Indigo, Magenta, Emerald, Cyan, Gold)
- Large Bold Typography Across All Buttons & Interactive Controls
- Multi-Resolution Support: 720p (HD), 1080p (Full HD), 2K (1440p Quad HD), 4K (2160p Ultra HD)
- Customizable Render Quality (CRF 15-24), Audio Bitrate (128k-320k), and Frame Rate (24-60 FPS)
- Dual Studio Modes: "Image to Music" & "Video to Music" with AI Background Removal Cutout
- Automated YouTube Chapter Timestamps & Tracklist Sequence .txt Exporter
"""

TAB_TITLE = "⚡ Bulk Video Studio"
TAB_ORDER = 1
TAB_GROUP = ""
TAB_ICON = "⚡"

import re
import os
import sys
import time
import math
import copy
import json
import random
import threading
import subprocess
import tkinter as tk
import customtkinter as ctk
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from tkinter import filedialog
from PIL import Image, ImageTk, ImageDraw, ImageFont

import concurrent.futures
from ui_theme import THEME, FONTS, CTk3DButton
from suno_api import SunoAPI
from config_manager import load_config, save_config, get_downloads_dir, get_config_dir
from video_engine import (
    render_dual_variant_video,
    calculate_album_schedule,
    resolve_font_file,
    remove_image_background,
    export_timestamp_metadata,
    detect_hardware_acceleration
)


def parse_songs_text(raw_text: str) -> List[Dict[str, str]]:
    """Parses pasted text containing headers like 'Song 1', 'Song 2', etc."""
    if not raw_text or not raw_text.strip():
        return []

    lines = raw_text.strip().split("\n")
    songs = []
    current_title = ""
    current_lyrics_lines = []

    header_pattern = re.compile(r'^\s*\[?\s*(?:Song|Track)?\s*(\d+)[:\-\.\s]*(.*?)\]?\s*$', re.IGNORECASE)

    for line in lines:
        stripped = line.strip()
        is_header = False
        match = header_pattern.match(line)
        if match:
            lower = stripped.lower()
            if lower.startswith("song") or lower.startswith("track") or stripped.startswith("["):
                is_header = True

        if is_header:
            if current_title or current_lyrics_lines:
                lyrics_text = "\n".join(current_lyrics_lines).strip()
                if lyrics_text or current_title:
                    songs.append({
                        "title": current_title if current_title else f"Song {len(songs)+1}",
                        "lyrics": lyrics_text
                    })
                current_lyrics_lines = []

            song_num = match.group(1)
            extra_title = match.group(2).strip(" -:[]")
            if extra_title:
                current_title = f"Song {song_num} - {extra_title}"
            else:
                current_title = f"Song {song_num}"
        else:
            current_lyrics_lines.append(line)

    if current_title or current_lyrics_lines:
        lyrics_text = "\n".join(current_lyrics_lines).strip()
        if lyrics_text or current_title:
            songs.append({
                "title": current_title if current_title else f"Song {len(songs)+1}",
                "lyrics": lyrics_text
            })

    return songs


def analyze_lyrics(raw_text: str) -> Dict[str, Any]:
    """
    Analyzes bulk lyrics in real time:
    - Counts detected songs
    - Counts words, characters, non-space characters, and lines for each song
    - Calculates total album words, characters, and estimated audio runtime
    - Evaluates song length health (Ideal, Short, Long)
    """
    songs = parse_songs_text(raw_text)
    total_words = 0
    total_chars = 0
    total_chars_no_space = 0
    total_lines = 0

    song_details = []
    for idx, song in enumerate(songs, 1):
        lyrics = song.get("lyrics", "")
        title = song.get("title", f"Song {idx}")

        words = len(re.findall(r'\b\w+\b', lyrics))
        chars = len(lyrics)
        chars_no_space = len(lyrics.replace(" ", "").replace("\n", "").replace("\r", ""))
        lines = len([l for l in lyrics.split("\n") if l.strip()])

        # Estimate duration (~35-40 words per minute for worship songs)
        est_seconds = max(60, int(words * 2.2 + 30)) if words > 0 else 0
        est_min = est_seconds // 60
        est_sec = est_seconds % 60
        est_time_str = f"{est_min}:{est_sec:02d}"

        # Health status check
        if words == 0:
            health = ("⚠️ No Lyrics", "#ef4444")
        elif words < 25:
            health = ("⚠️ Short", "#f59e0b")
        elif words > 450:
            health = ("⚠️ Very Long", "#f97316")
        else:
            health = ("✅ Ideal Length", "#4ade80")

        total_words += words
        total_chars += chars
        total_chars_no_space += chars_no_space
        total_lines += lines

        song_details.append({
            "idx": idx,
            "title": title,
            "words": words,
            "chars": chars,
            "chars_no_space": chars_no_space,
            "lines": lines,
            "est_time": est_time_str,
            "est_seconds": est_seconds,
            "health": health
        })

    tot_est_sec = sum(s["est_seconds"] for s in song_details)
    tot_est_min = tot_est_sec // 60
    tot_est_s = tot_est_sec % 60
    tot_runtime_str = f"{tot_est_min}:{tot_est_s:02d}" if tot_est_sec > 0 else "0:00"

    return {
        "song_count": len(songs),
        "total_words": total_words,
        "total_chars": total_chars,
        "total_chars_no_space": total_chars_no_space,
        "total_lines": total_lines,
        "total_runtime_str": tot_runtime_str,
        "songs": song_details
    }


def hex_to_rgb(hex_str: str) -> Tuple[int, int, int]:
    """Converts hex color '#EAB308' to RGB tuple."""
    clean = hex_str.replace("#", "").replace("0x", "")
    if len(clean) == 3:
        clean = "".join([c*2 for c in clean])
    if len(clean) < 6:
        return (255, 255, 255)
    return (int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16))


# Segoe UI Emoji Font Resolver for Native Emoji Rendering
EMOJI_FONT_PATH = "C:/Windows/Fonts/seguiemj.ttf"

def get_emoji_pil_font(size: int) -> ImageFont.ImageFont:
    """Returns Segoe UI Emoji truetype font if available for full emoji rendering."""
    if os.path.exists(EMOJI_FONT_PATH):
        try:
            return ImageFont.truetype(EMOJI_FONT_PATH, size)
        except Exception:
            pass
    try:
        return ImageFont.truetype("seguiemj.ttf", size)
    except Exception:
        return ImageFont.load_default()


def find_cached_audio_for_title(title: str, out_folder: Optional[Path] = None) -> Tuple[Optional[str], Optional[str]]:
    """
    Searches known cache and download directories for pre-existing Track 1 & Track 2 MP3 files.
    Returns (v1_path, v2_path) if found, else (None, None).
    """
    clean_t = "".join(c for c in title if c.isalnum() or c in (" ", "_", "-")).strip().lower()
    if not clean_t:
        return None, None

    search_dirs = []
    if out_folder:
        search_dirs.extend([out_folder / "temp_audio_cache", out_folder / "cache", out_folder])
    
    app_downloads = get_downloads_dir()
    search_dirs.extend([app_downloads / "cache", app_downloads / "temp_audio_cache", app_downloads])

    # Local workspace downloads directory
    local_down = Path(__file__).resolve().parent.parent / "downloads"
    search_dirs.extend([local_down / "cache", local_down / "temp_audio_cache", local_down])

    # De-duplicate directories while preserving search order
    seen_dirs = set()
    valid_dirs = []
    for d in search_dirs:
        try:
            rp = str(d.resolve())
            if rp not in seen_dirs and d.exists():
                seen_dirs.add(rp)
                valid_dirs.append(d)
        except Exception:
            pass

    # Exact or standard sanitized filename check
    for d in valid_dirs:
        p1 = d / f"{clean_t}_Track1.mp3"
        p2 = d / f"{clean_t}_Track2.mp3"
        if p1.exists() and p1.stat().st_size > 10000:
            return str(p1), str(p2 if p2.exists() and p2.stat().st_size > 10000 else p1)

    # Fuzzy/prefix search within cache directory
    for d in valid_dirs:
        try:
            for mp3_file in d.glob("*.mp3"):
                stem_clean = "".join(c for c in mp3_file.stem if c.isalnum() or c in (" ", "_", "-")).strip().lower()
                if clean_t in stem_clean or (len(clean_t) >= 6 and stem_clean.startswith(clean_t[:15])):
                    if mp3_file.stat().st_size > 10000:
                        track2_name = mp3_file.name.replace("Track1", "Track2").replace("track1", "track2")
                        p2 = d / track2_name
                        return str(mp3_file), str(p2 if p2.exists() and p2.stat().st_size > 10000 else mp3_file)
        except Exception:
            pass

    return None, None


# ════════════════════════════════════════════════════════════════
# COLLAPSIBLE ACCORDION CARD COMPONENT ("▼ Extend" / "▲ Collapse")
# ════════════════════════════════════════════════════════════════

class CollapsibleCard(ctk.CTkFrame):
    def __init__(
        self,
        master,
        title: str,
        icon: str = "📁",
        badge_text: str = "",
        badge_color: str = "#38bdf8",
        default_expanded: bool = False,
        **kwargs
    ):
        super().__init__(
            master,
            fg_color=THEME["card"],
            corner_radius=12,
            border_width=1,
            border_color=THEME["card_border"],
            **kwargs
        )
        self.pack(fill="x", padx=12, pady=4)
        
        self.title_str = title
        self.icon_str = icon
        self.is_expanded = default_expanded

        # Header Bar
        self.header = ctk.CTkFrame(self, fg_color="transparent", height=40)
        self.header.pack(fill="x", padx=12, pady=6)
        self.header.grid_columnconfigure(1, weight=1)

        # Title Label
        self.lbl_title = ctk.CTkLabel(
            self.header,
            text=f"{icon}  {title}",
            font=FONTS["body_bold"],
            text_color=THEME["text"]
        )
        self.lbl_title.grid(row=0, column=0, sticky="w", padx=(0, 8))

        # Badge Pill
        self.lbl_badge = ctk.CTkLabel(
            self.header,
            text=badge_text,
            font=FONTS["small_bold"],
            text_color=badge_color,
            anchor="w"
        )
        self.lbl_badge.grid(row=0, column=1, sticky="w")

        # Extend / Collapse Button
        self.btn_toggle = ctk.CTkButton(
            self.header,
            text="▲ Collapse" if default_expanded else "▼ Extend",
            width=95,
            height=28,
            fg_color=THEME["btn_indigo"] if default_expanded else THEME["secondary_btn"],
            hover_color=THEME["btn_indigo_hover"],
            text_color="#ffffff",
            font=FONTS["btn_small"],
            corner_radius=6,
            command=self.toggle
        )
        self.btn_toggle.grid(row=0, column=2, sticky="e")

        # Body Container
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        if default_expanded:
            self.body.pack(fill="x", padx=12, pady=(0, 10))

    def toggle(self):
        if self.is_expanded:
            self.collapse()
        else:
            self.expand()

    def expand(self):
        self.is_expanded = True
        self.body.pack(fill="x", padx=12, pady=(0, 10))
        self.btn_toggle.configure(text="▲ Collapse", fg_color=THEME["btn_indigo"])

    def collapse(self):
        self.is_expanded = False
        self.body.pack_forget()
        self.btn_toggle.configure(text="▼ Extend", fg_color=THEME["secondary_btn"])

    def set_badge(self, text: str, color: Optional[str] = None):
        self.lbl_badge.configure(text=text)
        if color:
            self.lbl_badge.configure(text_color=color)


def create(parent_frame, boot_data=None):
    boot_data = boot_data or {}
    config = load_config()

    # Main Grid Container (Clean Vibrant Slate)
    container = ctk.CTkFrame(parent_frame, fg_color=THEME["bg"], corner_radius=0)
    container.pack(fill="both", expand=True)
    container.grid_columnconfigure(0, weight=5, minsize=520)  # Left panel (Collapsible Static Dashboard)
    container.grid_columnconfigure(1, weight=6, minsize=560)  # Right panel (Preview & Live Monitor)
    container.grid_rowconfigure(0, weight=1)

    # ════════════════════════════════════════════════════════════════
    # STATE VARIABLES
    # ════════════════════════════════════════════════════════════════
    studio_mode_var = ctk.StringVar(value="video_to_music")

    # Image Mode Assets (Legacy fallbacks)
    img1_path_var = ctk.StringVar(value="")
    img2_path_var = ctk.StringVar(value="")
    
    # Video Mode Assets (Dual Video Backgrounds)
    bg_video_path_var = ctk.StringVar(value="")
    vid2_path_var = ctk.StringVar(value="")
    fg_image_path_var = ctk.StringVar(value="")
    fg_cutout_path_var = ctk.StringVar(value="")
    fg_scale_var = ctk.IntVar(value=100)
    
    logo_path_var = ctk.StringVar(value="")
    logo_scale_var = ctk.IntVar(value=100)
    
    # Audio Source Mode (Suno AI Generation vs Premade Local Audio Tracks)
    audio_source_mode_var = ctk.StringVar(value="suno_generate")
    premade_songs_list = []  # List of dicts: {"title": ..., "v1_file": ..., "v2_file": ..., "v1_name": ..., "v2_name": ..., "is_paired": bool}
    premade_folder_path_var = ctk.StringVar(value="")


    preview_mode_var = ctk.StringVar(value="Video 1")
    lock_positions_var = ctk.BooleanVar(value=False)
    
    # CTA Floating Banner Controls
    show_banner_var = ctk.BooleanVar(value=True)
    animate_banner_var = ctk.BooleanVar(value=True)
    BANNER_ANIM_MODES = [
        "🚀 Drop & Vanish (Periodic Slide Down, Hold, Vanish)",
        "✨ Ambient Float (Continuous Gentle Hover)",
        "📌 Static Fixed (Always Visible)"
    ]
    banner_anim_mode_var = ctk.StringVar(value=BANNER_ANIM_MODES[0])

    # Output Save Directory & Custom Filename Controls
    default_out_dir = str(get_downloads_dir())
    out_dir_var = ctk.StringVar(value=default_out_dir)
    v1_filename_var = ctk.StringVar(value="Video_1_Variant_1.mp4")
    v2_filename_var = ctk.StringVar(value="Video_2_Variant_2.mp4")
    export_txt_var = ctk.BooleanVar(value=True)

    # Resolution & Output Quality Options
    RESOLUTIONS_LIST = [
        "1080p Full HD (1920x1080)",
        "720p HD (1280x720)",
        "2K Quad HD (2560x1440)",
        "4K Ultra HD (3840x2160)"
    ]
    resolution_var = ctk.StringVar(value=RESOLUTIONS_LIST[0])

    QUALITY_PRESETS = [
        "Balanced (Recommended)",
        "High Speed (Smaller File)",
        "Ultra Quality (Crisp Master)",
        "Maximum Quality (Near Lossless)"
    ]
    quality_var = ctk.StringVar(value=QUALITY_PRESETS[0])

    BITRATES_LIST = ["192k (High Quality)", "320k (Studio Hi-Fi)", "128k (Standard)"]
    audio_bitrate_var = ctk.StringVar(value=BITRATES_LIST[0])

    FPS_LIST = ["30 FPS (Standard YouTube)", "60 FPS (Ultra Smooth)", "24 FPS (Cinematic)"]
    fps_var = ctk.StringVar(value=FPS_LIST[0])

    # GPU Hardware Acceleration & Multi-Threaded Parallel Rendering
    hw_info = detect_hardware_acceleration()
    GPU_MODES = [
        f"⚡ Auto-Detect ({hw_info.get('encoder', 'libx264')})",
        "⚡ NVIDIA NVENC (h264_nvenc)",
        "⚡ Intel QuickSync (h264_qsv)",
        "⚡ AMD AMF (h264_amf)",
        "💻 CPU Multi-Threaded (libx264)"
    ]
    gpu_mode_var = ctk.StringVar(value=GPU_MODES[0])
    parallel_render_var = ctk.BooleanVar(value=False)  # Default False (Sequential Safe Mode) to prevent 100% GPU BSOD crashes
    use_cache_var = ctk.BooleanVar(value=True)        # Auto-pick cached songs if already generated/downloaded

    # Background Video Motion Effects
    BG_EFFECTS = [
        "Cinematic Slow Zoom (Ken Burns)",
        "Audio Bass Pulse & Zoom",
        "Floating Light Leaks & Dust",
        "Ambient Breathing Glow",
        "Slow Panoramic Drift",
        "Slow Celestial Rise",
        "Static Image (No Motion)"
    ]
    bg_effect_var = ctk.StringVar(value=BG_EFFECTS[0])

    # Typography & Color Options
    FONT_FAMILIES = [
        "Segoe UI", "Outfit", "Inter", "Montserrat", "Poppins", "Roboto",
        "Arial", "Georgia", "Impact", "Consolas", "Calibri"
    ]
    font_family_var = ctk.StringVar(value="Segoe UI")
    font_size_var = ctk.IntVar(value=42)
    font_bold_var = ctk.BooleanVar(value=True)
    font_italic_var = ctk.BooleanVar(value=False)
    text_shadow_var = ctk.BooleanVar(value=True)

    COLOR_PRESETS = [
        ("Gold Worship", "#EAB308"),
        ("Pure White", "#FFFFFF"),
        ("Neon Lime", "#BEF264"),
        ("Cyber Cyan", "#38BDF8"),
        ("Sunset Coral", "#F97316"),
        ("Rose Pink", "#F43F5E"),
        ("Purple Glow", "#A855F7"),
        ("Emerald Green", "#10B981")
    ]
    title_color_var = ctk.StringVar(value="#FFFFFF")
    subtitle_color_var = ctk.StringVar(value="#94A3B8")
    accent_color_var = ctk.StringVar(value="#EAB308")

    PLAYER_STYLES = [
        "🌟 Circular Spinning Disc (Rotating Logo Vinyl)",
        "✨ Border-Free Glass Minimal (Centered)",
        "🎧 Studio Bottom Left Clean",
        "⚡ Floating Modern Pill (Border-Free)",
        "🎵 Clean Broadcast Bar (Bottom Edge)",
        "✝ Worship Golden Luxe"
    ]
    player_style_var = ctk.StringVar(value=PLAYER_STYLES[0])

    VIZ_STYLES = [
        "Neon Spectrum Bars",
        "Glowing Waveform Line",
        "Mirrored Dual Spectrum",
        "Circular / Radial Spectrum",
        "Musical Spectrum (ShowCQT)",
        "LED Studio Peak Meter",
        "None"
    ]
    viz_style_var = ctk.StringVar(value=VIZ_STYLES[0])
    viz_color_var = ctk.StringVar(value="#EAB308")

    # 1080p Coordinates
    DEFAULT_POS_1080 = {
        "banner": [360, 50],
        "logo": [1720, 50],
        "text": [60, 860],
        "viz": [320, 960],
        "subject": [660, 260]
    }
    pos_1080 = {k: list(v) for k, v in DEFAULT_POS_1080.items()}
    active_drag_elem = {"name": None, "offset_x": 0, "offset_y": 0}

    # Dual Channel Independent Profile Dictionaries
    def create_default_profile(name="Video 1"):
        is_v1 = (name == "Video 1")
        return {
            "name": name,
            "mode": "video_to_music",
            "img_path": "",
            "bg_video": "",
            "fg_image": "",
            "fg_cutout": "",
            "fg_scale": 100,
            "logo_path": "",
            "logo_scale": 100,
            "bg_effect": "Cinematic Slow Zoom (Ken Burns)",
            "title_color": "#FFFFFF" if is_v1 else "#38BDF8",
            "subtitle_color": "#94A3B8" if is_v1 else "#67E8F9",
            "accent_color": "#EAB308" if is_v1 else "#38BDF8",
            "font_family": "Segoe UI",
            "font_size": 42,
            "font_bold": True,
            "font_italic": False,
            "text_shadow": True,
            "player_style": PLAYER_STYLES[0] if is_v1 else PLAYER_STYLES[1],
            "viz_style": "Neon Spectrum Bars" if is_v1 else "Glowing Waveform Line",
            "viz_color": "#BEF264" if is_v1 else "#38BDF8",
            "show_banner": True,
            "banner_top": "🌈🙏 Thank you for worshipping with us! 🙏🌈" if is_v1 else "🎧🔥 Stream the Full Album in High Fidelity! 🔥🎧",
            "banner_bot": "👍✨ Please Like & Subscribe 🔔❤️" if is_v1 else "⚡ Hit Subscribe for Daily Beats 🔔",
            "banner_anim": "🚀 Drop & Vanish (Periodic Slide Down, Hold, Vanish)",
            "positions": {k: list(v) for k, v in DEFAULT_POS_1080.items()}
        }

    channel_profiles = {
        "video_1": create_default_profile("Video 1"),
        "video_2": create_default_profile("Video 2")
    }
    active_profile_key = ["video_1"]

    # Canvas scale (640x360 -> 1920x1080)
    CW, CH = 640, 360
    SCALE = 1920.0 / CW  # 3.0

    # ════════════════════════════════════════════════════════════════
    # LEFT PANEL: STATIC COLLAPSIBLE DASHBOARD WITH EXTEND BUTTONS
    # ════════════════════════════════════════════════════════════════
    left_scroll = ctk.CTkScrollableFrame(
        container,
        fg_color=THEME["surface"],
        corner_radius=16,
        border_width=1,
        border_color=THEME["card_border"]
    )
    left_scroll.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)
    left_scroll.grid_columnconfigure(0, weight=1)

    # Master Top Action & Accordion Toolbar
    top_toolbar = ctk.CTkFrame(left_scroll, fg_color=THEME["card"], corner_radius=12, border_width=1, border_color=THEME["card_border"])
    top_toolbar.pack(fill="x", padx=12, pady=(10, 4))
    top_toolbar.grid_columnconfigure(0, weight=1)

    ctk.CTkLabel(
        top_toolbar,
        text="⚡ Bulk Studio Controls",
        font=FONTS["header"],
        text_color="#4ade80"
    ).pack(side="left", padx=14, pady=8)

    all_cards = []

    def _expand_all_cards():
        for c in all_cards:
            c.expand()

    def _collapse_all_cards():
        for c in all_cards:
            c.collapse()

    ctk.CTkButton(
        top_toolbar,
        text="⊞ Expand All",
        width=100,
        height=26,
        fg_color=THEME["btn_indigo"],
        hover_color=THEME["btn_indigo_hover"],
        font=FONTS["btn_small"],
        command=_expand_all_cards
    ).pack(side="right", padx=(4, 12), pady=8)

    ctk.CTkButton(
        top_toolbar,
        text="⊟ Collapse All",
        width=105,
        height=26,
        fg_color=THEME["secondary_btn"],
        hover_color=THEME["secondary_btn_hover"],
        font=FONTS["btn_small"],
        command=_collapse_all_cards
    ).pack(side="right", padx=4, pady=8)

    # ════════════════════════════════════════════════════════════════
    # CHANNEL PROFILE SWITCHER & PRESET MANAGEMENT BAR
    # ════════════════════════════════════════════════════════════════
    profile_bar = ctk.CTkFrame(left_scroll, fg_color="#131724", corner_radius=12, border_width=1, border_color=THEME["card_border"])
    profile_bar.pack(fill="x", padx=12, pady=(4, 8))
    profile_bar.grid_columnconfigure((0, 1), weight=1)

    profile_segmented = ctk.CTkSegmentedButton(
        profile_bar,
        values=["🎬 Video 1 (Channel 1 Profile)", "🎬 Video 2 (Channel 2 Profile)"],
        fg_color="#090c14",
        selected_color=THEME["btn_indigo"],
        selected_hover_color=THEME["btn_indigo_hover"],
        unselected_color="#1e2538",
        unselected_hover_color="#2b354f",
        text_color="#ffffff",
        font=FONTS["btn_small"],
        height=36
    )
    profile_segmented.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 4))
    profile_segmented.set("🎬 Video 1 (Channel 1 Profile)")

    action_f = ctk.CTkFrame(profile_bar, fg_color="transparent")
    action_f.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=(2, 8))

    btn_copy_v1_v2 = ctk.CTkButton(
        action_f,
        text="📋 Copy V1 -> V2",
        width=105,
        height=28,
        fg_color=THEME["secondary_btn"],
        hover_color=THEME["secondary_btn_hover"],
        font=FONTS["btn_small"]
    )
    btn_copy_v1_v2.pack(side="left", padx=2, expand=True, fill="x")

    btn_save_preset = ctk.CTkButton(
        action_f,
        text="💾 Save Preset",
        width=100,
        height=28,
        fg_color=THEME["btn_emerald"],
        hover_color=THEME["btn_emerald_hover"],
        font=FONTS["btn_small"]
    )
    btn_save_preset.pack(side="left", padx=2, expand=True, fill="x")

    btn_load_preset = ctk.CTkButton(
        action_f,
        text="📂 Load Preset",
        width=100,
        height=28,
        fg_color=THEME["btn_indigo"],
        hover_color=THEME["btn_indigo_hover"],
        font=FONTS["btn_small"]
    )
    btn_load_preset.pack(side="left", padx=2, expand=True, fill="x")

    template_menu = ctk.CTkOptionMenu(
        action_f,
        values=["⚡ Templates", "Worship Gold Luxe", "Cyber Spotify Neon", "Cathedral Praise", "Sunset Acoustic Flow"],
        width=120,
        height=28,
        fg_color=THEME["btn_pink"],
        button_color=THEME["btn_pink_hover"],
        font=FONTS["btn_small"]
    )
    template_menu.pack(side="left", padx=2, expand=True, fill="x")

    # ----------------------------------------------------------------
    # Card 1: Video Background & Media (Video to Music Only)
    # ----------------------------------------------------------------
    c_mode = CollapsibleCard(left_scroll, "Video Background & Media Assets", icon="🎬", badge_text="Looped Video Mode", default_expanded=True)
    all_cards.append(c_mode)
    c_mode.body.grid_columnconfigure(1, weight=1)
    studio_mode_var.set("video_to_music")

    # Background Video (Single Unified Input per Profile)
    ctk.CTkLabel(c_mode.body, text="Background Video:", font=FONTS["small_bold"], text_color="#38bdf8").grid(row=0, column=0, sticky="w", padx=8, pady=4)
    vid_lbl = ctk.CTkLabel(c_mode.body, text="No video selected (Pick MP4/MKV)", font=FONTS["body_bold"], text_color=THEME["text_muted"], anchor="w")
    vid_lbl.grid(row=0, column=1, sticky="ew", padx=6)
    vid1_lbl = vid_lbl
    def _browse_vid():
        f = filedialog.askopenfilename(filetypes=[("Video Files", "*.mp4 *.mkv *.mov *.webm *.avi")])
        if f:
            bg_video_path_var.set(f)
            vid_lbl.configure(text=Path(f).name, text_color="#38bdf8")
            c_mode.set_badge(Path(f).name[:16], "#38bdf8")
            _save_form_to_profile(active_profile_key[0])
            _schedule_state_save()
    def _clear_vid():
        bg_video_path_var.set("")
        vid_lbl.configure(text="No video selected (Pick MP4/MKV)", text_color=THEME["text_muted"])
        c_mode.set_badge("No Video Selected", THEME["text_muted"])
        _save_form_to_profile(active_profile_key[0])
        _schedule_state_save()

    ctk.CTkButton(c_mode.body, text="📁 Browse Video", width=115, height=28, fg_color=THEME["btn_indigo"], font=FONTS["btn_small"], command=_browse_vid).grid(row=0, column=2, padx=4, pady=4)
    ctk.CTkButton(c_mode.body, text="❌", width=34, height=28, fg_color=THEME["danger"], hover_color=THEME["danger_shadow"], font=FONTS["btn_small"], command=_clear_vid).grid(row=0, column=3, padx=(2, 6), pady=4)

    # ----------------------------------------------------------------
    # Card 2: Channel Logo & Watermark (Collapsible)
    # ----------------------------------------------------------------
    c_logo = CollapsibleCard(left_scroll, "Channel Logo & Brand Watermark", icon="🏷️", badge_text="No Logo Selected", default_expanded=False)
    all_cards.append(c_logo)
    c_logo.body.grid_columnconfigure(1, weight=1)

    ctk.CTkLabel(c_logo.body, text="Channel / Brand Logo:", font=FONTS["small_bold"], text_color=THEME["text"]).grid(row=0, column=0, sticky="w", padx=6, pady=3)
    logo_lbl = ctk.CTkLabel(c_logo.body, text="Upload transparent PNG or JPG logo", font=FONTS["body_bold"], text_color=THEME["text_muted"], anchor="w")
    logo_lbl.grid(row=0, column=1, sticky="ew", padx=6)

    def _browse_logo():
        f = filedialog.askopenfilename(filetypes=[("Image Files", "*.png *.jpg *.jpeg *.webp *.ico")])
        if f:
            logo_path_var.set(f)
            logo_lbl.configure(text=Path(f).name, text_color="#38bdf8")
            c_logo.set_badge(Path(f).name[:14], "#38bdf8")

    def _clear_logo():
        logo_path_var.set("")
        logo_lbl.configure(text="Upload transparent PNG/JPG", text_color=THEME["text_muted"])
        c_logo.set_badge("No Logo", "#64748b")

    ctk.CTkButton(c_logo.body, text="📁 Browse", width=80, height=28, fg_color=THEME["btn_indigo"], font=FONTS["btn_small"], command=_browse_logo).grid(row=0, column=2, padx=4, pady=3)
    ctk.CTkButton(c_logo.body, text="❌", width=34, height=28, fg_color=THEME["danger"], hover_color=THEME["danger_shadow"], font=FONTS["btn_small"], command=_clear_logo).grid(row=0, column=3, padx=(2, 6), pady=3)

    # Logo Size / Scale Slider Controls
    logo_size_card = ctk.CTkFrame(c_logo.body, fg_color="#171c2b", corner_radius=8, border_width=1, border_color=THEME["card_border"])
    logo_size_card.grid(row=1, column=0, columnspan=4, sticky="ew", padx=6, pady=(4, 4))
    logo_size_card.grid_columnconfigure(0, weight=1)

    logo_scale_hdr = ctk.CTkFrame(logo_size_card, fg_color="transparent")
    logo_scale_hdr.pack(fill="x", padx=8, pady=(6, 2))

    ctk.CTkLabel(logo_scale_hdr, text="📏 Logo Watermark Size:", font=FONTS["small_bold"], text_color="#38bdf8").pack(side="left")
    logo_scale_lbl = ctk.CTkLabel(logo_scale_hdr, text="100% (Medium)", font=FONTS["body_bold"], text_color="#bef264")
    logo_scale_lbl.pack(side="right")

    def _update_logo_scale_text(val):
        pct = int(float(val))
        logo_scale_var.set(pct)
        desc = "Compact" if pct <= 75 else ("Medium" if pct <= 100 else ("Large" if pct <= 140 else "Extra Large"))
    logo_slider = ctk.CTkSlider(
        logo_size_card,
        from_=40,
        to=220,
        number_of_steps=36,
        variable=logo_scale_var,
        command=_update_logo_scale_text,
        progress_color=THEME["btn_cyan"],
        button_color=THEME["btn_cyan"],
        button_hover_color=THEME["btn_cyan_hover"],
        height=18
    )
    logo_slider.pack(fill="x", padx=10, pady=(2, 6))

    logo_preset_f = ctk.CTkFrame(logo_size_card, fg_color="transparent")
    logo_preset_f.pack(fill="x", padx=6, pady=(0, 6))

    def _set_logo_scale_preset(pct: int):
        logo_scale_var.set(pct)
        logo_slider.set(pct)
        _update_logo_scale_text(pct)

    for p_pct in [60, 80, 100, 130, 160]:
        lbl = "100%" if p_pct == 100 else f"{p_pct}%"
        bg_col = THEME["btn_indigo"] if p_pct == 100 else THEME["secondary_btn"]
        ctk.CTkButton(
            logo_preset_f,
            text=lbl,
            width=46,
            height=24,
            fg_color=bg_col,
            font=FONTS["small_bold"],
            corner_radius=6,
            command=lambda p=p_pct: _set_logo_scale_preset(p)
        ).pack(side="left", padx=2, expand=True, fill="x")

    ctk.CTkLabel(c_logo.body, text="💡 Tip: Logo watermark renders top-right (draggable with mouse on live canvas).", font=FONTS["small"], text_color="#94a3b8").grid(row=2, column=0, columnspan=4, sticky="w", padx=6, pady=(2, 4))

    c_lyrics = CollapsibleCard(left_scroll, "Music Source: Suno AI or Premade Songs", icon="🎵", badge_text="Suno AI Active", default_expanded=True)
    all_cards.append(c_lyrics)
    c_lyrics.body.grid_columnconfigure(0, weight=1)

    def _on_audio_source_change(val):
        is_premade = "Premade" in val
        audio_source_mode_var.set("premade_audio" if is_premade else "suno_generate")
        if is_premade:
            suno_box.grid_remove()
            premade_box.grid()
            cnt = len(premade_audio_paths)
            c_lyrics.set_badge(f"📂 {cnt} Premade Songs", "#38bdf8" if cnt > 0 else "#64748b")
        else:
            premade_box.grid_remove()
            suno_box.grid()
            _update_lyrics_detailing()

    audio_src_segmented = ctk.CTkSegmentedButton(
        c_lyrics.body,
        values=["⚡ Generate with Suno AI", "📂 Use Premade / Local MP3s"],
        command=_on_audio_source_change,
        fg_color="#121622",
        selected_color=THEME["btn_indigo"],
        selected_hover_color=THEME["btn_indigo_hover"],
        unselected_color="#202738",
        unselected_hover_color="#2d374e",
        text_color="#ffffff",
        font=FONTS["btn_small"],
        height=34
    )
    audio_src_segmented.grid(row=0, column=0, sticky="ew", padx=6, pady=(4, 8))
    audio_src_segmented.set("⚡ Generate with Suno AI")

    # ────────────────────────────────────────────────────────────────
    # Container 1: Suno AI Generation (Lyrics + Style Prompt)
    # ────────────────────────────────────────────────────────────────
    suno_box = ctk.CTkFrame(c_lyrics.body, fg_color="transparent")
    suno_box.grid(row=1, column=0, sticky="ew")
    suno_box.grid_columnconfigure(0, weight=1)

    ctk.CTkLabel(suno_box, text="Global Music Style Prompt:", font=FONTS["small_bold"], text_color=THEME["text"]).grid(row=0, column=0, sticky="w", padx=6, pady=2)
    style_entry = ctk.CTkEntry(
        suno_box,
        height=34,
        fg_color=THEME["input_bg"],
        border_width=1,
        border_color=THEME["input_border"],
        corner_radius=8,
        font=FONTS["body_bold"],
        text_color=THEME["text"]
    )
    style_entry.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 6))
    style_entry.insert(0, "contemporary gospel worship, uplifting cinematic piano, emotional female leads, powerful drum build, anointed worship 120 bpm, studio quality")

    # Header with Quick Paste Action Button
    lyrics_hdr = ctk.CTkFrame(suno_box, fg_color="transparent")
    lyrics_hdr.grid(row=2, column=0, sticky="ew", padx=4, pady=(2, 2))
    lyrics_hdr.grid_columnconfigure(0, weight=1)

    ctk.CTkLabel(lyrics_hdr, text="Bulk Lyrics Input (Song 1, Song 2, Song 3...):", font=FONTS["small_bold"], text_color=THEME["text"]).grid(row=0, column=0, sticky="w")

    def _paste_clipboard_lyrics():
        try:
            txt = container.clipboard_get()
            if txt:
                songs_textbox.delete("1.0", "end")
                songs_textbox.insert("1.0", txt)
                _update_lyrics_detailing()
        except Exception:
            pass

    def _clear_lyrics():
        songs_textbox.delete("1.0", "end")
        _update_lyrics_detailing()

    ctk.CTkButton(
        lyrics_hdr,
        text="📋 Paste & Analyze",
        width=130,
        height=26,
        fg_color=THEME["btn_indigo"],
        hover_color=THEME["btn_indigo_hover"],
        text_color="#ffffff",
        font=FONTS["btn_small"],
        command=_paste_clipboard_lyrics
    ).grid(row=0, column=1, padx=(4, 2))

    ctk.CTkButton(
        lyrics_hdr,
        text="🗑️ Clear",
        width=70,
        height=26,
        fg_color=THEME["danger"],
        hover_color=THEME["danger_shadow"],
        text_color="#ffffff",
        font=FONTS["btn_small"],
        command=_clear_lyrics
    ).grid(row=0, column=2, padx=(2, 4))
    
    songs_textbox = ctk.CTkTextbox(
        suno_box,
        height=125,
        fg_color=THEME["input_bg"],
        border_width=1,
        border_color=THEME["input_border"],
        corner_radius=8,
        font=FONTS["body"],
        text_color=THEME["text"],
        wrap="word"
    )
    songs_textbox.grid(row=3, column=0, sticky="ew", padx=6, pady=(0, 4))

    sample_text = """Song 1 - If The Road Becomes Uncertain
[Verse 1]
Faithful Father, I am tired of the old story
Isaiah 43 declares, "Behold, I do a new thing now"
He makes rivers in the desert, not the old pattern over me
This September I leave the old behind

[Chorus]
September is my month of breakthrough
I lay my old defeats right down
I trade my ashes for a crown
The God who split the sea splits this
And all that stuck is breaking through

Song 2 - Every Closed Door Opens
[Verse 1]
Merciful Father, I am tired of doors that will not move
Revelation 3:8 declares, "I set before you an open door"
No man can shut what You have opened

[Chorus]
September is my month of breakthrough
Now I hear the hinges start to turn
The God of the keys is opening my door!

Song 3 - Surrounded By Favor
[Verse 1]
Faithful Father, I have strived till I am worn
Psalm 5:12 declares, "You cover the righteous with favor like a shield"
What my hands could not earn, I stop and receive

[Chorus]
September is my month of breakthrough
Your favor is a shield on every side
It speaks before I step inside!"""
    songs_textbox.insert("1.0", sample_text)

    # ── Summary Badges Strip ──
    summary_strip = ctk.CTkFrame(suno_box, fg_color="#121622", corner_radius=8, border_width=1, border_color="#273146")
    summary_strip.grid(row=4, column=0, sticky="ew", padx=6, pady=(4, 6))
    summary_strip.grid_columnconfigure((0, 1, 2, 3), weight=1)

    lbl_stat_songs = ctk.CTkLabel(summary_strip, text="🎵 3 Songs", font=FONTS["small_bold"], text_color="#38bdf8")
    lbl_stat_songs.grid(row=0, column=0, padx=6, pady=4)

    lbl_stat_words = ctk.CTkLabel(summary_strip, text="📝 158 Words", font=FONTS["small_bold"], text_color="#4ade80")
    lbl_stat_words.grid(row=0, column=1, padx=6, pady=4)

    lbl_stat_chars = ctk.CTkLabel(summary_strip, text="🔤 974 Chars", font=FONTS["small_bold"], text_color="#f59e0b")
    lbl_stat_chars.grid(row=0, column=2, padx=6, pady=4)

    lbl_stat_time = ctk.CTkLabel(summary_strip, text="⏱️ ~9:15 Mins", font=FONTS["small_bold"], text_color="#ec4899")
    lbl_stat_time.grid(row=0, column=3, padx=6, pady=4)

    # ── Per-Song Detailed Breakdown Container ──
    breakdown_lbl = ctk.CTkLabel(suno_box, text="📊 Per-Song Live Word & Character Detailing:", font=FONTS["small_bold"], text_color=THEME["text"])
    breakdown_lbl.grid(row=5, column=0, sticky="w", padx=6, pady=(2, 2))

    breakdown_container = ctk.CTkFrame(suno_box, fg_color="transparent")
    breakdown_container.grid(row=6, column=0, sticky="ew", padx=2, pady=(0, 4))
    breakdown_container.grid_columnconfigure(0, weight=1)

    def _update_lyrics_detailing(event=None):
        raw = songs_textbox.get("1.0", "end-1c")
        analysis = analyze_lyrics(raw)

        # Update Badge
        if audio_source_mode_var.get() == "suno_generate":
            c_lyrics.set_badge(f"{analysis['song_count']} Songs ({analysis['total_words']}w, {analysis['total_chars']}c)", "#4ade80" if analysis['song_count'] > 0 else "#94a3b8")

        # Update Summary Strip
        lbl_stat_songs.configure(text=f"🎵 {analysis['song_count']} Songs")
        lbl_stat_words.configure(text=f"📝 {analysis['total_words']} Words")
        lbl_stat_chars.configure(text=f"🔤 {analysis['total_chars']} Chars")
        lbl_stat_time.configure(text=f"⏱️ ~{analysis['total_runtime_str']} Mins")

        # Re-render per-song breakdown chips
        for child in breakdown_container.winfo_children():
            child.destroy()

        if not analysis["songs"]:
            empty_lbl = ctk.CTkLabel(
                breakdown_container,
                text="ℹ️ Paste or type lyrics with 'Song 1', 'Song 2' headers above to view instant word count and character detailing.",
                font=FONTS["small_bold"],
                text_color=THEME["text_muted"],
                wraplength=460,
                justify="left"
            )
            empty_lbl.pack(fill="x", padx=4, pady=4)
            return

        for s in analysis["songs"]:
            row_card = ctk.CTkFrame(
                breakdown_container,
                fg_color="#151a27",
                corner_radius=8,
                border_width=1,
                border_color="#273146"
            )
            row_card.pack(fill="x", pady=2)
            row_card.grid_columnconfigure(1, weight=1)

            # Left: Song Number & Title
            title_f = ctk.CTkFrame(row_card, fg_color="transparent")
            title_f.grid(row=0, column=0, sticky="w", padx=8, pady=4)

            ctk.CTkLabel(
                title_f,
                text=f"🎵 {s['title']}",
                font=FONTS["body_bold"],
                text_color="#ffffff",
                anchor="w"
            ).pack(side="left")

            # Right: Metric Badges (Words, Characters, Lines, Est Time, Health)
            metrics_f = ctk.CTkFrame(row_card, fg_color="transparent")
            metrics_f.grid(row=0, column=1, sticky="e", padx=8, pady=4)

            # Words badge
            ctk.CTkLabel(
                metrics_f,
                text=f"📝 {s['words']}w",
                font=FONTS["small_bold"],
                text_color="#4ade80",
                fg_color="#1e293b",
                corner_radius=4,
                padx=6,
                pady=2
            ).pack(side="left", padx=2)

            # Chars badge
            ctk.CTkLabel(
                metrics_f,
                text=f"🔤 {s['chars']}c",
                font=FONTS["small_bold"],
                text_color="#f59e0b",
                fg_color="#1e293b",
                corner_radius=4,
                padx=6,
                pady=2
            ).pack(side="left", padx=2)

            # Lines badge
            ctk.CTkLabel(
                metrics_f,
                text=f"📑 {s['lines']}L",
                font=FONTS["small_bold"],
                text_color="#cbd5e1",
                fg_color="#1e293b",
                corner_radius=4,
                padx=6,
                pady=2
            ).pack(side="left", padx=2)

            # Est Time
            ctk.CTkLabel(
                metrics_f,
                text=f"⏱️ ~{s['est_time']}",
                font=FONTS["small_bold"],
                text_color="#f59e0b",
                fg_color="#1e293b",
                corner_radius=4,
                padx=6,
                pady=2
            ).pack(side="left", padx=2)

            # Health
            ctk.CTkLabel(
                metrics_f,
                text=s["health"][0],
                font=FONTS["small_bold"],
                text_color=s["health"][1],
                fg_color="#1e293b",
                corner_radius=4,
                padx=6,
                pady=2
            ).pack(side="left", padx=2)

    # Real-time event bindings (on key release, paste, focus, click)
    songs_textbox.bind("<KeyRelease>", _update_lyrics_detailing)
    songs_textbox.bind("<<Paste>>", lambda e: container.after(50, _update_lyrics_detailing))
    songs_textbox.bind("<FocusIn>", _update_lyrics_detailing)
    songs_textbox.bind("<ButtonRelease-1>", _update_lyrics_detailing)

    # ────────────────────────────────────────────────────────────────
    # Container 2: Premade / Local MP3 Audio Tracks (Track 1 for V1, Track 2 for V2)
    # ────────────────────────────────────────────────────────────────
    premade_box = ctk.CTkFrame(c_lyrics.body, fg_color="transparent")
    premade_box.grid(row=2, column=0, sticky="ew")
    premade_box.grid_columnconfigure(0, weight=1)
    premade_box.grid_remove()

    premade_hdr = ctk.CTkFrame(premade_box, fg_color="#171c2b", corner_radius=10, border_width=1, border_color=THEME["card_border"])
    premade_hdr.pack(fill="x", padx=4, pady=(2, 4))
    premade_hdr.grid_columnconfigure(0, weight=1)

    ctk.CTkLabel(premade_hdr, text="📂 Load Local MP3s (Track 1 -> Video 1, Track 2 -> Video 2):", font=FONTS["small_bold"], text_color="#38bdf8").grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(6, 2))

    premade_status_lbl = ctk.CTkLabel(premade_hdr, text="No Premade Songs Selected", font=FONTS["body_bold"], text_color=THEME["text_muted"], anchor="w")
    premade_status_lbl.grid(row=1, column=0, sticky="ew", padx=8, pady=2)

    def _build_premade_pairs(file_paths):
        """
        Intelligently groups MP3 files into paired Track 1 (for Video 1) and Track 2 (for Video 2).
        Matches patterns like _Track1 / _Track2, _v1 / _v2, Track 1 / Track 2, etc.
        """
        pairs_dict = {}
        unpaired_files = []

        re_t1 = re.compile(r'(?i)[_\-\s]*(track\s*1|variant\s*1|part\s*1|v1|t1|\(1\))(?:\.mp3)?$')
        re_t2 = re.compile(r'(?i)[_\-\s]*(track\s*2|variant\s*2|part\s*2|v2|t2|\(2\))(?:\.mp3)?$')

        for fp in file_paths:
            p = Path(fp)
            stem = p.stem

            if re_t1.search(stem):
                base_name = re_t1.sub('', stem).strip()
                if base_name not in pairs_dict:
                    pairs_dict[base_name] = {"title": base_name, "v1_file": str(p), "v2_file": None}
                else:
                    pairs_dict[base_name]["v1_file"] = str(p)
            elif re_t2.search(stem):
                base_name = re_t2.sub('', stem).strip()
                if base_name not in pairs_dict:
                    pairs_dict[base_name] = {"title": base_name, "v1_file": None, "v2_file": str(p)}
                else:
                    pairs_dict[base_name]["v2_file"] = str(p)
            else:
                unpaired_files.append(str(p))

        result = []
        for base_name, d in pairs_dict.items():
            v1 = d["v1_file"] or d["v2_file"]
            v2 = d["v2_file"] or d["v1_file"]
            is_paired = bool(d["v1_file"] and d["v2_file"])
            result.append({
                "title": d["title"] or Path(v1).stem,
                "v1_file": v1,
                "v2_file": v2,
                "v1_name": Path(v1).name if v1 else "",
                "v2_name": Path(v2).name if v2 else "",
                "is_paired": is_paired
            })

        for up in unpaired_files:
            result.append({
                "title": Path(up).stem,
                "v1_file": up,
                "v2_file": up,
                "v1_name": Path(up).name,
                "v2_name": Path(up).name,
                "is_paired": False
            })

        return result

    def _natural_sort_key(s):
        return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s))]

    def _update_premade_list_display():
        for w in premade_scroll.winfo_children():
            w.destroy()
        if not premade_songs_list:
            premade_status_lbl.configure(text="No Premade Songs Selected", text_color=THEME["text_muted"])
            if audio_source_mode_var.get() == "premade_audio":
                c_lyrics.set_badge("0 Songs", "#64748b")
            ctk.CTkLabel(premade_scroll, text="No MP3 files loaded yet.\nClick '📁 Select Audio Folder' or '🎵 Select MP3 Files' above.", font=FONTS["small"], text_color=THEME["text_muted"]).pack(pady=20)
            return

        cnt = len(premade_songs_list)
        paired_cnt = sum(1 for item in premade_songs_list if item["is_paired"])
        premade_status_lbl.configure(text=f"✅ {cnt} Songs Ready ({paired_cnt} Paired Tracks for V1 & V2)", text_color=THEME["success"])
        if audio_source_mode_var.get() == "premade_audio":
            c_lyrics.set_badge(f"📂 {cnt} Songs ({paired_cnt} Paired)", "#38bdf8")

        for idx, item in enumerate(premade_songs_list):
            row_f = ctk.CTkFrame(premade_scroll, fg_color="#121622", corner_radius=8, border_width=1, border_color="#273146")
            row_f.pack(fill="x", pady=3, padx=2)
            row_f.grid_columnconfigure(1, weight=1)

            # Left: Track Index Badge
            ctk.CTkLabel(row_f, text=f"#{idx+1}", font=FONTS["body_bold"], text_color="#38bdf8", width=34).grid(row=0, column=0, rowspan=2, padx=(6, 2), pady=6)

            # Center: Title & Dual Track Badges
            info_f = ctk.CTkFrame(row_f, fg_color="transparent")
            info_f.grid(row=0, column=1, rowspan=2, sticky="ew", padx=4, pady=4)
            info_f.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(info_f, text=f"🎵 {item['title']}", font=FONTS["body_bold"], text_color=THEME["text"], anchor="w").pack(fill="x")

            tags_f = ctk.CTkFrame(info_f, fg_color="transparent")
            tags_f.pack(fill="x", pady=(2, 0))

            if item["is_paired"]:
                ctk.CTkLabel(tags_f, text=f"🎬 Video 1: {item['v1_name']}", font=FONTS["small_bold"], text_color="#bef264", fg_color="#1c2b1e", corner_radius=4, padx=6, pady=2).pack(side="left", padx=(0, 4))
                ctk.CTkLabel(tags_f, text=f"🎬 Video 2: {item['v2_name']}", font=FONTS["small_bold"], text_color="#38bdf8", fg_color="#14263b", corner_radius=4, padx=6, pady=2).pack(side="left")
            else:
                ctk.CTkLabel(tags_f, text=f"🎧 Audio: {item['v1_name']}", font=FONTS["small_bold"], text_color="#94a3b8", fg_color="#1e2538", corner_radius=4, padx=6, pady=2).pack(side="left")

            # Right: Action Buttons (Move Up, Move Down, Delete)
            actions_f = ctk.CTkFrame(row_f, fg_color="transparent")
            actions_f.grid(row=0, column=2, rowspan=2, padx=6, pady=4)

            # Move Up
            btn_up = ctk.CTkButton(
                actions_f,
                text="▲",
                width=28,
                height=24,
                fg_color=THEME["secondary_btn"] if idx > 0 else "#1c2230",
                state="normal" if idx > 0 else "disabled",
                font=FONTS["small_bold"],
                command=lambda i=idx: _move_song_up(i)
            )
            btn_up.pack(side="left", padx=1)

            # Move Down
            btn_down = ctk.CTkButton(
                actions_f,
                text="▼",
                width=28,
                height=24,
                fg_color=THEME["secondary_btn"] if idx < len(premade_songs_list)-1 else "#1c2230",
                state="normal" if idx < len(premade_songs_list)-1 else "disabled",
                font=FONTS["small_bold"],
                command=lambda i=idx: _move_song_down(i)
            )
            btn_down.pack(side="left", padx=1)

            # Delete
            ctk.CTkButton(
                actions_f,
                text="❌",
                width=28,
                height=24,
                fg_color=THEME["danger"],
                hover_color=THEME["danger_shadow"],
                font=FONTS["small_bold"],
                command=lambda i=idx: _remove_song(i)
            ).pack(side="left", padx=1)

    def _move_song_up(i):
        if i > 0:
            premade_songs_list[i], premade_songs_list[i - 1] = premade_songs_list[i - 1], premade_songs_list[i]
            _update_premade_list_display()

    def _move_song_down(i):
        if i < len(premade_songs_list) - 1:
            premade_songs_list[i], premade_songs_list[i + 1] = premade_songs_list[i + 1], premade_songs_list[i]
            _update_premade_list_display()

    def _remove_song(i):
        if 0 <= i < len(premade_songs_list):
            premade_songs_list.pop(i)
            _update_premade_list_display()

    def _sort_numberwise():
        premade_songs_list.sort(key=lambda item: _natural_sort_key(item["title"]))
        _update_premade_list_display()
        _log_console("🔢 Premade songs sorted Numberwise (1, 2, 3...).")

    def _sort_namewise_az():
        premade_songs_list.sort(key=lambda item: item["title"].lower())
        _update_premade_list_display()
        _log_console("🔤 Premade songs sorted Alphabetically (A → Z).")

    def _sort_namewise_za():
        premade_songs_list.sort(key=lambda item: item["title"].lower(), reverse=True)
        _update_premade_list_display()
        _log_console("🔤 Premade songs sorted Alphabetically (Z → A).")

    def _reverse_order():
        premade_songs_list.reverse()
        _update_premade_list_display()
        _log_console("🔀 Premade songs sequence reversed.")

    def _browse_premade_folder():
        d = filedialog.askdirectory(title="Select Folder Containing MP3 Songs")
        if d:
            premade_folder_path_var.set(d)
            mp3s = sorted([str(p) for p in Path(d).glob("*.mp3")])
            if mp3s:
                pairs = _build_premade_pairs(mp3s)
                premade_songs_list.clear()
                premade_songs_list.extend(pairs)
                _sort_numberwise()
                _update_premade_list_display()
                _log_console(f"📂 Loaded {len(premade_songs_list)} songs from folder: {d}")
            else:
                _show_alert("No MP3 Files Found", f"No .mp3 files were found in folder:\n{d}")

    def _browse_premade_files():
        files = filedialog.askopenfilenames(title="Select MP3 Song Files", filetypes=[("MP3 Audio Files", "*.mp3")])
        if files:
            pairs = _build_premade_pairs(files)
            premade_songs_list.clear()
            premade_songs_list.extend(pairs)
            _sort_numberwise()
            _update_premade_list_display()
            _log_console(f"🎵 Selected {len(premade_songs_list)} songs directly.")

    def _clear_premade():
        premade_songs_list.clear()
        premade_folder_path_var.set("")
        _update_premade_list_display()

    btn_f_premade = ctk.CTkFrame(premade_hdr, fg_color="transparent")
    btn_f_premade.grid(row=2, column=0, columnspan=3, sticky="ew", padx=4, pady=(2, 6))

    ctk.CTkButton(btn_f_premade, text="📁 Select Folder (Auto-Pair)", height=28, fg_color=THEME["btn_indigo"], font=FONTS["btn_small"], command=_browse_premade_folder).pack(side="left", padx=2, expand=True, fill="x")
    ctk.CTkButton(btn_f_premade, text="🎵 Select MP3 Files", height=28, fg_color=THEME["btn_emerald"], font=FONTS["btn_small"], command=_browse_premade_files).pack(side="left", padx=2, expand=True, fill="x")
    ctk.CTkButton(btn_f_premade, text="❌ Clear", width=60, height=28, fg_color=THEME["danger"], font=FONTS["btn_small"], command=_clear_premade).pack(side="left", padx=2)

    # ── Sequence Sorting Action Bar ──
    sort_bar = ctk.CTkFrame(premade_box, fg_color="#131724", corner_radius=8, border_width=1, border_color="#273146")
    sort_bar.pack(fill="x", padx=4, pady=(0, 4))
    sort_bar.grid_columnconfigure((0, 1, 2, 3), weight=1)

    ctk.CTkButton(
        sort_bar, text="🔢 Numberwise (1,2,3...)",
        height=26, fg_color=THEME["btn_indigo"], font=FONTS["btn_small"],
        command=_sort_numberwise
    ).grid(row=0, column=0, padx=2, pady=4, sticky="ew")

    ctk.CTkButton(
        sort_bar, text="🔤 Namewise (A→Z)",
        height=26, fg_color=THEME["secondary_btn"], font=FONTS["btn_small"],
        command=_sort_namewise_az
    ).grid(row=0, column=1, padx=2, pady=4, sticky="ew")

    ctk.CTkButton(
        sort_bar, text="🔤 Namewise (Z→A)",
        height=26, fg_color=THEME["secondary_btn"], font=FONTS["btn_small"],
        command=_sort_namewise_za
    ).grid(row=0, column=2, padx=2, pady=4, sticky="ew")

    ctk.CTkButton(
        sort_bar, text="🔀 Reverse",
        height=26, fg_color=THEME["secondary_btn"], font=FONTS["btn_small"],
        command=_reverse_order
    ).grid(row=0, column=3, padx=2, pady=4, sticky="ew")

    # Scrollable preview list for premade tracks
    premade_scroll = ctk.CTkScrollableFrame(premade_box, fg_color="#0e111a", height=150, corner_radius=8, border_width=1, border_color="#273146")
    premade_scroll.pack(fill="x", padx=4, pady=(0, 6))
    premade_scroll.grid_columnconfigure(0, weight=1)
    _update_premade_list_display()



    # ----------------------------------------------------------------
    # Card 3: Video Resolution & Render Quality (Collapsible)
    # ----------------------------------------------------------------
    c_res = CollapsibleCard(left_scroll, "Video Resolution & Render Quality", icon="🎚️", badge_text="1080p Full HD", default_expanded=False)
    all_cards.append(c_res)
    c_res.body.grid_columnconfigure((0, 1), weight=1)

    ctk.CTkLabel(c_res.body, text="Resolution / Size:", font=FONTS["small_bold"], text_color=THEME["text"]).grid(row=0, column=0, sticky="w", padx=6, pady=2)
    def _on_res_change(val):
        c_res.set_badge(val.split()[0], "#f59e0b")
    ctk.CTkOptionMenu(c_res.body, values=RESOLUTIONS_LIST, variable=resolution_var, command=_on_res_change, height=30, fg_color=THEME["input_bg"], button_color=THEME["btn_indigo"], font=FONTS["btn_small"]).grid(row=0, column=1, sticky="ew", padx=6, pady=2)

    ctk.CTkLabel(c_res.body, text="Quality Preset:", font=FONTS["small_bold"], text_color=THEME["text"]).grid(row=1, column=0, sticky="w", padx=6, pady=2)
    ctk.CTkOptionMenu(c_res.body, values=QUALITY_PRESETS, variable=quality_var, height=30, fg_color=THEME["input_bg"], button_color=THEME["secondary_btn"], font=FONTS["btn_small"]).grid(row=1, column=1, sticky="ew", padx=6, pady=2)

    ctk.CTkLabel(c_res.body, text="Audio Bitrate:", font=FONTS["small_bold"], text_color=THEME["text"]).grid(row=2, column=0, sticky="w", padx=6, pady=2)
    ctk.CTkOptionMenu(c_res.body, values=BITRATES_LIST, variable=audio_bitrate_var, height=28, fg_color=THEME["input_bg"], button_color=THEME["secondary_btn"], font=FONTS["small_bold"]).grid(row=2, column=1, sticky="ew", padx=6, pady=2)

    ctk.CTkLabel(c_res.body, text="Frame Rate (FPS):", font=FONTS["small_bold"], text_color=THEME["text"]).grid(row=3, column=0, sticky="w", padx=6, pady=2)
    ctk.CTkOptionMenu(c_res.body, values=FPS_LIST, variable=fps_var, height=28, fg_color=THEME["input_bg"], button_color=THEME["secondary_btn"], font=FONTS["small_bold"]).grid(row=3, column=1, sticky="ew", padx=6, pady=2)

    # GPU Hardware Acceleration Control
    ctk.CTkLabel(c_res.body, text="GPU Hardware Encoder:", font=FONTS["small_bold"], text_color="#4ade80").grid(row=4, column=0, sticky="w", padx=6, pady=2)
    def _on_gpu_change(val):
        c_res.set_badge(val.split()[1] if len(val.split()) > 1 else "GPU", "#4ade80" if "NVIDIA" in val or "QSV" in val or "AMF" in val else "#f59e0b")
    ctk.CTkOptionMenu(
        c_res.body,
        values=GPU_MODES,
        variable=gpu_mode_var,
        command=_on_gpu_change,
        height=30,
        fg_color=THEME["input_bg"],
        button_color=THEME["btn_emerald"],
        font=FONTS["small_bold"]
    ).grid(row=4, column=1, sticky="ew", padx=6, pady=2)

    # Parallel Rendering Checkbox
    chk_parallel = ctk.CTkCheckBox(
        c_res.body,
        text="⚡ Parallel Concurrent Dual Render (⚠️ High GPU Load - Leave Unchecked for 100% Stability)",
        variable=parallel_render_var,
        font=FONTS["body_bold"],
        text_color="#f59e0b"
    )
    chk_parallel.grid(row=5, column=0, columnspan=2, sticky="w", padx=6, pady=(4, 2))

    # Auto-Pick Audio Cache Checkbox
    chk_cache = ctk.CTkCheckBox(
        c_res.body,
        text="📦 Auto-Pick Cached Songs (Saves Suno Credits & Skips Generation if MP3 Exists)",
        variable=use_cache_var,
        font=FONTS["body_bold"],
        text_color="#38bdf8"
    )
    chk_cache.grid(row=6, column=0, columnspan=2, sticky="w", padx=6, pady=(2, 4))


    # ----------------------------------------------------------------
    # Card 4: Output Save Location & Filenames (Collapsible)
    # ----------------------------------------------------------------
    c_out = CollapsibleCard(left_scroll, "Output Save Location & Filenames", icon="📁", badge_text="Custom Output", default_expanded=False)
    all_cards.append(c_out)
    c_out.body.grid_columnconfigure(1, weight=1)

    ctk.CTkLabel(c_out.body, text="Save Folder:", font=FONTS["small_bold"], text_color=THEME["text"]).grid(row=0, column=0, sticky="w", padx=6, pady=2)
    ctk.CTkEntry(c_out.body, textvariable=out_dir_var, height=30, fg_color=THEME["input_bg"], border_color=THEME["input_border"], font=FONTS["small_bold"]).grid(row=0, column=1, sticky="ew", padx=4, pady=2)
    def _browse_out():
        d = filedialog.askdirectory(initialdir=out_dir_var.get())
        if d:
            out_dir_var.set(d)
    ctk.CTkButton(c_out.body, text="📁 Browse", width=80, height=28, fg_color=THEME["btn_indigo"], font=FONTS["btn_small"], command=_browse_out).grid(row=0, column=2, padx=4, pady=2)

    ctk.CTkLabel(c_out.body, text="Video 1 Filename:", font=FONTS["small_bold"], text_color=THEME["text"]).grid(row=1, column=0, sticky="w", padx=6, pady=2)
    ctk.CTkEntry(c_out.body, textvariable=v1_filename_var, height=28, fg_color=THEME["input_bg"], border_color=THEME["input_border"], font=FONTS["small_bold"]).grid(row=1, column=1, columnspan=2, sticky="ew", padx=(4, 6), pady=2)

    ctk.CTkLabel(c_out.body, text="Video 2 Filename:", font=FONTS["small_bold"], text_color=THEME["text"]).grid(row=2, column=0, sticky="w", padx=6, pady=2)
    ctk.CTkEntry(c_out.body, textvariable=v2_filename_var, height=28, fg_color=THEME["input_bg"], border_color=THEME["input_border"], font=FONTS["small_bold"]).grid(row=2, column=1, columnspan=2, sticky="ew", padx=(4, 6), pady=2)

    ctk.CTkCheckBox(c_out.body, text="📌 Export YouTube Chapter Timestamps (.txt)", variable=export_txt_var, font=FONTS["body_bold"], text_color=THEME["text"]).grid(row=3, column=0, columnspan=3, sticky="w", padx=6, pady=(4, 2))

    # ----------------------------------------------------------------
    # Card 5: Background Motion Effects (Collapsible)
    # ----------------------------------------------------------------
    c_motion = CollapsibleCard(left_scroll, "Background Motion Effects", icon="🎬", badge_text="Ken Burns Zoom", default_expanded=False)
    all_cards.append(c_motion)
    c_motion.body.grid_columnconfigure(0, weight=1)

    def _on_motion_change(val):
        c_motion.set_badge(val.split("(")[0].strip(), "#ec4899")
    ctk.CTkOptionMenu(c_motion.body, values=BG_EFFECTS, variable=bg_effect_var, command=_on_motion_change, height=32, fg_color=THEME["input_bg"], button_color=THEME["btn_pink"], font=FONTS["btn_small"]).grid(row=0, column=0, sticky="ew", padx=6, pady=4)

    # ----------------------------------------------------------------
    # Card 6: Typography, Song Title & Subtitle Colors (Collapsible)
    # ----------------------------------------------------------------
    c_typo = CollapsibleCard(left_scroll, "Typography, Song Title Colors & Style", icon="🎨", badge_text="Title Color & Fonts", default_expanded=True)
    all_cards.append(c_typo)
    c_typo.body.grid_columnconfigure((0, 1), weight=1)

    # 1. Song Title (Name) Color Box
    title_col_f = ctk.CTkFrame(c_typo.body, fg_color="#171c2b", corner_radius=8, border_width=1, border_color=THEME["card_border"])
    title_col_f.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=4)
    title_col_f.grid_columnconfigure(1, weight=1)

    ctk.CTkLabel(title_col_f, text="🎵 Song Title (Name) Color:", font=FONTS["small_bold"], text_color="#f59e0b").grid(row=0, column=0, sticky="w", padx=8, pady=(6, 2))
    title_hex_entry = ctk.CTkEntry(title_col_f, textvariable=title_color_var, width=105, height=28, font=FONTS["small_bold"], fg_color=THEME["input_bg"])
    title_hex_entry.grid(row=0, column=1, sticky="e", padx=8, pady=(6, 2))

    # Title Color Preset Palette Buttons
    preset_title_f = ctk.CTkFrame(title_col_f, fg_color="transparent")
    preset_title_f.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=(2, 6))

    for name, hex_val in COLOR_PRESETS:
        btn_txt_col = "#000000" if hex_val in ("#FFFFFF", "#BEF264", "#EAB308", "#38BDF8") else "#ffffff"
        ctk.CTkButton(
            preset_title_f,
            text=name.split()[0],
            width=50,
            height=24,
            fg_color=hex_val,
            hover_color=hex_val,
            text_color=btn_txt_col,
            font=FONTS["small_bold"],
            corner_radius=6,
            command=lambda h=hex_val: (title_color_var.set(h), c_typo.set_badge(f"Title {h}", h))
        ).pack(side="left", padx=2, expand=True, fill="x")

    # 2. Subtitle / Up Next Color Box
    sub_col_f = ctk.CTkFrame(c_typo.body, fg_color="#171c2b", corner_radius=8, border_width=1, border_color=THEME["card_border"])
    sub_col_f.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=4)
    sub_col_f.grid_columnconfigure(1, weight=1)

    ctk.CTkLabel(sub_col_f, text="📝 Subtitle / Next Track Color:", font=FONTS["small_bold"], text_color="#38bdf8").grid(row=0, column=0, sticky="w", padx=8, pady=(6, 2))
    sub_hex_entry = ctk.CTkEntry(sub_col_f, textvariable=subtitle_color_var, width=105, height=28, font=FONTS["small_bold"], fg_color=THEME["input_bg"])
    sub_hex_entry.grid(row=0, column=1, sticky="e", padx=8, pady=(6, 2))

    preset_sub_f = ctk.CTkFrame(sub_col_f, fg_color="transparent")
    preset_sub_f.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=(2, 6))

    SUB_PRESETS = [
        ("Silver", "#CBD5E1"), ("Slate", "#94A3B8"), ("Gold Sub", "#FEF08A"),
        ("Cyan Sub", "#67E8F9"), ("Lime Sub", "#D9F99D"), ("Pink Sub", "#F472B6")
    ]
    for name, hex_val in SUB_PRESETS:
        btn_txt_col = "#000000" if hex_val in ("#CBD5E1", "#FEF08A", "#67E8F9", "#D9F99D") else "#ffffff"
        ctk.CTkButton(
            preset_sub_f,
            text=name.split()[0],
            width=50,
            height=24,
            fg_color=hex_val,
            hover_color=hex_val,
            text_color=btn_txt_col,
            font=FONTS["small_bold"],
            corner_radius=6,
            command=lambda h=hex_val: subtitle_color_var.set(h)
        ).pack(side="left", padx=2, expand=True, fill="x")

    # 3. Font Family & Upload Custom Font (.ttf / .otf)
    font_menu_f = ctk.CTkFrame(c_typo.body, fg_color="transparent")
    font_menu_f.grid(row=2, column=0, columnspan=2, sticky="ew", padx=6, pady=4)
    font_menu_f.grid_columnconfigure(1, weight=1)

    ctk.CTkLabel(font_menu_f, text="Font Family:", font=FONTS["small_bold"], text_color=THEME["text"]).grid(row=0, column=0, sticky="w", padx=(0, 6))
    font_dropdown = ctk.CTkOptionMenu(font_menu_f, values=FONT_FAMILIES, variable=font_family_var, height=30, fg_color=THEME["input_bg"], button_color=THEME["secondary_btn"], font=FONTS["btn_small"])
    font_dropdown.grid(row=0, column=1, sticky="ew", padx=4)

    def _upload_custom_font():
        f = filedialog.askopenfilename(
            title="Select Custom Font (.ttf / .otf)",
            filetypes=[("Font Files (*.ttf, *.otf)", "*.ttf;*.otf"), ("TrueType Fonts (*.ttf)", "*.ttf"), ("OpenType Fonts (*.otf)", "*.otf"), ("All Files", "*.*")]
        )
        if f:
            fname = Path(f).name
            font_family_var.set(f)
            cur_vals = list(font_dropdown.cget("values"))
            if f not in cur_vals:
                cur_vals.insert(0, f)
                font_dropdown.configure(values=cur_vals)
            c_typo.set_badge(f"Font: {fname[:18]}", "#38bdf8")
            _log_console(f"✔ Custom font activated: {fname}")

    ctk.CTkButton(font_menu_f, text="📤 Upload Font (.ttf/.otf)", width=175, height=30, fg_color="#0284c7", hover_color="#0369a1", font=FONTS["btn_small"], text_color="#ffffff", command=_upload_custom_font).grid(row=0, column=2, padx=(6, 0))

    # 4. Font Size Slider (24 to 96 px)
    size_lbl_text = ctk.StringVar(value=f"Font Size: {font_size_var.get()}px")
    ctk.CTkLabel(c_typo.body, textvariable=size_lbl_text, font=FONTS["body_bold"], text_color="#38bdf8").grid(row=3, column=0, sticky="w", padx=6, pady=4)
    def _on_sz(val):
        font_size_var.set(int(val))
        size_lbl_text.set(f"Font Size: {int(val)}px")
    ctk.CTkSlider(c_typo.body, from_=24, to=96, number_of_steps=72, variable=font_size_var, command=_on_sz, button_color=THEME["btn_indigo"], progress_color=THEME["btn_indigo"]).grid(row=3, column=1, sticky="ew", padx=6, pady=4)

    # 5. Font Style Toggles & Text Shadow
    toggles_f = ctk.CTkFrame(c_typo.body, fg_color="transparent")
    toggles_f.grid(row=4, column=0, columnspan=2, sticky="ew", padx=6, pady=4)
    ctk.CTkCheckBox(toggles_f, text="𝗕 Bold", variable=font_bold_var, font=FONTS["body_bold"], text_color=THEME["text"], width=80).pack(side="left")
    ctk.CTkCheckBox(toggles_f, text="𝘐 Italic", variable=font_italic_var, font=FONTS["body_bold"], text_color=THEME["text"], width=80).pack(side="left", padx=8)
    ctk.CTkCheckBox(toggles_f, text="✨ Soft Drop Shadow", variable=text_shadow_var, font=FONTS["body_bold"], text_color=THEME["text"], width=170).pack(side="left", padx=8)

    # ----------------------------------------------------------------
    # Card 7: Border-Free Player & Spinning Vinyl Skin (Collapsible)
    # ----------------------------------------------------------------
    c_player = CollapsibleCard(left_scroll, "Border-Free Player & Rotating Vinyl Skin", icon="💿", badge_text="Rotating Vinyl Active", default_expanded=True)
    all_cards.append(c_player)
    c_player.body.grid_columnconfigure(1, weight=1)

    ctk.CTkLabel(c_player.body, text="Player Layout Skin:", font=FONTS["small_bold"], text_color="#38bdf8").grid(row=0, column=0, sticky="w", padx=6, pady=4)
    ctk.CTkOptionMenu(c_player.body, values=PLAYER_STYLES, variable=player_style_var, height=32, fg_color=THEME["input_bg"], button_color=THEME["btn_indigo"], font=FONTS["btn_small"]).grid(row=0, column=1, sticky="ew", padx=6, pady=4)

    # Accent Progress Line Color Box
    accent_col_f = ctk.CTkFrame(c_player.body, fg_color="#171c2b", corner_radius=8, border_width=1, border_color=THEME["card_border"])
    accent_col_f.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=6)
    accent_col_f.grid_columnconfigure(1, weight=1)

    ctk.CTkLabel(accent_col_f, text="⚡ Progress Line & Vinyl Glow Accent:", font=FONTS["small_bold"], text_color="#eab308").grid(row=0, column=0, sticky="w", padx=8, pady=(6, 2))
    accent_hex_entry = ctk.CTkEntry(accent_col_f, textvariable=accent_color_var, width=105, height=28, font=FONTS["small_bold"], fg_color=THEME["input_bg"])
    accent_hex_entry.grid(row=0, column=1, sticky="e", padx=8, pady=(6, 2))

    preset_acc_f = ctk.CTkFrame(accent_col_f, fg_color="transparent")
    preset_acc_f.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=(2, 6))

    for name, hex_val in [("Gold", "#EAB308"), ("Cyan", "#38BDF8"), ("Lime", "#BEF264"), ("Pink", "#F43F5E"), ("Violet", "#A855F7"), ("White", "#FFFFFF")]:
        btn_txt_col = "#000000" if hex_val in ("#FFFFFF", "#BEF264", "#EAB308", "#38BDF8") else "#ffffff"
        ctk.CTkButton(
            preset_acc_f,
            text=name,
            width=50,
            height=24,
            fg_color=hex_val,
            hover_color=hex_val,
            text_color=btn_txt_col,
            font=FONTS["small_bold"],
            corner_radius=6,
            command=lambda h=hex_val: (accent_color_var.set(h), viz_color_var.set(h))
        ).pack(side="left", padx=2, expand=True, fill="x")

    # ----------------------------------------------------------------
    # Card 8: Floating CTA Banner & Full-Color Emojis (Collapsible)
    # ----------------------------------------------------------------
    c_banner = CollapsibleCard(left_scroll, "Floating CTA Banner & Emojis", icon="💬", badge_text="Banner Active 👍", default_expanded=True)
    all_cards.append(c_banner)
    c_banner.body.grid_columnconfigure(1, weight=1)

    # Floating CTA Banner Options (Toggle, Clear / Remove, and Emoji Support)
    banner_bar = ctk.CTkFrame(c_banner.body, fg_color="#171c2b", corner_radius=8, border_width=1, border_color=THEME["card_border"])
    banner_bar.grid(row=0, column=0, columnspan=3, sticky="ew", padx=6, pady=(4, 2))
    banner_bar.grid_columnconfigure(1, weight=1)

    def _on_banner_toggle():
        st = show_banner_var.get()
        c_banner.set_badge("Banner Active 👍" if st else "Banner Hidden ❌", "#4ade80" if st else "#ef4444")

    chk_banner = ctk.CTkCheckBox(
        banner_bar,
        text="☑️ Show Floating CTA Banner",
        variable=show_banner_var,
        command=_on_banner_toggle,
        font=FONTS["body_bold"],
        text_color=THEME["text"]
    )
    chk_banner.grid(row=0, column=0, sticky="w", padx=10, pady=6)

    def _remove_banner():
        show_banner_var.set(False)
        cta_top_entry.delete(0, "end")
        cta_bot_entry.delete(0, "end")
        _on_banner_toggle()

    btn_remove_banner = ctk.CTkButton(
        banner_bar,
        text="❌ Remove Banner",
        width=120,
        height=26,
        fg_color=THEME["danger"],
        hover_color=THEME["danger_shadow"],
        text_color="#ffffff",
        font=FONTS["btn_small"],
        command=_remove_banner
    )
    btn_remove_banner.grid(row=0, column=2, sticky="e", padx=10, pady=6)

    # Top & Bottom Banner Text (Emoji Supported!)
    ctk.CTkLabel(c_banner.body, text="Banner Top Text (Colorful Emojis):", font=FONTS["small_bold"], text_color=THEME["text"]).grid(row=1, column=0, sticky="w", padx=6, pady=2)
    cta_top_entry = ctk.CTkEntry(c_banner.body, height=30, fg_color=THEME["input_bg"], border_color=THEME["input_border"], font=FONTS["small_bold"])
    cta_top_entry.grid(row=1, column=1, columnspan=2, sticky="ew", padx=6, pady=2)
    cta_top_entry.insert(0, "🌈🙏 Thank you for worshipping with us! 🙏🌈")

    ctk.CTkLabel(c_banner.body, text="Banner Bottom Text (Colorful Emojis):", font=FONTS["small_bold"], text_color=THEME["text"]).grid(row=2, column=0, sticky="w", padx=6, pady=2)
    cta_bot_entry = ctk.CTkEntry(c_banner.body, height=30, fg_color=THEME["input_bg"], border_color=THEME["input_border"], font=FONTS["small_bold"])
    cta_bot_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=6, pady=2)
    cta_bot_entry.insert(0, "👍✨ Please Like & Subscribe 🔔❤️")

    ctk.CTkLabel(c_banner.body, text="Banner Motion Animation:", font=FONTS["small_bold"], text_color="#ec4899").grid(row=3, column=0, sticky="w", padx=6, pady=2)
    ctk.CTkOptionMenu(
        c_banner.body,
        values=BANNER_ANIM_MODES,
        variable=banner_anim_mode_var,
        height=32,
        fg_color=THEME["input_bg"],
        button_color=THEME["btn_pink"],
        font=FONTS["btn_small"]
    ).grid(row=3, column=1, columnspan=2, sticky="ew", padx=6, pady=(2, 6))

    # Master Floating 3D Action Button (Large, Bright & Bold)
    fab_container = ctk.CTkFrame(left_scroll, fg_color="transparent")
    fab_container.pack(fill="x", padx=12, pady=16)

    btn_start_3d = CTk3DButton(
        fab_container,
        text="🚀  START BULK GENERATION & DUAL RENDER",
        fg_color=THEME["accent"],
        hover_color=THEME["accent_hover"],
        shadow_color=THEME["accent_shadow"],
        text_color="#ffffff",
        font=FONTS["btn_3d_large"],
        height=52,
        corner_radius=12
    )
    btn_start_3d.pack(fill="x")

    def _open_channel_uploader():
        chosen_vid = getattr(container, "_last_rendered_video", "")
        if not chosen_vid or not os.path.exists(chosen_vid):
            from tkinter import filedialog
            chosen_vid = filedialog.askopenfilename(
                title="Select Rendered Video to Upload to Channel",
                filetypes=[("MP4 Video", "*.mp4"), ("All Videos", "*.mp4;*.mkv;*.mov;*.avi"), ("All Files", "*.*")]
            )
        if chosen_vid and os.path.exists(chosen_vid):
            try:
                import master_queue
                master_queue.register_rendered_video(
                    chosen_vid,
                    title=f"Bulk Studio: {Path(chosen_vid).stem}",
                    tool_name="Bulk Video Studio"
                )
            except Exception as e:
                print(f"[BULK_STUDIO] Upload dialog error: {e}")

    btn_upload_channel = ctk.CTkButton(
        fab_container,
        text="📤  UPLOAD VIDEO TO CHANNEL",
        fg_color="#ff0033",
        hover_color="#d4002a",
        text_color="#ffffff",
        font=FONTS["btn_small"],
        height=38,
        corner_radius=10,
        command=_open_channel_uploader
    )
    btn_upload_channel.pack(fill="x", pady=(8, 0))

    # ════════════════════════════════════════════════════════════════
    # RIGHT PANEL: REALTIME 3D CANVAS & PROCESS MONITOR
    # ════════════════════════════════════════════════════════════════
    right_frame = ctk.CTkFrame(
        container,
        fg_color=THEME["surface"],
        corner_radius=16,
        border_width=1,
        border_color=THEME["card_border"]
    )
    right_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=12)
    right_frame.grid_rowconfigure(2, weight=1)
    right_frame.grid_columnconfigure(0, weight=1)

    # Header & Switcher
    prev_header = ctk.CTkFrame(right_frame, fg_color="transparent")
    prev_header.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 4))
    prev_header.grid_columnconfigure(0, weight=1)

    ctk.CTkLabel(prev_header, text="🖼️ 3D Real-Time Canvas Preview", font=FONTS["header"], text_color=THEME["text"]).pack(side="left")

    prev_switcher = ctk.CTkSegmentedButton(
        prev_header,
        values=["Video 1", "Video 2"],
        variable=preview_mode_var,
        fg_color="#121622",
        selected_color=THEME["btn_indigo"],
        selected_hover_color=THEME["btn_indigo_hover"],
        unselected_color="#202738",
        unselected_hover_color="#2d374e",
        text_color="#ffffff",
        font=FONTS["btn_small"],
        width=190,
        height=32
    )
    prev_switcher.pack(side="right")

    # Drag Bar
    drag_bar = ctk.CTkFrame(right_frame, fg_color=THEME["card"], corner_radius=10, border_width=1, border_color=THEME["card_border"])
    drag_bar.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 6))

    def _toggle_lock():
        is_locked = lock_positions_var.get()
        lock_btn.configure(
            text="🔒 Positions Locked" if is_locked else "🔓 Drag Elements (Unlocked)",
            fg_color="#334155" if is_locked else THEME["accent"],
            text_color="#94a3b8" if is_locked else "#ffffff"
        )

    lock_btn = ctk.CTkCheckBox(
        drag_bar,
        text="🔒 Lock Element Positions",
        variable=lock_positions_var,
        command=_toggle_lock,
        font=FONTS["body_bold"],
        text_color=THEME["text"]
    )
    lock_btn.pack(side="left", padx=12, pady=8)

    anim_chk = ctk.CTkCheckBox(
        drag_bar,
        text="✨ Animated Banner Float",
        variable=animate_banner_var,
        font=FONTS["body_bold"],
        text_color=THEME["text"]
    )
    anim_chk.pack(side="left", padx=12, pady=8)

    pos_info_lbl = ctk.CTkLabel(drag_bar, text="Banner: 360,50 | Logo: 1720,50", font=FONTS["body_bold"], text_color="#38bdf8")
    pos_info_lbl.pack(side="right", padx=12)

    def _reset_positions():
        for k, v in DEFAULT_POS_1080.items():
            pos_1080[k] = list(v)
        pos_info_lbl.configure(text=f"Banner: {pos_1080['banner'][0]},{pos_1080['banner'][1]} | Logo: {pos_1080['logo'][0]},{pos_1080['logo'][1]}")

    ctk.CTkButton(
        drag_bar,
        text="↺ Reset",
        width=70,
        height=26,
        fg_color=THEME["btn_amber"],
        hover_color=THEME["btn_amber_hover"],
        text_color="#0f172a",
        font=FONTS["btn_small"],
        corner_radius=6,
        command=_reset_positions
    ).pack(side="right", padx=4)

    # ════════════════════════════════════════════════════════════════
    # ════════════════════════════════════════════════════════════════
    # CHANNEL PROFILE SYNCHRONIZATION & AUTO-PERSISTENCE ENGINE
    # ════════════════════════════════════════════════════════════════
    STATE_FILE_GLOBAL = get_config_dir() / "suno_studio_last_state.json"
    STATE_FILE_LOCAL = Path("presets") / "suno_studio_last_state.json"

    def _get_current_studio_state() -> dict:
        cur_k = active_profile_key[0]
        if cur_k in channel_profiles:
            p = channel_profiles[cur_k]
            p["mode"] = "video_to_music"
            p["bg_video"] = bg_video_path_var.get()
            p["logo_path"] = logo_path_var.get()
            p["logo_scale"] = logo_scale_var.get()
            p["bg_effect"] = bg_effect_var.get()
            p["title_color"] = title_color_var.get()
            p["subtitle_color"] = subtitle_color_var.get()
            p["accent_color"] = accent_color_var.get()
            p["font_family"] = font_family_var.get()
            p["font_size"] = font_size_var.get()
            p["font_bold"] = font_bold_var.get()
            p["font_italic"] = font_italic_var.get()
            p["text_shadow"] = text_shadow_var.get()
            p["player_style"] = player_style_var.get()
            p["viz_style"] = "None"
            p["show_banner"] = show_banner_var.get()
            try:
                p["banner_top"] = cta_top_entry.get()
                p["banner_bot"] = cta_bot_entry.get()
            except Exception:
                pass
            p["banner_anim"] = banner_anim_mode_var.get()
            p["positions"] = {k: list(v) for k, v in pos_1080.items()}

        return {
            "version": "2.0",
            "active_profile": active_profile_key[0],
            "channel_profiles": copy.deepcopy(channel_profiles),
            "global_settings": {
                "resolution": resolution_var.get(),
                "quality": quality_var.get(),
                "bitrate": audio_bitrate_var.get(),
                "fps": fps_var.get(),
                "gpu_mode": gpu_mode_var.get(),
                "parallel_render": parallel_render_var.get(),
                "use_cache": use_cache_var.get(),
                "animate_banner": animate_banner_var.get(),
                "banner_anim_mode": banner_anim_mode_var.get(),
                "out_dir": out_dir_var.get(),
                "export_txt": export_txt_var.get(),
                "bg_video_1": channel_profiles.get("video_1", {}).get("bg_video", "") or (bg_video_path_var.get() if active_profile_key[0] == "video_1" else ""),
                "bg_video_2": channel_profiles.get("video_2", {}).get("bg_video", "") or (bg_video_path_var.get() if active_profile_key[0] == "video_2" else ""),
                "lock_positions": lock_positions_var.get(),
            }
        }

    _is_loading_state = [True]

    def _save_last_applied_state():
        if _is_loading_state[0]:
            return
        try:
            data = _get_current_studio_state()
            STATE_FILE_GLOBAL.parent.mkdir(parents=True, exist_ok=True)
            with open(STATE_FILE_GLOBAL, "w", encoding="utf-8") as fp:
                json.dump(data, fp, indent=2, ensure_ascii=False)
            try:
                STATE_FILE_LOCAL.parent.mkdir(parents=True, exist_ok=True)
                with open(STATE_FILE_LOCAL, "w", encoding="utf-8") as fp2:
                    json.dump(data, fp2, indent=2, ensure_ascii=False)
            except Exception:
                pass
        except Exception as ex:
            print(f"[AUTO-SAVE ERROR] {ex}")

    _save_timer = [None]
    def _schedule_state_save():
        if _is_loading_state[0]:
            return
        if _save_timer[0] is not None:
            try:
                container.after_cancel(_save_timer[0])
            except Exception:
                pass
        _save_timer[0] = container.after(350, _save_last_applied_state)

    def _save_form_to_profile(key: str):
        if key not in channel_profiles:
            return
        p = channel_profiles[key]
        p["mode"] = "video_to_music"
        p["bg_video"] = bg_video_path_var.get()
        p["fg_image"] = fg_image_path_var.get()
        p["fg_cutout"] = fg_cutout_path_var.get()
        p["fg_scale"] = fg_scale_var.get()
        p["logo_path"] = logo_path_var.get()
        p["logo_scale"] = logo_scale_var.get()
        p["bg_effect"] = bg_effect_var.get()
        p["title_color"] = title_color_var.get()
        p["subtitle_color"] = subtitle_color_var.get()
        p["accent_color"] = accent_color_var.get()
        p["font_family"] = font_family_var.get()
        p["font_size"] = font_size_var.get()
        p["font_bold"] = font_bold_var.get()
        p["font_italic"] = font_italic_var.get()
        p["text_shadow"] = text_shadow_var.get()
        p["player_style"] = player_style_var.get()
        p["viz_style"] = "None"
        p["viz_color"] = viz_color_var.get()
        p["show_banner"] = show_banner_var.get()
        try:
            p["banner_top"] = cta_top_entry.get()
            p["banner_bot"] = cta_bot_entry.get()
        except Exception:
            pass
        p["banner_anim"] = banner_anim_mode_var.get()
        p["positions"] = {k: list(v) for k, v in pos_1080.items()}
        _schedule_state_save()

    def _load_profile_to_form(key: str):
        if key not in channel_profiles:
            return
        p = channel_profiles[key]
        studio_mode_var.set("video_to_music")

        v_p = p.get("bg_video", "")
        bg_video_path_var.set(v_p)
        if v_p:
            vid_lbl.configure(
                text=Path(v_p).name,
                text_color="#38bdf8"
            )
            c_mode.set_badge(Path(v_p).name[:16], "#38bdf8")
        else:
            vid_lbl.configure(
                text="No video selected (Pick MP4/MKV)",
                text_color=THEME["text_muted"]
            )
            c_mode.set_badge("No Video Selected", THEME["text_muted"])

        fg_image_path_var.set(p.get("fg_image", ""))
        fg_cutout_path_var.set(p.get("fg_cutout", ""))

        l_path = p.get("logo_path", "")
        logo_path_var.set(l_path)
        logo_lbl.configure(text=Path(l_path).name if l_path else "Upload transparent PNG or JPG logo", text_color="#38bdf8" if l_path else THEME["text_muted"])
        c_logo.set_badge(Path(l_path).name[:14] if l_path else "No Logo", "#38bdf8" if l_path else "#64748b")

        lsc = p.get("logo_scale", 100)
        logo_scale_var.set(lsc)
        logo_slider.set(lsc)
        _update_logo_scale_text(lsc)

        bg_effect_var.set(p.get("bg_effect", BG_EFFECTS[0]))
        c_motion.set_badge(p.get("bg_effect", "").split("(")[0].strip(), "#ec4899")

        title_color_var.set(p.get("title_color", "#FFFFFF"))
        subtitle_color_var.set(p.get("subtitle_color", "#94A3B8"))
        accent_color_var.set(p.get("accent_color", "#EAB308"))
        c_typo.set_badge(f"Title {p.get('title_color', '#FFFFFF')}", p.get("title_color", "#FFFFFF"))

        f_fam = p.get("font_family", "Segoe UI")
        font_family_var.set(f_fam)
        try:
            cur_vals = list(font_dropdown.cget("values"))
            if f_fam not in cur_vals:
                cur_vals.insert(0, f_fam)
                font_dropdown.configure(values=cur_vals)
            c_typo.set_badge(f"Font: {Path(f_fam).name[:18]}", "#38bdf8")
        except Exception:
            pass

        font_size_var.set(p.get("font_size", 42))
        size_lbl_text.set(f"Font Size: {p.get('font_size', 42)}px")
        font_bold_var.set(p.get("font_bold", True))
        font_italic_var.set(p.get("font_italic", False))
        text_shadow_var.set(p.get("text_shadow", True))

        player_style_var.set(p.get("player_style", PLAYER_STYLES[0]))

        show_banner_var.set(p.get("show_banner", True))
        try:
            cta_top_entry.delete(0, "end")
            cta_top_entry.insert(0, p.get("banner_top", ""))
            cta_bot_entry.delete(0, "end")
            cta_bot_entry.insert(0, p.get("banner_bot", ""))
        except Exception:
            pass
        banner_anim_mode_var.set(p.get("banner_anim", BANNER_ANIM_MODES[0]))
        c_banner.set_badge("Banner Active 👍" if p.get("show_banner") else "Banner Hidden ❌", "#4ade80" if p.get("show_banner") else "#ef4444")

        if "positions" in p:
            for k, v in p["positions"].items():
                pos_1080[k] = list(v)
            pos_info_lbl.configure(text=f"Banner: {pos_1080['banner'][0]},{pos_1080['banner'][1]} | Logo: {pos_1080['logo'][0]},{pos_1080['logo'][1]}")

    def _load_last_applied_state():
        _is_loading_state[0] = True
        target_file = None
        if STATE_FILE_GLOBAL.exists():
            target_file = STATE_FILE_GLOBAL
        elif STATE_FILE_LOCAL.exists():
            target_file = STATE_FILE_LOCAL

        if not target_file:
            _load_profile_to_form(active_profile_key[0])
            try:
                container.after(600, lambda: _is_loading_state.__setitem__(0, False))
            except Exception:
                _is_loading_state[0] = False
            return False

        try:
            with open(target_file, "r", encoding="utf-8") as fp:
                data = json.load(fp)

            # 1. Restore channel profiles
            saved_profiles = data.get("channel_profiles", {})
            for k in ["video_1", "video_2"]:
                if k in saved_profiles and isinstance(saved_profiles[k], dict):
                    channel_profiles[k].update(saved_profiles[k])

            # 2. Restore global settings
            glob = data.get("global_settings", {})
            if "resolution" in glob and glob["resolution"] in RESOLUTIONS_LIST:
                resolution_var.set(glob["resolution"])
            if "quality" in glob and glob["quality"] in QUALITY_PRESETS:
                quality_var.set(glob["quality"])
            if "bitrate" in glob and glob["bitrate"] in BITRATES_LIST:
                audio_bitrate_var.set(glob["bitrate"])
            if "fps" in glob and glob["fps"] in FPS_LIST:
                fps_var.set(glob["fps"])
            if "gpu_mode" in glob and glob["gpu_mode"] in GPU_MODES:
                gpu_mode_var.set(glob["gpu_mode"])
            if "parallel_render" in glob:
                parallel_render_var.set(bool(glob["parallel_render"]))
            if "use_cache" in glob:
                use_cache_var.set(bool(glob["use_cache"]))
            if "animate_banner" in glob:
                animate_banner_var.set(bool(glob["animate_banner"]))
            if "banner_anim_mode" in glob and glob["banner_anim_mode"] in BANNER_ANIM_MODES:
                banner_anim_mode_var.set(glob["banner_anim_mode"])
            if "out_dir" in glob and glob["out_dir"] and os.path.isdir(glob["out_dir"]):
                out_dir_var.set(glob["out_dir"])
            if "bg_video_1" in glob and glob["bg_video_1"]:
                channel_profiles["video_1"]["bg_video"] = glob["bg_video_1"]
            if "bg_video_2" in glob and glob["bg_video_2"]:
                channel_profiles["video_2"]["bg_video"] = glob["bg_video_2"]
            if "lock_positions" in glob:
                lock_positions_var.set(bool(glob["lock_positions"]))

            # 3. Restore active profile
            saved_active = data.get("active_profile", "video_1")
            if saved_active in channel_profiles:
                active_profile_key[0] = saved_active
                profile_segmented.set("🎬 Video 1 (Channel 1 Profile)" if saved_active == "video_1" else "🎬 Video 2 (Channel 2 Profile)")
                prev_switcher.set("Video 1" if saved_active == "video_1" else "Video 2")

            # 4. Load into UI form
            _load_profile_to_form(active_profile_key[0])
            _log_console("✔ Auto-restored last applied studio settings from previous session.")
            return True
        except Exception as ex:
            _log_console(f"[STATE LOAD ERROR] {ex}")
            _load_profile_to_form(active_profile_key[0])
            return False
        finally:
            try:
                container.after(600, lambda: _is_loading_state.__setitem__(0, False))
            except Exception:
                _is_loading_state[0] = False

    def _switch_active_profile(new_key: str):
        if new_key == active_profile_key[0]:
            return
        _save_form_to_profile(active_profile_key[0])
        active_profile_key[0] = new_key
        _load_profile_to_form(new_key)
        profile_segmented.set("🎬 Video 1 (Channel 1 Profile)" if new_key == "video_1" else "🎬 Video 2 (Channel 2 Profile)")
        prev_switcher.set("Video 1" if new_key == "video_1" else "Video 2")
        _log_console(f"Switched active channel profile to: {new_key.upper()}")
        _schedule_state_save()

    def _on_profile_switch_gui(val):
        target = "video_1" if "1" in val else "video_2"
        _switch_active_profile(target)

    def _on_preview_switch_gui(val):
        target = "video_1" if "1" in val else "video_2"
        _switch_active_profile(target)

    def _copy_v1_to_v2():
        _save_form_to_profile(active_profile_key[0])
        src = copy.deepcopy(channel_profiles["video_1"])
        channel_profiles["video_2"] = src
        channel_profiles["video_2"]["name"] = "Video 2"
        if active_profile_key[0] == "video_2":
            _load_profile_to_form("video_2")
        _show_alert("Settings Copied", "All settings, branding, colors & layout copied from Video 1 -> Video 2!")
        _log_console("Copied Video 1 profile settings to Video 2.")
        _schedule_state_save()

    def _save_preset_dialog():
        _save_form_to_profile(active_profile_key[0])
        p = channel_profiles[active_profile_key[0]]
        presets_d = Path("presets")
        presets_d.mkdir(exist_ok=True)
        f = filedialog.asksaveasfilename(
            initialdir=str(presets_d.resolve()),
            defaultextension=".json",
            filetypes=[("Preset JSON", "*.json")],
            initialfile=f"{active_profile_key[0]}_custom_preset.json"
        )
        if f:
            try:
                with open(f, "w", encoding="utf-8") as fp:
                    json.dump(p, fp, indent=4, ensure_ascii=False)
                _show_alert("Preset Saved", f"Successfully saved preset to:\n{Path(f).name}")
                _log_console(f"Saved preset file: {f}")
            except Exception as ex:
                _show_alert("Save Error", str(ex))

    def _load_preset_dialog():
        presets_d = Path("presets")
        presets_d.mkdir(exist_ok=True)
        f = filedialog.askopenfilename(
            initialdir=str(presets_d.resolve()),
            filetypes=[("Preset JSON", "*.json")]
        )
        if f and os.path.exists(f):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                cur_k = active_profile_key[0]
                channel_profiles[cur_k].update(data)
                _load_profile_to_form(cur_k)
                _show_alert("Preset Loaded", f"Loaded preset '{Path(f).stem}' into {cur_k.upper()}!")
                _log_console(f"Loaded preset file: {f}")
                _schedule_state_save()
            except Exception as ex:
                _show_alert("Load Error", str(ex))

    def _apply_template_preset(choice):
        if choice == "⚡ Templates":
            return
        mapping = {
            "Worship Gold Luxe": "01_worship_gold_luxe.json",
            "Cyber Spotify Neon": "02_cyber_spotify_neon.json",
            "Cathedral Praise": "03_cathedral_praise.json",
            "Sunset Acoustic Flow": "04_sunset_acoustic_flow.json"
        }
        fname = mapping.get(choice)
        if fname:
            p_file = Path("presets") / fname
            if p_file.exists():
                try:
                    with open(p_file, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                    cur_k = active_profile_key[0]
                    channel_profiles[cur_k].update(data)
                    _load_profile_to_form(cur_k)
                    _log_console(f"Applied built-in template '{choice}' to {cur_k.upper()}")
                    _schedule_state_save()
                except Exception as ex:
                    _log_console(f"Template load error: {ex}")
        template_menu.set("⚡ Templates")

    # Connect buttons to commands
    profile_segmented.configure(command=_on_profile_switch_gui)
    prev_switcher.configure(command=_on_preview_switch_gui)
    btn_copy_v1_v2.configure(command=_copy_v1_to_v2)
    btn_save_preset.configure(command=_save_preset_dialog)
    btn_load_preset.configure(command=_load_preset_dialog)
    template_menu.configure(command=_apply_template_preset)

    # Auto-save triggers on any setting change
    for _tr_var in [
        player_style_var, font_family_var, font_bold_var, font_italic_var,
        text_shadow_var, resolution_var, quality_var, fps_var, audio_bitrate_var,
        gpu_mode_var, parallel_render_var, show_banner_var, banner_anim_mode_var,
        bg_effect_var, title_color_var, subtitle_color_var, accent_color_var,
        bg_video_path_var, vid2_path_var, logo_path_var
    ]:
        try:
            _tr_var.trace_add("write", lambda *a: _schedule_state_save())
        except Exception:
            pass

    try:
        cta_top_entry.bind("<KeyRelease>", lambda e: _schedule_state_save())
        cta_bot_entry.bind("<KeyRelease>", lambda e: _schedule_state_save())
    except Exception:
        pass

    # Interactive 3D Canvas Box
    canvas_frame = ctk.CTkFrame(
        right_frame,
        fg_color="#090c14",
        corner_radius=12,
        border_width=2,
        border_color=THEME["card_border"]
    )
    canvas_frame.grid(row=2, column=0, sticky="ew", padx=14, pady=4)

    raw_canvas = tk.Canvas(
        canvas_frame,
        width=CW,
        height=CH,
        bg="#090c14",
        highlightthickness=0,
        bd=0
    )
    raw_canvas.pack(fill="both", expand=True, padx=4, pady=4)

    # Mouse Drag Handlers
    def _get_canvas_element_at(cx: int, cy: int) -> Optional[str]:
        if show_banner_var.get():
            bx = pos_1080["banner"][0] / SCALE
            by = pos_1080["banner"][1] / SCALE
            if bx <= cx <= bx + 360 and by <= cy <= by + 45:
                return "banner"

        lx = pos_1080["logo"][0] / SCALE
        ly = pos_1080["logo"][1] / SCALE
        if lx <= cx <= lx + 45 and ly <= cy <= ly + 45:
            return "logo"

        if studio_mode_var.get() == "video_to_music":
            sx = pos_1080["subject"][0] / SCALE
            sy = pos_1080["subject"][1] / SCALE
            if sx <= cx <= sx + 200 and sy <= cy <= sy + 250:
                return "subject"

        tx = pos_1080["text"][0] / SCALE
        ty = pos_1080["text"][1] / SCALE
        if tx <= cx <= tx + 320 and ty - 10 <= cy <= ty + 60:
            return "text"

        vx = pos_1080["viz"][0] / SCALE
        vy = pos_1080["viz"][1] / SCALE
        if vx <= cx <= vx + 400 and vy <= cy <= vy + 40:
            return "viz"

        return None

    def _on_canvas_press(event):
        if lock_positions_var.get():
            return
        cx, cy = event.x, event.y
        elem = _get_canvas_element_at(cx, cy)
        if elem:
            active_drag_elem["name"] = elem
            ex = pos_1080[elem][0] / SCALE
            ey = pos_1080[elem][1] / SCALE
            active_drag_elem["offset_x"] = cx - ex
            active_drag_elem["offset_y"] = cy - ey

    def _on_canvas_drag(event):
        if lock_positions_var.get() or not active_drag_elem["name"]:
            return
        elem = active_drag_elem["name"]
        cx = event.x - active_drag_elem["offset_x"]
        cy = event.y - active_drag_elem["offset_y"]

        cx = max(0, min(CW - 40, cx))
        cy = max(0, min(CH - 30, cy))

        pos_1080[elem][0] = int(cx * SCALE)
        pos_1080[elem][1] = int(cy * SCALE)

        pos_info_lbl.configure(text=f"Banner: {pos_1080['banner'][0]},{pos_1080['banner'][1]} | Logo: {pos_1080['logo'][0]},{pos_1080['logo'][1]}")

    def _on_canvas_release(event):
        active_drag_elem["name"] = None
        _save_form_to_profile(active_profile_key[0])
        _schedule_state_save()

    raw_canvas.bind("<ButtonPress-1>", _on_canvas_press)
    raw_canvas.bind("<B1-Motion>", _on_canvas_drag)
    raw_canvas.bind("<ButtonRelease-1>", _on_canvas_release)

    # Process Monitor
    monitor_frame = ctk.CTkFrame(
        right_frame,
        fg_color=THEME["card"],
        corner_radius=12,
        border_width=1,
        border_color=THEME["card_border"]
    )
    monitor_frame.grid(row=3, column=0, sticky="nsew", padx=14, pady=(6, 12))
    monitor_frame.grid_rowconfigure(3, weight=1)
    monitor_frame.grid_columnconfigure(0, weight=1)

    step_badge_lbl = ctk.CTkLabel(
        monitor_frame,
        text="Step 0/6: Ready to start bulk generation & render",
        font=FONTS["body_bold"],
        text_color="#4ade80",
        anchor="w"
    )
    step_badge_lbl.grid(row=0, column=0, sticky="w", padx=12, pady=(10, 2))

    master_pbar = ctk.CTkProgressBar(monitor_frame, progress_color=THEME["accent"], fg_color="#121622", height=10)
    master_pbar.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 6))
    master_pbar.set(0)

    mon_tabview = ctk.CTkTabview(
        monitor_frame,
        fg_color="transparent",
        segmented_button_fg_color="#121622",
        segmented_button_selected_color=THEME["btn_indigo"],
        segmented_button_selected_hover_color=THEME["btn_indigo_hover"],
        text_color=THEME["text"],
        corner_radius=8
    )
    mon_tabview.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0, 8))

    tab_queue = mon_tabview.add("🎵 Song Queue")
    tab_console = mon_tabview.add("💻 Detailed Process Logs")

    tab_queue.grid_columnconfigure(0, weight=1)
    tab_queue.grid_rowconfigure(0, weight=1)
    tab_console.grid_columnconfigure(0, weight=1)
    tab_console.grid_rowconfigure(0, weight=1)

    queue_scroll = ctk.CTkScrollableFrame(tab_queue, fg_color="transparent")
    queue_scroll.grid(row=0, column=0, sticky="nsew")
    queue_scroll.grid_columnconfigure(0, weight=1)

    console_textbox = ctk.CTkTextbox(
        tab_console,
        fg_color="#0e111a",
        border_width=1,
        border_color="#273048",
        corner_radius=8,
        font=("Consolas", 11),
        text_color="#a3e635",
        wrap="word"
    )
    console_textbox.grid(row=0, column=0, sticky="nsew")

    def _log_console(msg: str):
        timestamp = time.strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {msg}\n"
        def _write():
            console_textbox.insert("end", log_line)
            console_textbox.see("end")
        container.after(0, _write)

    _log_console("Bulk Video Studio Ready. Accordion blocks, Emoji engine & Remove controls active.")

    # ════════════════════════════════════════════════════════════════
    # ════════════════════════════════════════════════════════════════
    # ANIMATED REAL-TIME CANVAS RENDER LOOP (~25 FPS) WITH EMOJI ENGINE
    # ════════════════════════════════════════════════════════════════
    import cv2

    class VideoPreviewPlayer:
        def __init__(self):
            self.cap = None
            self.current_path = None
            self.last_frame = None

        def get_frame(self, video_path: str, target_w: int, target_h: int) -> Optional[Image.Image]:
            if not video_path or not os.path.exists(video_path):
                if self.cap is not None:
                    self.cap.release()
                    self.cap = None
                    self.current_path = None
                return None

            if self.current_path != video_path or self.cap is None or not self.cap.isOpened():
                if self.cap is not None:
                    self.cap.release()
                self.cap = cv2.VideoCapture(video_path)
                self.current_path = video_path

            if not self.cap.isOpened():
                return None

            ret, frame = self.cap.read()
            if not ret:
                # Seamless loop to frame 0
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = self.cap.read()
                if not ret:
                    return self.last_frame

            try:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_frame = Image.fromarray(frame_rgb)
                resized = pil_frame.resize((target_w, target_h), Image.Resampling.BILINEAR).convert("RGBA")
                self.last_frame = resized
                return resized
            except Exception:
                return self.last_frame

    video_preview_player = VideoPreviewPlayer()
    tk_img_ref = [None]
    bg_cache = {}

    def _get_pil_font(family: str, size: int, bold: bool, italic: bool):
        path, _ = resolve_font_file(family, bold, italic)
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            return ImageFont.load_default()

    def _draw_canvas_frame():
        is_video_mode = (studio_mode_var.get() == "video_to_music")
        t = time.time()

        if is_video_mode:
            mode = preview_mode_var.get()
            prev_key = "video_2" if "2" in mode else "video_1"
            if active_profile_key[0] == prev_key:
                bg_vid_p = bg_video_path_var.get()
            else:
                bg_vid_p = channel_profiles.get(prev_key, {}).get("bg_video", "") or bg_video_path_var.get()
            base_bg = None

            if bg_vid_p and os.path.exists(bg_vid_p):
                # Extract and display real live video frame in real time (25 FPS)
                base_bg = video_preview_player.get_frame(bg_vid_p, CW, CH)

            if base_bg is None:
                base_bg = Image.new("RGBA", (CW, CH), (20, 26, 38, 255))
                bg_draw = ImageDraw.Draw(base_bg)
                for wave_i in range(8):
                    wy = 180 + wave_i * 22 + int(math.sin(t * 2.0 + wave_i) * 6)
                    bg_draw.line([(0, wy), (CW, wy)], fill=(45, 65, 95, 140), width=2)
                bg_draw.text(
                    (CW // 2, CH // 2 - 20),
                    "🎬 Upload Looped Background Video (.mp4 / .mov)",
                    fill=(148, 163, 184),
                    font=_get_pil_font("Segoe UI", 12, True, False),
                    anchor="mm"
                )

            base_img = base_bg.copy()

            cutout_p = fg_cutout_path_var.get() or fg_image_path_var.get()
            if cutout_p and os.path.exists(cutout_p):
                if cutout_p not in bg_cache:
                    try:
                        c_img = Image.open(cutout_p).convert("RGBA")
                        bg_cache[cutout_p] = c_img
                    except Exception:
                        bg_cache[cutout_p] = None

                c_img = bg_cache.get(cutout_p)
                if c_img:
                    scale_mult = max(0.2, min(3.5, fg_scale_var.get() / 100.0))
                    target_h = int(240 * scale_mult)
                    aspect = c_img.width / max(1, c_img.height)
                    target_w = int(target_h * aspect)
                    resized_cutout = c_img.resize((target_w, target_h), Image.Resampling.BILINEAR)

                    sx = int(pos_1080["subject"][0] / SCALE)
                    sy = int(pos_1080["subject"][1] / SCALE)
                    base_img.paste(resized_cutout, (sx, sy), resized_cutout)

        else:
            mode = preview_mode_var.get()
            bg_path = img1_path_var.get() if "1" in mode else (img2_path_var.get() or img1_path_var.get())
            bg_eff = bg_effect_var.get().lower()

            if bg_path and os.path.exists(bg_path):
                if bg_path not in bg_cache:
                    try:
                        raw = Image.open(bg_path).convert("RGBA")
                        bg_cache[bg_path] = raw
                    except Exception:
                        bg_cache[bg_path] = Image.new("RGBA", (CW, CH), (28, 34, 48, 255))
                source_img = bg_cache[bg_path]

                sw, sh = source_img.size
                if "ken burns" in bg_eff or "slow zoom" in bg_eff:
                    zoom_factor = 1.05 + 0.05 * math.sin(t * 0.3)
                    crop_w = int(sw / zoom_factor)
                    crop_h = int(sh / zoom_factor)
                    off_x = int((sw - crop_w) / 2 + math.sin(t * 0.25) * ((sw - crop_w) * 0.3))
                    off_y = int((sh - crop_h) / 2 + math.cos(t * 0.18) * ((sh - crop_h) * 0.3))
                    off_x = max(0, min(sw - crop_w, off_x))
                    off_y = max(0, min(sh - crop_h, off_y))
                    cropped = source_img.crop((off_x, off_y, off_x + crop_w, off_y + crop_h))
                    base_img = cropped.resize((CW, CH), Image.Resampling.BILINEAR)
                elif "bass pulse" in bg_eff or "pulse & zoom" in bg_eff:
                    pulse_zoom = 1.02 + 0.03 * abs(math.sin(t * 3.5))
                    crop_w = int(sw / pulse_zoom)
                    crop_h = int(sh / pulse_zoom)
                    off_x = (sw - crop_w) // 2
                    off_y = (sh - crop_h) // 2
                    cropped = source_img.crop((off_x, off_y, off_x + crop_w, off_y + crop_h))
                    base_img = cropped.resize((CW, CH), Image.Resampling.BILINEAR)
                elif "panoramic drift" in bg_eff or "pan" in bg_eff:
                    crop_w = int(sw * 0.88)
                    crop_h = sh
                    off_x = int((sw - crop_w) / 2 + math.sin(t * 0.2) * ((sw - crop_w) * 0.45))
                    off_x = max(0, min(sw - crop_w, off_x))
                    cropped = source_img.crop((off_x, 0, off_x + crop_w, crop_h))
                    base_img = cropped.resize((CW, CH), Image.Resampling.BILINEAR)
                else:
                    base_img = source_img.resize((CW, CH), Image.Resampling.BILINEAR)
            else:
                base_img = Image.new("RGBA", (CW, CH), (28, 34, 48, 255))

        draw = ImageDraw.Draw(base_img)

        user_font_family = font_family_var.get()
        user_fsize = int(font_size_var.get() / SCALE)
        user_bold = font_bold_var.get()
        user_italic = font_italic_var.get()
        
        main_font = _get_pil_font(user_font_family, user_fsize, user_bold, user_italic)
        sub_font = _get_pil_font(user_font_family, max(10, int(user_fsize * 0.62)), False, False)
        
        # Emoji-enabled font for CTA banner and symbols
        emoji_banner_font = get_emoji_pil_font(11)
        badge_font = _get_pil_font("Segoe UI", 11, True, False)

        c_title_rgb = hex_to_rgb(title_color_var.get())
        c_sub_rgb = hex_to_rgb(subtitle_color_var.get())
        c_accent_rgb = hex_to_rgb(accent_color_var.get())
        c_viz_rgb = hex_to_rgb(viz_color_var.get())
        has_shadow = text_shadow_var.get()

        def _draw_shadow_text(xy, text, fill, font, anchor=None):
            if has_shadow:
                draw.text((xy[0] + 1, xy[1] + 1), text, fill=(0, 0, 0, 220), font=font, anchor=anchor)
            draw.text(xy, text, fill=fill, font=font, anchor=anchor)

        # 2. Channel Logo Overlay
        lx = int(pos_1080["logo"][0] / SCALE)
        ly = int(pos_1080["logo"][1] / SCALE)
        l_scale = max(0.3, min(3.0, logo_scale_var.get() / 100.0))
        target_lw = max(16, int(44 * l_scale))
        l_path = logo_path_var.get()
        if l_path and os.path.exists(l_path):
            try:
                raw_logo = Image.open(l_path).convert("RGBA")
                aspect = raw_logo.width / max(1, raw_logo.height)
                target_lh = max(16, int(target_lw / aspect))
                logo_img = raw_logo.resize((target_lw, target_lh), Image.Resampling.LANCZOS)
                base_img.paste(logo_img, (lx, ly), logo_img)
            except Exception:
                pass
        else:
            draw.rounded_rectangle([lx, ly, lx + target_lw, ly + target_lw], radius=6, fill=(30, 36, 52, 220), outline=c_accent_rgb)
            draw.text((lx + target_lw // 2, ly + target_lw // 2), "LOGO", fill=c_accent_rgb, font=badge_font, anchor="mm")


        # 3. Top Floating CTA Banner (Only rendered if show_banner_var is True!)
        if show_banner_var.get():
            bx = int(pos_1080["banner"][0] / SCALE)
            base_by = int(pos_1080["banner"][1] / SCALE)

            top_txt = cta_top_entry.get().strip() or "🌈🙏 Thank you for worshipping with us! 🙏🌈"
            bot_txt = cta_bot_entry.get().strip() or "👍✨ Please Like & Subscribe 🔔❤️"

            # Measure text width dynamically for perfect container sizing
            dummy = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
            d = ImageDraw.Draw(dummy)
            bb_top = d.textbbox((0, 0), top_txt, font=emoji_banner_font, embedded_color=True) if top_txt else (0, 0, 0, 0)
            bb_bot = d.textbbox((0, 0), bot_txt, font=emoji_banner_font, embedded_color=True) if bot_txt else (0, 0, 0, 0)
            tw = max(bb_top[2] - bb_top[0], bb_bot[2] - bb_bot[0], 220)
            banner_w_c = tw + 34
            banner_h_c = 48

            anim_mode = banner_anim_mode_var.get().lower()

            if "drop" in anim_mode or "vanish" in anim_mode or "slide" in anim_mode:
                # Live dynamic drop from top -> hold static -> vanish -> repeat every 12 seconds in preview
                cycle_t = t % 12.0
                if cycle_t < 0.7:
                    # Slide down smoothly from top
                    prog = (1.0 - math.cos(cycle_t / 0.7 * math.pi)) / 2.0
                    by = -banner_h_c + (base_by + banner_h_c) * prog
                elif cycle_t <= 5.5:
                    # Stay completely static
                    by = base_by
                elif cycle_t < 6.2:
                    # Slide back up and vanish
                    prog = (1.0 - math.cos((cycle_t - 5.5) / 0.7 * math.pi)) / 2.0
                    by = base_by - (base_by + banner_h_c + 20) * prog
                else:
                    # Offscreen / vanished
                    by = -999.0
            elif "ambient float" in anim_mode or "float" in anim_mode:
                float_offset = (math.sin(t * 1.8) * 6 + math.sin(t * 0.8) * 3) if animate_banner_var.get() else 0.0
                by = base_by + float_offset
            else:
                by = base_by

            if by > -banner_h_c:
                banner_rect = [bx, int(by), bx + banner_w_c, int(by) + banner_h_c]
                draw.rounded_rectangle(banner_rect, radius=8, fill=(22, 27, 40, 230), outline=(217, 249, 157, 220), width=1)

                # Draw with Segoe UI Emoji Font with embedded_color=True for full rich colorful emojis!
                draw.text((bx + banner_w_c // 2, int(by) + 14), top_txt, fill=(217, 249, 157, 255), font=emoji_banner_font, anchor="mm", embedded_color=True)
                draw.text((bx + banner_w_c // 2, int(by) + 34), bot_txt, fill=(255, 255, 255, 255), font=emoji_banner_font, anchor="mm", embedded_color=True)

                if not lock_positions_var.get():
                    draw.rectangle(banner_rect, outline=(56, 189, 248), width=1)

        # 4. Border-Free Player Overlays with Real-Time Spinning Vinyl Disc
        tx = int(pos_1080["text"][0] / SCALE)
        ty = int(pos_1080["text"][1] / SCALE)
        if audio_source_mode_var.get() == "premade_audio" and premade_songs_list:
            sample_title = premade_songs_list[0]["title"]
            sample_next = premade_songs_list[1]["title"] if len(premade_songs_list) > 1 else sample_title
        else:
            sample_title = "If The Road Becomes Uncertain"
            sample_next = "Every Closed Door Opens"

        p_sel = player_style_var.get().lower()
        song_pct = (t * 0.08) % 1.0

        if "circular" in p_sel or "spinning" in p_sel or "vinyl" in p_sel or "disc" in p_sel:
            # STYLE 0: Circular Spinning Disc (Rotating Logo Vinyl) — 100% Border-Free!
            disc_sz = 64
            disc_x = tx
            disc_y = ty - 4

            # Prepare circular spinning logo disc
            l_path = logo_path_var.get()
            if l_path and os.path.exists(l_path):
                try:
                    disc_base = Image.open(l_path).convert("RGBA").resize((disc_sz, disc_sz), Image.Resampling.LANCZOS)
                except Exception:
                    disc_base = None
            else:
                disc_base = None

            if disc_base is None:
                # Default stylish gold vinyl disc
                disc_base = Image.new("RGBA", (disc_sz, disc_sz), (0, 0, 0, 0))
                d_disc = ImageDraw.Draw(disc_base)
                d_disc.ellipse([2, 2, disc_sz - 2, disc_sz - 2], fill=(24, 28, 40), outline=c_accent_rgb, width=2)
                d_disc.ellipse([8, 8, disc_sz - 8, disc_sz - 8], outline=(71, 85, 105), width=1)
                d_disc.ellipse([disc_sz//2 - 6, disc_sz//2 - 6, disc_sz//2 + 6, disc_sz//2 + 6], fill=c_accent_rgb)

            # Circular mask
            mask = Image.new("L", (disc_sz, disc_sz), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, disc_sz - 1, disc_sz - 1), fill=255)

            # Rotate continuously in preview!
            rot_deg = (t * 45) % 360
            rotated_disc = disc_base.rotate(-rot_deg, resample=Image.Resampling.BICUBIC)

            # Outer glowing circular ring
            draw.ellipse([disc_x - 3, disc_y - 3, disc_x + disc_sz + 3, disc_y + disc_sz + 3], outline=c_accent_rgb, width=2)
            base_img.paste(rotated_disc, (disc_x, disc_y), mask)

            # Border-free text beside the spinning vinyl
            text_x = disc_x + disc_sz + 14
            _draw_shadow_text((text_x, ty + 2), sample_title, fill=c_title_rgb, font=main_font)

            # Accent progress line
            bar_w = 200
            bar_y = ty + user_fsize + 8
            draw.line([(text_x, bar_y), (text_x + bar_w, bar_y)], fill=(71, 85, 105, 180), width=3)
            draw.line([(text_x, bar_y), (text_x + int(bar_w * song_pct), bar_y)], fill=c_accent_rgb, width=3)
            draw.ellipse([text_x + int(bar_w * song_pct) - 3, bar_y - 3, text_x + int(bar_w * song_pct) + 3, bar_y + 3], fill=(255, 255, 255))

            # Subtitle
            _draw_shadow_text((text_x, bar_y + 8), f"4:54  -  UP NEXT: {sample_next}", fill=c_sub_rgb, font=sub_font)

        elif "bottom left" in p_sel:
            # Studio Bottom Left Clean (Border-Free)
            _draw_shadow_text((tx, ty), f"● NOW PLAYING: {sample_title}", fill=c_title_rgb, font=main_font)
            bar_w = 240
            bar_y = ty + user_fsize + 6
            draw.line([(tx, bar_y), (tx + bar_w, bar_y)], fill=(71, 85, 105, 180), width=2)
            draw.line([(tx, bar_y), (tx + int(bar_w * song_pct), bar_y)], fill=c_accent_rgb, width=2)
            _draw_shadow_text((tx, bar_y + 8), f"UP NEXT - {sample_next}  |  4:54", fill=c_sub_rgb, font=sub_font)

        elif "floating pill" in p_sel:
            # Floating Pill Modern (Border-Free)
            pill_w = 260
            pill_h = user_fsize + 16
            draw.rounded_rectangle([CW//2 - pill_w//2, ty - 4, CW//2 + pill_w//2, ty + pill_h], radius=14, fill=(15, 23, 42, 210))
            _draw_shadow_text((CW // 2, ty + (user_fsize // 2) + 2), f"♫  {sample_title}  (4:54)", fill=c_title_rgb, font=main_font, anchor="mm")

        elif "broadcast" in p_sel:
            # Clean Edge-to-Edge Broadcast Bar (Border-Free)
            draw.rectangle([0, CH - 30, CW, CH], fill=(10, 15, 26, 235))
            draw.line([(0, CH - 30), (int(CW * song_pct), CH - 30)], fill=c_accent_rgb, width=2)
            _draw_shadow_text((16, CH - 16), f"▶ {sample_title}", fill=c_title_rgb, font=main_font, anchor="lm")
            _draw_shadow_text((CW - 16, CH - 16), f"UP NEXT: {sample_next}  |  4:54", fill=c_sub_rgb, font=sub_font, anchor="rm")

        else:
            # Border-Free Centered Worship / Minimal
            _draw_shadow_text((CW // 2, ty), sample_title, fill=c_title_rgb, font=main_font, anchor="mm")
            bar_w = 260
            bar_x1 = (CW - bar_w) // 2
            bar_y1 = ty + user_fsize + 6
            draw.line([(bar_x1, bar_y1), (bar_x1 + bar_w, bar_y1)], fill=(71, 85, 105, 180), width=3)
            active_w = int(bar_w * song_pct)
            draw.line([(bar_x1, bar_y1), (bar_x1 + active_w, bar_y1)], fill=c_accent_rgb, width=3)
            draw.ellipse([bar_x1 + active_w - 3, bar_y1 - 3, bar_x1 + active_w + 3, bar_y1 + 3], fill=(255, 255, 255))
            _draw_shadow_text((bar_x1 + bar_w + 24, bar_y1), "4:54", fill=c_title_rgb, font=sub_font, anchor="lm")
            _draw_shadow_text((CW // 2, bar_y1 + 14), f"UP NEXT - {sample_next}", fill=c_sub_rgb, font=sub_font, anchor="mm")

        # 6. Selection Highlight Outlines if Drag Unlocked
        if not lock_positions_var.get():
            draw.rectangle([lx - 2, ly - 2, lx + 42, ly + 42], outline=(56, 189, 248), width=1)
            draw.rectangle([tx - 4, ty - 12, tx + 320, ty + 50], outline=(56, 189, 248), width=1)

        photo = ImageTk.PhotoImage(base_img)
        tk_img_ref[0] = photo
        raw_canvas.delete("all")
        raw_canvas.create_image(0, 0, image=photo, anchor="nw")

    def _animation_loop():
        try:
            if raw_canvas.winfo_exists() and raw_canvas.winfo_ismapped():
                _draw_canvas_frame()
        except Exception as ex:
            import traceback
            traceback.print_exc()
        if container.winfo_exists():
            container.after(100, _animation_loop)

    container.after(150, _animation_loop)

    # ════════════════════════════════════════════════════════════════
    # MASTER PIPELINE EXECUTION ENGINE (6-STEP BATCH PROCESS)
    # ════════════════════════════════════════════════════════════════
    def _trigger_full_pipeline():
        audio_mode = audio_source_mode_var.get()
        is_premade = (audio_mode == "premade_audio")
        is_video_mode = (studio_mode_var.get() == "video_to_music")

        if is_premade:
            if not premade_songs_list:
                _show_alert("No Premade Songs Selected", "Please click '📁 Select Folder' or '🎵 Select MP3 Files' in Card 3 to choose your songs!")
                return
            parsed_songs = [
                {
                    "title": item["title"],
                    "lyrics": f"Video 1 (Track 1): {item['v1_name']} | Video 2 (Track 2): {item['v2_name']}" if item["is_paired"] else f"Audio Track: {item['v1_name']}",
                    "v1_file": item["v1_file"],
                    "v2_file": item["v2_file"],
                    "is_paired": item["is_paired"]
                }
                for item in premade_songs_list
            ]
            style_prompt = "Premade Local Audio Tracks"
        else:
            raw_text = songs_textbox.get("1.0", "end-1c")
            parsed_songs = parse_songs_text(raw_text)
            style_prompt = style_entry.get().strip()

            if not parsed_songs:
                _show_alert("No Songs Found", "Please paste text containing 'Song 1', 'Song 2', etc.")
                return

            cfg = load_config()
            key = cfg.get("api_key", "")
            if not key and not use_cache_var.get():
                _show_alert("API Key Required", "Please configure your xi-api-key in Settings or switch to Premade Songs mode!")
                return

        if is_video_mode:
            bg_v = bg_video_path_var.get()
            if not bg_v or not os.path.exists(bg_v):
                _show_alert("Background Video Required", "Please select a Looped Background Video file (.mp4, .mov, etc.)!")
                return
        else:
            i1 = img1_path_var.get()
            if not i1 or not os.path.exists(i1):
                _show_alert("Image 1 Required", "Please select Image 1 (for Video 1)!")
                return

        cfg = load_config()
        key = cfg.get("api_key", "")

        out_folder = Path(out_dir_var.get())
        out_folder.mkdir(parents=True, exist_ok=True)

        v1_name = v1_filename_var.get().strip() or "Video_1_Variant_1.mp4"
        if not v1_name.lower().endswith(".mp4"):
            v1_name += ".mp4"

        v2_name = v2_filename_var.get().strip() or "Video_2_Variant_2.mp4"
        if not v2_name.lower().endswith(".mp4"):
            v2_name += ".mp4"

        v1_out_path = str(out_folder / v1_name)
        v2_out_path = str(out_folder / v2_name)
        v1_txt_path = str(out_folder / f"{Path(v1_name).stem}_Timestamps.txt")
        v2_txt_path = str(out_folder / f"{Path(v2_name).stem}_Timestamps.txt")

        chosen_res = resolution_var.get()
        chosen_qual = quality_var.get()
        chosen_bitrate = audio_bitrate_var.get().split()[0]
        try:
            chosen_fps = int(fps_var.get().split()[0])
        except Exception:
            chosen_fps = 30

        btn_start_3d.configure(state="disabled", text="⏳ Pipeline Running...")
        mon_tabview.set("🎵 Song Queue")

        for w in queue_scroll.winfo_children():
            w.destroy()

        cards_data = []
        for song in parsed_songs:
            s_title = song["title"]
            s_lyrics = song["lyrics"]

            card = ctk.CTkFrame(queue_scroll, fg_color=THEME["card"], corner_radius=10, border_width=1, border_color=THEME["card_border"])
            card.pack(fill="x", pady=4, ipady=4)
            card.grid_columnconfigure(1, weight=1)

            st_lbl = ctk.CTkLabel(card, text="⏳ In Queue", font=FONTS["body_bold"], text_color=THEME["warning"])
            st_lbl.grid(row=0, column=0, padx=12, pady=10)

            info_box = ctk.CTkFrame(card, fg_color="transparent")
            info_box.grid(row=0, column=1, sticky="ew", padx=6, pady=6)

            ctk.CTkLabel(info_box, text=s_title, font=FONTS["body_bold"], text_color=THEME["text"], anchor="w").pack(fill="x")
            preview_lyrics = (s_lyrics[:60] + "...") if len(s_lyrics) > 60 else s_lyrics
            ctk.CTkLabel(info_box, text=f"Audio: {preview_lyrics}", font=FONTS["small_bold"], text_color=THEME["text_muted"], anchor="w").pack(fill="x")

            p_bar = ctk.CTkProgressBar(info_box, progress_color=THEME["accent"], fg_color="#121622", height=8)
            p_bar.pack(fill="x", pady=(4, 0))
            p_bar.set(0)

            cards_data.append({
                "title": s_title,
                "lyrics": s_lyrics,
                "card": card,
                "st_lbl": st_lbl,
                "p_bar": p_bar,
                "v1_file": song.get("v1_file"),
                "v2_file": song.get("v2_file"),
                "is_paired": song.get("is_paired", False)
            })

        # Launch Master Pipeline Worker Thread
        def _pipeline_worker():
            try:
                # STEP 1/6: PARSE & VALIDATE (0% -> 5%)
                step1_msg = f"Step 1/6: Loaded {len(cards_data)} premade audio tracks..." if is_premade else "Step 1/6: Parsing songs & initializing bulk assets..."
                _update_step(1, 5, step1_msg, 0.05)
                _log_console(f"=== PIPELINE STARTED ({'PREMADE AUDIO MODE' if is_premade else 'SUNO AI GENERATION MODE'}) ===")
                _log_console(f"Studio Mode: {'🎬 Video to Music' if is_video_mode else '🖼️ Dual Image to Music'}")
                _log_console(f"Resolution / Size: {chosen_res} | Quality: {chosen_qual} | {chosen_fps} FPS | {chosen_bitrate} Audio")
                _log_console(f"Output Save Location: {out_folder}")
                _log_console(f"Songs Count: {len(cards_data)} song(s). Style: '{style_prompt}'")
                _log_console(f"Typography: Family='{font_family_var.get()}', Size={font_size_var.get()}px, Bold={font_bold_var.get()}, Italic={font_italic_var.get()}")
                _log_console(f"Player Layout: '{player_style_var.get()}' | Visualizer: '{viz_style_var.get()}'")
                time.sleep(1)

                if is_premade:
                    # STEP 2 & 3: SKIP SUNO API - PREMADE AUDIO INSTANTLY READY (5% -> 60%)
                    _update_step(2, 60, f"Step 2/6 & 3/6: Skipped Suno AI generation (All {len(cards_data)} premade tracks ready)...", 0.60)
                    for item in cards_data:
                        v1_f = item.get("v1_file")
                        v2_f = item.get("v2_file") or v1_f
                        st_lbl = item["st_lbl"]
                        p_bar = item["p_bar"]
                        card = item["card"]
                        status_text = "✅ Paired Tracks Ready (V1 & V2)" if item.get("is_paired") else "✅ Premade Audio Ready"
                        container.after(0, lambda sl=st_lbl, pb=p_bar, st=status_text: (sl.configure(text=st, text_color=THEME["success"]), pb.set(1.0)))
                        _add_card_buttons(card, item["title"], v1_f, v2_f)

                    v1_tracks = [item["v1_file"] for item in cards_data if item.get("v1_file")]
                    v2_tracks = [item["v2_file"] for item in cards_data if item.get("v2_file")]

                    if not v1_tracks:
                        _log_console("❌ Error: No premade MP3 tracks available. Aborting video render.")
                        _finish_pipeline(False)
                        return

                    _log_console(f"✅ Premade Audio Tracks Ready: {len(v1_tracks)} Video 1 (Track 1) songs, {len(v2_tracks)} Video 2 (Track 2) songs queued. Proceeding straight to dual video render.")

                else:
                    # STEP 2/6: DISPATCH SUNO AI TASKS OR LOAD FROM CACHE (5% -> 20%)
                    _update_step(2, 20, "Step 2/6: Checking audio cache & requesting Suno AI...", 0.10)
                    cache_dir = out_folder / "temp_audio_cache"
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    permanent_cache_dir = get_downloads_dir() / "cache"
                    permanent_cache_dir.mkdir(parents=True, exist_ok=True)

                    api_client = None
                    active_tasks = []
                    use_cache = use_cache_var.get()

                    for idx, item in enumerate(cards_data):
                        s_title = item["title"]
                        s_lyrics = item["lyrics"]
                        st_lbl = item["st_lbl"]
                        p_bar = item["p_bar"]
                        card = item["card"]

                        # Auto-pickup from local cache if enabled
                        if use_cache:
                            c1, c2 = find_cached_audio_for_title(s_title, out_folder)
                            if c1:
                                item["v1_file"] = c1
                                item["v2_file"] = c2 or c1
                                item["is_cached"] = True
                                _log_console(f"📦 [CACHE HIT] '{s_title}' found in cache: {Path(c1).name} (0 Suno Credits Used)")
                                container.after(0, lambda sl=st_lbl, pb=p_bar: (sl.configure(text="⚡ Audio Cached", text_color="#38bdf8"), pb.set(1.0)))
                                _add_card_buttons(card, s_title, c1, c2 or c1)
                                continue

                        # Need to request from Suno API
                        if api_client is None:
                            api_client = SunoAPI(key)

                        _log_console(f"Requesting Suno API for '{s_title}'...")
                        container.after(0, lambda sl=st_lbl, pb=p_bar: (sl.configure(text="⚡ Requesting..."), pb.set(0.1)))

                        ok, task_id_or_err, credits, raw = api_client.generate_music_custom(
                            title=s_title,
                            lyrics=s_lyrics,
                            tags=style_prompt
                        )

                        if ok:
                            _log_console(f"Suno Task created: #{task_id_or_err[:8]} (Remaining Credits: {credits})")
                            item["task_id"] = task_id_or_err
                            active_tasks.append(item)
                            container.after(0, lambda sl=st_lbl, tid=task_id_or_err: sl.configure(text=f"🔄 Processing #{tid[:6]}", text_color="#38bdf8"))
                        else:
                            _log_console(f"❌ Failed to request '{s_title}': {task_id_or_err}")
                            container.after(0, lambda sl=st_lbl, pb=p_bar, err=task_id_or_err: (sl.configure(text="❌ API Error", text_color=THEME["danger"]), pb.set(0)))

                        time.sleep(1)

                    # Check if we have active tasks or all are cached
                    cached_count = sum(1 for item in cards_data if item.get("is_cached"))
                    if not active_tasks and cached_count == 0:
                        _log_console("❌ Error: No tasks were created and no cached songs were found. Aborting pipeline.")
                        _finish_pipeline(False)
                        return

                    # STEP 3/6: POLL TASKS & DOWNLOAD TRACKS (20% -> 60%)
                    if active_tasks:
                        _update_step(3, 35, f"Step 3/6: Polling {len(active_tasks)} Suno AI tasks & downloading tracks...", 0.25)

                        for item in active_tasks:
                            task_id = item["task_id"]
                            title = item["title"]
                            st_lbl = item["st_lbl"]
                            p_bar = item["p_bar"]
                            card = item["card"]

                            _log_console(f"Polling status for task #{task_id[:8]} ({title})...")

                            for attempt in range(120):
                                time.sleep(4)
                                st, prg, meta, err_msg = api_client.get_task_status(task_id)

                                if st == "processing":
                                    val = max(0.1, min(0.95, prg / 100.0 if prg else (attempt * 0.04)))
                                    container.after(0, lambda pb=p_bar, v=val: pb.set(v))
                                elif st == "done":
                                    p_bar.set(1.0)
                                    all_audio = meta.get("all_audio_urls", [])
                                    primary_url = meta.get("audio_url", all_audio[0] if all_audio else "")
                                    second_url = all_audio[1] if len(all_audio) > 1 else primary_url

                                    _log_console(f"✅ Audio ready for '{title}'. Downloading tracks...")

                                    clean_t = "".join(c for c in title if c.isalnum() or c in (" ", "_", "-")).strip()
                                    file1 = cache_dir / f"{clean_t}_Track1.mp3"
                                    file2 = cache_dir / f"{clean_t}_Track2.mp3"

                                    SunoAPI.download_file(primary_url, str(file1))
                                    if second_url:
                                        SunoAPI.download_file(second_url, str(file2))
                                    else:
                                        file2 = file1

                                    # Also save to permanent cache
                                    try:
                                        perm1 = permanent_cache_dir / f"{clean_t}_Track1.mp3"
                                        perm2 = permanent_cache_dir / f"{clean_t}_Track2.mp3"
                                        if not perm1.exists() and file1.exists():
                                            import shutil
                                            shutil.copy2(str(file1), str(perm1))
                                        if not perm2.exists() and file2.exists():
                                            import shutil
                                            shutil.copy2(str(file2), str(perm2))
                                    except Exception:
                                        pass

                                    item["v1_file"] = str(file1)
                                    item["v2_file"] = str(file2)

                                    container.after(0, lambda sl=st_lbl: sl.configure(text="✅ Audio Ready", text_color=THEME["success"]))
                                    _add_card_buttons(card, title, str(file1), str(file2))
                                    break
                                elif st == "error":
                                    _log_console(f"❌ Task error for '{title}': {err_msg}")
                                    container.after(0, lambda sl=st_lbl, pb=p_bar: (sl.configure(text="❌ Failed", text_color=THEME["danger"]), pb.set(0)))
                                    break
                    else:
                        _log_console("⚡ 100% of songs loaded instantly from Local Audio Cache! Skipping API polling & download.")


                v1_tracks = [item["v1_file"] for item in cards_data if item.get("v1_file")]
                v2_tracks = [item["v2_file"] for item in cards_data if item.get("v2_file")]

                if not v1_tracks:
                    _log_console("❌ Error: No MP3 audio tracks were downloaded. Aborting video render.")
                    _finish_pipeline(False)
                    return

                # STEP 4/6: ALBUM TIMELINE SCHEDULE (60% -> 65%)
                _update_step(4, 65, "Step 4/6: Calculating duration & timestamp schedule...", 0.65)
                titles = [item["title"] for item in cards_data if item.get("v1_file")]
                
                sched1 = calculate_album_schedule(v1_tracks, titles)
                total_dur1 = sched1[-1]["end_time"] if sched1 else 180.0
                _log_console(f"Album Schedule: {len(v1_tracks)} tracks, Total Runtime: {int(total_dur1//60)}m {int(total_dur1%60)}s ({int(total_dur1)}s)")

                # STEP 5/6: MULTI-THREADED GPU DUAL VIDEO RENDERING (65% -> 100%)
                chosen_gpu_mode = gpu_mode_var.get()
                is_parallel = parallel_render_var.get()
                cutout_file = fg_cutout_path_var.get() or fg_image_path_var.get()

                _update_step(5, 65, f"Step 5/6: ⚡ GPU Dual Render ({chosen_res} | {chosen_gpu_mode.split()[1] if len(chosen_gpu_mode.split()) > 1 else 'GPU'})...", 0.65)
                _log_console(f"Starting Video Export: Video 1 & Video 2 (Parallel Concurrent: {is_parallel}, GPU Mode: {chosen_gpu_mode})")

                v1_prog = [0.0]
                v2_prog = [0.0]

                def _update_combined_progress():
                    overall_val = 0.65 + ((v1_prog[0] + v2_prog[0]) / 2.0 * 0.35)
                    overall_pct = overall_val * 100.0
                    step_txt = f"Step 5/6 ({overall_pct:.1f}%): ⚡ GPU Dual Render — V1: {int(v1_prog[0]*100)}% | V2: {int(v2_prog[0]*100)}%"
                    container.after(0, lambda: (master_pbar.set(overall_val), step_badge_lbl.configure(text=step_txt)))

                def _v1_progress(pct: float, msg: str = ""):
                    v1_prog[0] = pct
                    _update_combined_progress()
                    if msg:
                        _log_console(f"[GPU V1] {msg}")

                def _v2_progress(pct: float, msg: str = ""):
                    v2_prog[0] = pct
                    _update_combined_progress()
                    if msg:
                        _log_console(f"[GPU V2] {msg}")

                _save_form_to_profile(active_profile_key[0])
                p1 = channel_profiles["video_1"]
                p2 = channel_profiles["video_2"]

                def _run_v1():
                    _log_console(f"Starting Video 1 (Channel 1 Profile) GPU Render: {v1_out_path}")
                    p1_mode = p1.get("mode", "video_to_music")
                    p1_cutout = p1.get("fg_cutout") or p1.get("fg_image")
                    p1_bg_img = p1.get("img_path") or img1_path_var.get() or None
                    p1_bg_vid = p1.get("bg_video") or bg_video_path_var.get() or None
                    p1_pos = p1.get("positions", pos_1080)
                    return render_dual_variant_video(
                        audio_files=v1_tracks,
                        song_titles=titles,
                        output_mp4_path=v1_out_path,
                        mode=p1_mode,
                        bg_image_path=p1_bg_img,
                        bg_video_path=p1_bg_vid,
                        fg_image_path=p1_cutout if (p1_mode == "video_to_music" and p1_cutout and os.path.exists(p1_cutout)) else None,
                        fg_pos=tuple(p1_pos.get("subject", pos_1080["subject"])) if p1_mode == "video_to_music" else None,
                        fg_scale=(p1.get("fg_scale", 100) / 100.0),
                        output_txt_path=v1_txt_path,
                        album_title=titles[0] if titles else "Worship Album",
                        genre_prompt=style_prompt,
                        resolution=chosen_res,
                        quality_preset=chosen_qual,
                        audio_bitrate=chosen_bitrate,
                        fps=chosen_fps,
                        gpu_mode=chosen_gpu_mode,
                        logo_path=p1.get("logo_path") or None,
                        logo_scale=(p1.get("logo_scale", 100) / 100.0),
                        bg_effect=p1.get("bg_effect", "Cinematic Slow Zoom (Ken Burns)"),
                        visualizer_style=p1.get("visualizer_style") or viz_style_var.get() or "None",
                        visualizer_color=p1.get("viz_color", "#BEF264"),
                        player_style=p1.get("player_style") or player_style_var.get() or "🌟 Circular Spinning Disc (Rotating Logo Vinyl)",
                        font_family=p1.get("font_family", "Segoe UI"),
                        font_size=p1.get("font_size", 42),
                        font_bold=p1.get("font_bold", True),
                        font_italic=p1.get("font_italic", False),
                        title_color=p1.get("title_color", "#FFFFFF"),
                        subtitle_color=p1.get("subtitle_color", "#94A3B8"),
                        accent_color=p1.get("accent_color", "#EAB308"),
                        text_shadow=p1.get("text_shadow", True),
                        show_banner=p1.get("show_banner", True),
                        banner_text_top=p1.get("banner_top", "").strip(),
                        banner_text_bottom=p1.get("banner_bot", "").strip(),
                        banner_pos=tuple(p1_pos.get("banner", pos_1080["banner"])),
                        logo_pos=tuple(p1_pos.get("logo", pos_1080["logo"])),
                        text_pos=tuple(p1_pos.get("text", pos_1080["text"])),
                        viz_pos=tuple(p1_pos.get("viz", pos_1080["viz"])),
                        banner_animate=animate_banner_var.get(),
                        banner_anim_mode=p1.get("banner_anim", BANNER_ANIM_MODES[0]),
                        log_fn=_log_console,
                        progress_fn=_v1_progress
                    )

                def _run_v2():
                    _log_console(f"Starting Video 2 (Channel 2 Profile) GPU Render: {v2_out_path}")
                    p2_mode = p2.get("mode", "video_to_music")
                    p2_cutout = p2.get("fg_cutout") or p2.get("fg_image")
                    p2_bg_img = p2.get("img_path") or p1.get("img_path") or img2_path_var.get() or None
                    p2_bg_vid = p2.get("bg_video") or p1.get("bg_video") or bg_video_path_var.get() or None
                    p2_pos = p2.get("positions", pos_1080)
                    return render_dual_variant_video(
                        audio_files=v2_tracks if v2_tracks else v1_tracks,
                        song_titles=titles,
                        output_mp4_path=v2_out_path,
                        mode=p2_mode,
                        bg_image_path=p2_bg_img,
                        bg_video_path=p2_bg_vid,
                        fg_image_path=p2_cutout if (p2_mode == "video_to_music" and p2_cutout and os.path.exists(p2_cutout)) else None,
                        fg_pos=tuple(p2_pos.get("subject", pos_1080["subject"])) if p2_mode == "video_to_music" else None,
                        fg_scale=(p2.get("fg_scale", 100) / 100.0),
                        output_txt_path=v2_txt_path,
                        album_title=titles[0] if titles else "Worship Album",
                        genre_prompt=style_prompt,
                        resolution=chosen_res,
                        quality_preset=chosen_qual,
                        audio_bitrate=chosen_bitrate,
                        fps=chosen_fps,
                        gpu_mode=chosen_gpu_mode,
                        logo_path=p2.get("logo_path") or None,
                        logo_scale=(p2.get("logo_scale", 100) / 100.0),
                        bg_effect=p2.get("bg_effect", "Cinematic Slow Zoom (Ken Burns)"),
                        visualizer_style=p2.get("visualizer_style") or viz_style_var.get() or "None",
                        visualizer_color=p2.get("viz_color", "#38BDF8"),
                        player_style=p2.get("player_style") or player_style_var.get() or "Style 5: Cyberpunk Neon HUD Deck",

                        font_family=p2.get("font_family", "Segoe UI"),
                        font_size=p2.get("font_size", 42),
                        font_bold=p2.get("font_bold", True),
                        font_italic=p2.get("font_italic", False),
                        title_color=p2.get("title_color", "#38BDF8"),
                        subtitle_color=p2.get("subtitle_color", "#67E8F9"),
                        accent_color=p2.get("accent_color", "#38BDF8"),
                        text_shadow=p2.get("text_shadow", True),
                        show_banner=p2.get("show_banner", True),
                        banner_text_top=p2.get("banner_top", "").strip(),
                        banner_text_bottom=p2.get("banner_bot", "").strip(),
                        banner_pos=tuple(p2_pos.get("banner", pos_1080["banner"])),
                        logo_pos=tuple(p2_pos.get("logo", pos_1080["logo"])),
                        text_pos=tuple(p2_pos.get("text", pos_1080["text"])),
                        viz_pos=tuple(p2_pos.get("viz", pos_1080["viz"])),
                        banner_animate=animate_banner_var.get(),
                        banner_anim_mode=p2.get("banner_anim", BANNER_ANIM_MODES[0]),
                        log_fn=_log_console,
                        progress_fn=_v2_progress
                    )

                if is_parallel:
                    _log_console("⚡ Parallel Concurrent Multi-Threaded GPU Dual Rendering Active!")
                    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                        fut1 = pool.submit(_run_v1)
                        fut2 = pool.submit(_run_v2)
                        ok1 = fut1.result()
                        ok2 = fut2.result()
                else:
                    ok1 = _run_v1()
                    ok2 = _run_v2()

                if ok1:
                    _log_console(f"✅ Video 1 successfully rendered: {v1_out_path}")
                    if v1_txt_path and os.path.exists(v1_txt_path):
                        _log_console(f"📌 Video 1 Timestamps exported: {v1_txt_path}")
                        try:
                            with open(v1_txt_path, "r", encoding="utf-8") as tf:
                                ts_text = tf.read().strip()
                                _log_console(f"\n{ts_text}\n")
                        except Exception:
                            pass
                else:
                    _log_console("❌ Video 1 FFmpeg rendering failed.")

                if ok2:
                    _log_console(f"✅ Video 2 successfully rendered: {v2_out_path}")
                    if v2_txt_path and os.path.exists(v2_txt_path):
                        _log_console(f"📌 Video 2 Timestamps exported: {v2_txt_path}")
                        try:
                            with open(v2_txt_path, "r", encoding="utf-8") as tf:
                                ts_text = tf.read().strip()
                                _log_console(f"\n{ts_text}\n")
                        except Exception:
                            pass
                else:
                    _log_console("❌ Video 2 FFmpeg rendering failed.")

                # PIPELINE STATUS REPORTING
                if ok1 and ok2:
                    _update_step(6, 100, f"✅ PROCESS COMPLETE! Both Videos Rendered in {chosen_res}!", 1.0)
                    _log_console("=== PIPELINE FINISHED SUCCESSFULLY ===")
                    _log_console(f"Output Video 1: {v1_out_path}")
                    _log_console(f"Output Video 2: {v2_out_path}")
                    _finish_pipeline(True, v1_out_path, v2_out_path, str(out_folder))
                elif ok1 or ok2:
                    good_v = v1_out_path if ok1 else v2_out_path
                    _update_step(6, 100, f"⚠️ PROCESS PARTIAL: 1 Video Rendered in {chosen_res} (1 Failed)", 1.0)
                    _log_console("=== PIPELINE FINISHED WITH WARNINGS ===")
                    if ok1:
                        _log_console(f"Output Video 1: {v1_out_path}")
                    else:
                        _log_console("Video 1 render failed.")
                    if ok2:
                        _log_console(f"Output Video 2: {v2_out_path}")
                    else:
                        _log_console("Video 2 render failed.")
                    _finish_pipeline(True, good_v, "", str(out_folder))
                else:
                    _update_step(6, 0, f"❌ PROCESS FAILED! Video Rendering Failed in {chosen_res}!", 0.0)
                    _log_console("=== PIPELINE FAILED (See console logs above for FFmpeg error details) ===")
                    _finish_pipeline(False)

            except Exception as ex:
                _log_console(f"❌ Pipeline Exception: {ex}")
                _finish_pipeline(False)

        threading.Thread(target=_pipeline_worker, daemon=True).start()

    def _update_step(step_num: int, pct: int, msg: str, bar_val: float):
        def _u():
            step_badge_lbl.configure(text=f"{msg} ({pct}%)", text_color=THEME["success"] if pct == 100 else THEME["accent"])
            master_pbar.set(bar_val)
        container.after(0, _u)

    def _finish_pipeline(success: bool, v1_path: str = "", v2_path: str = "", folder_path: str = ""):
        def _f():
            btn_start_3d.configure(state="normal", text="🚀  START BULK GENERATION & DUAL RENDER")
            if success:
                chosen_vid = v1_path if (v1_path and os.path.exists(v1_path)) else v2_path
                if chosen_vid and os.path.exists(chosen_vid):
                    setattr(container, "_last_rendered_video", chosen_vid)
                    try:
                        import master_queue
                        master_queue.register_rendered_video(
                            chosen_vid,
                            title=f"Bulk Studio: {Path(chosen_vid).stem}",
                            tool_name="Bulk Video Studio"
                        )
                    except Exception as e:
                        print(f"[BULK_STUDIO] Master queue error: {e}")
                elif folder_path and os.path.exists(folder_path):
                    try:
                        os.startfile(folder_path)
                    except Exception:
                        pass
        container.after(0, _f)

    def _add_card_buttons(card: ctk.CTkFrame, title: str, f1: str, f2: str):
        act_frame = ctk.CTkFrame(card, fg_color="transparent")
        act_frame.grid(row=0, column=2, padx=10, pady=10)

        def _play_f1():
            if f1 and os.path.exists(f1):
                try:
                    import pygame
                    pygame.mixer.music.stop()
                    pygame.mixer.music.load(f1)
                    pygame.mixer.music.play()
                except Exception as ex:
                    print(f"Play error: {ex}")

        def _save_f1():
            if f1 and os.path.exists(f1):
                try:
                    os.startfile(str(Path(f1).parent))
                except Exception:
                    pass

        ctk.CTkButton(
            act_frame,
            text="▶ Play T1",
            width=80,
            height=30,
            fg_color=THEME["accent"],
            hover_color=THEME["accent_hover"],
            text_color="#ffffff",
            font=FONTS["btn_small"],
            corner_radius=8,
            command=_play_f1
        ).pack(side="left", padx=3)

        ctk.CTkButton(
            act_frame,
            text="📁 Open",
            width=75,
            height=30,
            fg_color=THEME["btn_cyan"],
            hover_color=THEME["btn_cyan_hover"],
            text_color="#ffffff",
            font=FONTS["btn_small"],
            corner_radius=8,
            command=_save_f1
        ).pack(side="left", padx=3)

    btn_start_3d.configure(command=_trigger_full_pipeline)

    def _show_alert(title: str, msg: str):
        modal = ctk.CTkToplevel(container.winfo_toplevel())
        modal.title(title)
        modal.geometry("380x180")
        modal.configure(fg_color=THEME["bg"])
        modal.transient(container.winfo_toplevel())
        modal.grab_set()

        ctk.CTkLabel(modal, text=title, font=FONTS["header"], text_color=THEME["danger"]).pack(pady=(20, 10))
        ctk.CTkLabel(modal, text=msg, font=FONTS["body"], text_color=THEME["text"], wraplength=340).pack(pady=(0, 20))
        ctk.CTkButton(modal, text="OK", width=100, fg_color=THEME["secondary_btn"], command=modal.destroy).pack()

    _update_lyrics_detailing()

    # Automatically restore last applied studio settings from previous session
    _load_last_applied_state()

    # Bind container destruction to immediately flush and persist state
    container.bind("<Destroy>", lambda e: _save_last_applied_state())
