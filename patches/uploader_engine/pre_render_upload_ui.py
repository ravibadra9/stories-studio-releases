"""
uploader_engine/pre_render_upload_ui.py — Pre-Render Direct YouTube Upload Component
══════════════════════════════════════════════════════════════════════════════════
Allows configuring YouTube upload BEFORE rendering begins, saving user time:
- Checkbox to enable/disable direct upload upon render completion
- Channel selector dropdown with "+ Add Channel" and "Refresh"
- Privacy status: Public, Unlisted, Private, Scheduled
- YouTube Studio-style Clock & Calendar with Timezone (GMT offsets)
- Optional Title, Description, Tags, and Custom Thumbnail
- Dual-variation support (Video 1 / Video 2) for Suno Music Tool
- Single-video support for Video Composer and Song Video Maker
- Guarantees video uploads ONLY to the selected channel!
"""

import os
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk

try:
    from uploader_engine.api import (
        db_get_channels, queue_video_for_upload, open_connect_channel_dialog
    )
    from uploader_engine.uploader_ui import CalendarTimezonePicker, TIMEZONE_NAMES
except Exception:
    try:
        from .api import (
            db_get_channels, queue_video_for_upload, open_connect_channel_dialog
        )
        from .uploader_ui import CalendarTimezonePicker, TIMEZONE_NAMES
    except Exception:
        # Standalone fallback
        _ROOT = Path(__file__).resolve().parent.parent
        if str(_ROOT) not in sys.path:
            sys.path.insert(0, str(_ROOT))
        from uploader_engine.api import (
            db_get_channels, queue_video_for_upload, open_connect_channel_dialog
        )
        from uploader_engine.uploader_ui import CalendarTimezonePicker, TIMEZONE_NAMES


def get_channel_choices():
    """Fetch connected channels and build display names and ID lookup."""
    try:
        channels = db_get_channels()
    except Exception:
        channels = []

    channel_names = []
    channel_map = {}  # display_name -> channel_id
    id_to_name = {}

    for c in channels:
        disp = f"{c.get('title', 'Unknown')} ({c.get('subscriber_count', 0):,} subs)"
        channel_names.append(disp)
        channel_map[disp] = c["id"]
        id_to_name[c["id"]] = disp

    return channel_names, channel_map, channels, id_to_name


