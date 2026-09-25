"""
master_queue.py — Universal Master Render Queue & Multi-Action Completion System
═════════════════════════════════════════════════════════════════════════════════
Central rendering & upload hub for ALL tools in StoriesStudio / AI Suite:
- Story Image Video, Recap Studio, Stories, Rhymes, Shorts, Jesus Prayer, 
  Song Video Maker, Suno Bulk Video Studio, Prayer Shorts, etc.
- Seamless Choice Workflow upon render:
    1. 💾 Save Video (Local destination / Reveal in folder)
    2. 📤 Upload to Channel (Target YouTube channel selection / instant queue)
    3. ⚡ Both (Save & Upload together in 1 click)
- Live Channel selector with ➕ Add Channel & OAuth linking support.
- Modes: Sequential (One-by-One) OR Parallel (Batch Processing).
- Live progress tracking, cancellation, and error telemetry.
"""

import os
import sys
import time
import uuid
import threading
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable

import customtkinter as ctk
from tkinter import messagebox

# ── Sound Notification Helper ────────────────────────────────────────────────
def play_completion_chime():
    """Play a pleasant notification chime sound across Windows."""
    def _sound_worker():
        try:
            if sys.platform == "win32":
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            else:
                import pygame
                pygame.mixer.init()
        except Exception:
            pass
    threading.Thread(target=_sound_worker, daemon=True).start()


# ── Channel Helper Functions ─────────────────────────────────────────────────
def get_channel_map():
    """Fetch all connected YouTube channels mapped by display name."""
    try:
        from uploader_engine.database import db_get_channels
        channels = db_get_channels()
        channel_names = [f"{c['title']} ({c.get('subscriber_count', 0):,} subs)" for c in channels]
        channel_map = {f"{c['title']} ({c.get('subscriber_count', 0):,} subs)": c["id"] for c in channels}
        return channel_names, channel_map, channels
    except Exception:
        return [], {}, []


