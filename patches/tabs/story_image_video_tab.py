import os
import re
import sys
import ssl
import json
import time
import glob
import queue
import shutil
import platform
import tempfile
import urllib.request
import traceback
import threading
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

import customtkinter as ctk
from tkinter import filedialog, messagebox

import lazy_menu  # Win32 / TCL native menu limit fix
import preset_manager

_SSL_CONTEXT: Optional[ssl.SSLContext] = None

def _get_ssl_context() -> ssl.SSLContext:
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            _SSL_CONTEXT = ctx
        except Exception:
            _SSL_CONTEXT = ssl._create_unverified_context()
    return _SSL_CONTEXT

# Modular Tab Metadata for plugin_loader.py
TAB_TITLE = "🎬  Story Image Video"
TAB_ORDER = 18
TAB_COLOR = "#8B5CF6"
TAB_GROUP = ""
LAZY_LOAD = True

# Pro 3D Dark Studio Design Tokens
C_BG = "#080C14"           # Deep space studio background
C_PANEL = "#101623"        # Translucent dark navy glass surface
C_CARD = "#151D2F"         # Inner 3D card container
C_CARD_HEADER = "#1E283F"  # 3D Card Header bevel
C_BORDER = "#283652"       # Metallic glass stroke border
C_BORDER_GLOW = "#3B82F6"  # Active cyan/blue glow border
C_PURPLE = "#8B5CF6"       # Electric Purple accent
C_PURPLE_HOVER = "#7C3AED" # Hover Electric Purple
C_CYAN = "#06B6D4"         # Secondary Cyan accent
C_GREEN = "#10B981"        # Emerald success accent
C_AMBER = "#F59E0B"        # Amber warning accent
C_RED = "#EF4444"          # Destructive action accent
C_TEXT = "#F9FAFB"         # Crisp white text
C_MUTED = "#9CA3AF"        # Muted gray text

def create(parent_frame: ctk.CTkFrame, boot_data: Optional[Dict[str, Any]] = None):
    """Factory function called by plugin_loader.py to instantiate Story Image Video tab."""
    frame = StoryImageVideoTab(parent_frame, boot_data=boot_data)
    frame.grid(row=0, column=0, sticky="nsew")
    return frame


