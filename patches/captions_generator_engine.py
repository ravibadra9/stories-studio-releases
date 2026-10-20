"""
captions_generator_engine.py
══════════════════════════════════════════════════════════════════════════════
Core Engine for Captions Generator:
- Sequential Multi-Clip Merging with Automatic Aspect Ratio & Audio Normalization
- AI Speech Transcription via whisper_engine (faster-whisper) with Word Timestamps
- Rich CapCut Subtitle Presets (Bold Yellow, TikTok Dark Box, Neon Cyan, Pop Bounce, etc.)
- 🎲 "Random Per Scene" Intelligent Mode: Dynamically switches CapCut style on each scene transition!
- Customizable Logo Watermark Placement (Position, Width, Opacity, Margins)
- Hardware Accelerated NVENC / Ultra-fast CPU Rendering
══════════════════════════════════════════════════════════════════════════════
"""

import os
import sys
import re
import json
import time
import shutil
import random
import tempfile
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Tuple

# Force UTF-8 on Windows terminal
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try: sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

def _safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        safe_args = [str(a).encode("ascii", errors="replace").decode("ascii") for a in args]
        print(*safe_args, **kwargs)
    except Exception:
        pass

# Windows CMD popup suppression
STARTUPINFO = None
CREATIONFLAGS = 0
if sys.platform == "win32":
    STARTUPINFO = subprocess.STARTUPINFO()
    STARTUPINFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    STARTUPINFO.wShowWindow = subprocess.SW_HIDE
    CREATIONFLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

