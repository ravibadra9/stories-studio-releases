"""
voice_cache.py — Smart AI33Pro voice search + cache system for StoriesStudio.

Provides:
  - Dynamic API voice fetch across providers (ElevenLabs, Minimax, FishAudio, Edge, Kokoro, Vbee, Cloned)
  - Local cache of voices & user's favorite/selected voices
  - Default API key persistence (sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt)
"""

import json, os, threading
from typing import List, Dict, Any, Optional

DEFAULT_AI33_KEY = ""
_APPDATA = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "StoriesStudio")
_CACHE_FILE = os.path.join(_APPDATA, "voice_cache.json")
_VOICE_LIST_CACHE_FILE = os.path.join(_APPDATA, "ai33_voices_cache.json")


def _ensure_dir():
    os.makedirs(_APPDATA, exist_ok=True)


def _load_cache():
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if data.get("api_key") == "sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt":
                data["api_key"] = ""
            return data
    except Exception:
        return {"api_key": "", "favorites": [], "recent_searches": []}


def _save_cache(data):
    _ensure_dir()
    with open(_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════
# API Key persistence
# ═══════════════════════════════════════════════
def save_api_key(key: str):
    c = _load_cache()
    cleaned = (key or "").strip()
    if cleaned == "sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt":
        cleaned = ""
    c["api_key"] = cleaned
    _save_cache(c)


def load_api_key() -> str:
    key = (_load_cache().get("api_key", "") or "").strip()
    if key == "sk_c8cdjxkts9xdinztd37ygd6m2fzfxzq2aoc7qn3xjmtpwqmt":
        return ""
    return key


# ═══════════════════════════════════════════════
# Favorites — user's selected voices (max 50)
# ═══════════════════════════════════════════════
def load_favorites() -> list:
    """Return list of dicts: [{"name": "...", "voice_id": "...", "gender": "..."}, ...]"""
    return _load_cache().get("favorites", [])


def add_favorite(name: str, voice_id: str, gender: str = "unknown"):
    c = _load_cache()
    favs = c.get("favorites", [])
    if any(f["voice_id"] == voice_id for f in favs):
        return
    favs.insert(0, {"name": name, "voice_id": voice_id, "gender": gender})
    if len(favs) > 50:
        favs = favs[:50]
    c["favorites"] = favs
    _save_cache(c)


def remove_favorite(voice_id: str):
    c = _load_cache()
    c["favorites"] = [f for f in c.get("favorites", []) if f["voice_id"] != voice_id]
    _save_cache(c)


def get_favorite_names() -> list:
    """Return list of voice names for dropdown."""
    return [f["name"] for f in load_favorites()]


def get_favorite_id(name: str) -> str:
    """Look up voice_id by name."""
    for f in load_favorites():
        if f["name"] == name:
            return f["voice_id"]
    return ""


DEFAULT_FALLBACK_VOICES = [
    # ── ElevenLabs Premade Voice Library ──
    {"voice_id": "elevenlabs_hpp4J3VqNfWAU000d1Us", "name": "Bella - Professional, Bright, Warm", "provider": "ElevenLabs", "category": "female", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/hpp4J3VqNfWAU000d1Us/preview.mp3"},
    {"voice_id": "elevenlabs_21m00Tcm4TlvDq8ikWAM", "name": "Rachel - Calm, Narrative", "provider": "ElevenLabs", "category": "female", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/21m00Tcm4TlvDq8ikWAM/preview.mp3"},
    {"voice_id": "elevenlabs_AZnzlk1XvdvUeBnXmlld", "name": "Domi - Strong, Expressive", "provider": "ElevenLabs", "category": "female", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/AZnzlk1XvdvUeBnXmlld/preview.mp3"},
    {"voice_id": "elevenlabs_EXAVITQu4vr4xnSDxMaL", "name": "Sarah - Mature, Reassuring", "provider": "ElevenLabs", "category": "female", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/EXAVITQu4vr4xnSDxMaL/preview.mp3"},
    {"voice_id": "elevenlabs_ErXwobaYiN019PkySvjV", "name": "Antoni - Well-rounded", "provider": "ElevenLabs", "category": "male", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/ErXwobaYiN019PkySvjV/preview.mp3"},
    {"voice_id": "elevenlabs_MF3mGyEYCl7XYWbV9V6O", "name": "Elli - Emotional, Narrative", "provider": "ElevenLabs", "category": "female", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/MF3mGyEYCl7XYWbV9V6O/preview.mp3"},
    {"voice_id": "elevenlabs_TxGEqnHWrfWFTfGW9XjX", "name": "Josh - Young, Energetic", "provider": "ElevenLabs", "category": "male", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/TxGEqnHWrfWFTfGW9XjX/preview.mp3"},
    {"voice_id": "elevenlabs_VR6AewLTigWG4xSOukaG", "name": "Arnold - Crisp, Confident", "provider": "ElevenLabs", "category": "male", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/VR6AewLTigWG4xSOukaG/preview.mp3"},
    {"voice_id": "elevenlabs_pNInz6obpgDQGcFmaJgB", "name": "Adam - Deep, Warm Narration", "provider": "ElevenLabs", "category": "male", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/pNInz6obpgDQGcFmaJgB/preview.mp3"},
    {"voice_id": "elevenlabs_yoZ06aMxZJJ28mfd3POQ", "name": "Sam - Casual, Expressive", "provider": "ElevenLabs", "category": "male", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/yoZ06aMxZJJ28mfd3POQ/preview.mp3"},
    {"voice_id": "elevenlabs_CwhRBWXzGAHq8TQ4Fs17", "name": "Roger - Laid-Back, Casual", "provider": "ElevenLabs", "category": "male", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/CwhRBWXzGAHq8TQ4Fs17/preview.mp3"},
    {"voice_id": "elevenlabs_IKne3meq5aSn9XLyUdCD", "name": "Charlie - Australian, Conversational", "provider": "ElevenLabs", "category": "male", "language": "en-AU", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/IKne3meq5aSn9XLyUdCD/preview.mp3"},
    {"voice_id": "elevenlabs_JBFqnCBsd6RMkjVDRZzb", "name": "George - British, Warm, Raspy", "provider": "ElevenLabs", "category": "male", "language": "en-GB", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/JBFqnCBsd6RMkjVDRZzb/preview.mp3"},
    {"voice_id": "elevenlabs_N2lVS1w4EtoT3dr4eOWO", "name": "Callum - Intense, Storyteller", "provider": "ElevenLabs", "category": "male", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/N2lVS1w4EtoT3dr4eOWO/preview.mp3"},
    {"voice_id": "elevenlabs_XB0fDUnXU5powFXDhCwa", "name": "Charlotte - Seductive, Warm", "provider": "ElevenLabs", "category": "female", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/XB0fDUnXU5powFXDhCwa/preview.mp3"},
    {"voice_id": "elevenlabs_2EiwWnXFnvU5JabPnv8n", "name": "Clyde - Veteran, Gritty", "provider": "ElevenLabs", "category": "male", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/2EiwWnXFnvU5JabPnv8n/preview.mp3"},
    {"voice_id": "elevenlabs_onwK4e9ZLuTAKqWW03F9", "name": "Daniel - Deep, British News", "provider": "ElevenLabs", "category": "male", "language": "en-GB", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/onwK4e9ZLuTAKqWW03F9/preview.mp3"},
    {"voice_id": "elevenlabs_CYw3kZ02Hs0563khs1Fj", "name": "Dave - Conversational British", "provider": "ElevenLabs", "category": "male", "language": "en-GB", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/CYw3kZ02Hs0563khs1Fj/preview.mp3"},
    {"voice_id": "elevenlabs_LcfcDJNUP1GQjkzn1xUU", "name": "Emily - Meditative, Calm", "provider": "ElevenLabs", "category": "female", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/LcfcDJNUP1GQjkzn1xUU/preview.mp3"},
    {"voice_id": "elevenlabs_g5CIjZEefAph4nZVnTnv", "name": "Ethan - ASMR, Whisper", "provider": "ElevenLabs", "category": "male", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/g5CIjZEefAph4nZVnTnv/preview.mp3"},
    {"voice_id": "elevenlabs_D38z5RcWu1voky8WS1ja", "name": "Fin - Sailor, Irish Accent", "provider": "ElevenLabs", "category": "male", "language": "en-IE", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/D38z5RcWu1voky8WS1ja/preview.mp3"},
    {"voice_id": "elevenlabs_jsCqWAovK2LkecY7zXl4", "name": "Freya - Overconfident, Youthful", "provider": "ElevenLabs", "category": "female", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/jsCqWAovK2LkecY7zXl4/preview.mp3"},
    {"voice_id": "elevenlabs_jBpfuIE2acCO8z3wKNLl", "name": "Gigi - Childish, Animation", "provider": "ElevenLabs", "category": "female", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/jBpfuIE2acCO8z3wKNLl/preview.mp3"},
    {"voice_id": "elevenlabs_z9fAnlkpzviPz146aGWa", "name": "Glinda - Witch, Fantasy", "provider": "ElevenLabs", "category": "female", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/z9fAnlkpzviPz146aGWa/preview.mp3"},
    {"voice_id": "elevenlabs_oWAxZDx7w5VEj9dCyTzz", "name": "Grace - Southern American", "provider": "ElevenLabs", "category": "female", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/oWAxZDx7w5VEj9dCyTzz/preview.mp3"},
    {"voice_id": "elevenlabs_SOYHLrjzK2X1ezoY6CVb", "name": "Harry - Anxious, Dramatic", "provider": "ElevenLabs", "category": "male", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/SOYHLrjzK2X1ezoY6CVb/preview.mp3"},
    {"voice_id": "elevenlabs_ZQe5CZNOzWyzPSCn5a3c", "name": "James - Australian Narration", "provider": "ElevenLabs", "category": "male", "language": "en-AU", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/ZQe5CZNOzWyzPSCn5a3c/preview.mp3"},
    {"voice_id": "elevenlabs_bVMeCyTHy58xNoL34h3p", "name": "Jeremy - Irish, Storyteller", "provider": "ElevenLabs", "category": "male", "language": "en-IE", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/bVMeCyTHy58xNoL34h3p/preview.mp3"},
    {"voice_id": "elevenlabs_t0jbNlBVZ17f02VDIeMI", "name": "Jessie - Raspy, American", "provider": "ElevenLabs", "category": "male", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/t0jbNlBVZ17f02VDIeMI/preview.mp3"},
    {"voice_id": "elevenlabs_Zlb1dXrM653N07WRdFW3", "name": "Joseph - British Grounded", "provider": "ElevenLabs", "category": "male", "language": "en-GB", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/Zlb1dXrM653N07WRdFW3/preview.mp3"},
    {"voice_id": "elevenlabs_TX3LPaxmHKxFdv7VOQHJ", "name": "Liam - Youthful American", "provider": "ElevenLabs", "category": "male", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/TX3LPaxmHKxFdv7VOQHJ/preview.mp3"},
    {"voice_id": "elevenlabs_Ida4X2iW2Y72vI2eA9qG", "name": "Marcus - Authoritative Narration", "provider": "ElevenLabs", "category": "male", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/Ida4X2iW2Y72vI2eA9qG/preview.mp3"},
    {"voice_id": "elevenlabs_XrExE9yKIg1WjnnlVkGX", "name": "Matilda - Warm, Narrative", "provider": "ElevenLabs", "category": "female", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/XrExE9yKIg1WjnnlVkGX/preview.mp3"},
    {"voice_id": "elevenlabs_flq6f7yk4E4fJM5XTYuZ", "name": "Michael - Audiobook Narrator", "provider": "ElevenLabs", "category": "male", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/flq6f7yk4E4fJM5XTYuZ/preview.mp3"},
    {"voice_id": "elevenlabs_zrHiDhphv9ZnVXBqCLjz", "name": "Mimi - Sweet, Animation", "provider": "ElevenLabs", "category": "female", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/zrHiDhphv9ZnVXBqCLjz/preview.mp3"},
    {"voice_id": "elevenlabs_piTKgcLEGmPE4e6mEKli", "name": "Nicole - Whisper Audio", "provider": "ElevenLabs", "category": "female", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/piTKgcLEGmPE4e6mEKli/preview.mp3"},
    {"voice_id": "elevenlabs_ODq5zmih8GrVes37Dizd", "name": "Patrick - Energetic Commercial", "provider": "ElevenLabs", "category": "male", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/ODq5zmih8GrVes37Dizd/preview.mp3"},
    {"voice_id": "elevenlabs_5Q0t7uMcjvnagumLfvZi", "name": "Paul - Grounded News Voice", "provider": "ElevenLabs", "category": "male", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/5Q0t7uMcjvnagumLfvZi/preview.mp3"},
    {"voice_id": "elevenlabs_GBv7mTt0atIp3Br8iCZE", "name": "Thomas - Calm Meditative", "provider": "ElevenLabs", "category": "male", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/GBv7mTt0atIp3Br8iCZE/preview.mp3"},
    {"voice_id": "elevenlabs_bIHbv24MWmeRgasZH58o", "name": "Will - Relaxed Narration", "provider": "ElevenLabs", "category": "male", "language": "en-US", "preview_url": "https://storage.googleapis.com/eleven-public-prod/previews/voices/bIHbv24MWmeRgasZH58o/preview.mp3"},

    # ── Microsoft Edge Neural Voice Library (100% Free / Ultra-Fast) ──
    {"voice_id": "edge_hi-IN-MadhurNeural", "name": "Madhur - Deep Hindi Narration", "provider": "Edge Neural", "category": "male", "language": "hi-IN"},
    {"voice_id": "edge_hi-IN-SwaraNeural", "name": "Swara - Expressive Hindi Female", "provider": "Edge Neural", "category": "female", "language": "hi-IN"},
    {"voice_id": "edge_en-IN-NeerjaNeural", "name": "Neerja - Indian English Female", "provider": "Edge Neural", "category": "female", "language": "en-IN"},
    {"voice_id": "edge_en-IN-PrabhatNeural", "name": "Prabhat - Indian English Male", "provider": "Edge Neural", "category": "male", "language": "en-IN"},
    {"voice_id": "edge_en-US-JennyNeural", "name": "Jenny - Natural US Female", "provider": "Edge Neural", "category": "female", "language": "en-US"},
    {"voice_id": "edge_en-US-GuyNeural", "name": "Guy - Natural US Male", "provider": "Edge Neural", "category": "male", "language": "en-US"},
    {"voice_id": "edge_en-US-ChristopherNeural", "name": "Christopher - Authoritative US", "provider": "Edge Neural", "category": "male", "language": "en-US"},
    {"voice_id": "edge_en-US-AriaNeural", "name": "Aria - Expressive Storytelling", "provider": "Edge Neural", "category": "female", "language": "en-US"},
    {"voice_id": "edge_en-GB-RyanNeural", "name": "Ryan - British English Male", "provider": "Edge Neural", "category": "male", "language": "en-GB"},
    {"voice_id": "edge_en-GB-SoniaNeural", "name": "Sonia - British English Female", "provider": "Edge Neural", "category": "female", "language": "en-GB"},

    # ── Minimax & Other Providers ──
    {"voice_id": "minimax_male-qn-qingse", "name": "Minimax - Young Crisp Male", "provider": "Minimax", "category": "male", "language": "en/zh"},
    {"voice_id": "minimax_female-shaonv", "name": "Minimax - Sweet Soft Female", "provider": "Minimax", "category": "female", "language": "en/zh"},
    {"voice_id": "kokoro_af_sarah", "name": "Kokoro - Sarah", "provider": "Kokoro", "category": "female", "language": "en-US"},
    {"voice_id": "kokoro_am_michael", "name": "Kokoro - Michael", "provider": "Kokoro", "category": "male", "language": "en-US"},
    {"voice_id": "fishaudio_802773d57d544dc59021e06f9d784a0d", "name": "FishAudio - Studio Master", "provider": "FishAudio", "category": "neutral", "language": "en/zh"},
]


# ═══════════════════════════════════════════════
# Dynamic Voice Fetching & Caching via AI33Client
# ═══════════════════════════════════════════════
def load_voices_cached(api_key: Optional[str] = None, force_refresh: bool = False, provider_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch voices via AI33Client across all supported providers with local JSON cache & resilient fallbacks."""
    key = api_key or load_api_key()
    
    if not force_refresh and os.path.exists(_VOICE_LIST_CACHE_FILE):
        try:
            with open(_VOICE_LIST_CACHE_FILE, "r", encoding="utf-8") as f:
                cached_voices = json.load(f)
                if isinstance(cached_voices, list) and len(cached_voices) > 0:
                    if provider_filter:
                        pf = provider_filter.lower().replace(" ", "")
                        res = [v for v in cached_voices if pf in v.get("provider", "").lower().replace(" ", "")]
                        if res: return res
                    else:
                        return cached_voices
        except Exception:
            pass

    voices = []
    try:
        from ai33_api import AI33Client
        client = AI33Client(api_key=key)
        voices = client.fetch_voices(provider_filter=provider_filter, fast_mode=True)
        if not voices and key != DEFAULT_AI33_KEY:
            client_def = AI33Client(api_key=DEFAULT_AI33_KEY)
            voices = client_def.fetch_voices(provider_filter=provider_filter, fast_mode=True)
        
        if voices:
            _ensure_dir()
            with open(_VOICE_LIST_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(voices, f, indent=2, ensure_ascii=False)
            return voices
    except Exception:
        pass

    # If network fetch failed, try cache file
    if os.path.exists(_VOICE_LIST_CACHE_FILE):
        try:
            with open(_VOICE_LIST_CACHE_FILE, "r", encoding="utf-8") as f:
                cached_voices = json.load(f)
                if isinstance(cached_voices, list) and len(cached_voices) > 0:
                    if provider_filter:
                        pf = provider_filter.lower().replace(" ", "")
                        return [v for v in cached_voices if pf in v.get("provider", "").lower().replace(" ", "")]
                    return cached_voices
        except Exception:
            pass

    # Built-in fallback voices so dropdowns and list never stay blank
    if provider_filter:
        pf = provider_filter.lower().replace(" ", "")
        return [v for v in DEFAULT_FALLBACK_VOICES if pf in v.get("provider", "").lower().replace(" ", "")]
    return list(DEFAULT_FALLBACK_VOICES)


def search_voices(api_key: Optional[str] = None, query: str = "", provider_filter: Optional[str] = None, page_size: int = 50) -> list:
    """
    Search AI33 voices matching query string and provider filter.
    Returns list of dicts: {"name", "voice_id", "provider", "category", "preview_url"}
    """
    voices = load_voices_cached(api_key=api_key, force_refresh=False, provider_filter=provider_filter)
    if not query:
        return voices[:page_size]

    q = query.strip().lower()
    results = []
    for v in voices:
        name = v.get("name", "").lower()
        vid = v.get("voice_id", "").lower()
        prov = v.get("provider", "").lower()
        cat = v.get("category", "").lower()
        if q in name or q in vid or q in prov or q in cat:
            results.append(v)
            if len(results) >= page_size:
                break
    return results


def search_voices_async(api_key: Optional[str], query: str, callback, provider_filter: Optional[str] = None, page_size: int = 50):
    """Threaded version — callback(results_list) called on completion."""
    def _worker():
        results = search_voices(api_key, query, provider_filter=provider_filter, page_size=page_size)
        try:
            callback(results)
        except Exception:
            pass
    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t


# ═══════════════════════════════════════════════
# API key validation
# ═══════════════════════════════════════════════
def validate_key(api_key: str) -> bool:
    """Quick check via /v3/voices endpoint."""
    key = api_key or DEFAULT_AI33_KEY
    try:
        from ai33_api import AI33Client
        client = AI33Client(api_key=key)
        res = client.fetch_voices(fast_mode=True)
        return len(res) > 0
    except Exception:
        return False


# ═══════════════════════════════════════════════
# Recent searches
# ═══════════════════════════════════════════════
def add_recent_search(query: str):
    c = _load_cache()
    recent = c.get("recent_searches", [])
    query = query.strip()
    if not query:
        return
    if query in recent:
        recent.remove(query)
    recent.insert(0, query)
    c["recent_searches"] = recent[:20]
    _save_cache(c)


def get_recent_searches() -> list:
    return _load_cache().get("recent_searches", [])

