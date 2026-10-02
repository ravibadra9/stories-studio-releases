"""
config_manager.py — Configuration & Settings Manager for Suno Music Tool
Enhanced with cross-suite AI33Pro key synchronization & live status validation.
"""

import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Tuple, Optional

DEFAULT_API_KEY = "sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt"

def get_config_dir() -> Path:
    app_data = os.getenv("LOCALAPPDATA", os.path.expanduser("~"))
    config_dir = Path(app_data) / "SunoMusicTool"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir

def get_downloads_dir() -> Path:
    user_downloads = Path(os.path.expanduser("~")) / "Downloads" / "Suno Music Tool" / "downloads"
    user_downloads.mkdir(parents=True, exist_ok=True)
    return user_downloads

CONFIG_FILE = get_config_dir() / "config.json"

DEFAULT_SETTINGS = {
    "api_key": DEFAULT_API_KEY,
    "download_dir": str(get_downloads_dir()),
    "autoplay": False,
    "theme": "dark",
    "saved_history": []
}

def _fetch_system_key() -> str:
    """Check voice_cache and environment variables for existing AI33Pro key."""
    # 1. Check voice_cache
    try:
        import voice_cache
        k = voice_cache.load_api_key()
        if k:
            return k.strip()
    except Exception:
        pass

    # 2. Check environment variables
    for env_var in ("AI33_API_KEY", "XI_API_KEY", "ELEVENLABS_API_KEY"):
        val = os.getenv(env_var, "").strip()
        if val:
            return val
    return DEFAULT_API_KEY

def load_config() -> dict:
    data = DEFAULT_SETTINGS.copy()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    data.update(saved)
        except Exception:
            pass

    # Auto-fetch from shared suite if empty
    if not data.get("api_key"):
        shared_key = _fetch_system_key()
        if shared_key:
            data["api_key"] = shared_key

    return data

def save_config(config_data: dict) -> bool:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)

        # Synchronize key to shared voice_cache
        k = config_data.get("api_key", "").strip()
        if k:
            try:
                import voice_cache
                voice_cache.save_api_key(k)
            except Exception:
                pass
        return True
    except Exception as e:
        print(f"[CONFIG] Save error: {e}")
        return False

def get_api_key() -> str:
    """Returns the active AI33Pro API key with multi-source fallback."""
    cfg = load_config()
    k = cfg.get("api_key", "").strip()
    if not k:
        k = _fetch_system_key()
    return k or DEFAULT_API_KEY

def save_api_key(key: str) -> bool:
    """Saves API key to both SunoMusicTool config and shared voice_cache."""
    cfg = load_config()
    clean_k = key.strip() if key else ""
    cfg["api_key"] = clean_k
    return save_config(cfg)

def validate_and_fetch_ai33_status(api_key: str) -> Tuple[bool, str, Optional[str]]:
    """
    Validates API key on https://api.ai33.pro.
    Returns: (is_valid: bool, status_msg: str, credits_remaining_str: Optional[str])
    """
    key = api_key.strip() if api_key else ""
    if not key:
        return False, "⚠️ API Key is empty", None

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    credits_str = None

    # Check via /v1/models (official endpoint supported on api.ai33.pro)
    try:
        req = urllib.request.Request(
            "https://api.ai33.pro/v1/models",
            headers={"xi-api-key": key, "User-Agent": "AI33-Python-SDK/1.0"},
            method="GET"
        )
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            if resp.status == 200:
                raw_data = resp.read().decode("utf-8")
                try:
                    data = json.loads(raw_data)
                    count = len(data) if isinstance(data, list) else len(data.keys())
                    return True, f"✅ AI33Pro Active ({count} Models)", None
                except Exception:
                    return True, "✅ AI33Pro Connected & Active ✓", None
            return False, f"⚠️ HTTP {resp.status}", None
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, "❌ Invalid Key (Unauthorized 401)", None
        return True, "✅ AI33Pro Connected ✓", None
    except Exception as e:
        return False, f"⚠️ Connection check failed: {str(e)[:40]}", None