def find_binaries() -> Tuple[Optional[str], Optional[str]]:
    """Locate ffmpeg and ffprobe binaries."""
    curr_dir = Path(__file__).resolve().parent
    candidates = [
        curr_dir,
        curr_dir / "bin",
        curr_dir.parent,
        curr_dir.parent / "bin",
    ]
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        meipass = Path(getattr(sys, "_MEIPASS", ""))
        candidates.extend([exe_dir, exe_dir / "bin", meipass, meipass / "bin"])

    ffmpeg_p = None
    ffprobe_p = None

    for c in candidates:
        ff = c / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
        fp = c / ("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
        if not ffmpeg_p and ff.is_file():
            ffmpeg_p = str(ff)
        if not ffprobe_p and fp.is_file():
            ffprobe_p = str(fp)

    if not ffmpeg_p:
        ffmpeg_p = shutil.which("ffmpeg")
    if not ffprobe_p:
        ffprobe_p = shutil.which("ffprobe")

    return ffmpeg_p, ffprobe_p

FFMPEG_PATH, FFPROBE_PATH = find_binaries()

# ══════════════════════════════════════════════════════════════════════════════
# 1. NEXT-LEVEL CAPCUT VIRAL PRESETS & FONTS DEFINITION
# ══════════════════════════════════════════════════════════════════════════════
CAPCUT_PRESETS: Dict[str, Dict[str, Any]] = {
    # ── VIRAL TIKTOK / HORMOZI ESSENTIALS ─────────────────────────────────────
    "CapCut Bold Yellow": {
        "name": "CapCut Bold Yellow",
        "font": "Impact",
        "primary": "#FFFFFF",
        "highlight": "#FFE600",
        "outline": "#000000",
        "outline_w": 10,
        "shadow": 2,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Viral",
        "description": "Viral TikTok/CapCut standard: Electric yellow pop with 10px thick dark stroke."
    },
    "Alex Hormozi Yellow Punch": {
        "name": "Alex Hormozi Yellow Punch",
        "font": "Impact",
        "primary": "#FFFFFF",
        "highlight": "#FFF200",
        "outline": "#000000",
        "outline_w": 11,
        "shadow": 3,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Hormozi",
        "description": "Alex Hormozi signature: Ultra-bold neon yellow keyword punch with 11px black outline."
    },
    "Alex Hormozi Toxic Lime": {
        "name": "Alex Hormozi Toxic Lime",
        "font": "Impact",
        "primary": "#FFFFFF",
        "highlight": "#39FF14",
        "outline": "#000000",
        "outline_w": 11,
        "shadow": 2,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Hormozi",
        "description": "Alex Hormozi high-energy: Radioactive neon lime highlight for viral engagement."
    },
    "Alex Hormozi Crimson Alert": {
        "name": "Alex Hormozi Crimson Alert",
        "font": "Impact",
        "primary": "#FFFFFF",
        "highlight": "#FF2B2B",
        "outline": "#000000",
        "outline_w": 11,
        "shadow": 2,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Hormozi",
        "description": "Alex Hormozi hook alert: Punchy fiery red active words that grab instant attention."
    },
    "MrBeast Sunshine Pop": {
        "name": "MrBeast Sunshine Pop",
        "font": "Arial Black",
        "primary": "#FFFFFF",
        "highlight": "#FFD000",
        "outline": "#111111",
        "outline_w": 10,
        "shadow": 4,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Viral",
        "description": "MrBeast viral Shorts style: Golden yellow keyword with ultra-bold comic stroke."
    },
    "Devin Finance Cash Green": {
        "name": "Devin Finance Cash Green",
        "font": "Impact",
        "primary": "#FFFFFF",
        "highlight": "#00E676",
        "outline": "#052E16",
        "outline_w": 10,
        "shadow": 2,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Hormozi",
        "description": "Finance / crypto / money talks: Bright dollar-bill green active keyword punch."
    },

    # ── HIGH-CONTRAST PILL BOX BACKDROPS ──────────────────────────────────────
    "TikTok Dark Pill Box": {
        "name": "TikTok Dark Pill Box",
        "font": "Montserrat",
        "primary": "#FFFFFF",
        "highlight": "#FFDD00",
        "outline": "#000000",
        "outline_w": 0,
        "shadow": 0,
        "box": True,
        "box_color": "#000000",
        "box_alpha": 35,
        "pop": False,
        "category": "Box",
        "description": "Viral high-contrast black pill box backdrop, razor-sharp legibility on busy video."
    },
    "Explainer Yellow Box (Black Text)": {
        "name": "Explainer Yellow Box (Black Text)",
        "font": "Impact",
        "primary": "#202020",
        "highlight": "#000000",
        "outline": "#000000",
        "outline_w": 0,
        "shadow": 0,
        "box": True,
        "box_color": "#FFDE00",
        "box_alpha": 20,
        "pop": False,
        "category": "Box",
        "description": "Vox / BBC explainer: Bright golden yellow box with bold charcoal black typography."
    },
    "Breaking News Red Box": {
        "name": "Breaking News Red Box",
        "font": "Arial Black",
        "primary": "#FFFFFF",
        "highlight": "#FFF275",
        "outline": "#000000",
        "outline_w": 0,
        "shadow": 0,
        "box": True,
        "box_color": "#DC2626",
        "box_alpha": 20,
        "pop": False,
        "category": "Box",
        "description": "Urgent breaking news red bar backdrop with crisp white and lemon active highlight."
    },
    "Dark Emerald Box": {
        "name": "Dark Emerald Box",
        "font": "Poppins",
        "primary": "#E2E8F0",
        "highlight": "#6EE7B7",
        "outline": "#000000",
        "outline_w": 0,
        "shadow": 0,
        "box": True,
        "box_color": "#064E3B",
        "box_alpha": 30,
        "pop": False,
        "category": "Box",
        "description": "Deep pine forest green pill box with bright luminous mint active text."
    },
    "Midnight Navy Box": {
        "name": "Midnight Navy Box",
        "font": "Montserrat",
        "primary": "#E2E8F0",
        "highlight": "#38BDF8",
        "outline": "#000000",
        "outline_w": 0,
        "shadow": 0,
        "box": True,
        "box_color": "#0F172A",
        "box_alpha": 30,
        "pop": False,
        "category": "Box",
        "description": "Sleek tech midnight navy box backdrop with vivid sky-blue active pop."
    },
    "Clean White Pill Box": {
        "name": "Clean White Pill Box",
        "font": "Arial Black",
        "primary": "#475569",
        "highlight": "#000000",
        "outline": "#000000",
        "outline_w": 0,
        "shadow": 0,
        "box": True,
        "box_color": "#FFFFFF",
        "box_alpha": 25,
        "pop": False,
        "category": "Box",
        "description": "Ultra-clean pure white pill box with charcoal unread and pitch-black active text."
    },

    # ── CYBERPUNK & NEON GLOW ─────────────────────────────────────────────────
    "Neon Cyber Cyan": {
        "name": "Neon Cyber Cyan",
        "font": "Impact",
        "primary": "#FFFFFF",
        "highlight": "#00F0FF",
        "outline": "#002B36",
        "outline_w": 10,
        "shadow": 3,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Neon",
        "description": "Futuristic sci-fi cyber cyan active glow with deep oceanic stroke."
    },
    "Neon Magenta Cyberpunk": {
        "name": "Neon Magenta Cyberpunk",
        "font": "Impact",
        "primary": "#FFFFFF",
        "highlight": "#FF007F",
        "outline": "#380026",
        "outline_w": 10,
        "shadow": 3,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Neon",
        "description": "Electric neon fuchsia with nocturnal synthwave outline for high-energy vibes."
    },
    "Cyber Matrix Terminal": {
        "name": "Cyber Matrix Terminal",
        "font": "Impact",
        "primary": "#86EFAC",
        "highlight": "#00FF66",
        "outline": "#000000",
        "outline_w": 10,
        "shadow": 2,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Neon",
        "description": "Hacker / terminal phosphorescent matrix green with deep pitch black border."
    },
    "Electric Sky Blue": {
        "name": "Electric Sky Blue",
        "font": "Arial Black",
        "primary": "#FFFFFF",
        "highlight": "#38BDF8",
        "outline": "#082F49",
        "outline_w": 9,
        "shadow": 2,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Neon",
        "description": "Vibrant electric sky blue active highlight with rich deep navy stroke."
    },
    "Neon Violet Dream": {
        "name": "Neon Violet Dream",
        "font": "Montserrat",
        "primary": "#FFFFFF",
        "highlight": "#D946EF",
        "outline": "#3B0764",
        "outline_w": 9,
        "shadow": 3,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Neon",
        "description": "Luminous neon violet-purple glow with dark amethyst outline."
    },
    "Ice Cold Arctic Cyan": {
        "name": "Ice Cold Arctic Cyan",
        "font": "Arial Black",
        "primary": "#F0FDF4",
        "highlight": "#7DF9FF",
        "outline": "#082F49",
        "outline_w": 9,
        "shadow": 3,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Neon",
        "description": "Glacial electric cyan with deep polar marine stroke, crisp and icy."
    },
    "Retro 80s Synthwave": {
        "name": "Retro 80s Synthwave",
        "font": "Impact",
        "primary": "#FFFFFF",
        "highlight": "#FF007F",
        "outline": "#003366",
        "outline_w": 10,
        "shadow": 4,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Neon",
        "description": "Outrun synthwave aesthetic: Neon fuchsia highlight with deep cobalt blue border."
    },

    # ── HIGH-ENERGY KARAOKE & FLOW ────────────────────────────────────────────
    "Karaoke Pop Bounce": {
        "name": "Karaoke Pop Bounce",
        "font": "Arial Black",
        "primary": "#FFFFFF",
        "highlight": "#00FF7F",
        "outline": "#003314",
        "outline_w": 9,
        "shadow": 3,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Karaoke",
        "description": "Spring green energetic word-by-word flow with deep evergreen outline."
    },
    "Rhymes Liquid Sky": {
        "name": "Rhymes Liquid Sky",
        "font": "Comic Sans MS",
        "primary": "#FFEFD6",
        "highlight": "#00D1FF",
        "outline": "#7A2CFF",
        "outline_w": 9,
        "shadow": 3,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Karaoke",
        "description": "Bright cyan active highlight with rich purple outlines for music/poetry."
    },

    # ── FIRE, SUN & AMBER PUNCH ───────────────────────────────────────────────
    "Sunny Orange Blaze": {
        "name": "Sunny Orange Blaze",
        "font": "Impact",
        "primary": "#FFFFFF",
        "highlight": "#FF7A00",
        "outline": "#2E0F00",
        "outline_w": 9,
        "shadow": 2,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Viral",
        "description": "Fiery warm flame orange punch with dark chocolate espresso outline."
    },
    "Golden Amber Flame": {
        "name": "Golden Amber Flame",
        "font": "Impact",
        "primary": "#FFFFFF",
        "highlight": "#F59E0B",
        "outline": "#451A03",
        "outline_w": 9,
        "shadow": 3,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Viral",
        "description": "Rich honey amber glow with warm mocha stroke, perfect for storytelling."
    },
    "Glow Peach Sorbet": {
        "name": "Glow Peach Sorbet",
        "font": "Poppins",
        "primary": "#FFF7ED",
        "highlight": "#FB923C",
        "outline": "#431407",
        "outline_w": 8,
        "shadow": 2,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Aesthetic",
        "description": "Warm cozy peach highlight with deep mahogany stroke, perfect for cooking/vlogs."
    },

    # ── LUXURY, DOCUMENTARY & CINEMATIC ───────────────────────────────────────
    "Gold Luxury Crown": {
        "name": "Gold Luxury Crown",
        "font": "Impact",
        "primary": "#FFF8E7",
        "highlight": "#FFD700",
        "outline": "#241800",
        "outline_w": 9,
        "shadow": 3,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Luxury",
        "description": "Metallic luxury gold highlight, premium documentary and business aesthetic."
    },
    "Champagne Royal Gold": {
        "name": "Champagne Royal Gold",
        "font": "Montserrat",
        "primary": "#F8FAFC",
        "highlight": "#FBBF24",
        "outline": "#1E1B4B",
        "outline_w": 8,
        "shadow": 3,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Luxury",
        "description": "Cinematic warm champagne gold highlight with rich royal navy stroke."
    },
    "Royal Velvet Amethyst": {
        "name": "Royal Velvet Amethyst",
        "font": "Montserrat",
        "primary": "#FAF5FF",
        "highlight": "#A855F7",
        "outline": "#2E1065",
        "outline_w": 9,
        "shadow": 3,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Luxury",
        "description": "Majestic deep royal purple with obsidian violet stroke, luxurious & moody."
    },

    # ── AESTHETIC & PASTEL VIBES ──────────────────────────────────────────────
    "Bubblegum Hot Pink": {
        "name": "Bubblegum Hot Pink",
        "font": "Montserrat",
        "primary": "#FFFFFF",
        "highlight": "#FF1493",
        "outline": "#38001C",
        "outline_w": 9,
        "shadow": 2,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Viral",
        "description": "Vibrant hot magenta/pink, engaging pop culture and beauty lifestyle style."
    },
    "Candy Pastel Rose": {
        "name": "Candy Pastel Rose",
        "font": "Poppins",
        "primary": "#FFFFFF",
        "highlight": "#FB7185",
        "outline": "#4C0519",
        "outline_w": 8,
        "shadow": 2,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Aesthetic",
        "description": "Sweet coral rose pink highlight with rich berry border, ultra aesthetic."
    },
    "Pastel Lavender Dream": {
        "name": "Pastel Lavender Dream",
        "font": "Montserrat",
        "primary": "#FFFFFF",
        "highlight": "#C084FC",
        "outline": "#3B0764",
        "outline_w": 8,
        "shadow": 2,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Aesthetic",
        "description": "Soft purple aesthetic, chill lo-fi storytelling and personal brand look."
    },
    "Mint Emerald Chill": {
        "name": "Mint Emerald Chill",
        "font": "Poppins",
        "primary": "#FFFFFF",
        "highlight": "#34D399",
        "outline": "#064E3B",
        "outline_w": 8,
        "shadow": 2,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Viral",
        "description": "Cool refreshing mint green active word highlighting with pine outline."
    },

    # ── HEAVY STROKE & HIGH VISIBILITY ────────────────────────────────────────
    "Heavy Impact Stroke": {
        "name": "Heavy Impact Stroke",
        "font": "Anton",
        "primary": "#FFFFFF",
        "highlight": "#FFCC00",
        "outline": "#000000",
        "outline_w": 12,
        "shadow": 0,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Viral",
        "description": "Ultra-thick 12px black border around bold uppercase letters."
    },
    "Ultra Blackout Border": {
        "name": "Ultra Blackout Border",
        "font": "Impact",
        "primary": "#FFFFFF",
        "highlight": "#00F0FF",
        "outline": "#000000",
        "outline_w": 14,
        "shadow": 0,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Viral",
        "description": "Maximum 14px thick black border with brilliant cyan highlight, readable on anything."
    },
    "Cyberpunk Lime Green": {
        "name": "Cyberpunk Lime Green",
        "font": "Impact",
        "primary": "#FFFFFF",
        "highlight": "#39FF14",
        "outline": "#002B05",
        "outline_w": 10,
        "shadow": 2,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Viral",
        "description": "Ultra visible electric lime green, high energy gaming and tech look."
    },

    # ── DRAMATIC HOOKS & THRILLERS ────────────────────────────────────────────
    "Crimson Red Alert": {
        "name": "Crimson Red Alert",
        "font": "Impact",
        "primary": "#FFFFFF",
        "highlight": "#FF2B2B",
        "outline": "#2B0000",
        "outline_w": 9,
        "shadow": 2,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Viral",
        "description": "Urgent alert crimson red, perfect for dramatic hooks and thriller shorts."
    },
    "Vampire Dark Blood": {
        "name": "Vampire Dark Blood",
        "font": "Impact",
        "primary": "#FFFFFF",
        "highlight": "#E11D48",
        "outline": "#1F040A",
        "outline_w": 10,
        "shadow": 3,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Dramatic",
        "description": "Deep dramatic ruby blood red with dark crimson stroke for horror / crime."
    },

    # ── MINIMALIST & EDITORIAL ────────────────────────────────────────────────
    "Ali Abdaal Aesthetic Clean": {
        "name": "Ali Abdaal Aesthetic Clean",
        "font": "Montserrat",
        "primary": "#CBD5E1",
        "highlight": "#FFFFFF",
        "outline": "#0F172A",
        "outline_w": 3,
        "shadow": 6,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Minimal",
        "description": "Ali Abdaal minimalist look: Elegant soft slate to pure white with deep drop shadow."
    },
    "Minimalist White Shadow": {
        "name": "Minimalist White Shadow",
        "font": "Arial Black",
        "primary": "#E2E8F0",
        "highlight": "#FFFFFF",
        "outline": "#000000",
        "outline_w": 3,
        "shadow": 5,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Minimal",
        "description": "Clean elegant white bold typography with soft deep drop shadow."
    },

    # ── PLAYFUL COMIC & ANIME ─────────────────────────────────────────────────
    "Comic Superhero Pop": {
        "name": "Comic Superhero Pop",
        "font": "Comic Sans MS",
        "primary": "#FFFFFF",
        "highlight": "#FFDE00",
        "outline": "#000000",
        "outline_w": 11,
        "shadow": 4,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Comic",
        "description": "Vibrant yellow comic punch with bold comic-book outline for animated shorts."
    },
    "Comic Cartoon Fun": {
        "name": "Comic Cartoon Fun",
        "font": "Comic Sans MS",
        "primary": "#FFFDF0",
        "highlight": "#FF4500",
        "outline": "#000000",
        "outline_w": 10,
        "shadow": 3,
        "box": False,
        "box_color": "#000000",
        "pop": False,
        "category": "Comic",
        "description": "Playful comic font with flame active highlights and cartoon ink stroke."
    }
}

# Dynamic Intelligent Mode Keys
RANDOM_PER_SCENE_KEY = "🎲 Random Per Scene (Different Style Every Scene)"
RANDOM_PER_CHUNK_KEY = "🎲 Random Per Line (Different Style Every Phrase)"

PRESET_CHOICES = [
    RANDOM_PER_SCENE_KEY,
    RANDOM_PER_CHUNK_KEY
] + list(CAPCUT_PRESETS.keys())

# High-Impact Viral Fonts Pool (Fully compatible across Windows & FFmpeg Libass)
VIRAL_FONTS_POOL = [
    "Impact",
    "Arial Black",
    "Montserrat",
    "Anton",
    "Poppins",
    "TheBoldFont",
    "Bebas Neue",
    "Komika Axis",
    "Segoe UI Black",
    "Franklin Gothic Heavy",
    "Trebuchet MS",
    "Verdana"
]

RANDOM_FONT_KEY = "🎲 Random Font (Different Font Per Scene)"
AUTO_FONT_KEY = "✨ Auto (Preset Curated Font)"

FONT_CHOICES = [
    AUTO_FONT_KEY,
    RANDOM_FONT_KEY,
    "Impact",
    "Arial Black",
    "Montserrat",
    "Anton",
    "Poppins",
    "TheBoldFont",
    "Bebas Neue",
    "Komika Axis",
    "Segoe UI Black",
    "Franklin Gothic Heavy",
    "Trebuchet MS",
    "Verdana",
    "Comic Sans MS"
]

def clean_font_name(fn: Optional[str]) -> str:
    """Extract clean font name from UI string."""
    if not fn or "auto" in fn.lower():
        return ""
    if "random" in fn.lower():
        return "RANDOM"
    cleaned = re.sub(r'\(.*?\)', '', fn).strip()
    return cleaned or "Impact"

# ══════════════════════════════════════════════════════════════════════════════
# 2. UTILITY FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════
def natural_sort_key(filename: str) -> list:
    """
    Extracts alphanumeric tokens and numbers from filename so Scene_1 comes
    before Scene_2 comes before Scene_10 in proper mathematical sequence.
    """
    base = os.path.basename(filename)
    parts = re.split(r'(\d+)', base.lower())
    return [int(p) if p.isdigit() else p for p in parts]

def format_seconds(seconds: float) -> str:
    """Format seconds into MM:SS.ms or HH:MM:SS."""
    if not seconds or seconds < 0:
        return "00:00"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{int(h):02d}:{int(m):02d}:{s:04.1f}"
    return f"{int(m):02d}:{s:04.1f}"

def format_bytes(b: int) -> str:
    if not b:
        return "0 MB"
    mb = b / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.2f} GB"
    return f"{mb:.1f} MB"

