"""
auth_manager.py
----------------
Hardware-locked login system for StoriesStudio & AI Editor
Backend: Firebase Realtime Database (REST API) + Local Analytics Engine

Flow:
  1. Machine ka unique fingerprint banao (MAC + disk serial + CPU)
  2. Firebase se user record fetch karo
  3. Password verify karo (SHA-256)
  4. Machine bind check (single PC lock)
  5. User Profile + License Validity + Video Export Analytics
"""

import base64
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import requests


# ============================================================
#  CONFIG  — Firebase details
# ============================================================
FIREBASE_URL = "https://stories-studio-524d3-default-rtdb.asia-southeast1.firebasedatabase.app/"
FIREBASE_SECRET = "pws0hTavQFfgduMiRDLkAynPHZrOJMJLTeNTAFoy"   # Firebase Database secret
APP_NAME = "StoriesStudio"
TIMEOUT = 10
# ============================================================

_APPDATA_DIR = os.path.join(os.getenv("LOCALAPPDATA") or os.path.expanduser("~"), APP_NAME)
_PROFILE_CACHE_FILE = os.path.join(_APPDATA_DIR, "user_profile.json")
_ANALYTICS_CACHE_FILE = os.path.join(_APPDATA_DIR, "user_analytics.json")


def _ensure_appdata_dir():
    os.makedirs(_APPDATA_DIR, exist_ok=True)


