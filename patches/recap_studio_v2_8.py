#!/usr/bin/env python3
"""Recap Studio V2.8 — Single-Page Dashboard with AI33 Voice Library & Parallel Render Engine."""
from __future__ import annotations

import os
import json
import hashlib
import faulthandler
import platform
import subprocess
import threading
import traceback
import queue
import sys
import shutil
import re
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

# Native-crash diagnostics (e.g. Windows 0xC0000005 / Tk crashes).
_FAULT_LOG_HANDLE = None
try:
    _fault_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recap_studio_native_crash.log")
    _FAULT_LOG_HANDLE = open(_fault_path, "a", encoding="utf-8", buffering=1)
    _FAULT_LOG_HANDLE.write("\n" + "=" * 80 + "\n")
    _FAULT_LOG_HANDLE.write(datetime.now().isoformat() + "  Recap Studio V2.8 startup\n")
    faulthandler.enable(_FAULT_LOG_HANDLE, all_threads=True)
except Exception:
    _FAULT_LOG_HANDLE = None

try:
    import customtkinter as ctk
except ImportError as exc:
    raise SystemExit("Missing dependency. Run: pip install customtkinter") from exc

from recap_engine_v2_8 import (
    build_project,
    check_ffmpeg,
    fetch_elevenlabs_models,
    fetch_elevenlabs_voices,
    generate_music,
    generate_tts,
    apply_narration_speed,
    render_audio_preview,
    prepare_bgm_playlist,
    validate_plan_against_script,
)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

LANG_OPTIONS = ["Auto / mixed", "English", "Hindi", "Hinglish", "Spanish", "Other"]


