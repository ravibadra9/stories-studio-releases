"""
whisper_engine.py
─────────────────
openai-whisper ka DROP-IN replacement, faster-whisper ke upar.

Kyun?
  openai-whisper  → PyTorch chahiye  → ~2.5 GB → installer 1.5 GB 💀
  faster-whisper  → CTranslate2      → ~40 MB  → installer ~200 MB ✅
                    Same OpenAI models, 4x tez, kam RAM.

API bilkul same rakhi hai, taaki stories_app.py mein sirf ek line badle:
      import whisper              →  import whisper_engine as whisper

Exposed API:
    load_model(size, device="auto")  ->  Model
    Model.transcribe(path, language=None, word_timestamps=True, **kw)
         ->  {"text": str, "segments": [{"text","start","end","words"}, ...]}
    model_is_downloaded(size) -> bool
    cache_root() -> str
"""

import os
import sys

# Models yahan cache honge (openai-whisper jaisa hi pattern)
_CACHE = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "StoriesStudio", "whisper_models",
)


def cache_root() -> str:
    os.makedirs(_CACHE, exist_ok=True)
    return _CACHE


def bundled_model_dir(size: str) -> str:
    """
    Installer ke saath pack hua model (bundled_models/faster-whisper-<size>).
    Mile to uska path, warna "". Yeh sabse pehle check hota hai — download
    ki zaroorat hi nahi padti.
    """
    candidates = []
    # Frozen exe: PyInstaller data _MEIPASS/_internal mein hoti hai
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(os.path.join(meipass, "bundled_models",
                                       f"faster-whisper-{size}"))
        candidates.append(os.path.join(os.path.dirname(sys.executable),
                                       "bundled_models", f"faster-whisper-{size}"))
    # Dev mode: script ke bagal mein
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "bundled_models", f"faster-whisper-{size}"))
    for c in candidates:
        if os.path.isfile(os.path.join(c, "model.bin")):
            return c
    return ""


def model_is_downloaded(size: str) -> bool:
    """Model available hai ya nahi — bundled YA cache mein."""
    if bundled_model_dir(size):
        return True
    try:
        root = cache_root()
        if not os.path.isdir(root):
            return False
        # faster-whisper HF cache use karta hai: models--Systran--faster-whisper-<size>
        for name in os.listdir(root):
            if size in name and os.path.isdir(os.path.join(root, name)):
                # snapshot ke andar model.bin hona chahiye
                for dirpath, _, files in os.walk(os.path.join(root, name)):
                    if "model.bin" in files:
                        return True
        return False
    except Exception:
        return False


def _cuda_available() -> bool:
    """
    CUDA device dikhna alag baat hai, cuBLAS + cuDNN DLLs hona alag.
    CTranslate2 ko cuda pe chalane ke liye cublas (cublas64_12.dll / cublas64_11.dll)
    aur cuDNN (cudnn_ops64_9.dll, etc.) dono runtime DLLs chahiye.
    DLL missing ho to ctranslate2 exception deta hai (cublas64_12.dll is not found).
    Isliye cuda choose karne se PEHLE DLLs load karke verify karo.
    """
    if sys.platform != "win32":
        return True
    import ctypes
    
    # 1. Verify cuBLAS
    cublas_ok = False
    for name in ("cublas64_12.dll", "cublas64_11.dll", "cublasLt64_12.dll", "cublasLt64_11.dll"):
        try:
            ctypes.WinDLL(name)
            cublas_ok = True
            break
        except OSError:
            continue
    if not cublas_ok:
        return False

    # 2. Verify cuDNN
    cudnn_ok = False
    for name in ("cudnn_ops64_9.dll", "cudnn_ops_infer64_8.dll",
                 "cudnn64_9.dll", "cudnn64_8.dll"):
        try:
            ctypes.WinDLL(name)
            cudnn_ok = True
            break
        except OSError:
            continue
    return cudnn_ok