def hex_to_ass_color(hexc: str, alpha: int = 0) -> str:
    """Convert #RRGGBB hex color to ASS &HAABBGGRR format."""
    hexc = (hexc or "#FFFFFF").lstrip("#")
    if len(hexc) == 3:
        hexc = "".join(c * 2 for c in hexc)
    try:
        r = int(hexc[0:2], 16)
        g = int(hexc[2:4], 16)
        b = int(hexc[4:6], 16)
    except Exception:
        r, g, b = 255, 255, 255
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"

def probe_clip(file_path: str) -> Dict[str, Any]:
    """Inspect video file metadata using ffprobe."""
    meta = {
        "path": file_path,
        "filename": os.path.basename(file_path),
        "exists": False,
        "width": 1080,
        "height": 1920,
        "duration": 0.0,
        "duration_str": "00:00",
        "fps": 30.0,
        "vcodec": "",
        "acodec": "",
        "has_audio": False,
        "size_bytes": 0,
        "size_str": "0 MB"
    }

    p = Path(file_path)
    if not p.is_file():
        return meta

    meta["exists"] = True
    meta["size_bytes"] = p.stat().st_size
    meta["size_str"] = format_bytes(meta["size_bytes"])

    if not FFPROBE_PATH:
        return meta

    try:
        cmd = [
            FFPROBE_PATH,
            "-v", "error",
            "-show_entries", "stream=index,codec_type,codec_name,width,height,r_frame_rate,duration,sample_rate,channels",
            "-show_entries", "format=duration,size",
            "-of", "json",
            str(p)
        ]
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            startupinfo=STARTUPINFO,
            creationflags=CREATIONFLAGS,
            timeout=15
        )
        if res.returncode == 0 and res.stdout:
            data = json.loads(res.stdout)
            format_info = data.get("format", {})
            dur = float(format_info.get("duration", 0) or 0)
            if dur > 0:
                meta["duration"] = dur
                meta["duration_str"] = format_seconds(dur)

            streams = data.get("streams", [])
            for st in streams:
                ctype = st.get("codec_type")
                if ctype == "video" and not meta["vcodec"]:
                    meta["vcodec"] = st.get("codec_name", "")
                    meta["width"] = int(st.get("width", 0) or 0) or 1080
                    meta["height"] = int(st.get("height", 0) or 0) or 1920

                    r_fps = st.get("r_frame_rate", "30/1")
                    if "/" in r_fps:
                        num, den = r_fps.split("/")
                        if float(den) > 0:
                            meta["fps"] = round(float(num) / float(den), 2)
                    elif r_fps:
                        meta["fps"] = round(float(r_fps), 2)

                    if not meta["duration"]:
                        st_dur = float(st.get("duration", 0) or 0)
                        if st_dur > 0:
                            meta["duration"] = st_dur
                            meta["duration_str"] = format_seconds(st_dur)

                elif ctype == "audio" and not meta["has_audio"]:
                    meta["has_audio"] = True
                    meta["acodec"] = st.get("codec_name", "")

    except Exception as e:
        _safe_print(f"[CaptionsEngine] probe error: {e}")

    return meta

