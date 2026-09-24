"""Auflösung mitgelieferter Dateien - im Quellbetrieb wie im PyInstaller-Bundle."""

from __future__ import annotations

import os
import sys


def bundle_dir() -> str:
    """Verzeichnis, in dem die mitgelieferten Dateien liegen.

    Im PyInstaller-Bundle ist das der entpackte Temporaerordner (``sys._MEIPASS``),
    im Quellbetrieb die Wurzel des Repos.
    """
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None)
        if base:
            return str(base)
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def icon_file() -> str | None:
    """Pfad zu orpheus.ico, oder None wenn die Datei fehlt.

    Fehlt sie, laeuft die Anwendung ohne eigenes Fenstersymbol weiter - ein
    fehlendes Symbol ist kein Grund, den Start abzubrechen.
    """
    candidate = os.path.join(bundle_dir(), "assets", "orpheus.ico")
    return candidate if os.path.isfile(candidate) else None
