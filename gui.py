"""
SIMsync GUI — local desktop app to sync event CSVs to Brella.
"""

import datetime
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog
from pathlib import Path

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
FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_SMALL = ("Segoe UI", 9)
FONT_MONO = ("Consolas", 9)
FONT_TITLE = ("Segoe UI", 14, "bold")
FONT_SECTION = ("Segoe UI", 8, "bold")


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


# --- Card helper ---

def make_card(parent):
    card = tk.Frame(parent, bg=SURFACE, highlightbackground=SURFACE_RAISED, highlightthickness=1)
    card.pack(fill="x", padx=24, pady=(0, 8))
    return card


def card_title(card, text):
    tk.Label(card, text=text, font=FONT_SECTION, fg=ACCENT, bg=SURFACE,
             anchor="w").pack(fill="x", padx=12, pady=(10, 4))


def make_field(parent, label, var, show=None, placeholder=""):
    tk.Label(parent, text=label, font=FONT_SMALL, fg=TEXT_SEC, bg=SURFACE,
             anchor="w").pack(fill="x")
    kw = dict(textvariable=var, font=FONT_MONO, bg=BG, fg=TEXT, insertbackground=TEXT,
              relief="flat", highlightthickness=1, highlightbackground=SURFACE_RAISED,
              highlightcolor=ACCENT)
    if show:
        kw["show"] = show
    entry = tk.Entry(parent, **kw)
    entry.pack(fill="x", ipady=5, pady=(2, 6))
    return entry


# --- Setup Tab ---

