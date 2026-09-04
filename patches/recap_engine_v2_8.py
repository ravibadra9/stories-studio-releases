#!/usr/bin/env python3
"""Recap Studio V2.8 build engine.

Purpose:
- Generate narration TTS from a user-provided rewritten script.
- Render an edit-plan JSON against a local source video.
- Support multiple short shots per narration beat for visual variety.
- Generate/loop ElevenLabs Music as optional BGM.
- Keep a persistent smart cache so reruns resume instead of rebuilding everything.

Editing effects are presentation tools only; they do not change the copyright/licensing
status of source footage.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import ssl
import subprocess
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

LogFn = Optional[Callable[[str], None]]


@dataclass
class Shot:
    source_start: float
    source_end: float
    mode: str = "clip"          # clip | freeze
    weight: float = 1.0          # relative share of narration duration
    zoom: float = 1.0            # backward-compatible static/final zoom
    zoom_from: float = 1.0       # dynamic motion start zoom
    zoom_to: float = 1.08        # dynamic motion end zoom
    motion: str = "none"         # none | push_in | pull_out | pan_left/right/up/down | *_push | handheld_soft
    overlay: str = "none"        # none | dust_subtle | light_specks | film_grain
    grain: float = 0.0           # 0.0-1.0 subtle texture strength
    flip: bool = False
    speed: float = 1.0           # source playback speed for clip
    anchor: str = "center"       # crop anchor
    look: str = "normal"         # normal | cinematic | dramatic | mono
    role: str = "story"          # story | character_intro | reveal | reaction | establishing | cta
    character: str = ""          # character name for intro/reveal metadata
    scene_key: str = ""          # semantic source-scene key used for repeat checks
    allow_repeat: bool = False   # explicit exception for intentional callbacks


@dataclass
class EditBeat:
    line_no: int
    text: str
    shots: List[Shot] = field(default_factory=list)


def _log(cb: LogFn, msg: str):
    if cb:
        cb(msg)
    else:
        print(msg)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_nonempty(path: str) -> bool:
    return bool(path and os.path.exists(path) and os.path.getsize(path) > 0)


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


def run(cmd: List[str]):
    if cmd and cmd[0] in ("ffmpeg", "ffprobe"):
        cmd = list(cmd)
        cmd[0] = find_binary(cmd[0])
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\n{result.stderr.decode(errors='ignore')}"
        )
    return result.stdout.decode(errors="ignore")


def run_with_progress(cmd: List[str], total_duration: float = 0.0, log_callback: Optional[Callable[[str], None]] = None,
                      step_name: str = "FFmpeg", check: bool = True):
    """Run FFmpeg command with real-time progress updates parsing FFmpeg time & frame metrics."""
    if cmd and cmd[0] in ("ffmpeg", "ffprobe"):
        cmd = list(cmd)
        cmd[0] = find_binary(cmd[0])

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        universal_newlines=True
    )

    last_pct = -1
    last_log_time = 0.0
    stderr_lines = []

    for line in iter(proc.stderr.readline, ''):
        stderr_lines.append(line)
        if log_callback and ("time=" in line or "frame=" in line):
            m_time = re.search(r"time=(\d+):(\d+):(\d+\.\d+|\d+)", line)
            m_frame = re.search(r"frame=\s*(\d+)", line)
            m_fps = re.search(r"fps=\s*([\d\.]+)", line)

            curr_sec = 0.0
            if m_time:
                h, m_, s = int(m_time.group(1)), int(m_time.group(2)), float(m_time.group(3))
                curr_sec = h * 3600 + m_ * 60 + s

            frame_str = f"Frame {m_frame.group(1)}" if m_frame else ""
            fps_str = f"{m_fps.group(1)} FPS" if m_fps else ""

            now = time.time()
            if total_duration > 0 and curr_sec > 0:
                pct = int(min(99.0, (curr_sec / total_duration) * 100))
                if (pct >= last_pct + 5 or now - last_log_time >= 3.0) and pct != last_pct:
                    last_pct = pct
                    last_log_time = now
                    details = " | ".join(filter(None, [frame_str, fps_str]))
                    detail_text = f" ({details})" if details else ""
                    log_callback(f"   [{step_name}] Progress: {pct}%{detail_text}")
            elif m_frame and now - last_log_time >= 3.0:
                last_log_time = now
                log_callback(f"   [{step_name}] {frame_str} | {fps_str}")

    proc.wait()
    full_stderr = "".join(stderr_lines)
    if check and proc.returncode != 0:
        cmd_str = " ".join(str(x) for x in cmd)
        raise RuntimeError(f"Command failed (code {proc.returncode}):\n{cmd_str}\n\nSTDERR:\n{full_stderr}")

    if log_callback and last_pct >= 0:
        log_callback(f"   [{step_name}] Progress: [OK] Complete")

    return full_stderr


def get_duration(path: str) -> float:
    ffprobe_bin = find_binary("ffprobe")
    out = run([
        ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path,
    ])
    return float(out.strip())


def check_ffmpeg() -> Dict[str, bool]:
    ff = find_binary("ffmpeg")
    fp = find_binary("ffprobe")
    return {
        "ffmpeg": bool(ff and (os.path.isfile(ff) or shutil.which(ff))),
        "ffprobe": bool(fp and (os.path.isfile(fp) or shutil.which(fp))),
    }


# ---------------------------------------------------------------------------
# ElevenLabs
# ---------------------------------------------------------------------------

_SAFE_SSL_CONTEXT: Optional[ssl.SSLContext] = None


def _get_ssl_context() -> ssl.SSLContext:
    global _SAFE_SSL_CONTEXT
    if _SAFE_SSL_CONTEXT is not None:
        return _SAFE_SSL_CONTEXT
    try:
        import certifi
        _SAFE_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
        return _SAFE_SSL_CONTEXT
    except Exception:
        pass
    try:
        _SAFE_SSL_CONTEXT = ssl.create_default_context()
        return _SAFE_SSL_CONTEXT
    except Exception:
        _SAFE_SSL_CONTEXT = ssl._create_unverified_context()
        return _SAFE_SSL_CONTEXT


def _request(url: str, api_key: str, method: str = "GET", payload=None, timeout: int = 120,
             retries: int = 4, log_callback: LogFn = None):
    """Network-resilient ElevenLabs request.

    Transient Windows socket timeouts (including WinError 10060), 408/429 and
    common 5xx responses are retried with backoff. The build cache remains
    untouched, so RUN / RESUME can continue after a real outage.
    """
    data = None
    headers = {
        "xi-api-key": api_key,
        "User-Agent": "RecapStudio/2.7",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    retryable_http = {408, 409, 425, 429, 500, 502, 503, 504}
    delays = [2, 4, 8, 12, 18]
    last_exc = None

    for attempt in range(max(1, retries + 1)):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_get_ssl_context()) as resp:
                body = resp.read()
                ctype = resp.headers.get("Content-Type", "")
                if "json" in ctype:
                    return json.loads(body.decode("utf-8"))
                return body
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            last_exc = exc
            if exc.code not in retryable_http or attempt >= retries:
                raise RuntimeError(f"ElevenLabs API error {exc.code}: {detail}") from exc
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                delay = max(float(retry_after), 1.0) if retry_after else delays[min(attempt, len(delays)-1)]
            except Exception:
                delay = delays[min(attempt, len(delays)-1)]
            _log(log_callback, f"[network] ElevenLabs HTTP {exc.code}; retry {attempt+1}/{retries} in {delay:.0f}s…")
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as exc:
            last_exc = exc
            if attempt >= retries:
                break
            delay = delays[min(attempt, len(delays)-1)]
            _log(log_callback, f"[network] ElevenLabs connection timeout/error; retry {attempt+1}/{retries} in {delay:.0f}s…")
            time.sleep(delay)

    raise RuntimeError(
        "ElevenLabs connection failed after automatic retries. "
        "This is usually a temporary network/VPN/firewall/DNS issue (for example WinError 10060). "
        "Your completed cache is safe — restore internet access and press RUN / RESUME. "
        f"Last error: {last_exc}"
    )


def fetch_elevenlabs_models(api_key: str) -> List[dict]:
    data = _request("https://api.elevenlabs.io/v1/models", api_key)
    if not isinstance(data, list):
        return []
    return [m for m in data if m.get("can_do_text_to_speech")]


def fetch_elevenlabs_voices(api_key: str, page_size: int = 100) -> List[dict]:
    voices: List[dict] = []
    token = None
    while True:
        params = {"page_size": str(page_size), "include_total_count": "false"}
        if token:
            params["next_page_token"] = token
        url = "https://api.elevenlabs.io/v2/voices?" + urllib.parse.urlencode(params)
        data = _request(url, api_key)
        voices.extend(data.get("voices", []))
        if not data.get("has_more"):
            break
        token = data.get("next_page_token")
        if not token:
            break
    return voices


def _try_elevenlabs_direct(text: str, voice_id: str, model_id: str, api_key: str, out_path: str,
                           stability: float = 0.5, similarity_boost: float = 0.75) -> bool:
    try:
        clean_vid = voice_id.replace("elevenlabs_", "")
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{clean_vid}?output_format=mp3_44100_128"
        payload = {
            "text": text,
            "model_id": model_id or "eleven_multilingual_v2",
            "voice_settings": {
                "stability": max(0.0, min(1.0, float(stability))),
                "similarity_boost": max(0.0, min(1.0, float(similarity_boost))),
            },
        }
        audio = _request(url, api_key, method="POST", payload=payload, timeout=120, retries=3)
        if isinstance(audio, (bytes, bytearray)) and len(audio) > 100:
            with open(out_path, "wb") as f:
                f.write(audio)
            return True
    except Exception:
        pass
    return False


def _try_spoken_fallback_tts(text: str, voice_id: str = "", out_path: str = "", log_callback: LogFn = None) -> bool:
    """Fallback TTS is disabled."""
    if log_callback:
        log_callback("[spoken-fallback] Fallback TTS is disabled.")
    return False


def generate_tts(text: str, voice_id: str, model_id: str, api_key: str, out_path: str,
                 stability: float = 0.5, similarity_boost: float = 0.75,
                 speed: float = 1.0, log_callback: LogFn = None):
    """Generate TTS audio with zero-failure multi-tier fallback (AI33 v3 -> default key -> ElevenLabs Direct -> Edge Neural)."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    voice_id_str = str(voice_id).strip()

    # Extract clean voice ID if a full display label was passed
    if "(" in voice_id_str and voice_id_str.endswith(")"):
        voice_id_str = voice_id_str[voice_id_str.rfind("(")+1 : -1].strip()
    elif "•" in voice_id_str:
        voice_id_str = voice_id_str.split("•")[-1].strip()

    prefixed_vid = voice_id_str
    if not any(prefixed_vid.startswith(p) for p in ["elevenlabs_", "minimax_", "clone_", "vbee_", "fishaudio_", "edge_", "kokoro_"]):
        prefixed_vid = f"elevenlabs_{prefixed_vid}"

    from ai33_api import ai33_tts_generate, DEFAULT_AI33_KEY

    # Use the robust zero-failure ai33_tts_generate engine
    ok = ai33_tts_generate(
        text=text,
        voice_id=prefixed_vid,
        api_key=api_key or DEFAULT_AI33_KEY,
        out_path=out_path,
        speed=speed,
        stability=stability,
        similarity_boost=similarity_boost,
        model_id=model_id or "eleven_multilingual_v2",
        log_fn=log_callback
    )

    if ok and os.path.exists(out_path) and os.path.getsize(out_path) > 100:
        return

    raise RuntimeError(f"TTS audio generation failed for voice '{prefixed_vid}' across all endpoints and fallbacks.")


def generate_music(prompt: str, duration_seconds: float, api_key: str, out_path: str,
                   model_id: str = "music_v2", force_instrumental: bool = True):
    duration_seconds = float(duration_seconds)
    if not 3 <= duration_seconds <= 600:
        raise ValueError("BGM duration must be between 3 and 600 seconds.")
    if not prompt.strip():
        raise ValueError("BGM prompt is empty.")
    payload = {
        "prompt": prompt.strip(),
        "music_length_ms": int(duration_seconds * 1000),
        "model_id": model_id,
        "force_instrumental": bool(force_instrumental),
    }
    audio = _request("https://api.elevenlabs.io/v1/music", api_key,
                     method="POST", payload=payload, timeout=900, retries=4)
    if not isinstance(audio, (bytes, bytearray)):
        raise RuntimeError("Unexpected ElevenLabs Music response.")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(audio)


