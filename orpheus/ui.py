"""Reiner Tkinter/ttk-View-Aufbau für Orpheus."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .styles import PREVIEW_BACKGROUND, PREVIEW_CARET, PREVIEW_FOREGROUND, palette


class OrpheusView(ttk.Frame):
    def __init__(self, master, callbacks: dict[str, object], backup_base_path: str, staging_dir: str):
        super().__init__(master)
        self.callbacks = callbacks
        self.base_path_var = tk.StringVar(value=backup_base_path)
        self.host_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.staging_root_var = tk.StringVar(value=staging_dir)
        self.file_status_var = tk.StringVar(value="Snapshot auswählen")
        self.selected_path_var = tk.StringVar(value="(gesamter Snapshot)")
        self.staging_path_var = tk.StringVar(value="Noch kein geprüfter Staging-Inhalt")
        self.destination_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Bereit. Beginnen Sie mit dem Backup-Basispfad.")
        self.progress_var = tk.DoubleVar(value=0.0)
        # Einmal ermitteln und weiterreichen, damit alle Beschriftungen
        # denselben, zum Hintergrund passenden Satz benutzen.
        self.colors = palette(self)
        self._build()

    def _callback(self, name: str):
        return self.callbacks[name]

    def _build(self):
        self.pack(fill="both", expand=True)
        settings = ttk.LabelFrame(self, text="Repository")
        settings.pack(fill="x", padx=10, pady=(8, 5))
        settings.columnconfigure(1, weight=1)
        ttk.Label(settings, text="Backup-Basispfad:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.base_entry = ttk.Entry(settings, textvariable=self.base_path_var, width=54)
        self.base_entry.grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        ttk.Button(settings, text="Durchsuchen …", command=self._callback("pick_base")).grid(row=0, column=2, padx=4, pady=4)
        self.hosts_button = ttk.Button(settings, text="Hosts laden  [F5]", command=self._callback("refresh_hosts"))
        self.hosts_button.grid(row=0, column=3, padx=6, pady=4)

        ttk.Label(settings, text="Host:").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        auth = ttk.Frame(settings)
        auth.grid(row=1, column=1, columnspan=3, sticky="ew", padx=4, pady=4)
        auth.columnconfigure(0, weight=1)
        self.host_combo = ttk.Combobox(auth, textvariable=self.host_var, state="readonly", width=24)
        self.host_combo.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.host_combo.bind("<<ComboboxSelected>>", self._callback("host_selected"))
        ttk.Label(auth, text="Repository-Passwort:").grid(row=0, column=1, sticky="e")
        self.password_entry = ttk.Entry(auth, textvariable=self.password_var, show="•", width=24)
        self.password_entry.grid(row=0, column=2, padx=6)
        self.password_button = ttk.Button(auth, text="DPAPI-geschützt speichern", command=self._callback("save_password"))
        self.password_button.grid(row=0, column=3)
        ttk.Label(settings, text="Staging-Basis:").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        staging_setting = ttk.Frame(settings)
        staging_setting.grid(row=2, column=1, columnspan=3, sticky="ew", padx=4, pady=4)
        staging_setting.columnconfigure(0, weight=1)
        self.staging_root_entry = ttk.Entry(staging_setting, textvariable=self.staging_root_var)
        self.staging_root_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(staging_setting, text="Staging wählen …", command=self._callback("pick_staging")).grid(row=0, column=1, padx=(5, 0))
        ttk.Label(staging_setting, text="Pro Lauf wird ein neuer Unterordner angelegt.", foreground=self.colors["hint"]).grid(row=0, column=2, padx=8)

        browser = ttk.PanedWindow(self, orient="horizontal")
        browser.pack(fill="both", expand=True, padx=10, pady=5)
        left = ttk.Frame(browser)
        middle = ttk.Frame(browser)
        right = ttk.Frame(browser)
        browser.add(left, weight=1)
        browser.add(middle, weight=2)
        browser.add(right, weight=2)

        snapshot_header = ttk.Frame(left)
        snapshot_header.pack(fill="x")
        ttk.Label(snapshot_header, text="Snapshots").pack(side="left")
        self.snapshots_button = ttk.Button(snapshot_header, text="Laden  [Strg+L]", command=self._callback("load_snapshots"))
        self.snapshots_button.pack(side="right")
        snapshot_frame = ttk.Frame(left)
        snapshot_frame.pack(fill="both", expand=True, pady=(3, 0))
        self.snapshot_tree = ttk.Treeview(
            snapshot_frame, columns=("id", "time"), show="headings", selectmode="browse",
        )
        self.snapshot_tree.heading("id", text="ID")
        self.snapshot_tree.heading("time", text="Zeitpunkt")
        self.snapshot_tree.column("id", width=82, stretch=False)
        self.snapshot_tree.column("time", width=150)
        snapshot_scroll = ttk.Scrollbar(snapshot_frame, orient="vertical", command=self.snapshot_tree.yview)
        self.snapshot_tree.configure(yscrollcommand=snapshot_scroll.set)
        self.snapshot_tree.pack(side="left", fill="both", expand=True)
        snapshot_scroll.pack(side="right", fill="y")
        self.snapshot_tree.bind("<<TreeviewSelect>>", self._callback("snapshot_selected"))

        file_header = ttk.Frame(middle)
        file_header.pack(fill="x")
        ttk.Label(file_header, text="Dateien (Lazy Loading)").pack(side="left")
        ttk.Label(file_header, textvariable=self.file_status_var, foreground=self.colors["hint"]).pack(side="right")
        file_frame = ttk.Frame(middle)
        file_frame.pack(fill="both", expand=True, pady=(3, 0))
        self.file_tree = ttk.Treeview(
            file_frame, columns=("size", "mtime"), show="tree headings", selectmode="browse",
        )
        self.file_tree.heading("#0", text="Name")
        self.file_tree.heading("size", text="Größe")
        self.file_tree.heading("mtime", text="Geändert")
        self.file_tree.column("#0", width=240, minwidth=130)
        self.file_tree.column("size", width=85, anchor="e", stretch=False)
        self.file_tree.column("mtime", width=140)
        file_scroll = ttk.Scrollbar(file_frame, orient="vertical", command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=file_scroll.set)
        self.file_tree.pack(side="left", fill="both", expand=True)
        file_scroll.pack(side="right", fill="y")
        self.file_tree.bind("<<TreeviewOpen>>", self._callback("tree_open"))
        self.file_tree.bind("<<TreeviewSelect>>", self._callback("file_selected"))

        ttk.Label(right, text="Vorschau").pack(anchor="w")
        self.preview_frame = ttk.Frame(right, relief="sunken", borderwidth=1)
        self.preview_frame.pack(fill="both", expand=True, pady=(3, 0))
        self.preview_frame.rowconfigure(0, weight=1)
        self.preview_frame.columnconfigure(0, weight=1)
        self.preview_text = tk.Text(
            self.preview_frame, wrap="none", state="disabled", font=("Consolas", 9),
            bg=PREVIEW_BACKGROUND, fg=PREVIEW_FOREGROUND, insertbackground=PREVIEW_CARET,
        )
        self.preview_text_vscroll = ttk.Scrollbar(self.preview_frame, orient="vertical", command=self.preview_text.yview)
        self.preview_text_hscroll = ttk.Scrollbar(self.preview_frame, orient="horizontal", command=self.preview_text.xview)
        self.preview_text.configure(
            yscrollcommand=self.preview_text_vscroll.set,
            xscrollcommand=self.preview_text_hscroll.set,
        )
        self.preview_image_label = ttk.Label(self.preview_frame, anchor="center")
        self.preview_info_label = ttk.Label(self.preview_frame, anchor="center", justify="center", wraplength=330)

        workflow = ttk.LabelFrame(self, text="Sicherer Zwei-Stufen-Restore – niemals direkt in Originaldaten")
        workflow.pack(fill="x", padx=10, pady=5)
        workflow.columnconfigure(1, weight=1)
        ttk.Label(workflow, text="1", style="Heading.TLabel").grid(row=0, column=0, rowspan=2, padx=(8, 6), pady=4)
        ttk.Label(workflow, text="In frischen Staging-Ordner wiederherstellen").grid(row=0, column=1, sticky="w", pady=(4, 0))
        ttk.Label(workflow, textvariable=self.selected_path_var, foreground=self.colors["accent"]).grid(row=1, column=1, sticky="w", pady=(0, 4))
        self.stage_button = ttk.Button(workflow, text="In Staging wiederherstellen", command=self._callback("stage_restore"))
        self.stage_button.grid(row=0, column=2, rowspan=2, padx=8, pady=4)

        ttk.Separator(workflow, orient="horizontal").grid(row=2, column=0, columnspan=4, sticky="ew", padx=6)
        ttk.Label(workflow, text="2", style="Heading.TLabel").grid(row=3, column=0, rowspan=2, padx=(8, 6), pady=4)
        ttk.Label(workflow, text="Staging-Inhalt im Explorer sichtprüfen").grid(row=3, column=1, sticky="w", pady=(4, 0))
        ttk.Label(workflow, textvariable=self.staging_path_var, foreground=self.colors["muted"]).grid(row=4, column=1, sticky="w", pady=(0, 4))
        staging_actions = ttk.Frame(workflow)
        staging_actions.grid(row=3, column=2, rowspan=2, padx=8, pady=4)
        self.open_staging_button = ttk.Button(staging_actions, text="Im Explorer öffnen", command=self._callback("open_staging"))
        self.open_staging_button.pack(side="left", padx=(0, 4))
        self.discard_staging_button = ttk.Button(staging_actions, text="Staging verwerfen", command=self._callback("discard_staging"))
        self.discard_staging_button.pack(side="left")

        ttk.Separator(workflow, orient="horizontal").grid(row=5, column=0, columnspan=4, sticky="ew", padx=6)
        ttk.Label(workflow, text="3", style="Heading.TLabel").grid(row=6, column=0, rowspan=2, padx=(8, 6), pady=4)
        ttk.Label(workflow, text="Nach Sichtprüfung explizit auf Zielordner übernehmen").grid(row=6, column=1, sticky="w", pady=(4, 0))
        target_row = ttk.Frame(workflow)
        target_row.grid(row=7, column=1, sticky="ew", pady=(0, 4))
        target_row.columnconfigure(0, weight=1)
        self.destination_entry = ttk.Entry(target_row, textvariable=self.destination_var)
        self.destination_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(target_row, text="Ziel wählen …", command=self._callback("pick_destination")).grid(row=0, column=1, padx=(5, 0))
        self.promote_button = ttk.Button(workflow, text="Auf Zielordner übernehmen", command=self._callback("promote"))
        self.promote_button.grid(row=6, column=2, rowspan=2, padx=8, pady=4)

        status = ttk.Frame(self)
        status.pack(fill="x", side="bottom", padx=10, pady=(2, 8))
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self.status_var, anchor="w").grid(row=0, column=0, sticky="ew")
        self.progress = ttk.Progressbar(status, variable=self.progress_var, maximum=100, length=220)
        self.progress.grid(row=0, column=1, padx=8)
        self.cancel_button = ttk.Button(status, text="Abbrechen  [Esc]", command=self._callback("cancel"))
        self.cancel_button.grid(row=0, column=2)

    def show_progress(self, fraction: float | None, message: str):
        self.status_var.set(message)
        if fraction is None:
            if str(self.progress["mode"]) != "indeterminate":
                self.progress.configure(mode="indeterminate")
                self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress_var.set(max(0.0, min(100.0, fraction * 100)))

    def reset_progress(self):
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress_var.set(0.0)

    def set_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        for widget in (self.hosts_button, self.snapshots_button, self.password_button, self.stage_button, self.promote_button):
            widget.configure(state=state)
        self.base_entry.configure(state=state)
        self.staging_root_entry.configure(state=state)
        self.password_entry.configure(state=state)
        self.host_combo.configure(state="disabled" if busy else "readonly")
        self.cancel_button.configure(state="normal" if busy else "disabled")