class RecapStudioV2(ctk.CTk):
    def __init__(self):
        if _FAULT_LOG_HANDLE:
            _FAULT_LOG_HANDLE.write("before CTk.__init__\n")
        super().__init__()
        if _FAULT_LOG_HANDLE:
            _FAULT_LOG_HANDLE.write("after CTk.__init__\n")
        self.title("Recap Studio V2.8 — Single-Page AI33 Dashboard")
        self.geometry("1280x880")
        self.minsize(1080, 720)
        self.models = []
        self.voices = []
        self.model_map = {}
        self.voice_map = {}
        self.model_languages = {}
        self.running = False
        self.generated_bgm_path = ""
        self.bgm_files = []
        self.uploaded_voiceover_files = []
        appdata = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or os.path.join(str(Path.home()), ".recap_studio")
        self.settings_dir = os.path.join(appdata, "StoriesStudio", "RecapStudio")
        os.makedirs(self.settings_dir, exist_ok=True)
        self.settings_path = os.path.join(self.settings_dir, "settings_v2_8.json")
        self.preview_cache_dir = os.path.join(self.settings_dir, ".preview_cache")
        os.makedirs(self.preview_cache_dir, exist_ok=True)
        self.ui_queue = queue.Queue()
        self.log_path = os.path.join(self.settings_dir, "recap_studio_build.log")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_header()
        if _FAULT_LOG_HANDLE:
            _FAULT_LOG_HANDLE.write("header built\n")
        self._build_single_page_dashboard()
        if _FAULT_LOG_HANDLE:
            _FAULT_LOG_HANDLE.write("dashboard built\n")
        self._load_env()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(75, self._drain_ui_queue)
        self.after(250, self._check_env)

    def _build_header(self):
        f = ctk.CTkFrame(self, corner_radius=0)
        f.grid(row=0, column=0, sticky="ew")
        f.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(f, text="RECAP STUDIO V2.8 — AI33 DASHBOARD", font=ctk.CTkFont(size=23, weight="bold")).grid(
            row=0, column=0, padx=22, pady=(12, 2), sticky="w")
        ctk.CTkLabel(
            f,
            text="Single-Page Control • AI33 Voice Library • Voice Preview • Parallel TTS & Video Render • Render Video vs Movie",
            text_color=("gray35", "gray70"),
        ).grid(row=1, column=0, padx=22, pady=(0, 10), sticky="w")
        self.env_status = ctk.CTkLabel(f, text="Checking FFmpeg…")
        self.env_status.grid(row=0, column=1, rowspan=2, padx=22, sticky="e")

    def _section(self, parent, title, badge_color="#6366F1", expanded: bool = True):
        outer = ctk.CTkFrame(parent, fg_color="#181B2A", corner_radius=14, border_width=1, border_color="#2E334D")
        outer.pack(fill="x", padx=8, pady=8)
        outer.grid_columnconfigure(0, weight=1)

        # Header Bar (Clickable)
        header = ctk.CTkFrame(outer, fg_color="#222538", corner_radius=10, cursor="hand2")
        header.grid(row=0, column=0, padx=8, pady=8, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        pill = ctk.CTkFrame(header, fg_color=badge_color, width=10, height=18, corner_radius=4)
        pill.grid(row=0, column=0, padx=(10, 6), pady=8)

        lbl = ctk.CTkLabel(header, text=title, font=ctk.CTkFont(size=14, weight="bold"), text_color="#F3F4F6")
        lbl.grid(row=0, column=1, padx=4, pady=8, sticky="w")

        toggle_lbl = ctk.CTkLabel(header, text="▼ Collapse" if expanded else "▲ Expand Section",
                                   font=ctk.CTkFont(size=11, weight="bold"),
                                   text_color="#9CA3AF" if expanded else "#6366F1")
        toggle_lbl.grid(row=0, column=2, padx=12, pady=8, sticky="e")

        # Card Body
        body = ctk.CTkFrame(outer, fg_color="transparent")
        body.grid_columnconfigure(1, weight=1)

        state = {"is_expanded": expanded}

        def toggle_card(_event=None):
            if state["is_expanded"]:
                body.grid_forget()
                toggle_lbl.configure(text="▲ Expand Section", text_color="#6366F1")
                state["is_expanded"] = False
            else:
                body.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="ew")
                toggle_lbl.configure(text="▼ Collapse", text_color="#9CA3AF")
                state["is_expanded"] = True

        header.bind("<Button-1>", toggle_card)
        lbl.bind("<Button-1>", toggle_card)
        pill.bind("<Button-1>", toggle_card)
        toggle_lbl.bind("<Button-1>", toggle_card)

        if expanded:
            body.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="ew")

        return body

    def _build_single_page_dashboard(self):
        # Outer Container
        main_box = ctk.CTkFrame(self, fg_color="transparent")
        main_box.grid(row=1, column=0, padx=12, pady=8, sticky="nsew")
        main_box.grid_columnconfigure(0, weight=1)
        main_box.grid_rowconfigure(0, weight=1)

        # Scrollable Dashboard
        self.scroll_frame = ctk.CTkScrollableFrame(main_box, label_text="")
        self.scroll_frame.grid(row=0, column=0, sticky="nsew")
        self.scroll_frame.grid_columnconfigure(0, weight=1)
        self.scroll_frame.grid_columnconfigure(1, weight=1)

        # ---------------------------------------------------------------------
        # LEFT COLUMN: AI33 API & Voice Settings
        # ---------------------------------------------------------------------
        left_col = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        left_col.grid(row=0, column=0, padx=8, pady=4, sticky="nsew")

        # 1. API & Preferences Card
        api_card = self._section(left_col, "AI33 API & Saved Preferences", badge_color="#6366F1")
        ctk.CTkLabel(api_card, text="API Key").grid(row=1, column=0, padx=14, pady=6, sticky="w")
        
        api_key_row = ctk.CTkFrame(api_card, fg_color="transparent")
        api_key_row.grid(row=1, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")
        api_key_row.grid_columnconfigure(0, weight=1)

        self.api_key = ctk.CTkEntry(api_key_row, show="•", placeholder_text="Paste AI33 / XI API key once")
        self.api_key.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        
        self.show_key_btn = ctk.CTkButton(api_key_row, text="👁 Show Key", width=95, command=self.toggle_show_api_key)
        self.show_key_btn.grid(row=0, column=1, padx=(0, 6))

        self.fetch_btn = ctk.CTkButton(api_key_row, text="Connect & Auto Fetch", width=150, fg_color="#6366F1", hover_color="#4F46E5", command=self.fetch_api)
        self.fetch_btn.grid(row=0, column=2)

        self.remember_api = ctk.CTkCheckBox(api_card, text="Remember API key on this PC")
        self.remember_api.grid(row=2, column=1, padx=4, pady=(0, 6), sticky="w")
        self.remember_api.select()

        pref_btns = ctk.CTkFrame(api_card, fg_color="transparent")
        pref_btns.grid(row=3, column=1, columnspan=2, padx=4, pady=(0, 6), sticky="w")
        ctk.CTkButton(pref_btns, text="Save Preferences", width=120, command=self._save_settings).pack(side="left")
        ctk.CTkButton(pref_btns, text="Clear Saved", width=100, fg_color="transparent", border_width=1,
                      command=self._clear_saved_settings).pack(side="left", padx=8)

        self.api_status = ctk.CTkLabel(api_card, text="Not connected", text_color=("gray40", "gray65"))
        self.api_status.grid(row=4, column=1, columnspan=2, padx=4, pady=(0, 8), sticky="w")

        # 2. Voiceover Source Card
        source_card = self._section(left_col, "Voiceover Source Mode", badge_color="#3B82F6", expanded=False)
        ctk.CTkLabel(source_card, text="Source Mode").grid(row=1, column=0, padx=14, pady=6, sticky="w")
        self.voiceover_mode = ctk.CTkSegmentedButton(
            source_card, values=["Generate Voiceover", "Upload Voiceover"], command=self._voiceover_mode_changed
        )
        self.voiceover_mode.grid(row=1, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")
        self.voiceover_mode.set("Generate Voiceover")

        ctk.CTkLabel(source_card, text="Uploaded Audio").grid(row=2, column=0, padx=14, pady=6, sticky="w")
        upload_wrap = ctk.CTkFrame(source_card, fg_color="transparent")
        upload_wrap.grid(row=2, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")
        upload_wrap.grid_columnconfigure(0, weight=1)
        self.upload_voice_summary = ctk.CTkLabel(upload_wrap, text="No voiceover uploaded", anchor="w")
        self.upload_voice_summary.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 4))
        self.upload_voice_btn = ctk.CTkButton(upload_wrap, text="Choose Voiceover File(s)", command=self.choose_uploaded_voiceover)
        self.upload_voice_btn.grid(row=1, column=0, padx=(0, 6), sticky="w")
        self.clear_voice_upload_btn = ctk.CTkButton(upload_wrap, text="Clear", fg_color="transparent", border_width=1, command=self.clear_uploaded_voiceover)
        self.clear_voice_upload_btn.grid(row=1, column=1, padx=6, sticky="w")
        self.upload_voice_count = ctk.CTkLabel(upload_wrap, text="0 files")
        self.upload_voice_count.grid(row=1, column=2, sticky="e")

        # 3. AI33 Voice Selector Card
        voice_card = self._section(left_col, "AI33 Voice Selector (ElevenLabs, Minimax, Vbee, Fish, Cloned)", badge_color="#8B5CF6", expanded=True)
        
        ctk.CTkLabel(voice_card, text="Provider Filter").grid(row=1, column=0, padx=14, pady=6, sticky="w")
        self.provider_filter_btn = ctk.CTkSegmentedButton(
            voice_card,
            values=["All", "ElevenLabs", "Minimax", "Vbee", "Fish", "Cloned"],
            command=self._on_provider_filter_changed
        )
        self.provider_filter_btn.grid(row=1, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")
        self.provider_filter_btn.set("All")

        ctk.CTkLabel(voice_card, text="TTS Model").grid(row=2, column=0, padx=14, pady=6, sticky="w")
        self.model_combo = ctk.CTkComboBox(voice_card, values=["Connect API first"], state="readonly", command=self._model_changed)
        self.model_combo.grid(row=2, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")

        ctk.CTkLabel(voice_card, text="Voice Search").grid(row=3, column=0, padx=14, pady=6, sticky="w")
        search_row = ctk.CTkFrame(voice_card, fg_color="transparent")
        search_row.grid(row=3, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")
        search_row.grid_columnconfigure(0, weight=1)
        self.voice_search = ctk.CTkEntry(search_row, placeholder_text="Search voice by NAME or VOICE ID")
        self.voice_search.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.voice_search.bind("<KeyRelease>", lambda _e: self._filter_voices())
        ctk.CTkButton(search_row, text="Search", width=75, command=self._filter_voices).grid(row=0, column=1, padx=2)
        ctk.CTkButton(search_row, text="Clear", width=65, fg_color="transparent", border_width=1, command=self._clear_voice_search).grid(row=0, column=2, padx=(2, 0))

        ctk.CTkLabel(voice_card, text="Voice Selection").grid(row=4, column=0, padx=14, pady=6, sticky="w")
        voice_select_row = ctk.CTkFrame(voice_card, fg_color="transparent")
        voice_select_row.grid(row=4, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")
        voice_select_row.grid_columnconfigure(0, weight=1)
        self.voice_combo = ctk.CTkComboBox(voice_select_row, values=["Connect API first"], state="readonly", command=self._voice_changed)
        self.voice_combo.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.play_voice_preview_btn = ctk.CTkButton(voice_select_row, text="▶ Play Voice Preview", width=145, fg_color="#8B5CF6", hover_color="#7C3AED", command=self.play_voice_preview)
        self.play_voice_preview_btn.grid(row=0, column=1, sticky="e")

        ctk.CTkLabel(voice_card, text="Voice ID").grid(row=5, column=0, padx=14, pady=6, sticky="w")
        self.voice_id = ctk.CTkEntry(voice_card, placeholder_text="Auto-filled or paste Voice ID")
        self.voice_id.grid(row=5, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")

        ctk.CTkLabel(voice_card, text="Narration Language").grid(row=6, column=0, padx=14, pady=6, sticky="w")
        self.output_language = ctk.CTkComboBox(voice_card, values=LANG_OPTIONS, state="readonly", command=self._model_changed)
        self.output_language.grid(row=6, column=1, padx=4, pady=6, sticky="ew")
        self.output_language.set("English")
        self.language_status = ctk.CTkLabel(voice_card, text="Script text controls spoken language")
        self.language_status.grid(row=6, column=2, padx=14, pady=6, sticky="e")

        self.voice_search_status = ctk.CTkLabel(voice_card, text="Cached voices load automatically after API fetch", text_color=("gray40", "gray65"))
        self.voice_search_status.grid(row=7, column=1, columnspan=2, padx=(4, 14), pady=(0, 8), sticky="w")

        # 4. Parallel Workers & Speed Controls Card
        adv_card = self._section(left_col, "Parallel Audio Workers & Speed Controls", badge_color="#EC4899", expanded=False)
        ctk.CTkLabel(adv_card, text="Parallel Audio Workers").grid(row=1, column=0, padx=14, pady=6, sticky="w")
        self.parallel_tts = ctk.CTkSlider(adv_card, from_=1, to=10, number_of_steps=9, command=lambda v: self.parallel_tts_label.configure(text=f"{int(v)} workers"))
        self.parallel_tts.grid(row=1, column=1, padx=4, pady=6, sticky="ew")
        self.parallel_tts.set(3)
        self.parallel_tts_label = ctk.CTkLabel(adv_card, text="3 workers", width=75)
        self.parallel_tts_label.grid(row=1, column=2, padx=14)

        ctk.CTkLabel(adv_card, text="Stability").grid(row=2, column=0, padx=14, pady=6, sticky="w")
        self.stability = ctk.CTkSlider(adv_card, from_=0.0, to=1.0, number_of_steps=20, command=lambda v: self.stability_label.configure(text=f"{v:.2f}"))
        self.stability.grid(row=2, column=1, padx=4, pady=6, sticky="ew")
        self.stability.set(0.5)
        self.stability_label = ctk.CTkLabel(adv_card, text="0.50", width=55)
        self.stability_label.grid(row=2, column=2, padx=14)

        ctk.CTkLabel(adv_card, text="Similarity").grid(row=3, column=0, padx=14, pady=6, sticky="w")
        self.similarity = ctk.CTkSlider(adv_card, from_=0.0, to=1.0, number_of_steps=20, command=lambda v: self.similarity_label.configure(text=f"{v:.2f}"))
        self.similarity.grid(row=3, column=1, padx=4, pady=6, sticky="ew")
        self.similarity.set(0.75)
        self.similarity_label = ctk.CTkLabel(adv_card, text="0.75", width=55)
        self.similarity_label.grid(row=3, column=2, padx=14)

        ctk.CTkLabel(adv_card, text="Narration Speed").grid(row=4, column=0, padx=14, pady=6, sticky="w")
        self.narration_speed = ctk.CTkSlider(adv_card, from_=0.90, to=1.20, number_of_steps=30, command=lambda v: self.narration_speed_label.configure(text=f"{v:.2f}x"))
        self.narration_speed.grid(row=4, column=1, padx=4, pady=6, sticky="ew")
        self.narration_speed.set(1.05)
        self.narration_speed_label = ctk.CTkLabel(adv_card, text="1.05x", width=55)
        self.narration_speed_label.grid(row=4, column=2, padx=14)

        ctk.CTkLabel(adv_card, text="Render Speed").grid(row=5, column=0, padx=14, pady=(6, 12), sticky="w")
        self.render_speed = ctk.CTkComboBox(adv_card, values=["Fast (recommended)", "Turbo", "Balanced"], state="readonly")
        self.render_speed.grid(row=5, column=1, padx=4, pady=(6, 12), sticky="ew")
        self.render_speed.set("Fast (recommended)")
        ctk.CTkLabel(adv_card, text="CRF 18", width=75).grid(row=5, column=2, padx=14)

        # ---------------------------------------------------------------------
        # RIGHT COLUMN: Project Files, Positioning & BGM Mixer
        # ---------------------------------------------------------------------
        right_col = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        right_col.grid(row=0, column=1, padx=8, pady=4, sticky="nsew")

        # 1. Project Files Card
        proj_card = self._section(right_col, "Project Input Files", badge_color="#0EA5E9", expanded=True)
        ctk.CTkLabel(proj_card, text="Source Story Language").grid(row=1, column=0, padx=14, pady=6, sticky="w")
        self.source_language = ctk.CTkComboBox(proj_card, values=LANG_OPTIONS, state="readonly")
        self.source_language.grid(row=1, column=1, padx=4, pady=6, sticky="ew")
        self.source_language.set("Auto / mixed")

        self.video_entry = self._file_row(proj_card, 2, "Source Video", self._choose_video, "Original video (.mp4/.mkv)")
        self.script_entry = self._file_row(proj_card, 3, "Rewritten Script", self._choose_script, "Narration script (.txt)")
        self.plan_entry = self._file_row(proj_card, 4, "Edit Plan JSON", self._choose_plan, "ChatGPT edit plan (.json)")
        self.logo_entry = self._file_row(proj_card, 5, "Logo (optional)", self._choose_logo, "PNG/JPG watermark")
        self.bgm_entry = self._file_row(proj_card, 6, "BGM / Playlist", self.choose_existing_bgm, "Audio track(s)")
        self.output_entry = self._file_row(proj_card, 7, "Final Output", self._choose_output, "Output MP4 path")

        ctk.CTkLabel(proj_card, text="Cache Folder").grid(row=8, column=0, padx=14, pady=6, sticky="w")
        cache_wrap = ctk.CTkFrame(proj_card, fg_color="transparent")
        cache_wrap.grid(row=8, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")
        cache_wrap.grid_columnconfigure(0, weight=1)
        self.cache_entry = ctk.CTkEntry(cache_wrap, placeholder_text="Automatic if blank")
        self.cache_entry.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        ctk.CTkButton(cache_wrap, text="Browse", width=75, command=self._choose_cache).grid(row=0, column=1, padx=2)
        ctk.CTkButton(cache_wrap, text="🗑 Clear Cache", width=105, fg_color="#EF4444", hover_color="#DC2626", command=self._clear_cache).grid(row=0, column=2, padx=(2, 0))

        validate_btns = ctk.CTkFrame(proj_card, fg_color="transparent")
        validate_btns.grid(row=9, column=1, columnspan=2, padx=4, pady=(6, 10), sticky="w")
        ctk.CTkButton(validate_btns, text="Validate Script + JSON", fg_color="#0EA5E9", hover_color="#0284C7", command=self.validate).pack(side="left")
        ctk.CTkButton(validate_btns, text="🗑 Clear Project Cache", fg_color="#EF4444", hover_color="#DC2626", command=self._clear_cache).pack(side="left", padx=8)
        self.validation = ctk.CTkLabel(validate_btns, text="")
        self.validation.pack(side="left", padx=6)

        # 2. Logo & CapCut Subtitle Customization Card
        logo_card = self._section(right_col, "Logo Watermark & CapCut Subtitles Customization", badge_color="#F59E0B", expanded=True)
        
        toggles_row = ctk.CTkFrame(logo_card, fg_color="transparent")
        toggles_row.grid(row=1, column=0, columnspan=3, padx=14, pady=6, sticky="w")
        
        self.enable_logo = ctk.CTkCheckBox(toggles_row, text="Enable Logo Watermark")
        self.enable_logo.pack(side="left", padx=(0, 14))
        self.enable_logo.select()

        self.enable_captions = ctk.CTkCheckBox(toggles_row, text="Enable Subtitles / Captions")
        self.enable_captions.pack(side="left", padx=14)
        self.enable_captions.select()

        ctk.CTkLabel(logo_card, text="Logo Position").grid(row=2, column=0, padx=14, pady=6, sticky="w")
        self.logo_position = ctk.CTkComboBox(logo_card, values=["Top-Right", "Top-Left", "Bottom-Right", "Bottom-Left", "Center", "Custom (Drag & Drop)"], state="readonly")
        self.logo_position.grid(row=2, column=1, padx=4, pady=6, sticky="ew")
        self.logo_position.set("Top-Right")

        ctk.CTkButton(logo_card, text="📐 Drag & Stretch Logo", width=160, fg_color="#F59E0B", hover_color="#D97706", command=self.open_logo_canvas_editor).grid(row=2, column=2, padx=(4, 14), pady=6, sticky="e")

        ctk.CTkLabel(logo_card, text="Logo Width / Size").grid(row=3, column=0, padx=14, pady=6, sticky="w")
        self.logo_width_slider = ctk.CTkSlider(logo_card, from_=50, to=500, number_of_steps=45, command=lambda v: self.logo_width_label.configure(text=f"{int(v)}px"))
        self.logo_width_slider.grid(row=3, column=1, padx=4, pady=6, sticky="ew")
        self.logo_width_slider.set(200)
        self.logo_width_label = ctk.CTkLabel(logo_card, text="200px", width=55)
        self.logo_width_label.grid(row=3, column=2, padx=14)

        ctk.CTkLabel(logo_card, text="Caption Style").grid(row=4, column=0, padx=14, pady=6, sticky="w")
        self.caption_preset = ctk.CTkComboBox(logo_card, values=["CapCut Yellow Pop", "CapCut Neon Cyan", "Karaoke Highlight Yellow", "Classic White Shadow", "Modern Box Subtitle"], state="readonly")
        self.caption_preset.grid(row=4, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")
        self.caption_preset.set("CapCut Yellow Pop")

        ctk.CTkLabel(logo_card, text="Caption Font").grid(row=5, column=0, padx=14, pady=6, sticky="w")
        self.caption_font = ctk.CTkComboBox(logo_card, values=["Impact", "Arial Black", "Montserrat", "Verdana", "Trebuchet MS", "Segoe UI", "Tahoma"], state="readonly")
        self.caption_font.grid(row=5, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")
        self.caption_font.set("Impact")

        ctk.CTkLabel(logo_card, text="Custom Font File").grid(row=6, column=0, padx=14, pady=6, sticky="w")
        font_wrap = ctk.CTkFrame(logo_card, fg_color="transparent")
        font_wrap.grid(row=6, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")
        font_wrap.grid_columnconfigure(0, weight=1)
        self.custom_font_entry = ctk.CTkEntry(font_wrap, placeholder_text="Optional .ttf / .otf custom font file")
        self.custom_font_entry.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        ctk.CTkButton(font_wrap, text="Browse", width=75, command=self._choose_custom_font).grid(row=0, column=1)

        ctk.CTkLabel(logo_card, text="Caption Font Size").grid(row=7, column=0, padx=14, pady=6, sticky="w")
        self.caption_size_slider = ctk.CTkSlider(logo_card, from_=10, to=60, number_of_steps=50, command=lambda v: self.caption_size_label.configure(text=f"{int(v)}pt"))
        self.caption_size_slider.grid(row=7, column=1, padx=4, pady=6, sticky="ew")
        self.caption_size_slider.set(28)
        self.caption_size_label = ctk.CTkLabel(logo_card, text="28pt", width=55)
        self.caption_size_label.grid(row=7, column=2, padx=14)

        ctk.CTkLabel(logo_card, text="Caption Position").grid(row=8, column=0, padx=14, pady=6, sticky="w")
        self.caption_position = ctk.CTkComboBox(logo_card, values=["Bottom-Center (CapCut Default)", "Top-Center", "Middle-Center"], state="readonly")
        self.caption_position.grid(row=8, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")
        self.caption_position.set("Bottom-Center (CapCut Default)")

        ctk.CTkLabel(logo_card, text="Text Casing").grid(row=9, column=0, padx=14, pady=6, sticky="w")
        self.caption_case = ctk.CTkComboBox(logo_card, values=["ALL CAPS", "First Letter Capital", "Normal"], state="readonly")
        self.caption_case.grid(row=9, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")
        self.caption_case.set("ALL CAPS")

        ctk.CTkLabel(logo_card, text="Word Gap / Words Per Line").grid(row=10, column=0, padx=14, pady=6, sticky="w")
        self.caption_words_per_line = ctk.CTkComboBox(logo_card, values=["1 Word (CapCut Pop)", "2 Words (TikTok)", "3 Words", "5 Words", "7 Words", "Auto (10 words)"], state="readonly")
        self.caption_words_per_line.grid(row=10, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")
        self.caption_words_per_line.set("1 Word (CapCut Pop)")

        preview_row = ctk.CTkFrame(logo_card, fg_color="transparent")
        preview_row.grid(row=11, column=1, columnspan=2, padx=4, pady=(6, 10), sticky="w")
        ctk.CTkButton(preview_row, text="👁 Live Logo & Caption Preview", fg_color="#8B5CF6", hover_color="#7C3AED", command=self.play_logo_caption_preview).pack(side="left")

        # 3. Render Output Mode Card
        render_card = self._section(right_col, "Render Mode: Render Video OR Render Movie", badge_color="#10B981", expanded=True)
        ctk.CTkLabel(render_card, text="Output Mode").grid(row=1, column=0, padx=14, pady=6, sticky="w")
        self.render_mode = ctk.CTkSegmentedButton(render_card, values=["Render Video", "Render Movie"], command=self._render_mode_changed)
        self.render_mode.grid(row=1, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")
        self.render_mode.set("Render Video")

        self.intro_entry = self._file_row(render_card, 2, "Upload Intro(s)", self._choose_intros, "Intro video(s) for Render Movie mode")
        ctk.CTkLabel(render_card, text="Movie Length").grid(row=3, column=0, padx=14, pady=(6, 10), sticky="w")
        self.movie_duration = ctk.CTkComboBox(render_card, values=["1 Hour (3600s)", "2 Hours (7200s)", "3 Hours (10800s)", "4 Hours (14400s)"], state="readonly")
        self.movie_duration.grid(row=3, column=1, padx=4, pady=(6, 10), sticky="ew")
        self.movie_duration.set("1 Hour (3600s)")

        # 4. BGM & Volume Mixer Card
        bgm_card = self._section(right_col, "BGM Music & Volume Balance", badge_color="#14B8A6", expanded=False)

        self.enable_bgm = ctk.CTkCheckBox(bgm_card, text="Enable Background Music (BGM)")
        self.enable_bgm.grid(row=1, column=0, columnspan=3, padx=14, pady=6, sticky="w")
        self.enable_bgm.select()

        ctk.CTkLabel(bgm_card, text="BGM Playlist / Tracks").grid(row=2, column=0, padx=14, pady=6, sticky="nw")
        pl_wrap = ctk.CTkFrame(bgm_card, fg_color="transparent")
        pl_wrap.grid(row=2, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")
        self.bgm_playlist_summary = ctk.CTkLabel(pl_wrap, text="No tracks selected", anchor="w")
        self.bgm_playlist_summary.pack(side="top", fill="x", pady=(0, 4))
        ctk.CTkButton(pl_wrap, text="Choose / Upload BGM", width=140, command=self.choose_existing_bgm).pack(side="left")
        ctk.CTkButton(pl_wrap, text="Add More", width=90, fg_color="transparent", border_width=1, command=self.add_existing_bgm).pack(side="left", padx=6)
        ctk.CTkButton(pl_wrap, text="Clear", width=70, fg_color="transparent", border_width=1, command=self.clear_bgm_playlist).pack(side="left", padx=4)
        self.playlist_count = ctk.CTkLabel(pl_wrap, text="0 tracks")
        self.playlist_count.pack(side="right")

        self.bgm_loop = ctk.CTkCheckBox(bgm_card, text="Loop BGM playlist until video ends")
        self.bgm_loop.grid(row=3, column=1, columnspan=2, padx=4, pady=6, sticky="w")
        self.bgm_loop.select()

        ctk.CTkLabel(bgm_card, text="Voice Volume").grid(row=6, column=0, padx=14, pady=6, sticky="w")
        v_vol = ctk.CTkFrame(bgm_card, fg_color="transparent")
        v_vol.grid(row=6, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")
        self.voice_volume = ctk.CTkSlider(v_vol, from_=0.50, to=1.50, number_of_steps=40, command=lambda v: self.voice_volume_label.configure(text=f"{v:.0%}"))
        self.voice_volume.pack(side="left", fill="x", expand=True)
        self.voice_volume.set(1.00)
        self.voice_volume_label = ctk.CTkLabel(v_vol, text="100%", width=50)
        self.voice_volume_label.pack(side="left", padx=(8, 0))

        ctk.CTkLabel(bgm_card, text="BGM Volume").grid(row=7, column=0, padx=14, pady=6, sticky="w")
        bg_vol = ctk.CTkFrame(bgm_card, fg_color="transparent")
        bg_vol.grid(row=7, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")
        self.bgm_volume = ctk.CTkSlider(bg_vol, from_=0.00, to=0.40, number_of_steps=80, command=lambda v: self.bgm_volume_label.configure(text=f"{v:.0%}"))
        self.bgm_volume.pack(side="left", fill="x", expand=True)
        self.bgm_volume.set(0.08)
        self.bgm_volume_label = ctk.CTkLabel(bg_vol, text="8%", width=50)
        self.bgm_volume_label.pack(side="left", padx=(8, 0))

        bgm_btns = ctk.CTkFrame(bgm_card, fg_color="transparent")
        bgm_btns.grid(row=8, column=1, columnspan=2, padx=(4, 14), pady=(6, 12), sticky="ew")
        self.generate_bgm_btn = ctk.CTkButton(bgm_btns, text="Generate BGM", command=self.generate_bgm)
        self.generate_bgm_btn.pack(side="left")
        self.preview_btn = ctk.CTkButton(bgm_btns, text="▶ Preview Volume Mix", command=self.preview_mix)
        self.preview_btn.pack(side="left", padx=8)
        ctk.CTkButton(bgm_btns, text="■ Stop Preview", fg_color="transparent", border_width=1, command=self.stop_preview).pack(side="left", padx=4)

        self.bgm_status = ctk.CTkLabel(bgm_card, text="No BGM selected", text_color=("gray40", "gray65"))
        self.bgm_status.grid(row=9, column=1, columnspan=2, padx=4, pady=(0, 8), sticky="w")

        # ---------------------------------------------------------------------
        # BOTTOM SECTION: Build Execution & Live Log Box
        # ---------------------------------------------------------------------
        build_card = ctk.CTkFrame(self, corner_radius=6)
        build_card.grid(row=2, column=0, padx=16, pady=(4, 12), sticky="ew")
        build_card.grid_columnconfigure(1, weight=1)

        self.run_btn = ctk.CTkButton(
            build_card, text="▶  RUN / RESUME PROJECT", height=44,
            font=ctk.CTkFont(size=15, weight="bold"), command=self.run_project
        )
        self.run_btn.grid(row=0, column=0, padx=14, pady=12)

        self.build_status = ctk.CTkLabel(build_card, text="Ready", font=ctk.CTkFont(weight="bold"))
        self.build_status.grid(row=0, column=1, padx=8, sticky="w")

        ctk.CTkButton(build_card, text="Open Output Folder", fg_color="transparent", border_width=1, command=self.open_output_folder).grid(row=0, column=2, padx=14)

        self.log_box = ctk.CTkTextbox(build_card, height=130)
        self.log_box.grid(row=1, column=0, columnspan=3, padx=14, pady=(0, 12), sticky="ew")
        self.log_box.insert("end", "Dashboard ready. Auto-fetch API key and voices, select project files, then RUN.\n")
        self.log_box.configure(state="disabled")

        self._voiceover_mode_changed(self.voiceover_mode.get())
        self._render_mode_changed(self.render_mode.get())

    def toggle_show_api_key(self):
        if self.api_key.cget("show") == "•":
            self.api_key.configure(show="")
            self.show_key_btn.configure(text="🙈 Hide Key")
        else:
            self.api_key.configure(show="•")
            self.show_key_btn.configure(text="👁 Show Key")

    def _file_row(self, parent, row, label, command, hint):
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, padx=14, pady=6, sticky="w")
        e = ctk.CTkEntry(parent, placeholder_text=hint)
        e.grid(row=row, column=1, padx=4, pady=6, sticky="ew")
        ctk.CTkButton(parent, text="Browse", width=85, command=command).grid(row=row, column=2, padx=14, pady=6)
        return e

    def _set_path(self, entry, p):
        entry.delete(0, "end")
        entry.insert(0, p)

    def _choose_video(self):
        p = filedialog.askopenfilename(filetypes=[("Video", "*.mp4 *.mkv *.mov *.avi *.webm"), ("All files", "*.*")])
        if p: self._set_path(self.video_entry, p)

    def _choose_script(self):
        p = filedialog.askopenfilename(filetypes=[("Text", "*.txt"), ("All files", "*.*")])
        if p: self._set_path(self.script_entry, p)

    def _choose_plan(self):
        p = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("Text", "*.txt"), ("All files", "*.*")])
        if p: self._set_path(self.plan_entry, p)

    def _choose_logo(self):
        p = filedialog.askopenfilename(filetypes=[("Image", "*.png *.jpg *.jpeg *.webp"), ("All files", "*.*")])
        if p: self._set_path(self.logo_entry, p)

    def _choose_custom_font(self):
        p = filedialog.askopenfilename(filetypes=[("Font files", "*.ttf *.otf *.woff *.woff2"), ("All files", "*.*")])
        if p: self._set_path(self.custom_font_entry, p)

    def _choose_output(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4", filetypes=[("MP4", "*.mp4")], initialfile="final_recap.mp4")
        if p: self._set_path(self.output_entry, p)

    def _choose_cache(self):
        p = filedialog.askdirectory(title="Choose project cache folder")
        if p: self._set_path(self.cache_entry, p)

    def _clear_cache(self):
        cache_dir = self.cache_entry.get().strip() if hasattr(self, "cache_entry") else ""
        out_path = self.output_entry.get().strip() if hasattr(self, "output_entry") else ""
        
        target_dirs = []
        if cache_dir and os.path.exists(cache_dir):
            target_dirs.append(cache_dir)
        elif out_path:
            out_abs = os.path.abspath(out_path)
            base_dir = os.path.dirname(out_abs)
            base_name = os.path.splitext(os.path.basename(out_abs))[0]
            def_cache = os.path.join(base_dir, f".{base_name}_recap_cache")
            if os.path.exists(def_cache):
                target_dirs.append(def_cache)
        
        prev_cache = getattr(self, "preview_cache_dir", os.path.abspath(".preview_cache"))
        if os.path.exists(prev_cache):
            target_dirs.append(prev_cache)

        if not target_dirs:
            messagebox.showinfo("Clear Cache", "No project cache or preview cache directory found to clear.")
            return

        confirm = messagebox.askyesno(
            "Clear Cache Confirmation",
            "Are you sure you want to delete all cached audio and video files in:\n\n" + "\n".join(target_dirs) + "\n\nThis will force a fresh generation on the next run."
        )
        if not confirm:
            return

        cleared_count = 0
        for d in target_dirs:
            try:
                for root, dirs, files in os.walk(d):
                    for f in files:
                        try:
                            os.remove(os.path.join(root, f))
                            cleared_count += 1
                        except Exception:
                            pass
            except Exception:
                pass

        messagebox.showinfo("Clear Cache", f"Cache cleared successfully!\nRemoved {cleared_count} cached file(s).")
        if hasattr(self, "validation"):
            self.validation.configure(text=f"Cache cleared ({cleared_count} files removed)")

    def _choose_intros(self):
        paths = filedialog.askopenfilenames(
            title="Choose Intro video file(s)",
            filetypes=[("Video", "*.mp4 *.mkv *.mov *.avi *.webm"), ("All files", "*.*")]
        )
        if paths:
            self._set_path(self.intro_entry, "; ".join(paths))

    def _render_mode_changed(self, value=None):
        mode = (value or self.render_mode.get()).strip()
        is_movie = mode == "Render Movie"
        state = "normal" if is_movie else "disabled"
        try:
            self.intro_entry.configure(state=state)
            self.movie_duration.configure(state="readonly" if is_movie else "disabled")
        except Exception:
            pass

    def validate(self):
        script = self.script_entry.get().strip()
        plan = self.plan_entry.get().strip()
        if not script or not plan:
            messagebox.showwarning("Validate", "Choose rewritten script and edit plan first.")
            return
        try:
            info = validate_plan_against_script(plan, script)
            txt = f"{info['segments']} beats • {info['shots']} shots • {info['script_lines']} lines"
            if info["strict_ok"] and info["same_count"]:
                txt += f" • PRO CHECK ✓ • gap ≥ {info['min_source_gap_seconds']:.1f}s"
                if info["found_character_intros"]:
                    txt += f" • {len(info['found_character_intros'])} intros"
            else:
                problems = []
                if not info["same_count"]: problems.append("line count")
                if info["gap_violations"]: problems.append(f"{len(info['gap_violations'])} gap")
                if info["repeat_violations"]: problems.append(f"{len(info['repeat_violations'])} repeat")
                if info["missing_character_intros"]: problems.append("missing intros")
                txt += " • CHECK FAILED: " + ", ".join(problems)
            self.validation.configure(text=txt)
        except Exception as e:
            self.validation.configure(text="Invalid")
            messagebox.showerror("Edit plan", str(e))

    def fetch_api(self):
        key = self.api_key.get().strip()
        if not key:
            messagebox.showwarning("AI33 API", "Enter your API key first.")
            return
        self.fetch_btn.configure(state="disabled", text="Fetching…")
        self.api_status.configure(text="Connecting to AI33 API…")

        def worker():
            try:
                from ai33_api import AI33Client
                client = AI33Client(api_key=key)
                voices_resp = client.fetch_voices()
                if isinstance(voices_resp, list):
                    fetched_voices = voices_resp
                elif isinstance(voices_resp, dict):
                    fetched_voices = voices_resp.get("voices", []) or voices_resp.get("data", [])
                else:
                    fetched_voices = []

                fetched_models = client.fetch_models()
                self._post_ui(self._apply_api, fetched_models, fetched_voices)
            except Exception as e:
                self._post_ui(self._api_error, str(e))
        threading.Thread(target=worker, daemon=True).start()

    def play_voice_preview(self):
        vdisplay = self.voice_combo.get().strip()
        vid = self.voice_map.get(vdisplay, self.voice_id.get().strip())
        if not vid:
            messagebox.showwarning("Voice Preview", "Select or enter a Voice ID first.")
            return

        preview_url = ""
        for v in self.voices:
            if v.get("voice_id") == vid or (v.get("name") and v.get("name") in vdisplay):
                preview_url = v.get("preview_url", "")
                break

        if not preview_url:
            preview_url = f"https://api.ai33.pro/previews/{vid}.mp3"

        self.api_status.configure(text=f"Playing voice preview for {vid}…")

        def worker():
            try:
                sample_path = os.path.join(self.preview_cache_dir, f"voice_sample_{vid.replace('/', '_')}.mp3")
                if not os.path.exists(sample_path):
                    from ai33_api import AI33Client
                    client = AI33Client(api_key=self.api_key.get().strip() or "demo")
                    try:
                        client.download_file(preview_url, sample_path)
                    except Exception:
                        key = self.api_key.get().strip()
                        if key:
                            generate_tts("Hello, this is a sample preview of this voice.", vid,
                                         self._selected_model_id(), key, sample_path)
                if os.path.exists(sample_path):
                    self._post_ui(self._play_preview_file, sample_path)
                else:
                    self._post_ui(self.api_status.configure, text=f"Voice sample ready for {vid}")
            except Exception as e:
                self._post_ui(self._preview_failed, f"Voice preview failed: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _apply_api(self, models, voices, cached=False):
        self.models, self.voices = models or [], voices or []
        self.model_map = {}
        self.model_languages = {}
        for m in self.models:
            mid = m.get("model_id") or m.get("id") or ""
            display = f"{m.get('name', mid)} [{mid}]"
            self.model_map[display] = mid

        self.voice_map = {}
        for v in self.voices:
            vid = v.get("voice_id") or v.get("id") or ""
            if not vid: continue
            provider = v.get("provider", "AI33")
            name = v.get("name", "Unnamed")
            category = v.get("category", "Voice")
            display = f"[{provider}] {name} ({category}) • {vid}"
            self.voice_map[display] = vid

        mvals = list(self.model_map) or ["Eleven Multilingual V2 [eleven_multilingual_v2]"]
        vvals = list(self.voice_map) or ["No voices loaded"]
        self.model_combo.configure(values=mvals)
        self.voice_combo.configure(values=vvals)

        target_model = self._restore_model_id or "eleven_multilingual_v2"
        preferred = next((d for d, mid in self.model_map.items() if mid == target_model), mvals[0])
        self.model_combo.set(preferred)

        target_voice = self._restore_voice_id or self.voice_id.get().strip()
        vdisplay = next((d for d, vid in self.voice_map.items() if vid == target_voice), vvals[0])
        self.voice_combo.set(vdisplay)

        if vdisplay in self.voice_map:
            self._voice_changed(vdisplay)
        elif target_voice:
            self.voice_id.delete(0, "end")
            self.voice_id.insert(0, target_voice)

        self._model_changed(preferred)
        self.fetch_btn.configure(state="normal", text="Refresh")

        if cached:
            self.voice_search_status.configure(text=f"Loaded {len(self.voices)} cached voices")
            self.api_status.configure(text="Cached voices & models loaded")
        else:
            self.voice_search_status.configure(text=f"{len(self.voices)} fetched voices ready")
            self.api_status.configure(text=f"Connected • {len(self.models)} models • {len(self.voices)} voices loaded")
            self._restore_model_id = self._selected_model_id()
            self._restore_voice_id = self.voice_id.get().strip()
            self._save_settings(silent=True)

    def _api_error(self, msg):
        self.fetch_btn.configure(state="normal", text="Connect & Fetch")
        self.api_status.configure(text="Connection failed — retry is safe")
        messagebox.showerror("AI33 API Error", msg)

    def _on_provider_filter_changed(self, value=None):
        self._filter_voices()

    def _filter_voices(self):
        if not self.voice_map:
            return
        q = self.voice_search.get().strip().lower()
        prov_filter = self.provider_filter_btn.get() if hasattr(self, "provider_filter_btn") else "All"

        filtered_items = {}
        for d, vid in self.voice_map.items():
            # Check provider match
            if prov_filter != "All":
                p_tag = f"[{prov_filter}]".lower()
                id_tag = f"{prov_filter.lower()}_"
                if p_tag not in d.lower() and not str(vid).lower().startswith(id_tag):
                    continue

            # Check query match
            if q:
                if q not in d.lower() and q not in str(vid).lower():
                    continue

            filtered_items[d] = vid

        vals = list(filtered_items.keys())
        if vals:
            self.voice_combo.configure(values=vals)
            self.voice_combo.set(vals[0])
            self._voice_changed(vals[0])
            self.voice_search_status.configure(text=f"Showing {len(vals)} voice(s) [{prov_filter}]")
        else:
            all_vals = list(self.voice_map.keys())
            self.voice_combo.configure(values=all_vals if all_vals else ["No voices loaded"])
            self.voice_search_status.configure(text=f"No voices matched filter '[{prov_filter}]'. Showing all available voices.")
            if all_vals and all_vals[0] in self.voice_map:
                self._voice_changed(all_vals[0])

    def _clear_voice_search(self):
        self.voice_search.delete(0, "end")
        if hasattr(self, "provider_filter_btn"):
            self.provider_filter_btn.set("All")
        self._filter_voices()

    def _voice_changed(self, display):
        vid = self.voice_map.get(display, "")
        if vid:
            self.voice_id.delete(0, "end")
            self.voice_id.insert(0, vid)

    def _selected_model_id(self):
        d = self.model_combo.get().strip()
        return self.model_map.get(d, d if d.startswith("eleven_") or d.startswith("minimax_") else "eleven_multilingual_v2")

    def _model_changed(self, _=None):
        lang = self.output_language.get().strip().lower() if hasattr(self, "output_language") else ""
        mid = self._selected_model_id() if hasattr(self, "model_combo") else ""
        if lang in {"auto / mixed", "hinglish", "other", ""}:
            self.language_status.configure(text="Script text controls spoken language")
            return
        langs = self.model_languages.get(mid, [])
        if not langs:
            self.language_status.configure(text="Check model language support")
        elif any(lang in x for x in langs):
            self.language_status.configure(text="Model lists this language ✓")
        else:
            self.language_status.configure(text="Language supported ✓")

    def _voiceover_mode_changed(self, value=None):
        mode = (value or self.voiceover_mode.get()).strip()
        upload = mode == "Upload Voiceover"
        state_upload = "normal" if upload else "disabled"
        try:
            self.upload_voice_btn.configure(state=state_upload)
            self.clear_voice_upload_btn.configure(state=state_upload)
        except Exception: pass
        gen_state = "readonly" if not upload else "disabled"
        try:
            self.model_combo.configure(state=gen_state)
            self.voice_combo.configure(state=gen_state)
            self.voice_id.configure(state="normal" if not upload else "disabled")
            self.voice_search.configure(state="normal" if not upload else "disabled")
            self.stability.configure(state="normal" if not upload else "disabled")
            self.similarity.configure(state="normal" if not upload else "disabled")
        except Exception: pass
        if upload:
            self.language_status.configure(text="Uploaded audio controls language")
        else:
            self._model_changed()

    def choose_uploaded_voiceover(self):
        paths = filedialog.askopenfilenames(
            title="Choose voiceover file(s)",
            filetypes=[("Audio", "*.mp3 *.wav *.m4a *.aac *.flac *.ogg"), ("All files", "*.*")]
        )
        if paths:
            self.uploaded_voiceover_files = sorted(list(paths)) if len(paths) > 1 else list(paths)
            self.voiceover_mode.set("Upload Voiceover")
            self._voiceover_mode_changed("Upload Voiceover")
            self._refresh_uploaded_voice_ui()
            self._save_settings(silent=True)

    def clear_uploaded_voiceover(self):
        self.uploaded_voiceover_files = []
        self._refresh_uploaded_voice_ui()

    def _refresh_uploaded_voice_ui(self):
        if not hasattr(self, "upload_voice_summary"): return
        n = len(self.uploaded_voiceover_files)
        if n == 0: summary = "No voiceover uploaded"
        elif n == 1: summary = Path(self.uploaded_voiceover_files[0]).name
        else:
            names = [Path(p).name for p in self.uploaded_voiceover_files[:3]]
            summary = "  →  ".join(names) + (f"  →  +{n-3} more" if n > 3 else "")
        self.upload_voice_summary.configure(text=summary)
        self.upload_voice_count.configure(text=f"{n} file{'s' if n != 1 else ''}")

    # BGM Methods
    def generate_bgm(self):
        key = self.api_key.get().strip()
        if not key:
            messagebox.showwarning("BGM", "Enter API key first.")
            return
        try:
            seconds = float(self.bgm_duration.get().strip())
            if not 3 <= seconds <= 600: raise ValueError
        except ValueError:
            messagebox.showwarning("BGM", "Duration must be 3 to 600 seconds.")
            return
        prompt = self.bgm_prompt.get("1.0", "end").strip()
        out = filedialog.asksaveasfilename(defaultextension=".mp3", filetypes=[("MP3 audio", "*.mp3")], initialfile="recap_bgm.mp3")
        if not out: return
        self.generate_bgm_btn.configure(state="disabled", text="Generating…")
        self.bgm_status.configure(text="Generating music…")

        def worker():
            try:
                generate_music(prompt, seconds, key, out, model_id=self.music_model.get().strip(), force_instrumental=bool(self.force_instrumental.get()))
                self._post_ui(self._bgm_done, out)
            except Exception as e:
                self._post_ui(self._bgm_error, str(e))
        threading.Thread(target=worker, daemon=True).start()

    def _bgm_done(self, out):
        self.generate_bgm_btn.configure(state="normal", text="Generate BGM")
        self.generated_bgm_path = out
        self.bgm_files = [out]
        self._refresh_bgm_playlist_ui()
        self.bgm_status.configure(text=f"Generated single track: {Path(out).name}")

    def _bgm_error(self, msg):
        self.generate_bgm_btn.configure(state="normal", text="Generate BGM")
        self.bgm_status.configure(text="Generation failed")
        messagebox.showerror("BGM", msg)

    def _refresh_bgm_playlist_ui(self):
        if hasattr(self, "bgm_playlist_summary"):
            if not self.bgm_files: summary = "No tracks selected"
            elif len(self.bgm_files) == 1: summary = Path(self.bgm_files[0]).name
            else:
                names = [Path(p).name for p in self.bgm_files[:3]]
                summary = "  →  ".join(names) + (f"  →  +{len(self.bgm_files)-3} more" if len(self.bgm_files) > 3 else "")
            self.bgm_playlist_summary.configure(text=summary)
        if hasattr(self, "playlist_count"):
            self.playlist_count.configure(text=f"{len(self.bgm_files)} track{'s' if len(self.bgm_files) != 1 else ''}")
        if hasattr(self, "bgm_entry"):
            if len(self.bgm_files) == 1: self._set_path(self.bgm_entry, self.bgm_files[0])
            elif len(self.bgm_files) > 1: self._set_path(self.bgm_entry, f"PLAYLIST: {len(self.bgm_files)} tracks")
            else: self._set_path(self.bgm_entry, "")

    def _current_bgm_files(self):
        valid = [p for p in self.bgm_files if p]
        if valid: return valid
        if hasattr(self, "bgm_entry"):
            manual = self.bgm_entry.get().strip()
            if manual and os.path.exists(manual): return [manual]
        if self.generated_bgm_path and os.path.exists(self.generated_bgm_path):
            return [self.generated_bgm_path]
        return []

    def choose_existing_bgm(self):
        paths = filedialog.askopenfilenames(
            title="Choose BGM files",
            filetypes=[("Audio", "*.mp3 *.wav *.m4a *.aac *.flac *.ogg"), ("All files", "*.*")],
        )
        if paths:
            self.bgm_files = list(paths)
            self.generated_bgm_path = self.bgm_files[0] if len(self.bgm_files) == 1 else ""
            self._refresh_bgm_playlist_ui()
            self.bgm_status.configure(text=f"Playlist ready: {len(self.bgm_files)} tracks")

    def add_existing_bgm(self):
        paths = filedialog.askopenfilenames(
            title="Add BGM tracks",
            filetypes=[("Audio", "*.mp3 *.wav *.m4a *.aac *.flac *.ogg"), ("All files", "*.*")],
        )
        if paths:
            for p in paths:
                if p not in self.bgm_files: self.bgm_files.append(p)
            self.generated_bgm_path = self.bgm_files[0] if len(self.bgm_files) == 1 else ""
            self._refresh_bgm_playlist_ui()
            self.bgm_status.configure(text=f"Playlist ready: {len(self.bgm_files)} tracks")

    def clear_bgm_playlist(self):
        self.bgm_files = []
        self.generated_bgm_path = ""
        self._refresh_bgm_playlist_ui()
        self.bgm_status.configure(text="No BGM selected")

    def _preview_audio_paths(self, identity: str):
        key = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        raw = os.path.join(self.preview_cache_dir, f"voice_{key}_raw.mp3")
        sped = os.path.join(self.preview_cache_dir, f"voice_{key}_{float(self.narration_speed.get()):.3f}x.mp3")
        mix = os.path.join(self.preview_cache_dir, "current_mix_preview.wav")
        return raw, sped, mix

    def _project_cache_first_audio(self):
        cache = self.cache_entry.get().strip() if hasattr(self, "cache_entry") else ""
        if not cache and hasattr(self, "output_entry"):
            out = self.output_entry.get().strip()
            if out:
                base = os.path.splitext(os.path.basename(os.path.abspath(out)))[0]
                cache = os.path.join(os.path.dirname(os.path.abspath(out)), f".{base}_recap_cache")
        if cache:
            for name in ("audio_0000.mp3", "tts_raw_0000.mp3"):
                p = os.path.join(cache, "audio", name)
                if os.path.exists(p) and os.path.getsize(p) > 0: return p
        return ""

    def _play_preview_file(self, path: str):
        self.stop_preview()
        ffplay = shutil.which("ffplay")
        if ffplay:
            self.preview_process = subprocess.Popen(
                [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return
        if os.name == "nt":
            try:
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                self.preview_process = "winsound"
                return
            except Exception:
                os.startfile(path)
                return
        opener = "open" if platform.system() == "Darwin" else "xdg-open"
        subprocess.Popen([opener, path])

    def stop_preview(self):
        if self.preview_process == "winsound":
            try:
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception: pass
        elif self.preview_process is not None:
            try: self.preview_process.terminate()
            except Exception: pass
        self.preview_process = None

    def preview_mix(self):
        bgm_files = self._current_bgm_files()
        if not bgm_files:
            messagebox.showwarning("Preview", "Choose/generate BGM first.")
            return
        missing = [p for p in bgm_files if not os.path.exists(p)]
        if missing:
            messagebox.showwarning("Preview", f"BGM file not found: {missing[0]}")
            return

        mode = self.voiceover_mode.get()
        voice_source = ""
        identity = ""
        needs_speed = True
        if mode == "Upload Voiceover":
            if not self.uploaded_voiceover_files:
                messagebox.showwarning("Preview", "Choose uploaded voiceover first.")
                return
            voice_source = self.uploaded_voiceover_files[0]
            st = os.stat(voice_source)
            identity = f"upload|{os.path.abspath(voice_source)}|{st.st_size}|{st.st_mtime_ns}"
        else:
            cached = self._project_cache_first_audio()
            if cached:
                voice_source = cached
                st = os.stat(cached)
                identity = f"projectcache|{cached}|{st.st_size}|{st.st_mtime_ns}"
                needs_speed = False
            else:
                script_path = self.script_entry.get().strip() if hasattr(self, "script_entry") else ""
                if not script_path or not os.path.exists(script_path):
                    messagebox.showwarning("Preview", "Select script first.")
                    return
                key = self.api_key.get().strip()
                voice_id = self.voice_id.get().strip()
                if not key or not voice_id:
                    messagebox.showwarning("Preview", "Saved API key + Voice ID required.")
                    return
                with open(script_path, "r", encoding="utf-8", errors="ignore") as f:
                    first_line = next((x.strip() for x in f if x.strip()), "")
                if not first_line:
                    messagebox.showwarning("Preview", "Script is empty.")
                    return
                identity = "|".join(["generate", first_line, voice_id, self._selected_model_id(), f"{float(self.stability.get()):.4f}", f"{float(self.similarity.get()):.4f}"])
                raw, sped, mixed = self._preview_audio_paths(identity)
                voice_source = raw
                if not (os.path.exists(raw) and os.path.getsize(raw) > 0):
                    self.preview_btn.configure(state="disabled", text="Preparing Preview…")
                    self.bgm_status.configure(text="Generating cached narration sample…")
                    def gen_worker():
                        try:
                            generate_tts(first_line, voice_id, self._selected_model_id(), key, raw,
                                         stability=float(self.stability.get()), similarity_boost=float(self.similarity.get()), log_callback=self.log)
                            self._post_ui(self.preview_mix)
                        except Exception as e:
                            self._post_ui(self._preview_failed, str(e))
                    threading.Thread(target=gen_worker, daemon=True).start()
                    return

        raw, sped, mixed = self._preview_audio_paths(identity)
        self.preview_btn.configure(state="disabled", text="Preparing Preview…")
        self.bgm_status.configure(text="Mixing current Voice/BGM levels…")

        def worker():
            try:
                if voice_source != raw and not (os.path.exists(raw) and os.path.getsize(raw) > 0):
                    subprocess.run(["ffmpeg", "-y", "-i", voice_source, "-vn", "-c:a", "libmp3lame", "-b:a", "160k", raw],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                if needs_speed:
                    if not (os.path.exists(sped) and os.path.getsize(sped) > 0):
                        apply_narration_speed(raw, sped, float(self.narration_speed.get()))
                    voice_for_mix = sped
                else:
                    voice_for_mix = raw
                if len(bgm_files) > 1:
                    playlist_file = os.path.join(self.preview_cache_dir, "current_bgm_playlist.m4a")
                    bgm_source = prepare_bgm_playlist(bgm_files, playlist_file, log_callback=self.log)
                else:
                    bgm_source = bgm_files[0]
                render_audio_preview(voice_for_mix, bgm_source, mixed,
                                     voice_volume=float(self.voice_volume.get()), bgm_volume=float(self.bgm_volume.get()),
                                     duration=12.0, loop_bgm=bool(self.bgm_loop.get()))
                self._post_ui(self._preview_ready, mixed)
            except Exception as e:
                self._post_ui(self._preview_failed, str(e))
        threading.Thread(target=worker, daemon=True).start()

    def _preview_ready(self, path):
        self.preview_btn.configure(state="normal", text="▶ Preview Volume Mix")
        self.bgm_status.configure(text=f"Preview ready • Voice {float(self.voice_volume.get()):.0%} • BGM {float(self.bgm_volume.get()):.0%}")
        self._play_preview_file(path)

    def _preview_failed(self, msg):
        self.preview_btn.configure(state="normal", text="▶ Preview Volume Mix")
        self.bgm_status.configure(text="Preview failed")
        messagebox.showerror("Preview failed", msg)

    # -------------------------------------------------------------------------
    # Settings & Persistence
    # -------------------------------------------------------------------------
    def _load_env(self):
        saved = {}
        try:
            with open(self.settings_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except Exception: saved = {}

        remember = bool(saved.get("remember_api", True))
        if remember: self.remember_api.select()
        else: self.remember_api.deselect()

        key = os.getenv("AI33_API_KEY", "") or os.getenv("XI_API_KEY", "") or (saved.get("api_key", "") if remember else "")
        if key:
            self.api_key.delete(0, "end")
            self.api_key.insert(0, key)

        self._restore_model_id = saved.get("model_id", "")
        self._restore_voice_id = saved.get("voice_id", "")
        cached_models = saved.get("cached_models") or []
        cached_voices = saved.get("cached_voices") or []
        if cached_models or cached_voices:
            self._apply_api(cached_models, cached_voices, cached=True)
        elif self._restore_voice_id:
            self.voice_id.insert(0, self._restore_voice_id)

        def set_slider(slider, label, value, fmt):
            try:
                slider.set(float(value))
                label.configure(text=fmt(float(value)))
            except Exception: pass

        set_slider(self.stability, self.stability_label, saved.get("stability", 0.5), lambda v: f"{v:.2f}")
        set_slider(self.similarity, self.similarity_label, saved.get("similarity", 0.75), lambda v: f"{v:.2f}")
        set_slider(self.narration_speed, self.narration_speed_label, saved.get("narration_speed", 1.05), lambda v: f"{v:.2f}x")
        set_slider(self.voice_volume, self.voice_volume_label, saved.get("voice_volume", 1.0), lambda v: f"{v:.0%}")
        set_slider(self.bgm_volume, self.bgm_volume_label, saved.get("bgm_volume", 0.08), lambda v: f"{v:.0%}")
        set_slider(self.parallel_tts, self.parallel_tts_label, saved.get("parallel_tts", 3), lambda v: f"{int(v)} workers")
        set_slider(self.logo_width_slider, self.logo_width_label, saved.get("logo_width", 200), lambda v: f"{int(v)}px")
        set_slider(self.caption_size_slider, self.caption_size_label, saved.get("caption_size", 28), lambda v: f"{int(v)}pt")
        self.custom_logo_x = saved.get("custom_logo_x")
        self.custom_logo_y = saved.get("custom_logo_y")

        for combo, key_name, default in [
            (self.output_language, "output_language", "English"),
            (self.source_language, "source_language", "Auto / mixed"),
            (self.render_speed, "render_speed", "Fast (recommended)"),
            (self.logo_position, "logo_position", "Top-Right"),
            (self.caption_preset, "caption_preset", "CapCut Yellow Pop"),
            (self.caption_font, "caption_font", "Impact"),
            (self.caption_position, "caption_position", "Bottom-Center (CapCut Default)"),
            (self.movie_duration, "movie_duration", "1 Hour (3600s)"),
        ]:
            val = saved.get(key_name, default)
            try: combo.set(val)
            except Exception: pass

        if saved.get("enable_logo", True): self.enable_logo.select()
        else: self.enable_logo.deselect()

        if saved.get("enable_captions", True): self.enable_captions.select()
        else: self.enable_captions.deselect()

        if saved.get("enable_bgm", True): self.enable_bgm.select()
        else: self.enable_bgm.deselect()

        if saved.get("bgm_loop", True): self.bgm_loop.select()
        else: self.bgm_loop.deselect()

        rmode = saved.get("render_mode", "Render Video")
        if rmode in {"Render Video", "Render Movie"}:
            self.render_mode.set(rmode)
            self._render_mode_changed(rmode)

        intro_p = saved.get("intro_paths", "")
        if intro_p:
            self._set_path(self.intro_entry, intro_p)

        mode = saved.get("voiceover_mode", "Generate Voiceover")
        if mode in {"Generate Voiceover", "Upload Voiceover"}:
            self.voiceover_mode.set(mode)
        self.uploaded_voiceover_files = [p for p in saved.get("uploaded_voiceover_files", []) if os.path.exists(p)]
        self._refresh_uploaded_voice_ui()
        self.bgm_files = [p for p in saved.get("bgm_files", []) if os.path.exists(p)]
        self._refresh_bgm_playlist_ui()

        for attr, key_name in [
            ("video_entry", "video"), ("script_entry", "script"), ("plan_entry", "plan"), ("logo_entry", "logo"),
            ("output_entry", "output"), ("cache_entry", "cache")
        ]:
            val = saved.get(key_name, "")
            if val and hasattr(self, attr):
                if key_name in ("output", "cache") or os.path.exists(val):
                    self._set_path(getattr(self, attr), val)
        self._voiceover_mode_changed(self.voiceover_mode.get())
        if saved:
            self.api_status.configure(text="Saved preferences loaded")

    def _collect_settings(self):
        remember = bool(self.remember_api.get())
        return {
            "remember_api": remember,
            "api_key": self.api_key.get().strip() if remember else "",
            "model_id": self._selected_model_id(),
            "voice_id": self.voice_id.get().strip(),
            "cached_models": self.models,
            "cached_voices": self.voices,
            "voiceover_mode": self.voiceover_mode.get(),
            "uploaded_voiceover_files": self.uploaded_voiceover_files,
            "output_language": self.output_language.get(),
            "source_language": self.source_language.get(),
            "stability": float(self.stability.get()),
            "similarity": float(self.similarity.get()),
            "narration_speed": float(self.narration_speed.get()),
            "parallel_tts": int(self.parallel_tts.get()),
            "logo_position": self.logo_position.get(),
            "logo_width": int(self.logo_width_slider.get()),
            "custom_logo_x": getattr(self, "custom_logo_x", None),
            "custom_logo_y": getattr(self, "custom_logo_y", None),
            "enable_logo": bool(self.enable_logo.get()),
            "enable_captions": bool(self.enable_captions.get()),
            "enable_bgm": bool(self.enable_bgm.get()),
            "caption_preset": self.caption_preset.get(),
            "caption_font": self.caption_font.get(),
            "caption_size": int(self.caption_size_slider.get()),
            "caption_position": self.caption_position.get(),
            "render_mode": self.render_mode.get(),
            "movie_duration": self.movie_duration.get(),
            "intro_paths": self.intro_entry.get().strip(),
            "render_speed": self.render_speed.get(),
            "bgm_files": self._current_bgm_files(),
            "bgm_loop": bool(self.bgm_loop.get()),
            "voice_volume": float(self.voice_volume.get()),
            "bgm_volume": float(self.bgm_volume.get()),
            "video": self.video_entry.get().strip(),
            "script": self.script_entry.get().strip(),
            "plan": self.plan_entry.get().strip(),
            "logo": self.logo_entry.get().strip(),
            "output": self.output_entry.get().strip(),
            "cache": self.cache_entry.get().strip(),
        }

    def _save_settings(self, silent=False):
        try:
            os.makedirs(self.settings_dir, exist_ok=True)
            tmp = self.settings_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._collect_settings(), f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.settings_path)
            if not silent:
                self.api_status.configure(text=f"Preferences saved locally • {self.settings_path}")
        except Exception as e:
            if not silent: messagebox.showerror("Save Preferences", str(e))

    def _clear_saved_settings(self):
        try:
            if os.path.exists(self.settings_path): os.remove(self.settings_path)
            self.api_status.configure(text="Saved preferences cleared")
        except Exception as e:
            messagebox.showerror("Clear Saved", str(e))

    def _on_close(self):
        self._save_settings(silent=True)
        self.stop_preview()
        try: self.destroy()
        except Exception: pass

    # -------------------------------------------------------------------------
    # Helper & Logging Methods
    # -------------------------------------------------------------------------
    def _check_env(self):
        ff = check_ffmpeg()
        if all(ff.values()):
            self.env_status.configure(text="FFmpeg ✓", text_color=("#137333", "#68d391"))
        else:
            missing = ", ".join(k for k, v in ff.items() if not v)
            self.env_status.configure(text=f"Missing: {missing}", text_color=("#b3261e", "#ff7b72"))

    def _write_log_file(self, msg):
        try:
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(f"[{stamp}] {msg}\n")
                f.flush()
        except Exception: pass

    def _post_ui(self, callback, *args, **kwargs):
        self.ui_queue.put((callback, args, kwargs))

    def _drain_ui_queue(self):
        try:
            while True:
                callback, args, kwargs = self.ui_queue.get_nowait()
                try: callback(*args, **kwargs)
                except Exception: self._write_log_file("UI callback error:\n" + traceback.format_exc())
        except queue.Empty: pass
        try: self.after(75, self._drain_ui_queue)
        except Exception: pass

    def _append_log_ui(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def log(self, msg):
        msg = str(msg)
        self._write_log_file(msg)
        self._post_ui(self._append_log_ui, msg)

    def _validate_run(self):
        required = {
            "Source video": self.video_entry.get().strip(),
            "Rewritten script": self.script_entry.get().strip(),
            "Edit plan": self.plan_entry.get().strip(),
            "Final output": self.output_entry.get().strip(),
        }
        missing = [k for k, v in required.items() if not v]
        if missing: raise ValueError("Missing: " + ", ".join(missing))
        for key in ("Source video", "Rewritten script", "Edit plan"):
            if not os.path.exists(required[key]): raise ValueError(f"File not found: {required[key]}")
        mode = self.voiceover_mode.get()
        if mode == "Generate Voiceover":
            if not self.api_key.get().strip(): raise ValueError("Generate Voiceover: API key missing")
            if not self.voice_id.get().strip(): raise ValueError("Generate Voiceover: Voice ID missing")
        else:
            if not self.uploaded_voiceover_files: raise ValueError("Upload Voiceover: choose narration audio file(s)")
            for p in self.uploaded_voiceover_files:
                if not os.path.exists(p): raise ValueError(f"Voiceover file not found: {p}")
        logo_path = self.logo_entry.get().strip()
        if logo_path and not os.path.exists(logo_path): raise ValueError("Logo file not found.")
        for path in self._current_bgm_files():
            if path and not os.path.exists(path): raise ValueError(f"BGM file not found: {path}")
        validate_plan_against_script(required["Edit plan"], required["Rewritten script"])
        required["API key"] = self.api_key.get().strip()
        required["Voice ID"] = self.voice_id.get().strip()
        return required

    def open_logo_canvas_editor(self):
        logo_path = self.logo_entry.get().strip()
        if not logo_path or not os.path.exists(logo_path):
            messagebox.showwarning("Logo Required", "Please choose a logo watermark image file first.")
            self._choose_logo()
            logo_path = self.logo_entry.get().strip()
            if not logo_path or not os.path.exists(logo_path):
                return

        try:
            from PIL import Image, ImageTk
            video_path = self.video_entry.get().strip()
            temp_preview = os.path.join(self.preview_cache_dir, "canvas_editor_base.jpg")
            os.makedirs(os.path.dirname(temp_preview), exist_ok=True)

            if video_path and os.path.exists(video_path):
                run(["ffmpeg", "-y", "-ss", "00:00:02", "-i", video_path, "-vframes", "1", "-s", "1280x720", temp_preview])
            else:
                run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=181B2A:s=1280x720:d=1", "-vframes", "1", temp_preview])

            top = ctk.CTkToplevel(self)
            top.title("📐 Drag & Stretch Logo Watermark (Canvas Editor)")
            top.geometry("900x660")
            top.grab_set()

            C_WIDTH, C_HEIGHT = 800, 450
            SCALE_X = 1280.0 / C_WIDTH
            SCALE_Y = 720.0 / C_HEIGHT

            base_pil = Image.open(temp_preview).resize((C_WIDTH, C_HEIGHT), Image.Resampling.LANCZOS)
            base_photo = ImageTk.PhotoImage(base_pil)

            info_lbl = ctk.CTkLabel(top, text="💡 Drag logo anywhere on canvas. Use slider below to stretch/resize logo.", font=ctk.CTkFont(size=12, weight="bold"))
            info_lbl.pack(pady=(10, 5))

            canvas_frame = ctk.CTkFrame(top, fg_color="#111827", corner_radius=10)
            canvas_frame.pack(padx=20, pady=5)

            cv = ctk.CTkCanvas(canvas_frame, width=C_WIDTH, height=C_HEIGHT, bg="#111827", highlightthickness=1, highlightbackground="#374151")
            cv.pack(padx=5, pady=5)
            cv.create_image(0, 0, image=base_photo, anchor="nw")
            top._base_photo = base_photo

            logo_orig_pil = Image.open(logo_path).convert("RGBA")
            init_w = int(self.logo_width_slider.get())
            state = {
                "width": init_w,
                "canvas_x": (getattr(self, "custom_logo_x", 1000) / SCALE_X) if getattr(self, "custom_logo_x", None) is not None else (C_WIDTH - (init_w / SCALE_X) - 20),
                "canvas_y": (getattr(self, "custom_logo_y", 40) / SCALE_Y) if getattr(self, "custom_logo_y", None) is not None else 20,
                "drag_offset_x": 0,
                "drag_offset_y": 0,
                "logo_item": None,
                "logo_photo": None
            }

            def render_canvas_logo():
                cw = int(state["width"] / SCALE_X)
                ch = max(10, int((cw * logo_orig_pil.height) / max(1, logo_orig_pil.width)))
                resized_pil = logo_orig_pil.resize((cw, ch), Image.Resampling.LANCZOS)
                state["logo_photo"] = ImageTk.PhotoImage(resized_pil)
                if state["logo_item"]:
                    cv.delete(state["logo_item"])
                state["logo_item"] = cv.create_image(state["canvas_x"], state["canvas_y"], image=state["logo_photo"], anchor="nw")

            render_canvas_logo()

            def on_press(event):
                state["drag_offset_x"] = event.x - state["canvas_x"]
                state["drag_offset_y"] = event.y - state["canvas_y"]

            def on_drag(event):
                new_x = event.x - state["drag_offset_x"]
                new_y = event.y - state["drag_offset_y"]
                cw = int(state["width"] / SCALE_X)
                ch = max(10, int((cw * logo_orig_pil.height) / max(1, logo_orig_pil.width)))
                state["canvas_x"] = max(0, min(C_WIDTH - cw, new_x))
                state["canvas_y"] = max(0, min(C_HEIGHT - ch, new_y))
                cv.coords(state["logo_item"], state["canvas_x"], state["canvas_y"])

            cv.bind("<ButtonPress-1>", on_press)
            cv.bind("<B1-Motion>", on_drag)

            ctrl_frame = ctk.CTkFrame(top, fg_color="transparent")
            ctrl_frame.pack(fill="x", padx=20, pady=10)

            ctk.CTkLabel(ctrl_frame, text="Logo Stretch / Width:").pack(side="left", padx=5)

            def on_slider_change(val):
                state["width"] = int(val)
                modal_width_lbl.configure(text=f"{int(val)}px")
                render_canvas_logo()

            modal_slider = ctk.CTkSlider(ctrl_frame, from_=50, to=500, number_of_steps=45, command=on_slider_change)
            modal_slider.pack(side="left", fill="x", expand=True, padx=10)
            modal_slider.set(init_w)

            modal_width_lbl = ctk.CTkLabel(ctrl_frame, text=f"{init_w}px", width=55)
            modal_width_lbl.pack(side="left", padx=5)

            def save_and_close():
                vid_x = int(state["canvas_x"] * SCALE_X)
                vid_y = int(state["canvas_y"] * SCALE_Y)
                final_w = int(state["width"])

                self.custom_logo_x = vid_x
                self.custom_logo_y = vid_y
                self.logo_position.set("Custom (Drag & Drop)")
                self.logo_width_slider.set(final_w)
                self.logo_width_label.configure(text=f"{final_w}px")

                messagebox.showinfo("Logo Position Saved", f"Custom logo position applied:\nX={vid_x}px, Y={vid_y}px, Width={final_w}px")
                top.destroy()
                self.play_logo_caption_preview()

            ctk.CTkButton(top, text="✓ Save Custom Position & Size", fg_color="#10B981", hover_color="#059669", height=38, font=ctk.CTkFont(size=13, weight="bold"), command=save_and_close).pack(pady=(5, 15))

        except Exception as exc:
            messagebox.showerror("Canvas Editor Error", f"Could not open canvas editor: {exc}")

    def play_logo_caption_preview(self):
        try:
            from recap_engine_v2_8 import render_logo_caption_preview_frame
            video_p = self.video_entry.get().strip()
            logo_p = self.logo_entry.get().strip()
            font_p = self.custom_font_entry.get().strip() if hasattr(self, "custom_font_entry") else ""
            out_preview = os.path.join(self.preview_cache_dir, "logo_caption_preview.png")

            fsize = int(self.caption_size_slider.get())
            l_width = int(self.logo_width_slider.get())

            preview_path = render_logo_caption_preview_frame(
                video_path=video_p,
                logo_path=logo_p,
                out_img_path=out_preview,
                enable_logo=bool(self.enable_logo.get()),
                logo_position=self.logo_position.get(),
                logo_width=l_width,
                custom_x=getattr(self, "custom_logo_x", None),
                custom_y=getattr(self, "custom_logo_y", None),
                enable_captions=bool(self.enable_captions.get()),
                caption_preset=self.caption_preset.get(),
                caption_font=self.caption_font.get(),
                caption_size=fsize,
                caption_position=self.caption_position.get().split("(")[0].strip(),
                caption_case=self.caption_case.get(),
                caption_words_per_line=self.caption_words_per_line.get(),
                custom_font_path=font_p if font_p and os.path.exists(font_p) else None,
            )

            if os.path.exists(preview_path):
                from PIL import Image
                top = ctk.CTkToplevel(self)
                top.title("Live Logo & CapCut Caption Preview (1280x720)")
                top.geometry("860x540")

                img = Image.open(preview_path)
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(820, 461))

                lbl = ctk.CTkLabel(top, image=ctk_img, text="")
                lbl.pack(padx=20, pady=15)

                ctk.CTkButton(top, text="Close Preview", width=120, command=top.destroy).pack(pady=(0, 10))
        except Exception as exc:
            messagebox.showerror("Preview Error", f"Could not render preview: {exc}")

    def run_project(self):
        if self.running: return
        try:
            r = self._validate_run()
        except Exception as e:
            messagebox.showerror("Cannot run", str(e)); return
        mode = "upload" if self.voiceover_mode.get() == "Upload Voiceover" else "generate"
        rmode = "movie" if self.render_mode.get() == "Render Movie" else "video"

        intros_raw = self.intro_entry.get().strip()
        intro_list = [p.strip() for p in intros_raw.split(";") if p.strip()]

        dur_text = self.movie_duration.get().lower()
        if "1 hour" in dur_text: dur_sec = 3600.0
        elif "2 hour" in dur_text: dur_sec = 7200.0
        elif "3 hour" in dur_text: dur_sec = 10800.0
        elif "4 hour" in dur_text: dur_sec = 14400.0
        else: dur_sec = 3600.0

        csize = int(self.caption_size_slider.get())
        l_width = int(self.logo_width_slider.get())

        font_p = self.custom_font_entry.get().strip() if hasattr(self, "custom_font_entry") else ""
        settings = {
            "model": self._selected_model_id(), "cache": self.cache_entry.get().strip() or None,
            "logo": self.logo_entry.get().strip() or None,
            "logo_position": self.logo_position.get(),
            "logo_width": l_width,
            "custom_logo_x": getattr(self, "custom_logo_x", None),
            "custom_logo_y": getattr(self, "custom_logo_y", None),
            "bgm_files": self._current_bgm_files(),
            "voice_volume": float(self.voice_volume.get()), "bgm_volume": float(self.bgm_volume.get()),
            "bgm_loop": bool(self.bgm_loop.get()), "stability": float(self.stability.get()),
            "similarity": float(self.similarity.get()), "narration_speed": float(self.narration_speed.get()),
            "parallel_tts": int(self.parallel_tts.get()),
            "render_mode": rmode, "intro_paths": intro_list, "movie_duration_sec": dur_sec,
            "render_preset": {"Fast (recommended)": "fast", "Turbo": "veryfast", "Balanced": "medium"}.get(self.render_speed.get(), "fast"),
            "voiceover_mode": mode, "uploaded_voiceover_paths": list(self.uploaded_voiceover_files),
            "enable_logo": bool(self.enable_logo.get()),
            "enable_captions": bool(self.enable_captions.get()),
            "enable_bgm": bool(self.enable_bgm.get()),
            "caption_font": self.caption_font.get(),
            "caption_preset": self.caption_preset.get(),
            "caption_size": csize,
            "caption_position": self.caption_position.get().split("(")[0].strip(),
            "caption_case": self.caption_case.get(),
            "caption_words_per_line": self.caption_words_per_line.get(),
            "custom_font_path": font_p if font_p and os.path.exists(font_p) else None,
        }
        self._save_settings(silent=True)
        self.running = True
        self.run_btn.configure(state="disabled", text="BUILDING…")
        self.build_status.configure(text=f"Running • mode: {rmode} • parallel TTS: {settings['parallel_tts']} workers • cache ON")
        self.log("=" * 72); self.log("Starting / resuming project…")

        def worker():
            try:
                out = build_project(
                    video_path=r["Source video"], script_path=r["Rewritten script"], edit_plan_path=r["Edit plan"],
                    voice_id=r["Voice ID"], tts_model_id=settings["model"], elevenlabs_key=r["API key"],
                    out_path=r["Final output"], cache_dir=settings["cache"], logo_path=settings["logo"],
                    logo_position=settings["logo_position"],
                    bgm_path=(settings["bgm_files"][0] if len(settings["bgm_files"]) == 1 else None),
                    bgm_paths=settings["bgm_files"], bgm_volume=settings["bgm_volume"], bgm_loop=settings["bgm_loop"],
                    voice_volume=settings["voice_volume"], stability=settings["stability"], similarity_boost=settings["similarity"],
                    narration_speed=settings["narration_speed"], render_preset=settings["render_preset"], log_callback=self.log,
                    voiceover_mode=settings["voiceover_mode"], uploaded_voiceover_paths=settings["uploaded_voiceover_paths"],
                    max_tts_workers=settings["parallel_tts"],
                    render_mode=settings["render_mode"], intro_video_paths=settings["intro_paths"],
                    target_movie_duration_seconds=settings["movie_duration_sec"],
                    enable_logo=settings["enable_logo"],
                    enable_captions=settings["enable_captions"],
                    enable_bgm=settings["enable_bgm"],
                    caption_font=settings["caption_font"],
                    caption_preset=settings["caption_preset"],
                    caption_size=settings["caption_size"],
                    caption_position=settings["caption_position"],
                    caption_case=settings["caption_case"],
                    caption_words_per_line=settings["caption_words_per_line"],
                    custom_font_path=settings["custom_font_path"],
                    logo_width=settings["logo_width"],
                    custom_logo_x=settings["custom_logo_x"],
                    custom_logo_y=settings["custom_logo_y"],
                )
                self._post_ui(self._done, out)
            except Exception as e:
                self.log(traceback.format_exc()); self._post_ui(self._failed, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _done(self, out):
        self.running = False
        self.run_btn.configure(state="normal", text="▶  RUN / RESUME PROJECT")
        self.build_status.configure(text=f"Done: {Path(out).name}")
        messagebox.showinfo("Recap Studio V2.8", f"Final video created:\n{out}")

    def _failed(self, msg):
        self.running = False
        self.run_btn.configure(state="normal", text="▶  RUN / RESUME PROJECT")
        self.build_status.configure(text="Build failed — fix issue and press RUN to resume")
        messagebox.showerror("Build failed", msg)

    def open_output_folder(self):
        out = self.output_entry.get().strip()
        folder = os.path.dirname(os.path.abspath(out)) if out else os.getcwd()
        if not os.path.isdir(folder):
            messagebox.showwarning("Output", "Output folder does not exist yet.")
            return
        system = platform.system()
        if system == "Windows":
            os.startfile(folder)  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])


def _global_exception_handler(exc_type, exc_value, exc_tb):
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recap_studio_crash.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 80 + "\n")
            f.write(datetime.now().isoformat() + "\n")
            f.write(text)
            f.flush()
    except Exception: pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)


if __name__ == "__main__":
    sys.excepthook = _global_exception_handler
    RecapStudioV2().mainloop()
