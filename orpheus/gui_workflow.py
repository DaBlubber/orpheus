"""Tk controller mixin for staging, inspection and the explicit apply step."""

from __future__ import annotations

import os
from tkinter import filedialog, messagebox

from . import config as cfg
from . import restic_client as rc
from .paths import is_remote_windows_path
from .restore_service import (
    StagingError,
    StagingSession,
    apply_transfer_plan,
    build_transfer_plan,
    create_staging_session,
    discard_staging,
    format_bytes,
    update_staging_status,
)


class RestoreWorkflowMixin:
    def _stage_restore(self):
        if self.tasks.busy:
            return
        self._staging_scan_generation += 1
        if not self._current_snapshot_id:
            messagebox.showwarning("Snapshot missing", "Select a snapshot first.", parent=self)
            return
        password = self.view.password_var.get()
        if not password:
            messagebox.showwarning("Password missing", "Enter the repository password.", parent=self)
            return
        include = self._selected_include
        scope = include or "entire snapshot"
        if not messagebox.askyesno(
            "Confirm staging restore",
            f"Selection: {scope}\n\nOrpheus restores only into a new staging subfolder. "
            "The original data is not changed.\n\nContinue?",
            parent=self,
        ):
            return
        staging_root = self.view.staging_root_var.get().strip() or cfg.default_staging_dir()
        if is_remote_windows_path(staging_root) and not messagebox.askyesno(
            "Staging on a network share?",
            "The chosen staging area is a UNC path. Its permissions are inherited from the share and "
            "may be broader than those of the recommended local default under LOCALAPPDATA.\n\n"
            "Only continue if the share is accessible to authorised users only.",
            parent=self,
        ):
            return
        self.view.staging_root_var.set(staging_root)
        self.config_data["staging_dir"] = staging_root
        try:
            cfg.save_config(self.config_data)
        except (cfg.ConfigError, OSError) as exc:
            self._show_error(exc)
            return
        holder: dict[str, StagingSession] = {}
        repo, snapshot = self._current_repo, self._current_snapshot_id

        def operation(cancel, progress):
            session = create_staging_session(staging_root, snapshot, include, repo)
            holder["session"] = session
            session = update_staging_status(session, "restoring")
            holder["session"] = session
            try:
                result = rc.restore_snapshot(
                    repo, password, snapshot, include, session.content_path,
                    cancel_event=cancel, progress=progress,
                )
            except rc.OperationCancelled:
                try:
                    holder["session"] = update_staging_status(session, "cancelled")
                except StagingError:
                    pass
                raise
            except Exception:
                try:
                    holder["session"] = update_staging_status(session, "failed")
                except StagingError:
                    pass
                raise
            completed = update_staging_status(session, "complete")
            holder["session"] = completed
            return completed, result.warnings

        def success(value):
            session, warnings = value
            self._active_staging = session
            self.view.staging_path_var.set(session.content_path)
            self.view.status_var.set("Staging restore finished. Now inspect the content in Explorer.")
            self._refresh_action_states()
            message = (
                f"The data is only in the staging folder:\n\n{session.content_path}\n\n"
                "Inspect the content. Only the separate step 3 applies files to a target."
            )
            if warnings:
                message += "\n\nrestic warnings:\n" + "\n".join(warnings[:8])
                messagebox.showwarning("Staging finished - note the warnings", message, parent=self)
            else:
                messagebox.showinfo("Staging finished", message, parent=self)

        def error(exc):
            if "session" in holder:
                self._active_staging = holder["session"]
                self.view.staging_path_var.set(
                    holder["session"].content_path + " (incomplete - inspect or discard only)"
                )
            self._show_error(exc)

        self._start_task("Staging restore", "Preparing a fresh staging folder ...", operation, success, error)

    def _open_staging(self):
        if not self._active_staging:
            return
        try:
            os.startfile(self._active_staging.content_path)
        except OSError as exc:
            self._show_error(exc)

    def _discard_staging(self):
        if self.tasks.busy or not self._active_staging:
            return
        session = self._active_staging
        if not messagebox.askyesno(
            "Discard staging",
            f"Only this marked staging run is deleted:\n\n{session.path}\n\n"
            "Target files that were already applied are not changed. Continue?",
            parent=self,
        ):
            return

        def operation(_cancel, progress):
            progress(None, "Removing the marked staging run ...")
            discard_staging(session)
            return None

        def success(_value):
            self._active_staging = None
            self.view.staging_path_var.set("No checked staging content yet")
            self.view.status_var.set("The staging run was discarded.")
            self.after_idle(self._recover_latest_staging)

        self._start_task("Discard staging", "Discarding staging ...", operation, success)

    def _pick_destination(self):
        path = filedialog.askdirectory(title="Choose the target folder for the explicit apply step", parent=self)
        if path:
            self.view.destination_var.set(path)

    def _promote(self):
        if self.tasks.busy or not self._active_staging or self._active_staging.status != "complete":
            return
        destination = self.view.destination_var.get().strip()
        if not destination:
            messagebox.showwarning("Target missing", "Choose the target folder to apply to.", parent=self)
            self.view.destination_entry.focus_set()
            return
        session = self._active_staging

        def operation(_cancel, progress):
            progress(None, "Inventorying the staging content and checking for target collisions ...")
            return build_transfer_plan(session.content_path, destination)

        def success(plan):
            summary = (
                f"Target: {plan.destination_dir}\n"
                f"Files/links: {plan.total_files}\n"
                f"Data: {format_bytes(plan.total_bytes)}\n"
                f"Collisions: {len(plan.collisions)}"
            )
            overwrite = False
            if plan.collisions:
                examples = "\n".join(f"• {path}" for path in plan.collisions[:10])
                if len(plan.collisions) > 10:
                    examples += f"\n• ... and {len(plan.collisions) - 10} more"
                overwrite = messagebox.askyesno(
                    "Explicitly overwrite existing targets?",
                    summary + "\n\nThese existing targets would be replaced:\n" + examples +
                    "\n\nOnly completely copied files are replaced atomically. Overwrite now?",
                    parent=self,
                )
                if not overwrite:
                    self.view.status_var.set("Apply not started because of target collisions; nothing was changed at the target.")
                    return
            elif not messagebox.askyesno(
                "Confirm apply",
                summary + "\n\nThe inspection is done. Apply the files to this target now?",
                parent=self,
            ):
                return
            self.after_idle(lambda: self._apply_plan(plan, overwrite))

        self._start_task("Plan apply", "Checking staging and target ...", operation, success)

    def _apply_plan(self, plan, overwrite: bool):
        def operation(cancel, progress):
            return apply_transfer_plan(plan, overwrite=overwrite, cancel_event=cancel, progress=progress)

        def success(result):
            self.view.status_var.set("Apply finished. The staging run is kept for your review.")
            messagebox.showinfo(
                "Apply finished",
                f"{result.files_copied} file(s)/link(s) were applied completely.\n"
                f"{result.overwritten} existing targets were replaced after your approval.\n\n"
                "The staging folder was deliberately not deleted automatically. You can discard it separately.",
                parent=self,
            )

        self._start_task("Apply", "Applying the checked files ...", operation, success)
