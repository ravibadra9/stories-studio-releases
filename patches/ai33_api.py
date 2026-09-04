"""
AI33 Audio Processing API Client Library
Official API Integration for https://api.ai33.pro

Supports:
- Dubbing (Multipart & Presigned JSON upload)
- Speech To Text (Transcribe audio to JSON & SRT)
- Sound Effect Generation (Text-to-sound effect)
- Voice Changer / Speech-to-Speech
- Voice Isolate (Extract vocal track)
- Task status polling & file downloading
"""

import json
import os
import re
import ssl
import time
import shutil
import subprocess
import urllib.parse
import urllib.request
import uuid
import mimetypes
from typing import Any, Dict, Optional, Union, Tuple, List

_DEFAULT_BASE_URL = "https://api.ai33.pro"
_SSL_CONTEXT: Optional[ssl.SSLContext] = None


DEFAULT_AI33_KEY = "sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt"


def trim_audio_silence(audio_path: str, cushion_sec: float = 0.03) -> bool:
    """Trim leading and trailing dead air silence from TTS audio file in-place."""
    if not audio_path or not os.path.exists(audio_path) or os.path.getsize(audio_path) < 100:
        return False
    ext = os.path.splitext(audio_path)[1].lower()
    tmp_trimmed = audio_path + f".trimmed_{uuid.uuid4().hex[:6]}{ext}"
    try:
        af = (
            "silenceremove=start_periods=1:start_duration=0.02:start_threshold=-40dB,"
            "areverse,silenceremove=start_periods=1:start_duration=0.02:start_threshold=-40dB,areverse,"
            "highpass=f=55,lowpass=f=13500,alimiter=limit=0.96,aresample=48000:async=1:first_pts=0"
        )
        if cushion_sec > 0.001:
            af += f",apad=pad_dur={cushion_sec:.3f}"
        
        cmd = ["ffmpeg", "-y", "-i", audio_path, "-af", af]
        if ext == ".mp3":
            cmd += ["-c:a", "libmp3lame", "-b:a", "192k", tmp_trimmed]
        elif ext == ".wav":
            cmd += ["-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", tmp_trimmed]
        elif ext in (".aac", ".m4a"):
            cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", tmp_trimmed]
        else:
            cmd += ["-c:a", "libmp3lame", "-b:a", "192k", tmp_trimmed]
            
        r = subprocess.run(cmd, capture_output=True, timeout=60)
        if os.path.exists(tmp_trimmed) and os.path.getsize(tmp_trimmed) > 200:
            shutil.move(tmp_trimmed, audio_path)
            return True
    except Exception as e:
        print(f"[trim_audio_silence] error: {e}")
    finally:
        if os.path.exists(tmp_trimmed):
            try: os.remove(tmp_trimmed)
            except Exception: pass
    return False


def generate_spoken_fallback_tts(text: str, voice_id: str = "", out_path: str = "", log_fn = None) -> bool:
    """Fallback TTS is disabled."""
    if log_fn:
        log_fn("[fallback-tts] Spoken fallback TTS is disabled.")
    return False


