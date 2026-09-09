# tabs/story_video_editor.py
"""
Story Video Editor — Tab module for All In One Tool
Original: AI Video Studio v10.0 → v11.0 (GPU Accelerated + All Fixes)
Converted for tab-based launcher.
"""

# ════════════════════════════════════════════════════════════════
# TAB METADATA (required by launcher)
# ════════════════════════════════════════════════════════════════
TITLE    = "Story Video Editor"
SUBTITLE = "AI Story Generator • Multi-Voice • GPU Accelerated"
ICON     = "🎬"
ACCENT   = "#bc8cff"

REQUIREMENTS = [
    ("customtkinter", "customtkinter"),
    ("Pillow",        "PIL"),
    ("requests",      "requests"),
    ("pygame",        "pygame"),
    ("opencv-python", "cv2"),
    ("numpy",         "numpy"),
]

# ════════════════════════════════════════════════════════════════
# IMPORTS
# ════════════════════════════════════════════════════════════════
import os, re, json, math, threading, subprocess, shutil, sys, hashlib, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import lazy_menu  # Win32 / TCL native menu limit fix
import customtkinter as ctk
from tkinter import filedialog, messagebox, Canvas, colorchooser
from PIL import Image, ImageTk, ImageDraw
import requests
import preset_manager

# Whiteboard animation feature needs OpenCV + NumPy (optional — feature disables if missing)
try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except Exception as _cv_err:
    HAS_CV2 = False
    print(f"[WARN] OpenCV/NumPy not available — Whiteboard animation disabled: {_cv_err}")

try:
    import pygame
    # pre_init BEFORE init for best chance of working across platforms (Win/Mac/Linux).
    # 44100 Hz, signed 16-bit, stereo, 512 sample buffer — matches what we extract.
    try: pygame.mixer.pre_init(44100, -16, 2, 512)
    except: pass
    pygame.mixer.init()
    # Verify it actually initialised — get_init returns None if it didn't.
    HAS_PYGAME = pygame.mixer.get_init() is not None
    if not HAS_PYGAME:
        print("[WARN] pygame.mixer initialised but get_init() returned None — audio playback disabled.")
except Exception as _pg_err:
    HAS_PYGAME = False
    print(f"[WARN] pygame import / init failed — audio in preview disabled: {_pg_err}")

def _run_ff(cmd, timeout=300):
    """Safe subprocess runner for ffmpeg — handles Windows encoding issues."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace")
    except TypeError:
        return subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None

# ════════════════════════════════════════════════════════════════
# PATHS & CONSTANTS
# ════════════════════════════════════════════════════════════════
SCRIPT_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "StoriesStudio"
TEMP_DIR   = str(SCRIPT_DIR / "temp_work" / "story_video_editor")
OUTPUT_DIR = str(SCRIPT_DIR / "output" / "story_video_editor")
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

SETTINGS_FILE  = os.path.join(TEMP_DIR, "app_settings.json")
TTS_CACHE_FILE = os.path.join(TEMP_DIR, "tts_cache.json")

MAX_PARALLEL_TTS = 3
MAX_PARALLEL_FF  = 4

VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".tif")
MEDIA_EXTS = VIDEO_EXTS + IMAGE_EXTS

C = {
    "bg": "#0d1117", "card": "#161b22", "border": "#30363d",
    "text": "#e6edf3", "dim": "#8b949e", "accent": "#58a6ff",
    "green": "#3fb950", "red": "#f85149", "orange": "#d29922",
    "purple": "#bc8cff", "btn": "#21262d", "btn_hov": "#30363d",
    "entry_bg": "#0d1117",
    "side_bg": "#161b22", "main_bg": "#0d1117",
    "toolbar_bg": "#161b22", "card_bg": "#1c2333",
    "accent_hov": "#4090e0",
}

CHAR_COLORS = [
    {"bg": "#1a2744", "border": "#58a6ff", "accent": "#58a6ff"},
    {"bg": "#1a3a1a", "border": "#3fb950", "accent": "#3fb950"},
    {"bg": "#3a1a2e", "border": "#f778ba", "accent": "#f778ba"},
    {"bg": "#3a2a1a", "border": "#d29922", "accent": "#d29922"},
    {"bg": "#2a1a3a", "border": "#bc8cff", "accent": "#bc8cff"},
    {"bg": "#1a3a3a", "border": "#56d4dd", "accent": "#56d4dd"},
    {"bg": "#3a1a1a", "border": "#f85149", "accent": "#f85149"},
    {"bg": "#2a2a1a", "border": "#e3b341", "accent": "#e3b341"},
    {"bg": "#1a2a2a", "border": "#39d353", "accent": "#39d353"},
    {"bg": "#2a1a2a", "border": "#db61a2", "accent": "#db61a2"},
]


# ════════════════════════════════════════════════════════════════
# ════════════════════════════════════════════════════════════════
# GPU AUTO-DETECT & ENCODER CONFIG (Instant cached singleton)
# ════════════════════════════════════════════════════════════════

import hardware_accel
GPUConfig = hardware_accel.MasterGPUConfig
GPU = hardware_accel.MasterGPUConfig()

# ════════════════════════════════════════════════════════════════
# OUTPUT RESOLUTION / QUALITY  (1K / 2K / 4K) — applied to the final
# render of EVERY tab. Pipeline renders at 1080p, then the finished file
# is scaled to the chosen resolution with high-quality (lanczos) scaling
# + light sharpening + the encoder's quality setting.
# ════════════════════════════════════════════════════════════════
_OUTPUT_PRESETS = {
    "1K (1080p)": (1920, 1080),
    "2K (1440p)": (2560, 1440),
    "4K (2160p)": (3840, 2160),
}
_OUTPUT_RES_CHOICE = "1K (1080p)"
_RES_CFG = os.path.join(os.path.expanduser("~"), ".vm_output_res.json")

def _load_output_res():
    global _OUTPUT_RES_CHOICE
    try:
        with open(_RES_CFG, "r", encoding="utf-8") as f:
            v = json.load(f).get("res", "")
            if v in _OUTPUT_PRESETS:
                _OUTPUT_RES_CHOICE = v
    except Exception:
        pass

def _set_output_res(v):
    global _OUTPUT_RES_CHOICE
    if v in _OUTPUT_PRESETS:
        _OUTPUT_RES_CHOICE = v
        try:
            with open(_RES_CFG, "w", encoding="utf-8") as f:
                json.dump({"res": v}, f)
        except Exception:
            pass

def _finalize_output_resolution(path, res_key=None, log=None):
    """Scale the finished video up to the chosen output resolution. 1K = native
    (no change). Uses lanczos + a touch of sharpening + the encoder quality preset."""
    res_key = res_key or _OUTPUT_RES_CHOICE
    pr = _OUTPUT_PRESETS.get(res_key)
    if not pr or "1K" in res_key:
        return False
    w, h = pr
    if not (path and os.path.exists(path)):
        return False
    try:
        cw, ch = get_resolution(path)
    except Exception:
        cw, ch = 0, 0
    if cw >= w and ch >= h:
        return False  # already at/above target
    if log:
        try: log(f"Rendering {res_key} output…")
        except Exception: pass
    tmp = path + ".upres.mp4"
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,unsharp=5:5:0.6:5:5:0.0")
    cmd = (["ffmpeg", "-y", "-i", path, "-vf", vf] + GPU.enc_args("fast") +
           ["-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", "-loglevel", "error", tmp])
    _run_ff(cmd, timeout=10800)
    if os.path.exists(tmp) and get_duration(tmp) > 0.1:
        try:
            shutil.move(tmp, path); return True
        except Exception:
            try:
                shutil.copy2(tmp, path); os.remove(tmp); return True
            except Exception:
                return False
    try:
        if os.path.exists(tmp): os.remove(tmp)
    except Exception:
        pass
    return False

_load_output_res()


# ════════════════════════════════════════════════════════════════
# SETTINGS MANAGER
# ════════════════════════════════════════════════════════════════
class SettingsManager:
    DEFAULTS = {
        "api_key": "", "last_model": "", "last_voice": "",
        "silence_pad": 0.0, "render_mode": "direct", "loop_count": 2,
        "intro_videos": [],
        "bgm_path": "", "bgm_volume": 0.15, "bgm_duck": True, "bgm_fade": 2.0, "bgm_loop": True,
        "bgm_xfade": True, "bgm_prompt": "", "bgm_gen_dur": 30,
        "bgm_mode": "single", "bgm_multi_entries": [],
        "logo_enabled": True, "logo_path": "",
        "logo_size": 80, "logo_opacity": 100,
        "logo_anchor": "top-left", "logo_margin_x": 20, "logo_margin_y": 20,
        "logo_pos_x": 20, "logo_pos_y": 20,
        "filler_video": "",
        "crop_right_px": 151, "crop_bottom_px": 151, "auto_crop_enabled": False,
        "use_intro": True, "use_bgm": True, "use_logo": True,
        "audio_source": "elevenlabs",
        "window_geometry": "1280x720",
        "last_upload_dir": "", "last_save_dir": "",
        "default_zoom_speed": 0.0015,
        "use_transition": False, "transition_duration": 0.5,
        "use_chroma_overlay": False, "chroma_overlay_path": "",
        "chroma_color": "green", "chroma_custom_hex": "00FF00",
        "chroma_similarity": 0.3, "chroma_blend": 0.05,
        "use_ticker": False, "ticker_text": "",
        "ticker_bar_color": "000000", "ticker_bar_opacity": 0.75,
        "ticker_bar_height": 50, "ticker_text_color": "FFFFFF",
        "ticker_font_size": 30, "ticker_speed": 80,
        "ticker_label_text": "BREAKING", "ticker_label_bg": "CC0000",
        "ticker_label_show": True,
        "common_voice_name": "", "common_voice_id": "",
        "master_volume": 100,
        "master_tts_volume": 100,
        # ── Captions ──
        "captions_enabled": False,
        "caption_font_path": "",
        "caption_font_size": 48,
        "caption_font_color": "FFFFFF",
        "caption_bg_color": "000000",
        "caption_bg_opacity": 0.6,
        "caption_max_chars": 35,
        "caption_max_lines": 2,
        "caption_position": "bottom",
        "caption_margin_bottom": 80,
        "caption_animation": "fade",
        "caption_words_per_group": 4,
        "blend_text_enabled": False, "blend_text_font_path": "", "blend_text_font_size": 60,
        "blend_text_font_color": "FFFFFF", "blend_text_bg_color": "000000", "blend_text_bg_opacity": 0.0,
        "blend_text_position": "center", "blend_text_margin": 50, "blend_text_animation": "fade",
        "blend_text_align": "center", "blend_text_border_w": 2, "blend_text_border_color": "000000",
        "blend_text_shadow": True,
        # ── Blend Video (green-screen lower-third overlay) + SFX ──
        "blend_video_enabled": False,
        "blend_video_key_color": "00FF00",   # default green
        "blend_video_similarity": 0.30,
        "blend_video_blend": 0.10,
        "blend_sfx_volume": 1.0,
        "blend_sfx_duration": 4.0,
        # ── Shorts (9:16) tab ──
        "shorts_thumbnail_enabled": False,
        "shorts_thumbnail_path": "",
        "shorts_thumbnail_duration": 2.0,
        # ── Whiteboard animation (Video Master) ──
        "wb_on": False,
        "wb_freeze": 2.5,
        "wb_hand": "",
        # ── Story Video tab ──
        "story_fx": "None",
        "story_cap_on": False,
        "story_cap_style": "Karaoke Pop",
        "story_cap_karaoke": True,
        "story_cap_maxwords": 10,
        "story_cap_caps": "UPPERCASE",
        "story_cap_size": "",
        "story_cap_primary": "",
        "story_cap_highlight": "",
        "story_cap_box": False,
        "story_cap_boxcolor": "#000000",
        "story_cap_active": "#FFFFFF",
        "story_cap_opacity": 90,
        "story_cap_mode": "box",
        "story_cap_px": 0.5,
        "story_cap_py": 0.80,
        "story_cap_font": "",
        "story_intro_videos": [],
        "story_intro_on": True,
        "story_motion": "Zoom In-Out",
        "story_motion_speed": 100,
        "health_intro1": [],
        "health_intro2": [],
        "health_vc_on": False,
        "health_vc_rmbg": True,
        "health_vc_voice": "",
        "disc_vc_on": False,
        "disc_vc_rmbg": True,
        "disc_vc_voice": "",
        "health_keepbg": True,
        "disc_keepbg": True,
        "disc_narr_on": True,
        "disc_clipvol": 100,
        "disc_mute": False,
    }
    def __init__(self):
        self.data = self._load_from_file()
    def _load_from_file(self):
        d = dict(self.DEFAULTS)
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                for k, v in saved.items():
                    if k in d: d[k] = v
            except Exception: pass
        return d
    def get(self, key): return self.data.get(key, self.DEFAULTS.get(key, ""))
    def set(self, key, value): self.data[key] = value
    def save(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception: pass
    @classmethod
    def load(cls):
        d = dict(cls.DEFAULTS)
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                for k, v in saved.items():
                    if k in d: d[k] = v
            except Exception: pass
        return d
    @classmethod
    def class_save(cls, data):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception: pass


# ════════════════════════════════════════════════════════════════
# TTS CACHE
# ════════════════════════════════════════════════════════════════
class TTSCache:
    _lock = threading.Lock()
    @classmethod
    def _hash(cls, text): return hashlib.md5(text.strip().encode("utf-8")).hexdigest()
    @classmethod
    def load(cls):
        try:
            if os.path.exists(TTS_CACHE_FILE):
                with open(TTS_CACHE_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: pass
        return {}
    @classmethod
    def save(cls, cache):
        with cls._lock:
            try:
                with open(TTS_CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(cache, f, indent=2, ensure_ascii=False)
            except: pass
    @classmethod
    def get_cached_audio(cls, scene_num, text):
        cache = cls.load(); key = str(scene_num); entry = cache.get(key)
        if not entry: return None
        if entry.get("text_hash") != cls._hash(text): return None
        audio = entry.get("audio_path", "")
        if audio and os.path.exists(audio) and get_duration(audio) > 0.1: return audio
        return None
    @classmethod
    def store(cls, scene_num, text, audio_path):
        cache = cls.load()
        cache[str(scene_num)] = {"text_hash": cls._hash(text), "audio_path": audio_path}
        cls.save(cache)
    @classmethod
    def clear_all(cls):
        """Clear entire TTS cache."""
        with cls._lock:
            try:
                if os.path.exists(TTS_CACHE_FILE): os.remove(TTS_CACHE_FILE)
            except: pass
# ════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS (All GPU-accelerated via GPUConfig)
# ════════════════════════════════════════════════════════════════
def _show_tab_help(title, steps):
    try:
        w=ctk.CTkToplevel(); w.title("Help: "+title); w.geometry("580x500")
        w.configure(fg_color="#0f1115"); w.attributes("-topmost", True)
        ctk.CTkLabel(w, text=title, font=("Segoe UI",18,"bold"), text_color="#f2a33c").pack(pady=(14,4))
        tb=ctk.CTkTextbox(w, fg_color="#11141a", text_color="#e8eaed", border_color="#2a2f3a",
                          border_width=1, font=("Consolas",11), wrap="word")
        tb.pack(fill="both", expand=True, padx=14, pady=(4,6))
        for i,st in enumerate(steps,1): tb.insert("end", "\n  STEP "+str(i)+":  "+st+"\n")
        tb.insert("end", "\n  Done!\n")
        tb.configure(state="disabled")
        ctk.CTkButton(w, text="Close", width=120, fg_color="#262b36", text_color="#e8eaed",
                      command=w.destroy).pack(pady=(0,10))
    except Exception as e: print("[HELP]", e)

def is_image_file(path): return os.path.splitext(path)[1].lower() in IMAGE_EXTS
def is_video_file(path): return os.path.splitext(path)[1].lower() in VIDEO_EXTS

def calc_logo_xy(anchor, mx, my, sz, vw, vh):
    """Calculate logo XY position based on anchor and margin (pixels)."""
    if anchor == "top-left":     return (mx, my)
    if anchor == "top-right":    return (vw - sz - mx, my)
    if anchor == "bottom-left":  return (mx, vh - sz - my)
    if anchor == "bottom-right": return (vw - sz - mx, vh - sz - my)
    if anchor == "center":       return ((vw - sz) // 2 + mx, (vh - sz) // 2 + my)
    return (mx, my)

_DURATION_CACHE = {}  # Cache: {path: duration} to avoid re-ffprobing
_RESOLUTION_CACHE = {}  # Cache: {path: (w, h)}

def get_duration(path):
    """Get video duration. Cached to avoid repeated ffprobe calls."""
    if path in _DURATION_CACHE:
        return _DURATION_CACHE[path]
    try:
        r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
            "-of","default=noprint_wrappers=1:nokey=1",path], capture_output=True, text=True, timeout=15)
        dur = float(r.stdout.strip())
        _DURATION_CACHE[path] = dur  # Cache it
        return dur
    except:
        return 0.0

def get_resolution(path):
    """Get video resolution. Cached to avoid repeated ffprobe calls."""
    if path in _RESOLUTION_CACHE:
        return _RESOLUTION_CACHE[path]
    try:
        r = subprocess.run(["ffprobe","-v","error","-select_streams","v:0",
            "-show_entries","stream=width,height","-of","csv=s=x:p=0",path],
            capture_output=True, text=True, timeout=15)
        w, h = r.stdout.strip().split("x")
        res = (int(w), int(h))
        _RESOLUTION_CACHE[path] = res  # Cache it
        return res
    except:
        return 1920, 1080

def get_image_resolution(path):
    try: img = Image.open(path); return img.size
    except: return 1920, 1080

_frame_counter = 0
def extract_frame(video_path, at_sec=1.0):
    global _frame_counter
    _frame_counter += 1
    tmp = os.path.join(TEMP_DIR, f"_frm_{os.getpid()}_{_frame_counter}.png")
    try:
        # Try without GPU first (most reliable for single frame extraction)
        cmd = ["ffmpeg","-y","-ss",str(at_sec),"-i",video_path,"-frames:v","1","-q:v","2",tmp]
        subprocess.run(cmd, capture_output=True, timeout=15)
        if os.path.exists(tmp) and os.path.getsize(tmp) > 100:
            img = Image.open(tmp).convert("RGBA")
            try: os.remove(tmp)
            except: pass
            return img
        # Fallback with hwaccel
        if GPU.gpu_vendor != "none":
            cmd2 = ["ffmpeg","-y"]
            if GPU.gpu_vendor == "nvidia":
                cmd2 += ["-hwaccel", "cuda"]
            else:
                cmd2 += GPU.dec_args()
            cmd2 += ["-ss",str(at_sec),"-i",video_path,"-frames:v","1","-q:v","2",tmp]
            subprocess.run(cmd2, capture_output=True, timeout=15)
            if os.path.exists(tmp) and os.path.getsize(tmp) > 100:
                img = Image.open(tmp).convert("RGBA")
                try: os.remove(tmp)
                except: pass
                return img
    except: pass
    return Image.new("RGBA", (1920, 1080), (0, 0, 0, 255))

def extract_last_frame(video_path):
    tmp = os.path.join(TEMP_DIR, f"_lastfrm_{os.getpid()}_{threading.current_thread().ident}.png")
    try:
        subprocess.run(["ffmpeg","-y","-sseof","-1","-i",video_path,"-update","1","-q:v","2",tmp],
            capture_output=True, timeout=30)
        if os.path.exists(tmp) and os.path.getsize(tmp) > 100: return tmp
        dur = get_duration(video_path)
        if dur > 0.1:
            subprocess.run(["ffmpeg","-y","-ss",str(max(0,dur-0.1)),"-i",video_path,
                "-frames:v","1","-q:v","2",tmp], capture_output=True, timeout=30)
            if os.path.exists(tmp) and os.path.getsize(tmp) > 100: return tmp
    except: pass
    return None

def generate_black_video(dur=5.0, w=1920, h=1080, output=None):
    if not output: output = os.path.join(TEMP_DIR, "black_filler.mp4")
    cmd = ["ffmpeg","-y","-f","lavfi","-i",f"color=c=black:s={w}x{h}:d={dur}:r=30",
        "-f","lavfi","-i","anullsrc=r=44100:cl=stereo","-t",str(dur)]
    cmd += GPU.enc_args("ultrafast")
    cmd += ["-c:a","aac","-shortest",output]
    subprocess.run(cmd, capture_output=True, timeout=60)
    return output if os.path.exists(output) else None

def has_audio_stream(path):
    try:
        r = subprocess.run(["ffprobe","-v","error","-select_streams","a:0",
            "-show_entries","stream=codec_type","-of","default=noprint_wrappers=1:nokey=1",path],
            capture_output=True, text=True, timeout=15)
        return bool(r.stdout.strip())
    except: return False

# ════════════════════════════════════════════════════════════════
# WHITEBOARD ANIMATION  (left→right hand-sketch reveal for images)
# ════════════════════════════════════════════════════════════════
def _wb_make_hand(size=420):
    """Default stylized hand+pen (BGRA). Returns (hand_bgra, tip_xy)."""
    S = size
    h = np.zeros((S, S, 4), dtype=np.uint8)
    skin = (175, 200, 232); skin_sh = (150, 175, 210); outline = (90, 110, 140)
    tip = (int(S*0.09), int(S*0.09)); grip = (int(S*0.50), int(S*0.50)); top = (int(S*0.66), int(S*0.64))
    cv2.line(h, tip, top, (55, 55, 60, 255), int(S*0.05), cv2.LINE_AA)
    cv2.line(h, tip, (int(tip[0]+(grip[0]-tip[0])*0.14), int(tip[1]+(grip[1]-tip[1])*0.14)),
             (25, 25, 25, 255), int(S*0.028), cv2.LINE_AA)
    poly = np.array([[S*0.40,S*0.52],[S*0.55,S*0.44],[S*0.72,S*0.50],[S*0.86,S*0.62],
                     [S*0.95,S*0.80],[S*0.98,S*0.99],[S*0.70,S*0.99],[S*0.55,S*0.86],
                     [S*0.44,S*0.70]], dtype=np.int32)
    cv2.fillConvexPoly(h, poly, (*skin, 255), cv2.LINE_AA)
    cv2.polylines(h, [poly], True, (*outline, 255), max(1, int(S*0.006)), cv2.LINE_AA)
    cv2.ellipse(h, (int(S*0.46),int(S*0.54)), (int(S*0.11),int(S*0.05)), 30,0,360,(*skin,255),-1,cv2.LINE_AA)
    cv2.ellipse(h, (int(S*0.55),int(S*0.49)), (int(S*0.09),int(S*0.042)),-8,0,360,(*skin_sh,255),-1,cv2.LINE_AA)
    cv2.ellipse(h, (int(S*0.62),int(S*0.60)), (int(S*0.05),int(S*0.05)),  0,0,360,(*skin_sh,255),-1,cv2.LINE_AA)
    return h, tip


def _wb_load_hand(path):
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        return None, None
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    if img.shape[2] == 3:
        b, g, r = cv2.split(img)
        a = np.where((b > 245) & (g > 245) & (r > 245), 0, 255).astype(np.uint8)
        img = cv2.merge([b, g, r, a])
    ys, xs = np.where(img[:, :, 3] > 10)
    tip = (int(xs.min()), int(ys.min())) if len(xs) else (0, 0)
    return img, tip


def _wb_paste(bg, fg, tip_xy, draw_xy):
    """Alpha-paste fg (BGRA) so its tip sits at draw_xy on bg (BGR)."""
    fh, fw = fg.shape[:2]
    x0 = int(draw_xy[0] - tip_xy[0]); y0 = int(draw_xy[1] - tip_xy[1])
    bx0, by0 = max(0, x0), max(0, y0)
    bx1, by1 = min(bg.shape[1], x0+fw), min(bg.shape[0], y0+fh)
    if bx0 >= bx1 or by0 >= by1:
        return
    fx0, fy0 = bx0-x0, by0-y0
    roi = bg[by0:by1, bx0:bx1].astype(np.float32)
    fc = fg[fy0:fy0+(by1-by0), fx0:fx0+(bx1-bx0)]
    a = fc[:, :, 3:4].astype(np.float32) / 255.0
    bg[by0:by1, bx0:bx1] = (roi*(1-a) + fc[:, :, :3].astype(np.float32)*a).astype(np.uint8)


def _wb_compose_canvas(img, out_w, out_h):
    """Fit + center image on a white out_w×out_h canvas."""
    canvas = np.full((out_h, out_w, 3), 255, dtype=np.uint8)
    h, w = img.shape[:2]
    s = min(out_w / w, out_h / h)
    nw, nh = max(1, int(w*s)), max(1, int(h*s))
    rim = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    ox, oy = (out_w-nw)//2, (out_h-nh)//2
    canvas[oy:oy+nh, ox:ox+nw] = rim
    return canvas


def _wb_fill_holes(mask):
    """Fill regions fully enclosed by the drawn outline (uint8 0/255 mask).
    Used so a shape colours in once the hand has closed its outline — no
    left-to-right wipe."""
    h, w = mask.shape
    ff = mask.copy()
    m2 = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(ff, m2, (0, 0), 255)     # flood the OUTSIDE from a corner
    holes = cv2.bitwise_not(ff)            # pixels the flood couldn't reach = holes
    return cv2.bitwise_or(mask, holes)


def image_to_whiteboard_video(image_path, total_duration, output_path,
                              freeze_tail=2.5, fps=30, out_w=1920, out_h=1080,
                              hand_path=None):
    """
    Image → LEFT→RIGHT hand-sketch whiteboard video (video only, no audio).

    Drawing is laid out so it COMPLETES ~freeze_tail seconds before total_duration,
    then the finished image FREEZES on screen for the remaining time. So a 10s scene
    draws for ~7.5s and holds the final frame for ~2.5s. Total = total_duration.

    Outlines are sketched left→right as stroke segments; colour fills pop region-by
    -region as the pen passes (not a vertical wipe). Returns output_path or None.
    """
    if not HAS_CV2:
        return None
    try:
        img = cv2.imread(image_path)
        if img is None:                       # webp/gif etc. → via PIL
            try:
                pil = Image.open(image_path).convert("RGB")
                img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
            except Exception:
                return None

        out_w -= out_w % 2; out_h -= out_h % 2
        canvas = _wb_compose_canvas(img, out_w, out_h)
        H, W = canvas.shape[:2]

        # ── timing: draw finishes freeze_tail before the end, then freeze ──
        total_frames = max(2, int(round(total_duration * fps)))
        freeze = max(0.0, min(float(freeze_tail), total_duration * 0.4))
        freeze_frames = int(round(freeze * fps))
        draw_frames = max(1, total_frames - freeze_frames)

        # ── hand overlay (auto-sized to ~30% of height) ──
        if hand_path and os.path.exists(hand_path):
            hand, tip = _wb_load_hand(hand_path)
        else:
            hand, tip = None, None
        if hand is None:
            hand, tip = _wb_make_hand(int(min(W, H) * 0.5) or 200)
        hs = float(np.clip((H * 0.30) / max(1, hand.shape[0]), 0.05, 4.0))
        hand = cv2.resize(hand, None, fx=hs, fy=hs, interpolation=cv2.INTER_AREA)
        tip = (int(tip[0]*hs), int(tip[1]*hs))

        # ── TRACE strokes: the pen follows the actual ink outlines (like a hand),
        #    NOT a left→right frontier. Each enclosed region colours in only once its
        #    outline has been closed by the pen — so there is NO white layer/curtain
        #    sweeping across; the picture appears where the hand is drawing. ──
        gray = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
        _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        cnts, _ = cv2.findContours(ink, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        strokes = [c[:, 0, :] for c in cnts if len(c) >= 2]

        dt = cv2.distanceTransform(ink, cv2.DIST_L2, 3)
        dv = dt[dt > 0]
        bw = int(max(2, (np.median(dv) * 2 if dv.size else 2))) + max(1, int(H * 0.004))

        # order strokes for natural continuous movement (nearest-neighbour between
        # shape centroids from the top-left); cheap sort if there are too many.
        if strokes:
            cents = np.array([[float(s[:, 0].mean()), float(s[:, 1].mean())] for s in strokes])
            if len(strokes) <= 1500:
                order = []; used = np.zeros(len(strokes), bool)
                cur = int(np.argmin(cents[:, 0] + cents[:, 1]))
                for _ in range(len(strokes)):
                    order.append(cur); used[cur] = True
                    d = np.sum((cents - cents[cur]) ** 2, axis=1); d[used] = np.inf
                    nxt = int(np.argmin(d))
                    if used[nxt]:
                        break
                    cur = nxt
                for i in range(len(strokes)):
                    if not used[i]:
                        order.append(i)
                strokes = [strokes[i] for i in order]
            else:
                strokes.sort(key=lambda s: (int(s[:, 1].mean()) // max(8, H // 60),
                                            int(s[:, 0].mean())))

        total_pts = sum(len(s) for s in strokes)
        kclose = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                           (max(3, bw + 2), max(3, bw + 2)))

        # ── ffmpeg pipe (raw BGR frames → mp4, video only) ──
        cmd = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
               "-s", f"{W}x{H}", "-r", str(fps), "-i", "-"]
        try:
            cmd += GPU.enc_args("veryfast")
        except Exception:
            cmd += ["-c:v", "libx264", "-preset", "veryfast"]
        cmd += ["-pix_fmt", "yuv420p", "-an", "-loglevel", "error", output_path]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

        if not strokes or total_pts < 2:
            for _ in range(total_frames):
                proc.stdin.write(canvas.tobytes())
        else:
            drawn = np.zeros((H, W), np.uint8)
            pen = (int(strokes[0][0, 0]), int(strokes[0][0, 1]))
            si = 0; pj = 0; done_pts = 0
            for f in range(draw_frames):
                target = int(round((f + 1) / draw_frames * total_pts))
                while done_pts < target and si < len(strokes):
                    s = strokes[si]
                    step = min(len(s) - pj, target - done_pts)
                    if step <= 0:
                        si += 1; pj = 0; continue
                    seg = s[max(0, pj - 1): pj + step]
                    if len(seg) >= 2:
                        cv2.polylines(drawn, [seg.reshape(-1, 1, 2)], False, 255, bw)
                    else:
                        cv2.circle(drawn, (int(seg[0, 0]), int(seg[0, 1])), max(1, bw // 2), 255, -1)
                    pen = (int(s[pj + step - 1, 0]), int(s[pj + step - 1, 1]))
                    pj += step; done_pts += step
                    if pj >= len(s):
                        si += 1; pj = 0
                # reveal: drawn linework + any regions whose outline is now closed
                closed = cv2.dilate(drawn, kclose)
                reveal = (_wb_fill_holes(closed) > 0) | (drawn > 0)
                frame = np.full_like(canvas, 255)
                frame[reveal] = canvas[reveal]
                _wb_paste(frame, hand, tip, pen)
                proc.stdin.write(frame.tobytes())
            # freeze: completed image, no hand
            for _ in range(total_frames - draw_frames):
                proc.stdin.write(canvas.tobytes())

        proc.stdin.close(); proc.wait()
        if os.path.exists(output_path) and get_duration(output_path) > 0.1:
            return output_path
    except Exception as e:
        print(f"image_to_whiteboard_video error: {e}")
    return None


def image_to_raindrop_reveal_video(image_path, total_duration, output_path,
                                   freeze_tail=2.5, fps=30, out_w=1920, out_h=1080):
    """
    Image → Raindrop splash & expanding water ripple reveal animation.
    Rain droplets fall and create expanding ripples that uncover the image.
    """
    if not HAS_CV2:
        return None
    try:
        img = cv2.imread(image_path)
        if img is None:
            try:
                pil = Image.open(image_path).convert("RGB")
                img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
            except Exception:
                return None

        out_w -= out_w % 2; out_h -= out_h % 2
        canvas = _wb_compose_canvas(img, out_w, out_h)
        H, W = canvas.shape[:2]

        total_frames = max(2, int(round(total_duration * fps)))
        freeze = max(0.0, min(float(freeze_tail), total_duration * 0.4))
        freeze_frames = int(round(freeze * fps))
        draw_frames = max(1, total_frames - freeze_frames)

        # Pre-generate raindrops with start frame, (x, y), max_radius, and speed
        import random
        rng = random.Random(42)
        num_drops = int(max(40, (W * H) // 25000))
        drops = []
        for _ in range(num_drops):
            st_f = rng.randint(0, max(0, int(draw_frames * 0.75)))
            cx = rng.randint(0, W)
            cy = rng.randint(0, H)
            max_r = rng.randint(int(min(W, H) * 0.25), int(min(W, H) * 0.65))
            growth_rate = rng.uniform(3.5, 9.0)
            drops.append({"st": st_f, "cx": cx, "cy": cy, "max_r": max_r, "rate": growth_rate})

        cmd = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
               "-s", f"{W}x{H}", "-r", str(fps), "-i", "-"]
        try:
            cmd += GPU.enc_args("veryfast")
        except Exception:
            cmd += ["-c:v", "libx264", "-preset", "veryfast"]
        cmd += ["-pix_fmt", "yuv420p", "-an", "-loglevel", "error", output_path]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

        dark_canvas = (canvas.astype(np.float32) * 0.05).astype(np.uint8)

        for f in range(draw_frames):
            prog = f / float(draw_frames)
            # Create reveal mask from cumulative ripples
            mask = np.zeros((H, W), dtype=np.uint8)
            for d in drops:
                if f >= d["st"]:
                    cur_r = int((f - d["st"]) * d["rate"])
                    cur_r = min(cur_r, d["max_r"])
                    if cur_r > 0:
                        cv2.circle(mask, (d["cx"], d["cy"]), cur_r, 255, -1)
            
            # Smooth blur the mask for soft water blending
            if f > 0:
                mask = cv2.GaussianBlur(mask, (31, 31), 0)
                # Boost global progress so 100% is unveiled cleanly at draw_frames
                if prog > 0.6:
                    boost = int((prog - 0.6) / 0.4 * 255)
                    mask = np.clip(mask.astype(np.int16) + boost, 0, 255).astype(np.uint8)

            alpha = (mask.astype(np.float32) / 255.0)[:, :, np.newaxis]
            frame = (canvas.astype(np.float32) * alpha + dark_canvas.astype(np.float32) * (1.0 - alpha)).astype(np.uint8)

            # Draw active rain droplet rings & streaks
            for d in drops:
                if f >= d["st"] and (f - d["st"]) < 18:
                    age = f - d["st"]
                    ring_r = int(age * d["rate"])
                    ring_alpha = max(0.0, 1.0 - (age / 18.0))
                    if ring_r > 2:
                        overlay = frame.copy()
                        cv2.circle(overlay, (d["cx"], d["cy"]), ring_r, (255, 240, 200), 2, cv2.LINE_AA)
                        cv2.circle(overlay, (d["cx"], d["cy"]), max(1, ring_r - 4), (200, 220, 255), 1, cv2.LINE_AA)
                        frame = cv2.addWeighted(overlay, ring_alpha * 0.7, frame, 1.0 - ring_alpha * 0.7, 0)

            proc.stdin.write(frame.tobytes())

        for _ in range(total_frames - draw_frames):
            proc.stdin.write(canvas.tobytes())

        proc.stdin.close(); proc.wait()
        if os.path.exists(output_path) and get_duration(output_path) > 0.1:
            return output_path
    except Exception as e:
        print(f"image_to_raindrop_reveal_video error: {e}")
    return None


def image_to_blooddrop_reveal_video(image_path, total_duration, output_path,
                                    freeze_tail=2.5, fps=30, out_w=1920, out_h=1080):
    """
    Image → Visceral dripping blood & dark ink reveal animation.
    Streams and splatters of crimson flow across the frame to unveil the artwork.
    """
    if not HAS_CV2:
        return None
    try:
        img = cv2.imread(image_path)
        if img is None:
            try:
                pil = Image.open(image_path).convert("RGB")
                img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
            except Exception:
                return None

        out_w -= out_w % 2; out_h -= out_h % 2
        canvas = _wb_compose_canvas(img, out_w, out_h)
        H, W = canvas.shape[:2]

        total_frames = max(2, int(round(total_duration * fps)))
        freeze = max(0.0, min(float(freeze_tail), total_duration * 0.4))
        freeze_frames = int(round(freeze * fps))
        draw_frames = max(1, total_frames - freeze_frames)

        import random
        rng = random.Random(101)
        num_drips = int(max(25, W // 45))
        drips = []
        for i in range(num_drips):
            sx = int(i * (W / float(num_drips))) + rng.randint(-15, 15)
            st_f = rng.randint(0, max(0, int(draw_frames * 0.4)))
            speed = rng.uniform(float(H) / (draw_frames * 0.65), float(H) / (draw_frames * 0.35))
            thickness = rng.randint(18, 55)
            drips.append({"sx": sx, "st": st_f, "speed": speed, "th": thickness})

        cmd = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
               "-s", f"{W}x{H}", "-r", str(fps), "-i", "-"]
        try:
            cmd += GPU.enc_args("veryfast")
        except Exception:
            cmd += ["-c:v", "libx264", "-preset", "veryfast"]
        cmd += ["-pix_fmt", "yuv420p", "-an", "-loglevel", "error", output_path]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

        dark_bg = np.zeros_like(canvas)

        for f in range(draw_frames):
            prog = f / float(draw_frames)
            mask = np.zeros((H, W), dtype=np.uint8)
            
            for d in drips:
                if f >= d["st"]:
                    cur_len = int((f - d["st"]) * d["speed"])
                    cur_len = min(H + 50, cur_len)
                    x = d["sx"]
                    w_r = int(d["th"] * (1.0 + 0.8 * (cur_len / float(H))))
                    # Draw drip trail + head bulb
                    cv2.line(mask, (x, 0), (x, cur_len), 255, w_r)
                    cv2.circle(mask, (x, min(H - 1, cur_len)), int(w_r * 1.3), 255, -1)
            
            # Dilate & expand to connect drips
            if prog > 0.3:
                k_sz = max(3, int((prog - 0.3) / 0.7 * 80))
                if k_sz % 2 == 0: k_sz += 1
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_sz, k_sz))
                mask = cv2.dilate(mask, kernel)

            mask = cv2.GaussianBlur(mask, (25, 25), 0)
            if prog > 0.75:
                boost = int((prog - 0.75) / 0.25 * 255)
                mask = np.clip(mask.astype(np.int16) + boost, 0, 255).astype(np.uint8)

            alpha = (mask.astype(np.float32) / 255.0)[:, :, np.newaxis]
            frame = (canvas.astype(np.float32) * alpha + dark_bg.astype(np.float32) * (1.0 - alpha)).astype(np.uint8)

            # Add crimson / blood red glow on the edge of the reveal
            edge = cv2.Canny(mask, 50, 180)
            if np.any(edge > 0):
                edge_dil = cv2.dilate(edge, np.ones((7, 7), np.uint8))
                edge_alpha = (edge_dil.astype(np.float32) / 255.0)[:, :, np.newaxis] * 0.75 * (1.0 - prog)
                blood_color = np.array([20, 10, 180], dtype=np.uint8) # BGR deep crimson
                frame = (frame.astype(np.float32) * (1.0 - edge_alpha) + blood_color * edge_alpha).astype(np.uint8)

            proc.stdin.write(frame.tobytes())

        for _ in range(total_frames - draw_frames):
            proc.stdin.write(canvas.tobytes())

        proc.stdin.close(); proc.wait()
        if os.path.exists(output_path) and get_duration(output_path) > 0.1:
            return output_path
    except Exception as e:
        print(f"image_to_blooddrop_reveal_video error: {e}")
    return None


def image_to_paper_burn_reveal_video(image_path, total_duration, output_path,
                                     freeze_tail=2.5, fps=30, out_w=1920, out_h=1080):
    """
    Image → Fire Paper Burn Reveal animation.
    Burning fiery embers incinerate a charred parchment overlay outward to unveil the image.
    """
    if not HAS_CV2:
        return None
    try:
        img = cv2.imread(image_path)
        if img is None:
            try:
                pil = Image.open(image_path).convert("RGB")
                img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
            except Exception:
                return None

        out_w -= out_w % 2; out_h -= out_h % 2
        canvas = _wb_compose_canvas(img, out_w, out_h)
        H, W = canvas.shape[:2]

        total_frames = max(2, int(round(total_duration * fps)))
        freeze = max(0.0, min(float(freeze_tail), total_duration * 0.4))
        freeze_frames = int(round(freeze * fps))
        draw_frames = max(1, total_frames - freeze_frames)

        # Parchment paper background
        paper_bg = np.full_like(canvas, (210, 230, 245), dtype=np.uint8) # Vintage parchment tone
        # Add subtle noise/texture to paper
        noise = np.random.randint(-15, 15, (H, W, 3)).astype(np.int16)
        paper_bg = np.clip(paper_bg.astype(np.int16) + noise, 0, 255).astype(np.uint8)

        cmd = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
               "-s", f"{W}x{H}", "-r", str(fps), "-i", "-"]
        try:
            cmd += GPU.enc_args("veryfast")
        except Exception:
            cmd += ["-c:v", "libx264", "-preset", "veryfast"]
        cmd += ["-pix_fmt", "yuv420p", "-an", "-loglevel", "error", output_path]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

        max_radius = int(np.hypot(W, H) * 0.65)
        cx, cy = W // 2, H // 2

        for f in range(draw_frames):
            prog = f / float(draw_frames)
            cur_r = int(prog * max_radius)

            mask = np.zeros((H, W), dtype=np.uint8)
            if cur_r > 0:
                cv2.circle(mask, (cx, cy), cur_r, 255, -1)
                # Add irregular organic fire edge distortion
                noise_map = np.random.randint(0, max(5, int(cur_r * 0.15) + 1), (H, W), dtype=np.uint8)
                mask = np.clip(mask.astype(np.int16) + (noise_map if cur_r > 20 else 0), 0, 255).astype(np.uint8)
                mask = cv2.GaussianBlur(mask, (15, 15), 0)

            alpha = (mask.astype(np.float32) / 255.0)[:, :, np.newaxis]
            frame = (canvas.astype(np.float32) * alpha + paper_bg.astype(np.float32) * (1.0 - alpha)).astype(np.uint8)

            # Fiery Ember border: Orange/Gold glow & black charred edge
            if 0.02 < prog < 0.98 and cur_r > 10:
                edge = cv2.Canny(mask, 40, 160)
                if np.any(edge > 0):
                    char = cv2.dilate(edge, np.ones((11, 11), np.uint8))
                    fire = cv2.dilate(edge, np.ones((5, 5), np.uint8))
                    char_a = (char.astype(np.float32) / 255.0)[:, :, np.newaxis] * 0.8
                    fire_a = (fire.astype(np.float32) / 255.0)[:, :, np.newaxis] * 0.9
                    # Charred ash color (BGR)
                    frame = (frame.astype(np.float32) * (1.0 - char_a) + np.array([20, 25, 30]) * char_a).astype(np.uint8)
                    # Glowing fiery ember color (BGR: Bright Gold/Orange)
                    frame = (frame.astype(np.float32) * (1.0 - fire_a) + np.array([0, 165, 255]) * fire_a).astype(np.uint8)

            proc.stdin.write(frame.tobytes())

        for _ in range(total_frames - draw_frames):
            proc.stdin.write(canvas.tobytes())

        proc.stdin.close(); proc.wait()
        if os.path.exists(output_path) and get_duration(output_path) > 0.1:
            return output_path
    except Exception as e:
        print(f"image_to_paper_burn_reveal_video error: {e}")
    return None


def image_to_sparkle_reveal_video(image_path, total_duration, output_path,
                                  freeze_tail=2.5, fps=30, out_w=1920, out_h=1080):
    """
    Image → Sparkle & Shimmer particle reveal animation.
    """
    if not HAS_CV2:
        return None
    try:
        img = cv2.imread(image_path)
        if img is None:
            try:
                pil = Image.open(image_path).convert("RGB")
                img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
            except Exception:
                return None

        out_w -= out_w % 2; out_h -= out_h % 2
        canvas = _wb_compose_canvas(img, out_w, out_h)
        H, W = canvas.shape[:2]

        total_frames = max(2, int(round(total_duration * fps)))
        freeze = max(0.0, min(float(freeze_tail), total_duration * 0.4))
        freeze_frames = int(round(freeze * fps))
        draw_frames = max(1, total_frames - freeze_frames)

        cmd = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
               "-s", f"{W}x{H}", "-r", str(fps), "-i", "-"]
        try:
            cmd += GPU.enc_args("veryfast")
        except Exception:
            cmd += ["-c:v", "libx264", "-preset", "veryfast"]
        cmd += ["-pix_fmt", "yuv420p", "-an", "-loglevel", "error", output_path]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

        for f in range(draw_frames):
            prog = f / float(draw_frames)
            # Smooth left-to-right diagonal sparkle wave
            diag = np.linspace(0, 1, W, dtype=np.float32)[np.newaxis, :]
            vert = np.linspace(0, 0.3, H, dtype=np.float32)[:, np.newaxis]
            grid = diag + vert
            mask = np.clip((prog * 1.4 - grid) * 3.5, 0.0, 1.0)
            
            alpha = mask[:, :, np.newaxis]
            frame = (canvas.astype(np.float32) * alpha).astype(np.uint8)

            # Sparkle particles along the edge
            if 0.05 < prog < 0.95:
                edge_mask = np.where((mask > 0.1) & (mask < 0.9), 255, 0).astype(np.uint8)
                ys, xs = np.where(edge_mask > 0)
                if len(xs) > 0:
                    sample_size = min(30, len(xs))
                    indices = np.random.choice(len(xs), sample_size, replace=False)
                    for idx in indices:
                        px, py = xs[idx], ys[idx]
                        sz = np.random.randint(2, 6)
                        cv2.drawMarker(frame, (px, py), (255, 255, 255), cv2.MARKER_STAR, sz * 2, 1, cv2.LINE_AA)
                        cv2.circle(frame, (px, py), sz, (180, 240, 255), -1, cv2.LINE_AA)

            proc.stdin.write(frame.tobytes())

        for _ in range(total_frames - draw_frames):
            proc.stdin.write(canvas.tobytes())

        proc.stdin.close(); proc.wait()
        if os.path.exists(output_path) and get_duration(output_path) > 0.1:
            return output_path
    except Exception as e:
        print(f"image_to_sparkle_reveal_video error: {e}")
    return None


def image_to_video_with_zoom(image_path, duration, output_path, zoom_speed=0.0015, out_w=1920, out_h=1080):
    try:
        fps=30; total_frames=max(2,int(duration*fps)); max_zoom=min(1.0+(zoom_speed*total_frames),3.0)
        vf=(f"scale=8000:-1,zoompan=z='min(zoom+{zoom_speed},{max_zoom:.4f})':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={total_frames}:s={out_w}x{out_h}:fps={fps},format=yuv420p")
        cmd = ["ffmpeg","-y","-loop","1","-i",image_path,"-vf",vf]
        cmd += GPU.enc_args("fast")
        cmd += ["-t",str(duration),output_path]
        _run_ff(cmd, timeout=300)
        if os.path.exists(output_path) and get_duration(output_path) > 0.1: return output_path
    except Exception as e: print(f"image_to_video_with_zoom error: {e}")
    return None

def freeze_last_frame_zoom_video(video_path, freeze_duration, output_path, zoom_speed=0.001, out_w=1920, out_h=1080):
    try:
        last_frame_path = extract_last_frame(video_path)
        if not last_frame_path: return None
        fzp = os.path.splitext(output_path)[0]+"_fz.mp4"
        result = image_to_video_with_zoom(last_frame_path, freeze_duration, fzp, zoom_speed=zoom_speed, out_w=out_w, out_h=out_h)
        if not result: return None
        on = os.path.splitext(output_path)[0]+"_on.mp4"
        cmd = ["ffmpeg","-y","-i",video_path,"-vf",
            f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,fps=30,format=yuv420p"]
        cmd += GPU.enc_args("fast")
        cmd += ["-an",on]
        _run_ff(cmd, timeout=300)
        if not os.path.exists(on): on = video_path
        lp = os.path.splitext(output_path)[0]+"_cl.txt"
        with open(lp,"w",encoding="utf-8") as f:
            f.write(f"file '{os.path.abspath(on)}'\nfile '{os.path.abspath(fzp)}'\n")
        cmd2 = ["ffmpeg","-y","-f","concat","-safe","0","-i",lp]
        cmd2 += GPU.enc_args("fast")
        cmd2 += ["-an",output_path]
        subprocess.run(cmd2, capture_output=True, text=True, timeout=600)
        if os.path.exists(output_path) and get_duration(output_path) > 0.1: return output_path
    except Exception as e: print(f"freeze_last_frame_zoom error: {e}")
    return None

def speed_fit_video(video_path, target_duration, output_path, out_w=1920, out_h=1080):
    """Speed the video up so the ENTIRE clip plays within target_duration.
    Used when the video is LONGER than the voiceover — instead of trimming,
    the whole video is shown faster. Speed factor = video_dur / voice_dur.
    Example: video 8s, voiceover 2s → 4x speed → full video shown in 2s.
    Source audio is dropped (voiceover is mixed in separately later)."""
    try:
        vd = get_duration(video_path)
        if vd <= 0.05:
            return None
        td = float(target_duration)
        if td <= 0.05:
            return None
        factor = vd / td  # >1 means speed up
        if factor < 1.01:
            factor = 1.0
        # setpts divides presentation timestamps → speeds the clip up
        vf = (f"setpts=PTS/{factor:.6f},"
              f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
              f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,fps=30,format=yuv420p,setsar=1")
        cmd = ["ffmpeg", "-y", "-i", video_path, "-vf", vf]
        cmd += GPU.enc_args("fast")
        cmd += ["-an", "-t", str(td), output_path]
        _run_ff(cmd, timeout=600)
        if os.path.exists(output_path) and get_duration(output_path) > 0.05:
            return output_path
        # Fallback: CPU encoder
        cmd2 = ["ffmpeg", "-y", "-i", video_path, "-vf", vf,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-an", "-t", str(td), output_path]
        subprocess.run(cmd2, capture_output=True, text=True, timeout=600)
        if os.path.exists(output_path) and get_duration(output_path) > 0.05:
            return output_path
    except Exception as e:
        print(f"speed_fit_video error: {e}")
    return None

def freeze_last_frame_video(video_path, target_duration, output_path, out_w=1920, out_h=1080):
    """Play the FULL video once, then FREEZE (hold) its last frame static until
    target_duration is reached. No looping, no zoom — the last frame just stays.
    Example: video 8s, voiceover 15s → plays 8s then holds last frame for 7s = 15s total.
    Uses ffmpeg's tpad (clone last frame) for a clean single-pass result."""
    try:
        vd = get_duration(video_path)
        if vd <= 0.05:
            return None
        freeze_dur = max(0.0, float(target_duration) - vd)
        vf = (f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
              f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,fps=30,format=yuv420p,setsar=1,"
              f"tpad=stop_mode=clone:stop_duration={freeze_dur:.3f}")
        cmd = ["ffmpeg", "-y", "-i", video_path, "-vf", vf]
        cmd += GPU.enc_args("fast")
        cmd += ["-an", "-t", str(target_duration), output_path]
        _run_ff(cmd, timeout=600)
        if os.path.exists(output_path) and get_duration(output_path) > 0.1:
            return output_path
        # Fallback: CPU encoder if GPU path failed
        cmd2 = ["ffmpeg", "-y", "-i", video_path, "-vf", vf,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-an", "-t", str(target_duration), output_path]
        subprocess.run(cmd2, capture_output=True, text=True, timeout=600)
        if os.path.exists(output_path) and get_duration(output_path) > 0.1:
            return output_path
    except Exception as e:
        print(f"freeze_last_frame_video error: {e}")
    return None

def build_pingpong_video(input_path, target_duration, output_path):
    try:
        base_dur = get_duration(input_path)
        if base_dur <= 0.05: return None
        cp = os.path.splitext(output_path)[0]+"_cyc.mp4"
        lp = os.path.splitext(output_path)[0]+"_cyc_l.txt"
        wa = has_audio_stream(input_path)
        if wa:
            fc="[0:v]split[vf][vr];[vr]reverse[rv];[0:a]asplit[af][ar];[ar]areverse[ra];[vf][af][rv][ra]concat=n=2:v=1:a=1[v][a]"
            cmd=["ffmpeg","-y","-i",input_path,"-filter_complex",fc,"-map","[v]","-map","[a]"]
            cmd+=GPU.enc_args("fast")
            cmd+=["-c:a","aac","-b:a","192k",cp]
        else:
            fc="[0:v]split[vf][vr];[vr]reverse[rv];[vf][rv]concat=n=2:v=1:a=0[v]"
            cmd=["ffmpeg","-y","-i",input_path,"-filter_complex",fc,"-map","[v]","-an"]
            cmd+=GPU.enc_args("fast")
            cmd+=[cp]
        _run_ff(cmd, timeout=300)
        if not os.path.exists(cp): return None
        cd = max(0.1, get_duration(cp)); loops = max(1, math.ceil(float(target_duration)/cd))
        with open(lp,"w",encoding="utf-8") as f:
            for _ in range(loops): f.write(f"file '{os.path.abspath(cp)}'\n")
        conp = os.path.splitext(output_path)[0]+"_con.mp4"
        cmd2=["ffmpeg","-y","-f","concat","-safe","0","-i",lp]
        cmd2+=GPU.enc_args("fast")
        cmd2+=["-c:a","aac","-b:a","192k",conp]
        subprocess.run(cmd2, capture_output=True, text=True, timeout=600)
        src = conp if os.path.exists(conp) else cp
        tc=["ffmpeg","-y","-i",src,"-t",str(target_duration)]
        tc+=GPU.enc_args("fast")
        tc += ["-c:a","aac","-b:a","192k"] if has_audio_stream(src) else ["-an"]
        tc += [output_path]
        subprocess.run(tc, capture_output=True, text=True, timeout=600)
        return output_path if os.path.exists(output_path) else None
    except Exception as e: print(f"build_pingpong_video error: {e}"); return None

def build_trim_loop_video(input_path, start_sec, end_sec, target_duration, output_path):
    try:
        seg_dur = max(0.1, end_sec - start_sec)
        trimmed = os.path.splitext(output_path)[0]+"_tr.mp4"
        cmd=["ffmpeg","-y","-ss",str(start_sec),"-i",input_path,"-t",str(seg_dur)]
        cmd+=GPU.enc_args("fast")
        cmd+=["-an",trimmed]
        _run_ff(cmd, timeout=300)
        if not os.path.exists(trimmed): return None
        actual = get_duration(trimmed)
        if actual <= 0.05: return None
        if actual >= target_duration - 0.1:
            cmd2=["ffmpeg","-y","-i",trimmed,"-t",str(target_duration)]
            cmd2+=GPU.enc_args("fast")
            cmd2+=["-an",output_path]
            subprocess.run(cmd2, capture_output=True, text=True, timeout=300)
            return output_path if os.path.exists(output_path) else None
        loops = max(1, math.ceil(target_duration / actual))
        lp = os.path.splitext(output_path)[0]+"_ll.txt"
        with open(lp,"w",encoding="utf-8") as f:
            for _ in range(loops+1): f.write(f"file '{os.path.abspath(trimmed)}'\n")
        conp = os.path.splitext(output_path)[0]+"_lp.mp4"
        cmd3=["ffmpeg","-y","-f","concat","-safe","0","-i",lp]
        cmd3+=GPU.enc_args("fast")
        cmd3+=["-an",conp]
        subprocess.run(cmd3, capture_output=True, text=True, timeout=600)
        src = conp if os.path.exists(conp) else trimmed
        cmd4=["ffmpeg","-y","-i",src,"-t",str(target_duration)]
        cmd4+=GPU.enc_args("fast")
        cmd4+=["-an",output_path]
        subprocess.run(cmd4, capture_output=True, text=True, timeout=600)
        return output_path if os.path.exists(output_path) else None
    except Exception as e: print(f"build_trim_loop_video error: {e}"); return None

def extract_scene_number(path_or_name):
    base = os.path.splitext(os.path.basename(path_or_name))[0]
    m = re.search(r'(?i)(?:^|[^a-z])scene[_\-\s]*(\d+)(?:[_\-\s]|$)', base)
    if m: return int(m.group(1))
    nums = re.findall(r'\d+', base)
    return int(nums[-1]) if nums else None

def sort_files(files):
    def key(f):
        n = extract_scene_number(f)
        return (n if n is not None else 10**9, os.path.basename(f).lower())
    return sorted(files, key=key)

def clean_tts_audio(input_path, output_path, pad_sec=0.0):
    try:
        base_dur=max(0.05,get_duration(input_path)); pad_sec=max(0.0,float(pad_sec or 0.0))
        tail_sec=0.25; target_dur=base_dur+pad_sec+tail_sec
        af='highpass=f=55,lowpass=f=13500,alimiter=limit=0.96,aresample=48000:async=1:first_pts=0'
        af+=f',apad=pad_dur={pad_sec+tail_sec:.3f},atrim=0:{target_dur:.3f}'
        subprocess.run(['ffmpeg','-y','-i',input_path,'-af',af,'-ar','48000','-ac','2','-c:a','pcm_s16le',output_path],
            capture_output=True, text=True, timeout=120)
        if os.path.exists(output_path) and get_duration(output_path) > 0.1: return output_path
    except Exception as e: print(f'clean_tts_audio error: {e}')
    return None

def format_duration(seconds):
    seconds=max(0,int(round(float(seconds or 0)))); h,rem=divmod(seconds,3600); m,s=divmod(rem,60)
    if h: return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def estimate_tts_duration_from_text(text):
    words=len(re.findall(r"\S+",text or "")); punct=len(re.findall(r"[,:;.!?]",text or ""))
    return max(1.5,words/2.4)+punct*0.12

def build_crop_preview_images(video_path, crop_right=151, crop_bottom=151, apply_crop=True, out_w=1920, out_h=1080):
    if is_image_file(video_path): src_w,src_h=get_image_resolution(video_path); orig=Image.open(video_path).convert("RGBA")
    else: src_w,src_h=get_resolution(video_path); orig=extract_frame(video_path,0.5).convert("RGBA")
    if orig.size!=(src_w,src_h): orig=orig.resize((src_w,src_h),Image.LANCZOS)
    if apply_crop: keep_w=max(src_w-max(0,int(crop_right)),100); keep_h=max(src_h-max(0,int(crop_bottom)),100)
    else: keep_w,keep_h=src_w,src_h; crop_right=crop_bottom=0
    cropped=orig.crop((0,0,keep_w,keep_h)); scale=min(out_w/keep_w,out_h/keep_h)
    fit_w=max(1,int(keep_w*scale)); fit_h=max(1,int(keep_h*scale))
    fitted=Image.new("RGBA",(out_w,out_h),(0,0,0,255)); resized=cropped.resize((fit_w,fit_h),Image.LANCZOS)
    fitted.paste(resized,((out_w-fit_w)//2,(out_h-fit_h)//2),resized)
    return orig, fitted, {"src_w":src_w,"src_h":src_h,"keep_w":keep_w,"keep_h":keep_h,
        "crop_right":max(0,int(crop_right)),"crop_bottom":max(0,int(crop_bottom)),"apply_crop":apply_crop}

def build_ticker_drawtext_filter(ticker_text, video_w, video_h, bar_color_hex="000000",
        bar_opacity=0.75, bar_height=50, text_color_hex="FFFFFF", font_size=30,
        scroll_speed=80, label_text="BREAKING", label_bg_hex="CC0000", show_label=True):
    if not ticker_text or not ticker_text.strip(): return None
    st=ticker_text.strip()
    st=st.replace("\\","\\\\\\\\").replace("'","'\\\\\\''").replace(":","\\\\:").replace("%","%%").replace('"','\\\\\\"')
    by=video_h-bar_height; ty=by+(bar_height-font_size)//2
    fs=[f"drawbox=x=0:y={by}:w={video_w}:h={bar_height}:color=0x{bar_color_hex}@{bar_opacity:.2f}:t=fill"]
    lw=0
    if show_label and label_text.strip():
        ls=label_text.strip().replace(":","\\\\:").replace("'","'\\\\\\''")
        lw=int(font_size*0.65*len(label_text))+30
        fs.append(f"drawbox=x=0:y={by}:w={lw}:h={bar_height}:color=0x{label_bg_hex}@1.0:t=fill")
        fs.append(f"drawtext=text='{ls}':x=({lw}-text_w)/2:y={by+(bar_height-font_size)//2}:fontsize={font_size}:fontcolor=0xFFFFFF:font='Arial'")
    scroll=f"     {st}     +++     {st}     +++     {st}     "
    sx=lw+10 if lw>0 else 10
    fs.append(f"drawtext=text='{scroll}':x={sx}+w-mod(t*{scroll_speed}\\,(tw+w)):y={ty}:fontsize={font_size}:fontcolor=0x{text_color_hex}:font='Arial'")
    return ",".join(fs)

# ════════════════════════════════════════════════════════════════
# CAPTION SYSTEM — Word-level timed captions with 25 animations
# ════════════════════════════════════════════════════════════════

CAPTION_ANIMATIONS = [
    "fade", "pop", "slide_up", "slide_down", "slide_left", "slide_right",
    "typewriter", "bounce", "glow", "shake", "zoom_in", "zoom_out",
    "rotate_in", "wave", "pulse", "flicker", "expand", "compress",
    "swing", "elastic", "blur_in", "color_cycle", "neon", "shadow_grow",
    "letter_drop", "cocomelon",
]

def _esc_drawtext(txt):
    """Escape text for ffmpeg drawtext filter."""
    t = txt.replace("\\", "\\\\")
    t = t.replace("'", "\u2019")
    t = t.replace(":", "\\:")
    t = t.replace(";", "\\;")
    t = t.replace("%", "%%")
    t = t.replace("[", "\\[")
    t = t.replace("]", "\\]")
    t = t.replace("\n", " ")
    return t

def split_text_to_caption_groups(text, max_chars=35, max_lines=2, words_per_group=4):
    """Split text into caption groups (word groups for display)."""
    words = text.split()
    if not words:
        return []
    groups = []
    i = 0
    while i < len(words):
        chunk = words[i:i + words_per_group]
        line = " ".join(chunk)
        # If line is too long, split further
        if len(line) > max_chars * max_lines:
            # Take fewer words
            while len(line) > max_chars * max_lines and len(chunk) > 1:
                chunk = chunk[:-1]
                line = " ".join(chunk)
        # Split into lines if needed
        if len(line) > max_chars and max_lines > 1:
            mid = len(chunk) // 2
            if mid < 1:
                mid = 1
            l1 = " ".join(chunk[:mid])
            l2 = " ".join(chunk[mid:])
            groups.append(l1 + "\n" + l2)
        else:
            groups.append(line)
        i += len(chunk)
    return groups

def estimate_word_timings(text, total_duration):
    """Estimate word-level timings based on text and total audio duration."""
    words = text.split()
    if not words:
        return []
    # Simple proportional timing based on character count
    total_chars = sum(len(w) for w in words) + len(words)  # +spaces
    if total_chars <= 0:
        total_chars = 1
    timings = []
    current_time = 0.0
    for w in words:
        word_dur = max(0.15, (len(w) + 1) / total_chars * total_duration)
        timings.append({"word": w, "start": current_time, "end": current_time + word_dur})
        current_time += word_dur
    # Scale to fit total duration
    if timings and timings[-1]["end"] > 0:
        scale = total_duration / timings[-1]["end"]
        for t in timings:
            t["start"] *= scale
            t["end"] *= scale
    return timings

def generate_caption_groups_with_timing(text, total_duration, max_chars=35, max_lines=2, words_per_group=4):
    """Generate caption groups with start/end times."""
    words = text.split()
    if not words:
        return []
    word_timings = estimate_word_timings(text, total_duration)
    groups = []
    i = 0
    while i < len(words):
        chunk_count = min(words_per_group, len(words) - i)
        chunk = words[i:i + chunk_count]
        line = " ".join(chunk)
        # Shrink if too long
        while len(line) > max_chars * max_lines and chunk_count > 1:
            chunk_count -= 1
            chunk = words[i:i + chunk_count]
            line = " ".join(chunk)
        # Get timing
        start_t = word_timings[i]["start"] if i < len(word_timings) else 0
        end_idx = min(i + chunk_count - 1, len(word_timings) - 1)
        end_t = word_timings[end_idx]["end"] if end_idx >= 0 else total_duration
        # Build display text with line breaks
        if len(line) > max_chars and max_lines > 1:
            mid = len(chunk) // 2
            if mid < 1:
                mid = 1
            display = " ".join(chunk[:mid]) + "\n" + " ".join(chunk[mid:])
        else:
            display = line
        groups.append({"text": display, "start": start_t, "end": end_t})
        i += chunk_count
    return groups

def build_caption_drawtext_filter(caption_groups, video_w, video_h, font_path="",
        font_size=48, font_color="FFFFFF", bg_color="000000", bg_opacity=0.6,
        position="bottom", margin_bottom=80, animation="fade",
        border_w=0, border_color="000000", shadow=False, align="center"):
    """Build ffmpeg drawtext filter. Uses single-quoted expressions for animation safety."""
    if not caption_groups:
        return None
    filters = []
    # Font — auto-detect Hindi-capable font if no custom font
    font_arg = ""
    if font_path and os.path.exists(font_path):
        fp = font_path.replace("\\", "/").replace(":", "\\:")
        font_arg = f":fontfile='{fp}'"
    else:
        # Try to find a Hindi-capable font on the system
        hindi_fonts = [
            "C:/Windows/Fonts/NirmalaUI.ttf",    # Windows 10/11
            "C:/Windows/Fonts/mangal.ttf",         # Windows older
            "C:/Windows/Fonts/NotoSansDevanagari-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",  # Linux
            "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        ]
        found_font = None
        for hf in hindi_fonts:
            if os.path.exists(hf):
                found_font = hf; break
        if found_font:
            fp = found_font.replace("\\", "/").replace(":", "\\:")
            font_arg = f":fontfile='{fp}'"
        else:
            font_arg = ":font=Arial"
    # Extra styling
    extra = ""
    if border_w and border_w > 0:
        extra += f":borderw={border_w}:bordercolor=0x{border_color}"
    if shadow:
        extra += ":shadowcolor=0x000000@0.6:shadowx=2:shadowy=2"
    for g in caption_groups:
        txt = _esc_drawtext(g["text"])
        t_s = g["start"]; t_e = g["end"]
        # Position base
        if position == "top": y_base = str(margin_bottom)
        elif position == "center": y_base = "(h-text_h)/2"
        else: y_base = f"h-text_h-{margin_bottom}"
        if align == "left": x_base = "20"
        elif align == "right": x_base = "w-text_w-20"
        else: x_base = "(w-text_w)/2"
        # Box — tight to text width, solid bg
        box = f":box=1:boxcolor=0x{bg_color}@{bg_opacity:.2f}:boxborderw=10"
        # Enable — NO quotes around between, commas OK here
        en = f":enable='between(t,{t_s:.3f},{t_e:.3f})'"
        # Animation — wrap expressions in single quotes so commas inside don't break
        fs_e = str(font_size)
        x_e = x_base
        y_e = y_base
        # For animations with commas (if/max/min), wrap y= or x= value in single quotes
        if animation == "slide_up":
            y_e = f"'if(lt(t-{t_s},0.2),h+({y_base}-h)*(t-{t_s})/0.2,{y_base})'"
        elif animation == "slide_down":
            y_e = f"'if(lt(t-{t_s},0.2),-text_h+({y_base}+text_h)*(t-{t_s})/0.2,{y_base})'"
        elif animation == "slide_left":
            x_e = f"'if(lt(t-{t_s},0.2),w+({x_base}-w)*(t-{t_s})/0.2,{x_base})'"
        elif animation == "slide_right":
            x_e = f"'if(lt(t-{t_s},0.2),-text_w+({x_base}+text_w)*(t-{t_s})/0.2,{x_base})'"
        elif animation == "pop":
            s0=int(font_size*0.3)
            fs_e = f"'if(lt(t-{t_s},0.1),{s0}+({font_size}-{s0})*(t-{t_s})/0.1,{font_size})'"
        elif animation == "bounce":
            y_e = f"'{y_base}+sin((t-{t_s})*8)*15*max(0,1-(t-{t_s})/0.5)'"
        elif animation == "shake":
            x_e = f"'{x_base}+sin((t-{t_s})*25)*5*max(0,1-(t-{t_s})/0.3)'"
            y_e = f"'{y_base}+cos((t-{t_s})*25)*3*max(0,1-(t-{t_s})/0.3)'"
        elif animation == "zoom_in":
            s0=int(font_size*0.5)
            fs_e = f"'if(lt(t-{t_s},0.2),{s0}+({font_size}-{s0})*(t-{t_s})/0.2,{font_size})'"
        elif animation == "zoom_out":
            s0=int(font_size*1.5)
            fs_e = f"'if(lt(t-{t_s},0.15),{s0}-({s0}-{font_size})*(t-{t_s})/0.15,{font_size})'"
        elif animation == "wave":
            y_e = f"'{y_base}+sin((t-{t_s})*3)*8'"
        elif animation == "pulse":
            fs_e = f"'{font_size}+{int(font_size*0.08)}*sin((t-{t_s})*6)'"
        elif animation == "swing":
            x_e = f"'{x_base}+sin((t-{t_s})*5)*20*max(0,1-(t-{t_s})/0.6)'"
        elif animation == "elastic":
            fs_e = f"'{font_size}*(1+0.3*sin((t-{t_s})*12)*max(0,1-(t-{t_s})/0.5))'"
        elif animation == "letter_drop":
            y_e = f"'if(lt(t-{t_s},0.25),-text_h+({y_base}+text_h)*(t-{t_s})/0.25,{y_base}+sin((t-{t_s}-0.25)*8)*5*max(0,1-(t-{t_s}-0.25)/0.3))'"
        if animation == "cocomelon":
            bdr = max(2, font_size // 12)
            dt1 = (f"drawtext=text='{txt}':x={x_base}:y={y_base}:fontsize={font_size}"
                f":fontcolor=0x000000{font_arg}:borderw={bdr}:bordercolor=0x000000"
                f":shadowcolor=0x000000@0.5:shadowx=2:shadowy=2{box}{en}")
            filters.append(dt1)
            dt2 = (f"drawtext=text='{txt}':x={x_base}:y={y_base}:fontsize={font_size}"
                f":fontcolor=0x{font_color}{font_arg}{en}")
            filters.append(dt2)
        else:
            dt = (f"drawtext=text='{txt}':x={x_e}:y={y_e}:fontsize={fs_e}"
                f":fontcolor=0x{font_color}{font_arg}{box}{extra}{en}")
            filters.append(dt)
    return ",".join(filters)

def generate_caption_srt(caption_groups, output_path):
    """Generate SRT subtitle file from caption groups."""
    with open(output_path, "w", encoding="utf-8") as f:
        for i, g in enumerate(caption_groups):
            s = g["start"]
            e = g["end"]
            sh, sm = divmod(int(s), 3600)
            sm2, ss = divmod(sm, 60)
            sms = int((s - int(s)) * 1000)
            eh, em = divmod(int(e), 3600)
            em2, es = divmod(em, 60)
            ems = int((e - int(e)) * 1000)
            f.write(f"{i+1}\n")
            f.write(f"{sh:02d}:{sm2:02d}:{ss:02d},{sms:03d} --> {eh:02d}:{em2:02d}:{es:02d},{ems:03d}\n")
            f.write(f"{g['text']}\n\n")
    return output_path

def simple_loop_video(input_path, target_duration, num):
    """Loop video using -stream_loop (GPU-accelerated). Standalone utility."""
    out=os.path.join(TEMP_DIR,f"sloop_{num}.mp4")
    base_dur=get_duration(input_path)
    if base_dur<=0.05: return None
    loops=max(1,math.ceil(target_duration/base_dur))
    try:
        cmd=["ffmpeg","-y","-stream_loop",str(loops),"-i",input_path,"-t",str(target_duration)]
        cmd+=GPU.enc_args("fast")
        cmd+=["-an",out]
        _run_ff(cmd, timeout=600)
        if os.path.exists(out) and get_duration(out)>0.1: return out
    except: pass
    # Fallback: concat demuxer
    try:
        lp=os.path.join(TEMP_DIR,f"sloop_{num}_list.txt")
        with open(lp,"w",encoding="utf-8") as f:
            for _ in range(loops+1): f.write(f"file '{os.path.abspath(input_path)}'\n")
        cmd2=["ffmpeg","-y","-f","concat","-safe","0","-i",lp,"-t",str(target_duration)]
        cmd2+=GPU.enc_args("fast")
        cmd2+=["-an",out]
        subprocess.run(cmd2, capture_output=True, text=True, timeout=600)
        if os.path.exists(out) and get_duration(out)>0.1: return out
    except: pass
    return None

def smart_thumb(video_path, w=72, h=38):
    """Extract a unique thumbnail per video using hash-based position."""
    try:
        dur=get_duration(video_path)
        if dur<=0.1: return None
        # Use filename hash to pick unique position (10%-90% range)
        h_val=hash(os.path.basename(video_path)) % 80 + 10  # 10-90
        at=dur * h_val / 100.0
        at=max(0.2, min(at, dur-0.2))
        img=extract_frame(video_path, at)
        if img:
            img.thumbnail((w,h),Image.LANCZOS)
            return ImageTk.PhotoImage(img.convert("RGB"))
    except: pass
    return None

def clean_temp_files():
    """Remove all temp files except settings and cache."""
    if not os.path.isdir(TEMP_DIR): return 0
    keep={SETTINGS_FILE, TTS_CACHE_FILE}
    removed=0
    for fn in os.listdir(TEMP_DIR):
        fp=os.path.join(TEMP_DIR,fn)
        if fp in keep: continue
        try:
            if os.path.isfile(fp): os.remove(fp); removed+=1
            elif os.path.isdir(fp): shutil.rmtree(fp); removed+=1
        except: pass
    return removed

def unique_paths_preserve_order(paths):
    seen = set()
    out = []
    for p in paths:
        if not p:
            continue
        ap = os.path.abspath(p)
        if ap in seen:
            continue
        seen.add(ap)
        out.append(p)
    return out



# ════════════════════════════════════════════════════════════════
# POPUP WINDOWS — CropLogo, CropPreview, LogoPreview, TrimLoop,
# VoiceSearch, MiniPlayer
# ════════════════════════════════════════════════════════════════

class CropLogoWindow(ctk.CTkToplevel):
    def __init__(self, master, logo_pil, callback):
        super().__init__(master); self.title("Crop Logo"); self.configure(fg_color=C["bg"]); self.transient(master)
        self.callback=callback; self.orig=logo_pil.copy().convert("RGBA"); self.aspect="1:1"; self.canvas_size=460
        top=ctk.CTkFrame(self,fg_color=C["card"]); top.pack(fill="x",padx=10,pady=5)
        ctk.CTkLabel(top,text="Ratio:",text_color=C["text"]).pack(side="left",padx=5)
        for ar in ["1:1","16:9","9:16","4:3","4:5","Free"]:
            ctk.CTkButton(top,text=ar,width=48,height=26,fg_color=C["btn"],hover_color=C["accent"],
                text_color=C["text"],command=lambda a=ar:self._set_aspect(a)).pack(side="left",padx=2)
        ctk.CTkLabel(top,text="  Size:",text_color=C["dim"]).pack(side="left",padx=5)
        self.size_var=ctk.IntVar(value=min(self.orig.width,self.orig.height)//2)
        ctk.CTkSlider(top,from_=30,to=max(self.orig.width,self.orig.height),variable=self.size_var,width=120,command=self._on_size).pack(side="left",padx=5)
        self.canvas=Canvas(self,width=460,height=460,bg=C["bg"],highlightthickness=0); self.canvas.pack(padx=10,pady=5)
        bot=ctk.CTkFrame(self,fg_color=C["card"]); bot.pack(fill="x",padx=10,pady=5)
        self.info_lbl=ctk.CTkLabel(bot,text="",text_color=C["dim"]); self.info_lbl.pack(side="left",padx=10)
        ctk.CTkButton(bot,text="Confirm Crop",fg_color=C["green"],text_color="#000",command=self._confirm).pack(side="right",padx=10,pady=5)
        self.scale=1.0; self.off_x=self.off_y=0; self.rect_x=self.rect_y=0; self._drag=None
        self._calc_scale(); self._init_rect(); self._render()
        self.canvas.bind("<Button-1>",self._press); self.canvas.bind("<B1-Motion>",self._move); self.canvas.bind("<ButtonRelease-1>",self._release)
        self.after(100,lambda:(self.lift(),self.focus_force(),self.grab_set()))
    def _calc_scale(self):
        w,h=self.orig.size; self.scale=min(self.canvas_size/w,self.canvas_size/h,1.0)
        self.disp_w=int(w*self.scale); self.disp_h=int(h*self.scale)
        self.off_x=(self.canvas_size-self.disp_w)//2; self.off_y=(self.canvas_size-self.disp_h)//2
    def _get_wh(self,base):
        ow,oh=self.orig.size
        if self.aspect=="1:1": s=min(base,ow,oh); return s,s
        ratios={"16:9":(16,9),"9:16":(9,16),"4:3":(4,3),"4:5":(4,5)}
        if self.aspect in ratios:
            rw,rh=ratios[self.aspect]; w=min(base,ow); h=int(w*rh/rw)
            if h>oh: h=oh; w=int(h*rw/rh)
            return max(1,w),max(1,h)
        s=min(base,ow,oh); return s,s
    def _init_rect(self): rw,rh=self._get_wh(self.size_var.get()); self.rect_x=(self.orig.width-rw)//2; self.rect_y=(self.orig.height-rh)//2
    def _set_aspect(self,a): self.aspect=a; self._init_rect(); self._render()
    def _on_size(self,_=None): self._init_rect(); self._render()
    def _render(self):
        self.canvas.delete("all"); rw,rh=self._get_wh(self.size_var.get()); ow,oh=self.orig.size
        rx=max(0,min(self.rect_x,ow-rw)); ry=max(0,min(self.rect_y,oh-rh)); self.rect_x,self.rect_y=rx,ry
        disp=self.orig.copy().resize((self.disp_w,self.disp_h),Image.LANCZOS)
        ov=Image.new("RGBA",disp.size,(0,0,0,140)); sx,sy=int(rx*self.scale),int(ry*self.scale)
        sw,sh=int(rw*self.scale),int(rh*self.scale); ImageDraw.Draw(ov).rectangle([sx,sy,sx+sw,sy+sh],fill=(0,0,0,0))
        disp=Image.alpha_composite(disp,ov); self._tk=ImageTk.PhotoImage(disp)
        self.canvas.create_image(self.off_x,self.off_y,anchor="nw",image=self._tk)
        self.canvas.create_rectangle(self.off_x+sx,self.off_y+sy,self.off_x+sx+sw,self.off_y+sy+sh,outline=C["green"],width=2,dash=(4,4))
        self.info_lbl.configure(text=f"Crop: {rw}x{rh} | {self.aspect}")
    def _press(self,e): self._drag=(e.x,e.y,self.rect_x,self.rect_y)
    def _move(self,e):
        if not self._drag: return
        self.rect_x=int(self._drag[2]+(e.x-self._drag[0])/self.scale); self.rect_y=int(self._drag[3]+(e.y-self._drag[1])/self.scale); self._render()
    def _release(self,e): self._drag=None
    def _confirm(self):
        rw,rh=self._get_wh(self.size_var.get()); rx=max(0,min(self.rect_x,self.orig.width-rw)); ry=max(0,min(self.rect_y,self.orig.height-rh))
        self.grab_release(); self.callback(self.orig.crop((rx,ry,rx+rw,ry+rh))); self.destroy()


class CropPreviewWindow(ctk.CTkToplevel):
    def __init__(self, master, video_path, crop_right, crop_bottom, apply_crop=True):
        super().__init__(master); self.title("Crop Preview"); self.configure(fg_color=C["bg"]); self.transient(master)
        orig,final,meta=build_crop_preview_images(video_path,crop_right,crop_bottom,apply_crop=apply_crop)
        self.orig=orig; self.final=final; self.meta=meta; self.geometry("1000x640")
        head=ctk.CTkFrame(self,fg_color=C["card"]); head.pack(fill="x",padx=10,pady=(10,5))
        ctk.CTkLabel(head,text=f"Crop {'ON' if apply_crop else 'OFF'} | Keep:{meta['keep_w']}x{meta['keep_h']}",text_color=C["accent"],font=("Consolas",11)).pack(anchor="w",padx=10,pady=8)
        body=ctk.CTkFrame(self,fg_color="transparent"); body.pack(fill="both",expand=True,padx=10,pady=5)
        body.grid_columnconfigure((0,1),weight=1); body.grid_rowconfigure(1,weight=1)
        ctk.CTkLabel(body,text="Original",text_color=C["orange"],font=("Segoe UI",12,"bold")).grid(row=0,column=0)
        ctk.CTkLabel(body,text="Output",text_color=C["green"],font=("Segoe UI",12,"bold")).grid(row=0,column=1)
        self.lc=Canvas(body,bg="#000",highlightthickness=1,highlightbackground=C["border"]); self.lc.grid(row=1,column=0,sticky="nsew",padx=(0,6))
        self.rc=Canvas(body,bg="#000",highlightthickness=1,highlightbackground=C["border"]); self.rc.grid(row=1,column=1,sticky="nsew",padx=(6,0))
        ctk.CTkButton(self,text="Close",fg_color=C["green"],text_color="#000",command=self.destroy).pack(anchor="e",padx=10,pady=10)
        self.after(80,self._render); self.after(120,lambda:(self.lift(),self.focus_force(),self.grab_set()))
    def _render(self):
        self.update_idletasks()
        def fit(img,mw,mh): c=img.copy(); c.thumbnail((mw,mh),Image.LANCZOS); return c
        lw,lh=max(300,self.lc.winfo_width()),max(220,self.lc.winfo_height())
        rw,rh=max(300,self.rc.winfo_width()),max(220,self.rc.winfo_height())
        sh=self.orig.copy()
        if self.meta["apply_crop"]:
            ov=Image.new("RGBA",sh.size,(0,0,0,0)); d=ImageDraw.Draw(ov)
            if self.meta["keep_w"]<sh.width: d.rectangle([self.meta["keep_w"],0,sh.width,sh.height],fill=(248,81,73,110))
            if self.meta["keep_h"]<sh.height: d.rectangle([0,self.meta["keep_h"],sh.width,sh.height],fill=(248,81,73,110))
            d.rectangle([0,0,self.meta["keep_w"],self.meta["keep_h"]],outline=(63,185,80,255),width=6)
            sh=Image.alpha_composite(sh,ov)
        l=fit(sh,lw-10,lh-10); r=fit(self.final,rw-10,rh-10)
        self._lt=ImageTk.PhotoImage(l.convert("RGB")); self._rt=ImageTk.PhotoImage(r.convert("RGB"))
        self.lc.delete("all"); self.rc.delete("all")
        self.lc.create_image(lw//2,lh//2,image=self._lt); self.rc.create_image(rw//2,rh//2,image=self._rt)


class LogoPreviewWindow(ctk.CTkToplevel):
    def __init__(self, master, preview_image, logo_pil, size, opacity, callback, init_anchor="top-left", init_mx=20, init_my=20, init_x=None, init_y=None):
        super().__init__(master); self.title("Logo Position"); self.configure(fg_color=C["bg"]); self.transient(master)
        self.callback=callback; self.logo_orig=logo_pil.copy().convert("RGBA"); self.bg_frame=preview_image.copy().convert("RGBA")
        self.src_w,self.src_h=self.bg_frame.size; r=min(820/self.src_w,480/self.src_h)
        self.canvas_w=int(self.src_w*r); self.canvas_h=int(self.src_h*r)
        self.scale_x=self.canvas_w/self.src_w; self.scale_y=self.canvas_h/self.src_h
        self.geometry(f"{self.canvas_w+40}x{self.canvas_h+240}"); self.resizable(False,False)
        ctrl=ctk.CTkFrame(self,fg_color=C["card"]); ctrl.pack(fill="x",padx=10,pady=(8,4))
        ctk.CTkLabel(ctrl,text="Size:",text_color=C["dim"]).pack(side="left",padx=(8,3))
        self.size_var=ctk.IntVar(value=size)
        ctk.CTkSlider(ctrl,from_=20,to=400,variable=self.size_var,width=120,command=self._on_slider).pack(side="left",padx=3)
        self.sz_lbl=ctk.CTkLabel(ctrl,text=f"{size}px",text_color=C["text"],width=45); self.sz_lbl.pack(side="left")
        ctk.CTkLabel(ctrl,text="Opacity:",text_color=C["dim"]).pack(side="left",padx=(10,3))
        self.opa_var=ctk.IntVar(value=opacity)
        ctk.CTkSlider(ctrl,from_=10,to=100,variable=self.opa_var,width=120,command=self._on_slider).pack(side="left",padx=3)
        self.op_lbl=ctk.CTkLabel(ctrl,text=f"{opacity}%",text_color=C["text"],width=40); self.op_lbl.pack(side="left")
        c2=ctk.CTkFrame(self,fg_color=C["card"]); c2.pack(fill="x",padx=10,pady=2)
        ctk.CTkButton(c2,text="Crop Logo",width=90,fg_color=C["purple"],text_color="#fff",command=self._open_crop).pack(side="left",padx=8,pady=5)
        ctk.CTkButton(c2,text="Confirm",width=130,fg_color=C["green"],text_color="#000",font=("Segoe UI",13,"bold"),command=self._confirm).pack(side="right",padx=8,pady=5)
        self.canvas=Canvas(self,width=self.canvas_w,height=self.canvas_h,bg="#000",highlightthickness=1,highlightbackground=C["border"],cursor="crosshair"); self.canvas.pack(padx=10,pady=5)
        self.anchor_lbl=ctk.CTkLabel(self,text="",text_color=C["orange"],font=("Consolas",11)); self.anchor_lbl.pack(pady=3)
        self.logo_sz=size
        if init_x is None or init_y is None: self.actual_x,self.actual_y=calc_logo_xy(init_anchor,init_mx,init_my,size,self.src_w,self.src_h)
        else: self.actual_x=max(0,min(int(init_x),self.src_w-size)); self.actual_y=max(0,min(int(init_y),self.src_h-size))
        self.anchor=init_anchor; self.margin_x=init_mx; self.margin_y=init_my; self._dragging=False; self._detect_anchor()
        self.canvas.bind("<ButtonPress-1>",self._on_press); self.canvas.bind("<B1-Motion>",self._on_motion); self.canvas.bind("<ButtonRelease-1>",self._on_release)
        self._render(); self.after(150,self._ff)
    def _ff(self): self.lift(); self.attributes("-topmost",True); self.focus_force(); self.grab_set(); self.after(300,lambda:self.attributes("-topmost",False))
    def _on_press(self,e):
        self.logo_sz=self.size_var.get(); ax,ay=int(e.x/self.scale_x),int(e.y/self.scale_y)
        self.actual_x=max(0,min(ax-self.logo_sz//2,self.src_w-self.logo_sz)); self.actual_y=max(0,min(ay-self.logo_sz//2,self.src_h-self.logo_sz))
        self._dragging=True; self._detect_anchor(); self._render()
    def _on_motion(self,e):
        if not self._dragging: return
        self.logo_sz=self.size_var.get(); ax,ay=int(e.x/self.scale_x),int(e.y/self.scale_y)
        self.actual_x=max(0,min(ax-self.logo_sz//2,self.src_w-self.logo_sz)); self.actual_y=max(0,min(ay-self.logo_sz//2,self.src_h-self.logo_sz))
        self._detect_anchor(); self._render()
    def _on_release(self,e): self._dragging=False
    def _on_slider(self,_=None):
        old=max(1,self.logo_sz); cx=self.actual_x+old/2; cy=self.actual_y+old/2; self.logo_sz=self.size_var.get()
        self.sz_lbl.configure(text=f"{self.logo_sz}px"); self.op_lbl.configure(text=f"{self.opa_var.get()}%")
        self.actual_x=max(0,min(int(cx-self.logo_sz/2),self.src_w-self.logo_sz)); self.actual_y=max(0,min(int(cy-self.logo_sz/2),self.src_h-self.logo_sz))
        self._detect_anchor(); self._render()
    def _detect_anchor(self):
        sz=self.logo_sz; cx=self.actual_x+sz//2; cy=self.actual_y+sz//2; mx2=self.src_w/2; my2=self.src_h/2
        h="left" if cx<mx2*0.66 else("right" if cx>mx2*1.34 else""); v="top" if cy<my2*0.66 else("bottom" if cy>my2*1.34 else"")
        if v and h: self.anchor=f"{v}-{h}"
        elif v: self.anchor=f"{v}-left"
        elif h: self.anchor=f"top-{h}"
        else: self.anchor="center"
        self.margin_x=max(0,self.actual_x if "left" in self.anchor else self.src_w-self.actual_x-sz)
        self.margin_y=max(0,self.actual_y if "top" in self.anchor else self.src_h-self.actual_y-sz)
    def _render(self):
        self.canvas.delete("all"); sz=self.logo_sz
        ax=max(0,min(self.actual_x,self.src_w-sz)); ay=max(0,min(self.actual_y,self.src_h-sz)); self.actual_x,self.actual_y=ax,ay
        comp=self.bg_frame.copy(); logo=self.logo_orig.copy().resize((sz,sz),Image.LANCZOS)
        opa=self.opa_var.get()/100.0
        if opa<1.0: a=logo.split()[3]; a=a.point(lambda p:int(p*opa)); logo.putalpha(a)
        comp.paste(logo,(ax,ay),logo); disp=comp.resize((self.canvas_w,self.canvas_h),Image.LANCZOS)
        self._tk_img=ImageTk.PhotoImage(disp); self.canvas.create_image(0,0,anchor="nw",image=self._tk_img)
        px,py=int(ax*self.scale_x),int(ay*self.scale_y); pw,ph=int(sz*self.scale_x),int(sz*self.scale_y)
        self.canvas.create_rectangle(px,py,px+pw,py+ph,outline=C["green"],width=2,dash=(5,3))
        self.anchor_lbl.configure(text=f"{self.anchor} M:({self.margin_x},{self.margin_y}) Sz:{sz} XY:({ax},{ay})")
    def _open_crop(self): self.grab_release(); CropLogoWindow(self,self.logo_orig,self._on_crop_done)
    def _on_crop_done(self,cr): self.logo_orig=cr.convert("RGBA"); self._render(); self.after(100,self._ff)
    def _confirm(self):
        self.grab_release(); self.callback(self.anchor,self.margin_x,self.margin_y,self.size_var.get(),self.opa_var.get(),self.logo_orig,int(self.actual_x),int(self.actual_y)); self.destroy()


class TrimLoopWindow(ctk.CTkToplevel):
    """Trim & Loop — DEFAULT is now pingpong (Task 6)."""
    def __init__(self, master, video_path, target_duration, callback, auto_process_callback=None):
        super().__init__(master); self.title("Trim & Loop"); self.configure(fg_color=C["bg"]); self.transient(master)
        self.video_path=video_path; self.target_duration=target_duration; self.callback=callback
        self.auto_process_callback=auto_process_callback
        self.vid_duration=get_duration(video_path)
        if self.vid_duration<=0.1: messagebox.showerror("Error","Cannot read video."); self.destroy(); return
        self.geometry("780x530"); self.minsize(720,480)
        ctk.CTkLabel(self,text=f"{os.path.basename(video_path)} ({format_duration(self.vid_duration)})",
            text_color=C["accent"],font=("Segoe UI",12,"bold")).pack(pady=(10,3))
        ctk.CTkLabel(self,text=f"Voice duration: {format_duration(target_duration)} — segment loops to fill",
            text_color=C["dim"],font=("Segoe UI",10)).pack(pady=(0,8))
        self.pc=Canvas(self,width=480,height=200,bg="#000",highlightthickness=1,highlightbackground=C["border"])
        self.pc.pack(pady=5)
        sf=ctk.CTkFrame(self,fg_color=C["card"]); sf.pack(fill="x",padx=15,pady=8)
        s1=ctk.CTkFrame(sf,fg_color="transparent"); s1.pack(fill="x",padx=10,pady=4)
        ctk.CTkLabel(s1,text="Start:",text_color=C["green"],font=("Segoe UI",11,"bold"),width=50).pack(side="left")
        self.sv=ctk.DoubleVar(value=0.0)
        ctk.CTkSlider(s1,from_=0,to=self.vid_duration,variable=self.sv,width=400,command=self._os).pack(side="left",padx=5)
        self.sl=ctk.CTkLabel(s1,text="00:00",text_color=C["text"],font=("Consolas",11),width=55); self.sl.pack(side="left")
        s2=ctk.CTkFrame(sf,fg_color="transparent"); s2.pack(fill="x",padx=10,pady=4)
        ctk.CTkLabel(s2,text="End:",text_color=C["red"],font=("Segoe UI",11,"bold"),width=50).pack(side="left")
        self.ev=ctk.DoubleVar(value=min(self.vid_duration,target_duration))
        ctk.CTkSlider(s2,from_=0,to=self.vid_duration,variable=self.ev,width=400,command=self._oe).pack(side="left",padx=5)
        self.el=ctk.CTkLabel(s2,text=format_duration(self.ev.get()),text_color=C["text"],font=("Consolas",11),width=55); self.el.pack(side="left")
        self.il=ctk.CTkLabel(sf,text="",text_color=C["orange"],font=("Consolas",10)); self.il.pack(anchor="w",padx=10,pady=(2,6))
        lmf=ctk.CTkFrame(self,fg_color=C["card"],border_color=C["border"],border_width=1,corner_radius=8)
        lmf.pack(fill="x",padx=15,pady=4)
        ctk.CTkLabel(lmf,text="█  LOOP MODE",text_color=C["accent"],font=("Segoe UI",11,"bold")).pack(anchor="w",padx=8,pady=(5,2))
        # ── DEFAULT CHANGED TO PINGPONG (Task 6) ──
        self.loop_mode_var=ctk.StringVar(value="pingpong")
        lmr=ctk.CTkFrame(lmf,fg_color="transparent"); lmr.pack(fill="x",padx=8,pady=(0,6))
        ctk.CTkRadioButton(lmr,text="Forward Loop (A→A→A...)",variable=self.loop_mode_var,value="forward",
            text_color=C["text"],fg_color=C["green"],hover_color=C["accent"]).pack(side="left",padx=(0,20))
        ctk.CTkRadioButton(lmr,text="Forward + Reverse (A→reverse(A)→A...)",variable=self.loop_mode_var,value="pingpong",
            text_color=C["text"],fg_color=C["orange"],hover_color=C["accent"]).pack(side="left")
        ap=ctk.CTkFrame(self,fg_color="transparent"); ap.pack(fill="x",padx=15,pady=2)
        self.auto_var=ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(ap,text="Auto-process trim immediately (saves render time)",variable=self.auto_var,
            text_color=C["accent"],fg_color=C["green"]).pack(side="left",padx=5)
        bf=ctk.CTkFrame(self,fg_color="transparent"); bf.pack(fill="x",padx=15,pady=5)
        ctk.CTkButton(bf,text="Confirm Trim & Loop",fg_color=C["green"],text_color="#000",
            font=("Segoe UI",13,"bold"),height=36,command=self._confirm).pack(side="right",padx=5)
        ctk.CTkButton(bf,text="Cancel",fg_color=C["btn"],text_color=C["text"],height=36,
            command=self.destroy).pack(side="right",padx=5)
        self._ui(); self._sf(0.0)
        self.after(100,lambda:(self.lift(),self.focus_force(),self.grab_set()))
    def _os(self,_=None):
        s,e=self.sv.get(),self.ev.get()
        if s>=e: self.sv.set(max(0,e-0.5))
        self.sl.configure(text=format_duration(self.sv.get())); self._ui(); self._sf(self.sv.get())
    def _oe(self,_=None):
        s,e=self.sv.get(),self.ev.get()
        if e<=s: self.ev.set(min(self.vid_duration,s+0.5))
        self.el.configure(text=format_duration(self.ev.get())); self._ui(); self._sf(self.ev.get())
    def _ui(self):
        seg=max(0.1,self.ev.get()-self.sv.get()); loops=math.ceil(self.target_duration/seg)
        mode=self.loop_mode_var.get()
        mode_txt="Fwd" if mode=="forward" else "Fwd+Rev"
        self.il.configure(text=f"Segment:{format_duration(seg)} | {mode_txt} {loops}x | Target:{format_duration(self.target_duration)}")
    def _sf(self,at):
        """Extract frame in background thread so slider stays smooth."""
        self._sf_target=max(0,float(at))
        if hasattr(self,'_sf_busy') and self._sf_busy: return
        self._sf_busy=True
        def _do():
            try:
                t=self._sf_target
                img=extract_frame(self.video_path,t)
                if img:
                    img.thumbnail((480,200),Image.LANCZOS)
                    tk=ImageTk.PhotoImage(img.convert("RGB"))
                    self._ptk=tk
                    self.pc.delete("all"); self.pc.create_image(240,100,image=self._ptk)
            except: pass
            self._sf_busy=False
            # If target changed while we were busy, fetch again
            if hasattr(self,'_sf_target') and abs(self._sf_target-t)>0.05:
                self.after(50,lambda:self._sf(self._sf_target))
        threading.Thread(target=_do,daemon=True).start()
    def _confirm(self):
        s,e=self.sv.get(),self.ev.get()
        if e<=s+0.1: messagebox.showwarning("Trim","End must be after start."); return
        do_auto=self.auto_var.get()
        loop_mode=self.loop_mode_var.get()
        self.grab_release(); self.callback(s,e,do_auto,loop_mode); self.destroy()


class VoiceSearchWindow(ctk.CTkToplevel):
    def __init__(self, master, voice_list_full, current_voice, callback, api_key=""):
        super().__init__(master); self.title("Search Voice"); self.configure(fg_color=C["bg"]); self.transient(master)
        self.geometry("650x560"); self.minsize(580,480)
        self.voice_list_full=voice_list_full; self.callback=callback; self.api_key=api_key
        self._preview_playing=False; self._preview_path=None
        ctk.CTkLabel(self,text="🔍 Search Voice by Name or ID",text_color=C["accent"],
            font=("Segoe UI",14,"bold")).pack(pady=(10,5))
        # Filter buttons: All / Male / Female / AI33 Providers
        ff=ctk.CTkFrame(self,fg_color=C["card"]); ff.pack(fill="x",padx=15,pady=(3,3))
        self.gender_filter=ctk.StringVar(value="all")
        for lbl,val,clr in [("All","all",C["accent"]),("♂ Male","male","#58a6ff"),("♀ Female","female","#f778ba")]:
            ctk.CTkButton(ff,text=lbl,width=70,height=24,fg_color=C["btn"],hover_color=clr,text_color=C["text"],
                font=("Segoe UI",9),command=lambda v=val:(self.gender_filter.set(v),self._filter())).pack(side="left",padx=2,pady=4)

        pf=ctk.CTkFrame(self,fg_color=C["card"]); pf.pack(fill="x",padx=15,pady=(0,3))
        self.provider_filter=ctk.StringVar(value="all")
        for lbl,val in [("All Prov","all"),("ElevenLabs","elevenlabs"),("Minimax","minimax"),("FishAudio","fishaudio"),("Edge","edge"),("Kokoro","kokoro"),("Vbee","vbee"),("Cloned","clone")]:
            ctk.CTkButton(pf,text=lbl,width=62,height=22,fg_color=C["btn"],hover_color=C["accent"],text_color=C["text"],
                font=("Segoe UI",8),command=lambda v=val:(self.provider_filter.set(v),self._filter())).pack(side="left",padx=1,pady=2)

        idf=ctk.CTkFrame(self,fg_color=C["card"],border_color=C["border"],border_width=1,corner_radius=8)
        idf.pack(fill="x",padx=15,pady=(5,3))
        ctk.CTkLabel(idf,text="█  DIRECT VOICE ID",text_color=C["orange"],
            font=("Segoe UI",11,"bold")).pack(anchor="w",padx=8,pady=(5,2))
        idr=ctk.CTkFrame(idf,fg_color="transparent"); idr.pack(fill="x",padx=8,pady=(0,6))
        ctk.CTkLabel(idr,text="Paste ID:",text_color=C["dim"]).pack(side="left",padx=(0,5))
        self.id_entry=ctk.CTkEntry(idr,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"],
            font=("Consolas",10),placeholder_text="e.g. 21m00Tcm4TlvDq8ikWAM")
        self.id_entry.pack(side="left",fill="x",expand=True,padx=3)
        ctk.CTkButton(idr,text="Use This ID",width=90,height=28,fg_color=C["orange"],text_color="#000",
            font=("Segoe UI",10,"bold"),command=self._use_direct_id).pack(side="left",padx=(5,3))
        sf=ctk.CTkFrame(self,fg_color=C["card"]); sf.pack(fill="x",padx=15,pady=5)
        ctk.CTkLabel(sf,text="Search:",text_color=C["dim"]).pack(side="left",padx=8,pady=8)
        self.sv=ctk.StringVar()
        self.se=ctk.CTkEntry(sf,textvariable=self.sv,fg_color=C["entry_bg"],text_color=C["text"],
            border_color=C["border"],font=("Consolas",11),placeholder_text="Type name or partial ID...")
        self.se.pack(side="left",fill="x",expand=True,padx=5,pady=6)
        self.count_lbl=ctk.CTkLabel(sf,text=f"{len(voice_list_full)} voices",text_color=C["green"],
            font=("Segoe UI",9),width=80)
        self.count_lbl.pack(side="right",padx=8)
        self.sv.trace_add("write",lambda*a:self._filter())
        self.lf=ctk.CTkScrollableFrame(self,fg_color=C["card"])
        self.lf.pack(fill="both",expand=True,padx=15,pady=5)
        self.current=current_voice
        self._render(voice_list_full)
        bf=ctk.CTkFrame(self,fg_color="transparent"); bf.pack(fill="x",padx=15,pady=8)
        self.preview_status=ctk.CTkLabel(bf,text="",text_color=C["dim"],font=("Segoe UI",9))
        self.preview_status.pack(side="left",padx=5)
        ctk.CTkButton(bf,text="Close",fg_color=C["btn"],text_color=C["text"],command=self._on_close).pack(side="right",padx=5)
        self.protocol("WM_DELETE_WINDOW",self._on_close)
        self.after(100,lambda:(self.lift(),self.focus_force(),self.grab_set(),self.se.focus_set()))
    def _on_close(self):
        self._stop_preview(); self.grab_release(); self.destroy()
    def _use_direct_id(self):
        vid=self.id_entry.get().strip()
        if not vid: messagebox.showwarning("ID","Paste a voice ID first."); return
        for item in self.voice_list_full:
            name=item[0]; i=item[1]
            if i==vid: self.callback(name,vid); self.grab_release(); self.destroy(); return
        self.callback(f"Custom({vid[:12]}...)",vid); self.grab_release(); self.destroy()
    def _filter(self):
        q=self.sv.get().strip().lower(); gf=self.gender_filter.get(); pf=getattr(self, "provider_filter", ctk.StringVar(value="all")).get()
        items=self.voice_list_full
        if gf!="all":
            items=[it for it in items if (len(it)>2 and it[2].lower()==gf)]
        if pf!="all":
            items=[it for it in items if (pf in it[1].lower() or (len(it)>3 and pf in it[3].lower()))]
        if q:
            items=[it for it in items if q in it[0].lower() or q in it[1].lower()]
        self._render(items); self.count_lbl.configure(text=f"{len(items)} match")
    def _render(self,items):
        for w in self.lf.winfo_children(): w.destroy()
        if not items:
            ctk.CTkLabel(self.lf,text="No matches — try Direct ID above",text_color=C["dim"]).pack(pady=20); return
        for item in items[:200]:
            name=item[0]; vid=item[1]; gender=item[2] if len(item)>2 else ""
            row=ctk.CTkFrame(self.lf,fg_color=C["bg"],border_color=C["border"],border_width=1,corner_radius=6)
            row.pack(fill="x",pady=2,padx=2)
            hl=C["green"] if name==self.current else C["text"]
            # Gender badge
            if gender.lower()=="male":
                g_text="♂M"; g_color="#58a6ff"
            elif gender.lower()=="female":
                g_text="♀F"; g_color="#f778ba"
            else:
                g_text="?"; g_color=C["dim"]
            ctk.CTkLabel(row,text=g_text,text_color=g_color,font=("Segoe UI",10,"bold"),width=25).pack(side="left",padx=(6,2),pady=4)
            ctk.CTkLabel(row,text=f"{name}",text_color=hl,font=("Segoe UI",11,"bold"),anchor="w").pack(side="left",padx=3,pady=4)
            ctk.CTkLabel(row,text=vid[:16]+"...",text_color=C["dim"],font=("Consolas",8)).pack(side="left",padx=3)
            ctk.CTkButton(row,text="Select",width=60,height=24,fg_color=C["accent"],text_color="#000",
                font=("Segoe UI",10),command=lambda n=name,i=vid:self._pick(n,i)).pack(side="right",padx=4,pady=3)
            # Play preview button
            ctk.CTkButton(row,text="▶",width=30,height=24,fg_color=C["green"],text_color="#000",
                font=("Segoe UI",10),command=lambda n=name,i=vid:self._play_preview(n,i)).pack(side="right",padx=2,pady=3)
    def _pick(self,name,vid):
        self._stop_preview(); self.callback(name,vid); self.grab_release(); self.destroy()
    def _play_preview(self,name,vid):
        """Play a short voice preview using ElevenLabs API."""
        if not self.api_key:
            # Try to get API key from parent
            try: self.api_key=self.master.api_entry.get().strip()
            except: pass
        if not self.api_key:
            self.preview_status.configure(text="No API key",text_color=C["red"]); return
        self._stop_preview()
        self.preview_status.configure(text=f"Loading {name}...",text_color=C["orange"])
        threading.Thread(target=self._play_preview_worker,args=(name,vid),daemon=True).start()
    def _play_preview_worker(self,name,vid):
        try:
            # Use ElevenLabs preview URL or generate short sample
            preview_url=None
            # Check if voice has preview_url in stored voices
            for v in getattr(self.master,'voices',[]):
                if v.get("voice_id")==vid:
                    preview_url=v.get("preview_url","")
                    break
            if preview_url:
                # Download preview audio
                r=requests.get(preview_url,timeout=15)
                if r.status_code==200:
                    pp=os.path.join(TEMP_DIR,f"_voice_preview_{vid[:8]}.mp3")
                    with open(pp,"wb") as f: f.write(r.content)
                    if os.path.exists(pp) and os.path.getsize(pp)>1000:
                        self._preview_path=pp
                        if HAS_PYGAME:
                            try:
                                pygame.mixer.music.load(pp)
                                pygame.mixer.music.play()
                                self.after(0,lambda:self.preview_status.configure(text=f"▶ Playing: {name}",text_color=C["green"]))
                                return
                            except: pass
            # Fallback: generate short TTS
            pp=os.path.join(TEMP_DIR,f"_voice_preview_{vid[:8]}.mp3")
            try:
                from ai33_api import AI33Client
                _ai33_k = (self.api_key or os.getenv("AI33_API_KEY") or "").strip()
                if _ai33_k == "sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt": _ai33_k = ""
                _ai33_c = AI33Client(api_key=_ai33_k)
                _res = _ai33_c.text_to_speech_v3(text="Hello, this is a voice preview test.", voice_id=vid)
                if isinstance(_res, (bytes, bytearray)) and len(_res) > 500:
                    with open(pp, "wb") as f: f.write(_res)
                    if os.path.exists(pp) and os.path.getsize(pp) > 1000:
                        self._preview_path = pp
                        if HAS_PYGAME:
                            try:
                                pygame.mixer.music.load(pp)
                                pygame.mixer.music.play()
                                self.after(0, lambda: self.preview_status.configure(text=f"▶ Playing: {name}", text_color=C["green"]))
                                return
                            except: pass
            except Exception: pass
            from ai33_api import ai33_tts_generate
            if ai33_tts_generate("Hello, this is a voice preview test.", vid, api_key=self.api_key, out_path=pp):
                self._preview_path=pp
                if HAS_PYGAME:
                    try:
                        pygame.mixer.music.load(pp)
                        pygame.mixer.music.play()
                        self.after(0,lambda:self.preview_status.configure(text=f"▶ Playing: {name}",text_color=C["green"]))
                        return
                    except: pass
                    if HAS_PYGAME:
                        try:
                            pygame.mixer.music.load(pp)
                            pygame.mixer.music.play()
                            self.after(0,lambda:self.preview_status.configure(text=f"▶ Playing: {name}",text_color=C["green"]))
                            return
                        except: pass
            self.after(0,lambda:self.preview_status.configure(text=f"Preview failed",text_color=C["red"]))
        except Exception as e:
            self.after(0,lambda:self.preview_status.configure(text=f"Error: {str(e)[:30]}",text_color=C["red"]))
    def _stop_preview(self):
        if HAS_PYGAME:
            try: pygame.mixer.music.stop()
            except: pass


class CaptionPreviewWindow(ctk.CTkToplevel):
    """Lightweight caption preview with drag-to-position. Uses Canvas drawing for smooth dragging."""
    def __init__(self, master, video_path, caption_groups, font_size=48,
                 font_color="FFFFFF", bg_color="000000", bg_opacity=0.6,
                 position="bottom", margin=80, callback=None, font_path=""):
        super().__init__(master); self.title("Caption Preview — Drag to Reposition"); self.configure(fg_color=C["bg"]); self.transient(master)
        self.callback=callback; self.groups=caption_groups; self.position=position; self.margin=margin
        self.font_size=font_size; self.font_color=font_color; self.bg_color=bg_color; self.bg_opacity=bg_opacity
        self.video_path=video_path
        self.geometry("820x560"); self.resizable(False,False)
        self.canvas_w=780; self.canvas_h=440
        self.src_w=1920; self.src_h=1080
        self.scale_y=self.canvas_h/self.src_h
        self._bg_tk=None; self._dragging=False; self._destroyed=False
        # Caption Y in canvas coords
        self.cap_y=self.canvas_h-int(margin*self.scale_y) if position=="bottom" else (int(margin*self.scale_y) if position=="top" else self.canvas_h//2)
        # UI
        ctk.CTkLabel(self,text="⬆⬇ Drag caption bar up/down to position",text_color=C["accent"],
            font=("Segoe UI",12,"bold")).pack(pady=(8,4))
        self.canvas=Canvas(self,width=self.canvas_w,height=self.canvas_h,bg="#111",
            highlightthickness=1,highlightbackground=C["border"],cursor="sb_v_double_arrow")
        self.canvas.pack(padx=15,pady=5)
        self.canvas.create_text(self.canvas_w//2,self.canvas_h//2,text="Loading...",fill="#8b949e",font=("Segoe UI",14),tags="loading")
        self.info_lbl=ctk.CTkLabel(self,text="Loading frame...",text_color=C["orange"],font=("Consolas",11))
        self.info_lbl.pack(pady=3)
        pf=ctk.CTkFrame(self,fg_color=C["card"]); pf.pack(fill="x",padx=15,pady=5)
        for name,pos in [("Top","top"),("Center","center"),("Bottom","bottom")]:
            ctk.CTkButton(pf,text=name,width=80,height=28,fg_color=C["btn"],hover_color=C["accent"],text_color=C["text"],
                command=lambda p=pos:self._set_pos(p)).pack(side="left",padx=5,pady=5)
        ctk.CTkLabel(pf,text="Margin:",text_color=C["dim"]).pack(side="left",padx=(15,5))
        self.margin_var=ctk.IntVar(value=margin)
        ctk.CTkSlider(pf,from_=10,to=300,variable=self.margin_var,width=120,
            command=self._on_margin).pack(side="left",padx=5)
        self.margin_lbl=ctk.CTkLabel(pf,text=f"{margin}px",text_color=C["text"],width=45); self.margin_lbl.pack(side="left")
        # Hindi font note
        ctk.CTkLabel(pf,text="Hindi: Noto Sans Devanagari.ttf",text_color=C["dim"],font=("Segoe UI",8)).pack(side="right",padx=8)
        bf=ctk.CTkFrame(self,fg_color="transparent"); bf.pack(fill="x",padx=15,pady=5)
        ctk.CTkButton(bf,text="✓ Confirm",fg_color=C["green"],text_color="#000",font=("Segoe UI",12,"bold"),height=34,command=self._confirm).pack(side="right",padx=5)
        ctk.CTkButton(bf,text="Cancel",fg_color=C["btn"],text_color=C["text"],height=34,command=self._close).pack(side="right",padx=5)
        self.canvas.bind("<ButtonPress-1>",self._press)
        self.canvas.bind("<B1-Motion>",self._drag)
        self.canvas.bind("<ButtonRelease-1>",self._release)
        self.protocol("WM_DELETE_WINDOW",self._close)
        threading.Thread(target=self._load_bg,daemon=True).start()
        self.after(100,lambda:(self.lift(),self.focus_force(),self.grab_set()))

    def _load_bg(self):
        """Background thread: extract one frame, resize, cache as PhotoImage."""
        try:
            self.src_w,self.src_h=get_resolution(self.video_path)
            self.scale_y=self.canvas_h/max(1,self.src_h)
            bg=extract_frame(self.video_path,0.5).convert("RGB")
            bg=bg.resize((self.canvas_w,self.canvas_h),Image.LANCZOS)
        except:
            bg=Image.new("RGB",(self.canvas_w,self.canvas_h),(20,20,30))
        if self._destroyed: return
        self._bg_pil=bg
        tk=ImageTk.PhotoImage(bg)
        self._bg_tk=tk
        # Set initial cap_y
        m=self.margin_var.get()
        if self.position=="top": self.cap_y=max(20,int(m*self.scale_y))
        elif self.position=="center": self.cap_y=self.canvas_h//2
        else: self.cap_y=max(20,self.canvas_h-int(m*self.scale_y))
        self.after(0,self._draw)

    def _set_pos(self,pos):
        self.position=pos; m=int(self.margin_var.get())
        if pos=="top": self.cap_y=max(20,int(m*self.scale_y))
        elif pos=="center": self.cap_y=self.canvas_h//2
        else: self.cap_y=max(20,self.canvas_h-int(m*self.scale_y))
        self._draw()

    def _on_margin(self,_=None):
        m=int(self.margin_var.get()); self.margin=m; self.margin_lbl.configure(text=f"{m}px")
        if self.position=="top": self.cap_y=max(20,int(m*self.scale_y))
        elif self.position=="bottom": self.cap_y=max(20,self.canvas_h-int(m*self.scale_y))
        self._draw()

    def _press(self,e): self._dragging=True
    def _drag(self,e):
        if not self._dragging: return
        self.cap_y=max(20,min(int(e.y),self.canvas_h-20))
        if self.cap_y<self.canvas_h*0.33:
            self.position="top"; self.margin=max(10,int(self.cap_y/max(0.01,self.scale_y)))
        elif self.cap_y>self.canvas_h*0.66:
            self.position="bottom"; self.margin=max(10,int((self.canvas_h-self.cap_y)/max(0.01,self.scale_y)))
        else:
            self.position="center"; self.margin=max(10,abs(int((self.cap_y-self.canvas_h//2)/max(0.01,self.scale_y))))
        self.margin_var.set(self.margin)
        self._draw()
    def _release(self,e): self._dragging=False

    def _draw(self):
        """Fast redraw using Canvas items — no Pillow copy per frame."""
        if self._destroyed or self._bg_tk is None: return
        self.canvas.delete("all")
        # Background image (cached PhotoImage — zero cost)
        self.canvas.create_image(0,0,anchor="nw",image=self._bg_tk)
        cy=max(20,min(self.cap_y,self.canvas_h-20))
        cap_h=max(30,min(int(self.font_size*1.2*self.scale_y),100))
        y1=max(0,cy-cap_h//2); y2=min(self.canvas_h,cy+cap_h//2)
        # Caption background bar (semi-transparent via stipple)
        try: bg_hex=f"#{self.bg_color[:6]}"
        except: bg_hex="#000000"
        self.canvas.create_rectangle(40,y1,self.canvas_w-40,y2,fill=bg_hex,stipple="gray50",outline="")
        # Caption sample text
        sample=self.groups[0]["text"].replace("\n"," ") if self.groups else "Sample Caption"
        if len(sample)>50: sample=sample[:50]+"..."
        try: fc_hex=f"#{self.font_color[:6]}"
        except: fc_hex="#FFFFFF"
        fs=max(10,int(self.font_size*self.scale_y*0.6))
        self.canvas.create_text(self.canvas_w//2,cy,text=sample,fill=fc_hex,font=("Arial",fs,"bold"))
        # Drag handles
        self.canvas.create_line(self.canvas_w//2-60,cy,self.canvas_w//2+60,cy,fill="#58a6ff",width=3)
        self.canvas.create_polygon(self.canvas_w//2,cy-12,self.canvas_w//2-6,cy-4,self.canvas_w//2+6,cy-4,fill="#58a6ff")
        self.canvas.create_polygon(self.canvas_w//2,cy+12,self.canvas_w//2-6,cy+4,self.canvas_w//2+6,cy+4,fill="#58a6ff")
        # Info
        self.info_lbl.configure(text=f"Position: {self.position} | Margin: {self.margin}px | Y: {int(cy/max(0.01,self.scale_y))}")
        self.margin_lbl.configure(text=f"{self.margin}px")

    def _confirm(self):
        if self.callback: self.callback(self.position,self.margin)
        self._close()
    def _close(self):
        self._destroyed=True
        try: self.grab_release()
        except: pass
        try: self.destroy()
        except: pass


class BlendTextPreviewWindow(ctk.CTkToplevel):
    """Preview blend text with drag-to-position."""
    def __init__(self, master, video_path, text, font_size=60,
                 font_color="FFFFFF", bg_color="000000", bg_opacity=0.0,
                 position="center", margin=50, align="center", callback=None):
        super().__init__(master); self.title("Blend Text Preview — Drag"); self.configure(fg_color=C["bg"]); self.transient(master)
        self.callback=callback; self.text=text; self.position=position; self.margin=margin
        self.font_size=font_size; self.font_color=font_color; self.bg_color=bg_color; self.bg_opacity=bg_opacity
        self.align=align; self.video_path=video_path
        self.geometry("820x520"); self.resizable(False,False)
        self.canvas_w=780; self.canvas_h=400; self.src_h=1080
        self.scale_y=self.canvas_h/self.src_h
        self._bg_tk=None; self._dragging=False; self._destroyed=False
        self.cap_y=self.canvas_h//2 if position=="center" else (int(margin*self.scale_y) if position=="top" else self.canvas_h-int(margin*self.scale_y))
        ctk.CTkLabel(self,text="⬆⬇ Drag text up/down",text_color=C["accent"],font=("Segoe UI",12,"bold")).pack(pady=(6,3))
        self.canvas=Canvas(self,width=self.canvas_w,height=self.canvas_h,bg="#111",highlightthickness=1,highlightbackground=C["border"],cursor="sb_v_double_arrow")
        self.canvas.pack(padx=15,pady=4)
        self.info_lbl=ctk.CTkLabel(self,text="Loading...",text_color=C["orange"],font=("Consolas",10)); self.info_lbl.pack(pady=2)
        pf=ctk.CTkFrame(self,fg_color=C["card"]); pf.pack(fill="x",padx=15,pady=4)
        for n,p in [("Top","top"),("Center","center"),("Bottom","bottom")]:
            ctk.CTkButton(pf,text=n,width=70,height=26,fg_color=C["btn"],hover_color=C["accent"],text_color=C["text"],
                command=lambda pp=p:self._set_pos(pp)).pack(side="left",padx=4,pady=4)
        ctk.CTkLabel(pf,text="Margin:",text_color=C["dim"]).pack(side="left",padx=(12,3))
        self.margin_var=ctk.IntVar(value=margin)
        ctk.CTkSlider(pf,from_=10,to=400,variable=self.margin_var,width=100,command=self._on_margin).pack(side="left",padx=3)
        self.margin_lbl=ctk.CTkLabel(pf,text=f"{margin}px",text_color=C["text"],width=40); self.margin_lbl.pack(side="left")
        bf=ctk.CTkFrame(self,fg_color="transparent"); bf.pack(fill="x",padx=15,pady=4)
        ctk.CTkButton(bf,text="✓ Confirm",fg_color=C["green"],text_color="#000",font=("Segoe UI",11,"bold"),height=30,command=self._confirm).pack(side="right",padx=4)
        ctk.CTkButton(bf,text="Cancel",fg_color=C["btn"],text_color=C["text"],height=30,command=self._close).pack(side="right",padx=4)
        self.canvas.bind("<ButtonPress-1>",lambda e:setattr(self,'_dragging',True))
        self.canvas.bind("<B1-Motion>",self._drag)
        self.canvas.bind("<ButtonRelease-1>",lambda e:setattr(self,'_dragging',False))
        self.protocol("WM_DELETE_WINDOW",self._close)
        threading.Thread(target=self._load_bg,daemon=True).start()
        self.after(100,lambda:(self.lift(),self.focus_force(),self.grab_set()))
    def _load_bg(self):
        try:
            _,self.src_h=get_resolution(self.video_path)
            self.scale_y=self.canvas_h/max(1,self.src_h)
            bg=extract_frame(self.video_path,1.0).convert("RGB").resize((self.canvas_w,self.canvas_h),Image.LANCZOS)
        except: bg=Image.new("RGB",(self.canvas_w,self.canvas_h),(20,20,30))
        if self._destroyed: return
        self._bg_tk=ImageTk.PhotoImage(bg)
        m=self.margin_var.get()
        if self.position=="top": self.cap_y=max(20,int(m*self.scale_y))
        elif self.position=="center": self.cap_y=self.canvas_h//2
        else: self.cap_y=max(20,self.canvas_h-int(m*self.scale_y))
        self.after(0,self._draw)
    def _set_pos(self,pos):
        self.position=pos; m=int(self.margin_var.get())
        if pos=="top": self.cap_y=max(20,int(m*self.scale_y))
        elif pos=="center": self.cap_y=self.canvas_h//2
        else: self.cap_y=max(20,self.canvas_h-int(m*self.scale_y))
        self._draw()
    def _on_margin(self,_=None):
        m=int(self.margin_var.get()); self.margin=m; self.margin_lbl.configure(text=f"{m}px")
        if self.position=="top": self.cap_y=max(20,int(m*self.scale_y))
        elif self.position=="bottom": self.cap_y=max(20,self.canvas_h-int(m*self.scale_y))
        self._draw()
    def _drag(self,e):
        if not self._dragging: return
        self.cap_y=max(15,min(int(e.y),self.canvas_h-15))
        if self.cap_y<self.canvas_h*0.33: self.position="top"; self.margin=max(10,int(self.cap_y/max(0.01,self.scale_y)))
        elif self.cap_y>self.canvas_h*0.66: self.position="bottom"; self.margin=max(10,int((self.canvas_h-self.cap_y)/max(0.01,self.scale_y)))
        else: self.position="center"; self.margin=max(10,abs(int((self.cap_y-self.canvas_h//2)/max(0.01,self.scale_y))))
        self.margin_var.set(self.margin); self._draw()
    def _draw(self):
        if self._destroyed or not self._bg_tk: return
        self.canvas.delete("all")
        self.canvas.create_image(0,0,anchor="nw",image=self._bg_tk)
        cy=max(15,min(self.cap_y,self.canvas_h-15))
        fs=max(10,int(self.font_size*self.scale_y*0.5))
        cap_h=fs+20
        try: bg_hex=f"#{self.bg_color[:6]}"
        except: bg_hex="#000000"
        try: fc_hex=f"#{self.font_color[:6]}"
        except: fc_hex="#FFFFFF"
        if self.bg_opacity>0.05:
            self.canvas.create_rectangle(30,cy-cap_h//2,self.canvas_w-30,cy+cap_h//2,fill=bg_hex,stipple="gray50",outline="")
        display=self.text[:60]+"..." if len(self.text)>60 else self.text
        anc="center" if self.align=="center" else ("w" if self.align=="left" else "e")
        tx=self.canvas_w//2 if self.align=="center" else (40 if self.align=="left" else self.canvas_w-40)
        self.canvas.create_text(tx,cy,text=display,fill=fc_hex,font=("Arial",fs,"bold"),anchor=anc)
        self.canvas.create_line(self.canvas_w//2-50,cy,self.canvas_w//2+50,cy,fill="#58a6ff",width=2,dash=(4,2))
        self.info_lbl.configure(text=f"Pos: {self.position} | Margin: {self.margin}px | \"{display[:30]}\"")
        self.margin_lbl.configure(text=f"{self.margin}px")
    def _confirm(self):
        if self.callback: self.callback(self.position,self.margin)
        self._close()
    def _close(self):
        self._destroyed=True
        try: self.grab_release()
        except: pass
        try: self.destroy()
        except: pass


class MiniPlayerWindow(ctk.CTkToplevel):
    """Preview player — frame slideshow + pygame audio playback.

    Tkinter has no native video widget, so we extract:
      • JPG frames at low fps for the visual slideshow
      • The audio track (if any) to a temp WAV, played in sync via pygame.mixer
    The in-window playback is best-effort. For *guaranteed* audio, the
    'Play with Audio (External)' button opens the file in the OS default
    player — this is the most reliable path, especially on machines where
    pygame.mixer has issues with the audio device.
    """
    def __init__(self, master, video_path, title_text="Preview", auto_open_external=False):
        super().__init__(master); self.title(title_text); self.configure(fg_color=C["bg"]); self.transient(master)
        self.video_path=video_path; self.geometry("700x560"); self.resizable(True,True)
        self._frames=[]; self._frame_idx=0; self._playing=False; self._fps=10; self._total_frames=0
        self._destroyed=False; self._uid=f"{os.getpid()}_{id(self)}"
        # Audio state
        self._audio_path=None       # extracted WAV used by pygame
        self._has_audio=False
        self._audio_started=False
        self._play_start_ts=0.0
        self._play_start_frame=0
        ctk.CTkLabel(self,text=f"🎬 {os.path.basename(video_path)}",text_color=C["accent"],
            font=("Segoe UI",11,"bold")).pack(pady=(5,2))
        dur=get_duration(video_path)
        self._duration=dur
        # Detect whether the file actually contains audio (cheap probe)
        self._video_has_audio = has_audio_stream(video_path)
        info_txt=(f"Duration: {format_duration(dur)} | "
                  + ("audio: detected ✓" if self._video_has_audio else "audio: NONE in this file 🔇"))
        self.info_lbl=ctk.CTkLabel(self,text=info_txt,
            text_color=(C["green"] if self._video_has_audio else C["orange"]),
            font=("Segoe UI",9))
        self.info_lbl.pack(pady=(0,3))
        # Prominent reliable-audio banner if the file has audio
        if self._video_has_audio:
            banner=ctk.CTkFrame(self,fg_color="#2A3F2A",corner_radius=6)
            banner.pack(fill="x",padx=10,pady=(0,4))
            ctk.CTkLabel(banner,
                text="🔊  For GUARANTEED audio playback, click 'Play with Audio (External)' below.",
                text_color="#A8E6A8",font=("Segoe UI",10,"bold")).pack(padx=8,pady=4)
        self.canvas=Canvas(self,width=620,height=340,bg="#000",highlightthickness=0)
        self.canvas.pack(padx=10,pady=5,fill="both",expand=True)
        self.canvas.create_text(310,170,text="Loading preview…",fill=C["dim"],font=("Segoe UI",14))
        ctrl=ctk.CTkFrame(self,fg_color=C["card"]); ctrl.pack(fill="x",padx=10,pady=5)
        self.play_btn=ctk.CTkButton(ctrl,text="▶ Play (in-window)",width=130,height=28,fg_color=C["green"],
            text_color="#000",command=self._toggle_play); self.play_btn.pack(side="left",padx=5,pady=5)
        ctk.CTkButton(ctrl,text="⏮",width=40,height=28,fg_color=C["btn"],text_color=C["text"],
            command=self._rewind).pack(side="left",padx=2)
        self.pos_lbl=ctk.CTkLabel(ctrl,text="Loading…",text_color=C["dim"],font=("Consolas",9))
        self.pos_lbl.pack(side="left",padx=10)
        # External player button — MADE PROMINENT (orange), since this guarantees audio.
        ext_text = "🔊 Play with Audio (External)" if self._video_has_audio else "🎞 Open External"
        ctk.CTkButton(ctrl,text=ext_text,width=200,height=28,
            fg_color=C["orange"],text_color="#000",
            font=("Segoe UI",10,"bold"),command=self._open_ext).pack(side="right",padx=5,pady=5)
        # Audio status hint
        if not self._video_has_audio:
            init_audio_txt="🔇 No audio track in this preview file"
            init_audio_clr=C["dim"]
        elif not HAS_PYGAME:
            init_audio_txt="⚠ pygame unavailable — use 'Play with Audio (External)' for sound"
            init_audio_clr=C["orange"]
        else:
            init_audio_txt="🔄 Audio: extracting for in-window playback…"
            init_audio_clr=C["dim"]
        self.audio_status_lbl=ctk.CTkLabel(self,text=init_audio_txt,
            text_color=init_audio_clr,font=("Segoe UI",9))
        self.audio_status_lbl.pack(pady=(0,4))
        self.protocol("WM_DELETE_WINDOW",self._on_close)
        threading.Thread(target=self._extract_frames,daemon=True).start()
        threading.Thread(target=self._extract_audio,daemon=True).start()
        self.after(100,lambda:(self.lift(),self.focus_force()))
        # Optionally auto-launch the external player too — guarantees user hears audio
        # without any extra click. Used when the caller knows audio matters (TTS scenes).
        if auto_open_external and self._video_has_audio:
            self.after(400,self._open_ext)

    def _on_close(self):
        self._destroyed=True; self._playing=False
        # Stop pygame mixer (both Sound channel and music) if we started it
        try:
            if HAS_PYGAME:
                if hasattr(self,"_sound_channel") and self._sound_channel is not None:
                    try: self._sound_channel.stop()
                    except: pass
                if self._audio_started:
                    try:
                        pygame.mixer.music.stop()
                        pygame.mixer.music.unload()
                    except: pass
        except: pass
        # Cleanup extracted audio
        try:
            if self._audio_path and os.path.exists(self._audio_path):
                os.remove(self._audio_path)
        except: pass
        try: self.destroy()
        except: pass

    def _extract_audio(self):
        """Extract audio track to a temp WAV for pygame to play. Skip if no audio."""
        try:
            if not HAS_PYGAME:
                if not self._destroyed:
                    self.after(0,lambda:self.audio_status_lbl.configure(
                        text="⚠ pygame unavailable — click 'Play with Audio (External)' button",
                        text_color=C["orange"]))
                return
            if not self._video_has_audio:
                if not self._destroyed:
                    self.after(0,lambda:self.audio_status_lbl.configure(
                        text="🔇 No audio in this preview",text_color=C["dim"]))
                return
            tmp_audio=os.path.join(TEMP_DIR,f"_prev_audio_{self._uid}.wav")
            # Extract as 44100/stereo/16-bit PCM WAV — matches pygame.mixer.init params exactly.
            cmd=["ffmpeg","-y","-i",self.video_path,"-vn",
                 "-acodec","pcm_s16le","-ar","44100","-ac","2",tmp_audio]
            r=_run_ff(cmd,timeout=60)
            if not (os.path.exists(tmp_audio) and os.path.getsize(tmp_audio)>1024):
                err=""
                if r and hasattr(r,"stderr") and r.stderr:
                    err=str(r.stderr)[-150:]
                if not self._destroyed:
                    self.after(0,lambda:self.audio_status_lbl.configure(
                        text=f"⚠ Audio extract failed — use 'Play with Audio (External)' [{err[:50]}]",
                        text_color=C["orange"]))
                return
            self._audio_path=tmp_audio
            self._has_audio=True
            if not self._destroyed:
                self.after(0,lambda:self.audio_status_lbl.configure(
                    text="🔊 In-window audio ready — press ▶ Play (or use External for guaranteed audio)",
                    text_color=C["green"]))
                self.after(0,lambda:self.info_lbl.configure(
                    text=f"Duration: {format_duration(self._duration)} | audio ready ✓",
                    text_color=C["green"]))
                # If user already pressed play before audio was ready, start it now
                if self._playing:
                    self.after(0,self._start_audio)
        except Exception as e:
            if not self._destroyed:
                self.after(0,lambda:self.audio_status_lbl.configure(
                    text=f"⚠ Audio error: {str(e)[:40]}",text_color=C["orange"]))

    def _start_audio(self):
        """Start audio playback from current frame position.
        Uses pygame.mixer.Sound (more reliable for WAVs than mixer.music)."""
        if self._destroyed or not self._has_audio or not self._audio_path or not HAS_PYGAME: return
        # Stop any prior playback
        try:
            if hasattr(self,"_sound_channel") and self._sound_channel is not None:
                self._sound_channel.stop()
        except: pass
        try: pygame.mixer.music.stop()
        except: pass
        # Compute offset based on current frame for resync
        offset=0.0
        if self._total_frames>0 and self._fps>0:
            offset=self._frame_idx/float(self._fps)
        # Try Sound first (works better for WAVs across platforms)
        played=False
        try:
            snd=pygame.mixer.Sound(self._audio_path)
            ch=snd.play()
            if ch is not None:
                self._sound_obj=snd
                self._sound_channel=ch
                played=True
        except Exception as e1:
            # Fallback to mixer.music
            try:
                pygame.mixer.music.load(self._audio_path)
                pygame.mixer.music.play()
                if offset>0.05:
                    try: pygame.mixer.music.set_pos(offset)
                    except: pass
                played=True
            except Exception as e2:
                try: self.audio_status_lbl.configure(
                    text=f"⚠ Audio play error: {str(e1)[:30]} / {str(e2)[:30]} — use External",
                    text_color=C["red"])
                except: pass
        if played:
            self._audio_started=True
            self._play_start_ts=time.time()
            self._play_start_frame=self._frame_idx
            try: self.audio_status_lbl.configure(
                text="🔊 Audio playing",text_color=C["green"])
            except: pass

    def _stop_audio(self):
        if not HAS_PYGAME: return
        try:
            if hasattr(self,"_sound_channel") and self._sound_channel is not None:
                self._sound_channel.stop()
        except: pass
        try: pygame.mixer.music.stop()
        except: pass
        self._audio_started=False

    def _extract_frames(self):
        dur=get_duration(self.video_path)
        if dur<=0 or self._destroyed: return
        # Use a fixed reasonable fps for preview
        preview_fps=8
        n_frames=min(300,max(10,int(dur*preview_fps)))
        self._fps=preview_fps
        # Unique pattern per player instance
        tmp_dir=os.path.join(TEMP_DIR,f"_prev_{self._uid}")
        os.makedirs(tmp_dir,exist_ok=True)
        tmp_pattern=os.path.join(tmp_dir,f"f_%04d.jpg")
        try:
            cmd=["ffmpeg","-y"]
            # Use hwaccel for decode speed but NOT hwaccel_output_format cuda
            # (cuda output format keeps frames in GPU memory, prevents writing to jpg)
            if GPU.gpu_vendor == "nvidia":
                cmd+=["-hwaccel", "cuda"]
            elif GPU.gpu_vendor != "none":
                cmd+=GPU.dec_args()
            cmd+=["-i",self.video_path,"-vf",f"fps={preview_fps},scale=620:-2:flags=fast_bilinear",
                "-q:v","5","-frames:v",str(n_frames),tmp_pattern]
            result=subprocess.run(cmd, capture_output=True, timeout=max(30,int(dur*2)))
            # Fallback if no frames generated (hwaccel issue)
            frames_check=list(Path(tmp_dir).glob("f_*.jpg"))
            if not frames_check:
                cmd2=["ffmpeg","-y","-i",self.video_path,"-vf",f"fps={preview_fps},scale=620:-2:flags=fast_bilinear",
                    "-q:v","5","-frames:v",str(n_frames),tmp_pattern]
                subprocess.run(cmd2, capture_output=True, timeout=max(30,int(dur*2)))
        except: pass
        if self._destroyed: return
        frames_files=sorted(Path(tmp_dir).glob("f_*.jpg"))
        for fp in frames_files:
            if self._destroyed: return
            try:
                img=Image.open(str(fp)).convert("RGB"); img.thumbnail((620,340),Image.LANCZOS)
                tk=ImageTk.PhotoImage(img); self._frames.append(tk)
            except: pass
        self._total_frames=len(self._frames)
        if self._destroyed: return
        if self._frames:
            self.after(0,lambda:self.pos_lbl.configure(text=f"1 / {self._total_frames}"))
            self.after(0,lambda:self._show_frame(0))
            # Auto-play on load
            self.after(100,lambda:self._toggle_play())
        else:
            self.after(0,lambda:self.pos_lbl.configure(text="No frames extracted"))
        # Cleanup temp files
        try: shutil.rmtree(tmp_dir,ignore_errors=True)
        except: pass

    def _show_frame(self,idx):
        if self._destroyed: return
        if 0<=idx<len(self._frames):
            try:
                cw=max(100,self.canvas.winfo_width()); ch=max(100,self.canvas.winfo_height())
                self.canvas.delete("all")
                self.canvas.create_image(cw//2,ch//2,image=self._frames[idx])
                self._frame_idx=idx
                self.pos_lbl.configure(text=f"{idx+1} / {self._total_frames}")
            except: pass

    def _toggle_play(self):
        if self._destroyed: return
        if self._playing:
            self._playing=False; self.play_btn.configure(text="▶ Play")
            self._stop_audio()
        else:
            if not self._frames: return
            self._playing=True; self.play_btn.configure(text="⏸ Pause")
            # Start audio playback (if ready) synchronized to current frame
            if self._has_audio:
                self._start_audio()
            self._play_next()

    def _play_next(self):
        if not self._playing or not self._frames or self._destroyed: return
        # Advance frame
        self._frame_idx=(self._frame_idx+1)%self._total_frames
        self._show_frame(self._frame_idx)
        # When we loop back to start, restart audio too
        if self._frame_idx==0 and self._has_audio:
            self._start_audio()
        delay=max(30,int(1000/max(1,self._fps)))
        if not self._destroyed:
            try: self.after(delay,self._play_next)
            except: pass

    def _rewind(self):
        self._frame_idx=0
        if self._frames: self._show_frame(0)
        if self._playing and self._has_audio:
            self._start_audio()

    def _open_ext(self):
        try:
            if hasattr(os,"startfile"): os.startfile(self.video_path)
            elif sys.platform=="darwin": subprocess.Popen(["open",self.video_path])
            else: subprocess.Popen(["xdg-open",self.video_path])
        except: pass
# ════════════════════════════════════════════════════════════════
# EMBEDDED EDITORS (converted from CTkToplevel → CTkFrame)
# ════════════════════════════════════════════════════════════════

class AdvanceEditorFrame(ctk.CTkFrame):
    """Embedded Advance Editor — v11.0 with all fixes + GPU acceleration."""
    def __init__(self, master):
        super().__init__(master, fg_color=C["bg"])
        self.settings=SettingsManager()
        self.characters={}; self.char_order=[]; self.blocks=[]; self.models=[]; self.voices=[]
        self.voice_list_full=[]; self._progress_lock=threading.Lock(); self.active_filter="All"
        self._cancelled=False  # Task 10: stop flag
        
        # ═══════════════════════════════════════════════════════════
        # FIX: Initialize filler_path early to avoid AttributeError
        # ═════════════════════════════════════════════════════════════
        try:
            self.filler_path = self.settings.get("filler_video") or ""
        except Exception:
            self.filler_path = ""
        
        # ── Sequential media-load worker ──
        # Loading thumbnails+durations for many videos at once locks up the UI because each
        # one needs 2 ffmpeg/ffprobe subprocess calls. Instead we queue (block_index, path)
        # tasks and process them one at a time on a single background thread, posting results
        # back to the UI thread via self.after(). This keeps the UI responsive when the user
        # bulk-uploads 10–50 videos.
        import queue as _q_mod
        self._media_q = _q_mod.Queue()
        self._media_thread = None
        self._media_q_total = 0     # total ever queued
        self._media_q_done = 0      # processed
        self._media_lock = threading.Lock()
        self.logo_enabled_var=ctk.BooleanVar(value=self.settings.get("use_logo"))
        self.logo_path_var=ctk.StringVar(value=self.settings.get("logo_path"))
        self.logo_size_var=ctk.IntVar(value=self.settings.get("logo_size"))
        self.logo_anchor_var=ctk.StringVar(value=self.settings.get("logo_anchor"))
        self.logo_opacity_var=ctk.IntVar(value=self.settings.get("logo_opacity"))
        self.logo_mx_var=ctk.IntVar(value=self.settings.get("logo_margin_x"))
        self.logo_my_var=ctk.IntVar(value=self.settings.get("logo_margin_y"))
        self.logo_pos_x_var=ctk.IntVar(value=self.settings.get("logo_pos_x"))
        self.logo_pos_y_var=ctk.IntVar(value=self.settings.get("logo_pos_y"))
        # Restore logo percentage position (for consistent positioning across resolutions)
        try:
            pct_x_saved = self.settings.get("logo_pct_x")
            pct_y_saved = self.settings.get("logo_pct_y")
            pct_sz_saved = self.settings.get("logo_pct_size")
            self._logo_pct_x = float(pct_x_saved) if pct_x_saved else None
            self._logo_pct_y = float(pct_y_saved) if pct_y_saved else None
            self._logo_pct_size = float(pct_sz_saved) if pct_sz_saved else None
        except: 
            self._logo_pct_x = None
            self._logo_pct_y = None
            self._logo_pct_size = None
        self.logo_cropped_pil=None
        # Tracks which logo file the cropped image belongs to (so a stale crop
        # from a previously-selected logo is never reused for a new one).
        self._logo_cropped_for_path=None
        self.transition_var=ctk.BooleanVar(value=self.settings.get("use_transition"))
        self.trans_dur_var=ctk.StringVar(value=str(self.settings.get("transition_duration")))
        self.intro_enabled_var=ctk.BooleanVar(value=self.settings.get("use_intro"))
        self.intro_var=ctk.StringVar(value="")
        self.bgm_enabled_var=ctk.BooleanVar(value=self.settings.get("use_bgm"))
        self.bgm_var=ctk.StringVar(value=self.settings.get("bgm_path"))
        self.bgm_vol_var=ctk.StringVar(value=str(self.settings.get("bgm_volume")))
        self.bgm_fade_var=ctk.StringVar(value=str(self.settings.get("bgm_fade")))
        self.bgm_loop_var=ctk.BooleanVar(value=bool(self.settings.get("bgm_loop")))
        self.bgm_xfade_var=ctk.BooleanVar(value=bool(self.settings.get("bgm_xfade")) if self.settings.get("bgm_xfade")!="" else True)
        self.bgm_prompt_var=ctk.StringVar(value=self.settings.get("bgm_prompt") or "")
        self.bgm_gen_dur_var=ctk.StringVar(value=str(self.settings.get("bgm_gen_dur") or 30))
        # Task 9: Master volume
        self.master_vol_var=ctk.IntVar(value=self.settings.get("master_volume"))
        self.master_tts_vol_var=ctk.IntVar(value=self.settings.get("master_tts_volume"))
        # Task 8: Common voice for Scene_N_ format
        self.common_voice_name=ctk.StringVar(value=self.settings.get("common_voice_name"))
        self.common_voice_id=ctk.StringVar(value=self.settings.get("common_voice_id"))
        self.model_var=ctk.StringVar(value=self.settings.get("last_model") or "eleven_multilingual_v2")
        self.models=getattr(self, "models", [])
        self._model_id_map=getattr(self, "_model_id_map", {})
        # ── Captions ──
        self.captions_enabled_var=ctk.BooleanVar(value=self.settings.get("captions_enabled"))
        self.caption_font_path_var=ctk.StringVar(value=self.settings.get("caption_font_path"))
        self.caption_font_size_var=ctk.IntVar(value=self.settings.get("caption_font_size"))
        self.caption_font_color_var=ctk.StringVar(value=self.settings.get("caption_font_color"))
        self.caption_bg_color_var=ctk.StringVar(value=self.settings.get("caption_bg_color"))
        self.caption_bg_opacity_var=ctk.DoubleVar(value=self.settings.get("caption_bg_opacity"))
        self.caption_max_chars_var=ctk.IntVar(value=self.settings.get("caption_max_chars"))
        self.caption_max_lines_var=ctk.IntVar(value=self.settings.get("caption_max_lines"))
        self.caption_position_var=ctk.StringVar(value=self.settings.get("caption_position"))
        self.caption_margin_var=ctk.IntVar(value=self.settings.get("caption_margin_bottom"))
        self.caption_animation_var=ctk.StringVar(value=self.settings.get("caption_animation"))
        self.caption_words_var=ctk.IntVar(value=self.settings.get("caption_words_per_group"))
        self._caption_groups={}
        self.blend_text_enabled_var=ctk.BooleanVar(value=self.settings.get("blend_text_enabled"))
        self.blend_text_font_size_var=ctk.IntVar(value=self.settings.get("blend_text_font_size"))
        self.blend_text_font_color_var=ctk.StringVar(value=self.settings.get("blend_text_font_color"))
        self.blend_text_position_var=ctk.StringVar(value=self.settings.get("blend_text_position"))
        self.blend_text_margin_var=ctk.IntVar(value=self.settings.get("blend_text_margin"))
        self.blend_text_animation_var=ctk.StringVar(value=self.settings.get("blend_text_animation"))
        self.blend_text_font_path_var=ctk.StringVar(value=self.settings.get("blend_text_font_path"))
        self.blend_text_align_var=ctk.StringVar(value=self.settings.get("blend_text_align"))
        self.blend_text_border_w_var=ctk.IntVar(value=self.settings.get("blend_text_border_w"))
        self.blend_text_border_color_var=ctk.StringVar(value=self.settings.get("blend_text_border_color"))
        self.blend_text_bg_color_var=ctk.StringVar(value=self.settings.get("blend_text_bg_color"))
        self.blend_text_bg_opacity_var=ctk.DoubleVar(value=self.settings.get("blend_text_bg_opacity"))
        self.blend_text_shadow_var=ctk.BooleanVar(value=self.settings.get("blend_text_shadow"))
        self._blend_texts={}
        # ── Blend Video (green-screen lower-third) + SFX ──
        self.blend_video_enabled_var=ctk.BooleanVar(value=self.settings.get("blend_video_enabled"))
        self.blend_video_key_color_var=ctk.StringVar(value=self.settings.get("blend_video_key_color"))
        self.blend_video_similarity_var=ctk.DoubleVar(value=float(self.settings.get("blend_video_similarity")))
        self.blend_video_blend_var=ctk.DoubleVar(value=float(self.settings.get("blend_video_blend")))
        self.blend_sfx_volume_var=ctk.DoubleVar(value=float(self.settings.get("blend_sfx_volume")))
        self.blend_sfx_duration_var=ctk.DoubleVar(value=float(self.settings.get("blend_sfx_duration")))
        self._blend_videos={}   # {scene_num: video_path}
        self._blend_sfx={}      # {scene_num: sfx_audio_path}
        self._blend_sfx_prompts={}   # {scene_num: prompt_text}
        self._build_ui()

    def _collect_master_settings(self) -> dict:
        data = {}
        vars_map = {
            "mode": getattr(self, "mode_var", None),
            "voice_name": getattr(self, "voice_name_var", None),
            "voice_id": getattr(self, "voice_id_var", None),
            "voice_speed": getattr(self, "voice_speed_var", None),
            "video_aspect": getattr(self, "video_aspect_var", None),
            "fps": getattr(self, "fps_var", None),
            "res": getattr(self, "res_var", None),
            "silence": getattr(self, "silence_var", None),
            "fx": getattr(self, "fx_var", None),
            "fx_intensity": getattr(self, "fx_intensity_var", None),
            "particle_overlay": getattr(self, "particle_overlay_var", None),
            "render_preset": getattr(self, "render_preset_var", None),
            "use_transition": getattr(self, "transition_var", None),
            "transition_duration": getattr(self, "trans_dur_var", None),
            "use_intro": getattr(self, "intro_enabled_var", None),
            "intro_path": getattr(self, "intro_var", None),
            "use_bgm": getattr(self, "bgm_enabled_var", None),
            "bgm_path": getattr(self, "bgm_var", None),
            "bgm_volume": getattr(self, "bgm_vol_var", None),
            "bgm_fade": getattr(self, "bgm_fade_var", None),
            "bgm_loop": getattr(self, "bgm_loop_var", None),
            "bgm_xfade": getattr(self, "bgm_xfade_var", None),
            "bgm_prompt": getattr(self, "bgm_prompt_var", None),
            "bgm_gen_dur": getattr(self, "bgm_gen_dur_var", None),
            "master_volume": getattr(self, "master_vol_var", None),
            "master_tts_volume": getattr(self, "master_tts_vol_var", None),
            "common_voice_name": getattr(self, "common_voice_name", None),
            "common_voice_id": getattr(self, "common_voice_id", None),
            "captions_enabled": getattr(self, "captions_enabled_var", None),
            "caption_font_path": getattr(self, "caption_font_path_var", None),
            "caption_font_size": getattr(self, "caption_font_size_var", None),
            "caption_font_color": getattr(self, "caption_font_color_var", None),
            "caption_bg_color": getattr(self, "caption_bg_color_var", None),
            "caption_bg_opacity": getattr(self, "caption_bg_opacity_var", None),
            "caption_max_chars": getattr(self, "caption_max_chars_var", None),
            "caption_max_lines": getattr(self, "caption_max_lines_var", None),
            "caption_position": getattr(self, "caption_position_var", None),
            "caption_margin_bottom": getattr(self, "caption_margin_var", None),
            "caption_animation": getattr(self, "caption_animation_var", None),
            "caption_words_per_group": getattr(self, "caption_words_var", None),
            "logo_path": getattr(self, "logo_path_var", None),
        }
        for k, v in vars_map.items():
            if v is not None:
                try: data[k] = v.get()
                except Exception: pass
        return data

    def _apply_master_settings(self, data: dict):
        if not isinstance(data, dict): return
        vars_map = {
            "mode": getattr(self, "mode_var", None),
            "voice_name": getattr(self, "voice_name_var", None),
            "voice_id": getattr(self, "voice_id_var", None),
            "voice_speed": getattr(self, "voice_speed_var", None),
            "video_aspect": getattr(self, "video_aspect_var", None),
            "fps": getattr(self, "fps_var", None),
            "res": getattr(self, "res_var", None),
            "silence": getattr(self, "silence_var", None),
            "fx": getattr(self, "fx_var", None),
            "fx_intensity": getattr(self, "fx_intensity_var", None),
            "particle_overlay": getattr(self, "particle_overlay_var", None),
            "render_preset": getattr(self, "render_preset_var", None),
            "use_transition": getattr(self, "transition_var", None),
            "transition_duration": getattr(self, "trans_dur_var", None),
            "use_intro": getattr(self, "intro_enabled_var", None),
            "intro_path": getattr(self, "intro_var", None),
            "use_bgm": getattr(self, "bgm_enabled_var", None),
            "bgm_path": getattr(self, "bgm_var", None),
            "bgm_volume": getattr(self, "bgm_vol_var", None),
            "bgm_fade": getattr(self, "bgm_fade_var", None),
            "bgm_loop": getattr(self, "bgm_loop_var", None),
            "bgm_xfade": getattr(self, "bgm_xfade_var", None),
            "bgm_prompt": getattr(self, "bgm_prompt_var", None),
            "bgm_gen_dur": getattr(self, "bgm_gen_dur_var", None),
            "master_volume": getattr(self, "master_vol_var", None),
            "master_tts_volume": getattr(self, "master_tts_vol_var", None),
            "common_voice_name": getattr(self, "common_voice_name", None),
            "common_voice_id": getattr(self, "common_voice_id", None),
            "captions_enabled": getattr(self, "captions_enabled_var", None),
            "caption_font_path": getattr(self, "caption_font_path_var", None),
            "caption_font_size": getattr(self, "caption_font_size_var", None),
            "caption_font_color": getattr(self, "caption_font_color_var", None),
            "caption_bg_color": getattr(self, "caption_bg_color_var", None),
            "caption_bg_opacity": getattr(self, "caption_bg_opacity_var", None),
            "caption_max_chars": getattr(self, "caption_max_chars_var", None),
            "caption_max_lines": getattr(self, "caption_max_lines_var", None),
            "caption_position": getattr(self, "caption_position_var", None),
            "caption_margin_bottom": getattr(self, "caption_margin_var", None),
            "caption_animation": getattr(self, "caption_animation_var", None),
            "caption_words_per_group": getattr(self, "caption_words_var", None),
            "logo_path": getattr(self, "logo_path_var", None),
        }
        for k, v in vars_map.items():
            if v is not None and k in data and data[k] is not None:
                try: v.set(data[k])
                except Exception: pass

    def _build_ui(self):
        self.grid_columnconfigure(1,weight=1); self.grid_rowconfigure(0,weight=1)
        sb=ctk.CTkScrollableFrame(self,width=380,fg_color=C["card"],corner_radius=0)
        sb.grid(row=0,column=0,sticky="nsew"); sb.grid_columnconfigure(0,weight=1)
        self._sb_ref=sb  # subclasses (ShortsEditorFrame) inject extra sections here
        ctk.CTkButton(sb, text="? Help", fg_color="#1e222b", hover_color="#323845",
                      text_color="#9aa0aa", height=28, font=("Segoe UI",10),
                      command=lambda: _show_tab_help(self._tab_help_title(), self._tab_help_steps())).grid(row=999, column=0, sticky="ew", padx=6, pady=(4,8))
        
        tool_id = getattr(self, "PRESET_TOOL_ID", "advance_editor")
        self.preset_widget = preset_manager.PresetWidget(
            sb, tool_id=tool_id,
            collect_fn=self._collect_master_settings,
            apply_fn=self._apply_master_settings
        )
        self.preset_widget.grid(row=0, column=0, sticky="ew", padx=6, pady=(6,2))
        row=1
        def sec(p,t,color=C["purple"]):
            f=ctk.CTkFrame(p,fg_color=C["card"],border_color=C["border"],border_width=1,corner_radius=8)
            ctk.CTkLabel(f,text=f"█  {t.upper()}",text_color=color,font=("Segoe UI",13,"bold")).pack(anchor="w",padx=8,pady=(5,2))
            return f

        # ── Mode Selector ──
        mode_sec=ctk.CTkFrame(sb,fg_color=C["card"],border_color=C["accent"],border_width=2,corner_radius=8)
        mode_sec.grid(row=row,column=0,sticky="ew",padx=6,pady=(6,4)); row+=1
        ctk.CTkLabel(mode_sec,text="MODE",text_color=C["accent"],font=("Segoe UI",11,"bold")).pack(anchor="w",padx=8,pady=(4,2))
        mf=ctk.CTkFrame(mode_sec,fg_color="transparent"); mf.pack(fill="x",padx=5,pady=(0,5))
        self.mode_var=ctk.StringVar(value="script")
        ctk.CTkRadioButton(mf,text="Script & Video",variable=self.mode_var,value="script",
            text_color=C["text"],fg_color=C["accent"],command=self._toggle_mode).pack(side="left",padx=8)
        ctk.CTkRadioButton(mf,text="Only Video",variable=self.mode_var,value="video",
            text_color=C["text"],fg_color=C["orange"],command=self._toggle_mode).pack(side="left",padx=8)

        # ── Only Video Mode Panel (hidden by default) ──
        self.video_mode_frame=ctk.CTkFrame(sb,fg_color=C["card"],border_color=C["orange"],border_width=1,corner_radius=8)
        # Don't grid it yet — _toggle_mode will show/hide
        self._video_mode_row=row; row+=1
        ctk.CTkLabel(self.video_mode_frame,text="█  ONLY VIDEO MODE",text_color=C["orange"],font=("Segoe UI",12,"bold")).pack(anchor="w",padx=8,pady=(5,2))
        ctk.CTkLabel(self.video_mode_frame,text="Upload videos → auto blocks → optional TTS text",text_color=C["dim"],font=("Segoe UI",8)).pack(anchor="w",padx=10)
        vmbtn=ctk.CTkFrame(self.video_mode_frame,fg_color="transparent"); vmbtn.pack(fill="x",padx=5,pady=4)
        ctk.CTkButton(vmbtn,text="📁 Upload Videos",fg_color=C["orange"],text_color="#000",width=130,height=30,
            font=("Segoe UI",10,"bold"),command=self._only_video_upload).pack(side="left",padx=3)
        ctk.CTkButton(vmbtn,text="📂 Upload Folder",fg_color=C["orange"],text_color="#000",width=120,height=30,
            command=self._only_video_folder).pack(side="left",padx=3)
        ctk.CTkLabel(self.video_mode_frame,text="Insert Text (optional — for TTS on specific scenes):",
            text_color=C["dim"],font=("Segoe UI",9)).pack(anchor="w",padx=10,pady=(5,0))
        ctk.CTkLabel(self.video_mode_frame,text="Format: Scene_1_: text | Scene_2_: text",
            text_color=C["dim"],font=("Segoe UI",8)).pack(anchor="w",padx=10)
        self.vm_text_box=ctk.CTkTextbox(self.video_mode_frame,height=70,fg_color=C["entry_bg"],text_color=C["text"],
            border_color=C["border"],border_width=1,font=("Consolas",10))
        self.vm_text_box.pack(fill="x",padx=5,pady=3)
        vmtbtn=ctk.CTkFrame(self.video_mode_frame,fg_color="transparent"); vmtbtn.pack(fill="x",padx=5,pady=(2,5))
        ctk.CTkButton(vmtbtn,text="📝 Insert Text to Blocks",fg_color=C["green"],text_color="#000",width=160,height=28,
            font=("Segoe UI",10,"bold"),command=self._insert_text_to_blocks).pack(side="left",padx=3)
        self.vm_status=ctk.CTkLabel(vmtbtn,text="",text_color=C["dim"],font=("Segoe UI",9))
        self.vm_status.pack(side="left",padx=8)

        # ── Script Mode sections (existing) ──
        self.script_mode_start_row=row

        # ── GPU Info ──
        gpu_sec=sec(sb,"GPU / Encoder",C["green"]); gpu_sec.grid(row=row,column=0,sticky="ew",padx=6,pady=(6,4)); row+=1
        ctk.CTkLabel(gpu_sec,text=f"🖥  {GPU.info_str()}",text_color=C["green"],font=("Consolas",10)).pack(anchor="w",padx=8,pady=(2,6))

        # ── API ──
        # ── Voice Studio & TTS Engine ──
        api=sec(sb,"🎙  Voice Studio & TTS Engine",C["accent"]); api.grid(row=row,column=0,sticky="ew",padx=6,pady=(2,4)); row+=1
        
        # Row 0: API Key + Fetch Voices
        kf=ctk.CTkFrame(api,fg_color="transparent"); kf.pack(fill="x",padx=5,pady=2)
        ctk.CTkLabel(kf,text="Key:",text_color=C["dim"],width=35).pack(side="left")
        self.api_entry=ctk.CTkEntry(kf,show="*",fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"])
        self.api_entry.pack(side="left",fill="x",expand=True,padx=5)
        if self.settings.get("api_key") and self.settings.get("api_key") != "sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt":
            self.api_entry.insert(0, self.settings.get("api_key"))
        self.api_key = self.api_entry
        self._key_visible = False
        def _toggle_key():
            self._key_visible = not self._key_visible
            self.api_entry.configure(show="" if self._key_visible else "*")
            btn_key.configure(text="🙈" if self._key_visible else "👁")
        btn_key = ctk.CTkButton(kf, text="👁", width=30, height=26, fg_color=C["btn"], hover_color=C["btn_hov"], text_color=C["text"], command=_toggle_key)
        btn_key.pack(side="left", padx=(0,4))
        ctk.CTkButton(kf, text="Fetch Voices", width=95, height=26, fg_color="#06B6D4", hover_color="#0891B2", command=self._fetch_voices_threaded).pack(side="left")

        # Row 1: Voice Provider
        pf=ctk.CTkFrame(api,fg_color="transparent"); pf.pack(fill="x",padx=5,pady=2)
        ctk.CTkLabel(pf,text="Provider:",text_color=C["dim"],width=70,anchor="w").pack(side="left")
        self.model_menu=ctk.CTkComboBox(pf,values=["All Providers", "ElevenLabs", "Minimax", "FishAudio", "Edge Neural", "Kokoro", "Vbee", "Cloned Voices"], height=26, state="readonly", command=lambda v: self._provider_changed(v), fg_color=C["entry_bg"], border_color=C["border"])
        self.model_menu.pack(side="left",fill="x",expand=True)
        self.model_menu.set("All Providers")

        # Row 2: Sub-Model
        smf=ctk.CTkFrame(api,fg_color="transparent"); smf.pack(fill="x",padx=5,pady=2)
        ctk.CTkLabel(smf,text="Sub-Model:",text_color=C["dim"],width=70,anchor="w").pack(side="left")
        self.submodel_menu=ctk.CTkComboBox(smf,values=["All Models / Sub-Models"], height=26, state="readonly", command=lambda v: self._filter_voices(), fg_color=C["entry_bg"], border_color=C["border"])
        self.submodel_menu.pack(side="left",fill="x",expand=True)

        # Row 3: Search Voices
        sf=ctk.CTkFrame(api,fg_color="transparent"); sf.pack(fill="x",padx=5,pady=2)
        ctk.CTkLabel(sf,text="Search:",text_color=C["dim"],width=70,anchor="w").pack(side="left")
        self.voice_search=ctk.CTkEntry(sf,placeholder_text="Type voice name or ID...", height=26, fg_color=C["entry_bg"], border_color=C["border"])
        self.voice_search.pack(side="left",fill="x",expand=True,padx=(0,4))
        self.voice_search.bind("<KeyRelease>", lambda e: self._filter_voices())
        ctk.CTkButton(sf, text="Refresh", width=55, height=26, fg_color=C["btn"], command=self._fetch_voices_threaded).pack(side="left", padx=(0, 2))
        ctk.CTkButton(sf, text="Clear", width=45, height=26, fg_color="transparent", border_width=1, border_color=C["border"], command=self._clear_voice_search).pack(side="left")

        # Row 4: Scrollable Voice Library
        ctk.CTkLabel(api, text="Voice Library:", text_color=C["dim"], anchor="w").pack(fill="x", padx=5, pady=(4, 1))
        self.voice_list_scroll = ctk.CTkScrollableFrame(api, height=160, fg_color=C["entry_bg"], border_width=1, border_color=C["border"])
        self.voice_list_scroll.pack(fill="x", padx=5, pady=2)

        # Row 5: Voice ID
        vidf=ctk.CTkFrame(api,fg_color="transparent"); vidf.pack(fill="x",padx=5,pady=2)
        ctk.CTkLabel(vidf,text="Voice ID:",text_color=C["dim"],width=70,anchor="w").pack(side="left")
        self.voice_id=ctk.CTkEntry(vidf,placeholder_text="Auto-filled or paste Voice ID", height=26, fg_color=C["entry_bg"], border_color=C["border"])
        self.voice_id.pack(side="left",fill="x",expand=True,padx=(0, 4))
        if hasattr(self, "common_voice_id") and self.common_voice_id.get():
            self.voice_id.insert(0, self.common_voice_id.get())
        ctk.CTkButton(vidf, text="▶ Test Voice", width=85, height=26, fg_color=C["purple"], hover_color="#7C3AED", font=("Segoe UI", 9, "bold"), command=self.play_voice_preview).pack(side="left")

        # Row 6: Voice Speed Slider
        vsdf=ctk.CTkFrame(api,fg_color="transparent"); vsdf.pack(fill="x",padx=5,pady=2)
        ctk.CTkLabel(vsdf,text="Speed:",text_color=C["dim"],width=70,anchor="w").pack(side="left")
        self.tts_speed_slider = ctk.CTkSlider(vsdf, from_=0.8, to=1.5, number_of_steps=14, height=14, command=lambda v: self.tts_speed_label.configure(text=f"{float(v):.2f}x"))
        self.tts_speed_slider.pack(side="left", fill="x", expand=True, padx=4)
        self.tts_speed_slider.set(1.0)
        self.tts_speed_label = ctk.CTkLabel(vsdf, text="1.00x", width=45, text_color=C["accent"], font=("Segoe UI", 9))
        self.tts_speed_label.pack(side="left")

        # Row 7: Parallel TTS Workers Slider
        pwf=ctk.CTkFrame(api,fg_color="transparent"); pwf.pack(fill="x",padx=5,pady=2)
        ctk.CTkLabel(pwf,text="Workers:",text_color=C["dim"],width=70,anchor="w").pack(side="left")
        self.parallel_tts = ctk.CTkSlider(pwf, from_=1, to=10, number_of_steps=9, height=14, command=lambda v: self.parallel_tts_label.configure(text=f"{int(v)} workers"))
        self.parallel_tts.pack(side="left", fill="x", expand=True, padx=4)
        self.parallel_tts.set(6)
        self.parallel_tts_label = ctk.CTkLabel(pwf, text="6 workers", width=65, text_color=C["accent"], font=("Segoe UI", 9))
        self.parallel_tts_label.pack(side="left")
        self.after(100, self._auto_load_voices_on_init)

        # Row 8: Status Label
        self.api_status = ctk.CTkLabel(api, text="AI33 Ready", font=("Segoe UI", 9), text_color=C["dim"])
        self.api_status.pack(fill="x", padx=5, pady=(2, 4))
        self.api_status_lbl = self.api_status

        # ── Story ──
        story=sec(sb,"Story Script"); story.grid(row=row,column=0,sticky="ew",padx=6,pady=4); row+=1
        ctk.CTkLabel(story,text="CharName: text  OR  Scene_1_: text  OR  Scene_2_: text",text_color=C["dim"],font=("Segoe UI",9)).pack(anchor="w",padx=5)
        self.story_box=ctk.CTkTextbox(story,height=130,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"],border_width=1,font=("Consolas",11))
        self.story_box.pack(fill="x",padx=5,pady=5)
        btf=ctk.CTkFrame(story,fg_color="transparent"); btf.pack(fill="x",padx=5,pady=(0,5))
        ctk.CTkButton(btf,text="Analyze",fg_color=C["purple"],text_color="#fff",height=30,command=self._analyze).pack(side="left",padx=3)
        ctk.CTkButton(btf,text="Create Blocks",fg_color=C["green"],text_color="#000",height=30,command=self._create_blocks).pack(side="left",padx=3)
        ctk.CTkButton(btf,text="📁 Upload Media",fg_color=C["accent"],text_color="#000",height=30,command=self._bulk_upload_media).pack(side="left",padx=3)

        # ── Blend Text ──
        blend=sec(sb,"Blend Text (Overlay on Scene)",C["accent"]); blend.grid(row=row,column=0,sticky="ew",padx=6,pady=4); row+=1
        ctk.CTkCheckBox(blend,text="Enable Blend Text",variable=self.blend_text_enabled_var,text_color=C["text"],fg_color=C["accent"]).pack(anchor="w",padx=8,pady=3)
        ctk.CTkLabel(blend,text="Scene_1: text | Scene_2: text | or just text for all",text_color=C["dim"],font=("Segoe UI",8)).pack(anchor="w",padx=10)
        self.blend_box=ctk.CTkTextbox(blend,height=55,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"],border_width=1,font=("Consolas",10))
        self.blend_box.pack(fill="x",padx=5,pady=3)
        blf1=ctk.CTkFrame(blend,fg_color="transparent"); blf1.pack(fill="x",padx=5,pady=2)
        ctk.CTkButton(blf1,text="Parse",width=60,height=24,fg_color=C["accent"],text_color="#000",command=self._parse_blend_text).pack(side="left",padx=2)
        ctk.CTkButton(blf1,text="Apply All",width=70,height=24,fg_color=C["green"],text_color="#000",
            font=("Segoe UI",9,"bold"),command=self._apply_blend_to_blocks).pack(side="left",padx=2)
        ctk.CTkButton(blf1,text="👁 Preview",width=70,height=24,fg_color=C["purple"],text_color="#fff",
            font=("Segoe UI",9),command=self._preview_blend_text).pack(side="left",padx=2)
        self.blend_status_lbl=ctk.CTkLabel(blf1,text="OFF",text_color=C["dim"],font=("Segoe UI",9))
        self.blend_status_lbl.pack(side="left",padx=6)
        # Font
        blf1b=ctk.CTkFrame(blend,fg_color="transparent"); blf1b.pack(fill="x",padx=5,pady=2)
        ctk.CTkButton(blf1b,text="Font",width=50,height=22,fg_color=C["btn"],text_color=C["text"],font=("Segoe UI",8),
            command=lambda:self._sel_blend_font()).pack(side="left",padx=2)
        self.blend_font_lbl=ctk.CTkLabel(blf1b,text=os.path.basename(self.blend_text_font_path_var.get()) or "Default (Arial)",
            text_color=C["dim"],font=("Segoe UI",8)); self.blend_font_lbl.pack(side="left",padx=5)
        # Size, color, border
        blf2=ctk.CTkFrame(blend,fg_color="transparent"); blf2.pack(fill="x",padx=5,pady=2)
        ctk.CTkLabel(blf2,text="Size:",text_color=C["dim"]).pack(side="left")
        ctk.CTkEntry(blf2,textvariable=self.blend_text_font_size_var,width=35,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"]).pack(side="left",padx=2)
        ctk.CTkLabel(blf2,text="Color:",text_color=C["dim"]).pack(side="left",padx=(4,0))
        ctk.CTkEntry(blf2,textvariable=self.blend_text_font_color_var,width=55,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"]).pack(side="left",padx=2)
        ctk.CTkLabel(blf2,text="Brdr:",text_color=C["dim"]).pack(side="left",padx=(4,0))
        ctk.CTkEntry(blf2,textvariable=self.blend_text_border_w_var,width=25,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"]).pack(side="left",padx=2)
        ctk.CTkEntry(blf2,textvariable=self.blend_text_border_color_var,width=50,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"]).pack(side="left",padx=2)
        # BG color, opacity, shadow
        blf2b=ctk.CTkFrame(blend,fg_color="transparent"); blf2b.pack(fill="x",padx=5,pady=2)
        ctk.CTkLabel(blf2b,text="BG:",text_color=C["dim"]).pack(side="left")
        ctk.CTkEntry(blf2b,textvariable=self.blend_text_bg_color_var,width=55,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"]).pack(side="left",padx=2)
        ctk.CTkLabel(blf2b,text="Opa:",text_color=C["dim"]).pack(side="left",padx=(4,0))
        ctk.CTkSlider(blf2b,from_=0.0,to=1.0,variable=self.blend_text_bg_opacity_var,width=70).pack(side="left",padx=2)
        ctk.CTkCheckBox(blf2b,text="Shadow",variable=self.blend_text_shadow_var,text_color=C["text"],fg_color=C["accent"],width=18).pack(side="left",padx=4)
        # Position, align, margin, animation
        blf3=ctk.CTkFrame(blend,fg_color="transparent"); blf3.pack(fill="x",padx=5,pady=2)
        ctk.CTkLabel(blf3,text="Pos:",text_color=C["dim"]).pack(side="left")
        ctk.CTkOptionMenu(blf3,variable=self.blend_text_position_var,fg_color=C["btn"],text_color=C["text"],values=["top","center","bottom"],width=70).pack(side="left",padx=2)
        ctk.CTkLabel(blf3,text="Align:",text_color=C["dim"]).pack(side="left",padx=(4,0))
        ctk.CTkOptionMenu(blf3,variable=self.blend_text_align_var,fg_color=C["btn"],text_color=C["text"],values=["left","center","right"],width=60).pack(side="left",padx=2)
        ctk.CTkLabel(blf3,text="Margin:",text_color=C["dim"]).pack(side="left",padx=(4,0))
        ctk.CTkEntry(blf3,textvariable=self.blend_text_margin_var,width=30,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"]).pack(side="left",padx=2)
        blf4=ctk.CTkFrame(blend,fg_color="transparent"); blf4.pack(fill="x",padx=5,pady=(2,5))
        ctk.CTkLabel(blf4,text="Anim:",text_color=C["dim"]).pack(side="left")
        ctk.CTkOptionMenu(blf4,variable=self.blend_text_animation_var,fg_color=C["btn"],text_color=C["text"],values=CAPTION_ANIMATIONS,width=100).pack(side="left",padx=2)

        # ── Blend Video (green-screen lower-third) + SFX ──
        bvid=sec(sb,"Blend Video (Lower-Third + SFX)",C["green"]); bvid.grid(row=row,column=0,sticky="ew",padx=6,pady=4); row+=1
        ctk.CTkCheckBox(bvid,text="Enable Blend Video",variable=self.blend_video_enabled_var,
            text_color=C["text"],fg_color=C["green"]).pack(anchor="w",padx=8,pady=3)
        ctk.CTkLabel(bvid,text="Green-screen lower-third videos. Files named Scene_1_*, Scene_2_* auto-map.",
            text_color=C["dim"],font=("Segoe UI",8),wraplength=350,justify="left").pack(anchor="w",padx=10)
        # Upload row
        bvb1=ctk.CTkFrame(bvid,fg_color="transparent"); bvb1.pack(fill="x",padx=5,pady=3)
        ctk.CTkButton(bvb1,text="📁 Upload Videos",width=120,height=26,fg_color=C["green"],text_color="#000",
            font=("Segoe UI",9,"bold"),command=self._sel_blend_videos).pack(side="left",padx=2)
        ctk.CTkButton(bvb1,text="📂 Folder",width=70,height=26,fg_color=C["green"],text_color="#000",
            font=("Segoe UI",9),command=self._sel_blend_videos_folder).pack(side="left",padx=2)
        ctk.CTkButton(bvb1,text="✕ Clear",width=60,height=26,fg_color=C["btn"],text_color=C["red"],
            font=("Segoe UI",9),command=self._clear_blend_videos).pack(side="left",padx=2)
        self.blend_video_status_lbl=ctk.CTkLabel(bvb1,text="(0 mapped)",text_color=C["dim"],font=("Segoe UI",9))
        self.blend_video_status_lbl.pack(side="left",padx=4)
        # Chroma key controls
        bvb2=ctk.CTkFrame(bvid,fg_color="transparent"); bvb2.pack(fill="x",padx=5,pady=2)
        ctk.CTkLabel(bvb2,text="Key:",text_color=C["dim"]).pack(side="left")
        ctk.CTkEntry(bvb2,textvariable=self.blend_video_key_color_var,width=60,fg_color=C["entry_bg"],
            text_color=C["text"],border_color=C["border"]).pack(side="left",padx=2)
        ctk.CTkLabel(bvb2,text="Sim:",text_color=C["dim"]).pack(side="left",padx=(6,0))
        ctk.CTkSlider(bvb2,from_=0.05,to=0.8,variable=self.blend_video_similarity_var,width=70).pack(side="left",padx=2)
        self.blend_sim_lbl=ctk.CTkLabel(bvb2,text=f"{self.blend_video_similarity_var.get():.2f}",
            text_color=C["text"],width=35,font=("Consolas",9))
        self.blend_sim_lbl.pack(side="left")
        self.blend_video_similarity_var.trace_add("write",lambda*a:self.blend_sim_lbl.configure(
            text=f"{self.blend_video_similarity_var.get():.2f}"))
        ctk.CTkLabel(bvb2,text="Blnd:",text_color=C["dim"]).pack(side="left",padx=(6,0))
        ctk.CTkSlider(bvb2,from_=0.0,to=0.4,variable=self.blend_video_blend_var,width=60).pack(side="left",padx=2)
        self.blend_blnd_lbl=ctk.CTkLabel(bvb2,text=f"{self.blend_video_blend_var.get():.2f}",
            text_color=C["text"],width=35,font=("Consolas",9))
        self.blend_blnd_lbl.pack(side="left")
        self.blend_video_blend_var.trace_add("write",lambda*a:self.blend_blnd_lbl.configure(
            text=f"{self.blend_video_blend_var.get():.2f}"))
        # SFX section
        ctk.CTkLabel(bvid,text="── ElevenLabs Sound Effect (SFX for lower-third) ──",
            text_color=C["orange"],font=("Segoe UI",9,"bold")).pack(anchor="w",padx=8,pady=(8,2))
        ctk.CTkLabel(bvid,text="Per-scene prompt. Format: Scene_1_: whoosh transition | Scene_2_: sparkle",
            text_color=C["dim"],font=("Segoe UI",8),wraplength=350,justify="left").pack(anchor="w",padx=10)
        self.blend_sfx_box=ctk.CTkTextbox(bvid,height=55,fg_color=C["entry_bg"],text_color=C["text"],
            border_color=C["border"],border_width=1,font=("Consolas",10))
        self.blend_sfx_box.pack(fill="x",padx=5,pady=3)
        bvs1=ctk.CTkFrame(bvid,fg_color="transparent"); bvs1.pack(fill="x",padx=5,pady=2)
        ctk.CTkLabel(bvs1,text="Dur(s):",text_color=C["dim"]).pack(side="left")
        ctk.CTkEntry(bvs1,textvariable=self.blend_sfx_duration_var,width=45,fg_color=C["entry_bg"],
            text_color=C["text"],border_color=C["border"]).pack(side="left",padx=2)
        ctk.CTkLabel(bvs1,text="Vol:",text_color=C["dim"]).pack(side="left",padx=(6,0))
        ctk.CTkSlider(bvs1,from_=0.0,to=2.0,variable=self.blend_sfx_volume_var,width=70).pack(side="left",padx=2)
        self.blend_sfx_vol_lbl=ctk.CTkLabel(bvs1,text=f"{self.blend_sfx_volume_var.get():.2f}",
            text_color=C["text"],width=35,font=("Consolas",9))
        self.blend_sfx_vol_lbl.pack(side="left")
        self.blend_sfx_volume_var.trace_add("write",lambda*a:self.blend_sfx_vol_lbl.configure(
            text=f"{self.blend_sfx_volume_var.get():.2f}"))
        bvs2=ctk.CTkFrame(bvid,fg_color="transparent"); bvs2.pack(fill="x",padx=5,pady=(2,6))
        ctk.CTkButton(bvs2,text="🎵 Generate SFX",width=130,height=26,fg_color=C["orange"],text_color="#000",
            font=("Segoe UI",9,"bold"),command=self._gen_blend_sfx).pack(side="left",padx=2)
        ctk.CTkButton(bvs2,text="✕ Clear SFX",width=80,height=26,fg_color=C["btn"],text_color=C["red"],
            font=("Segoe UI",9),command=self._clear_blend_sfx).pack(side="left",padx=2)
        self.blend_sfx_status_lbl=ctk.CTkLabel(bvs2,text="(0 SFX)",text_color=C["dim"],font=("Segoe UI",9))
        self.blend_sfx_status_lbl.pack(side="left",padx=4)

        # ── Characters ──
        chars=sec(sb,"Characters & Voices"); chars.grid(row=row,column=0,sticky="ew",padx=6,pady=4); row+=1
        self.clf=ctk.CTkFrame(chars,fg_color="transparent"); self.clf.pack(fill="x",padx=5,pady=3)
        ctk.CTkLabel(self.clf,text="No characters yet",text_color=C["dim"]).pack(anchor="w")

        # ── Audio ──
        pad=sec(sb,"Audio"); pad.grid(row=row,column=0,sticky="ew",padx=6,pady=4); row+=1
        pf=ctk.CTkFrame(pad,fg_color="transparent"); pf.pack(fill="x",padx=5,pady=3)
        ctk.CTkLabel(pf,text="Silence pad(s):",text_color=C["dim"]).pack(side="left")
        self.silence_var=ctk.DoubleVar(value=self.settings.get("silence_pad"))
        ctk.CTkEntry(pf,textvariable=self.silence_var,width=50,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"]).pack(side="left",padx=5)
        # Task 9: Master volume
        mvf=ctk.CTkFrame(pad,fg_color="transparent"); mvf.pack(fill="x",padx=5,pady=3)
        ctk.CTkLabel(mvf,text="Clip Master Vol:",text_color=C["dim"]).pack(side="left")
        ctk.CTkSlider(mvf,from_=0,to=100,variable=self.master_vol_var,width=120).pack(side="left",padx=3)
        self.mvol_lbl=ctk.CTkLabel(mvf,text=f"{self.master_vol_var.get()}%",text_color=C["text"],width=40)
        self.mvol_lbl.pack(side="left")
        self.master_vol_var.trace_add("write",lambda*a:self.mvol_lbl.configure(text=f"{self.master_vol_var.get()}%"))
        ctk.CTkLabel(mvf,text="TTS Vol:",text_color=C["dim"]).pack(side="left",padx=(10,0))
        ctk.CTkSlider(mvf,from_=0,to=100,variable=self.master_tts_vol_var,width=100).pack(side="left",padx=3)
        self.mtvol_lbl=ctk.CTkLabel(mvf,text=f"{self.master_tts_vol_var.get()}%",text_color=C["text"],width=40)
        self.mtvol_lbl.pack(side="left")
        self.master_tts_vol_var.trace_add("write",lambda*a:self.mtvol_lbl.configure(text=f"{self.master_tts_vol_var.get()}%"))

        # Concurrency Threads for Advance Editor
        th_adv = ctk.CTkFrame(pad, fg_color="transparent")
        th_adv.pack(fill="x", padx=5, pady=(2, 4))
        
        at_adv = ctk.CTkFrame(th_adv, fg_color="transparent")
        at_adv.pack(fill="x", pady=2)
        ctk.CTkLabel(at_adv, text="Audio Thread:", text_color=C["dim"], font=("Segoe UI", 10, "bold"), width=120, anchor="w").pack(side="left")
        
        def _dec_tts_adv():
            global MAX_PARALLEL_TTS
            if MAX_PARALLEL_TTS > 1:
                MAX_PARALLEL_TTS -= 1
                self.adv_audio_th_lbl.configure(text=f"{MAX_PARALLEL_TTS} Threads")
                self.adv_audio_th_slider.set(MAX_PARALLEL_TTS)
                
        def _inc_tts_adv():
            global MAX_PARALLEL_TTS
            if MAX_PARALLEL_TTS < 16:
                MAX_PARALLEL_TTS += 1
                self.adv_audio_th_lbl.configure(text=f"{MAX_PARALLEL_TTS} Threads")
                self.adv_audio_th_slider.set(MAX_PARALLEL_TTS)
                
        def _on_tts_adv(v):
            global MAX_PARALLEL_TTS
            MAX_PARALLEL_TTS = int(float(v))
            self.adv_audio_th_lbl.configure(text=f"{MAX_PARALLEL_TTS} Threads")

        ctk.CTkButton(at_adv, text="−", width=24, height=22, font=("Segoe UI", 11, "bold"), fg_color=C["btn"], hover_color=C["btn_hov"], command=_dec_tts_adv).pack(side="left", padx=(0, 3))
        self.adv_audio_th_slider = ctk.CTkSlider(at_adv, from_=1, to=16, number_of_steps=15, width=90, height=14, command=_on_tts_adv)
        self.adv_audio_th_slider.set(MAX_PARALLEL_TTS)
        self.adv_audio_th_slider.pack(side="left", padx=2)
        ctk.CTkButton(at_adv, text="+", width=24, height=22, font=("Segoe UI", 11, "bold"), fg_color=C["btn"], hover_color=C["btn_hov"], command=_inc_tts_adv).pack(side="left", padx=(3, 5))
        self.adv_audio_th_lbl = ctk.CTkLabel(at_adv, text=f"{MAX_PARALLEL_TTS} Threads", text_color=C["accent"], font=("Consolas", 10, "bold"), width=68)
        self.adv_audio_th_lbl.pack(side="left")

        vt_adv = ctk.CTkFrame(th_adv, fg_color="transparent")
        vt_adv.pack(fill="x", pady=2)
        ctk.CTkLabel(vt_adv, text="Editing Video Thread:", text_color=C["dim"], font=("Segoe UI", 10, "bold"), width=120, anchor="w").pack(side="left")
        
        def _dec_ff_adv():
            global MAX_PARALLEL_FF
            if MAX_PARALLEL_FF > 1:
                MAX_PARALLEL_FF -= 1
                self.adv_video_th_lbl.configure(text=f"{MAX_PARALLEL_FF} Threads")
                self.adv_video_th_slider.set(MAX_PARALLEL_FF)
                
        def _inc_ff_adv():
            global MAX_PARALLEL_FF
            if MAX_PARALLEL_FF < 12:
                MAX_PARALLEL_FF += 1
                self.adv_video_th_lbl.configure(text=f"{MAX_PARALLEL_FF} Threads")
                self.adv_video_th_slider.set(MAX_PARALLEL_FF)
                
        def _on_ff_adv(v):
            global MAX_PARALLEL_FF
            MAX_PARALLEL_FF = int(float(v))
            self.adv_video_th_lbl.configure(text=f"{MAX_PARALLEL_FF} Threads")

        ctk.CTkButton(vt_adv, text="−", width=24, height=22, font=("Segoe UI", 11, "bold"), fg_color=C["btn"], hover_color=C["btn_hov"], command=_dec_ff_adv).pack(side="left", padx=(0, 3))
        self.adv_video_th_slider = ctk.CTkSlider(vt_adv, from_=1, to=12, number_of_steps=11, width=90, height=14, command=_on_ff_adv)
        self.adv_video_th_slider.set(MAX_PARALLEL_FF)
        self.adv_video_th_slider.pack(side="left", padx=2)
        ctk.CTkButton(vt_adv, text="+", width=24, height=22, font=("Segoe UI", 11, "bold"), fg_color=C["btn"], hover_color=C["btn_hov"], command=_inc_ff_adv).pack(side="left", padx=(3, 5))
        self.adv_video_th_lbl = ctk.CTkLabel(vt_adv, text=f"{MAX_PARALLEL_FF} Threads", text_color=C["accent"], font=("Consolas", 10, "bold"), width=68)
        self.adv_video_th_lbl.pack(side="left")

        # ── Logo ──
        logo=sec(sb,"Logo / Watermark"); logo.grid(row=row,column=0,sticky="ew",padx=6,pady=4); row+=1
        ctk.CTkCheckBox(logo,text="Enable Logo",variable=self.logo_enabled_var,text_color=C["text"],
            fg_color=C["green"]).pack(anchor="w",padx=8,pady=3)
        ctk.CTkButton(logo,text="Select Logo",width=200,fg_color=C["accent"],text_color="#000",command=self._sel_logo).pack(padx=5,pady=3)
        self.logo_lbl=ctk.CTkLabel(logo,text=os.path.basename(self.logo_path_var.get()) or "(none)",text_color=C["dim"],font=("Segoe UI",9)); self.logo_lbl.pack(padx=5)
        lf=ctk.CTkFrame(logo,fg_color="transparent"); lf.pack(fill="x",padx=5,pady=3)
        ctk.CTkLabel(lf,text="Size:",text_color=C["dim"]).pack(side="left")
        ctk.CTkSlider(lf,from_=20,to=400,variable=self.logo_size_var,width=100).pack(side="left",padx=3)
        ctk.CTkLabel(lf,text="Opacity:",text_color=C["dim"]).pack(side="left",padx=(8,0))
        ctk.CTkSlider(lf,from_=10,to=100,variable=self.logo_opacity_var,width=100).pack(side="left",padx=3)
        lf2=ctk.CTkFrame(logo,fg_color="transparent"); lf2.pack(fill="x",padx=5,pady=3)
        ctk.CTkLabel(lf2,text="Anchor:",text_color=C["dim"]).pack(side="left")
        ctk.CTkOptionMenu(lf2,variable=self.logo_anchor_var,fg_color=C["btn"],text_color=C["text"],
            values=["top-left","top-right","bottom-left","bottom-right","center"],width=120).pack(side="left",padx=3)
        ctk.CTkButton(logo,text="🎯 Preview & Position Logo (Drag)",width=200,fg_color=C["purple"],text_color="#fff",
            font=("Segoe UI",11,"bold"),command=self._logo_preview).pack(padx=5,pady=(4,6))

        # ── Transition ──
        trans=sec(sb,"Transition"); trans.grid(row=row,column=0,sticky="ew",padx=6,pady=4); row+=1
        ctk.CTkCheckBox(trans,text="Enable Fade",variable=self.transition_var,text_color=C["text"],fg_color=C["purple"]).pack(anchor="w",padx=5,pady=3)
        tf=ctk.CTkFrame(trans,fg_color="transparent"); tf.pack(fill="x",padx=5,pady=3)
        ctk.CTkLabel(tf,text="Duration(s):",text_color=C["dim"]).pack(side="left")
        ctk.CTkEntry(tf,textvariable=self.trans_dur_var,width=55,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"]).pack(side="left",padx=3)

        # ── Intro ──
        intro=sec(sb,"Intro Videos"); self._intro_section=intro; intro.grid(row=row,column=0,sticky="ew",padx=6,pady=4); row+=1
        ctk.CTkCheckBox(intro,text="Enable Intro",variable=self.intro_enabled_var,text_color=C["text"],
            fg_color=C["green"]).pack(anchor="w",padx=8,pady=3)
        ctk.CTkButton(intro,text="Select Intro(s)",width=200,fg_color=C["accent"],text_color="#000",command=self._sel_intros).pack(padx=5,pady=3)
        self.intro_lbl=ctk.CTkLabel(intro,text="(none)",text_color=C["dim"],font=("Segoe UI",9)); self.intro_lbl.pack(padx=5)

        # ── BGM ──
        bgm=sec(sb,"Background Music"); bgm.grid(row=row,column=0,sticky="ew",padx=6,pady=4); row+=1
        self._bgm_section_frame = bgm
        ctk.CTkCheckBox(bgm,text="Enable BGM",variable=self.bgm_enabled_var,text_color=C["text"],
            fg_color=C["green"]).pack(anchor="w",padx=8,pady=3)
        ctk.CTkButton(bgm,text="Select BGM",width=200,fg_color=C["accent"],text_color="#000",command=self._sel_bgm).pack(padx=5,pady=3)
        self.bgm_lbl=ctk.CTkLabel(bgm,text=os.path.basename(self.bgm_var.get()) or "(none)",text_color=C["dim"],font=("Segoe UI",9)); self.bgm_lbl.pack(padx=5)
        bf2=ctk.CTkFrame(bgm,fg_color="transparent"); bf2.pack(fill="x",padx=5,pady=3)
        ctk.CTkLabel(bf2,text="Vol:",text_color=C["dim"]).pack(side="left")
        ctk.CTkEntry(bf2,textvariable=self.bgm_vol_var,width=50,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"]).pack(side="left",padx=3)
        ctk.CTkLabel(bf2,text="Fade(s):",text_color=C["dim"]).pack(side="left",padx=(8,0))
        ctk.CTkEntry(bf2,textvariable=self.bgm_fade_var,width=50,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"]).pack(side="left",padx=3)
        bf3=ctk.CTkFrame(bgm,fg_color="transparent"); bf3.pack(fill="x",padx=5,pady=(0,4))
        ctk.CTkCheckBox(bf3,text="Loop BGM",variable=self.bgm_loop_var,text_color=C["text"],
            fg_color=C["green"],font=("Segoe UI",11),width=20).pack(side="left",padx=(3,8))
        ctk.CTkButton(bf3,text="▶ Preview",width=80,height=26,fg_color=C["accent"],text_color="#000",
            font=("Segoe UI",10),command=self._preview_bgm).pack(side="left",padx=2)
        ctk.CTkButton(bf3,text="■ Stop",width=60,height=26,fg_color=C["btn"],hover_color=C["red"],
            text_color=C["text"],font=("Segoe UI",10),command=self._stop_bgm_preview).pack(side="left",padx=2)
        ctk.CTkCheckBox(bf3,text="Crossfade loop",variable=self.bgm_xfade_var,text_color=C["text"],
            fg_color=C["purple"],font=("Segoe UI",10),width=20).pack(side="left",padx=(8,2))
        # ── AI BGM generation (ElevenLabs Music) ──
        gline=ctk.CTkFrame(bgm,fg_color="#1f1730",corner_radius=8); gline.pack(fill="x",padx=5,pady=(2,5))
        ctk.CTkLabel(gline,text="🎵 Generate BGM (AI) — describe the music",text_color=C["purple"],
            font=("Segoe UI",10,"bold")).pack(anchor="w",padx=8,pady=(5,2))
        ctk.CTkEntry(gline,textvariable=self.bgm_prompt_var,width=240,
            placeholder_text="e.g. soft cinematic piano, calm, emotional, instrumental",
            fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"]).pack(fill="x",padx=8,pady=2)
        gl2=ctk.CTkFrame(gline,fg_color="transparent"); gl2.pack(fill="x",padx=8,pady=(2,6))
        ctk.CTkLabel(gl2,text="Duration(s):",text_color=C["dim"]).pack(side="left")
        ctk.CTkEntry(gl2,textvariable=self.bgm_gen_dur_var,width=50,fg_color=C["entry_bg"],
            text_color=C["text"],border_color=C["border"]).pack(side="left",padx=4)
        ctk.CTkButton(gl2,text="✨ Generate",width=110,height=28,fg_color=C["purple"],text_color="#fff",
            font=("Segoe UI",10,"bold"),command=self._generate_bgm).pack(side="left",padx=4)

        # ── Captions ──
        cap=sec(sb,"Captions / Subtitles",C["orange"]); self._cap_section=cap; cap.grid(row=row,column=0,sticky="ew",padx=6,pady=4); row+=1
        ctk.CTkCheckBox(cap,text="Enable Captions",variable=self.captions_enabled_var,text_color=C["text"],
            fg_color=C["orange"]).pack(anchor="w",padx=8,pady=3)
        # Font upload
        capf1=ctk.CTkFrame(cap,fg_color="transparent"); capf1.pack(fill="x",padx=5,pady=2)
        ctk.CTkButton(capf1,text="Upload Font",width=100,height=24,fg_color=C["accent"],text_color="#000",
            font=("Segoe UI",9),command=self._sel_caption_font).pack(side="left",padx=3)
        self.cap_font_lbl=ctk.CTkLabel(capf1,text=os.path.basename(self.caption_font_path_var.get()) or "Hindi → Noto Sans Devanagari.ttf",
            text_color=C["dim"],font=("Segoe UI",8)); self.cap_font_lbl.pack(side="left",padx=5)
        # Font size & color
        capf2=ctk.CTkFrame(cap,fg_color="transparent"); capf2.pack(fill="x",padx=5,pady=2)
        ctk.CTkLabel(capf2,text="Size:",text_color=C["dim"]).pack(side="left")
        ctk.CTkEntry(capf2,textvariable=self.caption_font_size_var,width=40,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"]).pack(side="left",padx=3)
        ctk.CTkLabel(capf2,text="Color:",text_color=C["dim"]).pack(side="left",padx=(8,0))
        ctk.CTkEntry(capf2,textvariable=self.caption_font_color_var,width=65,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"]).pack(side="left",padx=3)
        # BG color & opacity
        capf3=ctk.CTkFrame(cap,fg_color="transparent"); capf3.pack(fill="x",padx=5,pady=2)
        ctk.CTkLabel(capf3,text="BG:",text_color=C["dim"]).pack(side="left")
        ctk.CTkEntry(capf3,textvariable=self.caption_bg_color_var,width=65,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"]).pack(side="left",padx=3)
        ctk.CTkLabel(capf3,text="Opacity:",text_color=C["dim"]).pack(side="left",padx=(8,0))
        ctk.CTkSlider(capf3,from_=0.0,to=1.0,variable=self.caption_bg_opacity_var,width=80).pack(side="left",padx=3)
        self.cap_opa_lbl=ctk.CTkLabel(capf3,text=f"{int(self.caption_bg_opacity_var.get()*100)}%",text_color=C["text"],width=30)
        self.cap_opa_lbl.pack(side="left")
        self.caption_bg_opacity_var.trace_add("write",lambda*a:self.cap_opa_lbl.configure(text=f"{int(self.caption_bg_opacity_var.get()*100)}%"))
        # Max chars, lines, words per group
        capf4=ctk.CTkFrame(cap,fg_color="transparent"); capf4.pack(fill="x",padx=5,pady=2)
        ctk.CTkLabel(capf4,text="Chars/line:",text_color=C["dim"]).pack(side="left")
        ctk.CTkEntry(capf4,textvariable=self.caption_max_chars_var,width=35,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"]).pack(side="left",padx=3)
        ctk.CTkLabel(capf4,text="Lines:",text_color=C["dim"]).pack(side="left",padx=(6,0))
        ctk.CTkOptionMenu(capf4,variable=self.caption_max_lines_var,fg_color=C["btn"],text_color=C["text"],values=["1","2","3"],width=50,
            command=lambda v:self.caption_max_lines_var.set(int(v))).pack(side="left",padx=3)
        ctk.CTkLabel(capf4,text="Words:",text_color=C["dim"]).pack(side="left",padx=(6,0))
        ctk.CTkEntry(capf4,textvariable=self.caption_words_var,width=30,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"]).pack(side="left",padx=3)
        # Position & margin
        capf5=ctk.CTkFrame(cap,fg_color="transparent"); capf5.pack(fill="x",padx=5,pady=2)
        ctk.CTkLabel(capf5,text="Position:",text_color=C["dim"]).pack(side="left")
        ctk.CTkOptionMenu(capf5,variable=self.caption_position_var,fg_color=C["btn"],text_color=C["text"],
            values=["bottom","center","top"],width=90).pack(side="left",padx=3)
        ctk.CTkLabel(capf5,text="Margin:",text_color=C["dim"]).pack(side="left",padx=(8,0))
        ctk.CTkEntry(capf5,textvariable=self.caption_margin_var,width=40,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"]).pack(side="left",padx=3)
        # Animation style
        capf6=ctk.CTkFrame(cap,fg_color="transparent"); capf6.pack(fill="x",padx=5,pady=2)
        ctk.CTkLabel(capf6,text="Animation:",text_color=C["dim"]).pack(side="left")
        ctk.CTkOptionMenu(capf6,variable=self.caption_animation_var,fg_color=C["btn"],text_color=C["text"],
            values=CAPTION_ANIMATIONS,width=130).pack(side="left",padx=3)
        # Buttons: Generate captions, Preview
        capf7=ctk.CTkFrame(cap,fg_color="transparent"); capf7.pack(fill="x",padx=5,pady=(4,6))
        ctk.CTkButton(capf7,text="📝 Generate Captions",width=140,height=28,fg_color=C["orange"],text_color="#000",
            font=("Segoe UI",10,"bold"),command=self._gen_captions).pack(side="left",padx=3)
        ctk.CTkButton(capf7,text="👁 Preview",width=80,height=28,fg_color=C["purple"],text_color="#fff",
            font=("Segoe UI",10),command=self._preview_captions).pack(side="left",padx=3)
        self.cap_status_lbl=ctk.CTkLabel(capf7,text="OFF",text_color=C["dim"],font=("Segoe UI",9))
        self.cap_status_lbl.pack(side="left",padx=8)
        # Color presets
        capf8=ctk.CTkFrame(cap,fg_color="transparent"); capf8.pack(fill="x",padx=5,pady=(0,5))
        for n,fc,bg in [("White","FFFFFF","000000"),("Yellow","FFD700","000000"),("Cyan","00FFFF","000000"),
            ("Green","00FF88","000000"),("Red","FF4444","000000"),("Pink","FF69B4","1A001A"),
            ("Neon","39FF14","000000"),("Gold","FFD700","1A1A00")]:
            ctk.CTkButton(capf8,text=n,width=55,height=22,fg_color=C["btn"],hover_color=C["accent"],text_color=C["text"],
                font=("Segoe UI",8),command=lambda fc=fc,bg=bg:(self.caption_font_color_var.set(fc),self.caption_bg_color_var.set(bg))).pack(side="left",padx=1)

        # ════════ RIGHT PANEL ════════
        right=ctk.CTkFrame(self,fg_color=C["bg"],corner_radius=0); right.grid(row=0,column=1,sticky="nsew")
        right.grid_columnconfigure(0,weight=1); right.grid_rowconfigure(1,weight=1)
        tb=ctk.CTkFrame(right,fg_color=C["card"],height=50); tb.grid(row=0,column=0,sticky="ew",padx=5,pady=5)
        self._toolbar_ref=tb
        ctk.CTkLabel(tb,text="█  SCENE BLOCKS",text_color=C["purple"],font=("Segoe UI",14,"bold")).pack(side="left",padx=10,pady=7)
        ctk.CTkLabel(tb,text="Show:",text_color=C["dim"]).pack(side="left",padx=(15,3))
        self.filter_var=ctk.StringVar(value="All")
        self.filter_menu=ctk.CTkOptionMenu(tb,variable=self.filter_var,fg_color=C["btn"],text_color=C["text"],
            values=["All"],command=self._on_filter,width=140)
        self.filter_menu.pack(side="left",padx=3,pady=7)
        # Professional unified upload button — accepts videos + images, auto-maps Scene_N_
        ctk.CTkButton(tb,text="📁 Upload Videos/Images",fg_color=C["green"],text_color="#fff",width=180,height=32,
            font=("Segoe UI",11,"bold"),command=self._adv_bulk_upload_smart).pack(side="left",padx=5,pady=7)
        # Task 7: Add video-only blocks
        ctk.CTkButton(tb,text="+ Video Block",fg_color=C["orange"],text_color="#000",width=100,command=self._add_video_block).pack(side="left",padx=5,pady=7)
        self.bkf=ctk.CTkScrollableFrame(right,fg_color=C["bg"])
        self.bkf.grid(row=1,column=0,sticky="nsew",padx=5,pady=5); self.bkf.grid_columnconfigure(0,weight=1)
        bb=ctk.CTkFrame(right,fg_color=C["card"]); bb.grid(row=2,column=0,sticky="ew",padx=5,pady=5); bb.grid_columnconfigure(0,weight=1)
        ar=ctk.CTkFrame(bb,fg_color="transparent"); ar.grid(row=0,column=0,sticky="ew",padx=5,pady=(6,2))
        # Task 4: Separate audio generate button
        ctk.CTkButton(ar,text="🔊 Gen Audio",fg_color=C["orange"],text_color="#000",width=100,height=34,
            font=("Segoe UI",11,"bold"),command=self._gen_all_audio).pack(side="left",padx=3)
        # Save reference so Jesus tab can hide Generate All (it uses single-click merge)
        self._gen_all_btn = ctk.CTkButton(ar,text="🎬 Generate All",fg_color=C["green"],text_color="#000",width=110,height=34,
            font=("Segoe UI",12,"bold"),command=self._gen_all)
        self._gen_all_btn.pack(side="left",padx=3)
        ctk.CTkButton(ar,text="Merge Final",fg_color=C["accent"],text_color="#000",width=100,height=34,
            font=("Segoe UI",12,"bold"),command=self._merge).pack(side="left",padx=3)
        # Task 10: Stop button
        ctk.CTkButton(ar,text="⏹ Stop",fg_color=C["red"],text_color="#fff",width=70,height=34,
            command=self._stop_gen).pack(side="left",padx=3)
        # Task 11: Clean button
        ctk.CTkButton(ar,text="🗑 Clean",fg_color=C["btn"],text_color=C["dim"],width=70,height=34,
            command=self._clean_all).pack(side="left",padx=3)
        ctk.CTkButton(ar,text="✕ Del All",fg_color=C["btn"],text_color=C["red"],width=70,height=34,
            font=("Segoe UI",10,"bold"),command=self._delete_all_blocks).pack(side="left",padx=3)
        self.stl=ctk.CTkLabel(ar,text="Ready",text_color=C["dim"],font=("Segoe UI",11),anchor="w")
        self.stl.pack(side="left",padx=10,fill="x",expand=True)
        pr=ctk.CTkFrame(bb,fg_color="transparent"); pr.grid(row=1,column=0,sticky="ew",padx=5,pady=(2,6)); pr.grid_columnconfigure(0,weight=1)
        self.progress=ctk.CTkProgressBar(pr,height=14,fg_color=C["border"],progress_color=C["green"])
        self.progress.grid(row=0,column=0,sticky="ew",padx=(4,8)); self.progress.set(0)
        self.ssl=ctk.CTkLabel(pr,text="",text_color=C["accent"],font=("Consolas",10),width=320,anchor="e")
        self.ssl.grid(row=0,column=1,sticky="e",padx=4)

    # ── Sidebar helpers ──
    def _sel_logo(self):
        p=filedialog.askopenfilename(filetypes=[("Images","*.png *.jpg *.jpeg *.webp *.bmp")])
        if p:
            self.logo_path_var.set(p); self.logo_lbl.configure(text=os.path.basename(p))
            # New logo chosen → drop any cached/cropped version of the OLD logo
            self.logo_cropped_pil=None
            self._logo_cropped_for_path=None
    def _sel_intros(self):
        ps=filedialog.askopenfilenames(filetypes=[("Videos","*.mp4 *.mov *.avi *.mkv *.webm")])
        if ps: self.intro_var.set(";".join(ps)); self.intro_lbl.configure(text=f"{len(ps)} file(s)")
    def _sel_bgm(self):
        p=filedialog.askopenfilename(filetypes=[("Audio","*.mp3 *.wav *.aac *.ogg *.m4a")])
        if p: self.bgm_var.set(p); self.bgm_lbl.configure(text=os.path.basename(p))

    def _make_bgm_xfade_loop(self, bgm, target_dur, xf=1.5):
        """Build a seamless looped BGM (>= target_dur) by crossfading repeats of the
        track into each other, so the loop point never 'jumps'."""
        try:
            D=get_duration(bgm)
            if D<=0.3: return bgm
            if D>=target_dur+0.05: return bgm           # already long enough
            xf=max(0.3, min(xf, D*0.30))                # crossfade <= ~1/3 of the clip
            n=int(math.ceil((target_dur - D)/max(0.1,(D - xf))) + 1)
            n=max(2, min(n, 40))
            inputs=[]
            for _ in range(n): inputs += ["-i", bgm]
            fc=[]; cur="0:a"
            for i in range(1, n):
                nxt=f"x{i}"
                fc.append(f"[{cur}][{i}:a]acrossfade=d={xf:.2f}:c1=tri:c2=tri[{nxt}]")
                cur=nxt
            out=os.path.join(TEMP_DIR,"bgm_xfade_loop.m4a")
            cmd=["ffmpeg","-y"]+inputs+["-filter_complex",";".join(fc),"-map",f"[{cur}]",
                 "-t",f"{target_dur:.3f}","-c:a","aac","-b:a","192k","-loglevel","error",out]
            r=_run_ff(cmd, timeout=600)
            return out if (os.path.exists(out) and get_duration(out)>0.5) else bgm
        except Exception as e:
            print("[BGM-XFADE]", e); return bgm

    def _generate_bgm(self):
        """Generate instrumental BGM from a text prompt via ElevenLabs Music API
        (POST /v1/music) for the requested duration, then set it as the BGM."""
        try: key=self.api_entry.get().strip()
        except Exception: key=self.settings.get("api_key")
        if not key:
            messagebox.showwarning("Generate BGM","Enter your ElevenLabs API key first (top of the editor)."); return
        prompt=(self.bgm_prompt_var.get() or "").strip()
        if not prompt:
            messagebox.showwarning("Generate BGM","Describe the music in the prompt box first.\nE.g. 'soft cinematic piano, calm, emotional, instrumental'."); return
        try: dur_s=float(self.bgm_gen_dur_var.get() or 30)
        except Exception: dur_s=30.0
        ms=int(max(3.0, min(300.0, dur_s))*1000)   # API allows 3s–10min; cap at 5min for safety
        self._ss(f"Generating BGM ({int(ms/1000)}s)… this can take ~20–60s",C["orange"])
        def work():
            try:
                r=requests.post("https://api.elevenlabs.io/v1/music",
                    headers={"xi-api-key":key,"Content-Type":"application/json","Accept":"audio/mpeg"},
                    json={"prompt":prompt,"music_length_ms":ms,"model_id":"music_v1","force_instrumental":True},
                    timeout=300)
                ctype=r.headers.get("content-type","")
                if r.status_code==200 and ("audio" in ctype or len(r.content)>5000):
                    os.makedirs(TEMP_DIR,exist_ok=True)
                    out=os.path.join(TEMP_DIR,f"generated_bgm_{int(time.time())}.mp3")
                    with open(out,"wb") as f: f.write(r.content)
                    if get_duration(out)>0.5:
                        self.bgm_var.set(out)
                        self.after(0,lambda:(self.bgm_lbl.configure(text="🎵 "+os.path.basename(out)),
                                             self.bgm_enabled_var.set(True)))
                        self._ss(f"✓ BGM generated ({format_duration(get_duration(out))}). Use ▶ Preview to check volume.",C["green"])
                    else:
                        self._ss("BGM generation returned an unreadable file.",C["red"])
                else:
                    msg=""
                    try: msg=r.json().get("detail",{}).get("message","") or str(r.json())[:200]
                    except Exception: msg=r.text[:200]
                    self._ss(f"BGM generation failed ({r.status_code}). {msg[:120]}",C["red"])
                    print("[BGM-GEN] HTTP",r.status_code,msg)
            except Exception as e:
                self._ss(f"BGM generation error: {str(e)[:60]}",C["red"]); print("[BGM-GEN]",e)
        threading.Thread(target=work,daemon=True).start()

    def _bgm_vol_val(self):
        """BGM volume as a 0..2 gain. Accepts a fraction (0.15) OR a percent (15) —
        values above 2 are treated as a percent so the control 'just works'."""
        try: v=float(self.bgm_vol_var.get() or 0.15)
        except: v=0.15
        if v>2.0: v=v/100.0
        return max(0.0,min(2.0,v))

    def _preview_bgm(self):
        """Play the selected BGM at the chosen volume so the user can hear how loud
        it will be. Tries pygame; if that fails, bakes the volume into a short clip
        and opens it in the system player so it ALWAYS works."""
        p=self.bgm_var.get()
        if not p or not os.path.exists(p):
            messagebox.showwarning("Preview BGM","Select a BGM file first."); return
        vol=self._bgm_vol_val()
        loop_on = bool(getattr(self,"bgm_loop_var",None) and self.bgm_loop_var.get())
        # 1) try pygame (instant, has Stop)
        try:
            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            if pygame.mixer.get_init():
                pygame.mixer.music.load(p)
                pygame.mixer.music.set_volume(max(0.0,min(1.0,vol)))
                pygame.mixer.music.play(loops=-1 if loop_on else 0)
                self._ss(f"▶ BGM preview (vol {vol:.2f}) — use ■ Stop",C["accent"])
                return
        except Exception:
            pass
        # 2) fallback: bake the volume into a 30s clip and open in the system player
        try:
            self._ss("Preparing BGM preview...",C["orange"])
            prev=os.path.join(TEMP_DIR,"_bgm_preview.mp3")
            _run_ff(["ffmpeg","-y","-t","30","-i",p,"-filter:a",f"volume={vol}",
                     "-c:a","libmp3lame","-b:a","192k",prev],timeout=60)
            if os.path.exists(prev) and get_duration(prev)>0.1:
                if hasattr(os,"startfile"): os.startfile(prev)
                elif sys.platform=="darwin": subprocess.Popen(["open",prev])
                else: subprocess.Popen(["xdg-open",prev])
                self._ss(f"▶ BGM preview opened (vol {vol:.2f})",C["accent"])
            else:
                messagebox.showerror("Preview BGM","Could not prepare BGM preview.")
        except Exception as e:
            messagebox.showerror("Preview BGM",f"Could not play BGM:\n{e}")

    def _stop_bgm_preview(self):
        try:
            import pygame
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
            self._ss("■ BGM preview stopped",C["dim"])
        except Exception:
            pass

    # ── Blend Video (lower-third green-screen) helpers ──────────────────────
    def _map_blend_videos(self, paths):
        """Map uploaded blend videos to scene numbers using Scene_N_ in filename;
        if no scene number found, assign in upload order to sequential scene numbers."""
        if not paths: return 0
        mapped=0
        unscoped=[]
        for p in paths:
            n=extract_scene_number(p)
            if n is not None:
                self._blend_videos[n]=p; mapped+=1
            else:
                unscoped.append(p)
        # Anything without a scene number → assign to lowest unmapped scene numbers in order
        if unscoped:
            existing=set(self._blend_videos.keys())
            # Pick scenes from current blocks first; if not enough, start from 1
            candidate_nums=[b["num"] for b in self.blocks if b["num"] not in existing]
            i=0
            for p in unscoped:
                if i<len(candidate_nums):
                    self._blend_videos[candidate_nums[i]]=p; mapped+=1; i+=1
                else:
                    # No more scenes — fall back to next unused number
                    n=max(list(self._blend_videos.keys())+[0])+1
                    self._blend_videos[n]=p; mapped+=1
        return mapped

    def _sel_blend_videos(self):
        ps=filedialog.askopenfilenames(filetypes=[("Videos","*.mp4 *.mov *.avi *.mkv *.webm")])
        if not ps: return
        added=self._map_blend_videos(sort_files(list(ps)))
        self.blend_video_enabled_var.set(True)
        total=len(self._blend_videos)
        self.blend_video_status_lbl.configure(text=f"({total} mapped)",text_color=C["green"])
        self._ss(f"Blend videos: +{added} (total {total})",C["green"])

    def _sel_blend_videos_folder(self):
        d=filedialog.askdirectory()
        if not d: return
        paths=[]
        for fn in os.listdir(d):
            fp=os.path.join(d,fn)
            if os.path.isfile(fp) and fn.lower().endswith(VIDEO_EXTS): paths.append(fp)
        if not paths:
            messagebox.showinfo("Blend Video","No videos in that folder."); return
        added=self._map_blend_videos(sort_files(paths))
        self.blend_video_enabled_var.set(True)
        total=len(self._blend_videos)
        self.blend_video_status_lbl.configure(text=f"({total} mapped)",text_color=C["green"])
        self._ss(f"Blend videos: +{added} from folder (total {total})",C["green"])

    def _clear_blend_videos(self):
        self._blend_videos.clear()
        self.blend_video_status_lbl.configure(text="(0 mapped)",text_color=C["dim"])
        self._ss("Blend videos cleared",C["dim"])

    # ── Blend SFX (ElevenLabs Sound Effects) ─────────────────────────────────
    def _parse_blend_sfx_prompts(self):
        """Read the SFX prompt textbox; return {scene_num: prompt_text}.
        Same format as blend text: 'Scene_1_: prompt' or '1: prompt'."""
        raw=self.blend_sfx_box.get("1.0","end").strip()
        prompts={}
        if not raw: return prompts
        for line in raw.split("\n"):
            line=line.strip()
            if not line: continue
            m=re.match(r'(?i)scene[_\-\s]*(\d+)[_\-\s]*[:\-]?\s*(.+)',line)
            if m:
                sn=int(m.group(1)); t=m.group(2).strip()
                if t: prompts[sn]=t; continue
            m=re.match(r'^(\d+)\s*[:\-\)]\s*(.+)',line)
            if m:
                sn=int(m.group(1)); t=m.group(2).strip()
                if t: prompts[sn]=t; continue
        return prompts

    def _gen_blend_sfx(self):
        prompts=self._parse_blend_sfx_prompts()
        if not prompts:
            messagebox.showwarning("SFX","Enter prompts.\nFormat:\n  Scene_1_: whoosh transition\n  Scene_2_: sparkle ding"); return
        ak=self.api_entry.get().strip()
        if not ak:
            messagebox.showwarning("API","Enter ElevenLabs API key first."); return
        try: dur=float(self.blend_sfx_duration_var.get())
        except: dur=4.0
        dur=max(0.5,min(30.0,dur))
        self._blend_sfx_prompts=prompts
        self._ss(f"SFX: generating {len(prompts)}...",C["orange"])
        threading.Thread(target=self._gen_blend_sfx_worker,args=(prompts,ak,dur),daemon=True).start()

    def _gen_blend_sfx_worker(self,prompts,ak,dur):
        ok=0; fail=0
        for sn,prompt in prompts.items():
            if self._cancelled: break
            sfx_path=os.path.join(TEMP_DIR,f"adv_sfx_{sn}.mp3")
            self._sss(f"SFX #{sn}: {prompt[:30]}...")
            try:
                pl={"text":prompt,"duration_seconds":float(dur),"prompt_influence":0.3}
                r=requests.post("https://api.elevenlabs.io/v1/sound-generation",
                    headers={"xi-api-key":ak,"Content-Type":"application/json","Accept":"audio/mpeg"},
                    json=pl,timeout=120)
                if r.status_code==200:
                    ct=r.headers.get("content-type","")
                    if "audio" in ct or "octet-stream" in ct:
                        with open(sfx_path,"wb") as f: f.write(r.content)
                        if os.path.exists(sfx_path) and os.path.getsize(sfx_path)>1024:
                            self._blend_sfx[sn]=sfx_path; ok+=1
                            continue
                fail+=1
                self._sss(f"SFX #{sn} fail: HTTP {r.status_code}")
            except Exception as e:
                fail+=1
                self._sss(f"SFX #{sn} error: {str(e)[:40]}")
        total=len(self._blend_sfx)
        self.after(0,lambda:self.blend_sfx_status_lbl.configure(
            text=f"({total} SFX)",text_color=C["green"] if total else C["dim"]))
        self._ss(f"SFX done: ok={ok} fail={fail} total={total}",C["green"] if ok else C["red"])

    def _clear_blend_sfx(self):
        self._blend_sfx.clear()
        self._blend_sfx_prompts.clear()
        self.blend_sfx_status_lbl.configure(text="(0 SFX)",text_color=C["dim"])
        self._ss("SFX cleared",C["dim"])

    def _set_common_voice(self):
        """Task 8: Set common voice for Scene_N_ format scripts."""
        if not self.voice_list_full:
            messagebox.showinfo("Voices","Fetch Voices first."); return
        def pick(name,vid):
            self.common_voice_name.set(name); self.common_voice_id.set(vid)
            self.common_voice_lbl.configure(text=name)
            self._ss(f"Common voice: {name}",C["green"])
        VoiceSearchWindow(self,self.voice_list_full,self.common_voice_name.get(),pick,api_key=self.api_entry.get().strip())

    def _get_preview_bg(self):
        """Return a preview frame composed EXACTLY like the rendered output:
        the first available media is scaled into a 1920x1080 black-letterboxed
        canvas (same geometry the renderer uses). This guarantees the logo
        position shown in the preview matches the final video."""
        CW, CH = 1920, 1080
        raw = None
        src = None
        for b in self.blocks:
            mp = b.get("source_media", "")
            if mp and os.path.exists(mp):
                if is_image_file(mp):
                    try: raw = Image.open(mp).convert("RGBA"); src = mp; break
                    except: pass
                else:
                    try:
                        f = extract_frame(mp, 0.5)
                        if f is not None: raw = f.convert("RGBA"); src = mp; break
                    except: pass
        # Build a 1920x1080 canvas with the media letterboxed (matches output)
        canvas = Image.new("RGBA", (CW, CH), (0, 0, 0, 255))
        if raw is not None:
            iw, ih = raw.size
            if iw > 0 and ih > 0:
                scale = min(CW / iw, CH / ih)
                nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
                resized = raw.resize((nw, nh), Image.LANCZOS)
                canvas.paste(resized, ((CW - nw) // 2, (CH - nh) // 2), resized)
        return canvas, src

    def _logo_preview(self):
        lp=self.logo_path_var.get()
        if not lp or not os.path.exists(lp):
            messagebox.showwarning("Logo","Select a logo image first."); return
        bg,_=self._get_preview_bg()
        # Save preview frame dimensions for percentage calculation
        prev_w, prev_h = bg.size
        try: logo_pil=self.logo_cropped_pil if self.logo_cropped_pil else Image.open(lp).convert("RGBA")
        except Exception as e: messagebox.showerror("Logo",f"Cannot load logo: {e}"); return
        def cb(anchor,mx,my,sz,opa,cropped_pil,ax,ay):
            self.logo_anchor_var.set(anchor); self.logo_mx_var.set(mx); self.logo_my_var.set(my)
            self.logo_size_var.set(sz); self.logo_opacity_var.set(opa)
            # ═══════════════════════════════════════════════════════════
            # FIX: Save position AND size as a fraction of the preview frame.
            # Preview frame == output geometry (1920x1080 letterbox), so these
            # fractions reproduce the exact same placement at render time on
            # ANY output resolution.
            # ═════════════════════════════════════════════════════════════
            pct_x = ax / prev_w if prev_w > 0 else 0
            pct_y = ay / prev_h if prev_h > 0 else 0
            pct_size = sz / prev_w if prev_w > 0 else 0   # logo width as fraction of frame width
            self._logo_pct_x = pct_x
            self._logo_pct_y = pct_y
            self._logo_pct_size = pct_size
            # Also store pixel values for backward compatibility
            self.logo_pos_x_var.set(ax); self.logo_pos_y_var.set(ay)
            self.logo_cropped_pil=cropped_pil
            # Remember which logo file this cropped image came from
            self._logo_cropped_for_path = lp
            if cropped_pil is not None:
                try: cropped_pil.save(os.path.join(TEMP_DIR,"_logo_cropped_master.png"))
                except: pass
            self._ss(f"Logo: {anchor} ({pct_x*100:.1f}%, {pct_y*100:.1f}%) sz={sz} opa={opa}%",C["green"])
        # Seed the preview from stored fractions (so reopening shows the last placement)
        init_x = self.logo_pos_x_var.get(); init_y = self.logo_pos_y_var.get()
        init_sz = self.logo_size_var.get()
        if getattr(self, "_logo_pct_x", None) is not None and getattr(self, "_logo_pct_y", None) is not None:
            init_x = int(round(prev_w * self._logo_pct_x))
            init_y = int(round(prev_h * self._logo_pct_y))
        if getattr(self, "_logo_pct_size", None):
            init_sz = max(20, int(round(prev_w * self._logo_pct_size)))
        LogoPreviewWindow(self,bg,logo_pil,init_sz,self.logo_opacity_var.get(),cb,
            init_anchor=self.logo_anchor_var.get(),init_mx=self.logo_mx_var.get(),init_my=self.logo_my_var.get(),
            init_x=init_x,init_y=init_y)

    # ── Status helpers ──
    def _sp(self,f): self.after(0,lambda:self.progress.set(max(0,min(1,float(f)))))
    def _ss(self,t,c=None): self.after(0,lambda:self.stl.configure(text=t,text_color=c or C["dim"]))
    def _sss(self,t): self.after(0,lambda:self.ssl.configure(text=t))
    def _block_status(self,b,t,c):
        def _do():
            try: b["status_label"].configure(text=t,text_color=c)
            except: pass
        self.after(0,_do)

    # Task 10: Stop
    def _stop_gen(self):
        self._cancelled=True; self._ss("Stopping...",C["red"])

    # ── Auto-save settings ──
    def _save_settings(self):
        """Persist all current settings to disk — runs in background."""
        try:
            self.settings.set("api_key",self.api_entry.get().strip())
            self.settings.set("last_model",self.model_var.get())
            self.settings.set("silence_pad",self.silence_var.get())
            self.settings.set("master_volume",self.master_vol_var.get())
            self.settings.set("master_tts_volume",self.master_tts_vol_var.get())
            self.settings.set("use_logo",self.logo_enabled_var.get())
            self.settings.set("logo_path",self.logo_path_var.get())
            self.settings.set("logo_size",self.logo_size_var.get())
            self.settings.set("logo_opacity",self.logo_opacity_var.get())
            self.settings.set("logo_anchor",self.logo_anchor_var.get())
            self.settings.set("logo_margin_x",self.logo_mx_var.get())
            self.settings.set("logo_margin_y",self.logo_my_var.get())
            self.settings.set("logo_pos_x",self.logo_pos_x_var.get())
            self.settings.set("logo_pos_y",self.logo_pos_y_var.get())
            # Save percentage for consistent positioning across resolutions
            if hasattr(self, "_logo_pct_x") and self._logo_pct_x is not None:
                self.settings.set("logo_pct_x", self._logo_pct_x)
            if hasattr(self, "_logo_pct_y") and self._logo_pct_y is not None:
                self.settings.set("logo_pct_y", self._logo_pct_y)
            if getattr(self, "_logo_pct_size", None) is not None:
                self.settings.set("logo_pct_size", self._logo_pct_size)
            self.settings.set("use_transition",self.transition_var.get())
            self.settings.set("transition_duration",float(self.trans_dur_var.get() or 0.5))
            self.settings.set("use_intro",self.intro_enabled_var.get())
            self.settings.set("use_bgm",self.bgm_enabled_var.get())
            self.settings.set("bgm_path",self.bgm_var.get())
            self.settings.set("bgm_volume",float(self.bgm_vol_var.get() or 0.15))
            self.settings.set("bgm_fade",float(self.bgm_fade_var.get() or 2.0))
            self.settings.set("bgm_loop",bool(self.bgm_loop_var.get()))
            self.settings.set("bgm_xfade",bool(self.bgm_xfade_var.get()))
            self.settings.set("bgm_prompt",self.bgm_prompt_var.get())
            self.settings.set("bgm_gen_dur",self.bgm_gen_dur_var.get())
            self.settings.set("common_voice_name",self.common_voice_name.get())
            self.settings.set("common_voice_id",self.common_voice_id.get())
            # Captions
            self.settings.set("captions_enabled",self.captions_enabled_var.get())
            self.settings.set("caption_font_path",self.caption_font_path_var.get())
            self.settings.set("caption_font_size",self.caption_font_size_var.get())
            self.settings.set("caption_font_color",self.caption_font_color_var.get())
            self.settings.set("caption_bg_color",self.caption_bg_color_var.get())
            self.settings.set("caption_bg_opacity",self.caption_bg_opacity_var.get())
            self.settings.set("caption_max_chars",self.caption_max_chars_var.get())
            self.settings.set("caption_max_lines",self.caption_max_lines_var.get())
            self.settings.set("caption_position",self.caption_position_var.get())
            self.settings.set("caption_margin_bottom",self.caption_margin_var.get())
            self.settings.set("caption_animation",self.caption_animation_var.get())
            self.settings.set("caption_words_per_group",self.caption_words_var.get())
            self.settings.set("blend_text_enabled",self.blend_text_enabled_var.get())
            self.settings.set("blend_text_font_size",self.blend_text_font_size_var.get())
            self.settings.set("blend_text_font_color",self.blend_text_font_color_var.get())
            self.settings.set("blend_text_position",self.blend_text_position_var.get())
            self.settings.set("blend_text_margin",self.blend_text_margin_var.get())
            self.settings.set("blend_text_animation",self.blend_text_animation_var.get())
            self.settings.set("blend_text_align",self.blend_text_align_var.get())
            self.settings.set("blend_text_border_w",self.blend_text_border_w_var.get())
            self.settings.set("blend_text_shadow",self.blend_text_shadow_var.get())
            # Blend Video + SFX
            self.settings.set("blend_video_enabled",self.blend_video_enabled_var.get())
            self.settings.set("blend_video_key_color",self.blend_video_key_color_var.get())
            self.settings.set("blend_video_similarity",float(self.blend_video_similarity_var.get()))
            self.settings.set("blend_video_blend",float(self.blend_video_blend_var.get()))
            self.settings.set("blend_sfx_volume",float(self.blend_sfx_volume_var.get()))
            self.settings.set("blend_sfx_duration",float(self.blend_sfx_duration_var.get()))
            self.settings.save()
        except: pass

    # ── Mode Toggle ──
    def _toggle_mode(self):
        mode=self.mode_var.get()
        if mode=="video":
            self.video_mode_frame.grid(row=self._video_mode_row,column=0,sticky="ew",padx=6,pady=4)
        else:
            self.video_mode_frame.grid_forget()

    # ── Only Video Mode Methods ──
    def _only_video_upload(self):
        ps=filedialog.askopenfilenames(filetypes=[("Video","*.mp4 *.mov *.avi *.mkv *.webm *.flv")])
        if ps: self._create_blocks_from_videos(list(ps))

    def _only_video_folder(self):
        folder=filedialog.askdirectory(title="Video folder")
        if folder:
            exts={".mp4",".mov",".avi",".mkv",".webm",".flv"}
            ps=sorted([os.path.join(folder,f) for f in os.listdir(folder) if os.path.splitext(f)[1].lower() in exts])
            if ps: self._create_blocks_from_videos(ps)

    def _create_blocks_from_videos(self, paths):
        """Create blocks directly from video files — no script needed.
        Block UI is created immediately; thumbnail/duration extraction is queued
        on a background thread so 20+ video uploads don't freeze the app."""
        if not paths: return
        # Sort by scene number if available, else by name
        def sort_key(p):
            n=extract_scene_number(p)
            return n if n else 9999
        paths.sort(key=sort_key)
        for p in paths:
            sn=extract_scene_number(p)
            num=sn if sn else len(self.blocks)+1
            # Check if block with this num already exists
            exists=False
            for b in self.blocks:
                if b["num"]==num: exists=True; break
            if exists: continue
            # Create block
            char=f"Scene_{num}"
            if char not in self.characters:
                self.characters[char]={"voice_name":"","voice_id":"","color_idx":num%len(CHAR_COLORS),"is_scene":True}
            self._make_block(num,char,"",video_only=False)
            b=self.blocks[-1]
            b["source_media"]=p; b["media_type"]="video"; b["video"]=p
            # Heavy work goes to the queue — keeps the UI responsive during bulk upload
            self._queue_media_load(b, p, status_prefix="Video")
        self._update_filter()
        # Auto-assign voices if available
        if self.voice_list_full: self._auto_assign_voices()
        self.vm_status.configure(text=f"{len(paths)} videos → {len(self.blocks)} blocks",text_color=C["green"])
        self._ss(f"Created {len(paths)} blocks · loading thumbnails in background…",C["orange"])

    def _insert_text_to_blocks(self):
        """Insert text from Scene_N_: format to matching blocks."""
        raw=self.vm_text_box.get("1.0","end").strip()
        if not raw: messagebox.showwarning("Text","Enter text.\nFormat: Scene_1_: Your text here"); return
        inserted=0
        for line in raw.split("\n"):
            line=line.strip()
            if not line: continue
            m=re.match(r'(?i)scene[_\-\s]*(\d+)[_\-\s]*[:\-]?\s*(.+)',line)
            if not m:
                m=re.match(r'^(\d+)\s*[:\-\)]\s*(.+)',line)
            if m:
                sn=int(m.group(1)); text=m.group(2).strip()
                if not text: continue
                for b in self.blocks:
                    if b["num"]==sn:
                        b["text"]=text
                        # Update display text in UI
                        try:
                            d=text[:50]+"..." if len(text)>50 else text
                            # Find text label in block frame and update
                            for w in b["frame"].winfo_children():
                                for w2 in w.winfo_children():
                                    if isinstance(w2,ctk.CTkLabel) and hasattr(w2,'cget'):
                                        try:
                                            if w2.cget("wraplength")==250:
                                                w2.configure(text=d)
                                        except: pass
                        except: pass
                        b["status_label"].configure(text=f"Text added",text_color=C["green"])
                        inserted+=1; break
        if inserted>0:
            self.vm_status.configure(text=f"Inserted text in {inserted} blocks",text_color=C["green"])
            self._ss(f"Text inserted in {inserted} blocks",C["green"])
        else:
            self.vm_status.configure(text="No matching blocks",text_color=C["red"])

    # Task 11: Clean
    def _clean_all(self):
        # Delete temp files from disk
        cnt=clean_temp_files()
        TTSCache.clear_all()
        # Reset each block's generated data but keep structure
        for b in self.blocks:
            # ── Clear generated paths ──
            b["output"]=""
            b["tts_audio"]=""
            b["trimmed_loop_path"]=None
            # ── Reset thumbnail ──
            b["_ttk"]=None
            try:
                b["thumb_label"].configure(image=None, text="[no vid]")
            except:
                try: b["thumb_label"].configure(text="[no vid]")
                except: pass
            # ── Reset file label ──
            if not b.get("source_media"):
                try: b["file_label"].configure(text="[no media]")
                except: pass
            # ── Reset trim ──
            b["trim_start"]=None; b["trim_end"]=None
            try: b["trim_label"].configure(text="")
            except: pass
            # ── Reset status label ──
            try:
                if b.get("video_only"):
                    if b.get("source_media") and os.path.exists(b.get("source_media","")):
                        b["status_label"].configure(text="Video loaded",text_color=C["dim"])
                    else:
                        b["status_label"].configure(text="No video",text_color=C["orange"])
                else:
                    b["status_label"].configure(text="Pending",text_color=C["orange"])
            except: pass
            # ── Reload source thumbnail if source_media still exists ──
            sm=b.get("source_media","")
            if sm and os.path.exists(sm):
                try:
                    img=extract_frame(sm,0.5) if not is_image_file(sm) else Image.open(sm).convert("RGBA")
                    img.thumbnail((72,38),Image.LANCZOS)
                    tk=ImageTk.PhotoImage(img.convert("RGB"))
                    b["_ttk"]=tk
                    b["thumb_label"].configure(image=tk,text="")
                except: pass
        # ── Clear captions ──
        self._caption_groups.clear()
        try: self.cap_status_lbl.configure(text="OFF",text_color=C["dim"])
        except: pass
        # ── Clear blend text ──
        self._blend_texts.clear()
        try: self.blend_status_lbl.configure(text="OFF",text_color=C["dim"])
        except: pass
        # ── Reset progress ──
        try: self.progress.set(0)
        except: pass
        self._ss(f"✓ Cleaned {cnt} files + cache. {len(self.blocks)} blocks reset.",C["green"])

    def _delete_block(self, block_num):
        """Delete a single block by its number."""
        idx=None
        for i,b in enumerate(self.blocks):
            if b["num"]==block_num: idx=i; break
        if idx is None: return
        b=self.blocks[idx]
        # Destroy the UI frame
        try: b["frame"].destroy()
        except: pass
        self.blocks.pop(idx)
        # Clean up caption/blend data for this block
        self._caption_groups.pop(block_num, None)
        self._blend_texts.pop(block_num, None)
        self._ss(f"Deleted block #{block_num}. {len(self.blocks)} remaining.",C["orange"])

    def _delete_all_blocks(self):
        """Delete all blocks after confirmation."""
        if not self.blocks: return
        if not messagebox.askyesno("Delete All",f"Delete all {len(self.blocks)} blocks?\nThis cannot be undone."): return
        for b in self.blocks:
            try: b["frame"].destroy()
            except: pass
        self.blocks.clear()
        self._caption_groups.clear()
        self._blend_texts.clear()
        try: self.cap_status_lbl.configure(text="OFF",text_color=C["dim"])
        except: pass
        try: self.blend_status_lbl.configure(text="OFF",text_color=C["dim"])
        except: pass
        try: self.progress.set(0)
        except: pass
        # Clean temp files too
        cnt=clean_temp_files(); TTSCache.clear_all()
        self._ss(f"All blocks deleted. {cnt} temp files cleaned.",C["green"])

    # ── Captions ──
    def _sel_caption_font(self):
        p=filedialog.askopenfilename(filetypes=[("Font Files","*.ttf *.otf *.woff *.woff2"),("TrueType","*.ttf"),("OpenType","*.otf"),("All","*.*")])
        if p:
            self.caption_font_path_var.set(p)
            self.cap_font_lbl.configure(text=os.path.basename(p))
            self._ss(f"Caption font: {os.path.basename(p)}",C["green"])

    def _gen_captions(self):
        """Generate caption groups in background thread."""
        self._ss("Generating captions...",C["orange"])
        threading.Thread(target=self._gen_captions_worker,daemon=True).start()

    def _gen_captions_worker(self):
        self._save_settings()
        self._caption_groups.clear()
        count=0
        for b in self.blocks:
            if b.get("video_only"): continue
            text=b.get("text","").strip()
            if not text: continue
            ap=b.get("tts_audio","")
            if ap and os.path.exists(ap):
                dur=get_duration(ap)
            else:
                dur=estimate_tts_duration_from_text(text)
            if dur<=0.1: continue
            groups=generate_caption_groups_with_timing(
                text, dur,
                max_chars=self.caption_max_chars_var.get(),
                max_lines=self.caption_max_lines_var.get(),
                words_per_group=self.caption_words_var.get()
            )
            if groups:
                self._caption_groups[b["num"]]=groups
                count+=len(groups)
        def _upd():
            if count>0:
                self.captions_enabled_var.set(True)
                self.cap_status_lbl.configure(text=f"ON — {count} captions",text_color=C["green"])
                self._ss(f"Generated {count} captions for {len(self._caption_groups)} scenes",C["green"])
            else:
                self.cap_status_lbl.configure(text="No audio yet — gen audio first",text_color=C["red"])
        self.after(0,_upd)

    def _preview_captions(self):
        """Preview captions with realtime drag positioning."""
        if not self._caption_groups:
            messagebox.showinfo("Captions","Generate captions first."); return
        for b in self.blocks:
            num=b["num"]
            if num not in self._caption_groups: continue
            vp=b.get("output","") or b.get("source_media","")
            if not vp or not os.path.exists(vp): continue
            groups=self._caption_groups[num]
            CaptionPreviewWindow(self, vp, groups,
                font_size=self.caption_font_size_var.get(),
                font_color=self.caption_font_color_var.get().strip().lstrip("#"),
                bg_color=self.caption_bg_color_var.get().strip().lstrip("#"),
                bg_opacity=self.caption_bg_opacity_var.get(),
                position=self.caption_position_var.get(),
                margin=self.caption_margin_var.get(),
                callback=self._on_caption_pos_change)
            return
        messagebox.showinfo("Preview","No block with video + captions found.")

    def _on_caption_pos_change(self, position, margin):
        self.caption_position_var.set(position)
        self.caption_margin_var.set(margin)

    # ── Blend Text ──
    def _parse_blend_text(self):
        raw=self.blend_box.get("1.0","end").strip()
        if not raw: messagebox.showwarning("Blend","Enter text.\nFormats:\n  Scene_1_: text\n  Scene_1 text\n  1: text\n  1 text"); return
        self._blend_texts.clear()
        # Try multiple formats
        for line in raw.split("\n"):
            line=line.strip()
            if not line: continue
            # Format 1: Scene_1_: text  or  Scene 1: text
            m=re.match(r'(?i)scene[_\-\s]*(\d+)[_\-\s]*[:\-]?\s*(.+)',line)
            if m:
                sn=int(m.group(1)); t=m.group(2).strip()
                if t: self._blend_texts[sn]=t; continue
            # Format 2: 1: text  or  1) text
            m=re.match(r'^(\d+)\s*[:\-\)]\s*(.+)',line)
            if m:
                sn=int(m.group(1)); t=m.group(2).strip()
                if t: self._blend_texts[sn]=t; continue
        if self._blend_texts:
            self.blend_text_enabled_var.set(True)
            self.blend_status_lbl.configure(text=f"ON — {len(self._blend_texts)} scenes",text_color=C["green"])
            self._ss(f"Blend text: {len(self._blend_texts)} scenes",C["green"])
        else:
            self.blend_status_lbl.configure(text="No valid lines",text_color=C["red"])
            messagebox.showinfo("Blend","Formats:\n  Scene_1_: Your text\n  Scene_1 Your text\n  1: Your text")

    def _apply_blend_to_blocks(self):
        """Apply blend text to blocks — uses each block's OWN dialogue text.
        Style (font/size/color/animation) stays same across all, text is unique per scene."""
        if not self.blocks:
            messagebox.showwarning("Blend","No blocks to apply."); return
        raw=self.blend_box.get("1.0","end").strip()
        self._blend_texts.clear()
        if raw:
            # If user typed scene-specific text, parse that first
            lines=[l.strip() for l in raw.split("\n") if l.strip()]
            for line in lines:
                m=re.match(r'(?i)scene[_\-\s]*(\d+)[_\-\s]*[:\-]?\s*(.+)',line)
                if m:
                    sn=int(m.group(1)); t=m.group(2).strip()
                    if t: self._blend_texts[sn]=t; continue
                m=re.match(r'^(\d+)\s*[:\-\)]\s*(.+)',line)
                if m:
                    sn=int(m.group(1)); t=m.group(2).strip()
                    if t: self._blend_texts[sn]=t; continue
        # For any block NOT already assigned, use its own dialogue text
        added=0
        for b in self.blocks:
            num=b["num"]
            if num in self._blend_texts: continue  # already has custom text
            bt=b.get("text","").strip()
            if bt:
                self._blend_texts[num]=bt; added+=1
        total=len(self._blend_texts)
        if total>0:
            self.blend_text_enabled_var.set(True)
            self.blend_status_lbl.configure(text=f"ON — {total} scenes",text_color=C["green"])
            self._ss(f"Blend text: {total} scenes ({added} from dialogue)",C["green"])
        else:
            self.blend_status_lbl.configure(text="No text found",text_color=C["red"])

    def _sel_blend_font(self):
        p=filedialog.askopenfilename(filetypes=[("Font","*.ttf *.otf"),("All","*.*")])
        if p:
            self.blend_text_font_path_var.set(p)
            try: self.blend_font_lbl.configure(text=os.path.basename(p))
            except: pass

    def _preview_blend_text(self):
        """Preview blend text with drag positioning."""
        if not self._blend_texts:
            # Try apply first
            self._apply_blend_to_blocks()
        if not self._blend_texts:
            messagebox.showinfo("Blend","No blend text to preview."); return
        for b in self.blocks:
            num=b["num"]
            if num not in self._blend_texts: continue
            vp=b.get("output","") or b.get("source_media","")
            if not vp or not os.path.exists(vp): continue
            text=self._blend_texts[num]
            BlendTextPreviewWindow(self, vp, text,
                font_size=self.blend_text_font_size_var.get(),
                font_color=self.blend_text_font_color_var.get().strip().lstrip("#"),
                bg_color=self.blend_text_bg_color_var.get().strip().lstrip("#"),
                bg_opacity=self.blend_text_bg_opacity_var.get(),
                position=self.blend_text_position_var.get(),
                margin=self.blend_text_margin_var.get(),
                align=self.blend_text_align_var.get(),
                callback=self._on_blend_pos_change)
            return
        messagebox.showinfo("Preview","No block with video + blend text.")

    def _on_blend_pos_change(self, position, margin):
        self.blend_text_position_var.set(position)
        self.blend_text_margin_var.set(margin)

    def _safe_after(self, delay, fn):
        try:
            if hasattr(self, "winfo_exists") and self.winfo_exists():
                self.after(delay, fn)
        except Exception:
            pass

    # ── API ──
    def _fm(self):
        k=self.api_entry.get().strip() if (hasattr(self, "api_entry") and self.api_entry.winfo_exists()) else ""
        if not k: messagebox.showwarning("API","Enter key."); return
        if hasattr(self, "api_status_lbl"):
            self.api_status_lbl.configure(text="Fetching...",text_color=C["orange"])
        threading.Thread(target=self._fm_worker,args=(k,),daemon=True).start()
    def _fm_worker(self,k):
        try:
            r=requests.get("https://api.elevenlabs.io/v1/models",headers={"xi-api-key":k},timeout=15); r.raise_for_status()
            self.models=r.json(); ns=[m["name"] for m in self.models]
            def _upd():
                if hasattr(self, "model_menu"):
                    self.model_menu.configure(values=ns)
                lm=self.settings.get("last_model")
                if hasattr(self, "model_var"):
                    if lm in ns: self.model_var.set(lm)
                    elif ns: self.model_var.set(ns[0])
                if hasattr(self, "api_status_lbl"):
                    self.api_status_lbl.configure(text=f"✓ {len(ns)} models",text_color=C["green"])
            self._safe_after(0,_upd)
        except Exception as e:
            self._safe_after(0,lambda:hasattr(self, "api_status_lbl") and self.api_status_lbl.configure(text=f"✗ {e}",text_color=C["red"]))
    def _fv(self):
        k=self.api_entry.get().strip() if (hasattr(self, "api_entry") and self.api_entry.winfo_exists()) else ""
        if not k: messagebox.showwarning("API","Enter key."); return
        if hasattr(self, "api_status_lbl"):
            self.api_status_lbl.configure(text="Fetching voices...",text_color=C["orange"])
        threading.Thread(target=self._fv_worker,args=(k,),daemon=True).start()
    def _fv_worker(self,k):
        all_voices=[]; headers={"xi-api-key":k}
        try:
            r=requests.get("https://api.elevenlabs.io/v1/voices",headers=headers,timeout=20); r.raise_for_status()
            data=r.json(); voices_list=data.get("voices",[])
            if voices_list and not data.get("has_more",False):
                all_voices=voices_list
            else:
                all_voices=list(voices_list) if voices_list else []
                page_token=data.get("next_page_token")
                while page_token:
                    params={"page_size":100,"next_page_token":page_token}
                    r2=requests.get("https://api.elevenlabs.io/v1/voices",headers=headers,params=params,timeout=20); r2.raise_for_status()
                    d2=r2.json(); all_voices.extend(d2.get("voices",[])); page_token=d2.get("next_page_token") if d2.get("has_more") else None
        except:
            try:
                page_token=None; all_voices=[]
                for _ in range(50):
                    params={"page_size":100}
                    if page_token: params["next_page_token"]=page_token
                    r3=requests.get("https://api.elevenlabs.io/v1/voices/search",headers=headers,params=params,timeout=20); r3.raise_for_status()
                    d3=r3.json(); all_voices.extend(d3.get("voices",[])); page_token=d3.get("next_page_token") if d3.get("has_more") else None
                    if not page_token: break
            except:
                self._safe_after(0,lambda:hasattr(self, "api_status_lbl") and self.api_status_lbl.configure(text="✗ Failed",text_color=C["red"])); return
        if not all_voices:
            self._safe_after(0,lambda:hasattr(self, "api_status_lbl") and self.api_status_lbl.configure(text="✗ 0 voices",text_color=C["red"])); return
        self.voices=all_voices
        seen=set(); deduped=[]
        for v in all_voices:
            vid=v.get("voice_id",""); nm=v.get("name","?")
            # Extract gender from labels
            labels=v.get("labels",{})
            gender=labels.get("gender","") if isinstance(labels,dict) else ""
            if not gender:
                # Try to infer from name
                nl=nm.lower()
                if any(w in nl for w in ["female","girl","woman","lady","sister","mom","mother","aunt"]): gender="female"
                elif any(w in nl for w in ["male","boy","man","guy","brother","dad","father","uncle"]): gender="male"
            if vid and vid not in seen: seen.add(vid); deduped.append((nm,vid,gender))
        self.voice_list_full=deduped; count=len(deduped)
        def _upd():
            self.api_status_lbl.configure(text=f"✓ {count} voices",text_color=C["green"])
            if self.characters:
                self._auto_assign_voices()
                self._refresh_chars()
        self.after(0,_upd)

    # ── Analyze — supports both CharName: and Scene_N_: formats (Task 8) ──
    def _analyze(self):
        text=self.story_box.get("1.0","end").strip()
        if not text: messagebox.showwarning("Story","Paste story first."); return
        # First check: is this Scene_N_ format? (check BEFORE char detection)
        scene_pat=re.compile(r'^(scene[_\-\s]*\d+[_\-\s]*)\s*:\s*(.+)', re.MULTILINE | re.IGNORECASE)
        scene_matches=scene_pat.findall(text)
        # Count how many lines are Scene_N_ vs CharName format
        all_lines=[l.strip() for l in text.split("\n") if l.strip()]
        colon_lines=[l for l in all_lines if re.match(r'^.{1,50}\s*:\s*.+',l)]
        scene_line_count=len(scene_matches)
        # If majority of colon-lines are Scene_N_ format, treat as scene format
        is_scene_format = scene_line_count > 0 and (scene_line_count >= len(colon_lines) * 0.5)
        found=[]
        if is_scene_format:
            # Use scene format detection
            for name,_ in scene_matches:
                cn=name.strip()
                if cn and cn not in found: found.append(cn)
        else:
            # Use character name format — allow letters, digits, hyphens, dots, underscores, spaces, Hindi, Arabic
            char_pat=re.compile(r'^([A-Za-z0-9\u0900-\u097F\u0600-\u06FF_\-.\s]{1,50})\s*:\s*(.+)', re.MULTILINE)
            char_matches=char_pat.findall(text)
            for name,_ in char_matches:
                cn=name.strip()
                if cn and cn not in found: found.append(cn)
        # Fallback: if nothing found with strict patterns, try loose pattern
        if not found:
            loose_pat=re.compile(r'^(.+?)\s*:\s*(.+)', re.MULTILINE)
            loose_matches=loose_pat.findall(text)
            for name,_ in loose_matches:
                cn=name.strip()
                if len(cn)<=50 and cn and cn not in found: found.append(cn)
        if not found: messagebox.showwarning("Analysis","No characters or scenes found.\n\nFormat: CharName: dialogue\nOr: Scene_1_: dialogue"); return
        self.char_order=found; self.characters={}
        for i,n in enumerate(found):
            self.characters[n]={"voice_name":"","voice_id":"","color_idx":i%len(CHAR_COLORS),"is_scene":is_scene_format}
            # Task 8: Auto-assign common voice for Scene_N_ format
            if is_scene_format and self.common_voice_id.get():
                self.characters[n]["voice_name"]=self.common_voice_name.get()
                self.characters[n]["voice_id"]=self.common_voice_id.get()
        self._refresh_chars(); self._update_filter()
        # Auto-assign voices if voice list already loaded
        if self.voice_list_full:
            self._auto_assign_voices()
            self._refresh_chars()
        msg=f"Found {len(found)} characters: {', '.join(found)}"
        if is_scene_format: msg+=f" (Scene format — common voice: {self.common_voice_name.get() or 'NOT SET'})"
        self._ss(msg,C["green"])

    def _refresh_chars(self):
        for w in self.clf.winfo_children(): w.destroy()
        if not self.characters: ctk.CTkLabel(self.clf,text="No characters",text_color=C["dim"]).pack(anchor="w"); return
        for name in self.char_order:
            info=self.characters[name]; cc=CHAR_COLORS[info["color_idx"]]
            rf=ctk.CTkFrame(self.clf,fg_color=cc["bg"],border_color=cc["border"],border_width=2,corner_radius=8); rf.pack(fill="x",pady=3)
            top=ctk.CTkFrame(rf,fg_color="transparent"); top.pack(fill="x",padx=4,pady=2)
            ctk.CTkLabel(top,text=f"●  {name}",text_color=cc["accent"],font=("Segoe UI",12,"bold")).pack(side="left",padx=4,pady=4)
            vlbl=ctk.CTkLabel(top,text=info.get("voice_name") or "(no voice)",text_color=C["text"],font=("Segoe UI",10),anchor="e")
            vlbl.pack(side="right",padx=6); info["_vlbl"]=vlbl
            btnr=ctk.CTkFrame(rf,fg_color="transparent"); btnr.pack(fill="x",padx=4,pady=(0,4))
            cn=name
            ctk.CTkButton(btnr,text="🔍 Search Voice (Name/ID)",height=26,fg_color=C["btn"],text_color=C["text"],
                hover_color=cc["border"],font=("Segoe UI",10),
                command=lambda n=cn:self._open_voice_search(n)).pack(side="left",fill="x",expand=True,padx=4)

    def _open_voice_search(self,char_name):
        if not self.voice_list_full:
            messagebox.showinfo("Voices","Fetch Voices first."); return
        cv=self.characters.get(char_name,{}).get("voice_name","")
        def pick(name,vid):
            if char_name not in self.characters: return
            self.characters[char_name]["voice_name"]=name; self.characters[char_name]["voice_id"]=vid
            vlbl=self.characters[char_name].get("_vlbl")
            if vlbl:
                try: vlbl.configure(text=name)
                except: pass
            self._ss(f"Voice: {char_name} → {name}",C["green"])
        VoiceSearchWindow(self,self.voice_list_full,cv,pick,api_key=self.api_entry.get().strip())

    def _auto_assign_voices(self):
        """Auto-assign voices to characters by matching name. Runs in background."""
        if not self.voice_list_full or not self.characters: return
        threading.Thread(target=self._auto_assign_worker,daemon=True).start()

    def _auto_assign_worker(self):
        import random
        assigned=0
        vlist=list(self.voice_list_full)  # copy to avoid threading issues
        chars=dict(self.characters)
        for char_name,info in chars.items():
            if info.get("voice_id"): continue
            if info.get("is_scene"): continue
            cn=char_name.strip()
            if not cn: continue
            cn_low=cn.lower()
            cn_words=set(re.findall(r'[a-zA-Z\u0900-\u097F\u0600-\u06FF]+',cn_low))
            match=None
            # Level 1: Exact
            m=[v for v in vlist if v[0].strip().lower()==cn_low]
            if m: match=random.choice(m)
            # Level 2: Starts with
            if not match:
                m=[v for v in vlist if v[0].strip().lower().startswith(cn_low)]
                if m: match=random.choice(m)
            # Level 3: Word match
            if not match and len(cn_low)>=2:
                m=[]
                for v in vlist:
                    vw=set(re.findall(r'[a-zA-Z\u0900-\u097F\u0600-\u06FF]+',v[0].strip().lower()))
                    if cn_words & vw: m.append(v)
                if m:
                    best=[v for v in m if cn_words.issubset(set(re.findall(r'[a-zA-Z\u0900-\u097F\u0600-\u06FF]+',v[0].strip().lower())))]
                    match=random.choice(best) if best else random.choice(m)
            # Level 4: Substring
            if not match and len(cn_low)>=3:
                m=[v for v in vlist if cn_low in v[0].strip().lower() or v[0].strip().lower() in cn_low]
                if m: match=random.choice(m)
            if match:
                self.characters[char_name]["voice_name"]=match[0]
                self.characters[char_name]["voice_id"]=match[1]
                assigned+=1
    # ── Voice Studio & TTS Engine Methods ──
    def _fetch_voices_threaded(self):
        key = ""
        try:
            if hasattr(self, "api_entry") and self.api_entry.winfo_exists():
                val = self.api_entry.get().strip()
                if val and val != "sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt": key = val
        except Exception:
            pass
        if hasattr(self, "api_status"):
            try: self.api_status.configure(text="Fetching voices via AI33Pro v3...", text_color=C["accent"])
            except Exception: pass

        def worker():
            try:
                import voice_cache
                voice_cache.save_api_key(key)
                v_list = voice_cache.load_voices_cached(api_key=key, force_refresh=True)
                self.after(0, lambda: self._update_voices_ui(v_list))
            except Exception as e:
                self.after(0, lambda err=str(e): self._update_voices_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def _auto_load_voices_on_init(self):
        if getattr(self, "_voices_loaded_once", False) and getattr(self, "voices", None):
            return
        self._voices_loaded_once = True
        try:
            import voice_cache
            key = voice_cache.load_api_key()
            if hasattr(self, "api_entry") and key and key != "sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt" and self.api_entry.winfo_exists():
                try:
                    self.api_entry.delete(0, "end")
                    self.api_entry.insert(0, key)
                except Exception:
                    pass
            cached = voice_cache.load_voices_cached(force_refresh=False)
            if cached:
                self._update_voices_ui(cached)
            else:
                self._fetch_voices_threaded()
        except Exception:
            self._fetch_voices_threaded()

    def _update_voices_ui(self, voices: list):
        self.voices = voices or []
        self._filter_voices()
        if self.voices:
            first_vid = self.voices[0].get("voice_id") or "elevenlabs_hpp4J3VqNfWAUOO0d1Us"
            try:
                if hasattr(self, "voice_id") and self.voice_id.winfo_exists() and not self.voice_id.get().strip():
                    self.voice_id.insert(0, first_vid)
            except Exception:
                pass
            try:
                if hasattr(self, "common_voice_id") and not self.common_voice_id.get():
                    self.common_voice_id.set(first_vid)
            except Exception:
                pass
        if hasattr(self, "api_status"):
            try:
                self.api_status.configure(text=f"Loaded {len(self.voices)} voices from AI33Pro ✓", text_color=C["green"])
            except Exception:
                pass

    def _update_voices_error(self, err: str):
        if hasattr(self, "api_status"):
            try:
                self.api_status.configure(text=f"Voice Load Error: {err[:30]}", text_color=C["red"])
            except Exception:
                pass

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

    def _clear_voice_search(self):
        if hasattr(self, "voice_search"):
            self.voice_search.delete(0, "end")
        self._filter_voices()

    def _filter_voices(self):
        if not hasattr(self, "voice_list_scroll"): return
        try:
            if not self.voice_list_scroll.winfo_exists(): return
        except Exception:
            return

        for child in self.voice_list_scroll.winfo_children():
            try: child.destroy()
            except Exception: pass

        if not hasattr(self, "voices") or not self.voices:
            ctk.CTkLabel(self.voice_list_scroll, text="Click 'Fetch Voices' to load AI33 voice models.", font=("Segoe UI", 9), text_color=C["dim"]).pack(pady=20)
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
                if "eleven" in p_norm and "eleven" not in prov_norm: continue
                elif "minimax" in p_norm and "minimax" not in prov_norm: continue
                elif "fish" in p_norm and "fish" not in prov_norm: continue
                elif "edge" in p_norm and "edge" not in prov_norm: continue
                elif "kokoro" in p_norm and "kokoro" not in prov_norm: continue
                elif "vbee" in p_norm and "vbee" not in prov_norm: continue
                elif "clone" in p_norm and "clone" not in prov_norm: continue

            if q and q not in name.lower() and q not in vid.lower() and q not in prov.lower() and q not in cat.lower():
                continue

            matched_voices.append(v)

        if not matched_voices:
            ctk.CTkLabel(self.voice_list_scroll, text="No matching voices found.", font=("Segoe UI", 9), text_color=C["dim"]).pack(pady=20)
            return

        current_selected_vid = self.voice_id.get().strip() if hasattr(self, "voice_id") else ""

        for v in matched_voices[:30]:
            vid = v.get("voice_id") or v.get("id") or ""
            name = v.get("name", "Unnamed")
            prov = v.get("provider", "ElevenLabs")
            cat = v.get("category", "")
            lang = v.get("language", "")

            is_selected = (vid == current_selected_vid or (vid and current_selected_vid.endswith(vid)))
            row_bg = "#252B42" if is_selected else C["entry_bg"]

            row = ctk.CTkFrame(self.voice_list_scroll, fg_color=row_bg, corner_radius=4)
            row.pack(fill="x", padx=2, pady=2)

            play_btn = ctk.CTkButton(
                row, text="▶", width=28, height=22, font=("Segoe UI", 9, "bold"),
                fg_color=C["purple"], hover_color="#7C3AED",
                command=lambda voice=v: self.play_single_voice_preview(voice)
            )
            play_btn.pack(side="left", padx=4, pady=2)

            info_frame = ctk.CTkFrame(row, fg_color="transparent")
            info_frame.pack(side="left", fill="x", expand=True, padx=4)

            top_lbl = ctk.CTkLabel(info_frame, text=f"[{prov}] {name}", font=("Segoe UI", 9, "bold"), text_color=C["accent"] if is_selected else C["text"], anchor="w")
            top_lbl.pack(anchor="w")

            meta_str = " / ".join(filter(None, [cat, lang, vid]))
            sub_lbl = ctk.CTkLabel(info_frame, text=meta_str, font=("Segoe UI", 8), text_color=C["dim"], anchor="w")
            sub_lbl.pack(anchor="w")

            def _on_select(target_vid=vid, target_name=name):
                if hasattr(self, "voice_id"):
                    self.voice_id.delete(0, "end")
                    self.voice_id.insert(0, target_vid)
                if hasattr(self, "common_voice_id"):
                    self.common_voice_id.set(target_vid)
                if hasattr(self, "common_voice_name"):
                    self.common_voice_name.set(target_name)
                if hasattr(self, "api_status_lbl"):
                    self.api_status_lbl.configure(text=f"Selected: {target_name} ({target_vid}) ✓", text_color=C["green"])
                self._filter_voices()

            sel_btn = ctk.CTkButton(
                row, text="✓ In Use" if is_selected else "Use Voice", width=65, height=22, font=("Segoe UI", 9, "bold"),
                fg_color=C["green"] if is_selected else C["accent"],
                text_color="#000" if not is_selected else "#000",
                command=_on_select
            )
            sel_btn.pack(side="right", padx=4, pady=2)

    def play_single_voice_preview(self, voice_dict: dict):
        vid = voice_dict.get("voice_id") or voice_dict.get("id") or ""
        vname = voice_dict.get("name") or vid
        purl = voice_dict.get("preview_url") or ""
        key = self.api_entry.get().strip() if (hasattr(self, "api_entry") and self.api_entry.winfo_exists()) else ""
        if key == "sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt": key = ""

        if not vid:
            messagebox.showwarning("Voice Missing", "Please select a valid Voice ID.")
            return

        if hasattr(self, "api_status_lbl"):
            self.api_status_lbl.configure(text=f"Playing preview for '{vname}'...", text_color=C["accent"])

        def worker():
            try:
                clean_name = vid.replace('/', '_').replace(':', '_')
                out_p = os.path.join(TEMP_DIR, f"preview_{clean_name}.mp3")

                # 1. If audio already cached, play immediately!
                if os.path.exists(out_p) and os.path.getsize(out_p) > 500:
                    self._play_audio_file(out_p)
                    return

                # 2. Try preview_url download if valid HTTP URL
                if purl and purl.startswith("http"):
                    try:
                        import urllib.request
                        req = urllib.request.Request(purl, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req, timeout=4) as resp:
                            data = resp.read()
                            if len(data) > 500:
                                with open(out_p, "wb") as f:
                                    f.write(data)
                                self._play_audio_file(out_p)
                                return
                    except Exception:
                        pass

                # 3. Fast Zero-Failure TTS Sample Generation
                from ai33_api import ai33_tts_generate
                sample_text = f"Hello! This is a voice preview of {vname} in Stories Studio."
                if ai33_tts_generate(sample_text, vid, api_key=key, out_path=out_p):
                    if os.path.exists(out_p) and os.path.getsize(out_p) > 300:
                        self._play_audio_file(out_p)
                        return

                self.after(0, lambda: messagebox.showerror("Preview Failed", f"Unable to generate preview audio for {vid}."))
            except Exception as e:
                self.after(0, lambda err=str(e): messagebox.showerror("Preview Error", f"Voice preview error:\n{err}"))

        threading.Thread(target=worker, daemon=True).start()

    def play_voice_preview(self):
        vid = self.voice_id.get().strip() if hasattr(self, "voice_id") else ""
        if vid:
            self.play_single_voice_preview({"voice_id": vid, "name": vid})

    def _play_audio_file(self, audio_path: str):
        if not audio_path or not os.path.exists(audio_path):
            return
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
            pygame.mixer.music.load(audio_path)
            pygame.mixer.music.play()
            if hasattr(self, "api_status_lbl"):
                self.api_status_lbl.configure(text="Playing voice preview audio... ▶", text_color=C["green"])
        except Exception:
            try:
                subprocess.Popen(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", audio_path])
            except Exception:
                if hasattr(os, "startfile"):
                    os.startfile(audio_path)

    def _update_filter(self):
        self.filter_menu.configure(values=["All"]+list(self.char_order)); self.filter_var.set("All"); self.active_filter="All"

    def _on_filter(self,choice=None):
        self.active_filter=choice if choice else self.filter_var.get()
        for b in self.blocks:
            fr=b.get("frame")
            if fr:
                try: fr.pack_forget()
                except: pass
        shown=0
        for b in self.blocks:
            fr=b.get("frame")
            if not fr: continue
            if self.active_filter=="All" or b.get("character","")==self.active_filter:
                try: fr.pack(fill="x",padx=5,pady=3); shown+=1
                except: pass
        total=len(self.blocks)
        if self.active_filter=="All": self._ss(f"All scenes ({total})",C["accent"])
        else: self._ss(f"Filter: {self.active_filter} ({shown}/{total})",C["accent"])

    def _create_blocks(self):
        """Create blocks from story text with UI hang prevention."""
        text=self.story_box.get("1.0","end").strip()
        if not text: messagebox.showwarning("Story","Paste story."); return
        if not self.characters: messagebox.showwarning("Characters","Analyze first."); return
        for b in self.blocks:
            try: b["frame"].destroy()
            except: pass
        self.blocks.clear()
        pat=re.compile(r'^([A-Za-z0-9\u0900-\u097F\u0600-\u06FF_\-.\s]{1,50})\s*:\s*(.+)',re.MULTILINE)
        lines=[line.strip() for line in text.split("\n") if line.strip()]
        
        # Build block queue
        self._block_queue = []
        for line in lines:
            m=pat.match(line)
            if m:
                cn,dl=m.group(1).strip(),m.group(2).strip()
                if cn in self.characters and dl:
                    self._block_queue.append((cn,dl))
        
        # No block limit — Jesus tab handles unlimited blocks smoothly
        
        self._ss(f"Creating {len(self._block_queue)} blocks · loading smoothly…",C["orange"])
        self._block_creation_idx=0
        self._total_blocks_to_create=len(self._block_queue)
        threading.Thread(target=self._create_blocks_worker,daemon=True).start()

    def _create_blocks_worker(self):
        """Background worker: create blocks in small batches for responsive UI."""
        pat=re.compile(r'^scene[_\-\s]*(\d+)', re.IGNORECASE)
        batch=[]
        batch_size=15  # Smaller batches (was 100) — more responsive
        
        for cn,dl in self._block_queue:
            try:
                num=len(self.blocks)+len(batch)+1
                match=pat.search(dl)
                if match:
                    try: sn=int(match.group(1))
                    except: sn=num
                    num=sn
                batch.append((cn, dl, num))
                self._block_creation_idx+=1
                
                # Flush batch when full or at end
                if len(batch)>=batch_size or self._block_creation_idx>=self._total_blocks_to_create:
                    self._flush_blocks_batch(batch)
                    batch=[]
                    # Update status WITHOUT sleep — let OS handle scheduling
                    self.after(0, lambda: self._ss(
                        f"Creating blocks {self._block_creation_idx}/{self._total_blocks_to_create}…",
                        C["orange"]))
            except: pass
        
        # Final flush
        if batch:
            self._flush_blocks_batch(batch)
        
        # Done
        self.after(0, lambda: self._update_filter())
        self.after(0, lambda: self._on_filter("All"))
        self.after(0, lambda: self._ss(f"✓ Created {self._total_blocks_to_create} blocks", C["green"]))

    def _flush_blocks_batch(self, batch):
        """Create blocks with OPTIMIZED throttling: 50 blocks at a time, 10ms delay."""
        def _create_chunk(start_idx):
            end_idx = min(start_idx + 50, len(batch))
            for i in range(start_idx, end_idx):
                try:
                    cn, dl, num = batch[i]
                    self._make_block(num, cn, dl)
                except:
                    pass
            if end_idx < len(batch):
                self.after(10, lambda: _create_chunk(end_idx))
        
        self.after(0, lambda: _create_chunk(0))

    def _make_block(self,num,char,text,video_only=False):
        ci=self.characters.get(char,{}); cc=CHAR_COLORS[ci.get("color_idx",0)%len(CHAR_COLORS)]
        if video_only: cc={"bg":"#1a1a2e","border":C["dim"],"accent":C["dim"]}
        frame=ctk.CTkFrame(self.bkf,fg_color=cc["bg"],border_color=cc["border"],border_width=2,corner_radius=10,height=130)
        frame.pack(fill="x",padx=5,pady=3); frame.pack_propagate(False)
        block={"num":num,"text":text,"character":char,"color_idx":ci.get("color_idx",0),
            "source_media":"","media_type":"","video":"","output":"","tts_audio":"","frame":frame,
            "trim_start":None,"trim_end":None,"trimmed_loop_path":None,"loop_mode":"pingpong",
            "video_only":video_only,"clip_volume":0}  # Task 9: default mute

        top=ctk.CTkFrame(frame,fg_color="transparent"); top.pack(fill="x",padx=8,pady=(4,2))
        ctk.CTkLabel(top,text=f"#{num}",text_color=C["text"],font=("Segoe UI",13,"bold"),width=35).pack(side="left")
        badge_text=f" {char} " if not video_only else " VIDEO ONLY "
        badge=ctk.CTkFrame(top,fg_color=cc["border"],corner_radius=12,height=24); badge.pack(side="left",padx=5)
        ctk.CTkLabel(badge,text=badge_text,text_color="#000",font=("Segoe UI",10,"bold")).pack(padx=6,pady=2)
        tl=ctk.CTkLabel(top,text="[no vid]",text_color=C["dim"],width=72,height=38); tl.pack(side="left",padx=5); block["thumb_label"]=tl
        # ✕ Delete this block
        ctk.CTkButton(top,text="✕",width=24,height=24,fg_color=C["btn"],hover_color=C["red"],text_color=C["red"],
            font=("Segoe UI",12,"bold"),command=lambda n=num:self._delete_block(n)).pack(side="right",padx=4)
        d=text[:50]+"..." if len(text)>50 else text
        if not video_only:
            ctk.CTkLabel(top,text=d,text_color=C["text"],font=("Segoe UI",10),wraplength=250,anchor="w",justify="left").pack(side="left",fill="x",expand=True,padx=5)

        mid=ctk.CTkFrame(frame,fg_color="transparent"); mid.pack(fill="x",padx=8,pady=(0,2))
        fl=ctk.CTkLabel(mid,text="[no media]",text_color=C["dim"],font=("Consolas",9)); fl.pack(side="left",padx=5); block["file_label"]=fl
        trl=ctk.CTkLabel(mid,text="",text_color=C["orange"],font=("Consolas",8)); trl.pack(side="left",padx=8); block["trim_label"]=trl
        # Task 9: Per-clip volume slider
        ctk.CTkLabel(mid,text="Vol:",text_color=C["dim"],font=("Segoe UI",8)).pack(side="left",padx=(10,2))
        vol_var=ctk.IntVar(value=0)
        vol_slider=ctk.CTkSlider(mid,from_=0,to=100,variable=vol_var,width=50,height=14)
        vol_slider.pack(side="left",padx=2)
        vol_lbl=ctk.CTkLabel(mid,text="0%",text_color=C["dim"],font=("Consolas",7),width=25)
        vol_lbl.pack(side="left")
        vol_var.trace_add("write",lambda*a,v=vol_var,l=vol_lbl,bl=block:(l.configure(text=f"{v.get()}%"),bl.__setitem__("clip_volume",v.get())))
        block["vol_var"]=vol_var; block["vol_label"]=vol_lbl
        # Per-block TTS volume
        ctk.CTkLabel(mid,text="TTS:",text_color=C["dim"],font=("Segoe UI",8)).pack(side="left",padx=(6,2))
        tts_var=ctk.IntVar(value=100)
        ctk.CTkSlider(mid,from_=0,to=100,variable=tts_var,width=50,height=14).pack(side="left",padx=2)
        tts_lbl=ctk.CTkLabel(mid,text="100%",text_color=C["dim"],font=("Consolas",7),width=28)
        tts_lbl.pack(side="left")
        tts_var.trace_add("write",lambda*a,v=tts_var,l=tts_lbl,bl=block:(l.configure(text=f"{v.get()}%"),bl.__setitem__("tts_volume",v.get())))
        block["tts_var"]=tts_var; block["tts_volume"]=100
        st=ctk.CTkLabel(mid,text="Pending",text_color=C["orange"],font=("Segoe UI",9)); st.pack(side="right",padx=5); block["status_label"]=st

        bot=ctk.CTkFrame(frame,fg_color="transparent"); bot.pack(fill="x",padx=8,pady=(0,4))
        idx=len(self.blocks)
        ctk.CTkButton(bot,text="Upload Video",width=90,height=24,fg_color=C["accent"],text_color="#000",font=("Segoe UI",9),command=lambda i=idx:self._uvb(i)).pack(side="left",padx=2)
        ctk.CTkButton(bot,text="Trim & Loop",width=85,height=24,fg_color=C["orange"],text_color="#000",font=("Segoe UI",9),command=lambda i=idx:self._otl(i)).pack(side="left",padx=2)
        ctk.CTkButton(bot,text="Clear Trim",width=70,height=24,fg_color=C["btn"],text_color=C["dim"],font=("Segoe UI",9),command=lambda i=idx:self._ct(i)).pack(side="left",padx=2)
        ctk.CTkButton(bot,text="▶ Preview",width=70,height=24,fg_color=C["purple"],text_color="#fff",font=("Segoe UI",9),command=lambda i=idx:self._preview_block(i)).pack(side="right",padx=2)
        if not video_only:
            # Task 4: individual audio gen button
            ctk.CTkButton(bot,text="🔊 Audio",width=60,height=24,fg_color=C["orange"],text_color="#000",font=("Segoe UI",9),command=lambda i=idx:self._gen_audio_single(i)).pack(side="right",padx=2)
        ctk.CTkButton(bot,text="Gen",width=45,height=24,fg_color=C["green"],text_color="#000",font=("Segoe UI",9),command=lambda i=idx:self._gs(i)).pack(side="right",padx=2)
        self.blocks.append(block)

    # Task 7: Add video-only block (no script/audio needed)
    def _add_video_block(self):
        p=filedialog.askopenfilename(filetypes=[("Video","*.mp4 *.mov *.avi *.mkv *.webm *.flv")])
        if not p: return
        num=len(self.blocks)+1
        # Create a pseudo-character for filtering
        vchar=f"_VideoOnly_{num}"
        self.characters[vchar]={"voice_name":"","voice_id":"","color_idx":num%len(CHAR_COLORS),"is_scene":False}
        self._make_block(num,vchar,"",video_only=True)
        b=self.blocks[-1]; b["source_media"]=p; b["media_type"]="video"; b["video"]=p
        self._queue_media_load(b, p, status_prefix="Video only")
    # ── Block helpers ──

    def _queue_media_load(self, block, path, status_prefix="Video"):
        """Queue a video for background thumbnail+duration extraction.

        UI updates happen immediately with placeholder text ("loading…");
        the actual ffmpeg/ffprobe work runs on a single background thread
        sequentially so the app doesn't hang when many videos are uploaded.
        """
        # Immediate UI feedback so the user can see the block was registered.
        try:
            block["file_label"].configure(text=f"⏳ {os.path.basename(path)}")
            block["status_label"].configure(text=f"{status_prefix}: loading…", text_color=C["dim"])
        except: pass
        with self._media_lock:
            self._media_q_total += 1
        self._media_q.put((block, path, status_prefix))
        self._ensure_media_worker()
        # Top-level progress hint
        self._update_media_progress()

    def _ensure_media_worker(self):
        """Start the single background loader thread if it's not running."""
        if self._media_thread is None or not self._media_thread.is_alive():
            self._media_thread = threading.Thread(
                target=self._media_loader_worker, daemon=True)
            self._media_thread.start()

    def _media_loader_worker(self):
        """Drains the media queue one item at a time — simple, no complex futures."""
        while True:
            try:
                item = self._media_q.get(timeout=2.0)
            except:
                break
            if item is None:
                break
            
            block, path, status_prefix = item
            try:
                # Heavy work: thumbnail + duration
                tk, dur = self._extract_media_info(path)
                
                # Post UI update on main thread
                def _apply(_b=block, _tk=tk, _dur=dur, _path=path, _sp=status_prefix):
                    if _b not in self.blocks:
                        return
                    try:
                        if _tk is not None:
                            _b["_ttk"] = _tk
                            _b["thumb_label"].configure(image=_tk, text="")
                    except:
                        pass
                    try:
                        _b["file_label"].configure(text=os.path.basename(_path))
                    except:
                        pass
                    try:
                        dur_txt = format_duration(_dur) if _dur > 0 else "?"
                        _b["status_label"].configure(
                            text=f"{_sp} ({dur_txt})", text_color=C["green"])
                    except:
                        pass
                
                self.after(0, _apply)
            except Exception:
                pass
            finally:
                with self._media_lock:
                    self._media_q_done += 1
                self.after(0, self._update_media_progress)

    def _extract_media_info(self, path):
        """Extract thumbnail and duration (parallel-safe). Returns (PIL_image, duration)."""
        tk = None
        dur = 0.0
        try:
            tk = smart_thumb(path)
        except:
            tk = None
        try:
            dur = get_duration(path)
        except:
            dur = 0.0
        return (tk, dur)

    def _update_media_progress(self):
        """Update the top-level status bar with current loader progress."""
        try:
            with self._media_lock:
                total = self._media_q_total
                done = self._media_q_done
            if total <= 0: return
            if done >= total:
                # Reset counters once everything is done
                with self._media_lock:
                    self._media_q_total = 0
                    self._media_q_done = 0
                self._ss(f"✓ All {total} videos loaded", C["green"])
            else:
                self._ss(f"Loading videos {done}/{total} (queued)…", C["orange"])
        except: pass

    def _uvb(self,idx):
        if idx<0 or idx>=len(self.blocks): return
        p=filedialog.askopenfilename(filetypes=[("Video","*.mp4 *.mov *.avi *.mkv *.webm *.flv")])
        if not p: return
        b=self.blocks[idx]; b["source_media"]=p; b["media_type"]="video"; b["video"]=p
        b["trim_start"]=b["trim_end"]=None; b["trimmed_loop_path"]=None
        b["trim_label"].configure(text="No trim")
        # Queue heavy work (thumbnail+duration) on background thread → keeps UI snappy
        self._queue_media_load(b, p, status_prefix="Video")

    def _otl(self,idx):
        if idx<0 or idx>=len(self.blocks): return
        b=self.blocks[idx]; vp=b.get("source_media","")
        if not vp or not os.path.exists(vp): messagebox.showwarning("Trim","Upload video first."); return
        td=estimate_tts_duration_from_text(b["text"])+max(0,float(self.silence_var.get()))
        if b.get("tts_audio") and os.path.exists(b["tts_audio"]): td=get_duration(b["tts_audio"])
        if b.get("video_only"): td=get_duration(vp)  # For video-only, use video duration
        captured_idx=idx
        def on_trim(s,e,do_auto,loop_mode):
            b["trim_start"]=s; b["trim_end"]=e; b["loop_mode"]=loop_mode
            seg=e-s; loops=math.ceil(td/max(0.1,seg))
            mode_txt="Fwd" if loop_mode=="forward" else "Fwd+Rev"
            b["trim_label"].configure(text=f"Trim:{format_duration(s)}-{format_duration(e)} {mode_txt} {loops}x")
            b["status_label"].configure(text="Trim set",text_color=C["orange"])
            if do_auto:
                threading.Thread(target=self._auto_process_trim,args=(captured_idx,td),daemon=True).start()
        TrimLoopWindow(self,vp,td,on_trim)

    def _auto_process_trim(self,idx,target_dur):
        if idx<0 or idx>=len(self.blocks): return
        b=self.blocks[idx]; num=b["num"]
        if b.get("trim_start") is None or b.get("trim_end") is None: return
        mp=b.get("source_media","")
        if not mp or not os.path.exists(mp): return
        loop_mode=b.get("loop_mode","pingpong")
        self._block_status(b,"⚡ Pre-trimming...",C["accent"])
        self._sss(f"[#{num}] auto-trim ({loop_mode})...")
        out=os.path.join(TEMP_DIR,f"adv_tl_pre_{num}.mp4")
        try:
            if loop_mode=="pingpong":
                seg=os.path.join(TEMP_DIR,f"adv_tl_seg_{num}.mp4")
                cmd=["ffmpeg","-y","-ss",str(b["trim_start"]),"-i",mp,"-t",str(b["trim_end"]-b["trim_start"])]
                cmd+=GPU.enc_args("fast"); cmd+=["-an",seg]
                _run_ff(cmd,timeout=300)
                if os.path.exists(seg) and get_duration(seg)>0.05:
                    res=build_pingpong_video(seg,target_dur,out)
                else: res=None
            else:
                res=build_trim_loop_video(mp,b["trim_start"],b["trim_end"],target_dur,out)
            if res and os.path.exists(res) and get_duration(res)>0.1:
                b["trimmed_loop_path"]=res
                self._block_status(b,f"✓ Pre-trim ({format_duration(get_duration(res))})",C["green"])
            else:
                self._block_status(b,"Pre-trim fail → retry later",C["red"])
        except:
            self._block_status(b,"Pre-trim err → retry later",C["red"])

    def _ct(self,idx):
        if idx<0 or idx>=len(self.blocks): return
        b=self.blocks[idx]
        b["trim_start"]=b["trim_end"]=None; b["trimmed_loop_path"]=None; b["loop_mode"]="pingpong"
        b["trim_label"].configure(text="No trim")
        b["status_label"].configure(text="Trim cleared",text_color=C["dim"])

    def _preview_block(self,idx):
        """Preview a scene with proper audio mixing.

        Decision tree:
          1. If b['output'] already exists (Gen done) → play it directly (has final audio).
          2. Else if block is video-only (no script) → play raw video.
          3. Else if block has script:
               • If TTS audio is ready → build proxy preview WITH all overlays + TTS + clip + SFX mixed.
               • If TTS audio is missing → warn user; offer to generate now or preview without voice.
        """
        if idx<0 or idx>=len(self.blocks): return
        b=self.blocks[idx]; num=b["num"]

        # Case 1: Final output already rendered → just play it
        final_out=b.get("output","")
        if final_out and os.path.exists(final_out) and get_duration(final_out)>0.1:
            # Final output has full mixed audio — auto-open external player for guaranteed sound.
            MiniPlayerWindow(self,final_out,title_text=f"Scene #{num} (final)",
                auto_open_external=True)
            return

        target=b.get("source_media","")
        if not target or not os.path.exists(target):
            messagebox.showwarning("Preview","Nothing to preview — upload a video or image first."); return

        # If the source is an image, open it externally (image preview doesn't need audio mixing)
        if not is_video_file(target):
            try:
                if hasattr(os,"startfile"): os.startfile(target)
                elif sys.platform=="darwin": subprocess.Popen(["open",target])
                else: subprocess.Popen(["xdg-open",target])
            except: pass
            return

        # Case 2: Video-only block → play raw, no warning
        if b.get("video_only"):
            self._ss(f"Building preview #{num}...",C["orange"])
            threading.Thread(target=self._preview_proxy_worker,args=(b,target,num),daemon=True).start()
            return

        # Case 3: Block has script — TTS audio expected
        text=b.get("text","").strip()
        ap=b.get("tts_audio","")
        has_tts_ready=bool(ap) and os.path.exists(ap) and get_duration(ap)>0.1

        if text and not has_tts_ready:
            # WARNING: voice missing
            char=b.get("character","")
            ci=self.characters.get(char,{}); vid_id=ci.get("voice_id","") or self.common_voice_id.get()
            ak=self.api_entry.get().strip()
            can_gen=bool(ak) and bool(vid_id)
            if can_gen:
                msg=(f"Scene #{num} has script but TTS voice is not generated yet.\n\n"
                     f"Generate voice now using 'Gen' button on this block first,\n"
                     f"then click Preview again.\n\n"
                     f"Generate voice now?")
                ans=messagebox.askyesnocancel("Generate voice first?",msg)
                if ans is None: return  # cancel
                if ans:
                    # Generate TTS first, then auto-relaunch preview
                    self._ss(f"Generating voice for #{num}...",C["orange"])
                    def _gen_then_preview():
                        try: self._gen_audio_worker(idx)
                        except Exception as e:
                            self.after(0,lambda:messagebox.showerror("TTS error",str(e)[:200]))
                            return
                        # Re-check & launch preview
                        b2=self.blocks[idx] if idx<len(self.blocks) else None
                        if not b2: return
                        ap2=b2.get("tts_audio","")
                        if ap2 and os.path.exists(ap2):
                            self._ss(f"Building preview #{num}...",C["orange"])
                            self._preview_proxy_worker(b2,target,num)
                        else:
                            self.after(0,lambda:messagebox.showwarning(
                                "Preview","Voice generation failed. Check API key / voice setup."))
                    threading.Thread(target=_gen_then_preview,daemon=True).start()
                    return
                # User said No → preview without voice
            else:
                # Cannot generate (no API key or no voice configured)
                missing=[]
                if not ak: missing.append("ElevenLabs API key")
                if not vid_id: missing.append(f"voice for character '{char}'")
                detail=" and ".join(missing) if missing else "voice setup"
                ans=messagebox.askyesno(
                    "Voice not ready",
                    f"Scene #{num} has script but voice is missing.\n\n"
                    f"Missing: {detail}.\n\n"
                    f"Set it up, then click 'Gen' to generate audio.\n\n"
                    f"Preview without voice anyway?")
                if not ans: return

        # Build proxy preview with everything mixed in (TTS, clip audio, SFX, blend video, captions, blend text)
        self._ss(f"Building preview #{num}...",C["orange"])
        threading.Thread(target=self._preview_proxy_worker,args=(b,target,num),daemon=True).start()

    def _preview_proxy_worker(self,b,target,num):
        """Quick preview at lower resolution including captions, blend text,
        blend video lower-third, SFX, and proper clip+TTS volume mixing —
        so what the user hears here is what the final output will produce."""
        vw,vh=get_resolution(target)
        pw=min(vw,854); ph=int(pw*vh/max(1,vw)); ph=ph if ph%2==0 else ph+1
        # Effective volumes (same formula as final render)
        clip_vol=b.get("clip_volume",0); master_clip=self.master_vol_var.get()
        tts_vol=b.get("tts_volume",100); master_tts=self.master_tts_vol_var.get()
        eff_clip=(clip_vol/100.0)*(master_clip/100.0)
        eff_tts=(tts_vol/100.0)*(master_tts/100.0)
        ap=b.get("tts_audio","")
        has_tts=bool(ap) and os.path.exists(ap) and eff_tts>0.001
        has_clip_audio=has_audio_stream(target) and eff_clip>0.001
        # SFX for this scene (already-generated, lower-third sound)
        sfx_path=self._blend_sfx.get(num) if hasattr(self,"_blend_sfx") else None
        if sfx_path and not os.path.exists(sfx_path): sfx_path=None
        try: sfx_vol=max(0.0,min(2.0,float(self.blend_sfx_volume_var.get())))
        except: sfx_vol=1.0
        has_sfx=bool(sfx_path)
        # Blend video for this scene
        blend_video_path=self._blend_videos.get(num) if hasattr(self,"_blend_videos") else None
        if blend_video_path and not os.path.exists(blend_video_path): blend_video_path=None

        # Build video filter graph piece-by-piece for proxy resolution
        vf_parts=[f"scale={pw}:{ph}:flags=fast_bilinear"]
        # Add captions
        if self.captions_enabled_var.get() and num in self._caption_groups:
            cf=build_caption_drawtext_filter(
                self._caption_groups[num],pw,ph,
                font_path=self.caption_font_path_var.get(),
                font_size=max(16,int(self.caption_font_size_var.get()*pw/max(1,vw))),
                font_color=self.caption_font_color_var.get().strip().lstrip("#"),
                bg_color=self.caption_bg_color_var.get().strip().lstrip("#"),
                bg_opacity=self.caption_bg_opacity_var.get(),
                position=self.caption_position_var.get(),
                margin_bottom=max(10,int(self.caption_margin_var.get()*ph/max(1,vh))),
                animation=self.caption_animation_var.get())
            if cf: vf_parts.append(cf)
        # Add blend text
        if self.blend_text_enabled_var.get() and num in self._blend_texts:
            bt_dur=get_duration(target)
            bt_groups=[{"text":self._blend_texts[num],"start":0.0,"end":bt_dur}]
            bt_cf=build_caption_drawtext_filter(
                bt_groups,pw,ph,
                font_path=self.blend_text_font_path_var.get(),
                font_size=max(16,int(self.blend_text_font_size_var.get()*pw/max(1,vw))),
                font_color=self.blend_text_font_color_var.get().strip().lstrip("#"),
                bg_color=self.blend_text_bg_color_var.get().strip().lstrip("#"),
                bg_opacity=self.blend_text_bg_opacity_var.get(),
                position=self.blend_text_position_var.get(),
                margin_bottom=max(10,int(self.blend_text_margin_var.get()*ph/max(1,vh))),
                animation=self.blend_text_animation_var.get(),
                border_w=self.blend_text_border_w_var.get(),
                border_color=self.blend_text_border_color_var.get().strip().lstrip("#"),
                shadow=self.blend_text_shadow_var.get(),
                align=self.blend_text_align_var.get())
            if bt_cf: vf_parts.append(bt_cf)
        prev_out=os.path.join(TEMP_DIR,f"_proxy_preview_{num}.mp4")
        # Duration: cover the full TTS length (if present), capped at 30 sec for preview speed.
        # If source video is shorter than TTS, loop it so audio doesn't get cut off.
        target_dur=get_duration(target)
        tts_dur=get_duration(ap) if has_tts else 0.0
        sfx_dur=get_duration(sfx_path) if has_sfx else 0.0
        wanted=max(target_dur, tts_dur, sfx_dur)
        dur=min(30.0, wanted if wanted>0.1 else target_dur)

        # If the source video is shorter than the audio, loop it so the preview keeps playing
        # while TTS / SFX is still speaking.
        original_target=target  # keep ref so we can still pull clip audio from original
        need_loop = has_tts and target_dur>0.1 and tts_dur>target_dur+0.2
        looped_target=None
        if need_loop:
            looped_target=os.path.join(TEMP_DIR,f"_proxy_loop_{num}.mp4")
            n_loops=int(math.ceil(dur/max(0.5,target_dur)))+1
            try:
                cmd_loop=["ffmpeg","-y","-stream_loop",str(n_loops),"-i",target,
                          "-t",f"{dur:.3f}","-c","copy","-an",looped_target]
                _run_ff(cmd_loop,timeout=120)
                if not (os.path.exists(looped_target) and get_duration(looped_target)>0.1):
                    # Fallback: re-encode loop
                    cmd_loop2=["ffmpeg","-y","-stream_loop",str(n_loops),"-i",target,
                               "-t",f"{dur:.3f}"]+GPU.enc_args("ultrafast")+["-an",looped_target]
                    _run_ff(cmd_loop2,timeout=180)
                if os.path.exists(looped_target) and get_duration(looped_target)>0.1:
                    target=looped_target
            except: pass

        # Build inputs list: target = 0, [blend_video], [tts], [sfx], [orig_audio]
        # When we looped the video, its audio is gone (-an). Re-add the original file as
        # an audio-only input so the clip-audio mix still works.
        inputs=["-i",target]
        idx_map={"main":0}
        next_idx=1
        if blend_video_path:
            inputs+=["-i",blend_video_path]; idx_map["blend"]=next_idx; next_idx+=1
        if has_tts:
            inputs+=["-i",ap]; idx_map["tts"]=next_idx; next_idx+=1
        if has_sfx:
            inputs+=["-i",sfx_path]; idx_map["sfx"]=next_idx; next_idx+=1
        # Clip audio source: from looped video's original file if we looped, else from main
        clip_audio_idx=idx_map["main"]
        if looped_target and has_clip_audio:
            inputs+=["-i",original_target]; idx_map["clipaud"]=next_idx; clip_audio_idx=next_idx; next_idx+=1

        # BGM in the scene preview (looped to cover the clip) so the preview matches
        # what the final render will sound like.
        bgm_path_pv=self.bgm_var.get()
        bgm_on_pv=self.bgm_enabled_var.get() and bool(bgm_path_pv) and os.path.exists(bgm_path_pv)
        bgm_vol_pv=0.15
        if bgm_on_pv:
            if getattr(self,"bgm_loop_var",None) and self.bgm_loop_var.get():
                inputs+=["-stream_loop","-1","-i",bgm_path_pv]
            else:
                inputs+=["-i",bgm_path_pv]
            idx_map["bgm"]=next_idx; next_idx+=1
            bgm_vol_pv=self._bgm_vol_val()

        # Video filter: main vf, then overlay blend video (chroma-keyed) if present
        vf_str=",".join(vf_parts)
        filter_complex_parts=[]
        if blend_video_path:
            try:
                key_color=self.blend_video_key_color_var.get().strip().lstrip("#") or "00FF00"
            except: key_color="00FF00"
            try: key_sim=float(self.blend_video_similarity_var.get())
            except: key_sim=0.30
            try: key_blend=float(self.blend_video_blend_var.get())
            except: key_blend=0.10
            bv_h=max(1,ph//3)
            filter_complex_parts.append(f"[{idx_map['main']}:v]{vf_str}[base]")
            filter_complex_parts.append(
                f"[{idx_map['blend']}:v]scale={pw}:{bv_h}:force_original_aspect_ratio=decrease,"
                f"colorkey=0x{key_color}:{key_sim:.2f}:{key_blend:.2f},format=yuva420p[bv]")
            filter_complex_parts.append(f"[base][bv]overlay=(W-w)/2:H-h-10:shortest=0[vout]")
            v_map=["-map","[vout]"]
        else:
            v_map=["-map","0:v"]

        # Audio mixing: clip (from main/original input audio) + TTS + SFX
        a_inputs=[]
        if has_clip_audio: a_inputs.append((clip_audio_idx, eff_clip, "ca"))
        if has_tts:        a_inputs.append((idx_map["tts"],  eff_tts,  "ta"))
        if has_sfx:        a_inputs.append((idx_map["sfx"],  sfx_vol,  "sa"))
        if bgm_on_pv:      a_inputs.append((idx_map["bgm"],  bgm_vol_pv, "ba"))

        a_map=[]
        if len(a_inputs)>=2:
            parts=[]; labels=[]
            for src_idx,v,lbl in a_inputs:
                parts.append(f"[{src_idx}:a]volume={v:.3f},aresample=48000:async=1:first_pts=0[{lbl}]")
                labels.append(f"[{lbl}]")
            filter_complex_parts.append(
                ";".join(parts)+";"+"".join(labels)+f"amix=inputs={len(a_inputs)}:duration=longest:normalize=0[aout]")
            a_map=["-map","[aout]"]
        elif len(a_inputs)==1:
            src_idx,v,lbl=a_inputs[0]
            filter_complex_parts.append(f"[{src_idx}:a]volume={v:.3f}[aout]")
            a_map=["-map","[aout]"]
        # else: no audio at all — leave it silent
        cmd=["ffmpeg","-y"]+inputs
        if filter_complex_parts:
            cmd+=["-filter_complex",";".join(filter_complex_parts)]
        else:
            # No filter graph needed — fall back to simple -vf for non-blend-video case with no audio inputs
            cmd+=["-vf",vf_str]
        cmd+=v_map
        if a_map:
            cmd+=a_map+["-c:a","aac","-b:a","128k"]
        else:
            cmd+=["-an"]
        cmd+=["-t",str(dur),"-c:v","libx264","-preset","ultrafast","-crf","28","-pix_fmt","yuv420p",prev_out]
        result=_run_ff(cmd,timeout=180)
        if os.path.exists(prev_out) and get_duration(prev_out)>0.1:
            self._ss(f"Preview ready #{num}",C["green"])
            # Hook: subclasses (Story Video) can add FX/captions to the preview so it
            # matches the final output. Default returns the proxy unchanged.
            try:
                prev_out = self._preview_post_hook(prev_out, b, num, dur)
            except Exception as _e:
                pass
            # Auto-open external player when we mixed audio — guarantees the user actually hears
            # the TTS/clip/SFX even if pygame.mixer is flaky on their system.
            auto_ext = (has_tts or has_clip_audio or has_sfx or bgm_on_pv)
            self.after(0,lambda ae=auto_ext, po=prev_out: MiniPlayerWindow(
                self,po,title_text=f"Preview #{num}",auto_open_external=ae))
        else:
            # Log error and try without overlays/mix
            err=""
            if result and hasattr(result,'stderr') and result.stderr: err=str(result.stderr)[:200]
            self._ss(f"Preview failed: {err[:50]}",C["orange"])
            cmd2=["ffmpeg","-y","-i",target,"-vf",f"scale={pw}:{ph}:flags=fast_bilinear",
                "-t",str(dur),"-c:v","libx264","-preset","ultrafast","-crf","28","-pix_fmt","yuv420p"]
            if has_audio_stream(target): cmd2+=["-c:a","aac","-b:a","128k"]
            else: cmd2+=["-an"]
            cmd2+=[prev_out]
            _run_ff(cmd2,timeout=120)
            if os.path.exists(prev_out) and get_duration(prev_out)>0.1:
                self.after(0,lambda:MiniPlayerWindow(self,prev_out,
                    title_text=f"Preview #{num} (fallback)",auto_open_external=False))
            else:
                self.after(0,lambda:MiniPlayerWindow(self,target,
                    title_text=f"Scene #{num} (raw)",auto_open_external=False))

    # ── Professional Unified Upload (Videos + Images) ──

    def _adv_bulk_upload_smart(self):
        """Professional-grade upload: accepts videos/images, auto-maps Scene_1_ etc,
        queues loading in background for smooth 1000+ block support."""
        ps = filedialog.askopenfilenames(filetypes=[
            ("All Media", "*.mp4 *.mov *.avi *.mkv *.webm *.flv *.jpg *.jpeg *.png *.webp *.bmp *.gif"),
            ("Videos", "*.mp4 *.mov *.avi *.mkv *.webm *.flv"),
            ("Images", "*.jpg *.jpeg *.png *.webp *.bmp *.gif")])
        if not ps:
            return
        if not self.blocks:
            messagebox.showwarning("Blocks", "Create blocks first using 'Analyze' + 'Create Blocks'.")
            return
        ps = sort_files(list(ps))
        self._ss(f"Uploading {len(ps)} files… mapping & loading", C["orange"])
        # Process on background thread so UI stays responsive
        threading.Thread(target=self._smart_upload_worker, args=(ps,), daemon=True).start()

    def _smart_upload_worker(self, paths):
        """Background worker: map files to blocks by Scene_N_ and queue thumbnails with throttling."""
        mapped = 0
        assigned_blocks = set()
        queue_batch = []
        queue_delay = 10  # 10ms between batches (was 50ms)
        
        def _queue_batch_throttled(batch, start_idx):
            """Queue a batch of files, then schedule next batch."""
            for b, p, prefix in batch:
                try:
                    self._queue_media_load(b, p, status_prefix=prefix)
                except:
                    pass
            
            # Schedule next batch if files remain
            if start_idx + 20 < len(paths):  # 20 files per batch (was 5)
                self.after(queue_delay, lambda: _queue_next_batch(start_idx + 20))
        
        def _queue_next_batch(start_idx):
            """Build and queue the next batch."""
            end_idx = min(start_idx + 20, len(paths))  # 20 files (was 5)
            next_batch = []
            for i in range(start_idx, end_idx):
                if i < len(queue_batch) and queue_batch[i] is not None:
                    next_batch.append(queue_batch[i])
            if next_batch:
                _queue_batch_throttled(next_batch, start_idx)
        
        # Pass 1: Explicit Scene_1_, Scene_2_, etc. matches
        for p in paths:
            if not os.path.exists(p):
                continue
            scene_num = extract_scene_number(p)
            if scene_num and 1 <= scene_num <= len(self.blocks):
                b = self.blocks[scene_num - 1]
                is_vid = is_video_file(p)
                b["source_media"] = p
                b["media_type"] = "video" if is_vid else "image"
                b["video"] = p if is_vid else ""
                b["trim_start"] = b["trim_end"] = None
                b["trimmed_loop_path"] = None
                try:
                    b["trim_label"].configure(text="No trim")
                except:
                    pass
                queue_batch.append((b, p, "Scene " + str(scene_num)))
                assigned_blocks.add(scene_num)
                mapped += 1
        
        # Pass 2: Remaining files → fill empty blocks sequentially
        for p in paths:
            if not os.path.exists(p):
                continue
            scene_num = extract_scene_number(p)
            if scene_num and scene_num in assigned_blocks:
                continue  # Already assigned
            
            # Find next empty block
            for i, b in enumerate(self.blocks):
                if i + 1 in assigned_blocks:
                    continue
                if not b.get("source_media") or not os.path.exists(b.get("source_media", "")):
                    is_vid = is_video_file(p)
                    b["source_media"] = p
                    b["media_type"] = "video" if is_vid else "image"
                    b["video"] = p if is_vid else ""
                    b["trim_start"] = b["trim_end"] = None
                    b["trimmed_loop_path"] = None
                    try:
                        b["trim_label"].configure(text="No trim")
                    except:
                        pass
                    queue_batch.append((b, p, "Block " + str(i + 1)))
                    assigned_blocks.add(i + 1)
                    mapped += 1
                    break
        
        # Start throttled queueing with 20-file batches
        self.after(0, lambda: _queue_batch_throttled(queue_batch[:20], 0))
        
        # Final status
        self.after(0, lambda: self._ss(
            f"✓ Mapped {mapped}/{len(paths)} files · loading thumbnails in background…",
            C["green"]))

    def _uv(self):
        ps=filedialog.askopenfilenames(filetypes=[("Video","*.mp4 *.mov *.avi *.mkv *.webm *.flv")])
        if ps: self._mvb(list(ps))
    def _uf(self):
        folder=filedialog.askdirectory(title="Video folder")
        if not folder: return
        ps=[os.path.join(r,f) for r,_,fs in os.walk(folder) for f in fs if os.path.splitext(f)[1].lower() in VIDEO_EXTS]
        if not ps: messagebox.showinfo("Folder","No videos."); return
        self._mvb(ps)
    def _bulk_upload_media(self):
        """Upload videos/images in bulk. Auto-map Scene_1_, Scene_2_, etc. to blocks.
        Supports both files AND folders (with subfolders)!"""
        if not self.blocks:
            messagebox.showwarning("Blocks","Create blocks first."); return
        
        # Ask user: Files or Folder?
        choice = messagebox.askyesnocancel("Upload Type", 
            "Click YES to select a FOLDER (will scan all subfolders)\n"
            "Click NO to select individual FILES\n"
            "Click CANCEL to abort")
        
        if choice is None:  # Cancel
            return
        
        all_files = []
        
        if choice:  # YES - Select folder
            folder = filedialog.askdirectory(title="Select folder with media files")
            if not folder: return
            
            # Scan folder and ALL subfolders for media files
            self._ss(f"Scanning folder: {os.path.basename(folder)}...", C["orange"])
            media_extensions = ('.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', 
                              '.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif', '.tiff', '.tif')
            
            for root, dirs, files in os.walk(folder):
                for file in files:
                    if file.lower().endswith(media_extensions):
                        full_path = os.path.normpath(os.path.join(root, file))
                        all_files.append(full_path)
            
            if not all_files:
                messagebox.showwarning("No Media", 
                    f"No media files found in:\n{folder}\n\nSupported: mp4, mov, jpg, png, etc.")
                return
            
            self._ss(f"Found {len(all_files)} media files in folder & subfolders", C["green"])
        
        else:  # NO - Select files
            ps = filedialog.askopenfilenames(filetypes=[
                ("Media","*.mp4 *.mov *.avi *.mkv *.webm *.flv *.jpg *.jpeg *.png *.webp *.bmp *.gif"),
                ("Video","*.mp4 *.mov *.avi *.mkv *.webm *.flv"),
                ("Image","*.jpg *.jpeg *.png *.webp *.bmp *.gif")])
            if not ps: return
            all_files = [os.path.normpath(p) for p in ps]
        
        # Map files to blocks (Scene_N_ matching + sequential fill)
        self._map_media_to_blocks(all_files)

    def _map_media_to_blocks(self, paths):
        """Map uploaded media (video/image) to blocks. Scene_1_ maps to block 1, etc."""
        paths=sort_files(paths); mapped=0
        # First pass: explicit Scene_N_ matches
        used=set()
        for p in paths:
            n=extract_scene_number(p)
            if n and 1<=n<=len(self.blocks):
                b=self.blocks[n-1]
                b["source_media"]=p
                b["media_type"]="video" if is_video_file(p) else "image"
                b["video"]=p if is_video_file(p) else ""
                b["trim_start"]=b["trim_end"]=None
                b["trimmed_loop_path"]=None
                b["trim_label"].configure(text="No trim")
                # Queue thumbnail load
                self._queue_media_load(b, p, status_prefix="Mapped")
                mapped+=1
                used.add(p)
        # Second pass: remaining → fill empty blocks sequentially
        for p in paths:
            if p in used: continue
            n=extract_scene_number(p)
            if n and 1<=n<=len(self.blocks): continue
            for b in self.blocks:
                if not b.get("source_media") or not os.path.exists(b.get("source_media","")):
                    b["source_media"]=p
                    b["media_type"]="video" if is_video_file(p) else "image"
                    b["video"]=p if is_video_file(p) else ""
                    b["trim_start"]=b["trim_end"]=None
                    b["trimmed_loop_path"]=None
                    b["trim_label"].configure(text="No trim")
                    self._queue_media_load(b, p, status_prefix="Mapped seq")
                    mapped+=1
                    break
        self._ss(f"Queued {mapped}/{len(paths)} — loading thumbnails…",C["orange"])

    def _mvb(self,paths):
        """Map uploaded videos to blocks — calls the unified media mapper."""
        self._map_media_to_blocks(paths)

    # ── Task 4: Generate audio only for single block ──
    def _gen_audio_single(self,idx):
        if idx<0 or idx>=len(self.blocks): return
        threading.Thread(target=self._gen_audio_worker,args=(idx,),daemon=True).start()

    def _gen_audio_worker(self,idx):
        # Add small random delay to stagger API calls and avoid rate limiting
        import random
        time.sleep(random.uniform(0.1, 0.5))
        
        b=self.blocks[idx]; num=b["num"]; text=b["text"]; char=b.get("character","")
        if not text or b.get("video_only"): return
        def st(t,c): self._block_status(b,t,c)
        ci=self.characters.get(char,{}); vid_id=ci.get("voice_id","")
        if not vid_id: vid_id=self.common_voice_id.get()
        if not vid_id: st(f"No voice!",C["red"]); return
        ak=self.api_entry.get().strip()
        if not ak: st("No API!",C["red"]); return
        mn = self.model_var.get() if hasattr(self, "model_var") else ""
        mid = None
        for m in getattr(self, "models", []):
            if m.get("name","") == mn: mid = m.get("model_id",""); break
        if not mid and hasattr(self, "_model_id_map"):
            mid = self._model_id_map.get(mn, "")
        if not mid: mid = "eleven_multilingual_v2"
        # Check cache first
        cached=TTSCache.get_cached_audio(num,text)
        if cached:
            b["tts_audio"]=cached; st(f"🔊 Cached ({format_duration(get_duration(cached))})",C["green"]); return
        st(f"🔊 TTS...",C["orange"])
        
        # ═══════════════════════════════════════════════════════════
        # NEW: Split text into chunks (ElevenLabs max 5000 chars/request)
        # ═══════════════════════════════════════════════════════════
        MAX_CHARS_PER_REQUEST = 5000
        text_chunks = []
        if len(text) <= MAX_CHARS_PER_REQUEST:
            text_chunks = [text]
        else:
            # Split by sentences while respecting MAX_CHARS_PER_REQUEST
            sentences = re.split(r'(?<=[.!?])\s+', text)
            current_chunk = ""
            for sent in sentences:
                if len(current_chunk) + len(sent) + 1 <= MAX_CHARS_PER_REQUEST:
                    current_chunk += (" " if current_chunk else "") + sent
                else:
                    if current_chunk:
                        text_chunks.append(current_chunk)
                    current_chunk = sent
            if current_chunk:
                text_chunks.append(current_chunk)
        
        # Generate audio for each chunk and merge
        audio_files = []
        for chunk_idx, chunk_text in enumerate(text_chunks):
            if self._cancelled: return
            rp = os.path.join(TEMP_DIR, f"adv_tts_{num}_chunk_{chunk_idx}_raw.mp3")
            pl = {"text": chunk_text, "model_id": mid, "voice_settings": {"stability": 0.82, "similarity_boost": 0.75, "style": 0.0, "use_speaker_boost": True}}
            err = None
            try:
                from ai33_api import ai33_tts_generate
                if ai33_tts_generate(text=chunk_text, voice_id=vid_id, api_key=ak, out_path=rp):
                    chunk_dur = get_duration(rp)
                    if chunk_dur and chunk_dur > 0.25:
                        err = None
                    else:
                        err = "audio too short or invalid"
                else:
                    err = "AI33Pro TTS failed"
            except Exception as _e:
                err = str(_e)
            
            if err:
                st(f"TTS fail (chunk {chunk_idx+1}): {err[:30]}", C["red"])
                return
            audio_files.append(rp)
        
        # Merge all chunks if multiple
        if len(audio_files) > 1:
            rp = os.path.join(TEMP_DIR, f"adv_tts_{num}_merged.mp3")
            concat_list_file = os.path.join(TEMP_DIR, f"adv_tts_{num}_concat.txt")
            with open(concat_list_file, "w") as f:
                for af in audio_files:
                    f.write(f"file '{af}'\n")
            cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_file, "-c", "copy", rp]
            _run_ff(cmd, timeout=300)
            if os.path.exists(rp) and os.path.getsize(rp) > 2048:
                for af in audio_files:
                    try: os.remove(af)
                    except: pass
                try: os.remove(concat_list_file)
                except: pass
            else:
                # Fallback: use first chunk
                rp = audio_files[0]
        else:
            rp = audio_files[0]
        
        if not os.path.exists(rp) or os.path.getsize(rp) <= 2048:
            st(f"TTS fail: No audio generated", C["red"])
            return
        
        pad = max(0, float(self.silence_var.get())); cl = os.path.join(TEMP_DIR, f"adv_tts_{num}_clean.wav")
        ap = clean_tts_audio(rp, cl, pad_sec=pad) or rp; b["tts_audio"] = ap; TTSCache.store(num, text, ap)
        st(f"🔊 Ready ({format_duration(get_duration(ap))})", C["green"])
        # Task 5: If narrator (has audio now), start backend video compose
        mp = b.get("source_media", "")
        if mp and os.path.exists(mp) and b.get("trim_start") is not None:
            threading.Thread(target=self._auto_process_trim, args=(idx, get_duration(ap)), daemon=True).start()

    # ── Task 4: Generate ALL audio ──
    def _gen_all_audio(self):
        blocks_with_text=[i for i,b in enumerate(self.blocks) if b.get("text") and not b.get("video_only")]
        if not blocks_with_text: messagebox.showwarning("Audio","No blocks with script."); return
        ak=self.api_entry.get().strip()
        if not ak: messagebox.showwarning("API","Enter API key."); return
        self._cancelled=False
        threading.Thread(target=self._gen_all_audio_worker,args=(blocks_with_text,),daemon=True).start()

    def _gen_all_audio_worker(self,indices):
        total=len(indices); done=0
        self._ss(f"Audio 0/{total}...",C["orange"]); self._sp(0)
        
        # First pass: Generate audio for all blocks
        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_TTS,total)) as ex:
            fm={ex.submit(self._gen_audio_worker,i):i for i in indices}
            for fut in as_completed(fm):
                if self._cancelled: break
                try: fut.result()
                except Exception as e: 
                    idx = fm.get(fut)
                    if idx is not None:
                        self._sss(f"[Block {idx}] Audio generation error: {str(e)[:50]}")
                with self._progress_lock: done+=1
                self._sp(done/total); self._ss(f"Audio {done}/{total}...",C["orange"])
        
        # Check for failed blocks and report
        ready=sum(1 for i in indices if self.blocks[i].get("tts_audio") and os.path.exists(self.blocks[i]["tts_audio"]))
        failed = total - ready
        
        self._sp(1.0)
        if failed > 0:
            self._ss(f"Audio done: {ready}/{total} ✓ | {failed} failed (check API key & internet)",C["orange"])
        else:
            self._ss(f"Audio done: {ready}/{total} ✓ All complete!",C["green"])

    # ── Full scene generate ──
    def _gs(self,idx):
        if idx<0 or idx>=len(self.blocks): return
        threading.Thread(target=self._gw,args=(idx,),daemon=True).start()

    def _gw(self,idx):
        b=self.blocks[idx]; num=b["num"]; text=b["text"]; char=b.get("character","")
        def st(t,c): self._block_status(b,t,c)
        def ts(s): self._sss(f"[#{num}] {s}")

        # ── Task 7: Video-only blocks ──
        if b.get("video_only"):
            mp=b.get("source_media","")
            if not mp or not os.path.exists(mp): st("No video!",C["red"]); return
            vd=get_duration(mp)
            if vd<=0: st("Invalid video!",C["red"]); return
            st("[1/2] Processing video...",C["orange"]); ts("video-only: processing")
            # Task 9: Apply clip volume
            clip_vol=b.get("clip_volume",0); master_vol=self.master_vol_var.get()
            eff_vol=(clip_vol/100.0)*(master_vol/100.0)
            op=os.path.join(TEMP_DIR,f"adv_out_{num}.mp4")
            if has_audio_stream(mp) and eff_vol>0:
                cmd=["ffmpeg","-y","-i",mp,"-af",f"volume={eff_vol:.2f}"]
                cmd+=GPU.enc_args("fast"); cmd+=["-c:a","aac","-b:a","192k",op]
            elif has_audio_stream(mp):
                cmd=["ffmpeg","-y","-i",mp,"-an"]; cmd+=GPU.enc_args("fast"); cmd+=[op]
            else:
                cmd=["ffmpeg","-y","-i",mp]; cmd+=GPU.enc_args("fast"); cmd+=["-an",op]
            _run_ff(cmd,timeout=300)
            if os.path.exists(op) and get_duration(op)>0.1:
                b["output"]=op; st(f"✓ Done ({format_duration(get_duration(op))})",C["green"])
            else: st("Failed!",C["red"])
            return

        # ── Normal scene with audio ──
        ci=self.characters.get(char,{}); vid_id=ci.get("voice_id","")
        if not vid_id: vid_id=self.common_voice_id.get()

        # Step 1: Audio
        if not b.get("tts_audio") or not os.path.exists(b.get("tts_audio","")):
            if text and vid_id:
                st("[1/5] TTS...",C["orange"]); ts("step 1: TTS")
                self._gen_audio_worker(idx)
            elif not text:
                # No script, no audio — render video only at its own length
                b["video_only"]=True; self._gw(idx); return

        ap=b.get("tts_audio","")
        if not ap or not os.path.exists(ap):
            # No audio available — render video at its own length
            mp=b.get("source_media","")
            if mp and os.path.exists(mp):
                b["video_only"]=True; self._gw(idx); return
            st("No audio & no video!",C["red"]); return

        ta=get_duration(ap)
        if ta<=0.1: st("Audio invalid!",C["red"]); return

        # Step 2: Video compose
        st(f"[3/5] Video ({format_duration(ta)})...",C["orange"]); ts("step 3: video")
        
        # ═══════════════════════════════════════════════════════════
        # FIX: Handle Windows paths properly
        # ═════════════════════════════════════════════════════════════
        mp=b.get("source_media","")
        # Normalize path (handle Windows backslashes)
        if mp:
            mp = os.path.normpath(mp)
        
        vp=None
        loop_mode=b.get("loop_mode","pingpong")
        if mp and os.path.exists(mp):
            # ═══════════════════════════════════════════════════════════
            # FIX: Check if it's an IMAGE - convert to video!
            # ═════════════════════════════════════════════════════════════
            if is_image_file(mp):
                # ── Whiteboard animation (Video Master): sketch the image LEFT→RIGHT;
                #    drawing finishes ~freeze_tail sec before the voiceover ends, then
                #    the finished frame freezes for the rest of the scene. ──
                wb_on = False
                try:
                    wb_on = bool(self._wb_on.get()) and HAS_CV2
                except Exception:
                    wb_on = False
                # Skip whiteboard for very short scenes (< 5s) — there isn't enough
                # time for a natural hand-drawing, so render the image normally.
                if wb_on and ta < 5.0:
                    wb_on = False
                    ts(f"Scene {ta:.1f}s < 5s — skipping whiteboard, using plain image")
                if wb_on:
                    try:
                        freeze_tail = max(0.0, float(self._wb_freeze_var.get()))
                    except Exception:
                        freeze_tail = 2.5
                    hand = getattr(self, "_wb_hand", "") or None
                    effect_choice = getattr(self, "_reveal_effect_var", None)
                    effect_name = effect_choice.get() if effect_choice else (self.settings.get("reveal_effect") or "✍️ Whiteboard Hand Sketch")
                    
                    ts(f"Reveal effect: {effect_name} on {os.path.basename(mp)} (freeze {freeze_tail:.1f}s)")
                    st(f"[3/5] {effect_name}...", C["orange"])
                    wb_vid = os.path.join(TEMP_DIR, f"adv_wb_{num}.mp4")
                    
                    res = None
                    if "Rain" in effect_name:
                        res = image_to_raindrop_reveal_video(mp, ta, wb_vid, freeze_tail=freeze_tail, out_w=1920, out_h=1080)
                    elif "Blood" in effect_name:
                        res = image_to_blooddrop_reveal_video(mp, ta, wb_vid, freeze_tail=freeze_tail, out_w=1920, out_h=1080)
                    elif "Fire" in effect_name or "Paper" in effect_name:
                        res = image_to_paper_burn_reveal_video(mp, ta, wb_vid, freeze_tail=freeze_tail, out_w=1920, out_h=1080)
                    elif "Sparkle" in effect_name:
                        res = image_to_sparkle_reveal_video(mp, ta, wb_vid, freeze_tail=freeze_tail, out_w=1920, out_h=1080)
                    else: # Default Whiteboard Hand Sketch
                        res = image_to_whiteboard_video(mp, ta, wb_vid, freeze_tail=freeze_tail, out_w=1920, out_h=1080, hand_path=hand)
                    
                    if res and os.path.exists(res) and get_duration(res) > 0.1:
                        vp = res
                        ts(f"Reveal animation ({effect_name}) created successfully")
                    else:
                        ts("Reveal effect failed - falling back to plain image video")

                if vp is None:
                    # Image: convert to video with audio duration
                    ts(f"Image detected: {os.path.basename(mp)} - converting to video")
                    img_vid = os.path.join(TEMP_DIR, f"adv_img_{num}.mp4")
                    # Create video from image - simple, fast, no zoom
                    cmd_img = ["ffmpeg", "-y", "-loop", "1", "-i", mp, 
                              "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                              "-pix_fmt", "yuv420p", "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black",
                              "-t", str(ta), "-r", "30", img_vid]
                    result = _run_ff(cmd_img, timeout=180)
                    if os.path.exists(img_vid) and get_duration(img_vid) > 0.1:
                        vp = img_vid
                        ts(f"Image converted to video successfully")
                    else:
                        ts(f"Image conversion failed - will use black")
            elif b.get("trim_start") is not None and b.get("trim_end") is not None:
                if b.get("trimmed_loop_path") and os.path.exists(b["trimmed_loop_path"]):
                    pre_dur=get_duration(b["trimmed_loop_path"])
                    if abs(pre_dur-ta)<0.5: vp=b["trimmed_loop_path"]; ts("using pre-trimmed")
                if not vp:
                    st("[3/5] Trim & Loop...",C["orange"])
                    if loop_mode=="pingpong":
                        seg=os.path.join(TEMP_DIR,f"adv_seg_{num}.mp4")
                        cmd=["ffmpeg","-y","-ss",str(b["trim_start"]),"-i",mp,"-t",str(b["trim_end"]-b["trim_start"])]
                        cmd+=GPU.enc_args("fast"); cmd+=["-an",seg]
                        _run_ff(cmd,timeout=300)
                        pp=os.path.join(TEMP_DIR,f"adv_pp_{num}.mp4")
                        if os.path.exists(seg) and get_duration(seg)>0.05:
                            vp=build_pingpong_video(seg,ta,pp)
                    else:
                        tv=os.path.join(TEMP_DIR,f"adv_tl_{num}.mp4")
                        vp=build_trim_loop_video(mp,b["trim_start"],b["trim_end"],ta,tv)
                    if not vp: vp=simple_loop_video(mp,ta,num)
            else:
                vd=get_duration(mp)
                if vd>ta+0.05:
                    # Video LONGER than voiceover. Video Master tab → speed up to fit.
                    if getattr(self, "_speed_fit_long_video", False):
                        ts(f"Video {format_duration(vd)} > voice {format_duration(ta)} — speeding {vd/ta:.2f}x to fit")
                        sf=os.path.join(TEMP_DIR,f"adv_speed_{num}.mp4")
                        vp=speed_fit_video(mp,ta,sf)
                        if not vp:
                            tr=os.path.join(TEMP_DIR,f"adv_tr_{num}.mp4")
                            cmd=["ffmpeg","-y","-i",mp,"-t",str(ta)]; cmd+=GPU.enc_args("fast"); cmd+=["-an",tr]
                            _run_ff(cmd,timeout=300)
                            vp=tr if os.path.exists(tr) and get_duration(tr)>0.1 else mp
                    else:
                        tr=os.path.join(TEMP_DIR,f"adv_tr_{num}.mp4")
                        cmd=["ffmpeg","-y","-i",mp,"-t",str(ta)]; cmd+=GPU.enc_args("fast"); cmd+=["-an",tr]
                        _run_ff(cmd,timeout=300)
                        vp=tr if os.path.exists(tr) and get_duration(tr)>0.1 else mp
                elif vd<ta-0.05:
                    # Video shorter than voiceover. Video Master tab → freeze last frame.
                    if getattr(self, "_freeze_extend_short_video", False):
                        ts(f"Video {format_duration(vd)} < voice {format_duration(ta)} — freezing last frame")
                        fz=os.path.join(TEMP_DIR,f"adv_freeze_{num}.mp4")
                        vp=freeze_last_frame_video(mp,ta,fz)
                        if not vp: vp=simple_loop_video(mp,ta,num)
                    else:
                        vp=simple_loop_video(mp,ta,num)
                else: vp=mp
        if not vp or not os.path.exists(str(vp)):
            # ═══════════════════════════════════════════════════════════
            # FALLBACK: No source media - create background video
            # ═══════════════════════════════════════════════════════════
            # Show warning about missing media
            ts(f"⚠️ WARNING: Block #{num} has NO source media - using black background")
            st(f"⚠️ No media - black bg", C["orange"])
            
            # Try to use filler if available
            if self.filler_path and os.path.exists(self.filler_path):
                # Use filler video as background
                vp = self.filler_path
                ts(f"Using filler video as fallback")
            else:
                # Generate black video with TTS audio
                vp=os.path.join(TEMP_DIR,f"adv_bk_{num}.mp4")
                generate_black_video(ta,output=vp)
                ts(f"Generated black background video")
                # Note to user: Add media to improve visual output
                self._sss(f"⚠️ Block #{num} needs media (image/video) - showing black background")

        # Normalize video — SKIP if already correct format
        # Source video ka audio agar hai to copy/encode kar lo; agar nahi hai to silent rakho.
        vw,vh=get_resolution(vp)
        if vw<=0 or vh<=0: vw,vh=1920,1080
        
        # ═══════════════════════════════════════════════════════════
        # OPTIMIZATION: Skip normalization if resolution already matches
        # ═════════════════════════════════════════════════════════════
        src_has_audio=has_audio_stream(vp)
        needs_normalization = vw != 1920 or vh != 1080  # If not standard resolution
        
        if needs_normalization:
            # Only normalize if needed
            norm_vp=os.path.join(TEMP_DIR,f"adv_norm_{num}.mp4")
            cmd=["ffmpeg","-y","-i",vp,"-vf",
                f"scale={vw}:{vh}:force_original_aspect_ratio=decrease,pad={vw}:{vh}:(ow-iw)/2:(oh-ih)/2:black,fps=30,format=yuv420p,setsar=1"]
            cmd+=["-c:v","libx264","-preset","ultrafast","-crf","28"]
            if src_has_audio:
                cmd+=["-c:a","aac","-b:a","192k","-ar","48000","-ac","2"]
            else:
                cmd+=["-an"]
            cmd+=["-t",str(ta),norm_vp]
            _run_ff(cmd,timeout=300)
            if os.path.exists(norm_vp) and get_duration(norm_vp)>0.1: vp=norm_vp
        else:
            # Video already good, use directly
            ts(f"Video resolution OK - skipping normalization")

        # ── Pull ORIGINAL source audio (mp) too — many of our loop/trim helpers strip audio (-an),
        # so vp may not have audio even if the user's source had it. We fetch it directly from `mp`,
        # pad/trim it to ta seconds, and use it as the clip-audio source in mixing.
        clip_audio_src=None
        try:
            if mp and os.path.exists(mp) and not is_image_file(mp) and has_audio_stream(mp):
                clip_audio_src=os.path.join(TEMP_DIR,f"_clip_audio_src_{num}.aac")
                # Stretch / loop audio to ta seconds: apad at end, then atrim to exact ta
                cmd_ca=["ffmpeg","-y","-stream_loop","-1","-i",mp,
                        "-vn","-af",f"aresample=48000:async=1:first_pts=0,apad,atrim=0:{ta:.3f},asetpts=N/SR/TB",
                        "-t",str(ta),"-ar","48000","-ac","2","-c:a","aac","-b:a","192k",clip_audio_src]
                _run_ff(cmd_ca,timeout=180)
                if not (os.path.exists(clip_audio_src) and get_duration(clip_audio_src)>0.1):
                    clip_audio_src=None
        except: clip_audio_src=None

        # Step 3: Logo + Captions  (crop & chroma removed)
        st("[4/5] Logo + Captions...",C["orange"]); ts("step 4: logo+captions")
        use_logo=self.logo_enabled_var.get() and not getattr(self,"_story_skip_logo",False)
        logo_p=self.logo_path_var.get(); logo_sz=self.logo_size_var.get(); logo_opa=self.logo_opacity_var.get()
        effective_logo_p=None
        if use_logo and logo_p and os.path.exists(logo_p):
            # Use the cropped image ONLY if it was made from the CURRENT logo file.
            # This guarantees a freshly-selected logo is always the one rendered
            # (no stale/old logo leaking through).
            cropped_ok = (self.logo_cropped_pil is not None and
                          getattr(self, "_logo_cropped_for_path", None) == logo_p)
            if cropped_ok:
                ctp=os.path.join(TEMP_DIR,f"_logo_cropped_{num}.png")
                try: self.logo_cropped_pil.save(ctp); effective_logo_p=ctp
                except: effective_logo_p=logo_p
            else:
                effective_logo_p=logo_p
            # Pre-convert logo to a clean RGBA PNG. The temp name includes a hash of
            # the source path + mtime so a changed logo never reuses an old cached file.
            if effective_logo_p:
                try:
                    sig=f"{logo_p}|{os.path.getmtime(logo_p)}|{'crop' if cropped_ok else 'orig'}"
                    tag=hashlib.md5(sig.encode("utf-8")).hexdigest()[:10]
                    fixed_logo=os.path.join(TEMP_DIR,f"_logo_fixed_{num}_{tag}.png")
                    logo_img=Image.open(effective_logo_p).convert("RGBA")
                    logo_img.save(fixed_logo,format="PNG")
                    if os.path.exists(fixed_logo) and os.path.getsize(fixed_logo)>100:
                        effective_logo_p=fixed_logo
                except: pass
        op=os.path.join(TEMP_DIR,f"adv_out_{num}.mp4")
        vw2,vh2=get_resolution(vp)
        out_w,out_h=vw2,vh2
        vf_parts=[]
        vf_parts.append(f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1")
        # Build caption filter if enabled
        cap_filter_str=""
        _cap_on=self.captions_enabled_var.get()
        _cap_has=num in self._caption_groups
        
        # Only do caption processing if enabled
        if _cap_on and _cap_has:
            cap_groups=self._caption_groups[num]
            cf_str=build_caption_drawtext_filter(
                cap_groups, out_w, out_h,
                font_path=self.caption_font_path_var.get(),
                font_size=self.caption_font_size_var.get(),
                font_color=self.caption_font_color_var.get().strip().lstrip("#"),
                bg_color=self.caption_bg_color_var.get().strip().lstrip("#"),
                bg_opacity=self.caption_bg_opacity_var.get(),
                position=self.caption_position_var.get(),
                margin_bottom=self.caption_margin_var.get(),
                animation=self.caption_animation_var.get()
            )
            if cf_str: cap_filter_str=","+cf_str
        # Blend text overlay
        if self.blend_text_enabled_var.get() and num in self._blend_texts:
            bt=self._blend_texts[num]
            ap2=b.get("tts_audio","")
            bt_dur=get_duration(ap2) if (ap2 and os.path.exists(ap2)) else get_duration(vp)
            bt_groups=[{"text":bt,"start":0.0,"end":bt_dur}]
            bt_cf=build_caption_drawtext_filter(bt_groups,out_w,out_h,
                font_path=self.blend_text_font_path_var.get(),
                font_size=self.blend_text_font_size_var.get(),
                font_color=self.blend_text_font_color_var.get().strip().lstrip("#"),
                bg_color=self.blend_text_bg_color_var.get().strip().lstrip("#"),
                bg_opacity=self.blend_text_bg_opacity_var.get(),
                position=self.blend_text_position_var.get(),
                margin_bottom=self.blend_text_margin_var.get(),
                animation=self.blend_text_animation_var.get(),
                border_w=self.blend_text_border_w_var.get(),
                border_color=self.blend_text_border_color_var.get().strip().lstrip("#"),
                shadow=self.blend_text_shadow_var.get(),
                align=self.blend_text_align_var.get())
            if bt_cf: cap_filter_str+=","+bt_cf
        # ── Audio mixing: Clip audio + TTS audio + Blend SFX ──
        clip_vol=b.get("clip_volume",0); master_clip=self.master_vol_var.get()
        tts_vol=b.get("tts_volume",100); master_tts=self.master_tts_vol_var.get()
        eff_clip=(clip_vol/100.0)*(master_clip/100.0)
        eff_tts=(tts_vol/100.0)*(master_tts/100.0)

        # Clip audio comes from the original source file (we pulled it earlier as clip_audio_src).
        # Falls back to whatever vp has if extraction failed.
        clip_aud_path=clip_audio_src if (clip_audio_src and os.path.exists(clip_audio_src)) else (vp if has_audio_stream(vp) else None)
        has_clip_audio=bool(clip_aud_path) and eff_clip>0.001
        has_tts=ap and os.path.exists(ap) and eff_tts>0.001

        # Blend SFX (from ElevenLabs Sound Effects) — auto-mapped by scene number.
        sfx_path=None
        sfx_vol=1.0
        try:
            sfx_path=self._blend_sfx.get(num) if hasattr(self,"_blend_sfx") else None
            if sfx_path and not os.path.exists(sfx_path): sfx_path=None
            if sfx_path:
                sfx_vol=float(getattr(self,"blend_sfx_volume_var",ctk.DoubleVar(value=1.0)).get())
                sfx_vol=max(0.0,min(2.0,sfx_vol))
        except: sfx_path=None
        has_sfx=bool(sfx_path)

        ts(f"audio mix: clip={has_clip_audio}({eff_clip:.2f}) tts={has_tts}({eff_tts:.2f}) sfx={has_sfx}")

        # Build a single amix command with whichever sources are active.
        mixed_ap=ap if has_tts else None
        sources=[]   # list of (input_path, volume, label)
        if has_clip_audio: sources.append((clip_aud_path, eff_clip, "clip"))
        if has_tts:        sources.append((ap, eff_tts, "tts"))
        if has_sfx:        sources.append((sfx_path, sfx_vol, "sfx"))

        if len(sources)>=2:
            mixed_ap=os.path.join(TEMP_DIR,f"_mix_audio_{num}.aac")
            cmd_mix=["ffmpeg","-y"]
            for src,_v,_l in sources: cmd_mix+=["-i",src]
            parts=[]; labels=[]
            for i,(_src,v,lbl) in enumerate(sources):
                parts.append(f"[{i}:a]volume={v:.3f},aresample=48000:async=1:first_pts=0[{lbl}{i}]")
                labels.append(f"[{lbl}{i}]")
            af_mix=";".join(parts)+";"+"".join(labels)+f"amix=inputs={len(sources)}:duration=longest:normalize=0[outa]"
            cmd_mix+=["-filter_complex",af_mix,"-map","[outa]","-t",str(ta),
                      "-c:a","aac","-b:a","192k","-ar","48000","-ac","2",mixed_ap]
            _run_ff(cmd_mix,timeout=180)
            if not (os.path.exists(mixed_ap) and get_duration(mixed_ap)>0.1):
                # fallback chain: prefer TTS > clip > sfx
                mixed_ap=ap if has_tts else (clip_aud_path if has_clip_audio else sfx_path)
        elif len(sources)==1:
            src,v,lbl=sources[0]
            mixed_ap=os.path.join(TEMP_DIR,f"_one_audio_{num}.aac")
            cmd_one=["ffmpeg","-y","-i",src,"-af",f"volume={v:.3f},aresample=48000:async=1:first_pts=0",
                     "-t",str(ta),"-c:a","aac","-b:a","192k","-ar","48000","-ac","2",mixed_ap]
            _run_ff(cmd_one,timeout=120)
            if not (os.path.exists(mixed_ap) and get_duration(mixed_ap)>0.1):
                mixed_ap=src
        else:
            # No audio at all — generate silence so downstream -map "1:a" still works
            mixed_ap=os.path.join(TEMP_DIR,f"_silent_{num}.aac")
            cmd_sil=["ffmpeg","-y","-f","lavfi","-i","anullsrc=r=48000:cl=stereo",
                     "-t",str(ta),"-c:a","aac","-b:a","128k",mixed_ap]
            _run_ff(cmd_sil,timeout=60)
            if not (os.path.exists(mixed_ap) and get_duration(mixed_ap)>0.1):
                mixed_ap=ap  # last resort

        # ── Blend Video overlay (green-screen lower-third) ──
        # If the user assigned a blend video for this scene, chroma-key it (mute) and
        # composite it over the main scene BEFORE logo/captions are applied.
        blend_video_path=None
        try:
            blend_video_path=self._blend_videos.get(num) if hasattr(self,"_blend_videos") else None
            if blend_video_path and not os.path.exists(blend_video_path): blend_video_path=None
        except: blend_video_path=None

        if blend_video_path:
            ts(f"applying blend video: {os.path.basename(blend_video_path)}")
            bv_out=os.path.join(TEMP_DIR,f"_blend_overlay_{num}.mp4")
            # Chroma key params (defaults: green key)
            try:
                key_color=self.blend_video_key_color_var.get().strip().lstrip("#") or "00FF00"
            except: key_color="00FF00"
            try:    key_sim=float(self.blend_video_similarity_var.get())
            except: key_sim=0.30
            try:    key_blend=float(self.blend_video_blend_var.get())
            except: key_blend=0.10
            # Position scale: blend video stretches over scene at lower-third by default,
            # but we keep aspect: place at bottom, full-width, ~33% height.
            bv_h=max(1,out_h//3)
            # Filter: scale blend to scene width × 1/3 height, chroma-key, overlay at bottom.
            # Note: 0x{hex} colorkey works with similarity (0-1) & blend (0-1).
            fc_blend=(
                f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
                f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[base];"
                f"[1:v]scale={out_w}:{bv_h}:force_original_aspect_ratio=decrease,"
                f"colorkey=0x{key_color}:{key_sim:.2f}:{key_blend:.2f},format=yuva420p[bv];"
                f"[base][bv]overlay=(W-w)/2:H-h-20:shortest=0[outv]"
            )
            cmd_bv=["ffmpeg","-y","-i",vp,"-i",blend_video_path,"-filter_complex",fc_blend,
                    "-map","[outv]","-an","-t",str(ta)]
            cmd_bv+=GPU.enc_args("fast"); cmd_bv+=["-pix_fmt","yuv420p",bv_out]
            _run_ff(cmd_bv,timeout=300)
            if os.path.exists(bv_out) and get_duration(bv_out)>0.1:
                vp=bv_out
                ts("blend video composited ✓")
            else:
                ts("blend video failed, continuing without it")
        if effective_logo_p and os.path.exists(effective_logo_p):
            # ═══════════════════════════════════════════════════════════
            # Position AND size are stored as fractions of the preview frame
            # (which uses the same 1920x1080 letterbox geometry as the output).
            # Scaling both by the real output resolution makes the logo land in
            # the EXACT same relative spot & size as shown in the preview.
            # ═════════════════════════════════════════════════════════════
            pct_x = getattr(self, "_logo_pct_x", None)
            pct_y = getattr(self, "_logo_pct_y", None)
            pct_size = getattr(self, "_logo_pct_size", None)

            # Logo render size (square) — from fraction of frame width if available
            if pct_size is not None and pct_size > 0:
                logo_w = max(8, int(round(out_w * pct_size)))
            else:
                logo_w = max(8, int(logo_sz))
            logo_h = logo_w

            if pct_x is not None and pct_y is not None:
                # Fraction-based → guarantees position matches the preview
                lx = int(round(out_w * pct_x))
                ly = int(round(out_h * pct_y))
            else:
                # Fallback to old pixel/anchor behavior
                lx=self.logo_pos_x_var.get(); ly=self.logo_pos_y_var.get()
                if lx<=0 and ly<=0:
                    logo_anc=self.logo_anchor_var.get(); logo_mx=self.logo_mx_var.get(); logo_my=self.logo_my_var.get()
                    lx,ly=calc_logo_xy(logo_anc,logo_mx,logo_my,logo_w,out_w,out_h)

            lx=max(0,min(lx,max(0,out_w-logo_w))); ly=max(0,min(ly,max(0,out_h-logo_h)))
            opa_f=logo_opa/100.0; vf_str=",".join(vf_parts)
            cf=(f"[0:v]{vf_str},format=yuv420p[base];"
                f"[2:v]scale={logo_w}:{logo_h},format=rgba,colorchannelmixer=aa={opa_f}[logo];"
                f"[base][logo]overlay={lx}:{ly}:format=auto[outv]")
            if cap_filter_str:
                logo_tmp=os.path.join(TEMP_DIR,f"_logo_tmp_{num}.mp4")
                cmd_l=["ffmpeg","-y","-i",vp,"-i",mixed_ap,"-i",effective_logo_p,"-filter_complex",cf,
                    "-map","[outv]","-map","1:a","-t",str(ta)]
                cmd_l+=GPU.enc_args("fast"); cmd_l+=["-pix_fmt","yuv420p","-c:a","aac","-b:a","192k",logo_tmp]
                _run_ff(cmd_l,timeout=600)
                if os.path.exists(logo_tmp) and get_duration(logo_tmp)>0.1:
                    cmd=["ffmpeg","-y","-i",logo_tmp,"-vf",cap_filter_str.lstrip(","),"-c:a","copy"]
                    cmd+=GPU.enc_args("fast"); cmd+=["-pix_fmt","yuv420p",op]
                else:
                    vf_all=",".join(vf_parts)+cap_filter_str
                    cmd=["ffmpeg","-y","-i",vp,"-i",mixed_ap,"-vf",vf_all,"-map","0:v","-map","1:a","-t",str(ta)]
                    cmd+=GPU.enc_args("fast"); cmd+=["-pix_fmt","yuv420p","-c:a","aac","-b:a","192k",op]
            else:
                cmd=["ffmpeg","-y","-i",vp,"-i",mixed_ap,"-i",effective_logo_p,"-filter_complex",cf,
                    "-map","[outv]","-map","1:a","-t",str(ta)]
                cmd+=GPU.enc_args("fast"); cmd+=["-pix_fmt","yuv420p","-c:a","aac","-b:a","192k",op]
        else:
            vf_str=",".join(vf_parts)+cap_filter_str
            cmd=["ffmpeg","-y","-i",vp,"-i",mixed_ap,"-vf",vf_str,"-map","0:v","-map","1:a","-t",str(ta)]
            cmd+=GPU.enc_args("fast"); cmd+=["-pix_fmt","yuv420p","-c:a","aac","-b:a","192k",op]

        st("[5/5] Rendering...",C["orange"]); ts("step 5: render")
        
        # ═══════════════════════════════════════════════════════════
        # OPTIMIZATION: Use codec copy when possible (no re-encoding)
        # ═════════════════════════════════════════════════════════════
        # Determine if we can use codec copy (no video filters needed)
        has_video_filters = bool(cap_filter_str or "pad" in vf_str if vf_parts else False)
        use_codec_copy = not has_video_filters and not effective_logo_p
        
        try:
            if use_codec_copy:
                # Fast path: No filters, just copy video stream
                ts("Codec copy mode - ultra fast!")
                cmd=["ffmpeg","-y","-i",vp,"-i",mixed_ap,"-c:v","copy","-c:a","aac","-b:a","192k","-t",str(ta),op]
            else:
                # Normal path: With filters/logo
                if cap_filter_str:
                    ts(f"TEXT OVERLAY ACTIVE: {cap_filter_str[:100]}...")
                else:
                    ts("NO text overlay in this render")
                
                if effective_logo_p:
                    # With logo overlay
                    cmd=["ffmpeg","-y","-i",vp,"-i",mixed_ap,"-i",effective_logo_p,"-filter_complex",cf,
                        "-map","[outv]","-map","1:a","-t",str(ta)]
                    cmd+=["-c:v","libx264","-preset","ultrafast","-crf","28","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k",op]
                else:
                    # Without logo, with vf filters
                    vf_str=",".join(vf_parts)+cap_filter_str
                    cmd=["ffmpeg","-y","-i",vp,"-i",mixed_ap,"-vf",vf_str,"-map","0:v","-map","1:a","-t",str(ta)]
                    cmd+=["-c:v","libx264","-preset","ultrafast","-crf","28","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k",op]
            
            result=_run_ff(cmd,timeout=600)
            render_ok = result is not None and hasattr(result,'returncode') and result.returncode==0
            if not render_ok:
                err_txt=""
                if result and hasattr(result,'stderr') and result.stderr: err_txt=str(result.stderr)[:200]
                ts(f"Render failed: {err_txt}")
                # Retry with ultrafast preset
                ts("Retry with ultrafast...")
                vf_retry=",".join(vf_parts)+cap_filter_str
                cmd2=["ffmpeg","-y","-i",vp,"-i",mixed_ap,"-vf",vf_retry,"-map","0:v","-map","1:a","-t",str(ta)]
                cmd2+=["-c:v","libx264","-preset","ultrafast","-crf","28","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k",op]
                result2=_run_ff(cmd2,timeout=600)
        except Exception as e: st(f"FFmpeg: {str(e)[:30]}",C["red"]); return

        if os.path.exists(op) and get_duration(op)>0.1:
            b["output"]=op; st(f"✓ Done ({format_duration(get_duration(op))})",C["green"]); ts("DONE ✓")
            try:
                img=extract_frame(op,min(1.0,get_duration(op)/2)); img.thumbnail((72,38),Image.LANCZOS)
                tk=ImageTk.PhotoImage(img.convert("RGB")); b["_ttk"]=tk
                self.after(0,lambda:b["thumb_label"].configure(image=tk,text=""))
            except: pass
        else: st("Output missing!",C["red"])

    # ── Generate all (Task 5 + Task 10) ──
    def _gen_all(self):
        if not self.blocks: messagebox.showwarning("Blocks","No scenes."); return
        self._save_settings()  # persist before long operation
        
        # ═══════════════════════════════════════════════════════════
        # CHECK: Warn about blocks without media
        # ═══════════════════════════════════════════════════════════
        blocks_without_media = 0
        for b in self.blocks:
            if b.get("video_only"):
                continue
            mp = b.get("source_media", "")
            # Normalize path for cross-platform compatibility
            if mp:
                mp = os.path.normpath(mp)
                # Update block with normalized path
                b["source_media"] = mp
            # Check if media exists
            has_media = bool(mp and os.path.exists(mp))
            if not has_media:
                blocks_without_media += 1
        
        if blocks_without_media > 0:
            has_filler = self.filler_path and os.path.exists(self.filler_path)
            if has_filler:
                msg = (f"⚠️ {blocks_without_media} scenes have NO media.\n\n"
                      "Will use your filler video as background.\n\n"
                      "Continue?")
            else:
                msg = (f"⚠️ {blocks_without_media} scenes have NO media.\n\n"
                      "Will show BLACK background instead.\n\n"
                      "Recommendation: Set a filler video or add media to blocks first.\n\n"
                      "Continue anyway?")
            if not messagebox.askyesno("Missing Media", msg):
                self._ss("Cancelled - add media or set filler first", C["red"])
                return
        
        # Check voices for non-video-only blocks
        for b in self.blocks:
            if b.get("video_only"): continue
            if not b.get("text"): continue
            char=b.get("character",""); ci=self.characters.get(char,{})
            vid_id=ci.get("voice_id","") or self.common_voice_id.get()
            if not vid_id:
                messagebox.showwarning("Voices",f"No voice for '{char}'. Set voice or common voice."); return
        ak=self.api_entry.get().strip()
        if not ak and any(b.get("text") and not b.get("video_only") for b in self.blocks):
            messagebox.showwarning("API","Enter API key."); return
        self._cancelled=False
        threading.Thread(target=self._gaw,daemon=True).start()

    def _gaw(self):
        total=len(self.blocks); done=0
        self._ss(f"Rendering 0/{total}...",C["orange"]); self._sp(0)
        
        # ═══════════════════════════════════════════════════════════
        # OPTIMIZATION: If captions are disabled, clear caption data
        # ═════════════════════════════════════════════════════════════
        if not self.captions_enabled_var.get():
            self._caption_groups.clear()
        
        # ═══════════════════════════════════════════════════════════
        # FAST MODE: Skip audio generation phase
        # Audio should already be generated separately
        # Only do video rendering + merging
        # ═════════════════════════════════════════════════════════════
        self._sss("Fast mode: Rendering scenes...")
        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_FF,total)) as ex:
            fm={ex.submit(self._gw,i):i for i in range(total)}
            for fut in as_completed(fm):
                if self._cancelled: break
                try: fut.result()
                except Exception as e: 
                    self._sss(f"Render error: {str(e)[:50]}")
                with self._progress_lock: done+=1
                self._sp(done/total); self._ss(f"Rendering {done}/{total}...",C["orange"])
        
        ready=sum(1 for b in self.blocks if b.get("output") and os.path.exists(b["output"]))
        self._sp(1.0); fail=total-ready
        self._ss(f"Complete: {ready}/{total}" + (f" ({fail} failed)" if fail else ""),
            C["green"] if ready==total else C["orange"])

    # ── Merge ──
    def _merge(self):
        if not self.blocks: messagebox.showwarning("Merge","No scenes."); return
        self._save_settings()
        clips=[b["output"] for b in self.blocks if b.get("output") and os.path.exists(b["output"])]
        if not clips: messagebox.showwarning("Merge","Generate scenes first."); return
        sp=filedialog.asksaveasfilename(defaultextension=".mp4",initialdir=OUTPUT_DIR,filetypes=[("MP4","*.mp4")])
        if not sp: return
        self._cancelled=False
        threading.Thread(target=self._mw,args=(clips,sp),daemon=True).start()

    def _mw(self,clips,sp):
        self._ss("Normalizing...",C["orange"]); self._sp(0.05); self._sss("merge 1/5: normalize")
        tw,th=get_resolution(clips[0]) if clips else (1920,1080)
        norm=[]; trans_on=self.transition_var.get()
        try: trans_dur=float(self.trans_dur_var.get() or 0.5)
        except: trans_dur=0.5
        for i,c in enumerate(clips):
            if self._cancelled: return
            n=os.path.join(TEMP_DIR,f"adv_n_{i}.mp4")
            # Pad video (freeze last frame) AND audio (silence) to the clip's FULL
            # duration so every clip has video length == audio length. This stops the
            # voiceover from being cut and removes A/V-desync glitches at concat time.
            cd=get_duration(c)
            vf=(f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
                f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:black,fps=30,format=yuv420p,setsar=1,"
                f"tpad=stop_mode=clone:stop_duration=7200")
            cmd=["ffmpeg","-y","-i",c,"-vf",vf,
                 "-af","aresample=48000:async=1:first_pts=0,apad","-r","30"]
            cmd+=GPU.enc_args("veryfast"); cmd+=["-c:a","aac","-b:a","192k","-ar","48000","-ac","2"]
            if cd and cd>0.1: cmd+=["-t",f"{cd:.3f}"]
            cmd+=[n]
            subprocess.run(cmd,capture_output=True,timeout=600)
            norm.append(n if os.path.exists(n) else c)
            self._sp(0.05+0.35*(i+1)/len(clips)); self._sss(f"merge 1/5: {i+1}/{len(clips)}")
        if trans_on and len(norm)>1:
            self._ss("Transitions...",C["orange"]); self._sss("merge 2/5: transitions")
            faded=[]
            for ci,clip in enumerate(norm):
                if self._cancelled: return
                if ci>0:
                    fc=os.path.join(TEMP_DIR,f"adv_fade_{ci}.mp4")
                    d=get_duration(clip)
                    if d and d>trans_dur*2:
                        cmd=["ffmpeg","-y","-i",clip,
                            "-vf",f"fade=t=in:st=0:d={trans_dur},fade=t=out:st={d-trans_dur}:d={trans_dur}",
                            "-af",f"afade=t=in:st=0:d={trans_dur},afade=t=out:st={d-trans_dur}:d={trans_dur}"]
                        cmd+=GPU.enc_args("fast"); cmd+=["-c:a","aac",fc]
                        subprocess.run(cmd,capture_output=True,timeout=300)
                        faded.append(fc if os.path.exists(fc) else clip)
                    else: faded.append(clip)
                else: faded.append(clip)
            norm=faded
        self._sp(0.55)
        intro_clips=[]
        if self.intro_enabled_var.get():
            intro_str=self.intro_var.get()
            if intro_str:
                self._ss("Intros...",C["orange"]); self._sss("merge 3/5: intros")
                for ip in intro_str.split(";"):
                    ip=ip.strip()
                    if ip and os.path.exists(ip):
                        io=os.path.join(TEMP_DIR,f"adv_intro_{len(intro_clips)}.mp4")
                        cmd=["ffmpeg","-y","-i",ip,"-vf",
                            f"scale={tw}:{th}:force_original_aspect_ratio=decrease,pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:black,fps=30,format=yuv420p"]
                        cmd+=GPU.enc_args("fast"); cmd+=["-c:a","aac","-ar","48000",io]
                        subprocess.run(cmd,capture_output=True,timeout=300)
                        if os.path.exists(io): intro_clips.append(io)
        all_clips=intro_clips+norm
        self._sp(0.7)
        self._ss("Joining...",C["orange"]); self._sss("merge 4/5: concat")
        lp=os.path.join(TEMP_DIR,"adv_cl.txt")
        with open(lp,"w",encoding="utf-8") as f:
            for c in all_clips: f.write(f"file '{os.path.abspath(c)}'\n")
        merged=os.path.join(TEMP_DIR,"adv_merged.mp4")
        subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-i",lp,"-c","copy","-movflags","+faststart",merged],
            capture_output=True,text=True,timeout=900)
        if not os.path.exists(merged) or get_duration(merged)<0.1:
            cmd=["ffmpeg","-y","-fflags","+genpts","-f","concat","-safe","0","-i",lp,"-vsync","cfr","-r","30"]
            cmd+=GPU.enc_args("veryfast"); cmd+=["-c:a","aac","-b:a","192k","-ar","48000","-ac","2","-movflags","+faststart",merged]
            _run_ff(cmd,timeout=900)
        self._sp(0.85)
        bgm_path=self.bgm_var.get(); final_out=sp
        if self.bgm_enabled_var.get() and bgm_path and os.path.exists(bgm_path):
            self._ss("BGM...",C["orange"]); self._sss("merge 5/5: BGM")
            md=get_duration(merged)
            bgm_vol=self._bgm_vol_val()
            try: bgm_fade=float(self.bgm_fade_var.get() or 2.0)
            except: bgm_fade=2.0
            fs=max(0,md-bgm_fade)
            bgm_out=os.path.join(TEMP_DIR,"adv_bgm_final.mp4")
            if self.bgm_loop_var.get() and bool(getattr(self,"bgm_xfade_var",None) and self.bgm_xfade_var.get()):
                bgm_src=self._make_bgm_xfade_loop(bgm_path, md+1.0, 1.5)   # seamless crossfaded loop
                bgm_in=["-i",bgm_src]
            elif self.bgm_loop_var.get():
                bgm_in=["-stream_loop","-1","-i",bgm_path]
            else:
                bgm_in=["-i",bgm_path]
            subprocess.run(["ffmpeg","-y","-i",merged]+bgm_in+["-filter_complex",
                f"[1:a]volume={bgm_vol},afade=t=in:st=0:d={bgm_fade},afade=t=out:st={fs}:d={bgm_fade}[bgm];"
                f"[0:a][bgm]amix=inputs=2:duration=first:normalize=0[outa]",
                "-map","0:v","-map","[outa]","-c:v","copy","-c:a","aac","-shortest",bgm_out],
                capture_output=True,text=True,timeout=900)
            if os.path.exists(bgm_out): shutil.copy2(bgm_out,final_out)
            else: shutil.copy2(merged,final_out)
        else: shutil.copy2(merged,final_out)
        _finalize_output_resolution(final_out, log=lambda m: self._sss(m))
        self._sp(1.0)
        if os.path.exists(final_out):
            self._ss(f"✓ Saved! ({format_duration(get_duration(final_out))})",C["green"])
        else: self._ss("FAILED!",C["red"])
        for f in norm:
            if f and TEMP_DIR in f and os.path.exists(f):
                try: os.remove(f)
                except: pass


# ════════════════════════════════════════════════════════════════════════════
# SHORTS EDITOR — 9:16 (1080x1920) with optional thumbnail intro
# ════════════════════════════════════════════════════════════════════════════
# Inherits everything from AdvanceEditorFrame (same UI, same features) and only
# overrides the parts that need to behave differently:
#   • Output resolution forced to 9:16 (TARGET_W × TARGET_H)
#   • Optional thumbnail image — if uploaded, shown for first 2 sec of final video
#   • Sidebar adds a "Shorts (9:16) + Thumbnail" section
# Everything else (TTS, blend video/SFX, captions, blend text, logo, BGM,
# transitions, intros, volume mixing) works identically.
# ════════════════════════════════════════════════════════════════════════════
# ════════════════════════════════════════════════════════════════════════════
# VIDEO MASTER EDITOR — Minimal, Ultra-Fast: Master Folder + Voice
# ════════════════════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════════════════
    def _tab_help_title(self): return "Advance Editor"
    def _tab_help_steps(self):
        return ["Enter ElevenLabs API key.","Choose Script&Video or Only Video.","Load voices, pick narration voice.","Add scenes: script + image/video.","Adjust volume, add logo, BGM.","MERGE to render. Pick 1K/2K/4K in header."]


# VIDEO MASTER EDITOR — Advance Editor streamlined + Master Folder + freeze-last-frame
# ════════════════════════════════════════════════════════════════════════════
class VideoMasterEditorFrame(AdvanceEditorFrame):
    """Video Master — Advance Editor made butter-smooth for 10,000+ blocks.

    Full functionality retained:
    - Script → automatic blocks creation (unlimited)
    - ElevenLabs voice fetch + generation
    - Full voiceover + audio mixing
    - Captions (optional)
    - BGM (optional)
    - Logo (optional)
    - Preview + Rendering + Merge

    Master Folder feature:
    - Pick ONE master folder → every image/video inside is mapped to blocks
      sequence-wise (block 1 → 1st media, block 2 → 2nd media, …).
    - If a clip is a VIDEO shorter than its voiceover, the video plays once
      and then FREEZES on its last frame for the rest of the voiceover.
      (e.g. voiceover 15s, video 8s → plays 8s, last frame held for 7s.)

    Removed for maximum speed:
    - Intro Videos section (sidebar)
    - Blend Text section (sidebar)
    - Blend Video + SFX section (sidebar)
    - Trim & Loop (per-block)
    - Per-block volume sliders
    - Per-block TTS volume sliders
    - Per-block Upload/Audio/Gen buttons (use toolbar instead)

    Each block = 1 frame + 3 labels = 4 widgets (was 20+).
    10,000 blocks = 40,000 widgets (manageable) vs 200,000 (crash).
    """

    def __init__(self, master):
        self.PRESET_TOOL_ID = "video_master_editor"
        self._is_jesus = True            # internal flag kept for compatibility
        self._is_video_master = True
        # Short videos extend by freezing their last frame (instead of looping)
        self._freeze_extend_short_video = True
        # Long videos speed up to fit the voiceover (instead of trimming)
        self._speed_fit_long_video = True
        super().__init__(master)
        # After parent builds UI, hide unwanted sidebar sections
        self._hide_jesus_sections()
        # Add the Master Folder button to the toolbar
        self._add_master_folder_button()
        # Add the Whiteboard Animation panel to the sidebar
        self._add_whiteboard_card()

    def _add_master_folder_button(self):
        """Add a '📂 Master Folder' button to the scene-blocks toolbar."""
        tb = getattr(self, "_toolbar_ref", None)
        if tb is None:
            return
        try:
            ctk.CTkButton(
                tb, text="📂 Master Folder",
                fg_color=C["purple"], text_color="#fff",
                width=150, height=32, font=("Segoe UI", 11, "bold"),
                command=self._master_folder_upload
            ).pack(side="left", padx=5, pady=7)
        except Exception:
            pass

    def _add_whiteboard_card(self):
        """Animation & Reveal Effects panel in the Video Master sidebar.
        Supports: Whiteboard Hand Sketch, Rain Drop Reveal, Blood Drop Reveal, Fire Paper Burn, Sparkle."""
        sb = getattr(self, "_sb_ref", None)
        if sb is None:
            return
        try:
            self._wb_on = ctk.BooleanVar(value=bool(self.settings.get("wb_on")))
            self._wb_freeze_var = ctk.DoubleVar(value=float(self.settings.get("wb_freeze") or 2.5))
            self._wb_hand = self.settings.get("wb_hand") or ""
            self._reveal_effect_var = ctk.StringVar(value=self.settings.get("reveal_effect") or "✍️ Whiteboard Hand Sketch")

            card = ctk.CTkFrame(sb, fg_color=C["card"], border_color=C["purple"],
                                border_width=2, corner_radius=8)
            card.grid(row=900, column=0, sticky="ew", padx=6, pady=(4, 6))
            self._wb_card = card

            head = ctk.CTkFrame(card, fg_color="transparent")
            head.pack(fill="x", padx=8, pady=(6, 2))
            ctk.CTkLabel(head, text="✨ REVEAL & ANIMATION",
                         text_color=C["purple"], font=("Segoe UI", 12, "bold")).pack(side="left")
            state = "normal" if HAS_CV2 else "disabled"
            ctk.CTkCheckBox(head, text="Enable", variable=self._wb_on, state=state,
                            text_color=C["green"], fg_color=C["green"],
                            font=("Segoe UI", 11, "bold"), width=20,
                            command=self._wb_toggle).pack(side="right")

            # Reveal Style Selector Dropdown
            sel_fr = ctk.CTkFrame(card, fg_color="transparent")
            sel_fr.pack(fill="x", padx=8, pady=(4, 2))
            ctk.CTkLabel(sel_fr, text="Effect:", text_color=C["text"], font=("Segoe UI", 10, "bold")).pack(side="left")
            
            effect_options = [
                "✍️ Whiteboard Hand Sketch",
                "🌧️ Rain Drop Reveal",
                "🩸 Blood Drop Reveal",
                "🔥 Fire Paper Burn",
                "✨ Sparkle / Shimmer Reveal"
            ]
            self._effect_menu = ctk.CTkOptionMenu(
                sel_fr, values=effect_options, variable=self._reveal_effect_var,
                width=175, height=26, font=("Segoe UI", 10),
                fg_color=C["btn"], button_color=C["purple"], text_color=C["text"],
                command=self._on_effect_style_change
            )
            self._effect_menu.pack(side="right")

            # Dynamic description label
            self._wb_desc_lbl = ctk.CTkLabel(
                card, text="", text_color=C["dim"], font=("Segoe UI", 8),
                justify="left", wraplength=260
            )
            self._wb_desc_lbl.pack(anchor="w", padx=10, pady=(2, 4))

            if not HAS_CV2:
                ctk.CTkLabel(card, text="⚠️ Install 'opencv-python' + 'numpy' to enable.",
                             text_color=C["red"], font=("Segoe UI", 9)
                             ).pack(anchor="w", padx=10, pady=(0, 6))

            # Freeze-tail setting (Applies to all reveal animations)
            fr = ctk.CTkFrame(card, fg_color="transparent"); fr.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(fr, text="Freeze last frame (sec before audio ends):",
                         text_color=C["text"], font=("Segoe UI", 10)).pack(side="left")
            fe = ctk.CTkEntry(fr, textvariable=self._wb_freeze_var, width=50,
                              fg_color=C["entry_bg"], text_color=C["text"],
                              border_color=C["border"])
            fe.pack(side="right")
            fe.bind("<FocusOut>", lambda e: self._wb_save_settings())

            # Optional hand image frame (Only for Whiteboard Hand Sketch)
            self._hand_frame = ctk.CTkFrame(card, fg_color="transparent")
            self._hand_frame.pack(fill="x", padx=10, pady=(4, 2))
            
            hr = ctk.CTkFrame(self._hand_frame, fg_color="transparent"); hr.pack(fill="x")
            ctk.CTkLabel(hr, text="Hand image (optional):", text_color=C["text"],
                         font=("Segoe UI", 10)).pack(side="left")
            ctk.CTkButton(hr, text="✕", width=28, height=26, fg_color=C["btn"],
                          hover_color=C["red"], text_color=C["dim"], font=("Segoe UI", 11),
                          command=self._wb_clear_hand).pack(side="right", padx=(4, 0))
            ctk.CTkButton(hr, text="📎 Choose Hand", width=110, height=26,
                          fg_color=C["btn"], hover_color=C["btn_hov"], text_color=C["text"],
                          font=("Segoe UI", 10), command=self._wb_upload_hand).pack(side="right")

            self._wb_hand_lbl = ctk.CTkLabel(self._hand_frame, text="", text_color=C["green"],
                                             font=("Segoe UI", 9), anchor="w", justify="left")
            self._wb_hand_lbl.pack(fill="x", padx=2, pady=(2, 0))
            self._wb_hand_tip_lbl = ctk.CTkLabel(self._hand_frame,
                         text="Transparent PNG (pen tip top-left). Default built-in hand.",
                         text_color=C["dim"], font=("Segoe UI", 8), justify="left"
                         )
            self._wb_hand_tip_lbl.pack(anchor="w", padx=2, pady=(0, 4))
            
            self._wb_refresh_hand_lbl()
            self._update_effect_ui_mode()
        except Exception as e:
            print(f"[WARN] whiteboard card: {e}")

    def _on_effect_style_change(self, val=None):
        self._update_effect_ui_mode()
        self._wb_save_settings()
        self._wb_toggle()

    def _update_effect_ui_mode(self):
        try:
            eff = self._reveal_effect_var.get() if hasattr(self, "_reveal_effect_var") else "✍️ Whiteboard Hand Sketch"
            if "Whiteboard" in eff:
                desc = "Hand-sketches linework left→right with realistic drawing strokes, then freezes."
                if hasattr(self, "_hand_frame"):
                    self._hand_frame.pack(fill="x", padx=10, pady=(4, 2))
            elif "Rain" in eff:
                desc = "Cascading water droplets & expanding ripple rings splash open to reveal the artwork."
                if hasattr(self, "_hand_frame"):
                    self._hand_frame.pack_forget()
            elif "Blood" in eff:
                desc = "Visceral dripping blood & crimson ink streams flow downward to reveal the frame."
                if hasattr(self, "_hand_frame"):
                    self._hand_frame.pack_forget()
            elif "Fire" in eff or "Paper" in eff:
                desc = "Fiery orange embers incinerate charred vintage parchment outward to uncover the scene."
                if hasattr(self, "_hand_frame"):
                    self._hand_frame.pack_forget()
            elif "Sparkle" in eff:
                desc = "Starry glitter particles & celestial shimmer waves dissolve across the image."
                if hasattr(self, "_hand_frame"):
                    self._hand_frame.pack_forget()
            else:
                desc = "Smooth animated reveal transition."
                if hasattr(self, "_hand_frame"):
                    self._hand_frame.pack_forget()
            if hasattr(self, "_wb_desc_lbl"):
                self._wb_desc_lbl.configure(text=desc)
        except Exception:
            pass

    def _wb_refresh_hand_lbl(self):
        try:
            h = getattr(self, "_wb_hand", "")
            if h and os.path.exists(h):
                self._wb_hand_lbl.configure(text="✓ " + os.path.basename(h), text_color=C["green"])
            else:
                self._wb_hand_lbl.configure(text="(using built-in hand)", text_color=C["dim"])
        except Exception:
            pass

    def _wb_upload_hand(self):
        f = filedialog.askopenfilename(
            title="Select hand image (PNG with transparent background; pen tip top-left)",
            filetypes=[("PNG image", "*.png"), ("Images", "*.png *.jpg *.jpeg *.webp")])
        if f:
            self._wb_hand = f
            self._wb_refresh_hand_lbl()
            self._wb_save_settings()

    def _wb_clear_hand(self):
        self._wb_hand = ""
        self._wb_refresh_hand_lbl()
        self._wb_save_settings()

    def _wb_toggle(self):
        """Enable/disable reveal animations. Clears cached IMAGE-scene outputs so they
        re-render with (or without) the effect on the next Merge Final."""
        self._wb_save_settings()
        try:
            for b in self.blocks:
                if b.get("media_type") == "image":
                    b["output"] = ""
                    for k in ("status_label", "status_lbl"):
                        try:
                            b[k].configure(text="Needs render", text_color=C["dim"]); break
                        except Exception:
                            pass
        except Exception:
            pass

    def _wb_save_settings(self):
        try:
            self.settings.set("wb_on", bool(self._wb_on.get()))
            self.settings.set("wb_freeze", float(self._wb_freeze_var.get()))
            self.settings.set("wb_hand", getattr(self, "_wb_hand", ""))
            if hasattr(self, "_reveal_effect_var"):
                self.settings.set("reveal_effect", self._reveal_effect_var.get())
            self.settings.save()
        except Exception:
            pass

    def _master_folder_upload(self):
        """Pick ONE master folder; take ALL images & videos inside and map them to
        blocks sequence-wise (block 1 → 1st media, block 2 → 2nd media, …).
        Videos shorter than the voiceover will freeze on their last frame at render."""
        if not self.blocks:
            messagebox.showwarning("Blocks", "Create blocks first (Analyze + Create Blocks).")
            return
        folder = filedialog.askdirectory(title="Select MASTER folder (images / videos)")
        if not folder:
            return
        media_exts = tuple(VIDEO_EXTS) + tuple(IMAGE_EXTS)
        files = []
        for root, _dirs, fs in os.walk(folder):
            for f in fs:
                if os.path.splitext(f)[1].lower() in media_exts:
                    files.append(os.path.normpath(os.path.join(root, f)))
        if not files:
            messagebox.showwarning(
                "Master Folder",
                f"No images or videos found in:\n{folder}\n\nSupported: mp4, mov, jpg, png, …")
            return
        files = sort_files(files)  # sequence-wise (Scene_N / natural name order)
        self._ss(f"Master folder: {len(files)} media → mapping sequence-wise…", C["orange"])
        threading.Thread(target=self._master_folder_worker, args=(files,), daemon=True).start()

    def _master_folder_worker(self, files):
        """Background mapper: assign sorted media to blocks positionally, in order."""
        n = min(len(files), len(self.blocks))
        queue = []
        for i in range(n):
            p = files[i]
            b = self.blocks[i]
            is_vid = is_video_file(p)
            b["source_media"] = p
            b["media_type"] = "video" if is_vid else "image"
            b["video"] = p if is_vid else ""
            b["trim_start"] = b["trim_end"] = None
            b["trimmed_loop_path"] = None
            try:
                b["trim_label"].configure(text="No trim")
            except Exception:
                pass
            queue.append((b, p))

        def _flush(start):
            end = min(start + 25, len(queue))
            for j in range(start, end):
                b, p = queue[j]
                try:
                    self._queue_media_load(b, p, status_prefix="Seq")
                except Exception:
                    pass
            if end < len(queue):
                self.after(10, lambda: _flush(end))
            else:
                extra = len(files) - n
                empty = len(self.blocks) - n
                msg = f"✓ Master folder: mapped {n} media sequence-wise"
                if extra > 0:
                    msg += f" · {extra} extra media skipped (more files than blocks)"
                if empty > 0:
                    msg += f" · {empty} blocks still empty (fewer files than blocks)"
                self._ss(msg, C["green"])

        self.after(0, lambda: _flush(0))

    def _hide_jesus_sections(self):
        """Hide Intro, Blend Text, Blend Video, SFX sections + Generate All button.
        Jesus tab uses single-click 'Merge Final' which auto-generates + merges."""
        # Hide Generate All button - Merge Final does everything
        try:
            if hasattr(self, "_gen_all_btn") and self._gen_all_btn:
                self._gen_all_btn.pack_forget()
        except: pass
        
        sb = getattr(self, "_sb_ref", None)
        if sb is None:
            return
        # Walk through sidebar children and hide sections by title
        hide_titles = {"INTRO VIDEOS", "BLEND TEXT", "BLEND VIDEO", "TRANSITION", 
                       "SFX", "SOUND EFFECTS", "BLEND SFX"}
        for child in sb.winfo_children():
            try:
                # Check if this frame contains a label with one of our hide titles
                for sub in child.winfo_children():
                    if isinstance(sub, ctk.CTkLabel):
                        txt = sub.cget("text").upper().replace("█", "").strip()
                        for ht in hide_titles:
                            if ht in txt:
                                child.grid_forget()
                                break
            except:
                pass

    def _make_block(self, num, char, text, video_only=False):
        """Ultra-lightweight blocks — only 4 widgets per block.
        No buttons, no sliders, no volume controls.
        Preview via double-click. All operations via toolbar."""
        ci = self.characters.get(char, {})
        cc = CHAR_COLORS[ci.get("color_idx", 0) % len(CHAR_COLORS)]
        if video_only:
            cc = {"bg": "#1a1a2e", "border": C["dim"], "accent": C["dim"]}

        frame = ctk.CTkFrame(
            self.bkf, fg_color=cc["bg"],
            border_color=cc["border"], border_width=1,
            corner_radius=6, height=36
        )
        frame.pack(fill="x", padx=4, pady=1)
        frame.pack_propagate(False)

        block = {
            "num": num, "text": text, "character": char,
            "color_idx": ci.get("color_idx", 0),
            "source_media": "", "media_type": "", "video": "",
            "output": "", "tts_audio": "", "frame": frame,
            "trim_start": None, "trim_end": None,
            "trimmed_loop_path": None, "loop_mode": "pingpong",
            "video_only": video_only, "clip_volume": 0,
            "tts_volume": 100,
        }

        # ── Single row: #num | character badge | text | status ──
        # Number
        ctk.CTkLabel(
            frame, text=f"#{num}",
            text_color=C["text"],
            font=("Segoe UI", 11, "bold"),
            width=40
        ).pack(side="left", padx=(6, 2))

        # Character badge (compact)
        badge_text = char[:12] if not video_only else "VID"
        ctk.CTkLabel(
            frame, text=badge_text,
            text_color=cc["accent"],
            font=("Segoe UI", 9, "bold"),
            width=70
        ).pack(side="left", padx=2)

        # Text preview (truncated)
        d = text[:60] + "…" if len(text) > 60 else text
        if not d:
            d = "[no text]"
        txt_lbl = ctk.CTkLabel(
            frame, text=d,
            text_color=C["text"],
            font=("Segoe UI", 9),
            anchor="w", justify="left"
        )
        txt_lbl.pack(side="left", fill="x", expand=True, padx=4)

        # File label (hidden by default, used by _queue_media_load)
        # We create a dummy label that's not packed — just for compatibility
        file_lbl = ctk.CTkLabel(frame, text="")
        block["file_label"] = file_lbl  # not packed — saves widget count

        # Trim label (dummy, not packed)
        trim_lbl = ctk.CTkLabel(frame, text="")
        block["trim_label"] = trim_lbl

        # Thumb label (dummy, not packed — thumbnail not shown in compact mode)
        thumb_lbl = ctk.CTkLabel(frame, text="")
        block["thumb_label"] = thumb_lbl

        # Status label (compact, right-aligned)
        st = ctk.CTkLabel(
            frame, text="•",
            text_color=C["orange"],
            font=("Segoe UI", 9),
            width=60
        )
        st.pack(side="right", padx=(2, 6))
        block["status_label"] = st

        # Double-click to preview
        def _on_dblclick(event, idx=len(self.blocks)):
            self._preview_block(idx)
        frame.bind("<Double-Button-1>", _on_dblclick)
        txt_lbl.bind("<Double-Button-1>", _on_dblclick)

        self.blocks.append(block)

    def _create_blocks(self):
        """Create blocks from story text — NO LIMIT, optimized for 10k+."""
        text = self.story_box.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Story", "Paste story.")
            return
        if not self.characters:
            messagebox.showwarning("Characters", "Analyze first.")
            return

        for b in self.blocks:
            try:
                b["frame"].destroy()
            except:
                pass
        self.blocks.clear()

        pat = re.compile(
            r'^([A-Za-z0-9\u0900-\u097F\u0600-\u06FF_\-.\s]{1,50})\s*:\s*(.+)',
            re.MULTILINE
        )
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        self._block_queue = []
        for line in lines:
            m = pat.match(line)
            if m:
                cn, dl = m.group(1).strip(), m.group(2).strip()
                if cn in self.characters and dl:
                    self._block_queue.append((cn, dl))

        total = len(self._block_queue)
        self._ss(f"Creating {total} blocks smoothly…", C["orange"])
        self._block_creation_idx = 0
        self._total_blocks_to_create = total

        # Create ALL blocks in batches of 50 with 10ms delay — butter smooth
        self._jesus_create_batch(0)

    def _jesus_create_batch(self, start_idx):
        """Create blocks in batches of 50 — no threads, pure after() scheduling."""
        BATCH = 50
        end_idx = min(start_idx + BATCH, len(self._block_queue))

        for i in range(start_idx, end_idx):
            cn, dl = self._block_queue[i]
            num = len(self.blocks) + 1
            # Check for Scene_N_ format
            m2 = re.match(r'^scene[_\-\s]*(\d+)', dl, re.IGNORECASE)
            if m2:
                try:
                    num = int(m2.group(1))
                except:
                    pass
            self._make_block(num, cn, dl)

        done = len(self.blocks)
        total = len(self._block_queue)

        if end_idx < total:
            # More to create — schedule next batch
            self._ss(f"Creating blocks {done}/{total}…", C["orange"])
            self._sp(done / max(1, total))
            self.after(10, lambda: self._jesus_create_batch(end_idx))
        else:
            # All done
            self._update_filter()
            self._on_filter("All")
            self._sp(1.0)
            self._ss(f"✓ Created {total} blocks — double-click to preview", C["green"])

    def _queue_media_load(self, block, path, status_prefix="Video"):
        """Override: skip thumbnail extraction for Jesus tab — too heavy for 10k blocks.
        Just update status label with filename."""
        try:
            block["source_media"] = path
            bn = os.path.basename(path)
            block["status_label"].configure(
                text=bn[:15] + "…" if len(bn) > 15 else bn,
                text_color=C["green"]
            )
        except:
            pass

    def _clean_all(self):
        """Override: faster clean for Jesus tab."""
        cnt = clean_temp_files()
        TTSCache.clear_all()
        for b in self.blocks:
            b["output"] = ""
            b["tts_audio"] = ""
            b["trimmed_loop_path"] = None
            try:
                b["status_label"].configure(text="•", text_color=C["orange"])
            except:
                pass
        self._caption_groups.clear()
        self._blend_texts.clear()
        try:
            self.progress.set(0)
        except:
            pass
        self._ss(f"✓ Cleaned {cnt} files. {len(self.blocks)} blocks reset.", C["green"])

    # ═══════════════════════════════════════════════════════════
    # JESUS TAB: One-Click Generate+Merge (no separate Generate All step!)
    # ═════════════════════════════════════════════════════════════
    def _merge(self):
        """Jesus tab: Auto-generate any missing scenes, then merge into final video.
        Single-click workflow - no need to click 'Generate All' separately.
        """
        if not self.blocks: 
            messagebox.showwarning("Merge","No scenes."); return
        self._save_settings()
        
        # Check API key for blocks with text but no audio
        needs_audio = any(b.get("text") and not b.get("video_only") and 
                         not (b.get("tts_audio") and os.path.exists(b.get("tts_audio",""))) 
                         for b in self.blocks)
        if needs_audio:
            ak = self.api_entry.get().strip()
            if not ak:
                messagebox.showwarning("API", "Generate audio first or enter API key.")
                return
        
        # Ask for save location FIRST
        sp = filedialog.asksaveasfilename(
            defaultextension=".mp4",
            initialdir=OUTPUT_DIR,
            filetypes=[("MP4","*.mp4")],
            title="Save Final Video As..."
        )
        if not sp: return
        
        self._cancelled = False
        # Run full workflow in background thread
        threading.Thread(target=self._jesus_full_workflow, args=(sp,), daemon=True).start()
    
    def _jesus_full_workflow(self, save_path):
        """Complete workflow: Generate audio (if needed) → Generate scenes → Merge → Save."""
        
        # ─── Step 0: Generate audio for blocks that need it ───
        audio_needed = [i for i, b in enumerate(self.blocks) 
                       if b.get("text") and not b.get("video_only") 
                       and not (b.get("tts_audio") and os.path.exists(b.get("tts_audio","")))]
        
        if audio_needed:
            self._ss(f"Step 1/3: Generating audio for {len(audio_needed)} blocks...", C["orange"])
            self._sp(0)
            done = 0
            with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_TTS, len(audio_needed))) as ex:
                fm = {ex.submit(self._gen_audio_worker, i): i for i in audio_needed}
                for fut in as_completed(fm):
                    if self._cancelled: 
                        self._ss("Cancelled.", C["red"]); return
                    try: fut.result()
                    except Exception as e: 
                        self._sss(f"Audio error: {str(e)[:50]}")
                    done += 1
                    self._sp(0.3 * done / len(audio_needed))
                    self._ss(f"Audio: {done}/{len(audio_needed)}", C["orange"])
        
        if self._cancelled: return
        
        # ─── Step 1: Generate any missing scene videos ───
        missing = [i for i, b in enumerate(self.blocks) 
                   if not b.get("output") or not os.path.exists(b.get("output",""))]
        
        if missing:
            self._ss(f"Step 2/3: Rendering {len(missing)} scenes...", C["orange"])
            self._sp(0.3)
            
            # Clear captions if disabled (optimization)
            if not self.captions_enabled_var.get():
                self._caption_groups.clear()
            
            done = 0
            with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_FF, len(missing))) as ex:
                fm = {ex.submit(self._gw, i): i for i in missing}
                for fut in as_completed(fm):
                    if self._cancelled: 
                        self._ss("Cancelled.", C["red"]); return
                    try: fut.result()
                    except Exception as e: 
                        self._sss(f"Scene error: {str(e)[:50]}")
                    done += 1
                    self._sp(0.3 + 0.5 * done / len(missing))
                    self._ss(f"Rendered {done}/{len(missing)} scenes", C["orange"])
        else:
            self._sss("All scenes already rendered")
        
        if self._cancelled: return
        
        # ─── Step 2: Collect successful clips ───
        clips = [b["output"] for b in self.blocks 
                 if b.get("output") and os.path.exists(b["output"])]
        
        if not clips:
            self._ss("No scenes rendered successfully! Check logs.", C["red"])
            return
        
        # ─── Step 3: Merge ───
        self._ss(f"Step 3/3: Merging {len(clips)} scenes...", C["orange"])
        self._sp(0.8)
        
        try:
            self._mw(clips, save_path)
        except Exception as e:
            self._ss(f"Merge failed: {str(e)[:50]}", C["red"])
            return
        
        if os.path.exists(save_path):
            self._sp(1.0)
            self._ss(f"✓ Done! Saved: {os.path.basename(save_path)}", C["green"])
            try:
                import auth_manager
                auth_manager.record_video_export(tool_name="Master Video Editor", file_path=save_path)
            except Exception:
                pass
        else:
            self._ss("Save failed!", C["red"])


    def _tab_help_title(self): return "Video Master"
    def _tab_help_steps(self):
        return ["Same as Advance + Whiteboard animation.","Toggle Whiteboard ON for hand-drawn effect.","Set freeze-tail + optional hand cursor."]


# Backward-compatibility alias (old name → new Video Master class)
JesusEditorFrame = VideoMasterEditorFrame


# ════════════════════════════════════════════════════════════════════════════
# STORY VIDEO EDITOR — duplicate of Video Master, NO whiteboard, with
# freeze-frame FX overlays + a PRO caption engine (karaoke / CapCut-style)
# ════════════════════════════════════════════════════════════════════════════
class StoryVideoEditorFrame(VideoMasterEditorFrame):
    """Story Video — same as Video Master (image/video upload, last-frame freeze,
    full voiceover), but WITHOUT whiteboard, PLUS:
      • Overlay EFFECT (snow, bokeh, particles … 20 presets) applied ONLY on the
        frozen last frame (images = whole clip, videos = the freeze tail).
      • Live "Preview Effect" button.
      • PRO captions from each block's script: 20 styles, karaoke realtime word-run,
        AA / Aa / aa caps, colour PICKERS for text / highlight / background,
        text background, system or uploaded font, single line with max words.
      • Preview shows the effect + karaoke captions too.
    """

    def __init__(self, master):
        super().__init__(master)
        try: self.captions_enabled_var.set(False)   # old captions off here
        except Exception: pass
        # Remove the OLD "Captions / Subtitles" section — Story uses the pro engine only.
        try: self._cap_section.grid_remove()
        except Exception: pass
        # Replace the simple (start-only) intro with the per-scene intro system.
        try:
            self.intro_enabled_var.set(False)
            self._intro_section.grid_remove()
        except Exception: pass
        self.intro_entries = []          # [{"path": str, "before_scene": int}]
        self._story_skip_logo = True     # logo is composited AFTER motion (stays static)
        try: self._story_restore_intros()
        except Exception: pass
        self._add_story_intro_section()
        self._story_fontsdir = None
        self._add_story_sections()

    def _add_whiteboard_card(self):   # no whiteboard in Story Video
        return

    # ---------------------------------------------------------------- UI
    def _swatch(self, parent, var, default_hex):
        btn = ctk.CTkButton(parent, text="", width=34, height=26,
                            fg_color=(var.get() or default_hex),
                            hover_color=(var.get() or default_hex), corner_radius=6)
        btn.configure(command=lambda: self._story_pick(var, btn, default_hex))
        return btn

    def _story_pick(self, var, btn, default_hex):
        cur = var.get() or default_hex
        try:
            res = colorchooser.askcolor(color=cur, title="Pick colour")
        except Exception:
            res = (None, None)
        if res and res[1]:
            var.set(res[1])
            try: btn.configure(fg_color=res[1], hover_color=res[1])
            except Exception: pass
            self._story_save()

    def _add_story_sections(self):
        sb = getattr(self, "_sb_ref", None)
        if sb is None: return
        try:
            C_=C
            # ---------- Freeze / Overlay FX ----------
            fxc = ctk.CTkFrame(sb, fg_color=C_["card"], border_color=C_["accent"], border_width=2, corner_radius=8)
            fxc.grid(row=901, column=0, sticky="ew", padx=6, pady=(4,6))
            self._story_fx_card = fxc
            ctk.CTkLabel(fxc, text="✨ FREEZE-FRAME EFFECT", text_color=C_["accent"],
                         font=("Segoe UI",13,"bold")).pack(anchor="w", padx=10, pady=(6,2))
            ctk.CTkLabel(fxc, text="Applied ONLY on the frozen frame (image = whole scene,\nvideo = after it ends).",
                         text_color=C_["dim"], font=("Segoe UI",9), justify="left").pack(anchor="w", padx=10)
            self._story_fx_var = ctk.StringVar(value=self.settings.get("story_fx") or "None")
            rowfx = ctk.CTkFrame(fxc, fg_color="transparent"); rowfx.pack(fill="x", padx=10, pady=(4,8))
            ctk.CTkOptionMenu(rowfx, variable=self._story_fx_var, values=STORY_EFFECTS,
                              fg_color=C_["btn"], button_color=C_["btn_hov"], width=160,
                              command=lambda *_: self._story_save()).pack(side="left")
            ctk.CTkButton(rowfx, text="▶ Preview Effect", width=120, height=28, fg_color=C_["accent"],
                          text_color="#000", font=("Segoe UI",10,"bold"),
                          command=self._story_preview_effect).pack(side="left", padx=6)

            # Freeze MOTION (zoom / pan / shake / rotate) + speed — image only, logo stays static
            ctk.CTkLabel(fxc, text="Freeze motion (after the frame holds) — logo stays static:",
                         text_color=C_["dim"], font=("Segoe UI",9), justify="left").pack(anchor="w", padx=10, pady=(2,0))
            rowm = ctk.CTkFrame(fxc, fg_color="transparent"); rowm.pack(fill="x", padx=10, pady=(2,8))
            self._story_motion_var = ctk.StringVar(value=self.settings.get("story_motion") or "Zoom In-Out")
            ctk.CTkOptionMenu(rowm, variable=self._story_motion_var, values=STORY_MOTIONS,
                              fg_color=C_["btn"], button_color=C_["btn_hov"], width=150,
                              command=lambda *_: self._story_save()).pack(side="left")
            ctk.CTkLabel(rowm, text="Speed", text_color=C_["dim"]).pack(side="left", padx=(8,2))
            self._story_motion_speed = ctk.StringVar(value=str(self.settings.get("story_motion_speed") or 100))
            ctk.CTkOptionMenu(rowm, variable=self._story_motion_speed,
                              values=["50","75","100","150","200","250"],
                              fg_color=C_["btn"], button_color=C_["btn_hov"], width=70,
                              command=lambda *_: self._story_save()).pack(side="left")
            ctk.CTkLabel(rowm, text="%", text_color=C_["dim"]).pack(side="left")

            # ---------- Pro captions ----------
            cc = ctk.CTkFrame(sb, fg_color=C_["card"], border_color=C_["purple"], border_width=2, corner_radius=8)
            cc.grid(row=902, column=0, sticky="ew", padx=6, pady=(0,6))
            self._story_cap_card = cc
            hd = ctk.CTkFrame(cc, fg_color="transparent"); hd.pack(fill="x", padx=10, pady=(6,2))
            ctk.CTkLabel(hd, text="🅰 PRO CAPTIONS (from script)", text_color=C_["purple"],
                         font=("Segoe UI",13,"bold")).pack(side="left")
            self._story_cap_on = ctk.BooleanVar(value=bool(self.settings.get("story_cap_on")))
            ctk.CTkCheckBox(hd, text="On", variable=self._story_cap_on, width=20,
                            text_color=C_["green"], fg_color=C_["green"],
                            command=self._story_save).pack(side="right")

            r1 = ctk.CTkFrame(cc, fg_color="transparent"); r1.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(r1, text="Style:", text_color=C_["text"], width=70, anchor="w").pack(side="left")
            self._story_cap_style = ctk.StringVar(value=self.settings.get("story_cap_style") or "Karaoke Pop")
            ctk.CTkOptionMenu(r1, variable=self._story_cap_style, values=STORY_CAPTION_STYLES,
                              fg_color=C_["btn"], button_color=C_["btn_hov"], width=180,
                              command=lambda *_: self._story_save()).pack(side="right")

            # caption animation mode (how the spoken word is shown)
            self._story_cap_px = float(self.settings.get("story_cap_px") or 0.5)
            self._story_cap_py = float(self.settings.get("story_cap_py") or 0.80)
            rmode = ctk.CTkFrame(cc, fg_color="transparent"); rmode.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(rmode, text="Animation:", text_color=C_["text"], width=70, anchor="w").pack(side="left")
            self._story_cap_mode = ctk.StringVar(value=self.settings.get("story_cap_mode") or "box")
            ctk.CTkOptionMenu(rmode, variable=self._story_cap_mode,
                              values=["box","highlight","pop","word","plain"],
                              fg_color=C_["btn"], button_color=C_["btn_hov"], width=120,
                              command=lambda *_: self._story_save()).pack(side="left")
            ctk.CTkButton(rmode, text="📍 Position (drag & lock)", height=26, fg_color=C_["btn"],
                          hover_color=C_["btn_hov"], text_color=C_["text"], font=("Segoe UI",10),
                          command=self._story_position_picker).pack(side="left", padx=6)

            r2 = ctk.CTkFrame(cc, fg_color="transparent"); r2.pack(fill="x", padx=10, pady=2)
            kar0=self.settings.get("story_cap_karaoke"); kar=True if kar0 in ("",None) else bool(kar0)
            self._story_cap_karaoke = ctk.BooleanVar(value=kar)
            ctk.CTkCheckBox(r2, text="Karaoke (realtime)", variable=self._story_cap_karaoke,
                            text_color=C_["text"], fg_color=C_["purple"], width=20,
                            command=self._story_save).pack(side="left")
            ctk.CTkLabel(r2, text="Max words:", text_color=C_["dim"]).pack(side="left", padx=(12,2))
            self._story_cap_maxwords = ctk.StringVar(value=str(self.settings.get("story_cap_maxwords") or 10))
            ctk.CTkEntry(r2, textvariable=self._story_cap_maxwords, width=44,
                         fg_color=C_["entry_bg"], text_color=C_["text"], border_color=C_["border"]).pack(side="left")

            r3 = ctk.CTkFrame(cc, fg_color="transparent"); r3.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(r3, text="Caps:", text_color=C_["text"], width=70, anchor="w").pack(side="left")
            self._story_cap_caps = ctk.StringVar(value=self.settings.get("story_cap_caps") or "AA")
            ctk.CTkOptionMenu(r3, variable=self._story_cap_caps, values=["AA","Aa","aa"],
                              fg_color=C_["btn"], button_color=C_["btn_hov"], width=80,
                              command=lambda *_: self._story_save()).pack(side="left")
            ctk.CTkLabel(r3, text="Size:", text_color=C_["dim"]).pack(side="left", padx=(10,2))
            self._story_cap_size = ctk.StringVar(value=str(self.settings.get("story_cap_size") or ""))
            ctk.CTkEntry(r3, textvariable=self._story_cap_size, width=50,
                         fg_color=C_["entry_bg"], text_color=C_["text"], border_color=C_["border"]).pack(side="left")

            r4 = ctk.CTkFrame(cc, fg_color="transparent"); r4.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(r4, text="Word colour:", text_color=C_["text"], width=88, anchor="w").pack(side="left")
            self._story_cap_primary = ctk.StringVar(value=self.settings.get("story_cap_primary") or "#FFFFFF")
            self._swatch(r4, self._story_cap_primary, "#FFFFFF").pack(side="left", padx=2)
            ctk.CTkLabel(r4, text="Active box:", text_color=C_["text"]).pack(side="left", padx=(10,2))
            self._story_cap_highlight = ctk.StringVar(value=self.settings.get("story_cap_highlight") or "#7C3AED")
            self._swatch(r4, self._story_cap_highlight, "#7C3AED").pack(side="left", padx=2)
            ctk.CTkLabel(r4, text="Active text:", text_color=C_["text"]).pack(side="left", padx=(10,2))
            self._story_cap_active = ctk.StringVar(value=self.settings.get("story_cap_active") or "#FFFFFF")
            self._swatch(r4, self._story_cap_active, "#FFFFFF").pack(side="left", padx=2)

            r5 = ctk.CTkFrame(cc, fg_color="transparent"); r5.pack(fill="x", padx=10, pady=2)
            self._story_cap_box = ctk.BooleanVar(value=bool(self.settings.get("story_cap_box")))
            ctk.CTkCheckBox(r5, text="Line bg", variable=self._story_cap_box,
                            text_color=C_["text"], fg_color=C_["purple"], width=20,
                            command=self._story_save).pack(side="left")
            self._story_cap_boxcolor = ctk.StringVar(value=self.settings.get("story_cap_boxcolor") or "#000000")
            self._swatch(r5, self._story_cap_boxcolor, "#000000").pack(side="left", padx=6)
            ctk.CTkLabel(r5, text="Bg opacity %:", text_color=C_["dim"]).pack(side="left", padx=(10,2))
            self._story_cap_opacity = ctk.StringVar(value=str(self.settings.get("story_cap_opacity") or 90))
            ctk.CTkEntry(r5, textvariable=self._story_cap_opacity, width=44,
                         fg_color=C_["entry_bg"], text_color=C_["text"], border_color=C_["border"]).pack(side="left")

            r6 = ctk.CTkFrame(cc, fg_color="transparent"); r6.pack(fill="x", padx=10, pady=(2,4))
            ctk.CTkLabel(r6, text="Font:", text_color=C_["text"], width=70, anchor="w").pack(side="left")
            self._story_cap_font = ctk.StringVar(value=self.settings.get("story_cap_font") or "(style default)")
            ctk.CTkOptionMenu(r6, variable=self._story_cap_font,
                              values=["(style default)","Poppins","Anton","Montserrat","Playfair Display",
                                      "DejaVu Sans","Comic Neue","Oswald","Bebas Neue"],
                              fg_color=C_["btn"], button_color=C_["btn_hov"], width=150,
                              command=lambda *_: self._story_save()).pack(side="left")
            ctk.CTkButton(r6, text="📎 Upload", width=80, height=26, fg_color=C_["btn"],
                          hover_color=C_["btn_hov"], text_color=C_["text"], font=("Segoe UI",10),
                          command=self._story_upload_font).pack(side="left", padx=6)

            # ---------- Preview + Apply ----------
            ctk.CTkButton(cc, text="▶ Preview Captions (live style check)", height=30,
                          fg_color=C_["purple"], text_color="#fff", font=("Segoe UI",11,"bold"),
                          command=self._story_preview_captions).pack(fill="x", padx=10, pady=(6,3))
            ctk.CTkButton(cc, text="🔄 Apply & re-render (clear cache)", height=30,
                          fg_color=C_["green"], text_color="#000", font=("Segoe UI",11,"bold"),
                          command=self._story_clear_cache).pack(fill="x", padx=10, pady=(0,8))
            ctk.CTkLabel(cc, text="Active word gets a coloured box (CapCut style). Preview shows the exact\nlook. After changes the cache clears so videos re-render.",
                         text_color=C_["dim"], font=("Segoe UI",8), justify="left").pack(anchor="w", padx=12, pady=(0,8))
        except Exception as e:
            print(f"[WARN] story sections: {e}")

    def _story_upload_font(self):
        f = filedialog.askopenfilename(title="Select a font", filetypes=[("Font","*.ttf *.otf")])
        if not f: return
        try:
            d = os.path.join(TEMP_DIR, "story_fonts"); os.makedirs(d, exist_ok=True)
            dst = os.path.join(d, os.path.basename(f)); shutil.copy2(f, dst)
            self._story_fontsdir = d
            self._story_cap_font.set(os.path.splitext(os.path.basename(f))[0])
            self._story_save()
            self._ss(f"Font added: {os.path.basename(f)}", C["green"])
        except Exception as e:
            messagebox.showerror("Font", str(e))

    def _story_save(self):
        try:
            self.settings.set("story_fx", self._story_fx_var.get())
            if hasattr(self,"_story_motion_var"): self.settings.set("story_motion", self._story_motion_var.get())
            if hasattr(self,"_story_motion_speed"): self.settings.set("story_motion_speed", self._story_motion_speed.get())
            self.settings.set("story_cap_on", bool(self._story_cap_on.get()))
            self.settings.set("story_cap_style", self._story_cap_style.get())
            self.settings.set("story_cap_karaoke", bool(self._story_cap_karaoke.get()))
            self.settings.set("story_cap_maxwords", self._story_cap_maxwords.get())
            self.settings.set("story_cap_caps", self._story_cap_caps.get())
            self.settings.set("story_cap_size", self._story_cap_size.get())
            self.settings.set("story_cap_primary", self._story_cap_primary.get())
            self.settings.set("story_cap_highlight", self._story_cap_highlight.get())
            self.settings.set("story_cap_box", bool(self._story_cap_box.get()))
            self.settings.set("story_cap_boxcolor", self._story_cap_boxcolor.get())
            self.settings.set("story_cap_active", self._story_cap_active.get())
            self.settings.set("story_cap_opacity", self._story_cap_opacity.get())
            if hasattr(self,"_story_cap_mode"): self.settings.set("story_cap_mode", self._story_cap_mode.get())
            self.settings.set("story_cap_px", getattr(self,"_story_cap_px",0.5))
            self.settings.set("story_cap_py", getattr(self,"_story_cap_py",0.80))
            self.settings.set("story_cap_font", self._story_cap_font.get())
            self.settings.save()
        except Exception: pass
        # any change invalidates rendered scenes so the new look is applied
        self._story_invalidate()

    def _story_invalidate(self):
        try:
            for b in self.blocks:
                b["output"] = ""
        except Exception: pass

    def _story_clear_cache(self):
        self._story_save()
        self._story_invalidate()
        try:
            for f in os.listdir(TEMP_DIR):
                if f.startswith(("story_final_","story_fx_","story_cap_","story_capov_","story_intro_a_","_proxy_story_","adv_out_","adv_n_","adv_merged","adv_bgm")):
                    try: os.remove(os.path.join(TEMP_DIR,f))
                    except Exception: pass
        except Exception: pass
        self._ss("Cache cleared — press Merge to re-render with new effect/captions.", C["green"])

    def _story_position_picker(self):
        """Open a 16:9 board, drag the caption where you want it, then Lock — the
        position is saved (as fractions) and used for all caption rendering."""
        try:
            top = ctk.CTkToplevel(self); top.title("Caption position — drag the text, then Lock")
            top.geometry("720x640"); top.configure(fg_color=C["bg"])
            try:
                top.attributes("-topmost", True); top.lift(); top.after(150, top.focus_force)
            except Exception: pass
            ctk.CTkLabel(top, text="Drag the caption to where you want it, then press 🔒 LOCK.",
                         text_color=C["text"], font=("Segoe UI",13,"bold")).pack(pady=(12,4))
            # LOCK button at the TOP too so it is never missed / cut off
            top_lock = ctk.CTkFrame(top, fg_color="transparent"); top_lock.pack()
            CW,CH=640,360
            cv = Canvas(top, width=CW, height=CH, bg="#15171E", highlightthickness=1,
                        highlightbackground=C["border"]); cv.pack(padx=10, pady=8)
            for gx in (CW//3, 2*CW//3): cv.create_line(gx,0,gx,CH, fill="#2A2E38")
            for gy in (CH//3, 2*CH//3): cv.create_line(0,gy,CW,gy, fill="#2A2E38")
            px=float(getattr(self,"_story_cap_px",0.5)); py=float(getattr(self,"_story_cap_py",0.80))
            hl = self._story_cap_highlight.get() or "#7C3AED"
            box = cv.create_rectangle(0,0,0,0, fill=hl, outline="")
            tid = cv.create_text(px*CW, py*CH, text="SAMPLE CAPTION", fill="#FFFFFF",
                                 font=("Arial Black",20,"bold"))
            def rebox():
                bb=cv.bbox(tid)
                if bb: cv.coords(box, bb[0]-8,bb[1]-4,bb[2]+8,bb[3]+4); cv.tag_lower(box, tid)
            rebox()
            def on_drag(e):
                x=max(20,min(CW-20,e.x)); y=max(16,min(CH-16,e.y))
                cv.coords(tid, x, y); rebox()
            cv.bind("<B1-Motion>", on_drag); cv.tag_bind(tid,"<B1-Motion>", on_drag)
            def lock():
                x,y = cv.coords(tid)
                self._story_cap_px = round(max(0.05,min(0.95,x/CW)),3)
                self._story_cap_py = round(max(0.05,min(0.95,y/CH)),3)
                self._story_save()
                self._ss(f"✓ Caption position locked ({self._story_cap_px:.2f}, {self._story_cap_py:.2f})", C["green"])
                top.destroy()
            row=ctk.CTkFrame(top, fg_color="transparent"); row.pack(pady=6)
            ctk.CTkLabel(row, text="Quick:", text_color=C["dim"]).pack(side="left", padx=(0,4))
            for label,fx,fy in [("Bottom",0.5,0.82),("Center",0.5,0.5),("Top",0.5,0.16),
                                 ("Lower-L",0.28,0.82),("Lower-R",0.72,0.82)]:
                ctk.CTkButton(row, text=label, width=72, height=26, fg_color=C["btn"], hover_color=C["btn_hov"],
                              command=lambda fx=fx,fy=fy:(cv.coords(tid,fx*CW,fy*CH),rebox())).pack(side="left",padx=3)
            # BIG lock button (bottom) — guaranteed visible with the taller window
            ctk.CTkButton(top, text="🔒  LOCK POSITION", height=44, fg_color=C["green"], text_color="#000",
                          font=("Segoe UI",14,"bold"), command=lock).pack(fill="x", padx=20, pady=(8,14))
            # mirror lock button at top
            ctk.CTkButton(top_lock, text="🔒 Lock", height=28, width=120, fg_color=C["green"],
                          text_color="#000", font=("Segoe UI",11,"bold"), command=lock).pack()
        except Exception as e:
            messagebox.showerror("Position", str(e))

    def _story_preview_captions(self):
        """Render a short sample with the CURRENT caption style (active-word box,
        karaoke, colours, font) over a neutral background so the user sees the exact
        look in realtime — independent of scenes."""
        opts=self._story_opts(); opts["captions_on"]=True
        sample="Rain fell steady over the quiet workshop tonight"
        self._ss("Rendering caption preview…", C["orange"])
        def work():
            try:
                bg=os.path.join(TEMP_DIR,"_cap_bg.mp4")
                _run_ff(["ffmpeg","-y","-f","lavfi","-i","color=c=0x20232B:s=1920x1080:d=4",
                         "-c:v","libx264","-preset","ultrafast","-pix_fmt","yuv420p","-loglevel","error",bg],timeout=60)
                out=os.path.join(TEMP_DIR,"_cap_preview.mp4")
                # captions only (no scene effect) so the style is crystal-clear
                res=story_apply_fx_captions(bg, out, "None", sample, 4.0, opts, freeze_start=0.0)
                if res and os.path.exists(res):
                    self.after(0, lambda: MiniPlayerWindow(self, res, title_text="Caption style preview", auto_open_external=False))
                    self._ss("Caption preview ready", C["green"])
                else:
                    self._ss("Caption preview failed (check console)", C["red"])
            except Exception as e:
                self._ss(f"Caption preview error: {str(e)[:40]}", C["red"])
        threading.Thread(target=work, daemon=True).start()

    def _story_int(self, v, dflt):
        try: return int(float(v))
        except Exception: return dflt

    def _story_opts(self):
        caps_map = {"AA":"upper","Aa":"title","aa":"lower"}
        font = self._story_cap_font.get().strip()
        if font in ("", "(style default)"): font = None
        return dict(
            captions_on=bool(self._story_cap_on.get()),
            style=self._story_cap_style.get(),
            karaoke=bool(self._story_cap_karaoke.get()),
            caps=caps_map.get(self._story_cap_caps.get(), "upper"),
            size=self._story_int(self._story_cap_size.get(), 0),
            max_words=self._story_int(self._story_cap_maxwords.get(), 6),
            primary=(self._story_cap_primary.get().strip() or None),
            highlight=(self._story_cap_highlight.get().strip() or None),
            active_text=(self._story_cap_active.get().strip() or None),
            box_opacity=self._story_int(self._story_cap_opacity.get(), 90),
            font=font,
            box=bool(self._story_cap_box.get()),
            box_color=(self._story_cap_boxcolor.get().strip() or "#000000"),
            mode=getattr(self,"_story_cap_mode",None).get() if hasattr(self,"_story_cap_mode") else "box",
            pos_x=float(getattr(self,"_story_cap_px",0.5) if not hasattr(self,"_story_cap_px") else self._story_cap_px),
            pos_y=float(getattr(self,"_story_cap_py",0.80) if not hasattr(self,"_story_cap_py") else self._story_cap_py),
            freeze_motion=(self._story_motion_var.get() if hasattr(self,"_story_motion_var") else "Zoom In-Out"),
            freeze_speed=(self._story_int(self._story_motion_speed.get(),100)/100.0 if hasattr(self,"_story_motion_speed") else 1.0),
            fontsdir=getattr(self, "_story_fontsdir", None),
        )

    def _story_freeze_start(self, b, dur):
        """Where the frozen frame begins: images = 0 (whole scene), video = the
        moment the real footage ends (so FX only plays on the held frame)."""
        mp = b.get("source_media","")
        try:
            if mp and os.path.exists(mp) and not is_image_file(mp):
                vd = get_duration(mp)
                if vd and vd < dur-0.05: return float(vd)
                return float(dur)   # footage covers the scene → no frozen frame
        except Exception: pass
        return 0.0

    def _story_preview_effect(self):
        eff = self._story_fx_var.get()
        if not eff or eff == "None":
            messagebox.showinfo("Preview Effect","Choose an effect first."); return
        self._ss(f"Rendering {eff} preview…", C["orange"])
        def work():
            try:
                bg = os.path.join(TEMP_DIR, "_fx_bg.mp4")
                _run_ff(["ffmpeg","-y","-f","lavfi","-i","color=c=0x1A1A22:s=1920x1080:d=4",
                         "-c:v","libx264","-preset","ultrafast","-pix_fmt","yuv420p","-loglevel","error",bg],timeout=60)
                out = os.path.join(TEMP_DIR, "_fx_preview.mp4")
                res = story_apply_fx_captions(bg, out, eff, "", 4.0, {"captions_on":False}, freeze_start=0.0)
                if res and os.path.exists(res):
                    self.after(0, lambda: MiniPlayerWindow(self, res, title_text=f"Effect: {eff}", auto_open_external=False))
                    self._ss("Effect preview ready", C["green"])
                else:
                    self._ss("Effect preview failed", C["red"])
            except Exception as e:
                self._ss(f"Effect preview error: {str(e)[:40]}", C["red"])
        threading.Thread(target=work, daemon=True).start()

    # preview shows the chosen effect + karaoke captions too
    def _preview_post_hook(self, prev_out, b, num, dur):
        try:
            eff = self._story_fx_var.get(); cap_on = bool(self._story_cap_on.get())
        except Exception:
            return prev_out
        try: motion = self._story_motion_var.get()
        except Exception: motion = "Zoom In-Out"
        motion_on = (motion or "").strip().lower() not in ("", "none")
        logo_params = self._story_logo_params()
        if (not eff or eff == "None") and not cap_on and not motion_on and not logo_params:
            return prev_out
        fs = self._story_freeze_start(b, dur)
        out = os.path.join(TEMP_DIR, f"_proxy_story_{num}.mp4")
        try:
            res = story_apply_fx_captions(prev_out, out, eff, b.get("text","") or "", dur,
                                          self._story_opts(), freeze_start=fs, logo=logo_params)
            if res and os.path.exists(res) and get_duration(res) > 0.1:
                return res
        except Exception as e:
            self._sss(f"Story preview FX error: {str(e)[:40]}")
        return prev_out

    # ── Per-scene INTRO videos (Simple-editor style: place intro before scene N) ──
    def _add_story_intro_section(self):
        sb = getattr(self, "_sb_ref", None)
        if sb is None: return
        try:
            C_=C
            ic = ctk.CTkFrame(sb, fg_color=C_["card"], border_color=C_["orange"], border_width=2, corner_radius=8)
            ic.grid(row=900, column=0, sticky="ew", padx=6, pady=(4,6))
            self._story_intro_section_frame = ic
            hd = ctk.CTkFrame(ic, fg_color="transparent"); hd.pack(fill="x", padx=10, pady=(6,2))
            ctk.CTkLabel(hd, text="🎬 INTRO VIDEOS", text_color=C_["orange"],
                         font=("Segoe UI",13,"bold")).pack(side="left")
            iv = self.settings.get("story_intro_on")
            self._story_intro_on = ctk.BooleanVar(value=True if iv=="" else bool(iv))
            ctk.CTkCheckBox(hd, text="On", variable=self._story_intro_on, width=20,
                            text_color=C_["green"], fg_color=C_["green"],
                            command=self._story_save_intros).pack(side="right")
            ctk.CTkLabel(ic, text="Each intro plays BEFORE the chosen scene number.\nBefore Scene 1 = very start of the video.",
                         text_color=C_["dim"], font=("Segoe UI",9), justify="left").pack(anchor="w", padx=10, pady=(0,2))
            ibf=ctk.CTkFrame(ic, fg_color="transparent"); ibf.pack(fill="x", padx=10, pady=3)
            ctk.CTkButton(ibf, text="➕ Add Intro", width=100, fg_color=C_["accent"], text_color="#000",
                          command=self._add_intro).pack(side="left", padx=3)
            ctk.CTkButton(ibf, text="Clear All", width=80, fg_color=C_["red"], text_color="#fff",
                          command=self._clear_intros).pack(side="left", padx=3)
            self.intro_list_frame = ctk.CTkFrame(ic, fg_color="transparent")
            self.intro_list_frame.pack(fill="x", padx=10, pady=(3,8))
            self._refresh_intro_list_ui()
        except Exception as e:
            print("[WARN] story intro section:", e)

    def _story_restore_intros(self):
        raw = self.settings.get("story_intro_videos") or []
        self.intro_entries = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and item.get("path"):
                    try: bs=int(item.get("before_scene",1) or 1)
                    except: bs=1
                    self.intro_entries.append({"path": item["path"], "before_scene": max(1,bs)})

    def _story_save_intros(self):
        try:
            self.settings.set("story_intro_videos",
                [{"path":e["path"],"before_scene":int(e.get("before_scene",1))} for e in self.intro_entries])
            if hasattr(self,"_story_intro_on"):
                self.settings.set("story_intro_on", bool(self._story_intro_on.get()))
            self.settings.save()
        except Exception: pass

    def _add_intro(self):
        ps = filedialog.askopenfilenames(filetypes=[("Video","*.mp4 *.mov *.avi *.mkv *.webm")])
        if not ps: return
        for p in ps: self.intro_entries.append({"path": p, "before_scene": 1})
        self._refresh_intro_list_ui(); self._story_save_intros()

    def _clear_intros(self):
        self.intro_entries.clear(); self._refresh_intro_list_ui(); self._story_save_intros()

    def _remove_intro(self, idx):
        if 0 <= idx < len(self.intro_entries):
            self.intro_entries.pop(idx); self._refresh_intro_list_ui(); self._story_save_intros()

    def _update_intro_before_scene(self, idx, value):
        if 0 <= idx < len(self.intro_entries):
            try: val = max(1, int(value))
            except: val = 1
            self.intro_entries[idx]["before_scene"] = val
            self._story_save_intros()

    def _refresh_intro_list_ui(self):
        if not hasattr(self,"intro_list_frame"): return
        for w in self.intro_list_frame.winfo_children(): w.destroy()
        if not self.intro_entries:
            ctk.CTkLabel(self.intro_list_frame, text="No intros", text_color=C["dim"],
                         font=("Segoe UI",10)).pack(anchor="w"); return
        for i, entry in enumerate(self.intro_entries):
            rf = ctk.CTkFrame(self.intro_list_frame, fg_color=C["btn"], corner_radius=5); rf.pack(fill="x", pady=2)
            fname = os.path.basename(entry.get("path","?"))
            dur = get_duration(entry["path"]) if os.path.exists(entry.get("path","")) else 0
            ctk.CTkLabel(rf, text=f"#{i+1} {fname} ({format_duration(dur)})", text_color=C["text"],
                         font=("Segoe UI",9), wraplength=150, justify="left").pack(side="left", padx=4, pady=2)
            ctk.CTkLabel(rf, text="Before Scene:", text_color=C["dim"], font=("Segoe UI",9)).pack(side="left", padx=(4,2))
            sv = ctk.IntVar(value=entry.get("before_scene",1))
            ctk.CTkEntry(rf, textvariable=sv, width=40, fg_color=C["entry_bg"], text_color=C["text"],
                         border_color=C["border"], font=("Segoe UI",9)).pack(side="left", padx=2)
            cap_i=i
            sv.trace_add("write", lambda *a, idx=cap_i, var=sv: self._update_intro_before_scene(idx, var.get()))
            ctk.CTkButton(rf, text="X", width=24, height=22, fg_color=C["red"], text_color="#fff",
                          font=("Segoe UI",9,"bold"), command=lambda idx=cap_i: self._remove_intro(idx)).pack(side="right", padx=3, pady=2)

    def _story_prep_intro(self, path):
        """Ensure the intro has an audio track (add silence if missing) so it
        normalises and concatenates cleanly alongside the scenes."""
        if not path or not os.path.exists(path): return None
        try:
            pr=subprocess.run(["ffprobe","-v","error","-select_streams","a","-show_entries","stream=index",
                               "-of","csv=p=0",path], capture_output=True, text=True)
            if pr.stdout.strip(): return path     # already has audio
            out=os.path.join(TEMP_DIR, f"story_intro_a_{abs(hash(path))%99999}.mp4")
            _run_ff(["ffmpeg","-y","-i",path,"-f","lavfi","-i","anullsrc=r=48000:cl=stereo",
                     "-map","0:v","-map","1:a","-shortest","-c:v","copy","-c:a","aac","-loglevel","error",out],
                    timeout=300)
            return out if (os.path.exists(out) and get_duration(out)>0.1) else path
        except Exception:
            return path

    def _story_build_clips_with_intros(self, scene_clips):
        """Interleave intro videos into the scene clip list at their before_scene
        positions (Simple-editor style)."""
        on = bool(getattr(self,"_story_intro_on",None) and self._story_intro_on.get())
        intro_map={}
        if on:
            for e in self.intro_entries:
                p=e.get("path","")
                if p and os.path.exists(p):
                    try: bs=max(1,int(e.get("before_scene",1)))
                    except: bs=1
                    intro_map.setdefault(bs,[]).append(p)
        if not intro_map:
            return scene_clips
        ordered=[]; total=len(self.blocks)
        for i,b in enumerate(self.blocks):
            scene_num=i+1
            for ip in intro_map.get(scene_num,[]):
                pi=self._story_prep_intro(ip)
                if pi: ordered.append(pi)
            op=b.get("output","")
            if op and os.path.exists(op):
                ordered.append(op)
        for bs,paths in intro_map.items():
            if bs>total:
                for ip in paths:
                    pi=self._story_prep_intro(ip)
                    if pi: ordered.append(pi)
        return ordered or scene_clips

    def _mw(self, clips, sp):
        # inject intros before their target scenes, then run the normal merge
        try:
            clips = self._story_build_clips_with_intros(clips)
        except Exception as e:
            print("[STORY] intro interleave error:", e)
        super()._mw(clips, sp)

    # render: add FX (frozen frame) + pro captions + static logo onto each scene
    def _gw(self, idx):
        super()._gw(idx)
        if idx < 0 or idx >= len(self.blocks): return
        b = self.blocks[idx]
        op = b.get("output", "")
        if not op or not os.path.exists(op): return
        try:
            eff = self._story_fx_var.get(); cap_on = bool(self._story_cap_on.get())
        except Exception:
            return
        try: motion = self._story_motion_var.get()
        except Exception: motion = "Zoom In-Out"
        motion_on = (motion or "").strip().lower() not in ("", "none")
        logo_params = self._story_logo_params()
        has_logo = bool(logo_params)
        if (not eff or eff == "None") and not cap_on and not motion_on and not has_logo:
            return
        dur = get_duration(op)
        if dur <= 0.1: return
        fs = self._story_freeze_start(b, dur)
        out = os.path.join(TEMP_DIR, f"story_final_{b['num']}.mp4")
        try:
            res = story_apply_fx_captions(op, out, eff, b.get("text","") or "", dur,
                                          self._story_opts(), freeze_start=fs, logo=logo_params)
            if res and os.path.exists(res) and get_duration(res) > 0.1:
                b["output"] = res
        except Exception as e:
            self._sss(f"Story FX/caption error: {str(e)[:50]}")

    def _story_logo_params(self, W=1920, H=1080):
        """Compute the STATIC logo placement (path, size, position, opacity) for a
        1920x1080 frame — same geometry as the preview — so the logo can be overlaid
        after the motion effect without stretching."""
        try:
            if not self.logo_enabled_var.get(): return None
            logo_p=self.logo_path_var.get()
            if not (logo_p and os.path.exists(logo_p)): return None
            eff=logo_p
            try:
                if (getattr(self,"logo_cropped_pil",None) is not None and
                        getattr(self,"_logo_cropped_for_path",None)==logo_p):
                    ctp=os.path.join(TEMP_DIR,"_story_logo.png"); self.logo_cropped_pil.save(ctp); eff=ctp
                else:
                    ctp=os.path.join(TEMP_DIR,"_story_logo.png")
                    Image.open(logo_p).convert("RGBA").save(ctp); eff=ctp
            except Exception: eff=logo_p
            pct_x=getattr(self,"_logo_pct_x",None); pct_y=getattr(self,"_logo_pct_y",None)
            pct_size=getattr(self,"_logo_pct_size",None)
            if pct_size and pct_size>0: lw=max(8,int(round(W*pct_size)))
            else:
                try: lw=max(8,int(self.logo_size_var.get() or 140))
                except Exception: lw=140
            lh=lw
            if pct_x is not None and pct_y is not None:
                lx=int(round(W*pct_x)); ly=int(round(H*pct_y))
            else:
                try: lx=int(self.logo_pos_x_var.get() or 20); ly=int(self.logo_pos_y_var.get() or 20)
                except Exception: lx,ly=20,20
            lx=max(0,min(lx,W-lw)); ly=max(0,min(ly,H-lh))
            try: opa=float(self.logo_opacity_var.get() or 100)/100.0
            except Exception: opa=1.0
            return dict(path=eff,w=lw,h=lh,x=lx,y=ly,opa=max(0.0,min(1.0,opa)))
        except Exception as e:
            print("[STORY] logo params:", e); return None


    def _tab_help_title(self): return "Story Video"
    def _tab_help_steps(self):
        return ["Same as Video Master + effects/captions/motion.","EFFECTS: Snow/Bokeh/Sparkle on freeze-frame.","CAPTIONS: style, karaoke, colours, font, position.","MOTION: Zoom/Pan/Shake/Rotate on freeze-tail.","LOGO + INTRO optional."]


# Story Video keys for SettingsManager defaults are added at runtime (get() returns "" if absent)



class ShortsEditorFrame(AdvanceEditorFrame):
    """Shorts Editor — same as Advance Editor but locked to 9:16 with optional
    2-second thumbnail intro prepended at render time."""

    # Target output dimensions for Shorts (9:16 vertical)
    TARGET_W = 1080
    TARGET_H = 1920

    def __init__(self, master):
        self.PRESET_TOOL_ID = "shorts_editor"
        # Initialise shorts-specific state BEFORE super().__init__ runs, because
        # the parent's __init__ calls _build_ui() which we extend.
        self._shorts_init_done = False
        super().__init__(master)
        # Inject the Shorts thumbnail section into the sidebar
        self._add_shorts_section()
        self._shorts_init_done = True

    def _add_shorts_section(self):
        """Add a 'Shorts (9:16) + Thumbnail' section to the existing sidebar.
        We piggyback on the sidebar frame that AdvanceEditorFrame._build_ui created."""
        # Find sidebar — AdvanceEditorFrame stores scrollable sidebar children under self._sb_ref if available;
        # otherwise locate it heuristically from the grid.
        sb = getattr(self, "_sb_ref", None)
        if sb is None:
            # Heuristic: the sidebar is the first column-0 widget that is a scrollable frame
            for child in self.winfo_children():
                try:
                    if isinstance(child, ctk.CTkScrollableFrame):
                        sb = child; break
                except: pass
        if sb is None:
            # Fallback — make it a top-level frame so the user can still see it
            sb = ctk.CTkFrame(self, fg_color=C["card"])
            sb.grid(row=0, column=0, sticky="ns", padx=4, pady=4)

        # Init thumbnail state
        self.shorts_thumb_enabled_var = ctk.BooleanVar(
            value=self.settings.get("shorts_thumbnail_enabled"))
        self.shorts_thumb_path_var = ctk.StringVar(
            value=self.settings.get("shorts_thumbnail_path"))
        self.shorts_thumb_dur_var = ctk.DoubleVar(
            value=float(self.settings.get("shorts_thumbnail_duration")))

        # Use the same section helper visual style as the rest of the sidebar
        def _sec(parent, title, accent=C["accent"]):
            f = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=8)
            ctk.CTkLabel(f, text=f"▸ {title}",
                text_color=accent, font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=8, pady=(6, 2))
            return f

        # Find an empty grid row at the bottom of the sidebar.
        # CTk grids don't expose the next free row reliably; we just inspect existing rows.
        used_rows = set()
        for child in sb.winfo_children():
            try:
                gi = child.grid_info()
                if gi: used_rows.add(int(gi.get("row", 0)))
            except: pass
        bottom_row = (max(used_rows) + 1) if used_rows else 0
        sec = _sec(sb, "Shorts (9:16) + Thumbnail", C["orange"])
        sec.grid(row=bottom_row, column=0, sticky="ew", padx=6, pady=4)
        ctk.CTkLabel(sec,
            text=f"Output locked to {self.TARGET_W}×{self.TARGET_H} (9:16).",
            text_color=C["dim"], font=("Segoe UI", 9)
        ).pack(anchor="w", padx=10, pady=(0, 2))
        ctk.CTkCheckBox(sec, text="Show thumbnail for first N seconds",
            variable=self.shorts_thumb_enabled_var, text_color=C["text"],
            fg_color=C["orange"]).pack(anchor="w", padx=8, pady=3)
        # Upload row
        thb1 = ctk.CTkFrame(sec, fg_color="transparent"); thb1.pack(fill="x", padx=5, pady=3)
        ctk.CTkButton(thb1, text="🖼 Upload Thumbnail", width=160, height=26,
            fg_color=C["orange"], text_color="#000",
            font=("Segoe UI", 10, "bold"),
            command=self._sel_shorts_thumbnail).pack(side="left", padx=2)
        ctk.CTkButton(thb1, text="✕ Clear", width=60, height=26,
            fg_color=C["btn"], text_color=C["red"], font=("Segoe UI", 9),
            command=self._clear_shorts_thumbnail).pack(side="left", padx=2)
        self.shorts_thumb_lbl = ctk.CTkLabel(sec,
            text=os.path.basename(self.shorts_thumb_path_var.get()) or "(no thumbnail)",
            text_color=C["dim"], font=("Segoe UI", 9))
        self.shorts_thumb_lbl.pack(anchor="w", padx=8, pady=(0, 2))
        # Duration
        thb2 = ctk.CTkFrame(sec, fg_color="transparent"); thb2.pack(fill="x", padx=5, pady=(2, 6))
        ctk.CTkLabel(thb2, text="Show for (sec):", text_color=C["dim"]).pack(side="left")
        ctk.CTkEntry(thb2, textvariable=self.shorts_thumb_dur_var, width=55,
            fg_color=C["entry_bg"], text_color=C["text"],
            border_color=C["border"]).pack(side="left", padx=4)
        ctk.CTkLabel(thb2, text="(default 2.0)",
            text_color=C["dim"], font=("Segoe UI", 8)).pack(side="left", padx=4)

    def _sel_shorts_thumbnail(self):
        p = filedialog.askopenfilename(
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp")])
        if not p: return
        self.shorts_thumb_path_var.set(p)
        self.shorts_thumb_enabled_var.set(True)
        try: self.shorts_thumb_lbl.configure(text=os.path.basename(p))
        except: pass
        self._ss(f"Shorts thumbnail set: {os.path.basename(p)}", C["green"])

    def _clear_shorts_thumbnail(self):
        self.shorts_thumb_path_var.set("")
        self.shorts_thumb_enabled_var.set(False)
        try: self.shorts_thumb_lbl.configure(text="(no thumbnail)")
        except: pass
        self._ss("Shorts thumbnail cleared", C["dim"])

    def _save_settings(self):
        """Persist parent settings PLUS shorts-specific keys."""
        super()._save_settings()
        try:
            if hasattr(self, "shorts_thumb_enabled_var"):
                self.settings.set("shorts_thumbnail_enabled", self.shorts_thumb_enabled_var.get())
            if hasattr(self, "shorts_thumb_path_var"):
                self.settings.set("shorts_thumbnail_path", self.shorts_thumb_path_var.get())
            if hasattr(self, "shorts_thumb_dur_var"):
                self.settings.set("shorts_thumbnail_duration",
                    float(self.shorts_thumb_dur_var.get() or 2.0))
            self.settings.save()
        except: pass

    # ── 9:16 conversion of a single scene's rendered output ────────────────
    def _convert_to_vertical(self, in_path, out_path):
        """Take a horizontal/odd-aspect clip and produce a 9:16 (TARGET_W × TARGET_H) version
        with the source scaled to fit and letterboxed in black. Audio is preserved."""
        tw, th = self.TARGET_W, self.TARGET_H
        vf = (f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
              f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:black,fps=30,format=yuv420p,setsar=1")
        has_aud = has_audio_stream(in_path)
        cmd = ["ffmpeg", "-y", "-i", in_path, "-vf", vf]
        cmd += GPU.enc_args("fast")
        if has_aud:
            cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
        else:
            cmd += ["-an"]
        cmd += [out_path]
        _run_ff(cmd, timeout=600)
        return os.path.exists(out_path) and get_duration(out_path) > 0.1

    def _gw(self, idx):
        """Render a single scene normally, then convert the result to 9:16."""
        # Run the parent's full render pipeline first
        super()._gw(idx)
        # Now ensure the produced output is 9:16
        if idx < 0 or idx >= len(self.blocks): return
        b = self.blocks[idx]; num = b["num"]
        op = b.get("output", "")
        if not op or not os.path.exists(op): return
        try:
            vw, vh = get_resolution(op)
            if vw == self.TARGET_W and vh == self.TARGET_H:
                return  # already vertical
        except: pass
        # Convert
        self._sss(f"[#{num}] converting to 9:16 ({self.TARGET_W}×{self.TARGET_H})")
        vert_op = os.path.join(TEMP_DIR, f"shorts_v_{num}.mp4")
        if self._convert_to_vertical(op, vert_op):
            b["output"] = vert_op
            self._block_status(b, f"✓ 9:16 ({format_duration(get_duration(vert_op))})", C["green"])

    # ── Build a 2-second thumbnail clip in 9:16 with audio silence ─────────
    def _build_thumbnail_clip(self, image_path, duration, out_path):
        """Create a clip from the thumbnail image: 9:16, silent audio, of the given duration.
        Audio is included so concat with audio-bearing clips stays in sync."""
        tw, th = self.TARGET_W, self.TARGET_H
        vf = (f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
              f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30,format=yuv420p")
        # Use lavfi anullsrc for a silent audio track, image2 for the still
        cmd = ["ffmpeg", "-y",
               "-loop", "1", "-t", f"{duration:.3f}", "-i", image_path,
               "-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
               "-vf", vf, "-r", "30"]
        cmd += GPU.enc_args("fast")
        cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                "-shortest", out_path]
        _run_ff(cmd, timeout=180)
        return os.path.exists(out_path) and get_duration(out_path) > 0.1

    # ── Merge: same as parent but inject 9:16 enforcement + thumbnail intro ─
    def _mw(self, clips, sp):
        """Override merge to:
        1. Force all clips into 9:16 before normalize
        2. Prepend a 2-second thumbnail clip if enabled and a thumbnail is set"""
        # Step A: ensure all scene clips are 9:16 — _gw should have done this but
        # be defensive (user may have generated some clips in another tab first).
        fixed_clips = []
        for i, c in enumerate(clips):
            try:
                vw, vh = get_resolution(c)
                if vw == self.TARGET_W and vh == self.TARGET_H:
                    fixed_clips.append(c); continue
            except: pass
            vert = os.path.join(TEMP_DIR, f"shorts_pre_v_{i}.mp4")
            if self._convert_to_vertical(c, vert):
                fixed_clips.append(vert)
            else:
                fixed_clips.append(c)  # last-resort fallback

        # Step B: prepend the thumbnail clip if enabled
        thumb_clip = None
        if (hasattr(self, "shorts_thumb_enabled_var")
                and self.shorts_thumb_enabled_var.get()):
            tp = self.shorts_thumb_path_var.get()
            if tp and os.path.exists(tp):
                try: dur = float(self.shorts_thumb_dur_var.get() or 2.0)
                except: dur = 2.0
                dur = max(0.3, min(10.0, dur))
                self._ss("Building thumbnail intro...", C["orange"])
                self._sss(f"shorts: thumbnail clip {dur:.1f}s")
                thumb_out = os.path.join(TEMP_DIR, "shorts_thumb_intro.mp4")
                if self._build_thumbnail_clip(tp, dur, thumb_out):
                    thumb_clip = thumb_out

        if thumb_clip:
            fixed_clips = [thumb_clip] + fixed_clips

        # Now hand off to the parent merge with the prepared clip list
        super()._mw(fixed_clips, sp)

    def _tab_help_title(self): return "Shorts (9:16)"
    def _tab_help_steps(self):
        return ["Same as Advance but 9:16 vertical output.","Optional 2s thumbnail intro."]


class SimpleEditorFrame(ctk.CTkFrame):
    """Simple Editor — AI Video Generator (converted from standalone app)."""
    def __init__(self, master):
        super().__init__(master, fg_color=C["bg"])
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.settings = SettingsManager.load()

        self.blocks = []; self.models = []; self.voices = []
        self.voice_list_full = []
        self.intro_entries = []  # list of {"path": str, "before_scene": int}
        self._restore_intro_entries_from_settings()
        self.logo_pil = None
        self.logo_processed_path = os.path.join(TEMP_DIR,"logo_processed.png")
        self.filler_path = self.settings.get("filler_video","")
        self.bgm_path = self.settings.get("bgm_path","")
        self.bgm_multi_entries = []  # list of {"path":str, "from":int, "to":int}

        self._progress_lock = threading.Lock()

        self._build_ui()
        self._restore_settings()

    def _restore_intro_entries_from_settings(self):
        raw = self.settings.get("intro_videos", [])
        self.intro_entries = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    self.intro_entries.append(item)
                elif isinstance(item, str) and item:
                    self.intro_entries.append({"path": item, "before_scene": 1})

    # ── Thread-safe progress / status updaters ──
    def _set_progress(self, frac):
        frac = max(0.0, min(1.0, float(frac)))
        self.after(0, lambda: self.progress.set(frac))

    def _set_status(self, text, color=None):
        def _do():
            self.status_lbl.configure(text=text, text_color=color or C["dim"])
        self.after(0, _do)

    def _set_substatus(self, text):
        def _do():
            self.sub_status_lbl.configure(text=text)
        self.after(0, _do)

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sb = ctk.CTkScrollableFrame(self, width=340, fg_color=C["card"], corner_radius=0)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_columnconfigure(0, weight=1)

        right = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        row = 0

        # ══════ AUDIO SOURCE SECTION ══════
        audio_src = self._card(sb, "Audio Source")
        audio_src.grid(row=row, column=0, sticky="ew", padx=6, pady=(6,4)); row+=1

        self.audio_source_var = ctk.StringVar(value=self.settings.get("audio_source","elevenlabs"))
        src_frame = ctk.CTkFrame(audio_src, fg_color="transparent")
        src_frame.pack(fill="x", padx=5, pady=3)
        ctk.CTkRadioButton(src_frame, text="ElevenLabs TTS", variable=self.audio_source_var,
            value="elevenlabs", text_color=C["text"], fg_color=C["accent"],
            command=self._on_audio_source_change).pack(side="left", padx=5)
        ctk.CTkRadioButton(src_frame, text="Bulk Audio Upload", variable=self.audio_source_var,
            value="bulk_upload", text_color=C["text"], fg_color=C["accent"],
            command=self._on_audio_source_change).pack(side="left", padx=5)

        # ── ElevenLabs sub-panel ──
        self.elevenlabs_panel = ctk.CTkFrame(audio_src, fg_color="transparent")
        self.elevenlabs_panel.pack(fill="x", padx=0, pady=0)

        kf=ctk.CTkFrame(self.elevenlabs_panel,fg_color="transparent"); kf.pack(fill="x",padx=5,pady=3)
        ctk.CTkLabel(kf,text="Key:",text_color=C["dim"],width=35).pack(side="left")
        self.api_entry=ctk.CTkEntry(kf,show="*",fg_color=C["entry_bg"],text_color=C["text"],placeholder_text="Enter API Key (Optional)...",
            border_color=C["border"]); self.api_entry.pack(side="left",fill="x",expand=True,padx=5)
        self.eye_btn=ctk.CTkButton(kf,text="👁",width=30,fg_color=C["btn"],
            command=self._toggle_key); self.eye_btn.pack(side="left")
        bf=ctk.CTkFrame(self.elevenlabs_panel,fg_color="transparent"); bf.pack(fill="x",padx=5,pady=3)
        ctk.CTkButton(bf,text="Fetch Models",width=95,fg_color=C["accent"],text_color="#000",
            command=self._fetch_models).pack(side="left",padx=3)
        ctk.CTkButton(bf,text="Fetch Voices",width=95,fg_color=C["accent"],text_color="#000",
            command=self._fetch_voices).pack(side="left",padx=3)
        mf=ctk.CTkFrame(self.elevenlabs_panel,fg_color="transparent"); mf.pack(fill="x",padx=5,pady=3)
        ctk.CTkLabel(mf,text="Model:",text_color=C["dim"],width=50).pack(side="left")
        self.model_var=ctk.StringVar()
        self.model_menu=ctk.CTkOptionMenu(mf,variable=self.model_var,fg_color=C["btn"],
            text_color=C["text"],values=["(fetch first)"])
        self.model_menu.pack(side="left",fill="x",expand=True,padx=5)
        vf=ctk.CTkFrame(self.elevenlabs_panel,fg_color="transparent"); vf.pack(fill="x",padx=5,pady=3)
        ctk.CTkLabel(vf,text="Voice:",text_color=C["dim"],width=50).pack(side="left")
        self.voice_search=ctk.CTkEntry(vf,placeholder_text="Search…",fg_color=C["entry_bg"],
            text_color=C["text"],border_color=C["border"],width=85)
        self.voice_search.pack(side="left",padx=3)
        self.voice_search.bind("<KeyRelease>",self._filter_voices)
        self.voice_var=ctk.StringVar()
        self.voice_menu=ctk.CTkOptionMenu(vf,variable=self.voice_var,fg_color=C["btn"],
            text_color=C["text"],values=["(fetch first)"])
        self.voice_menu.pack(side="left",fill="x",expand=True,padx=3)

        # ── Bulk Audio Upload sub-panel ──
        self.bulk_audio_panel = ctk.CTkFrame(audio_src, fg_color="transparent")
        # Initially hidden; toggled by radio

        baf = ctk.CTkFrame(self.bulk_audio_panel, fg_color="transparent")
        baf.pack(fill="x", padx=5, pady=3)
        ctk.CTkButton(baf, text="Upload Audio Files", width=130, fg_color=C["accent"],
            text_color="#000", command=self._bulk_upload_audio_files).pack(side="left", padx=3)
        ctk.CTkButton(baf, text="Upload Audio Folder", width=135, fg_color=C["accent"],
            text_color="#000", command=self._bulk_upload_audio_folder).pack(side="left", padx=3)
        ctk.CTkLabel(self.bulk_audio_panel,
            text="Format: Scene_1_.mp3, Scene_2_.mp3, …\nAuto-maps by scene number in filename",
            text_color=C["dim"], font=("Segoe UI", 10), justify="left").pack(anchor="w", padx=5, pady=3)
        self.bulk_audio_lbl = ctk.CTkLabel(self.bulk_audio_panel, text="No audio uploaded",
            text_color=C["dim"], font=("Segoe UI", 10), wraplength=300, justify="left")
        self.bulk_audio_lbl.pack(anchor="w", padx=5, pady=3)

        # ── TEXT ──
        txt=self._card(sb,"Script Text")
        txt.grid(row=row,column=0,sticky="ew",padx=6,pady=4); row+=1
        ctk.CTkLabel(txt,text="One scene per line (or Scene_N: text)",
            text_color=C["dim"],font=("Segoe UI",10)).pack(anchor="w",padx=5)
        self.text_box=ctk.CTkTextbox(txt,height=95,fg_color=C["entry_bg"],text_color=C["text"],
            border_color=C["border"],border_width=1,font=("Consolas",11))
        self.text_box.pack(fill="x",padx=5,pady=5)
        sf=ctk.CTkFrame(txt,fg_color="transparent"); sf.pack(fill="x",padx=5,pady=3)
        ctk.CTkLabel(sf,text="Silence pad (s):",text_color=C["dim"]).pack(side="left")
        self.silence_var=ctk.DoubleVar(value=0.0)
        ctk.CTkEntry(sf,textvariable=self.silence_var,width=50,fg_color=C["entry_bg"],
            text_color=C["text"],border_color=C["border"]).pack(side="left",padx=5)
        ctk.CTkButton(txt,text="Create Scene Blocks",fg_color=C["green"],text_color="#000",
            command=self._create_blocks_from_text).pack(fill="x",padx=5,pady=(5,2))
        ctk.CTkButton(txt,text="➕ Add Next Scenes (Append)",fg_color=C["orange"],text_color="#000",
            font=("Segoe UI",11,"bold"),
            command=self._append_blocks_from_text).pack(fill="x",padx=5,pady=(2,5))

        # ── AUTO CROP SETTINGS ──
        crop_sec = self._card(sb, "Auto Crop (Upload)")
        crop_sec.grid(row=row, column=0, sticky="ew", padx=6, pady=4); row += 1

        self.auto_crop_var = ctk.BooleanVar(value=self.settings.get("auto_crop_enabled", True))
        ctk.CTkCheckBox(crop_sec, text="Auto-crop uploaded videos → 16:9",
            variable=self.auto_crop_var, text_color=C["text"],
            fg_color=C["accent"]).pack(anchor="w", padx=5, pady=3)

        cr_f = ctk.CTkFrame(crop_sec, fg_color="transparent")
        cr_f.pack(fill="x", padx=5, pady=3)
        ctk.CTkLabel(cr_f, text="Right:", text_color=C["dim"]).pack(side="left")
        self.crop_right_var = ctk.IntVar(value=self.settings.get("crop_right_px", 151))
        ctk.CTkEntry(cr_f, textvariable=self.crop_right_var, width=55,
            fg_color=C["entry_bg"], text_color=C["text"], border_color=C["border"]).pack(side="left", padx=4)
        ctk.CTkLabel(cr_f, text="Bottom:", text_color=C["dim"]).pack(side="left", padx=(8,0))
        self.crop_bottom_var = ctk.IntVar(value=self.settings.get("crop_bottom_px", 151))
        ctk.CTkEntry(cr_f, textvariable=self.crop_bottom_var, width=55,
            fg_color=C["entry_bg"], text_color=C["text"], border_color=C["border"]).pack(side="left", padx=4)

        ctk.CTkLabel(crop_sec,
            text="≈ 4cm at 96 DPI = 151px | Crop is applied only at final merge",
            text_color=C["dim"], font=("Segoe UI", 10)).pack(anchor="w", padx=5, pady=(0,4))

        pr_f = ctk.CTkFrame(crop_sec, fg_color="transparent")
        pr_f.pack(fill="x", padx=5, pady=(0,5))
        for label, rpx, bpx in [("~2cm",76,76), ("~4cm",151,151), ("~6cm",227,227),
                                  ("720p",100,100), ("4K",302,302)]:
            ctk.CTkButton(pr_f, text=label, width=52, height=22, fg_color=C["btn"],
                hover_color=C["accent"], text_color=C["text"], font=("Segoe UI",9),
                command=lambda r=rpx,b=bpx: self._set_crop_preset(r,b)
            ).pack(side="left", padx=2)
        ctk.CTkButton(pr_f, text="Preview", width=70, height=22, fg_color=C["orange"],
            text_color="#000", font=("Segoe UI",9), command=self._preview_crop).pack(side="right", padx=2)

        # ── INTRO (with USE checkbox + before scene N) ──
        intro=self._card_with_checkbox(sb,"Intro Videos","use_intro")
        intro.grid(row=row,column=0,sticky="ew",padx=6,pady=4); row+=1
        ctk.CTkLabel(intro,
            text="Each intro plays BEFORE a chosen scene number.\nBefore Scene 1 = very start.",
            text_color=C["dim"], font=("Segoe UI", 9), justify="left").pack(anchor="w", padx=5, pady=(0,2))
        ibf=ctk.CTkFrame(intro,fg_color="transparent"); ibf.pack(fill="x",padx=5,pady=3)
        ctk.CTkButton(ibf,text="Add Intro",width=85,fg_color=C["accent"],text_color="#000",
            command=self._add_intro).pack(side="left",padx=3)
        ctk.CTkButton(ibf,text="Clear All",width=85,fg_color=C["red"],text_color="#fff",
            command=self._clear_intros).pack(side="left",padx=3)
        self.intro_list_frame = ctk.CTkFrame(intro, fg_color="transparent")
        self.intro_list_frame.pack(fill="x", padx=5, pady=3)
        self.intro_no_lbl = ctk.CTkLabel(self.intro_list_frame, text="No intros",
            text_color=C["dim"], font=("Segoe UI",10))
        self.intro_no_lbl.pack(anchor="w")

        # ── BGM (with USE checkbox + single/multiple mode) ──
        bgm=self._card_with_checkbox(sb,"Background Music","use_bgm")
        bgm.grid(row=row,column=0,sticky="ew",padx=6,pady=4); row+=1

        bgm_mode_f = ctk.CTkFrame(bgm, fg_color="transparent")
        bgm_mode_f.pack(fill="x", padx=5, pady=3)
        self.bgm_mode_var = ctk.StringVar(value=self.settings.get("bgm_mode","single"))
        ctk.CTkRadioButton(bgm_mode_f, text="Single BGM", variable=self.bgm_mode_var,
            value="single", text_color=C["text"], fg_color=C["accent"],
            command=self._on_bgm_mode_change).pack(side="left", padx=5)
        ctk.CTkRadioButton(bgm_mode_f, text="Multiple BGM", variable=self.bgm_mode_var,
            value="multiple", text_color=C["text"], fg_color=C["accent"],
            command=self._on_bgm_mode_change).pack(side="left", padx=5)

        # Single BGM panel
        self.bgm_single_panel = ctk.CTkFrame(bgm, fg_color="transparent")
        self.bgm_single_panel.pack(fill="x", padx=0, pady=0)
        bf2=ctk.CTkFrame(self.bgm_single_panel,fg_color="transparent"); bf2.pack(fill="x",padx=5,pady=3)
        ctk.CTkButton(bf2,text="Browse BGM",width=95,fg_color=C["accent"],text_color="#000",
            command=self._browse_bgm).pack(side="left",padx=3)
        self.bgm_lbl=ctk.CTkLabel(bf2,text="None",text_color=C["dim"],font=("Segoe UI",10))
        self.bgm_lbl.pack(side="left",padx=5)

        # Multiple BGM panel
        self.bgm_multi_panel = ctk.CTkFrame(bgm, fg_color="transparent")
        # Initially hidden
        mbf = ctk.CTkFrame(self.bgm_multi_panel, fg_color="transparent")
        mbf.pack(fill="x", padx=5, pady=3)
        ctk.CTkButton(mbf, text="Add BGM Track", width=110, fg_color=C["accent"],
            text_color="#000", command=self._add_bgm_track).pack(side="left", padx=3)
        ctk.CTkButton(mbf, text="Clear All", width=75, fg_color=C["red"],
            text_color="#fff", command=self._clear_bgm_tracks).pack(side="left", padx=3)
        ctk.CTkLabel(self.bgm_multi_panel,
            text="Each track plays from Scene X to Scene Y with fade-in/out crossfade",
            text_color=C["dim"], font=("Segoe UI", 9)).pack(anchor="w", padx=5, pady=(0,2))
        self.bgm_multi_list_frame = ctk.CTkFrame(self.bgm_multi_panel, fg_color="transparent")
        self.bgm_multi_list_frame.pack(fill="x", padx=5, pady=3)
        self.bgm_multi_no_lbl = ctk.CTkLabel(self.bgm_multi_list_frame, text="No BGM tracks",
            text_color=C["dim"], font=("Segoe UI",10))
        self.bgm_multi_no_lbl.pack(anchor="w")

        # Shared BGM controls
        gf=ctk.CTkFrame(bgm,fg_color="transparent"); gf.pack(fill="x",padx=5,pady=3)
        ctk.CTkLabel(gf,text="Volume:",text_color=C["dim"]).pack(side="left")
        self.bgm_vol_var=ctk.DoubleVar(value=0.15)
        self.bgm_slider=ctk.CTkSlider(gf,from_=0.0,to=1.0,variable=self.bgm_vol_var,width=95,
            command=self._on_bgm_volume_change)
        self.bgm_slider.pack(side="left",padx=5)
        self.bgm_pct_lbl=ctk.CTkLabel(gf,text="15%",text_color=C["text"],width=42)
        self.bgm_pct_lbl.pack(side="left",padx=(0,6))
        self.bgm_duck_var=ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(gf,text="Duck",variable=self.bgm_duck_var,text_color=C["text"],
            fg_color=C["accent"]).pack(side="left",padx=5)
        ff=ctk.CTkFrame(bgm,fg_color="transparent"); ff.pack(fill="x",padx=5,pady=3)
        ctk.CTkLabel(ff,text="Fade (s):",text_color=C["dim"]).pack(side="left")
        self.bgm_fade_var=ctk.DoubleVar(value=2.0)
        ctk.CTkEntry(ff,textvariable=self.bgm_fade_var,width=50,fg_color=C["entry_bg"],
            text_color=C["text"],border_color=C["border"]).pack(side="left",padx=5)

        # ── LOGO (with USE checkbox) ──
        logo_sec=self._card_with_checkbox(sb,"Logo Overlay","use_logo")
        logo_sec.grid(row=row,column=0,sticky="ew",padx=6,pady=4); row+=1
        self.logo_enabled_var=ctk.BooleanVar(value=self.settings.get("logo_enabled",True))
        ctk.CTkCheckBox(logo_sec,text="Enable Logo (alias)",variable=self.logo_enabled_var,
            text_color=C["text"],fg_color=C["accent"]).pack(anchor="w",padx=5,pady=3)
        lbf=ctk.CTkFrame(logo_sec,fg_color="transparent"); lbf.pack(fill="x",padx=5,pady=3)
        ctk.CTkButton(lbf,text="Select",width=70,fg_color=C["accent"],text_color="#000",
            command=self._select_logo).pack(side="left",padx=2)
        ctk.CTkButton(lbf,text="Re-position",width=90,fg_color=C["orange"],text_color="#000",
            command=self._reposition_logo).pack(side="left",padx=2)
        ctk.CTkButton(lbf,text="Clear",width=55,fg_color=C["red"],text_color="#fff",
            command=self._clear_logo).pack(side="left",padx=2)
        self.logo_thumb_lbl=ctk.CTkLabel(logo_sec,text="No logo",text_color=C["dim"])
        self.logo_thumb_lbl.pack(anchor="w",padx=5,pady=3)
        self.logo_info_lbl=ctk.CTkLabel(logo_sec,text="",text_color=C["dim"],
            font=("Consolas",9),wraplength=300,justify="left")
        self.logo_info_lbl.pack(anchor="w",padx=5)

        # ── TRANSITIONS (optional fade crossfade) ──
        trans_sec=self._card_with_checkbox(sb,"Clip Transitions","use_transition")
        trans_sec.grid(row=row,column=0,sticky="ew",padx=6,pady=4); row+=1
        ctk.CTkLabel(trans_sec,
            text="Fade crossfade between clips during final merge",
            text_color=C["dim"],font=("Segoe UI",9)).pack(anchor="w",padx=5,pady=(0,2))
        tf=ctk.CTkFrame(trans_sec,fg_color="transparent"); tf.pack(fill="x",padx=5,pady=3)
        ctk.CTkLabel(tf,text="Duration (s):",text_color=C["dim"]).pack(side="left")
        self.transition_dur_var=ctk.DoubleVar(value=self.settings.get("transition_duration",0.5))
        ctk.CTkEntry(tf,textvariable=self.transition_dur_var,width=50,fg_color=C["entry_bg"],
            text_color=C["text"],border_color=C["border"]).pack(side="left",padx=5)
        for label, val in [("0.3s",0.3),("0.5s",0.5),("0.8s",0.8),("1.0s",1.0),("1.5s",1.5)]:
            ctk.CTkButton(tf,text=label,width=38,height=22,fg_color=C["btn"],
                hover_color=C["accent"],text_color=C["text"],font=("Segoe UI",9),
                command=lambda v=val: self.transition_dur_var.set(v)
            ).pack(side="left",padx=1)

        # ── CHROMA KEY OVERLAY (optional) ──
        chroma_sec=self._card_with_checkbox(sb,"Chroma Key Overlay","use_chroma_overlay")
        chroma_sec.grid(row=row,column=0,sticky="ew",padx=6,pady=4); row+=1
        ctk.CTkLabel(chroma_sec,
            text="Overlay a green/black screen video on SCENE clips only.\nIntro clips are NOT affected.",
            text_color=C["dim"],font=("Segoe UI",9),justify="left").pack(anchor="w",padx=5,pady=(0,2))
        cobf=ctk.CTkFrame(chroma_sec,fg_color="transparent"); cobf.pack(fill="x",padx=5,pady=3)
        ctk.CTkButton(cobf,text="Browse Overlay",width=115,fg_color=C["accent"],text_color="#000",
            command=self._browse_chroma_overlay).pack(side="left",padx=2)
        ctk.CTkButton(cobf,text="Clear",width=50,fg_color=C["red"],text_color="#fff",
            command=self._clear_chroma_overlay).pack(side="left",padx=2)
        self.chroma_overlay_lbl=ctk.CTkLabel(chroma_sec,text="No overlay",text_color=C["dim"],
            font=("Segoe UI",10),wraplength=280)
        self.chroma_overlay_lbl.pack(anchor="w",padx=5,pady=2)
        ccf=ctk.CTkFrame(chroma_sec,fg_color="transparent"); ccf.pack(fill="x",padx=5,pady=3)
        ctk.CTkLabel(ccf,text="Key color:",text_color=C["dim"]).pack(side="left")
        self.chroma_color_var=ctk.StringVar(value=self.settings.get("chroma_color","green"))
        for clbl, cval in [("Green","green"),("Black","black"),("Blue","blue"),("White","white")]:
            ctk.CTkRadioButton(ccf,text=clbl,variable=self.chroma_color_var,value=cval,
                text_color=C["text"],fg_color=C["accent"],
                font=("Segoe UI",9),radiobutton_width=14,radiobutton_height=14
            ).pack(side="left",padx=3)
        cxf=ctk.CTkFrame(chroma_sec,fg_color="transparent"); cxf.pack(fill="x",padx=5,pady=3)
        ctk.CTkLabel(cxf,text="Custom hex:",text_color=C["dim"]).pack(side="left")
        self.chroma_hex_var=ctk.StringVar(value=self.settings.get("chroma_custom_hex","00FF00"))
        ctk.CTkEntry(cxf,textvariable=self.chroma_hex_var,width=75,fg_color=C["entry_bg"],
            text_color=C["text"],border_color=C["border"],placeholder_text="00FF00").pack(side="left",padx=5)
        ctk.CTkRadioButton(cxf,text="Custom",variable=self.chroma_color_var,value="custom",
            text_color=C["text"],fg_color=C["orange"],
            font=("Segoe UI",9),radiobutton_width=14,radiobutton_height=14
        ).pack(side="left",padx=3)
        csf=ctk.CTkFrame(chroma_sec,fg_color="transparent"); csf.pack(fill="x",padx=5,pady=(0,4))
        ctk.CTkLabel(csf,text="Similarity:",text_color=C["dim"]).pack(side="left")
        self.chroma_sim_var=ctk.DoubleVar(value=self.settings.get("chroma_similarity",0.3))
        ctk.CTkSlider(csf,from_=0.05,to=0.8,variable=self.chroma_sim_var,width=80).pack(side="left",padx=3)
        self.chroma_sim_lbl=ctk.CTkLabel(csf,text="0.30",text_color=C["text"],width=35,
            font=("Consolas",9))
        self.chroma_sim_lbl.pack(side="left")
        ctk.CTkLabel(csf,text="Blend:",text_color=C["dim"]).pack(side="left",padx=(6,0))
        self.chroma_blend_var=ctk.DoubleVar(value=self.settings.get("chroma_blend",0.05))
        ctk.CTkSlider(csf,from_=0.0,to=0.3,variable=self.chroma_blend_var,width=65).pack(side="left",padx=3)
        self.chroma_blend_lbl=ctk.CTkLabel(csf,text="0.05",text_color=C["text"],width=35,
            font=("Consolas",9))
        self.chroma_blend_lbl.pack(side="left")
        self.chroma_sim_var.trace_add("write", lambda *a: self.chroma_sim_lbl.configure(
            text=f"{self.chroma_sim_var.get():.2f}"))
        self.chroma_blend_var.trace_add("write", lambda *a: self.chroma_blend_lbl.configure(
            text=f"{self.chroma_blend_var.get():.2f}"))
        self.chroma_overlay_path = self.settings.get("chroma_overlay_path", "")

        # ── RENDER ──
        ren=self._card(sb,"Render Options")
        ren.grid(row=row,column=0,sticky="ew",padx=6,pady=4); row+=1
        rf=ctk.CTkFrame(ren,fg_color="transparent"); rf.pack(fill="x",padx=5,pady=3)
        self.render_mode_var=ctk.StringVar(value="direct")
        ctk.CTkRadioButton(rf,text="Direct",variable=self.render_mode_var,value="direct",
            text_color=C["text"],fg_color=C["accent"]).pack(side="left",padx=5)
        ctk.CTkRadioButton(rf,text="Loop",variable=self.render_mode_var,value="loop",
            text_color=C["text"],fg_color=C["accent"]).pack(side="left",padx=5)
        lf2=ctk.CTkFrame(ren,fg_color="transparent"); lf2.pack(fill="x",padx=5,pady=3)
        ctk.CTkLabel(lf2,text="Loop count:",text_color=C["dim"]).pack(side="left")
        self.loop_var=ctk.IntVar(value=2)
        ctk.CTkEntry(lf2,textvariable=self.loop_var,width=50,fg_color=C["entry_bg"],
            text_color=C["text"],border_color=C["border"]).pack(side="left",padx=5)
        ctk.CTkLabel(ren,
            text="Loop mode: intro plays once at its position,\nthen MAIN portion is copy-looped (super fast)",
            text_color=C["dim"],font=("Segoe UI",9),justify="left"
        ).pack(anchor="w",padx=5,pady=(0,4))

        # Audio & Video Concurrency Threads for VideoMasterEditorFrame
        th_f = ctk.CTkFrame(ren, fg_color="transparent")
        th_f.pack(fill="x", padx=5, pady=(4, 2))
        
        # Audio Thread
        at_row = ctk.CTkFrame(th_f, fg_color="transparent")
        at_row.pack(fill="x", pady=2)
        ctk.CTkLabel(at_row, text="Audio Thread:", text_color=C["dim"], font=("Segoe UI", 10, "bold"), width=120, anchor="w").pack(side="left")
        
        def _dec_tts_th():
            global MAX_PARALLEL_TTS
            if MAX_PARALLEL_TTS > 1:
                MAX_PARALLEL_TTS -= 1
                self.audio_th_lbl.configure(text=f"{MAX_PARALLEL_TTS} Threads")
                self.audio_th_slider.set(MAX_PARALLEL_TTS)
                
        def _inc_tts_th():
            global MAX_PARALLEL_TTS
            if MAX_PARALLEL_TTS < 16:
                MAX_PARALLEL_TTS += 1
                self.audio_th_lbl.configure(text=f"{MAX_PARALLEL_TTS} Threads")
                self.audio_th_slider.set(MAX_PARALLEL_TTS)
                
        def _on_tts_slider(v):
            global MAX_PARALLEL_TTS
            MAX_PARALLEL_TTS = int(float(v))
            self.audio_th_lbl.configure(text=f"{MAX_PARALLEL_TTS} Threads")

        ctk.CTkButton(at_row, text="−", width=24, height=22, font=("Segoe UI", 11, "bold"), fg_color=C["btn"], hover_color=C["btn_hov"], command=_dec_tts_th).pack(side="left", padx=(0, 3))
        self.audio_th_slider = ctk.CTkSlider(at_row, from_=1, to=16, number_of_steps=15, width=90, height=14, command=_on_tts_slider)
        self.audio_th_slider.set(MAX_PARALLEL_TTS)
        self.audio_th_slider.pack(side="left", padx=2)
        ctk.CTkButton(at_row, text="+", width=24, height=22, font=("Segoe UI", 11, "bold"), fg_color=C["btn"], hover_color=C["btn_hov"], command=_inc_tts_th).pack(side="left", padx=(3, 5))
        self.audio_th_lbl = ctk.CTkLabel(at_row, text=f"{MAX_PARALLEL_TTS} Threads", text_color=C["accent"], font=("Consolas", 10, "bold"), width=68)
        self.audio_th_lbl.pack(side="left")

        # Editing Video Thread
        vt_row = ctk.CTkFrame(th_f, fg_color="transparent")
        vt_row.pack(fill="x", pady=2)
        ctk.CTkLabel(vt_row, text="Editing Video Thread:", text_color=C["dim"], font=("Segoe UI", 10, "bold"), width=120, anchor="w").pack(side="left")
        
        def _dec_ff_th():
            global MAX_PARALLEL_FF
            if MAX_PARALLEL_FF > 1:
                MAX_PARALLEL_FF -= 1
                self.video_th_lbl.configure(text=f"{MAX_PARALLEL_FF} Threads")
                self.video_th_slider.set(MAX_PARALLEL_FF)
                
        def _inc_ff_th():
            global MAX_PARALLEL_FF
            if MAX_PARALLEL_FF < 12:
                MAX_PARALLEL_FF += 1
                self.video_th_lbl.configure(text=f"{MAX_PARALLEL_FF} Threads")
                self.video_th_slider.set(MAX_PARALLEL_FF)
                
        def _on_ff_slider(v):
            global MAX_PARALLEL_FF
            MAX_PARALLEL_FF = int(float(v))
            self.video_th_lbl.configure(text=f"{MAX_PARALLEL_FF} Threads")

        ctk.CTkButton(vt_row, text="−", width=24, height=22, font=("Segoe UI", 11, "bold"), fg_color=C["btn"], hover_color=C["btn_hov"], command=_dec_ff_th).pack(side="left", padx=(0, 3))
        self.video_th_slider = ctk.CTkSlider(vt_row, from_=1, to=12, number_of_steps=11, width=90, height=14, command=_on_ff_slider)
        self.video_th_slider.set(MAX_PARALLEL_FF)
        self.video_th_slider.pack(side="left", padx=2)
        ctk.CTkButton(vt_row, text="+", width=24, height=22, font=("Segoe UI", 11, "bold"), fg_color=C["btn"], hover_color=C["btn_hov"], command=_inc_ff_th).pack(side="left", padx=(3, 5))
        self.video_th_lbl = ctk.CTkLabel(vt_row, text=f"{MAX_PARALLEL_FF} Threads", text_color=C["accent"], font=("Consolas", 10, "bold"), width=68)
        self.video_th_lbl.pack(side="left")

        # ═══ RIGHT SIDE ═══
        top_bar=ctk.CTkFrame(right,fg_color=C["card"],height=50)
        top_bar.grid(row=0,column=0,sticky="ew",padx=5,pady=5)
        ctk.CTkButton(top_bar,text="+ Scene",fg_color=C["green"],text_color="#000",
            width=80,command=self._add_scene_dialog).pack(side="left",padx=4,pady=7)
        ctk.CTkButton(top_bar,text="Upload Media",fg_color=C["accent"],text_color="#000",
            width=105,command=self._upload_media_files).pack(side="left",padx=4,pady=7)
        ctk.CTkButton(top_bar,text="Upload M-Folder",fg_color=C["accent"],text_color="#000",
            width=115,command=self._upload_media_folder).pack(side="left",padx=4,pady=7)
        ctk.CTkButton(top_bar,text="Upload Filler",fg_color=C["purple"],text_color="#fff",
            width=95,command=self._select_filler).pack(side="left",padx=4,pady=7)
        self.filler_lbl=ctk.CTkLabel(top_bar,text="No filler",text_color=C["dim"],
            font=("Segoe UI",10))
        self.filler_lbl.pack(side="left",padx=5)

        # ── Apply All Videos effect (Reverse / Freeze+Zoom) ──
        sep_lbl = ctk.CTkLabel(top_bar, text="│", text_color=C["border"],
            font=("Segoe UI", 14))
        sep_lbl.pack(side="left", padx=(8,4), pady=7)
        ctk.CTkLabel(top_bar, text="All Videos:", text_color=C["dim"],
            font=("Segoe UI", 10)).pack(side="left", padx=(0,3), pady=7)
        ctk.CTkButton(top_bar, text="⟲ Reverse All", fg_color=C["accent"],
            text_color="#000", width=105, height=28, font=("Segoe UI", 10, "bold"),
            command=lambda: self._apply_all_video_mode("reverse")).pack(side="left", padx=2, pady=7)
        ctk.CTkButton(top_bar, text="⏸ Freeze+Zoom All", fg_color=C["orange"],
            text_color="#000", width=130, height=28, font=("Segoe UI", 10, "bold"),
            command=lambda: self._apply_all_video_mode("freeze_zoom")).pack(side="left", padx=2, pady=7)

        self.blocks_frame=ctk.CTkScrollableFrame(right,fg_color=C["bg"])
        self.blocks_frame.grid(row=1,column=0,sticky="nsew",padx=5,pady=5)
        self.blocks_frame.grid_columnconfigure(0,weight=1)

        # ── Bottom: two rows – actions + progress ──
        bot_bar=ctk.CTkFrame(right,fg_color=C["card"])
        bot_bar.grid(row=2,column=0,sticky="ew",padx=5,pady=5)
        bot_bar.grid_columnconfigure(0, weight=1)

        act_row = ctk.CTkFrame(bot_bar, fg_color="transparent")
        act_row.grid(row=0, column=0, sticky="ew", padx=5, pady=(6,2))
        ctk.CTkButton(act_row,text="Generate All",fg_color=C["green"],text_color="#000",
            width=100,height=32,font=("Segoe UI",12,"bold"),
            command=self._generate_all).pack(side="left",padx=3)
        ctk.CTkButton(act_row,text="Gen Next ▶",fg_color=C["orange"],text_color="#000",
            width=100,height=32,font=("Segoe UI",12,"bold"),
            command=self._generate_pending_only).pack(side="left",padx=3)
        ctk.CTkButton(act_row,text="Merge Final",fg_color=C["accent"],text_color="#000",
            width=100,height=32,font=("Segoe UI",12,"bold"),
            command=self._merge_final).pack(side="left",padx=3)
        ctk.CTkButton(act_row,text="Clean",fg_color=C["red"],text_color="#fff",
            width=70,height=32,font=("Segoe UI",11,"bold"),
            command=self._clear_project).pack(side="left",padx=3)
        self.status_lbl=ctk.CTkLabel(act_row,text="Ready",text_color=C["dim"],
            font=("Segoe UI",11),anchor="w")
        self.status_lbl.pack(side="left",padx=10,fill="x",expand=True)

        prog_row = ctk.CTkFrame(bot_bar, fg_color="transparent")
        prog_row.grid(row=1, column=0, sticky="ew", padx=5, pady=(2,6))
        prog_row.grid_columnconfigure(0, weight=1)
        self.progress=ctk.CTkProgressBar(prog_row,height=14,fg_color=C["border"],
            progress_color=C["green"])
        self.progress.grid(row=0,column=0,sticky="ew",padx=(4,8))
        self.progress.set(0)
        self.sub_status_lbl=ctk.CTkLabel(prog_row,text="",text_color=C["accent"],
            font=("Consolas",10),width=260,anchor="e")
        self.sub_status_lbl.grid(row=0,column=1,sticky="e",padx=4)

        # Initial panel visibility
        self._on_audio_source_change()
        self._on_bgm_mode_change()

    def _card(self, parent, title):
        f=ctk.CTkFrame(parent,fg_color=C["card"],border_color=C["border"],
            border_width=1,corner_radius=8)
        ctk.CTkLabel(f,text=f"█  {title.upper()}",text_color=C["accent"],
            font=("Segoe UI",14,"bold")).pack(anchor="w",padx=8,pady=(5,2))
        return f

    def _card_with_checkbox(self, parent, title, var_key):
        f = ctk.CTkFrame(parent, fg_color=C["card"], border_color=C["border"],
                         border_width=1, corner_radius=8)
        header = ctk.CTkFrame(f, fg_color="transparent")
        header.pack(fill="x", padx=8, pady=(5,2))
        ctk.CTkLabel(header, text=f"█  {title.upper()}", text_color=C["accent"],
                     font=("Segoe UI",14,"bold")).pack(side="left")
        use_var = ctk.BooleanVar(value=self.settings.get(var_key, True))
        setattr(self, var_key + "_var", use_var)
        ctk.CTkCheckBox(header, text="Use", variable=use_var,
                        text_color=C["green"], fg_color=C["green"],
                        font=("Segoe UI",11,"bold"), width=20
        ).pack(side="right")
        return f

    def _set_crop_preset(self, r, b):
        self.crop_right_var.set(r)
        self.crop_bottom_var.set(b)

    # ── Audio source toggle ──
    def _on_audio_source_change(self):
        if self.audio_source_var.get() == "elevenlabs":
            self.elevenlabs_panel.pack(fill="x", padx=0, pady=0)
            self.bulk_audio_panel.pack_forget()
        else:
            self.elevenlabs_panel.pack_forget()
            self.bulk_audio_panel.pack(fill="x", padx=0, pady=0)

    # ── BGM mode toggle ──
    def _on_bgm_mode_change(self):
        if self.bgm_mode_var.get() == "single":
            self.bgm_single_panel.pack(fill="x", padx=0, pady=0)
            self.bgm_multi_panel.pack_forget()
        else:
            self.bgm_single_panel.pack_forget()
            self.bgm_multi_panel.pack(fill="x", padx=0, pady=0)

    # ── Settings ──
    def _on_bgm_volume_change(self, _=None):
        pct = int(round(float(self.bgm_vol_var.get()) * 100))
        if hasattr(self, "bgm_pct_lbl"):
            self.bgm_pct_lbl.configure(text=f"{pct}%")

    def _safe_open_media(self, path):
        if not path or not os.path.exists(path):
            return False
        try:
            if hasattr(os, "startfile"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            return True
        except Exception as e:
            messagebox.showerror("Preview", f"Cannot open file:\n{e}")
            return False

    def _estimate_scene_output_duration(self, block):
        tts_audio = block.get("tts_audio", "")
        if tts_audio and os.path.exists(tts_audio):
            return get_duration(tts_audio)
        op = block.get("output", "")
        if op and os.path.exists(op):
            return get_duration(op)
        return estimate_tts_duration_from_text(block.get("text", "")) + max(0.0, float(self.silence_var.get()))

    def _confirm_generate_start(self):
        scenes = len(self.blocks)
        use_intro = self.use_intro_var.get()
        intros = [e for e in self.intro_entries if os.path.exists(e.get("path",""))] if use_intro else []
        intro_dur = sum(get_duration(e["path"]) for e in intros)
        blanks = sum(1 for b in self.blocks if not b.get("source_media") or not os.path.exists(b.get("source_media", "")))
        images = sum(1 for b in self.blocks if b.get("media_type") == "image")
        videos = sum(1 for b in self.blocks if b.get("media_type") == "video")
        est_scene_dur = sum(self._estimate_scene_output_duration(b) for b in self.blocks)
        loop_count = self.loop_var.get() if self.render_mode_var.get() == "loop" else 1
        final_est = intro_dur + (est_scene_dur * max(1, int(loop_count)))
        audio_mode = self.audio_source_var.get()
        msg = (
            f"Audio source: {'ElevenLabs TTS' if audio_mode == 'elevenlabs' else 'Bulk Upload'}\n"
            f"Scenes: {scenes} (Videos: {videos} | Images: {images})\n"
            f"Intro clips: {len(intros)} ({format_duration(intro_dur)}) {'[ON]' if use_intro else '[OFF]'}\n"
            f"Blank / filler scenes: {blanks}\n"
            f"Estimated scene voice duration: {format_duration(est_scene_dur)}\n"
            f"Estimated final duration after merge: {format_duration(final_est)}\n"
            f"Parallel TTS workers: {MAX_PARALLEL_TTS}\n\n"
            "Start generating now?"
        )
        return messagebox.askyesno("Confirm Generate", msg)

    def _confirm_merge_start(self, ordered_clips, loop_count):
        total_dur = sum(get_duration(c) for c in ordered_clips if os.path.exists(c))
        generated = sum(1 for b in self.blocks if b.get("output") and os.path.exists(b["output"]))
        missing = len(self.blocks) - generated
        msg = (
            f"Total clips in sequence: {len(ordered_clips)} ({format_duration(total_dur)})\n"
            f"Main scenes ready: {generated}/{len(self.blocks)}\n"
            f"Missing scenes: {missing}\n"
            f"Loop count on MAIN portion: x{loop_count}\n"
            f"BGM: {'ON' if self.use_bgm_var.get() else 'OFF'} ({self.bgm_mode_var.get()})  |  "
            f"Logo: {'ON' if self.use_logo_var.get() else 'OFF'}\n"
            f"Expected final duration: ~{format_duration(total_dur * max(1, loop_count))}\n\n"
            "Continue final render?"
        )
        return messagebox.askyesno("Confirm Final Render", msg)

    def _play_block_output(self, idx):
        if idx < 0 or idx >= len(self.blocks):
            return
        block = self.blocks[idx]
        target = ""
        if block.get("output") and os.path.exists(block["output"]):
            target = block["output"]
        elif block.get("video") and os.path.exists(block["video"]):
            target = block["video"]
        elif block.get("tts_audio") and os.path.exists(block["tts_audio"]):
            target = block["tts_audio"]
        if not target:
            messagebox.showwarning("Play", "No generated voice/output available for this scene yet.")
            return
        if self._safe_open_media(target):
            self._set_status(f"Opened preview → Scene_{block['num']}_ | {os.path.basename(target)}", C["accent"])

    def _clear_project(self):
        if not messagebox.askyesno("Clean Project", "Clear current script, scenes, intro, filler, BGM, logo and temp outputs for a fresh start?"):
            return
        self.text_box.delete("1.0", "end")
        for b in self.blocks:
            if b.get("frame"):
                try: b["frame"].destroy()
                except: pass
        self.blocks.clear()
        self.intro_entries = []
        self._refresh_intro_list_ui()
        self.filler_path = ""
        self.filler_lbl.configure(text="No filler")
        self.bgm_path = ""
        self.bgm_lbl.configure(text="None")
        self.bgm_multi_entries = []
        self._refresh_bgm_multi_list_ui()
        self.progress.set(0)
        self.sub_status_lbl.configure(text="")
        self._clear_logo()
        for name in os.listdir(TEMP_DIR):
            p = os.path.join(TEMP_DIR, name)
            if os.path.abspath(p) == os.path.abspath(SETTINGS_FILE):
                continue
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    os.remove(p)
            except:
                pass
        self._set_status("Project cleaned. Paste new script and start again.", C["green"])

    def _restore_settings(self):
        s=self.settings
        if s.get("api_key") and s.get("api_key") != "sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt":
            self.api_entry.insert(0, s["api_key"])
        self.silence_var.set(s.get("silence_pad",0.0))
        self.render_mode_var.set(s.get("render_mode","direct"))
        self.loop_var.set(s.get("loop_count",2))
        self.bgm_vol_var.set(s.get("bgm_volume",0.15))
        self._on_bgm_volume_change()
        self.bgm_duck_var.set(s.get("bgm_duck",True))
        self.bgm_fade_var.set(s.get("bgm_fade",2.0))
        self.bgm_mode_var.set(s.get("bgm_mode","single"))
        self.logo_enabled_var.set(s.get("logo_enabled",True))
        self.auto_crop_var.set(s.get("auto_crop_enabled",True))
        self.crop_right_var.set(s.get("crop_right_px",151))
        self.crop_bottom_var.set(s.get("crop_bottom_px",151))
        self.audio_source_var.set(s.get("audio_source","elevenlabs"))
        self.use_intro_var.set(s.get("use_intro", True))
        self.use_bgm_var.set(s.get("use_bgm", True))
        self.use_logo_var.set(s.get("use_logo", True))
        if self.bgm_path and os.path.exists(self.bgm_path):
            self.bgm_lbl.configure(text=os.path.basename(self.bgm_path))
        if self.filler_path and os.path.exists(self.filler_path):
            self.filler_lbl.configure(text=os.path.basename(self.filler_path))
        else: self.filler_path=""
        if os.path.exists(self.logo_processed_path):
            self.logo_pil=Image.open(self.logo_processed_path).convert("RGBA")
            self._update_logo_thumb(); self._update_logo_info()
        elif s.get("logo_path") and os.path.exists(s["logo_path"]):
            self.logo_pil=Image.open(s["logo_path"]).convert("RGBA")
            self._update_logo_thumb(); self._update_logo_info()
        # Restore multi BGM entries
        raw_multi = s.get("bgm_multi_entries", [])
        self.bgm_multi_entries = []
        for entry in raw_multi:
            if isinstance(entry, dict) and entry.get("path") and os.path.exists(entry["path"]):
                self.bgm_multi_entries.append(entry)
        self._refresh_bgm_multi_list_ui()
        # Restore intro entries
        self.intro_entries = [e for e in self.intro_entries if os.path.exists(e.get("path",""))]
        self._refresh_intro_list_ui()
        self._on_audio_source_change()
        self._on_bgm_mode_change()
        # Restore transition & chroma settings
        self.use_transition_var.set(s.get("use_transition", False))
        self.transition_dur_var.set(s.get("transition_duration", 0.5))
        self.use_chroma_overlay_var.set(s.get("use_chroma_overlay", False))
        self.chroma_color_var.set(s.get("chroma_color", "green"))
        self.chroma_hex_var.set(s.get("chroma_custom_hex", "00FF00"))
        self.chroma_sim_var.set(s.get("chroma_similarity", 0.3))
        self.chroma_blend_var.set(s.get("chroma_blend", 0.05))
        self.chroma_overlay_path = s.get("chroma_overlay_path", "")
        if self.chroma_overlay_path and os.path.exists(self.chroma_overlay_path):
            self.chroma_overlay_lbl.configure(text=os.path.basename(self.chroma_overlay_path))
        else:
            self.chroma_overlay_path = ""

    def _collect_settings(self):
        return {
            "api_key":self.api_entry.get(),"last_model":self.model_var.get(),
            "last_voice":self.voice_var.get(),"silence_pad":self.silence_var.get(),
            "render_mode":self.render_mode_var.get(),"loop_count":self.loop_var.get(),
            "intro_videos": self.intro_entries,
            "bgm_path":self.bgm_path,"bgm_volume":self.bgm_vol_var.get(),
            "bgm_duck":self.bgm_duck_var.get(),"bgm_fade":self.bgm_fade_var.get(),
            "bgm_mode":self.bgm_mode_var.get(),
            "bgm_multi_entries": self.bgm_multi_entries,
            "logo_enabled":self.logo_enabled_var.get(),
            "use_intro": self.use_intro_var.get(),
            "use_bgm": self.use_bgm_var.get(),
            "use_logo": self.use_logo_var.get(),
            "audio_source": self.audio_source_var.get(),
            "logo_path":self.settings.get("logo_path",""),
            "logo_size":self.settings.get("logo_size",80),
            "logo_opacity":self.settings.get("logo_opacity",100),
            "logo_anchor":self.settings.get("logo_anchor","top-left"),
            "logo_margin_x":self.settings.get("logo_margin_x",20),
            "logo_margin_y":self.settings.get("logo_margin_y",20),
            "logo_pos_x":self.settings.get("logo_pos_x",20),
            "logo_pos_y":self.settings.get("logo_pos_y",20),
            "filler_video":self.filler_path,
            "auto_crop_enabled":self.auto_crop_var.get(),
            "crop_right_px":self.crop_right_var.get(),
            "crop_bottom_px":self.crop_bottom_var.get(),
            "window_geometry":"1280x720",
            "last_upload_dir":self.settings.get("last_upload_dir",""),
            "last_save_dir":self.settings.get("last_save_dir",""),
            "default_zoom_speed":self.settings.get("default_zoom_speed", 0.0015),
            "use_transition":self.use_transition_var.get(),
            "transition_duration":self.transition_dur_var.get(),
            "use_chroma_overlay":self.use_chroma_overlay_var.get(),
            "chroma_overlay_path":self.chroma_overlay_path,
            "chroma_color":self.chroma_color_var.get(),
            "chroma_custom_hex":self.chroma_hex_var.get(),
            "chroma_similarity":self.chroma_sim_var.get(),
            "chroma_blend":self.chroma_blend_var.get(),
        }

    def _on_close(self):
        try: SettingsManager.save(self._collect_settings())
        except: pass

    # ── API ──
    def _toggle_key(self):
        if self.api_entry.cget("show")=="•":
            self.api_entry.configure(show=""); self.eye_btn.configure(text="🙈")
        else:
            self.api_entry.configure(show="•"); self.eye_btn.configure(text="👁")

    def _fetch_models(self):
        key=self.api_entry.get().strip()
        if not key: messagebox.showwarning("API","Enter API key first."); return
        try:
            from ai33_api import AI33Client
            client = AI33Client(api_key=key)
            self.models = client.fetch_models()
            names = [m.get("name", m.get("model_id", "")) for m in self.models]
            self.model_menu.configure(values=names)
            last = self.settings.get("last_model", "")
            if last in names: self.model_var.set(last)
            elif names: self.model_var.set(names[0])
            self._set_status(f"Loaded {len(names)} models", C["green"])
        except Exception as e: messagebox.showerror("Error",f"Fetch models failed:\n{e}")

    def _fetch_voices(self):
        key=self.api_entry.get().strip()
        if not key: messagebox.showwarning("API","Enter API key first."); return
        try:
            from ai33_api import AI33Client
            client = AI33Client(api_key=key)
            self.voices = client.fetch_voices()
            self.voice_list_full = []
            names = []
            for v in self.voices:
                name = v.get("name", "Voice")
                vid = v.get("voice_id", "")
                cat = v.get("category", "")
                prov = v.get("provider", "")
                display = f"[{prov}] {name} [{cat}] ({vid})" if prov and cat else (f"[{prov}] {name} ({vid})" if prov else f"{name} ({vid})")
                self.voice_list_full.append((display, vid))
                names.append(display)
            self.voice_menu.configure(values=names if names else ["No voices found"])
            last = self.settings.get("last_voice", "")
            if last in names: self.voice_var.set(last)
            elif names: self.voice_var.set(names[0])
            self._set_status(f"Loaded {len(names)} voices", C["green"])
        except Exception as e: messagebox.showerror("Error",f"Fetch voices failed:\n{e}")

    def _filter_voices(self,_=None):
        q=self.voice_search.get().strip().lower()
        fl=[v[0] for v in self.voice_list_full if (not q or q in v[0].lower())]
        self.voice_menu.configure(values=fl if fl else ["(no match)"])
        if fl: self.voice_var.set(fl[0])

    # ══════════════════════════════════════════════════════════
    # BULK AUDIO UPLOAD
    # ══════════════════════════════════════════════════════════
    def _bulk_upload_audio_files(self):
        init = self.settings.get("last_upload_dir", "")
        ps = filedialog.askopenfilenames(
            filetypes=[("Audio", "*.mp3 *.wav *.aac *.m4a *.ogg *.flac")],
            initialdir=init if init else None)
        if not ps: return
        self.settings["last_upload_dir"] = os.path.dirname(ps[0])
        self._map_audio_to_blocks(list(ps))

    def _bulk_upload_audio_folder(self):
        init = self.settings.get("last_upload_dir", "")
        folder = filedialog.askdirectory(title="Select audio folder (subfolders included)",
            initialdir=init if init else None)
        if not folder: return
        self.settings["last_upload_dir"] = folder
        exts = (".mp3", ".wav", ".aac", ".m4a", ".ogg", ".flac")
        # Recursive scan — walks into ALL subfolders
        ps = []
        for root, dirs, files in os.walk(folder):
            for f in files:
                if os.path.splitext(f)[1].lower() in exts:
                    ps.append(os.path.join(root, f))
        if not ps:
            messagebox.showinfo("Folder", "No audio files found in folder or subfolders.")
            return
        self._map_audio_to_blocks(ps)

    def _map_audio_to_blocks(self, paths):
        if not self.blocks:
            messagebox.showwarning("Blocks", "Create scene blocks first.")
            return
        paths = sort_files(paths)
        mapped = 0
        unmapped = []

        for p in paths:
            n = extract_scene_number(p)
            assigned = False
            if n is not None and 1 <= n <= len(self.blocks):
                block = self.blocks[n - 1]
                pad = max(0.0, float(self.silence_var.get()))
                cleaned = os.path.join(TEMP_DIR, f"tts_{n}_clean.wav")
                result = clean_tts_audio(p, cleaned, pad_sec=pad)
                audio_path = result if result else p
                block["tts_audio"] = audio_path
                block["audio_source_file"] = p
                block["status_label"].configure(
                    text=f"Audio mapped → Scene_{n}_ ({format_duration(get_duration(audio_path))})",
                    text_color=C["green"])
                mapped += 1
                assigned = True
            if not assigned:
                unmapped.append(p)

        for p in unmapped:
            for bi, b in enumerate(self.blocks):
                if not b.get("tts_audio") or not os.path.exists(b.get("tts_audio", "")):
                    num = b["num"]
                    pad = max(0.0, float(self.silence_var.get()))
                    cleaned = os.path.join(TEMP_DIR, f"tts_{num}_clean.wav")
                    result = clean_tts_audio(p, cleaned, pad_sec=pad)
                    audio_path = result if result else p
                    b["tts_audio"] = audio_path
                    b["audio_source_file"] = p
                    b["status_label"].configure(
                        text=f"Audio mapped seq → Scene_{num}_ ({format_duration(get_duration(audio_path))})",
                        text_color=C["green"])
                    mapped += 1
                    break

        self.bulk_audio_lbl.configure(
            text=f"Mapped {mapped}/{len(paths)} audio files to scenes")
        self._set_status(f"Bulk audio: {mapped}/{len(paths)} mapped", C["green"])

    # ══════════════════════════════════════════════════════════
    # INTRO VIDEOS (with Before Scene N)
    # ══════════════════════════════════════════════════════════
    def _add_intro(self):
        ps = filedialog.askopenfilenames(filetypes=[("Video", "*.mp4 *.mov *.avi *.mkv")])
        if not ps: return
        for p in ps:
            self.intro_entries.append({"path": p, "before_scene": 1})
        self._refresh_intro_list_ui()

    def _clear_intros(self):
        self.intro_entries.clear()
        self._refresh_intro_list_ui()

    def _remove_intro(self, idx):
        if 0 <= idx < len(self.intro_entries):
            self.intro_entries.pop(idx)
            self._refresh_intro_list_ui()

    def _update_intro_before_scene(self, idx, value):
        if 0 <= idx < len(self.intro_entries):
            try:
                val = max(1, int(value))
            except:
                val = 1
            self.intro_entries[idx]["before_scene"] = val

    def _refresh_intro_list_ui(self):
        for w in self.intro_list_frame.winfo_children():
            w.destroy()
        if not self.intro_entries:
            self.intro_no_lbl = ctk.CTkLabel(self.intro_list_frame, text="No intros",
                text_color=C["dim"], font=("Segoe UI", 10))
            self.intro_no_lbl.pack(anchor="w")
            return
        for i, entry in enumerate(self.intro_entries):
            row_f = ctk.CTkFrame(self.intro_list_frame, fg_color=C["btn"], corner_radius=5)
            row_f.pack(fill="x", pady=2)
            fname = os.path.basename(entry.get("path", "?"))
            dur = get_duration(entry["path"]) if os.path.exists(entry.get("path","")) else 0
            ctk.CTkLabel(row_f, text=f"#{i+1} {fname} ({format_duration(dur)})",
                text_color=C["text"], font=("Segoe UI", 9),
                wraplength=160, justify="left").pack(side="left", padx=4, pady=2)
            ctk.CTkLabel(row_f, text="Before Scene:",
                text_color=C["dim"], font=("Segoe UI", 9)).pack(side="left", padx=(4,2))
            sv = ctk.IntVar(value=entry.get("before_scene", 1))
            e_widget = ctk.CTkEntry(row_f, textvariable=sv, width=40,
                fg_color=C["entry_bg"], text_color=C["text"],
                border_color=C["border"], font=("Segoe UI", 9))
            e_widget.pack(side="left", padx=2)
            cap_i = i
            sv.trace_add("write", lambda *a, idx=cap_i, var=sv: self._update_intro_before_scene(idx, var.get()))
            ctk.CTkButton(row_f, text="X", width=24, height=22,
                fg_color=C["red"], text_color="#fff", font=("Segoe UI", 9, "bold"),
                command=lambda idx=cap_i: self._remove_intro(idx)).pack(side="right", padx=3, pady=2)

    # ══════════════════════════════════════════════════════════
    # BGM MULTIPLE TRACKS (scene range)
    # ══════════════════════════════════════════════════════════
    def _browse_bgm(self):
        p = filedialog.askopenfilename(filetypes=[("Audio", "*.mp3 *.wav *.aac *.m4a")])
        if p:
            self.bgm_path = p
            self.bgm_lbl.configure(text=os.path.basename(p))

    def _add_bgm_track(self):
        p = filedialog.askopenfilename(filetypes=[("Audio", "*.mp3 *.wav *.aac *.m4a *.ogg *.flac")])
        if not p: return
        total_scenes = max(len(self.blocks), 1)
        self.bgm_multi_entries.append({
            "path": p,
            "from": 1,
            "to": total_scenes
        })
        self._refresh_bgm_multi_list_ui()

    def _clear_bgm_tracks(self):
        self.bgm_multi_entries.clear()
        self._refresh_bgm_multi_list_ui()

    def _remove_bgm_track(self, idx):
        if 0 <= idx < len(self.bgm_multi_entries):
            self.bgm_multi_entries.pop(idx)
            self._refresh_bgm_multi_list_ui()

    def _update_bgm_track_from(self, idx, value):
        if 0 <= idx < len(self.bgm_multi_entries):
            try: val = max(1, int(value))
            except: val = 1
            self.bgm_multi_entries[idx]["from"] = val

    def _update_bgm_track_to(self, idx, value):
        if 0 <= idx < len(self.bgm_multi_entries):
            try: val = max(1, int(value))
            except: val = 1
            self.bgm_multi_entries[idx]["to"] = val

    def _refresh_bgm_multi_list_ui(self):
        for w in self.bgm_multi_list_frame.winfo_children():
            w.destroy()
        if not self.bgm_multi_entries:
            self.bgm_multi_no_lbl = ctk.CTkLabel(self.bgm_multi_list_frame,
                text="No BGM tracks", text_color=C["dim"], font=("Segoe UI", 10))
            self.bgm_multi_no_lbl.pack(anchor="w")
            return
        for i, entry in enumerate(self.bgm_multi_entries):
            row_f = ctk.CTkFrame(self.bgm_multi_list_frame, fg_color=C["btn"], corner_radius=5)
            row_f.pack(fill="x", pady=2)
            fname = os.path.basename(entry.get("path", "?"))
            dur = get_duration(entry["path"]) if os.path.exists(entry.get("path","")) else 0
            ctk.CTkLabel(row_f, text=f"#{i+1} {fname} ({format_duration(dur)})",
                text_color=C["text"], font=("Segoe UI", 9),
                wraplength=120, justify="left").pack(side="left", padx=4, pady=2)
            ctk.CTkLabel(row_f, text="From:",
                text_color=C["dim"], font=("Segoe UI", 9)).pack(side="left", padx=(4,1))
            fv = ctk.IntVar(value=entry.get("from", 1))
            ctk.CTkEntry(row_f, textvariable=fv, width=35,
                fg_color=C["entry_bg"], text_color=C["text"],
                border_color=C["border"], font=("Segoe UI", 9)).pack(side="left", padx=1)
            ctk.CTkLabel(row_f, text="To:",
                text_color=C["dim"], font=("Segoe UI", 9)).pack(side="left", padx=(3,1))
            tv = ctk.IntVar(value=entry.get("to", len(self.blocks) or 1))
            ctk.CTkEntry(row_f, textvariable=tv, width=35,
                fg_color=C["entry_bg"], text_color=C["text"],
                border_color=C["border"], font=("Segoe UI", 9)).pack(side="left", padx=1)
            cap_i = i
            fv.trace_add("write", lambda *a, idx=cap_i, var=fv: self._update_bgm_track_from(idx, var.get()))
            tv.trace_add("write", lambda *a, idx=cap_i, var=tv: self._update_bgm_track_to(idx, var.get()))
            ctk.CTkButton(row_f, text="X", width=24, height=22,
                fg_color=C["red"], text_color="#fff", font=("Segoe UI", 9, "bold"),
                command=lambda idx=cap_i: self._remove_bgm_track(idx)).pack(side="right", padx=3, pady=2)

    def _preview_crop(self):
        media = self._find_any_media()
        if not media:
            messagebox.showwarning("Preview", "Load any video/image, intro, or filler first for crop preview.")
            return
        CropPreviewWindow(self, media, self.crop_right_var.get(), self.crop_bottom_var.get(),
                          apply_crop=self.auto_crop_var.get())

    # ── Logo ──
    def _select_logo(self):
        p = filedialog.askopenfilename(filetypes=[("Image", "*.png *.jpg *.jpeg *.webp *.bmp")])
        if not p: return
        self.settings["logo_path"] = p
        self.logo_pil = Image.open(p).convert("RGBA")
        self.logo_pil.save(self.logo_processed_path)
        self._update_logo_thumb()
        vid = self._find_any_media()
        if vid: self._open_logo_preview(vid)
        else: messagebox.showinfo("Logo", "Logo loaded. Add a video/image to preview and lock its final position.")

    def _reposition_logo(self):
        if not self.logo_pil: messagebox.showwarning("Logo", "No logo loaded."); return
        vid = self._find_any_media()
        if not vid: messagebox.showwarning("Logo", "No media for preview."); return
        self._open_logo_preview(vid)

    def _clear_logo(self):
        self.logo_pil = None; self.settings["logo_path"] = ""
        self.logo_thumb_lbl.configure(text="No logo", image=None)
        self.logo_info_lbl.configure(text="")
        if os.path.exists(self.logo_processed_path):
            try: os.remove(self.logo_processed_path)
            except: pass

    def _find_any_media(self):
        """Find any available video or image for previewing."""
        for b in self.blocks:
            # Check for source_media (image or video)
            sm = b.get("source_media", "")
            if sm and os.path.exists(sm):
                # For images, return as-is; for videos return as-is
                return sm
            v = b.get("video", "")
            if v and os.path.exists(v): return v
        if self.filler_path and os.path.exists(self.filler_path): return self.filler_path
        for e in self.intro_entries:
            if os.path.exists(e.get("path", "")): return e["path"]
        return None

    def _open_logo_preview(self, vp):
        _orig, preview_bg, _meta = build_crop_preview_images(
            vp, self.crop_right_var.get(), self.crop_bottom_var.get(),
            apply_crop=self.auto_crop_var.get())
        LogoPreviewWindow(self, preview_bg, self.logo_pil,
            self.settings.get("logo_size", 80), self.settings.get("logo_opacity", 100),
            callback=self._on_logo_positioned,
            init_anchor=self.settings.get("logo_anchor", "top-left"),
            init_mx=self.settings.get("logo_margin_x", 20),
            init_my=self.settings.get("logo_margin_y", 20),
            init_x=self.settings.get("logo_pos_x"),
            init_y=self.settings.get("logo_pos_y"))

    def _on_logo_positioned(self, anchor, mx, my, sz, opa, pil_img, pos_x, pos_y):
        self.logo_pil = pil_img.convert("RGBA")
        self.logo_pil.save(self.logo_processed_path)
        self.settings["logo_anchor"] = anchor; self.settings["logo_margin_x"] = mx
        self.settings["logo_margin_y"] = my; self.settings["logo_size"] = sz
        self.settings["logo_opacity"] = opa
        self.settings["logo_pos_x"] = int(pos_x); self.settings["logo_pos_y"] = int(pos_y)
        self._update_logo_thumb(); self._update_logo_info()
        self._set_status(f"Logo locked at X={int(pos_x)}, Y={int(pos_y)}", C["green"])

    def _update_logo_thumb(self):
        if not self.logo_pil: return
        t = self.logo_pil.copy(); t.thumbnail((40, 40), Image.LANCZOS)
        self._logo_tk = ImageTk.PhotoImage(t)
        self.logo_thumb_lbl.configure(image=self._logo_tk, text="")

    def _update_logo_info(self):
        s = self.settings
        self.logo_info_lbl.configure(
            text=f"Anchor: {s.get('logo_anchor','?')} XY:({s.get('logo_pos_x',0)},{s.get('logo_pos_y',0)})\n"
                 f"Size: {s.get('logo_size',80)}px | Opacity: {s.get('logo_opacity',100)}%")

    # ── Chroma Key Overlay ──
    def _browse_chroma_overlay(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.avi *.mkv *.webm *.flv"),
                       ("All", "*.*")])
        if p:
            self.chroma_overlay_path = p
            self.chroma_overlay_lbl.configure(text=os.path.basename(p))
            self._set_status(f"Chroma overlay set: {os.path.basename(p)}", C["green"])

    def _clear_chroma_overlay(self):
        self.chroma_overlay_path = ""
        self.chroma_overlay_lbl.configure(text="No overlay")

    def _get_chroma_hex(self):
        """Return the hex color string for the selected chroma key color."""
        color = self.chroma_color_var.get()
        if color == "green":   return "00FF00"
        if color == "black":   return "000000"
        if color == "blue":    return "0000FF"
        if color == "white":   return "FFFFFF"
        if color == "custom":  return self.chroma_hex_var.get().strip().lstrip("#")[:6]
        return "00FF00"

    # ── Filler ──
    def _select_filler(self):
        p = filedialog.askopenfilename(filetypes=[("Video", "*.mp4 *.mov *.avi *.mkv")])
        if p:
            self.filler_path = p; self.filler_lbl.configure(text=os.path.basename(p))
            self._auto_fill_blanks()

    def _auto_fill_blanks(self):
        if not self.filler_path or not os.path.exists(self.filler_path): return
        c = 0
        for b in self.blocks:
            has_real_media = (bool(b.get("source_media")) and os.path.exists(b.get("source_media", ""))
                             and not b.get("media_is_filler", False))
            if not has_real_media:
                b["source_media"] = self.filler_path
                b["media_type"] = "video"
                b["video"] = self.filler_path
                b["media_is_filler"] = True
                self._update_block_thumb(b)
                c += 1
        if c: self._set_status(f"Auto-filled {c} blank slots", C["accent"])

    # ══════════════════════════════════════════════════════════
    # BLOCKS
    # ══════════════════════════════════════════════════════════
    def _create_blocks_from_text(self):
        text = self.text_box.get("1.0", "end").strip()
        if not text: messagebox.showwarning("Text", "Enter text first."); return
        if self.blocks:
            if not messagebox.askyesno("Replace All",
                f"This will REPLACE all {len(self.blocks)} existing scenes.\n\n"
                "Use 'Add Next Scenes' to append instead.\n\nReplace all?"):
                return
        for b in self.blocks:
            if b.get("frame"): b["frame"].destroy()
        self.blocks.clear()
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        for i, line in enumerate(lines):
            clean = re.sub(r'^Scene_?\d+\s*[:\-]\s*', '', line, flags=re.IGNORECASE)
            self._create_block(i + 1, clean)
        self._auto_fill_blanks()
        self._set_status(f"Created {len(self.blocks)} scenes", C["green"])

    def _append_blocks_from_text(self):
        """Append new lines as continuation scenes (Scene_36, 37…) without touching existing blocks."""
        text = self.text_box.get("1.0", "end").strip()
        if not text: messagebox.showwarning("Text", "Enter text first."); return
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        start_num = len(self.blocks) + 1
        added = 0
        for i, line in enumerate(lines):
            clean = re.sub(r'^Scene_?\d+\s*[:\-]\s*', '', line, flags=re.IGNORECASE)
            self._create_block(start_num + i, clean)
            added += 1
        self._auto_fill_blanks()
        self.text_box.delete("1.0", "end")  # clear textbox after appending
        self._set_status(
            f"Appended {added} scenes (Scene_{start_num}_ → Scene_{start_num + added - 1}_) | "
            f"Total: {len(self.blocks)} scenes", C["green"])

    def _create_block(self, num, text, source_media_path="", media_type=""):
        """
        Create a scene block.
        source_media_path: can be a video file OR an image file.
        media_type: "video", "image", or "" (auto-detect).
        """
        frame = ctk.CTkFrame(self.blocks_frame, fg_color=C["card"], border_color=C["border"],
            border_width=1, corner_radius=8, height=130)
        frame.pack(fill="x", padx=5, pady=3); frame.pack_propagate(False)

        # Auto-detect media type
        if source_media_path and not media_type:
            if is_image_file(source_media_path):
                media_type = "image"
            elif is_video_file(source_media_path):
                media_type = "video"

        block = {
            "num": num, "text": text,
            "source_media": source_media_path,  # original image or video path
            "media_type": media_type,  # "video", "image", or ""
            "video": source_media_path if media_type == "video" else "",  # compat
            "media_is_filler": False,
            "output": "", "tts_audio": "", "audio_source_file": "",
            "frame": frame,
            "zoom_speed": self.settings.get("default_zoom_speed", 0.0015),
            "video_extend_mode": "reverse",  # "reverse" or "freeze_zoom"
        }

        top = ctk.CTkFrame(frame, fg_color="transparent"); top.pack(fill="x", padx=8, pady=(4, 2))
        nl = ctk.CTkLabel(top, text=f"Scene_{num}_", text_color=C["accent"],
            font=("Segoe UI", 13, "bold"), width=78); nl.pack(side="left")
        block["num_label"] = nl
        tl = ctk.CTkLabel(top, text="[no media]", text_color=C["dim"], width=72, height=42)
        tl.pack(side="left", padx=5); block["thumb_label"] = tl

        # Media type badge
        type_lbl = ctk.CTkLabel(top, text="", text_color=C["purple"],
            font=("Segoe UI", 9, "bold"), width=60)
        type_lbl.pack(side="left", padx=3)
        block["type_label"] = type_lbl

        mid = ctk.CTkFrame(frame, fg_color="transparent")
        mid.pack(fill="x", padx=8, pady=(0, 2))
        d = text[:70] + "…" if len(text) > 70 else text
        ctk.CTkLabel(mid, text=d, text_color=C["text"], font=("Segoe UI", 10),
            wraplength=350, anchor="w", justify="left").pack(side="left", fill="x", expand=True, padx=5)

        fl = ctk.CTkLabel(mid, text="[blank slot]", text_color=C["dim"], font=("Consolas", 9),
            anchor="w", justify="left")
        fl.pack(side="right", padx=5)
        block["file_label"] = fl

        # ── Controls row (with video mode options) ──
        ctrl = ctk.CTkFrame(frame, fg_color="transparent"); ctrl.pack(fill="x", padx=8, pady=(0, 1))

        # Video extend mode (only relevant for video sources)
        mode_var = ctk.StringVar(value="reverse")
        block["extend_mode_var"] = mode_var
        ctk.CTkLabel(ctrl, text="Extend:", text_color=C["dim"],
            font=("Segoe UI", 8)).pack(side="left", padx=(0,2))
        ctk.CTkRadioButton(ctrl, text="Reverse", variable=mode_var, value="reverse",
            text_color=C["text"], fg_color=C["accent"],
            font=("Segoe UI", 8), radiobutton_width=14, radiobutton_height=14,
            command=lambda idx=len(self.blocks): self._on_extend_mode_change(idx)
        ).pack(side="left", padx=2)
        ctk.CTkRadioButton(ctrl, text="Freeze+Zoom", variable=mode_var, value="freeze_zoom",
            text_color=C["text"], fg_color=C["orange"],
            font=("Segoe UI", 8), radiobutton_width=14, radiobutton_height=14,
            command=lambda idx=len(self.blocks): self._on_extend_mode_change(idx)
        ).pack(side="left", padx=2)

        # Zoom speed control (for images and freeze_zoom)
        ctk.CTkLabel(ctrl, text="Zoom:", text_color=C["dim"],
            font=("Segoe UI", 8)).pack(side="left", padx=(8,2))
        zoom_var = ctk.DoubleVar(value=0.0015)
        block["zoom_speed_var"] = zoom_var
        zoom_slider = ctk.CTkSlider(ctrl, from_=0.0003, to=0.005, variable=zoom_var,
            width=75, height=14,
            command=lambda val, idx=len(self.blocks): self._on_zoom_speed_change(idx, val))
        zoom_slider.pack(side="left", padx=2)
        zoom_lbl = ctk.CTkLabel(ctrl, text="0.0015", text_color=C["text"],
            font=("Consolas", 8), width=45)
        zoom_lbl.pack(side="left")
        block["zoom_speed_label"] = zoom_lbl

        bot = ctk.CTkFrame(frame, fg_color="transparent"); bot.pack(fill="x", padx=8, pady=(0, 4))
        ka = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(bot, text="Keep Audio", variable=ka, text_color=C["dim"],
            fg_color=C["accent"], font=("Segoe UI", 9)).pack(side="left", padx=3)
        block["keep_audio_var"] = ka
        st = ctk.CTkLabel(bot, text="Pending", text_color=C["orange"], font=("Segoe UI", 9))
        st.pack(side="left", padx=8); block["status_label"] = st

        idx = len(self.blocks)
        ctk.CTkButton(bot, text="Play", width=50, height=24, fg_color=C["accent"],
            text_color="#000", font=("Segoe UI", 9),
            command=lambda i=idx: self._play_block_output(i)).pack(side="right", padx=2)
        ctk.CTkButton(bot, text="Gen", width=50, height=24, fg_color=C["green"],
            text_color="#000", font=("Segoe UI", 9),
            command=lambda i=idx: self._generate_single(i)).pack(side="right", padx=2)
        ctk.CTkButton(bot, text="Del", width=45, height=24, fg_color=C["red"],
            text_color="#fff", font=("Segoe UI", 9),
            command=lambda i=idx: self._delete_scene(i)).pack(side="right", padx=2)
        ctk.CTkButton(bot, text="Replace", width=60, height=24, fg_color=C["purple"],
            text_color="#fff", font=("Segoe UI", 9),
            command=lambda i=idx: self._replace_media(i)).pack(side="right", padx=2)

        self.blocks.append(block)
        if source_media_path and os.path.exists(source_media_path):
            block["media_is_filler"] = (self.filler_path and os.path.exists(self.filler_path) and
                                        os.path.abspath(source_media_path) == os.path.abspath(self.filler_path))
            self._update_block_thumb(block)

    def _on_extend_mode_change(self, idx):
        if idx < 0 or idx >= len(self.blocks): return
        block = self.blocks[idx]
        block["video_extend_mode"] = block["extend_mode_var"].get()

    def _on_zoom_speed_change(self, idx, val):
        if idx < 0 or idx >= len(self.blocks): return
        block = self.blocks[idx]
        try:
            speed = float(val)
        except:
            speed = 0.0015
        block["zoom_speed"] = speed
        if "zoom_speed_label" in block:
            block["zoom_speed_label"].configure(text=f"{speed:.4f}")

    def _apply_all_video_mode(self, mode):
        """Apply Reverse or Freeze+Zoom extend mode to ALL video scenes at once."""
        if not self.blocks:
            messagebox.showwarning("Apply All", "No scenes created yet.")
            return
        count = 0
        for b in self.blocks:
            if b.get("media_type") == "video":
                b["video_extend_mode"] = mode
                if "extend_mode_var" in b:
                    b["extend_mode_var"].set(mode)
                count += 1
        mode_label = "Reverse" if mode == "reverse" else "Freeze+Zoom"
        self._set_status(f"Applied '{mode_label}' to {count} video scenes", C["green"])

    def _update_block_thumb(self, block):
        media = block.get("source_media", "")
        if not media or not os.path.exists(media):
            block["thumb_label"].configure(text="[blank]", image=None)
            if block.get("file_label"):
                block["file_label"].configure(text="[blank slot / filler pending]")
            if block.get("type_label"):
                block["type_label"].configure(text="")
            return

        mtype = block.get("media_type", "")

        try:
            if mtype == "image":
                img = Image.open(media).convert("RGBA")
                img.thumbnail((72, 42), Image.LANCZOS)
            else:
                img = extract_frame(media, 0.5)
                img.thumbnail((72, 42), Image.LANCZOS)
            tk = ImageTk.PhotoImage(img.convert("RGB"))
            block["_thumb_tk"] = tk; block["thumb_label"].configure(image=tk, text="")
        except:
            block["thumb_label"].configure(text="[err]", image=None)

        label = os.path.basename(media)
        if block.get("media_is_filler", False):
            label = f"[filler] {label}"
        elif mtype == "image":
            label = f"[IMG] {label}"
        else:
            label = f"[VID] {label}"
        if block.get("file_label"):
            block["file_label"].configure(text=label)

        # Update type badge
        if block.get("type_label"):
            if mtype == "image":
                block["type_label"].configure(text="IMAGE", text_color=C["orange"])
            elif mtype == "video":
                block["type_label"].configure(text="VIDEO", text_color=C["purple"])
            else:
                block["type_label"].configure(text="")

    def _add_scene_dialog(self):
        d = ctk.CTkInputDialog(text="Enter scene text:", title="Add New Scene")
        t = d.get_input()
        if t and t.strip():
            n = len(self.blocks) + 1; self._create_block(n, t.strip())
            self._set_status(f"Added scene #{n}", C["green"])

    def _delete_scene(self, idx):
        if idx < 0 or idx >= len(self.blocks): return
        if not messagebox.askyesno("Delete", f"Delete scene #{self.blocks[idx]['num']}?"): return
        b = self.blocks.pop(idx); b["frame"].destroy()
        self._reindex_blocks()
        self._set_status(f"Deleted. {len(self.blocks)} remaining.", C["orange"])

    def _replace_media(self, idx):
        """Replace media for a scene — accepts both video and image files."""
        if idx < 0 or idx >= len(self.blocks): return
        p = filedialog.askopenfilename(
            filetypes=[
                ("Media", "*.mp4 *.mov *.avi *.mkv *.webm *.flv *.jpg *.jpeg *.png *.webp *.bmp *.gif *.tiff *.tif"),
                ("Video", "*.mp4 *.mov *.avi *.mkv *.webm *.flv"),
                ("Image", "*.jpg *.jpeg *.png *.webp *.bmp *.gif *.tiff *.tif"),
            ])
        if not p: return
        mtype = "image" if is_image_file(p) else "video"
        self.blocks[idx]["source_media"] = p
        self.blocks[idx]["media_type"] = mtype
        self.blocks[idx]["video"] = p if mtype == "video" else ""
        self.blocks[idx]["media_is_filler"] = False
        self._update_block_thumb(self.blocks[idx])
        self.blocks[idx]["status_label"].configure(
            text=f"{'Image' if mtype == 'image' else 'Video'} replaced",
            text_color=C["green"])

    def _reindex_blocks(self):
        old = list(self.blocks)
        for w in self.blocks_frame.winfo_children(): w.destroy()
        self.blocks.clear()
        for i, ob in enumerate(old):
            self._create_block(i + 1, ob["text"], ob.get("source_media", ""), ob.get("media_type", ""))
            nb = self.blocks[-1]; nb["output"] = ob.get("output", "")
            nb["tts_audio"] = ob.get("tts_audio", "")
            nb["audio_source_file"] = ob.get("audio_source_file", "")
            nb["media_is_filler"] = ob.get("media_is_filler", False)
            nb["video_extend_mode"] = ob.get("video_extend_mode", "reverse")
            nb["zoom_speed"] = ob.get("zoom_speed", 0.0015)
            if isinstance(ob.get("extend_mode_var"), ctk.StringVar):
                nb["extend_mode_var"].set(ob["extend_mode_var"].get())
            if isinstance(ob.get("zoom_speed_var"), ctk.DoubleVar):
                nb["zoom_speed_var"].set(ob["zoom_speed_var"].get())
            self._update_block_thumb(nb)
            if isinstance(ob.get("keep_audio_var"), ctk.BooleanVar):
                nb["keep_audio_var"].set(ob["keep_audio_var"].get())
            if nb["output"] and os.path.exists(nb["output"]):
                nb["status_label"].configure(text="Done", text_color=C["green"])

    # ── Upload: Media Files (Video + Image) ──
    def _upload_media_files(self):
        init = self.settings.get("last_upload_dir", "")
        ps = filedialog.askopenfilenames(
            filetypes=[
                ("Media", "*.mp4 *.mov *.avi *.mkv *.webm *.flv *.jpg *.jpeg *.png *.webp *.bmp *.gif *.tiff *.tif"),
                ("Video", "*.mp4 *.mov *.avi *.mkv *.webm *.flv"),
                ("Image", "*.jpg *.jpeg *.png *.webp *.bmp *.gif *.tiff *.tif"),
            ],
            initialdir=init if init else None)
        if not ps: return
        self.settings["last_upload_dir"] = os.path.dirname(ps[0])
        self._map_media_to_blocks(list(ps))

    # ── Upload: Media Folder (Video + Image) ──
    def _upload_media_folder(self):
        init = self.settings.get("last_upload_dir", "")
        folder = filedialog.askdirectory(title="Select media folder (subfolders included)",
            initialdir=init if init else None)
        if not folder: return
        self.settings["last_upload_dir"] = folder
        # Recursive scan — walks into ALL subfolders
        ps = []
        for root, dirs, files in os.walk(folder):
            for f in files:
                if os.path.splitext(f)[1].lower() in MEDIA_EXTS:
                    ps.append(os.path.join(root, f))
        if not ps:
            messagebox.showinfo("Folder", "No video/image files found in folder or subfolders.")
            return
        subfolder_count = len(set(os.path.dirname(p) for p in ps))
        self._set_status(f"Found {len(ps)} media files across {subfolder_count} folder(s)", C["accent"])
        self._map_media_to_blocks(ps)

    # ── Map media (video + image) → blocks (scene-number based) ──
    def _map_media_to_blocks(self, paths):
        if not self.blocks:
            messagebox.showwarning("Blocks", "Create scene blocks first."); return
        paths = sort_files(paths)
        mapped = 0; unmapped = []

        def _process_in_thread():
            nonlocal mapped
            total = len(paths)
            for pi, p in enumerate(paths):
                mtype = "image" if is_image_file(p) else "video"
                n = extract_scene_number(p)
                assigned = False
                if n is not None and 1 <= n <= len(self.blocks):
                    self.blocks[n - 1]["source_media"] = p
                    self.blocks[n - 1]["media_type"] = mtype
                    self.blocks[n - 1]["video"] = p if mtype == "video" else ""
                    self.blocks[n - 1]["media_is_filler"] = False
                    self._update_block_thumb(self.blocks[n - 1])
                    tag = "IMG" if mtype == "image" else "VID"
                    self.blocks[n - 1]["status_label"].configure(
                        text=f"[{tag}] Mapped by name → Scene_{n}_",
                        text_color=C["green"])
                    mapped += 1; assigned = True
                if not assigned:
                    unmapped.append(p)
                self._set_status(f"Processing media… {pi+1}/{total}", C["orange"])
                self._set_progress((pi + 1) / total)

            for p in unmapped:
                mtype = "image" if is_image_file(p) else "video"
                for bi, b in enumerate(self.blocks):
                    has_real = (bool(b.get("source_media")) and os.path.exists(b.get("source_media", ""))
                                and not b.get("media_is_filler", False))
                    if not has_real:
                        b["source_media"] = p
                        b["media_type"] = mtype
                        b["video"] = p if mtype == "video" else ""
                        b["media_is_filler"] = False
                        self._update_block_thumb(b)
                        tag = "IMG" if mtype == "image" else "VID"
                        b["status_label"].configure(
                            text=f"[{tag}] Mapped sequentially → Scene_{bi+1}_",
                            text_color=C["green"])
                        mapped += 1; break

            for b in self.blocks:
                has_any = bool(b.get("source_media")) and os.path.exists(b.get("source_media", ""))
                if not has_any or b.get("media_is_filler", False):
                    self._update_block_thumb(b)
                    if not b.get("media_is_filler", False):
                        b["status_label"].configure(text="Blank slot", text_color=C["orange"])
            self._auto_fill_blanks()
            self._set_progress(1.0)
            self._set_status(f"Mapped {mapped}/{len(paths)} media | Crop applies at final merge", C["green"])

        threading.Thread(target=_process_in_thread, daemon=True).start()

    # ── Final filters ──
    def _build_logo_filter(self, vw, vh):
        if not self.use_logo_var.get() or not self.logo_pil: return None
        if not os.path.exists(self.logo_processed_path): return None
        sz = self.settings.get("logo_size", 80)
        opa = self.settings.get("logo_opacity", 100) / 100.0
        x = max(0, min(int(self.settings.get("logo_pos_x", 20)), max(0, vw - sz)))
        y = max(0, min(int(self.settings.get("logo_pos_y", 20)), max(0, vh - sz)))
        if opa < 1.0:
            return (f"[1:v]scale={sz}:{sz},format=rgba,"
                    f"colorchannelmixer=aa={opa:.2f}[logo];"
                    f"[0:v][logo]overlay={x}:{y}[vout]")
        return (f"[1:v]scale={sz}:{sz}[logo];[0:v][logo]overlay={x}:{y}[vout]")

    def _build_merge_video_filter(self, src_w, src_h, target_w, target_h):
        if self.auto_crop_var.get():
            crop_right = max(0, int(self.crop_right_var.get()))
            crop_bottom = max(0, int(self.crop_bottom_var.get()))
            keep_w = max(src_w - crop_right, 100)
            keep_h = max(src_h - crop_bottom, 100)
        else:
            keep_w, keep_h = src_w, src_h
        return (
            f"crop={keep_w}:{keep_h}:0:0,"
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black,"
            f"fps=30,format=yuv420p,setsar=1"
        )

    # ══════════════════════════════════════════════════════════
    # TTS + scene compose worker (per-block)
    # ══════════════════════════════════════════════════════════
    def _gen_worker(self, idx):
        block = self.blocks[idx]; num = block["num"]; text = block["text"]
        def _set_block_status(t, color):
            self.after(0, lambda: block["status_label"].configure(text=t, text_color=color))

        audio_source = self.audio_source_var.get()

        # ── Determine audio path ──
        audio_path = None

        if audio_source == "bulk_upload":
            existing = block.get("tts_audio", "")
            if existing and os.path.exists(existing):
                audio_path = existing
                _set_block_status(f"Using uploaded audio ({format_duration(get_duration(audio_path))})", C["orange"])
            else:
                _set_block_status("No audio mapped! Upload audio first.", C["red"])
                return
        else:
            # ElevenLabs TTS — CHECK CACHE FIRST to save credits!
            cached_audio = TTSCache.get_cached_audio(num, text)
            if cached_audio:
                # Text unchanged + audio file exists → reuse, ZERO credits spent
                audio_path = cached_audio
                block["tts_audio"] = audio_path
                dur_str = format_duration(get_duration(audio_path))
                _set_block_status(f"♻ Reusing cached TTS ({dur_str}) — 0 credits", C["green"])
            else:
                # Need to call ElevenLabs
                _set_block_status("Generating TTS…", C["orange"])
                api_key = self.api_entry.get().strip()
                if not api_key:
                    _set_block_status("No API key!", C["red"]); return

                voice_name = self.voice_var.get(); voice_id = None
                for vn, vid in self.voice_list_full:
                    if vn == voice_name: voice_id = vid; break
                if not voice_id:
                    _set_block_status("No voice!", C["red"]); return

                model_name = self.model_var.get(); model_id = None
                for m in self.models:
                    if m["name"] == model_name: model_id = m["model_id"]; break
                if not model_id: model_id = "eleven_multilingual_v2"

                raw_audio_path = os.path.join(TEMP_DIR, f"tts_{num}_raw.mp3")
                last_err = None
                payload = {
                    "text": text,
                    "model_id": model_id,
                    "voice_settings": {
                        "stability": 0.82,
                        "similarity_boost": 0.75,
                        "style": 0.0,
                        "use_speaker_boost": True,
                    },
                }
                from ai33_api import ai33_tts_generate
                if ai33_tts_generate(text=combined_script, voice_id=voice_id, api_key=api_key, out_path=raw_audio_path):
                    if os.path.exists(raw_audio_path) and get_duration(raw_audio_path) > 0.3:
                        last_err = None
                    else:
                        last_err = "Received incomplete TTS audio"
                else:
                    last_err = "AI33Pro TTS generation failed"
                if last_err:
                    _set_block_status(f"TTS fail: {last_err}", C["red"]); return

                _set_block_status("Cleaning voice…", C["orange"])
                pad = max(0.0, float(self.silence_var.get()))
                cleaned_audio_path = os.path.join(TEMP_DIR, f"tts_{num}_clean.wav")
                audio_path = clean_tts_audio(raw_audio_path, cleaned_audio_path, pad_sec=pad) or raw_audio_path
                block["tts_audio"] = audio_path

                # Save to cache for future reuse
                TTSCache.store(num, text, audio_path)

        total_audio = get_duration(audio_path)
        if total_audio <= 0.1:
            _set_block_status("Audio invalid!", C["red"]); return

        _set_block_status("Composing scene…", C["orange"])

        media_path = block.get("source_media", "")
        media_type = block.get("media_type", "")
        zoom_speed = block.get("zoom_speed", 0.0015)
        try:
            zoom_speed = float(block.get("zoom_speed_var", ctk.DoubleVar(value=0.0015)).get())
        except:
            zoom_speed = 0.0015

        vid_path = None

        # ── CASE 1: IMAGE SOURCE → zoom-in Ken Burns effect ──
        if media_type == "image" and media_path and os.path.exists(media_path):
            _set_block_status(f"Image → Zoom-in video (speed={zoom_speed:.4f})…", C["orange"])
            zoom_vid_path = os.path.join(TEMP_DIR, f"img_zoom_{num}.mp4")
            result = image_to_video_with_zoom(
                media_path, total_audio, zoom_vid_path,
                zoom_speed=zoom_speed, out_w=1920, out_h=1080
            )
            if result and os.path.exists(result):
                vid_path = result
            else:
                _set_block_status("Image zoom failed, using black filler", C["orange"])
                vid_path = os.path.join(TEMP_DIR, f"black_{num}.mp4")
                generate_black_video(total_audio, output=vid_path)

        # ── CASE 2: VIDEO SOURCE ──
        elif media_type == "video" and media_path and os.path.exists(media_path):
            vid_path = media_path
            vid_dur = get_duration(vid_path)
            extend_mode = block.get("video_extend_mode", "reverse")
            try:
                extend_mode = block["extend_mode_var"].get()
            except:
                pass

            if vid_dur > total_audio + 0.05:
                _set_block_status("Trimming video…", C["orange"])
                trimmed_vid = os.path.join(TEMP_DIR, f"trimmed_{num}.mp4")
                subprocess.run(["ffmpeg", "-y", "-i", vid_path, "-t", str(total_audio),
                    "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                    "-c:a", "aac", "-b:a", "192k", trimmed_vid],
                    capture_output=True, text=True, timeout=300)
                if os.path.exists(trimmed_vid):
                    vid_path = trimmed_vid

            elif vid_dur > 0 and vid_dur < total_audio - 0.05:
                # Video is shorter than audio — need to extend
                if extend_mode == "freeze_zoom":
                    # ── FREEZE LAST FRAME + SLOW ZOOM ──
                    _set_block_status("Extending (freeze+zoom last frame)…", C["orange"])
                    freeze_dur = total_audio - vid_dur
                    freeze_vid = os.path.join(TEMP_DIR, f"freeze_zoom_{num}.mp4")
                    built = freeze_last_frame_zoom_video(
                        vid_path, freeze_dur, freeze_vid,
                        zoom_speed=max(0.0003, zoom_speed * 0.7),  # slightly slower for freeze
                        out_w=1920, out_h=1080
                    )
                    if built and os.path.exists(built):
                        vid_path = built
                    else:
                        _set_block_status("Freeze-zoom failed, falling back to ping-pong…", C["orange"])
                        pingpong_vid = os.path.join(TEMP_DIR, f"pingpong_{num}.mp4")
                        built = build_pingpong_video(vid_path, total_audio, pingpong_vid)
                        if built and os.path.exists(built):
                            vid_path = built
                else:
                    # ── REVERSE (PING-PONG) — default ──
                    _set_block_status("Extending (ping-pong)…", C["orange"])
                    pingpong_vid = os.path.join(TEMP_DIR, f"pingpong_{num}.mp4")
                    built = build_pingpong_video(vid_path, total_audio, pingpong_vid)
                    if built and os.path.exists(built):
                        vid_path = built

        # ── CASE 3: NO MEDIA → black video ──
        else:
            _set_block_status("Creating blank…", C["orange"])
            vid_path = os.path.join(TEMP_DIR, f"black_{num}.mp4")
            generate_black_video(total_audio, output=vid_path)

        if not vid_path or not os.path.exists(vid_path):
            _set_block_status("No video created!", C["red"]); return

        output_path = os.path.join(TEMP_DIR, f"output_{num}.mp4")
        keep_audio = block["keep_audio_var"].get()

        cmd = ["ffmpeg", "-y", "-i", vid_path, "-i", audio_path]
        filters = []; map_v = "0:v"; map_a = "1:a"
        if keep_audio and has_audio_stream(vid_path):
            filters.append("[0:a][1:a]amix=inputs=2:duration=longest[aout]")
            map_a = "[aout]"
        if filters: cmd.extend(["-filter_complex", ";".join(filters)])
        cmd.extend(["-map", map_v, "-map", map_a, "-t", str(total_audio),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k", output_path])

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if res.returncode != 0:
                print(f"FFmpeg err: {res.stderr[-500:]}")
                fb = ["ffmpeg", "-y", "-i", vid_path, "-i", audio_path,
                    "-map", "0:v", "-map", "1:a", "-t", str(total_audio),
                    "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                    "-c:a", "aac", "-b:a", "192k", output_path]
                subprocess.run(fb, capture_output=True, timeout=300)
        except Exception as e:
            _set_block_status(f"FFmpeg error: {e}", C["red"]); return

        if os.path.exists(output_path):
            block["output"] = output_path; dur = get_duration(output_path)
            mtype_tag = "IMG" if media_type == "image" else ("VID" if media_type == "video" else "BLK")
            _set_block_status(f"Done [{mtype_tag}] ({dur:.1f}s)", C["green"])
        else:
            _set_block_status("Output missing!", C["red"])

    def _generate_single(self, idx):
        if idx < 0 or idx >= len(self.blocks): return
        threading.Thread(target=self._gen_worker, args=(idx,), daemon=True).start()

    def _collect_missing_scene_indexes(self):
        return [i for i, b in enumerate(self.blocks)
                if not (b.get("output") and os.path.exists(b.get("output", "")))]

    # Parallel TTS + scene composition
    def _generate_blocks_parallel(self, indexes, progress_start=0.0, progress_end=1.0,
                                  stage_label="Generating scenes"):
        indexes = [i for i in indexes if 0 <= i < len(self.blocks)]
        total = len(indexes)
        if total == 0:
            return 0
        workers = min(MAX_PARALLEL_TTS, max(1, total))
        done_counter = {"n": 0}
        self._set_status(f"{stage_label}… 0/{total} (parallel x{workers})", C["orange"])
        self._set_substatus(f"0/{total} completed")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            fut_map = {ex.submit(self._gen_worker, i): i for i in indexes}
            for fut in as_completed(fut_map):
                idx = fut_map[fut]
                try:
                    fut.result()
                except Exception as e:
                    try:
                        self.after(0, lambda ee=e, b=self.blocks[idx]: b["status_label"].configure(
                            text=f"Error: {ee}", text_color=C["red"]))
                    except:
                        pass
                with self._progress_lock:
                    done_counter["n"] += 1
                    done = done_counter["n"]
                frac = progress_start + ((progress_end - progress_start) * (done / total))
                self._set_progress(frac)
                self._set_status(f"{stage_label}… {done}/{total} (parallel x{workers})", C["orange"])
                self._set_substatus(f"{done}/{total} completed")
        ready = sum(1 for i in indexes if self.blocks[i].get("output") and os.path.exists(self.blocks[i]["output"]))
        return ready

    def _generate_all(self):
        if not self.blocks: messagebox.showwarning("Blocks", "No scenes."); return
        if not self._confirm_generate_start(): return
        threading.Thread(target=self._gen_all_worker, daemon=True).start()

    def _gen_all_worker(self):
        total = len(self.blocks)
        done = self._generate_blocks_parallel(list(range(total)), 0.0, 1.0, "Bulk generating scenes")
        self._set_progress(1.0)
        self._set_status(f"Done: {done}/{total} generated", C["green"])
        self._set_substatus("")

    def _generate_pending_only(self):
        """Generate ONLY scenes that have no output yet — skips already-done scenes."""
        if not self.blocks: messagebox.showwarning("Blocks", "No scenes."); return
        pending = self._collect_missing_scene_indexes()
        if not pending:
            messagebox.showinfo("Gen Next", "All scenes already have output! Nothing to generate.")
            return
        already_done = len(self.blocks) - len(pending)
        msg = (
            f"Scenes with output: {already_done} (will be SKIPPED)\n"
            f"Scenes pending: {len(pending)} (will be generated)\n\n"
            f"TTS cache is active — previously generated voices\n"
            f"will be reused if text hasn't changed (0 credits).\n\n"
            f"Generate {len(pending)} pending scenes?"
        )
        if not messagebox.askyesno("Generate Pending", msg):
            return
        threading.Thread(target=self._gen_pending_worker, args=(pending,), daemon=True).start()

    def _gen_pending_worker(self, indexes):
        total = len(indexes)
        done = self._generate_blocks_parallel(indexes, 0.0, 1.0, f"Generating {total} pending scenes")
        self._set_progress(1.0)
        all_done = sum(1 for b in self.blocks if b.get("output") and os.path.exists(b.get("output", "")))
        self._set_status(f"Done: {done}/{total} generated | Total ready: {all_done}/{len(self.blocks)}", C["green"])
        self._set_substatus("")

    # ══════════════════════════════════════════════════════════
    # BUILD ORDERED CLIP LIST (intro at correct positions)
    # ══════════════════════════════════════════════════════════
    def _build_ordered_clip_list(self):
        use_intro = self.use_intro_var.get()
        intro_map = {}
        if use_intro:
            for entry in self.intro_entries:
                p = entry.get("path", "")
                bs = entry.get("before_scene", 1)
                if p and os.path.exists(p):
                    try: bs = max(1, int(bs))
                    except: bs = 1
                    intro_map.setdefault(bs, []).append(p)

        ordered = []
        main_scene_indexes = []

        for i, b in enumerate(self.blocks):
            scene_num = i + 1
            if scene_num in intro_map:
                for ip in intro_map[scene_num]:
                    ordered.append(("intro", ip))
            op = b.get("output", "")
            if op and os.path.exists(op):
                idx_in_ordered = len(ordered)
                main_scene_indexes.append(idx_in_ordered)
                ordered.append(("scene", op))

        total_scenes = len(self.blocks)
        for bs, paths in intro_map.items():
            if bs > total_scenes:
                for ip in paths:
                    ordered.append(("intro", ip))

        return ordered, main_scene_indexes

    # ══════════════════════════════════════════════════════════
    # MERGE PIPELINE
    # ══════════════════════════════════════════════════════════
    def _normalize_clip_for_merge(self, clip, idx, tw, th, clip_type="scene"):
        w, h = get_resolution(clip)
        vf = self._build_merge_video_filter(w, h, tw, th)
        norm = os.path.join(TEMP_DIR, f"norm_{idx}.mp4")

        # For SCENE clips only: apply chroma overlay + logo
        inputs = ["-i", clip]
        extra_input_count = 0

        use_chroma = (clip_type == "scene" and self.use_chroma_overlay_var.get()
                      and self.chroma_overlay_path and os.path.exists(self.chroma_overlay_path))
        use_logo_here = (clip_type == "scene" and self.use_logo_var.get()
                         and self.logo_pil and os.path.exists(self.logo_processed_path))

        if use_chroma:
            inputs.extend(["-stream_loop", "-1", "-i", self.chroma_overlay_path])
            extra_input_count += 1
        if use_logo_here:
            inputs.extend(["-i", self.logo_processed_path])
            extra_input_count += 1

        # Build complex filter chain
        fc_parts = []
        current_label = "[0:v]"

        # Step A: crop/scale/pad the main clip
        fc_parts.append(f"{current_label}{vf}[base]")
        current_label = "[base]"

        # Step B: chroma key overlay (if enabled for scenes)
        if use_chroma:
            chroma_idx = 1  # second input
            hex_color = self._get_chroma_hex()
            sim = self.chroma_sim_var.get()
            blend = self.chroma_blend_var.get()
            fc_parts.append(
                f"[{chroma_idx}:v]scale={tw}:{th},format=yuva420p,"
                f"chromakey=0x{hex_color}:similarity={sim:.2f}:blend={blend:.2f}[chroma]"
            )
            fc_parts.append(f"{current_label}[chroma]overlay=0:0:shortest=1[chromed]")
            current_label = "[chromed]"

        # Step C: logo overlay (if enabled for scenes)
        if use_logo_here:
            logo_input_idx = 1 + (1 if use_chroma else 0)
            sz = self.settings.get("logo_size", 80)
            opa = self.settings.get("logo_opacity", 100) / 100.0
            x = max(0, min(int(self.settings.get("logo_pos_x", 20)), max(0, tw - sz)))
            y = max(0, min(int(self.settings.get("logo_pos_y", 20)), max(0, th - sz)))
            if opa < 1.0:
                fc_parts.append(
                    f"[{logo_input_idx}:v]scale={sz}:{sz},format=rgba,"
                    f"colorchannelmixer=aa={opa:.2f}[logo]"
                )
            else:
                fc_parts.append(f"[{logo_input_idx}:v]scale={sz}:{sz}[logo]")
            fc_parts.append(f"{current_label}[logo]overlay={x}:{y}[logoed]")
            current_label = "[logoed]"

        # Determine output
        if fc_parts:
            # Rename last label to [vout]
            last_part = fc_parts[-1]
            # Find and replace the final label
            final_label = current_label.strip("[]")
            fc_parts[-1] = last_part.rsplit(f"[{final_label}]", 1)[0] + "[vout]"
            fc_str = ";".join(fc_parts)
            cmd = (["ffmpeg", "-y"] + inputs +
                   ["-filter_complex", fc_str,
                    "-map", "[vout]", "-map", "0:a?",
                    "-af", "aresample=48000:async=1:first_pts=0",
                    "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", norm])
        else:
            cmd = ["ffmpeg", "-y", "-i", clip, "-vf", vf,
                   "-af", "aresample=48000:async=1:first_pts=0",
                   "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                   "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", norm]

        subprocess.run(cmd, capture_output=True, timeout=600)
        return idx, (norm if os.path.exists(norm) else clip)

    def _concat_copy(self, clip_paths, output_path):
        if not clip_paths: return None
        list_path = output_path + ".list.txt"
        with open(list_path, "w", encoding="utf-8") as f:
            for c in clip_paths:
                f.write(f"file '{os.path.abspath(c)}'\n")
        r = subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
            "-c", "copy", "-movflags", "+faststart", output_path],
            capture_output=True, text=True, timeout=900)
        if os.path.exists(output_path) and get_duration(output_path) > 0.1:
            return output_path
        subprocess.run(["ffmpeg", "-y", "-fflags", "+genpts", "-f", "concat", "-safe", "0", "-i", list_path,
            "-vsync", "cfr", "-r", "30",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", output_path],
            capture_output=True, text=True, timeout=900)
        return output_path if os.path.exists(output_path) else None

    def _concat_with_transitions(self, clip_paths, output_path, fade_dur=0.5):
        """Concat clips with xfade crossfade transitions between each pair."""
        if not clip_paths: return None
        if len(clip_paths) == 1:
            shutil.copy2(clip_paths[0], output_path)
            return output_path if os.path.exists(output_path) else None

        fade_dur = max(0.05, min(float(fade_dur), 2.0))

        # Get durations
        durations = []
        for c in clip_paths:
            d = get_duration(c)
            durations.append(max(0.5, d))

        # Build xfade chain: pair-wise transitions
        # For N clips we need N-1 xfade filters
        n = len(clip_paths)
        inputs = []
        for c in clip_paths:
            inputs.extend(["-i", c])

        fc_parts = []
        af_parts = []
        # Calculate offsets: each xfade starts at (cumulative_duration - fade_dur)
        cumulative = durations[0]

        for i in range(1, n):
            offset = max(0.01, cumulative - fade_dur)
            in_a = f"[tmp{i-1}]" if i > 1 else "[0:v]"
            in_b = f"[{i}:v]"
            out_label = f"[tmp{i}]" if i < n - 1 else "[vout]"
            fc_parts.append(f"{in_a}{in_b}xfade=transition=fade:duration={fade_dur:.3f}:offset={offset:.3f}{out_label}")

            # Audio crossfade
            ain_a = f"[atmp{i-1}]" if i > 1 else "[0:a]"
            ain_b = f"[{i}:a]"
            aout_label = f"[atmp{i}]" if i < n - 1 else "[aout]"
            af_parts.append(f"{ain_a}{ain_b}acrossfade=d={fade_dur:.3f}:c1=tri:c2=tri{aout_label}")

            cumulative = offset + durations[i]

        fc_str = ";".join(fc_parts + af_parts)

        cmd = (["ffmpeg", "-y"] + inputs +
               ["-filter_complex", fc_str,
                "-map", "[vout]", "-map", "[aout]",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", output_path])
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        except Exception as e:
            print(f"xfade concat failed: {e}")

        if os.path.exists(output_path) and get_duration(output_path) > 0.1:
            return output_path
        # Fallback to normal concat if xfade fails
        print("xfade failed, falling back to normal concat")
        return self._concat_copy(clip_paths, output_path)

    def _stream_loop_copy(self, input_path, loop_count, output_path):
        if loop_count <= 1:
            shutil.copy2(input_path, output_path)
            return output_path if os.path.exists(output_path) else None
        extra = max(0, int(loop_count) - 1)
        r = subprocess.run(
            ["ffmpeg", "-y", "-stream_loop", str(extra), "-i", input_path,
             "-c", "copy", "-movflags", "+faststart", output_path],
            capture_output=True, text=True, timeout=1800)
        if os.path.exists(output_path) and get_duration(output_path) > 0.1:
            return output_path
        list_path = output_path + ".loop_list.txt"
        with open(list_path, "w", encoding="utf-8") as f:
            for _ in range(int(loop_count)):
                f.write(f"file '{os.path.abspath(input_path)}'\n")
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
            "-c", "copy", "-movflags", "+faststart", output_path],
            capture_output=True, text=True, timeout=1800)
        return output_path if os.path.exists(output_path) else None

    def _merge_final(self):
        if not self.blocks and not self.intro_entries:
            messagebox.showwarning("Merge", "No scenes or intro clips available."); return
        sp = filedialog.asksaveasfilename(defaultextension=".mp4", filetypes=[("MP4", "*.mp4")],
            initialdir=self.settings.get("last_save_dir", ""))
        if not sp: return
        self.settings["last_save_dir"] = os.path.dirname(sp)
        threading.Thread(target=self._prepare_and_merge_worker, args=(sp,), daemon=True).start()

    def _prepare_and_merge_worker(self, save_path):
        missing = self._collect_missing_scene_indexes()
        if missing:
            self._set_status(f"Step 1/7: Auto-generating {len(missing)} missing scenes in parallel…", C["orange"])
            self._set_progress(0.02)
            self._generate_blocks_parallel(missing, 0.02, 0.35, "Step 1/7: Auto-generating scenes")
        else:
            self._set_progress(0.12)
            self._set_status("Step 1/7: All scene outputs already available", C["green"])

        ordered, main_scene_indexes = self._build_ordered_clip_list()
        if not ordered:
            self._set_status("Merge failed: no clips available", C["red"])
            return

        all_clip_paths = [item[1] for item in ordered]
        loop_count = self.loop_var.get() if self.render_mode_var.get() == "loop" else 1
        try: loop_count = max(1, int(loop_count))
        except: loop_count = 1

        if not self._confirm_merge_start(all_clip_paths, loop_count):
            self._set_status("Merge cancelled", C["orange"])
            return

        self._merge_worker(ordered, main_scene_indexes, loop_count, save_path)

    def _merge_worker(self, ordered, main_scene_indexes, loop_count, save_path):
        all_clip_paths = [item[1] for item in ordered]
        all_clip_types = [item[0] for item in ordered]  # "scene" or "intro"

        # ── Step 2: detect target resolution ──
        self._set_status("Step 2/7: Detecting target resolution…", C["orange"])
        self._set_substatus("probing clips")
        self._set_progress(0.38)
        tw, th = 1920, 1080
        for b in self.blocks:
            if b.get("output") and os.path.exists(b["output"]):
                tw, th = get_resolution(b["output"]); break

        # ── Step 3: normalize ALL clips in parallel (logo+chroma on scenes only) ──
        logo_on = self.use_logo_var.get() and self.logo_pil and os.path.exists(self.logo_processed_path)
        chroma_on = (self.use_chroma_overlay_var.get() and self.chroma_overlay_path
                     and os.path.exists(self.chroma_overlay_path))
        extra_info = []
        if logo_on: extra_info.append("logo")
        if chroma_on: extra_info.append("chroma")
        extra_str = f" +{'+'.join(extra_info)}" if extra_info else ""
        self._set_status(f"Step 3/7: Normalizing {len(all_clip_paths)} clips{extra_str} (parallel x{MAX_PARALLEL_FF})…", C["orange"])
        self._set_progress(0.40)
        normalized = [None] * len(all_clip_paths)
        workers = min(MAX_PARALLEL_FF, max(1, len(all_clip_paths)))
        done_norm = {"n": 0}
        with ThreadPoolExecutor(max_workers=workers) as ex:
            fut_map = {ex.submit(self._normalize_clip_for_merge, clip, i, tw, th, ctype): i
                       for i, (clip, ctype) in enumerate(zip(all_clip_paths, all_clip_types))}
            for fut in as_completed(fut_map):
                idx, out_path = fut.result()
                normalized[idx] = out_path
                with self._progress_lock:
                    done_norm["n"] += 1
                    n = done_norm["n"]
                frac = 0.40 + (0.18 * n / max(1, len(all_clip_paths)))
                self._set_progress(frac)
                self._set_status(f"Step 3/7: Normalizing {n}/{len(all_clip_paths)}{extra_str}…", C["orange"])
                self._set_substatus(f"{n}/{len(all_clip_paths)} clips ready")

        # Determine which concat method to use
        use_transitions = self.use_transition_var.get()
        fade_dur = max(0.05, min(float(self.transition_dur_var.get()), 2.0))

        def _do_concat(clips, out_path):
            if use_transitions and len(clips) > 1:
                return self._concat_with_transitions(clips, out_path, fade_dur)
            return self._concat_copy(clips, out_path)

        # ── Step 4: If loop mode, separate intro clips from main scene clips ──
        self._set_status("Step 4/7: Joining clips…", C["orange"])
        self._set_progress(0.60)

        if loop_count > 1:
            intro_clip_indexes = set(range(len(ordered))) - set(main_scene_indexes)

            full_once_path = os.path.join(TEMP_DIR, "full_once.mp4")
            full_once = _do_concat(normalized, full_once_path)
            if not full_once:
                self._set_status("Step 4/7 failed: cannot join clips", C["red"]); return

            main_norm = [normalized[i] for i in main_scene_indexes]
            if main_norm:
                main_once_path = os.path.join(TEMP_DIR, "main_once.mp4")
                main_once = _do_concat(main_norm, main_once_path)
                if not main_once:
                    self._set_status("Step 4/7 failed: cannot join main clips", C["red"]); return
            else:
                main_once = None

            self._set_substatus(f"full_once → {format_duration(get_duration(full_once))}")
            self._set_progress(0.68)

            # ── Step 5: loop main_once ──
            self._set_status(f"Step 5/7: Looping MAIN x{loop_count} via fast stream copy…", C["orange"])
            if main_once and loop_count > 1:
                main_extra_path = os.path.join(TEMP_DIR, "main_extra_loops.mp4")
                extra_loops = self._stream_loop_copy(main_once, loop_count - 1, main_extra_path)
                if extra_loops:
                    self._set_substatus(f"main_extra → {format_duration(get_duration(extra_loops))}")
                else:
                    extra_loops = None
            else:
                extra_loops = None
            self._set_progress(0.76)

            # ── Step 6: join full_once + extra main loops ──
            self._set_status("Step 6/7: Joining full + looped main (fast copy)…", C["orange"])
            final_joined = os.path.join(TEMP_DIR, "final_joined.mp4")
            parts = [full_once]
            if extra_loops:
                parts.append(extra_loops)
            if len(parts) == 1:
                shutil.copy2(parts[0], final_joined)
                final = final_joined
            else:
                final = self._concat_copy(parts, final_joined)
                if not final:
                    self._set_status("Step 6/7 failed: cannot join", C["red"]); return
        else:
            final_joined = os.path.join(TEMP_DIR, "final_joined.mp4")
            final = _do_concat(normalized, final_joined)
            if not final:
                self._set_status("Step 4/7 failed: cannot join clips", C["red"]); return
            self._set_progress(0.76)

        self._set_substatus(f"joined → {format_duration(get_duration(final))}")
        self._set_progress(0.82)

        # ── Step 7: BGM ──
        if self.use_bgm_var.get():
            bgm_mode = self.bgm_mode_var.get()
            if bgm_mode == "single" and self.bgm_path and os.path.exists(self.bgm_path):
                final = self._apply_single_bgm(final)
            elif bgm_mode == "multiple" and self.bgm_multi_entries:
                final = self._apply_multi_bgm(final)
            else:
                self._set_substatus("BGM skipped (no file)")
        else:
            self._set_substatus("BGM skipped")
        self._set_progress(0.95)

        # Logo is now applied per-clip during normalization (Step 3)
        # No separate logo step needed — this fixes the "missing on some clips" bug

        # ── Save final ──
        self._set_status("Saving final video…", C["orange"])
        self._set_substatus("writing to disk")
        try: shutil.copy2(final, save_path)
        except Exception as e:
            self._set_status(f"Save failed: {e}", C["red"]); return
        _finalize_output_resolution(save_path, log=self._set_substatus)

        dur = get_duration(save_path); self._set_progress(1.0)
        self._set_status(
            f"✓ Saved! {format_duration(dur)} → {os.path.basename(save_path)}", C["green"])
        self._set_substatus("done")

        # cleanup temp normalized clips
        for f in normalized:
            if f and TEMP_DIR in f and os.path.exists(f):
                try: os.remove(f)
                except: pass

    # ══════════════════════════════════════════════════════════
    # SINGLE BGM APPLICATION
    # ══════════════════════════════════════════════════════════
    def _apply_single_bgm(self, video_path):
        self._set_status("Step 7/7: Adding background music (single)…", C["orange"])
        self._set_substatus("mixing BGM")
        bgm_out = os.path.join(TEMP_DIR, "merged_bgm.mp4")
        vol = self.bgm_vol_var.get()
        fade = self.bgm_fade_var.get()
        vdur = get_duration(video_path)
        if self.bgm_duck_var.get():
            af = (f"[0:a]volume=1.0[main];"
                  f"[1:a]volume={vol},afade=t=in:st=0:d=2,"
                  f"afade=t=out:st={max(0,vdur-fade)}:d={fade},aresample=48000[bg];"
                  f"[main][bg]amix=inputs=2:duration=first:dropout_transition=3:weights='1 0.60'[aout]")
        else:
            af = (f"[0:a]volume=1.0[main];"
                  f"[1:a]volume={vol},afade=t=in:st=0:d=2,"
                  f"afade=t=out:st={max(0,vdur-fade)}:d={fade},aresample=48000[bg];"
                  f"[main][bg]amix=inputs=2:duration=first:dropout_transition=3[aout]")
        subprocess.run(["ffmpeg", "-y", "-i", video_path, "-stream_loop", "-1", "-i", self.bgm_path,
            "-filter_complex", af, "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", bgm_out],
            capture_output=True, timeout=1200)
        if os.path.exists(bgm_out):
            return bgm_out
        return video_path

    # ══════════════════════════════════════════════════════════
    # MULTIPLE BGM APPLICATION (scene ranges with crossfade)
    # ══════════════════════════════════════════════════════════
    def _apply_multi_bgm(self, video_path):
        self._set_status("Step 7/7: Adding multiple BGM tracks with crossfade…", C["orange"])
        self._set_substatus("computing scene timestamps")

        scene_start_times = []
        cumulative = 0.0
        for b in self.blocks:
            scene_start_times.append(cumulative)
            op = b.get("output", "")
            if op and os.path.exists(op):
                cumulative += get_duration(op)
            else:
                cumulative += 3.0
        total_video_dur = get_duration(video_path)

        use_intro = self.use_intro_var.get()
        intro_map = {}
        if use_intro:
            for entry in self.intro_entries:
                p = entry.get("path", "")
                bs = entry.get("before_scene", 1)
                if p and os.path.exists(p):
                    try: bs = max(1, int(bs))
                    except: bs = 1
                    intro_map.setdefault(bs, []).append(p)

        actual_scene_starts = []
        timeline_pos = 0.0
        for i, b in enumerate(self.blocks):
            scene_num = i + 1
            if scene_num in intro_map:
                for ip in intro_map[scene_num]:
                    timeline_pos += get_duration(ip)
            actual_scene_starts.append(timeline_pos)
            op = b.get("output", "")
            if op and os.path.exists(op):
                timeline_pos += get_duration(op)
            else:
                timeline_pos += 3.0

        total_scenes = len(self.blocks)
        for bs, paths in intro_map.items():
            if bs > total_scenes:
                for ip in paths:
                    timeline_pos += get_duration(ip)

        vol = self.bgm_vol_var.get()
        fade = max(0.1, float(self.bgm_fade_var.get()))
        duck = self.bgm_duck_var.get()

        valid_entries = []
        for entry in self.bgm_multi_entries:
            p = entry.get("path", "")
            if not p or not os.path.exists(p):
                continue
            fr = max(1, int(entry.get("from", 1)))
            to = max(fr, int(entry.get("to", len(self.blocks))))
            fr = min(fr, len(self.blocks))
            to = min(to, len(self.blocks))
            fr_idx = fr - 1
            to_idx = to - 1
            start_t = actual_scene_starts[fr_idx] if fr_idx < len(actual_scene_starts) else 0.0
            end_op = self.blocks[to_idx].get("output", "") if to_idx < len(self.blocks) else ""
            if end_op and os.path.exists(end_op):
                end_t = actual_scene_starts[to_idx] + get_duration(end_op) if to_idx < len(actual_scene_starts) else total_video_dur
            else:
                end_t = actual_scene_starts[to_idx] + 3.0 if to_idx < len(actual_scene_starts) else total_video_dur
            end_t = min(end_t, total_video_dur)
            segment_dur = max(0.5, end_t - start_t)
            valid_entries.append({
                "path": p,
                "start": start_t,
                "end": end_t,
                "dur": segment_dur,
                "from": fr,
                "to": to,
            })

        if not valid_entries:
            self._set_substatus("no valid BGM tracks")
            return video_path

        current = video_path
        for bi, bgm_entry in enumerate(valid_entries):
            self._set_substatus(f"mixing BGM track {bi+1}/{len(valid_entries)} (scene {bgm_entry['from']}-{bgm_entry['to']})")
            bgm_out = os.path.join(TEMP_DIR, f"merged_multi_bgm_{bi}.mp4")
            bgm_path = bgm_entry["path"]
            start_t = bgm_entry["start"]
            end_t = bgm_entry["end"]
            seg_dur = bgm_entry["dur"]

            fade_in_dur = min(fade, seg_dur * 0.3)
            fade_out_start = max(0, seg_dur - fade)
            fade_out_dur = min(fade, seg_dur * 0.3)
            delay_ms = int(start_t * 1000)

            if duck:
                af = (
                    f"[0:a]volume=1.0[main];"
                    f"[1:a]volume={vol},"
                    f"atrim=0:{seg_dur:.3f},"
                    f"afade=t=in:st=0:d={fade_in_dur:.3f},"
                    f"afade=t=out:st={fade_out_start:.3f}:d={fade_out_dur:.3f},"
                    f"aresample=48000,"
                    f"adelay={delay_ms}|{delay_ms},"
                    f"apad=whole_dur={get_duration(current):.3f}[bg];"
                    f"[main][bg]amix=inputs=2:duration=first:dropout_transition=3:weights='1 0.60'[aout]"
                )
            else:
                af = (
                    f"[0:a]volume=1.0[main];"
                    f"[1:a]volume={vol},"
                    f"atrim=0:{seg_dur:.3f},"
                    f"afade=t=in:st=0:d={fade_in_dur:.3f},"
                    f"afade=t=out:st={fade_out_start:.3f}:d={fade_out_dur:.3f},"
                    f"aresample=48000,"
                    f"adelay={delay_ms}|{delay_ms},"
                    f"apad=whole_dur={get_duration(current):.3f}[bg];"
                    f"[main][bg]amix=inputs=2:duration=first:dropout_transition=3[aout]"
                )

            subprocess.run([
                "ffmpeg", "-y",
                "-i", current,
                "-stream_loop", "-1", "-i", bgm_path,
                "-filter_complex", af,
                "-map", "0:v", "-map", "[aout]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                bgm_out
            ], capture_output=True, timeout=1200)

            if os.path.exists(bgm_out) and get_duration(bgm_out) > 0.1:
                current = bgm_out
            else:
                print(f"Warning: multi BGM track {bi+1} failed to apply")

        self._set_substatus(f"all {len(valid_entries)} BGM tracks applied")
        return current

    # ══════════════════════════════════════════════════════════



class NewsEditorFrame(ctk.CTkFrame):
    """Embedded News Editor — GPU accelerated."""
    def __init__(self, master):
        super().__init__(master, fg_color=C["bg"])
        self.settings=SettingsManager.load(); self._build_ui()
    def _build_ui(self):
        self.grid_columnconfigure(0,weight=1); self.grid_rowconfigure(1,weight=1)
        top=ctk.CTkFrame(self,fg_color=C["card"]); top.grid(row=0,column=0,sticky="ew",padx=8,pady=(8,4))
        ctk.CTkLabel(top,text=f"█  NEWS TICKER EDITOR  |  {GPU.info_str()}",text_color=C["red"],font=("Segoe UI",16,"bold")).pack(anchor="w",padx=12,pady=8)
        mid=ctk.CTkScrollableFrame(self,fg_color=C["bg"]); mid.grid(row=1,column=0,sticky="nsew",padx=8,pady=4); mid.grid_columnconfigure(0,weight=1)
        def nc(p,t):
            f=ctk.CTkFrame(p,fg_color=C["card"],border_color=C["border"],border_width=1,corner_radius=8)
            ctk.CTkLabel(f,text=f"█  {t.upper()}",text_color=C["red"],font=("Segoe UI",13,"bold")).pack(anchor="w",padx=8,pady=(5,2)); return f
        h=nc(mid,"Headlines"); h.grid(row=0,column=0,sticky="ew",padx=5,pady=4)
        ctk.CTkLabel(h,text="Separate with | pipe",text_color=C["dim"],font=("Segoe UI",10)).pack(anchor="w",padx=8)
        self.n_text=ctk.CTkTextbox(h,height=80,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"],border_width=1,font=("Consolas",11))
        self.n_text.pack(fill="x",padx=8,pady=(0,8))
        sv=self.settings.get("ticker_text","")
        if sv: self.n_text.insert("1.0",sv)
        lc=nc(mid,"Label & Colors"); lc.grid(row=1,column=0,sticky="ew",padx=5,pady=4)
        r1=ctk.CTkFrame(lc,fg_color="transparent"); r1.pack(fill="x",padx=8,pady=3)
        self.n_lshow=ctk.BooleanVar(value=self.settings.get("ticker_label_show",True))
        ctk.CTkCheckBox(r1,text="Label:",variable=self.n_lshow,text_color=C["text"],fg_color=C["red"]).pack(side="left",padx=(0,5))
        self.n_ltxt=ctk.StringVar(value=self.settings.get("ticker_label_text","BREAKING"))
        ctk.CTkEntry(r1,textvariable=self.n_ltxt,width=100,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"]).pack(side="left",padx=3)
        ctk.CTkLabel(r1,text="LabelBG:",text_color=C["dim"]).pack(side="left",padx=(10,3))
        self.n_lbg=ctk.StringVar(value=self.settings.get("ticker_label_bg","CC0000"))
        ctk.CTkEntry(r1,textvariable=self.n_lbg,width=70,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"]).pack(side="left",padx=3)
        r2=ctk.CTkFrame(lc,fg_color="transparent"); r2.pack(fill="x",padx=8,pady=3)
        ctk.CTkLabel(r2,text="Bar:",text_color=C["dim"]).pack(side="left")
        self.n_bc=ctk.StringVar(value=self.settings.get("ticker_bar_color","000000"))
        ctk.CTkEntry(r2,textvariable=self.n_bc,width=70,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"]).pack(side="left",padx=3)
        ctk.CTkLabel(r2,text="Text:",text_color=C["dim"]).pack(side="left",padx=(10,0))
        self.n_tc=ctk.StringVar(value=self.settings.get("ticker_text_color","FFFFFF"))
        ctk.CTkEntry(r2,textvariable=self.n_tc,width=70,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"]).pack(side="left",padx=3)
        ctk.CTkLabel(r2,text="Font:",text_color=C["dim"]).pack(side="left",padx=(10,0))
        self.n_fs=ctk.IntVar(value=self.settings.get("ticker_font_size",30))
        ctk.CTkEntry(r2,textvariable=self.n_fs,width=45,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"]).pack(side="left",padx=3)
        ac=nc(mid,"Animation"); ac.grid(row=2,column=0,sticky="ew",padx=5,pady=4)
        ar=ctk.CTkFrame(ac,fg_color="transparent"); ar.pack(fill="x",padx=8,pady=3)
        ctk.CTkLabel(ar,text="Speed:",text_color=C["dim"]).pack(side="left")
        self.n_sp=ctk.IntVar(value=self.settings.get("ticker_speed",80))
        ctk.CTkSlider(ar,from_=20,to=300,variable=self.n_sp,width=120).pack(side="left",padx=5)
        self.n_spl=ctk.CTkLabel(ar,text=str(self.n_sp.get()),text_color=C["text"],width=35); self.n_spl.pack(side="left")
        self.n_sp.trace_add("write",lambda*a:self.n_spl.configure(text=str(self.n_sp.get())))
        ctk.CTkLabel(ar,text="Height:",text_color=C["dim"]).pack(side="left",padx=(15,0))
        self.n_ht=ctk.IntVar(value=self.settings.get("ticker_bar_height",50))
        ctk.CTkEntry(ar,textvariable=self.n_ht,width=45,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"]).pack(side="left",padx=3)
        ctk.CTkLabel(ar,text="Opacity:",text_color=C["dim"]).pack(side="left",padx=(15,0))
        self.n_op=ctk.DoubleVar(value=self.settings.get("ticker_bar_opacity",0.75))
        ctk.CTkSlider(ar,from_=0.1,to=1.0,variable=self.n_op,width=80).pack(side="left",padx=5)
        self.n_opl=ctk.CTkLabel(ar,text=f"{int(self.n_op.get()*100)}%",text_color=C["text"],width=35); self.n_opl.pack(side="left")
        self.n_op.trace_add("write",lambda*a:self.n_opl.configure(text=f"{int(self.n_op.get()*100)}%"))
        pc=nc(mid,"Presets"); pc.grid(row=3,column=0,sticky="ew",padx=5,pady=4)
        pf=ctk.CTkFrame(pc,fg_color="transparent"); pf.pack(fill="x",padx=8,pady=5)
        for n,b,t,l,lb in [("Dark","000000","FFFFFF","BREAKING","CC0000"),("Red","8B0000","FFFFFF","ALERT","FF0000"),
            ("Blue","001133","00CCFF","NEWS","0055AA"),("Gold","1A1A00","FFD700","UPDATE","AA8800"),("Green","002200","00FF88","LIVE","006600")]:
            ctk.CTkButton(pf,text=n,width=70,height=28,fg_color=C["btn"],hover_color=C["accent"],text_color=C["text"],
                command=lambda b=b,t=t,l=l,lb=lb:(self.n_bc.set(b),self.n_tc.set(t),self.n_ltxt.set(l),self.n_lbg.set(lb))).pack(side="left",padx=4)
        vc=nc(mid,"Apply to Video"); vc.grid(row=4,column=0,sticky="ew",padx=5,pady=4)
        vf=ctk.CTkFrame(vc,fg_color="transparent"); vf.pack(fill="x",padx=8,pady=5)
        ctk.CTkButton(vf,text="Select Video",width=110,fg_color=C["accent"],text_color="#000",command=self._sel_vid).pack(side="left",padx=3)
        self.n_vl=ctk.CTkLabel(vf,text="No video",text_color=C["dim"],font=("Segoe UI",10)); self.n_vl.pack(side="left",padx=8); self.n_vp=""
        ef=ctk.CTkFrame(vc,fg_color="transparent"); ef.pack(fill="x",padx=8,pady=(0,8))
        ctk.CTkButton(ef,text="Apply & Export",width=180,height=36,fg_color=C["green"],text_color="#000",font=("Segoe UI",13,"bold"),command=self._export).pack(side="left",padx=3)
        self.n_st=ctk.CTkLabel(ef,text="Ready",text_color=C["dim"]); self.n_st.pack(side="left",padx=10)
    def _sel_vid(self):
        p=filedialog.askopenfilename(filetypes=[("Video","*.mp4 *.mov *.avi *.mkv")])
        if p: self.n_vp=p; self.n_vl.configure(text=f"{os.path.basename(p)} ({format_duration(get_duration(p))})")
    def _export(self):
        if not self.n_vp or not os.path.exists(self.n_vp): messagebox.showwarning("Video","Select video."); return
        tt=self.n_text.get("1.0","end").strip()
        if not tt: messagebox.showwarning("Text","Enter headlines."); return
        sp=filedialog.asksaveasfilename(defaultextension=".mp4",initialdir=OUTPUT_DIR,filetypes=[("MP4","*.mp4")])
        if not sp: return
        self.n_st.configure(text="Processing...",text_color=C["orange"])
        threading.Thread(target=self._ew,args=(sp,tt),daemon=True).start()
    def _ew(self,sp,tt):
        tw,th=get_resolution(self.n_vp)
        tf=build_ticker_drawtext_filter(tt,tw,th,self.n_bc.get().strip().lstrip("#")[:6],self.n_op.get(),max(20,int(self.n_ht.get())),
            self.n_tc.get().strip().lstrip("#")[:6],max(10,int(self.n_fs.get())),max(10,int(self.n_sp.get())),
            self.n_ltxt.get().strip(),self.n_lbg.get().strip().lstrip("#")[:6],self.n_lshow.get())
        if not tf: self.after(0,lambda:self.n_st.configure(text="Filter empty!",text_color=C["red"])); return
        cmd=["ffmpeg","-y","-i",self.n_vp,"-vf",tf]
        cmd+=GPU.enc_args("fast"); cmd+=["-c:a","copy",sp]
        try: _run_ff(cmd,timeout=1800)
        except Exception as e: self.after(0,lambda:self.n_st.configure(text=f"Error:{e}",text_color=C["red"])); return
        _finalize_output_resolution(sp)
        if os.path.exists(sp): self.after(0,lambda:self.n_st.configure(text=f"Exported! {format_duration(get_duration(sp))}",text_color=C["green"]))
        else: self.after(0,lambda:self.n_st.configure(text="Failed!",text_color=C["red"]))


# ════════════════════════════════════════════════════════════════
# ENTRY POINT FOR LAUNCHER
# ════════════════════════════════════════════════════════════════
# ════════════════════════════════════════════════════════════════════════════
# STORY VIDEO — freeze-frame EFFECTS engine + PRO CAPTION (ASS/karaoke) engine
# ════════════════════════════════════════════════════════════════════════════

# ---- 22 CapCut-style overlay effects (procedural, additive "screen" blend) ----
STORY_EFFECTS = [
    "None", "Rain Drop", "Blood Drop", "Snow", "Heavy Snow", "Rain", "Bokeh", "Gold Bokeh", "Sparkle",
    "Stars", "Embers", "Fireflies", "Hearts", "Confetti", "Dust", "Bubbles",
    "Petals", "Light Leak", "Glow Pulse", "Film Grain", "Gradient Sweep", "Lens Flare",
]

def _story_fx_params(effect):
    e = (effect or "").lower().strip()
    P = dict(kind="dot", n=140, smin=2, smax=5, vy=60, vx=10, sway=0.0,
             twinkle=False, blur=0, color=(255, 255, 255), palette=None, alpha=(120, 220))
    if e in ("rain drop", "raindrop", "rain_drop"):
        P.update(kind="raindrop", n=140, smin=4, smax=12, vy=680, vx=16, sway=0.4,
                 palette=[(245,250,255),(210,235,255),(185,215,250),(255,255,255)], alpha=(140,240))
    elif e in ("blood drop", "blood", "blooddrop", "blood ink", "blood_drop"):
        P.update(kind="blooddrop", n=90, smin=4, smax=14, vy=340, vx=10, sway=0.3,
                 palette=[(20,15,170),(30,20,210),(15,10,130),(45,30,235)], alpha=(160,245))
    elif e == "snow":        P.update(kind="dot", n=160, smin=2, smax=6, vy=70, vx=14, sway=1.2, color=(255,255,255), alpha=(140,235))
    elif e == "heavy snow": P.update(kind="dot", n=320, smin=2, smax=8, vy=130, vx=24, sway=1.6, color=(255,255,255), alpha=(150,245))
    elif e == "rain":      P.update(kind="line", n=240, smin=10, smax=22, vy=900, vx=40, color=(210,225,255), alpha=(90,170))
    elif e == "bokeh":     P.update(kind="blur", n=26, smin=26, smax=80, vy=14, vx=10, blur=25, color=(255,255,255), alpha=(40,110))
    elif e == "gold bokeh":P.update(kind="blur", n=26, smin=26, smax=85, vy=14, vx=10, blur=25, palette=[(120,200,255),(80,170,255),(170,225,255)], alpha=(45,120))
    elif e == "sparkle":   P.update(kind="star", n=90, smin=3, smax=9, vy=6, vx=6, twinkle=True, color=(255,255,255), alpha=(0,255))
    elif e == "stars":     P.update(kind="star", n=120, smin=2, smax=6, vy=2, vx=2, twinkle=True, color=(235,245,255), alpha=(0,235))
    elif e == "embers":    P.update(kind="dot", n=120, smin=2, smax=6, vy=-90, vx=22, sway=1.4, twinkle=True, palette=[(40,120,255),(40,170,255),(60,210,255)], alpha=(120,235))
    elif e == "fireflies": P.update(kind="dot", n=70, smin=3, smax=7, vy=-12, vx=26, sway=2.2, twinkle=True, palette=[(120,255,210),(150,255,180)], alpha=(0,235), blur=3)
    elif e == "hearts":    P.update(kind="heart", n=46, smin=10, smax=26, vy=-55, vx=18, sway=1.6, palette=[(140,140,255),(150,120,255),(170,150,255)], alpha=(120,220))
    elif e == "confetti":  P.update(kind="rect", n=130, smin=6, smax=14, vy=160, vx=60, sway=1.0, palette=[(80,80,255),(80,220,90),(255,200,60),(255,120,200),(60,200,255)], alpha=(180,255))
    elif e == "dust":      P.update(kind="dot", n=200, smin=1, smax=3, vy=10, vx=18, sway=1.0, color=(235,235,235), alpha=(40,120))
    elif e == "bubbles":   P.update(kind="ring", n=60, smin=8, smax=30, vy=-60, vx=16, sway=1.5, color=(235,245,255), alpha=(60,150))
    elif e == "petals":    P.update(kind="rect", n=70, smin=8, smax=18, vy=55, vx=42, sway=2.0, palette=[(180,180,255),(190,200,255),(200,180,250)], alpha=(120,210))
    elif e == "light leak":P.update(kind="leak")
    elif e == "glow pulse":P.update(kind="glow")
    elif e == "film grain":P.update(kind="grain")
    elif e == "gradient sweep":P.update(kind="sweep")
    elif e == "lens flare":P.update(kind="flare")
    return P

def _story_render_overlay(effect, W, H, fps, out_path, seconds=6.0):
    """Render a seamless ~6s loopable additive overlay (bright FX on black)."""
    if not HAS_CV2:
        return None
    import math, random
    P = _story_fx_params(effect)
    N = int(round(seconds * fps))
    rng = random.Random(1234)
    kind = P["kind"]
    cmd = ["ffmpeg","-y","-f","rawvideo","-pix_fmt","bgr24","-s",f"{W}x{H}","-r",str(fps),"-i","-"]
    # Use CPU (libx264) for the overlay so we don't consume scarce NVENC sessions
    # (consumer GPUs allow only ~3 concurrent NVENC encodes — base scenes need them).
    cmd += ["-c:v","libx264","-preset","veryfast","-crf","26"]
    cmd += ["-pix_fmt","yuv420p","-an","-loglevel","error",out_path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    def col(P):
        return P["palette"][rng.randrange(len(P["palette"]))] if P.get("palette") else P["color"]

    # particle state (loop seamlessly by wrapping positions over the period)
    parts = []
    if kind in ("dot","line","star","heart","rect","ring","raindrop","blooddrop"):
        for _ in range(P["n"]):
            parts.append(dict(x=rng.uniform(0,W), y=rng.uniform(0,H), s=rng.uniform(P["smin"],P["smax"]),
                              ph=rng.uniform(0,math.tau), c=col(P), a=rng.uniform(*P["alpha"]),
                              tw=rng.uniform(0,math.tau)))
    for f in range(N):
        t = f / fps
        img = np.zeros((H, W, 3), np.uint8)
        if kind == "grain":
            img = rng_grain(W, H)
        elif kind == "glow":
            cx, cy = W//2, H//2
            rad = int(min(W,H)*(0.5 + 0.12*math.sin(t*1.6)))
            ov = np.zeros((H,W,3),np.uint8); cv2.circle(ov,(cx,cy),rad,(60,60,70),-1)
            img = cv2.GaussianBlur(ov,(0,0), rad*0.5)
        elif kind == "sweep":
            xx = np.linspace(0,1,W,dtype=np.float32)
            phase = (t*0.15) % 1.0
            band = np.clip(1.0-np.abs(((xx-phase+1)%1.0)-0.0)*6.0,0,1)
            row = (band[None,:,None]*np.array([90,70,120],np.float32)[None,None,:])
            img = np.repeat(row.astype(np.uint8), H, axis=0)
        elif kind == "leak":
            img = np.zeros((H,W,3),np.uint8)
            for k,(ox,oy,cc) in enumerate([(0.15,0.2,(40,80,180)),(0.85,0.8,(150,90,40)),(0.7,0.15,(40,140,150))]):
                cx=int((ox+0.1*math.sin(t*0.7+k))*W); cy=int((oy+0.1*math.cos(t*0.6+k))*H)
                o=np.zeros((H,W,3),np.uint8); cv2.circle(o,(cx,cy),int(min(W,H)*0.35),cc,-1)
                img=cv2.add(img, cv2.GaussianBlur(o,(0,0), min(W,H)*0.18))
        else:
            for p in parts:
                # motion
                yy = p["y"] + P["vy"]*t
                xx = p["x"] + math.sin(t*1.3 + p["ph"])*P["vx"]*P.get("sway",0)
                yy = yy % (H+40) - 20
                xx = xx % (W+40) - 20
                a = p["a"]
                if P.get("twinkle"):
                    a = max(0.0, math.sin(t*3.0 + p["tw"]))*p["a"]
                if a <= 3: continue
                cc = tuple(int(min(255, v*a/255.0)) for v in p["c"])
                s = int(p["s"])
                if kind == "dot":
                    cv2.circle(img,(int(xx),int(yy)),max(1,s),cc,-1,cv2.LINE_AA)
                elif kind == "raindrop":
                    cv2.circle(img,(int(xx),int(yy)),max(2,s),cc,-1,cv2.LINE_AA)
                    cv2.line(img,(int(xx),int(yy)),(int(xx-int(P.get("vx",10)*0.15)),int(yy-s*2)),cc,max(1,s//3),cv2.LINE_AA)
                    cv2.circle(img,(int(xx-max(1,s//3)),int(yy-max(1,s//3))),max(1,s//3),(255,255,255),-1,cv2.LINE_AA)
                elif kind == "blooddrop":
                    cv2.circle(img,(int(xx),int(yy)),max(3,s),cc,-1,cv2.LINE_AA)
                    cv2.line(img,(int(xx),int(yy)),(int(xx),int(yy-int(s*2.2))),cc,max(2,s//2),cv2.LINE_AA)
                    cv2.circle(img,(int(xx),int(yy)),max(1,s//2),(50,40,240),-1,cv2.LINE_AA)
                elif kind == "line":
                    cv2.line(img,(int(xx),int(yy)),(int(xx-3),int(yy+s)),cc,1,cv2.LINE_AA)
                elif kind == "star":
                    cv2.circle(img,(int(xx),int(yy)),max(1,s//2),cc,-1,cv2.LINE_AA)
                    cv2.line(img,(int(xx-s),int(yy)),(int(xx+s),int(yy)),cc,1,cv2.LINE_AA)
                    cv2.line(img,(int(xx),int(yy-s)),(int(xx),int(yy+s)),cc,1,cv2.LINE_AA)
                elif kind == "rect":
                    ang=t*120+p["ph"]*57; M=cv2.getRotationMatrix2D((0,0),ang,1)
                    pts=np.array([[-s,-s//2],[s,-s//2],[s,s//2],[-s,s//2]],np.float32)
                    R=(M[:, :2]@pts.T).T+np.array([xx,yy]); cv2.fillConvexPoly(img,R.astype(np.int32),cc,cv2.LINE_AA)
                elif kind == "ring":
                    cv2.circle(img,(int(xx),int(yy)),max(2,s),cc,1,cv2.LINE_AA)
                elif kind == "heart":
                    _story_heart(img,int(xx),int(yy),s,cc)
            if P.get("blur"):
                img = cv2.GaussianBlur(img,(0,0), P["blur"])
        proc.stdin.write(np.ascontiguousarray(img).tobytes())
    proc.stdin.close(); proc.wait()
    return out_path if (os.path.exists(out_path) and get_duration(out_path) > 0.1) else None

def rng_grain(W,H):
    g = (np.random.rand(H//2, W//2, 1)*60).astype(np.uint8)
    g = cv2.resize(np.repeat(g,3,axis=2),(W,H),interpolation=cv2.INTER_LINEAR)
    return g

def _story_heart(img,x,y,s,c):
    pts=[]
    import math
    for i in range(0,360,12):
        t=math.radians(i)
        hx=16*math.sin(t)**3
        hy=13*math.cos(t)-5*math.cos(2*t)-2*math.cos(3*t)-math.cos(4*t)
        pts.append([x+hx*s/16.0, y-hy*s/16.0])
    cv2.fillConvexPoly(img,np.array(pts,np.int32),c,cv2.LINE_AA)

_STORY_FX_LOCK = threading.Lock()
def _story_get_overlay(effect, W, H, fps=30):
    """Cached overlay clip per effect/size (thread-safe — parallel scene renders
    share one generation instead of racing on the same file)."""
    if not effect or effect == "None" or not HAS_CV2:
        return None
    safe = "".join(ch for ch in effect.lower() if ch.isalnum())
    path = os.path.join(TEMP_DIR, f"story_fx_{safe}_{W}x{H}.mp4")
    if os.path.exists(path) and get_duration(path) > 0.1:
        return path
    with _STORY_FX_LOCK:
        if os.path.exists(path) and get_duration(path) > 0.1:
            return path
        return _story_render_overlay(effect, W, H, fps, path)

# ---------------------------- PRO CAPTIONS (ASS) ----------------------------
STORY_CAPTION_STYLES = [
    "Clean White","Bold Yellow","TikTok Black Box","Karaoke Pop","Neon Cyan",
    "Sunny","Bubblegum","Minimal","Outline Heavy","Highlight Bar","Gold Lux",
    "Mint","Coral","Sky","Mono","Comic","Elegant Serif","Impact","Pastel","Fire",
]

def _story_hex_to_ass(hexc, alpha=0):
    hexc = (hexc or "#FFFFFF").lstrip("#")
    if len(hexc) == 3: hexc = "".join(c*2 for c in hexc)
    try:
        r=int(hexc[0:2],16); g=int(hexc[2:4],16); b=int(hexc[4:6],16)
    except Exception:
        r,g,b=255,255,255
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"

def _story_style_preset(name):
    """CapCut-style presets. highlight = ACTIVE-word box colour, active_text = the
    text colour inside that box, primary = the other (non-active) words."""
    n=(name or "").lower()
    P=dict(font="Poppins", size=72, primary="#FFFFFF", highlight="#7C3AED", active_text="#FFFFFF",
           outline="#000000", outline_w=8, shadow=1, box=False, box_color="#000000",
           bold=1, align=2, marginv=120)
    if n=="bold yellow":        P.update(primary="#FFFFFF", highlight="#FFC400", active_text="#1A1A1A", size=76)
    elif n=="tiktok black box": P.update(primary="#FFFFFF", highlight="#FFFFFF", active_text="#000000", box=True, box_color="#000000", outline_w=0, size=64)
    elif n=="karaoke pop":      P.update(primary="#FFFFFF", highlight="#22D3EE", active_text="#06222A", outline_w=8, size=72)
    elif n=="neon cyan":        P.update(primary="#FFFFFF", highlight="#22D3EE", active_text="#06222A", outline="#063B3B", outline_w=8, size=70)
    elif n=="sunny":            P.update(primary="#FFFFFF", highlight="#FF7A00", active_text="#FFFFFF", outline="#3A2400", outline_w=8, size=74)
    elif n=="bubblegum":        P.update(primary="#FFFFFF", highlight="#FF4FC3", active_text="#FFFFFF", outline="#5A0033", outline_w=8, size=72)
    elif n=="minimal":          P.update(primary="#FFFFFF", highlight="#FFFFFF", active_text="#000000", outline_w=4, size=60)
    elif n=="outline heavy":    P.update(primary="#FFFFFF", highlight="#FFE14D", active_text="#1A1A1A", outline="#000000", outline_w=12, size=74)
    elif n=="highlight bar":    P.update(primary="#FFFFFF", highlight="#FFE14D", active_text="#1A1A1A", box=True, box_color="#000000", outline_w=6, size=66)
    elif n=="gold lux":         P.update(font="Playfair Display", primary="#FFE9B0", highlight="#E0A93B", active_text="#2A1C00", outline="#2A1C00", outline_w=6, size=70)
    elif n=="mint":             P.update(primary="#FFFFFF", highlight="#34D399", active_text="#06281C", outline="#073B2A", outline_w=8, size=70)
    elif n=="coral":            P.update(primary="#FFFFFF", highlight="#FF6B5C", active_text="#FFFFFF", outline="#3B0E08", outline_w=8, size=70)
    elif n=="sky":              P.update(primary="#FFFFFF", highlight="#3B9EFF", active_text="#06223B", outline="#082A3B", outline_w=8, size=70)
    elif n=="mono":             P.update(font="DejaVu Sans Mono", primary="#FFFFFF", highlight="#FFE14D", active_text="#1A1A1A", outline_w=6, size=62)
    elif n=="comic":            P.update(font="Comic Neue", primary="#FFFFFF", highlight="#FF4D4D", active_text="#FFFFFF", outline_w=8, size=70)
    elif n=="elegant serif":    P.update(font="Playfair Display", primary="#FFFFFF", highlight="#E0A93B", active_text="#1A1A1A", outline_w=6, size=68)
    elif n=="impact":           P.update(font="Anton", primary="#FFFFFF", highlight="#FFE14D", active_text="#1A1A1A", outline_w=10, size=84)
    elif n=="pastel":           P.update(primary="#FFFFFF", highlight="#C9A7FF", active_text="#2A1640", outline="#3A2740", outline_w=8, size=68)
    elif n=="fire":             P.update(primary="#FFD000", highlight="#FF3B00", active_text="#FFFFFF", outline="#2A0A00", outline_w=8, size=78)
    return P

def _story_caption_chunks(text, max_words=10):
    words=[w for w in (text or "").split() if w.strip()]
    return [words[i:i+max_words] for i in range(0, len(words), max_words)] or []

def _story_build_ass(text, duration, W, H, opts):
    """Single-line (<=max_words) realtime karaoke captions for one scene."""
    chunks=_story_caption_chunks(text, int(opts.get("max_words",10)))
    if not chunks or duration<=0.1:
        return None
    st=_story_style_preset(opts.get("style"))
    # UI overrides
    font = opts.get("font") or st["font"]
    size = int(opts.get("size") or st["size"])
    primary = opts.get("primary") or st["primary"]
    highlight = opts.get("highlight") or st["highlight"]
    karaoke = bool(opts.get("karaoke", True))
    caps = opts.get("caps","none")
    box = bool(opts.get("box", st["box"]))
    box_color = opts.get("box_color", st["box_color"])
    outline_w = st["outline_w"] if not box else 3
    border_style = 3 if box else 1
    back = _story_hex_to_ass(box_color, 20) if box else _story_hex_to_ass("#000000", 0)
    prim = _story_hex_to_ass(primary, 0)
    sec  = _story_hex_to_ass(highlight, 0)        # SecondaryColour = karaoke sweep target
    if karaoke:
        prim_fill = _story_hex_to_ass(highlight,0); pre = _story_hex_to_ass(primary,60)
    else:
        prim_fill = prim; pre = prim
    outline = _story_hex_to_ass(st["outline"], 0)

    def conv(words):
        s=" ".join(words)
        if caps=="upper": s=s.upper()
        elif caps=="title": s=s.title()
        elif caps=="lower": s=s.lower()
        elif caps=="first": s=(s[:1].upper()+s[1:].lower()) if s else s
        return s.replace("\n"," ")

    # time budget proportional to word count
    total_words=sum(len(c) for c in chunks) or 1
    head=[]
    head.append("[Script Info]")
    head.append("ScriptType: v4.00+"); head.append(f"PlayResX: {W}"); head.append(f"PlayResY: {H}")
    head.append("WrapStyle: 2"); head.append("ScaledBorderAndShadow: yes"); head.append("")
    head.append("[V4+ Styles]")
    head.append("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding")
    head.append(f"Style: S,{font},{size},{prim_fill},{sec},{outline},{back},{st['bold']},0,0,0,100,100,0,0,{border_style},{outline_w},{st['shadow']},{st['align']},60,60,{st['marginv']},1")
    head.append(""); head.append("[Events]")
    head.append("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text")

    def tc(sec_):
        h=int(sec_//3600); m=int((sec_%3600)//60); s=sec_%60
        return f"{h:d}:{m:02d}:{s:05.2f}"

    t=0.0; lines=[]
    for c in chunks:
        dur=duration*(len(c)/total_words)
        start=t; end=min(duration, t+dur); t=end
        if karaoke:
            per=max(1,int(round((end-start)*100/max(1,len(c)))))  # centiseconds per word
            txt="".join(f"{{\\kf{per}}}{conv([w])} " for w in c).strip()
            txt="{\\fad(80,80)}"+txt
        else:
            txt="{\\fad(80,80)}"+conv(c)
        lines.append(f"Dialogue: 0,{tc(start)},{tc(end)},S,,0,0,0,,{txt}")
    ass="\n".join(head+lines)
    p=os.path.join(TEMP_DIR, f"story_cap_{abs(hash((text,duration)))%99999}.ass")
    open(p,"w",encoding="utf-8").write(ass)
    return p

def _story_caption_font(name, size, fontsdir=None):
    from PIL import ImageFont
    cands=[]
    if fontsdir and os.path.isdir(fontsdir):
        for f in os.listdir(fontsdir):
            if f.lower().endswith((".ttf",".otf")): cands.append(os.path.join(fontsdir,f))
    nm=(name or "").strip()
    wf=r"C:\Windows\Fonts"
    if nm and nm!="(style default)":
        base=nm.replace(" ","")
        cands += [nm, nm+".ttf", base+".ttf", base+"-Bold.ttf", nm.replace(" ","-")+"-Bold.ttf"]
        if os.path.isdir(wf):
            cands += [os.path.join(wf,nm+".ttf"), os.path.join(wf,base+".ttf"), os.path.join(wf,base+"b.ttf")]
        for d in ["/usr/share/fonts/truetype/google-fonts","/usr/share/fonts/truetype"]:
            if os.path.isdir(d):
                for root,_,files in os.walk(d):
                    for f in files:
                        if f.lower().endswith((".ttf",".otf")) and base.lower() in f.replace(" ","").lower():
                            cands.insert(0, os.path.join(root,f))
    # bold fallbacks
    for fb in ["Poppins-Bold.ttf","Montserrat-Bold.ttf","Anton-Regular.ttf","arialbd.ttf","DejaVuSans-Bold.ttf","arial.ttf"]:
        cands.append(fb)
        if os.path.isdir(wf): cands.append(os.path.join(wf,fb))
    for d in ["/usr/share/fonts/truetype/google-fonts","/usr/share/fonts/truetype/dejavu"]:
        if os.path.isdir(d):
            for root,_,files in os.walk(d):
                for f in files:
                    if f in ("Poppins-Bold.ttf","DejaVuSans-Bold.ttf","Anton-Regular.ttf"):
                        cands.append(os.path.join(root,f))
    for c in cands:
        try: return ImageFont.truetype(c, size)
        except Exception: continue
    try: return ImageFont.load_default()
    except Exception: return None

def _hx(h, d):
    h=(h or d).lstrip("#")
    if len(h)==3: h="".join(c*2 for c in h)
    try: return (int(h[0:2],16),int(h[2:4],16),int(h[4:6],16))
    except Exception: return (255,255,255)

STORY_MOTIONS = ["None","Zoom In-Out","Zoom In","Zoom Out","Zoom Pulse","Shake",
                 "Zoom + Shake","Pan L->R","Pan R->L","Pan Up","Pan Down","Rotate Sway"]
_STORY_MOTION_KEY = {"none":"none","zoom in-out":"zoominout","zoom in":"zoomin","zoom out":"zoomout",
    "zoom pulse":"zoompulse","shake":"shake","zoom + shake":"zoomshake","pan l->r":"panlr",
    "pan r->l":"panrl","pan up":"panud","pan down":"pandu","rotate sway":"rotate"}

def _story_motion_chain(motion, spd, fs, duration, fps, W, H):
    """Build filter segments that turn [scaled] -> [base] applying a MOTION effect
    ONLY on the frozen portion (t>=fs); whole clip when fs~0. Zoom/pan/shake use
    zoompan (handles expression commas), rotate uses the rotate filter."""
    motion=_STORY_MOTION_KEY.get((motion or "").strip().lower(), "zoominout")
    try: spd=float(spd)
    except Exception: spd=1.0
    spd=max(0.3, min(3.0, spd))
    N=max(1, int(round(duration*fps))-1); FSf=int(round(fs*fps)); after=(duration-fs)>0.4
    if motion=="none" or not after:
        return ["[scaled]null[base]"], "base"
    denom=f"max(1,{N}-{FSf})"
    GATE=(f"gte(on,{FSf})" if fs>0.05 else "1")
    PROG=(f"((on-{FSf})/{denom})" if fs>0.05 else f"(on/{N})")
    zin_out=lambda a:(f"if(lt(on,{FSf}),1,1+{a:.3f}*(1-abs(2*(on-{FSf})/{denom}-1)))" if fs>0.05 else f"1+{a:.3f}*(1-abs(2*on/{N}-1))")
    zin=lambda a:(f"if(lt(on,{FSf}),1,1+{a:.3f}*((on-{FSf})/{denom}))" if fs>0.05 else f"1+{a:.3f}*(on/{N})")
    zout=lambda a:(f"if(lt(on,{FSf}),1,1+{a:.3f}*(1-(on-{FSf})/{denom}))" if fs>0.05 else f"1+{a:.3f}*(1-on/{N})")
    def zp(z="1.0", x="iw/2-(iw/zoom/2)", y="ih/2-(ih/zoom/2)", out="base"):
        return f"[scaled]zoompan=z='{z}':x='{x}':y='{y}':d=1:s={W}x{H}:fps={fps}[{out}]"
    if motion=="zoominout": return [zp(zin_out(0.12*spd))], "base"
    if motion=="zoomin":    return [zp(zin(0.20*spd))], "base"
    if motion=="zoomout":   return [zp(zout(0.20*spd))], "base"
    if motion=="zoompulse":
        z=(f"if(lt(on,{FSf}),1,1+{0.05*spd:.3f}*(1-cos(2*PI*{0.9*spd:.3f}*(on-{FSf})/{fps})))" if fs>0.05
           else f"1+{0.05*spd:.3f}*(1-cos(2*PI*{0.9*spd:.3f}*on/{fps}))")
        return [zp(z)], "base"
    if motion in ("shake","zoomshake"):
        amp=max(4,int(round(18*spd))); fr=2.0*spd
        z = zin_out(0.10*spd) if motion=="zoomshake" else "1.08"
        x=f"iw/2-(iw/zoom/2)+{GATE}*{amp}*sin(2*PI*{fr:.3f}*on/{fps})"
        y=f"ih/2-(ih/zoom/2)+{GATE}*{amp}*cos(2*PI*{fr*1.3:.3f}*on/{fps})"
        return [zp(z,x,y)], "base"
    if motion in ("panlr","panrl","panud","pandu"):
        z="1.14"; mx="(iw-iw/zoom)"; my="(ih-ih/zoom)"
        if motion=="panlr": x=f"{mx}*{PROG}"; y=f"{my}/2"
        elif motion=="panrl": x=f"{mx}*(1-{PROG})"; y=f"{my}/2"
        elif motion=="panud": x=f"{mx}/2"; y=f"{my}*{PROG}"
        else: x=f"{mx}/2"; y=f"{my}*(1-{PROG})"
        return [zp(z,x,y)], "base"
    if motion=="rotate":
        amp=0.035*spd; fr=0.6*spd
        gate=(f"if(lt(t,{fs:.3f})\\,0\\,1)" if fs>0.05 else "1")
        sw="ceil(iw*1.22/2)*2"; sh="ceil(ih*1.22/2)*2"
        ang=f"{gate}*{amp:.4f}*sin(2*PI*{fr:.3f}*t)"
        return [f"[scaled]scale={sw}:{sh},rotate='{ang}':c=black,crop={W}:{H}[base]"], "base"
    return [zp(zin_out(0.12*spd))], "base"


def _story_render_caption_overlay(text, duration, W, H, opts, out_path, fps=30):
    """Pro caption overlay (RGBA). Supports multiple animation MODES and a custom
    locked position. Modes:
      box       -> active word in a rounded highlight box (CapCut classic)
      highlight -> active word recoloured, no box
      pop       -> active word boxed AND slightly larger
      word      -> ONE word at a time, big, at the position
      plain     -> whole line, no per-word highlight (static)
    """
    from PIL import Image, ImageDraw
    chunks=_story_caption_chunks(text, int(opts.get("max_words",6) or 6))
    if not chunks or duration<=0.1: return None
    st=_story_style_preset(opts.get("style"))
    size=int(opts.get("size") or st["size"])
    primary=_hx(opts.get("primary"), st["primary"])
    highlight=_hx(opts.get("highlight"), st["highlight"])
    outline=_hx(st["outline"], "#000000"); ow=max(0,int(st["outline_w"]))
    line_bg_on=bool(opts.get("box", st["box"]))
    line_bg=_hx(opts.get("box_color"), st["box_color"])
    box_alpha=int(round(float(opts.get("box_opacity",90))*255/100))
    active_text=_hx(opts.get("active_text") or st.get("active_text") or "#FFFFFF","#FFFFFF")
    caps=opts.get("caps","none"); karaoke=bool(opts.get("karaoke",True))
    mode=(opts.get("mode") or "box").lower()
    if not karaoke and mode in ("box","highlight","pop","word"):
        mode="plain"
    px=float(opts.get("pos_x", 0.5)); py=float(opts.get("pos_y", 0.80))
    font=_story_caption_font(opts.get("font") or st["font"], size, opts.get("fontsdir"))
    font_big=_story_caption_font(opts.get("font") or st["font"], int(size*1.18), opts.get("fontsdir"))
    font_word=_story_caption_font(opts.get("font") or st["font"], int(size*1.6), opts.get("fontsdir"))
    def conv(s):
        if caps=="upper": return s.upper()
        if caps=="title": return s.title()
        if caps=="lower": return s.lower()
        return s
    total=sum(len(c) for c in chunks) or 1
    spans=[]; t=0.0
    for c in chunks:
        cd=duration*len(c)/total; spans.append((t,t+cd,c,cd/max(1,len(c)))); t+=cd
    cx=int(px*W); cy=int(py*H)
    spc=int(size*0.32); pad_x=int(size*0.30); pad_y=int(size*0.16); rad=int(size*0.32)
    cmd=["ffmpeg","-y","-f","rawvideo","-pix_fmt","rgba","-s",f"{W}x{H}","-r",str(fps),"-i","-",
         "-c:v","qtrle","-loglevel","error",out_path]
    proc=subprocess.Popen(cmd, stdin=subprocess.PIPE)
    N=int(round(duration*fps))
    probe=Image.new("RGBA",(8,8)); pd=ImageDraw.Draw(probe)
    def wbb(s,f): 
        b=pd.textbbox((0,0),s,font=f,stroke_width=ow); return b[2]-b[0], b[3]-b[1], b[1]
    for f in range(N):
        tt=f/fps
        img=Image.new("RGBA",(W,H),(0,0,0,0)); d=ImageDraw.Draw(img)
        chunk=spans[-1][2]; cs=spans[-1][0]; per=spans[-1][3]
        for (a,b,c,p) in spans:
            if a<=tt<b: chunk,cs,per=c,a,p; break
        active=min(len(chunk)-1,int((tt-cs)/per)) if karaoke else -1
        words=[conv(w) for w in chunk]

        if mode=="word":
            w=words[active if active>=0 else 0]
            ww,wh,yb=wbb(w,font_word)
            x=cx-ww//2; ytop=cy-wh//2
            d.rounded_rectangle([x-pad_x, ytop-pad_y, x+ww+pad_x, ytop+wh+pad_y], radius=rad,
                                fill=(highlight[0],highlight[1],highlight[2],255))
            d.text((x, ytop-yb), w, font=font_word, fill=(active_text[0],active_text[1],active_text[2],255),
                   stroke_width=ow, stroke_fill=(outline[0],outline[1],outline[2],255))
            proc.stdin.write(img.tobytes()); continue

        # line modes
        widths=[wbb(w,font)[0] for w in words]
        _,wh,yb=wbb("Ayg",font)
        total_w=sum(widths)+spc*(len(words)-1)
        x=cx-total_w//2; ytop=cy-wh//2
        if line_bg_on:
            d.rounded_rectangle([x-pad_x, ytop-pad_y, x+total_w+pad_x, ytop+wh+pad_y], radius=rad,
                                fill=(line_bg[0],line_bg[1],line_bg[2],box_alpha))
        for i,w in enumerate(words):
            ww=widths[i]; act=(i==active and mode!="plain")
            if act and mode in ("box","pop"):
                d.rounded_rectangle([x-int(pad_x*0.7), ytop-int(pad_y*0.7), x+ww+int(pad_x*0.7), ytop+wh+int(pad_y*0.7)],
                                    radius=int(rad*0.8), fill=(highlight[0],highlight[1],highlight[2],255))
                col=active_text
            elif act and mode=="highlight":
                col=highlight
            else:
                col=primary
            d.text((x, ytop-yb), w, font=font, fill=(col[0],col[1],col[2],255),
                   stroke_width=ow, stroke_fill=(outline[0],outline[1],outline[2],255))
            x+=widths[i]+spc
        proc.stdin.write(img.tobytes())
    proc.stdin.close(); proc.wait()
    return out_path if (os.path.exists(out_path) and get_duration(out_path)>0.1) else None

def story_apply_fx_captions(scene_video, out_path, effect, caption_text, duration, opts, fps=30, freeze_start=0.0, logo=None):
    """Composite: a selectable MOTION effect (zoom/pan/shake/rotate) on the frozen
    frame + overlay FX (only on the frozen portion) + PRO CapCut captions
    (active-word highlight box) + a STATIC logo on top. Voiceover kept fully."""
    W,H=1920,1080
    scene_video=os.path.abspath(scene_video)
    out_path=os.path.abspath(out_path)
    ov=_story_get_overlay(effect, W, H, fps) if effect and effect!="None" else None
    cap_ov=None
    try:
        if opts.get("captions_on") and caption_text:
            cap_path=os.path.join(TEMP_DIR, f"story_capov_{abs(hash((caption_text,round(duration,2))))%999999}.mov")
            cap_ov=_story_render_caption_overlay(caption_text, duration, W, H, opts, cap_path, fps=fps)
    except Exception as e:
        print("[STORY] caption overlay error:", e); cap_ov=None

    fs=max(0.0, float(freeze_start or 0.0))
    motion=opts.get("freeze_motion","Zoom In-Out")
    motion_on = (_STORY_MOTION_KEY.get((motion or "").strip().lower(),"zoominout")!="none") and (duration-fs)>0.4
    logo_ok = bool(logo and logo.get("path") and os.path.exists(logo.get("path","")))
    if not ov and not cap_ov and not motion_on and not logo_ok:
        return scene_video  # nothing to do

    inputs=["-i",scene_video]
    # IMPORTANT: clone the last frame to fill the FULL duration BEFORE the motion runs.
    # Otherwise a scene whose video is shorter than its voiceover would have empty
    # frames in the tail (a ~frozen/black "hang"). With tpad the freeze tail has real
    # frames and the motion (zoom/pan) animates over them.
    fc=[f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
        f"tpad=stop_mode=clone:stop_duration={max(0.5,duration)+1.0:.3f},"
        f"trim=duration={max(0.1,duration):.3f},setpts=PTS-STARTPTS[scaled]"]
    # MOTION effect on the frozen portion (zoom / pan / shake / rotate) — image only,
    # the logo is added AFTER so it never stretches.
    msegs, mlabel = _story_motion_chain(motion, opts.get("freeze_speed",1.0), fs, duration, fps, W, H)
    fc += msegs
    last=mlabel; idx=1
    if ov:
        inputs+=["-stream_loop","-1","-i",ov]
        oi=idx; idx+=1
        fc.append(f"[{oi}:v]trim=duration={duration:.3f},setpts=PTS-STARTPTS,scale={W}:{H},"
                  f"format=rgba,lumakey=threshold=0.06:tolerance=0.20[ovk]")
        en = f":enable='gte(t,{fs:.3f})'" if fs>0.05 else ""
        fc.append(f"[{last}][ovk]overlay=eof_action=pass{en}[bg]")
        last="bg"
    if cap_ov:
        inputs+=["-i",cap_ov]
        ci=idx; idx+=1
        fc.append(f"[{last}][{ci}:v]overlay=eof_action=pass:shortest=1[v]")
        last="v"
    if logo_ok:
        inputs+=["-i",logo["path"]]
        li=idx; idx+=1
        lw=int(logo.get("w",160)); lh=int(logo.get("h",160))
        lx=int(logo.get("x",20)); ly=int(logo.get("y",20)); opa=float(logo.get("opa",1.0))
        fc.append(f"[{li}:v]scale={lw}:{lh},format=rgba,colorchannelmixer=aa={opa:.3f}[lg]")
        fc.append(f"[{last}][lg]overlay={lx}:{ly}:format=auto[vlogo]")
        last="vlogo"
    cmd=["ffmpeg","-y"]+inputs+["-filter_complex",";".join(fc),"-map",f"[{last}]"]
    cmd+=["-map","0:a?","-t",f"{duration:.3f}"]
    cmd+=["-c:v","libx264","-preset","veryfast","-crf","23"]
    cmd+=["-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-loglevel","error",out_path]
    try:
        r=subprocess.run(cmd, capture_output=True, text=True, timeout=900, encoding="utf-8", errors="replace")
    except Exception as e:
        print("[STORY] render exception:", e); r=None
    ok = os.path.exists(out_path) and get_duration(out_path)>0.1
    if not ok:
        err = str(getattr(r,'stderr','') or '')[-500:]
        print(f"[STORY] FX/caption render FAILED — falling back to plain scene.\n  effect={effect} captions_on={opts.get('captions_on')} cap_ov={'yes' if cap_ov else 'no'}\n  ffmpeg: {err}")
    return out_path if ok else scene_video



# ════════════════════════════════════════════════════════════════
# HEALTH tab — Story Video + auto dual-intro + optional intro voice-change
# ════════════════════════════════════════════════════════════════
def _hsts_extract_audio(video, out_mp3):
    r=_run_ff(["ffmpeg","-y","-i",video,"-vn","-ac","1","-ar","44100","-b:a","192k","-loglevel","error",out_mp3],timeout=1800)
    return out_mp3 if (os.path.exists(out_mp3) and get_duration(out_mp3)>0.05) else None

def _hsts_convert(key, voice_id, model, audio_path, voice_settings, remove_bg, out_path, timeout=1800):
    try:
        with open(audio_path,"rb") as fh:
            files={"audio":(os.path.basename(audio_path),fh,"audio/mpeg")}
            data={"model_id":model,"voice_settings":json.dumps(voice_settings),
                  "remove_background_noise":"true" if remove_bg else "false"}
            params={"output_format":"mp3_44100_128"}
            r=requests.post(f"https://api.elevenlabs.io/v1/speech-to-speech/{voice_id}",
                headers={"xi-api-key":key,"Accept":"audio/mpeg"},files=files,data=data,params=params,timeout=timeout)
        if r.status_code==200 and ("audio" in r.headers.get("content-type","") or len(r.content)>2000):
            with open(out_path,"wb") as f: f.write(r.content)
            return True,""
        msg=""
        try: msg=r.json().get("detail",{}).get("message","") or str(r.json())[:200]
        except Exception: msg=(r.text or "")[:200]
        return False,f"HTTP {r.status_code}: {msg}"
    except Exception as e:
        return False,str(e)

def _hsts_mux(video, new_audio, out_path):
    vdur=get_duration(video)
    fixed=os.path.join(TEMP_DIR,f"hsts_fixed_{abs(hash(out_path))%99999}.m4a")
    _run_ff(["ffmpeg","-y","-i",new_audio,"-af","apad","-t",f"{max(0.1,vdur):.3f}",
             "-c:a","aac","-b:a","192k","-loglevel","error",fixed],timeout=600)
    src=fixed if (os.path.exists(fixed) and get_duration(fixed)>0.05) else new_audio
    r=_run_ff(["ffmpeg","-y","-i",video,"-i",src,"-map","0:v:0","-map","1:a:0",
               "-c:v","copy","-c:a","aac","-b:a","192k","-movflags","+faststart","-loglevel","error",out_path],timeout=1800)
    if not (os.path.exists(out_path) and get_duration(out_path)>0.1):
        _run_ff(["ffmpeg","-y","-i",video,"-i",src,"-map","0:v:0","-map","1:a:0",
                 "-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k",
                 "-movflags","+faststart","-loglevel","error",out_path],timeout=3600)
    return os.path.exists(out_path) and get_duration(out_path)>0.1

def _hsts_extract_audio_wav(video, out_wav):
    r=_run_ff(["ffmpeg","-y","-i",video,"-vn","-ac","2","-ar","44100","-loglevel","error",out_wav],timeout=1800)
    return out_wav if (os.path.exists(out_wav) and get_duration(out_wav)>0.05) else None

_DEMUCS_OK=None
def _has_demucs():
    """True if the 'demucs' separation library is importable (cached)."""
    global _DEMUCS_OK
    if _DEMUCS_OK is not None: return _DEMUCS_OK
    try:
        import importlib.util as _u
        _DEMUCS_OK = (_u.find_spec("demucs") is not None)
    except Exception:
        _DEMUCS_OK=False
    return _DEMUCS_OK

def _separate_vocals(audio, outdir, timeout=3600):
    """Split `audio` into (vocals, background) using Demucs two-stems.
    background = music + SFX (everything except the voice). Returns (voc, bg) or (None,None)."""
    try:
        os.makedirs(outdir, exist_ok=True)
        cmd=[sys.executable,"-m","demucs","--two-stems=vocals","--segment","8","-o",outdir,audio]
        subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        base=os.path.splitext(os.path.basename(audio))[0]
        for root,_dirs,files in os.walk(outdir):
            if os.path.basename(root)==base and "vocals.wav" in files and "no_vocals.wav" in files:
                return os.path.join(root,"vocals.wav"), os.path.join(root,"no_vocals.wav")
        # retry without --segment (some models ignore it)
        subprocess.run([sys.executable,"-m","demucs","--two-stems=vocals","-o",outdir,audio],
                       capture_output=True, text=True, timeout=timeout)
        for root,_dirs,files in os.walk(outdir):
            if os.path.basename(root)==base and "vocals.wav" in files and "no_vocals.wav" in files:
                return os.path.join(root,"vocals.wav"), os.path.join(root,"no_vocals.wav")
        return None,None
    except Exception as e:
        print("[DEMUCS]", e); return None,None

def _voice_change_clip(video, voice_id, key, model, rmbg, out_path, keep_bg=True, logf=None):
    """Change ONLY the spoken voice in `video`. When keep_bg and Demucs are available,
    the music + SFX are separated out and re-mixed untouched (only the voice stem is
    re-voiced). Otherwise falls back to re-voicing the whole track. Returns out_path|None."""
    def log(m):
        if logf:
            try: logf(m)
            except Exception: pass
    tag=abs(hash((os.path.abspath(video),voice_id,bool(keep_bg))))%999999
    aud=os.path.join(TEMP_DIR,f"vc_in_{tag}.wav")
    if not _hsts_extract_audio_wav(video, aud):
        return None
    vs={"stability":0.5,"similarity_boost":0.8,"style":0.0,"use_speaker_boost":True}
    final_aud=os.path.join(TEMP_DIR,f"vc_final_{tag}.m4a")
    used_bg=False
    if keep_bg and _has_demucs():
        log("separating voice from music/SFX (Demucs)…")
        work=os.path.join(TEMP_DIR,f"vcsep_{tag}")
        voc,bg=_separate_vocals(aud, work)
        if voc and bg:
            changed=os.path.join(TEMP_DIR,f"vc_voc_{tag}.mp3")
            ok,err=_hsts_convert(key,voice_id,model,voc,vs,rmbg,changed)
            if not ok: log(f"voice-swap failed: {err[:60]}"); return None
            # re-mix: NEW voice + ORIGINAL background (levels preserved, no normalize)
            _run_ff(["ffmpeg","-y","-i",changed,"-i",bg,"-filter_complex",
                     "[0:a]aresample=44100[v];[1:a]aresample=44100[b];"
                     "[v][b]amix=inputs=2:duration=longest:normalize=0[a]",
                     "-map","[a]","-c:a","aac","-b:a","192k","-loglevel","error",final_aud],timeout=900)
            used_bg = os.path.exists(final_aud) and get_duration(final_aud)>0.1
        if not used_bg:
            log("separation unavailable → re-voicing whole track")
    if not used_bg:
        ok,err=_hsts_convert(key,voice_id,model,aud,vs,rmbg,final_aud)
        if not ok: log(f"voice-swap failed: {err[:60]}"); return None
    return out_path if _hsts_mux(video, final_aud, out_path) else None

def _tts_simple(text, voice_id, key, model_id, out_mp3, timeout=180):
    """Generate a TTS narration clip → mp3. Returns out_mp3 | None."""
    if not (text and voice_id and key): return None
    try:
        from ai33_api import ai33_tts_generate
        if ai33_tts_generate(text=text[:5000], voice_id=voice_id, api_key=key, out_path=out_mp3):
            return out_mp3 if (os.path.exists(out_mp3) and get_duration(out_mp3)>0.1) else None
    except Exception as e:
        print("[NAR-TTS]", e)
    return None

def _blend_narration_duck(video, narration_mp3, out_path, duck=0.10):
    """Overlay the narration at the START of the clip and DUCK the clip's own audio
    DOWN to `duck` (≈10%) while the narration plays, so the narration is clearly on
    top (no doubling). The voice FADES IN as it starts and FADES OUT as it ends, so
    moving from one clip to the next feels like one continuous flow rather than cuts.
    After the narration ends the clip returns to full. Video + duration unchanged."""
    vdur=get_duration(video); ndur=get_duration(narration_mp3)
    if vdur<=0.05: return False
    tail=min(vdur, ndur+0.3)        # duck window = narration length (+0.3s release)
    fin=min(0.35, max(0.12, ndur*0.18))           # voice fade-in
    fo =min(0.6,  max(0.20, ndur*0.30))           # voice fade-out
    fo_st=max(0.0, ndur-fo)
    nar_chain=(f"[1:a]aresample=44100,"
               f"afade=t=in:st=0:d={fin:.3f},afade=t=out:st={fo_st:.3f}:d={fo:.3f},"
               f"apad=whole_dur={vdur:.3f}[nar]")
    has_aud = has_audio_stream(video)
    if has_aud:
        fc=(f"[0:a]aresample=44100,volume=eval=frame:volume='if(lt(t,{tail:.3f}),{duck:.3f},1.0)'[clip];"
            f"{nar_chain};"
            f"[clip][nar]amix=inputs=2:duration=first:normalize=0[a]")
    else:
        fc=nar_chain.replace("[nar]","[a]")
    base=["ffmpeg","-y","-i",video,"-i",narration_mp3,"-filter_complex",fc,"-map","0:v:0","-map","[a]"]
    tail_args=["-c:a","aac","-b:a","192k","-t",f"{vdur:.3f}","-movflags","+faststart","-loglevel","error",out_path]
    _run_ff(base+["-c:v","copy"]+tail_args, timeout=1800)
    if not (os.path.exists(out_path) and get_duration(out_path)>0.1):
        _run_ff(base+["-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p"]+tail_args, timeout=3600)
    return os.path.exists(out_path) and get_duration(out_path)>0.1

def _health_extract_num(name, kind):
    """Pull the ordering / scene number out of an intro filename.
    intro1 → 'Intro_Visual_<N>_...';  intro2 → 'Before_Scene_<N>_...'.
    Falls back to the first number in the name."""
    base=os.path.basename(name)
    if kind=="intro1":
        m=re.search(r'intro[_\s]*visual[_\s]*0*(\d+)',base,re.I) or re.search(r'visual[_\s]*0*(\d+)',base,re.I)
    else:
        m=re.search(r'before[_\s]*scene[_\s]*0*(\d+)',base,re.I) or re.search(r'scene[_\s]*0*(\d+)',base,re.I)
    if m: return int(m.group(1))
    m2=re.search(r'(\d+)',base)
    return int(m2.group(1)) if m2 else None


class HealthVideoEditorFrame(StoryVideoEditorFrame):
    """Health = Story Video, but the intro is fully automatic from filenames:
       • INTRO 1 : bulk videos that play at the very START, ordered by the number
                   in the name (Intro_Visual_1, _2, _3 …).
       • INTRO 2 : bulk videos each placed JUST BEFORE the scene number found in the
                   name (Before_Scene_<N>_…). Number is auto-fetched.
       • Optional: change the intro videos' voice via ElevenLabs (dropdown + search).
    """
    def __init__(self, master):
        super().__init__(master)
        # Health uses its own auto dual-intro → disable & hide Story's manual intro.
        try: self._story_intro_on.set(False)
        except Exception: pass
        try: self._story_intro_section_frame.grid_remove()
        except Exception: pass
        self._h_intro1_files=[]; self._h_intro2_files=[]
        self._h_voices=[]; self._h_voice_map={}
        self._h_restore()
        self._add_health_intro_section()

    # ---------- persistence ----------
    def _h_restore(self):
        try:
            self._h_intro1_files=[p for p in (self.settings.get("health_intro1") or []) if os.path.exists(p)]
            self._h_intro2_files=[p for p in (self.settings.get("health_intro2") or []) if os.path.exists(p)]
        except Exception: pass

    def _h_save(self):
        try:
            self.settings.set("health_intro1", list(self._h_intro1_files))
            self.settings.set("health_intro2", list(self._h_intro2_files))
            if hasattr(self,"_h_vc_on"):   self.settings.set("health_vc_on", bool(self._h_vc_on.get()))
            if hasattr(self,"_h_vc_rmbg"): self.settings.set("health_vc_rmbg", bool(self._h_vc_rmbg.get()))
            if hasattr(self,"_h_keepbg"): self.settings.set("health_keepbg", bool(self._h_keepbg.get()))
            if hasattr(self,"_h_voice_var"): self.settings.set("health_vc_voice", self._h_voice_var.get())
            self.settings.save()
        except Exception: pass

    # ---------- UI ----------
    def _add_health_intro_section(self):
        sb=getattr(self,"_sb_ref",None)
        if sb is None: return
        try:
            C_=C
            card=ctk.CTkFrame(sb, fg_color=C_["card"], border_color=C_["green"], border_width=2, corner_radius=8)
            card.grid(row=899, column=0, sticky="ew", padx=6, pady=(4,6))
            self._health_intro_card = card
            ctk.CTkLabel(card, text="🏥 HEALTH INTROS (auto from filenames)", text_color=C_["green"],
                         font=("Segoe UI",13,"bold")).pack(anchor="w", padx=10, pady=(8,2))

            # INTRO 1
            ctk.CTkLabel(card, text="INTRO 1 — plays at the START (ordered by number, e.g. Intro_Visual_1,2,3…)",
                         text_color=C_["dim"], font=("Segoe UI",9), justify="left").pack(anchor="w", padx=10, pady=(2,0))
            r1=ctk.CTkFrame(card, fg_color="transparent"); r1.pack(fill="x", padx=10, pady=2)
            ctk.CTkButton(r1, text="➕ Add Intro-1 videos", width=150, fg_color=C_["accent"], text_color="#000",
                          command=self._h_add_intro1).pack(side="left")
            ctk.CTkButton(r1, text="Clear", width=60, fg_color=C_["red"], text_color="#fff",
                          command=self._h_clear_intro1).pack(side="left", padx=6)
            self._h_intro1_lbl=ctk.CTkLabel(r1, text="0 videos", text_color=C_["dim"]); self._h_intro1_lbl.pack(side="left", padx=4)
            self._h_intro1_box=ctk.CTkTextbox(card, height=64, fg_color=C_["entry_bg"], text_color=C_["text"],
                                              border_color=C_["border"], border_width=1)
            self._h_intro1_box.pack(fill="x", padx=10, pady=(0,6)); self._h_intro1_box.configure(state="disabled")

            # INTRO 2
            ctk.CTkLabel(card, text="INTRO 2 — each plays BEFORE its scene (number from Before_Scene_<N>_…)",
                         text_color=C_["dim"], font=("Segoe UI",9), justify="left").pack(anchor="w", padx=10, pady=(2,0))
            r2=ctk.CTkFrame(card, fg_color="transparent"); r2.pack(fill="x", padx=10, pady=2)
            ctk.CTkButton(r2, text="➕ Add Intro-2 videos", width=150, fg_color=C_["accent"], text_color="#000",
                          command=self._h_add_intro2).pack(side="left")
            ctk.CTkButton(r2, text="Clear", width=60, fg_color=C_["red"], text_color="#fff",
                          command=self._h_clear_intro2).pack(side="left", padx=6)
            self._h_intro2_lbl=ctk.CTkLabel(r2, text="0 videos", text_color=C_["dim"]); self._h_intro2_lbl.pack(side="left", padx=4)
            self._h_intro2_box=ctk.CTkTextbox(card, height=64, fg_color=C_["entry_bg"], text_color=C_["text"],
                                              border_color=C_["border"], border_width=1)
            self._h_intro2_box.pack(fill="x", padx=10, pady=(0,6)); self._h_intro2_box.configure(state="disabled")

            # VOICE CHANGE for intros
            ctk.CTkLabel(card, text="🎙️ Change intro voice (optional) — ElevenLabs voice swap on intro clips:",
                         text_color=C_["purple"], font=("Segoe UI",10,"bold"), justify="left").pack(anchor="w", padx=10, pady=(4,0))
            vr=ctk.CTkFrame(card, fg_color="transparent"); vr.pack(fill="x", padx=10, pady=2)
            self._h_vc_on=ctk.BooleanVar(value=bool(self.settings.get("health_vc_on")))
            ctk.CTkCheckBox(vr, text="Change voice", variable=self._h_vc_on, width=20,
                            text_color=C_["text"], fg_color=C_["purple"], command=self._h_save).pack(side="left")
            ctk.CTkButton(vr, text="🔄 Load voices", width=110, fg_color=C_["btn"], hover_color=C_["btn_hov"],
                          text_color=C_["text"], command=self._h_load_voices).pack(side="left", padx=6)
            self._h_vc_rmbg=ctk.BooleanVar(value=True if self.settings.get("health_vc_rmbg")=="" else bool(self.settings.get("health_vc_rmbg")))
            ctk.CTkCheckBox(vr, text="Remove BG noise", variable=self._h_vc_rmbg, width=20,
                            text_color=C_["text"], fg_color=C_["purple"], command=self._h_save).pack(side="left", padx=6)
            vrk=ctk.CTkFrame(card, fg_color="transparent"); vrk.pack(fill="x", padx=10, pady=(0,2))
            self._h_keepbg=ctk.BooleanVar(value=True if self.settings.get("health_keepbg")=="" else bool(self.settings.get("health_keepbg")))
            ctk.CTkCheckBox(vrk, text="Keep music & SFX (only swap the voice — needs Demucs)",
                            variable=self._h_keepbg, width=20, text_color=C_["green"],
                            fg_color=C_["green"], command=self._h_save).pack(side="left")
            vr2=ctk.CTkFrame(card, fg_color="transparent"); vr2.pack(fill="x", padx=10, pady=(2,8))
            ctk.CTkLabel(vr2, text="Search:", text_color=C_["dim"]).pack(side="left")
            self._h_search_var=ctk.StringVar(value="")
            se=ctk.CTkEntry(vr2, textvariable=self._h_search_var, width=120, fg_color=C_["entry_bg"],
                            text_color=C_["text"], border_color=C_["border"], placeholder_text="filter…")
            se.pack(side="left", padx=4)
            self._h_search_var.trace_add("write", self._h_filter_voices)
            self._h_voice_var=ctk.StringVar(value=self.settings.get("health_vc_voice") or "(load voices)")
            self._h_voice_menu=ctk.CTkOptionMenu(vr2, variable=self._h_voice_var, values=["(load voices)"],
                                                 fg_color=C_["btn"], button_color=C_["btn_hov"], width=200,
                                                 command=lambda *_: self._h_save())
            self._h_voice_menu.pack(side="left", padx=4)
            self._h_refresh_lists()
        except Exception as e:
            print("[WARN] health intro section:", e)

    def _h_refresh_lists(self):
        for box, files, lbl, kind in [
            (getattr(self,"_h_intro1_box",None), self._h_intro1_files, getattr(self,"_h_intro1_lbl",None), "intro1"),
            (getattr(self,"_h_intro2_box",None), self._h_intro2_files, getattr(self,"_h_intro2_lbl",None), "intro2")]:
            if box is None: continue
            box.configure(state="normal"); box.delete("1.0","end")
            ordered=sorted(files, key=lambda p:(_health_extract_num(p,kind) if _health_extract_num(p,kind) is not None else 99999))
            for p in ordered:
                n=_health_extract_num(p,kind)
                tag=("start #"+str(n)) if kind=="intro1" else ("before scene "+str(n))
                box.insert("end", f"[{tag}]  {os.path.basename(p)}\n")
            box.configure(state="disabled")
            if lbl is not None: lbl.configure(text=f"{len(files)} video(s)")

    def _h_add_intro1(self):
        ps=filedialog.askopenfilenames(filetypes=[("Video","*.mp4 *.mov *.avi *.mkv *.webm")])
        for p in ps:
            if p not in self._h_intro1_files: self._h_intro1_files.append(p)
        self._h_refresh_lists(); self._h_save()
    def _h_clear_intro1(self):
        self._h_intro1_files.clear(); self._h_refresh_lists(); self._h_save()
    def _h_add_intro2(self):
        ps=filedialog.askopenfilenames(filetypes=[("Video","*.mp4 *.mov *.avi *.mkv *.webm")])
        for p in ps:
            if p not in self._h_intro2_files: self._h_intro2_files.append(p)
        self._h_refresh_lists(); self._h_save()
    def _h_clear_intro2(self):
        self._h_intro2_files.clear(); self._h_refresh_lists(); self._h_save()

    # ---------- voices ----------
    def _h_api_key(self):
        try: k=self.api_entry.get().strip()
        except Exception: k=""
        return k or self.settings.get("api_key")

    def _h_load_voices(self):
        key=self._h_api_key()
        if not key:
            messagebox.showwarning("API key","Enter your ElevenLabs API key (top of the editor) first."); return
        self._ss("Loading voices…", C["orange"])
        def work():
            try:
                r=requests.get("https://api.elevenlabs.io/v1/voices",headers={"xi-api-key":key},timeout=30); r.raise_for_status()
                vs=[(v.get("name","?"),v.get("voice_id","")) for v in r.json().get("voices",[])]
                self._h_voices=vs; self._h_voice_map={n:i for n,i in vs}
                names=[n for n,_ in vs] or ["(none)"]
                self.after(0, lambda:(self._h_voice_menu.configure(values=names), self._h_voice_var.set(names[0])))
                self._ss(f"✓ Loaded {len(vs)} voices", C["green"])
            except Exception as e:
                self._ss(f"Voice load error: {str(e)[:50]}", C["red"])
        threading.Thread(target=work, daemon=True).start()

    def _h_filter_voices(self, *a):
        q=self._h_search_var.get().strip().lower()
        names=[n for n,_ in self._h_voices if q in n.lower()] if self._h_voices else []
        if not names: names=["(no match)"]
        try:
            self._h_voice_menu.configure(values=names)
            if names[0]!="(no match)": self._h_voice_var.set(names[0])
        except Exception: pass

    def _h_resolve_voice_id(self):
        return self._h_voice_map.get(self._h_voice_var.get(), "")

    # ---------- intro processing ----------
    def _health_voice_change_video(self, video, key, vid):
        tag=abs(hash((os.path.abspath(video), vid, "kb")))%999999
        out=os.path.join(TEMP_DIR, f"health_vc_{tag}.mp4")
        if os.path.exists(out) and get_duration(out)>0.1: return out
        keep_bg=bool(getattr(self,"_h_keepbg",None) and self._h_keepbg.get())
        if keep_bg and not _has_demucs():
            self._sss("Demucs not installed → background can't be kept; re-voicing whole intro. (pip install demucs)")
        return _voice_change_clip(video, vid, key, "eleven_multilingual_sts_v2",
                                  bool(self._h_vc_rmbg.get()), out, keep_bg=keep_bg,
                                  logf=lambda m: self._sss(m))

    def _health_prep_intro(self, path):
        if not (path and os.path.exists(path)): return None
        if bool(getattr(self,"_h_vc_on",None) and self._h_vc_on.get()):
            key=self._h_api_key(); vid=self._h_resolve_voice_id()
            if key and vid:
                self._ss(f"Voice-changing intro: {os.path.basename(path)}…", C["orange"])
                res=self._health_voice_change_video(path, key, vid)
                if res: return res
        return self._story_prep_intro(path)   # ensure audio for clean concat

    def _health_build_clips_with_intros(self, scene_clips):
        # INTRO 1 → start, ordered by number
        intro1=[]
        for p in self._h_intro1_files:
            if os.path.exists(p):
                n=_health_extract_num(p,"intro1")
                intro1.append((n if n is not None else 99999, p))
        intro1.sort(key=lambda x:x[0])
        # INTRO 2 → before scene N
        intro2_map={}
        for p in self._h_intro2_files:
            if os.path.exists(p):
                n=_health_extract_num(p,"intro2")
                if n is not None: intro2_map.setdefault(n, []).append(p)
        if not intro1 and not intro2_map:
            return scene_clips
        ordered=[]
        for _,p in intro1:
            pp=self._health_prep_intro(p)
            if pp: ordered.append(pp)
        total=len(self.blocks)
        for i,b in enumerate(self.blocks):
            scene_num=i+1
            for p in intro2_map.get(scene_num, []):
                pp=self._health_prep_intro(p)
                if pp: ordered.append(pp)
            op=b.get("output","")
            if op and os.path.exists(op): ordered.append(op)
        for n,paths in sorted(intro2_map.items()):
            if n>total:
                for p in paths:
                    pp=self._health_prep_intro(p)
                    if pp: ordered.append(pp)
        return ordered or scene_clips

    def _mw(self, clips, sp):
        # build the Health sequence (auto intros), then run the BASE merge
        try:
            clips=self._health_build_clips_with_intros(clips)
        except Exception as e:
            print("[HEALTH] intro build error:", e)
        AdvanceEditorFrame._mw(self, clips, sp)

    def _tab_help_title(self): return "Health"
    def _tab_help_steps(self):
        return ["Same as Story + auto dual-intro from filenames.","INTRO 1: Intro_Visual_1,2,3... at START sorted.","INTRO 2: Before_Scene_N... before scene N.","Optional: change intro voice (ElevenLabs STS)."]


class DiscoveryVideoEditorFrame(HealthVideoEditorFrame):
    """Discovery = Health, tuned for 'Only Video' mode with an optional SCENE
    voice-change: at render time each uploaded video's speech is re-voiced via
    ElevenLabs (only when ticked). Videos without audio are kept as-is."""
    def __init__(self, master):
        super().__init__(master)
        try:
            self.mode_var.set("video"); self._toggle_mode()
        except Exception: pass
        self._disc_voices=[]; self._disc_voice_map={}
        for attr in ("_health_intro_card","_story_intro_section_frame","_story_fx_card","_story_cap_card","_wb_card","_bgm_section_frame"):
            try: getattr(self, attr).grid_remove()
            except Exception: pass
        self._add_discovery_section()

    def _add_discovery_section(self):
        sb=getattr(self,"_sb_ref",None)
        if sb is None: return
        try:
            C_=C
            card=ctk.CTkFrame(sb, fg_color=C_["card"], border_color=C_["accent"], border_width=2, corner_radius=8)
            card.grid(row=898, column=0, sticky="ew", padx=6, pady=(4,6))
            ctk.CTkLabel(card, text="🔍 DISCOVERY — clips + voiceover narration", text_color=C_["accent"],
                         font=("Segoe UI",13,"bold")).pack(anchor="w", padx=10, pady=(8,2))
            ctk.CTkLabel(card, text="Upload clips + write script. Each scene's text becomes a voiceover\n(narrator voice). Clip audio ducks under narration, then returns.\nWrite VISUAL ONLY in text → no voiceover for that clip.",
                         text_color=C_["dim"], font=("Segoe UI",9), justify="left").pack(anchor="w", padx=10, pady=(0,2))
            # narrator voice
            rn=ctk.CTkFrame(card, fg_color="transparent"); rn.pack(fill="x", padx=10, pady=2)
            ctk.CTkButton(rn, text="🔄 Load voices", width=110, fg_color=C_["btn"], hover_color=C_["btn_hov"],
                          text_color=C_["text"], command=self._disc_load_voices).pack(side="left")
            r2=ctk.CTkFrame(card, fg_color="transparent"); r2.pack(fill="x", padx=10, pady=(2,8))
            ctk.CTkLabel(r2, text="Voice:", text_color=C_["dim"]).pack(side="left")
            self._disc_search_var=ctk.StringVar(value="")
            ctk.CTkEntry(r2, textvariable=self._disc_search_var, width=90, fg_color=C_["entry_bg"],
                         text_color=C_["text"], border_color=C_["border"], placeholder_text="search…").pack(side="left", padx=4)
            self._disc_search_var.trace_add("write", self._disc_filter_voices)
            self._disc_voice_var=ctk.StringVar(value=self.settings.get("disc_vc_voice") or "(load voices)")
            self._disc_voice_menu=ctk.CTkOptionMenu(r2, variable=self._disc_voice_var, values=["(load voices)"],
                                                    fg_color=C_["btn"], button_color=C_["btn_hov"], width=190,
                                                    command=lambda *_: self._disc_save())
            self._disc_voice_menu.pack(side="left", padx=4)

            # ── Clip audio ──
            ac=ctk.CTkFrame(sb, fg_color=C_["card"], border_color=C_["purple"], border_width=2, corner_radius=8)
            ac.grid(row=897, column=0, sticky="ew", padx=6, pady=(4,6))
            ctk.CTkLabel(ac, text="🔊 Clip audio", text_color=C_["purple"],
                         font=("Segoe UI",13,"bold")).pack(anchor="w", padx=10, pady=(8,2))
            ctk.CTkLabel(ac, text="The clip's own sound (set how loud it plays, or mute it).",
                         text_color=C_["dim"], font=("Segoe UI",9)).pack(anchor="w", padx=10, pady=(0,2))
            av=ctk.CTkFrame(ac, fg_color="transparent"); av.pack(fill="x", padx=10, pady=(2,8))
            ctk.CTkLabel(av, text="Clip volume", width=80, anchor="w", text_color=C_["text"]).pack(side="left")
            self._disc_clipvol=ctk.IntVar(value=int(self.settings.get("disc_clipvol")))
            self._disc_clipvol_lbl=ctk.CTkLabel(av, text=f"{self._disc_clipvol.get()}%", width=46, text_color=C_["dim"])
            ctk.CTkSlider(av, from_=0, to=200, variable=self._disc_clipvol, width=150,
                          command=lambda v:(self._disc_clipvol_lbl.configure(text=f"{int(float(v))}%"), self._disc_save())).pack(side="left", padx=6)
            self._disc_clipvol_lbl.pack(side="left")
            self._disc_mute=ctk.BooleanVar(value=bool(self.settings.get("disc_mute")))
            ctk.CTkCheckBox(av, text="Mute clip", variable=self._disc_mute, width=20,
                            text_color=C_["text"], fg_color=C_["red"], command=self._disc_save).pack(side="left", padx=10)

            # ── Background music ──
            bc=ctk.CTkFrame(sb, fg_color=C_["card"], border_color=C_["green"], border_width=2, corner_radius=8)
            bc.grid(row=896, column=0, sticky="ew", padx=6, pady=(4,6))
            ctk.CTkLabel(bc, text="🎵 Background music", text_color=C_["green"],
                         font=("Segoe UI",13,"bold")).pack(anchor="w", padx=10, pady=(8,2))
            bg1=ctk.CTkFrame(bc, fg_color="transparent"); bg1.pack(fill="x", padx=10, pady=(2,2))
            ctk.CTkButton(bg1, text="🎵 Select music", width=120, fg_color=C_["accent"], text_color="#000",
                          command=self._disc_pick_bgm).pack(side="left")
            self._disc_bgm_lbl=ctk.CTkLabel(bg1, text=(os.path.basename(self.bgm_var.get()) if self.bgm_var.get() else "no music"),
                                            text_color=C_["dim"]); self._disc_bgm_lbl.pack(side="left", padx=6)
            ctk.CTkLabel(bc, text="…or generate with ElevenLabs:", text_color=C_["dim"], font=("Segoe UI",9)).pack(anchor="w", padx=10, pady=(4,0))
            ctk.CTkEntry(bc, textvariable=self.bgm_prompt_var, fg_color=C_["entry_bg"], text_color=C_["text"],
                         border_color=C_["border"], placeholder_text="e.g. soft cinematic piano, calm, instrumental").pack(fill="x", padx=10, pady=2)
            bg2=ctk.CTkFrame(bc, fg_color="transparent"); bg2.pack(fill="x", padx=10, pady=(0,4))
            ctk.CTkLabel(bg2, text="Dur(s):", text_color=C_["dim"]).pack(side="left")
            ctk.CTkEntry(bg2, textvariable=self.bgm_gen_dur_var, width=46, fg_color=C_["entry_bg"], text_color=C_["text"],
                         border_color=C_["border"]).pack(side="left", padx=3)
            ctk.CTkButton(bg2, text="✨ Generate BGM", width=120, fg_color=C_["purple"], text_color="#fff",
                          command=self._disc_generate_bgm).pack(side="left", padx=4)
            bg3=ctk.CTkFrame(bc, fg_color="transparent"); bg3.pack(fill="x", padx=10, pady=(0,8))
            ctk.CTkLabel(bg3, text="Music vol", width=80, anchor="w", text_color=C_["text"]).pack(side="left")
            ctk.CTkEntry(bg3, textvariable=self.bgm_vol_var, width=54, fg_color=C_["entry_bg"], text_color=C_["text"],
                         border_color=C_["border"]).pack(side="left", padx=4)
            ctk.CTkLabel(bg3, text="(0.15 = 15%)", text_color=C_["dim"], font=("Segoe UI",8)).pack(side="left", padx=2)
            ctk.CTkCheckBox(bg3, text="Loop", variable=self.bgm_loop_var, width=20, text_color=C_["text"],
                            fg_color=C_["purple"]).pack(side="left", padx=8)
            ctk.CTkLabel(bc, text="Logo & captions: use the controls above (optional).",
                         text_color=C_["dim"], font=("Segoe UI",8)).pack(anchor="w", padx=10, pady=(0,8))
        except Exception as e:
            print("[WARN] discovery section:", e)

    def _disc_generate_bgm(self):
        # turn BGM on so the generated track is used in the merge, then generate
        try: self.bgm_enabled_var.set(True)
        except Exception: pass
        self._generate_bgm()
        try:
            if self.bgm_var.get(): self._disc_bgm_lbl.configure(text=os.path.basename(self.bgm_var.get()))
        except Exception: pass

    def _disc_pick_bgm(self):
        p=filedialog.askopenfilename(filetypes=[("Audio","*.mp3 *.wav *.m4a *.aac *.ogg *.flac")])
        if p:
            self.bgm_var.set(p); self.bgm_enabled_var.set(True)
            try: self._disc_bgm_lbl.configure(text=os.path.basename(p))
            except Exception: pass
            self._disc_save()

    def _tab_help_title(self): return "Discovery"
    def _tab_help_steps(self):
        return ["Upload video clips (Only Video mode).","Write STORY SCRIPT: text = voiceover narration.","VISUAL ONLY in text = no voiceover, clip as-is.","Pick NARRATOR VOICE: Load voices, search, select.","Voiceover at START + clip DUCKS, then full volume.","Clip volume slider 0-200% or Mute.","BGM: select file or Generate with ElevenLabs.","LOGO: controls in left panel (optional).","MERGE to render final output."]

    def _disc_apply_clipvol(self, b):
        """Set this block's clip volume from the Discovery control (0 if muted)."""
        try:
            if getattr(self,"_disc_mute",None) and self._disc_mute.get():
                b["clip_volume"]=0
            elif hasattr(self,"_disc_clipvol"):
                b["clip_volume"]=int(self._disc_clipvol.get())
        except Exception: pass

    def _disc_save(self):
        try:
            self.settings.set("disc_vc_on", bool(self._disc_vc_on.get()))
            self.settings.set("disc_vc_rmbg", bool(self._disc_vc_rmbg.get()))
            if hasattr(self,"_disc_keepbg"): self.settings.set("disc_keepbg", bool(self._disc_keepbg.get()))
            if hasattr(self,"_disc_clipvol"): self.settings.set("disc_clipvol", int(self._disc_clipvol.get()))
            if hasattr(self,"_disc_mute"): self.settings.set("disc_mute", bool(self._disc_mute.get()))
            self.settings.set("disc_vc_voice", self._disc_voice_var.get())
            self.settings.save()
        except Exception: pass

    def _disc_load_voices(self):
        key=self._h_api_key()
        if not key:
            messagebox.showwarning("API key","Enter your ElevenLabs API key (top of the editor) first."); return
        self._ss("Loading voices…", C["orange"])
        def work():
            try:
                r=requests.get("https://api.elevenlabs.io/v1/voices",headers={"xi-api-key":key},timeout=30); r.raise_for_status()
                vs=[(v.get("name","?"),v.get("voice_id","")) for v in r.json().get("voices",[])]
                self._disc_voices=vs; self._disc_voice_map={n:i for n,i in vs}
                names=[n for n,_ in vs] or ["(none)"]
                self.after(0, lambda:(self._disc_voice_menu.configure(values=names), self._disc_voice_var.set(names[0])))
                self._ss(f"✓ Loaded {len(vs)} voices", C["green"])
            except Exception as e:
                self._ss(f"Voice load error: {str(e)[:50]}", C["red"])
        threading.Thread(target=work, daemon=True).start()

    def _disc_filter_voices(self, *a):
        q=self._disc_search_var.get().strip().lower()
        names=[n for n,_ in self._disc_voices if q in n.lower()] if self._disc_voices else []
        if not names: names=["(no match)"]
        try:
            self._disc_voice_menu.configure(values=names)
            if names[0]!="(no match)": self._disc_voice_var.set(names[0])
        except Exception: pass

    def _disc_resolve_voice_id(self):
        return self._disc_voice_map.get(self._disc_voice_var.get(), "")

    def _disc_voice_change_video(self, video):
        vid=self._disc_resolve_voice_id(); key=self._h_api_key()
        if not (vid and key): return None
        tag=abs(hash((os.path.abspath(video), vid, "kb")))%999999
        out=os.path.join(TEMP_DIR, f"disc_vc_{tag}.mp4")
        if os.path.exists(out) and get_duration(out)>0.1: return out
        keep_bg=bool(getattr(self,"_disc_keepbg",None) and self._disc_keepbg.get())
        if keep_bg and not _has_demucs():
            self._sss("Demucs not installed → background can't be kept; re-voicing whole track. (pip install demucs)")
        return _voice_change_clip(video, vid, key, "eleven_multilingual_sts_v2",
                                  bool(self._disc_vc_rmbg.get()), out, keep_bg=keep_bg,
                                  logf=lambda m: self._sss(m))

    def _disc_tts_model(self):
        try:
            mn=self.model_var.get()
            for m in getattr(self,"models",[]):
                if m.get("name","")==mn: return m.get("model_id","") or "eleven_multilingual_v2"
        except Exception: pass
        return "eleven_multilingual_v2"

    def _disc_overlay_voiceover(self, idx, op):
        """`op` is the already-rendered FULL-duration clip. Generate a TTS voiceover
        from the scene text and overlay it at the START with ducking (+ fades). The
        clip keeps its full length; its own audio returns to full once the voice ends."""
        b=self.blocks[idx]; orig_text=b.get("text","") or ""
        vid=self._disc_resolve_voice_id(); key=self._h_api_key()
        if not (vid and key):
            self._sss(f"voiceover needs a voice + API key (scene {b['num']})"); return
        self._ss(f"Voiceover TTS (scene {b['num']})…", C["orange"])
        nar=os.path.join(TEMP_DIR, f"disc_nar_{b['num']}_{abs(hash(orig_text))%99999}.mp3")
        if not _tts_simple(orig_text, vid, key, self._disc_tts_model(), nar):
            self._sss(f"voiceover TTS failed (scene {b['num']})"); return
        out=os.path.join(TEMP_DIR, f"disc_blend_{b['num']}.mp4")
        self._ss(f"Blending voiceover + ducking (scene {b['num']})…", C["orange"])
        if _blend_narration_duck(op, nar, out):
            b["output"]=out

    def _gw(self, idx):
        b=self.blocks[idx]
        self._disc_apply_clipvol(b)   # clip's own volume / mute (Discovery control)
        text=(b.get("text","") or "").strip()
        # Robust "VISUAL ONLY" detection — matches VISUAL ONLY / Visual_Only / visual-only etc.
        norm=re.sub(r"[^a-z]", "", text.lower())
        is_visual_only = "visualonly" in norm
        want_vo = (not is_visual_only) and bool(text)

        # ALWAYS render the clip at its FULL natural duration — never stretch/trim it to
        # the voiceover length. Forcing video_only makes the base skip TTS-compose, so the
        # whole clip plays. (VISUAL ONLY clips therefore also just play as-is, no voiceover.)
        orig_text=b.get("text",""); prev_vo=b.get("video_only")
        b["text"] = orig_text if want_vo else ""     # keep text (captions) only when narrating
        b["video_only"]=True
        try:
            super()._gw(idx)
        finally:
            b["text"]=orig_text; b["video_only"]=prev_vo

        op=b.get("output","")
        if not op or not os.path.exists(op): return
        # VISUAL ONLY, or blend off, or no text → the clip plays exactly as-is (own audio, full length).
        if not want_vo:
            return
        # Voiceover requested → overlay at start + ducking (+ fades), keeping the full clip length.
        self._disc_overlay_voiceover(idx, op)


def create(frame):
    print("=== Video Master Tool — BUILD v13.10 STORY-FX (Discovery: VISUAL ONLY skips voiceover + voice fade in-out) ===")
    container = ctk.CTkFrame(frame, fg_color=C["bg"], corner_radius=0)
    container.pack(fill="both", expand=True)
    container.grid_columnconfigure(0, weight=1); container.grid_rowconfigure(1, weight=1)
    header = ctk.CTkFrame(container, fg_color=C["card"], height=50, corner_radius=0)
    header.grid(row=0, column=0, sticky="ew"); header.grid_propagate(False)
    ctk.CTkLabel(header, text="🎬  STORY VIDEO EDITOR",text_color=C["purple"], font=("Segoe UI", 16, "bold")).pack(side="left", padx=15, pady=10)
    ctk.CTkLabel(header, text=f"v13.10 STORY-FX • {GPU.info_str()}",text_color=C["dim"], font=("Segoe UI", 10)).pack(side="left", padx=10)
    # Output resolution / quality (applies to the final render of every tab)
    _res_var = ctk.StringVar(value=_OUTPUT_RES_CHOICE)
    ctk.CTkLabel(header, text="Output:", text_color=C["dim"], font=("Segoe UI", 11)).pack(side="right", padx=(6,2))
    ctk.CTkOptionMenu(header, variable=_res_var, values=list(_OUTPUT_PRESETS.keys()),
                      width=130, fg_color=C["btn"], button_color=C["btn_hov"],
                      command=lambda v: _set_output_res(v)).pack(side="right", padx=(0,12), pady=8)
    tabview = ctk.CTkTabview(container, fg_color=C["bg"],
        segmented_button_fg_color=C["card"], segmented_button_selected_color=C["purple"],
        segmented_button_selected_hover_color=C["accent"], segmented_button_unselected_color=C["btn"],
        segmented_button_unselected_hover_color=C["btn_hov"], text_color=C["text"], corner_radius=8)
    tabview.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
    tab_basic = tabview.add("📝 Simple Editor"); tab_news = tabview.add("📰  News Editor"); tab_advance = tabview.add("🎭  Advance Editor"); tab_shorts = tabview.add("📱  Shorts"); tab_master = tabview.add("🎬  Video Master"); tab_story = tabview.add("📖  Story Video"); tab_health = tabview.add("🏥  Health"); tab_discovery = tabview.add("🔍  Discovery")
    for t in (tab_basic, tab_news, tab_advance, tab_shorts, tab_master, tab_story, tab_health, tab_discovery):
        t.grid_columnconfigure(0, weight=1); t.grid_rowconfigure(0, weight=1)
    _mounted = {"basic": False, "news": False, "advance": False, "shorts": False, "master": False, "story": False, "health": False, "discovery": False}
    def _mount_basic():
        if _mounted["basic"]: return
        SimpleEditorFrame(tab_basic).grid(row=0, column=0, sticky="nsew"); _mounted["basic"] = True
    def _mount_news():
        if _mounted["news"]: return
        NewsEditorFrame(tab_news).grid(row=0, column=0, sticky="nsew"); _mounted["news"] = True
    def _mount_advance():
        if _mounted["advance"]: return
        AdvanceEditorFrame(tab_advance).grid(row=0, column=0, sticky="nsew"); _mounted["advance"] = True
    def _mount_shorts():
        if _mounted["shorts"]: return
        ShortsEditorFrame(tab_shorts).grid(row=0, column=0, sticky="nsew"); _mounted["shorts"] = True
    def _mount_master():
        if _mounted["master"]: return
        VideoMasterEditorFrame(tab_master).grid(row=0, column=0, sticky="nsew"); _mounted["master"] = True
    def _mount_story():
        if _mounted["story"]: return
        StoryVideoEditorFrame(tab_story).grid(row=0, column=0, sticky="nsew"); _mounted["story"] = True
    def _mount_health():
        if _mounted["health"]: return
        HealthVideoEditorFrame(tab_health).grid(row=0, column=0, sticky="nsew"); _mounted["health"] = True
    def _mount_discovery():
        if _mounted["discovery"]: return
        DiscoveryVideoEditorFrame(tab_discovery).grid(row=0, column=0, sticky="nsew"); _mounted["discovery"] = True
    _mount_basic()
    def _on_tab_change():
        try:
            cur = tabview.get()
            if "Simple" in cur: _mount_basic()
            elif "News" in cur: _mount_news()
            elif "Advance" in cur: _mount_advance()
            elif "Shorts" in cur: _mount_shorts()
            elif "Master" in cur: _mount_master()
            elif "Discovery" in cur: _mount_discovery()
            elif "Health" in cur: _mount_health()
            elif "Story" in cur: _mount_story()
        except: pass
    def _poll():
        _on_tab_change()
        try: frame.after(400, _poll)
        except: pass
    frame.after(400, _poll)


# ════════════════════════════════════════════════════════════════
# STANDALONE TEST
# ════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    root.title(f"{TITLE} — Standalone Test")
    root.geometry("1450x800"); root.minsize(1200, 680); root.configure(fg_color=C["bg"])
    test_frame = ctk.CTkFrame(root, fg_color=C["bg"]); test_frame.pack(fill="both", expand=True)
    create(test_frame)
    root.mainloop()