# ------------------------------------------------------------
#  1. HARDWARE FINGERPRINT
# ------------------------------------------------------------
def _cmd(command: str) -> str:
    """Windows command chalao, output do. Fail ho to empty string."""
    try:
        out = subprocess.check_output(
            command,
            shell=True,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return out.decode(errors="ignore").strip()
    except Exception:
        return ""


def get_machine_id() -> str:
    """
    3 cheezon ko mila kar ek stable fingerprint banata hai:
      - Motherboard serial
      - Disk volume serial
      - MAC address
    Kisi ek ke fail hone par bhi ID stable rehti hai (kam se kam MAC to milega).
    """
    parts = []

    if sys.platform == "win32":
        # Motherboard UUID
        mb = _cmd("wmic csproduct get uuid")
        mb = "".join(mb.split("\n")[1:]).strip() if mb else ""
        parts.append(mb)

        # C: drive volume serial
        vol = _cmd("wmic diskdrive get serialnumber")
        vol = "".join(vol.split("\n")[1:]).strip() if vol else ""
        parts.append(vol)
    else:
        parts.append(_cmd("cat /etc/machine-id"))

    # MAC address (fallback, hamesha milta hai)
    parts.append(str(uuid.getnode()))

    raw = "|".join(p for p in parts if p)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ------------------------------------------------------------
#  2. PASSWORD HASHING
# ------------------------------------------------------------
def hash_password(password: str) -> str:
    """Salted SHA-256. Salt fixed hai kyunki server-side bhi wahi hona chahiye."""
    salted = f"{APP_NAME}::{password}::v1"
    return hashlib.sha256(salted.encode()).hexdigest()


# ------------------------------------------------------------
#  2b. REMEMBER-ME (machine-tied, plaintext kabhi save nahi hota)
# ------------------------------------------------------------
def _remember_key() -> bytes:
    """Key sirf isi machine pe reproduce ho sakti hai."""
    mid = get_machine_id()
    return hashlib.sha256(f"{mid}::remember::v1".encode()).digest()


def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def _remember_path() -> str:
    _ensure_appdata_dir()
    return os.path.join(_APPDATA_DIR, "session.dat")


def save_remembered(user_id: str, password_hash: str) -> None:
    """Login safal hone ke baad, checkbox tick ho to yeh call hota hai."""
    try:
        _ensure_appdata_dir()
        payload = json.dumps({"u": user_id, "h": password_hash}).encode()
        enc = _xor(payload, _remember_key())
        with open(_remember_path(), "wb") as f:
            f.write(base64.b64encode(enc))
    except Exception:
        pass


def load_remembered():
    """(user_id, password_hash) return karta hai, ya None agar kuch saved nahi / corrupt hai."""
    path = _remember_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            enc = base64.b64decode(f.read())
        raw = _xor(enc, _remember_key())
        data = json.loads(raw.decode())
        uid, h = data.get("u"), data.get("h")
        if uid and h:
            return uid, h
        return None
    except Exception:
        return None


def clear_remembered() -> None:
    try:
        p = _remember_path()
        if os.path.exists(p):
            os.remove(p)
    except Exception:
        pass


# ------------------------------------------------------------
#  3. VALIDITY & USER PROFILE HELPERS
# ------------------------------------------------------------
def parse_expiry_info(expires_on: Any) -> Dict[str, Any]:
    """Parse expiry field into human-friendly metrics."""
    if not expires_on or str(expires_on).strip().lower() in ("", "lifetime", "none", "null", "false", "0", "unlimited"):
        return {
            "expires_on": "",
            "validity_display": "✨ Lifetime Access",
            "badge_color": "#10b981",  # Emerald Green
            "days_left": None,
            "is_expired": False,
            "formatted_date": "Lifetime Unlimited",
        }

    raw_str = str(expires_on).strip()
    try:
        clean_iso = raw_str.replace("Z", "+00:00")
        if "T" in clean_iso:
            exp_dt = datetime.fromisoformat(clean_iso)
        else:
            exp_dt = datetime.strptime(clean_iso[:10], "%Y-%m-%d")

        if exp_dt.tzinfo is not None:
            exp_dt = exp_dt.astimezone(timezone.utc).replace(tzinfo=None)

        now = datetime.utcnow()
        diff = exp_dt - now
        days_left = diff.days + (1 if diff.seconds > 0 else 0)

        if days_left < 0:
            return {
                "expires_on": raw_str,
                "validity_display": f"⚠️ Expired on {exp_dt.strftime('%d %b %Y')}",
                "badge_color": "#ef4444",  # Red
                "days_left": days_left,
                "is_expired": True,
                "formatted_date": exp_dt.strftime("%d %b %Y"),
            }
        elif days_left == 0:
            return {
                "expires_on": raw_str,
                "validity_display": f"⏳ Expires Today ({exp_dt.strftime('%d %b %Y')})",
                "badge_color": "#f59e0b",  # Amber
                "days_left": 0,
                "is_expired": False,
                "formatted_date": exp_dt.strftime("%d %b %Y"),
            }
        elif days_left <= 7:
            return {
                "expires_on": raw_str,
                "validity_display": f"⏳ {days_left} Days Remaining (Exp: {exp_dt.strftime('%d %b %Y')})",
                "badge_color": "#f59e0b",  # Amber
                "days_left": days_left,
                "is_expired": False,
                "formatted_date": exp_dt.strftime("%d %b %Y"),
            }
        else:
            return {
                "expires_on": raw_str,
                "validity_display": f"🛡️ {days_left} Days Remaining (Exp: {exp_dt.strftime('%d %b %Y')})",
                "badge_color": "#3b82f6",  # Blue
                "days_left": days_left,
                "is_expired": False,
                "formatted_date": exp_dt.strftime("%d %b %Y"),
            }
    except Exception:
        return {
            "expires_on": raw_str,
            "validity_display": f"Valid ({raw_str[:10]})",
            "badge_color": "#10b981",
            "days_left": None,
            "is_expired": False,
            "formatted_date": raw_str[:10],
        }


def save_user_profile(data: Dict[str, Any]) -> None:
    """Save user profile to local cache for instant zero-latency loading."""
    _ensure_appdata_dir()
    try:
        with open(_PROFILE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def get_user_profile(user_id: Optional[str] = None) -> Dict[str, Any]:
    """Load cached user profile from disk."""
    if os.path.exists(_PROFILE_CACHE_FILE):
        try:
            with open(_PROFILE_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not user_id or str(data.get("user_id", "")).lower() == user_id.lower():
                    exp_info = parse_expiry_info(data.get("expires_on"))
                    data.update(exp_info)
                    data["exports_count"] = get_video_exports_count(data.get("user_id"))
                    return data
        except Exception:
            pass

    return {
        "user_id": user_id or "Guest",
        "name": (user_id or "Guest Creator").title(),
        "active": True,
        "expires_on": "",
        "validity_display": "✨ Lifetime Access",
        "badge_color": "#10b981",
        "days_left": None,
        "is_expired": False,
        "exports_count": get_video_exports_count(user_id),
        "machine_id": get_machine_id(),
        "last_login": "",
    }


# ------------------------------------------------------------
#  4. VIDEO EXPORTS ANALYTICS TRACKING
# ------------------------------------------------------------
def _load_analytics() -> Dict[str, Any]:
    _ensure_appdata_dir()
    if os.path.exists(_ANALYTICS_CACHE_FILE):
        try:
            with open(_ANALYTICS_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"exports_count": 0, "history": []}


def _save_analytics(data: Dict[str, Any]) -> None:
    _ensure_appdata_dir()
    try:
        with open(_ANALYTICS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def get_video_exports_count(user_id: Optional[str] = None) -> int:
    """Return current video export count from profile or analytics cache."""
    if os.path.exists(_PROFILE_CACHE_FILE):
        try:
            with open(_PROFILE_CACHE_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                cnt = d.get("exports_count")
                if isinstance(cnt, (int, float)):
                    return int(cnt)
        except Exception:
            pass

    analytics = _load_analytics()
    return int(analytics.get("exports_count", 0))


def record_video_export(tool_name: str = "Video Studio", file_path: str = "", duration: float = 0.0) -> int:
    """
    Universal Video Export Event Tracker:
    1. Increments local analytics count and recent exports list.
    2. Updates cached user profile.
    3. Asynchronously syncs export increment + event to Firebase Realtime Database.
    """
    _ensure_appdata_dir()

    # 1. Update local analytics
    analytics = _load_analytics()
    new_count = int(analytics.get("exports_count", 0)) + 1
    analytics["exports_count"] = new_count

    filename = os.path.basename(file_path) if file_path else f"Render_{datetime.now().strftime('%H%M%S')}.mp4"
    history = analytics.get("history", [])
    entry = {
        "tool": tool_name,
        "file": filename,
        "path": file_path,
        "duration": round(duration, 2),
        "timestamp": datetime.utcnow().isoformat(),
    }
    history.insert(0, entry)
    analytics["history"] = history[:50]  # Keep last 50
    _save_analytics(analytics)

    # 2. Update local user profile
    profile = get_user_profile()
    profile["exports_count"] = new_count
    save_user_profile(profile)

    user_id = profile.get("user_id", "").strip().lower()

    # 3. Asynchronously sync to Firebase in background thread
    def _sync_firebase():
        if not user_id or user_id in ("guest", "unknown", ""):
            return
        try:
            # Sync total count
            requests.patch(
                _url(f"users/{user_id}"),
                data=json.dumps({"exports_count": new_count}),
                timeout=TIMEOUT,
            )
            # Push history event
            history_url = f"{FIREBASE_URL}/users/{user_id}/exports_history.json?auth={FIREBASE_SECRET}"
            requests.post(history_url, data=json.dumps(entry), timeout=TIMEOUT)
        except Exception:
            pass

    threading.Thread(target=_sync_firebase, daemon=True).start()
    return new_count


# ------------------------------------------------------------
#  5. FIREBASE CALLS & AUTHENTICATION
# ------------------------------------------------------------
def _url(path: str) -> str:
    return f"{FIREBASE_URL}/{path}.json?auth={FIREBASE_SECRET}"


def fetch_user(user_id: str):
    """Firebase se user record laao. None agar exist nahi karta."""
    try:
        r = requests.get(_url(f"users/{user_id}"), timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        return r.json()
    except requests.RequestException:
        raise ConnectionError("Internet connection nahi mil raha. Login ke liye net zaroori hai.")


# ------------------------------------------------------------
#  1b. PC NAME & IP NETWORK DETECTION
# ------------------------------------------------------------
def get_system_network_info() -> Dict[str, str]:
    """
    Fetch PC Hostname, OS Username, Local IP, and Public IP Address + Geolocation.
    Runs fast with low timeouts (< 2.5s) and resilient fallback mechanisms.
    """
    pc_name = "Unknown-PC"
    try:
        pc_name = socket.gethostname() or os.getenv("COMPUTERNAME") or os.getenv("HOSTNAME") or "Unknown-PC"
    except Exception:
        pass

    os_user = os.getenv("USERNAME") or os.getenv("USER") or "Unknown"
    local_ip = "127.0.0.1"
    try:
        local_ip = socket.gethostbyname(pc_name)
    except Exception:
        pass

    public_ip = "Unknown"
    location = ""
    try:
        r = requests.get("https://ipinfo.io/json", timeout=2.5)
        if r.status_code == 200:
            d = r.json()
            public_ip = d.get("ip", "Unknown")
            city = d.get("city", "")
            country = d.get("country", "")
            location = f"{city}, {country}" if city and country else (city or country)
    except Exception:
        try:
            r = requests.get("https://api.ipify.org?format=json", timeout=2)
            if r.status_code == 200:
                public_ip = r.json().get("ip", "Unknown")
        except Exception:
            pass

    os_ver = "Windows"
    try:
        os_ver = f"{platform.system()} {platform.release()}"
    except Exception:
        pass

    return {
        "pc_name": pc_name,
        "os_user": os_user,
        "local_ip": local_ip,
        "ip_address": public_ip,
        "ip_location": location,
        "os_version": os_ver,
    }


def bind_machine(user_id: str, machine_id: str):
    """Pehli baar activate hone par machine bind kar do aur PC info save karo."""
    def _bg_bind():
        try:
            net_info = get_system_network_info()
            payload = {
                "machine_id": machine_id,
                "activated_on": datetime.utcnow().isoformat(),
                "pc_name": net_info["pc_name"],
                "os_user": net_info["os_user"],
                "ip_address": net_info["ip_address"],
                "ip_location": net_info["ip_location"],
                "local_ip": net_info["local_ip"],
                "os_version": net_info["os_version"],
            }
            requests.patch(_url(f"users/{user_id}"), data=json.dumps(payload), timeout=TIMEOUT)
        except Exception:
            pass
    threading.Thread(target=_bg_bind, daemon=True).start()


def log_login(user_id: str):
    """Last login time, PC name, and IP address log karo Firebase par."""
    def _bg_log():
        try:
            net_info = get_system_network_info()
            payload = {
                "last_login": datetime.utcnow().isoformat(),
                "pc_name": net_info["pc_name"],
                "os_user": net_info["os_user"],
                "ip_address": net_info["ip_address"],
                "ip_location": net_info["ip_location"],
                "local_ip": net_info["local_ip"],
                "os_version": net_info["os_version"],
            }
            requests.patch(_url(f"users/{user_id}"), data=json.dumps(payload), timeout=TIMEOUT)
        except Exception:
            pass
    threading.Thread(target=_bg_log, daemon=True).start()



class AuthResult:
    def __init__(self, ok: bool, message: str, user_data: Optional[Dict[str, Any]] = None):
        self.ok = ok
        self.message = message
        self.user_data = user_data or {}


def _verify_core(user_id: str, password_hash: str) -> AuthResult:
    """Dono verify_login aur verify_login_by_hash isi se hoke guzarte hain."""
    user_id = user_id.strip().lower()

    if not user_id or not password_hash:
        return AuthResult(False, "User ID aur Password dono bharo.")

    # Master Super Admin offline fallback if connection fails
    try:
        user = fetch_user(user_id)
    except ConnectionError as e:
        if str(user_id).strip().lower() in ("8949400100", "ravibadra9") and password_hash == hash_password("12345678"):
            user_data = {
                "user_id": user_id,
                "name": "Ravi Badra (Master Super Admin)",
                "active": True,
                "role": "super_admin",
                "is_admin": True,
                "universal": True,
                "unlimited_machines": True,
                "multi_machine": True,
                "machine_lock": False,
                "expires_on": "",
                "validity_display": "✨ Lifetime Unlimited (Master Super Admin)",
                "badge_color": "#10b981",
                "days_left": None,
                "is_expired": False,
                "formatted_date": "Lifetime Unlimited",
                "exports_count": get_video_exports_count(user_id),
                "machine_id": "universal",
                "pc_name": socket.gethostname(),
                "os_user": os.getenv("USERNAME") or "Admin",
                "ip_address": "127.0.0.1",
                "ip_location": "",
                "last_login": datetime.utcnow().isoformat(),
            }
            save_user_profile(user_data)
            return AuthResult(True, "Offline Master Login successful.", user_data=user_data)

        cached = get_user_profile(user_id)
        if cached and cached.get("user_id") == user_id:
            return AuthResult(True, "Offline Mode (Logged in with cached profile).", user_data=cached)
        return AuthResult(False, str(e))

    if user is None:
        return AuthResult(False, "Invalid User ID ya Password.")

    # -- account active check
    if not user.get("active", True):
        return AuthResult(False, "Yeh account deactivate kar diya gaya hai. Admin se contact karo.")

    # -- password check
    if user.get("password_hash", "") != password_hash:
        return AuthResult(False, "Invalid User ID ya Password.")

    # -- expiry check
    expiry_info = parse_expiry_info(user.get("expires_on"))
    if expiry_info["is_expired"] and str(user_id).strip().lower() not in ("8949400100", "ravibadra9"):
        return AuthResult(False, f"License expire ho gaya hai ({expiry_info['formatted_date']}). Renew karwao.")

    # -- machine lock check
    is_master_admin = (str(user_id).strip().lower() in ("8949400100", "ravibadra9"))
    is_universal = bool(
        is_master_admin
        or user.get("universal")
        or user.get("multi_machine")
        or user.get("unlimited_machines")
        or user.get("bypass_machine_lock")
        or (user.get("machine_lock") is False)
        or user.get("role") in ("super_admin", "admin")
        or user.get("is_admin") is True
        or str(user.get("machine_id", "")).strip().lower() in ("universal", "unlimited", "all", "*", "multi", "none")
    )

    current = get_machine_id()
    saved = user.get("machine_id", "")

    if is_universal:
        # Universal / Multi-PC access: No machine binding, login allowed on any PC unlimited times
        log_login(user_id)
    elif not saved:
        bind_machine(user_id, current)
        log_login(user_id)
    elif saved != current:
        return AuthResult(
            False,
            "Yeh license kisi doosri machine par activate hai.\n"
            "Machine badalni hai to admin se reset karwao.",
        )
    else:
        log_login(user_id)

    # Role identification: ONLY 8949400100 and ravibadra9 get Super Admin privileges
    is_admin = is_master_admin
    user_role = "super_admin" if is_master_admin else user.get("role", "user")

    if is_master_admin:
        expiry_info["is_expired"] = False
        expiry_info["validity_display"] = "✨ Lifetime Unlimited (Master Super Admin)"
        expiry_info["badge_color"] = "#10b981"

    # Sync analytics and construct full profile
    remote_exports = user.get("exports_count")
    local_exports = get_video_exports_count(user_id)
    final_exports = max(int(remote_exports or 0), local_exports)

    user_data = {
        "user_id": user_id,
        "name": user.get("name") or user.get("display_name") or user_id.title(),
        "active": True,
        "role": user_role,
        "is_admin": is_admin,
        "universal": is_universal,
        "expires_on": "" if is_master_admin else user.get("expires_on", ""),
        "validity_display": expiry_info["validity_display"],
        "badge_color": expiry_info["badge_color"],
        "days_left": expiry_info["days_left"],
        "is_expired": expiry_info["is_expired"],
        "formatted_date": expiry_info["formatted_date"],
        "exports_count": final_exports,
        "machine_id": current,
        "pc_name": user.get("pc_name") or socket.gethostname(),
        "os_user": user.get("os_user") or os.getenv("USERNAME") or "Unknown",
        "ip_address": user.get("ip_address") or "Unknown",
        "ip_location": user.get("ip_location") or "",
        "last_login": datetime.utcnow().isoformat(),
    }

    save_user_profile(user_data)
    return AuthResult(True, "Login successful.", user_data=user_data)


MASTER_SUPER_ADMINS = {"8949400100", "ravibadra9"}


def is_current_user_admin(user_data: Optional[Dict[str, Any]] = None) -> bool:
    """Returns True ONLY if the active user is the authorized Master Super Admin (8949400100)."""
    try:
        data = user_data or get_user_profile()
        if not data:
            return False
        uid = str(data.get("user_id", "")).strip().lower()
        return uid in MASTER_SUPER_ADMINS
    except Exception:
        return False


def verify_login(user_id: str, password: str) -> AuthResult:
    """Normal login: plaintext password se."""
    return _verify_core(user_id, hash_password(password))


def verify_login_by_hash(user_id: str, password_hash: str) -> AuthResult:
    """Remember-me auto-login: saved hash se, plaintext kabhi nahi chahiye."""
    return _verify_core(user_id, password_hash)


def refresh_user_profile(user_id: Optional[str] = None) -> Dict[str, Any]:
    """Force refresh profile data from Firebase and return refreshed dict."""
    uid = user_id or get_user_profile().get("user_id")
    if uid and uid not in ("Guest", ""):
        try:
            user = fetch_user(uid)
            if user:
                expiry_info = parse_expiry_info(user.get("expires_on"))
                remote_exports = int(user.get("exports_count") or 0)
                local_exports = get_video_exports_count(uid)
                final_exports = max(remote_exports, local_exports)
                profile = {
                    "user_id": uid,
                    "name": user.get("name") or user.get("display_name") or uid.title(),
                    "active": user.get("active", True),
                    "expires_on": user.get("expires_on", ""),
                    "validity_display": expiry_info["validity_display"],
                    "badge_color": expiry_info["badge_color"],
                    "days_left": expiry_info["days_left"],
                    "is_expired": expiry_info["is_expired"],
                    "formatted_date": expiry_info["formatted_date"],
                    "exports_count": final_exports,
                    "machine_id": user.get("machine_id", get_machine_id()),
                    "pc_name": user.get("pc_name") or socket.gethostname(),
                    "os_user": user.get("os_user") or os.getenv("USERNAME") or "Unknown",
                    "ip_address": user.get("ip_address") or "Unknown",
                    "ip_location": user.get("ip_location") or "",
                    "last_login": user.get("last_login", ""),
                }
                save_user_profile(profile)
                return profile
        except Exception:
            pass
    return get_user_profile(uid)



# ------------------------------------------------------------
#  Helper CLI: Password hash generate & Machine ID check
# ------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) > 1:
        print("\n--- Firebase mein yeh daalo ---")
        print("password_hash :", hash_password(sys.argv[1]))
        print("\n--- Is machine ki ID ---")
        print("machine_id    :", get_machine_id())
    else:
        print("Usage: python auth_manager.py <password>")
        print("Is machine ki ID:", get_machine_id())
