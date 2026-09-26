"""
07_suno_music_shorts.py — 📱 Suno Music Shorts Studio Pro (9:16 Vertical HD)
═════════════════════════════════════════════════════════════════════════════════
Direct GPU-Accelerated 9:16 Vertical HD (1080×1920) YouTube Shorts & Reels Generator:
- 📱 100% Native 9:16 Vertical Aspect Ratio (1080x1920 Full HD / 720x1280 / 4K)
- 🎵 1 Song = 1 Short: Every single fetched song renders its own individual Short video!
- 🎬 Per-Song 9:16 Video Upload: Each song has its own "Select 9:16 Video" button!
- 🌐 Universal 9:16 Video Fallback: Apply a default 9:16 video or folder for all songs.
- ⚡ Suno AI Prompts + Premade Local MP3s dual workflow
- 🎯 Individual Custom Prompt Style override per song [📋 Paste Style]
- 🎨 Aesthetic Audio Visualizers (Neon Spectrum, Waveform, Circular Vinyl Disc, Pulse)
- 🚀 YouTube Shorts Direct Upload with #Shorts hashtag injection & live transfer speed
- 🗂️ Universal Master Queue Integration & "Added to Queue" Sequential/Parallel Modal
- 🔄 Auto-Recovery Resumable Upload with Instant [🔄 Retry Upload] button
"""

TAB_TITLE = "📱 Suno Music Shorts"
TAB_ORDER = 12
TAB_GROUP = ""
TAB_ICON = "📱"

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
from tkinter import filedialog, messagebox
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
    detect_hardware_acceleration,
    parse_resolution
)

# Ensure root workspace and uploader_engine are on sys.path
_THIS_FILE = Path(__file__).resolve()
for _cand in [
    _THIS_FILE.parent,
    _THIS_FILE.parent.parent,
    _THIS_FILE.parent.parent.parent,
    _THIS_FILE.parent.parent.parent.parent,
]:
    if _cand.is_dir() and str(_cand) not in sys.path:
        sys.path.insert(0, str(_cand))

try:
    from uploader_engine.pre_render_upload_ui import PreRenderUploadSection, QueueAddedDialog
    from uploader_engine.api import show_quick_upload_modal
except Exception:
    PreRenderUploadSection = None
    QueueAddedDialog = None
    show_quick_upload_modal = None


def parse_songs_text(raw_text: str) -> List[Dict[str, str]]:
    """Parses pasted text containing headers like 'Song 1', 'Song 2', etc. Also supports per-song [Style: ...] tags."""
    if not raw_text or not raw_text.strip():
        return []

    lines = raw_text.strip().split("\n")
    songs = []
    current_title = ""
    current_lyrics_lines = []
    current_style = ""

    header_pattern = re.compile(r'^\s*\[?\s*(?:Song|Track)?\s*(\d+)[:\-\.\s]*(.*?)\]?\s*$', re.IGNORECASE)
    style_pattern = re.compile(r'^\s*\[?(?:Style|Genre|Music Style|Prompt)[:\-\s]+(.*?)\]?\s*$', re.IGNORECASE)

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
                        "lyrics": lyrics_text,
                        "style": current_style
                    })
            num, title_part = match.groups()
            current_title = title_part.strip() if title_part.strip() else f"Song {num}"
            current_lyrics_lines = []
            current_style = ""
            continue

        sm = style_pattern.match(line)
        if sm:
            current_style = sm.group(1).strip()
            continue

        if stripped:
            current_lyrics_lines.append(stripped)

    if current_title or current_lyrics_lines:
        lyrics_text = "\n".join(current_lyrics_lines).strip()
        if lyrics_text or current_title:
            songs.append({
                "title": current_title if current_title else f"Song {len(songs)+1}",
                "lyrics": lyrics_text,
                "style": current_style
            })

    if not songs and raw_text.strip():
        songs.append({
            "title": "Short Track 1",
            "lyrics": raw_text.strip(),
            "style": ""
        })

    return songs


