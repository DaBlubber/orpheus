"""Staging and apply logic without GUI or restic dependencies."""

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
        super().__init__(f"{len(collisions)} target conflict(s) found.")
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
    """Creates a guaranteed fresh run folder with an ownership marker."""

    if not (staging_root or "").strip():
        raise StagingError("The staging base path is empty.")
    root = os.path.abspath(os.path.expandvars(staging_root))
    try:
        os.makedirs(windows_extended_path(root), exist_ok=True)
        free = shutil.disk_usage(windows_extended_path(root)).free
        if free < MINIMUM_STAGING_FREE:
            raise StagingError(
                "Less than 64 MB are free in the staging area. Choose a different folder or free up space."
            )
        descriptor, probe = tempfile.mkstemp(prefix=".orpheus-write-test-", dir=windows_extended_path(root))
        os.close(descriptor)
        os.unlink(probe)
    except StagingError:
        raise
    except OSError as exc:
        raise StagingError(
            f"The staging area is not writable: {root}. Check the path, free space and permissions. ({exc})"
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
        raise StagingError(f"The fresh staging folder could not be created: {exc}") from exc
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
        raise StagingError("The folder lies outside the configured staging area.")
    marker = os.path.join(absolute, MARKER_NAME)
    try:
        with open(windows_extended_path(marker), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        session = StagingSession(**{field: data[field] for field in StagingSession.__dataclass_fields__})
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise StagingError(
            "The folder has no valid Orpheus staging marker and is not managed, for safety reasons."
        ) from exc
    if os.path.abspath(session.path) != absolute:
        raise StagingError("The staging marker belongs to a different folder.")
    if not is_within(session.content_path, session.path) or not os.path.isdir(windows_extended_path(session.content_path)):
        raise StagingError("The content folder recorded in the marker is invalid or missing.")
    return session


def discover_staging_sessions(staging_root: str) -> list[StagingSession]:
    """Finds existing marked runs without touching any other folders."""

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
        raise StagingError(f"Existing staging runs could not be read: {exc}") from exc
    return sorted(sessions, key=lambda session: session.created_at, reverse=True)


def discard_staging(session: StagingSession):
    """Deletes only a marked run folder below its recorded root."""

    verified = load_staging_session(session.path, session.root)
    if os.path.abspath(verified.path) == os.path.abspath(verified.root):
        raise StagingError("The staging base folder itself is never deleted.")
    try:
        shutil.rmtree(windows_extended_path(verified.path))
    except OSError as exc:
        raise StagingError(
            f"The staging folder could not be removed completely: {exc}. Close any open files and try again."
        ) from exc


def build_transfer_plan(staged_dir: str, destination_dir: str) -> TransferPlan:
    """Inventories the checked staging content and all target collisions."""

    staged = os.path.abspath(staged_dir)
    destination = os.path.abspath(os.path.expandvars(destination_dir))
    if not os.path.isdir(windows_extended_path(staged)):
        raise StagingError(f"The staging folder was not found: {staged}")
    if not destination_dir.strip():
        raise StagingError("The target folder is empty.")
    if is_within(destination, staged) or is_within(staged, destination):
        raise StagingError("Staging and target folder must not overlap.")
    extended_destination = windows_extended_path(destination)
    if os.path.lexists(extended_destination) and (
        _is_link_or_reparse(extended_destination) or not os.path.isdir(extended_destination)
    ):
        raise StagingError("The target path must be a real folder, not a link.")
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
                    raise StagingError(f"The size of '{relative}' could not be read: {exc}") from exc
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
    """Applies files atomically; existing targets only after explicit approval."""

    if plan.collisions and not overwrite:
        raise CollisionError(plan.collisions)
    if is_within(plan.destination_dir, plan.staged_dir) or is_within(plan.staged_dir, plan.destination_dir):
        raise StagingError("Staging and target folder must not overlap.")
    _ensure_destination_space(plan)
    try:
        os.makedirs(windows_extended_path(plan.destination_dir), exist_ok=True)
    except OSError as exc:
        raise StagingError(f"The target folder cannot be created: {exc}") from exc
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
            progress(fraction, f"Applying {files_copied} of {plan.total_files} files")
    for directory in reversed(directories):
        try:
            shutil.copystat(directory.source_path, windows_extended_path(directory.destination_path), follow_symlinks=False)
        except OSError:
            pass  # Applying the content matters more than non-portable directory metadata.
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
                progress(copied / total if total else None, f"Copying {relative}")
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
        raise StagingError(f"The free space at the target could not be determined: {exc}") from exc
    if free < plan.total_bytes:
        raise StagingError(
            f"The target lacks at least {format_bytes(plan.total_bytes - free)} of free space. Choose a different target or free up space."
        )


def _check_cancel(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise OperationCancelled("Applying was cancelled. Files that were already applied completely are kept.")


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
        raise StagingError(f"The staging marker could not be written: {exc}") from exc


def format_bytes(size: int) -> str:
    value = float(max(size, 0))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.0f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"
