"""Reine Pfadhelfer für Restic-Pfade und lokale Windows-Dateioperationen."""

from __future__ import annotations

import ntpath
import os
import re
import ctypes


class PathValidationError(ValueError):
    """Ein vom Benutzer oder von Restic gelieferter Pfad ist nicht sicher nutzbar."""


def normalize_snapshot_path(path: str, *, allow_empty: bool = True) -> str:
    """Normalisiert einen Snapshot-Pfad in Restics vorwärtsgerichtete Pfadform.

    Snapshot-Pfade sind keine lokalen Windows-Pfade. Relative Segmente werden
    nicht aufgelöst, sondern abgelehnt, damit ein Filter nie unbemerkt seinen
    Bedeutungsbereich ändert.
    """

    if path is None:
        raise PathValidationError("Der Snapshot-Pfad fehlt.")
    value = str(path).strip()
    if not value:
        if allow_empty:
            return ""
        raise PathValidationError("Der Snapshot-Pfad ist leer.")
    if "\x00" in value or "\r" in value or "\n" in value:
        raise PathValidationError("Der Snapshot-Pfad enthält unzulässige Steuerzeichen.")
    value = value.replace("\\", "/")
    parts = [part for part in value.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise PathValidationError("Der Snapshot-Pfad darf kein '..' enthalten.")
    normalized = "/" + "/".join(parts)
    return normalized if normalized != "" else "/"


def literal_restic_pattern(path: str) -> str:
    """Escaped Glob-Metazeichen, damit eine Browserauswahl exakt bleibt."""

    normalized = normalize_snapshot_path(path, allow_empty=False)
    # Restic-Patterns verstehen die üblichen Glob-Zeichen. Zeichenklassen
    # bilden portable Literale, ohne Windows-Backslash als Escape zu benötigen.
    return normalized.replace("[", "[[]").replace("*", "[*]").replace("?", "[?]")


def validate_hostname(hostname: str) -> str:
    """Validiert den unmittelbaren Repository-Unterordner."""

    host = (hostname or "").strip()
    if not host or host in {".", ".."}:
        raise PathValidationError("Der Hostname ist leer oder ungültig.")
    if any(char in host for char in ("/", "\\", "\x00", ":")):
        raise PathValidationError("Der Hostname darf keine Pfadtrennzeichen enthalten.")
    return host


def join_repo_path(backup_base_path: str, hostname: str) -> str:
    base = (backup_base_path or "").strip()
    if not base:
        raise PathValidationError("Der Backup-Basispfad ist leer.")
    return os.path.join(base, validate_hostname(hostname))


def windows_extended_path(path: str) -> str:
    """Gibt für lokale Dateioperationen einen absoluten Windows-Langpfad zurück."""

    if os.name != "nt" or not path:
        return path
    absolute = ntpath.abspath(path)
    if absolute.startswith("\\\\?\\"):
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def is_remote_windows_path(path: str) -> bool:
    """Erkennt UNC- und gemappte Netzlaufwerkpfade unter Windows."""

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
    """Erzeugt einen kurzen, Windows-kompatiblen Namensbestandteil."""

    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "").strip(" .-")
    return (cleaned or fallback)[:40]
