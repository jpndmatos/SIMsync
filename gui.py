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
    return Path(__file__).resolve().parent

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

CARD_PAD_X = 24
CARD_PAD_INNER = 12
CARD_PAD_Y_TOP = 10
CARD_PAD_Y_BOT = 12

# Sidebar width
SIDEBAR_W = 210

# Nav icon mapping (unicode glyphs)
NAV_ICONS = {
    "Setup": "\u2699",        # gear
    "Participants": "\u2630",  # trigram / list
    "Speakers": "\u266A",     # music note (mic-like)
    "Sponsors": "\u2302",     # house / building
    "Schedule": "\u2637",     # trigram / calendar-like
}

APP_VERSION = "v1.0"

# --- Animation constants ---
ANIM_INTERVAL = 16       # ~60fps
NAV_ANIM_STEPS = 10      # steps for nav hover/active transitions
BUTTON_FLASH_MS = 120    # button press flash duration
PULSE_INTERVAL = 40      # status dot pulse tick interval
PULSE_STEPS = 30         # steps per half-cycle of pulse
LOG_FADE_STEPS = 8       # steps for log line fade-in
LOG_FADE_INTERVAL = 30   # ms between log fade steps
INDICATOR_ANIM_STEPS = 8 # steps for accent bar height animation


# --- Color interpolation helpers ---

def _hex_to_rgb(hex_color):
    """Convert '#rrggbb' to (r, g, b) tuple."""
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _rgb_to_hex(r, g, b):
    """Convert (r, g, b) to '#rrggbb'."""
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