# ---------------------------------------------------------------------------
# Script + edit-plan
# ---------------------------------------------------------------------------

def read_script_lines(script_path: str) -> List[str]:
    with open(script_path, "r", encoding="utf-8", errors="ignore") as f:
        raw_lines = [line.strip() for line in f if line.strip()]

    if not raw_lines:
        return []

    # Strip embedded JSON blocks or metadata if user saved narration script + JSON together in script.txt
    narrative_raw = []
    in_json = False
    for line in raw_lines:
        s = line.strip()
        if s.startswith("```"):
            in_json = not in_json
            continue
        if in_json:
            continue
        if s.startswith("{") or s.startswith("}") or s.startswith('"project":') or s.startswith('"segments":') or s.startswith('"beat":'):
            continue
        narrative_raw.append(line)

    if not narrative_raw:
        narrative_raw = raw_lines

    tag_regex = re.compile(r"^(?:\[\s*\d+\s*\]|\d+[\.\)]|(?:beat|line|segment|shot)\s*\d+[:\.]?|#\s*\d+)$", re.IGNORECASE)
    inline_tag_regex = re.compile(r"^(?:\[\s*\d+\s*\]|\d+[\.\)]\s+|(?:beat|line|segment|shot)\s*\d+\s*[:\.\-]\s*)\s*", re.IGNORECASE)

    has_standalone_headers = any(tag_regex.match(l) for l in narrative_raw)

    cleaned_lines: List[str] = []
    if has_standalone_headers:
        for line in narrative_raw:
            if tag_regex.match(line):
                continue
            cleaned_lines.append(line.strip())
    else:
        for line in narrative_raw:
            cleaned_lines.append(inline_tag_regex.sub("", line).strip())

    return [l for l in cleaned_lines if l]


def _normalize_mode(value: str) -> str:
    value = (value or "clip").lower().strip()
    aliases = {
        "video": "clip",
        "moving": "clip",
        "narration": "clip",
        "speech": "clip",
        "talk": "clip",
        "normal": "clip",
        "dialogue": "clip",
        "scene": "clip",
        "action": "clip",
        "cut": "clip",
        "freeze_zoom": "freeze",
        "freeze-frame": "freeze",
        "freeze_frame": "freeze",
        "still": "freeze",
        "image": "freeze",
        "picture": "freeze",
    }
    value = aliases.get(value, value)
    if value not in {"clip", "freeze"}:
        return "clip"
    return value


def _normalize_anchor(value: str) -> str:
    value = (value or "center").lower().strip()
    allowed = {
        "center", "left", "right", "top", "bottom",
        "top_left", "top_right", "bottom_left", "bottom_right",
    }
    return value if value in allowed else "center"


def _normalize_look(value: str) -> str:
    value = (value or "normal").lower().strip()
    return value if value in {"normal", "cinematic", "dramatic", "mono"} else "normal"


def _normalize_motion(value: str) -> str:
    value = (value or "none").lower().strip()
    aliases = {
        "zoom_in": "push_in",
        "zoom_out": "pull_out",
        "pan_right_push_in": "pan_right_push",
        "pan_left_push_in": "pan_left_push",
        "pan_and_zoom": "pan_right_push",
        "handheld": "handheld_soft",
    }
    value = aliases.get(value, value)
    allowed = {
        "none", "push_in", "pull_out", "pan_left", "pan_right",
        "pan_up", "pan_down", "pan_left_push", "pan_right_push",
        "handheld_soft",
    }
    return value if value in allowed else "none"


def _normalize_overlay(value: str) -> str:
    value = (value or "none").lower().strip()
    aliases = {
        "dust": "dust_subtle",
        "particles": "light_specks",
        "grain": "film_grain",
    }
    value = aliases.get(value, value)
    return value if value in {"none", "dust_subtle", "light_specks", "film_grain"} else "none"


def _parse_time_seconds(value) -> float:
    if value is None:
        raise ValueError("Timestamp value cannot be empty.")
    if isinstance(value, (int, float)):
        return float(value)
    val = str(value).strip().lower().replace(",", ".")
    for suffix in ["secs", "sec", "s"]:
        if val.endswith(suffix):
            val = val[:-len(suffix)].strip()
            break
    if not val:
        raise ValueError("Timestamp value cannot be empty.")
    if ":" in val:
        parts = [p.strip() for p in val.split(":")]
        if len(parts) == 2:
            return float(parts[0]) * 60.0 + float(parts[1])
        elif len(parts) == 3:
            return float(parts[0]) * 3600.0 + float(parts[1]) * 60.0 + float(parts[2])
        else:
            raise ValueError(f"Invalid timestamp format '{value}'. Expected HH:MM:SS or MM:SS or seconds.")
    return float(val)


def _extract_start_end(item: dict, parent_item: Optional[dict] = None, last_known_end: Optional[float] = None) -> tuple[float, float, bool]:
    """Returns (start, end, was_auto_filled)"""
    def _find_val(keys, d1, d2):
        for k in keys:
            if d1 and k in d1 and d1[k] not in (None, ""):
                return d1[k]
        if d2:
            for k in keys:
                if k in d2 and d2[k] not in (None, ""):
                    return d2[k]
        return None

    start_keys = ["source_start", "start", "start_time", "source_start_time", "from", "start_s", "source_in", "in"]
    end_keys = ["source_end", "end", "end_time", "source_end_time", "to", "end_s", "source_out", "out"]
    duration_keys = ["duration", "length", "clip_duration", "duration_seconds", "source_duration"]

    raw_start = _find_val(start_keys, item, parent_item)
    raw_end = _find_val(end_keys, item, parent_item)
    raw_dur = _find_val(duration_keys, item, parent_item)

    # If start is missing or explicitly null (common in ChatGPT outro/CTA lines)
    if raw_start is None:
        start = float(last_known_end if last_known_end is not None else 0.0)
        dur = _parse_time_seconds(raw_dur) if raw_dur is not None else 3.0
        end = start + max(0.5, dur)
        return start, end, True

    start = _parse_time_seconds(raw_start)

    if raw_end is not None:
        end = _parse_time_seconds(raw_end)
    elif raw_dur is not None:
        end = start + _parse_time_seconds(raw_dur)
    else:
        end = start + 3.0

    return start, end, False


def _shot_from_item(item: dict, parent_item: Optional[dict] = None, location_desc: str = "", last_known_end: Optional[float] = None) -> Shot:
    if not isinstance(item, dict):
        raise ValueError(f"{location_desc}: expected shot object, got {type(item).__name__}")
    
    try:
        start, end, auto_filled = _extract_start_end(item, parent_item, last_known_end)
    except Exception as e:
        prefix = f"{location_desc}: " if location_desc else ""
        raise ValueError(f"{prefix}{e}")

    if end <= start:
        prefix = f"{location_desc}: " if location_desc else ""
        raise ValueError(f"{prefix}source_end ({end}s) must be after source_start ({start}s).")

    def _safe_float(val, default):
        if val in (None, ""):
            return default
        try:
            return float(val)
        except Exception:
            return default

    allow_rep = bool(item.get("allow_repeat", False)) or auto_filled
    role = str(item.get("role", "cta" if auto_filled else "story") or "story").strip().lower()

    return Shot(
        source_start=start,
        source_end=end,
        mode=_normalize_mode(item.get("mode", item.get("type", "clip"))),
        weight=max(0.05, _safe_float(item.get("weight", item.get("share")), 1.0)),
        zoom=max(1.0, min(1.6, _safe_float(item.get("zoom", item.get("zoom_to")), 1.0))),
        zoom_from=max(1.0, min(1.6, _safe_float(item.get("zoom_from"), 1.0))),
        zoom_to=max(1.0, min(1.6, _safe_float(item.get("zoom_to", item.get("zoom")), 1.08))),
        motion=_normalize_motion(item.get("motion", "none")),
        overlay=_normalize_overlay(item.get("overlay", "none")),
        grain=max(0.0, min(1.0, _safe_float(item.get("grain"), 0.0))),
        flip=bool(item.get("flip", False)),
        speed=max(0.5, min(2.0, _safe_float(item.get("speed"), 1.0))),
        anchor=_normalize_anchor(item.get("anchor", "center")),
        look=_normalize_look(item.get("look", "normal")),
        role=role,
        character=str(item.get("character", "") or "").strip(),
        scene_key=str(item.get("scene_key", "") or "").strip(),
        allow_repeat=allow_rep,
    )


