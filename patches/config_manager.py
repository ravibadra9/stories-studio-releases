"""
config_manager.py — Configuration & Settings Manager for Suno Music Tool
"""

import json
import os
from pathlib import Path

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

def load_config() -> dict:
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Merge with defaults for missing keys
            for k, v in DEFAULT_SETTINGS.items():
                if k not in data:
                    data[k] = v
            return data
    except Exception:
        return DEFAULT_SETTINGS.copy()

def save_config(config_data: dict) -> bool:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[CONFIG] Save error: {e}")
        return False