# ── Completion Notification & Choice Popup Window ────────────────────────────
def show_video_completion_popup(parent=None, video_path: str = "", title: str = "Video Rendered Successfully!", tool_name: str = "Video Tool"):
    """
    Display a modern futuristic completion notification popup where the user can choose:
    - 💾 Save Only (Keep local / Reveal in Folder)
    - 📤 Upload Only (Send to selected YouTube Channel)
    - ⚡ Both (Save locally & Upload to Channel)
    - Choose or ➕ Add YouTube channel right on the popup.
    """
    play_completion_chime()

    if not video_path or not os.path.exists(video_path):
        return

    fname = os.path.basename(video_path)
    clean_title = title.split(":")[-1].strip() if ":" in title else (title or os.path.splitext(fname)[0])

    def _open_video():
        if video_path and os.path.exists(video_path):
            try:
                os.startfile(video_path)
            except Exception as e:
                print(f"[QUEUE] Open video error: {e}")

    def _save_video_action():
        """Reveal file in Explorer and confirm save."""
        if video_path and os.path.exists(video_path):
            try:
                folder = os.path.dirname(os.path.abspath(video_path))
                if sys.platform == "win32":
                    subprocess.Popen(f'explorer /select,"{os.path.abspath(video_path)}"')
                else:
                    os.startfile(folder)
            except Exception as e:
                print(f"[QUEUE] Open folder error: {e}")

    def _queue_upload(channel_id: Optional[str] = None):
        """Send video to YouTube upload queue."""
        try:
            from uploader_engine.api import queue_video_for_upload
            task_id = queue_video_for_upload(
                video_path=video_path,
                title=clean_title,
                description=f"Rendered with {tool_name}",
                channel_id=channel_id,
                privacy_status="public"
            )
            return task_id
        except Exception as e:
            messagebox.showerror("Upload Error", f"Could not queue upload:\n{e}")
            return None

    # Build sleek popup modal
    try:
        top = ctk.CTkToplevel()
        top.title("🎉 Render Complete — Choose Action")
        top.geometry("640x380")
        top.minsize(580, 360)
        top.configure(fg_color="#080c14")
        top.attributes("-topmost", True)
        top.focus_force()

        card = ctk.CTkFrame(top, fg_color="#0f172a", corner_radius=16, border_width=2, border_color="#10b981")
        card.pack(fill="both", expand=True, padx=12, pady=12)

        # Header Badge
        badge = ctk.CTkFrame(card, fg_color="#064e3b", corner_radius=10, border_width=1, border_color="#10b981")
        badge.pack(pady=(14, 4))
        ctk.CTkLabel(badge, text="  ✓ RENDER COMPLETE • 100%  ", font=("Segoe UI", 10, "bold"), text_color="#34d399").pack(padx=8, pady=3)

        ctk.CTkLabel(card, text=f"✨ {title}", font=("Segoe UI", 15, "bold"), text_color="#f8fafc").pack(pady=(0, 2))
        ctk.CTkLabel(card, text=f"📁 {fname}", font=("Consolas", 11), text_color="#94a3b8").pack(pady=(0, 10))

        # Channel Selector Frame
        ch_frame = ctk.CTkFrame(card, fg_color="#101726", corner_radius=10, border_width=1, border_color="#1e293b")
        ch_frame.pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkLabel(ch_frame, text="📺 YouTube Channel:", font=("Segoe UI", 11, "bold"), text_color="#38bdf8").pack(side="left", padx=(12, 6), pady=8)

        ch_menu = ctk.CTkOptionMenu(ch_frame, values=["Loading..."], width=300, height=30, fg_color="#1e293b")
        ch_menu.pack(side="left", fill="x", expand=True, padx=4, pady=8)

        ch_id_lookup = {}

        def refresh_channels(target_id=None):
            nonlocal ch_id_lookup
            names, lookup, _ = get_channel_map()
            ch_id_lookup = lookup
            if names:
                ch_menu.configure(values=names)
                sel_name = names[0]
                if target_id:
                    for nm, cid in lookup.items():
                        if cid == target_id:
                            sel_name = nm
                            break
                ch_menu.set(sel_name)
            else:
                ch_menu.configure(values=["No YouTube channel connected"])
                ch_menu.set("No YouTube channel connected")

        def on_add_channel():
            try:
                from uploader_engine.api import open_connect_channel_dialog
                open_connect_channel_dialog(top, on_success=lambda p: refresh_channels(p.get("id")))
            except Exception as ex:
                messagebox.showerror("Error", str(ex))

        ctk.CTkButton(
            ch_frame, text="➕ Add Channel", width=110, height=30,
            fg_color="#2563eb", hover_color="#1d4ed8", font=("Segoe UI", 11, "bold"),
            command=on_add_channel
        ).pack(side="right", padx=(4, 12), pady=8)

        refresh_channels()

        # Prompt Text
        ctk.CTkLabel(
            card, text="Choose how you want to proceed with this rendered video:",
            font=("Segoe UI", 11), text_color="#cbd5e1"
        ).pack(pady=(0, 8))

        # Main 3 Choice Buttons Row
        action_row = ctk.CTkFrame(card, fg_color="transparent")
        action_row.pack(fill="x", padx=16, pady=4)

        def on_save_only():
            _save_video_action()
            top.destroy()
            messagebox.showinfo("Saved", f"✓ Video saved successfully:\n{video_path}")

        def on_upload_only():
            sel_name = ch_menu.get()
            cid = ch_id_lookup.get(sel_name)
            if not cid:
                # Open full upload modal so user can configure
                top.destroy()
                try:
                    from uploader_engine.api import show_quick_upload_modal
                    show_quick_upload_modal(parent=parent, video_path=video_path, default_title=clean_title)
                except Exception as ex:
                    messagebox.showerror("Error", str(ex))
                return

            tid = _queue_upload(channel_id=cid)
            if tid:
                top.destroy()
                messagebox.showinfo("Queued for Upload", f"🚀 Video '{clean_title}' added to upload queue for {sel_name}!")

        def on_both_save_and_upload():
            # 1. Reveal in folder
            _save_video_action()
            # 2. Queue for upload
            sel_name = ch_menu.get()
            cid = ch_id_lookup.get(sel_name)
            tid = _queue_upload(channel_id=cid)
            top.destroy()
            if tid:
                messagebox.showinfo(
                    "Save & Upload",
                    f"🎉 Both actions completed!\n\n1. 💾 Video saved to folder.\n2. 🚀 Video queued to YouTube for {sel_name}."
                )

        # 1. 💾 Save Only Button
        ctk.CTkButton(
            action_row,
            text="💾 Save Only",
            height=42,
            fg_color="#3b82f6",
            hover_color="#2563eb",
            text_color="#ffffff",
            font=("Segoe UI", 12, "bold"),
            corner_radius=10,
            command=on_save_only
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))

        # 2. 📤 Upload Only Button
        ctk.CTkButton(
            action_row,
            text="📤 Upload Only",
            height=42,
            fg_color="#ff0033",
            hover_color="#d4002a",
            text_color="#ffffff",
            font=("Segoe UI", 12, "bold"),
            corner_radius=10,
            command=on_upload_only
        ).pack(side="left", fill="x", expand=True, padx=4)

        # 3. ⚡ Both (Save & Upload) Button
        ctk.CTkButton(
            action_row,
            text="⚡ Both (Save & Upload)",
            height=42,
            fg_color="#8b5cf6",
            hover_color="#7c3aed",
            text_color="#ffffff",
            font=("Segoe UI", 12, "bold"),
            corner_radius=10,
            command=on_both_save_and_upload
        ).pack(side="left", fill="x", expand=True, padx=(4, 0))

        # Bottom Utilities Row
        bot_row = ctk.CTkFrame(card, fg_color="transparent")
        bot_row.pack(fill="x", padx=16, pady=(10, 8))

        ctk.CTkButton(
            bot_row,
            text="▶ Play Preview",
            height=30,
            width=110,
            fg_color="#10b981",
            hover_color="#059669",
            text_color="#ffffff",
            font=("Segoe UI", 11),
            corner_radius=8,
            command=_open_video
        ).pack(side="left")

        ctk.CTkButton(
            bot_row,
            text="⚙️ Advanced Upload Options…",
            height=30,
            fg_color="#1e293b",
            hover_color="#334155",
            text_color="#38bdf8",
            font=("Segoe UI", 11),
            corner_radius=8,
            command=lambda: (top.destroy(), _open_adv_modal(video_path, clean_title, parent))
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            bot_row,
            text="Dismiss",
            height=30,
            width=80,
            fg_color="#1e293b",
            hover_color="#334155",
            text_color="#94a3b8",
            font=("Segoe UI", 11),
            corner_radius=8,
            command=top.destroy
        ).pack(side="right")

    except Exception as e:
        print(f"[QUEUE] Could not display popup modal: {e}")
        messagebox.showinfo("Render Complete", f"{title}\n\nFile saved to:\n{video_path}")

