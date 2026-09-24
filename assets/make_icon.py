"""Erzeugt assets/orpheus.ico aus der in diesem Skript beschriebenen Geometrie.

Bewusst nur mit Pillow, ohne SVG-Rasterizer: cairosvg/GTK unter Windows
einzurichten ist aufwaendiger als die paar geometrischen Formen direkt zu
zeichnen. Die Datei orpheus.svg daneben zeigt dieselbe Form als Quellgrafik.

Aufruf ohne Argumente, idempotent:

    py -3 assets\\make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

BASE = 256
# Supersampling: erst gross zeichnen, dann per LANCZOS herunterrechnen.
SS = 4

# Tuerkis/Smaragd - klar getrennt von Tempest (Cyan-Blau), Hestia (Orange),
# Janus (Violett) und Helios (Gold).
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
    """Pfeil, der aus einem offenen Behaelter aufsteigt - das Zurueckholen.

    Orpheus holt Verlorenes aus der Unterwelt zurueck: unten der geoeffnete
    Speicher, daraus der Pfeil nach oben. Ein Pfeil ueber einer blossen Linie
    waere das gaengige Upload-Symbol gewesen - fuer ein Wiederherstellungs-
    werkzeug genau die falsche Aussage. Eine Leier waere motivisch naeher,
    ihre Saiten verschwinden bei 16x16 aber vollstaendig.
    """
    def r(*v: float) -> list[float]:
        return [x * s for x in v]

    clear = (0, 0, 0, 0)

    # Pfeilspitze.
    draw.polygon(
        [(128 * s, 40 * s), (186 * s, 108 * s), (70 * s, 108 * s)],
        fill=GLYPH,
    )
    # Schaft, bewusst breit (32 von 256) damit er bei 16x16 nicht verschwindet.
    draw.rounded_rectangle(r(112, 96, 144, 176), radius=8 * s, fill=GLYPH)
    # Offener Behaelter: aussen voll, innen ausgestanzt. Waende 22 von 256,
    # duenner laeuft bei 16x16 zu.
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
    # Jede Stufe einzeln aus dem Supersample rechnen statt Pillow skalieren zu
    # lassen - das ergibt bei 16x16 sichtbar sauberere Kanten.
    frames = [build(n) for n in ICO_SIZES if n != BASE]
    master.save(out, format="ICO", sizes=[(n, n) for n in ICO_SIZES], append_images=frames)
    print(f"geschrieben: {out} ({', '.join(f'{n}x{n}' for n in ICO_SIZES)})")


if __name__ == "__main__":
    main()