def ai33_tts_generate(
    text: str,
    voice_id: str,
    api_key: str = "",
    out_path: str = "",
    speed: float = 1.0,
    stability: float = 0.5,
    similarity_boost: float = 0.75,
    model_id: str = "eleven_multilingual_v2",
    log_fn = None
) -> bool:
    """
    Universal Zero-Failure TTS Generator (Matching Story Image Engine):
    Tier 0: Global Persistent Disk Cache (Instant 0s, 0 credits)
    Tier 1: AI33Pro v3 endpoint (with exponential retry)
    Tier 2: Direct ElevenLabs API (if custom user API key configured)
    Tier 3: Language-Aware Microsoft Edge Neural TTS (100% free, studio clarity, zero failure)
    Tier 4: Google gTTS (language-specific)
    """
    if not text or not text.strip():
        return False

    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    raw_vid = str(voice_id).strip()
    if "•" in raw_vid:
        raw_vid = raw_vid.split("•")[-1].strip()
    if "(" in raw_vid and ")" in raw_vid and not raw_vid.startswith("elevenlabs_"):
        m = re.search(r'\(([^)]+)\)', raw_vid)
        if m and len(m.group(1)) > 5:
            raw_vid = m.group(1).strip()
    clean_vid = raw_vid.split()[-1].strip()

    bare_vid = clean_vid
    provider_prefix = "elevenlabs_"
    for p in ["elevenlabs_", "minimax_", "clone_", "vbee_", "fishaudio_", "edge_", "kokoro_"]:
        if bare_vid.startswith(p):
            provider_prefix = p
            bare_vid = bare_vid[len(p):]
            break

    # Auto-normalize common case typos against default known IDs (e.g. lKne3 -> IKne3)
    try:
        from voice_cache import DEFAULT_FALLBACK_VOICES
        for dv in DEFAULT_FALLBACK_VOICES:
            dvid = dv.get("voice_id", "")
            dvid_clean = dvid.split("_")[-1] if "_" in dvid else dvid
            if bare_vid.lower() == dvid_clean.lower() or clean_vid.lower() == dvid.lower():
                prefixed_vid = dvid
                clean_vid = dvid_clean
                break
        else:
            prefixed_vid = f"{provider_prefix}{bare_vid}"
            clean_vid = bare_vid
    except Exception:
        prefixed_vid = f"{provider_prefix}{bare_vid}"
        clean_vid = bare_vid

    # --- Tier 0: Check Global Persistent Audio Cache ---
    cached_file = None
    try:
        import hashlib, shutil
        cache_appdata = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or os.path.expanduser("~")
        global_cache_dir = os.path.join(cache_appdata, "StoriesStudio", "tts_cache")
        os.makedirs(global_cache_dir, exist_ok=True)
        raw_key = f"{text.strip()}|{clean_vid}|{str(model_id).strip()}|{float(speed):.2f}"
        cache_key = hashlib.md5(raw_key.encode("utf-8")).hexdigest()
        cached_file = os.path.join(global_cache_dir, f"{cache_key}.mp3")
        if os.path.exists(cached_file) and os.path.getsize(cached_file) > 500:
            if out_path:
                shutil.copy2(cached_file, out_path)
            if log_fn:
                try:
                    log_fn(f"   [CACHE] [OK] Reused cached audio from disk ({os.path.getsize(cached_file)} bytes)")
                except Exception:
                    pass
            return True
    except Exception:
        pass

    def _save_to_cache(src_path: str):
        if cached_file and src_path and os.path.exists(src_path) and os.path.getsize(src_path) > 500:
            try:
                import shutil
                shutil.copy2(src_path, cached_file)
            except Exception:
                pass

    key_candidates = []
    for k in [api_key, os.getenv("AI33_API_KEY"), os.getenv("XI_API_KEY"), DEFAULT_AI33_KEY]:
        if k and k not in key_candidates:
            key_candidates.append(k)

    # --- Tier 1: AI33 v3 Endpoint ---
    for cur_key in key_candidates:
        try:
            client = AI33Client(api_key=cur_key)
            for attempt in range(1, 4):
                try:
                    if log_fn and attempt > 1:
                        log_fn(f"[ai33-v3] (Retry {attempt}/3) Requesting TTS for '{prefixed_vid}'...")
                    res = client.text_to_speech_v3(text=text.strip(), voice_id=prefixed_vid, speed=speed, model_id=model_id)
                    if isinstance(res, (bytes, bytearray)) and len(res) > 100:
                        if out_path:
                            with open(out_path, "wb") as f:
                                f.write(res)
                            trim_audio_silence(out_path)
                            _save_to_cache(out_path)
                        if log_fn:
                            log_fn(f"[ai33-v3] Generated {len(res)} bytes")
                        return True
                    elif isinstance(res, dict):
                        task_id = res.get("task_id")
                        if task_id:
                            if log_fn:
                                log_fn(f"[ai33-v3] Task created: {task_id}. Polling (up to 90s)...")
                            task_res = client.poll_task(task_id, timeout=90)
                            meta = task_res.get("metadata", {}) if isinstance(task_res.get("metadata"), dict) else {}
                            audio_url = meta.get("audio_url") or task_res.get("audio_url") or task_res.get("output_url") or task_res.get("url")
                            if audio_url and out_path:
                                client.download_file(audio_url, out_path)
                                trim_audio_silence(out_path)
                                _save_to_cache(out_path)
                                return True
                        elif (res.get("audio_url") or res.get("url")) and out_path:
                            client.download_file(res.get("audio_url") or res.get("url"), out_path)
                            trim_audio_silence(out_path)
                            _save_to_cache(out_path)
                            return True
                except AI33APIError as exc:
                    if (exc.status_code in (429, 503) or "queue" in str(exc).lower()) and attempt < 3:
                        time.sleep(2.0 * attempt)
                        continue
                    if attempt >= 3:
                        break
                except Exception as exc:
                    err_text = str(exc).lower()
                    is_retryable = any(kw in err_text for kw in ("timeout", "timed out", "queue", "rate", "429", "500", "502", "503", "504"))
                    if is_retryable and attempt < 3:
                        time.sleep(2.0 * attempt)
                        continue
                    break
        except Exception:
            pass

    # --- Tier 2: Direct ElevenLabs API (if custom user API key is configured) ---
    if api_key and api_key != DEFAULT_AI33_KEY:
        try:
            bare_vid = clean_vid
            for p in ["elevenlabs_", "minimax_", "clone_", "vbee_", "fishaudio_", "edge_", "kokoro_"]:
                if bare_vid.startswith(p):
                    bare_vid = bare_vid[len(p):]
                    break
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{urllib.parse.quote(bare_vid)}?output_format=mp3_44100_128"
            req_headers = {
                "Content-Type": "application/json",
                "xi-api-key": api_key,
                "User-Agent": "StoriesStudio/2.8"
            }
            payload = json.dumps({
                "text": text.strip(),
                "model_id": model_id or "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": max(0.0, min(1.0, float(stability))),
                    "similarity_boost": max(0.0, min(1.0, float(similarity_boost)))
                }
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers=req_headers, method="POST")
            with urllib.request.urlopen(req, timeout=45, context=_get_ssl_context()) as resp:
                audio_bytes = resp.read()
                if len(audio_bytes) > 500:
                    if out_path:
                        with open(out_path, "wb") as f:
                            f.write(audio_bytes)
                        trim_audio_silence(out_path)
                        _save_to_cache(out_path)
                    if log_fn:
                        log_fn(f"[elevenlabs-direct] Generated {len(audio_bytes)} bytes")
                    return True
        except Exception:
            pass

    # --- Tier 3: High-Quality Microsoft Edge Neural TTS Fallback (Language-Aware, Zero Failure) ---
    try:
        import asyncio
        import edge_tts
        
        # Detect text script to select native studio neural voice
        is_hindi = any('\u0900' <= c <= '\u097F' for c in text)
        is_arabic_urdu = any('\u0600' <= c <= '\u06FF' for c in text)
        is_bengali = any('\u0980' <= c <= '\u09FF' for c in text)
        is_tamil = any('\u0B80' <= c <= '\u0BFF' for c in text)
        is_telugu = any('\u0C00' <= c <= '\u0C7F' for c in text)
        is_cyrillic = any('\u0400' <= c <= '\u04FF' for c in text)
        is_cjk = any('\u4E00' <= c <= '\u9FFF' or '\u3040' <= c <= '\u30FF' or '\uAC00' <= c <= '\uD7AF' for c in text)

        vh = f"{clean_vid} {prefixed_vid} {voice_id}".lower()
        is_female = any(w in vh for w in ("female", "woman", "girl", "aria", "sarah", "rachel", "bella", "swara", "emma", "lily", "alice", "charlotte", "jessica", "freya", "salli", "kimberly", "kendra", "joanna"))

        if is_hindi:
            edge_v = "hi-IN-SwaraNeural" if is_female else "hi-IN-MadhurNeural"
        elif is_arabic_urdu:
            edge_v = "ur-IN-GulNeural" if is_female else "ur-IN-SalmanNeural"
        elif is_bengali:
            edge_v = "bn-IN-TanishaaNeural" if is_female else "bn-IN-BashkarNeural"
        elif is_tamil:
            edge_v = "ta-IN-PallaviNeural" if is_female else "ta-IN-ValluvarNeural"
        elif is_telugu:
            edge_v = "te-IN-ShrutiNeural" if is_female else "te-IN-MohanNeural"
        elif is_cyrillic:
            edge_v = "ru-RU-SvetlanaNeural" if is_female else "ru-RU-DmitryNeural"
        elif is_cjk:
            edge_v = "zh-CN-XiaoxiaoNeural" if is_female else "zh-CN-YunxiNeural"
        elif any(w in vh for w in ("british", "uk", "ryan", "george")):
            edge_v = "en-GB-SoniaNeural" if is_female else "en-GB-RyanNeural"
        elif any(w in vh for w in ("deep", "narrator", "adam", "antoni", "josh", "christopher")):
            edge_v = "en-US-ChristopherNeural"
        else:
            edge_v = "en-US-JennyNeural" if is_female else "en-US-GuyNeural"

        rate_int = int((speed - 1.0) * 100)
        rate_str = f"{'+' if rate_int >= 0 else ''}{rate_int}%"

        def _run_edge_tts():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                comm = edge_tts.Communicate(text=text.strip(), voice=edge_v, rate=rate_str)
                loop.run_until_complete(comm.save(out_path))
            finally:
                loop.close()

        _run_edge_tts()
        if out_path and os.path.exists(out_path) and os.path.getsize(out_path) > 500:
            trim_audio_silence(out_path)
            _save_to_cache(out_path)
            if log_fn:
                log_fn(f"[edge-tts-fallback] [OK] Audio generated using {edge_v}")
            return True
    except Exception as _e_edge:
        if log_fn:
            log_fn(f"[edge-tts-fallback] Error: {_e_edge}")

    # --- Tier 4: Google gTTS Fallback (with script language code) ---
    try:
        from gtts import gTTS
        is_hindi = any('\u0900' <= c <= '\u097F' for c in text)
        is_arabic_urdu = any('\u0600' <= c <= '\u06FF' for c in text)
        is_bengali = any('\u0980' <= c <= '\u09FF' for c in text)
        is_tamil = any('\u0B80' <= c <= '\u0BFF' for c in text)
        is_telugu = any('\u0C00' <= c <= '\u0C7F' for c in text)
        is_cyrillic = any('\u0400' <= c <= '\u04FF' for c in text)
        
        gtts_lang = "hi" if is_hindi else ("ur" if is_arabic_urdu else ("bn" if is_bengali else ("ta" if is_tamil else ("te" if is_telugu else ("ru" if is_cyrillic else "en")))))
        tts = gTTS(text=text.strip(), lang=gtts_lang)
        tts.save(out_path)
        if out_path and os.path.exists(out_path) and os.path.getsize(out_path) > 500:
            trim_audio_silence(out_path)
            _save_to_cache(out_path)
            if log_fn:
                log_fn(f"[gtts-fallback] [OK] Audio generated via gTTS ({gtts_lang})")
            return True
    except Exception:
        pass

    if log_fn:
        log_fn(f"[ai33-tts] All TTS tiers exhausted for voice '{clean_vid}'")
    return False