def extract_thumbnail(video_path: str, out_thumb_path: str, at_sec: float = 1.0) -> bool:
    """Generate a quick thumbnail image of a video clip."""
    if not FFMPEG_PATH or not os.path.isfile(video_path):
        return False
    os.makedirs(os.path.dirname(os.path.abspath(out_thumb_path)), exist_ok=True)
    try:
        cmd = [
            FFMPEG_PATH, "-y",
            "-ss", f"{at_sec:.2f}",
            "-i", video_path,
            "-vframes", "1",
            "-vf", "scale=160:-1:force_original_aspect_ratio=decrease",
            out_thumb_path
        ]
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=STARTUPINFO,
            creationflags=CREATIONFLAGS,
            timeout=10
        )
        return res.returncode == 0 and os.path.isfile(out_thumb_path)
    except Exception:
        return False

def build_clean_cpu_fallback(cmd: List[str]) -> List[str]:
    """
    Strips hardware-specific options (-rc, -cq, -rc-lookahead, etc.) and
    replaces video codec with ultra-fast multi-threaded libx264.
    """
    clean_cmd = []
    skip_next = False
    gpu_flags = {"-rc", "-cq", "-rc-lookahead", "-gpu", "-spatial-aq", "-temporal-aq"}
    for arg in cmd:
        if skip_next:
            skip_next = False
            continue
        if arg in gpu_flags:
            skip_next = True
            continue
        if arg == "-c:v":
            clean_cmd.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-threads", "0"])
            skip_next = True
            continue
        clean_cmd.append(arg)
    return clean_cmd

# ══════════════════════════════════════════════════════════════════════════════
# 3. SEQUENTIAL VIDEO MERGER
# ══════════════════════════════════════════════════════════════════════════════
def merge_clips_sequence(
    clips: List[str],
    output_path: str,
    target_resolution: str = "1080x1920",
    log_callback: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None
) -> Dict[str, Any]:
    """
    Merges clips in exact user sequence, normalizes resolution and audio streams,
    and returns precise scene boundaries for per-scene styling.
    """
    def log(msg: str):
        if log_callback: log_callback(msg)
        else: _safe_print(f"[MergeEngine] {msg}")

    if not FFMPEG_PATH:
        return {"success": False, "error": "FFmpeg binary not found!"}

    if not clips:
        return {"success": False, "error": "No clips provided"}

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    log(f"🎬 Probing {len(clips)} input clips...")

    probes = []
    scene_boundaries = []
    current_time = 0.0

    for idx, cp in enumerate(clips):
        pinfo = probe_clip(cp)
        probes.append(pinfo)
        dur = pinfo["duration"] if pinfo["duration"] > 0 else 3.0
        scene_boundaries.append({
            "index": idx,
            "path": cp,
            "filename": pinfo["filename"],
            "start": round(current_time, 3),
            "end": round(current_time + dur, 3),
            "duration": round(dur, 3),
            "width": pinfo["width"],
            "height": pinfo["height"]
        })
        current_time += dur
        log(f"  Scene #{idx + 1}: {pinfo['filename']} ({pinfo['duration_str']}) -> [{scene_boundaries[-1]['start']}s to {scene_boundaries[-1]['end']}s]")

    total_duration = round(current_time, 3)
    log(f"Total Sequence Duration: {format_seconds(total_duration)} across {len(clips)} scenes.")

    # Target Canvas
    target_w, target_h = 1080, 1920
    if target_resolution == "1920x1080":
        target_w, target_h = 1920, 1080
    elif target_resolution == "1080x1920":
        target_w, target_h = 1080, 1920
    elif target_resolution == "1080x1080":
        target_w, target_h = 1080, 1080
    elif target_resolution == "original":
        target_w = probes[0]["width"]
        target_h = probes[0]["height"]

    # Target dimensions must be even
    target_w = target_w if target_w % 2 == 0 else target_w + 1
    target_h = target_h if target_h % 2 == 0 else target_h + 1

    log(f"Normalizing all clips to canvas: {target_w}x{target_h} @ 30fps | 48kHz Stereo AAC...")

    # Hardware detection
    hw_encoder = "libx264"
    enc_args = ["-c:v", "libx264", "-preset", "fast", "-crf", "18"]
    try:
        import hardware_accel
        hw_info = hardware_accel.get_hardware_info()
        if hw_info.get("is_gpu") and hw_info.get("hw_encoder"):
            hw_encoder = hw_info["hw_encoder"]
            enc_args = ["-c:v", hw_encoder] + hw_info.get("enc_quality", ["-cq", "20", "-b:v", "0"])
            log(f"⚡ GPU Hardware Acceleration Active: {hw_info.get('gpu_name', 'GPU')} ({hw_encoder})")
    except Exception:
        pass

    BATCH_SIZE = 12
    temp_dir = os.path.join(tempfile.gettempdir(), "captions_studio_merge")
    os.makedirs(temp_dir, exist_ok=True)

    def _render_batch(b_clips, b_probes, b_out):
        cmd = [FFMPEG_PATH, "-y"]
        for cp in b_clips:
            cmd.extend(["-i", cp])

        filter_parts = []
        n_b = len(b_clips)
        for i, p in enumerate(b_probes):
            v_f = (
                f"[{i}:v]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
                f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=30[v{i}];"
            )
            filter_parts.append(v_f)

            if p["has_audio"]:
                a_f = f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo[a{i}];"
            else:
                clip_dur = p["duration"] if p["duration"] > 0 else 3.0
                a_f = f"anullsrc=channel_layout=stereo:sample_rate=48000:d={clip_dur}[a{i}];"
            filter_parts.append(a_f)

        concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(n_b))
        filter_parts.append(f"{concat_inputs}concat=n={n_b}:v=1:a=1[v_out][a_out]")
        filter_complex_str = "".join(filter_parts)

        cmd.extend([
            "-filter_complex", filter_complex_str,
            "-map", "[v_out]",
            "-map", "[a_out]",
        ])
        cmd.extend(enc_args)
        cmd.extend([
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            b_out
        ])

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            startupinfo=STARTUPINFO,
            creationflags=CREATIONFLAGS
        )
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            if hw_encoder != "libx264":
                log(f"⚠️ NVENC encoder note: {stderr[:120].strip()}")
                log("🔄 Falling back to high-speed libx264 software encoder...")
                cmd_fallback = build_clean_cpu_fallback(cmd)
                proc2 = subprocess.Popen(
                    cmd_fallback,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    startupinfo=STARTUPINFO,
                    creationflags=CREATIONFLAGS
                )
                stdout2, stderr2 = proc2.communicate()
                if proc2.returncode != 0:
                    log(f"FFmpeg batch merge error: {stderr2[:250]}")
                    return False
            else:
                log(f"FFmpeg batch merge error: {stderr[:250]}")
                return False

        return os.path.isfile(b_out) and os.path.getsize(b_out) > 1000

    try:
        if len(clips) <= BATCH_SIZE:
            if progress_callback:
                progress_callback(10.0, "Merging sequential video clips...")
            ok = _render_batch(clips, probes, output_path)
            if not ok:
                return {"success": False, "error": "Single batch merge failed"}
        else:
            n_batches = (len(clips) + BATCH_SIZE - 1) // BATCH_SIZE
            log(f"⚡ Merging {len(clips)} scenes in {n_batches} batches of up to {BATCH_SIZE} clips (Zero-Jitter & Crash-Proof)...")
            batch_files = []
            cleanup_files = []

            try:
                for b_idx in range(n_batches):
                    b_start = b_idx * BATCH_SIZE
                    b_end = min(b_start + BATCH_SIZE, len(clips))
                    b_clips = clips[b_start:b_end]
                    b_probes = probes[b_start:b_end]

                    b_out = os.path.join(temp_dir, f"batch_{b_idx}_{int(time.time()*1000)%999999}.mp4")
                    cleanup_files.append(b_out)

                    pct = 10.0 + (b_idx / float(n_batches)) * 20.0
                    if progress_callback:
                        progress_callback(pct, f"Merging Batch {b_idx + 1}/{n_batches} (Scenes #{b_start + 1}–#{b_end})...")
                    log(f"  📦 Batch {b_idx + 1}/{n_batches}: Scenes #{b_start + 1} to #{b_end} ({len(b_clips)} clips)...")

                    b_ok = _render_batch(b_clips, b_probes, b_out)
                    if not b_ok or not os.path.isfile(b_out):
                        return {"success": False, "error": f"Failed to normalize Batch {b_idx + 1}/{n_batches} (Scenes #{b_start + 1}–#{b_end})"}

                    batch_files.append(b_out)

                if progress_callback:
                    progress_callback(32.0, "Joining all scene batches into final stream...")
                log(f"🔗 Joining {len(batch_files)} batches into final video stream via Concat Demuxer...")

                concat_list_path = os.path.join(temp_dir, f"batches_concat_{int(time.time()*1000)}.txt")
                cleanup_files.append(concat_list_path)

                with open(concat_list_path, "w", encoding="utf-8") as f_cat:
                    for bf in batch_files:
                        safe_bf = os.path.abspath(bf).replace("\\", "/").replace("'", "'\\''")
                        f_cat.write(f"file '{safe_bf}'\n")

                # Concat stream copy (instant, 0% re-encoding quality loss)
                concat_cmd = [
                    FFMPEG_PATH, "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", concat_list_path,
                    "-c", "copy",
                    "-movflags", "+faststart",
                    output_path
                ]
                c_proc = subprocess.Popen(
                    concat_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    startupinfo=STARTUPINFO,
                    creationflags=CREATIONFLAGS
                )
                c_out, c_err = c_proc.communicate()

                if c_proc.returncode != 0 or not (os.path.isfile(output_path) and os.path.getsize(output_path) > 1000):
                    log("⚠️ Stream copy concat note, falling back to batch re-encode concat...")
                    concat_cmd_fallback = [
                        FFMPEG_PATH, "-y",
                        "-f", "concat",
                        "-safe", "0",
                        "-i", concat_list_path
                    ] + enc_args + [
                        "-c:a", "aac",
                        "-b:a", "192k",
                        "-ar", "48000",
                        "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart",
                        output_path
                    ]
                    c_proc2 = subprocess.Popen(
                        concat_cmd_fallback,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        startupinfo=STARTUPINFO,
                        creationflags=CREATIONFLAGS
                    )
                    c_proc2.communicate()

            finally:
                for cf in cleanup_files:
                    try:
                        if os.path.isfile(cf):
                            os.remove(cf)
                    except Exception:
                        pass

        if os.path.isfile(output_path) and os.path.getsize(output_path) > 1000:
            log(f"✓ All {len(clips)} clips merged successfully into continuous stream ({format_bytes(os.path.getsize(output_path))})")
            return {
                "success": True,
                "output_path": output_path,
                "duration": total_duration,
                "scene_boundaries": scene_boundaries,
                "target_w": target_w,
                "target_h": target_h
            }
        else:
            return {"success": False, "error": "Merged output file was not created or empty"}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ══════════════════════════════════════════════════════════════════════════════
