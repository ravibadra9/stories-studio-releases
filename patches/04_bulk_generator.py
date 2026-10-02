"""
04_bulk_generator.py — Bulk Song Generation Engine for Suno Music Tool
Parses pasted song lists (Song 1, Song 2, Song 3...) into distinct blocks
and generates all songs in batch with Universal and Per-Song Style prompts.
"""

TAB_TITLE = "⚡  Bulk Generator"
TAB_ORDER = 15
TAB_GROUP = ""
TAB_ICON = "⚡"

import re
import os
import time
import threading
import tkinter as tk
import customtkinter as ctk
from pathlib import Path
from typing import List, Dict, Any, Optional

from ui_theme import THEME, FONTS
from suno_api import SunoAPI
from config_manager import load_config, save_config, get_downloads_dir


def parse_songs_text(raw_text: str) -> List[Dict[str, str]]:
    """
    Parses pasted text containing headers like 'Song 1', 'Song 2', etc.
    Supports optional per-song style tags like [Style: ...] or Style: ...
    Returns a list of dicts: [{'title': 'Song 1', 'lyrics': '...', 'style': '...'}, ...]
    """
    if not raw_text or not raw_text.strip():
        return []

    lines = raw_text.strip().split("\n")
    songs = []
    current_title = ""
    current_lyrics_lines = []
    current_style = ""

    # Regex to match headers like "Song 1", "Song 2:", "Song 3 - My Title", "[Song 4]"
    song_header_pattern = re.compile(r'^\s*\[?\s*Song\s*(\d+)[:\-\.\s]*(.*?)\]?\s*$', re.IGNORECASE)
    style_pattern = re.compile(r'^\s*\[?(?:Style|Genre|Music Style|Prompt)[:\-\s]+(.*?)\]?\s*$', re.IGNORECASE)

    for line in lines:
        match = song_header_pattern.match(line)
        if match:
            # If we were building a previous song block, save it
            if current_title or current_lyrics_lines:
                lyrics_text = "\n".join(current_lyrics_lines).strip()
                if lyrics_text or current_title:
                    songs.append({
                        "title": current_title if current_title else f"Song {len(songs)+1}",
                        "lyrics": lyrics_text,
                        "style": current_style
                    })
                current_lyrics_lines = []
                current_style = ""

            song_num = match.group(1)
            extra_title = match.group(2).strip()
            if extra_title:
                current_title = f"Song {song_num} - {extra_title}"
            else:
                current_title = f"Song {song_num}"
        else:
            s_match = style_pattern.match(line)
            if s_match:
                current_style = s_match.group(1).strip()
            else:
                current_lyrics_lines.append(line)

    # Save final song block
    if current_title or current_lyrics_lines:
        lyrics_text = "\n".join(current_lyrics_lines).strip()
        if lyrics_text or current_title:
            songs.append({
                "title": current_title if current_title else f"Song {len(songs)+1}",
                "lyrics": lyrics_text,
                "style": current_style
            })

    return songs