def get_songs_metrics(parsed_songs: List[Dict[str, str]]) -> Dict[str, Any]:
    """Calculates comprehensive lyrics detailing metrics."""
    song_count = len(parsed_songs)
    total_words = 0
    total_chars = 0
    total_chars_no_space = 0
    total_lines = 0
    song_details = []

    for idx, s in enumerate(parsed_songs, 1):
        t = s.get("title", f"Song {idx}")
        lyrics = s.get("lyrics", "")
        style = s.get("style", "")
        words = len(lyrics.split()) if lyrics else 0
        chars = len(lyrics)
        chars_no_sp = len(lyrics.replace(" ", "").replace("\n", "").replace("\r", ""))
        lines = len(lyrics.splitlines()) if lyrics else 0

        total_words += words
        total_chars += chars
        total_chars_no_space += chars_no_sp
        total_lines += lines

        est_dur_sec = max(30, min(180, words * 0.9 + 15))
        m = int(est_dur_sec // 60)
        sec = int(est_dur_sec % 60)
        runtime_str = f"{m}:{sec:02d}"

        song_details.append({
            "index": idx,
            "title": t,
            "words": words,
            "chars": chars,
            "chars_no_space": chars_no_sp,
            "lines": lines,
            "est_runtime": runtime_str,
            "style": style,
            "lyrics": lyrics
        })

    tot_est_sec = song_count * 60
    tot_m = int(tot_est_sec // 60)
    tot_s = int(tot_est_sec % 60)
    tot_runtime_str = f"{tot_m}:{tot_s:02d}"

    return {
        "song_count": song_count,
        "total_words": total_words,
        "total_chars": total_chars,
        "total_chars_no_space": total_chars_no_space,
        "total_lines": total_lines,
        "total_runtime_str": tot_runtime_str,
        "songs": song_details
    }


def hex_to_rgb(hex_str: str) -> Tuple[int, int, int]:
    clean = hex_str.replace("#", "").replace("0x", "")
    if len(clean) == 3:
        clean = "".join([c*2 for c in clean])
    if len(clean) < 6:
        return (255, 255, 255)
    return (int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16))


EMOJI_FONT_PATH = "C:/Windows/Fonts/seguiemj.ttf"
def get_emoji_pil_font(size: int) -> ImageFont.ImageFont:
    if os.path.exists(EMOJI_FONT_PATH):
        try:
            return ImageFont.truetype(EMOJI_FONT_PATH, size)
        except Exception:
            pass
    try:
        return ImageFont.truetype("seguiemj.ttf", size)
    except Exception:
        return ImageFont.load_default()


def find_cached_audio_for_title(title: str, out_folder: Optional[Path] = None) -> Optional[str]:
    """Finds cached audio file for a given title."""
    clean_t = "".join(c for c in title if c.isalnum() or c in (" ", "_", "-")).strip().lower()
    if not clean_t:
        return None

    search_dirs = []
    if out_folder:
        search_dirs.extend([out_folder / "temp_audio_cache", out_folder / "cache", out_folder])
    
    app_downloads = get_downloads_dir()
    search_dirs.extend([app_downloads / "cache", app_downloads / "temp_audio_cache", app_downloads])

    local_down = Path(__file__).resolve().parent.parent / "downloads"
    search_dirs.extend([local_down / "cache", local_down / "temp_audio_cache", local_down])

    valid_dirs = []
    for d in search_dirs:
        try:
            if d.exists():
                valid_dirs.append(d)
        except Exception:
            pass

    for d in valid_dirs:
        for p in [d / f"{clean_t}.mp3", d / f"{clean_t}_Track1.mp3", d / f"{clean_t}_Shorts.mp3"]:
            if p.exists() and p.stat().st_size > 10000:
                return str(p)

    for d in valid_dirs:
        try:
            for mp3_file in d.glob("*.mp3"):
                stem_clean = "".join(c for c in mp3_file.stem if c.isalnum() or c in (" ", "_", "-")).strip().lower()
                if clean_t in stem_clean or (len(clean_t) >= 6 and stem_clean.startswith(clean_t[:15])):
                    if mp3_file.stat().st_size > 10000:
                        return str(mp3_file)
        except Exception:
            pass
    return None


class CollapsibleCard(ctk.CTkFrame):
    """Modern Futuristic Collapsible Accordion Block with Badges & Extend/Collapse."""
    def __init__(
        self,
        master,
        title: str,
        icon: str = "⚡",
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

        self.lbl_title = ctk.CTkLabel(
            self.header,
            text=f"{icon}  {title}",
            font=FONTS["body_bold"],
            text_color=THEME["text"]
        )
        self.lbl_title.grid(row=0, column=0, sticky="w", padx=(0, 8))

        self.lbl_badge = ctk.CTkLabel(
            self.header,
            text=badge_text,
            font=FONTS["small_bold"],
            text_color=badge_color,
            anchor="w"
        )
        self.lbl_badge.grid(row=0, column=1, sticky="w")

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

    def set_badge(self, text: str, color: str = "#38bdf8"):
        self.lbl_badge.configure(text=text, text_color=color)


SHORTS_RESOLUTIONS = [
    "1080x1920 Full HD (9:16 Shorts)",
    "720x1280 HD (9:16 Shorts)",
    "2160x3840 4K (9:16 Shorts)"
]

SHORTS_DURATIONS = [
    "Full Song (Complete Audio)",
    "First 60s (Standard Shorts Limit)",
    "First 90s (Extended Reel)",
    "First 120s (2 Minutes)"
]

QUALITY_PRESETS = [
    "Balanced (Recommended)",
    "Fast (High Speed Render)",
    "Ultra (Crisp Master Quality)",
    "Maximum (Lossless Archive)"
]

BITRATES_LIST = ["192k (Standard High)", "256k (Pristine Master)", "320k (Maximum Fidelity)", "128k (Fast Web)"]
FPS_LIST = ["30 FPS (Standard Smooth)", "60 FPS (Ultra Fluid)", "24 FPS (Cinematic)"]

GPU_MODES = [
    "Auto-Detect (GPU Recommended)",
    "NVIDIA NVENC (High Speed)",
    "Intel QuickSync (QSV)",
    "AMD AMF (Radeon Accelerated)",
    "CPU Multi-Threaded (Fail-Safe)"
]

VISUALIZER_STYLES = [
    "Neon Spectrum Bars",
    "Glowing Waveform Line",
    "Circular Spinning Vinyl",
    "Dual Mirrored Waves",
    "None (Background Only)"
]

PLAYER_STYLES = [
    "Style 1: Centered Modern Shorts",
    "Style 2: Spinning Vinyl Disc",
    "Style 3: Minimalist Glass Card",
    "Style 4: Dynamic Neon Glow"
]


def create(parent_frame, boot_data=None):
    """Mounts the Suno Music Shorts Studio Tab into the parent tab frame."""
    container = ctk.CTkFrame(parent_frame, fg_color=THEME["bg"])
    container.pack(fill="both", expand=True)

    # ════════════════════════════════════════════════════════════════
    # STATE VARIABLES
    # ════════════════════════════════════════════════════════════════
    audio_source_mode_var = ctk.StringVar(value="suno_prompts")  # "suno_prompts" or "premade_audio"
    resolution_var = ctk.StringVar(value=SHORTS_RESOLUTIONS[0])
    duration_mode_var = ctk.StringVar(value=SHORTS_DURATIONS[0])
    quality_var = ctk.StringVar(value=QUALITY_PRESETS[0])
    audio_bitrate_var = ctk.StringVar(value=BITRATES_LIST[0])
    fps_var = ctk.StringVar(value=FPS_LIST[0])
    gpu_mode_var = ctk.StringVar(value=GPU_MODES[0])
    use_cache_var = ctk.BooleanVar(value=True)
    parallel_render_var = ctk.BooleanVar(value=False)

    universal_video_path_var = ctk.StringVar(value="")
    universal_folder_path_var = ctk.StringVar(value="")
    visualizer_style_var = ctk.StringVar(value=VISUALIZER_STYLES[0])
    visualizer_color_var = ctk.StringVar(value="#38bdf8")
    player_style_var = ctk.StringVar(value=PLAYER_STYLES[0])
    font_family_var = ctk.StringVar(value="Segoe UI")
    top_badge_text_var = ctk.StringVar(value="#Shorts")

    default_out_dir = str(get_downloads_dir())
    out_dir_var = ctk.StringVar(value=default_out_dir)

    # Per-song custom video paths and style overrides: {song_key: path_or_str}
    per_song_custom_videos: Dict[str, str] = {}
    per_song_custom_styles: Dict[str, str] = {}
    premade_songs_list: List[Dict[str, Any]] = []

    all_cards: List[CollapsibleCard] = []

    # ════════════════════════════════════════════════════════════════
    # 1. HEADER BRANDING & ACTION BAR
    # ════════════════════════════════════════════════════════════════
    hdr_frame = ctk.CTkFrame(
        container,
        fg_color=THEME["surface"],
        height=58,
        corner_radius=12,
        border_width=1,
        border_color=THEME["card_border"]
    )
    hdr_frame.pack(fill="x", padx=12, pady=(10, 6))
    hdr_frame.pack_propagate(False)

    # Left: Title & 9:16 Badge
    hl = ctk.CTkFrame(hdr_frame, fg_color="transparent")
    hl.pack(side="left", padx=16, pady=8)

    ctk.CTkLabel(
        hl,
        text="📱 SUNO MUSIC SHORTS STUDIO",
        font=FONTS.get("title_large", FONTS.get("title", ("Segoe UI", 16, "bold"))),
        text_color=THEME["text"]
    ).pack(side="left", padx=(0, 10))

    badge_shorts = ctk.CTkFrame(hl, fg_color="#1e1b4b", corner_radius=6, border_width=1, border_color="#818cf8")
    badge_shorts.pack(side="left", padx=4)
    ctk.CTkLabel(badge_shorts, text="📱 9:16 VERTICAL (1080×1920)", font=FONTS["small_bold"], text_color="#a5b4fc").pack(padx=8, pady=2)

    hw_info = detect_hardware_acceleration()
    gpu_badge = ctk.CTkFrame(hl, fg_color="#064e3b", corner_radius=6, border_width=1, border_color="#22c55e")
    gpu_badge.pack(side="left", padx=6)
    ctk.CTkLabel(gpu_badge, text=f"⚡ {hw_info.get('encoder', 'GPU')}", font=FONTS["small_bold"], text_color="#4ade80").pack(padx=8, pady=2)

    # Right: Action Buttons
    hr = ctk.CTkFrame(hdr_frame, fg_color="transparent")
    hr.pack(side="right", padx=14, pady=8)

    def _switch_to_master_queue():
        try:
            top = container.winfo_toplevel()
            def _find_and_switch(widget):
                if hasattr(widget, "set") and hasattr(widget, "_tab_dict"):
                    for t_key in widget._tab_dict.keys():
                        if "Queue" in t_key or "queue" in t_key.lower():
                            widget.set(t_key)
                            return True
                for ch in getattr(widget, "winfo_children", lambda: [])():
                    if _find_and_switch(ch):
                        return True
                return False
            if not _find_and_switch(top):
                # Also try parent hierarchy
                curr = container
                while curr:
                    if hasattr(curr, "set") and hasattr(curr, "_tab_dict"):
                        for t_key in getattr(curr, "_tab_dict", {}).keys():
                            if "Queue" in t_key or "queue" in t_key.lower():
                                curr.set(t_key)
                                return True
                    curr = getattr(curr, "master", None)
        except Exception:
            pass

    btn_to_mq = ctk.CTkButton(
        hr,
        text="🗂 Go to Master Queue",
        width=150,
        height=32,
        font=FONTS["small_bold"],
        fg_color="#6d28d9",
        hover_color="#5b21b6",
        command=_switch_to_master_queue
    )
    btn_to_mq.pack(side="right", padx=4)

    def _toggle_all_cards():
        any_closed = any(not c.is_expanded for c in all_cards)
        for c in all_cards:
            if any_closed:
                c.expand()
            else:
                c.collapse()
        btn_expand_all.configure(text="▲ Collapse All" if any_closed else "▼ Expand All")

    btn_expand_all = ctk.CTkButton(
        hr,
        text="▼ Expand All",
        width=110,
        height=32,
        font=FONTS["btn_small"],
        fg_color=THEME["secondary_btn"],
        hover_color="#2b3954",
        command=_toggle_all_cards
    )
    btn_expand_all.pack(side="right", padx=4)

    # ════════════════════════════════════════════════════════════════
    # 2. PIPELINE PROGRESS STEP BANNER
    # ════════════════════════════════════════════════════════════════
    step_bar_frame = ctk.CTkFrame(container, fg_color=THEME["surface"], corner_radius=10, height=38, border_width=1, border_color=THEME["card_border"])
    step_bar_frame.pack(fill="x", padx=12, pady=(0, 6))
    step_bar_frame.pack_propagate(False)

    step_badge_lbl = ctk.CTkLabel(
        step_bar_frame,
        text="Step 1/6: Configure 9:16 Shorts, Prompts & Videos",
        font=FONTS["body_bold"],
        text_color="#38bdf8"
    )
    step_badge_lbl.pack(side="left", padx=14)

    master_pbar = ctk.CTkProgressBar(step_bar_frame, height=10, progress_color=THEME["accent"], fg_color="#121622")
    master_pbar.pack(side="right", fill="x", expand=True, padx=(10, 14), pady=12)
    master_pbar.set(0.0)

    # ════════════════════════════════════════════════════════════════
    # 3. MAIN WORKSPACE: 2-COLUMN SPLIT
    # ════════════════════════════════════════════════════════════════
    split_panes = ctk.CTkFrame(container, fg_color="transparent")
    split_panes.pack(fill="both", expand=True, padx=12, pady=2)
    split_panes.grid_columnconfigure(0, weight=6, uniform="group1")
    split_panes.grid_columnconfigure(1, weight=5, uniform="group1")
    split_panes.grid_rowconfigure(0, weight=1)

    left_scroll = ctk.CTkScrollableFrame(split_panes, fg_color="transparent")
    left_scroll.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=0)
    left_scroll.grid_columnconfigure(0, weight=1)

    right_col = ctk.CTkFrame(split_panes, fg_color="transparent")
    right_col.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=0)
    right_col.grid_rowconfigure(1, weight=1)
    right_col.grid_columnconfigure(0, weight=1)

    # ────────────────────────────────────────────────────────────────
    # CARD 1: PROMPTS, SONGS & PER-SONG 9:16 VIDEO UPLOAD (EXPANDED)
    # ────────────────────────────────────────────────────────────────
    c_lyrics = CollapsibleCard(left_scroll, "Prompts, Lyrics & Per-Song 9:16 Video Upload", icon="📝", badge_text="0 Songs", default_expanded=True)
    all_cards.append(c_lyrics)
    c_lyrics.body.grid_columnconfigure(0, weight=1)

    # Source mode toggle: Suno AI vs Premade Audio
    mode_sel_frame = ctk.CTkFrame(c_lyrics.body, fg_color="#131724", corner_radius=8, border_width=1, border_color="#2b3954")
    mode_sel_frame.grid(row=0, column=0, sticky="ew", padx=4, pady=(2, 6))
    mode_sel_frame.grid_columnconfigure((0, 1), weight=1)

    def _on_source_mode_change():
        m = audio_source_mode_var.get()
        if m == "suno_prompts":
            prompts_box.grid()
            premade_box.grid_remove()
            _update_lyrics_detailing()
        else:
            prompts_box.grid_remove()
            premade_box.grid()
            _update_premade_list_display()

    r_prompts = ctk.CTkRadioButton(
        mode_sel_frame,
        text="⚡ Generate via Suno AI (Lyrics & Prompts)",
        variable=audio_source_mode_var,
        value="suno_prompts",
        font=FONTS["body_bold"],
        text_color="#f8fafc",
        border_color="#38bdf8",
        fg_color="#0284c7",
        command=_on_source_mode_change
    )
    r_prompts.grid(row=0, column=0, padx=12, pady=8, sticky="w")

    r_premade = ctk.CTkRadioButton(
        mode_sel_frame,
        text="📂 Use Premade MP3 Audio Tracks (Local Files)",
        variable=audio_source_mode_var,
        value="premade_audio",
        font=FONTS["body_bold"],
        text_color="#f8fafc",
        border_color="#38bdf8",
        fg_color="#0284c7",
        command=_on_source_mode_change
    )
    r_premade.grid(row=0, column=1, padx=12, pady=8, sticky="w")

    # Container 1: Suno AI Prompts
    prompts_box = ctk.CTkFrame(c_lyrics.body, fg_color="transparent")
    prompts_box.grid(row=1, column=0, sticky="ew")
    prompts_box.grid_columnconfigure(0, weight=1)

    # Global Style Entry
    style_frame = ctk.CTkFrame(prompts_box, fg_color="#161c2b", corner_radius=8, border_width=1, border_color="#273146")
    style_frame.pack(fill="x", padx=4, pady=(2, 6))
    style_frame.grid_columnconfigure(1, weight=1)

    ctk.CTkLabel(style_frame, text="🌐 Global Style / Genre Prompt:", font=FONTS["small_bold"], text_color="#38bdf8").grid(row=0, column=0, padx=8, pady=6, sticky="w")
    style_entry = ctk.CTkEntry(
        style_frame,
        placeholder_text="e.g. ambient christian lo-fi, peaceful worship, 432hz acoustic guitar, soft soothing male vocal",
        height=32,
        fg_color=THEME["input_bg"],
        border_color=THEME["input_border"],
        font=FONTS["body"]
    )
    style_entry.insert(0, "peaceful christian worship, uplifting acoustic, atmospheric pads, female warm vocals")
    style_entry.grid(row=0, column=1, sticky="ew", padx=4, pady=6)

    def _paste_global_style():
        try:
            cl = container.clipboard_get().strip()
            if cl:
                style_entry.delete(0, "end")
                style_entry.insert(0, cl)
                btn_p_glob.configure(text="✅ Pasted!", fg_color="#10b981")
                container.after(1200, lambda: btn_p_glob.configure(text="📋 Paste", fg_color=THEME["btn_indigo"]))
        except Exception:
            pass

    btn_p_glob = ctk.CTkButton(style_frame, text="📋 Paste", width=75, height=28, fg_color=THEME["btn_indigo"], font=FONTS["btn_small"], command=_paste_global_style)
    btn_p_glob.grid(row=0, column=2, padx=6, pady=6)

    # Prompts Textbox
    songs_textbox = ctk.CTkTextbox(
        prompts_box,
        height=140,
        font=("Consolas", 11),
        fg_color=THEME["input_bg"],
        border_width=1,
        border_color=THEME["input_border"]
    )
    songs_textbox.pack(fill="x", padx=4, pady=(2, 4))

    # Prompts Action Bar
    btn_bar_p = ctk.CTkFrame(prompts_box, fg_color="transparent")
    btn_bar_p.pack(fill="x", padx=4, pady=(0, 6))

    def _load_demo_shorts():
        demo_text = (
            "Song 1: Grace Like Rain\n"
            "[Verse 1]\nYour grace falls down like gentle rain\nWashing all my guilt and pain\n"
            "[Chorus]\nI am healed, I am free\nLord Your love is all I see\n\n"
            "Song 2: Morning Light\n"
            "[Verse 1]\nWith the rising of the sun\nNew mercies have begun\n"
            "[Chorus]\nI praise You in the morning light\nYou make everything so bright\n\n"
            "Song 3: River of Peace\n"
            "[Verse 1]\nThere is a river flowing calm\nIn Your presence is my psalm\n"
            "[Chorus]\nPeace that passes understanding\nOn Your holy truth I'm standing"
        )
        songs_textbox.delete("1.0", "end")
        songs_textbox.insert("1.0", demo_text)
        _update_lyrics_detailing()

    def _load_txt_file():
        fn = filedialog.askopenfilename(title="Load Lyrics .txt File", filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")])
        if fn:
            try:
                with open(fn, "r", encoding="utf-8") as f:
                    txt = f.read()
                songs_textbox.delete("1.0", "end")
                songs_textbox.insert("1.0", txt)
                _update_lyrics_detailing()
            except Exception as ex:
                messagebox.showerror("Error", f"Failed to load file: {ex}")

    def _clear_prompts():
        songs_textbox.delete("1.0", "end")
        _update_lyrics_detailing()

    ctk.CTkButton(btn_bar_p, text="💡 Load Demo Shorts", height=28, fg_color=THEME["btn_emerald"], font=FONTS["btn_small"], command=_load_demo_shorts).pack(side="left", padx=2)
    ctk.CTkButton(btn_bar_p, text="📂 Load .txt File", height=28, fg_color=THEME["btn_indigo"], font=FONTS["btn_small"], command=_load_txt_file).pack(side="left", padx=2)
    ctk.CTkButton(btn_bar_p, text="❌ Clear", width=65, height=28, fg_color=THEME["danger"], font=FONTS["btn_small"], command=_clear_prompts).pack(side="left", padx=2)

    # ── LIVE PARSED SONG DETAILING CONTAINER WITH PER-SONG 9:16 VIDEO UPLOAD ──
    detailing_outer = ctk.CTkFrame(prompts_box, fg_color="#0e1320", corner_radius=10, border_width=1, border_color="#1e293b")
    detailing_outer.pack(fill="x", padx=4, pady=(4, 6))

    det_hdr = ctk.CTkFrame(detailing_outer, fg_color="#141a29", corner_radius=8)
    det_hdr.pack(fill="x", padx=6, pady=6)

    lbl_det_summary = ctk.CTkLabel(
        det_hdr,
        text="📊 Live Shorts List (Each Song = 1 Short Video):",
        font=FONTS["small_bold"],
        text_color="#38bdf8"
    )
    lbl_det_summary.pack(side="left", padx=10, pady=4)

    detailing_scroll = ctk.CTkScrollableFrame(detailing_outer, fg_color="transparent", height=220)
    detailing_scroll.pack(fill="x", padx=6, pady=(0, 6))
    detailing_scroll.grid_columnconfigure(0, weight=1)

    def _update_lyrics_detailing(event=None):
        raw = songs_textbox.get("1.0", "end-1c")
        parsed = parse_songs_text(raw)
        metrics = get_songs_metrics(parsed)
        cnt = metrics["song_count"]

        c_lyrics.set_badge(f"📱 {cnt} Short Video{'s' if cnt != 1 else ''}", "#38bdf8" if cnt > 0 else "#64748b")
        lbl_det_summary.configure(text=f"📊 Live Shorts List: {cnt} Short Video{'s' if cnt != 1 else ''} • {metrics['total_words']} Words")

        for w in detailing_scroll.winfo_children():
            w.destroy()

        if not parsed:
            ctk.CTkLabel(
                detailing_scroll,
                text="Paste song prompts above or click '💡 Load Demo Shorts'.\nEach song row will appear here with an individual '🎬 Select 9:16 Video' button!",
                font=FONTS["small"],
                text_color=THEME["text_muted"]
            ).pack(pady=20)
            return

        for s_idx, song in enumerate(parsed, 1):
            s_title = song["title"]
            s_key = f"Song_{s_idx}_{s_title}"

            row_card = ctk.CTkFrame(detailing_scroll, fg_color="#121622", corner_radius=8, border_width=1, border_color="#2b3954")
            row_card.pack(fill="x", pady=4, padx=2)
            row_card.grid_columnconfigure(1, weight=1)

            # Left: Number & Title
            left_info = ctk.CTkFrame(row_card, fg_color="transparent")
            left_info.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=(6, 2))
            left_info.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(left_info, text=f"#{s_idx}", font=FONTS["body_bold"], text_color="#38bdf8", width=28).pack(side="left")
            ctk.CTkLabel(left_info, text=f"🎬 Short {s_idx}: {s_title}", font=FONTS["body_bold"], text_color="#f8fafc").pack(side="left", padx=6)

            words_cnt = len(song["lyrics"].split())
            ctk.CTkLabel(left_info, text=f"({words_cnt} words)", font=FONTS["small"], text_color=THEME["text_muted"]).pack(side="left")

            # Middle Row: Per-Song 9:16 Video Upload Button
            video_row = ctk.CTkFrame(row_card, fg_color="#171e2e", corner_radius=6, border_width=1, border_color="#223049")
            video_row.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=3)
            video_row.grid_columnconfigure(1, weight=1)

            curr_v = per_song_custom_videos.get(s_key, per_song_custom_videos.get(str(s_idx), ""))

            lbl_v_stat = ctk.CTkLabel(
                video_row,
                text=f"🎬 9:16 Video: {Path(curr_v).name}" if curr_v and os.path.exists(curr_v) else "🖼️ 9:16 Video: Using Universal Default",
                font=FONTS["small_bold"],
                text_color="#4ade80" if (curr_v and os.path.exists(curr_v)) else "#94a3b8"
            )
            lbl_v_stat.grid(row=0, column=0, sticky="w", padx=8, pady=4)

            btn_f_vid = ctk.CTkFrame(video_row, fg_color="transparent")
            btn_f_vid.grid(row=0, column=1, sticky="e", padx=6, pady=4)

            def _select_song_video(sk=s_key, sidx=s_idx, lbl=lbl_v_stat):
                fn = filedialog.askopenfilename(
                    title=f"Select 9:16 Background Video for Short #{sidx}",
                    filetypes=[("Video Files", "*.mp4 *.mov *.webm *.mkv *.avi"), ("All Files", "*.*")]
                )
                if fn:
                    per_song_custom_videos[sk] = fn
                    per_song_custom_videos[str(sidx)] = fn
                    lbl.configure(text=f"🎬 9:16 Video: {Path(fn).name}", text_color="#4ade80")

            btn_pick_vid = ctk.CTkButton(
                btn_f_vid,
                text="🎬 Upload 9:16 Video",
                width=135,
                height=24,
                fg_color="#0284c7",
                hover_color="#0369a1",
                font=FONTS["btn_small"],
                command=_select_song_video
            )
            btn_pick_vid.pack(side="left", padx=2)

            def _clear_song_video(sk=s_key, sidx=s_idx, lbl=lbl_v_stat):
                per_song_custom_videos.pop(sk, None)
                per_song_custom_videos.pop(str(sidx), None)
                lbl.configure(text="🖼️ 9:16 Video: Using Universal Default", text_color="#94a3b8")

            btn_clr_vid = ctk.CTkButton(
                btn_f_vid,
                text="✕ Clear",
                width=55,
                height=24,
                fg_color="#334155",
                hover_color="#475569",
                font=FONTS["btn_small"],
                command=_clear_song_video
            )
            btn_clr_vid.pack(side="left", padx=2)

            # Bottom Row: Style Override with [📋 Paste Style]
            style_row = ctk.CTkFrame(row_card, fg_color="transparent")
            style_row.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=(2, 6))
            style_row.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(style_row, text="🎯 Style:", font=FONTS["small_bold"], text_color="#c084fc").grid(row=0, column=0, padx=(0, 4), sticky="w")

            init_style = per_song_custom_styles.get(s_key, per_song_custom_styles.get(str(s_idx), song.get("style", "")))
            song_style_var = ctk.StringVar(value=init_style)

            style_entry_song = ctk.CTkEntry(
                style_row,
                textvariable=song_style_var,
                placeholder_text="Uses Global Style... (Click '📋 Paste Style' to override)",
                height=24,
                fg_color="#161d2d",
                border_color="#a855f7" if init_style else "#2b3954",
                font=FONTS["small"],
                text_color="#f8fafc"
            )
            style_entry_song.grid(row=0, column=1, sticky="ew", padx=4)

            def _paste_song_style(sk=s_key, sidx=s_idx, sv=song_style_var):
                try:
                    cl = container.clipboard_get().strip()
                    if cl:
                        sv.set(cl)
                        per_song_custom_styles[sk] = cl
                        per_song_custom_styles[str(sidx)] = cl
                except Exception:
                    pass

            ctk.CTkButton(
                style_row,
                text="📋 Paste Style",
                width=88,
                height=24,
                fg_color="#6366f1",
                font=FONTS["small_bold"],
                command=_paste_song_style
            ).grid(row=0, column=2, padx=2)

    songs_textbox.bind("<KeyRelease>", _update_lyrics_detailing)
    songs_textbox.bind("<<Paste>>", lambda e: container.after(50, _update_lyrics_detailing))

    # Container 2: Premade MP3 Audio Tracks
    premade_box = ctk.CTkFrame(c_lyrics.body, fg_color="transparent")
    premade_box.grid(row=2, column=0, sticky="ew")
    premade_box.grid_columnconfigure(0, weight=1)
    premade_box.grid_remove()

    premade_hdr = ctk.CTkFrame(premade_box, fg_color="#171c2b", corner_radius=10, border_width=1, border_color=THEME["card_border"])
    premade_hdr.pack(fill="x", padx=4, pady=(2, 4))
    premade_hdr.grid_columnconfigure(0, weight=1)

    ctk.CTkLabel(premade_hdr, text="📂 Load Local MP3s (Each MP3 = 1 Short Video):", font=FONTS["small_bold"], text_color="#38bdf8").grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(6, 2))
    premade_status_lbl = ctk.CTkLabel(premade_hdr, text="No Premade Songs Selected", font=FONTS["body_bold"], text_color=THEME["text_muted"], anchor="w")
    premade_status_lbl.grid(row=1, column=0, sticky="ew", padx=8, pady=2)

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
        premade_status_lbl.configure(text=f"✅ {cnt} Songs Ready for Shorts Render", text_color=THEME["success"])
        if audio_source_mode_var.get() == "premade_audio":
            c_lyrics.set_badge(f"📱 {cnt} Short Video{'s' if cnt != 1 else ''}", "#38bdf8")

        for idx, item in enumerate(premade_songs_list):
            row_f = ctk.CTkFrame(premade_scroll, fg_color="#121622", corner_radius=8, border_width=1, border_color="#273146")
            row_f.pack(fill="x", pady=3, padx=2)
            row_f.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(row_f, text=f"#{idx+1}", font=FONTS["body_bold"], text_color="#38bdf8", width=34).grid(row=0, column=0, padx=6, pady=6)
            ctk.CTkLabel(row_f, text=f"🎵 {item['title']}", font=FONTS["body_bold"], text_color=THEME["text"], anchor="w").grid(row=0, column=1, sticky="w", padx=4, pady=6)

            # Per-song video picker in premade mode
            p_v = item.get("video_path", "")
            btn_v = ctk.CTkButton(
                row_f,
                text=f"🎬 {Path(p_v).name[:16]}..." if p_v else "🎬 Upload 9:16 Video",
                width=130,
                height=24,
                fg_color="#0284c7" if p_v else THEME["secondary_btn"],
                font=FONTS["btn_small"],
                command=lambda i=idx: _pick_premade_video(i)
            )
            btn_v.grid(row=0, column=2, padx=4, pady=6)

            ctk.CTkButton(
                row_f,
                text="❌",
                width=28,
                height=24,
                fg_color=THEME["danger"],
                font=FONTS["btn_small"],
                command=lambda i=idx: (premade_songs_list.pop(i), _update_premade_list_display())
            ).grid(row=0, column=3, padx=4, pady=6)

    def _pick_premade_video(idx):
        fn = filedialog.askopenfilename(
            title=f"Select 9:16 Video for Song #{idx+1}",
            filetypes=[("Video Files", "*.mp4 *.mov *.webm *.mkv"), ("All Files", "*.*")]
        )
        if fn and idx < len(premade_songs_list):
            premade_songs_list[idx]["video_path"] = fn
            _update_premade_list_display()

    def _browse_premade_folder():
        d = filedialog.askdirectory(title="Select Folder Containing MP3 Songs")
        if d:
            mp3s = sorted([str(p) for p in Path(d).glob("*.mp3")])
            if mp3s:
                premade_songs_list.clear()
                for p in mp3s:
                    premade_songs_list.append({"title": Path(p).stem, "file": str(p), "video_path": ""})
                _update_premade_list_display()
            else:
                messagebox.showwarning("No MP3 Files", f"No .mp3 files found in {d}")

    def _browse_premade_files():
        files = filedialog.askopenfilenames(title="Select MP3 Song Files", filetypes=[("MP3 Audio", "*.mp3")])
        if files:
            premade_songs_list.clear()
            for p in files:
                premade_songs_list.append({"title": Path(p).stem, "file": str(p), "video_path": ""})
            _update_premade_list_display()

    btn_f_pre = ctk.CTkFrame(premade_hdr, fg_color="transparent")
    btn_f_pre.grid(row=2, column=0, columnspan=3, sticky="ew", padx=4, pady=(2, 6))

    ctk.CTkButton(btn_f_pre, text="📁 Select Folder", height=28, fg_color=THEME["btn_indigo"], font=FONTS["btn_small"], command=_browse_premade_folder).pack(side="left", padx=2, expand=True, fill="x")
    ctk.CTkButton(btn_f_pre, text="🎵 Select MP3 Files", height=28, fg_color=THEME["btn_emerald"], font=FONTS["btn_small"], command=_browse_premade_files).pack(side="left", padx=2, expand=True, fill="x")
    ctk.CTkButton(btn_f_pre, text="❌ Clear", width=60, height=28, fg_color=THEME["danger"], font=FONTS["btn_small"], command=lambda: (premade_songs_list.clear(), _update_premade_list_display())).pack(side="left", padx=2)

    premade_scroll = ctk.CTkScrollableFrame(premade_box, fg_color="#0e111a", height=150, corner_radius=8, border_width=1, border_color="#273146")
    premade_scroll.pack(fill="x", padx=4, pady=(0, 6))
    premade_scroll.grid_columnconfigure(1, weight=1)
    _update_premade_list_display()

    # ────────────────────────────────────────────────────────────────
    # CARD 2: UNIVERSAL 9:16 BACKGROUND VIDEO & VISUALS (EXPANDED)
    # ────────────────────────────────────────────────────────────────
    c_media = CollapsibleCard(left_scroll, "Universal 9:16 Background Video & Visualizer", icon="🎬", badge_text="9:16 Video Ready", default_expanded=True)
    all_cards.append(c_media)
    c_media.body.grid_columnconfigure(1, weight=1)

    ctk.CTkLabel(c_media.body, text="Universal 9:16 Video:", font=FONTS["small_bold"], text_color="#38bdf8").grid(row=0, column=0, sticky="w", padx=6, pady=4)
    ent_univ_vid = ctk.CTkEntry(c_media.body, textvariable=universal_video_path_var, height=30, fg_color=THEME["input_bg"], border_color=THEME["input_border"], font=FONTS["small_bold"])
    ent_univ_vid.grid(row=0, column=1, sticky="ew", padx=4, pady=4)

    def _browse_univ_video():
        fn = filedialog.askopenfilename(
            title="Select Universal Default 9:16 Background Video",
            filetypes=[("Video Files", "*.mp4 *.mov *.webm *.mkv"), ("All Files", "*.*")]
        )
        if fn:
            universal_video_path_var.set(fn)
            c_media.set_badge("🎬 9:16 Video Attached", "#4ade80")

    ctk.CTkButton(c_media.body, text="📁 Browse Video", width=110, height=28, fg_color=THEME["btn_indigo"], font=FONTS["btn_small"], command=_browse_univ_video).grid(row=0, column=2, padx=4, pady=4)

    # Folder of 9:16 Videos
    ctk.CTkLabel(c_media.body, text="Or 9:16 Videos Folder:", font=FONTS["small_bold"], text_color=THEME["text_muted"]).grid(row=1, column=0, sticky="w", padx=6, pady=4)
    ent_univ_folder = ctk.CTkEntry(c_media.body, textvariable=universal_folder_path_var, height=28, fg_color=THEME["input_bg"], border_color=THEME["input_border"], font=FONTS["small_bold"])
    ent_univ_folder.grid(row=1, column=1, sticky="ew", padx=4, pady=4)

    def _browse_univ_folder():
        d = filedialog.askdirectory(title="Select Folder of 9:16 Videos (Auto-Rotate across Shorts)")
        if d:
            universal_folder_path_var.set(d)
            c_media.set_badge("📂 Folder Connected", "#a855f7")

    ctk.CTkButton(c_media.body, text="📂 Browse Folder", width=110, height=28, fg_color=THEME["secondary_btn"], font=FONTS["btn_small"], command=_browse_univ_folder).grid(row=1, column=2, padx=4, pady=4)

    # Visualizer Style & Color
    ctk.CTkLabel(c_media.body, text="Audio Visualizer:", font=FONTS["small_bold"], text_color=THEME["text"]).grid(row=2, column=0, sticky="w", padx=6, pady=4)
    ctk.CTkOptionMenu(c_media.body, values=VISUALIZER_STYLES, variable=visualizer_style_var, height=28, fg_color=THEME["input_bg"], button_color=THEME["btn_indigo"], font=FONTS["small_bold"]).grid(row=2, column=1, sticky="ew", padx=4, pady=4)

    ctk.CTkLabel(c_media.body, text="Visualizer Color:", font=FONTS["small_bold"], text_color=THEME["text"]).grid(row=3, column=0, sticky="w", padx=6, pady=4)
    ctk.CTkEntry(c_media.body, textvariable=visualizer_color_var, height=28, fg_color=THEME["input_bg"], border_color=THEME["input_border"], font=FONTS["small_bold"]).grid(row=3, column=1, sticky="ew", padx=4, pady=4)

    # Player Overlay Style
    ctk.CTkLabel(c_media.body, text="Shorts Overlay Style:", font=FONTS["small_bold"], text_color=THEME["text"]).grid(row=4, column=0, sticky="w", padx=6, pady=4)
    ctk.CTkOptionMenu(c_media.body, values=PLAYER_STYLES, variable=player_style_var, height=28, fg_color=THEME["input_bg"], button_color=THEME["secondary_btn"], font=FONTS["small_bold"]).grid(row=4, column=1, sticky="ew", padx=4, pady=4)

    # Top Badge Text
    ctk.CTkLabel(c_media.body, text="Top Badge / Tag:", font=FONTS["small_bold"], text_color=THEME["text"]).grid(row=5, column=0, sticky="w", padx=6, pady=4)
    ctk.CTkEntry(c_media.body, textvariable=top_badge_text_var, height=28, fg_color=THEME["input_bg"], border_color=THEME["input_border"], font=FONTS["small_bold"]).grid(row=5, column=1, sticky="ew", padx=4, pady=4)

    # ────────────────────────────────────────────────────────────────
    # CARD 3: 9:16 RESOLUTION & RENDER QUALITY (COLLAPSIBLE)
    # ────────────────────────────────────────────────────────────────
    c_res = CollapsibleCard(left_scroll, "9:16 Shorts Resolution & Quality", icon="🎚️", badge_text="1080x1920 (9:16)", default_expanded=False)
    all_cards.append(c_res)
    c_res.body.grid_columnconfigure((0, 1), weight=1)

    ctk.CTkLabel(c_res.body, text="Shorts Resolution:", font=FONTS["small_bold"], text_color=THEME["text"]).grid(row=0, column=0, sticky="w", padx=6, pady=2)
    ctk.CTkOptionMenu(c_res.body, values=SHORTS_RESOLUTIONS, variable=resolution_var, height=28, fg_color=THEME["input_bg"], button_color=THEME["btn_indigo"], font=FONTS["btn_small"]).grid(row=0, column=1, sticky="ew", padx=6, pady=2)

    ctk.CTkLabel(c_res.body, text="Shorts Duration Mode:", font=FONTS["small_bold"], text_color=THEME["text"]).grid(row=1, column=0, sticky="w", padx=6, pady=2)
    ctk.CTkOptionMenu(c_res.body, values=SHORTS_DURATIONS, variable=duration_mode_var, height=28, fg_color=THEME["input_bg"], button_color=THEME["secondary_btn"], font=FONTS["btn_small"]).grid(row=1, column=1, sticky="ew", padx=6, pady=2)

    ctk.CTkLabel(c_res.body, text="Quality Preset:", font=FONTS["small_bold"], text_color=THEME["text"]).grid(row=2, column=0, sticky="w", padx=6, pady=2)
    ctk.CTkOptionMenu(c_res.body, values=QUALITY_PRESETS, variable=quality_var, height=28, fg_color=THEME["input_bg"], button_color=THEME["secondary_btn"], font=FONTS["btn_small"]).grid(row=2, column=1, sticky="ew", padx=6, pady=2)

    ctk.CTkLabel(c_res.body, text="GPU Hardware Encoder:", font=FONTS["small_bold"], text_color="#4ade80").grid(row=3, column=0, sticky="w", padx=6, pady=2)
    ctk.CTkOptionMenu(c_res.body, values=GPU_MODES, variable=gpu_mode_var, height=28, fg_color=THEME["input_bg"], button_color=THEME["btn_emerald"], font=FONTS["small_bold"]).grid(row=3, column=1, sticky="ew", padx=6, pady=2)

    chk_cache = ctk.CTkCheckBox(c_res.body, text="📦 Auto-Pick Cached Songs (Saves Suno Credits)", variable=use_cache_var, font=FONTS["body_bold"], text_color="#38bdf8")
    chk_cache.grid(row=4, column=0, columnspan=2, sticky="w", padx=6, pady=(4, 2))

    chk_parallel = ctk.CTkCheckBox(c_res.body, text="⚡ Parallel Concurrent Render (Multiple Shorts at once)", variable=parallel_render_var, font=FONTS["body_bold"], text_color="#f59e0b")
    chk_parallel.grid(row=5, column=0, columnspan=2, sticky="w", padx=6, pady=(2, 4))

    # ────────────────────────────────────────────────────────────────
    # CARD 4: OUTPUT DIRECTORY (COLLAPSIBLE)
    # ────────────────────────────────────────────────────────────────
    c_out = CollapsibleCard(left_scroll, "Output Save Directory", icon="📁", badge_text="Downloads/Shorts", default_expanded=False)
    all_cards.append(c_out)
    c_out.body.grid_columnconfigure(1, weight=1)

    ctk.CTkLabel(c_out.body, text="Save Folder:", font=FONTS["small_bold"], text_color=THEME["text"]).grid(row=0, column=0, sticky="w", padx=6, pady=4)
    ctk.CTkEntry(c_out.body, textvariable=out_dir_var, height=30, fg_color=THEME["input_bg"], border_color=THEME["input_border"], font=FONTS["small_bold"]).grid(row=0, column=1, sticky="ew", padx=4, pady=4)

    def _browse_out():
        d = filedialog.askdirectory(initialdir=out_dir_var.get())
        if d:
            out_dir_var.set(d)

    ctk.CTkButton(c_out.body, text="📁 Browse", width=85, height=28, fg_color=THEME["btn_indigo"], font=FONTS["btn_small"], command=_browse_out).grid(row=0, column=2, padx=4, pady=4)

    # ────────────────────────────────────────────────────────────────
    # CARD 5: YOUTUBE SHORTS DIRECT UPLOAD (COLLAPSIBLE / READY)
    # ────────────────────────────────────────────────────────────────
    c_upload = CollapsibleCard(left_scroll, "YouTube Shorts Direct Upload", icon="🚀", badge_text="Direct Upload Ready", default_expanded=True)
    all_cards.append(c_upload)

    if PreRenderUploadSection:
        try:
            shorts_upload_section = PreRenderUploadSection(
                c_upload.body,
                title="🚀 YouTube Shorts Direct Upload",
                variation_label="Shorts",
                default_privacy="public",
                default_tags=["#Shorts", "#YouTubeShorts", "#SunoMusic", "#ShortsVideo"],
                accent_color="#e11d48",
                default_enabled=False
            )
        except Exception:
            shorts_upload_section = PreRenderUploadSection(
                c_upload.body,
                variation_label="Shorts",
                accent_color="#e11d48",
                default_enabled=False
            )
    else:
        shorts_upload_section = None
        ctk.CTkLabel(c_upload.body, text="YouTube Direct Uploader Engine Attached.", font=FONTS["body_bold"], text_color="#38bdf8").pack(pady=10)

    # ════════════════════════════════════════════════════════════════
    # 4. RIGHT COLUMN: 9:16 LIVE CANVAS & SHORTS QUEUE MONITOR
    # ════════════════════════════════════════════════════════════════
    # 9:16 Portrait Canvas Preview Frame
    canvas_container = ctk.CTkFrame(right_col, fg_color="#0b0f19", corner_radius=12, border_width=1, border_color="#1e293b")
    canvas_container.pack(fill="x", padx=4, pady=(0, 6))

    canv_hdr = ctk.CTkFrame(canvas_container, fg_color="transparent")
    canv_hdr.pack(fill="x", padx=12, pady=6)

    ctk.CTkLabel(canv_hdr, text="📱 LIVE 9:16 SHORTS PREVIEW", font=FONTS["small_bold"], text_color="#38bdf8").pack(side="left")
    ctk.CTkLabel(canv_hdr, text="1080×1920 Vertical Portrait", font=FONTS["small"], text_color="#94a3b8").pack(side="right")

    # 9:16 Canvas Dimensions: Width 270, Height 480
    CW, CH = 270, 480
    canvas_box = ctk.CTkFrame(canvas_container, fg_color="#070a12", width=CW, height=CH, corner_radius=8)
    canvas_box.pack(pady=(0, 10))
    canvas_box.pack_propagate(False)

    raw_canvas = tk.Canvas(canvas_box, width=CW, height=CH, bg="#070a12", highlightthickness=0)
    raw_canvas.pack(fill="both", expand=True)

    tk_img_ref = [None]
    canvas_tick = [0]

    def _draw_916_canvas():
        canvas_tick[0] += 1
        t = canvas_tick[0] * 0.1

        base_img = Image.new("RGBA", (CW, CH), (10, 15, 29, 255))
        draw = ImageDraw.Draw(base_img)

        # Draw subtle vertical gradient or background
        u_vid = universal_video_path_var.get()
        if u_vid and os.path.exists(u_vid):
            # Gradient tone indicating active video
            draw.rectangle([0, 0, CW, CH], fill=(16, 24, 40, 255))
        else:
            # Dark futuristic mesh
            for y in range(0, CH, 40):
                draw.line([(0, y), (CW, y)], fill=(18, 26, 46, 120), width=1)
            for x in range(0, CW, 40):
                draw.line([(x, 0), (x, CH)], fill=(18, 26, 46, 120), width=1)

        # Top Badge (#Shorts)
        badge_t = top_badge_text_var.get() or "#Shorts"
        draw.rounded_rectangle([20, 24, 110, 52], radius=6, fill=(2, 132, 199, 220))
        draw.text((32, 28), badge_t, fill=(255, 255, 255, 255))

        # Channel Badge Top Right
        draw.rounded_rectangle([CW - 95, 24, CW - 20, 52], radius=6, fill=(30, 41, 59, 200))
        draw.text((CW - 85, 28), "● HD 9:16", fill=(56, 189, 248, 255))

        # Title in Lower Third (Centered around y=310)
        draw.text((CW // 2, 305), "🎵 SHORT TITLE PREVIEW", fill=(255, 255, 255, 255), anchor="mm")
        draw.text((CW // 2, 330), "Suno AI Music • Worship", fill=(148, 163, 184, 255), anchor="mm")

        # Audio Waveform / Visualizer Preview around y=365
        viz_st = visualizer_style_var.get()
        v_col_hex = visualizer_color_var.get() or "#38bdf8"
        v_rgb = hex_to_rgb(v_col_hex)

        if "none" not in viz_st.lower():
            wave_y = 370
            wave_w = 210
            start_x = (CW - wave_w) // 2
            for bar_i in range(24):
                bx = start_x + (bar_i * 9)
                bh = int(12 + 18 * abs(math.sin(t * 1.5 + bar_i * 0.4)))
                draw.rounded_rectangle([bx, wave_y - bh // 2, bx + 6, wave_y + bh // 2], radius=3, fill=v_rgb)

        # Progress Line
        prog_y = 415
        prog_w = 210
        p_start_x = (CW - prog_w) // 2
        draw.line([(p_start_x, prog_y), (p_start_x + prog_w, prog_y)], fill=(51, 65, 85, 200), width=3)
        cur_w = int(prog_w * ((t * 0.2) % 1.0))
        draw.line([(p_start_x, prog_y), (p_start_x + cur_w, prog_y)], fill=(56, 189, 248, 255), width=3)
        draw.ellipse([p_start_x + cur_w - 4, prog_y - 4, p_start_x + cur_w + 4, prog_y + 4], fill=(255, 255, 255, 255))

        # Bottom Subtitle / Time
        draw.text((p_start_x, prog_y + 14), "0:15", fill=(148, 163, 184, 255), anchor="lm")
        draw.text((p_start_x + prog_w, prog_y + 14), "0:60", fill=(148, 163, 184, 255), anchor="rm")

        photo = ImageTk.PhotoImage(base_img)
        tk_img_ref[0] = photo
        raw_canvas.delete("all")
        raw_canvas.create_image(0, 0, image=photo, anchor="nw")

    def _anim_loop():
        try:
            if raw_canvas.winfo_exists() and raw_canvas.winfo_ismapped():
                _draw_916_canvas()
        except Exception:
            pass
        if container.winfo_exists():
            container.after(120, _anim_loop)

    container.after(200, _anim_loop)

    # ── SHORTS QUEUE & TERMINAL TABVIEW ──
    mon_tabview = ctk.CTkTabview(
        right_col,
        fg_color="#0e1424",
        segmented_button_fg_color="#121829",
        segmented_button_selected_color=THEME["btn_indigo"],
        text_color="#ffffff",
        corner_radius=10,
        border_width=1,
        border_color="#1e293b"
    )
    mon_tabview.pack(fill="both", expand=True, padx=4, pady=4)

    tab_queue = mon_tabview.add("📱 Shorts Queue")
    tab_log = mon_tabview.add("📋 Live Terminal")

    tab_queue.grid_columnconfigure(0, weight=1)
    tab_queue.grid_rowconfigure(0, weight=1)

    shorts_queue_scroll = ctk.CTkScrollableFrame(tab_queue, fg_color="transparent")
    shorts_queue_scroll.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
    shorts_queue_scroll.grid_columnconfigure(0, weight=1)

    lbl_empty_shorts_queue = ctk.CTkLabel(
        shorts_queue_scroll,
        text="📭 No Shorts rendering right now.\nClick '🚀 START SHORTS GENERATION & BATCH RENDER' below to begin!",
        font=FONTS["body"],
        text_color=THEME["text_muted"]
    )
    lbl_empty_shorts_queue.pack(pady=40)

    # Live Terminal Log Textbox
    tab_log.grid_columnconfigure(0, weight=1)
    tab_log.grid_rowconfigure(0, weight=1)
    log_textbox = ctk.CTkTextbox(tab_log, font=("Consolas", 10), fg_color="#070a12", text_color="#38bdf8")
    log_textbox.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)

    def _log_console(msg: str):
        def _a():
            ts = time.strftime("[%H:%M:%S] ")
            log_textbox.insert("end", ts + msg + "\n")
            log_textbox.see("end")
        container.after(0, _a)

    _log_console("⚡ Suno Music Shorts Studio Pro initialized (9:16 Vertical HD Ready).")

    # ════════════════════════════════════════════════════════════════
    # 5. MASTER SHORTS PIPELINE EXECUTION ENGINE
    # ════════════════════════════════════════════════════════════════
    btn_start_3d = CTk3DButton(
        left_scroll,
        text="🚀  START SHORTS GENERATION & BATCH RENDER",
        color="magenta",
        height=52,
        font=FONTS.get("title_large", FONTS.get("title", ("Segoe UI", 16, "bold"))),
        command=lambda: threading.Thread(target=_trigger_shorts_pipeline, daemon=True).start()
    )
    btn_start_3d.pack(fill="x", padx=12, pady=(10, 20))

    def _update_step(step_idx: int, pct: int, msg: str, pbar_val: float):
        container.after(0, lambda: (
            step_badge_lbl.configure(text=f"Step {step_idx}/6 ({pct}%): {msg}"),
            master_pbar.set(pbar_val)
        ))

    def _trigger_shorts_pipeline():
        try:
            _execute_shorts_pipeline()
        except Exception as ex:
            import traceback
            traceback.print_exc()
            btn_start_3d.configure(state="normal", text="🚀  START SHORTS GENERATION & BATCH RENDER")
            _log_console(f"❌ Pipeline Execution Error: {ex}")
            messagebox.showerror("Pipeline Error", str(ex))

    def _execute_shorts_pipeline():
        btn_start_3d.configure(state="disabled", text="⏳ Shorts Pipeline Running...")
        container.after(0, lambda: mon_tabview.set("📱 Shorts Queue"))

        audio_mode = audio_source_mode_var.get()
        is_premade = (audio_mode == "premade_audio")

        # 1. Gather Songs List
        if is_premade:
            if not premade_songs_list:
                btn_start_3d.configure(state="normal", text="🚀  START SHORTS GENERATION & BATCH RENDER")
                messagebox.showwarning("No Songs", "Please select MP3 audio files or a folder in Card 1!")
                return
            songs_data = [
                {
                    "title": item["title"],
                    "lyrics": "",
                    "audio_file": item["file"],
                    "video_path": item.get("video_path", "")
                }
                for item in premade_songs_list
            ]
        else:
            raw_text = songs_textbox.get("1.0", "end-1c")
            parsed = parse_songs_text(raw_text)
            if not parsed:
                btn_start_3d.configure(state="normal", text="🚀  START SHORTS GENERATION & BATCH RENDER")
                messagebox.showwarning("No Songs", "Please enter song prompts or lyrics in Card 1!")
                return
            songs_data = [
                {
                    "title": p["title"],
                    "lyrics": p["lyrics"],
                    "style": p.get("style", ""),
                    "audio_file": "",
                    "video_path": ""
                }
                for p in parsed
            ]

        total_shorts = len(songs_data)
        _log_console(f"🚀 Initializing Shorts Pipeline for {total_shorts} Short Video{'s' if total_shorts > 1 else ''}...")

        # Clear queue cards UI
        def _clear_cards():
            for w in shorts_queue_scroll.winfo_children():
                w.destroy()
        container.after(0, _clear_cards)

        # Build Queue Cards in UI
        shorts_cards = []
        for idx, item in enumerate(songs_data, 1):
            s_title = item["title"]
            s_key = f"Song_{idx}_{s_title}"

            # Check individual video override
            indiv_v = per_song_custom_videos.get(s_key, per_song_custom_videos.get(str(idx), item.get("video_path", "")))
            if indiv_v and os.path.exists(indiv_v):
                item["video_path"] = indiv_v

            card_f = ctk.CTkFrame(shorts_queue_scroll, fg_color=THEME["card"], corner_radius=10, border_width=1, border_color=THEME["card_border"])
            card_f.pack(fill="x", pady=4, padx=2)
            card_f.grid_columnconfigure(1, weight=1)

            st_pill = ctk.CTkLabel(card_f, text="⏳ In Queue", font=FONTS["small_bold"], text_color=THEME["warning"], fg_color="#332200", corner_radius=6, padx=8, pady=2)
            st_pill.grid(row=0, column=0, padx=10, pady=8)

            c_info = ctk.CTkFrame(card_f, fg_color="transparent")
            c_info.grid(row=0, column=1, sticky="ew", padx=6, pady=6)
            c_info.grid_columnconfigure(0, weight=1)

            t_disp = f"🎬 Short #{idx}: {s_title}"
            ctk.CTkLabel(c_info, text=t_disp, font=FONTS["body_bold"], text_color="#f8fafc", anchor="w").pack(fill="x")

            v_src = Path(item['video_path']).name if item['video_path'] else "Universal Default 9:16 Video"
            lbl_v_info = ctk.CTkLabel(c_info, text=f"📹 Video: {v_src}", font=FONTS["small"], text_color="#38bdf8", anchor="w")
            lbl_v_info.pack(fill="x")

            p_bar = ctk.CTkProgressBar(c_info, height=8, progress_color=THEME["accent"], fg_color="#121622")
            p_bar.pack(fill="x", pady=(4, 2))
            p_bar.set(0.0)

            lbl_sub = ctk.CTkLabel(c_info, text="Waiting in queue...", font=FONTS["small"], text_color=THEME["text_muted"], anchor="w")
            lbl_sub.pack(fill="x")

            # Completion box
            comp_box = ctk.CTkFrame(c_info, fg_color="#062e20", corner_radius=6, border_width=1, border_color="#047857")
            lbl_comp = ctk.CTkLabel(comp_box, text="✅ Short Render Complete (1080x1920 9:16)!", font=FONTS["small_bold"], text_color="#34d399", anchor="w")
            lbl_comp.pack(fill="x", padx=8, pady=(4, 2))

            btn_row = ctk.CTkFrame(comp_box, fg_color="transparent")
            btn_row.pack(fill="x", padx=8, pady=(2, 6))

            btn_play = ctk.CTkButton(btn_row, text="▶ Play Short", width=80, height=24, fg_color="#10b981", font=FONTS["btn_small"])
            btn_play.pack(side="left", padx=2)

            btn_folder = ctk.CTkButton(btn_row, text="📂 Reveal", width=70, height=24, fg_color="#2563eb", font=FONTS["btn_small"])
            btn_folder.pack(side="left", padx=2)

            shorts_cards.append({
                "index": idx,
                "card": card_f,
                "st_pill": st_pill,
                "p_bar": p_bar,
                "lbl_sub": lbl_sub,
                "lbl_v_info": lbl_v_info,
                "comp_box": comp_box,
                "btn_play": btn_play,
                "btn_folder": btn_folder
            })

        out_folder = Path(out_dir_var.get())
        out_folder.mkdir(parents=True, exist_ok=True)
        cache_dir = out_folder / "temp_audio_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # 2. AUDIO RESOLUTION & DOWNLOADING
        if not is_premade:
            _update_step(2, 20, "Step 2/6: Fetching audio from Suno AI / Cache...", 0.15)
            cfg = load_config()
            key = cfg.get("api_key", "")
            api_client = None
            use_cache = use_cache_var.get()
            active_suno_tasks = []

            for idx, item in enumerate(songs_data):
                s_title = item["title"]
                card_ui = shorts_cards[idx]

                # Check cache
                if use_cache:
                    cached_audio = find_cached_audio_for_title(s_title, out_folder)
                    if cached_audio:
                        item["audio_file"] = cached_audio
                        _log_console(f"📦 [CACHE HIT] Audio for '{s_title}' found in cache: {Path(cached_audio).name}")
                        container.after(0, lambda u=card_ui: (
                            u["st_pill"].configure(text="⚡ Audio Ready", text_color="#38bdf8", fg_color="#0c2e4e"),
                            u["p_bar"].set(0.2)
                        ))
                        continue

                # Request Suno API
                if api_client is None:
                    api_client = SunoAPI(key)

                custom_s = per_song_custom_styles.get(f"Song_{idx+1}_{s_title}", per_song_custom_styles.get(str(idx+1), item.get("style", "")))
                effective_style = custom_s.strip() if custom_s.strip() else style_entry.get().strip()

                _log_console(f"Requesting Suno AI for Short #{idx+1} '{s_title}' [Style: '{effective_style}']...")
                container.after(0, lambda u=card_ui: (
                    u["st_pill"].configure(text="⚡ Requesting AI...", text_color="#38bdf8", fg_color="#0c2e4e"),
                    u["p_bar"].set(0.1)
                ))

                ok, task_id_or_err, credits, raw = api_client.generate_music_custom(
                    title=s_title,
                    lyrics=item["lyrics"],
                    tags=effective_style
                )

                if ok:
                    item["task_id"] = task_id_or_err
                    active_suno_tasks.append(item)
                    _log_console(f"Suno Task created: #{task_id_or_err[:8]} (Remaining Credits: {credits})")
                else:
                    _log_console(f"❌ Failed to request '{s_title}': {task_id_or_err}")

                time.sleep(1)

            # Poll Active Suno Tasks
            if active_suno_tasks:
                _update_step(3, 40, f"Step 3/6: Polling {len(active_suno_tasks)} Suno AI audio tracks...", 0.35)
                for item in active_suno_tasks:
                    tid = item["task_id"]
                    t_title = item["title"]
                    clean_t = "".join(c for c in t_title if c.isalnum() or c in (" ", "_", "-")).strip()

                    for attempt in range(120):
                        time.sleep(4)
                        st, prg, meta, err_msg = api_client.get_task_status(tid)
                        if st == "done":
                            all_a = meta.get("all_audio_urls", [])
                            aud_url = meta.get("audio_url", all_a[0] if all_a else "")
                            if aud_url:
                                out_mp3 = cache_dir / f"{clean_t}_Shorts.mp3"
                                SunoAPI.download_file(aud_url, str(out_mp3))
                                item["audio_file"] = str(out_mp3)
                                _log_console(f"✅ Audio downloaded for Short '{t_title}': {out_mp3.name}")
                            break
                        elif st == "error":
                            _log_console(f"❌ Suno generation error for '{t_title}': {err_msg}")
                            break

        # 3. VERIFY ALL AUDIO FILES
        valid_items = [item for item in songs_data if item.get("audio_file") and os.path.exists(item["audio_file"])]
        if not valid_items:
            btn_start_3d.configure(state="normal", text="🚀  START SHORTS GENERATION & BATCH RENDER")
            messagebox.showerror("Audio Error", "No audio tracks were successfully loaded or generated!")
            return

        # 4. RESOLVE 9:16 VIDEOS FOR EACH SHORT
        _update_step(4, 50, "Step 4/6: Resolving 9:16 background videos for each short...", 0.50)
        univ_video = universal_video_path_var.get()
        univ_folder = universal_folder_path_var.get()
        folder_videos = []
        if univ_folder and os.path.exists(univ_folder):
            folder_videos = sorted([str(p) for p in Path(univ_folder).glob("*.mp4")] + [str(p) for p in Path(univ_folder).glob("*.mov")])

        for idx, item in enumerate(songs_data):
            # 1. Per-song video if chosen
            if item.get("video_path") and os.path.exists(item["video_path"]):
                continue
            # 2. Folder video round-robin
            if folder_videos:
                item["video_path"] = folder_videos[idx % len(folder_videos)]
                continue
            # 3. Universal video
            if univ_video and os.path.exists(univ_video):
                item["video_path"] = univ_video
                continue
            # 4. Fallback None (uses dark aesthetic background)
            item["video_path"] = None

        # 5. RENDER EACH SHORT (1 SONG = 1 9:16 SHORT VIDEO)
        _update_step(5, 60, f"Step 5/6: ⚡ GPU Batch Rendering {len(valid_items)} 9:16 Shorts...", 0.60)
        _log_console(f"🎬 Starting 9:16 Short Video Rendering ({resolution_var.get()}). Each song renders its own individual Short video!")

        rendered_shorts_files = []
        tasks_for_direct_upload = []

        chosen_res = resolution_var.get()
        chosen_qual = quality_var.get()
        chosen_bitrate = audio_bitrate_var.get().split()[0]
        chosen_fps = int(fps_var.get().split()[0])
        chosen_gpu = gpu_mode_var.get()
        vis_st = visualizer_style_var.get()
        vis_col = visualizer_color_var.get()
        p_style = player_style_var.get()
        badge_tag = top_badge_text_var.get()

        dur_mode = duration_mode_var.get()
        max_dur_limit = None
        if "60s" in dur_mode:
            max_dur_limit = 60.0
        elif "90s" in dur_mode:
            max_dur_limit = 90.0
        elif "120s" in dur_mode:
            max_dur_limit = 120.0

        def _render_single_short_worker(item_idx: int, item_obj: Dict[str, Any]):
            card_ui = shorts_cards[item_idx]
            s_title = item_obj["title"]
            clean_t = "".join(c for c in s_title if c.isalnum() or c in (" ", "_", "-")).strip()
            out_name = f"Shorts_{item_idx+1:02d}_{clean_t}.mp4"
            out_path = str(out_folder / out_name)

            container.after(0, lambda u=card_ui: (
                u["st_pill"].configure(text="⚡ Rendering 9:16...", text_color="#f59e0b", fg_color="#332200"),
                u["p_bar"].configure(progress_color="#f59e0b")
            ))

            _log_console(f"Rendering Short #{item_idx+1}: {out_name} [9:16 Resolution: {chosen_res}]...")

            def _prog(pct, msg=""):
                p_val = max(0.01, min(1.0, pct))
                container.after(0, lambda u=card_ui, p=p_val, m=msg: (
                    u["p_bar"].set(p),
                    u["lbl_sub"].configure(text=f"Encoding 9:16: {int(p*100)}% {m}")
                ))

            # Execute FFmpeg 9:16 Render via render_dual_variant_video
            success = render_dual_variant_video(
                audio_files=[item_obj["audio_file"]],
                song_titles=[s_title],
                output_mp4_path=out_path,
                mode="video_to_music" if (item_obj.get("video_path") and os.path.exists(item_obj["video_path"])) else "image_to_music",
                bg_video_path=item_obj.get("video_path"),
                bg_image_path=None,
                resolution=chosen_res,
                quality_preset=chosen_qual,
                audio_bitrate=chosen_bitrate,
                fps=chosen_fps,
                gpu_mode=chosen_gpu,
                visualizer_style=vis_st,
                visualizer_color=vis_col,
                player_style=p_style,
                progress_fn=_prog,
                log_fn=_log_console
            )

            if success and os.path.exists(out_path):
                rendered_shorts_files.append(out_path)
                _log_console(f"✅ Short #{item_idx+1} Render Complete: {out_name}")

                # Register into Universal Master Queue
                try:
                    import master_queue
                    master_queue.register_rendered_video(
                        video_path=out_path,
                        title=f"Short #{item_idx+1}: {s_title}",
                        tool_name="Suno Music Shorts",
                        show_popup=False
                    )
                except Exception as mq_ex:
                    pass

                def _open_f(p=out_path):
                    try:
                        subprocess.Popen(f'explorer /select,"{os.path.abspath(p)}"')
                    except Exception:
                        pass

                def _play_v(p=out_path):
                    try:
                        os.startfile(p)
                    except Exception:
                        pass

                container.after(0, lambda u=card_ui, p=out_path: (
                    u["st_pill"].configure(text="✅ Rendered", text_color="#34d399", fg_color="#064e3b"),
                    u["p_bar"].set(1.0),
                    u["p_bar"].configure(progress_color="#10b981"),
                    u["lbl_sub"].configure(text="✓ 1080x1920 Short Ready"),
                    u["comp_box"].pack(fill="x", pady=(4, 0)),
                    u["btn_play"].configure(command=lambda: _play_v(p)),
                    u["btn_folder"].configure(command=lambda: _open_f(p))
                ))

                # Check if YouTube Direct Upload enabled
                if shorts_upload_section and shorts_upload_section.upload_enabled_var.get():
                    ch_id = shorts_upload_section.get_target_channel_id()
                    ch_name = shorts_upload_section.ch_menu.get()
                    if ch_id:
                        tasks_for_direct_upload.append({
                            "id": f"short_{item_idx}_{int(time.time())}",
                            "video_path": out_path,
                            "title": f"{s_title} #Shorts",
                            "description": f"Listen to '{s_title}'. Produced with AI Music Suite.\n\n#Shorts #YouTubeShorts #SunoAI",
                            "tags": ["#Shorts", "#YouTubeShorts", "#SunoAI", "#MusicShorts"],
                            "channel_id": ch_id,
                            "channel_name": ch_name,
                            "privacy_status": shorts_upload_section.privacy_menu.get().lower(),
                            "made_for_kids": bool(shorts_upload_section.kids_var.get()),
                            "variation_label": f"Short #{item_idx+1}"
                        })
            else:
                _log_console(f"❌ Short #{item_idx+1} Render Failed: {out_name}")
                container.after(0, lambda u=card_ui: (
                    u["st_pill"].configure(text="❌ Failed", text_color="#ef4444", fg_color="#3b0f15"),
                    u["p_bar"].configure(progress_color="#ef4444")
                ))

        # Run multi-shorts rendering
        is_parallel = parallel_render_var.get()
        if is_parallel and len(valid_items) > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(3, len(valid_items))) as executor:
                futures = [executor.submit(_render_single_short_worker, idx, item) for idx, item in enumerate(valid_items)]
                concurrent.futures.wait(futures)
        else:
            for idx, item in enumerate(valid_items):
                _render_single_short_worker(idx, item)

        # 6. YOUTUBE SHORTS DIRECT UPLOAD FLOW
        _update_step(6, 100, f"✅ Step 6/6: All {len(rendered_shorts_files)} Shorts Finished!", 1.0)
        btn_start_3d.configure(state="normal", text="🚀  START SHORTS GENERATION & BATCH RENDER")

        if tasks_for_direct_upload:
            _log_console(f"🚀 Queued {len(tasks_for_direct_upload)} Short video(s) for YouTube Direct Upload!")

            def _start_upload_mode(mode: str):
                _log_console(f"Starting Shorts YouTube Direct Upload in [{mode.upper()}] mode...")
                from uploader_engine.auth import get_authenticated_youtube_service
                from uploader_engine.uploader import perform_video_upload

                def _upload_worker(task):
                    t_lbl = task.get("variation_label", "Short")
                    cid = task.get("channel_id")
                    _log_console(f"⚡ Uploading {t_lbl} to YouTube channel: {task.get('channel_name')}...")
                    try:
                        yt = get_authenticated_youtube_service(cid)
                        vid_id = perform_video_upload(yt, task)
                        w_url = f"https://youtu.be/{vid_id}"
                        _log_console(f"🎉 ✅ {t_lbl} Upload Successful! Live at: {w_url}")
                    except Exception as u_ex:
                        _log_console(f"❌ {t_lbl} upload error: {u_ex}")

                if mode == "parallel":
                    for t in tasks_for_direct_upload:
                        threading.Thread(target=lambda task_obj=t: _upload_worker(task_obj), daemon=True).start()
                else:
                    def _seq():
                        for t in tasks_for_direct_upload:
                            _upload_worker(t)
                    threading.Thread(target=_seq, daemon=True).start()

            # Show Added to Queue dialog
            top = container.winfo_toplevel()
            try:
                if QueueAddedDialog:
                    QueueAddedDialog(
                        top,
                        tasks_for_direct_upload,
                        on_start_callback=_start_upload_mode,
                        on_cancel_callback=lambda: _log_console("Upload cancelled by user.")
                    )
                else:
                    _start_upload_mode("sequential")
            except Exception as ex:
                _start_upload_mode("sequential")
        else:
            messagebox.showinfo(
                "Shorts Render Complete",
                f"🎉 Successfully rendered {len(rendered_shorts_files)} 9:16 Short videos!\n\nFolder:\n{out_folder}"
            )

    return container