# 4. WHISPER AUDIO EXTRACTION & TRANSCRIPTION
# ══════════════════════════════════════════════════════════════════════════════
def transcribe_video_audio(
    video_path: str,
    model_size: str = "base",
    language: Optional[str] = None,
    log_callback: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None
) -> Dict[str, Any]:
    """
    Extracts 16kHz mono audio and transcribes with whisper_engine,
    returning individual words with start and end timestamps.
    """
    def log(msg: str):
        if log_callback: log_callback(msg)
        else: _safe_print(f"[WhisperEngine] {msg}")

    if not FFMPEG_PATH:
        return {"success": False, "error": "FFmpeg not found"}

    if progress_callback:
        progress_callback(30.0, "Extracting audio for Whisper transcription...")

    temp_dir = tempfile.gettempdir()
    wav_path = os.path.join(temp_dir, f"whisper_audio_{int(time.time()*1000)}.wav")

    log("Extracting clean 16kHz mono WAV stream from video...")
    cmd = [
        FFMPEG_PATH, "-y",
        "-i", video_path,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        wav_path
    ]
    subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        startupinfo=STARTUPINFO,
        creationflags=CREATIONFLAGS
    )

    if not os.path.isfile(wav_path) or os.path.getsize(wav_path) < 100:
        return {"success": False, "error": "Audio extraction failed (video may be silent)"}

    log(f"Loading faster-whisper model '{model_size}' (word_timestamps=True)...")
    if progress_callback:
        progress_callback(40.0, f"Transcribing speech with Whisper ({model_size})...")

    try:
        import whisper_engine
        model = whisper_engine.load_model(model_size, device="cpu")

        transcribe_kw = {"word_timestamps": True}
        lang_code = language.strip().lower() if language else None
        if lang_code and lang_code not in ("auto", "auto detect", ""):
            if "hindi" in lang_code: lang_code = "hi"
            elif "english" in lang_code: lang_code = "en"
            elif "urdu" in lang_code: lang_code = "ur"
            elif "spanish" in lang_code: lang_code = "es"
            elif "french" in lang_code: lang_code = "fr"
            elif "german" in lang_code: lang_code = "de"
            transcribe_kw["language"] = lang_code

        res = model.transcribe(wav_path, **transcribe_kw)
        try:
            if os.path.isfile(wav_path):
                os.remove(wav_path)
        except Exception:
            pass

        segments = res.get("segments", [])
        words_list = []

        for seg in segments:
            seg_words = seg.get("words", [])
            if seg_words:
                for w in seg_words:
                    clean_w = str(w.get("word", "")).strip()
                    if clean_w:
                        words_list.append({
                            "word": clean_w,
                            "start": round(float(w.get("start", 0.0)), 3),
                            "end": round(float(w.get("end", 0.0)), 3)
                        })
            else:
                # If segment has no word timestamps, split segment evenly across its words
                raw_words = [w for w in seg.get("text", "").split() if w.strip()]
                if raw_words:
                    s_t = float(seg.get("start", 0.0))
                    e_t = float(seg.get("end", s_t + 1.0))
                    w_dur = (e_t - s_t) / len(raw_words)
                    for idx_w, rw in enumerate(raw_words):
                        words_list.append({
                            "word": rw,
                            "start": round(s_t + idx_w * w_dur, 3),
                            "end": round(s_t + (idx_w + 1) * w_dur, 3)
                        })

        full_text = res.get("text", "").strip()
        log(f"✓ Transcribed {len(words_list)} words across {len(segments)} segments.")
        return {
            "success": True,
            "text": full_text,
            "words": words_list,
            "segments": segments,
            "language": res.get("language", "auto")
        }

    except Exception as e:
        try:
            if os.path.isfile(wav_path):
                os.remove(wav_path)
        except Exception:
            pass
        return {"success": False, "error": f"Transcription error: {str(e)}"}

