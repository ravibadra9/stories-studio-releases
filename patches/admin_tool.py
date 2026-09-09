"""
admin_tool.py — StoriesStudio Pro Admin Control Center & License Management Suite
═════════════════════════════════════════════════════════════════════════════════
Complete Desktop GUI & CLI Admin Dashboard for managing:
- Users (Add, Delete, Block/Unblock, Password Reset)
- Machine Binding / Hardware Lock (View & Unbind HWID)
- License Validity & Expiry Extension Engine (+7d, +30d, +90d, +1y, Lifetime, Custom)
- Real-Time Video Export Analytics & History Tracking
- App Version Updates Broadcast
═════════════════════════════════════════════════════════════════════════════════
"""

import json
import os
import re
import secrets
import string
import sys
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List

import requests

from auth_manager import (
    FIREBASE_URL,
    FIREBASE_SECRET,
    hash_password,
    parse_expiry_info,
    get_machine_id,
)

TIMEOUT = 15

# ══════════════════════════════════════════════════════════
#  FIREBASE REST API HELPERS
# ══════════════════════════════════════════════════════════
def _url(path: str) -> str:
    return f"{FIREBASE_URL}/{path}.json?auth={FIREBASE_SECRET}"


def _get(path: str) -> Any:
    r = requests.get(_url(path), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _patch(path: str, data: Dict[str, Any]) -> Any:
    r = requests.patch(_url(path), data=json.dumps(data), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _delete(path: str) -> Any:
    r = requests.delete(_url(path), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def gen_password(n: int = 12) -> str:
    """Generate friendly, readable password without ambiguous characters."""
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(n))


# ══════════════════════════════════════════════════════════
#  GUI ADMIN DASHBOARD (CustomTkinter + Dark Glassmorphic)
# ══════════════════════════════════════════════════════════
def launch_gui_admin(parent=None, user_data=None):
    from auth_manager import is_current_user_admin
    if not is_current_user_admin(user_data):
        from tkinter import messagebox
        messagebox.showerror(
            "Unauthorized Access",
            "⚠️ Access Denied: Unauthorized.\n\nOnly Master Super Admin (8949400100) has permission to open the Admin Panel."
        )
        return

    import customtkinter as ctk
    from tkinter import messagebox, simpledialog

    ctk.set_appearance_mode("dark")

    # Detect if a root window is already active
    root_exists = (parent is not None)
    if not root_exists:
        try:
            import tkinter
            root_exists = (tkinter._default_root is not None)
        except Exception:
            pass

    base_class = ctk.CTkToplevel if root_exists else ctk.CTk

    THEME = {
        "bg": "#070913",
        "card": "#0f1424",
        "card_hi": "#171f38",
        "card_acc": "#1c2646",
        "border": "#222c4a",
        "border_glow": "#6366f1",
        "text": "#f8fafc",
        "text_dim": "#94a3b8",
        "text_faint": "#64748b",
        "violet": "#8b5cf6",
        "violet_hi": "#a78bfa",
        "cyan": "#06b6d4",
        "cyan_hi": "#38bdf8",
        "emerald": "#10b981",
        "emerald_hi": "#34d399",
        "gold": "#f59e0b",
        "gold_hi": "#fbbf24",
        "rose": "#f43f5e",
        "red": "#ef4444",
    }

    class AdminDashboard(base_class):
        def __init__(self, master=None):
            if base_class == ctk.CTkToplevel:
                master = master or getattr(ctk, "_current_root", None)
                super().__init__(master)
                try:
                    if master:
                        self.transient(master)
                except Exception:
                    pass
            else:
                super().__init__()
            self.title("👑 StoriesStudio — Super Admin Control Center")
            self.geometry("1220x780")
            self.minsize(1100, 680)
            self.configure(fg_color=THEME["bg"])

            self.all_users: Dict[str, Dict[str, Any]] = {}
            self.selected_uid: Optional[str] = None
            self.filter_mode = "all"  # all | active | expired | blocked
            self.search_query = ""

            self.grid_columnconfigure(1, weight=1)
            self.grid_rowconfigure(1, weight=1)

            self._build_header()
            self._build_main_layout()
            self.refresh_data()

        # ──────────────────────────────────────────────────
        # TOP STATS & ACTIONS HEADER
        # ──────────────────────────────────────────────────
        def _build_header(self):
            header = ctk.CTkFrame(self, fg_color=THEME["card"], height=68, corner_radius=0, border_width=1, border_color=THEME["border"])
            header.grid(row=0, column=0, columnspan=2, sticky="ew")
            header.grid_propagate(False)

            # Left Brand Title
            left = ctk.CTkFrame(header, fg_color="transparent")
            left.pack(side="left", padx=16, pady=10)

            title_row = ctk.CTkFrame(left, fg_color="transparent")
            title_row.pack(anchor="w")
            ctk.CTkLabel(title_row, text="👑 STORIES STUDIO", font=("Segoe UI", 16, "bold"), text_color=THEME["violet_hi"]).pack(side="left", padx=(0, 8))
            
            badge = ctk.CTkFrame(title_row, fg_color="#18233c", corner_radius=6, border_width=1, border_color=THEME["cyan"])
            badge.pack(side="left")
            ctk.CTkLabel(badge, text=" MASTER ADMIN ", font=("Segoe UI", 9, "bold"), text_color=THEME["cyan_hi"]).pack(padx=4, pady=1)

            self.server_status_lbl = ctk.CTkLabel(left, text="● Connected to Firebase Live DB", font=("Segoe UI", 10), text_color=THEME["emerald"])
            self.server_status_lbl.pack(anchor="w")

            # Center Live Summary Stats
            self.stats_box = ctk.CTkFrame(header, fg_color="transparent")
            self.stats_box.pack(side="left", padx=30, pady=10)

            self.stat_users_lbl = self._create_stat_pill(self.stats_box, "👥 Users", "0", THEME["violet_hi"])
            self.stat_active_lbl = self._create_stat_pill(self.stats_box, "🟢 Active", "0", THEME["emerald_hi"])
            self.stat_exports_lbl = self._create_stat_pill(self.stats_box, "🎬 Exports", "0", THEME["cyan_hi"])

            # Right Quick Actions
            right = ctk.CTkFrame(header, fg_color="transparent")
            right.pack(side="right", padx=16, pady=10)

            ctk.CTkButton(
                right,
                text="➕ Add User",
                font=("Segoe UI", 11, "bold"),
                fg_color=THEME["emerald"],
                hover_color="#059669",
                text_color="#ffffff",
                height=34,
                width=110,
                corner_radius=8,
                command=self._modal_add_user,
            ).pack(side="left", padx=4)

            ctk.CTkButton(
                right,
                text="📢 Push Update",
                font=("Segoe UI", 11, "bold"),
                fg_color=THEME["card_hi"],
                hover_color=THEME["card_acc"],
                text_color=THEME["gold_hi"],
                height=34,
                width=120,
                corner_radius=8,
                border_width=1,
                border_color=THEME["border"],
                command=self._modal_push_update,
            ).pack(side="left", padx=4)

            self.refresh_btn = ctk.CTkButton(
                right,
                text="🔄 Refresh",
                font=("Segoe UI", 11, "bold"),
                fg_color=THEME["card_hi"],
                hover_color=THEME["card_acc"],
                text_color=THEME["text"],
                height=34,
                width=90,
                corner_radius=8,
                border_width=1,
                border_color=THEME["border"],
                command=self.refresh_data,
            )
            self.refresh_btn.pack(side="left", padx=4)

        def _create_stat_pill(self, parent, label: str, val: str, color: str):
            f = ctk.CTkFrame(parent, fg_color=THEME["card_hi"], corner_radius=8, border_width=1, border_color=THEME["border"], height=38)
            f.pack(side="left", padx=5)
            ctk.CTkLabel(f, text=f"{label}: ", font=("Segoe UI", 10), text_color=THEME["text_dim"]).pack(side="left", padx=(8, 2), pady=6)
            vlbl = ctk.CTkLabel(f, text=val, font=("Segoe UI", 12, "bold"), text_color=color)
            vlbl.pack(side="left", padx=(0, 8), pady=6)
            return vlbl

        # ──────────────────────────────────────────────────
        # MAIN 2-COLUMN LAYOUT
        # ──────────────────────────────────────────────────
        def _build_main_layout(self):
            # ── LEFT PANEL: USERS LIST & FILTERS (Width ~380px) ──
            self.left_panel = ctk.CTkFrame(self, fg_color=THEME["card"], width=390, corner_radius=0, border_width=1, border_color=THEME["border"])
            self.left_panel.grid(row=1, column=0, sticky="nsew")
            self.left_panel.grid_propagate(False)
            self.left_panel.grid_columnconfigure(0, weight=1)
            self.left_panel.grid_rowconfigure(2, weight=1)

            # Search Bar
            search_box = ctk.CTkFrame(self.left_panel, fg_color="transparent")
            search_box.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
            search_box.grid_columnconfigure(0, weight=1)

            self.search_entry = ctk.CTkEntry(
                search_box,
                placeholder_text="🔍 Search user ID or name...",
                font=("Segoe UI", 11),
                fg_color=THEME["card_hi"],
                border_color=THEME["border"],
                height=34,
                corner_radius=8,
            )
            self.search_entry.grid(row=0, column=0, sticky="ew")
            self.search_entry.bind("<KeyRelease>", self._on_search_change)

            # Filter Tab Buttons (All, Active, Expired, Blocked)
            filter_bar = ctk.CTkFrame(self.left_panel, fg_color="transparent")
            filter_bar.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))

            self.filter_btns = {}
            for tag in ("all", "active", "expired", "blocked"):
                b = ctk.CTkButton(
                    filter_bar,
                    text=tag.title(),
                    font=("Segoe UI", 10, "bold"),
                    height=26,
                    fg_color=THEME["violet"] if tag == "all" else THEME["card_hi"],
                    text_color="#ffffff",
                    corner_radius=6,
                    command=lambda t=tag: self._set_filter(t),
                )
                b.pack(side="left", fill="x", expand=True, padx=2)
                self.filter_btns[tag] = b

            # Scrollable User Cards List
            self.user_scroll = ctk.CTkScrollableFrame(self.left_panel, fg_color="transparent")
            self.user_scroll.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 8))
            self.user_scroll.grid_columnconfigure(0, weight=1)

            # ── RIGHT PANEL: COMPLETE USER DETAIL & MANAGEMENT ──
            self.right_panel = ctk.CTkFrame(self, fg_color=THEME["bg"], corner_radius=0)
            self.right_panel.grid(row=1, column=1, sticky="nsew", padx=12, pady=12)
            self.right_panel.grid_columnconfigure(0, weight=1)
            self.right_panel.grid_rowconfigure(0, weight=1)

            # Placeholder view before user selection
            self._render_empty_detail_view()

        def _on_search_change(self, event=None):
            self.search_query = self.search_entry.get().strip().lower()
            self._render_user_list()

        def _set_filter(self, mode: str):
            self.filter_mode = mode
            for t, btn in self.filter_btns.items():
                btn.configure(fg_color=THEME["violet"] if t == mode else THEME["card_hi"])
            self._render_user_list()

        # ──────────────────────────────────────────────────
        # DATA FETCH & RENDER USERS
        # ──────────────────────────────────────────────────
        def refresh_data(self):
            self.refresh_btn.configure(state="disabled", text="⏳ Loading...")
            self.server_status_lbl.configure(text="● Fetching latest data from cloud...", text_color=THEME["cyan"])

            def worker():
                try:
                    users = _get("users") or {}
                    self.all_users = users

                    def on_success():
                        self.refresh_btn.configure(state="normal", text="🔄 Refresh")
                        self.server_status_lbl.configure(text=f"● Cloud Synced ({datetime.now().strftime('%H:%M:%S')})", text_color=THEME["emerald"])
                        self._update_header_stats()
                        self._render_user_list()
                        if self.selected_uid and self.selected_uid in self.all_users:
                            self._render_user_details(self.selected_uid)
                        elif self.all_users:
                            # Auto select first user
                            first_uid = list(self.all_users.keys())[0]
                            self._select_user(first_uid)

                    self.after(0, on_success)
                except Exception as e:
                    def on_err(err=str(e)):
                        self.refresh_btn.configure(state="normal", text="🔄 Refresh")
                        self.server_status_lbl.configure(text=f"⚠️ Sync Error: {err[:35]}", text_color=THEME["red"])
                        messagebox.showerror("Firebase Error", f"Unable to fetch database:\n{err}")

                    self.after(0, on_err)

            threading.Thread(target=worker, daemon=True).start()

        def _update_header_stats(self):
            total = len(self.all_users)
            active = sum(1 for u in self.all_users.values() if u.get("active", True))
            total_exports = sum(int(u.get("exports_count", 0)) for u in self.all_users.values())

            self.stat_users_lbl.configure(text=str(total))
            self.stat_active_lbl.configure(text=str(active))
            self.stat_exports_lbl.configure(text=f"{total_exports:,}")

        def _render_user_list(self):
            for child in self.user_scroll.winfo_children():
                try: child.destroy()
                except Exception: pass

            filtered = []
            for uid, data in self.all_users.items():
                # Search filter
                name = str(data.get("name") or "").lower()
                if self.search_query and (self.search_query not in uid.lower() and self.search_query not in name):
                    continue

                # Category filter
                is_active = data.get("active", True)
                exp_info = parse_expiry_info(data.get("expires_on"))
                is_expired = exp_info.get("is_expired", False)

                if self.filter_mode == "active" and (not is_active or is_expired):
                    continue
                if self.filter_mode == "expired" and not is_expired:
                    continue
                if self.filter_mode == "blocked" and is_active:
                    continue

                filtered.append((uid, data, exp_info))

            if not filtered:
                ctk.CTkLabel(self.user_scroll, text="No users found.", font=("Segoe UI", 11), text_color=THEME["text_dim"]).pack(pady=40)
                return

            for uid, data, exp_info in filtered:
                is_selected = (uid == self.selected_uid)
                card_bg = THEME["card_acc"] if is_selected else THEME["card_hi"]
                border_col = THEME["violet"] if is_selected else THEME["border"]

                card = ctk.CTkFrame(self.user_scroll, fg_color=card_bg, corner_radius=10, border_width=1, border_color=border_col)
                card.pack(fill="x", pady=3, padx=2)
                card.bind("<Button-1>", lambda e, u=uid: self._select_user(u))

                inner = ctk.CTkFrame(card, fg_color="transparent")
                inner.pack(fill="x", padx=10, pady=8)
                inner.bind("<Button-1>", lambda e, u=uid: self._select_user(u))

                # Top Row: Avatar + User ID + Status Dot
                top_r = ctk.CTkFrame(inner, fg_color="transparent")
                top_r.pack(fill="x")
                top_r.bind("<Button-1>", lambda e, u=uid: self._select_user(u))

                status_dot = "🟢" if data.get("active", True) else "🔴"
                ctk.CTkLabel(top_r, text=status_dot, font=("Segoe UI", 10)).pack(side="left", padx=(0, 4))
                
                u_lbl = ctk.CTkLabel(top_r, text=uid, font=("Segoe UI", 12, "bold"), text_color=THEME["text"])
                u_lbl.pack(side="left")
                u_lbl.bind("<Button-1>", lambda e, u=uid: self._select_user(u))

                exp_cnt = data.get("exports_count", 0)
                ctk.CTkLabel(top_r, text=f"🎬 {exp_cnt}", font=("Segoe UI", 10, "bold"), text_color=THEME["cyan_hi"]).pack(side="right")

                # Bottom Row: Display Name & Validity Pill
                bot_r = ctk.CTkFrame(inner, fg_color="transparent")
                bot_r.pack(fill="x", pady=(2, 0))
                bot_r.bind("<Button-1>", lambda e, u=uid: self._select_user(u))

                dname = data.get("name") or uid.title()
                ctk.CTkLabel(bot_r, text=dname[:18], font=("Segoe UI", 10), text_color=THEME["text_dim"]).pack(side="left")

                val_short = exp_info.get("validity_display", "✨ Lifetime")
                if len(val_short) > 22:
                    val_short = val_short[:20] + "…"
                v_lbl = ctk.CTkLabel(bot_r, text=val_short, font=("Segoe UI", 9, "bold"), text_color=exp_info.get("badge_color", THEME["emerald"]))
                v_lbl.pack(side="right")

                # Sub Row: PC Name & IP if available
                pc_name = data.get("pc_name") or ""
                ip_addr = data.get("ip_address") or ""
                loc_txt = data.get("ip_location") or ""
                if pc_name or (ip_addr and ip_addr != "Unknown"):
                    sub_r = ctk.CTkFrame(inner, fg_color="transparent")
                    sub_r.pack(fill="x", pady=(2, 0))
                    sub_r.bind("<Button-1>", lambda e, u=uid: self._select_user(u))

                    dev_txt = f"💻 {pc_name[:12]}" if pc_name else ""
                    ip_display_short = f"🌐 {ip_addr}" + (f" ({loc_txt[:10]})" if loc_txt else "") if ip_addr and ip_addr != "Unknown" else ""
                    comb = f"{dev_txt}  •  {ip_display_short}" if dev_txt and ip_display_short else (dev_txt or ip_display_short)
                    ctk.CTkLabel(sub_r, text=comb, font=("Consolas", 8), text_color=THEME["text_faint"]).pack(side="left")

        def _select_user(self, uid: str):
            self.selected_uid = uid
            self._render_user_list()
            self._render_user_details(uid)

        def _render_empty_detail_view(self):
            for child in self.right_panel.winfo_children():
                try: child.destroy()
                except Exception: pass
            box = ctk.CTkFrame(self.right_panel, fg_color=THEME["card"], corner_radius=16, border_width=1, border_color=THEME["border"])
            box.pack(fill="both", expand=True)
            ctk.CTkLabel(box, text="👈 Select a user from the left list to view complete details & manage license.", font=("Segoe UI", 13), text_color=THEME["text_dim"]).pack(expand=True)

        # ──────────────────────────────────────────────────
        # COMPLETE USER DETAILS & MANAGEMENT SUITE
        # ──────────────────────────────────────────────────
        def _render_user_details(self, uid: str):
            for child in self.right_panel.winfo_children():
                try: child.destroy()
                except Exception: pass

            u = self.all_users.get(uid)
            if not u:
                self._render_empty_detail_view()
                return

            exp_info = parse_expiry_info(u.get("expires_on"))
            is_active = u.get("active", True)
            mid = u.get("machine_id", "")
            exports_count = int(u.get("exports_count", 0))
            last_login = u.get("last_login", "")

            # Main scrollable card
            detail_scroll = ctk.CTkScrollableFrame(self.right_panel, fg_color=THEME["card"], corner_radius=16, border_width=1, border_color=THEME["border"])
            detail_scroll.pack(fill="both", expand=True)
            detail_scroll.grid_columnconfigure(0, weight=1)

            # ── SECTION 1: HEADER & PROFILE SUMMARY ──
            hdr = ctk.CTkFrame(detail_scroll, fg_color=THEME["card_hi"], corner_radius=12, border_width=1, border_color=THEME["border"])
            hdr.pack(fill="x", padx=16, pady=16)

            h_row = ctk.CTkFrame(hdr, fg_color="transparent")
            h_row.pack(fill="x", padx=16, pady=14)

            # Avatar
            av = ctk.CTkFrame(h_row, fg_color="#1e1b4b", width=54, height=54, corner_radius=27, border_width=2, border_color=THEME["violet"])
            av.pack(side="left", padx=(0, 14))
            av.pack_propagate(False)
            ctk.CTkLabel(av, text="👤", font=("Segoe UI", 22)).pack(expand=True)

            # Name & ID
            u_info = ctk.CTkFrame(h_row, fg_color="transparent")
            u_info.pack(side="left", fill="both", expand=True)

            name_title = u.get("name") or uid.title()
            ctk.CTkLabel(u_info, text=name_title, font=("Segoe UI", 18, "bold"), text_color=THEME["text"], anchor="w").pack(fill="x")
            
            tag_line = ctk.CTkFrame(u_info, fg_color="transparent")
            tag_line.pack(fill="x", pady=(2, 0))
            ctk.CTkLabel(tag_line, text=f"@{uid}", font=("Segoe UI", 11, "bold"), text_color=THEME["cyan_hi"]).pack(side="left", padx=(0, 10))
            
            status_text = "🟢 ACTIVE ACCOUNT" if is_active else "🔴 BLOCKED ACCOUNT"
            status_col = THEME["emerald_hi"] if is_active else THEME["red"]
            ctk.CTkLabel(tag_line, text=status_text, font=("Segoe UI", 10, "bold"), text_color=status_col).pack(side="left")

            # Quick Status Toggle & Delete Actions
            act_box = ctk.CTkFrame(h_row, fg_color="transparent")
            act_box.pack(side="right")

            toggle_btn_text = "🚫 Block User" if is_active else "✅ Unblock User"
            toggle_btn_col = THEME["rose"] if is_active else THEME["emerald"]
            ctk.CTkButton(
                act_box,
                text=toggle_btn_text,
                font=("Segoe UI", 10, "bold"),
                fg_color=toggle_btn_col,
                hover_color="#991b1b" if is_active else "#059669",
                height=30,
                width=110,
                corner_radius=8,
                command=lambda: self._toggle_user_status(uid),
            ).pack(side="left", padx=4)

            ctk.CTkButton(
                act_box,
                text="🗑️ Delete",
                font=("Segoe UI", 10, "bold"),
                fg_color=THEME["card_acc"],
                hover_color="#7f1d1d",
                text_color=THEME["rose"],
                height=30,
                width=80,
                corner_radius=8,
                command=lambda: self._delete_user_action(uid),
            ).pack(side="left", padx=4)

            # ── SECTION 2: 3 LIVE METRIC CARDS ──
            m_row = ctk.CTkFrame(detail_scroll, fg_color="transparent")
            m_row.pack(fill="x", padx=16, pady=(0, 12))
            m_row.grid_columnconfigure((0, 1, 2), weight=1, uniform="m")

            # Metric 1: Total Videos Exported
            c_exp = ctk.CTkFrame(m_row, fg_color=THEME["card_hi"], corner_radius=12, border_width=1, border_color="#3b82f6")
            c_exp.grid(row=0, column=0, sticky="nsew", padx=4)
            c1_in = ctk.CTkFrame(c_exp, fg_color="transparent")
            c1_in.pack(fill="x", padx=12, pady=10)
            ctk.CTkLabel(c1_in, text="🎬 TOTAL EXPORTS", font=("Segoe UI", 9, "bold"), text_color=THEME["text_dim"], anchor="w").pack(fill="x")
            ctk.CTkLabel(c1_in, text=f"{exports_count} Videos", font=("Segoe UI", 18, "bold"), text_color=THEME["cyan_hi"], anchor="w").pack(fill="x")
            ctk.CTkButton(c1_in, text="✏️ Edit Counter", font=("Segoe UI", 9), height=22, fg_color=THEME["card_acc"], text_color=THEME["text_dim"], command=lambda: self._modal_set_exports(uid)).pack(anchor="w", pady=(4, 0))

            # Metric 2: License Validity
            c_val = ctk.CTkFrame(m_row, fg_color=THEME["card_hi"], corner_radius=12, border_width=1, border_color=exp_info.get("badge_color", THEME["emerald"]))
            c_val.grid(row=0, column=1, sticky="nsew", padx=4)
            c2_in = ctk.CTkFrame(c_val, fg_color="transparent")
            c2_in.pack(fill="x", padx=12, pady=10)
            ctk.CTkLabel(c2_in, text="🛡️ LICENSE VALIDITY", font=("Segoe UI", 9, "bold"), text_color=THEME["text_dim"], anchor="w").pack(fill="x")
            ctk.CTkLabel(c2_in, text=exp_info.get("validity_display", "✨ Lifetime"), font=("Segoe UI", 13, "bold"), text_color=exp_info.get("badge_color", THEME["emerald"]), anchor="w").pack(fill="x")
            ctk.CTkLabel(c2_in, text=f"Expires: {exp_info.get('formatted_date', 'Lifetime')}", font=("Segoe UI", 9), text_color=THEME["text_faint"], anchor="w").pack(fill="x")

            # Metric 3: Machine / Hardware Bound
            c_hw = ctk.CTkFrame(m_row, fg_color=THEME["card_hi"], corner_radius=12, border_width=1, border_color=THEME["border"])
            c_hw.grid(row=0, column=2, sticky="nsew", padx=4)
            c3_in = ctk.CTkFrame(c_hw, fg_color="transparent")
            c3_in.pack(fill="x", padx=12, pady=10)
            ctk.CTkLabel(c3_in, text="💻 DEVICE LOCK", font=("Segoe UI", 9, "bold"), text_color=THEME["text_dim"], anchor="w").pack(fill="x")
            hw_status_str = "Bound to PC" if mid else "Free / Unbound"
            hw_status_col = THEME["emerald_hi"] if mid else THEME["gold_hi"]
            ctk.CTkLabel(c3_in, text=hw_status_str, font=("Segoe UI", 13, "bold"), text_color=hw_status_col, anchor="w").pack(fill="x")
            if mid:
                ctk.CTkButton(c3_in, text="🔓 Unbind / Free PC", font=("Segoe UI", 9), height=22, fg_color=THEME["card_acc"], text_color=THEME["rose"], command=lambda: self._unbind_machine_action(uid)).pack(anchor="w", pady=(4, 0))

            # ── SECTION 3: ⭐️ EXPIRY DATE EXTENSION ENGINE (HIGHLIGHT FEATURE) ──
            ext_card = ctk.CTkFrame(detail_scroll, fg_color=THEME["card_hi"], corner_radius=14, border_width=1, border_color=THEME["border_glow"])
            ext_card.pack(fill="x", padx=16, pady=8)

            ext_hdr = ctk.CTkFrame(ext_card, fg_color="transparent")
            ext_hdr.pack(fill="x", padx=16, pady=(14, 8))
            ctk.CTkLabel(ext_hdr, text="⚡ License Expiry Extension & Validity Manager", font=("Segoe UI", 13, "bold"), text_color=THEME["gold_hi"]).pack(side="left")
            ctk.CTkLabel(ext_hdr, text=f"Current Expiry: {exp_info.get('formatted_date', 'Lifetime')}", font=("Segoe UI", 11, "bold"), text_color=exp_info.get("badge_color", THEME["emerald"])).pack(side="right")

            # Quick Preset Buttons
            preset_bar = ctk.CTkFrame(ext_card, fg_color="transparent")
            preset_bar.pack(fill="x", padx=16, pady=(0, 10))

            presets = [
                ("➕ 7 Days", 7),
                ("➕ 30 Days (1 Mo)", 30),
                ("➕ 90 Days (3 Mo)", 90),
                ("➕ 180 Days (6 Mo)", 180),
                ("➕ 1 Year (365d)", 365),
                ("✨ Lifetime", 0),
            ]
            for plbl, pdays in presets:
                ctk.CTkButton(
                    preset_bar,
                    text=plbl,
                    font=("Segoe UI", 10, "bold"),
                    height=30,
                    fg_color=THEME["card_acc"],
                    hover_color=THEME["violet"],
                    text_color=THEME["text"],
                    corner_radius=8,
                    command=lambda d=pdays: self._apply_quick_extension(uid, d),
                ).pack(side="left", fill="x", expand=True, padx=3)

            # Custom Date Extension Row
            custom_row = ctk.CTkFrame(ext_card, fg_color="transparent")
            custom_row.pack(fill="x", padx=16, pady=(0, 14))

            ctk.CTkLabel(custom_row, text="Custom Date (YYYY-MM-DD) or Days:", font=("Segoe UI", 11), text_color=THEME["text_dim"]).pack(side="left", padx=(0, 8))
            self.custom_exp_entry = ctk.CTkEntry(custom_row, placeholder_text="e.g. 2026-12-31 or 45", font=("Segoe UI", 11), width=180, height=32, corner_radius=8)
            self.custom_exp_entry.pack(side="left", padx=(0, 8))

            ctk.CTkButton(
                custom_row,
                text="⚡ Apply Custom Expiry",
                font=("Segoe UI", 11, "bold"),
                fg_color=THEME["violet"],
                hover_color=THEME["violet_hi"],
                text_color="#ffffff",
                height=32,
                corner_radius=8,
                command=lambda: self._apply_custom_expiry(uid),
            ).pack(side="left")

            # ── SECTION 4: 💻 PC HARDWARE, NETWORK & LOCATION DETAILS ──
            sec_card = ctk.CTkFrame(detail_scroll, fg_color=THEME["card_hi"], corner_radius=12, border_width=1, border_color=THEME["border"])
            sec_card.pack(fill="x", padx=16, pady=8)

            sec_in = ctk.CTkFrame(sec_card, fg_color="transparent")
            sec_in.pack(fill="x", padx=16, pady=12)

            sec_top = ctk.CTkFrame(sec_in, fg_color="transparent")
            sec_top.pack(fill="x", pady=(0, 8))
            ctk.CTkLabel(sec_top, text="💻 PC Hardware, IP Network & Location", font=("Segoe UI", 12, "bold"), text_color=THEME["cyan_hi"], anchor="w").pack(side="left")

            ctk.CTkButton(
                sec_top,
                text="🔑 Reset Password",
                font=("Segoe UI", 10, "bold"),
                fg_color=THEME["card_acc"],
                hover_color=THEME["violet"],
                text_color=THEME["violet_hi"],
                height=26,
                corner_radius=8,
                command=lambda: self._modal_reset_password(uid),
            ).pack(side="right")

            info_grid = ctk.CTkFrame(sec_in, fg_color="transparent")
            info_grid.pack(fill="x")
            info_grid.grid_columnconfigure((0, 1), weight=1)

            pc_val = u.get("pc_name") or "— Not Logged In Yet —"
            os_u_val = u.get("os_user") or "—"
            ip_val = u.get("ip_address") or "—"
            loc_val = u.get("ip_location") or ""
            local_ip_val = u.get("local_ip") or ""
            ip_display = f"{ip_val}  ({loc_val})" if loc_val and ip_val != "—" else ip_val

            # Left column
            ctk.CTkLabel(info_grid, text=f"• 💻 PC Hostname:  {pc_val}", font=("Segoe UI", 10, "bold"), text_color=THEME["text"], anchor="w").grid(row=0, column=0, sticky="w", pady=3)
            ctk.CTkLabel(info_grid, text=f"• 👤 OS Username:  {os_u_val}", font=("Segoe UI", 10), text_color=THEME["text_dim"], anchor="w").grid(row=1, column=0, sticky="w", pady=3)
            ctk.CTkLabel(info_grid, text=f"• 🛡️ Machine HWID: {mid or '— None (Free PC) —'}", font=("Consolas", 10), text_color=THEME["text_dim"], anchor="w").grid(row=2, column=0, sticky="w", pady=3)

            # Right column
            ctk.CTkLabel(info_grid, text=f"• 🌐 Public IP:    {ip_display}", font=("Segoe UI", 10, "bold"), text_color=THEME["emerald_hi"] if ip_val != "—" else THEME["text_dim"], anchor="w").grid(row=0, column=1, sticky="w", pady=3)
            ctk.CTkLabel(info_grid, text=f"• 🔌 Local IP:     {local_ip_val or '—'}", font=("Segoe UI", 10), text_color=THEME["text_dim"], anchor="w").grid(row=1, column=1, sticky="w", pady=3)
            ctk.CTkLabel(info_grid, text=f"• 🕒 Last Login:   {last_login[:19].replace('T', ' ') if last_login else '— Never —'}", font=("Segoe UI", 10), text_color=THEME["text_dim"], anchor="w").grid(row=2, column=1, sticky="w", pady=3)


        # ──────────────────────────────────────────────────
        # ACTION HANDLERS (EXPIRY, HWID, PASSWORDS)
        # ──────────────────────────────────────────────────
        def _apply_quick_extension(self, uid: str, days: int):
            if days == 0:
                new_exp = ""
                msg = "✨ Lifetime Access applied!"
            else:
                # If current expiry is in future, extend from existing expiry date
                cur_exp = self.all_users[uid].get("expires_on")
                base_dt = datetime.utcnow()
                if cur_exp:
                    try:
                        exp_dt = datetime.fromisoformat(cur_exp.replace("Z", "+00:00")).replace(tzinfo=None)
                        if exp_dt > base_dt:
                            base_dt = exp_dt
                    except Exception:
                        pass
                new_dt = base_dt + timedelta(days=days)
                new_exp = new_dt.isoformat()
                msg = f"Extended by {days} days! New Expiry: {new_dt.strftime('%d %b %Y')}"

            _patch(f"users/{uid}", {"expires_on": new_exp})
            self.all_users[uid]["expires_on"] = new_exp
            self._render_user_details(uid)
            self._render_user_list()
            messagebox.showinfo("License Updated", f"User @{uid} license updated successfully:\n\n{msg}")

        def _apply_custom_expiry(self, uid: str):
            val = self.custom_exp_entry.get().strip()
            if not val or val.lower() in ("0", "lifetime", "none"):
                new_exp = ""
                msg = "✨ Lifetime Access applied!"
            elif val.isdigit():
                d = int(val)
                new_dt = datetime.utcnow() + timedelta(days=d)
                new_exp = new_dt.isoformat()
                msg = f"Set to {d} days from today (Exp: {new_dt.strftime('%d %b %Y')})"
            else:
                try:
                    new_dt = datetime.strptime(val[:10], "%Y-%m-%d")
                    new_exp = new_dt.isoformat()
                    msg = f"Set to specific date: {new_dt.strftime('%d %b %Y')}"
                except Exception:
                    messagebox.showerror("Invalid Date", "Please enter a valid format:\n- Number of days (e.g. 45)\n- Specific date: YYYY-MM-DD (e.g. 2026-12-31)\n- '0' or 'lifetime'")
                    return

            _patch(f"users/{uid}", {"expires_on": new_exp})
            self.all_users[uid]["expires_on"] = new_exp
            self._render_user_details(uid)
            self._render_user_list()
            messagebox.showinfo("License Updated", f"User @{uid} custom license updated:\n\n{msg}")

        def _toggle_user_status(self, uid: str):
            cur = self.all_users[uid].get("active", True)
            new_val = not cur
            _patch(f"users/{uid}", {"active": new_val})
            self.all_users[uid]["active"] = new_val
            self._update_header_stats()
            self._render_user_details(uid)
            self._render_user_list()
            messagebox.showinfo("Status Updated", f"User @{uid} is now {'ACTIVE 🟢' if new_val else 'BLOCKED 🔴'}")

        def _unbind_machine_action(self, uid: str):
            if not messagebox.askyesno("Unbind Machine", f"Unbind hardware lock for @{uid}?\n\nThey will be able to bind to a new PC on their next login."):
                return
            _patch(f"users/{uid}", {"machine_id": ""})
            self.all_users[uid]["machine_id"] = ""
            self._render_user_details(uid)
            self._render_user_list()
            messagebox.showinfo("Hardware Lock Released", f"Machine ID unbound for @{uid} ✓")

        def _delete_user_action(self, uid: str):
            if not messagebox.askyesno("Confirm Delete", f"⚠️ Permanently delete user @{uid}?\n\nThis cannot be undone."):
                return
            _delete(f"users/{uid}")
            if uid in self.all_users:
                del self.all_users[uid]
            self.selected_uid = None
            self._update_header_stats()
            self._render_user_list()
            self._render_empty_detail_view()
            messagebox.showinfo("Deleted", f"User @{uid} deleted successfully.")

        def _modal_set_exports(self, uid: str):
            cur = self.all_users[uid].get("exports_count", 0)
            res = simpledialog.askstring("Set Exports Count", f"Enter new exports count for @{uid}:", initialvalue=str(cur), parent=self)
            if res is not None and res.isdigit():
                new_cnt = int(res)
                _patch(f"users/{uid}", {"exports_count": new_cnt})
                self.all_users[uid]["exports_count"] = new_cnt
                self._update_header_stats()
                self._render_user_details(uid)
                self._render_user_list()
                messagebox.showinfo("Exports Updated", f"@{uid} exports count set to {new_cnt} ✓")

        def _modal_reset_password(self, uid: str):
            new_pw = gen_password()
            res = simpledialog.askstring("Reset Password", f"Enter new password for @{uid} (or use generated):", initialvalue=new_pw, parent=self)
            if res and res.strip():
                final_pw = res.strip()
                _patch(f"users/{uid}", {"password_hash": hash_password(final_pw)})
                messagebox.showinfo("Password Reset", f"✅ Password updated for @{uid}!\n\nUser ID  : {uid}\nPassword : {final_pw}\n\nSend these credentials to the user.")

        # ──────────────────────────────────────────────────
        # MODAL: ADD NEW USER
        # ──────────────────────────────────────────────────
        def _modal_add_user(self):
            modal = ctk.CTkToplevel(self)
            modal.title("Add New User")
            modal.geometry("450x460")
            modal.resizable(False, False)
            modal.configure(fg_color=THEME["bg"])
            modal.transient(self)
            modal.grab_set()

            # Center modal
            modal.update_idletasks()
            mx = self.winfo_x() + (self.winfo_width() - 450) // 2
            my = self.winfo_y() + (self.winfo_height() - 460) // 2
            modal.geometry(f"450x460+{mx}+{my}")

            card = ctk.CTkFrame(modal, fg_color=THEME["card"], corner_radius=16, border_width=1, border_color=THEME["border"])
            card.pack(fill="both", expand=True, padx=16, pady=16)

            ctk.CTkLabel(card, text="➕ Create New User", font=("Segoe UI", 16, "bold"), text_color=THEME["emerald_hi"]).pack(pady=(16, 12))

            # User ID
            ctk.CTkLabel(card, text="User ID / Username:", font=("Segoe UI", 11, "bold"), text_color=THEME["text_dim"], anchor="w").pack(fill="x", padx=20)
            u_entry = ctk.CTkEntry(card, placeholder_text="e.g. ravi_pro", font=("Segoe UI", 11), height=34, corner_radius=8)
            u_entry.pack(fill="x", padx=20, pady=(2, 10))

            # Display Name
            ctk.CTkLabel(card, text="Full / Display Name:", font=("Segoe UI", 11, "bold"), text_color=THEME["text_dim"], anchor="w").pack(fill="x", padx=20)
            name_entry = ctk.CTkEntry(card, placeholder_text="e.g. Ravi Badra", font=("Segoe UI", 11), height=34, corner_radius=8)
            name_entry.pack(fill="x", padx=20, pady=(2, 10))

            # Password
            ctk.CTkLabel(card, text="Password (Auto-Generated):", font=("Segoe UI", 11, "bold"), text_color=THEME["text_dim"], anchor="w").pack(fill="x", padx=20)
            pw_entry = ctk.CTkEntry(card, font=("Segoe UI", 11), height=34, corner_radius=8)
            pw_entry.insert(0, gen_password())
            pw_entry.pack(fill="x", padx=20, pady=(2, 10))

            # Expiry
            ctk.CTkLabel(card, text="Validity / Expiry Days (Enter '0' or blank for Lifetime):", font=("Segoe UI", 11, "bold"), text_color=THEME["text_dim"], anchor="w").pack(fill="x", padx=20)
            exp_entry = ctk.CTkEntry(card, placeholder_text="e.g. 30 (or blank for Lifetime)", font=("Segoe UI", 11), height=34, corner_radius=8)
            exp_entry.pack(fill="x", padx=20, pady=(2, 16))

            def _submit_create():
                uid = u_entry.get().strip().lower()
                dname = name_entry.get().strip() or uid.title()
                pwd = pw_entry.get().strip()
                days_str = exp_entry.get().strip()

                if not uid or not pwd:
                    messagebox.showwarning("Required", "User ID and Password are required.")
                    return

                if uid in self.all_users or _get(f"users/{uid}"):
                    messagebox.showerror("User Exists", f"User @{uid} already exists.")
                    return

                expires = ""
                if days_str.isdigit() and int(days_str) > 0:
                    expires = (datetime.utcnow() + timedelta(days=int(days_str))).isoformat()

                payload = {
                    "name": dname,
                    "password_hash": hash_password(pwd),
                    "machine_id": "",
                    "active": True,
                    "expires_on": expires,
                    "exports_count": 0,
                    "created_on": datetime.utcnow().isoformat(),
                }
                _patch(f"users/{uid}", payload)
                self.all_users[uid] = payload
                self.selected_uid = uid

                modal.destroy()
                self._update_header_stats()
                self._render_user_list()
                self._render_user_details(uid)

                val_str = f"{days_str} Days" if expires else "✨ Lifetime Access"
                messagebox.showinfo("User Created!", f"✅ User Created Successfully!\n\nUser ID  : {uid}\nPassword : {pwd}\nName     : {dname}\nValidity : {val_str}\n\nSend these credentials to the user.")

            ctk.CTkButton(
                card,
                text="⚡ Create User Account",
                font=("Segoe UI", 12, "bold"),
                fg_color=THEME["emerald"],
                hover_color="#059669",
                height=38,
                corner_radius=8,
                command=_submit_create,
            ).pack(fill="x", padx=20, pady=4)

        # ──────────────────────────────────────────────────
        # MODAL: PUSH UPDATE BROADCAST
        # ──────────────────────────────────────────────────
        def _modal_push_update(self):
            modal = ctk.CTkToplevel(self)
            modal.title("Push Software Update")
            modal.geometry("480x420")
            modal.resizable(False, False)
            modal.configure(fg_color=THEME["bg"])
            modal.transient(self)
            modal.grab_set()

            # Center modal
            modal.update_idletasks()
            mx = self.winfo_x() + (self.winfo_width() - 480) // 2
            my = self.winfo_y() + (self.winfo_height() - 420) // 2
            modal.geometry(f"480x420+{mx}+{my}")

            card = ctk.CTkFrame(modal, fg_color=THEME["card"], corner_radius=16, border_width=1, border_color=THEME["border"])
            card.pack(fill="both", expand=True, padx=16, pady=16)

            ctk.CTkLabel(card, text="📢 Broadcast Software Update", font=("Segoe UI", 15, "bold"), text_color=THEME["gold_hi"]).pack(pady=(16, 12))

            app_data = _get("app") or {}
            cur_ver = app_data.get("latest_version", "63.0.0")

            ctk.CTkLabel(card, text=f"New Version (Current: {cur_ver}):", font=("Segoe UI", 11, "bold"), text_color=THEME["text_dim"], anchor="w").pack(fill="x", padx=20)
            ver_entry = ctk.CTkEntry(card, placeholder_text="e.g. 64.0.0", font=("Segoe UI", 11), height=34, corner_radius=8)
            ver_entry.insert(0, cur_ver)
            ver_entry.pack(fill="x", padx=20, pady=(2, 10))

            ctk.CTkLabel(card, text="GitHub Installer Download URL:", font=("Segoe UI", 11, "bold"), text_color=THEME["text_dim"], anchor="w").pack(fill="x", padx=20)
            url_entry = ctk.CTkEntry(card, placeholder_text="https://github.com/.../Setup.exe", font=("Segoe UI", 11), height=34, corner_radius=8)
            url_entry.insert(0, app_data.get("download_url", ""))
            url_entry.pack(fill="x", padx=20, pady=(2, 10))

            ctk.CTkLabel(card, text="Release Notes / Changelog:", font=("Segoe UI", 11, "bold"), text_color=THEME["text_dim"], anchor="w").pack(fill="x", padx=20)
            notes_box = ctk.CTkTextbox(card, font=("Segoe UI", 10), height=70, corner_radius=8, fg_color=THEME["card_hi"])
            notes_box.insert("1.0", app_data.get("release_notes", "- Performance enhancements\n- Voice updates\n- Bug fixes"))
            notes_box.pack(fill="x", padx=20, pady=(2, 14))

            def _submit_update():
                n_ver = ver_entry.get().strip()
                n_url = url_entry.get().strip()
                n_notes = notes_box.get("1.0", "end").strip()

                if not n_ver:
                    messagebox.showwarning("Version Required", "Please enter version number.")
                    return

                _patch("app", {
                    "latest_version": n_ver,
                    "download_url": n_url,
                    "release_notes": n_notes,
                })
                modal.destroy()
                messagebox.showinfo("Update Pushed", f"✅ Update v{n_ver} is now LIVE!\nAll users will see the update on app startup.")

            ctk.CTkButton(
                card,
                text="🚀 Push Update to All Users",
                font=("Segoe UI", 12, "bold"),
                fg_color=THEME["gold"],
                hover_color="#d97706",
                height=38,
                corner_radius=8,
                command=_submit_update,
            ).pack(fill="x", padx=20)

    app = AdminDashboard(master=parent)
    if base_class == ctk.CTk:
        app.mainloop()
    else:
        app.deiconify()
        app.lift()
        app.focus_force()
    return app


