"""
video_engine.py — High Performance FFmpeg Dual-Video Rendering & Overlay Engine
Features:
- Multi-Resolution Support: 720p (HD), 1080p (Full HD), 2K (1440p Quad HD), 4K (2160p Ultra HD)
- Customizable Render Quality (CRF 15-24, Presets), Audio Bitrate (128k-320k), and Frame Rate (24-60 FPS)
- Dual Modes: "image_to_music" (Dual Images with Ken Burns/Motion) & "video_to_music" (Looped Background Video + AI Cutout Subject)
- Integrated AI Background Removal helper (rembg u2netp lightweight model)
- Automated YouTube-Formatted Chapter Timestamps & Tracklist Sequence .txt Exporter
- Custom Output Save Directory & Custom Filename Handling
- 10 Modern Player Overlay Styles, Rich Visualizers & Typography Controls
"""

import os
import sys
import shutil
import subprocess
import json
import time
import random
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Tuple

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def _safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        safe_args = [str(a).encode("ascii", errors="replace").decode("ascii") for a in args]
        print(*safe_args, **kwargs)
    except Exception:
        pass


def find_binary(name: str) -> str:
    """Find ffmpeg/ffprobe binary path checking bundled bin directory and system paths first."""
    base_dir = Path(__file__).resolve().parent
    meipass_dir = Path(getattr(sys, "_MEIPASS", "")) if hasattr(sys, "_MEIPASS") else None
    exe_dir = Path(sys.executable).parent

    candidates = [
        base_dir / "bin" / f"{name}.exe",
        base_dir / "bin" / name,
        exe_dir / "bin" / f"{name}.exe",
        exe_dir / "bin" / name,
        exe_dir / f"{name}.exe",
        exe_dir / name,
    ]

    if meipass_dir:
        candidates.extend([
            meipass_dir / "bin" / f"{name}.exe",
            meipass_dir / "bin" / name,
            meipass_dir / f"{name}.exe",
            meipass_dir / name,
        ])

    # Common macOS Homebrew / MacPorts system paths
    if sys.platform == "darwin":
        candidates.extend([
            Path(f"/opt/homebrew/bin/{name}"),
            Path(f"/usr/local/bin/{name}"),
            Path(f"/opt/local/bin/{name}"),
            Path(f"/usr/bin/{name}"),
        ])

    for c in candidates:
        if c and c.is_file():
            return str(c)

    return shutil.which(name) or name



FFMPEG_BIN = find_binary("ffmpeg")
FFPROBE_BIN = find_binary("ffprobe")


# ════════════════════════════════════════════════════════════════════════════════
# RESOLUTION & QUALITY DEFINITIONS
# ════════════════════════════════════════════════════════════════════════════════

RESOLUTIONS = {
    "720p HD (1280x720)": (1280, 720),
    "1080p Full HD (1920x1080)": (1920, 1080),
    "2K Quad HD (2560x1440)": (2560, 1440),
    "4K Ultra HD (3840x2160)": (3840, 2160),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "1k": (1920, 1080),
    "2k": (2560, 1440),
    "4k": (3840, 2160)
}

def parse_resolution(res_str: str) -> Tuple[int, int]:
    """Parses resolution string like '1080p', '4k', '2K Quad HD (2560x1440)' -> (w, h)."""
    if not res_str:
        return (1920, 1080)
    clean = res_str.strip()
    if clean in RESOLUTIONS:
        return RESOLUTIONS[clean]
    lower = clean.lower()
    for k, v in RESOLUTIONS.items():
        if k.lower() in lower:
            return v
    if "720" in lower:
        return (1280, 720)
    if "4k" in lower or "2160" in lower:
        return (3840, 2160)
    if "2k" in lower or "1440" in lower:
        return (2560, 1440)
    return (1920, 1080)


def parse_quality_settings(quality_str: str) -> Tuple[str, str]:
    """Returns (crf_value, x264_preset) based on quality choice."""
    lower = (quality_str or "").lower()
    if "fast" in lower or "high speed" in lower:
        return ("24", "veryfast")
    elif "ultra" in lower or "crisp" in lower:
        return ("18", "medium")
    elif "maximum" in lower or "lossless" in lower:
        return ("15", "slow")
    else:
        # Balanced (default)
        return ("21", "fast")


# ════════════════════════════════════════════════════════════════════════════════
# GPU HARDWARE ACCELERATION DETECTION & OPTIMIZATION
# ════════════════════════════════════════════════════════════════════════════════

_GPU_DETECTION_CACHE: Optional[Dict[str, Any]] = None

def detect_hardware_acceleration(force_refresh: bool = False) -> Dict[str, Any]:
    """
    Detects GPU hardware encoders and primary GPU name via centralized cache or hardware_accel.
    Caches result for instant performance across the studio.
    """
    global _GPU_DETECTION_CACHE
    if _GPU_DETECTION_CACHE is not None and not force_refresh:
        return _GPU_DETECTION_CACHE

    try:
        import hardware_accel
        hw = hardware_accel.get_hardware_info(force_refresh=force_refresh)
        primary_gpu = hw.get("gpu_name", "Generic Display Adapter")
        enc = hw.get("hw_encoder", "libx264")
        vendor = hw.get("gpu_vendor", "none")
        is_gpu = hw.get("is_gpu", False)

        if vendor == "nvidia" or enc == "h264_nvenc":
            result = {
                "type": "nvenc",
                "encoder": "h264_nvenc",
                "gpu_name": primary_gpu,
                "badge_text": f"⚡ GPU Active: {primary_gpu} (NVIDIA NVENC)",
                "badge_color": "#4ade80",
                "is_gpu": True
            }
        elif vendor == "intel" or enc == "h264_qsv":
            result = {
                "type": "qsv",
                "encoder": "h264_qsv",
                "gpu_name": primary_gpu,
                "badge_text": f"⚡ GPU Active: {primary_gpu} (Intel QuickSync)",
                "badge_color": "#38bdf8",
                "is_gpu": True
            }
        elif vendor == "amd" or enc == "h264_amf":
            result = {
                "type": "amf",
                "encoder": "h264_amf",
                "gpu_name": primary_gpu,
                "badge_text": f"⚡ GPU Active: {primary_gpu} (AMD AMF)",
                "badge_color": "#f97316",
                "is_gpu": True
            }
        elif is_gpu:
            result = {
                "type": "gpu",
                "encoder": enc,
                "gpu_name": primary_gpu,
                "badge_text": f"⚡ GPU Active: {primary_gpu} ({enc})",
                "badge_color": "#a855f7",
                "is_gpu": True
            }
        else:
            result = {
                "type": "cpu",
                "encoder": "libx264",
                "gpu_name": primary_gpu,
                "badge_text": "💻 CPU Multi-Threaded (libx264 High-Performance)",
                "badge_color": "#f59e0b",
                "is_gpu": False
            }
    except Exception:
        result = {
            "type": "cpu",
            "encoder": "libx264",
            "gpu_name": "CPU System",
            "badge_text": "💻 CPU Multi-Threaded (libx264)",
            "badge_color": "#f59e0b",
            "is_gpu": False
        }

    _GPU_DETECTION_CACHE = result
    return result


def get_video_encoder_flags(
    gpu_mode: str = "auto",
    crf_val: str = "21",
    cpu_preset: str = "fast",
    threads: Optional[int] = None
) -> List[str]:
    """
    Resolves optimal FFmpeg encoder flags based on GPU / hardware choice.
    Uses safe, universal parameters to prevent unsupported preset errors and driver crashes.
    """
    hw_info = detect_hardware_acceleration()
    mode = (gpu_mode or "auto").lower()

    if "auto" in mode:
        target_enc = hw_info.get("encoder", "libx264")
    elif "nvenc" in mode:
        target_enc = "h264_nvenc"
    elif "qsv" in mode:
        target_enc = "h264_qsv"
    elif "amf" in mode:
        target_enc = "h264_amf"
    else:
        target_enc = "libx264"

    safe_threads = threads or max(2, min(6, (os.cpu_count() or 4)))

    if target_enc == "h264_nvenc":
        return [
            "-c:v", "h264_nvenc",
            "-preset", "fast",
            "-rc", "vbr",
            "-cq", str(crf_val),
            "-b:v", "0",
            "-maxrate", "25M",
            "-bufsize", "50M"
        ]
    elif target_enc == "h264_qsv":
        return ["-c:v", "h264_qsv", "-preset", "medium", "-global_quality", str(crf_val)]
    elif target_enc == "h264_amf":
        return ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "vbr_latency", "-qp_i", str(crf_val), "-qp_p", str(crf_val)]
    else:
        return ["-c:v", "libx264", "-preset", str(cpu_preset or "fast"), "-crf", str(crf_val), "-threads", str(safe_threads)]