def load_json_robust(path: str) -> Any:
    """Robustly load JSON file, handling UTF-8 BOM, markdown code fences, or surrounding text."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        content = f.read().strip()

    if not content:
        raise ValueError(f"Selected file '{Path(path).name}' is empty (0 bytes). Make sure you selected a valid JSON Edit Plan file.")

    # Remove markdown code blocks ```json ... ```
    if "```" in content:
        lines = []
        in_code = False
        for line in content.splitlines():
            s = line.strip()
            if s.startswith("```"):
                in_code = not in_code
                continue
            lines.append(line)
        cleaned = "\n".join(lines).strip()
        if cleaned:
            content = cleaned

    # Try direct parse
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try searching for outer JSON braces { ... } or [ ... ]
    first_brace = content.find("{")
    first_bracket = content.find("[")

    start_idx = -1
    if first_brace != -1 and first_bracket != -1:
        start_idx = min(first_brace, first_bracket)
    elif first_brace != -1:
        start_idx = first_brace
    elif first_bracket != -1:
        start_idx = first_bracket

    if start_idx != -1:
        end_brace = content.rfind("}")
        end_bracket = content.rfind("]")
        end_idx = max(end_brace, end_bracket)

        if end_idx > start_idx:
            snippet = content[start_idx:end_idx + 1]
            try:
                return json.loads(snippet)
            except json.JSONDecodeError:
                pass

    raise ValueError(f"File '{Path(path).name}' is not valid JSON.\nPlease make sure you selected the Edit Plan (.json) file, not the rewritten script (.txt) file.")


def load_edit_plan(path: str, script_path: str) -> List[EditBeat]:
    """Load V2 multi-shot JSON with backward compatibility for V1 flat segments.

    Preferred V2:
    {
      "version": 2,
      "segments": [
        {
          "line": 1,
          "shots": [
            {"source_start": 12.0, "source_end": 14.7, "mode": "clip", "weight": 1},
            {"source_start": 18.1, "source_end": 18.8, "mode": "freeze", "weight": 1,
             "zoom": 1.18, "anchor": "right"}
          ]
        }
      ]
    }
    """
    script_lines = read_script_lines(script_path)
    raw = load_json_robust(path)
    items = raw.get("segments", []) if isinstance(raw, dict) else raw
    if not isinstance(items, list) or not items:
        raise ValueError("Edit plan must contain a non-empty 'segments' array.")

    beats: List[EditBeat] = []
    last_end = 0.0
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Segment #{idx}: expected JSON object.")
        line_no = int(item.get("line", item.get("beat", item.get("segment", idx))))
        if line_no < 1 or line_no > len(script_lines):
            raise ValueError(f"Segment #{idx}: script line {line_no} does not exist (script has {len(script_lines)} lines).")
        text = item.get("text") or item.get("narration") or script_lines[line_no - 1]

        shots_data = item.get("shots")
        if isinstance(shots_data, list) and shots_data:
            shots = []
            for s_idx, s in enumerate(shots_data, start=1):
                shot = _shot_from_item(s, parent_item=item,
                                       location_desc=f"Segment #{idx} (Line {line_no}), Shot #{s_idx}",
                                       last_known_end=last_end)
                last_end = shot.source_end
                shots.append(shot)
        else:
            # V1 flat item -> one shot
            shot = _shot_from_item(item, location_desc=f"Segment #{idx} (Line {line_no})", last_known_end=last_end)
            last_end = shot.source_end
            shots = [shot]
        beats.append(EditBeat(line_no=line_no, text=text, shots=shots))
    return beats


def load_plan_rules(plan_path: str) -> dict:
    raw = load_json_robust(plan_path)
    has_settings = isinstance(raw, dict) and ("settings" in raw or "rules" in raw)
    has_settings = isinstance(raw, dict) and ("settings" in raw or "rules" in raw)
    settings = (raw.get("settings", {}) or raw.get("rules", {})) if isinstance(raw, dict) else {}
    required = raw.get("required_character_intros", []) if isinstance(raw, dict) else []
    if not isinstance(settings, dict):
        settings = {}
    if not isinstance(required, list):
        required = []

    def _safe_rule_time(val, default):
        if val in (None, ""):
            return default
        try:
            return _parse_time_seconds(val)
        except Exception:
            return default

    min_gap_default = 3.0 if has_settings else 0.0
    strict_order_default = True if has_settings else False
    prevent_repeat_default = True if has_settings else False

    min_gap = _safe_rule_time(settings.get("min_source_gap_seconds"), min_gap_default)
    max_moving = _safe_rule_time(settings.get("max_moving_clip_seconds"), 3.0)
    return {
        "min_source_gap_seconds": max(0.0, min_gap),
        "strict_story_order": bool(settings.get("strict_story_order", strict_order_default)),
        "prevent_repeated_source": bool(settings.get("prevent_repeated_source", prevent_repeat_default)),
        "max_moving_clip_seconds": max(0.5, max_moving),
        "required_character_intros": [str(x).strip() for x in required if str(x).strip()],
    }


def _flatten_shots(beats: List[EditBeat]):
    for beat in beats:
        for shot in beat.shots:
            yield beat, shot


def validate_plan_against_script(plan_path: str, script_path: str) -> dict:
    script_lines = read_script_lines(script_path)
    beats = load_edit_plan(plan_path, script_path)
    rules = load_plan_rules(plan_path)
    flat = list(_flatten_shots(beats))
    gap = rules["min_source_gap_seconds"]
    gap_violations = []
    repeat_violations = []
    seen_scene_keys = set()
    previous = None
    used_ranges = []

    for beat, shot in flat:
        if previous is not None and rules["strict_story_order"]:
            prev_beat, prev_shot = previous
            actual_gap = shot.source_start - prev_shot.source_end
            if actual_gap + 1e-6 < gap:
                gap_violations.append({
                    "previous_line": prev_beat.line_no,
                    "line": beat.line_no,
                    "actual_gap": round(actual_gap, 3),
                })
        if rules["prevent_repeated_source"] and not shot.allow_repeat:
            for old_start, old_end, old_line in used_ranges:
                overlap = min(shot.source_end, old_end) - max(shot.source_start, old_start)
                if overlap > 0.10:
                    repeat_violations.append({"line": beat.line_no, "previous_line": old_line})
                    break
            if shot.scene_key and shot.scene_key in seen_scene_keys:
                repeat_violations.append({"line": beat.line_no, "scene_key": shot.scene_key})
        if shot.scene_key:
            seen_scene_keys.add(shot.scene_key)
        used_ranges.append((shot.source_start, shot.source_end, beat.line_no))
        previous = (beat, shot)

    required = {x.casefold(): x for x in rules["required_character_intros"]}
    found = {}
    for beat, shot in flat:
        if shot.role == "character_intro" and shot.character:
            found.setdefault(shot.character.casefold(), (shot.character, beat.line_no, shot.source_start))
    missing = [display for key, display in required.items() if key not in found]

    return {
        "script_lines": len(script_lines),
        "segments": len(beats),
        "shots": sum(len(b.shots) for b in beats),
        "same_count": (len(script_lines) == len(beats) or (len(beats) > 0 and max(b.line_no for b in beats) <= len(script_lines))),
        "min_source_gap_seconds": gap,
        "gap_violations": gap_violations,
        "repeat_violations": repeat_violations,
        "required_character_intros": rules["required_character_intros"],
        "found_character_intros": [v[0] for v in found.values()],
        "missing_character_intros": missing,
        "strict_ok": (len(gap_violations) == 0 and len(repeat_violations) == 0 and len(missing) == 0),
        "max_moving_clip_seconds": rules["max_moving_clip_seconds"],
    }


def get_video_profile(video_path: str) -> dict:
    out = run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,avg_frame_rate,r_frame_rate:format=duration",
        "-of", "json", video_path,
    ])
    data = json.loads(out)
    streams = data.get("streams") or []
    if not streams:
        raise RuntimeError("No video stream found in source video.")
    st = streams[0]
    width = max(2, int(st.get("width") or 1920))
    height = max(2, int(st.get("height") or 1080))
    width -= width % 2
    height -= height % 2
    rate = st.get("avg_frame_rate") or st.get("r_frame_rate") or "25/1"
    try:
        a, b = rate.split("/", 1)
        fps = float(a) / max(float(b), 1e-9)
    except Exception:
        fps = 25.0
    if not (1.0 <= fps <= 120.0):
        fps = 25.0
    try:
        duration = float((data.get("format") or {}).get("duration") or 0.0)
    except Exception:
        duration = 0.0
    if duration <= 0:
        try:
            duration = get_duration(video_path)
        except Exception:
            duration = 0.0
    return {"width": width, "height": height, "fps": fps, "duration": duration}


def _encode_args(render_preset: str = "fast") -> List[str]:
    # Keep CRF 18 quality while allowing faster x264 presets. A faster preset
    # mainly trades compression efficiency/file size for render time.
    preset = (render_preset or "fast").lower().strip()
    if preset not in {"medium", "fast", "veryfast"}:
        preset = "fast"
    return ["-c:v", "libx264", "-preset", preset, "-crf", "18", "-pix_fmt", "yuv420p"]


# ---------------------------------------------------------------------------
# FFmpeg effects
# ---------------------------------------------------------------------------

def _anchor_xy(anchor: str, scaled_w: int, scaled_h: int, base_w: int, base_h: int) -> tuple[int, int]:
    max_x = max(scaled_w - base_w, 0)
    max_y = max(scaled_h - base_h, 0)
    x_map = {
        "left": 0.0, "right": 1.0, "center": 0.5,
        "top": 0.5, "bottom": 0.5,
        "top_left": 0.0, "top_right": 1.0,
        "bottom_left": 0.0, "bottom_right": 1.0,
    }
    y_map = {
        "top": 0.0, "bottom": 1.0, "center": 0.5,
        "left": 0.5, "right": 0.5,
        "top_left": 0.0, "top_right": 0.0,
        "bottom_left": 1.0, "bottom_right": 1.0,
    }
    return int(max_x * x_map.get(anchor, 0.5)), int(max_y * y_map.get(anchor, 0.5))


def _look_filter(look: str) -> List[str]:
    if look == "cinematic":
        return ["eq=contrast=1.06:saturation=0.97:brightness=-0.005"]
    if look == "dramatic":
        return ["eq=contrast=1.10:saturation=1.02:brightness=-0.008"]
    if look == "mono":
        return ["hue=s=0", "eq=contrast=1.06"]
    return []


def _base_reframe_filters(zoom: float, anchor: str, flip: bool, look: str, profile: dict) -> List[str]:
    base_w, base_h = profile["width"], profile["height"]
    zoom = max(1.0, min(1.6, zoom))
    # Keep the source resolution/fps. Effects crop within the original canvas instead of forcing 1080p/25fps.
    filters = [f"scale={base_w}:{base_h}:force_original_aspect_ratio=increase", f"crop={base_w}:{base_h}"]
    if zoom > 1.0001:
        sw = int(round(base_w * zoom)); sh = int(round(base_h * zoom))
        sw += sw % 2; sh += sh % 2
        x, y = _anchor_xy(anchor, sw, sh, base_w, base_h)
        filters += [f"scale={sw}:{sh}", f"crop={base_w}:{base_h}:{x}:{y}"]
    if flip:
        filters.append("hflip")
    filters += _look_filter(look)
    return filters


def _motion_reframe_filters(shot: Shot, target_duration: float, profile: dict) -> List[str]:
    """Return frame-safe motion filters for an already-normalized clip.

    zoompan uses d=1, so every decoded source/padded frame produces one output
    frame. That lets pan/zoom continue across a short held tail instead of
    becoming a visually dead freeze.
    """
    w, h = profile["width"], profile["height"]
    fps = float(profile["fps"])
    frames = max(int(math.ceil(max(target_duration, 0.2) * fps)), 1)
    motion = shot.motion
    if motion == "none":
        return _base_reframe_filters(shot.zoom, shot.anchor, shot.flip, shot.look, profile)

    z0 = max(1.0, min(1.35, float(shot.zoom_from or 1.0)))
    z1 = max(1.0, min(1.35, float(shot.zoom_to or shot.zoom or 1.08)))
    # Pan moves need a little crop headroom even when JSON zoom values are 1.0.
    if motion.startswith("pan_") or motion == "handheld_soft":
        z0 = max(z0, 1.055)
        z1 = max(z1, 1.075)
    p = f"min(on/{max(frames-1,1):.6f},1)"

    if motion == "push_in":
        zexpr = f"{z0:.6f}+({z1-z0:.6f})*{p}"
        xexpr = "iw/2-(iw/zoom/2)"; yexpr = "ih/2-(ih/zoom/2)"
    elif motion == "pull_out":
        if z0 <= z1:
            z0, z1 = max(z1, 1.12), min(z0, 1.01)
        zexpr = f"{z0:.6f}-({z0-z1:.6f})*{p}"
        xexpr = "iw/2-(iw/zoom/2)"; yexpr = "ih/2-(ih/zoom/2)"
    elif motion == "pan_right":
        zexpr = f"{z1:.6f}"
        xexpr = f"(iw-iw/zoom)*{p}"; yexpr = "ih/2-(ih/zoom/2)"
    elif motion == "pan_left":
        zexpr = f"{z1:.6f}"
        xexpr = f"(iw-iw/zoom)*(1-{p})"; yexpr = "ih/2-(ih/zoom/2)"
    elif motion == "pan_down":
        zexpr = f"{z1:.6f}"
        xexpr = "iw/2-(iw/zoom/2)"; yexpr = f"(ih-ih/zoom)*{p}"
    elif motion == "pan_up":
        zexpr = f"{z1:.6f}"
        xexpr = "iw/2-(iw/zoom/2)"; yexpr = f"(ih-ih/zoom)*(1-{p})"
    elif motion == "pan_left_push":
        zexpr = f"{z0:.6f}+({z1-z0:.6f})*{p}"
        xexpr = f"(iw-iw/zoom)*(1-{p})"; yexpr = "ih/2-(ih/zoom/2)"
    elif motion == "pan_right_push":
        zexpr = f"{z0:.6f}+({z1-z0:.6f})*{p}"
        xexpr = f"(iw-iw/zoom)*{p}"; yexpr = "ih/2-(ih/zoom/2)"
    else:  # handheld_soft
        zexpr = f"{max(z1,1.07):.6f}"
        xexpr = "iw/2-(iw/zoom/2)+sin(on/5.0)*5"
        yexpr = "ih/2-(ih/zoom/2)+cos(on/7.0)*4"

    filters = [
        f"scale={w}:{h}:force_original_aspect_ratio=increase",
        f"crop={w}:{h}",
        f"zoompan=z='{zexpr}':x='{xexpr}':y='{yexpr}':d=1:s={w}x{h}:fps={fps:.6f}",
    ]
    if shot.flip:
        filters.append("hflip")
    filters += _look_filter(shot.look)
    return filters


def _overlay_filters(shot: Shot, profile: dict) -> List[str]:
    """Subtle procedural overlays; no external particle asset is required."""
    filters: List[str] = []
    strength = max(0.0, min(1.0, float(shot.grain)))
    if shot.overlay == "film_grain" or strength > 0.001:
        amount = max(1.0, min(8.0, 1.5 + strength * 18.0))
        filters.append(f"noise=alls={amount:.2f}:allf=t+u")

    if shot.overlay == "dust_subtle":
        # Tiny moving translucent specks. Positions are time-driven so they drift
        # while the underlying clip/padded tail keeps moving through pan/zoom.
        specs = [
            ("55*t+37", "31*t+71", 3, 3, "white@0.12"),
            ("-42*t+410", "48*t+120", 2, 2, "white@0.10"),
            ("73*t+160", "-29*t+330", 3, 2, "white@0.09"),
            ("-35*t+690", "-44*t+510", 2, 3, "white@0.08"),
        ]
        for x, y, bw, bh, color in specs:
            filters.append(
                f"drawbox=x='mod({x},iw)':y='mod({y},ih)':w={bw}:h={bh}:"
                f"color={color}:t=fill"
            )
    elif shot.overlay == "light_specks":
        specs = [
            ("28*t+90", "-52*t+640", 4, 4, "white@0.11"),
            ("-32*t+620", "-38*t+420", 3, 3, "white@0.09"),
            ("45*t+280", "-61*t+710", 2, 4, "white@0.08"),
        ]
        for x, y, bw, bh, color in specs:
            filters.append(
                f"drawbox=x='mod({x},iw)':y='mod({y},ih)':w={bw}:h={bh}:"
                f"color={color}:t=fill"
            )
    return filters


def build_clip_shot(video_path: str, shot: Shot, target_duration: float, out_path: str,
                    profile: dict, max_moving_clip_seconds: float = 3.0,
                    render_preset: str = "fast"):
    target_duration = max(0.20, float(target_duration))
    src_duration = float(profile.get("duration") or 0.0)
    safe_start = max(0.0, float(shot.source_start))
    safe_end = max(safe_start + 0.20, float(shot.source_end))
    if src_duration > 0.25:
        safe_start = min(safe_start, max(0.0, src_duration - 0.25))
        safe_end = min(max(safe_end, safe_start + 0.20), src_duration)
    avail = max(safe_end - safe_start, 0.20)

    max_extract = max(0.5, float(max_moving_clip_seconds))
    grab = min(avail, max_extract)

    # Preserve the requested speed when possible. If a narration share is only
    # slightly longer than the source extract, gently slow the clip (never below
    # 0.80x) before using any held tail. This keeps more of the segment genuinely
    # moving instead of freezing early.
    requested_speed = max(0.5, min(2.0, float(shot.speed)))
    effective_speed = requested_speed
    moving_out = grab / effective_speed
    if moving_out + 0.02 < target_duration:
        fill_speed = grab / target_duration
        if 0.80 <= fill_speed < effective_speed:
            effective_speed = fill_speed
            moving_out = grab / effective_speed

    # Important: tpad happens BEFORE zoom/pan/particle filters. If a short tail
    # must be held, camera motion and texture continue across it, so it does not
    # look like a dead freeze frame.
    filters: List[str] = []
    if abs(effective_speed - 1.0) > 0.001:
        filters.append(f"setpts=PTS/{effective_speed:.6f}")
    pad_needed = max(0.0, target_duration - moving_out)
    if pad_needed > 0.01:
        filters.append(f"tpad=stop_mode=clone:stop_duration={pad_needed + 0.12:.3f}")
    filters += _motion_reframe_filters(shot, target_duration, profile)
    filters += _overlay_filters(shot, profile)

    cmd = [
        "ffmpeg", "-y", "-ss", f"{safe_start:.3f}", "-i", video_path,
        "-t", f"{grab:.3f}", "-an", "-vf", ",".join(filters),
        "-t", f"{target_duration:.3f}", "-r", f"{profile['fps']:.6f}",
    ] + _encode_args(render_preset) + ["-movflags", "+faststart", out_path]
    try:
        run(cmd)
    except RuntimeError:
        # EOF/corrupt-GOP safety only. Normal edit plans should stay moving.
        build_freeze_shot(video_path, shot, target_duration, out_path, profile, render_preset)
        return
    if not _file_nonempty(out_path):
        build_freeze_shot(video_path, shot, target_duration, out_path, profile, render_preset)

def build_freeze_shot(video_path: str, shot: Shot, target_duration: float, out_path: str, profile: dict,
                      render_preset: str = "fast"):
    """Build a freeze/zoom shot with robust end-of-video fallback.

    FFmpeg can return exit-code 0 yet produce no image when seeking just past the
    final decodable frame. V2.4 verifies the PNG and retries progressively earlier
    timestamps (plus an -sseof fallback) so one bad EOF timestamp cannot kill a run.
    """
    target_duration = max(0.20, float(target_duration))
    requested_mid = (shot.source_start + shot.source_end) / 2.0
    src_duration = float(profile.get("duration") or 0.0)
    frame_path = out_path + ".frame.png"
    os.makedirs(os.path.dirname(os.path.abspath(frame_path)), exist_ok=True)

    def clear_frame():
        try:
            if os.path.exists(frame_path):
                os.remove(frame_path)
        except OSError:
            pass

    candidates = []
    def add_candidate(ts):
        try:
            ts = max(0.0, float(ts))
        except Exception:
            return
        if src_duration > 0.25:
            ts = min(ts, max(0.0, src_duration - 0.25))
        if not any(abs(ts - x) < 0.05 for x in candidates):
            candidates.append(ts)

    add_candidate(requested_mid)
    add_candidate(shot.source_start)
    if src_duration > 0:
        add_candidate(src_duration - 0.50)
        add_candidate(src_duration - 1.00)
        add_candidate(src_duration - 2.00)

    extracted = False
    for ts in candidates:
        clear_frame()
        try:
            run([
                "ffmpeg", "-y", "-ss", f"{ts:.3f}", "-i", video_path,
                "-map", "0:v:0", "-frames:v", "1", "-compression_level", "3",
                "-update", "1", frame_path,
            ])
        except RuntimeError:
            pass
        if _file_nonempty(frame_path):
            extracted = True
            break

    if not extracted:
        clear_frame()
        try:
            run([
                "ffmpeg", "-y", "-sseof", "-1.0", "-i", video_path,
                "-map", "0:v:0", "-frames:v", "1", "-compression_level", "3",
                "-update", "1", frame_path,
            ])
        except RuntimeError:
            pass
        extracted = _file_nonempty(frame_path)

    if not extracted:
        raise RuntimeError(
            f"Could not extract a valid freeze frame near {requested_mid:.2f}s. "
            f"Detected source duration: {src_duration:.2f}s. The source file may be truncated or undecodable near EOF."
        )

    fps = profile["fps"]
    frames = max(int(math.ceil(target_duration * fps)), 1)
    end_zoom = max(1.03, shot.zoom if shot.zoom > 1.0 else 1.14)
    increment = max((end_zoom - 1.0) / frames, 0.00001)
    w,h=profile["width"],profile["height"]
    filters = [
        f"scale={w}:{h}:force_original_aspect_ratio=increase",
        f"crop={w}:{h}",
        f"zoompan=z='min(zoom+{increment:.8f},{end_zoom:.5f})':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps:.6f}",
    ]
    if shot.flip:
        filters.append("hflip")
    filters += _look_filter(shot.look)
    filters += _overlay_filters(shot, profile)
    cmd=[
        "ffmpeg", "-y", "-loop", "1", "-i", frame_path,
        "-vf", ",".join(filters), "-t", f"{target_duration:.3f}",
    ] + _encode_args(render_preset) + ["-movflags", "+faststart", out_path]
    run(cmd)
    clear_frame()

def concat_video_only(paths: List[str], out_path: str, workdir: str, tag: str,
                      render_preset: str = "fast"):
    """Concat normalized segments. Fast stream-copy first; if FFmpeg rejects
    a timestamp/stream mismatch, transparently retry with a normalized re-encode.
    This makes final assembly much more resilient on Windows/varied source files.
    """
    list_file = os.path.join(workdir, f"concat_{tag}.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for p in paths:
            safe = os.path.abspath(p).replace("'", "'\\''")
            f.write(f"file '{safe}'\n")
    try:
        run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file,
            "-c", "copy", out_path,
        ])
    except RuntimeError:
        # Retry by normalizing streams instead of abandoning the completed cache.
        run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file,
            "-c:v", "libx264", "-preset", render_preset, "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", out_path,
        ])


def mux_audio(video_only_path: str, audio_path: str, out_path: str):
    run([
        "ffmpeg", "-y", "-i", video_only_path, "-i", audio_path,
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out_path,
    ])


def _color_to_ass_hex(color_name: str) -> tuple[str, str, str, str, int, int]:
    """
    Returns (PrimaryColour, SecondaryColour, OutlineColour, BackColour, outline_w, shadow_w)
    in ASS &HAABBGGRR hex format.
    """
    c = str(color_name).strip().lower()
    if "yellow pop" in c or ("yellow" in c and "pill" not in c and "box" not in c and "cinema" not in c):
        return ("&H0000FFFF", "&H00FFFFFF", "&H00000000", "&H80000000", 4, 2)
    elif "karaoke" in c:
        return ("&H0000FFFF", "&H00FFFFFF", "&H00000000", "&H80000000", 4, 2)
    elif "white & black box" in c or ("box" in c and "yellow" not in c):
        return ("&H00FFFFFF", "&H0000FFFF", "&H00000000", "&HB0000000", 6, 0)
    elif "neon cyan" in c or "cyan" in c or "teal" in c:
        return ("&H00FFFF00", "&H00FFFFFF", "&H00400000", "&H80000000", 4, 2)
    elif "gold" in c or "luxury" in c:
        return ("&H0000D7FF", "&H00FFFFFF", "&H00000000", "&H80000000", 4, 3)
    elif "red & white" in c or "red" in c:
        return ("&H000000FF", "&H00FFFFFF", "&H00000000", "&H80000000", 4, 2)
    elif "cyberpunk" in c or "green" in c or "emerald" in c:
        return ("&H0000FF00", "&H00FFFFFF", "&H00000000", "&H80000000", 4, 2)
    elif "purple" in c or "violet" in c or "electric purple" in c:
        return ("&H00FF00FF", "&H00FFFF00", "&H00000000", "&H80000000", 4, 2)
    elif "yellow pill" in c or "cinema yellow" in c or "pill" in c:
        return ("&H00000000", "&H00000000", "&H0000D4FF", "&H0000D4FF", 6, 0)
    elif "orange" in c or "fire" in c:
        return ("&H000080FF", "&H00FFFFFF", "&H00000000", "&H80000000", 4, 2)
    elif "pastel blue" in c or "blue" in c:
        return ("&H00F0A030", "&H00FFFFFF", "&H00000000", "&H80000000", 3, 1)
    else:  # Minimal White Shadow
        return ("&H00FFFFFF", "&H0000FFFF", "&H00151515", "&H80000000", 3, 2)


def add_watermark(video_path: str, logo_path: str, out_path: str, render_preset: str = "fast",
                  position: str = "Top-Right", x_offset: int = 24, y_offset: int = 24,
                  logo_width: int = 200, custom_x: Optional[int] = None, custom_y: Optional[int] = None,
                  log_callback: Optional[Callable[[str], None]] = None):
    """Add watermark/logo overlay with customizable size/scale and drag & drop coordinates."""
    pos = position.strip()
    scale_expr = f"scale={max(40, min(800, int(logo_width)))}:-1"

    if custom_x is not None and custom_y is not None and ("custom" in pos.lower() or pos == "Custom"):
        overlay_expr = f"{int(custom_x)}:{int(custom_y)}"
    elif pos == "Top-Left":
        overlay_expr = f"{x_offset}:{y_offset}"
    elif pos == "Bottom-Right":
        overlay_expr = f"W-w-{x_offset}:H-h-{y_offset}"
    elif pos == "Bottom-Left":
        overlay_expr = f"{x_offset}:H-h-{y_offset}"
    elif pos == "Center":
        overlay_expr = "(W-w)/2:(H-h)/2"
    elif "custom" in pos.lower():
        cx = custom_x if custom_x is not None else x_offset
        cy = custom_y if custom_y is not None else y_offset
        overlay_expr = f"{int(cx)}:{int(cy)}"
    else:  # Top-Right default
        overlay_expr = f"W-w-{x_offset}:{y_offset}"

    dur = get_duration(video_path)
    run_with_progress([
        "ffmpeg", "-y", "-i", video_path, "-i", logo_path,
        "-filter_complex", f"[1:v]{scale_expr}[wm];[0:v][wm]overlay={overlay_expr}",
        "-c:v", "libx264", "-preset", render_preset, "-crf", "18", "-c:a", "copy", out_path,
    ], total_duration=dur, log_callback=log_callback, step_name="Watermark")


def hex_to_ass_abgr(hex_str: str, alpha: int = 0) -> str:
    """Converts #RRGGBB or RRGGBB to ASS &HAABBGGRR hex format."""
    if not hex_str: return f"&H{alpha:02X}FFFFFF"
    h = str(hex_str).strip().lstrip("#")
    if len(h) == 6:
        r, g, b = h[0:2], h[2:4], h[4:6]
        return f"&H{alpha:02X}{b}{g}{r}"
    elif len(h) == 8:
        r, g, b, a = h[0:2], h[2:4], h[4:6], h[6:8]
        return f"&H{a}{b}{g}{r}"
    return f"&H{alpha:02X}FFFFFF"


