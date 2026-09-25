import os
import time
from typing import Dict, Any, Callable, Optional
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from uploader_engine.config import UPLOAD_CHUNK_SIZE
from uploader_engine.database import (
    db_update_task_progress, db_update_task_status, db_get_tasks, db_get_channels, db_save_channel
)
from uploader_engine.auth import get_authenticated_youtube_service

def perform_video_upload(
    youtube,
    task: Dict[str, Any],
    progress_callback: Optional[Callable[[float, int, float], None]] = None
) -> str:
    """
    Executes a resumable chunked upload to YouTube.
    Supports title, description, tags, category, custom thumbnail, made_for_kids,
    and scheduled publishing (publishAt).
    """
    video_path = task["video_path"]
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")
        
    file_size = os.path.getsize(video_path)
    
    # 1. Construct snippet metadata
    clean_title = (task.get("title") or os.path.splitext(task.get("original_filename", "video"))[0]).strip()
    if not clean_title:
        clean_title = os.path.splitext(task.get("original_filename", "video"))[0]
    clean_title = clean_title[:100]

    snippet = {
        "title": clean_title,
        "description": (task.get("description") or "")[:5000],
        "categoryId": str(task.get("category_id", "22")),
    }
    
    tags = task.get("tags")
    if tags:
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        snippet["tags"] = tags
        
    # 2. Construct status metadata
    status_body = {
        "selfDeclaredMadeForKids": bool(task.get("made_for_kids", False))
    }
    
    privacy = task.get("privacy_status", "private").lower()
    publish_at = task.get("publish_at")
    
    if privacy == "scheduled" and publish_at:
        try:
            from datetime import datetime, timezone, timedelta
            dt_pub = datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
            now_utc = datetime.now(timezone.utc)
            if dt_pub <= now_utc + timedelta(minutes=2):
                status_body["privacyStatus"] = "public"
            else:
                status_body["privacyStatus"] = "private"
                if not publish_at.endswith("Z") and "+" not in publish_at:
                    publish_at = f"{publish_at}Z"
                status_body["publishAt"] = publish_at
        except Exception:
            status_body["privacyStatus"] = "public"
    elif privacy in ["public", "private", "unlisted"]:
        status_body["privacyStatus"] = privacy
    else:
        status_body["privacyStatus"] = "private"
        
    body = {
        "snippet": snippet,
        "status": status_body
    }
    
    # 3. Create Resumable Media Upload
    media = MediaFileUpload(
        video_path,
        chunksize=UPLOAD_CHUNK_SIZE,
        resumable=True
    )
    
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )
    
    response = None
    start_time = time.time()
    last_bytes = 0
    last_time = start_time
    
    while response is None:
        chunk_status, response = request.next_chunk()
        current_time = time.time()
        
        if chunk_status:
            uploaded_bytes = chunk_status.resumable_progress()
            percent = (uploaded_bytes / file_size) * 100 if file_size > 0 else 0
            
            time_diff = current_time - last_time
            bytes_diff = uploaded_bytes - last_bytes
            speed = (bytes_diff / (1024 * 1024)) / time_diff if time_diff > 0 else 0
            
            last_bytes = uploaded_bytes
            last_time = current_time
            
            if progress_callback:
                progress_callback(round(percent, 2), uploaded_bytes, round(speed, 2))
                
    video_id = response.get("id")
    if not video_id:
        raise ValueError("Upload finished but no video ID returned from YouTube.")
        
    # 4. Handle Custom Thumbnail upload if provided
    thumbnail_path = task.get("thumbnail_path")
    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            upload_thumbnail(youtube, video_id, thumbnail_path)
        except Exception as e:
            print(f"Warning: Failed to set custom thumbnail for video {video_id}: {e}")
            
    return video_id

def upload_thumbnail(youtube, video_id: str, thumbnail_path: str):
    media = MediaFileUpload(thumbnail_path)
    youtube.thumbnails().set(
        videoId=video_id,
        media_body=media
    ).execute()

def execute_single_upload_task(task: dict):
    task_id = task["id"]
    channel_id = task["channel_id"]

    try:
        db_update_task_status(task_id, "uploading")
        youtube = get_authenticated_youtube_service(channel_id)

        def progress_callback(pct, bytes_up, speed):
            db_update_task_progress(task_id, pct, bytes_up, speed)

        video_id = perform_video_upload(youtube, task, progress_callback)
        db_update_task_status(task_id, "completed", youtube_id=video_id)
        return video_id

    except Exception as e:
        err_msg = str(e)
        print(f"[Uploader] Task {task_id} failed: {err_msg}")
        db_update_task_status(task_id, "failed", error=err_msg)
        raise