def create(parent_frame, boot_data=None):
    boot_data = boot_data or {}
    config = load_config()

    container = ctk.CTkFrame(parent_frame, fg_color=THEME["bg"], corner_radius=0)
    container.pack(fill="both", expand=True)
    container.grid_columnconfigure(0, weight=5, minsize=460)  # Left panel
    container.grid_columnconfigure(1, weight=5, minsize=460)  # Right panel
    container.grid_rowconfigure(0, weight=1)

    # State dictionaries & flags
    per_song_custom_styles: Dict[str, str] = {}
    is_generating = [False]
    live_card_items: List[Dict[str, Any]] = []

    # ════════════════════════════════════════════════════════════════
    # LEFT PANEL: BULK INPUTS & UNIVERSAL STYLE
    # ════════════════════════════════════════════════════════════════
    left_frame = ctk.CTkFrame(
        container,
        fg_color=THEME["card"],
        corner_radius=14,
        border_width=1,
        border_color=THEME["card_border"]
    )
    left_frame.grid(row=0, column=0, sticky="nsew", padx=(14, 7), pady=14)
    left_frame.grid_rowconfigure(3, weight=1)
    left_frame.grid_columnconfigure(0, weight=1)

    ctk.CTkLabel(
        left_frame,
        text="⚡  Bulk Song Batch Generator",
        font=FONTS["title"],
        text_color=THEME["accent"]
    ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 4))

    ctk.CTkLabel(
        left_frame,
        text="Paste your multi-song lyrics below (separated by Song 1, Song 2, Song 3...).",
        font=FONTS["small"],
        text_color=THEME["text_muted"]
    ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 10))

    # Shared Universal Style Prompt Input
    style_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
    style_frame.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 10))
    style_frame.grid_columnconfigure(0, weight=1)

    style_hdr = ctk.CTkFrame(style_frame, fg_color="transparent")
    style_hdr.pack(fill="x", pady=(0, 4))
    ctk.CTkLabel(
        style_hdr,
        text="🌐 Universal Music Style (Default Fallback)",
        font=FONTS["body_bold"],
        text_color="#38bdf8"
    ).pack(side="left")

    ctk.CTkLabel(
        style_hdr,
        text="● Applied to songs without custom style",
        font=FONTS["small"],
        text_color="#94a3b8"
    ).pack(side="right")

    style_entry = ctk.CTkEntry(
        style_frame,
        placeholder_text="e.g. indie pop, cinematic drums, emotional vocal, 120 bpm",
        height=38,
        fg_color=THEME["input_bg"],
        border_width=1,
        border_color=THEME["input_border"],
        corner_radius=8,
        font=FONTS["body"],
        text_color=THEME["text"]
    )
    style_entry.pack(fill="x")
    style_entry.insert(0, "indie pop, emotional, cinematic drums, high quality studio sound")

    # Pasted Songs Text Box
    paste_box_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
    paste_box_frame.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 10))
    paste_box_frame.grid_columnconfigure(0, weight=1)
    paste_box_frame.grid_rowconfigure(1, weight=1)

    lyrics_hdr = ctk.CTkFrame(paste_box_frame, fg_color="transparent")
    lyrics_hdr.grid(row=0, column=0, sticky="ew", pady=(0, 4))
    lyrics_hdr.grid_columnconfigure(0, weight=1)

    ctk.CTkLabel(
        lyrics_hdr,
        text="Paste Songs List (Song 1, Song 2, Song 3...):",
        font=FONTS["body_bold"],
        text_color=THEME["text"]
    ).grid(row=0, column=0, sticky="w")

    def _paste_clipboard_action():
        try:
            txt = container.clipboard_get()
            if txt:
                songs_textbox.delete("1.0", "end")
                songs_textbox.insert("1.0", txt)
                _on_text_change()
        except Exception:
            pass

    def _clear_lyrics_action():
        songs_textbox.delete("1.0", "end")
        _on_text_change()

    ctk.CTkButton(
        lyrics_hdr,
        text="📋 Paste",
        width=70,
        height=24,
        fg_color="#4f46e5",
        hover_color="#4338ca",
        font=FONTS["small_bold"],
        text_color="#ffffff",
        corner_radius=6,
        command=_paste_clipboard_action
    ).grid(row=0, column=1, padx=(4, 2))

    ctk.CTkButton(
        lyrics_hdr,
        text="🗑️ Clear",
        width=60,
        height=24,
        fg_color="#334155",
        hover_color="#475569",
        font=FONTS["small_bold"],
        text_color="#ffffff",
        corner_radius=6,
        command=_clear_lyrics_action
    ).grid(row=0, column=2, padx=2)

    songs_textbox = ctk.CTkTextbox(
        paste_box_frame,
        fg_color=THEME["input_bg"],
        border_width=1,
        border_color=THEME["input_border"],
        corner_radius=10,
        font=FONTS["body"],
        text_color=THEME["text"],
        wrap="word"
    )
    songs_textbox.grid(row=1, column=0, sticky="nsew")

    # Sample default template inside text box
    sample_text = """Song 1 - Border Lights
[Verse 1]
I walk the line between two lives
Underneath the border lights
Searching for a brand new sign

Song 2 - Midnight Shadows
[Verse 1]
Midnight shadows on the street
Dancing to the city beat
Echoes in the quiet night

Song 3 - River of Hope
[Verse 1]
Sky above and earth below
Watching all the rivers flow
Singing songs of hope and dream"""
    songs_textbox.insert("1.0", sample_text)

    # Bottom Actions: Parse & Generate All
    left_bottom = ctk.CTkFrame(left_frame, fg_color="#121318", corner_radius=12, height=64)
    left_bottom.grid(row=4, column=0, sticky="ew", padx=16, pady=16)
    left_bottom.grid_propagate(False)

    parsed_count_lbl = ctk.CTkLabel(left_bottom, text="Parsed: 3 Songs", font=FONTS["body_bold"], text_color=THEME["accent"])
    parsed_count_lbl.pack(side="left", padx=16)

    btn_start_bulk = ctk.CTkButton(
        left_bottom,
        text="🚀 Generate All Songs",
        font=("Segoe UI", 13, "bold"),
        fg_color=THEME["accent"],
        hover_color=THEME["accent_hover"],
        text_color=THEME["accent_text"],
        corner_radius=18,
        height=40,
        width=175
    )
    btn_start_bulk.pack(side="right", padx=12)

    # ════════════════════════════════════════════════════════════════
    # RIGHT PANEL: PARSED SONGS WITH INDIVIDUAL STYLE BOXES & QUEUE
    # ════════════════════════════════════════════════════════════════
    right_frame = ctk.CTkFrame(
        container,
        fg_color=THEME["card"],
        corner_radius=14,
        border_width=1,
        border_color=THEME["card_border"]
    )
    right_frame.grid(row=0, column=1, sticky="nsew", padx=(7, 14), pady=14)
    right_frame.grid_rowconfigure(1, weight=1)
    right_frame.grid_columnconfigure(0, weight=1)

    right_header = ctk.CTkFrame(right_frame, fg_color="transparent", height=44)
    right_header.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 0))
    right_header.grid_columnconfigure(0, weight=1)

    ctk.CTkLabel(
        right_header,
        text="🎵 Song Queue & Individual Styles",
        font=FONTS["header"],
        text_color=THEME["text"]
    ).grid(row=0, column=0, sticky="w")

    ctk.CTkLabel(
        right_header,
        text="💡 Leave blank to use Universal Style",
        font=FONTS["small"],
        text_color="#94a3b8"
    ).grid(row=0, column=1, sticky="e")

    bulk_scroll = ctk.CTkScrollableFrame(right_frame, fg_color="transparent")
    bulk_scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
    bulk_scroll.grid_columnconfigure(0, weight=1)

    def _render_song_cards():
        if is_generating[0]:
            return

        raw_text = songs_textbox.get("1.0", "end-1c")
        parsed_songs = parse_songs_text(raw_text)
        parsed_count_lbl.configure(text=f"Parsed: {len(parsed_songs)} Song(s)")

        # Clear scroll area
        for w in bulk_scroll.winfo_children():
            w.destroy()

        live_card_items.clear()

        if not parsed_songs:
            empty_box = ctk.CTkFrame(bulk_scroll, fg_color="#121520", corner_radius=12, border_width=1, border_color="#20293d")
            empty_box.pack(fill="x", padx=12, pady=40, ipady=24)
            ctk.CTkLabel(empty_box, text="📝 No Songs Detected", font=FONTS["header"], text_color="#94a3b8").pack(pady=(10, 4))
            ctk.CTkLabel(
                empty_box,
                text="Format your pasted lyrics on the left with 'Song 1', 'Song 2', etc.\nEach song will appear here with its own individual Music Style box.",
                font=FONTS["body"],
                text_color="#64748b",
                justify="center"
            ).pack(pady=(0, 10))
            return

        for s_idx, song in enumerate(parsed_songs, 1):
            s_title = song["title"]
            s_lyrics = song["lyrics"]
            song_key = s_title

            # Lookup previously saved style, or parse from [Style: ...] in text
            if song_key in per_song_custom_styles:
                init_val = per_song_custom_styles[song_key]
            elif str(s_idx) in per_song_custom_styles:
                init_val = per_song_custom_styles[str(s_idx)]
            elif f"Song {s_idx}" in per_song_custom_styles:
                init_val = per_song_custom_styles[f"Song {s_idx}"]
            else:
                init_val = song.get("style", "").strip()
                per_song_custom_styles[song_key] = init_val
                per_song_custom_styles[str(s_idx)] = init_val
                per_song_custom_styles[f"Song {s_idx}"] = init_val

            card = ctk.CTkFrame(
                bulk_scroll,
                fg_color="#131622",
                corner_radius=10,
                border_width=1,
                border_color="#a855f7" if init_val else "#1e293b"
            )
            card.pack(fill="x", pady=6, padx=2, ipady=4)
            card.grid_columnconfigure(1, weight=1)

            # Left status pill / index badge
            st_lbl = ctk.CTkLabel(
                card,
                text=f"🎵 #{s_idx}",
                font=FONTS["body_bold"],
                text_color="#38bdf8",
                fg_color="#0e2439",
                corner_radius=6,
                padx=8,
                pady=4
            )
            st_lbl.grid(row=0, column=0, padx=(10, 6), pady=(10, 4), sticky="n")

            # Center info frame
            center_f = ctk.CTkFrame(card, fg_color="transparent")
            center_f.grid(row=0, column=1, sticky="nsew", padx=6, pady=8)
            center_f.grid_columnconfigure(0, weight=1)

            # Title & Preview row
            title_row = ctk.CTkFrame(center_f, fg_color="transparent")
            title_row.pack(fill="x", pady=(0, 2))
            title_row.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                title_row,
                text=s_title,
                font=FONTS["body_bold"],
                text_color=THEME["text"],
                anchor="w"
            ).grid(row=0, column=0, sticky="w")

            lines_count = len([l for l in s_lyrics.split("\n") if l.strip()])
            words_count = len(s_lyrics.split())
            meta_txt = f"{lines_count} lines • {words_count} words"
            ctk.CTkLabel(title_row, text=meta_txt, font=FONTS["small"], text_color="#64748b").grid(row=0, column=1, sticky="e")

            # Lyrics preview
            preview_clean = " ".join(s_lyrics.split())
            if len(preview_clean) > 75:
                preview_clean = preview_clean[:72] + "..."
            ctk.CTkLabel(
                center_f,
                text=f"Lyrics: {preview_clean if preview_clean else '(No lyrics entered)'}",
                font=FONTS["small"],
                text_color=THEME["text_muted"],
                anchor="w"
            ).pack(fill="x", pady=(0, 6))

            # ── PARTICULAR SONG MUSIC STYLE BOX ──
            style_row = ctk.CTkFrame(center_f, fg_color="#0a0d14", corner_radius=6, border_width=1, border_color="#1e2738")
            style_row.pack(fill="x", pady=(2, 6))
            style_row.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(
                style_row,
                text="🎨 Style:",
                font=FONTS["small_bold"],
                text_color="#38bdf8"
            ).grid(row=0, column=0, padx=(8, 4), pady=4, sticky="w")

            song_style_var = ctk.StringVar(value=init_val)

            style_entry_song = ctk.CTkEntry(
                style_row,
                textvariable=song_style_var,
                placeholder_text="Uses Universal Style... (or enter custom style here)",
                height=26,
                fg_color="#141926",
                border_width=1,
                border_color="#a855f7" if init_val else "#273248",
                corner_radius=6,
                font=FONTS["small"],
                text_color="#f8fafc"
            )
            style_entry_song.grid(row=0, column=1, sticky="ew", padx=4, pady=4)

            # Paste Style Button
            btn_paste_s = ctk.CTkButton(
                style_row,
                text="📋 Paste",
                width=68,
                height=24,
                fg_color="#6366f1",
                hover_color="#4f46e5",
                font=FONTS["small_bold"],
                text_color="#ffffff",
                corner_radius=5
            )
            btn_paste_s.grid(row=0, column=2, padx=3, pady=4)

            # Badge Label (🎯 Custom Active vs 🌐 Universal Style)
            badge_lbl = ctk.CTkLabel(
                style_row,
                text="🎯 Custom Style" if init_val else "🌐 Universal Style",
                font=FONTS["small_bold"],
                text_color="#c084fc" if init_val else "#64748b",
                fg_color="#2d1b4e" if init_val else "#1a2234",
                corner_radius=4,
                padx=6,
                pady=2
            )
            badge_lbl.grid(row=0, column=3, padx=3, pady=4)

            # Clear Button
            btn_clear_s = ctk.CTkButton(
                style_row,
                text="✕",
                width=28,
                height=24,
                fg_color="#334155" if init_val else "#1e293b",
                hover_color="#475569",
                font=FONTS["small_bold"],
                text_color="#cbd5e1" if init_val else "#64748b",
                corner_radius=5
            )
            btn_clear_s.grid(row=0, column=4, padx=(2, 6), pady=4)

            def _paste_style(sk=song_key, sidx=s_idx, sv=song_style_var, bp=btn_paste_s):
                clip = ""
                for getter in [container.clipboard_get, card.clipboard_get]:
                    try:
                        clip = getter().strip()
                        if clip:
                            break
                    except Exception:
                        pass
                if clip:
                    clean_c = " ".join(clip.split())
                    sv.set(clean_c)
                    per_song_custom_styles[sk] = clean_c
                    per_song_custom_styles[str(sidx)] = clean_c
                    per_song_custom_styles[f"Song {sidx}"] = clean_c
                    bp.configure(text="✓ Done", fg_color="#10b981")
                    container.after(1000, lambda: bp.configure(text="📋 Paste", fg_color="#6366f1"))
                else:
                    bp.configure(text="Empty", fg_color="#f59e0b")
                    container.after(1000, lambda: bp.configure(text="📋 Paste", fg_color="#6366f1"))

            btn_paste_s.configure(command=_paste_style)

            def _on_style_var_change(*args, sk=song_key, sidx=s_idx, sv=song_style_var, bl=badge_lbl, se=style_entry_song, bc=btn_clear_s, cd=card):
                val = sv.get().strip()
                per_song_custom_styles[sk] = val
                per_song_custom_styles[str(sidx)] = val
                per_song_custom_styles[f"Song {sidx}"] = val
                if val:
                    bl.configure(text="🎯 Custom Style", text_color="#c084fc", fg_color="#2d1b4e")
                    se.configure(border_color="#a855f7")
                    cd.configure(border_color="#a855f7")
                    bc.configure(fg_color="#334155", text_color="#cbd5e1")
                else:
                    bl.configure(text="🌐 Universal Style", text_color="#64748b", fg_color="#1a2234")
                    se.configure(border_color="#273248")
                    cd.configure(border_color="#1e293b")
                    bc.configure(fg_color="#1e293b", text_color="#64748b")

            song_style_var.trace_add("write", _on_style_var_change)

            def _clear_style(sk=song_key, sidx=s_idx, sv=song_style_var):
                sv.set("")
                per_song_custom_styles[sk] = ""
                per_song_custom_styles[str(sidx)] = ""
                per_song_custom_styles[f"Song {sidx}"] = ""

            btn_clear_s.configure(command=_clear_style)

            # Progress bar
            p_bar = ctk.CTkProgressBar(center_f, progress_color=THEME["accent"], fg_color="#1a202c", height=6)
            p_bar.pack(fill="x", pady=(2, 0))
            p_bar.set(0)

            # Action buttons slot (Play / Save)
            act_frame = ctk.CTkFrame(card, fg_color="transparent")
            act_frame.grid(row=0, column=2, padx=10, pady=10)

            live_card_items.append({
                "title": s_title,
                "lyrics": s_lyrics,
                "song_key": song_key,
                "s_idx": s_idx,
                "song_style_var": song_style_var,
                "card": card,
                "st_lbl": st_lbl,
                "badge_lbl": badge_lbl,
                "p_bar": p_bar,
                "act_frame": act_frame
            })

    # Debounced text change handler
    _debounce_timer = [None]

    def _on_text_change(event=None):
        if is_generating[0]:
            return
        if _debounce_timer[0] is not None:
            container.after_cancel(_debounce_timer[0])
        _debounce_timer[0] = container.after(300, _render_song_cards)

    songs_textbox.bind("<KeyRelease>", _on_text_change)
    songs_textbox.bind("<<Paste>>", lambda e: container.after(50, _on_text_change))

    # ════════════════════════════════════════════════════════════════
    # GENERATION PIPELINE (PARALLEL WORKER & POLLER)
    # ════════════════════════════════════════════════════════════════
    def _trigger_bulk_generation():
        raw_text = songs_textbox.get("1.0", "end-1c")
        parsed_songs = parse_songs_text(raw_text)
        universal_style = style_entry.get().strip()

        if not parsed_songs:
            _show_alert("No Songs Found", "Please paste text containing 'Song 1', 'Song 2', etc.")
            return

        cfg = load_config()
        key = cfg.get("api_key", "")
        if not key:
            _show_alert("API Key Required", "Please configure your xi-api-key / AI33Pro key in Settings!")
            return

        is_generating[0] = True
        btn_start_bulk.configure(state="disabled", text="⏳ Starting Batch...")

        if len(live_card_items) != len(parsed_songs):
            _render_song_cards()

        api_client = SunoAPI(key)

        def _bulk_worker():
            for item in live_card_items:
                time.sleep(1)  # Stagger requests slightly
                s_title = item["title"]
                s_lyrics = item["lyrics"]
                st_lbl = item["st_lbl"]
                p_bar = item["p_bar"]
                sv = item["song_style_var"]

                # Particular song style override logic:
                # If user entered something in this particular song's style box, use it!
                # Otherwise, fall back to universal music style!
                custom_s = sv.get().strip() or per_song_custom_styles.get(s_title, "").strip() or per_song_custom_styles.get(str(item["s_idx"]), "").strip()
                effective_style = custom_s if custom_s else universal_style
                style_source = "🎯 Custom" if custom_s else "🌐 Universal"

                container.after(0, lambda sl=st_lbl, pb=p_bar, ss=style_source: (
                    sl.configure(text=f"⚡ Requesting ({ss})...", text_color="#38bdf8", fg_color="#0c2e4e"),
                    pb.set(0.1)
                ))

                ok, task_id_or_err, credits, raw = api_client.generate_music_custom(
                    title=s_title,
                    lyrics=s_lyrics,
                    tags=effective_style
                )

                if ok:
                    tid = task_id_or_err
                    container.after(0, lambda sl=st_lbl, t=tid: sl.configure(text=f"🔄 #{t[:6]}", text_color="#38bdf8", fg_color="#0c2e4e"))
                    threading.Thread(target=_poll_single_bulk_task, args=(tid, api_client, item, s_title), daemon=True).start()
                else:
                    container.after(0, lambda sl=st_lbl, pb=p_bar, err=task_id_or_err: (
                        sl.configure(text="❌ Failed", text_color=THEME["danger"], fg_color="#381014"),
                        pb.set(0)
                    ))

            def _watchdog():
                all_done = True
                for itm in live_card_items:
                    txt = itm["st_lbl"].cget("text")
                    if "🔄" in txt or "⚡" in txt or "Pending" in txt:
                        all_done = False
                        break
                if all_done:
                    btn_start_bulk.configure(state="normal", text="🚀 Generate All Songs")
                    is_generating[0] = False
                else:
                    container.after(2000, _watchdog)

            container.after(2000, _watchdog)

        threading.Thread(target=_bulk_worker, daemon=True).start()

    def _poll_single_bulk_task(task_id: str, api_client: SunoAPI, item: dict, title: str):
        st_lbl = item["st_lbl"]
        p_bar = item["p_bar"]
        act_frame = item["act_frame"]

        for attempt in range(120):
            time.sleep(4)
            status, progress, meta, err_msg = api_client.get_task_status(task_id)

            def _update(st=status, pr=progress, mt=meta, err=err_msg):
                if st == "processing":
                    val = max(0.1, min(0.95, pr / 100.0 if pr else (attempt * 0.05)))
                    p_bar.set(val)
                elif st == "done":
                    p_bar.set(1.0)
                    st_lbl.configure(text="✅ Ready (2 Tracks)", text_color=THEME["success"], fg_color="#0d2818")
                    _render_action_buttons(act_frame, title, mt)
                elif st == "error":
                    p_bar.set(0)
                    st_lbl.configure(text="❌ Error", text_color=THEME["danger"], fg_color="#381014")

            container.after(0, _update)
            if status in ("done", "error"):
                break

    def _render_action_buttons(act_frame: ctk.CTkFrame, title: str, meta: dict):
        all_urls = meta.get("all_audio_urls", [])
        primary_url = meta.get("audio_url", all_urls[0] if all_urls else "")

        for w in act_frame.winfo_children():
            w.destroy()

        def _play():
            if primary_url:
                try:
                    import pygame
                    cache_file = get_downloads_dir() / "cache" / f"{title}_bulk.mp3"
                    cache_file.parent.mkdir(parents=True, exist_ok=True)
                    if not cache_file.exists():
                        SunoAPI.download_file(primary_url, str(cache_file))
                    pygame.mixer.music.stop()
                    pygame.mixer.music.load(str(cache_file))
                    pygame.mixer.music.play()
                except Exception as ex:
                    print(f"Play error: {ex}")

        def _download():
            if primary_url:
                dest = get_downloads_dir() / f"{title}.mp3"
                def _dl():
                    if SunoAPI.download_file(primary_url, str(dest)):
                        try:
                            os.startfile(str(get_downloads_dir()))
                        except Exception:
                            pass
                threading.Thread(target=_dl, daemon=True).start()

        ctk.CTkButton(
            act_frame,
            text="▶ Play",
            width=65,
            height=28,
            fg_color=THEME["accent"],
            text_color=THEME["accent_text"],
            font=FONTS["small_bold"],
            command=_play
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            act_frame,
            text="⬇ Save",
            width=65,
            height=28,
            fg_color=THEME["secondary_btn"],
            text_color=THEME["text"],
            font=FONTS["small_bold"],
            command=_download
        ).pack(side="left", padx=2)

    btn_start_bulk.configure(command=_trigger_bulk_generation)

    def _show_alert(title: str, msg: str):
        modal = ctk.CTkToplevel(container.winfo_toplevel())
        modal.title(title)
        modal.geometry("400x190")
        modal.configure(fg_color=THEME["bg"])
        modal.transient(container.winfo_toplevel())
        modal.grab_set()

        ctk.CTkLabel(modal, text=title, font=FONTS["header"], text_color=THEME["danger"]).pack(pady=(20, 10))
        ctk.CTkLabel(modal, text=msg, font=FONTS["body"], text_color=THEME["text"], wraplength=360).pack(pady=(0, 20))
        ctk.CTkButton(modal, text="OK", width=100, fg_color=THEME["secondary_btn"], command=modal.destroy).pack()

    # Initial preview render
    _render_song_cards()