def _pick_device(requested: str = "auto"):
    """
    (device, compute_type) return karta hai.
    CUDA + cuBLAS + cuDNN sabhi available hon to GPU (cuda, float16),
    warna guaranteed CPU int8 (tez + halka + zero external DLL requirements).
    """
    if requested == "cpu":
        return "cpu", "int8"
    if requested == "cuda":
        return "cuda", "float16"

    # Windows crash fix: CTranslate2 CUDA float16 inside Windows processes
    # frequently throws STATUS_STACK_BUFFER_OVERRUN (0xc0000409) in ucrtbase.dll.
    # CPU int8 is fast (2-4s), lightweight, and 100% crash-proof across all Windows versions.
    if sys.platform == "win32":
        return "cpu", "int8"

    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0 and _cuda_available():
            return "cuda", "float16"
    except Exception:
        pass

    return "cpu", "int8"


def _import_whisper_model():
    """
    faster_whisper import karo. Agar 'av' (PyAV) ki wajah se fail ho —
    "DLL load failed" ya "No module named av" — to av ka stub daal ke retry.

    Kyun safe hai: av ka use faster-whisper sirf audio DECODE ke liye karta
    hai. Hum whisper ko hamesha khud-decoded numpy array dete hain (neeche
    _read_pcm_wav), to av ke functions kabhi call hi nahi hote. Smart App
    Control av ki unsigned FFmpeg DLLs block kar de tab bhi captions chalenge.
    """
    try:
        from faster_whisper import WhisperModel
        return WhisperModel
    except Exception as e:
        msg = str(e).lower()
        if not ("av" in msg and ("dll" in msg or "module" in msg)):
            raise
        import types
        class _StubResampler:                       # kabhi call nahi hota
            def __init__(self, *a, **k):
                raise RuntimeError("PyAV unavailable on this PC")
        for name in ("av", "av.audio", "av.audio.resampler", "av.error"):
            if name not in sys.modules:
                m = types.ModuleType(name)
                m.__version__ = "0.0.0-stub"
                m.AudioResampler = _StubResampler
                m.open = _StubResampler
                m.FFmpegError = Exception
                sys.modules[name] = m
        # Parent modules pe child attributes bhi set karo taaki
        # "from av.audio.resampler import AudioResampler" har Python
        # version mein chale.
        sys.modules["av"].audio = sys.modules["av.audio"]
        sys.modules["av"].error = sys.modules["av.error"]
        sys.modules["av.audio"].resampler = sys.modules["av.audio.resampler"]
        from faster_whisper import WhisperModel
        return WhisperModel


def _read_pcm_wav(path):
    """
    App ka extracted WAV (pcm_s16le, mono, 16 kHz) khud decode karke
    float32 numpy array do — bilkul woh format jo faster-whisper chahta hai.
    Yahi asli fix hai: av/FFmpeg-DLL ki zaroorat transcription se hat jaati hai.
    Kuch bhi unexpected ho (format alag, file corrupt) → None, caller
    path-mode pe fallback kar lega.
    """
    try:
        import wave
        import numpy as np
        with wave.open(path, "rb") as w:
            ch = w.getnchannels()
            width = w.getsampwidth()
            rate = w.getframerate()
            if width != 2 or rate != 16000:
                return None
            data = w.readframes(w.getnframes())
        if not data:
            return None
        arr = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        if ch > 1:
            arr = arr.reshape(-1, ch).mean(axis=1)
        return arr
    except Exception:
        return None


class _Segment(dict):
    """Plain dict — app seg.get("text"/"start"/"end") karta hai, bas kaam ho gaya."""
    pass


