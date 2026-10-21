#!/usr/bin/env python3
"""
14_youtube_data_fetcher.py — 📺 YouTube Data Fetcher & Downloader Tab Plugin
═══════════════════════════════════════════════════════════════════════════════
YouTube Channel / Playlist / Video Data Fetcher for StoriesStudio & Standalone.
"""

from __future__ import annotations

# Plugin Registration Attributes
TAB_TITLE = "📺  YouTube Data Fetcher"
TAB_ORDER = 35
TAB_GROUP = ""
TAB_COLOR = ("#ef4444", "#dc2626")
TAB_ICON  = "📺"
LAZY_LOAD = True

import os
import sys
import re
import json
import csv
import time
import queue
import shutil
import html
import urllib.request
import xml.etree.ElementTree as ElementTree
import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import lazy_menu  # Win32 / TCL native menu limit fix
import preset_manager

# Lazy / Safe imports for yt_dlp, youtube_transcript_api, requests
try:
    import yt_dlp
except ImportError:
    yt_dlp = None

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    YouTubeTranscriptApi = None

try:
    import requests
except ImportError:
    requests = None

try:
    from curl_cffi import requests as c_requests
except ImportError:
    c_requests = None



# ═══════════════════════════════════════════════════════════════════════════════
# HELPER UTILITIES & PATH RESOLUTION
# ═══════════════════════════════════════════════════════════════════════════════

def get_ffmpeg_path() -> Optional[str]:
    """Find bundled or system ffmpeg executable."""
    candidates = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ffmpeg.exe"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "ffmpeg.exe"),
        os.path.join(os.getcwd(), "ffmpeg.exe"),
        os.path.join(os.getcwd(), "bin", "ffmpeg.exe"),
        shutil.which("ffmpeg"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return str(Path(c).resolve())
    return None

def get_default_output_dir() -> str:
    """Default output directory in Downloads or local workspace."""
    user_downloads = os.path.join(os.path.expanduser("~"), "Downloads", "YouTube_Fetcher_Output")
    os.makedirs(user_downloads, exist_ok=True)
    return user_downloads

def sanitize_filename(name: str, max_len: int = 120) -> str:
    """Sanitize filename to prevent invalid OS characters."""
    clean = re.sub(r'[\\/*?:"<>|]', '_', name)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean[:max_len] if len(clean) > max_len else (clean or "untitled")

def format_duration(seconds: Any) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    try:
        sec = int(float(seconds or 0))
    except (ValueError, TypeError):
        return "--:--"
    if sec <= 0:
        return "--:--"
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"

def format_srt_time(seconds: float) -> str:
    """Convert float seconds to SRT time format (00:00:00,000)."""
    seconds = max(0.0, float(seconds or 0.0))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def format_vtt_time(seconds: float) -> str:
    """Convert float seconds to WebVTT time format (00:00:00.000)."""
    seconds = max(0.0, float(seconds or 0.0))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

def format_views(views: Any) -> str:
    """Format view count into readable short string (e.g. 1.5M, 240K)."""
    try:
        v = int(views or 0)
    except (ValueError, TypeError):
        return "— views"
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.1f}B views"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M views"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K views"
    return f"{v} views"


# ═══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class VideoItem:
    video_id: str
    title: str
    url: str
    duration: int = 0
    duration_str: str = "0:00"
    uploader: str = ""
    view_count: int = 0
    published_date: str = ""
    thumbnail_url: str = ""
    description: str = ""
    selected: bool = True
    
    # UI reference
    card_frame: Optional[Any] = None
    checkbox_var: Optional[ctk.BooleanVar] = None
    thumb_label: Optional[ctk.CTkLabel] = None
    cached_thumb_img: Optional[ctk.CTkImage] = None


