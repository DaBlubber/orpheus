"""Reine Vorschauentscheidungen, unabhängig von Tkinter und Restic."""

from __future__ import annotations

import os


TEXT_EXTENSIONS = {
    ".txt", ".log", ".md", ".yml", ".yaml", ".json", ".toml", ".ini",
    ".conf", ".cfg", ".sh", ".bash", ".zsh", ".py", ".js", ".ts",
    ".html", ".htm", ".xml", ".env", ".properties", ".csv", ".nfo",
    ".gitignore", ".dockerfile", ".tf", ".hcl", ".service", ".timer",
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff"}
NO_PREVIEW_EXTENSIONS = {
    ".db", ".sqlite", ".sqlite3", ".mdb", ".zip", ".tar", ".gz", ".bz2",
    ".xz", ".7z", ".rar", ".mp4", ".mkv", ".avi", ".mov", ".mp3",
    ".flac", ".wav", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt",
    ".pptx", ".exe", ".dll", ".so", ".bin", ".img", ".iso", ".key",
    ".pem", ".crt", ".p12", ".pfx", ".pyc", ".class",
}


def preview_kind(path: str) -> str:
    extension = os.path.splitext(path)[1].lower()
    if extension in IMAGE_EXTENSIONS:
        return "image"
    if extension in TEXT_EXTENSIONS:
        return "text"
    return "metadata"


def decode_text(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")
