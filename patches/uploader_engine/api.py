import os
import uuid
import threading
from typing import Optional, Dict, Any, List
import customtkinter as ctk
from tkinter import messagebox
from uploader_engine.database import (
    db_get_channels, db_create_task, db_get_tasks, db_get_setting, db_save_channel
)
from uploader_engine.config import REDIRECT_URI

def get_connected_channels() -> List[Dict[str, Any]]:
    """Returns list of all connected YouTube channels."""
    try:
        return db_get_channels()
    except Exception:
        return []

def open_api_settings_dialog(parent=None, on_saved=None):
    """
    Opens a dialog to configure Google OAuth Client ID and Secret.
    """
    import webbrowser
    dialog = ctk.CTkToplevel(parent)
    dialog.title("⚙️ Google YouTube API Configuration")
    dialog.geometry("620x460")
    dialog.configure(fg_color="#080c14")
    dialog.attributes("-topmost", True)
    dialog.grab_set()
    dialog.focus_force()

    # Title & header
    header_frame = ctk.CTkFrame(dialog, fg_color="transparent")
    header_frame.pack(fill="x", padx=24, pady=(18, 6))
    ctk.CTkLabel(
        header_frame,
        text="⚙️ Google Cloud API Credentials",
        font=ctk.CTkFont(size=18, weight="bold"),
        text_color="#ff0033"
    ).pack(anchor="w")

    ctk.CTkLabel(
        header_frame,
        text="Required to authenticate YouTube channels and enable automated video uploads.",
        font=ctk.CTkFont(size=11),
        text_color="#94a3b8"
    ).pack(anchor="w", pady=(2, 0))

    # Helper info card
    info_card = ctk.CTkFrame(dialog, fg_color="#101726", corner_radius=10, border_width=1, border_color="#1e293b")
    info_card.pack(fill="x", padx=24, pady=(6, 12))

    info_text = (
        "📌 Quick Setup Steps:\n"
        "1. Open Google Cloud Console & select or create a project.\n"
        "2. Enable 'YouTube Data API v3'.\n"
        "3. Go to 'Credentials' > 'Create Credentials' > 'OAuth client ID' (Web Application).\n"
        f"4. Add Authorized Redirect URI:\n   {REDIRECT_URI}\n"
        "5. Copy & Paste the Client ID and Secret below, then click Save."
    )
    ctk.CTkLabel(
        info_card,
        text=info_text,
        font=ctk.CTkFont(size=11),
        justify="left",
        text_color="#bae6fd"
    ).pack(padx=14, pady=10, anchor="w")

    # Form
    form = ctk.CTkFrame(dialog, fg_color="transparent")
    form.pack(fill="x", padx=24, pady=2)

    ctk.CTkLabel(form, text="Google Client ID:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#f8fafc").pack(anchor="w", pady=(2, 2))
    client_id_ent = ctk.CTkEntry(form, width=540, placeholder_text="e.g. 123456789-xxxxxx.apps.googleusercontent.com")
    cur_cid = db_get_setting("google_client_id")
    if cur_cid:
        client_id_ent.insert(0, cur_cid)
    client_id_ent.pack(fill="x", pady=(0, 10))

    ctk.CTkLabel(form, text="Google Client Secret:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#f8fafc").pack(anchor="w", pady=(2, 2))

    sec_row = ctk.CTkFrame(form, fg_color="transparent")
    sec_row.pack(fill="x", pady=(0, 10))
    client_sec_ent = ctk.CTkEntry(sec_row, show="*", placeholder_text="e.g. GOCSPX-xxxxxx")
    cur_sec = db_get_setting("google_client_secret")
    if cur_sec:
        client_sec_ent.insert(0, cur_sec)
    client_sec_ent.pack(side="left", fill="x", expand=True)

    def toggle_show():
        if client_sec_ent.cget("show") == "*":
            client_sec_ent.configure(show="")
            btn_toggle.configure(text="👁️ Hide")
        else:
            client_sec_ent.configure(show="*")
            btn_toggle.configure(text="👁️ Show")

    btn_toggle = ctk.CTkButton(sec_row, text="👁️ Show", width=75, fg_color="#1e293b", hover_color="#334155", command=toggle_show)
    btn_toggle.pack(side="left", padx=(8, 0))

    # Action Buttons
    btn_bar = ctk.CTkFrame(dialog, fg_color="transparent")
    btn_bar.pack(fill="x", padx=24, pady=(14, 10))

    def open_gconsole():
        webbrowser.open("https://console.cloud.google.com/apis/credentials")

    ctk.CTkButton(
        btn_bar,
        text="🌐 Open Google Console",
        command=open_gconsole,
        fg_color="#0f766e",
        hover_color="#115e59",
        width=165,
        height=38
    ).pack(side="left")

    def save():
        cid = client_id_ent.get().strip()
        csec = client_sec_ent.get().strip()
        if not cid or not csec:
            messagebox.showerror("Required", "Both Client ID and Client Secret are required.")
            return
        from uploader_engine.database import db_set_setting
        db_set_setting("google_client_id", cid)
        db_set_setting("google_client_secret", csec)
        dialog.destroy()
        messagebox.showinfo("Saved", "✅ Google API credentials saved successfully!")
        if on_saved:
            try:
                on_saved()
            except Exception:
                pass

    ctk.CTkButton(
        btn_bar,
        text="💾 Save Credentials",
        command=save,
        fg_color="#ff0033",
        hover_color="#d4002a",
        height=38,
        font=ctk.CTkFont(weight="bold")
    ).pack(side="right", padx=(8, 0))

    ctk.CTkButton(
        btn_bar,
        text="Cancel",
        command=dialog.destroy,
        fg_color="#1e293b",
        hover_color="#334155",
        width=85,
        height=38
    ).pack(side="right")


