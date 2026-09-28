# Orpheus program icon

| | |
|---|---|
| Motif | an arrow rising out of an opened store |
| Gradient | `#5eead4` → `#0f766e` (turquoise/emerald) |
| Glyph | white |
| Base | rounded square, radius 64 of 256 |
| Files | `orpheus.svg` (source graphic), `orpheus.ico` (shipped) |

## Motif

Orpheus brings the lost back from the underworld. The opened store at the bottom,
the arrow rising out of it: exactly what the tool does.

## Why this shape

The deciding criterion was legibility at **16 × 16 pixels** (taskbar, window title,
Explorer details view):

- **No lyre.** It would fit the myth better, but its strings disappear completely at
  16 px – what remains is an unreadable blob.
- **No arrow above a plain line.** The first draft looked exactly like that and was
  indistinguishable from the common upload symbol – the wrong message for a restore
  tool. The opened container turns the meaning into "getting something out".
- Container wall 22 of 256, arrow shaft 32. Thinner fills in at 16 px.

## Regenerating

```powershell
py -3 -m pip install Pillow
py -3 assets\make_icon.py
```

The script draws the geometry with Pillow – deliberately without an SVG rasteriser,
because setting up cairosvg/GTK on Windows is more work than these few shapes. It
writes `orpheus.ico` with the sizes 16, 32, 48, 64, 128 and 256, each computed
separately from a 4× supersample with LANCZOS.

`orpheus.svg` shows the same geometry and serves as documentation. If the script
changes, update the SVG as well.
