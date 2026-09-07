import os
import re
import sys
import math
import json
import time
import shutil
import threading
import subprocess
import traceback
import urllib.request
import urllib.parse
import ssl
import cv2
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Tuple, Union
from concurrent.futures import ThreadPoolExecutor, as_completed

LogFn = Optional[Callable[[str], None]]

# ── Silent subprocess flags for Windows (no flashing console windows) ──
# ── Silent subprocess flags for Windows (no flashing console windows) ──
if os.name == "nt":
    _si = subprocess.STARTUPINFO()
    _si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _si.wShowWindow = 0  # SW_HIDE
    _NO_WINDOW = {"creationflags": 0x08000000, "startupinfo": _si}
else:
    _NO_WINDOW = {}


def find_binary(name: str) -> str:
    """Find binary path checking bundled paths first."""
    candidates = [
        getattr(sys, "_MEIPASS", ""),
        os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else "",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin"),
        os.path.dirname(os.path.abspath(__file__)),
        os.getcwd()
    ]
    for c in candidates:
        if c:
            p = os.path.join(c, f"{name}.exe" if os.name == 'nt' and not name.endswith('.exe') else name)
            if os.path.isfile(p):
                return p
    return shutil.which(name) or name


def check_ffmpeg() -> Dict[str, bool]:
    """Check availability of ffmpeg and ffprobe."""
    ff = find_binary("ffmpeg")
    fp = find_binary("ffprobe")
    return {
        "ffmpeg": bool(ff and (os.path.isfile(ff) or shutil.which(ff))),
        "ffprobe": bool(fp and (os.path.isfile(fp) or shutil.which(fp))),
    }