class PreRenderUploadSection(ctk.CTkFrame):
    """
    Sleek, modern collapsible or flat panel for configuring YouTube upload
    BEFORE video rendering starts.
    """

    def __init__(
        self,
        parent,
        variation_label: str = "Video 1",
        accent_color: str = "#ff0033",
        default_enabled: bool = False,
        on_channel_change: Optional[Callable[[str], None]] = None,
        **kwargs
    ):
        super().__init__(parent, fg_color="#0f1523", corner_radius=12, border_width=1, border_color="#243049", **kwargs)
        self.variation_label = variation_label
        self.accent_color = accent_color
        self.on_channel_change = on_channel_change

        self.channel_map = {}
        self.id_to_name = {}
        self.channels_list = []

        # State Variables
        self.upload_enabled_var = ctk.BooleanVar(value=default_enabled)
        self.privacy_var = ctk.StringVar(value="public")
        self.title_var = ctk.StringVar(value="")
        self.tags_var = ctk.StringVar(value="")
        self.thumb_path_var = ctk.StringVar(value="")
        self.schedule_data = {
            "display_str": "",
            "publish_at_iso": None,
            "timezone_name": ""
        }

        self._build_ui()
        self.refresh_channels()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)

        # ── 1. Top Header & Upload Checkbox ──────────────────────────
        hdr_frame = ctk.CTkFrame(self, fg_color="#172033", corner_radius=8)
        hdr_frame.pack(fill="x", padx=10, pady=(10, 6))

        self.chk_upload = ctk.CTkCheckBox(
            hdr_frame,
            text=f"📤 Auto-Upload {self.variation_label} to YouTube (Direct upon Render)",
            variable=self.upload_enabled_var,
            command=self._on_toggle_enabled,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#ffffff",
            fg_color=self.accent_color,
            hover_color="#e11d48",
            corner_radius=6
        )
        self.chk_upload.pack(side="left", padx=12, pady=10)

        # Status Pill Badge
        self.status_pill = ctk.CTkLabel(
            hdr_frame,
            text="● Upload Disabled",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#94a3b8",
            fg_color="#1e293b",
            corner_radius=6,
            padx=8,
            pady=3
        )
        self.status_pill.pack(side="right", padx=12, pady=10)

        # ── 2. Content Area (Form Fields) ───────────────────────────
        self.body_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.body_frame.pack(fill="x", padx=10, pady=(2, 10))
        self.body_frame.grid_columnconfigure(1, weight=1)

        # Row 0: Target Channel Selection
        ctk.CTkLabel(
            self.body_frame,
            text="Target Channel:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#38bdf8"
        ).grid(row=0, column=0, sticky="w", padx=(4, 8), pady=4)

        ch_row = ctk.CTkFrame(self.body_frame, fg_color="transparent")
        ch_row.grid(row=0, column=1, sticky="ew", padx=2, pady=4)
        ch_row.grid_columnconfigure(0, weight=1)

        self.ch_menu = ctk.CTkOptionMenu(
            ch_row,
            values=["Loading channels..."],
            height=30,
            fg_color="#182234",
            button_color="#2b3b5c",
            font=ctk.CTkFont(size=11),
            command=self._on_select_channel
        )
        self.ch_menu.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.btn_add_ch = ctk.CTkButton(
            ch_row,
            text="➕ Add",
            width=65,
            height=30,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._on_add_channel_click
        )
        self.btn_add_ch.pack(side="left", padx=2)

        self.btn_refresh_ch = ctk.CTkButton(
            ch_row,
            text="🔄",
            width=36,
            height=30,
            fg_color="#334155",
            hover_color="#475569",
            font=ctk.CTkFont(size=11),
            command=self.refresh_channels
        )
        self.btn_refresh_ch.pack(side="left", padx=(2, 0))

        # Row 1: Visibility & Scheduling
        ctk.CTkLabel(
            self.body_frame,
            text="Privacy / Visibility:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#cbd5e1"
        ).grid(row=1, column=0, sticky="w", padx=(4, 8), pady=4)

        vis_row = ctk.CTkFrame(self.body_frame, fg_color="transparent")
        vis_row.grid(row=1, column=1, sticky="ew", padx=2, pady=4)

        self.vis_menu = ctk.CTkOptionMenu(
            vis_row,
            values=["public", "unlisted", "private", "scheduled"],
            variable=self.privacy_var,
            width=130,
            height=30,
            fg_color="#182234",
            button_color="#2b3b5c",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._on_vis_change
        )
        self.vis_menu.pack(side="left", padx=(0, 6))

        # Schedule Button (opens YouTube-style calendar with timezone)
        self.btn_schedule = ctk.CTkButton(
            vis_row,
            text="📅 Pick Schedule Date, Time & Timezone...",
            height=30,
            fg_color="#334155",
            hover_color="#475569",
            font=ctk.CTkFont(size=11),
            command=self._open_schedule_dialog
        )
        self.btn_schedule.pack(side="left", fill="x", expand=True, padx=2)

        self.btn_clear_sched = ctk.CTkButton(
            vis_row,
            text="✕",
            width=30,
            height=30,
            fg_color="#3f1d24",
            hover_color="#7f1d1d",
            text_color="#f87171",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._clear_schedule
        )
        # initially not packed until scheduled

        # Row 2: Video Title (Optional)
        ctk.CTkLabel(
            self.body_frame,
            text="Title (Optional):",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8"
        ).grid(row=2, column=0, sticky="w", padx=(4, 8), pady=3)

        self.title_entry = ctk.CTkEntry(
            self.body_frame,
            textvariable=self.title_var,
            placeholder_text="Leave empty to use song/album name automatically",
            height=28,
            fg_color="#141c2c",
            border_color="#273146",
            font=ctk.CTkFont(size=11)
        )
        self.title_entry.grid(row=2, column=1, sticky="ew", padx=2, pady=3)

        # Row 3: Description (Optional)
        ctk.CTkLabel(
            self.body_frame,
            text="Description (Optional):",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8"
        ).grid(row=3, column=0, sticky="nw", padx=(4, 8), pady=(6, 3))

        self.desc_box = ctk.CTkTextbox(
            self.body_frame,
            height=54,
            fg_color="#141c2c",
            border_width=1,
            border_color="#273146",
            font=ctk.CTkFont(size=10)
        )
        self.desc_box.grid(row=3, column=1, sticky="ew", padx=2, pady=3)
        self.desc_box.insert("1.0", "")

        # Row 4: Tags (Optional)
        ctk.CTkLabel(
            self.body_frame,
            text="Tags (Optional):",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8"
        ).grid(row=4, column=0, sticky="w", padx=(4, 8), pady=3)

        self.tags_entry = ctk.CTkEntry(
            self.body_frame,
            textvariable=self.tags_var,
            placeholder_text="e.g. worship, gospel, ambient (comma separated)",
            height=28,
            fg_color="#141c2c",
            border_color="#273146",
            font=ctk.CTkFont(size=11)
        )
        self.tags_entry.grid(row=4, column=1, sticky="ew", padx=2, pady=3)

        # Row 5: Custom Thumbnail (Optional)
        ctk.CTkLabel(
            self.body_frame,
            text="Thumbnail (Optional):",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8"
        ).grid(row=5, column=0, sticky="w", padx=(4, 8), pady=3)

        thumb_row = ctk.CTkFrame(self.body_frame, fg_color="transparent")
        thumb_row.grid(row=5, column=1, sticky="ew", padx=2, pady=3)
        thumb_row.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            thumb_row,
            text="🖼️ Browse Image",
            width=110,
            height=28,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            font=ctk.CTkFont(size=11),
            command=self._browse_thumbnail
        ).pack(side="left", padx=(0, 6))

        self.thumb_lbl = ctk.CTkLabel(
            thumb_row,
            text="No custom thumbnail (YouTube will generate automatically)",
            font=ctk.CTkFont(size=10),
            text_color="#64748b",
            anchor="w"
        )
        self.thumb_lbl.pack(side="left", fill="x", expand=True, padx=2)

        self.btn_clear_thumb = ctk.CTkButton(
            thumb_row,
            text="✕",
            width=26,
            height=26,
            fg_color="#1e293b",
            hover_color="#ef4444",
            text_color="#ef4444",
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self._clear_thumbnail
        )

        self._on_toggle_enabled()

    def _on_toggle_enabled(self):
        is_on = self.upload_enabled_var.get()
        if is_on:
            sel_ch = self.ch_menu.get()
            self.status_pill.configure(
                text=f"● Upload ACTIVE -> {sel_ch[:20]}",
                text_color="#34d399",
                fg_color="#064e3b"
            )
            self.configure(border_color=self.accent_color)
        else:
            self.status_pill.configure(
                text="● Upload Disabled",
                text_color="#94a3b8",
                fg_color="#1e293b"
            )
            self.configure(border_color="#243049")

    def _on_select_channel(self, choice):
        self._on_toggle_enabled()
        cid = self.get_selected_channel_id()
        if self.on_channel_change and cid:
            self.on_channel_change(cid)

    def _on_vis_change(self, val):
        if val == "scheduled":
            self.btn_schedule.configure(fg_color="#d97706", hover_color="#b45309", text_color="#ffffff")
            if not self.schedule_data.get("publish_at_iso"):
                self._open_schedule_dialog()
        else:
            self.btn_schedule.configure(fg_color="#334155", hover_color="#475569", text_color="#f8fafc")

    def _open_schedule_dialog(self):
        def _on_selected(data):
            self.schedule_data = data
            disp = data.get("display_str", "")
            self.privacy_var.set("scheduled")
            self.btn_schedule.configure(
                text=f"📅 {disp[:28]}",
                fg_color="#059669",
                hover_color="#047857"
            )
            self.btn_clear_sched.pack(side="left", padx=2)

        CalendarTimezonePicker(self.winfo_toplevel(), on_select_callback=_on_selected)

    def _clear_schedule(self):
        self.schedule_data = {
            "display_str": "",
            "publish_at_iso": None,
            "timezone_name": ""
        }
        self.privacy_var.set("public")
        self.btn_schedule.configure(
            text="📅 Pick Schedule Date, Time & Timezone...",
            fg_color="#334155",
            hover_color="#475569"
        )
        self.btn_clear_sched.pack_forget()

    def _browse_thumbnail(self):
        f = filedialog.askopenfilename(
            title="Select Custom Thumbnail Image",
            filetypes=[("Image Files", "*.jpg;*.jpeg;*.png;*.webp"), ("All Files", "*.*")]
        )
        if f and os.path.exists(f):
            self.thumb_path_var.set(f)
            self.thumb_lbl.configure(text=Path(f).name, text_color="#38bdf8")
            self.btn_clear_thumb.pack(side="left", padx=2)

    def _clear_thumbnail(self):
        self.thumb_path_var.set("")
        self.thumb_lbl.configure(
            text="No custom thumbnail (YouTube will generate automatically)",
            text_color="#64748b"
        )
        self.btn_clear_thumb.pack_forget()

    def _on_add_channel_click(self):
        try:
            top = self.winfo_toplevel()
            open_connect_channel_dialog(top, on_success=lambda prof: self.refresh_channels(prof.get("id")))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open connect channel dialog:\n{e}")

    def refresh_channels(self, target_id: Optional[str] = None):
        """Reload connected channels from DB and update OptionMenu."""
        names, lookup, channels, id_map = get_channel_choices()
        self.channel_map = lookup
        self.id_to_name = id_map
        self.channels_list = channels

        if names:
            self.ch_menu.configure(values=names)
            sel_name = names[0]
            if target_id and target_id in id_map:
                sel_name = id_map[target_id]
            elif self.ch_menu.get() in names:
                sel_name = self.ch_menu.get()
            self.ch_menu.set(sel_name)
        else:
            self.ch_menu.configure(values=["No YouTube channel connected"])
            self.ch_menu.set("No YouTube channel connected")

        self._on_toggle_enabled()

    def get_selected_channel_id(self) -> Optional[str]:
        """Resolves the exact channel_id string (e.g. UCxxxxxx)."""
        sel_display = self.ch_menu.get()
        if sel_display in self.channel_map:
            return self.channel_map[sel_display]
        for c in self.channels_list:
            if c["id"] == sel_display or c.get("title") == sel_display:
                return c["id"]
        if self.channels_list:
            return self.channels_list[0]["id"]
        return None

    def get_upload_config(self) -> Dict[str, Any]:
        """Returns the full parsed configuration."""
        raw_desc = self.desc_box.get("1.0", "end-1c").strip()
        raw_tags = self.tags_var.get().strip()
        tag_list = [t.strip() for t in raw_tags.split(",") if t.strip()] if raw_tags else []

        return {
            "enabled": bool(self.upload_enabled_var.get()),
            "channel_id": self.get_selected_channel_id(),
            "channel_name": self.ch_menu.get(),
            "privacy_status": self.privacy_var.get(),
            "publish_at": self.schedule_data.get("publish_at_iso"),
            "timezone_name": self.schedule_data.get("timezone_name", ""),
            "title": self.title_var.get().strip(),
            "description": raw_desc,
            "tags": tag_list,
            "thumbnail_path": self.thumb_path_var.get().strip() or None
        }

    def dispatch_upload(
        self,
        video_path: str,
        default_title: str = "",
        default_desc: str = "",
        default_tags: Optional[List[str]] = None,
        default_thumb: str = ""
    ) -> Optional[str]:
        """
        Submits the rendered video for upload ONLY if upload is enabled.
        Guarantees upload ONLY goes to the selected channel!
        """
        cfg = self.get_upload_config()
        if not cfg["enabled"]:
            print(f"[{self.variation_label}] Upload is unchecked. Skipping YouTube upload.")
            return None

        if not video_path or not os.path.exists(video_path):
            print(f"[{self.variation_label}] Error: Rendered video path does not exist: {video_path}")
            return None

        ch_id = cfg["channel_id"]
        if not ch_id:
            print(f"[{self.variation_label}] Error: No YouTube channel selected for upload.")
            return None

        final_title = cfg["title"] or default_title or Path(video_path).stem
        final_desc = cfg["description"] or default_desc or f"Produced with Suno Music Tool — {final_title}"
        final_tags = cfg["tags"] if cfg["tags"] else (default_tags or [])
        final_thumb = cfg["thumbnail_path"] or (default_thumb if (default_thumb and os.path.exists(default_thumb)) else None)

        try:
            task_id = queue_video_for_upload(
                video_path=video_path,
                title=final_title,
                description=final_desc,
                tags=final_tags,
                privacy_status=cfg["privacy_status"],
                publish_at=cfg["publish_at"],
                scheduled_upload_time=cfg["publish_at"],
                timezone_name=cfg["timezone_name"],
                channel_id=ch_id,
                thumbnail_path=final_thumb
            )
            print(f"[{self.variation_label}] 🚀 Directly queued for YouTube upload! Target: {cfg['channel_name']} (Task ID: {task_id})")

            from uploader_engine.uploader import get_video_duration_seconds, format_duration
            fsize = os.path.getsize(video_path) if os.path.exists(video_path) else 0
            dur_sec = get_video_duration_seconds(video_path)
            dur_str = format_duration(dur_sec)
            task_data = {
                "id": task_id,
                "channel_id": ch_id,
                "channel_name": cfg["channel_name"],
                "video_path": os.path.abspath(video_path),
                "original_filename": os.path.basename(video_path),
                "file_size": fsize,
                "video_duration": dur_sec,
                "video_duration_str": dur_str,
                "title": final_title,
                "description": final_desc,
                "tags": final_tags,
                "privacy_status": cfg["privacy_status"],
                "publish_at": cfg["publish_at"],
                "scheduled_upload_time": cfg["publish_at"],
                "timezone_name": cfg["timezone_name"],
                "thumbnail_path": final_thumb,
                "variation_label": self.variation_label,
                "status": "pending"
            }
            return task_data
        except Exception as e:
            print(f"[{self.variation_label}] Upload queue error: {e}")
            messagebox.showerror(f"{self.variation_label} Upload Error", f"Failed to queue video for YouTube:\n{e}")
            return None


