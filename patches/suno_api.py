"""
suno_api.py — Suno Music Generation API Client (https://api.ai33.pro)
Handles task creation, task polling, metadata parsing, and file downloading.
"""

import json
import os
import requests
from typing import Dict, Any, Tuple, Optional

BASE_URL = "https://api.ai33.pro"

class SunoAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key.strip()

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "xi-api-key": self.api_key
        }

    def generate_music_simple(
        self,
        prompt: str,
        make_instrumental: bool = False,
        receive_url: Optional[str] = None
    ) -> Tuple[bool, str, Optional[str], Any]:
        """
        Simple Mode Request:
        Returns (success: bool, task_id_or_error: str, credits_remaining: str, raw_response: dict)
        """
        url = f"{BASE_URL}/v1s/task/music-generation"
        payload = {
            "create_mode": "simple",
            "gpt_description_prompt": prompt,
            "make_instrumental": make_instrumental
        }
        if receive_url:
            payload["receive_url"] = receive_url

        try:
            res = requests.post(url, headers=self._get_headers(), json=payload, timeout=20)
            data = res.json()
            if res.status_code == 200 and data.get("success"):
                task_id = data.get("task_id", "")
                credits = str(data.get("ec_remain_credits", ""))
                return True, task_id, credits, data
            else:
                err = data.get("message") or data.get("error") or res.text or "Unknown error"
                return False, f"API Error: {err}", None, data
        except Exception as e:
            return False, f"Connection Failed: {str(e)}", None, None

    def generate_music_custom(
        self,
        title: str = "",
        lyrics: str = "",
        tags: str = "",
        vocal_gender: str = "auto",
        receive_url: Optional[str] = None
    ) -> Tuple[bool, str, Optional[str], Any]:
        """
        Custom Mode Request:
        Returns (success: bool, task_id_or_error: str, credits_remaining: str, raw_response: dict)
        """
        url = f"{BASE_URL}/v1s/task/music-generation"
        payload = {
            "create_mode": "custom"
        }
        if title and title.strip():
            payload["title"] = title.strip()
        if lyrics and lyrics.strip():
            payload["lyrics"] = lyrics.strip()
        if tags and tags.strip():
            payload["tags"] = tags.strip()
        if vocal_gender in ("f", "m"):
            payload["vocal_gender"] = vocal_gender
        if receive_url:
            payload["receive_url"] = receive_url

        try:
            res = requests.post(url, headers=self._get_headers(), json=payload, timeout=20)
            data = res.json()
            if res.status_code == 200 and data.get("success"):
                task_id = data.get("task_id", "")
                credits = str(data.get("ec_remain_credits", ""))
                return True, task_id, credits, data
            else:
                err = data.get("message") or data.get("error") or res.text or "Unknown error"
                return False, f"API Error: {err}", None, data
        except Exception as e:
            return False, f"Connection Failed: {str(e)}", None, None

    def get_task_status(self, task_id: str) -> Tuple[str, int, Dict[str, Any], Optional[str]]:
        """
        Poll task status by task_id.
        Returns: (status: str ["processing", "done", "error"], progress: int, metadata: dict, error_message: str)
        """
        url = f"{BASE_URL}/v1/task/{task_id}"
        try:
            res = requests.get(url, headers=self._get_headers(), timeout=15)
            data = res.json()
            if res.status_code == 200:
                status = data.get("status", "processing")
                progress = int(data.get("progress", 0))
                metadata = data.get("metadata", {})
                error_msg = data.get("error_message")
                return status, progress, metadata, error_msg
            else:
                return "error", 0, {}, f"HTTP {res.status_code}: {res.text}"
        except Exception as e:
            return "processing", 0, {}, f"Network error during poll: {e}"

    @staticmethod
    def download_file(url: str, dest_path: str) -> bool:
        """Download remote audio/image file to local path."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
            resp = requests.get(url, stream=True, timeout=30)
            if resp.status_code == 200:
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                return True
            return False
        except Exception as e:
            print(f"[DOWNLOAD ERROR] {e}")
            return False
