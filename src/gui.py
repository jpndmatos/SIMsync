"""
SIMsync GUI — local desktop app to sync event CSVs to Brella.
"""

import ctypes
import datetime
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog
from pathlib import Path

# Import api early so it runs load_env_file (which handles exe path resolution),
# populating os.environ before the Setup tab reads values via load_env_value.
import api as _api  # noqa: F401

# --- Paths ---
def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent  # src/ -> project root

BASE_DIR = get_base_dir()
ENV_PATH = BASE_DIR / ".env"

# --- Theme ---
BG = "#101016"
SURFACE = "#19191f"
SURFACE_RAISED = "#222229"
TEXT = "#f0f0f5"
TEXT_SEC = "#8e8e9a"
TEXT_TER = "#55555f"
ACCENT = "#e6007e"
ACCENT_LIGHT = "#ff3da5"
SUCCESS = "#2dd4a8"
DANGER = "#f85149"
WARN = "#f0a030"
FONT = ("Poppins", 10)
FONT_BOLD = ("Poppins", 10, "bold")
FONT_SMALL = ("Poppins", 9)
FONT_MONO = ("Poppins", 9)
FONT_TITLE = ("Poppins", 14, "bold")
FONT_SECTION = ("Poppins", 9, "bold")

CARD_PAD_X = 8
CARD_PAD_INNER = 8
CARD_PAD_Y_TOP = 5
CARD_PAD_Y_BOT = 5

SIDEBAR_W = 250
SIDEBAR_WIDTH_RATIO = 0.35

APP_VERSION = "v1.0"

# --- Animation constants ---
ANIM_INTERVAL = 16
NAV_ANIM_STEPS = 10
BUTTON_FLASH_MS = 120
PULSE_INTERVAL = 40
PULSE_STEPS = 30
LOG_FADE_STEPS = 8
LOG_FADE_INTERVAL = 30
INDICATOR_ANIM_STEPS = 8
GAP = 6
ACTION_ROW_PAD_Y = 2
ACTION_BTN_PADX = 12
ACTION_BTN_PADY = 2
ACTION_BTN_GAP = 5


# --- Color interpolation helpers ---

def _hex_to_rgb(hex_color):
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

def _rgb_to_hex(r, g, b):
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"

def _lerp_color(color_a, color_b, t):
    t = max(0.0, min(1.0, t))
    ra, ga, ba = _hex_to_rgb(color_a)
    rb, gb, bb = _hex_to_rgb(color_b)
    return _rgb_to_hex(
        ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t,
    )


# --- .env helpers ---

def load_env_value(key, default=""):
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    return os.environ.get(key, default)

def save_env_values(updates):
    lines = []
    existing_keys = set()
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k = stripped.split("=", 1)[0].strip()
                if k in updates:
                    lines.append(f"{k}={updates[k]}")
                    existing_keys.add(k)
                    continue
            lines.append(line)
    for k, v in updates.items():
        if k not in existing_keys:
            lines.append(f"{k}={v}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- Scrollable list helper ---

def _make_scroll_list(parent, bg=None):
    """Create a vertically scrollable frame inside parent. Returns (canvas, frame)."""
    if bg is None:
        bg = SURFACE
    canvas = tk.Canvas(parent, bg=bg, highlightthickness=0, borderwidth=0)
    frame = tk.Frame(canvas, bg=bg)
    frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    win = canvas.create_window((0, 0), window=frame, anchor="nw")
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
    canvas.pack(fill="both", expand=True)
    frame.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>",
        lambda ev: canvas.yview_scroll(int(-1 * (ev.delta / 120)), "units")))
    frame.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
    return canvas, frame


# --- Card helpers ---

def make_card(parent):
    card = tk.Frame(parent, bg=SURFACE, highlightbackground=SURFACE_RAISED, highlightthickness=1)
    card.pack(fill="x", padx=CARD_PAD_X, pady=(0, GAP))
    return card

def card_title(card, text):
    tk.Label(card, text=text, font=FONT_SECTION, fg=ACCENT, bg=SURFACE,
             anchor="w").pack(fill="x", padx=CARD_PAD_INNER, pady=(CARD_PAD_Y_TOP, 4))

def make_field(parent, label, var, show=None, placeholder=""):
    parent_bg = parent.cget("bg") if hasattr(parent, "cget") else SURFACE
    tk.Label(parent, text=label, font=FONT_SMALL, fg=TEXT_SEC, bg=parent_bg,
             anchor="w").pack(fill="x")
    kw = dict(textvariable=var, font=FONT_MONO, bg=BG, fg=TEXT, insertbackground=TEXT,
              relief="flat", highlightthickness=1, highlightbackground=SURFACE_RAISED,
              highlightcolor=ACCENT)
    if show:
        kw["show"] = show
    entry = tk.Entry(parent, **kw)
    entry.pack(fill="x", ipady=4, pady=(1, 5))
    return entry


# --- Scrollable frame wrapper ---

class ScrollableFrame:
    def __init__(self, parent):
        self.canvas = tk.Canvas(parent, bg=BG, highlightthickness=0, borderwidth=0)
        self.frame = tk.Frame(self.canvas, bg=BG)
        self.frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.frame, anchor="nw")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.frame.bind("<Enter>", self._bind_mousewheel)
        self.frame.bind("<Leave>", self._unbind_mousewheel)

    def _on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)
    def _bind_mousewheel(self, event):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
    def _unbind_mousewheel(self, event):
        self.canvas.unbind_all("<MouseWheel>")
    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


# --- Button press flash helper ---

def _bind_button_flash(btn, rest_color, flash_color):
    def on_press(e):
        btn.config(bg=flash_color)
        btn.after(BUTTON_FLASH_MS, lambda: btn.config(bg=rest_color))
    btn.bind("<ButtonPress-1>", on_press, add="+")


# --- Status dot pulse animation ---

class StatusPulse:
    def __init__(self, widget):
        self.widget = widget
        self._running = False
        self._step = 0
        self._forward = True
        self._color_a = ACCENT_LIGHT
        self._color_b = TEXT_TER
        self._after_id = None

    def start(self, color_a=ACCENT_LIGHT, color_b=None):
        if self._running:
            return
        self._color_a = color_a
        self._color_b = color_b or _lerp_color(color_a, BG, 0.6)
        self._running = True
        self._step = 0
        self._forward = True
        self._tick()

    def stop(self, final_color=None):
        self._running = False
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if final_color:
            try:
                self.widget.config(bg=final_color)
            except Exception:
                pass

    def _tick(self):
        if not self._running:
            return
        t = self._step / PULSE_STEPS
        color = _lerp_color(self._color_a, self._color_b, t)
        try:
            self.widget.config(bg=color)
        except Exception:
            self._running = False
            return
        if self._forward:
            self._step += 1
            if self._step >= PULSE_STEPS:
                self._forward = False
        else:
            self._step -= 1
            if self._step <= 0:
                self._forward = True
        self._after_id = self.widget.after(PULSE_INTERVAL, self._tick)