class DualVariationUploadPanel(ctk.CTkFrame):
    """
    Dedicated panel for Suno Dual Variations:
    - Master Switch: Auto-Upload Both Variations (Direct upon Render)
    - Sync Switch: Apply same channel & settings to both Video 1 & Video 2
    - Video 1 (Track 1) Upload Settings & Target Channel
    - Video 2 (Track 2) Upload Settings & Target Channel
    """

    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.pack(fill="x")
        self.grid_columnconfigure(0, weight=1)

        self.master_upload_var = ctk.BooleanVar(value=True)
        self.sync_channels_var = ctk.BooleanVar(value=True)

        # ── Top Master Control Bar ──
        master_bar = ctk.CTkFrame(self, fg_color="#131b2e", corner_radius=8, border_width=1, border_color="#2b3b5c")
        master_bar.pack(fill="x", padx=4, pady=(2, 6))

        self.chk_master = ctk.CTkCheckBox(
            master_bar,
            text="📤 Auto-Upload BOTH Rendered Videos to YouTube (Direct upon Render)",
            variable=self.master_upload_var,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38bdf8",
            fg_color="#0284c7",
            hover_color="#0369a1",
            corner_radius=6,
            command=self._on_master_toggle
        )
        self.chk_master.pack(side="left", padx=12, pady=8)

        self.chk_sync = ctk.CTkCheckBox(
            master_bar,
            text="🔗 Same Channel for Both Videos",
            variable=self.sync_channels_var,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#94a3b8",
            fg_color="#6366f1",
            hover_color="#4f46e5",
            corner_radius=6,
            command=self._on_sync_toggle
        )
        self.chk_sync.pack(side="right", padx=12, pady=8)

        # Tab Segmented Switcher for switching between Video 1 & Video 2 settings
        self.tab_selector = ctk.CTkSegmentedButton(
            self,
            values=["🎬 Video 1 (Variation 1) [● Active]", "🎬 Video 2 (Variation 2) [● Active]"],
            font=ctk.CTkFont(size=12, weight="bold"),
            selected_color="#4f46e5",
            selected_hover_color="#4338ca",
            unselected_color="#182234",
            unselected_hover_color="#243049",
            height=34,
            command=self._on_tab_switch
        )
        self.tab_selector.pack(fill="x", padx=4, pady=(2, 6))
        self.tab_selector.set("🎬 Video 1 (Variation 1) [● Active]")

        # Container for the two sections
        self.content_container = ctk.CTkFrame(self, fg_color="transparent")
        self.content_container.pack(fill="x")

        # Video 1 Upload Section
        self.v1_section = PreRenderUploadSection(
            self.content_container,
            variation_label="Video 1 (Track 1)",
            accent_color="#38bdf8",
            on_channel_change=self._on_v1_channel_change
        )

        # Video 2 Upload Section
        self.v2_section = PreRenderUploadSection(
            self.content_container,
            variation_label="Video 2 (Track 2)",
            accent_color="#f43f5e"
        )

        # Enable both by default
        self.v1_section.upload_enabled_var.set(True)
        self.v2_section.upload_enabled_var.set(True)
        self.v1_section._on_toggle_enabled()
        self.v2_section._on_toggle_enabled()

        self._show_v1()

    def _on_master_toggle(self):
        val = self.master_upload_var.get()
        self.v1_section.upload_enabled_var.set(val)
        self.v2_section.upload_enabled_var.set(val)
        self.v1_section._on_toggle_enabled()
        self.v2_section._on_toggle_enabled()
        self._update_tab_labels()

    def _on_sync_toggle(self):
        if self.sync_channels_var.get():
            self._sync_v1_to_v2()

    def _on_v1_channel_change(self, cid):
        if self.sync_channels_var.get():
            self._sync_v1_to_v2()

    def _sync_v1_to_v2(self):
        v1_ch = self.v1_section.ch_menu.get()
        v2_vals = self.v2_section.ch_menu.cget("values")
        if v1_ch in v2_vals:
            self.v2_section.ch_menu.set(v1_ch)
            self.v2_section._on_toggle_enabled()
        self.v2_section.privacy_var.set(self.v1_section.privacy_var.get())
        self.v2_section.schedule_data = dict(self.v1_section.schedule_data)
        if self.v1_section.schedule_data.get("display_str"):
            self.v2_section.btn_schedule.configure(
                text=f"📅 {self.v1_section.schedule_data['display_str'][:28]}",
                fg_color="#059669",
                hover_color="#047857"
            )
            self.v2_section.btn_clear_sched.pack(side="left", padx=2)
        else:
            self.v2_section._clear_schedule()

    def _update_tab_labels(self):
        v1_on = self.v1_section.upload_enabled_var.get()
        v2_on = self.v2_section.upload_enabled_var.get()
        v1_lbl = "🎬 Video 1 (Variation 1) [● Active]" if v1_on else "🎬 Video 1 (Disabled)"
        v2_lbl = "🎬 Video 2 (Variation 2) [● Active]" if v2_on else "🎬 Video 2 (Disabled)"
        cur = self.tab_selector.get()
        self.tab_selector.configure(values=[v1_lbl, v2_lbl])
        if "Video 1" in cur:
            self.tab_selector.set(v1_lbl)
        else:
            self.tab_selector.set(v2_lbl)

    def _show_v1(self):
        self.v2_section.pack_forget()
        self.v1_section.pack(fill="x", padx=2, pady=2)

    def _show_v2(self):
        self.v1_section.pack_forget()
        self.v2_section.pack(fill="x", padx=2, pady=2)

    def _on_tab_switch(self, choice):
        if "Video 1" in choice:
            self._show_v1()
        else:
            self._show_v2()

    def refresh_all_channels(self):
        self.v1_section.refresh_channels()
        self.v2_section.refresh_channels()
        if self.sync_channels_var.get():
            self._sync_v1_to_v2()

    def dispatch_v1(self, video_path: str, default_title: str = "", default_desc: str = "", default_tags=None, default_thumb=""):
        return self.v1_section.dispatch_upload(video_path, default_title, default_desc, default_tags, default_thumb)

    def dispatch_v2(self, video_path: str, default_title: str = "", default_desc: str = "", default_tags=None, default_thumb=""):
        return self.v2_section.dispatch_upload(video_path, default_title, default_desc, default_tags, default_thumb)

