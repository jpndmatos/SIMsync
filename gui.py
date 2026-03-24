"""
SIMsync GUI — local desktop app to sync event CSVs to Brella.
"""

import threading
import tkinter as tk
from tkinter import filedialog, ttk
from pathlib import Path

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


class SyncTab:
    """A single sync module tab (participants, speakers, etc.)."""

    def __init__(self, parent, name, description, has_prune=False, run_func=None, enabled=True):
        self.name = name
        self.run_func = run_func
        self.enabled = enabled
        self.csv_path = tk.StringVar()
        self.dry_run = tk.BooleanVar(value=False)
        self.prune = tk.BooleanVar(value=True)
        self.has_prune = has_prune
        self.running = False

        self.frame = tk.Frame(parent, bg=BG)

        # Header
        hdr = tk.Frame(self.frame, bg=BG)
        hdr.pack(fill="x", padx=24, pady=(20, 4))
        tk.Label(hdr, text=name, font=FONT_TITLE, fg=TEXT, bg=BG, anchor="w").pack(side="left")
        if not enabled:
            tk.Label(hdr, text="COMING SOON", font=("Segoe UI", 8, "bold"), fg=TEXT_TER,
                     bg=SURFACE_RAISED, padx=8, pady=2).pack(side="right")

        tk.Label(self.frame, text=description, font=FONT_SMALL, fg=TEXT_SEC, bg=BG,
                 anchor="w").pack(fill="x", padx=24, pady=(0, 16))

        # CSV picker
        card = tk.Frame(self.frame, bg=SURFACE, highlightbackground=SURFACE_RAISED,
                        highlightthickness=1)
        card.pack(fill="x", padx=24, pady=(0, 8))

        tk.Label(card, text="CSV FILE", font=("Segoe UI", 8, "bold"), fg=ACCENT,
                 bg=SURFACE, anchor="w").pack(fill="x", padx=12, pady=(10, 4))

        row = tk.Frame(card, bg=SURFACE)
        row.pack(fill="x", padx=12, pady=(0, 10))

        self.path_entry = tk.Entry(row, textvariable=self.csv_path, font=FONT_MONO,
                                   bg=BG, fg=TEXT, insertbackground=TEXT,
                                   relief="flat", highlightthickness=1,
                                   highlightbackground=SURFACE_RAISED,
                                   highlightcolor=ACCENT, state="normal")
        self.path_entry.pack(side="left", fill="x", expand=True, ipady=6)

        self.browse_btn = tk.Button(row, text="Browse", font=FONT_SMALL, bg=SURFACE_RAISED,
                                    fg=TEXT, activebackground=ACCENT, activeforeground="white",
                                    relief="flat", cursor="hand2", padx=12, pady=4,
                                    command=self._browse)
        self.browse_btn.pack(side="right", padx=(8, 0))

        # Options
        opts = tk.Frame(self.frame, bg=SURFACE, highlightbackground=SURFACE_RAISED,
                        highlightthickness=1)
        opts.pack(fill="x", padx=24, pady=(0, 8))

        tk.Label(opts, text="OPTIONS", font=("Segoe UI", 8, "bold"), fg=ACCENT,
                 bg=SURFACE, anchor="w").pack(fill="x", padx=12, pady=(10, 4))

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

        if not enabled:
            self.preview_btn.config(state="disabled")
            self.import_btn.config(state="disabled")
            self.browse_btn.config(state="disabled")
            self.path_entry.config(state="disabled")
            self.dry_cb.config(state="disabled")

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
        self.browse_btn.config(state=state)

    def _set_status(self, text, color=TEXT_SEC):
        def _update():
            self.status_var.set(text)
            self.status_label.config(fg=color)
        self.frame.after(0, _update)

    def _log(self, msg):
        if hasattr(self, '_log_callback') and self._log_callback:
            self.frame.after(0, lambda: self._log_callback(msg))


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("SIMsync")
        self.root.geometry("900x640")
        self.root.configure(bg=BG)
        self.root.minsize(700, 500)

        # Try to set icon
        try:
            icon_path = Path(__file__).parent / "simlogo.png"
            if icon_path.exists():
                img = tk.PhotoImage(file=str(icon_path))
                self.root.iconphoto(True, img)
        except Exception:
            pass

        # Main layout: sidebar + content + log
        main = tk.Frame(self.root, bg=BG)
        main.pack(fill="both", expand=True)

        # Sidebar
        sidebar = tk.Frame(main, bg=SURFACE, width=180)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        # Brand
        brand = tk.Frame(sidebar, bg=SURFACE)
        brand.pack(fill="x", padx=14, pady=(16, 6))
        tk.Label(brand, text="SIMsync", font=("Segoe UI", 14, "bold"), fg=TEXT,
                 bg=SURFACE).pack(anchor="w")
        tk.Label(brand, text="EVENT PLATFORM", font=("Segoe UI", 7, "bold"),
                 fg=TEXT_TER, bg=SURFACE).pack(anchor="w")

        sep = tk.Frame(sidebar, bg=SURFACE_RAISED, height=1)
        sep.pack(fill="x", padx=14, pady=(10, 10))

        # Nav buttons
        self.nav_buttons = []
        self.tabs = {}
        self.active_tab = None

        # Content area (center)
        self.content = tk.Frame(main, bg=BG)
        self.content.pack(side="left", fill="both", expand=True)

        # Log panel (right)
        log_frame = tk.Frame(main, bg=SURFACE, width=280)
        log_frame.pack(side="right", fill="y")
        log_frame.pack_propagate(False)

        log_header = tk.Frame(log_frame, bg=SURFACE)
        log_header.pack(fill="x", padx=10, pady=(10, 4))
        tk.Label(log_header, text="LOG", font=("Segoe UI", 8, "bold"), fg=TEXT_SEC,
                 bg=SURFACE).pack(side="left")
        tk.Button(log_header, text="Clear", font=("Segoe UI", 8), bg=SURFACE,
                  fg=TEXT_TER, activebackground=SURFACE_RAISED, activeforeground=TEXT,
                  relief="flat", cursor="hand2", command=self._clear_log).pack(side="right")

        self.log_text = tk.Text(log_frame, font=FONT_MONO, bg="#0e0e14", fg=ACCENT_LIGHT,
                                relief="flat", wrap="word", insertbackground=ACCENT_LIGHT,
                                state="disabled", padx=10, pady=8)
        self.log_text.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        # Create tabs
        self._add_tab(sidebar, "Participants",
                      "Sync 3cket participants to Brella.",
                      has_prune=True, run_func=self._run_participants, enabled=True)
        self._add_tab(sidebar, "Speakers",
                      "Import speaker profiles to Brella.",
                      run_func=None, enabled=False)
        self._add_tab(sidebar, "Sponsors",
                      "Sync sponsor data to Brella.",
                      run_func=None, enabled=False)
        self._add_tab(sidebar, "Schedule",
                      "Sync event sessions to Brella.",
                      run_func=None, enabled=False)

        # Show first tab
        self._switch_tab("Participants")
        self.log("SIMsync ready.")

    def _add_tab(self, sidebar, name, description, has_prune=False, run_func=None, enabled=True):
        tab = SyncTab(self.content, name, description, has_prune=has_prune,
                      run_func=run_func, enabled=enabled)
        tab._log_callback = self.log
        self.tabs[name] = tab

        btn = tk.Button(sidebar, text=name, font=FONT, fg=TEXT_SEC, bg=SURFACE,
                        activebackground=SURFACE_RAISED, activeforeground=TEXT,
                        relief="flat", anchor="w", padx=14, pady=8, cursor="hand2",
                        command=lambda n=name: self._switch_tab(n))
        btn.pack(fill="x", padx=6, pady=1)
        self.nav_buttons.append((name, btn))

    def _switch_tab(self, name):
        self.active_tab = name
        for tab_name, tab in self.tabs.items():
            if tab_name == name:
                tab.frame.pack(fill="both", expand=True)
            else:
                tab.frame.pack_forget()
        for btn_name, btn in self.nav_buttons:
            if btn_name == name:
                btn.config(bg=SURFACE_RAISED, fg=ACCENT_LIGHT)
            else:
                btn.config(bg=SURFACE, fg=TEXT_SEC)

    def log(self, msg):
        import datetime
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
        from api import prepare_csv, run_sync_v4
        csv_path = Path(tab.csv_path.get())
        prepare_csv(csv_path, download_csv=False, log_callback=self.log)
        run_sync_v4(
            csv_path,
            dry_run=tab.dry_run.get(),
            prune_missing=tab.prune.get(),
            log_callback=self.log,
        )

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