# ════════════════════════════════════════════════════════════════════════════════
# AI BACKGROUND REMOVAL (CUTOUT) HELPER
# ════════════════════════════════════════════════════════════════════════════════

_rembg_session = None

def remove_image_background(input_path: str, output_path: str, log_fn: Optional[Callable[[str], None]] = None) -> bool:
    """
    Removes background from an image and saves as transparent PNG.
    Uses ultra-fast local u2netp ONNX model via rembg.
    """
    global _rembg_session
    if not os.path.exists(input_path):
        return False
    try:
        if log_fn:
            log_fn("Initializing AI Background Removal...")
        import rembg
        from PIL import Image

        if _rembg_session is None:
            _rembg_session = rembg.new_session("u2netp")

        with open(input_path, "rb") as f:
            input_bytes = f.read()

        if log_fn:
            log_fn("Processing subject segmentation & alpha cutout...")

        output_bytes = rembg.remove(input_bytes, session=_rembg_session)

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(output_bytes)

        if log_fn:
            log_fn(f"Cutout created successfully: {Path(output_path).name}")
        return True
    except Exception as ex:
        _safe_print(f"[REMBG ERROR] {ex}")
        if log_fn:
            log_fn(f"Background removal notice: {ex}")
        try:
            from PIL import Image
            img = Image.open(input_path).convert("RGBA")
            img.save(output_path, "PNG")
            return True
        except Exception:
            return False


# ════════════════════════════════════════════════════════════════════════════════
# YOUTUBE CHAPTER TIMESTAMPS & TRACKLIST .TXT EXPORTER
# ════════════════════════════════════════════════════════════════════════════════

