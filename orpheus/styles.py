"""Textfarben, die sich nach dem tatsächlichen Hintergrund richten.

Tk folgt dem Windows-Dunkelmodus nicht: die Flächen bleiben hell
(``SystemButtonFace``), auch wenn Windows dunkel eingestellt ist. Bei
aktiviertem **Kontrastdesign** kippt derselbe Systemwert aber ins Dunkle — und
dann wären fest verdrahtete Töne wie ``#555555`` oder ``gray`` unlesbar.

Deshalb wird die Helligkeit zur Laufzeit aus der echten Systemfarbe bestimmt
und der passende Satz gewählt. Zusätzlich ist ``gray`` ersetzt: auf
``#f0f0f0`` kommt es nur auf rund 3:1 und liegt damit unter der
Lesbarkeitsgrenze.
"""

from __future__ import annotations

import tkinter as tk

# Töne für helle Flächen (Normalfall) …
_ON_LIGHT = {
    "hint": "#5a6470",       # Nebentext, ersetzt "gray" (3.0:1 -> 5.5:1)
    "accent": "#1f4c94",     # hervorgehobener Pfad
    "muted": "#4a4a4a",      # zweitrangige Pfadangabe
}
# … und für dunkle, wie sie das Windows-Kontrastdesign liefert.
_ON_DARK = {
    "hint": "#b9c2cc",
    "accent": "#8ab4ff",
    "muted": "#cfcfcf",
}

# Der Vorschautext bringt seinen eigenen dunklen Hintergrund mit und ist
# deshalb von der Umschaltung unabhängig.
PREVIEW_BACKGROUND = "#1e1e1e"
PREVIEW_FOREGROUND = "#d4d4d4"
PREVIEW_CARET = "#ffffff"


def _is_light(widget: tk.Misc) -> bool:
    """Ist der Systemhintergrund hell? Ermittelt aus der echten Farbe."""
    try:
        red, green, blue = widget.winfo_rgb("SystemButtonFace")
    except tk.TclError:
        return True  # Im Zweifel hell - das ist der Normalfall unter Windows.
    # winfo_rgb liefert 16 Bit je Kanal.
    luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 65535
    return luminance >= 0.5


def palette(widget: tk.Misc) -> dict[str, str]:
    """Textfarben passend zum aktuellen Systemhintergrund."""
    return dict(_ON_LIGHT if _is_light(widget) else _ON_DARK)


__all__ = [
    "PREVIEW_BACKGROUND", "PREVIEW_CARET", "PREVIEW_FOREGROUND", "palette",
]