def _open_adv_modal(video_path: str, title: str, parent=None):
    try:
        from uploader_engine.api import show_quick_upload_modal
        show_quick_upload_modal(parent=parent, video_path=video_path, default_title=title)
    except Exception as ex:
        messagebox.showerror("Error", str(ex))


# ── Universal Task Data Structure ────────────────────────────────────────────
class UniversalQueueTask:
    def __init__(
        self,
        title: str,
        tool_name: str,
        execute_fn: Callable[[Callable[[float], None], Callable[[str], None]], str],
        output_path: str = "",
        payload: Optional[Dict[str, Any]] = None
    ):
        self.id = str(uuid.uuid4())[:8]
        self.title = title
        self.tool_name = tool_name
        self.execute_fn = execute_fn
        self.output_path = output_path
        self.payload = payload or {}
        
        self.status = "Queued"  # "Queued", "Rendering", "Completed", "Failed", "Cancelled"
        self.progress_pct = 0.0
        self.status_msg = "Waiting in queue..."
        self.created_at = datetime.now().strftime("%H:%M:%S")
        self.start_time: Optional[float] = None
        self.elapsed_secs: int = 0
        self.error_msg = ""
        self.logs: List[str] = [f"[{self.created_at}] Task initialized and placed in queue."]
        self._thread: Optional[threading.Thread] = None
        self._is_cancelled = False

    def start(self, on_finish_callback: Optional[Callable[["UniversalQueueTask"], None]] = None):
        if self.status == "Rendering":
            return

        self.status = "Rendering"
        self.progress_pct = 0.0
        self.start_time = time.time()
        self.status_msg = "Starting render pipeline..."
        self.logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] Render engine started.")

        def _worker():
            try:
                def _prog_cb(pct: float):
                    self.progress_pct = max(0.0, min(100.0, float(pct)))

                def _status_cb(msg: str):
                    self.status_msg = str(msg)
                    stamp = datetime.now().strftime('%H:%M:%S')
                    self.logs.append(f"[{stamp}] {msg}")
                    if len(self.logs) > 600:
                        self.logs.pop(0)
                    if self.start_time:
                        self.elapsed_secs = int(time.time() - self.start_time)

                # Execute task payload
                result_path = self.execute_fn(_prog_cb, _status_cb)
                if result_path and os.path.exists(result_path):
                    self.output_path = result_path

                self.status = "Completed"
                self.progress_pct = 100.0
                if self.start_time:
                    self.elapsed_secs = int(time.time() - self.start_time)
                self.status_msg = f"✓ Render complete ({self.elapsed_secs}s)"
                self.logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] Render completed successfully in {self.elapsed_secs}s.")

                # Trigger completion notification popup with Save / Upload / Both options
                show_video_completion_popup(
                    video_path=self.output_path,
                    title=f"{self.tool_name}: {self.title}",
                    tool_name=self.tool_name
                )

                # Auto-Upload to YouTube trigger if requested
                if self.payload.get("auto_upload") and self.output_path and os.path.exists(self.output_path):
                    try:
                        from uploader_engine.api import queue_video_for_upload
                        queue_video_for_upload(
                            video_path=self.output_path,
                            title=self.payload.get("upload_title") or self.title,
                            description=self.payload.get("upload_desc", ""),
                            tags=self.payload.get("upload_tags", []),
                            privacy_status=self.payload.get("upload_privacy", "private"),
                            channel_id=self.payload.get("upload_channel_id"),
                        )
                        self.logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] ⚡ Auto-queued to YouTube Bulk Uploader.")
                        print(f"[QUEUE] ⚡ Auto-queued '{self.title}' to YouTube upload queue!")
                    except Exception as ux:
                        print(f"[QUEUE] Auto-upload error: {ux}")

            except Exception as e:
                self.status = "Failed"
                self.error_msg = str(e)
                self.status_msg = f"❌ Error: {str(e)[:120]}"
                self.logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] [ERROR] {e}")
                print(f"[QUEUE-ERROR] Task '{self.title}' failed: {e}")
            finally:
                if on_finish_callback:
                    try:
                        on_finish_callback(self)
                    except Exception:
                        pass

        self._thread = threading.Thread(target=_worker, daemon=True, name=f"QueueTask-{self.id}")
        self._thread.start()


