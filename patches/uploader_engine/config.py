import os
import sys
from pathlib import Path

# Base directories
ROOT_DIR = Path(__file__).resolve().parent.parent
LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "StoriesStudio"

# Candidate database paths (Prioritizes existing Video Uploader database)
EXTERNAL_UPLOADER_DB = Path(r"c:\Users\Administrator\Downloads\Telegram Desktop\Video Uploader\data\uploader.db")
SHARED_APPDATA_DB = LOCAL_APPDATA / "uploader.db"
INTERNAL_DATA_DB = ROOT_DIR / "data" / "uploader.db"

if EXTERNAL_UPLOADER_DB.exists():
    DB_PATH = EXTERNAL_UPLOADER_DB
elif SHARED_APPDATA_DB.exists():
    DB_PATH = SHARED_APPDATA_DB
else:
    # Default to Shared AppData or External
    DB_PATH = EXTERNAL_UPLOADER_DB if EXTERNAL_UPLOADER_DB.parent.exists() else SHARED_APPDATA_DB

DATA_DIR = DB_PATH.parent
DATA_DIR.mkdir(parents=True, exist_ok=True)

# OAuth & YouTube Configuration
HOST = "127.0.0.1"
PORT = 8000
REDIRECT_URI = f"http://localhost:{PORT}/api/channels/auth/callback"

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/userinfo.profile"
]

UPLOAD_CHUNK_SIZE = 5 * 1024 * 1024  # 5 MB resumable chunks
