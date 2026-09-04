#!/usr/bin/env python3
"""Recap Studio V2.8 — Embedded Tab Frame with AI33 Voice Library & Parallel Render Engine."""
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
import lazy_menu  # Win32 / TCL native menu limit fix
import preset_manager

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

LANG_OPTIONS = ["Auto / mixed", "English", "Hindi", "Hinglish", "Spanish", "Other"]

TAB_TITLE = "🎬  Recap Studio"
TAB_ORDER = 15
TAB_GROUP = ""
TAB_COLOR = ("#6366f1", "#818cf8")
LAZY_LOAD = True


def create(parent_frame, boot_data=None):
    try:
        parent_frame.grid_columnconfigure(0, weight=1)
        parent_frame.grid_rowconfigure(0, weight=1)
    except Exception:
        pass
    frame = RecapStudioTabFrame(parent_frame)
    try:
        frame.grid(row=0, column=0, sticky="nsew")
    except Exception:
        frame.pack(fill="both", expand=True)
    return frame


class RecapStudioTabFrame(ctk.CTkFrame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.models = []
        self.voices = []
        self.model_map = {}
        self.voice_map = {}
        self.model_languages = {}
        self._restore_model_id = ""
        self._restore_voice_id = ""
        self.running = False
        self.generated_bgm_path = ""
        self.bgm_files = []
        self.uploaded_voiceover_files = []
        self.preview_process = None
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
        self._build_single_page_dashboard()
        self._build_header()
        self._load_env()
        self.after(75, self._drain_ui_queue)
        self.after(250, self._check_env)

    def _check_env(self):
        try:
            status = check_ffmpeg()
            if not status.get("ffmpeg"):
                if hasattr(self, "_log"):
                    self._log("⚠️ FFmpeg binary not found in system or bundled path.")
        except Exception:
            pass

    def _build_header(self):
        f = ctk.CTkFrame(self, corner_radius=0)
        f.grid(row=0, column=0, sticky="ew")
        f.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(f, text="RECAP STUDIO V2.8 — AI33 DASHBOARD", font=ctk.CTkFont(size=20, weight="bold")).grid(
            row=0, column=0, padx=22, pady=(10, 2), sticky="w")
        ctk.CTkLabel(
            f,
            text="Single-Page Control • AI33 Voice Library • Voice Preview • Parallel TTS & Video Render",
            text_color=("gray35", "gray70"),
        ).grid(row=1, column=0, padx=22, pady=(0, 8), sticky="w")
        self.preset_widget = preset_manager.PresetWidget(
            f,
            tool_id="recap_studio",
            collect_fn=self._collect_settings,
            apply_fn=self._apply_settings,
            status_cb=lambda msg, col: self._log(f"[preset] {msg}")
        )
        self.preset_widget.grid(row=0, column=1, rowspan=2, padx=14, pady=6, sticky="e")

    def _collect_settings(self) -> dict:
        try:
            return {
                "api_key": self.api_key.get().strip() if hasattr(self, "api_key") else "",
                "model": self.model_menu.get() if hasattr(self, "model_menu") else "",
                "voice_id": self.voice_id.get().strip() if hasattr(self, "voice_id") else "",
                "stability": float(self.stability.get()) if hasattr(self, "stability") else 0.50,
                "similarity": float(self.similarity.get()) if hasattr(self, "similarity") else 0.75,
                "narration_speed": float(self.narration_speed.get()) if hasattr(self, "narration_speed") else 1.05,
                "video_entry": self.video_entry.get().strip() if hasattr(self, "video_entry") else "",
                "script_entry": self.script_entry.get().strip() if hasattr(self, "script_entry") else "",
                "plan_entry": self.plan_entry.get().strip() if hasattr(self, "plan_entry") else "",
                "logo_entry": self.logo_entry.get().strip() if hasattr(self, "logo_entry") else "",
                "output_entry": self.output_entry.get().strip() if hasattr(self, "output_entry") else "",
            }
        except Exception as e:
            print("[recap_studio] _collect_settings error:", e)
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
            if "stability" in st and hasattr(self, "stability"):
                try: self.stability.set(st["stability"])
                except Exception: pass
            if "similarity" in st and hasattr(self, "similarity"):
                try: self.similarity.set(st["similarity"])
                except Exception: pass
            if "narration_speed" in st and hasattr(self, "narration_speed"):
                try: self.narration_speed.set(st["narration_speed"])
                except Exception: pass
            if "video_entry" in st and st["video_entry"] and hasattr(self, "video_entry"):
                self.video_entry.delete(0, "end"); self.video_entry.insert(0, st["video_entry"])
            if "script_entry" in st and st["script_entry"] and hasattr(self, "script_entry"):
                self.script_entry.delete(0, "end"); self.script_entry.insert(0, st["script_entry"])
            if "plan_entry" in st and st["plan_entry"] and hasattr(self, "plan_entry"):
                self.plan_entry.delete(0, "end"); self.plan_entry.insert(0, st["plan_entry"])
            if "logo_entry" in st and st["logo_entry"] and hasattr(self, "logo_entry"):
                self.logo_entry.delete(0, "end"); self.logo_entry.insert(0, st["logo_entry"])
            if "output_entry" in st and st["output_entry"] and hasattr(self, "output_entry"):
                self.output_entry.delete(0, "end"); self.output_entry.insert(0, st["output_entry"])
            self.log("[preset] Applied Recap Studio settings ✓")
        except Exception as e:
            self.log(f"[preset] Apply settings warning: {e}")

    def _section(self, parent, title, badge_color="#6366F1", expanded: bool = True):
        outer = ctk.CTkFrame(parent, fg_color="#181B2A", corner_radius=14, border_width=1, border_color="#2E334D")
        outer.pack(fill="x", padx=8, pady=8)
        outer.grid_columnconfigure(0, weight=1)

        # Header Bar (Clickable)
        header = ctk.CTkFrame(outer, fg_color="#222538", corner_radius=10, cursor="hand2")
        header.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        header.grid_columnconfigure(1, weight=1)

        badge = ctk.CTkFrame(header, fg_color=badge_color, corner_radius=6, width=12, height=22)
        badge.grid(row=0, column=0, padx=(12, 8), pady=8)

        lbl = ctk.CTkLabel(header, text=title, font=ctk.CTkFont(size=14, weight="bold"), text_color="#F3F4F6")
        lbl.grid(row=0, column=1, sticky="w", pady=8)

        toggle_lbl = ctk.CTkLabel(header, text="▼ Collapse" if expanded else "▲ Expand Section", font=ctk.CTkFont(size=11, weight="bold"), text_color="#9CA3AF")
        toggle_lbl.grid(row=0, column=2, padx=14, pady=8)

        # Content Frame
        body = ctk.CTkFrame(outer, fg_color="transparent")
        if expanded:
            body.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 8))

        def toggle_section(event=None):
            if body.winfo_ismapped():
                body.grid_forget()
                toggle_lbl.configure(text="▲ Expand Section")
            else:
                body.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 8))
                toggle_lbl.configure(text="▼ Collapse")

        header.bind("<Button-1>", toggle_section)
        lbl.bind("<Button-1>", toggle_section)
        badge.bind("<Button-1>", toggle_section)
        toggle_lbl.bind("<Button-1>", toggle_section)

        body.grid_columnconfigure(1, weight=1)
        return body

    def _build_single_page_dashboard(self):
        dash = ctk.CTkScrollableFrame(self, fg_color="transparent")
        dash.grid(row=1, column=0, sticky="nsew", padx=14, pady=10)
        dash.grid_columnconfigure((0, 1), weight=1)

        left_col = ctk.CTkFrame(dash, fg_color="transparent")
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        left_col.grid_columnconfigure(0, weight=1)

        right_col = ctk.CTkFrame(dash, fg_color="transparent")
        right_col.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        right_col.grid_columnconfigure(0, weight=1)

        # ---------------------------------------------------------------------
        # LEFT COLUMN CARDS
        # ---------------------------------------------------------------------
        # 1. Project Inputs Card
        inputs_card = self._section(left_col, "Project Input Files", badge_color="#3B82F6", expanded=True)
        self.video_entry = self._file_row(inputs_card, 1, "Source Video", self._choose_video, "Select main raw footage (.mp4/.mov)")
        self.script_entry = self._file_row(inputs_card, 2, "Rewritten Script", self._choose_script, "Select formatted script.txt")
        self.plan_entry = self._file_row(inputs_card, 3, "Edit Plan JSON", self._choose_plan, "Select ChatGPT edit plan (.json / .txt)")
        self.logo_entry = self._file_row(inputs_card, 4, "Logo Watermark", self._choose_logo, "Optional PNG logo watermark image")
        self.output_entry = self._file_row(inputs_card, 5, "Final Output", self._choose_output, "Target output path for rendered MP4")
        self.cache_entry = self._file_row(inputs_card, 6, "Cache Folder", self._choose_cache, "Optional custom cache directory")

        cache_btn_row = ctk.CTkFrame(inputs_card, fg_color="transparent")
        cache_btn_row.grid(row=7, column=1, columnspan=2, padx=4, pady=(2, 8), sticky="w")
        ctk.CTkButton(cache_btn_row, text="🧹 Clear Script & Audio Cache", width=190, fg_color="#EF4444", hover_color="#DC2626", command=self.clear_cache_folder).pack(side="left")

        # 2. Voice Library & TTS Settings Card
        voice_card = self._section(left_col, "AI33 Voice Library & TTS Configuration", badge_color="#8B5CF6", expanded=True)
        
        self.voiceover_mode = ctk.CTkSegmentedButton(voice_card, values=["Generate Voiceover", "Upload Voiceover"], command=self._voiceover_mode_changed)
        self.voiceover_mode.grid(row=1, column=0, columnspan=3, padx=14, pady=6, sticky="ew")
        self.voiceover_mode.set("Generate Voiceover")

        self.gen_voice_frame = ctk.CTkFrame(voice_card, fg_color="transparent")
        self.gen_voice_frame.grid(row=2, column=0, columnspan=3, sticky="ew")
        self.gen_voice_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self.gen_voice_frame, text="AI33 API Key").grid(row=0, column=0, padx=14, pady=6, sticky="w")
        self.api_key = ctk.CTkEntry(self.gen_voice_frame, show="•", placeholder_text="sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt")
        self.api_key.grid(row=0, column=1, padx=4, pady=6, sticky="ew")
        self.api_key.insert(0, "sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt")

        api_btn_frame = ctk.CTkFrame(self.gen_voice_frame, fg_color="transparent")
        api_btn_frame.grid(row=0, column=2, padx=(4, 14), pady=6, sticky="e")
        self._key_visible = False
        def _toggle_key():
            self._key_visible = not self._key_visible
            self.api_key.configure(show="" if self._key_visible else "•")
            btn_key_toggle.configure(text="🙈" if self._key_visible else "👁")
        btn_key_toggle = ctk.CTkButton(api_btn_frame, text="👁", width=32, command=_toggle_key, fg_color="#2E334D")
        btn_key_toggle.pack(side="left", padx=(0, 6))
        ctk.CTkButton(api_btn_frame, text="Fetch Voices", width=110, command=self.fetch_api_data, fg_color="#06B6D4", hover_color="#0891B2").pack(side="left", padx=(0, 6))

        self.api_status = ctk.CTkLabel(self.gen_voice_frame, text="Key required to load voice catalog", text_color="gray70")
        self.api_status.grid(row=1, column=1, columnspan=2, padx=4, pady=(0, 6), sticky="w")

        ctk.CTkLabel(self.gen_voice_frame, text="Voice Provider").grid(row=2, column=0, padx=14, pady=6, sticky="w")
        self.model_menu = ctk.CTkComboBox(self.gen_voice_frame, values=["All Providers", "ElevenLabs", "Minimax", "FishAudio", "Edge Neural", "Kokoro", "Vbee", "Cloned Voices"], command=lambda v: self._provider_changed(v), state="readonly")
        self.model_menu.grid(row=2, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")
        self.model_menu.set("All Providers")

        ctk.CTkLabel(self.gen_voice_frame, text="Sub-Model").grid(row=3, column=0, padx=14, pady=6, sticky="w")
        self.submodel_menu = ctk.CTkComboBox(self.gen_voice_frame, values=["All Models / Sub-Models"], command=lambda v: self._filter_voices(), state="readonly")
        self.submodel_menu.grid(row=3, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")

        ctk.CTkLabel(self.gen_voice_frame, text="Search Voice").grid(row=4, column=0, padx=14, pady=6, sticky="w")
        search_f = ctk.CTkFrame(self.gen_voice_frame, fg_color="transparent")
        search_f.grid(row=4, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")
        search_f.grid_columnconfigure(0, weight=1)
        self.voice_search = ctk.CTkEntry(search_f, placeholder_text="Type voice name or ID...")
        self.voice_search.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.voice_search.bind("<KeyRelease>", lambda e: self._filter_voices())
        ctk.CTkButton(search_f, text="Refresh", width=65, fg_color="#1E293B", hover_color="#334155", command=self.fetch_api_data).grid(row=0, column=1, padx=(0, 4))
        ctk.CTkButton(search_f, text="Clear", width=55, fg_color="#374151", hover_color="#4B5563", command=self._clear_voice_search).grid(row=0, column=2)

        ctk.CTkLabel(self.gen_voice_frame, text="Voice Library").grid(row=5, column=0, padx=14, pady=6, sticky="nw")
        self.voice_list_scroll = ctk.CTkScrollableFrame(self.gen_voice_frame, height=180, fg_color="#111827", border_width=1, border_color="#374151")
        self.voice_list_scroll.grid(row=5, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")

        ctk.CTkLabel(self.gen_voice_frame, text="Selected Voice").grid(row=6, column=0, padx=14, pady=6, sticky="w")
        vid_f = ctk.CTkFrame(self.gen_voice_frame, fg_color="transparent")
        vid_f.grid(row=6, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")
        vid_f.grid_columnconfigure(0, weight=1)

        self.voice_id = ctk.CTkEntry(vid_f, placeholder_text="Auto-filled or paste Voice ID")
        self.voice_id.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.voice_id.insert(0, "elevenlabs_hpp4J3VqNfWAUOO0d1Us")

        self.preview_voice_btn = ctk.CTkButton(
            vid_f, text="▶ Test Voice", width=95,
            fg_color="#8B5CF6", hover_color="#7C3AED", font=ctk.CTkFont(size=10, weight="bold"),
            command=self.play_voice_preview
        )
        self.preview_voice_btn.grid(row=0, column=1)

        self.upload_voice_frame = ctk.CTkFrame(voice_card, fg_color="transparent")
        self.upload_voice_frame.grid(row=3, column=0, columnspan=3, sticky="ew")
        self.upload_voice_frame.grid_columnconfigure(1, weight=1)
        self.upload_voice_frame.grid_remove()

        ctk.CTkLabel(self.upload_voice_frame, text="Upload Narration").grid(row=0, column=0, padx=14, pady=6, sticky="w")
        self.uploaded_voice_summary = ctk.CTkLabel(self.upload_voice_frame, text="No audio files chosen", anchor="w")
        self.uploaded_voice_summary.grid(row=0, column=1, padx=4, pady=6, sticky="ew")
        ctk.CTkButton(self.upload_voice_frame, text="Choose File(s)", width=120, command=self.choose_uploaded_voiceover).grid(row=0, column=2, padx=(4, 14), pady=6, sticky="e")

        ctk.CTkLabel(voice_card, text="Stability").grid(row=4, column=0, padx=14, pady=6, sticky="w")
        self.stability = ctk.CTkSlider(voice_card, from_=0.0, to=1.0, command=lambda v: self.stability_label.configure(text=f"{v:.2f}"))
        self.stability.grid(row=4, column=1, padx=4, pady=6, sticky="ew")
        self.stability.set(0.50)
        self.stability_label = ctk.CTkLabel(voice_card, text="0.50", width=45)
        self.stability_label.grid(row=4, column=2, padx=14)

        ctk.CTkLabel(voice_card, text="Clarity / Similarity").grid(row=5, column=0, padx=14, pady=6, sticky="w")
        self.similarity = ctk.CTkSlider(voice_card, from_=0.0, to=1.0, command=lambda v: self.similarity_label.configure(text=f"{v:.2f}"))
        self.similarity.grid(row=5, column=1, padx=4, pady=6, sticky="ew")
        self.similarity.set(0.75)
        self.similarity_label = ctk.CTkLabel(voice_card, text="0.75", width=45)
        self.similarity_label.grid(row=5, column=2, padx=14)

        ctk.CTkLabel(voice_card, text="Narration Speed").grid(row=6, column=0, padx=14, pady=6, sticky="w")
        self.narration_speed = ctk.CTkSlider(voice_card, from_=0.80, to=1.30, command=lambda v: self.narration_speed_label.configure(text=f"{v:.2f}x"))
        self.narration_speed.grid(row=6, column=1, padx=4, pady=6, sticky="ew")
        self.narration_speed.set(1.05)
        self.narration_speed_label = ctk.CTkLabel(voice_card, text="1.05x", width=45)
        self.narration_speed_label.grid(row=6, column=2, padx=14)

        ctk.CTkLabel(voice_card, text="AI33 Parallel Workers").grid(row=7, column=0, padx=14, pady=6, sticky="w")
        self.parallel_tts = ctk.CTkSlider(voice_card, from_=1, to=10, number_of_steps=9, command=lambda v: self.parallel_tts_label.configure(text=f"{int(v)} workers"))
        self.parallel_tts.grid(row=7, column=1, padx=4, pady=6, sticky="ew")
        self.parallel_tts.set(3)
        self.parallel_tts_label = ctk.CTkLabel(voice_card, text="3 workers", width=75)
        self.parallel_tts_label.grid(row=7, column=2, padx=14)

        # ---------------------------------------------------------------------
        # RIGHT COLUMN CARDS
        # ---------------------------------------------------------------------
        # 1. Output Preferences Card
        render_opt_card = self._section(right_col, "Render Speed & Quality Preset", badge_color="#EC4899", expanded=True)
        ctk.CTkLabel(render_opt_card, text="Encoder Speed").grid(row=1, column=0, padx=14, pady=6, sticky="w")
        self.render_speed = ctk.CTkComboBox(render_opt_card, values=["Fast (recommended)", "Turbo", "Balanced"], state="readonly")
        self.render_speed.grid(row=1, column=1, columnspan=2, padx=(4, 14), pady=6, sticky="ew")
        self.render_speed.set("Fast (recommended)")

        # 2. Logo Watermark & CapCut Subtitle Customization Card
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

        ctk.CTkLabel(bgm_card, text="Generate BGM (AI)").grid(row=3, column=0, padx=14, pady=6, sticky="w")
        self.bgm_prompt = ctk.CTkEntry(bgm_card, placeholder_text="Describe BGM mood (e.g., epic cinematic suspense)")
        self.bgm_prompt.grid(row=3, column=1, padx=4, pady=6, sticky="ew")
        ctk.CTkButton(bgm_card, text="✨ Generate BGM", width=120, command=self.generate_ai_bgm).grid(row=3, column=2, padx=(4, 14), pady=6, sticky="e")

        self.bgm_status = ctk.CTkLabel(bgm_card, text="Select or generate BGM track", text_color="gray70")
        self.bgm_status.grid(row=4, column=1, columnspan=2, padx=4, pady=(0, 6), sticky="w")

        self.bgm_loop = ctk.CTkCheckBox(bgm_card, text="☑ Loop BGM Playlist")
        self.bgm_loop.grid(row=5, column=1, columnspan=2, padx=4, pady=6, sticky="w")
        self.bgm_loop.select()

        ctk.CTkLabel(bgm_card, text="Voice Volume").grid(row=6, column=0, padx=14, pady=6, sticky="w")
        self.voice_volume = ctk.CTkSlider(bgm_card, from_=0.0, to=2.0, command=lambda v: self.voice_volume_label.configure(text=f"{v:.0%}"))
        self.voice_volume.grid(row=6, column=1, padx=4, pady=6, sticky="ew")
        self.voice_volume.set(1.0)
        self.voice_volume_label = ctk.CTkLabel(bgm_card, text="100%", width=45)
        self.voice_volume_label.grid(row=6, column=2, padx=14)

        ctk.CTkLabel(bgm_card, text="BGM Volume").grid(row=7, column=0, padx=14, pady=6, sticky="w")
        self.bgm_volume = ctk.CTkSlider(bgm_card, from_=0.0, to=0.5, command=lambda v: self.bgm_volume_label.configure(text=f"{v:.0%}"))
        self.bgm_volume.grid(row=7, column=1, padx=4, pady=6, sticky="ew")
        self.bgm_volume.set(0.08)
        self.bgm_volume_label = ctk.CTkLabel(bgm_card, text="8%", width=45)
        self.bgm_volume_label.grid(row=7, column=2, padx=14)

        # ---------------------------------------------------------------------
        # BOTTOM ACTION & LOGS CARD
        # ---------------------------------------------------------------------
        run_card = ctk.CTkFrame(dash, fg_color="#1E293B", corner_radius=14, border_width=1, border_color="#334155")
        run_card.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(12, 18))
        run_card.grid_columnconfigure(0, weight=1)

        btn_row = ctk.CTkFrame(run_card, fg_color="transparent")
        btn_row.grid(row=0, column=0, padx=18, pady=(16, 8), sticky="ew")
        btn_row.grid_columnconfigure(0, weight=1)
        btn_row.grid_columnconfigure(1, weight=1)

        self.run_btn = ctk.CTkButton(
            btn_row,
            text="🚀  RUN / RESUME PROJECT",
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#10B981",
            hover_color="#059669",
            height=50,
            command=self.run_project,
        )
        self.run_btn.grid(row=0, column=0, padx=(0, 6), sticky="ew")

        self.queue_btn = ctk.CTkButton(
            btn_row,
            text="➕  ADD TO MASTER QUEUE",
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#8B5CF6",
            hover_color="#7C3AED",
            height=50,
            command=self._add_to_master_queue,
        )
        self.queue_btn.grid(row=0, column=1, padx=(6, 0), sticky="ew")

        self.build_status = ctk.CTkLabel(run_card, text="Ready • Click Run to build final video", font=ctk.CTkFont(size=12, weight="bold"))
        self.build_status.grid(row=1, column=0, padx=18, pady=(0, 10), sticky="w")

        ctk.CTkLabel(run_card, text="Execution Logs", font=ctk.CTkFont(size=13, weight="bold")).grid(row=2, column=0, padx=18, pady=(8, 4), sticky="w")

        self.log_box = ctk.CTkTextbox(run_card, height=180, font=ctk.CTkFont(family="Consolas", size=12))
        self.log_box.grid(row=3, column=0, padx=18, pady=(0, 16), sticky="ew")
        self.log_box.configure(state="disabled")

        self.after(50, self._auto_load_voices_on_init)

    def _auto_load_voices_on_init(self):
        if getattr(self, "_voices_loaded_once", False) and getattr(self, "voices", None):
            return
        self._voices_loaded_once = True
        try:
            import voice_cache
            key = voice_cache.load_api_key()
            if hasattr(self, "api_key") and key:
                try:
                    self.api_key.delete(0, "end")
                    self.api_key.insert(0, key)
                except Exception:
                    pass
            cached = voice_cache.load_voices_cached(force_refresh=False)
            if cached:
                self._update_voices_ui(cached)
            else:
                self.fetch_api_data()
        except Exception:
            self.fetch_api_data()

    def _file_row(self, parent, row, label_text, command, hint):
        ctk.CTkLabel(parent, text=label_text).grid(row=row, column=0, padx=14, pady=6, sticky="w")
        entry = ctk.CTkEntry(parent, placeholder_text=hint)
        entry.grid(row=row, column=1, padx=4, pady=6, sticky="ew")
        ctk.CTkButton(parent, text="Browse", width=85, command=command).grid(row=row, column=2, padx=(4, 14), pady=6, sticky="e")
        return entry

    def _choose_video(self): self._set_path(self.video_entry, filedialog.askopenfilename(filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm *.ts"), ("All files", "*.*")]))
    def _choose_script(self): self._set_path(self.script_entry, filedialog.askopenfilename(filetypes=[("Script Text", "*.txt"), ("All files", "*.*")]))
    def _choose_plan(self): self._set_path(self.plan_entry, filedialog.askopenfilename(filetypes=[("Edit Plan JSON", "*.json"), ("Text Files", "*.txt"), ("All files", "*.*")]))
    def _choose_logo(self): self._set_path(self.logo_entry, filedialog.askopenfilename(filetypes=[("Image", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All files", "*.*")]))
    def _choose_custom_font(self): self._set_path(self.custom_font_entry, filedialog.askopenfilename(filetypes=[("Font files", "*.ttf *.otf *.woff *.woff2"), ("All files", "*.*")]))
    def _choose_output(self): self._set_path(self.output_entry, filedialog.asksaveasfilename(defaultextension=".mp4", filetypes=[("MP4 Video", "*.mp4"), ("All files", "*.*")]))
    def _choose_cache(self): self._set_path(self.cache_entry, filedialog.askdirectory())
    def _choose_intros(self):
        files = filedialog.askopenfilenames(filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm *.ts"), ("All files", "*.*")])
        if files: self.intro_entry.delete(0, "end"); self.intro_entry.insert(0, "; ".join(files))

    def choose_existing_bgm(self):
        files = filedialog.askopenfilenames(filetypes=[("Audio", "*.mp3 *.wav *.m4a *.aac *.flac")])
        if files:
            self.bgm_files = list(files)
            self._refresh_bgm_playlist_ui()

    def choose_uploaded_voiceover(self):
        files = filedialog.askopenfilenames(filetypes=[("Audio", "*.mp3 *.wav *.m4a *.aac *.flac")])
        if files:
            self.uploaded_voiceover_files = list(files)
            self._refresh_uploaded_voice_ui()

    def _refresh_bgm_playlist_ui(self):
        if not self.bgm_files:
            self.bgm_playlist_summary.configure(text="No tracks selected")
            self.bgm_status.configure(text="Select or generate BGM track", text_color="gray70")
        else:
            names = [Path(p).name for p in self.bgm_files]
            summary = f"{len(names)} track(s): " + ", ".join(names[:2])
            if len(names) > 2:
                summary += f" +{len(names)-2} more"
            self.bgm_playlist_summary.configure(text=summary)
            self.bgm_status.configure(text=f"Ready • {len(self.bgm_files)} BGM track(s) in rotation", text_color="#10B981")

    def _refresh_uploaded_voice_ui(self):
        if not self.uploaded_voiceover_files:
            self.uploaded_voice_summary.configure(text="No audio files chosen")
        else:
            names = [Path(p).name for p in self.uploaded_voiceover_files]
            summary = f"{len(names)} file(s): " + ", ".join(names[:2])
            if len(names) > 2:
                summary += f" +{len(names)-2} more"
            self.uploaded_voice_summary.configure(text=summary)

    def _voiceover_mode_changed(self, mode: str):
        if mode == "Generate Voiceover":
            self.gen_voice_frame.grid()
            self.upload_voice_frame.grid_remove()
        else:
            self.gen_voice_frame.grid_remove()
            self.upload_voice_frame.grid()

    def _render_mode_changed(self, mode: str):
        pass

    def _set_path(self, entry: ctk.CTkEntry, path: str):
        if path:
            entry.delete(0, "end")
            entry.insert(0, path)

    def clear_cache_folder(self):
        cache_dir = self.cache_entry.get().strip()
        if not cache_dir:
            out_abs = os.path.abspath(self.output_entry.get().strip() or "final_recap.mp4")
            base_dir = os.path.dirname(out_abs)
            base_name = os.path.splitext(os.path.basename(out_abs))[0]
            cache_dir = os.path.join(base_dir, f".{base_name}_recap_cache")
        if not os.path.exists(cache_dir):
            messagebox.showinfo("Cache Clear", f"No cache folder found at:\n{cache_dir}")
            return
        if messagebox.askyesno("Confirm Clear Cache", f"Are you sure you want to delete all cached audio and video files in:\n{cache_dir}?"):
            try:
                shutil.rmtree(cache_dir)
                messagebox.showinfo("Cache Cleared", "Script and audio cache folder deleted successfully.")
            except Exception as e:
                messagebox.showerror("Error Clearing Cache", str(e))

    def fetch_api_data(self):
        key = self.api_key.get().strip() or "sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt"
        self.api_status.configure(text="Fetching voices via AI33Pro v3...", text_color="#3B82F6")

        def worker():
            try:
                import voice_cache
                voice_cache.save_api_key(key)
                v_list = voice_cache.load_voices_cached(api_key=key, force_refresh=True)
                self._post_ui(self._update_voices_ui, v_list)
            except Exception as e:
                self._post_ui(self._update_voices_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _update_voices_ui(self, voices):
        self.voices = voices or []
        self._filter_voices()
        if self.voices:
            first_vid = self.voices[0].get("voice_id") or "elevenlabs_hpp4J3VqNfWAUOO0d1Us"
            if hasattr(self, "voice_id"):
                try:
                    if isinstance(self.voice_id, ctk.CTkEntry) and not self.voice_id.get().strip():
                        self.voice_id.insert(0, first_vid)
                    elif isinstance(self.voice_id, ctk.CTkComboBox) and not self.voice_id.get().strip():
                        self.voice_id.set(first_vid)
                except Exception:
                    pass
        self.api_status.configure(text=f"Loaded {len(self.voices)} voices from AI33Pro ✓", text_color="#10B981")

    def _update_voices_error(self, err: str):
        self.api_status.configure(text=f"Voice Load Error: {err[:30]}", text_color="#EF4444")

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
        if hasattr(self, "submodel_menu"):
            self.submodel_menu.configure(values=options)
            self.submodel_menu.set(options[0])
        self._filter_voices()

    def _select_voice_id(self, vid: str):
        if hasattr(self, "voice_id"):
            if isinstance(self.voice_id, ctk.CTkEntry):
                self.voice_id.delete(0, "end")
                self.voice_id.insert(0, vid)
            elif isinstance(self.voice_id, ctk.CTkComboBox):
                self.voice_id.set(vid)
        self._filter_voices()

    def _preview_voice_inline(self, name: str, vid: str):
        key = self.api_key.get().strip() if hasattr(self, "api_key") else "sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt"
        out_p = os.path.join(os.environ.get("TEMP", "C:/tmp"), f"_preview_{vid[:12]}.mp3")
        
        def worker():
            try:
                from ai33_api import AI33Client
                c = AI33Client(api_key=key)
                res = c.text_to_speech_v3(text="Hello, this is a voice preview test.", voice_id=vid)
                if isinstance(res, (bytes, bytearray)) and len(res) > 500:
                    with open(out_p, "wb") as f: f.write(res)
                    try:
                        import pygame
                        pygame.mixer.init()
                        pygame.mixer.music.load(out_p)
                        pygame.mixer.music.play()
                    except Exception: pass
            except Exception as e:
                print("Preview error:", e)

        threading.Thread(target=worker, daemon=True).start()

    def _clear_voice_search(self):
        if hasattr(self, "voice_search"):
            self.voice_search.delete(0, "end")
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
            try:
                child.destroy()
            except Exception:
                pass

        if not hasattr(self, "voices") or not self.voices:
            ctk.CTkLabel(self.voice_list_scroll, text="Click 'Fetch Voices' to load AI33 voice models.", font=ctk.CTkFont(size=10), text_color="gray70").pack(pady=20)
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

            if q:
                if q not in name.lower() and q not in vid.lower() and q not in prov.lower() and q not in cat.lower() and q not in lang.lower():
                    continue

            matched_voices.append(v)

        if not matched_voices:
            ctk.CTkLabel(self.voice_list_scroll, text="No matching voices found for search/filter.", font=ctk.CTkFont(size=10), text_color="gray70").pack(pady=20)
            return

        current_selected_vid = self.voice_id.get().strip() if hasattr(self, "voice_id") else ""

        for v in matched_voices[:150]:
            vid = v.get("voice_id") or v.get("id") or ""
            name = v.get("name", "Unnamed")
            prov = v.get("provider", "ElevenLabs")
            cat = v.get("category", "")
            lang = v.get("language", "")

            is_selected = (vid == current_selected_vid or (vid and current_selected_vid.endswith(vid)))
            row_bg = "#374151" if is_selected else "#1F2937"

            row = ctk.CTkFrame(self.voice_list_scroll, fg_color=row_bg, corner_radius=6)
            row.pack(fill="x", padx=2, pady=2)

            play_btn = ctk.CTkButton(
                row, text="▶", width=30, height=24, font=ctk.CTkFont(size=10, weight="bold"),
                fg_color="#8B5CF6", hover_color="#7C3AED",
                command=lambda n=name, v_id=vid: self._preview_voice_inline(n, v_id)
            )
            play_btn.pack(side="left", padx=4, pady=3)

            info_lbl = ctk.CTkLabel(
                row, text=f"[{prov}] {name}  •  {cat or lang or 'General'}",
                font=ctk.CTkFont(size=10, weight="bold" if is_selected else "normal"),
                text_color="#06B6D4" if is_selected else "#F9FAFB",
                anchor="w"
            )
            info_lbl.pack(side="left", fill="x", expand=True, padx=4)

            sel_btn = ctk.CTkButton(
                row, text="✓ In Use" if is_selected else "Use Voice", width=70, height=24,
                font=ctk.CTkFont(size=9, weight="bold"),
                fg_color="#10B981" if is_selected else "#06B6D4",
                text_color="#000" if is_selected else "#000",
                hover_color="#059669" if is_selected else "#0891B2",
                command=lambda v_id=vid, v_name=name: self._select_voice_id(v_id, v_name)
            )
            sel_btn.pack(side="right", padx=6, pady=3)

    def _select_voice_id(self, vid: str, name: str = ""):
        if hasattr(self, "voice_id"):
            self.voice_id.delete(0, "end")
            self.voice_id.insert(0, vid)
            if hasattr(self, "api_status") and name:
                self.api_status.configure(text=f"Selected Voice: {name} ({vid}) ✓", text_color="#10B981")
            self._filter_voices()

    def _preview_voice_inline(self, name: str, vid: str):
        self.play_single_voice_preview({"voice_id": vid, "name": name})

    def _clear_voice_search(self):
        if hasattr(self, "voice_search"):
            self.voice_search.delete(0, "end")
        self._filter_voices()

    def _apply_api(self, models, voices, cached=False):
        self.models, self.voices = models or [], voices or []
        self.model_map = {}
        for m in self.models:
            if not isinstance(m, dict): continue
            mid = m.get("model_id") or m.get("id") or ""
            display = f"{m.get('name', mid)} [{mid}]"
            self.model_map[display] = mid

        self.voice_map = {}
        for v in self.voices:
            if not isinstance(v, dict): continue
            vid = v.get("voice_id") or v.get("id") or ""
            if not vid: continue
            provider = v.get("provider", "AI33")
            name = v.get("name", "Unnamed")
            category = v.get("category", "Voice")
            display = f"[{provider}] {name} ({category}) • {vid}"
            self.voice_map[display] = vid

        if hasattr(self, "submodel_menu"):
            mvals = ["All Models / Sub-Models"] + list(self.model_map)
            try: self.submodel_menu.configure(values=mvals)
            except Exception: pass

        if hasattr(self, "voice_id") and self._restore_voice_id:
            self.voice_id.delete(0, "end")
            self.voice_id.insert(0, self._restore_voice_id)

        self._filter_voices()
        if cached:
            self.api_status.configure(text=f"Loaded {len(self.voices)} cached voices")
        else:
            self.api_status.configure(text=f"Connected • {len(self.models)} models • {len(self.voices)} voices loaded")

    def _api_failed(self, err: str):
        self.api_status.configure(text=f"Fetch note: {err}. Loaded built-in voice library ✓", text_color="#F59E0B")
        if not self.voices:
            from ai33_api import AI33Client
            client = AI33Client()
            self._apply_api(client.fetch_models(), client.fetch_voices(), cached=True)

    def _language_changed(self, choice=None): pass
    def _model_changed(self, choice=None):
        self._filter_voices()

    def _voice_changed(self, choice=None): pass

    def _selected_model_id(self) -> str:
        label = self.model_menu.get() if hasattr(self, "model_menu") else ""
        return self.model_map.get(label, label or "eleven_multilingual_v2")

    def _selected_voice_id(self) -> str:
        label = self.voice_id.get().strip() if hasattr(self, "voice_id") else ""
        vid = self.voice_map.get(label, "")
        if not vid:
            if "•" in label:
                vid = label.split("•")[-1].strip()
            elif "(" in label and label.endswith(")"):
                vid = label[label.rfind("(")+1 : -1].strip()
            else:
                vid = label
        if vid:
            valid_prefixes = ("elevenlabs_", "minimax_", "fishaudio_")
            if not any(vid.startswith(p) for p in valid_prefixes):
                mid = self._selected_model_id().lower()
                if "minimax" in mid: vid = f"minimax_{vid}"
                elif "fish" in mid: vid = f"fishaudio_{vid}"
                else: vid = f"elevenlabs_{vid}"
        return vid

    def _current_bgm_files(self) -> list[str]:
        if self.generated_bgm_path and os.path.exists(self.generated_bgm_path):
            return [self.generated_bgm_path]
        return self.bgm_files

    def play_single_voice_preview(self, voice_dict: dict):
        vid = voice_dict.get("voice_id") or voice_dict.get("id") or ""
        vname = voice_dict.get("name") or vid
        purl = voice_dict.get("preview_url") or ""
        key = self.api_key.get().strip() or "sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt"

        if not vid:
            messagebox.showwarning("Voice Missing", "Please select a valid Voice ID.")
            return

        self.api_status.configure(text=f"Generating/Playing preview for '{vname}'...", text_color="#3B82F6")

        def worker():
            try:
                clean_name = vid.replace('/', '_').replace(':', '_')
                sample_path = os.path.join(self.preview_cache_dir, f"preview_{clean_name}.mp3")

                # 1. If audio already cached, play immediately!
                if os.path.exists(sample_path) and os.path.getsize(sample_path) > 500:
                    self._post_ui(self._play_audio_file, sample_path)
                    return

                # 2. Try preview_url download if valid HTTP URL
                if purl and purl.startswith("http"):
                    try:
                        import urllib.request
                        req = urllib.request.Request(purl, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req, timeout=4) as resp:
                            data = resp.read()
                            if len(data) > 500:
                                with open(sample_path, "wb") as f:
                                    f.write(data)
                                self._post_ui(self._play_audio_file, sample_path)
                                return
                    except Exception:
                        pass

                # 3. Fast Zero-Failure TTS Sample Generation
                from ai33_api import ai33_tts_generate
                sample_text = f"Hello! This is a voice preview of {vname} in Recap Studio."
                if ai33_tts_generate(sample_text, vid, api_key=key, out_path=sample_path):
                    if os.path.exists(sample_path) and os.path.getsize(sample_path) > 300:
                        self._post_ui(self._play_audio_file, sample_path)
                        return

                self._post_ui(self._preview_failed, f"Unable to generate voice preview for {vid}")
            except Exception as e:
                self._post_ui(self._preview_failed, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def play_voice_preview(self):
        vid = self._selected_voice_id()
        self.play_single_voice_preview({"voice_id": vid, "name": vid})

    def _play_audio_file(self, path: str):
        if not path or not os.path.exists(path):
            return
        self.api_status.configure(text="Playing voice preview audio... ▶", text_color="#10B981")
        self.stop_preview()
        try:
            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            try:
                pygame.mixer.music.stop()
                if hasattr(pygame.mixer.music, "unload"):
                    pygame.mixer.music.unload()
            except Exception:
                pass
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            return
        except Exception as pe:
            # Fallback to ffplay
            try:
                if os.name == "nt":
                    si = subprocess.STARTUPINFO()
                    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    si.wShowWindow = 0
                    flags = {"creationflags": 0x08000000, "startupinfo": si}
                else:
                    flags = {}
                self.preview_process = subprocess.Popen(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path], **flags)
            except Exception as e:
                messagebox.showerror("Playback Error", f"Could not play audio:\n{e}")

    def stop_preview(self):
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

    def _preview_failed(self, err: str):
        self.api_status.configure(text=f"Preview failed: {err}", text_color="#EF4444")
        messagebox.showerror("Preview failed", str(err))

    def generate_ai_bgm(self):
        key = self.api_key.get().strip()
        prompt = self.bgm_prompt.get().strip()
        if not key or not prompt:
            messagebox.showerror("BGM Error", "API Key and BGM Prompt are required.")
            return
        self.bgm_status.configure(text="Generating AI BGM track…", text_color="#3B82F6")
        def worker():
            try:
                out_mp3 = os.path.join(self.preview_cache_dir, f"bgm_{hashlib.md5(prompt.encode()).hexdigest()[:8]}.mp3")
                generate_music(prompt, out_mp3, key)
                self.generated_bgm_path = out_mp3
                self._post_ui(self._bgm_generated_success, out_mp3)
            except Exception as e:
                self._post_ui(self._bgm_generated_failed, str(e))
        threading.Thread(target=worker, daemon=True).start()

    def _bgm_generated_success(self, path: str):
        self.bgm_playlist_summary.configure(text=f"AI Generated BGM: {Path(path).name}")
        self.bgm_status.configure(text="AI BGM generated successfully ✓", text_color="#10B981")

    def _bgm_generated_failed(self, err: str):
        self.bgm_status.configure(text=f"BGM Generation failed: {err}", text_color="#EF4444")
        messagebox.showerror("BGM Error", f"Could not generate AI BGM:\n{err}")

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
        required["Voice ID"] = self._selected_voice_id()
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
            temp_preview = os.path.abspath(".preview_cache/canvas_editor_base.jpg")
            os.makedirs(os.path.dirname(temp_preview), exist_ok=True)

            if video_path and os.path.exists(video_path):
                subprocess.run(["ffmpeg", "-y", "-ss", "00:00:02", "-i", video_path, "-vframes", "1", "-s", "1280x720", temp_preview], capture_output=True)
            else:
                subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=181B2A:s=1280x720:d=1", "-vframes", "1", temp_preview], capture_output=True)

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
            out_preview = os.path.abspath(".preview_cache/logo_caption_preview.png")

            fsize = int(self.caption_size_slider.get())
            l_width = int(self.logo_width_slider.get())

            font_p = self.custom_font_entry.get().strip() if hasattr(self, "custom_font_entry") else ""
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

    def _add_to_master_queue(self):
        try:
            r = self._validate_run()
        except Exception as e:
            messagebox.showerror("Cannot Queue", str(e), parent=self.winfo_toplevel())
            return

        out_path = r.get("Final output")
        if not out_path:
            default_name = f"Recap_Studio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            out_path = filedialog.asksaveasfilename(
                defaultextension=".mp4",
                initialfile=default_name,
                filetypes=[("MP4 Video", "*.mp4")],
                title="Save Queued Recap Video As...",
                parent=self.winfo_toplevel()
            )
            if not out_path:
                return
            r["Final output"] = out_path

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

        task_title = f"Recap Studio — {Path(out_path).name}"

        def execute_recap_job(progress_cb, status_cb):
            status_cb("Starting Recap Studio render...")
            progress_cb(5.0)

            def _log_cb(msg):
                status_cb(msg)
                if "%" in msg:
                    try:
                        import re
                        m = re.search(r'(\d+)%', msg)
                        if m:
                            progress_cb(float(m.group(1)))
                    except:
                        pass

            out = build_project(
                video_path=r["Source video"], script_path=r["Rewritten script"], edit_plan_path=r["Edit plan"],
                voice_id=r["Voice ID"], tts_model_id=settings["model"], elevenlabs_key=r["API key"],
                out_path=out_path, cache_dir=settings["cache"], logo_path=settings["logo"],
                logo_position=settings["logo_position"],
                bgm_path=(settings["bgm_files"][0] if len(settings["bgm_files"]) == 1 else None),
                bgm_paths=settings["bgm_files"], bgm_volume=settings["bgm_volume"], bgm_loop=settings["bgm_loop"],
                voice_volume=settings["voice_volume"], stability=settings["stability"], similarity_boost=settings["similarity"],
                narration_speed=settings["narration_speed"], render_preset=settings["render_preset"], log_callback=_log_cb,
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
            progress_cb(100.0)
            return out

        try:
            import master_queue
            task = master_queue.MASTER_QUEUE.add_task(
                title=task_title,
                tool_name="Recap Studio",
                execute_fn=execute_recap_job,
                output_path=out_path
            )

            # Silently reset screen for next recap video
            try:
                self.video_entry.delete(0, "end")
                self.script_entry.delete(0, "end")
                self.plan_entry.delete(0, "end")
                self.output_entry.delete(0, "end")
                self.build_status.configure(text="✓ Added to Master Queue • Screen ready for next video", text_color="#10B981")
            except Exception:
                pass

            messagebox.showinfo(
                "Task Added to Master Queue",
                f"✓ '{task_title}' has been sent to the Master Render Queue!\n\n"
                f"• Auto-Sequential background rendering is active.\n"
                f"• If a render is already in progress, this video will automatically start next in line.\n"
                f"• Screen has been cleared for your next recap video.\n"
                f"• Track live progress in the '🗂 Queue' tab.",
                parent=self.winfo_toplevel()
            )
        except Exception as e:
            messagebox.showerror("Queue Error", f"Failed to add task to Master Queue:\n{e}", parent=self.winfo_toplevel())

    def _done(self, out):
        self.running = False
        self.run_btn.configure(state="normal", text="▶  RUN / RESUME PROJECT")
        self.build_status.configure(text=f"Done: {Path(out).name}")
        try:
            import auth_manager
            auth_manager.record_video_export(tool_name="Recap Studio", file_path=str(out))
        except Exception:
            pass
        messagebox.showinfo("Recap Studio V2.8", f"Final video created:\n{out}")


    def _failed(self, err: str):
        self.running = False
        self.run_btn.configure(state="normal", text="▶  RUN / RESUME PROJECT")
        self.build_status.configure(text=f"Failed: {err}", text_color="#EF4444")
        messagebox.showerror("Build Failed", f"Recap Engine failed:\n{err}")

    def _load_env(self):
        if not os.path.exists(self.settings_path): return
        try:
            with open(self.settings_path, "r", encoding="utf-8") as f: saved = json.load(f)
        except Exception: return

        if saved.get("remember_api") and saved.get("api_key"):
            self.api_key.insert(0, saved["api_key"])
        self._restore_model_id = saved.get("model_id", "")
        self._restore_voice_id = saved.get("voice_id", "")

        cached_models = saved.get("cached_models", [])
        cached_voices = saved.get("cached_voices", [])
        if (cached_models or cached_voices) and hasattr(self, "_apply_api"):
            self._apply_api(cached_models, cached_voices, cached=True)
        elif self._restore_voice_id and hasattr(self, "voice_id"):
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

        for combo_attr, key_name, default in [
            ("output_language", "output_language", "English"),
            ("source_language", "source_language", "Auto / mixed"),
            ("render_speed", "render_speed", "Fast (recommended)"),
            ("logo_position", "logo_position", "Top-Right"),
            ("caption_preset", "caption_preset", "CapCut Yellow Pop"),
            ("caption_font", "caption_font", "Impact"),
            ("caption_position", "caption_position", "Bottom-Center (CapCut Default)"),
            ("caption_case", "caption_case", "ALL CAPS"),
            ("caption_words_per_line", "caption_words_per_line", "1 Word (CapCut Pop)"),
            ("movie_duration", "movie_duration", "1 Hour (3600s)"),
        ]:
            if hasattr(self, combo_attr):
                combo = getattr(self, combo_attr)
                val = saved.get(key_name, default)
                try: combo.set(val)
                except Exception: pass

        if hasattr(self, "enable_logo"):
            if saved.get("enable_logo", True): self.enable_logo.select()
            else: self.enable_logo.deselect()

        if hasattr(self, "enable_captions"):
            if saved.get("enable_captions", True): self.enable_captions.select()
            else: self.enable_captions.deselect()

        if hasattr(self, "enable_bgm"):
            if saved.get("enable_bgm", True): self.enable_bgm.select()
            else: self.enable_bgm.deselect()

        if hasattr(self, "bgm_loop"):
            if saved.get("bgm_loop", True): self.bgm_loop.select()
            else: self.bgm_loop.deselect()

        rmode = saved.get("render_mode", "Render Video")
        if rmode in {"Render Video", "Render Movie"} and hasattr(self, "render_mode"):
            self.render_mode.set(rmode)
            if hasattr(self, "_render_mode_changed"):
                self._render_mode_changed(rmode)

        intro_p = saved.get("intro_paths", "")
        if intro_p and hasattr(self, "intro_entry"):
            self._set_path(self.intro_entry, intro_p)

        mode = saved.get("voiceover_mode", "Generate Voiceover")
        if mode in {"Generate Voiceover", "Upload Voiceover"} and hasattr(self, "voiceover_mode"):
            self.voiceover_mode.set(mode)
        self.uploaded_voiceover_files = [p for p in saved.get("uploaded_voiceover_files", []) if os.path.exists(p)]
        if hasattr(self, "_refresh_uploaded_voice_ui"):
            self._refresh_uploaded_voice_ui()
        self.bgm_files = [p for p in saved.get("bgm_files", []) if os.path.exists(p)]
        if hasattr(self, "_refresh_bgm_playlist_ui"):
            self._refresh_bgm_playlist_ui()

        for attr, key_name in [
            ("video_entry", "video"), ("script_entry", "script"), ("plan_entry", "plan"), ("logo_entry", "logo"),
            ("output_entry", "output"), ("cache_entry", "cache")
        ]:
            val = saved.get(key_name, "")
            if val and hasattr(self, attr):
                if key_name in ("output", "cache") or os.path.exists(val):
                    self._set_path(getattr(self, attr), val)
        if hasattr(self, "_voiceover_mode_changed") and hasattr(self, "voiceover_mode"):
            self._voiceover_mode_changed(self.voiceover_mode.get())
        if saved and hasattr(self, "api_status"):
            self.api_status.configure(text="Saved preferences loaded")

    def _collect_settings(self):
        remember = bool(self.remember_api.get()) if hasattr(self, "remember_api") else True
        return {
            "remember_api": remember,
            "api_key": self.api_key.get().strip() if (remember and hasattr(self, "api_key")) else "",
            "model_id": self._selected_model_id(),
            "voice_id": self.voice_id.get().strip() if hasattr(self, "voice_id") else "",
            "cached_models": getattr(self, "models", []),
            "cached_voices": getattr(self, "voices", []),
            "voiceover_mode": self.voiceover_mode.get() if hasattr(self, "voiceover_mode") else "Generate Voiceover",
            "uploaded_voiceover_files": getattr(self, "uploaded_voiceover_files", []),
            "output_language": self.output_language.get() if hasattr(self, "output_language") else "English",
            "source_language": self.source_language.get() if hasattr(self, "source_language") else "Auto / mixed",
            "stability": float(self.stability.get()) if hasattr(self, "stability") else 0.5,
            "similarity": float(self.similarity.get()) if hasattr(self, "similarity") else 0.75,
            "narration_speed": float(self.narration_speed.get()) if hasattr(self, "narration_speed") else 1.0,
            "parallel_tts": int(self.parallel_tts.get()) if hasattr(self, "parallel_tts") else 3,
            "logo_position": self.logo_position.get() if hasattr(self, "logo_position") else "Top-Right",
            "logo_width": int(self.logo_width_slider.get()) if hasattr(self, "logo_width_slider") else 200,
            "custom_logo_x": getattr(self, "custom_logo_x", None),
            "custom_logo_y": getattr(self, "custom_logo_y", None),
            "enable_logo": bool(self.enable_logo.get()) if hasattr(self, "enable_logo") else True,
            "enable_captions": bool(self.enable_captions.get()) if hasattr(self, "enable_captions") else True,
            "enable_bgm": bool(self.enable_bgm.get()) if hasattr(self, "enable_bgm") else True,
            "caption_preset": self.caption_preset.get() if hasattr(self, "caption_preset") else "CapCut Yellow Pop",
            "caption_font": self.caption_font.get() if hasattr(self, "caption_font") else "Impact",
            "caption_size": int(self.caption_size_slider.get()) if hasattr(self, "caption_size_slider") else 28,
            "caption_position": self.caption_position.get() if hasattr(self, "caption_position") else "Bottom-Center (CapCut Default)",
            "caption_case": self.caption_case.get() if hasattr(self, "caption_case") else "ALL CAPS",
            "caption_words_per_line": self.caption_words_per_line.get() if hasattr(self, "caption_words_per_line") else "1 Word (CapCut Pop)",
            "custom_font": self.custom_font_entry.get().strip() if hasattr(self, "custom_font_entry") else "",
            "render_mode": self.render_mode.get() if hasattr(self, "render_mode") else "Render Video",
            "movie_duration": self.movie_duration.get() if hasattr(self, "movie_duration") else "1 Hour (3600s)",
            "intro_paths": self.intro_entry.get().strip() if hasattr(self, "intro_entry") else "",
            "render_speed": self.render_speed.get() if hasattr(self, "render_speed") else "Fast (recommended)",
            "bgm_files": self._current_bgm_files() if hasattr(self, "_current_bgm_files") else [],
            "bgm_loop": bool(self.bgm_loop.get()) if hasattr(self, "bgm_loop") else True,
            "voice_volume": float(self.voice_volume.get()) if hasattr(self, "voice_volume") else 1.0,
            "bgm_volume": float(self.bgm_volume.get()) if hasattr(self, "bgm_volume") else 0.08,
            "video": self.video_entry.get().strip() if hasattr(self, "video_entry") else "",
            "script": self.script_entry.get().strip() if hasattr(self, "script_entry") else "",
            "plan": self.plan_entry.get().strip() if hasattr(self, "plan_entry") else "",
            "logo": self.logo_entry.get().strip() if hasattr(self, "logo_entry") else "",
            "output": self.output_entry.get().strip() if hasattr(self, "output_entry") else "",
            "cache": self.cache_entry.get().strip() if hasattr(self, "cache_entry") else "",
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

    def _check_env(self):
        if not hasattr(self, "env_status"): return
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
