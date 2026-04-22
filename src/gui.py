"""
SIMsync GUI — local desktop app to sync event CSVs to Brella.
"""

import ctypes
import datetime
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, ttk
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
SURFACE_HOVER = "#2a2a33"
ROW_ALT = "#15151b"
TEXT = "#f0f0f5"
TEXT_SEC = "#8e8e9a"
TEXT_TER = "#55555f"
ACCENT = "#e6007e"
ACCENT_LIGHT = "#ff3da5"
ACCENT_DIM = "#4a1434"
SUCCESS = "#2dd4a8"
DANGER = "#f85149"
WARN = "#f0a030"

# --- Typography ---
# Poppins regular everywhere. Hierarchy comes from size and color, not weight.
FONT = ("Poppins", 10)
FONT_BOLD = FONT              # legacy alias — no bold variants anywhere
FONT_SMALL = FONT
FONT_MONO = FONT
FONT_SECTION = FONT
FONT_TITLE = FONT               # section titles match sidebar labels
FONT_DISPLAY = ("Poppins", 16)  # big stat numbers

# --- Spacing scale ---
SP_XS = 2
SP_SM = 4
SP_MD = 8
SP_LG = 12
SP_XL = 16

# Canonical input-bar height — Entry + Browse button always render at exactly this.
BAR_H = 34

CARD_PAD_X = SP_MD
CARD_PAD_INNER = SP_MD
CARD_PAD_Y_TOP = SP_SM
CARD_PAD_Y_BOT = SP_SM

SIDEBAR_W = 280            # minimum sidebar width
SIDEBAR_MAX_W = 800        # cap only to prevent runaway growth on ultrawide
SIDEBAR_WIDTH_RATIO = 0.38

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
GAP = SP_MD
ACTION_ROW_PAD_Y = SP_XS
ACTION_BTN_PADX = SP_LG
ACTION_BTN_PADY = SP_SM
ACTION_BTN_GAP = SP_MD


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

def make_field(parent, label, var, show=None, placeholder=""):
    parent_bg = parent.cget("bg") if hasattr(parent, "cget") else SURFACE
    tk.Label(parent, text=label, font=FONT, fg=TEXT_SEC, bg=parent_bg,
             anchor="w").pack(fill="x", pady=(0, SP_XS))
    kw = dict(textvariable=var, font=FONT, bg=BG, fg=TEXT, insertbackground=TEXT,
              relief="flat", bd=SP_MD,  # internal horizontal padding
              highlightthickness=1, highlightbackground=SURFACE_RAISED,
              highlightcolor=ACCENT)
    if show:
        kw["show"] = show
    entry = tk.Entry(parent, **kw)
    entry.pack(fill="x", ipady=SP_SM, pady=(0, SP_MD))
    return entry


def make_section(parent, title, subtitle=None, pady=(0, SP_LG)):
    """Consistent section: title (accent) + subtitle (muted) + body. A thin
    divider is drawn on TOP of the section (skipped for the first section
    in its parent), so dividers separate consecutive sections rather than
    splitting a section's title from its body."""
    is_first = len(parent.winfo_children()) == 0

    section = tk.Frame(parent, bg=BG)
    section.pack(fill="x", pady=pady)

    if not is_first:
        tk.Frame(section, bg=SURFACE_RAISED, height=1).pack(
            fill="x", pady=(0, SP_MD))

    tk.Label(section, text=title, font=FONT_TITLE, fg=ACCENT,
             bg=BG, anchor="w").pack(fill="x", pady=(0, SP_SM))
    if subtitle:
        tk.Label(section, text=subtitle, font=FONT, fg=TEXT_TER,
                 bg=BG, anchor="w").pack(fill="x", pady=(0, SP_SM))
    body = tk.Frame(section, bg=BG)
    body.pack(fill="both", expand=True)
    return body


def make_page(parent):
    """Consistent outer page padding; returns inner frame to populate."""
    outer = tk.Frame(parent, bg=BG)
    outer.pack(fill="both", expand=True, padx=SP_LG, pady=SP_LG)
    return outer


def make_checkbox(parent, text, variable, command=None):
    return tk.Checkbutton(
        parent, text=text, variable=variable, font=FONT,
        fg=TEXT_SEC, bg=BG, selectcolor=BG,
        activebackground=BG, activeforeground=TEXT,
        anchor="w", bd=0, highlightthickness=0,
        command=command, cursor="hand2",
    )


def make_toggle(parent, text, variable, command=None):
    """Button-styled boolean toggle bound to a tk.BooleanVar.
    Active = accent pink text (same as other buttons).
    Inactive = muted text on the same raised surface."""
    btn = tk.Button(
        parent, text=text, font=FONT,
        bg=SURFACE_RAISED,
        activebackground=SURFACE_HOVER,
        relief="flat", cursor="hand2", borderwidth=0,
        padx=ACTION_BTN_PADX, pady=ACTION_BTN_PADY,
    )

    def _apply():
        on = bool(variable.get())
        btn.config(
            fg=ACCENT_LIGHT if on else TEXT_SEC,
            activeforeground="#ffffff" if on else TEXT,
        )

    def _toggle():
        variable.set(not variable.get())
        if command:
            command()

    btn.config(command=_toggle)
    variable.trace_add("write", lambda *_: _apply())
    _apply()

    btn.bind("<Enter>", lambda _e: btn.config(bg=SURFACE_HOVER), add="+")
    btn.bind("<Leave>", lambda _e: btn.config(bg=SURFACE_RAISED), add="+")
    _bind_button_flash(btn, SURFACE_RAISED, ACCENT_DIM)
    return btn


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


# --- Button factory (consistent styling) ---

def make_button(parent, text, command, primary=False, danger=False):
    """Unified button style.
    - primary: pink background, white text — for important actions (Sync, Save).
    - danger:  dark background with danger-colored text.
    - default: dark raised surface with accent pink text.
    """
    if primary:
        bg = ACCENT
        fg = "#ffffff"
        hover_bg = ACCENT_LIGHT
        hover_fg = "#ffffff"
        press_bg = "#c8006d"
    elif danger:
        bg = SURFACE_RAISED
        fg = DANGER
        hover_bg = SURFACE_HOVER
        hover_fg = "#ffffff"
        press_bg = SURFACE_HOVER
    else:
        bg = SURFACE_RAISED
        fg = ACCENT_LIGHT
        hover_bg = SURFACE_HOVER
        hover_fg = "#ffffff"
        press_bg = ACCENT_DIM

    btn = tk.Button(
        parent, text=text, font=FONT,
        bg=bg, fg=fg,
        activebackground=hover_bg, activeforeground=hover_fg,
        disabledforeground=fg,
        relief="flat", cursor="hand2", borderwidth=0,
        padx=ACTION_BTN_PADX, pady=ACTION_BTN_PADY, command=command,
    )

    def on_enter(_e):
        btn.config(bg=hover_bg, fg=hover_fg)

    def on_leave(_e):
        btn.config(bg=bg, fg=fg)

    btn.bind("<Enter>", on_enter, add="+")
    btn.bind("<Leave>", on_leave, add="+")
    _bind_button_flash(btn, bg, press_bg)
    return btn


def make_card(parent, accent_color=None, pady=(0, SP_MD), padx=0):
    """Card-like container: thin accent top line + 1px border + padded body.
    Returns the inner content frame (BG background) to populate with widgets."""
    outer = tk.Frame(parent, bg=SURFACE_RAISED)
    outer.pack(fill="x", pady=pady, padx=padx)

    if accent_color:
        tk.Frame(outer, bg=accent_color, height=2).pack(fill="x")

    inner = tk.Frame(outer, bg=BG)
    inner.pack(fill="both", expand=True, padx=1, pady=(0 if accent_color else 1, 1))

    content = tk.Frame(inner, bg=BG)
    content.pack(fill="both", expand=True, padx=SP_MD, pady=SP_MD)
    return content


# --- ttk styling (scrollbars, treeview) ---

