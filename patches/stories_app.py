"""
stories_app.py — AI Editor Entry Point (MODULAR / Plugin-Based)
═══════════════════════════════════════════════════════════════════
Ab tabs hardcoded nahi hain.
tabs/ folder mein .py daalo → automatic tab ban jayega.

Purana behavior 100% same hai:
  - Boot screen with progress
  - API key validation
  - Voice/model fetch
  - Whisper check
  - GPU detect
  - Theme system
  - Resolution picker

Bas tab creation dynamic ho gayi hai.
"""

# ════════════════════════════════════════════════════════════════
# TAB METADATA (launcher ke liye — same as before)
# ════════════════════════════════════════════════════════════════
try:
    from updater import CURRENT_VERSION as APP_VERSION
except Exception:
    APP_VERSION = "dev"

TITLE    = "AI Editor"
SUBTITLE = "Modular AI Video Production Suite"
ICON     = "🎬"
ACCENT   = "#bc8cff"

# ════════════════════════════════════════════════════════════════
# IMPORTS
# ════════════════════════════════════════════════════════════════
import os
import sys
import threading
import time
import traceback

import customtkinter as ctk
import requests
import lazy_menu
lazy_menu.patch_customtkinter()
from lazy_menu import LazyDropdownMenu

# stories_engine se saari cheezein import — C dict, GPU, voice_cache, etc.
from stories_engine import (
    C, GPU, _OUTPUT_PRESETS, _OUTPUT_RES_CHOICE, _set_output_res,
    _open_theme_picker, _safe_std_streams, SettingsManager,
)
import voice_cache

from plugin_loader import discover_tabs, mount_tabs, StudioScrollableTabview