class QueueAddedDialog(ctk.CTkToplevel):
    """
    Sleek notification popup shown upon render completion:
    - Informs user that videos are added to the direct YouTube upload queue
    - Offers choice:
        1. Sequential Queue (Video 1 first, then Video 2) [Default]
        2. Parallel Upload (Both simultaneously)
    - Automatically defaults to Sequential Queue if user closes or timer expires
    """
    def __init__(self, parent, tasks: List[Dict[str, Any]], on_start_callback, on_cancel_callback=None):
        super().__init__(parent)
        self.tasks = [t for t in tasks if t]
        self.on_start_callback = on_start_callback
        self.on_cancel_callback = on_cancel_callback
        self.countdown_seconds = 10
        self.is_resolved = False

        self.title("🚀 Added to Upload Queue — YouTube Direct Uploader")
        self.geometry("590x520")
        self.resizable(False, False)
        self.configure(fg_color="#080c14")

        # Center on parent window
        self.update_idletasks()
        try:
            x = max(40, parent.winfo_x() + (parent.winfo_width() - 590) // 2)
            y = max(40, parent.winfo_y() + (parent.winfo_height() - 520) // 2)
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self._on_close_default)

        self.mode_var = ctk.StringVar(value="sequential")
        self._build_ui()
        self._start_countdown()

    def _build_ui(self):
        # ── Header ──
        hdr = ctk.CTkFrame(self, fg_color="#0d1322", corner_radius=0, height=72)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        hdr_inner = ctk.CTkFrame(hdr, fg_color="transparent")
        hdr_inner.pack(fill="x", padx=20, pady=12)

        ctk.CTkLabel(
            hdr_inner,
            text="✅ Added to YouTube Upload Queue",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#34d399",
            anchor="w"
        ).pack(fill="x")

        ctk.CTkLabel(
            hdr_inner,
            text=f"Render complete! {len(self.tasks)} video(s) ready for direct YouTube upload.",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
            anchor="w"
        ).pack(fill="x")

        # ── Content Frame ──
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=14)

        # Videos preview
        preview_box = ctk.CTkFrame(content, fg_color="#0e1422", corner_radius=8, border_width=1, border_color="#1e293b")
        preview_box.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            preview_box,
            text="📁 Queued Videos:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#38bdf8",
            anchor="w"
        ).pack(fill="x", padx=12, pady=(8, 4))

        for idx, task in enumerate(self.tasks, 1):
            row = ctk.CTkFrame(preview_box, fg_color="#131c2e", corner_radius=6)
            row.pack(fill="x", padx=10, pady=(0, 6))

            var_lbl = task.get("variation_label") or f"Video {idx}"
            t_title = task.get("title") or f"Song {idx}"
            ch_name = task.get("channel_name") or "YouTube Channel"
            fsize_mb = (task.get("file_size") or 0) / (1024 * 1024)
            dur = task.get("video_duration_str") or "N/A"

            disp_t = f"🎬 {var_lbl}: {t_title}"
            if len(disp_t) > 36:
                disp_t = disp_t[:34] + "..."

            ctk.CTkLabel(
                row,
                text=disp_t,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#f8fafc"
            ).pack(side="left", padx=8, pady=6)

            ctk.CTkLabel(
                row,
                text=f"📺 {ch_name[:18]}  •  💾 {fsize_mb:.1f} MB  •  ⏱️ {dur}",
                font=ctk.CTkFont(size=10),
                text_color="#94a3b8"
            ).pack(side="right", padx=8, pady=6)

        # Mode Selection Box
        mode_box = ctk.CTkFrame(content, fg_color="#0e1422", corner_radius=8, border_width=1, border_color="#1e293b")
        mode_box.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            mode_box,
            text="⚡ Select Upload Transfer Mode:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#f8fafc",
            anchor="w"
        ).pack(fill="x", padx=12, pady=(10, 6))

        # Option 1: Sequential
        opt1_frame = ctk.CTkFrame(mode_box, fg_color="#131c2e", corner_radius=6)
        opt1_frame.pack(fill="x", padx=10, pady=(0, 6))

        r1 = ctk.CTkRadioButton(
            opt1_frame,
            text="📋 Sequential Queue (First run ho jaye, fir second run ho)",
            variable=self.mode_var,
            value="sequential",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#f8fafc",
            border_color="#38bdf8",
            fg_color="#0284c7"
        )
        r1.pack(anchor="w", padx=10, pady=(6, 2))

        ctk.CTkLabel(
            opt1_frame,
            text="   Video 1 pehle upload hoga, complete hone par Video 2 start hoga. (Recommended)",
            font=ctk.CTkFont(size=10),
            text_color="#94a3b8"
        ).pack(anchor="w", padx=10, pady=(0, 6))

        # Option 2: Parallel
        opt2_frame = ctk.CTkFrame(mode_box, fg_color="#131c2e", corner_radius=6)
        opt2_frame.pack(fill="x", padx=10, pady=(0, 8))

        r2 = ctk.CTkRadioButton(
            opt2_frame,
            text="⚡ Parallel Upload (Dono video ek saath upload honge)",
            variable=self.mode_var,
            value="parallel",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#f8fafc",
            border_color="#a855f7",
            fg_color="#9333ea"
        )
        r2.pack(anchor="w", padx=10, pady=(6, 2))

        ctk.CTkLabel(
            opt2_frame,
            text="   Video 1 aur Video 2 dono simultaneously parallel threads me upload honge.",
            font=ctk.CTkFont(size=10),
            text_color="#94a3b8"
        ).pack(anchor="w", padx=10, pady=(0, 6))

        # Note
        ctk.CTkLabel(
            content,
            text="💡 Note: Real-time speed & progress Studio ke '🎵 Song Queue' tab me dikhegi.",
            font=ctk.CTkFont(size=10),
            text_color="#64748b"
        ).pack(anchor="w", pady=(0, 4))

        # ── Bottom Bar ──
        bot_bar = ctk.CTkFrame(self, fg_color="#0d1322", height=54, corner_radius=0)
        bot_bar.pack(fill="x", side="bottom")
        bot_bar.pack_propagate(False)

        self.timer_lbl = ctk.CTkLabel(
            bot_bar,
            text=f"⏱️ Auto-starting queue in {self.countdown_seconds}s...",
            font=ctk.CTkFont(size=11),
            text_color="#f59e0b"
        )
        self.timer_lbl.pack(side="left", padx=18, pady=14)

        btn_cancel = ctk.CTkButton(
            bot_bar,
            text="Cancel Upload",
            width=100,
            height=32,
            fg_color="#334155",
            hover_color="#475569",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._on_cancel
        )
        btn_cancel.pack(side="right", padx=(6, 18), pady=11)

        btn_start = ctk.CTkButton(
            bot_bar,
            text="🚀 Start Upload",
            width=130,
            height=32,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._on_start_clicked
        )
        btn_start.pack(side="right", padx=6, pady=11)

    def _start_countdown(self):
        if self.countdown_seconds > 0 and not self.is_resolved:
            self.timer_lbl.configure(text=f"⏱️ Auto-starting queue in {self.countdown_seconds}s...")
            self.countdown_seconds -= 1
            self.after(1000, self._start_countdown)
        elif not self.is_resolved:
            self._on_start_clicked()

    def _on_start_clicked(self):
        if self.is_resolved:
            return
        self.is_resolved = True
        chosen_mode = self.mode_var.get()
        try:
            self.destroy()
        except Exception:
            pass
        if self.on_start_callback:
            self.on_start_callback(chosen_mode)

    def _on_close_default(self):
        if self.is_resolved:
            return
        self.is_resolved = True
        try:
            self.destroy()
        except Exception:
            pass
        if self.on_start_callback:
            self.on_start_callback("sequential")

    def _on_cancel(self):
        if self.is_resolved:
            return
        self.is_resolved = True
        try:
            self.destroy()
        except Exception:
            pass
        if self.on_cancel_callback:
            self.on_cancel_callback()