def _configure_ttk_styles():
    style = ttk.Style()
    try:
        style.theme_use("default")
    except Exception:
        pass

    # Vertical + horizontal scrollbar — dark, slim, no arrows.
    style.configure(
        "Dark.Vertical.TScrollbar",
        background=SURFACE_RAISED, troughcolor=SURFACE,
        bordercolor=SURFACE, arrowcolor=TEXT_TER,
        lightcolor=SURFACE_RAISED, darkcolor=SURFACE_RAISED,
        relief="flat", borderwidth=0, arrowsize=0, gripcount=0,
    )
    style.map(
        "Dark.Vertical.TScrollbar",
        background=[("active", SURFACE_HOVER), ("pressed", ACCENT_DIM)],
        troughcolor=[("!disabled", SURFACE)],
    )
    style.configure(
        "Dark.Horizontal.TScrollbar",
        background=SURFACE_RAISED, troughcolor=SURFACE,
        bordercolor=SURFACE, arrowcolor=TEXT_TER,
        relief="flat", borderwidth=0, arrowsize=0,
    )
    style.map(
        "Dark.Horizontal.TScrollbar",
        background=[("active", SURFACE_HOVER), ("pressed", ACCENT_DIM)],
    )


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

        self.api_key = tk.StringVar(value=load_env_value("BRELLA_API_KEY"))
        self.org_id = tk.StringVar(value=load_env_value("BRELLA_ORG_ID"))
        self.event_id = tk.StringVar(value=load_env_value("BRELLA_EVENT_ID"))
        self.admin_token = tk.StringVar(value=load_env_value("BRELLA_ADMIN_ACCESS_TOKEN"))
        self.admin_client = tk.StringVar(value=load_env_value("BRELLA_ADMIN_CLIENT"))
        self.admin_uid = tk.StringVar(value=load_env_value("BRELLA_ADMIN_UID"))

        page = make_page(self.frame)

        # ===== CONNECTION — custom header with status pill on the right =====
        conn_section = tk.Frame(page, bg=BG)
        conn_section.pack(fill="x", pady=(0, SP_LG))

        hdr_row = tk.Frame(conn_section, bg=BG)
        hdr_row.pack(fill="x")

        hdr_left = tk.Frame(hdr_row, bg=BG)
        hdr_left.pack(side="left", fill="x", expand=True)
        tk.Label(hdr_left, text="Connection", font=FONT_TITLE, fg=ACCENT,
                 bg=BG, anchor="w").pack(fill="x", pady=(0, SP_SM))
        tk.Label(
            hdr_left,
            text="Brella API credentials. The API key is required for syncing.",
            font=FONT, fg=TEXT_TER, bg=BG, anchor="w",
        ).pack(fill="x", pady=(0, SP_SM))

        # Status pill anchored top-right
        api_loaded = bool(self.api_key.get())
        status_col = tk.Frame(hdr_row, bg=BG)
        status_col.pack(side="right", padx=(SP_LG, 0), pady=(SP_XS, 0))
        self._api_status_dot = tk.Frame(status_col,
                                        bg=SUCCESS if api_loaded else DANGER,
                                        width=8, height=8)
        self._api_status_dot.pack(side="left", padx=(0, SP_SM))
        self._api_status_dot.pack_propagate(False)
        self._api_status_lbl = tk.Label(
            status_col,
            text="API key loaded" if api_loaded else "API key not set",
            font=FONT,
            fg=SUCCESS if api_loaded else DANGER, bg=BG,
        )
        self._api_status_lbl.pack(side="left")

        # Two credential cards: Integration API | Admin Panel
        creds_grid = tk.Frame(conn_section, bg=BG)
        creds_grid.pack(fill="x", pady=(SP_SM, 0))
        creds_grid.columnconfigure(0, weight=1, uniform="creds")
        creds_grid.columnconfigure(1, weight=1, uniform="creds")

        # --- Integration API card ---
        api_wrap = tk.Frame(creds_grid, bg=BG)
        api_wrap.grid(row=0, column=0, sticky="nsew", padx=(0, SP_MD))
        api_col = make_card(api_wrap, accent_color=ACCENT, pady=(0, 0))
        tk.Label(api_col, text="Integration API", font=FONT,
                 fg=TEXT_SEC, bg=BG, anchor="w").pack(fill="x", pady=(0, SP_SM))
        make_field(api_col, "API Key", self.api_key, show="*")

        ids_row = tk.Frame(api_col, bg=BG)
        ids_row.pack(fill="x")
        ids_row.columnconfigure(0, weight=1, uniform="ids")
        ids_row.columnconfigure(1, weight=1, uniform="ids")
        ids_left = tk.Frame(ids_row, bg=BG)
        ids_left.grid(row=0, column=0, sticky="nsew", padx=(0, SP_SM))
        ids_right = tk.Frame(ids_row, bg=BG)
        ids_right.grid(row=0, column=1, sticky="nsew", padx=(SP_SM, 0))
        make_field(ids_left, "Org ID", self.org_id)
        make_field(ids_right, "Event ID", self.event_id)

        # --- Admin Panel card ---
        admin_wrap = tk.Frame(creds_grid, bg=BG)
        admin_wrap.grid(row=0, column=1, sticky="nsew", padx=(SP_MD, 0))
        admin_col = make_card(admin_wrap, accent_color=ACCENT, pady=(0, 0))
        tk.Label(admin_col, text="Admin Panel", font=FONT,
                 fg=TEXT_SEC, bg=BG, anchor="w").pack(fill="x", pady=(0, SP_SM))
        make_field(admin_col, "Access Token", self.admin_token, show="*")

        admin_row = tk.Frame(admin_col, bg=BG)
        admin_row.pack(fill="x")
        admin_row.columnconfigure(0, weight=1, uniform="adm")
        admin_row.columnconfigure(1, weight=1, uniform="adm")
        al = tk.Frame(admin_row, bg=BG)
        al.grid(row=0, column=0, sticky="nsew", padx=(0, SP_SM))
        ar = tk.Frame(admin_row, bg=BG)
        ar.grid(row=0, column=1, sticky="nsew", padx=(SP_SM, 0))
        make_field(al, "Client", self.admin_client)
        make_field(ar, "UID", self.admin_uid)

        # Connection test result (below the cards)
        self._api_status_var = tk.StringVar(value="")
        self._api_status_result = tk.Label(
            conn_section, textvariable=self._api_status_var,
            font=FONT, fg=TEXT_SEC, bg=BG, anchor="w",
        )
        self._api_status_result.pack(fill="x", pady=(SP_MD, 0))

        # ===== MAPPINGS =====
        import api

        maps_body = make_section(
            page, "Groups & Tickets",
            subtitle="How 3cket ticket types map to Brella attendee groups.",
        )

        self.groups_inline_var = tk.StringVar(
            value=self._format_mapping_inline(api.BRELLA_ATTENDEE_GROUP_IDS)
        )
        self.priority_inline_var = tk.StringVar(value="; ".join(api.GROUP_PRIORITY))

        tk.Label(maps_body, text="Group numbers", font=FONT, fg=TEXT_SEC,
                 bg=BG, anchor="w").pack(fill="x", pady=(0, SP_XS))
        self.groups_inline_entry = tk.Entry(
            maps_body, textvariable=self.groups_inline_var,
            font=FONT, bg=BG, fg=TEXT, insertbackground=TEXT,
            relief="flat", bd=SP_MD,
            highlightthickness=1, highlightbackground=SURFACE_RAISED,
            highlightcolor=ACCENT,
        )
        self.groups_inline_entry.pack(fill="x", ipady=SP_MD, pady=(0, SP_MD))

        tk.Label(maps_body, text="Priority group IDs", font=FONT, fg=TEXT_SEC,
                 bg=BG, anchor="w").pack(fill="x", pady=(0, SP_XS))
        self.priority_inline_entry = tk.Entry(
            maps_body, textvariable=self.priority_inline_var,
            font=FONT, bg=BG, fg=TEXT, insertbackground=TEXT,
            relief="flat", bd=SP_MD,
            highlightthickness=1, highlightbackground=SURFACE_RAISED,
            highlightcolor=ACCENT,
        )
        self.priority_inline_entry.pack(fill="x", ipady=SP_MD, pady=(0, SP_MD))

        tk.Label(maps_body, text="Ticket types (key=value, separated by ';')",
                 font=FONT, fg=TEXT_SEC, bg=BG, anchor="w").pack(
            fill="x", pady=(0, SP_XS))
        self.tickets_inline_text = tk.Text(
            maps_body, font=FONT, bg=BG, fg=TEXT, insertbackground=TEXT,
            relief="flat", highlightthickness=1,
            highlightbackground=SURFACE_RAISED, highlightcolor=ACCENT,
            wrap="word", height=10, padx=SP_MD, pady=SP_MD,
        )
        self.tickets_inline_text.pack(fill="both", expand=True, pady=(0, 0))
        self.tickets_inline_text.insert(
            "1.0", self._format_mapping_inline(api.TICKET_TYPE_TO_GROUP_ID)
        )

        # Log-hosted action row for Setup
        if self._app and hasattr(self._app, "_log_action_host"):
            self.action_row = tk.Frame(self._app._log_action_host, bg=SURFACE)
            action_parent = self.action_row
        else:
            action_parent = self.frame

        self.save_btn = make_button(action_parent, "Save",
                                    command=self._save_all, primary=True)
        self.test_btn = make_button(action_parent, "Test",
                                    command=self._test_connection)

        self.save_btn.pack(side="left", padx=(0, ACTION_BTN_GAP))
        self.test_btn.pack(side="left")

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

    def _save_all(self):
        """Save credentials + groups/tickets mappings in one click."""
        self._save_api()
        self._save_values()

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
    def __init__(self, parent, name, description, has_prune=False,
                 has_staff_only=False, has_remove=True,
                 run_func=None, enabled=True, app=None,
                 csv_header_fields=None):
        self.name = name
        self.run_func = run_func
        self.enabled = enabled
        self._app = app
        self.csv_path = tk.StringVar()
        self.dry_run = tk.BooleanVar(value=False)
        self.prune = tk.BooleanVar(value=False)
        self.update_existing = tk.BooleanVar(value=False)
        self.staff_only = tk.BooleanVar(value=False)
        self.has_prune = has_prune
        self.has_staff_only = has_staff_only
        self.running = False
        self.action_row = None

        self.frame = tk.Frame(parent, bg=BG)

        page = make_page(self.frame)

        # ===== CSV header preview (inline: prefix + values + hint) =====
        req_fields = [f for f, req in (csv_header_fields or []) if req]
        if req_fields:
            hdr_body = make_section(page, "CSV Header")
            txt = tk.Text(
                hdr_body, font=FONT, bg=BG, fg=TEXT_SEC,
                relief="flat", borderwidth=0, highlightthickness=0,
                wrap="word", cursor="hand2", height=1,
            )
            txt.tag_configure("prefix", foreground=TEXT_SEC)
            txt.tag_configure("values", foreground=ACCENT_LIGHT)
            txt.tag_configure("hint", foreground=TEXT_TER)

            values_str = ", ".join(req_fields)
            txt.insert("end", "Required columns: ", "prefix")
            txt.insert("end", values_str, "values")
            txt.insert("end", "   click to copy", "hint")
            txt.config(state="disabled")
            txt.pack(fill="x")

            def _fit_height(tw=txt):
                tw.update_idletasks()
                lines = int(tw.index("end-1c").split(".")[0])
                tw.config(height=max(lines, 1))
            txt.after_idle(_fit_height)
            txt.bind("<Configure>", lambda _e, tw=txt: _fit_height(tw))

            def _copy_header(event=None, names=req_fields, widget=txt):
                widget.clipboard_clear()
                widget.clipboard_append(",".join(names))
                widget.config(state="normal")
                widget.tag_configure("values", foreground=SUCCESS)

                def _unflash(tw=widget):
                    tw.tag_configure("values", foreground=ACCENT_LIGHT)
                    tw.config(state="disabled")

                widget.after(350, _unflash)
                widget.config(state="disabled")
            txt.bind("<Button-1>", _copy_header)

        # ===== CSV file picker (path + optional prune toggle + browse) =====
        csv_body = make_section(page, "CSV File")
        csv_row = tk.Frame(csv_body, bg=BG)
        csv_row.pack(fill="x")

        self.browse_btn = make_button(csv_row, "Browse", command=self._browse)
        self.browse_btn.config(pady=SP_MD, highlightthickness=1,
                               highlightbackground=SURFACE_RAISED)
        # Browse on the left of the input bar.
        self.browse_btn.pack(side="left", padx=(0, SP_MD), fill="y")

        # Right-to-left packing for the toggles (first packed sits furthest right).
        # Visual order (left to right): [Browse] [entry] [Staff] [Update] [Remove]
        if has_prune:
            if has_remove:
                self.prune_cb = make_toggle(csv_row, "Remove", self.prune)
                self.prune_cb.config(pady=SP_MD, highlightthickness=1,
                                     highlightbackground=SURFACE_RAISED)
                self.prune_cb.pack(side="right", padx=(SP_MD, 0), fill="y")

            self.update_cb = make_toggle(csv_row, "Update existing",
                                         self.update_existing)
            self.update_cb.config(pady=SP_MD, highlightthickness=1,
                                  highlightbackground=SURFACE_RAISED)
            self.update_cb.pack(side="right", padx=(SP_MD, 0), fill="y")

            if has_staff_only:
                self.staff_cb = make_toggle(csv_row, "Staff only",
                                            self.staff_only)
                self.staff_cb.config(pady=SP_MD, highlightthickness=1,
                                     highlightbackground=SURFACE_RAISED)
                self.staff_cb.pack(side="right", padx=(SP_MD, 0), fill="y")

        # Notices area: surfaces active-mode system messages between the
        # CSV bar and the result containers.
        self._notices = tk.Frame(csv_body, bg=BG)
        self._notices.pack(fill="x", pady=(SP_MD, 0))
        self._notice_labels = {}
        if has_prune:
            if has_remove:
                self._install_notice(
                    "prune", self.prune,
                    "Removing from Brella if not in CSV", WARN,
                )
            self._install_notice(
                "update", self.update_existing,
                "Updating existing rows in Brella (will overwrite manual edits)",
                ACCENT_LIGHT,
            )
            if has_staff_only:
                self._install_notice(
                    "staff", self.staff_only,
                    "Syncing only Staff ticket types", SUCCESS,
                )

        self.path_entry = tk.Entry(
            csv_row, textvariable=self.csv_path, font=FONT,
            bg=BG, fg=TEXT, insertbackground=TEXT,
            relief="flat", bd=SP_MD,
            highlightthickness=1, highlightbackground=SURFACE_RAISED,
            highlightcolor=ACCENT,
        )
        self.path_entry.pack(side="left", fill="x", expand=True, ipady=SP_SM)

        # Detail boxes: 2x2 grid. The wrapper's height is synced to the
        # sidebar log panel's height, so its top edge lines up with where
        # the log starts. Wrapper is pinned to the bottom of the tab.
        self._stat_wrap = tk.Frame(self.frame, bg=SURFACE_RAISED)
        self._stat_wrap.pack(side="bottom", fill="x")
        self._stat_wrap.pack_propagate(False)

        tk.Frame(self._stat_wrap, bg=SURFACE_RAISED, height=1).pack(fill="x")
        detail_container = tk.Frame(self._stat_wrap, bg=SURFACE_RAISED)
        detail_container.pack(fill="both", expand=True, padx=0, pady=0)
        for c in range(3):
            detail_container.columnconfigure(c, weight=1, uniform="stats")
        detail_container.rowconfigure(0, weight=1)
        detail_container.rowconfigure(1, weight=1)

        # Row 0: Added · Updated · Skipped
        self.card_added, self.card_added_title, self.list_added = self._make_unified_box(
            detail_container, "Added", "0", SUCCESS, row=0, col=0)
        self.card_updated, _, self.list_updated = self._make_unified_box(
            detail_container, "Updated", "0", ACCENT, row=0, col=1)
        self.card_skipped, _, self.list_skipped = self._make_unified_box(
            detail_container, "Skipped", "0", TEXT_TER, row=0, col=2)

        # Row 1: Removed · Missing info · Duplicates
        self.card_removed, self.card_removed_title, self.list_removed = self._make_unified_box(
            detail_container, "Removed", "0", DANGER, row=1, col=0)
        self.card_missing, _, self.list_missing = self._make_unified_box(
            detail_container, "Missing info", "0", WARN, row=1, col=1, copyable=True)
        self.card_duplicate, _, self.list_duplicate = self._make_unified_box(
            detail_container, "Duplicates", "0", DANGER, row=1, col=2, copyable=True)

        # Sync the wrapper's height to match the log panel's height so its
        # top edge aligns with where the log starts.
        if self._app and hasattr(self._app, "_log_frame"):
            self._app._log_frame.bind(
                "<Configure>",
                lambda e, w=self._stat_wrap: w.config(height=e.height),
                add="+",
            )
            self.frame.after_idle(
                lambda w=self._stat_wrap: w.config(
                    height=self._app._log_frame.winfo_height()
                )
            )

        # Log-hosted action row for Preview/Import
        if self._app and hasattr(self._app, "_log_action_host"):
            self.action_row = tk.Frame(self._app._log_action_host, bg=SURFACE)
            action_parent = self.action_row
        else:
            action_parent = self.frame

        self.import_btn = make_button(action_parent, "Sync",
                                      command=lambda: self._run(dry_run=False),
                                      primary=True)
        self.preview_btn = make_button(action_parent, "Preview",
                                       command=lambda: self._run(dry_run=True))

        self.import_btn.pack(side="left", padx=(0, ACTION_BTN_GAP))
        self.preview_btn.pack(side="left")

        if not enabled:
            self.browse_btn.config(state="disabled")
            self.path_entry.config(state="disabled")
            self.preview_btn.config(state="disabled")
            self.import_btn.config(state="disabled")

    def _install_notice(self, key, variable, text, color):
        """Show/hide a one-line notice whenever `variable` changes.
        Rendered as a small dot + muted text in the notices strip."""
        row = tk.Frame(self._notices, bg=BG)
        dot = tk.Frame(row, bg=color, width=8, height=8)
        dot.pack(side="left", padx=(0, SP_SM), pady=(SP_XS, 0))
        dot.pack_propagate(False)
        lbl = tk.Label(row, text=text, font=FONT, fg=TEXT_SEC, bg=BG, anchor="w")
        lbl.pack(side="left")

        self._notice_labels[key] = row

        def _apply(*_):
            if variable.get():
                row.pack(fill="x", pady=(0, SP_XS))
            else:
                row.pack_forget()

        variable.trace_add("write", _apply)
        _apply()
        return row

    @staticmethod
    def _attach_dark_scrollbar(parent, target):
        """Attach a Dark.Vertical.TScrollbar to the Listbox/Text `target`
        inside `parent`. Assumes parent is a grid-using frame with row 0 and
        col 0 holding `target`."""
        _configure_ttk_styles()
        vsb = ttk.Scrollbar(parent, orient="vertical",
                            style="Dark.Vertical.TScrollbar",
                            command=target.yview)
        target.configure(yscrollcommand=vsb.set)
        vsb.grid(row=0, column=1, sticky="ns")
        parent.columnconfigure(1, weight=0)
        return vsb

    def _make_unified_box(self, parent, title, value, color, row=0, col=0, copyable=False):
        outer = tk.Frame(parent, bg=BG)
        # 1px separator between columns and rows. Rightmost column (index 2
        # in the 3-col layout) drops the right border so it meets the edge.
        padx = (0, 1) if col < 2 else (0, 0)
        pady = (0, 1) if row == 0 else (0, 0)
        outer.grid(row=row, column=col, sticky="nsew", padx=padx, pady=pady)
        outer.columnconfigure(0, weight=1)

        accent_line = tk.Frame(outer, bg=color, height=2)
        accent_line.grid(row=0, column=0, sticky="ew")

        header = tk.Frame(outer, bg=BG)
        header.grid(row=1, column=0, sticky="ew")

        title_row = tk.Frame(header, bg=BG)
        title_row.pack(fill="x", padx=SP_MD, pady=(SP_XS, SP_XS))

        count_label = tk.Label(title_row, text=value, font=FONT_DISPLAY,
                       fg=color, bg=BG, anchor="w")
        count_label.pack(side="left")

        card_title_font = ("Poppins", 8)
        title_label = tk.Label(title_row, text=title, font=card_title_font,
                               fg=TEXT_TER, bg=BG, anchor="w")
        title_label.pack(side="left", padx=(SP_MD, 0), pady=(SP_SM, 0))

        if copyable:
            copy_btn = tk.Button(title_row, text="Copy", font=card_title_font,
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

        lb = tk.Listbox(list_frame, font=("Poppins", 8), bg=BG, fg=TEXT_SEC,
                        selectbackground=SURFACE_RAISED, selectforeground=TEXT,
                        relief="flat", borderwidth=0, highlightthickness=0,
                        activestyle="none")
        lb.grid(row=0, column=0, sticky="nsew", padx=(SP_MD, 0), pady=SP_MD)

        self._attach_dark_scrollbar(list_frame, lb)

        return count_label, title_label, lb

    def _copy_listbox(self, lb):
        items = lb.get(0, "end")
        if items:
            self.frame.clipboard_clear()
            self.frame.clipboard_append("\n".join(items))

    def update_summary(self, added=0, updated=0, skipped=0,
                        removed=0, missing=0, duplicate=0):
        def _update():
            self.card_added.config(text=str(added))
            self.card_added_title.config(text="To add" if self.dry_run.get() else "Added")
            self.card_updated.config(text=str(updated))
            self.card_skipped.config(text=str(skipped))
            self.card_removed.config(text=str(removed))
            self.card_missing.config(text=str(missing))
            self.card_duplicate.config(text=str(duplicate))
        self.frame.after(0, _update)

    def update_details(self, added=None, updated=None, skipped=None,
                        removed=None, missing=None, duplicate=None):
        def _update():
            for lb, items in [
                (self.list_added, added or []),
                (self.list_updated, updated or []),
                (self.list_skipped, skipped or []),
                (self.list_removed, removed or []),
                (self.list_missing, missing or []),
                (self.list_duplicate, duplicate or []),
            ]:
                lb.delete(0, "end")
                if items:
                    for item in items:
                        lb.insert("end", f"  {item}")
                else:
                    lb.insert("end", "  —")
        self.frame.after(0, _update)

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
        if not self.csv_path.get().strip():
            self._set_status("Select a CSV file first.", DANGER)
            return
        if not Path(self.csv_path.get()).exists():
            self._set_status("File not found.", DANGER)
            return
        self.dry_run.set(dry_run)
        self.running = True
        self._set_busy(True)
        mode = "preview" if dry_run else "sync"
        self._set_status(f"Running {mode}...", ACCENT_LIGHT)
        if self._app:
            self._app._log_status_pulse.start(ACCENT_LIGHT)
        # Visual start marker for this run in the log.
        self._log(f"[preview] --- {self.name} {mode} started ---"
                  if dry_run else
                  f"[info] --- {self.name} sync started ---")
        threading.Thread(target=self._run_thread, daemon=True).start()

    def _run_thread(self):
        try:
            if self.run_func:
                self.run_func(self)
            else:
                self._log(f"[{self.name}] Not implemented yet.")
            mode = "Preview" if self.dry_run.get() else "Sync"
            # Visual end marker for this run in the log.
            tag = "preview" if self.dry_run.get() else "info"
            self._log(f"[{tag}] --- {self.name} {mode.lower()} complete ---")
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


# --- Debug Tab ---

class DebugTab:
    """
    Inspect every Brella invite, highlight ones whose external_qr_string
    is missing or still falling back to `brella_invite_id=...`, and patch
    them individually (auto from 3cket CSV, or manual value).
    """

    BRELLA_FALLBACK_PREFIX = "brella_invite_id="

    def __init__(self, parent, app=None, log_callback=None):
        self._app = app
        self._log_callback = log_callback
        self.frame = tk.Frame(parent, bg=BG)
        self.action_row = None

        self._invites = []            # raw Brella invites
        self._csv_ticket_map = {}     # email -> "ticket / ticket" string
        self._csv_qr_map = {}         # email -> expected external_qr_string (from 3cket)
        self._loading = False

        self.csv_path = tk.StringVar(value=str(BASE_DIR / "data" / "participants.csv"))
        self.filter_missing_only = tk.BooleanVar(value=False)
        self.search_var = tk.StringVar(value="")
        self.total_var = tk.StringVar(value="—")
        self.missing_var = tk.StringVar(value="—")

        page = make_page(self.frame)

        # ===== CSV picker =====
        csv_body = make_section(
            page, "3cket CSV",
            subtitle="Used to show ticket types and auto-fill 'Fix from CSV'.",
        )
        csv_row = tk.Frame(csv_body, bg=BG)
        csv_row.pack(fill="x")

        self.browse_btn = make_button(csv_row, "Browse", command=self._browse_csv)
        self.browse_btn.config(pady=SP_MD, highlightthickness=1,
                               highlightbackground=SURFACE_RAISED)
        self.browse_btn.pack(side="left", padx=(0, SP_MD), fill="y")

        self.csv_entry = tk.Entry(
            csv_row, textvariable=self.csv_path, font=FONT,
            bg=BG, fg=TEXT, insertbackground=TEXT,
            relief="flat", bd=SP_MD,
            highlightthickness=1, highlightbackground=SURFACE_RAISED,
            highlightcolor=ACCENT,
        )
        self.csv_entry.pack(side="left", fill="x", expand=True, ipady=SP_SM)

        # ===== Filter / search bar =====
        filter_bar = tk.Frame(page, bg=BG)
        filter_bar.pack(fill="x", pady=(0, SP_SM))

        self.missing_cb = make_checkbox(
            filter_bar, "Only missing QR", self.filter_missing_only,
            command=self._refresh_display,
        )
        self.missing_cb.pack(side="left")

        tk.Label(filter_bar, text="Search", font=FONT, fg=TEXT_TER,
                 bg=BG).pack(side="left", padx=(SP_LG, SP_SM))
        search_entry = tk.Entry(
            filter_bar, textvariable=self.search_var, font=FONT,
            bg=BG, fg=TEXT, insertbackground=TEXT, width=28,
            relief="flat", bd=SP_MD,
            highlightthickness=1, highlightbackground=SURFACE_RAISED,
            highlightcolor=ACCENT,
        )
        search_entry.pack(side="left", ipady=0)
        self.search_var.trace_add("write", lambda *a: self._refresh_display())

        # Summary counters (right) — just two labels, no separator dot.
        summary = tk.Frame(filter_bar, bg=BG)
        summary.pack(side="right")
        tk.Label(summary, textvariable=self.total_var, font=FONT,
                 fg=TEXT_SEC, bg=BG).pack(side="right")
        self._missing_label = tk.Label(
            summary, textvariable=self.missing_var, font=FONT,
            fg=TEXT_TER, bg=BG,
        )
        self._missing_label.pack(side="right", padx=(0, SP_LG))

        # ===== Treeview =====
        self._configure_tree_style()

        tree_wrap = tk.Frame(page, bg=SURFACE_RAISED)
        tree_wrap.pack(fill="both", expand=True, pady=(SP_SM, 0))

        cols = ("email", "ticket", "group", "qr", "invite_id")
        self.tree = ttk.Treeview(
            tree_wrap, columns=cols, show="headings",
            style="Debug.Treeview", selectmode="browse",
        )
        widths = {
            "email": 280, "ticket": 200, "group": 100,
            "qr": 220, "invite_id": 80,
        }
        headings = {
            "email": "Email", "ticket": "Ticket type", "group": "Group",
            "qr": "External QR", "invite_id": "Invite ID",
        }
        for col in cols:
            self.tree.heading(col, text=headings[col], anchor="w")
            self.tree.column(col, width=widths[col], anchor="w", stretch=True)

        vsb = ttk.Scrollbar(tree_wrap, orient="vertical",
                            style="Dark.Vertical.TScrollbar",
                            command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        # Column separator overlay: thin vertical frames placed on top of the
        # tree at column boundaries. Redrawn whenever the tree is resized.
        self._column_separators = []
        self._tree_wrap = tree_wrap
        # Use after_idle so widths are read AFTER Tk finishes laying out
        # stretch columns for the new tree size.
        self.tree.bind(
            "<Configure>",
            lambda _e: self.tree.after_idle(self._draw_column_separators),
            add="+",
        )
        self.tree.bind(
            "<ButtonRelease-1>",
            lambda _e: self.tree.after_idle(self._draw_column_separators),
            add="+",
        )

        self.tree.tag_configure("missing", background="#2a1f0a", foreground=WARN)
        self.tree.tag_configure("ok", background=BG, foreground=TEXT)
        self.tree.tag_configure("ok_alt", background=ROW_ALT, foreground=TEXT)

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self._edit_qr_dialog())

        # First-paint separators after Tk settles the tree's stretch columns.
        self.tree.after(100, self._draw_column_separators)
        self.tree.after(400, self._draw_column_separators)

        # === Action buttons (hosted in log panel like other tabs) ===
        if self._app and hasattr(self._app, "_log_action_host"):
            self.action_row = tk.Frame(self._app._log_action_host, bg=SURFACE)
            action_parent = self.action_row
        else:
            action_parent = self.frame

        self.fix_btn = make_button(action_parent, "Fix",
                                   command=self._fix_from_csv, primary=True)
        self.fix_btn.config(state="disabled")
        self.refresh_btn = make_button(action_parent, "Refresh",
                                       command=self._refresh)

        self.fix_btn.pack(side="left", padx=(0, ACTION_BTN_GAP))
        self.refresh_btn.pack(side="left")

    # --- Styling ---

    def _draw_column_separators(self, _event=None):
        """Overlay 1px vertical dividers at column boundaries.
        Re-runs on tree resize so dividers track the current column widths."""
        for sep in self._column_separators:
            try:
                sep.destroy()
            except Exception:
                pass
        self._column_separators = []

        try:
            cols = self.tree["columns"]
            x = 0
            for col in cols[:-1]:  # no divider after the last column
                x += int(self.tree.column(col, option="width"))
                sep = tk.Frame(self.tree, bg=SURFACE_RAISED, width=1)
                # place uses tree's client area; height takes full tree height.
                sep.place(x=x - 1, y=0, relheight=1.0, width=1)
                self._column_separators.append(sep)
        except Exception:
            pass

    def _configure_tree_style(self):
        _configure_ttk_styles()
        style = ttk.Style()
        table_font = ("Poppins", 9)
        style.configure(
            "Debug.Treeview",
            background=BG, foreground=TEXT, fieldbackground=BG,
            borderwidth=0, relief="flat", rowheight=22, font=table_font,
        )
        style.map(
            "Debug.Treeview",
            background=[("selected", SURFACE_RAISED)],
            foreground=[("selected", TEXT)],
        )
        style.configure(
            "Debug.Treeview.Heading",
            background=SURFACE, foreground=TEXT_SEC,
            borderwidth=0, relief="flat", font=table_font,
            padding=(SP_SM, SP_XS),
        )
        style.map(
            "Debug.Treeview.Heading",
            background=[("active", SURFACE_RAISED)],
            foreground=[("active", ACCENT_LIGHT)],
        )
        style.layout("Debug.Treeview", style.layout("Treeview"))

    # --- Actions ---

    def _browse_csv(self):
        path = filedialog.askopenfilename(
            title="Select 3cket participants CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self.csv_path.set(path)

    def _refresh(self):
        if self._loading:
            return
        self._loading = True
        self._set_busy(True)
        self._log("[INFO] Loading Brella invites...")
        if self._app:
            self._app._log_status_var.set("Loading invites...")
            self._app._log_status_label.config(fg=ACCENT_LIGHT)
            self._app._log_status_pulse.start(ACCENT_LIGHT)
        threading.Thread(target=self._load_thread, daemon=True).start()

    def _load_thread(self):
        try:
            import api
            api.API_KEY = os.environ.get("BRELLA_API_KEY", api.API_KEY)
            api.ORG_ID = os.environ.get("BRELLA_ORG_ID", api.ORG_ID)
            api.EVENT_ID = os.environ.get("BRELLA_EVENT_ID", api.EVENT_ID)

            self._csv_ticket_map = {}
            self._csv_qr_map = {}
            csv_path = Path(self.csv_path.get().strip())
            if csv_path.exists():
                self._load_csv_map(csv_path)
                self._log(f"[INFO] Loaded {len(self._csv_ticket_map)} rows from 3cket CSV.")
            else:
                self._log(f"[WARN] CSV not found: {csv_path} — ticket types and 'Fix from CSV' will be empty.")

            headers = api.build_request_headers()
            invites = api.list_invites(headers)
            self._invites = invites
            self._log(f"[OK] Loaded {len(invites)} invites from Brella. Fetching details...")
            # First render (QR still empty) so the UI feels responsive.
            self.frame.after(0, self._refresh_display)

            self._fetch_invite_details(headers, invites)
            self._log("[OK] Invite details loaded.")
            self.frame.after(0, self._refresh_display)

            if self._app:
                self.frame.after(0, lambda: self._app._log_status_var.set(
                    f"{len(invites)} invites loaded"))
                self.frame.after(0, lambda: self._app._log_status_label.config(fg=SUCCESS))
        except Exception as exc:
            self._log(f"[ERROR] Debug load failed: {exc}")
            if self._app:
                self.frame.after(0, lambda: self._app._log_status_var.set("Load failed"))
                self.frame.after(0, lambda: self._app._log_status_label.config(fg=DANGER))
        finally:
            self._loading = False
            self.frame.after(0, lambda: self._set_busy(False))
            if self._app:
                self.frame.after(0, self._app._log_status_pulse.stop)

    def _fetch_invite_details(self, headers, invites):
        """GET per-invite detail to populate fields not returned by the list endpoint
        (notably external_qr_string). Runs concurrently to stay responsive."""
        import api
        import json as _json
        from concurrent.futures import ThreadPoolExecutor

        stats = {"ok": 0, "fail": 0}
        sample = {"logged": False}

        def merge_detail_into(invite, detail):
            # Detail shape may be JSON:API ({"data": {"attributes": {...}}})
            # or legacy ({"event_invite": {...}}) or flat.
            data = detail.get("data", detail) if isinstance(detail, dict) else None
            if isinstance(data, dict):
                attrs = data.get("attributes")
                if isinstance(attrs, dict):
                    tgt = invite.get("attributes")
                    if not isinstance(tgt, dict):
                        tgt = {}
                        invite["attributes"] = tgt
                    for k, v in attrs.items():
                        if v is not None:
                            tgt[k] = v
                ei = data.get("event_invite")
                if isinstance(ei, dict):
                    invite["event_invite"] = ei
            if isinstance(detail, dict):
                ei = detail.get("event_invite")
                if isinstance(ei, dict):
                    invite["event_invite"] = ei

        def fetch_one(invite):
            invite_id = str(invite.get("id", "")).strip()
            if not invite_id:
                return
            try:
                url = api.build_update_url(invite_id)
                status, resp = api.api_request(url, headers, "GET")
                if status != 200:
                    stats["fail"] += 1
                    if stats["fail"] <= 2:
                        self._log(f"[WARN] detail GET {invite_id} -> {status}: {resp[:200]}")
                    return
                payload = _json.loads(resp)
                # Log the first successful payload shape so we can see the keys.
                if not sample["logged"]:
                    sample["logged"] = True
                    self._log_detail_sample(invite_id, payload)
                merge_detail_into(invite, payload)
                stats["ok"] += 1
            except Exception as exc:
                stats["fail"] += 1
                if stats["fail"] <= 2:
                    self._log(f"[WARN] detail GET {invite_id} exception: {exc}")

        workers = min(8, max(1, len(invites)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(fetch_one, invites))

        self._log(f"[INFO] Detail fetches: {stats['ok']} ok, {stats['fail']} failed.")

    def _log_detail_sample(self, invite_id, payload):
        """Dump attribute/event_invite keys from one response so we can see
        what fields Brella actually returns for an invite detail."""
        keys_found = []
        if isinstance(payload, dict):
            data = payload.get("data", payload)
            if isinstance(data, dict):
                attrs = data.get("attributes")
                if isinstance(attrs, dict):
                    keys_found.append(f"attributes: {sorted(attrs.keys())}")
                ei = data.get("event_invite")
                if isinstance(ei, dict):
                    keys_found.append(f"event_invite: {sorted(ei.keys())}")
            if "event_invite" in payload and isinstance(payload["event_invite"], dict):
                keys_found.append(f"top event_invite: {sorted(payload['event_invite'].keys())}")
        self._log(f"[INFO] Sample invite {invite_id} keys -> {' | '.join(keys_found) or 'no dict keys'}")

    def _load_csv_map(self, csv_path):
        import api
        for _line_no, row in api.iter_threecket_rows(csv_path):
            email = api.pick_email(row)
            if not email:
                continue
            tickets = api.pick_ticket_types(row)
            ticket_str = " / ".join(tickets) if tickets else ""
            self._csv_ticket_map[email] = ticket_str

            threecket_id = api.pick_threecket_id(row)
            expected_qr = api.pick_external_qr(row, threecket_id)
            if expected_qr:
                self._csv_qr_map[email] = expected_qr

    # --- Display ---

    def _invite_field(self, invite, *field_names):
        """Read a field from an invite, trying event_invite wrapper, top-level,
        and JSON:API `attributes` (both snake_case and kebab-case)."""
        if not isinstance(invite, dict):
            return ""

        event_invite = invite.get("event_invite")
        if isinstance(event_invite, dict):
            for name in field_names:
                v = event_invite.get(name)
                if v is not None and str(v).strip():
                    return str(v).strip()

        for name in field_names:
            v = invite.get(name)
            if v is not None and str(v).strip():
                return str(v).strip()

        attributes = invite.get("attributes")
        if isinstance(attributes, dict):
            for name in field_names:
                for variant in (name, name.replace("_", "-")):
                    v = attributes.get(variant)
                    if v is not None and str(v).strip():
                        return str(v).strip()

        relationships = invite.get("relationships")
        if isinstance(relationships, dict):
            for name in field_names:
                rel_key = name.replace("_id", "")
                rel = relationships.get(rel_key) or relationships.get(rel_key.replace("_", "-"))
                if isinstance(rel, dict):
                    data = rel.get("data")
                    if isinstance(data, dict) and data.get("id"):
                        return str(data["id"]).strip()

        return ""

    def _refresh_display(self):
        import api

        for iid in self.tree.get_children():
            self.tree.delete(iid)

        group_name_map = {v: k for k, v in api.BRELLA_ATTENDEE_GROUP_IDS.items()}
        missing_count = 0
        total_count = 0

        filter_missing = self.filter_missing_only.get()
        search_q = self.search_var.get().strip().lower()

        for invite in self._invites:
            if not isinstance(invite, dict):
                continue

            first = self._invite_field(invite, "external_first_name")
            last = self._invite_field(invite, "external_last_name")
            name = " ".join(p for p in (first, last) if p and p != ".") or "—"
            email = self._invite_field(invite, "external_email", "email").lower()

            group_id = self._invite_field(invite, "attendee_group_id")
            if group_id:
                group_name = group_name_map.get(group_id, f"id={group_id}")
            else:
                group_name = "—"

            qr = self._invite_field(
                invite,
                "external_qr_string", "external_qr", "qr_string", "qr",
            )
            external_id = self._invite_field(invite, "external_id")

            qr_missing = (not qr) or qr.startswith(self.BRELLA_FALLBACK_PREFIX)

            if qr_missing:
                tag = "missing"
                missing_count += 1
            else:
                # Zebra stripe OK rows for readability.
                tag = "ok_alt" if (total_count % 2) else "ok"

            total_count += 1

            ticket = self._csv_ticket_map.get(email, "—")

            if filter_missing and not qr_missing:
                continue
            if search_q:
                haystack = f"{name} {email} {group_name} {ticket} {qr}".lower()
                if search_q not in haystack:
                    continue

            invite_id = str(invite.get("id", "")).strip()
            if not invite_id:
                continue

            qr_display = qr if len(qr) <= 32 else qr[:29] + "..."
            self.tree.insert(
                "", "end", iid=invite_id,
                values=(
                    email or "—",
                    ticket or "—",
                    group_name,
                    qr_display or "—",
                    invite_id,
                ),
                tags=(tag,),
            )

        self.total_var.set(f"{total_count} invites")
        self.missing_var.set(f"{missing_count} missing")
        self._missing_label.config(fg=WARN if missing_count else TEXT_TER)

        # Redraw column separators on top of the refreshed content.
        self.tree.after_idle(self._draw_column_separators)

        # Clear selection-dependent buttons since the tree was rebuilt.
        self._update_action_buttons()

    def _on_select(self, _event=None):
        self._update_action_buttons()

    def _update_action_buttons(self):
        invite = self._selected_invite()
        if not invite:
            self.fix_btn.config(state="disabled")
            return

        email = self._invite_field(invite, "external_email", "email").lower()
        if email and email in self._csv_qr_map:
            self.fix_btn.config(state="normal")
        else:
            self.fix_btn.config(state="disabled")

    def _selected_invite(self):
        sel = self.tree.selection()
        if not sel:
            return None
        invite_id = sel[0]
        for invite in self._invites:
            if str(invite.get("id", "")).strip() == invite_id:
                return invite
        return None

    # --- Patch actions ---

    def _fix_from_csv(self):
        invite = self._selected_invite()
        if not invite:
            return
        email = self._invite_field(invite, "external_email", "email").lower()
        expected_qr = self._csv_qr_map.get(email)
        if not expected_qr:
            self._log(f"[WARN] No 3cket CSV row for {email or '(no email)'} — use 'Edit QR...' instead.")
            return

        invite_id = str(invite.get("id")).strip()
        name = self._invite_label(invite)
        self._log(f"[INFO] Fixing QR for {name} (invite {invite_id}) -> {expected_qr[:48]}")
        self._patch_qr(invite_id, expected_qr)

    def _edit_qr_dialog(self):
        invite = self._selected_invite()
        if not invite:
            return

        current_qr = self._invite_field(invite, "external_qr_string")
        email = self._invite_field(invite, "external_email", "email").lower()
        invite_id = str(invite.get("id")).strip()
        expected = self._csv_qr_map.get(email, "")

        dlg = tk.Toplevel(self.frame)
        dlg.title(f"Edit QR — invite {invite_id}")
        dlg.configure(bg=BG)
        dlg.transient(self.frame.winfo_toplevel())
        dlg.grab_set()
        _apply_dark_title_bar(dlg)

        pad = 12
        wrap = tk.Frame(dlg, bg=BG)
        wrap.pack(fill="both", expand=True, padx=pad, pady=pad)

        tk.Label(wrap, text=self._invite_label(invite),
                 font=FONT_BOLD, fg=TEXT, bg=BG, anchor="w").pack(fill="x")
        tk.Label(wrap, text=f"Invite id {invite_id} · {email or 'no email'}",
                 font=FONT_SMALL, fg=TEXT_TER, bg=BG, anchor="w").pack(fill="x", pady=(0, 8))

        tk.Label(wrap, text="Current QR string", font=FONT_SMALL,
                 fg=TEXT_SEC, bg=BG, anchor="w").pack(fill="x")
        cur_var = tk.StringVar(value=current_qr or "(empty)")
        tk.Entry(wrap, textvariable=cur_var, font=FONT_MONO, bg=BG, fg=TEXT_TER,
                 insertbackground=TEXT,
                 relief="flat", bd=SP_MD,
                 highlightthickness=1, highlightbackground=SURFACE_RAISED,
                 state="readonly", readonlybackground=BG
                 ).pack(fill="x", ipady=SP_SM, pady=(1, SP_MD))

        tk.Label(wrap, text="New QR string", font=FONT_SMALL,
                 fg=TEXT_SEC, bg=BG, anchor="w").pack(fill="x")
        new_var = tk.StringVar(value=expected or current_qr)
        entry = tk.Entry(wrap, textvariable=new_var, font=FONT_MONO, bg=BG, fg=TEXT,
                         insertbackground=TEXT,
                         relief="flat", bd=SP_MD,
                         highlightthickness=1, highlightbackground=SURFACE_RAISED,
                         highlightcolor=ACCENT, width=60)
        entry.pack(fill="x", ipady=SP_SM, pady=(1, SP_MD))
        entry.focus_set()
        entry.icursor("end")

        if expected:
            tk.Label(wrap,
                     text=f"Tip: 3cket CSV expects '{expected[:40]}{'...' if len(expected) > 40 else ''}'",
                     font=FONT_SMALL, fg=TEXT_TER, bg=BG, anchor="w"
                     ).pack(fill="x", pady=(0, 8))

        btn_row = tk.Frame(wrap, bg=BG)
        btn_row.pack(fill="x", pady=(4, 0))

        def do_save():
            value = new_var.get().strip()
            if not value:
                self._log("[WARN] QR string is empty — aborting.")
                return
            dlg.destroy()
            self._patch_qr(invite_id, value)

        save_btn = make_button(btn_row, "Save", command=do_save)
        save_btn.pack(side="right")
        cancel_btn = make_button(btn_row, "Cancel", command=dlg.destroy)
        cancel_btn.pack(side="right", padx=(0, ACTION_BTN_GAP))

        entry.bind("<Return>", lambda e: do_save())
        dlg.bind("<Escape>", lambda e: dlg.destroy())

    def _patch_qr(self, invite_id, new_qr):
        if self._loading:
            return

        def _thread():
            try:
                import api
                api.API_KEY = os.environ.get("BRELLA_API_KEY", api.API_KEY)
                api.ORG_ID = os.environ.get("BRELLA_ORG_ID", api.ORG_ID)
                api.EVENT_ID = os.environ.get("BRELLA_EVENT_ID", api.EVENT_ID)
                headers = api.build_request_headers()
                payload = {"event_invite": {"external_qr_string": new_qr}}
                status, resp = api.update_invite(
                    api.build_update_url(invite_id), headers, payload,
                )
                if status in (200, 201):
                    self._log(f"[OK] PATCH invite {invite_id} -> QR set ({status}).")
                    self._update_cached_qr(invite_id, new_qr)
                    self.frame.after(0, self._refresh_display)
                else:
                    self._log(
                        f"[ERROR] PATCH {invite_id} failed: {status} — {resp[:200]}"
                    )
            except Exception as exc:
                self._log(f"[ERROR] PATCH {invite_id} exception: {exc}")

        threading.Thread(target=_thread, daemon=True).start()

    def _update_cached_qr(self, invite_id, new_qr):
        for invite in self._invites:
            if str(invite.get("id", "")).strip() != invite_id:
                continue
            event_invite = invite.get("event_invite")
            if isinstance(event_invite, dict):
                event_invite["external_qr_string"] = new_qr
            attributes = invite.get("attributes")
            if isinstance(attributes, dict):
                # Write back to whichever key variant exists so UI reflects the change.
                if "external-qr-string" in attributes:
                    attributes["external-qr-string"] = new_qr
                if "external_qr_string" in attributes:
                    attributes["external_qr_string"] = new_qr
                if "external-qr-string" not in attributes and "external_qr_string" not in attributes:
                    attributes["external_qr_string"] = new_qr
            if "external_qr_string" in invite:
                invite["external_qr_string"] = new_qr
            return

    # --- Helpers ---

    def _invite_label(self, invite):
        first = self._invite_field(invite, "external_first_name")
        last = self._invite_field(invite, "external_last_name")
        name = " ".join(p for p in (first, last) if p and p != ".")
        email = self._invite_field(invite, "external_email", "email").lower()
        if name and email:
            return f"{name} <{email}>"
        if name:
            return name
        if email:
            return email
        return f"invite {invite.get('id', '?')}"

    def _set_busy(self, busy):
        state = "disabled" if busy else "normal"
        self.refresh_btn.config(state=state)
        self.browse_btn.config(state=state)
        if busy:
            self.fix_btn.config(state="disabled")
        else:
            self._update_action_buttons()

    def _log(self, msg):
        if self._log_callback:
            self.frame.after(0, lambda: self._log_callback(msg))
        else:
            print(msg)


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

        # Log text — smaller, muted body; only the [label] carries color.
        _configure_ttk_styles()
        log_wrap = tk.Frame(self._log_frame, bg=SURFACE)
        log_wrap.pack(fill="both", expand=True, padx=SP_SM, pady=(SP_SM, SP_XS))
        log_wrap.rowconfigure(0, weight=1)
        log_wrap.columnconfigure(0, weight=1)

        log_font = ("Poppins", 8)
        self.log_text = tk.Text(log_wrap, font=log_font,
                                bg="#0c0c12", fg=TEXT_TER,
                                relief="flat", wrap="word",
                                insertbackground=ACCENT_LIGHT,
                                state="disabled", padx=SP_MD, pady=SP_MD)
        self.log_text.grid(row=0, column=0, sticky="nsew")

        log_vsb = ttk.Scrollbar(log_wrap, orient="vertical",
                                style="Dark.Vertical.TScrollbar",
                                command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_vsb.set)
        log_vsb.grid(row=0, column=1, sticky="ns")

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
            font=FONT_BOLD,
            fg=TEXT_SEC,
            bg=SURFACE,
            anchor="w",
        )
        self._log_status_label.pack(side="left")

        self._panel_action_rows = {}

        # Log tags: muted body + colored bracket labels. (No timestamps.)
        self.log_text.tag_configure("body", foreground=TEXT_SEC)
        self.log_text.tag_configure("highlight", foreground=ACCENT_LIGHT)
        self.log_text.tag_configure("label_add", foreground=SUCCESS)
        self.log_text.tag_configure("label_update", foreground=ACCENT_LIGHT)
        self.log_text.tag_configure("label_remove", foreground=DANGER)
        self.log_text.tag_configure("label_skip", foreground=TEXT_TER)
        self.log_text.tag_configure("label_dup", foreground=DANGER)
        self.log_text.tag_configure("label_missing", foreground=WARN)
        self.log_text.tag_configure("label_ok", foreground=SUCCESS)
        self.log_text.tag_configure("label_error", foreground=DANGER)
        self.log_text.tag_configure("label_warn", foreground=WARN)
        self.log_text.tag_configure("label_info", foreground=TEXT_SEC)
        self.log_text.tag_configure("label_preview", foreground=ACCENT_LIGHT)

        # --- Setup tab ---
        self._add_nav(sidebar, "Setup")
        setup = SetupTab(self.content, log_callback=self.log, app=self)
        self._setup_tab = setup
        self.panels["Setup"] = setup.frame
        if getattr(setup, "action_row", None) is not None:
            self._panel_action_rows["Setup"] = setup.action_row

        # --- Debug tab (right below Setup, no separator) ---
        self._add_nav(sidebar, "Debug")
        debug = DebugTab(self.content, app=self, log_callback=self.log)
        self._debug_tab = debug
        self.panels["Debug"] = debug.frame
        if getattr(debug, "action_row", None) is not None:
            self._panel_action_rows["Debug"] = debug.action_row

        nav_sep = tk.Frame(sidebar, bg=SURFACE_RAISED, height=1)
        nav_sep.pack(fill="x", padx=16, pady=(6, 6))

        # --- Sync tabs ---
        _default_csvs = {
            "Participants": BASE_DIR / "data" / "participants.csv",
            "Speakers": BASE_DIR / "data" / "speakers.csv",
            "Schedule": BASE_DIR / "data" / "schedule.csv",
        }

        for name, desc, prune, staff_only, remove, func, en, fields in [
            (
                "Participants",
                "Sync 3cket participants to Brella.",
                True, True, True,
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
                True, False, True,
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
                "Schedule",
                "Sync event sessions to Brella.",
                True, False, False,  # Remove toggle hidden — never prune sessions.
                self._run_schedule,
                True,
                [
                    ("date", True), ("start_time", True), ("duration", True),
                    ("title", True), ("content", False), ("track", True),
                    ("speakers", False),
                ],
            ),
        ]:
            self._add_nav(sidebar, name)
            tab = SyncTab(self.content, name, desc, has_prune=prune,
                          has_staff_only=staff_only, has_remove=remove,
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
        ratio_width = int(total_width * SIDEBAR_WIDTH_RATIO)
        target_width = max(SIDEBAR_W, min(SIDEBAR_MAX_W, ratio_width))
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

    # Parsers for the backend's log prefixes. Both English (canonical) and
    # legacy Portuguese phrasings are matched so older messages still render
    # as clean labels. Order matters — more specific patterns first.
    _LOG_PATTERNS = [
        # --- preview (line-ref may be a number or '?' when not tracked) ---
        (r'^\[PREVIEW\]\s*line\s*[\d\?]+:\s*would add\s*(.*)$', 'add'),
        (r'^\[PREVIEW\]\s*line\s*[\d\?]+:\s*would update\s*(.*)$', 'update'),
        (r'^\[PREVIEW\]\s*Would remove:\s*(.*)$', 'remove'),
        (r'^\[PREVIEW\]\s*would remove\s*(.*)$', 'remove'),
        (r'^\[PREVIEW\]\s*linha\s*\d+:\s*ADICIONARIA\s*(.*)$', 'add'),
        (r'^\[PREVIEW\]\s*linha\s*\d+:\s*ATUALIZARIA\s*(.*)$', 'update'),
        (r'^\[PREVIEW\]\s*REMOVERIA\s*(.*)$', 'remove'),
        # --- skip (skip-existing mode, no-changes, preview or real) ---
        (r'^\[SKIP\]\s*(.*)$', 'skip'),
        (r'^\[INFO\]\s*skip(?:ped|ping| )? \(already exists\):\s*(.*)$', 'skip'),
        (r'^\[INFO\]\s*would skip \(already exists\):\s*(.*)$', 'skip'),
        (r'^\[INFO\]\s*would skip \(existing, changes available\):\s*(.*)$', 'skip'),
        (r'^\[INFO\]\s*skipped \(existing, changes available\):\s*(.*)$', 'skip'),
        (r'^\[INFO\]\s*no changes:\s*(.*)$', 'skip'),
        (r'^\[INFO\]\s*IGNORA\w*\s*\(ja existe\):\s*(.*)$', 'skip'),
        # --- duplicate ---
        (r'^\[DUP\]\s*(.*)$', 'dup'),
        # --- missing info (no email / no id) ---
        (r'^\[SKIPPED\]\s*line\s*\d+:\s*(.*)$', 'missing'),
        (r'^\[IGNORADO\]\s*linha\s*\d+:\s*participante sem email\s*-\s*(.*)$', 'missing'),
        (r'^\[IGNORADO\]\s*linha\s*\d+:\s*participante sem ID 3cket\s*-\s*(.*)$', 'missing'),
        (r'^\[IGNORADO\]\s*linha\s*\d+:\s*(.*)$', 'missing'),
        # --- real sync confirmations ---
        (r'^\[OK(?:\s+\d+)?\]\s*ADDED:\s*(.*)$', 'add'),
        (r'^\[OK(?:\s+\d+)?\]\s*UPDATED:\s*(.*)$', 'update'),
        (r'^\[OK(?:\s+\d+)?\]\s*REMOVED:\s*(.*)$', 'remove'),
        (r'^\[OK(?:\s+\d+)?\]\s*ADICIONADO:\s*(.*)$', 'add'),
        (r'^\[OK(?:\s+\d+)?\]\s*ATUALIZADO:\s*(.*)$', 'update'),
        (r'^\[OK(?:\s+\d+)?\]\s*REMOVIDO:\s*(.*)$', 'remove'),
        (r'^\[OK(?:\s+\d+)?\]\s*(.*)$', 'ok'),
        # --- errors / warnings / info ---
        (r'^\[ERROR\]\s*line\s*[\d\?]+\s*(.*)$', 'error'),
        (r'^\[ERROR\]\s*(.*)$', 'error'),
        (r'^\[ERRO\]\s*(.*)$', 'error'),
        (r'^\[WARN\]\s*(.*)$', 'warn'),
        (r'^\[AVISO\]\s*(.*)$', 'warn'),
        (r'^\[INFO\]\s*(.*)$', 'info'),
        (r'^\[SIMULACAO\]\s*linha\s*\d+:\s*(.*)$', 'preview'),
        (r'^\[SIMULATION\]\s*line\s*\d+:\s*(.*)$', 'preview'),
        # case-insensitive tag variants
        (r'^\[add\]\s*(.*)$', 'add'),
        (r'^\[update\]\s*(.*)$', 'update'),
        (r'^\[remove\]\s*(.*)$', 'remove'),
        (r'^\[skip\]\s*(.*)$', 'skip'),
        (r'^\[missing\]\s*(.*)$', 'missing'),
        (r'^\[dup\]\s*(.*)$', 'dup'),
        (r'^\[ok\]\s*(.*)$', 'ok'),
        (r'^\[error\]\s*(.*)$', 'error'),
        (r'^\[warn\]\s*(.*)$', 'warn'),
        (r'^\[info\]\s*(.*)$', 'info'),
        (r'^\[preview\]\s*(.*)$', 'preview'),
    ]

    def _parse_log(self, msg):
        """Return (label, body). label is 'add'/'update'/'remove'/'skip'/
        'missing'/'ok'/'error'/'warn'/'info'/'preview' or '' for untagged."""
        import re
        stripped = msg.strip()
        if not stripped:
            return "", ""
        for pattern, label in self._LOG_PATTERNS:
            m = re.match(pattern, stripped)
            if m:
                return label, m.group(1).strip()
        return "", stripped

    def log(self, msg):
        import re
        label, body = self._parse_log(msg)

        self.log_text.config(state="normal")
        if label:
            self.log_text.insert("end", f"[{label}] ", (f"label_{label}",))
        if body:
            # Split body on «highlighted» portions so we can tag them pink.
            for piece in re.split(r'(«[^»]*»)', body):
                if piece.startswith("«") and piece.endswith("»") and len(piece) >= 2:
                    self.log_text.insert("end", piece[1:-1], ("highlight",))
                else:
                    self.log_text.insert("end", piece, ("body",))
        self.log_text.insert("end", "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

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
        csv_path = Path(tab.csv_path.get())
        api.prepare_csv(csv_path, download_csv=False, log_callback=self.log)
        if tab.dry_run.get():
            result = api.preview_sync_v4(
                csv_path,
                prune_missing=tab.prune.get(),
                update_existing=tab.update_existing.get(),
                staff_only=tab.staff_only.get(),
                log_callback=self.log,
            )
        else:
            result = api.run_sync_v4(
                csv_path, dry_run=False,
                prune_missing=tab.prune.get(),
                update_existing=tab.update_existing.get(),
                staff_only=tab.staff_only.get(),
                log_callback=self.log,
            )
        if result:
            self._apply_sync_result(tab, result, missing_key="missing_email_participants")

    def _run_speakers(self, tab):
        from speakers import run_speakers_sync
        csv_path = Path(tab.csv_path.get())
        result = run_speakers_sync(
            csv_path, dry_run=tab.dry_run.get(),
            prune_missing=tab.prune.get(),
            update_existing=tab.update_existing.get(),
            log_callback=self.log,
        )
        if result:
            self._apply_sync_result(tab, result, missing_key="missing_email_participants")

    def _run_schedule(self, tab):
        from schedule_sync import run_schedule_sync
        csv_path = Path(tab.csv_path.get())
        result = run_schedule_sync(
            csv_path, dry_run=tab.dry_run.get(),
            prune_missing=tab.prune.get(),
            update_existing=tab.update_existing.get(),
            log_callback=self.log,
        )
        if result:
            # Show "Only in Brella" sessions in the Removed card.
            only_in_brella = result.get("only_in_brella", []) or []
            result["removed_participants"] = only_in_brella
            tab.card_removed_title.config(text="Only in Brella")
            self._apply_sync_result(tab, result, missing_key="unmatched_speakers")

    def _apply_sync_result(self, tab, result, missing_key):
        added_list = result.get("added_participants", []) or []
        updated_list = result.get("updated_participants", []) or []
        skipped_list = result.get("skipped_participants", []) or []
        removed_list = result.get("removed_participants", []) or []
        missing_list = result.get(missing_key, []) or []
        duplicate_list = result.get("duplicate_participants", []) or []
        tab.update_summary(
            added=len(added_list), updated=len(updated_list),
            skipped=len(skipped_list), removed=len(removed_list),
            missing=len(missing_list), duplicate=len(duplicate_list),
        )
        tab.update_details(
            added=added_list, updated=updated_list, skipped=skipped_list,
            removed=removed_list, missing=missing_list, duplicate=duplicate_list,
        )

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
