"""
login_window.py — Ultra-Attractive Cyberpunk & Dark Glassmorphic Studio Login Window
════════════════════════════════════════════════════════════════════════════════════
Features:
- Procedural glowing mesh-gradient background & cosmic neon orb
- Dual-mode card system:
    1. Active User Analytics Dashboard (User Name, Validity, Total Videos Exported count)
    2. Interactive Sign-In Form with eye password reveal & machine-locked validation
- Real-time cloud sync for user analytics & video export counts
- Single-root architecture support for StoriesStudio & Boot Splash Sequence
"""

import json
import os
import queue
import sys
import threading
import time
from typing import Optional, Tuple, Dict, Any, Callable

import customtkinter as ctk
from PIL import Image

import ui_theme as T
from auth_manager import (
    verify_login,
    verify_login_by_hash,
    get_machine_id,
    load_remembered,
    save_remembered,
    clear_remembered,
    get_user_profile,
    refresh_user_profile,
    get_video_exports_count,
)

ctk.set_appearance_mode("dark")

APP_NAME = "AI EDITOR"
APP_SUBTITLE = "PRO AI VIDEO PRODUCTION SUITE"
W, H = 980, 640


def resource_path(rel: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


class LoginWindow:
    def __init__(self, root: Optional[ctk.CTk] = None):
        if root is None:
            self.root = ctk.CTk()
            self._owns_root = True
        else:
            self.root = root
            self._owns_root = False
            for child in self.root.winfo_children():
                try:
                    child.destroy()
                except Exception:
                    pass
            self.root.overrideredirect(False)
            self.root.deiconify()

        self.success = False
        self.user_data: Dict[str, Any] = {}
        self._pw_visible = False
        self._is_loading = False

        self.root.title(f"{APP_NAME} — Authentication & Studio Dashboard")
        self.root.geometry(f"{W}x{H}")
        self.root.minsize(W, H)
        self.root.resizable(False, False)
        self.root.configure(fg_color=T.INK)
        self._center()

        try:
            self.root.iconbitmap(resource_path("app_icon.ico"))
        except Exception:
            pass

        # Background mesh gradient
        self._render_background()

        # Build UI layout
        self._build_left_showcase()
        self._build_right_card_container()

        # Thread-safe UI dispatch queue
        self._ui_queue: queue.Queue = queue.Queue()
        self._start_queue_poller()

        # Check remembered login state
        self._check_initial_auth_state()

        # Keyboard shortcut for Super Admin Portal
        try:
            self.root.bind("<Control-Shift-Key-A>", self._open_admin)
            self.root.bind("<Control-Shift-Key-a>", self._open_admin)
        except Exception:
            pass

    def _start_queue_poller(self):
        try:
            while not self._ui_queue.empty():
                fn, args = self._ui_queue.get_nowait()
                try:
                    fn(*args)
                except Exception as ex:
                    print(f"[UI_QUEUE] Error running callback: {ex}")
        except Exception:
            pass
        if hasattr(self, "root") and self.root.winfo_exists():
            self.root.after(35, self._start_queue_poller)

    def _dispatch_ui(self, fn: Callable, *args: Any):
        self._ui_queue.put((fn, args))

    def _open_admin(self, event=None):
        try:
            from auth_manager import is_current_user_admin
            active_user = getattr(self, "user_data", None)
            if not is_current_user_admin(active_user):
                from tkinter import messagebox
                messagebox.showerror(
                    "Unauthorized Access",
                    "⚠️ Access Denied: Unauthorized.\n\nOnly Master Super Admin (8949400100) has permission to open the Admin Panel."
                )
                return
            import admin_tool
            admin_tool.launch_gui_admin(self.root, user_data=active_user)
        except Exception as e:
            print("[ADMIN] Launch error:", e)

    def _center(self):
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - W) // 2
        y = (self.root.winfo_screenheight() - H) // 3
        self.root.geometry(f"{W}x{H}+{x}+{y}")

    def mainloop(self):
        self.root.mainloop()

    def destroy(self):
        self.root.destroy()

    def withdraw(self):
        self.root.withdraw()

    def after(self, ms: int, func: Any, *args: Any):
        return self.root.after(ms, func, *args)

    def get_root(self) -> ctk.CTk:
        return self.root

    # ══════════════════════════════════════════════════════
    # BACKGROUND MESH GRADIENT
    # ══════════════════════════════════════════════════════
    def _render_background(self):
        try:
            bg_blobs = [
                (0.12, 0.15, 0.65, T.VIOLET, 0.60),
                (0.85, 0.20, 0.55, T.CYAN, 0.40),
                (0.65, 0.90, 0.60, T.PINK, 0.35),
                (0.08, 0.85, 0.50, T.EMERALD, 0.35),
            ]
            bg = T.mesh_gradient(W, H, blobs=bg_blobs, seed_dark=T.INK)
            bg = T.noise_overlay(bg, amount=4)
            self._bg_img = ctk.CTkImage(light_image=bg, dark_image=bg, size=(W, H))
            bg_lbl = ctk.CTkLabel(self.root, image=self._bg_img, text="")
            bg_lbl.place(x=0, y=0, relwidth=1, relheight=1)
        except Exception:
            pass

    # ══════════════════════════════════════════════════════
    # LEFT BRAND SHOWCASE PANEL
    # ══════════════════════════════════════════════════════
    def _build_left_showcase(self):
        left = ctk.CTkFrame(self.root, fg_color="transparent", width=460, height=H)
        left.place(x=0, y=0)

        # Glowing Neon Logo Orb
        try:
            orb = T.glow_orb(150, T.VIOLET, 0.90)
            self._orb_img = ctk.CTkImage(light_image=orb, dark_image=orb, size=(150, 150))
            ctk.CTkLabel(left, image=self._orb_img, text="").place(x=48, y=42)
            ctk.CTkLabel(left, text="⚡", text_color="#ffffff", font=(T.FONT, 42, "bold")).place(x=105, y=92)
        except Exception:
            pass

        # Top Badge
        try:
            from updater import CURRENT_VERSION
            v_badge = f"  🚀 STORIES STUDIO V{CURRENT_VERSION}  "
        except Exception:
            v_badge = "  🚀 STORIES STUDIO V1.0  "

        top_badge = ctk.CTkFrame(left, fg_color="#132338", corner_radius=12, border_width=1, border_color=T.CYAN)
        top_badge.place(x=56, y=210)
        ctk.CTkLabel(
            top_badge,
            text=v_badge,
            text_color=T.CYAN_HI,
            font=(T.FONT, 10, "bold"),
        ).pack(padx=8, pady=4)

        # Main Brand Title
        ctk.CTkLabel(
            left,
            text=APP_NAME,
            text_color=T.TEXT,
            font=(T.FONT, 38, "bold"),
        ).place(x=54, y=250)

        ctk.CTkLabel(
            left,
            text=APP_SUBTITLE,
            text_color=T.VIOLET_HI,
            font=(T.FONT, 11, "bold"),
        ).place(x=56, y=302)

        ctk.CTkLabel(
            left,
            text="Next-Gen AI Story, Movie Recap & Audio Suite.\nMulti-voice narration, word karaoke captions\nand parallel GPU rendering.",
            text_color=T.TEXT_DIM,
            font=(T.FONT, 12),
            justify="left",
            anchor="w",
        ).place(x=56, y=332)

        # Feature Badges
        features = [
            ("⚡ GPU Accelerated", T.VIOLET),
            ("🎙️ AI Multi-Voice", T.CYAN),
            ("📝 Faster-Whisper", T.EMERALD),
            ("🎬 4K & Shorts Ready", T.GOLD),
        ]
        fx, fy = 56, 412
        for i, (feat, color) in enumerate(features):
            row = i // 2
            col = i % 2
            chip = ctk.CTkFrame(
                left,
                fg_color=T.SURFACE_HI,
                corner_radius=10,
                border_width=1,
                border_color=T.STROKE,
                height=30,
                width=175,
            )
            chip.place(x=fx + col * 185, y=fy + row * 38)
            chip.pack_propagate(False)
            ctk.CTkLabel(
                chip,
                text=feat,
                text_color=color,
                font=(T.FONT, 10, "bold"),
            ).pack(expand=True)

        # Bottom System Info & Hardware ID
        mid = get_machine_id()
        foot = ctk.CTkFrame(left, fg_color="transparent")
        foot.place(x=56, y=515)

        status_line = ctk.CTkFrame(foot, fg_color="transparent")
        status_line.pack(anchor="w")

        # Pulsing green dot indicator
        ctk.CTkLabel(status_line, text="●", text_color=T.EMERALD, font=(T.FONT, 12)).pack(side="left", padx=(0, 4))
        ctk.CTkLabel(status_line, text="System Online • Cloud Database Ready", text_color=T.TEXT_DIM, font=(T.FONT, 10, "bold")).pack(side="left")

        hw_box = ctk.CTkFrame(foot, fg_color=T.SURFACE, corner_radius=8, border_width=1, border_color=T.STROKE, height=32, width=360)
        hw_box.pack(pady=(6, 0))
        hw_box.pack_propagate(False)

        ctk.CTkLabel(
            hw_box,
            text=f"💻 HWID: {mid[:18].upper()}…",
            text_color=T.TEXT_DIM,
            font=("Consolas", 10),
        ).pack(side="left", padx=10)

        def _copy_hwid():
            self.root.clipboard_clear()
            self.root.clipboard_append(mid)
            hw_copy_btn.configure(text="✓ Copied", fg_color=T.EMERALD, text_color="#ffffff")
            self.after(1500, lambda: hw_copy_btn.configure(text="Copy", fg_color=T.SURFACE_HI, text_color=T.TEXT_DIM))

        hw_copy_btn = ctk.CTkButton(
            hw_box,
            text="Copy",
            width=55,
            height=22,
            corner_radius=6,
            fg_color=T.SURFACE_HI,
            hover_color=T.SURFACE_ACC,
            text_color=T.TEXT_DIM,
            font=(T.FONT, 9, "bold"),
            command=_copy_hwid,
        )
        hw_copy_btn.pack(side="right", padx=6)

        # (Admin Portal button removed from login screen - restricted exclusively to 8949400100 after login or Ctrl+Shift+A)

    # ══════════════════════════════════════════════════════
    # RIGHT CARD CONTAINER (DYNAMIC VIEW)
    # ══════════════════════════════════════════════════════
    def _build_right_card_container(self):
        self.right_container = ctk.CTkFrame(
            self.root,
            fg_color=T.SURFACE,
            corner_radius=20,
            border_width=1,
            border_color=T.STROKE_GLOW,
            width=430,
            height=H - 60,
        )
        self.right_container.place(x=495, y=30)
        self.right_container.pack_propagate(False)

    def _clear_right_container(self):
        for child in self.right_container.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass

    # ──────────────────────────────────────────────────────
    # INITIAL AUTH CHECK (REMEMBERED LOGIN VS FORM)
    # ──────────────────────────────────────────────────────
    def _check_initial_auth_state(self):
        saved = load_remembered()
        cached_profile = get_user_profile()

        if saved:
            u, h = saved
            # Show active user analytics dashboard directly
            self._render_analytics_dashboard(cached_profile, is_remembered=True)
            # Verify asynchronously in background to ensure fresh analytics
            threading.Thread(target=self._background_verify_saved, args=(u, h), daemon=True).start()
        else:
            self._render_login_form()

    def _background_verify_saved(self, u: str, h: str):
        try:
            res = verify_login_by_hash(u, h)
            if res.ok and res.user_data:
                self.user_data = res.user_data
                self._dispatch_ui(self._update_dashboard_ui, res.user_data)
        except Exception:
            pass

    # ══════════════════════════════════════════════════════
    # VIEW A: USER ANALYTICS & PROFILE DASHBOARD
    # ══════════════════════════════════════════════════════
    def _render_analytics_dashboard(self, profile: Dict[str, Any], is_remembered: bool = True):
        self._clear_right_container()
        self.user_data = profile

        p = self.right_container

        # Top Header & Avatar
        top_bar = ctk.CTkFrame(p, fg_color="transparent")
        top_bar.pack(fill="x", padx=24, pady=(24, 10))

        avatar = ctk.CTkFrame(top_bar, fg_color="#1e1b4b", width=52, height=52, corner_radius=26, border_width=2, border_color=T.VIOLET)
        avatar.pack(side="left", padx=(0, 14))
        avatar.pack_propagate(False)
        ctk.CTkLabel(avatar, text="👤", font=(T.FONT, 22)).pack(expand=True)

        user_info = ctk.CTkFrame(top_bar, fg_color="transparent")
        user_info.pack(side="left", fill="both", expand=True)

        ctk.CTkLabel(
            user_info,
            text="WELCOME BACK",
            text_color=T.TEXT_FAINT,
            font=(T.FONT, 10, "bold"),
            anchor="w",
        ).pack(fill="x")

        display_name = profile.get("name") or profile.get("user_id") or "Creator"
        self.dash_name_lbl = ctk.CTkLabel(
            user_info,
            text=display_name,
            text_color=T.TEXT,
            font=(T.FONT, 20, "bold"),
            anchor="w",
        )
        self.dash_name_lbl.pack(fill="x")

        uid_text = f"@{profile.get('user_id', 'user')}"
        ctk.CTkLabel(
            user_info,
            text=uid_text,
            text_color=T.CYAN_HI,
            font=(T.FONT, 11),
            anchor="w",
        ).pack(fill="x")

        # ── 3 GLOWING ANALYTICS METRIC CARDS ──
        metrics_box = ctk.CTkFrame(p, fg_color="transparent")
        metrics_box.pack(fill="x", padx=24, pady=(10, 12))

        # 1. Total Videos Exported Card
        exports_cnt = profile.get("exports_count", get_video_exports_count(profile.get("user_id")))
        self.card_exports = ctk.CTkFrame(metrics_box, fg_color=T.SURFACE_HI, corner_radius=14, border_width=1, border_color="#3b82f6")
        self.card_exports.pack(fill="x", pady=(0, 8))

        row1 = ctk.CTkFrame(self.card_exports, fg_color="transparent")
        row1.pack(fill="x", padx=14, pady=10)

        icon1 = ctk.CTkLabel(row1, text="🎬", font=(T.FONT, 22))
        icon1.pack(side="left", padx=(0, 12))

        info1 = ctk.CTkFrame(row1, fg_color="transparent")
        info1.pack(side="left", fill="both", expand=True)

        ctk.CTkLabel(info1, text="TOTAL VIDEOS EXPORTED", text_color=T.TEXT_DIM, font=(T.FONT, 10, "bold"), anchor="w").pack(fill="x")
        self.dash_exports_lbl = ctk.CTkLabel(info1, text=f"{exports_cnt} Videos", text_color="#38bdf8", font=(T.FONT, 18, "bold"), anchor="w")
        self.dash_exports_lbl.pack(fill="x")

        # 2. License Validity Card
        val_display = profile.get("validity_display", "✨ Lifetime Access")
        badge_color = profile.get("badge_color", T.EMERALD)

        self.card_validity = ctk.CTkFrame(metrics_box, fg_color=T.SURFACE_HI, corner_radius=14, border_width=1, border_color=badge_color)
        self.card_validity.pack(fill="x", pady=(0, 8))

        row2 = ctk.CTkFrame(self.card_validity, fg_color="transparent")
        row2.pack(fill="x", padx=14, pady=10)

        icon2 = ctk.CTkLabel(row2, text="🛡️", font=(T.FONT, 22))
        icon2.pack(side="left", padx=(0, 12))

        info2 = ctk.CTkFrame(row2, fg_color="transparent")
        info2.pack(side="left", fill="both", expand=True)

        ctk.CTkLabel(info2, text="LICENSE VALIDITY", text_color=T.TEXT_DIM, font=(T.FONT, 10, "bold"), anchor="w").pack(fill="x")
        self.dash_val_lbl = ctk.CTkLabel(info2, text=val_display, text_color=badge_color, font=(T.FONT, 14, "bold"), anchor="w")
        self.dash_val_lbl.pack(fill="x")

        # 3. Device Status Card
        card_dev = ctk.CTkFrame(metrics_box, fg_color=T.SURFACE_HI, corner_radius=14, border_width=1, border_color=T.STROKE)
        card_dev.pack(fill="x")

        row3 = ctk.CTkFrame(card_dev, fg_color="transparent")
        row3.pack(fill="x", padx=14, pady=8)

        icon3 = ctk.CTkLabel(row3, text="💻", font=(T.FONT, 18))
        icon3.pack(side="left", padx=(0, 12))

        info3 = ctk.CTkFrame(row3, fg_color="transparent")
        info3.pack(side="left", fill="both", expand=True)

        is_univ = profile.get("universal") or (str(profile.get("user_id", "")).strip().lower() in ("8949400100", "ravibadra9"))
        dev_text = "Authorized • Universal Multi-PC (Unlimited)" if is_univ else "Authorized • Single Machine Lock"
        ctk.CTkLabel(info3, text="HARDWARE AUTHORIZATION", text_color=T.TEXT_DIM, font=(T.FONT, 9, "bold"), anchor="w").pack(fill="x")
        ctk.CTkLabel(info3, text=dev_text, text_color=T.EMERALD_HI, font=(T.FONT, 12, "bold"), anchor="w").pack(fill="x")

        # ── ACTION BUTTONS ──
        actions = ctk.CTkFrame(p, fg_color="transparent")
        actions.pack(fill="x", padx=24, pady=(12, 0))

        # Main Launch Button
        self.launch_btn = ctk.CTkButton(
            actions,
            text="🚀  Launch Studio",
            height=46,
            corner_radius=12,
            fg_color="#10b981",
            hover_color="#059669",
            text_color="#ffffff",
            font=(T.FONT, 14, "bold"),
            command=self._launch_studio_action,
        )
        self.launch_btn.pack(fill="x", pady=(0, 8))

        from auth_manager import is_current_user_admin
        if is_current_user_admin(profile):
            self.admin_btn = ctk.CTkButton(
                actions,
                text="👑  Open Super Admin Portal",
                height=38,
                corner_radius=10,
                fg_color="#6366f1",
                hover_color="#4f46e5",
                text_color="#ffffff",
                font=(T.FONT, 12, "bold"),
                command=self._open_admin,
            )
            self.admin_btn.pack(fill="x", pady=(0, 8))

        # Secondary Actions (Sync Analytics & Switch Account)
        sec_row = ctk.CTkFrame(actions, fg_color="transparent")
        sec_row.pack(fill="x")

        self.btn_sync = ctk.CTkButton(
            sec_row,
            text="🔄 Sync Cloud",
            width=180,
            height=32,
            corner_radius=8,
            fg_color=T.SURFACE_HI,
            hover_color=T.SURFACE_ACC,
            text_color=T.CYAN_HI,
            font=(T.FONT, 11, "bold"),
            command=self._sync_analytics_action,
        )
        self.btn_sync.pack(side="left", padx=(0, 6), expand=True, fill="x")

        btn_switch = ctk.CTkButton(
            sec_row,
            text="👤 Switch Account",
            width=180,
            height=32,
            corner_radius=8,
            fg_color=T.SURFACE_HI,
            hover_color=T.SURFACE_ACC,
            text_color=T.TEXT_DIM,
            font=(T.FONT, 11),
            command=self._switch_account_action,
        )
        btn_switch.pack(side="right", padx=(6, 0), expand=True, fill="x")

        self.dash_status = ctk.CTkLabel(p, text="", font=(T.FONT, 10), text_color=T.TEXT_DIM)
        self.dash_status.pack(pady=(8, 0))

    def _update_dashboard_ui(self, profile: Dict[str, Any]):
        try:
            if hasattr(self, "dash_name_lbl") and self.dash_name_lbl.winfo_exists():
                name = profile.get("name") or profile.get("user_id") or "Creator"
                self.dash_name_lbl.configure(text=name)
            if hasattr(self, "dash_exports_lbl") and self.dash_exports_lbl.winfo_exists():
                cnt = profile.get("exports_count", get_video_exports_count(profile.get("user_id")))
                self.dash_exports_lbl.configure(text=f"{cnt} Videos")
            if hasattr(self, "dash_val_lbl") and self.dash_val_lbl.winfo_exists():
                val = profile.get("validity_display", "✨ Lifetime Access")
                col = profile.get("badge_color", T.EMERALD)
                self.dash_val_lbl.configure(text=val, text_color=col)
                if hasattr(self, "card_validity") and self.card_validity.winfo_exists():
                    self.card_validity.configure(border_color=col)
        except Exception:
            pass

    def _sync_analytics_action(self):
        self.btn_sync.configure(state="disabled", text="⏳ Syncing...")
        self.dash_status.configure(text="Fetching latest cloud analytics...", text_color=T.CYAN)

        def _worker():
            refreshed = refresh_user_profile(self.user_data.get("user_id"))
            self.user_data = refreshed

            def _done():
                self._update_dashboard_ui(refreshed)
                self.btn_sync.configure(state="normal", text="✓ Synced")
                self.dash_status.configure(text="Cloud analytics synchronized successfully ✓", text_color=T.EMERALD)
                self.after(2000, lambda: self.btn_sync.configure(text="🔄 Sync Cloud"))

            self._dispatch_ui(_done)

        threading.Thread(target=_worker, daemon=True).start()

    def _launch_studio_action(self):
        self.launch_btn.configure(state="disabled", text="🚀 Starting Studio...")
        self.success = True
        self.after(300, self._finish_success)

    def _switch_account_action(self):
        clear_remembered()
        self._render_login_form()

    # ══════════════════════════════════════════════════════
    # VIEW B: SIGN-IN FORM
    # ══════════════════════════════════════════════════════
    def _render_login_form(self):
        self._clear_right_container()
        p = self.right_container

        # Header Title
        ctk.CTkLabel(
            p,
            text="Studio Sign In",
            text_color=T.TEXT,
            font=(T.FONT, 24, "bold"),
        ).pack(pady=(36, 4))

        ctk.CTkLabel(
            p,
            text="Enter your credentials to access your production tools",
            text_color=T.TEXT_DIM,
            font=(T.FONT, 11),
        ).pack(pady=(0, 24))

        # USER ID field
        ctk.CTkLabel(
            p,
            text="USER ID / USERNAME",
            text_color=T.TEXT_FAINT,
            font=(T.FONT, 10, "bold"),
            anchor="w",
            width=320,
        ).pack(pady=(0, 6))

        self.user_entry = ctk.CTkEntry(
            p,
            placeholder_text="e.g. creator_pro",
            width=320,
            height=44,
            corner_radius=10,
            fg_color=T.SURFACE_HI,
            border_color=T.STROKE,
            border_width=1,
            text_color=T.TEXT,
            placeholder_text_color=T.TEXT_FAINT,
            font=(T.FONT, 13),
        )
        self.user_entry.pack(pady=(0, 14))
        self.user_entry.bind("<FocusIn>", lambda e: self.user_entry.configure(border_color=T.VIOLET))
        self.user_entry.bind("<FocusOut>", lambda e: self.user_entry.configure(border_color=T.STROKE))
        self.user_entry.bind("<Return>", lambda e: self._attempt_login())

        # PASSWORD field with Eye toggle
        ctk.CTkLabel(
            p,
            text="PASSWORD",
            text_color=T.TEXT_FAINT,
            font=(T.FONT, 10, "bold"),
            anchor="w",
            width=320,
        ).pack(pady=(0, 6))

        pw_frame = ctk.CTkFrame(
            p,
            fg_color=T.SURFACE_HI,
            corner_radius=10,
            border_width=1,
            border_color=T.STROKE,
            height=44,
            width=320,
        )
        pw_frame.pack(pady=(0, 10))
        pw_frame.pack_propagate(False)

        self.pw_entry = ctk.CTkEntry(
            pw_frame,
            placeholder_text="Enter your password",
            width=265,
            height=40,
            corner_radius=0,
            fg_color="transparent",
            border_width=0,
            text_color=T.TEXT,
            placeholder_text_color=T.TEXT_FAINT,
            font=(T.FONT, 13),
            show="●",
        )
        self.pw_entry.pack(side="left", padx=(10, 0), pady=2)
        self.pw_entry.bind("<Return>", lambda e: self._attempt_login())

        self.eye_btn = ctk.CTkButton(
            pw_frame,
            text="👁",
            width=36,
            height=34,
            corner_radius=6,
            fg_color="transparent",
            hover_color=T.SURFACE_ACC,
            text_color=T.TEXT_DIM,
            font=(T.FONT, 14),
            command=self._toggle_pw_visibility,
        )
        self.eye_btn.pack(side="right", padx=(0, 4))

        # Remember Me Checkbox
        self.remember_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            p,
            text="Remember me on this machine",
            variable=self.remember_var,
            text_color=T.TEXT_DIM,
            font=(T.FONT, 11),
            fg_color=T.VIOLET,
            hover_color=T.VIOLET_HI,
            border_color=T.STROKE,
            checkmark_color="#ffffff",
            corner_radius=4,
            height=24,
            width=320,
        ).pack(pady=(4, 18), anchor="center")

        # Submit Button
        self.submit_btn = ctk.CTkButton(
            p,
            text="Sign In & Load Profile ⚡",
            height=46,
            width=320,
            corner_radius=12,
            fg_color=T.VIOLET,
            hover_color=T.VIOLET_HI,
            text_color="#ffffff",
            font=(T.FONT, 13, "bold"),
            command=self._attempt_login,
        )
        self.submit_btn.pack(pady=(0, 10))

        # Status feedback label
        self.status_lbl = ctk.CTkLabel(
            p,
            text="",
            text_color=T.TEXT_FAINT,
            font=(T.FONT, 11),
            wraplength=310,
            justify="center",
        )
        self.status_lbl.pack(pady=(6, 0))

        # Fill with any cached username
        prof = get_user_profile()
        if prof and prof.get("user_id") and prof.get("user_id") != "Guest":
            self.user_entry.insert(0, prof.get("user_id"))

    def _toggle_pw_visibility(self):
        self._pw_visible = not self._pw_visible
        if self._pw_visible:
            self.pw_entry.configure(show="")
            self.eye_btn.configure(text="🔒")
        else:
            self.pw_entry.configure(show="●")
            self.eye_btn.configure(text="👁")

    def _attempt_login(self):
        if self._is_loading:
            return
        u = self.user_entry.get().strip()
        p = self.pw_entry.get().strip()

        if not u or not p:
            self.status_lbl.configure(text="Please enter both User ID and Password.", text_color=T.BAD)
            return

        self._is_loading = True
        self.submit_btn.configure(state="disabled", text="Verifying Credentials…", fg_color=T.SURFACE_ACC)
        self.status_lbl.configure(text="Connecting to authentication server...", text_color=T.CYAN)

        threading.Thread(target=self._login_worker, args=(u, p), daemon=True).start()

    def _login_worker(self, u: str, p: str):
        try:
            res = verify_login(u, p)
            self._dispatch_ui(self._on_login_finished, res)
        except Exception as e:
            from auth_manager import AuthResult
            err_res = AuthResult(False, f"Connection error: {e}")
            self._dispatch_ui(self._on_login_finished, err_res)

    def _on_login_finished(self, res):
        self._is_loading = False
        self.submit_btn.configure(state="normal", text="Sign In & Load Profile ⚡", fg_color=T.VIOLET)

        if res.ok:
            self.user_data = res.user_data
            self.status_lbl.configure(text="✓ Authentication Successful! Loading Dashboard...", text_color=T.GOOD)
            if self.remember_var.get():
                from auth_manager import hash_password
                save_remembered(self.user_entry.get().strip(), hash_password(self.pw_entry.get().strip()))
            else:
                clear_remembered()

            # Smoothly transition to the rich analytics dashboard
            self.after(400, lambda: self._render_analytics_dashboard(res.user_data, is_remembered=True))
        else:
            self.status_lbl.configure(text=res.message, text_color=T.BAD)
            self.pw_entry.delete(0, "end")
            self._shake_window()

    def _shake_window(self):
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        for i, dx in enumerate((-8, 8, -6, 6, -3, 3, 0)):
            self.after(i * 40, lambda d=dx: self.root.geometry(f"{W}x{H}+{x + d}+{y}"))

    def _finish_success(self):
        self.success = True
        for child in self.root.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass
        self.root.withdraw()
        self.root.quit()  # returns control to run_login()'s mainloop()


# ══════════════════════════════════════════════════════════
# RUNNER ENTRY POINT
# ══════════════════════════════════════════════════════════
def run_login(root: Optional[ctk.CTk] = None) -> Tuple[bool, Optional[ctk.CTk], Dict[str, Any]]:
    """
    Launches the Login Window and returns:
    (success: bool, root: ctk.CTk | None, user_data: dict)
    """
    win = LoginWindow(root=root)
    win.mainloop()
    if win.success:
        return True, win.get_root(), win.user_data
    try:
        win.destroy()
    except Exception:
        pass
    return False, None, {}


if __name__ == "__main__":
    ok, root, udata = run_login()
    print("Login OK:", ok)
    print("User Data:", udata)
    if root:
        root.destroy()