# ── Master Queue Engine ──────────────────────────────────────────────────────
class MasterUniversalQueueEngine:
    def __init__(self):
        self.tasks: List[UniversalQueueTask] = []
        self.mode = "one_by_one"  # "one_by_one" | "parallel"
        self.is_running = False
        self.is_paused = False
        self._lock = threading.Lock()
        self._listeners: List[Callable[[], None]] = []

    def subscribe(self, listener: Callable[[], None]):
        """Subscribe UI frame to queue update ticks."""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener: Callable[[], None]):
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _notify_listeners(self):
        for l in list(self._listeners):
            try:
                l()
            except Exception:
                pass

    def add_task(
        self,
        title: str,
        tool_name: str,
        execute_fn: Callable[[Callable[[float], None], Callable[[str], None]], str],
        output_path: str = "",
        payload: Optional[Dict[str, Any]] = None,
        auto_start: bool = True
    ) -> UniversalQueueTask:
        """Add a job to the master universal queue from ANY tool."""
        with self._lock:
            task = UniversalQueueTask(
                title=title,
                tool_name=tool_name,
                execute_fn=execute_fn,
                output_path=output_path,
                payload=payload
            )
            self.tasks.append(task)
            if auto_start and not self.is_paused:
                self.is_running = True

        self._notify_listeners()
        self._pump()
        return task

    def add_completed_video(
        self,
        video_path: str,
        title: str = "",
        tool_name: str = "Video Tool"
    ) -> UniversalQueueTask:
        """Register an already-rendered video directly into the queue as Completed."""
        with self._lock:
            # Check if this video path is already registered
            for t in self.tasks:
                if t.output_path and os.path.abspath(t.output_path) == os.path.abspath(video_path):
                    return t

            clean_title = title or os.path.basename(video_path)
            task = UniversalQueueTask(
                title=clean_title,
                tool_name=tool_name,
                execute_fn=lambda p, s: video_path,
                output_path=video_path
            )
            task.status = "Completed"
            task.progress_pct = 100.0
            task.status_msg = "✓ Rendered (Ready to Save / Upload)"
            task.logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] Video rendered via {tool_name}.")
            self.tasks.insert(0, task)

        self._notify_listeners()
        return task

    def run_one_by_one(self):
        """Start sequential rendering."""
        with self._lock:
            self.mode = "one_by_one"
            self.is_running = True
            self.is_paused = False
        self._pump()
        self._notify_listeners()

    def run_parallel(self):
        """Start parallel batch rendering for all queued tasks."""
        with self._lock:
            self.mode = "parallel"
            self.is_running = True
            self.is_paused = False
        self._pump()
        self._notify_listeners()

    def pause_queue(self):
        """Pause queue execution."""
        with self._lock:
            self.is_running = False
            self.is_paused = True
        self._notify_listeners()

    def clear_finished(self):
        """Remove completed or failed jobs."""
        with self._lock:
            self.tasks = [t for t in self.tasks if t.status in ("Queued", "Rendering")]
        self._notify_listeners()

    def remove_task(self, task_id: str):
        """Remove a specific task by ID."""
        with self._lock:
            self.tasks = [t for t in self.tasks if t.id != task_id]
        self._notify_listeners()

    def _on_task_finish(self, task: UniversalQueueTask):
        self._pump()
        self._notify_listeners()

    def _pump(self):
        """Scheduler loop managing sequential vs parallel queue execution."""
        if not self.is_running or self.is_paused:
            return

        with self._lock:
            queued = [t for t in self.tasks if t.status == "Queued"]
            rendering = [t for t in self.tasks if t.status == "Rendering"]

            if not queued and not rendering:
                self.is_running = False
                return

            if self.mode == "parallel":
                for t in queued:
                    t.start(on_finish_callback=self._on_task_finish)
            else:
                if len(rendering) == 0 and queued:
                    queued[0].start(on_finish_callback=self._on_task_finish)


# Global Singleton Instance
MASTER_QUEUE = MasterUniversalQueueEngine()


def register_rendered_video(
    video_path: str,
    title: str = "",
    tool_name: str = "Video Tool",
    show_popup: bool = True
) -> Optional[UniversalQueueTask]:
    """
    Universally registers any rendered video into the Master Queue, displays
    the interactive Save / Upload / Both prompt, and notifies the Queue UI.
    """
    if not video_path or not os.path.exists(video_path):
        return None

    clean_title = title or os.path.basename(video_path)
    task = MASTER_QUEUE.add_completed_video(
        video_path=video_path,
        title=clean_title,
        tool_name=tool_name
    )

    if show_popup:
        try:
            show_video_completion_popup(
                video_path=video_path,
                title=clean_title,
                tool_name=tool_name
            )
        except Exception as ex:
            print(f"[QUEUE] Popup error: {ex}")

    return task


