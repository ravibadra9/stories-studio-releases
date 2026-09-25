import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from uploader_engine.config import YOUTUBE_SCOPES, REDIRECT_URI
from uploader_engine.database import db_get_channel_by_id, db_save_channel

def parse_auth_code(code_or_url: str) -> str:
    code_or_url = code_or_url.strip()
    if "?" in code_or_url or "code=" in code_or_url:
        parsed = urllib.parse.urlparse(code_or_url)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params and params["code"]:
            return params["code"][0]
    return code_or_url

def generate_authorization_url(client_id: str, redirect_uri: str = REDIRECT_URI, state: str = "yt_uploader") -> str:
    base_url = "https://accounts.google.com/o/oauth2/v2/auth"
    params = {
        "client_id": client_id.strip(),
        "redirect_uri": redirect_uri.strip(),
        "response_type": "code",
        "scope": " ".join(YOUTUBE_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state
    }
    return f"{base_url}?{urllib.parse.urlencode(params)}"

def exchange_code_for_tokens(
    client_id: str, 
    client_secret: str, 
    code_or_url: str, 
    redirect_uri: str = REDIRECT_URI
) -> Dict[str, Any]:
    code = parse_auth_code(code_or_url)
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": client_id.strip(),
        "client_secret": client_secret.strip(),
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri.strip(),
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    
    response = requests.post(token_url, data=data, headers=headers, timeout=15)
    if response.status_code != 200:
        error_detail = response.json().get("error_description", response.text)
        raise ValueError(f"Google OAuth Error ({response.status_code}): {error_detail}")
    
    token_data = response.json()
    expires_in = token_data.get("expires_in", 3600)
    expiry = datetime.utcnow() + timedelta(seconds=expires_in)
    token_data["token_expiry"] = expiry.isoformat()
    return token_data

def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> Dict[str, Any]:
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": client_id.strip(),
        "client_secret": client_secret.strip(),
        "refresh_token": refresh_token.strip(),
        "grant_type": "refresh_token",
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    response = requests.post(token_url, data=data, headers=headers, timeout=15)
    if response.status_code != 200:
        raise ValueError(f"Failed to refresh token: {response.text}")
    
    token_data = response.json()
    expires_in = token_data.get("expires_in", 3600)
    token_data["token_expiry"] = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat()
    return token_data

def get_channel_profile_from_token(access_token: str) -> Dict[str, Any]:
    creds = Credentials(token=access_token)
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    
    response = youtube.channels().list(
        part="snippet,statistics",
        mine=True
    ).execute()
    
    items = response.get("items", [])
    if not items:
        raise ValueError("No YouTube channel found for the authenticated Google account.")
    
    ch = items[0]
    snippet = ch.get("snippet", {})
    stats = ch.get("statistics", {})
    thumbnails = snippet.get("thumbnails", {})
    thumb_url = (
        thumbnails.get("high", {}).get("url") or 
        thumbnails.get("medium", {}).get("url") or 
        thumbnails.get("default", {}).get("url") or ""
    )
    
    return {
        "id": ch["id"],
        "title": snippet.get("title", "Unknown Channel"),
        "custom_url": snippet.get("customUrl", ""),
        "thumbnail_url": thumb_url,
        "subscriber_count": int(stats.get("subscriberCount", 0)),
        "video_count": int(stats.get("videoCount", 0))
    }

def get_authenticated_youtube_service(channel_id: str):
    channel = db_get_channel_by_id(channel_id)
    if not channel:
        raise ValueError(f"Channel not found: {channel_id}")
    
    client_id = channel.get("client_id")
    client_secret = channel.get("client_secret")
    access_token = channel.get("access_token")
    refresh_token = channel.get("refresh_token")
    expiry_str = channel.get("token_expiry")
    
    needs_refresh = False
    if expiry_str:
        try:
            expiry_dt = datetime.fromisoformat(expiry_str)
            if datetime.utcnow() >= (expiry_dt - timedelta(minutes=5)):
                needs_refresh = True
        except Exception:
            needs_refresh = True
    else:
        needs_refresh = True
        
    if needs_refresh and refresh_token and client_id and client_secret:
        try:
            refreshed = refresh_access_token(client_id, client_secret, refresh_token)
            access_token = refreshed["access_token"]
            channel["access_token"] = access_token
            channel["token_expiry"] = refreshed["token_expiry"]
            db_save_channel(channel)
        except Exception as e:
            print(f"Warning: Token refresh error: {e}")
            
    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=YOUTUBE_SCOPES
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)
