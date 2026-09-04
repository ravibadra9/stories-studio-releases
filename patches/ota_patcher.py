"""
ota_patcher.py — Over-The-Air (OTA) Hot-Patching Engine for StoriesStudio / AI Editor

Enables real-time module updates without rebuilding or reinstalling the full .exe.
How it works:
1. Hot-patch directory (%LOCALAPPDATA%\\StoriesStudio\\hot_patches) is prepended to sys.path at startup.
2. When Python imports any module (e.g. story_image_engine, tabs.14_youtube_data_fetcher),
   it prioritizes the fresh hot-patched .py file over the bundled/frozen copy inside _MEIPASS.
3. Automatically downloads, syntax-verifies, and stages patches from the cloud manifest.
"""

import os
import sys
import json
import hashlib
import shutil
import tempfile
import threading
import importlib
from typing import Dict, Any, List, Optional, Tuple, Callable

# ── Paths & Constants ────────────────────────────────────────────────────────
_APPDATA = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or os.path.expanduser("~")
DATA_ROOT = os.path.join(_APPDATA, "StoriesStudio")
HOT_PATCH_DIR = os.path.join(DATA_ROOT, "hot_patches")
PATCH_INFO_FILE = os.path.join(HOT_PATCH_DIR, "patch_status.json")

# Default cloud manifest URL (GitHub Raw / Releases / Custom Server)
DEFAULT_MANIFEST_URL = "https://raw.githubusercontent.com/ravibadra9/stories-studio-releases/main/hot_patch_manifest.json"

_patch_lock = threading.Lock()
_active_patch_info: Dict[str, Any] = {}


def setup_hot_patch_path():
    """
    Mount the hot_patches directory at the very beginning of sys.path.
    Must be called at startup in main.py before other application modules are imported.
    """
    try:
        os.makedirs(HOT_PATCH_DIR, exist_ok=True)
        tabs_patch_dir = os.path.join(HOT_PATCH_DIR, "tabs")
        os.makedirs(tabs_patch_dir, exist_ok=True)

        # Ensure hot_patches directory is at index 0 of sys.path
        if HOT_PATCH_DIR not in sys.path:
            sys.path.insert(0, HOT_PATCH_DIR)

        _load_active_patch_info()
    except Exception as e:
        print(f"[OTA] ⚠️ Failed to initialize hot patch path: {e}")


def _load_active_patch_info() -> Dict[str, Any]:
    global _active_patch_info
    try:
        if os.path.exists(PATCH_INFO_FILE):
            with open(PATCH_INFO_FILE, "r", encoding="utf-8") as f:
                _active_patch_info = json.load(f)
                return _active_patch_info
    except Exception:
        pass
    _active_patch_info = {"version": "0.0.0", "installed_patches": []}
    return _active_patch_info


def get_active_patch_info() -> Dict[str, Any]:
    """Return dictionary of currently installed hot patches and active patch version."""
    return _active_patch_info or _load_active_patch_info()


