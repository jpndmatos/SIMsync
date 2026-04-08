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
FONT_MONO = ("Consolas", 9)
FONT_TITLE = ("Poppins", 14, "bold")
FONT_SECTION = ("Poppins", 9, "bold")

CARD_PAD_X = 8
CARD_PAD_INNER = 8
CARD_PAD_Y_TOP = 5
CARD_PAD_Y_BOT = 5

SIDEBAR_W = 250
SIDEBAR_WIDTH_RATIO = 0.22

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
    tk.Label(parent, text=label, font=FONT_SMALL, fg=TEXT_SEC, bg=SURFACE,
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
    def __init__(self, parent, log_callback=None):
        self.log_callback = log_callback
        self.frame = tk.Frame(parent, bg=BG)

        P = 4  # grid gap

        # 3-column grid: API+Priority | Groups | Tickets
        self.frame.columnconfigure(0, weight=2)
        self.frame.columnconfigure(1, weight=1)
        self.frame.columnconfigure(2, weight=2)
        self.frame.rowconfigure(0, weight=1)

        # === Column 0: API config + Group Priority + Save ===
        col0 = tk.Frame(self.frame, bg=BG)
        col0.grid(row=0, column=0, sticky="nsew", padx=(P, P), pady=P)

        # -- Brella API card --
        api_card = tk.Frame(col0, bg=SURFACE, highlightbackground=SURFACE_RAISED,
                            highlightthickness=1)
        api_card.pack(fill="x", pady=(0, GAP))
        card_title(api_card, "BRELLA API")
        api_inner = tk.Frame(api_card, bg=SURFACE)
        api_inner.pack(fill="x", padx=CARD_PAD_INNER, pady=(0, CARD_PAD_Y_BOT))

        self.api_key = tk.StringVar(value=load_env_value("BRELLA_API_KEY"))
        self.org_id = tk.StringVar(value=load_env_value("BRELLA_ORG_ID"))
        self.event_id = tk.StringVar(value=load_env_value("BRELLA_EVENT_ID"))

        # Status pill
        api_status_row = tk.Frame(api_inner, bg=SURFACE)
        api_status_row.pack(fill="x", pady=(0, 2))
        api_loaded = bool(self.api_key.get())
        self._api_status_dot = tk.Frame(api_status_row,
                                        bg=SUCCESS if api_loaded else DANGER, width=7, height=7)
        self._api_status_dot.pack(side="left", padx=(0, 6), pady=3)
        self._api_status_dot.pack_propagate(False)
        self._api_status_lbl = tk.Label(api_status_row,
                                        text="API key loaded" if api_loaded else "API key not set",
                                        font=FONT_SMALL,
                                        fg=SUCCESS if api_loaded else DANGER, bg=SURFACE)
        self._api_status_lbl.pack(side="left")

        make_field(api_inner, "API Key", self.api_key, show="*")
        ids_row = tk.Frame(api_inner, bg=SURFACE)
        ids_row.pack(fill="x")
        ids_left = tk.Frame(ids_row, bg=SURFACE)
        ids_left.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ids_right = tk.Frame(ids_row, bg=SURFACE)
        ids_right.pack(side="right", fill="x", expand=True, padx=(4, 0))
        make_field(ids_left, "Org ID", self.org_id)
        make_field(ids_right, "Event ID", self.event_id)

        # Admin panel credentials
        tk.Frame(api_inner, bg=SURFACE_RAISED, height=1).pack(fill="x", pady=(2, 4))
        admin_hdr = tk.Frame(api_inner, bg=SURFACE)
        admin_hdr.pack(fill="x")
        tk.Label(admin_hdr, text="ADMIN PANEL", font=FONT_SECTION, fg=ACCENT,
                 bg=SURFACE, anchor="w").pack(side="left")
        tk.Label(admin_hdr, text="(stage sync)", font=FONT_SMALL, fg=TEXT_TER,
                 bg=SURFACE, anchor="w").pack(side="left", padx=(6, 0))

        self.admin_token = tk.StringVar(value=load_env_value("BRELLA_ADMIN_ACCESS_TOKEN"))
        self.admin_client = tk.StringVar(value=load_env_value("BRELLA_ADMIN_CLIENT"))
        self.admin_uid = tk.StringVar(value=load_env_value("BRELLA_ADMIN_UID"))

        make_field(api_inner, "Access Token", self.admin_token, show="*")
        admin_row = tk.Frame(api_inner, bg=SURFACE)
        admin_row.pack(fill="x")
        al = tk.Frame(admin_row, bg=SURFACE)
        al.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ar = tk.Frame(admin_row, bg=SURFACE)
        ar.pack(side="right", fill="x", expand=True, padx=(4, 0))
        make_field(al, "Client", self.admin_client)
        make_field(ar, "UID", self.admin_uid)

        # API buttons
        api_btns = tk.Frame(api_inner, bg=SURFACE)
        api_btns.pack(fill="x", pady=(0, 2))
        test_btn = tk.Button(api_btns, text="Test Connection", font=FONT_SMALL,
                             bg=SURFACE_RAISED, fg=TEXT_SEC,
                             activebackground="#2e2e38", activeforeground=TEXT,
                             relief="flat", cursor="hand2", pady=4,
                             command=self._test_connection)
        test_btn.pack(side="left", fill="x", expand=True, padx=(0, 3))
        save_api_btn = tk.Button(api_btns, text="Save", font=FONT_SMALL,
                                  bg=ACCENT, fg="white",
                                  activebackground=ACCENT_LIGHT, activeforeground="white",
                                  relief="flat", cursor="hand2", pady=4,
                                  command=self._save_api)
        save_api_btn.pack(side="left", fill="x", expand=True, padx=(3, 0))
        _bind_button_flash(test_btn, SURFACE_RAISED, "#2e2e38")
        _bind_button_flash(save_api_btn, ACCENT, ACCENT_LIGHT)

        self._api_status_var = tk.StringVar()
        self._api_status_result = tk.Label(api_inner, textvariable=self._api_status_var,
                                            font=FONT_SMALL, fg=TEXT_SEC, bg=SURFACE, anchor="w")

        # -- Group Priority card (fills remaining height) --
        priority_card = tk.Frame(col0, bg=SURFACE, highlightbackground=SURFACE_RAISED,
                                 highlightthickness=1)
        priority_card.pack(fill="both", expand=True, pady=(0, GAP))
        card_title(priority_card, "GROUP PRIORITY")
        priority_inner = tk.Frame(priority_card, bg=SURFACE)
        priority_inner.pack(fill="both", expand=True, padx=CARD_PAD_INNER,
                            pady=(0, CARD_PAD_Y_BOT))

        tk.Label(priority_inner, text="Top = highest priority.",
                 font=FONT_SMALL, fg=TEXT_TER, bg=SURFACE, anchor="w").pack(fill="x", pady=(0, 2))

        _, prio_scroll = _make_scroll_list(priority_inner)
        self._priority_frame = prio_scroll
        self._priority_rows = []

        import api
        for gid in api.GROUP_PRIORITY:
            self._add_priority_row(gid)

        tk.Button(priority_inner, text="+ Add", font=FONT_SMALL,
                  bg=SURFACE_RAISED, fg=TEXT_SEC,
                  activebackground=ACCENT, activeforeground="white",
                  relief="flat", cursor="hand2", pady=2,
                  command=lambda: self._add_priority_row("")).pack(anchor="w", pady=(2, 0))

        # Save Values button
        save_vals_btn = tk.Button(col0, text="Save Values", font=FONT_BOLD,
                                   bg=ACCENT, fg="white",
                                   activebackground=ACCENT_LIGHT, activeforeground="white",
                                   relief="flat", cursor="hand2", pady=6,
                                   command=self._save_values)
        save_vals_btn.pack(fill="x")
        _bind_button_flash(save_vals_btn, ACCENT, ACCENT_LIGHT)

        # === Column 1: Attendee Groups ===
        groups_card = tk.Frame(self.frame, bg=SURFACE, highlightbackground=SURFACE_RAISED,
                               highlightthickness=1)
        groups_card.grid(row=0, column=1, sticky="nsew", padx=(0, P), pady=P)
        card_title(groups_card, "ATTENDEE GROUPS")
        groups_inner = tk.Frame(groups_card, bg=SURFACE)
        groups_inner.pack(fill="both", expand=True, padx=CARD_PAD_INNER,
                          pady=(0, CARD_PAD_Y_BOT))

        hdr = tk.Frame(groups_inner, bg=SURFACE)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Name", font=FONT_SECTION, fg=TEXT_SEC, bg=SURFACE,
                 width=12, anchor="w").pack(side="left")
        tk.Label(hdr, text="ID", font=FONT_SECTION, fg=TEXT_SEC, bg=SURFACE,
                 anchor="w").pack(side="left", fill="x", expand=True)

        _, groups_scroll = _make_scroll_list(groups_inner)
        self._groups_frame = groups_scroll
        self._group_rows = []

        for name, gid in api.BRELLA_ATTENDEE_GROUP_IDS.items():
            self._add_group_row(name, gid)

        tk.Button(groups_inner, text="+ Add", font=FONT_SMALL,
                  bg=SURFACE_RAISED, fg=TEXT_SEC,
                  activebackground=ACCENT, activeforeground="white",
                  relief="flat", cursor="hand2", pady=2,
                  command=lambda: self._add_group_row("", "")).pack(anchor="w", pady=(2, 0))

        # === Column 2: Ticket Type Mappings ===
        tickets_card = tk.Frame(self.frame, bg=SURFACE, highlightbackground=SURFACE_RAISED,
                                highlightthickness=1)
        tickets_card.grid(row=0, column=2, sticky="nsew", padx=(0, P), pady=P)
        card_title(tickets_card, "TICKET TYPE MAPPINGS")
        tickets_inner = tk.Frame(tickets_card, bg=SURFACE)
        tickets_inner.pack(fill="both", expand=True, padx=CARD_PAD_INNER,
                           pady=(0, CARD_PAD_Y_BOT))

        hdr2 = tk.Frame(tickets_inner, bg=SURFACE)
        hdr2.pack(fill="x")
        tk.Label(hdr2, text="Ticket Type", font=FONT_SECTION, fg=TEXT_SEC, bg=SURFACE,
                 width=22, anchor="w").pack(side="left")
        tk.Label(hdr2, text="Group ID", font=FONT_SECTION, fg=TEXT_SEC, bg=SURFACE,
                 anchor="w").pack(side="left", fill="x", expand=True)

        _, tickets_scroll = _make_scroll_list(tickets_inner)
        self._tickets_frame = tickets_scroll
        self._ticket_rows = []

        for ttype, gid in api.TICKET_TYPE_TO_GROUP_ID.items():
            self._add_ticket_row(ttype, gid)

        tk.Button(tickets_inner, text="+ Add", font=FONT_SMALL,
                  bg=SURFACE_RAISED, fg=TEXT_SEC,
                  activebackground=ACCENT, activeforeground="white",
                  relief="flat", cursor="hand2", pady=2,
                  command=lambda: self._add_ticket_row("", "")).pack(anchor="w", pady=(2, 0))

    # --- Value row helpers ---

    def _make_entry(self, parent, value="", width=20):
        var = tk.StringVar(value=value)
        entry = tk.Entry(parent, textvariable=var, font=FONT_MONO, bg=BG, fg=TEXT,
                         insertbackground=TEXT, relief="flat", width=width,
                         highlightthickness=1, highlightbackground=SURFACE_RAISED,
                         highlightcolor=ACCENT)
        return entry, var

    def _make_del_btn(self, parent, command):
        btn = tk.Button(parent, text="\u2715", font=("Poppins", 8), bg=SURFACE, fg=TEXT_TER,
                        activebackground=DANGER, activeforeground="white",
                        relief="flat", cursor="hand2", bd=0, command=command)
        btn.bind("<Enter>", lambda e: btn.config(fg=DANGER))
        btn.bind("<Leave>", lambda e: btn.config(fg=TEXT_TER))
        return btn

    def _add_group_row(self, name, gid):
        row = tk.Frame(self._groups_frame, bg=SURFACE)
        row.pack(fill="x", pady=0)
        name_entry, name_var = self._make_entry(row, name, width=16)
        name_entry.pack(side="left", padx=(0, 4), ipady=1)
        id_entry, id_var = self._make_entry(row, gid, width=8)
        id_entry.pack(side="left", fill="x", expand=True, ipady=1)
        def remove():
            row.destroy()
            self._group_rows = [(r, n, i) for r, n, i in self._group_rows if r.winfo_exists()]
        self._make_del_btn(row, remove).pack(side="right", padx=(4, 0))
        self._group_rows.append((row, name_var, id_var))

    def _add_ticket_row(self, ttype, gid):
        row = tk.Frame(self._tickets_frame, bg=SURFACE)
        row.pack(fill="x", pady=0)
        type_entry, type_var = self._make_entry(row, ttype, width=30)
        type_entry.pack(side="left", padx=(0, 4), ipady=1)
        id_entry, id_var = self._make_entry(row, gid, width=8)
        id_entry.pack(side="left", fill="x", expand=True, ipady=1)
        def remove():
            row.destroy()
            self._ticket_rows = [(r, t, i) for r, t, i in self._ticket_rows if r.winfo_exists()]
        self._make_del_btn(row, remove).pack(side="right", padx=(4, 0))
        self._ticket_rows.append((row, type_var, id_var))

    def _add_priority_row(self, gid):
        row = tk.Frame(self._priority_frame, bg=SURFACE)
        row.pack(fill="x", pady=0)
        pos_label = tk.Label(row, text=str(len(self._priority_rows) + 1), font=FONT_SMALL,
                             fg=TEXT_TER, bg=SURFACE, width=3)
        pos_label.pack(side="left")
        entry, var = self._make_entry(row, gid, width=10)
        entry.pack(side="left", fill="x", expand=True, ipady=1)
        def remove():
            row.destroy()
            self._priority_rows = [(r, v) for r, v in self._priority_rows if r.winfo_exists()]
            self._renumber_priority()
        self._make_del_btn(row, remove).pack(side="right", padx=(4, 0))
        def move_up():
            idx = next((i for i, (r, v) in enumerate(self._priority_rows) if r == row), None)
            if idx and idx > 0:
                self._priority_rows[idx], self._priority_rows[idx - 1] = \
                    self._priority_rows[idx - 1], self._priority_rows[idx]
                self._repack_priority()
        def move_down():
            idx = next((i for i, (r, v) in enumerate(self._priority_rows) if r == row), None)
            if idx is not None and idx < len(self._priority_rows) - 1:
                self._priority_rows[idx], self._priority_rows[idx + 1] = \
                    self._priority_rows[idx + 1], self._priority_rows[idx]
                self._repack_priority()
        down_btn = tk.Button(row, text="\u25BC", font=("Poppins", 7), bg=SURFACE, fg=TEXT_TER,
                             activebackground=SURFACE_RAISED, activeforeground=TEXT,
                             relief="flat", cursor="hand2", bd=0, command=move_down)
        down_btn.pack(side="right", padx=1)
        up_btn = tk.Button(row, text="\u25B2", font=("Poppins", 7), bg=SURFACE, fg=TEXT_TER,
                           activebackground=SURFACE_RAISED, activeforeground=TEXT,
                           relief="flat", cursor="hand2", bd=0, command=move_up)
        up_btn.pack(side="right", padx=1)
        self._priority_rows.append((row, var))

    def _renumber_priority(self):
        for i, (row, var) in enumerate(self._priority_rows):
            if row.winfo_exists():
                for child in row.winfo_children():
                    if isinstance(child, tk.Label):
                        child.config(text=str(i + 1))
                        break

    def _repack_priority(self):
        for row, var in self._priority_rows:
            row.pack_forget()
        for row, var in self._priority_rows:
            row.pack(fill="x", pady=0)
        self._renumber_priority()

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
        groups = {}
        for row, name_var, id_var in self._group_rows:
            if not row.winfo_exists():
                continue
            name = name_var.get().strip()
            gid = id_var.get().strip()
            if name and gid:
                groups[name] = gid
        tickets = {}
        for row, type_var, id_var in self._ticket_rows:
            if not row.winfo_exists():
                continue
            ttype = type_var.get().strip()
            gid = id_var.get().strip()
            if ttype and gid:
                tickets[ttype] = gid
        priority = []
        for row, var in self._priority_rows:
            if not row.winfo_exists():
                continue
            gid = var.get().strip()
            if gid:
                priority.append(gid)
        api.save_config(
            attendee_groups=groups,
            group_priority=priority,
            ticket_type_to_group=tickets,
        )
        if self.log_callback:
            self.log_callback(
                f"Values saved — {len(groups)} groups, "
                f"{len(tickets)} ticket mappings, {len(priority)} priority entries"
            )