class SetupTab:
    def __init__(self, parent, log_callback=None):
        self.log_callback = log_callback
        self.frame = tk.Frame(parent, bg=BG)

        # Header
        hdr = tk.Frame(self.frame, bg=BG)
        hdr.pack(fill="x", padx=24, pady=(20, 4))
        tk.Label(hdr, text="Setup", font=FONT_TITLE, fg=TEXT, bg=BG).pack(side="left")

        tk.Label(self.frame, text="Configure your Brella API credentials. Saved to .env file.",
                 font=FONT_SMALL, fg=TEXT_SEC, bg=BG).pack(fill="x", padx=24, pady=(0, 16))

        # Brella card
        card = make_card(self.frame)
        card_title(card, "BRELLA API")
        inner = tk.Frame(card, bg=SURFACE)
        inner.pack(fill="x", padx=12, pady=(0, 10))

        self.api_key = tk.StringVar(value=load_env_value("BRELLA_API_KEY"))
        self.org_id = tk.StringVar(value=load_env_value("BRELLA_ORG_ID"))
        self.event_id = tk.StringVar(value=load_env_value("BRELLA_EVENT_ID"))

        make_field(inner, "API Key", self.api_key, show="*")
        row = tk.Frame(inner, bg=SURFACE)
        row.pack(fill="x")
        left = tk.Frame(row, bg=SURFACE)
        left.pack(side="left", fill="x", expand=True, padx=(0, 4))
        right = tk.Frame(row, bg=SURFACE)
        right.pack(side="right", fill="x", expand=True, padx=(4, 0))
        make_field(left, "Org ID", self.org_id)
        make_field(right, "Event ID", self.event_id)

        # Save button
        actions = tk.Frame(self.frame, bg=BG)
        actions.pack(fill="x", padx=24, pady=(4, 0))
        tk.Button(actions, text="Save", font=FONT_BOLD, bg=ACCENT, fg="white",
                  activebackground=ACCENT_LIGHT, activeforeground="white",
                  relief="flat", cursor="hand2", padx=20, pady=8,
                  command=self._save).pack(fill="x")

        self.status_var = tk.StringVar(value="")
        self.status_label = tk.Label(self.frame, textvariable=self.status_var, font=FONT_SMALL,
                                     fg=TEXT_SEC, bg=SURFACE, anchor="w", padx=10, pady=6)
        self.status_label.pack(fill="x", padx=24, pady=(8, 0))

    def _save(self):
        save_env_values({
            "BRELLA_API_KEY": self.api_key.get().strip(),
            "BRELLA_ORG_ID": self.org_id.get().strip(),
            "BRELLA_EVENT_ID": self.event_id.get().strip(),
        })
        # Also update os.environ so api.py picks it up without restart
        os.environ["BRELLA_API_KEY"] = self.api_key.get().strip()
        os.environ["BRELLA_ORG_ID"] = self.org_id.get().strip()
        os.environ["BRELLA_EVENT_ID"] = self.event_id.get().strip()

        self.status_var.set("Saved to .env")
        self.status_label.config(fg=SUCCESS)
        if self.log_callback:
            self.log_callback("Setup saved to .env")


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

        # Header
        hdr = tk.Frame(self.frame, bg=BG)
        hdr.pack(fill="x", padx=24, pady=(20, 4))
        tk.Label(hdr, text=name, font=FONT_TITLE, fg=TEXT, bg=BG, anchor="w").pack(side="left")
        if not enabled:
            tk.Label(hdr, text="COMING SOON", font=FONT_SECTION, fg=TEXT_TER,
                     bg=SURFACE_RAISED, padx=8, pady=2).pack(side="right")

        tk.Label(self.frame, text=description, font=FONT_SMALL, fg=TEXT_SEC, bg=BG,
                 anchor="w").pack(fill="x", padx=24, pady=(0, 16))

        # 3cket cookie card (participants only)
        if has_cookie:
            cookie_card = make_card(self.frame)
            card_title(cookie_card, "3CKET")
            cookie_inner = tk.Frame(cookie_card, bg=SURFACE)
            cookie_inner.pack(fill="x", padx=12, pady=(0, 10))

            self.dl_cb = tk.Checkbutton(cookie_inner, text="Download CSV from 3cket instead of local file",
                                        variable=self.download_from_3cket, font=FONT_SMALL,
                                        fg=TEXT_SEC, bg=SURFACE, selectcolor=BG,
                                        activebackground=SURFACE, activeforeground=TEXT,
                                        anchor="w", command=self._toggle_source)
            self.dl_cb.pack(fill="x")

            self.cookie_entry = make_field(cookie_inner, "Session Cookie", self.cookie, show="*")

        # CSV picker
        csv_card = make_card(self.frame)
        card_title(csv_card, "CSV FILE")
        csv_row = tk.Frame(csv_card, bg=SURFACE)
        csv_row.pack(fill="x", padx=12, pady=(0, 10))

        self.path_entry = tk.Entry(csv_row, textvariable=self.csv_path, font=FONT_MONO,
                                   bg=BG, fg=TEXT, insertbackground=TEXT,
                                   relief="flat", highlightthickness=1,
                                   highlightbackground=SURFACE_RAISED,
                                   highlightcolor=ACCENT)
        self.path_entry.pack(side="left", fill="x", expand=True, ipady=6)

        self.browse_btn = tk.Button(csv_row, text="Browse", font=FONT_SMALL, bg=SURFACE_RAISED,
                                    fg=TEXT, activebackground=ACCENT, activeforeground="white",
                                    relief="flat", cursor="hand2", padx=12, pady=4,
                                    command=self._browse)
        self.browse_btn.pack(side="right", padx=(8, 0))

        # Options
        opts = make_card(self.frame)
        card_title(opts, "OPTIONS")
        opts_inner = tk.Frame(opts, bg=SURFACE)
        opts_inner.pack(fill="x", padx=12, pady=(0, 10))

        self.dry_cb = tk.Checkbutton(opts_inner, text="Dry run (preview only)",
                                     variable=self.dry_run, font=FONT_SMALL,
                                     fg=TEXT_SEC, bg=SURFACE, selectcolor=BG,
                                     activebackground=SURFACE, activeforeground=TEXT,
                                     anchor="w")
        self.dry_cb.pack(fill="x")

        if has_prune:
            self.prune_cb = tk.Checkbutton(opts_inner, text="Prune missing (remove from Brella if not in CSV)",
                                           variable=self.prune, font=FONT_SMALL,
                                           fg=TEXT_SEC, bg=SURFACE, selectcolor=BG,
                                           activebackground=SURFACE, activeforeground=TEXT,
                                           anchor="w")
            self.prune_cb.pack(fill="x")

        # Action buttons
        actions = tk.Frame(self.frame, bg=BG)
        actions.pack(fill="x", padx=24, pady=(4, 0))

        self.preview_btn = tk.Button(actions, text="Preview", font=FONT_BOLD,
                                     bg=SURFACE_RAISED, fg=TEXT,
                                     activebackground=ACCENT, activeforeground="white",
                                     relief="flat", cursor="hand2", padx=20, pady=8,
                                     command=lambda: self._run(dry_run=True))
        self.preview_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.import_btn = tk.Button(actions, text="Import", font=FONT_BOLD,
                                    bg=ACCENT, fg="white",
                                    activebackground=ACCENT_LIGHT, activeforeground="white",
                                    relief="flat", cursor="hand2", padx=20, pady=8,
                                    command=lambda: self._run(dry_run=False))
        self.import_btn.pack(side="right", fill="x", expand=True, padx=(4, 0))

        # Status
        self.status_var = tk.StringVar(value="Ready")
        self.status_label = tk.Label(self.frame, textvariable=self.status_var, font=FONT_SMALL,
                                     fg=TEXT_SEC, bg=SURFACE, anchor="w", padx=10, pady=6)
        self.status_label.pack(fill="x", padx=24, pady=(8, 0))

        # Summary cards
        summary_row = tk.Frame(self.frame, bg=BG)
        summary_row.pack(fill="x", padx=24, pady=(8, 0))
        summary_row.columnconfigure(0, weight=1)
        summary_row.columnconfigure(1, weight=1)
        summary_row.columnconfigure(2, weight=1)

        self.card_added, self.card_added_title = self._make_summary_card(summary_row, "ADDED", "0", SUCCESS, 0)
        self.card_removed, _ = self._make_summary_card(summary_row, "REMOVED", "0", DANGER, 1)
        self.card_missing, _ = self._make_summary_card(summary_row, "MISSING INFO", "0", "#f0a030", 2)

        if not enabled:
            self.preview_btn.config(state="disabled")
            self.import_btn.config(state="disabled")
            self.browse_btn.config(state="disabled")
            self.path_entry.config(state="disabled")
            self.dry_cb.config(state="disabled")

    def _make_summary_card(self, parent, title, value, color, col):
        card = tk.Frame(parent, bg=SURFACE, highlightbackground=SURFACE_RAISED,
                        highlightthickness=1)
        card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 4, 0))
        title_label = tk.Label(card, text=title, font=("Segoe UI", 7, "bold"), fg=TEXT_TER,
                               bg=SURFACE)
        title_label.pack(padx=10, pady=(8, 0))
        count_label = tk.Label(card, text=value, font=("Segoe UI", 18, "bold"),
                               fg=color, bg=SURFACE)
        count_label.pack(padx=10, pady=(0, 8))
        return count_label, title_label

    def update_summary(self, added=0, removed=0, missing=0):
        def _update():
            self.card_added.config(text=str(added))
            self.card_added_title.config(text="TO SYNC" if self.dry_run.get() else "ADDED")
            self.card_removed.config(text=str(removed))
            self.card_missing.config(text=str(missing))
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
            self.frame.after(0, lambda: self._set_busy(False))

    def _set_busy(self, busy):
        state = "disabled" if busy else "normal"
        self.preview_btn.config(state=state)
        self.import_btn.config(state=state)
        if not (self.has_cookie and self.download_from_3cket.get()):
            self.browse_btn.config(state=state)

    def _set_status(self, text, color=TEXT_SEC):
        def _update():
            self.status_var.set(text)
            self.status_label.config(fg=color)
        self.frame.after(0, _update)

    def _log(self, msg):
        if hasattr(self, '_log_callback') and self._log_callback:
            self.frame.after(0, lambda: self._log_callback(msg))


