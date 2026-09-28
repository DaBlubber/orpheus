"""Orpheus application controller; view and core logic stay separately testable."""

from __future__ import annotations

import os
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from . import APP_NAME
from . import config as cfg
from .assets import icon_file
from . import restic_client as rc
from .cache import ListingCache
from .gui_preview import PreviewControllerMixin
from .gui_workflow import RestoreWorkflowMixin
from .restore_service import (
    CollisionError,
    StagingError,
    StagingSession,
    discover_staging_sessions,
    format_bytes,
)
from .tasks import TaskController
from .ui import OrpheusView

# placeholder child of a directory that has not been loaded yet
LOADING = "Loading ..."


class OrpheusApp(PreviewControllerMixin, RestoreWorkflowMixin, tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} - safe restic restore")
        self._apply_window_icon()
        self.geometry("1260x820")
        self.minsize(980, 650)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.config_data = cfg.load_config()
        staging_root = self.config_data.get("staging_dir") or cfg.default_staging_dir()
        callbacks = {
            "pick_base": self._pick_base_path,
            "pick_staging": self._pick_staging_root,
            "refresh_hosts": self._refresh_hosts,
            "host_selected": self._on_host_selected,
            "save_password": self._save_password,
            "load_snapshots": self._load_snapshots,
            "snapshot_selected": self._on_snapshot_selected,
            "tree_open": self._on_tree_open,
            "file_selected": self._on_file_select,
            "stage_restore": self._stage_restore,
            "open_staging": self._open_staging,
            "discard_staging": self._discard_staging,
            "pick_destination": self._pick_destination,
            "promote": self._promote,
            "cancel": self._cancel_active,
        }
        self.view = OrpheusView(
            self, callbacks, self.config_data.get("backup_base_path", ""), staging_root,
        )
        self.tasks = TaskController(self)
        try:
            cache_directory = os.path.join(cfg.app_dir(), "ls_cache")
        except OSError as exc:
            cache_directory = os.path.join(tempfile.gettempdir(), APP_NAME, "ls_cache")
            self.after(
                100,
                lambda error=exc: messagebox.showwarning(
                    "Cache is temporary only",
                    "The AppData folder is not writable. The directory cache is kept in the temp "
                    f"folder for this session.\n\n{error}",
                    parent=self,
                ),
            )
        self.cache = ListingCache(cache_directory)

        self._current_repo = ""
        self._current_password = ""
        self._current_snapshot_id = ""
        self._selected_include = ""
        self._snapshot_ids: dict[str, str] = {}
        self._iid_to_path: dict[str, str] = {}
        self._iid_to_node: dict[str, dict] = {}
        self._active_staging: StagingSession | None = None
        self._preview_image = None
        self._browser_generation = 0
        self._browser_cancel = threading.Event()
        self._preview_generation = 0
        self._preview_cancel = threading.Event()
        self._closing = False
        self._staging_scan_generation = 0

        self.bind("<F5>", lambda _event: self._refresh_hosts())
        self.bind("<Control-l>", lambda _event: self._load_snapshots())
        self.bind("<Escape>", lambda _event: self._cancel_active())
        self.view.password_entry.bind("<Return>", lambda _event: self._load_snapshots())
        self._show_preview_placeholder("Select a file to preview")
        self._refresh_action_states()
        warning = cfg.config_warning()
        if warning:
            self.after(100, lambda: messagebox.showwarning("Configuration notice", warning, parent=self))
        if self.config_data.get("backup_base_path"):
            self.after(150, self._refresh_hosts)
        else:
            self.after(100, self.view.base_entry.focus_set)
        self.after(250, self._recover_latest_staging)

    # ------------------------------------------------------------ shared UI
    def _start_task(self, name, initial_status, operation, on_success, on_error=None) -> bool:
        self.view.set_busy(True)
        self.view.show_progress(None, initial_status)
        started = self.tasks.start(
            name,
            operation,
            on_success,
            on_error or self._show_error,
            self.view.show_progress,
            self._task_finished,
        )
        if not started:
            self.view.status_var.set("Please wait until the running action has finished.")
            self.view.set_busy(False)
        return started

    def _task_finished(self):
        self.view.reset_progress()
        self.view.set_busy(False)
        self._refresh_action_states()

    def _refresh_action_states(self):
        if self.tasks.busy:
            return
        self.view.stage_button.configure(
            state="normal" if self._current_snapshot_id and self.view.password_var.get() else "disabled"
        )
        has_staging = self._active_staging is not None and os.path.isdir(self._active_staging.path)
        complete = has_staging and self._active_staging.status == "complete"
        self.view.open_staging_button.configure(state="normal" if has_staging else "disabled")
        self.view.discard_staging_button.configure(state="normal" if has_staging else "disabled")
        self.view.promote_button.configure(state="normal" if complete else "disabled")
        self.view.cancel_button.configure(state="disabled")

    def _show_error(self, error: Exception):
        if isinstance(error, rc.OperationCancelled):
            self.view.status_var.set(str(error))
            messagebox.showinfo("Cancelled", str(error), parent=self)
            return
        if isinstance(error, rc.ResticError):
            message = error.user_message()
        elif isinstance(error, (StagingError, cfg.ConfigError, CollisionError)):
            message = str(error)
        elif isinstance(error, OSError):
            message = f"Windows could not perform the action.\n\n{error}\n\nCheck the path, permissions and network connection."
        else:
            message = f"The action could not be completed.\n\n{type(error).__name__}: {error}"
        self.view.status_var.set("Action failed. See the message.")
        messagebox.showerror("Orpheus - action not completed", message, parent=self)

    def _cancel_active(self):
        if self.tasks.busy:
            self.tasks.cancel()
            self.view.status_var.set("Cancellation requested ... restic is being stopped cleanly.")

    # ------------------------------------------------------------ settings
    def _pick_base_path(self):
        path = filedialog.askdirectory(title="Choose the backup base folder", parent=self)
        if path:
            self.view.base_path_var.set(path)

    def _pick_staging_root(self):
        path = filedialog.askdirectory(title="Choose the local staging base folder", parent=self)
        if path:
            self.view.staging_root_var.set(path)
            self.config_data["staging_dir"] = path
            try:
                cfg.save_config(self.config_data)
            except (cfg.ConfigError, OSError) as exc:
                self._show_error(exc)
                return
            self._active_staging = None
            self._recover_latest_staging()

    def _recover_latest_staging(self):
        root = self.view.staging_root_var.get().strip() or cfg.default_staging_dir()
        self._staging_scan_generation += 1
        generation = self._staging_scan_generation

        def worker():
            try:
                sessions = discover_staging_sessions(root)
            except StagingError:
                return
            if not self._closing:
                try:
                    self.after(0, lambda: update(sessions))
                except tk.TclError:
                    return

        def update(sessions):
            if generation != self._staging_scan_generation or self._active_staging is not None:
                return
            if sessions:
                session = sessions[0]
                self._active_staging = session
                suffix = "complete" if session.status == "complete" else f"status: {session.status}"
                self.view.staging_path_var.set(f"{session.content_path} ({suffix}, resumed)")
                self.view.status_var.set("An existing staging run was resumed. Inspect or discard it.")
            else:
                self.view.staging_path_var.set("No checked staging content yet")
            self._refresh_action_states()

        threading.Thread(target=worker, name="Orpheus-staging-scan", daemon=True).start()

    def _refresh_hosts(self):
        if self.tasks.busy:
            return
        base = self.view.base_path_var.get().strip()
        if not base:
            messagebox.showwarning("Base path missing", "Choose the backup base path first.", parent=self)
            self.view.base_entry.focus_set()
            return

        def operation(cancel, progress):
            progress(None, "Checking the backup base path and looking for hosts ...")
            return rc.discover_hosts_cancellable(base, cancel)

        def success(hosts):
            self._reset_repository_view()
            self.view.host_combo["values"] = hosts
            self.config_data["backup_base_path"] = base
            self.config_data["staging_dir"] = self.view.staging_root_var.get().strip()
            try:
                cfg.save_config(self.config_data)
            except (cfg.ConfigError, OSError) as exc:
                self._show_error(exc)
                return
            if hosts:
                self.view.host_combo.current(0)
                self._on_host_selected()
                self.view.status_var.set(f"{len(hosts)} host(s) found. Now load the snapshots.")
                self.view.snapshots_button.focus_set()
            else:
                self.view.status_var.set("No host subfolders found. Check the repository layout <base path>\\<HOSTNAME>.")
                messagebox.showinfo(
                    "No hosts found",
                    "The base path is reachable but contains no host subfolders.\n\n"
                    "Expected: <base path>\\<HOSTNAME>.",
                    parent=self,
                )

        self._start_task("Hosts", "Looking for hosts ...", operation, success)

    def _on_host_selected(self, _event=None):
        self._cancel_browser_workers()
        host = self.view.host_var.get()
        try:
            self._current_repo = rc.repo_path(self.view.base_path_var.get(), host)
            saved = cfg.get_repo_password(host)
        except (rc.ResticError, cfg.ConfigError) as exc:
            self._show_error(exc)
            return
        self.view.password_var.set(saved or "")
        self._current_password = ""
        self._current_snapshot_id = ""
        self._selected_include = ""
        self._snapshot_ids.clear()
        self.view.snapshot_tree.delete(*self.view.snapshot_tree.get_children())
        self._clear_file_tree()
        self.view.selected_path_var.set("(entire snapshot)")
        self.view.file_status_var.set("Load the snapshots")
        self._show_preview_placeholder("Select a snapshot and a file")
        self._refresh_action_states()

    def _save_password(self):
        host = self.view.host_var.get()
        password = self.view.password_var.get()
        if not host or not password:
            messagebox.showwarning("Missing input", "Choose a host and enter a password.", parent=self)
            return
        try:
            cfg.set_repo_password(host, password)
        except cfg.ConfigError as exc:
            self._show_error(exc)
            return
        messagebox.showinfo(
            "Password saved",
            f"The password for '{host}' was stored, protected by Windows DPAPI for your user.",
            parent=self,
        )

    # ------------------------------------------------------------ snapshots/browser
    def _load_snapshots(self):
        if self.tasks.busy:
            return
        host = self.view.host_var.get()
        password = self.view.password_var.get()
        if not host or not password:
            messagebox.showwarning("Missing input", "Choose a host and enter the repository password.", parent=self)
            self.view.password_entry.focus_set()
            return
        try:
            repo = rc.repo_path(self.view.base_path_var.get(), host)
        except rc.ResticError as exc:
            self._show_error(exc)
            return

        def operation(cancel, progress):
            progress(None, "Loading the snapshot list from restic ...")
            return rc.list_snapshots(repo, password, cancel_event=cancel)

        def success(snapshots):
            self._cancel_browser_workers()
            self._current_repo = repo
            self._current_password = password
            self._current_snapshot_id = ""
            self._snapshot_ids.clear()
            self.view.snapshot_tree.delete(*self.view.snapshot_tree.get_children())
            self._clear_file_tree()
            for snapshot in sorted(snapshots, key=lambda item: item.get("time", ""), reverse=True):
                full_id = str(snapshot.get("id") or "")
                if not full_id:
                    continue
                short_id = str(snapshot.get("short_id") or full_id[:8])
                item_id = self.view.snapshot_tree.insert(
                    "", "end", values=(short_id, str(snapshot.get("time") or "")[:19].replace("T", " ")),
                )
                self._snapshot_ids[item_id] = full_id
            count = len(self._snapshot_ids)
            self.view.status_var.set(
                f"{count} snapshot(s) loaded. Select a snapshot."
                if count else "The repository contains no snapshots."
            )
            self.view.file_status_var.set("Select a snapshot" if count else "No snapshots")
            if count:
                first = next(iter(self._snapshot_ids))
                self.view.snapshot_tree.selection_set(first)
                self.view.snapshot_tree.focus(first)

        self._start_task("Snapshots", "Loading snapshots ...", operation, success)

    def _on_snapshot_selected(self, _event=None):
        selected = self.view.snapshot_tree.selection()
        if not selected:
            return
        snapshot_id = self._snapshot_ids.get(selected[0])
        if not snapshot_id:
            return
        self._cancel_browser_workers()
        self._current_snapshot_id = snapshot_id
        self._selected_include = ""
        self._clear_file_tree()
        self.view.selected_path_var.set("(entire snapshot)")
        self.view.file_status_var.set("Loading top level ...")
        self._show_preview_placeholder("Select a file to preview")
        self._load_dir_async("", "/", self._browser_generation)
        self._refresh_action_states()

    def _cancel_browser_workers(self):
        self._browser_cancel.set()
        self._preview_cancel.set()
        self._browser_generation += 1
        self._preview_generation += 1
        self._browser_cancel = threading.Event()
        self._preview_cancel = threading.Event()

    def _clear_file_tree(self):
        self.view.file_tree.delete(*self.view.file_tree.get_children())
        self._iid_to_path.clear()
        self._iid_to_node.clear()

    def _load_dir_async(self, parent_iid: str, path: str, generation: int):
        repo, password, snapshot = self._current_repo, self._current_password, self._current_snapshot_id
        cached = self.cache.get(repo, snapshot, path)
        if cached is not None:
            self._populate_dir(parent_iid, path, cached, generation)
            return
        cancel_event = self._browser_cancel

        def worker():
            try:
                entries = rc.list_snapshot_dir(repo, password, snapshot, path, cancel_event=cancel_event)
            except rc.OperationCancelled:
                return
            except Exception as exc:
                self.after(0, lambda error=exc: self._directory_error(error, generation))
                return
            self.cache.put(repo, snapshot, path, entries)
            self.after(0, lambda: self._populate_dir(parent_iid, path, entries, generation))

        threading.Thread(target=worker, name="Orpheus-directory", daemon=True).start()

    def _directory_error(self, error: Exception, generation: int):
        if generation != self._browser_generation:
            return
        self.view.file_status_var.set("Directory not loaded")
        self._show_error(error)

    def _populate_dir(self, parent_iid: str, path: str, entries: list[dict], generation: int):
        if generation != self._browser_generation:
            return
        if parent_iid and not self.view.file_tree.exists(parent_iid):
            return
        children = self.view.file_tree.get_children(parent_iid)
        if len(children) == 1 and self.view.file_tree.item(children[0], "text") == LOADING:
            self.view.file_tree.delete(children[0])
        for node in sorted(entries, key=lambda item: (item.get("type") != "dir", str(item.get("path", "")).casefold())):
            self._insert_node(parent_iid, node)
        if path == "/":
            self.view.file_status_var.set(f"{len(entries)} entries")

    def _insert_node(self, parent_iid: str, node: dict):
        path = str(node.get("path") or "")
        name = path.rstrip("/").split("/")[-1] or path
        is_directory = node.get("type") == "dir"
        size = "" if is_directory else format_bytes(int(node.get("size") or 0))
        mtime = str(node.get("mtime") or "")[:19].replace("T", " ")
        item_id = self.view.file_tree.insert(
            parent_iid, "end", text=("Folder: " if is_directory else "") + name,
            values=(size, mtime), open=False,
        )
        self._iid_to_path[item_id] = path
        self._iid_to_node[item_id] = node
        if is_directory:
            self.view.file_tree.insert(item_id, "end", text=LOADING)

    def _on_tree_open(self, _event=None):
        item_id = self.view.file_tree.focus()
        children = self.view.file_tree.get_children(item_id)
        if len(children) == 1 and self.view.file_tree.item(children[0], "text") == LOADING:
            path = self._iid_to_path.get(item_id)
            if path:
                self._load_dir_async(item_id, path, self._browser_generation)

    # ------------------------------------------------------------ lifecycle
    def _reset_repository_view(self):
        self._cancel_browser_workers()
        self.view.host_var.set("")
        self.view.password_var.set("")
        self.view.host_combo["values"] = ()
        self.view.snapshot_tree.delete(*self.view.snapshot_tree.get_children())
        self._clear_file_tree()
        self._current_repo = ""
        self._current_password = ""
        self._current_snapshot_id = ""
        self._selected_include = ""

    def _apply_window_icon(self):
        """Sets the window icon if the file is present.

        Tk raises different errors depending on the state of the file; a
        missing or unreadable icon must not prevent the start.
        """
        path = icon_file()
        if not path:
            return
        try:
            self.iconbitmap(default=path)
        except tk.TclError:
            pass

    def _on_close(self):
        if self._closing:
            return
        if self.tasks.busy:
            if not messagebox.askyesno(
                "Cancel the running action?",
                "An action is still running. Orpheus requests a clean cancellation and closes afterwards. Continue?",
                parent=self,
            ):
                return
            self._closing = True
            self.tasks.cancel()
            self._browser_cancel.set()
            self._preview_cancel.set()
            self.view.status_var.set("Stopping the running action before closing ...")
            self._wait_for_close()
            return
        self._browser_cancel.set()
        self._preview_cancel.set()
        self.destroy()

    def _wait_for_close(self):
        if self.tasks.busy:
            self.after(100, self._wait_for_close)
        else:
            self.destroy()


def main():
    app = OrpheusApp()
    app.mainloop()
