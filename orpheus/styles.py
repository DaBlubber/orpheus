"""Text colours that follow the actual background.

Tk does not follow Windows dark mode: surfaces stay light (``SystemButtonFace``)
even when Windows is set to dark. With a **contrast theme** enabled, however, the
same system colour turns dark - and hard-coded tones such as ``#555555`` or
``gray`` would become unreadable.

The brightness is therefore determined at runtime from the real system colour
and the matching set is chosen. ``gray`` is replaced as well: on ``#f0f0f0`` it
only reaches about 3:1, below the readability threshold.
"""

from __future__ import annotations

import tkinter as tk

# Tones for light surfaces (the normal case) ...
_ON_LIGHT = {
    "hint": "#5a6470",       # secondary text, replaces "gray" (3.0:1 -> 5.5:1)
    "accent": "#1f4c94",     # highlighted path
    "muted": "#4a4a4a",      # secondary path
}
# ... and for dark ones, as produced by Windows contrast themes.
_ON_DARK = {
    "hint": "#b9c2cc",
    "accent": "#8ab4ff",
    "muted": "#cfcfcf",
}

# The preview text brings its own dark background and is therefore
# independent of the switch.
PREVIEW_BACKGROUND = "#1e1e1e"
PREVIEW_FOREGROUND = "#d4d4d4"
PREVIEW_CARET = "#ffffff"


def _is_light(widget: tk.Misc) -> bool:
    """Is the system background light? Determined from the real colour."""
    try:
        red, green, blue = widget.winfo_rgb("SystemButtonFace")
    except tk.TclError:
        return True  # When in doubt: light - the normal case on Windows.
    # winfo_rgb returns 16 bits per channel.
    luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 65535
    return luminance >= 0.5


def palette(widget: tk.Misc) -> dict[str, str]:
    """Text colours matching the current system background."""
    return dict(_ON_LIGHT if _is_light(widget) else _ON_DARK)


__all__ = [
    "PREVIEW_BACKGROUND", "PREVIEW_CARET", "PREVIEW_FOREGROUND", "palette",
]
