import os
import sys
import json
import time
import uuid
import threading
import calendar
import webbrowser
from datetime import datetime, timezone, timedelta
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk

try:
    from uploader_engine.config import REDIRECT_URI
    from uploader_engine.database import (
        db_get_setting, db_set_setting, db_get_channels, db_save_channel,
        db_delete_channel, db_get_tasks, db_create_task, db_update_task_progress,
        db_update_task_status, db_delete_task, format_bytes
    )
except Exception:
    try:
        from .config import REDIRECT_URI
        from .database import (
            db_get_setting, db_set_setting, db_get_channels, db_save_channel,
            db_delete_channel, db_get_tasks, db_create_task, db_update_task_progress,
            db_update_task_status, db_delete_task, format_bytes
        )
    except Exception:
        from uploader_engine.api import db_get_setting, db_set_setting, db_get_channels, db_save_channel, db_get_tasks, db_create_task, REDIRECT_URI
        def db_delete_channel(cid): pass
        def db_update_task_progress(tid, p, b, s): pass
        def db_update_task_status(tid, s, vid=None, err=None): pass
        def db_delete_task(tid): pass
        def format_bytes(size):
            for unit in ['B', 'KB', 'MB', 'GB']:
                if size < 1024.0: return f"{size:.1f} {unit}"
                size /= 1024.0
            return f"{size:.1f} TB"

CATEGORIES = [
    ("22", "People & Blogs"),
    ("20", "Gaming"),
    ("24", "Entertainment"),
    ("23", "Comedy"),
    ("26", "Howto & Style"),
    ("27", "Education"),
    ("28", "Science & Tech"),
    ("10", "Music"),
    ("17", "Sports"),
    ("1",  "Film & Animation"),
    ("2",  "Autos & Vehicles"),
    ("25", "News & Politics")
]
CATEGORY_NAMES = [name for _, name in CATEGORIES]
CATEGORY_NAME_TO_ID = {name: cid for cid, name in CATEGORIES}
CATEGORY_ID_TO_NAME = {cid: name for cid, name in CATEGORIES}

TIMEZONE_OPTIONS = [
    ("(GMT+05:30) India Standard Time (IST - Delhi / Mumbai)", 5, 30),
    ("(GMT-05:00) Eastern Time (US & Canada - New York)", -5, 0),
    ("(GMT-06:00) Central Time (US & Canada - Chicago)", -6, 0),
    ("(GMT-07:00) Mountain Time (US & Canada - Denver)", -7, 0),
    ("(GMT-08:00) Pacific Time (US & Canada - Los Angeles)", -8, 0),
    ("(GMT+00:00) Coordinated Universal Time (UTC)", 0, 0),
    ("(GMT+01:00) London, Dublin, Lisbon (GMT / BST)", 1, 0),
    ("(GMT+02:00) Central European Time (Berlin, Paris, Rome)", 2, 0),
    ("(GMT+03:00) Moscow, Istanbul, Riyadh, Nairobi", 3, 0),
    ("(GMT+04:00) Dubai, Abu Dhabi, Baku (GST)", 4, 0),
    ("(GMT+05:00) Pakistan, Tashkent, Karachi (PKT)", 5, 0),
    ("(GMT+06:00) Bangladesh, Dhaka, Almaty (BST)", 6, 0),
    ("(GMT+07:00) Bangkok, Jakarta, Hanoi (ICT)", 7, 0),
    ("(GMT+08:00) Singapore, Beijing, Manila, Hong Kong (SGT)", 8, 0),
    ("(GMT+09:00) Tokyo, Seoul, Osaka (JST / KST)", 9, 0),
    ("(GMT+10:00) Sydney, Melbourne, Brisbane (AEST)", 10, 0),
    ("(GMT+12:00) Auckland, Wellington, Fiji (NZST)", 12, 0),
    ("(GMT-03:00) Brasilia, Buenos Aires, Sao Paulo (BRT)", -3, 0),
    ("(GMT-04:00) Atlantic Time (Halifax), Santiago", -4, 0),
    ("(GMT-10:00) Hawaii Standard Time (Honolulu)", -10, 0),
]
TIMEZONE_NAMES = [tz[0] for tz in TIMEZONE_OPTIONS]
TIMEZONE_DICT = {tz[0]: (tz[1], tz[2]) for tz in TIMEZONE_OPTIONS}