def generate_capcut_ass_file(beats: List[EditBeat], segment_durations: List[float], ass_out_path: str,
                             font_name: str = "Impact", font_size: int = 28,
                             preset_style: str = "CapCut Yellow Pop", position: str = "Bottom-Center",
                             text_case: str = "ALL CAPS", max_words_per_line: Union[int, str] = 10,
                             max_lines_per_caption: Union[int, str] = 1,
                             custom_font_path: Optional[str] = None,
                             custom_caption_x: Optional[int] = None, custom_caption_y: Optional[int] = None,
                             target_w: int = 1280, target_h: int = 720,
                             custom_font_color: Optional[str] = None,
                             custom_stroke_color: Optional[str] = None,
                             custom_stroke_width: Optional[int] = None,
                             custom_shadow_color: Optional[str] = None,
                             custom_shadow_width: Optional[int] = None,
                             custom_box_color: Optional[str] = None,
                             custom_box_opacity: Optional[float] = None):
    """Generates an Advanced SubStation Alpha (.ass) subtitle file with CapCut font styling, text casing, word choose & line count controls, and custom color/stroke/shadow overrides."""
    os.makedirs(os.path.dirname(os.path.abspath(ass_out_path)) or ".", exist_ok=True)
    primary_c, secondary_c, outline_c, back_c, outline_w, shadow_w = _color_to_ass_hex(preset_style)

    # Apply manual/custom color overrides if provided
    if custom_font_color and str(custom_font_color).strip():
        primary_c = hex_to_ass_abgr(custom_font_color, 0)
    if custom_stroke_color and str(custom_stroke_color).strip():
        outline_c = hex_to_ass_abgr(custom_stroke_color, 0)
    if custom_stroke_width is not None and int(custom_stroke_width) >= 0:
        outline_w = int(custom_stroke_width)
    if custom_shadow_color and str(custom_shadow_color).strip():
        back_c = hex_to_ass_abgr(custom_shadow_color, 128)
    if custom_shadow_width is not None and int(custom_shadow_width) >= 0:
        shadow_w = int(custom_shadow_width)

    alignment = 2
    pos_lower = str(position).lower()
    if "top" in pos_lower:
        alignment = 8
    elif "middle" in pos_lower or ("center" in pos_lower and "bottom" not in pos_lower):
        alignment = 5

    border_style = 3 if ("box" in preset_style.lower() or "pill" in preset_style.lower()) else 1

    if custom_box_color and str(custom_box_color).strip():
        border_style = 3
        box_opa = float(custom_box_opacity) if custom_box_opacity is not None else 0.8
        alpha_val = max(0, min(255, int((1.0 - box_opa) * 255)))
        back_c = hex_to_ass_abgr(custom_box_color, alpha_val)
        outline_c = back_c

    effective_font = font_name
    if custom_font_path and os.path.exists(custom_font_path):
        try:
            from PIL import ImageFont
            f_test = ImageFont.truetype(custom_font_path, 30)
            rec = f_test.getname()
            if rec and rec[0]:
                effective_font = rec[0]
            else:
                effective_font = Path(custom_font_path).stem
        except Exception:
            effective_font = Path(custom_font_path).stem

    pw = max(480, int(target_w)) if target_w else 1280
    ph = max(360, int(target_h)) if target_h else 720

    scale_factor = pw / 1280.0
    effective_fsize = max(16, int(font_size * scale_factor))

    # Calculate vertical margin: For vertical 9:16 shorts (ph > pw), leave ~14% safe margin at bottom
    if ph > pw:
        margin_v = max(80, int(ph * 0.14)) if alignment == 2 else max(40, int(ph * 0.05))
    else:
        margin_v = max(30, int(ph * 0.05))

    margin_l = max(20, int(pw * 0.04))
    margin_r = max(20, int(pw * 0.04))

    header_str = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {pw}