def _lerp_color(color_a, color_b, t):
    """Linearly interpolate between two hex colors. t in [0, 1]."""
    t = max(0.0, min(1.0, t))
    ra, ga, ba = _hex_to_rgb(color_a)
    rb, gb, bb = _hex_to_rgb(color_b)
    return _rgb_to_hex(
        ra + (rb - ra) * t,
        ga + (gb - ga) * t,
        ba + (bb - ba) * t,
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


# --- Card helpers ---

def make_card(parent):
    card = tk.Frame(parent, bg=SURFACE, highlightbackground=SURFACE_RAISED, highlightthickness=1)
    card.pack(fill="x", padx=CARD_PAD_X, pady=(0, 6))
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
    entry.pack(fill="x", ipady=5, pady=(2, 8))
    return entry


# --- Scrollable frame wrapper ---

class ScrollableFrame:
    """A frame inside a canvas that supports vertical scrolling via mousewheel."""

    def __init__(self, parent):
        self.canvas = tk.Canvas(parent, bg=BG, highlightthickness=0, borderwidth=0)
        self.frame = tk.Frame(self.canvas, bg=BG)

        self.frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self.canvas_window = self.canvas.create_window((0, 0), window=self.frame, anchor="nw")

        self.canvas.pack(side="left", fill="both", expand=True)

        # Bind mousewheel on all platforms
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


# --- Setup Tab ---

class SetupTab:
    def __init__(self, parent, log_callback=None):
        self.log_callback = log_callback
        self.frame = tk.Frame(parent, bg=BG)

        # Scrollable wrapper
        scroller = ScrollableFrame(self.frame)
        inner_frame = scroller.frame

        tk.Frame(inner_frame, bg=BG, height=20).pack(fill="x")

        # Brella card
        card = make_card(inner_frame)
        card_title(card, "BRELLA API")
        inner = tk.Frame(card, bg=SURFACE)
        inner.pack(fill="x", padx=CARD_PAD_INNER, pady=(0, CARD_PAD_Y_BOT))

        self.api_key = tk.StringVar(value=load_env_value("BRELLA_API_KEY"))
        self.org_id = tk.StringVar(value=load_env_value("BRELLA_ORG_ID"))
        self.event_id = tk.StringVar(value=load_env_value("BRELLA_EVENT_ID"))

        # API status pill
        api_status_row = tk.Frame(inner, bg=SURFACE)
        api_status_row.pack(fill="x", pady=(0, 8))
        api_loaded = bool(self.api_key.get())
        self._api_status_dot = tk.Frame(api_status_row, bg=SUCCESS if api_loaded else DANGER,
                                        width=7, height=7)
        self._api_status_dot.pack(side="left", padx=(0, 6), pady=3)
        self._api_status_dot.pack_propagate(False)
        self._api_status_lbl = tk.Label(api_status_row,
                                        text="API key loaded from .env" if api_loaded else "API key not set",
                                        font=FONT_SMALL, fg=SUCCESS if api_loaded else DANGER, bg=SURFACE)
        self._api_status_lbl.pack(side="left")

        make_field(inner, "API Key", self.api_key, show="*")
        row = tk.Frame(inner, bg=SURFACE)
        row.pack(fill="x")
        left = tk.Frame(row, bg=SURFACE)
        left.pack(side="left", fill="x", expand=True, padx=(0, 4))
        right = tk.Frame(row, bg=SURFACE)
        right.pack(side="right", fill="x", expand=True, padx=(4, 0))
        make_field(left, "Org ID", self.org_id)
        make_field(right, "Event ID", self.event_id)

        # Admin credentials card (for Tags endpoint)
        tk.Frame(inner_frame, bg=SURFACE_RAISED, height=1).pack(
            fill="x", padx=CARD_PAD_X, pady=(12, 16))

        admin_card = make_card(inner_frame)
        card_title(admin_card, "BRELLA ADMIN SESSION  —  Tags sync")
        admin_inner = tk.Frame(admin_card, bg=SURFACE)
        admin_inner.pack(fill="x", padx=CARD_PAD_INNER, pady=(0, CARD_PAD_Y_BOT))

        # How-to instructions — one label per step so wrapping never breaks indentation
        tk.Label(admin_inner,
                 text="Needed to load your event's tags. Expire in ~2 weeks — refresh when tags stop loading.",
                 font=FONT_SMALL, fg=TEXT_TER, bg=SURFACE, justify="left", anchor="w"
                 ).pack(fill="x", pady=(0, 6))

        steps_frame = tk.Frame(admin_inner, bg=SURFACE)
        steps_frame.pack(fill="x", pady=(0, 10))
        for step in [
            "1.  Open manager.brella.io → Schedule → Tags",
            "2.  DevTools (F12) → Network tab → reload the page",
            "3.  Click the request to api.brella.io/api/admin_panel/…/tags",
            "4.  Copy access-token, client and uid from Request Headers",
        ]:
            tk.Label(steps_frame, text=step, font=FONT_SMALL, fg=TEXT_TER, bg=SURFACE,
                     anchor="w").pack(fill="x", pady=1)

        self.admin_token = tk.StringVar(value=load_env_value("BRELLA_ADMIN_ACCESS_TOKEN"))
        self.admin_client = tk.StringVar(value=load_env_value("BRELLA_ADMIN_CLIENT"))
        self.admin_uid = tk.StringVar(value=load_env_value("BRELLA_ADMIN_UID"))

        # Status pill: shows whether tokens are currently loaded from .env
        token_status_row = tk.Frame(admin_inner, bg=SURFACE)
        token_status_row.pack(fill="x", pady=(0, 8))
        all_set = all([self.admin_token.get(), self.admin_client.get(), self.admin_uid.get()])
        dot_color = SUCCESS if all_set else TEXT_TER
        status_text = "Tokens loaded from .env" if all_set else "Tokens not set"
        status_fg = SUCCESS if all_set else TEXT_TER
        self._admin_status_dot = tk.Frame(token_status_row, bg=dot_color, width=7, height=7)
        self._admin_status_dot.pack(side="left", padx=(0, 6), pady=3)
        self._admin_status_dot.pack_propagate(False)
        self._admin_status_lbl = tk.Label(token_status_row, text=status_text,
                                          font=FONT_SMALL, fg=status_fg, bg=SURFACE)
        self._admin_status_lbl.pack(side="left")

        make_field(admin_inner, "access-token", self.admin_token, show="*")
        make_field(admin_inner, "client", self.admin_client, show="*")
        make_field(admin_inner, "uid  (your login email)", self.admin_uid)

        # Action buttons row: Save + Test Connection
        actions = tk.Frame(inner_frame, bg=BG)
        actions.pack(fill="x", padx=CARD_PAD_X, pady=(16, 0))

        self._save_btn = tk.Button(actions, text="Save", font=FONT_BOLD, bg=ACCENT, fg="white",
                  activebackground=ACCENT_LIGHT, activeforeground="white",
                  relief="flat", cursor="hand2", padx=24, pady=8,
                  command=self._save)
        self._save_btn.pack(side="left", padx=(0, 8))

        self._test_btn = tk.Button(actions, text="Test Connection", font=FONT_BOLD,
                  bg=SURFACE_RAISED, fg=TEXT,
                  activebackground=SURFACE, activeforeground=TEXT_SEC,
                  relief="flat", cursor="hand2", padx=24, pady=8,
                  highlightthickness=1, highlightbackground=TEXT_TER,
                  command=self._test_connection)
        self._test_btn.pack(side="left")

        # Button press feedback
        _bind_button_flash(self._save_btn, ACCENT, ACCENT_LIGHT)
        _bind_button_flash(self._test_btn, SURFACE_RAISED, "#2e2e38")

        self.status_var = tk.StringVar(value="")
        self.status_label = tk.Label(inner_frame, textvariable=self.status_var, font=FONT_SMALL,
                                     fg=TEXT_SEC, bg=BG, anchor="w", padx=4, pady=6)
        self.status_label.pack(fill="x", padx=CARD_PAD_X, pady=(8, 0))

    def _save(self):
        save_env_values({
            "BRELLA_API_KEY": self.api_key.get().strip(),
            "BRELLA_ORG_ID": self.org_id.get().strip(),
            "BRELLA_EVENT_ID": self.event_id.get().strip(),
            "BRELLA_ADMIN_ACCESS_TOKEN": self.admin_token.get().strip(),
            "BRELLA_ADMIN_CLIENT": self.admin_client.get().strip(),
            "BRELLA_ADMIN_UID": self.admin_uid.get().strip(),
        })
        # Also update os.environ so it's picked up without restart
        os.environ["BRELLA_API_KEY"] = self.api_key.get().strip()
        os.environ["BRELLA_ORG_ID"] = self.org_id.get().strip()
        os.environ["BRELLA_EVENT_ID"] = self.event_id.get().strip()
        os.environ["BRELLA_ADMIN_ACCESS_TOKEN"] = self.admin_token.get().strip()
        os.environ["BRELLA_ADMIN_CLIENT"] = self.admin_client.get().strip()
        os.environ["BRELLA_ADMIN_UID"] = self.admin_uid.get().strip()

        self.status_var.set("Saved to .env")
        self.status_label.config(fg=SUCCESS)

        # Update API status pill
        api_ok = bool(self.api_key.get().strip())
        self._api_status_dot.config(bg=SUCCESS if api_ok else DANGER)
        self._api_status_lbl.config(
            text="API key loaded from .env" if api_ok else "API key not set",
            fg=SUCCESS if api_ok else DANGER,
        )

        # Update admin token status pill
        all_set = all([self.admin_token.get().strip(), self.admin_client.get().strip(),
                       self.admin_uid.get().strip()])
        self._admin_status_dot.config(bg=SUCCESS if all_set else TEXT_TER)
        self._admin_status_lbl.config(
            text="Tokens loaded from .env" if all_set else "Tokens not set",
            fg=SUCCESS if all_set else TEXT_TER,
        )

        if self.log_callback:
            self.log_callback("Setup saved to .env")

    def _test_connection(self):
        self.status_var.set("Test connection not yet implemented.")
        self.status_label.config(fg=WARN)
        if self.log_callback:
            self.log_callback("[INFO] Test connection placeholder — not yet implemented.")


# --- Button press flash helper ---

def _bind_button_flash(btn, rest_color, flash_color):
    """Bind a brief color flash on button press for tactile feedback."""
    def on_press(e):
        btn.config(bg=flash_color)
        btn.after(BUTTON_FLASH_MS, lambda: btn.config(bg=rest_color))
    btn.bind("<ButtonPress-1>", on_press, add="+")


# --- Status dot pulse animation ---

class StatusPulse:
    """Animates a status dot between two colors in a loop while active."""

    def __init__(self, widget):
        self.widget = widget
        self._running = False
        self._step = 0
        self._forward = True
        self._color_a = ACCENT_LIGHT
        self._color_b = TEXT_TER
        self._after_id = None

    def start(self, color_a=ACCENT_LIGHT, color_b=None):
        """Begin pulsing between color_a and a dimmed version."""
        if self._running:
            return
        self._color_a = color_a
        self._color_b = color_b or _lerp_color(color_a, BG, 0.6)
        self._running = True
        self._step = 0
        self._forward = True
        self._tick()

    def stop(self, final_color=None):
        """Stop pulsing and set a final color."""
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


# --- Sync Tab ---

class SyncTab:
    def __init__(self, parent, name, description, has_prune=False, has_cookie=False,
                 run_func=None, enabled=True):
        self.name = name
        self.run_func = run_func
        self.enabled = enabled
        self.csv_path = tk.StringVar()
        self.dry_run = tk.BooleanVar(value=False)
        self.prune = tk.BooleanVar(value=True)
        self.has_prune = has_prune
        self.has_cookie = has_cookie
        self.download_from_3cket = tk.BooleanVar(value=False)
        self.cookie = tk.StringVar(value=load_env_value("THREECKET_COOKIE"))
        self.running = False

        self.frame = tk.Frame(parent, bg=BG)

        # Top form section — plain frame (no scroll; fits fine on maximized window)
        inner_frame = tk.Frame(self.frame, bg=BG)
        inner_frame.pack(fill="x", side="top")

        tk.Frame(inner_frame, bg=BG, height=20).pack(fill="x")

        # CSV picker
        csv_card = make_card(inner_frame)
        card_title(csv_card, "CSV FILE")
        csv_row = tk.Frame(csv_card, bg=SURFACE)
        csv_row.pack(fill="x", padx=CARD_PAD_INNER, pady=(0, CARD_PAD_Y_BOT))

        self.path_entry = tk.Entry(csv_row, textvariable=self.csv_path, font=FONT_MONO,
                                   bg=BG, fg=TEXT, insertbackground=TEXT,
                                   relief="flat", highlightthickness=1,
                                   highlightbackground=SURFACE_RAISED,
                                   highlightcolor=ACCENT)
        self.path_entry.pack(side="left", fill="x", expand=True, ipady=5)

        self.browse_btn = tk.Button(csv_row, text="Browse", font=FONT_SMALL, bg=SURFACE_RAISED,
                                    fg=TEXT, activebackground=ACCENT, activeforeground="white",
                                    relief="flat", cursor="hand2", padx=14, pady=5,
                                    command=self._browse)
        self.browse_btn.pack(side="right", padx=(8, 0))

        # Options card — shown when there are prune or 3cket options
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

        # Action row: Preview (ghost) + Import (solid)
        actions = tk.Frame(inner_frame, bg=BG)
        actions.pack(fill="x", padx=CARD_PAD_X, pady=(6, 0))

        btn_pady = 8

        self.preview_btn = tk.Button(actions, text="Preview", font=FONT_BOLD,
                                     bg=SURFACE_RAISED, fg=TEXT_SEC,
                                     activebackground="#2e2e38", activeforeground=TEXT,
                                     relief="flat", cursor="hand2", padx=20, pady=btn_pady,
                                     command=lambda: self._run(dry_run=True))
        self.preview_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.import_btn = tk.Button(actions, text="Import", font=FONT_BOLD,
                                    bg=ACCENT, fg="white",
                                    activebackground=ACCENT_LIGHT, activeforeground="white",
                                    relief="flat", cursor="hand2", padx=20, pady=btn_pady,
                                    command=lambda: self._run(dry_run=False))
        self.import_btn.pack(side="left", fill="x", expand=True, padx=(4, 0))

        # Button press feedback
        _bind_button_flash(self.preview_btn, SURFACE_RAISED, "#2e2e38")
        _bind_button_flash(self.import_btn, ACCENT, ACCENT_LIGHT)

        # Status badge
        status_row = tk.Frame(inner_frame, bg=BG)
        status_row.pack(fill="x", padx=CARD_PAD_X, pady=(6, 8))

        self.status_dot = tk.Frame(status_row, bg=TEXT_TER, width=7, height=7)
        self.status_dot.pack(side="left", padx=(4, 8), pady=1)
        self.status_dot.pack_propagate(False)

        # Pulse animator for status dot
        self._pulse = StatusPulse(self.status_dot)

        self.status_var = tk.StringVar(value="Ready")
        self.status_label = tk.Label(status_row, textvariable=self.status_var, font=FONT_SMALL,
                                     fg=TEXT_TER, bg=BG, anchor="w")
        self.status_label.pack(side="left")

        # --- Detail boxes: 2x2 grid packed directly in self.frame ---
        detail_container = tk.Frame(self.frame, bg=BG)
        detail_container.pack(fill="both", expand=True, padx=CARD_PAD_X, pady=(0, 14))
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
            detail_container, "MISSING INFO", "0", WARN, row=1, col=1)

        if not enabled:
            self.preview_btn.config(state="disabled")
            self.import_btn.config(state="disabled")
            self.browse_btn.config(state="disabled")
            self.path_entry.config(state="disabled")

    def _make_unified_box(self, parent, title, value, color, row=0, col=0):
        """Create a unified card: colored accent bar on top, header with title+count, list below."""
        outer = tk.Frame(parent, bg=SURFACE, highlightbackground=SURFACE_RAISED,
                         highlightthickness=1)
        padx = (0 if col == 0 else 3, 0 if col == 1 else 3)
        pady = (0 if row == 0 else 3, 0 if row == 1 else 3)
        outer.grid(row=row, column=col, sticky="nsew", padx=padx, pady=pady)
        outer.columnconfigure(0, weight=1)

        # Row 0: Thin colored accent bar at very top
        accent_line = tk.Frame(outer, bg=color, height=3)
        accent_line.grid(row=0, column=0, sticky="ew")

        # Row 1: Header — count (large, left) and title label (small, below count)
        header = tk.Frame(outer, bg=SURFACE)
        header.grid(row=1, column=0, sticky="ew")

        count_label = tk.Label(header, text=value, font=("Poppins", 28, "bold"),
                               fg=color, bg=SURFACE, anchor="w")
        count_label.pack(anchor="w", padx=12, pady=(10, 0))

        title_label = tk.Label(header, text=title, font=("Poppins", 8, "bold"),
                               fg=TEXT_TER, bg=SURFACE, anchor="w")
        title_label.pack(anchor="w", padx=13, pady=(0, 8))

        # Row 2: Separator
        sep = tk.Frame(outer, bg=SURFACE_RAISED, height=1)
        sep.grid(row=2, column=0, sticky="ew")

        # Row 3: List — fills remaining space; items in neutral TEXT_SEC, not the accent color
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
        """Enable/disable CSV picker based on download toggle."""
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

        # Save cookie to env if provided
        if self.has_cookie and self.cookie.get().strip():
            os.environ["THREECKET_COOKIE"] = self.cookie.get().strip()
            save_env_values({"THREECKET_COOKIE": self.cookie.get().strip()})

        self.dry_run.set(dry_run)
        self.running = True
        self._set_busy(True)
        mode = "preview" if dry_run else "import"
        self._set_status(f"Running {mode}...", ACCENT_LIGHT)
        # Start pulsing the status dot
        self._pulse.start(ACCENT_LIGHT)

        thread = threading.Thread(target=self._run_thread, daemon=True)
        thread.start()

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
            self._pulse.stop()
            self.frame.after(0, lambda: self._set_busy(False))

    def _set_busy(self, busy):
        state = "disabled" if busy else "normal"
        self.preview_btn.config(state=state)
        self.import_btn.config(state=state)
        if not (self.has_cookie and self.download_from_3cket.get()):
            self.browse_btn.config(state=state)

    def _set_status(self, text, color=TEXT_TER):
        def _update():
            self.status_var.set(text)
            self.status_label.config(fg=color)
            # Only set dot color directly when not pulsing
            if not self._pulse._running:
                self.status_dot.config(bg=color)
            else:
                # Stop pulse and set final color
                self._pulse.stop(final_color=color)
        self.frame.after(0, _update)

    def _log(self, msg):
        if hasattr(self, '_log_callback') and self._log_callback:
            self.frame.after(0, lambda: self._log_callback(msg))