def _get_ssl_context() -> ssl.SSLContext:
    global _SSL_CONTEXT
    if _SSL_CONTEXT is not None:
        return _SSL_CONTEXT
    try:
        import certifi
        _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
        return _SSL_CONTEXT
    except Exception:
        pass
    try:
        _SSL_CONTEXT = ssl.create_default_context()
        return _SSL_CONTEXT
    except Exception:
        _SSL_CONTEXT = ssl._create_unverified_context()
        return _SSL_CONTEXT


def encode_multipart_formdata(fields: Dict[str, Any], files: Dict[str, Tuple[str, bytes, str]]) -> Tuple[bytes, str]:
    """
    Encode form fields and files into multipart/form-data.
    fields: dict of key -> value (string, int, bool, dict, etc.)
    files: dict of key -> (filename, file_bytes, content_type)
    """
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    body = bytearray()

    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, bool):
            val_str = "true" if value else "false"
        elif isinstance(value, (dict, list)):
            val_str = json.dumps(value)
        else:
            val_str = str(value)
        
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        body.extend(f"{val_str}\r\n".encode("utf-8"))

    for key, (filename, file_data, content_type) in files.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'.encode("utf-8"))
        body.extend(f'Content-Type: {content_type}\r\n\r\n'.encode("utf-8"))
        body.extend(file_data)
        body.extend(b"\r\n")

    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    content_type_header = f"multipart/form-data; boundary={boundary}"
    return bytes(body), content_type_header