# ════════════════════════════════════════════════════════════════
# CREATE — plugin-based tab mounting
# ════════════════════════════════════════════════════════════════
def create(frame, boot_data=None):
    """
    Plugin-based create:
    1. Header bar banao (same as before — version, GPU, theme, resolution)
    2. tabs/ folder scan karo (discover_tabs)
    3. Mount all discovered plugins as tabs
    """
    if boot_data is None:
        boot_data = {}

    container = ctk.CTkFrame(frame, fg_color=C["bg"], corner_radius=0)
    container.pack(fill="both", expand=True)
    container.grid_columnconfigure(0, weight=1)
    container.grid_rowconfigure(1, weight=1)

    # ── Header bar ───────────────────────────────────────────
    header = ctk.CTkFrame(container, fg_color=C["card"], height=52, corner_radius=0)
    header.grid(row=0, column=0, sticky="ew")
    header.grid_propagate(False)

    # Left Section: Brand & GPU Info
    left_box = ctk.CTkFrame(header, fg_color="transparent")
    left_box.pack(side="left", padx=12, pady=8)

    ctk.CTkLabel(left_box, text="🎬🎵  AI EDITOR",
        text_color=C["purple"], font=("Segoe UI", 16, "bold")
    ).pack(side="left", padx=(0, 8))

    gpu_short = GPU.info_str()
    if len(gpu_short) > 28:
        gpu_short = gpu_short[:25] + "…"
    ctk.CTkLabel(left_box, text=f"v{APP_VERSION} • {gpu_short}",
        text_color=C["dim"], font=("Segoe UI", 10)
    ).pack(side="left", padx=(0, 10))

    # User Profile & Analytics Badge in Header
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
            modal.title("User Profile & Studio Analytics")
            modal.geometry("480x420")
            modal.resizable(False, False)
            modal.configure(fg_color="#0b0e18")
            modal.transient(header.winfo_toplevel())
            modal.grab_set()

            # Center modal
            modal.update_idletasks()
            mx = header.winfo_toplevel().winfo_x() + (header.winfo_toplevel().winfo_width() - 480) // 2
            my = header.winfo_toplevel().winfo_y() + (header.winfo_toplevel().winfo_height() - 420) // 2
            modal.geometry(f"480x420+{mx}+{my}")

            card = ctk.CTkFrame(modal, fg_color="#121829", corner_radius=16, border_width=1, border_color="#384776")
            card.pack(fill="both", expand=True, padx=16, pady=16)

            # Avatar & Title
            top_box = ctk.CTkFrame(card, fg_color="transparent")
            top_box.pack(fill="x", padx=16, pady=(16, 12))

            av = ctk.CTkFrame(top_box, fg_color="#1e1b4b", width=44, height=44, corner_radius=22, border_width=2, border_color="#8b5cf6")
            av.pack(side="left", padx=(0, 10))
            av.pack_propagate(False)
            ctk.CTkLabel(av, text="👤", font=("Segoe UI", 18)).pack(expand=True)

            u_info = ctk.CTkFrame(top_box, fg_color="transparent")
            u_info.pack(side="left", fill="both", expand=True)
            ctk.CTkLabel(u_info, text=prof.get("name", u_name), font=("Segoe UI", 16, "bold"), text_color="#f8fafc", anchor="w").pack(fill="x")
            ctk.CTkLabel(u_info, text=f"User ID: @{prof.get('user_id', 'creator')}", font=("Segoe UI", 10), text_color="#38bdf8", anchor="w").pack(fill="x")

            # Metrics
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
            ctk.CTkLabel(inf1, text="TOTAL VIDEOS EXPORTED", font=("Segoe UI", 9, "bold"), text_color="#94a3b8", anchor="w").pack(fill="x")
            ctk.CTkLabel(inf1, text=f"{prof.get('exports_count', u_exp)} Videos Rendered", font=("Segoe UI", 13, "bold"), text_color="#38bdf8", anchor="w").pack(fill="x")

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

            # Close button
            ctk.CTkButton(card, text="Close", width=120, height=32, corner_radius=8, fg_color="#384776", hover_color="#475569", command=modal.destroy).pack(pady=(12, 10))
        except Exception as e:
            print("[PROFILE] Modal error:", e)

    user_chip = ctk.CTkButton(
        left_box,
        text=f"👤 {u_name} • {u_val[:18]} • 🎬 {u_exp} Videos",
        height=28,
        fg_color="#162038",
        hover_color="#223055",
        text_color="#e2e8f0",
        border_width=1,
        border_color="#3b82f6",
        font=("Segoe UI", 10, "bold"),
        corner_radius=14,
        command=_open_user_profile_modal
    )
    user_chip.pack(side="left", padx=2)

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

    import system_monitor
    system_monitor.start_hardware_monitor()
    header.after(400, _update_hardware_hud)

    # Right Section: Controls & Update Button
    right_box = ctk.CTkFrame(header, fg_color="transparent")
    right_box.pack(side="right", padx=10, pady=8)

    # 🚀 Update Check button
    _latest_update_info = [None]


    def _on_update_click():
        if _latest_update_info[0]:
            try:
                from updater import UpdateWindow
                UpdateWindow(header.winfo_toplevel(), _latest_update_info[0])
            except Exception as e:
                print("[UPDATE] Failed to open update window:", e)
        else:
            _trigger_update_check(manual=True)

    btn_update = ctk.CTkButton(right_box, text="🚀 Check Update", width=130, height=32,
        fg_color="#059669", hover_color="#047857",
        border_width=1, border_color="#34d399",
        text_color="#ffffff", text_color_disabled="#e2e8f0",
        font=("Segoe UI", 11, "bold"),
        corner_radius=8, cursor="hand2",
        command=_on_update_click
    )
    btn_update.pack(side="right", padx=(4, 0))

    # 🔄 Refresh Plugins (Hot Reload) button
    btn_refresh = ctk.CTkButton(right_box, text="🔄 Refresh", width=100, height=32,
        fg_color="#2563eb", hover_color="#1d4ed8",
        border_width=1, border_color="#60a5fa",
        text_color="#ffffff", font=("Segoe UI", 11, "bold"),
        corner_radius=8, cursor="hand2",
        command=lambda: _reload_plugins()
    )
    btn_refresh.pack(side="right", padx=(4, 4))

    # Theme button
    ctk.CTkButton(right_box, text="🎨 Theme", width=80, height=32,
        fg_color="#1e293b", hover_color="#334155",
        border_width=1, border_color="#475569",
        text_color="#f8fafc", font=("Segoe UI", 11, "bold"),
        corner_radius=8, cursor="hand2",
        command=lambda: _open_theme_picker(header)
    ).pack(side="right", padx=(4, 4))

    # Output resolution picker
    _res_var = ctk.StringVar(value=_OUTPUT_RES_CHOICE)
    ctk.CTkOptionMenu(right_box, variable=_res_var,
        values=list(_OUTPUT_PRESETS.keys()),
        width=120, height=32, fg_color="#1e293b", button_color="#334155", button_hover_color="#475569",
        font=("Segoe UI", 10, "bold"),
        corner_radius=8,
        command=lambda v: _set_output_res(v)
    ).pack(side="right", padx=(4, 4))

    ctk.CTkLabel(right_box, text="Output:", text_color=C["dim"],
        font=("Segoe UI", 11, "bold")).pack(side="right", padx=(6, 2))

    def _trigger_update_check(manual=False):
        try:
            if manual and btn_update.winfo_exists():
                btn_update.configure(state="disabled", text="⏳ Checking...", fg_color="#047857")
        except Exception:
            pass

        def _worker():
            try:
                from updater import check_for_update, UpdateWindow, CURRENT_VERSION
                info = check_for_update()
                if info:
                    _latest_update_info[0] = info
                    def _show_upd():
                        try:
                            if btn_update.winfo_exists():
                                btn_update.configure(state="normal", text=f"🔥 Update v{info['version']}", fg_color="#ef4444", hover_color="#dc2626")
                            if manual:
                                try:
                                    UpdateWindow(header.winfo_toplevel(), info)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    try: header.after(0, _show_upd)
                    except Exception: pass
                else:
                    def _show_ok():
                        try:
                            if btn_update.winfo_exists():
                                btn_update.configure(state="normal", text="🚀 Check Update", fg_color="#10b981", hover_color="#059669")
                            if manual:
                                from tkinter import messagebox
                                messagebox.showinfo("Software Update", f"You are running the latest version (v{CURRENT_VERSION}).")
                        except Exception:
                            pass
                    try: header.after(0, _show_ok)
                    except Exception: pass
            except Exception as e:
                def _show_err():
                    try:
                        if btn_update.winfo_exists():
                            btn_update.configure(state="normal", text="🚀 Check Update", fg_color="#10b981", hover_color="#059669")
                        if manual:
                            from tkinter import messagebox
                            messagebox.showerror("Update Check Failed", f"Unable to check for updates:\n{e}")
                    except Exception:
                        pass
                try: header.after(0, _show_err)
                except Exception: pass

        threading.Thread(target=_worker, daemon=True).start()

    # Background initial check
    _trigger_update_check(manual=False)

    # ── Discover plugins ─────────────────────────────────────
    plugins = discover_tabs()

    if not plugins:
        ctk.CTkLabel(container,
            text="⚠️  tabs/ folder khaali hai ya nahi mila.\n\n"
                 "tabs/ mein .py files rakh ke app restart karo.",
            text_color=C.get("red", "#fb7185"), font=("Segoe UI", 14),
            justify="center",
        ).grid(row=1, column=0, pady=60)
        return

    # ── Scrollable Studio Tabview ────────────────────────────
    tabview = StudioScrollableTabview(container, fg_color=C["bg"], corner_radius=10)
    tabview.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

    # ── Mount all plugins ────────────────────────────────────
    mount_fns = mount_tabs(tabview, plugins, boot_data, theme_colors=C)
    _orig_mount = mount_fns.copy()

    def _reload_plugins():
        nonlocal plugins, mount_fns, _orig_mount, tabview
        btn_refresh.configure(state="disabled", text="🔄 Syncing...")
        try:
            cur_tab = tabview.get()
        except Exception:
            cur_tab = None

        def _do_reload():
            # 1. Check for cloud hot patches
            try:
                import ota_patcher
                patch_res = ota_patcher.check_and_apply_cloud_patches()
                if patch_res.get("new_patch_applied"):
                    print(f"[HOT-RELOAD] ⚡ New patch applied: {patch_res['message']}")
            except Exception as pe:
                print(f"[HOT-RELOAD] OTA check notice: {pe}")

            # 2. Rediscover & reload all tab modules dynamically
            try:
                new_plugins = discover_tabs(reload=True)
                def _ui_swap():
                    nonlocal plugins, mount_fns, _orig_mount, tabview
                    try:
                        tabview.destroy()
                    except Exception:
                        pass

                    tabview = StudioScrollableTabview(container, fg_color=C["bg"], corner_radius=10)
                    tabview.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

                    plugins = new_plugins
                    mount_fns = mount_tabs(tabview, plugins, boot_data, theme_colors=C)
                    _orig_mount = mount_fns.copy()

                    tabview.configure(command=_on_tab_change)

                    if cur_tab:
                        try: tabview.set(cur_tab)
                        except Exception: pass

                    btn_refresh.configure(state="normal", text="⚡ Live Patched!", fg_color="#10b981")
                    container.after(2000, lambda: btn_refresh.configure(text="🔄 Refresh", fg_color="#3b82f6"))
                    print(f"[HOT-RELOAD] ✓ {len(plugins)} tabs reloaded successfully!")
                container.after(0, _ui_swap)
            except Exception as e:
                traceback.print_exc()
                def _ui_err():
                    btn_refresh.configure(state="normal", text="⚠️ Fail", fg_color="#ef4444")
                    container.after(2000, lambda: btn_refresh.configure(text="🔄 Refresh", fg_color="#3b82f6"))
                container.after(0, _ui_err)

        threading.Thread(target=_do_reload, daemon=True).start()

    # Background OTA Hot-Patch check on startup
    def _bg_ota_check():
        try:
            import ota_patcher
            res = ota_patcher.check_and_apply_cloud_patches()
            if res.get("new_patch_applied"):
                print(f"[OTA-BOOT] ⚡ Background patch applied: {res['message']}")

            # Check for broadcast announcements / notifications
            broadcast = ota_patcher.get_pending_broadcast()
            if broadcast:
                def _show_broadcast():
                    try:
                        b_id = broadcast.get("id") or broadcast.get("title", "")
                        b_title = broadcast.get("title", "Announcement")
                        b_msg = broadcast.get("message", "")
                        from tkinter import messagebox
                        messagebox.showinfo(b_title, b_msg)
                        ota_patcher.mark_broadcast_seen(b_id)
                    except Exception:
                        pass
                container.after(1500, _show_broadcast)
        except Exception:
            pass
    threading.Thread(target=_bg_ota_check, daemon=True).start()

    try:
        top = container.winfo_toplevel()
        top.bind("<F5>", lambda e: _reload_plugins())
        top.bind("<Control-r>", lambda e: _reload_plugins())
    except Exception:
        pass

    def _on_tab_change():
        try:
            cur = tabview.get()
            fn = _orig_mount.get(cur)
            if fn:
                fn()
            # ── Auto refresh voices UI on tab map if not loaded yet ──
            tab_frame = tabview.tab(cur)
            def _refresh_active_tab():
                try:
                    for child in tab_frame.winfo_children():
                        if hasattr(child, "_auto_load_voices_on_init") and not getattr(child, "_voices_loaded_once", False):
                            child._auto_load_voices_on_init()
                except Exception:
                    pass
            container.after(60, _refresh_active_tab)
        except Exception:
            pass

    tabview.configure(command=_on_tab_change)

    # ── Restore Last Saved Session Active Tab ────────────────
    try:
        import system_monitor
        last_saved_tab = system_monitor.load_session_state().get("active_tab")
        if last_saved_tab and last_saved_tab in tabview._tabs:
            container.after(100, lambda: tabview.set(last_saved_tab))
    except Exception:
        pass

    print(f"=== AI EDITOR — {len(plugins)} tabs mounted ===")