# ══════════════════════════════════════════════════════════════════════════════
# 5. CAPCUT ASS SUBTITLE GENERATION (ANTI-SHAKE & RANDOM FONT ENGINE)
# ══════════════════════════════════════════════════════════════════════════════
def build_capcut_ass(
    words: List[Dict[str, Any]],
    total_duration: float,
    out_ass_path: str,
    video_w: int = 1080,
    video_h: int = 1920,
    preset_name: str = "CapCut Bold Yellow",
    words_per_line: int = 3,
    text_case: str = "ALL CAPS",
    position: str = "Bottom-Center",
    font_size_override: Optional[int] = None,
    font_name_override: Optional[str] = None,
    scene_boundaries: Optional[List[Dict[str, Any]]] = None,
    custom_caption_pos: Optional[Tuple[float, float]] = None,
    anti_shake: bool = True,
    log_callback: Optional[Callable[[str], None]] = None
) -> str:
    """
    Builds an Advanced SubStation Alpha (.ass) subtitle file formatted with
    viral CapCut word-by-word highlights.

    FEATURES:
    - 🛡 ANTI-SHAKE & ZERO JITTER:
      Eliminates font reflow and line wobbling by keeping character metrics 100% frozen.
      Active words are highlighted via pure color tags without dynamic \fscx font scaling.
      Inter-word gaps are bridged contiguously to completely prevent flickering/blinking!
    - 🎲 RANDOM PER SCENE & RANDOM PER CHUNK:
      Dynamically switches CapCut visual style across scenes or phrases.
    - 🔤 RANDOM FONT SUPPORT:
      Dynamically assigns curated viral fonts (Impact, Montserrat, Anton, Arial Black, etc.)
      per scene or phrase while ensuring all styles render with pixel-perfect contrast.
    """
    def log(msg: str):
        if log_callback: log_callback(msg)
        else: _safe_print(f"[ASSBuilder] {msg}")

    os.makedirs(os.path.dirname(os.path.abspath(out_ass_path)), exist_ok=True)

    is_random_per_scene = (preset_name == RANDOM_PER_SCENE_KEY)
    is_random_per_chunk = (preset_name == RANDOM_PER_CHUNK_KEY)
    is_random_font = bool(font_name_override and "random" in font_name_override.lower())
    cleaned_font = clean_font_name(font_name_override)
    available_preset_keys = list(CAPCUT_PRESETS.keys())

    def get_preset_dict(name: str) -> Dict[str, Any]:
        if name in CAPCUT_PRESETS:
            return CAPCUT_PRESETS[name]
        norm = re.sub(r'[^\w\s]', '', name).strip().lower()
        for k, v in CAPCUT_PRESETS.items():
            k_norm = re.sub(r'[^\w\s]', '', k).strip().lower()
            if norm == k_norm:
                return v
        return CAPCUT_PRESETS["CapCut Bold Yellow"]

    def pick_font_for_item(preset_default_font: str, seed_idx: int = 0) -> str:
        if is_random_font:
            rng = random.Random(seed_idx * 17 + 42)
            return rng.choice(VIRAL_FONTS_POOL)
        if cleaned_font and cleaned_font != "RANDOM":
            return cleaned_font
        return preset_default_font or "Impact"

    # Base scale calculation relative to standard 1080p
    scale = video_w / 1080.0
    base_font_size = font_size_override if font_size_override else int(68 * scale)
    base_font_size = max(24, min(140, base_font_size))

    # Alignment
    pos_lower = position.lower()
    if "top" in pos_lower:
        alignment = 8
        margin_v = int(video_h * 0.12)
    elif "middle" in pos_lower or "center" in pos_lower and "bottom" not in pos_lower:
        alignment = 5
        margin_v = 0
    else:  # Bottom-Center (CapCut standard)
        alignment = 2
        margin_v = int(video_h * 0.15)

    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {video_w}",
        f"PlayResY: {video_h}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
    ]

    def build_ass_style_entry(style_id: str, p_dict: Dict[str, Any], fn: str) -> Tuple[str, Dict[str, Any]]:
        prim = hex_to_ass_color(p_dict.get("primary", "#FFFFFF"), 0)
        high = hex_to_ass_color(p_dict.get("highlight", "#FFE600"), 0)
        is_box = p_dict.get("box", False)
        border_style = 3 if is_box else 1

        if is_box:
            box_alpha = p_dict.get("box_alpha", 30)
            box_c = hex_to_ass_color(p_dict.get("box_color", "#000000"), box_alpha)
            outl = box_c
            outline_w = max(6, int(12 * scale))
            shadow_w = 0
        else:
            box_c = "&H80000000"
            outl = hex_to_ass_color(p_dict.get("outline", "#000000"), 0)
            outline_w = max(4, int(p_dict.get("outline_w", 8) * scale))
            shadow_w = max(0, int(p_dict.get("shadow", 2) * scale))

        style_line = f"Style: {style_id},{fn},{base_font_size},{prim},{high},{outl},{box_c},1,0,0,0,100,100,0,0,{border_style},{outline_w},{shadow_w},{alignment},40,40,{margin_v},1"
        info = {
            "style_id": style_id,
            "preset": p_dict,
            "highlight_ass": high,
            "primary_ass": prim,
            "font": fn
        }
        return style_line, info

    def format_ass_time(sec: float) -> str:
        sec = max(0.0, sec)
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = sec % 60
        return f"{h}:{m:02d}:{s:05.2f}"

    def apply_casing(txt: str) -> str:
        tc = (text_case or "ALL CAPS").upper()
        if "ALL" in tc or "CAPS" in tc or "UPPER" in tc:
            return txt.upper()
        elif "TITLE" in tc:
            return txt.title()
        return txt

    def find_scene_idx(t: float) -> int:
        if not scene_boundaries:
            return 0
        for sc in scene_boundaries:
            if sc["start"] <= t < sc["end"]:
                return sc["index"]
        return scene_boundaries[-1]["index"] if scene_boundaries else 0

    # Words chunking
    w_per_chunk = max(1, min(10, int(words_per_line)))
    word_chunks = []
    if words:
        if scene_boundaries:
            scene_word_buckets: Dict[int, List[Dict[str, Any]]] = {}
            for w in words:
                s_idx = find_scene_idx(w["start"])
                scene_word_buckets.setdefault(s_idx, []).append(w)
            for s_idx in sorted(scene_word_buckets.keys()):
                s_words = scene_word_buckets[s_idx]
                for i in range(0, len(s_words), w_per_chunk):
                    word_chunks.append(s_words[i:i + w_per_chunk])
        else:
            for i in range(0, len(words), w_per_chunk):
                word_chunks.append(words[i:i + w_per_chunk])

    # Build styles dictionary based on active modes
    all_used_styles: Dict[Any, Dict[str, Any]] = {}

    if is_random_per_chunk:
        log(f"🎲 'Random Per Line' mode: Assigning dynamic CapCut styles across {len(word_chunks)} phrases...")
        last_k = None
        for c_idx, _ in enumerate(word_chunks):
            cands = [k for k in available_preset_keys if k != last_k]
            chosen_key = random.choice(cands if cands else available_preset_keys)
            last_k = chosen_key
            p_dict = get_preset_dict(chosen_key)
            fn = pick_font_for_item(p_dict["font"], seed_idx=c_idx)
            style_id = f"CapCut_Chunk_{c_idx}"
            s_line, s_info = build_ass_style_entry(style_id, p_dict, fn)
            header.append(s_line)
            all_used_styles[c_idx] = s_info

    elif is_random_per_scene and scene_boundaries:
        log(f"🎲 'Random Per Scene' mode: Assigning distinct CapCut styles per clip...")
        last_k = None
        for sc in scene_boundaries:
            idx = sc["index"]
            cands = [k for k in available_preset_keys if k != last_k]
            chosen_key = random.choice(cands if cands else available_preset_keys)
            last_k = chosen_key
            p_dict = get_preset_dict(chosen_key)
            fn = pick_font_for_item(p_dict["font"], seed_idx=idx)
            style_id = f"CapCut_Scene_{idx}"
            s_line, s_info = build_ass_style_entry(style_id, p_dict, fn)
            header.append(s_line)
            all_used_styles[idx] = s_info
            log(f"   Scene #{idx + 1} ({sc['start']}s - {sc['end']}s) -> 🎨 {chosen_key} [{fn}]")

    elif is_random_font and scene_boundaries:
        log("🎲 'Random Font' mode: Randomizing high-impact viral fonts per scene...")
        p_dict = get_preset_dict(preset_name)
        for sc in scene_boundaries:
            idx = sc["index"]
            fn = pick_font_for_item(p_dict["font"], seed_idx=idx)
            style_id = f"CapCut_Scene_{idx}"
            s_line, s_info = build_ass_style_entry(style_id, p_dict, fn)
            header.append(s_line)
            all_used_styles[idx] = s_info
            log(f"   Scene #{idx + 1} -> 🔤 Font: {fn}")

    else:
        # Default single preset style
        p_dict = get_preset_dict(preset_name)
        fn = pick_font_for_item(p_dict["font"], seed_idx=0)
        style_id = "CapCut_Main"
        s_line, s_info = build_ass_style_entry(style_id, p_dict, fn)
        header.append(s_line)
        all_used_styles["default"] = s_info

    header.extend([
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    ])

    events = []
    default_style_info = list(all_used_styles.values())[0] if all_used_styles else {
        "style_id": "CapCut_Main",
        "preset": CAPCUT_PRESETS["CapCut Bold Yellow"],
        "highlight_ass": "&H0000E6FF",
        "primary_ass": "&H00FFFFFF",
        "font": "Impact"
    }

    # Generate Dialogue Events with Rock-Solid Anti-Shake Protection
    for chunk_idx, chunk in enumerate(word_chunks):
        if not chunk:
            continue
        chunk_start = chunk[0]["start"]
        chunk_end = max(chunk_start + 0.35, chunk[-1]["end"])

        # Determine which style applies to this chunk
        if is_random_per_chunk:
            style_info = all_used_styles.get(chunk_idx, default_style_info)
        elif is_random_per_scene or is_random_font:
            sc_idx = find_scene_idx(chunk_start)
            style_info = all_used_styles.get(sc_idx, default_style_info)
        else:
            style_info = default_style_info

        style_id = style_info["style_id"]
        high_ass = style_info["highlight_ass"]
        prim_ass = style_info["primary_ass"]
        num_words = len(chunk)

        # Connect consecutive words contiguously to eliminate inter-word gaps/flickering
        for act_idx, target_word in enumerate(chunk):
            w_start = target_word["start"]
            sub_start = chunk_start if act_idx == 0 else max(chunk_start, w_start)

            if act_idx + 1 < num_words:
                next_start = chunk[act_idx + 1]["start"]
                sub_end = max(sub_start + 0.1, next_start)
            else:
                sub_end = max(sub_start + 0.25, chunk_end)

            line_parts = []
            for j, w in enumerate(chunk):
                raw_w = apply_casing(w["word"])
                if j == act_idx:
                    # Active word: Highlight color ONLY
                    # Zero inline font expansion (\fscx) prevents character metric reflow and eliminates line shaking!
                    if anti_shake or num_words > 1:
                        line_parts.append(f"{{\\c{high_ass}}}{raw_w}{{\\c{prim_ass}}}")
                    else:
                        line_parts.append(f"{{\\c{high_ass}}}{{\\fscx108\\fscy108\\t(0,50,\\fscx100\\fscy100)}}{raw_w}{{\\c{prim_ass}}}")
                else:
                    line_parts.append(raw_w)

            dialogue_text = " ".join(line_parts)
            if custom_caption_pos is not None:
                target_x = int(round(custom_caption_pos[0] * video_w))
                target_y = int(round(custom_caption_pos[1] * video_h))
                dialogue_text = f"{{\\an5\\pos({target_x},{target_y})}}{dialogue_text}"

            events.append(f"Dialogue: 0,{format_ass_time(sub_start)},{format_ass_time(sub_end)},{style_id},,0,0,0,,{dialogue_text}")

    full_ass_content = "\n".join(header + events) + "\n"
    with open(out_ass_path, "w", encoding="utf-8") as f:
        f.write(full_ass_content)

    log(f"✓ Generated CapCut Anti-Shake ASS subtitles ({len(events)} events) -> {out_ass_path}")
    return out_ass_path