# --- Sync Tab ---

class SyncTab:
    def __init__(self, parent, name, description, has_prune=False, has_cookie=False,
                 run_func=None, enabled=True, app=None,
                 csv_header_example="", csv_delimiter=","):
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

        self.frame = tk.Frame(parent, bg=BG)

        inner_frame = tk.Frame(self.frame, bg=BG)
        inner_frame.pack(fill="x", side="top")

        tk.Frame(inner_frame, bg=BG, height=4).pack(fill="x")

        # CSV format card (description + header example)
        if description or csv_header_example:
            fmt_card = make_card(inner_frame)
            card_title(fmt_card, "CSV FORMAT")
            fmt_inner = tk.Frame(fmt_card, bg=SURFACE)
            fmt_inner.pack(fill="x", padx=CARD_PAD_INNER, pady=(0, CARD_PAD_Y_BOT))

            if description:
                tk.Label(fmt_inner, text=description, font=FONT_SMALL, fg=TEXT_SEC,
                         bg=SURFACE, anchor="w", justify="left",
                         wraplength=980).pack(fill="x", pady=(0, 4))

            if csv_delimiter:
                tk.Label(fmt_inner, text=f"Delimiter: {csv_delimiter}",
                         font=FONT_SMALL, fg=TEXT_TER, bg=SURFACE,
                         anchor="w").pack(fill="x", pady=(0, 2))

            if csv_header_example:
                tk.Label(fmt_inner, text="Header example:", font=FONT_SMALL,
                         fg=TEXT_SEC, bg=SURFACE, anchor="w").pack(fill="x")
                tk.Label(fmt_inner, text=csv_header_example, font=FONT_MONO,
                         fg=ACCENT_LIGHT, bg=SURFACE, anchor="w", justify="left",
                         wraplength=980).pack(fill="x", pady=(1, 0))

        # CSV picker
        csv_card = make_card(inner_frame)
        card_title(csv_card, "CSV FILE")
        csv_row = tk.Frame(csv_card, bg=SURFACE)
        csv_row.pack(fill="x", padx=CARD_PAD_INNER, pady=(0, CARD_PAD_Y_BOT))

        self.path_entry = tk.Entry(csv_row, textvariable=self.csv_path, font=FONT_MONO,
                                   bg=BG, fg=TEXT, insertbackground=TEXT,
                                   relief="flat", highlightthickness=1,
                                   highlightbackground=SURFACE_RAISED, highlightcolor=ACCENT)
        self.path_entry.pack(side="left", fill="x", expand=True, ipady=5)

        self.browse_btn = tk.Button(csv_row, text="Browse", font=FONT_SMALL, bg=SURFACE_RAISED,
                                    fg=TEXT, activebackground=ACCENT, activeforeground="white",
                                    relief="flat", cursor="hand2", padx=14, pady=5,
                                    command=self._browse)
        self.browse_btn.pack(side="right", padx=(8, 0))

        # Options card
        if has_prune or has_cookie:
            opts = make_card(inner_frame)
            card_title(opts, "OPTIONS")
            opts_inner = tk.Frame(opts, bg=SURFACE)
            opts_inner.pack(fill="x", padx=CARD_PAD_INNER, pady=(0, CARD_PAD_Y_BOT))
            if has_prune:
                self.prune_cb = tk.Checkbutton(opts_inner,
                                               text="Prune missing (remove from Brella if not in CSV)",
                                               variable=self.prune, font=FONT_SMALL,
                                               fg=TEXT_SEC, bg=SURFACE, selectcolor=BG,
                                               activebackground=SURFACE, activeforeground=TEXT,
                                               anchor="w")
                self.prune_cb.pack(fill="x")
            if has_cookie:
                self.dl_cb = tk.Checkbutton(opts_inner,
                                            text="Download CSV from 3cket instead of local file",
                                            variable=self.download_from_3cket, font=FONT_SMALL,
                                            fg=TEXT_SEC, bg=SURFACE, selectcolor=BG,
                                            activebackground=SURFACE, activeforeground=TEXT,
                                            anchor="w", command=self._toggle_source)
                self.dl_cb.pack(fill="x", pady=(4, 0))
                self.cookie_entry = make_field(opts_inner, "Session Cookie", self.cookie, show="*")

        # Action buttons
        btn_row = tk.Frame(inner_frame, bg=BG)
        btn_row.pack(fill="x", padx=CARD_PAD_X, pady=(0, GAP))
        self.preview_btn = tk.Button(btn_row, text="Preview", font=FONT_BOLD,
                                      bg=SURFACE_RAISED, fg=TEXT_SEC,
                                      activebackground="#2e2e38", activeforeground=TEXT,
                                      relief="flat", cursor="hand2", pady=7,
                                      command=lambda: self._run(dry_run=True))
        self.preview_btn.pack(side="left", fill="x", expand=True, padx=(0, 3))
        self.import_btn = tk.Button(btn_row, text="Import", font=FONT_BOLD,
                                     bg=ACCENT, fg="white",
                                     activebackground=ACCENT_LIGHT, activeforeground="white",
                                     relief="flat", cursor="hand2", pady=7,
                                     command=lambda: self._run(dry_run=False))
        self.import_btn.pack(side="left", fill="x", expand=True, padx=(3, 0))
        _bind_button_flash(self.preview_btn, SURFACE_RAISED, "#2e2e38")
        _bind_button_flash(self.import_btn, ACCENT, ACCENT_LIGHT)

        # Detail boxes: 2x2 grid
        detail_container = tk.Frame(self.frame, bg=BG)
        detail_container.pack(fill="both", expand=True, padx=CARD_PAD_X, pady=(0, CARD_PAD_X))
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

        if not enabled:
            self.browse_btn.config(state="disabled")
            self.path_entry.config(state="disabled")
            self.preview_btn.config(state="disabled")
            self.import_btn.config(state="disabled")

    def _make_unified_box(self, parent, title, value, color, row=0, col=0, copyable=False):
        outer = tk.Frame(parent, bg=SURFACE, highlightbackground=SURFACE_RAISED,
                         highlightthickness=1)
        padx = (0 if col == 0 else GAP, 0 if col == 1 else GAP)
        pady = (0 if row == 0 else GAP, 0 if row == 1 else GAP)
        outer.grid(row=row, column=col, sticky="nsew", padx=padx, pady=pady)
        outer.columnconfigure(0, weight=1)

        accent_line = tk.Frame(outer, bg=color, height=3)
        accent_line.grid(row=0, column=0, sticky="ew")

        header = tk.Frame(outer, bg=SURFACE)
        header.grid(row=1, column=0, sticky="ew")

        count_label = tk.Label(header, text=value, font=("Poppins", 18, "bold"),
                               fg=color, bg=SURFACE, anchor="w")
        count_label.pack(anchor="w", padx=8, pady=(4, 0))

        title_row = tk.Frame(header, bg=SURFACE)
        title_row.pack(fill="x", padx=9, pady=(0, 4))

        title_label = tk.Label(title_row, text=title, font=("Poppins", 8, "bold"),
                               fg=TEXT_TER, bg=SURFACE, anchor="w")
        title_label.pack(side="left")

        if copyable:
            copy_btn = tk.Button(title_row, text="Copy", font=("Poppins", 7),
                                 bg=SURFACE, fg=TEXT_TER,
                                 activebackground=SURFACE_RAISED, activeforeground=TEXT,
                                 relief="flat", cursor="hand2", bd=0,
                                 command=lambda: self._copy_listbox(lb))
            copy_btn.pack(side="right")
            copy_btn.bind("<Enter>", lambda e: copy_btn.config(fg=TEXT_SEC))
            copy_btn.bind("<Leave>", lambda e: copy_btn.config(fg=TEXT_TER))

        sep = tk.Frame(outer, bg=SURFACE_RAISED, height=1)
        sep.grid(row=2, column=0, sticky="ew")

        list_frame = tk.Frame(outer, bg=SURFACE)
        list_frame.grid(row=3, column=0, sticky="nsew")
        outer.rowconfigure(3, weight=1)
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        lb = tk.Listbox(list_frame, font=FONT_SMALL, bg=SURFACE, fg=TEXT_SEC,
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

        self._log_status_dot = tk.Frame(log_title_row, bg=TEXT_TER, width=7, height=7)
        self._log_status_dot.pack(side="left", padx=(0, 6), pady=1)
        self._log_status_dot.pack_propagate(False)
        self._log_status_pulse = StatusPulse(self._log_status_dot)

        self._log_status_var = tk.StringVar(value="Ready")
        self._log_status_label = tk.Label(log_title_row, textvariable=self._log_status_var,
                                           font=("Poppins", 9, "bold"), fg=TEXT_SEC, bg=SURFACE)
        self._log_status_label.pack(side="left")

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
        self.log_text = tk.Text(self._log_frame, font=("Consolas", 8), bg="#0c0c12", fg=TEXT_SEC,
                                relief="flat", wrap="word", insertbackground=ACCENT_LIGHT,
                                state="disabled", padx=6, pady=6)
        self.log_text.pack(fill="both", expand=True, padx=4, pady=(GAP, 4))

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
        setup = SetupTab(self.content, log_callback=self.log)
        self._setup_tab = setup
        self.panels["Setup"] = setup.frame

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

        for name, desc, prune, cookie, func, en, header_example, delimiter in [
            (
                "Participants",
                "Sync 3cket participants to Brella.",
                True,
                True,
                self._run_participants,
                True,
                (
                    "3cket_id [required]; name [full name]; phone; email [required]; "
                    "gender; birth_date [YYYY-MM-DD]; country; language; "
                    "check_in [in/out]; marketing_authorization [0/1]; "
                    "tickets [pipe-separated values]; total_tickets [int]; "
                    "email_fallback; company; group"
                ),
                ";",
            ),
            (
                "Speakers",
                "Sync published speakers to Brella.",
                True,
                False,
                self._run_speakers,
                True,
                (
                    "first_name [required], last_name [required], company, job_title, bio, "
                    "photo [URL], linkedin [URL], email [required], "
                    "token [optional external_id], publish [Publish or Do not publish]"
                ),
                ",",
            ),
            (
                "Sponsors",
                "Sync sponsor data to Brella.",
                False,
                False,
                None,
                False,
                "",
                ",",
            ),
            (
                "Schedule",
                "Sync event sessions to Brella.",
                True,
                False,
                self._run_schedule,
                True,
                (
                    "date [YYYY-MM-DD], start_time [HH:MM:SS], duration [int min], "
                    "title, content, track [predetermined tracks in ALL CAPS], "
                    "location, speakers [full names separated by \" / \"]"
                ),
                ",",
            ),
        ]:
            self._add_nav(sidebar, name)
            tab = SyncTab(self.content, name, desc, has_prune=prune, has_cookie=cookie,
                          run_func=func, enabled=en, app=self,
                          csv_header_example=header_example,
                          csv_delimiter=delimiter)
            tab._log_callback = self.log
            default_csv = _default_csvs.get(name)
            if default_csv and default_csv.exists():
                tab.csv_path.set(str(default_csv))
            self.panels[name] = tab.frame
            self._sync_tabs[name] = tab

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