# ═══════════════════════════════════════════════════════════════════════════════
# CORE FETCHER & DOWNLOAD ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class YouTubeEngine:
    """Handles channel video extraction, subtitle extraction, and media downloads."""

    @staticmethod
    def normalize_url(raw_url: str) -> str:
        url = raw_url.strip()
        if not url:
            return ""
        if url.startswith("@"):
            return f"https://www.youtube.com/{url}"
        if ("youtube.com/" in url or "youtu.be/" in url) and not url.startswith("http"):
            return f"https://{url}"
        if not url.startswith("http") and not url.startswith("@") and "youtube.com" not in url and "youtu.be" not in url:
            return f"https://www.youtube.com/@{url}"
        return url

    @staticmethod
    def fetch_channel_videos(url: str, limit: Optional[int] = None, filter_type: str = "all", log_cb=None) -> List[VideoItem]:
        """Extract video list from YouTube channel, playlist, or single video URL."""
        if not yt_dlp:
            raise RuntimeError("yt-dlp is not installed. Please run `pip install yt-dlp`.")

        url = YouTubeEngine.normalize_url(url)
        if log_cb:
            log_cb(f"🔍 Analyzing URL: {url} ...")

        # Custom playlist range if limit set
        ydl_opts: Dict[str, Any] = {
            'extract_flat': 'in_playlist',
            'skip_download': True,
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
        }
        if limit and limit > 0:
            ydl_opts['playlist_items'] = f"1-{limit}"

        results: List[VideoItem] = []
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
            except Exception:
                info = None

            # Fallback if URL ends with a specific tab (e.g. /videos) that doesn't exist on channel
            if not info and re.search(r'/(videos|shorts|streams|featured|playlists|community)$', url):
                base_url = re.sub(r'/(videos|shorts|streams|featured|playlists|community)$', '', url)
                if log_cb:
                    log_cb(f"ℹ️ Tab not found, falling back to base channel: {base_url}")
                try:
                    info = ydl.extract_info(base_url, download=False)
                except Exception:
                    info = None

            if not info:
                return []

            # Flatten nested playlists / channel tabs (e.g. Shorts, Live streams, Videos)
            raw_entries: List[tuple[Dict[str, Any], str]] = []
            def _flatten(node: Any, parent_tab_name: str = ""):
                if not node or not isinstance(node, dict):
                    return
                node_entries = node.get('entries')
                tab_name = node.get('title') or parent_tab_name
                if node_entries is not None:
                    for sub in node_entries:
                        _flatten(sub, parent_tab_name=tab_name)
                elif node.get('_type') == 'playlist':
                    pass
                else:
                    raw_entries.append((node, parent_tab_name))

            if info.get('entries') is None:
                # Single video
                _flatten(info)
            else:
                for entry in info.get('entries', []):
                    _flatten(entry)

            seen_ids = set()
            for entry, tab_name in raw_entries:
                if not entry or not isinstance(entry, dict):
                    continue

                vid_id = entry.get('id') or ""
                if not vid_id or vid_id in seen_ids:
                    continue
                seen_ids.add(vid_id)

                title = entry.get('title') or "Untitled Video"
                raw_vid_url = entry.get('url') or ""
                duration = entry.get('duration') or 0
                uploader = entry.get('uploader') or info.get('uploader') or info.get('title') or ""
                view_count = entry.get('view_count') or 0
                pub_date = entry.get('upload_date') or entry.get('timestamp') or ""
                if isinstance(pub_date, (int, float)) and pub_date > 0:
                    try:
                        pub_date = time.strftime("%Y-%m-%d", time.localtime(pub_date))
                    except Exception:
                        pub_date = ""
                elif isinstance(pub_date, str) and len(pub_date) == 8 and pub_date.isdigit():
                    pub_date = f"{pub_date[:4]}-{pub_date[4:6]}-{pub_date[6:]}"

                # Detect if Short
                is_short = (
                    "/shorts/" in str(raw_vid_url).lower()
                    or "shorts" in str(tab_name).lower()
                    or (0 < duration <= 60)
                    or any(t in title.lower() for t in ("#shorts", "#short", "#ytshorts"))
                )

                # Filter type check
                if filter_type == "videos_only" and is_short:
                    continue
                if filter_type == "shorts_only" and not is_short:
                    continue

                # Construct proper URL
                if not str(raw_vid_url).startswith("http"):
                    if is_short:
                        vid_url = f"https://www.youtube.com/shorts/{vid_id}"
                    else:
                        vid_url = f"https://www.youtube.com/watch?v={vid_id}"
                else:
                    vid_url = raw_vid_url

                # Format duration string
                if duration > 0:
                    dur_str = format_duration(duration)
                elif is_short:
                    dur_str = "⚡ Short"
                else:
                    dur_str = "--:--"

                # Thumbnails
                thumbs = entry.get('thumbnails') or []
                thumb_url = ""
                if thumbs and isinstance(thumbs, list):
                    valid_thumbs = [t for t in thumbs if isinstance(t, dict) and t.get('url')]
                    if valid_thumbs:
                        thumb_url = valid_thumbs[-1].get('url') or valid_thumbs[0].get('url', '')
                if not thumb_url and entry.get('thumbnail'):
                    thumb_url = entry.get('thumbnail')
                if not thumb_url and vid_id:
                    thumb_url = f"https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg"

                item = VideoItem(
                    video_id=vid_id,
                    title=title,
                    url=vid_url,
                    duration=int(duration) if duration else 0,
                    duration_str=dur_str,
                    uploader=str(uploader),
                    view_count=int(view_count) if view_count else 0,
                    published_date=str(pub_date),
                    thumbnail_url=thumb_url,
                    description=entry.get('description') or "",
                    selected=True,
                )
                results.append(item)

                if limit and limit > 0 and len(results) >= limit:
                    break

        return results

    @staticmethod
    def fetch_full_metadata(video_url: str) -> Dict[str, Any]:
        """Fetch complete detailed metadata for a single video including description."""
        if not yt_dlp:
            return {}
        ydl_opts = {
            'skip_download': True,
            'extractor_args': {'youtube': {'player_client': ['android', 'web', 'mweb']}},
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(video_url, download=False) or {}

    @staticmethod
    def _fetch_url_content(url: str, timeout: int = 3) -> Optional[str]:
        """Fetch URL content with browser impersonation, android client headers, or safe fallback."""
        android_ua = "com.google.android.apps.youtube.vr.oculus/1.37.10 (Linux; U; Android 10; Quest 2) gzip"

        if c_requests:
            # 1. Try Android VR client (fastest on YouTube timedtext)
            try:
                resp = c_requests.get(url, headers={"User-Agent": android_ua}, timeout=timeout)
                if resp.status_code == 200 and resp.text:
                    return resp.text
            except Exception:
                pass

            # 2. Try Chrome impersonation
            try:
                resp = c_requests.get(url, impersonate="chrome120", timeout=timeout)
                if resp.status_code == 200 and resp.text:
                    return resp.text
            except Exception:
                pass
            return None

        if requests:
            try:
                resp = requests.get(url, headers={"User-Agent": android_ua}, timeout=timeout)
                if resp.status_code == 200 and resp.text:
                    return resp.text
            except Exception:
                pass

            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
                }
                resp = requests.get(url, headers=headers, timeout=timeout)
                if resp.status_code == 200 and resp.text:
                    return resp.text
            except Exception:
                pass
            return None

        try:
            req = urllib.request.Request(url, headers={"User-Agent": android_ua})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception:
            pass

        return None

    @staticmethod
    def fetch_transcript(video_id: str, lang_codes=("en", "hi", "a.en", "a.hi")) -> List[Dict[str, Any]]:
        """Fetch transcript with timestamps using youtube_transcript_api or yt-dlp fallback."""
        lines: List[Dict[str, Any]] = []

        # 1. Try youtube_transcript_api
        if YouTubeTranscriptApi:
            try:
                ytt = YouTubeTranscriptApi()
                try:
                    t_list = ytt.list(video_id)
                    selected_transcript = None
                    try:
                        selected_transcript = t_list.find_transcript(list(lang_codes))
                    except Exception:
                        pass
                    if not selected_transcript:
                        try:
                            selected_transcript = t_list.find_manually_created_transcript(list(lang_codes))
                        except Exception:
                            pass
                    if not selected_transcript:
                        try:
                            selected_transcript = t_list.find_generated_transcript(list(lang_codes))
                        except Exception:
                            pass
                    if not selected_transcript:
                        for t in t_list:
                            selected_transcript = t
                            break

                    if selected_transcript:
                        # Try direct URL fetch with browser impersonation (avoids YouTube blocking/timeout)
                        if hasattr(selected_transcript, "_url") and selected_transcript._url:
                            xml_text = YouTubeEngine._fetch_url_content(selected_transcript._url)
                            if xml_text:
                                try:
                                    root = ElementTree.fromstring(xml_text)
                                    for elem in root:
                                        if elem.text is not None:
                                            txt = html.unescape(elem.text)
                                            txt = re.sub(r"<[^>]*>", "", txt).strip()
                                            if txt:
                                                st = float(elem.attrib.get("start", 0.0))
                                                dur = float(elem.attrib.get("dur", 0.0))
                                                lines.append({
                                                    "start": round(st, 3),
                                                    "end": round(st + dur, 3),
                                                    "duration": round(dur, 3),
                                                    "timestamp": format_duration(st),
                                                    "text": txt,
                                                })
                                    if lines:
                                        return lines
                                except Exception:
                                    pass
                except Exception:
                    pass
            except Exception:
                pass

        # 2. Fallback: yt-dlp subtitle extraction
        if yt_dlp:
            try:
                ydl_opts = {
                    'skip_download': True,
                    'writesubtitles': True,
                    'writeautomaticsub': True,
                    'subtitleslangs': ['en', 'hi', 'all'],
                    'quiet': True,
                    'no_warnings': True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                    subs = (info.get('subtitles') or {}) if info else {}
                    auto_subs = (info.get('automatic_captions') or {}) if info else {}
                    all_subs = {**subs, **auto_subs}

                    # Preferred languages priority
                    search_langs = list(lang_codes) + ['en', 'hi', 'en-US', 'hi-IN']
                    for k in all_subs.keys():
                        if k not in search_langs:
                            search_langs.append(k)

                    for lcode in search_langs:
                        if lcode in all_subs:
                            sub_formats = all_subs[lcode]

                            # 1) Try json3 format
                            json3_fmt = next((f for f in sub_formats if f.get('ext') == 'json3'), None)
                            if json3_fmt and json3_fmt.get('url'):
                                content = YouTubeEngine._fetch_url_content(json3_fmt['url'])
                                if content:
                                    try:
                                        data = json.loads(content)
                                        for event in data.get('events', []):
                                            if 'segs' in event and 'tStartMs' in event:
                                                st = event['tStartMs'] / 1000.0
                                                dur = event.get('dDurationMs', 0) / 1000.0
                                                txt = "".join([s.get('utf8', '') for s in event['segs']]).strip()
                                                txt = html.unescape(txt)
                                                txt = re.sub(r"<[^>]*>", "", txt).strip()
                                                if txt:
                                                    lines.append({
                                                        "start": round(st, 3),
                                                        "end": round(st + dur, 3),
                                                        "duration": round(dur, 3),
                                                        "timestamp": format_duration(st),
                                                        "text": txt,
                                                    })
                                        if lines:
                                            return lines
                                    except Exception:
                                        pass

                            # 2) Try srv1 / srv2 / srv3 / xml format
                            srv_fmt = next((f for f in sub_formats if f.get('ext') in ('srv1', 'srv2', 'srv3', 'ttml', 'xml')), None)
                            if srv_fmt and srv_fmt.get('url'):
                                xml_text = YouTubeEngine._fetch_url_content(srv_fmt['url'])
                                if xml_text:
                                    try:
                                        root = ElementTree.fromstring(xml_text)
                                        for elem in root:
                                            if elem.text is not None:
                                                txt = html.unescape(elem.text)
                                                txt = re.sub(r"<[^>]*>", "", txt).strip()
                                                if txt:
                                                    st = float(elem.attrib.get("start", 0.0))
                                                    dur = float(elem.attrib.get("dur", 0.0))
                                                    lines.append({
                                                        "start": round(st, 3),
                                                        "end": round(st + dur, 3),
                                                        "duration": round(dur, 3),
                                                        "timestamp": format_duration(st),
                                                        "text": txt,
                                                    })
                                        if lines:
                                            return lines
                                    except Exception:
                                        pass

                            # 3) Try vtt format
                            vtt_fmt = next((f for f in sub_formats if f.get('ext') == 'vtt'), None)
                            if vtt_fmt and vtt_fmt.get('url'):
                                vtt_text = YouTubeEngine._fetch_url_content(vtt_fmt['url'])
                                if vtt_text:
                                    try:
                                        blocks = vtt_text.replace("\r\n", "\n").split("\n\n")
                                        for block in blocks:
                                            lines_in_block = [b.strip() for b in block.strip().split("\n") if b.strip()]
                                            time_line = next((l for l in lines_in_block if "-->" in l), None)
                                            if time_line:
                                                parts = time_line.split("-->")
                                                start_str = parts[0].strip()
                                                s_parts = start_str.split(":")
                                                if len(s_parts) == 3:
                                                    st = float(s_parts[0]) * 3600 + float(s_parts[1]) * 60 + float(s_parts[2])
                                                elif len(s_parts) == 2:
                                                    st = float(s_parts[0]) * 60 + float(s_parts[1])
                                                else:
                                                    st = 0.0

                                                t_idx = lines_in_block.index(time_line)
                                                txt_lines = lines_in_block[t_idx + 1:]
                                                txt = " ".join(txt_lines)
                                                txt = html.unescape(txt)
                                                txt = re.sub(r"<[^>]*>", "", txt).strip()
                                                if txt:
                                                    lines.append({
                                                        "start": round(st, 3),
                                                        "end": round(st + 2.0, 3),
                                                        "duration": 2.0,
                                                        "timestamp": format_duration(st),
                                                        "text": txt,
                                                    })
                                        if lines:
                                            return lines
                                    except Exception:
                                        pass
            except Exception:
                pass

        return lines


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN TAB FRAME UI
# ═══════════════════════════════════════════════════════════════════════════════

class YouTubeDataFetcherFrame(ctk.CTkFrame):
    """Modern CustomTkinter GUI for YouTube Data Fetching, Selection & Multi-format Downloads."""

    def __init__(self, parent, boot_data=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.boot_data = boot_data or {}
        self.videos: List[VideoItem] = []
        self.active_search_query = ""
        self.cancel_requested = False
        self.is_fetching = False
        self.is_downloading = False
        
        # Color Palette
        self.COLOR_BG = "#0f111a"
        self.COLOR_CARD = "#181a26"
        self.COLOR_CARD_ALT = "#1f2233"
        self.COLOR_ACCENT = "#ef4444"
        self.COLOR_ACCENT_HOVER = "#dc2626"
        self.COLOR_SECONDARY = "#6366f1"
        self.COLOR_SECONDARY_HOVER = "#4f46e5"
        self.COLOR_TEXT = "#f8fafc"
        self.COLOR_DIM = "#94a3b8"
        self.COLOR_BORDER = "#2e344e"

        self.configure(fg_color=self.COLOR_BG)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_header_card()
        self._build_toolbar_card()
        self._build_main_content()
        self._build_bottom_progress_card()

    # ── Header & Channel URL Input Bar ─────────────────────────────────────────
    def _build_header_card(self):
        header_card = ctk.CTkFrame(self, fg_color=self.COLOR_CARD, corner_radius=12, border_width=1, border_color=self.COLOR_BORDER)
        header_card.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        header_card.grid_columnconfigure(1, weight=1)

        # Title & Badge Row
        title_row = ctk.CTkFrame(header_card, fg_color="transparent")
        title_row.grid(row=0, column=0, columnspan=3, sticky="ew", padx=16, pady=(12, 6))

        ctk.CTkLabel(
            title_row,
            text="📺  YouTube Data Fetcher & Downloader",
            font=("Segoe UI", 18, "bold"),
            text_color="#fca5a5",
        ).pack(side="left")

        ctk.CTkLabel(
            title_row,
            text="⚡ Batch Videos, Audios, Timestamps, Subtitles & Metadata",
            font=("Segoe UI", 11),
            text_color=self.COLOR_DIM,
        ).pack(side="left", padx=(12, 0), pady=(4, 0))

        self.preset_widget = preset_manager.PresetWidget(
            title_row,
            tool_id="youtube_data_fetcher",
            collect_fn=self._collect_preset_settings,
            apply_fn=self._apply_preset_settings
        )
        self.preset_widget.pack(side="right", padx=(8, 0))

        # URL Input Bar
        ctk.CTkLabel(header_card, text="Channel / URL:", font=("Segoe UI", 12, "bold"), text_color=self.COLOR_TEXT).grid(
            row=1, column=0, padx=(16, 8), pady=8, sticky="w"
        )

        self.url_entry = ctk.CTkEntry(
            header_card,
            placeholder_text="Enter YouTube Channel (@Handle/URL), Playlist, or single Video / Shorts Link...",
            font=("Segoe UI", 12),
            height=38,
            fg_color=self.COLOR_CARD_ALT,
            border_color=self.COLOR_BORDER,
        )
        self.url_entry.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=8)

        btn_box = ctk.CTkFrame(header_card, fg_color="transparent")
        btn_box.grid(row=1, column=2, padx=(0, 16), pady=8, sticky="e")

        ctk.CTkButton(
            btn_box,
            text="📋 Paste",
            width=70,
            height=38,
            fg_color=self.COLOR_CARD_ALT,
            hover_color=self.COLOR_BORDER,
            text_color=self.COLOR_TEXT,
            font=("Segoe UI", 11, "bold"),
            command=self._paste_url,
        ).pack(side="left", padx=(0, 6))

        self.fetch_btn = ctk.CTkButton(
            btn_box,
            text="🔍 Fetch Videos",
            width=130,
            height=38,
            fg_color=self.COLOR_ACCENT,
            hover_color=self.COLOR_ACCENT_HOVER,
            text_color="#ffffff",
            font=("Segoe UI", 12, "bold"),
            command=self._start_fetch_videos,
        )
        self.fetch_btn.pack(side="left")

        # Second Row: Filters, Limits & Output Folder
        opts_row = ctk.CTkFrame(header_card, fg_color="transparent")
        opts_row.grid(row=2, column=0, columnspan=3, sticky="ew", padx=16, pady=(0, 12))
        opts_row.grid_columnconfigure(4, weight=1)

        ctk.CTkLabel(opts_row, text="Fetch Limit:", font=("Segoe UI", 11), text_color=self.COLOR_DIM).grid(
            row=0, column=0, padx=(0, 4), sticky="w"
        )
        self.limit_menu = ctk.CTkOptionMenu(
            opts_row,
            values=["All Videos", "20 Videos", "50 Videos", "100 Videos", "250 Videos", "500 Videos"],
            width=115,
            height=28,
            fg_color=self.COLOR_CARD_ALT,
            button_color=self.COLOR_BORDER,
            font=("Segoe UI", 11),
        )
        self.limit_menu.set("All Videos")
        self.limit_menu.grid(row=0, column=1, padx=(0, 12), sticky="w")

        ctk.CTkLabel(opts_row, text="Content Type:", font=("Segoe UI", 11), text_color=self.COLOR_DIM).grid(
            row=0, column=2, padx=(0, 4), sticky="w"
        )
        self.type_menu = ctk.CTkOptionMenu(
            opts_row,
            values=["All (Videos & Shorts)", "Videos Only", "Shorts Only"],
            width=160,
            height=28,
            fg_color=self.COLOR_CARD_ALT,
            button_color=self.COLOR_BORDER,
            font=("Segoe UI", 11),
        )
        self.type_menu.set("All (Videos & Shorts)")
        self.type_menu.grid(row=0, column=3, padx=(0, 16), sticky="w")

        # Output Folder Picker
        ctk.CTkLabel(opts_row, text="Save To:", font=("Segoe UI", 11), text_color=self.COLOR_DIM).grid(
            row=0, column=4, padx=(0, 4), sticky="e"
        )
        self.output_dir_var = ctk.StringVar(value=get_default_output_dir())
        self.output_entry = ctk.CTkEntry(
            opts_row,
            textvariable=self.output_dir_var,
            font=("Segoe UI", 10),
            height=28,
            width=220,
            fg_color=self.COLOR_CARD_ALT,
            border_color=self.COLOR_BORDER,
        )
        self.output_entry.grid(row=0, column=5, padx=(0, 6), sticky="e")

        ctk.CTkButton(
            opts_row,
            text="📁 Browse",
            width=70,
            height=28,
            fg_color=self.COLOR_CARD_ALT,
            hover_color=self.COLOR_BORDER,
            text_color=self.COLOR_TEXT,
            font=("Segoe UI", 11),
            command=self._browse_output_dir,
        ).grid(row=0, column=6, padx=(0, 6), sticky="e")

        ctk.CTkButton(
            opts_row,
            text="📂 Open",
            width=60,
            height=28,
            fg_color=self.COLOR_CARD_ALT,
            hover_color=self.COLOR_BORDER,
            text_color=self.COLOR_TEXT,
            font=("Segoe UI", 11),
            command=self._open_output_dir,
        ).grid(row=0, column=7, sticky="e")

    def _collect_preset_settings(self) -> dict:
        return {
            "url": self.url_entry.get() if hasattr(self, "url_entry") else "",
            "search_type": self.type_menu.get() if hasattr(self, "type_menu") else "",
            "limit": self.limit_menu.get() if hasattr(self, "limit_menu") else "",
            "sort_by": self.sort_menu.get() if hasattr(self, "sort_menu") else "",
            "output_dir": self.output_dir_var.get() if hasattr(self, "output_dir_var") else "",
            "download_mode": self.download_mode_var.get() if hasattr(self, "download_mode_var") else "",
            "folderwise": self.folderwise_var.get() if hasattr(self, "folderwise_var") else True,
            "chk_audio": self.chk_audio_var.get() if hasattr(self, "chk_audio_var") else True,
            "chk_caption": self.chk_caption_var.get() if hasattr(self, "chk_caption_var") else True,
            "chk_link": self.chk_link_var.get() if hasattr(self, "chk_link_var") else True,
            "chk_thumb": self.chk_thumb_var.get() if hasattr(self, "chk_thumb_var") else True,
            "chk_title": self.chk_title_var.get() if hasattr(self, "chk_title_var") else True,
        }

    def _apply_preset_settings(self, data: dict):
        if not isinstance(data, dict): return
        if "url" in data and hasattr(self, "url_entry"):
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, data["url"])
        if "search_type" in data and hasattr(self, "type_menu"):
            try: self.type_menu.set(data["search_type"])
            except Exception: pass
        if "limit" in data and hasattr(self, "limit_menu"):
            try: self.limit_menu.set(str(data["limit"]))
            except Exception: pass
        if "sort_by" in data and hasattr(self, "sort_menu"):
            try:
                self.sort_menu.set(data["sort_by"])
                self._on_sort_change(data["sort_by"])
            except Exception: pass
        if "output_dir" in data and hasattr(self, "output_dir_var"):
            try: self.output_dir_var.set(data["output_dir"])
            except Exception: pass
        if "folderwise" in data and hasattr(self, "folderwise_var"):
            try: self.folderwise_var.set(bool(data["folderwise"]))
            except Exception: pass
        if "chk_audio" in data and hasattr(self, "chk_audio_var"):
            try: self.chk_audio_var.set(bool(data["chk_audio"]))
            except Exception: pass
        if "chk_caption" in data and hasattr(self, "chk_caption_var"):
            try: self.chk_caption_var.set(bool(data["chk_caption"]))
            except Exception: pass
        if "chk_link" in data and hasattr(self, "chk_link_var"):
            try: self.chk_link_var.set(bool(data["chk_link"]))
            except Exception: pass
        if "chk_thumb" in data and hasattr(self, "chk_thumb_var"):
            try: self.chk_thumb_var.set(bool(data["chk_thumb"]))
            except Exception: pass
        if "chk_title" in data and hasattr(self, "chk_title_var"):
            try: self.chk_title_var.set(bool(data["chk_title"]))
            except Exception: pass
        if "download_mode" in data and hasattr(self, "download_mode_var"):
            try:
                self.download_mode_var.set(data["download_mode"])
                self._on_download_mode_change(data["download_mode"])
            except Exception: pass

    # ── Toolbar: Selection & Download Action Hub ────────────────────────────────
    def _build_toolbar_card(self):
        toolbar_card = ctk.CTkFrame(self, fg_color=self.COLOR_CARD, corner_radius=12, border_width=1, border_color=self.COLOR_BORDER)
        toolbar_card.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        toolbar_card.grid_columnconfigure(1, weight=1)

        # Top line of toolbar: Selection Stats & Quick Select Buttons
        top_bar = ctk.CTkFrame(toolbar_card, fg_color="transparent")
        top_bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=14, pady=(10, 6))

        self.stats_label = ctk.CTkLabel(
            top_bar,
            text="📊  Total: 0 videos  |  Selected: 0  |  Duration: 0:00",
            font=("Segoe UI", 12, "bold"),
            text_color=self.COLOR_TEXT,
        )
        self.stats_label.pack(side="left")

        # Select Action Buttons on Far Right
        ctk.CTkButton(
            top_bar,
            text="☑️ Select All",
            width=88,
            height=28,
            fg_color=self.COLOR_CARD_ALT,
            hover_color=self.COLOR_BORDER,
            text_color="#4ade80",
            font=("Segoe UI", 11, "bold"),
            command=lambda: self._set_all_selection(True),
        ).pack(side="right", padx=(4, 0))

        ctk.CTkButton(
            top_bar,
            text="◻️ Deselect All",
            width=96,
            height=28,
            fg_color=self.COLOR_CARD_ALT,
            hover_color=self.COLOR_BORDER,
            text_color="#f87171",
            font=("Segoe UI", 11),
            command=lambda: self._set_all_selection(False),
        ).pack(side="right", padx=(4, 0))

        ctk.CTkButton(
            top_bar,
            text="🔄 Invert",
            width=65,
            height=28,
            fg_color=self.COLOR_CARD_ALT,
            hover_color=self.COLOR_BORDER,
            text_color=self.COLOR_DIM,
            font=("Segoe UI", 11),
            command=self._invert_selection,
        ).pack(side="right", padx=(4, 0))

        # Sort Dropdown Selector
        ctk.CTkLabel(top_bar, text="Sort:", font=("Segoe UI", 11, "bold"), text_color=self.COLOR_DIM).pack(side="right", padx=(10, 4))
        self.sort_menu = ctk.CTkOptionMenu(
            top_bar,
            values=[
                "👁️ Most Views (High ➔ Low)",
                "👁️ Least Views (Low ➔ High)",
                "📅 Newest First (Latest ➔ Oldest)",
                "⏳ Oldest First (Oldest ➔ Latest)",
                "⏱️ Longest First (Duration)",
                "⚡ Shortest First (Duration)",
                "🔤 Title (A ➔ Z)",
                "🔤 Title (Z ➔ A)",
                "📌 Default Channel Order",
            ],
            width=210,
            height=28,
            fg_color=self.COLOR_CARD_ALT,
            button_color=self.COLOR_BORDER,
            font=("Segoe UI", 10, "bold"),
            command=self._on_sort_change,
        )
        self.sort_menu.set("👁️ Most Views (High ➔ Low)")
        self.sort_menu.pack(side="right", padx=(0, 6))

        # Filter Search Bar
        self.search_entry = ctk.CTkEntry(
            top_bar,
            placeholder_text="🔍 Filter title...",
            width=150,
            height=28,
            font=("Segoe UI", 11),
            fg_color=self.COLOR_CARD_ALT,
            border_color=self.COLOR_BORDER,
        )
        self.search_entry.pack(side="right", padx=(0, 8))
        self.search_entry.bind("<KeyRelease>", lambda e: self._on_search_change())

        # Separator line
        sep = ctk.CTkFrame(toolbar_card, height=1, fg_color=self.COLOR_BORDER)
        sep.grid(row=1, column=0, columnspan=2, sticky="ew", padx=14, pady=4)

        # Download / Export Configuration Bar
        dl_bar = ctk.CTkFrame(toolbar_card, fg_color="transparent")
        dl_bar.grid(row=2, column=0, columnspan=2, sticky="ew", padx=14, pady=(6, 10))

        # Mode Selection
        ctk.CTkLabel(dl_bar, text="Download Mode:", font=("Segoe UI", 11, "bold"), text_color=self.COLOR_TEXT).pack(
            side="left", padx=(0, 6)
        )
        
        self.download_mode_var = ctk.StringVar(value="🎯 Selected Components (Folder-wise / Multi)")
        self.mode_menu = ctk.CTkOptionMenu(
            dl_bar,
            variable=self.download_mode_var,
            values=[
                "🎯 Selected Components (Folder-wise / Multi)",
                "🎬 Video (MP4)",
                "🎵 Audio (MP3 / WAV)",
                "🖼️ Thumbnail (HD / MaxRes)",
                "📝 Transcript (with Timestamps)",
                "📋 Titles & Descriptions (TXT/CSV)",
                "📦 Full Package (Everything)",
            ],
            width=250,
            height=32,
            fg_color=self.COLOR_SECONDARY,
            button_color=self.COLOR_SECONDARY_HOVER,
            font=("Segoe UI", 11, "bold"),
            command=self._on_download_mode_change,
        )
        self.mode_menu.pack(side="left", padx=(0, 12))

        # Format / Quality Option Menu (Dynamic based on mode)
        ctk.CTkLabel(dl_bar, text="Quality / Format:", font=("Segoe UI", 11), text_color=self.COLOR_DIM).pack(
            side="left", padx=(0, 6)
        )
        self.format_menu = ctk.CTkOptionMenu(
            dl_bar,
            values=["MP3 (320 kbps High)", "MP3 (192 kbps)", "WAV (Lossless)", "M4A (AAC)"],
            width=200,
            height=32,
            fg_color=self.COLOR_CARD_ALT,
            button_color=self.COLOR_BORDER,
            font=("Segoe UI", 11),
        )
        self.format_menu.pack(side="left", padx=(0, 16))

        # Primary Download Button
        self.download_btn = ctk.CTkButton(
            dl_bar,
            text="🚀 DOWNLOAD SELECTED (0)",
            height=36,
            fg_color=self.COLOR_ACCENT,
            hover_color=self.COLOR_ACCENT_HOVER,
            text_color="#ffffff",
            font=("Segoe UI", 12, "bold"),
            command=self._start_batch_download,
        )
        self.download_btn.pack(side="right", padx=(6, 0))

        self.cancel_btn = ctk.CTkButton(
            dl_bar,
            text="⏹️ Cancel",
            width=80,
            height=36,
            fg_color=self.COLOR_CARD_ALT,
            hover_color="#7f1d1d",
            text_color="#f87171",
            font=("Segoe UI", 11, "bold"),
            state="disabled",
            command=self._cancel_operation,
        )
        self.cancel_btn.pack(side="right", padx=(0, 6))

        # Row 3: Selective Data Components & Folder-wise Options Bar
        data_bar = ctk.CTkFrame(toolbar_card, fg_color=self.COLOR_CARD_ALT, corner_radius=8, border_width=1, border_color=self.COLOR_BORDER)
        data_bar.grid(row=3, column=0, columnspan=2, sticky="ew", padx=14, pady=(0, 10))

        # Folderwise Checkbox
        self.folderwise_var = ctk.BooleanVar(value=True)
        self.folderwise_cb = ctk.CTkCheckBox(
            data_bar,
            text="📁 Folder-wise (Subfolder per Song [Date])",
            variable=self.folderwise_var,
            font=("Segoe UI", 11, "bold"),
            text_color="#38bdf8",
            fg_color="#0284c7",
            hover_color="#0369a1",
            checkmark_color="#ffffff",
        )
        self.folderwise_cb.pack(side="left", padx=(12, 14), pady=7)

        # Vertical separator
        vsep = ctk.CTkFrame(data_bar, width=1, height=20, fg_color=self.COLOR_BORDER)
        vsep.pack(side="left", padx=(0, 12), pady=6)

        ctk.CTkLabel(
            data_bar,
            text="Select Data:",
            font=("Segoe UI", 11, "bold"),
            text_color=self.COLOR_TEXT,
        ).pack(side="left", padx=(0, 8))

        # The 5 Checkboxes (Audio, Caption/Transcript, Link, Thumbnail, Title)
        self.chk_audio_var = ctk.BooleanVar(value=True)
        self.chk_caption_var = ctk.BooleanVar(value=True)
        self.chk_link_var = ctk.BooleanVar(value=True)
        self.chk_thumb_var = ctk.BooleanVar(value=True)
        self.chk_title_var = ctk.BooleanVar(value=True)

        self.cb_audio = ctk.CTkCheckBox(
            data_bar,
            text="🎵 Audio",
            variable=self.chk_audio_var,
            font=("Segoe UI", 11),
            text_color=self.COLOR_TEXT,
            fg_color=self.COLOR_ACCENT,
            command=self._on_component_check_change,
        )
        self.cb_audio.pack(side="left", padx=(0, 10))

        self.cb_caption = ctk.CTkCheckBox(
            data_bar,
            text="📝 Caption / Transcript",
            variable=self.chk_caption_var,
            font=("Segoe UI", 11),
            text_color=self.COLOR_TEXT,
            fg_color=self.COLOR_ACCENT,
            command=self._on_component_check_change,
        )
        self.cb_caption.pack(side="left", padx=(0, 10))

        self.cb_link = ctk.CTkCheckBox(
            data_bar,
            text="🔗 Link",
            variable=self.chk_link_var,
            font=("Segoe UI", 11),
            text_color=self.COLOR_TEXT,
            fg_color=self.COLOR_ACCENT,
            command=self._on_component_check_change,
        )
        self.cb_link.pack(side="left", padx=(0, 10))

        self.cb_thumb = ctk.CTkCheckBox(
            data_bar,
            text="🖼️ Thumbnail",
            variable=self.chk_thumb_var,
            font=("Segoe UI", 11),
            text_color=self.COLOR_TEXT,
            fg_color=self.COLOR_ACCENT,
            command=self._on_component_check_change,
        )
        self.cb_thumb.pack(side="left", padx=(0, 10))

        self.cb_title = ctk.CTkCheckBox(
            data_bar,
            text="🏷️ Title",
            variable=self.chk_title_var,
            font=("Segoe UI", 11),
            text_color=self.COLOR_TEXT,
            fg_color=self.COLOR_ACCENT,
            command=self._on_component_check_change,
        )
        self.cb_title.pack(side="left", padx=(0, 12))

        # Quick Toggle for Items: All / None
        ctk.CTkButton(
            data_bar,
            text="All",
            width=36,
            height=22,
            fg_color="transparent",
            hover_color=self.COLOR_BORDER,
            text_color="#4ade80",
            font=("Segoe UI", 10, "bold"),
            command=lambda: self._set_all_components(True),
        ).pack(side="right", padx=(2, 10))

        ctk.CTkButton(
            data_bar,
            text="None",
            width=40,
            height=22,
            fg_color="transparent",
            hover_color=self.COLOR_BORDER,
            text_color="#f87171",
            font=("Segoe UI", 10),
            command=lambda: self._set_all_components(False),
        ).pack(side="right", padx=(2, 2))

    def _set_all_components(self, val: bool):
        self.chk_audio_var.set(val)
        self.chk_caption_var.set(val)
        self.chk_link_var.set(val)
        self.chk_thumb_var.set(val)
        self.chk_title_var.set(val)
        self._on_component_check_change()

    def _on_component_check_change(self):
        if hasattr(self, "download_mode_var"):
            self.download_mode_var.set("🎯 Selected Components (Folder-wise / Multi)")
            self._on_download_mode_change("🎯 Selected Components (Folder-wise / Multi)")

    # ── Main Video Scrollable Grid ─────────────────────────────────────────────
    def _build_main_content(self):
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 8))
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(0, weight=1)

        # Video List Scrollable Frame
        self.video_scroll = ctk.CTkScrollableFrame(
            self.main_container,
            fg_color=self.COLOR_CARD,
            corner_radius=12,
            border_width=1,
            border_color=self.COLOR_BORDER,
        )
        self.video_scroll.grid(row=0, column=0, sticky="nsew")
        self.video_scroll.grid_columnconfigure(0, weight=1)

        # Placeholder Banner when no videos loaded
        self._show_empty_placeholder()

    def _show_empty_placeholder(self):
        for widget in self.video_scroll.winfo_children():
            widget.destroy()

        self.placeholder_box = ctk.CTkFrame(self.video_scroll, fg_color="transparent")
        self.placeholder_box.pack(expand=True, fill="both", pady=80)

        ctk.CTkLabel(
            self.placeholder_box,
            text="📺  Ready to Fetch YouTube Data",
            font=("Segoe UI", 18, "bold"),
            text_color=self.COLOR_TEXT,
        ).pack(pady=(0, 6))

        ctk.CTkLabel(
            self.placeholder_box,
            text="Enter a YouTube Channel handle (e.g. @Khushiaistorylith, @MrBeast),\nChannel URL, Playlist URL, or a Single Video / Shorts URL above and click 'Fetch Videos'.\n\nYou can select items and download Videos (MP4), Audios (MP3/WAV), High-Res Thumbnails, Transcripts, Titles & Descriptions.",
            font=("Segoe UI", 12),
            text_color=self.COLOR_DIM,
            justify="center",
        ).pack(pady=4)

    # ── Bottom Progress & Live Log Card ────────────────────────────────────────
    def _build_bottom_progress_card(self):
        self.bottom_card = ctk.CTkFrame(self, fg_color=self.COLOR_CARD, corner_radius=12, border_width=1, border_color=self.COLOR_BORDER)
        self.bottom_card.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 14))
        self.bottom_card.grid_columnconfigure(0, weight=1)

        prog_row = ctk.CTkFrame(self.bottom_card, fg_color="transparent")
        prog_row.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 6))
        prog_row.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            prog_row,
            text="Status: Ready",
            font=("Segoe UI", 11),
            text_color=self.COLOR_DIM,
            anchor="w",
        )
        self.status_label.grid(row=0, column=0, sticky="w")

        self.log_toggle_btn = ctk.CTkButton(
            prog_row,
            text="📜 Show Activity Logs",
            width=140,
            height=24,
            fg_color=self.COLOR_CARD_ALT,
            hover_color=self.COLOR_BORDER,
            text_color=self.COLOR_DIM,
            font=("Segoe UI", 10),
            command=self._toggle_logs,
        )
        self.log_toggle_btn.grid(row=0, column=1, sticky="e")

        self.progress_bar = ctk.CTkProgressBar(
            self.bottom_card,
            height=8,
            fg_color=self.COLOR_CARD_ALT,
            progress_color=self.COLOR_ACCENT,
        )
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 10))
        self.progress_bar.set(0.0)

        # Expandable Activity Log Box
        self.log_box = ctk.CTkTextbox(
            self.bottom_card,
            height=110,
            font=("Consolas", 10),
            fg_color=self.COLOR_BG,
            text_color="#cbd5e1",
            wrap="word",
        )
        # Hidden by default
        self.logs_visible = False

    def _toggle_logs(self):
        if self.logs_visible:
            self.log_box.grid_forget()
            self.log_toggle_btn.configure(text="📜 Show Activity Logs")
            self.logs_visible = False
        else:
            self.log_box.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 10))
            self.log_toggle_btn.configure(text="🔼 Hide Activity Logs")
            self.logs_visible = True

    def log(self, text: str):
        """Append log message thread-safely."""
        self.after(0, self._append_log, text)

    def _append_log(self, text: str):
        timestamp = time.strftime("%H:%M:%S")
        self.log_box.insert("end", f"[{timestamp}] {text}\n")
        self.log_box.see("end")

    # ── UI Mode & Format Change Handlers ───────────────────────────────────────
    def _on_download_mode_change(self, mode: str):
        if "Selected Components" in mode or "Selective" in mode:
            self.format_menu.configure(values=["MP3 (320 kbps High)", "MP3 (192 kbps)", "WAV (Lossless)", "M4A (AAC)"])
            self.format_menu.set("MP3 (320 kbps High)")
        elif "Video" in mode:
            self.format_menu.configure(values=["Best Quality (1080p+)", "1080p FHD", "720p HD", "480p SD"])
            self.format_menu.set("Best Quality (1080p+)")
        elif "Audio" in mode:
            self.format_menu.configure(values=["MP3 (320 kbps High)", "MP3 (192 kbps)", "WAV (Lossless)", "M4A (AAC)"])
            self.format_menu.set("MP3 (320 kbps High)")
        elif "Thumbnail" in mode:
            self.format_menu.configure(values=[
                "Best Resolution (MaxRes / HD)",
                "Standard HD (sddefault)",
                "High Quality (hqdefault)",
            ])
            self.format_menu.set("Best Resolution (MaxRes / HD)")
        elif "Transcript" in mode:
            self.format_menu.configure(values=[
                "SRT Subtitles (.srt)",
                "VTT Subtitles (.vtt)",
                "Timestamped TXT [00:01:23] (.txt)",
                "Clean Text (No Timestamps) (.txt)",
                "JSON with Timestamps (.json)",
                "All Transcript Formats (Bundle)",
            ])
            self.format_menu.set("SRT Subtitles (.srt)")
        elif "Titles" in mode:
            self.format_menu.configure(values=[
                "Titles List (.txt)",
                "Individual Descriptions (.txt)",
                "Combined Descriptions (.txt)",
                "Full Metadata (CSV & JSON)",
            ])
            self.format_menu.set("Titles List (.txt)")
        elif "Full Package" in mode:
            self.format_menu.configure(values=["MP4 + MP3 + Subtitles + Info Folder"])
            self.format_menu.set("MP4 + MP3 + Subtitles + Info Folder")

    def _paste_url(self):
        try:
            clipboard = self.clipboard_get()
            if clipboard:
                self.url_entry.delete(0, "end")
                self.url_entry.insert(0, clipboard.strip())
        except Exception:
            pass

    def _browse_output_dir(self):
        chosen = filedialog.askdirectory(initialdir=self.output_dir_var.get())
        if chosen:
            self.output_dir_var.set(chosen)

    def _open_output_dir(self):
        target_dir = self.output_dir_var.get()
        os.makedirs(target_dir, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(target_dir)
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", target_dir])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", target_dir])
        except Exception as e:
            self.log(f"⚠️ Could not open folder: {e}")

    # ── Fetching Logic ─────────────────────────────────────────────────────────
    def _start_fetch_videos(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("URL Missing", "Please enter a YouTube Channel handle, URL, or Playlist link.")
            return

        if self.is_fetching or self.is_downloading:
            return

        self.is_fetching = True
        self.cancel_requested = False
        self.fetch_btn.configure(state="disabled", text="⏳ Fetching...")
        self.cancel_btn.configure(state="normal")
        self.progress_bar.set(0.2)
        self.status_label.configure(text="Status: Connecting to YouTube & scanning channel...", text_color=self.COLOR_TEXT)
        self.log(f"🚀 Starting channel scan for: {url}")

        limit_str = self.limit_menu.get()
        limit = None
        if "20" in limit_str:
            limit = 20
        elif "50" in limit_str:
            limit = 50
        elif "100" in limit_str:
            limit = 100
        elif "250" in limit_str:
            limit = 250
        elif "500" in limit_str:
            limit = 500

        type_str = self.type_menu.get()
        filter_type = "all"
        if "Videos Only" in type_str:
            filter_type = "videos_only"
        elif "Shorts Only" in type_str:
            filter_type = "shorts_only"

        threading.Thread(
            target=self._fetch_videos_worker,
            args=(url, limit, filter_type),
            daemon=True,
        ).start()

    def _fetch_videos_worker(self, url: str, limit: Optional[int], filter_type: str):
        try:
            fetched_items = YouTubeEngine.fetch_channel_videos(
                url,
                limit=limit,
                filter_type=filter_type,
                log_cb=self.log,
            )
            self.after(0, self._on_fetch_success, fetched_items)
        except Exception as e:
            self.after(0, self._on_fetch_error, str(e))

    def _on_fetch_success(self, items: List[VideoItem]):
        self.is_fetching = False
        self.fetch_btn.configure(state="normal", text="🔍 Fetch Videos")
        self.cancel_btn.configure(state="disabled")
        self.progress_bar.set(1.0)
        self.videos = items
        self._original_videos = list(items)

        if not items:
            self.status_label.configure(text="Status: No videos found for this channel/URL.", text_color="#f87171")
            self.log("⚠️ No videos found. Check channel URL or privacy settings.")
            self._show_empty_placeholder()
            self._update_stats()
            return

        self.status_label.configure(text=f"Status: Successfully loaded {len(items)} videos!", text_color="#4ade80")
        self.log(f"✅ Found {len(items)} videos. Applying sort & rendering cards...")
        self._apply_sorting()
        self._render_video_cards()
        self._update_stats()

    def _on_sort_change(self, choice: str):
        self.sort_choice = choice
        self._apply_sorting()
        self._render_video_cards()
        self._update_stats()

    def _apply_sorting(self):
        if not self.videos:
            return

        choice = getattr(self, "sort_choice", None)
        if not choice and hasattr(self, "sort_menu"):
            choice = self.sort_menu.get()
        choice = choice or "👁️ Most Views (High ➔ Low)"

        if "Most Views" in choice:
            self.videos.sort(key=lambda v: (v.view_count or 0), reverse=True)
        elif "Least Views" in choice:
            self.videos.sort(key=lambda v: (v.view_count or 0))
        elif "Newest First" in choice:
            self.videos.sort(key=lambda v: str(v.published_date or ""), reverse=True)
        elif "Oldest First" in choice:
            self.videos.sort(key=lambda v: str(v.published_date or "9999-99-99"))
        elif "Longest First" in choice:
            self.videos.sort(key=lambda v: (v.duration or 0), reverse=True)
        elif "Shortest First" in choice:
            self.videos.sort(key=lambda v: (v.duration or 0))
        elif "Title (A ➔ Z)" in choice or "Title A-Z" in choice:
            self.videos.sort(key=lambda v: v.title.lower())
        elif "Title (Z ➔ A)" in choice or "Title Z-A" in choice:
            self.videos.sort(key=lambda v: v.title.lower(), reverse=True)
        elif "Default" in choice:
            if hasattr(self, "_original_videos") and self._original_videos:
                selected_map = {v.video_id: v.selected for v in self.videos}
                self.videos = list(self._original_videos)
                for v in self.videos:
                    if v.video_id in selected_map:
                        v.selected = selected_map[v.video_id]

    def _on_fetch_error(self, err_msg: str):
        self.is_fetching = False
        self.fetch_btn.configure(state="normal", text="🔍 Fetch Videos")
        self.cancel_btn.configure(state="disabled")
        self.progress_bar.set(0.0)
        self.status_label.configure(text=f"Status: Error fetching channel ({err_msg[:60]}...)", text_color="#f87171")
        self.log(f"❌ Error fetching videos: {err_msg}")
        messagebox.showerror("Fetch Failed", f"Failed to fetch videos from channel:\n\n{err_msg}")

    # ── Video Card Progressive Streaming Renderer ─────────────────────────────
    def _render_video_cards(self):
        self._render_batch_token = getattr(self, "_render_batch_token", 0) + 1
        current_token = self._render_batch_token

        for widget in self.video_scroll.winfo_children():
            widget.destroy()

        query = self.active_search_query.lower()
        filtered_items = []
        for item in self.videos:
            if query and query not in item.title.lower():
                continue
            filtered_items.append(item)

        if not filtered_items:
            if self.videos:
                msg = ctk.CTkLabel(
                    self.video_scroll,
                    text="🔍 No videos matched your filter search.",
                    font=("Segoe UI", 12),
                    text_color=self.COLOR_DIM,
                )
                msg.pack(pady=40)
            return

        # Progressive non-blocking slice renderer (25 cards per frame every 10ms)
        chunk_size = 25

        def _render_slice(start_idx: int):
            if getattr(self, "_render_batch_token", 0) != current_token:
                return

            end_idx = min(start_idx + chunk_size, len(filtered_items))
            for idx in range(start_idx, end_idx):
                item = filtered_items[idx]
                self._create_single_card(idx, item)

            if end_idx < len(filtered_items):
                self.after(10, _render_slice, end_idx)

        _render_slice(0)

    def _create_single_card(self, idx: int, item: VideoItem):
        card = ctk.CTkFrame(
            self.video_scroll,
            fg_color=self.COLOR_CARD_ALT,
            corner_radius=8,
            border_width=1,
            border_color=self.COLOR_BORDER,
        )
        card.pack(fill="x", padx=6, pady=2)
        card.grid_columnconfigure(1, weight=1)
        item.card_frame = card

        # Checkbox
        var = ctk.BooleanVar(value=item.selected)
        item.checkbox_var = var
        chk = ctk.CTkCheckBox(
            card,
            text="",
            variable=var,
            width=22,
            checkbox_width=18,
            checkbox_height=18,
            fg_color=self.COLOR_ACCENT,
            hover_color=self.COLOR_ACCENT_HOVER,
            command=lambda it=item: self._on_item_toggle(it),
        )
        chk.grid(row=0, column=0, rowspan=2, padx=(10, 8), pady=6, sticky="w")

        # Plain Video Title (#1 Title)
        title_lbl = ctk.CTkLabel(
            card,
            text=f"#{idx+1}  {item.title}",
            font=("Segoe UI", 12, "bold"),
            text_color=self.COLOR_TEXT,
            anchor="w",
            justify="left",
        )
        title_lbl.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=(5, 1))

        # Views & Metadata directly below title (Plain clean text)
        v_count = item.view_count or 0
        v_str = format_views(v_count)
        meta_text = f"👁️ {v_str} views  •  ⏱️ {item.duration_str}  •  🗓️ {item.published_date or 'Recent'}  •  🆔 {item.video_id}"
        meta_lbl = ctk.CTkLabel(
            card,
            text=meta_text,
            font=("Segoe UI", 10),
            text_color="#38bdf8" if v_count >= 100000 else self.COLOR_DIM,
            anchor="w",
            justify="left",
        )
        meta_lbl.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=(0, 5))

        # Double click row to copy URL
        for w in (card, title_lbl, meta_lbl):
            w.bind("<Double-Button-1>", lambda e, it=item: self._copy_video_url(it))

    # ── Selection & Filter Handlers ────────────────────────────────────────────
    def _on_item_toggle(self, item: VideoItem):
        if item.checkbox_var:
            item.selected = item.checkbox_var.get()
        self._update_stats()

    def _set_all_selection(self, select: bool):
        for item in self.videos:
            item.selected = select
            if item.checkbox_var:
                item.checkbox_var.set(select)
        self._update_stats()

    def _invert_selection(self):
        for item in self.videos:
            item.selected = not item.selected
            if item.checkbox_var:
                item.checkbox_var.set(item.selected)
        self._update_stats()

    def _on_search_change(self):
        query = self.search_entry.get().strip()
        if query != self.active_search_query:
            self.active_search_query = query
            self._render_video_cards()

    def _update_stats(self):
        total = len(self.videos)
        selected_items = [v for v in self.videos if v.selected]
        sel_count = len(selected_items)
        total_seconds = sum(v.duration for v in selected_items)
        dur_str = format_duration(total_seconds)

        self.stats_label.configure(
            text=f"📊  Total: {total} videos  |  Selected: {sel_count}  |  Total Duration: {dur_str}"
        )
        self.download_btn.configure(text=f"🚀 DOWNLOAD SELECTED ({sel_count})")

    def _copy_video_url(self, item: VideoItem):
        self.clipboard_clear()
        self.clipboard_append(item.url)
        self.status_label.configure(text=f"Status: Copied URL for '{item.title[:40]}...' to clipboard!", text_color="#38bdf8")

    # ── Batch Download Manager ─────────────────────────────────────────────────
    def _start_batch_download(self):
        selected_items = [v for v in self.videos if v.selected]
        if not selected_items:
            messagebox.showwarning("No Selection", "Please select at least one video to download.")
            return

        if self.is_downloading:
            return

        output_dir = self.output_dir_var.get().strip()
        if not output_dir:
            messagebox.showwarning("Output Folder", "Please choose a valid destination folder.")
            return
        os.makedirs(output_dir, exist_ok=True)

        mode = self.download_mode_var.get()
        fmt_choice = self.format_menu.get()

        if "Selected Components" in mode or "Selective" in mode:
            do_audio = self.chk_audio_var.get() if hasattr(self, "chk_audio_var") else True
            do_caption = self.chk_caption_var.get() if hasattr(self, "chk_caption_var") else True
            do_link = self.chk_link_var.get() if hasattr(self, "chk_link_var") else True
            do_thumb = self.chk_thumb_var.get() if hasattr(self, "chk_thumb_var") else True
            do_title = self.chk_title_var.get() if hasattr(self, "chk_title_var") else True
            if not any([do_audio, do_caption, do_link, do_thumb, do_title]):
                messagebox.showwarning(
                    "No Items Selected",
                    "Please tick at least one item to download:\n• Audio\n• Caption / Transcript\n• Link\n• Thumbnail\n• Title"
                )
                return

        self.is_downloading = True
        self.cancel_requested = False
        self.download_btn.configure(state="disabled", text="⏳ Downloading...")
        self.cancel_btn.configure(state="normal")
        self.fetch_btn.configure(state="disabled")
        self.progress_bar.set(0.0)

        is_folderwise = self.folderwise_var.get() if hasattr(self, "folderwise_var") else False
        folderwise_note = " [📁 Folder-wise per Song]" if is_folderwise else ""
        self.log(f"🎬 Batch Download initiated for {len(selected_items)} selected videos | Mode: {mode} ({fmt_choice}){folderwise_note}")

        threading.Thread(
            target=self._batch_download_worker,
            args=(selected_items, mode, fmt_choice, output_dir),
            daemon=True,
        ).start()

    def _cancel_operation(self):
        self.cancel_requested = True
        self.status_label.configure(text="Status: Cancelling operation...", text_color="#f87171")
        self.log("🛑 Cancellation requested by user.")

    def _batch_download_worker(self, items: List[VideoItem], mode: str, fmt_choice: str, out_dir: str):
        total = len(items)
        ffmpeg_bin = get_ffmpeg_path()
        success_count = 0
        fail_count = 0
        is_folderwise = self.folderwise_var.get() if hasattr(self, "folderwise_var") else False

        for idx, item in enumerate(items):
            if self.cancel_requested:
                self.log("⏹️ Batch process stopped by user.")
                break

            current_num = idx + 1
            progress_ratio = idx / total
            self.after(0, self.progress_bar.set, progress_ratio)
            self.after(
                0,
                self.status_label.configure,
                {
                    "text": f"Status: [{current_num}/{total}] Processing '{item.title[:45]}...' ({int(progress_ratio*100)}%)",
                    "text_color": self.COLOR_TEXT,
                },
            )
            self.log(f"▶️ [{current_num}/{total}] Processing: {item.title}")

            try:
                if "Selected Components" in mode or "Selective" in mode:
                    self._download_selective_item(item, fmt_choice, out_dir, ffmpeg_bin, is_folderwise)
                elif "Video" in mode:
                    target_dir = os.path.join(out_dir, self._get_item_folder_name(item)) if is_folderwise else out_dir
                    os.makedirs(target_dir, exist_ok=True)
                    self._download_video_item(item, fmt_choice, target_dir, ffmpeg_bin, clean_name_only=is_folderwise)
                elif "Audio" in mode:
                    target_dir = os.path.join(out_dir, self._get_item_folder_name(item)) if is_folderwise else out_dir
                    os.makedirs(target_dir, exist_ok=True)
                    self._download_audio_item(item, fmt_choice, target_dir, ffmpeg_bin, clean_name_only=is_folderwise)
                elif "Thumbnail" in mode:
                    target_dir = os.path.join(out_dir, self._get_item_folder_name(item)) if is_folderwise else out_dir
                    os.makedirs(target_dir, exist_ok=True)
                    self._download_thumbnail_item(item, fmt_choice, target_dir, clean_name_only=is_folderwise)
                elif "Transcript" in mode:
                    target_dir = os.path.join(out_dir, self._get_item_folder_name(item)) if is_folderwise else out_dir
                    os.makedirs(target_dir, exist_ok=True)
                    self._download_transcript_item(item, fmt_choice, target_dir, clean_name_only=is_folderwise)
                elif "Titles" in mode:
                    target_dir = os.path.join(out_dir, self._get_item_folder_name(item)) if is_folderwise else out_dir
                    os.makedirs(target_dir, exist_ok=True)
                    self._download_metadata_item(item, fmt_choice, target_dir, is_batch=True, items_all=items, clean_name_only=is_folderwise)
                    if "Titles List" in fmt_choice or "Combined" in fmt_choice or "Full Metadata" in fmt_choice:
                        success_count = total
                        break
                elif "Full Package" in mode:
                    self._download_full_package_item(item, out_dir, ffmpeg_bin)

                success_count += 1
            except Exception as e:
                fail_count += 1
                self.log(f"❌ Failed processing '{item.title}': {e}")

        self.after(0, self._on_batch_complete, success_count, fail_count, total, out_dir)

    def _on_batch_complete(self, success: int, fail: int, total: int, out_dir: str):
        self.is_downloading = False
        self.download_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.fetch_btn.configure(state="normal")
        self.progress_bar.set(1.0)
        self._update_stats()

        if self.cancel_requested:
            self.status_label.configure(text=f"Status: Cancelled. Completed {success}/{total} items.", text_color="#f87171")
        else:
            self.status_label.configure(
                text=f"Status: ✅ Done! Successfully downloaded {success}/{total} items.", text_color="#4ade80"
            )
            self.log(f"🎉 Batch operation complete! {success} succeeded, {fail} failed.")
            messagebox.showinfo(
                "Download Complete",
                f"Batch download finished!\n\nSuccessfully processed: {success} / {total}\nSaved to: {out_dir}",
            )

    # ── Single Item Download Handlers ──────────────────────────────────────────
    def _download_thumbnail_item(self, item: VideoItem, fmt_choice: str, out_dir: str, clean_name_only: bool = False):
        """Download high-resolution / best available thumbnail for video item."""
        clean_title = sanitize_filename(item.title)
        out_file = os.path.join(out_dir, f"{clean_title}_thumb.jpg" if clean_name_only else f"{clean_title} [{item.video_id}]_thumb.jpg")

        candidates = [
            f"https://img.youtube.com/vi/{item.video_id}/maxresdefault.jpg",
            f"https://img.youtube.com/vi/{item.video_id}/sddefault.jpg",
            f"https://img.youtube.com/vi/{item.video_id}/hqdefault.jpg",
        ]
        if item.thumbnail_url:
            candidates.append(item.thumbnail_url)
        candidates.append(f"https://img.youtube.com/vi/{item.video_id}/mqdefault.jpg")

        saved = False
        for thumb_url in candidates:
            try:
                req = urllib.request.Request(thumb_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status == 200:
                        data = resp.read()
                        if len(data) > 1500:
                            with open(out_file, "wb") as f:
                                f.write(data)
                            saved = True
                            break
            except Exception:
                continue

        if not saved and item.thumbnail_url:
            try:
                req = urllib.request.Request(item.thumbnail_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = resp.read()
                    with open(out_file, "wb") as f:
                        f.write(data)
                    saved = True
            except Exception:
                pass

        if saved:
            self.log(f"🖼️ Downloaded Thumbnail: {os.path.basename(out_file)}")
        else:
            raise RuntimeError(f"Could not download thumbnail for {item.video_id}")

    def _download_video_item(self, item: VideoItem, fmt_choice: str, out_dir: str, ffmpeg_bin: Optional[str], clean_name_only: bool = False):
        if not yt_dlp:
            raise RuntimeError("yt-dlp missing")

        clean_title = sanitize_filename(item.title)
        out_tmpl = os.path.join(out_dir, f"{clean_title}.%(ext)s" if clean_name_only else f"{clean_title} [{item.video_id}].%(ext)s")

        if "480p" in fmt_choice:
            fmt = "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best"
        elif "720p" in fmt_choice:
            fmt = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best"
        elif "1080p FHD" in fmt_choice:
            fmt = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best"
        else:
            fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best"

        ydl_opts: Dict[str, Any] = {
            'format': fmt,
            'outtmpl': out_tmpl,
            'merge_output_format': 'mp4',
            'extractor_args': {'youtube': {'player_client': ['android', 'web', 'mweb']}},
            'quiet': True,
            'no_warnings': True,
        }
        if ffmpeg_bin:
            ydl_opts['ffmpeg_location'] = ffmpeg_bin

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([item.url])

        self.log(f"🎬 Downloaded Video: {clean_title}.mp4")

    def _download_audio_item(self, item: VideoItem, fmt_choice: str, out_dir: str, ffmpeg_bin: Optional[str], clean_name_only: bool = False):
        if not yt_dlp:
            raise RuntimeError("yt-dlp missing")

        clean_title = sanitize_filename(item.title)
        out_tmpl = os.path.join(out_dir, f"{clean_title}.%(ext)s" if clean_name_only else f"{clean_title} [{item.video_id}].%(ext)s")

        codec = "mp3"
        quality = "320"
        if "192" in fmt_choice:
            quality = "192"
        elif "WAV" in fmt_choice:
            codec = "wav"
        elif "M4A" in fmt_choice:
            codec = "m4a"

        ydl_opts: Dict[str, Any] = {
            'format': 'bestaudio/best',
            'outtmpl': out_tmpl,
            'extractor_args': {'youtube': {'player_client': ['android', 'web', 'mweb']}},
            'quiet': True,
            'no_warnings': True,
            'postprocessors': [
                {
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': codec,
                    'preferredquality': quality,
                },
                {
                    'key': 'FFmpegMetadata',
                    'add_metadata': True,
                },
            ],
        }
        if ffmpeg_bin:
            ydl_opts['ffmpeg_location'] = ffmpeg_bin

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([item.url])

        self.log(f"🎵 Downloaded Audio ({codec.upper()}): {clean_title}.{codec}")

    def _download_transcript_item(self, item: VideoItem, fmt_choice: str, out_dir: str, clean_name_only: bool = False):
        lines = YouTubeEngine.fetch_transcript(item.video_id)
        if not lines:
            self.log(f"⚠️ No subtitles/transcript found for '{item.title}'")
            raise RuntimeError(f"No transcript or subtitles available on YouTube for '{item.title}'")

        os.makedirs(out_dir, exist_ok=True)
        clean_title = sanitize_filename(item.title)
        prefix = clean_title if clean_name_only else f"{clean_title} [{item.video_id}]"
        saved_any = False

        if "SRT" in fmt_choice or "Bundle" in fmt_choice:
            srt_path = os.path.join(out_dir, f"{prefix}.srt")
            with open(srt_path, "w", encoding="utf-8") as f:
                for idx, line in enumerate(lines, start=1):
                    t_start = format_srt_time(line["start"])
                    t_end = format_srt_time(line["end"])
                    f.write(f"{idx}\n{t_start} --> {t_end}\n{line['text']}\n\n")
            self.log(f"📝 Saved SRT: {os.path.basename(srt_path)}")
            saved_any = True

        if "VTT" in fmt_choice or "Bundle" in fmt_choice:
            vtt_path = os.path.join(out_dir, f"{prefix}.vtt")
            with open(vtt_path, "w", encoding="utf-8") as f:
                f.write("WEBVTT\n\n")
                for line in lines:
                    t_start = format_vtt_time(line["start"])
                    t_end = format_vtt_time(line["end"])
                    f.write(f"{t_start} --> {t_end}\n{line['text']}\n\n")
            self.log(f"📝 Saved VTT: {os.path.basename(vtt_path)}")
            saved_any = True

        if "Timestamped" in fmt_choice or "Bundle" in fmt_choice:
            txt_path = os.path.join(out_dir, f"{prefix}_timestamps.txt" if clean_name_only else f"{prefix}_timestamps [{item.video_id}].txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(f"Title: {item.title}\nURL: {item.url}\n\n=== TRANSCRIPT WITH TIMESTAMPS ===\n\n")
                for line in lines:
                    f.write(f"[{line['timestamp']}] {line['text']}\n")
            self.log(f"📝 Saved Timestamped TXT: {os.path.basename(txt_path)}")
            saved_any = True

        if "Clean Text" in fmt_choice or "Bundle" in fmt_choice:
            txt_path = os.path.join(out_dir, f"{prefix}_clean.txt" if clean_name_only else f"{prefix}_clean [{item.video_id}].txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(f"Title: {item.title}\nURL: {item.url}\n\n")
                f.write(" ".join(l["text"] for l in lines))
            self.log(f"📝 Saved Clean TXT: {os.path.basename(txt_path)}")
            saved_any = True

        if "JSON" in fmt_choice or "Bundle" in fmt_choice:
            json_path = os.path.join(out_dir, f"{prefix}.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump({
                    "video_id": item.video_id,
                    "title": item.title,
                    "url": item.url,
                    "duration": item.duration,
                    "segments": lines,
                }, f, indent=2, ensure_ascii=False)
            self.log(f"📝 Saved Subtitle JSON: {os.path.basename(json_path)}")
            saved_any = True

        if not saved_any:
            txt_path = os.path.join(out_dir, f"{prefix}_timestamps.txt" if clean_name_only else f"{prefix}_timestamps [{item.video_id}].txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(f"Title: {item.title}\nURL: {item.url}\n\n=== TRANSCRIPT WITH TIMESTAMPS ===\n\n")
                for line in lines:
                    f.write(f"[{line['timestamp']}] {line['text']}\n")
            self.log(f"📝 Saved Transcript: {os.path.basename(txt_path)}")

    def _download_metadata_item(self, item: VideoItem, fmt_choice: str, out_dir: str, is_batch=False, items_all=None, clean_name_only: bool = False):
        clean_title = sanitize_filename(item.title)
        prefix = clean_title if clean_name_only else f"{clean_title} [{item.video_id}]"

        if "Titles List" in fmt_choice:
            titles_path = os.path.join(out_dir, "selected_video_titles.txt")
            selected_items = items_all if items_all else [item]
            with open(titles_path, "w", encoding="utf-8") as f:
                f.write(f"=== YOUTUBE SELECTED VIDEO TITLES ({len(selected_items)}) ===\n\n")
                for idx, it in enumerate(selected_items, start=1):
                    f.write(f"{idx}. {it.title}  [{it.duration_str}] — {it.url}\n")
            self.log(f"📋 Exported Titles List: {os.path.basename(titles_path)}")

        elif "Individual Descriptions" in fmt_choice:
            desc_dir = os.path.join(out_dir, "descriptions")
            os.makedirs(desc_dir, exist_ok=True)
            desc_path = os.path.join(desc_dir, f"{prefix}_desc.txt")
            
            desc = item.description
            if not desc:
                meta = YouTubeEngine.fetch_full_metadata(item.url)
                desc = meta.get("description") or ""
                item.description = desc

            with open(desc_path, "w", encoding="utf-8") as f:
                f.write(f"Title: {item.title}\nURL: {item.url}\nDuration: {item.duration_str}\nViews: {item.view_count}\n\n=== DESCRIPTION ===\n\n{desc}\n")
            self.log(f"📋 Saved Description: {os.path.basename(desc_path)}")

        elif "Combined Descriptions" in fmt_choice:
            comb_path = os.path.join(out_dir, "all_selected_descriptions.txt")
            selected_items = items_all if items_all else [item]
            with open(comb_path, "w", encoding="utf-8") as f:
                f.write(f"=== ALL DESCRIPTIONS ({len(selected_items)} VIDEOS) ===\n\n")
                for idx, it in enumerate(selected_items, start=1):
                    desc = it.description
                    if not desc:
                        meta = YouTubeEngine.fetch_full_metadata(it.url)
                        desc = meta.get("description") or ""
                        it.description = desc
                    f.write(f"--------------------------------------------------------------------------------\n")
                    f.write(f"#{idx} | {it.title}\nURL: {it.url} | Duration: {it.duration_str} | Date: {it.published_date}\n")
                    f.write(f"--------------------------------------------------------------------------------\n")
                    f.write(f"{desc}\n\n\n")
            self.log(f"📋 Saved Combined Descriptions: {os.path.basename(comb_path)}")

        elif "Full Metadata" in fmt_choice:
            selected_items = items_all if items_all else [item]
            csv_path = os.path.join(out_dir, "youtube_metadata.csv")
            json_path = os.path.join(out_dir, "youtube_metadata.json")

            with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Index", "Video ID", "Title", "URL", "Duration (sec)", "Duration (formatted)", "Views", "Published Date", "Thumbnail URL"])
                for idx, it in enumerate(selected_items, start=1):
                    writer.writerow([idx, it.video_id, it.title, it.url, it.duration, it.duration_str, it.view_count, it.published_date, it.thumbnail_url])

            json_data = [
                {
                    "index": idx,
                    "video_id": it.video_id,
                    "title": it.title,
                    "url": it.url,
                    "duration": it.duration,
                    "duration_formatted": it.duration_str,
                    "view_count": it.view_count,
                    "published_date": it.published_date,
                    "thumbnail_url": it.thumbnail_url,
                }
                for idx, it in enumerate(selected_items, start=1)
            ]
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(json_data, f, indent=2, ensure_ascii=False)

            self.log(f"📋 Exported CSV & JSON Metadata to: {os.path.basename(csv_path)}, {os.path.basename(json_path)}")

    def _get_item_folder_name(self, item: VideoItem) -> str:
        """Generate clean song folder name including upload date if available (e.g. 'Song Name [2023-11-05]')."""
        clean_title = sanitize_filename(item.title)
        pub_date = (item.published_date or "").strip()
        if not pub_date:
            try:
                meta = YouTubeEngine.fetch_full_metadata(item.url)
                raw_date = meta.get('upload_date') or meta.get('timestamp') or ""
                if isinstance(raw_date, (int, float)) and raw_date > 0:
                    pub_date = time.strftime("%Y-%m-%d", time.localtime(raw_date))
                elif isinstance(raw_date, str) and len(raw_date) == 8 and raw_date.isdigit():
                    pub_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
                elif isinstance(raw_date, str):
                    pub_date = raw_date
                item.published_date = pub_date
                if not item.description and meta.get('description'):
                    item.description = meta.get('description')
            except Exception:
                pass

        if pub_date:
            clean_date = re.sub(r'[\\/*?:"<>|]', '-', pub_date)
            return sanitize_filename(f"{clean_title} [{clean_date}]")
        return clean_title

    def _download_selective_item(self, item: VideoItem, fmt_choice: str, base_out_dir: str, ffmpeg_bin: Optional[str], is_folderwise: bool):
        """Download user-selected components (Audio, Caption, Link, Thumbnail, Title).
        If folderwise is True, items are saved inside a dedicated subfolder named after the song and upload date!"""
        clean_title = sanitize_filename(item.title)

        if is_folderwise:
            folder_name = self._get_item_folder_name(item)
            target_dir = os.path.join(base_out_dir, folder_name)
        else:
            folder_name = clean_title
            target_dir = base_out_dir
        os.makedirs(target_dir, exist_ok=True)

        do_audio = self.chk_audio_var.get() if hasattr(self, "chk_audio_var") else True
        do_caption = self.chk_caption_var.get() if hasattr(self, "chk_caption_var") else True
        do_link = self.chk_link_var.get() if hasattr(self, "chk_link_var") else True
        do_thumb = self.chk_thumb_var.get() if hasattr(self, "chk_thumb_var") else True
        do_title = self.chk_title_var.get() if hasattr(self, "chk_title_var") else True

        if not any([do_audio, do_caption, do_link, do_thumb, do_title]):
            self.log(f"⚠️ No components selected for '{clean_title}'.")
            return

        downloaded_tags = []

        # 1. Title
        if do_title:
            try:
                title_filename = "title.txt" if is_folderwise else f"{clean_title} [{item.video_id}]_title.txt"
                title_file = os.path.join(target_dir, title_filename)
                with open(title_file, "w", encoding="utf-8") as f:
                    f.write(f"{item.title}\n")
                    f.write(f"\nChannel: {item.uploader}\n")
                    if item.published_date:
                        f.write(f"Published: {item.published_date}\n")
                    if item.duration_str:
                        f.write(f"Duration: {item.duration_str}\n")
                    if item.view_count:
                        f.write(f"Views: {item.view_count}\n")
                    if item.description:
                        f.write(f"\n=== Description ===\n{item.description}\n")
                downloaded_tags.append("Title")
            except Exception as e:
                self.log(f"⚠️ Error saving title for '{clean_title}': {e}")

        # 2. Link
        if do_link:
            try:
                link_filename = "link.txt" if is_folderwise else f"{clean_title} [{item.video_id}]_link.txt"
                link_file = os.path.join(target_dir, link_filename)
                with open(link_file, "w", encoding="utf-8") as f:
                    f.write(f"{item.url}\n\nTitle: {item.title}\nVideo ID: {item.video_id}\nChannel: {item.uploader}\n")

                if is_folderwise:
                    url_shortcut = os.path.join(target_dir, f"{clean_title}.url")
                    try:
                        with open(url_shortcut, "w", encoding="utf-8") as f:
                            f.write(f"[InternetShortcut]\nURL={item.url}\n")
                    except Exception:
                        pass
                downloaded_tags.append("Link")
            except Exception as e:
                self.log(f"⚠️ Error saving link for '{clean_title}': {e}")

        # 3. Thumbnail
        if do_thumb:
            try:
                thumb_target_name = "thumbnail.jpg" if is_folderwise else f"{clean_title} [{item.video_id}]_thumb.jpg"
                thumb_dest = os.path.join(target_dir, thumb_target_name)

                candidates = [
                    f"https://img.youtube.com/vi/{item.video_id}/maxresdefault.jpg",
                    f"https://img.youtube.com/vi/{item.video_id}/sddefault.jpg",
                    f"https://img.youtube.com/vi/{item.video_id}/hqdefault.jpg",
                ]
                if item.thumbnail_url:
                    candidates.append(item.thumbnail_url)
                candidates.append(f"https://img.youtube.com/vi/{item.video_id}/mqdefault.jpg")

                saved = False
                for turl in candidates:
                    try:
                        req = urllib.request.Request(turl, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req, timeout=10) as resp:
                            if resp.status == 200:
                                data = resp.read()
                                if len(data) > 1500:
                                    with open(thumb_dest, "wb") as f:
                                        f.write(data)
                                    saved = True
                                    break
                    except Exception:
                        continue

                if not saved and item.thumbnail_url:
                    try:
                        req = urllib.request.Request(item.thumbnail_url, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req, timeout=10) as resp:
                            with open(thumb_dest, "wb") as f:
                                f.write(resp.read())
                            saved = True
                    except Exception:
                        pass

                if saved:
                    if is_folderwise:
                        named_thumb = os.path.join(target_dir, f"{clean_title}_thumb.jpg")
                        try:
                            shutil.copyfile(thumb_dest, named_thumb)
                        except Exception:
                            pass
                    downloaded_tags.append("Thumbnail")
                else:
                    self.log(f"⚠️ Thumbnail unavailable for '{clean_title}'")
            except Exception as e:
                self.log(f"⚠️ Error downloading thumbnail for '{clean_title}': {e}")

        # 4. Caption / Transcript
        if do_caption:
            try:
                lines = YouTubeEngine.fetch_transcript(item.video_id)
                if lines:
                    srt_file = os.path.join(target_dir, f"{clean_title}.srt" if is_folderwise else f"{clean_title} [{item.video_id}].srt")
                    with open(srt_file, "w", encoding="utf-8") as f:
                        for s_idx, s_line in enumerate(lines, start=1):
                            t_start = format_srt_time(s_line["start"])
                            t_end = format_srt_time(s_line["end"])
                            f.write(f"{s_idx}\n{t_start} --> {t_end}\n{s_line['text']}\n\n")

                    txt_file = os.path.join(target_dir, f"{clean_title}_transcript.txt" if is_folderwise else f"{clean_title} [{item.video_id}]_transcript.txt")
                    with open(txt_file, "w", encoding="utf-8") as f:
                        f.write(f"Title: {item.title}\nURL: {item.url}\n\n=== TRANSCRIPT WITH TIMESTAMPS ===\n\n")
                        for s_line in lines:
                            f.write(f"[{s_line['timestamp']}] {s_line['text']}\n")
                    downloaded_tags.append("Caption/Transcript")
                else:
                    self.log(f"ℹ️ No YouTube subtitles/captions found for '{clean_title}'")
            except Exception as e:
                self.log(f"⚠️ Caption fetch skipped for '{clean_title}': {e}")

        # 5. Audio
        if do_audio:
            try:
                self._download_audio_item(item, fmt_choice, target_dir, ffmpeg_bin, clean_name_only=is_folderwise)
                downloaded_tags.append("Audio")
            except Exception as e:
                self.log(f"⚠️ Audio download error for '{clean_title}': {e}")
                raise e

        tags_str = ", ".join(downloaded_tags) if downloaded_tags else "None"
        where_str = f"subfolder '{folder_name}'" if is_folderwise else "destination folder"
        self.log(f"✅ Saved [{tags_str}] for '{clean_title}' in {where_str}")

    def _download_full_package_item(self, item: VideoItem, base_out_dir: str, ffmpeg_bin: Optional[str]):
        clean_title = sanitize_filename(item.title)
        folder_name = self._get_item_folder_name(item)
        item_folder = os.path.join(base_out_dir, folder_name)
        os.makedirs(item_folder, exist_ok=True)

        try:
            self._download_video_item(item, "Best Quality (1080p+)", item_folder, ffmpeg_bin, clean_name_only=True)
        except Exception as e:
            self.log(f"⚠️ Video download error for package: {e}")

        try:
            self._download_audio_item(item, "MP3 (320 kbps High)", item_folder, ffmpeg_bin, clean_name_only=True)
        except Exception as e:
            self.log(f"⚠️ Audio download error for package: {e}")

        try:
            self._download_thumbnail_item(item, "Best Resolution (MaxRes / HD)", item_folder, clean_name_only=True)
        except Exception as e:
            self.log(f"⚠️ Thumbnail download error for package: {e}")

        try:
            self._download_transcript_item(item, "All Transcript Formats (Bundle)", item_folder, clean_name_only=True)
        except Exception as e:
            self.log(f"⚠️ Transcript download error for package: {e}")

        try:
            desc = item.description
            if not desc:
                meta = YouTubeEngine.fetch_full_metadata(item.url)
                desc = meta.get("description") or ""
            with open(os.path.join(item_folder, "description.txt"), "w", encoding="utf-8") as f:
                f.write(f"Title: {item.title}\nURL: {item.url}\n\n=== DESCRIPTION ===\n\n{desc}")
        except Exception:
            pass

        self.log(f"📦 Full Package Created: {os.path.basename(item_folder)}")

    # ── Quick Single Action Triggers ───────────────────────────────────────────
    def _quick_download_single(self, item: VideoItem, media_type: str):
        out_dir = self.output_dir_var.get().strip()
        os.makedirs(out_dir, exist_ok=True)
        ffmpeg_bin = get_ffmpeg_path()

        self.log(f"⚡ Starting quick download of {media_type.upper()} for: {item.title}")
        self.status_label.configure(text=f"Status: Downloading {media_type.upper()} for '{item.title[:30]}...'")

        def _task():
            try:
                if media_type == "video":
                    self._download_video_item(item, "Best Quality (1080p+)", out_dir, ffmpeg_bin)
                elif media_type == "audio":
                    self._download_audio_item(item, "MP3 (320 kbps High)", out_dir, ffmpeg_bin)
                elif media_type == "thumbnail":
                    self._download_thumbnail_item(item, "Best Resolution (MaxRes / HD)", out_dir)
                self.after(0, lambda: messagebox.showinfo("Downloaded", f"Successfully downloaded {media_type.upper()}:\n{item.title}\n\nSaved to: {out_dir}"))
                self.after(0, lambda: self.status_label.configure(text="Status: Download complete!", text_color="#4ade80"))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Download Error", f"Failed: {e}"))
                self.after(0, lambda: self.status_label.configure(text=f"Status: Download failed ({str(e)[:40]})", text_color="#f87171"))

        threading.Thread(target=_task, daemon=True).start()

    # ── Modal Dialogs (Transcript Preview & Info Viewer) ────────────────────────
    def _preview_transcript_modal(self, item: VideoItem):
        modal = ctk.CTkToplevel(self)
        modal.title(f"📝 Subtitles & Transcript — {item.title[:50]}")
        modal.geometry("780x560")
        modal.configure(fg_color=self.COLOR_BG)
        modal.transient(self)
        modal.grab_set()

        header = ctk.CTkFrame(modal, fg_color=self.COLOR_CARD, corner_radius=0)
        header.pack(fill="x", padx=0, pady=0)

        ctk.CTkLabel(
            header,
            text=f"📝  Transcript with Timestamps",
            font=("Segoe UI", 15, "bold"),
            text_color="#38bdf8",
        ).pack(side="left", padx=16, pady=12)

        ctk.CTkLabel(
            header,
            text=f"Duration: {item.duration_str}",
            font=("Segoe UI", 11),
            text_color=self.COLOR_DIM,
        ).pack(side="right", padx=16, pady=12)

        text_box = ctk.CTkTextbox(
            modal,
            font=("Consolas", 11),
            fg_color=self.COLOR_CARD,
            text_color=self.COLOR_TEXT,
            wrap="word",
        )
        text_box.pack(fill="both", expand=True, padx=16, pady=12)
        text_box.insert("end", "⏳ Fetching subtitles with timestamps from YouTube API...\nPlease wait...")

        bottom = ctk.CTkFrame(modal, fg_color="transparent")
        bottom.pack(fill="x", padx=16, pady=(0, 14))

        copy_btn = ctk.CTkButton(
            bottom,
            text="📋 Copy Transcript",
            width=130,
            fg_color=self.COLOR_SECONDARY,
            hover_color=self.COLOR_SECONDARY_HOVER,
            command=lambda: [self.clipboard_clear(), self.clipboard_append(text_box.get("1.0", "end")), messagebox.showinfo("Copied", "Transcript copied to clipboard!", parent=modal)],
        )
        copy_btn.pack(side="left", padx=(0, 8))

        save_srt_btn = ctk.CTkButton(
            bottom,
            text="💾 Save as SRT",
            width=110,
            fg_color=self.COLOR_CARD_ALT,
            hover_color=self.COLOR_BORDER,
            command=lambda: self._save_modal_transcript(item, "srt", text_box.get("1.0", "end")),
        )
        save_srt_btn.pack(side="left", padx=(0, 8))

        save_txt_btn = ctk.CTkButton(
            bottom,
            text="💾 Save as TXT",
            width=110,
            fg_color=self.COLOR_CARD_ALT,
            hover_color=self.COLOR_BORDER,
            command=lambda: self._save_modal_transcript(item, "txt", text_box.get("1.0", "end")),
        )
        save_txt_btn.pack(side="left")

        ctk.CTkButton(
            bottom,
            text="Close",
            width=80,
            fg_color=self.COLOR_CARD_ALT,
            hover_color=self.COLOR_BORDER,
            command=modal.destroy,
        ).pack(side="right")

        def _fetch_sub():
            lines = YouTubeEngine.fetch_transcript(item.video_id)
            modal.after(0, lambda: self._populate_transcript_modal(text_box, lines, item))

        threading.Thread(target=_fetch_sub, daemon=True).start()

    def _populate_transcript_modal(self, text_box: ctk.CTkTextbox, lines: List[Dict[str, Any]], item: VideoItem):
        text_box.delete("1.0", "end")
        if not lines:
            text_box.insert("end", "⚠️ No captions / subtitles found for this video.\n\nYouTube did not provide automatic or manual captions for this specific video ID.")
            return

        text_box.insert("end", f"Video Title: {item.title}\nURL: {item.url}\nTotal Lines: {len(lines)}\n\n")
        text_box.insert("end", "=================== TRANSCRIPT WITH TIMESTAMPS ===================\n\n")
        for line in lines:
            text_box.insert("end", f"[{line['timestamp']}] {line['text']}\n")

    def _save_modal_transcript(self, item: VideoItem, ext: str, content: str):
        default_name = f"{sanitize_filename(item.title)}.{ext}"
        path = filedialog.asksaveasfilename(initialfile=default_name, defaultextension=f".{ext}")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            messagebox.showinfo("Saved", f"Transcript saved successfully to:\n{path}")

    def _view_video_info_modal(self, item: VideoItem):
        modal = ctk.CTkToplevel(self)
        modal.title(f"ℹ️ Video Details — {item.title[:50]}")
        modal.geometry("780x560")
        modal.configure(fg_color=self.COLOR_BG)
        modal.transient(self)
        modal.grab_set()

        header = ctk.CTkFrame(modal, fg_color=self.COLOR_CARD, corner_radius=0)
        header.pack(fill="x", padx=0, pady=0)

        ctk.CTkLabel(
            header,
            text=f"ℹ️  Video Metadata & Description",
            font=("Segoe UI", 15, "bold"),
            text_color="#a78bfa",
        ).pack(side="left", padx=16, pady=12)

        content = ctk.CTkFrame(modal, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=16, pady=12)

        info_text = f"Title: {item.title}\nURL: {item.url}\nVideo ID: {item.video_id}\nDuration: {item.duration_str} ({item.duration}s)\nViews: {format_views(item.view_count)}\nPublished Date: {item.published_date}\n\n=== FULL DESCRIPTION ===\n\n"
        
        desc_box = ctk.CTkTextbox(
            content,
            font=("Segoe UI", 11),
            fg_color=self.COLOR_CARD,
            text_color=self.COLOR_TEXT,
            wrap="word",
        )
        desc_box.pack(fill="both", expand=True)
        desc_box.insert("end", info_text + (item.description or "Loading full description..."))

        if not item.description:
            def _load_desc():
                meta = YouTubeEngine.fetch_full_metadata(item.url)
                full_desc = meta.get("description") or "No description provided by uploader."
                item.description = full_desc
                modal.after(0, lambda: [desc_box.delete("1.0", "end"), desc_box.insert("end", info_text + full_desc)])
            threading.Thread(target=_load_desc, daemon=True).start()

        bottom = ctk.CTkFrame(modal, fg_color="transparent")
        bottom.pack(fill="x", padx=16, pady=(0, 14))

        ctk.CTkButton(
            bottom,
            text="📋 Copy All Info",
            width=120,
            fg_color=self.COLOR_SECONDARY,
            hover_color=self.COLOR_SECONDARY_HOVER,
            command=lambda: [self.clipboard_clear(), self.clipboard_append(desc_box.get("1.0", "end")), messagebox.showinfo("Copied", "Metadata copied to clipboard!", parent=modal)],
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            bottom,
            text="🖼️ Save HD Thumbnail",
            width=140,
            fg_color=self.COLOR_CARD_ALT,
            hover_color=self.COLOR_BORDER,
            text_color="#f59e0b",
            font=("Segoe UI", 11, "bold"),
            command=lambda: self._quick_download_single(item, "thumbnail"),
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            bottom,
            text="🎬 Download MP4",
            width=120,
            fg_color=self.COLOR_CARD_ALT,
            hover_color=self.COLOR_BORDER,
            text_color="#4ade80",
            command=lambda: self._quick_download_single(item, "video"),
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            bottom,
            text="🎵 Download MP3",
            width=120,
            fg_color=self.COLOR_CARD_ALT,
            hover_color=self.COLOR_BORDER,
            text_color="#fb7185",
            command=lambda: self._quick_download_single(item, "audio"),
        ).pack(side="left")

        ctk.CTkButton(
            bottom,
            text="Close",
            width=80,
            fg_color=self.COLOR_CARD_ALT,
            hover_color=self.COLOR_BORDER,
            command=modal.destroy,
        ).pack(side="right")


# ═══════════════════════════════════════════════════════════════════════════════
# PLUGIN EXPORT & STANDALONE RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

def create(parent_frame, boot_data=None):
    """Entry point for StoriesStudio plugin_loader."""
    frame = YouTubeDataFetcherFrame(parent_frame, boot_data=boot_data)
    try:
        frame.pack(fill="both", expand=True)
    except Exception:
        frame.grid(row=0, column=0, sticky="nsew")
        try:
            parent_frame.grid_columnconfigure(0, weight=1)
            parent_frame.grid_rowconfigure(0, weight=1)
        except Exception:
            pass
    return frame


if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    root.title("YouTube Data Fetcher — Standalone")
    root.geometry("1280x850")
    root.minsize(980, 650)
    
    app_frame = YouTubeDataFetcherFrame(root)
    app_frame.pack(fill="both", expand=True)
    
    root.mainloop()
