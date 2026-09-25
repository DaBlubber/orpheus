"""Pure path helpers for restic paths and local Windows file operations."""

from __future__ import annotations

import ntpath
import os
import re
import ctypes


class PathValidationError(ValueError):
    """A path supplied by the user or by restic cannot be used safely."""


def normalize_snapshot_path(path: str, *, allow_empty: bool = True) -> str:
    """Normalises a snapshot path into restic's forward-slash form.

    Snapshot paths are not local Windows paths. Relative segments are not
    resolved but rejected, so a filter never silently changes its scope.
    """

    if path is None:
        raise PathValidationError("The snapshot path is missing.")
    value = str(path).strip()
    if not value:
        if allow_empty:
            return ""
        raise PathValidationError("The snapshot path is empty.")
    if "\x00" in value or "\r" in value or "\n" in value:
        raise PathValidationError("The snapshot path contains invalid control characters.")
    value = value.replace("\\", "/")
    parts = [part for part in value.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise PathValidationError("The snapshot path must not contain '..'.")
    normalized = "/" + "/".join(parts)
    return normalized if normalized != "" else "/"


def literal_restic_pattern(path: str) -> str:
    """Escapes glob metacharacters so a selection in the browser stays exact."""

    normalized = normalize_snapshot_path(path, allow_empty=False)
    # restic patterns understand the usual glob characters. Character classes
    # form portable literals without needing the Windows backslash as escape.
    return normalized.replace("[", "[[]").replace("*", "[*]").replace("?", "[?]")


def validate_hostname(hostname: str) -> str:
    """Validates the immediate repository subfolder."""

    host = (hostname or "").strip()
    if not host or host in {".", ".."}:
        raise PathValidationError("The host name is empty or invalid.")
    if any(char in host for char in ("/", "\\", "\x00", ":")):
        raise PathValidationError("The host name must not contain path separators.")
    return host


def join_repo_path(backup_base_path: str, hostname: str) -> str:
    base = (backup_base_path or "").strip()
    if not base:
        raise PathValidationError("The backup base path is empty.")
    return os.path.join(base, validate_hostname(hostname))


def windows_extended_path(path: str) -> str:
    """Returns an absolute Windows long path for local file operations."""

    if os.name != "nt" or not path:
        return path
    absolute = ntpath.abspath(path)
    if absolute.startswith("\\\\?\\"):
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def is_remote_windows_path(path: str) -> bool:
    """Detects UNC paths and mapped network drives on Windows."""

    value = (path or "").strip()
    if value.startswith("\\\\"):
        return True
    if os.name != "nt":
        return False
    drive, _tail = ntpath.splitdrive(ntpath.abspath(value))
    if not drive:
        return False
    return ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == 4


def is_within(child: str, parent: str) -> bool:
    """Case-insensitive Windows containment check without requiring existence."""

    try:
        child_abs = ntpath.normcase(ntpath.abspath(child))
        parent_abs = ntpath.normcase(ntpath.abspath(parent))
        return ntpath.commonpath([child_abs, parent_abs]) == parent_abs
    except ValueError:
        return False


def safe_component(value: str, fallback: str = "restore") -> str:
    """Creates a short, Windows-compatible name component."""

    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "").strip(" .-")
    return (cleaned or fallback)[:40]
