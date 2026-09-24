"""Lesbarkeit der Textfarben.

Tk folgt dem Windows-Dunkelmodus nicht, wohl aber dem Kontrastdesign. Fest
verdrahtete Töne wie ``gray`` oder ``#555555`` sind deshalb doppelt heikel:
auf hellem Grund ist ``gray`` mit rund 3:1 ohnehin zu schwach, auf dunklem
Grund wären beide unlesbar.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from orpheus import styles

MINIMUM = 4.5  # WCAG AA fuer normalen Text
LIGHT_BACKGROUND = "#f0f0f0"  # SystemButtonFace unter Windows
DARK_BACKGROUND = "#1f1f1f"   # so dunkel wird es im Kontrastdesign

PACKAGE = Path(styles.__file__).resolve().parent


def contrast(hex_a: str, hex_b: str) -> float:
    def channel(value: float) -> float:
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    def luminance(color: str) -> float:
        color = color.lstrip("#")
        r, g, b = (int(color[i:i + 2], 16) for i in (0, 2, 4))
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)

    light, dark = sorted((luminance(hex_a), luminance(hex_b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


@pytest.mark.parametrize("role", ["hint", "accent", "muted"])
def test_light_palette_is_readable_on_the_windows_background(role):
    ratio = contrast(LIGHT_BACKGROUND, styles._ON_LIGHT[role])
    assert ratio >= MINIMUM, f"{role}: nur {ratio:.1f}:1 auf hellem Grund"


@pytest.mark.parametrize("role", ["hint", "accent", "muted"])
def test_dark_palette_is_readable_in_high_contrast_mode(role):
    ratio = contrast(DARK_BACKGROUND, styles._ON_DARK[role])
    assert ratio >= MINIMUM, f"{role}: nur {ratio:.1f}:1 auf dunklem Grund"


def test_preview_pane_brings_its_own_matching_pair():
    ratio = contrast(styles.PREVIEW_BACKGROUND, styles.PREVIEW_FOREGROUND)
    assert ratio >= MINIMUM, f"Vorschau: nur {ratio:.1f}:1"


def test_no_module_hardcodes_a_text_colour():
    """Farben gehoeren nach styles.py, damit sie umschaltbar bleiben."""
    offenders = []
    pattern = re.compile(r'(?:foreground|fg|bg|background)\s*=\s*"(#[0-9a-fA-F]{3,6}|gray|grey|black|white)"')
    for path in PACKAGE.glob("*.py"):
        if path.name == "styles.py":
            continue
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.name}: {match.group(0)}")
    assert not offenders, (
        "Feste Farbwerte ausserhalb von styles.py:\n" + "\n".join(offenders)
    )