# --- Setup Tab (merged: API config + Values) ---

class SetupTab:
    def __init__(self, parent, log_callback=None, app=None):
        self.log_callback = log_callback
        self._app = app
        self.action_row = None
        self.frame = tk.Frame(parent, bg=BG)

        P = 4  # grid gap

        # Single-column flat layout: Connection (top) -> Groups & Tickets (bottom)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=0)
        self.frame.rowconfigure(1, weight=0)
        self.frame.rowconfigure(2, weight=1)

        self.api_key = tk.StringVar(value=load_env_value("BRELLA_API_KEY"))
        self.org_id = tk.StringVar(value=load_env_value("BRELLA_ORG_ID"))
        self.event_id = tk.StringVar(value=load_env_value("BRELLA_EVENT_ID"))
        self.admin_token = tk.StringVar(value=load_env_value("BRELLA_ADMIN_ACCESS_TOKEN"))
        self.admin_client = tk.StringVar(value=load_env_value("BRELLA_ADMIN_CLIENT"))
        self.admin_uid = tk.StringVar(value=load_env_value("BRELLA_ADMIN_UID"))

        # === Top block: API / Admin connection ===
        conn_block = tk.Frame(self.frame, bg=BG)
        conn_block.grid(row=0, column=0, sticky="nsew", padx=P, pady=(P, P // 2))
        tk.Label(conn_block, text="CONNECTION", font=FONT_SECTION, fg=ACCENT,
             bg=BG, anchor="w").pack(fill="x", padx=2, pady=(0, 4))
        tk.Frame(conn_block, bg=SURFACE_RAISED, height=1).pack(fill="x", pady=(0, 6))

        conn_inner = tk.Frame(conn_block, bg=BG)
        conn_inner.pack(fill="x")

        # Status pill
        api_status_row = tk.Frame(conn_inner, bg=BG)
        api_status_row.pack(fill="x", pady=(0, 2))
        api_loaded = bool(self.api_key.get())
        self._api_status_dot = tk.Frame(api_status_row,
                                        bg=SUCCESS if api_loaded else DANGER, width=7, height=7)
        self._api_status_dot.pack(side="left", padx=(0, 6), pady=3)
        self._api_status_dot.pack_propagate(False)
        self._api_status_lbl = tk.Label(api_status_row,
                                        text="API key loaded" if api_loaded else "API key not set",
                                        font=FONT_SMALL,
                                        fg=SUCCESS if api_loaded else DANGER, bg=BG)
        self._api_status_lbl.pack(side="left")

        creds_grid = tk.Frame(conn_inner, bg=BG)
        creds_grid.pack(fill="x")
        creds_grid.columnconfigure(0, weight=1)
        creds_grid.columnconfigure(1, weight=1)

        api_col = tk.Frame(creds_grid, bg=BG)
        api_col.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        tk.Label(
            api_col,
            text="INTEGRATION API",
            font=FONT_SECTION,
            fg=ACCENT,
            bg=BG,
            anchor="w",
        ).pack(fill="x")
        make_field(api_col, "API Key", self.api_key, show="*")

        ids_row = tk.Frame(api_col, bg=BG)
        ids_row.pack(fill="x")
        ids_left = tk.Frame(ids_row, bg=BG)
        ids_left.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ids_right = tk.Frame(ids_row, bg=BG)
        ids_right.pack(side="right", fill="x", expand=True, padx=(4, 0))
        make_field(ids_left, "Org ID", self.org_id)
        make_field(ids_right, "Event ID", self.event_id)

        admin_col = tk.Frame(creds_grid, bg=BG)
        admin_col.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        tk.Label(
            admin_col,
            text="ADMIN PANEL",
            font=FONT_SECTION,
            fg=ACCENT,
            bg=BG,
            anchor="w",
        ).pack(fill="x")
        make_field(admin_col, "Access Token", self.admin_token, show="*")

        admin_row = tk.Frame(admin_col, bg=BG)
        admin_row.pack(fill="x")
        al = tk.Frame(admin_row, bg=BG)
        al.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ar = tk.Frame(admin_row, bg=BG)
        ar.pack(side="right", fill="x", expand=True, padx=(4, 0))
        make_field(al, "Client", self.admin_client)
        make_field(ar, "UID", self.admin_uid)

        # API status row (action buttons are in bottom action bar)
        self._api_status_var = tk.StringVar(value="")
        self._api_status_result = tk.Label(conn_inner, textvariable=self._api_status_var,
                                            font=FONT_SMALL, fg=TEXT_SEC, bg=BG,
                                            anchor="w")
        self._api_status_result.pack(fill="x", pady=(4, 0))

        # Divider between major Setup blocks
        tk.Frame(self.frame, bg=SURFACE_RAISED, height=1).grid(
            row=1, column=0, sticky="ew", padx=P, pady=(0, P // 2)
        )

        # === Bottom block: compact mappings ===
        import api

        values_block = tk.Frame(self.frame, bg=BG)
        values_block.grid(row=2, column=0, sticky="nsew", padx=P, pady=(P // 2, P))
        tk.Label(values_block, text="GROUPS & TICKETS", font=FONT_SECTION, fg=ACCENT,
             bg=BG, anchor="w").pack(fill="x", padx=2, pady=(0, 4))
        tk.Frame(values_block, bg=SURFACE_RAISED, height=1).pack(fill="x", pady=(0, 6))

        values_inner = tk.Frame(values_block, bg=BG)
        values_inner.pack(fill="both", expand=True)

        self.groups_inline_var = tk.StringVar(
            value=self._format_mapping_inline(api.BRELLA_ATTENDEE_GROUP_IDS)
        )
        self.priority_inline_var = tk.StringVar(value="; ".join(api.GROUP_PRIORITY))

        tk.Label(values_inner, text="Group numbers",
                 font=FONT_SMALL, fg=TEXT_SEC, bg=BG, anchor="w").pack(fill="x")
        self.groups_inline_entry = tk.Entry(
            values_inner,
            textvariable=self.groups_inline_var,
            font=FONT_MONO,
            bg=BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=SURFACE_RAISED,
            highlightcolor=ACCENT,
        )
        self.groups_inline_entry.pack(fill="x", ipady=4, pady=(1, 4))

        tk.Label(values_inner, text="Priority group IDs",
                 font=FONT_SMALL, fg=TEXT_SEC, bg=BG, anchor="w").pack(fill="x")
        self.priority_inline_entry = tk.Entry(
            values_inner,
            textvariable=self.priority_inline_var,
            font=FONT_MONO,
            bg=BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=SURFACE_RAISED,
            highlightcolor=ACCENT,
        )
        self.priority_inline_entry.pack(fill="x", ipady=4, pady=(1, 4))

        tk.Label(values_inner, text="Ticket types",
                 font=FONT_SMALL, fg=TEXT_SEC, bg=BG, anchor="w").pack(fill="x")
        self.tickets_inline_text = tk.Text(
            values_inner,
            font=FONT_MONO,
            bg=BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=SURFACE_RAISED,
            highlightcolor=ACCENT,
            wrap="word",
            height=12,
            padx=6,
            pady=6,
        )
        self.tickets_inline_text.pack(fill="both", expand=True, pady=(1, 6))
        self.tickets_inline_text.insert(
            "1.0", self._format_mapping_inline(api.TICKET_TYPE_TO_GROUP_ID)
        )

        # Log-hosted action row for Setup
        if self._app and hasattr(self._app, "_log_action_host"):
            self.action_row = tk.Frame(self._app._log_action_host, bg=SURFACE)
            action_parent = self.action_row
        else:
            action_parent = self.frame

        self.test_btn = tk.Button(
            action_parent,
            text="Test Connection",
            font=FONT_SMALL,
            bg=SURFACE_RAISED,
            fg=TEXT_SEC,
            activebackground="#2e2e38",
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            padx=ACTION_BTN_PADX,
            pady=ACTION_BTN_PADY,
            command=self._test_connection,
        )

        self.save_api_btn = tk.Button(
            action_parent,
            text="Save",
            font=FONT_SMALL,
            bg=ACCENT,
            fg="white",
            activebackground=ACCENT_LIGHT,
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            padx=ACTION_BTN_PADX,
            pady=ACTION_BTN_PADY,
            command=self._save_api,
        )

        self.save_vals_btn = tk.Button(
            action_parent,
            text="Save Values",
            font=FONT_SMALL,
            bg=ACCENT,
            fg="white",
            activebackground=ACCENT_LIGHT,
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            padx=ACTION_BTN_PADX,
            pady=ACTION_BTN_PADY,
            command=self._save_values,
        )

        self.test_btn.pack(side="left", padx=(0, ACTION_BTN_GAP))
        self.save_api_btn.pack(side="left", padx=(0, ACTION_BTN_GAP))
        self.save_vals_btn.pack(side="left")

        _bind_button_flash(self.test_btn, SURFACE_RAISED, "#2e2e38")
        _bind_button_flash(self.save_api_btn, ACCENT, ACCENT_LIGHT)
        _bind_button_flash(self.save_vals_btn, ACCENT, ACCENT_LIGHT)

    # --- Inline value helpers ---

    def _format_mapping_inline(self, mapping):
        return "; ".join(f"{k}={v}" for k, v in mapping.items())

    def _parse_mapping_inline(self, raw_text, label):
        parsed = {}
        invalid = []

        for token in raw_text.split(";"):
            item = token.strip()
            if not item:
                continue
            if "=" not in item:
                invalid.append(item)
                continue
            key, value = item.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key or not value:
                invalid.append(item)
                continue
            parsed[key] = value

        if invalid and self.log_callback:
            preview = "; ".join(invalid[:5])
            suffix = " ..." if len(invalid) > 5 else ""
            self.log_callback(
                f"[WARN] {label}: ignored invalid item(s) without key=value: {preview}{suffix}"
            )

        return parsed

    def _parse_priority_inline(self, raw_text):
        return [item.strip() for item in raw_text.split(";") if item.strip()]

    # --- Save / Test ---

    def _save_api(self):
        save_env_values({
            "BRELLA_API_KEY": self.api_key.get().strip(),
            "BRELLA_ORG_ID": self.org_id.get().strip(),
            "BRELLA_EVENT_ID": self.event_id.get().strip(),
            "BRELLA_ADMIN_ACCESS_TOKEN": self.admin_token.get().strip(),
            "BRELLA_ADMIN_CLIENT": self.admin_client.get().strip(),
            "BRELLA_ADMIN_UID": self.admin_uid.get().strip(),
        })
        for k, var in [("BRELLA_API_KEY", self.api_key), ("BRELLA_ORG_ID", self.org_id),
                       ("BRELLA_EVENT_ID", self.event_id),
                       ("BRELLA_ADMIN_ACCESS_TOKEN", self.admin_token),
                       ("BRELLA_ADMIN_CLIENT", self.admin_client),
                       ("BRELLA_ADMIN_UID", self.admin_uid)]:
            os.environ[k] = var.get().strip()

        api_ok = bool(self.api_key.get().strip())
        self._api_status_dot.config(bg=SUCCESS if api_ok else DANGER)
        self._api_status_lbl.config(
            text="API key loaded" if api_ok else "API key not set",
            fg=SUCCESS if api_ok else DANGER,
        )
        self._show_api_status("Saved to .env", SUCCESS)

    def _test_connection(self):
        import threading
        def _test():
            from urllib import request as url_req, error as url_err
            org = os.environ.get("BRELLA_ORG_ID", "")
            event = os.environ.get("BRELLA_EVENT_ID", "")
            api_key = os.environ.get("BRELLA_API_KEY", "")
            if api_key and org and event:
                url = f"https://api.brella.io/api/integration/organizations/{org}/events/{event}"
                headers = {
                    os.environ.get("BRELLA_AUTH_HEADER_NAME", "Brella-API-Access-Token"): api_key,
                    "User-Agent": os.environ.get("BRELLA_HTTP_USER_AGENT", "SIMsync"),
                }
                try:
                    req = url_req.Request(url, headers=headers)
                    resp = url_req.urlopen(req, timeout=10)
                    self.frame.after(0, lambda: self._show_api_status(
                        f"Connected — event {event} (HTTP {resp.status})", SUCCESS))
                except url_err.HTTPError as e:
                    self.frame.after(0, lambda: self._show_api_status(
                        f"API error: HTTP {e.code}", DANGER))
                except Exception as e:
                    self.frame.after(0, lambda: self._show_api_status(
                        f"Connection failed: {e}", DANGER))
            else:
                self.frame.after(0, lambda: self._show_api_status(
                    "Missing API key, org, or event ID", WARN))
        threading.Thread(target=_test, daemon=True).start()

    def _show_api_status(self, text, color):
        self._api_status_var.set(text)
        self._api_status_result.config(fg=color)
        self._api_status_result.pack(fill="x", pady=(4, 0))

    def _save_values(self):
        import api

        groups_raw = self.groups_inline_var.get().strip()
        priority_raw = self.priority_inline_var.get().strip()
        tickets_raw = self.tickets_inline_text.get("1.0", "end").strip()

        groups = self._parse_mapping_inline(groups_raw, "Groups")
        tickets = self._parse_mapping_inline(tickets_raw, "Ticket mappings")
        priority = self._parse_priority_inline(priority_raw)

        api.save_config(
            attendee_groups=groups,
            group_priority=priority,
            ticket_type_to_group=tickets,
        )

        # Normalize UI text after save so format stays clean and compact.
        self.groups_inline_var.set(self._format_mapping_inline(groups))
        self.priority_inline_var.set("; ".join(priority))
        self.tickets_inline_text.delete("1.0", "end")
        self.tickets_inline_text.insert("1.0", self._format_mapping_inline(tickets))

        if self.log_callback:
            self.log_callback(
                f"Values saved — {len(groups)} groups, "
                f"{len(tickets)} ticket mappings, {len(priority)} priority entries"
            )


# --- Sync Tab ---

class SyncTab:
    def __init__(self, parent, name, description, has_prune=False, has_cookie=False,
                 run_func=None, enabled=True, app=None,
                 csv_header_fields=None):
        self.name = name
        self.run_func = run_func
        self.enabled = enabled
        self._app = app
        self.csv_path = tk.StringVar()
        self.dry_run = tk.BooleanVar(value=False)
        self.prune = tk.BooleanVar(value=False)
        self.has_prune = has_prune
        self.has_cookie = has_cookie
        self.download_from_3cket = tk.BooleanVar(value=False)
        self.cookie = tk.StringVar(value=load_env_value("THREECKET_COOKIE"))
        self.running = False
        self.action_row = None

        self.frame = tk.Frame(parent, bg=BG)

        inner_frame = tk.Frame(self.frame, bg=BG)
        inner_frame.pack(fill="x", side="top")

        # CSV header section — inline, required fields only, copyable
        req_fields = [f for f, req in (csv_header_fields or []) if req]
        if req_fields:
            fmt_inner = self._make_section(inner_frame, "CSV HEADER", compact=True)
            txt = tk.Text(
                fmt_inner, font=("Poppins", 8), bg=BG, fg=ACCENT_LIGHT,
                relief="flat", borderwidth=0, highlightthickness=0,
                wrap="word", cursor="hand2", height=1,
            )
            txt.insert("end", ", ".join(req_fields))
            txt.config(state="disabled")
            txt.pack(fill="x", pady=0)
            def _fit_height(tw=txt):
                tw.update_idletasks()
                lines = int(tw.index("end-1c").split(".")[0])
                tw.config(height=max(lines, 1))
            txt.after_idle(_fit_height)
            # Click to copy
            def _copy_header(event=None, names=req_fields, widget=txt):
                widget.clipboard_clear()
                widget.clipboard_append(",".join(names))
                widget.config(state="normal")
                widget.tag_configure("flash", foreground=SUCCESS)
                widget.tag_add("flash", "1.0", "end")
                def _unflash():
                    widget.tag_delete("flash")
                    widget.config(state="disabled")
                widget.after(350, _unflash)
                widget.config(state="disabled")
            txt.bind("<Button-1>", _copy_header)

        # CSV picker section
        csv_inner = self._make_section(inner_frame, "CSV FILE")
        csv_row = tk.Frame(csv_inner, bg=BG)
        csv_row.pack(fill="x")
        csv_row.columnconfigure(0, weight=1)

        self.path_entry = tk.Entry(csv_row, textvariable=self.csv_path, font=FONT_MONO,
                                   bg=BG, fg=TEXT, insertbackground=TEXT,
                                   relief="flat", highlightthickness=1,
                                   highlightbackground=SURFACE_RAISED, highlightcolor=ACCENT)
        self.path_entry.grid(row=0, column=0, sticky="ew", ipady=5)

        self.browse_btn = tk.Button(
            csv_row,
            text="Browse",
            font=FONT_SMALL,
            bg=SURFACE_RAISED,
            fg=TEXT,
            activebackground=ACCENT,
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            padx=14,
            pady=2,
            height=1,
            command=self._browse,
        )
        self.browse_btn.grid(row=0, column=1, padx=(8, 0), sticky="ns")

        # Options section
        if has_prune or has_cookie:
            opts_inner = self._make_section(inner_frame, "OPTIONS")
            if has_prune:
                self.prune_cb = tk.Checkbutton(opts_inner,
                                               text="Prune missing (remove from Brella if not in CSV)",
                                               variable=self.prune, font=FONT_SMALL,
                                               fg=TEXT_SEC, bg=BG, selectcolor=BG,
                                               activebackground=BG, activeforeground=TEXT,
                                               anchor="w")
                self.prune_cb.pack(fill="x")
            if has_cookie:
                self.dl_cb = tk.Checkbutton(opts_inner,
                                            text="Download CSV from 3cket instead of local file",
                                            variable=self.download_from_3cket, font=FONT_SMALL,
                                            fg=TEXT_SEC, bg=BG, selectcolor=BG,
                                            activebackground=BG, activeforeground=TEXT,
                                            anchor="w", command=self._toggle_source)
                self.dl_cb.pack(fill="x", pady=(4, 0))
                self.cookie_entry = make_field(opts_inner, "Session Cookie", self.cookie, show="*")

        # Detail boxes: 2x2 grid with line dividers and no card spacing
        tk.Frame(self.frame, bg=SURFACE_RAISED, height=1).pack(fill="x")
        detail_container = tk.Frame(self.frame, bg=SURFACE_RAISED)
        detail_container.pack(fill="both", expand=True, padx=0, pady=0)
        detail_container.columnconfigure(0, weight=1)
        detail_container.columnconfigure(1, weight=1)
        detail_container.rowconfigure(0, weight=1)
        detail_container.rowconfigure(1, weight=1)

        self.card_added, self.card_added_title, self.list_added = self._make_unified_box(
            detail_container, "ADDED", "0", SUCCESS, row=0, col=0)
        self.card_updated, _, self.list_updated = self._make_unified_box(
            detail_container, "UPDATED", "0", ACCENT, row=0, col=1)
        self.card_removed, _, self.list_removed = self._make_unified_box(
            detail_container, "REMOVED", "0", DANGER, row=1, col=0)
        self.card_missing, _, self.list_missing = self._make_unified_box(
            detail_container, "MISSING INFO", "0", WARN, row=1, col=1, copyable=True)

        # Log-hosted action row for Preview/Import
        if self._app and hasattr(self._app, "_log_action_host"):
            self.action_row = tk.Frame(self._app._log_action_host, bg=SURFACE)
            action_parent = self.action_row
        else:
            action_parent = self.frame

        self.preview_btn = tk.Button(
            action_parent,
            text="Preview",
            font=FONT_SMALL,
            bg=SURFACE_RAISED,
            fg=TEXT_SEC,
            activebackground="#2e2e38",
            activeforeground=TEXT,
            relief="flat",
            cursor="hand2",
            padx=ACTION_BTN_PADX,
            pady=ACTION_BTN_PADY,
            command=lambda: self._run(dry_run=True),
        )

        self.import_btn = tk.Button(
            action_parent,
            text="Import",
            font=FONT_SMALL,
            bg=ACCENT,
            fg="white",
            activebackground=ACCENT_LIGHT,
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            padx=ACTION_BTN_PADX,
            pady=ACTION_BTN_PADY,
            command=lambda: self._run(dry_run=False),
        )

        self.preview_btn.pack(side="left", padx=(0, ACTION_BTN_GAP))
        self.import_btn.pack(side="left")

        _bind_button_flash(self.preview_btn, SURFACE_RAISED, "#2e2e38")
        _bind_button_flash(self.import_btn, ACCENT, ACCENT_LIGHT)

        if not enabled:
            self.browse_btn.config(state="disabled")
            self.path_entry.config(state="disabled")
            self.preview_btn.config(state="disabled")
            self.import_btn.config(state="disabled")

    def _make_section(self, parent, title, compact=False):
        section = tk.Frame(parent, bg=BG)
        section.pack(fill="x")

        tk.Frame(section, bg=SURFACE_RAISED, height=1).pack(fill="x")
        title_pady = (3, 2) if compact else (5, 4)
        inner_pady = (0, 2) if compact else (0, 6)
        tk.Label(section, text=title, font=FONT_SECTION, fg=ACCENT,
                 bg=BG, anchor="w").pack(fill="x", padx=CARD_PAD_INNER, pady=title_pady)

        inner = tk.Frame(section, bg=BG)
        inner.pack(fill="x", padx=CARD_PAD_INNER, pady=inner_pady)
        return inner


    def _make_unified_box(self, parent, title, value, color, row=0, col=0, copyable=False):
        outer = tk.Frame(parent, bg=BG)
        padx = (0, 1) if col == 0 else (0, 0)
        pady = (0, 1) if row == 0 else (0, 0)
        outer.grid(row=row, column=col, sticky="nsew", padx=padx, pady=pady)
        outer.columnconfigure(0, weight=1)

        accent_line = tk.Frame(outer, bg=color, height=2)
        accent_line.grid(row=0, column=0, sticky="ew")

        header = tk.Frame(outer, bg=BG)
        header.grid(row=1, column=0, sticky="ew")

        title_row = tk.Frame(header, bg=BG)
        title_row.pack(fill="x", padx=7, pady=(1, 2))

        count_label = tk.Label(title_row, text=value, font=("Poppins", 14, "bold"),
                       fg=color, bg=BG, anchor="w")
        count_label.pack(side="left")

        title_label = tk.Label(title_row, text=title, font=("Poppins", 7, "bold"),
                               fg=TEXT_TER, bg=BG, anchor="w")
        title_label.pack(side="left", padx=(7, 0), pady=(3, 0))

        if copyable:
            copy_btn = tk.Button(title_row, text="Copy", font=("Poppins", 7),
                                 bg=BG, fg=TEXT_TER,
                                 activebackground=SURFACE_RAISED, activeforeground=TEXT,
                                 relief="flat", cursor="hand2", bd=0,
                                 command=lambda: self._copy_listbox(lb))
            copy_btn.pack(side="right")
            copy_btn.bind("<Enter>", lambda e: copy_btn.config(fg=TEXT_SEC))
            copy_btn.bind("<Leave>", lambda e: copy_btn.config(fg=TEXT_TER))

        sep = tk.Frame(outer, bg=SURFACE_RAISED, height=1)
        sep.grid(row=2, column=0, sticky="ew")

        list_frame = tk.Frame(outer, bg=BG)
        list_frame.grid(row=3, column=0, sticky="nsew")
        outer.rowconfigure(3, weight=1)
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        lb = tk.Listbox(list_frame, font=FONT_SMALL, bg=BG, fg=TEXT_SEC,
                        selectbackground=SURFACE_RAISED, selectforeground=TEXT,
                        relief="flat", borderwidth=0, highlightthickness=0,
                        activestyle="none")
        lb.grid(row=0, column=0, sticky="nsew", padx=6, pady=(6, 6))

        return count_label, title_label, lb

    def _copy_listbox(self, lb):
        items = lb.get(0, "end")
        if items:
            self.frame.clipboard_clear()
            self.frame.clipboard_append("\n".join(items))

    def update_summary(self, added=0, updated=0, removed=0, missing=0):
        def _update():
            self.card_added.config(text=str(added))
            self.card_added_title.config(text="TO SYNC" if self.dry_run.get() else "ADDED")
            self.card_updated.config(text=str(updated))
            self.card_removed.config(text=str(removed))
            self.card_missing.config(text=str(missing))
        self.frame.after(0, _update)

    def update_details(self, added=None, updated=None, removed=None, missing=None):
        def _update():
            for lb, items in [
                (self.list_added, added or []),
                (self.list_updated, updated or []),
                (self.list_removed, removed or []),
                (self.list_missing, missing or []),
            ]:
                lb.delete(0, "end")
                if items:
                    for item in items:
                        lb.insert("end", f"  {item}")
                else:
                    lb.insert("end", "  —")
        self.frame.after(0, _update)

    def _toggle_source(self):
        if self.download_from_3cket.get():
            self.path_entry.config(state="disabled")
            self.browse_btn.config(state="disabled")
        else:
            self.path_entry.config(state="normal")
            self.browse_btn.config(state="normal")

    def _browse(self):
        path = filedialog.askopenfilename(
            title=f"Select {self.name} CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self.csv_path.set(path)

    def _run(self, dry_run=False):
        if self.running:
            return
        downloading = self.has_cookie and self.download_from_3cket.get()
        if not downloading and not self.csv_path.get().strip():
            self._set_status("Select a CSV file first.", DANGER)
            return
        if not downloading and not Path(self.csv_path.get()).exists():
            self._set_status("File not found.", DANGER)
            return
        if self.has_cookie and self.cookie.get().strip():
            os.environ["THREECKET_COOKIE"] = self.cookie.get().strip()
            save_env_values({"THREECKET_COOKIE": self.cookie.get().strip()})
        self.dry_run.set(dry_run)
        self.running = True
        self._set_busy(True)
        mode = "preview" if dry_run else "import"
        self._set_status(f"Running {mode}...", ACCENT_LIGHT)
        if self._app:
            self._app._log_status_pulse.start(ACCENT_LIGHT)
        threading.Thread(target=self._run_thread, daemon=True).start()

    def _run_thread(self):
        try:
            if self.run_func:
                self.run_func(self)
            else:
                self._log(f"[{self.name}] Not implemented yet.")
            mode = "Preview" if self.dry_run.get() else "Import"
            self._set_status(f"{mode} complete.", SUCCESS)
        except Exception as exc:
            self._log(f"[ERROR] {exc}")
            self._set_status(f"Failed: {exc}", DANGER)
        finally:
            self.running = False
            if self._app:
                self._app._log_status_pulse.stop()
            self.frame.after(0, lambda: self._set_busy(False))

    def _set_busy(self, busy):
        state = "disabled" if busy else "normal"
        self.preview_btn.config(state=state)
        self.import_btn.config(state=state)
        if not (self.has_cookie and self.download_from_3cket.get()):
            self.browse_btn.config(state=state)

    def _set_status(self, text, color=TEXT_TER):
        def _update():
            if self._app:
                self._app._log_status_var.set(text)
                self._app._log_status_label.config(fg=color)
                pulse = self._app._log_status_pulse
                if not pulse._running:
                    self._app._log_status_dot.config(bg=color)
                else:
                    pulse.stop(final_color=color)
        self.frame.after(0, _update)

    def _log(self, msg):
        if hasattr(self, '_log_callback') and self._log_callback:
            self.frame.after(0, lambda: self._log_callback(msg))


# --- App ---

def _apply_dark_title_bar(root):
    try:
        root.update()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(value), ctypes.sizeof(value),
        )
    except Exception:
        pass


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("SIMconference2Brella")
        self.root.configure(bg=BG)
        self.root.minsize(750, 520)
        self.root.state("zoomed")
        _apply_dark_title_bar(self.root)

        self._nav_anim_ids = {}
        self._ind_anim_ids = {}
        self._log_fade_counter = 0

        # Main layout: sidebar left, right side = content top + log bottom
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="both", expand=True)
        self._outer = outer

        # Sidebar
        sidebar = tk.Frame(outer, bg=SURFACE, width=SIDEBAR_W)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        self._sidebar = sidebar

        self._outer.bind("<Configure>", self._on_outer_resize)

        tk.Frame(sidebar, bg=SURFACE, height=10).pack(fill="x")

        # Nav
        self.nav_buttons = []
        self.nav_indicators = []
        self.panels = {}
        self._sync_tabs = {}
        self.active_panel = None
        self._nav_current_bg = {}
        self._nav_current_fg = {}
        self._nav_hovered = {}

        # Content area (fills remaining space after sidebar)
        self.content = tk.Frame(outer, bg=BG)
        self.content.pack(side="left", fill="both", expand=True)

        # Log panel (inside sidebar — packed after nav items below)
        self._log_frame = tk.Frame(sidebar, bg=SURFACE)

        # Log header
        log_header = tk.Frame(self._log_frame, bg=SURFACE)
        log_header.pack(fill="x")

        log_title_row = tk.Frame(log_header, bg=SURFACE)
        log_title_row.pack(fill="x", padx=CARD_PAD_X, pady=(6, 0))

        tk.Label(log_title_row, text="LOG", font=("Poppins", 8, "bold"),
             fg=TEXT_TER, bg=SURFACE, anchor="w").pack(side="left")

        clear_btn = tk.Button(log_title_row, text="Clear", font=("Poppins", 8),
                              bg=SURFACE, fg=TEXT_TER,
                              activebackground=SURFACE_RAISED, activeforeground=TEXT,
                              relief="flat", cursor="hand2", bd=0,
                              command=self._clear_log)
        clear_btn.pack(side="right")
        clear_btn.bind("<Enter>", lambda e: clear_btn.config(fg=TEXT_SEC))
        clear_btn.bind("<Leave>", lambda e: clear_btn.config(fg=TEXT_TER))

        log_sep = tk.Frame(log_header, bg=SURFACE_RAISED, height=1)
        log_sep.pack(fill="x", padx=CARD_PAD_X, pady=(GAP, 0))

        # Log text
        self.log_text = tk.Text(self._log_frame, font=("Poppins", 8), bg="#0c0c12", fg=TEXT_SEC,
                                relief="flat", wrap="word", insertbackground=ACCENT_LIGHT,
                                state="disabled", padx=6, pady=6)
        self.log_text.pack(fill="both", expand=True, padx=4, pady=(GAP, 2))

        # Shared host for per-page floating actions inside log panel.
        self._log_action_host = tk.Frame(self._log_frame, bg=SURFACE)
        self._log_action_host.pack(side="bottom", fill="x", padx=4, pady=(0, 4))

        self._log_status_row = tk.Frame(self._log_action_host, bg=SURFACE)
        self._log_status_row.pack(side="right", padx=(8, 4), pady=4)

        self._log_status_dot = tk.Frame(self._log_status_row, bg=TEXT_TER, width=7, height=7)
        self._log_status_dot.pack(side="left", padx=(0, 6), pady=1)
        self._log_status_dot.pack_propagate(False)
        self._log_status_pulse = StatusPulse(self._log_status_dot)

        self._log_status_var = tk.StringVar(value="Ready")
        self._log_status_label = tk.Label(
            self._log_status_row,
            textvariable=self._log_status_var,
            font=("Poppins", 8, "bold"),
            fg=TEXT_SEC,
            bg=SURFACE,
            anchor="w",
        )
        self._log_status_label.pack(side="left")

        self._panel_action_rows = {}

        # Configure log text tags
        self.log_text.tag_configure("timestamp", foreground=TEXT_TER)
        self.log_text.tag_configure("msg_default", foreground=TEXT_SEC)
        self.log_text.tag_configure("msg_ok", foreground=SUCCESS)
        self.log_text.tag_configure("msg_error", foreground=DANGER)
        self.log_text.tag_configure("msg_warn", foreground=WARN)
        self.log_text.tag_configure("msg_preview", foreground=ACCENT)
        self.log_text.tag_configure("msg_info", foreground=TEXT_SEC)

        # --- Setup tab ---
        self._add_nav(sidebar, "Setup")
        setup = SetupTab(self.content, log_callback=self.log, app=self)
        self._setup_tab = setup
        self.panels["Setup"] = setup.frame
        if getattr(setup, "action_row", None) is not None:
            self._panel_action_rows["Setup"] = setup.action_row

        nav_sep = tk.Frame(sidebar, bg=SURFACE_RAISED, height=1)
        nav_sep.pack(fill="x", padx=16, pady=(6, 6))
        tk.Label(sidebar, text="SYNC", font=("Poppins", 7, "bold"),
                 fg=TEXT_TER, bg=SURFACE).pack(fill="x", padx=18, pady=(0, 4))

        # --- Sync tabs ---
        _default_csvs = {
            "Participants": BASE_DIR / "data" / "participants.csv",
            "Speakers": BASE_DIR / "data" / "speakers.csv",
            "Schedule": BASE_DIR / "data" / "schedule.csv",
        }

        for name, desc, prune, cookie, func, en, fields in [
            (
                "Participants",
                "Sync 3cket participants to Brella.",
                True,
                True,
                self._run_participants,
                True,
                [
                    ("#", True), ("Name", True), ("Phone", False),
                    ("Email", True), ("Gender", False), ("Birth date", False),
                    ("Country", False), ("Language", False), ("Check in", False),
                    ("Marketing authorization", False), ("Tickets", True),
                    ("Total tickets", False), ("E-mail", True),
                    ("Company // Empresa", True), ("Group", False),
                ],
            ),
            (
                "Speakers",
                "Sync published speakers to Brella.",
                False,
                False,
                self._run_speakers,
                True,
                [
                    ("First name", True), ("Last Name", True),
                    ("Company", True), ("Job Title", True), ("Bio", True),
                    ("Privacy Policy consent", False),
                    ("Optional consents", False), ("Photo", True),
                    ("Social media links", True), ("Email Contact", True),
                    ("Speaker Email", True), ("Phone Contact", False),
                    ("Pre-event communication interest", False),
                    ("Media availability", False), ("Submitted At", False),
                    ("Token", True), ("Publish", True),
                ],
            ),
            (
                "Sponsors",
                "Sync sponsor data to Brella.",
                False,
                False,
                None,
                False,
                [],
            ),
            (
                "Schedule",
                "Sync event sessions to Brella.",
                False,
                False,
                self._run_schedule,
                True,
                [
                    ("date", True), ("start_time", True), ("duration", True),
                    ("title", True), ("content", False), ("track", True),
                    ("location", False), ("speakers", False),
                ],
            ),
        ]:
            self._add_nav(sidebar, name)
            tab = SyncTab(self.content, name, desc, has_prune=prune, has_cookie=cookie,
                          run_func=func, enabled=en, app=self,
                          csv_header_fields=fields)
            tab._log_callback = self.log
            default_csv = _default_csvs.get(name)
            if default_csv and default_csv.exists():
                tab.csv_path.set(str(default_csv))
            self.panels[name] = tab.frame
            self._sync_tabs[name] = tab
            if getattr(tab, "action_row", None) is not None:
                self._panel_action_rows[name] = tab.action_row

        # Pack log into sidebar below nav
        log_nav_sep = tk.Frame(sidebar, bg=SURFACE_RAISED, height=1)
        log_nav_sep.pack(fill="x", padx=10, pady=(8, 0))
        self._log_frame.pack(fill="both", expand=True, pady=(0, 0))

        self._set_sidebar_width()

        self._switch_panel("Setup")
        self._apply_env()

    def _set_sidebar_width(self, total_width=None):
        if total_width is None:
            total_width = self._outer.winfo_width()
        if total_width <= 1:
            return
        target_width = max(1, int(total_width * SIDEBAR_WIDTH_RATIO))
        current_width = int(self._sidebar.cget("width"))
        if current_width != target_width:
            self._sidebar.config(width=target_width)

    def _on_outer_resize(self, event):
        self._set_sidebar_width(event.width)

    def _add_nav(self, sidebar, name):
        row = tk.Frame(sidebar, bg=SURFACE)
        row.pack(fill="x", padx=0, pady=0)

        indicator = tk.Frame(row, bg=SURFACE, width=3)
        indicator.pack(side="left", fill="y")
        indicator.pack_propagate(False)

        btn = tk.Button(row, text=name, font=FONT_SMALL, fg=TEXT_SEC, bg=SURFACE,
                        activebackground=SURFACE_RAISED, activeforeground=TEXT,
                        relief="flat", anchor="w", padx=14, pady=5, cursor="hand2",
                        command=lambda n=name: self._switch_panel(n))
        btn.pack(side="left", fill="x", expand=True)

        self._nav_current_bg[name] = SURFACE
        self._nav_current_fg[name] = TEXT_SEC
        self._nav_hovered[name] = False

        def on_enter(e, n=name, ind=indicator):
            self._nav_hovered[n] = True
            if self.active_panel != n:
                self._animate_nav(n, target_bg=SURFACE_RAISED, target_fg=TEXT)
                ind.config(bg=TEXT_TER)

        def on_leave(e, n=name, ind=indicator):
            self._nav_hovered[n] = False
            if self.active_panel != n:
                self._animate_nav(n, target_bg=SURFACE, target_fg=TEXT_SEC)
                ind.config(bg=SURFACE)

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        row.bind("<Enter>", on_enter)
        row.bind("<Leave>", on_leave)

        self.nav_buttons.append((name, btn, row))
        self.nav_indicators.append((name, indicator))

    def _animate_nav(self, name, target_bg, target_fg):
        if name in self._nav_anim_ids and self._nav_anim_ids[name] is not None:
            try:
                self.root.after_cancel(self._nav_anim_ids[name])
            except Exception:
                pass
            self._nav_anim_ids[name] = None
        start_bg = self._nav_current_bg.get(name, SURFACE)
        start_fg = self._nav_current_fg.get(name, TEXT_SEC)
        btn = row = None
        for n, b, r in self.nav_buttons:
            if n == name:
                btn, row = b, r
                break
        if btn is None:
            return
        step = [0]
        def tick():
            step[0] += 1
            t = min(step[0] / NAV_ANIM_STEPS, 1.0)
            t_ease = 1.0 - (1.0 - t) ** 2
            bg = _lerp_color(start_bg, target_bg, t_ease)
            fg = _lerp_color(start_fg, target_fg, t_ease)
            try:
                btn.config(bg=bg, fg=fg)
                row.config(bg=bg)
            except Exception:
                return
            self._nav_current_bg[name] = bg
            self._nav_current_fg[name] = fg
            if step[0] < NAV_ANIM_STEPS:
                self._nav_anim_ids[name] = self.root.after(ANIM_INTERVAL, tick)
            else:
                self._nav_anim_ids[name] = None
        tick()

    def _switch_panel(self, name):
        self.active_panel = name
        for panel_name, frame in self.panels.items():
            if panel_name == name:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()

        for btn_name, btn, row in self.nav_buttons:
            if btn_name == name:
                self._animate_nav(btn_name, target_bg=SURFACE_RAISED, target_fg=ACCENT_LIGHT)
            else:
                if not self._nav_hovered.get(btn_name, False):
                    self._animate_nav(btn_name, target_bg=SURFACE, target_fg=TEXT_SEC)
                else:
                    self._animate_nav(btn_name, target_bg=SURFACE_RAISED, target_fg=TEXT)

        for ind_name, indicator in self.nav_indicators:
            indicator.config(bg=ACCENT if ind_name == name else SURFACE)

        self._show_log_actions(name)

    def _show_log_actions(self, panel_name):
        for row in self._panel_action_rows.values():
            row.pack_forget()

        active_row = self._panel_action_rows.get(panel_name)
        if active_row is not None:
            active_row.pack(side="left", padx=(4, 0), pady=4)

    def log(self, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        msg_upper = msg.upper()
        if "[OK]" in msg_upper or "complete" in msg.lower() or "success" in msg.lower():
            msg_tag = "msg_ok"
        elif "[ERROR]" in msg_upper or "failed" in msg.lower():
            msg_tag = "msg_error"
        elif "[WARN]" in msg_upper or "warning" in msg.lower():
            msg_tag = "msg_warn"
        elif "[PREVIEW]" in msg_upper or "preview" in msg.lower() or "dry" in msg.lower():
            msg_tag = "msg_preview"
        elif "[INFO]" in msg_upper:
            msg_tag = "msg_info"
        else:
            msg_tag = "msg_default"

        tag_info = self.log_text.tag_cget(msg_tag, "foreground")
        target_color = tag_info if tag_info else TEXT_SEC

        self._log_fade_counter += 1
        fade_ts_tag = f"_fade_ts_{self._log_fade_counter}"
        fade_msg_tag = f"_fade_msg_{self._log_fade_counter}"

        ts_target = TEXT_TER
        ts_bright = _lerp_color(ts_target, TEXT, 0.7)
        msg_bright = _lerp_color(target_color, TEXT, 0.5)

        self.log_text.tag_configure(fade_ts_tag, foreground=ts_bright)
        self.log_text.tag_configure(fade_msg_tag, foreground=msg_bright)

        self.log_text.config(state="normal")
        self.log_text.insert("end", f"{ts}  ", (fade_ts_tag,))
        self.log_text.insert("end", f"{msg}\n", (fade_msg_tag,))
        self.log_text.see("end")
        self.log_text.config(state="disabled")

        step = [0]
        def fade_tick():
            step[0] += 1
            t = min(step[0] / LOG_FADE_STEPS, 1.0)
            ts_color = _lerp_color(ts_bright, ts_target, t)
            msg_color = _lerp_color(msg_bright, target_color, t)
            try:
                self.log_text.tag_configure(fade_ts_tag, foreground=ts_color)
                self.log_text.tag_configure(fade_msg_tag, foreground=msg_color)
            except Exception:
                return
            if step[0] < LOG_FADE_STEPS:
                self.root.after(LOG_FADE_INTERVAL, fade_tick)
            else:
                try:
                    ts_ranges = self.log_text.tag_ranges(fade_ts_tag)
                    msg_ranges = self.log_text.tag_ranges(fade_msg_tag)
                    if ts_ranges:
                        self.log_text.tag_add("timestamp", ts_ranges[0], ts_ranges[1])
                    if msg_ranges:
                        self.log_text.tag_add(msg_tag, msg_ranges[0], msg_ranges[1])
                    self.log_text.tag_delete(fade_ts_tag)
                    self.log_text.tag_delete(fade_msg_tag)
                except Exception:
                    pass
        self.root.after(LOG_FADE_INTERVAL, fade_tick)

    def _clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    def _apply_env(self):
        if ENV_PATH.exists():
            for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")

    def _run_participants(self, tab):
        import api
        api.API_KEY = os.environ.get("BRELLA_API_KEY", "")
        api.ORG_ID = os.environ.get("BRELLA_ORG_ID", "1218")
        api.EVENT_ID = os.environ.get("BRELLA_EVENT_ID", "10672")
        downloading = tab.download_from_3cket.get()
        if downloading:
            csv_path = BASE_DIR / "data" / "participants.csv"
        else:
            csv_path = Path(tab.csv_path.get())
        api.prepare_csv(csv_path, download_csv=downloading, log_callback=self.log)
        result = api.run_sync_v4(
            csv_path, dry_run=tab.dry_run.get(),
            prune_missing=tab.prune.get(), log_callback=self.log,
        )
        if result:
            added_list = result.get("added_participants", [])
            updated_list = result.get("updated_participants", [])
            removed_list = result.get("removed_participants", [])
            missing_list = result.get("missing_email_participants", [])
            added = result.get("processed", 0) if tab.dry_run.get() else len(added_list)
            tab.update_summary(added=added, updated=len(updated_list),
                               removed=len(removed_list), missing=len(missing_list))
            tab.update_details(added=added_list, updated=updated_list,
                               removed=removed_list, missing=missing_list)

    def _run_speakers(self, tab):
        from speakers import run_speakers_sync
        csv_path = Path(tab.csv_path.get())
        result = run_speakers_sync(
            csv_path, dry_run=tab.dry_run.get(),
            prune_missing=tab.prune.get(), log_callback=self.log,
        )
        if result:
            added_list = result.get("added_participants", [])
            updated_list = result.get("updated_participants", [])
            removed_list = result.get("removed_participants", [])
            missing_list = result.get("missing_email_participants", [])
            added = result.get("processed", 0) if tab.dry_run.get() else len(added_list)
            tab.update_summary(added=added, updated=len(updated_list),
                               removed=len(removed_list), missing=len(missing_list))
            tab.update_details(added=added_list, updated=updated_list,
                               removed=removed_list, missing=missing_list)

    def _run_schedule(self, tab):
        from schedule_sync import run_schedule_sync
        csv_path = Path(tab.csv_path.get())
        result = run_schedule_sync(
            csv_path, dry_run=tab.dry_run.get(),
            prune_missing=tab.prune.get(), log_callback=self.log,
        )
        if result:
            added_list = result.get("added_participants", [])
            updated_list = result.get("updated_participants", [])
            removed_list = result.get("removed_participants", [])
            missing_list = result.get("unmatched_speakers", [])
            added = result.get("processed", 0) if tab.dry_run.get() else len(added_list)
            tab.update_summary(added=added, updated=len(updated_list),
                               removed=len(removed_list), missing=len(missing_list))
            tab.update_details(added=added_list, updated=updated_list,
                               removed=removed_list, missing=missing_list)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    App().run()