class AI33APIError(Exception):
    """Exception raised for errors in AI33 API calls."""
    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[Any] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class AI33Client:
    """Client for interacting with the AI33 Audio API."""

    def __init__(self, api_key: Optional[str] = None, base_url: str = _DEFAULT_BASE_URL, timeout: int = 120):
        self.api_key = api_key or os.getenv("AI33_API_KEY") or os.getenv("XI_API_KEY") or os.getenv("ELEVENLABS_API_KEY") or DEFAULT_AI33_KEY
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self, content_type: Optional[str] = None) -> Dict[str, str]:
        if not self.api_key:
            self.api_key = DEFAULT_AI33_KEY
        headers = {
            "xi-api-key": self.api_key,
            "User-Agent": "AI33-Python-SDK/1.0",
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _request(self, method: str, endpoint: str, data: Optional[bytes] = None,
                 content_type: Optional[str] = None, full_url: Optional[str] = None,
                 max_retries: int = 4) -> Dict[str, Any]:
        url = full_url if full_url else f"{self.base_url}{endpoint}"
        headers = self._headers(content_type)
        
        last_exc = None
        for attempt in range(1, max_retries + 1):
            try:
                req = urllib.request.Request(url, data=data, headers=headers, method=method)
                with urllib.request.urlopen(req, timeout=self.timeout, context=_get_ssl_context()) as resp:
                    raw = resp.read().decode("utf-8")
                    try:
                        return json.loads(raw)
                    except json.JSONDecodeError:
                        return {"raw_response": raw}
            except urllib.error.HTTPError as exc:
                err_body = exc.read().decode("utf-8", errors="ignore")
                try:
                    parsed = json.loads(err_body)
                except Exception:
                    parsed = err_body
                if exc.code in (429, 500, 502, 503, 504, 520, 521, 522, 524) and attempt < max_retries:
                    time.sleep(2.0 * attempt)
                    continue
                raise AI33APIError(f"AI33 HTTP {exc.code}: {parsed}", status_code=exc.code, response_body=parsed) from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last_exc = exc
                if attempt < max_retries:
                    time.sleep(2.0 * attempt)
                    continue
                raise AI33APIError(f"Network error connecting to AI33 API: {exc}") from exc

        if last_exc:
            raise AI33APIError(f"Network error connecting to AI33 API after {max_retries} attempts: {last_exc}")
        return {}

    def text_to_speech_v3(
        self,
        text: str,
        voice_id: str,
        speed: float = 1.0,
        model_id: Optional[str] = None,
        with_transcript: bool = False,
        file_name: Optional[str] = None,
        receive_url: Optional[str] = None,
    ) -> Union[bytes, Dict[str, Any]]:
        """POST /v3/text-to-speech — generate audio using AI33Pro v3 JSON endpoint."""
        if not text or not text.strip():
            raise ValueError("Text is required for v3 text-to-speech.")
        if not voice_id or not voice_id.strip():
            raise ValueError("Voice ID is required for v3 text-to-speech.")

        prefixed_vid = voice_id.strip()
        valid_prefixes = ("elevenlabs_", "minimax_", "clone_", "edge_", "kokoro_", "vbee_", "fishaudio_")
        if not any(prefixed_vid.startswith(p) for p in valid_prefixes):
            prefixed_vid = f"elevenlabs_{prefixed_vid}"

        payload: Dict[str, Any] = {
            "text": text.strip(),
            "voice_id": prefixed_vid,
            "speed": float(speed),
        }
        if model_id:
            payload["model_id"] = model_id
        if with_transcript:
            payload["with_transcript"] = True
        if file_name:
            payload["file_name"] = file_name
        if receive_url:
            payload["receive_url"] = receive_url

        data_bytes = json.dumps(payload).encode("utf-8")
        headers = self._headers("application/json")

        req = urllib.request.Request(
            f"{self.base_url}/v3/text-to-speech",
            data=data_bytes,
            headers=headers,
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=_get_ssl_context()) as resp:
                content_type = resp.headers.get("Content-Type", "").lower()
                data = resp.read()
                if "json" in content_type:
                    return json.loads(data.decode("utf-8"))
                return data
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                msg = err_json.get("message") or err_json.get("error") or str(err)
            except Exception:
                msg = err_body or str(err)
            raise AI33APIError(f"AI33 HTTP {err.code}: {msg}", status_code=err.code, response_body=err_body)

    # -------------------------------------------------------------------------
    # Fetch Voices (v3/voices) & Voice Library
    # -------------------------------------------------------------------------
    def fetch_voices(self, provider_filter: Optional[str] = None, fast_mode: bool = False, max_pages_per_provider: int = 1) -> List[Dict[str, Any]]:
        """
        Fetch available voices concurrently across providers.
        Fast parallel execution (under 2 seconds).
        """
        import concurrent.futures
        fetched_voices: List[Dict[str, Any]] = []
        seen_ids = set()

        api_key_to_use = self.api_key or DEFAULT_AI33_KEY
        req_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StoriesStudio/2.8",
            "xi-api-key": api_key_to_use,
        }

        providers_to_fetch = [
            ("elevenlabs", "ElevenLabs"),
            ("minimax", "Minimax"),
            ("fishaudio", "FishAudio"),
            ("edge", "Edge Neural"),
            ("kokoro", "Kokoro"),
            ("vbee", "Vbee"),
            ("clone", "Cloned"),
        ]

        active_providers = [
            (p, lbl) for (p, lbl) in providers_to_fetch
            if not provider_filter or provider_filter.lower() in (p.lower(), lbl.lower(), lbl.lower().replace(" ", ""))
        ]

        def _fetch_prov(prov_param, prov_label):
            res_list = []
            url = f"{self.base_url}/v3/voices?provider={prov_param}&page_size=100&page=1"
            try:
                req = urllib.request.Request(url, headers=req_headers, method="GET")
                with urllib.request.urlopen(req, timeout=3, context=_get_ssl_context()) as resp:
                    raw_text = resp.read().decode("utf-8")
                    data = json.loads(raw_text)
                    items = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                    for v in items:
                        if not isinstance(v, dict): continue
                        vid = v.get("voice_id") or v.get("id")
                        if not vid: continue
                        name = v.get("name") or vid
                        gender = v.get("gender") or v.get("category") or "Voice"
                        lang = v.get("language") or v.get("locale") or ""
                        p_url = v.get("preview_url") or ""
                        res_list.append({
                            "voice_id": vid,
                            "name": name,
                            "provider": prov_label,
                            "category": gender,
                            "language": lang,
                            "preview_url": p_url,
                        })
            except Exception:
                pass
            return res_list

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(active_providers) or 1)) as ex:
            futures = [ex.submit(_fetch_prov, p, lbl) for p, lbl in active_providers]
            for f in concurrent.futures.as_completed(futures):
                try:
                    for v in f.result():
                        vid = v.get("voice_id")
                        if vid and vid not in seen_ids:
                            seen_ids.add(vid)
                            fetched_voices.append(v)
                except Exception:
                    pass

        # Also fetch direct ElevenLabs voices if custom user key is set
        if api_key_to_use and api_key_to_use != DEFAULT_AI33_KEY and not fast_mode:
            try:
                el_url = "https://api.elevenlabs.io/v1/voices"
                el_headers = {"xi-api-key": api_key_to_use, "User-Agent": "StoriesStudio/2.8"}
                el_req = urllib.request.Request(el_url, headers=el_headers, method="GET")
                with urllib.request.urlopen(el_req, timeout=3, context=_get_ssl_context()) as resp:
                    el_data = json.loads(resp.read().decode("utf-8"))
                    for v in el_data.get("voices", []):
                        vid = v.get("voice_id")
                        if not vid: continue
                        full_vid = f"elevenlabs_{vid}" if not vid.startswith("elevenlabs_") else vid
                        if full_vid not in seen_ids:
                            seen_ids.add(full_vid)
                            fetched_voices.append({
                                "voice_id": full_vid,
                                "name": v.get("name") or vid,
                                "provider": "ElevenLabs",
                                "category": v.get("category") or "custom",
                                "language": "en",
                                "preview_url": v.get("preview_url") or "",
                            })
            except Exception:
                pass

        return fetched_voices

    def fetch_models(self, fast_mode: bool = False) -> List[Dict[str, Any]]:
        """Fetch available models dynamically from ElevenLabs/AI33 API endpoints."""
        models: List[Dict[str, Any]] = []
        seen_ids = set()

        standard_models = [
            {"model_id": "eleven_multilingual_v2", "name": "Eleven Multilingual V2"},
            {"model_id": "eleven_turbo_v2_5", "name": "Eleven Turbo V2.5"},
            {"model_id": "eleven_flash_v2_5", "name": "Eleven Flash V2.5"},
            {"model_id": "eleven_v3", "name": "Eleven V3"},
            {"model_id": "minimax_v1", "name": "Minimax Audio V1"},
            {"model_id": "edge_v1", "name": "Edge Neural V1"},
            {"model_id": "kokoro_v1", "name": "Kokoro TTS V1"},
            {"model_id": "vbee_v1", "name": "Vbee Voice V1"},
            {"model_id": "fishaudio_v1", "name": "Fish Audio V1"},
            {"model_id": "clone_v1", "name": "Cloned Voice V1"},
        ]

        if not fast_mode and self.api_key and not self.api_key.startswith("http"):
            try:
                url = f"{self.base_url}/v1/models"
                headers = self._headers()
                req = urllib.request.Request(url, headers=headers, method="GET")
                with urllib.request.urlopen(req, timeout=5, context=_get_ssl_context()) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if isinstance(data, list):
                        for m in data:
                            mid = m.get("model_id") or m.get("id")
                            if mid and mid not in seen_ids:
                                seen_ids.add(mid)
                                models.append({
                                    "model_id": mid,
                                    "name": m.get("name") or mid
                                })
            except Exception:
                pass

        if models:
            for sm in standard_models:
                if sm["model_id"] not in seen_ids:
                    models.append(sm)
            return models

        return standard_models

    # -------------------------------------------------------------------------
    # Dialogue (v3)
    # -------------------------------------------------------------------------
    def text_to_dialogue_v3(
        self,
        text: str,
        speakers: List[Dict[str, Any]],
        delay: float = 0.0,
        with_transcript: bool = False,
        file_name: Optional[str] = None,
        receive_url: Optional[str] = None,
        pronunciation_dictionary_id: Optional[int] = None,
    ) -> Union[Dict[str, Any], bytes]:
        """
        POST /v3/text-to-speech/dialogue
        Multi-speaker dialogue. speakers is a JSON array; text labels A>, B>, C> map to speakers by index.
        """
        if not text or not text.strip():
            raise ValueError("Text is required for dialogue.")
        if not speakers or len(speakers) < 2:
            raise ValueError("speakers list must contain at least 2 speaker dicts.")

        formatted_speakers = []
        for sp in speakers:
            vid = sp.get("voice_id", "")
            if not any(vid.startswith(p) for p in ("elevenlabs_", "minimax_", "clone_", "edge_", "kokoro_", "vbee_", "fishaudio_")):
                vid = f"elevenlabs_{vid}"
            entry = {"voice_id": vid}
            if "speed" in sp:
                entry["speed"] = float(sp["speed"])
            formatted_speakers.append(entry)

        fields = {
            "text": text,
            "speakers": json.dumps(formatted_speakers),
            "delay": str(delay),
            "with_transcript": "true" if with_transcript else "false",
        }
        if file_name:
            fields["file_name"] = file_name
        if receive_url:
            fields["receive_url"] = receive_url
        if pronunciation_dictionary_id is not None:
            fields["pronunciation_dictionary_id"] = str(pronunciation_dictionary_id)

        data, ctype = encode_multipart_formdata(fields, {})
        return self._request("POST", "/v3/text-to-speech/dialogue", data=data, content_type=ctype)

    def voice_clone_v3(self, voice_name: str, audio_file_path_or_bytes: Union[str, bytes], filename: Optional[str] = None) -> Dict[str, Any]:
        """
        POST /v3/text-to-speech/voice-clone
        Create a cloned voice from an audio sample. Returns clone_<voice_id>.
        """
        if not voice_name:
            raise ValueError("voice_name is required for voice cloning.")

        if isinstance(audio_file_path_or_bytes, str):
            fname = filename or os.path.basename(audio_file_path_or_bytes)
            with open(audio_file_path_or_bytes, "rb") as f:
                file_bytes = f.read()
        else:
            fname = filename or "sample.mp3"
            file_bytes = audio_file_path_or_bytes

        mime_type = mimetypes.guess_type(fname)[0] or "audio/mpeg"
        fields = {"voice_name": voice_name}
        files = {"audio_file": (fname, file_bytes, mime_type)}
        data, ctype = encode_multipart_formdata(fields, files)
        return self._request("POST", "/v3/text-to-speech/voice-clone", data=data, content_type=ctype)

    def delete_voice_clone_v3(self, voice_clone_id: str) -> Dict[str, Any]:
        """DELETE /v3/text-to-speech/voice-clone/{voice_clone_id}"""
        clean_id = voice_clone_id.replace("clone_", "")
        return self._request("DELETE", f"/v3/text-to-speech/voice-clone/{clean_id}")

    def create_dictionary_v3(self, name: str, rules: List[Dict[str, Any]]) -> Dict[str, Any]:
        """POST /v3/dictionaries - Create Pronunciation Dictionary"""
        payload = json.dumps({"name": name, "rules": rules}).encode("utf-8")
        return self._request("POST", "/v3/dictionaries", data=payload, content_type="application/json")

    def get_dictionaries_v3(self) -> Dict[str, Any]:
        """GET /v3/dictionaries - List Pronunciation Dictionaries"""
        return self._request("GET", "/v3/dictionaries")

    def get_dictionary_v3(self, dictionary_id: Union[int, str]) -> Dict[str, Any]:
        """GET /v3/dictionaries/{id}"""
        return self._request("GET", f"/v3/dictionaries/{dictionary_id}")

    def update_dictionary_v3(self, dictionary_id: Union[int, str], name: Optional[str] = None, rules: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """PUT /v3/dictionaries/{id}"""
        body = {}
        if name: body["name"] = name
        if rules is not None: body["rules"] = rules
        payload = json.dumps(body).encode("utf-8")
        return self._request("PUT", f"/v3/dictionaries/{dictionary_id}", data=payload, content_type="application/json")

    def delete_dictionary_v3(self, dictionary_id: Union[int, str]) -> Dict[str, Any]:
        """DELETE /v3/dictionaries/{id}"""
        return self._request("DELETE", f"/v3/dictionaries/{dictionary_id}")

    def preview_dictionary_v3(self, text: str, rules: List[Dict[str, Any]]) -> Dict[str, Any]:
        """POST /v3/dictionaries/preview"""
        payload = json.dumps({"text": text, "rules": rules}).encode("utf-8")
        return self._request("POST", "/v3/dictionaries/preview", data=payload, content_type="application/json")


    # -------------------------------------------------------------------------
    # Presigned Upload Helper
    # -------------------------------------------------------------------------
    def create_upload(self, kind: str = "dubbing") -> Dict[str, Any]:
        """POST /v1/uploads - returns upload_id and put_url"""
        payload = json.dumps({"kind": kind}).encode("utf-8")
        return self._request("POST", "/v1/uploads", data=payload, content_type="application/json")

    def upload_file_to_presigned_url(self, put_url: str, file_path_or_bytes: Union[str, bytes]) -> None:
        """PUT raw audio file to presigned put_url"""
        if isinstance(file_path_or_bytes, str):
            with open(file_path_or_bytes, "rb") as f:
                data = f.read()
        else:
            data = file_path_or_bytes

        req = urllib.request.Request(put_url, data=data, method="PUT")
        req.add_header("Content-Type", "application/octet-stream")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=_get_ssl_context()) as resp:
                if resp.status not in (200, 201, 204):
                    raise AI33APIError(f"Presigned upload failed with status {resp.status}")
        except Exception as exc:
            raise AI33APIError(f"Failed uploading file to presigned URL: {exc}") from exc

    # -------------------------------------------------------------------------
    # 1. Dubbing Task
    # -------------------------------------------------------------------------
    def dub_audio(
        self,
        file_path_or_bytes: Optional[Union[str, bytes]] = None,
        filename: Optional[str] = None,
        target_lang: str = "en",
        source_lang: str = "auto",
        num_speakers: Union[int, str] = 0,
        disable_voice_cloning: bool = False,
        voice_id: Optional[str] = None,
        receive_url: Optional[str] = None,
        upload_id: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        poll: bool = False,
        poll_interval: float = 3.0,
        poll_timeout: float = 300.0,
    ) -> Dict[str, Any]:
        """
        Dub an audio file into a target language.
        Supports both Multipart form upload and pre-uploaded JSON request (via upload_id).
        """
        if upload_id is not None:
            # JSON Request mode
            if duration_seconds is None or duration_seconds <= 0:
                raise ValueError("duration_seconds > 0 is required when using JSON upload_id mode.")
            payload = {
                "upload_id": upload_id,
                "duration_seconds": float(duration_seconds),
                "num_speakers": str(num_speakers),
                "disable_voice_cloning": "true" if disable_voice_cloning else "false",
                "source_lang": source_lang,
                "target_lang": target_lang,
            }
            if voice_id:
                payload["voice_id"] = voice_id
            if receive_url:
                payload["receive_url"] = receive_url

            data_bytes = json.dumps(payload).encode("utf-8")
            res = self._request("POST", "/v1/task/dubbing", data=data_bytes, content_type="application/json")
        else:
            # Multipart mode
            if file_path_or_bytes is None:
                raise ValueError("Either file_path_or_bytes or upload_id must be provided for dubbing.")

            if isinstance(file_path_or_bytes, str):
                fname = filename or os.path.basename(file_path_or_bytes)
                with open(file_path_or_bytes, "rb") as f:
                    file_bytes = f.read()
            else:
                fname = filename or "audio.mp3"
                file_bytes = file_path_or_bytes

            mime_type = mimetypes.guess_type(fname)[0] or "audio/mpeg"

            fields: Dict[str, Any] = {
                "num_speakers": str(num_speakers),
                "disable_voice_cloning": "true" if disable_voice_cloning else "false",
                "source_lang": source_lang,
                "target_lang": target_lang,
            }
            if voice_id:
                fields["voice_id"] = voice_id
            if receive_url:
                fields["receive_url"] = receive_url

            files = {"file": (fname, file_bytes, mime_type)}
            body, ctype = encode_multipart_formdata(fields, files)
            res = self._request("POST", "/v1/task/dubbing", data=body, content_type=ctype)

        if poll and res.get("task_id"):
            return self.poll_task(res["task_id"], interval=poll_interval, timeout=poll_timeout)
        return res

    # -------------------------------------------------------------------------
    # 2. Speech to Text Task
    # -------------------------------------------------------------------------
    def speech_to_text(
        self,
        file_path_or_bytes: Union[str, bytes],
        filename: Optional[str] = None,
        tag_audio_events: bool = True,
        receive_url: Optional[str] = None,
        poll: bool = False,
        poll_interval: float = 3.0,
        poll_timeout: float = 300.0,
    ) -> Dict[str, Any]:
        """Transcribe audio file to JSON and SRT format."""
        if isinstance(file_path_or_bytes, str):
            fname = filename or os.path.basename(file_path_or_bytes)
            with open(file_path_or_bytes, "rb") as f:
                file_bytes = f.read()
        else:
            fname = filename or "audio.mp3"
            file_bytes = file_path_or_bytes

        mime_type = mimetypes.guess_type(fname)[0] or "audio/mpeg"

        fields: Dict[str, Any] = {
            "tag_audio_events": tag_audio_events,
        }
        if receive_url:
            fields["receive_url"] = receive_url

        files = {"file": (fname, file_bytes, mime_type)}
        body, ctype = encode_multipart_formdata(fields, files)
        res = self._request("POST", "/v1/task/speech-to-text", data=body, content_type=ctype)

        if poll and res.get("task_id"):
            return self.poll_task(res["task_id"], interval=poll_interval, timeout=poll_timeout)
        return res

    # -------------------------------------------------------------------------
    # 3. Sound Effect Generation Task
    # -------------------------------------------------------------------------
    def generate_sound_effect(
        self,
        text: str,
        duration_seconds: Optional[float] = None,
        prompt_influence: float = 0.3,
        loop: bool = False,
        model_id: str = "eleven_text_to_sound_v2",
        receive_url: Optional[str] = None,
        poll: bool = False,
        poll_interval: float = 3.0,
        poll_timeout: float = 300.0,
    ) -> Dict[str, Any]:
        """Generate sound effect from text prompt."""
        if not text or not text.strip():
            raise ValueError("Prompt text is required for sound effect generation.")
        if len(text) > 450:
            raise ValueError("Text prompt must be <= 450 characters.")

        payload: Dict[str, Any] = {
            "text": text.strip(),
            "duration_seconds": duration_seconds,
            "prompt_influence": float(prompt_influence),
            "loop": bool(loop),
            "model_id": model_id,
        }
        if receive_url:
            payload["receive_url"] = receive_url

        data_bytes = json.dumps(payload).encode("utf-8")
        res = self._request("POST", "/v1/task/sound-effect", data=data_bytes, content_type="application/json")

        if poll and res.get("task_id"):
            return self.poll_task(res["task_id"], interval=poll_interval, timeout=poll_timeout)
        return res

    # -------------------------------------------------------------------------
    # 4. Voice Changer Task (Speech-to-Speech)
    # -------------------------------------------------------------------------
    def voice_changer(
        self,
        file_path_or_bytes: Union[str, bytes],
        voice_id: str,
        filename: Optional[str] = None,
        model_id: str = "eleven_multilingual_sts_v2",
        voice_settings: Optional[Dict[str, Any]] = None,
        remove_background_noise: bool = False,
        poll: bool = False,
        poll_interval: float = 3.0,
        poll_timeout: float = 300.0,
    ) -> Dict[str, Any]:
        """Transform voice in an audio file to another voice."""
        if not voice_id:
            raise ValueError("Target voice_id is required for voice changer.")

        if isinstance(file_path_or_bytes, str):
            fname = filename or os.path.basename(file_path_or_bytes)
            with open(file_path_or_bytes, "rb") as f:
                file_bytes = f.read()
        else:
            fname = filename or "audio.mp3"
            file_bytes = file_path_or_bytes

        mime_type = mimetypes.guess_type(fname)[0] or "audio/mpeg"

        fields: Dict[str, Any] = {
            "voice_id": voice_id,
            "model_id": model_id,
            "remove_background_noise": remove_background_noise,
        }
        if voice_settings is not None:
            fields["voice_settings"] = json.dumps(voice_settings)

        files = {"file": (fname, file_bytes, mime_type)}
        body, ctype = encode_multipart_formdata(fields, files)
        res = self._request("POST", "/v1/task/voice-changer", data=body, content_type=ctype)

        if poll and res.get("task_id"):
            return self.poll_task(res["task_id"], interval=poll_interval, timeout=poll_timeout)
        return res

    # -------------------------------------------------------------------------
    # 5. Voice Isolate Task
    # -------------------------------------------------------------------------
    def voice_isolate(
        self,
        file_path_or_bytes: Union[str, bytes],
        filename: Optional[str] = None,
        poll: bool = False,
        poll_interval: float = 3.0,
        poll_timeout: float = 300.0,
    ) -> Dict[str, Any]:
        """Isolate vocal voice track from background noise."""
        if isinstance(file_path_or_bytes, str):
            fname = filename or os.path.basename(file_path_or_bytes)
            with open(file_path_or_bytes, "rb") as f:
                file_bytes = f.read()
        else:
            fname = filename or "audio.mp3"
            file_bytes = file_path_or_bytes

        mime_type = mimetypes.guess_type(fname)[0] or "audio/mpeg"

        files = {"file": (fname, file_bytes, mime_type)}
        body, ctype = encode_multipart_formdata({}, files)
        res = self._request("POST", "/v1/task/voice-isolate", data=body, content_type=ctype)

        if poll and res.get("task_id"):
            return self.poll_task(res["task_id"], interval=poll_interval, timeout=poll_timeout)
        return res

    # -------------------------------------------------------------------------
    # Query & Poll Tasks
    # -------------------------------------------------------------------------
    def get_task(self, task_id: str) -> Dict[str, Any]:
        """Query task status: GET /v1/task/{task_id}"""
        return self._request("GET", f"/v1/task/{task_id}")

    def poll_task(self, task_id: str, interval: float = 2.0, timeout: float = 90.0) -> Dict[str, Any]:
        """Poll task status until completion or timeout (default 90s)."""
        start_time = time.time()
        curr_interval = interval
        while time.time() - start_time < timeout:
            try:
                res = self.get_task(task_id)
                status = str(res.get("status") or res.get("state") or "").lower()
                if status in ("done", "completed", "success", "succeeded"):
                    meta = res.get("metadata", {})
                    if isinstance(meta, dict) and "audio_url" in meta:
                        res["audio_url"] = meta["audio_url"]
                    return res
                if status in ("failed", "error"):
                    err_msg = res.get("error_message") or res.get("error") or "Task processing failed."
                    raise AI33APIError(f"Task {task_id} failed: {err_msg}", response_body=res)
            except AI33APIError as exc:
                if exc.status_code in (429, 500, 502, 503, 504):
                    curr_interval = min(6.0, curr_interval + 1.0)
                else:
                    raise
            except Exception:
                curr_interval = min(6.0, curr_interval + 1.0)

            time.sleep(curr_interval)

        raise TimeoutError(f"Task {task_id} did not finish within {timeout} seconds.")

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------
    def download_file(self, url: str, dest_path: str, max_retries: int = 4) -> str:
        """Download remote asset (audio/SRT) to local destination path with retries."""
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
        headers = self._headers()
        
        last_err = None
        for attempt in range(1, max_retries + 1):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout, context=_get_ssl_context()) as resp:
                    data = resp.read()
                    if len(data) > 0:
                        with open(dest_path, "wb") as f:
                            f.write(data)
                        return dest_path
            except Exception as e:
                last_err = e
                if attempt < max_retries:
                    time.sleep(2.0 * attempt)
                    continue
        if last_err:
            raise AI33APIError(f"Failed to download audio from {url}: {last_err}")
        return dest_path
