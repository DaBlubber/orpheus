"""Staging- und Übernahmelogik ohne GUI- oder Restic-Abhängigkeit."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import stat
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .paths import is_within, safe_component, windows_extended_path
from .restic_client import OperationCancelled


MARKER_NAME = ".orpheus-staging.json"
MINIMUM_STAGING_FREE = 64 * 1024 * 1024
CopyProgress = Callable[[float | None, str], None]


class StagingError(RuntimeError):
    pass


class CollisionError(StagingError):
    def __init__(self, collisions: tuple[str, ...]):
        super().__init__(f"{len(collisions)} Zielkonflikt(e) wurden gefunden.")
        self.collisions = collisions


@dataclass(frozen=True)
class StagingSession:
    path: str
    root: str
    content_path: str
    snapshot_id: str
    include_path: str
    repository: str
    created_at: str
    status: str = "created"


@dataclass(frozen=True)
class TransferItem:
    relative_path: str
    source_path: str
    destination_path: str
    kind: str
    size: int = 0


@dataclass(frozen=True)
class TransferPlan:
    staged_dir: str
    destination_dir: str
    items: tuple[TransferItem, ...]
    collisions: tuple[str, ...]
    total_files: int
    total_bytes: int


@dataclass(frozen=True)
class TransferResult:
    files_copied: int
    bytes_copied: int
    overwritten: int


def create_staging_session(
    staging_root: str,
    snapshot_id: str,
    include_path: str,
    repository: str,
) -> StagingSession:
    """Erstellt einen garantiert frischen Laufordner mit Besitzmarker."""

    if not (staging_root or "").strip():
        raise StagingError("Der Staging-Basispfad ist leer.")
    root = os.path.abspath(os.path.expandvars(staging_root))
    try:
        os.makedirs(windows_extended_path(root), exist_ok=True)
        free = shutil.disk_usage(windows_extended_path(root)).free
        if free < MINIMUM_STAGING_FREE:
            raise StagingError(
                "Im Staging-Bereich sind weniger als 64 MB frei. Wählen Sie einen anderen Ordner oder schaffen Sie Platz."
            )
        descriptor, probe = tempfile.mkstemp(prefix=".orpheus-write-test-", dir=windows_extended_path(root))
        os.close(descriptor)
        os.unlink(probe)
    except StagingError:
        raise
    except OSError as exc:
        raise StagingError(
            f"Der Staging-Bereich ist nicht beschreibbar: {root}. Prüfen Sie Pfad, freien Speicher und Berechtigungen. ({exc})"
        ) from exc
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dirname = f"{timestamp}_{safe_component(snapshot_id[:12], 'snapshot')}_{secrets.token_hex(4)}"
    target = os.path.join(root, dirname)
    target_created = False
    try:
        os.mkdir(windows_extended_path(target))
        target_created = True
        content = os.path.join(target, "content")
        os.mkdir(windows_extended_path(content))
    except OSError as exc:
        if target_created:
            shutil.rmtree(windows_extended_path(target), ignore_errors=True)
        raise StagingError(f"Der frische Staging-Ordner konnte nicht angelegt werden: {exc}") from exc
    session = StagingSession(
        path=target,
        root=root,
        content_path=content,
        snapshot_id=snapshot_id,
        include_path=include_path,
        repository=repository,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    try:
        _write_marker(session)
    except StagingError:
        shutil.rmtree(windows_extended_path(target), ignore_errors=True)
        raise
    return session


def update_staging_status(session: StagingSession, status: str) -> StagingSession:
    updated = replace(session, status=status)
    _write_marker(updated)
    return updated


def load_staging_session(path: str, expected_root: str | None = None) -> StagingSession:
    absolute = os.path.abspath(path)
    if expected_root and (absolute == os.path.abspath(expected_root) or not is_within(absolute, expected_root)):
        raise StagingError("Der Ordner liegt außerhalb des konfigurierten Staging-Bereichs.")
    marker = os.path.join(absolute, MARKER_NAME)
    try:
        with open(windows_extended_path(marker), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        session = StagingSession(**{field: data[field] for field in StagingSession.__dataclass_fields__})
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise StagingError(
            "Der Ordner besitzt keinen gültigen Orpheus-Staging-Marker und wird aus Sicherheitsgründen nicht verwaltet."
        ) from exc
    if os.path.abspath(session.path) != absolute:
        raise StagingError("Der Staging-Marker gehört zu einem anderen Ordner.")
    if not is_within(session.content_path, session.path) or not os.path.isdir(windows_extended_path(session.content_path)):
        raise StagingError("Der im Marker festgehaltene Inhaltsordner ist ungültig oder fehlt.")
    return session


def discover_staging_sessions(staging_root: str) -> list[StagingSession]:
    """Findet bestehende markierte Läufe, ohne fremde Ordner anzutasten."""

    root = os.path.abspath(os.path.expandvars(staging_root))
    if not os.path.isdir(windows_extended_path(root)):
        return []
    sessions: list[StagingSession] = []
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                try:
                    sessions.append(load_staging_session(entry.path, root))
                except StagingError:
                    continue
    except OSError as exc:
        raise StagingError(f"Vorhandene Staging-Läufe konnten nicht gelesen werden: {exc}") from exc
    return sorted(sessions, key=lambda session: session.created_at, reverse=True)


def discard_staging(session: StagingSession):
    """Löscht nur einen markierten Laufordner unterhalb seines festgehaltenen Roots."""

    verified = load_staging_session(session.path, session.root)
    if os.path.abspath(verified.path) == os.path.abspath(verified.root):
        raise StagingError("Der Staging-Basisordner selbst wird niemals gelöscht.")
    try:
        shutil.rmtree(windows_extended_path(verified.path))
    except OSError as exc:
        raise StagingError(
            f"Der Staging-Ordner konnte nicht vollständig entfernt werden: {exc}. Schließen Sie geöffnete Dateien und versuchen Sie es erneut."
        ) from exc


def build_transfer_plan(staged_dir: str, destination_dir: str) -> TransferPlan:
    """Inventarisiert den geprüften Staging-Inhalt und alle Zielkollisionen."""

    staged = os.path.abspath(staged_dir)
    destination = os.path.abspath(os.path.expandvars(destination_dir))
    if not os.path.isdir(windows_extended_path(staged)):
        raise StagingError(f"Der Staging-Ordner wurde nicht gefunden: {staged}")
    if not destination_dir.strip():
        raise StagingError("Der Zielordner ist leer.")
    if is_within(destination, staged) or is_within(staged, destination):
        raise StagingError("Staging- und Zielordner dürfen sich nicht überlappen.")
    extended_destination = windows_extended_path(destination)
    if os.path.lexists(extended_destination) and (
        _is_link_or_reparse(extended_destination) or not os.path.isdir(extended_destination)
    ):
        raise StagingError("Der Zielpfad muss ein echter Ordner sein und darf kein Link sein.")
    items: list[TransferItem] = []
    collisions: list[str] = []
    total_files = 0
    total_bytes = 0
    extended_staged = windows_extended_path(staged)
    for current, dirnames, filenames in os.walk(extended_staged, topdown=True, followlinks=False):
        relative_current = os.path.relpath(current, extended_staged)
        if relative_current == ".":
            relative_current = ""
        for dirname in list(dirnames):
            source = os.path.join(current, dirname)
            relative = os.path.join(relative_current, dirname)
            target = os.path.join(destination, relative)
            if _is_link_or_reparse(source):
                dirnames.remove(dirname)
                item = TransferItem(relative, source, target, "symlink")
                items.append(item)
                total_files += 1
                if os.path.lexists(windows_extended_path(target)):
                    collisions.append(relative)
            else:
                items.append(TransferItem(relative, source, target, "directory"))
                extended_target = windows_extended_path(target)
                if os.path.lexists(extended_target) and (
                    _is_link_or_reparse(extended_target) or not os.path.isdir(extended_target)
                ):
                    collisions.append(relative)
        for filename in filenames:
            if not relative_current and filename == MARKER_NAME:
                continue
            source = os.path.join(current, filename)
            relative = os.path.join(relative_current, filename)
            target = os.path.join(destination, relative)
            if _is_link_or_reparse(source):
                kind, size = "symlink", 0
            else:
                kind = "file"
                try:
                    size = os.path.getsize(source)
                except OSError as exc:
                    raise StagingError(f"Die Größe von '{relative}' konnte nicht gelesen werden: {exc}") from exc
            items.append(TransferItem(relative, source, target, kind, size))
            total_files += 1
            total_bytes += size
            if os.path.lexists(windows_extended_path(target)):
                collisions.append(relative)
    return TransferPlan(
        staged, destination, tuple(items), tuple(sorted(set(collisions), key=str.casefold)),
        total_files, total_bytes,
    )


def apply_transfer_plan(
    plan: TransferPlan,
    *,
    overwrite: bool = False,
    cancel_event=None,
    progress: CopyProgress | None = None,
) -> TransferResult:
    """Übernimmt Dateien atomar; vorhandene Ziele nur nach expliziter Freigabe."""

    if plan.collisions and not overwrite:
        raise CollisionError(plan.collisions)
    if is_within(plan.destination_dir, plan.staged_dir) or is_within(plan.staged_dir, plan.destination_dir):
        raise StagingError("Staging- und Zielordner dürfen sich nicht überlappen.")
    _ensure_destination_space(plan)
    try:
        os.makedirs(windows_extended_path(plan.destination_dir), exist_ok=True)
    except OSError as exc:
        raise StagingError(f"Der Zielordner kann nicht angelegt werden: {exc}") from exc
    bytes_copied = 0
    files_copied = 0
    overwritten = 0
    directories: list[TransferItem] = []
    for item in plan.items:
        _check_cancel(cancel_event)
        if item.kind == "directory":
            directories.append(item)
            target = windows_extended_path(item.destination_path)
            if os.path.lexists(target) and (_is_link_or_reparse(target) or not os.path.isdir(target)):
                if not overwrite:
                    raise CollisionError((item.relative_path,))
                if os.path.isdir(target) and not _is_link_or_reparse(target):
                    raise CollisionError((item.relative_path,))
                os.unlink(target)
            os.makedirs(target, exist_ok=True)
            continue
        target = windows_extended_path(item.destination_path)
        existed = os.path.lexists(target)
        if existed and not overwrite:
            raise CollisionError((item.relative_path,))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        temporary = f"{target}.orpheus-{secrets.token_hex(6)}.tmp"
        try:
            if item.kind == "symlink":
                link_target = os.readlink(item.source_path)
                os.symlink(link_target, temporary, target_is_directory=os.path.isdir(item.source_path))
            else:
                bytes_copied = _copy_file(
                    item.source_path, temporary, bytes_copied, plan.total_bytes,
                    item.relative_path, cancel_event, progress,
                )
                shutil.copystat(item.source_path, temporary, follow_symlinks=False)
            if os.path.lexists(target) and os.path.isdir(target) and not _is_link_or_reparse(target):
                raise CollisionError((item.relative_path,))
            os.replace(temporary, target)
        except Exception:
            try:
                if os.path.lexists(temporary):
                    os.unlink(temporary)
            except OSError:
                pass
            raise
        files_copied += 1
        overwritten += int(existed)
        if progress:
            fraction = (bytes_copied / plan.total_bytes) if plan.total_bytes else (files_copied / max(plan.total_files, 1))
            progress(fraction, f"Übernehme {files_copied} von {plan.total_files} Dateien")
    for directory in reversed(directories):
        try:
            shutil.copystat(directory.source_path, windows_extended_path(directory.destination_path), follow_symlinks=False)
        except OSError:
            pass  # Inhaltsübernahme ist wichtiger als nicht portable Verzeichnismetadaten.
    return TransferResult(files_copied, bytes_copied, overwritten)


def _copy_file(
    source: str,
    target: str,
    completed: int,
    total: int,
    relative: str,
    cancel_event,
    progress: CopyProgress | None,
) -> int:
    copied = completed
    with open(source, "rb") as source_handle, open(target, "xb") as target_handle:
        while True:
            _check_cancel(cancel_event)
            chunk = source_handle.read(1024 * 1024)
            if not chunk:
                break
            target_handle.write(chunk)
            copied += len(chunk)
            if progress:
                progress(copied / total if total else None, f"Kopiere {relative}")
        target_handle.flush()
        os.fsync(target_handle.fileno())
    return copied


def _ensure_destination_space(plan: TransferPlan):
    probe = plan.destination_dir
    while not os.path.exists(windows_extended_path(probe)):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    try:
        free = shutil.disk_usage(windows_extended_path(probe)).free
    except OSError as exc:
        raise StagingError(f"Der freie Speicher am Ziel konnte nicht ermittelt werden: {exc}") from exc
    if free < plan.total_bytes:
        raise StagingError(
            f"Am Ziel fehlen mindestens {format_bytes(plan.total_bytes - free)} freier Speicher. Wählen Sie ein anderes Ziel oder schaffen Sie Platz."
        )


def _check_cancel(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise OperationCancelled("Die Übernahme wurde abgebrochen. Bereits vollständig übernommene Dateien bleiben erhalten.")


def _is_link_or_reparse(path: str) -> bool:
    if os.path.islink(path):
        return True
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _write_marker(session: StagingSession):
    marker = os.path.join(session.path, MARKER_NAME)
    temporary = marker + ".tmp"
    payload = {field: getattr(session, field) for field in StagingSession.__dataclass_fields__}
    try:
        with open(windows_extended_path(temporary), "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(windows_extended_path(temporary), windows_extended_path(marker))
    except OSError as exc:
        raise StagingError(f"Der Staging-Marker konnte nicht geschrieben werden: {exc}") from exc


def format_bytes(size: int) -> str:
    value = float(max(size, 0))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.0f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"