# --- App ---

class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("SIMsync")
        self.root.geometry("920x660")
        self.root.configure(bg=BG)
        self.root.minsize(750, 520)

        # Set window icon
        try:
            ico_path = BASE_DIR / "simlogo.ico"
            if ico_path.exists():
                self.root.iconbitmap(str(ico_path))
            else:
                png_path = BASE_DIR / "simlogo.png"
                if png_path.exists():
                    img = tk.PhotoImage(file=str(png_path))
                    self.root.iconphoto(True, img)
        except Exception:
            pass

        # Main layout: sidebar left, right side split top/bottom
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="both", expand=True)

        # Sidebar
        sidebar = tk.Frame(outer, bg=SURFACE, width=180)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        # Brand with logo
        brand = tk.Frame(sidebar, bg=SURFACE)
        brand.pack(fill="x", padx=14, pady=(16, 6))

        self._logo_img = None
        try:
            png_path = BASE_DIR / "simlogo.png"
            if png_path.exists():
                self._logo_img = tk.PhotoImage(file=str(png_path))
                # Subsample to ~80px wide (natural aspect ratio)
                orig_w = self._logo_img.width()
                factor = max(1, orig_w // 80)
                self._logo_img = self._logo_img.subsample(factor, factor)
                tk.Label(brand, image=self._logo_img, bg=SURFACE).pack(anchor="w", pady=(0, 6))
        except Exception:
            pass

        tk.Label(brand, text="SIMsync", font=("Segoe UI", 13, "bold"), fg=TEXT,
                 bg=SURFACE).pack(anchor="w")
        tk.Label(brand, text="EVENT PLATFORM", font=("Segoe UI", 7, "bold"),
                 fg=TEXT_TER, bg=SURFACE).pack(anchor="w")

        sep = tk.Frame(sidebar, bg=SURFACE_RAISED, height=1)
        sep.pack(fill="x", padx=14, pady=(10, 10))

        # Nav
        self.nav_buttons = []
        self.panels = {}
        self.active_panel = None

        # Right side: content (top 3/5) + log (bottom 2/5)
        right = tk.PanedWindow(outer, orient="vertical", bg=SURFACE_RAISED,
                               sashwidth=2, sashrelief="flat")
        right.pack(side="left", fill="both", expand=True)

        # Content area (top)
        self.content = tk.Frame(right, bg=BG)
        right.add(self.content, stretch="always")

        # Log panel (bottom)
        log_frame = tk.Frame(right, bg=SURFACE)
        right.add(log_frame, stretch="never")

        # Set initial sash position after window renders
        def set_sash():
            h = self.root.winfo_height()
            if h > 1:
                right.sash_place(0, 0, int(h * 0.6))
        self.root.after(50, set_sash)

        log_header = tk.Frame(log_frame, bg=SURFACE)
        log_header.pack(fill="x", padx=10, pady=(6, 2))
        tk.Label(log_header, text="LOG", font=FONT_SECTION, fg=TEXT_SEC,
                 bg=SURFACE).pack(side="left")
        tk.Button(log_header, text="Clear", font=("Segoe UI", 8), bg=SURFACE,
                  fg=TEXT_TER, activebackground=SURFACE_RAISED, activeforeground=TEXT,
                  relief="flat", cursor="hand2", command=self._clear_log).pack(side="right")

        self.log_text = tk.Text(log_frame, font=FONT_MONO, bg="#0e0e14", fg=ACCENT_LIGHT,
                                relief="flat", wrap="word", insertbackground=ACCENT_LIGHT,
                                state="disabled", padx=10, pady=6)
        self.log_text.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        # --- Setup ---
        self._add_nav(sidebar, "Setup")
        setup = SetupTab(self.content, log_callback=self.log)
        self.panels["Setup"] = setup.frame

        nav_sep = tk.Frame(sidebar, bg=SURFACE_RAISED, height=1)
        nav_sep.pack(fill="x", padx=14, pady=(6, 6))
        tk.Label(sidebar, text="SYNC MODULES", font=("Segoe UI", 7, "bold"),
                 fg=TEXT_TER, bg=SURFACE).pack(fill="x", padx=14, pady=(0, 4))

        # --- Sync tabs ---
        for name, desc, prune, cookie, func, en in [
            ("Participants", "Sync 3cket participants to Brella.", True, True,
             self._run_participants, True),
            ("Speakers", "Import speaker profiles to Brella.", False, False, None, False),
            ("Sponsors", "Sync sponsor data to Brella.", False, False, None, False),
            ("Schedule", "Sync event sessions to Brella.", False, False, None, False),
        ]:
            self._add_nav(sidebar, name)
            tab = SyncTab(self.content, name, desc, has_prune=prune, has_cookie=cookie,
                          run_func=func, enabled=en)
            tab._log_callback = self.log
            self.panels[name] = tab.frame

        self._switch_panel("Setup")
        self.log("SIMsync ready.")

    def _add_nav(self, sidebar, name):
        btn = tk.Button(sidebar, text=name, font=FONT, fg=TEXT_SEC, bg=SURFACE,
                        activebackground=SURFACE_RAISED, activeforeground=TEXT,
                        relief="flat", anchor="w", padx=14, pady=8, cursor="hand2",
                        command=lambda n=name: self._switch_panel(n))
        btn.pack(fill="x", padx=6, pady=1)
        self.nav_buttons.append((name, btn))

    def _switch_panel(self, name):
        self.active_panel = name
        for panel_name, frame in self.panels.items():
            if panel_name == name:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
        for btn_name, btn in self.nav_buttons:
            if btn_name == name:
                btn.config(bg=SURFACE_RAISED, fg=ACCENT_LIGHT)
            else:
                btn.config(bg=SURFACE, fg=TEXT_SEC)

    def log(self, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text.config(state="normal")
        self.log_text.insert("end", f"{ts}  {msg}\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

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
            added = len(result.get("added_participants", []))
            removed = len(result.get("removed_participants", []))
            missing = len(result.get("missing_email_participants", []))
            # In dry-run, added/removed are empty — use processed as "to sync"
            if tab.dry_run.get():
                added = result.get("processed", 0)
            tab.update_summary(added=added, removed=removed, missing=missing)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