# --- App ---

def _apply_dark_title_bar(root):
    """Enable dark title bar on Windows 10/11 via DWM API."""
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
        self.root.state("zoomed")  # start maximized
        _apply_dark_title_bar(self.root)

        # Set window icon
        try:
            png_path = BASE_DIR / "assets" / "SIMlogo.png"
            if png_path.exists():
                self._icon_img = tk.PhotoImage(file=str(png_path))
                self.root.iconphoto(True, self._icon_img)
        except Exception:
            pass

        # Track pending nav animations to cancel on rapid switching
        self._nav_anim_ids = {}
        # Track pending indicator animations
        self._ind_anim_ids = {}
        # Log fade-in animation counter (for unique tag names)
        self._log_fade_counter = 0

        # Main layout: sidebar left, right side split content/log
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="both", expand=True)

        # Sidebar
        sidebar = tk.Frame(outer, bg=SURFACE, width=SIDEBAR_W)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        # Brand area with logo
        brand = tk.Frame(sidebar, bg=SURFACE)
        brand.pack(fill="x", padx=16, pady=(18, 8))

        self._logo_img = None
        try:
            png_path = BASE_DIR / "assets" / "SIMlogo.png"
            if png_path.exists():
                raw = tk.PhotoImage(file=str(png_path))
                orig_w = raw.width()
                factor = max(1, orig_w // 160)
                self._logo_img = raw.subsample(factor, factor)
                tk.Label(brand, image=self._logo_img, bg=SURFACE).pack(anchor="w")
        except Exception:
            tk.Label(brand, text="SIMconference2Brella", font=("Poppins", 12, "bold"),
                     fg=TEXT, bg=SURFACE).pack(anchor="w")

        sep = tk.Frame(sidebar, bg=SURFACE_RAISED, height=1)
        sep.pack(fill="x", padx=16, pady=(12, 12))

        # Nav
        self.nav_buttons = []
        self.nav_indicators = []
        self.panels = {}
        self.active_panel = None
        # Track current bg color per nav button for smooth interpolation
        self._nav_current_bg = {}
        self._nav_current_fg = {}
        self._nav_hovered = {}

        # Right side: content (left) + log (right)
        right = tk.PanedWindow(outer, orient="horizontal", bg=SURFACE_RAISED,
                               sashwidth=2, sashrelief="flat")
        right.pack(side="left", fill="both", expand=True)

        # Content area
        self.content = tk.Frame(right, bg=BG)
        right.add(self.content, stretch="always", sticky="nsew")

        # Log panel
        log_frame = tk.Frame(right, bg=SURFACE)
        right.add(log_frame, stretch="always", sticky="nsew")

        # Set initial sash position after window renders
        def set_sash():
            w = right.winfo_width()
            if w > 100:
                # Log gets a fixed 680px; content fills the rest
                right.sash_place(0, max(300, int(w * 0.67)), 0)
        self.root.after(300, set_sash)

        # Log header
        log_header = tk.Frame(log_frame, bg=SURFACE)
        log_header.pack(fill="x", padx=0, pady=0)

        log_title_row = tk.Frame(log_header, bg=SURFACE)
        log_title_row.pack(fill="x", padx=14, pady=(10, 0))

        # Log icon + title
        tk.Label(log_title_row, text="\u2261", font=("Poppins", 12, "bold"), fg=TEXT_TER,
                 bg=SURFACE).pack(side="left", padx=(0, 6))
        tk.Label(log_title_row, text="Activity Log", font=("Poppins", 10, "bold"), fg=TEXT_SEC,
                 bg=SURFACE).pack(side="left")

        clear_btn = tk.Button(log_title_row, text="Clear", font=("Poppins", 8),
                              bg=SURFACE, fg=TEXT_TER,
                              activebackground=SURFACE_RAISED, activeforeground=TEXT,
                              relief="flat", cursor="hand2", bd=0,
                              command=self._clear_log)
        clear_btn.pack(side="right")

        clear_btn.bind("<Enter>", lambda e: clear_btn.config(fg=TEXT_SEC))
        clear_btn.bind("<Leave>", lambda e: clear_btn.config(fg=TEXT_TER))

        log_sep = tk.Frame(log_header, bg=SURFACE_RAISED, height=1)
        log_sep.pack(fill="x", padx=10, pady=(6, 0))

        # Log text widget with color tags
        self.log_text = tk.Text(log_frame, font=FONT_MONO, bg="#0c0c12", fg=TEXT_SEC,
                                relief="flat", wrap="word", insertbackground=ACCENT_LIGHT,
                                state="disabled", padx=12, pady=8)
        self.log_text.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        # Configure text tags for log colorization
        self.log_text.tag_configure("timestamp", foreground=TEXT_TER)
        self.log_text.tag_configure("msg_default", foreground=TEXT_SEC)
        self.log_text.tag_configure("msg_ok", foreground=SUCCESS)
        self.log_text.tag_configure("msg_error", foreground=DANGER)
        self.log_text.tag_configure("msg_warn", foreground=WARN)
        self.log_text.tag_configure("msg_preview", foreground=ACCENT)
        self.log_text.tag_configure("msg_info", foreground=TEXT_SEC)

        # --- Setup nav + tab ---
        self._add_nav(sidebar, "Setup")
        setup = SetupTab(self.content, log_callback=self.log)
        self.panels["Setup"] = setup.frame

        nav_sep = tk.Frame(sidebar, bg=SURFACE_RAISED, height=1)
        nav_sep.pack(fill="x", padx=16, pady=(8, 8))
        tk.Label(sidebar, text="SYNC MODULES", font=("Poppins", 7, "bold"),
                 fg=TEXT_TER, bg=SURFACE).pack(fill="x", padx=18, pady=(0, 6))

        # --- Sync tabs ---
        for name, desc, prune, cookie, func, en in [
            ("Participants", "Sync 3cket participants to Brella.", True, True,
             self._run_participants, True),
            ("Speakers", "Sync published speakers to Brella.", True, False,
             self._run_speakers, True),
            ("Sponsors", "Sync sponsor data to Brella.", False, False, None, False),
            ("Schedule", "Sync event sessions to Brella.", True, False,
             self._run_schedule, True),
        ]:
            self._add_nav(sidebar, name)
            tab = SyncTab(self.content, name, desc, has_prune=prune, has_cookie=cookie,
                          run_func=func, enabled=en)
            tab._log_callback = self.log
            self.panels[name] = tab.frame

        self._switch_panel("Setup")
        self._apply_env()
        self.root.after(600, self._prefetch_tags)

    def _add_nav(self, sidebar, name):
        row = tk.Frame(sidebar, bg=SURFACE)
        row.pack(fill="x", padx=0, pady=1)

        # Left accent indicator
        indicator = tk.Frame(row, bg=SURFACE, width=3)
        indicator.pack(side="left", fill="y")
        indicator.pack_propagate(False)

        btn = tk.Button(row, text=name, font=FONT, fg=TEXT_SEC, bg=SURFACE,
                        activebackground=SURFACE_RAISED, activeforeground=TEXT,
                        relief="flat", anchor="w", padx=14, pady=9, cursor="hand2",
                        command=lambda n=name: self._switch_panel(n))
        btn.pack(side="left", fill="x", expand=True)

        # Initialize tracking state
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
        """Smoothly interpolate a nav button's bg and fg color."""
        # Cancel any pending animation for this nav item
        if name in self._nav_anim_ids and self._nav_anim_ids[name] is not None:
            try:
                self.root.after_cancel(self._nav_anim_ids[name])
            except Exception:
                pass
            self._nav_anim_ids[name] = None

        start_bg = self._nav_current_bg.get(name, SURFACE)
        start_fg = self._nav_current_fg.get(name, TEXT_SEC)

        # Find the btn and row for this name
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
            # Ease-out quad
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

    def _animate_indicator_height(self, name, color):
        pass  # indicator is a plain Frame; color set directly in _switch_panel

    def _switch_panel(self, name):
        prev = self.active_panel
        self.active_panel = name
        for panel_name, frame in self.panels.items():
            if panel_name == name:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()

        # Animate nav buttons
        for btn_name, btn, row in self.nav_buttons:
            if btn_name == name:
                self._animate_nav(btn_name, target_bg=SURFACE_RAISED, target_fg=ACCENT_LIGHT)
            else:
                # Only animate back to rest if not hovered
                if not self._nav_hovered.get(btn_name, False):
                    self._animate_nav(btn_name, target_bg=SURFACE, target_fg=TEXT_SEC)
                else:
                    self._animate_nav(btn_name, target_bg=SURFACE_RAISED, target_fg=TEXT)

        # Update indicators
        for ind_name, indicator in self.nav_indicators:
            indicator.config(bg=ACCENT if ind_name == name else SURFACE)

    def log(self, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S")

        # Determine message color tag based on content
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

        # Get the target color for this tag to use as fade destination
        tag_info = self.log_text.tag_cget(msg_tag, "foreground")
        target_color = tag_info if tag_info else TEXT_SEC

        # Create unique fade tags for this log entry
        self._log_fade_counter += 1
        fade_ts_tag = f"_fade_ts_{self._log_fade_counter}"
        fade_msg_tag = f"_fade_msg_{self._log_fade_counter}"

        # Bright start colors for fade-in
        ts_target = TEXT_TER
        ts_bright = _lerp_color(ts_target, TEXT, 0.7)
        msg_bright = _lerp_color(target_color, TEXT, 0.5)

        # Configure initial bright tags
        self.log_text.tag_configure(fade_ts_tag, foreground=ts_bright)
        self.log_text.tag_configure(fade_msg_tag, foreground=msg_bright)

        self.log_text.config(state="normal")
        self.log_text.insert("end", f"{ts}  ", (fade_ts_tag,))
        self.log_text.insert("end", f"{msg}\n", (fade_msg_tag,))
        self.log_text.see("end")
        self.log_text.config(state="disabled")

        # Animate fade: bright -> target color
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
                # Replace fade tags with permanent tags to avoid tag buildup
                try:
                    # Get ranges for the fade tags
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
        """Force-load all .env values into os.environ and log active config."""
        if ENV_PATH.exists():
            for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")

        event_id = os.environ.get("BRELLA_EVENT_ID", "—")
        org_id = os.environ.get("BRELLA_ORG_ID", "—")
        api_set = bool(os.environ.get("BRELLA_API_KEY"))
        admin_set = bool(os.environ.get("BRELLA_ADMIN_ACCESS_TOKEN"))
        self.log(f"SIMconference2Brella ready — event {event_id} / org {org_id}")
        self.log(f"[INFO] API key: {'set' if api_set else 'NOT SET'}  |  Admin tokens: {'set' if admin_set else 'NOT SET'}")

    def _prefetch_tags(self):
        if not os.environ.get("BRELLA_API_KEY"):
            return  # Not configured yet — skip silently
        threading.Thread(target=self._prefetch_tags_thread, daemon=True).start()

    def _prefetch_tags_thread(self):
        try:
            from schedule_sync import prefetch_tags
            prefetch_tags(log_callback=self.log)
        except Exception as exc:
            self.log(f"[WARN] Tags prefetch failed: {exc}")

    def _run_participants(self, tab):
        # Reload api.py module-level vars from current env
        import api
        api.API_KEY = os.environ.get("BRELLA_API_KEY", "")
        api.ORG_ID = os.environ.get("BRELLA_ORG_ID", "1218")
        api.EVENT_ID = os.environ.get("BRELLA_EVENT_ID", "10672")

        downloading = tab.download_from_3cket.get()
        if downloading:
            csv_path = BASE_DIR / "participants.csv"
        else:
            csv_path = Path(tab.csv_path.get())

        api.prepare_csv(csv_path, download_csv=downloading, log_callback=self.log)
        result = api.run_sync_v4(
            csv_path,
            dry_run=tab.dry_run.get(),
            prune_missing=tab.prune.get(),
            log_callback=self.log,
        )

        if result:
            added_list = result.get("added_participants", [])
            updated_list = result.get("updated_participants", [])
            removed_list = result.get("removed_participants", [])
            missing_list = result.get("missing_email_participants", [])
            added = result.get("processed", 0) if tab.dry_run.get() else len(added_list)
            tab.update_summary(added=added, updated=len(updated_list), removed=len(removed_list), missing=len(missing_list))
            tab.update_details(added=added_list, updated=updated_list, removed=removed_list, missing=missing_list)

    def _run_speakers(self, tab):
        from speakers import run_speakers_sync
        csv_path = Path(tab.csv_path.get())
        result = run_speakers_sync(
            csv_path,
            dry_run=tab.dry_run.get(),
            prune_missing=tab.prune.get(),
            log_callback=self.log,
        )
        if result:
            added_list = result.get("added_participants", [])
            updated_list = result.get("updated_participants", [])
            removed_list = result.get("removed_participants", [])
            missing_list = result.get("missing_email_participants", [])
            added = result.get("processed", 0) if tab.dry_run.get() else len(added_list)
            tab.update_summary(added=added, updated=len(updated_list), removed=len(removed_list), missing=len(missing_list))
            tab.update_details(added=added_list, updated=updated_list, removed=removed_list, missing=missing_list)

    def _run_schedule(self, tab):
        from schedule_sync import run_schedule_sync
        csv_path = Path(tab.csv_path.get())
        result = run_schedule_sync(
            csv_path,
            dry_run=tab.dry_run.get(),
            prune_missing=tab.prune.get(),
            log_callback=self.log,
        )
        if result:
            added_list = result.get("added_participants", [])
            updated_list = result.get("updated_participants", [])
            removed_list = result.get("removed_participants", [])
            missing_list = result.get("unmatched_speakers", [])
            added = result.get("processed", 0) if tab.dry_run.get() else len(added_list)
            tab.update_summary(added=added, updated=len(updated_list), removed=len(removed_list), missing=len(missing_list))
            tab.update_details(added=added_list, updated=updated_list, removed=removed_list, missing=missing_list)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    # Tell Windows this process is per-monitor DPI-aware so tkinter renders crisp on 4K displays
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    App().run()
