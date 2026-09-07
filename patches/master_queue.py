"""
master_queue.py — Universal Master Render Queue & Completion Notification System
═════════════════════════════════════════════════════════════════════════════════
Central rendering hub for ALL tools in StoriesStudio / AI Editor:
- Story Image Video, Recap Studio, Stories, Rhymes, Shorts, Jesus Prayer, etc.
- Modes: Sequential (One-by-One) OR Parallel (Batch Processing).
- Live progress tracking, cancellation, and error handling.
- Completion notification popup with sound, '▶ Play Video', and '📂 Open Folder'.
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
                # Play Windows Asterisk / Notification chime
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            else:
                import pygame
                pygame.mixer.init()
                # Default beep
        except Exception:
            pass
    threading.Thread(target=_sound_worker, daemon=True).start()


# ── Completion Notification Popup Window ─────────────────────────────────────
_active_notification_dialog = None

def show_video_completion_popup(parent=None, video_path: str = "", title: str = "Video Rendered Successfully!"):
    """
    Display a modern futuristic completion notification popup with Play and Open Folder actions.
    """
    play_completion_chime()

    def _open_video():
        if video_path and os.path.exists(video_path):
            try:
                os.startfile(video_path)
            except Exception as e:
                print(f"[QUEUE] Open video error: {e}")

    def _open_folder():
        if video_path and os.path.exists(video_path):
            try:
                folder = os.path.dirname(os.path.abspath(video_path))
                if sys.platform == "win32":
                    subprocess.Popen(f'explorer /select,"{os.path.abspath(video_path)}"')
                else:
                    os.startfile(folder)
            except Exception as e:
                print(f"[QUEUE] Open folder error: {e}")

    # Build sleek popup modal
    try:
        top = ctk.CTkToplevel()
        top.title("🎉 Render Completed!")
        top.geometry("520x280")
        top.minsize(480, 260)
        top.configure(fg_color="#080c14")
        top.attributes("-topmost", True)
        top.focus_force()

        card = ctk.CTkFrame(top, fg_color="#0f172a", corner_radius=16, border_width=2, border_color="#10b981")
        card.pack(fill="both", expand=True, padx=12, pady=12)

        # Header Badge
        badge = ctk.CTkFrame(card, fg_color="#064e3b", corner_radius=10, border_width=1, border_color="#10b981")
        badge.pack(pady=(16, 6))
        ctk.CTkLabel(badge, text="  ✓ RENDER COMPLETE • 100%  ", font=("Segoe UI", 10, "bold"), text_color="#34d399").pack(padx=8, pady=3)

        ctk.CTkLabel(card, text=f"✨ {title}", font=("Segoe UI", 15, "bold"), text_color="#f8fafc").pack(pady=(0, 4))
        
        file_name = os.path.basename(video_path) if video_path else "video.mp4"
        ctk.CTkLabel(card, text=f"📁 {file_name}", font=("Consolas", 11), text_color="#94a3b8").pack(pady=(0, 16))

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=6)

        # ▶ Play Video Button
        ctk.CTkButton(
            btn_row,
            text="▶ Play Video",
            height=38,
            fg_color="#10b981",
            hover_color="#059669",
            text_color="#ffffff",
            font=("Segoe UI", 12, "bold"),
            corner_radius=9,
            command=lambda: (_open_video(), top.destroy())
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))

        # 📂 Open Folder Button
        ctk.CTkButton(
            btn_row,
            text="📂 Open Folder",
            height=38,
            fg_color="#3b82f6",
            hover_color="#2563eb",
            text_color="#ffffff",
            font=("Segoe UI", 12, "bold"),
            corner_radius=9,
            command=lambda: (_open_folder(), top.destroy())
        ).pack(side="left", fill="x", expand=True, padx=6)

        # ❌ Close Button
        ctk.CTkButton(
            btn_row,
            text="Dismiss",
            height=38,
            width=80,
            fg_color="#1e293b",
            hover_color="#334155",
            text_color="#cbd5e1",
            font=("Segoe UI", 11),
            corner_radius=9,
            command=top.destroy
        ).pack(side="right", padx=(6, 0))

    except Exception as e:
        print(f"[QUEUE] Could not display popup modal: {e}")
        # Fallback standard messagebox
        messagebox.showinfo("Render Complete", f"{title}\n\nFile saved to:\n{video_path}")


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
        self._thread: Optional[threading.Thread] = None
        self._is_cancelled = False

    def start(self, on_finish_callback: Optional[Callable[["UniversalQueueTask"], None]] = None):
        if self.status == "Rendering":
            return

        self.status = "Rendering"
        self.progress_pct = 0.0
        self.start_time = time.time()
        self.status_msg = "Starting render pipeline..."

        def _worker():
            try:
                def _prog_cb(pct: float):
                    self.progress_pct = max(0.0, min(100.0, float(pct)))

                def _status_cb(msg: str):
                    self.status_msg = str(msg)
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

                # Trigger completion notification popup
                show_video_completion_popup(
                    video_path=self.output_path,
                    title=f"{self.tool_name}: {self.title}"
                )

            except Exception as e:
                self.status = "Failed"
                self.error_msg = str(e)
                self.status_msg = f"❌ Error: {str(e)[:120]}"
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
        """Pause queue execution (active jobs will finish, remaining wait)."""
        with self._lock:
            self.is_running = False
            self.is_paused = True
        self._notify_listeners()

    def clear_finished(self):
        """Remove completed or failed jobs."""
        with self._lock:
            self.tasks = [t for t in self.tasks if t.status in ("Queued", "Rendering")]
            if not self.tasks:
                self.is_running = False
        self._notify_listeners()

    def remove_task(self, task_id: str):
        with self._lock:
            self.tasks = [t for t in self.tasks if t.id != task_id]
        self._notify_listeners()

    def _on_task_finish(self, finished_task: UniversalQueueTask):
        self._notify_listeners()
        if self.is_running:
            self._pump()

    def _pump(self):
        """Schedule next tasks according to active mode."""
        if not self.is_running:
            return

        with self._lock:
            queued = [t for t in self.tasks if t.status == "Queued"]
            rendering = [t for t in self.tasks if t.status == "Rendering"]

            if not queued:
                if not rendering:
                    self.is_running = False
                return

            if self.mode == "parallel":
                # Launch all queued tasks
                for t in queued:
                    t.start(on_finish_callback=self._on_task_finish)
            else:
                # Sequential: Launch only 1 task if none is currently rendering
                if len(rendering) == 0 and queued:
                    queued[0].start(on_finish_callback=self._on_task_finish)


# Global Singleton Instance
MASTER_QUEUE = MasterUniversalQueueEngine()


# ── Master Queue UI Tab Frame ────────────────────────────────────────────────
class MasterQueueFrame(ctk.CTkFrame):
    """Universal Master Queue View — Manage rendering across all tools."""

    def __init__(self, master, boot_data=None):
        super().__init__(master, fg_color="#080c14")
        self.pack(fill="both", expand=True)

        # Header Control Bar
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

        # Action Buttons
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

        # Subtitle Helper
        ctk.CTkLabel(
            self,
            text="ℹ️ Jobs added from ANY tool (Story Image Video, Recap Studio, Stories, Rhymes, etc.) appear here automatically. "
                 "Choose Sequential or Parallel rendering mode.",
            font=("Segoe UI", 10), text_color="#64748b"
        ).pack(anchor="w", padx=16, pady=(0, 4))

        # Scrollable Task List
        self.scroll_list = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll_list.pack(fill="both", expand=True, padx=10, pady=6)

        self._row_widgets: Dict[str, Dict[str, Any]] = {}
        MASTER_QUEUE.subscribe(self._request_rebuild)

        self._refresh_timer()

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
        """Update live progress bars & status messages every 500ms."""
        try:
            tasks = MASTER_QUEUE.tasks
            self.task_count_lbl.configure(text=f"{len(tasks)} tasks")

            for t in tasks:
                if t.id in self._row_widgets:
                    w = self._row_widgets[t.id]
                    # Format live timer and status
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
                        w["folder_btn"].configure(state="normal")
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
                text="📭 No jobs in Master Queue.\nGo to any tool and click '➕ Add to Queue' to queue up video tasks!",
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

            # Action Buttons Row
            act_box = ctk.CTkFrame(row, fg_color="transparent")
            act_box.grid(row=2, column=2, padx=10, pady=(0, 10), sticky="e")

            def _play(path=t.output_path):
                if path and os.path.exists(path):
                    os.startfile(path)

            def _folder(path=t.output_path):
                if path and os.path.exists(path):
                    subprocess.Popen(f'explorer /select,"{os.path.abspath(path)}"')

            def _del(tid=t.id):
                MASTER_QUEUE.remove_task(tid)

            play_btn = ctk.CTkButton(
                act_box, text="▶ Play", width=65, height=24,
                fg_color="#10b981", hover_color="#059669", font=("Segoe UI", 10, "bold"),
                state="normal" if t.status == "Completed" else "disabled",
                command=_play
            )
            play_btn.pack(side="left", padx=2)

            folder_btn = ctk.CTkButton(
                act_box, text="📂 Folder", width=70, height=24,
                fg_color="#3b82f6", hover_color="#2563eb", font=("Segoe UI", 10),
                state="normal" if t.status == "Completed" else "disabled",
                command=_folder
            )
            folder_btn.pack(side="left", padx=2)

            ctk.CTkButton(
                act_box, text="🗑", width=30, height=24,
                fg_color="#1e293b", hover_color="#ef4444", text_color="#ef4444",
                font=("Segoe UI", 10),
                command=_del
            ).pack(side="left", padx=2)

            self._row_widgets[t.id] = {
                "prog_bar": prog_bar,
                "pct_lbl": pct_lbl,
                "status_lbl": status_lbl,
                "play_btn": play_btn,
                "folder_btn": folder_btn
            }
