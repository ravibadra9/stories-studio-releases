"""
music_app.py — 🎶 MUSIC SUITE Entry Point & Studio Navigation Shell
═══════════════════════════════════════════════════════════════════
Modular AI Music & Video Production Suite:
- Song Video Maker (with Video Maker & Audio Splitter)
- Music Tool (Boomerang + YT Transcript + Audio Fetcher)
- Suno Music Studio (Generator, Bulk Generator, Library)
- Suno AI Song Downloader (Local & Web GUI)
- Universal Master Render Queue
- Shared Common Authentication & Admin Management
"""

import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Optional, Dict, Any

import customtkinter as ctk
import lazy_menu
lazy_menu.patch_customtkinter()

try:
    from updater import CURRENT_VERSION as APP_VERSION
except Exception:
    APP_VERSION = "2.8"

TITLE    = "MUSIC SUITE"
SUBTITLE = "AI Music & Video Production Suite"
ICON     = "🎶"
ACCENT   = "#f43f5e"

# Color Palette matching Music Studio Dark UI
C = {
    "bg": "#070a12",
    "card": "#0f1422",
    "card_hi": "#171f34",
    "card_border": "#1e293b",
    "fg": "#f8fafc",
    "dim": "#94a3b8",
    "accent": "#f43f5e",
    "purple": "#8b5cf6",
    "cyan": "#38bdf8",
    "green": "#10b981",
    "yellow": "#f59e0b",
    "red": "#ef4444",
}

from hardware_accel import detect_hardware_acceleration
from plugin_loader import discover_tabs, mount_tabs, StudioScrollableTabview


def get_music_tabs_dir() -> Path:
    _appdata = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or os.path.expanduser("~")
    hot_music_tabs = Path(_appdata) / "StoriesStudio" / "hot_patches" / "music_tabs"
    if hot_music_tabs.is_dir() and any(hot_music_tabs.glob("*.py")):
        return hot_music_tabs

    candidates = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidates.append(Path(meipass) / "music_tabs")
        exe_dir = Path(sys.executable).parent
        candidates.append(exe_dir / "music_tabs")
        candidates.append(exe_dir / "_internal" / "music_tabs")
    candidates.append(Path(__file__).resolve().parent / "music_tabs")
    candidates.append(Path.cwd() / "music_tabs")
    for c in candidates:
        if c.is_dir():
            return c
    return Path(__file__).resolve().parent / "music_tabs"


