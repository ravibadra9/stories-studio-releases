import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from uploader_engine.config import DB_PATH, DATA_DIR

def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS channels (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        custom_url TEXT,
        thumbnail_url TEXT,
        subscriber_count INTEGER DEFAULT 0,
        video_count INTEGER DEFAULT 0,
        access_token TEXT,
        refresh_token TEXT,
        token_expiry TEXT,
        client_id TEXT,
        client_secret TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS upload_tasks (
        id TEXT PRIMARY KEY,
        channel_id TEXT NOT NULL,
        video_path TEXT NOT NULL,
        original_filename TEXT NOT NULL,
        file_size INTEGER DEFAULT 0,
        title TEXT NOT NULL,
        description TEXT DEFAULT '',
        thumbnail_path TEXT,
        tags TEXT DEFAULT '[]',
        category_id TEXT DEFAULT '22',
        privacy_status TEXT DEFAULT 'private',
        publish_at TEXT,
        scheduled_upload_time TEXT,
        timezone_name TEXT,
        made_for_kids INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending',
        progress_percent REAL DEFAULT 0.0,
        bytes_uploaded INTEGER DEFAULT 0,
        speed_mbps REAL DEFAULT 0.0,
        youtube_video_id TEXT,
        error_message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP,
        FOREIGN KEY (channel_id) REFERENCES channels (id) ON DELETE CASCADE
    );
    """)

    # Migration check for new columns
    cur.execute("PRAGMA table_info(upload_tasks);")
    cols = [col[1] for col in cur.fetchall()]
    if "scheduled_upload_time" not in cols:
        cur.execute("ALTER TABLE upload_tasks ADD COLUMN scheduled_upload_time TEXT;")
    if "timezone_name" not in cols:
        cur.execute("ALTER TABLE upload_tasks ADD COLUMN timezone_name TEXT;")

    conn.commit()
    conn.close()

init_db()

def db_get_setting(key: str, default: str = "") -> str:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else default

def db_set_setting(key: str, value: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (key, value))
    conn.commit()
    conn.close()

def db_get_channels() -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM channels ORDER BY created_at DESC")
    rows = cur.fetchall()
    channels = [dict(r) for r in rows]
    conn.close()
    return channels

def db_get_channel_by_id(channel_id: str) -> Optional[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM channels WHERE id = ?", (channel_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def db_save_channel(channel_data: dict):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO channels (
            id, title, custom_url, thumbnail_url, subscriber_count, 
            video_count, access_token, refresh_token, token_expiry, 
            client_id, client_secret, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title,
            custom_url = excluded.custom_url,
            thumbnail_url = excluded.thumbnail_url,
            subscriber_count = excluded.subscriber_count,
            video_count = excluded.video_count,
            access_token = excluded.access_token,
            refresh_token = COALESCE(excluded.refresh_token, channels.refresh_token),
            token_expiry = excluded.token_expiry,
            client_id = excluded.client_id,
            client_secret = excluded.client_secret,
            updated_at = CURRENT_TIMESTAMP
    """, (
        channel_data["id"],
        channel_data.get("title", "Unknown"),
        channel_data.get("custom_url", ""),
        channel_data.get("thumbnail_url", ""),
        channel_data.get("subscriber_count", 0),
        channel_data.get("video_count", 0),
        channel_data.get("access_token", ""),
        channel_data.get("refresh_token", ""),
        channel_data.get("token_expiry", ""),
        channel_data.get("client_id", ""),
        channel_data.get("client_secret", "")
    ))
    conn.commit()
    conn.close()

def db_delete_channel(channel_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
    conn.commit()
    conn.close()

def db_get_tasks(channel_id: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if channel_id:
        cur.execute("SELECT * FROM upload_tasks WHERE channel_id = ? ORDER BY created_at DESC", (channel_id,))
    else:
        cur.execute("SELECT * FROM upload_tasks ORDER BY created_at DESC")
    rows = cur.fetchall()
    tasks = []
    for r in rows:
        t = dict(r)
        try:
            t["tags"] = json.loads(t["tags"]) if t["tags"] else []
        except Exception:
            t["tags"] = []
        tasks.append(t)
    conn.close()
    return tasks

def db_create_task(task_data: dict) -> str:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO upload_tasks (
            id, channel_id, video_path, original_filename, file_size,
            title, description, thumbnail_path, tags, category_id,
            privacy_status, publish_at, scheduled_upload_time, timezone_name,
            made_for_kids, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        task_data["id"],
        task_data["channel_id"],
        task_data["video_path"],
        task_data["original_filename"],
        task_data.get("file_size", 0),
        task_data["title"],
        task_data.get("description", ""),
        task_data.get("thumbnail_path"),
        json.dumps(task_data.get("tags", [])) if isinstance(task_data.get("tags"), list) else task_data.get("tags", "[]"),
        task_data.get("category_id", "22"),
        task_data.get("privacy_status", "private"),
        task_data.get("publish_at"),
        task_data.get("scheduled_upload_time"),
        task_data.get("timezone_name", ""),
        1 if task_data.get("made_for_kids") else 0,
        task_data.get("status", "pending")
    ))
    conn.commit()
    conn.close()
    return task_data["id"]

def db_update_task_progress(task_id: str, progress: float, bytes_up: int, speed: float):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        UPDATE upload_tasks 
        SET progress_percent = ?, bytes_uploaded = ?, speed_mbps = ?, status = 'uploading'
        WHERE id = ?
    """, (progress, bytes_up, speed, task_id))
    conn.commit()
    conn.close()

def db_update_task_status(task_id: str, status: str, error: Optional[str] = None, youtube_id: Optional[str] = None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    completed = datetime.utcnow().isoformat() if status in ["completed", "failed"] else None
    cur.execute("""
        UPDATE upload_tasks 
        SET status = ?, error_message = ?, youtube_video_id = COALESCE(?, youtube_video_id),
            completed_at = COALESCE(?, completed_at)
        WHERE id = ?
    """, (status, error, youtube_id, completed, task_id))
    conn.commit()
    conn.close()

def db_delete_task(task_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM upload_tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()

def format_bytes(b: int) -> str:
    if not b: return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if b < 1024.0:
            return f"{b:.2f} {unit}"
        b /= 1024.0
    return f"{b:.2f} TB"