class CalendarTimezonePicker(ctk.CTkToplevel):
    def __init__(self, parent, initial_dt=None, initial_tz=None, auto_upload_default=True, on_select_callback=None):
        super().__init__(parent)
        self.title("📅 YouTube Upload & Publish Scheduler")
        self.geometry("540x700")
        self.resizable(False, False)
        self.grab_set()

        try:
            self.update_idletasks()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            if pw > 100 and ph > 100:
                x = px + max(0, (pw - 540) // 2)
                y = py + max(0, (ph - 700) // 2)
                self.geometry(f"540x700+{x}+{y}")
        except Exception:
            pass

        self.on_select_callback = on_select_callback
        now = datetime.now()
        def_target = now + timedelta(hours=2)

        self.view_year = initial_dt.year if initial_dt else def_target.year
        self.view_month = initial_dt.month if initial_dt else def_target.month
        self.selected_year = initial_dt.year if initial_dt else def_target.year
        self.selected_month = initial_dt.month if initial_dt else def_target.month
        self.selected_day = initial_dt.day if initial_dt else def_target.day
        self.selected_hour = f"{initial_dt.hour:02d}" if initial_dt else f"{def_target.hour:02d}"
        self.selected_minute = f"{(initial_dt.minute // 5) * 5:02d}" if initial_dt else "00"
        self.selected_tz = initial_tz if (initial_tz and initial_tz in TIMEZONE_NAMES) else TIMEZONE_NAMES[0]
        self.auto_upload_default = auto_upload_default

        self.build_ui()

    def build_ui(self):
        ctk.CTkLabel(
            self, text="📅 Schedule Upload & YouTube Publish Time",
            font=ctk.CTkFont(size=17, weight="bold"), text_color="#ff0033"
        ).pack(padx=20, pady=(15, 4))

        ctk.CTkLabel(
            self, text="Select date, time, and timezone like YouTube Studio.\nRDP Mode: The app will automatically upload at this exact time!",
            font=ctk.CTkFont(size=11), text_color="#94a3b8", justify="center"
        ).pack(padx=20, pady=(0, 10))

        month_frame = ctk.CTkFrame(self, fg_color="#182234", corner_radius=8)
        month_frame.pack(fill="x", padx=20, pady=6)

        btn_prev = ctk.CTkButton(
            month_frame, text="◀", width=36, height=28,
            fg_color="#334155", hover_color="#475569", command=self.prev_month
        )
        btn_prev.pack(side="left", padx=10, pady=6)

        self.lbl_month_year = ctk.CTkLabel(
            month_frame, text="", font=ctk.CTkFont(size=14, weight="bold"), text_color="#f8fafc"
        )
        self.lbl_month_year.pack(side="left", expand=True)

        btn_next = ctk.CTkButton(
            month_frame, text="▶", width=36, height=28,
            fg_color="#334155", hover_color="#475569", command=self.next_month
        )
        btn_next.pack(side="right", padx=10, pady=6)

        self.cal_grid_frame = ctk.CTkFrame(self, fg_color="#131d2e", corner_radius=10)
        self.cal_grid_frame.pack(padx=20, pady=6)
        self.render_calendar_days()

        time_section = ctk.CTkFrame(self, fg_color="#182234", corner_radius=8)
        time_section.pack(fill="x", padx=20, pady=10)

        t_top = ctk.CTkFrame(time_section, fg_color="transparent")
        t_top.pack(fill="x", padx=15, pady=(8, 4))
        ctk.CTkLabel(t_top, text="⏰ Select Time:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#f8fafc").pack(side="left")

        hours_list = [f"{h:02d}" for h in range(24)]
        self.hour_menu = ctk.CTkOptionMenu(t_top, values=hours_list, width=70, height=28, fg_color="#1e293b")
        self.hour_menu.set(self.selected_hour)
        self.hour_menu.pack(side="left", padx=(10, 4))

        ctk.CTkLabel(t_top, text=":", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")

        mins_list = [f"{m:02d}" for m in range(0, 60, 5)]
        self.min_menu = ctk.CTkOptionMenu(t_top, values=mins_list, width=70, height=28, fg_color="#1e293b")
        self.min_menu.set(self.selected_minute)
        self.min_menu.pack(side="left", padx=4)

        tz_frame = ctk.CTkFrame(self, fg_color="#182234", corner_radius=8)
        tz_frame.pack(fill="x", padx=20, pady=6)
        ctk.CTkLabel(tz_frame, text="🌍 Timezone (YouTube Studio):", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8").pack(anchor="w", padx=15, pady=(8, 2))
        self.tz_menu = ctk.CTkOptionMenu(tz_frame, values=TIMEZONE_NAMES, width=470, height=30, fg_color="#1e293b")
        self.tz_menu.set(self.selected_tz)
        self.tz_menu.pack(padx=15, pady=(0, 10))

        self.auto_upload_cb = ctk.CTkCheckBox(
            self, text="⚡ Auto-Start Upload when scheduled time arrives",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#f8fafc"
        )
        if self.auto_upload_default:
            self.auto_upload_cb.select()
        else:
            self.auto_upload_cb.deselect()
        self.auto_upload_cb.pack(padx=25, pady=8, anchor="w")

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(10, 15))

        btn_apply = ctk.CTkButton(
            btn_frame, text="✅ Set Schedule", command=self.apply_schedule,
            fg_color="#ff0033", hover_color="#d4002a", height=38, font=ctk.CTkFont(weight="bold")
        )
        btn_apply.pack(side="left", expand=True, fill="x", padx=(0, 6))

        btn_clear = ctk.CTkButton(
            btn_frame, text="🗑️ Clear Schedule", command=self.clear_schedule,
            fg_color="#334155", hover_color="#475569", height=38, width=130
        )
        btn_clear.pack(side="left", padx=4)

        btn_cancel = ctk.CTkButton(
            btn_frame, text="Cancel", command=self.destroy,
            fg_color="#1e293b", hover_color="#334155", height=38, width=90
        )
        btn_cancel.pack(side="left", padx=(6, 0))

    def prev_month(self):
        if self.view_month == 1:
            self.view_month = 12
            self.view_year -= 1
        else:
            self.view_month -= 1
        self.render_calendar_days()

    def next_month(self):
        if self.view_month == 12:
            self.view_month = 1
            self.view_year += 1
        else:
            self.view_month += 1
        self.render_calendar_days()

    def render_calendar_days(self):
        for w in self.cal_grid_frame.winfo_children():
            w.destroy()

        month_name = calendar.month_name[self.view_month]
        self.lbl_month_year.configure(text=f"{month_name} {self.view_year}")

        headers = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
        for col, h in enumerate(headers):
            ctk.CTkLabel(
                self.cal_grid_frame, text=h, width=64, height=24,
                font=ctk.CTkFont(size=11, weight="bold"), text_color="#94a3b8"
            ).grid(row=0, column=col, padx=2, pady=2)

        now = datetime.now()
        weeks = calendar.monthcalendar(self.view_year, self.view_month)
        for r_idx, week in enumerate(weeks):
            for c_idx, day in enumerate(week):
                if day == 0:
                    ctk.CTkLabel(self.cal_grid_frame, text="", width=64, height=30).grid(row=r_idx + 1, column=c_idx, padx=2, pady=2)
                    continue

                is_selected = (self.selected_day == day and self.selected_month == self.view_month and self.selected_year == self.view_year)
                is_today = (day == now.day and self.view_month == now.month and self.view_year == now.year)

                if is_selected:
                    btn_color, hover_color, txt_color = "#ff0033", "#d4002a", "white"
                elif is_today:
                    btn_color, hover_color, txt_color = "#0284c7", "#0369a1", "white"
                else:
                    btn_color, hover_color, txt_color = "#1e293b", "#334155", "#f8fafc"

                btn_day = ctk.CTkButton(
                    self.cal_grid_frame, text=str(day), width=64, height=30,
                    fg_color=btn_color, hover_color=hover_color, text_color=txt_color,
                    font=ctk.CTkFont(size=12, weight="bold" if (is_selected or is_today) else "normal"),
                    command=lambda d=day: self.select_day(d)
                )
                btn_day.grid(row=r_idx + 1, column=c_idx, padx=2, pady=2)

    def select_day(self, day):
        self.selected_day = day
        self.selected_month = self.view_month
        self.selected_year = self.view_year
        self.render_calendar_days()

    def apply_schedule(self):
        hour = int(self.hour_menu.get())
        minute = int(self.min_menu.get())
        selected_tz_name = self.tz_menu.get()
        auto_upload = bool(self.auto_upload_cb.get())

        tz_offset_h, tz_offset_m = TIMEZONE_DICT.get(selected_tz_name, (5, 30))
        tz_obj = timezone(timedelta(hours=tz_offset_h, minutes=tz_offset_m))
        local_dt = datetime(self.selected_year, self.selected_month, self.selected_day, hour, minute, tzinfo=tz_obj)
        utc_dt = local_dt.astimezone(timezone.utc)
        utc_iso = utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        short_tz = selected_tz_name.split(")")[0].replace("(", "")
        display_str = f"{self.selected_year}-{self.selected_month:02d}-{self.selected_day:02d} {hour:02d}:{minute:02d} ({short_tz})"

        if self.on_select_callback:
            self.on_select_callback({
                "display_str": display_str,
                "publish_at_iso": utc_iso,
                "scheduled_upload_time": utc_iso if auto_upload else None,
                "timezone_name": selected_tz_name,
                "auto_upload": auto_upload
            })
        self.destroy()

    def clear_schedule(self):
        if self.on_select_callback:
            self.on_select_callback(None)
        self.destroy()


class BulkVideoUploaderFrame(ctk.CTkFrame):
    """
    Universal reusable CTkFrame containing the YouTube Bulk Video Uploader Suite.
    Can be mounted into any CTk tabview in Video Tool or Music Tool.
    """
    def __init__(self, parent, boot_data=None, **kwargs):
        super().__init__(parent, fg_color="#080c14", **kwargs)
        self.boot_data = boot_data or {}
        self.channels = []
        self.selected_channel_id = None
        self.staged_videos = []
        self.is_queue_running = True
        self.upload_mode = "sequential"
        self.active_upload_ids = set()
        self.current_upload_task = None
        self.worker_thread = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.build_header()
        self.build_tabs()

        self.refresh_channels_dropdown()
        self.start_background_worker()
        self.poll_queue_updates()

    def build_header(self):
        header_frame = ctk.CTkFrame(self, height=56, corner_radius=0, fg_color="#0b0f19")
        header_frame.grid(row=0, column=0, sticky="ew")

        brand_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        brand_frame.pack(side="left", padx=16, pady=10)

        ctk.CTkLabel(
            brand_frame, text="▶ YouTube Bulk Studio", 
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color="#ff0033"
        ).pack(side="left")

        ctk.CTkLabel(
            brand_frame, text="DIRECT CLOUD UPLOAD", 
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#331118", text_color="#ff4d6d",
            corner_radius=6, padx=8, pady=2
        ).pack(side="left", padx=10)

        right_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        right_frame.pack(side="right", padx=16, pady=10)

        ctk.CTkLabel(right_frame, text="Channel:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#94a3b8").pack(side="left", padx=(0, 6))

        self.channel_dropdown = ctk.CTkOptionMenu(
            right_frame, values=["No Channels Connected"],
            command=self.on_channel_selected,
            width=240, height=30, fg_color="#1e293b", button_color="#334155"
        )
        self.channel_dropdown.pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            right_frame, text="+ Connect Channel",
            command=self.open_connect_channel_dialog,
            fg_color="#ff0033", hover_color="#d4002a",
            font=ctk.CTkFont(weight="bold"), width=135, height=30
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            right_frame, text="⚙️ API Config",
            command=self.open_settings_dialog,
            fg_color="#1e293b", hover_color="#334155",
            border_width=1, border_color="#475569", width=95, height=30
        ).pack(side="left")

    def build_tabs(self):
        self.tabview = ctk.CTkTabview(
            self, fg_color="#0f172a", segmented_button_fg_color="#1e293b",
            segmented_button_selected_color="#ff0033", segmented_button_selected_hover_color="#d4002a"
        )
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=10, pady=(6, 10))

        self.tab_uploader = self.tabview.add("📤 Bulk Uploader")
        self.tab_queue = self.tabview.add("📊 Upload Queue & Progress")
        self.tab_channels = self.tabview.add("📺 Channel Manager")

        self.build_uploader_tab()
        self.build_queue_tab()
        self.build_channels_tab()

    def build_uploader_tab(self):
        toolbar = ctk.CTkFrame(self.tab_uploader, fg_color="#182234", corner_radius=10)
        toolbar.pack(fill="x", padx=10, pady=8)

        ctk.CTkButton(
            toolbar, text="📁 + Add Video Files", command=self.browse_video_files,
            fg_color="#ff0033", hover_color="#e6002e", font=ctk.CTkFont(size=13, weight="bold"),
            height=34
        ).pack(side="left", padx=10, pady=8)

        self.target_ch_banner = ctk.CTkLabel(
            toolbar, text="Default Target: None", font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38bdf8"
        )
        self.target_ch_banner.pack(side="right", padx=15)

        ctk.CTkButton(
            toolbar, text="🗑️ Clear List", command=self.clear_staged_videos,
            fg_color="#334155", hover_color="#475569", height=34
        ).pack(side="right", padx=8, pady=8)

        self.videos_scroll_frame = ctk.CTkScrollableFrame(
            self.tab_uploader, fg_color="#0b1120", corner_radius=12
        )
        self.videos_scroll_frame.pack(fill="both", expand=True, padx=10, pady=4)

        self.empty_label = ctk.CTkLabel(
            self.videos_scroll_frame, 
            text="No videos queued yet.\n\nClick '+ Add Video Files' above, or render videos directly from any tab!",
            font=ctk.CTkFont(size=14), text_color="#64748b"
        )
        self.empty_label.pack(pady=100)

        bottom_bar = ctk.CTkFrame(self.tab_uploader, height=54, fg_color="#182234", corner_radius=10)
        bottom_bar.pack(fill="x", padx=10, pady=8)

        self.lbl_summary_count = ctk.CTkLabel(
            bottom_bar, text="Videos Queued: 0", font=ctk.CTkFont(size=12, weight="bold"), text_color="#f8fafc"
        )
        self.lbl_summary_count.pack(side="left", padx=16, pady=12)

        self.lbl_summary_size = ctk.CTkLabel(
            bottom_bar, text="Total Size: 0 MB", font=ctk.CTkFont(size=12, weight="bold"), text_color="#94a3b8"
        )
        self.lbl_summary_size.pack(side="left", padx=10, pady=12)

        self.btn_upload_parallel = ctk.CTkButton(
            bottom_bar, text="⚡ Upload All in Once", command=lambda: self.submit_staged_to_queue(mode="concurrent"),
            fg_color="#ff0033", hover_color="#d4002a", font=ctk.CTkFont(size=12, weight="bold"),
            height=36, width=170, state="disabled"
        )
        self.btn_upload_parallel.pack(side="right", padx=(4, 12), pady=8)

        self.btn_upload_sequential = ctk.CTkButton(
            bottom_bar, text="▶ Upload One by One", command=lambda: self.submit_staged_to_queue(mode="sequential"),
            fg_color="#0284c7", hover_color="#0369a1", font=ctk.CTkFont(size=12, weight="bold"),
            height=36, width=170, state="disabled"
        )
        self.btn_upload_sequential.pack(side="right", padx=4, pady=8)

    def browse_video_files(self):
        filetypes = [
            ("Video files", "*.mp4 *.mov *.mkv *.avi *.webm *.flv *.m4v"),
            ("All files", "*.*")
        ]
        filenames = filedialog.askopenfilenames(title="Select Videos for Bulk Upload", filetypes=filetypes)
        if not filenames:
            return

        for path in filenames:
            fname = os.path.basename(path)
            fsize = os.path.getsize(path) if os.path.exists(path) else 0
            clean_title = os.path.splitext(fname)[0].replace("_", " ").replace("-", " ").strip()
            
            item = {
                "id": str(uuid.uuid4()),
                "channel_id": self.selected_channel_id or (self.channels[0]["id"] if self.channels else None),
                "video_path": path,
                "original_filename": fname,
                "file_size": fsize,
                "title": clean_title,
                "description": "",
                "thumbnail_path": "",
                "tags": "",
                "category_id": "22",
                "privacy_status": "private",
                "publish_at": "",
                "publish_at_iso": None,
                "scheduled_upload_time": None,
                "timezone_name": "",
                "schedule_display": "",
                "made_for_kids": False,
                "widgets": {}
            }
            self.staged_videos.append(item)

        self.render_video_cards()

    def render_video_cards(self):
        for widget in self.videos_scroll_frame.winfo_children():
            widget.destroy()

        if not self.staged_videos:
            self.empty_label = ctk.CTkLabel(
                self.videos_scroll_frame, 
                text="No videos queued yet.\n\nClick '+ Add Video Files' above, or render videos directly from any tab!",
                font=ctk.CTkFont(size=14), text_color="#64748b"
            )
            self.empty_label.pack(pady=100)
            self.lbl_summary_count.configure(text="Videos Queued: 0")
            self.lbl_summary_size.configure(text="Total Size: 0 MB")
            self.btn_upload_sequential.configure(state="disabled")
            self.btn_upload_parallel.configure(state="disabled")
            return

        total_bytes = sum(v["file_size"] for v in self.staged_videos)
        self.lbl_summary_count.configure(text=f"Videos Queued: {len(self.staged_videos)}")
        self.lbl_summary_size.configure(text=f"Total Size: {format_bytes(total_bytes)}")
        self.btn_upload_sequential.configure(state="normal")
        self.btn_upload_parallel.configure(state="normal")

        for idx, item in enumerate(self.staged_videos):
            card = ctk.CTkFrame(self.videos_scroll_frame, fg_color="#131d2e", corner_radius=10)
            card.pack(fill="x", padx=6, pady=6)

            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=12, pady=(10, 4))

            num_lbl = ctk.CTkLabel(top, text=f"#{idx+1}", font=ctk.CTkFont(size=13, weight="bold"), text_color="#38bdf8")
            num_lbl.pack(side="left", padx=(0, 8))

            title_entry = ctk.CTkEntry(top, font=ctk.CTkFont(size=13, weight="bold"), height=30)
            title_entry.insert(0, item["title"])
            title_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
            item["widgets"]["title"] = title_entry

            btn_del = ctk.CTkButton(
                top, text="🗑️", width=36, height=28, fg_color="#334155", hover_color="#ef4444",
                command=lambda i=item: self.remove_staged_video(i)
            )
            btn_del.pack(side="right")

            info_lbl = ctk.CTkLabel(
                card, text=f"{item['original_filename']}  •  {format_bytes(item['file_size'])}",
                font=ctk.CTkFont(size=11), text_color="#94a3b8"
            )
            info_lbl.pack(anchor="w", padx=14, pady=(0, 6))

            fields_row = ctk.CTkFrame(card, fg_color="transparent")
            fields_row.pack(fill="x", padx=12, pady=(0, 10))

            vis_menu = ctk.CTkOptionMenu(fields_row, values=["private", "unlisted", "public", "scheduled"], width=110, height=28, fg_color="#1e293b")
            vis_menu.set(item["privacy_status"])
            vis_menu.pack(side="left", padx=(0, 6))
            item["widgets"]["privacy"] = vis_menu

            btn_sched = ctk.CTkButton(
                fields_row, text=item.get("schedule_display") or "📅 Schedule...", width=140, height=28,
                fg_color="#1e293b", hover_color="#334155", command=lambda i=item: self.open_schedule_picker_for_item(i)
            )
            btn_sched.pack(side="left", padx=(0, 6))
            item["widgets"]["btn_schedule"] = btn_sched

            kids_cb = ctk.CTkCheckBox(fields_row, text="Made for Kids", font=ctk.CTkFont(size=11))
            if item.get("made_for_kids"): kids_cb.select()
            kids_cb.pack(side="left", padx=10)
            item["widgets"]["made_for_kids"] = kids_cb

    def open_schedule_picker_for_item(self, item):
        def on_selected(data):
            if data:
                item["schedule_display"] = data["display_str"]
                item["publish_at_iso"] = data["publish_at_iso"]
                item["scheduled_upload_time"] = data["scheduled_upload_time"]
                item["timezone_name"] = data["timezone_name"]
                item["privacy_status"] = "scheduled"
                if "privacy" in item.get("widgets", {}):
                    item["widgets"]["privacy"].set("scheduled")
                if "btn_schedule" in item.get("widgets", {}):
                    item["widgets"]["btn_schedule"].configure(text=f"📅 {data['display_str'][:18]}...")
            else:
                item["schedule_display"] = ""
                item["publish_at_iso"] = None
                item["scheduled_upload_time"] = None
                item["timezone_name"] = ""
                if "btn_schedule" in item.get("widgets", {}):
                    item["widgets"]["btn_schedule"].configure(text="📅 Schedule...")

        CalendarTimezonePicker(self, on_select_callback=on_selected)

    def remove_staged_video(self, item):
        self.staged_videos = [v for v in self.staged_videos if v["id"] != item["id"]]
        self.render_video_cards()

    def clear_staged_videos(self):
        self.staged_videos.clear()
        self.render_video_cards()

    def submit_staged_to_queue(self, mode="sequential"):
        if not self.staged_videos:
            return

        target_ch_id = self.selected_channel_id or (self.channels[0]["id"] if self.channels else None)
        if not target_ch_id:
            messagebox.showerror("No Channel", "Please connect and select a target YouTube channel first.")
            return

        for item in self.staged_videos:
            w = item.get("widgets", {})
            title = w["title"].get().strip() if "title" in w else item["title"]
            privacy = w["privacy"].get() if "privacy" in w else item["privacy_status"]
            kids = bool(w["made_for_kids"].get()) if "made_for_kids" in w else False

            task_payload = {
                "id": item["id"],
                "channel_id": target_ch_id,
                "video_path": item["video_path"],
                "original_filename": item["original_filename"],
                "file_size": item["file_size"],
                "title": title or item["title"],
                "description": item.get("description", ""),
                "thumbnail_path": item.get("thumbnail_path"),
                "tags": item.get("tags", []),
                "category_id": item.get("category_id", "22"),
                "privacy_status": privacy,
                "publish_at": item.get("publish_at_iso"),
                "scheduled_upload_time": item.get("scheduled_upload_time"),
                "timezone_name": item.get("timezone_name", ""),
                "made_for_kids": kids,
                "status": "pending"
            }
            db_create_task(task_payload)

        count = len(self.staged_videos)
        self.upload_mode = mode
        self.staged_videos.clear()
        self.render_video_cards()
        self.tabview.set("📊 Upload Queue & Progress")
        messagebox.showinfo("Queued", f"Successfully added {count} video(s) to the YouTube Upload Queue!")

    def build_queue_tab(self):
        self.hero_progress_frame = ctk.CTkFrame(self.tab_queue, fg_color="#182234", corner_radius=12)
        self.hero_progress_frame.pack(fill="x", padx=10, pady=8)

        hero_top = ctk.CTkFrame(self.hero_progress_frame, fg_color="transparent")
        hero_top.pack(fill="x", padx=16, pady=(12, 6))

        self.lbl_active_title = ctk.CTkLabel(hero_top, text="Queue Idle", font=ctk.CTkFont(size=15, weight="bold"), text_color="#f8fafc")
        self.lbl_active_title.pack(side="left")

        self.lbl_active_percent = ctk.CTkLabel(hero_top, text="0%", font=ctk.CTkFont(size=20, weight="bold"), text_color="#ff0033")
        self.lbl_active_percent.pack(side="right")

        self.hero_progress_bar = ctk.CTkProgressBar(self.hero_progress_frame, height=12, progress_color="#ff0033")
        self.hero_progress_bar.set(0)
        self.hero_progress_bar.pack(fill="x", padx=16, pady=4)

        hero_bottom = ctk.CTkFrame(self.hero_progress_frame, fg_color="transparent")
        hero_bottom.pack(fill="x", padx=16, pady=(4, 12))

        self.lbl_active_metrics = ctk.CTkLabel(hero_bottom, text="0 MB / 0 MB", font=ctk.CTkFont(size=11), text_color="#94a3b8")
        self.lbl_active_metrics.pack(side="left")

        self.lbl_active_speed = ctk.CTkLabel(hero_bottom, text="0 MB/s", font=ctk.CTkFont(size=11), text_color="#38bdf8")
        self.lbl_active_speed.pack(side="right")

        ctrl_bar = ctk.CTkFrame(self.tab_queue, fg_color="transparent")
        ctrl_bar.pack(fill="x", padx=10, pady=4)

        self.btn_pause_resume = ctk.CTkButton(
            ctrl_bar, text="⏸ Pause Queue", width=120, command=self.toggle_queue_worker,
            fg_color="#334155", hover_color="#475569", height=30
        )
        self.btn_pause_resume.pack(side="left")

        ctk.CTkButton(
            ctrl_bar, text="🔄 Refresh", width=90, command=self.refresh_queue_table,
            fg_color="#1e293b", hover_color="#334155", height=30
        ).pack(side="left", padx=8)

        self.tasks_scroll_frame = ctk.CTkScrollableFrame(self.tab_queue, fg_color="#0b1120", corner_radius=12)
        self.tasks_scroll_frame.pack(fill="both", expand=True, padx=10, pady=6)

    def toggle_queue_worker(self):
        self.is_queue_running = not self.is_queue_running
        if self.is_queue_running:
            self.btn_pause_resume.configure(text="⏸ Pause Queue", fg_color="#334155")
        else:
            self.btn_pause_resume.configure(text="▶ Resume Queue", fg_color="#0284c7")

    def poll_queue_updates(self):
        self.refresh_queue_table()
        self.after(2500, self.poll_queue_updates)

    def refresh_queue_table(self):
        tasks = db_get_tasks()
        active_task = None
        for t in tasks:
            if t["status"] == "uploading":
                active_task = t
                break

        if active_task:
            self.lbl_active_title.configure(text=f"Uploading: {active_task['title']}")
            pct = active_task["progress_percent"] or 0
            self.lbl_active_percent.configure(text=f"{pct:.1f}%")
            self.hero_progress_bar.set(pct / 100.0)
            self.lbl_active_metrics.configure(text=f"{format_bytes(active_task['bytes_uploaded'])} / {format_bytes(active_task['file_size'])}")
            self.lbl_active_speed.configure(text=f"{active_task.get('speed_mbps', 0):.2f} MB/s")
        else:
            self.lbl_active_title.configure(text="Queue Idle" if self.is_queue_running else "Queue Paused")
            self.lbl_active_percent.configure(text="0%")
            self.hero_progress_bar.set(0)
            self.lbl_active_metrics.configure(text="0 MB / 0 MB")
            self.lbl_active_speed.configure(text="0 MB/s")

        for widget in self.tasks_scroll_frame.winfo_children():
            widget.destroy()

        if not tasks:
            ctk.CTkLabel(self.tasks_scroll_frame, text="No upload tasks in history.", font=ctk.CTkFont(size=14), text_color="#64748b").pack(pady=70)
            return

        channel_title_map = {c["id"]: c["title"] for c in self.channels}
        now_utc = datetime.now(timezone.utc)

        for t in tasks:
            row = ctk.CTkFrame(self.tasks_scroll_frame, fg_color="#131d2e", corner_radius=8)
            row.pack(fill="x", padx=4, pady=3)

            left_frame = ctk.CTkFrame(row, fg_color="transparent")
            left_frame.pack(side="left", padx=10, pady=6, fill="x", expand=True)

            ch_name = channel_title_map.get(t["channel_id"], "YouTube Channel")
            ctk.CTkLabel(
                left_frame, text=f"{t['title']}  →  [{ch_name}]", font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#f8fafc", anchor="w"
            ).pack(fill="x")

            meta_str = f"{t['original_filename']} • {format_bytes(t['file_size'])} • Visibility: {t['privacy_status']}"
            if t.get("error_message"):
                meta_str += f" • ⚠️ {t['error_message']}"
            elif t["status"] == "completed":
                meta_str += f" • ✅ Upload Complete"

            ctk.CTkLabel(
                left_frame, text=meta_str, font=ctk.CTkFont(size=10),
                text_color="#ef4444" if t.get("error_message") else ("#10b981" if t["status"] == "completed" else "#94a3b8"), anchor="w"
            ).pack(fill="x")

            actions_frame = ctk.CTkFrame(row, fg_color="transparent")
            actions_frame.pack(side="right", padx=10)

            vid_id = t.get("youtube_video_id")
            if vid_id and t["status"] == "completed":
                ctk.CTkButton(
                    actions_frame, text="▶ Watch", width=65, height=24, fg_color="#ff0033", hover_color="#d4002a",
                    command=lambda v=vid_id: webbrowser.open(f"https://youtu.be/{v}")
                ).pack(side="left", padx=3)

            elif t["status"] == "failed":
                ctk.CTkButton(
                    actions_frame, text="🔄 Retry", width=60, height=24, fg_color="#0284c7", hover_color="#0369a1",
                    command=lambda tid=t["id"]: self.retry_task(tid)
                ).pack(side="left", padx=3)

            ctk.CTkButton(
                actions_frame, text="🗑️", width=30, height=24, fg_color="#475569", hover_color="#ef4444",
                command=lambda tid=t["id"]: self.delete_task(tid)
            ).pack(side="left", padx=3)

    def retry_task(self, task_id):
        db_update_task_status(task_id, "pending", error=None)
        self.refresh_queue_table()

    def delete_task(self, task_id):
        db_delete_task(task_id)
        self.refresh_queue_table()

    def build_channels_tab(self):
        top_bar = ctk.CTkFrame(self.tab_channels, fg_color="transparent")
        top_bar.pack(fill="x", padx=12, pady=10)

        ctk.CTkLabel(top_bar, text="Linked YouTube Channels", font=ctk.CTkFont(size=16, weight="bold"), text_color="#f8fafc").pack(side="left")

        ctk.CTkButton(
            top_bar, text="+ Connect New Channel", command=self.open_connect_channel_dialog,
            fg_color="#ff0033", hover_color="#d4002a", font=ctk.CTkFont(weight="bold"), height=32
        ).pack(side="right")

        self.channels_scroll_frame = ctk.CTkScrollableFrame(self.tab_channels, fg_color="#0b1120", corner_radius=12)
        self.channels_scroll_frame.pack(fill="both", expand=True, padx=10, pady=6)

    def render_channels_tab(self):
        for widget in self.channels_scroll_frame.winfo_children():
            widget.destroy()

        if not self.channels:
            ctk.CTkLabel(
                self.channels_scroll_frame, text="No channels linked yet.\nClick '+ Connect New Channel' to link your YouTube channel.",
                font=ctk.CTkFont(size=13), text_color="#64748b"
            ).pack(pady=70)
            return

        for ch in self.channels:
            card = ctk.CTkFrame(self.channels_scroll_frame, fg_color="#131d2e", corner_radius=10)
            card.pack(fill="x", padx=8, pady=6)

            left = ctk.CTkFrame(card, fg_color="transparent")
            left.pack(side="left", padx=12, pady=10)

            ctk.CTkLabel(left, text=ch["title"], font=ctk.CTkFont(size=14, weight="bold"), text_color="#f8fafc").pack(anchor="w")
            sub_str = f"{ch.get('custom_url', '')} • Subscribers: {ch.get('subscriber_count', 0):,} • Videos: {ch.get('video_count', 0):,}"
            ctk.CTkLabel(left, text=sub_str, font=ctk.CTkFont(size=11), text_color="#94a3b8").pack(anchor="w", pady=(2, 0))

            right = ctk.CTkFrame(card, fg_color="transparent")
            right.pack(side="right", padx=12)

            is_active = (ch["id"] == self.selected_channel_id)
            ctk.CTkButton(
                right, text="Default Channel" if is_active else "Set as Default",
                fg_color="#10b981" if is_active else "#334155",
                hover_color="#059669" if is_active else "#475569",
                command=lambda cid=ch["id"]: self.set_active_channel(cid),
                height=30
            ).pack(side="left", padx=4)

            ctk.CTkButton(
                right, text="🗑️ Unlink", width=70, height=30, fg_color="#ef4444", hover_color="#dc2626",
                command=lambda cid=ch["id"]: self.unlink_channel(cid)
            ).pack(side="left", padx=4)

    def set_active_channel(self, channel_id):
        self.selected_channel_id = channel_id
        matching = [f"{c['title']} ({c['subscriber_count']:,} subs)" for c in self.channels if c["id"] == channel_id]
        if matching:
            self.channel_dropdown.set(matching[0])
            self.target_ch_banner.configure(text=f"Default Target: {matching[0]}")
        self.render_channels_tab()

    def unlink_channel(self, channel_id):
        if messagebox.askyesno("Unlink Channel", "Are you sure you want to unlink this channel?"):
            db_delete_channel(channel_id)
            self.refresh_channels_dropdown()

    def refresh_channels_dropdown(self):
        self.channels = db_get_channels()
        if not self.channels:
            self.channel_dropdown.configure(values=["No Channels Connected"])
            self.channel_dropdown.set("No Channels Connected")
            self.selected_channel_id = None
            self.target_ch_banner.configure(text="Default Target: None")
        else:
            names = [f"{c['title']} ({c['subscriber_count']:,} subs)" for c in self.channels]
            self.channel_dropdown.configure(values=names)

            if not self.selected_channel_id or not any(c["id"] == self.selected_channel_id for c in self.channels):
                self.selected_channel_id = self.channels[0]["id"]
                self.channel_dropdown.set(names[0])
                self.target_ch_banner.configure(text=f"Default Target: {names[0]}")
            else:
                current_name = [f"{c['title']} ({c['subscriber_count']:,} subs)" for c in self.channels if c["id"] == self.selected_channel_id][0]
                self.channel_dropdown.set(current_name)
                self.target_ch_banner.configure(text=f"Default Target: {current_name}")

        self.render_channels_tab()

    def on_channel_selected(self, choice):
        for c in self.channels:
            name = f"{c['title']} ({c['subscriber_count']:,} subs)"
            if name == choice:
                self.selected_channel_id = c["id"]
                self.target_ch_banner.configure(text=f"Default Target: {name}")
                break
        self.render_channels_tab()

    def open_connect_channel_dialog(self):
        from uploader_engine.api import open_connect_channel_dialog
        def _on_success(profile):
            self.refresh_channels_dropdown()
            self.set_active_channel(profile["id"])
            self.render_channels_tab()
        open_connect_channel_dialog(self, on_success=_on_success)

    def open_settings_dialog(self):
        from uploader_engine.api import open_api_settings_dialog
        open_api_settings_dialog(self, on_saved=self.render_channels_tab)

    def start_background_worker(self):
        if not self.worker_thread or not self.worker_thread.is_alive():
            self.worker_thread = threading.Thread(target=self._queue_worker_loop, daemon=True)
            self.worker_thread.start()

    def _queue_worker_loop(self):
        while True:
            try:
                if not self.is_queue_running:
                    time.sleep(2)
                    continue

                tasks = db_get_tasks()
                now_utc = datetime.now(timezone.utc)

                ready_tasks = []
                for t in reversed(tasks):
                    if t["status"] == "pending":
                        sched_time_str = t.get("scheduled_upload_time")
                        if sched_time_str:
                            try:
                                dt_sched = datetime.fromisoformat(sched_time_str.replace("Z", "+00:00"))
                                if now_utc < dt_sched:
                                    continue
                            except Exception:
                                pass
                        ready_tasks.append(t)

                if not ready_tasks:
                    time.sleep(2)
                    continue

                if self.upload_mode == "sequential":
                    if len(self.active_upload_ids) > 0:
                        time.sleep(1)
                        continue

                    next_task = ready_tasks[0]
                    self.active_upload_ids.add(next_task["id"])
                    self.current_upload_task = next_task
                    threading.Thread(target=self._run_task_wrapper, args=(next_task,), daemon=True).start()

                elif self.upload_mode == "concurrent":
                    MAX_CONCURRENT = 4
                    for next_task in ready_tasks:
                        if len(self.active_upload_ids) >= MAX_CONCURRENT:
                            break
                        if next_task["id"] not in self.active_upload_ids:
                            self.active_upload_ids.add(next_task["id"])
                            threading.Thread(target=self._run_task_wrapper, args=(next_task,), daemon=True).start()

                time.sleep(1)
            except Exception as e:
                print(f"[UploaderWorker] Loop notice: {e}")
                time.sleep(2)

    def _run_task_wrapper(self, task):
        try:
            from uploader_engine.uploader import execute_single_upload_task
            execute_single_upload_task(task)
        except Exception as e:
            print(f"[UploaderWorker] Task {task['id']} failed: {e}")
        finally:
            self.active_upload_ids.discard(task["id"])
            if self.current_upload_task and self.current_upload_task["id"] == task["id"]:
                self.current_upload_task = None
