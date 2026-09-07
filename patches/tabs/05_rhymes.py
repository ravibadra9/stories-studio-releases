# tabs/05_rhymes.py
"""
05_rhymes.py — 🎤 Rhymes Editor
tabs/ mein daalo → automatic tab ban jayega.
"""

TAB_TITLE = "🎤  Rhymes"
TAB_ORDER = 35
TAB_GROUP = ""
TAB_COLOR = ("#ec4899", "#f472b6")
TAB_ICON  = "🎤"
LAZY_LOAD = True

# ════════════════════════════════════════════════════════════════
# NOTE: Purana file-based owner-lock hata diya gaya hai.
# Ab licensing main.py + auth_manager.py (Firebase + hardware lock)
# handle karta hai. Yeh file ab sirf UI/engine hai.
# ════════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════════
# TAB METADATA (required by launcher)
# ════════════════════════════════════════════════════════════════
# Version ek hi jagah se aata hai (updater.py). release.py wahi bump karta hai.
try:
    from updater import CURRENT_VERSION as APP_VERSION
except Exception:
    APP_VERSION = "dev"

TITLE    = "Rhymes Video Editor"
SUBTITLE = "Rhymes Audio + Scene Videos • ElevenLabs Scribe Captions • GPU Accelerated"
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
import lazy_menu  # Win32 / TCL native menu limit fix

# ── Never flash a console window when calling ffmpeg / ffprobe / etc. ──
# On Windows every subprocess.run/Popen without this pops a black CMD box for
# a split second — dozens of them during a render = the "flickering CMD" the
# user sees. CREATE_NO_WINDOW + a hidden STARTUPINFO suppress it completely.
# Merge _NO_WINDOW into EVERY subprocess call in this file.
if os.name == "nt":
    _si = subprocess.STARTUPINFO()
    _si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _si.wShowWindow = 0  # SW_HIDE
    _NO_WINDOW = {"creationflags": 0x08000000,  # CREATE_NO_WINDOW
                  "startupinfo": _si}

    # Patching our own call sites isn't enough: THIRD-PARTY libraries spawn
    # processes too (Whisper shells out to ffmpeg to decode audio, pygame and
    # torch probe the system, pip runs child processes…). Each one pops its own
    # console window. Patching Popen itself — which run/call/check_output all
    # funnel through — makes every process in this app window-less, ours and
    # theirs alike.
    _orig_popen_init = subprocess.Popen.__init__

    def _popen_no_window(self, *args, **kwargs):
        try:
            kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | 0x08000000
            if kwargs.get("startupinfo") is None:
                _s = subprocess.STARTUPINFO()
                _s.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                _s.wShowWindow = 0
                kwargs["startupinfo"] = _s
        except Exception:
            pass
        return _orig_popen_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _popen_no_window
else:
    _NO_WINDOW = {}
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import collections

import customtkinter as ctk
import tkinter as tk

# ════════════════════════════════════════════════════════════════
# WINDOWS / VM DISPLAY ADAPTER DETECTION
# For Hyper-V / basic virtual adapters, CustomTkinter's Windows titlebar
# recolor path can leave CTkToplevel client areas black. We keep the rest
# of the app intact, but disable ONLY that Windows titlebar manipulation
# and use plain Tk toplevel shells for the caption/preview dialogs.
# Logo/file-dialog behaviour is intentionally left untouched.
# ════════════════════════════════════════════════════════════════
def _should_disable_ctk_windows_titlebar_hack():
    if os.name != "nt":
        return False
    try:
        import hardware_accel
        hw = hardware_accel.get_hardware_info()
        gpu_name = (hw.get("gpu_name") or "").lower()
        suspects = ("hyper-v", "basic display", "remote display", "virtualbox", "vmware", "parallels", "qxl", "virtio", "citrix", "rdpudd")
        return any(s in gpu_name for s in suspects)
    except Exception:
        return False

_CTKTOPLEVEL_PLAIN_TITLEBAR = _should_disable_ctk_windows_titlebar_hack()
if _CTKTOPLEVEL_PLAIN_TITLEBAR:
    try:
        ctk.CTkToplevel._deactivate_windows_window_header_manipulation = True
    except Exception:
        pass

# ════════════════════════════════════════════════════════════════
# BLANK-DIALOG FIX (Hyper-V / some VM display drivers)
# On certain virtual displays (seen on Hyper-V's basic video adapter),
# CTkToplevel windows sometimes open completely unpainted — the window
# frame shows but none of its child widgets ever draw, staying solid
# black, until the user manually resizes/moves it. No Python exception
# is raised (it's a Windows/Tk paint issue, not a code bug), which is
# why this was invisible in every crash log.
# Fix: force a repaint shortly after EVERY dialog opens, app-wide, via
# the classic "nudge -alpha" trick that makes Windows recomposite the
# window. Patched once here instead of touching each of the several
# CTkToplevel subclasses scattered through this file.
if not getattr(ctk.CTkToplevel, "_is_repaint_patched", False):
    ctk.CTkToplevel._is_repaint_patched = True
    _orig_ctktoplevel_init = ctk.CTkToplevel.__init__
    def _patched_ctktoplevel_init(self, *a, **kw):
        _orig_ctktoplevel_init(self, *a, **kw)
        def _force_repaint():
            try:
                self.update_idletasks()
                w = self.winfo_width(); h = self.winfo_height()
                x = self.winfo_x(); y = self.winfo_y()
                if w > 10 and h > 10:
                    self.geometry(f"{w+1}x{h+1}+{x}+{y}")
                    self.update()
                    self.geometry(f"{w}x{h}+{x}+{y}")
                    self.update()
                try:
                    self.attributes("-alpha", 0.99)
                    self.update()
                    self.attributes("-alpha", 1.0)
                except Exception:
                    pass
                try:
                    n_children = len(self.winfo_children())
                    mapped = self.winfo_ismapped()
                    print(f"[REPAINT-DEBUG] toplevel={self.title()!r} "
                          f"children={n_children} mapped={mapped} size={w}x{h} "
                          f"plain_titlebar={_CTKTOPLEVEL_PLAIN_TITLEBAR}")
                except Exception:
                    pass
            except Exception:
                pass
        try:
            self.after(60, _force_repaint)
            self.after(400, _force_repaint)
        except Exception:
            pass
    ctk.CTkToplevel.__init__ = _patched_ctktoplevel_init

# ════════════════════════════════════════════════════════════════
# PREMIUM POLISH LAYER
# Har CTk widget ko professional defaults deta hai — rounded corners,
# consistent font, borders, hover — bina 12,000 lines chhue. Jahan code
# ne explicitly kuch set kiya hai, wahi jeetata hai (defaults sirf
# missing values bharte hain).
# ════════════════════════════════════════════════════════════════
_UI_FONT = "Segoe UI"

def _patch_widget_defaults(cls, defaults):
    flag_name = f"_patched_{cls.__name__}_defaults"
    if getattr(cls, flag_name, False):
        return
    setattr(cls, flag_name, True)
    orig_init = cls.__init__
    def __init__(self, *args, **kwargs):
        merged = dict(defaults)
        merged.update(kwargs)          # explicit values hamesha jeetein
        orig_init(self, *args, **merged)
    cls.__init__ = __init__

def _apply_premium_polish():
    P = {
        "bg": "#0a0a10", "card": "#12121c", "border": "#262638",
        "text": "#f0f0f6", "dim": "#8f8fa8",
        "purple": "#8b5cf6", "purple_hi": "#a78bfa",
        "btn": "#1a1a2a", "btn_hov": "#26263c", "entry": "#0c0c14",
    }
    _patch_widget_defaults(ctk.CTkButton, {
        "corner_radius": 9,
        "font": (_UI_FONT, 12),
        "border_width": 0,
    })
    _patch_widget_defaults(ctk.CTkEntry, {
        "corner_radius": 8,
        "border_width": 1,
        "border_color": P["border"],
        "fg_color": P["entry"],
        "font": (_UI_FONT, 12),
    })
    _patch_widget_defaults(ctk.CTkTextbox, {
        "corner_radius": 10,
        "border_width": 1,
        "border_color": P["border"],
        "font": (_UI_FONT, 12),
    })
    _patch_widget_defaults(ctk.CTkOptionMenu, {
        "corner_radius": 8,
        "font": (_UI_FONT, 12),
        "fg_color": P["btn"],
        "button_color": P["btn_hov"],
        "button_hover_color": P["purple"],
        "dropdown_fg_color": P["card"],
        "dropdown_hover_color": P["btn_hov"],
        "dropdown_font": (_UI_FONT, 12),
    })
    _patch_widget_defaults(ctk.CTkComboBox, {
        "corner_radius": 8,
        "font": (_UI_FONT, 12),
        "border_width": 1,
        "border_color": P["border"],
        "fg_color": P["entry"],
        "button_color": P["btn_hov"],
        "button_hover_color": P["purple"],
        "dropdown_fg_color": P["card"],
        "dropdown_hover_color": P["btn_hov"],
    })
    _patch_widget_defaults(ctk.CTkSlider, {
        "button_color": P["purple"],
        "button_hover_color": P["purple_hi"],
        "progress_color": P["purple"],
        "fg_color": P["btn_hov"],
        "button_corner_radius": 8,
    })
    _patch_widget_defaults(ctk.CTkCheckBox, {
        "corner_radius": 5,
        "border_width": 2,
        "border_color": P["border"],
        "fg_color": P["purple"],
        "hover_color": P["purple_hi"],
        "checkmark_color": "#ffffff",
        "font": (_UI_FONT, 12),
    })
    _patch_widget_defaults(ctk.CTkRadioButton, {
        "border_color": P["border"],
        "fg_color": P["purple"],
        "hover_color": P["purple_hi"],
        "font": (_UI_FONT, 12),
    })
    _patch_widget_defaults(ctk.CTkSwitch, {
        "progress_color": P["purple"],
        "button_color": "#ffffff",
        "fg_color": P["btn_hov"],
        "font": (_UI_FONT, 12),
    })
    _patch_widget_defaults(ctk.CTkProgressBar, {
        "corner_radius": 4,
        "progress_color": P["purple"],
        "fg_color": P["entry"],
    })
    _patch_widget_defaults(ctk.CTkScrollableFrame, {
        "corner_radius": 12,
        "scrollbar_button_color": P["btn_hov"],
        "scrollbar_button_hover_color": P["purple"],
    })
    _patch_widget_defaults(ctk.CTkTabview, {
        "corner_radius": 10,
        "segmented_button_selected_color": P["purple"],
        "segmented_button_selected_hover_color": P["purple_hi"],
        "segmented_button_unselected_color": P["btn"],
        "segmented_button_unselected_hover_color": P["btn_hov"],
    })

_apply_premium_polish()

from tkinter import filedialog, messagebox, Canvas, colorchooser, simpledialog, TclError


def _style_toplevel_bg(win, color):
    try:
        win.configure(fg_color=color)
    except Exception:
        try: win.configure(bg=color)
        except Exception: pass


_BASIC_VM_TOPLEVEL = tk.Toplevel if _CTKTOPLEVEL_PLAIN_TITLEBAR else ctk.CTkToplevel


def _asksaveasfilename_safe(parent=None, title="Save File", defaultextension="", initialdir="", initialfile="", filetypes=None, **kwargs):
    try:
        return filedialog.asksaveasfilename(
            parent=parent,
            title=title,
            defaultextension=defaultextension,
            initialdir=initialdir,
            initialfile=initialfile,
            filetypes=filetypes,
            **kwargs,
        )
    except TclError as e:
        print(f"[SAVE-DIALOG] native save dialog failed: {e}")
        seed = os.path.join(initialdir or "", initialfile or "").strip() or (initialfile or "")
        p = simpledialog.askstring(
            title,
            "Save dialog iss machine pe fail ho gaya.\n\nFull output path paste karo.",
            initialvalue=seed,
            parent=parent,
        )
        if not p:
            return ""
        p = p.strip().strip('"')
        if defaultextension and os.path.splitext(p)[1] == "":
            p += defaultextension
        return p


def _write_json_atomic(path, data):
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        print(f"[SETTINGS] save failed: {e}")


def _queue_settings_save(widget, settings_mgr, delay=250, attr_name="_settings_save_job"):
    try:
        old = getattr(widget, attr_name, None)
        if old:
            widget.after_cancel(old)
    except Exception:
        pass

    def _flush():
        try:
            setattr(widget, attr_name, None)
        except Exception:
            pass
        try:
            snapshot = dict(settings_mgr.data)
        except Exception:
            snapshot = {}
        threading.Thread(
            target=lambda snap=snapshot: _write_json_atomic(SETTINGS_FILE, snap),
            daemon=True,
        ).start()

    try:
        setattr(widget, attr_name, widget.after(delay, _flush))
    except Exception:
        try:
            settings_mgr.save()
        except Exception:
            pass

from PIL import Image, ImageTk, ImageDraw
import requests
import voice_cache
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

# ── Live-process registry — lets Stop actually kill ffmpeg immediately ──
_ACTIVE_PROCS = set()
_ACTIVE_PROCS_LOCK = threading.Lock()

def _register_active_proc(p):
    with _ACTIVE_PROCS_LOCK:
        _ACTIVE_PROCS.add(p)

def _unregister_active_proc(p):
    with _ACTIVE_PROCS_LOCK:
        _ACTIVE_PROCS.discard(p)

def kill_all_active_procs():
    """Kill every ffmpeg/ffprobe process started right now.
    Call this the instant Stop/Abort is pressed — not just after the current
    step finishes — so Stop really means immediate kill."""
    with _ACTIVE_PROCS_LOCK:
        procs = list(_ACTIVE_PROCS)
        _ACTIVE_PROCS.clear()
    for p in procs:
        try:
            p.kill()
        except Exception:
            pass
    if os.name == "nt":
        try:
            _si = subprocess.STARTUPINFO()
            _si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            _si.wShowWindow = 0
            subprocess.run(["taskkill", "/F", "/IM", "ffmpeg.exe", "/T"],
                           capture_output=True, startupinfo=_si, creationflags=0x08000000)
            subprocess.run(["taskkill", "/F", "/IM", "ffprobe.exe", "/T"],
                           capture_output=True, startupinfo=_si, creationflags=0x08000000)
        except Exception:
            pass

def _run_ff(cmd, timeout=300):
    """Safe subprocess runner for ffmpeg — handles Windows encoding issues
    and, crucially, never flashes a console window."""
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace", **_NO_WINDOW)
        _register_active_proc(proc)
        try:
            out, err = proc.communicate(timeout=timeout)
            return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
        finally:
            _unregister_active_proc(proc)
    except subprocess.TimeoutExpired:
        try: proc.kill()
        except Exception: pass
        return None
    except Exception:
        return None

def _run_ff_live(cmd, duration=0.0, on_progress=None, timeout=3600):
    """Run ffmpeg subprocess with realtime frame-by-frame progress streaming.
    Calls on_progress(frac, label, frame, fps, speed) on every update."""
    if not on_progress:
        return _run_ff(cmd, timeout=timeout)
    
    cmd_list = [str(x) for x in cmd]
    if "-progress" not in cmd_list:
        cmd_run = list(cmd_list[:-1]) + ["-progress", "pipe:1", "-nostats", cmd_list[-1]]
    else:
        cmd_run = list(cmd_list)
    
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        
    try:
        proc = subprocess.Popen(
            cmd_run,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags
        )
        _register_active_proc(proc)
    except Exception:
        return _run_ff(cmd, timeout=timeout)

    cur_time = 0.0
    frame_num = 0
    fps_val = "0"
    speed_val = "1.0x"
    tail_lines = collections.deque(maxlen=30)
    
    time_re = re.compile(r"out_time=(\d+):(\d+):(\d+\.\d+)")
    time_ms_re = re.compile(r"out_time_ms=(\d+)")
    time_alt_re = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
    
    last_update = 0.0
    
    try:
        for line in proc.stdout:
            line_s = line.strip()
            if not line_s:
                continue
            tail_lines.append(line_s)
            
            if line_s.startswith("frame="):
                try: frame_num = int(line_s.split("=", 1)[1].strip())
                except Exception: pass
            elif line_s.startswith("fps="):
                fps_val = line_s.split("=", 1)[1].strip()
            elif line_s.startswith("speed="):
                speed_val = line_s.split("=", 1)[1].strip()
            elif line_s.startswith("out_time="):
                m = time_re.search(line_s)
                if m:
                    cur_time = int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))
            elif line_s.startswith("out_time_ms="):
                m = time_ms_re.search(line_s)
                if m:
                    cur_time = float(m.group(1)) / 1000000.0
            else:
                m = time_alt_re.search(line_s)
                if m:
                    cur_time = int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))
            
            now = time.time()
            if now - last_update >= 0.12 or line_s.startswith("progress=end"):
                last_update = now
                if duration > 0.05:
                    frac = max(0.0, min(1.0, cur_time / duration))
                    pct_int = int(frac * 100)
                    total_f = max(1, int(round(duration * 30.0)))
                    prog_str = f"Frame {frame_num}/{total_f} ({pct_int}%) • {fps_val} fps • {speed_val}"
                else:
                    frac = 0.5
                    prog_str = f"Frame {frame_num} • {fps_val} fps • {speed_val}"
                try:
                    on_progress(frac, prog_str, frame_num, fps_val, speed_val)
                except Exception:
                    pass
        
        proc.wait(timeout=timeout)
    except Exception:
        try: proc.kill()
        except Exception: pass
    finally:
        _unregister_active_proc(proc)
        
    class _Res:
        returncode = proc.returncode
        stderr = "\n".join(tail_lines)
    
    return _Res()

# ════════════════════════════════════════════════════════════════
# PATHS & CONSTANTS
# ════════════════════════════════════════════════════════════════
# ── App root ─────────────────────────────────────────────────────
# Purana code `.parent.parent` karta tha kyunki file `tabs/` subfolder
# mein thi. Ab file root pe hai, toh `.parent.parent` C:\ pe pahunch
# jata tha — jahan Windows likhne nahi deta. Isliye GPU ka test-encode
# fail hota tha aur NVENC hone ke bawajood app CPU pe gir jata tha.
#
# Frozen exe (Program Files) mein bhi likhna allowed nahi hai, isliye
# writable data ab hamesha LOCALAPPDATA mein jayega.
if getattr(sys, "frozen", False):
    _APP_ROOT = Path(sys.executable).resolve().parent
else:
    _APP_ROOT = Path(__file__).resolve().parent

_DATA_ROOT = Path(os.environ.get("LOCALAPPDATA",
                                 os.path.expanduser("~"))) / "StoriesStudio"

SCRIPT_DIR = _APP_ROOT                       # ffmpeg.exe / assets yahan hain
TEMP_DIR   = str(_DATA_ROOT / "temp_work")
OUTPUT_DIR = str(Path.home() / "Videos" / "StoriesStudio")

os.makedirs(TEMP_DIR, exist_ok=True)
try:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
except Exception as _out_dir_err:
    # Some Windows accounts have a relocated or broken "Videos" shell folder
    # (OneDrive Folder Backup redirect, a dangling junction, a corporate
    # policy path, etc.) — on those, even os.makedirs(exist_ok=True) can't
    # create a subfolder underneath it and raises WinError 2, which used to
    # crash the whole app before the GUI ever opened. Fall back to a
    # location under LOCALAPPDATA that we already know is writable (TEMP_DIR
    # just succeeded there) instead of hard-failing at startup.
    print(f"[PATHS] Preferred OUTPUT_DIR ('{OUTPUT_DIR}') failed: {_out_dir_err} "
          f"— falling back to LOCALAPPDATA\\StoriesStudio\\output")
    OUTPUT_DIR = str(_DATA_ROOT / "output")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── FFmpeg ko app folder se hi utha ──────────────────────────────
# Bare "ffmpeg" naam PATH pe depend karta hai — user ke system pe kuch
# aur build mil sakta hai (ya kuch bhi nahi). Bundled binary pin kar do.
_FF_LOCAL = _APP_ROOT / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
if _FF_LOCAL.exists():
    os.environ["PATH"] = str(_APP_ROOT) + os.pathsep + os.environ.get("PATH", "")

SETTINGS_FILE  = os.path.join(TEMP_DIR, "app_settings.json")
TTS_CACHE_FILE = os.path.join(TEMP_DIR, "tts_cache.json")

# Parallelism scales with the actual machine. On a weak new laptop, spawning
# 4 simultaneous ffmpeg encodes pins every core and the UI stops repainting
# (the "no smoothness / laggy" feeling). Cap FF workers to half the cores.
_CPU = os.cpu_count() or 4
MAX_PARALLEL_TTS = 3                       # network-bound → fine to keep at 3
MAX_PARALLEL_FF  = max(2, min(4, _CPU // 2))  # NVENC supports 3 concurrent encodes

VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".tif")
MEDIA_EXTS = VIDEO_EXTS + IMAGE_EXTS

# ════════════════════════════════════════════════════════════════
# APPEARANCE — dark/light theme + accent color, chosen from the
# "🎨 Theme" button in the header. Applied on next launch (rebuilding
# every already-created widget's colours live isn't practical — this
# is read once, here, at startup).
# ════════════════════════════════════════════════════════════════
_THEME_BASES = {
    "dark": {
        "bg": "#0a0a10", "card": "#12121c", "border": "#262638",
        "text": "#f0f0f6", "dim": "#8f8fa8",
        "green": "#34d399", "red": "#fb7185", "orange": "#f5a623",
        "btn": "#1a1a2a", "btn_hov": "#26263c",
        "entry_bg": "#0c0c14",
        "side_bg": "#101018", "main_bg": "#0a0a10",
        "toolbar_bg": "#101018", "card_bg": "#171726",
    },
    "light": {
        "bg": "#f5f5fa", "card": "#ffffff", "border": "#dcdce6",
        "text": "#16161f", "dim": "#6b6b80",
        "green": "#0f9d68", "red": "#e0455a", "orange": "#c9791a",
        "btn": "#eceef5", "btn_hov": "#dfe1ec",
        "entry_bg": "#ffffff",
        "side_bg": "#f0f1f7", "main_bg": "#f5f5fa",
        "toolbar_bg": "#f0f1f7", "card_bg": "#ffffff",
    },
}
_THEME_ACCENTS = {
    "purple": "#8b5cf6",
    "blue":   "#3b82f6",
    "pink":   "#ec4899",
    "teal":   "#14b8a6",
    "orange": "#f97316",
    "red":    "#ef4444",
    "green":  "#22c55e",
    "gold":   "#eab308",
}

def _load_theme_pref():
    """Reads ui_theme/ui_accent straight from the settings JSON file —
    SettingsManager doesn't exist yet this early in module load, so this
    is a small standalone, fully guarded read (missing/corrupt file just
    falls back to the exact original defaults, no visual change)."""
    theme, accent = "dark", "purple"
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        theme = d.get("ui_theme", theme)
        accent = d.get("ui_accent", accent)
    except Exception:
        pass
    if theme not in _THEME_BASES: theme = "dark"
    if accent not in _THEME_ACCENTS: accent = "purple"
    return theme, accent

_UI_THEME, _UI_ACCENT = _load_theme_pref()
_UI_ACCENT_HEX = _THEME_ACCENTS[_UI_ACCENT]

def _hex_lighten(hexc, amt=0.28):
    hexc = hexc.lstrip("#")
    r, g, b = int(hexc[0:2], 16), int(hexc[2:4], 16), int(hexc[4:6], 16)
    r = int(r + (255 - r) * amt); g = int(g + (255 - g) * amt); b = int(b + (255 - b) * amt)
    return f"#{r:02x}{g:02x}{b:02x}"

C = dict(_THEME_BASES[_UI_THEME])
C["purple"] = _UI_ACCENT_HEX
C["accent"] = _UI_ACCENT_HEX if _UI_ACCENT != "purple" else "#a78bfa"   # original lighter tint, preserved
C["accent_hov"] = _UI_ACCENT_HEX

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
    print(f"[RES-DEBUG] _set_output_res called with v={v!r}")
    if v in _OUTPUT_PRESETS:
        _OUTPUT_RES_CHOICE = v
        print(f"[RES-DEBUG] _OUTPUT_RES_CHOICE now = {_OUTPUT_RES_CHOICE!r}")
        try:
            with open(_RES_CFG, "w", encoding="utf-8") as f:
                json.dump({"res": v}, f)
        except Exception:
            pass

def _finalize_output_resolution(path, res_key=None, log=None, on_progress=None):
    """Scale the finished video up to the chosen output resolution. 1K = native
    (no change).

    IMPORTANT: this is a pure quality/resolution upscale — it must NOT change
    framing. The old version always forced the output onto an exact 16:9 w×h
    canvas via `scale=...:decrease` + `pad`. That's a no-op when the finished
    video is already exactly that aspect ratio, but whenever a project's real
    aspect ratio differed even a little (e.g. scenes built from non-16:9
    source images), the pad added visible bars and shoved the
    ALREADY-COMPOSITED frame — including any baked-in logo — toward the
    center. That's exactly why the logo drift only showed up at 2K/4K: at 1K
    this function returns immediately and never touches the file.
    Fix: scale up by whatever factor is needed to reach the target on its
    tightest dimension, keeping the source's own aspect ratio exactly as
    rendered. No pad, no crop, nothing already baked in gets repositioned."""
    res_key = res_key or _OUTPUT_RES_CHOICE
    pr = _OUTPUT_PRESETS.get(res_key)
    print(f"[RES-DEBUG] _finalize_output_resolution called: res_key={res_key!r} pr={pr}")
    if not pr or "1K" in res_key:
        print(f"[RES-DEBUG] skipping — res_key is 1K or unknown")
        return False
    w, h = pr
    if not (path and os.path.exists(path)):
        print(f"[RES-DEBUG] skipping — path missing: {path}")
        return False
    try:
        cw, ch = get_resolution(path)
    except Exception:
        cw, ch = 0, 0
    print(f"[RES-DEBUG] source={cw}x{ch} target={w}x{h}")
    if not cw or not ch:
        print(f"[RES-DEBUG] skipping — could not read source resolution")
        return False
    if cw >= w and ch >= h:
        print(f"[RES-DEBUG] skipping — source already >= target")
        return False  # already at/above target
    if log:
        try: log(f"Rendering {res_key} output…")
        except Exception: pass
    tmp = path + ".upres.mp4"
    # Scale by whichever ratio is larger, so the video reaches (or slightly
    # exceeds on one axis) the target resolution — aspect ratio unchanged.
    factor = max(w / cw, h / ch)
    tw = max(2, int(round(cw * factor / 2)) * 2)
    th = max(2, int(round(ch * factor / 2)) * 2)
    vf = f"scale={tw}:{th}:flags=lanczos,setsar=1,unsharp=5:5:0.6:5:5:0.0"
    cmd = (["ffmpeg", "-y", "-i", path, "-vf", vf] + GPU.enc_args("fast") +
           ["-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", "-loglevel", "error", tmp])
    print(f"[RES-DEBUG] running upscale: target={tw}x{th} cmd={' '.join(cmd)}")
    vdur = max(0.1, get_duration(path) or 5.0)
    r = _run_ff_live(cmd, duration=vdur, on_progress=on_progress, timeout=10800)
    if r is None:
        print(f"[RES-DEBUG] upscale FAILED — _run_ff returned None (timeout or exception)")
    else:
        print(f"[RES-DEBUG] upscale returncode={r.returncode} stderr={str(getattr(r,'stderr',''))[-500:]}")
    print(f"[RES-DEBUG] tmp exists={os.path.exists(tmp)} "
          f"duration={get_duration(tmp) if os.path.exists(tmp) else 'n/a'}")
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
    _SAVE_DEBOUNCE_MS = 450
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
        # ── Whisper ──
        # Boot pe base model background mein download ho jaye (one-time,
        # ~145MB) taaki Create Captions pehli baar hi turant chale.
        "whisper_auto_base": True,
        "whisper_model": "base",
        # Rhymes lyrics usually sit under background music, so default to
        # a stronger local Whisper model than normal speech captions.
        "rhymes_whisper_model": "medium",
        "rhymes_transcript_engine": "Local Whisper",
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
        "master_clip_mode": "full_clip",
        "master_extend": "freeze_zoom",
        "master_tts_vol": 100,
        "master_clip_vol": 0,
        "master_tr_on": False,
        "jesus_tr_on": False,
        "jesus_tr_dur": 0.5,
        "jesus_tr_types": ["fade","wipeleft","slideright","circlecrop"],
        "script_clip_mode": "full_clip",
        "master_tr_dur": 0.5,
        "master_tr_types": ["fade","wipeleft","slideright","circlecrop"],
    }
    def __init__(self):
        self.data = self._load_from_file()
        self._save_lock = threading.Lock()
        self._save_timer = None
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
    def save(self, immediate=False):
        try:
            if immediate:
                self.flush_save()
                return
            with self._save_lock:
                try:
                    old = self._save_timer
                    if old is not None:
                        old.cancel()
                except Exception:
                    pass
                def _debounced_write():
                    try:
                        snapshot = dict(self.data)
                    except Exception:
                        snapshot = {}
                    _write_json_atomic(SETTINGS_FILE, snapshot)
                    with self._save_lock:
                        self._save_timer = None
                self._save_timer = threading.Timer(self._SAVE_DEBOUNCE_MS / 1000.0, _debounced_write)
                self._save_timer.daemon = True
                self._save_timer.start()
        except Exception as e:
            print(f"[SETTINGS] queued save failed: {e}")

    def flush_save(self):
        try:
            with self._save_lock:
                try:
                    old = self._save_timer
                    if old is not None:
                        old.cancel()
                except Exception:
                    pass
                self._save_timer = None
            snapshot = dict(self.data)
            _write_json_atomic(SETTINGS_FILE, snapshot)
        except Exception as e:
            print(f"[SETTINGS] flush save failed: {e}")
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
            _write_json_atomic(SETTINGS_FILE, data)
        except Exception as e:
            print(f"[SETTINGS] class save failed: {e}")


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

_DURATION_CACHE = {}  # Cache: {(path, mtime): duration} to avoid re-ffprobing
_RESOLUTION_CACHE = {}  # Cache: {(path, mtime): (w, h)}

def _cache_key(path):
    """(path, mtime) instead of just path — this is the fix for a real bug:
    the render pipeline overwrites the SAME path multiple times in place
    (scene render → resolution upscale → logo pass, each does
    shutil.move(tmp, path)). A plain path-keyed cache kept returning the
    resolution/duration from BEFORE the overwrite forever, which is exactly
    why a successful 4K upscale still showed as 1920x1080 to every function
    that ran after it. mtime changes on every overwrite, so this
    self-invalidates automatically with no caller changes needed anywhere else."""
    try:
        return (path, os.path.getmtime(path))
    except Exception:
        return (path, None)

def get_duration(path):
    """Get video duration. Cached (per path+mtime) to avoid repeated ffprobe calls."""
    key = _cache_key(path)
    if key in _DURATION_CACHE:
        return _DURATION_CACHE[key]
    try:
        r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
            "-of","default=noprint_wrappers=1:nokey=1",path], capture_output=True, text=True, timeout=15, **_NO_WINDOW)
        dur = float(r.stdout.strip())
        _DURATION_CACHE[key] = dur  # Cache it
        return dur
    except:
        return 0.0

def get_resolution(path):
    """Get video resolution. Cached (per path+mtime) to avoid repeated ffprobe calls."""
    key = _cache_key(path)
    if key in _RESOLUTION_CACHE:
        return _RESOLUTION_CACHE[key]
    try:
        r = subprocess.run(["ffprobe","-v","error","-select_streams","v:0",
            "-show_entries","stream=width,height","-of","csv=s=x:p=0",path],
            capture_output=True, text=True, timeout=15, **_NO_WINDOW)
        w, h = r.stdout.strip().split("x")
        res = (int(w), int(h))
        _RESOLUTION_CACHE[key] = res  # Cache it
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
        subprocess.run(cmd, capture_output=True, timeout=15, **_NO_WINDOW)
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
            subprocess.run(cmd2, capture_output=True, timeout=15, **_NO_WINDOW)
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
            capture_output=True, timeout=30, **_NO_WINDOW)
        if os.path.exists(tmp) and os.path.getsize(tmp) > 100: return tmp
        dur = get_duration(video_path)
        if dur > 0.1:
            subprocess.run(["ffmpeg","-y","-ss",str(max(0,dur-0.1)),"-i",video_path,
                "-frames:v","1","-q:v","2",tmp], capture_output=True, timeout=30, **_NO_WINDOW)
            if os.path.exists(tmp) and os.path.getsize(tmp) > 100: return tmp
    except: pass
    return None

def generate_black_video(dur=5.0, w=1920, h=1080, output=None):
    if not output: output = os.path.join(TEMP_DIR, "black_filler.mp4")
    cmd = ["ffmpeg","-y","-f","lavfi","-i",f"color=c=black:s={w}x{h}:d={dur}:r=30",
        "-f","lavfi","-i","anullsrc=r=44100:cl=stereo","-t",str(dur)]
    cmd += GPU.enc_args("ultrafast")
    cmd += ["-c:a","aac","-shortest",output]
    subprocess.run(cmd, capture_output=True, timeout=60, **_NO_WINDOW)
    return output if os.path.exists(output) else None

def has_audio_stream(path):
    try:
        r = subprocess.run(["ffprobe","-v","error","-select_streams","a:0",
            "-show_entries","stream=codec_type","-of","default=noprint_wrappers=1:nokey=1",path],
            capture_output=True, text=True, timeout=15, **_NO_WINDOW)
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
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, **_NO_WINDOW)

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
        subprocess.run(cmd2, capture_output=True, text=True, timeout=600, **_NO_WINDOW)
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
        subprocess.run(cmd2, capture_output=True, text=True, timeout=600, **_NO_WINDOW)
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
        subprocess.run(cmd2, capture_output=True, text=True, timeout=600, **_NO_WINDOW)
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
        subprocess.run(cmd2, capture_output=True, text=True, timeout=600, **_NO_WINDOW)
        src = conp if os.path.exists(conp) else cp
        tc=["ffmpeg","-y","-i",src,"-t",str(target_duration)]
        tc+=GPU.enc_args("fast")
        tc += ["-c:a","aac","-b:a","192k"] if has_audio_stream(src) else ["-an"]
        tc += [output_path]
        subprocess.run(tc, capture_output=True, text=True, timeout=600, **_NO_WINDOW)
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
            subprocess.run(cmd2, capture_output=True, text=True, timeout=300, **_NO_WINDOW)
            return output_path if os.path.exists(output_path) else None
        loops = max(1, math.ceil(target_duration / actual))
        lp = os.path.splitext(output_path)[0]+"_ll.txt"
        with open(lp,"w",encoding="utf-8") as f:
            for _ in range(loops+1): f.write(f"file '{os.path.abspath(trimmed)}'\n")
        conp = os.path.splitext(output_path)[0]+"_lp.mp4"
        cmd3=["ffmpeg","-y","-f","concat","-safe","0","-i",lp]
        cmd3+=GPU.enc_args("fast")
        cmd3+=["-an",conp]
        subprocess.run(cmd3, capture_output=True, text=True, timeout=600, **_NO_WINDOW)
        src = conp if os.path.exists(conp) else trimmed
        cmd4=["ffmpeg","-y","-i",src,"-t",str(target_duration)]
        cmd4+=GPU.enc_args("fast")
        cmd4+=["-an",output_path]
        subprocess.run(cmd4, capture_output=True, text=True, timeout=600, **_NO_WINDOW)
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
            capture_output=True, text=True, timeout=120, **_NO_WINDOW)
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
        subprocess.run(cmd2, capture_output=True, text=True, timeout=600, **_NO_WINDOW)
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
        # Debounce: rebuilding hundreds of CTk rows on EVERY keystroke is what
        # made this window feel frozen. Wait until typing pauses (220 ms).
        try:
            if getattr(self, "_filter_job", None):
                self.after_cancel(self._filter_job)
        except Exception: pass
        self._filter_job = self.after(220, self._filter_now)

    def _filter_now(self):
        self._filter_job = None
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
        # Cancel any in-flight chunked build from a previous query.
        try:
            if getattr(self, "_chunk_job", None):
                self.after_cancel(self._chunk_job); self._chunk_job=None
        except Exception: pass
        for w in self.lf.winfo_children(): w.destroy()
        if not items:
            ctk.CTkLabel(self.lf,text="No matches — try Direct ID above",text_color=C["dim"]).pack(pady=20); return
        self._pending = list(items[:300])
        self._shown = 0
        self._total_matches = len(items)
        self._more_lbl = None
        self._render_chunk(first=True)

    def _render_chunk(self, first=False):
        """Build the list a few rows at a time so the UI never blocks."""
        self._chunk_job = None
        batch = 25 if first else 20
        chunk = self._pending[:batch]
        self._pending = self._pending[batch:]
        self._build_rows(chunk)
        self._shown += len(chunk)
        if self._pending:
            self._chunk_job = self.after(1, self._render_chunk)
        elif self._total_matches > self._shown:
            try:
                ctk.CTkLabel(self.lf, text=f"… {self._total_matches - self._shown} more — refine your search",
                             text_color=C["dim"], font=("Segoe UI",9)).pack(pady=6)
            except Exception: pass

    def _build_rows(self,items):
        for item in items:
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
                _ai33_c = AI33Client(api_key=self.api_key or os.getenv("AI33_API_KEY") or "sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt")
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


class CaptionPreviewWindow(_BASIC_VM_TOPLEVEL):
    """Lightweight caption preview with drag-to-position. Uses Canvas drawing for smooth dragging."""
    def __init__(self, master, video_path, caption_groups, font_size=48,
                 font_color="FFFFFF", bg_color="000000", bg_opacity=0.6,
                 position="bottom", margin=80, callback=None, font_path=""):
        super().__init__(master); self.title("Caption Preview — Drag to Reposition"); _style_toplevel_bg(self, C["bg"]); self.transient(master)
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


class MiniPlayerWindow(_BASIC_VM_TOPLEVEL):
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
        super().__init__(master); self.title(title_text); _style_toplevel_bg(self, C["bg"]); self.transient(master)
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
        # CPU-only machines (no GPU encoder/decoder — common on VMs like
        # Hyper-V) decode noticeably slower. A short fixed timeout that's
        # fine on a GPU machine can expire here before ffmpeg even finishes,
        # which used to fail SILENTLY (bare except: pass) leaving the canvas
        # blank/black with no indication anything went wrong.
        _cpu_only = (GPU.gpu_vendor == "none")
        _extract_timeout = max(30, int(dur*2)) * (3 if _cpu_only else 1)
        _last_err = None
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
            result=subprocess.run(cmd, capture_output=True, timeout=_extract_timeout, **_NO_WINDOW)
            # Fallback if no frames generated (hwaccel issue)
            frames_check=list(Path(tmp_dir).glob("f_*.jpg"))
            if not frames_check:
                cmd2=["ffmpeg","-y","-i",self.video_path,"-vf",f"fps={preview_fps},scale=620:-2:flags=fast_bilinear",
                    "-q:v","5","-frames:v",str(n_frames),tmp_pattern]
                r2=subprocess.run(cmd2, capture_output=True, timeout=_extract_timeout, **_NO_WINDOW)
                if not list(Path(tmp_dir).glob("f_*.jpg")):
                    _last_err = (r2.stderr or b"").decode(errors="ignore")[-300:] or "no frames produced"
        except subprocess.TimeoutExpired:
            _last_err = f"timed out after {_extract_timeout}s (slow/no-GPU system — try 'Play with Audio (External)' instead)"
        except Exception as e:
            _last_err = f"{type(e).__name__}: {e}"
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
            # NEVER leave the canvas ambiguously blank — always show why,
            # and point at the one path that's guaranteed to work
            # (external player, which uses the OS's own decoder).
            msg = "No frames extracted"
            if _last_err:
                msg += f"\n({_last_err})"
            msg += "\n\nUse 'Play with Audio (External)' below instead."
            self.after(0,lambda m=msg:self._show_error(m))
            self.after(0,lambda:self.pos_lbl.configure(text="No frames extracted"))
        # Cleanup temp files
        try: shutil.rmtree(tmp_dir,ignore_errors=True)
        except: pass

    def _show_error(self, msg):
        if self._destroyed: return
        try:
            cw=max(100,self.canvas.winfo_width()); ch=max(100,self.canvas.winfo_height())
            self.canvas.delete("all")
            self.canvas.create_text(cw//2,ch//2,text=msg,fill="#ff8080",
                                    font=("Segoe UI",11),width=cw-40,justify="center")
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
            elif sys.platform=="darwin": subprocess.Popen(["open",self.video_path], **_NO_WINDOW)
            else: subprocess.Popen(["xdg-open",self.video_path], **_NO_WINDOW)
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
        # ── Pick up boot data (voices, models, API key pre-fetched at startup) ──
        self._boot_data = {}
        try:
            self._boot_data = self.winfo_toplevel()._boot_data or {}
        except Exception:
            pass
        
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

        self._build_ui()
        # ── Apply boot data: voices, models, API key (pre-fetched at startup) ──
        self.after(100, self._apply_boot_data)

    def _apply_boot_data(self):
        try:
            if not self.winfo_exists(): return
        except Exception: return
        bd = getattr(self, "_boot_data", {})
        if not bd:
            return
        # API key
        ak = bd.get("api_key", "")
        if ak and hasattr(self, "api_entry"):
            try:
                if self.api_entry.winfo_exists():
                    cur = self.api_entry.get().strip()
                    if not cur:
                        self.api_entry.insert(0, ak)
            except Exception: pass
            try: voice_cache.save_api_key(ak)
            except Exception: pass
        # Voices — pre-loaded list of (name, voice_id, gender)
        voices = bd.get("voices", [])
        if voices and not self.voice_list_full:
            self.voice_list_full = list(voices)
            try:
                self.api_status_lbl.configure(
                    text=f"✓ {len(voices)} voices (boot)",
                    text_color=C["green"])
            except Exception:
                pass
        # Models
        models = bd.get("models", [])
        if models and hasattr(self, "model_menu"):
            try:
                ns = [m.get("name", m.get("model_id", "?")) for m in models]
                self._model_id_map = {m.get("name", m.get("model_id","")): m.get("model_id","") for m in models}
                self.model_menu.configure(values=ns)
                lm = self.settings.get("last_model")
                if lm in ns:
                    self.model_var.set(lm)
                elif ns:
                    self.model_var.set(ns[0])
            except Exception:
                pass

    def _build_ui(self):
        self.grid_columnconfigure(1,weight=1); self.grid_rowconfigure(0,weight=1)
        sb=ctk.CTkScrollableFrame(self,width=380,fg_color=C["card"],corner_radius=0)
        sb.grid(row=0,column=0,sticky="nsew"); sb.grid_columnconfigure(0,weight=1)
        self._sb_ref=sb  # subclasses (ShortsEditorFrame) inject extra sections here
        ctk.CTkButton(sb, text="? Help", fg_color="#1e222b", hover_color="#323845",
                      text_color="#9aa0aa", height=28, font=("Segoe UI",10),
                      command=lambda: _show_tab_help(self._tab_help_title(), self._tab_help_steps())).grid(row=999, column=0, sticky="ew", padx=6, pady=(4,2))
        # ── Video Type (Normal / Kids) — Master/Stories only. Kids Video
        # turns on automatic BGM ducking (music drops under narration/SFX);
        # Normal Video behaves exactly as before, unchanged. Kept at the
        # very top, above even the preset buttons. ──
        is_master_family = hasattr(self, "_get_master_presets_dir")
        if is_master_family:
            _vt = ctk.CTkFrame(sb, fg_color="transparent")
            _vt.grid(row=0, column=0, sticky="ew", padx=6, pady=(6,2))
            ctk.CTkLabel(_vt, text="Video Type:", text_color=C["dim"],
                        font=("Segoe UI",10,"bold")).pack(side="left", padx=(4,6))
            self._video_type_var = ctk.StringVar(value=self.settings.get("video_type") or "Normal Video")
            ctk.CTkOptionMenu(_vt, variable=self._video_type_var,
                              values=["Normal Video", "Kids Video"],
                              fg_color=C["btn"], button_color=C["purple"],
                              button_hover_color=C["btn_hov"], width=170,
                              command=self._on_video_type_change).pack(side="left", padx=(0,4))
            self._video_type_hint = ctk.CTkLabel(_vt, text="", text_color=C["dim"],
                                                 font=("Segoe UI",9))
            self._video_type_hint.pack(side="left", padx=(6,2))
            self._on_video_type_change(self._video_type_var.get(), _save=False)
            preset_row = 1
        else:
            preset_row = 0

        # ── Preset Save / Load buttons — kept at the TOP (row=0/1; every
        # other section below is shifted to start one row after these) ──
        self.preset_widget = preset_manager.PresetWidget(
            sb, tool_id="rhymes_studio",
            collect_fn=self._collect_master_settings,
            apply_fn=self._apply_master_settings
        )
        self.preset_widget.grid(row=preset_row, column=0, sticky="ew", padx=6, pady=(6,2))
        row=preset_row + 1
        def sec(p,t,color=C["purple"]):
            f=ctk.CTkFrame(p,fg_color=C["card"],border_color=C["border"],border_width=1,corner_radius=8)
            ctk.CTkLabel(f,text=f"█  {t.upper()}",text_color=color,font=("Segoe UI",13,"bold")).pack(anchor="w",padx=8,pady=(5,2))
            return f

        # ── Mode Selector ──
        mode_sec=ctk.CTkFrame(sb,fg_color=C["card"],border_color=C["accent"],border_width=2,corner_radius=8)
        mode_sec.grid(row=row,column=0,sticky="ew",padx=6,pady=(6,4)); row+=1
        self.mode_sec = mode_sec
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
        ctk.CTkLabel(self.video_mode_frame,text="Upload videos → auto blocks. Then insert script for specific scenes below.",text_color=C["dim"],font=("Segoe UI",8)).pack(anchor="w",padx=10)
        vmbtn=ctk.CTkFrame(self.video_mode_frame,fg_color="transparent"); vmbtn.pack(fill="x",padx=5,pady=4)
        ctk.CTkButton(vmbtn,text="📁 Upload Videos",fg_color=C["orange"],text_color="#000",width=130,height=30,
            font=("Segoe UI",10,"bold"),command=self._only_video_upload).pack(side="left",padx=3)
        ctk.CTkButton(vmbtn,text="📂 Upload Folder",fg_color=C["orange"],text_color="#000",width=120,height=30,
            command=self._only_video_folder).pack(side="left",padx=3)
        ctk.CTkLabel(self.video_mode_frame,text="📝 Insert Script for specific scenes (voiceover):",
            text_color=C["green"],font=("Segoe UI",10,"bold")).pack(anchor="w",padx=10,pady=(5,0))
        ctk.CTkLabel(self.video_mode_frame,text="Any prefix works — bas _number_ chahiye:  Script_1_: text  |  Scene_8_: text  |  _10_: text",
            text_color=C["dim"],font=("Segoe UI",8)).pack(anchor="w",padx=10)
        self.vm_text_box=ctk.CTkTextbox(self.video_mode_frame,height=70,fg_color=C["entry_bg"],text_color=C["text"],
            border_color=C["border"],border_width=1,font=("Consolas",10))
        self.vm_text_box.pack(fill="x",padx=5,pady=3)
        vmtbtn=ctk.CTkFrame(self.video_mode_frame,fg_color="transparent"); vmtbtn.pack(fill="x",padx=5,pady=(2,5))
        ctk.CTkButton(vmtbtn,text="📝 Insert Script to Scenes",fg_color=C["green"],text_color="#000",width=180,height=28,
            font=("Segoe UI",10,"bold"),command=self._insert_text_to_blocks).pack(side="left",padx=3)
        self.vm_status=ctk.CTkLabel(vmtbtn,text="",text_color=C["dim"],font=("Segoe UI",9))
        self.vm_status.pack(side="left",padx=8)
        # Clip mode for scripted scenes
        cmf=ctk.CTkFrame(self.video_mode_frame,fg_color="transparent"); cmf.pack(fill="x",padx=5,pady=(2,5))
        ctk.CTkLabel(cmf,text="Scripted clips:",text_color=C["dim"],font=("Segoe UI",9)).pack(side="left")
        self._script_clip_mode=ctk.StringVar(value=self.settings.get("script_clip_mode") or "full_clip")
        ctk.CTkRadioButton(cmf,text="Full clip (TTS at start)",variable=self._script_clip_mode,
            value="full_clip",text_color=C["text"],fg_color=C["orange"],font=("Segoe UI",9)).pack(side="left",padx=4)
        ctk.CTkRadioButton(cmf,text="Clip = TTS length",variable=self._script_clip_mode,
            value="clip_eq_tts",text_color=C["text"],fg_color=C["orange"],font=("Segoe UI",9)).pack(side="left",padx=4)

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
        if self.settings.get("api_key"): self.api_entry.insert(0,self.settings.get("api_key"))
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

        # Row 8: Status Label
        self.api_status = ctk.CTkLabel(api, text="AI33 Ready", font=("Segoe UI", 9), text_color=C["dim"])
        self.api_status.pack(fill="x", padx=5, pady=(2, 4))
        self.api_status_lbl = self.api_status

        # ── Story ──
        story=sec(sb,"Story Script"); story.grid(row=row,column=0,sticky="ew",padx=6,pady=4); row+=1
        self._story_section_frame = story
        ctk.CTkLabel(story,text="CharName: text  OR  Scene_1_: text  OR  Scene_2_: text",text_color=C["dim"],font=("Segoe UI",9)).pack(anchor="w",padx=5)
        self.story_box=ctk.CTkTextbox(story,height=130,fg_color=C["entry_bg"],text_color=C["text"],border_color=C["border"],border_width=1,font=("Consolas",11))
        self.story_box.pack(fill="x",padx=5,pady=5)
        btf=ctk.CTkFrame(story,fg_color="transparent"); btf.pack(fill="x",padx=5,pady=(0,5))
        ctk.CTkButton(btf,text="Analyze",fg_color=C["purple"],text_color="#fff",height=30,command=self._analyze).pack(side="left",padx=3)
        ctk.CTkButton(btf,text="Create Blocks",fg_color=C["green"],text_color="#000",height=30,command=self._create_blocks).pack(side="left",padx=3)
        ctk.CTkButton(btf,text="📁 Upload Media",fg_color=C["accent"],text_color="#000",height=30,command=self._bulk_upload_media).pack(side="left",padx=3)

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
        def _mvol_upd(*a):
            try:
                if self.winfo_exists(): self.mvol_lbl.configure(text=f"{self.master_vol_var.get()}%")
            except Exception: pass
        self.master_vol_var.trace_add("write", _mvol_upd)
        ctk.CTkLabel(mvf,text="TTS Vol:",text_color=C["dim"]).pack(side="left",padx=(10,0))
        ctk.CTkSlider(mvf,from_=0,to=100,variable=self.master_tts_vol_var,width=100).pack(side="left",padx=3)
        self.mtvol_lbl=ctk.CTkLabel(mvf,text=f"{self.master_tts_vol_var.get()}%",text_color=C["text"],width=40)
        self.mtvol_lbl.pack(side="left")
        def _mtvol_upd(*a):
            try:
                if self.winfo_exists(): self.mtvol_lbl.configure(text=f"{self.master_tts_vol_var.get()}%")
            except Exception: pass
        self.master_tts_vol_var.trace_add("write", _mtvol_upd)

        # ── Logo ──
        logo=sec(sb,"Logo / Watermark"); logo.grid(row=row,column=0,sticky="ew",padx=6,pady=4); row+=1
        self._logo_section_frame = logo
        self._extra_logos = []  # list of {"path":..,"size_var":..,"opacity_var":..,"anchor_var":..,"lbl":..}
        ctk.CTkCheckBox(logo,text="Enable Logo",variable=self.logo_enabled_var,text_color=C["text"],
            fg_color=C["green"]).pack(anchor="w",padx=8,pady=3)
        ctk.CTkButton(logo,text="Select Logo 1",width=200,fg_color=C["accent"],text_color="#000",command=self._sel_logo).pack(padx=5,pady=3)
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
            font=("Segoe UI",11,"bold"),command=self._logo_preview).pack(padx=5,pady=(4,2))
        # Multi-logo: add more logos
        self._extra_logos_frame=ctk.CTkFrame(logo,fg_color="transparent"); self._extra_logos_frame.pack(fill="x",padx=5,pady=2)
        ctk.CTkButton(logo,text="➕ Add Logo 2, 3…",width=160,fg_color=C["btn"],hover_color=C["btn_hov"],
            text_color=C["text"],height=26,font=("Segoe UI",9),command=self._add_extra_logo).pack(padx=5,pady=(2,6))

        # ── Intro ──
        intro=sec(sb,"Intro Videos"); self._intro_section=intro; intro.grid(row=row,column=0,sticky="ew",padx=6,pady=4); row+=1
        ctk.CTkCheckBox(intro,text="Enable Intro",variable=self.intro_enabled_var,text_color=C["text"],
            fg_color=C["green"]).pack(anchor="w",padx=8,pady=3)
        ctk.CTkButton(intro,text="Select Intro(s)",width=200,fg_color=C["accent"],text_color="#000",command=self._sel_intros).pack(padx=5,pady=3)
        self.intro_lbl=ctk.CTkLabel(intro,text="(none)",text_color=C["dim"],font=("Segoe UI",9)); self.intro_lbl.pack(padx=5)

        # ── BGM ──
        bgm=sec(sb,"Background Music"); bgm.grid(row=row,column=0,sticky="ew",padx=6,pady=4); row+=1
        self._bgm_section_frame = bgm
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
        self._action_row_ref = ar  # so subclasses (Master) can rebuild the buttons
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

        # ── Auto-load saved API key + auto-fetch models/voices as soon as
        #    this tab opens, so the user never has to click Fetch manually. ──
        self.after(500, self._auto_fetch_on_start)

    def _auto_fetch_on_start(self):
        """Runs once when the tab first mounts: if a saved ElevenLabs API key
        exists, load it into the field and fetch models + voices automatically."""
        if getattr(self, "_auto_fetch_done", False):
            return
        self._auto_fetch_done = True
        self._auto_load_voices_on_init()
        try:
            key = self.api_entry.get().strip()
        except Exception:
            key = ""
        if not key:
            key = (self.settings.get("api_key") or "").strip()
            if key:
                try:
                    self.api_entry.delete(0, "end"); self.api_entry.insert(0, key)
                except Exception:
                    pass
        if not key:
            return
        try:
            self.api_status_lbl.configure(text="Auto-loading key…", text_color=C["orange"])
        except Exception:
            pass
        threading.Thread(target=self._fm_worker, args=(key,), daemon=True).start()
        threading.Thread(target=self._fv_worker, args=(key,), daemon=True).start()

    # ── Sidebar helpers ──
    def _import_logo_safe(self, src_path, slot="logo1"):
        """User ka chosen logo app ke APNE folder mein PNG banake copy karo.
        Kyun: original path Desktop/Downloads/OneDrive pe hota hai —
          - OneDrive 'files on-demand' = file disk pe hoti hi nahi, sirf placeholder
          - non-English (Hindi/etc.) username paths kuch tools ko todte hain
          - user file move/delete kar de to render time pe logo gayab
        PIL se open + PNG save = format bhi normalize (webp/bmp → png) aur
        path bhi hamesha safe. Fail ho to error DIKHAO — silent kabhi nahi."""
        try:
            safe_dir = str(_DATA_ROOT / "logos")
            os.makedirs(safe_dir, exist_ok=True)
            img = Image.open(src_path)
            img.load()                      # OneDrive placeholder yahin pakda jayega
            img = img.convert("RGBA")
            dest = os.path.join(safe_dir, f"{slot}.png")
            img.save(dest, "PNG")
            return dest
        except Exception as e:
            messagebox.showerror(
                "Logo",
                f"Logo load nahi ho paya:\n{src_path}\n\n"
                f"Error: {e}\n\n"
                "Agar file OneDrive/Google Drive mein hai to pehle usko "
                "local folder (jaise C:\\Logos) mein copy karke wahan se select karo.")
            return ""

    def _sel_logo(self):
        p=filedialog.askopenfilename(parent=self, filetypes=[("Images","*.png *.jpg *.jpeg *.webp *.bmp")])
        if p:
            _orig_name = os.path.basename(p)
            safe = self._import_logo_safe(p, "logo1")
            if not safe: return
            p = safe
            self.logo_path_var.set(p); self.logo_lbl.configure(text=_orig_name)
            # New logo chosen → drop any cached/cropped version of the OLD logo
            self.logo_cropped_pil=None
            self._logo_cropped_for_path=None
            # Auto-enable the "Enable Logo" checkbox — picking a file is a
            # strong signal the user wants the logo applied. Manual toggle is
            # still there if they want to temporarily disable.
            try: self.logo_enabled_var.set(True)
            except Exception: pass

    def _add_extra_logo(self):
        """Add another logo slot (Logo 2, 3…) — size/opacity/anchor PLUS its own
        Preview & Position button, same drag-to-place window as Logo 1.
        However many logos get added, every single one gets this control."""
        p=filedialog.askopenfilename(parent=self, filetypes=[("Images","*.png *.jpg *.jpeg *.webp *.bmp")])
        if not p: return
        idx=len(self._extra_logos)+2
        _orig_name = os.path.basename(p)
        safe = self._import_logo_safe(p, f"logo{idx}")
        if not safe: return
        p = safe
        ef=ctk.CTkFrame(self._extra_logos_frame, fg_color=C["btn"], corner_radius=6)
        ef.pack(fill="x", pady=(2,3), padx=1)
        ctk.CTkLabel(ef, text=f"Logo {idx}: {_orig_name[:22]}", text_color=C["green"],
                     font=("Segoe UI",9,"bold")).pack(anchor="w", padx=5, pady=(4,1))
        row1=ctk.CTkFrame(ef, fg_color="transparent"); row1.pack(fill="x", padx=3, pady=1)
        ctk.CTkLabel(row1,text="Sz",text_color=C["dim"],font=("Segoe UI",8),width=14).pack(side="left")
        sz=ctk.IntVar(value=80); op=ctk.IntVar(value=100)
        # Logo 1 sits at bottom-right by default, so extra logos start at a
        # DIFFERENT corner (cycling) so both are visible without dragging.
        _anchor_cycle=["top-right","top-left","bottom-left","center","bottom-right"]
        anc=ctk.StringVar(value=_anchor_cycle[(idx-2) % len(_anchor_cycle)])
        ctk.CTkSlider(row1,from_=20,to=400,variable=sz,width=55).pack(side="left",padx=2)
        ctk.CTkLabel(row1,text="Op",text_color=C["dim"],font=("Segoe UI",8),width=14).pack(side="left")
        ctk.CTkSlider(row1,from_=10,to=100,variable=op,width=55).pack(side="left",padx=2)
        ctk.CTkOptionMenu(row1,variable=anc,fg_color=C["btn_hov"],text_color=C["text"],
            values=["top-left","top-right","bottom-left","bottom-right","center"],width=90,
            font=("Segoe UI",8)).pack(side="left",padx=2)
        # This dict is the single source of truth for this logo — the Preview
        # window callback fills in pct_x/pct_y once the user drags & confirms.
        entry={"path":p,"size_var":sz,"opacity_var":op,"anchor_var":anc,"frame":ef,
               "pct_x":None,"pct_y":None,"cropped_pil":None}
        row2=ctk.CTkFrame(ef, fg_color="transparent"); row2.pack(fill="x", padx=3, pady=(1,4))
        ctk.CTkButton(row2,text="Preview & Position",height=24,fg_color=C["purple"],text_color="#fff",
            font=("Segoe UI",9,"bold"),command=lambda e=entry:self._extra_logo_preview(e)).pack(side="left",padx=2,fill="x",expand=True)
        def _rm(frame=ef, e=entry):
            self._extra_logos=[l for l in self._extra_logos if l is not e]
            frame.destroy()
        ctk.CTkButton(row2,text="X",width=26,height=24,fg_color=C["red"],text_color="#fff",command=_rm).pack(side="left",padx=2)
        self._extra_logos.append(entry)

    def _extra_logo_preview(self, entry):
        """Same drag-to-place preview window Logo 1 uses, but for an extra logo
        slot (Logo 2, 3, ...). Saves position as a % of the frame so it renders
        correctly at any output resolution."""
        lp=entry.get("path")
        if not lp or not os.path.exists(lp):
            messagebox.showwarning("Logo","This logo's image file could not be found."); return
        bg,_=self._get_preview_bg()
        prev_w, prev_h = bg.size
        print(f"[LOGO-DEBUG] preview opened for {os.path.basename(lp)} "
              f"preview_canvas={prev_w}x{prev_h}")
        try:
            logo_pil=entry.get("cropped_pil") or Image.open(lp).convert("RGBA")
        except Exception as e:
            messagebox.showerror("Logo",f"Cannot load logo: {e}"); return
        def cb(anchor,mx,my,sz,opa,cropped_pil,ax,ay):
            try: entry["anchor_var"].set(anchor)
            except Exception: pass
            try: entry["size_var"].set(sz)
            except Exception: pass
            try: entry["opacity_var"].set(opa)
            except Exception: pass
            entry["pct_x"]=ax/prev_w if prev_w>0 else 0
            entry["pct_y"]=ay/prev_h if prev_h>0 else 0
            # Size bhi fraction mein — Logo 1 jaisa. Bina iske slider ke
            # absolute pixels output resolution pe galat size dete the.
            entry["pct_size"]=sz/prev_w if prev_w>0 else 0
            entry["cropped_pil"]=cropped_pil
            if cropped_pil is not None:
                try:
                    tag=abs(hash(lp))%999999
                    cp_path=os.path.join(TEMP_DIR,f"_extra_logo_{tag}.png")
                    cropped_pil.save(cp_path); entry["path"]=cp_path
                except Exception: pass
            self._ss(f"Logo positioned: {anchor} ({entry['pct_x']*100:.1f}%, {entry['pct_y']*100:.1f}%) sz={sz} opa={opa}%",C["green"])
        init_sz=entry["size_var"].get()
        if entry.get("pct_size"):
            init_sz=max(20,int(round(prev_w*entry["pct_size"])))
        init_x=int(round(prev_w*entry["pct_x"])) if entry.get("pct_x") is not None else None
        init_y=int(round(prev_h*entry["pct_y"])) if entry.get("pct_y") is not None else None
        LogoPreviewWindow(self,bg,logo_pil,init_sz,entry["opacity_var"].get(),cb,
            init_anchor=entry["anchor_var"].get(),init_mx=20,init_my=20,
            init_x=init_x,init_y=init_y)

    def _apply_extra_logos_to_file(self, path, include_logo1=False):
        """Composite Logo 1 (optional) + every extra logo (Logo 2, 3, ...) onto the
        finished video -- called once at the very end of the merge, after BGM
        and output-resolution scaling are already baked in. Doing every logo
        in ONE pass at the TRUE final pixel size (not an earlier per-scene
        size) is what guarantees a logo lands at its exact preview position
        whether the project is 1K, 2K or 4K. No-op if there's nothing to draw."""
        logos=[]
        if include_logo1:
            try:
                if self.logo_enabled_var.get():
                    lp=self.logo_path_var.get()
                    if lp and os.path.exists(lp):
                        eff_path=lp
                        if (getattr(self,"logo_cropped_pil",None) is not None and
                                getattr(self,"_logo_cropped_for_path",None)==lp):
                            try:
                                ctp=os.path.join(TEMP_DIR,"_logo1_final.png")
                                self.logo_cropped_pil.save(ctp); eff_path=ctp
                            except Exception: pass
                        logos.append({
                            "path": eff_path,
                            "pct_x": getattr(self,"_logo_pct_x",None),
                            "pct_y": getattr(self,"_logo_pct_y",None),
                            "pct_size": getattr(self,"_logo_pct_size",None),
                            "size_var": self.logo_size_var,
                            "opacity_var": self.logo_opacity_var,
                            "anchor_var": self.logo_anchor_var,
                        })
            except Exception:
                pass
        logos += [lg for lg in (getattr(self,"_extra_logos",None) or [])
               if lg.get("path") and os.path.exists(lg["path"])]
        if not logos or not (path and os.path.exists(path)):
            return False
        try:
            vw,vh=get_resolution(path)
        except Exception:
            vw,vh=0,0
        if not vw or not vh: vw,vh=1920,1080
        inputs=["-i",path]; fc_parts=[]; prev="0:v"
        for i,lg in enumerate(logos, start=1):
            # Size: fraction of frame width (preview jaisa) — fallback slider px
            pct_sz=lg.get("pct_size")
            if pct_sz and pct_sz>0:
                sz=max(10,int(round(vw*pct_sz)))
            else:
                try: sz=max(10,int(lg["size_var"].get()))
                except Exception: sz=80
            if sz%2: sz+=1                       # yuv420p even dims
            try: opa=max(0,min(100,int(lg["opacity_var"].get())))
            except Exception: opa=100
            opa_f=opa/100.0
            pct_x,pct_y=lg.get("pct_x"),lg.get("pct_y")
            if pct_x is not None and pct_y is not None:
                ox,oy=int(pct_x*vw),int(pct_y*vh)
            else:
                try: anchor=lg["anchor_var"].get()
                except Exception: anchor="bottom-right"
                ox,oy=calc_logo_xy(anchor,20,20,sz,vw,vh)
            ox=max(0,min(ox,max(0,vw-sz))); oy=max(0,min(oy,max(0,vh-sz)))
            print(f"[LOGO-DEBUG] #{i} path={os.path.basename(lg.get('path',''))} "
                  f"pct_x={pct_x} pct_y={pct_y} pct_size={lg.get('pct_size')} "
                  f"final_canvas={vw}x{vh} sz={sz} -> ox={ox} oy={oy}")
            inputs+=["-i",lg["path"]]
            tag=f"[lg{i}]"; out_tag=f"[ov{i}]"
            # SQUARE scale (sz x sz) — preview bhi square dikhata hai.
            # Pehle scale=sz:-1 tha (original aspect) → height preview se
            # alag → position mismatch. Ab render == preview, exactly.
            fc_parts.append(f"[{i}:v]scale={sz}:{sz},format=rgba,colorchannelmixer=aa={opa_f:.2f}{tag}")
            fc_parts.append(f"[{prev}]{tag}overlay=x={ox}:y={oy}:shortest=1{out_tag}")
            prev=out_tag.strip("[]")
        if not fc_parts: return False
        fc=";".join(fc_parts)
        tmp=path+".xlogo.mp4"
        # Use CPU libx264 for reliability — this final polish step was seen to
        # silently produce audio-only files on Intel QSV, which was then moved
        # over the good `path` file (destroying the video). CPU is bulletproof.
        cmd=["ffmpeg","-y"]+inputs+["-filter_complex",fc,"-map",f"[{prev}]","-map","0:a?"]
        cmd+=["-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p",
              "-c:a","aac","-b:a","192k","-movflags","+faststart","-loglevel","error",tmp]
        _run_ff(cmd, timeout=3600)
        # BOTH duration >0.1 AND a decodable video stream must be present —
        # otherwise we'd overwrite a perfectly good `path` file with a broken
        # audio-only tmp (which was the exact v13.22 bug).
        tmp_ok = False
        if os.path.exists(tmp) and get_duration(tmp) > 0.1:
            try:
                r = subprocess.run(
                    ["ffprobe","-v","error","-select_streams","v:0",
                     "-show_entries","stream=codec_type",
                     "-of","default=noprint_wrappers=1:nokey=1", tmp],
                    capture_output=True, text=True, timeout=15, **_NO_WINDOW)
                tmp_ok = bool(r.stdout.strip())
            except Exception:
                tmp_ok = False
        if tmp_ok:
            try:
                shutil.move(tmp, path); return True
            except Exception:
                try: shutil.copy2(tmp, path); os.remove(tmp); return True
                except Exception: return False
        try:
            if os.path.exists(tmp): os.remove(tmp)
        except Exception: pass
        return False
    def _sel_intros(self):
        ps=filedialog.askopenfilenames(parent=self, filetypes=[("Videos","*.mp4 *.mov *.avi *.mkv *.webm")])
        if ps: self.intro_var.set(";".join(ps)); self.intro_lbl.configure(text=f"{len(ps)} file(s)")
    def _sel_bgm(self):
        p=filedialog.askopenfilename(parent=self, filetypes=[("Audio","*.mp3 *.wav *.aac *.ogg *.m4a")])
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
        try:
            if hasattr(self, "api_entry") and self.api_entry.winfo_exists():
                key=self.api_entry.get().strip()
            else:
                key=(self.settings.get("api_key") or "").strip()
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
                        # Auto-enable both "enabled" AND "loop" — a generated
                        # BGM is meant to fill the whole video; users otherwise
                        # get a track that plays for 30 seconds and then goes
                        # silent for the rest of a longer render.
                        self.after(0,lambda:(self.bgm_lbl.configure(text="🎵 "+os.path.basename(out)),
                                             self.bgm_enabled_var.set(True),
                                             (self.bgm_loop_var.set(True) if hasattr(self,"bgm_loop_var") else None)))
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
                elif sys.platform=="darwin": subprocess.Popen(["open",prev], **_NO_WINDOW)
                else: subprocess.Popen(["xdg-open",prev], **_NO_WINDOW)
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

    def _set_common_voice(self):
        """Task 8: Set common voice for Scene_N_ format scripts."""
        if not self.voice_list_full:
            messagebox.showinfo("Voices","Fetch Voices first."); return
        def pick(name,vid):
            self.common_voice_name.set(name); self.common_voice_id.set(vid)
            self.common_voice_lbl.configure(text=name)
            self._ss(f"Common voice: {name}",C["green"])
        VoiceSearchWindow(self,self.voice_list_full,self.common_voice_name.get(),pick,api_key=self.api_entry.get().strip())

    # ── Inline voice autocomplete (type-to-search) ──────────────
    def _voice_ac_update(self):
        """Debounced live search: updates the dropdown with matching voices."""
        try:
            if getattr(self,"_vac_job",None): self.after_cancel(self._vac_job)
        except Exception: pass
        self._vac_job=self.after(180,self._voice_ac_search)
    def _voice_ac_search(self):
        self._vac_job=None
        q=(self._voice_search_var.get() or "").strip().lower()
        if len(q)<2:
            self._voice_ac_menu.configure(values=["(type 2+ chars)"]); self._voice_ac_menu.set("(type 2+ chars)"); return
        if not self.voice_list_full:
            self._voice_ac_menu.configure(values=["(fetch voices first)"]); self._voice_ac_menu.set("(fetch voices first)"); return
        matches=[]
        for item in self.voice_list_full:
            nm=item[0]; vid=item[1]
            if q in nm.lower():
                gender=item[2] if len(item)>2 else ""
                tag=f" ({gender})" if gender else ""
                matches.append(f"{nm}{tag}")
            if len(matches)>=25: break
        if not matches:
            self._voice_ac_menu.configure(values=["(no match)"]); self._voice_ac_menu.set("(no match)"); return
        self._voice_ac_menu.configure(values=matches)
        self._voice_ac_menu.set(matches[0])
    def _voice_ac_pick(self,choice):
        """User picked a voice from the autocomplete dropdown."""
        if choice.startswith("("): return
        # Parse "VoiceName (gender)" back to name
        name=choice.rsplit(" (",1)[0].strip()
        for item in self.voice_list_full:
            if item[0]==name:
                self.common_voice_name.set(item[0])
                self.common_voice_id.set(item[1])
                self.common_voice_lbl.configure(text=item[0])
                self._ss(f"Voice: {item[0]}",C["green"])
                return
        # Fuzzy fallback — first match
        nl=name.lower()
        for item in self.voice_list_full:
            if nl in item[0].lower():
                self.common_voice_name.set(item[0])
                self.common_voice_id.set(item[1])
                self.common_voice_lbl.configure(text=item[0])
                self._ss(f"Voice: {item[0]}",C["green"])
                return

    def _get_preview_bg(self):
        """Return a preview frame composed EXACTLY like the rendered output.

        FIX (logo position lock): pehle canvas hamesha 1920x1080 hota tha,
        lekin renderer `get_resolution(video)` — asli media resolution — pe
        kaam karta hai (Shorts editor 1080x1920 pe). Geometry alag → pct
        fractions alag jagah map hote the → logo final output mein shift.
        Ab canvas wahi dimensions use karta hai jo render karega:
          1. Shorts editor → TARGET_W x TARGET_H (1080x1920)
          2. Warna → pehle block ke media ka actual resolution
          3. Kuch na mile → 1920x1080 fallback
        Letterbox math bilkul renderer ke scale+pad filter jaisa hai."""
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

        # ── Output geometry EXACTLY renderer jaisa decide karo ──
        CW = CH = 0
        tw = getattr(self, "TARGET_W", 0); th = getattr(self, "TARGET_H", 0)
        if tw and th:
            CW, CH = int(tw), int(th)                 # Shorts: locked 9:16
        elif src is not None:
            try:
                if is_image_file(src):
                    CW, CH = raw.size                  # image scene: apna size
                else:
                    CW, CH = get_resolution(src)       # video scene: asli res
            except Exception:
                CW = CH = 0
        if not CW or not CH:
            CW, CH = 1920, 1080
        # yuv420p ke liye renderer even dims use karta hai
        CW, CH = max(2, CW - (CW % 2)), max(2, CH - (CH % 2))

        # Build canvas with the media letterboxed (matches output)
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

    # ── Voice Studio & TTS Engine Methods ──
    def _fetch_voices_threaded(self):
        key = "sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt"
        try:
            if hasattr(self, "api_entry") and self.api_entry.winfo_exists():
                val = self.api_entry.get().strip()
                if val: key = val
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
        key = self.api_entry.get().strip() or "sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt"

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

    # Task 10: Stop
    def _stop_gen(self):
        self._cancelled=True; self._ss("Stopping...",C["red"])

    # ── Auto-save settings ──
    # ── Preset Save / Load / Delete UI ──────────────────────────
    # NOTE: Master/Stories (any tab with _get_master_presets_dir) use a
    # simple, self-contained JSON-file store — one file per preset in
    # ~/.video_master_tool/master_presets/. Earlier this went through an
    # external `preset_manager` module whose save/list weren't reading from
    # the same place, so a preset you just saved wouldn't show up in Load —
    # that indirection is why it looked "not working". Other tabs (without
    # _get_master_presets_dir) still use the original preset_manager path.
    def _preset_safe_name(self, name):
        safe = re.sub(r'[^A-Za-z0-9 _\-]', '', name).strip()
        return safe or f"preset_{int(time.time())}"

    def _preset_save_ui(self):
        from tkinter import simpledialog
        name = simpledialog.askstring("Save Preset", "Preset name:", parent=self)
        if not name or not name.strip(): return
        name = name.strip()
        data = self._collect_master_settings()
        if hasattr(self, "_get_master_presets_dir"):
            try:
                safe = self._preset_safe_name(name)
                d = self._get_master_presets_dir()
                path = os.path.join(d, safe + ".json")
                if os.path.exists(path) and not messagebox.askyesno(
                        "Overwrite?", f"A preset named '{safe}' already exists. Overwrite?", parent=self):
                    return
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False, default=str)
                os.replace(tmp, path)
                print(f"[PRESET] saved -> {path}")
                self._ss(f"✓ Preset '{safe}' saved", C["green"])
            except Exception as e:
                print("[PRESET] save failed:", e)
                messagebox.showerror("Save Preset", f"Could not save preset:\n{e}", parent=self)
        else:
            try:
                preset_manager.save_preset(name, data)
                self._ss(f"✓ Preset '{name}' saved", C["green"])
            except Exception as e:
                messagebox.showerror("Save Preset", str(e), parent=self)

    def _preset_names_and_loader(self):
        """Returns (names, load_fn) where load_fn(name) -> dict or None."""
        if hasattr(self, "_get_master_presets_dir"):
            d = self._get_master_presets_dir()
            try:
                names = sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json"))
            except Exception as e:
                print("[PRESET] list failed:", e)
                names = []
            def _load(n, _d=d):
                path = os.path.join(_d, n + ".json")
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception as e:
                    print(f"[PRESET] read failed for {n}:", e)
                    return None
            return names, _load
        else:
            try:
                names = preset_manager.list_presets()
            except Exception as e:
                print("[PRESET] list failed:", e); names = []
            return names, preset_manager.load_preset

    def _preset_popup_shell(self, title):
        win = _BASIC_VM_TOPLEVEL(self) if "_BASIC_VM_TOPLEVEL" in globals() else ctk.CTkToplevel(self)
        win.title(title); win.geometry("360x420")
        win.resizable(False, False)
        try: win.configure(fg_color=C["bg"])
        except Exception:
            try: win.configure(bg=C["bg"])
            except Exception: pass
        win.transient(self.winfo_toplevel())
        # Delayed grab (not immediate) — an immediate grab_set() right after
        # creation is what was leaving these popups' content area blank on
        # some machines; letting one paint cycle happen first fixes it.
        win.after(60, lambda: (win.lift(), win.focus_force(), win.grab_set()))
        return win

    def _preset_load_ui(self):
        names, loader = self._preset_names_and_loader()
        if not names:
            messagebox.showinfo("Presets", "No saved presets yet.\nUse '💾 Save Preset' first.", parent=self)
            return
        win = self._preset_popup_shell("Load Preset")
        ctk.CTkLabel(win, text="📂  Select Preset", text_color=C["accent"],
                     font=("Segoe UI", 16, "bold")).pack(pady=(16,10))
        sf = ctk.CTkScrollableFrame(win, fg_color=C["card"], height=300)
        sf.pack(fill="both", expand=True, padx=12, pady=(0,8))

        def _load(n):
            data = loader(n)
            if data:
                self._apply_master_settings(data, warn_missing_files=True)
                self._ss(f"✓ Preset '{n}' loaded", C["green"])
            else:
                messagebox.showerror("Load Preset", f"Could not load preset '{n}'.", parent=win)
                return
            win.destroy()

        for n in names:
            ctk.CTkButton(sf, text=n, height=36, fg_color=C["card"],
                          hover_color=C["btn_hov"], text_color=C["text"],
                          border_width=1, border_color=C["border"],
                          font=("Segoe UI", 12),
                          command=lambda nm=n: _load(nm)).pack(fill="x", pady=2, padx=4)
        ctk.CTkButton(win, text="Cancel", height=32, fg_color="transparent",
                      hover_color=C["card"], text_color=C["dim"],
                      command=win.destroy).pack(pady=(0,10))

    def _preset_delete_ui(self):
        names, _ = self._preset_names_and_loader()
        if not names:
            messagebox.showinfo("Presets", "No presets to delete.", parent=self)
            return
        win = self._preset_popup_shell("Delete Preset")
        ctk.CTkLabel(win, text="🗑  Delete Preset", text_color="#fb7185",
                     font=("Segoe UI", 16, "bold")).pack(pady=(16,10))
        sf = ctk.CTkScrollableFrame(win, fg_color=C["card"], height=300)
        sf.pack(fill="both", expand=True, padx=12, pady=(0,8))

        def _del(n, btn):
            if not messagebox.askyesno("Delete", f"Delete preset '{n}'?", parent=win): return
            try:
                if hasattr(self, "_get_master_presets_dir"):
                    path = os.path.join(self._get_master_presets_dir(), n + ".json")
                    if os.path.exists(path): os.remove(path)
                else:
                    preset_manager.delete_preset(n)
                btn.destroy()
                self._ss(f"Preset '{n}' deleted", C["orange"])
            except Exception as e:
                messagebox.showerror("Delete Preset", str(e), parent=win)

        for n in names:
            btn = ctk.CTkButton(sf, text=f"✕  {n}", height=36, fg_color="#3d1515",
                                hover_color="#5c1a1a", text_color="#e4a3a3",
                                border_width=1, border_color="#5c1a1a",
                                font=("Segoe UI", 12))
            btn.configure(command=lambda nm=n, b=btn: _del(nm, b))
            btn.pack(fill="x", pady=2, padx=4)
        ctk.CTkButton(win, text="Close", height=32, fg_color="transparent",
                      hover_color=C["card"], text_color=C["dim"],
                      command=win.destroy).pack(pady=(0,10))

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

            _queue_settings_save(self, self.settings, delay=300)
        except: pass

    # ── Mode Toggle ──
    def _toggle_mode(self):
        mode=self.mode_var.get()
        if mode=="video":
            self.video_mode_frame.grid(row=self._video_mode_row,column=0,sticky="ew",padx=6,pady=4)
            # Hide Story Script section (confusing in Only-Video — use the Insert Script box instead)
            try:
                if hasattr(self,"_story_section_frame"): self._story_section_frame.grid_remove()
            except: pass
        else:
            self.video_mode_frame.grid_forget()
            # Show Story Script section back
            try:
                if hasattr(self,"_story_section_frame"): self._story_section_frame.grid()
            except: pass

    # ── Only Video Mode Methods ──
    def _only_video_upload(self):
        ps=filedialog.askopenfilenames(parent=self, filetypes=[("Video","*.mp4 *.mov *.avi *.mkv *.webm *.flv")])
        if ps: self._create_blocks_from_videos(list(ps))

    def _only_video_folder(self):
        folder=filedialog.askdirectory(parent=self, title="Video folder")
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
        """Insert script into matching blocks — GENERIC _N_ FORMAT.
        Rule: line mein `_number_` marker mila to wahi scene hai. Prefix kuch
        bhi ho sakta hai: Script_1_:, Scene_8_:, Voice_5_-, ya bas _7_:
        Marker ke baad aane wali plain lines usi scene ke script mein judti
        hain (multi-line support). Fallback: `8: text` bhi chalta hai.
        Blocks with text → TTS will be generated (clip vol low).
        Blocks without text → clip plays its own audio (clip vol 100)."""
        raw=self.vm_text_box.get("1.0","end").strip()
        if not raw:
            messagebox.showwarning("Script","Enter script.\nFormat: Script_1_: your text  (bas _number_ hona chahiye)")
            return
        # ── Pass 1: parse lines into {scene_num: [text lines]} ──
        marker=re.compile(r'^\s*[A-Za-z0-9\u0900-\u097F\u0600-\u06FF]*_(\d+)_\s*[:\-–—]?\s*(.*)$')
        entries={}; order=[]; current=None
        for line in raw.split("\n"):
            ls=line.strip()
            if not ls:
                current=None            # blank line = scene block khatam
                continue
            m=marker.match(ls)
            if m:
                sn=int(m.group(1)); txt=(m.group(2) or "").strip()
                if sn not in entries: entries[sn]=[]; order.append(sn)
                if txt: entries[sn].append(txt)
                current=sn
                continue
            m2=re.match(r'^(\d+)\s*[:\-\)]\s*(.+)$',ls)
            if m2:
                sn=int(m2.group(1)); txt=m2.group(2).strip()
                if sn not in entries: entries[sn]=[]; order.append(sn)
                if txt: entries[sn].append(txt)
                current=sn
                continue
            if current is not None:     # continuation line → previous scene
                entries[current].append(ls)
        # ── Pass 2: apply to blocks ──
        inserted=0
        for sn in order:
            text=" ".join(entries.get(sn,[])).strip()
            if not text: continue
            for b in self.blocks:
                if b["num"]==sn:
                    b["text"]=text
                    clip_mode = self._script_clip_mode.get() if hasattr(self,"_script_clip_mode") else "full_clip"
                    if clip_mode == "full_clip":
                        b["video_only"]=True    # full clip plays, TTS overlaid at start
                    else:
                        b["video_only"]=False   # clip trimmed to TTS length
                    b["clip_volume"]=0       # mute clip during voiceover
                    b["tts_volume"]=100
                    # Update display
                    try:
                        d=text[:50]+"..." if len(text)>50 else text
                        for w in b["frame"].winfo_children():
                            for w2 in w.winfo_children():
                                if isinstance(w2,ctk.CTkLabel) and hasattr(w2,'cget'):
                                    try:
                                        if w2.cget("wraplength")==250:
                                            w2.configure(text=d)
                                    except: pass
                    except: pass
                    b["status_label"].configure(text=f"Script added",text_color=C["green"])
                    inserted+=1; break
        # Blocks WITHOUT text keep their original audio
        for b in self.blocks:
            if not (b.get("text","") or "").strip():
                b["clip_volume"]=100   # full clip audio
                b["video_only"]=True   # no TTS
        if inserted>0:
            self.vm_status.configure(text=f"✓ Script inserted in {inserted} scenes",text_color=C["green"])
            self._ss(f"Script inserted in {inserted} scenes — Generate Audio to create voiceover",C["green"])
        else:
            self.vm_status.configure(text="No matching scenes — line mein _number_ chahiye (e.g. Script_1_:)",text_color=C["red"])

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
        self._caption_groups.pop(block_num, None)
        self._ss(f"Deleted block #{block_num}. {len(self.blocks)} remaining.",C["orange"])

    def _delete_all_blocks(self):
        """Delete all blocks after confirmation, in small batches for smooth UI."""
        if not self.blocks: return
        total = len(self.blocks)
        if not messagebox.askyesno("Delete All",f"Delete all {total} blocks?\nThis cannot be undone."): return
        frames = [b.get("frame") for b in self.blocks]
        self._ss(f"Cleaning {total} scenes…", C["orange"])

        def _step(i=0, chunk=60):
            end = min(i + chunk, len(frames))
            for fr in frames[i:end]:
                try:
                    if fr is not None:
                        fr.destroy()
                except Exception:
                    pass
            if end < len(frames):
                self._ss(f"Cleaning scenes… {end}/{total}", C["orange"])
                self.after(1, lambda e=end: _step(e, chunk))
                return
            self.blocks.clear()
            self._caption_groups.clear()
            try: self.cap_status_lbl.configure(text="OFF",text_color=C["dim"])
            except Exception: pass
            try: self.progress.set(0)
            except Exception: pass
            cnt=clean_temp_files(); TTSCache.clear_all()
            self._ss(f"All blocks deleted. {cnt} temp files cleaned.",C["green"])

        _step()

    # ── Captions ──
    def _sel_caption_font(self):
        p=filedialog.askopenfilename(parent=self, filetypes=[("Font Files","*.ttf *.otf *.woff *.woff2"),("TrueType","*.ttf"),("OpenType","*.otf"),("All","*.*")])
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

    def _fm(self):
        k=self.api_entry.get().strip()
        if not k: messagebox.showwarning("API","Enter key."); return
        self.api_status_lbl.configure(text="Fetching...",text_color=C["orange"])
        threading.Thread(target=self._fm_worker,args=(k,),daemon=True).start()
    def _fm_worker(self,k):
        try:
            r=requests.get("https://api.elevenlabs.io/v1/models",headers={"xi-api-key":k},timeout=15)
            if r.status_code==401:
                self.after(0,lambda:(self.api_status_lbl.configure(text="✗ Key rejected (401 — invalid/expired key)",text_color=C["red"]) if self.winfo_exists() else None)); return
            r.raise_for_status()
            self.models=r.json(); ns=[m["name"] for m in self.models]
            def _upd():
                try:
                    if not self.winfo_exists(): return
                    self.model_menu.configure(values=ns)
                    lm=self.settings.get("last_model")
                    if lm in ns: self.model_var.set(lm)
                    elif ns: self.model_var.set(ns[0])
                    self.api_status_lbl.configure(text=f"✓ {len(ns)} models",text_color=C["green"])
                except Exception: pass
            self.after(0,_upd)
        except requests.exceptions.Timeout:
            self.after(0,lambda:(self.api_status_lbl.configure(text="✗ Models: request timed out",text_color=C["red"]) if self.winfo_exists() else None))
        except requests.exceptions.ConnectionError:
            self.after(0,lambda:self.api_status_lbl.configure(text="✗ Models: no internet / DNS error",text_color=C["red"]))
        except Exception as e:
            msg=str(e)[:80]
            self.after(0,lambda m=msg:self.api_status_lbl.configure(text=f"✗ Models failed: {m}",text_color=C["red"]))
    def _fv(self):
        k=self.api_entry.get().strip()
        if not k: messagebox.showwarning("API","Enter key."); return
        self.api_status_lbl.configure(text="Fetching voices...",text_color=C["orange"])
        threading.Thread(target=self._fv_worker,args=(k,),daemon=True).start()
    def _fv_worker(self,k):
        try:
            voices = voice_cache.load_voices_cached(api_key=k, force_refresh=True)
        except Exception as e:
            msg = str(e)[:80]
            self.after(0, lambda m=msg: self.api_status_lbl.configure(text=f"✗ Voices failed: {m}", text_color=C["red"]) if getattr(self, "api_status_lbl", None) and self.api_status_lbl.winfo_exists() else None)
            return
        if not voices:
            self.after(0, lambda: self.api_status_lbl.configure(text="✗ 0 voices loaded", text_color=C["orange"]) if getattr(self, "api_status_lbl", None) and self.api_status_lbl.winfo_exists() else None)
            return
        self.voices = voices
        seen = set(); deduped = []
        for v in voices:
            vid = v.get("voice_id", "")
            nm = v.get("name", "?")
            gender = v.get("gender", "")
            provider = v.get("provider", "")
            if not gender:
                nl = nm.lower()
                if any(w in nl for w in ["female","girl","woman","lady","sister","mom","mother","aunt"]): gender = "female"
                elif any(w in nl for w in ["male","boy","man","guy","brother","dad","father","uncle"]): gender = "male"
            if vid and vid not in seen:
                seen.add(vid)
                deduped.append((nm, vid, gender, provider))
        self.voice_list_full = deduped
        count = len(deduped)
        try: voice_cache.save_api_key(k)
        except: pass
        def _upd():
            try:
                if getattr(self, "api_status_lbl", None) and self.api_status_lbl.winfo_exists():
                    self.api_status_lbl.configure(text=f"[OK] {count} voices loaded", text_color=C["green"])
                if hasattr(self, "characters") and self.characters:
                    self._auto_assign_voices(); self._refresh_chars()
            except Exception: pass
        self.after(0, _upd)

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
        if assigned>0:
            def _upd():
                self._refresh_chars()
                self._ss(f"Auto-assigned {assigned} voice(s)",C["green"])
            self.after(0,_upd)

    def _update_filter(self):
        self.filter_menu.configure(values=["All"]+list(self.char_order)); self.filter_var.set("All"); self.active_filter="All"

    def _on_filter(self,choice=None,_fresh=False):
        self.active_filter=choice if choice else self.filter_var.get()
        if self.active_filter=="All" and _fresh:
            # FAST PATH: called right after (re)building the whole scene list
            # from scratch — every block's frame is ALREADY packed in the
            # right order (_make_block() packs itself at creation time), so
            # unpacking and re-packing all of them here again was pure
            # wasted work. With hundreds/thousands of scenes that unpack+
            # repack loop (2x len(blocks) geometry-manager calls) was slow
            # enough on a weak CPU to make the UI feel "stuck" right after
            # loading a big project — exactly when people then try to click
            # logo/caption/preview and it seems like nothing responds.
            self._ss(f"All scenes ({len(self.blocks)})",C["accent"])
            return
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
        self.after(0, lambda: self._on_filter("All", _fresh=True))
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
        p=filedialog.askopenfilename(parent=self, filetypes=[("Video","*.mp4 *.mov *.avi *.mkv *.webm *.flv")])
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
        p=filedialog.askopenfilename(parent=self, filetypes=[("Video","*.mp4 *.mov *.avi *.mkv *.webm *.flv")])
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
                elif sys.platform=="darwin": subprocess.Popen(["open",target], **_NO_WINDOW)
                else: subprocess.Popen(["xdg-open",target], **_NO_WINDOW)
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

        # Build proxy preview with everything mixed in (TTS, clip audio, captions)
        self._ss(f"Building preview #{num}...",C["orange"])
        threading.Thread(target=self._preview_proxy_worker,args=(b,target,num),daemon=True).start()

    def _preview_proxy_worker(self,b,target,num):
        """Quick preview at lower resolution including captions
        and proper clip+TTS volume mixing —
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
        if sfx_path and not os.path.exists(sfx_path): sfx_path=None
        has_sfx=bool(sfx_path)

        # Build video filter graph piece-by-piece for proxy resolution
        vf_parts=[f"scale={pw}:{ph}:flags=fast_bilinear"]
        # Add captions (only for legacy tabs — PRO tabs use _preview_post_hook)
        _is_pro_tab = (hasattr(self, "_stories_burn_captions") or hasattr(self, "_story_cap_on") or
                       hasattr(self, "_rhymes_cap_on") or hasattr(self, "_add_stories_caption_section") or
                       self.__class__.__name__ in ("StoriesEditorFrame", "StoryVideoEditorFrame", "MasterEditorFrame", "RhymesEditorFrame", "VideoMasterEditorFrame"))
        if self.captions_enabled_var.get() and num in self._caption_groups and not _is_pro_tab:
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

        # Build inputs list: target = 0, [tts], [orig_audio]
        # When we looped the video, its audio is gone (-an). Re-add the original file as
        # an audio-only input so the clip-audio mix still works.
        inputs=["-i",target]
        idx_map={"main":0}
        next_idx=1
        if has_tts:
            inputs+=["-i",ap]; idx_map["tts"]=next_idx; next_idx+=1
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

        # Video filter
        vf_str=",".join(vf_parts)
        filter_complex_parts=[]
        v_map=["-map","0:v"]

        # Audio mixing: clip (from main/original input audio) + TTS
        a_inputs=[]
        if has_clip_audio: a_inputs.append((clip_audio_idx, eff_clip, "ca"))
        if has_tts:        a_inputs.append((idx_map["tts"],  eff_tts,  "ta"))
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
            # No filter graph needed — fall back to simple -vf when no audio inputs
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
            auto_ext = (has_tts or has_clip_audio or bgm_on_pv)
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
        ps = filedialog.askopenfilenames(parent=self, filetypes=[
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
        ps=filedialog.askopenfilenames(parent=self, filetypes=[("Video","*.mp4 *.mov *.avi *.mkv *.webm *.flv")])
        if ps: self._mvb(list(ps))
    def _uf(self):
        folder=filedialog.askdirectory(parent=self, title="Video folder")
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
            folder = filedialog.askdirectory(parent=self, title="Select folder with media files")
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
            ps = filedialog.askopenfilenames(parent=self, filetypes=[
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
                b["video"]=p if is_vid else ""
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
        # NOTE: previously this returned early on `video_only=True` too — that was
        # a HUGE trap: in Master tab, "full clip" mode sets video_only=True to mean
        # "don't shorten the clip to the TTS length" (voiceover overlaid over full
        # clip). But the SAME flag was then being read as "skip TTS entirely" here,
        # so Gen Audio silently returned without touching the block status at all →
        # user saw "6 failed — Unknown error". Now we generate TTS as long as text
        # exists, and only silently exit for genuinely-no-text blocks.
        if not text: return
        def st(t,c): self._block_status(b,t,c)
        ci=self.characters.get(char,{}); vid_id=ci.get("voice_id","")
        if not vid_id: vid_id=self.common_voice_id.get()
        if not vid_id:
            st(f"No voice!",C["red"]); b["_tts_err"]="No voice assigned — set a Common Voice or per-character voice"; return
        ak=self.api_entry.get().strip()
        if not ak:
            st("No API!",C["red"]); b["_tts_err"]="No API key entered"; return
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
            b["tts_audio"]=cached; b["_tts_err"]=None; st(f"🔊 Cached ({format_duration(get_duration(cached))})",C["green"]); return
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
            try:
                from ai33_api import ai33_tts_generate
                if ai33_tts_generate(text=chunk_text, voice_id=vid_id, api_key=ak, out_path=rp):
                    chunk_dur = get_duration(rp)
                    if chunk_dur and chunk_dur > 0.25:
                        err = None
                    else:
                        err = "audio too short"
                else:
                    err = "AI33Pro TTS failed"
            except Exception as _e:
                err = str(_e)
            
            if err:
                st(f"TTS fail (chunk {chunk_idx+1}): {err[:60]}", C["red"])
                b["_tts_err"]=err[:100]
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
        
        if not os.path.exists(rp) or os.path.getsize(rp) <= 2048 or get_duration(rp) < 0.25:
            st(f"TTS fail: No audio generated", C["red"])
            b["_tts_err"]="Audio file came back empty or corrupted (0-duration)"
            return
        
        pad = max(0, float(self.silence_var.get())); cl = os.path.join(TEMP_DIR, f"adv_tts_{num}_clean.wav")
        ap = clean_tts_audio(rp, cl, pad_sec=pad) or rp; b["tts_audio"] = ap; b["_tts_err"]=None; TTSCache.store(num, text, ap)
        st(f"🔊 Ready ({format_duration(get_duration(ap))})", C["green"])
        # Task 5: If narrator (has audio now), start backend video compose
        mp = b.get("source_media", "")
        if mp and os.path.exists(mp) and b.get("trim_start") is not None:
            threading.Thread(target=self._auto_process_trim, args=(idx, get_duration(ap)), daemon=True).start()

    # ── Task 4: Generate ALL audio ──
    def _gen_all_audio(self):
        blocks_with_text=[i for i,b in enumerate(self.blocks) if (b.get("text") or "").strip()]
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
                        err_msg = f"Exception: {str(e)[:80]}"
                        self.blocks[idx]["_tts_err"] = err_msg
                        self._sss(f"[Block {idx}] Audio generation error: {str(e)[:50]}")
                        try:
                            self._block_status(self.blocks[idx], f"Error: {str(e)[:40]}", C["red"])
                        except Exception: pass
                with self._progress_lock: done+=1
                self._sp(done/total); self._ss(f"Audio {done}/{total}...",C["orange"])
        
        # Check for failed blocks and report
        ready=sum(1 for i in indices if self.blocks[i].get("tts_audio") and os.path.exists(self.blocks[i]["tts_audio"]))
        failed = total - ready
        
        self._sp(1.0)
        if failed > 0:
            # Show the ACTUAL reason(s) instead of a generic "check API key &
            # internet" guess — e.g. "No voice assigned", "HTTP 401 ...", etc.
            reasons={}
            for i in indices:
                bb=self.blocks[i]
                if bb.get("tts_audio") and os.path.exists(bb.get("tts_audio","")): continue
                r=bb.get("_tts_err") or "Unknown error (see block status)"
                reasons[r]=reasons.get(r,0)+1
            top=sorted(reasons.items(), key=lambda x:-x[1])[:2]
            reason_txt="; ".join(f"{cnt}x {msg}" for msg,cnt in top)
            self._ss(f"Audio done: {ready}/{total} ✓ | {failed} failed — {reason_txt}",C["orange"])
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
                    ts(f"Whiteboard draw: {os.path.basename(mp)} (freeze {freeze_tail:.1f}s)")
                    st("[3/5] Whiteboard draw...", C["orange"])
                    wb_vid = os.path.join(TEMP_DIR, f"adv_wb_{num}.mp4")
                    res = image_to_whiteboard_video(
                        mp, ta, wb_vid, freeze_tail=freeze_tail,
                        out_w=1920, out_h=1080, hand_path=hand)
                    if res and os.path.exists(res) and get_duration(res) > 0.1:
                        vp = res
                        ts("Whiteboard animation created")
                    else:
                        ts("Whiteboard failed - falling back to plain image video")

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
        # Build caption filter if enabled (only for legacy tabs — PRO tabs use _stories_burn_captions)
        cap_filter_str=""
        _is_pro_tab = (hasattr(self, "_stories_burn_captions") or hasattr(self, "_story_cap_on") or
                       hasattr(self, "_rhymes_cap_on") or hasattr(self, "_add_stories_caption_section") or
                       self.__class__.__name__ in ("StoriesEditorFrame", "StoryVideoEditorFrame", "MasterEditorFrame", "RhymesEditorFrame", "VideoMasterEditorFrame"))
        _cap_on = self.captions_enabled_var.get() and (not _is_pro_tab or not bool(getattr(self, "_story_cap_on", lambda: False) and self._story_cap_on.get()))
        _cap_has = num in self._caption_groups
        
        # Only do caption processing if enabled on legacy tabs (NEVER on PRO tabs)
        if _cap_on and _cap_has and not _is_pro_tab:
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

        # ── Audio mixing: Clip audio + TTS audio ──
        clip_vol=b.get("clip_volume",0); master_clip=self.master_vol_var.get()
        tts_vol=b.get("tts_volume",100); master_tts=self.master_tts_vol_var.get()
        eff_clip=(clip_vol/100.0)*(master_clip/100.0)
        eff_tts=(tts_vol/100.0)*(master_tts/100.0)

        # Clip audio comes from the original source file (we pulled it earlier as clip_audio_src).
        # Falls back to whatever vp has if extraction failed.
        clip_aud_path=clip_audio_src if (clip_audio_src and os.path.exists(clip_audio_src)) else (vp if has_audio_stream(vp) else None)
        has_clip_audio=bool(clip_aud_path) and eff_clip>0.001
        has_tts=ap and os.path.exists(ap) and eff_tts>0.001

        sfx_path=None
        sfx_vol=1.0
        has_sfx=False

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
        sp=_asksaveasfilename_safe(parent=self, defaultextension=".mp4", initialdir=OUTPUT_DIR, filetypes=[("MP4","*.mp4")])
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
            subprocess.run(cmd,capture_output=True,timeout=600, **_NO_WINDOW)
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
                        subprocess.run(cmd,capture_output=True,timeout=300, **_NO_WINDOW)
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
                        subprocess.run(cmd,capture_output=True,timeout=300, **_NO_WINDOW)
                        if os.path.exists(io): intro_clips.append(io)
        all_clips=intro_clips+norm
        self._sp(0.7)
        self._ss("Joining...",C["orange"]); self._sss("merge 4/5: concat")
        lp=os.path.join(TEMP_DIR,"adv_cl.txt")
        with open(lp,"w",encoding="utf-8") as f:
            for c in all_clips: f.write(f"file '{os.path.abspath(c)}'\n")
        merged=os.path.join(TEMP_DIR,"adv_merged.mp4")
        subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-i",lp,"-c","copy","-movflags","+faststart",merged],
            capture_output=True,text=True,timeout=900, **_NO_WINDOW)
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
                capture_output=True,text=True,timeout=900, **_NO_WINDOW)
            if os.path.exists(bgm_out): shutil.copy2(bgm_out,final_out)
            else: shutil.copy2(merged,final_out)
        else: shutil.copy2(merged,final_out)
        _finalize_output_resolution(final_out, log=lambda m: self._sss(m))
        try: self._apply_extra_logos_to_file(final_out, include_logo1=getattr(self,"_story_skip_logo",False))
        except Exception as e: print("[LOGO2+] ", e)
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
# Everything else (TTS, captions, logo, BGM,
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
    - Trim & Loop (per-block)
    - Per-block volume sliders
    - Per-block TTS volume sliders
    - Per-block Upload/Audio/Gen buttons (use toolbar instead)

    Each block = 1 frame + 3 labels = 4 widgets (was 20+).
    10,000 blocks = 40,000 widgets (manageable) vs 200,000 (crash).
    """

    def __init__(self, master):
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
        self._add_jesus_transition_section()

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
        """Proper Whiteboard Animation panel in the Video Master sidebar.
        Enable toggle + freeze setting + optional hand-image picker."""
        sb = getattr(self, "_sb_ref", None)
        if sb is None:
            return
        try:
            self._wb_on = ctk.BooleanVar(value=bool(self.settings.get("wb_on")))
            self._wb_freeze_var = ctk.DoubleVar(value=float(self.settings.get("wb_freeze") or 2.5))
            self._wb_hand = self.settings.get("wb_hand") or ""

            card = ctk.CTkFrame(sb, fg_color=C["card"], border_color=C["purple"],
                                border_width=2, corner_radius=8)
            card.grid(row=900, column=0, sticky="ew", padx=6, pady=(4, 6))
            self._wb_card = card

            head = ctk.CTkFrame(card, fg_color="transparent")
            head.pack(fill="x", padx=8, pady=(6, 2))
            ctk.CTkLabel(head, text="\u2588  \u270d\ufe0f WHITEBOARD ANIMATION",
                         text_color=C["purple"], font=("Segoe UI", 13, "bold")).pack(side="left")
            state = "normal" if HAS_CV2 else "disabled"
            ctk.CTkCheckBox(head, text="Enable", variable=self._wb_on, state=state,
                            text_color=C["green"], fg_color=C["green"],
                            font=("Segoe UI", 11, "bold"), width=20,
                            command=self._wb_toggle).pack(side="right")

            ctk.CTkLabel(card,
                         text="Each image is hand-sketched left\u2192right. Drawing finishes a few\n"
                              "seconds before the voiceover ends, then the frame freezes.",
                         text_color=C["dim"], font=("Segoe UI", 9), justify="left"
                         ).pack(anchor="w", padx=10, pady=(0, 4))

            if not HAS_CV2:
                ctk.CTkLabel(card, text="\u26a0 Install 'opencv-python' + 'numpy' to enable.",
                             text_color=C["red"], font=("Segoe UI", 9)
                             ).pack(anchor="w", padx=10, pady=(0, 6))

            # Freeze-tail setting
            fr = ctk.CTkFrame(card, fg_color="transparent"); fr.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(fr, text="Freeze last frame (sec before audio ends):",
                         text_color=C["text"], font=("Segoe UI", 10)).pack(side="left")
            fe = ctk.CTkEntry(fr, textvariable=self._wb_freeze_var, width=50,
                              fg_color=C["entry_bg"], text_color=C["text"],
                              border_color=C["border"])
            fe.pack(side="right")
            fe.bind("<FocusOut>", lambda e: self._wb_save_settings())

            # Optional hand image
            hr = ctk.CTkFrame(card, fg_color="transparent"); hr.pack(fill="x", padx=10, pady=(6, 2))
            ctk.CTkLabel(hr, text="Hand image (optional):", text_color=C["text"],
                         font=("Segoe UI", 10)).pack(side="left")
            ctk.CTkButton(hr, text="\u2715", width=28, height=26, fg_color=C["btn"],
                          hover_color=C["red"], text_color=C["dim"], font=("Segoe UI", 11),
                          command=self._wb_clear_hand).pack(side="right", padx=(4, 0))
            ctk.CTkButton(hr, text="\U0001f4ce Choose Hand", width=120, height=26,
                          fg_color=C["btn"], hover_color=C["btn_hov"], text_color=C["text"],
                          font=("Segoe UI", 10), command=self._wb_upload_hand).pack(side="right")

            self._wb_hand_lbl = ctk.CTkLabel(card, text="", text_color=C["green"],
                                             font=("Segoe UI", 9), anchor="w", justify="left")
            self._wb_hand_lbl.pack(fill="x", padx=12, pady=(0, 2))
            ctk.CTkLabel(card,
                         text="Transparent-background PNG; pen tip at the top-left.\n"
                              "Leave empty to use the built-in hand.",
                         text_color=C["dim"], font=("Segoe UI", 8), justify="left"
                         ).pack(anchor="w", padx=12, pady=(0, 8))
            self._wb_refresh_hand_lbl()
        except Exception as e:
            print(f"[WARN] whiteboard card: {e}")

    def _wb_refresh_hand_lbl(self):
        try:
            h = getattr(self, "_wb_hand", "")
            if h and os.path.exists(h):
                self._wb_hand_lbl.configure(text="\u2713 " + os.path.basename(h), text_color=C["green"])
            else:
                self._wb_hand_lbl.configure(text="(using built-in hand)", text_color=C["dim"])
        except Exception:
            pass

    def _wb_upload_hand(self):
        f = filedialog.askopenfilename(parent=self, 
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
        """Enable/disable whiteboard. Clears cached IMAGE-scene outputs so they
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
            _queue_settings_save(self, self.settings, delay=300, attr_name="_wb_settings_save_job")
        except Exception:
            pass

    def _master_folder_upload(self):
        """Pick ONE master folder; take ALL images & videos inside and map them to
        blocks sequence-wise (block 1 → 1st media, block 2 → 2nd media, …).
        Videos shorter than the voiceover will freeze on their last frame at render."""
        if not self.blocks:
            messagebox.showwarning("Blocks", "Create blocks first (Analyze + Create Blocks).")
            return
        folder = filedialog.askdirectory(parent=self, title="Select MASTER folder (images / videos)")
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
        """Hide Intro sections + Generate All button.
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
        hide_titles = {"INTRO VIDEOS", "TRANSITION"}
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
            self._on_filter("All", _fresh=True)
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
        needs_audio = any(b.get("text") and
                         not (b.get("tts_audio") and os.path.exists(b.get("tts_audio","")))
                         for b in self.blocks)
        if needs_audio:
            ak = self.api_entry.get().strip()
            if not ak:
                messagebox.showwarning("API", "Generate audio first or enter API key.")
                return
        
        # Ask for save location FIRST
        sp = _asksaveasfilename_safe(parent=self, 
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
                       if (b.get("text") or "").strip()
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
        else:
            self._ss("Save failed!", C["red"])

    def _add_jesus_transition_section(self):
        sb = getattr(self, "_sb_ref", None)
        if sb is None: return
        try:
            tr = ctk.CTkFrame(sb, fg_color=C["card"], border_color=C["purple"], border_width=2, corner_radius=8)
            tr.grid(row=903, column=0, sticky="ew", padx=6, pady=(4,6))
            ctk.CTkLabel(tr, text="🔀 Random transitions", text_color=C["purple"],
                         font=("Segoe UI",13,"bold")).pack(anchor="w", padx=10, pady=(8,2))
            tr1 = ctk.CTkFrame(tr, fg_color="transparent"); tr1.pack(fill="x", padx=10, pady=2)
            self._j_tr_on = ctk.BooleanVar(value=bool(self.settings.get("jesus_tr_on")))
            ctk.CTkCheckBox(tr1, text="Enable", variable=self._j_tr_on,
                            text_color=C["text"], fg_color=C["purple"]).pack(side="left")
            ctk.CTkLabel(tr1, text="  Dur:", text_color=C["dim"]).pack(side="left")
            self._j_tr_dur = ctk.DoubleVar(value=float(self.settings.get("jesus_tr_dur") or 0.5))
            ctk.CTkEntry(tr1, textvariable=self._j_tr_dur, width=40, fg_color=C["entry_bg"],
                         text_color=C["text"], border_color=C["border"]).pack(side="left", padx=2)
            ctk.CTkLabel(tr1, text="s", text_color=C["dim"]).pack(side="left")
            tg = ctk.CTkFrame(tr, fg_color="transparent"); tg.pack(fill="x", padx=10, pady=(2,8))
            self._j_tr_vars = {}
            saved = self.settings.get("jesus_tr_types") or ["fade","wipeleft","slideright","circlecrop"]
            for i, t in enumerate(MASTER_TRANSITIONS):
                v = ctk.BooleanVar(value=(t in saved))
                self._j_tr_vars[t] = v
                ctk.CTkCheckBox(tg, text=t, variable=v, width=14, text_color=C["dim"],
                                fg_color=C["purple"], font=("Segoe UI",9)).grid(row=i//3, column=i%3, sticky="w", padx=2, pady=1)
        except Exception as e:
            print("[JESUS-TR]", e)

    def _mw(self, clips, sp):
        """Override: normalize clips → apply random transitions if enabled → base merge."""
        use_tr = bool(getattr(self,"_j_tr_on",None) and self._j_tr_on.get())
        tr_types = [t for t,v in (getattr(self,"_j_tr_vars",{}) or {}).items() if v.get()]
        tr_dur = max(0.2, float(getattr(self,"_j_tr_dur",None) and self._j_tr_dur.get() or 0.5))

        if use_tr and tr_types and len(clips) > 1:
            # Normalize all clips first (same format for xfade)
            norm = []
            for i, c in enumerate(clips):
                if not (c and os.path.exists(c)): continue
                n = os.path.join(TEMP_DIR, f"jn_{i}.mp4")
                cd = get_duration(c)
                _run_ff(["ffmpeg","-y","-i",c,
                         "-vf","scale=1920:1080:force_original_aspect_ratio=decrease,"
                               "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,"
                               "tpad=stop_mode=clone:stop_duration=7200",
                         "-af","aresample=48000:async=1:first_pts=0,apad",
                         "-r","30","-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p",
                         "-c:a","aac","-b:a","192k","-t",f"{cd:.3f}",
                         "-loglevel","error",n], timeout=1800)
                norm.append(n if (os.path.exists(n) and get_duration(n)>0.1) else c)

            merged = os.path.join(TEMP_DIR, "jesus_tr_merged.mp4")
            self._ss("Applying transitions…", C["orange"])
            _merge_with_transitions(norm, tr_types, tr_dur, merged,
                                    logf=lambda m: self._sss(m))
            if os.path.exists(merged) and get_duration(merged) > 0.1:
                # BGM
                bgm_on = bool(getattr(self,"bgm_enabled_var",None) and self.bgm_enabled_var.get())
                bgm_path = self.bgm_var.get() if hasattr(self,"bgm_var") else ""
                if bgm_on and bgm_path and os.path.exists(bgm_path):
                    self._ss("BGM…", C["orange"])
                    bgm_vol = 0.15
                    try: bgm_vol = float(self.bgm_vol_var.get())
                    except: pass
                    vdur = get_duration(merged)
                    bgm_src = bgm_path
                    if bool(getattr(self,"bgm_loop_var",None) and self.bgm_loop_var.get()) and get_duration(bgm_path)<vdur:
                        looped = os.path.join(TEMP_DIR, "j_bgm_lp.m4a")
                        try:
                            xf = getattr(self, "_make_bgm_xfade_loop", None)
                            if xf: bgm_src = xf(bgm_path, vdur, looped) or bgm_path
                        except: pass
                    _run_ff(["ffmpeg","-y","-i",merged,"-i",bgm_src,
                             "-filter_complex",f"[1:a]aresample=48000,volume={bgm_vol:.3f},"
                                               f"apad=whole_dur={vdur:.3f}[b];"
                                               f"[0:a][b]amix=inputs=2:duration=first:normalize=0[a]",
                             "-map","0:v","-map","[a]","-c:v","copy","-c:a","aac","-b:a","192k",
                             "-movflags","+faststart","-loglevel","error",sp], timeout=3600)
                else:
                    shutil.copy2(merged, sp)
                _finalize_output_resolution(sp, log=lambda m: self._sss(m))
                try: self._apply_extra_logos_to_file(sp, include_logo1=getattr(self,"_story_skip_logo",False))
                except Exception as e: print("[LOGO2+] ", e)
                self._sp(1.0)
                if os.path.exists(sp):
                    self._ss(f"✓ Done! {format_duration(get_duration(sp))} → {os.path.basename(sp)}", C["green"])
                else:
                    self._ss("Save failed!", C["red"])
                return
        # No transitions → use base merge
        AdvanceEditorFrame._mw(self, clips, sp)

    def _tab_help_title(self): return "✟ Jesus"
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
        _fd = os.path.join(TEMP_DIR, "story_fonts")
        self._story_fontsdir = _fd if os.path.isdir(_fd) and os.listdir(_fd) else None
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
                              command=self._story_apply_style_defaults).pack(side="right")

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
            ctk.CTkLabel(r4, text="Base text:", text_color=C_["text"], width=88, anchor="w").pack(side="left")
            self._story_cap_primary = ctk.StringVar(value=self.settings.get("story_cap_primary") or "#FFFFFF")
            self._swatch(r4, self._story_cap_primary, "#FFFFFF").pack(side="left", padx=2)
            ctk.CTkLabel(r4, text="Fill:", text_color=C_["text"]).pack(side="left", padx=(10,2))
            self._story_cap_highlight = ctk.StringVar(value=self.settings.get("story_cap_highlight") or "#7C3AED")
            self._swatch(r4, self._story_cap_highlight, "#7C3AED").pack(side="left", padx=2)
            ctk.CTkLabel(r4, text="Border:", text_color=C_["text"]).pack(side="left", padx=(10,2))
            self._story_cap_active = ctk.StringVar(value=self.settings.get("story_cap_active") or "#FFFFFF")
            self._swatch(r4, self._story_cap_active, "#FFFFFF").pack(side="left", padx=2)

            # ── Border on/off + size (for Rhymes/Rhymes1/Cocomelon) ──
            r4b = ctk.CTkFrame(cc, fg_color="transparent"); r4b.pack(fill="x", padx=10, pady=2)
            self._story_cap_border_on = ctk.BooleanVar(value=bool((lambda v: v if v is not None else True)(self.settings.get("story_cap_border_on"))))
            ctk.CTkCheckBox(r4b, text="Border", variable=self._story_cap_border_on,
                            text_color=C_["text"], fg_color=C_["purple"], width=20,
                            command=self._story_save).pack(side="left")
            ctk.CTkLabel(r4b, text="Size:", text_color=C_["dim"]).pack(side="left", padx=(14,2))
            self._story_cap_border_w = ctk.StringVar(value=str(self.settings.get("story_cap_border_w") or ""))
            ctk.CTkEntry(r4b, textvariable=self._story_cap_border_w, width=48,
                         fg_color=C_["entry_bg"], text_color=C_["text"],
                         border_color=C_["border"],
                         placeholder_text="auto").pack(side="left")
            ctk.CTkLabel(r4b, text="px  (blank = style default)",
                         text_color=C_["dim"], font=("Segoe UI",9)).pack(side="left", padx=4)

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
            self._story_cap_font_values = ["(style default)","Poppins","Anton","Montserrat","Playfair Display",
                                           "DejaVu Sans","Comic Sans MS","Comic Neue","Trebuchet MS","Oswald","Bebas Neue",
                                           "Fredoka SemiBold"]
            _cur=self._story_cap_font.get()
            if _cur and _cur not in self._story_cap_font_values:
                self._story_cap_font_values.append(_cur)
            self._story_cap_font_menu = ctk.CTkOptionMenu(r6, variable=self._story_cap_font,
                              values=self._story_cap_font_values,
                              fg_color=C_["btn"], button_color=C_["btn_hov"], width=150,
                              command=lambda *_: self._story_save())
            self._story_cap_font_menu.pack(side="left")
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
        f = filedialog.askopenfilename(parent=self, title="Select a font", filetypes=[("Font","*.ttf *.otf")])
        if not f: return
        try:
            d = os.path.join(TEMP_DIR, "story_fonts"); os.makedirs(d, exist_ok=True)
            dst = os.path.join(d, os.path.basename(f)); shutil.copy2(f, dst)
            self._story_fontsdir = d
            nm = os.path.splitext(os.path.basename(f))[0]
            # Add the uploaded font to the dropdown so it stays selected
            # (without this, setting the StringVar to a value not in the
            # OptionMenu's values list leaves the menu blank and the save
            # cycle can silently revert to "(style default)").
            try:
                vals = getattr(self, "_story_cap_font_values", None) or []
                if nm not in vals:
                    vals.append(nm)
                    self._story_cap_font_values = vals
                if hasattr(self, "_story_cap_font_menu"):
                    self._story_cap_font_menu.configure(values=vals)
            except Exception as _e:
                print(f"[WARN] font menu refresh: {_e}")
            self._story_cap_font.set(nm)
            self._story_save()
            self._ss(f"Font added: {os.path.basename(f)}", C["green"])
        except Exception as e:
            messagebox.showerror("Font", str(e))

    def _story_apply_style_defaults(self, *_):
        """When a preset is chosen, push its defaults into the visible controls.

        The old UI only saved the style name, so Cocomelon still rendered with
        whatever colours/font were left from the previous preset.  Cocomelon is
        intentionally a Rhymes 1 clone with its own default look, so selecting
        it must immediately reset the caption controls to that preset.
        """
        try:
            style = (self._story_cap_style.get() or "").strip().lower()
            st = _story_style_preset(style)
            if style == "cocomelon":
                # Rhymes 1 copy + requested defaults:
                # Font Fredoka SemiBold, text white, pink stroke 6px, subtle
                # black shadow, rounded/title-case children's-caption look.
                if hasattr(self, "_story_cap_font"):
                    self._story_cap_font.set("(style default)")
                if hasattr(self, "_story_cap_caps"):
                    self._story_cap_caps.set("Aa")
                if hasattr(self, "_story_cap_karaoke"):
                    self._story_cap_karaoke.set(True)
                if hasattr(self, "_story_cap_primary"):
                    self._story_cap_primary.set(st.get("primary", "#FFFFFF"))
                if hasattr(self, "_story_cap_highlight"):
                    pal = st.get("multicolor_palette") or [st.get("highlight", "#FF3B30")]
                    self._story_cap_highlight.set(pal[0])
                if hasattr(self, "_story_cap_active"):
                    self._story_cap_active.set(st.get("outline", "#FF4F8B"))
                if hasattr(self, "_story_cap_size"):
                    self._story_cap_size.set(str(st.get("size", 82)))
                if hasattr(self, "_story_cap_box"):
                    self._story_cap_box.set(False)
                if hasattr(self, "_story_cap_boxcolor"):
                    self._story_cap_boxcolor.set(st.get("box_color", "#000000"))
                if hasattr(self, "_story_cap_opacity"):
                    self._story_cap_opacity.set("90")
        except Exception as e:
            print(f"[WARN] style preset apply: {e}")
        self._story_save()

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
        # Clear cached caption overlays so style changes take effect
        try:
            import glob
            for f in glob.glob(os.path.join(TEMP_DIR, "story_capov_*.mov")):
                try: os.remove(f)
                except Exception: pass
        except Exception: pass
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
                bg=self._story_preview_bg(4.0, force_synthetic=True)
                if not bg:
                    self._ss("Caption preview failed (no sample frame)", C["red"]); return
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
            border_color=(self._story_cap_active.get().strip() or None),
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
            border_on=bool(self._story_cap_border_on.get()) if hasattr(self,"_story_cap_border_on") else True,
            outline_w=self._story_int(self._story_cap_border_w.get(), None) if hasattr(self,"_story_cap_border_w") else None,
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

    def _story_preview_sample(self, force_synthetic=False):
        """A real-looking still to preview on. Tries, in order:
             1. a frame from one of YOUR uploaded clips/images (unless force_synthetic is True)
             2. a generated cinematic gradient + grain + vignette
        A flat colour card is useless here — zoom/pan has nothing to bite on
        and the FX overlays get keyed straight out, which is why the preview
        came back black."""
        # 1 — a frame from any uploaded scene
        if not force_synthetic:
            try:
                for b in (self.blocks or []):
                    mp = b.get("source_media") or ""
                    if not (mp and os.path.exists(mp)): continue
                    png = os.path.join(TEMP_DIR, "_fx_sample.png")
                    if is_image_file(mp):
                        im = Image.open(mp).convert("RGB")
                    else:
                        d = get_duration(mp) or 1.0
                        im = extract_frame(mp, min(max(0.5, d * 0.35), max(0.1, d - 0.1)))
                        im = im.convert("RGB")
                    im.thumbnail((1920, 1080), Image.LANCZOS)
                    canvas = Image.new("RGB", (1920, 1080), (10, 12, 16))
                    canvas.paste(im, ((1920 - im.width)//2, (1080 - im.height)//2))
                    canvas.save(png)
                    return png
            except Exception as e:
                print("[STORY preview] clip frame failed:", e)

        # 2 — synthetic scene (clean cinematic gradient + soft light + grain + vignette)
        try:
            from PIL import ImageDraw, ImageFilter
            import random as _rnd
            W, H = 1920, 1080
            img = Image.new("RGB", (W, H))
            d = ImageDraw.Draw(img)
            top, bot = (24, 32, 54), (10, 12, 18)
            for y in range(H):
                t = y / H
                d.line([(0, y), (W, y)],
                       fill=(int(top[0]+(bot[0]-top[0])*t),
                             int(top[1]+(bot[1]-top[1])*t),
                             int(top[2]+(bot[2]-top[2])*t)))
            glow = Image.new("RGB", (W, H), (0, 0, 0))
            gd = ImageDraw.Draw(glow)
            gd.ellipse([W*0.55, -H*0.35, W*1.25, H*0.75], fill=(100, 80, 50))
            gd.ellipse([-W*0.2, H*0.45, W*0.5, H*1.35], fill=(24, 60, 80))
            glow = glow.filter(ImageFilter.GaussianBlur(180))
            img = Image.blend(img, glow, 0.40)
            png = os.path.join(TEMP_DIR, "_fx_sample_clean.png" if force_synthetic else "_fx_sample.png")
            img.save(png)
            return png
        except Exception as e:
            print("[STORY preview] synthetic sample failed:", e)
            return None

    def _story_preview_bg(self, seconds=5.0, force_synthetic=False):
        """Turn the sample still into a short video the FX pipeline can chew on."""
        png = self._story_preview_sample(force_synthetic=force_synthetic)
        bg = os.path.join(TEMP_DIR, "_fx_bg_clean.mp4" if force_synthetic else "_fx_bg.mp4")
        if png and os.path.exists(png):
            _run_ff(["ffmpeg","-y","-loop","1","-t",f"{seconds:.2f}","-i",png,
                     "-vf","scale=1920:1080:force_original_aspect_ratio=decrease,"
                           "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p",
                     "-r","30","-c:v","libx264","-preset","veryfast","-crf","20",
                     "-loglevel","error", bg], timeout=120)
            if os.path.exists(bg) and get_duration(bg) > 0.5:
                return bg
        # last-ditch fallback
        _run_ff(["ffmpeg","-y","-f","lavfi",
                 "-i",f"testsrc2=s=1920x1080:r=30:d={seconds:.2f}",
                 "-c:v","libx264","-preset","ultrafast","-pix_fmt","yuv420p",
                 "-loglevel","error", bg], timeout=60)
        return bg if os.path.exists(bg) else None

    def _story_preview_effect(self):
        eff = self._story_fx_var.get()
        try: motion = self._story_motion_var.get()
        except Exception: motion = "None"
        if (not eff or eff == "None") and (not motion or motion == "None"):
            messagebox.showinfo("Preview Effect",
                                "Choose an effect and/or a camera motion first."); return
        self._ss(f"Rendering preview: {eff} + {motion}…", C["orange"])

        def work():
            try:
                bg = self._story_preview_bg(5.0)
                if not bg:
                    self._ss("Preview failed — could not build a sample frame", C["red"]); return
                out = os.path.join(TEMP_DIR, "_fx_preview.mp4")
                try: opts = dict(self._story_opts())
                except Exception: opts = {}
                opts["captions_on"] = False
                # freeze_start=0 → the effect + motion run across the whole
                # sample, which is exactly what you want to judge them.
                res = story_apply_fx_captions(bg, out, eff or "None", "", 5.0,
                                              opts, freeze_start=0.0)
                if res and os.path.exists(res) and get_duration(res) > 0.1:
                    title = " + ".join([x for x in (eff, motion) if x and x != "None"])
                    self.after(0, lambda: MiniPlayerWindow(self, res,
                               title_text=f"Preview: {title}", auto_open_external=False))
                    self._ss("Effect preview ready", C["green"])
                else:
                    self._ss("Effect preview failed (check console)", C["red"])
            except Exception as e:
                self._ss(f"Effect preview error: {str(e)[:40]}", C["red"])
                print("[STORY preview] error:", e)
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
        canvas_w, canvas_h = self._story_canvas_wh()
        logo_params = self._story_logo_params(canvas_w, canvas_h)
        if (not eff or eff == "None") and not cap_on and not motion_on and not logo_params:
            return prev_out
        fs = self._story_freeze_start(b, dur)
        out = os.path.join(TEMP_DIR, f"_proxy_story_{num}.mp4")
        try:
            res = story_apply_fx_captions(prev_out, out, eff, b.get("text","") or "", dur,
                                          self._story_opts(), freeze_start=fs, logo=logo_params,
                                          canvas_w=canvas_w, canvas_h=canvas_h)
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
        ps = filedialog.askopenfilenames(parent=self, filetypes=[("Video","*.mp4 *.mov *.avi *.mkv *.webm")])
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
                               "-of","csv=p=0",path], capture_output=True, text=True, **_NO_WINDOW)
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
        canvas_w, canvas_h = self._story_canvas_wh()
        # NOTE: Logo 1 is intentionally NOT composited here anymore. Baking it
        # in per-scene, at this scene's canvas size, is exactly what caused it
        # to drift at 2K/4K — a later whole-video resolution pass could still
        # shift it. Logo 1 is now drawn once, at the very end, at the TRUE
        # final pixel size, together with any extra logos (see _gw's caller
        # chain -> _apply_extra_logos_to_file(..., include_logo1=True)).
        if (not eff or eff == "None") and not cap_on and not motion_on:
            return
        dur = get_duration(op)
        if dur <= 0.1: return
        fs = self._story_freeze_start(b, dur)
        out = os.path.join(TEMP_DIR, f"story_final_{b['num']}.mp4")
        try:
            res = story_apply_fx_captions(op, out, eff, b.get("text","") or "", dur,
                                          self._story_opts(), freeze_start=fs, logo=None,
                                          canvas_w=canvas_w, canvas_h=canvas_h)
            if res and os.path.exists(res) and get_duration(res) > 0.1:
                b["output"] = res
        except Exception as e:
            self._sss(f"Story FX/caption error: {str(e)[:50]}")

    def _story_canvas_wh(self):
        """The exact frame size (W,H) the Story render composites onto for THIS
        project. MUST be identical to what _get_preview_bg() used when you
        dragged the logo into place in 'Preview & Position' — that's the whole
        bug this fixes: the preview used to size its canvas from the real scene
        media, while the final render always composited on a hardcoded
        1920x1080 canvas. A logo placed near an edge (top-left worked because
        it's close to 0,0 either way; bottom-right didn't, because the two
        canvases disagreed the most out there) would drift toward the middle.
        Cached per render session so every scene in the same video lands on
        the same canvas."""
        sig = (len(self.blocks or []), tuple(b.get("source_media","") for b in (self.blocks or [])))
        cached = getattr(self, "_story_cached_wh", None)
        cached_sig = getattr(self, "_story_cached_wh_sig", None)
        if cached and cached_sig == sig:
            return cached
        w = h = 0
        try:
            bg, _ = self._get_preview_bg()
            w, h = bg.size
        except Exception:
            pass
        if not w or not h:
            w, h = 1920, 1080
        self._story_cached_wh = (w, h)
        self._story_cached_wh_sig = sig
        return self._story_cached_wh

    def _story_logo_params(self, W=None, H=None):
        """Compute the STATIC logo placement (path, size, position, opacity) for a
        frame — same geometry as the preview (see _story_canvas_wh) — so the
        logo lands exactly where you dragged it, after the motion effect,
        without stretching."""
        if W is None or H is None:
            W, H = self._story_canvas_wh()
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
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, **_NO_WINDOW)

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
    "Rhymes",
    "Rhymes 1",
    "Cocomelon",
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
    text colour inside that box, primary = the other (non-active) words.
    pop = per-word scale pop-in animation instead of the plain fade.
    caps_default = this style's own default case-conversion, used only when
    the caller hasn't explicitly picked one via opts['caps']."""
    n=(name or "").strip().lower()
    P=dict(font="Poppins", size=72, primary="#FFFFFF", highlight="#7C3AED", active_text="#FFFFFF",
           outline="#000000", outline_w=8, shadow=1, box=False, box_color="#000000",
           bold=1, align=2, marginv=120, pop=False, caps_default=None)
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
    elif n=="rhymes":
        # Rounded bold sans-serif, white fill / gold outline, all words
        # visible from the start of each caption line — the active word
        # simply flips white→gold as it's spoken (classic karaoke fill,
        # no scale/bounce). All-lowercase by default.
        P.update(font="Comic Sans MS", primary="#FFEFD6", highlight="#00D1FF", active_text="#7A2CFF",
                 outline="#7A2CFF", outline_w=7, size=82, pop=False, caps_default="title",
                 rhymes_liquid=True)
    elif n=="rhymes 1":
        # EXACT same structure/animation as "Rhymes" (rounded bold sans-serif,
        # thick purple outline, title-case, liquid glyph-fill karaoke reveal).
        # ONLY difference: the liquid FILL colour rotates word-by-word through
        # a fixed rainbow palette (word 0 = red, 1 = yellow, 2 = green,
        # 3 = blue, then repeat). Base colour + outline + wavy liquid front
        # are identical to "Rhymes".
        P.update(font="Comic Sans MS", primary="#FFEFD6", highlight="#00D1FF", active_text="#7A2CFF",
                 outline="#7A2CFF", outline_w=7, size=82, pop=False, caps_default="title",
                 rhymes_liquid=True, rhymes_multicolor=True,
                 multicolor_palette=["#FF3B30", "#FFCC00", "#34C759", "#0A84FF"])
    elif n=="cocomelon":
        # Cocomelon preset — exact Rhymes 1 karaoke/liquid glyph-fill structure,
        # with the requested default look:
        #   Font   : Fredoka SemiBold  (uploaded via 📎 Upload if not installed)
        #   Text   : White
        #   Stroke : Pink #FF4F8B, 6 px
        #   Shadow : subtle black (~15% opacity)
        #   Caps   : First-letter capital (title case)
        P.update(font="Fredoka SemiBold", primary="#FFFFFF", highlight="#FF3B30",
                 active_text="#FFFFFF", outline="#FF4F8B", outline_w=6,
                 shadow=2, size=82, pop=False, caps_default="title",
                  rhymes_liquid=True, rhymes_multicolor=True, shadow_alpha=38,
                  multicolor_palette=["#FF3B30", "#FFCC00", "#34C759", "#0A84FF"])
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
    caps = opts.get("caps") or st.get("caps_default") or "none"
    pop = bool(st.get("pop", False))
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
            if pop:
                # Per-word scale pop-in: shrink→overshoot→settle, timed to
                # each word's own karaoke start offset (ms) within the line.
                parts=[]
                for i, w in enumerate(c):
                    t0 = i * per * 10          # ms, this word's start within the line
                    t1 = t0 + 70
                    t2 = t0 + 160
                    t3 = t0 + 260
                    parts.append(
                        f"{{\\kf{per}\\fscx85\\fscy85"
                        f"\\t({t0},{t1},\\fscx108\\fscy108)"
                        f"\\t({t1},{t2},\\fscx96\\fscy96)"
                        f"\\t({t2},{t3},\\fscx100\\fscy100)}}"
                        f"{conv([w])} "
                    )
                txt="".join(parts).strip()
            else:
                txt="".join(f"{{\\kf{per}}}{conv([w])} " for w in c).strip()
            txt="{\\fad(80,80)}"+txt
        else:
            txt="{\\fad(80,80)}"+conv(c)
        lines.append(f"Dialogue: 0,{tc(start)},{tc(end)},S,,0,0,0,,{txt}")
    ass="\n".join(head+lines)
    p=os.path.join(TEMP_DIR, f"story_cap_{abs(hash((text,duration)))%99999}.ass")
    open(p,"w",encoding="utf-8").write(ass)
    return p


# A CTkOptionMenu builds a real Tk menu entry per value. An ElevenLabs account
# with the shared library can return thousands of voices — handing all of them
# to the menu locks the UI for many seconds ("voice load pe hang"). Cap what
# the dropdown holds; the 🔍 Search window still sees the full list.
VOICE_MENU_CAP = 80

def _cap_voice_names(names):
    names = list(names or [])
    if len(names) <= VOICE_MENU_CAP:
        return names or ["(none)"]
    return names[:VOICE_MENU_CAP] + [f"… +{len(names)-VOICE_MENU_CAP} more — use 🔍 Search"]

def _story_caption_font(name, size, fontsdir=None):
    from PIL import ImageFont
    cands=[]
    nm=(name or "").strip()
    def _norm(s): return "".join(ch for ch in (s or "").lower() if ch.isalnum())
    # Well-known family tokens we might see in a preset's default font name
    # OR in the user's uploaded filename. Kept broad so "Fredoka SemiBold"
    # still matches "Fredoka-VariableFont_wdth,wght.ttf", etc.
    _FAMILIES = ("fredoka","poppins","montserrat","anton","comicneue","comicsans",
                 "bebasneue","oswald","playfair","playfairdisplay","dejavusans",
                 "dejavusansmono","quicksand","nunito","lato","raleway","opensans",
                 "roboto","inter","rubik","cabin","karla","mulish","figtree")
    def _tokens(k):
        found=[]
        for fam in _FAMILIES:
            if fam in k: found.append(fam)
        for w in ("semibold","demibold","medium","regular","bold","light","black","thin","italic","variablefont"):
            if w in k: found.append(w)
        return found
    def _font_score(path, key):
        fn = _norm(os.path.splitext(os.path.basename(path))[0])
        if not key or not fn: return 0
        if key == fn: return 200
        if key in fn: return 100
        if fn in key: return 90
        score = 0
        kt = _tokens(key); ft = _tokens(fn)
        fam_hit = [t for t in kt if t in _FAMILIES and t in ft]
        if fam_hit: score += 60
        wants_semibold = any(w in kt for w in ("semibold","demibold"))
        has_semibold  = any(w in ft for w in ("semibold","demibold"))
        if wants_semibold and has_semibold: score += 30
        if "bold" in kt and "bold" in ft: score += 20
        if "italic" in kt and "italic" in ft: score += 10
        if not wants_semibold and "bold" not in kt:
            if "regular" in ft or "variablefont" in ft: score += 5
        return score
    # Default fontsdir to the standard uploads folder even when the caller
    # forgot to plumb it through — otherwise a preset's default font (e.g.
    # Fredoka SemiBold for Cocomelon) silently falls all the way through
    # to Arial even though the user just uploaded the ttf.
    if not fontsdir:
        _def_fd = os.path.join(TEMP_DIR, "story_fonts")
        if os.path.isdir(_def_fd): fontsdir = _def_fd
    if fontsdir and os.path.isdir(fontsdir):
        pool=[os.path.join(fontsdir,f) for f in os.listdir(fontsdir)
              if f.lower().endswith((".ttf",".otf"))]
        if nm and nm!="(style default)":
            key=_norm(nm)
            scored=[(p,_font_score(p,key)) for p in pool]
            matched=[p for p,s in sorted(scored,key=lambda x:x[1],reverse=True) if s>0]
            # Only fall back to *any* uploaded font when nothing scored — a
            # zero-score fallback would silently override the requested name.
            cands += matched if matched else pool
        else:
            cands += pool
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
                        if f.lower().endswith((".ttf",".otf")) and _norm(base) in _norm(f):
                            cands.insert(0, os.path.join(root,f))
        # These are Google Fonts (Nunito, Quicksand, Poppins, Montserrat,
        # Comic Neue...) that are almost NEVER pre-installed on a plain
        # Windows machine — without this, requesting them silently fell all
        # the way through to plain Arial (or worse, PIL's tiny bitmap
        # default font), which is why the caption font looked wrong even
        # though the style said "Nunito". Segoe UI (Semi)Bold is bundled
        # with every Windows install since Vista and is visually much
        # closer to a rounded/friendly font than Arial — try it BEFORE the
        # harder fallbacks below.
        if base.lower() in ("nunito","quicksand","poppins","montserrat","comicneue","opensans","lato","raleway"):
            if os.path.isdir(wf):
                cands += [os.path.join(wf,"seguisb.ttf"), os.path.join(wf,"segoeuib.ttf")]
            cands += ["seguisb.ttf","segoeuib.ttf","Segoe UI Semibold","Segoe UI Bold"]
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
                 "Zoom + Shake","Pan L->R","Pan R->L","Pan Up","Pan Down","Rotate Sway",
                 # ── new cinematic moves ──
                 "Drift L->R","Drift R->L","Diagonal Drift","Slow Push In",
                 "Breathe","Handheld","Parallax Sway"]
_STORY_MOTION_KEY = {"none":"none","zoom in-out":"zoominout","zoom in":"zoomin","zoom out":"zoomout",
    "zoom pulse":"zoompulse","shake":"shake","zoom + shake":"zoomshake","pan l->r":"panlr",
    "pan r->l":"panrl","pan up":"panud","pan down":"pandu","rotate sway":"rotate",
    "drift l->r":"driftlr","drift r->l":"driftrl","diagonal drift":"driftdiag",
    "slow push in":"pushin","breathe":"breathe","handheld":"handheld","parallax sway":"parallax"}

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
    # ── new cinematic moves ────────────────────────────────────────────────
    if motion in ("driftlr","driftrl","driftdiag"):
        # slow lateral glide WITH a gentle push-in (classic doc/story look)
        z=zin(0.10*spd); mx="(iw-iw/zoom)"; my="(ih-ih/zoom)"
        if motion=="driftlr":   x=f"{mx}*(0.15+0.70*{PROG})"; y=f"{my}/2"
        elif motion=="driftrl": x=f"{mx}*(0.85-0.70*{PROG})"; y=f"{my}/2"
        else:                   x=f"{mx}*(0.12+0.76*{PROG})"; y=f"{my}*(0.15+0.70*{PROG})"
        return [zp(z,x,y)], "base"
    if motion=="pushin":
        return [zp(zin(0.09*spd))], "base"           # very slow, steady push
    if motion=="breathe":
        z=(f"if(lt(on,{FSf}),1,1+{0.028*spd:.4f}*(1-cos(2*PI*{0.28*spd:.3f}*(on-{FSf})/{fps})))" if fs>0.05
           else f"1+{0.028*spd:.4f}*(1-cos(2*PI*{0.28*spd:.3f}*on/{fps}))")
        return [zp(z)], "base"
    if motion=="handheld":
        # small, irregular drift — two out-of-phase sines per axis = organic
        amp=max(3,int(round(7*spd))); z="1.06"
        x=(f"iw/2-(iw/zoom/2)+{GATE}*{amp}*(sin(2*PI*{0.7*spd:.3f}*on/{fps})"
           f"+0.6*sin(2*PI*{1.9*spd:.3f}*on/{fps}))")
        y=(f"ih/2-(ih/zoom/2)+{GATE}*{amp}*(cos(2*PI*{0.5*spd:.3f}*on/{fps})"
           f"+0.5*sin(2*PI*{1.3*spd:.3f}*on/{fps}))")
        return [zp(z,x,y)], "base"
    if motion=="parallax":
        # lateral sway + counter-rotation → subtle 3D parallax feel
        amp=max(6,int(round(22*spd))); ang_a=0.012*spd; fr=0.35*spd
        z=zin_out(0.08*spd)
        x=f"iw/2-(iw/zoom/2)+{GATE}*{amp}*sin(2*PI*{fr:.3f}*on/{fps})"
        y=f"ih/2-(ih/zoom/2)"
        gate=(f"if(lt(t,{fs:.3f})\\,0\\,1)" if fs>0.05 else "1")
        ang=f"{gate}*{ang_a:.4f}*sin(2*PI*{fr*0.9:.3f}*t+1.2)"
        return [f"[scaled]zoompan=z='{z}':x='{x}':y='{y}':d=1:s={W}x{H}:fps={fps}[pz]",
                f"[pz]scale=ceil(iw*1.12/2)*2:ceil(ih*1.12/2)*2,rotate='{ang}':c=black,crop={W}:{H}[base]"], "base"
    return [zp(zin_out(0.12*spd))], "base"


_ENC_CACHE={}
def _ffmpeg_has_encoder(name):
    """True if this ffmpeg build ships the given encoder (cached)."""
    if name in _ENC_CACHE: return _ENC_CACHE[name]
    ok=False
    try:
        r=subprocess.run(["ffmpeg","-hide_banner","-encoders"],
                         capture_output=True, text=True, timeout=15, **_NO_WINDOW)
        ok = bool(r and r.stdout and (f" {name} " in r.stdout or f" {name}\n" in r.stdout
                                      or name in r.stdout))
    except Exception:
        ok=False
    _ENC_CACHE[name]=ok
    return ok

def _story_render_caption_overlay(text, duration, W, H, opts, out_path, fps=30, progress_cb=None):
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
    outline=_hx(opts.get("border_color") or st["outline"], "#000000")
    # border_on: if explicitly False in opts, set ow=0; else use opts outline_w or preset
    _border_on = opts.get("border_on", True)
    if not _border_on:
        ow = 0
    elif opts.get("outline_w") is not None:
        ow = max(0, int(opts.get("outline_w") or 0))
    else:
        ow = max(0, int(st["outline_w"]))
    line_bg_on=bool(opts.get("box", st["box"]))
    line_bg=_hx(opts.get("box_color"), st["box_color"])
    box_alpha=int(round(float(opts.get("box_opacity",90))*255/100))
    active_text=_hx(opts.get("active_text") or st.get("active_text") or "#FFFFFF","#FFFFFF")
    caps=opts.get("caps") or st.get("caps_default") or "none"; karaoke=bool(opts.get("karaoke",True))
    mode=(opts.get("mode") or "box").lower()
    pop_words=bool(st.get("pop", False))
    if not karaoke and mode in ("box","highlight","pop","word"):
        mode="plain"
    px=float(opts.get("pos_x", 0.5)); py=float(opts.get("pos_y", 0.80))
    _fname = opts.get("font")
    if not _fname or _fname == "(style default)": _fname = st["font"]
    font=_story_caption_font(_fname, size, opts.get("fontsdir"))
    font_big=_story_caption_font(_fname, int(size*1.18), opts.get("fontsdir"))
    font_word=_story_caption_font(_fname, int(size*1.6), opts.get("fontsdir"))
    def conv(s):
        if caps=="upper": return s.upper()
        if caps=="title": return s.title()
        if caps=="lower": return s.lower()
        return s
    # ── Timing source ────────────────────────────────────────────────────
    # opts["word_times"] (optional) = [{"word":str,"start":float,"end":float}, …]
    #   • Whisper auto-captions  → REAL per-word timestamps from the clip audio
    #   • Scripted blocks        → evenly spread across the TTS duration
    # When absent we fall back to the old proportional-by-length estimate.
    wt_in = opts.get("word_times") or None
    spans=[]
    if wt_in:
        mw = max(1, int(opts.get("max_words",6) or 6))
        cur=[]
        def _flush(cw):
            if not cw: return
            spans.append({
                "start": float(cw[0]["start"]),
                "end":   max(float(cw[-1]["end"]), float(cw[0]["start"])+0.15),
                "words": [str(w["word"]) for w in cw],
                "wt":    [(float(w["start"]), float(w["end"])) for w in cw],
            })
        for w in wt_in:
            cur.append(w)
            if len(cur) >= mw: _flush(cur); cur=[]
        _flush(cur)
    if not spans:
        wt_in = None
        total=sum(len(c) for c in chunks) or 1
        t=0.0
        for c in chunks:
            cd=duration*len(c)/total; per=cd/max(1,len(c))
            spans.append({"start":t, "end":t+cd, "words":c,
                          "wt":[(t+i*per, t+(i+1)*per) for i in range(len(c))]})
            t+=cd
    cx=int(px*W); cy=int(py*H)
    spc=int(size*0.32); pad_x=int(size*0.30); pad_y=int(size*0.16); rad=int(size*0.32)
    # Cap overlay fps at 15 — captions are text, not motion; halves render time
    overlay_fps = min(fps, 10)  # 10fps enough for text captions
    cmd=["ffmpeg","-y","-f","rawvideo","-pix_fmt","rgba","-s",f"{W}x{H}","-r",str(overlay_fps),"-i","-",
         "-c:v","qtrle","-loglevel","error",out_path]
    N=int(round(duration*overlay_fps))
    _use_pngseq = not _ffmpeg_has_encoder("qtrle")
    proc=None; pngdir=None; frame_i=0
    if _use_pngseq:
        pngdir=os.path.join(TEMP_DIR, f"capseq_{abs(hash(out_path))%99999}")
        try: shutil.rmtree(pngdir, ignore_errors=True)
        except Exception: pass
        os.makedirs(pngdir, exist_ok=True)
    else:
        try:
            proc=subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, **_NO_WINDOW)
        except Exception as e:
            print("[STORY] qtrle pipe failed, switching to PNG sequence:", e)
            _use_pngseq=True
            pngdir=os.path.join(TEMP_DIR, f"capseq_{abs(hash(out_path))%99999}")
            os.makedirs(pngdir, exist_ok=True)
    probe=Image.new("RGBA",(8,8)); pd=ImageDraw.Draw(probe)
    def wbb(s,f): 
        b=pd.textbbox((0,0),s,font=f,stroke_width=ow); return b[2]-b[0], b[3]-b[1], b[1]
    _pop_font_cache = {}
    def _pop_font(scale):
        sz = max(8, int(round(size * scale)))
        if sz not in _pop_font_cache:
            _pfn = opts.get("font")
            if not _pfn or _pfn == "(style default)": _pfn = st["font"]
            _pop_font_cache[sz] = _story_caption_font(_pfn, sz, opts.get("fontsdir"))
        return _pop_font_cache[sz]
    def _pop_scale(elapsed):
        # shrink → overshoot → settle, ~260ms total
        if elapsed < 0.07:   return 0.85 + (1.08 - 0.85) * (elapsed / 0.07)
        if elapsed < 0.16:   return 1.08 + (0.96 - 1.08) * ((elapsed - 0.07) / 0.09)
        if elapsed < 0.26:   return 0.96 + (1.00 - 0.96) * ((elapsed - 0.16) / 0.10)
        return 1.0
    is_rhymes_liquid = bool(st.get("rhymes_liquid")) or ((opts.get("style") or "").lower()=="rhymes")
    is_rhymes_multi = bool(st.get("rhymes_multicolor")) or ((opts.get("style") or "").lower()=="rhymes 1")
    rhymes_border = _hx(opts.get("border_color") or st.get("outline") or "#7A2CFF", "#7A2CFF")
    # Rainbow palette for "Rhymes 1": cycles word-by-word left→right.
    _multi_hex = opts.get("multicolor_palette") or st.get("multicolor_palette")                  or ["#FF3B30", "#FFCC00", "#34C759", "#0A84FF"]
    multi_palette = [_hx(c, "#FFFFFF") for c in _multi_hex] or [primary]
    def _draw_liquid_rhymes(draw, x0, y0, text, font_obj, progress, base_col, fill_col, border_col, stroke_w):
        # TRUE GLYPH-ONLY liquid fill (Disney / rhymes look):
        #   1) the whole word is ALWAYS drawn (base colour + border on every
        #      glyph) so captions can never "disappear";
        #   2) a wavy left->right liquid front reveals the FILL colour, but the
        #      reveal is clipped to the exact glyph shape (text alpha mask), so
        #      the fill only ever appears INSIDE the letters -- never a box.
        # NOTE: everything is drawn on FULL-CANVAS layers at the real (x0,y0)
        # absolute coordinates. The previous version drew onto a tiny cropped
        # layer with a wrong offset, which pushed the text off that layer and
        # produced a 100%-transparent frame -- that is why captions vanished.
        import math
        try:
            from PIL import ImageChops, ImageFilter
        except Exception:
            ImageChops = None; ImageFilter = None
        progress = max(0.0, min(1.0, float(progress)))
        Wc, Hc = img.size
        sw = max(1, int(stroke_w))
        shadow_alpha = int(st.get("shadow_alpha") or 0)
        if shadow_alpha > 0:
            shadow_layer = Image.new("RGBA", (Wc, Hc), (0, 0, 0, 0))
            sd = ImageDraw.Draw(shadow_layer)
            off = max(2, sw // 2)
            sd.text((x0 + off, y0 + off), text, font=font_obj,
                    fill=(0, 0, 0, max(0, min(255, shadow_alpha))),
                    stroke_width=sw,
                    stroke_fill=(0, 0, 0, max(0, min(255, shadow_alpha))))
            img.alpha_composite(shadow_layer)
        # 1) base word -- always visible, full opacity, border on every glyph
        base_layer = Image.new("RGBA", (Wc, Hc), (0, 0, 0, 0))
        bd = ImageDraw.Draw(base_layer)
        bd.text((x0, y0), text, font=font_obj,
                fill=(base_col[0], base_col[1], base_col[2], 255),
                stroke_width=sw,
                stroke_fill=(border_col[0], border_col[1], border_col[2], 255))
        img.alpha_composite(base_layer)
        if progress <= 0:
            return
        # 2) filled word on its own layer with identical stroke geometry to prevent subpixel shift
        fill_layer = Image.new("RGBA", (Wc, Hc), (0, 0, 0, 0))
        fd = ImageDraw.Draw(fill_layer)
        fd.text((x0, y0), text, font=font_obj,
                fill=(fill_col[0], fill_col[1], fill_col[2], 255),
                stroke_width=sw,
                stroke_fill=(border_col[0], border_col[1], border_col[2], 255))
        glyph_alpha = fill_layer.getchannel("A")
        # 3) liquid reveal mask -- wavy vertical front sweeping across the word
        bbox = draw.textbbox((x0, y0), text, font=font_obj, stroke_width=sw)
        x_left = max(0, bbox[0] - sw); x_right = min(Wc, bbox[2] + sw)
        span = max(1, x_right - x_left)
        fill_x = int(x_left + span * progress)
        amp = max(2, int(sw * 1.4))
        liquid = Image.new("L", (Wc, Hc), 0)
        ld = ImageDraw.Draw(liquid)
        pts = []
        for yy in range(0, Hc + 1, 2):
            wave = int(math.sin((yy * 0.13) + (progress * math.pi * 4.0)) * amp)
            pts.append((fill_x + wave, yy))
        ld.polygon([(0, 0), (fill_x, 0)] + pts + [(0, Hc)], fill=255)
        if ImageFilter is not None:
            liquid = liquid.filter(ImageFilter.GaussianBlur(radius=max(1, sw // 4)))
        # 4) final alpha = glyph shape (INTERSECT) liquid front
        if ImageChops is not None:
            final_alpha = ImageChops.multiply(glyph_alpha, liquid)
        else:
            final_alpha = glyph_alpha
        fill_layer.putalpha(final_alpha)
        img.alpha_composite(fill_layer)

    for f in range(N):
        tt=f/overlay_fps
        if progress_cb and f % 30 == 0:
            try: progress_cb(f, N)
            except Exception: pass
        img=Image.new("RGBA",(W,H),(0,0,0,0)); d=ImageDraw.Draw(img)
        sp=None
        for s in spans:
            if s["start"] <= tt < s["end"]: sp=s; break
        if sp is None:
            if wt_in:
                # Real speech timings → silence gap: draw nothing (clean look)
                if proc and proc.stdin: proc.stdin.write(img.tobytes()); continue
            sp = spans[-1] if tt >= spans[-1]["end"] else spans[0]
        chunk = sp["words"]
        active = -1
        if karaoke:
            for i,(ws,we) in enumerate(sp["wt"]):
                if ws <= tt < we: active=i; break
            if active < 0:
                active = 0
                for i,(ws,_we) in enumerate(sp["wt"]):
                    if tt >= ws: active=i
        words=[conv(w) for w in chunk]

        if mode=="word":
            w=words[active if active>=0 else 0]
            ww,wh,yb=wbb(w,font_word)
            x=cx-ww//2; ytop=cy-wh//2
            d.rounded_rectangle([x-pad_x, ytop-pad_y, x+ww+pad_x, ytop+wh+pad_y], radius=rad,
                                fill=(highlight[0],highlight[1],highlight[2],255))
            d.text((x, ytop-yb), w, font=font_word, fill=(active_text[0],active_text[1],active_text[2],255),
                   stroke_width=ow, stroke_fill=(outline[0],outline[1],outline[2],255))
            if proc and proc.stdin: proc.stdin.write(img.tobytes()); continue

        # line modes
        widths=[wbb(w,font)[0] for w in words]
        _,wh,yb=wbb("Ayg",font)
        total_w=sum(widths)+spc*(len(words)-1)
        x=cx-total_w//2; ytop=cy-wh//2
        if is_rhymes_liquid:
            line_start=sp["wt"][0][0] if sp.get("wt") else sp["start"]
            line_end=sp["wt"][-1][1] if sp.get("wt") else sp["end"]
            prog=(tt-line_start)/max(0.05,(line_end-line_start))
            prog=max(0.0,min(1.0,prog)); prog=prog*prog*(3-2*prog)
            if is_rhymes_multi:
                # Rhymes 1 keeps the exact same glyph-only liquid fill, but the
                # reveal is timed per word (true karaoke), not shared across the
                # whole line. Previous words stay fully filled, the active word
                # fills left-to-right, and upcoming words remain in the base
                # colour until their own turn starts.
                xw = x
                word_times = sp.get("wt") or []
                for i, w in enumerate(words):
                    fill_col = multi_palette[i % len(multi_palette)]
                    if i < len(word_times):
                        ws, we = word_times[i]
                        word_prog = (tt - ws) / max(0.05, (we - ws))
                    else:
                        word_prog = prog
                    word_prog = max(0.0, min(1.0, word_prog))
                    word_prog = word_prog * word_prog * (3 - 2 * word_prog)
                    _draw_liquid_rhymes(d, xw, ytop-yb, w, font, word_prog,
                                        primary, fill_col, rhymes_border, max(1,ow))
                    xw += widths[i] + spc
            else:
                full_text=" ".join(words)
                _draw_liquid_rhymes(d, x, ytop-yb, full_text, font, prog, primary, highlight, rhymes_border, max(1,ow))
            if _use_pngseq:
                img.save(os.path.join(pngdir, f"f{frame_i:06d}.png")); frame_i+=1
            else:
                if proc and proc.stdin: proc.stdin.write(img.tobytes())
            continue
        if line_bg_on:
            d.rounded_rectangle([x-pad_x, ytop-pad_y, x+total_w+pad_x, ytop+pad_y+wh], radius=rad,
                                fill=(line_bg[0],line_bg[1],line_bg[2],box_alpha))
        for i,w in enumerate(words):
            ww=widths[i]; act=(i==active and mode!="plain")
            draw_font = font; x_draw = x; y_draw = ytop - yb
            if act and pop_words and karaoke:
                elapsed = tt - sp["wt"][i][0]
                scale = _pop_scale(elapsed) if elapsed >= 0 else 0.85
                if abs(scale - 1.0) > 0.01:
                    draw_font = _pop_font(scale)
                    dw, dh, dyb = wbb(w, draw_font)
                    x_draw = x + (ww - dw) // 2                  # stay centered in its own slot
                    y_draw = ytop - dyb - (dh - wh) // 2          # re-center vertically too
            if act and mode in ("box","pop"):
                d.rounded_rectangle([x-int(pad_x*0.7), ytop-int(pad_y*0.7), x+ww+int(pad_x*0.7), ytop+wh+int(pad_y*0.7)],
                                    radius=int(rad*0.8), fill=(highlight[0],highlight[1],highlight[2],255))
                col=active_text
            elif mode=="highlight" and karaoke and active>=0 and i<=active:
                # Progressive fill: every word up to and including the current
                # one stays in the highlight colour (classic karaoke look) —
                # only words not reached yet stay in the default colour.
                col=highlight
            else:
                col=primary
            if is_rhymes_multi and not act:
                # Fallback (non-liquid path): still rotate per-word colour
                # so "Rhymes 1" keeps its rainbow identity if liquid is off.
                col = multi_palette[i % len(multi_palette)]
            d.text((x_draw, y_draw), w, font=draw_font, fill=(col[0],col[1],col[2],255),
                   stroke_width=ow, stroke_fill=(outline[0],outline[1],outline[2],255))
            x+=widths[i]+spc
        if _use_pngseq:
            img.save(os.path.join(pngdir, f"f{frame_i:06d}.png")); frame_i+=1
        else:
            if proc and proc.stdin: proc.stdin.write(img.tobytes())
    if _use_pngseq:
        # Mux the PNG sequence into a transparent .mov (png codec = universal).
        r=_run_ff(["ffmpeg","-y","-framerate",str(overlay_fps),"-i",os.path.join(pngdir,"f%06d.png"),
                   "-c:v","png","-pix_fmt","rgba","-loglevel","error",out_path], timeout=600)
        try: shutil.rmtree(pngdir, ignore_errors=True)
        except Exception: pass
    else:
        proc.stdin.close()
        try:
            err=proc.stderr.read().decode("utf-8","replace") if proc.stderr else ""
        except Exception: err=""
        proc.wait()
        if err.strip():
            print("[STORY] caption overlay ffmpeg:", err[-300:])
    ok = os.path.exists(out_path) and get_duration(out_path)>0.1
    if not ok:
        print(f"[STORY] caption overlay produced NO output ({out_path}). "
              f"qtrle_available={_ffmpeg_has_encoder('qtrle')}. Captions will be missing.")
    return out_path if ok else None

def story_apply_fx_captions(scene_video, out_path, effect, caption_text, duration, opts, fps=30, freeze_start=0.0, logo=None, canvas_w=None, canvas_h=None, progress_cb=None):
    """Composite: a selectable MOTION effect (zoom/pan/shake/rotate) on the frozen
    frame + overlay FX (only on the frozen portion) + PRO CapCut captions
    (active-word highlight box) + a STATIC logo on top. Voiceover kept fully.

    canvas_w/canvas_h: the frame size this scene is scaled+padded onto before
    any overlay. MUST match the canvas the logo's (x,y) was computed against
    (see StoryVideoEditorFrame._story_canvas_wh) — otherwise a logo positioned
    at, say, bottom-right in the preview lands somewhere else entirely once
    ffmpeg composites it here. Defaults to 1920x1080 only when the caller
    doesn't know better (e.g. the quick effect-preview path with no logo)."""
    W,H=int(canvas_w or 1920),int(canvas_h or 1080)
    scene_video=os.path.abspath(scene_video)
    out_path=os.path.abspath(out_path)
    ov=_story_get_overlay(effect, W, H, fps) if effect and effect!="None" else None
    cap_ov=None
    try:
        if opts.get("captions_on") and caption_text:
            _wt=opts.get("word_times") or []
            _wtk=(len(_wt), round(float(_wt[0]["start"]),2) if _wt else 0,
                  round(float(_wt[-1]["end"]),2) if _wt else 0)
            cap_path=os.path.join(TEMP_DIR,
                f"story_capov_{abs(hash(('v5_clean_single_pass',caption_text,round(duration,2),_wtk,opts.get('mode'),opts.get('style'),opts.get('size'),opts.get('max_words'),opts.get('primary'),opts.get('highlight'),opts.get('active_text'),opts.get('border_color'))))%999999}.mov")
            # Cache hit — skip expensive PIL frame-loop if overlay already built
            if os.path.exists(cap_path) and get_duration(cap_path) > 0.05:
                cap_ov = cap_path
            else:
                cap_ov=_story_render_caption_overlay(caption_text, duration, W, H, opts, cap_path, fps=fps, progress_cb=progress_cb)
            if cap_ov is None:
                print(f"[STORY] [WARN] cap_ov=None for '{os.path.basename(scene_video)}' -- captions will be missing.\n"
                      f"  Check: ffmpeg qtrle={_ffmpeg_has_encoder(chr(39)+'qtrle'+chr(39))}, text len={len(caption_text)}, dur={duration:.1f}s")
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
    cmd += GPU.enc_args("veryfast")
    cmd+=["-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-loglevel","error",out_path]
    try:
        r=subprocess.run(cmd, capture_output=True, text=True, timeout=900, encoding="utf-8", errors="replace", **_NO_WINDOW)
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
        subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **_NO_WINDOW)
        base=os.path.splitext(os.path.basename(audio))[0]
        for root,_dirs,files in os.walk(outdir):
            if os.path.basename(root)==base and "vocals.wav" in files and "no_vocals.wav" in files:
                return os.path.join(root,"vocals.wav"), os.path.join(root,"no_vocals.wav")
        # retry without --segment (some models ignore it)
        subprocess.run([sys.executable,"-m","demucs","--two-stems=vocals","-o",outdir,audio],
                       capture_output=True, text=True, timeout=timeout, **_NO_WINDOW)
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





# MASTER tab — simple: clips + script/TTS + volume mix + transitions + logo + BGM
# ════════════════════════════════════════════════════════════════
MASTER_TRANSITIONS = [
    "fade","fadeblack","fadewhite","wipeleft","wiperight",
    "slideup","slidedown","slideleft","slideright","circlecrop",
]

def _apply_xfade(clip_a, clip_b, out, transition="fade", xfade_dur=0.5, timeout=600):
    """Legacy 2-clip xfade — kept for callers that only have a pair. Prefers
    the GPU encoder if available for speed."""
    da=get_duration(clip_a)
    if da < xfade_dur+0.2: return None
    offset=max(0.1, da - xfade_dur)
    fc=f"[0:v][1:v]xfade=transition={transition}:duration={xfade_dur:.2f}:offset={offset:.3f}[v]"
    has_a0=has_audio_stream(clip_a); has_a1=has_audio_stream(clip_b)
    if has_a0 and has_a1:
        fc+=f";[0:a][1:a]acrossfade=d={xfade_dur:.2f}:c1=tri:c2=tri[a]"
        maps=["-map","[v]","-map","[a]"]
    else:
        maps=["-map","[v]"]
    cmd=["ffmpeg","-y","-i",clip_a,"-i",clip_b,"-filter_complex",fc]+maps
    cmd+=GPU.enc_args("fast")
    if getattr(GPU, "gpu_vendor", "") == "nvidia":
        cmd+=["-b:v","12M","-maxrate","18M","-bufsize","24M",
              "-rc","vbr","-cq","18","-spatial-aq","1","-temporal-aq","1"]
    cmd+=["-c:a","aac","-b:a","192k","-movflags","+faststart","-loglevel","error",out]
    _run_ff(cmd, timeout=timeout)
    return out if (os.path.exists(out) and get_duration(out)>0.1) else None

def _merge_with_transitions_batched(clips, tr_list, xfade_dur, out, batch_size, logf=None):
    """Batched transition merger — for jobs with too many clips to xfade in a
    single filter graph (ffmpeg's decoder pool starts throwing obscure errors
    around 25+ concurrent H.264 inputs).

    Strategy:
      1. Split the clip list into batches of `batch_size` clips each
      2. Run _merge_with_transitions on each batch (single-pass xfade within)
      3. Concat all batch outputs with a simple demuxer concat + optional
         xfade between adjacent batches (to keep the transitions smooth
         across batch boundaries)

    This keeps every filter graph small enough that the decoder can handle
    it, while still preserving crossfades within each batch."""
    import random
    batch_outs = []
    n_batches = (len(clips) + batch_size - 1) // batch_size
    for b in range(n_batches):
        start = b * batch_size
        end = min(start + batch_size, len(clips))
        batch = clips[start:end]
        if not batch: continue
        bo = os.path.join(TEMP_DIR, f"batch_{b}_{int(time.time()*1000)%99999}.mp4")
        if logf:
            try: logf(f"Batch {b+1}/{n_batches}: {len(batch)} clips → {os.path.basename(bo)}")
            except: pass
        if len(batch) == 1:
            try: shutil.copy2(batch[0], bo); batch_outs.append(bo)
            except: batch_outs.append(batch[0])
            continue
        # Single-pass xfade for this batch
        r = _merge_with_transitions(batch, tr_list, xfade_dur, bo, logf=logf)
        if r and os.path.exists(r) and get_duration(r) > 0.1:
            batch_outs.append(r)
        else:
            # Batch itself failed — fall back to concat-copy for THIS batch only
            if logf:
                try: logf(f"Batch {b+1} xfade failed — concat-copy fallback for batch")
                except: pass
            lst_b = os.path.join(TEMP_DIR, f"batch_{b}_cat.txt")
            with open(lst_b, "w") as f:
                for c in batch: f.write(f"file '{os.path.abspath(c)}'\n")
            _run_ff(["ffmpeg","-y","-f","concat","-safe","0","-i",lst_b,"-c","copy",
                     "-movflags","+faststart","-loglevel","error", bo], timeout=1800)
            if os.path.exists(bo) and get_duration(bo) > 0.1:
                batch_outs.append(bo)
            else:
                batch_outs.extend(batch)  # last resort: keep individual clips

    if not batch_outs: return None
    if len(batch_outs) == 1:
        try: shutil.copy2(batch_outs[0], out); return out
        except: return None

    # Concat all batch outputs. We try demuxer concat first (fastest, no
    # re-encode) since all batches share the same codec/resolution/fps.
    lst = os.path.join(TEMP_DIR, f"batches_cat.txt")
    with open(lst, "w") as f:
        for bo in batch_outs: f.write(f"file '{os.path.abspath(bo)}'\n")
    if logf:
        try: logf(f"Concatenating {len(batch_outs)} batches…")
        except: pass
    _run_ff(["ffmpeg","-y","-f","concat","-safe","0","-i",lst,"-c","copy",
             "-movflags","+faststart","-loglevel","error", out], timeout=3600)
    if os.path.exists(out) and get_duration(out) > 0.1:
        return out
    # Concat-copy failed → re-encode concat via filter_complex
    if logf:
        try: logf("Batch concat-copy failed — filter_complex re-encode fallback")
        except: pass
    fc_parts = []; inputs = []
    for j, bo in enumerate(batch_outs):
        inputs += ["-fflags","+genpts","-i", bo]
        fc_parts.append(f"[{j}:v:0][{j}:a:0]")
    fc = "".join(fc_parts) + f"concat=n={len(batch_outs)}:v=1:a=1[v][a]"
    cmd = ["ffmpeg","-y"] + inputs + [
        "-filter_complex", fc, "-map","[v]","-map","[a]"]
    cmd += GPU.enc_args("fast")
    if getattr(GPU, "gpu_vendor", "") == "nvidia":
        cmd += ["-b:v","12M","-maxrate","18M","-bufsize","24M",
                "-rc","vbr","-cq","18","-spatial-aq","1"]
    cmd += ["-c:a","aac","-b:a","192k","-movflags","+faststart",
            "-loglevel","error", out]
    _run_ff(cmd, timeout=3600)
    return out if (os.path.exists(out) and get_duration(out) > 0.1) else None


def _merge_with_transitions(clips, tr_list, xfade_dur, out, logf=None):
    """SINGLE-PASS chained xfade merge — massive speedup vs the old approach.

    OLD approach (O(N²) work):
      • For each pair, re-encode the entire cumulative video with libx264 CPU
      • 10 clips → 9 sequential re-encodes, each larger than the last
      • Filmora looked fast by comparison because it does exactly this next
        step: one big filter graph, one encode, hardware-accelerated.

    NEW approach (O(N) work):
      • Build a single filter_complex chaining xfade + acrossfade across ALL
        clips at once
      • Feed to ffmpeg exactly once
      • Encode with the GPU encoder (NVENC/QSV/AMF) at its fastest preset

    On a 1660 SUPER with 8-10 clips this cuts transition time from ~minutes
    down to a few seconds."""
    import random
    if not clips: return None
    if len(clips) == 1:
        try: shutil.copy2(clips[0], out); return out
        except: return None

    # Get every clip's duration up front. We need them to compute the xfade
    # timing offsets in the filter graph.
    durs = []
    valid = []
    for c in clips:
        if not (c and os.path.exists(c)): continue
        d = get_duration(c)
        if d <= 0.1: continue
        # A clip must be at least xfade_dur long to fade into the next one,
        # otherwise ffmpeg's xfade filter errors out. Skip clips that are
        # too short.
        durs.append(d); valid.append(c)
    clips = valid
    if len(clips) < 2:
        if clips:
            try: shutil.copy2(clips[0], out); return out
            except: return None
        return None

    if logf:
        try: logf(f"Single-pass transition build: {len(clips)} clips, GPU={GPU.hw_encoder}")
        except: pass

    # ── Adaptive strategy ──
    # ffmpeg's decoder + xfade filter graph is stable up to ~20 clips per
    # single pass. Beyond that, the internal H.264 decoder can throw obscure
    # errors like -1145393733 when >25 streams are open at once. So if the
    # user has many clips, we build in BATCHES of MAX_PER_PASS, xfade within
    # each batch, then concat the batch outputs.
    MAX_PER_PASS = 15
    if len(clips) > MAX_PER_PASS:
        if logf:
            try: logf(f"Too many clips for single pass ({len(clips)}) — batching by {MAX_PER_PASS}")
            except: pass
        return _merge_with_transitions_batched(clips, tr_list, xfade_dur, out, MAX_PER_PASS, logf)

    # ── Build the filter_complex ──
    fc_parts = []

    # Video chain: iteratively xfade current cumulative stream with next clip.
    # Offset for k-th xfade (0-indexed) is total_duration_so_far - xfade_dur.
    prev_v = "0:v"
    cum = durs[0]
    for i in range(1, len(clips)):
        tr = random.choice(tr_list) if tr_list else "fade"
        # xfade offset is the point in the current stream where the transition
        # BEGINS. If the current cumulative length is `cum`, we want the fade
        # to end exactly at `cum`, so it must begin at `cum - xfade_dur`.
        offset = max(0.05, cum - xfade_dur)
        out_tag = f"vx{i}"
        fc_parts.append(
            f"[{prev_v}][{i}:v]xfade=transition={tr}:duration={xfade_dur:.3f}:offset={offset:.3f}[{out_tag}]"
        )
        prev_v = out_tag
        # After this xfade, the total length grows by durs[i] - xfade_dur
        # (the overlap of length xfade_dur only counts once).
        cum += durs[i] - xfade_dur

    # Audio chain — only if every clip has an audio track. Otherwise fall back
    # to muxing the video-only chain and dropping audio; users with mixed
    # tracks would rather have video with silence than a failed render.
    audio_ok = all(has_audio_stream(c) for c in clips)
    if audio_ok:
        prev_a = "0:a"
        for i in range(1, len(clips)):
            out_tag = f"ax{i}"
            fc_parts.append(
                f"[{prev_a}][{i}:a]acrossfade=d={xfade_dur:.3f}:c1=tri:c2=tri[{out_tag}]"
            )
            prev_a = out_tag
        maps = ["-map", f"[{prev_v}]", "-map", f"[{prev_a}]"]
    else:
        maps = ["-map", f"[{prev_v}]"]

    fc = ";".join(fc_parts)

    # Build the ffmpeg command with ALL clips as inputs.
    # `-fflags +genpts` on EACH input regenerates PTS timestamps if the
    # source has any inconsistencies — this is what fixes the "-1145393733"
    # decoder error family seen with large xfade filter graphs.
    inputs = []
    for c in clips: inputs += ["-fflags", "+genpts", "-i", c]

    cmd = ["ffmpeg", "-y"] + inputs + ["-filter_complex", fc] + maps
    # Use the "fast" (not ultrafast) preset — this is the FINAL output that
    # ships to the viewer, so quality matters. On NVENC that's p4 with CQ 20
    # by default. We ALSO bump the target bitrate and set VBR-HQ so gradient
    # areas (skies, fades) don't blockify. On libx264 fallback we use CRF 18.
    cmd += GPU.enc_args("fast")
    # For NVENC specifically, override the low-bitrate default with a target
    # that keeps quality high through xfade blends (the crossfade generates
    # smooth gradients that eat bits — with CQ-only encoding, quality dips).
    if getattr(GPU, "gpu_vendor", "") == "nvidia":
        cmd += ["-b:v", "12M", "-maxrate", "18M", "-bufsize", "24M",
                "-rc", "vbr", "-cq", "18", "-spatial-aq", "1", "-temporal-aq", "1"]
    cmd += ["-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            "-loglevel", "error",
            out]

    if logf:
        try: logf(f"Encoding chained xfade → {os.path.basename(out)}…")
        except: pass
    result = _run_ff(cmd, timeout=3600)
    if result is not None and hasattr(result, "stderr") and result.stderr:
        err = str(result.stderr)[-400:]
        if err.strip(): print(f"[XFADE ffmpeg stderr] {err}")

    if os.path.exists(out) and get_duration(out) > 0.1:
        return out

    # ── Fallback #1: retry with CPU libx264 (in case the GPU encoder
    #    choked on the filter graph output). Still single-pass, high quality.
    if logf:
        try: logf("GPU single-pass failed — retry with CPU libx264 single-pass")
        except: pass
    cmd_cpu = ["ffmpeg", "-y"] + inputs + ["-filter_complex", fc] + maps
    cmd_cpu += ["-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                "-loglevel", "error", out]
    result2 = _run_ff(cmd_cpu, timeout=3600)
    if result2 is not None and hasattr(result2, "stderr") and result2.stderr:
        err = str(result2.stderr)[-400:]
        if err.strip(): print(f"[XFADE CPU stderr] {err}")

    if os.path.exists(out) and get_duration(out) > 0.1:
        return out

    # ── Fallback #2: pairwise xfade (the old slow approach) so users still
    #    get an output even if the filter graph is somehow broken.
    if logf:
        try: logf("Single-pass failed — falling back to pairwise xfade")
        except: pass
    cur = clips[0]
    for i in range(1, len(clips)):
        tr = random.choice(tr_list) if tr_list else "fade"
        tmp = os.path.join(TEMP_DIR, f"mtr_{i}_{int(time.time()*1000)%99999}.mp4")
        r = _apply_xfade(cur, clips[i], tmp, transition=tr, xfade_dur=xfade_dur)
        if r: cur = r
        else:
            lst = os.path.join(TEMP_DIR, f"mtr_cat_{i}.txt")
            with open(lst, "w") as f:
                f.write(f"file '{os.path.abspath(cur)}'\nfile '{os.path.abspath(clips[i])}'\n")
            tmp2 = os.path.join(TEMP_DIR, f"mtr_cat_{i}.mp4")
            _run_ff(["ffmpeg","-y","-f","concat","-safe","0","-i",lst,"-c","copy",
                     "-movflags","+faststart","-loglevel","error",tmp2], timeout=600)
            cur = tmp2 if os.path.exists(tmp2) else clips[i]
    if cur != out:
        try: shutil.copy2(cur, out)
        except: pass
    return out if os.path.exists(out) else None

def _overlay_multi_logos(video, logos, out):
    if not logos: return None
    inputs=["-i", video]
    fc=""; prev="0:v"
    for i, lg in enumerate(logos):
        if not os.path.exists(lg["path"]): continue
        inputs+=["-i", lg["path"]]
        sx=int(lg.get("size",0.08)*1920)
        ox=int(lg.get("x",0.02)*1920); oy=int(lg.get("y",0.02)*1080)
        op=lg.get("opacity",1.0)
        tag=f"[lg{i}]"; out_tag=f"[o{i}]"
        fc+=f"[{i+1}:v]scale={sx}:-1,format=rgba,colorchannelmixer=aa={op:.2f}{tag};"
        fc+=f"[{prev}]{tag}overlay=x={ox}:y={oy}:shortest=1{out_tag};"
        prev=out_tag.strip("[]")
    if not fc: return None
    fc=fc.rstrip(";")
    cmd=["ffmpeg","-y"]+inputs+["-filter_complex",fc,"-map",f"[{prev}]","-map","0:a?",
         "-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k",
         "-movflags","+faststart","-loglevel","error",out]
    _run_ff(cmd, timeout=3600)
    return out if (os.path.exists(out) and get_duration(out)>0.1) else None




# ════════════════════════════════════════════════════════════════
# RENDER QUEUE — set up video 1, send it to the queue, and start
# building video 2 immediately. Tasks render in a hidden clone of the
# tab, so nothing you do afterwards can disturb a job already queued.
# ════════════════════════════════════════════════════════════════
def _render_beep():
    """Long, unmistakable 'job finished' chime."""
    def work():
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
            for f, d in ((1200, 400), (1500, 400), (1800, 400), (2200, 700)):
                winsound.Beep(f, d)
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            try: print("\a", end="", flush=True)
            except Exception: pass
    threading.Thread(target=work, daemon=True).start()




class RenderTask:
    _seq = 0

    def __init__(self, src_frame, tab_class, snapshot, save_path, plan, name=None):
        RenderTask._seq += 1
        self.id = RenderTask._seq
        self.src_frame = src_frame
        self.tab_class = tab_class
        self.snapshot = snapshot
        self.save_path = save_path
        self.plan = plan
        self.name = name or f"Task {self.id} — {os.path.basename(save_path)}"
        self.status = "Queued"          # Queued | Rendering | Done | Failed | Stopped
        self.step_text = "Waiting in queue…"
        self.overall = 0.0
        self.step_frac = 0.0
        self.started_at = None
        self.elapsed = 0.0
        self.clone = None
        self.error = ""
        self.current_step_id = None

    # ── progress (called from the render worker thread) ──
    def update(self, step_id, message, sub=None, finished=False):
        self.status = "Rendering"
        self.step_text = message
        self.current_step_id = step_id
        rows = [sid for sid, _ in (self.plan.get("steps") or [])]
        frac = float(sub) if isinstance(sub, (int, float)) else (1.0 if finished else 0.35)
        frac = max(0.0, min(1.0, frac))
        self.step_frac = frac
        try:
            pos = rows.index(step_id) + 1
            self.overall = max(self.overall, ((pos - 1) + frac) / max(1, len(rows)))
        except ValueError:
            pass
        if self.started_at: self.elapsed = time.time() - self.started_at

    def finish(self, ok, save_path=None, elapsed=None):
        self.status = "Done" if ok else ("Stopped" if getattr(self.clone, "_cancelled", False) else "Failed")
        self.overall = 1.0 if ok else self.overall
        self.step_text = ("✓ Rendered — done" if ok else "✗ Did not finish")
        if elapsed: self.elapsed = elapsed
        if ok: _render_beep()
        RENDER_QUEUE.task_finished(self)

    def stop(self):
        try:
            if self.clone is not None: self.clone._cancelled = True
        except Exception: pass
        if self.status == "Queued":
            self.status = "Stopped"; self.step_text = "Removed before start"
            RENDER_QUEUE.task_finished(self)

    # ── execution (clone is built on the Tk main thread) ──
    def start(self):
        self.status = "Rendering"
        self.step_text = "Starting…"
        self.started_at = time.time()
        try:
            self.src_frame.after(0, self._spawn)
        except Exception as e:
            self.error = str(e); self.finish(False)

    def _spawn(self):
        try:
            holder = ctk.CTkFrame(self.src_frame.winfo_toplevel(), fg_color="transparent")
            clone = self.tab_class(holder)      # built, never displayed
            self.clone = clone
            clone._task = self
            clone._render_win = None
            clone._cancelled = False
            clone._apply_task_snapshot(self.snapshot)
            self._holder = holder
            threading.Thread(target=clone._master_render_worker,
                             args=(self.save_path,), daemon=True).start()
        except Exception as e:
            self.error = str(e)[:120]
            print("[QUEUE] spawn error:", e)
            self.finish(False)

    def cleanup(self):
        def _kill():
            try:
                if self.clone is not None: self.clone.destroy()
                if getattr(self, "_holder", None) is not None: self._holder.destroy()
            except Exception: pass
            self.clone = None
        try: self.src_frame.after(1500, _kill)
        except Exception: pass


class RenderQueueManager:
    def __init__(self):
        self.tasks = []
        self.mode = "one_by_one"       # one_by_one | all_at_once
        self.mode_chosen = False
        self.started = False           # True once the user presses Run All / Run One-by-one

    def add(self, task):
        self.tasks.append(task)
        # Don't auto-start: newly-added tasks wait in "Queued" until the user
        # explicitly presses ▶ Run All / ▶ Run One-by-one in the Queue tab.
        # If the queue is ALREADY running (started=True), new tasks should
        # still be picked up per the active mode without needing another click.
        if self.started:
            self._pump()

    def running(self):
        return [t for t in self.tasks if t.status == "Rendering"]

    def run_all(self):
        self.mode = "all_at_once"; self.mode_chosen = True; self.started = True
        self._pump()

    def run_one_by_one(self):
        self.mode = "one_by_one"; self.mode_chosen = True; self.started = True
        self._pump()

    def _pump(self):
        if not self.started: return
        queued = [t for t in self.tasks if t.status == "Queued"]
        if not queued: return
        if self.mode == "all_at_once":
            for t in queued: t.start()
        else:
            if not self.running():
                queued[0].start()

    def task_finished(self, task):
        try: task.cleanup()
        except Exception: pass
        self._pump()

    def clear_finished(self):
        self.tasks = [t for t in self.tasks if t.status in ("Queued", "Rendering")]
        if not self.tasks:
            self.started = False   # fresh queue → wait for Run again

    def remove(self, task):
        if task.status == "Rendering": return
        self.tasks = [t for t in self.tasks if t is not task]


RENDER_QUEUE = RenderQueueManager()


class RenderWindow(ctk.CTkToplevel):
    """Futuristic Cyberpunk / DaVinci Glassmorphic Studio HUD for Rhymes & Stories rendering."""

    def __init__(self, parent, plan, save_path, on_start, on_cancel=None):
        super().__init__(parent)
        self.parent = parent
        self.plan = plan
        self.save_path = save_path
        self.on_start = on_start
        self.on_cancel = on_cancel
        self.started = False
        self._t0 = None
        self._timer_job = None
        self.log_lines = []

        self.title("⚡ Production Render HUD — Stories Studio")
        self.configure(fg_color="#070a14")
        self.transient(parent.winfo_toplevel())

        try:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            w = min(740, max(560, int(sw * 0.48)))
            h = min(740, max(520, int(sh * 0.82)))
            self.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2)}")
        except Exception:
            self.geometry("700x700")
        self.minsize(540, 480)

        # ── 1. TOP CYBERPUNK HUD BAR ──
        head = ctk.CTkFrame(self, fg_color="#0b1020", corner_radius=0, height=72,
                            border_width=1, border_color="#18233c")
        head.pack(fill="x")
        head.pack_propagate(False)

        # Left: Neon Title + Subtitle
        hl = ctk.CTkFrame(head, fg_color="transparent")
        hl.pack(side="left", padx=18, pady=10)
        ctk.CTkLabel(hl, text="⚡ STUDIO RENDER HUD", text_color="#00f2fe",
                     font=("Segoe UI", 17, "bold")).pack(anchor="w")
        self.head_sub = ctk.CTkLabel(hl, text="System Manifest Ready • Select Hardware Engine",
                                     text_color="#94a3b8", font=("Segoe UI", 10))
        self.head_sub.pack(anchor="w")

        # Right: Hardware Engine Selector + Stopwatch
        hr = ctk.CTkFrame(head, fg_color="transparent")
        hr.pack(side="right", padx=18, pady=10)

        cur_mode = GPU.get_mode().lower()
        mode_label = "⚡ Auto (Hybrid)" if cur_mode == "auto" else ("🚀 GPU NVENC" if cur_mode == "gpu" else "🛡️ CPU Safe")
        self.engine_var = ctk.StringVar(value=mode_label)

        def _on_engine_change(choice):
            if "gpu" in choice.lower():
                GPU.set_mode("gpu")
            elif "cpu" in choice.lower():
                GPU.set_mode("cpu")
            else:
                GPU.set_mode("auto")
            try:
                self.engine_badge.configure(text=GPU.info_str()[:32])
            except Exception:
                pass

        self.engine_menu = ctk.CTkOptionMenu(
            hr, variable=self.engine_var,
            values=["⚡ Auto (Hybrid)", "🚀 Force GPU (Hardware)", "🛡️ Force CPU (Safe libx264)"],
            command=_on_engine_change, width=170, height=28,
            fg_color="#141d33", button_color="#1f2c4d", button_hover_color="#00f2fe",
            text_color="#00f2fe", font=("Segoe UI", 10, "bold")
        )
        self.engine_menu.pack(anchor="e", pady=(0, 2))

        self.timer_lbl = ctk.CTkLabel(hr, text="⏱ 00:00", text_color="#10b981",
                                      font=("Consolas", 12, "bold"))
        self.timer_lbl.pack(anchor="e")

        # ── 2. PINNED FOOTER ACTION CONTROLS ──
        foot = ctk.CTkFrame(self, fg_color="#0b1020", corner_radius=0, height=62,
                            border_width=1, border_color="#18233c")
        foot.pack(side="bottom", fill="x")
        foot.pack_propagate(False)

        foot_inner = ctk.CTkFrame(foot, fg_color="transparent")
        foot_inner.pack(fill="both", expand=True, padx=16, pady=10)

        self.cancel_btn = ctk.CTkButton(foot_inner, text="✕  Cancel", width=110, height=38,
                                        fg_color="#161f36", hover_color="#243254", text_color="#94a3b8",
                                        font=("Segoe UI", 11, "bold"), command=self._cancel)
        self.cancel_btn.pack(side="left")

        self.start_btn = ctk.CTkButton(foot_inner, text="🚀  LAUNCH PRODUCTION RENDER", height=38,
                                       fg_color="#10b981", hover_color="#059669", text_color="#000",
                                       font=("Segoe UI", 12, "bold"), command=self._start)
        self.start_btn.pack(side="right", fill="x", expand=True, padx=(10, 0))

        # ── 3. SCROLLABLE BODY ──
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=16, pady=(10, 6))

        self._build_review()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.after(60, lambda: (self.lift(), self.focus_force(), self.grab_set()))

    # ───────────────────────── PHASE 1 : MANIFEST REVIEW ─────────────────────────
    def _build_review(self):
        lbl_bar = ctk.CTkFrame(self.body, fg_color="transparent")
        lbl_bar.pack(fill="x", pady=(2, 8))
        ctk.CTkLabel(lbl_bar, text="SYSTEM MANIFEST & ASSET MATRIX", text_color="#00f2fe",
                     font=("Segoe UI", 11, "bold")).pack(side="left")

        self.engine_badge = ctk.CTkLabel(lbl_bar, text=GPU.info_str()[:38],
                                         text_color="#10b981", font=("Consolas", 10, "bold"))
        self.engine_badge.pack(side="right")

        _summary = self.plan.get("summary") or []
        if isinstance(_summary, str):
            _summary = [("📋", "Summary", _summary, True)]

        for item in _summary:
            icon, name, value = item[0], item[1], item[2]
            card = ctk.CTkFrame(self.body, fg_color="#0e1528", corner_radius=8,
                                border_width=1, border_color="#1c2742")
            card.pack(fill="x", pady=3)

            ctk.CTkLabel(card, text=icon, font=("Segoe UI", 16), width=36).pack(side="left", padx=(10, 2), pady=8)
            ctk.CTkLabel(card, text=name, text_color="#e2e8f0", font=("Segoe UI", 12, "bold"),
                         anchor="w", width=150).pack(side="left")
            ctk.CTkLabel(card, text=value, text_color="#38bdf8", font=("Consolas", 11),
                         anchor="e").pack(side="right", padx=14)

        op = ctk.CTkFrame(self.body, fg_color="#0c1829", border_color="#10b981",
                          border_width=1, corner_radius=8)
        op.pack(fill="x", pady=(10, 4))
        op_top = ctk.CTkFrame(op, fg_color="transparent")
        op_top.pack(fill="x", padx=12, pady=(8, 2))
        ctk.CTkLabel(op_top, text="💾  TARGET EXPORT DESTINATION", text_color="#10b981",
                     font=("Segoe UI", 11, "bold")).pack(side="left")

        self.path_lbl = ctk.CTkLabel(op, text=self.save_path, text_color="#94a3b8",
                                     font=("Consolas", 9), anchor="w", wraplength=560, justify="left")
        self.path_lbl.pack(anchor="w", padx=12, pady=(2, 6))

        ctk.CTkButton(op, text="📁  Change Destination…", height=26, width=150,
                      fg_color="#152438", hover_color="#1e3a5f", text_color="#00f2fe",
                      font=("Segoe UI", 10, "bold"), command=self._change_path).pack(anchor="w", padx=12, pady=(0, 8))

    def _change_path(self):
        p = _asksaveasfilename_safe(parent=self, defaultextension=".mp4", filetypes=[("MP4", "*.mp4")],
                                    initialfile=os.path.basename(self.save_path or "render.mp4"))
        if p:
            self.save_path = p
            self.path_lbl.configure(text=p)

    # ───────────────────────── PHASE 2 : LIVE TELEMETRY HUD ─────────────────────────
    def _start(self):
        if self.started: return
        self.started = True
        for w in self.body.winfo_children(): w.destroy()

        self.start_btn.configure(text="⏹  ABORT RENDER", fg_color="#ef4444", hover_color="#dc2626",
                                 text_color="#fff", command=self._stop)
        self.cancel_btn.configure(state="disabled")
        self.head_sub.configure(text="⚡ Pipeline Engine Active • Realtime Stream Running", text_color="#10b981")

        ov = ctk.CTkFrame(self.body, fg_color="#0d1424", corner_radius=10,
                          border_width=1, border_color="#1e293b")
        ov.pack(fill="x", pady=(2, 8))

        top = ctk.CTkFrame(ov, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(10, 2))
        ctk.CTkLabel(top, text="MASTER RENDERING PIPELINE", text_color="#00f2fe",
                     font=("Segoe UI", 11, "bold")).pack(side="left")

        self.overall_pct = ctk.CTkLabel(top, text="0%", text_color="#10b981",
                                        font=("Consolas", 15, "bold"))
        self.overall_pct.pack(side="right")

        self.overall_bar = ctk.CTkProgressBar(ov, height=12, progress_color="#10b981", fg_color="#152033")
        self.overall_bar.pack(fill="x", padx=14, pady=(4, 6))
        self.overall_bar.set(0)

        self.stage_lbl = ctk.CTkLabel(ov, text="⚡ Initiating synthesis & pipeline...", text_color="#f59e0b",
                                      font=("Segoe UI", 11, "bold"), anchor="w")
        self.stage_lbl.pack(fill="x", padx=14, pady=(2, 2))

        self.step_bar = ctk.CTkProgressBar(ov, height=5, progress_color="#00f2fe", fg_color="#152033")
        self.step_bar.pack(fill="x", padx=14, pady=(2, 10))
        self.step_bar.set(0)

        ctk.CTkLabel(self.body, text="STAGE TELEMETRY MATRIX", text_color="#94a3b8",
                     font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(6, 4))
        self.rows = {}
        for i, (sid, label) in enumerate(self.plan["steps"], 1):
            row = ctk.CTkFrame(self.body, fg_color="#0a101d", corner_radius=6,
                               border_width=1, border_color="#162238")
            row.pack(fill="x", pady=2)

            dot = ctk.CTkLabel(row, text="○", width=26, text_color="#64748b", font=("Segoe UI", 13, "bold"))
            dot.pack(side="left", padx=(8, 2), pady=6)

            txt = ctk.CTkLabel(row, text=f"{i}. {label}", text_color="#94a3b8",
                               font=("Segoe UI", 11), anchor="w")
            txt.pack(side="left", fill="x", expand=True)

            sub = ctk.CTkLabel(row, text="pending", text_color="#64748b", font=("Consolas", 9), anchor="e")
            sub.pack(side="right", padx=12)

            self.rows[sid] = {"frame": row, "dot": dot, "txt": txt, "sub": sub, "label": label, "pos": i}

        # Live log box
        log_head = ctk.CTkFrame(self.body, fg_color="transparent")
        log_head.pack(fill="x", pady=(6, 2))
        ctk.CTkLabel(log_head, text="📟 ENGINE ACTIVITY LOG", text_color="#94a3b8",
                     font=("Segoe UI", 10, "bold")).pack(side="left")

        self.log_box = ctk.CTkTextbox(self.body, height=90, fg_color="#050811",
                                      text_color="#38bdf8", border_width=1, border_color="#162238",
                                      font=("Consolas", 9), wrap="word")
        self.log_box.pack(fill="x", pady=(0, 6))
        self.log_box.insert("end", "[HUD] Engine online. Dispatching workers...\n")
        self.log_box.configure(state="disabled")

        self._t0 = time.time()
        self._tick()
        try:
            self.on_start(self.save_path)
        except Exception as e:
            import traceback as _tb
            _tb.print_exc()
            try:
                self.stage_lbl.configure(text=f"Start failed: {e}", text_color="#ef4444")
            except Exception:
                pass

    def _tick(self):
        if not self.started or self._t0 is None: return
        el = int(time.time() - self._t0)
        try:
            self.timer_lbl.configure(text=f"⏱ {el//60:02d}:{el%60:02d}", text_color="#10b981")
        except Exception: return
        self._timer_job = self.after(1000, self._tick)

    def set_step(self, step_id, message, sub=None, finished=False):
        try:
            if not self.winfo_exists(): return
        except Exception: return
        if not self.started: return
        rows = getattr(self, "rows", {})
        try:
            cur = rows.get(step_id)
            pos = cur["pos"] if cur else None
            for sid, w in rows.items():
                p = w["pos"]
                if pos is None: continue
                if p < pos:
                    w["frame"].configure(border_color="#10b981", fg_color="#07121b")
                    w["dot"].configure(text="✓", text_color="#10b981")
                    w["txt"].configure(text_color="#f1f5f9")
                    if not w["sub"].cget("text") or w["sub"].cget("text") == "pending":
                        w["sub"].configure(text="COMPLETED ✓", text_color="#10b981")
                elif p == pos:
                    if finished:
                        w["frame"].configure(border_color="#10b981", fg_color="#07121b")
                        w["dot"].configure(text="✓", text_color="#10b981")
                        w["txt"].configure(text_color="#f1f5f9")
                        w["sub"].configure(text="COMPLETED ✓", text_color="#10b981")
                    else:
                        w["frame"].configure(border_color="#00f2fe", fg_color="#0c182d")
                        w["dot"].configure(text="⚡", text_color="#00f2fe")
                        w["txt"].configure(text_color="#00f2fe")
                        sub_txt = f"{int(sub*100)}%" if isinstance(sub, (int, float)) else "RUNNING…"
                        w["sub"].configure(text=sub_txt, text_color="#00f2fe")
                else:
                    w["frame"].configure(border_color="#162238", fg_color="#0a101d")
                    w["dot"].configure(text="○", text_color="#64748b")
                    w["txt"].configure(text_color="#64748b")
                    w["sub"].configure(text="pending", text_color="#475569")

            self.stage_lbl.configure(text=message, text_color="#10b981" if finished else "#00f2fe")

            frac = float(sub) if isinstance(sub, (int, float)) else (1.0 if finished else 0.4)
            frac = max(0.0, min(1.0, frac))
            self.step_bar.set(frac)

            if pos is not None:
                n = max(1, len(rows))
                overall = ((pos - 1) + frac) / n
                self.overall_bar.set(overall)
                self.overall_pct.configure(text=f"{int(overall*100)}%")

            if hasattr(self, "log_box") and message:
                try:
                    self.log_box.configure(state="normal")
                    self.log_box.insert("end", f"[{time.strftime('%H:%M:%S')}] {message}\n")
                    self.log_box.see("end")
                    self.log_box.configure(state="disabled")
                except Exception:
                    pass
        except Exception:
            pass

    def finish(self, ok=True):
        try:
            if self._timer_job: self.after_cancel(self._timer_job)
        except Exception: pass
        try:
            self.overall_bar.set(1.0)
            self.overall_pct.configure(text="100%" if ok else "ABORTED")
            self.stage_lbl.configure(text="✨ RENDER COMPLETED SUCCESSFULLY ✓" if ok else "Render Aborted / Failed",
                                     text_color="#10b981" if ok else "#ef4444")
            self.start_btn.configure(text="✕  Close HUD", fg_color="#162238", hover_color="#223354",
                                     text_color="#fff", command=self._close)
            self.cancel_btn.configure(state="normal", text="✕  Close", command=self._close)
            if ok:
                try:
                    import auth_manager
                    auth_manager.record_video_export(tool_name="Rhymes Editor")
                except Exception:
                    pass
        except Exception:
            pass

    def _stop(self):
        try: self.parent._cancelled = True
        except Exception: pass
        try: kill_all_active_procs()
        except Exception: pass
        try:
            self.finish(ok=False)
            self.stage_lbl.configure(text="Render aborted by user.", text_color="#ef4444")
        except Exception:
            pass

    def _close(self):
        try: self.grab_release()
        except Exception: pass
        try:
            if getattr(self.parent, "_render_win", None) is self: self.parent._render_win = None
        except Exception: pass
        self.destroy()

    def _cancel(self):
        if self.started:
            self._stop(); return
        if self.on_cancel:
            try: self.on_cancel()
            except Exception: pass
        self._close()


class _NullWidget:
    """Zero-cost stand-in for a Tk widget. Master/Stories' compact block row
    doesn't display a thumbnail/file/trim label anymore, but a lot of shared
    code (inherited from AdvanceEditorFrame) still calls
    block["thumb_label"].configure(...) etc. This makes those calls safe
    no-ops without ever creating a real widget — the actual perf win."""
    def configure(self, *a, **kw): pass
    def cget(self, *a, **kw): return ""
    def winfo_exists(self): return False


class MasterEditorFrame(AdvanceEditorFrame):
    """MASTER tab — clean and simple:
    Upload clips (Scene_1_, Scene_2_…) + write script per scene → TTS voiceover.
    Two volume sliders (Script audio / Clip audio) control the mix.
    Random transitions, logo, background music. No extra clutter."""

    def __init__(self, master):
        super().__init__(master)
        self._master_logos = []
        try:
            self.mode_var.set("video"); self._toggle_mode()
        except: pass
        # Hide base Logo/BGM sections (Master has its own)
        # REMOVED — keeping base sections because they have Preview/Position features
        self._add_master_sections()
        # Replace the base's "Gen Audio + Generate All + Merge Final" buttons
        # with a single professional "🎬 RENDER" button + a nice step-by-step
        # progress card at the top of the block list.
        try:
            self._install_master_render_ui()
        except Exception as e:
            print("[MASTER UI] ", e)

    # ────────────────────────────────────────────────────────────────
    # PERFORMANCE: lightweight per-scene row.
    # The base AdvanceEditorFrame._make_block() builds ~20 real CTk widgets
    # per scene (thumbnail, file/trim labels, two sliders+labels, 5 buttons).
    # Every CTk widget draws itself on a canvas for rounded corners, so at
    # scene counts like 500-1000+ the sheer widget count is what makes normal
    # clicks/typing feel laggy — Tk's event queue is doing many times more
    # work than it needs to per repaint. Master/Stories don't need per-scene
    # thumbnails or always-visible sliders, so this builds a compact 1-row
    # block (~6 widgets) and moves Upload/Trim/Audio/Volume into a small
    # on-demand "⋯" popup — same handlers as before (_uvb/_otl/_ct/
    # _gen_audio_single/_gs), just not permanently mounted on screen.
    # ────────────────────────────────────────────────────────────────
    def _make_block(self, num, char, text, video_only=False):
        ci = self.characters.get(char, {})
        cc = CHAR_COLORS[ci.get("color_idx", 0) % len(CHAR_COLORS)]
        if video_only:
            cc = {"bg": "#1a1a2e", "border": C["dim"], "accent": C["dim"]}

        frame = ctk.CTkFrame(self.bkf, fg_color=cc["bg"], border_color=cc["border"],
                             border_width=1, corner_radius=6, height=38)
        frame.pack(fill="x", padx=4, pady=1)
        frame.pack_propagate(False)

        block = {
            "num": num, "text": text, "character": char, "color_idx": ci.get("color_idx", 0),
            "source_media": "", "media_type": "", "video": "",
            "output": "", "tts_audio": "", "frame": frame,
            "trim_start": None, "trim_end": None, "trimmed_loop_path": None, "loop_mode": "pingpong",
            "video_only": video_only, "clip_volume": 0, "tts_volume": 100,
            "thumb_label": _NullWidget(), "file_label": _NullWidget(), "trim_label": _NullWidget(),
        }

        ctk.CTkLabel(frame, text=f"#{num}", text_color=C["text"], font=("Segoe UI", 11, "bold"),
                    width=42).pack(side="left", padx=(6, 2))
        badge_text = (char[:14] if not video_only else "VIDEO")
        ctk.CTkLabel(frame, text=badge_text, text_color=cc["accent"], font=("Segoe UI", 9, "bold"),
                    width=78).pack(side="left", padx=2)

        d = (text[:60] + "…") if len(text) > 60 else (text or "[no script]")
        txt_lbl = ctk.CTkLabel(frame, text=d, text_color=C["text"], font=("Segoe UI", 9),
                              anchor="w", justify="left")
        txt_lbl.pack(side="left", fill="x", expand=True, padx=4)
        block["txt_lbl"] = txt_lbl

        st = ctk.CTkLabel(frame, text=("No video" if video_only else "Pending"),
                          text_color=(C["dim"] if video_only else C["orange"]),
                          font=("Segoe UI", 9), width=90)
        st.pack(side="right", padx=(2, 6))
        block["status_label"] = st

        idx = len(self.blocks)
        ctk.CTkButton(frame, text="✕", width=24, height=24, fg_color=C["btn"], hover_color=C["red"],
                     text_color=C["red"], font=("Segoe UI", 12, "bold"),
                     command=lambda n=num: self._delete_block(n)).pack(side="right", padx=2)
        ctk.CTkButton(frame, text="⋯", width=28, height=24, fg_color=C["btn"], text_color=C["text"],
                     font=("Segoe UI", 11, "bold"),
                     command=lambda i=idx: self._block_more_menu(i)).pack(side="right", padx=2)

        def _dbl(_e=None, i=idx): self._preview_block(i)
        frame.bind("<Double-Button-1>", _dbl)
        txt_lbl.bind("<Double-Button-1>", _dbl)

        self.blocks.append(block)

    def _block_more_menu(self, idx):
        """Small on-demand popup with the actions that used to be permanent
        buttons on every scene row: Upload / Trim & Loop / Clear Trim /
        Volume sliders / Audio / Gen / Preview. Built fresh each time it's
        opened (a handful of widgets, not thousands sitting idle)."""
        if idx < 0 or idx >= len(self.blocks): return
        b = self.blocks[idx]
        win = _BASIC_VM_TOPLEVEL(self) if "_BASIC_VM_TOPLEVEL" in globals() else ctk.CTkToplevel(self)
        win.title(f"Scene #{b['num']}")
        win.geometry("300x330")
        win.resizable(False, False)
        win.transient(self.winfo_toplevel())
        try: win.configure(fg_color=C["bg"])
        except Exception:
            try: win.configure(bg=C["bg"])
            except Exception: pass

        ctk.CTkLabel(win, text=f"Scene #{b['num']} — {b.get('character','')}",
                    text_color=C["text"], font=("Segoe UI", 12, "bold")).pack(pady=(10, 6), padx=10, anchor="w")

        def _close(): 
            try: win.destroy()
            except Exception: pass

        ctk.CTkButton(win, text="📁 Upload Video", height=30, fg_color=C["accent"], text_color="#000",
                     command=lambda: (self._uvb(idx), _close())).pack(fill="x", padx=10, pady=3)
        ctk.CTkButton(win, text="✂ Trim & Loop", height=30, fg_color=C["orange"], text_color="#000",
                     command=lambda: (self._otl(idx), _close())).pack(fill="x", padx=10, pady=3)
        ctk.CTkButton(win, text="Clear Trim", height=30, fg_color=C["btn"], text_color=C["dim"],
                     command=lambda: (self._ct(idx), _close())).pack(fill="x", padx=10, pady=3)
        ctk.CTkButton(win, text="▶ Preview", height=30, fg_color=C["purple"], text_color="#fff",
                     command=lambda: (self._preview_block(idx), _close())).pack(fill="x", padx=10, pady=3)
        if not b.get("video_only") and hasattr(self, "_gen_audio_single"):
            ctk.CTkButton(win, text="🔊 Gen Audio", height=30, fg_color=C["orange"], text_color="#000",
                         command=lambda: (self._gen_audio_single(idx), _close())).pack(fill="x", padx=10, pady=3)
        ctk.CTkButton(win, text="⚙ Gen This Scene", height=30, fg_color=C["green"], text_color="#000",
                     command=lambda: (self._gs(idx), _close())).pack(fill="x", padx=10, pady=3)

        volf = ctk.CTkFrame(win, fg_color="transparent"); volf.pack(fill="x", padx=10, pady=(8, 2))
        ctk.CTkLabel(volf, text=f"Clip Vol: {b.get('clip_volume',0)}%", text_color=C["dim"],
                    font=("Segoe UI", 9)).pack(anchor="w")
        vol_var = ctk.IntVar(value=int(b.get("clip_volume", 0)))
        def _set_vol(v, _b=b): _b["clip_volume"] = int(float(v))
        ctk.CTkSlider(volf, from_=0, to=100, variable=vol_var, command=_set_vol).pack(fill="x")

        ttsf = ctk.CTkFrame(win, fg_color="transparent"); ttsf.pack(fill="x", padx=10, pady=(6, 2))
        ctk.CTkLabel(ttsf, text=f"TTS Vol: {b.get('tts_volume',100)}%", text_color=C["dim"],
                    font=("Segoe UI", 9)).pack(anchor="w")
        tts_var = ctk.IntVar(value=int(b.get("tts_volume", 100)))
        def _set_tts(v, _b=b): _b["tts_volume"] = int(float(v))
        ctk.CTkSlider(ttsf, from_=0, to=100, variable=tts_var, command=_set_tts).pack(fill="x")

        ctk.CTkButton(win, text="Close", height=28, fg_color="transparent", hover_color=C["card"],
                     text_color=C["dim"], command=_close).pack(fill="x", padx=10, pady=(10, 8))

    def _extract_media_info(self, path):
        """Compact rows don't show a thumbnail, so skip the ffmpeg frame-grab
        (smart_thumb) entirely and only fetch duration — this alone roughly
        halves the per-clip background-loader cost during bulk upload."""
        try:
            dur = get_duration(path)
        except Exception:
            dur = 0.0
        return (None, dur)

    def _clean_all(self):
        """Chunked, thumbnail-free clean — the base version re-extracts a
        thumbnail per scene synchronously on the UI thread (a multi-second+
        freeze at hundreds of scenes). Compact rows have no thumbnail to
        refresh, so this just resets state, a few hundred scenes per
        after()-tick so the UI stays responsive throughout."""
        cnt = clean_temp_files(); TTSCache.clear_all()
        total = len(self.blocks)
        self._ss(f"Cleaning {total} scene(s)…", C["orange"])

        def _step(i=0, chunk=150):
            end = min(i + chunk, total)
            for b in self.blocks[i:end]:
                b["output"] = ""; b["tts_audio"] = ""; b["trimmed_loop_path"] = None
                b["trim_start"] = b["trim_end"] = None
                try:
                    if b.get("video_only"):
                        ok = bool(b.get("source_media") and os.path.exists(b.get("source_media", "")))
                        b["status_label"].configure(text=("Video loaded" if ok else "No video"),
                                                    text_color=(C["dim"] if ok else C["orange"]))
                    else:
                        b["status_label"].configure(text="Pending", text_color=C["orange"])
                except Exception:
                    pass
            if end < total:
                self._ss(f"Cleaning… {end}/{total}", C["orange"])
                self.after(1, lambda e=end: _step(e, chunk))
                return
            self._caption_groups.clear()
            try: self.cap_status_lbl.configure(text="OFF", text_color=C["dim"])
            except Exception: pass
            try: self.progress.set(0)
            except Exception: pass
            self._ss(f"✓ Cleaned {cnt} files + cache. {total} scene(s) reset.", C["green"])

        _step()

    def _create_blocks_from_videos(self, paths):
        """Chunked bulk upload — the base version builds every block in one
        synchronous loop, which itself becomes a freeze once you're dropping
        in hundreds of clips at once."""
        if not paths: return
        def sort_key(p):
            n = extract_scene_number(p)
            return n if n else 9999
        paths = sorted(paths, key=sort_key)
        total = len(paths)
        self._ss(f"Adding {total} scene(s)…", C["orange"])

        def _step(i=0, chunk=50):
            end = min(i + chunk, total)
            for p in paths[i:end]:
                sn = extract_scene_number(p)
                num = sn if sn else len(self.blocks) + 1
                if any(b["num"] == num for b in self.blocks):
                    continue
                char = f"Scene_{num}"
                if char not in self.characters:
                    self.characters[char] = {"voice_name": "", "voice_id": "",
                                             "color_idx": num % len(CHAR_COLORS), "is_scene": True}
                self._make_block(num, char, "", video_only=False)
                b = self.blocks[-1]
                b["source_media"] = p; b["media_type"] = "video"; b["video"] = p
                self._queue_media_load(b, p, status_prefix="Video")
            if end < total:
                self._ss(f"Adding scenes… {end}/{total}", C["orange"])
                self.after(1, lambda e=end: _step(e, chunk))
                return
            self._update_filter()
            if self.voice_list_full:
                self._auto_assign_voices()
            try:
                self.vm_status.configure(text=f"{total} videos → {len(self.blocks)} blocks", text_color=C["green"])
            except Exception:
                pass
            self._ss(f"✓ Added {total} scene(s) — durations loading in background…", C["green"])

        _step()

    def _install_master_render_ui(self):
        """Rebuild the top button row (single 🎬 RENDER button) and install a
        step-by-step progress card at the top of the block area."""
        ar = getattr(self, "_action_row_ref", None)
        if ar is None: return
        # Wipe the existing base buttons
        for w in list(ar.winfo_children()):
            try: w.destroy()
            except Exception: pass
        # Build the new, single-button row
        self._render_btn = ctk.CTkButton(
            ar, text="🎬 RENDER", fg_color=C["green"], text_color="#000",
            width=170, height=38, font=("Segoe UI",14,"bold"),
            command=self._render_all_master)
        self._render_btn.pack(side="left", padx=3)
        self._stop_btn = ctk.CTkButton(
            ar, text="⏹ Stop", fg_color=C["red"], text_color="#fff",
            width=80, height=38, command=self._stop_gen)
        self._stop_btn.pack(side="left", padx=3)
        ctk.CTkButton(ar, text="🗑 Clean", fg_color=C["btn"], text_color=C["dim"],
                      width=80, height=38, command=self._clean_all).pack(side="left", padx=3)
        ctk.CTkButton(ar, text="✕ Del All", fg_color=C["btn"], text_color=C["red"],
                      width=80, height=38, font=("Segoe UI",10,"bold"),
                      command=self._delete_all_blocks).pack(side="left", padx=3)
        self.stl = ctk.CTkLabel(ar, text="Ready", text_color=C["dim"],
                                font=("Segoe UI",11), anchor="w")
        self.stl.pack(side="left", padx=10, fill="x", expand=True)

        # The old inline step card is gone — the render pipeline now lives in a
        # dedicated modal window (RenderWindow), opened on 🎬 RENDER.
        self._render_step_widgets = []
        self._render_win = None
        self._render_last_paint = 0.0

    def _render_step(self, step_num, message, sub=None, finished=False):
        """Drive the render window's step tracker. Safe to call from worker
        threads. Updates are throttled to ~12/s so a fast pipeline can't flood
        the Tk event loop (that flooding is what made the UI feel hung)."""
        win  = getattr(self, "_render_win", None)
        task = getattr(self, "_task", None)
        if win is None and task is None: return
        key = (step_num, message, None if sub is None else round(float(sub), 2), bool(finished))
        now = time.time()
        if key == getattr(self, "_render_last_key", None) and (now - getattr(self, "_render_last_paint", 0)) < 0.35:
            return
        if (now - getattr(self, "_render_last_paint", 0)) < 0.08 and not finished and key[2] not in (None, 1.0):
            return
        self._render_last_key = key
        self._render_last_paint = now
        if task is not None:
            try: task.update(step_num, message, sub, finished)
            except Exception: pass
        if win is not None:
            _sn, _msg, _sub, _fin = step_num, message, sub, finished
            try:
                win.after(0, lambda: win.set_step(_sn, _msg, _sub, _fin))
            except Exception:
                try: self.after(0, lambda: win.set_step(_sn, _msg, _sub, _fin))
                except Exception: pass

    # ────────────────────────────────────────────────────────────────────
    # Which pipeline steps actually apply to THIS render?
    # Only what the user configured is shown — nothing else.
    # ────────────────────────────────────────────────────────────────────
    def _render_plan(self):
        blocks = self.blocks
        scripted = sum(1 for b in blocks if (b.get("text") or "").strip() and not b.get("auto_captioned"))
        autocap  = sum(1 for b in blocks if b.get("auto_captioned"))
        clips    = sum(1 for b in blocks if (b.get("source_media") or "") and os.path.exists(b.get("source_media","")))

        # logos
        n_logos = 0
        try:
            if (self.logo_path_var.get() or "").strip() and os.path.exists(self.logo_path_var.get()): n_logos += 1
        except Exception: pass
        n_logos += len([lg for lg in (getattr(self, "_master_logos", None) or []) if lg.get("path")])
        n_logos += len([lg for lg in (getattr(self, "_extra_logos", None) or []) if lg.get("path")])

        # bgm
        bgm = ""
        try:
            v = self.bgm_var.get()
            if v and os.path.exists(v): bgm = v
        except Exception: pass

        # transitions
        tr_on = False; tr_dur = 0.5
        try:
            tr_on = bool(self._m_tr_on.get()); tr_dur = float(self._m_tr_dur.get())
        except Exception: pass

        # pro captions (Stories tab)
        cap_on = False; cap_style = ""
        try:
            cap_on = bool(self._story_cap_on.get())
            cap_style = f"{self._story_cap_style.get()} / {self._story_cap_mode.get()}"
        except Exception: pass

        # freeze-frame motion / FX (Stories tab)
        fx = ""; motion = ""
        try:
            fx = self._story_fx_var.get()
            if fx == "None": fx = ""
        except Exception: pass
        try:
            motion = self._story_motion_var.get()
            if motion == "None": motion = ""
        except Exception: pass

        summary = [("🎞", "Video clips",   f"{clips} scene(s)", True)]
        if scripted: summary.append(("🎙", "Voiceover (TTS)", f"{scripted} scripted scene(s)", True))
        if autocap:  summary.append(("🎤", "Clip audio kept", f"{autocap} auto-captioned scene(s)", True))
        if cap_on:   summary.append(("🅰", "Captions",       cap_style or "on", True))
        if fx or motion:
            summary.append(("✨", "Freeze-frame", " + ".join([x for x in (fx, motion) if x]), True))
        if tr_on:    summary.append(("🔀", "Transitions",    f"on • {tr_dur:g}s", True))
        if n_logos:  summary.append(("🖼", "Logos",          f"{n_logos} logo(s)", True))
        if bgm:      summary.append(("🎵", "Background music", os.path.basename(bgm), True))

        steps = [(1, "Preflight checks")]
        if scripted: steps.append((2, "Generate voiceovers"))
        steps.append((3, "Render scenes" + (" + captions" if cap_on else "")))
        steps.append((4, "Normalize clips"))
        steps.append((5, "Concat + transitions" if tr_on else "Concat clips"))
        if bgm:     steps.append((6, "Mix background music"))
        steps.append((7, "Finalize output"))
        if n_logos: steps.append((8, "Overlay logos"))
        steps.append((9, "Done"))
        return {"summary": summary, "steps": steps,
                "scripted": scripted, "clips": clips, "captions": cap_on}

    def _render_all_master(self):
        """🎬 RENDER → preflight → ASK SAVE PATH FIRST → review popup → run."""
        if not self.blocks:
            messagebox.showwarning("Blocks", "No scenes."); return
        if getattr(self, "_render_win", None) is not None:
            try: self._render_win.lift(); return
            except Exception: self._render_win = None

        # ── Preflight (before anything else, so the user isn't surprised later) ──
        missing = sum(1 for b in self.blocks
                      if not (b.get("source_media") and os.path.exists(b["source_media"])))
        if missing and not messagebox.askyesno(
                "Missing media", f"⚠️ {missing} scene(s) have no clip attached.\n\nContinue anyway?"):
            return
        need_voice = False
        for b in self.blocks:
            if not (b.get("text") or "").strip(): continue
            if b.get("auto_captioned"): continue      # uses the clip's own audio
            ci = self.characters.get(b.get("character", ""), {})
            vid = ci.get("voice_id", "") or (self.common_voice_id.get() if hasattr(self, "common_voice_id") else "")
            if not vid: need_voice = True; break
        if need_voice:
            messagebox.showwarning("Voice",
                "One or more scripted scenes have no voice assigned.\n"
                "Set a Common Voice (API section → 🔍 Set), then Render again.")
            return

        # ── SAVE PATH FIRST — chosen before any work starts ──
        sp = _asksaveasfilename_safe(parent=self, 
            defaultextension=".mp4", filetypes=[("MP4", "*.mp4")],
            initialdir=OUTPUT_DIR if os.path.isdir(OUTPUT_DIR) else None,
            initialfile=f"render_{time.strftime('%Y%m%d_%H%M%S')}.mp4",
            title="Where should the finished video be saved?")
        if not sp:
            self._ss("Render cancelled — no save location chosen.", C["dim"]); return

        # ── Review + progress window ──
        plan = self._render_plan()
        self._render_win = RenderWindow(
            self, plan, sp,
            on_start=self._begin_master_render,
            on_cancel=lambda: setattr(self, "_render_win", None))

    # ────────────────────────────────────────────────────────────────────
    # QUEUE SUPPORT — snapshot the whole setup so the job can render later
    # in a hidden clone of this tab, while you build the next video here.
    # ────────────────────────────────────────────────────────────────────
    _SNAP_BLOCK_KEYS = ("num","character","text","source_media","media_type","video",
                        "trim_start","trim_end","trimmed_loop_path","loop_mode",
                        "clip_volume","tts_volume","video_only",
                        "auto_captioned","whisper_segments","caption_text")

    def _snapshot_render_task(self):
        import copy as _copy
        blocks = []
        for b in self.blocks:
            bd = {k: _copy.deepcopy(b.get(k)) for k in self._SNAP_BLOCK_KEYS}
            blocks.append(bd)
        snap = {
            "settings": self._collect_master_settings(),
            "api_key":  (self.api_entry.get().strip() if hasattr(self, "api_entry") else ""),
            "model":    (self.model_var.get() if hasattr(self, "model_var") else ""),
            "common_voice_id":   (self.common_voice_id.get() if hasattr(self, "common_voice_id") else ""),
            "common_voice_name": (self.common_voice_name.get() if hasattr(self, "common_voice_name") else ""),
            "characters": _copy.deepcopy(self.characters),
            "voices": list(getattr(self, "voices", []) or []),
            "voice_list_full": list(getattr(self, "voice_list_full", []) or []),
            "blocks": blocks,
        }
        return snap

    def _apply_task_snapshot(self, snap):
        """Rebuild this (hidden) frame from a snapshot, ready to render."""
        import copy as _copy
        try:
            if hasattr(self, "api_entry"):
                self.api_entry.delete(0, "end"); self.api_entry.insert(0, snap.get("api_key",""))
            if hasattr(self, "model_var") and snap.get("model"):
                self.model_var.set(snap["model"])
            self.voices = list(snap.get("voices") or [])
            self.voice_list_full = list(snap.get("voice_list_full") or [])
            self.characters = _copy.deepcopy(snap.get("characters") or {})
            if hasattr(self, "common_voice_id"):
                self.common_voice_id.set(snap.get("common_voice_id",""))
            if hasattr(self, "common_voice_name"):
                self.common_voice_name.set(snap.get("common_voice_name",""))
            self._apply_master_settings(snap.get("settings") or {}, warn_missing_files=False)
        except Exception as e:
            print("[QUEUE] settings restore:", e)

        for bd in (snap.get("blocks") or []):
            try:
                self._make_block(bd.get("num"), bd.get("character",""), bd.get("text","") or "",
                                 video_only=bool(bd.get("video_only")))
                b = self.blocks[-1]
                for k in self._SNAP_BLOCK_KEYS:
                    if k in ("num","character","video_only"): continue
                    b[k] = bd.get(k)
                try:
                    if b.get("vol_var") is not None: b["vol_var"].set(int(bd.get("clip_volume") or 0))
                    if b.get("tts_var") is not None: b["tts_var"].set(int(bd.get("tts_volume") or 100))
                except Exception: pass
            except Exception as e:
                print("[QUEUE] block restore:", e)

    def _queue_render(self, save_path, plan):
        # ── Collision guard — two tasks must NEVER share a save_path. If
        # they did, whichever finishes last silently overwrites the other's
        # finished video on disk (this happened in practice: the default
        # suggested filename only had minute resolution, so two videos
        # queued within the same minute got an identical default name). ──
        existing_paths = {os.path.normcase(os.path.abspath(t.save_path))
                          for t in RENDER_QUEUE.tasks if t.save_path}
        norm_sp = os.path.normcase(os.path.abspath(save_path))
        renamed = False
        if norm_sp in existing_paths or os.path.exists(save_path):
            base, ext = os.path.splitext(save_path)
            n = 2
            while True:
                candidate = f"{base}_{n}{ext}"
                if (os.path.normcase(os.path.abspath(candidate)) not in existing_paths
                        and not os.path.exists(candidate)):
                    save_path = candidate
                    renamed = True
                    break
                n += 1

        task = RenderTask(self, type(self), self._snapshot_render_task(), save_path, plan)
        RENDER_QUEUE.add(task)
        # The queued clone above got its OWN independent snapshot of every
        # scene, so it's safe to wipe the live tab now — frees it up
        # immediately for the next video instead of the user having to
        # manually delete 100s of old scenes first.
        try:
            self._clear_blocks_silent()
        except Exception as e:
            print("[QUEUE] post-queue clear:", e)
        self._ss(f"✓ Added to queue: {os.path.basename(save_path)} — "
                 f"scenes cleared, ready for the next video. Go to 🗂 Queue tab and "
                 f"press ▶ Run All / ▶ Run One-by-one.", C["green"])
        try:
            note = (f"\n\n⚠ That filename was already used by another queued/existing "
                    f"file, so this one was auto-renamed to:\n{os.path.basename(save_path)}"
                    if renamed else "")
            messagebox.showinfo("Added to queue",
                f"“{task.name}” is in the render queue (Queued).{note}\n\n"
                "This tab's scenes have been cleared so you can start the next "
                "video right away.\n\n"
                "Open the 🗂 Queue tab and press:\n"
                "▶ Run All — render every queued job in parallel\n"
                "▶ Run One-by-one — render them one at a time",
                parent=self)
        except Exception:
            pass

    def _begin_master_render(self, save_path):
        self._cancelled = False
        self._render_last_key = None
        self._render_last_paint = 0.0
        # Snapshot all Tkinter widget values on main thread BEFORE spawning
        # the render worker. This avoids reading Tk variables from background
        # threads on Windows, which causes silent crashes / hangs.
        # ── Snapshot ALL Tk widget values on main thread (thread-safe) ──
        # Individual reads with try/except per field — one failure doesn't
        # kill the whole snapshot.
        def _sget(attr, default=None):
            try: return getattr(self, attr).get()
            except Exception: return default

        caps_map = {"AA":"upper","Aa":"title","aa":"lower"}
        _font = (_sget("_story_cap_font","") or "").strip()
        if _font in ("","(style default)"): _font = None
        self._rhymes_cap_opts_snapshot = {
            "captions_on":  bool(_sget("_story_cap_on", False)),
            "style":        _sget("_story_cap_style", "Rhymes 1"),
            "karaoke":      bool(_sget("_story_cap_karaoke", True)),
            "caps":         caps_map.get(_sget("_story_cap_caps","AA"), "upper"),
            "size":         int(float(_sget("_story_cap_size", 0) or 0)),
            "max_words":    int(float(_sget("_story_cap_maxwords", 6) or 6)),
            "primary":      (_sget("_story_cap_primary","#FFFFFF") or "").strip() or None,
            "highlight":    (_sget("_story_cap_highlight","#7C3AED") or "").strip() or None,
            "active_text":  (_sget("_story_cap_active","#FFFFFF") or "").strip() or None,
            "border_color": (_sget("_story_cap_active","#000000") or "").strip() or None,
            "box_opacity":  int(float(_sget("_story_cap_opacity", 90) or 90)),
            "font":         _font,
            "box":          bool(_sget("_story_cap_box", False)),
            "box_color":    (_sget("_story_cap_boxcolor","#000000") or "").strip() or "#000000",
            "mode":         _sget("_story_cap_mode", "highlight"),
            "pos_x":        float(getattr(self, "_story_cap_px", 0.5)),
            "pos_y":        float(getattr(self, "_story_cap_py", 0.80)),
            "freeze_motion": "None",
            "freeze_speed":  1.0,
            "fontsdir":     getattr(self, "_story_fontsdir", None),
            "border_on":    bool(_sget("_story_cap_border_on", True)),
            "outline_w":    (lambda v: int(float(v)) if v else None)(_sget("_story_cap_border_w", "")),
        }
        self._render_vars_snapshot = {
            "captions_on":      self._rhymes_cap_opts_snapshot["captions_on"],
            "cap_on":           self._rhymes_cap_opts_snapshot["captions_on"],
            "m_tts_vol":        int(float(_sget("_m_tts_vol", 100) or 100)),
            "m_clip_vol":       int(float(_sget("_m_clip_vol", 0) or 0)),
            "master_vol":       int(float(_sget("master_vol_var", 100) or 100)),
            "master_tts":       int(float(_sget("master_tts_vol_var", 100) or 100)),
            "script_clip_mode": _sget("_script_clip_mode", "clip_eq_tts"),
            "tr_on":            bool(_sget("_m_tr_on", False)),
            "tr_dur":           float(_sget("_m_tr_dur", 0.5) or 0.5),
            "tr_vars": {},
        }
        try: self._render_vars_snapshot["tr_vars"] = {t: bool(v.get()) for t,v in (getattr(self,"_m_tr_vars",{}) or {}).items()}
        except Exception: pass
        print(f"[RENDER] snapshot: style={self._rhymes_cap_opts_snapshot.get('style')}, "
              f"cap_on={self._rhymes_cap_opts_snapshot.get('captions_on')}, "
              f"border_color={self._rhymes_cap_opts_snapshot.get('border_color')}, "
              f"tts_vol={self._render_vars_snapshot.get('m_tts_vol')}")
        threading.Thread(target=self._master_render_worker, args=(save_path,), daemon=True).start()

    def _master_render_worker(self, save_path):
        """Sequential worker: TTS → per-scene → merge → done. The save path is
        already known, so nothing blocks half-way through."""
        render_start = time.time()
        win  = getattr(self, "_render_win", None)
        task = getattr(self, "_task", None)
        try:
            total = len(self.blocks)
            self._render_step(1, "Checking media and voices…", sub=1.0, finished=True)

            # ── Auto-generate PRO captions for un-scripted clips if the
            # captions toggle is ON but the user skipped 🎤 Generate Captions
            # manually. No-op on plain Master (Stories overrides this). ──
            try:
                self._auto_caption_before_render()
            except Exception as e:
                self._sss(f"auto-caption pre-render error: {e}")

            # ── STEP 2 : TTS for scripted scenes ──
            audio_blocks = [i for i, b in enumerate(self.blocks)
                            if (b.get("text") or "").strip() and not b.get("auto_captioned")]
            if audio_blocks:
                if getattr(self, "_cancelled", False): raise RuntimeError("stopped")
                self._render_step(2, "Generating voiceovers…", sub=0.0)
                done = 0
                with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_TTS, len(audio_blocks))) as ex:
                    fm = {ex.submit(self._gen_audio_worker, i): i for i in audio_blocks}
                    for fut in as_completed(fm):
                        if getattr(self, "_cancelled", False):
                            try: ex.shutdown(wait=False, cancel_futures=True)
                            except Exception: pass
                            break
                        try: fut.result()
                        except Exception as e:
                            idx = fm.get(fut)
                            if idx is not None: self.blocks[idx]["_tts_err"] = str(e)[:80]
                        done += 1
                        self._render_step(2, f"Voiceovers {done}/{len(audio_blocks)}",
                                          sub=done/len(audio_blocks))
                if getattr(self, "_cancelled", False): raise RuntimeError("stopped")
                self._render_step(2, "Voiceovers ready", sub=1.0, finished=True)
            if getattr(self, "_cancelled", False): raise RuntimeError("stopped")

            # ── STEP 3 : per-scene compose (+ captions in Stories) ──
            self._render_step(3, "Rendering scenes…", sub=0.0)
            done = 0
            with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_FF, total)) as ex:
                fm = {ex.submit(self._gw, i): i for i in range(total)}
                for fut in as_completed(fm):
                    if getattr(self, "_cancelled", False):
                        try: ex.shutdown(wait=False, cancel_futures=True)
                        except Exception: pass
                        break
                    try: fut.result()
                    except Exception as e:
                        self._sss(f"scene render error: {str(e)[:60]}")
                    done += 1
                    self._render_step(3, f"Scenes {done}/{total}", sub=done/total)
            if getattr(self, "_cancelled", False): raise RuntimeError("stopped")
            ready = sum(1 for b in self.blocks if b.get("output") and os.path.exists(b["output"]))
            if ready == 0:
                self._ss("No scenes rendered successfully!", C["red"])
                self._render_step(3, "All scenes failed — check API / voice / media")
                if task is not None:
                    task.error = "All scenes failed to render"
                    task.finish(False, save_path, time.time() - render_start)
                else:
                    self.after(0, lambda: (win.finish(False) if win else None))
                return
            self._render_step(3, f"{ready} scene(s) rendered", sub=1.0, finished=True)

            if getattr(self, "_cancelled", False): raise RuntimeError("stopped")

            # ── STEP 4-9 : merge (_mw drives the remaining steps) ──
            clips_in_order = [b["output"] for b in self.blocks
                              if b.get("output") and os.path.exists(b["output"])]
            render_start = time.time()
            self._mw(clips_in_order, save_path)

            ok = bool(save_path and os.path.exists(save_path) and self._has_video_track(save_path))
            elapsed = time.time() - render_start
            if task is not None:
                task.finish(ok, save_path, elapsed)           # queue tab + beep
            elif ok:
                self.after(0, lambda: (win.finish(True) if win else None))
                self.after(120, lambda: self._show_render_completion(save_path, elapsed))
            else:
                self.after(0, lambda: (win.finish(False) if win else None))
        except RuntimeError:
            self._ss("Render stopped.", C["red"])
            if task is not None: task.finish(False, save_path, time.time() - render_start)
            else: self.after(0, lambda: (win.finish(False) if win else None))
        except Exception as e:
            self._ss(f"Render error: {str(e)[:70]}", C["red"])
            self._sss(f"master render error: {e}")
            if task is not None:
                task.error = str(e)[:120]
                task.finish(False, save_path, time.time() - render_start)
            else:
                self.after(0, lambda: (win.finish(False) if win else None))
        finally:
            # Safety net — a queued task must NEVER be left at "Rendering".
            # One-by-one mode only advances to the next task once the
            # current one leaves that status, so any missed task.finish()
            # call (a bug, a future code path, anything) would otherwise
            # silently freeze the entire rest of the queue forever.
            if task is not None and task.status == "Rendering":
                task.error = task.error or "Render worker exited without finishing"
                try:
                    task.finish(False, save_path, time.time() - render_start)
                except Exception as e:
                    print("[QUEUE] safety-net finish failed:", e)

    def _show_render_completion(self, output_path, elapsed_seconds):
        """After a successful render, play a long beep and pop up a modal
        dialog showing elapsed time. OK opens the folder containing the
        rendered file (Explorer on Windows, Finder on macOS, xdg-open on
        Linux). Uses a native tkinter Toplevel so it works on every platform
        without extra deps."""
        # ── LOUD, attention-grabbing completion notification ──
        # Uses the system's Windows alert sound (SystemAsterisk) AND a series
        # of longer high-pitched beeps. On Windows the built-in "asterisk"
        # notification honors the user's system volume — much more audible
        # than the raw hardware Beep() calls used earlier.
        def _play_beep():
            try:
                import winsound
                # First: system alert (uses your Windows notification volume,
                # so it's audible even if speakers are low).
                try: winsound.MessageBeep(winsound.MB_ICONASTERISK)
                except Exception: pass
                # Then: 4 clearly-separated long beeps, ascending → completion
                # chime that's impossible to miss even from another room.
                for freq, dur in [(1200, 400), (1500, 400), (1800, 400), (2200, 700)]:
                    try: winsound.Beep(freq, dur)
                    except Exception: pass
                    time.sleep(0.05)
                # Final system alert to punctuate the end.
                try: winsound.MessageBeep(winsound.MB_ICONASTERISK)
                except Exception: pass
            except Exception:
                # Cross-platform fallback: multiple terminal bells with pauses
                try:
                    for _ in range(6):
                        print("\a", end="", flush=True); time.sleep(0.15)
                except Exception: pass
        threading.Thread(target=_play_beep, daemon=True).start()

        # Format elapsed time nicely
        m, s = divmod(int(elapsed_seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:   tstr = f"{h}h {m}m {s}s"
        elif m > 0: tstr = f"{m}m {s}s"
        else:       tstr = f"{s}s"

        try: size_mb = os.path.getsize(output_path) / (1024*1024)
        except Exception: size_mb = 0
        try: video_dur = get_duration(output_path)
        except Exception: video_dur = 0
        dur_str = format_duration(video_dur) if video_dur else "?"

        # ── Modal popup ──
        popup = ctk.CTkToplevel(self)
        popup.title("Render Complete ✓")
        popup.geometry("520x340")
        popup.configure(fg_color=C["bg"])
        popup.transient(self.winfo_toplevel())
        # Center on parent
        try:
            self.winfo_toplevel().update_idletasks()
            px = self.winfo_toplevel().winfo_rootx()
            py = self.winfo_toplevel().winfo_rooty()
            pw = self.winfo_toplevel().winfo_width()
            ph = self.winfo_toplevel().winfo_height()
            popup.geometry(f"+{px + pw//2 - 260}+{py + ph//2 - 170}")
        except Exception: pass

        # Header
        head = ctk.CTkFrame(popup, fg_color=C["green"], corner_radius=0, height=70)
        head.pack(fill="x")
        head.pack_propagate(False)
        ctk.CTkLabel(head, text="✓ RENDER COMPLETE",
                     text_color="#000", font=("Segoe UI", 20, "bold")).pack(pady=18)

        # Body
        body = ctk.CTkFrame(popup, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=25, pady=(20,10))

        rowf = lambda: ctk.CTkFrame(body, fg_color="transparent")
        r = rowf(); r.pack(fill="x", pady=4)
        ctk.CTkLabel(r, text="⏱  Render time:", width=140, anchor="w",
                     text_color=C["dim"], font=("Segoe UI", 12)).pack(side="left")
        ctk.CTkLabel(r, text=tstr, anchor="w",
                     text_color=C["green"], font=("Segoe UI", 13, "bold")).pack(side="left")

        r = rowf(); r.pack(fill="x", pady=4)
        ctk.CTkLabel(r, text="🎞  Video length:", width=140, anchor="w",
                     text_color=C["dim"], font=("Segoe UI", 12)).pack(side="left")
        ctk.CTkLabel(r, text=dur_str, anchor="w",
                     text_color=C["text"], font=("Segoe UI", 12)).pack(side="left")

        r = rowf(); r.pack(fill="x", pady=4)
        ctk.CTkLabel(r, text="💾  File size:", width=140, anchor="w",
                     text_color=C["dim"], font=("Segoe UI", 12)).pack(side="left")
        ctk.CTkLabel(r, text=f"{size_mb:.1f} MB", anchor="w",
                     text_color=C["text"], font=("Segoe UI", 12)).pack(side="left")

        r = rowf(); r.pack(fill="x", pady=(8,4))
        ctk.CTkLabel(r, text="📁  Saved to:", width=140, anchor="w",
                     text_color=C["dim"], font=("Segoe UI", 12)).pack(side="left")
        # Show truncated path if too long
        disp_path = output_path
        if len(disp_path) > 45:
            disp_path = "…" + disp_path[-42:]
        ctk.CTkLabel(r, text=disp_path, anchor="w",
                     text_color=C["accent"], font=("Consolas", 10)).pack(side="left")

        # Buttons
        btn_row = ctk.CTkFrame(popup, fg_color="transparent")
        btn_row.pack(fill="x", padx=25, pady=(10,20))

        def _open_folder():
            folder = os.path.dirname(os.path.abspath(output_path))
            try:
                # Prefer selecting the file itself in Explorer/Finder if we can.
                if sys.platform.startswith("win"):
                    # /select, MUST be one argv token together with the path —
                    # split across two list items, Explorer sees a stray
                    # trailing comma+space and can silently no-op.
                    subprocess.Popen(f'explorer /select,"{os.path.abspath(output_path)}"', **_NO_WINDOW)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", "-R", os.path.abspath(output_path)], **_NO_WINDOW)
                else:
                    subprocess.Popen(["xdg-open", folder], **_NO_WINDOW)
            except Exception:
                try: os.startfile(folder)      # Windows fallback
                except Exception: pass
            try: popup.destroy()
            except Exception: pass

        def _open_file():
            try:
                if sys.platform.startswith("win"):
                    os.startfile(os.path.abspath(output_path))
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", os.path.abspath(output_path)], **_NO_WINDOW)
                else:
                    subprocess.Popen(["xdg-open", os.path.abspath(output_path)], **_NO_WINDOW)
            except Exception: pass
            try: popup.destroy()
            except Exception: pass

        ctk.CTkButton(btn_row, text="▶  Play video", fg_color=C["accent"], text_color="#000",
                      height=38, font=("Segoe UI", 12, "bold"),
                      command=_open_file).pack(side="left", padx=(0,8), fill="x", expand=True)
        ctk.CTkButton(btn_row, text="📁  OK — Open folder", fg_color=C["green"], text_color="#000",
                      height=38, font=("Segoe UI", 12, "bold"),
                      command=_open_folder).pack(side="left", padx=(0,0), fill="x", expand=True)

        # Give focus + lift + grab modality
        popup.after(50, lambda: (popup.lift(), popup.focus_force(), popup.grab_set()))
        # ESC or window-close cancels
        popup.protocol("WM_DELETE_WINDOW", lambda: popup.destroy())
        popup.bind("<Escape>", lambda e: popup.destroy())

    def _add_master_sections(self):
        sb = getattr(self, "_sb_ref", None)
        if sb is None: return
        try:
            C_ = C
            # ── 1. VOLUME MIX ──
            vc = ctk.CTkFrame(sb, fg_color=C_["card"], border_color=C_["accent"], border_width=2, corner_radius=8)
            vc.grid(row=895, column=0, sticky="ew", padx=6, pady=(4,6))
            ctk.CTkLabel(vc, text="🔊 Volume mix", text_color=C_["accent"],
                         font=("Segoe UI",13,"bold")).pack(anchor="w", padx=10, pady=(8,2))
            ctk.CTkLabel(vc, text="Script 100 + Clip 0 = only voiceover. Both 50 = equal mix.",
                         text_color=C_["dim"], font=("Segoe UI",9)).pack(anchor="w", padx=10, pady=(0,4))
            v1 = ctk.CTkFrame(vc, fg_color="transparent"); v1.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(v1, text="Script audio", width=80, text_color=C_["text"]).pack(side="left")
            self._m_tts_vol = ctk.IntVar(value=int(self.settings.get("master_tts_vol") or 100))
            self._m_tts_lbl = ctk.CTkLabel(v1, text=f"{self._m_tts_vol.get()}%", width=40, text_color=C_["dim"])
            ctk.CTkSlider(v1, from_=0, to=100, variable=self._m_tts_vol, width=140,
                          command=lambda v: self._m_tts_lbl.configure(text=f"{int(float(v))}%")).pack(side="left", padx=4)
            self._m_tts_lbl.pack(side="left")
            v2 = ctk.CTkFrame(vc, fg_color="transparent"); v2.pack(fill="x", padx=10, pady=(2,8))
            ctk.CTkLabel(v2, text="Clip audio", width=80, text_color=C_["text"]).pack(side="left")
            self._m_clip_vol = ctk.IntVar(value=int(self.settings.get("master_clip_vol") or 0))
            self._m_clip_lbl = ctk.CTkLabel(v2, text=f"{self._m_clip_vol.get()}%", width=40, text_color=C_["dim"])
            ctk.CTkSlider(v2, from_=0, to=100, variable=self._m_clip_vol, width=140,
                          command=lambda v: self._m_clip_lbl.configure(text=f"{int(float(v))}%")).pack(side="left", padx=4)
            self._m_clip_lbl.pack(side="left")

            # ── 2. TRANSITIONS ──
            tr = ctk.CTkFrame(sb, fg_color=C_["card"], border_color=C_["purple"], border_width=2, corner_radius=8)
            tr.grid(row=894, column=0, sticky="ew", padx=6, pady=(4,6))
            ctk.CTkLabel(tr, text="🔀 Transitions", text_color=C_["purple"],
                         font=("Segoe UI",13,"bold")).pack(anchor="w", padx=10, pady=(8,2))
            self._m_tr_on = ctk.BooleanVar(value=bool(self.settings.get("master_tr_on")))
            tr1 = ctk.CTkFrame(tr, fg_color="transparent"); tr1.pack(fill="x", padx=10, pady=2)
            ctk.CTkCheckBox(tr1, text="Enable random transitions", variable=self._m_tr_on,
                            text_color=C_["text"], fg_color=C_["purple"]).pack(side="left")
            ctk.CTkLabel(tr1, text="Dur:", text_color=C_["dim"]).pack(side="left", padx=(10,2))
            self._m_tr_dur = ctk.DoubleVar(value=float(self.settings.get("master_tr_dur") or 0.5))
            ctk.CTkEntry(tr1, textvariable=self._m_tr_dur, width=40, fg_color=C_["entry_bg"],
                         text_color=C_["text"], border_color=C_["border"]).pack(side="left")
            ctk.CTkLabel(tr1, text="s", text_color=C_["dim"]).pack(side="left")
            tg = ctk.CTkFrame(tr, fg_color="transparent"); tg.pack(fill="x", padx=10, pady=(2,8))
            self._m_tr_vars = {}
            saved = self.settings.get("master_tr_types") or ["fade","wipeleft","slideright","circlecrop"]
            for i, t in enumerate(MASTER_TRANSITIONS):
                v = ctk.BooleanVar(value=(t in saved))
                self._m_tr_vars[t] = v
                ctk.CTkCheckBox(tg, text=t, variable=v, width=14, text_color=C_["dim"],
                                fg_color=C_["purple"], font=("Segoe UI",9)).grid(row=i//3, column=i%3, sticky="w", padx=2, pady=1)

            # ── 3. BULK SFX (name + timestamp based) ──
            sfx = ctk.CTkFrame(sb, fg_color=C_["card"], border_color=C_["orange"], border_width=2, corner_radius=8)
            sfx.grid(row=893, column=0, sticky="ew", padx=6, pady=(4,6))
            ctk.CTkLabel(sfx, text="🔊 Bulk SFX", text_color=C_["orange"],
                         font=("Segoe UI",13,"bold")).pack(anchor="w", padx=10, pady=(8,2))
            ctk.CTkLabel(sfx, text="1) Upload SFX audio files.  2) Upload a timestamp CSV with "
                                   "columns: scene, name, timestamp (e.g. 3,door_creak,2.5 or "
                                   "3,door_creak,0:02.5). Matching SFX get placed automatically.",
                         text_color=C_["dim"], font=("Segoe UI",9), wraplength=330,
                         justify="left").pack(anchor="w", padx=10, pady=(0,4))
            sfx_r1 = ctk.CTkFrame(sfx, fg_color="transparent"); sfx_r1.pack(fill="x", padx=10, pady=2)
            ctk.CTkButton(sfx_r1, text="📁 Upload SFX (bulk)", fg_color=C_["accent"], text_color="#000",
                         height=28, font=("Segoe UI",10),
                         command=self._sfx_upload_bulk).pack(side="left", fill="x", expand=True, padx=(0,3))
            ctk.CTkButton(sfx_r1, text="🗑", width=32, height=28, fg_color=C_["btn"], text_color=C_["dim"],
                         command=self._sfx_clear_all).pack(side="left")
            self._sfx_files_lbl = ctk.CTkLabel(sfx, text="0 SFX file(s) uploaded",
                                               text_color=C_["dim"], font=("Segoe UI",9))
            self._sfx_files_lbl.pack(anchor="w", padx=10, pady=(2,4))
            ctk.CTkButton(sfx, text="📄 Upload Timestamps (CSV)", fg_color=C_["purple"], text_color="#fff",
                         height=28, font=("Segoe UI",10),
                         command=self._sfx_upload_timestamps).pack(fill="x", padx=10, pady=(0,4))
            self._sfx_match_lbl = ctk.CTkLabel(sfx, text="", text_color=C_["dim"],
                                               font=("Segoe UI",9), wraplength=330, justify="left")
            self._sfx_match_lbl.pack(anchor="w", padx=10, pady=(0,8))

            # Logo + BGM: uses the base sections (with Preview/Position features)
            # Presets: handled by base AdvanceEditorFrame preset buttons (row=998)

            # ── HELP ──
            ctk.CTkButton(sb, text="❓ Help", fg_color="#1e222b", hover_color="#323845",
                          text_color="#9aa0aa", height=28, font=("Segoe UI",10),
                          command=lambda: _show_tab_help("👑 Master", self._tab_help_steps())).grid(
                          row=999, column=0, sticky="ew", padx=6, pady=(4,8))
        except Exception as e:
            print("[MASTER] section error:", e)

    # ────────────────────────────────────────────────────────────────────
    # PRESET SYSTEM — save/load complete Master configuration
    # ────────────────────────────────────────────────────────────────────
    def _get_master_presets_dir(self):
        """User's presets folder: ~/.video_master_tool/master_presets/"""
        d = os.path.join(os.path.expanduser("~"), ".video_master_tool", "master_presets")
        try: os.makedirs(d, exist_ok=True)
        except Exception: pass
        return d

    def _list_master_presets(self):
        try:
            d = self._get_master_presets_dir()
            files = [f[:-5] for f in os.listdir(d) if f.endswith(".json")]
            return sorted(files)
        except Exception:
            return []

    def _refresh_preset_dropdown(self):
        """Repopulate the preset dropdown after save/delete."""
        try:
            presets = self._list_master_presets()
            if not presets: presets = ["(no presets yet)"]
            self._preset_menu.configure(values=presets)
            if presets and presets[0] != "(no presets yet)":
                self._preset_dropdown_var.set(presets[0])
        except Exception as e:
            print("[PRESET refresh]", e)

    def _collect_master_settings(self):
        """Snapshot every configurable Master + base setting into a dict.
        Files are stored by absolute path — if you move the file later, the
        preset will show a warning on load but won't crash."""
        g = lambda var, default=None: (var.get() if var is not None else default)
        snap = {
            "_schema_version": 1,
            "_saved_at": int(time.time()),
            # ── Master's own controls ──
            "m_tts_vol":  g(getattr(self, "_m_tts_vol", None), 100),
            "m_clip_vol": g(getattr(self, "_m_clip_vol", None), 0),
            "m_tr_on":    g(getattr(self, "_m_tr_on", None), False),
            "m_tr_dur":   g(getattr(self, "_m_tr_dur", None), 0.5),
            "m_tr_types": [t for t, v in (getattr(self, "_m_tr_vars", {}) or {}).items() if v.get()],
            "master_logos": [dict(lg) for lg in (getattr(self, "_master_logos", None) or [])],
            "script_clip_mode": g(getattr(self, "_script_clip_mode", None), "full_clip"),
            # ── Base Logo 1 (Preview & Position) ──
            "logo_enabled": g(getattr(self, "logo_enabled_var", None), False),
            "logo_path":    g(getattr(self, "logo_path_var", None), ""),
            "logo_size":    g(getattr(self, "logo_size_var", None), 100),
            "logo_anchor":  g(getattr(self, "logo_anchor_var", None), "top-right"),
            "logo_opacity": g(getattr(self, "logo_opacity_var", None), 100),
            "logo_pct_x":   getattr(self, "_logo_pct_x", None),
            "logo_pct_y":   getattr(self, "_logo_pct_y", None),
            "logo_pct_size": getattr(self, "_logo_pct_size", None),
            # ── Extra logos (Logo 2, 3, …) ──
            "extra_logos": [
                {
                    "path":    lg.get("path", ""),
                    "size":    (lg["size_var"].get()    if lg.get("size_var")    else 80),
                    "opacity": (lg["opacity_var"].get() if lg.get("opacity_var") else 100),
                    "anchor":  (lg["anchor_var"].get()  if lg.get("anchor_var")  else "top-right"),
                    "pct_x":   lg.get("pct_x"),
                    "pct_y":   lg.get("pct_y"),
                    "pct_size": lg.get("pct_size"),
                }
                for lg in (getattr(self, "_extra_logos", None) or [])
            ],
            # ── BGM ──
            "bgm_enabled": g(getattr(self, "bgm_enabled_var", None), False),
            "bgm_path":    g(getattr(self, "bgm_var", None), ""),
            "bgm_volume":  g(getattr(self, "bgm_vol_var", None), 0.15),
            "bgm_loop":    g(getattr(self, "bgm_loop_var", None), False),
            "bgm_xfade":   g(getattr(self, "bgm_xfade_var", None), False),
            "bgm_prompt":  g(getattr(self, "bgm_prompt_var", None), ""),
            "bgm_gen_dur": g(getattr(self, "bgm_gen_dur_var", None), 30),
            # ── Volumes ──
            "master_vol":    g(getattr(self, "master_vol_var", None), 100),
            "master_tts_vol": g(getattr(self, "master_tts_vol_var", None), 100),
        }
        # ── Captions ──
        snap["captions_enabled"] = g(getattr(self, "captions_enabled_var", None), False)
        snap["caption_font_path"] = g(getattr(self, "caption_font_path_var", None), "")
        snap["caption_font_size"] = g(getattr(self, "caption_font_size_var", None), 48)
        snap["caption_font_color"] = g(getattr(self, "caption_font_color_var", None), "FFFFFF")
        snap["caption_bg_color"] = g(getattr(self, "caption_bg_color_var", None), "000000")
        snap["caption_bg_opacity"] = g(getattr(self, "caption_bg_opacity_var", None), 0.6)
        snap["caption_max_chars"] = g(getattr(self, "caption_max_chars_var", None), 30)
        snap["caption_max_lines"] = g(getattr(self, "caption_max_lines_var", None), 2)
        snap["caption_position"] = g(getattr(self, "caption_position_var", None), "bottom")
        snap["caption_margin"] = g(getattr(self, "caption_margin_var", None), 50)
        snap["caption_animation"] = g(getattr(self, "caption_animation_var", None), "fade")
        snap["caption_words"] = g(getattr(self, "caption_words_var", None), 4)
        # ── ElevenLabs ──
        snap["api_key"] = (self.api_entry.get().strip() if hasattr(self, "api_entry") else "")
        snap["silence_pad"] = g(getattr(self, "silence_var", None), 300)
        # ── Intro ──
        snap["intro_enabled"] = g(getattr(self, "intro_enabled_var", None), False)
        # ── Transition ──
        snap["transition_enabled"] = g(getattr(self, "transition_var", None), False)
        snap["transition_duration"] = g(getattr(self, "trans_dur_var", None), 0.5)
        # ── Render settings ──
        snap["mode"] = g(getattr(self, "mode_var", None), "story")
        snap["loop_count"] = g(getattr(self, "loop_count_var", None), 1)
        # ── Crop / Resolution ──
        snap["crop_ratio"] = g(getattr(self, "crop_ratio_var", None), "16:9")
        snap["output_resolution"] = g(getattr(self, "output_res_var", None), "1080p")
        # ── Chroma Key ──
        snap["chroma_enabled"] = g(getattr(self, "chroma_enabled_var", None), False)
        snap["chroma_color"] = g(getattr(self, "chroma_color_var", None), "00FF00")
        snap["chroma_similarity"] = g(getattr(self, "chroma_sim_var", None), 0.3)
        # ── Filler ──
        snap["filler_video"] = getattr(self, "filler_path", "")
        # Voice/model — save the *name* strings; user might not have the
        # same voices on a different account, so we only restore if present.
        try: snap["common_voice"] = self.common_voice_var.get() if hasattr(self,"common_voice_var") else ""
        except: snap["common_voice"] = ""
        try: snap["common_voice_id"] = self.common_voice_id.get() if hasattr(self,"common_voice_id") else ""
        except: snap["common_voice_id"] = ""
        try: snap["common_voice_name"] = self.common_voice_name.get() if hasattr(self,"common_voice_name") else ""
        except: snap["common_voice_name"] = ""
        try: snap["model_name"] = self.model_var.get() if hasattr(self,"model_var") else ""
        except: snap["model_name"] = ""
        try: snap["video_type"] = self._video_type_var.get() if hasattr(self,"_video_type_var") else "Normal Video"
        except: snap["video_type"] = "Normal Video"

        # ── Scenes are intentionally NOT saved in presets. A preset only
        # captures reusable settings (logo, BGM, captions, render, voice,
        # etc.) — per-video scene structure (clips/trim/character/script)
        # stays with the project, not the preset. ──
        snap["blocks"] = []
        return snap


    def _apply_master_settings(self, snap, warn_missing_files=True):
        """Restore state from a preset dict. Best-effort — a missing widget
        or a moved file will just be skipped with a printed warning rather
        than crashing the whole load."""
        def s(var, key, default=None):
            if var is None: return
            v = snap.get(key, default)
            if v is None: return
            try: var.set(v)
            except Exception: pass

        s(getattr(self, "_m_tts_vol",  None), "m_tts_vol", 100)
        s(getattr(self, "_m_clip_vol", None), "m_clip_vol", 0)
        s(getattr(self, "_m_tr_on",    None), "m_tr_on", False)
        s(getattr(self, "_m_tr_dur",   None), "m_tr_dur", 0.5)
        tr_saved = set(snap.get("m_tr_types", []) or [])
        for t, v in (getattr(self, "_m_tr_vars", {}) or {}).items():
            try: v.set(t in tr_saved)
            except Exception: pass
        s(getattr(self, "_script_clip_mode", None), "script_clip_mode", "full_clip")
        if hasattr(self, "_video_type_var"):
            vt = snap.get("video_type", "Normal Video") or "Normal Video"
            try:
                self._video_type_var.set(vt)
                self._on_video_type_change(vt, _save=False)
            except Exception:
                pass
        # Master logos
        try:
            self._master_logos.clear()
            for lg in snap.get("master_logos", []) or []:
                self._master_logos.append(dict(lg))
            if hasattr(self, "_m_refresh_logos"): self._m_refresh_logos()
        except Exception as e:
            print("[PRESET] master_logos:", e)
        # Base Logo 1
        s(getattr(self, "logo_enabled_var", None), "logo_enabled", False)
        s(getattr(self, "logo_path_var",    None), "logo_path", "")
        s(getattr(self, "logo_size_var",    None), "logo_size", 100)
        s(getattr(self, "logo_anchor_var",  None), "logo_anchor", "top-right")
        s(getattr(self, "logo_opacity_var", None), "logo_opacity", 100)
        for k in ("logo_pct_x", "logo_pct_y", "logo_pct_size"):
            attr = "_" + k
            v = snap.get(k)
            try: setattr(self, attr, v)
            except Exception: pass
        # Update the logo label
        try:
            lp = snap.get("logo_path", "")
            if lp and hasattr(self, "logo_lbl"):
                self.logo_lbl.configure(text=os.path.basename(lp))
        except Exception: pass
        # BGM
        s(getattr(self, "bgm_enabled_var", None), "bgm_enabled", False)
        s(getattr(self, "bgm_var",         None), "bgm_path", "")
        s(getattr(self, "bgm_vol_var",     None), "bgm_volume", 0.15)
        s(getattr(self, "bgm_loop_var",    None), "bgm_loop", False)
        s(getattr(self, "bgm_xfade_var",   None), "bgm_xfade", False)
        s(getattr(self, "bgm_prompt_var",  None), "bgm_prompt", "")
        s(getattr(self, "bgm_gen_dur_var", None), "bgm_gen_dur", 30)
        try:
            bp = snap.get("bgm_path", "")
            if bp and hasattr(self, "bgm_lbl"):
                self.bgm_lbl.configure(text="🎵 " + os.path.basename(bp))
            if bp and hasattr(self, "_m_bgm_lbl"):
                self._m_bgm_lbl.configure(text=os.path.basename(bp))
        except Exception: pass
        # Volumes
        s(getattr(self, "master_vol_var",     None), "master_vol", 100)
        s(getattr(self, "master_tts_vol_var", None), "master_tts_vol", 100)
        # Extra logos — rebuild by calling the base's _add_extra_logo logic
        try:
            if hasattr(self, "_extra_logos_frame"):
                for w in list(self._extra_logos_frame.winfo_children()):
                    try: w.destroy()
                    except: pass
                self._extra_logos = []
            for lg in snap.get("extra_logos", []) or []:
                lp = lg.get("path")
                if not (lp and os.path.exists(lp)): continue
                self._recreate_extra_logo(lp, lg)
        except Exception as e:
            print("[PRESET] extra_logos:", e)

        # Captions
        s(getattr(self, "captions_enabled_var", None), "captions_enabled", False)
        s(getattr(self, "caption_font_path_var", None), "caption_font_path", "")
        s(getattr(self, "caption_font_size_var", None), "caption_font_size", 48)
        s(getattr(self, "caption_font_color_var", None), "caption_font_color", "FFFFFF")
        s(getattr(self, "caption_bg_color_var", None), "caption_bg_color", "000000")
        s(getattr(self, "caption_bg_opacity_var", None), "caption_bg_opacity", 0.6)
        s(getattr(self, "caption_max_chars_var", None), "caption_max_chars", 30)
        s(getattr(self, "caption_max_lines_var", None), "caption_max_lines", 2)
        s(getattr(self, "caption_position_var", None), "caption_position", "bottom")
        s(getattr(self, "caption_margin_var", None), "caption_margin", 50)
        s(getattr(self, "caption_animation_var", None), "caption_animation", "fade")
        s(getattr(self, "caption_words_var", None), "caption_words", 4)
        # ElevenLabs
        if snap.get("api_key") and hasattr(self, "api_entry"):
            self.api_entry.delete(0, "end"); self.api_entry.insert(0, snap["api_key"])
        s(getattr(self, "silence_var", None), "silence_pad", 300)
        # Intro / Transition
        s(getattr(self, "intro_enabled_var", None), "intro_enabled", False)
        s(getattr(self, "transition_var", None), "transition_enabled", False)
        s(getattr(self, "trans_dur_var", None), "transition_duration", 0.5)
        # Render
        s(getattr(self, "mode_var", None), "mode", "story")
        s(getattr(self, "loop_count_var", None), "loop_count", 1)
        # Crop / Resolution
        s(getattr(self, "crop_ratio_var", None), "crop_ratio", "16:9")
        s(getattr(self, "output_res_var", None), "output_resolution", "1080p")
        # Chroma
        s(getattr(self, "chroma_enabled_var", None), "chroma_enabled", False)
        s(getattr(self, "chroma_color_var", None), "chroma_color", "00FF00")
        s(getattr(self, "chroma_sim_var", None), "chroma_similarity", 0.3)
        # Filler
        if snap.get("filler_video"):
            self.filler_path = snap["filler_video"]
        # Voice — restore by name and ID directly
        if snap.get("common_voice_id") and hasattr(self, "common_voice_id"):
            self.common_voice_id.set(snap["common_voice_id"])
        if snap.get("common_voice_name") and hasattr(self, "common_voice_name"):
            self.common_voice_name.set(snap["common_voice_name"])
        # Voice/model — only apply if the name is still in the loaded list
        try:
            vn = snap.get("common_voice", "")
            if vn and hasattr(self, "voices"):
                names = [v.get("name") for v in self.voices] if self.voices else []
                if vn in names and hasattr(self, "common_voice_var"):
                    self.common_voice_var.set(vn)
                    # Also trigger the ID sync
                    for v in self.voices:
                        if v.get("name") == vn:
                            self.common_voice_id.set(v.get("voice_id",""))
                            break
        except Exception: pass
        try:
            mn = snap.get("model_name", "")
            if mn and hasattr(self, "models"):
                names = [m.get("name") for m in self.models] if self.models else []
                if mn in names and hasattr(self, "model_var"):
                    self.model_var.set(mn)
        except Exception: pass

        # ── Scenes are NOT part of a preset (by design). Loading a preset
        # never touches the existing scene list — user's clips, trims,
        # characters and scripts stay exactly as they were. ──


        # ── Warn about missing files ──
        if warn_missing_files:
            missing = []
            for k in ("logo_path", "bgm_path"):
                p = snap.get(k, "")
                if p and not os.path.exists(p): missing.append((k, p))
            for lg in snap.get("master_logos", []) or []:
                p = lg.get("path", "")
                if p and not os.path.exists(p): missing.append(("master_logo", p))
            for lg in snap.get("extra_logos", []) or []:
                p = lg.get("path", "")
                if p and not os.path.exists(p): missing.append(("extra_logo", p))
            for bd in (blocks_data or []):
                p = bd.get("source_media", "")
                if p and not os.path.exists(p): missing.append(("scene clip", p))
            if missing:
                lines = "\n".join(f"  • {os.path.basename(p) or p} ({k})" for k, p in missing[:10])
                messagebox.showwarning(
                    "Missing files",
                    f"Preset loaded, but {len(missing)} file(s) referenced by it "
                    f"no longer exist on disk:\n\n{lines}\n\n"
                    f"Please re-pick those files or move them back to their original location."
                )

    # ────────────────────────────────────────────────────────────────
    # BULK SFX — upload a batch of sound-effect files, then a timestamp
    # CSV (scene, name, timestamp) that says where each one goes. Matched
    # SFX get mixed into that scene's audio at render time (see _gw()).
    # ────────────────────────────────────────────────────────────────
    def _sfx_upload_bulk(self):
        paths = filedialog.askopenfilenames(
            parent=self, filetypes=[("Audio", "*.mp3 *.wav *.m4a *.aac *.ogg *.flac")])
        if not paths: return
        if not hasattr(self, "_bulk_sfx_files"):
            self._bulk_sfx_files = {}
        for p in paths:
            key = os.path.splitext(os.path.basename(p))[0].strip().lower()
            self._bulk_sfx_files[key] = p
        try:
            self._sfx_files_lbl.configure(text=f"{len(self._bulk_sfx_files)} SFX file(s) uploaded")
        except Exception: pass
        self._ss(f"✓ {len(paths)} SFX file(s) added — now upload the timestamp CSV.", C["green"])

    def _sfx_clear_all(self):
        self._bulk_sfx_files = {}
        for b in self.blocks:
            b["sfx"] = []
        try: self._sfx_files_lbl.configure(text="0 SFX file(s) uploaded")
        except Exception: pass
        try: self._sfx_match_lbl.configure(text="")
        except Exception: pass
        self._ss("SFX cleared from all scenes.", C["orange"])

    def _sfx_parse_timestamp(self, s):
        """Accepts plain seconds ('2.5') or MM:SS / HH:MM:SS ('0:02.5', '1:02:03')."""
        s = (s or "").strip()
        if not s: return 0.0
        try:
            if ":" in s:
                parts = [float(p) for p in s.split(":")]
                secs = 0.0
                for p in parts:
                    secs = secs * 60 + p
                return max(0.0, secs)
            return max(0.0, float(s))
        except Exception:
            return 0.0

    def _sfx_upload_timestamps(self):
        if not getattr(self, "_bulk_sfx_files", None):
            messagebox.showinfo("Bulk SFX", "Pehle '📁 Upload SFX (bulk)' se SFX files upload karo.",
                                parent=self)
            return
        path = filedialog.askopenfilename(parent=self, filetypes=[("CSV/Text", "*.csv *.txt")])
        if not path: return

        import csv as _csv
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                rows = [r for r in _csv.reader(f) if r and any((c or "").strip() for c in r)]
        except Exception as e:
            messagebox.showerror("Bulk SFX", f"Timestamp file nahi padh paya:\n{e}", parent=self)
            return

        start_idx = 0
        if rows and rows[0][0].strip().lower() in ("scene", "scene_number", "#"):
            start_idx = 1  # skip header row

        block_by_num = {b["num"]: b for b in self.blocks}
        matched, unmatched, bad_scene = 0, [], []

        for r in rows[start_idx:]:
            if len(r) < 3: continue
            scene_s, name, ts_s = (r[0] or "").strip(), (r[1] or "").strip(), (r[2] or "").strip()
            try:
                scene_num = int(float(scene_s))
            except Exception:
                continue
            ts = self._sfx_parse_timestamp(ts_s)
            key = os.path.splitext(name)[0].strip().lower()
            sfx_path = self._bulk_sfx_files.get(key)
            if not sfx_path:
                # fallback: loose substring match (e.g. "door" matches "door_creak_v2")
                for k, p in self._bulk_sfx_files.items():
                    if key and (key in k or k in key):
                        sfx_path = p; break
            if not sfx_path:
                unmatched.append(name); continue
            b = block_by_num.get(scene_num)
            if not b:
                bad_scene.append(f"{name} → scene {scene_num}"); continue
            b.setdefault("sfx", []).append({"path": sfx_path, "start": ts, "name": name})
            matched += 1

        msg = f"✓ {matched} SFX placed"
        if unmatched: msg += f" • {len(unmatched)} name(s) not matched"
        if bad_scene: msg += f" • {len(bad_scene)} scene number(s) not found"
        try: self._sfx_match_lbl.configure(text=msg)
        except Exception: pass
        self._ss(msg, C["green"] if matched else C["orange"])
        if unmatched or bad_scene:
            detail = ""
            if unmatched: detail += "Naam se match nahi hua:\n" + "\n".join(unmatched[:15]) + "\n\n"
            if bad_scene: detail += "Scene number nahi mila:\n" + "\n".join(bad_scene[:15])
            messagebox.showwarning("Bulk SFX — kuch rows skip hui", detail, parent=self)

    def _on_video_type_change(self, value, _save=True):
        is_kids = (value == "Kids Video")
        try:
            self._video_type_hint.configure(
                text="🎵 BGM auto-ducks under narration/SFX" if is_kids else "")
        except Exception:
            pass
        if _save:
            try:
                self.settings.set("video_type", value)
                self.settings.save()
            except Exception:
                pass
            try:
                self._ss(f"Video type: {value}" + (" — BGM ducking ON" if is_kids else ""), C["green"])
            except Exception:
                pass

    def _render_session_uid(self):
        """Stable-per-instance token so two renders (e.g. two videos queued
        back to back, each rendering in its own hidden clone) never share a
        temp filename. Without this, every TEMP_DIR path in _gw()/_mw() was
        keyed only by scene number (or not keyed at all, e.g. 'master_out.mp4'
        was completely fixed) — so if a later queued video's own render step
        stumbled even briefly, it could silently pick up a STALE leftover
        file from an earlier video's render (identical path/name) and report
        success. The symptom: a later queued video's output turns out to be
        a duplicate of an earlier one instead of its own content."""
        uid = getattr(self, "_render_uid", None)
        if not uid:
            uid = f"{os.getpid()}_{id(self)}"
            self._render_uid = uid
        return uid

    def _auto_caption_before_render(self):
        """No-op on plain Master — PRO captions/Whisper auto-transcription is
        a Stories-tab feature. StoriesEditorFrame overrides this."""
        pass

    def _clear_blocks_silent(self, reset_characters=True):
        """Destroy all scene rows WITHOUT a confirmation dialog — used right
        before restoring a preset's scenes, and right after a render is sent
        to the 🗂 Queue tab (the queued clone already has its own independent
        snapshot, so clearing the live tab here just frees it up for the
        next video)."""
        frames = [b.get("frame") for b in self.blocks]
        for fr in frames:
            try:
                if fr is not None: fr.destroy()
            except Exception: pass
        self.blocks.clear()
        self._caption_groups.clear()
        if reset_characters:
            self.characters = {}
        try: self.cap_status_lbl.configure(text="OFF", text_color=C["dim"])
        except Exception: pass
        try: self.progress.set(0)
        except Exception: pass

    def _recreate_extra_logo(self, path, snap_entry):
        """Rebuild ONE extra-logo UI row from a preset snapshot, mimicking
        exactly what base's _add_extra_logo does but skipping the file dialog."""
        idx = len(self._extra_logos) + 2
        ef = ctk.CTkFrame(self._extra_logos_frame, fg_color=C["btn"], corner_radius=6)
        ef.pack(fill="x", pady=(2,3), padx=1)
        ctk.CTkLabel(ef, text=f"Logo {idx}: {os.path.basename(path)[:22]}", text_color=C["green"],
                     font=("Segoe UI",9,"bold")).pack(anchor="w", padx=5, pady=(4,1))
        row1=ctk.CTkFrame(ef, fg_color="transparent"); row1.pack(fill="x", padx=3, pady=1)
        ctk.CTkLabel(row1,text="Sz",text_color=C["dim"],font=("Segoe UI",8),width=14).pack(side="left")
        sz=ctk.IntVar(value=int(snap_entry.get("size", 80)))
        op=ctk.IntVar(value=int(snap_entry.get("opacity", 100)))
        anc=ctk.StringVar(value=str(snap_entry.get("anchor", "top-right")))
        ctk.CTkSlider(row1,from_=20,to=400,variable=sz,width=55).pack(side="left",padx=2)
        ctk.CTkLabel(row1,text="Op",text_color=C["dim"],font=("Segoe UI",8),width=14).pack(side="left")
        ctk.CTkSlider(row1,from_=10,to=100,variable=op,width=55).pack(side="left",padx=2)
        ctk.CTkOptionMenu(row1,variable=anc,fg_color=C["btn_hov"],text_color=C["text"],
            values=["top-left","top-right","bottom-left","bottom-right","center"],width=90,
            font=("Segoe UI",8)).pack(side="left",padx=2)
        entry={"path":path,"size_var":sz,"opacity_var":op,"anchor_var":anc,"frame":ef,
               "pct_x":snap_entry.get("pct_x"),"pct_y":snap_entry.get("pct_y"),
               "pct_size":snap_entry.get("pct_size"),"cropped_pil":None}
        row2=ctk.CTkFrame(ef, fg_color="transparent"); row2.pack(fill="x", padx=3, pady=(1,4))
        ctk.CTkButton(row2,text="Preview & Position",height=24,fg_color=C["purple"],text_color="#fff",
            font=("Segoe UI",9,"bold"),command=lambda e=entry:self._extra_logo_preview(e)).pack(side="left",padx=2,fill="x",expand=True)
        def _rm(frame=ef, e=entry):
            self._extra_logos=[l for l in self._extra_logos if l is not e]
            frame.destroy()
        ctk.CTkButton(row2,text="X",width=26,height=24,fg_color=C["red"],text_color="#fff",command=_rm).pack(side="left",padx=2)
        self._extra_logos.append(entry)

    def _save_master_preset(self):
        """Prompt for a name, save current state to a JSON file."""
        # Use a simple modal to collect the name
        popup = ctk.CTkToplevel(self)
        popup.title("Save preset")
        popup.geometry("380x180")
        popup.configure(fg_color=C["bg"])
        popup.transient(self.winfo_toplevel())
        try:
            self.winfo_toplevel().update_idletasks()
            px = self.winfo_toplevel().winfo_rootx() + self.winfo_toplevel().winfo_width()//2 - 190
            py = self.winfo_toplevel().winfo_rooty() + self.winfo_toplevel().winfo_height()//2 - 90
            popup.geometry(f"+{px}+{py}")
        except Exception: pass
        ctk.CTkLabel(popup, text="💾 Save current setup as preset",
                     text_color=C["orange"], font=("Segoe UI",14,"bold")).pack(pady=(20,4))
        ctk.CTkLabel(popup, text="Name it (letters, digits, spaces, dashes):",
                     text_color=C["dim"], font=("Segoe UI",10)).pack()
        name_var = ctk.StringVar(value="")
        ent = ctk.CTkEntry(popup, textvariable=name_var, width=280, height=32,
                           fg_color=C["entry_bg"], border_color=C["orange"])
        ent.pack(pady=8)
        ent.focus_set()
        row = ctk.CTkFrame(popup, fg_color="transparent"); row.pack(pady=(6,0))
        def do_save():
            name = (name_var.get() or "").strip()
            if not name:
                messagebox.showwarning("Save preset", "Please enter a name."); return
            # Sanitize
            safe = re.sub(r"[^\w \-\.]", "_", name).strip("._ ")
            if not safe:
                messagebox.showwarning("Save preset", "Name has no valid characters."); return
            path = os.path.join(self._get_master_presets_dir(), safe + ".json")
            if os.path.exists(path):
                if not messagebox.askyesno("Overwrite?",
                    f"A preset named '{safe}' already exists. Overwrite?"):
                    return
            try:
                snap = self._collect_master_settings()
                snap["_name"] = safe
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(snap, f, indent=2)
                self._refresh_preset_dropdown()
                try: self._preset_dropdown_var.set(safe)
                except Exception: pass
                self._ss(f"✓ Preset saved: {safe}", C["green"])
                popup.destroy()
            except Exception as e:
                messagebox.showerror("Save preset", f"Could not save preset:\n{e}")
        ctk.CTkButton(row, text="💾 Save", fg_color=C["green"], text_color="#000",
                      font=("Segoe UI",11,"bold"), width=100, command=do_save).pack(side="left", padx=5)
        ctk.CTkButton(row, text="Cancel", fg_color=C["btn"], text_color=C["dim"],
                      width=100, command=popup.destroy).pack(side="left", padx=5)
        ent.bind("<Return>", lambda e: do_save())
        popup.bind("<Escape>", lambda e: popup.destroy())
        popup.after(50, lambda: (popup.lift(), popup.focus_force(), popup.grab_set()))

    def _load_master_preset(self):
        name = (self._preset_dropdown_var.get() or "").strip()
        if not name or name == "(no presets yet)":
            messagebox.showinfo("Load preset", "Pick a preset from the dropdown first."); return
        path = os.path.join(self._get_master_presets_dir(), name + ".json")
        if not os.path.exists(path):
            messagebox.showwarning("Load preset", f"Preset file not found:\n{path}"); return
        try:
            with open(path, "r", encoding="utf-8") as f:
                snap = json.load(f)
            self._apply_master_settings(snap)
            self._ss(f"✓ Preset loaded: {name}", C["green"])
        except Exception as e:
            messagebox.showerror("Load preset", f"Could not load preset:\n{e}")

    def _delete_master_preset(self):
        name = (self._preset_dropdown_var.get() or "").strip()
        if not name or name == "(no presets yet)":
            messagebox.showinfo("Delete preset", "Pick a preset from the dropdown first."); return
        if not messagebox.askyesno("Delete preset", f"Really delete preset '{name}'?"):
            return
        try:
            path = os.path.join(self._get_master_presets_dir(), name + ".json")
            if os.path.exists(path): os.remove(path)
            self._refresh_preset_dropdown()
            self._ss(f"Preset deleted: {name}", C["orange"])
        except Exception as e:
            messagebox.showerror("Delete preset", f"Could not delete preset:\n{e}")

    def _open_master_presets_folder(self):
        d = self._get_master_presets_dir()
        try:
            if sys.platform.startswith("win"):
                os.startfile(d)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", d], **_NO_WINDOW)
            else:
                subprocess.Popen(["xdg-open", d], **_NO_WINDOW)
        except Exception as e:
            messagebox.showinfo("Presets folder", f"Located at:\n{d}\n\n(Couldn't open automatically: {e})")

    def _m_pick_bgm(self):
        p=filedialog.askopenfilename(parent=self, filetypes=[("Audio","*.mp3 *.wav *.m4a *.aac *.ogg *.flac")])
        if p:
            self.bgm_var.set(p); self.bgm_enabled_var.set(True)
            # Auto-enable the "Loop BGM" checkbox — users almost always want
            # their BGM to fill the whole video regardless of clip length.
            # Manual toggle is still available in the base BGM section.
            try: self.bgm_loop_var.set(True)
            except Exception: pass
            try: self._m_bgm_lbl.configure(text=os.path.basename(p))
            except: pass

    def _m_gen_bgm(self):
        try: self.bgm_enabled_var.set(True)
        except: pass
        # Auto-enable loop for generated BGM too — the whole point of
        # prompt-generated BGM is to have music covering the entire render.
        try: self.bgm_loop_var.set(True)
        except Exception: pass
        self._generate_bgm()
        try:
            if self.bgm_var.get(): self._m_bgm_lbl.configure(text=os.path.basename(self.bgm_var.get()))
        except: pass

    def _m_add_logo(self):
        p=filedialog.askopenfilename(parent=self, filetypes=[("Images","*.png *.jpg *.jpeg *.webp *.bmp")])
        if not p: return
        # Stagger each newly-added logo so multiple logos never land on the
        # EXACT same spot (that overlap is why "2 logos" looked like only 1).
        _n = len(self._master_logos)
        _spots = [(0.88,0.88),(0.06,0.06),(0.88,0.06),(0.06,0.88),(0.47,0.06),(0.47,0.88)]
        _sx,_sy = _spots[_n % len(_spots)]
        _bump = 0.02 * (_n // len(_spots))
        _sx = min(0.90, max(0.03, _sx + _bump)); _sy = min(0.90, max(0.03, _sy + _bump))
        self._master_logos.append({"path":p, "x":_sx, "y":_sy, "size":0.08, "opacity":1.0})
        self._m_refresh_logos()

    def _m_clear_logos(self):
        self._master_logos.clear(); self._m_refresh_logos()

    def _m_refresh_logos(self):
        # Defensive: the compact optional list-display widget for this isn't
        # always present (e.g. during a hidden queue-clone render, or on a
        # preset load). The actual render logic reads self._master_logos
        # directly, so a missing display widget is cosmetic only — never a
        # reason to raise and abort a preset load or a render.
        if not (hasattr(self, "_m_logo_list") and hasattr(self, "_m_logo_count")):
            return
        try:
            self._m_logo_list.configure(state="normal"); self._m_logo_list.delete("1.0","end")
            for i, lg in enumerate(self._master_logos, 1):
                self._m_logo_list.insert("end", f"{i}. {os.path.basename(lg['path'])}\n")
            self._m_logo_list.configure(state="disabled")
            self._m_logo_count.configure(text=f"{len(self._master_logos)}")
        except Exception as e:
            print("[MASTER] logo list refresh:", e)

    def _gw(self, idx):
        """Master's own per-scene render — self-contained, CPU-based, no reliance
        on the base pipeline's branch-heavy code (which was silently producing
        audio-only outputs on some setups).

        Pipeline:
          1. If script text: generate TTS via base worker (writes b['tts_audio'])
          2. Pick video length target (full clip OR TTS length per Scripted clips radio)
          3. Normalize source video to 1920×1080 30fps H.264 (libx264 CPU)
          4. Build audio: TTS + clip audio mixed at the chosen volumes,
             or silence if no audio at all
          5. Mux normalized video + built audio → b['output']
        Every step has fallbacks so we never end up with an audio-only file."""
        b = self.blocks[idx]
        num = b["num"]
        text = (b.get("text","") or "").strip()
        mp = b.get("source_media","")
        if mp: mp = os.path.normpath(mp)

        def st(t,c): self._block_status(b,t,c)
        def ts(msg): self._sss(f"[#{num}] {msg}")

        if not mp or not os.path.exists(mp):
            st("No source media!", C["red"]); return
        if is_image_file(mp):
            # Fall back to the base pipeline for images (whiteboard / ken-burns
            # handled there). Master is optimised for video clips.
            b["video_only"] = False if text else True
            AdvanceEditorFrame._gw(self, idx); return

        vd = get_duration(mp)
        if vd <= 0.05:
            st("Invalid source video!", C["red"]); return

        # ── STEP 1 : Generate TTS if we have text ────────────────────────────
        # Use pre-snapshotted values (thread-safe) if available
        _rvs = getattr(self, "_render_vars_snapshot", {})
        tts_pct    = _rvs.get("m_tts_vol",  int(self._m_tts_vol.get())        if hasattr(self,"_m_tts_vol")        else 100)
        clip_pct   = _rvs.get("m_clip_vol", int(self._m_clip_vol.get())        if hasattr(self,"_m_clip_vol")       else 0)
        master_vol = _rvs.get("master_vol", self.master_vol_var.get()           if hasattr(self,"master_vol_var")   else 100)
        master_tts = _rvs.get("master_tts", self.master_tts_vol_var.get()       if hasattr(self,"master_tts_vol_var") else 100)

        # Effective per-track volumes.
        # IMPORTANT: For scenes with NO script, the Clip-volume slider (which
        # normally controls how loud the clip sits UNDER the voiceover) does
        # NOT apply — the clip's original audio always plays at 100% (times
        # the master gain). Otherwise a user setting Clip=0 for scripted
        # scenes would silently mute every non-scripted clip too.
        if text:
            eff_clip = (clip_pct/100.0) * (master_vol/100.0)
            eff_tts  = (tts_pct/100.0)  * (master_tts/100.0)
        else:
            eff_clip = 1.0 * (master_vol/100.0)
            eff_tts  = 0.0

        tts_path = None
        if text:
            st("[1/3] TTS…", C["orange"]); ts("generating voiceover")
            self._gen_audio_worker(idx)
            tts_path = b.get("tts_audio","")
            if not tts_path or not os.path.exists(tts_path):
                err = b.get("_tts_err") or "TTS failed"
                st(f"TTS failed: {err[:40]}", C["red"]); return

        # ── STEP 2 : Decide target duration ──────────────────────────────────
        # "Full clip (TTS at start)" → the CLIP's original duration wins. TTS
        # plays over the beginning of the clip; after TTS ends the rest of the
        # clip continues (with just clip audio, if any). If the clip is
        # shorter than TTS, freeze the last frame until TTS ends.
        #
        # "Clip = TTS length" → clip is trimmed (or last-frame-frozen) to
        # exactly match the TTS duration.
        _rvs2 = getattr(self, "_render_vars_snapshot", {})
        mode = _rvs2.get("script_clip_mode", "clip_eq_tts")
        if not mode:
            try: mode = self._script_clip_mode.get()
            except Exception: mode = "full_clip"
        ta = get_duration(tts_path) if tts_path else 0.0

        if not text:
            target_dur = vd
        elif mode == "clip_eq_tts" and ta > 0.05:
            target_dur = ta                     # trim/freeze video to TTS length
        elif mode == "full_clip" and ta > 0.05:
            target_dur = max(vd, ta)            # keep FULL clip; freeze if TTS longer
        else:
            target_dur = vd
        speed_factor = 1.0                      # never speed-fit — user asked for full clip

        # ── STEP 3 : Normalize video to 1920x1080 30fps H.264 (CPU, reliable) ─
        st("[2/3] Video…", C["orange"]); ts(f"normalizing to 1920x1080 (dur {target_dur:.2f}s)")
        norm_video = os.path.join(TEMP_DIR, f"m_v_{self._render_session_uid()}_{num}.mp4")
        vf_parts = []
        if speed_factor > 1.01:
            vf_parts.append(f"setpts=PTS/{speed_factor:.6f}")
        vf_parts.append("scale=1920:1080:force_original_aspect_ratio=decrease")
        vf_parts.append("pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black")
        vf_parts.append("setsar=1")
        vf_parts.append("fps=30")
        vf_parts.append("format=yuv420p")
        needs_extend = target_dur > (vd / max(speed_factor, 1.0)) + 0.05
        # "Full clip (TTS at start)": when narration outlasts the clip, LOOP the
        # clip's own video (matches the clip audio, which already loops via
        # -stream_loop below) instead of freezing on the last frame. Freezing
        # here was the actual bug — it made "Full clip" LOOK identical to
        # "Clip = TTS length" once narration was longer than the clip, because
        # the picture stopped moving at the same point either way.
        # "Clip = TTS length" keeps the original freeze/trim-to-length behaviour.
        loop_extend = needs_extend and (mode == "full_clip")
        if needs_extend and not loop_extend:
            vf_parts.append("tpad=stop_mode=clone:stop_duration=7200")
        vf = ",".join(vf_parts)
        _enc = GPU.enc_args("veryfast"); _enc_fast = GPU.enc_args("ultrafast")
        if loop_extend:
            cmd_v = ["ffmpeg","-y","-stream_loop","-1","-i",mp,"-vf",vf,
                     "-r","30","-an","-t",f"{target_dur:.3f}","-loglevel","error"]+_enc+[norm_video]
        else:
            cmd_v = ["ffmpeg","-y","-i",mp,"-vf",vf,
                     "-r","30","-an","-t",f"{target_dur:.3f}","-loglevel","error"]+_enc+[norm_video]
        _run_ff(cmd_v, timeout=900)
        if not (os.path.exists(norm_video) and get_duration(norm_video) > 0.05):
            ts(f"normalize failed — retry ({GPU.hw_encoder})")
            if loop_extend:
                cmd_v2 = ["ffmpeg","-y","-stream_loop","-1","-i",mp,"-vf",vf,
                          "-r","30","-an","-t",f"{target_dur:.3f}","-loglevel","error"]+_enc_fast+[norm_video]
            else:
                cmd_v2 = ["ffmpeg","-y","-i",mp,"-vf",vf,
                          "-r","30","-an","-t",f"{target_dur:.3f}","-loglevel","error"]+_enc_fast+[norm_video]
            _run_ff(cmd_v2, timeout=900)
        if not (os.path.exists(norm_video) and get_duration(norm_video) > 0.05):
            st("Video normalize failed!", C["red"]); return

        # ── STEP 4 : Build the audio track (TTS + clip mixed) ────────────────
        st("[3/3] Audio mix…", C["orange"])
        clip_audio_src = None
        if has_audio_stream(mp) and eff_clip > 0.001:
            clip_audio_src = os.path.join(TEMP_DIR, f"m_ca_{self._render_session_uid()}_{num}.aac")
            # stream_loop -1 in case the clip is short; then trim to target_dur
            cmd_ca = ["ffmpeg","-y","-stream_loop","-1","-i",mp,"-vn",
                      "-af",f"aresample=48000:async=1:first_pts=0,apad,atrim=0:{target_dur:.3f},asetpts=N/SR/TB",
                      "-t",f"{target_dur:.3f}",
                      "-c:a","aac","-b:a","192k","-ar","48000","-ac","2",
                      "-loglevel","error", clip_audio_src]
            _run_ff(cmd_ca, timeout=300)
            if not (os.path.exists(clip_audio_src) and get_duration(clip_audio_src) > 0.05):
                clip_audio_src = None

        has_tts  = bool(tts_path and os.path.exists(tts_path)) and eff_tts > 0.001
        has_clip = bool(clip_audio_src) and eff_clip > 0.001

        final_audio = os.path.join(TEMP_DIR, f"m_a_{self._render_session_uid()}_{num}.aac")
        if has_tts and has_clip:
            # Duck the clip's OWN audio under the narration (sidechaincompress,
            # keyed off the TTS track) — always on, Kids or Normal video —
            # instead of a flat constant-volume mix. This is what makes the
            # narration stay clearly audible over the clip's own sound instead
            # of the two fighting at fixed levels for the whole scene.
            cmd_a = ["ffmpeg","-y","-i",tts_path,"-i",clip_audio_src,
                     "-filter_complex",
                     f"[0:a]volume={eff_tts:.3f},aresample=48000:async=1:first_pts=0[t];"
                     f"[1:a]volume={eff_clip:.3f},aresample=48000:async=1:first_pts=0[c_raw];"
                     f"[t]asplit=2[t_out][t_sc];"
                     f"[c_raw][t_sc]sidechaincompress=threshold=0.05:ratio=8:attack=5:release=300:makeup=1[c_duck];"
                     f"[t_out][c_duck]amix=inputs=2:duration=longest:normalize=0[out]",
                     "-map","[out]","-t",f"{target_dur:.3f}",
                     "-c:a","aac","-b:a","192k","-ar","48000","-ac","2",
                     "-loglevel","error", final_audio]
            _run_ff(cmd_a, timeout=300)
            if not (os.path.exists(final_audio) and get_duration(final_audio) > 0.05):
                # Sidechain filter failed (rare) — fall back to the plain flat
                # mix so the scene still renders instead of hard-failing.
                ts("ducked mix failed — falling back to flat mix")
                cmd_a_fallback = ["ffmpeg","-y","-i",tts_path,"-i",clip_audio_src,
                         "-filter_complex",
                         f"[0:a]volume={eff_tts:.3f},aresample=48000:async=1:first_pts=0[t];"
                         f"[1:a]volume={eff_clip:.3f},aresample=48000:async=1:first_pts=0[c];"
                         f"[t][c]amix=inputs=2:duration=longest:normalize=0[out]",
                         "-map","[out]","-t",f"{target_dur:.3f}",
                         "-c:a","aac","-b:a","192k","-ar","48000","-ac","2",
                         "-loglevel","error", final_audio]
                _run_ff(cmd_a_fallback, timeout=300)
        elif has_tts:
            cmd_a = ["ffmpeg","-y","-i",tts_path,
                     "-af",f"volume={eff_tts:.3f},aresample=48000:async=1:first_pts=0,apad",
                     "-t",f"{target_dur:.3f}",
                     "-c:a","aac","-b:a","192k","-ar","48000","-ac","2",
                     "-loglevel","error", final_audio]
            _run_ff(cmd_a, timeout=300)
        elif has_clip:
            cmd_a = ["ffmpeg","-y","-i",clip_audio_src,
                     "-af",f"volume={eff_clip:.3f},aresample=48000:async=1:first_pts=0",
                     "-t",f"{target_dur:.3f}",
                     "-c:a","aac","-b:a","192k","-ar","48000","-ac","2",
                     "-loglevel","error", final_audio]
            _run_ff(cmd_a, timeout=300)
        else:
            # silence
            cmd_a = ["ffmpeg","-y","-f","lavfi","-i","anullsrc=r=48000:cl=stereo",
                     "-t",f"{target_dur:.3f}","-c:a","aac","-b:a","128k",
                     "-loglevel","error", final_audio]
            _run_ff(cmd_a, timeout=60)

        if not (os.path.exists(final_audio) and get_duration(final_audio) > 0.05):
            ts("audio build failed — using silence fallback")
            _run_ff(["ffmpeg","-y","-f","lavfi","-i","anullsrc=r=48000:cl=stereo",
                     "-t",f"{target_dur:.3f}","-c:a","aac","-b:a","128k",
                     "-loglevel","error", final_audio], timeout=60)

        # ── STEP 4.5 : Mix in any Bulk SFX attached to this scene ────────────
        # (uploaded + timestamp-matched via the Bulk SFX sidebar section).
        # Each SFX is delayed to its own offset within the scene, then mixed
        # in alongside the narration/clip audio built above.
        sfx_list = [s for s in (b.get("sfx") or []) if s.get("path") and os.path.exists(s["path"])]
        if sfx_list:
            ts(f"mixing {len(sfx_list)} SFX")
            sfx_audio = os.path.join(TEMP_DIR, f"m_sfx_{self._render_session_uid()}_{num}.aac")
            inputs = ["-i", final_audio]
            filter_parts = ["[0:a]anull[base]"]
            mix_labels = ["[base]"]
            for i, sfxd in enumerate(sfx_list, 1):
                inputs += ["-i", sfxd["path"]]
                delay_ms = max(0, int(float(sfxd.get("start") or 0.0) * 1000))
                filter_parts.append(f"[{i}:a]aresample=48000,adelay={delay_ms}|{delay_ms}[sfx{i}]")
                mix_labels.append(f"[sfx{i}]")
            filter_complex_sfx = (";".join(filter_parts) + ";" + "".join(mix_labels)
                                  + f"amix=inputs={len(mix_labels)}:duration=first:normalize=0[out]")
            cmd_sfx = ["ffmpeg","-y"] + inputs + [
                "-filter_complex", filter_complex_sfx,
                "-map", "[out]", "-t", f"{target_dur:.3f}",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                "-loglevel", "error", sfx_audio]
            _run_ff(cmd_sfx, timeout=300)
            if os.path.exists(sfx_audio) and get_duration(sfx_audio) > 0.05:
                final_audio = sfx_audio
            else:
                ts("SFX mix failed — continuing without SFX for this scene")

        # ── STEP 5 : Mux video + audio → final block output ──────────────────
        op = os.path.join(TEMP_DIR, f"adv_out_{self._render_session_uid()}_{num}.mp4")
        cmd_mux = ["ffmpeg","-y","-i",norm_video,"-i",final_audio,
                   "-map","0:v:0","-map","1:a:0",
                   "-c:v","copy","-c:a","copy",
                   "-shortest",
                   "-movflags","+faststart","-loglevel","error", op]
        _run_ff(cmd_mux, timeout=300)
        if not (os.path.exists(op) and get_duration(op) > 0.05):
            # Fallback: re-encode both
            cmd_mux2 = ["ffmpeg","-y","-i",norm_video,"-i",final_audio,
                        "-map","0:v:0","-map","1:a:0",
                        "-c:v","libx264","-preset","ultrafast","-crf","23","-pix_fmt","yuv420p",
                        "-c:a","aac","-b:a","192k",
                        "-shortest",
                        "-movflags","+faststart","-loglevel","error", op]
            _run_ff(cmd_mux2, timeout=600)

        if not (os.path.exists(op) and get_duration(op) > 0.05):
            st("Render failed!", C["red"]); return

        # Explicit sanity check — the WHOLE POINT of this rewrite is to make
        # sure a block never gets marked "done" if its video track is missing.
        try:
            probe = subprocess.run(["ffprobe","-v","error","-select_streams","v:0",
                "-show_entries","stream=codec_type","-of","default=noprint_wrappers=1:nokey=1", op],
                capture_output=True, text=True, timeout=15, **_NO_WINDOW)
            if not probe.stdout.strip():
                st("Video track missing in output!", C["red"]); return
        except Exception:
            pass

        b["output"] = op
        st(f"✓ Done ({format_duration(get_duration(op))})", C["green"]); ts("DONE ✓")
        try:
            img = extract_frame(op, min(1.0, get_duration(op)/2)); img.thumbnail((72,38), Image.LANCZOS)
            tk = ImageTk.PhotoImage(img.convert("RGB")); b["_ttk"] = tk
            self.after(0, lambda: b["thumb_label"].configure(image=tk, text=""))
        except Exception: pass

    # ────────────────────────────────────────────────────────────────────
    # Helper: verify a file actually has a decodable video stream. Used to
    # catch the silent "audio-only output" bug — some ffmpeg commands can
    # return success (rc=0, non-empty file) but drop the video track (bad
    # encoder, filter graph mismatch, etc). Every merge step now runs this
    # check and either recovers with a CPU fallback or aborts with a clear
    # message rather than propagating a broken file downstream.
    # ────────────────────────────────────────────────────────────────────
    def _has_video_track(self, path):
        if not (path and os.path.exists(path)): return False
        try:
            r = subprocess.run(["ffprobe","-v","error","-select_streams","v:0",
                "-show_entries","stream=codec_type",
                "-of","default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, timeout=15, **_NO_WINDOW)
            return bool(r.stdout.strip())
        except Exception:
            return False

    def _apply_base_logo_to_file(self, path):
        """Composite the base's PRIMARY logo (Logo 1 with Preview & Position)
        onto the given video file. Master's custom _gw skips per-scene logo
        baking, so this is where Logo 1 finally lands in the pipeline.
        Uses libx264 CPU + verifies video track before overwriting `path`."""
        try: logo_p = self.logo_path_var.get().strip()
        except Exception: logo_p = ""
        if not logo_p or not os.path.exists(logo_p): return False
        if not (path and os.path.exists(path)): return False

        # If the user cropped the logo, prefer that cropped PNG.
        effective = logo_p
        try:
            cropped_ok = (getattr(self, "logo_cropped_pil", None) is not None and
                          getattr(self, "_logo_cropped_for_path", None) == logo_p)
            if cropped_ok:
                ctp = os.path.join(TEMP_DIR, f"m_base_logo_cropped_{self._render_session_uid()}.png")
                self.logo_cropped_pil.save(ctp); effective = ctp
        except Exception: pass

        try: vw, vh = get_resolution(path)
        except Exception: vw, vh = 1920, 1080
        if not vw or not vh: vw, vh = 1920, 1080

        # Position + size: prefer fractional coords from Preview & Position;
        # fall back to anchor + margin, then to bottom-right default.
        pct_x = getattr(self, "_logo_pct_x", None)
        pct_y = getattr(self, "_logo_pct_y", None)
        pct_size = getattr(self, "_logo_pct_size", None)
        if pct_size and pct_size > 0:
            lw = max(8, int(round(vw * pct_size)))
        else:
            try: lw = max(8, int(self.logo_size_var.get()))
            except Exception: lw = 120
        lh = lw
        if pct_x is not None and pct_y is not None:
            lx, ly = int(round(vw * pct_x)), int(round(vh * pct_y))
        else:
            try:
                anchor = self.logo_anchor_var.get()
                mx = self.logo_mx_var.get(); my = self.logo_my_var.get()
                lx, ly = calc_logo_xy(anchor, mx, my, lw, vw, vh)
            except Exception:
                lx, ly = vw - lw - 20, vh - lh - 20
        lx = max(0, min(lx, max(0, vw - lw)))
        ly = max(0, min(ly, max(0, vh - lh)))
        try: opa = float(self.logo_opacity_var.get()) / 100.0
        except Exception: opa = 1.0
        opa = max(0.0, min(1.0, opa))

        # Even dimensions required by yuv420p — round up.
        if lw % 2: lw += 1
        if lh % 2: lh += 1

        tmp = path + ".base_logo.mp4"
        # Attempt 1: filter_complex with alpha handling
        fc = (f"[1:v]scale={lw}:{lh}:flags=lanczos,format=rgba,colorchannelmixer=aa={opa:.3f}[lg];"
              f"[0:v][lg]overlay=x={lx}:y={ly}:format=auto:shortest=1[outv]")
        cmd = ["ffmpeg","-y","-i",path,"-i",effective,
               "-filter_complex", fc,
               "-map","[outv]","-map","0:a?",
               "-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p",
               "-c:a","aac","-b:a","192k","-movflags","+faststart",
               tmp]
        result = _run_ff(cmd, timeout=3600)
        # Log any ffmpeg stderr so the "encode returned no video" mystery is
        # solvable next time. Print to console (visible in terminal) and to
        # the substatus line (visible in the UI).
        if result is not None and hasattr(result,"stderr") and result.stderr:
            err_snip = str(result.stderr)[-300:]
            print(f"[BASE LOGO ffmpeg stderr] {err_snip}")
        if not (os.path.exists(tmp) and get_duration(tmp) > 0.1 and self._has_video_track(tmp)):
            # Attempt 2: simpler chain — skip alpha manipulation, just overlay
            try:
                if os.path.exists(tmp): os.remove(tmp)
            except Exception: pass
            self._sss("primary logo attempt 1 failed → retry with simple overlay")
            fc2 = f"[0:v][1:v]overlay=x={lx}:y={ly}:format=auto:shortest=1[outv]"
            cmd2 = ["ffmpeg","-y","-i",path,"-i",effective,
                    "-filter_complex", fc2,
                    "-map","[outv]","-map","0:a?",
                    "-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p",
                    "-c:a","aac","-b:a","192k","-movflags","+faststart",
                    tmp]
            result2 = _run_ff(cmd2, timeout=3600)
            if result2 is not None and hasattr(result2,"stderr") and result2.stderr:
                err_snip = str(result2.stderr)[-300:]
                print(f"[BASE LOGO ffmpeg stderr #2] {err_snip}")
        if not (os.path.exists(tmp) and get_duration(tmp) > 0.1 and self._has_video_track(tmp)):
            # Attempt 3: pre-scale the logo image, then overlay with -vf
            try:
                if os.path.exists(tmp): os.remove(tmp)
            except Exception: pass
            self._sss("primary logo attempt 2 failed → retry with pre-scaled logo")
            try:
                pre_logo = os.path.join(TEMP_DIR, f"m_base_logo_pre_{self._render_session_uid()}.png")
                img = Image.open(effective).convert("RGBA")
                img = img.resize((lw, lh), Image.LANCZOS)
                if opa < 1.0:
                    alpha = img.split()[-1].point(lambda p: int(p * opa))
                    img.putalpha(alpha)
                img.save(pre_logo)
                fc3 = f"[0:v][1:v]overlay=x={lx}:y={ly}:format=auto:shortest=1[outv]"
                cmd3 = ["ffmpeg","-y","-i",path,"-i",pre_logo,
                        "-filter_complex", fc3,
                        "-map","[outv]","-map","0:a?",
                        "-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p",
                        "-c:a","aac","-b:a","192k","-movflags","+faststart",
                        tmp]
                result3 = _run_ff(cmd3, timeout=3600)
                if result3 is not None and hasattr(result3,"stderr") and result3.stderr:
                    err_snip = str(result3.stderr)[-300:]
                    print(f"[BASE LOGO ffmpeg stderr #3] {err_snip}")
            except Exception as e:
                print(f"[BASE LOGO pre-scale error] {e}")
        # Final check
        if os.path.exists(tmp) and get_duration(tmp) > 0.1 and self._has_video_track(tmp):
            try:
                shutil.move(tmp, path); return True
            except Exception:
                try: shutil.copy2(tmp, path); os.remove(tmp); return True
                except Exception: return False
        try:
            if os.path.exists(tmp): os.remove(tmp)
        except Exception: pass
        return False

    def _mw(self, clips, sp):
        """Merge pipeline — every step verifies video track presence and falls
        back to CPU libx264 if hardware encoders drop the video."""
        if getattr(self, "_cancelled", False): return
        step = self._render_step  # step-progress helper (installed by _render_all)

        # ═══════════════════════════════════════════════════════════════
        # STEP: Normalize all clips to 1920×1080 30fps H.264
        # ═══════════════════════════════════════════════════════════════
        step(4, "Normalizing clips…")
        norm = []
        total_c = len([c for c in clips if c and os.path.exists(c)])
        idx = 0
        for i, c in enumerate(clips):
            if getattr(self, "_cancelled", False): return
            if not (c and os.path.exists(c)): continue
            idx += 1
            step(4, f"Normalizing clip {idx}/{total_c}…", sub=(idx-1)/max(total_c,1))
            n = os.path.join(TEMP_DIR, f"mn_{self._render_session_uid()}_{i}.mp4")
            # If clip already matches target resolution & fps, skip re-encoding
            try:
                cw, ch = get_resolution(c)
                if cw == 1920 and ch == 1080:
                    norm.append(c)
                    continue
            except Exception:
                pass
            cd = max(0.1, get_duration(c) or 5.0)
            cmd = ["ffmpeg","-y","-fflags","+genpts","-i",c,
                   "-vf","scale=1920:1080:force_original_aspect_ratio=decrease,"
                         "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30,format=yuv420p",
                   "-af","aresample=48000:async=1:first_pts=0,apad,atrim=0:"+f"{cd:.3f}"] + GPU.enc_args("fast") + [
                   "-profile:v","main","-level","4.0","-g","30","-keyint_min","30",
                   "-vsync","cfr","-r","30",
                   "-c:a","aac","-b:a","192k","-ar","48000","-ac","2",
                   "-t",f"{cd:.3f}","-movflags","+faststart",
                   "-loglevel","error",n]
            
            def _norm_prog(frac, label, fr, fps, spd, _i=idx, _tc=total_c):
                overall = (_i - 1 + frac) / max(_tc, 1)
                step(4, f"Normalizing clip {_i}/{_tc}: Frame {fr} ({int(frac*100)}%) • {fps} fps", sub=overall)
            _run_ff_live(cmd, duration=cd, on_progress=_norm_prog, timeout=1800)
            if getattr(self, "_cancelled", False): return
            if not self._has_video_track(n):
                # retry: CPU libx264 re-encode
                nn = os.path.join(TEMP_DIR, f"mn_{self._render_session_uid()}_{i}_cpu.mp4")
                cmd_cpu = ["ffmpeg","-y","-fflags","+genpts","-i",c,
                           "-vf","scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30,format=yuv420p",
                           "-c:v","libx264","-preset","veryfast","-crf","20",
                           "-c:a","aac","-b:a","192k","-ar","48000","-ac","2",
                           "-t",f"{cd:.3f}","-movflags","+faststart","-loglevel","error",nn]
                _run_ff_live(cmd_cpu, duration=cd, on_progress=_norm_prog, timeout=1800)
                if getattr(self, "_cancelled", False): return
                if self._has_video_track(nn): n = nn
                else: n = c    # last-resort: use original
            norm.append(n)

        if getattr(self, "_cancelled", False): return
        if not norm:
            self._ss("No clips to merge!", C["red"]); return

        # ═══════════════════════════════════════════════════════════════
        # STEP: Concat / apply transitions
        # ═══════════════════════════════════════════════════════════════
        merged = os.path.join(TEMP_DIR, f"master_out_{self._render_session_uid()}.mp4")
        use_tr = bool(getattr(self,"_m_tr_on",None) and self._m_tr_on.get())
        tr_types = [t for t,v in (getattr(self,"_m_tr_vars",{}) or {}).items() if v.get()]
        tr_dur = max(0.2, float(getattr(self,"_m_tr_dur",None) and self._m_tr_dur.get() or 0.5))
        lst = os.path.join(TEMP_DIR, f"m_cat_{self._render_session_uid()}.txt")
        if use_tr and tr_types and len(norm)>1:
            step(5, f"Applying {len(tr_types)} random transitions to {len(norm)} clips…")
            r = _merge_with_transitions(norm, tr_types, tr_dur, merged, logf=lambda m: self._sss(m))
            # If transitions failed entirely, fall back to plain concat so the
            # user still gets an output (better a video without transitions
            # than no video at all).
            if not r or not (os.path.exists(merged) and self._has_video_track(merged)):
                if getattr(self, "_cancelled", False): return
                self._sss("⚠️ All transition strategies failed — falling back to plain concat (no transitions)")
                step(5, "Transitions failed → plain concat fallback")
                with open(lst,"w", encoding="utf-8") as f:
                    for c in norm: f.write(f"file '{os.path.abspath(c).replace(os.sep, '/')}'\n")
                _run_ff(["ffmpeg","-y","-f","concat","-safe","0","-i",lst,"-c","copy",
                         "-movflags","+faststart","-loglevel","error",merged], timeout=3600)
        else:
            step(5, f"Concatenating {len(norm)} clips…")
            with open(lst,"w", encoding="utf-8") as f:
                for c in norm: f.write(f"file '{os.path.abspath(c).replace(os.sep, '/')}'\n")
            _run_ff(["ffmpeg","-y","-f","concat","-safe","0","-i",lst,"-c","copy",
                     "-movflags","+faststart","-loglevel","error",merged], timeout=3600)
            # If concat -c copy dropped the video (mismatched streams), retry
            # with a re-encode of ALL clips concatenated via filter_complex.
            if not self._has_video_track(merged):
                if getattr(self, "_cancelled", False): return
                self._sss("concat lost video — retry with filter_complex re-encode")
                fc_parts=[]; inputs=[]
                for j, c in enumerate(norm):
                    inputs+=["-i", c]
                    fc_parts.append(f"[{j}:v:0][{j}:a:0]")
                fc = "".join(fc_parts) + f"concat=n={len(norm)}:v=1:a=1[v][a]"
                _run_ff(["ffmpeg","-y"]+inputs+["-filter_complex",fc,"-map","[v]","-map","[a]",
                         "-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p",
                         "-c:a","aac","-b:a","192k","-movflags","+faststart",
                         "-loglevel","error",merged], timeout=3600)

        if getattr(self, "_cancelled", False): return
        if not self._has_video_track(merged):
            self._ss("Merge failed — video track missing after concat!", C["red"]); return

        # ═══════════════════════════════════════════════════════════════
        # STEP: BGM mix
        # ═══════════════════════════════════════════════════════════════
        final = sp
        bgm_on = bool(getattr(self,"bgm_enabled_var",None) and self.bgm_enabled_var.get())
        bgm_path = self.bgm_var.get() if hasattr(self,"bgm_var") else ""
        if bgm_on and bgm_path and os.path.exists(bgm_path):
            step(6, "Mixing background music…")
            bgm_vol = 0.15
            try: bgm_vol = float(self.bgm_vol_var.get())
            except: pass
            vdur = get_duration(merged)
            bgm_dur = get_duration(bgm_path)
            bgm_src = bgm_path
            loop_on = bool(getattr(self,"bgm_loop_var",None) and self.bgm_loop_var.get())
            xfade_on = bool(getattr(self,"bgm_xfade_var",None) and self.bgm_xfade_var.get())

            if loop_on and bgm_dur > 0.1 and bgm_dur < vdur - 0.5:
                self._sss(f"BGM loop: extending {bgm_dur:.1f}s → {vdur:.1f}s target")
                loop_ok = False
                if xfade_on:
                    try:
                        looped_xf = os.path.join(TEMP_DIR, f"m_bgm_xfade_lp_{self._render_session_uid()}.m4a")
                        xf = getattr(self, "_make_bgm_xfade_loop", None)
                        r = xf(bgm_path, vdur + 1.0, 1.5) if xf else None
                        if (r and r != bgm_path and os.path.exists(r)
                                and get_duration(r) > bgm_dur + 0.5):
                            bgm_src = r; loop_ok = True
                            self._sss(f"BGM loop: xfade extended to {get_duration(r):.1f}s ✓")
                        else:
                            self._sss("BGM loop: xfade path fell through")
                    except Exception as e:
                        self._sss(f"BGM loop: xfade error: {e}")

                if not loop_ok:
                    looped_sl = os.path.join(TEMP_DIR, f"m_bgm_streamloop_{self._render_session_uid()}.m4a")
                    try:
                        cmd_sl = ["ffmpeg","-y","-stream_loop","-1","-i", bgm_path,
                                  "-t", f"{vdur + 1.0:.3f}",
                                  "-c:a","aac","-b:a","192k","-ar","48000","-ac","2",
                                  "-loglevel","error", looped_sl]
                        _run_ff(cmd_sl, timeout=900)
                        if (os.path.exists(looped_sl)
                                and get_duration(looped_sl) > bgm_dur + 0.5):
                            bgm_src = looped_sl; loop_ok = True
                            self._sss(f"BGM loop: stream_loop extended to {get_duration(looped_sl):.1f}s ✓")
                        else:
                            self._sss("BGM loop: stream_loop also failed — will play once then silence")
                    except Exception as e:
                        self._sss(f"BGM loop: stream_loop error: {e}")

            is_kids = bool(getattr(self, "_video_type_var", None)
                          and self._video_type_var.get() == "Kids Video")
            duck_threshold, duck_ratio = (0.03, 10) if is_kids else (0.08, 4)
            self._sss(f"BGM ducking ON ({'Kids' if is_kids else 'Normal'} — "
                     f"threshold={duck_threshold}, ratio={duck_ratio})")
            filter_complex = (
                f"[1:a]aresample=48000,volume={bgm_vol:.3f},apad=whole_dur={vdur:.3f}[bgm];"
                f"[0:a]asplit=2[voice][sc];"
                f"[bgm][sc]sidechaincompress=threshold={duck_threshold}:ratio={duck_ratio}:attack=5:release=300:makeup=1[bgmduck];"
                f"[voice][bgmduck]amix=inputs=2:duration=first:normalize=0[a]"
            )

            def _bgm_prog(frac, label, fr, fps, spd):
                step(6, f"Mixing background music: Frame {fr} ({int(frac*100)}%) • {fps} fps • {spd}", sub=frac)

            cmd_bgm = ["ffmpeg","-y","-i",merged,"-i",bgm_src,
                       "-filter_complex",filter_complex,
                       "-map","0:v","-map","[a]","-c:v","copy","-c:a","aac","-b:a","192k",
                       "-movflags","+faststart","-loglevel","error",final]
            _run_ff_live(cmd_bgm, duration=vdur, on_progress=_bgm_prog, timeout=3600)
            if getattr(self, "_cancelled", False): return
            if not self._has_video_track(final):
                self._sss("BGM step lost video — re-encoding with CPU libx264")
                cmd_bgm_cpu = ["ffmpeg","-y","-i",merged,"-i",bgm_src,
                               "-filter_complex",filter_complex,
                               "-map","0:v","-map","[a]",
                               "-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p",
                               "-c:a","aac","-b:a","192k","-movflags","+faststart",
                               "-loglevel","error",final]
                _run_ff_live(cmd_bgm_cpu, duration=vdur, on_progress=_bgm_prog, timeout=3600)
        else:
            step(6, "Skipping BGM (not enabled)")
            shutil.copy2(merged, final)

        if getattr(self, "_cancelled", False): return

        # ═══════════════════════════════════════════════════════════════
        # STEP: Output resolution scale
        # ═══════════════════════════════════════════════════════════════
        step(7, "Finalizing output resolution…")
        def _res_prog(frac, label, fr, fps, spd):
            step(7, f"Finalizing output: Frame {fr} ({int(frac*100)}%) • {fps} fps • {spd}", sub=frac)
        _finalize_output_resolution(final, log=lambda m: self._sss(m), on_progress=_res_prog)
        if getattr(self, "_cancelled", False): return
        if not self._has_video_track(final):
            self._ss("Finalize dropped video — check GPU encoder settings", C["red"]); return

        # ═══════════════════════════════════════════════════════════════
        # STEP: ALL logos in one final pass (base Logo 1 + master + extra)
        # ═══════════════════════════════════════════════════════════════
        step(8, "Overlaying ALL logos in one pass…")
        try:
            self._apply_all_logos_final(final)
        except Exception as e:
            self._sss(f"[FINAL LOGO] {e}")
            print(f"[FINAL LOGO error] {e}")

        if getattr(self, "_cancelled", False): return

        self._sp(1.0)
        if os.path.exists(final) and self._has_video_track(final):
            step(9, f"✓ Done! {format_duration(get_duration(final))} → {os.path.basename(final)}", finished=True)
            self._ss(f"✓ Done! {format_duration(get_duration(final))} → {os.path.basename(final)}", C["green"])
        else:
            self._ss("Save failed — video track missing in final output!", C["red"])

    def _apply_all_logos_final(self, path):
        """Single-pass, at-the-very-end logo overlay. Collects EVERY logo the
        user has configured (base Logo 1, Master's _master_logos list, and
        base's Add-Another-Logo extras), pre-processes each one with PIL (so
        ffmpeg only has to do a raw overlay), and composites them all in one
        ffmpeg call. Runs on CPU libx264 for reliability."""
        if not (path and os.path.exists(path)):
            self._sss("[FINAL LOGO] source video missing, skipping")
            return False

        try: vw, vh = get_resolution(path)
        except Exception: vw, vh = 1920, 1080
        if not vw or not vh: vw, vh = 1920, 1080

        # Build a single unified list of (pre-processed PNG path, x, y).
        # All alpha/opacity handling is done in PIL up front — ffmpeg's filter
        # graph gets only "overlay this ready-made PNG here" instructions,
        # which is as bulletproof as it gets.
        logos_to_apply = []

        # ── Base Logo 1 (Preview & Position) ──
        try:
            logo_p = (self.logo_path_var.get() or "").strip()
        except Exception:
            logo_p = ""
        base_enabled = True
        try:
            if hasattr(self, "logo_enabled_var") and not self.logo_enabled_var.get():
                base_enabled = False
        except Exception: pass
        if base_enabled and logo_p and os.path.exists(logo_p):
            # Cropped PIL takes priority if it matches current file
            try:
                cropped_ok = (getattr(self, "logo_cropped_pil", None) is not None and
                              getattr(self, "_logo_cropped_for_path", None) == logo_p)
                img = self.logo_cropped_pil.copy() if cropped_ok else Image.open(logo_p).convert("RGBA")
            except Exception as e:
                self._sss(f"[FINAL LOGO] base logo open failed: {e}"); img = None
            if img is not None:
                # size
                pct_size = getattr(self, "_logo_pct_size", None)
                if pct_size and pct_size > 0:
                    lw = max(8, int(round(vw * pct_size)))
                else:
                    try: lw = max(8, int(self.logo_size_var.get()))
                    except Exception: lw = 120
                lh = lw
                if lw % 2: lw += 1
                if lh % 2: lh += 1
                # position
                pct_x = getattr(self, "_logo_pct_x", None)
                pct_y = getattr(self, "_logo_pct_y", None)
                if pct_x is not None and pct_y is not None:
                    lx, ly = int(round(vw * pct_x)), int(round(vh * pct_y))
                else:
                    try:
                        anchor = self.logo_anchor_var.get()
                        mx = self.logo_mx_var.get(); my = self.logo_my_var.get()
                        lx, ly = calc_logo_xy(anchor, mx, my, lw, vw, vh)
                    except Exception:
                        lx, ly = vw - lw - 20, vh - lh - 20
                lx = max(0, min(lx, max(0, vw - lw)))
                ly = max(0, min(ly, max(0, vh - lh)))
                print(f"[LOGO-DEBUG] base-logo1 path={os.path.basename(logo_p)} "
                      f"pct_x={pct_x} pct_y={pct_y} pct_size={pct_size} "
                      f"final_canvas={vw}x{vh} sz={lw} -> lx={lx} ly={ly}")
                # opacity
                try: opa = max(0.0, min(1.0, float(self.logo_opacity_var.get()) / 100.0))
                except Exception: opa = 1.0
                # pre-process → PNG
                try:
                    img = img.convert("RGBA").resize((lw, lh), Image.LANCZOS)
                    if opa < 0.999:
                        a = img.split()[-1].point(lambda p, o=opa: int(p * o))
                        img.putalpha(a)
                    p_out = os.path.join(TEMP_DIR, f"final_logo_1_{self._render_session_uid()}.png")
                    img.save(p_out, "PNG")
                    logos_to_apply.append((p_out, lx, ly, lw))
                    self._sss(f"[FINAL LOGO] queued base Logo 1 @ ({lx},{ly}) size {lw}")
                except Exception as e:
                    self._sss(f"[FINAL LOGO] base preprocess failed: {e}")

        # ── Master's own logos (_master_logos list, fractional coords) ──
        for i, lg in enumerate(getattr(self, "_master_logos", None) or []):
            lp = lg.get("path")
            if not (lp and os.path.exists(lp)): continue
            try:
                sx = max(8, int(round(float(lg.get("size", 0.08)) * vw)))
                if sx % 2: sx += 1
                lx = max(0, min(int(round(float(lg.get("x", 0.02)) * vw)), max(0, vw - sx)))
                ly = max(0, min(int(round(float(lg.get("y", 0.02)) * vh)), max(0, vh - sx)))
                opa = max(0.0, min(1.0, float(lg.get("opacity", 1.0))))
                img = Image.open(lp).convert("RGBA").resize((sx, sx), Image.LANCZOS)
                if opa < 0.999:
                    a = img.split()[-1].point(lambda p, o=opa: int(p * o))
                    img.putalpha(a)
                p_out = os.path.join(TEMP_DIR, f"final_logo_m{i}_{self._render_session_uid()}.png")
                img.save(p_out, "PNG")
                logos_to_apply.append((p_out, lx, ly, sx))
                self._sss(f"[FINAL LOGO] queued master logo #{i+1}")
            except Exception as e:
                self._sss(f"[FINAL LOGO] master #{i+1} skipped: {e}")

        # ── Extra logos (Logo 2, 3… added via base's "Add Another Logo") ──
        for i, lg in enumerate(getattr(self, "_extra_logos", None) or []):
            lp = lg.get("path")
            if not (lp and os.path.exists(lp)): continue
            try:
                # BUG FIX: this used to always read lg["size_var"] (a raw pixel
                # value calibrated against the PREVIEW canvas, e.g. 1280x720)
                # regardless of the actual final resolution. At 2K/4K that
                # pixel count is tiny relative to the real frame, so the logo
                # rendered far smaller than intended — which visually reads as
                # "wrong position" even though x,y itself was computed right.
                # pct_size (fraction of frame width) is resolution-safe, same
                # as Logo 1 above — use it first, exactly like Logo 1 does.
                pct_sz = lg.get("pct_size")
                if pct_sz and pct_sz > 0:
                    sz = max(8, int(round(vw * pct_sz)))
                else:
                    sz = max(8, int(lg["size_var"].get()))
                if sz % 2: sz += 1
                try: opa = max(0.0, min(1.0, int(lg["opacity_var"].get()) / 100.0))
                except Exception: opa = 1.0
                pct_x, pct_y = lg.get("pct_x"), lg.get("pct_y")
                if pct_x is not None and pct_y is not None:
                    lx, ly = int(pct_x * vw), int(pct_y * vh)
                else:
                    try:
                        anchor = lg["anchor_var"].get()
                        lx, ly = calc_logo_xy(anchor, 20, 20, sz, vw, vh)
                    except Exception:
                        lx, ly = vw - sz - 20, vh - sz - 20
                lx = max(0, min(lx, max(0, vw - sz)))
                ly = max(0, min(ly, max(0, vh - sz)))
                print(f"[LOGO-DEBUG] extra#{i+2} path={os.path.basename(lp)} "
                      f"pct_x={pct_x} pct_y={pct_y} pct_size={pct_sz} "
                      f"final_canvas={vw}x{vh} sz={sz} -> lx={lx} ly={ly}")
                img = Image.open(lp).convert("RGBA").resize((sz, sz), Image.LANCZOS)
                if opa < 0.999:
                    a = img.split()[-1].point(lambda p, o=opa: int(p * o))
                    img.putalpha(a)
                p_out = os.path.join(TEMP_DIR, f"final_logo_x{i}_{self._render_session_uid()}.png")
                img.save(p_out, "PNG")
                logos_to_apply.append((p_out, lx, ly, sz))
                self._sss(f"[FINAL LOGO] queued extra Logo {i+2}")
            except Exception as e:
                self._sss(f"[FINAL LOGO] extra #{i+2} skipped: {e}")

        if not logos_to_apply:
            self._sss("[FINAL LOGO] no logos configured — skipping")
            return False

        # ── Anti-overlap safeguard ─────────────────────────────────
        # If two or more logos resolve to (nearly) the same spot they stack
        # and only the top one is visible — which reads as "I picked 2 logos
        # but only 1 shows". Spread any colliding logo to the next free corner
        # so every chosen logo is actually seen. The first logo keeps its spot;
        # only genuine collisions get nudged.
        def _corner_slots(s):
            m = 20
            return [(vw-s-m, vh-s-m), (m, vh-s-m), (vw-s-m, m), (m, m),
                    ((vw-s)//2, vh-s-m), ((vw-s)//2, m),
                    (vw-s-m, (vh-s)//2), (m, (vh-s)//2)]
        _placed = []
        _spread = []
        def _clash(x, y, s):
            for (px, py, ps) in _placed:
                if abs(x-px) < max(s, ps)*0.5 and abs(y-py) < max(s, ps)*0.5:
                    return True
            return False
        for (_p, _lx, _ly, _s) in logos_to_apply:
            if _clash(_lx, _ly, _s):
                for (cx, cy) in _corner_slots(_s):
                    cx = max(0, min(cx, max(0, vw-_s)))
                    cy = max(0, min(cy, max(0, vh-_s)))
                    if not _clash(cx, cy, _s):
                        print(f"[LOGO-DEBUG] anti-overlap moved "
                              f"{os.path.basename(_p)} ({_lx},{_ly})->({cx},{cy})")
                        _lx, _ly = cx, cy
                        break
            _placed.append((_lx, _ly, _s))
            _spread.append((_p, _lx, _ly, _s))
        logos_to_apply = _spread

        # ── Single ffmpeg pass: minimal command, one overlay per logo ──
        inputs = ["-i", path]
        for lp, _, _, _ in logos_to_apply:
            inputs += ["-i", lp]
        # Chain overlays: [0:v][1:v]overlay=x1:y1[o1]; [o1][2:v]overlay=x2:y2[o2]; …
        fc_parts = []; prev = "0:v"
        for i, (_, lx, ly, _) in enumerate(logos_to_apply, start=1):
            out_tag = f"[o{i}]"
            fc_parts.append(f"[{prev}][{i}:v]overlay={lx}:{ly}{out_tag}")
            prev = f"o{i}"
        fc = ";".join(fc_parts)
        tmp = path + ".alllogo.mp4"
        vdur = max(0.1, get_duration(path) or 5.0)
        cmd = ["ffmpeg", "-y"] + inputs + [
            "-filter_complex", fc,
            "-map", f"[{prev}]", "-map", "0:a?",
            "-t", f"{vdur:.3f}",
            ] + GPU.enc_args("veryfast") + ["-pix_fmt", "yuv420p",
            "-c:a", "copy",       # audio was already finalized — just copy
            "-movflags", "+faststart",
            "-shortest",
            tmp]
        self._sss(f"[FINAL LOGO] compositing {len(logos_to_apply)} logo(s)…")
        
        def _logo_prog(frac, label, fr, fps, spd):
            self._render_step(8, f"Overlaying logos: Frame {fr} ({int(frac*100)}%) • {fps} fps • {spd}", sub=frac)
            
        result = _run_ff_live(cmd, duration=vdur, on_progress=_logo_prog, timeout=3600)
        if result is not None and hasattr(result, "stderr") and result.stderr:
            err = str(result.stderr)[-400:]
            if err.strip():
                print(f"[FINAL LOGO ffmpeg stderr] {err}")

        if os.path.exists(tmp) and get_duration(tmp) > 0.1 and self._has_video_track(tmp):
            try:
                shutil.move(tmp, path)
                self._sss(f"[FINAL LOGO] ✓ {len(logos_to_apply)} logo(s) applied")
                return True
            except Exception:
                try:
                    shutil.copy2(tmp, path); os.remove(tmp)
                    self._sss(f"[FINAL LOGO] ✓ {len(logos_to_apply)} logo(s) applied (copy)")
                    return True
                except Exception as e:
                    self._sss(f"[FINAL LOGO] file replace failed: {e}"); return False

        # If we get here, the ffmpeg call failed. Retry once with re-encoded
        # audio in case "-c:a copy" was the culprit.
        self._sss("[FINAL LOGO] first pass failed — retry re-encoding audio")
        try:
            if os.path.exists(tmp): os.remove(tmp)
        except Exception: pass
        cmd2 = ["ffmpeg", "-y"] + inputs + [
            "-filter_complex", fc,
            "-map", f"[{prev}]", "-map", "0:a?",
            "-t", f"{vdur:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            "-shortest",
            tmp]
        result2 = _run_ff_live(cmd2, duration=vdur, on_progress=_logo_prog, timeout=3600)
        if result2 is not None and hasattr(result2, "stderr") and result2.stderr:
            print(f"[FINAL LOGO stderr #2] {str(result2.stderr)[-400:]}")

        if os.path.exists(tmp) and get_duration(tmp) > 0.1 and self._has_video_track(tmp):
            try:
                shutil.move(tmp, path)
                self._sss(f"[FINAL LOGO] ✓ applied on retry")
                return True
            except Exception:
                try: shutil.copy2(tmp, path); os.remove(tmp); return True
                except Exception: return False

        self._sss("[FINAL LOGO] ✗ FAILED — see terminal for ffmpeg errors")
        try:
            if os.path.exists(tmp): os.remove(tmp)
        except Exception: pass
        return False

    def _tab_help_title(self): return "👑 Master"
    def _tab_help_steps(self):
        return ["Upload clips (Scene_1_xxx, Scene_2_xxx…). Auto-sorted by number.",
                "Write script text per scene → TTS voiceover generated automatically.",
                "No script = clip plays with its own audio. 100 clips + 20 scripts = 20 get voice.",
                "🔊 Volume: Script audio 100 + Clip 0 = only voiceover. 50+50 = both.",
                "🔀 Transitions: tick types, they apply randomly between scenes.",
                "🏷 Logo: add one or more logos (bottom-right default).",
                "🎵 BGM: select file or generate with ElevenLabs. Set volume + loop.",
                "Click MERGE → voiceover + transitions + logo + BGM → final output."]


# ════════════════════════════════════════════════════════════════════
# STORIES TAB — MasterEditorFrame + auto-caption generation from clip
# audio via Whisper (openai-whisper). Duplicate of Master with an extra
# "Create Captions" button that transcribes video-only clips.
# ════════════════════════════════════════════════════════════════════

# Whisper's supported language codes → human names. Sorted so the most
# common languages the user's actually likely to want appear at the top.
_WHISPER_LANGUAGES = [
    ("auto", "Auto-detect"),
    ("en", "English"),
    ("de", "German (Deutsch)"),
    ("hi", "Hindi (हिन्दी)"),
    ("es", "Spanish (Español)"),
    ("fr", "French (Français)"),
    ("it", "Italian (Italiano)"),
    ("pt", "Portuguese (Português)"),
    ("ru", "Russian (Русский)"),
    ("ja", "Japanese (日本語)"),
    ("zh", "Chinese (中文)"),
    ("ko", "Korean (한국어)"),
    ("ar", "Arabic (العربية)"),
    ("tr", "Turkish (Türkçe)"),
    ("nl", "Dutch (Nederlands)"),
    ("pl", "Polish (Polski)"),
    ("sv", "Swedish (Svenska)"),
    ("id", "Indonesian"),
    ("vi", "Vietnamese"),
    ("th", "Thai"),
    ("uk", "Ukrainian"),
    ("cs", "Czech"),
    ("ro", "Romanian"),
    ("el", "Greek"),
    ("bn", "Bengali"),
    ("ur", "Urdu"),
    ("ta", "Tamil"),
    ("te", "Telugu"),
    ("mr", "Marathi"),
    ("gu", "Gujarati"),
]

# Whisper model catalog — size vs. rough disk footprint vs. quality.
_WHISPER_MODELS = [
    ("tiny",     "Tiny",     "~75 MB",  "Fastest • decent for clear speech"),
    ("base",     "Base",     "~150 MB", "Balanced • good for most cases (recommended)"),
    ("small",    "Small",    "~500 MB", "Better accuracy • slower"),
    ("medium",   "Medium",   "~1.5 GB", "Very good accuracy • much slower"),
    ("large-v3", "Large v3", "~3 GB",   "Best accuracy • needs a decent GPU/CPU"),
]

def _whisper_cache_root():
    """Jahan faster-whisper models cache hote hain."""
    import whisper_engine
    return whisper_engine.cache_root()

def _whisper_model_is_downloaded(model_size):
    """Model pehle se download hai ya nahi."""
    import whisper_engine
    return whisper_engine.model_is_downloaded(model_size)



def _whisper_import_hint(e) -> str:
    """ImportError message ke basis pe user ko actionable fix batao."""
    el = str(e).lower()
    if "dll load failed" in el:
        return ("\n\nYeh PC pe Microsoft Visual C++ Runtime missing hai.\n"
                "Fix (2 min): yeh install karke app restart karo:\n"
                "https://aka.ms/vc/17/release/vc_redist.x64.exe")
    if "no module named" in el:
        return "\n\nBuild issue — naye installer se update karo."
    return ""

import contextlib as _contextlib

@_contextlib.contextmanager
def _safe_std_streams():
    """Whisper (and its tqdm progress bars / warnings) write straight to
    sys.stdout / sys.stderr. When the tool is launched WITHOUT a console
    (pythonw, the .bat launcher, a frozen EXE) those are None, and any write
    raises: 'NoneType' object has no attribute 'write'.
    Swap in throwaway buffers for the duration of the call."""
    import io
    o, e = sys.stdout, sys.stderr
    try:
        if sys.stdout is None: sys.stdout = io.StringIO()
        if sys.stderr is None: sys.stderr = io.StringIO()
        yield
    finally:
        sys.stdout, sys.stderr = o, e


class StoriesEditorFrame(MasterEditorFrame):
    """Duplicate of the Master tab, plus a 'Create Captions' feature that
    transcribes video-only clips (using local Whisper), so those clips can
    have captions burned in during render without the user typing anything.

    All the base Master features (single 🎬 RENDER button, presets, logos,
    BGM, transitions, video-track verification, etc.) are inherited as-is."""

    def __init__(self, master):
        super().__init__(master)
        # ONE captions system in this tab: the PRO engine (Story Video's
        # karaoke / styles / colours / font / position) — fed either by the
        # block's script text OR by Whisper transcription of the clip's own
        # audio. The base's plain "Captions / Subtitles" section is removed so
        # there is no second, competing caption path.
        try: self.captions_enabled_var.set(False)
        except Exception: pass
        try: self._cap_section.grid_remove()
        except Exception: pass
        _fd = os.path.join(TEMP_DIR, "story_fonts")
        self._story_fontsdir = _fd if os.path.isdir(_fd) and os.listdir(_fd) else None
        self._story_cap_px = float(self.settings.get("story_cap_px") or 0.5)
        self._story_cap_py = float(self.settings.get("story_cap_py") or 0.80)
        self._stories_perf_job = None
        self._stories_dirty_outputs = False
        self._add_stories_freeze_section()
        self._add_stories_caption_section()

    # ── Pro-caption helpers reused verbatim from Story Video ──
    _swatch                 = StoryVideoEditorFrame._swatch
    _story_pick             = StoryVideoEditorFrame._story_pick
    _story_upload_font      = StoryVideoEditorFrame._story_upload_font
    _story_apply_style_defaults = StoryVideoEditorFrame._story_apply_style_defaults
    _story_int              = StoryVideoEditorFrame._story_int
    _story_opts             = StoryVideoEditorFrame._story_opts
    _story_position_picker  = StoryVideoEditorFrame._story_position_picker
    _story_preview_captions = StoryVideoEditorFrame._story_preview_captions
    _story_clear_cache      = StoryVideoEditorFrame._story_clear_cache
    _story_preview_effect   = StoryVideoEditorFrame._story_preview_effect
    _story_preview_sample   = StoryVideoEditorFrame._story_preview_sample
    _story_preview_bg       = StoryVideoEditorFrame._story_preview_bg
    _story_freeze_start     = StoryVideoEditorFrame._story_freeze_start

    def _queue_story_perf_commit(self, delay=220):
        try:
            old = self._stories_perf_job
            if old:
                self.after_cancel(old)
        except Exception:
            pass

        def _commit():
            self._stories_perf_job = None
            try:
                if self._stories_dirty_outputs:
                    for b in self.blocks:
                        try:
                            b["output"] = ""
                        except Exception:
                            pass
                    self._stories_dirty_outputs = False
                    print(f"[PERF] stories outputs invalidated lazily for {len(self.blocks)} scenes")
            except Exception as e:
                print("[PERF] lazy invalidate failed:", e)

        try:
            self._stories_perf_job = self.after(delay, _commit)
        except Exception:
            _commit()

    def _story_invalidate(self):
        # Clear cached caption overlays so style changes take effect
        try:
            import glob
            for f in glob.glob(os.path.join(TEMP_DIR, "story_capov_*.mov")):
                try: os.remove(f)
                except Exception: pass
        except Exception: pass
        self._stories_dirty_outputs = True
        self._queue_story_perf_commit()

    def _story_save(self):
        """Persist ONLY the caption settings (Stories has no freeze-FX card)."""
        try:
            s = self.settings
            s.set("story_cap_on",        bool(self._story_cap_on.get()))
            s.set("story_cap_style",     self._story_cap_style.get())
            s.set("story_cap_mode",      self._story_cap_mode.get())
            s.set("story_cap_karaoke",   bool(self._story_cap_karaoke.get()))
            s.set("story_cap_maxwords",  self._story_cap_maxwords.get())
            s.set("story_cap_caps",      self._story_cap_caps.get())
            s.set("story_cap_size",      self._story_cap_size.get())
            s.set("story_cap_primary",   self._story_cap_primary.get())
            s.set("story_cap_highlight", self._story_cap_highlight.get())
            s.set("story_cap_active",    self._story_cap_active.get())
            if hasattr(self, "_story_cap_box"):      s.set("story_cap_box",       bool(self._story_cap_box.get()))
            if hasattr(self, "_story_cap_boxcolor"): s.set("story_cap_boxcolor",  self._story_cap_boxcolor.get())
            if hasattr(self, "_story_cap_opacity"):  s.set("story_cap_opacity",   self._story_cap_opacity.get())
            s.set("story_cap_font",      self._story_cap_font.get())
            s.set("story_cap_px",        float(getattr(self, "_story_cap_px", 0.5)))
            s.set("story_cap_py",        float(getattr(self, "_story_cap_py", 0.80)))
            if hasattr(self, "_story_cap_border_on"): s.set("story_cap_border_on", bool(self._story_cap_border_on.get()))
            if hasattr(self, "_story_cap_border_w"):  s.set("story_cap_border_w",  self._story_cap_border_w.get())
            if hasattr(self, "_story_cap_box"):       s.set("story_cap_box",       bool(self._story_cap_box.get()))
            if hasattr(self, "_story_cap_boxcolor"):  s.set("story_cap_boxcolor",  self._story_cap_boxcolor.get())
            if hasattr(self, "_story_cap_opacity"):   s.set("story_cap_opacity",   self._story_cap_opacity.get())
            if hasattr(self, "_story_fx_var"):       s.set("story_fx",           self._story_fx_var.get())
            if hasattr(self, "_story_motion_var"):   s.set("story_motion",       self._story_motion_var.get())
            if hasattr(self, "_story_motion_speed"): s.set("story_motion_speed", self._story_motion_speed.get())
            s.save()
            self._story_invalidate()
        except Exception as e:
            print("[STORIES] caption save:", e)

    # ────────────────────────────────────────────────────────────────
    # Freeze-frame: when the voiceover is LONGER than the clip, the last
    # frame is held — this card decides what happens on that held frame
    # (overlay FX + a camera MOTION so it never looks like a dead still).
    # ────────────────────────────────────────────────────────────────
    def _add_stories_freeze_section(self):
        sb = getattr(self, "_sb_ref", None)
        if sb is None: return
        try:
            C_ = C
            fxc = ctk.CTkFrame(sb, fg_color=C_["card"], border_color=C_["accent"],
                               border_width=2, corner_radius=8)
            fxc.grid(row=949, column=0, sticky="ew", padx=6, pady=(4,4))
            ctk.CTkLabel(fxc, text="✨ FREEZE-FRAME EFFECT", text_color=C_["accent"],
                         font=("Segoe UI",13,"bold")).pack(anchor="w", padx=10, pady=(6,2))
            ctk.CTkLabel(fxc, text="Kicks in only when the voiceover runs LONGER than the clip —\n"
                                   "the last frame is held, and these keep it alive.",
                         text_color=C_["dim"], font=("Segoe UI",9), justify="left").pack(anchor="w", padx=10)

            self._story_fx_var = ctk.StringVar(value=self.settings.get("story_fx") or "None")
            rowfx = ctk.CTkFrame(fxc, fg_color="transparent"); rowfx.pack(fill="x", padx=10, pady=(4,6))
            ctk.CTkOptionMenu(rowfx, variable=self._story_fx_var, values=STORY_EFFECTS,
                              fg_color=C_["btn"], button_color=C_["btn_hov"], width=150,
                              command=lambda *_: self._story_save()).pack(side="left")
            ctk.CTkButton(rowfx, text="▶ Preview", width=90, height=28, fg_color=C_["accent"],
                          text_color="#000", font=("Segoe UI",10,"bold"),
                          command=self._story_preview_effect).pack(side="left", padx=6)

            ctk.CTkLabel(fxc, text="Camera motion on the held frame (logo + captions stay static):",
                         text_color=C_["dim"], font=("Segoe UI",9)).pack(anchor="w", padx=10, pady=(2,0))
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
        except Exception as e:
            print(f"[WARN] stories freeze section: {e}")

    # ────────────────────────────────────────────────────────────────
    # ONE unified sidebar card: style + Whisper + preview, together.
    # ────────────────────────────────────────────────────────────────
    def _add_stories_caption_section(self):
        sb = getattr(self, "_sb_ref", None)
        if sb is None: return
        try:
            C_ = C
            cc = ctk.CTkFrame(sb, fg_color=C_["card"], border_color=C_["purple"],
                              border_width=2, corner_radius=8)
            cc.grid(row=950, column=0, sticky="ew", padx=6, pady=(4,6))
            self._story_cap_card = cc

            hd = ctk.CTkFrame(cc, fg_color="transparent"); hd.pack(fill="x", padx=10, pady=(6,0))
            ctk.CTkLabel(hd, text="🅰 PRO CAPTIONS", text_color=C_["purple"],
                         font=("Segoe UI",13,"bold")).pack(side="left")
            self._story_cap_on = ctk.BooleanVar(value=bool(self.settings.get("story_cap_on")))
            ctk.CTkCheckBox(hd, text="On", variable=self._story_cap_on, width=20,
                            text_color=C_["green"], fg_color=C_["green"],
                            command=self._story_save).pack(side="right")
            ctk.CTkLabel(cc, text="Scripted clip → captions from its script.\n"
                                  "Clip with no script → 🎤 fetches them from the clip's own voice.\n"
                                  "Same style, same preview, one section.",
                         text_color=C_["dim"], font=("Segoe UI",9), justify="left").pack(anchor="w", padx=10, pady=(1,4))

            # ── the Whisper entry point lives INSIDE this card ──
            cap_btn_row = ctk.CTkFrame(cc, fg_color="transparent")
            cap_btn_row.pack(fill="x", padx=10, pady=(2,2))
            self._stories_cap_btn = ctk.CTkButton(
                cap_btn_row, text="🎤 Generate Captions", height=32, fg_color=C_["orange"],
                text_color="#000", font=("Segoe UI",12,"bold"), command=self._gen_captions)
            self._stories_cap_btn.pack(side="left", fill="x", expand=True)
            ctk.CTkButton(
                cap_btn_row, text="🗑 Clean Scenes", width=130, height=32, fg_color=C_["red"],
                text_color="#fff", font=("Segoe UI",11,"bold"), command=self._delete_all_blocks
            ).pack(side="left", padx=(8,0))
            self._stories_cap_lbl = ctk.CTkLabel(cc, text="Not generated yet",
                                                 text_color=C_["dim"], font=("Segoe UI",9))
            self._stories_cap_lbl.pack(anchor="w", padx=12, pady=(0,4))

            r1 = ctk.CTkFrame(cc, fg_color="transparent"); r1.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(r1, text="Style:", text_color=C_["text"], width=70, anchor="w").pack(side="left")
            self._story_cap_style = ctk.StringVar(value=self.settings.get("story_cap_style") or "Karaoke Pop")
            ctk.CTkOptionMenu(r1, variable=self._story_cap_style, values=STORY_CAPTION_STYLES,
                              fg_color=C_["btn"], button_color=C_["btn_hov"], width=180,
                              command=self._story_apply_style_defaults).pack(side="right")

            rmode = ctk.CTkFrame(cc, fg_color="transparent"); rmode.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(rmode, text="Animation:", text_color=C_["text"], width=70, anchor="w").pack(side="left")
            self._story_cap_mode = ctk.StringVar(value=self.settings.get("story_cap_mode") or "box")
            ctk.CTkOptionMenu(rmode, variable=self._story_cap_mode,
                              values=["box","highlight","pop","word","plain"],
                              fg_color=C_["btn"], button_color=C_["btn_hov"], width=110,
                              command=lambda *_: self._story_save()).pack(side="left")
            ctk.CTkButton(rmode, text="📍 Position (drag & lock)", height=26, fg_color=C_["btn"],
                          hover_color=C_["btn_hov"], text_color=C_["text"], font=("Segoe UI",10),
                          command=self._story_position_picker).pack(side="left", padx=6)

            r2 = ctk.CTkFrame(cc, fg_color="transparent"); r2.pack(fill="x", padx=10, pady=2)
            kar0 = self.settings.get("story_cap_karaoke")
            self._story_cap_karaoke = ctk.BooleanVar(value=(True if kar0 in ("", None) else bool(kar0)))
            ctk.CTkCheckBox(r2, text="Karaoke (realtime)", variable=self._story_cap_karaoke,
                            text_color=C_["text"], fg_color=C_["purple"], width=20,
                            command=self._story_save).pack(side="left")
            ctk.CTkLabel(r2, text="Max words:", text_color=C_["dim"]).pack(side="left", padx=(12,2))
            self._story_cap_maxwords = ctk.StringVar(value=str(self.settings.get("story_cap_maxwords") or 6))
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
            ctk.CTkLabel(r4, text="Base text:", text_color=C_["text"], width=88, anchor="w").pack(side="left")
            self._story_cap_primary = ctk.StringVar(value=self.settings.get("story_cap_primary") or "#FFFFFF")
            self._swatch(r4, self._story_cap_primary, "#FFFFFF").pack(side="left", padx=2)
            ctk.CTkLabel(r4, text="Fill:", text_color=C_["text"]).pack(side="left", padx=(10,2))
            self._story_cap_highlight = ctk.StringVar(value=self.settings.get("story_cap_highlight") or "#7C3AED")
            self._swatch(r4, self._story_cap_highlight, "#7C3AED").pack(side="left", padx=2)
            ctk.CTkLabel(r4, text="Border:", text_color=C_["text"]).pack(side="left", padx=(10,2))
            self._story_cap_active = ctk.StringVar(value=self.settings.get("story_cap_active") or "#FFFFFF")
            self._swatch(r4, self._story_cap_active, "#FFFFFF").pack(side="left", padx=2)

            # ── Border on/off + size (for Rhymes/Rhymes1/Cocomelon) ──
            r4b = ctk.CTkFrame(cc, fg_color="transparent"); r4b.pack(fill="x", padx=10, pady=2)
            self._story_cap_border_on = ctk.BooleanVar(value=bool((lambda v: v if v is not None else True)(self.settings.get("story_cap_border_on"))))
            ctk.CTkCheckBox(r4b, text="Border", variable=self._story_cap_border_on,
                            text_color=C_["text"], fg_color=C_["purple"], width=20,
                            command=self._story_save).pack(side="left")
            ctk.CTkLabel(r4b, text="Size:", text_color=C_["dim"]).pack(side="left", padx=(14,2))
            self._story_cap_border_w = ctk.StringVar(value=str(self.settings.get("story_cap_border_w") or ""))
            ctk.CTkEntry(r4b, textvariable=self._story_cap_border_w, width=48,
                         fg_color=C_["entry_bg"], text_color=C_["text"],
                         border_color=C_["border"],
                         placeholder_text="auto").pack(side="left")
            ctk.CTkLabel(r4b, text="px  (blank = style default)",
                         text_color=C_["dim"], font=("Segoe UI",9)).pack(side="left", padx=4)

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
            self._story_cap_font_values = ["(style default)","Poppins","Anton","Montserrat","Playfair Display",
                                           "DejaVu Sans","Comic Sans MS","Comic Neue","Trebuchet MS","Oswald","Bebas Neue",
                                           "Fredoka SemiBold"]
            _cur=self._story_cap_font.get()
            if _cur and _cur not in self._story_cap_font_values:
                self._story_cap_font_values.append(_cur)
            self._story_cap_font_menu = ctk.CTkOptionMenu(r6, variable=self._story_cap_font,
                              values=self._story_cap_font_values,
                              fg_color=C_["btn"], button_color=C_["btn_hov"], width=150,
                              command=lambda *_: self._story_save())
            self._story_cap_font_menu.pack(side="left")
            ctk.CTkButton(r6, text="📎 Upload", width=80, height=26, fg_color=C_["btn"],
                          hover_color=C_["btn_hov"], text_color=C_["text"], font=("Segoe UI",10),
                          command=self._story_upload_font).pack(side="left", padx=6)

            ctk.CTkButton(cc, text="▶ Preview Captions (live style check)", height=30,
                          fg_color=C_["purple"], text_color="#fff", font=("Segoe UI",11,"bold"),
                          command=self._story_preview_captions).pack(fill="x", padx=10, pady=(6,3))
            ctk.CTkButton(cc, text="🔄 Apply & re-render (clear cache)", height=30,
                          fg_color=C_["green"], text_color="#000", font=("Segoe UI",11,"bold"),
                          command=self._story_clear_cache).pack(fill="x", padx=10, pady=(0,8))
        except Exception as e:
            print(f"[WARN] stories caption section: {e}")

    def _cap_lbl(self, txt, col=None):
        try:
            self.after(0, lambda: self._stories_cap_lbl.configure(text=txt, text_color=col or C["dim"]))
        except Exception: pass

    def _story_cap_btn_set(self, text=None, state=None, fg=None, text_color=None):
        def _do():
            try:
                if not hasattr(self, "_stories_cap_btn"):
                    return
                kw = {}
                if text is not None: kw["text"] = text
                if state is not None: kw["state"] = state
                if fg is not None: kw["fg_color"] = fg
                if text_color is not None: kw["text_color"] = text_color
                if kw:
                    self._stories_cap_btn.configure(**kw)
            except Exception as e:
                print("[STORIES] caption button ui:", e)
        try:
            self.after(0, _do)
        except Exception:
            pass

    def _story_caption_apply_text_ui(self, block, text):
        """Reflect the transcribed text in the block's row. Older code wrote
        to block["text_entry"], a Text widget that this block layout never
        actually creates — so transcribed captions silently never showed up.
        The compact row's preview label ("txt_lbl") is what's really there."""
        try:
            lbl = block.get("txt_lbl")
            if lbl:
                d = (text[:60] + "…") if len(text) > 60 else (text or "[no script]")
                lbl.configure(text=d)
        except Exception as e:
            print(f"[STORIES] text ui update failed for block #{block.get('num','?')}: {e}")

    def _story_caption_finish_ui(self, successes, failures, total):
        try:
            self._story_cap_on.set(True)
            self._story_save()
            self._story_invalidate()
        except Exception as e:
            print("[STORIES] caption finish ui:", e)
        self._story_caption_busy = False
        self._story_cap_btn_set("🎤 Generate Captions", "normal", C["orange"], "#000")
        if failures:
            self._ss(f"✓ Captions done: {successes}/{total} succeeded, {failures} failed", C["orange"])
            self._cap_lbl(f"ON — {successes} transcribed, {failures} failed", C["orange"])
        else:
            self._ss(f"✓ All {successes} captions generated! Press 🎬 RENDER to burn them in.", C["green"])
            self._cap_lbl(f"ON — {successes} clip(s) transcribed + scripted clips", C["green"])

    def _story_caption_abort_ui(self, status_text, color=None):
        self._story_caption_busy = False
        self._story_cap_btn_set("🎤 Generate Captions", "normal", C["orange"], "#000")
        if status_text:
            self._ss(status_text, color or C["red"])

    # ── Presets also carry the caption look ──
    def _collect_master_settings(self):
        snap = super()._collect_master_settings()
        try:
            snap["stories_captions"] = {
                "on":        bool(self._story_cap_on.get()),
                "style":     self._story_cap_style.get(),
                "mode":      self._story_cap_mode.get(),
                "karaoke":   bool(self._story_cap_karaoke.get()),
                "maxwords":  self._story_cap_maxwords.get(),
                "caps":      self._story_cap_caps.get(),
                "size":      self._story_cap_size.get(),
                "primary":   self._story_cap_primary.get(),
                "highlight": self._story_cap_highlight.get(),
                "active":    self._story_cap_active.get(),
                "box":       bool(self._story_cap_box.get()),
                "boxcolor":  self._story_cap_boxcolor.get(),
                "opacity":   self._story_cap_opacity.get(),
                "font":      self._story_cap_font.get(),
                "px":        float(getattr(self, "_story_cap_px", 0.5)),
                "py":        float(getattr(self, "_story_cap_py", 0.80)),
                "fx":        (self._story_fx_var.get() if hasattr(self,"_story_fx_var") else "None"),
                "motion":    (self._story_motion_var.get() if hasattr(self,"_story_motion_var") else "Zoom In-Out"),
                "motion_speed": (self._story_motion_speed.get() if hasattr(self,"_story_motion_speed") else "100"),
            }
        except Exception as e:
            print("[STORIES preset collect]", e)
        return snap

    def _apply_master_settings(self, snap, warn_missing_files=True):
        super()._apply_master_settings(snap, warn_missing_files)
        cp = (snap or {}).get("stories_captions") or {}
        if not cp: return
        try:
            self._story_cap_on.set(bool(cp.get("on")))
            self._story_cap_style.set(cp.get("style") or "Karaoke Pop")
            self._story_cap_mode.set(cp.get("mode") or "box")
            self._story_cap_karaoke.set(bool(cp.get("karaoke", True)))
            self._story_cap_maxwords.set(str(cp.get("maxwords") or 6))
            self._story_cap_caps.set(cp.get("caps") or "AA")
            self._story_cap_size.set(str(cp.get("size") or ""))
            self._story_cap_primary.set(cp.get("primary") or "#FFFFFF")
            self._story_cap_highlight.set(cp.get("highlight") or "#7C3AED")
            self._story_cap_active.set(cp.get("active") or "#FFFFFF")
            self._story_cap_box.set(bool(cp.get("box")))
            self._story_cap_boxcolor.set(cp.get("boxcolor") or "#000000")
            self._story_cap_opacity.set(str(cp.get("opacity") or 90))
            self._story_cap_font.set(cp.get("font") or "(style default)")
            self._story_cap_px = float(cp.get("px", 0.5))
            self._story_cap_py = float(cp.get("py", 0.80))
            if hasattr(self, "_story_fx_var"):       self._story_fx_var.set(cp.get("fx") or "None")
            if hasattr(self, "_story_motion_var"):   self._story_motion_var.set(cp.get("motion") or "Zoom In-Out")
            if hasattr(self, "_story_motion_speed"): self._story_motion_speed.set(str(cp.get("motion_speed") or 100))
            self._story_save()
        except Exception as e:
            print("[STORIES preset apply]", e)

    # ── Help text override so users know about the new feature ──
    def _tab_help_title(self): return "📖 Stories"
    def _tab_help_steps(self):
        return [
            "📖 Stories = Master + ONE unified PRO caption system.",
            "1. Upload video clips (like Master). Paste scripts where you have them.",
            "2. Open 🅰 PRO CAPTIONS in the sidebar — style, animation, karaoke, colours,",
            "   font, size and drag-lock position. ▶ Preview Captions shows the exact look.",
            "3. Click 🎤 Generate Captions (one button for everything):",
            "   • clips WITH a script → captions come from the script, timed to its TTS",
            "   • clips WITHOUT a script → pick a language + Whisper model, and the tool",
            "     transcribes the clip's OWN voice (real word-level timing).",
            "4. Click 🎬 RENDER — captions get burned into every scene in the same style.",
            "   TTS is skipped on auto-captioned clips (they already have their own audio).",
            "5. Presets save the caption look too — load one and everything comes back.",
        ]

    # ────────────────────────────────────────────────────────────────
    # Override the base's caption group worker so:
    #   • Scripted blocks: behave exactly like the base (uses text +
    #     TTS-audio duration to lay out caption groups)
    #   • Auto-captioned blocks: use Whisper's PRECISE per-segment
    #     start/end timestamps directly — captions land word-for-word
    #     on the actual speech in the source clip
    # Styling (font, size, color, BG, opacity, position, margin,
    # animation) comes from the same UI controls in the sidebar. Only
    # the TIMING is customised for auto-captioned blocks.
    # ────────────────────────────────────────────────────────────────
    def _gen_captions_worker(self):
        self._save_settings()
        self._caption_groups.clear()
        count = 0
        for b in self.blocks:
            text = (b.get("text") or "").strip()
            if not text: continue

            # ── Auto-captioned block: use Whisper's exact segment timings ──
            if b.get("auto_captioned") and b.get("whisper_segments"):
                try:
                    groups = self._groups_from_whisper_segments(
                        b["whisper_segments"],
                        max_chars=self.caption_max_chars_var.get(),
                        max_lines=self.caption_max_lines_var.get(),
                        words_per_group=self.caption_words_var.get())
                except Exception as e:
                    print(f"[STORIES caption timing] block #{b.get('num')}: {e}")
                    groups = None
                if groups:
                    self._caption_groups[b["num"]] = groups
                    count += len(groups)
                    continue
                # Fall through to duration-based fallback if segment
                # conversion produced nothing usable.

            # ── Everything else: base behaviour (scripted clips + fallback) ──
            if b.get("video_only") and not b.get("auto_captioned"):
                continue
            ap = b.get("tts_audio","")
            if ap and os.path.exists(ap):
                dur = get_duration(ap)
            elif b.get("auto_captioned"):
                # Auto-captioned block without segments — use the clip's
                # own duration as the caption timeline.
                mp = b.get("source_media","")
                dur = get_duration(mp) if mp and os.path.exists(mp) else estimate_tts_duration_from_text(text)
            else:
                dur = estimate_tts_duration_from_text(text)
            if dur <= 0.1: continue
            groups = generate_caption_groups_with_timing(
                text, dur,
                max_chars=self.caption_max_chars_var.get(),
                max_lines=self.caption_max_lines_var.get(),
                words_per_group=self.caption_words_var.get())
            if groups:
                self._caption_groups[b["num"]] = groups
                count += len(groups)

        def _upd():
            if count > 0:
                self.captions_enabled_var.set(False)
                try:
                    self._story_cap_on.set(True)
                    self._story_save()
                except Exception:
                    pass
                self.cap_status_lbl.configure(text=f"ON — {count} captions", text_color=C["green"])
                self._ss(f"Generated {count} captions for {len(self._caption_groups)} scenes", C["green"])
            else:
                self.cap_status_lbl.configure(text="No audio yet — gen audio first", text_color=C["red"])
        self.after(0, _upd)

    def _groups_from_whisper_segments(self, segments, max_chars=35, max_lines=2, words_per_group=7):
        """Convert Whisper's raw segment list into the same caption-group
        format the rest of the pipeline uses. Each returned entry is
        `{"text": "...", "start": float, "end": float}` — exactly what the
        caption drawtext filter expects. Segments are split further when
        they exceed the char/line/word limits set in the sidebar."""
        groups = []
        max_total_chars = max(max_chars * max_lines, 20)
        for seg in segments:
            seg_text = (seg.get("text") or "").strip()
            if not seg_text: continue
            start = float(seg.get("start", 0) or 0)
            end   = float(seg.get("end",   start + 1.0) or start + 1.0)
            words = seg_text.split()
            # If the segment fits the limits, keep it as one group.
            if len(seg_text) <= max_total_chars and len(words) <= words_per_group:
                groups.append({"text": seg_text, "start": start, "end": end})
                continue
            # Otherwise split it evenly by word count so each sub-group
            # respects the sidebar's chars/words settings.
            chunks = []
            cur = []
            for w in words:
                cur.append(w)
                if len(cur) >= words_per_group or len(" ".join(cur)) >= max_total_chars:
                    chunks.append(" ".join(cur)); cur = []
            if cur: chunks.append(" ".join(cur))
            if not chunks: continue
            span = max(0.2, end - start)
            per = span / len(chunks)
            for i, c in enumerate(chunks):
                groups.append({
                    "text": c,
                    "start": start + i * per,
                    "end":   start + (i + 1) * per,
                })
        return groups

    # ────────────────────────────────────────────────────────────────
    # Override the base's yellow "Generate Captions" button so it does
    # the RIGHT thing for Stories: if any clip has no script, run the
    # Whisper transcription flow first, THEN generate caption groups.
    # The Preview button, style controls (font/size/color/BG/opacity/
    # position/animation) are ALL inherited unchanged — auto-captioned
    # clips get the same look as scripted ones.
    # ────────────────────────────────────────────────────────────────
    def _gen_captions(self):
        """ONE button for everything:
             • scripted clips      → caption text = the script (timed to its TTS)
             • un-scripted clips   → Whisper transcribes the clip's own voice
           Either way the PRO caption engine burns them in at render time with
           the exact style shown in ▶ Preview Captions."""
        if not self.blocks:
            messagebox.showinfo("Captions", "Upload some clips first."); return

        scripted = 0
        needs_whisper = []
        refresh_auto = 0
        for i, b in enumerate(self.blocks):
            has_text  = bool((b.get("text") or "").strip())
            mp        = b.get("source_media") or ""
            has_media = bool(mp and os.path.exists(mp))
            auto_done = bool(b.get("auto_captioned"))
            if has_text and not auto_done:
                scripted += 1
            elif has_media and ((not has_text) or auto_done):
                needs_whisper.append(i)
                if auto_done:
                    refresh_auto += 1

        # Captions ON + cached scene outputs dropped so they re-render burned-in.
        self._story_cap_on.set(True)
        self._story_save()
        self._story_invalidate()

        if not needs_whisper:
            self._cap_lbl(f"ON — {scripted} scripted clip(s), captions from script", C["green"])
            self._ss(f"Captions ON — {scripted} scripted clip(s) will use their script text.", C["green"])
            return

        msg = (
            f"{len(needs_whisper)} clip(s) Whisper se load / reload honge.\n\n"
            "Clip ka audio dubara transcribe hoga. Next dialog me language + model pick karoge.\n\n"
            f"({scripted} scripted clip(s) untouched rahenge.)"
        )
        if refresh_auto:
            msg += f"\n\nRefresh: {refresh_auto} already-captioned clip(s) bhi dubara load honge."

        if not messagebox.askyesno("Transcribe clip audio?", msg):
            self._cap_lbl(f"ON — {scripted} scripted clip(s) only", C["orange"])
            return

        # Engine app ke saath bundled hai — koi install prompt nahi chahiye.
        try:
            import whisper_engine  # noqa: F401
        except ImportError as e:
            messagebox.showerror("Whisper engine missing",
                                 f"faster-whisper load nahi hua:\n{e}{_whisper_import_hint(e)}")
            return

        CaptionsCreateDialog(self, needs_whisper, on_start=self._start_caption_worker)

    # ────────────────────────────────────────────────────────────────
    # Per-block caption timing for the PRO engine
    #   • auto-captioned → Whisper's REAL word timestamps
    #   • scripted       → words spread evenly across the TTS duration
    #     (so captions end when the voiceover ends, even in Full-clip mode)
    # ────────────────────────────────────────────────────────────────
    def _stories_word_times(self, b, vdur):
        text = (b.get("caption_text") or b.get("text") or "").strip()
        if not text: return None

        if b.get("auto_captioned"):
            wt = []
            for seg in (b.get("whisper_segments") or []):
                words = seg.get("words") or []
                if words:
                    for w in words:
                        t = (w.get("word") or "").strip()
                        if not t: continue
                        wt.append({"word": t,
                                   "start": float(w.get("start", 0) or 0),
                                   "end":   float(w.get("end", 0) or 0)})
                else:  # segment without word-level data → spread its words evenly
                    st_ = float(seg.get("start", 0) or 0)
                    en_ = float(seg.get("end", st_ + 1.0) or st_ + 1.0)
                    ws  = (seg.get("text") or "").split()
                    if not ws: continue
                    per = max(0.05, (en_ - st_) / len(ws))
                    for i, w in enumerate(ws):
                        wt.append({"word": w, "start": st_ + i*per, "end": st_ + (i+1)*per})
            # sanitise: monotonic, non-zero length
            clean = []
            for w in wt:
                if w["end"] <= w["start"]: w["end"] = w["start"] + 0.18
                clean.append(w)
            return clean or None

        # Scripted block → time the script against its TTS audio.
        tp  = b.get("tts_audio") or ""
        dur = get_duration(tp) if (tp and os.path.exists(tp)) else 0.0
        if dur <= 0.1: dur = min(float(vdur or 0), estimate_tts_duration_from_text(text))
        if dur <= 0.1: return None
        words = text.split()
        if not words: return None
        per = dur / len(words)
        return [{"word": w, "start": i*per, "end": (i+1)*per} for i, w in enumerate(words)]

    def _stories_cap_opts(self, b, vdur):
        # freeze_motion / freeze_speed come straight from the FREEZE-FRAME card
        # (they only ever act on the held tail — see _stories_burn_captions).
        opts = self._story_opts()
        opts["captions_on"] = True
        wt = self._stories_word_times(b, vdur)
        if wt: opts["word_times"] = wt
        return opts

    # ────────────────────────────────────────────────────────────────
    # Caption creation — main entry point (top action-row button)
    # ────────────────────────────────────────────────────────────────
    def _auto_caption_before_render(self):
        """If PRO CAPTIONS is ON but the user never pressed 🎤 Generate
        Captions, auto-transcribe any clip that still has no script text —
        using the 'base' Whisper model (fast, always-available) so this
        never turns into a long surprise mid-render. Caption STYLE (font,
        color, position, animation, box, karaoke, etc.) already comes from
        whatever is currently set — manually or via a loaded preset — this
        only fills in the missing caption TEXT for un-scripted clips.
        Clips that already have a script, or were already transcribed
        earlier, are left untouched."""
        try:
            if not bool(self._story_cap_on.get()):
                return
        except Exception:
            return
        if getattr(self, "_story_caption_busy", False):
            self._sss("[STORIES] auto-caption skipped — a caption job is already running")
            return

        targets = []
        for i, b in enumerate(self.blocks):
            has_text = bool((b.get("text") or "").strip())
            mp = b.get("source_media") or ""
            has_media = bool(mp and os.path.exists(mp))
            if has_media and not has_text and not b.get("auto_captioned"):
                targets.append(i)
        if not targets:
            return

        try:
            import whisper_engine  # noqa: F401
        except ImportError as e:
            self._sss(f"[STORIES] auto-caption skipped — whisper engine missing: {e}")
            self._ss("Captions ON but Whisper engine missing — rendering without "
                     "auto-captions for un-scripted clip(s).", C["orange"])
            return

        self._story_caption_busy = True
        self._render_step(1, f"Auto-transcribing {len(targets)} clip(s) (base model, CPU)…", sub=0.2)
        saved_lang_name = self.settings.get("whisper_language") if hasattr(self, "settings") else "auto"
        lang_code = "auto"
        for c, n in _WHISPER_LANGUAGES:
            if n == saved_lang_name or c == saved_lang_name:
                lang_code = c
                break
        self._sss(f"[STORIES] auto-caption (render-time): {len(targets)} clip(s), "
                 f"model=base, lang={lang_code}, device=cpu (forced — avoids a CUDA-context "
                 f"crash risk while ffmpeg/NVENC may run in the same process)")
        try:
            self._caption_worker(targets, lang_code, "base", device="cpu")
        finally:
            self._story_caption_busy = False
        self._render_step(1, "Auto-captions ready", sub=0.9)

    def _create_captions_flow(self):
        """Open the caption-creation dialog after basic pre-flight checks."""
        if getattr(self, "_story_caption_busy", False):
            self._ss("Caption generation already running…", C["orange"])
            return
        if not self.blocks:
            messagebox.showinfo("Create Captions",
                "Upload some video clips first, then click Create Captions."); return

        # Find blocks that qualify: video source present, no script text yet.
        targets = []
        for i, b in enumerate(self.blocks):
            has_text = bool((b.get("text") or "").strip())
            mp = b.get("source_media") or ""
            has_media = bool(mp and os.path.exists(mp))
            if has_media and not has_text:
                targets.append(i)

        if not targets:
            messagebox.showinfo(
                "Nothing to transcribe",
                "Every clip already has a script — captions will come from those.\n\n"
                "The 🎤 Create Captions button only transcribes clips that DON'T have a script."
            ); return

        # Engine app ke saath bundled hai — koi install prompt nahi chahiye.
        try:
            import whisper_engine  # noqa: F401
        except ImportError as e:
            messagebox.showerror("Whisper engine missing",
                                 f"faster-whisper load nahi hua:\n{e}{_whisper_import_hint(e)}")
            return

        self._sss(f"[STORIES] caption preflight: whisper_targets={len(targets)} total_blocks={len(self.blocks)}")
        # Open the dialog to pick language + model size.
        CaptionsCreateDialog(self, targets, on_start=self._start_caption_worker)

    def _start_caption_worker(self, targets, language_code, model_size):
        """Called by the CaptionsCreateDialog when the user clicks Start."""
        if getattr(self, "_story_caption_busy", False):
            self._ss("Caption generation already running…", C["orange"])
            return
        self._story_caption_busy = True
        self._story_cap_btn_set("⏳ Generating captions…", "disabled", C["btn"], C["dim"])
        self._ss(f"Loading Whisper model '{model_size}'…", C["orange"])
        self._sss(f"[STORIES] caption worker queued for {len(targets)} scene(s)")
        self._sp(0.05)
        threading.Thread(
            target=self._caption_worker,
            args=(targets, language_code, model_size),
            daemon=True).start()

    def _caption_worker(self, targets, language_code, model_size, device="cpu"):
        # faster-whisper engine — app ke saath bundled hai, koi install nahi chahiye
        try:
            import whisper_engine as whisper
        except ImportError as e:
            self._story_caption_abort_ui("Whisper engine load nahi hua.", C["red"])
            self.after(0, lambda: messagebox.showerror(
                "Whisper engine missing",
                f"faster-whisper load nahi ho paya:\n\n{e}{_whisper_import_hint(e)}"))
            return

        # device: "auto" (manual button flow — shim decides CUDA/CPU) or a
        # forced value like "cpu" (render-time auto-caption — see caller).

        was_cached = _whisper_model_is_downloaded(model_size)
        if not was_cached:
            self._ss(f"Downloading Whisper model '{model_size}' (one-time)…", C["orange"])
        else:
            self._ss(f"Loading Whisper model '{model_size}'…", C["orange"])

        model = None
        load_err = None
        try:
            with _safe_std_streams():          # model download uses tqdm → stdout
                model = whisper.load_model(model_size, device=device)
        except Exception as e:
            load_err = e
            self._sss(f"Whisper '{model_size}' load error: {e}")

        # ── FALLBACK: selected model fail → base model CPU pe try karo ──
        # Kuch bhi ho jaye, kam se kam base model se kaam chalna chahiye.
        if model is None and model_size != "base":
            self._ss(f"'{model_size}' load fail → falling back to 'base' model…", C["orange"])
            try:
                with _safe_std_streams():
                    model = whisper.load_model("base", device="cpu")
                model_size = "base"
            except Exception as e:
                load_err = e
                self._sss(f"Whisper 'base' fallback bhi fail: {e}")

        if model is None:
            emsg = str(load_err)[:400]
            self._story_caption_abort_ui(f"✗ Model load failed: {emsg[:80]}", C["red"])
            hint = ""
            el = emsg.lower()
            if "dll load failed" in el:
                hint = ("\n\nYeh PC pe Microsoft Visual C++ Runtime missing hai.\n"
                        "Fix (2 min): yeh install karo aur app restart karo:\n"
                        "https://aka.ms/vc/17/release/vc_redist.x64.exe")
            elif "av" in el and "module" in el:
                hint = ("\n\nYeh build issue hai — 'av' module exe mein bundle "
                        "nahi hua. Naye installer se update karo.")
            elif "connect" in emsg.lower() or "resolve" in emsg.lower() or "timed out" in emsg.lower():
                hint = ("\n\nModel download ke liye internet chahiye (sirf pehli "
                        "baar). Net check karke dobara try karo.")
            self.after(0, lambda: messagebox.showerror(
                "Whisper model load failed",
                f"Model load nahi ho paya:\n\n{emsg}{hint}"))
            return

        self._sss(f"Whisper: {model.device.upper()} ({model.compute_type}) • model: {model_size}")

        total = len(targets); done = 0
        successes = 0; failures = 0
        for idx in targets:
            if self._cancelled: break
            b = self.blocks[idx]
            mp = b.get("source_media","")
            if not (mp and os.path.exists(mp)): continue
            num = b.get("num","?")
            self._ss(f"Transcribing scene {num} ({done+1}/{total})…", C["orange"])
            self._block_status(b, "🎤 Transcribing…", C["orange"])

            # Extract clean 16kHz mono WAV — Whisper's optimal input format —
            # into TEMP_DIR. Removed after transcription.
            wav = os.path.join(TEMP_DIR, f"whisper_in_{num}.wav")
            try:
                _run_ff(["ffmpeg","-y","-i", mp,
                         "-vn","-ac","1","-ar","16000",
                         "-c:a","pcm_s16le","-loglevel","error", wav], timeout=600)
            except Exception as e:
                self._sss(f"[caption #{num}] audio extract failed: {e}")
                self._block_status(b, "✗ Audio extract fail", C["red"])
                failures += 1
                done += 1; self._sp(done/total); continue
            if not (os.path.exists(wav) and os.path.getsize(wav) > 1024):
                self._block_status(b, "✗ No audio in clip", C["orange"])
                failures += 1
                done += 1; self._sp(done/total); continue

            # Run Whisper.
            try:
                # verbose=None → Whisper draws NO tqdm progress bar. With
                # verbose=False it *does* draw one, and that bar writes to
                # sys.stdout — which is None when the tool runs without a
                # console (pythonw / .bat launcher / frozen EXE), producing
                # "'NoneType' object has no attribute 'write'".
                kwargs = {"word_timestamps": True}
                if language_code and language_code != "auto":
                    kwargs["language"] = language_code
                try:
                    with _safe_std_streams():
                        result = model.transcribe(wav, **kwargs)
                except Exception as e_try:
                    # Self-heal: any GPU/CUDA library problem (missing
                    # cublas/cudnn DLL, driver mismatch, etc.) → silently
                    # reload Whisper on CPU and retry THIS clip immediately.
                    # No manual install, restart, or settings change ever
                    # needed — the tool just keeps going on whatever this
                    # machine can actually run.
                    emsg_l = str(e_try).lower()
                    gpu_lib_issue = any(k in emsg_l for k in
                        ("cublas", "cudnn", "libcu", "cuda", ".dll", "nvidia"))
                    if gpu_lib_issue and getattr(model, "device", "") != "cpu":
                        self._sss(f"[caption #{num}] GPU library issue ({str(e_try)[:70]}) "
                                 f"— reloading Whisper on CPU and retrying…")
                        with _safe_std_streams():
                            model = whisper.load_model(model_size, device="cpu")
                        with _safe_std_streams():
                            result = model.transcribe(wav, **kwargs)
                    else:
                        raise
                text = (result.get("text") or "").strip()
                # Whisper returns SEGMENT-level start/end timestamps — these
                # are far more accurate than any text-length-based estimate.
                # We stash them so caption group generation can honor them.
                b["whisper_segments"] = result.get("segments", []) or []
            except Exception as e:
                self._sss(f"[caption #{num}] transcribe error: {e}")
                self._block_status(b, "✗ Transcribe fail", C["red"])
                failures += 1
                done += 1; self._sp(done/total); continue
            finally:
                try:
                    if os.path.exists(wav): os.remove(wav)
                except Exception: pass

            if not text:
                self._block_status(b, "✓ Silent (no speech found)", C["orange"])
                b["auto_captioned"] = True
                b["caption_text"] = ""
            else:
                b["text"] = text
                b["caption_text"] = text
                b["auto_captioned"] = True
                # Update the text field in the UI on the main thread only.
                self.after(0, lambda _b=b, _t=text: self._story_caption_apply_text_ui(_b, _t))
                snippet = (text[:40] + "…") if len(text) > 40 else text
                self._block_status(b, f"✓ {snippet}", C["green"])
                successes += 1

            done += 1
            self._sp(done/total)

        self._sp(1.0)
        self._sss(f"[STORIES] caption worker finished: ok={successes} fail={failures} total={total}")
        self.after(0, lambda s=successes, f=failures, t=total: self._story_caption_finish_ui(s, f, t))

    # ────────────────────────────────────────────────────────────────
    # Override _gen_audio_worker: skip TTS on auto-captioned blocks
    # (they already have real audio in the source clip — synthesising
    # over it would double-track voice on top of voice)
    # ────────────────────────────────────────────────────────────────
    def _gen_audio_worker(self, idx):
        b = self.blocks[idx]
        if b.get("auto_captioned"):
            # No TTS: the clip's OWN audio is the voiceover. Silently
            # succeed so the render pipeline treats this block as "done".
            b["_tts_err"] = None
            # Set a small marker so downstream code knows there's no TTS file.
            b["tts_audio"] = None
            try: self._block_status(b, "🎤 Auto-caption (clip audio)", C["accent"])
            except Exception: pass
            return
        return super()._gen_audio_worker(idx)

    # Override _gw: render the scene with Master's bulletproof pipeline, then
    # burn the PRO captions on top of that scene output (same engine, same
    # style, same preview as Story Video).
    #   • auto-captioned block → routed as a no-script clip (own audio, own
    #     duration), but its transcribed text is still captioned
    #   • scripted block       → normal Master flow (TTS + clip mix)
    def _gw(self, idx):
        b = self.blocks[idx]
        if b.get("auto_captioned"):
            saved_text = b.get("text","")
            b["caption_text"] = saved_text or b.get("caption_text","")
            b["text"] = ""                       # → treated as video-only by Master
            try:
                super()._gw(idx)
            finally:
                b["text"] = saved_text
        else:
            super()._gw(idx)
        self._stories_burn_captions(b)

    def _stories_burn_captions(self, b):
        """One post pass per scene: PRO captions + freeze-frame FX + camera
        motion on the held frame. Skipped entirely when none apply."""
        op = b.get("output") or ""
        if not (op and os.path.exists(op)): return
        dur = get_duration(op)
        if dur <= 0.1: return

        # Read cap_on from render snapshot (thread-safe) — NOT from Tk widget
        # which silently fails on Windows background threads.
        _snap = getattr(self, "_render_vars_snapshot", None) or                 getattr(self, "_rhymes_cap_opts_snapshot", None) or {}
        if "captions_on" in _snap:
            cap_on = bool(_snap["captions_on"])
        else:
            try: cap_on = bool(self._story_cap_on.get())
            except Exception: cap_on = True  # default ON
        try:
            eff = self._story_fx_var.get()
            if eff == "None": eff = ""
        except Exception: eff = ""

        text = (b.get("caption_text") or b.get("text") or "").strip() if cap_on else ""
        # Freeze tail = the moment the real footage ends (0 if the clip covers
        # the whole scene → no motion, no FX, nothing to do).
        fs = self._story_freeze_start(b, dur)
        has_tail = (dur - fs) > 0.4
        opts = self._stories_cap_opts(b, dur)
        opts["captions_on"] = bool(text)
        if not has_tail:
            opts["freeze_motion"] = "None"
            eff = ""
        if not text and not eff and not has_tail:
            return                                   # nothing to composite

        num = b.get("num","?")
        try:
            bits = []
            if text: bits.append("captions")
            if eff: bits.append(eff.lower())
            if has_tail and opts.get("freeze_motion","None") != "None":
                bits.append(str(opts["freeze_motion"]).lower())
            self._block_status(b, "🅰 " + " + ".join(bits or ["post"]) + "…", C["purple"])
            self._sss(f"[#{num}] post pass: {', '.join(bits) or 'none'}")
            out = os.path.join(TEMP_DIR, f"story_final_cap_{self._render_session_uid()}_{num}_{abs(hash(op))%99999}.mp4")
            res = story_apply_fx_captions(op, out, eff or "None", text, dur, opts, freeze_start=fs)
            if res and os.path.exists(res) and res != op and self._has_video_track(res):
                b["output"] = res
                self._block_status(b, f"✓ Done ({format_duration(get_duration(res))})", C["green"])
            elif res == op:
                pass                                  # engine decided nothing to do
            else:
                self._sss(f"[#{num}] post pass failed — scene kept as-is")
                self._block_status(b, "✓ Done (post-fx failed)", C["orange"])
        except Exception as e:
            self._sss(f"[#{num}] post-fx error: {str(e)[:60]}")


class CaptionsCreateDialog(_BASIC_VM_TOPLEVEL):
    """Modal dialog: language selector + Whisper model size + start button.
    Shows which models are already downloaded (like Adobe language packs)."""

    def __init__(self, parent, targets, on_start):
        super().__init__(parent)
        self.parent = parent
        self.targets = targets
        self.on_start = on_start
        self.title("Create Captions")
        # Responsive: fits small laptop screens, resizable, and the action
        # buttons are pinned to the bottom BEFORE the scrolling body is packed
        # so they can never be pushed off-screen.
        try:
            sw = self.winfo_screenwidth(); sh = self.winfo_screenheight()
            w = min(680, max(520, int(sw*0.45))); h = min(780, max(520, int(sh*0.85)))
            self.geometry(f"{w}x{h}+{max(0,(sw-w)//2)}+{max(0,(sh-h)//2)}")
        except Exception:
            self.geometry("620x580")
        self.minsize(500, 480)
        self.resizable(True, True)
        _style_toplevel_bg(self, C["bg"])
        self.transient(parent.winfo_toplevel())

        # Header
        head = ctk.CTkFrame(self, fg_color=C["purple"], corner_radius=0, height=60)
        head.pack(fill="x"); head.pack_propagate(False)
        ctk.CTkLabel(head, text="🎤 Create Captions",
                     text_color="#fff", font=("Segoe UI",18,"bold")).pack(side="left", padx=18, pady=15)
        ctk.CTkLabel(head, text=f"{len(targets)} un-scripted clip(s)",
                     text_color="#eee", font=("Segoe UI",11)).pack(side="right", padx=18)

        # ── Buttons FIRST (pinned bottom) ──
        btn_row = ctk.CTkFrame(self, fg_color="transparent"); btn_row.pack(side="bottom", fill="x", padx=18, pady=(6,14))
        ctk.CTkButton(btn_row, text="Cancel", fg_color=C["btn"], text_color=C["dim"],
                      width=110, height=36, command=self.destroy).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="🎤 Start transcription", fg_color=C["purple"],
                      text_color="#fff", height=36, font=("Segoe UI",12,"bold"),
                      command=self._on_start_click).pack(side="right", padx=4, fill="x", expand=True)

        # ── Language section (inside a scrollable body) ──
        body = ctk.CTkScrollableFrame(self, fg_color="transparent"); body.pack(fill="both", expand=True, padx=16, pady=(12,2))
        ctk.CTkLabel(body, text="1. Language of the clips",
                     text_color=C["accent"], font=("Segoe UI",12,"bold")).pack(anchor="w", pady=(6,4))
        ctk.CTkLabel(body, text="Whisper will use this to lock its recogniser. "
                     "Auto-detect is fine but slower and less accurate.",
                     text_color=C["dim"], font=("Segoe UI",9)).pack(anchor="w", pady=(0,4))
        self.lang_var = ctk.StringVar(value=self.parent.settings.get("whisper_language") or "English")
        lang_names = [name for _, name in _WHISPER_LANGUAGES]
        self.lang_menu = ctk.CTkOptionMenu(body, variable=self.lang_var, values=lang_names,
                                           fg_color=C["btn"], text_color=C["text"], width=280)
        self.lang_menu.pack(anchor="w", pady=(0,10))

        # ── Model section — every model listed, each downloadable on demand ──
        hdr = ctk.CTkFrame(body, fg_color="transparent"); hdr.pack(fill="x", pady=(10,2))
        ctk.CTkLabel(hdr, text="2. Model (quality vs. speed)",
                     text_color=C["accent"], font=("Segoe UI",12,"bold")).pack(side="left")
        ctk.CTkButton(hdr, text="↻", width=30, height=24, fg_color=C["btn"],
                      text_color=C["dim"], command=self._refresh_models).pack(side="right")
        ctk.CTkLabel(body, text="Download as many as you like — they're cached forever. "
                     "Pick one, then Start. A model that isn't downloaded yet will be "
                     "fetched automatically when you start.",
                     text_color=C["dim"], font=("Segoe UI",9), justify="left",
                     wraplength=520).pack(anchor="w", pady=(0,6))

        self.model_var = ctk.StringVar(value=self.parent.settings.get("whisper_model") or "base")
        self.model_rows = {}
        self.models_box = ctk.CTkFrame(body, fg_color="transparent")
        self.models_box.pack(fill="x")
        self._build_model_rows()

        # ── Auto-download base model at startup ──
        self.auto_base_var = ctk.BooleanVar(
            value=bool(self.parent.settings.get("whisper_auto_base")))
        def _save_auto_base():
            try:
                self.parent.settings.set("whisper_auto_base", bool(self.auto_base_var.get()))
                self.parent.settings.save()
            except Exception: pass
        ctk.CTkCheckBox(body,
            text="App start pe 'base' model auto-download karo (background, one-time ~145MB)",
            variable=self.auto_base_var, command=_save_auto_base,
            text_color=C["text"], font=("Segoe UI",10),
            fg_color=C["purple"], border_color=C["border"],
            checkmark_color="#fff", corner_radius=4).pack(anchor="w", pady=(10,2))

        ctk.CTkLabel(body, text=f"Cache: {_whisper_cache_root()}",
                     text_color=C["dim"], font=("Consolas",8)).pack(anchor="w", pady=(8,2))

        self.after(50, lambda: (self.lift(), self.focus_force(), self.grab_set()))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda e: self.destroy())

    # ────────────────────────────────────────────────────────────
    def _build_model_rows(self):
        for w in self.models_box.winfo_children(): w.destroy()
        self.model_rows = {}
        for size, label, disk, desc in _WHISPER_MODELS:
            is_dl = _whisper_model_is_downloaded(size)
            row = ctk.CTkFrame(self.models_box, fg_color=C["card"], corner_radius=8,
                               border_width=1,
                               border_color=(C["green"] if is_dl else C["border"]))
            row.pack(fill="x", pady=3)

            line = ctk.CTkFrame(row, fg_color="transparent"); line.pack(fill="x", padx=8, pady=(7,0))
            ctk.CTkRadioButton(line, text="", variable=self.model_var, value=size,
                               width=20, fg_color=C["purple"]).pack(side="left", padx=(0,4))
            ctk.CTkLabel(line, text=label, text_color=C["text"],
                         font=("Segoe UI",12,"bold"), width=80, anchor="w").pack(side="left")
            ctk.CTkLabel(line, text=disk, text_color=C["dim"],
                         font=("Consolas",10), width=70, anchor="w").pack(side="left")

            badge = ctk.CTkLabel(line, text=("✓ Downloaded" if is_dl else "Not downloaded"),
                                 text_color=(C["green"] if is_dl else C["dim"]),
                                 font=("Segoe UI",10,"bold"))
            badge.pack(side="left", padx=8)

            btn = ctk.CTkButton(line, text=("🗑 Remove" if is_dl else "⬇ Download"),
                                width=100, height=26,
                                fg_color=(C["btn"] if is_dl else C["accent"]),
                                text_color=(C["dim"] if is_dl else "#000"),
                                font=("Segoe UI",10,"bold"),
                                command=(lambda sz=size: self._delete_model(sz)) if is_dl
                                        else (lambda sz=size: self._download_model(sz)))
            btn.pack(side="right")

            ctk.CTkLabel(row, text=desc, text_color=C["dim"], font=("Segoe UI",9),
                         anchor="w").pack(fill="x", padx=(34,8), pady=(0,2))
            bar = ctk.CTkProgressBar(row, height=4, progress_color=C["accent"])
            bar.set(0)
            self.model_rows[size] = {"row": row, "badge": badge, "btn": btn, "bar": bar}

    def _refresh_models(self):
        self._build_model_rows()

    def _download_model(self, size):
        """Fetch a model now, so the user can pre-load whatever they want
        before ever starting a transcription."""
        try:
            import whisper_engine  # noqa: F401
        except ImportError as e:
            messagebox.showerror("Whisper engine missing",
                                 f"faster-whisper load nahi hua:\n{e}{_whisper_import_hint(e)}")
            return
        r = self.model_rows.get(size)
        if not r: return
        r["btn"].configure(state="disabled", text="⏳ Downloading…")
        r["badge"].configure(text="downloading…", text_color=C["orange"])
        r["bar"].pack(fill="x", padx=10, pady=(2,8))
        r["bar"].configure(mode="indeterminate"); r["bar"].start()

        def work():
            ok = True; err = ""
            try:
                import whisper_engine
                with _safe_std_streams():          # download progress writes to stdout
                    whisper_engine.load_model(size, device="cpu")
            except Exception as e:
                ok = False; err = str(e)[:120]
                print("[WHISPER] download failed:", e)

            def done():
                try:
                    r["bar"].stop(); r["bar"].pack_forget()
                except Exception: pass
                if ok and _whisper_model_is_downloaded(size):
                    self._build_model_rows()
                    self.model_var.set(size)
                else:
                    r["btn"].configure(state="normal", text="⬇ Retry")
                    r["badge"].configure(text=f"✗ {err[:28] or 'failed'}", text_color=C["red"])
            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _delete_model(self, size):
        # faster-whisper HF-style folders mein cache karta hai:
        #   models--Systran--faster-whisper-<size>/
        # Purana code "{size}.pt" file dhoondhta tha (openai-whisper style)
        # jo kabhi exist nahi karti — isliye Remove kaam hi nahi karta tha.
        root = _whisper_cache_root()
        targets = []
        try:
            for name in os.listdir(root):
                full = os.path.join(root, name)
                if os.path.isdir(full) and name.endswith(f"-{size}"):
                    targets.append(full)
        except Exception:
            pass
        if not targets:
            self._build_model_rows(); return
        mb = 0
        try:
            for t in targets:
                for dirpath, _, files in os.walk(t):
                    for f in files:
                        mb += os.path.getsize(os.path.join(dirpath, f))
            mb /= (1024*1024)
        except Exception: pass
        if not messagebox.askyesno("Remove model",
                                   f"Delete the '{size}' model ({mb:.0f} MB) from disk?\n\n"
                                   "You can download it again any time."):
            return
        try:
            for t in targets:
                shutil.rmtree(t, ignore_errors=True)
        except Exception as e:
            messagebox.showerror("Remove", str(e)); return
        self._build_model_rows()

    def _on_start_click(self):
        # Resolve language name → code
        name = self.lang_var.get()
        code = "auto"
        for c, n in _WHISPER_LANGUAGES:
            if n == name or c == name: code = c; break
        model_size = self.model_var.get()
        try: self.parent.settings.set("whisper_model", model_size)
        except Exception: pass
        try:
            self.parent.settings.set("whisper_language", name)
            self.parent.settings.save()
        except Exception: pass
        self.destroy()
        try:
            self.on_start(self.targets, code, model_size)
        except Exception as e:
            print("[STORIES] transcription start error:", e)


# ════════════════════════════════════════════════════════════════
# TAB CREATION — dedicated 2-tab build (Stories + Queue only)
# ════════════════════════════════════════════════════════════════
# ════════════════════════════════════════════════════════════════
# SUFFIX TOOL — native Python port of life_with_paint_studio.html
# (Master Visual Prompt Engine, Numbering, Scene Suffix, Image Renamer).
# Ported instead of embedded because there is no reliable way to host a
# JS-capable browser AS A CHILD WIDGET inside a Tkinter frame — pywebview
# only ever opens its own separate OS window, which isn't "inside the
# tool". All 4 sub-tools here are pure text/file operations, so a native
# port gives the exact same behaviour with zero external dependency and
# genuinely lives inside this tab.
# ════════════════════════════════════════════════════════════════
def _st_parse_key_value(text):
    """Flexible parser — recognizes several real-world paste formats,
    tried in this order per line:
      1) 'Name = description'                      (classic key=value)
      2) '{NAME} — description'                     (curly-brace name — the
         format used when scene text also refers back to the character as
         {NAME}, e.g. {ANACONDA} — Green anaconda...)
      3) 'NAME — description' / 'NAME– description'  (em/en-dash separated —
         name itself may contain underscores, e.g. OXPECKER_A, FISH_SCHOOL)
      4) 'NAME  description' (2+ spaces, no dash — covers the dash having
         been silently stripped by a copy-paste, common with em-dashes)
      5) 'TAG_description' with no spaces at all     (e.g. ATLAS_adult female owl)
      6) a plain unnamed paragraph with no name at all
    Whichever separator style each line uses, the name is normalized by
    stripping any stray internal whitespace (so 'OXPECKER _A' → 'OXPECKER_A')."""
    entries = []
    current = None
    unnamed = []

    def flush():
        nonlocal current
        if current:
            entries.append({"name": current["name"],
                            "prompt": re.sub(r"\s+", " ", " ".join(current["parts"])).strip()})
            current = None

    for raw in (text or "").replace("\r", "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        m = re.match(r'^([A-Za-z][A-Za-z0-9 _-]{0,40}?)\s*=\s*(.+)$', line)
        if m:
            flush(); current = {"name": m.group(1).strip(), "parts": [m.group(2).strip()]}; continue
        m = re.match(r'^\{([A-Za-z][A-Za-z0-9 _]{0,40}?)\}\s*[—–-]+\s*(.+)$', line)
        if m:
            name = re.sub(r"\s+", "", m.group(1)).strip()
            flush(); current = {"name": name, "parts": [m.group(2).strip()]}; continue
        m = re.match(r'^([A-Za-z][A-Za-z0-9 _]{0,40}?)\s*[—–]+\s*(.+)$', line)
        if m:
            name = re.sub(r"\s+", "", m.group(1)).strip()
            flush(); current = {"name": name, "parts": [m.group(2).strip()]}; continue
        m = re.match(r'^([A-Za-z][A-Za-z0-9 _]{0,40}?)\s{2,}(.+)$', line)
        if m:
            name = re.sub(r"\s+", "", m.group(1)).strip()
            flush(); current = {"name": name, "parts": [m.group(2).strip()]}; continue
        m = re.match(r'^([A-Z][A-Z0-9]{1,20})_(.+)$', line)
        if m:
            flush(); current = {"name": m.group(1).strip(), "parts": [m.group(2).strip()]}; continue
        if current:
            current["parts"].append(line)
        else:
            unnamed.append(line)
    flush()
    if unnamed:
        entries.append({"name": None, "prompt": re.sub(r"\s+", " ", " ".join(unnamed)).strip()})
    entries = [e for e in entries if e["prompt"]]
    entries.sort(key=lambda e: -(len(e["name"]) if e["name"] else 0))
    return entries


def _st_parse_scenes_auto(text, current_format):
    """Same as parseScenesAuto(): detects 'Scene_N' (with or without a
    trailing underscore) OR 'Prompt N:' prefixes — including when wrapped
    in markdown bold ('**Scene_77_full prompt:**') — strips noise phrases
    like 'full prompt:', and re-titles every scene using current_format
    so mixed/messy source formatting never leaks into the output."""
    lines = (text or "").replace("\r", "").split("\n")
    scene_re = re.compile(r'^Scene_(\d+)[_\s]*(.*)$', re.I)
    prompt_re = re.compile(r'^Prompt\s*(\d+)\s*:\s*(.*)$', re.I)

    def strip_noise(s):
        s = re.sub(r'^\s*(full\s*prompt|prompt)\s*:\s*', '', s, flags=re.I).strip()
        return s.strip('*').strip()

    scenes = []
    state = {"num": None, "body": []}

    def push():
        if state["num"] is not None:
            scenes.append({"num": state["num"],
                           "body": re.sub(r"\s+", " ", " ".join(state["body"])).strip()})

    for raw in lines:
        line = raw.strip()
        # Markdown bold markers ('**...**') around a scene header shouldn't
        # stop it being recognized — strip them just for the header check.
        line_clean = line.replace("**", "").strip()
        m = scene_re.match(line_clean)
        if m:
            push()
            state["num"] = m.group(1)
            state["body"] = [strip_noise(m.group(2))] if m.group(2) else []
            continue
        m = prompt_re.match(line_clean)
        if m:
            push()
            state["num"] = m.group(1)
            state["body"] = [strip_noise(m.group(2))] if m.group(2) else []
            continue
        if state["num"] is not None and line:
            state["body"].append(line)
    push()

    return [{"title": (f"Prompt {s['num']}:" if current_format == "prompt" else f"Scene_{s['num']}_"),
            "body": s["body"]} for s in scenes]


def _st_expand(body, chars, styles):
    """Same as expand(): replaces character names with their descriptions
    (twice, to catch names nested inside other characters' descriptions),
    strips explicit style-name references, then auto-appends every style
    value at the end. Matches a character name whether the scene text wrote
    it bare ('ANACONDA') or curly-brace wrapped ('{ANACONDA}') — either way
    the whole reference (braces included) is replaced by the description."""
    out = body
    for _pass in range(2):
        for item in chars:
            if not item["name"]:
                continue
            out = re.sub(r'\{?\b' + re.escape(item["name"]) + r'\b\}?', item["prompt"], out)
    for item in styles:
        if not item["name"]:
            continue
        out = re.sub(r',?\s*\{?\b' + re.escape(item["name"]) + r'\b\}?', '', out, flags=re.I)
    out = re.sub(r"\s+", " ", out).strip()
    out = re.sub(r",\s*$", "", out)
    style_text = ", ".join(s["prompt"] for s in styles)
    if style_text:
        out += ", " + style_text
    return re.sub(r"\s+", " ", out).strip()



def _st_split_sentences(text):
    parts = re.split(r'(?<=[.!?])\s+|\n+', (text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def _st_split_paragraphs(text):
    parts = re.split(r'\n+', (text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def _st_remove_numbering(text):
    return "\n".join(re.sub(r'^\d+[.)\-]\s*', '', line) for line in (text or "").split("\n"))


def _st_handle_suffix(prompts, suffix):
    matches = re.findall(r'Scene_\d+[_\s]*.*?(?=Scene_\d+[_\s]*|$)', prompts or "", re.S)
    matches = [m for m in matches if m.strip()]
    out = []
    for m in matches:
        c = " ".join(m.split())
        if suffix:
            c += " " + suffix
        out.append(c)
    return out


_ST_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif"}


def _st_ir_ext(name):
    dot = name.rfind(".")
    return name[dot:].lower() if dot > 0 else ""


def _st_ir_make_new_base(name):
    dot = name.rfind(".")
    stem = name[:dot] if dot > 0 else name
    base = stem.split("_")[0] if "_" in stem else stem
    return base.strip().lower() or "image"


def _st_ir_build_plan(names):
    used = set()
    plan = []
    for name in names:
        ext = _st_ir_ext(name)
        base = _st_ir_make_new_base(name)
        cand = base + ext
        i = 1
        while cand.lower() in used:
            cand = f"{base}_{i}{ext}"; i += 1
        used.add(cand.lower())
        plan.append((name, cand))
    return plan


# ════════════════════════════════════════════════════════════════
# RHYMES TAB  —  Bulk audio + bulk Scene_N_ videos → merged output
# ════════════════════════════════════════════════════════════════
def _rhymes_fmt_ts(sec):
    sec = max(0, int(round(float(sec))))
    return f"{sec//60:02d}:{sec%60:02d}"

def _rhymes_scene_num(path):
    m = re.search(r"[Ss]cene[_\-\s]*(\d+)", os.path.basename(path))
    return int(m.group(1)) if m else 10**9

def _rhymes_natural_key(value):
    """Small local natural-sort helper for Rhymes uploads.
    Kept local because the main app does not define natural_sort_key."""
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", str(value))]

def _rhymes_ffesc(s):
    return (str(s).replace("\\", "\\\\")
                  .replace(":", "\\:")
                  .replace("'", "\u2019")
                  .replace("%", "\\%")
                  .replace(",", "\\,"))

def _rhymes_build_drawtexts(txt_path):
    try:
        lines = open(txt_path, encoding="utf-8").read().splitlines()
    except Exception:
        return ""
    parts = []
    for ln in lines:
        m = re.match(r"\s*(\d+):(\d+)\s*-\s*(\d+):(\d+)\s*\[(.*)\]\s*$", ln)
        if not m:
            continue
        s = int(m.group(1))*60 + int(m.group(2))
        e = int(m.group(3))*60 + int(m.group(4))
        if e <= s:
            continue
        text = _rhymes_ffesc(m.group(5).strip() or "Music")
        parts.append(
            f"drawtext=text='{text}':fontcolor=white:fontsize=52:"
            f"borderw=5:bordercolor=black@0.85:"
            f"x=(w-text_w)/2:y=h-th-140:"
            f"enable='between(t\\,{s}\\,{e})'"
        )
    return ",".join(parts)

def _rhymes_clean_lyrics_text(text):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    text = re.sub(r"^(\[|\()?music(\]|\))?\s*", "", text, flags=re.I).strip()
    text = re.sub(r"^(instrumental|background music|applause|silence)$", "", text, flags=re.I).strip()
    return text

def _rhymes_seg_get(seg, key, default=None):
    if isinstance(seg, dict):
        return seg.get(key, default)
    return getattr(seg, key, default)

def _rhymes_result_segments(res):
    """Accept both app shim dicts and raw faster-whisper tuples/generators."""
    if res is None:
        return []
    try:
        if isinstance(res, dict):
            return list(res.get("segments") or [])
        if isinstance(res, tuple) and res:
            return list(res[0] or [])
        if isinstance(res, list):
            return list(res)
        segs = getattr(res, "segments", None)
        if segs is not None:
            return list(segs or [])
    except Exception:
        return []
    return []

def _rhymes_result_text(res):
    if res is None:
        return ""
    try:
        if isinstance(res, dict):
            return _rhymes_clean_lyrics_text(res.get("text", ""))
        txt = getattr(res, "text", "")
        if txt:
            return _rhymes_clean_lyrics_text(txt)
    except Exception:
        pass
    try:
        return _rhymes_clean_lyrics_text(" ".join(
            _rhymes_seg_get(seg, "text", "") for seg in _rhymes_result_segments(res)
        ))
    except Exception:
        return ""

def _rhymes_words_from_plain_text(text, duration):
    """Fallback for engines that return only full text without word timings."""
    clean = _rhymes_clean_lyrics_text(text)
    toks = [t.strip() for t in re.split(r"\s+", clean) if t.strip()]
    if not toks:
        return []
    duration = max(1.0, float(duration or 1.0))
    step = duration / max(1, len(toks))
    return [{"start": i * step, "end": min(duration, (i + 1) * step), "text": tok}
            for i, tok in enumerate(toks)]

def _rhymes_words_from_result(res):
    words = []
    for seg in _rhymes_result_segments(res):
        seg_start = float(_rhymes_seg_get(seg, "start", 0) or 0)
        seg_end = float(_rhymes_seg_get(seg, "end", seg_start) or seg_start)
        seg_text = _rhymes_clean_lyrics_text(_rhymes_seg_get(seg, "text", ""))
        raw_words = _rhymes_seg_get(seg, "words", None) or []
        if raw_words:
            for w in raw_words:
                txt = _rhymes_clean_lyrics_text(_rhymes_seg_get(w, "word", _rhymes_seg_get(w, "text", "")))
                if not txt:
                    continue
                st = float(_rhymes_seg_get(w, "start", seg_start) or seg_start)
                en = float(_rhymes_seg_get(w, "end", st) or st)
                words.append({"start": max(0.0, st), "end": max(st, en), "text": txt})
        elif seg_text:
            words.append({"start": max(0.0, seg_start), "end": max(seg_start, seg_end), "text": seg_text})
    return sorted(words, key=lambda w: (w["start"], w["end"]))

def _rhymes_make_8sec_lines(words, duration, chunk=8.0):
    duration = max(0.1, float(duration or 0.0))
    total_chunks = max(1, int(math.ceil(duration / chunk)))
    lines = []
    for i in range(total_chunks):
        start = i * chunk
        end = min(duration, (i + 1) * chunk)
        if end <= start or (i > 0 and (end - start) < 0.5):
            continue
        picked = []
        seen = set()
        for w in words:
            ws = float(w.get("start", 0.0))
            we = float(w.get("end", ws))
            mid = (ws + we) / 2.0
            if start <= mid < end or (i == total_chunks - 1 and start <= mid <= end):
                txt = _rhymes_clean_lyrics_text(w.get("text", ""))
                sig = (txt.lower(), round(mid, 2))
                if txt and sig not in seen:
                    picked.append(txt)
                    seen.add(sig)
        lyric = _rhymes_clean_lyrics_text(" ".join(picked)) or "Music"
        disp_start = int(round(start)) if i == 0 else int(round(start)) + 1
        disp_end = int(round(end))
        if i > 0 and disp_start >= disp_end:
            continue
        if disp_start > disp_end:
            disp_start = disp_end
        lines.append(f"{_rhymes_fmt_ts(disp_start)}-{_rhymes_fmt_ts(disp_end)} [{lyric}]")
    return lines or [f"00:00-{_rhymes_fmt_ts(duration)} [Music]"]

def _rhymes_ts_to_sec(value):
    s = str(value or "").strip().replace(",", ".")
    if not s:
        return 0.0
    parts = s.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(parts[0])
    except Exception:
        return 0.0

class RhymesEditorFrame(StoriesEditorFrame):
    """Rhymes tab — SAME UI as Stories (logo, PRO captions preview, sidebar,
    per-block controls, single 🎬 RENDER). Only differences:
      • Top toolbar has a '🎵 Upload Bulk Audio (Rhymes)' button. Each audio
        becomes one block, with that audio pre-loaded as the block's voice
        (so on RENDER it plays back like a normal Stories voiceover).
      • Every block gets an extra '📥 Transcript' button that runs Whisper
        on the block's audio and saves timestamps_<audio-name>.txt directly
        to the user's Downloads folder.
      • Each block also keeps the inherited 'Upload Video' button.
    """

    def __init__(self, master):
        super().__init__(master)
        # ElevenLabs Scribe only — no Whisper model selection.
        # 100% default rhymes vol, 0% clip vol (rhymes = voiceover, clips silent)
        self.rhymes_vol_var = ctk.DoubleVar(value=100.0)
        self.clip_audio_vol_var = ctk.DoubleVar(value=0.0)
        try: self._script_clip_mode.set("clip_eq_tts")
        except Exception: pass
        self._rhymes_strip_mode_panels()
        self._rhymes_strip_sidebar()
        self._rhymes_add_volume_panel()
        # Whisper/TurboScribe removed — ElevenLabs Scribe only.
        self._rhymes_install_upload_panel()

    # ── strip out MODE + Only-Video panels ──
    def _rhymes_strip_mode_panels(self):
        try:
            if hasattr(self, "mode_var"):
                try: self.mode_var.set("script")
                except Exception: pass
            try: self._toggle_mode()
            except Exception: pass
            for attr in ("mode_sec", "video_mode_frame"):
                w = getattr(self, attr, None)
                if w is not None:
                    try: w.destroy()
                    except Exception: pass
                    try: setattr(self, attr, None)
                    except Exception: pass
        except Exception as e:
            print("[RHYMES] strip mode panels:", e)

    # ── keep only LOGO / TRANSITION / CAPTIONS sections in sidebar ──
    def _rhymes_strip_sidebar(self):
        try:
            sb = getattr(self, "_sb_ref", None)
            if sb is None: return
            KEEP_TOKENS = ("LOGO", "TRANSITION", "CAPTION", "INTRO", "ELEVENLABS", "API")
            for child in list(sb.winfo_children()):
                try:
                    # Find the section title label inside this child
                    title = ""
                    if isinstance(child, (ctk.CTkFrame, ctk.CTkScrollableFrame)):
                        for sub in child.winfo_children():
                            if isinstance(sub, ctk.CTkLabel):
                                t = (sub.cget("text") or "").upper()
                                if t.strip():
                                    title = t; break
                    if not title:
                        child.destroy(); continue
                    # Preserve Help button + Video Type strip (no bordered title)
                    if any(tok in title for tok in KEEP_TOKENS):
                        continue
                    # Kill everything else (GPU, ElevenLabs, Script, Chars, Audio, Presets)
                    child.destroy()
                except Exception:
                    pass
        except Exception as e:
            print("[RHYMES] strip sidebar:", e)

    # ── new sidebar panel: Clip Audio Vol + Rhymes Audio Vol ──
    def _rhymes_add_volume_panel(self):
        try:
            sb = getattr(self, "_sb_ref", None)
            if sb is None: return
            panel = ctk.CTkFrame(sb, fg_color=C["card"],
                                 border_color="#ec4899", border_width=2,
                                 corner_radius=8)
            panel.grid(row=500, column=0, sticky="ew", padx=6, pady=(6, 4))
            ctk.CTkLabel(panel, text="█  AUDIO VOLUMES",
                         text_color="#ec4899",
                         font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=8, pady=(6, 4))
            # Rhymes audio (voiceover) — default 100%
            r1 = ctk.CTkFrame(panel, fg_color="transparent"); r1.pack(fill="x", padx=8, pady=3)
            ctk.CTkLabel(r1, text="🎵 Rhymes Audio:",
                         text_color=C["text"], font=("Segoe UI", 10, "bold"),
                         width=140, anchor="w").pack(side="left")
            self._rhy_vol_lbl = ctk.CTkLabel(r1, text="100%", text_color="#ec4899",
                                             font=("Segoe UI", 10, "bold"), width=45)
            self._rhy_vol_lbl.pack(side="right", padx=4)
            ctk.CTkSlider(panel, from_=0, to=200, number_of_steps=200,
                          variable=self.rhymes_vol_var,
                          progress_color="#ec4899", button_color="#ec4899",
                          command=lambda v: self._rhy_vol_lbl.configure(text=f"{int(float(v))}%")
                          ).pack(fill="x", padx=10, pady=(0, 6))
            # Clip (video's own) audio — default 0%
            r2 = ctk.CTkFrame(panel, fg_color="transparent"); r2.pack(fill="x", padx=8, pady=3)
            ctk.CTkLabel(r2, text="🎬 Clip Audio:",
                         text_color=C["text"], font=("Segoe UI", 10, "bold"),
                         width=140, anchor="w").pack(side="left")
            self._clip_vol_lbl = ctk.CTkLabel(r2, text="0%", text_color=C["orange"],
                                              font=("Segoe UI", 10, "bold"), width=45)
            self._clip_vol_lbl.pack(side="right", padx=4)
            ctk.CTkSlider(panel, from_=0, to=200, number_of_steps=200,
                          variable=self.clip_audio_vol_var,
                          progress_color=C["orange"], button_color=C["orange"],
                          command=lambda v: self._clip_vol_lbl.configure(text=f"{int(float(v))}%")
                          ).pack(fill="x", padx=10, pady=(0, 8))
            # Mirror into Master/Stories render vars so render path picks them up.
            # Master._gw reads _m_tts_vol / _m_clip_vol, not the older
            # clip_vol_var / tts_vol_var names, so wire the correct controls.
            try:
                def _sync_vols(*_a):
                    r = int(float(self.rhymes_vol_var.get() or 0))
                    c = int(float(self.clip_audio_vol_var.get() or 0))
                    if hasattr(self, "_m_tts_vol"): self._m_tts_vol.set(r)
                    if hasattr(self, "_m_clip_vol"): self._m_clip_vol.set(c)
                    if hasattr(self, "master_tts_vol_var"): self.master_tts_vol_var.set(100)
                    if hasattr(self, "master_vol_var"): self.master_vol_var.set(100)
                self.rhymes_vol_var.trace_add("write", _sync_vols)
                self.clip_audio_vol_var.trace_add("write", _sync_vols)
                _sync_vols()
            except Exception: pass
        except Exception as e:
            print("[RHYMES] volume panel:", e)


    # ── guaranteed visible upload panel above Rhymes blocks ──
    def _rhymes_install_upload_panel(self):
        try:
            tb = getattr(self, "_toolbar_ref", None)
            if tb is not None:
                for w in list(tb.winfo_children()):
                    try: w.destroy()
                    except Exception: pass
                ctk.CTkLabel(tb, text="█  RHYMES AUDIO BLOCKS",
                             text_color="#ec4899", font=("Segoe UI", 14, "bold")
                             ).pack(side="left", padx=10, pady=7)

            bkf = getattr(self, "bkf", None)
            if bkf is None: return
            panel = ctk.CTkFrame(bkf, fg_color="#241026", border_color="#ec4899",
                                 border_width=2, corner_radius=10, height=155)
            panel.pack(fill="x", padx=4, pady=(4, 8))
            panel.pack_propagate(False)
            btn_row = ctk.CTkFrame(panel, fg_color="transparent")
            btn_row.pack(fill="x", padx=14, pady=(12, 8))
            ctk.CTkButton(btn_row, text="🎵  UPLOAD AUDIO",
                          fg_color="#ec4899", hover_color="#f472b6",
                          text_color="#ffffff", height=52,
                          font=("Segoe UI", 18, "bold"),
                          command=self._rhymes_bulk_upload_audio
                          ).pack(side="left", fill="x", expand=True, padx=(0, 6))
            ctk.CTkButton(btn_row, text="🎬  UPLOAD VIDEOS",
                          fg_color="#22c55e", hover_color="#4ade80",
                          text_color="#000000", height=52,
                          font=("Segoe UI", 18, "bold"),
                          command=self._rhymes_bulk_upload_videos
                          ).pack(side="left", fill="x", expand=True, padx=(6, 0))
            ctk.CTkLabel(panel,
                         text="Transcripts auto-generate via ElevenLabs Scribe during render.  "
                              "Use 📥 Transcript on any block to save the 8-second .txt anytime.",
                         text_color=C["dim"], font=("Segoe UI", 10),
                         anchor="w", justify="left"
                         ).pack(fill="x", padx=16, pady=(0, 2))
            self._rhymes_upload_status = ctk.CTkLabel(
                panel, text="No audio loaded", text_color=C["dim"],
                font=("Segoe UI", 11, "bold"))
            self._rhymes_upload_status.pack(anchor="w", padx=16)

            # ── Save / Load last session ──
            sess_row = ctk.CTkFrame(panel, fg_color="transparent")
            sess_row.pack(fill="x", padx=14, pady=(4, 6))
            self._rhymes_auto_restore = ctk.BooleanVar(
                value=bool(bool(self.settings.get("rhymes_auto_restore"))))
            ctk.CTkCheckBox(sess_row, text="🔄 Auto-restore last session on startup",
                            variable=self._rhymes_auto_restore,
                            text_color=C["text"], fg_color="#ec4899", width=20,
                            command=self._rhymes_save_restore_pref
                            ).pack(side="left")
            ctk.CTkButton(sess_row, text="💾 Save", width=70, height=28,
                          fg_color=C["btn"], hover_color=C["btn_hov"],
                          text_color=C["text"], font=("Segoe UI", 10, "bold"),
                          command=self._rhymes_save_session
                          ).pack(side="right", padx=(4, 0))
            ctk.CTkButton(sess_row, text="📂 Load", width=70, height=28,
                          fg_color=C["btn"], hover_color=C["btn_hov"],
                          text_color=C["text"], font=("Segoe UI", 10, "bold"),
                          command=self._rhymes_load_session
                          ).pack(side="right", padx=(4, 0))

            # Auto-restore if enabled
            if self._rhymes_auto_restore.get():
                self.after(500, self._rhymes_load_session_silent)
        except Exception as e:
            print("[RHYMES] upload panel:", e)


    # ── bulk audio → blocks ──
    def _rhymes_bulk_upload_audio(self):
        try:
            paths = filedialog.askopenfilenames(
                parent=self, title="Select Rhymes audios",
                filetypes=[("Audio", "*.mp3 *.wav *.m4a *.aac *.ogg *.opus *.flac"),
                           ("All files", "*.*")])
        except Exception as e:
            messagebox.showerror("Audio upload", f"Audio picker open nahi ho paya:\n{e}", parent=self)
            return
        if not paths:
            return

        try:
            paths = sorted(list(paths), key=lambda p: _rhymes_natural_key(os.path.basename(p)))
        except Exception:
            paths = list(paths)

        made, errs = 0, []
        try:
            self._ss(f"Adding {len(paths)} rhymes audio block(s)…", C["orange"])
        except Exception: pass
        try:
            self._rhymes_upload_status.configure(text="Creating audio block(s)…", text_color=C["orange"])
        except Exception: pass
        try:
            self.update_idletasks()
        except Exception: pass

        for p in paths:
            try:
                self._rhymes_make_audio_block(str(p))
                made += 1
            except Exception as e:
                import traceback
                errs.append(f"{os.path.basename(str(p))}: {e}")
                print("[RHYMES] make block failed:", traceback.format_exc())

        try:
            self._update_filter()
        except Exception: pass
        try:
            self._on_filter("All", _fresh=True)
        except Exception: pass
        try:
            self.update_idletasks()
        except Exception: pass

        if errs:
            messagebox.showerror(
                "Some audios failed",
                f"Created {made} block(s).\n\nFailed:\n" + "\n".join(errs[:6]),
                parent=self)
        elif made:
            try: self.stl.configure(text=f"Loaded {made} rhymes audio(s).")
            except Exception: pass
            try: self._ss(f"✓ Loaded {made} rhymes audio block(s)", C["green"])
            except Exception: pass
            try: self._rhymes_upload_status.configure(
                text=f"✓ {len(self.blocks)} audio block(s) ready", text_color=C["green"])
            except Exception: pass

    # ── bulk videos → assign to blocks by Scene_N_ order ──
    def _rhymes_bulk_upload_videos(self):
        if not self.blocks:
            messagebox.showwarning("Upload Videos",
                "Pehle audio upload karo — blocks ban jaayenge, phir videos assign honge.",
                parent=self)
            return
        try:
            paths = filedialog.askopenfilenames(
                parent=self, title="Select Scene_N_ videos (bulk)",
                filetypes=[("Video", "*.mp4 *.mov *.avi *.mkv *.webm *.flv"),
                           ("All files", "*.*")])
        except Exception as e:
            messagebox.showerror("Video upload", f"Video picker open nahi ho paya:\n{e}", parent=self)
            return
        if not paths:
            return

        # Sort by Scene_N_ number if present, else natural filename order.
        def _scene_key(p):
            name = os.path.basename(str(p))
            m = re.search(r'(?:^|[_\-\s])(?:scene|scn|clip|s)[_\-\s]*(\d+)', name, re.I)
            if not m:
                m = re.search(r'_(\d+)_', name)
            if not m:
                m = re.search(r'(\d+)', name)
            num = int(m.group(1)) if m else 10**9
            return (num, _rhymes_natural_key(name))

        try:
            paths = sorted([str(p) for p in paths], key=_scene_key)
        except Exception:
            paths = [str(p) for p in paths]

        # Fill blocks that don't yet have a video, in order.
        assigned, skipped = 0, 0
        i = 0
        for p in paths:
            # find next block without a video
            while i < len(self.blocks) and (self.blocks[i].get("video") or "").strip():
                i += 1
            if i >= len(self.blocks):
                skipped = len(paths) - assigned
                break
            b = self.blocks[i]
            try:
                b["source_media"] = p
                b["media_type"] = "video"
                b["video"] = p
                b["trim_start"] = b["trim_end"] = None
                b["trimmed_loop_path"] = None
                try: b["trim_label"].configure(text="No trim")
                except Exception: pass
                try: self._queue_media_load(b, p, status_prefix="Video")
                except Exception:
                    try: self._block_status(b, f"🎬 {os.path.basename(p)}", C["green"])
                    except Exception: pass
                assigned += 1
                i += 1
            except Exception as e:
                print("[RHYMES] assign video failed:", e)

        try:
            msg = f"✓ Assigned {assigned} video(s) to blocks in Scene_ order."
            if skipped: msg += f" {skipped} extra video(s) skipped (no free block)."
            self._rhymes_upload_status.configure(text=msg, text_color=C["green"])
        except Exception: pass
        try: self._ss(msg, C["green"])
        except Exception: pass


    def _uvb(self, idx):
        """Rhymes override: pick MULTIPLE videos for one audio block.
        They are concatenated in Scene_N_ (or pick) order and trimmed to
        the audio's total duration, then set as this block's source video."""
        if idx < 0 or idx >= len(self.blocks):
            return
        b = self.blocks[idx]
        if not b.get("is_rhymes_audio"):
            try: return super()._uvb(idx)
            except Exception: return
        paths = filedialog.askopenfilenames(
            parent=self,
            title=f"Select videos for #{b.get('num','?')} (Scene_N_ order recommended)",
            filetypes=[("Video", "*.mp4 *.mov *.avi *.mkv *.webm *.flv *.m4v")])
        if not paths:
            return
        paths = [str(p) for p in paths]

        def _scene_key(p):
            m = re.search(r"[Ss]cene[_\-\s]*(\d+)", os.path.basename(p))
            return (0, int(m.group(1))) if m else (1, os.path.basename(p).lower())
        if any(re.search(r"[Ss]cene[_\-\s]*\d+", os.path.basename(p)) for p in paths):
            paths.sort(key=_scene_key)

        audio_dur = 0.0
        try: audio_dur = float(b.get("duration") or b.get("tts_duration") or 0.0)
        except Exception: audio_dur = 0.0
        if audio_dur <= 0:
            try: audio_dur = float(get_duration(b.get("tts_audio", "")) or 0.0)
            except Exception: audio_dur = 0.0

        try: self._block_status(b, f"⚙ Queued: merging {len(paths)} video(s)…", C["accent"])
        except Exception: pass
        threading.Thread(target=self._rhymes_concat_videos_worker,
                         args=(idx, paths, audio_dur), daemon=True).start()

    def _rhymes_concat_videos_worker(self, idx, paths, audio_dur):
        if idx < 0 or idx >= len(self.blocks): return
        b = self.blocks[idx]
        num = b.get("num", idx + 1)
        try:
            if len(paths) == 1 and (audio_dur is None or audio_dur <= 0):
                merged = paths[0]
            else:
                merged = os.path.join(TEMP_DIR, f"rhymes_merged_{num}.mp4")
                # Try fast concat demuxer (no re-encode of streams that match).
                list_txt = os.path.join(TEMP_DIR, f"rhymes_concat_{num}.txt")
                with open(list_txt, "w", encoding="utf-8") as f:
                    for p in paths:
                        esc = os.path.abspath(p).replace("\\", "/").replace("'", "'\\''")
                        f.write(f"file '{esc}'\n")
                cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_txt]
                if audio_dur and audio_dur > 0:
                    cmd += ["-t", f"{audio_dur:.3f}"]
                cmd += GPU.enc_args("fast") + ["-an", merged]
                ok = False
                try:
                    _run_ff(cmd, timeout=3600)
                    ok = os.path.exists(merged) and (get_duration(merged) or 0) > 0.1
                except Exception:
                    ok = False
                if not ok:
                    # Fallback: re-encode + normalise resolution/fps via filter_complex concat.
                    inputs = []
                    filters = []
                    for i, p in enumerate(paths):
                        inputs += ["-i", p]
                        filters.append(
                            f"[{i}:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
                            f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30,format=yuv420p[v{i}]")
                    concat_in = "".join(f"[v{i}]" for i in range(len(paths)))
                    fc = ";".join(filters) + f";{concat_in}concat=n={len(paths)}:v=1:a=0[vout]"
                    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", fc, "-map", "[vout]"]
                    if audio_dur and audio_dur > 0:
                        cmd += ["-t", f"{audio_dur:.3f}"]
                    cmd += GPU.enc_args("fast") + ["-an", merged]
                    _run_ff(cmd, timeout=7200)

            if not (os.path.exists(merged) and (get_duration(merged) or 0) > 0.1):
                try: self._block_status(b, "✗ Video merge failed", C["red"])
                except Exception: pass
                return

            b["source_media"] = merged
            b["media_type"]   = "video"
            b["video"]        = merged
            b["trim_start"]   = None
            b["trim_end"]     = None
            b["trimmed_loop_path"] = None
            try: b["trim_label"].configure(text="No trim")
            except Exception: pass

            dur = get_duration(merged) or 0.0
            msg = f"✓ {len(paths)} video(s) merged → {format_duration(dur)}"
            if audio_dur and dur + 0.05 < audio_dur:
                msg += f"  (⚠ shorter than audio {format_duration(audio_dur)})"
            try: self._block_status(b, msg, C["green"])
            except Exception: pass

            # Kick off standard media-load (thumbnail + duration cache).
            try: self._queue_media_load(b, merged, status_prefix="Video")
            except Exception: pass
        except Exception as e:
            try: self._block_status(b, f"Merge err: {e}", C["red"])
            except Exception: pass

    def _rhymes_make_audio_block(self, audio_path):
        """Build a self-contained Rhymes block row directly inside self.bkf.
        Does NOT depend on the inherited _make_block plumbing, so any base-
        class change can't silently break block creation here."""
        if not hasattr(self, "bkf") or self.bkf is None:
            raise RuntimeError("Scene container (bkf) not initialised")

        audio_path = str(audio_path)
        if not os.path.exists(audio_path):
            raise RuntimeError(f"Audio file not found: {audio_path}")
        num = len(self.blocks) + 1
        stem = Path(audio_path).stem
        char_name = f"_Rhyme_{num}"
        try:
            if char_name not in self.characters:
                self.characters[char_name] = {
                    "voice_name": "Uploaded Rhymes Audio", "voice_id": "_uploaded_rhymes_audio_",
                    "color_idx": (num - 1) % max(1, len(CHAR_COLORS)),
                    "is_scene": False}
                if char_name not in self.char_order:
                    self.char_order.append(char_name)
        except Exception:
            pass

        try:
            dur = float(get_duration(audio_path) or 0.0)
        except Exception:
            dur = 0.0

        # ── Row card (professional two-row layout) ────────────────
        cc_bg     = "#1f1030"
        cc_border = "#ec4899"
        row = ctk.CTkFrame(self.bkf, fg_color=cc_bg, border_color=cc_border,
                           border_width=2, corner_radius=10, height=108)
        row.pack(fill="x", padx=4, pady=5)
        row.pack_propagate(False)

        # Top row: number + filename + action buttons
        top = ctk.CTkFrame(row, fg_color="transparent")
        top.pack(fill="x", padx=8, pady=(8, 2))

        ctk.CTkLabel(top, text=f"#{num}", text_color="#ec4899",
                     font=("Segoe UI", 14, "bold"),
                     width=42).pack(side="left", padx=(2, 6))

        file_lbl = ctk.CTkLabel(
            top,
            text=f"🎵 {os.path.basename(audio_path)}   ·   {dur:.1f}s",
            text_color="#ffffff", font=("Segoe UI", 11, "bold"),
            anchor="w", justify="left")
        file_lbl.pack(side="left", fill="x", expand=True, padx=4)

        # Bottom row: progress bar + stage text + percent
        bot = ctk.CTkFrame(row, fg_color="transparent")
        bot.pack(fill="x", padx=10, pady=(2, 8))

        stage_lbl = ctk.CTkLabel(
            bot, text="● Idle", text_color="#94a3b8",
            font=("Segoe UI", 10, "bold"), width=210, anchor="w")
        stage_lbl.pack(side="left")

        pct_lbl = ctk.CTkLabel(
            bot, text="", text_color="#ec4899",
            font=("Segoe UI", 10, "bold"), width=44, anchor="e")
        pct_lbl.pack(side="right")

        prog = ctk.CTkProgressBar(
            bot, height=10, corner_radius=5,
            progress_color="#ec4899", fg_color="#2a1533")
        prog.set(0)
        prog.pack(side="left", fill="x", expand=True, padx=8)

        # Legacy status label alias (kept invisible; existing code writes to it)
        status_lbl = stage_lbl

        # Build the block dict FIRST so button commands can capture it
        block = {
            "num": num, "text": "", "caption_text": "", "character": char_name,
            "color_idx": (num - 1) % max(1, len(CHAR_COLORS)),
            "source_media": "", "media_type": "", "video": "",
            "output": "", "tts_audio": audio_path, "rhymes_audio": audio_path,
            "voice_generated": True, "tts_duration": dur, "duration": dur,
            "is_rhymes_audio": True,
            # Mark auto-captioned so the render pipeline skips the "Generate
            # voiceovers" step for this block (audio is already the rhyme)
            # AND uses whisper_segments (populated from ElevenLabs Scribe
            # transcript) to burn real lyric captions.
            "auto_captioned": True,
            "whisper_segments": [],
            "frame": row, "file_label": file_lbl, "status_label": status_lbl,
            "stage_label": stage_lbl, "progress_bar": prog, "pct_label": pct_lbl,
            "_prog_pulse": None,
            "trim_start": None, "trim_end": None, "trimmed_loop_path": None,
            "loop_mode": "pingpong", "video_only": False,
            "clip_volume": 0, "tts_volume": 100,
            "thumb_label": _NullWidget(), "trim_label": _NullWidget(),
            "txt_lbl": file_lbl,
        }
        self.blocks.append(block)
        idx = len(self.blocks) - 1

        try:
            row.update_idletasks()
        except Exception: pass
        try:
            self.bkf._parent_canvas.yview_moveto(1.0)
        except Exception: pass

        # ── Action buttons (right side of top row) ──
        ctk.CTkButton(top, text="✕", width=30, height=30,
                      fg_color="#3a1522", hover_color="#ef4444",
                      text_color="#ef4444", font=("Segoe UI", 12, "bold"),
                      command=lambda n=num: self._delete_block(n)
                      ).pack(side="right", padx=2)

        ctk.CTkButton(top, text="📥 Transcript", width=118, height=30,
                      fg_color="#ec4899", hover_color="#f472b6",
                      text_color="#ffffff", font=("Segoe UI", 10, "bold"),
                      command=lambda b=block: self._rhymes_download_transcript(b)
                      ).pack(side="right", padx=3)

        ctk.CTkButton(top, text="📁 Upload Video", width=138, height=30,
                      fg_color="#22c55e", hover_color="#4ade80",
                      text_color="#000000", font=("Segoe UI", 10, "bold"),
                      command=lambda i=idx: self._uvb(i)
                      ).pack(side="right", padx=3)

    def _gen_audio_worker(self, idx):
        """Rhymes blocks already have their final audio from upload.
        Do not call ElevenLabs / TTS for these blocks."""
        if 0 <= idx < len(self.blocks):
            b = self.blocks[idx]
            if b.get("is_rhymes_audio"):
                ap = b.get("rhymes_audio") or b.get("tts_audio")
                if ap and os.path.exists(ap):
                    b["tts_audio"] = ap
                    b["_tts_err"] = None
                    try:
                        self._block_status(b, f"🎵 Audio ready ({format_duration(get_duration(ap))})", C["green"])
                    except Exception: pass
                    return
        return super()._gen_audio_worker(idx)

    def _gw(self, idx):
        """Render Rhymes block — SELF-CONTAINED, no MRO chain.

        Three ffmpeg steps:
        1. Normalize source video → 1920x1080 30fps (GPU)
        2. Mux rhymes audio + normalized video → output
        3. Burn captions via story_apply_fx_captions (if ON)

        No Tk widgets are read — all values from snapshot or block dict.
        """
        if not (0 <= idx < len(self.blocks)):
            return
        b = self.blocks[idx]
        if not b.get("is_rhymes_audio"):
            return super()._gw(idx)

        num = b.get("num", "?")
        def st(msg, col=C["orange"]): self._block_status(b, msg, col)
        def log(msg): self._sss(f"[RHYMES #{num}] {msg}")

        # ── Validate inputs ──────────────────────────────────────────
        audio = b.get("rhymes_audio") or b.get("tts_audio")
        if not (audio and os.path.exists(audio)):
            st("Audio missing!", C["red"]); return

        video = b.get("source_media") or ""
        if not (video and os.path.exists(video)):
            st("Video missing!", C["red"]); return

        audio_dur = get_duration(audio) or 0
        if audio_dur < 0.1:
            st("Audio too short!", C["red"]); return

        uid = f"{self._render_session_uid()}_{num}_{abs(hash(video))%99999}"
        log(f"start: audio={os.path.basename(audio)} ({audio_dur:.1f}s), video={os.path.basename(video)}")

        # ── STEP 1: Normalize video → 1920x1080 30fps, trim to audio length ──
        st("[1/3] Normalize…", C["orange"])
        norm = os.path.join(TEMP_DIR, f"rhymes_norm_{uid}.mp4")
        vf = ("scale=1920:1080:force_original_aspect_ratio=decrease,"
              "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30,format=yuv420p")
        _run_ff(["ffmpeg", "-y", "-i", video, "-vf", vf,
                 "-r", "30", "-an", "-t", f"{audio_dur:.3f}",
                 "-loglevel", "error"] + GPU.enc_args("veryfast") + [norm], timeout=900)

        if not (os.path.exists(norm) and get_duration(norm) > 0.05):
            log("normalize failed — trying ultrafast CPU fallback")
            _run_ff(["ffmpeg", "-y", "-i", video, "-vf", vf,
                     "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                     "-pix_fmt", "yuv420p", "-r", "30", "-an",
                     "-t", f"{audio_dur:.3f}", "-loglevel", "error", norm], timeout=900)
        if not (os.path.exists(norm) and get_duration(norm) > 0.05):
            st("Normalize failed!", C["red"]); return

        # ── STEP 2: Mux audio + video ────────────────────────────────
        st("[2/3] Mux audio…", C["orange"])
        muxed = os.path.join(TEMP_DIR, f"rhymes_mux_{uid}.mp4")

        # Read volumes from snapshot (thread-safe)
        _rvs = getattr(self, "_render_vars_snapshot", {})
        tts_vol = _rvs.get("m_tts_vol", 100) / 100.0
        master_vol = _rvs.get("master_vol", 100) / 100.0
        clip_vol = _rvs.get("m_clip_vol", 0) / 100.0
        eff_audio_vol = tts_vol * master_vol
        eff_clip_vol = clip_vol * master_vol

        af_parts = []
        af_parts.append(f"[1:a]volume={eff_audio_vol:.3f}[a1]")
        if eff_clip_vol > 0.01:
            af_parts.append(f"[0:a]volume={eff_clip_vol:.3f}[a0]")
            af_parts.append("[a0][a1]amix=inputs=2:duration=first[aout]")
        else:
            af_parts.append("[a1]anull[aout]")

        _run_ff(["ffmpeg", "-y", "-i", norm, "-i", audio,
                 "-filter_complex", ";".join(af_parts),
                 "-map", "0:v", "-map", "[aout]",
                 "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                 "-t", f"{audio_dur:.3f}", "-movflags", "+faststart",
                 "-loglevel", "error", muxed], timeout=600)

        if not (os.path.exists(muxed) and self._has_video_track(muxed)):
            log("mux failed — simple copy fallback")
            _run_ff(["ffmpeg", "-y", "-i", norm, "-i", audio,
                     "-map", "0:v", "-map", "1:a",
                     "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                     "-t", f"{audio_dur:.3f}", "-movflags", "+faststart",
                     "-loglevel", "error", muxed], timeout=600)

        if not (os.path.exists(muxed) and self._has_video_track(muxed)):
            st("Audio mux failed!", C["red"]); return

        b["output"] = muxed
        b["tts_audio"] = audio
        dur = get_duration(muxed) or audio_dur
        log(f"muxed OK: {dur:.1f}s")

        # ── STEP 3: Burn captions (if ON) ────────────────────────────
        _snap = getattr(self, "_render_vars_snapshot", {})
        _opts_snap = getattr(self, "_rhymes_cap_opts_snapshot", None)
        cap_on = _snap.get("captions_on", _snap.get("cap_on", False))
        if _opts_snap and "captions_on" in _opts_snap:
            cap_on = _opts_snap["captions_on"]

        cap_text = (b.get("caption_text") or "").strip()
        log(f"captions: on={cap_on}, text_len={len(cap_text)}")

        if cap_on and cap_text:
            st(f"[3/3] 🅰 {len(cap_text.split())} words…", C["purple"])
            try:
                opts = {}
                if _opts_snap:
                    opts = dict(_opts_snap)
                else:
                    try: opts = self._story_opts()
                    except: opts = {}
                opts["captions_on"] = True
                opts["freeze_motion"] = "None"
                opts["freeze_speed"] = 1.0
                wt = None
                try: wt = self._stories_word_times(b, dur)
                except: pass
                if wt: opts["word_times"] = wt

                n_words = len(cap_text.split())
                def _prog(f, N):
                    pct = int(f * 100 / max(N, 1))
                    st(f"🅰 Captions: {pct}%", C["purple"])
                    self._render_step(3, f"Burning captions: {pct}%", sub=pct/100)

                cap_out = os.path.join(TEMP_DIR, f"rhymes_cap_{uid}.mp4")
                res = story_apply_fx_captions(
                    muxed, cap_out, "None", cap_text, dur, opts,
                    freeze_start=0.0, progress_cb=_prog)

                log(f"caption result: {res!r}, exists={os.path.exists(res) if res else 'N/A'}")

                if res and os.path.exists(res) and res != muxed and self._has_video_track(res):
                    b["output"] = res
                    st(f"✓ Done ({n_words} words, {format_duration(dur)})", C["green"])
                else:
                    log("caption burn returned original — captions NOT applied")
                    st(f"✓ Done (captions failed)", C["orange"])
            except Exception as e:
                import traceback
                log(f"caption error:\n{traceback.format_exc()[:400]}")
                st(f"✗ Caption error: {str(e)[:50]}", C["red"])
        else:
            st(f"✓ Done ({format_duration(dur)})", C["green"])

    # ── Auto-transcribe rhymes audio right before render, so real lyric
    # captions burn in even if the user never clicked 📥 Transcript. Also
    # filters out non-lyric tags (Music / Instrumental / etc.). ──
    def _rhymes_get_api_key(self):
        api_key = ""
        try:
            if hasattr(self, "api_entry"):
                api_key = (self.api_entry.get() or "").strip()
        except Exception: api_key = ""
        if not api_key:
            try: api_key = (self.settings.get("api_key") or "").strip()
            except Exception: pass
        if not api_key:
            api_key = (os.environ.get("ELEVENLABS_API_KEY") or "").strip()
        return api_key

    def _rhymes_scribe_words_sync(self, audio, api_key):
        """Blocking Scribe call with 24h cache. Cache hit = no API credit used."""
        import hashlib, json as _json
        _cache_path = None
        try:
            _sz = os.path.getsize(audio) if os.path.exists(audio) else 0
            _key = hashlib.md5(f"{os.path.abspath(audio)}|{_sz}".encode()).hexdigest()
            _cache_path = os.path.join(TEMP_DIR, f"scribe_cache_{_key}.json")
            if os.path.exists(_cache_path):
                _age = time.time() - os.path.getmtime(_cache_path)
                if _age < 86400:
                    cached = _json.loads(Path(_cache_path).read_text(encoding="utf-8"))
                    self._sss(f"[RHYMES] Scribe cache HIT ({int(_age/60)}min): {os.path.basename(audio)}")
                    return cached
        except Exception as _ce:
            self._sss(f"[RHYMES] cache read: {_ce}"); _cache_path = None
        # Down-mix large / exotic inputs to 16k mono MP3.
        upload_path = audio
        tmp_mp3 = None
        try: size = os.path.getsize(audio) if os.path.exists(audio) else 0
        except Exception: size = 0
        need_reencode = (not audio.lower().endswith((".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm"))
                         or size > 24 * 1024 * 1024)
        if need_reencode:
            tmp_mp3 = os.path.join(TEMP_DIR, f"rhymes_auto_{abs(hash((audio, time.time()))) % 10**9}.mp3")
            r = _run_ff(["ffmpeg", "-y", "-i", audio, "-vn", "-ac", "1",
                         "-ar", "16000", "-b:a", "64k", "-loglevel", "error", tmp_mp3],
                        timeout=900)
            if r is None or getattr(r, "returncode", 0) not in (0, None):
                raise RuntimeError("ffmpeg failed to prepare audio")
            upload_path = tmp_mp3
        try:
            with open(upload_path, "rb") as fh:
                files = {"file": (os.path.basename(upload_path), fh, "audio/mpeg")}
                data = {"model_id": "scribe_v1", "timestamps_granularity": "word",
                        "diarize": "false", "tag_audio_events": "false"}
                r = requests.post("https://api.elevenlabs.io/v1/speech-to-text",
                                  headers={"xi-api-key": api_key, "Accept": "application/json"},
                                  files=files, data=data, timeout=900)
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
            res = r.json()
        finally:
            if tmp_mp3:
                try: os.remove(tmp_mp3)
                except Exception: pass

        words_out = []
        for w in (res.get("words") or []):
            wtype = str(w.get("type") or "word").lower()
            # Skip non-verbal events entirely — no [Music] / [Applause] etc.
            if wtype not in ("word", "spacing", ""):
                continue
            txt = _rhymes_clean_lyrics_text(str(w.get("text") or ""))
            if not txt.strip(): continue
            try:
                st = float(w.get("start") or 0.0)
                en = float(w.get("end") or st)
            except Exception:
                continue
            words_out.append({"start": max(0.0, st), "end": max(st, en), "text": txt})
        words_out.sort(key=lambda x: (x["start"], x["end"]))
        try:
            if _cache_path and words_out:
                import json as _json
                Path(_cache_path).write_text(_json.dumps(words_out, ensure_ascii=False), encoding="utf-8")
                self._sss(f"[RHYMES] Scribe cached: {len(words_out)} words → 24h valid")
        except Exception: pass
        # Merge orphan "spacing" tokens (single spaces) into neighbours; the
        # cleaner already dropped bare tags so remaining spacing is fine.
        return words_out

    def _rhymes_words_to_segments(self, words, max_words=6, max_gap=1.2):
        """Group flat word list into short caption segments with word-level
        timing that the story caption pipeline consumes as whisper_segments."""
        def _flush(cur):
            if not cur: return None
            return {
                "start": cur[0]["start"],
                "end":   cur[-1]["end"],
                "text":  " ".join(w["text"] for w in cur),
                "words": [{"word": w["text"], "start": w["start"], "end": w["end"]} for w in cur],
            }
        segs, cur = [], []
        for w in words:
            if cur and (len(cur) >= max_words
                        or (w["start"] - cur[-1]["end"]) > max_gap):
                s = _flush(cur); cur = []
                if s: segs.append(s)
            cur.append(w)
        s = _flush(cur)
        if s: segs.append(s)
        return segs

    def _gen_captions(self):
        """RHYMES: Generate Captions button — uses Scribe, never Whisper.
        If transcript already exists → reuse it, no API call."""
        if not self.blocks:
            messagebox.showinfo("Captions", "Pehle audio upload karo.", parent=self); return
        try: self._story_cap_on.set(True)
        except Exception: pass
        try: self._story_save()
        except Exception: pass
        try: self._story_invalidate()
        except Exception: pass
        rhyme_blocks = [b for b in self.blocks if b.get("is_rhymes_audio")]
        already = [b for b in rhyme_blocks if (b.get("caption_text") or "").strip() or b.get("whisper_segments")]
        todo    = [b for b in rhyme_blocks if b not in already]
        if not todo:
            self._cap_lbl(f"✓ Existing transcript(s) — {len(already)} block(s)", C["green"])
            self._ss(f"Captions ON — {len(already)} block(s) ki pehle-se-bani transcript use hogi.", C["green"])
            return
        api_key = self._rhymes_get_api_key()
        if not api_key:
            messagebox.showerror("ElevenLabs API key missing",
                "Editor ke top me API key set karo.", parent=self); return
        note = f"{len(todo)} block(s) Scribe se transcribe honge."
        if already: note += f" ({len(already)} already done.)"
        self._cap_lbl(note, C["orange"]); self._ss(note, C["orange"])
        def _work():
            import os as _os, re as _re
            # PARALLEL Scribe — up to 3 blocks at once (cloud API, IO-bound)
            def _scribe_one(b_item):
                b, i = b_item
                ap = b.get("rhymes_audio") or b.get("tts_audio")
                if not (ap and _os.path.exists(ap)): return False
                try:
                    self._rhymes_prog_set(b, 0.30, stage=f"☁ Scribe {i}/{len(todo)}", color="#ec4899")
                    words = self._rhymes_scribe_words_sync(ap, api_key)
                    if not words:
                        self._rhymes_prog_set(b, 0.0, stage="● No lyrics", color="#f59e0b"); return False
                    segs = self._rhymes_words_to_segments(words)
                    text = " ".join(w["text"] for w in words).strip()
                    b["whisper_segments"] = segs; b["text"] = text
                    b["caption_text"] = text; b["auto_captioned"] = True
                    try:
                        dur = float(get_duration(ap) or b.get("duration") or 0.0) or 1.0
                        lines = _rhymes_make_8sec_lines(words, dur, chunk=8.0)
                        stem = _re.sub(r"[^A-Za-z0-9._ \-]+","_",Path(ap).stem).strip(" _")[:100] or "transcript"
                        tmp = _os.path.join(TEMP_DIR, f"rhymes_scribe_{stem}.txt")
                        Path(tmp).write_text("\n".join(lines)+"\n", encoding="utf-8")
                        b["ts_txt_temp"] = tmp
                    except Exception: pass
                    self._rhymes_prog_set(b, 1.0, stage=f"✓ {len(words)} words", color="#22c55e"); return True
                except Exception as e:
                    self._rhymes_prog_set(b, 0.0, stage=f"✗ {str(e)[:40]}", color="#ef4444"); return False

            done = 0
            with ThreadPoolExecutor(max_workers=3) as ex:
                futs = {ex.submit(_scribe_one, (b, i)): b for i, b in enumerate(todo, 1)}
                for fut in as_completed(futs):
                    try:
                        if fut.result(): done += 1
                    except Exception: pass

            def _fin():
                self._cap_lbl(f"✓ Captions ready — {len(already)+done} block(s)", C["green"])
                self._ss(f"✓ Scribe done: {done} new" + (f" + {len(already)} existing" if already else ""), C["green"])
            self.after(0, _fin)
        threading.Thread(target=_work, daemon=True).start()

    def _auto_caption_before_render(self):
        """Auto-transcribe missing blocks via parallel Scribe before render.
        User does NOT need to press Generate Captions — render handles it."""
        _snap = getattr(self, "_rhymes_cap_opts_snapshot", None) or                 getattr(self, "_render_vars_snapshot", None) or {}
        cap_on = _snap.get("captions_on", _snap.get("cap_on", False))
        if not cap_on: return

        missing = [b for b in self.blocks
                   if b.get("is_rhymes_audio")
                   and not (b.get("caption_text") or "").strip()
                   and not (b.get("whisper_segments") or [])]
        if not missing:
            self._sss("[RHYMES] pre-render: all blocks have transcripts ✓")
            return

        api_key = self._rhymes_get_api_key()
        if not api_key:
            self._sss("[RHYMES] pre-render: no API key — skipping auto-transcribe")
            return

        self._render_step(1, f"Auto-transcribing {len(missing)} block(s)…", sub=0.2)
        self._sss(f"[RHYMES] pre-render: auto-transcribing {len(missing)} blocks via Scribe (parallel)")

        def _scribe_one(item):
            b, i = item
            ap = b.get("rhymes_audio") or b.get("tts_audio")
            if not (ap and os.path.exists(ap)): return False
            try:
                self._rhymes_prog_set(b, 0.3, stage=f"☁ Auto-Scribe {i}/{len(missing)}", color="#ec4899")
                words = self._rhymes_scribe_words_sync(ap, api_key)
                if not words:
                    self._rhymes_prog_set(b, 0, stage="● No lyrics", color="#f59e0b"); return False
                segs = self._rhymes_words_to_segments(words)
                text = " ".join(w["text"] for w in words).strip()
                b["whisper_segments"] = segs; b["text"] = text
                b["caption_text"] = text; b["auto_captioned"] = True
                try:
                    dur = float(get_duration(ap) or b.get("duration") or 0) or 1.0
                    lines = _rhymes_make_8sec_lines(words, dur, chunk=8.0)
                    stem = re.sub(r"[^A-Za-z0-9._ \-]+","_",Path(ap).stem).strip(" _")[:100] or "t"
                    tmp = os.path.join(TEMP_DIR, f"rhymes_scribe_{stem}.txt")
                    Path(tmp).write_text("\n".join(lines)+"\n", encoding="utf-8")
                    b["ts_txt_temp"] = tmp
                except Exception: pass
                self._rhymes_prog_set(b, 1.0, stage=f"✓ {len(words)} words", color="#22c55e")
                return True
            except Exception as e:
                self._sss(f"[RHYMES] auto-scribe error: {e}")
                self._rhymes_prog_set(b, 0, stage=f"✗ {str(e)[:40]}", color="#ef4444")
                return False

        done = 0
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = {ex.submit(_scribe_one, (b, i)): b for i, b in enumerate(missing, 1)}
            for fut in as_completed(futs):
                try:
                    if fut.result(): done += 1
                except Exception: pass
                self._render_step(1, f"Transcribed {done}/{len(missing)}…",
                                  sub=0.2 + 0.7 * done / max(len(missing), 1))

        self._render_step(1, f"✓ {done}/{len(missing)} transcribed", sub=0.95)
        self._sss(f"[RHYMES] pre-render: auto-transcribed {done}/{len(missing)} blocks")

    # ── download-transcript action ──
    def _rhymes_default_transcript_path(self, audio):
        """Return a user-visible TXT path, named exactly from the audio file.
        Prefer Downloads, but gracefully fall back beside the audio / app output."""
        stem = Path(audio).stem
        safe_stem = re.sub(r"[^A-Za-z0-9._ \-]+", "_", stem).strip(" _")[:100] or "transcript"
        candidates = []
        try:
            candidates.append(Path.home() / "Downloads")
        except Exception:
            pass
        try:
            parent = Path(audio).resolve().parent
            if parent.exists():
                candidates.append(parent)
        except Exception:
            pass
        try:
            candidates.append(Path(OUTPUT_DIR))
        except Exception:
            pass
        try:
            candidates.append(Path(TEMP_DIR))
        except Exception:
            pass
        for folder in candidates:
            try:
                folder.mkdir(parents=True, exist_ok=True)
                test = folder / ".write_test.tmp"
                test.write_text("ok", encoding="utf-8")
                try: test.unlink()
                except Exception: pass
                return folder / f"{safe_stem}.txt"
            except Exception:
                continue
        return Path(f"{safe_stem}.txt")

    # ── Professional progress helpers ─────────────────────────────
    def _rhymes_prog_set(self, block, frac, stage=None, color="#ec4899"):
        """Thread-safe: set determinate progress on a block's row."""
        try: frac = max(0.0, min(1.0, float(frac)))
        except Exception: frac = 0.0
        def _apply():
            try:
                pb = block.get("progress_bar")
                if pb is not None:
                    pb.configure(progress_color=color); pb.set(frac)
                pl = block.get("pct_label")
                if pl is not None:
                    pl.configure(text=f"{int(frac*100)}%", text_color=color)
                if stage is not None:
                    sl = block.get("stage_label")
                    if sl is not None:
                        sl.configure(text=stage, text_color=color)
            except Exception: pass
        try: self.after(0, _apply)
        except Exception: _apply()

    def _rhymes_prog_pulse_start(self, block, stage, base=0.35, span=0.55, color="#ec4899"):
        """Animate an indeterminate 'working' sweep between base and base+span."""
        self._rhymes_prog_pulse_stop(block)
        state = {"t": 0.0, "on": True}
        block["_prog_pulse"] = state
        def _tick():
            if not state.get("on"): return
            import math
            state["t"] += 0.08
            frac = base + (span * (0.5 - 0.5 * math.cos(state["t"])))
            self._rhymes_prog_set(block, frac, stage=stage, color=color)
            try: self.after(90, _tick)
            except Exception: pass
        try: self.after(0, _tick)
        except Exception: pass

    def _rhymes_prog_pulse_stop(self, block):
        st = block.get("_prog_pulse")
        if st: st["on"] = False
        block["_prog_pulse"] = None

    def _rhymes_download_transcript(self, block):
        audio = block.get("tts_audio") or block.get("rhymes_audio")
        if not audio or not os.path.exists(audio):
            messagebox.showwarning("No audio",
                "This block has no audio to transcribe.", parent=self)
            return

        default_path = self._rhymes_default_transcript_path(audio)
        out_path = _asksaveasfilename_safe(
            parent=self,
            title="Save Rhymes Transcript",
            defaultextension=".txt",
            initialdir=str(default_path.parent),
            initialfile=default_path.name,
            filetypes=[("Text", "*.txt"), ("All files", "*.*")],
        )
        if not out_path:
            return
        out_path = str(out_path)
        if os.path.splitext(out_path)[1] == "":
            out_path += ".txt"

        # If we already have cached Scribe segments from a prior render,
        # just re-emit the 8-second .txt without hitting the API again.
        cached_segs = block.get("whisper_segments") or []
        cached_txt = block.get("ts_txt_temp")
        if cached_txt and os.path.exists(cached_txt):
            try:
                import shutil
                shutil.copyfile(cached_txt, out_path)
                block["ts_txt"] = out_path
                self._rhymes_prog_set(block, 1.0, stage=f"✓ Saved · {Path(out_path).name}", color="#22c55e")
                try: self.stl.configure(text=f"Transcript saved: {out_path}")
                except Exception: pass
                messagebox.showinfo("Transcript saved", f"Transcript saved to:\n{out_path}", parent=self)
                return
            except Exception:
                pass

        self._rhymes_prog_set(block, 0.02, stage="⏳ Queued · ElevenLabs Scribe", color="#f59e0b")
        try: self.stl.configure(text="Generating transcript via ElevenLabs Scribe…")
        except Exception: pass
        threading.Thread(target=self._rhymes_transcript_worker,
                         args=(block, audio, out_path), daemon=True).start()


    def _rhymes_transcript_worker(self, block, audio, out_txt, model_size="medium"):
        """Transcribe rhyme audio using ElevenLabs Speech-to-Text (Scribe).

        Uses the ElevenLabs API key already configured at the top of the editor
        (self.api_entry / settings['api_key']). Output is broken down into
        fixed 8-second chunks and written to the .txt file.
        """
        def _ui_error(title, msg):
            self._rhymes_prog_pulse_stop(block)
            self._rhymes_prog_set(block, 1.0, stage=f"✗ {title}", color="#ef4444")
            self.after(0, lambda t=title, m=str(msg): messagebox.showerror(t, m, parent=self))

        # ── API key ────────────────────────────────────────────────
        api_key = ""
        try:
            if hasattr(self, "api_entry"):
                api_key = (self.api_entry.get() or "").strip()
        except Exception:
            api_key = ""
        if not api_key:
            try: api_key = (self.settings.get("api_key") or "").strip()
            except Exception: pass
        if not api_key:
            api_key = (os.environ.get("ELEVENLABS_API_KEY") or "").strip()
        if not api_key:
            _ui_error("ElevenLabs API key missing",
                      "ElevenLabs API key nahi mila. Editor ke top me API key set karo.")
            return

        try: dur = float(get_duration(audio) or block.get("duration") or 0.0)
        except Exception: dur = float(block.get("duration") or 0.0)
        if dur <= 0:
            dur = 1.0

        # Stage 1/3 — prepare audio
        self._rhymes_prog_set(block, 0.10, stage="🎧 [1/3] Preparing audio…", color="#f59e0b")
        # ElevenLabs Scribe accepts common formats directly. For huge/long inputs
        # (or non-standard containers) we down-mix to 16 kHz mono MP3 to keep the
        # upload small and reliable. Skip re-encode if file already ≤ 24 MB.
        upload_path = audio
        tmp_mp3 = None
        try:
            size = os.path.getsize(audio) if os.path.exists(audio) else 0
        except Exception:
            size = 0
        need_reencode = (not audio.lower().endswith((".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm"))
                         or size > 24 * 1024 * 1024)
        if need_reencode:
            tmp_mp3 = os.path.join(TEMP_DIR, f"rhymes_el_{abs(hash((audio, time.time()))) % 10**9}.mp3")
            try:
                result = _run_ff(["ffmpeg", "-y", "-i", audio,
                                  "-vn", "-ac", "1", "-ar", "16000",
                                  "-b:a", "64k", "-loglevel", "error", tmp_mp3],
                                 timeout=900)
                if result is None or getattr(result, "returncode", 0) not in (0, None):
                    err = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "")[:400] if result else ""
                    raise RuntimeError(err or "ffmpeg couldn't prepare audio for upload.")
                if not (os.path.exists(tmp_mp3) and os.path.getsize(tmp_mp3) > 1024):
                    raise RuntimeError("Prepared MP3 not created.")
                upload_path = tmp_mp3
            except Exception as e:
                _ui_error("Audio prep failed", e)
                return

        self._rhymes_prog_set(block, 0.25, stage="🎧 [1/3] Audio ready", color="#f59e0b")

        # Stage 2/3 — upload + transcribe
        self._rhymes_prog_pulse_start(
            block, "☁ [2/3] ElevenLabs Scribe transcribing…",
            base=0.30, span=0.50, color="#ec4899")

        res = None
        try:
            with open(upload_path, "rb") as fh:
                files = {"file": (os.path.basename(upload_path), fh, "audio/mpeg")}
                data = {
                    "model_id": "scribe_v1",
                    "timestamps_granularity": "word",
                    "diarize": "false",
                    "tag_audio_events": "false",
                }
                r = requests.post(
                    "https://api.elevenlabs.io/v1/speech-to-text",
                    headers={"xi-api-key": api_key, "Accept": "application/json"},
                    files=files, data=data, timeout=900,
                )
            if r.status_code >= 400:
                body = ""
                try: body = r.text[:500]
                except Exception: pass
                raise RuntimeError(f"HTTP {r.status_code}: {body}")
            res = r.json()
        except Exception as e:
            self._rhymes_prog_pulse_stop(block)
            if tmp_mp3:
                try: os.remove(tmp_mp3)
                except Exception: pass
            _ui_error("ElevenLabs error", e)
            return
        finally:
            if tmp_mp3:
                try:
                    if os.path.exists(tmp_mp3): os.remove(tmp_mp3)
                except Exception: pass

        self._rhymes_prog_pulse_stop(block)
        self._rhymes_prog_set(block, 0.85, stage="🧩 [3/3] Building 8s chunks…", color="#22c55e")

        # ── Normalize ElevenLabs response into our internal segment/word shape.
        # Scribe returns: { "text": "...", "words": [{"text","start","end","type"}], ... }
        words_out = []
        raw_words = (res or {}).get("words") or []
        for w in raw_words:
            wtype = str(w.get("type") or "word").lower()
            if wtype not in ("word", "spacing", ""):
                # Skip audio_event, non-verbal tags etc.
                if wtype != "audio_event":
                    continue
                else:
                    continue
            txt = _rhymes_clean_lyrics_text(str(w.get("text") or ""))
            if not txt or not txt.strip():
                continue
            try:
                st = float(w.get("start") or 0.0)
                en = float(w.get("end") or st)
            except Exception:
                continue
            words_out.append({"start": max(0.0, st), "end": max(st, en), "text": txt})

        if words_out:
            words = sorted(words_out, key=lambda x: (x["start"], x["end"]))
        else:
            # No word timings — fall back to distributing full text across duration.
            words = _rhymes_words_from_plain_text(str((res or {}).get("text") or ""), dur)

        lines = _rhymes_make_8sec_lines(words, dur, chunk=8.0)

        try:
            out_path = Path(out_txt)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception as e:
            _ui_error("Write failed", e)
            return

        block["ts_txt"] = str(out_path)
        # ── Cache caption data on the block so the render pipeline
        # reuses it instead of transcribing a second time. ──
        try:
            if words_out:
                segs = self._rhymes_words_to_segments(words_out)
                cap_text = " ".join(w["text"] for w in words_out).strip()
                block["whisper_segments"] = segs
                block["text"] = cap_text
                block["caption_text"] = cap_text
                block["auto_captioned"] = True
        except Exception as _e:
            self._sss(f"[RHYMES] segment cache failed: {_e}")

        self._rhymes_prog_set(block, 1.0, stage=f"✓ Saved · {out_path.name}", color="#22c55e")
        def _done():
            try: self.stl.configure(text=f"Transcript saved: {out_path}")
            except Exception: pass
            messagebox.showinfo("Transcript saved", f"Timestamps saved to:\n{out_path}", parent=self)
        self.after(0, _done)

    def _story_opts(self):
        """Return caption opts from snapshot (thread-safe) or live widgets."""
        snap = getattr(self, "_rhymes_cap_opts_snapshot", None)
        if snap and len(snap) > 3:  # ensure it's a real snapshot, not empty
            return dict(snap)
        try:
            return super()._story_opts()
        except Exception:
            return dict(snap) if snap else {}

    def _render_plan(self, save_path=None):
        """Rhymes pipeline — 3 steps: Preflight, Merge, Burn+Logo, Done."""
        plan = super()._render_plan()
        snap = getattr(self, "_rhymes_cap_opts_snapshot", None) or {}
        try:    cap_on = bool(snap.get("captions_on", False)) or bool(self._story_cap_on.get())
        except: cap_on = snap.get("captions_on", False)
        try:
            n_logos = (1 if (self.logo_path_var.get() and self.settings.get("logo_enabled")) else 0)
            n_logos += len(getattr(self, "_extra_logos", []))
        except: n_logos = 0

        # ── Steps ──
        steps = [(1,"Preflight checks"), (3,"Merge scenes (video + audio)")]
        if cap_on or n_logos:
            steps.append((6, "Burn captions" if (cap_on and not n_logos) else
                             "Overlay logo"  if (n_logos and not cap_on) else
                             "Burn captions + logo"))
        steps.append((9,"Done"))
        plan["steps"] = steps; plan["scripted"] = 0

        # ── Summary (Rhymes-specific: no freeze-frame, no BGM, no TTS) ──
        clips = len(self.blocks)
        autocap = sum(1 for b in self.blocks if b.get("auto_captioned"))
        cap_style = snap.get("style", "")
        cap_mode = snap.get("mode", "")
        cap_info = f"{cap_style} / {cap_mode}" if cap_style else "on"
        try: tr_on = bool(self._m_tr_on.get())
        except: tr_on = False
        try: tr_dur = float(self._m_tr_dur.get())
        except: tr_dur = 0.5

        summary = [("🎞", "Video clips", f"{clips} scene(s)", True)]
        if autocap: summary.append(("🎤", "Clip audio kept", f"{autocap} auto-captioned scene(s)", True))
        if cap_on:  summary.append(("🅰", "Captions", cap_info, True))
        if tr_on:   summary.append(("🔀", "Transitions", f"on • {tr_dur:g}s", True))
        if n_logos: summary.append(("🖼", "Logos", f"{n_logos} logo(s)", True))
        plan["summary"] = summary
        return plan

    def _stories_burn_captions(self, b):
        """RHYMES: burn captions via ASS subtitle direct ffmpeg burn.
        Bypasses PIL frame loop — 10x faster, always works."""
        op = b.get("output") or ""
        num = b.get("num", "?")
        if not (op and os.path.exists(op)): return
        dur = get_duration(op)
        if dur <= 0.1: return

        # cap_on: try snapshot first (thread-safe), fallback to widget
        snap = getattr(self, "_rhymes_cap_opts_snapshot", None)
        if snap and "captions_on" in snap:
            cap_on = bool(snap["captions_on"])
        else:
            try: cap_on = bool(self._story_cap_on.get())
            except: cap_on = True  # default ON if widget unreadable

        text = (b.get("caption_text") or b.get("text") or "").strip() if cap_on else ""
        if not text: return

        try:
            opts = self._stories_cap_opts(b, dur)
        except Exception as e:
            self._sss(f"[RHYMES #{num}] cap_opts error: {e}"); return
        opts["captions_on"] = True
        opts["freeze_motion"] = "None"; opts["freeze_speed"] = 1.0
        n_words = len(text.split())

        self._sss(f"[RHYMES #{num}] burning captions: {n_words} words via story_apply_fx")
        try:
            self._block_status(b, f"🅰 {n_words} words burning…", C["purple"])
            out = os.path.join(TEMP_DIR,
                f"rhymes_cap_{self._render_session_uid()}_{num}_{abs(hash(op))%99999}.mp4")

            # Progress callback
            def _cap_progress(f, N):
                pct = int(f * 100 / max(N, 1))
                self._block_status(b, f"🅰 Captions: {pct}%…", C["purple"])
                self._render_step(3, f"Burning captions: {pct}%", sub=pct/100)

            res = story_apply_fx_captions(
                op, out, "None", text, dur, opts,
                freeze_start=0.0, progress_cb=_cap_progress)

            self._sss(f"[RHYMES #{num}] result: {res!r}, exists={os.path.exists(res) if res else False}")
            if res and os.path.exists(res) and res != op and self._has_video_track(res):
                b["output"] = res
                self._block_status(b, f"✓ Captions done ({n_words} words)", C["green"])
            elif res == op:
                self._block_status(b, "✓ Done", C["green"])
            else:
                self._sss(f"[RHYMES #{num}] caption burn failed — keeping original")
                self._block_status(b, "✓ Done (caption pass failed)", C["orange"])
        except Exception as e:
            import traceback
            self._sss(f"[RHYMES #{num}] caption error:\n{traceback.format_exc()[:400]}")
            self._block_status(b, f"✗ {str(e)[:60]}", C["red"])

    def _mw(self, clips, sp):
        """RHYMES _mw: skip normalize+finalize, direct join → logo → done."""
        import shutil as _sh
        step = self._render_step
        clips = [c for c in clips if c and os.path.exists(c)]
        if not clips:
            self._ss("No rendered clips!", C["red"]); return

        # ── Join blocks ──────────────────────────────────────────────
        if len(clips) == 1:
            merged = clips[0]
        else:
            merged = os.path.join(TEMP_DIR, f"rhymes_join_{self._render_session_uid()}.mp4")
            use_tr = bool(getattr(self,"_m_tr_on",None) and self._m_tr_on.get())
            tr_types = [t for t,v in (getattr(self,"_m_tr_vars",{}) or {}).items() if v.get()]
            tr_dur = max(0.2, float(getattr(self,"_m_tr_dur",None) and self._m_tr_dur.get() or 0.5))
            ok = False
            if use_tr and tr_types:
                step(3, f"Joining {len(clips)} blocks with transitions…", sub=0.4)
                r = _merge_with_transitions(clips, tr_types, tr_dur, merged, logf=lambda m:self._sss(m))
                ok = bool(r and os.path.exists(merged) and self._has_video_track(merged))
            if not ok:
                step(3, f"Joining {len(clips)} blocks…", sub=0.4)
                lst = os.path.join(TEMP_DIR, f"rhymes_lst_{self._render_session_uid()}.txt")
                with open(lst,"w") as f:
                    for c in clips: f.write(f"file '{os.path.abspath(c)}'\n")
                _run_ff(["ffmpeg","-y","-f","concat","-safe","0","-i",lst,
                         "-c","copy","-movflags","+faststart","-loglevel","error",merged], timeout=3600)
            if not self._has_video_track(merged):
                fc_parts=[]; inputs=[]
                for j,c in enumerate(clips): inputs+=["-i",c]; fc_parts.append(f"[{j}:v:0][{j}:a:0]")
                fc="".join(fc_parts)+f"concat=n={len(clips)}:v=1:a=1[v][a]"
                _run_ff(["ffmpeg","-y"]+inputs+["-filter_complex",fc,"-map","[v]","-map","[a]"]+
                        GPU.enc_args("veryfast")+["-c:a","aac","-b:a","192k","-movflags","+faststart",
                        "-loglevel","error",merged], timeout=3600)

        if not self._has_video_track(merged):
            self._ss("Join failed!", C["red"]); return
        step(3, f"✓ {len(clips)} block(s) ready", sub=1.0, finished=True)

        # ── Save ─────────────────────────────────────────────────────
        try:
            if os.path.abspath(merged) != os.path.abspath(sp): _sh.copy2(merged, sp)
        except Exception:
            try: _sh.move(merged, sp)
            except Exception as e: self._ss(f"Save failed: {e}", C["red"]); return

        # ── Logo ─────────────────────────────────────────────────────
        step(6, "Burn logo…", sub=0.5)
        try: self._apply_all_logos_final(sp)
        except Exception as e: self._sss(f"[RHYMES LOGO] {e}")
        step(6, "✓ Done", sub=1.0, finished=True)

        self._sp(1.0)
        if os.path.exists(sp) and self._has_video_track(sp):
            dur = format_duration(get_duration(sp))
            step(9, f"✓ Done! {dur} → {os.path.basename(sp)}", finished=True)
            self._ss(f"✓ Done! {dur} → {os.path.basename(sp)}", C["green"])
        else:
            self._ss("Save failed!", C["red"])


    # ── Session save / load ─────────────────────────────────────────
    _RHYMES_SESSION_FILE = os.path.join(
        os.path.expanduser("~"), ".rhymes_editor_session.json")

    def _rhymes_save_restore_pref(self):
        self.settings.set("rhymes_auto_restore", bool(self._rhymes_auto_restore.get()))
        self.settings.save()

    def _rhymes_save_session(self):
        """Save current blocks (audio paths, video paths, captions) to JSON."""
        import json
        data = {"blocks": []}
        for b in self.blocks:
            entry = {
                "rhymes_audio":   b.get("rhymes_audio") or b.get("tts_audio") or "",
                "source_media":   b.get("source_media") or "",
                "caption_text":   b.get("caption_text") or "",
                "text":           b.get("text") or "",
                "is_rhymes_audio": bool(b.get("is_rhymes_audio")),
                "auto_captioned": bool(b.get("auto_captioned")),
                "whisper_segments": b.get("whisper_segments") or [],
                "video_paths":    b.get("_rhymes_video_paths") or [],
            }
            data["blocks"].append(entry)
        try:
            Path(self._RHYMES_SESSION_FILE).write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            n = len(data["blocks"])
            self._rhymes_upload_status.configure(
                text=f"✓ Session saved ({n} block{'s' if n!=1 else ''})",
                text_color=C["green"])
            self._sss(f"[RHYMES] session saved: {n} blocks → {self._RHYMES_SESSION_FILE}")
        except Exception as e:
            messagebox.showerror("Save", f"Session save failed: {e}", parent=self)

    def _rhymes_load_session(self):
        """Load saved session — restore blocks with audio, video, captions."""
        self._rhymes_load_session_silent(notify=True)

    def _rhymes_load_session_silent(self, notify=False):
        """Restore session from JSON. If notify=False, fail silently."""
        import json
        sf = self._RHYMES_SESSION_FILE
        if not os.path.exists(sf):
            if notify:
                messagebox.showinfo("Load", "No saved session found.", parent=self)
            return
        try:
            data = json.loads(Path(sf).read_text(encoding="utf-8"))
        except Exception as e:
            if notify: messagebox.showerror("Load", f"Read error: {e}", parent=self)
            return

        blocks_data = data.get("blocks") or []
        if not blocks_data:
            if notify: messagebox.showinfo("Load", "Saved session is empty.", parent=self)
            return

        # Clear existing blocks
        while self.blocks:
            try: self._delete_block(self.blocks[0].get("num", 1))
            except Exception: self.blocks.pop(0)

        restored = 0
        for entry in blocks_data:
            audio = entry.get("rhymes_audio") or ""
            if not (audio and os.path.exists(audio)):
                self._sss(f"[RHYMES] session restore: audio missing {audio}")
                continue

            # Create block from audio
            try:
                self._rhymes_make_audio_block(audio)
            except Exception as e:
                self._sss(f"[RHYMES] block create error: {e}")
                continue

            b = self.blocks[-1]  # last added block

            # Restore caption text + segments
            ct = entry.get("caption_text") or ""
            if ct:
                b["caption_text"] = ct
                b["text"] = ct
                b["auto_captioned"] = True
            segs = entry.get("whisper_segments")
            if segs:
                b["whisper_segments"] = segs

            # Restore video(s)
            video_paths = entry.get("video_paths") or []
            sm = entry.get("source_media") or ""
            if video_paths:
                # Re-concat videos if paths still exist
                valid = [p for p in video_paths if os.path.exists(p)]
                if valid:
                    idx = len(self.blocks) - 1
                    b["_rhymes_video_paths"] = valid
                    audio_dur = get_duration(audio) or 0
                    if len(valid) == 1:
                        b["source_media"] = valid[0]
                        try: self._block_status(b, f"🎬 {os.path.basename(valid[0])}", C["green"])
                        except: pass
                    else:
                        # Trigger concat in background
                        import threading
                        threading.Thread(
                            target=self._rhymes_concat_videos_worker,
                            args=(idx, valid, audio_dur), daemon=True).start()
            elif sm and os.path.exists(sm):
                b["source_media"] = sm
                try: self._block_status(b, f"🎬 {os.path.basename(sm)}", C["green"])
                except: pass

            restored += 1

        msg = f"✓ Restored {restored} block{'s' if restored!=1 else ''}"
        try:
            self._rhymes_upload_status.configure(text=msg, text_color=C["green"])
        except: pass
        self._sss(f"[RHYMES] session loaded: {restored}/{len(blocks_data)} blocks restored")
        if notify and restored:
            try: self._story_cap_on.set(True)
            except: pass

    def _rhymes_make_audio_block_save_paths(self, b, video_paths):
        """Store video paths in block for session save."""
        b["_rhymes_video_paths"] = list(video_paths)

    def _rhymes_reset_status(self, block):
        self._rhymes_prog_pulse_stop(block)
        self._rhymes_prog_set(block, 0.0, stage="● Idle", color="#94a3b8")






def _build_rhymes(frame):
    container = ctk.CTkFrame(frame, fg_color=C["bg"], corner_radius=0)
    try:
        container.pack(fill="both", expand=True)
    except Exception:
        container.grid(row=0, column=0, sticky="nsew")
        try:
            frame.grid_columnconfigure(0, weight=1)
            frame.grid_rowconfigure(0, weight=1)
        except Exception:
            pass
    container.grid_columnconfigure(0, weight=1); container.grid_rowconfigure(1, weight=1)
    header = ctk.CTkFrame(container, fg_color=C["card"], height=50, corner_radius=0)
    header.grid(row=0, column=0, sticky="ew"); header.grid_propagate(False)
    ctk.CTkLabel(header, text="🎶  RHYMES EDITOR", text_color="#ec4899",
                 font=("Segoe UI", 16, "bold")).pack(side="left", padx=15, pady=10)
    ctk.CTkLabel(header, text=f"v{APP_VERSION} • {GPU.info_str()}",
                 text_color=C["dim"], font=("Segoe UI", 10)).pack(side="left", padx=10)
    _res_var = ctk.StringVar(value=_OUTPUT_RES_CHOICE)
    ctk.CTkLabel(header, text="Output:", text_color=C["dim"],
                 font=("Segoe UI", 11)).pack(side="right", padx=(6,2))
    ctk.CTkOptionMenu(header, variable=_res_var, values=list(_OUTPUT_PRESETS.keys()),
                      width=130, fg_color=C["btn"], button_color=C["btn_hov"],
                      command=lambda v: _set_output_res(v)).pack(side="right", padx=(0,12), pady=8)
    ctk.CTkButton(header, text="🎨 Theme", width=90, height=30, fg_color=C["btn"],
                 hover_color=C["btn_hov"], text_color=C["text"], font=("Segoe UI", 11),
                 command=lambda: _open_theme_picker(header)).pack(side="right", padx=(0, 8), pady=8)
    body = ctk.CTkFrame(container, fg_color=C["bg"], corner_radius=0)
    body.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
    body.grid_columnconfigure(0, weight=1); body.grid_rowconfigure(0, weight=1)
    RhymesEditorFrame(body).grid(row=0, column=0, sticky="nsew")

def create(parent_frame, boot_data=None):
    """Plugin-compatible create — tabs/ mein daalo, tab ban jayega."""
    _build_rhymes(parent_frame)


def launch_app(root=None):
    """Root window banao (ya existing reuse karo), boot screen dikhao, phir tab UI mount karo.

    SINGLE-ROOT FIX: `root` agar diya gaya hai (login window se, main.py se
    passed), usi ko reuse karo — naya ctk.CTk() mat banao. Poori app ke
    process mein hamesha sirf EK Tk root hona chahiye; pehle yeh function
    apna khud ka teesra alag root banata tha (login + update-check ke baad),
    jo customtkinter ke internal DPI/theme tracking ko corrupt karta tha."""
    ctk.set_appearance_mode("dark")
    if root is None:
        root = ctk.CTk()
    else:
        # Reused root abhi login se withdrawn/hidden hai — saaf karo aur
        # dikhao.
        for child in root.winfo_children():
            try: child.destroy()
            except Exception: pass
        root.deiconify()
        root.resizable(True, True)  # login window disables resizing; main app needs it back

    try:
        from updater import CURRENT_VERSION
        ver = CURRENT_VERSION
    except Exception:
        ver = "dev"

    root.title(f"{TITLE} — v{ver}")
    root.geometry("1450x800")
    root.minsize(1200, 680)
    root.configure(fg_color=C["bg"])

    # App icon
    try:
        _base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        root.iconbitmap(os.path.join(_base, "app_icon.ico"))
    except Exception:
        pass

    # ═══════════════════════════════════════════════════
    # BOOT SCREEN — smooth loading like Windows startup
    # ═══════════════════════════════════════════════════
    boot = ctk.CTkFrame(root, fg_color=C["bg"])
    boot.pack(fill="both", expand=True)

    boot.update_idletasks()
    card = ctk.CTkFrame(boot, fg_color=C["card"], corner_radius=20,
                        border_width=1, border_color=C["border"], width=500, height=380)
    card.place(relx=0.5, rely=0.5, anchor="center")
    card.pack_propagate(False)

    ctk.CTkLabel(card, text="🎬", font=("Segoe UI", 52)).pack(pady=(35, 5))
    ctk.CTkLabel(card, text="RHYMES EDITOR", text_color="#ec4899",
                 font=("Segoe UI", 28, "bold")).pack(pady=(0, 3))
    ctk.CTkLabel(card, text=f"v{ver}", text_color=C["dim"],
                 font=("Segoe UI", 12)).pack()

    boot_status = ctk.CTkLabel(card, text="Initializing...", text_color=C["text"],
                               font=("Segoe UI", 12))
    boot_status.pack(pady=(25, 8))

    boot_bar = ctk.CTkProgressBar(card, height=8, corner_radius=4,
                                   progress_color=C["accent"], fg_color=C["border"],
                                   width=350)
    boot_bar.pack(pady=(0, 5))
    boot_bar.set(0)

    boot_pct = ctk.CTkLabel(card, text="0%", text_color=C["dim"],
                             font=("Consolas", 11))
    boot_pct.pack()

    boot_detail = ctk.CTkLabel(card, text="", text_color=C["dim"],
                                font=("Segoe UI", 9))
    boot_detail.pack(pady=(8, 0))

    root.update()

    _boot_cur = [0.0]  # current animated progress

    def _boot_animate_to(target_pct, duration=0.25):
        """Smoothly animate progress bar from current to target over duration seconds."""
        start = _boot_cur[0]; steps = max(8, int(duration * 40))
        for i in range(1, steps + 1):
            t = i / steps
            ease = t * t * (3 - 2 * t)  # smoothstep
            val = start + (target_pct - start) * ease
            _boot_cur[0] = val
            boot_bar.set(val / 100.0)
            boot_pct.configure(text=f"{int(val)}%")
            root.update()
            import time; time.sleep(duration / steps)

    def _boot_set(pct, msg, detail=""):
        boot_status.configure(text=msg)
        if detail:
            boot_detail.configure(text=detail)
        _boot_animate_to(pct)

    import time as _t

    # Step 1: GPU Detection
    _boot_set(5, "Detecting GPU...", GPU.info_str())
    _boot_set(15, f"GPU: {GPU.info_str()}", f"Encoder: {GPU.hw_encoder}")

    # Step 2: Load or ask for API key
    _boot_set(20, "Loading API key...", "Checking voice_cache")
    api_key = voice_cache.load_api_key()
    if api_key:
        _boot_set(25, "API key loaded from cache", f"Key: ...{api_key[-6:]}")
    else:
        # Ask user for API key on boot screen
        _boot_set(22, "Enter your ElevenLabs API key", "Required for voice loading")
        _api_frame = ctk.CTkFrame(card, fg_color="transparent")
        _api_frame.pack(pady=(10, 0))
        ctk.CTkLabel(_api_frame, text="ElevenLabs API Key:",
                     text_color=C["text"], font=("Segoe UI", 11)).pack(pady=(0,4))
        _api_entry = ctk.CTkEntry(_api_frame, width=320, height=36,
                                   placeholder_text="Paste your xi-api-key here...",
                                   fg_color=C["bg"], border_color=C["border"],
                                   text_color=C["text"], font=("Consolas", 11),
                                   show="*")
        _api_entry.pack(pady=(0,4))
        _api_status = ctk.CTkLabel(_api_frame, text="", text_color=C["dim"],
                                    font=("Segoe UI", 10))
        _api_status.pack()
        _api_done = [False]

        def _submit_key(evt=None):
            k = _api_entry.get().strip()
            if not k:
                _api_status.configure(text="Please enter a key", text_color=C["orange"])
                return
            _api_status.configure(text="Validating...", text_color=C["orange"])
            root.update()
            ok = voice_cache.validate_key(k)
            if ok:
                voice_cache.save_api_key(k)
                _api_status.configure(text="✓ Key valid!", text_color=C["green"])
                _api_done[0] = True
                root.update()
            else:
                _api_status.configure(text="✗ Invalid key — try again", text_color=C["red"])

        _api_entry.bind("<Return>", _submit_key)
        ctk.CTkButton(_api_frame, text="Validate & Continue",
                       height=32, width=200, corner_radius=8,
                       fg_color=C["accent"], hover_color="#7c3aed",
                       text_color="#ffffff", font=("Segoe UI", 11, "bold"),
                       command=_submit_key).pack(pady=(4,0))
        ctk.CTkButton(_api_frame, text="Skip (enter later)",
                       height=26, width=150, corner_radius=6,
                       fg_color="transparent", hover_color=C["card"],
                       text_color=C["dim"], border_width=1,
                       border_color=C["border"], font=("Segoe UI", 10),
                       command=lambda: _api_done.__setitem__(0, True)).pack(pady=(6,0))

        root.update()
        while not _api_done[0]:
            root.update()
            _t.sleep(0.05)

        api_key = voice_cache.load_api_key()
        _api_frame.destroy()
        if api_key:
            _boot_set(25, f"API key saved ✓", f"Key: ...{api_key[-6:]}")
        else:
            _boot_set(25, "No API key — voices will load manually", "")

    # Step 3: Fetch ElevenLabs models
    _boot_models = []
    if api_key:
        _boot_set(30, "Fetching ElevenLabs models...", "api.elevenlabs.io/v1/models")
        try:
            r = requests.get("https://api.elevenlabs.io/v1/models",
                             headers={"xi-api-key": api_key}, timeout=10)
            if r.status_code == 200:
                _boot_models = r.json()
                _boot_set(45, f"✓ {len(_boot_models)} models loaded",
                          ", ".join(m["name"][:20] for m in _boot_models[:3]))
            else:
                _boot_set(45, "Models: API error", f"Status {r.status_code}")
        except Exception as e:
            _boot_set(45, "Models: network error", str(e)[:50])
    else:
        _boot_set(45, "Models: skipped (no API key)")

    # Step 4: Fetch ALL voices via voice_cache
    _boot_voices = []
    if api_key:
        _boot_set(48, "Fetching AI33 Voices...", "voice_cache")
        try:
            voices = voice_cache.load_voices_cached(api_key=api_key)
            seen = set()
            for v in voices:
                vid = v.get("voice_id", "")
                nm = v.get("name", "?")
                gender = v.get("gender", "")
                provider = v.get("provider", "")
                if not gender:
                    nl = nm.lower()
                    if any(w in nl for w in ["female","girl","woman","lady"]): gender = "female"
                    elif any(w in nl for w in ["male","boy","man","guy"]): gender = "male"
                if vid and vid not in seen:
                    seen.add(vid)
                    _boot_voices.append((nm, vid, gender, provider))
            _boot_set(60, f"[OK] {len(_boot_voices)} voices loaded",
                      ", ".join(v[0] for v in _boot_voices[:5]))
        except Exception as e:
            _boot_set(60, "Voices error", str(e)[:50])
    else:
        _boot_set(60, "Voices: skipped (no API key)", "")

    # Step 5: Captions via ElevenLabs Scribe (cloud). No local Whisper.
    _boot_set(75, "Captions: ElevenLabs Scribe", "cloud — API key needed")

    # Step 6: Check ffmpeg
    _boot_set(80, "Checking ffmpeg...", "")
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True,
                           timeout=5, **_NO_WINDOW)
        ver_line = r.stdout.split("\n")[0] if r.stdout else "unknown"
        _boot_set(85, "✓ ffmpeg ready", ver_line[:60])
    except Exception:
        _boot_set(85, "ffmpeg not found!", "Video rendering may fail")

    # Step 7: Building UI
    _boot_set(100, "Launching...", "Almost there")

    # Smooth fade-out boot screen
    for alpha_step in range(10, 0, -1):
        try:
            root.attributes("-alpha", alpha_step / 10.0)
            root.update()
            _t.sleep(0.025)
        except Exception:
            break

    # Destroy boot screen, mount main UI
    boot.destroy()

    frame = ctk.CTkFrame(root, fg_color=C["bg"])
    frame.pack(fill="both", expand=True)

    # Pass boot data to tabs via root
    root._boot_data = {
        "api_key": api_key,
        "models": _boot_models,
        "voices": _boot_voices,
        "captions_engine": "elevenlabs_scribe",
    }

    create(frame)

    # Smooth fade-in to main UI
    for alpha_step in range(1, 11):
        try:
            root.attributes("-alpha", alpha_step / 10.0)
            root.update()
            _t.sleep(0.025)
        except Exception:
            break
    try: root.attributes("-alpha", 1.0)
    except: pass

    root.mainloop()


if __name__ == "__main__":
    launch_app()
