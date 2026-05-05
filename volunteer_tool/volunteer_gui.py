"""
Volunteer Tool - participant import with a minimal connection setup.
"""

from __future__ import annotations

import ctypes
import csv
import importlib
import os
import queue
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib import error as url_error
from urllib import request as url_request

def get_runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


PROJECT_ROOT = get_runtime_root()
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_CSV = DATA_DIR / "participants.csv"
ENV_PATH = PROJECT_ROOT / ".env"

try:
    import api  # noqa: E402
except ModuleNotFoundError:
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))
    import api  # noqa: E402


# Main app visual language
BG = "#101016"
SURFACE = "#19191f"
SURFACE_RAISED = "#222229"
SURFACE_HOVER = "#2a2a33"
SURFACE_ALT = "#14141b"
BORDER = "#2a2a33"
TAB_BORDER = "#272733"
TEXT = "#f0f0f5"
TEXT_SEC = "#8e8e9a"
TEXT_TER = "#55555f"
ACCENT = "#e6007e"
ACCENT_LIGHT = "#ff3da5"
SUCCESS = "#2dd4a8"
DANGER = "#f85149"
WARN = "#f0a030"

# Poppins can look soft on some Windows setups; keep a crisp default.
FONT = ("Segoe UI", 10)
FONT_TITLE = ("Segoe UI Semibold", 11)
FONT_MONO = ("Consolas", 10)
SP_XS = 2
SP_SM = 4
SP_MD = 8
SP_LG = 12
SP_XL = 16
APP_MIN_WIDTH = 560
APP_MIN_HEIGHT = 620


def load_env_value(key: str, default: str = "") -> str:
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    return os.environ.get(key, default)


def save_env_values(updates: dict[str, str]) -> None:
    lines: list[str] = []
    existing_keys: set[str] = set()

    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in updates:
                    lines.append(f"{key}={updates[key]}")
                    existing_keys.add(key)
                    continue
            lines.append(line)

    for key, value in updates.items():
        if key not in existing_keys:
            lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for key, value in updates.items():
        os.environ[key] = value


def make_field(parent: tk.Widget, label: str, var: tk.StringVar, show: str | None = None) -> tk.Entry:
    parent_bg = parent.cget("bg")
    tk.Label(parent, text=label, font=FONT, fg=TEXT_SEC, bg=parent_bg, anchor="w").pack(fill="x", pady=(0, SP_XS))
    options = {
        "textvariable": var,
        "font": FONT,
        "bg": SURFACE_ALT,
        "fg": TEXT,
        "insertbackground": TEXT,
        "relief": "flat",
        "bd": 6,
        "highlightthickness": 1,
        "highlightbackground": BORDER,
        "highlightcolor": ACCENT,
    }
    if show:
        options["show"] = show
    entry = tk.Entry(parent, **options)
    entry.pack(fill="x", ipady=SP_SM, pady=(0, SP_MD))
    return entry


def make_card(parent: tk.Widget) -> tk.Frame:
    wrap = tk.Frame(parent, bg=SURFACE)
    wrap.pack(fill="both", expand=True)
    tk.Frame(wrap, bg=ACCENT, height=1).pack(fill="x")
    body = tk.Frame(wrap, bg=SURFACE, padx=SP_LG, pady=SP_LG)
    body.pack(fill="both", expand=True)
    return body


