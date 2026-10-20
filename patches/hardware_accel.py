"""
hardware_accel.py — High-Performance Hardware Acceleration & Process Optimizer
══════════════════════════════════════════════════════════════════════════════
1. Silences ALL Windows CMD popup windows globally (subprocess monkey-patch).
2. Probes GPU hardware once, caches across all modules & persists to disk.
3. Provides instantaneous (0ms) hardware acceleration lookups for all tabs.
"""

import os
import sys
import json
import subprocess
import threading
from pathlib import Path
from typing import Dict, Any, List

# ══════════════════════════════════════════════════════════════════════════════
# 1. GLOBAL PROCESS SILENCER (Prevents black CMD windows on Windows)
# ══════════════════════════════════════════════════════════════════════════════
def silence_all_windows_processes():
    """Globally ensure all subprocess calls hide console windows on Windows."""
    if sys.platform != "win32":
        return

    if getattr(subprocess, "_STP_SILENCED", False):
        return
    subprocess._STP_SILENCED = True

    _orig_popen_init = subprocess.Popen.__init__

    def _safe_popen_init(self, *args, **kwargs):
        # 1. Inject STARTUPINFO to hide window
        si = kwargs.get("startupinfo")
        if si is None:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            kwargs["startupinfo"] = si
        else:
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0

        # 2. Inject CREATE_NO_WINDOW (0x08000000)
        cflags = kwargs.get("creationflags", 0)
        kwargs["creationflags"] = cflags | 0x08000000

        return _orig_popen_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _safe_popen_init

silence_all_windows_processes()


# ══════════════════════════════════════════════════════════════════════════════
# 2. CACHE PATH & GLOBALS
# ══════════════════════════════════════════════════════════════════════════════
_CACHE_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "StoriesStudio"
_CACHE_FILE = _CACHE_DIR / "hardware_accel_cache.json"

_HW_LOCK = threading.Lock()
_GLOBAL_GPU_DATA = getattr(sys, "_MASTER_GPU_CACHE", None)


def _load_disk_cache() -> Dict[str, Any]:
    try:
        if _CACHE_FILE.exists():
            with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and data.get("hw_encoder"):
                    return data
    except Exception:
        pass
    return None


def _save_disk_cache(data: Dict[str, Any]):
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# 3. PROBING UTILITIES
# ══════════════════════════════════════════════════════════════════════════════
def _detect_gpu_name() -> tuple[str, str]:
    """Returns (gpu_name, vendor_str)."""
    # 1. Try nvidia-smi
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=2
        )
        if r.returncode == 0 and r.stdout.strip():
            name = r.stdout.split("\n")[0].split(",")[0].strip()
            return name, "nvidia"
    except Exception:
        pass

    # 2. Windows CIM / WMI
    if sys.platform == "win32":
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
                capture_output=True, text=True, timeout=3
            )
            lines = [l.strip() for l in r.stdout.split("\n") if l.strip() and "virtual" not in l.lower() and "rdp" not in l.lower()]
            if lines:
                name = lines[0]
                n_low = name.lower()
                if "nvidia" in n_low or "geforce" in n_low or "rtx" in n_low or "gtx" in n_low or "quadro" in n_low:
                    return name, "nvidia"
                elif "amd" in n_low or "radeon" in n_low:
                    return name, "amd"
                elif "intel" in n_low or "iris" in n_low or "uhd" in n_low or "arc" in n_low:
                    return name, "intel"
                return name, "generic"
        except Exception:
            pass

    return "Unknown GPU", "none"


def _get_available_encoders() -> set:
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=5
        )
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