PlayResY: {ph}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: CapCutStyle,{effective_font},{effective_fsize},{primary_c},{secondary_c},{outline_c},{back_c},-1,0,0,0,100,100,0,0,{border_style},{outline_w},{shadow_w},{alignment},{margin_l},{margin_r},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    current_time = 0.0

    def format_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = seconds % 60
        return f"{h}:{m:02d}:{s:05.2f}"

    def apply_casing(t: str) -> str:
        tc = (text_case or "Normal").strip().lower()
        if "all" in tc or "caps" in tc or "upper" in tc:
            return t.upper()
        elif "first" in tc or "title" in tc or "capital" in tc:
            return t.title()
        return t

    def parse_max_words(val) -> int:
        s = str(val).lower().strip()
        if "1 word" in s or s == "1": return 1
        elif "2 word" in s or s == "2": return 2
        elif "3 word" in s or s == "3": return 3
        elif "4 word" in s or s == "4": return 4
        elif "5 word" in s or s == "5": return 5
        elif "6 word" in s or s == "6": return 6
        elif "7 word" in s or s == "7": return 7
        elif "8 word" in s or s == "8": return 8
        elif "9 word" in s or s == "9": return 9
        elif "10 word" in s or s == "10": return 10
        elif "full" in s or "sentence" in s or "line" in s: return 50
        import re
        m = re.search(r'(\d+)', s)
        if m:
            return max(1, min(50, int(m.group(1))))
        return 10

    def parse_max_lines(val) -> int:
        s = str(val).lower().strip()
        if "1 line" in s or s == "1": return 1
        elif "2 line" in s or s == "2": return 2
        elif "3 line" in s or s == "3": return 3
        elif "4 line" in s or s == "4": return 4
        elif "auto" in s: return 2
        try: return max(1, min(10, int(val)))
        except Exception: return 1

    max_w = parse_max_words(max_words_per_line)
    max_l = parse_max_lines(max_lines_per_caption)
    words_per_event = max_w * max_l

    pos_tag = ""
    if custom_caption_x is not None and custom_caption_y is not None:
        try:
            cx = float(custom_caption_x)
            cy = float(custom_caption_y)
            if 0.0 <= cx <= 1.0:
                cx = cx * pw
            if 0.0 <= cy <= 1.0:
                cy = cy * ph
            pos_tag = f"{{\\an5\\pos({int(cx)},{int(cy)})}}"
        except Exception:
            pos_tag = ""

    for i, beat in enumerate(beats):
        dur = segment_durations[i] if i < len(segment_durations) else 3.0
        text = apply_casing(beat.text.strip())
        words = text.split()

        if not words:
            current_time += dur
            continue

        # Group words into events based on words_per_line * lines_on_screen
        if len(words) > words_per_event:
            event_word_slices = [words[k:k + words_per_event] for k in range(0, len(words), words_per_event)]
        else:
            event_word_slices = [words]

        # For each event, if max_l > 1 and slice exceeds max_w, join lines with ASS \N
        chunks = []
        for w_slice in event_word_slices:
            if max_l > 1 and len(w_slice) > max_w:
                sub_lines = [" ".join(w_slice[j:j + max_w]) for j in range(0, len(w_slice), max_w)]
                chunks.append(r"\N".join(sub_lines))
            else:
                chunks.append(" ".join(w_slice))

        if not chunks:
            current_time += dur
            continue

        # Real-time Voice Sync Formula: Weight each word/chunk by character length & punctuation pauses
        chunk_weights = []
        for chk in chunks:
            raw_chk = chk.replace(r"\N", " ")
            chk_w = sum(len(w) for w in raw_chk.split())
            # Extra pause weight for punctuation marks (. , ! ? ; :)
            if any(raw_chk.strip().endswith(p) for p in [".", ",", "!", "?", ";", ":"]):
                chk_w += 2.5
            chunk_weights.append(max(1.0, float(chk_w)))

        total_weight = sum(chunk_weights) or 1.0
        elapsed_in_beat = 0.0

        for c_idx, chunk_text in enumerate(chunks):
            c_dur = dur * (chunk_weights[c_idx] / total_weight)
            sub_start = current_time + elapsed_in_beat
            sub_end = sub_start + c_dur
            elapsed_in_beat += c_dur

            start_str = format_time(sub_start)
            end_str = format_time(sub_end)

            if "karaoke" in preset_style.lower():
                lines_in_chunk = chunk_text.split(r"\N")
                all_k_lines = []
                total_chunk_words = sum(len(ln.split()) for ln in lines_in_chunk)
                ms_per_word = int((c_dur * 100) / max(1, total_chunk_words))
                for ln in lines_in_chunk:
                    ln_words = ln.split()
                    if ln_words:
                        k_ln = "".join(f"{{\\k{ms_per_word}}}{w} " for w in ln_words).strip()
                        all_k_lines.append(k_ln)
                    else:
                        all_k_lines.append(ln)
                k_text = r"\N".join(all_k_lines)
                events.append(f"Dialogue: 0,{start_str},{end_str},CapCutStyle,,0,0,0,,{pos_tag}{k_text}")
            else:
                events.append(f"Dialogue: 0,{start_str},{end_str},CapCutStyle,,0,0,0,,{pos_tag}{chunk_text}")

        current_time += dur

    with open(ass_out_path, "w", encoding="utf-8") as f:
        f.write(header_str + "\n".join(events) + "\n")
    return ass_out_path


def burn_subtitles(video_path: str, ass_path: str, out_path: str, render_preset: str = "fast",
                   custom_font_path: Optional[str] = None, log_callback: Optional[Callable[[str], None]] = None):
    """Burn ASS subtitles onto final video using FFmpeg with optional custom fontsdir and progress logging."""
    safe_ass = os.path.abspath(ass_path).replace("\\", "/").replace(":", "\\:")
    vf_expr = f"subtitles='{safe_ass}'"
    if custom_font_path and os.path.exists(custom_font_path):
        font_dir = os.path.dirname(os.path.abspath(custom_font_path))
        safe_font_dir = os.path.abspath(font_dir).replace("\\", "/").replace(":", "\\:")
        vf_expr = f"subtitles='{safe_ass}':fontsdir='{safe_font_dir}'"
    dur = get_duration(video_path)
    run_with_progress([
        "ffmpeg", "-y", "-i", video_path,
        "-vf", vf_expr,
        "-c:v", "libx264", "-preset", render_preset, "-crf", "18", "-c:a", "copy", out_path,
    ], total_duration=dur, log_callback=log_callback, step_name="Subtitles")


