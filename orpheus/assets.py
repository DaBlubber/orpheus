"""Locating bundled files - both when running from source and from a PyInstaller bundle."""

from __future__ import annotations

import os
import sys


def bundle_dir() -> str:
    """Directory that holds the bundled files.

    In a PyInstaller bundle this is the extracted temporary folder (``sys._MEIPASS``),
    when running from source it is the repository root.
    """
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None)
        if base:
            return str(base)
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def icon_file() -> str | None:
    """Path to orpheus.ico, or None if the file is missing.

    Without it the application simply runs without its own window icon - a
    missing icon is no reason to abort the start.
    """
    candidate = os.path.join(bundle_dir(), "assets", "orpheus.ico")
    return candidate if os.path.isfile(candidate) else None
