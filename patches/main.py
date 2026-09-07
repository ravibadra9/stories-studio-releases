#!/usr/bin/env python3
"""
main.py — All-Tools AI Creator Suite / Stories Studio Unified Entry Point

Single-Root Lifecycle Architecture:
    0. Crash logger (captures all uncaught exceptions)
    1. Single-instance Windows Mutex (prevents duplicate instances)
    2. Phase 1: Booting Splash Screen (Live OTA Hot-Patching & Hardware Init)
    3. Phase 2: Login Window (Machine Lock & Firebase User Authentication)
    4. Phase 3: Stories Studio Main Production Suite (16+ Modular Tools)
"""

import crash_logger  # MUST be first import — sets up logging/stdout before anything else runs
import lazy_menu      # MUST patch CustomTkinter before ANY CTk widgets or modules are imported
lazy_menu.patch_customtkinter()

import ctypes
import os
import sys
import traceback
import customtkinter as ctk

MUTEX_NAME = "StoriesStudioMutex"


def setup_environment():
    """Setup safe PATH, sys.path, bundled binaries, and writable data directory."""
    # 0. Root directory must be top priority in sys.path
    root_dir = os.path.dirname(os.path.abspath(__file__))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)

    # 1. Mount OTA Hot-Patch Path
    try:
        import ota_patcher
        ota_patcher.setup_hot_patch_path()
    except Exception as e:
        print(f"[BOOT] OTA initialization notice: {e}")

    # 2. Bundled binary directories to PATH and sys.path
    bundled_paths = [
        getattr(sys, "_MEIPASS", ""),
        os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else "",
        os.path.join(root_dir, "bin"),
        root_dir,
    ]
    cur_path = os.environ.get("PATH", "")
    for p in bundled_paths:
        if p and os.path.isdir(p):
            if p not in cur_path:
                os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
            if p not in sys.path:
                sys.path.append(p)

    # 3. Ensure safe LOCALAPPDATA directories exist
    data_root = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "StoriesStudio")
    for sub in ("temp_work", "output", "whisper_models", "RecapStudio", "StoryImageVideo", "hot_patches"):
        try:
            os.makedirs(os.path.join(data_root, sub), exist_ok=True)
        except Exception:
            pass


def create_mutex():
    """Windows mutex creation for single instance detection."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    except Exception:
        pass


def main():
    setup_environment()
    create_mutex()

    # Phase 1: Booting Splash Screen (Live OTA Check & Fix, Hardware Init)
    import boot_screen
    root, boot_info = boot_screen.run_boot_sequence()

    # Phase 2: Login Window (Credentials & Firebase Authentication)
    import login_window
    ok, root, user_data = login_window.run_login(root=root)
    if not ok or root is None:
        try:
            if root:
                root.destroy()
        except Exception:
            pass
        sys.exit(0)

    # Phase 3: Launch Main Desktop Application (All 19 Functional Tabs)
    try:
        import stories_app
        stories_app.launch_app(root, user_data=user_data)
    except Exception:
        traceback.print_exc()
        try:
            from tkinter import messagebox
            log_path = crash_logger.get_log_path() or ""
            messagebox.showerror(
                "Stories Studio",
                traceback.format_exc()[:1200] +
                (f"\n\nFull log saved at:\n{log_path}" if log_path else "")
            )
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