class LiveUploadProgressDialog(ctk.CTkToplevel):
    """
    Ultra-professional real-time floating dialog for direct YouTube video uploads.
    Shows real-time upload speed (MB/s), percentage, transferred MB / total MB,
    ETA, status badges, full completion metrics (Duration, Size, Upload Time),
    and final clickable YouTube watch links with 1-click copy.
    """
    def __init__(
        self,
        parent,
        tasks: List[Dict[str, Any]],
        on_complete_callback=None,
        on_progress_callback=None,
        on_task_done_callback=None
    ):
        super().__init__(parent)
        self.tasks = [t for t in tasks if t]
        self.on_complete_callback = on_complete_callback
        self.on_progress_callback = on_progress_callback
        self.on_task_done_callback = on_task_done_callback
        self.card_widgets = []
        self.is_closed = False

        self.title("🚀 YouTube Direct Uploader — Live Transfer & Progress")
        self.geometry("760x600")
        self.minsize(700, 480)
        self.configure(fg_color="#080c14")

        # Center on parent window
        self.update_idletasks()
        try:
            x = max(40, parent.winfo_x() + (parent.winfo_width() - 760) // 2)
            y = max(40, parent.winfo_y() + (parent.winfo_height() - 600) // 2)
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self._on_close_request)

        self._build_ui()
        self._start_worker()

    def _build_ui(self):
        # ── Header ──
        hdr = ctk.CTkFrame(self, height=64, fg_color="#0d1322", corner_radius=0)
        hdr.pack(fill="x")
        hdr.grid_propagate(False)

        left_hdr = ctk.CTkFrame(hdr, fg_color="transparent")
        left_hdr.pack(side="left", padx=18, pady=10)

        ctk.CTkLabel(
            left_hdr,
            text="🚀 YouTube Direct Uploader",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#ffffff"
        ).pack(anchor="w")

        ctk.CTkLabel(
            left_hdr,
            text="Directly uploading rendered videos to your chosen YouTube channels",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8"
        ).pack(anchor="w")

        self.overall_pill = ctk.CTkLabel(
            hdr,
            text=f"⚡ 0 of {len(self.tasks)} Uploaded",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#38bdf8",
            fg_color="#0f2942",
            corner_radius=6,
            padx=12,
            pady=4
        )
        self.overall_pill.pack(side="right", padx=18, pady=16)

        # ── Scrollable Area for Cards ──
        self.scroll_area = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll_area.pack(fill="both", expand=True, padx=16, pady=12)

        for idx, task in enumerate(self.tasks, 1):
            card = self._build_task_card(idx, task)
            self.card_widgets.append(card)

        # ── Bottom Bar ──
        bot_bar = ctk.CTkFrame(self, height=52, fg_color="#0d1322", corner_radius=0)
        bot_bar.pack(fill="x", side="bottom")
        bot_bar.grid_propagate(False)

        self.bot_status_lbl = ctk.CTkLabel(
            bot_bar,
            text="⚡ Transferring video files directly to YouTube API...",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8"
        )
        self.bot_status_lbl.pack(side="left", padx=18, pady=12)

        self.btn_done = ctk.CTkButton(
            bot_bar,
            text="Minimize / Close Window",
            width=170,
            height=32,
            fg_color="#1e293b",
            hover_color="#334155",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._on_close_request
        )
        self.btn_done.pack(side="right", padx=18, pady=10)

    def _build_task_card(self, idx: int, task: Dict[str, Any]) -> Dict[str, Any]:
        c_frame = ctk.CTkFrame(self.scroll_area, fg_color="#101726", corner_radius=10, border_width=1, border_color="#1e293b")
        c_frame.pack(fill="x", pady=6)

        # Top Row: Title, Channel Pill, Status Pill
        top_row = ctk.CTkFrame(c_frame, fg_color="transparent")
        top_row.pack(fill="x", padx=14, pady=(12, 6))

        t_title = task.get("title") or f"Video {idx}"
        var_lbl = task.get("variation_label") or f"Variation {idx}"
        display_title = f"🎬 {var_lbl}: {t_title}"
        if len(display_title) > 52:
            display_title = display_title[:50] + "..."

        ctk.CTkLabel(
            top_row,
            text=display_title,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#f8fafc",
            anchor="w"
        ).pack(side="left")

        status_pill = ctk.CTkLabel(
            top_row,
            text="⏳ In Queue",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#f59e0b",
            fg_color="#332200",
            corner_radius=4,
            padx=8,
            pady=2
        )
        status_pill.pack(side="right", padx=(6, 0))

        ch_name = task.get("channel_name", "YouTube Channel")
        ch_pill = ctk.CTkLabel(
            top_row,
            text=f"📺 {ch_name[:24]}",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#38bdf8",
            fg_color="#14243b",
            corner_radius=4,
            padx=8,
            pady=2
        )
        ch_pill.pack(side="right", padx=4)

        # Progress Bar
        p_bar = ctk.CTkProgressBar(c_frame, height=10, progress_color="#6366f1", fg_color="#172133")
        p_bar.pack(fill="x", padx=14, pady=(4, 6))
        p_bar.set(0)

        # Stats Row: Speed, Transferred, ETA
        stats_row = ctk.CTkFrame(c_frame, fg_color="transparent")
        stats_row.pack(fill="x", padx=14, pady=(2, 8))

        lbl_speed = ctk.CTkLabel(
            stats_row,
            text="⚡ Speed: 0.00 MB/s",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#38bdf8"
        )
        lbl_speed.pack(side="left")

        fsize = task.get("file_size", 0)
        tot_mb = fsize / (1024 * 1024) if fsize else 0.0
        lbl_transferred = ctk.CTkLabel(
            stats_row,
            text=f"💾 0 MB / {tot_mb:.1f} MB (0%)",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8"
        )
        lbl_transferred.pack(side="left", padx=16)

        lbl_eta = ctk.CTkLabel(
            stats_row,
            text="⏱️ ETA: Calculating...",
            font=ctk.CTkFont(size=11),
            text_color="#cbd5e1"
        )
        lbl_eta.pack(side="right")

        # Completion Row (Pack-forgotten initially, revealed when upload finishes)
        comp_frame = ctk.CTkFrame(c_frame, fg_color="#062e20", corner_radius=8, border_width=1, border_color="#047857")

        comp_status_lbl = ctk.CTkLabel(
            comp_frame,
            text="✅ Upload Successful! (Live on YouTube)",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#34d399",
            anchor="w"
        )
        comp_status_lbl.pack(fill="x", padx=12, pady=(8, 2))

        comp_details_lbl = ctk.CTkLabel(
            comp_frame,
            text="",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#a7f3d0",
            anchor="w"
        )
        comp_details_lbl.pack(fill="x", padx=12, pady=(2, 6))

        link_row = ctk.CTkFrame(comp_frame, fg_color="transparent")
        link_row.pack(fill="x", padx=10, pady=(0, 8))

        link_entry = ctk.CTkEntry(
            link_row,
            height=28,
            font=ctk.CTkFont(size=11),
            fg_color="#071410",
            border_color="#047857",
            text_color="#34d399"
        )
        link_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        btn_copy = ctk.CTkButton(
            link_row,
            text="📋 Copy Link",
            width=90,
            height=28,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8"
        )
        btn_copy.pack(side="right", padx=(2, 4))

        btn_open = ctk.CTkButton(
            link_row,
            text="🌐 Watch",
            width=70,
            height=28,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#059669",
            hover_color="#047857"
        )
        btn_open.pack(side="right", padx=2)

        return {
            "frame": c_frame,
            "status_pill": status_pill,
            "progress_bar": p_bar,
            "lbl_speed": lbl_speed,
            "lbl_transferred": lbl_transferred,
            "lbl_eta": lbl_eta,
            "comp_frame": comp_frame,
            "comp_status_lbl": comp_status_lbl,
            "comp_details_lbl": comp_details_lbl,
            "link_entry": link_entry,
            "btn_copy": btn_copy,
            "btn_open": btn_open
        }

    def _start_worker(self):
        threading.Thread(target=self._worker_thread, daemon=True).start()

    def _worker_thread(self):
        from uploader_engine.uploader import perform_video_upload
        from uploader_engine.auth import get_authenticated_youtube_service
        from uploader_engine.database import db_update_task_progress, db_update_task_status

        success_count = 0
        total_count = len(self.tasks)

        for idx, task in enumerate(self.tasks):
            cd = self.card_widgets[idx] if idx < len(self.card_widgets) else None
            task_id = task.get("id")
            channel_id = task.get("channel_id")
            video_path = task.get("video_path")
            fsize = task.get("file_size") or (os.path.getsize(video_path) if (video_path and os.path.exists(video_path)) else 0)

            # Update UI to Uploading
            if not self.is_closed and cd:
                self.after(0, lambda c=cd: (
                    c["status_pill"].configure(text="⚡ Uploading...", text_color="#38bdf8", fg_color="#0c2e4e"),
                    c["progress_bar"].configure(progress_color="#6366f1")
                ))
            try:
                db_update_task_status(task_id, "uploading")
            except Exception:
                pass

            try:
                youtube = get_authenticated_youtube_service(channel_id)

                def _progress_cb(pct, bytes_up, speed_mbps, c=cd, fsz=fsize, tid=task_id, t_idx=idx, t_obj=task):
                    rem = max(0, fsz - bytes_up)
                    eta_str = "--:--"
                    if speed_mbps > 0.05:
                        eta_sec = int(rem / (speed_mbps * 1024 * 1024))
                        eta_str = f"{eta_sec // 60}:{eta_sec % 60:02d}"

                    u_mb = bytes_up / (1024 * 1024)
                    tot_mb = fsz / (1024 * 1024)

                    if not self.is_closed and c:
                        self.after(0, lambda p=pct, s=speed_mbps, u=u_mb, t=tot_mb, e=eta_str, card_d=c: (
                            card_d["progress_bar"].set(max(0.01, min(1.0, p / 100.0))),
                            card_d["lbl_speed"].configure(text=f"⚡ Speed: {s:.2f} MB/s"),
                            card_d["lbl_transferred"].configure(text=f"💾 {u:.1f} MB / {t:.1f} MB ({p:.1f}%)"),
                            card_d["lbl_eta"].configure(text=f"⏱️ ETA: {e}")
                        ))

                    if self.on_progress_callback:
                        try:
                            self.on_progress_callback(t_idx, t_obj, pct, bytes_up, speed_mbps, eta_str)
                        except Exception:
                            pass

                    try:
                        db_update_task_progress(tid, pct, bytes_up, speed_mbps)
                    except Exception:
                        pass

                video_id = perform_video_upload(youtube, task, _progress_cb)
                success_count += 1

                try:
                    db_update_task_status(task_id, "completed", youtube_id=video_id)
                except Exception:
                    pass

                watch_url = f"https://youtu.be/{video_id}"
                task["watch_url"] = watch_url
                task["youtube_video_id"] = video_id

                if not self.is_closed and cd:
                    self.after(0, lambda c=cd, url=watch_url, t=task: self._mark_success(c, url, t))

                if self.on_task_done_callback:
                    try:
                        self.on_task_done_callback(idx, task, True, watch_url, "")
                    except Exception:
                        pass

            except Exception as e:
                err_msg = str(e)
                print(f"[LiveUploader] Upload error for task {task_id}: {err_msg}")
                try:
                    db_update_task_status(task_id, "failed", error=err_msg)
                except Exception:
                    pass

                if not self.is_closed and cd:
                    self.after(0, lambda c=cd, err=err_msg: self._mark_failed(c, err))

                if self.on_task_done_callback:
                    try:
                        self.on_task_done_callback(idx, task, False, "", err_msg)
                    except Exception:
                        pass

            if not self.is_closed:
                self.after(0, lambda s=success_count, tot=total_count: self.overall_pill.configure(
                    text=f"⚡ {s} of {tot} Uploaded",
                    text_color="#34d399" if s == tot else "#38bdf8",
                    fg_color="#064e3b" if s == tot else "#0f2942"
                ))

        if not self.is_closed:
            self.after(0, lambda: self._on_all_finished(success_count, total_count))

        if self.on_complete_callback:
            try:
                self.on_complete_callback(success_count)
            except Exception:
                pass

    def _mark_success(self, cd: Dict[str, Any], url: str, task: Dict[str, Any] = None):
        cd["progress_bar"].set(1.0)
        cd["progress_bar"].configure(progress_color="#10b981")
        cd["status_pill"].configure(text="✅ Published!", text_color="#34d399", fg_color="#064e3b")
        cd["lbl_speed"].configure(text="⚡ Transfer Complete!")
        cd["lbl_eta"].configure(text="🎉 Live on YouTube")

        task = task or {}
        dur = task.get("video_duration_str") or "N/A"
        fsize = task.get("file_size") or 0
        sz_mb = fsize / (1024 * 1024) if fsize else 0.0
        upt = task.get("upload_time_seconds") or 0
        avg_spd = task.get("average_speed_mbps") or 0.0
        vid_id = task.get("youtube_video_id") or ""

        cd["comp_status_lbl"].configure(
            text=f"✅ Upload Successful! (Video ID: {vid_id})" if vid_id else "✅ Upload Successful!"
        )
        cd["comp_details_lbl"].configure(
            text=f"⏱️ Duration: {dur}   |   💾 Size: {sz_mb:.1f} MB   |   ⚡ Upload Time: {upt}s (Avg {avg_spd:.2f} MB/s)"
        )

        cd["link_entry"].delete(0, "end")
        cd["link_entry"].insert(0, url)

        def _do_copy(u=url, btn=cd["btn_copy"]):
            try:
                self.clipboard_clear()
                self.clipboard_append(u)
                btn.configure(text="✅ Copied!", fg_color="#059669")
                self.after(1500, lambda: btn.configure(text="📋 Copy Link", fg_color="#2563eb"))
            except Exception:
                pass

        def _do_open(u=url):
            webbrowser.open(u)

        cd["btn_copy"].configure(command=_do_copy)
        cd["btn_open"].configure(command=_do_open)
        cd["comp_frame"].pack(fill="x", padx=14, pady=(4, 10))

    def _mark_failed(self, cd: Dict[str, Any], err: str):
        cd["status_pill"].configure(text="❌ Failed", text_color="#ef4444", fg_color="#3b0f15")
        cd["progress_bar"].configure(progress_color="#ef4444")
        cd["lbl_speed"].configure(text="❌ Error")
        cd["lbl_eta"].configure(text=f"Error: {err[:35]}")

    def _on_all_finished(self, success_cnt: int, total_cnt: int):
        if success_cnt == total_cnt and total_cnt > 0:
            self.bot_status_lbl.configure(
                text=f"🎉 All {total_cnt} video(s) successfully uploaded to YouTube!",
                text_color="#34d399"
            )
            self.btn_done.configure(text="✓ Close Window", fg_color="#059669", hover_color="#047857")
        else:
            self.bot_status_lbl.configure(
                text=f"Completed {success_cnt} of {total_cnt} video uploads.",
                text_color="#f59e0b"
            )
            self.btn_done.configure(text="Close", fg_color="#334155")

    def _on_close_request(self):
        self.is_closed = True
        try:
            self.destroy()
        except Exception:
            pass