def enable_high_dpi() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class VolunteerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SIMsync Volunteer Tool")
        self.root.geometry(f"{APP_MIN_WIDTH}x{APP_MIN_HEIGHT}")
        self.root.configure(bg=BG)
        self.root.minsize(APP_MIN_WIDTH, APP_MIN_HEIGHT)

        self.csv_path = tk.StringVar(value=str(DEFAULT_CSV))
        self.preview_mode = tk.BooleanVar(value=True)
        self.import_scope = tk.StringVar(value="all")
        self.single_email = tk.StringVar(value="")
        self.running = False
        self._run_added_count = 0
        self._run_skipped_count = 0

        self.api_key = tk.StringVar(value=load_env_value("BRELLA_API_KEY", ""))
        self.org_id = tk.StringVar(value=load_env_value("BRELLA_ORG_ID", "1218"))
        self.event_id = tk.StringVar(value=load_env_value("BRELLA_EVENT_ID", "10672"))
        self.admin_token = tk.StringVar(value=load_env_value("BRELLA_ADMIN_ACCESS_TOKEN", ""))
        self.admin_client = tk.StringVar(value=load_env_value("BRELLA_ADMIN_CLIENT", ""))
        self.admin_uid = tk.StringVar(value=load_env_value("BRELLA_ADMIN_UID", ""))

        self._log_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._build_ui()
        self.api_key.trace_add("write", lambda *_: self._refresh_api_status_pill())
        self._refresh_api_status_pill()
        self.root.after(100, self._drain_log_queue)

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "TNotebook",
            background=BG,
            borderwidth=0,
            relief="flat",
            tabmargins=(0, 0, 0, 0),
            bordercolor=TAB_BORDER,
            lightcolor=TAB_BORDER,
            darkcolor=TAB_BORDER,
        )
        style.configure(
            "TNotebook.Tab",
            background=BG,
            foreground=TEXT_SEC,
            padding=(18, 10),
            borderwidth=1,
            relief="flat",
            font=FONT,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", SURFACE), ("active", SURFACE_RAISED)],
            foreground=[("selected", ACCENT_LIGHT), ("active", TEXT)],
            bordercolor=[("selected", TAB_BORDER), ("!selected", TAB_BORDER)],
            lightcolor=[("selected", TAB_BORDER), ("!selected", TAB_BORDER)],
            darkcolor=[("selected", TAB_BORDER), ("!selected", TAB_BORDER)],
            padding=[("selected", [18, 10]), ("!selected", [18, 10])],
            expand=[("selected", [0, 0, 0, 0]), ("!selected", [0, 0, 0, 0])],
        )

        outer = tk.Frame(self.root, bg=BG, padx=SP_SM, pady=SP_SM)
        outer.pack(fill="both", expand=True)

        # Global status (top-right, outside tab container).
        top_row = tk.Frame(outer, bg=BG)
        top_row.pack(fill="x", pady=(0, SP_XS))
        self.status_label = tk.Label(top_row, text="Idle", bg=BG, fg=TEXT_TER, font=FONT)
        self.status_label.pack(side="right")

        # Neutral, aligned tab container border.
        tabs_wrap = tk.Frame(outer, bg=TAB_BORDER, padx=1, pady=1)
        tabs_wrap.pack(fill="both", expand=True)
        notebook = ttk.Notebook(tabs_wrap)
        notebook.pack(fill="both", expand=True)

        import_page = tk.Frame(notebook, bg=BG)
        setup_page = tk.Frame(notebook, bg=BG)
        notebook.add(import_page, text="Import")
        notebook.add(setup_page, text="Setup")

        self._build_import_page(import_page)
        self._build_setup_page(setup_page)

    def _build_import_page(self, parent: tk.Frame) -> None:
        page = tk.Frame(parent, bg=BG)
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)

        content = tk.Frame(page, bg=BG)
        content.grid(row=0, column=0, sticky="nsew", padx=SP_SM, pady=SP_SM)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=0)
        content.rowconfigure(1, weight=1)

        controls = tk.Frame(content, bg=SURFACE, padx=SP_MD, pady=SP_MD)
        controls.grid(row=0, column=0, sticky="ew")

        csv_row = tk.Frame(controls, bg=SURFACE)
        csv_row.pack(fill="x")
        self.csv_entry = tk.Entry(
            csv_row,
            textvariable=self.csv_path,
            font=FONT,
            bg=SURFACE_ALT,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=6,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        self.csv_entry.pack(side="left", fill="x", expand=True, ipady=SP_SM)
        tk.Button(
            csv_row,
            text="Browse",
            font=FONT,
            bg=SURFACE_RAISED,
            fg=TEXT,
            activebackground=SURFACE_HOVER,
            activeforeground=TEXT,
            relief="flat",
            borderwidth=0,
            command=self._browse_csv,
            cursor="hand2",
            padx=SP_MD,
            pady=SP_SM + 1,
        ).pack(side="left", padx=(SP_SM, 0))

        action_row = tk.Frame(controls, bg=SURFACE)
        action_row.pack(fill="x", pady=(SP_SM, 0))
        scope_group = tk.Frame(action_row, bg=SURFACE)
        scope_group.pack(side="left")
        self.scope_all_btn = tk.Button(
            scope_group,
            text="All",
            command=lambda: self._set_scope("all"),
            font=FONT,
            relief="flat",
            bd=0,
            padx=SP_MD,
            pady=SP_SM + 1,
            cursor="hand2",
        )
        self.scope_all_btn.pack(side="left")
        self.scope_single_btn = tk.Button(
            scope_group,
            text="1",
            command=lambda: self._set_scope("single"),
            font=FONT,
            relief="flat",
            bd=0,
            padx=SP_MD,
            pady=SP_SM + 1,
            cursor="hand2",
        )
        self.scope_single_btn.pack(side="left", padx=(SP_XS, 0))

        self.single_email_entry = tk.Entry(
            action_row,
            textvariable=self.single_email,
            font=FONT,
            bg=SURFACE_ALT,
            fg=TEXT,
            disabledbackground=SURFACE_ALT,
            disabledforeground=TEXT_SEC,
            insertbackground=TEXT,
            relief="flat",
            bd=6,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        self.single_email_entry.pack(side="left", fill="x", expand=True, padx=(SP_SM, SP_SM), ipady=SP_SM)
        self.preview_action_btn = tk.Button(
            action_row,
            text="Preview",
            font=FONT,
            bg=SURFACE_RAISED,
            fg=TEXT,
            activebackground=SURFACE_HOVER,
            activeforeground=TEXT,
            relief="flat",
            borderwidth=0,
            command=lambda: self._start_run(preview=True),
            cursor="hand2",
            padx=SP_LG,
            pady=SP_SM + 1,
        )
        self.preview_action_btn.pack(side="left")

        self.run_btn = tk.Button(
            action_row,
            text="Import",
            font=FONT,
            bg=ACCENT,
            fg="#ffffff",
            activebackground=ACCENT_LIGHT,
            activeforeground="#ffffff",
            relief="flat",
            borderwidth=0,
            command=lambda: self._start_run(preview=False),
            cursor="hand2",
            padx=SP_LG,
            pady=SP_SM + 1,
        )
        self.run_btn.pack(side="left", padx=(SP_SM, 0))

        log_wrap = tk.Frame(content, bg=BG, padx=0, pady=0)
        log_wrap.grid(row=1, column=0, sticky="nsew", pady=(SP_SM, 0))
        self.log_text = tk.Text(
            log_wrap,
            bg=SURFACE_ALT,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            font=FONT_MONO,
            wrap="word",
            padx=SP_MD,
            pady=SP_MD,
        )
        self.log_text.tag_configure("added", foreground=SUCCESS)
        self.log_text.tag_configure("skipped", foreground=TEXT_SEC)
        self.log_text.pack(fill="both", expand=True)

    def _build_setup_page(self, parent: tk.Frame) -> None:
        page = tk.Frame(parent, bg=BG)
        page.pack(fill="both", expand=True)
        page.rowconfigure(0, weight=1)
        page.columnconfigure(0, weight=1)

        content = tk.Frame(page, bg=BG)
        content.grid(row=0, column=0, sticky="nsew", padx=SP_SM, pady=SP_SM)
        content.columnconfigure(0, weight=1)

        top_bar = tk.Frame(content, bg=BG)
        top_bar.pack(fill="x", pady=(0, SP_SM))
        status_col = tk.Frame(top_bar, bg=BG)
        status_col.pack(side="right")
        self._api_status_dot = tk.Frame(status_col, bg=DANGER, width=8, height=8)
        self._api_status_dot.pack(side="left", padx=(0, SP_SM))
        self._api_status_dot.pack_propagate(False)
        self._api_status_lbl = tk.Label(status_col, text="API key not set", font=FONT, fg=DANGER, bg=BG)
        self._api_status_lbl.pack(side="left")
        tk.Button(
            top_bar,
            text="Save",
            font=FONT,
            bg=ACCENT,
            fg="#ffffff",
            activebackground=ACCENT_LIGHT,
            activeforeground="#ffffff",
            relief="flat",
            borderwidth=0,
            command=self._save_connection,
            cursor="hand2",
            padx=SP_LG,
            pady=SP_XS,
        ).pack(side="left", padx=(0, SP_SM))
        tk.Button(
            top_bar,
            text="Test",
            font=FONT,
            bg=SURFACE_RAISED,
            fg=TEXT,
            activebackground=SURFACE_HOVER,
            activeforeground=TEXT,
            relief="flat",
            borderwidth=0,
            command=self._test_connection,
            cursor="hand2",
            padx=SP_LG,
            pady=SP_XS,
        ).pack(side="left")

        api_wrap = tk.Frame(content, bg=BG)
        api_wrap.pack(fill="x", expand=True, pady=(0, SP_SM))
        api_col = make_card(api_wrap)
        make_field(api_col, "API Key", self.api_key, show="*")

        ids_row = tk.Frame(api_col, bg=SURFACE)
        ids_row.pack(fill="x")
        ids_row.columnconfigure(0, weight=1, uniform="ids")
        ids_row.columnconfigure(1, weight=1, uniform="ids")
        ids_left = tk.Frame(ids_row, bg=SURFACE)
        ids_left.grid(row=0, column=0, sticky="nsew", padx=(0, SP_SM))
        ids_right = tk.Frame(ids_row, bg=SURFACE)
        ids_right.grid(row=0, column=1, sticky="nsew", padx=(SP_SM, 0))
        make_field(ids_left, "Org ID", self.org_id)
        make_field(ids_right, "Event ID", self.event_id)

        admin_wrap = tk.Frame(content, bg=BG)
        admin_wrap.pack(fill="x", expand=True)
        admin_col = make_card(admin_wrap)
        make_field(admin_col, "Access Token", self.admin_token, show="*")

        admin_row = tk.Frame(admin_col, bg=SURFACE)
        admin_row.pack(fill="x")
        admin_row.columnconfigure(0, weight=1, uniform="adm")
        admin_row.columnconfigure(1, weight=1, uniform="adm")
        adm_left = tk.Frame(admin_row, bg=SURFACE)
        adm_left.grid(row=0, column=0, sticky="nsew", padx=(0, SP_SM))
        adm_right = tk.Frame(admin_row, bg=SURFACE)
        adm_right.grid(row=0, column=1, sticky="nsew", padx=(SP_SM, 0))
        make_field(adm_left, "Client", self.admin_client)
        make_field(adm_right, "UID", self.admin_uid)
        self._api_status_var = tk.StringVar(value="")
        self._api_status_result = tk.Label(content, textvariable=self._api_status_var, font=FONT, fg=TEXT_SEC, bg=BG, anchor="w")
        self._api_status_result.pack(fill="x", pady=(SP_SM, 0))
        self._update_scope_ui()

    def _refresh_api_status_pill(self) -> None:
        loaded = bool(self.api_key.get().strip())
        self._api_status_dot.configure(bg=SUCCESS if loaded else DANGER)
        self._api_status_lbl.configure(
            text="API key loaded" if loaded else "API key not set",
            fg=SUCCESS if loaded else DANGER,
        )

    def _show_api_status(self, text: str, color: str) -> None:
        self._api_status_var.set(text)
        self._api_status_result.configure(fg=color)

    def _save_connection(self) -> None:
        updates = {
            "BRELLA_API_KEY": self.api_key.get().strip(),
            "BRELLA_ORG_ID": self.org_id.get().strip(),
            "BRELLA_EVENT_ID": self.event_id.get().strip(),
            "BRELLA_ADMIN_ACCESS_TOKEN": self.admin_token.get().strip(),
            "BRELLA_ADMIN_CLIENT": self.admin_client.get().strip(),
            "BRELLA_ADMIN_UID": self.admin_uid.get().strip(),
        }

        if not updates["BRELLA_ORG_ID"] or not updates["BRELLA_EVENT_ID"]:
            messagebox.showerror("Missing values", "Org ID and Event ID are required.")
            return

        save_env_values(updates)
        importlib.reload(api)
        self._refresh_api_status_pill()
        self._show_api_status("Saved to .env", SUCCESS)

    def _test_connection(self) -> None:
        def _run_test() -> None:
            org = self.org_id.get().strip()
            event = self.event_id.get().strip()
            api_key = self.api_key.get().strip()
            header_name = load_env_value("BRELLA_AUTH_HEADER_NAME", "Brella-API-Access-Token")
            user_agent = load_env_value("BRELLA_HTTP_USER_AGENT", "SIMsync")

            if not org or not event or not api_key:
                self.root.after(0, lambda: self._show_api_status("Missing API key, Org ID, or Event ID", WARN))
                return

            url = f"https://api.brella.io/api/integration/organizations/{org}/events/{event}"
            headers = {header_name: api_key, "User-Agent": user_agent}

            try:
                req = url_request.Request(url, headers=headers, method="GET")
                with url_request.urlopen(req, timeout=10) as response:
                    self.root.after(
                        0,
                        lambda: self._show_api_status(
                            f"Connected - event {event} (HTTP {response.status})",
                            SUCCESS,
                        ),
                    )
            except url_error.HTTPError as exc:
                self.root.after(0, lambda: self._show_api_status(f"API error: HTTP {exc.code}", DANGER))
            except Exception as exc:
                self.root.after(0, lambda: self._show_api_status(f"Connection failed: {exc}", DANGER))

        threading.Thread(target=_run_test, daemon=True).start()

    def _browse_csv(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select participants CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialdir=str(DATA_DIR if DATA_DIR.exists() else PROJECT_ROOT),
        )
        if selected:
            self.csv_path.set(selected)

    def _append_log(self, message: str) -> None:
        msg = (message or "").strip()
        if not msg:
            return

        lower = msg.lower()

        # Count only: added and skipped.
        is_added = ("[ok" in lower and "added:" in lower) or (
            "[preview]" in lower and "would add" in lower
        )
        is_skipped = "[skip]" in lower

        if not (is_added or is_skipped):
            return

        if is_added:
            self._run_added_count += 1
        elif is_skipped:
            self._run_skipped_count += 1

    def _append_run_summary(self) -> None:
        self._log_queue.put((f"Added ({self._run_added_count}):", "added"))
        self._log_queue.put(("", "added"))
        self._log_queue.put((f"Skipped ({self._run_skipped_count}):", "skipped"))

    def _update_scope_ui(self) -> None:
        single_mode = self.import_scope.get() == "single"
        self.single_email_entry.configure(state="normal" if single_mode else "disabled")
        self._apply_toolbar_toggle_styles()

    def _set_scope(self, value: str) -> None:
        self.import_scope.set(value)
        self._update_scope_ui()

    def _apply_toolbar_toggle_styles(self) -> None:
        all_on = self.import_scope.get() == "all"
        single_on = self.import_scope.get() == "single"
        self.scope_all_btn.configure(
            bg=ACCENT if all_on else SURFACE_RAISED,
            fg="#ffffff" if all_on else TEXT,
            activebackground=ACCENT_LIGHT if all_on else SURFACE_HOVER,
            activeforeground="#ffffff" if all_on else TEXT,
        )
        self.scope_single_btn.configure(
            bg=ACCENT if single_on else SURFACE_RAISED,
            fg="#ffffff" if single_on else TEXT,
            activebackground=ACCENT_LIGHT if single_on else SURFACE_HOVER,
            activeforeground="#ffffff" if single_on else TEXT,
        )

    def _drain_log_queue(self) -> None:
        while True:
            try:
                message, kind = self._log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_text.insert("end", message.rstrip() + "\n", kind)
            self.log_text.see("end")
        self.root.after(100, self._drain_log_queue)

    def _set_running_ui(self, running: bool) -> None:
        self.running = running
        state = "disabled" if running else "normal"
        self.run_btn.configure(state=state)
        self.preview_action_btn.configure(state=state)
        self.csv_entry.configure(state=state)
        self.scope_all_btn.configure(state=state)
        self.scope_single_btn.configure(state=state)
        if self.import_scope.get() == "single":
            self.single_email_entry.configure(state=state)
        self.status_label.configure(text="Running..." if running else "Idle", fg=ACCENT if running else TEXT_TER)

    def _start_run(self, preview: bool) -> None:
        if self.running:
            return
        self.preview_mode.set(preview)
        self._run_added_count = 0
        self._run_skipped_count = 0

        csv_path = Path(self.csv_path.get()).expanduser()
        if not csv_path.exists():
            messagebox.showerror("CSV not found", f"CSV file not found:\n{csv_path}")
            return
        if self.import_scope.get() == "single" and not self.single_email.get().strip():
            messagebox.showerror("Missing email", "Write an email to import only one participant.")
            return

        self.log_text.delete("1.0", "end")
        self._set_running_ui(True)
        threading.Thread(target=lambda: self._run_sync(preview), daemon=True).start()

    def _run_sync(self, preview: bool) -> None:
        csv_path = Path(self.csv_path.get()).expanduser()
        temp_csv_path: Path | None = None

        try:
            source_csv = csv_path
            if self.import_scope.get() == "single":
                target_email = self.single_email.get().strip().lower()
                filtered_csv, matches = self._build_single_email_csv(source_csv, target_email)
                temp_csv_path = filtered_csv
                csv_path = filtered_csv
                if matches > 1:
                    self._append_log(
                        f"[INFO] Found {matches} rows for {target_email}; using latest row only."
                    )
                else:
                    self._append_log(f"[INFO] Importing only: {target_email}")

            api.prepare_csv(csv_path, download_csv=False, log_callback=self._append_log)
            kwargs = {
                "csv_path": csv_path,
                "prune_missing": False,
                "update_existing": False,
                "staff_only": False,
                "log_callback": self._append_log,
                "reverse_csv": False,
                "stop_after_existing_skips": 0,
            }

            if preview:
                api.preview_sync_v4(**kwargs)
            else:
                api.run_sync_v4(dry_run=False, **kwargs)
            self._append_run_summary()
        except Exception as exc:
            self._append_log(f"[FATAL] {exc}")
        finally:
            if temp_csv_path and temp_csv_path.exists():
                try:
                    temp_csv_path.unlink()
                except Exception:
                    pass
            self.root.after(0, lambda: self._set_running_ui(False))

    def _build_single_email_csv(self, csv_path: Path, target_email: str) -> tuple[Path, int]:
        header_line: str | None = None
        matching_lines: list[str] = []

        with csv_path.open(mode="r", encoding="utf-8-sig", newline="") as handle:
            for raw_line in handle:
                if not raw_line.strip():
                    continue

                normalized_line = api.normalize_export_line(raw_line)
                row = next(csv.reader([normalized_line], delimiter=";"))

                if header_line is None:
                    header_line = raw_line
                    continue

                row_email = api.pick_email(row).strip().lower()
                if row_email == target_email:
                    matching_lines.append(raw_line)

        if header_line is None:
            raise RuntimeError("CSV appears to be empty.")
        if not matching_lines:
            raise RuntimeError(f"Email not found in CSV: {target_email}")

        selected_line = matching_lines[-1]
        temp = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            suffix=".csv",
            prefix="volunteer_single_",
            delete=False,
        )
        with temp:
            temp.write(header_line)
            temp.write(selected_line)

        return Path(temp.name), len(matching_lines)


def main() -> None:
    enable_high_dpi()
    root = tk.Tk()
    root.option_add("*Font", FONT)
    _app = VolunteerApp(root)
    _ = _app
    root.mainloop()


if __name__ == "__main__":
    main()