def export_timestamp_metadata(
    output_txt_path: str,
    schedule: List[Dict[str, Any]],
    album_title: str = "Worship Music Album",
    genre_prompt: str = ""
) -> str:
    """
    Generates and saves a clean, YouTube-ready timestamp & tracklist sequence .txt file.
    Exact user format:
    🎵 TRACK LIST / TIMESTAMPS

    00:00 - Song Title 1
    05:28 - Song Title 2
    """
    if not schedule:
        return ""

    import re
    total_dur = schedule[-1]["end_time"] if schedule else 0.0
    tot_h = int(total_dur // 3600)
    tot_m = int((total_dur % 3600) // 60)
    tot_s = int(total_dur % 60)
    tot_str = f"{tot_h:02d}:{tot_m:02d}:{tot_s:02d}" if tot_h > 0 else f"{tot_m:02d}:{tot_s:02d}"

    lines = []
    lines.append("🎵 TRACK LIST / TIMESTAMPS")
    lines.append("")

    for item in schedule:
        st = item["start_time"]
        h = int(st // 3600)
        m = int((st % 3600) // 60)
        s = int(st % 60)
        time_tag = f"{h:02d}:{m:02d}:{s:02d}" if tot_h > 0 else f"{m:02d}:{s:02d}"

        raw_title = str(item.get("title", "")).strip()
        # Clean title if it has "Song 1 - Actual Title" or "Track 01: Actual Title"
        m_title = re.match(r'^(?:Song|Track)\s*\d+\s*[-:]\s*(.+)$', raw_title, re.IGNORECASE)
        clean_title = m_title.group(1).strip() if m_title else raw_title

        lines.append(f"{time_tag} - {clean_title}")

    lines.append("")
    lines.append("=" * 60)
    lines.append("ALBUM DETAILS & SUMMARY")
    lines.append("=" * 60)
    lines.append(f"Album Title   : {album_title}")
    lines.append(f"Total Tracks  : {len(schedule)}")
    lines.append(f"Total Runtime : {tot_str} ({int(total_dur)} seconds)")
    lines.append(f"Export Date   : {time.strftime('%Y-%m-%d %H:%M:%S')}")
    if genre_prompt:
        lines.append(f"Music Style   : {genre_prompt}")
    lines.append("=" * 60)
    lines.append("")
    lines.append("📋 DETAILED SONG SEQUENCE & DURATION BREAKDOWN:")
    lines.append("-" * 60)

    for i, item in enumerate(schedule, 1):
        st = item["start_time"]
        et = item["end_time"]
        dur = item["duration"]
        st_h = int(st // 3600)
        st_m = int((st % 3600) // 60)
        st_s = int(st % 60)
        et_h = int(et // 3600)
        et_m = int((et % 3600) // 60)
        et_s = int(et % 60)
        st_str = f"{st_h:02d}:{st_m:02d}:{st_s:02d}" if tot_h > 0 else f"{st_m:02d}:{st_s:02d}"
        et_str = f"{et_h:02d}:{et_m:02d}:{et_s:02d}" if tot_h > 0 else f"{et_m:02d}:{et_s:02d}"
        dur_str = f"{int(dur//60)}:{int(dur%60):02d}"

        raw_title = str(item.get("title", "")).strip()
        m_title = re.match(r'^(?:Song|Track)\s*\d+\s*[-:]\s*(.+)$', raw_title, re.IGNORECASE)
        clean_title = m_title.group(1).strip() if m_title else raw_title

        lines.append(f"Track {i:02d}: {clean_title}")
        lines.append(f"   • Timestamp Range : {st_str} - {et_str}")
        lines.append(f"   • Track Duration  : {dur_str} ({dur:.1f}s)")

    lines.append("")
    lines.append("=" * 60)
    lines.append("Generated automatically by Suno Music Tool — Bulk Video Studio")
    lines.append("=" * 60)

    content = "\n".join(lines)

    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_txt_path)), exist_ok=True)
        with open(output_txt_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as ex:
        _safe_print(f"[TIMESTAMP EXPORT ERROR] {ex}")

    return content


# ════════════════════════════════════════════════════════════════════════════════
# FULL-COLOR EMOJI BANNER OVERLAY GENERATOR (COLR/CPAL)
# ════════════════════════════════════════════════════════════════════════════════

def generate_color_banner_overlay(
    top_text: str,
    bottom_text: str,
    scale_factor: float = 1.0,
    output_png: str = "temp_render/color_banner.png"
) -> Optional[str]:
    """
    Renders high-resolution, full-color emoji transparent banner overlay (COLR/CPAL).
    Preserves vibrant emoji colors (rainbows, yellow thumbs up, red hearts, etc.).
    """
    top_t = top_text.strip()
    bot_t = bottom_text.strip()
    if not top_t and not bot_t:
        return None

    try:
        from PIL import Image, ImageDraw, ImageFont

        top_font_sz = max(14, int(22 * scale_factor))
        bot_font_sz = max(18, int(28 * scale_factor))

        emoji_p = "C:/Windows/Fonts/seguiemj.ttf"
        if os.path.exists(emoji_p):
            font_top = ImageFont.truetype(emoji_p, top_font_sz)
            font_bot = ImageFont.truetype(emoji_p, bot_font_sz)
        else:
            font_top = ImageFont.load_default()
            font_bot = ImageFont.load_default()

        dummy = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        d = ImageDraw.Draw(dummy)

        bb_top = d.textbbox((0, 0), top_t, font=font_top, embedded_color=True) if top_t else (0, 0, 0, 0)
        bb_bot = d.textbbox((0, 0), bot_t, font=font_bot, embedded_color=True) if bot_t else (0, 0, 0, 0)

        w_top = bb_top[2] - bb_top[0]
        w_bot = bb_bot[2] - bb_bot[0]

        content_w = max(w_top, w_bot, int(300 * scale_factor))
        pad_x = int(40 * scale_factor)
        banner_w = content_w + pad_x * 2
        banner_w = banner_w if banner_w % 2 == 0 else banner_w + 1

        banner_h = int(105 * scale_factor)
        banner_h = banner_h if banner_h % 2 == 0 else banner_h + 1

        img = Image.new("RGBA", (banner_w, banner_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Rounded sleek glassmorphic container
        draw.rounded_rectangle(
            [0, 0, banner_w, banner_h],
            radius=int(14 * scale_factor),
            fill=(18, 23, 35, 230),
            outline=(217, 249, 157, 220),
            width=max(1, int(2 * scale_factor))
        )

        mid_x = banner_w // 2
        if top_t and bot_t:
            draw.text((mid_x, int(28 * scale_factor)), top_t, fill=(217, 249, 157, 255), font=font_top, anchor="mm", embedded_color=True)
            draw.text((mid_x, int(72 * scale_factor)), bot_t, fill=(255, 255, 255, 255), font=font_bot, anchor="mm", embedded_color=True)
        elif top_t:
            draw.text((mid_x, banner_h // 2), top_t, fill=(217, 249, 157, 255), font=font_top, anchor="mm", embedded_color=True)
        elif bot_t:
            draw.text((mid_x, banner_h // 2), bot_t, fill=(255, 255, 255, 255), font=font_bot, anchor="mm", embedded_color=True)

        os.makedirs(os.path.dirname(os.path.abspath(output_png)), exist_ok=True)
        img.save(output_png, "PNG")
        return output_png
    except Exception as ex:
        _safe_print(f"[COLOR BANNER ERROR] {ex}")
        return None


# ════════════════════════════════════════════════════════════════════════════════
# FONT & COLOR RESOLUTION UTILITIES
# ════════════════════════════════════════════════════════════════════════════════

FONT_FILE_MAP = {
    "Segoe UI": {
        "regular": "C:/Windows/Fonts/segoeui.ttf",
        "bold": "C:/Windows/Fonts/segoeuib.ttf",
        "italic": "C:/Windows/Fonts/segoeuii.ttf",
        "bold_italic": "C:/Windows/Fonts/segoeuiz.ttf",
    },
    "Arial": {
        "regular": "C:/Windows/Fonts/arial.ttf",
        "bold": "C:/Windows/Fonts/arialbd.ttf",
        "italic": "C:/Windows/Fonts/ariali.ttf",
        "bold_italic": "C:/Windows/Fonts/arialbi.ttf",
    },
    "Georgia": {
        "regular": "C:/Windows/Fonts/georgia.ttf",
        "bold": "C:/Windows/Fonts/georgiab.ttf",
        "italic": "C:/Windows/Fonts/georgiai.ttf",
        "bold_italic": "C:/Windows/Fonts/georgiaz.ttf",
    },
    "Impact": {
        "regular": "C:/Windows/Fonts/impact.ttf",
        "bold": "C:/Windows/Fonts/impact.ttf",
        "italic": "C:/Windows/Fonts/impact.ttf",
        "bold_italic": "C:/Windows/Fonts/impact.ttf",
    },
    "Trebuchet MS": {
        "regular": "C:/Windows/Fonts/trebuc.ttf",
        "bold": "C:/Windows/Fonts/trebucbd.ttf",
        "italic": "C:/Windows/Fonts/trebucit.ttf",
        "bold_italic": "C:/Windows/Fonts/trebucbi.ttf",
    },
    "Verdana": {
        "regular": "C:/Windows/Fonts/verdana.ttf",
        "bold": "C:/Windows/Fonts/verdanab.ttf",
        "italic": "C:/Windows/Fonts/verdanai.ttf",
        "bold_italic": "C:/Windows/Fonts/verdanaz.ttf",
    },
    "Consolas": {
        "regular": "C:/Windows/Fonts/consola.ttf",
        "bold": "C:/Windows/Fonts/consolab.ttf",
        "italic": "C:/Windows/Fonts/consolai.ttf",
        "bold_italic": "C:/Windows/Fonts/consolaz.ttf",
    },
    "Times New Roman": {
        "regular": "C:/Windows/Fonts/times.ttf",
        "bold": "C:/Windows/Fonts/timesbd.ttf",
        "italic": "C:/Windows/Fonts/timesi.ttf",
        "bold_italic": "C:/Windows/Fonts/timesbi.ttf",
    },
    "Calibri": {
        "regular": "C:/Windows/Fonts/calibri.ttf",
        "bold": "C:/Windows/Fonts/calibrib.ttf",
        "italic": "C:/Windows/Fonts/calibrii.ttf",
        "bold_italic": "C:/Windows/Fonts/calibriz.ttf",
    },
    "Tahoma": {
        "regular": "C:/Windows/Fonts/tahoma.ttf",
        "bold": "C:/Windows/Fonts/tahomabd.ttf",
        "italic": "C:/Windows/Fonts/tahoma.ttf",
        "bold_italic": "C:/Windows/Fonts/tahomabd.ttf",
    },
}

def resolve_font_file(family: str = "Segoe UI", bold: bool = False, italic: bool = False) -> Tuple[str, str]:
    """
    Returns (pil_font_path, ffmpeg_font_spec).
    e.g. ('C:/Windows/Fonts/segoeuib.ttf', 'fontfile=/Windows/Fonts/segoeuib.ttf')
    """
    # Check if family is an uploaded or direct custom font file path (.ttf or .otf)
    if family and (str(family).lower().endswith(".ttf") or str(family).lower().endswith(".otf") or os.path.isfile(str(family))):
        target_path = str(family)
        clean_p = str(Path(target_path).resolve()).replace("\\", "/")
        escaped = clean_p.replace(":", "\\\\:")
        ffmpeg_spec = f"fontfile={escaped}"
        return target_path, ffmpeg_spec

    f_entry = FONT_FILE_MAP.get(family, FONT_FILE_MAP.get("Segoe UI", {}))
    
    if bold and italic:
        target_path = f_entry.get("bold_italic") or f_entry.get("bold") or f_entry.get("regular")
    elif bold:
        target_path = f_entry.get("bold") or f_entry.get("regular")
    elif italic:
        target_path = f_entry.get("italic") or f_entry.get("regular")
    else:
        target_path = f_entry.get("regular")
        
    if not target_path or not os.path.exists(target_path):
        target_path = "C:/Windows/Fonts/segoeui.ttf"
        if not os.path.exists(target_path):
            target_path = "C:/Windows/Fonts/arial.ttf"

    clean_p = str(Path(target_path).resolve()).replace("\\", "/")
    if clean_p.lower().startswith("c:"):
        ffmpeg_spec = f"fontfile=/Windows/Fonts/{Path(target_path).name}"
    else:
        escaped = clean_p.replace(":", "\\\\:")
        ffmpeg_spec = f"fontfile={escaped}"

    return target_path, ffmpeg_spec


def color_to_ffmpeg(hex_color: str, alpha: float = 1.0) -> str:
    """Converts hex color '#EAB308' or '0xeab308' to FFmpeg color string '0xeab308@1.0'."""
    clean = hex_color.replace("#", "").replace("0x", "").lower()
    if len(clean) == 3:
        clean = "".join([c*2 for c in clean])
    if len(clean) < 6:
        clean = "ffffff"
    return f"0x{clean[:6]}@{alpha:.2f}"


def ffmpeg_escape_text(text: str) -> str:
    """Escapes special characters (: ' \\ % [ ]) for FFmpeg drawtext filter string."""
    if not text:
        return ""
    clean = text.replace("•", "-").replace("♫", "").replace("✝", "+").replace("▶", ">")
    clean = clean.replace("[", "\\[").replace("]", "\\]")
    clean = clean.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:").replace("%", "%%")
    return clean


def get_audio_duration(audio_path: str) -> float:
    """Get duration of audio file in seconds using ffprobe."""
    try:
        cmd = [
            FFPROBE_BIN, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(result.stdout.strip())
    except Exception as e:
        _safe_print(f"[FFPROBE ERROR] {e}")
        return 180.0


def calculate_album_schedule(audio_files: List[str], song_titles: List[str]) -> List[Dict[str, Any]]:
    """Calculates start_time, end_time, duration for each song in the album queue."""
    schedule = []
    current_time = 0.0

    for i, file_path in enumerate(audio_files):
        dur = get_audio_duration(file_path)
        title = song_titles[i] if i < len(song_titles) else f"Song {i+1}"
        schedule.append({
            "index": i,
            "title": title,
            "file_path": file_path,
            "start_time": current_time,
            "end_time": current_time + dur,
            "duration": dur
        })
        current_time += dur

    return schedule


# ════════════════════════════════════════════════════════════════════════════════
# MASTER MULTI-RESOLUTION VIDEO RENDER ENGINE (720p, 1080p, 2K, 4K)
# ════════════════════════════════════════════════════════════════════════════════

def render_dual_variant_video(
    audio_files: List[str],
    song_titles: List[str],
    output_mp4_path: str,
    # Media Mode & Assets
    mode: str = "image_to_music",  # "image_to_music" or "video_to_music"
    bg_image_path: Optional[str] = None,
    bg_video_path: Optional[str] = None,
    fg_image_path: Optional[str] = None,
    fg_pos: Optional[Tuple[int, int]] = None,
    fg_scale: float = 1.0,
    logo_path: Optional[str] = None,
    logo_scale: float = 1.0,
    output_txt_path: Optional[str] = None,
    album_title: str = "Worship Music Album",
    genre_prompt: str = "",
    # Resolution & Output Quality Controls
    resolution: str = "1080p Full HD (1920x1080)",  # 720p, 1080p, 2K, 4K
    quality_preset: str = "Balanced (Recommended)",  # Fast, Balanced, Ultra, Maximum
    audio_bitrate: str = "192k",                     # 128k, 192k, 320k
    fps: int = 30,                                   # 24, 30, 60
    gpu_mode: str = "auto",                          # auto, nvenc, qsv, amf, cpu
    # Background Motion Video Effects (Image mode)
    bg_effect: str = "Cinematic Slow Zoom (Ken Burns)",
    # Visualizer Options
    visualizer_style: str = "Neon Spectrum Bars",
    visualizer_color: str = "#BEF264",
    # Player Style Options
    player_style: str = "Style 1: Centered Worship (Default)",
    # Typography & Color Options
    font_family: str = "Segoe UI",
    font_size: int = 42,
    font_bold: bool = True,
    font_italic: bool = False,
    title_color: str = "#FFFFFF",
    subtitle_color: str = "#94A3B8",
    accent_color: str = "#EAB308",
    text_shadow: bool = True,
    # CTA Floating Banner Options
    show_banner: bool = True,
    banner_text_top: str = "🌈🙏 Thank you for worshipping with us! 🙏🌈",
    banner_text_bottom: str = "👍✨ Please Like & Subscribe 🔔❤️",
    banner_animate: bool = True,
    banner_anim_mode: str = "drop_and_vanish",
    # Coordinates (defined in 1080p baseline, scaled automatically to target resolution)
    banner_pos: Optional[Tuple[int, int]] = None,
    logo_pos: Optional[Tuple[int, int]] = None,
    text_pos: Optional[Tuple[int, int]] = None,
    viz_pos: Optional[Tuple[int, int]] = None,
    # Callbacks
    log_fn: Optional[Callable[[str], None]] = None,
    progress_fn: Optional[Callable[[float, str], None]] = None
) -> bool:
    """
    Renders a complete MP4 video file at 720p, 1080p, 2K, or 4K with selected quality settings,
    and exports a YouTube chapter timestamp .txt file.
    """
    def _log(msg: str):
        _safe_print(f"[VIDEO ENGINE] {msg}")
        if log_fn:
            try:
                log_fn(msg)
            except Exception:
                pass

    if not audio_files:
        _log("Error: No audio files provided for video render!")
        return False

    # Resolution calculation & scaling factor
    target_w, target_h = parse_resolution(resolution)
    scale_factor = target_w / 1920.0
    crf_val, x264_preset = parse_quality_settings(quality_preset)

    is_video_mode = (mode == "video_to_music") or (bg_video_path and os.path.exists(bg_video_path))

    if is_video_mode:
        if not bg_video_path or not os.path.exists(bg_video_path):
            _log(f"Error: Background video not found: {bg_video_path}")
            return False
    else:
        if not bg_image_path or not os.path.exists(bg_image_path):
            _log(f"Error: Background image not found: {bg_image_path}")
            return False

    os.makedirs(os.path.dirname(os.path.abspath(output_mp4_path)), exist_ok=True)
    temp_dir = Path(output_mp4_path).parent / "temp_render"
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Unique render ID to prevent filename collisions in multi-threaded/concurrent renders
    render_id = f"{int(time.time()*1000)}_{os.getpid()}_{random.randint(1000, 9999)}"

    # Step 1: Create FFmpeg audio concat list file
    concat_list_path = temp_dir / f"concat_{render_id}.txt"
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for audio in audio_files:
            clean_path = str(Path(audio).resolve()).replace("\\", "/")
            f.write(f"file '{clean_path}'\n")

    # Step 2: Concatenate all audio files into a single master audio track
    master_audio_path = temp_dir / f"master_audio_{render_id}.mp3"
    _log("Step 1/3: Concatenating audio tracks...")
    concat_cmd = [
        FFMPEG_BIN, "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list_path),
        "-c", "copy",
        str(master_audio_path)
    ]
    res = subprocess.run(concat_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        _log("Direct audio concat copy failed, attempting robust re-encode concat...")
        reencode_cmd = [
            FFMPEG_BIN, "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list_path),
            "-c:a", "libmp3lame", "-b:a", "192k",
            str(master_audio_path)
        ]
        res2 = subprocess.run(reencode_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res2.returncode != 0:
            _log(f"Concat failed: {res2.stderr or res.stderr}")
            return False

    # Step 3: Calculate timestamps schedule & export .txt file
    schedule = calculate_album_schedule(audio_files, song_titles)
    total_duration = schedule[-1]["end_time"] if schedule else 10.0

    txt_file_path = output_txt_path or str(Path(output_mp4_path).with_suffix(".txt"))
    export_timestamp_metadata(txt_file_path, schedule, album_title=album_title, genre_prompt=genre_prompt)
    _log(f"Step 2/3: Timestamps & tracklist exported to: {Path(txt_file_path).name}")

    # Step 4: Resolve Fonts & Scaled Typography
    _, ffmpeg_font = resolve_font_file(font_family, font_bold, font_italic)
    _, ffmpeg_sub_font = resolve_font_file(font_family, False, False)

    c_title = color_to_ffmpeg(title_color, 1.0)
    c_sub = color_to_ffmpeg(subtitle_color, 0.9)
    c_accent = color_to_ffmpeg(accent_color, 1.0)
    c_viz = color_to_ffmpeg(visualizer_color, 1.0)
    
    sh_px = max(1, int(2 * scale_factor))
    bw_px = max(1, int(1 * scale_factor))
    shadow_filter = f":shadowcolor=0x000000@0.85:shadowx={sh_px}:shadowy={sh_px}:borderw={bw_px}:bordercolor=0x000000@0.7" if text_shadow else ""

    # Scaled Coordinates in Target Resolution
    raw_bx, raw_by = banner_pos if banner_pos else (360, 50)
    raw_lx, raw_ly = logo_pos if logo_pos else (1720, 50)
    raw_tx, raw_ty = text_pos if text_pos else (60, 860)
    raw_vx, raw_vy = viz_pos if viz_pos else (320, 960)

    bx = int(raw_bx * scale_factor)
    by = int(raw_by * scale_factor)
    lx = int(raw_lx * scale_factor)
    ly = int(raw_ly * scale_factor)
    tx = int(raw_tx * scale_factor)
    ty = int(raw_ty * scale_factor)
    vx = int(raw_vx * scale_factor)
    vy = int(raw_vy * scale_factor)

    # Input index tracking for FFmpeg
    input_count = 2
    fg_input_idx = None
    logo_input_idx = None
    banner_input_idx = None
    color_banner_path = None

    if is_video_mode and fg_image_path and os.path.exists(fg_image_path):
        fg_input_idx = input_count
        input_count += 1

    if logo_path and os.path.exists(logo_path):
        logo_input_idx = input_count
        input_count += 1

    if show_banner and (banner_text_top.strip() or banner_text_bottom.strip()):
        banner_temp_png = str(temp_dir / f"color_banner_{render_id}.png")
        color_banner_path = generate_color_banner_overlay(
            top_text=banner_text_top,
            bottom_text=banner_text_bottom,
            scale_factor=scale_factor,
            output_png=banner_temp_png
        )
        if color_banner_path and os.path.exists(color_banner_path):
            banner_input_idx = input_count
            input_count += 1

    filters = []

    # ────────────────────────────────────────────────────────────────
    # A. Background Layer (Multi-Resolution Scaled)
    # ────────────────────────────────────────────────────────────────
    overscan_w = int(target_w * 1.15)
    overscan_h = int(target_h * 1.15)
    # Ensure even dimensions for H264
    overscan_w = overscan_w if overscan_w % 2 == 0 else overscan_w + 1
    overscan_h = overscan_h if overscan_h % 2 == 0 else overscan_h + 1

    pan_x = int(80 * scale_factor)
    pan_y = int(35 * scale_factor)

    if is_video_mode:
        filters.append(f"[0:v]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,crop={target_w}:{target_h}[scaled_bg]")
        last_v = "scaled_bg"

        if fg_input_idx is not None:
            fg_mult = max(0.2, min(3.5, fg_scale))
            scaled_fg_h = int(target_h * 0.67 * fg_mult)
            scaled_fg_h = scaled_fg_h if scaled_fg_h % 2 == 0 else scaled_fg_h + 1
            filters.append(f"[{fg_input_idx}:v]scale=-2:{scaled_fg_h}[scaled_fg]")

            if fg_pos:
                fg_x = int(fg_pos[0] * scale_factor)
                fg_y = int(fg_pos[1] * scale_factor)
                filters.append(f"[{last_v}][scaled_fg]overlay=x={fg_x}:y={fg_y}:eof_action=repeat[v_fg]")
            else:
                filters.append(f"[{last_v}][scaled_fg]overlay=x=(W-w)/2:y=H-h:eof_action=repeat[v_fg]")
            last_v = "v_fg"
    else:
        bg_eff_lower = bg_effect.lower()
        if "ken burns" in bg_eff_lower or "slow zoom" in bg_eff_lower:
            filters.append(
                f"[0:v]scale={overscan_w}:{overscan_h},"
                f"crop={target_w}:{target_h}:(in_w-out_w)/2+sin(t*0.25)*{pan_x}:(in_h-out_h)/2+cos(t*0.18)*{pan_y}[scaled_bg]"
            )
        elif "bass pulse" in bg_eff_lower or "pulse & zoom" in bg_eff_lower:
            pulse_w = int(target_w * 1.09)
            pulse_h = int(target_h * 1.09)
            pulse_w = pulse_w if pulse_w % 2 == 0 else pulse_w + 1
            pulse_h = pulse_h if pulse_h % 2 == 0 else pulse_h + 1
            filters.append(
                f"[0:v]scale={pulse_w}:{pulse_h},"
                f"crop={target_w}:{target_h}:(in_w-out_w)/2+sin(t*3.0)*{int(15*scale_factor)}:(in_h-out_h)/2+cos(t*3.0)*{int(10*scale_factor)},"
                f"eq=brightness='0.02*sin(t*2.5)':contrast='1.0+0.04*sin(t*2.5)'[scaled_bg]"
            )
        elif "light leaks" in bg_eff_lower or "dust" in bg_eff_lower:
            pulse_w = int(target_w * 1.09)
            pulse_h = int(target_h * 1.09)
            pulse_w = pulse_w if pulse_w % 2 == 0 else pulse_w + 1
            pulse_h = pulse_h if pulse_h % 2 == 0 else pulse_h + 1
            filters.append(
                f"[0:v]scale={pulse_w}:{pulse_h},"
                f"crop={target_w}:{target_h}:(in_w-out_w)/2+sin(t*0.2)*{int(40*scale_factor)}:(in_h-out_h)/2+cos(t*0.15)*{int(20*scale_factor)},"
                f"vignette=PI/4+0.05*sin(t*0.8),eq=gamma_r='1.0+0.05*sin(t*0.5)':gamma_b='1.0-0.03*sin(t*0.5)'[scaled_bg]"
            )
        elif "ambient breathing" in bg_eff_lower or "glow" in bg_eff_lower:
            pulse_w = int(target_w * 1.06)
            pulse_h = int(target_h * 1.06)
            pulse_w = pulse_w if pulse_w % 2 == 0 else pulse_w + 1
            pulse_h = pulse_h if pulse_h % 2 == 0 else pulse_h + 1
            filters.append(
                f"[0:v]scale={pulse_w}:{pulse_h},"
                f"crop={target_w}:{target_h}:(in_w-out_w)/2+sin(t*0.15)*{int(25*scale_factor)}:(in_h-out_h)/2+cos(t*0.15)*{int(15*scale_factor)},"
                f"eq=brightness='0.03*sin(t*0.8)':saturation='1.0+0.1*sin(t*0.8)'[scaled_bg]"
            )
        elif "panoramic drift" in bg_eff_lower or "pan" in bg_eff_lower:
            drift_w = int(target_w * 1.2)
            drift_w = drift_w if drift_w % 2 == 0 else drift_w + 1
            filters.append(
                f"[0:v]scale={drift_w}:{target_h},"
                f"crop={target_w}:{target_h}:(in_w-out_w)/2+sin(t*0.15)*{int(180*scale_factor)}:(in_h-out_h)/2[scaled_bg]"
            )
        elif "celestial rise" in bg_eff_lower or "rise" in bg_eff_lower:
            drift_h = int(target_h * 1.2)
            drift_h = drift_h if drift_h % 2 == 0 else drift_h + 1
            filters.append(
                f"[0:v]scale={target_w}:{drift_h},"
                f"crop={target_w}:{target_h}:(in_w-out_w)/2:(in_h-out_h)/2+sin(t*0.2)*{int(90*scale_factor)}[scaled_bg]"
            )
        else:
            filters.append(f"[0:v]scale={target_w}:{target_h}[scaled_bg]")

        last_v = "scaled_bg"

    # ────────────────────────────────────────────────────────────────
    # B. Audio Visualizer Layer (Scaled to Resolution)
    # ────────────────────────────────────────────────────────────────
    viz_lower = visualizer_style.lower()
    clean_viz_hex = visualizer_color.replace("#", "").replace("0x", "")
    if len(clean_viz_hex) < 6:
        clean_viz_hex = "bef264"
    viz_c1 = f"0x{clean_viz_hex}"
    viz_c2 = f"0x{clean_viz_hex[:4]}ff"

    vw = int(1280 * scale_factor)
    vh = int(120 * scale_factor)
    vw = vw if vw % 2 == 0 else vw + 1
    vh = vh if vh % 2 == 0 else vh + 1

    if "none" in viz_lower or "off" in viz_lower or "disable" in viz_lower:
        # No visualizer rendered
        pass
    elif "neon spectrum" in viz_lower or "bar" in viz_lower:
        filters.append(
            f"[1:a]showfreqs=s={vw}x{vh}:mode=bar:ascale=log:fscale=log:win_size=4096:win_func=hanning:colors={viz_c1}|{viz_c2},"
            f"format=yuva420p,colorkey=0x000000:0.25:0.15[viz]"
        )
        filters.append(f"[{last_v}][viz]overlay=x={vx}:y={vy}:eof_action=repeat[v_viz]")
        last_v = "v_viz"
    elif "glowing waveform" in viz_lower or "wave" in viz_lower:
        filters.append(
            f"[1:a]showwaves=s={vw}x{int(100*scale_factor)}:mode=line:scale=sqrt:draw=scale:colors={viz_c1}|{viz_c2},"
            f"format=yuva420p,colorkey=0x000000:0.25:0.15[viz]"
        )
        filters.append(f"[{last_v}][viz]overlay=x={vx}:y={vy}:eof_action=repeat[v_viz]")
        last_v = "v_viz"
    elif "mirrored" in viz_lower or "dual" in viz_lower:
        filters.append(
            f"[1:a]showwaves=s={vw}x{int(120*scale_factor)}:mode=p2p:scale=cbrt:draw=full:colors={viz_c1}|{viz_c2},"
            f"format=yuva420p,colorkey=0x000000:0.25:0.15[viz]"
        )
        filters.append(f"[{last_v}][viz]overlay=x={vx}:y={vy}:eof_action=repeat[v_viz]")
        last_v = "v_viz"
    elif "circular" in viz_lower or "radial" in viz_lower or "pulse" in viz_lower:
        circ_sz = int(280 * scale_factor)
        circ_sz = circ_sz if circ_sz % 2 == 0 else circ_sz + 1
        filters.append(
            f"[1:a]avectorscope=s={circ_sz}x{circ_sz}:m=lissajous:rc=234:gc=179:bc=8:zoom=1.3,"
            f"format=yuva420p,colorkey=0x000000:0.25:0.15[viz]"
        )
        calc_cx = vx if viz_pos else int((target_w - circ_sz) / 2)
        calc_cy = vy if viz_pos else int(target_h - circ_sz - int(40 * scale_factor))
        filters.append(f"[{last_v}][viz]overlay=x={calc_cx}:y={calc_cy}:eof_action=repeat[v_viz]")
        last_v = "v_viz"
    elif "showcqt" in viz_lower or "musical" in viz_lower:
        filters.append(
            f"[1:a]showcqt=s={vw}x{int(100*scale_factor)}:count=1:fcount=1:gamma=2,"
            f"format=yuva420p,colorkey=0x000000:0.25:0.15[viz]"
        )
        filters.append(f"[{last_v}][viz]overlay=x={vx}:y={vy}:eof_action=repeat[v_viz]")
        last_v = "v_viz"
    elif "led" in viz_lower or "peak meter" in viz_lower:
        led_w = int(800 * scale_factor)
        led_h = int(60 * scale_factor)
        filters.append(
            f"[1:a]showfreqs=s={led_w}x{led_h}:mode=dot:ascale=sqrt:fscale=log:win_size=4096:win_func=hanning:colors={viz_c1}|0xeab308|0xf87171,"
            f"format=yuva420p,colorkey=0x000000:0.25:0.15[viz]"
        )
        filters.append(f"[{last_v}][viz]overlay=x={vx+int(240*scale_factor)}:y={vy+int(40*scale_factor)}:eof_action=repeat[v_viz]")
        last_v = "v_viz"


    # ────────────────────────────────────────────────────────────────
    # C. Player Overlay Styles (Scaled to Target Resolution) — Border-Free & Circular Vinyl
    # ────────────────────────────────────────────────────────────────
    p_style = player_style.lower()
    f_size = max(18, int(font_size * scale_factor))
    sub_size = max(13, int(f_size * 0.54))
    disc_sz = max(60, int(150 * scale_factor))
    disc_sz = disc_sz if disc_sz % 2 == 0 else disc_sz + 1

    # If spinning circular vinyl style is selected and logo exists, add spinning disc stream
    has_spinning_disc = ("circular" in p_style or "spinning" in p_style or "vinyl" in p_style or "disc" in p_style)
    if has_spinning_disc and logo_input_idx is not None:
        disc_x = tx
        disc_y = ty - int(10 * scale_factor)
        text_x = disc_x + disc_sz + int(24 * scale_factor)
        prog_w = int(520 * scale_factor)
        filters.append(
            f"[{logo_input_idx}:v]format=yuva420p,scale={disc_sz}:{disc_sz},"
            f"rotate=2*PI*t/12:c=none:ow='hypot(iw,ih)':oh='hypot(iw,ih)'[spinning_disc]"
        )
        filters.append(
            f"[{last_v}][spinning_disc]overlay=x={disc_x}:y={disc_y}:eof_action=repeat[v_disc_bg]"
        )
        last_v = "v_disc_bg"
    else:
        disc_x = tx
        disc_y = ty
        text_x = tx
        prog_w = int(600 * scale_factor)

    for i, s in enumerate(schedule):
        st = s["start_time"]
        et = s["end_time"]
        dur = max(1.0, s["duration"])
        mm = int(dur // 60)
        ss = int(dur % 60)
        time_str = ffmpeg_escape_text(f"{mm}:{ss:02d}")

        raw_title = s["title"] or f"Song {i+1}"
        raw_next = schedule[i+1]["title"] if i + 1 < len(schedule) else "End of Album"
        clean_title = ffmpeg_escape_text(raw_title)
        next_title = ffmpeg_escape_text(raw_next)

        if has_spinning_disc:
            # STYLE 0: Circular Spinning Vinyl Disc (Rotating Channel Logo) — 100% Border-Free
            # Track Title (Border-free)
            filters.append(
                f"[{last_v}]drawtext="
                f"{ffmpeg_font}:text='{clean_title}':"
                f"fontsize={f_size}:fontcolor={c_title}:x={text_x}:y={ty}{shadow_filter}:"
                f"enable='between(t,{st},{et})'[v_p0_t_{i}]"
            )
            last_v = f"v_p0_t_{i}"

            # Sleek progress line background
            prog_y = ty + f_size + int(10 * scale_factor)
            filters.append(
                f"[{last_v}]drawbox="
                f"x={text_x}:y={prog_y}:w={prog_w}:h={max(2, int(3*scale_factor))}:color=0x475569@0.7:t=fill:"
                f"enable='between(t,{st},{et})'[v_p0_bg_{i}]"
            )
            last_v = f"v_p0_bg_{i}"

            # Animated progress fill line
            filters.append(
                f"[{last_v}]drawbox="
                f"x={text_x}:y={prog_y}:w='min({prog_w}, {prog_w}*(t-{st})/({dur}))':h={max(2, int(3*scale_factor))}:color={c_accent}:t=fill:"
                f"enable='between(t,{st},{et})'[v_p0_fg_{i}]"
            )
            last_v = f"v_p0_fg_{i}"

            # Subtitle / Next Track + Time
            filters.append(
                f"[{last_v}]drawtext="
                f"{ffmpeg_sub_font}:text='{time_str}  -  UP NEXT - {next_title}':"
                f"fontsize={sub_size}:fontcolor={c_sub}:x={text_x}:y={prog_y + int(14*scale_factor)}{shadow_filter}:"
                f"enable='between(t,{st},{et})'[v_p0_sub_{i}]"
            )
            last_v = f"v_p0_sub_{i}"

        elif "style 2" in p_style or "glassmorphic" in p_style or "minimal" in p_style:
            # STYLE 2: Border-Free Glass Minimal (Centered)
            p2_bar_w = int(680 * scale_factor)
            p2_bar_x = int((target_w - p2_bar_w) / 2)
            filters.append(
                f"[{last_v}]drawtext="
                f"{ffmpeg_font}:text='{clean_title}':"
                f"fontsize={f_size}:fontcolor={c_title}:x=(W-tw)/2:y={ty}{shadow_filter}:"
                f"enable='between(t,{st},{et})'[v_p2_t_{i}]"
            )
            last_v = f"v_p2_t_{i}"
            p2_bar_y = ty + f_size + int(10 * scale_factor)
            filters.append(
                f"[{last_v}]drawbox="
                f"x={p2_bar_x}:y={p2_bar_y}:w='min({p2_bar_w}, {p2_bar_w}*(t-{st})/({dur}))':h={max(2, int(3*scale_factor))}:color={c_accent}:t=fill:"
                f"enable='between(t,{st},{et})'[v_p2_b_{i}]"
            )
            last_v = f"v_p2_b_{i}"
            filters.append(
                f"[{last_v}]drawtext="
                f"{ffmpeg_sub_font}:text='UP NEXT - {next_title}  ({time_str})':"
                f"fontsize={sub_size}:fontcolor={c_sub}:x=(W-tw)/2:y={p2_bar_y + int(16*scale_factor)}{shadow_filter}:"
                f"enable='between(t,{st},{et})'[v_p2_sub_{i}]"
            )
            last_v = f"v_p2_sub_{i}"

        elif "style 3" in p_style or "bottom left" in p_style:
            # STYLE 3: Studio Bottom Left Clean (Border-Free)
            filters.append(
                f"[{last_v}]drawtext="
                f"{ffmpeg_font}:text='NOW PLAYING - {clean_title}':"
                f"fontsize={f_size}:fontcolor={c_title}:x={tx}:y={ty}{shadow_filter}:"
                f"enable='between(t,{st},{et})'[v_p3_t_{i}]"
            )
            last_v = f"v_p3_t_{i}"
            p3_bar_w = int(500 * scale_factor)
            p3_bar_y = ty + f_size + int(8 * scale_factor)
            filters.append(
                f"[{last_v}]drawbox="
                f"x={tx}:y={p3_bar_y}:w='min({p3_bar_w}, {p3_bar_w}*(t-{st})/({dur}))':h={max(2, int(3*scale_factor))}:color={c_accent}:t=fill:"
                f"enable='between(t,{st},{et})'[v_p3_b_{i}]"
            )
            last_v = f"v_p3_b_{i}"
            filters.append(
                f"[{last_v}]drawtext="
                f"{ffmpeg_sub_font}:text='UP NEXT - {next_title}  |  {time_str}':"
                f"fontsize={sub_size}:fontcolor={c_sub}:x={tx}:y={p3_bar_y + int(14*scale_factor)}{shadow_filter}:"
                f"enable='between(t,{st},{et})'[v_p3_nxt_{i}]"
            )
            last_v = f"v_p3_nxt_{i}"

        elif "style 6" in p_style or "floating pill" in p_style:
            # STYLE 6: Floating Pill Modern (Border-Free)
            filters.append(
                f"[{last_v}]drawtext="
                f"{ffmpeg_font}:text='{clean_title}  ({time_str})':"
                f"fontsize={f_size}:fontcolor={c_title}:x=(W-tw)/2:y={ty}{shadow_filter}:"
                f"enable='between(t,{st},{et})'[v_p6_t_{i}]"
            )
            last_v = f"v_p6_t_{i}"
            filters.append(
                f"[{last_v}]drawtext="
                f"{ffmpeg_sub_font}:text='UP NEXT - {next_title}':"
                f"fontsize={sub_size}:fontcolor={c_sub}:x=(W-tw)/2:y={ty+f_size+int(12*scale_factor)}{shadow_filter}:"
                f"enable='between(t,{st},{et})'[v_p6_nxt_{i}]"
            )
            last_v = f"v_p6_nxt_{i}"

        elif "style 9" in p_style or "broadcast" in p_style:
            # STYLE 9: Clean Edge-To-Edge Broadcast Bar
            bar_top_y = int(target_h - 75 * scale_factor)
            filters.append(
                f"[{last_v}]drawbox=x=0:y={bar_top_y}:w={target_w}:h={int(75*scale_factor)}:color=0x0a0d14@0.85:t=fill[v_bbar_{i}]"
            )
            last_v = f"v_bbar_{i}"
            filters.append(
                f"[{last_v}]drawbox=x=0:y={bar_top_y}:w='min({target_w}, {target_w}*(t-{st})/({dur}))':h={max(2, int(3*scale_factor))}:color={c_accent}:t=fill[v_bprog_{i}]"
            )
            last_v = f"v_bprog_{i}"
            filters.append(
                f"[{last_v}]drawtext="
                f"{ffmpeg_font}:text='{clean_title}':"
                f"fontsize={f_size}:fontcolor={c_title}:x={int(30*scale_factor)}:y={bar_top_y + int(22*scale_factor)}{shadow_filter}:"
                f"enable='between(t,{st},{et})'[v_p9_t_{i}]"
            )
            last_v = f"v_p9_t_{i}"
            filters.append(
                f"[{last_v}]drawtext="
                f"{ffmpeg_sub_font}:text='UP NEXT - {next_title}  |  {time_str}':"
                f"fontsize={sub_size}:fontcolor={c_sub}:x=W-tw-{int(30*scale_factor)}:y={bar_top_y + int(24*scale_factor)}{shadow_filter}:"
                f"enable='between(t,{st},{et})'[v_p9_sub_{i}]"
            )
            last_v = f"v_p9_sub_{i}"

        else:
            # Centered Worship Gold Luxe (Border-Free)
            p1_bar_w = int(700 * scale_factor)
            p1_bar_x = int((target_w - p1_bar_w) / 2)
            p1_bar_y = int(ty + f_size + 10 * scale_factor)
            p1_bar_h = max(2, int(3 * scale_factor))

            filters.append(
                f"[{last_v}]drawtext="
                f"{ffmpeg_font}:text='{clean_title}':"
                f"fontsize={f_size}:fontcolor={c_title}:x=(W-tw)/2:y={ty}{shadow_filter}:"
                f"enable='between(t,{st},{et})'[v_p1_t_{i}]"
            )
            last_v = f"v_p1_t_{i}"

            filters.append(
                f"[{last_v}]drawbox="
                f"x={p1_bar_x}:y={p1_bar_y}:w='min({p1_bar_w}, {p1_bar_w}*(t-{st})/({dur}))':h={p1_bar_h}:color={c_accent}:t=fill:"
                f"enable='between(t,{st},{et})'[v_p1_b2_{i}]"
            )
            last_v = f"v_p1_b2_{i}"

            filters.append(
                f"[{last_v}]drawtext="
                f"{ffmpeg_sub_font}:text='{time_str}':"
                f"fontsize={sub_size}:fontcolor={c_title}:x={p1_bar_x + p1_bar_w + int(15*scale_factor)}:y={p1_bar_y - int(6*scale_factor)}{shadow_filter}:"
                f"enable='between(t,{st},{et})'[v_p1_dur_{i}]"
            )
            last_v = f"v_p1_dur_{i}"

            filters.append(
                f"[{last_v}]drawtext="
                f"{ffmpeg_sub_font}:text='UP NEXT - {next_title}':"
                f"fontsize={sub_size}:fontcolor={c_sub}:x=(W-tw)/2:y={p1_bar_y + int(18*scale_factor)}{shadow_filter}:"
                f"enable='between(t,{st},{et})'[v_p1_nxt_{i}]"
            )
            last_v = f"v_p1_nxt_{i}"

    
    # D. Top Floating CTA Banner Overlay (Full-Color Emojis & Drop/Vanish Animation)
    # ────────────────────────────────────────────────────────────────
    if banner_input_idx is not None and color_banner_path:
        anim_m = banner_anim_mode.lower() if banner_animate else "static"

        if "drop" in anim_m or "vanish" in anim_m or "slide" in anim_m:
            # Periodic drop & vanish: Slide down smoothly from top, hold static, slide up to vanish, repeat every 30s
            cycle_sec = 30
            slide_time = 0.8
            hold_time = 7.0
            exit_start = slide_time + hold_time
            exit_end = exit_start + slide_time

            y_banner = (
                f"'if(lt(mod(t, {cycle_sec}), {slide_time}), "
                f"-H + ({by} + H)*(1 - cos(mod(t, {cycle_sec})/{slide_time}*PI))/2, "
                f"if(lte(mod(t, {cycle_sec}), {exit_start}), {by}, "
                f"if(lt(mod(t, {cycle_sec}), {exit_end}), "
                f"{by} - ({by} + H + 30)*(1 - cos((mod(t, {cycle_sec})-{exit_start})/{slide_time}*PI))/2, "
                f"-9999)))'"
            )
            filters.append(f"[{last_v}][{banner_input_idx}:v]overlay=x={bx}:y={y_banner}:eval=frame:eof_action=repeat[v_b2]")
        elif "ambient float" in anim_m or "float" in anim_m:
            y_banner = f"'{by} + {int(20*scale_factor)}*(sin(2*3.14159*t/6.5)+1)/2 + {int(8*scale_factor)}*sin(2*3.14159*t/2.1)'"
            filters.append(f"[{last_v}][{banner_input_idx}:v]overlay=x={bx}:y={y_banner}:eof_action=repeat[v_b2]")
        else:
            y_banner = f"{by}"
            filters.append(f"[{last_v}][{banner_input_idx}:v]overlay=x={bx}:y={y_banner}:eof_action=repeat[v_b2]")

        last_v = "v_b2"

    # ────────────────────────────────────────────────────────────────
    # E. Logo Watermark Overlay (Scaled, Bounded & Crisp Lanczos Filter)
    # ────────────────────────────────────────────────────────────────
    if logo_input_idx is not None and not has_spinning_disc:
        # Base logo width in 1080p is 130px, scaled by user logo_scale and target resolution
        logo_w = max(32, int(130 * max(0.3, min(3.0, logo_scale)) * scale_factor))
        logo_w = logo_w if logo_w % 2 == 0 else logo_w + 1
        filters.append(f"[{logo_input_idx}:v]scale={logo_w}:-2:flags=lanczos[scaled_logo]")

        pad_x = int(24 * scale_factor)
        pad_y = int(24 * scale_factor)
        if logo_pos:
            raw_lx, raw_ly = logo_pos
            calc_lx = int(raw_lx * scale_factor)
            calc_ly = int(raw_ly * scale_factor)
        else:
            calc_lx = target_w - logo_w - pad_x
            calc_ly = pad_y

        lx = max(pad_x, min(target_w - logo_w - pad_x, calc_lx))
        ly = max(pad_y, min(target_h - int(60 * scale_factor), calc_ly))

        filters.append(f"[{last_v}][scaled_logo]overlay=x={lx}:y={ly}:eof_action=repeat[v_out]")
        last_v = "v_out"
    else:
        filters.append(f"[{last_v}]null[v_out]")
        last_v = "v_out"


    filter_complex_str = ";".join(filters)

    # Step 5: Execute final FFmpeg Video Export Command
    _log(f"Step 3/3: Rendering final {target_w}x{target_h} MP4 (CRF {crf_val}, {fps} FPS, {audio_bitrate} audio)...")

    cmd = [FFMPEG_BIN, "-y"]

    if is_video_mode:
        clean_bg_vid = str(Path(bg_video_path).resolve()).replace("\\", "/")
        cmd.extend(["-stream_loop", "-1", "-i", clean_bg_vid])
    else:
        clean_bg_img = str(Path(bg_image_path).resolve()).replace("\\", "/")
        cmd.extend(["-loop", "1", "-i", clean_bg_img])

    cmd.extend(["-i", str(master_audio_path)])

    if fg_input_idx is not None:
        cmd.extend(["-i", str(Path(fg_image_path).resolve()).replace("\\", "/")])

    if logo_input_idx is not None:
        cmd.extend(["-i", str(Path(logo_path).resolve()).replace("\\", "/")])

    if banner_input_idx is not None and color_banner_path:
        cmd.extend(["-i", str(Path(color_banner_path).resolve()).replace("\\", "/")])

    encoder_flags = get_video_encoder_flags(gpu_mode=gpu_mode, crf_val=crf_val, cpu_preset=x264_preset)

    cmd.extend([
        "-filter_complex", filter_complex_str,
        "-map", f"[{last_v}]",
        "-map", "1:a",
        "-r", str(fps),
        *encoder_flags,
        "-c:a", "aac",
        "-b:a", audio_bitrate if "k" in str(audio_bitrate) else f"{audio_bitrate}k",
        "-shortest",
        "-pix_fmt", "yuv420p",
        "-progress", "pipe:1",
        "-nostats",
        output_mp4_path
    ])

    def _execute_ffmpeg(current_cmd: List[str], label: str) -> Tuple[bool, List[str]]:
        tail_lines = []
        last_update_time = 0
        try:
            proc = subprocess.Popen(
                current_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace"
            )

            while True:
                line = proc.stdout.readline()
                if not line:
                    if proc.poll() is not None:
                        break
                    continue
                line_str = line.strip()
                if line_str:
                    tail_lines.append(line_str)
                    if len(tail_lines) > 40:
                        tail_lines.pop(0)

                if line_str.startswith("out_time_ms="):
                    try:
                        val = float(line_str.split("=")[1])
                        cur_sec = val / 1000000.0
                        if total_duration > 0:
                            pct = min(0.99, max(0.0, cur_sec / total_duration))
                            now = time.time()
                            if now - last_update_time >= 0.25:
                                last_update_time = now
                                msg = f"Encoding [{label}]: {cur_sec:.1f}s / {total_duration:.1f}s ({pct*100:.1f}%)"
                                _log(msg)
                                if progress_fn:
                                    try:
                                        progress_fn(pct, msg)
                                    except TypeError:
                                        progress_fn(pct)
                    except Exception:
                        pass

            proc.wait()
            return (proc.returncode == 0), tail_lines
        except Exception as ex:
            _log(f"Exception during FFmpeg execution ({label}): {ex}")
            return False, [str(ex)]

    is_gpu = any("nvenc" in a or "qsv" in a or "amf" in a for a in encoder_flags)
    primary_label = f"{target_w}x{target_h} GPU" if is_gpu else f"{target_w}x{target_h}"

    success, tail_log = _execute_ffmpeg(cmd, primary_label)

    # Automatic CPU Fallback if GPU encoder failed
    if not success and is_gpu:
        err_hint = ""
        for err_candidate in reversed(tail_log):
            if any(k in err_candidate.lower() for k in ["error", "invalid", "failed", "cannot", "unsupported", "out of range", "cuda", "nvenc", "qsv", "amf"]):
                err_hint = err_candidate
                break
        if not err_hint and tail_log:
            err_hint = tail_log[-1]

        _log(f"⚠️ GPU Hardware Encoder failed ({err_hint}).")
        _log("🔄 Automatically falling back to CPU multi-threaded encoder (libx264) for fail-safe render...")

        safe_threads = max(2, min(6, (os.cpu_count() or 4)))
        cpu_flags = ["-c:v", "libx264", "-preset", str(x264_preset or "fast"), "-crf", str(crf_val), "-threads", str(safe_threads)]

        cpu_cmd = []
        i = 0
        while i < len(cmd):
            if cmd[i:i+len(encoder_flags)] == encoder_flags:
                cpu_cmd.extend(cpu_flags)
                i += len(encoder_flags)
            else:
                cpu_cmd.append(cmd[i])
                i += 1

        success, tail_log = _execute_ffmpeg(cpu_cmd, f"{target_w}x{target_h} CPU")

    if success:
        _log(f"Render complete: {output_mp4_path}")
        if progress_fn:
            try:
                progress_fn(1.0, f"Render complete: {Path(output_mp4_path).name}")
            except TypeError:
                progress_fn(1.0)
        return True
    else:
        err_msg = ""
        for err_candidate in reversed(tail_log):
            if any(k in err_candidate.lower() for k in ["error", "invalid", "failed", "cannot", "unsupported", "not found"]):
                err_msg = err_candidate
                break
        if not err_msg and tail_log:
            err_msg = " | ".join(tail_log[-3:])
        _log(f"❌ FFmpeg Render failed: {err_msg}")
        return False