class StoryImageVideoTab(ctk.CTkFrame):
    """Plugin GUI Tab for Story Image Video Creation - CapCut / DaVinci Grade 3D Workstation."""

    def __init__(self, parent: ctk.CTkFrame, boot_data: Optional[Dict[str, Any]] = None):
        super().__init__(parent, fg_color=C_BG)
        self.boot_data = boot_data or {}
        
        appdata = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or os.path.expanduser("~")
        self.settings_dir = os.path.join(appdata, "StoriesStudio", "StoryImageVideo")
        os.makedirs(self.settings_dir, exist_ok=True)
        self.settings_path = os.path.join(self.settings_dir, "story_image_video_settings.json")
        self.log_path = os.path.join(self.settings_dir, "story_image_video_activity.log")
        self.preview_cache_dir = os.path.join(self.settings_dir, ".preview_cache")
        os.makedirs(self.preview_cache_dir, exist_ok=True)

        self.ui_queue = queue.Queue()
        self.running = False
        self.preview_process = None
        self.show_api_key = False

        self.models: List[Dict[str, Any]] = []
        self.voices: List[Dict[str, Any]] = []
        self.model_map: Dict[str, str] = {}
        self.voice_map: Dict[str, str] = {}
        
        self.parsed_scenes: List[Dict[str, Any]] = []
        self.bulk_images: List[str] = []
        self.scene_image_map: Dict[int, str] = {}
        self.uploaded_logos: List[str] = []
        
        self.project_queue: List[Dict[str, Any]] = []
        self.custom_logo_x: Optional[int] = None
        self.custom_logo_y: Optional[int] = None
        self.custom_caption_x: Optional[int] = None
        self.custom_caption_y: Optional[int] = None

        self._build_ui()
        self._load_env()
        self._auto_load_voices_on_init()
        self._drain_ui_queue()

    def _build_ui(self):
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # ---------------------------------------------------------------------
        # 1. TOP 3D STUDIO HEADER BAR
        # ---------------------------------------------------------------------
        top_bar = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=10, border_width=1, border_color=C_BORDER)
        top_bar.grid(row=0, column=0, padx=10, pady=(8, 2), sticky="ew")

        hdr_left = ctk.CTkFrame(top_bar, fg_color="transparent")
        hdr_left.pack(side="left", padx=10, pady=6)

        title_box = ctk.CTkFrame(hdr_left, fg_color="transparent")
        title_box.pack(anchor="w")
        ctk.CTkLabel(title_box, text="🎬 Story Image Video Studio", font=ctk.CTkFont(size=16, weight="bold"), text_color=C_TEXT).pack(side="left")
        ctk.CTkLabel(title_box, text=" PRO STUDIO v3.0 ", font=ctk.CTkFont(size=9, weight="bold"), fg_color=C_PURPLE, text_color=C_TEXT, corner_radius=5).pack(side="left", padx=6)

        ctk.CTkLabel(hdr_left, text="CapCut/DaVinci Grade Production Workstation • Storyboard • FX • Batch Export", font=ctk.CTkFont(size=10), text_color=C_MUTED).pack(anchor="w", pady=(1, 0))

        hdr_right = ctk.CTkFrame(top_bar, fg_color="transparent")
        hdr_right.pack(side="right", padx=10, pady=6)

        self.gpu_badge = ctk.CTkLabel(
            hdr_right,
            text="⚡ GPU: Detecting…",
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#1E283F",
            text_color=C_CYAN,
            corner_radius=6,
            padx=10,
            pady=4
        )
        self.gpu_badge.pack(side="left", padx=4)

        self.env_status = ctk.CTkLabel(hdr_right, text="Checking environment…", font=ctk.CTkFont(size=10), text_color=C_MUTED)
        self.env_status.pack(side="left", padx=6)

        self.top_export_btn = ctk.CTkButton(
            hdr_right, text="⚡ EXPORT VIDEO NOW", font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=C_PURPLE, hover_color=C_PURPLE_HOVER, width=140, height=32, corner_radius=7,
            command=self.run_project
        )
        self.top_export_btn.pack(side="left", padx=(6, 0))

        # ---------------------------------------------------------------------
        # 2. 1-CLICK SMART PRESET PROFILES BAR
        # ---------------------------------------------------------------------
        preset_bar = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=8, border_width=1, border_color=C_BORDER)
        preset_bar.grid(row=1, column=0, padx=10, pady=2, sticky="ew")

        preset_wrap = ctk.CTkFrame(preset_bar, fg_color="transparent")
        preset_wrap.pack(fill="x", padx=6, pady=3)

        ctk.CTkLabel(preset_wrap, text="⚡ Smart Presets:", font=ctk.CTkFont(size=10, weight="bold"), text_color=C_MUTED).pack(side="left", padx=(4, 8))

        p_shorts = ctk.CTkButton(preset_wrap, text="🔥 Viral YouTube Shorts (9:16)", font=ctk.CTkFont(size=10, weight="bold"), height=24, fg_color="#8B5CF6", hover_color="#7C3AED", command=self._apply_preset_shorts)
        p_shorts.pack(side="left", padx=2)

        p_long = ctk.CTkButton(preset_wrap, text="🎬 YouTube Longform (16:9 1080p)", font=ctk.CTkFont(size=10, weight="bold"), height=24, fg_color="#2563EB", hover_color="#1D4ED8", command=self._apply_preset_longform)
        p_long.pack(side="left", padx=2)

        p_fast = ctk.CTkButton(preset_wrap, text="⚡ Ultra Speed Draft (720p Static)", font=ctk.CTkFont(size=10, weight="bold"), height=24, fg_color="#10B981", hover_color="#059669", command=self._apply_preset_fast)
        p_fast.pack(side="left", padx=2)

        p_4k = ctk.CTkButton(preset_wrap, text="💎 4K Cinema Master", font=ctk.CTkFont(size=10, weight="bold"), height=24, fg_color="#F59E0B", hover_color="#D97706", command=self._apply_preset_4k)
        p_4k.pack(side="left", padx=2)

        self.preset_widget = preset_manager.PresetWidget(
            preset_wrap,
            tool_id="story_image_video",
            collect_fn=self._collect_settings,
            apply_fn=self._apply_settings,
            status_cb=lambda msg, col: self.log(f"[preset] {msg}")
        )
        self.preset_widget.pack(side="right", padx=(10, 4))

        # ---------------------------------------------------------------------
        # 3. PRO STUDIO WORKSPACE TABS (3 DEDICATED WORKSTATIONS)
        # ---------------------------------------------------------------------
        self.studio_tabs = ctk.CTkTabview(
            self, fg_color=C_BG, segmented_button_fg_color=C_PANEL,
            segmented_button_selected_color=C_PURPLE, segmented_button_selected_hover_color=C_PURPLE_HOVER,
            corner_radius=8
        )
        self.studio_tabs.grid(row=2, column=0, padx=8, pady=2, sticky="nsew")

        tab_story = self.studio_tabs.add("🎬 1. Storyboard & Voice Production")
        tab_fx = self.studio_tabs.add("🎨 2. Styling, Subtitles & FX")
        tab_export = self.studio_tabs.add("🚀 3. Export & Batch Queue Manager")

        # Configure tab grids with deterministic column weights (eliminates flickering & hanging)
        for t in (tab_story, tab_fx, tab_export):
            t.grid_rowconfigure(0, weight=1)
            t.grid_columnconfigure(0, weight=0)
            t.grid_columnconfigure(1, weight=1)

        # =====================================================================
        # TAB 1: 🎬 STORYBOARD & VOICE PRODUCTION WORKSTATION
        # =====================================================================
        story_left = ctk.CTkScrollableFrame(tab_story, fg_color="transparent", width=440)
        story_left.grid(row=0, column=0, padx=(2, 4), pady=2, sticky="nsew")

        story_right = ctk.CTkScrollableFrame(tab_story, fg_color="transparent")
        story_right.grid(row=0, column=1, padx=(2, 4), pady=2, sticky="nsew")

        # CARD 1: Script Input & Parser
        c1 = ctk.CTkFrame(story_left, fg_color=C_CARD, corner_radius=8, border_width=1, border_color=C_BORDER)
        c1.pack(fill="x", pady=4, padx=2)
        c1.grid_columnconfigure(1, weight=1)

        c1_hdr = ctk.CTkFrame(c1, fg_color=C_CARD_HEADER, corner_radius=6, height=28)
        c1_hdr.grid(row=0, column=0, columnspan=3, sticky="ew", padx=2, pady=2)
        ctk.CTkLabel(c1_hdr, text="  📜 1. Script Input & Scene Parsing", font=ctk.CTkFont(size=11, weight="bold"), text_color=C_TEXT).pack(side="left", padx=6)

        self.script_box = ctk.CTkTextbox(c1, height=130, font=ctk.CTkFont(family="Consolas", size=10), fg_color=C_BG, border_color=C_BORDER, border_width=1)
        self.script_box.grid(row=1, column=0, columnspan=3, padx=6, pady=4, sticky="ew")
        self.script_box.insert("1.0", "Scene_1_There is a particular kind of cruelty that wears silk and smiles at dinner parties. It does not strike with fists. It does not raise its voice. It simply arranges the world so that one person is always standing in the cold.\n\nScene_2_Lady Constance Ashford had perfected this art. She had married Sir Harold Ashford when his first wife was barely six months in the ground.")

        c1_btn_bar = ctk.CTkFrame(c1, fg_color="transparent")
        c1_btn_bar.grid(row=2, column=0, columnspan=3, padx=6, pady=2, sticky="ew")

        ctk.CTkButton(c1_btn_bar, text="⚡ Parse Scenes", font=ctk.CTkFont(size=10, weight="bold"), height=26, fg_color=C_PURPLE, hover_color=C_PURPLE_HOVER, command=self.parse_script_blocks).pack(side="left", padx=(0, 4))
        ctk.CTkButton(c1_btn_bar, text="🖼️ Bulk Select Images", font=ctk.CTkFont(size=10, weight="bold"), height=26, fg_color=C_CYAN, hover_color="#0891B2", command=self._choose_bulk_images).pack(side="left", padx=(0, 4))
        
        self.parse_badge = ctk.CTkLabel(c1_btn_bar, text="0 Scenes Parsed", font=ctk.CTkFont(size=10, weight="bold"), text_color=C_MUTED)
        self.parse_badge.pack(side="left", padx=4)

        # CARD 2: Voice Studio & API Engine
        c2 = ctk.CTkFrame(story_left, fg_color=C_CARD, corner_radius=8, border_width=1, border_color=C_BORDER)
        c2.pack(fill="x", pady=4, padx=2)
        c2.grid_columnconfigure(1, weight=1)

        c2_hdr = ctk.CTkFrame(c2, fg_color=C_CARD_HEADER, corner_radius=6, height=28)
        c2_hdr.grid(row=0, column=0, columnspan=3, sticky="ew", padx=2, pady=2)
        ctk.CTkLabel(c2_hdr, text="  🎙️ 2. Voice Studio & TTS Engine", font=ctk.CTkFont(size=11, weight="bold"), text_color=C_TEXT).pack(side="left", padx=6)

        ctk.CTkLabel(c2, text="API Key").grid(row=1, column=0, padx=6, pady=2, sticky="w")
        api_wrap = ctk.CTkFrame(c2, fg_color="transparent")
        api_wrap.grid(row=1, column=1, columnspan=2, padx=(2, 6), pady=2, sticky="ew")
        api_wrap.grid_columnconfigure(0, weight=1)

        self.api_key = ctk.CTkEntry(api_wrap, placeholder_text="sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt", show="*", height=26, fg_color=C_BG, border_color=C_BORDER)
        self.api_key.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        self.api_key.insert(0, "sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt")

        self.show_key_btn = ctk.CTkButton(api_wrap, text="👁", width=28, height=26, fg_color=C_CARD_HEADER, command=self._toggle_key_visibility)
        self.show_key_btn.grid(row=0, column=1, padx=(0, 4))
        ctk.CTkButton(api_wrap, text="Fetch Voices", width=80, height=26, fg_color=C_CYAN, hover_color="#0891B2", command=self._fetch_voices_threaded).grid(row=0, column=2)

        ctk.CTkLabel(c2, text="Voice Provider").grid(row=2, column=0, padx=6, pady=2, sticky="w")
        self.model_menu = ctk.CTkComboBox(c2, values=["All Providers", "ElevenLabs", "Minimax", "FishAudio", "Edge Neural", "Kokoro", "Vbee", "Cloned Voices"], height=26, state="readonly", command=lambda v: self._provider_changed(v), fg_color=C_BG, border_color=C_BORDER)
        self.model_menu.grid(row=2, column=1, columnspan=2, padx=(2, 6), pady=2, sticky="ew")
        self.model_menu.set("All Providers")

        ctk.CTkLabel(c2, text="Sub-Model").grid(row=3, column=0, padx=6, pady=2, sticky="w")
        self.submodel_menu = ctk.CTkComboBox(c2, values=["All Models / Sub-Models"], height=26, state="readonly", command=lambda v: self._filter_voices(), fg_color=C_BG, border_color=C_BORDER)
        self.submodel_menu.grid(row=3, column=1, columnspan=2, padx=(2, 6), pady=2, sticky="ew")

        ctk.CTkLabel(c2, text="Search Voices").grid(row=4, column=0, padx=6, pady=2, sticky="w")
        search_wrap = ctk.CTkFrame(c2, fg_color="transparent")
        search_wrap.grid(row=4, column=1, columnspan=2, padx=(2, 6), pady=2, sticky="ew")
        search_wrap.grid_columnconfigure(0, weight=1)

        self.voice_search = ctk.CTkEntry(search_wrap, placeholder_text="Type voice name or ID...", height=26, fg_color=C_BG, border_color=C_BORDER)
        self.voice_search.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        self.voice_search.bind("<KeyRelease>", lambda e: self._filter_voices())

        ctk.CTkButton(search_wrap, text="Refresh", width=55, height=26, fg_color=C_CARD_HEADER, command=self._fetch_voices_threaded).grid(row=0, column=1, padx=(0, 2))
        ctk.CTkButton(search_wrap, text="Clear", width=45, height=26, fg_color="transparent", border_width=1, border_color=C_BORDER, command=self._clear_voice_search).grid(row=0, column=2)

        # Scrollable Voice Browser List with Inline Play Buttons
        ctk.CTkLabel(c2, text="Voice Library").grid(row=5, column=0, padx=6, pady=2, sticky="nw")
        self.voice_list_scroll = ctk.CTkScrollableFrame(c2, height=180, fg_color=C_BG, border_width=1, border_color=C_BORDER)
        self.voice_list_scroll.grid(row=5, column=1, columnspan=2, padx=(2, 6), pady=2, sticky="ew")

        ctk.CTkLabel(c2, text="Selected Voice").grid(row=6, column=0, padx=6, pady=2, sticky="w")
        vid_wrap = ctk.CTkFrame(c2, fg_color="transparent")
        vid_wrap.grid(row=6, column=1, columnspan=2, padx=(2, 6), pady=2, sticky="ew")
        vid_wrap.grid_columnconfigure(0, weight=1)

        self.voice_id = ctk.CTkEntry(vid_wrap, placeholder_text="Auto-filled or paste Voice ID", height=26, fg_color=C_BG, border_color=C_BORDER)
        self.voice_id.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.test_voice_btn = ctk.CTkButton(
            vid_wrap, text="▶ Test Voice", width=90, height=26,
            fg_color=C_PURPLE, hover_color="#7C3AED", font=ctk.CTkFont(size=10, weight="bold"),
            command=self.play_voice_preview
        )
        self.test_voice_btn.grid(row=0, column=1)

        ctk.CTkLabel(c2, text="Voice Speed").grid(row=7, column=0, padx=6, pady=2, sticky="w")
        self.tts_speed_slider = ctk.CTkSlider(c2, from_=0.8, to=1.5, number_of_steps=14, height=14, command=lambda v: self.tts_speed_label.configure(text=f"{float(v):.2f}x"))
        self.tts_speed_slider.grid(row=7, column=1, padx=4, pady=2, sticky="ew")
        self.tts_speed_slider.set(1.0)
        self.tts_speed_label = ctk.CTkLabel(c2, text="1.00x", width=65, text_color=C_CYAN, font=ctk.CTkFont(size=10))
        self.tts_speed_label.grid(row=7, column=2, padx=6)

        ctk.CTkLabel(c2, text="Parallel TTS Workers").grid(row=8, column=0, padx=6, pady=2, sticky="w")
        self.parallel_tts = ctk.CTkSlider(c2, from_=1, to=10, number_of_steps=9, height=14, command=lambda v: self.parallel_tts_label.configure(text=f"{int(v)} workers"))
        self.parallel_tts.grid(row=8, column=1, padx=4, pady=2, sticky="ew")
        self.parallel_tts.set(6)
        self.parallel_tts_label = ctk.CTkLabel(c2, text="6 workers", width=65, text_color=C_CYAN, font=ctk.CTkFont(size=10))
        self.parallel_tts_label.grid(row=8, column=2, padx=6)

        self.api_status = ctk.CTkLabel(c2, text="AI33 Ready", font=ctk.CTkFont(size=10), text_color=C_MUTED)
        self.api_status.grid(row=9, column=1, columnspan=2, padx=4, pady=(1, 4), sticky="w")

        # RIGHT COLUMN: Interactive Visual Storyboard Grid
        sb_card = ctk.CTkFrame(story_right, fg_color=C_CARD, corner_radius=8, border_width=1, border_color=C_BORDER)
        sb_card.pack(fill="both", expand=True, pady=4, padx=2)
        sb_card.grid_columnconfigure(0, weight=1)

        sb_hdr = ctk.CTkFrame(sb_card, fg_color=C_CARD_HEADER, corner_radius=6, height=28)
        sb_hdr.pack(fill="x", padx=2, pady=2)
        ctk.CTkLabel(sb_hdr, text="  🖼️ Visual Storyboard & Scene Inspector", font=ctk.CTkFont(size=11, weight="bold"), text_color=C_TEXT).pack(side="left", padx=6)

        self.scene_tree = ctk.CTkScrollableFrame(sb_card, height=350, fg_color=C_BG, border_width=1, border_color=C_BORDER)
        self.scene_tree.pack(fill="both", expand=True, padx=6, pady=6)
        ctk.CTkLabel(self.scene_tree, text="Paste script and click '⚡ Parse Scenes' to load storyboard inspector.", font=ctk.CTkFont(size=10), text_color=C_MUTED).pack(pady=40)

        # =====================================================================
        # TAB 2: 🎨 STYLING, SUBTITLES & FX WORKSTATION
        # =====================================================================
        fx_left = ctk.CTkScrollableFrame(tab_fx, fg_color="transparent", width=440)
        fx_left.grid(row=0, column=0, padx=(2, 4), pady=2, sticky="nsew")

        fx_right = ctk.CTkScrollableFrame(tab_fx, fg_color="transparent")
        fx_right.grid(row=0, column=1, padx=(2, 4), pady=2, sticky="nsew")

        # Subtitles Card
        c5 = ctk.CTkFrame(fx_left, fg_color=C_CARD, corner_radius=8, border_width=1, border_color=C_BORDER)
        c5.pack(fill="x", pady=4, padx=2)
        c5.grid_columnconfigure(1, weight=1)

        c5_hdr = ctk.CTkFrame(c5, fg_color=C_CARD_HEADER, corner_radius=6, height=28)
        c5_hdr.grid(row=0, column=0, columnspan=3, sticky="ew", padx=2, pady=2)
        ctk.CTkLabel(c5_hdr, text="  ✨ Subtitles & CapCut Styling", font=ctk.CTkFont(size=11, weight="bold"), text_color=C_TEXT).pack(side="left", padx=6)

        self.enable_captions = ctk.CTkCheckBox(c5, text="Enable CapCut Word Subtitles", text_color=C_TEXT)
        self.enable_captions.grid(row=1, column=0, padx=6, pady=3, sticky="w")
        self.enable_captions.select()

        ctk.CTkLabel(c5, text="Preset Style").grid(row=2, column=0, padx=6, pady=3, sticky="w")
        self.caption_preset = ctk.CTkComboBox(
            c5, height=26,
            values=["CapCut Yellow Pop", "Classic White & Black Box", "Neon Cyan Glow", "Karaoke Word Highlight", "Minimal White Shadow", "Gold Luxury Bold"],
            state="readonly", fg_color=C_BG, border_color=C_BORDER
        )
        self.caption_preset.grid(row=2, column=1, columnspan=2, padx=(2, 6), pady=3, sticky="ew")
        self.caption_preset.set("CapCut Yellow Pop")

        ctk.CTkLabel(c5, text="Font Family").grid(row=3, column=0, padx=6, pady=3, sticky="w")
        self.caption_font = ctk.CTkComboBox(c5, height=26, values=["Impact", "Montserrat", "Arial Black", "Komika Axis", "TheBoldFont", "Bebas Neue", "Roboto", "Outfit"], state="readonly", fg_color=C_BG, border_color=C_BORDER)
        self.caption_font.grid(row=3, column=1, columnspan=2, padx=(2, 6), pady=3, sticky="ew")
        self.caption_font.set("Impact")

        self.custom_font_entry = self._file_row(c5, 4, "Custom Font (.ttf)", self._choose_custom_font, "Optional custom font file (.ttf / .otf)")

        ctk.CTkLabel(c5, text="Text Casing").grid(row=5, column=0, padx=6, pady=3, sticky="w")
        self.caption_case = ctk.CTkComboBox(c5, height=26, values=["ALL CAPS (Recommended)", "Normal Case", "Title Case"], state="readonly", fg_color=C_BG, border_color=C_BORDER)
        self.caption_case.grid(row=5, column=1, columnspan=2, padx=(2, 6), pady=3, sticky="ew")
        self.caption_case.set("ALL CAPS (Recommended)")

        ctk.CTkLabel(c5, text="Words Per Line").grid(row=6, column=0, padx=6, pady=3, sticky="w")
        self.caption_words_per_line = ctk.CTkComboBox(c5, height=26, values=["1 Word (CapCut Pop)", "2 Words", "3 Words", "4 Words", "5 Words", "6 Words", "8 Words", "Auto (10 Words)"], state="readonly", fg_color=C_BG, border_color=C_BORDER)
        self.caption_words_per_line.grid(row=6, column=1, columnspan=2, padx=(2, 6), pady=3, sticky="ew")
        self.caption_words_per_line.set("4 Words")

        ctk.CTkLabel(c5, text="Number of Lines").grid(row=7, column=0, padx=6, pady=3, sticky="w")
        self.caption_lines = ctk.CTkComboBox(c5, height=26, values=["1 Line (Standard)", "2 Lines", "3 Lines"], state="readonly", fg_color=C_BG, border_color=C_BORDER)
        self.caption_lines.grid(row=7, column=1, columnspan=2, padx=(2, 6), pady=3, sticky="ew")
        self.caption_lines.set("1 Line (Standard)")

        ctk.CTkLabel(c5, text="Subtitle Position").grid(row=8, column=0, padx=6, pady=3, sticky="w")
        self.caption_position = ctk.CTkComboBox(c5, height=26, values=["Bottom-Center", "Middle-Center", "Top-Center", "Custom (Canvas Drag)"], state="readonly", fg_color=C_BG, border_color=C_BORDER)
        self.caption_position.grid(row=8, column=1, columnspan=2, padx=(2, 6), pady=3, sticky="ew")
        self.caption_position.set("Bottom-Center")

        ctk.CTkLabel(c5, text="Font Size").grid(row=9, column=0, padx=6, pady=3, sticky="w")
        self.caption_size = ctk.CTkSlider(c5, from_=16, to=72, number_of_steps=56, height=14, command=lambda v: self.caption_size_label.configure(text=f"{int(v)}pt"))
        self.caption_size.grid(row=9, column=1, padx=4, pady=3, sticky="ew")
        self.caption_size.set(28)
        self.caption_size_label = ctk.CTkLabel(c5, text="28pt", width=55, text_color=C_CYAN, font=ctk.CTkFont(size=10))
        self.caption_size_label.grid(row=9, column=2, padx=6)

        sub_btn_wrap = ctk.CTkFrame(c5, fg_color="transparent")
        sub_btn_wrap.grid(row=10, column=0, columnspan=3, padx=4, pady=(4, 6), sticky="ew")
        ctk.CTkButton(sub_btn_wrap, text="✨ Live Subtitle Preview", height=26, fg_color="#EC4899", hover_color="#DB2777", command=self.play_logo_caption_preview).pack(side="left", padx=(0, 6))
        ctk.CTkButton(sub_btn_wrap, text="🔥 Burn Standalone ASS", height=26, fg_color="#8B5CF6", hover_color=C_PURPLE_HOVER, command=self.burn_subtitles_standalone).pack(side="left")

        # Cinematic Camera Motion & Dynamic Overlays Card
        c6 = ctk.CTkFrame(fx_right, fg_color=C_CARD, corner_radius=8, border_width=1, border_color=C_BORDER)
        c6.pack(fill="x", pady=4, padx=2)
        c6.grid_columnconfigure(1, weight=1)

        c6_hdr = ctk.CTkFrame(c6, fg_color=C_CARD_HEADER, corner_radius=6, height=28)
        c6_hdr.grid(row=0, column=0, columnspan=3, sticky="ew", padx=2, pady=2)
        ctk.CTkLabel(c6_hdr, text="  🎬 Cinematic Camera Motion & Overlays", font=ctk.CTkFont(size=11, weight="bold"), text_color=C_TEXT).pack(side="left", padx=6)

        # 1. Camera Motion Style (5-6 Slow Organic Styles + Auto-Director)
        ctk.CTkLabel(c6, text="Camera Motion Style").grid(row=1, column=0, padx=6, pady=3, sticky="w")
        self.camera_motion = ctk.CTkComboBox(
            c6, height=26,
            values=[
                "🌟 Auto-Director Flow (Dynamic Scenes)",
                "🎬 Slow Push-In (Depth Focus)",
                "🌊 3D Parallax & Gentle Float",
                "↔️ Smooth Pan (Left to Right)",
                "📐 Subtle Diagonal Drift",
                "📽️ Gentle Crane & Tilt Up",
                "🌬️ Living Breathing Camera",
                "⏹️ Static (No Motion)"
            ],
            state="readonly", fg_color=C_BG, border_color=C_BORDER
        )
        self.camera_motion.grid(row=1, column=1, columnspan=2, padx=(2, 6), pady=3, sticky="ew")
        self.camera_motion.set("🌟 Auto-Director Flow (Dynamic Scenes)")
        # Legacy alias for backward compatibility
        self.motion_effect = self.camera_motion

        # 2. Audio Visualizer (GIF / Behind Captions)
        self.enable_visualizer = ctk.CTkCheckBox(c6, text="Audio Visualizer (Behind Captions)", text_color=C_TEXT)
        self.enable_visualizer.grid(row=2, column=0, columnspan=3, padx=6, pady=(5, 2), sticky="w")
        self.enable_visualizer.select()

        self.visualizer_entry = self._file_row(c6, 3, "Visualizer GIF / File", self._choose_visualizer, "Looping soundwave GIF (Downloads/soundwave...)")
        def_vis = r"C:\Users\Administrator\Downloads\mxj_files-soundwave-23743.gif"
        if os.path.exists(def_vis):
            self.visualizer_entry.insert(0, def_vis)

        ctk.CTkLabel(c6, text="Visualizer Opacity").grid(row=4, column=0, padx=6, pady=2, sticky="w")
        self.vis_opacity_slider = ctk.CTkSlider(c6, from_=20, to=100, number_of_steps=16, height=14, command=lambda v: self.vis_opacity_label.configure(text=f"{int(v)}%"))
        self.vis_opacity_slider.grid(row=4, column=1, padx=4, pady=2, sticky="ew")
        self.vis_opacity_slider.set(85)
        self.vis_opacity_label = ctk.CTkLabel(c6, text="85%", width=55, text_color=C_CYAN, font=ctk.CTkFont(size=10))
        self.vis_opacity_label.grid(row=4, column=2, padx=6)

        # 3. Subscribe Button Overlay (Bottom-Left Corner periodic loop)
        self.enable_subscribe = ctk.CTkCheckBox(c6, text="Subscribe Button (Bottom-Left Loop)", text_color=C_TEXT)
        self.enable_subscribe.grid(row=5, column=0, columnspan=3, padx=6, pady=(5, 2), sticky="w")
        self.enable_subscribe.select()

        self.subscribe_entry = self._file_row(c6, 6, "Subscribe GIF / File", self._choose_subscribe, "Subscribe animation GIF (Downloads/subscribe...)")
        def_sub = r"C:\Users\Administrator\Downloads\funkikids-subscribe-16146_512.gif"
        if os.path.exists(def_sub):
            self.subscribe_entry.insert(0, def_sub)

        # Subscribe Gap & Width controls
        sub_ctrl_wrap = ctk.CTkFrame(c6, fg_color="transparent")
        sub_ctrl_wrap.grid(row=7, column=0, columnspan=3, padx=6, pady=2, sticky="ew")
        ctk.CTkLabel(sub_ctrl_wrap, text="Loop Gap:").pack(side="left", padx=(0, 4))
        self.subscribe_gap_menu = ctk.CTkComboBox(sub_ctrl_wrap, width=105, height=24, values=["20s Gap", "30s Gap", "35s Gap", "45s Gap", "60s Gap"], state="readonly", fg_color=C_BG, border_color=C_BORDER)
        self.subscribe_gap_menu.pack(side="left", padx=(0, 12))
        self.subscribe_gap_menu.set("35s Gap")

        ctk.CTkLabel(sub_ctrl_wrap, text="Size:").pack(side="left", padx=(0, 4))
        self.subscribe_width_menu = ctk.CTkComboBox(sub_ctrl_wrap, width=95, height=24, values=["180px", "220px", "260px", "300px"], state="readonly", fg_color=C_BG, border_color=C_BORDER)
        self.subscribe_width_menu.pack(side="left")
        self.subscribe_width_menu.set("220px")

        # 4. Background Videos & Intros
        self.bg_video_entry = self._file_row(c6, 8, "Background Videos", self._choose_bg_videos, "Optional video backgrounds (.mp4)")

        ctk.CTkLabel(c6, text="BG Video Opacity").grid(row=9, column=0, padx=6, pady=3, sticky="w")
        self.bg_opacity_slider = ctk.CTkSlider(c6, from_=10, to=100, number_of_steps=18, height=14, command=lambda v: self.bg_opacity_label.configure(text=f"{int(v)}%"))
        self.bg_opacity_slider.grid(row=9, column=1, padx=4, pady=3, sticky="ew")
        self.bg_opacity_slider.set(60)
        self.bg_opacity_label = ctk.CTkLabel(c6, text="60%", width=55, text_color=C_CYAN, font=ctk.CTkFont(size=10))
        self.bg_opacity_label.grid(row=9, column=2, padx=6)

        self.intro_entry = self._file_row(c6, 10, "Intro / Outro Videos", self._choose_intros, "Optional intro/outro videos (.mp4)")

        # Watermark & Branding Card
        c4 = ctk.CTkFrame(fx_right, fg_color=C_CARD, corner_radius=8, border_width=1, border_color=C_BORDER)
        c4.pack(fill="x", pady=4, padx=2)
        c4.grid_columnconfigure(1, weight=1)

        c4_hdr = ctk.CTkFrame(c4, fg_color=C_CARD_HEADER, corner_radius=6, height=28)
        c4_hdr.grid(row=0, column=0, columnspan=3, sticky="ew", padx=2, pady=2)
        ctk.CTkLabel(c4_hdr, text="  📷 Watermark & Branding Options", font=ctk.CTkFont(size=11, weight="bold"), text_color=C_TEXT).pack(side="left", padx=6)

        self.enable_logo = ctk.CTkCheckBox(c4, text="Enable Logo Watermark", text_color=C_TEXT)
        self.enable_logo.grid(row=1, column=0, padx=6, pady=3, sticky="w")
        self.enable_logo.select()

        self.logo_entry = self._file_row(c4, 2, "Watermark Image", self._choose_logo, "Logo file path (.png / .jpg)")

        ctk.CTkLabel(c4, text="Logo Position").grid(row=3, column=0, padx=6, pady=3, sticky="w")
        self.logo_position = ctk.CTkComboBox(c4, height=26, values=["Top-Right", "Top-Left", "Bottom-Right", "Bottom-Left", "Center", "Custom (Drag & Drop)"], state="readonly", fg_color=C_BG, border_color=C_BORDER)
        self.logo_position.grid(row=3, column=1, padx=4, pady=3, sticky="ew")
        self.logo_position.set("Top-Right")

        ctk.CTkButton(c4, text="📐 Canvas Editor", width=110, height=26, fg_color=C_AMBER, hover_color="#D97706", command=self.open_logo_canvas_editor).grid(row=3, column=2, padx=(2, 6), pady=3, sticky="e")

        ctk.CTkLabel(c4, text="Logo Width").grid(row=4, column=0, padx=6, pady=3, sticky="w")
        self.logo_width_slider = ctk.CTkSlider(c4, from_=40, to=600, number_of_steps=56, height=14, command=lambda v: self.logo_width_label.configure(text=f"{int(v)}px"))
        self.logo_width_slider.grid(row=4, column=1, padx=4, pady=(3, 6), sticky="ew")
        self.logo_width_slider.set(200)
        self.logo_width_label = ctk.CTkLabel(c4, text="200px", width=55, text_color=C_CYAN, font=ctk.CTkFont(size=10))
        self.logo_width_label.grid(row=4, column=2, padx=6)

        logo_btn_wrap = ctk.CTkFrame(c4, fg_color="transparent")
        logo_btn_wrap.grid(row=5, column=0, columnspan=3, padx=6, pady=(4, 6), sticky="ew")
        ctk.CTkButton(logo_btn_wrap, text="✨ Live Logo & Subtitle Preview", height=26, fg_color="#8B5CF6", hover_color=C_PURPLE_HOVER, command=self.play_logo_caption_preview).pack(side="left", padx=(0, 6))

        # Audio Mixing Card
        c7 = ctk.CTkFrame(fx_left, fg_color=C_CARD, corner_radius=8, border_width=1, border_color=C_BORDER)
        c7.pack(fill="x", pady=4, padx=2)
        c7.grid_columnconfigure(1, weight=1)

        c7_hdr = ctk.CTkFrame(c7, fg_color=C_CARD_HEADER, corner_radius=6, height=28)
        c7_hdr.grid(row=0, column=0, columnspan=3, sticky="ew", padx=2, pady=2)
        ctk.CTkLabel(c7_hdr, text="  🎵 Audio Mixing & Background Music (BGM)", font=ctk.CTkFont(size=11, weight="bold"), text_color=C_TEXT).pack(side="left", padx=6)

        self.bgm_entry = self._file_row(c7, 1, "Background Music (BGM)", lambda: self._set_path(self.bgm_entry, filedialog.askopenfilename(filetypes=[("Audio files", "*.mp3 *.wav *.m4a")])), "Optional background music (.mp3)")

        ctk.CTkLabel(c7, text="BGM Volume").grid(row=2, column=0, padx=6, pady=3, sticky="w")
        self.bgm_vol_slider = ctk.CTkSlider(c7, from_=0, to=100, number_of_steps=20, height=14, command=lambda v: self.bgm_vol_label.configure(text=f"{int(v)}%"))
        self.bgm_vol_slider.grid(row=2, column=1, padx=4, pady=3, sticky="ew")
        self.bgm_vol_slider.set(20)
        self.bgm_vol_label = ctk.CTkLabel(c7, text="20%", width=55, text_color=C_CYAN, font=ctk.CTkFont(size=10))
        self.bgm_vol_label.grid(row=2, column=2, padx=6)

        ctk.CTkLabel(c7, text="Voice Volume").grid(row=3, column=0, padx=6, pady=3, sticky="w")
        self.voice_vol_slider = ctk.CTkSlider(c7, from_=50, to=200, number_of_steps=30, height=14, command=lambda v: self.voice_vol_label.configure(text=f"{int(v)}%"))
        self.voice_vol_slider.grid(row=3, column=1, padx=4, pady=3, sticky="ew")
        self.voice_vol_slider.set(100)
        self.voice_vol_label = ctk.CTkLabel(c7, text="100%", width=55, text_color=C_CYAN, font=ctk.CTkFont(size=10))
        self.voice_vol_label.grid(row=3, column=2, padx=6)

        self.enable_ducking = ctk.CTkCheckBox(c7, text="Auto Audio Ducking (BGM drops when voice speaks)", text_color=C_TEXT)
        self.enable_ducking.grid(row=4, column=0, columnspan=2, padx=6, pady=(3, 8), sticky="w")
        self.enable_ducking.select()

        # =====================================================================
        # TAB 3: 🚀 EXPORT & BATCH QUEUE WORKSTATION
        # =====================================================================
        exp_left = ctk.CTkScrollableFrame(tab_export, fg_color="transparent", width=440)
        exp_left.grid(row=0, column=0, padx=(2, 4), pady=2, sticky="nsew")

        exp_right = ctk.CTkScrollableFrame(tab_export, fg_color="transparent")
        exp_right.grid(row=0, column=1, padx=(2, 4), pady=2, sticky="nsew")

        # Video Quality & Export Settings Card
        c3 = ctk.CTkFrame(exp_left, fg_color=C_CARD, corner_radius=8, border_width=1, border_color=C_BORDER)
        c3.pack(fill="x", pady=4, padx=2)
        c3.grid_columnconfigure(1, weight=1)

        c3_hdr = ctk.CTkFrame(c3, fg_color=C_CARD_HEADER, corner_radius=6, height=28)
        c3_hdr.grid(row=0, column=0, columnspan=3, sticky="ew", padx=2, pady=2)
        ctk.CTkLabel(c3_hdr, text="  🎬 Render Quality & Resolution Settings", font=ctk.CTkFont(size=11, weight="bold"), text_color=C_TEXT).pack(side="left", padx=6)

        ctk.CTkLabel(c3, text="Video Resolution").grid(row=1, column=0, padx=6, pady=3, sticky="w")
        self.video_res = ctk.CTkComboBox(
            c3, height=26,
            values=[
                "1280x720 (720p Fast HD)",
                "1920x1080 (1080p Full HD Standard)",
                "2560x1440 (2K QHD Ultra Quality)",
                "3840x2160 (4K UHD Cinematic)",
                "720x1280 (720p Shorts/Reels 9:16)",
                "1080x1920 (1080p Shorts/Reels 9:16)",
                "1440x2560 (2K Shorts/Reels 9:16)",
                "2160x3840 (4K Shorts/Reels 9:16)",
                "1080x1080 (1:1 Square)"
            ],
            state="readonly", fg_color=C_BG, border_color=C_BORDER
        )
        self.video_res.grid(row=1, column=1, columnspan=2, padx=(2, 6), pady=3, sticky="ew")
        self.video_res.set("1920x1080 (1080p Full HD Standard)")

        ctk.CTkLabel(c3, text="Aspect Ratio").grid(row=2, column=0, padx=6, pady=3, sticky="w")
        self.aspect_ratio = ctk.CTkSegmentedButton(c3, values=["16:9", "9:16", "1:1", "4:3"], selected_color=C_PURPLE, selected_hover_color=C_PURPLE_HOVER, height=26)
        self.aspect_ratio.grid(row=2, column=1, columnspan=2, padx=(2, 6), pady=3, sticky="ew")
        self.aspect_ratio.set("16:9")

        ctk.CTkLabel(c3, text="Render Quality").grid(row=3, column=0, padx=6, pady=3, sticky="w")
        self.render_quality = ctk.CTkComboBox(c3, height=26, values=["Fast Draft (Ultra Speed)", "Balanced Production (Recommended)", "High Quality 1080p", "Ultra Cinematic 4K"], state="readonly", fg_color=C_BG, border_color=C_BORDER)
        self.render_quality.grid(row=3, column=1, columnspan=2, padx=(2, 6), pady=3, sticky="ew")
        self.render_quality.set("Balanced Production (Recommended)")

        ctk.CTkLabel(c3, text="Frame Rate (FPS)").grid(row=4, column=0, padx=6, pady=3, sticky="w")
        self.video_fps = ctk.CTkComboBox(c3, height=26, values=["24 FPS (Cinematic Film)", "30 FPS (Standard Video)", "60 FPS (Ultra Smooth)"], state="readonly", fg_color=C_BG, border_color=C_BORDER)
        self.video_fps.grid(row=4, column=1, columnspan=2, padx=(2, 6), pady=3, sticky="ew")
        self.video_fps.set("30 FPS (Standard Video)")

        ctk.CTkLabel(c3, text="Parallel Video Workers").grid(row=5, column=0, padx=6, pady=3, sticky="w")
        self.parallel_video = ctk.CTkSlider(c3, from_=1, to=8, number_of_steps=7, height=14, command=lambda v: self.parallel_video_label.configure(text=f"{int(v)} workers"))
        self.parallel_video.grid(row=5, column=1, padx=4, pady=(3, 6), sticky="ew")
        self.parallel_video.set(4)
        self.parallel_video_label = ctk.CTkLabel(c3, text="4 workers", width=65, text_color=C_CYAN, font=ctk.CTkFont(size=10))
        self.parallel_video_label.grid(row=5, column=2, padx=6)

        self.output_path_entry = self._file_row(c3, 6, "Output Video Path", self._choose_output_path, "Save path for final MP4 video")

        # Export Action & Progress Tracker Card
        c8 = ctk.CTkFrame(exp_right, fg_color=C_CARD, corner_radius=8, border_width=1, border_color=C_BORDER)
        c8.pack(fill="x", pady=4, padx=2)
        c8.grid_columnconfigure(1, weight=1)

        c8_hdr = ctk.CTkFrame(c8, fg_color=C_CARD_HEADER, corner_radius=6, height=28)
        c8_hdr.grid(row=0, column=0, columnspan=3, sticky="ew", padx=2, pady=2)
        ctk.CTkLabel(c8_hdr, text="  ⚡ Render Action & Real-Time Progress Tracker", font=ctk.CTkFont(size=11, weight="bold"), text_color=C_TEXT).pack(side="left", padx=6)

        self.run_btn = ctk.CTkButton(
            c8, text="⚡ GENERATE STORY IMAGE VIDEO NOW", font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=C_PURPLE, hover_color=C_PURPLE_HOVER, height=38, command=self.run_project
        )
        self.run_btn.grid(row=1, column=0, columnspan=3, padx=6, pady=(6, 4), sticky="ew")

        # Live Progress Bar & Stage Tracker
        self.progress_bar = ctk.CTkProgressBar(c8, height=12, fg_color=C_BG, progress_color=C_PURPLE)
        self.progress_bar.grid(row=2, column=0, columnspan=3, padx=6, pady=2, sticky="ew")
        self.progress_bar.set(0.0)

        self.build_status = ctk.CTkLabel(c8, text="Idle • System ready to build story video", font=ctk.CTkFont(size=10, weight="bold"), text_color=C_MUTED)
        self.build_status.grid(row=3, column=0, columnspan=3, padx=6, pady=(0, 4), sticky="w")

        # Batch Queue Box
        q_box = ctk.CTkFrame(c8, fg_color=C_BG, corner_radius=6, border_width=1, border_color=C_BORDER)
        q_box.grid(row=4, column=0, columnspan=3, padx=6, pady=4, sticky="ew")

        q_hdr = ctk.CTkFrame(q_box, fg_color="transparent")
        q_hdr.pack(fill="x", padx=6, pady=3)
        ctk.CTkLabel(q_hdr, text="🗂️ Batch Queue", font=ctk.CTkFont(size=10, weight="bold"), text_color=C_CYAN).pack(side="left")
        
        ctk.CTkButton(q_hdr, text="➕ Add Queue", height=22, width=75, fg_color="#3B82F6", hover_color="#2563EB", command=self.add_current_to_queue).pack(side="left", padx=(8, 2))
        ctk.CTkButton(q_hdr, text="▶ Process", height=22, width=65, fg_color=C_GREEN, hover_color="#059669", command=self.process_queue).pack(side="left", padx=2)
        ctk.CTkButton(q_hdr, text="🗑 Clear", height=22, width=55, fg_color=C_RED, hover_color="#DC2626", command=self.clear_queue).pack(side="left", padx=2)

        self.queue_container = ctk.CTkScrollableFrame(q_box, height=75, fg_color="transparent")
        self.queue_container.pack(fill="x", padx=4, pady=2)
        ctk.CTkLabel(self.queue_container, text="No batch projects in queue", font=ctk.CTkFont(size=10), text_color=C_MUTED).pack(pady=6)

        # Log Console Card
        self.log_box = ctk.CTkTextbox(c8, height=130, font=ctk.CTkFont(family="Consolas", size=10), fg_color=C_BG, border_color=C_BORDER, border_width=1)
        self.log_box.grid(row=5, column=0, columnspan=3, padx=6, pady=(2, 6), sticky="ew")

        # ---------------------------------------------------------------------
        # 4. BOTTOM GLASS STATUS BAR
        # ---------------------------------------------------------------------
        bottom_bar = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=8, border_width=1, border_color=C_BORDER)
        bottom_bar.grid(row=3, column=0, padx=10, pady=(2, 6), sticky="ew")

        self.status_bar_lbl = ctk.CTkLabel(
            bottom_bar,
            text="● Auto Save Enabled  |  Scenes: 0  |  Words: 0  |  Duration: ~00:00  |  Output: 1920×1080  |  FFmpeg: Ready  |  Status: System Ready",
            font=ctk.CTkFont(size=10), text_color=C_MUTED
        )
        self.status_bar_lbl.pack(side="left", padx=10, pady=4)

    # -------------------------------------------------------------------------
    # SMART 1-CLICK PRESET PROFILES
    # -------------------------------------------------------------------------
    def _apply_preset_shorts(self):
        self.video_res.set("1080x1920 (1080p Shorts/Reels 9:16)")
        self.aspect_ratio.set("9:16")
        self.caption_preset.set("CapCut Yellow Pop")
        self.caption_words_per_line.set("1 Word (CapCut Pop)")
        self.caption_size.set(34)
        self.caption_position.set("Bottom-Center")
        self.camera_motion.set("🌟 Auto-Director Flow (Dynamic Scenes)")
        self.log("[preset] Applied '🔥 Viral YouTube Shorts (9:16)' preset ✓")

    def _apply_preset_longform(self):
        self.video_res.set("1920x1080 (1080p Full HD Standard)")
        self.aspect_ratio.set("16:9")
        self.caption_preset.set("Classic White & Black Box")
        self.caption_words_per_line.set("3 Words")
        self.caption_size.set(28)
        self.camera_motion.set("🎬 Slow Push-In (Depth Focus)")
        self.log("[preset] Applied '🎬 YouTube Longform (16:9 1080p)' preset ✓")

    def _apply_preset_fast(self):
        self.video_res.set("1280x720 (720p Fast HD)")
        self.aspect_ratio.set("16:9")
        self.render_quality.set("Fast Draft (Ultra Speed)")
        self.camera_motion.set("⏹️ Static (No Motion)")
        self.parallel_video.set(6)
        self.parallel_video_label.configure(text="6 workers")
        self.log("[preset] Applied '⚡ Ultra Speed Draft (720p Static)' preset ✓")

    def _apply_preset_4k(self):
        self.video_res.set("3840x2160 (4K UHD Cinematic)")
        self.video_fps.set("60 FPS (Ultra Smooth)")
        self.render_quality.set("Ultra Cinematic 4K")
        self.caption_preset.set("Gold Luxury Bold")
        self.camera_motion.set("🌊 3D Parallax & Gentle Float")
        self.log("[preset] Applied '💎 4K Cinema Master' preset ✓")

    # -------------------------------------------------------------------------
    # UI NAVIGATION & SCROLL HELPERS
    # -------------------------------------------------------------------------
    def _scroll_to_script(self):
        self.studio_tabs.set("🎬 1. Storyboard & Voice Production")

    def _scroll_to_voice(self):
        self.studio_tabs.set("🎬 1. Storyboard & Voice Production")

    def _scroll_to_video_settings(self):
        self.studio_tabs.set("🚀 3. Export & Batch Queue Manager")

    def _scroll_to_branding(self):
        self.studio_tabs.set("🎨 2. Styling, Subtitles & FX")

    def _scroll_to_captions(self):
        self.studio_tabs.set("🎨 2. Styling, Subtitles & FX")

    def _scroll_to_motion(self):
        self.studio_tabs.set("🎨 2. Styling, Subtitles & FX")

    def _scroll_to_audio(self):
        self.studio_tabs.set("🎨 2. Styling, Subtitles & FX")

    def _scroll_to_export(self):
        self.studio_tabs.set("🚀 3. Export & Batch Queue Manager")

    def _file_row(self, parent: ctk.CTkFrame, row: int, label: str, cmd, placeholder: str = "") -> ctk.CTkEntry:
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, padx=6, pady=2, sticky="w")
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.grid(row=row, column=1, columnspan=2, padx=(2, 6), pady=2, sticky="ew")
        wrap.grid_columnconfigure(0, weight=1)

        entry = ctk.CTkEntry(wrap, placeholder_text=placeholder, height=26, fg_color=C_BG, border_color=C_BORDER)
        entry.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        ctk.CTkButton(wrap, text="Browse", width=65, height=26, fg_color=C_CARD_HEADER, hover_color="#283652", command=cmd).grid(row=0, column=1)
        return entry

    def _set_path(self, entry: ctk.CTkEntry, path: str):
        if path:
            entry.delete(0, "end")
            entry.insert(0, os.path.abspath(path))

    def _choose_logo(self):
        p = filedialog.askopenfilename(filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp")])
        if p:
            self._set_path(self.logo_entry, p)
            if p not in self.uploaded_logos:
                self.uploaded_logos.append(p)

    def _choose_visualizer(self):
        p = filedialog.askopenfilename(filetypes=[("Visualizer / Soundwave GIF", "*.gif *.mp4 *.mov *.webp *.png"), ("All Files", "*.*")])
        if p:
            self._set_path(self.visualizer_entry, p)

    def _choose_subscribe(self):
        p = filedialog.askopenfilename(filetypes=[("Subscribe Animation GIF", "*.gif *.mp4 *.mov *.webp *.png"), ("All Files", "*.*")])
        if p:
            self._set_path(self.subscribe_entry, p)

    def _choose_bg_videos(self):
        files = filedialog.askopenfilenames(filetypes=[("Video files", "*.mp4 *.mov *.mkv *.avi")])
        if files:
            self.bg_video_entry.delete(0, "end")
            self.bg_video_entry.insert(0, ";".join(files))

    def _choose_intros(self):
        files = filedialog.askopenfilenames(filetypes=[("Video files", "*.mp4 *.mov *.mkv *.avi")])
        if files:
            self.intro_entry.delete(0, "end")
            self.intro_entry.insert(0, ";".join(files))

    def _choose_custom_font(self):
        p = filedialog.askopenfilename(filetypes=[("Font files", "*.ttf *.otf")])
        if p:
            self._set_path(self.custom_font_entry, p)

    def _choose_output_path(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4", filetypes=[("MP4 Video", "*.mp4")])
        if p:
            self._set_path(self.output_path_entry, p)

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{ts}] {msg}"
        self.ui_queue.put(("log", formatted))
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(formatted + "\n")
        except Exception:
            pass

        # Progress bar parser logic
        if "%" in msg:
            try:
                # Extract percentage from msg
                import re
                m = re.search(r"(\d+)%", msg)
                if m:
                    pct = int(m.group(1)) / 100.0
                    self.ui_queue.put(("progress", pct))
            except Exception: pass

    def _post_ui(self, fn, *args):
        self.ui_queue.put(("callback", (fn, args)))

    def _drain_ui_queue(self):
        try:
            while not self.ui_queue.empty():
                item = self.ui_queue.get_nowait()
                if item[0] == "log":
                    line = item[1]
                    self.log_box.insert("end", line + "\n")
                    self.log_box.see("end")
                    if "Progress:" in line or "FPS" in line or "Speed" in line:
                        short_stat = line.split("]")[-1].strip()
                        if short_stat:
                            self.build_status.configure(text=short_stat[:85], text_color=C_CYAN)
                elif item[0] == "progress":
                    self.progress_bar.set(item[1])
                elif item[0] == "callback":
                    fn, args = item[1]
                    fn(*args)
        except Exception:
            pass
        self.after(80, self._drain_ui_queue)

    def _load_env(self):
        try:
            env_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
            if env_key:
                self.api_key.delete(0, "end")
                self.api_key.insert(0, env_key)

            try:
                import voice_cache
                cached = voice_cache.load_api_key()
                if cached and not self.api_key.get().strip():
                    self.api_key.delete(0, "end")
                    self.api_key.insert(0, cached)
            except Exception:
                pass

            # Detect GPU Hardware Acceleration
            gpu_display_name = "CPU"
            try:
                import story_image_engine
                gpu_info = story_image_engine.get_gpu_info()
                gpu_name = gpu_info.get("gpu_name", "Integrated Display")
                enc = gpu_info.get("hw_encoder", "libx264")
                is_gpu = gpu_info.get("is_gpu", False)
                max_s = gpu_info.get("max_gpu_sessions", 3)
                if is_gpu:
                    gpu_display_name = f"{gpu_name} ({enc.upper()})"
                    self.gpu_badge.configure(
                        text=f"⚡ GPU: {gpu_name} ({enc.upper()}) | Hybrid Parallel 🚀",
                        fg_color="#133826",
                        text_color="#34D399"
                    )
                    self.env_status.configure(text=f"FFmpeg + GPU NVENC Ready ✓ ({max_s} slots)", text_color=C_GREEN)
                else:
                    self.gpu_badge.configure(
                        text=f"💻 CPU Multi-Thread ({enc})",
                        fg_color="#2A2415",
                        text_color="#FBBF24"
                    )
                    self.env_status.configure(text="FFmpeg Ready (CPU)", text_color=C_CYAN)
            except Exception as _gpu_e:
                self.gpu_badge.configure(text="⚡ GPU: Standard", text_color=C_MUTED)

            if hasattr(self, "status_bar_lbl"):
                self.status_bar_lbl.configure(
                    text=f"● Auto Save Active  |  GPU Acceleration: {gpu_display_name}  |  FFmpeg: Ready  |  Status: System Ready"
                )

            self._load_settings()
            self.after(300, self._auto_load_voices_on_init)
        except Exception as e:
            self.env_status.configure(text=f"Env Warning: {e}", text_color=C_AMBER)

    def _toggle_key_visibility(self):
        self.show_api_key = not self.show_api_key
        self.api_key.configure(show="" if self.show_api_key else "*")
        self.show_key_btn.configure(text="🔒" if self.show_api_key else "👁")

    def _clear_voice_search(self):
        self.voice_search.delete(0, "end")
        self._filter_voices()

    def parse_script_blocks(self):
        raw = self.script_box.get("1.0", "end").strip()
        if not raw:
            messagebox.showwarning("Empty Script", "Please enter or paste script text first.")
            return

        import story_image_engine
        scenes = story_image_engine.parse_scene_script(raw)
        self.parsed_scenes = scenes
        
        tot_words = sum(sc["word_count"] for sc in scenes)
        tot_chars = sum(sc["char_count"] for sc in scenes)
        est_dur = sum(sc["word_count"] / 2.5 for sc in scenes)

        m, s = divmod(int(est_dur), 60)
        dur_str = f"{m:02d}:{s:02d}"

        self.parse_badge.configure(text=f"{len(scenes)} Scenes | ~{dur_str}", text_color=C_CYAN)
        self.log(f"[script] Parsed Scene {len(scenes)} | Total Words: {tot_words:,} | Total Chars: {tot_chars:,}")
        
        for w in self.scene_tree.winfo_children():
            w.destroy()

        if hasattr(story_image_engine, "auto_match_images"):
            self.scene_image_map = story_image_engine.auto_match_images(self.bulk_images, len(scenes))

        from PIL import Image, ImageTk

        for sc in scenes:
            s_no = sc["scene_no"]
            row = ctk.CTkFrame(self.scene_tree, fg_color=C_CARD_HEADER, corner_radius=6)
            row.pack(fill="x", padx=4, pady=3)
            
            hdr = ctk.CTkFrame(row, fg_color="transparent")
            hdr.pack(fill="x", padx=6, pady=3)
            
            ctk.CTkLabel(hdr, text=f"Scene {s_no}", font=ctk.CTkFont(size=11, weight="bold"), text_color=C_PURPLE).pack(side="left")
            
            est_sc_dur = sc["word_count"] / 2.5
            ctk.CTkLabel(hdr, text=f"• {sc['word_count']} words (~{est_sc_dur:.1f}s)", font=ctk.CTkFont(size=9), text_color=C_MUTED).pack(side="left", padx=6)

            # Per Scene Image Button
            img_p = self.scene_image_map.get(s_no, "")
            img_name = os.path.basename(img_p) if img_p else "No image assigned"

            btn_wrap = ctk.CTkFrame(hdr, fg_color="transparent")
            btn_wrap.pack(side="right")

            img_btn = ctk.CTkButton(
                btn_wrap, text=f"🖼️ {img_name[:18]}...", font=ctk.CTkFont(size=9), height=22, fg_color=C_CARD, hover_color="#283652",
                command=lambda s=s_no: self._replace_scene_image(s)
            )
            img_btn.pack(side="left", padx=2)

            play_sc_btn = ctk.CTkButton(
                btn_wrap, text="▶ Audio", font=ctk.CTkFont(size=9), width=55, height=22, fg_color=C_CYAN, hover_color="#0891B2",
                command=lambda text=sc["text"]: self._preview_scene_text(text)
            )
            play_sc_btn.pack(side="left", padx=2)

            preview_txt = sc["text"][:110] + ("..." if len(sc["text"]) > 110 else "")
            ctk.CTkLabel(row, text=preview_txt, font=ctk.CTkFont(size=9), text_color=C_TEXT, anchor="w", justify="left").pack(fill="x", padx=6, pady=(0, 3))

        self.status_bar_lbl.configure(text=f"● Auto Save Enabled  |  Scenes: {len(scenes)}  |  Words: {tot_words}  |  Duration: ~{dur_str}  |  Output: {self.video_res.get().split()[0]}  |  Status: Storyboard Loaded")

    def _replace_scene_image(self, scene_no: int):
        p = filedialog.askopenfilename(filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp")])
        if p:
            self.scene_image_map[scene_no] = p
            self.log(f"[storyboard] Scene {scene_no} image updated -> {os.path.basename(p)}")
            self.parse_script_blocks()

    def _preview_scene_text(self, text: str):
        vid = self._selected_voice_id()
        key = self.api_key.get().strip()
        
        def worker():
            try:
                import story_image_engine
                out_p = os.path.join(self.preview_cache_dir, f"scene_tts_{hash(text)}.mp3")
                story_image_engine._generate_single_chunk_tts(text, vid, self._selected_model_id(), key, out_p)
                if os.path.exists(out_p):
                    self._post_ui(self._play_audio_file, out_p)
            except Exception as e:
                self._post_ui(messagebox.showerror, "TTS Error", f"Scene audio preview failed:\n{e}")

        threading.Thread(target=worker, daemon=True).start()

    def _choose_bulk_images(self):
        files = filedialog.askopenfilenames(filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp")])
        if files:
            self.bulk_images = list(files)
            self.log(f"[images] Bulk selected {len(files)} image(s).")
            if self.parsed_scenes:
                self.parse_script_blocks()

    def _fetch_voices_threaded(self):
        key = self.api_key.get().strip() or "sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt"
        
        # 1. Immediate instant load from cache/built-in so user never waits (0s delay)
        import voice_cache
        immediate_voices = voice_cache.load_voices_cached(api_key=key, force_refresh=False)
        if immediate_voices:
            self.voices = immediate_voices
            self._filter_voices()

        self.api_status.configure(text="Syncing online voice models... ▶", text_color=C_CYAN)

        def worker():
            try:
                voice_cache.save_api_key(key)
                v_list = voice_cache.load_voices_cached(api_key=key, force_refresh=True)
                self._post_ui(self._update_voices_ui, v_list or immediate_voices)
            except Exception:
                self._post_ui(self._update_voices_ui, immediate_voices or voice_cache.DEFAULT_FALLBACK_VOICES)

        threading.Thread(target=worker, daemon=True).start()

    def _auto_load_voices_on_init(self):
        if getattr(self, "_voices_loaded_once", False) and getattr(self, "voices", None):
            return
        self._voices_loaded_once = True
        try:
            import voice_cache
            cached = voice_cache.load_voices_cached(force_refresh=False)
            if cached:
                self._update_voices_ui(cached)
            else:
                self._fetch_voices_threaded()
        except Exception:
            self._fetch_voices_threaded()

    def _update_voices_ui(self, voices: List[Dict[str, Any]]):
        self.voices = voices or []
        self._filter_voices()
        if self.voices:
            first_vid = self.voices[0].get("voice_id") or "elevenlabs_hpp4J3VqNfWAU000d1Us"
            if hasattr(self, "voice_id") and not self.voice_id.get().strip():
                self.voice_id.insert(0, first_vid)
        if hasattr(self, "api_status"):
            try:
                self.api_status.configure(text=f"Loaded {len(self.voices)} voices ✓", text_color=C_GREEN)
            except Exception:
                pass
        self.log(f"[voice] Loaded {len(self.voices)} voice models.")

    def _update_voices_error(self, err: str):
        import voice_cache
        if not getattr(self, "voices", None):
            self.voices = voice_cache.DEFAULT_FALLBACK_VOICES
            self._filter_voices()
        if hasattr(self, "api_status"):
            try:
                self.api_status.configure(text=f"Loaded {len(self.voices)} voices ✓", text_color=C_GREEN)
            except Exception:
                pass

    def _selected_model_id(self) -> str:
        choice = self.submodel_menu.get().strip() if hasattr(self, "submodel_menu") else "All Models / Sub-Models"
        if "All " in choice:
            return "eleven_multilingual_v2"
        return choice

    def _selected_voice_id(self) -> str:
        vid = self.voice_id.get().strip() if hasattr(self, "voice_id") else ""
        if not vid:
            vid = "elevenlabs_hpp4J3VqNfWAU000d1Us"

        if "•" in vid:
            vid = vid.split("•")[-1].strip()
        if "(" in vid and ")" in vid and not any(vid.startswith(p) for p in ["elevenlabs_", "minimax_", "clone_", "edge_", "kokoro_", "vbee_", "fishaudio_"]):
            m = re.search(r'\(([^)]+)\)', vid)
            if m and len(m.group(1)) > 5:
                vid = m.group(1).strip()

        clean_vid = vid.split()[-1].strip()
        valid_prefixes = ("elevenlabs_", "minimax_", "clone_", "edge_", "kokoro_", "vbee_", "fishaudio_")
        if not any(clean_vid.startswith(p) for p in valid_prefixes):
            clean_vid = f"elevenlabs_{clean_vid}"
        return clean_vid

    def _provider_changed(self, provider: str):
        submodel_map = {
            "ElevenLabs": ["All ElevenLabs Models", "eleven_multilingual_v2", "eleven_turbo_v2_5", "eleven_flash_v2_5", "eleven_v3"],
            "Minimax": ["All Minimax Models", "minimax_v1"],
            "FishAudio": ["All FishAudio Models", "fishaudio_v1"],
            "Edge Neural": ["All Edge Models", "edge_v1"],
            "Kokoro": ["All Kokoro Models", "kokoro_v1"],
            "Vbee": ["All Vbee Models", "vbee_v1"],
            "Cloned Voices": ["All Cloned Models", "clone_v1"],
        }
        options = submodel_map.get(provider, ["All Models / Sub-Models"])
        self.submodel_menu.configure(values=options)
        self.submodel_menu.set(options[0])
        self._filter_voices()

    def _filter_voices(self):
        if not hasattr(self, "voice_list_scroll"):
            return
        try:
            if not self.voice_list_scroll.winfo_exists():
                return
        except Exception:
            return

        for child in self.voice_list_scroll.winfo_children():
            try: child.destroy()
            except Exception: pass

        if not hasattr(self, "voices") or not self.voices:
            ctk.CTkLabel(self.voice_list_scroll, text="Click 'Fetch Voices' to load AI33 voice models.", font=ctk.CTkFont(size=10), text_color=C_MUTED).pack(pady=20)
            return

        provider_sel = self.model_menu.get().strip() if hasattr(self, "model_menu") else "All Providers"
        submodel_sel = self.submodel_menu.get().strip() if hasattr(self, "submodel_menu") else "All Models / Sub-Models"
        q = self.voice_search.get().strip().lower() if hasattr(self, "voice_search") else ""

        matched_voices = []

        for v in self.voices:
            vid = v.get("voice_id") or v.get("id") or ""
            name = v.get("name", "Unnamed")
            prov = v.get("provider", "ElevenLabs")
            cat = v.get("category", "")
            lang = v.get("language", "")

            if provider_sel and provider_sel != "All Providers":
                p_norm = provider_sel.lower()
                prov_norm = prov.lower()
                if "eleven" in p_norm:
                    if "eleven" not in prov_norm: continue
                elif "minimax" in p_norm:
                    if "minimax" not in prov_norm: continue
                elif "fish" in p_norm:
                    if "fish" not in prov_norm: continue
                elif "edge" in p_norm:
                    if "edge" not in prov_norm: continue
                elif "kokoro" in p_norm:
                    if "kokoro" not in prov_norm: continue
                elif "vbee" in p_norm:
                    if "vbee" not in prov_norm: continue
                elif "clone" in p_norm:
                    if "clone" not in prov_norm: continue
                elif p_norm.replace(" ", "") not in prov_norm.replace(" ", ""):
                    continue

            if submodel_sel and "All " not in submodel_sel:
                sm_clean = submodel_sel.lower()
                if sm_clean not in vid.lower() and sm_clean not in name.lower():
                    pass

            if q:
                if q not in name.lower() and q not in vid.lower() and q not in prov.lower() and q not in cat.lower() and q not in lang.lower():
                    continue

            matched_voices.append(v)

        if not matched_voices:
            ctk.CTkLabel(self.voice_list_scroll, text="No matching voices found for search/filter.", font=ctk.CTkFont(size=10), text_color=C_MUTED).pack(pady=20)
            return

        current_selected_vid = self.voice_id.get().strip() if hasattr(self, "voice_id") else ""

        for v in matched_voices[:30]:
            vid = v.get("voice_id") or v.get("id") or ""
            name = v.get("name", "Unnamed")
            prov = v.get("provider", "ElevenLabs")
            cat = v.get("category", "")
            lang = v.get("language", "")

            is_selected = False
            if current_selected_vid:
                is_selected = (
                    vid == current_selected_vid or 
                    (vid and current_selected_vid.endswith(vid)) or 
                    (current_selected_vid and vid.endswith(current_selected_vid))
                )

            row_bg = "#1e293b" if is_selected else C_CARD_HEADER
            border_col = C_GREEN if is_selected else C_BORDER

            row = ctk.CTkFrame(self.voice_list_scroll, fg_color=row_bg, corner_radius=6, border_width=1, border_color=border_col)
            row.pack(fill="x", padx=2, pady=2)

            # 1. Left: Inline ▶ Play button
            play_btn = ctk.CTkButton(
                row, text="▶", width=28, height=24, font=ctk.CTkFont(size=10, weight="bold"),
                fg_color=C_PURPLE, hover_color="#7C3AED",
                command=lambda voice=v: self.play_single_voice_preview(voice)
            )
            play_btn.pack(side="left", padx=(4, 4), pady=3)

            # 2. Right: Select / Use Button (PACKED BEFORE info_frame SO IT NEVER GETS CUT OFF!)
            sel_btn = ctk.CTkButton(
                row, text="✓ In Use" if is_selected else "Use Voice", width=68, height=24, font=ctk.CTkFont(size=9, weight="bold"),
                fg_color=C_GREEN if is_selected else C_CYAN,
                text_color="#000000",
                hover_color="#059669" if is_selected else "#0891B2",
                command=lambda v_id=vid, v_name=name: self._select_voice_id(v_id, v_name)
            )
            sel_btn.pack(side="right", padx=(4, 6), pady=3)

            # 3. Center: Voice Name + Metadata
            info_frame = ctk.CTkFrame(row, fg_color="transparent")
            info_frame.pack(side="left", fill="x", expand=True, padx=(2, 4))

            disp_name = f"[{prov}] {name}"
            if len(disp_name) > 34:
                disp_name = disp_name[:32] + "…"
            top_lbl = ctk.CTkLabel(info_frame, text=disp_name, font=ctk.CTkFont(size=10, weight="bold"), text_color=C_CYAN if is_selected else C_TEXT, anchor="w")
            top_lbl.pack(anchor="w")

            meta_items = [cat, lang]
            if vid:
                short_vid = vid.split('_')[-1] if '_' in vid else vid
                meta_items.append(short_vid[:18])
            meta_str = " / ".join(filter(None, meta_items))
            if len(meta_str) > 36:
                meta_str = meta_str[:34] + "…"
            sub_lbl = ctk.CTkLabel(info_frame, text=meta_str, font=ctk.CTkFont(size=8), text_color=C_MUTED, anchor="w")
            sub_lbl.pack(anchor="w")

            # Click on row / text to also select voice
            row.bind("<Button-1>", lambda e, v_id=vid, v_name=name: self._select_voice_id(v_id, v_name))
            info_frame.bind("<Button-1>", lambda e, v_id=vid, v_name=name: self._select_voice_id(v_id, v_name))
            top_lbl.bind("<Button-1>", lambda e, v_id=vid, v_name=name: self._select_voice_id(v_id, v_name))
            sub_lbl.bind("<Button-1>", lambda e, v_id=vid, v_name=name: self._select_voice_id(v_id, v_name))

    def _select_voice_id(self, vid: str, name: str = ""):
        if hasattr(self, "voice_id"):
            self.voice_id.delete(0, "end")
            self.voice_id.insert(0, vid)
            if hasattr(self, "api_status") and name:
                self.api_status.configure(text=f"Selected Voice: {name} ({vid[:20]}) ✓", text_color=C_GREEN)
            self._filter_voices()

    def play_single_voice_preview(self, voice_dict: Dict[str, Any]):
        vid = voice_dict.get("voice_id") or voice_dict.get("id") or ""
        vname = voice_dict.get("name") or vid
        purl = voice_dict.get("preview_url") or ""
        key = self.api_key.get().strip() or "sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt"

        if not vid:
            messagebox.showwarning("Voice Missing", "Please select a valid Voice ID.")
            return

        if hasattr(self, "api_status"):
            self.api_status.configure(text=f"Loading preview for '{vname}'... ▶", text_color=C_CYAN)

        def worker():
            try:
                clean_name = vid.replace('/', '_').replace(':', '_')
                out_p = os.path.join(self.preview_cache_dir, f"preview_{clean_name}.mp3")

                # 1. If audio already cached, play immediately!
                if os.path.exists(out_p) and os.path.getsize(out_p) > 500:
                    self._play_audio_file(out_p)
                    return

                # 2. Build candidate URLs for direct sample download
                candidate_urls = []
                if purl and purl.startswith("http"):
                    candidate_urls.append(purl)

                bare_vid = vid
                for p in ["elevenlabs_", "minimax_", "clone_", "edge_", "kokoro_", "vbee_", "fishaudio_"]:
                    if bare_vid.startswith(p):
                        bare_vid = bare_vid[len(p):]
                        break

                if "eleven" in vid.lower() or not any(vid.startswith(p) for p in ["minimax_", "fishaudio_", "edge_", "kokoro_"]):
                    candidate_urls.append(f"https://storage.googleapis.com/eleven-public-prod/previews/voices/{bare_vid}/preview.mp3")
                    candidate_urls.append(f"https://storage.googleapis.com/eleven-public-cdn/audio/previews/{bare_vid}.mp3")
                candidate_urls.append(f"https://api.ai33.pro/previews/{vid}.mp3")

                # Try candidate URLs
                for c_url in candidate_urls:
                    try:
                        req = urllib.request.Request(c_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                        with urllib.request.urlopen(req, timeout=6, context=_get_ssl_context()) as resp:
                            if resp.status == 200:
                                data = resp.read()
                                if len(data) > 800 and not data.startswith(b"<!DOCTYPE") and not data.startswith(b"<html"):
                                    with open(out_p, "wb") as f:
                                        f.write(data)
                                    self._play_audio_file(out_p)
                                    return
                    except Exception:
                        pass

                # 3. TTS Sample Generation via AI33 / ElevenLabs
                sample_text = f"Hello! This is a voice preview of {vname} in Stories Studio."
                try:
                    from ai33_api import ai33_tts_generate
                    if ai33_tts_generate(sample_text, vid, api_key=key, out_path=out_p, log_fn=self.log):
                        if os.path.exists(out_p) and os.path.getsize(out_p) > 300:
                            self._play_audio_file(out_p)
                            return
                except Exception as ai33_err:
                    self.log(f"[preview-ai33] AI33 TTS sample failed: {ai33_err}")

                self._post_ui(messagebox.showerror, "Preview Failed", f"Unable to generate preview audio for {vid}.")
                if hasattr(self, "api_status"):
                    self._post_ui(lambda: self.api_status.configure(text=f"Preview failed for {vname}", text_color=C_RED))
            except Exception as e:
                self._post_ui(messagebox.showerror, "Preview Error", f"Voice preview error:\n{e}")

        threading.Thread(target=worker, daemon=True).start()

    def play_voice_preview(self):
        vid = self._selected_voice_id()
        self.play_single_voice_preview({"voice_id": vid, "name": vid})

    def _play_audio_file(self, audio_path: str):
        if not audio_path or not os.path.exists(audio_path):
            return
        audio_path = os.path.abspath(audio_path)
        self.stop_preview()

        # Strategy 1: Native Windows Multimedia MCI API (Built into Windows, zero deps, instant MP3/WAV playback)
        if sys.platform == "win32":
            try:
                import ctypes
                winmm = ctypes.windll.winmm
                winmm.mciSendStringW("close voice_preview_mci", None, 0, None)
                safe_p = audio_path.replace('"', '')
                open_cmd = f'open "{safe_p}" type mpegvideo alias voice_preview_mci'
                err = winmm.mciSendStringW(open_cmd, None, 0, None)
                if err == 0:
                    winmm.mciSendStringW("play voice_preview_mci", None, 0, None)
                    if hasattr(self, "api_status"):
                        self._post_ui(lambda: self.api_status.configure(text="Playing voice preview audio... ▶", text_color=C_GREEN))
                    return
            except Exception as mci_err:
                self.log(f"[audio-play] MCI playback notice: {mci_err}")

        # Strategy 2: Pygame Mixer
        try:
            import pygame
            if not pygame.mixer.get_init():
                try:
                    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=4096)
                except Exception:
                    pygame.mixer.init()
            try:
                pygame.mixer.music.stop()
                if hasattr(pygame.mixer.music, "unload"):
                    pygame.mixer.music.unload()
            except Exception:
                pass
            pygame.mixer.music.load(audio_path)
            pygame.mixer.music.play()
            if hasattr(self, "api_status"):
                self._post_ui(lambda: self.api_status.configure(text="Playing voice preview audio... ▶", text_color=C_GREEN))
            return
        except Exception as pe:
            self.log(f"[audio-play] Pygame playback warning: {pe}")

        # Strategy 3: PowerShell MediaPlayer (with presentationCore + WindowsBase)
        if sys.platform == "win32":
            try:
                safe_p = audio_path.replace("'", "''")
                ps_script = f"Add-Type -AssemblyName presentationCore, WindowsBase; $p = New-Object System.Windows.Media.MediaPlayer; $p.Open((New-Object System.Uri('{safe_p}'))); $p.Play(); Start-Sleep -s 6"
                self.preview_process = subprocess.Popen(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                    creationflags=0x08000000
                )
                if hasattr(self, "api_status"):
                    self._post_ui(lambda: self.api_status.configure(text="Playing voice preview audio... ▶", text_color=C_GREEN))
                return
            except Exception as ps_err:
                self.log(f"[audio-play] PowerShell audio player failed: {ps_err}")

        # Strategy 4: System default handler
        if hasattr(os, "startfile"):
            try:
                os.startfile(audio_path)
                if hasattr(self, "api_status"):
                    self._post_ui(lambda: self.api_status.configure(text="Playing voice preview audio... ▶", text_color=C_GREEN))
            except Exception as sf_err:
                self.log(f"[audio-play] startfile failed: {sf_err}")

    def stop_preview(self):
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.winmm.mciSendStringW("stop voice_preview_mci", None, 0, None)
                ctypes.windll.winmm.mciSendStringW("close voice_preview_mci", None, 0, None)
            except Exception:
                pass
        try:
            import pygame
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
                if hasattr(pygame.mixer.music, "unload"):
                    pygame.mixer.music.unload()
        except Exception:
            pass
        if hasattr(self, "preview_process") and self.preview_process:
            try:
                self.preview_process.terminate()
            except Exception:
                pass
            self.preview_process = None

    def open_logo_canvas_editor(self):
        logo_p = self.logo_entry.get().strip()
        if not logo_p or not os.path.exists(logo_p):
            messagebox.showwarning("Logo Required", "Please select a valid logo image file first.")
            return

        win = ctk.CTkToplevel(self)
        win.title("📐 Canvas Logo Drag & Drop Editor")
        win.geometry("920x640")
        win.configure(fg_color=C_BG)
        win.grab_set()

        hdr = ctk.CTkFrame(win, fg_color=C_CARD, corner_radius=8, border_width=1, border_color=C_BORDER)
        hdr.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkLabel(hdr, text="  📐 DRAG & DROP LOGO WATERMARK", font=ctk.CTkFont(size=12, weight="bold"), text_color=C_CYAN).pack(side="left", padx=8, pady=6)
        status_coord_lbl = ctk.CTkLabel(hdr, text="Drag the logo on canvas to set custom position", font=ctk.CTkFont(size=11), text_color=C_MUTED)
        status_coord_lbl.pack(side="right", padx=12)

        c_frame = ctk.CTkFrame(win, fg_color="#000000", corner_radius=8, border_width=1, border_color=C_BORDER)
        c_frame.pack(fill="both", expand=True, padx=12, pady=4)

        canvas_w, canvas_h = 850, 480
        canvas = ctk.CTkCanvas(c_frame, width=canvas_w, height=canvas_h, bg="#0F172A", highlightthickness=0)
        canvas.pack(expand=True, padx=4, pady=4)

        from PIL import Image, ImageTk, ImageOps
        try:
            # 1. Load active background image if available
            assigned_imgs = [p for p in self.scene_image_map.values() if p and os.path.exists(p)]
            if not assigned_imgs and self.bulk_images:
                assigned_imgs = [p for p in self.bulk_images if p and os.path.exists(p)]
            
            if assigned_imgs and os.path.exists(assigned_imgs[0]):
                src_im = Image.open(assigned_imgs[0]).convert("RGB")
                bg_im = ImageOps.fit(src_im, (canvas_w, canvas_h), method=Image.Resampling.LANCZOS)
            else:
                bg_im = Image.new("RGB", (canvas_w, canvas_h), color=(15, 23, 42))

            bg_tk = ImageTk.PhotoImage(bg_im)
            canvas.bg_tk = bg_tk
            canvas.create_image(0, 0, image=bg_tk, anchor="nw")

            # 2. Draw subtitle area indicator
            sub_pos = self.caption_position.get().lower()
            if "top" in sub_pos:
                sub_y = 40
            elif "middle" in sub_pos or "center" in sub_pos and "bottom" not in sub_pos:
                sub_y = canvas_h // 2
            else:
                sub_y = canvas_h - 50

            canvas.create_rectangle(
                canvas_w // 2 - 220, sub_y - 20,
                canvas_w // 2 + 220, sub_y + 20,
                fill="#1E293B", outline="#475569", dash=(4, 4), width=1
            )
            canvas.create_text(
                canvas_w // 2, sub_y,
                text=f"[ Subtitle Zone: {self.caption_preset.get()} ]",
                fill="#94A3B8", font=("Impact", 12)
            )

            # 3. Load & Scale Logo
            logo_im_raw = Image.open(logo_p).convert("RGBA")
            scale_ratio = canvas_w / 1280.0
            l_w_real = int(self.logo_width_slider.get())
            l_w_canvas = max(24, int(l_w_real * scale_ratio))
            aspect = logo_im_raw.height / max(1, logo_im_raw.width)
            l_h_canvas = max(24, int(l_w_canvas * aspect))
            logo_im = logo_im_raw.resize((l_w_canvas, l_h_canvas), Image.Resampling.LANCZOS)
            logo_tk = ImageTk.PhotoImage(logo_im)
            canvas.logo_tk = logo_tk

            if self.custom_logo_x is not None and self.custom_logo_y is not None:
                init_x = int(self.custom_logo_x * scale_ratio)
                init_y = int(self.custom_logo_y * scale_ratio)
            else:
                init_x = canvas_w - l_w_canvas - 20
                init_y = 20

            logo_item = canvas.create_image(init_x, init_y, image=logo_tk, anchor="nw")

            drag_data = {"x": 0, "y": 0}

            def on_press(event):
                drag_data["x"] = event.x
                drag_data["y"] = event.y

            def on_drag(event):
                dx = event.x - drag_data["x"]
                dy = event.y - drag_data["y"]
                canvas.move(logo_item, dx, dy)
                drag_data["x"] = event.x
                drag_data["y"] = event.y
                coords = canvas.coords(logo_item)
                if coords:
                    cx = max(0, int(coords[0] / scale_ratio))
                    cy = max(0, int(coords[1] / scale_ratio))
                    status_coord_lbl.configure(text=f"Logo Position -> X: {cx}px, Y: {cy}px", text_color=C_CYAN)

            def on_release(event):
                coords = canvas.coords(logo_item)
                if coords:
                    self.custom_logo_x = max(0, int(coords[0] / scale_ratio))
                    self.custom_logo_y = max(0, int(coords[1] / scale_ratio))
                    self.logo_position.set("Custom (Drag & Drop)")
                    status_coord_lbl.configure(text=f"✓ Saved Position -> X: {self.custom_logo_x}px, Y: {self.custom_logo_y}px", text_color=C_GREEN)
                    self.log(f"[logo-canvas] Saved custom logo coordinates: x={self.custom_logo_x}, y={self.custom_logo_y}")

            canvas.tag_bind(logo_item, "<Button-1>", on_press)
            canvas.tag_bind(logo_item, "<B1-Motion>", on_drag)
            canvas.tag_bind(logo_item, "<ButtonRelease-1>", on_release)

            btn_row = ctk.CTkFrame(win, fg_color="transparent")
            btn_row.pack(fill="x", padx=12, pady=(6, 12))

            def reset_top_right():
                self.custom_logo_x = None
                self.custom_logo_y = None
                self.logo_position.set("Top-Right")
                canvas.coords(logo_item, canvas_w - l_w_canvas - 20, 20)
                status_coord_lbl.configure(text="Reset to Top-Right Preset", text_color=C_MUTED)

            ctk.CTkButton(btn_row, text="💾 Save & Close", width=130, fg_color=C_PURPLE, hover_color=C_PURPLE_HOVER, command=win.destroy).pack(side="left", padx=(0, 8))
            ctk.CTkButton(btn_row, text="🔄 Reset (Top-Right)", width=140, fg_color=C_CARD, hover_color=C_CARD_HEADER, border_width=1, border_color=C_BORDER, command=reset_top_right).pack(side="left", padx=(0, 8))
            ctk.CTkButton(btn_row, text="👁 View Full WYSIWYG Preview", width=210, fg_color=C_AMBER, hover_color="#D97706", command=lambda: (win.destroy(), self.play_logo_caption_preview())).pack(side="right")
        except Exception as e:
            ctk.CTkLabel(win, text=f"Canvas preview error: {e}", text_color=C_RED).pack(pady=20)

    def _render_story_image_preview_frame(
        self, bg_image_path: str, out_img_path: str, target_w: int, target_h: int,
        enable_logo: bool, logo_path: str, logo_position: str, logo_width: int,
        custom_logo_x: Optional[int], custom_logo_y: Optional[int],
        enable_captions: bool, caption_text: str, caption_preset: str,
        caption_font: str, caption_size: int, caption_position: str,
        caption_case: str, caption_words_per_line: str,
        caption_lines: str = "1 Line (Standard)",
        custom_font_path: Optional[str] = None,
        custom_caption_y: Optional[int] = None
    ) -> str:
        """
        Pure PIL High-Definition WYSIWYG Composite Renderer for instant Logo & Subtitle Preview.
        Renders the exact background, scales & positions the logo, and styles CapCut captions.
        """
        os.makedirs(os.path.dirname(os.path.abspath(out_img_path)) or ".", exist_ok=True)
        from PIL import Image, ImageDraw, ImageFont, ImageOps

        # 1. Create Base Background Image
        if bg_image_path and os.path.exists(bg_image_path):
            try:
                base_img = Image.open(bg_image_path).convert("RGBA")
                base_img = ImageOps.fit(base_img, (target_w, target_h), method=Image.Resampling.LANCZOS)
            except Exception:
                base_img = Image.new("RGBA", (target_w, target_h), (16, 22, 35, 255))
        else:
            base_img = Image.new("RGBA", (target_w, target_h), (16, 22, 35, 255))

        # 2. Overlay Logo / Watermark
        if enable_logo and logo_path and os.path.exists(logo_path):
            try:
                logo_img = Image.open(logo_path).convert("RGBA")
                lw = max(30, min(target_w - 40, int(logo_width)))
                lh = int(logo_img.height * (lw / max(1, logo_img.width)))
                logo_img = logo_img.resize((lw, lh), Image.Resampling.LANCZOS)

                pos = logo_position.strip()
                if custom_logo_x is not None and custom_logo_y is not None and ("custom" in pos.lower() or pos == "Custom"):
                    lx, ly = int(custom_logo_x), int(custom_logo_y)
                elif pos == "Top-Left":
                    lx, ly = 30, 30
                elif pos == "Bottom-Right":
                    lx, ly = target_w - lw - 30, target_h - lh - 30
                elif pos == "Bottom-Left":
                    lx, ly = 30, target_h - lh - 30
                elif pos == "Center":
                    lx, ly = (target_w - lw) // 2, (target_h - lh) // 2
                elif "custom" in pos.lower():
                    lx = int(custom_logo_x) if custom_logo_x is not None else 30
                    ly = int(custom_logo_y) if custom_logo_y is not None else 30
                else:  # Top-Right default
                    lx, ly = target_w - lw - 30, 30

                base_img.paste(logo_img, (lx, ly), logo_img)
            except Exception as e:
                print(f"[PREVIEW] Logo composite error: {e}")

        # 3. Render CapCut Styled Subtitles
        if enable_captions and caption_text.strip():
            try:
                draw = ImageDraw.Draw(base_img)

                # Resolve font
                font_scale = target_w / 1280.0
                effective_size = max(18, int(caption_size * font_scale * 1.35))
                font_obj = None

                # Resolve TrueType font from Windows Fonts directory
                font_scale = target_w / 1280.0
                effective_size = max(24, int(caption_size * font_scale * 1.5))
                font_obj = None

                windir = os.environ.get("WINDIR", "C:\\Windows")
                font_candidates = []
                if custom_font_path and os.path.exists(custom_font_path):
                    font_candidates.append(custom_font_path)

                chosen_font_name = str(caption_font).lower()
                if "montserrat" in chosen_font_name:
                    font_candidates.extend([os.path.join(windir, "Fonts", "montserrat.ttf"), "montserrat.ttf"])
                elif "arial" in chosen_font_name:
                    font_candidates.extend([os.path.join(windir, "Fonts", "ariblk.ttf"), os.path.join(windir, "Fonts", "arialbd.ttf")])
                elif "roboto" in chosen_font_name:
                    font_candidates.extend([os.path.join(windir, "Fonts", "roboto.ttf"), "roboto.ttf"])

                # Standard high-visibility fallback fonts
                for fn in ("impact.ttf", "Impact.ttf", "ariblk.ttf", "arialbd.ttf", "segoeuib.ttf", "tahomabd.ttf", "arial.ttf"):
                    font_candidates.append(os.path.join(windir, "Fonts", fn))
                    font_candidates.append(fn)

                for cand in font_candidates:
                    try:
                        font_obj = ImageFont.truetype(cand, effective_size)
                        if font_obj:
                            break
                    except Exception:
                        continue

                if not font_obj:
                    try:
                        font_obj = ImageFont.truetype("arial.ttf", effective_size)
                    except Exception:
                        font_obj = ImageFont.load_default()

                # Text Casing
                raw_txt = caption_text.strip()
                if "all" in caption_case.lower() or "caps" in caption_case.lower():
                    disp_text = raw_txt.upper()
                elif "title" in caption_case.lower() or "first" in caption_case.lower():
                    disp_text = raw_txt.title()
                else:
                    disp_text = raw_txt

                def parse_max_words(val) -> int:
                    s = str(val).lower().strip()
                    if "1 word" in s or s == "1": return 1
                    elif "2 word" in s or s == "2": return 2
                    elif "3 word" in s or s == "3": return 3
                    elif "4 word" in s or s == "4": return 4
                    elif "5 word" in s or s == "5": return 5
                    elif "6 word" in s or s == "6": return 6
                    elif "7 word" in s or s == "7": return 7
                    elif "8 word" in s or s == "8": return 8
                    try:
                        import re
                        m = re.search(r'\d+', s)
                        if m: return max(1, min(50, int(m.group(0))))
                    except Exception: pass
                    return 4

                def parse_max_lines(val) -> int:
                    s = str(val).lower().strip()
                    if "2 line" in s or s == "2": return 2
                    elif "3 line" in s or s == "3": return 3
                    elif "4 line" in s or s == "4": return 4
                    try:
                        import re
                        m = re.search(r'\d+', s)
                        if m: return max(1, min(10, int(m.group(0))))
                    except Exception: pass
                    return 1

                words = disp_text.split()
                max_w = parse_max_words(caption_words_per_line)
                max_l = parse_max_lines(caption_lines)

                # Word Chunking into lines
                if len(words) > max_w:
                    all_lines = [" ".join(words[k:k+max_w]) for k in range(0, len(words), max_w)]
                else:
                    all_lines = [disp_text] if disp_text else []

                # CRUCIAL FIX: Live Preview displays ONLY 1 on-screen subtitle block (up to max_l lines)!
                # This prevents rendering 12 vertical lines overlapping the entire video frame.
                lines = all_lines[:max_l] if all_lines else [disp_text]

                # Style Preset Palette Colors
                p_lower = caption_preset.lower()
                if "yellow" in p_lower or "gold" in p_lower:
                    text_fill = (255, 230, 0, 255)
                elif "cyan" in p_lower or "teal" in p_lower or "neon" in p_lower:
                    text_fill = (0, 240, 255, 255)
                elif "pink" in p_lower or "magenta" in p_lower:
                    text_fill = (255, 46, 147, 255)
                elif "green" in p_lower or "emerald" in p_lower:
                    text_fill = (16, 185, 129, 255)
                elif "violet" in p_lower or "purple" in p_lower:
                    text_fill = (168, 85, 247, 255)
                elif "red" in p_lower:
                    text_fill = (239, 68, 68, 255)
                else:
                    text_fill = (255, 255, 255, 255)

                outline_fill = (0, 0, 0, 255)
                stroke_width = max(3, int(5 * font_scale))

                # Calculate Multi-line Bounding Box & Centering
                line_bboxes = []
                for l in lines:
                    try:
                        bbox = draw.textbbox((0, 0), l, font=font_obj)
                        line_bboxes.append(bbox)
                    except Exception:
                        line_bboxes.append((0, 0, len(l) * 20, 40))

                line_heights = [bb[3] - bb[1] for bb in line_bboxes]
                line_widths = [bb[2] - bb[0] for bb in line_bboxes]
                total_text_h = sum(line_heights) + (len(lines) - 1) * 12

                if custom_caption_y is not None:
                    curr_y = int(custom_caption_y)
                elif "top" in caption_position.lower():
                    curr_y = int(60 * font_scale)
                elif "middle" in caption_position.lower() or ("center" in caption_position.lower() and "bottom" not in caption_position.lower()):
                    curr_y = (target_h - total_text_h) // 2
                else:
                    # Bottom-Center default
                    curr_y = target_h - total_text_h - int(80 * font_scale)

                for l_idx, line in enumerate(lines):
                    lw = line_widths[l_idx]
                    lh = line_heights[l_idx]
                    curr_x = (target_w - lw) // 2

                    # Draw 3D Radial Embossed Shadow / Thick Outline
                    for ox in range(-stroke_width, stroke_width + 1, max(1, stroke_width // 2)):
                        for oy in range(-stroke_width, stroke_width + 1, max(1, stroke_width // 2)):
                            if ox != 0 or oy != 0:
                                draw.text((curr_x + ox, curr_y + oy), line, font=font_obj, fill=outline_fill)

                    # Draw Main Colored Text
                    draw.text((curr_x, curr_y), line, font=font_obj, fill=text_fill)
                    curr_y += lh + 12

            except Exception as e:
                print(f"[PREVIEW] Subtitle composite error: {e}")

        # 4. Save Final Composite Image
        final_rgb = base_img.convert("RGB")
        final_rgb.save(out_img_path, "JPEG", quality=95)
        return out_img_path

    def _show_preview_dialog(self, preview_path: str, display_w: int, display_h: int, target_w: int, target_h: int):
        top = ctk.CTkToplevel(self)
        top.title(f"👁 Live Logo & CapCut Caption Preview ({target_w}x{target_h})")
        top.geometry(f"{max(880, display_w + 60)}x{display_h + 170}")
        top.configure(fg_color=C_BG)
        top.grab_set()

        hdr = ctk.CTkFrame(top, fg_color=C_CARD, corner_radius=8, border_width=1, border_color=C_BORDER)
        hdr.pack(fill="x", padx=14, pady=(12, 6))

        preset_name = self.caption_preset.get()
        font_name = self.caption_font.get()
        fsize = int(self.caption_size.get())
        pos_name = self.caption_position.get().split("(")[0].strip()

        ctk.CTkLabel(hdr, text="  ✨ LIVE WYSIWYG PREVIEW", font=ctk.CTkFont(size=12, weight="bold"), text_color=C_CYAN).pack(side="left", padx=8, pady=6)

        badge_txt = f"📐 {target_w}x{target_h} • 🎨 Style: {preset_name} • 🔤 {font_name} ({fsize}pt) • 📍 {pos_name}"
        if self.enable_logo.get() and self.logo_entry.get().strip():
            badge_txt += f" • 📷 Logo: {int(self.logo_width_slider.get())}px ({self.logo_position.get()})"

        ctk.CTkLabel(hdr, text=badge_txt, font=ctk.CTkFont(size=10), text_color=C_MUTED).pack(side="left", padx=6)

        img_frame = ctk.CTkFrame(top, fg_color="#000000", corner_radius=8, border_width=1, border_color=C_BORDER)
        img_frame.pack(padx=14, pady=6, fill="both", expand=True)

        from PIL import Image
        pil_img = Image.open(preview_path).copy()
        ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(display_w, display_h))

        img_label = ctk.CTkLabel(img_frame, image=ctk_img, text="")
        img_label.image = ctk_img
        img_label.pack(expand=True, padx=8, pady=8)

        act_row = ctk.CTkFrame(top, fg_color="transparent")
        act_row.pack(fill="x", padx=14, pady=(6, 12))

        def refresh_cmd():
            top.destroy()
            self.play_logo_caption_preview()

        def open_external_cmd():
            if os.path.exists(preview_path):
                os.startfile(preview_path)

        ctk.CTkButton(act_row, text="🔄 Refresh Preview", width=140, fg_color=C_PURPLE, hover_color=C_PURPLE_HOVER, command=refresh_cmd).pack(side="left", padx=(0, 8))
        ctk.CTkButton(act_row, text="📂 Open Full-Res Image", width=170, fg_color=C_CARD, hover_color=C_CARD_HEADER, border_width=1, border_color=C_BORDER, command=open_external_cmd).pack(side="left", padx=(0, 8))
        ctk.CTkButton(act_row, text="❌ Close", width=100, fg_color=C_CARD, hover_color=C_CARD_HEADER, border_width=1, border_color=C_BORDER, command=top.destroy).pack(side="right")

    def play_logo_caption_preview(self):
        try:
            self.stop_preview()

            # 1. Determine background image from scene map or bulk images
            assigned_imgs = [p for p in self.scene_image_map.values() if p and os.path.exists(p)]
            if not assigned_imgs and self.bulk_images:
                assigned_imgs = [p for p in self.bulk_images if p and os.path.exists(p)]

            bg_image_path = assigned_imgs[0] if assigned_imgs else ""

            # 2. Determine sample text from actual user script if available
            sample_text = ""
            if self.parsed_scenes:
                sample_text = self.parsed_scenes[0].get("text", "")
            if not sample_text:
                raw_script = self.script_box.get("1.0", "end").strip()
                if raw_script:
                    for line in raw_script.splitlines():
                        line_clean = line.strip()
                        if line_clean and not line_clean.startswith("Scene_") and not line_clean.startswith("["):
                            sample_text = line_clean
                            break
            if not sample_text:
                sample_text = "CapCut Subtitle Preview: High Impact Visual Storytelling!"

            # 3. Determine resolution / aspect ratio
            res_str = self.video_res.get()
            aspect_str = self.aspect_ratio.get() if hasattr(self, "aspect_ratio") else "16:9"

            if "9:16" in aspect_str or "720x1280" in res_str or "1080x1920" in res_str:
                target_w, target_h = 720, 1280
                display_w, display_h = 320, 568
            elif "1:1" in aspect_str or "1080x1080" in res_str:
                target_w, target_h = 1080, 1080
                display_w, display_h = 460, 460
            else:
                target_w, target_h = 1280, 720
                display_w, display_h = 820, 461

            logo_p = self.logo_entry.get().strip()
            font_p = self.custom_font_entry.get().strip() if hasattr(self, "custom_font_entry") else ""
            fsize = int(self.caption_size.get())
            l_width = int(self.logo_width_slider.get())

            out_preview = os.path.join(self.preview_cache_dir, "logo_caption_live_preview.png")

            # 4. Generate accurate WYSIWYG preview frame (Captions ALWAYS TRUE in preview)
            preview_path = self._render_story_image_preview_frame(
                bg_image_path=bg_image_path,
                out_img_path=out_preview,
                target_w=target_w,
                target_h=target_h,
                enable_logo=bool(self.enable_logo.get()) or bool(logo_p and os.path.exists(logo_p)),
                logo_path=logo_p,
                logo_position=self.logo_position.get(),
                logo_width=l_width,
                custom_logo_x=self.custom_logo_x,
                custom_logo_y=self.custom_logo_y,
                enable_captions=True,
                caption_text=sample_text,
                caption_preset=self.caption_preset.get(),
                caption_font=self.caption_font.get(),
                caption_size=fsize,
                caption_position=self.caption_position.get(),
                caption_case=self.caption_case.get(),
                caption_words_per_line=self.caption_words_per_line.get(),
                caption_lines=self.caption_lines.get() if hasattr(self, "caption_lines") else "1 Line (Standard)",
                custom_font_path=font_p if font_p and os.path.exists(font_p) else None,
                custom_caption_y=self.custom_caption_y,
            )

            # 5. Open sleek modern in-app CTkToplevel preview dialog
            if os.path.exists(preview_path):
                self._show_preview_dialog(preview_path, display_w, display_h, target_w, target_h)
        except Exception as exc:
            messagebox.showerror("Preview Error", f"Could not render preview:\n{exc}")

    def burn_subtitles_standalone(self):
        ass_p = filedialog.askopenfilename(filetypes=[("ASS Subtitles", "*.ass")])
        if not ass_p: return
        vid_p = filedialog.askopenfilename(filetypes=[("Video files", "*.mp4 *.mov *.mkv")])
        if not vid_p: return

        out_p = os.path.splitext(vid_p)[0] + "_with_subtitles.mp4"

        def worker():
            try:
                import recap_engine_v2_8
                recap_engine_v2_8.burn_subtitles(vid_p, ass_p, out_p, render_preset="fast")
                self._post_ui(messagebox.showinfo, "Subtitles Burned!", f"Burned subtitles saved to:\n{out_p}")
                self._post_ui(self.log, f"[burn] Burned subtitles -> {out_p}")
            except Exception as e:
                self._post_ui(messagebox.showerror, "Burn Error", f"Failed burning subtitles:\n{e}")

        threading.Thread(target=worker, daemon=True).start()

    def run_project(self):
        if self.running:
            messagebox.showinfo("Build in Progress", "A story video build is already running. Please wait for it to finish.")
            return

        self.studio_tabs.set("🚀 3. Export & Batch Queue Manager")

        raw_script = self.script_box.get("1.0", "end").strip()
        if not raw_script:
            messagebox.showwarning("Script Missing", "Please paste or write a scene script in the Script Input box before exporting.")
            return

        if not self.parsed_scenes:
            self.parse_script_blocks()

        if not self.parsed_scenes:
            messagebox.showwarning("No Scenes Parsed", "No valid scene blocks found in script. Please format script with 'Scene_1_...' headers.")
            return

        key = self.api_key.get().strip()
        if not key:
            try:
                import voice_cache
                key = voice_cache.load_api_key() or ""
                if key:
                    self.api_key.delete(0, "end")
                    self.api_key.insert(0, key)
            except Exception:
                key = ""

        vid = self._selected_voice_id()
        if not vid:
            vid = "elevenlabs_21m00Tcm4TlvDq8ikWAM"

        out_path = self.output_path_entry.get().strip()
        if not out_path:
            out_path = os.path.abspath("final_story_image_video.mp4")
        out_path = os.path.abspath(out_path)

        intros_raw = self.intro_entry.get().strip()
        intro_list = [p.strip() for p in intros_raw.split(";") if p.strip()]

        bg_raw = self.bg_video_entry.get().strip() if hasattr(self, "bg_video_entry") else ""
        bg_list = [p.strip() for p in bg_raw.split(";") if p.strip()]
        bg_opacity = float(self.bg_opacity_slider.get()) / 100.0 if hasattr(self, "bg_opacity_slider") else 0.6

        font_p = self.custom_font_entry.get().strip()

        self.running = True
        self.progress_bar.set(0.05)
        self.run_btn.configure(state="disabled", text="GENERATING STORY VIDEO…")
        if hasattr(self, "top_export_btn"):
            self.top_export_btn.configure(state="disabled", text="GENERATING…")

        self.build_status.configure(text=f"Running • {len(self.parsed_scenes)} Scenes • Parallel Processing Active", text_color=C_PURPLE)
        self.log("=" * 72); self.log("Starting Story Image Video Build…")

        def worker():
            try:
                import importlib
                import story_image_engine
                importlib.reload(story_image_engine)
                from story_image_engine import build_story_image_project

                img_list = []
                if hasattr(self, "scene_image_map") and self.scene_image_map:
                    for sc in self.parsed_scenes:
                        s_no = sc["scene_no"]
                        if s_no in self.scene_image_map and os.path.exists(self.scene_image_map[s_no]):
                            img_list.append(self.scene_image_map[s_no])
                logo_file = self.logo_entry.get().strip() if hasattr(self, "logo_entry") else ""
                is_logo_enabled = bool(self.enable_logo.get()) if hasattr(self, "enable_logo") else False
                if logo_file and os.path.exists(logo_file):
                    is_logo_enabled = True

                is_caps_enabled = bool(self.enable_captions.get()) if hasattr(self, "enable_captions") else True

                out = build_story_image_project(
                    script_text_or_path=raw_script,
                    image_paths=img_list,
                    voice_id=vid,
                    tts_model_id=self.model_map.get(self.model_menu.get(), "eleven_multilingual_v2"),
                    elevenlabs_key=key,
                    out_path=out_path,
                    resolution=self.video_res.get(),
                    fps=30,
                    enable_logo=is_logo_enabled,
                    logo_path=logo_file,
                    logo_position=self.logo_position.get(),
                    logo_width=int(self.logo_width_slider.get()),
                    custom_logo_x=self.custom_logo_x,
                    custom_logo_y=self.custom_logo_y,
                    enable_captions=is_caps_enabled,
                    caption_preset=self.caption_preset.get(),
                    caption_font=self.caption_font.get(),
                    caption_case=self.caption_case.get(),
                    caption_words_per_line=self.caption_words_per_line.get(),
                    caption_lines=self.caption_lines.get() if hasattr(self, "caption_lines") else "1 Line (Standard)",
                    caption_position=self.caption_position.get(),
                    caption_size=self.caption_size.get(),
                    custom_font_path=font_p if font_p and os.path.exists(font_p) else None,
                    custom_caption_y=self.custom_caption_y,
                    motion_effect=self.camera_motion.get() if hasattr(self, "camera_motion") else "Auto-Director Flow (Dynamic Scenes)",
                    camera_motion=self.camera_motion.get() if hasattr(self, "camera_motion") else "Auto-Director Flow (Dynamic Scenes)",
                    enable_visualizer=bool(self.enable_visualizer.get()) if hasattr(self, "enable_visualizer") else False,
                    visualizer_path=self.visualizer_entry.get().strip() if hasattr(self, "visualizer_entry") and os.path.exists(self.visualizer_entry.get().strip()) else None,
                    visualizer_opacity=float(self.vis_opacity_slider.get()) / 100.0 if hasattr(self, "vis_opacity_slider") else 0.85,
                    enable_subscribe=bool(self.enable_subscribe.get()) if hasattr(self, "enable_subscribe") else False,
                    subscribe_path=self.subscribe_entry.get().strip() if hasattr(self, "subscribe_entry") and os.path.exists(self.subscribe_entry.get().strip()) else None,
                    subscribe_gap=int(re.search(r'\d+', self.subscribe_gap_menu.get()).group(0)) if hasattr(self, "subscribe_gap_menu") and re.search(r'\d+', self.subscribe_gap_menu.get()) else 35,
                    subscribe_width=int(re.search(r'\d+', self.subscribe_width_menu.get()).group(0)) if hasattr(self, "subscribe_width_menu") and re.search(r'\d+', self.subscribe_width_menu.get()) else 220,
                    bg_video_paths=bg_list,
                    bg_opacity=bg_opacity,
                    intro_video_paths=intro_list,
                    bgm_path=self.bgm_entry.get().strip() if hasattr(self, "bgm_entry") and os.path.exists(self.bgm_entry.get().strip()) else None,
                    bgm_volume=float(self.bgm_vol_slider.get()) / 100.0 if hasattr(self, "bgm_vol_slider") else 0.2,
                    voice_volume=float(self.voice_vol_slider.get()) / 100.0 if hasattr(self, "voice_vol_slider") else 1.0,
                    enable_ducking=bool(self.enable_ducking.get()) if hasattr(self, "enable_ducking") else True,
                    parallel_tts_workers=int(self.parallel_tts.get()) if hasattr(self, "parallel_tts") else 5,
                    parallel_video_workers=int(self.parallel_video.get()) if hasattr(self, "parallel_video") else 4,
                    log_callback=self.log
                )

                self._post_ui(self._build_success, out)
            except Exception as e:
                self._post_ui(self._build_failed, str(e), traceback.format_exc())

        threading.Thread(target=worker, daemon=True).start()

    def _build_success(self, out_path: str):
        self.running = False
        self.progress_bar.set(1.0)
        self.run_btn.configure(state="normal", text="⚡ GENERATE STORY IMAGE VIDEO NOW")
        if hasattr(self, "top_export_btn"):
            self.top_export_btn.configure(state="normal", text="⚡ EXPORT VIDEO NOW")
        self.build_status.configure(text=f"Success ✓ Video generated: {os.path.basename(out_path)}", text_color=C_GREEN)
        self.log(f"SUCCESS: Video exported to {out_path}")
        self._save_settings(silent=True)
        try:
            import auth_manager
            auth_manager.record_video_export(tool_name="Story Image Video", file_path=out_path)
        except Exception:
            pass

        # Trigger completion notification popup with chime sound
        try:
            import master_queue
            master_queue.show_video_completion_popup(
                parent=self,
                video_path=out_path,
                title="Story Image Video Created!"
            )
        except Exception:
            messagebox.showinfo("Video Created!", f"Story Image Video created successfully!\n\nSaved to:\n{out_path}")

    def _build_failed(self, err: str, tb: str):
        self.running = False
        self.progress_bar.set(0.0)
        self.run_btn.configure(state="normal", text="⚡ GENERATE STORY IMAGE VIDEO NOW")
        if hasattr(self, "top_export_btn"):
            self.top_export_btn.configure(state="normal", text="⚡ EXPORT VIDEO NOW")
        self.build_status.configure(text=f"Error: {err[:50]}", text_color=C_RED)
        self.log(f"ERROR: {err}\n{tb}")
        messagebox.showerror("Build Error", f"Story Image Video build failed:\n{err}")

    # -------------------------------------------------------------------------
    # BATCH PROJECT MASTER QUEUE INTEGRATION
    # -------------------------------------------------------------------------
    def add_current_to_queue(self):
        raw_script = self.script_box.get("1.0", "end").strip()
        if not raw_script:
            messagebox.showwarning("Script Required", "Please enter script text before adding to queue.")
            return

        if not self.parsed_scenes:
            self.parse_script_blocks()

        vid = self._selected_voice_id() or "elevenlabs_21m00Tcm4TlvDq8ikWAM"
        key = self.api_key.get().strip()

        out_path = self.output_path_entry.get().strip()
        if not out_path:
            out_path = os.path.abspath(f"story_video_queue_{int(time.time())}.mp4")
        out_path = os.path.abspath(out_path)

        intros_raw = self.intro_entry.get().strip() if hasattr(self, "intro_entry") else ""
        intro_list = [p.strip() for p in intros_raw.split(";") if p.strip()]

        bg_raw = self.bg_video_entry.get().strip() if hasattr(self, "bg_video_entry") else ""
        bg_list = [p.strip() for p in bg_raw.split(";") if p.strip()]
        bg_opacity = float(self.bg_opacity_slider.get()) / 100.0 if hasattr(self, "bg_opacity_slider") else 0.6

        font_p = self.custom_font_entry.get().strip() if hasattr(self, "custom_font_entry") else ""

        img_list = []
        if hasattr(self, "scene_image_map") and self.scene_image_map:
            for sc in self.parsed_scenes:
                s_no = sc["scene_no"]
                if s_no in self.scene_image_map and os.path.exists(self.scene_image_map[s_no]):
                    img_list.append(self.scene_image_map[s_no])
        if not img_list:
            img_list = list(self.bulk_images)

        task_title = f"Story: {len(self.parsed_scenes)} Scenes ({self.video_res.get().split()[0]})"

        # Capture frozen copy of current settings for execution
        params = {
            "script_text_or_path": raw_script,
            "image_paths": list(img_list),
            "voice_id": vid,
            "tts_model_id": self.model_map.get(self.model_menu.get(), "eleven_multilingual_v2"),
            "elevenlabs_key": key,
            "out_path": out_path,
            "resolution": self.video_res.get(),
            "fps": 30,
            "enable_logo": bool(self.enable_logo.get()),
            "logo_path": self.logo_entry.get().strip(),
            "logo_position": self.logo_position.get(),
            "logo_width": int(self.logo_width_slider.get()),
            "custom_logo_x": self.custom_logo_x,
            "custom_logo_y": self.custom_logo_y,
            "enable_captions": bool(self.enable_captions.get()),
            "caption_preset": self.caption_preset.get(),
            "caption_font": self.caption_font.get(),
            "caption_case": self.caption_case.get(),
            "caption_words_per_line": self.caption_words_per_line.get(),
            "caption_lines": self.caption_lines.get() if hasattr(self, "caption_lines") else "1 Line (Standard)",
            "caption_position": self.caption_position.get(),
            "caption_size": self.caption_size.get(),
            "custom_font_path": font_p if font_p and os.path.exists(font_p) else None,
            "custom_caption_y": self.custom_caption_y,
            "camera_motion": self.camera_motion.get() if hasattr(self, "camera_motion") else "Auto-Director Flow (Dynamic Scenes)",
            "motion_effect": self.camera_motion.get() if hasattr(self, "camera_motion") else "Auto-Director Flow (Dynamic Scenes)",
            "enable_visualizer": bool(self.enable_visualizer.get()) if hasattr(self, "enable_visualizer") else False,
            "visualizer_path": self.visualizer_entry.get().strip() if hasattr(self, "visualizer_entry") and os.path.exists(self.visualizer_entry.get().strip()) else None,
            "visualizer_opacity": float(self.vis_opacity_slider.get()) / 100.0 if hasattr(self, "vis_opacity_slider") else 0.85,
            "enable_subscribe": bool(self.enable_subscribe.get()) if hasattr(self, "enable_subscribe") else False,
            "subscribe_path": self.subscribe_entry.get().strip() if hasattr(self, "subscribe_entry") and os.path.exists(self.subscribe_entry.get().strip()) else None,
            "subscribe_gap": int(re.search(r'\d+', self.subscribe_gap_menu.get()).group(0)) if hasattr(self, "subscribe_gap_menu") and re.search(r'\d+', self.subscribe_gap_menu.get()) else 35,
            "subscribe_width": int(re.search(r'\d+', self.subscribe_width_menu.get()).group(0)) if hasattr(self, "subscribe_width_menu") and re.search(r'\d+', self.subscribe_width_menu.get()) else 220,
            "bg_video_paths": bg_list,
            "bg_opacity": bg_opacity,
            "intro_video_paths": intro_list,
            "bgm_path": self.bgm_entry.get().strip() if hasattr(self, "bgm_entry") and os.path.exists(self.bgm_entry.get().strip()) else None,
            "bgm_volume": float(self.bgm_vol_slider.get()) / 100.0 if hasattr(self, "bgm_vol_slider") else 0.2,
            "voice_volume": float(self.voice_vol_slider.get()) / 100.0 if hasattr(self, "voice_vol_slider") else 1.0,
            "enable_ducking": bool(self.enable_ducking.get()) if hasattr(self, "enable_ducking") else True,
            "parallel_tts_workers": int(self.parallel_tts.get()) if hasattr(self, "parallel_tts") else 5,
            "parallel_video_workers": int(self.parallel_video.get()) if hasattr(self, "parallel_video") else 4,
        }

        def execute_story_job(progress_cb, status_cb):
            import story_image_engine
            def _log_forwarder(msg):
                clean_msg = str(msg).strip()
                status_cb(clean_msg)
                try:
                    import re
                    m = re.search(r'(\d+)\s*%', clean_msg)
                    if m:
                        progress_cb(float(m.group(1)))
                except Exception:
                    pass
            params["log_callback"] = _log_forwarder
            return story_image_engine.build_story_image_project(**params)

        try:
            import master_queue
            task = master_queue.MASTER_QUEUE.add_task(
                title=task_title,
                tool_name="Story Image Video",
                execute_fn=execute_story_job,
                output_path=out_path,
                payload=params
            )
            self.log(f"[queue] Added job '{task.title}' to Master Queue (ID: {task.id})")
            # Auto-clear the current tab so it is completely fresh for the next video!
            self.reset_tab_form()
            messagebox.showinfo(
                "Task Added to Master Queue",
                f"✓ '{task_title}' has been sent to the Master Render Queue!\n\n"
                f"• Tab form has been reset fresh for your next video.\n"
                f"• Check the '🗂 Queue' tab for live rendering progress."
            )
        except Exception as e:
            messagebox.showerror("Queue Error", f"Failed to add task to Master Queue:\n{e}")

    def reset_tab_form(self):
        """Clears all inputs and parsed scenes so the tab is 100% clean and ready for the next video."""
        try:
            self.script_box.delete("1.0", "end")
            self.parsed_scenes = []
            self.bulk_images = []
            self.scene_image_map = {}
            for w in self.scene_tree.winfo_children():
                try:
                    w.destroy()
                except Exception:
                    pass
            placeholder = ctk.CTkLabel(
                self.scene_tree,
                text="Paste script and click '⚡ Parse Scenes' to load storyboard inspector.",
                font=ctk.CTkFont(size=11),
                text_color=C_MUTED
            )
            placeholder.pack(pady=40)
            self.parse_badge.configure(text="0 Scenes Parsed", text_color=C_MUTED)
            if hasattr(self, "status_bar_lbl"):
                self.status_bar_lbl.configure(text="● Auto Save Enabled  |  Scenes: 0  |  Status: Ready for new video")
            self.log("[workspace] Form cleared — Ready for new video!")
        except Exception as e:
            self.log(f"[workspace] Form reset error: {e}")

    def _render_queue_list(self):
        for w in self.queue_container.winfo_children():
            w.destroy()

        if not self.project_queue:
            ctk.CTkLabel(self.queue_container, text="No batch projects in queue", font=ctk.CTkFont(size=10), text_color=C_MUTED).pack(pady=6)
            return

        for idx, item in enumerate(self.project_queue):
            row = ctk.CTkFrame(self.queue_container, fg_color=C_CARD_HEADER, corner_radius=5)
            row.pack(fill="x", padx=2, pady=2)
            
            ctk.CTkLabel(row, text=f"#{idx+1} {item['name']}", font=ctk.CTkFont(size=10, weight="bold"), text_color=C_TEXT).pack(side="left", padx=6)
            ctk.CTkLabel(row, text=f"{item['resolution'].split()[0]}", font=ctk.CTkFont(size=9), text_color=C_CYAN).pack(side="left", padx=4)
            
            del_btn = ctk.CTkButton(row, text="✕", width=22, height=22, fg_color=C_RED, hover_color="#DC2626", command=lambda i=idx: self._delete_queue_item(i))
            del_btn.pack(side="right", padx=4)

    def _delete_queue_item(self, idx: int):
        if 0 <= idx < len(self.project_queue):
            del self.project_queue[idx]
            self._render_queue_list()

    def clear_queue(self):
        self.project_queue.clear()
        self._render_queue_list()

    def process_queue(self):
        if not self.project_queue:
            messagebox.showinfo("Empty Queue", "No batch projects in queue to process.")
            return

        if self.running:
            messagebox.showinfo("Build in Progress", "A project build is already running.")
            return

        self.running = True
        self.run_btn.configure(state="disabled", text="PROCESSING QUEUE…")

        def worker():
            import story_image_engine
            tot = len(self.project_queue)
            for idx, item in enumerate(list(self.project_queue)):
                self._post_ui(self.build_status.configure, {"text": f"Batch Queue ({idx+1}/{tot}): {item['name']}"})
                self.log(f"[queue] Processing item {idx+1}/{tot}: {item['name']}")
                try:
                    story_image_engine.build_story_image_project(
                        script_text_or_path=item["script"],
                        image_paths=self.bulk_images,
                        voice_id=item["voice_id"],
                        tts_model_id=self.model_map.get(self.model_menu.get(), "eleven_multilingual_v2"),
                        elevenlabs_key=item["api_key"],
                        out_path=item["out_path"],
                        resolution=item["resolution"],
                        fps=30,
                        enable_logo=bool(self.enable_logo.get()),
                        logo_path=self.logo_entry.get().strip(),
                        enable_captions=bool(self.enable_captions.get()),
                        caption_preset=self.caption_preset.get(),
                        caption_font=self.caption_font.get(),
                        caption_size=self.caption_size.get(),
                        motion_effect=self.motion_effect.get(),
                        log_callback=self.log
                    )
                    self.log(f"[queue] Finished #{idx+1} -> {item['out_path']}")
                except Exception as e:
                    self.log(f"[queue] Failed #{idx+1}: {e}")

            self._post_ui(self.clear_queue)
            self._post_ui(self._build_success, "Batch Queue Finished")

        threading.Thread(target=worker, daemon=True).start()

    def _collect_settings(self) -> dict:
        try:
            return {
                "api_key": self.api_key.get().strip() if hasattr(self, "api_key") else "",
                "model": self.model_menu.get() if hasattr(self, "model_menu") else "",
                "voice_id": self.voice_id.get().strip() if hasattr(self, "voice_id") else "",
                "parallel_tts": int(self.parallel_tts.get()) if hasattr(self, "parallel_tts") else 2,
                "parallel_video": int(self.parallel_video.get()) if hasattr(self, "parallel_video") else 2,
                "video_res": self.video_res.get() if hasattr(self, "video_res") else "1080p",
                "aspect_ratio": self.aspect_ratio.get() if hasattr(self, "aspect_ratio") else "16:9",
                "render_quality": self.render_quality.get() if hasattr(self, "render_quality") else "High (CRF 18)",
                "video_fps": self.video_fps.get() if hasattr(self, "video_fps") else "30 fps",
                "enable_logo": bool(self.enable_logo.get()) if hasattr(self, "enable_logo") else False,
                "logo_path": self.logo_entry.get().strip() if hasattr(self, "logo_entry") else "",
                "logo_position": self.logo_position.get() if hasattr(self, "logo_position") else "Top Right",
                "logo_width": int(self.logo_width_slider.get()) if hasattr(self, "logo_width_slider") else 120,
                "enable_captions": bool(self.enable_captions.get()) if hasattr(self, "enable_captions") else True,
                "caption_preset": self.caption_preset.get() if hasattr(self, "caption_preset") else "Yellow Highlight (Karaoke)",
                "caption_font": self.caption_font.get() if hasattr(self, "caption_font") else "Impact",
                "caption_case": self.caption_case.get() if hasattr(self, "caption_case") else "UPPERCASE",
                "caption_words_per_line": self.caption_words_per_line.get() if hasattr(self, "caption_words_per_line") else "4 Words",
                "caption_lines": self.caption_lines.get() if hasattr(self, "caption_lines") else "1 Line (Standard)",
                "caption_position": self.caption_position.get() if hasattr(self, "caption_position") else "Bottom (Center)",
                "caption_size": int(self.caption_size.get()) if hasattr(self, "caption_size") else 54,
                "custom_font": self.custom_font_entry.get().strip() if hasattr(self, "custom_font_entry") else "",
                "camera_motion": self.camera_motion.get() if hasattr(self, "camera_motion") else "🌟 Auto-Director Flow (Dynamic Scenes)",
                "enable_visualizer": bool(self.enable_visualizer.get()) if hasattr(self, "enable_visualizer") else False,
                "visualizer_path": self.visualizer_entry.get().strip() if hasattr(self, "visualizer_entry") else "",
                "visualizer_opacity": int(self.vis_opacity_slider.get()) if hasattr(self, "vis_opacity_slider") else 85,
                "enable_subscribe": bool(self.enable_subscribe.get()) if hasattr(self, "enable_subscribe") else False,
                "subscribe_path": self.subscribe_entry.get().strip() if hasattr(self, "subscribe_entry") else "",
                "subscribe_gap": self.subscribe_gap_menu.get() if hasattr(self, "subscribe_gap_menu") else "35s Gap",
                "subscribe_width": self.subscribe_width_menu.get() if hasattr(self, "subscribe_width_menu") else "220px",
                "bg_opacity": int(self.bg_opacity_slider.get()) if hasattr(self, "bg_opacity_slider") else 100,
                "bgm_volume": int(self.bgm_vol_slider.get()) if hasattr(self, "bgm_vol_slider") else 15,
                "voice_volume": int(self.voice_vol_slider.get()) if hasattr(self, "voice_vol_slider") else 100,
                "enable_ducking": bool(self.enable_ducking.get()) if hasattr(self, "enable_ducking") else True,
                "output_path": self.output_path_entry.get().strip() if hasattr(self, "output_path_entry") else ""
            }
        except Exception as e:
            print("[story_image_video] _collect_settings error:", e)
            return {}

    def _apply_settings(self, st: dict):
        if not st: return
        try:
            if "api_key" in st and st["api_key"] and hasattr(self, "api_key"):
                self.api_key.delete(0, "end"); self.api_key.insert(0, st["api_key"])
            if "model" in st and st["model"] and hasattr(self, "model_menu"):
                try: self.model_menu.set(st["model"])
                except Exception: pass
            if "voice_id" in st and st["voice_id"] and hasattr(self, "voice_id"):
                self.voice_id.delete(0, "end"); self.voice_id.insert(0, st["voice_id"])
            if "video_res" in st and hasattr(self, "video_res"):
                try: self.video_res.set(st["video_res"])
                except Exception: pass
            if "aspect_ratio" in st and hasattr(self, "aspect_ratio"):
                try: self.aspect_ratio.set(st["aspect_ratio"])
                except Exception: pass
            if "camera_motion" in st and hasattr(self, "camera_motion"):
                try: self.camera_motion.set(st["camera_motion"])
                except Exception: pass
            elif "motion_effect" in st and hasattr(self, "camera_motion"):
                try: self.camera_motion.set(st["motion_effect"])
                except Exception: pass
            if "enable_visualizer" in st and hasattr(self, "enable_visualizer"):
                try:
                    if st["enable_visualizer"]: self.enable_visualizer.select()
                    else: self.enable_visualizer.deselect()
                except Exception: pass
            if "visualizer_path" in st and hasattr(self, "visualizer_entry"):
                try:
                    self.visualizer_entry.delete(0, "end")
                    self.visualizer_entry.insert(0, st["visualizer_path"])
                except Exception: pass
            if "enable_subscribe" in st and hasattr(self, "enable_subscribe"):
                try:
                    if st["enable_subscribe"]: self.enable_subscribe.select()
                    else: self.enable_subscribe.deselect()
                except Exception: pass
            if "subscribe_path" in st and hasattr(self, "subscribe_entry"):
                try:
                    self.subscribe_entry.delete(0, "end")
                    self.subscribe_entry.insert(0, st["subscribe_path"])
                except Exception: pass
            if "caption_preset" in st and hasattr(self, "caption_preset"):
                try: self.caption_preset.set(st["caption_preset"])
                except Exception: pass
            if "caption_font" in st and hasattr(self, "caption_font"):
                try: self.caption_font.set(st["caption_font"])
                except Exception: pass
            if "caption_size" in st and hasattr(self, "caption_size"):
                try: self.caption_size.set(st["caption_size"])
                except Exception: pass
            if "enable_logo" in st and hasattr(self, "enable_logo"):
                try:
                    if st.get("enable_logo", True): self.enable_logo.select()
                    else: self.enable_logo.deselect()
                except Exception: pass
            if "logo_path" in st and st["logo_path"] and hasattr(self, "logo_entry"):
                self.logo_entry.delete(0, "end"); self.logo_entry.insert(0, st["logo_path"])
                if os.path.exists(st["logo_path"]) and hasattr(self, "enable_logo"):
                    self.enable_logo.select()
            if "enable_captions" in st and hasattr(self, "enable_captions"):
                try:
                    if st.get("enable_captions", True): self.enable_captions.select()
                    else: self.enable_captions.deselect()
                except Exception: pass
            else:
                if hasattr(self, "enable_captions"):
                    self.enable_captions.select()
            if "bgm_volume" in st and hasattr(self, "bgm_vol_slider"):
                try: self.bgm_vol_slider.set(st["bgm_volume"])
                except Exception: pass
            if "voice_volume" in st and hasattr(self, "voice_vol_slider"):
                try: self.voice_vol_slider.set(st["voice_volume"])
                except Exception: pass
            if "output_path" in st and st["output_path"] and hasattr(self, "output_path_entry"):
                self.output_path_entry.delete(0, "end"); self.output_path_entry.insert(0, st["output_path"])
            self.log("[preset] Applied settings successfully ✓")
        except Exception as e:
            self.log(f"[preset] Apply settings warning: {e}")

    def _save_settings(self, silent: bool = False):
        try:
            st = self._collect_settings()
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(st, f, indent=2)
            preset_manager.save_last_settings("story_image_video", st)
            if not silent:
                self.log("[settings] Saved workspace settings ✓")
        except Exception as e:
            if not silent:
                self.log(f"[settings] Save warning: {e}")

    def _load_settings(self):
        try:
            st = preset_manager.load_last_settings("story_image_video")
            if not st and os.path.exists(self.settings_path):
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    st = json.load(f)
            if st:
                self._apply_settings(st)
                self.log("[settings] Loaded workspace settings ✓")
        except Exception as e:
            self.log(f"[settings] Load warning: {e}")