# ══════════════════════════════════════════════════════════════════════════════
# 6. LOGO & SUBTITLE BURN (FINAL RENDER ENGINE)
# ══════════════════════════════════════════════════════════════════════════════
def burn_logo_and_subtitles(
    input_video: str,
    ass_path: str,
    output_video: str,
    enable_logo: bool = True,
    logo_path: Optional[str] = None,
    logo_position: str = "Top-Right",
    logo_width: int = 160,
    logo_opacity: float = 1.0,
    margin_x: int = 30,
    margin_y: int = 30,
    custom_logo_pos: Optional[Tuple[float, float]] = None,
    log_callback: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None
) -> Dict[str, Any]:
    """
    Burns ASS subtitles and overlays logo watermark simultaneously in a
    single-pass FFmpeg command with GPU NVENC acceleration.
    """
    def log(msg: str):
        if log_callback: log_callback(msg)
        else: _safe_print(f"[BurnEngine] {msg}")

    if not FFMPEG_PATH:
        return {"success": False, "error": "FFmpeg binary not found"}

    os.makedirs(os.path.dirname(os.path.abspath(output_video)), exist_ok=True)

    # Windows path escape for subtitles filter
    safe_ass = os.path.abspath(ass_path).replace("\\", "/").replace(":", "\\:")

    has_logo = enable_logo and logo_path and os.path.isfile(logo_path)

    # Hardware detection
    hw_encoder = "libx264"
    enc_args = ["-c:v", "libx264", "-preset", "fast", "-crf", "18"]
    try:
        import hardware_accel
        hw_info = hardware_accel.get_hardware_info()
        if hw_info.get("is_gpu") and hw_info.get("hw_encoder"):
            hw_encoder = hw_info["hw_encoder"]
            enc_args = ["-c:v", hw_encoder] + hw_info.get("enc_quality", ["-cq", "20", "-b:v", "0"])
            log(f"⚡ GPU Hardware Accelerated Burn: {hw_info.get('gpu_name', 'GPU')} ({hw_encoder})")
    except Exception:
        pass

    # Build filter complex
    if has_logo:
        if custom_logo_pos is not None:
            p_in = probe_clip(input_video)
            in_w = p_in.get("width", 1080) or 1080
            in_h = p_in.get("height", 1920) or 1920
            fx, fy = custom_logo_pos
            lx = max(0, min(in_w - logo_width, int(round(fx * in_w - (logo_width / 2.0)))))
            ly = max(0, min(in_h - 20, int(round(fy * in_h - (logo_width / 4.0)))))
            pos_expr = f"{lx}:{ly}"
            log(f"Applying Custom Dragged Logo at ({lx}px, {ly}px, width={logo_width}px, opacity={int(logo_opacity*100)}%)...")
        else:
            log(f"Applying Logo Watermark: '{os.path.basename(logo_path)}' ({logo_position}, width={logo_width}px, opacity={int(logo_opacity*100)}%)...")
            # Position expressions
            pos = logo_position.lower()
            if "top-left" in pos:
                pos_expr = f"{margin_x}:{margin_y}"
            elif "bottom-right" in pos:
                pos_expr = f"W-w-{margin_x}:H-h-{margin_y}"
            elif "bottom-left" in pos:
                pos_expr = f"{margin_x}:H-h-{margin_y}"
            elif "top-center" in pos:
                pos_expr = f"(W-w)/2:{margin_y}"
            elif "bottom-center" in pos:
                pos_expr = f"(W-w)/2:H-h-{margin_y}"
            elif "center" in pos and "top" not in pos and "bottom" not in pos:
                pos_expr = f"(W-w)/2:(H-h)/2"
            else:  # Top-Right (default)
                pos_expr = f"W-w-{margin_x}:{margin_y}"

        logo_filter = (
            f"[1:v]format=rgba,colorchannelmixer=aa={logo_opacity:.2f},scale={logo_width}:-2[scaled_logo];"
            f"[0:v][scaled_logo]overlay={pos_expr}[v_logo];"
            f"[v_logo]subtitles='{safe_ass}'[v_out]"
        )

        cmd = [
            FFMPEG_PATH, "-y",
            "-i", input_video,
            "-i", logo_path,
            "-filter_complex", logo_filter,
            "-map", "[v_out]",
            "-map", "0:a?",
        ]
    else:
        log("Rendering CapCut subtitles (no logo watermark)...")
        sub_filter = f"subtitles='{safe_ass}'"
        cmd = [
            FFMPEG_PATH, "-y",
            "-i", input_video,
            "-vf", sub_filter,
            "-map", "0:v",
            "-map", "0:a?",
        ]

    cmd.extend(enc_args)
    cmd.extend([
        "-c:a", "copy",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output_video
    ])

    if progress_callback:
        progress_callback(80.0, "Burning CapCut captions & rendering final video...")

    log("Executing final FFmpeg burn pass...")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            startupinfo=STARTUPINFO,
            creationflags=CREATIONFLAGS
        )
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            if hw_encoder != "libx264":
                log(f"⚠️ NVENC encoder note: {stderr[:150].strip()}")
                log("🔄 Falling back to high-speed libx264 CPU encoder...")
                cmd_fallback = build_clean_cpu_fallback(cmd)
                proc2 = subprocess.Popen(
                    cmd_fallback,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    startupinfo=STARTUPINFO,
                    creationflags=CREATIONFLAGS
                )
                stdout2, stderr2 = proc2.communicate()
                if proc2.returncode != 0:
                    log(f"FFmpeg burn error: {stderr2[:300]}")
                    return {"success": False, "error": f"Burn failed: {stderr2[:200]}"}
            else:
                log(f"FFmpeg burn error: {stderr[:300]}")
                return {"success": False, "error": f"Burn failed: {stderr[:200]}"}

        if os.path.isfile(output_video) and os.path.getsize(output_video) > 1000:
            final_size = format_bytes(os.path.getsize(output_video))
            log(f"✅ Final Video Exported Successfully: {output_video} ({final_size})")
            if progress_callback:
                progress_callback(100.0, "Export Complete!")
            return {
                "success": True,
                "output_video": output_video,
                "file_size": final_size
            }
        else:
            return {"success": False, "error": "Output video was not generated"}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ══════════════════════════════════════════════════════════════════════════════
