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


import importlib.abc
import importlib.machinery
import importlib.util

class HotPatchMetaFinder(importlib.abc.MetaPathFinder):
    """
    Guarantees that hot-patched .py files in HOT_PATCH_DIR always take precedence
    over PyInstaller's FrozenImporter and bundled PYZ modules.
    """
    def find_spec(self, fullname, path, target=None):
        try:
            rel_parts = fullname.split(".")
            candidate_file = os.path.join(HOT_PATCH_DIR, *rel_parts) + ".py"
            if os.path.isfile(candidate_file):
                return importlib.util.spec_from_file_location(fullname, candidate_file)
            
            candidate_pkg = os.path.join(HOT_PATCH_DIR, *rel_parts, "__init__.py")
            if os.path.isfile(candidate_pkg):
                return importlib.util.spec_from_file_location(fullname, candidate_pkg)
        except Exception:
            pass
        return None

_finder_installed = False

def reload_active_patches():
    """Immediately inject all hot-patched modules from disk into sys.modules."""
    if not os.path.exists(HOT_PATCH_DIR):
        return
    for root, _, files in os.walk(HOT_PATCH_DIR):
        for f in files:
            if f.endswith(".py") and not f.startswith("__"):
                full_p = os.path.join(root, f)
                rel_p = os.path.relpath(full_p, HOT_PATCH_DIR)
                mod_name = os.path.splitext(rel_p)[0].replace("\\", ".").replace("/", ".")
                try:
                    spec = importlib.util.spec_from_file_location(mod_name, full_p)
                    if spec and spec.loader:
                        mod = importlib.util.module_from_spec(spec)
                        sys.modules[mod_name] = mod
                        spec.loader.exec_module(mod)
                        print(f"[OTA] Injected hot-patched module: {mod_name}")
                except Exception as e:
                    print(f"[OTA] Error loading {mod_name}: {e}")


def setup_hot_patch_path():
    """
    Mount the hot_patches directory at the very beginning of sys.path and sys.meta_path.
    Must be called at startup in main.py before other application modules are imported.
    """
    global _finder_installed
    try:
        os.makedirs(HOT_PATCH_DIR, exist_ok=True)
        tabs_patch_dir = os.path.join(HOT_PATCH_DIR, "tabs")
        os.makedirs(tabs_patch_dir, exist_ok=True)

        # 1. Ensure MetaPathFinder is installed at index 0 of sys.meta_path (overrides FrozenImporter)
        if not _finder_installed:
            sys.meta_path.insert(0, HotPatchMetaFinder())
            _finder_installed = True

        # 2. Ensure hot_patches directory is at index 0 of sys.path
        if HOT_PATCH_DIR not in sys.path:
            sys.path.insert(0, HOT_PATCH_DIR)

        # 3. Reload active patches into sys.modules
        reload_active_patches()
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


def _safe_log(log_fn, msg):
    if not log_fn:
        return
    try:
        log_fn(msg)
    except Exception:
        try:
            clean = msg.encode("ascii", errors="replace").decode("ascii")
            log_fn(clean)
        except Exception:
            pass


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
                _safe_log(log_fn, f"[OTA] Syntax verification failed for {relative_path}: {err}")
                return False

            # 3. Atomically replace target
            shutil.move(temp_path, target_path)

            _safe_log(log_fn, f"[OTA] Successfully activated patch: {relative_path}")
            return True
        except Exception as e:
            _safe_log(log_fn, f"[OTA] Error applying patch {relative_path}: {e}")
            return False


def check_and_apply_cloud_patches(
    manifest_url: Optional[str] = None,
    log_fn: Optional[Callable[[str], None]] = None,
    timeout: int = 6
) -> Dict[str, Any]:
    """
    Check remote manifest, download new/updated script files, verify syntax, and apply.
    Returns result dict with status, patch_version, applied_files, and restart_needed.
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
        _safe_log(log_fn, "[OTA] Checking for hot patches at remote manifest...")

        resp = requests.get(url, timeout=timeout)
        if resp.status_code != 200:
            result["message"] = f"Manifest HTTP {resp.status_code}"
            return result

        manifest = resp.json()
        patch_ver = manifest.get("patch_version", "0.0.0")
        files_to_patch = manifest.get("files", [])

        current_info = get_active_patch_info()
        current_ver = current_info.get("version", "0.0.0")

        if patch_ver == current_ver and current_info.get("installed_patches"):
            result["success"] = True
            result["message"] = f"Hot patches up to date (v{current_ver})"
            return result

        if not files_to_patch:
            result["success"] = True
            result["message"] = "No hot patch files specified in manifest."
            return result

        applied = []
        for item in files_to_patch:
            rel_path = item.get("path")
            file_url = item.get("url")
            file_code = item.get("content")

            if not rel_path:
                continue

            # Fetch content if URL provided
            if not file_code and file_url:
                f_resp = requests.get(file_url, timeout=timeout)
                if f_resp.status_code == 200:
                    file_code = f_resp.text

            if file_code:
                ok = apply_patch_payload(rel_path, file_code, log_fn=log_fn)
                if ok:
                    applied.append(rel_path)

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
            result["message"] = f"Successfully applied {len(applied)} hot-patch file(s) (v{patch_ver})!"

            _safe_log(log_fn, f"[OTA] Hot-Patch v{patch_ver} applied ({', '.join(applied)})")
        elif broadcast_data:
            result["success"] = True
        else:
            result["message"] = "No patches could be applied."

        return result

    except Exception as e:
        result["message"] = str(e)
        _safe_log(log_fn, f"[OTA] Patch check error: {e}")
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

