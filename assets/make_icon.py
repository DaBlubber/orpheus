"""Generates assets/orpheus.ico from the geometry described in this script.

Deliberately Pillow only, without an SVG rasteriser: setting up cairosvg/GTK on
Windows is more work than drawing these few geometric shapes directly. The
orpheus.svg next to it shows the same shape as a source graphic.

Run without arguments, idempotent:

    py -3 assets\\make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

BASE = 256
# Supersampling: draw large first, then scale down with LANCZOS.
SS = 4

# Turquoise/emerald - clearly distinct from the colours of sibling tools.
GRADIENT_TOP = (94, 234, 212)
GRADIENT_BOTTOM = (15, 118, 110)
GLYPH = (255, 255, 255, 255)

ICO_SIZES = [16, 32, 48, 64, 128, 256]


def _gradient(size: int) -> Image.Image:
    column = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(size - 1, 1)
        column.putpixel(
            (0, y),
            tuple(
                round(GRADIENT_TOP[i] + (GRADIENT_BOTTOM[i] - GRADIENT_TOP[i]) * t)
                for i in range(3)
            ),
        )
    return column.resize((size, size), Image.Resampling.BILINEAR)


def _draw_glyph(draw: ImageDraw.ImageDraw, s: float) -> None:
    """An arrow rising out of an open container - bringing something back.

    Orpheus brings the lost back from the underworld: the opened store at the
    bottom, the arrow rising out of it. An arrow above a plain line would have
    been the common upload symbol - exactly the wrong message for a restore
    tool. A lyre would fit the myth better, but its strings disappear
    completely at 16x16.
    """
    def r(*v: float) -> list[float]:
        return [x * s for x in v]

    clear = (0, 0, 0, 0)

    # Arrow head.
    draw.polygon(
        [(128 * s, 40 * s), (186 * s, 108 * s), (70 * s, 108 * s)],
        fill=GLYPH,
    )
    # Shaft, deliberately wide (32 of 256) so it does not vanish at 16x16.
    draw.rounded_rectangle(r(112, 96, 144, 176), radius=8 * s, fill=GLYPH)
    # Open container: filled outside, punched out inside. Walls 22 of 256,
    # thinner fills in at 16x16.
    draw.rounded_rectangle(r(52, 148, 204, 216), radius=18 * s, fill=GLYPH)
    draw.rounded_rectangle(r(74, 126, 182, 194), radius=8 * s, fill=clear)


def build(size: int = BASE) -> Image.Image:
    s = size * SS
    canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, s - 1, s - 1], radius=int(64 * SS * size / BASE), fill=255
    )
    canvas.paste(_gradient(s), (0, 0), mask)

    overlay = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    _draw_glyph(ImageDraw.Draw(overlay), SS * size / BASE)
    overlay.putalpha(Image.composite(overlay.getchannel("A"), Image.new("L", (s, s), 0), mask))
    canvas = Image.alpha_composite(canvas, overlay)

    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    out = Path(__file__).resolve().parent / "orpheus.ico"
    master = build(BASE)
    # Compute every size separately from the supersample instead of letting
    # Pillow scale - that gives visibly cleaner edges at 16x16.
    frames = [build(n) for n in ICO_SIZES if n != BASE]
    master.save(out, format="ICO", sizes=[(n, n) for n in ICO_SIZES], append_images=frames)
    print(f"geschrieben: {out} ({', '.join(f'{n}x{n}' for n in ICO_SIZES)})")


if __name__ == "__main__":
    main()