# ══════════════════════════════════════════════════════════
#  CLI INTERACTIVE MODE
# ══════════════════════════════════════════════════════════
def run_cli_admin():
    def list_users_cli():
        users = _get("users") or {}
        if not users:
            print("\n  Koi user nahi mila.\n")
            return
        print(f"\n  {'USER ID':<12} {'STATUS':<8} {'EXPORTS':<8} {'VALIDITY':<16} {'PC NAME':<16} {'IP / LOCATION':<22} {'LAST LOGIN'}")
        print("  " + "─" * 102)
        for uid, u in users.items():
            status = "ACTIVE" if u.get("active", True) else "BLOCKED"
            exports = str(u.get("exports_count", 0))
            exp_info = parse_expiry_info(u.get("expires_on"))
            val_str = exp_info.get("validity_display", "✨ Lifetime")[:15]
            pc_name = (u.get("pc_name") or "—")[:15]
            ip_val = u.get("ip_address") or "—"
            loc_val = u.get("ip_location") or ""
            ip_str = (f"{ip_val} ({loc_val})" if loc_val and ip_val != "—" else ip_val)[:21]
            last = (u.get("last_login") or "—")[:16].replace("T", " ")
            print(f"  {uid:<12} {status:<8} {exports:<8} {val_str:<16} {pc_name:<16} {ip_str:<22} {last}")
        print()


    def add_user_cli():
        uid = input("\n  Naya User ID (e.g. amit): ").strip().lower()
        if not uid: return
        if _get(f"users/{uid}"):
            print(f"  ⚠️ '{uid}' pehle se maujood hai.")
            return
        pwd = input("  Password (Enter = auto-generate): ").strip() or gen_password()
        dname = input("  Display / Full Name (Enter = default): ").strip() or uid.title()
        days = input("  Kitne din valid? (Enter = Lifetime): ").strip()
        expires = (datetime.utcnow() + timedelta(days=int(days))).isoformat() if days.isdigit() and int(days) > 0 else ""
        _patch(f"users/{uid}", {
            "name": dname, "password_hash": hash_password(pwd), "machine_id": "",
            "active": True, "expires_on": expires, "exports_count": 0,
            "created_on": datetime.utcnow().isoformat(),
        })
        print(f"\n  ✅ User @{uid} ban gaya!\n  Password: {pwd}\n  Validity: {days+' Days' if expires else 'Lifetime'}\n")

    def extend_expiry_cli():
        uid = input("\n  Kis user ki expiry extend karni hai? ").strip().lower()
        u = _get(f"users/{uid}")
        if not u: print("  ⚠️ User nahi mila."); return
        exp_info = parse_expiry_info(u.get("expires_on"))
        print(f"  Abhi validity: {exp_info.get('validity_display')} (Expires: {exp_info.get('formatted_date')})")
        print("  Presets: 1) +7d  2) +30d  3) +90d  4) +365d  5) Lifetime  6) Custom Days")
        ch = input("  Chuno (1-6): ").strip()
        days_map = {"1": 7, "2": 30, "3": 90, "4": 365, "5": 0}
        if ch in days_map:
            d = days_map[ch]
        elif ch == "6":
            d_str = input("  Kitne din aur? ").strip()
            d = int(d_str) if d_str.isdigit() else 0
        else:
            return
        if d == 0:
            new_exp = ""
            msg = "✨ Lifetime Access"
        else:
            cur_exp = u.get("expires_on")
            base = datetime.utcnow()
            if cur_exp:
                try:
                    exp_dt = datetime.fromisoformat(cur_exp.replace("Z", "+00:00")).replace(tzinfo=None)
                    if exp_dt > base: base = exp_dt
                except Exception: pass
            new_dt = base + timedelta(days=d)
            new_exp = new_dt.isoformat()
            msg = f"Extended until {new_dt.strftime('%d %b %Y')} (+{d} days)"
        _patch(f"users/{uid}", {"expires_on": new_exp})
        print(f"\n  ✅ @{uid} validity update ho gayi: {msg}\n")

    def unbind_pc_cli():
        uid = input("\n  Kis user ki machine free karni hai? ").strip().lower()
        _patch(f"users/{uid}", {"machine_id": ""})
        print(f"\n  ✅ @{uid} ki machine free ho gayi (Agli login pe nayi PC bind hogi).\n")

    def reset_pw_cli():
        uid = input("\n  Kis user ka password badalna hai? ").strip().lower()
        pwd = input("  Naya password (Enter = auto): ").strip() or gen_password()
        _patch(f"users/{uid}", {"password_hash": hash_password(pwd)})
        print(f"\n  ✅ Password update ho gaya: {uid} -> {pwd}\n")

    def toggle_block_cli():
        uid = input("\n  Kis user ko block/unblock karna hai? ").strip().lower()
        u = _get(f"users/{uid}")
        if not u: print("  ⚠️ User nahi mila."); return
        new_val = not u.get("active", True)
        _patch(f"users/{uid}", {"active": new_val})
        print(f"\n  ✅ @{uid} ab {'ACTIVE 🟢' if new_val else 'BLOCKED 🔴'} hai.\n")

    def delete_user_cli():
        uid = input("\n  Kis user ko DELETE karna hai? ").strip().lower()
        if input(f"  Pakka '{uid}' delete karna hai? (yes/no): ").strip() == "yes":
            _delete(f"users/{uid}")
            print(f"  ✅ @{uid} delete ho gaya.\n")

    def set_exports_cli():
        uid = input("\n  Kis user ke exports count badalne hain? ").strip().lower()
        cnt = input("  Naya export count: ").strip()
        if cnt.isdigit():
            _patch(f"users/{uid}", {"exports_count": int(cnt)})
            print(f"\n  ✅ @{uid} exports count {cnt} ho gaya.\n")

    MENU_TEXT = """
╔══════════════════════════════════════════════╗
║       STORIES STUDIO — ADMIN CONSOLE         ║
╚══════════════════════════════════════════════╝
  1) Users Dekho (Analytics & Validity)
  2) Naya User Banao
  3) Password Reset Karo
  4) Machine ID Free Karo (Unbind PC)
  5) User Block / Unblock
  6) User Expiry Date Extend Karo ⚡
  7) Video Exports Counter Set Karo
  8) User Delete Karo
  0) Exit
"""
    ACTIONS_CLI = {
        "1": list_users_cli, "2": add_user_cli, "3": reset_pw_cli,
        "4": unbind_pc_cli, "5": toggle_block_cli, "6": extend_expiry_cli,
        "7": set_exports_cli, "8": delete_user_cli,
    }

    while True:
        print(MENU_TEXT)
        choice = input("  Chuno (0-8): ").strip()
        if choice == "0": break
        fn = ACTIONS_CLI.get(choice)
        if fn:
            try: fn()
            except Exception as e: print(f"  ❌ Error: {e}")
        else:
            print("  ⚠️ Galat option.")


if __name__ == "__main__":
    if "--cli" in sys.argv:
        run_cli_admin()
    else:
        launch_gui_admin()