# ── Master Queue UI Tab Frame ────────────────────────────────────────────────
class MasterQueueFrame(ctk.CTkFrame):
    """Universal Master Queue View — Manage rendering, saving, and uploading across all tools."""

    def __init__(self, master, boot_data=None):
        super().__init__(master, fg_color="#080c14")
        self.pack(fill="both", expand=True)

        # 1. Header Control Bar
        head = ctk.CTkFrame(self, fg_color="#0f172a", corner_radius=12, border_width=1, border_color="#1e293b")
        head.pack(fill="x", padx=10, pady=(10, 6))

        ctk.CTkLabel(
            head, text="🗂️ MASTER RENDER QUEUE",
            font=("Segoe UI", 16, "bold"), text_color="#38bdf8"
        ).pack(side="left", padx=14, pady=12)

        # Mode Indicator Pill
        self.mode_pill = ctk.CTkLabel(
            head, text="● Mode: Sequential",
            font=("Consolas", 11, "bold"), text_color="#10b981",
            fg_color="#064e3b", corner_radius=8
        )
        self.mode_pill.pack(side="left", padx=6, pady=12)

        # Mode Run Buttons
        ctk.CTkButton(
            head, text="▶ Run One-by-One (Sequential)",
            height=32, fg_color="#8b5cf6", hover_color="#7c3aed",
            font=("Segoe UI", 11, "bold"), corner_radius=8,
            command=self._on_run_sequential
        ).pack(side="left", padx=(12, 4))

        ctk.CTkButton(
            head, text="⚡ Run Parallel (Batch All)",
            height=32, fg_color="#10b981", hover_color="#059669",
            font=("Segoe UI", 11, "bold"), corner_radius=8,
            command=self._on_run_parallel
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            head, text="⏸ Pause",
            height=32, width=80, fg_color="#f59e0b", hover_color="#d97706",
            font=("Segoe UI", 11, "bold"), corner_radius=8,
            command=self._on_pause
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            head, text="🗑 Clear Finished",
            height=32, width=120, fg_color="#1e293b", hover_color="#334155",
            font=("Segoe UI", 11), corner_radius=8,
            command=self._on_clear
        ).pack(side="right", padx=14)

        self.task_count_lbl = ctk.CTkLabel(head, text="0 tasks", font=("Segoe UI", 11), text_color="#94a3b8")
        self.task_count_lbl.pack(side="right", padx=6)

        # 2. Target YouTube Channel Bar
        ch_bar = ctk.CTkFrame(self, fg_color="#0b1322", corner_radius=10, border_width=1, border_color="#1e293b")
        ch_bar.pack(fill="x", padx=10, pady=(0, 6))

        ctk.CTkLabel(
            ch_bar, text="📺 Target YouTube Channel:",
            font=("Segoe UI", 11, "bold"), text_color="#38bdf8"
        ).pack(side="left", padx=(14, 6), pady=8)

        self.ch_menu = ctk.CTkOptionMenu(
            ch_bar, values=["Loading channels..."], width=300, height=30,
            fg_color="#1e293b", font=("Segoe UI", 11)
        )
        self.ch_menu.pack(side="left", padx=4, pady=8)

        self.add_ch_btn = ctk.CTkButton(
            ch_bar, text="➕ Add Channel", width=110, height=30,
            fg_color="#2563eb", hover_color="#1d4ed8", font=("Segoe UI", 11, "bold"),
            command=self._on_add_channel
        )
        self.add_ch_btn.pack(side="left", padx=4, pady=8)

        self.refresh_ch_btn = ctk.CTkButton(
            ch_bar, text="🔄 Refresh", width=80, height=30,
            fg_color="#1e293b", hover_color="#334155", font=("Segoe UI", 11),
            command=self._refresh_channels
        )
        self.refresh_ch_btn.pack(side="left", padx=4, pady=8)

        self.api_cfg_btn = ctk.CTkButton(
            ch_bar, text="⚙️ API Config", width=95, height=30,
            fg_color="#334155", hover_color="#475569", font=("Segoe UI", 11),
            command=self._on_api_config
        )
        self.api_cfg_btn.pack(side="left", padx=4, pady=8)

        self.ch_id_map = {}
        self._refresh_channels()

        # Subtitle Helper
        ctk.CTkLabel(
            self,
            text="ℹ️ Every rendered video automatically appears here. Choose 💾 Save, 📤 Upload, or ⚡ Both (Save & Upload) on any video.",
            font=("Segoe UI", 10), text_color="#64748b"
        ).pack(anchor="w", padx=16, pady=(0, 4))

        # Scrollable Task List
        self.scroll_list = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll_list.pack(fill="both", expand=True, padx=10, pady=6)

        self._row_widgets: Dict[str, Dict[str, Any]] = {}
        MASTER_QUEUE.subscribe(self._request_rebuild)

        self._refresh_timer()

    def _refresh_channels(self, target_id=None):
        names, lookup, _ = get_channel_map()
        self.ch_id_map = lookup
        if names:
            self.ch_menu.configure(values=names)
            sel = names[0]
            if target_id:
                for nm, cid in lookup.items():
                    if cid == target_id:
                        sel = nm
                        break
            self.ch_menu.set(sel)
        else:
            self.ch_menu.configure(values=["No YouTube channel connected"])
            self.ch_menu.set("No YouTube channel connected")

    def _on_add_channel(self):
        try:
            from uploader_engine.api import open_connect_channel_dialog
            open_connect_channel_dialog(self, on_success=lambda p: self._refresh_channels(p.get("id")))
        except Exception as ex:
            messagebox.showerror("Error", str(ex))

    def _on_api_config(self):
        try:
            from uploader_engine.api import open_api_settings_dialog
            open_api_settings_dialog(self, on_saved=self._refresh_channels)
        except Exception as ex:
            messagebox.showerror("Error", str(ex))

    def _on_run_sequential(self):
        MASTER_QUEUE.run_one_by_one()
        self.mode_pill.configure(text="● Mode: Sequential", fg_color="#064e3b", text_color="#34d399")

    def _on_run_parallel(self):
        MASTER_QUEUE.run_parallel()
        self.mode_pill.configure(text="● Mode: Parallel (All)", fg_color="#1e3a8a", text_color="#60a5fa")

    def _on_pause(self):
        MASTER_QUEUE.pause_queue()
        self.mode_pill.configure(text="● Mode: Paused", fg_color="#78350f", text_color="#fde047")

    def _on_clear(self):
        MASTER_QUEUE.clear_finished()
        self._rebuild_ui()

    def _request_rebuild(self):
        try:
            self.after(0, self._rebuild_ui)
        except Exception:
            pass

    def _refresh_timer(self):
        """Update live progress bars & status messages every 400ms."""
        try:
            tasks = MASTER_QUEUE.tasks
            self.task_count_lbl.configure(text=f"{len(tasks)} tasks")

            for t in tasks:
                if t.id in self._row_widgets:
                    w = self._row_widgets[t.id]
                    if t.status == "Rendering" and t.start_time:
                        elapsed = int(time.time() - t.start_time)
                        time_badge = f"⏱️ {elapsed}s"
                        stat_text = f"[{t.status} • {time_badge}] {t.status_msg}"
                        stat_col = "#38bdf8"
                    elif t.status == "Completed":
                        stat_text = f"[{t.status}] {t.status_msg}"
                        stat_col = "#10b981"
                    elif t.status == "Failed":
                        stat_text = f"[{t.status}] {t.status_msg}"
                        stat_col = "#ef4444"
                    else:
                        stat_text = f"[{t.status}] {t.status_msg}"
                        stat_col = "#94a3b8"

                    w["status_lbl"].configure(text=stat_text, text_color=stat_col)
                    w["prog_bar"].set(t.progress_pct / 100.0)
                    w["pct_lbl"].configure(text=f"{int(t.progress_pct)}%")
                    
                    if t.status == "Completed" and t.output_path and os.path.exists(t.output_path):
                        w["play_btn"].configure(state="normal")
                        w["save_btn"].configure(state="normal")
                        w["upload_btn"].configure(state="normal")
                        w["both_btn"].configure(state="normal")
        except Exception:
            pass

        try:
            self.after(400, self._refresh_timer)
        except Exception:
            pass

    def _rebuild_ui(self):
        # Clear list
        for child in self.scroll_list.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass
        self._row_widgets.clear()

        tasks = MASTER_QUEUE.tasks
        self.task_count_lbl.configure(text=f"{len(tasks)} tasks")

        if not tasks:
            empty_box = ctk.CTkFrame(self.scroll_list, fg_color="#0f172a", corner_radius=12, border_width=1, border_color="#1e293b")
            empty_box.pack(fill="x", padx=10, pady=30)
            ctk.CTkLabel(
                empty_box,
                text="📭 No jobs in Master Queue.\nWhenever you render a video in any tool, it will appear here automatically\nwith instant options to Save, Upload, or Both!",
                font=("Segoe UI", 12), text_color="#64748b"
            ).pack(pady=30)
            return

        for t in tasks:
            row = ctk.CTkFrame(self.scroll_list, fg_color="#0f172a", corner_radius=10, border_width=1, border_color="#1e293b")
            row.pack(fill="x", pady=4)
            row.grid_columnconfigure(1, weight=1)

            # Tool Chip
            t_chip = ctk.CTkLabel(
                row, text=f" {t.tool_name} ",
                font=("Segoe UI", 10, "bold"), text_color="#38bdf8",
                fg_color="#082f49", corner_radius=6
            )
            t_chip.grid(row=0, column=0, padx=10, pady=(10, 4), sticky="w")

            # Title
            ctk.CTkLabel(
                row, text=t.title,
                font=("Segoe UI", 12, "bold"), text_color="#f8fafc"
            ).grid(row=0, column=1, padx=6, pady=(10, 4), sticky="w")

            # Timestamp
            ctk.CTkLabel(
                row, text=f"Added: {t.created_at}",
                font=("Consolas", 10), text_color="#64748b"
            ).grid(row=0, column=2, padx=10, pady=(10, 4), sticky="e")

            # Progress Bar & Status Line
            prog_bar = ctk.CTkProgressBar(row, height=8, corner_radius=4, progress_color="#38bdf8", fg_color="#1e293b")
            prog_bar.grid(row=1, column=0, columnspan=2, padx=(10, 6), pady=(2, 4), sticky="ew")
            prog_bar.set(t.progress_pct / 100.0)

            pct_lbl = ctk.CTkLabel(row, text=f"{int(t.progress_pct)}%", font=("Consolas", 10, "bold"), text_color="#38bdf8")
            pct_lbl.grid(row=1, column=2, padx=10, pady=(2, 4), sticky="e")

            stat_col = "#10b981" if t.status == "Completed" else "#ef4444" if t.status == "Failed" else "#38bdf8" if t.status == "Rendering" else "#94a3b8"
            status_lbl = ctk.CTkLabel(row, text=f"[{t.status}] {t.status_msg}", font=("Segoe UI", 10), text_color=stat_col)
            status_lbl.grid(row=2, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="w")

            # Action Buttons Box
            act_box = ctk.CTkFrame(row, fg_color="transparent")
            act_box.grid(row=2, column=2, padx=10, pady=(0, 10), sticky="e")

            def _play(path=t.output_path):
                if path and os.path.exists(path):
                    os.startfile(path)

            def _save_only(path=t.output_path):
                if path and os.path.exists(path):
                    if sys.platform == "win32":
                        subprocess.Popen(f'explorer /select,"{os.path.abspath(path)}"')
                    else:
                        os.startfile(os.path.dirname(os.path.abspath(path)))
                    messagebox.showinfo("Saved", f"✓ File saved locally:\n{path}")

            def _upload_only(path=t.output_path, title_txt=t.title):
                if path and os.path.exists(path):
                    sel_name = self.ch_menu.get()
                    cid = self.ch_id_map.get(sel_name)
                    if cid:
                        try:
                            from uploader_engine.api import queue_video_for_upload
                            clean_t = title_txt.split(":")[-1].strip() if ":" in title_txt else title_txt
                            queue_video_for_upload(
                                video_path=path,
                                title=clean_t,
                                channel_id=cid,
                                privacy_status="public"
                            )
                            messagebox.showinfo("Queued", f"🚀 Video '{clean_t}' queued for upload to {sel_name}!")
                        except Exception as ex:
                            messagebox.showerror("Upload Error", str(ex))
                    else:
                        from uploader_engine.api import show_quick_upload_modal
                        show_quick_upload_modal(parent=self, video_path=path, default_title=title_txt)

            def _both_save_and_upload(path=t.output_path, title_txt=t.title):
                if path and os.path.exists(path):
                    _save_only(path)
                    _upload_only(path, title_txt)

            def _del(tid=t.id):
                MASTER_QUEUE.remove_task(tid)

            def _expand(task_obj=t):
                TaskLiveInspectorDialog(self, task_obj)

            play_btn = ctk.CTkButton(
                act_box, text="▶ Play", width=60, height=26,
                fg_color="#10b981", hover_color="#059669", font=("Segoe UI", 10, "bold"),
                state="normal" if t.status == "Completed" else "disabled",
                command=_play
            )
            play_btn.pack(side="left", padx=2)

            save_btn = ctk.CTkButton(
                act_box, text="💾 Save", width=64, height=26,
                fg_color="#3b82f6", hover_color="#2563eb", font=("Segoe UI", 10, "bold"),
                state="normal" if t.status == "Completed" else "disabled",
                command=_save_only
            )
            save_btn.pack(side="left", padx=2)

            upload_btn = ctk.CTkButton(
                act_box, text="📤 Upload", width=70, height=26,
                fg_color="#ff0033", hover_color="#d4002a", font=("Segoe UI", 10, "bold"),
                state="normal" if t.status == "Completed" else "disabled",
                command=_upload_only
            )
            upload_btn.pack(side="left", padx=2)

            both_btn = ctk.CTkButton(
                act_box, text="⚡ Both", width=62, height=26,
                fg_color="#8b5cf6", hover_color="#7c3aed", font=("Segoe UI", 10, "bold"),
                state="normal" if t.status == "Completed" else "disabled",
                command=_both_save_and_upload
            )
            both_btn.pack(side="left", padx=2)

            expand_btn = ctk.CTkButton(
                act_box, text="🔍", width=32, height=26,
                fg_color="#1e293b", hover_color="#334155", font=("Segoe UI", 10),
                command=_expand
            )
            expand_btn.pack(side="left", padx=2)

            ctk.CTkButton(
                act_box, text="✕", width=28, height=26,
                fg_color="#1e293b", hover_color="#ef4444", text_color="#ef4444",
                font=("Segoe UI", 10),
                command=_del
            ).pack(side="left", padx=2)

            self._row_widgets[t.id] = {
                "prog_bar": prog_bar,
                "pct_lbl": pct_lbl,
                "status_lbl": status_lbl,
                "play_btn": play_btn,
                "save_btn": save_btn,
                "upload_btn": upload_btn,
                "both_btn": both_btn
            }