def open_connect_channel_dialog(parent=None, on_success=None):
    """
    Opens the interactive dialog to authenticate and link a new YouTube Channel via Google OAuth.
    """
    import webbrowser
    client_id = db_get_setting("google_client_id")
    client_secret = db_get_setting("google_client_secret")

    if not client_id or not client_secret:
        res = messagebox.askyesno(
            "API Credentials Required",
            "Google Client ID & Secret are required to link a YouTube Channel.\n\n"
            "Would you like to configure your Google API credentials now?"
        )
        if res:
            open_api_settings_dialog(
                parent=parent,
                on_saved=lambda: open_connect_channel_dialog(parent=parent, on_success=on_success)
            )
        return

    from uploader_engine.auth import generate_authorization_url, exchange_code_for_tokens, get_channel_profile_from_token
    auth_url = generate_authorization_url(client_id, redirect_uri=REDIRECT_URI)

    dialog = ctk.CTkToplevel(parent)
    dialog.title("➕ Connect YouTube Channel")
    dialog.geometry("660x540")
    dialog.configure(fg_color="#080c14")
    dialog.attributes("-topmost", True)
    dialog.focus_force()

    # Header with API settings quick action
    header_row = ctk.CTkFrame(dialog, fg_color="transparent")
    header_row.pack(fill="x", padx=20, pady=(16, 4))

    ctk.CTkLabel(header_row, text="⚡ Connect YouTube Channel", font=ctk.CTkFont(size=18, weight="bold"), text_color="#ff0033").pack(side="left")

    def edit_api_creds():
        dialog.destroy()
        open_api_settings_dialog(parent=parent, on_saved=lambda: open_connect_channel_dialog(parent=parent, on_success=on_success))

    ctk.CTkButton(
        header_row, text="⚙️ API Config", width=95, height=28,
        fg_color="#1e293b", hover_color="#334155", font=ctk.CTkFont(size=11),
        command=edit_api_creds
    ).pack(side="right")

    guide_box = ctk.CTkFrame(dialog, fg_color="#101726", corner_radius=10)
    guide_box.pack(fill="x", padx=20, pady=6)
    guide_text = (
        "📌 Quick Channel Linking Guide:\n"
        "1. Click '🌐 Open' or '📋 Copy' below to authenticate in your browser.\n"
        "2. Grant permissions in your Google/YouTube account.\n"
        "3. Copy the redirected URL (or code) from your browser address bar.\n"
        "4. Paste it in Step 2 below and click '⚡ Link Channel'."
    )
    ctk.CTkLabel(guide_box, text=guide_text, font=ctk.CTkFont(size=11), justify="left", text_color="#bae6fd").pack(padx=14, pady=10, anchor="w")

    ctk.CTkLabel(dialog, text="Step 1: Authorization Link", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8").pack(padx=20, anchor="w", pady=(8, 2))
    link_frame = ctk.CTkFrame(dialog, fg_color="transparent")
    link_frame.pack(fill="x", padx=20)
    link_entry = ctk.CTkEntry(link_frame, width=420)
    link_entry.insert(0, auth_url)
    link_entry.configure(state="readonly")
    link_entry.pack(side="left", fill="x", expand=True)

    def open_link():
        webbrowser.open(auth_url)

    btn_open = ctk.CTkButton(link_frame, text="🌐 Open", width=75, command=open_link, fg_color="#2563eb", hover_color="#1d4ed8")
    btn_open.pack(side="left", padx=(8, 0))

    def copy_link():
        dialog.clipboard_clear()
        dialog.clipboard_append(auth_url)
        btn_copy.configure(text="✓ Copied!")
        dialog.after(2000, lambda: btn_copy.configure(text="📋 Copy"))

    btn_copy = ctk.CTkButton(link_frame, text="📋 Copy", width=75, command=copy_link, fg_color="#ff0033", hover_color="#d4002a")
    btn_copy.pack(side="left", padx=(6, 0))

    ctk.CTkLabel(dialog, text="Step 2: Paste Redirected URL or Authorization Code", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8").pack(padx=20, anchor="w", pady=(12, 2))
    code_entry = ctk.CTkTextbox(dialog, height=80, fg_color="#101726")
    code_entry.pack(fill="x", padx=20, pady=4)

    def complete_connection():
        code_or_url = code_entry.get("1.0", "end-1c").strip()
        if not code_or_url:
            messagebox.showerror("Input Required", "Please paste the redirected URL or code from your browser.")
            return

        btn_submit.configure(text="Connecting...", state="disabled")
        dialog.update()

        def bg_exchange():
            try:
                token_data = exchange_code_for_tokens(client_id, client_secret, code_or_url, REDIRECT_URI)
                profile = get_channel_profile_from_token(token_data["access_token"])

                channel_record = {
                    "id": profile["id"],
                    "title": profile["title"],
                    "custom_url": profile["custom_url"],
                    "thumbnail_url": profile["thumbnail_url"],
                    "subscriber_count": profile["subscriber_count"],
                    "video_count": profile["video_count"],
                    "access_token": token_data.get("access_token"),
                    "refresh_token": token_data.get("refresh_token"),
                    "token_expiry": token_data.get("token_expiry"),
                    "client_id": client_id,
                    "client_secret": client_secret
                }
                db_save_channel(channel_record)
                dialog.after(0, lambda: on_finish_ok(profile))
            except Exception as ex:
                dialog.after(0, lambda err=ex: on_finish_err(err))

        def on_finish_ok(profile):
            dialog.destroy()
            messagebox.showinfo("Success!", f"🎉 Successfully connected YouTube channel:\n{profile['title']}")
            if on_success:
                try:
                    on_success(profile)
                except Exception:
                    pass

        def on_finish_err(err):
            btn_submit.configure(text="⚡ Link Channel", state="normal")
            messagebox.showerror("Auth Error", f"Failed to authenticate channel:\n{err}")

        threading.Thread(target=bg_exchange, daemon=True).start()

    btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
    btn_row.pack(fill="x", padx=20, pady=(14, 10))

    btn_submit = ctk.CTkButton(btn_row, text="⚡ Link Channel", command=complete_connection, fg_color="#ff0033", hover_color="#d4002a", height=38, font=ctk.CTkFont(weight="bold"))
    btn_submit.pack(side="left", fill="x", expand=True, padx=(0, 8))

    ctk.CTkButton(btn_row, text="Cancel", command=dialog.destroy, fg_color="#1e293b", hover_color="#334155", width=90, height=38).pack(side="right")


def queue_video_for_upload(
    video_path: str,
    title: str = "",
    description: str = "",
    tags: Optional[List[str]] = None,
    category_id: str = "22",
    privacy_status: str = "private",
    publish_at: Optional[str] = None,
    scheduled_upload_time: Optional[str] = None,
    timezone_name: str = "",
    channel_id: Optional[str] = None,
    made_for_kids: bool = False,
    thumbnail_path: Optional[str] = None,
) -> str:
    """
    Submits a video file directly into the YouTube Bulk Uploader Queue.
    If channel_id is not specified, uses the first active channel or default.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    channels = db_get_channels()
    if not channels:
        raise ValueError("No YouTube channel connected! Please connect a channel first in 🚀 Bulk Video Uploader.")

    target_channel_id = channel_id
    if not target_channel_id or not any(c["id"] == target_channel_id for c in channels):
        target_channel_id = channels[0]["id"]

    fname = os.path.basename(video_path)
    fsize = os.path.getsize(video_path)
    clean_title = (title or os.path.splitext(fname)[0].replace("_", " ").replace("-", " ")).strip()[:100]

    task_data = {
        "id": str(uuid.uuid4()),
        "channel_id": target_channel_id,
        "video_path": os.path.abspath(video_path),
        "original_filename": fname,
        "file_size": fsize,
        "title": clean_title,
        "description": description or "",
        "thumbnail_path": os.path.abspath(thumbnail_path) if thumbnail_path and os.path.exists(thumbnail_path) else None,
        "tags": tags or [],
        "category_id": category_id or "22",
        "privacy_status": privacy_status or "private",
        "publish_at": publish_at,
        "scheduled_upload_time": scheduled_upload_time,
        "timezone_name": timezone_name or "",
        "made_for_kids": made_for_kids,
        "status": "pending"
    }

    task_id = db_create_task(task_data)
    print(f"[UploaderAPI] Video queued for YouTube upload: '{clean_title}' (Task ID: {task_id})")
    return task_id


def show_quick_upload_modal(
    parent=None,
    video_path: str = "",
    default_title: str = "",
    default_tags: str = "",
    default_desc: str = "",
    on_queued_callback=None
):
    """
    Opens an elegant modal dialog to select channel, add channels, choose visibility, and queue upload.
    """
    channels = db_get_channels()
    if not channels:
        res = messagebox.askyesno(
            "Channel Required",
            "No YouTube channels are connected yet.\n\nWould you like to connect a YouTube Channel right now?"
        )
        if res:
            open_connect_channel_dialog(parent, on_success=lambda p: show_quick_upload_modal(
                parent=parent,
                video_path=video_path,
                default_title=default_title,
                default_tags=default_tags,
                default_desc=default_desc,
                on_queued_callback=on_queued_callback
            ))
        return

    dialog = ctk.CTkToplevel(parent)
    dialog.title("📤 Send Video to YouTube Channel")
    dialog.geometry("580x600")
    dialog.resizable(False, False)
    dialog.configure(fg_color="#080c14")
    dialog.attributes("-topmost", True)
    dialog.focus_force()

    # Header
    ctk.CTkLabel(
        dialog, text="📤 Upload Video to YouTube",
        font=ctk.CTkFont(size=18, weight="bold"), text_color="#ff0033"
    ).pack(padx=20, pady=(15, 2))

    fname = os.path.basename(video_path) if video_path else "video.mp4"
    ctk.CTkLabel(
        dialog, text=f"File: {fname}",
        font=ctk.CTkFont(size=11), text_color="#94a3b8"
    ).pack(padx=20, pady=(0, 10))

    form = ctk.CTkFrame(dialog, fg_color="#101726", corner_radius=12)
    form.pack(fill="both", expand=True, padx=20, pady=5)

    # Channel Picker & Add Channel Row
    ctk.CTkLabel(form, text="Choose YouTube Channel:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8").pack(anchor="w", padx=16, pady=(10, 2))
    ch_row = ctk.CTkFrame(form, fg_color="transparent")
    ch_row.pack(fill="x", padx=16, pady=(0, 8))

    ch_menu = ctk.CTkOptionMenu(ch_row, values=["Loading channels..."], width=360, height=32, fg_color="#1e293b")
    ch_menu.pack(side="left", fill="x", expand=True, padx=(0, 6))

    channel_map = {}

    def refresh_channel_list(select_id=None):
        nonlocal channel_map
        cur_channels = db_get_channels()
        channel_names = [f"{c['title']} ({c.get('subscriber_count', 0):,} subs)" for c in cur_channels]
        channel_map = {f"{c['title']} ({c.get('subscriber_count', 0):,} subs)": c["id"] for c in cur_channels}
        if channel_names:
            ch_menu.configure(values=channel_names)
            target_name = channel_names[0]
            if select_id:
                for name, cid in channel_map.items():
                    if cid == select_id:
                        target_name = name
                        break
            ch_menu.set(target_name)
        else:
            ch_menu.configure(values=["No channels found"])
            ch_menu.set("No channels found")

    def on_add_channel_click():
        open_connect_channel_dialog(dialog, on_success=lambda prof: refresh_channel_list(prof.get("id")))

    btn_add_ch = ctk.CTkButton(
        ch_row, text="➕ Add Channel", width=110, height=32,
        fg_color="#2563eb", hover_color="#1d4ed8", font=ctk.CTkFont(size=11, weight="bold"),
        command=on_add_channel_click
    )
    btn_add_ch.pack(side="right")

    refresh_channel_list()

    # Title
    ctk.CTkLabel(form, text="Video Title:", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=16, pady=(4, 2))
    ent_title = ctk.CTkEntry(form, width=500, height=32)
    ent_title.insert(0, default_title or os.path.splitext(fname)[0].replace("_", " ").title())
    ent_title.pack(padx=16, pady=(0, 8))

    # Visibility & Category Row
    row_vis = ctk.CTkFrame(form, fg_color="transparent")
    row_vis.pack(fill="x", padx=16, pady=4)

    ctk.CTkLabel(row_vis, text="Visibility:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
    vis_menu = ctk.CTkOptionMenu(row_vis, values=["public", "unlisted", "private"], width=130, height=28, fg_color="#1e293b")
    vis_menu.set("public")
    vis_menu.pack(side="left", padx=8)

    cb_kids = ctk.CTkCheckBox(row_vis, text="Made for Kids", font=ctk.CTkFont(size=11))
    cb_kids.pack(side="right")

    # Description
    ctk.CTkLabel(form, text="Description:", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=16, pady=(4, 2))
    txt_desc = ctk.CTkTextbox(form, width=500, height=80, fg_color="#0b1120")
    txt_desc.insert("1.0", default_desc or "Created with AI Studio Suite")
    txt_desc.pack(padx=16, pady=(0, 8))

    # Tags
    ctk.CTkLabel(form, text="Tags (comma separated):", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=16, pady=(4, 2))
    ent_tags = ctk.CTkEntry(form, width=500, height=32)
    ent_tags.insert(0, default_tags or "")
    ent_tags.pack(padx=16, pady=(0, 10))

    # Action Buttons
    btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
    btn_row.pack(fill="x", padx=20, pady=(10, 15))

    def _submit_queue():
        selected_ch_name = ch_menu.get()
        ch_id = channel_map.get(selected_ch_name)
        if not ch_id:
            all_chs = db_get_channels()
            if all_chs:
                ch_id = all_chs[0]["id"]
            else:
                messagebox.showerror("Error", "No channel selected.")
                return

        title = ent_title.get().strip() or fname
        desc = txt_desc.get("1.0", "end-1c").strip()
        tags_raw = ent_tags.get().strip()
        tag_list = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
        visibility = vis_menu.get()
        kids = bool(cb_kids.get())

        try:
            tid = queue_video_for_upload(
                video_path=video_path,
                title=title,
                description=desc,
                tags=tag_list,
                privacy_status=visibility,
                channel_id=ch_id,
                made_for_kids=kids
            )
            dialog.destroy()
            messagebox.showinfo(
                "Queued for Upload",
                f"✅ Video '{title}' successfully queued for upload!\n\nTarget Channel: {selected_ch_name}\nStatus: Bulk Uploader is active."
            )
            if on_queued_callback:
                on_queued_callback(tid)
        except Exception as ex:
            messagebox.showerror("Upload Error", f"Failed to queue video for upload:\n{ex}")

    btn_upload = ctk.CTkButton(
        btn_row, text="⚡ Send to Upload Queue", command=_submit_queue,
        fg_color="#ff0033", hover_color="#d4002a", height=38, font=ctk.CTkFont(weight="bold")
    )
    btn_upload.pack(side="left", fill="x", expand=True, padx=(0, 8))

    ctk.CTkButton(
        btn_row, text="Cancel", command=dialog.destroy,
        fg_color="#1e293b", hover_color="#334155", height=38, width=100
    ).pack(side="right")