def run(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run shell command using subprocess without popping CMD windows."""
    cmd = [str(x) for x in cmd if x is not None]
    if cmd and cmd[0] in ("ffmpeg", "ffprobe"):
        cmd[0] = find_binary(cmd[0])
    kw = {"capture_output": True, "text": True}
    if _NO_WINDOW:
        kw.update(_NO_WINDOW)
    res = subprocess.run(cmd, **kw)
    if check and res.returncode != 0:
        cmd_str = " ".join(str(x) for x in cmd)
        raise RuntimeError(f"Command failed (code {res.returncode}):\n{cmd_str}\n\nSTDERR:\n{res.stderr}")
    return res


def check_free_disk_gb(path: str = ".") -> float:
    """Return available disk space in Gigabytes for the given filesystem path."""
    try:
        total, used, free = shutil.disk_usage(path)
        return free / (1024 ** 3)
    except Exception:
        return 999.0


def cleanup_stale_temp_work(safe_data_root: str, max_age_hours: float = 6.0, log_callback: LogFn = None):
    """
    Scans safe_data_root/temp_work and automatically removes temporary directories & files older than max_age_hours.
    Preserves persistent items like whisper_models, tts_cache, logos, and fonts.
    """
    temp_work_dir = os.path.join(safe_data_root, "temp_work")
    if not os.path.exists(temp_work_dir):
        return
    now = time.time()
    cutoff_sec = max_age_hours * 3600
    cleaned_count = 0

    try:
        for entry in os.scandir(temp_work_dir):
            try:
                # Do not delete active models or persistent cache directories
                if entry.name in ("whisper_models", "tts_cache", "logos", "presets", "story_fonts", "session.dat"):
                    continue
                mtime = entry.stat().st_mtime
                if (now - mtime) > cutoff_sec:
                    if entry.is_dir():
                        shutil.rmtree(entry.path, ignore_errors=True)
                        cleaned_count += 1
                    else:
                        os.remove(entry.path)
                        cleaned_count += 1
            except Exception:
                pass
        if cleaned_count > 0 and log_callback:
            log_callback(f"[Disk Auto-Clean] 🧹 Purged {cleaned_count} stale temporary file(s)/folder(s) from cache.")
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════
# GPU AUTO-DETECT & HYBRID PARALLEL ENCODER ENGINE
# ════════════════════════════════════════════════════════════════

class GPUConfig:
    """
    Singleton GPU detection & hybrid hardware acceleration manager.
    Detects NVIDIA NVENC / AMD AMF / Intel QSV / Apple VideoToolbox.
    Manages concurrent GPU encode slots with seamless parallel CPU fallback.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._detected = False
        return cls._instance

    def __init__(self):
        if not self._detected:
            self._detected = True
            self.gpu_name = "None"
            self.gpu_vendor = "none"          # nvidia / amd / intel / apple / none
            self.hw_encoder = "libx264"       # fallback
            self.hw_decoder_args = []         # e.g. ["-hwaccel", "cuda"]
            self.is_gpu = False
            self.max_gpu_sessions = 3
            self._gpu_slots = threading.Semaphore(self.max_gpu_sessions)
            self._stats_lock = threading.Lock()
            self.active_gpu_workers = 0
            self.active_cpu_workers = 0
            self.total_frames_rendered = 0
            self.total_clips_gpu = 0
            self.total_clips_cpu = 0
            self.last_speed_str = "0.0x"
            self.last_fps_val = 0.0
            self._detect()

    def _detect(self):
        """Use instant cached hardware info."""
        import hardware_accel
        hw = hardware_accel.get_hardware_info()
        self.gpu_name = hw.get("gpu_name", "Unknown GPU")
        self.gpu_vendor = hw.get("gpu_vendor", "none")
        self.hw_encoder = hw.get("hw_encoder", "libx264")
        self.hw_decoder_args = list(hw.get("hw_decoder_args", []))
        self.is_gpu = bool(hw.get("is_gpu", False))
        self.max_gpu_sessions = 3 if self.gpu_vendor == "nvidia" else 2
        self._gpu_slots = threading.Semaphore(self.max_gpu_sessions)

    def _get_available_encoders(self) -> set:
        """Query FFmpeg for available H.264 video encoders."""
        try:
            ff = find_binary("ffmpeg")
            r = subprocess.run([ff, "-hide_banner", "-encoders"],
                               capture_output=True, text=True, timeout=8, **_NO_WINDOW)
            text = r.stdout + r.stderr
            encoders = set()
            for line in text.split("\n"):
                line = line.strip()
                if line.startswith("V") and "h264" in line.lower():
                    parts = line.split()
                    if len(parts) >= 2:
                        encoders.add(parts[1])
            return encoders
        except Exception:
            return set()

    def _test_encoder(self, encoder_name: str) -> bool:
        """Run a test encode to guarantee the encoder works reliably."""
        test_out = os.path.join(os.environ.get("TEMP", "."), f"_gpu_probe_{encoder_name}_{os.getpid()}.mp4")
        try:
            ff = find_binary("ffmpeg")
            cmd = [ff, "-y", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.1:r=30",
                   "-c:v", encoder_name, "-frames:v", "3"]
            if encoder_name in ("h264_nvenc", "h264_videotoolbox", "libx264"):
                cmd += ["-pix_fmt", "yuv420p"]
            elif encoder_name in ("h264_amf", "h264_qsv"):
                cmd += ["-pix_fmt", "nv12"]
            elif encoder_name == "h264_mf":
                cmd += ["-b:v", "6M", "-pix_fmt", "yuv420p"]
            cmd.append(test_out)
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=8, **_NO_WINDOW)
            ok = (res.returncode == 0) and os.path.exists(test_out) and os.path.getsize(test_out) > 0
            if os.path.exists(test_out):
                try: os.remove(test_out)
                except Exception: pass
            return ok
        except Exception:
            if os.path.exists(test_out):
                try: os.remove(test_out)
                except Exception: pass
            return False

    def _detect_gpu_name(self):
        """Detect GPU hardware name from OS."""
        # 1. nvidia-smi
        try:
            r = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
                               capture_output=True, text=True, timeout=3, **_NO_WINDOW)
            if r.returncode == 0 and r.stdout.strip():
                first = r.stdout.split("\n")[0].strip()
                self.gpu_name = first.split(",")[0].strip()
                self.gpu_vendor = "nvidia"
                return
        except Exception:
            pass

        # 2. Windows CIM / WMI
        if sys.platform == "win32":
            try:
                r = subprocess.run(["powershell", "-NoProfile", "-Command",
                                    "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
                                   capture_output=True, text=True, timeout=4, **_NO_WINDOW)
                lines = [l.strip() for l in r.stdout.split("\n") if l.strip() and "virtual" not in l.lower() and "rdp" not in l.lower()]
                if lines:
                    self.gpu_name = lines[0]
                    lo = self.gpu_name.lower()
                    if any(k in lo for k in ("nvidia", "geforce", "rtx", "gtx", "quadro")):
                        self.gpu_vendor = "nvidia"
                    elif any(k in lo for k in ("amd", "radeon")):
                        self.gpu_vendor = "amd"
                    elif any(k in lo for k in ("intel", "arc", "iris", "uhd")):
                        self.gpu_vendor = "intel"
                    return
            except Exception:
                pass
            try:
                r = subprocess.run(["wmic", "path", "win32_VideoController", "get", "name"],
                                   capture_output=True, text=True, timeout=4, **_NO_WINDOW)
                lines = [l.strip() for l in r.stdout.split("\n") if l.strip() and l.strip().lower() != "name" and "virtual" not in l.lower()]
                if lines:
                    self.gpu_name = lines[0]
                    return
            except Exception:
                pass
        elif sys.platform == "darwin":
            try:
                r = subprocess.run(["system_profiler", "SPDisplaysDataType"],
                                   capture_output=True, text=True, timeout=4, **_NO_WINDOW)
                for line in r.stdout.split("\n"):
                    if "Chipset Model" in line or "Chip" in line:
                        self.gpu_name = line.split(":")[-1].strip()
                        self.gpu_vendor = "apple"
                        return
            except Exception:
                pass
        elif sys.platform == "linux":
            try:
                r = subprocess.run(["lspci"], capture_output=True, text=True, timeout=4, **_NO_WINDOW)
                for line in r.stdout.split("\n"):
                    if "VGA" in line or "3D" in line or "Display" in line:
                        self.gpu_name = line.split(":")[-1].strip()
                        return
            except Exception:
                pass
        self.gpu_name = "Integrated / Standard Display"

    def acquire_encoder(self, preset: str = "fast") -> Tuple[List[str], bool, Callable[[], None]]:
        """
        Thread-safe Hybrid slot acquisition:
        - If GPU slot available: returns (GPU_args, True, release_slot_fn)
        - If all GPU slots busy: returns (CPU_libx264_args, False, noop_fn)
        """
        got_gpu = False
        if self.is_gpu:
            try:
                got_gpu = self._gpu_slots.acquire(blocking=False)
            except Exception:
                got_gpu = False

        if got_gpu:
            with self._stats_lock:
                self.active_gpu_workers += 1
                self.total_clips_gpu += 1

            def _release_gpu():
                try:
                    self._gpu_slots.release()
                except Exception:
                    pass
                with self._stats_lock:
                    self.active_gpu_workers = max(0, self.active_gpu_workers - 1)

            if self.hw_encoder == "h264_nvenc" or (self.gpu_vendor == "nvidia" and self.hw_encoder != "h264_mf"):
                p_map = {"ultrafast": "p1", "veryfast": "p2", "fast": "p4", "medium": "p5", "slow": "p6"}
                p = p_map.get(preset, "p4")
                args = ["-c:v", "h264_nvenc", "-preset", p, "-rc", "vbr", "-cq", "22", "-b:v", "4M", "-maxrate", "8M", "-bufsize", "12M",
                        "-rc-lookahead", "8", "-pix_fmt", "yuv420p"]
            elif self.hw_encoder == "h264_mf":
                args = ["-c:v", "h264_mf", "-b:v", "5M", "-pix_fmt", "yuv420p"]
            elif self.gpu_vendor == "amd":
                p_map = {"ultrafast": "speed", "veryfast": "speed", "fast": "balanced", "medium": "quality"}
                p = p_map.get(preset, "balanced")
                args = ["-c:v", "h264_amf", "-preset", p, "-rc", "vbr_latency", "-qp_i", "22", "-qp_p", "24",
                        "-pix_fmt", "nv12"]
            elif self.gpu_vendor == "intel":
                args = ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "23", "-pix_fmt", "nv12"]
            elif self.gpu_vendor == "apple":
                args = ["-c:v", "h264_videotoolbox", "-q:v", "65", "-pix_fmt", "yuv420p"]
            else:
                args = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]

            return args, True, _release_gpu
        else:
            with self._stats_lock:
                self.active_cpu_workers += 1
                self.total_clips_cpu += 1

            def _release_cpu():
                with self._stats_lock:
                    self.active_cpu_workers = max(0, self.active_cpu_workers - 1)

            cpu_preset_map = {"ultrafast": "ultrafast", "veryfast": "veryfast", "fast": "faster", "medium": "medium"}
            cpu_p = cpu_preset_map.get(preset, "veryfast")
            cpu_threads = str(max(2, min(4, (os.cpu_count() or 4) // 2)))
            args = ["-c:v", "libx264", "-preset", cpu_p, "-crf", "20", "-threads", cpu_threads, "-pix_fmt", "yuv420p"]
            return args, False, _release_cpu

    def get_info(self) -> Dict[str, Any]:
        """Return structured GPU device info & acceleration status."""
        return {
            "gpu_name": self.gpu_name,
            "gpu_vendor": self.gpu_vendor,
            "hw_encoder": self.hw_encoder,
            "is_gpu": self.is_gpu,
            "max_gpu_sessions": self.max_gpu_sessions,
            "status": f"{self.gpu_vendor.upper()} ({self.hw_encoder})" if self.is_gpu else "CPU (libx264)",
            "speed_tier": "Ultra Fast (Hardware NVENC)" if self.gpu_vendor == "nvidia" else ("Hardware Accelerated" if self.is_gpu else "Standard CPU")
        }

    def get_analytics(self) -> Dict[str, Any]:
        """Return live rendering throughput, active sessions, and speed metrics."""
        with self._stats_lock:
            return {
                "active_gpu": self.active_gpu_workers,
                "active_cpu": self.active_cpu_workers,
                "gpu_clips": self.total_clips_gpu,
                "cpu_clips": self.total_clips_cpu,
                "last_speed": self.last_speed_str,
                "last_fps": self.last_fps_val,
                "total_frames": self.total_frames_rendered,
            }


# Singleton GPU instance
GPU = GPUConfig()

def get_gpu_info() -> Dict[str, Any]:
    """Public helper for UI tabs to query GPU name & acceleration status."""
    return GPU.get_info()

def get_gpu_analytics() -> Dict[str, Any]:
    """Public helper for UI tabs to query live render speed & analytics."""
    return GPU.get_analytics()
    kw = {"capture_output": True, "text": True}
    if _NO_WINDOW:
        kw.update(_NO_WINDOW)
    res = subprocess.run(cmd, **kw)
    if check and res.returncode != 0:
        cmd_str = " ".join(str(x) for x in cmd)
        raise RuntimeError(f"Command failed (code {res.returncode}):\n{cmd_str}\n\nSTDERR:\n{res.stderr}")
    return res

def run_with_progress(cmd: List[str], total_duration: float = 0.0, log_callback: Optional[LogFn] = None,
                      step_name: str = "FFmpeg", check: bool = True, is_gpu: bool = False) -> subprocess.CompletedProcess:
    """
    Run FFmpeg command with real-time progress updates, parsing time, frame, FPS, and processing speed metrics.
    Emits live GPU/CPU speed analytics to log_callback.
    """
    cmd = [str(x) for x in cmd if x is not None]
    if cmd and cmd[0] in ("ffmpeg", "ffprobe"):
        cmd[0] = find_binary(cmd[0])

    kw = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "bufsize": 1,
        "universal_newlines": True
    }
    if _NO_WINDOW:
        kw.update(_NO_WINDOW)

    proc = subprocess.Popen(cmd, **kw)

    last_pct = -1
    last_log_time = 0.0
    stderr_lines = []

    for line in iter(proc.stderr.readline, ''):
        stderr_lines.append(line)
        if "time=" in line or "frame=" in line or "fps=" in line:
            m_time = re.search(r"time=(\d+):(\d+):(\d+\.\d+|\d+)", line)
            m_frame = re.search(r"frame=\s*(\d+)", line)
            m_fps = re.search(r"fps=\s*([\d\.]+)", line)
            m_speed = re.search(r"speed=\s*([\d\.]+)x", line)

            curr_sec = 0.0
            if m_time:
                h, m_, s = int(m_time.group(1)), int(m_time.group(2)), float(m_time.group(3))
                curr_sec = h * 3600 + m_ * 60 + s

            frame_str = f"Frame {m_frame.group(1)}" if m_frame else ""
            fps_str = f"{m_fps.group(1)} FPS" if m_fps else ""
            speed_val = float(m_speed.group(1)) if m_speed else 0.0
            speed_str = f"{speed_val:.1f}x Speed" if speed_val > 0 else ""

            if m_fps:
                try: GPU.last_fps_val = float(m_fps.group(1))
                except Exception: pass
            if m_speed:
                GPU.last_speed_str = f"{speed_val:.1f}x"
            if m_frame:
                try: GPU.total_frames_rendered += 1
                except Exception: pass

            now = time.time()
            if total_duration > 0 and curr_sec > 0:
                pct = int(min(99.0, (curr_sec / total_duration) * 100))
                if (pct >= last_pct + 5 or now - last_log_time >= 2.5) and pct != last_pct:
                    last_pct = pct
                    last_log_time = now
                    eta_str = ""
                    if speed_val > 0.05 and total_duration > curr_sec:
                        rem_sec = max(0, int((total_duration - curr_sec) / speed_val))
                        eta_str = f"ETA: {rem_sec}s"

                    accel_tag = "GPU NVENC" if is_gpu else "CPU"
                    details = " | ".join(filter(None, [frame_str, fps_str, speed_str, eta_str, accel_tag]))
                    detail_text = f" ({details})" if details else ""
                    if log_callback:
                        try:
                            log_callback(f"   [{step_name}] Progress: {pct}%{detail_text}")
                        except Exception:
                            pass
            elif (m_frame or m_fps) and now - last_log_time >= 3.0:
                last_log_time = now
                accel_tag = "GPU" if is_gpu else "CPU"
                details = " | ".join(filter(None, [frame_str, fps_str, speed_str, accel_tag]))
                if log_callback:
                    try:
                        log_callback(f"   [{step_name}] {details}")
                    except Exception:
                        pass

    proc.wait()
    full_stderr = "".join(stderr_lines)
    if check and proc.returncode != 0:
        cmd_str = " ".join(str(x) for x in cmd)
        raise RuntimeError(f"Command failed (code {proc.returncode}):\n{cmd_str}\n\nSTDERR:\n{full_stderr}")

    if log_callback and last_pct >= 0:
        accel_tag = "GPU" if is_gpu else "CPU"
        try:
            log_callback(f"   [{step_name}] Progress: [OK] Complete ({accel_tag})")
        except Exception:
            pass

    return subprocess.CompletedProcess(cmd, proc.returncode, "", full_stderr)

def get_duration(media_path: str) -> float:
    """Get exact media duration in seconds using ffprobe."""
    if not os.path.exists(media_path):
        return 0.0
    ffprobe_bin = find_binary("ffprobe")
    cmd = [
        ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", media_path
    ]
    res = run(cmd, check=False)
    try:
        return float(res.stdout.strip())
    except ValueError:
        return 0.0

def get_video_profile(media_path: str) -> Dict[str, Any]:
    """Inspect video dimensions and frame rate."""
    if not media_path or not os.path.exists(media_path):
        return {"width": 1280, "height": 720, "fps": 30}
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate",
        "-of", "json", media_path
    ]
    res = run(cmd, check=False)
    try:
        data = json.loads(res.stdout)
        stream = data["streams"][0]
        w = int(stream["width"])
        h = int(stream["height"])
        fps_str = stream.get("r_frame_rate", "30/1")
        if "/" in fps_str:
            num, den = map(int, fps_str.split("/"))
            fps = float(num) / max(1, den)
        else:
            fps = float(fps_str)
        return {"width": w, "height": h, "fps": max(1, int(round(fps)))}
    except Exception:
        return {"width": 1280, "height": 720, "fps": 30}

def split_text_into_chunks(text: str, max_chars: int = 800) -> List[str]:
    """
    Split text into sentence-aware chunks of at most max_chars length.
    Prefers splitting on sentence endings (. ! ? \n), then clauses (, ; :), then spaces.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    sentence_pattern = re.compile(r'(?<=[.!?\n])\s+')
    sentences = [s.strip() for s in sentence_pattern.split(text) if s.strip()]
    if not sentences:
        sentences = [text]

    chunks = []
    current_chunk = ""

    for s in sentences:
        if len(s) > max_chars:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
            
            words = s.split(' ')
            sub_chunk = ""
            for w in words:
                if len(sub_chunk) + len(w) + 1 > max_chars:
                    if sub_chunk:
                        chunks.append(sub_chunk.strip())
                    sub_chunk = w
                else:
                    sub_chunk = (sub_chunk + " " + w).strip() if sub_chunk else w
            if sub_chunk:
                chunks.append(sub_chunk.strip())
        else:
            if len(current_chunk) + len(s) + 1 > max_chars:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = s
            else:
                current_chunk = (current_chunk + " " + s).strip() if current_chunk else s

    if current_chunk:
        chunks.append(current_chunk.strip())

    return [c for c in chunks if c]


def merge_audio_chunks(chunk_paths: List[str], out_path: str):
    """Concatenate audio chunk files into out_path using FFmpeg."""
    if not chunk_paths:
        return
    if len(chunk_paths) == 1:
        shutil.copy2(chunk_paths[0], out_path)
        return
    concat_list = os.path.join(os.path.dirname(out_path), f"concat_{int(time.time()*1000)}.txt")
    with open(concat_list, "w", encoding="utf-8") as f:
        for p in chunk_paths:
            safe_p = os.path.abspath(p).replace("\\", "/")
            f.write(f"file '{safe_p}'\n")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", out_path])
    try:
        os.remove(concat_list)
    except Exception:
        pass


def _generate_silent_audio(text: str, out_path: str, wpm: float = 150.0):
    """Generate silent MP3 placeholder based on word count to prevent script build crashes."""
    words = len(text.split()) if text else 1
    duration = max(2.0, (words / wpm) * 60.0)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
        "-t", f"{duration:.2f}",
        "-c:a", "libmp3lame", "-b:a", "128k", out_path
    ]
    run(cmd, check=False)


def parse_scene_script(script_text: str, max_scene_chars: Optional[int] = None, auto_chunk: bool = False) -> List[Dict[str, Any]]:
    """
    Parse a script string containing scene markers into structured scene blocks.
    Preserves exact explicit scene headers (e.g. Scene_1_, Scene_2_, ..., Scene_30_).
    Computes per-scene word count and character count.
    Only splits into sub-chunks if auto_chunk=True and max_scene_chars is set.
    """
    if not script_text or not script_text.strip():
        return []

    # Ensure scene markers that are not at the start of a line get proper double line breaks
    prep_text = re.sub(
        r"(?<!^)(?<!\n)\s*(?=(?:scene[_\s]*\d+[_\s:]*|\[scene[_\s]*\d+\]))",
        "\n\n",
        script_text.strip(),
        flags=re.IGNORECASE
    )

    lines = prep_text.splitlines()
    raw_scenes: List[Dict[str, Any]] = []
    
    current_scene_no = 0
    current_text_lines = []

    pattern = re.compile(r"^(?:scene[_\s]*(\d+)[_\s:]*|\[scene[_\s]*(\d+)\])(.*)", re.IGNORECASE)

    for line in lines:
        raw = line.strip()
        if not raw:
            continue

        match = pattern.match(raw)
        if match:
            if current_scene_no > 0 and current_text_lines:
                full_text = " ".join(current_text_lines).strip()
                if full_text:
                    raw_scenes.append({
                        "scene_no": current_scene_no,
                        "header": f"Scene_{current_scene_no}",
                        "text": full_text,
                        "word_count": len(full_text.split()),
                        "char_count": len(full_text)
                    })
                current_text_lines = []

            s_num = match.group(1) or match.group(2)
            current_scene_no = int(s_num) if s_num else (len(raw_scenes) + 1)
            rest = match.group(3).strip()
            rest = re.sub(r"^[_\s:]+", "", rest)
            if rest:
                current_text_lines.append(rest)
        else:
            if current_scene_no == 0:
                current_scene_no = 1
            current_text_lines.append(raw)

    if current_scene_no > 0 and current_text_lines:
        full_text = " ".join(current_text_lines).strip()
        if full_text:
            raw_scenes.append({
                "scene_no": current_scene_no,
                "header": f"Scene_{current_scene_no}",
                "text": full_text,
                "word_count": len(full_text.split()),
                "char_count": len(full_text)
            })

    if not raw_scenes and script_text.strip():
        paragraphs = [p.strip() for p in script_text.strip().split("\n\n") if p.strip()]
        for idx, p in enumerate(paragraphs, start=1):
            clean_p = " ".join(p.splitlines()).strip()
            if clean_p:
                raw_scenes.append({
                    "scene_no": idx,
                    "header": f"Scene_{idx}",
                    "text": clean_p,
                    "word_count": len(clean_p.split()),
                    "char_count": len(clean_p)
                })

    # Only chunk if auto_chunk is explicitly True and max_scene_chars is set
    if auto_chunk and max_scene_chars and max_scene_chars > 0:
        final_scenes: List[Dict[str, Any]] = []
        global_scene_counter = 1

        for sc in raw_scenes:
            stext = sc["text"]
            if len(stext) > max_scene_chars:
                sub_chunks = split_text_into_chunks(stext, max_chars=max_scene_chars)
                for chunk in sub_chunks:
                    clean_chunk = chunk.strip()
                    if clean_chunk:
                        final_scenes.append({
                            "scene_no": global_scene_counter,
                            "header": f"Scene_{global_scene_counter}",
                            "text": clean_chunk,
                            "word_count": len(clean_chunk.split()),
                            "char_count": len(clean_chunk)
                        })
                        global_scene_counter += 1
            else:
                final_scenes.append({
                    "scene_no": global_scene_counter,
                    "header": f"Scene_{global_scene_counter}",
                    "text": stext,
                    "word_count": sc.get("word_count", len(stext.split())),
                    "char_count": sc.get("char_count", len(stext))
                })
                global_scene_counter += 1
        return final_scenes

    return raw_scenes

def auto_match_images(image_paths: List[str], scene_count: int) -> Dict[int, str]:
    """
    Automatically match a list of image paths to scene numbers (1 to scene_count).
    Looks for Scene_1, Scene1, scene_01, or number indices in filenames.
    """
    matched: Dict[int, str] = {}
    remaining_images = list(image_paths)

    for s_no in range(1, scene_count + 1):
        target_patterns = [
            f"scene_{s_no}_", f"scene_{s_no}.", f"scene_{s_no:02d}_", f"scene_{s_no:02d}.",
            f"scene{s_no}_", f"scene{s_no}.", f"scene{s_no:02d}_", f"scene{s_no:02d}.",
            f"shot_{s_no}_", f"shot_{s_no:02d}_", f"img_{s_no}_", f"img_{s_no:02d}_"
        ]
        found_path = None
        for img_p in remaining_images:
            basename = os.path.basename(img_p).lower()
            if any(pat in basename for pat in target_patterns):
                found_path = img_p
                break
        if found_path:
            matched[s_no] = found_path
            remaining_images.remove(found_path)

    for s_no in range(1, scene_count + 1):
        if s_no not in matched and remaining_images:
            matched[s_no] = remaining_images.pop(0)

    return matched

def clean_voice_id(vid: Any) -> str:
    if not vid:
        return "elevenlabs_21m00Tcm4TlvDq8ikWAM"
    vid = str(vid).strip()
    if "(" in vid and vid.endswith(")"):
        vid = vid[vid.rfind("(")+1 : -1].strip()
    elif "•" in vid:
        vid = vid.split("•")[-1].strip()

    valid_prefixes = ["elevenlabs_", "minimax_", "clone_", "edge_", "kokoro_", "vbee_", "fishaudio_", "fish_"]
    if any(vid.startswith(p) for p in valid_prefixes):
        if vid.startswith("fish_"):
            return "fishaudio_" + vid[5:]
        return vid

    return f"elevenlabs_{vid}"

def _try_spoken_fallback_tts(text: str, voice_id: str, out_path: str, log_callback: LogFn = None) -> bool:
    """Fallback TTS is disabled."""
    if log_callback:
        log_callback("[spoken-fallback] Fallback TTS is disabled.")
    return False


def _get_persistent_tts_cache_dir() -> str:
    appdata = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or os.path.expanduser("~")
    d = os.path.join(appdata, "StoriesStudio", "tts_cache")
    os.makedirs(d, exist_ok=True)
    return d

def _get_persistent_tts_cache_key(text: str, voice_id: str, model_id: str = "", speed: float = 1.0) -> str:
    import hashlib
    c_vid = clean_voice_id(voice_id)
    raw = f"{text.strip()}|{c_vid.strip()}|{str(model_id).strip()}|{float(speed):.2f}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()

def _generate_single_chunk_tts(text: str, voice_id: str, tts_model_id: str, elevenlabs_key: str, out_path: str,
                               stability: float = 0.5, similarity_boost: float = 0.75,
                               speed: float = 1.0, log_callback: LogFn = None):
    """
    Generate TTS audio via AI33 API or direct ElevenLabs API with persistent disk cache.
    Fallback to Edge-TTS/gTTS is disabled.
    """
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    clean_vid = clean_voice_id(voice_id)

    # 0. Check Persistent Global Audio Cache (Credit Saving!)
    try:
        cache_key = _get_persistent_tts_cache_key(text, voice_id, tts_model_id, speed)
        cache_file = os.path.join(_get_persistent_tts_cache_dir(), f"{cache_key}.mp3")
        if os.path.exists(cache_file) and os.path.getsize(cache_file) > 500:
            shutil.copy2(cache_file, out_path)
            if log_callback:
                log_callback(f"   [CACHE] ⚡ Reused cached audio from disk ({os.path.getsize(out_path)} bytes) — 0 credits used")
            return
    except Exception:
        pass

    prefixed_vid = clean_vid
    if not any(prefixed_vid.startswith(p) for p in ["elevenlabs_", "minimax_", "clone_", "vbee_", "fishaudio_", "edge_", "kokoro_"]):
        prefixed_vid = f"elevenlabs_{prefixed_vid}"

    last_error = ""
    api_key_to_use = elevenlabs_key or os.getenv("AI33_API_KEY") or "sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt"

    # Tier 1: AI33 Client v3 Endpoint
    try:
        from ai33_api import AI33Client, AI33APIError
        client = AI33Client(api_key=api_key_to_use)
        for attempt in range(1, 4):
            try:
                if log_callback:
                    if attempt > 1:
                        log_callback(f"[ai33-v3] (Retry {attempt}/3) Requesting TTS for '{prefixed_vid}'...")
                    else:
                        log_callback(f"[ai33-v3] Requesting TTS for '{prefixed_vid}'...")

                res = client.text_to_speech_v3(
                    text=text,
                    voice_id=prefixed_vid,
                    speed=speed,
                    model_id=tts_model_id or "eleven_multilingual_v2",
                )
                if isinstance(res, (bytes, bytearray)) and len(res) > 100:
                    with open(out_path, "wb") as f:
                        f.write(res)
                    if log_callback:
                        log_callback(f"[ai33-v3] [OK] Audio received from AI33Pro v3 ({len(res)} bytes)")
                    try:
                        shutil.copy2(out_path, os.path.join(_get_persistent_tts_cache_dir(), f"{_get_persistent_tts_cache_key(text, voice_id, tts_model_id, speed)}.mp3"))
                    except Exception:
                        pass
                    return
                elif isinstance(res, dict):
                    task_id = res.get("task_id")
                    if task_id:
                        if log_callback:
                            log_callback(f"[ai33-v3] Task created: {task_id}. Polling (up to 90s)...")
                        task_res = client.poll_task(task_id, timeout=90)
                        meta = task_res.get("metadata", {}) if isinstance(task_res.get("metadata"), dict) else {}
                        audio_url = meta.get("audio_url") or task_res.get("audio_url") or task_res.get("output_url") or task_res.get("url")
                        if audio_url:
                            client.download_file(audio_url, out_path)
                            if log_callback:
                                log_callback(f"[ai33-v3] [OK] Downloaded audio task output from AI33Pro")
                            try:
                                shutil.copy2(out_path, os.path.join(_get_persistent_tts_cache_dir(), f"{_get_persistent_tts_cache_key(text, voice_id, tts_model_id, speed)}.mp3"))
                            except Exception:
                                pass
                            return
                        else:
                            raise RuntimeError(f"No audio URL returned in task {task_id}")
                    elif res.get("audio_url") or res.get("url"):
                        audio_url = res.get("audio_url") or res.get("url")
                        client.download_file(audio_url, out_path)
                        if log_callback:
                            log_callback(f"[ai33-v3] [OK] Downloaded audio from AI33Pro")
                        try:
                            shutil.copy2(out_path, os.path.join(_get_persistent_tts_cache_dir(), f"{_get_persistent_tts_cache_key(text, voice_id, tts_model_id, speed)}.mp3"))
                        except Exception:
                            pass
                        return
            except AI33APIError as exc:
                last_error = str(exc)
                if (exc.status_code in (429, 503) or "queue" in str(exc).lower()) and attempt < 3:
                    if log_callback:
                        log_callback(f"[ai33-v3] ⚠️ API busy / queued ({last_error[:60]}). Retrying ({attempt}/3) in {attempt * 2}s...")
                    time.sleep(2.0 * attempt)
                    continue
                if attempt >= 3:
                    break
            except Exception as exc:
                last_error = str(exc)
                err_text = last_error.lower()
                is_retryable = any(kw in err_text for kw in ("timeout", "timed out", "queue", "rate", "429", "500", "502", "503", "504", "processing", "connection"))
                if is_retryable and attempt < 3:
                    if log_callback:
                        log_callback(f"[ai33-v3] ⚠️ Attempt {attempt} failed ({last_error[:60]}). Retrying ({attempt}/3) in {attempt * 2}s...")
                    time.sleep(2.0 * attempt)
                    continue
                break
    except Exception as exc:
        last_error = str(exc)

    # Tier 2: Direct ElevenLabs API (if custom user API key is provided)
    if api_key_to_use and api_key_to_use != "sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt":
        try:
            bare_vid = clean_vid
            for p in ["elevenlabs_", "minimax_", "clone_", "vbee_", "fishaudio_", "edge_", "kokoro_"]:
                if bare_vid.startswith(p):
                    bare_vid = bare_vid[len(p):]
                    break
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{urllib.parse.quote(bare_vid)}?output_format=mp3_44100_128"
            req_headers = {
                "Content-Type": "application/json",
                "xi-api-key": api_key_to_use,
                "User-Agent": "StoriesStudio/2.8"
            }
            payload = json.dumps({
                "text": text,
                "model_id": tts_model_id or "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": max(0.0, min(1.0, float(stability))),
                    "similarity_boost": max(0.0, min(1.0, float(similarity_boost)))
                }
            }).encode("utf-8")
            ctx = ssl._create_unverified_context() if hasattr(ssl, "_create_unverified_context") else None
            req = urllib.request.Request(url, data=payload, headers=req_headers, method="POST")
            with urllib.request.urlopen(req, timeout=45, context=ctx) as resp:
                audio_bytes = resp.read()
                if len(audio_bytes) > 500:
                    with open(out_path, "wb") as f:
                        f.write(audio_bytes)
                    if log_callback:
                        log_callback(f"[elevenlabs-direct] [OK] Audio received from ElevenLabs Direct ({len(audio_bytes)} bytes)")
                    try:
                        shutil.copy2(out_path, os.path.join(_get_persistent_tts_cache_dir(), f"{_get_persistent_tts_cache_key(text, voice_id, tts_model_id, speed)}.mp3"))
                    except Exception:
                        pass
                    return
        except Exception as exc:
            last_error = f"{last_error} | direct elevenlabs error: {exc}"

    if not (os.path.exists(out_path) and os.path.getsize(out_path) > 100):
        # Tier 3 & 4: Seamless Free Fallback (Edge-TTS Neural & Google gTTS)
        if log_callback:
            log_callback(f"[story-image-tts] Primary TTS unavailable, activating free neural fallback TTS (Edge-TTS / gTTS)...")
        try:
            from ai33_api import generate_spoken_fallback_tts
            ok = generate_spoken_fallback_tts(text=text, voice_id=prefixed_vid or clean_vid, out_path=out_path, speed=speed, log_fn=log_callback)
            if ok and os.path.exists(out_path) and os.path.getsize(out_path) > 100:
                try:
                    shutil.copy2(out_path, os.path.join(_get_persistent_tts_cache_dir(), f"{_get_persistent_tts_cache_key(text, voice_id, tts_model_id, speed)}.mp3"))
                except Exception:
                    pass
                return
        except Exception as fb_exc:
            last_error = f"{last_error} | fallback error: {fb_exc}"

    if not (os.path.exists(out_path) and os.path.getsize(out_path) > 100):
        if log_callback:
            log_callback(f"[tts-error] TTS generation failed for '{text[:25]}...': {last_error}")
        raise RuntimeError(f"TTS generation failed for voice '{prefixed_vid}': {last_error}")

def generate_scene_tts(text: str, voice_id: str, tts_model_id: str, elevenlabs_key: str, out_path: str,
                       stability: float = 0.5, similarity_boost: float = 0.75,
                       speed: float = 1.0, log_callback: LogFn = None):
    """Generate TTS audio with automatic sentence sub-chunking for long text blocks."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    if len(text) > 800:
        chunks = split_text_into_chunks(text, max_chars=800)
        chunk_paths = []
        temp_dir = os.path.dirname(os.path.abspath(out_path))
        base_name = os.path.splitext(os.path.basename(out_path))[0]
        
        for idx, chunk_text in enumerate(chunks):
            c_path = os.path.join(temp_dir, f"{base_name}_sub_{idx:02d}.mp3")
            _generate_single_chunk_tts(chunk_text, voice_id, tts_model_id, elevenlabs_key, c_path,
                                       stability=stability, similarity_boost=similarity_boost,
                                       speed=speed, log_callback=log_callback)
            if os.path.exists(c_path) and os.path.getsize(c_path) > 100:
                chunk_paths.append(c_path)

        if chunk_paths:
            merge_audio_chunks(chunk_paths, out_path)
            for cp in chunk_paths:
                try: os.remove(cp)
                except Exception: pass
            return
        else:
            _generate_silent_audio(text, out_path)
            return

    _generate_single_chunk_tts(text, voice_id, tts_model_id, elevenlabs_key, out_path,
                               stability=stability, similarity_boost=similarity_boost,
                               speed=speed, log_callback=log_callback)

def generate_cinematic_organic_mask(width: int = 1280, height: int = 720, cache_dir: Optional[str] = None) -> str:
    """
    Generate an organic feathered/spiky-brush alpha matte mask.
    Center is fully opaque (subject illustration), borders organically dissolve into transparency.
    """
    mask_dir = cache_dir or os.path.join(os.path.expanduser("~"), ".story_cache", "masks")
    os.makedirs(mask_dir, exist_ok=True)
    mask_file = os.path.join(mask_dir, f"organic_mask_{width}x{height}_v3.png")
    if os.path.exists(mask_file) and os.path.getsize(mask_file) > 1000:
        return mask_file

    try:
        import cv2
        import numpy as np

        y, x = np.ogrid[:height, :width]
        cx, cy = width / 2.0, height / 2.0
        rx = width * 0.44
        ry = height * 0.44

        dist = np.sqrt(((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2)

        rng = np.random.RandomState(42)
        noise1 = rng.normal(0, 1, (max(8, height // 32), max(8, width // 32))).astype(np.float32)
        noise1 = cv2.resize(noise1, (width, height), interpolation=cv2.INTER_CUBIC)
        noise1 = (noise1 - noise1.min()) / (noise1.max() - noise1.min()) - 0.5

        noise2 = rng.normal(0, 1, (max(8, height // 16), max(8, width // 16))).astype(np.float32)
        noise2 = cv2.resize(noise2, (width, height), interpolation=cv2.INTER_CUBIC)
        noise2 = (noise2 - noise2.min()) / (noise2.max() - noise2.min()) - 0.5

        dist_distorted = dist + noise1 * 0.08 + noise2 * 0.04

        inner = 0.60
        outer = 1.02
        alpha = np.clip((outer - dist_distorted) / (outer - inner), 0.0, 1.0)
        alpha = alpha * alpha * (3.0 - 2.0 * alpha)

        alpha_u8 = (alpha * 255).astype(np.uint8)
        blur_k = int(min(width, height) * 0.07)
        if blur_k % 2 == 0:
            blur_k += 1
        alpha_blurred = cv2.GaussianBlur(alpha_u8, (blur_k, blur_k), blur_k / 2.5)

        cv2.imwrite(mask_file, alpha_blurred)
        return mask_file
    except Exception:
        # Fallback using PIL
        from PIL import Image, ImageDraw, ImageFilter
        im = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(im)
        draw.ellipse([int(width * 0.06), int(height * 0.06), int(width * 0.94), int(height * 0.94)], fill=255)
        im = im.filter(ImageFilter.GaussianBlur(radius=min(width, height) // 8))
        im.save(mask_file)
        return mask_file


def _build_zoompan_motion_expr(motion_lower: str, w: int, h: int, tf: int, fps: int, is_rgba: bool = False, scene_no: int = 1) -> str:
    """
    Build high-grade organic cinematic camera motion expressions with smooth cosine S-curve easing.
    Feels like genuine high-budget filmed video rather than static or linear digital zoom.
    Supports Auto-Director Flow which varies motion style dynamically across story scenes.
    """
    fmt = "rgba" if is_rgba else "yuv420p"
    scale_w = int(w * 1.20)
    scale_h = int(h * 1.20)
    scale_prefix = f"scale={scale_w}:{scale_h}:force_original_aspect_ratio=increase,crop={scale_w}:{scale_h}"

    m = motion_lower.lower().strip()

    # 1. Static / None
    if any(k in m for k in ("none", "static", "off", "raw", "clean")):
        return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},format={fmt}"

    # 2. Auto-Director Flow: Automatically cycle cinematic styles per scene
    if "auto" in m or "director" in m or "flow" in m or "dynamic" in m:
        slot = (max(1, int(scene_no)) - 1) % 5
        if slot == 0:
            m = "push"
        elif slot == 1:
            m = "pan_lr"
        elif slot == 2:
            m = "parallax"
        elif slot == 3:
            m = "crane"
        else:
            m = "drift"

    # 3. Slow Push-In (Depth Focus) - Subtle zoom into upper-middle subject with smooth cosine easing
    if any(k in m for k in ("push", "slow zoom", "subtle zoom", "ken burns", "zoom in")):
        return (
            f"{scale_prefix},"
            f"zoompan=z='1.02+0.07*(0.5-0.5*cos(PI*on/{tf}))':"
            f"x='(iw-iw/zoom)/2':"
            f"y='(ih-ih/zoom)*0.38':"
            f"d={tf}:s={w}x{h}:fps={fps},format={fmt}"
        )

    # 4. 3D Parallax & Gentle Float - Multi-axis floating camera with gentle orbital sway
    elif any(k in m for k in ("parallax", "float", "sway", "3d", "living")):
        return (
            f"{scale_prefix},"
            f"zoompan=z='1.04+0.03*sin(PI*on/{tf})':"
            f"x='(iw-iw/zoom)/2+sin(2*PI*on/{tf})*((iw-iw/zoom)*0.24)':"
            f"y='(ih-ih/zoom)/2+cos(2*PI*on/{tf})*((ih-ih/zoom)*0.24)':"
            f"d={tf}:s={w}x{h}:fps={fps},format={fmt}"
        )

    # 5. Smooth Pan Left-to-Right
    elif "pan_lr" in m or ("pan" in m and "right" in m) or "pan" in m:
        return (
            f"{scale_prefix},"
            f"zoompan=z='1.05+0.02*(0.5-0.5*cos(PI*on/{tf}))':"
            f"x='(iw-iw/zoom)*(0.15+0.70*(0.5-0.5*cos(PI*on/{tf})))':"
            f"y='(ih-ih/zoom)/2':"
            f"d={tf}:s={w}x{h}:fps={fps},format={fmt}"
        )

    # 6. Gentle Crane & Tilt Up
    elif any(k in m for k in ("crane", "tilt up", "tilt")):
        return (
            f"{scale_prefix},"
            f"zoompan=z='1.03+0.04*(0.5-0.5*cos(PI*on/{tf}))':"
            f"x='(iw-iw/zoom)/2':"
            f"y='(ih-ih/zoom)*(0.80-0.60*(0.5-0.5*cos(PI*on/{tf})))':"
            f"d={tf}:s={w}x{h}:fps={fps},format={fmt}"
        )

    # 7. Subtle Diagonal Drift
    elif "drift" in m or "diagonal" in m:
        return (
            f"{scale_prefix},"
            f"zoompan=z='1.04+0.03*(0.5-0.5*cos(PI*on/{tf}))':"
            f"x='(iw-iw/zoom)*(0.20+0.60*(0.5-0.5*cos(PI*on/{tf})))':"
            f"y='(ih-ih/zoom)*(0.75-0.50*(0.5-0.5*cos(PI*on/{tf})))':"
            f"d={tf}:s={w}x{h}:fps={fps},format={fmt}"
        )

    # 8. Living Breathing Camera (Subtle hand-held micro-float)
    elif any(k in m for k in ("breath", "ambient")):
        return (
            f"{scale_prefix},"
            f"zoompan=z='1.03+0.025*sin(PI*on/{tf})':"
            f"x='(iw-iw/zoom)/2+sin(PI*on/{tf})*((iw-iw/zoom)*0.10)':"
            f"y='(ih-ih/zoom)/2+cos(PI*on/{tf})*((ih-ih/zoom)*0.10)':"
            f"d={tf}:s={w}x{h}:fps={fps},format={fmt}"
        )

    # Default fallback: Slow Push-In
    else:
        return (
            f"{scale_prefix},"
            f"zoompan=z='1.02+0.07*(0.5-0.5*cos(PI*on/{tf}))':"
            f"x='(iw-iw/zoom)/2':"
            f"y='(ih-ih/zoom)*0.38':"
            f"d={tf}:s={w}x{h}:fps={fps},format={fmt}"
        )


def build_scene_image_clip(image_path: str, duration: float, out_clip_path: str,
                            profile: Dict[str, Any], motion_effect: str = "Auto-Director Flow (Dynamic Scenes)",
                            bg_video_path: Optional[str] = None, bg_opacity: float = 0.6,
                            render_preset: str = "fast", audio_path: Optional[str] = None,
                            log_callback: LogFn = None, scene_no: int = 1):
    """
    Render an MP4 video clip from a static image with motion effect and real-time FFmpeg progress logging.
    If bg_video_path is provided, loops the background video behind an organically feathered/blended foreground illustration.
    If audio_path is provided, synchronizes and muxes audio in the same pass (saving 50% disk I/O and space).
    Utilizes GPU hardware acceleration (NVENC/AMF/QSV) with dynamic CPU fallback.
    """
    os.makedirs(os.path.dirname(os.path.abspath(out_clip_path)) or ".", exist_ok=True)
    w = profile.get("width", 1280)
    h = profile.get("height", 720)
    fps = int(profile.get("fps", 30))
    total_frames = max(30, int(duration * fps))
    tf = total_frames
    motion_lower = motion_effect.lower()
    step_label = f"Scene {scene_no}"
    has_audio = bool(audio_path and os.path.exists(audio_path))

    enc_args, is_gpu, release_slot = GPU.acquire_encoder(render_preset)
    try:
        if bg_video_path and os.path.exists(bg_video_path):
            fg_motion = _build_zoompan_motion_expr(motion_lower, w, h, tf, fps, is_rgba=False, scene_no=scene_no)
            eff_opacity = max(0.05, min(0.40, float(bg_opacity) if bg_opacity <= 1.0 else float(bg_opacity) / 100.0))

            # Blend background video softly on top of the full-canvas main story image as an atmospheric overlay
            fc = (
                f"[0:v]{fg_motion}[main_img];"
                f"[1:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},format=yuv420p,colorchannelmixer=aa={eff_opacity:.2f}[bg_fx];"
                f"[main_img][bg_fx]overlay=0:0:format=auto[v_out]"
            )

            cmd_base = [
                "ffmpeg", "-y",
                "-loop", "1", "-r", str(fps), "-i", image_path,
                "-stream_loop", "-1", "-i", bg_video_path,
            ]
            if has_audio:
                cmd_base += ["-i", audio_path]

            cmd_base += ["-filter_complex", fc, "-map", "[v_out]"]
            if has_audio:
                cmd_base += ["-map", "2:a:0"]

            cmd_base += ["-t", f"{duration:.3f}"]
            audio_args = ["-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2", "-shortest"] if has_audio else []

            cmd = cmd_base + enc_args + audio_args + ["-r", str(fps), out_clip_path]

            try:
                run_with_progress(cmd, total_duration=duration, log_callback=log_callback, step_name=step_label, is_gpu=is_gpu)
            except Exception as e:
                if is_gpu:
                    if log_callback:
                        log_callback(f"   [{step_label}] GPU encode fallback -> retrying on CPU libx264")
                    cpu_args = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
                    cmd_cpu = cmd_base + cpu_args + audio_args + ["-r", str(fps), out_clip_path]
                    run_with_progress(cmd_cpu, total_duration=duration, log_callback=log_callback, step_name=step_label, is_gpu=False)
                else:
                    raise e
        else:
            # Standard Full-Canvas Image Motion
            vf = _build_zoompan_motion_expr(motion_lower, w, h, tf, fps, is_rgba=False, scene_no=scene_no)

            cmd_base = ["ffmpeg", "-y", "-loop", "1", "-r", str(fps), "-i", image_path]
            if has_audio:
                cmd_base += ["-i", audio_path]

            cmd_base += ["-vf", vf, "-map", "0:v:0"]
            if has_audio:
                cmd_base += ["-map", "1:a:0"]

            cmd_base += ["-t", f"{duration:.3f}"]
            audio_args = ["-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2", "-shortest"] if has_audio else []

            cmd = cmd_base + enc_args + audio_args + ["-r", str(fps), out_clip_path]

            try:
                run_with_progress(cmd, total_duration=duration, log_callback=log_callback, step_name=step_label, is_gpu=is_gpu)
            except Exception as e:
                if is_gpu:
                    if log_callback:
                        log_callback(f"   [{step_label}] GPU encode fallback -> retrying on CPU libx264")
                    cpu_args = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
                    cmd_cpu = cmd_base + cpu_args + audio_args + ["-r", str(fps), out_clip_path]
                    run_with_progress(cmd_cpu, total_duration=duration, log_callback=log_callback, step_name=step_label, is_gpu=False)
                else:
                    raise e
    finally:
        release_slot()

def apply_particle_overlay(in_video_path: str, out_video_path: str,
                           overlay_type: str = "Off / None",
                           render_preset: str = "fast"):
    """
    Safely passthrough video without applying any chroma-distorting noise or blend filters.
    """
    os.makedirs(os.path.dirname(os.path.abspath(out_video_path)) or ".", exist_ok=True)
    shutil.copy2(in_video_path, out_video_path)

def apply_story_overlays_and_subtitles(
    video_path: str,
    out_path: str,
    visualizer_path: Optional[str] = None,
    visualizer_opacity: float = 0.85,
    visualizer_width: int = 520,
    subscribe_path: Optional[str] = None,
    subscribe_gap: int = 35,
    subscribe_width: int = 220,
    logo_path: Optional[str] = None,
    logo_position: str = "Top-Right",
    logo_width: int = 200,
    custom_logo_x: Optional[int] = None,
    custom_logo_y: Optional[int] = None,
    ass_path: Optional[str] = None,
    custom_font_path: Optional[str] = None,
    render_preset: str = "fast",
    log_callback: LogFn = None
):
    """
    Renders Visualizer (behind captions) + Subscribe Button (bottom-left periodic loop)
    + Logo Watermark + CapCut Subtitles simultaneously in a SINGLE FFmpeg pass with GPU acceleration.
    """
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    duration = get_duration(video_path)

    cmd_inputs = ["ffmpeg", "-y", "-i", video_path]
    filter_parts = []
    curr_v = "[0:v]"
    in_idx = 1

    # 1. Audio Visualizer Overlay (placed BEHIND subtitles)
    if visualizer_path and os.path.exists(visualizer_path):
        cmd_inputs.extend(["-stream_loop", "-1", "-i", visualizer_path])
        vis_tag = f"[vis_{in_idx}]"
        v_out_tag = f"[v_vis_{in_idx}]"
        eff_vis_op = max(0.05, min(1.0, float(visualizer_opacity)))
        eff_vis_w = max(100, min(1200, int(visualizer_width)))
        filter_parts.append(f"[{in_idx}:v]scale={eff_vis_w}:-1,format=rgba,colorchannelmixer=aa={eff_vis_op:.2f}{vis_tag}")
        # Place centered behind bottom-center captions
        filter_parts.append(f"{curr_v}{vis_tag}overlay=(main_w-overlay_w)/2:main_h*0.74-overlay_h/2:format=auto{v_out_tag}")
        curr_v = v_out_tag
        in_idx += 1

    # 2. Subscribe Button Overlay (Bottom-Left corner, wide periodic loop)
    if subscribe_path and os.path.exists(subscribe_path):
        cmd_inputs.extend(["-stream_loop", "-1", "-i", subscribe_path])
        sub_tag = f"[sub_{in_idx}]"
        v_out_tag = f"[v_sub_{in_idx}]"
        eff_sub_w = max(80, min(600, int(subscribe_width)))
        cycle = max(10, int(subscribe_gap))
        filter_parts.append(f"[{in_idx}:v]scale={eff_sub_w}:-1,format=rgba{sub_tag}")
        # Appear for 5 seconds starting at 2s, then wide gap of cycle seconds
        filter_parts.append(f"{curr_v}{sub_tag}overlay=32:main_h-overlay_h-32:enable='between(mod(t,{cycle}),2,7)':format=auto{v_out_tag}")
        curr_v = v_out_tag
        in_idx += 1

    # 3. Logo Watermark Overlay
    if logo_path and os.path.exists(logo_path):
        cmd_inputs.extend(["-i", logo_path])
        wm_tag = f"[wm_{in_idx}]"
        v_out_tag = f"[v_wm_{in_idx}]"
        eff_logo_w = max(40, min(800, int(logo_width)))
        pos = (logo_position or "Top-Right").strip()

        if custom_logo_x is not None and custom_logo_y is not None and ("custom" in pos.lower() or pos == "Custom"):
            ov_pos = f"{int(custom_logo_x)}:{int(custom_logo_y)}"
        elif pos == "Top-Left":
            ov_pos = "24:24"
        elif pos == "Bottom-Right":
            ov_pos = "main_w-overlay_w-24:main_h-overlay_h-24"
        elif pos == "Bottom-Left":
            ov_pos = "24:main_h-overlay_h-24"
        elif pos == "Center":
            ov_pos = "(main_w-overlay_w)/2:(main_h-overlay_h)/2"
        else:
            ov_pos = "main_w-overlay_w-24:24"

        filter_parts.append(f"[{in_idx}:v]scale={eff_logo_w}:-1,format=rgba{wm_tag}")
        filter_parts.append(f"{curr_v}{wm_tag}overlay={ov_pos}:format=auto{v_out_tag}")
        curr_v = v_out_tag
        in_idx += 1

    # 4. CapCut Subtitles (Burned on topmost layer so text is crisp over visualizer)
    if ass_path and os.path.exists(ass_path):
        norm_ass = os.path.abspath(ass_path).replace("\\", "/").replace(":", "\\:")
        if custom_font_path and os.path.exists(custom_font_path):
            font_dir = os.path.dirname(os.path.abspath(custom_font_path)).replace("\\", "/").replace(":", "\\:")
            vf_sub = f"subtitles=filename='{norm_ass}':fontsdir='{font_dir}'"
        else:
            vf_sub = f"subtitles=filename='{norm_ass}'"
        filter_parts.append(f"{curr_v}{vf_sub}[v_final]")
        curr_v = "[v_final]"

    # If no filters applied at all, just copy
    if not filter_parts:
        shutil.copy2(video_path, out_path)
        return

    filter_complex = ";".join(filter_parts)
    enc_args, is_gpu, release_slot = GPU.acquire_encoder(render_preset)
    t_args = ["-t", f"{duration:.3f}"] if duration > 0 else []
    try:
        cmd = cmd_inputs + [
            "-filter_complex", filter_complex,
            "-map", curr_v,
            "-map", "0:a:0?",
        ] + enc_args + ["-c:a", "copy"] + t_args + ["-shortest", out_path]

        try:
            run_with_progress(cmd, total_duration=duration, log_callback=log_callback, step_name="Single-Pass (Overlays + Subtitles)", is_gpu=is_gpu)
        except Exception as e:
            if log_callback:
                log_callback(f"   [Single-Pass] GPU encode fallback ({e}) -> retrying CPU libx264")
            cmd_cpu = cmd_inputs + [
                "-filter_complex", filter_complex,
                "-map", curr_v,
                "-map", "0:a:0?",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-c:a", "copy", "-pix_fmt", "yuv420p",
            ] + t_args + ["-shortest", out_path]
            run_with_progress(cmd_cpu, total_duration=duration, log_callback=log_callback, step_name="Single-Pass (Overlays + Subtitles)", is_gpu=False)
    finally:
        release_slot()


def apply_combined_logo_and_subtitles(video_path: str, logo_path: str, ass_path: str, out_path: str,
                                       render_preset: str = "fast", position: str = "Top-Right",
                                       logo_width: int = 200, custom_x: Optional[int] = None,
                                       custom_y: Optional[int] = None, custom_font_path: Optional[str] = None,
                                       log_callback: LogFn = None):
    """Backward compatibility wrapper delegating to apply_story_overlays_and_subtitles."""
    return apply_story_overlays_and_subtitles(
        video_path=video_path,
        out_path=out_path,
        logo_path=logo_path,
        logo_position=position,
        logo_width=logo_width,
        custom_logo_x=custom_x,
        custom_logo_y=custom_y,
        ass_path=ass_path,
        custom_font_path=custom_font_path,
        render_preset=render_preset,
        log_callback=log_callback
    )


def render_symmetrical_audiogram_video(
    audio_source: str,
    out_video_path: str,
    duration: float,
    width: int = 520,
    height: int = 90,
    bar_count: int = 52,
    color_hex: str = "#FFFFFF",
    fps: int = 30,
    cache_dir: Optional[str] = None,
    log_callback: LogFn = None
) -> str:
    """
    Render exact symmetrical vertical rounded soundwave bars video matching reference audiogram.
    """
    os.makedirs(os.path.dirname(os.path.abspath(out_video_path)) or ".", exist_ok=True)
    temp_d = cache_dir or os.path.dirname(os.path.abspath(out_video_path))
    raw_pcm = os.path.join(temp_d, "temp_eq_audio.raw")
    frames_dir = os.path.join(temp_d, "eq_frames")
    os.makedirs(frames_dir, exist_ok=True)

    # 1. Parse color hex to BGR
    c_hex = color_hex.strip().lstrip("#")
    if len(c_hex) >= 6:
        r, g, b = int(c_hex[0:2], 16), int(c_hex[2:4], 16), int(c_hex[4:6], 16)
        bgr_color = (b, g, r)
    elif "cyan" in color_hex.lower():
        bgr_color = (255, 255, 0)
    elif "green" in color_hex.lower():
        bgr_color = (102, 255, 0)
    elif "gold" in color_hex.lower() or "yellow" in color_hex.lower():
        bgr_color = (0, 215, 255)
    elif "purple" in color_hex.lower():
        bgr_color = (247, 85, 168)
    elif "red" in color_hex.lower():
        bgr_color = (51, 51, 255)
    elif "pink" in color_hex.lower():
        bgr_color = (127, 0, 255)
    else:
        bgr_color = (255, 255, 255)

    # 2. Extract PCM audio stream
    try:
        run([
            "ffmpeg", "-y", "-i", audio_source,
            "-vn", "-ac", "1", "-ar", "22050", "-f", "f32le", raw_pcm
        ])
        with open(raw_pcm, "rb") as f:
            samples = np.frombuffer(f.read(), dtype=np.float32)
    except Exception:
        samples = np.zeros(int(duration * 22050), dtype=np.float32)

    total_frames = max(10, int(duration * fps))
    samples_per_frame = len(samples) / max(1, total_frames) if len(samples) > 0 else 1.0

    frame_bars = []
    for f_idx in range(total_frames):
        start_samp = int(f_idx * samples_per_frame)
        end_samp = int(start_samp + samples_per_frame)
        frame_chunk = samples[start_samp:end_samp]

        if len(frame_chunk) == 0:
            bars = np.zeros(bar_count)
        else:
            sub_chunks = np.array_split(frame_chunk, bar_count)
            bars = np.array([np.sqrt(np.mean(c**2)) if len(c) > 0 else 0.0 for c in sub_chunks])
            bars = np.power(bars * 4.0, 0.75)
            bars = np.clip(bars, 0.04, 1.0)
            window = np.sin(np.linspace(0.2, np.pi - 0.2, bar_count)) ** 0.6
            bars = bars * window
        frame_bars.append(bars)

    # Temporal smoothing
    for f_idx in range(1, total_frames):
        frame_bars[f_idx] = frame_bars[f_idx - 1] * 0.35 + frame_bars[f_idx] * 0.65

    cy = height // 2
    bar_w = max(2, int((width - (bar_count - 1) * 3) / bar_count))
    gap = max(2, (width - (bar_count * bar_w)) // max(1, bar_count - 1))

    for f_idx, bars in enumerate(frame_bars):
        img = np.zeros((height, width, 3), dtype=np.uint8)
        for b_idx in range(bar_count):
            bx = b_idx * (bar_w + gap) + (bar_w // 2)
            b_height = max(4, int(bars[b_idx] * (height * 0.88)))
            y1 = cy - (b_height // 2)
            y2 = cy + (b_height // 2)
            cv2.line(img, (bx, y1), (bx, y2), bgr_color, bar_w, lineType=cv2.LINE_AA)
        cv2.imwrite(f"{frames_dir}/frame_{f_idx:04d}.png", img)

        if log_callback and (f_idx % max(1, total_frames // 10) == 0 or f_idx == total_frames - 1):
            pct = int(((f_idx + 1) / total_frames) * 100)
            log_callback(f"   [Equalizer-Frames] Rendering soundwave bars: frame {f_idx+1}/{total_frames} ({pct}%)...")

    run_with_progress([
        "ffmpeg", "-y", "-framerate", str(fps),
        "-i", f"{frames_dir}/frame_%04d.png",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", out_video_path
    ], total_duration=duration, log_callback=log_callback, step_name="Equalizer-Build")

    try:
        shutil.rmtree(frames_dir, ignore_errors=True)
        if os.path.exists(raw_pcm): os.remove(raw_pcm)
    except Exception:
        pass

    return out_video_path

def apply_audio_equalizer(
    in_video_path: str,
    out_video_path: str,
    style: str = "Symmetrical Soundwave Bars (Audiogram)",
    color: str = "#FFFFFF",
    position: str = "Bottom-Center",
    width: int = 520,
    height: int = 90,
    custom_x: Optional[int] = None,
    custom_y: Optional[int] = None,
    render_preset: str = "fast",
    log_callback: LogFn = None
):
    """
    Overlay an animated symmetrical soundwave audiogram visualizer on top of a video.
    """
    os.makedirs(os.path.dirname(os.path.abspath(out_video_path)) or ".", exist_ok=True)
    style_lower = style.lower()
    
    if "off" in style_lower or "none" in style_lower or "disable" in style_lower:
        shutil.copy2(in_video_path, out_video_path)
        return

    dur = max(1.0, get_duration(in_video_path))
    w = max(100, int(width))
    h = max(30, int(height))
    
    pos_lower = position.lower()
    if custom_x is not None and custom_y is not None:
        pos_expr = f"x={custom_x}:y={custom_y}"
    elif "top-left" in pos_lower:
        pos_expr = "x=40:y=40"
    elif "top-right" in pos_lower:
        pos_expr = "x=W-w-40:y=40"
    elif "top-center" in pos_lower:
        pos_expr = "x=(W-w)/2:y=40"
    elif "bottom-left" in pos_lower:
        pos_expr = "x=40:y=H-h-40"
    elif "bottom-right" in pos_lower:
        pos_expr = "x=W-w-40:y=H-h-40"
    elif "center" in pos_lower and "bottom" not in pos_lower and "top" not in pos_lower:
        pos_expr = "x=(W-w)/2:y=(H-h)/2"
    else:
        # Default: Bottom-Center (positioned right above subtitles)
        pos_expr = "x=(W-w)/2:y=H-h-70"

    eq_vid = os.path.join(os.path.dirname(out_video_path), "temp_audiogram_track.mp4")
    render_symmetrical_audiogram_video(
        audio_source=in_video_path,
        out_video_path=eq_vid,
        duration=dur,
        width=w,
        height=h,
        bar_count=52,
        color_hex=color,
        fps=30,
        log_callback=log_callback
    )

    filter_complex = f"[1:v]colorkey=0x000000:0.12:0.12[eq];[0:v][eq]overlay={pos_expr}[v_out]"
    run_with_progress([
        "ffmpeg", "-y", "-i", in_video_path, "-i", eq_vid,
        "-filter_complex", filter_complex,
        "-map", "[v_out]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", render_preset, "-crf", "18",
        "-c:a", "copy", out_video_path
    ], total_duration=dur, log_callback=log_callback, step_name="Equalizer-Overlay")
    try:
        if os.path.exists(eq_vid): os.remove(eq_vid)
    except Exception: pass

def build_story_image_project(
    script_text_or_path: str,
    image_paths: List[str],
    voice_id: str = "",
    tts_model_id: str = "eleven_multilingual_v2",
    elevenlabs_key: str = "",
    out_path: str = "story_image_output.mp4",
    resolution: str = "1920x1080 (16:9 Landscape)",
    fps: int = 30,
    cache_dir: Optional[str] = None,
    bg_video_paths: Optional[List[str]] = None,
    bg_opacity: float = 0.6,
    logo_path: Optional[str] = None,
    logo_position: str = "Top-Right",
    logo_width: int = 200,
    custom_logo_x: Optional[int] = None,
    custom_logo_y: Optional[int] = None,
    enable_logo: bool = True,
    enable_captions: bool = True,
    caption_font: str = "Impact",
    caption_preset: str = "CapCut Yellow Pop",
    caption_size: int = 28,
    caption_position: str = "Bottom-Center",
    caption_case: str = "ALL CAPS",
    caption_words_per_line: Union[int, str] = "4 Words",
    caption_lines: Union[int, str] = "1 Line (Standard)",
    custom_font_path: Optional[str] = None,
    custom_caption_x: Optional[int] = None,
    custom_caption_y: Optional[int] = None,
    enable_equalizer: bool = False,
    equalizer_style: str = "Spectrum Bars (showfreqs)",
    equalizer_color: str = "#00FFFF",
    equalizer_position: str = "Bottom-Center",
    equalizer_width: int = 500,
    equalizer_height: int = 120,
    custom_eq_x: Optional[int] = None,
    custom_eq_y: Optional[int] = None,
    motion_effect: str = "Auto-Director Flow (Dynamic Scenes)",
    camera_motion: Optional[str] = None,
    enable_visualizer: bool = False,
    visualizer_path: Optional[str] = None,
    visualizer_opacity: float = 0.85,
    visualizer_width: int = 520,
    enable_subscribe: bool = False,
    subscribe_path: Optional[str] = None,
    subscribe_gap: int = 35,
    subscribe_width: int = 220,
    particle_overlay: str = "Off / None",
    intro_video_paths: Optional[List[str]] = None,
    bgm_path: Optional[str] = None,
    bgm_volume: float = 0.2,
    voice_volume: float = 1.0,
    enable_ducking: bool = True,
    parallel_tts_workers: int = 5,
    parallel_video_workers: int = 4,
    render_preset: str = "fast",
    max_workers: int = 5,
    log_callback: LogFn = None,
    **kwargs
) -> str:
    """Master build pipeline for Story Image Video Tab."""
    _orig_log = log_callback
    def _safe_log(msg: str):
        if _orig_log:
            try:
                _orig_log(str(msg))
            except UnicodeEncodeError:
                try:
                    clean_msg = str(msg).encode("ascii", "replace").decode("ascii")
                    _orig_log(clean_msg)
                except Exception:
                    pass
            except Exception:
                pass
    log_callback = _safe_log

    ff = check_ffmpeg()
    if not all(ff.values()):
        raise RuntimeError("FFmpeg and FFprobe are required in PATH.")

    tts_workers = parallel_tts_workers or max_workers
    video_workers = parallel_video_workers or max_workers

    # Read script if file path provided
    if os.path.exists(script_text_or_path):
        with open(script_text_or_path, "r", encoding="utf-8") as sf:
            script_content = sf.read()
    else:
        script_content = script_text_or_path

    scenes = parse_scene_script(script_content)
    if not scenes:
        raise ValueError("No valid scene blocks found in script. Use 'Scene_1_text...' format.")

    if log_callback:
        log_callback(f"[story-image] Parsed {len(scenes)} scene block(s) from script.")

    matched_images = auto_match_images(image_paths, len(scenes))
    if log_callback:
        log_callback(f"[story-image] Matched {len(matched_images)}/{len(scenes)} scene image(s).")

    appdata = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or os.path.expanduser("~")
    safe_data_root = os.path.join(appdata, "StoriesStudio")

    out_abs = os.path.abspath(out_path)
    base_dir = os.path.dirname(out_abs)
    base_name = os.path.splitext(os.path.basename(out_abs))[0]

    # Test writability of base_dir; fallback if in Program Files or read-only location
    try:
        os.makedirs(base_dir, exist_ok=True)
        test_file = os.path.join(base_dir, f".test_perm_{os.getpid()}")
        with open(test_file, "w") as tf: tf.write("ok")
        os.remove(test_file)
    except Exception:
        fallback_out_dir = os.path.join(safe_data_root, "output")
        os.makedirs(fallback_out_dir, exist_ok=True)
        out_abs = os.path.join(fallback_out_dir, os.path.basename(out_path))

    workdir = cache_dir or os.path.join(safe_data_root, "temp_work", f"story_image_{base_name}")
    tts_cache_dir = os.path.join(safe_data_root, "tts_cache")
    os.makedirs(workdir, exist_ok=True)
    os.makedirs(tts_cache_dir, exist_ok=True)

    # Purge stale temp files from previous sessions to prevent disk bloat
    cleanup_stale_temp_work(safe_data_root, max_age_hours=6.0, log_callback=log_callback)
    free_gb = check_free_disk_gb(safe_data_root)
    if log_callback:
        log_callback(f"[Disk Status] Available Disk Space: {free_gb:.1f} GB")
        if free_gb < 4.0:
            log_callback(f"[Disk Warning] Low disk space ({free_gb:.1f} GB)! Running emergency temp cleanup...")
            cleanup_stale_temp_work(safe_data_root, max_age_hours=0.5, log_callback=log_callback)

    # Purge current project workdir (clips/segments) but NOT the persistent TTS cache
    if os.path.exists(workdir):
        try:
            for sub in ("clips", "segments"):
                sp = os.path.join(workdir, sub)
                if os.path.exists(sp):
                    shutil.rmtree(sp, ignore_errors=True)
        except Exception:
            pass

    audio_dir = os.path.join(workdir, "audio")
    seg_dir = os.path.join(workdir, "segments")
    for d in (workdir, audio_dir, seg_dir):
        os.makedirs(d, exist_ok=True)

    res_str = str(resolution).lower()
    fps_val = int(fps) if fps else 30
    if "2160x3840" in res_str:
        profile = {"width": 2160, "height": 3840, "fps": fps_val}
    elif "3840x2160" in res_str or "4k" in res_str:
        profile = {"width": 3840, "height": 2160, "fps": fps_val}
    elif "1440x2560" in res_str:
        profile = {"width": 1440, "height": 2560, "fps": fps_val}
    elif "2560x1440" in res_str or "2k" in res_str:
        profile = {"width": 2560, "height": 1440, "fps": fps_val}
    elif "720x1280" in res_str:
        profile = {"width": 720, "height": 1280, "fps": fps_val}
    elif "1280x720" in res_str or "720p" in res_str:
        profile = {"width": 1280, "height": 720, "fps": fps_val}
    elif "1080x1920" in res_str:
        profile = {"width": 1080, "height": 1920, "fps": fps_val}
    elif "1080x1080" in res_str or "1:1" in res_str:
        profile = {"width": 1080, "height": 1080, "fps": fps_val}
    elif "1440x1080" in res_str or "4:3" in res_str:
        profile = {"width": 1440, "height": 1080, "fps": fps_val}
    else:
        profile = {"width": 1920, "height": 1080, "fps": fps_val}

    # --- TTS Cache Helper ---
    import hashlib
    def _tts_cache_key(text: str, vid: str, model_id: str = "") -> str:
        """Generate hash from text + clean voice_id + model_id for cache lookup."""
        c_vid = clean_voice_id(vid)
        raw = f"{text.strip()}|{c_vid.strip()}|{model_id.strip()}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    # --- Check GPU Hardware Acceleration Status ---
    gpu_info = GPU.get_info()
    if log_callback:
        if gpu_info.get("is_gpu"):
            log_callback(f"[GPU Acceleration] ⚡ Hardware Engine Active: {gpu_info['gpu_name']} ({gpu_info['hw_encoder'].upper()})")
            log_callback(f"[GPU Pipeline] 🚀 Hybrid Parallel: {gpu_info['max_gpu_sessions']} Concurrent GPU NVENC Slots + Parallel CPU Threads")
        else:
            log_callback(f"[GPU Notice] 💻 Running on Multi-threaded CPU ({gpu_info['hw_encoder']})")

    # 1. Parallel TTS Generation (with cache reuse)
    if log_callback:
        log_callback(f"[parallel-tts] Generating audio for {len(scenes)} scenes ({tts_workers} TTS workers)")
        log_callback(f"[voice-debug] voice_id='{voice_id}' | clean='{clean_voice_id(voice_id)}' | model='{tts_model_id}' | key={'SET' if elevenlabs_key else 'MISSING'}")

    def _tts_job(idx: int, sc: Dict[str, Any]):
        a_path = os.path.join(audio_dir, f"scene_{sc['scene_no']:03d}.mp3")

        # 1. Check if scene dict contains explicit audio_path or audio file provided
        sc_audio = sc.get("audio_path") or sc.get("audio")
        if sc_audio and os.path.exists(sc_audio) and os.path.getsize(sc_audio) > 500:
            shutil.copy2(sc_audio, a_path)
            if log_callback:
                log_callback(f"   [CACHE] Used provided audio for Scene {sc['scene_no']}")
            return idx, a_path

        # 2. Check global TTS cache directory
        cache_key = _tts_cache_key(sc["text"], voice_id, tts_model_id)
        cached_file = os.path.join(tts_cache_dir, f"{cache_key}.mp3")

        if os.path.exists(cached_file) and os.path.getsize(cached_file) > 500:
            shutil.copy2(cached_file, a_path)
            if log_callback:
                log_callback(f"   [CACHE] Reused cached audio for Scene {sc['scene_no']}")
            return idx, a_path

        # 3. Check if audio file already exists in local audio_dir
        if os.path.exists(a_path) and os.path.getsize(a_path) > 500:
            if log_callback:
                log_callback(f"   [CACHE] Reused workdir audio for Scene {sc['scene_no']}")
            return idx, a_path

        if log_callback:
            log_callback(f"   [TTS] Synthesizing Scene {sc['scene_no']}/{len(scenes)}...")

        for attempt in range(1, 4):
            try:
                generate_scene_tts(sc["text"], voice_id, tts_model_id, elevenlabs_key, a_path, speed=1.0, log_callback=log_callback)
                if os.path.exists(a_path) and os.path.getsize(a_path) > 100:
                    break
            except Exception as e:
                if attempt == 3:
                    if log_callback:
                        log_callback(f"   [ERROR] TTS failed for Scene {sc['scene_no']}: {e}")
                    raise
                else:
                    time.sleep(1.5 * attempt)

        # Save to persistent cache for future reuse
        if os.path.exists(a_path) and os.path.getsize(a_path) > 500:
            try:
                shutil.copy2(a_path, cached_file)
            except Exception:
                pass
        return idx, a_path

    tts_results: Dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=tts_workers) as executor:
        futures = {}
        for i, sc in enumerate(scenes):
            f = executor.submit(_tts_job, i, sc)
            futures[f] = i
            time.sleep(0.04)  # Rate-limiting stagger to avoid 429 API flooding

        for future in as_completed(futures):
            idx = futures[future]
            try:
                _, a_path = future.result()
                tts_results[idx] = a_path
                if log_callback:
                    log_callback(f"   [OK] Audio ready for Scene {scenes[idx]['scene_no']}")
            except Exception as exc:
                if log_callback:
                    log_callback(f"   [ERROR] Audio generation failed for Scene {scenes[idx]['scene_no']}: {exc}")
                raise RuntimeError(f"Scene {scenes[idx]['scene_no']} audio generation failed: {exc}")

    # 2. Parallel Image Clip Rendering with Selected Motion (Single-Pass Single File)
    eff_motion = camera_motion if camera_motion else motion_effect
    if log_callback:
        log_callback(f"[parallel-clips] Rendering video clips with '{eff_motion}' motion effect ({video_workers} video workers)...")
        log_callback(f"[motion-debug] Active camera motion: '{eff_motion}' -> lower: '{eff_motion.lower()}'")

    def _clip_job(idx: int, sc: Dict[str, Any]):
        a_path = tts_results[idx]
        dur = max(2.0, get_duration(a_path))
        img_p = matched_images.get(sc["scene_no"])
        seg_path = os.path.join(seg_dir, f"segment_{sc['scene_no']:03d}.mp4")

        if log_callback:
            log_callback(f"   [Motion] Animating Scene {sc['scene_no']}/{len(scenes)} ({dur:.1f}s)...")

        # Create solid fallback image if no image matched
        if not img_p or not os.path.exists(img_p):
            img_p = os.path.join(workdir, "fallback_dark.png")
            if not os.path.exists(img_p):
                run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=181B2A:s=1280x720:d=1", "-vframes", "1", img_p])

        # Pick background video for scene if provided
        bg_v = None
        if bg_video_paths:
            valid_bgs = [p for p in bg_video_paths if os.path.exists(p)]
            if valid_bgs:
                bg_v = valid_bgs[idx % len(valid_bgs)]

        # Build fresh clip with exact user-selected motion effect, background looping, and audio synchronously in 1-pass
        build_scene_image_clip(
            img_p, dur, seg_path, profile,
            motion_effect=eff_motion,
            bg_video_path=bg_v,
            bg_opacity=bg_opacity,
            render_preset=render_preset,
            audio_path=a_path,
            log_callback=log_callback,
            scene_no=sc["scene_no"]
        )

        return idx, seg_path, sc["text"]

    # Collect indexed results (as_completed returns in RANDOM order!)
    clip_results: List[Dict[str, Any]] = []
    completed_clips = 0
    total_scenes = len(scenes)

    with ThreadPoolExecutor(max_workers=video_workers) as executor:
        futures = {executor.submit(_clip_job, i, sc): i for i, sc in enumerate(scenes)}
        for future in as_completed(futures):
            try:
                idx, seg_p, stext = future.result()
                completed_clips += 1
                clip_pct = int((completed_clips / total_scenes) * 100)
                clip_results.append({"idx": idx, "scene_no": scenes[idx]["scene_no"], "seg_path": seg_p, "text": stext})
                if log_callback:
                    log_callback(f"   [Motion Progress] Scene {scenes[idx]['scene_no']} clip complete ({completed_clips}/{total_scenes} • {clip_pct}%)")
            except Exception as exc:
                if log_callback:
                    log_callback(f"   [FAIL] Clip failed for Scene {scenes[futures[future]]['scene_no']}: {exc}")
                raise exc

    # Sort by scene_no so segment_paths AND beat_texts are in correct sequence
    clip_results.sort(key=lambda r: r["scene_no"])
    segment_paths = [r["seg_path"] for r in clip_results]
    beat_texts = [r["text"] for r in clip_results]

    if log_callback:
        log_callback(f"[sequence] Final order: {[r['scene_no'] for r in clip_results]}")

    # 3. Concatenate Scene Segments (Robust Multi-Stage Concat Demuxer)
    concat_txt = os.path.join(workdir, "segments.txt")
    with open(concat_txt, "w", encoding="utf-8") as f:
        for p in segment_paths:
            safe_p = os.path.abspath(p).replace("\\", "/")
            f.write(f"file '{safe_p}'\n")

    concat_out = os.path.join(workdir, "story_concat.mp4")
    if log_callback:
        log_callback("[final] Concatenating scene video segments...")

    concat_success = False
    # Attempt 1: Fast Stream-Copy with PTS generation & zero-timestamp alignment
    try:
        run([
            "ffmpeg", "-y", "-fflags", "+genpts", "-f", "concat", "-safe", "0", "-i", concat_txt,
            "-avoid_negative_ts", "make_zero", "-c", "copy", concat_out
        ])
        if os.path.exists(concat_out) and os.path.getsize(concat_out) > 1000:
            concat_success = True
    except Exception as e_c1:
        if log_callback:
            log_callback(f"[concat] Fast stream-copy notice ({e_c1}), falling back to audio re-encode concat...")

    # Attempt 2: Video Stream-Copy + Audio Re-encode (fixes any subtle audio DTS boundary shifts)
    if not concat_success:
        try:
            run([
                "ffmpeg", "-y", "-fflags", "+genpts", "-f", "concat", "-safe", "0", "-i", concat_txt,
                "-avoid_negative_ts", "make_zero", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", concat_out
            ])
            if os.path.exists(concat_out) and os.path.getsize(concat_out) > 1000:
                concat_success = True
        except Exception as e_c2:
            if log_callback:
                log_callback(f"[concat] Re-encode fallback notice ({e_c2}), using filter_complex concat...")

    # Attempt 3: Filter-Complex Concat (Universal bulletproof fallback)
    if not concat_success:
        fc_inputs = []
        for p in segment_paths:
            fc_inputs.extend(["-i", p])
        fc_map = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(len(segment_paths))) + f"concat=n={len(segment_paths)}:v=1:a=1[v][a]"
        run([
            "ffmpeg", "-y", *fc_inputs,
            "-filter_complex", fc_map,
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            concat_out
        ])

    current_v = concat_out

    # 4. Overlays & Subtitles (Visualizer + Subscribe Button + Logo + CapCut Captions)
    has_vis = bool(enable_visualizer and visualizer_path and os.path.exists(visualizer_path))
    has_sub = bool(enable_subscribe and subscribe_path and os.path.exists(subscribe_path))
    has_logo = bool(enable_logo and logo_path and os.path.exists(logo_path))
    has_caps = bool(enable_captions)

    ass_path = None
    if has_caps:
        ass_path = os.path.join(workdir, "story_captions.ass")
        if log_callback:
            log_callback(f"[final] Generating CapCut subtitles ({caption_case}, {caption_words_per_line})...")
        from recap_engine_v2_8 import EditBeat, generate_capcut_ass_file
        beats = [EditBeat(line_no=i+1, text=t, shots=[]) for i, t in enumerate(beat_texts)]
        audio_files_sorted = [os.path.join(audio_dir, f"scene_{r['scene_no']:03d}.mp3") for r in clip_results]
        durations = [get_duration(af) for af in audio_files_sorted]
        try:
            import inspect
            sig = inspect.signature(generate_capcut_ass_file)
            ass_kw = {
                "font_name": caption_font,
                "font_size": caption_size,
                "preset_style": caption_preset,
                "position": caption_position,
                "text_case": caption_case,
                "max_words_per_line": caption_words_per_line,
                "custom_font_path": custom_font_path,
                "custom_caption_x": custom_caption_x,
                "custom_caption_y": custom_caption_y,
                "max_lines_per_screen": caption_lines,
            }
            filtered_kw = {k: v for k, v in ass_kw.items() if k in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())}
            generate_capcut_ass_file(beats, durations, ass_path, **filtered_kw)
        except Exception as e_ass:
            if log_callback:
                log_callback(f"[final] Advanced subtitle fallback notice ({e_ass}), generating standard subtitles...")
            try:
                generate_capcut_ass_file(
                    beats, durations, ass_path,
                    font_name=caption_font, font_size=caption_size,
                    preset_style=caption_preset, position=caption_position,
                    text_case=caption_case, max_words_per_line=caption_words_per_line
                )
            except Exception as e_ass_basic:
                if log_callback:
                    log_callback(f"[final] Standard subtitle generation notice: {e_ass_basic}")

    if has_vis or has_sub or has_logo or has_caps:
        layered_out = os.path.join(workdir, "final_layered_output.mp4")
        if log_callback:
            active_elements = []
            if has_vis: active_elements.append("Audio Visualizer (Behind Captions)")
            if has_sub: active_elements.append(f"Subscribe Button (Bottom-Left Loop every {subscribe_gap}s)")
            if has_logo: active_elements.append(f"Logo Watermark ({logo_position})")
            if has_caps: active_elements.append(f"CapCut Subtitles ({caption_preset})")
            log_callback(f"[final] [Single-Pass ⚡] Rendering {' + '.join(active_elements)}...")

        apply_story_overlays_and_subtitles(
            video_path=current_v,
            out_path=layered_out,
            visualizer_path=visualizer_path if has_vis else None,
            visualizer_opacity=visualizer_opacity,
            visualizer_width=visualizer_width,
            subscribe_path=subscribe_path if has_sub else None,
            subscribe_gap=subscribe_gap,
            subscribe_width=subscribe_width,
            logo_path=logo_path if has_logo else None,
            logo_position=logo_position,
            logo_width=logo_width,
            custom_logo_x=custom_logo_x,
            custom_logo_y=custom_logo_y,
            ass_path=ass_path if (has_caps and os.path.exists(ass_path)) else None,
            custom_font_path=custom_font_path,
            render_preset=render_preset,
            log_callback=log_callback
        )
        if os.path.exists(layered_out) and os.path.getsize(layered_out) > 1000:
            current_v = layered_out

    # 7. Prepend Intro Video if provided
    valid_intros = [p for p in (intro_video_paths or []) if os.path.exists(p)]
    if valid_intros:
        if log_callback:
            log_callback(f"[final] Prepending {len(valid_intros)} intro video(s)...")
        intro_concat_txt = os.path.join(workdir, "intro_concat.txt")
        with open(intro_concat_txt, "w", encoding="utf-8") as f:
            for ip in valid_intros + [current_v]:
                safe_ip = os.path.abspath(ip).replace("\\", "/")
                f.write(f"file '{safe_ip}'\n")
        
        final_movie = os.path.join(workdir, "story_final_with_intro.mp4")
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", intro_concat_txt, "-c", "copy", final_movie])
        current_v = final_movie

    # Copy final output to requested path
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    shutil.copy2(current_v, out_path)

    # Automatic cleanup of temporary rendering video segments to save disk space, preserving audio & SRT
    try:
        if os.path.exists(workdir):
            if log_callback:
                log_callback("[cleanup] Cleaning up intermediate video segment clips (Audio & Subtitles preserved)...")
            # Delete segments and clips subdirectories
            for sub_d in ("segments", "clips"):
                sub_path = os.path.join(workdir, sub_d)
                if os.path.exists(sub_path):
                    shutil.rmtree(sub_path, ignore_errors=True)
            for f_item in os.listdir(workdir):
                f_p = os.path.join(workdir, f_item)
                ext_lower = os.path.splitext(f_item)[1].lower()
                if ext_lower in ['.mp4', '.mkv', '.mov', '.avi'] or f_item.endswith('.txt'):
                    try:
                        if os.path.abspath(f_p) != os.path.abspath(out_path):
                            if os.path.isfile(f_p) or os.path.islink(f_p):
                                os.unlink(f_p)
                    except Exception:
                        pass
            if log_callback:
                log_callback("[cleanup] Temp video segment clips cleaned up successfully (Audio & SRT preserved ✓)")
    except Exception as _cl_e:
        if log_callback:
            log_callback(f"[cleanup warning] Could not purge temp video segments: {_cl_e}")

    if log_callback:
        analytics = GPU.get_analytics()
        final_dur = get_duration(out_path)
        log_callback("=" * 64)
        log_callback(f"[Analytics] ⏱️ Story Image Video Render Summary:")
        log_callback(f"   • Output Duration : {final_dur:.1f}s ({format(final_dur/60, '.1f')} min)")
        log_callback(f"   • GPU Hardware Clips : {analytics.get('gpu_clips', 0)} ({GPU.hw_encoder.upper()})")
        log_callback(f"   • CPU Multi-thread Clips : {analytics.get('cpu_clips', 0)}")
        log_callback(f"   • Acceleration Profile : {gpu_info.get('speed_tier', 'Standard')}")
        log_callback(f"   • Saved To : {out_path}")
        log_callback("=" * 64)
        log_callback(f"[story-image] [SUCCESS] Output video created -> {out_path}")

    return out_path