def verify_python_syntax(file_path: str) -> Tuple[bool, str]:
    """Verify that a Python file has valid syntax before activating it."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            code = f.read()
        compile(code, file_path, "exec")
        return True, ""
    except Exception as e:
        return False, str(e)


def apply_patch_payload(relative_path: str, code_content: str, log_fn: Optional[Callable[[str], None]] = None) -> bool:
    """
    Apply a single module patch from string content into the hot_patches directory.
    Validates syntax before saving.
    """
    with _patch_lock:
        try:
            target_path = os.path.join(HOT_PATCH_DIR, relative_path)
            os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)

            # 1. Write to temporary staging file
            temp_fd, temp_path = tempfile.mkstemp(suffix=".py", prefix="patch_stage_")
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                f.write(code_content)

            # 2. Verify syntax
            valid, err = verify_python_syntax(temp_path)
            if not valid:
                try: os.remove(temp_path)
                except Exception: pass
                if log_fn:
                    log_fn(f"[OTA] ❌ Syntax verification failed for {relative_path}: {err}")
                return False

            # 3. Atomically replace target
            shutil.move(temp_path, target_path)

            if log_fn:
                log_fn(f"[OTA] ⚡ Successfully activated patch: {relative_path}")
            return True
        except Exception as e:
            if log_fn:
                log_fn(f"[OTA] ❌ Error applying patch {relative_path}: {e}")
            return False


def check_and_apply_cloud_patches(
    manifest_url: Optional[str] = None,
    log_fn: Optional[Callable[[str], None]] = None,
    progress_fn: Optional[Callable[[float, str, str], None]] = None,
    timeout: int = 4
) -> Dict[str, Any]:
    """
    Check remote manifest, download new/updated script files, verify syntax, and apply.
    Returns result dict with status, patch_version, applied_files, and restart_needed.
    Supports real-time progress callbacks for boot screen animation.
    """
    url = manifest_url or DEFAULT_MANIFEST_URL
    result = {
        "success": False,
        "new_patch_applied": False,
        "patch_version": "0.0.0",
        "applied_files": [],
        "message": "",
    }

    try:
        import requests
        from auth_manager import FIREBASE_URL, FIREBASE_SECRET

        if log_fn:
            log_fn(f"[OTA] 🔍 Checking for hot patches at remote manifest...")
        if progress_fn:
            progress_fn(22.0, "🔍 Checking Cloud Auto-Updates & Hot-Patches...", "Connecting to remote manifest...")

        manifest = None
        # 1. Try Firebase Realtime DB first (fastest, 100% reliable)
        try:
            fb_url = f"{FIREBASE_URL}/hot_patch.json?auth={FIREBASE_SECRET}"
            fb_resp = requests.get(fb_url, timeout=timeout)
            if fb_resp.status_code == 200 and fb_resp.json():
                manifest = fb_resp.json()
        except Exception:
            pass

        # 2. Fallback to manifest URL
        if not manifest:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 200 and resp.json():
                manifest = resp.json()

        if not manifest:
            result["message"] = "No pending hot patches found."
            if progress_fn:
                progress_fn(28.0, "✓ Cloud Hot-Patches Verified", "No pending remote updates")
            return result
        patch_ver = manifest.get("patch_version", "0.0.0")
        files_to_patch = manifest.get("files", [])

        current_info = get_active_patch_info()
        current_ver = current_info.get("version", "0.0.0")

        if patch_ver == current_ver and current_info.get("installed_patches"):
            result["success"] = True
            result["message"] = f"Hot patches up to date (v{current_ver})"
            if progress_fn:
                progress_fn(28.0, f"✓ Cloud Hot-Patches Up-To-Date (v{current_ver})", f"{len(current_info.get('installed_patches', []))} hot-patch module(s) active")
            return result

        if not files_to_patch:
            result["success"] = True
            result["message"] = "No hot patch files specified in manifest."
            if progress_fn:
                progress_fn(28.0, "✓ Core Engine Up-To-Date", "Running latest cloud release")
            return result

        applied = []
        total_files = len(files_to_patch)
        for idx, item in enumerate(files_to_patch):
            rel_path = item.get("path")
            file_url = item.get("url")
            file_code = item.get("content")

            if not rel_path:
                continue

            pct_step = 22.0 + ((idx + 0.5) / max(1, total_files)) * 8.0
            if progress_fn:
                progress_fn(pct_step, f"⚡ Downloading Auto-Update: {rel_path}", f"Patch v{patch_ver} • [{idx+1}/{total_files}]")

            # Fetch content if URL provided
            if not file_code and file_url:
                f_resp = requests.get(file_url, timeout=timeout)
                if f_resp.status_code == 200:
                    file_code = f_resp.text

            if file_code:
                ok = apply_patch_payload(rel_path, file_code, log_fn=log_fn)
                if ok:
                    applied.append(rel_path)
                    pct_done = 22.0 + ((idx + 1) / max(1, total_files)) * 8.0
                    if progress_fn:
                        progress_fn(pct_done, f"✓ Applied Auto-Update: {rel_path}", f"Patch v{patch_ver} active")

        broadcast_data = manifest.get("broadcast")
        if broadcast_data and isinstance(broadcast_data, dict):
            result["broadcast"] = broadcast_data

        if applied:
            # Update local patch status
            new_status = {
                "version": patch_ver,
                "notes": manifest.get("notes", ""),
                "installed_patches": applied,
                "updated_at": manifest.get("timestamp", ""),
                "last_seen_broadcast_id": current_info.get("last_seen_broadcast_id", ""),
            }
            if broadcast_data:
                new_status["broadcast"] = broadcast_data

            with open(PATCH_INFO_FILE, "w", encoding="utf-8") as f:
                json.dump(new_status, f, indent=2)

            global _active_patch_info
            _active_patch_info = new_status

            result["success"] = True
            result["new_patch_applied"] = True
            result["patch_version"] = patch_ver
            result["applied_files"] = applied
            result["message"] = f"⚡ Successfully applied {len(applied)} hot-patch file(s) (v{patch_ver})!"

            if progress_fn:
                progress_fn(30.0, f"🎉 AUTO-UPDATE APPLIED: v{patch_ver} ✓", f"Updated {len(applied)} file(s): {', '.join(applied[:2])}")
            if log_fn:
                log_fn(f"[OTA] 🎉 Hot-Patch v{patch_ver} applied ({', '.join(applied)})")
        elif broadcast_data:
            result["success"] = True
            if progress_fn:
                progress_fn(28.0, "✓ Cloud Broadcast Received", "")
        else:
            result["message"] = "No patches could be applied."
            if progress_fn:
                progress_fn(28.0, "✓ Cloud Check Finished", "No pending updates")

        return result

    except Exception as e:
        result["message"] = str(e)
        if progress_fn:
            progress_fn(28.0, "✓ Offline Mode Active", "Using local bundled modules")
        if log_fn:
            log_fn(f"[OTA] ⚠️ Patch check failed: {e}")
        return result


def rollback_all_patches(log_fn: Optional[Callable[[str], None]] = None) -> bool:
    """Clear all applied hot patches and restore to default base installation."""
    with _patch_lock:
        try:
            if os.path.exists(HOT_PATCH_DIR):
                shutil.rmtree(HOT_PATCH_DIR, ignore_errors=True)
            setup_hot_patch_path()
            if log_fn:
                log_fn("[OTA] 🔄 All hot patches removed. Reverted to base installation.")
            return True
        except Exception as e:
            if log_fn:
                log_fn(f"[OTA] ❌ Rollback error: {e}")
            return False


def get_pending_broadcast() -> Optional[Dict[str, Any]]:
    """Return broadcast message if not yet dismissed by user."""
    info = get_active_patch_info()
    broadcast = info.get("broadcast")
    if broadcast and isinstance(broadcast, dict):
        b_id = broadcast.get("id") or broadcast.get("title")
        last_seen = info.get("last_seen_broadcast_id")
        if b_id and b_id != last_seen:
            return broadcast
    return None


def mark_broadcast_seen(broadcast_id: str):
    """Mark broadcast message as seen so it does not pop up repeatedly."""
    with _patch_lock:
        try:
            info = get_active_patch_info()
            info["last_seen_broadcast_id"] = broadcast_id
            with open(PATCH_INFO_FILE, "w", encoding="utf-8") as f:
                json.dump(info, f, indent=2)
            global _active_patch_info
            _active_patch_info = info
        except Exception:
            pass

