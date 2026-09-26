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

def get_video_duration_seconds(file_path: str) -> float:
    """Calculates duration in seconds using OpenCV or ffprobe."""
    if not file_path or not os.path.exists(file_path):
        return 0.0
    try:
        import cv2
        cap = cv2.VideoCapture(file_path)
        if cap.isOpened():
            fps = cap.get(cv2.CAP_PROP_FPS)
            cnt = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            cap.release()
            if fps and fps > 0 and cnt > 0:
                return float(cnt / fps)
    except Exception:
        pass
    try:
        import subprocess, json
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", file_path]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        d = json.loads(res.stdout)
        return float(d["format"]["duration"])
    except Exception:
        pass
    return 0.0

def format_duration(seconds: float) -> str:
    """Formats duration seconds into MM:SS or HH:MM:SS."""
    if not seconds or seconds <= 0:
        return "00:00"
    sec = int(round(seconds))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

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
    dur_sec = get_video_duration_seconds(video_path)
    task["file_size"] = file_size
    task["video_duration_seconds"] = dur_sec
    task["video_duration_str"] = format_duration(dur_sec)
    
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
    
    chunk_size = task.get("chunk_size") or UPLOAD_CHUNK_SIZE
    chunk_size = max(256 * 1024, (chunk_size // (256 * 1024)) * (256 * 1024))

    # 3. Create Resumable Media Upload (high speed 25MB chunks)
    media = MediaFileUpload(
        video_path,
        chunksize=chunk_size,
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
    retry_count = 0
    max_retries = 25

    # Configure reasonable socket/http timeout to prevent hanging connections
    try:
        if hasattr(request, "http") and getattr(request.http, "timeout", None) is None:
            request.http.timeout = 60
    except Exception:
        pass
    
    while response is None:
        try:
            chunk_status, response = request.next_chunk(num_retries=3)
            retry_count = 0  # reset retry counter on successful chunk
        except (HttpError, Exception) as ex:
            if isinstance(ex, HttpError) and getattr(ex, "resp", None) and ex.resp.status in [400, 401, 403, 404]:
                raise ex  # Fatal authentication or quota error
            retry_count += 1
            if retry_count > max_retries:
                raise ex
            # Force close dead/broken SSL sockets so next attempt creates a fresh TLS connection
            try:
                if hasattr(request, "http") and hasattr(request.http, "close"):
                    request.http.close()
                elif hasattr(request, "http") and hasattr(request.http, "connections"):
                    request.http.connections.clear()
            except Exception:
                pass
            sleep_sec = min(15, (1.5 ** min(retry_count, 6)))
            print(f"[Uploader] Network drop or SSL reset ({ex}). Auto-recovering and resuming chunk in {sleep_sec:.1f}s (Attempt {retry_count}/{max_retries})...")
            time.sleep(sleep_sec)
            continue
        current_time = time.time()
        
        if chunk_status:
            # Safely handle resumable_progress whether property int or callable
            if callable(getattr(chunk_status, "resumable_progress", None)):
                uploaded_bytes = chunk_status.resumable_progress()
            else:
                uploaded_bytes = getattr(chunk_status, "resumable_progress", 0)

            total_size = getattr(chunk_status, "total_size", file_size) or file_size
            if callable(getattr(chunk_status, "progress", None)):
                percent = chunk_status.progress() * 100.0
            else:
                percent = (uploaded_bytes / total_size) * 100.0 if total_size > 0 else 0.0
            
            time_diff = current_time - last_time
            bytes_diff = uploaded_bytes - last_bytes
            if time_diff > 0.05 and bytes_diff > 0:
                speed = (bytes_diff / (1024 * 1024)) / time_diff
            elif current_time > start_time:
                speed = (uploaded_bytes / (1024 * 1024)) / (current_time - start_time)
            else:
                speed = 0.0
            
            last_bytes = uploaded_bytes
            last_time = current_time
            
            if progress_callback:
                progress_callback(round(percent, 2), uploaded_bytes, round(speed, 2))
                
    video_id = response.get("id")
    if not video_id:
        raise ValueError("Upload finished but no video ID returned from YouTube.")
        
    elapsed_total = round(time.time() - start_time, 1)
    task["upload_time_seconds"] = elapsed_total
    task["average_speed_mbps"] = round((file_size / (1024 * 1024)) / elapsed_total, 2) if elapsed_total > 0 else 0.0
    task["youtube_video_id"] = video_id
    task["watch_url"] = f"https://youtu.be/{video_id}"

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