def render_logo_caption_preview_frame(video_path: str, logo_path: Optional[str], out_img_path: str,
                                      enable_logo: bool = True, logo_position: str = "Top-Right",
                                      logo_width: int = 200, custom_x: Optional[int] = None, custom_y: Optional[int] = None,
                                      enable_captions: bool = True, caption_preset: str = "CapCut Yellow Pop",
                                      caption_font: str = "Impact", caption_size: int = 28,
                                      caption_position: str = "Bottom-Center",
                                      caption_case: str = "ALL CAPS", caption_words_per_line: Union[int, str] = 10,
                                      caption_lines: Union[int, str] = 1,
                                      custom_font_path: Optional[str] = None,
                                      custom_caption_x: Optional[int] = None, custom_caption_y: Optional[int] = None):
    """Renders a single 1280x720 PNG frame combining logo watermark & CapCut styled subtitle overlay for live GUI preview."""
    os.makedirs(os.path.dirname(os.path.abspath(out_img_path)) or ".", exist_ok=True)
    temp_dir = os.path.join(os.path.dirname(out_img_path), "preview_temp")
    os.makedirs(temp_dir, exist_ok=True)

    # Sample base frame
    base_frame = os.path.join(temp_dir, "base_frame.jpg")
    if video_path and os.path.exists(video_path):
        ext = os.path.splitext(video_path)[1].lower()
        if ext in [".png", ".jpg", ".jpeg", ".webp", ".bmp"]:
            run(["ffmpeg", "-y", "-i", video_path, "-vframes", "1", "-s", "1280x720", base_frame])
        else:
            try:
                run(["ffmpeg", "-y", "-ss", "00:00:02", "-i", video_path, "-vframes", "1", "-s", "1280x720", base_frame])
            except Exception:
                run(["ffmpeg", "-y", "-i", video_path, "-vframes", "1", "-s", "1280x720", base_frame])
    else:
        # Create solid dark canvas if no video selected
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=181B2A:s=1280x720:d=1", "-vframes", "1", base_frame])

    current_frame = base_frame

    # Watermark overlay
    if enable_logo and logo_path and os.path.exists(logo_path):
        wm_frame = os.path.join(temp_dir, "wm_frame.jpg")
        pos = logo_position.strip()
        scale_expr = f"scale={max(40, min(800, int(logo_width)))}:-1"

        if custom_x is not None and custom_y is not None and ("custom" in pos.lower() or pos == "Custom"):
            overlay_expr = f"{int(custom_x)}:{int(custom_y)}"
        elif pos == "Top-Left":
            overlay_expr = "24:24"
        elif pos == "Bottom-Right":
            overlay_expr = "W-w-24:H-h-24"
        elif pos == "Bottom-Left":
            overlay_expr = "24:H-h-24"
        elif pos == "Center":
            overlay_expr = "(W-w)/2:(H-h)/2"
        elif "custom" in pos.lower():
            cx = custom_x if custom_x is not None else 24
            cy = custom_y if custom_y is not None else 24
            overlay_expr = f"{int(cx)}:{int(cy)}"
        else:
            overlay_expr = "W-w-24:24"

        run([
            "ffmpeg", "-y", "-i", current_frame, "-i", logo_path,
            "-filter_complex", f"[1:v]{scale_expr}[wm];[0:v][wm]overlay={overlay_expr}",
            "-vframes", "1", wm_frame,
        ])
        current_frame = wm_frame

    # CapCut Caption overlay
    if enable_captions:
        sample_beat = EditBeat(line_no=1, text="CapCut Subtitle Preview: High Impact Storytelling!", shots=[])
        ass_sample = os.path.join(temp_dir, "sample.ass")
        generate_capcut_ass_file([sample_beat], [5.0], ass_sample, font_name=caption_font,
                                font_size=caption_size, preset_style=caption_preset, position=caption_position,
                                text_case=caption_case, max_words_per_line=caption_words_per_line,
                                max_lines_per_caption=caption_lines,
                                custom_font_path=custom_font_path,
                                custom_caption_x=custom_caption_x, custom_caption_y=custom_caption_y)
        safe_ass = os.path.abspath(ass_sample).replace("\\", "/").replace(":", "\\:")
        vf_expr = f"subtitles='{safe_ass}'"
        if custom_font_path and os.path.exists(custom_font_path):
            font_dir = os.path.dirname(os.path.abspath(custom_font_path))
            safe_font_dir = os.path.abspath(font_dir).replace("\\", "/").replace(":", "\\:")
            vf_expr = f"subtitles='{safe_ass}':fontsdir='{safe_font_dir}'"
        sub_frame = os.path.join(temp_dir, "sub_frame.png")
        run([
            "ffmpeg", "-y", "-i", current_frame,
            "-vf", vf_expr,
            "-vframes", "1", sub_frame,
        ])
        current_frame = sub_frame

    shutil.copy2(current_frame, out_img_path)
    return out_img_path


def build_movie(recap_video_path: str, intro_video_paths: List[str], target_duration_seconds: float,
                out_movie_path: str, workdir: str, render_preset: str = "fast", log_callback: LogFn = None) -> str:
    """
    Render a Recap Movie:
    1. Prepend Intro Video(s) if provided.
    2. Loop the main recap video as many times as needed to reach target_duration_seconds.
    3. Concatenate all segments in proper sequence to produce final movie.
    """
    intros = [os.path.abspath(p) for p in (intro_video_paths or []) if p and _file_nonempty(p)]
    recap = os.path.abspath(recap_video_path)
    if not _file_nonempty(recap):
        raise ValueError("Recap video file not found or empty.")

    recap_dur = get_duration(recap)
    if recap_dur <= 0.5:
        raise ValueError("Recap video duration is too short for movie generation.")

    intro_dur = sum(get_duration(p) for p in intros)
    _log(log_callback, f"[movie] Intro videos duration: {intro_dur:.2f}s • Recap video duration: {recap_dur:.2f}s")

    remaining_dur = max(0.0, target_duration_seconds - intro_dur)
    loop_count = max(1, math.ceil(remaining_dur / recap_dur)) if target_duration_seconds > 0 else 1

    _log(log_callback, f"[movie] Target movie duration: {target_duration_seconds/3600:.2f}h ({target_duration_seconds:.0f}s) • Looping recap {loop_count} time(s)")

    movie_sequence = intros + [recap] * loop_count
    os.makedirs(workdir, exist_ok=True)

    concat_video_only(movie_sequence, out_movie_path, workdir, "movie_final", render_preset)
    _log(log_callback, f"[movie] Final movie created: {out_movie_path}")
    return out_movie_path


def mix_bgm(video_path: str, bgm_path: str, out_path: str, volume: float = 0.10,
            loop: bool = True, voice_volume: float = 1.0):
    """Mix narration/video audio with BGM using independently adjustable levels."""
    volume = max(0.0, min(1.0, float(volume)))
    voice_volume = max(0.0, min(2.0, float(voice_volume)))
    cmd = ["ffmpeg", "-y", "-i", video_path]
    if loop:
        cmd += ["-stream_loop", "-1"]
    cmd += ["-i", bgm_path]
    filter_complex = (
        f"[0:a]volume={voice_volume:.4f}[voice];"
        f"[1:a]volume={volume:.4f}[bg];"
        f"[voice][bg]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[mix];"
        f"[mix]alimiter=limit=0.97[aout]"
    )
    cmd += [
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out_path,
    ]
    run(cmd)



def prepare_bgm_playlist(bgm_paths: List[str], out_path: str, log_callback: LogFn = None) -> str:
    """Normalize and concatenate one or more BGM tracks into a reusable playlist file.

    Track order is exactly the order supplied by the GUI. The resulting playlist can
    then be looped as one continuous audio source through the full final video.
    """
    paths = [os.path.abspath(p) for p in (bgm_paths or []) if p]
    if not paths:
        raise ValueError("No BGM tracks selected.")
    missing = [p for p in paths if not _file_nonempty(p)]
    if missing:
        raise ValueError("BGM file not found or empty: " + missing[0])

    if len(paths) == 1:
        return paths[0]

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    meta_path = out_path + ".json"
    identity_items = []
    for p in paths:
        st = os.stat(p)
        identity_items.append({
            "path": p,
            "size": st.st_size,
            "mtime_ns": getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        })
    identity = _sha256_text(json.dumps(identity_items, sort_keys=True, ensure_ascii=False))

    try:
        if _file_nonempty(out_path) and os.path.exists(meta_path):
            meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
            if meta.get("identity") == identity:
                _log(log_callback, f"[bgm] Playlist cache reused ({len(paths)} tracks)")
                return out_path
    except Exception:
        pass

    _log(log_callback, f"[bgm] Building playlist from {len(paths)} tracks...")
    cmd = ["ffmpeg", "-y"]
    for path in paths:
        cmd += ["-i", path]
    chains = []
    labels = []
    for i in range(len(paths)):
        label = f"bg{i}"
        chains.append(
            f"[{i}:a]aresample=44100,"
            f"aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[{label}]"
        )
        labels.append(f"[{label}]")
    chains.append("".join(labels) + f"concat=n={len(paths)}:v=0:a=1[playlist]")
    cmd += [
        "-filter_complex", ";".join(chains),
        "-map", "[playlist]",
        "-vn", "-c:a", "aac", "-b:a", "192k",
        out_path,
    ]
    run(cmd)
    Path(meta_path).write_text(
        json.dumps({"identity": identity, "tracks": paths}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return out_path

def apply_video_audio_volume(video_path: str, out_path: str, voice_volume: float = 1.0):
    """Adjust final narration/video audio even when no BGM is selected."""
    voice_volume = max(0.0, min(2.0, float(voice_volume)))
    if abs(voice_volume - 1.0) < 0.001:
        shutil.copy2(video_path, out_path)
        return
    run([
        "ffmpeg", "-y", "-i", video_path,
        "-filter:a", f"volume={voice_volume:.4f}",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", out_path,
    ])


def render_audio_preview(voice_audio_path: str, bgm_path: str, out_path: str,
                         voice_volume: float = 1.0, bgm_volume: float = 0.10,
                         duration: float = 12.0, loop_bgm: bool = True):
    """Create a short WAV preview of narration + BGM at the chosen levels."""
    voice_volume = max(0.0, min(2.0, float(voice_volume)))
    bgm_volume = max(0.0, min(1.0, float(bgm_volume)))
    duration = max(3.0, min(30.0, float(duration)))
    cmd = ["ffmpeg", "-y", "-i", voice_audio_path]
    if loop_bgm:
        cmd += ["-stream_loop", "-1"]
    cmd += ["-i", bgm_path]
    filt = (
        f"[0:a]volume={voice_volume:.4f}[voice];"
        f"[1:a]volume={bgm_volume:.4f}[bg];"
        f"[voice][bg]amix=inputs=2:duration=first:dropout_transition=1:normalize=0[mix];"
        f"[mix]alimiter=limit=0.97[aout]"
    )
    cmd += [
        "-filter_complex", filt, "-map", "[aout]",
        "-t", f"{duration:.3f}", "-ar", "44100", "-ac", "2",
        "-c:a", "pcm_s16le", out_path,
    ]
    run(cmd)


def apply_narration_speed(input_path: str, out_path: str, speed: float = 1.0):
    """Apply a small local narration speed change without spending TTS credits again."""
    speed = max(0.80, min(1.30, float(speed)))
    if abs(speed - 1.0) < 0.001:
        shutil.copy2(input_path, out_path)
        return
    run([
        "ffmpeg", "-y", "-i", input_path, "-vn",
        "-filter:a", f"atempo={speed:.5f}",
        "-c:a", "libmp3lame", "-b:a", "128k", out_path,
    ])



def _file_signature(path: str) -> dict:
    """Local cache signature for uploaded audio without hashing a huge media file."""
    st = os.stat(path)
    return {
        "path": os.path.abspath(path),
        "size": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
    }


def _transcode_audio_to_mp3(input_path: str, out_path: str):
    run([
        "ffmpeg", "-y", "-i", input_path, "-vn",
        "-c:a", "libmp3lame", "-b:a", "160k", out_path,
    ])


def prepare_uploaded_voiceover_segments(uploaded_paths: List[str], beats: List[EditBeat],
                                         audio_dir: str, log_callback: LogFn = None) -> str:
    """Prepare one raw narration file per script beat from uploaded narration.

    If the user chooses one complete narration file, it is split proportionally by
    script-line word weight. If they choose exactly one file per script beat, mapping
    is exact: file 1 -> line 1, file 2 -> line 2, etc.
    """
    paths = [os.path.abspath(p) for p in (uploaded_paths or []) if p]
    if not paths:
        raise ValueError("Upload Voiceover mode requires at least one narration audio file.")
    missing = [p for p in paths if not _file_nonempty(p)]
    if missing:
        raise FileNotFoundError(f"Uploaded voiceover file not found or empty: {missing[0]}")
    if len(paths) not in (1, len(beats)):
        raise ValueError(
            f"Upload Voiceover accepts either 1 complete narration file or exactly {len(beats)} line-by-line files; got {len(paths)}."
        )

    sig_payload = {
        "files": [_file_signature(p) for p in paths],
        "lines": [b.text for b in beats],
        "mode": "line_files" if len(paths) == len(beats) else "single_full_audio",
    }
    upload_fp = _sha256_text(json.dumps(sig_payload, sort_keys=True, ensure_ascii=False))
    meta_path = os.path.join(audio_dir, "uploaded_voiceover_manifest.json")
    old_fp = ""
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            old_fp = json.load(f).get("fingerprint", "")
    except Exception:
        pass

    raw_paths = [os.path.join(audio_dir, f"tts_raw_{i:04d}.mp3") for i in range(len(beats))]
    if old_fp == upload_fp and all(_file_nonempty(x) for x in raw_paths):
        _log(log_callback, f"[voice upload] Reusing {len(raw_paths)} cached narration line audio file(s)")
        return upload_fp

    for rp in raw_paths:
        try:
            if os.path.exists(rp):
                os.remove(rp)
        except OSError:
            pass

    if len(paths) == len(beats):
        _log(log_callback, f"[voice upload] Importing {len(paths)} line-by-line narration file(s)")
        for i, src in enumerate(paths):
            _transcode_audio_to_mp3(src, raw_paths[i])
    else:
        src = paths[0]
        total = get_duration(src)
        if total <= 0.2:
            raise ValueError("Uploaded narration audio is too short.")
        weights = []
        for b in beats:
            words = max(1, len(re.findall(r"\b\w+\b", b.text, flags=re.UNICODE)))
            punctuation_pause = 0.35 + 0.12 * sum(b.text.count(ch) for ch in ".!?;:")
            weights.append(words + punctuation_pause * 2.0)
        total_w = sum(weights) or 1.0
        cursor = 0.0
        _log(log_callback, f"[voice upload] Splitting complete narration ({total:.2f}s) across {len(beats)} script beats")
        for i, w in enumerate(weights):
            dur = max(0.05, total - cursor) if i == len(weights) - 1 else total * w / total_w
            run([
                "ffmpeg", "-y", "-ss", f"{cursor:.4f}", "-i", src,
                "-t", f"{dur:.4f}", "-vn",
                "-c:a", "libmp3lame", "-b:a", "160k", raw_paths[i],
            ])
            cursor += dur

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"fingerprint": upload_fp, "files": paths}, f, indent=2, ensure_ascii=False)
    return upload_fp

