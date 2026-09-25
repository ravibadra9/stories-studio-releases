import os
import uuid
import threading
from typing import Optional, Dict, Any, List
import customtkinter as ctk
from tkinter import messagebox

# Bulletproof imports with fallback
try:
    from uploader_engine.database import (
        db_get_channels, db_create_task, db_get_tasks, db_get_setting, db_save_channel
    )
    from uploader_engine.config import REDIRECT_URI
except Exception:
    try:
        from .database import (
            db_get_channels, db_create_task, db_get_tasks, db_get_setting, db_save_channel
        )
        from .config import REDIRECT_URI
    except Exception:
        import sqlite3
        from pathlib import Path
        _LOCAL_APP = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "StoriesStudio"
        _DB_P = _LOCAL_APP / "uploader.db"
        _DB_P.parent.mkdir(parents=True, exist_ok=True)
        REDIRECT_URI = "http://localhost:8000/api/channels/auth/callback"

        def _get_conn():
            c = sqlite3.connect(str(_DB_P))
            c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            c.execute("""CREATE TABLE IF NOT EXISTS channels (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, custom_url TEXT, thumbnail_url TEXT,
                subscriber_count INTEGER DEFAULT 0, video_count INTEGER DEFAULT 0,
                access_token TEXT, refresh_token TEXT, token_expiry TEXT,
                client_id TEXT, client_secret TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS upload_tasks (
                id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, video_path TEXT NOT NULL,
                original_filename TEXT NOT NULL, file_size INTEGER DEFAULT 0, title TEXT NOT NULL,
                description TEXT DEFAULT '', thumbnail_path TEXT, tags TEXT DEFAULT '[]',
                category_id TEXT DEFAULT '22', privacy_status TEXT DEFAULT 'private',
                publish_at TEXT, scheduled_upload_time TEXT, timezone_name TEXT,
                made_for_kids INTEGER DEFAULT 0, status TEXT DEFAULT 'pending',
                progress_percent REAL DEFAULT 0.0, bytes_uploaded INTEGER DEFAULT 0,
                speed_mbps REAL DEFAULT 0.0, youtube_video_id TEXT, error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, completed_at TIMESTAMP
            )""")
            c.commit()
            return c

        def db_get_setting(key: str, default: str = "") -> str:
            try:
                conn = _get_conn()
                cur = conn.cursor()
                cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
                row = cur.fetchone()
                conn.close()
                return row[0] if row else default
            except Exception:
                return default

        def db_set_setting(key: str, value: str):
            try:
                conn = _get_conn()
                cur = conn.cursor()
                cur.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
                conn.commit()
                conn.close()
            except Exception:
                pass

        def db_get_channels():
            try:
                conn = _get_conn()
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("SELECT * FROM channels ORDER BY created_at DESC")
                rows = cur.fetchall()
                res = [dict(r) for r in rows]
                conn.close()
                return res
            except Exception:
                return []

        def db_save_channel(data: dict):
            try:
                conn = _get_conn()
                cur = conn.cursor()
                cur.execute("""INSERT INTO channels (id, title, custom_url, thumbnail_url, subscriber_count, video_count, access_token, refresh_token, token_expiry, client_id, client_secret)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title = excluded.title, custom_url = excluded.custom_url, thumbnail_url = excluded.thumbnail_url,
                        subscriber_count = excluded.subscriber_count, video_count = excluded.video_count,
                        access_token = excluded.access_token, refresh_token = excluded.refresh_token,
                        token_expiry = excluded.token_expiry, client_id = excluded.client_id, client_secret = excluded.client_secret,
                        updated_at = CURRENT_TIMESTAMP""", (
                    data["id"], data["title"], data.get("custom_url", ""), data.get("thumbnail_url", ""),
                    data.get("subscriber_count", 0), data.get("video_count", 0),
                    data.get("access_token", ""), data.get("refresh_token", ""),
                    data.get("token_expiry", ""), data.get("client_id", ""), data.get("client_secret", "")
                ))
                conn.commit()
                conn.close()
            except Exception:
                pass

        def db_create_task(t: dict) -> str:
            tid = t.get("id") or str(uuid.uuid4())
            try:
                conn = _get_conn()
                cur = conn.cursor()
                import json
                cur.execute("""INSERT INTO upload_tasks (id, channel_id, video_path, original_filename, file_size, title, description, thumbnail_path, tags, category_id, privacy_status, publish_at, scheduled_upload_time, timezone_name, made_for_kids, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                    tid, t["channel_id"], t["video_path"], t.get("original_filename", ""),
                    t.get("file_size", 0), t.get("title", ""), t.get("description", ""),
                    t.get("thumbnail_path"), json.dumps(t.get("tags", [])),
                    t.get("category_id", "22"), t.get("privacy_status", "private"),
                    t.get("publish_at"), t.get("scheduled_upload_time"), t.get("timezone_name", ""),
                    1 if t.get("made_for_kids") else 0, t.get("status", "pending")
                ))
                conn.commit()
                conn.close()
            except Exception:
                pass
            return tid

        def db_get_tasks():
            try:
                conn = _get_conn()
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("SELECT * FROM upload_tasks ORDER BY created_at DESC")
                rows = cur.fetchall()
                import json
                tasks = []
                for r in rows:
                    td = dict(r)
                    try: td["tags"] = json.loads(td["tags"])
                    except Exception: td["tags"] = []
                    tasks.append(td)
                conn.close()
                return tasks
            except Exception:
                return []

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


def sync_live_streamer_accounts():
    """
    Auto-discovers and imports any existing channel accounts and client_secrets.json
    from Live Streamer (~/.live_streamer_rdp) so the user never has to re-authenticate!
    """
    try:
        ls_dir = os.path.expanduser("~/.live_streamer_rdp")
        if not os.path.exists(ls_dir):
            return 0

        # 1. Sync client_secrets.json if not already present
        sec_src = os.path.join(ls_dir, "client_secrets.json")
        sec_dest = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "StoriesStudio", "client_secrets.json")
        if os.path.exists(sec_src) and not os.path.exists(sec_dest):
            try:
                import shutil
                shutil.copy2(sec_src, sec_dest)
            except Exception:
                pass

        # 2. Sync accounts
        acc_file = os.path.join(ls_dir, "accounts.json")
        if not os.path.exists(acc_file):
            return 0

        import json
        with open(acc_file, "r", encoding="utf-8") as f:
            accounts = json.load(f)

        imported = 0
        for acc in accounts:
            cid = acc.get("id")
            token_file = acc.get("token_file", "")
            if not cid or not token_file or not os.path.exists(token_file):
                continue
            with open(token_file, "r", encoding="utf-8") as tf:
                tok_data = json.load(tf)
            ch_record = {
                "id": cid,
                "title": acc.get("title", "YouTube Channel"),
                "custom_url": acc.get("custom_url", ""),
                "thumbnail_url": acc.get("avatar_url", ""),
                "subscriber_count": 0,
                "video_count": 0,
                "access_token": tok_data.get("token", ""),
                "refresh_token": tok_data.get("refresh_token", ""),
                "token_expiry": tok_data.get("expiry", ""),
                "client_id": tok_data.get("client_id", ""),
                "client_secret": tok_data.get("client_secret", "")
            }
            db_save_channel(ch_record)
            if tok_data.get("client_id") and not db_get_setting("google_client_id"):
                db_set_setting("google_client_id", tok_data["client_id"])
            if tok_data.get("client_secret") and not db_get_setting("google_client_secret"):
                db_set_setting("google_client_secret", tok_data["client_secret"])
            imported += 1

        return imported
    except Exception as e:
        print(f"[OTA] Notice syncing Live Streamer accounts: {e}")
        return 0


def open_connect_channel_dialog(parent=None, on_success=None):
    """
    Dedicated dialog matching Live Streamer for connecting YouTube accounts safely via
    Remote / Anti-Detect Browser OAuth flow (Browse Secrets -> Copy Auth Link -> Paste Redirect Code).
    Supports multiple channels.
    """
    import webbrowser
    import json
    from uploader_engine.auth import (
        generate_authorization_url, exchange_code_for_tokens,
        get_channel_profile_from_token, parse_auth_code
    )

    # Auto-sync Live Streamer accounts if available
    sync_live_streamer_accounts()

    dialog = ctk.CTkToplevel(parent)
    dialog.title("Connect YouTube Channel (Anti-Detect & Multi-Account)")
    dialog.geometry("660x780")
    dialog.minsize(600, 680)
    dialog.configure(fg_color="#080c14")
    dialog.attributes("-topmost", True)
    dialog.focus_force()

    # Find secrets file
    def find_existing_secrets_file():
        candidates = [
            os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "StoriesStudio", "client_secrets.json"),
            os.path.expanduser("~/.live_streamer_rdp/client_secrets.json")
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        return ""

    state = {
        "secrets_file": find_existing_secrets_file(),
        "client_id": db_get_setting("google_client_id"),
        "client_secret": db_get_setting("google_client_secret"),
        "redirect_uri": "http://localhost:8080/",
        "auth_url": ""
    }

    # If secrets file exists, parse client_id and client_secret if needed
    if state["secrets_file"] and os.path.exists(state["secrets_file"]):
        try:
            with open(state["secrets_file"], "r", encoding="utf-8") as f:
                s_data = json.load(f)
            cfg = s_data.get("installed") or s_data.get("web") or s_data
            if cfg.get("client_id"):
                state["client_id"] = cfg["client_id"].strip()
                db_set_setting("google_client_id", state["client_id"])
            if cfg.get("client_secret"):
                state["client_secret"] = cfg["client_secret"].strip()
                db_set_setting("google_client_secret", state["client_secret"])
            uris = cfg.get("redirect_uris", [])
            if uris:
                state["redirect_uri"] = uris[0]
        except Exception:
            pass

    scroll = ctk.CTkScrollableFrame(dialog, fg_color="transparent")
    scroll.pack(fill="both", expand=True, padx=16, pady=16)

    # Header Card
    header = ctk.CTkFrame(scroll, fg_color="#181824", corner_radius=10)
    header.pack(fill="x", pady=(0, 10))

    ctk.CTkLabel(
        header,
        text="🔗 Connect YouTube Channel (Anti-Detect / IP-Safe)",
        font=ctk.CTkFont(size=16, weight="bold"),
        text_color="#ffffff"
    ).pack(anchor="w", padx=16, pady=(12, 2))

    ctk.CTkLabel(
        header,
        text="No RDP browser will open. You can copy the login link directly into your anti-detect browser profile.",
        font=ctk.CTkFont(size=11),
        text_color="#94a3b8"
    ).pack(anchor="w", padx=16, pady=(0, 12))

    # STEP 1: client_secrets.json Card
    s1_card = ctk.CTkFrame(scroll, fg_color="#181824", corner_radius=10)
    s1_card.pack(fill="x", pady=6)

    ctk.CTkLabel(
        s1_card,
        text="Step 1: Google Cloud client_secrets.json",
        font=ctk.CTkFont(size=13, weight="bold"),
        text_color="#cbd5e1"
    ).pack(anchor="w", padx=16, pady=(12, 4))

    sec_row = ctk.CTkFrame(s1_card, fg_color="transparent")
    sec_row.pack(fill="x", padx=16, pady=(0, 10))

    has_secrets = bool((state["secrets_file"] and os.path.exists(state["secrets_file"])) or (state["client_id"] and state["client_secret"]))
    init_txt = f"✓ Using: {os.path.basename(state['secrets_file']) if state['secrets_file'] else 'Configured Credentials'}" if has_secrets else "No client_secrets.json selected"
    init_col = "#10b981" if has_secrets else "#94a3b8"

    secrets_lbl = ctk.CTkLabel(
        sec_row,
        text=init_txt,
        font=ctk.CTkFont(size=11),
        text_color=init_col,
        anchor="w"
    )
    secrets_lbl.pack(side="left", fill="x", expand=True)

    def browse_secrets():
        from tkinter import filedialog
        fp = filedialog.askopenfilename(
            title="Select Google Cloud client_secrets.json",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")]
        )
        if fp and os.path.exists(fp):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    s_data = json.load(f)
                cfg = s_data.get("installed") or s_data.get("web") or s_data
                cid = cfg.get("client_id", "").strip()
                csec = cfg.get("client_secret", "").strip()
                if not cid or not csec:
                    messagebox.showerror("Invalid JSON", "Selected JSON does not contain client_id and client_secret.")
                    return
                state["client_id"] = cid
                state["client_secret"] = csec
                db_set_setting("google_client_id", cid)
                db_set_setting("google_client_secret", csec)
                uris = cfg.get("redirect_uris", [])
                if uris:
                    state["redirect_uri"] = uris[0]

                # Copy to local appdata
                save_p = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "StoriesStudio", "client_secrets.json")
                os.makedirs(os.path.dirname(save_p), exist_ok=True)
                import shutil
                shutil.copy2(fp, save_p)
                state["secrets_file"] = save_p

                secrets_lbl.configure(text=f"✓ Using: {os.path.basename(fp)}", text_color="#10b981")
                messagebox.showinfo("Loaded", f"Loaded credentials from {os.path.basename(fp)} successfully!")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load JSON file: {e}")

    ctk.CTkButton(
        sec_row,
        text="Browse JSON...",
        width=120,
        height=30,
        font=ctk.CTkFont(size=11),
        fg_color="#3b82f6",
        hover_color="#2563eb",
        command=browse_secrets
    ).pack(side="right")

    # STEP 2: Generate & Copy Link Card
    s2_card = ctk.CTkFrame(scroll, fg_color="#181824", corner_radius=10)
    s2_card.pack(fill="x", pady=6)

    ctk.CTkLabel(
        s2_card,
        text="Step 2: Generate & Copy Google Auth Link",
        font=ctk.CTkFont(size=13, weight="bold"),
        text_color="#cbd5e1"
    ).pack(anchor="w", padx=16, pady=(12, 4))

    ctk.CTkLabel(
        s2_card,
        text="Click below to generate a secure Google OAuth link for your YouTube channel:",
        font=ctk.CTkFont(size=11),
        text_color="#94a3b8"
    ).pack(anchor="w", padx=16, pady=(0, 6))

    gen_btn_row = ctk.CTkFrame(s2_card, fg_color="transparent")
    gen_btn_row.pack(fill="x", padx=16, pady=4)

    def copy_link_to_clipboard():
        if state["auth_url"]:
            dialog.clipboard_clear()
            dialog.clipboard_append(state["auth_url"])
            copy_btn.configure(text="✓ Copied!", fg_color="#059669")
            dialog.after(2000, lambda: copy_btn.configure(text="📋 Copy Link", fg_color="#10b981"))

    def generate_auth_link():
        cid = state.get("client_id") or db_get_setting("google_client_id")
        csec = state.get("client_secret") or db_get_setting("google_client_secret")
        if not cid or not csec:
            messagebox.showerror("Secrets Missing", "Please select your Google Cloud client_secrets.json in Step 1 first (or click Browse JSON).")
            return
        try:
            auth_url = generate_authorization_url(cid, redirect_uri=state.get("redirect_uri", "http://localhost:8080/"))
            state["auth_url"] = auth_url
            url_display.delete(0, "end")
            url_display.insert(0, auth_url)
            copy_btn.configure(state="normal")
            open_btn.configure(state="normal")
            copy_link_to_clipboard()
            messagebox.showinfo(
                "Link Generated & Copied!",
                "Google Auth link has been generated and copied to your clipboard!\n\n"
                "Now switch to your Anti-Detect browser profile, paste the link in the address bar, and click 'Allow'."
            )
        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate authorization URL: {e}")

    gen_link_btn = ctk.CTkButton(
        gen_btn_row,
        text="⚡ Generate Authorization Link",
        height=34,
        font=ctk.CTkFont(size=12, weight="bold"),
        fg_color="#e11d48",
        hover_color="#be123c",
        command=generate_auth_link
    )
    gen_link_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

    copy_btn = ctk.CTkButton(
        gen_btn_row,
        text="📋 Copy Link",
        height=34,
        width=100,
        font=ctk.CTkFont(size=12, weight="bold"),
        fg_color="#10b981",
        hover_color="#059669",
        state="normal" if state.get("auth_url") else "disabled",
        command=copy_link_to_clipboard
    )
    copy_btn.pack(side="right")

    def open_link_in_browser():
        if state.get("auth_url"):
            webbrowser.open(state["auth_url"])

    open_btn = ctk.CTkButton(
        gen_btn_row,
        text="🌐 Open",
        height=34,
        width=80,
        font=ctk.CTkFont(size=12, weight="bold"),
        fg_color="#2563eb",
        hover_color="#1d4ed8",
        state="normal" if state.get("auth_url") else "disabled",
        command=open_link_in_browser
    )
    open_btn.pack(side="right", padx=(0, 6))

    url_display = ctk.CTkEntry(
        s2_card,
        placeholder_text="Google Auth link will appear here...",
        height=32,
        font=ctk.CTkFont(size=10)
    )
    url_display.pack(fill="x", padx=16, pady=(4, 12))

    # STEP 3: Approval Instruction Card (Warm Amber)
    s3_card = ctk.CTkFrame(scroll, fg_color="#101018", corner_radius=10)
    s3_card.pack(fill="x", pady=6)

    ctk.CTkLabel(
        s3_card,
        text="Step 3: Approve in your Anti-Detect Browser Profile",
        font=ctk.CTkFont(size=12, weight="bold"),
        text_color="#f59e0b"
    ).pack(anchor="w", padx=16, pady=(10, 2))

    instructions = (
        "1. Go to your Anti-Detect browser profile where your YouTube channel is logged in.\n"
        "2. Paste the copied link into the address bar and press Enter.\n"
        "3. Choose your YouTube Channel account and click 'Allow'.\n"
        "4. Google will redirect to 'http://localhost:8080/?code=4/0A...' (or http://localhost:8000/...). \n"
        "5. Copy that entire URL (or the code) from your browser address bar and paste it below!"
    )
    ctk.CTkLabel(
        s3_card,
        text=instructions,
        font=ctk.CTkFont(size=11),
        text_color="#cbd5e1",
        justify="left"
    ).pack(anchor="w", padx=16, pady=(0, 10))

    # STEP 4: Complete Verification Card
    s4_card = ctk.CTkFrame(scroll, fg_color="#181824", corner_radius=10)
    s4_card.pack(fill="x", pady=6)

    ctk.CTkLabel(
        s4_card,
        text="Step 4: Paste Redirected URL or Code & Complete",
        font=ctk.CTkFont(size=13, weight="bold"),
        text_color="#cbd5e1"
    ).pack(anchor="w", padx=16, pady=(12, 4))

    code_entry = ctk.CTkEntry(
        s4_card,
        placeholder_text="Paste 'http://localhost:8080/?code=4/0A...' or code here",
        height=36,
        font=ctk.CTkFont(size=11)
    )
    code_entry.pack(fill="x", padx=16, pady=4)

    def finish_connection():
        inp = code_entry.get().strip()
        if not inp:
            messagebox.showerror("Code Required", "Please paste the redirect URL or code from your browser.")
            return

        cid = state.get("client_id") or db_get_setting("google_client_id")
        csec = state.get("client_secret") or db_get_setting("google_client_secret")
        if not cid or not csec:
            messagebox.showerror("Credentials Missing", "Please select client_secrets.json first.")
            return

        complete_btn.configure(text="Verifying & Connecting...", state="disabled")
        dialog.update()

        def bg_task():
            try:
                redirect_uri = state.get("redirect_uri", "http://localhost:8080/")
                token_data = exchange_code_for_tokens(cid, csec, inp, redirect_uri=redirect_uri)
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
                    "client_id": cid,
                    "client_secret": csec
                }
                db_save_channel(channel_record)

                def on_done():
                    complete_btn.configure(text="✅ Complete Channel Connection", state="normal")
                    code_entry.delete(0, "end")
                    refresh_connected_channels()
                    messagebox.showinfo("Channel Connected!", f"🎉 Successfully connected YouTube channel:\n\n{profile['title']} ({profile.get('custom_url') or profile['id']})")
                    if on_success:
                        try:
                            on_success(profile)
                        except Exception:
                            pass
                dialog.after(0, on_done)
            except Exception as ex:
                def on_err(e):
                    complete_btn.configure(text="✅ Complete Channel Connection", state="normal")
                    messagebox.showerror("Verification Failed", f"Failed to authenticate channel:\n{e}")
                dialog.after(0, lambda: on_err(ex))

        threading.Thread(target=bg_task, daemon=True).start()

    complete_btn = ctk.CTkButton(
        s4_card,
        text="✅ Complete Channel Connection",
        height=38,
        font=ctk.CTkFont(size=13, weight="bold"),
        fg_color="#10b981",
        hover_color="#059669",
        command=finish_connection
    )
    complete_btn.pack(fill="x", padx=16, pady=(8, 14))

    # SECTION: Connected Channels List Card
    channels_card = ctk.CTkFrame(scroll, fg_color="#181824", corner_radius=10)
    channels_card.pack(fill="x", pady=6)

    ch_header = ctk.CTkFrame(channels_card, fg_color="transparent")
    ch_header.pack(fill="x", padx=16, pady=(12, 4))

    ctk.CTkLabel(
        ch_header,
        text="📺 Connected YouTube Channels:",
        font=ctk.CTkFont(size=13, weight="bold"),
        text_color="#cbd5e1"
    ).pack(side="left")

    def import_from_live_streamer():
        cnt = sync_live_streamer_accounts()
        refresh_connected_channels()
        if cnt > 0:
            messagebox.showinfo("Imported", f"Successfully synced channel(s) from Live Streamer!")
            if on_success:
                try:
                    channels = db_get_channels()
                    if channels:
                        on_success(channels[0])
                except Exception:
                    pass
        else:
            messagebox.showinfo("Sync", "Channels are already up to date with Live Streamer.")

    ctk.CTkButton(
        ch_header,
        text="🔄 Sync Live Streamer",
        width=130,
        height=26,
        font=ctk.CTkFont(size=10, weight="bold"),
        fg_color="#334155",
        hover_color="#475569",
        command=import_from_live_streamer
    ).pack(side="right")

    channels_container = ctk.CTkFrame(channels_card, fg_color="transparent")
    channels_container.pack(fill="x", padx=16, pady=(0, 12))

    def remove_channel(cid):
        if messagebox.askyesno("Confirm", "Are you sure you want to remove this channel account?"):
            try:
                import sqlite3
                from pathlib import Path
                _DB_P = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "StoriesStudio" / "uploader.db"
                conn = sqlite3.connect(str(_DB_P))
                conn.execute("DELETE FROM channels WHERE id = ?", (cid,))
                conn.commit()
                conn.close()
            except Exception:
                pass
            refresh_connected_channels()
            if on_success:
                try:
                    on_success(None)
                except Exception:
                    pass

    def refresh_connected_channels():
        for widget in channels_container.winfo_children():
            widget.destroy()

        channels = db_get_channels()
        if not channels:
            ctk.CTkLabel(
                channels_container,
                text="No channels connected yet. Follow the 4 steps above to add your first channel!",
                font=ctk.CTkFont(size=11),
                text_color="#64748b"
            ).pack(anchor="w", pady=4)
            return

        for ch in channels:
            row = ctk.CTkFrame(channels_container, fg_color="#101018", corner_radius=6)
            row.pack(fill="x", pady=3)

            title = ch.get("title", "Unnamed Channel")
            handle = ch.get("custom_url") or ch.get("id")

            info_lbl = ctk.CTkLabel(
                row,
                text=f"🟢 {title} ({handle})",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#10b981",
                anchor="w"
            )
            info_lbl.pack(side="left", padx=10, pady=8, fill="x", expand=True)

            del_btn = ctk.CTkButton(
                row,
                text="Remove",
                width=70,
                height=26,
                font=ctk.CTkFont(size=10),
                fg_color="#334155",
                hover_color="#dc2626",
                command=lambda cid=ch.get("id"): remove_channel(cid)
            )
            del_btn.pack(side="right", padx=6)

    refresh_connected_channels()


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