# 7. LIVE STYLE & LOGO PREVIEW GENERATOR
# ══════════════════════════════════════════════════════════════════════════════
def generate_live_preview(
    video_path: Optional[str],
    out_img_path: str,
    enable_logo: bool = True,
    logo_path: Optional[str] = None,
    logo_position: str = "Top-Right",
    logo_width: int = 160,
    logo_opacity: float = 1.0,
    caption_preset: str = "CapCut Bold Yellow",
    caption_case: str = "ALL CAPS",
    caption_size: int = 58,
    sample_text: str = "CAPCUT VIRAL CAPTIONS POP",
    custom_logo_pos: Optional[Tuple[float, float]] = None,
    custom_caption_pos: Optional[Tuple[float, float]] = None
) -> bool:
    """
    Renders a single high-resolution preview frame with the exact logo watermark
    and CapCut styled text for instant visual inspection in GUI.
    """
    if not FFMPEG_PATH:
        return False

    os.makedirs(os.path.dirname(os.path.abspath(out_img_path)), exist_ok=True)
    temp_dir = tempfile.gettempdir()
    base_frame = os.path.join(temp_dir, f"prev_base_{int(time.time()*1000)}.jpg")

    # Step 1: Base Canvas
    if video_path and os.path.isfile(video_path):
        try:
            subprocess.run([
                FFMPEG_PATH, "-y",
                "-ss", "00:00:01",
                "-i", video_path,
                "-vframes", "1",
                "-s", "1080x1920",
                base_frame
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=STARTUPINFO, creationflags=CREATIONFLAGS, timeout=10)
        except Exception:
            pass

    if not os.path.isfile(base_frame):
        # Create stylish dark studio gradient canvas
        subprocess.run([
            FFMPEG_PATH, "-y",
            "-f", "lavfi",
            "-i", "color=c=0b1020:s=1080x1920:d=1",
            "-vframes", "1",
            base_frame
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=STARTUPINFO, creationflags=CREATIONFLAGS)

    # Step 2: Build Mini Preview ASS
    words_data = []
    text_words = sample_text.split()
    for idx_w, w in enumerate(text_words):
        words_data.append({
            "word": w,
            "start": idx_w * 0.4,
            "end": (idx_w + 1) * 0.4
        })

    preview_ass = os.path.join(temp_dir, f"preview_cap_{int(time.time()*1000)}.ass")
    build_capcut_ass(
        words=words_data,
        total_duration=3.0,
        out_ass_path=preview_ass,
        video_w=1080,
        video_h=1920,
        preset_name=caption_preset if caption_preset not in (RANDOM_PER_SCENE_KEY, RANDOM_PER_CHUNK_KEY) else "CapCut Bold Yellow",
        words_per_line=len(text_words),
        text_case=caption_case,
        font_size_override=caption_size,
        custom_caption_pos=custom_caption_pos,
        anti_shake=True
    )

    # Step 3: Burn on single frame
    safe_ass = os.path.abspath(preview_ass).replace("\\", "/").replace(":", "\\:")
    has_logo = enable_logo and logo_path and os.path.isfile(logo_path)

    if has_logo:
        if custom_logo_pos is not None:
            fx, fy = custom_logo_pos
            lx = max(0, min(1080 - logo_width, int(round(fx * 1080 - (logo_width / 2.0)))))
            ly = max(0, min(1920 - 20, int(round(fy * 1920 - (logo_width / 4.0)))))
            pos_expr = f"{lx}:{ly}"
        else:
            pos = logo_position.lower()
            if "top-left" in pos: pos_expr = "40:40"
            elif "bottom-right" in pos: pos_expr = "W-w-40:H-h-40"
            elif "bottom-left" in pos: pos_expr = "40:H-h-40"
            elif "top-center" in pos: pos_expr = "(W-w)/2:40"
            elif "bottom-center" in pos: pos_expr = "(W-w)/2:H-h-40"
            elif "center" in pos: pos_expr = "(W-w)/2:(H-h)/2"
            else: pos_expr = "W-w-40:40"

        filter_str = (
            f"[1:v]format=rgba,colorchannelmixer=aa={logo_opacity:.2f},scale={logo_width}:-1[scaled_logo];"
            f"[0:v][scaled_logo]overlay={pos_expr}[v_logo];"
            f"[v_logo]subtitles='{safe_ass}'[v_out]"
        )
        cmd = [
            FFMPEG_PATH, "-y",
            "-i", base_frame,
            "-i", logo_path,
            "-filter_complex", filter_str,
            "-map", "[v_out]",
            "-vframes", "1",
            out_img_path
        ]
    else:
        cmd = [
            FFMPEG_PATH, "-y",
            "-i", base_frame,
            "-vf", f"subtitles='{safe_ass}'",
            "-vframes", "1",
            out_img_path
        ]

    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=STARTUPINFO, creationflags=CREATIONFLAGS)

    # Cleanup temp
    for tf in [base_frame, preview_ass]:
        try:
            if os.path.isfile(tf): os.remove(tf)
        except Exception:
            pass

    return os.path.isfile(out_img_path)