# ── Expanded Live Task Inspector Window ──────────────────────────────────────
class TaskLiveInspectorDialog(ctk.CTkToplevel):
    def __init__(self, parent, task: UniversalQueueTask):
        super().__init__(parent)
        self.task = task
        self.title(f"🔍 Render Inspector — {task.title}")
        self.geometry("720x520")
        self.minsize(620, 420)
        self.configure(fg_color="#080c14")
        self.attributes("-topmost", True)

        card = ctk.CTkFrame(self, fg_color="#0f172a", corner_radius=12, border_width=1, border_color="#1e293b")
        card.pack(fill="both", expand=True, padx=12, pady=12)

        # Header Info Bar
        top_bar = ctk.CTkFrame(card, fg_color="#082f49", corner_radius=8)
        top_bar.pack(fill="x", padx=10, pady=(10, 6))

        ctk.CTkLabel(
            top_bar, text=f"🎬 {task.tool_name}",
            font=("Segoe UI", 11, "bold"), text_color="#38bdf8"
        ).pack(side="left", padx=10, pady=8)

        self.title_lbl = ctk.CTkLabel(
            top_bar, text=f"• {task.title}",
            font=("Segoe UI", 12, "bold"), text_color="#f8fafc"
        )
        self.title_lbl.pack(side="left", padx=6, pady=8)

        self.status_pill = ctk.CTkLabel(
            top_bar, text=f" {task.status} ",
            font=("Consolas", 11, "bold"), text_color="#34d399",
            fg_color="#064e3b", corner_radius=6
        )
        self.status_pill.pack(side="right", padx=10, pady=8)

        # Progress Section
        prog_frame = ctk.CTkFrame(card, fg_color="transparent")
        prog_frame.pack(fill="x", padx=10, pady=4)

        self.prog_bar = ctk.CTkProgressBar(prog_frame, height=14, corner_radius=7, progress_color="#38bdf8", fg_color="#1e293b")
        self.prog_bar.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.prog_bar.set(task.progress_pct / 100.0)

        self.pct_lbl = ctk.CTkLabel(prog_frame, text=f"{int(task.progress_pct)}%", font=("Consolas", 13, "bold"), text_color="#38bdf8")
        self.pct_lbl.pack(side="right")

        self.live_msg = ctk.CTkLabel(card, text=task.status_msg, font=("Segoe UI", 11), text_color="#94a3b8", anchor="w")
        self.live_msg.pack(fill="x", padx=12, pady=(0, 6))

        # Log Terminal Header
        log_hdr = ctk.CTkFrame(card, fg_color="transparent")
        log_hdr.pack(fill="x", padx=10, pady=(4, 2))
        ctk.CTkLabel(log_hdr, text="📋 Live Pipeline Log Output:", font=("Segoe UI", 11, "bold"), text_color="#cbd5e1").pack(side="left")
        self.timer_lbl = ctk.CTkLabel(log_hdr, text="⏱️ 0s", font=("Consolas", 10, "bold"), text_color="#fde047")
        self.timer_lbl.pack(side="right")

        # Log Terminal Box
        self.log_box = ctk.CTkTextbox(card, font=("Consolas", 10), fg_color="#050811", text_color="#94a3b8", border_width=1, border_color="#1e293b")
        self.log_box.pack(fill="both", expand=True, padx=10, pady=4)

        # Action Buttons
        bot_bar = ctk.CTkFrame(card, fg_color="transparent")
        bot_bar.pack(fill="x", padx=10, pady=(6, 10))

        self.play_btn = ctk.CTkButton(
            bot_bar, text="▶ Play Video", width=110, height=32,
            fg_color="#10b981", hover_color="#059669", font=("Segoe UI", 11, "bold"),
            state="normal" if task.status == "Completed" else "disabled",
            command=self._play_video
        )
        self.play_btn.pack(side="left", padx=4)

        self.folder_btn = ctk.CTkButton(
            bot_bar, text="📂 Open Folder", width=120, height=32,
            fg_color="#3b82f6", hover_color="#2563eb", font=("Segoe UI", 11),
            state="normal" if task.status == "Completed" else "disabled",
            command=self._open_folder
        )
        self.folder_btn.pack(side="left", padx=4)

        ctk.CTkButton(
            bot_bar, text="Close", width=80, height=32,
            fg_color="#1e293b", hover_color="#334155", font=("Segoe UI", 11),
            command=self.destroy
        ).pack(side="right", padx=4)

        self._last_log_len = 0
        self._update_loop()

    def _update_loop(self):
        try:
            if not self.winfo_exists():
                return
            t = self.task
            self.prog_bar.set(t.progress_pct / 100.0)
            self.pct_lbl.configure(text=f"{int(t.progress_pct)}%")
            self.live_msg.configure(text=t.status_msg)

            if t.start_time and t.status == "Rendering":
                el = int(time.time() - t.start_time)
                self.timer_lbl.configure(text=f"⏱️ Running: {el}s")
                self.status_pill.configure(text=" Rendering ", fg_color="#082f49", text_color="#38bdf8")
            elif t.status == "Completed":
                self.timer_lbl.configure(text=f"✓ Done in {t.elapsed_secs}s", text_color="#10b981")
                self.status_pill.configure(text=" Completed ", fg_color="#064e3b", text_color="#34d399")
                self.play_btn.configure(state="normal")
                self.folder_btn.configure(state="normal")
            elif t.status == "Failed":
                self.timer_lbl.configure(text="❌ Failed", text_color="#ef4444")
                self.status_pill.configure(text=" Failed ", fg_color="#7f1d1d", text_color="#f87171")

            # Update logs
            if len(t.logs) != self._last_log_len:
                new_logs = t.logs[self._last_log_len:]
                self.log_box.insert("end", "\n".join(new_logs) + "\n")
                self.log_box.see("end")
                self._last_log_len = len(t.logs)

            self.after(250, self._update_loop)
        except Exception:
            pass

    def _play_video(self):
        p = self.task.output_path
        if p and os.path.exists(p):
            try:
                os.startfile(p)
            except Exception:
                pass

    def _open_folder(self):
        p = self.task.output_path
        if p and os.path.exists(p):
            try:
                subprocess.Popen(f'explorer /select,"{os.path.abspath(p)}"')
            except Exception:
                pass