# ════════════════════════════════════════════════════════════════
# LAUNCH_APP — boot screen + tab mount (from original stories_1_final.py)
# ════════════════════════════════════════════════════════════════
def launch_app(root=None, user_data=None):
    """Root window banao (ya existing reuse karo), boot screen dikhao, phir tab UI mount karo.

    SINGLE-ROOT FIX: same as before — login window ka root reuse."""
    ctk.set_appearance_mode("dark")

    if root is None:
        root = ctk.CTk()
    else:
        for child in root.winfo_children():
            try: child.destroy()
            except Exception: pass
        root.deiconify()
        root.resizable(True, True)

    try:
        from updater import CURRENT_VERSION
        ver = CURRENT_VERSION
    except Exception:
        ver = "dev"

    root.title(f"{TITLE} — v{ver}")
    root.geometry("1450x800")
    root.minsize(1200, 680)
    root.configure(fg_color=C["bg"])

    # App icon
    try:
        _base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        root.iconbitmap(os.path.join(_base, "app_icon.ico"))
    except Exception:
        pass

    # ═══════════════════════════════════════════════════
    # INSTANT LAUNCH (Boot Screen Bypassed for 0ms Load)
    # ═══════════════════════════════════════════════════
    api_key = voice_cache.load_api_key() or ""

    frame = ctk.CTkFrame(root, fg_color=C["bg"])
    frame.pack(fill="both", expand=True)

    boot_data = {
        "api_key": api_key,
        "models": [],
        "voices": [],
        "whisper_ok": True,
        "user_data": user_data,
    }
    root._boot_data = boot_data

    # Directly render studio UI in 0 milliseconds
    create(frame, boot_data)
    try:
        root.attributes("-alpha", 1.0)
    except Exception:
        pass

    # ── Background OTA, Cloud Patches & Update Notification ──
    def _bg_ota_and_updates_worker():
        # 1. Check for OTA Hot-Patches
        try:
            import ota_patcher
            res = ota_patcher.check_and_apply_cloud_patches()
            if res.get("new_patch_applied"):
                msg = res.get("message") or "Cloud patch applied successfully."
                def _show_patch_popup():
                    try:
                        from tkinter import messagebox
                        messagebox.showinfo(
                            "⚡ Live Cloud Patch Applied",
                            f"A new hot-patch has been applied over-the-air!\n\n{msg}\n\nAll tools are running with the latest updates."
                        )
                    except Exception:
                        pass
                root.after(1000, _show_patch_popup)
        except Exception as pe:
            print(f"[OTA] Background check notice: {pe}")

        # 2. Check for App Version Updates
        try:
            from updater import check_for_update, UpdateWindow
            upd_info = check_for_update()
            if upd_info:
                def _show_upd_popup():
                    try:
                        UpdateWindow(root, upd_info)
                    except Exception:
                        pass
                root.after(1500, _show_upd_popup)
        except Exception as ue:
            print(f"[UPDATE] Background update check notice: {ue}")

        # 3. Background pre-fetch of models and voices (non-blocking)
        try:
            voice_cache.load_voices_cached(api_key=api_key, force_refresh=False)
        except Exception:
            pass

    threading.Thread(target=_bg_ota_and_updates_worker, daemon=True).start()
    root.mainloop()


if __name__ == "__main__":
    launch_app()