class Model:
    def __init__(self, size: str, device: str = "auto"):
        WhisperModel = _import_whisper_model()

        dev, compute = _pick_device(device)
        self.device = dev
        self.compute_type = compute
        self.size = size

        # Bundled model pehle — installer ke saath aaya hai to seedha
        # local folder se load, na download na cache lookup.
        src = bundled_model_dir(size) or size

        try:
            self._m = WhisperModel(
                src,
                device=dev,
                compute_type=compute,
                download_root=cache_root(),
            )
        except Exception:
            # GPU init fail (driver/cuDNN/cuBLAS issue) → CPU int8 pe retry.
            if dev == "cpu":
                raise
            self.device, self.compute_type = "cpu", "int8"
            self._m = WhisperModel(
                src,
                device="cpu",
                compute_type="int8",
                download_root=cache_root(),
            )

    def transcribe(self, audio_path: str, **kwargs) -> dict:
        """
        openai-whisper ke result dict ki shakal mein output deta hai.
        Unsupported kwargs (fp16, verbose) chup-chaap ignore ho jate hain.
        """
        language = kwargs.get("language")
        if language in ("auto", ""):
            language = None

        word_ts = bool(kwargs.get("word_timestamps", True))

        # ── OLD-FILE IDEA, POORA KIYA HUA ──
        # App pehle hi ffmpeg se clean 16kHz mono WAV nikaal deta hai.
        # Usko hum KHUD decode karke numpy array dete hain — av (PyAV)
        # transcription mein kabhi use hi nahi hota. WAV read fail ho to
        # purana path-mode fallback (jismein av chahiye hota hai).
        audio_input = audio_path
        if isinstance(audio_path, str) and audio_path.lower().endswith(".wav"):
            arr = _read_pcm_wav(audio_path)
            if arr is not None and len(arr) > 0:
                audio_input = arr

        try:
            segments_iter, info = self._m.transcribe(
                audio_input,
                language=language,
                word_timestamps=word_ts,
                vad_filter=True,                       # silence skip -> tez + saaf
                vad_parameters={"min_silence_duration_ms": 500},
                beam_size=5,
            )

            segments = []
            full_text = []

            for s in segments_iter:                    # generator — yahin actual kaam hota hai
                txt = (s.text or "").strip()
                if not txt:
                    continue

                words = []
                if word_ts and getattr(s, "words", None):
                    for w in s.words:
                        words.append({
                            "word": w.word,
                            "start": float(w.start),
                            "end": float(w.end),
                            "probability": float(getattr(w, "probability", 1.0)),
                        })

                segments.append(_Segment({
                    "id": len(segments),
                    "text": txt,
                    "start": float(s.start),
                    "end": float(s.end),
                    "words": words,
                }))
                full_text.append(txt)

            return {
                "text": " ".join(full_text),
                "segments": segments,
                "language": getattr(info, "language", language or "en"),
            }
        except Exception as exc:
            err_msg = str(exc).lower()
            # If CUDA DLL (cublas64_12.dll, cudnn, out of memory, or driver mismatch) fails at runtime:
            if self.device != "cpu" and any(k in err_msg for k in ("cublas", "cudnn", "cuda", "memory", "not found", "cannot be loaded")):
                WhisperModel = _import_whisper_model()
                src = bundled_model_dir(self.size) or self.size
                self.device, self.compute_type = "cpu", "int8"
                self._m = WhisperModel(
                    src,
                    device="cpu",
                    compute_type="int8",
                    download_root=cache_root(),
                )
                return self.transcribe(audio_path, **kwargs)
            raise

        return {
            "text": " ".join(full_text).strip(),
            "segments": segments,
            "language": getattr(info, "language", language or "en"),
        }


def load_model(size: str, device: str = "auto", **_ignored) -> Model:
    """openai-whisper ka whisper.load_model() jaisa hi."""
    return Model(size, device=device)


def predownload(size: str = "base") -> bool:
    """
    Model ko background mein pehle se download kar lo (boot time pe call hota hai).
    Pehle se cached hai to turant True. Net nahi hai to chup-chaap False —
    koi crash nahi, koi popup nahi.
    """
    try:
        if model_is_downloaded(size):
            return True
        # CPU pe load karna hi download trigger karta hai. Ek baar load hone ke
        # baad model files cache mein rehti hain; object discard kar do.
        Model(size, device="cpu")
        return model_is_downloaded(size)
    except Exception:
        return False


# ── Self-test ────────────────────────────────────────────────
if __name__ == "__main__":
    dev, comp = _pick_device()
    print(f"Device       : {dev} ({comp})")
    print(f"Cache root   : {cache_root()}")
    for s in ("tiny", "base", "small", "medium", "large-v3"):
        print(f"  {s:10s} downloaded: {model_is_downloaded(s)}")

    if len(sys.argv) > 1:
        print("\nTranscribing:", sys.argv[1])
        m = load_model("base")
        r = m.transcribe(sys.argv[1])
        print("TEXT:", r["text"][:300])
        print("SEGMENTS:", len(r["segments"]))
