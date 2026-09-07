"""
boot_screen.py — Ultra-Modern Cosmic Booting & Splash Screen with Live OTA Hot-Patching
════════════════════════════════════════════════════════════════════════════════════════
Features:
- Glassmorphic glowing mesh gradient UI
- Multi-phase live boot pipeline:
    1. Safe environment and binary paths mount
    2. Over-The-Air (OTA) Cloud Hot-Patch verification & instant module patching
    3. Hardware acceleration & AI Whisper model detection
    4. Smooth handover to Login Window / Studio Main App
"""

import os
import sys
import time
import threading
from typing import Optional, Callable, Dict, Any, Tuple

import customtkinter as ctk
from PIL import Image

import ui_theme as T

W, H = 680, 420

def resource_path(rel: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


class BootScreen(ctk.CTk):
    """
    Sleek cosmic splash screen displaying real-time boot status,
    progress animation, and OTA cloud hot-patch verification.
    """
    def __init__(self, on_complete: Optional[Callable[[ctk.CTk, Dict[str, Any]], None]] = None):
        super().__init__()
        self.on_complete = on_complete
        self.boot_info: Dict[str, Any] = {}
        self._progress_val = 0.0
        self._target_progress = 0.0

        # Window settings
        self.overrideredirect(True)  # Frameless splash look
        self.geometry(f"{W}x{H}")
        self.configure(fg_color=T.INK)
        self._center()

        try:
            self.iconbitmap(resource_path("app_icon.ico"))
        except Exception:
            pass

        # Background mesh gradient
        self._render_background()
        self._build_ui()

        # Start boot sequence in background thread
        threading.Thread(target=self._run_boot_worker, daemon=True).start()
        self._smooth_progress_tick()

    def _center(self):
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - W) // 2
        y = (sh - H) // 2
        self.geometry(f"{W}x{H}+{x}+{y}")

    def _render_background(self):
        try:
            bg_blobs = [
                (0.15, 0.20, 0.55, T.VIOLET, 0.60),
                (0.85, 0.25, 0.50, T.CYAN, 0.40),
                (0.50, 0.90, 0.50, T.PINK, 0.35),
            ]
            bg = T.mesh_gradient(W, H, blobs=bg_blobs, seed_dark=T.INK)
            bg = T.noise_overlay(bg, amount=3)
            self._bg_img = ctk.CTkImage(light_image=bg, dark_image=bg, size=(W, H))
            bg_lbl = ctk.CTkLabel(self, image=self._bg_img, text="")
            bg_lbl.place(x=0, y=0, relwidth=1, relheight=1)
        except Exception:
            pass

    def _build_ui(self):
        # Outer border frame
        border = ctk.CTkFrame(
            self,
            fg_color="transparent",
            corner_radius=16,
            border_width=1.5,
            border_color=T.STROKE_GLOW,
        )
        border.place(x=0, y=0, relwidth=1, relheight=1)

        # Top Glowing Logo
        try:
            orb = T.glow_orb(90, T.VIOLET, 0.95)
            self._orb_img = ctk.CTkImage(light_image=orb, dark_image=orb, size=(90, 90))
            ctk.CTkLabel(border, image=self._orb_img, text="").place(x=W // 2 - 45, y=35)
            ctk.CTkLabel(border, text="⚡", text_color="#ffffff", font=(T.FONT, 28, "bold")).place(x=W // 2 - 13, y=65)
        except Exception:
            pass

        # Title and Subtitle
        try:
            from updater import CURRENT_VERSION
            v_str = f"v{CURRENT_VERSION}"
        except Exception:
            v_str = "v1.0.0"

        ctk.CTkLabel(
            border,
            text="AI EDITOR & STORIES STUDIO",
            text_color=T.TEXT,
            font=(T.FONT, 20, "bold"),
        ).place(x=0, y=140, relwidth=1)

        ctk.CTkLabel(
            border,
            text=f"NEXT-GEN AI PRODUCTION SUITE • {v_str}",
            text_color=T.VIOLET_HI,
            font=(T.FONT, 10, "bold"),
        ).place(x=0, y=170, relwidth=1)

        # Status & Details Box
        self.status_lbl = ctk.CTkLabel(
            border,
            text="Initializing core runtime systems…",
            text_color=T.TEXT_DIM,
            font=(T.FONT, 12),
            justify="center",
        )
        self.status_lbl.place(relx=0.5, y=240, anchor="center")

        # Progress bar
        self.prog_bar = ctk.CTkProgressBar(
            border,
            width=520,
            height=8,
            corner_radius=4,
            fg_color=T.SURFACE_HI,
            progress_color=T.VIOLET,
        )
        self.prog_bar.place(x=(W - 520) // 2, y=285)
        self.prog_bar.set(0.0)

        # Sub-status detail (e.g. OTA / GPU status)
        self.sub_lbl = ctk.CTkLabel(
            border,
            text="Checking local assets…",
            text_color=T.TEXT_FAINT,
            font=(T.FONT, 10),
            justify="center",
        )
        self.sub_lbl.place(relx=0.5, y=305, anchor="center")

        # Footer badge
        foot = ctk.CTkFrame(border, fg_color="transparent")
        foot.place(x=0, y=365, relwidth=1)
        ctk.CTkLabel(
            foot,
            text="● Secure Cloud Authentication • Universal Multi-Engine Pipeline",
            text_color=T.TEXT_FAINT,
            font=(T.FONT, 9),
        ).pack(expand=True)

    def _set_status(self, main_text: str, sub_text: str, target_progress: float):
        self._target_progress = target_progress
        self.after(0, lambda: self._update_labels(main_text, sub_text))

    def _update_labels(self, main_text: str, sub_text: str):
        self.status_lbl.configure(text=main_text)
        self.sub_lbl.configure(text=sub_text)

    def _smooth_progress_tick(self):
        if self._progress_val < self._target_progress:
            self._progress_val = min(self._target_progress, self._progress_val + 0.035)
            self.prog_bar.set(self._progress_val)
        self.after(25, self._smooth_progress_tick)

    def _run_boot_worker(self):
        time.sleep(0.3)

        # Step 1: Environment & Safe paths
        self._set_status("Setting up system environment & binary paths…", "Configuring safe paths & local storage", 0.20)
        try:
            import main
            main.setup_environment()
        except Exception as e:
            print(f"[BOOT] Environment setup notice: {e}")
        time.sleep(0.3)

        # Step 2: Over-The-Air (OTA) Cloud Hot-Patching
        self._set_status("Checking for live Over-The-Air (OTA) patches…", "Connecting to cloud manifest…", 0.45)
        try:
            import ota_patcher
            ota_res = ota_patcher.check_and_apply_cloud_patches(timeout=4)
            if ota_res.get("new_patch_applied"):
                v = ota_res.get("patch_version", "")
                self._set_status(f"⚡ Live Hot-Patch v{v} Applied!", f"Patched modules: {', '.join(ota_res.get('applied_files', []))}", 0.65)
                time.sleep(0.5)
            else:
                self._set_status("OTA Hot-Patches verified & up to date.", "System modules integrity verified", 0.65)
        except Exception as e:
            print(f"[BOOT] OTA check notice: {e}")
            self._set_status("OTA check completed (offline mode)", "Using local cached modules", 0.65)
        time.sleep(0.3)

        # Step 3: Hardware Diagnostics & AI Engines
        self._set_status("Scanning hardware acceleration & AI models…", "Detecting NVIDIA CUDA / DirectML / CPU", 0.85)
        try:
            import hardware_accel
            hw_info = hardware_accel.detect_best_device()
            self.boot_info["hardware"] = hw_info
        except Exception:
            pass
        time.sleep(0.3)

        # Step 4: Finalizing Boot
        self._set_status("System ready. Launching Secure Authentication…", "Opening Login Gateway…", 1.0)
        time.sleep(0.5)

        # Handover
        self.after(200, self._finish_boot)

    def _finish_boot(self):
        for child in self.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass
        self.overrideredirect(False)
        self.withdraw()
        if self.on_complete:
            self.on_complete(self, self.boot_info)


def run_boot_sequence() -> Tuple[ctk.CTk, Dict[str, Any]]:
    """
    Runs the modern boot/splash screen and returns the reusable CTk root
    and collected boot metadata.
    """
    ctk.set_appearance_mode("dark")
    root_holder = {"root": None, "boot_info": {}}

    def on_done(root_win, info):
        root_holder["root"] = root_win
        root_holder["boot_info"] = info
        root_win.quit()

    boot_app = BootScreen(on_complete=on_done)
    boot_app.mainloop()

    return boot_app, root_holder["boot_info"]


if __name__ == "__main__":
    r, binfo = run_boot_sequence()
    print("Boot sequence complete:", binfo)
    r.destroy()
