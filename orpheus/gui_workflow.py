"""Tk-Controller-Mixin für Staging, Sichtprüfung und explizite Übernahme."""

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
            messagebox.showwarning("Snapshot fehlt", "Wählen Sie zuerst einen Snapshot aus.", parent=self)
            return
        password = self.view.password_var.get()
        if not password:
            messagebox.showwarning("Passwort fehlt", "Geben Sie das Repository-Passwort ein.", parent=self)
            return
        include = self._selected_include
        scope = include or "gesamter Snapshot"
        if not messagebox.askyesno(
            "Staging-Wiederherstellung bestätigen",
            f"Auswahl: {scope}\n\nOrpheus stellt ausschließlich in einen neuen Staging-Unterordner wieder her. "
            "Originaldaten werden nicht verändert.\n\nFortfahren?",
            parent=self,
        ):
            return
        staging_root = self.view.staging_root_var.get().strip() or cfg.default_staging_dir()
        if is_remote_windows_path(staging_root) and not messagebox.askyesno(
            "Staging auf Netzwerkfreigabe?",
            "Der gewählte Staging-Bereich ist ein UNC-Pfad. Seine Zugriffsrechte werden von der Freigabe geerbt und "
            "können breiter sein als bei der empfohlenen lokalen Vorgabe unter LOCALAPPDATA.\n\n"
            "Nur fortfahren, wenn die Freigabe ausschließlich für berechtigte Benutzer zugänglich ist.",
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
            self.view.status_var.set("Staging-Wiederherstellung abgeschlossen. Prüfen Sie jetzt den Inhalt im Explorer.")
            self._refresh_action_states()
            message = (
                f"Die Daten liegen ausschließlich im Staging-Ordner:\n\n{session.content_path}\n\n"
                "Prüfen Sie den Inhalt. Erst der separate Schritt 3 übernimmt Dateien auf ein Ziel."
            )
            if warnings:
                message += "\n\nRestic-Hinweise:\n" + "\n".join(warnings[:8])
                messagebox.showwarning("Staging abgeschlossen – Hinweise beachten", message, parent=self)
            else:
                messagebox.showinfo("Staging abgeschlossen", message, parent=self)

        def error(exc):
            if "session" in holder:
                self._active_staging = holder["session"]
                self.view.staging_path_var.set(
                    holder["session"].content_path + " (unvollständig – nur prüfen oder verwerfen)"
                )
            self._show_error(exc)

        self._start_task("Staging-Restore", "Bereite frischen Staging-Ordner vor …", operation, success, error)

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
            "Staging verwerfen",
            f"Nur dieser markierte Staging-Lauf wird gelöscht:\n\n{session.path}\n\n"
            "Bereits übernommene Zieldateien werden nicht verändert. Fortfahren?",
            parent=self,
        ):
            return

        def operation(_cancel, progress):
            progress(None, "Entferne markierten Staging-Lauf …")
            discard_staging(session)
            return None

        def success(_value):
            self._active_staging = None
            self.view.staging_path_var.set("Noch kein geprüfter Staging-Inhalt")
            self.view.status_var.set("Staging-Lauf wurde verworfen.")
            self.after_idle(self._recover_latest_staging)

        self._start_task("Staging-verwerfen", "Verwerfe Staging …", operation, success)

    def _pick_destination(self):
        path = filedialog.askdirectory(title="Zielordner für die explizite Übernahme wählen", parent=self)
        if path:
            self.view.destination_var.set(path)

    def _promote(self):
        if self.tasks.busy or not self._active_staging or self._active_staging.status != "complete":
            return
        destination = self.view.destination_var.get().strip()
        if not destination:
            messagebox.showwarning("Ziel fehlt", "Wählen Sie den Zielordner für die Übernahme aus.", parent=self)
            self.view.destination_entry.focus_set()
            return
        session = self._active_staging

        def operation(_cancel, progress):
            progress(None, "Inventarisiere Staging-Inhalt und prüfe Zielkollisionen …")
            return build_transfer_plan(session.content_path, destination)

        def success(plan):
            summary = (
                f"Ziel: {plan.destination_dir}\n"
                f"Dateien/Links: {plan.total_files}\n"
                f"Datenmenge: {format_bytes(plan.total_bytes)}\n"
                f"Kollisionen: {len(plan.collisions)}"
            )
            overwrite = False
            if plan.collisions:
                examples = "\n".join(f"• {path}" for path in plan.collisions[:10])
                if len(plan.collisions) > 10:
                    examples += f"\n• … und {len(plan.collisions) - 10} weitere"
                overwrite = messagebox.askyesno(
                    "Bestehende Ziele ausdrücklich überschreiben?",
                    summary + "\n\nDiese vorhandenen Ziele würden ersetzt:\n" + examples +
                    "\n\nNur vollständig kopierte Dateien werden atomar ersetzt. Jetzt ausdrücklich überschreiben?",
                    parent=self,
                )
                if not overwrite:
                    self.view.status_var.set("Übernahme wegen Zielkollisionen nicht gestartet; am Ziel wurde nichts verändert.")
                    return
            elif not messagebox.askyesno(
                "Übernahme endgültig bestätigen",
                summary + "\n\nDie Sichtprüfung ist abgeschlossen. Dateien jetzt auf dieses Ziel übernehmen?",
                parent=self,
            ):
                return
            self.after_idle(lambda: self._apply_plan(plan, overwrite))

        self._start_task("Übernahme-planen", "Prüfe Staging und Ziel …", operation, success)

    def _apply_plan(self, plan, overwrite: bool):
        def operation(cancel, progress):
            return apply_transfer_plan(plan, overwrite=overwrite, cancel_event=cancel, progress=progress)

        def success(result):
            self.view.status_var.set("Übernahme abgeschlossen. Der Staging-Lauf bleibt für Ihre Kontrolle erhalten.")
            messagebox.showinfo(
                "Übernahme abgeschlossen",
                f"{result.files_copied} Datei(en)/Link(s) wurden vollständig übernommen.\n"
                f"{result.overwritten} vorhandene Ziele wurden nach Ihrer Freigabe ersetzt.\n\n"
                "Der Staging-Ordner wurde bewusst nicht automatisch gelöscht. Sie können ihn separat verwerfen.",
                parent=self,
            )

        self._start_task("Übernahme", "Übernehme geprüfte Dateien …", operation, success)
