import queue
import re
import threading
import tkinter as tk
from csv import writer
from os import environ
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import api


class BrellaGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("3cket -> Brella Importer")
        self.root.geometry("1100x760")

        self.csv_path_var = tk.StringVar(value=str(api.DEFAULT_CSV_PATH))
        self.download_csv_var = tk.BooleanVar(value=True)
        self.prune_missing_var = tk.BooleanVar(value=True)
        self.brella_api_key_var = tk.StringVar(value=api.API_KEY)
        self.brella_org_id_var = tk.StringVar(value=api.ORG_ID)
        self.brella_event_id_var = tk.StringVar(value=api.EVENT_ID)
        self.threecket_cookie_var = tk.StringVar(value=api.THREECKET_COOKIE)
        self.show_secrets_var = tk.BooleanVar(value=False)
        self._last_report = None

        self._event_queue = queue.Queue()
        self._is_running = False

        self._build_layout()
        self.root.after(100, self._pump_events)

    def _build_layout(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(3, weight=1)
        self.root.rowconfigure(4, weight=2)

        frame_top = ttk.Frame(self.root, padding=12)
        frame_top.grid(row=0, column=0, sticky="ew")
        frame_top.columnconfigure(1, weight=1)

        ttk.Label(frame_top, text="CSV:").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame_top, textvariable=self.csv_path_var).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(8, 8),
        )
        ttk.Button(frame_top, text="Browse", command=self._browse_csv).grid(
            row=0,
            column=2,
            sticky="ew",
        )

        options_frame = ttk.Frame(frame_top)
        options_frame.grid(row=1, column=1, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Checkbutton(
            options_frame,
            text="Download CSV",
            variable=self.download_csv_var,
        ).grid(row=0, column=0, padx=(0, 10))
        ttk.Checkbutton(
            options_frame,
            text="Prune Missing",
            variable=self.prune_missing_var,
        ).grid(row=0, column=1)

        settings_frame = ttk.LabelFrame(self.root, text="Settings", padding=12)
        settings_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        settings_frame.columnconfigure(1, weight=1)
        settings_frame.columnconfigure(3, weight=1)

        ttk.Label(settings_frame, text="Brella API Key").grid(row=0, column=0, sticky="w")
        self.entry_api_key = ttk.Entry(settings_frame, textvariable=self.brella_api_key_var, show="*")
        self.entry_api_key.grid(row=0, column=1, sticky="ew", padx=(8, 10))

        ttk.Label(settings_frame, text="Brella Org ID").grid(row=0, column=2, sticky="w")
        ttk.Entry(settings_frame, textvariable=self.brella_org_id_var).grid(
            row=0,
            column=3,
            sticky="ew",
            padx=(8, 0),
        )

        ttk.Label(settings_frame, text="Brella Event ID").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(settings_frame, textvariable=self.brella_event_id_var).grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(8, 10),
            pady=(8, 0),
        )

        ttk.Label(settings_frame, text="3cket Cookie").grid(row=1, column=2, sticky="w", pady=(8, 0))
        self.entry_cookie = ttk.Entry(settings_frame, textvariable=self.threecket_cookie_var, show="*")
        self.entry_cookie.grid(
            row=1,
            column=3,
            sticky="ew",
            padx=(8, 0),
            pady=(8, 0),
        )

        settings_actions = ttk.Frame(settings_frame)
        settings_actions.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        settings_actions.columnconfigure(0, weight=1)

        self.chk_show_secrets = ttk.Checkbutton(
            settings_actions,
            text="Show secrets",
            variable=self.show_secrets_var,
            command=self._toggle_secret_visibility,
        )
        self.chk_show_secrets.grid(row=0, column=0, sticky="w")

        self.btn_test_connection = ttk.Button(
            settings_actions,
            text="Test Connection",
            command=self._run_test_connection,
        )
        self.btn_test_connection.grid(row=0, column=1, sticky="e", padx=(0, 8))

        self.btn_save_settings = ttk.Button(
            settings_actions,
            text="Save Settings",
            command=self._save_settings,
        )
        self.btn_save_settings.grid(row=0, column=2, sticky="e")

        frame_actions = ttk.Frame(self.root, padding=(12, 0, 12, 10))
        frame_actions.grid(row=2, column=0, sticky="ew")
        frame_actions.columnconfigure(0, weight=1)
        frame_actions.columnconfigure(1, weight=1)

        self.btn_preview = ttk.Button(
            frame_actions,
            text="Preview Changes",
            command=self._run_preview,
        )
        self.btn_preview.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.btn_import = ttk.Button(
            frame_actions,
            text="Run Import",
            command=self._run_import,
        )
        self.btn_import.grid(row=0, column=1, sticky="ew")

        status_frame = ttk.Frame(self.root, padding=(12, 0, 12, 8))
        status_frame.grid(row=3, column=0, sticky="nsew")
        status_frame.columnconfigure(0, weight=1)
        status_frame.rowconfigure(1, weight=1)

        self.status_label = ttk.Label(
            status_frame,
            text="Ready.",
            anchor="w",
        )
        self.status_label.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        self.log_text = tk.Text(status_frame, wrap="word", height=12)
        self.log_text.grid(row=1, column=0, sticky="nsew")

        lists_frame = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        lists_frame.grid(row=4, column=0, sticky="nsew")
        for index in range(4):
            lists_frame.columnconfigure(index, weight=1)
        lists_frame.rowconfigure(1, weight=1)

        missing_header = ttk.Frame(lists_frame)
        missing_header.grid(row=0, column=0, sticky="ew")
        missing_header.columnconfigure(0, weight=1)

        self.missing_title_label = ttk.Label(missing_header, text="Missing Emails (0)")
        self.missing_title_label.grid(row=0, column=0, sticky="w")

        self.btn_export_missing = ttk.Button(
            missing_header,
            text="Export CSV",
            command=self._export_missing_csv,
        )
        self.btn_export_missing.grid(row=0, column=1, sticky="e")

        ttk.Label(lists_frame, text="To Add").grid(row=0, column=1, sticky="w")
        ttk.Label(lists_frame, text="To Update").grid(row=0, column=2, sticky="w")
        ttk.Label(lists_frame, text="To Remove").grid(row=0, column=3, sticky="w")

        self.list_missing = tk.Listbox(lists_frame)
        self.list_missing.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(6, 0))

        self.list_add = tk.Listbox(lists_frame)
        self.list_add.grid(row=1, column=1, sticky="nsew", padx=(0, 8), pady=(6, 0))

        self.list_update = tk.Listbox(lists_frame)
        self.list_update.grid(row=1, column=2, sticky="nsew", padx=(0, 8), pady=(6, 0))

        self.list_remove = tk.Listbox(lists_frame)
        self.list_remove.grid(row=1, column=3, sticky="nsew", pady=(6, 0))

    def _browse_csv(self):
        file_path = filedialog.askopenfilename(
            title="Choose participants CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if file_path:
            self.csv_path_var.set(file_path)

    def _set_running(self, running, status=None):
        self._is_running = running
        state = "disabled" if running else "normal"
        self.btn_preview.config(state=state)
        self.btn_import.config(state=state)
        self.btn_export_missing.config(state=state)
        self.btn_test_connection.config(state=state)
        self.btn_save_settings.config(state=state)
        self.chk_show_secrets.config(state=state)
        self.entry_api_key.config(state=state)
        self.entry_cookie.config(state=state)
        if status:
            self.status_label.config(text=status)

    def _toggle_secret_visibility(self):
        show_char = "" if self.show_secrets_var.get() else "*"
        self.entry_api_key.config(show=show_char)
        self.entry_cookie.config(show=show_char)

    def _normalize_cookie(self, cookie_value):
        cleaned = cookie_value.strip()
        if cleaned.startswith('"') and cleaned.endswith('"') and len(cleaned) >= 2:
            return cleaned[1:-1].strip()
        return cleaned

    def _collect_settings(self):
        return {
            "BRELLA_API_KEY": self.brella_api_key_var.get().strip(),
            "BRELLA_ORG_ID": self.brella_org_id_var.get().strip(),
            "BRELLA_EVENT_ID": self.brella_event_id_var.get().strip(),
            "THREECKET_COOKIE": self.threecket_cookie_var.get().strip(),
        }

    def _validate_settings(self, settings):
        if not settings["BRELLA_API_KEY"]:
            raise ValueError("Brella API Key is required.")
        if not settings["BRELLA_ORG_ID"]:
            raise ValueError("Brella Org ID is required.")
        if not settings["BRELLA_EVENT_ID"]:
            raise ValueError("Brella Event ID is required.")

    def _apply_settings_to_runtime(self, settings):
        environ["BRELLA_API_KEY"] = settings["BRELLA_API_KEY"]
        environ["BRELLA_ORG_ID"] = settings["BRELLA_ORG_ID"]
        environ["BRELLA_EVENT_ID"] = settings["BRELLA_EVENT_ID"]
        environ["THREECKET_COOKIE"] = settings["THREECKET_COOKIE"]

        api.API_KEY = settings["BRELLA_API_KEY"]
        api.ORG_ID = settings["BRELLA_ORG_ID"]
        api.EVENT_ID = settings["BRELLA_EVENT_ID"]
        api.THREECKET_COOKIE = settings["THREECKET_COOKIE"]

    def _write_env_file(self, env_values):
        env_path = api.ENV_FILE
        existing_lines = []
        if env_path.exists():
            existing_lines = env_path.read_text(encoding="utf-8").splitlines()

        keys_to_update = set(env_values.keys())
        found_keys = set()
        updated_lines = []

        for line in existing_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                updated_lines.append(line)
                continue

            key = line.split("=", 1)[0].strip()
            if key in keys_to_update:
                value = env_values[key]
                if key == "THREECKET_COOKIE":
                    value = f'"{value}"'
                updated_lines.append(f"{key}={value}")
                found_keys.add(key)
            else:
                updated_lines.append(line)

        for key in env_values:
            if key in found_keys:
                continue

            value = env_values[key]
            if key == "THREECKET_COOKIE":
                value = f'"{value}"'
            updated_lines.append(f"{key}={value}")

        env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")

    def _save_settings(self):
        try:
            settings = self._collect_settings()
            settings["THREECKET_COOKIE"] = self._normalize_cookie(settings["THREECKET_COOKIE"])
            self._validate_settings(settings)
            self._apply_settings_to_runtime(settings)
            self._write_env_file(settings)
        except Exception as exc:
            messagebox.showerror("Settings", str(exc))
            return

        messagebox.showinfo("Settings", "Settings saved to .env and applied in this session.")

    def _append_log(self, message):
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)

    def _clear_results(self):
        self.list_missing.delete(0, tk.END)
        self.list_add.delete(0, tk.END)
        self.list_update.delete(0, tk.END)
        self.list_remove.delete(0, tk.END)
        self.missing_title_label.config(text="Missing Emails (0)")

    def _fill_listbox(self, listbox, values):
        if not values:
            listbox.insert(tk.END, "(none)")
            return

        for value in values:
            listbox.insert(tk.END, value)

    def _show_report(self, report):
        self._last_report = report
        self._clear_results()

        missing_entries = report.get("missing_email_participants", [])
        self.missing_title_label.config(text=f"Missing Emails ({len(missing_entries)})")

        self._fill_listbox(
            self.list_missing,
            missing_entries,
        )
        self._fill_listbox(self.list_add, report.get("added_participants", []))
        self._fill_listbox(self.list_update, report.get("updated_participants", []))
        self._fill_listbox(self.list_remove, report.get("removed_participants", []))

    def _enqueue_log(self, message):
        self._event_queue.put(("log", message))

    def _enqueue_report(self, report, title):
        self._event_queue.put(("report", report, title))

    def _enqueue_error(self, message):
        self._event_queue.put(("error", message))

    def _enqueue_done(self):
        self._event_queue.put(("done",))

    def _enqueue_info(self, message):
        self._event_queue.put(("info", message))

    def _enqueue_status(self, message):
        self._event_queue.put(("status", message))

    def _pump_events(self):
        while True:
            try:
                event = self._event_queue.get_nowait()
            except queue.Empty:
                break

            if not event:
                continue

            event_type = event[0]

            if event_type == "log":
                self._append_log(event[1])
            elif event_type == "report":
                report, title = event[1], event[2]
                self._show_report(report)
                self.status_label.config(text=title)
            elif event_type == "error":
                self.status_label.config(text="Execution failed.")
                messagebox.showerror("Error", event[1])
            elif event_type == "info":
                messagebox.showinfo("Info", event[1])
            elif event_type == "status":
                self.status_label.config(text=event[1])
            elif event_type == "done":
                if self._is_running:
                    self._set_running(False, status=self.status_label.cget("text"))

        self.root.after(100, self._pump_events)

    def _run_async(self, mode):
        if self._is_running:
            return

        try:
            settings = self._collect_settings()
            settings["THREECKET_COOKIE"] = self._normalize_cookie(settings["THREECKET_COOKIE"])
            self._validate_settings(settings)
            self._apply_settings_to_runtime(settings)
        except Exception as exc:
            messagebox.showwarning("Invalid settings", str(exc))
            return

        csv_raw = self.csv_path_var.get().strip()
        if not csv_raw:
            messagebox.showwarning("Missing CSV", "Choose a CSV path first.")
            return
        csv_path = Path(csv_raw)

        self.log_text.delete("1.0", tk.END)
        self._clear_results()
        self._last_report = None

        mode_label = {
            "preview": "Running preview...",
            "import": "Running import...",
        }[mode]
        self._set_running(True, status=mode_label)

        prune_missing = self.prune_missing_var.get()
        download_csv = self.download_csv_var.get()

        worker = threading.Thread(
            target=self._worker,
            args=(mode, csv_path, prune_missing, download_csv),
            daemon=True,
        )
        worker.start()

    def _worker(self, mode, csv_path, prune_missing, download_csv):
        try:
            api.prepare_csv(csv_path, download_csv=download_csv, log_callback=self._enqueue_log)

            if mode == "preview":
                report = api.preview_sync_v4(
                    csv_path,
                    prune_missing=prune_missing,
                    log_callback=self._enqueue_log,
                    include_final_report=False,
                )
                self._enqueue_report(report, "Preview complete.")
                return

            report = api.run_sync_v4(
                csv_path,
                dry_run=False,
                prune_missing=prune_missing,
                log_callback=self._enqueue_log,
                include_final_report=False,
            )
            self._enqueue_report(report, "Import complete.")
        except Exception as exc:
            self._enqueue_error(str(exc))
        finally:
            self._enqueue_done()

    def _run_preview(self):
        self._run_async("preview")

    def _run_import(self):
        self._run_async("import")

    def _run_test_connection(self):
        if self._is_running:
            return

        try:
            settings = self._collect_settings()
            settings["THREECKET_COOKIE"] = self._normalize_cookie(settings["THREECKET_COOKIE"])
            self._validate_settings(settings)
            self._apply_settings_to_runtime(settings)
        except Exception as exc:
            messagebox.showwarning("Invalid settings", str(exc))
            return

        self._set_running(True, status="Testing Brella connection...")
        worker = threading.Thread(target=self._worker_test_connection, daemon=True)
        worker.start()

    def _worker_test_connection(self):
        try:
            headers = api.build_request_headers()
            preflight_url = api.build_url(api.PREFLIGHT_URL_TEMPLATE)
            status_code, response_text = api.preflight_check(preflight_url, headers)

            if status_code == 200:
                self._enqueue_info("Brella connection successful.")
                self._enqueue_log("[OK] Brella preflight succeeded.")
                self._enqueue_status("Connection test passed.")
                return

            raise RuntimeError(f"Brella preflight failed: {status_code} - {response_text}")
        except Exception as exc:
            self._enqueue_error(str(exc))
        finally:
            self._enqueue_done()

    def _parse_missing_label(self, label):
        pattern = r"^(?P<name>.*)\s+\(ID 3cket:\s*(?P<external_id>[^\)]+)\)$"
        match = re.match(pattern, label.strip())
        if match:
            return match.group("name").strip(), match.group("external_id").strip()

        id_only = re.match(r"^ID 3cket:\s*(?P<external_id>.+)$", label.strip())
        if id_only:
            return "", id_only.group("external_id").strip()

        return label.strip(), ""

    def _export_missing_csv(self):
        if not self._last_report:
            messagebox.showinfo("No data", "Run Preview Changes first.")
            return

        missing_entries = self._last_report.get("missing_email_participants", [])
        if not missing_entries:
            messagebox.showinfo("No missing emails", "There are no missing-email participants to export.")
            return

        save_path = filedialog.asksaveasfilename(
            title="Save Missing Emails CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile="missing_emails.csv",
        )
        if not save_path:
            return

        output_path = Path(save_path)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            csv_writer = writer(handle)
            csv_writer.writerow(["name", "external_id", "label"])
            for label in missing_entries:
                name, external_id = self._parse_missing_label(label)
                csv_writer.writerow([name, external_id, label])

        messagebox.showinfo("Exported", f"Missing-email CSV exported to:\n{output_path}")


def main():
    root = tk.Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")

    app = BrellaGUI(root)
    root.minsize(960, 640)
    root.mainloop()


if __name__ == "__main__":
    main()