# ---------------------------------------------------------------------------
# Cache + build
# ---------------------------------------------------------------------------

def _load_manifest(path: str) -> dict:
    if not os.path.exists(path):
        return {"version": 2, "segments": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"version": 2, "segments": {}}
        data.setdefault("segments", {})
        return data
    except Exception:
        return {"version": 2, "segments": {}}


def _save_manifest(path: str, manifest: dict):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _tts_fp(beat: EditBeat, voice_id: str, model_id: str,
            stability: float, similarity_boost: float) -> str:
    payload = {
        "text": beat.text,
        "voice_id": voice_id,
        "model_id": model_id,
        "stability": round(float(stability), 4),
        "similarity_boost": round(float(similarity_boost), 4),
    }
    return _sha256_text(json.dumps(payload, sort_keys=True, ensure_ascii=False))


def _audio_fp(beat: EditBeat, voice_id: str, model_id: str,
              stability: float, similarity_boost: float, narration_speed: float = 1.0) -> str:
    # Keep speed=1.0 compatible with the V2.2 fingerprint so old caches can migrate.
    payload = {
        "text": beat.text,
        "voice_id": voice_id,
        "model_id": model_id,
        "stability": round(float(stability), 4),
        "similarity_boost": round(float(similarity_boost), 4),
    }
    speed = round(float(narration_speed), 4)
    if abs(speed - 1.0) > 0.0001:
        payload["narration_speed"] = speed
    return _sha256_text(json.dumps(payload, sort_keys=True, ensure_ascii=False))


def _visual_fp(beat: EditBeat, source_video: str, audio_duration: float) -> str:
    stat = os.stat(source_video)
    payload = {
        "shots": [asdict(s) for s in beat.shots],
        "audio_duration": round(audio_duration, 3),
        "video": os.path.abspath(source_video),
        "video_size": stat.st_size,
        "video_mtime_ns": stat.st_mtime_ns,
    }
    return _sha256_text(json.dumps(payload, sort_keys=True, ensure_ascii=False))


def _shot_durations(shots: List[Shot], total: float) -> List[float]:
    if not shots:
        return []
    weights = [max(0.05, s.weight) for s in shots]
    total_w = sum(weights)
    raw = [total * w / total_w for w in weights]
    # For extremely short TTS lines, do not create unusably tiny shots; fewer shots
    # should be supplied in the edit plan. We still clamp to 0.20s and renormalize.
    if total < 0.20 * len(shots):
        return [total / len(shots)] * len(shots)
    clamped = [max(0.20, x) for x in raw]
    scale = total / sum(clamped)
    return [x * scale for x in clamped]


def _output_is_fresh(output_path: str, input_paths: List[str]) -> bool:
    if not _file_nonempty(output_path):
        return False
    try:
        out_mtime = os.path.getmtime(output_path)
        return all(os.path.getmtime(p) <= out_mtime for p in input_paths if os.path.exists(p))
    except OSError:
        return False