def create(frame, boot_data=None):
    """Mounts all discovered music tabs into frame."""
    if boot_data is None:
        boot_data = {}

    container = ctk.CTkFrame(frame, fg_color=C["bg"], corner_radius=0)
    container.pack(fill="both", expand=True)
    container.grid_columnconfigure(0, weight=1)
    container.grid_rowconfigure(1, weight=1)

    # ── Header bar ───────────────────────────────────────────
    header = ctk.CTkFrame(container, fg_color=C["card"], height=54, corner_radius=0)
    header.grid(row=0, column=0, sticky="ew")
    header.grid_propagate(False)

    # Left Section: Brand & GPU Info
    left_box = ctk.CTkFrame(header, fg_color="transparent")
    left_box.pack(side="left", padx=14, pady=8)

    ctk.CTkLabel(
        left_box, text="🎶⚡  MUSIC SUITE",
        text_color="#f43f5e", font=("Segoe UI", 16, "bold")
    ).pack(side="left", padx=(0, 10))

    # GPU Detection
    hw_info = detect_hardware_acceleration()
    gpu_badge_txt = f"v{APP_VERSION} • {hw_info.get('encoder_display', 'CPU libx264')}"
    if len(gpu_badge_txt) > 30:
        gpu_badge_txt = gpu_badge_txt[:28] + "…"

    ctk.CTkLabel(
        left_box, text=gpu_badge_txt,
        text_color=C["dim"], font=("Segoe UI", 10)
    ).pack(side="left", padx=(0, 10))

    # User Profile & Analytics Badge in Header (Shared Auth)
    from auth_manager import get_user_profile, get_video_exports_count
    user_prof = boot_data.get("user_data") or get_user_profile()
    u_name = user_prof.get("name") or user_prof.get("user_id") or "Creator"
    u_val = user_prof.get("validity_display") or "✨ Lifetime"
    u_exp = user_prof.get("exports_count", get_video_exports_count(user_prof.get("user_id")))

    def _open_user_profile_modal():
        try:
            from auth_manager import refresh_user_profile
            prof = refresh_user_profile(user_prof.get("user_id"))
            modal = ctk.CTkToplevel(header.winfo_toplevel())
            modal.title("User Profile & Music Studio Analytics")
            modal.geometry("480x420")
            modal.resizable(False, False)
            modal.configure(fg_color="#0b0e18")
            modal.transient(header.winfo_toplevel())
            modal.grab_set()

            modal.update_idletasks()
            mx = header.winfo_toplevel().winfo_x() + (header.winfo_toplevel().winfo_width() - 480) // 2
            my = header.winfo_toplevel().winfo_y() + (header.winfo_toplevel().winfo_height() - 420) // 2
            modal.geometry(f"480x420+{mx}+{my}")

            card = ctk.CTkFrame(modal, fg_color="#121829", corner_radius=16, border_width=1, border_color="#384776")
            card.pack(fill="both", expand=True, padx=16, pady=16)

            top_box = ctk.CTkFrame(card, fg_color="transparent")
            top_box.pack(fill="x", padx=16, pady=(16, 12))

            av = ctk.CTkFrame(top_box, fg_color="#3b0764", width=44, height=44, corner_radius=22, border_width=2, border_color="#f43f5e")
            av.pack(side="left", padx=(0, 10))
            av.pack_propagate(False)
            ctk.CTkLabel(av, text="🎵", font=("Segoe UI", 18)).pack(expand=True)

            u_info = ctk.CTkFrame(top_box, fg_color="transparent")
            u_info.pack(side="left", fill="both", expand=True)
            ctk.CTkLabel(u_info, text=prof.get("name", u_name), font=("Segoe UI", 16, "bold"), text_color="#f8fafc", anchor="w").pack(fill="x")
            ctk.CTkLabel(u_info, text=f"User ID: @{prof.get('user_id', 'creator')}", font=("Segoe UI", 10), text_color="#38bdf8", anchor="w").pack(fill="x")

            met_grid = ctk.CTkFrame(card, fg_color="transparent")
            met_grid.pack(fill="x", padx=16, pady=8)

            # Metric 1: Exports
            c1 = ctk.CTkFrame(met_grid, fg_color="#171f38", corner_radius=10, border_width=1, border_color="#3b82f6")
            c1.pack(fill="x", pady=4)
            r1 = ctk.CTkFrame(c1, fg_color="transparent")
            r1.pack(fill="x", padx=12, pady=8)
            ctk.CTkLabel(r1, text="🎬", font=("Segoe UI", 18)).pack(side="left", padx=(0, 10))
            inf1 = ctk.CTkFrame(r1, fg_color="transparent")
            inf1.pack(side="left", fill="both", expand=True)
            ctk.CTkLabel(inf1, text="TOTAL VIDEOS & SONGS EXPORTED", font=("Segoe UI", 9, "bold"), text_color="#94a3b8", anchor="w").pack(fill="x")
            ctk.CTkLabel(inf1, text=f"{prof.get('exports_count', u_exp)} Projects Rendered", font=("Segoe UI", 13, "bold"), text_color="#38bdf8", anchor="w").pack(fill="x")

            # Metric 2: Validity
            c2 = ctk.CTkFrame(met_grid, fg_color="#171f38", corner_radius=10, border_width=1, border_color=prof.get("badge_color", "#10b981"))
            c2.pack(fill="x", pady=4)
            r2 = ctk.CTkFrame(c2, fg_color="transparent")
            r2.pack(fill="x", padx=12, pady=8)
            ctk.CTkLabel(r2, text="🛡️", font=("Segoe UI", 18)).pack(side="left", padx=(0, 10))
            inf2 = ctk.CTkFrame(r2, fg_color="transparent")
            inf2.pack(side="left", fill="both", expand=True)
            ctk.CTkLabel(inf2, text="LICENSE & VALIDITY", font=("Segoe UI", 9, "bold"), text_color="#94a3b8", anchor="w").pack(fill="x")
            ctk.CTkLabel(inf2, text=prof.get("validity_display", u_val), font=("Segoe UI", 12, "bold"), text_color=prof.get("badge_color", "#10b981"), anchor="w").pack(fill="x")

            # Metric 3: Machine Lock
            c3 = ctk.CTkFrame(met_grid, fg_color="#171f38", corner_radius=10, border_width=1, border_color="#222c4a")
            c3.pack(fill="x", pady=4)
            r3 = ctk.CTkFrame(c3, fg_color="transparent")
            r3.pack(fill="x", padx=12, pady=8)
            ctk.CTkLabel(r3, text="💻", font=("Segoe UI", 16)).pack(side="left", padx=(0, 10))
            inf3 = ctk.CTkFrame(r3, fg_color="transparent")
            inf3.pack(side="left", fill="both", expand=True)
            ctk.CTkLabel(inf3, text="DEVICE HARDWARE LOCK", font=("Segoe UI", 9, "bold"), text_color="#94a3b8", anchor="w").pack(fill="x")
            ctk.CTkLabel(inf3, text=f"Bound ({prof.get('machine_id', '')[:16]}…)", font=("Consolas", 10), text_color="#10b981", anchor="w").pack(fill="x")

            ctk.CTkButton(card, text="Close", width=120, height=32, corner_radius=8, fg_color="#384776", hover_color="#475569", command=modal.destroy).pack(pady=(12, 10))
        except Exception as e:
            print("[PROFILE] Modal error:", e)

    user_chip = ctk.CTkButton(
        left_box,
        text=f"👤 {u_name}  •  {u_val}",
        height=26,
        corner_radius=13,
        fg_color="#141c2e",
        hover_color="#1e293b",
        border_width=1,
        border_color="#334155",
        text_color="#38bdf8",
        font=("Segoe UI", 10, "bold"),
        cursor="hand2",
        command=_open_user_profile_modal
    )
    user_chip.pack(side="left", padx=(4, 6))

    # ── Live Hardware Monitoring Badge (CPU, RAM, GPU) ───────────────────────
    hw_box = ctk.CTkFrame(header, fg_color="#090f1d", corner_radius=8, border_width=1, border_color="#1e293b")
    hw_box.pack(side="left", padx=(10, 4), pady=6)

    lbl_cpu = ctk.CTkLabel(hw_box, text="CPU: --%", font=("Consolas", 10, "bold"), text_color="#00ff8c")
    lbl_cpu.pack(side="left", padx=(8, 4))
    
    ctk.CTkLabel(hw_box, text="|", font=("Consolas", 10), text_color="#334155").pack(side="left")

    lbl_ram = ctk.CTkLabel(hw_box, text="RAM: --GB / --GB", font=("Consolas", 10, "bold"), text_color="#00ff8c")
    lbl_ram.pack(side="left", padx=4)

    ctk.CTkLabel(hw_box, text="|", font=("Consolas", 10), text_color="#334155").pack(side="left")

    lbl_gpu = ctk.CTkLabel(hw_box, text="GPU: Auto", font=("Consolas", 10, "bold"), text_color="#38bdf8")
    lbl_gpu.pack(side="left", padx=(4, 8))

    def _update_hardware_hud():
        try:
            import system_monitor
            stats = system_monitor.get_current_hw_stats()
            
            # CPU
            cpu_pct = stats.get("cpu_pct", 0)
            lbl_cpu.configure(
                text=f"CPU: {cpu_pct}%",
                text_color="#ff4444" if stats.get("is_cpu_high") else "#00ff8c"
            )

            # RAM
            ram_used = stats.get("ram_used_gb", 0.0)
            ram_tot = stats.get("ram_total_gb", 16.0)
            ram_pct = stats.get("ram_pct", 0)
            lbl_ram.configure(
                text=f"RAM: {ram_used}GB/{ram_tot}GB ({ram_pct}%)",
                text_color="#ff4444" if stats.get("is_ram_high") else "#00ff8c"
            )

            # GPU
            gpu_str = stats.get("gpu_name", "GPU")
            temp = stats.get("gpu_temp_c", 0)
            if temp > 0:
                gpu_str += f" ({temp}°C)"
            lbl_gpu.configure(text=f"GPU: {gpu_str}")
        except Exception:
            pass

        try:
            header.after(1200, _update_hardware_hud)
        except Exception:
            pass

    try:
        import system_monitor
        system_monitor.start_hardware_monitor()
        header.after(400, _update_hardware_hud)
    except Exception:
        pass

    # Right Actions
    right_box = ctk.CTkFrame(header, fg_color="transparent")
    right_box.pack(side="right", padx=12, pady=8)

    # Super Admin Shortcut Button (Exclusively for 8949400100)
    from auth_manager import is_current_user_admin
    user_is_super_admin = is_current_user_admin(user_prof)

    def _open_admin():
        try:
            import admin_tool
            admin_tool.launch_gui_admin(header.winfo_toplevel())
        except Exception as e:
            print("[ADMIN] Launch error:", e)

    if user_is_super_admin:
        btn_admin = ctk.CTkButton(
            right_box,
            text="👑 Admin",
            height=28,
            width=85,
            corner_radius=7,
            fg_color="#3b0764",
            hover_color="#581c87",
            border_width=1,
            border_color="#c084fc",
            text_color="#f3e8ff",
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            command=_open_admin
        )
        btn_admin.pack(side="right", padx=4)

    # Reload / Sync Tabs Button
    btn_refresh = ctk.CTkButton(
        right_box,
        text="🔄 Sync",
        height=28,
        width=75,
        corner_radius=7,
        fg_color="#1e293b",
        hover_color="#334155",
        font=("Segoe UI", 10),
        cursor="hand2"
    )
    btn_refresh.pack(side="right", padx=4)

    # ── Discover Music Plugins ───────────────────────────────
    music_tabs_dir = get_music_tabs_dir()
    plugins = discover_tabs(tabs_path=music_tabs_dir)

    if not plugins:
        ctk.CTkLabel(container,
            text="⚠️  music_tabs/ folder khaali hai ya nahi mila.\n\n"
                 "music_tabs/ mein .py files rakh ke app restart karo.",
            text_color=C.get("red", "#fb7185"), font=("Segoe UI", 14),
            justify="center",
        ).grid(row=1, column=0, pady=60)
        return

    # ── Scrollable Studio Tabview ────────────────────────────
    tabview = StudioScrollableTabview(container, fg_color=C["bg"], corner_radius=10)
    tabview.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

    # Mount discovered plugins
    mount_fns = mount_tabs(tabview, plugins, boot_data, theme_colors=C)

    def _reload_plugins():
        nonlocal plugins, tabview
        btn_refresh.configure(state="disabled", text="🔄...")
        try:
            new_plugins = discover_tabs(tabs_path=music_tabs_dir, reload=True)
            try:
                tabview.destroy()
            except Exception:
                pass
            tabview = StudioScrollableTabview(container, fg_color=C["bg"], corner_radius=10)
            tabview.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
            mount_tabs(tabview, new_plugins, boot_data, theme_colors=C)
            btn_refresh.configure(state="normal", text="✓ Synced", fg_color="#10b981")
            container.after(1500, lambda: btn_refresh.configure(text="🔄 Sync", fg_color="#1e293b"))
        except Exception as e:
            print("[RELOAD] Error:", e)
            btn_refresh.configure(state="normal", text="⚠️ Error")

    btn_refresh.configure(command=_reload_plugins)

    # Bind Admin shortcut (Exclusively for 8949400100)
    if user_is_super_admin:
        try:
            header.winfo_toplevel().bind("<Control-Shift-Key-A>", lambda e: _open_admin())
            header.winfo_toplevel().bind("<Control-Shift-Key-a>", lambda e: _open_admin())
        except Exception:
            pass


def launch_app(root: Optional[ctk.CTk] = None, user_data: Optional[Dict[str, Any]] = None):
    """Launches Music Suite inside the reusable Tk root."""
    if root is None:
        ctk.set_appearance_mode("dark")
        root = ctk.CTk()
    else:
        for child in root.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass
        root.deiconify()
        root.resizable(True, True)

    root.title(f"{TITLE} — v{APP_VERSION}")
    root.geometry("1450x850")
    root.minsize(1100, 700)
    root.configure(fg_color=C["bg"])

    try:
        _base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        root.iconbitmap(os.path.join(_base, "app_icon.ico"))
    except Exception:
        pass

    frame = ctk.CTkFrame(root, fg_color=C["bg"])
    frame.pack(fill="both", expand=True)

    boot_data = {
        "api_key": "",
        "user_data": user_data or {},
    }
    root._boot_data = boot_data

    create(frame, boot_data)
    root.mainloop()


if __name__ == "__main__":
    launch_app()