def _test_encoder(encoder_name: str) -> bool:
    try:
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            "color=c=black:s=320x240:d=0.05:r=30",
            "-c:v", encoder_name, "-frames:v", "2",
            "-f", "null", "-"
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=3)
        return (r.returncode == 0)
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# 4. MASTER DETECTION & SINGLETON
# ══════════════════════════════════════════════════════════════════════════════
def get_hardware_info(force_refresh: bool = False) -> Dict[str, Any]:
    """Retrieve GPU hardware acceleration config in 0ms (from memory/disk)."""
    global _GLOBAL_GPU_DATA
    if not force_refresh:
        if _GLOBAL_GPU_DATA:
            return _GLOBAL_GPU_DATA
        disk_data = _load_disk_cache()
        if disk_data:
            _GLOBAL_GPU_DATA = disk_data
            sys._MASTER_GPU_CACHE = disk_data
            return disk_data

    with _HW_LOCK:
        if not force_refresh and _GLOBAL_GPU_DATA:
            return _GLOBAL_GPU_DATA

        print("[GPU] Initializing hardware acceleration engine...")
        gpu_name, vendor = _detect_gpu_name()
        available = _get_available_encoders()

        hw_encoder = "libx264"
        is_gpu = False
        hw_decoder_args = []
        enc_preset_fast = "fast"
        enc_preset_vfast = "veryfast"
        enc_preset_ufast = "ultrafast"
        enc_quality = ["-crf", "18"]
        enc_extra = []
        pix_fmt = "yuv420p"

        # Check vendor priority
        if vendor == "nvidia" or "h264_nvenc" in available:
            if _test_encoder("h264_nvenc"):
                vendor = "nvidia"
                hw_encoder = "h264_nvenc"
                is_gpu = True
                hw_decoder_args = ["-hwaccel", "cuda"]
                enc_preset_fast = "p4"
                enc_preset_vfast = "p2"
                enc_preset_ufast = "p1"
                enc_quality = ["-rc", "vbr", "-cq", "20", "-b:v", "0"]
                enc_extra = ["-rc-lookahead", "8"]

        if not is_gpu and (vendor == "intel" or "h264_qsv" in available):
            if _test_encoder("h264_qsv"):
                vendor = "intel"
                hw_encoder = "h264_qsv"
                is_gpu = True
                hw_decoder_args = ["-hwaccel", "qsv"]
                enc_preset_fast = "fast"
                enc_preset_vfast = "veryfast"
                enc_preset_ufast = "veryfast"
                enc_quality = ["-global_quality", "22"]

        if not is_gpu and (vendor == "amd" or "h264_amf" in available):
            if _test_encoder("h264_amf"):
                vendor = "amd"
                hw_encoder = "h264_amf"
                is_gpu = True
                hw_decoder_args = ["-hwaccel", "d3d11va"]
                enc_preset_fast = "balanced"
                enc_preset_vfast = "speed"
                enc_preset_ufast = "speed"
                enc_quality = ["-rc", "vbr_latency", "-qp_i", "20", "-qp_p", "22"]

        if not is_gpu and ("h264_mf" in available):
            if _test_encoder("h264_mf"):
                hw_encoder = "h264_mf"
                is_gpu = True
                hw_decoder_args = ["-hwaccel", "d3d11va"]
                enc_preset_fast = ""
                enc_preset_vfast = ""
                enc_preset_ufast = ""
                enc_quality = ["-b:v", "8M"]

        if not is_gpu and ("h264_videotoolbox" in available):
            if _test_encoder("h264_videotoolbox"):
                vendor = "apple"
                hw_encoder = "h264_videotoolbox"
                is_gpu = True
                hw_decoder_args = ["-hwaccel", "videotoolbox"]
                enc_preset_fast = ""
                enc_preset_vfast = ""
                enc_preset_ufast = ""
                enc_quality = ["-q:v", "65"]
                enc_extra = ["-allow_sw", "1"]

        data = {
            "gpu_name": gpu_name,
            "gpu_vendor": vendor,
            "hw_encoder": hw_encoder,
            "is_gpu": is_gpu,
            "hw_decoder_args": hw_decoder_args,
            "enc_preset_fast": enc_preset_fast,
            "enc_preset_vfast": enc_preset_vfast,
            "enc_preset_ufast": enc_preset_ufast,
            "enc_quality": enc_quality,
            "enc_extra": enc_extra,
            "pix_fmt": pix_fmt
        }

        _GLOBAL_GPU_DATA = data
        sys._MASTER_GPU_CACHE = data
        _save_disk_cache(data)
        print(f"[GPU] Configured: {hw_encoder} ({gpu_name}) | GPU Active: {is_gpu}")
        return data


class MasterGPUConfig:
    """Universal Drop-in GPUConfig for all existing modules."""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init_values()
        return cls._instance

    def _init_values(self):
        hw = get_hardware_info()
        for k, v in hw.items():
            setattr(self, k, v)

    def refresh(self):
        hw = get_hardware_info(force_refresh=True)
        for k, v in hw.items():
            setattr(self, k, v)

    def enc_args(self, preset="fast", quality="normal") -> List[str]:
        args = ["-c:v", self.hw_encoder]
        if self.pix_fmt:
            args += ["-pix_fmt", self.pix_fmt]
        p = self.enc_preset_fast if preset == "fast" else self.enc_preset_vfast
        if p and self.hw_encoder not in ("h264_mf", "h264_videotoolbox"):
            args += ["-preset", p]
        args += self.enc_quality
        args += self.enc_extra
        return args

    def dec_args(self) -> List[str]:
        return list(self.hw_decoder_args)

    def summary(self) -> str:
        if not self.is_gpu or self.hw_encoder == "libx264":
            if self.gpu_name and self.gpu_name not in ("None", "Unknown", "Unknown GPU", ""):
                return f"CPU ({self.gpu_name})"
            return "CPU (libx264)"
        v = self.gpu_vendor.upper() if self.gpu_vendor != "none" else "GPU"
        return f"{v} — {self.hw_encoder} ({self.gpu_name})"

    def info_str(self) -> str:
        return self.summary()

    def set_mode(self, mode: str):
        pass

    def get_mode(self) -> str:
        return "auto"

    def get_info(self) -> Dict[str, Any]:
        return {
            "gpu_name": self.gpu_name,
            "gpu_vendor": self.gpu_vendor,
            "hw_encoder": self.hw_encoder,
            "is_gpu": self.is_gpu,
            "speed_tier": "Ultra Fast (Hardware NVENC)" if self.gpu_vendor == "nvidia" else ("Hardware Accelerated" if self.is_gpu else "Standard CPU")
        }

    def get_analytics(self) -> Dict[str, Any]:
        return {
            "active_gpu": 0,
            "active_cpu": 0,
            "gpu_clips": 0,
            "cpu_clips": 0,
            "last_speed": "1.0x",
            "last_fps": 30.0,
            "total_frames": 0,
        }


# Aliases & Singletons for cross-module compatibility
detect_hardware_acceleration = get_hardware_info
GPU = MasterGPUConfig()