def build_project(video_path: str, script_path: str, edit_plan_path: str,
                  voice_id: str = "", tts_model_id: str = "eleven_multilingual_v2", elevenlabs_key: str = "",
                  out_path: str = "final_recap.mp4", cache_dir: Optional[str] = None,
                  logo_path: Optional[str] = None,
                  logo_position: str = "Top-Right", logo_x_offset: int = 24, logo_y_offset: int = 24,
                  bgm_path: Optional[str] = None, bgm_volume: float = 0.10,
                  bgm_loop: bool = True, voice_volume: float = 1.0, stability: float = 0.5,
                  similarity_boost: float = 0.75, narration_speed: float = 1.05,
                  render_preset: str = "fast", log_callback: LogFn = None,
                  bgm_paths: Optional[List[str]] = None,
                  voiceover_mode: str = "generate", uploaded_voiceover_paths: Optional[List[str]] = None,
                  max_tts_workers: int = 3,
                  render_mode: str = "video", intro_video_paths: Optional[List[str]] = None,
                  target_movie_duration_seconds: float = 3600.0,
                  enable_logo: bool = True, enable_captions: bool = True, enable_bgm: bool = True,
                  caption_font: str = "Impact", caption_preset: str = "CapCut Yellow Pop",
                  caption_size: int = 28, caption_position: str = "Bottom-Center",
                  caption_case: str = "ALL CAPS", caption_words_per_line: Union[int, str] = 10,
                  custom_font_path: Optional[str] = None,
                  logo_width: int = 200, custom_logo_x: Optional[int] = None, custom_logo_y: Optional[int] = None):
    ff = check_ffmpeg()
    if not all(ff.values()):
        raise RuntimeError("ffmpeg/ffprobe not found in PATH. Install FFmpeg first.")

    validation = validate_plan_against_script(edit_plan_path, script_path)
    if not validation["same_count"]:
        raise ValueError(f"Edit-plan segment count ({validation['segments']}) must match rewritten-script line count ({validation['script_lines']}).")
    if not validation["strict_ok"]:
        details = []
        if validation["missing_character_intros"]:
            details.append("missing character intros: " + ", ".join(validation["missing_character_intros"]))
        if details:
            raise ValueError("Professional edit-plan validation failed: " + "; ".join(details))
        if validation["gap_violations"]:
            _log(log_callback, f"[director notice] {len(validation['gap_violations'])} source-gap item(s)")
        if validation["repeat_violations"]:
            _log(log_callback, f"[director notice] {len(validation['repeat_violations'])} repeated-source item(s)")
    beats = load_edit_plan(edit_plan_path, script_path)
    rules = load_plan_rules(edit_plan_path)
    voiceover_mode = (voiceover_mode or "generate").strip().lower()
    if voiceover_mode not in {"generate", "upload"}:
        raise ValueError("voiceover_mode must be 'generate' or 'upload'.")
    if voiceover_mode == "generate":
        if not elevenlabs_key:
            raise ValueError("API key is required when Generate Voiceover is selected.")
        if not voice_id:
            raise ValueError("Voice ID is required when Generate Voiceover is selected.")
    elif not uploaded_voiceover_paths:
        raise ValueError("Choose uploaded narration audio when Upload Voiceover is selected.")
    profile = get_video_profile(video_path)
    render_preset = (render_preset or "fast").lower().strip()
    if render_preset not in {"medium", "fast", "veryfast"}:
        render_preset = "fast"
    narration_speed = max(0.80, min(1.30, float(narration_speed)))
    _log(log_callback, f"[quality] Preserving source canvas {profile['width']}x{profile['height']} @ {profile['fps']:.3f} fps • CRF 18 • x264 {render_preset}")
    _log(log_callback, f"[voice] Narration speed {narration_speed:.2f}x (local FFmpeg speed; raw TTS cache preserved)")
    _log(log_callback, f"[director] min source gap={rules['min_source_gap_seconds']:.1f}s • max moving clip={rules['max_moving_clip_seconds']:.1f}s • no-repeat=on")
    if rules["required_character_intros"]:
        _log(log_callback, "[director] Character intros locked: " + ", ".join(rules["required_character_intros"]))

    out_abs = os.path.abspath(out_path)
    base_dir = os.path.dirname(out_abs)
    base_name = os.path.splitext(os.path.basename(out_abs))[0]
    cache_dir = os.path.abspath(cache_dir) if cache_dir and cache_dir.strip() else os.path.join(base_dir, f".{base_name}_recap_cache")
    audio_dir = os.path.join(cache_dir, "audio")
    visual_dir = os.path.join(cache_dir, "visuals")
    shot_dir = os.path.join(cache_dir, "shots")
    segment_dir = os.path.join(cache_dir, "segments")
    workdir = os.path.join(cache_dir, "workdir")
    manifest_path = os.path.join(cache_dir, "manifest.json")
    for d in (cache_dir, audio_dir, visual_dir, shot_dir, segment_dir, workdir):
        os.makedirs(d, exist_ok=True)

    # 1. Smart Script Content Cache Invalidation
    script_raw_content = ""
    if os.path.exists(script_path):
        with open(script_path, "r", encoding="utf-8", errors="ignore") as sf:
            script_raw_content = sf.read().strip()

    script_fingerprint = _sha256_text(f"{script_raw_content}_{voice_id}_{tts_model_id}_{narration_speed}")
    cache_meta_path = os.path.join(cache_dir, "script_cache_meta.json")

    if os.path.exists(cache_meta_path):
        try:
            with open(cache_meta_path, "r", encoding="utf-8") as cmf:
                prev_meta = json.load(cmf)
                if prev_meta.get("script_fingerprint") != script_fingerprint:
                    _log(log_callback, "[cache] Script content or voice parameters changed — invalidating stale audio cache.")
                    for f in os.listdir(audio_dir):
                        if f.startswith("tts_raw_") or f.startswith("narration_") or f.startswith("segment_"):
                            try: os.remove(os.path.join(audio_dir, f))
                            except Exception: pass
        except Exception:
            pass

    with open(cache_meta_path, "w", encoding="utf-8") as cmf:
        json.dump({"script_fingerprint": script_fingerprint, "script_path": script_path, "voice_id": voice_id}, cmf, indent=2)

    uploaded_voice_fp = ""
    if voiceover_mode == "upload":
        uploaded_voice_fp = prepare_uploaded_voiceover_segments(
            uploaded_voiceover_paths or [], beats, audio_dir, log_callback=log_callback
        )
        _log(log_callback, "[voice] Using uploaded voiceover — TTS generation skipped")
    else:
        _log(log_callback, f"[voice] Generate Voiceover mode — AI33 Parallel TTS enabled (up to {max_tts_workers} workers)")

    manifest_path = os.path.join(workdir, "cache_manifest.json")
    manifest = _load_manifest(manifest_path)
    _log(log_callback, f"[project] Cache: {workdir}")
    _log(log_callback, f"[project] {len(beats)} narration beats / {sum(len(b.shots) for b in beats)} shots")

    # -------------------------------------------------------------------------
    # Parallel TTS Audio Generation (up to max_tts_workers requests in parallel)
    # -------------------------------------------------------------------------
    if voiceover_mode == "generate":
        tts_tasks = []
        for i, beat in enumerate(beats):
            raw_audio_path = os.path.join(audio_dir, f"tts_raw_{i:04d}.mp3")
            if not _file_nonempty(raw_audio_path):
                tts_tasks.append((i, beat, raw_audio_path))

        if tts_tasks:
            _log(log_callback, f"[parallel-tts] Generating {len(tts_tasks)} audio beats in parallel ({max_tts_workers} workers)...")
            def _gen_job(idx, b, r_path):
                if idx > 0:
                    time.sleep(min(1.0, (idx % max(1, max_tts_workers)) * 0.12))
                generate_tts(b.text, voice_id, tts_model_id, elevenlabs_key, r_path,
                             stability=stability, similarity_boost=similarity_boost,
                             log_callback=log_callback)
                return idx

            with ThreadPoolExecutor(max_workers=max_tts_workers) as executor:
                futures = {executor.submit(_gen_job, idx, b, r_path): (idx, b) for idx, b, r_path in tts_tasks}
                for future in as_completed(futures):
                    idx, b = futures[future]
                    try:
                        future.result()
                        _log(log_callback, f"   ✓ TTS audio generated for line {b.line_no}: {b.text[:50]}...")
                    except Exception as exc:
                        _log(log_callback, f"   ✗ TTS audio failed for line {b.line_no}: {exc}")
                        raise exc

    segment_paths: List[str] = []
    for i, beat in enumerate(beats):
        num = i + 1
        key = str(i)
        old = manifest["segments"].get(key, {})
        audio_path = os.path.join(audio_dir, f"audio_{i:04d}.mp3")
        visual_path = os.path.join(visual_dir, f"visual_{i:04d}.mp4")
        final_seg = os.path.join(segment_dir, f"segment_{i:04d}.mp4")

        raw_audio_path = os.path.join(audio_dir, f"tts_raw_{i:04d}.mp3")
        if voiceover_mode == "upload":
            tfp = _sha256_text(json.dumps({
                "mode": "upload", "upload_fp": uploaded_voice_fp, "line": beat.line_no, "text": beat.text
            }, sort_keys=True, ensure_ascii=False))
            afp = _sha256_text(json.dumps({
                "tts_fp": tfp, "narration_speed": round(float(narration_speed), 4)
            }, sort_keys=True, ensure_ascii=False))
        else:
            tfp = _tts_fp(beat, voice_id, tts_model_id, stability, similarity_boost)
            afp = _audio_fp(beat, voice_id, tts_model_id, stability, similarity_boost, narration_speed)

        if not _file_nonempty(raw_audio_path):
            if voiceover_mode == "upload":
                raise RuntimeError(f"Prepared uploaded narration segment missing for line {beat.line_no}: {raw_audio_path}")
            _log(log_callback, f"[tts] {num}/{len(beats)} line {beat.line_no}: {beat.text[:72]}")
            generate_tts(beat.text, voice_id, tts_model_id, elevenlabs_key, raw_audio_path,
                         stability=stability, similarity_boost=similarity_boost,
                         log_callback=log_callback)

        if old.get("audio_fp") != afp:
            for p in (audio_path, visual_path, final_seg):
                try:
                    if os.path.exists(p): os.remove(p)
                except OSError:
                    pass
            old.update({"tts_fp": tfp, "audio_fp": afp, "state": "audio_speed_pending"})
            manifest["segments"][key] = old
            _save_manifest(manifest_path, manifest)

        if not _file_nonempty(audio_path):
            apply_narration_speed(raw_audio_path, audio_path, narration_speed)
            if abs(narration_speed - 1.0) > 0.001:
                _log(log_callback, f"[voice] {num}/{len(beats)} local speed applied: {narration_speed:.2f}x")
        else:
            _log(log_callback, f"[cache] {num}/{len(beats)} narration audio reused")
        audio_duration = get_duration(audio_path)

        vfp = _visual_fp(beat, video_path, audio_duration)
        if old.get("visual_fp") != vfp:
            for p in (visual_path, final_seg):
                try:
                    if os.path.exists(p): os.remove(p)
                except OSError:
                    pass
            old.update({"audio_fp": afp, "visual_fp": vfp, "state": "visual_pending"})
            manifest["segments"][key] = old
            _save_manifest(manifest_path, manifest)

        if not _file_nonempty(visual_path):
            durations = _shot_durations(beat.shots, audio_duration)
            shot_paths: List[str] = []
            _log(log_callback, f"[visual] {num}/{len(beats)} rendering {len(beat.shots)} shot(s) for {audio_duration:.2f}s narration")
            for j, (shot, shot_duration) in enumerate(zip(beat.shots, durations)):
                shot_path = os.path.join(shot_dir, f"beat_{i:04d}_shot_{j:02d}_{vfp[:10]}.mp4")
                if not _file_nonempty(shot_path):
                    _log(log_callback,
                         f"   shot {j+1}: {shot.mode} {shot.source_start:.2f}-{shot.source_end:.2f}s "
                         f"→ {shot_duration:.2f}s zoom={shot.zoom:.2f} flip={'Y' if shot.flip else 'N'}")
                    if shot.mode == "freeze":
                        build_freeze_shot(video_path, shot, shot_duration, shot_path, profile, render_preset)
                    else:
                        build_clip_shot(video_path, shot, shot_duration, shot_path, profile, rules["max_moving_clip_seconds"], render_preset)
                else:
                    _log(log_callback, f"   shot {j+1}: cached")
                shot_paths.append(shot_path)
            concat_video_only(shot_paths, visual_path, workdir, f"beat_{i:04d}", render_preset)
        else:
            _log(log_callback, f"[cache] {num}/{len(beats)} visual reused")

        if not _file_nonempty(final_seg):
            mux_audio(visual_path, audio_path, final_seg)
        else:
            _log(log_callback, f"[cache] {num}/{len(beats)} completed segment reused")

        manifest["segments"][key] = {
            "tts_fp": tfp,
            "audio_fp": afp,
            "visual_fp": vfp,
            "text": beat.text,
            "line": beat.line_no,
            "duration": audio_duration,
            "state": "complete",
        }
        _save_manifest(manifest_path, manifest)
        segment_paths.append(final_seg)

    concat_out = os.path.join(workdir, "concat_narration.mp4")
    if _output_is_fresh(concat_out, segment_paths):
        _log(log_callback, "[cache] Final narration concat reused")
    else:
        _log(log_callback, "[final] Concatenating narration beats...")
        concat_video_only(segment_paths, concat_out, workdir, "final", render_preset)

    current = concat_out
    watermark_out = os.path.join(workdir, "with_watermark.mp4")
    if enable_logo and logo_path and os.path.exists(logo_path):
        wm_inputs = [current, logo_path]
        if _output_is_fresh(watermark_out, wm_inputs):
            _log(log_callback, "[cache] Watermarked video reused (100% complete)")
        else:
            _log(log_callback, f"[final] [0%] Adding logo watermark ({logo_position}, width={logo_width}px)...")
            add_watermark(current, logo_path, watermark_out, render_preset,
                          position=logo_position, x_offset=logo_x_offset, y_offset=logo_y_offset,
                          logo_width=logo_width, custom_x=custom_logo_x, custom_y=custom_logo_y)
            _log(log_callback, f"[final] [100%] Logo watermark applied successfully ✓")
        current = watermark_out

    # CapCut Subtitles / Captions Burning
    caption_out = os.path.join(workdir, "with_captions.mp4")
    if enable_captions:
        ass_path = os.path.join(workdir, "capcut_captions.ass")
        seg_durations = [get_duration(p) for p in segment_paths]
        _log(log_callback, f"[final] [10%] Generating CapCut ASS subtitles ({caption_case}, max {caption_words_per_line} words/line)...")
        generate_capcut_ass_file(beats, seg_durations, ass_path,
                                font_name=caption_font, font_size=caption_size,
                                preset_style=caption_preset, position=caption_position,
                                text_case=caption_case, max_words_per_line=caption_words_per_line,
                                custom_font_path=custom_font_path)
        if _output_is_fresh(caption_out, [current, ass_path]):
            _log(log_callback, "[cache] CapCut captions video reused (100% complete)")
        else:
            _log(log_callback, f"[final] [50%] Burning CapCut captions ({caption_preset}, {caption_font} {caption_size}pt)...")
            burn_subtitles(current, ass_path, caption_out, render_preset, custom_font_path=custom_font_path)
            _log(log_callback, f"[final] [100%] CapCut captions burned successfully ✓")
        current = caption_out

    selected_bgm = []
    if enable_bgm:
        selected_bgm = [p for p in (bgm_paths or []) if p]
        if not selected_bgm and bgm_path:
            selected_bgm = [bgm_path]

    recap_final = out_abs
    if render_mode == "movie":
        recap_final = os.path.join(workdir, "recap_base.mp4")

    if selected_bgm:
        if len(selected_bgm) > 1:
            playlist_audio = os.path.join(workdir, "bgm_playlist.m4a")
            bgm_source = prepare_bgm_playlist(selected_bgm, playlist_audio, log_callback=log_callback)
            _log(log_callback, f"[final] BGM playlist: {len(selected_bgm)} tracks • {'loop to video end' if bgm_loop else 'play once'}")
        else:
            bgm_source = selected_bgm[0]
            _log(log_callback, f"[final] BGM single track • {'loop to video end' if bgm_loop else 'play once'}")
        _log(log_callback, f"[final] Mixing narration={voice_volume:.0%} BGM={bgm_volume:.0%}")
        mix_bgm(current, bgm_source, recap_final, bgm_volume, bgm_loop, voice_volume=voice_volume)
    else:
        if abs(float(voice_volume) - 1.0) >= 0.001:
            _log(log_callback, f"[final] Applying narration volume={voice_volume:.0%}")
            apply_video_audio_volume(current, recap_final, voice_volume)
        else:
            shutil.copy2(current, recap_final)

    # -------------------------------------------------------------------------
    # Render Movie Option (Intros + Looping Recap to target duration)
    # -------------------------------------------------------------------------
    if render_mode == "movie":
        _log(log_callback, f"[movie] Building Recap Movie with target duration {target_movie_duration_seconds/3600:.2f}h...")
        build_movie(
            recap_video_path=recap_final,
            intro_video_paths=intro_video_paths or [],
            target_duration_seconds=target_movie_duration_seconds,
            out_movie_path=out_abs,
            workdir=workdir,
            render_preset=render_preset,
            log_callback=log_callback,
        )

    _log(log_callback, f"[done] Final video/movie created: {out_abs}")
    return out_abs


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Recap Studio V2.8 engine")
    p.add_argument("--video", required=True)
    p.add_argument("--script", required=True)
    p.add_argument("--plan", required=True)
    p.add_argument("--voice-id", default="")
    p.add_argument("--voiceover-mode", choices=["generate", "upload"], default="generate")
    p.add_argument("--voiceover-audio", action="append", default=[], help="Repeat for line-by-line narration files")
    p.add_argument("--model-id", default="eleven_multilingual_v2")
    p.add_argument("--elevenlabs-key", default=os.getenv("ELEVENLABS_API_KEY"))
    p.add_argument("--out", required=True)
    p.add_argument("--cache-dir")
    p.add_argument("--logo")
    p.add_argument("--bgm")
    p.add_argument("--bgm-volume", type=float, default=0.10)
    p.add_argument("--voice-volume", type=float, default=1.0)
    p.add_argument("--no-bgm-loop", action="store_true")
    p.add_argument("--narration-speed", type=float, default=1.05)
    p.add_argument("--render-preset", choices=["medium", "fast", "veryfast"], default="fast")
    a = p.parse_args()
    if a.voiceover_mode == "generate" and not a.elevenlabs_key:
        raise SystemExit("ELEVENLABS_API_KEY missing for Generate Voiceover mode")
    build_project(a.video, a.script, a.plan, a.voice_id, a.model_id,
                  a.elevenlabs_key or "", a.out, a.cache_dir, a.logo, a.bgm,
                  a.bgm_volume, not a.no_bgm_loop, voice_volume=a.voice_volume, narration_speed=a.narration_speed,
                  render_preset=a.render_preset, voiceover_mode=a.voiceover_mode,
                  uploaded_voiceover_paths=a.voiceover_audio)
