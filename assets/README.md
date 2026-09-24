# Programmsymbol Orpheus

| | |
|---|---|
| Motiv | Pfeil, der aus einem geöffneten Speicher aufsteigt |
| Farbverlauf | `#5eead4` → `#0f766e` (Türkis/Smaragd) |
| Glyph | Weiß |
| Grundfläche | abgerundetes Quadrat, Radius 64 von 256 |
| Dateien | `orpheus.svg` (Quellgrafik), `orpheus.ico` (ausgeliefert) |

## Motiv

Orpheus holt Verlorenes aus der Unterwelt zurück. Unten der geöffnete Speicher,
daraus der Pfeil nach oben: genau der Vorgang, den das Werkzeug ausführt.

## Warum diese Form

Entscheidendes Kriterium war die Lesbarkeit bei **16 × 16 Pixeln** (Taskleiste,
Fenstertitel, Explorer-Detailansicht). Daraus folgen zwei Entscheidungen:

- **Keine Leier.** Motivisch wäre sie näher an Orpheus, ihre Saiten verschwinden
  bei 16 px aber restlos — übrig bliebe ein unlesbarer Klecks.
- **Kein Pfeil über einer bloßen Linie.** Der erste Entwurf sah genau so aus und
  war damit vom gängigen Upload-Symbol nicht zu unterscheiden — für ein
  Wiederherstellungswerkzeug die falsche Aussage, weil es die Richtung
  umdeutet. Der geöffnete Behälter dreht die Bedeutung auf „herausholen".
- Wandstärke des Behälters 22 von 256, Pfeilschaft 32. Dünner läuft bei 16 px zu.

## Neu erzeugen

```powershell
py -3 -m pip install Pillow
py -3 assets\make_icon.py
```

Das Skript zeichnet die Geometrie mit Pillow — bewusst ohne SVG-Rasterizer,
weil cairosvg/GTK unter Windows aufwendiger einzurichten ist als diese paar
Formen. Es schreibt `orpheus.ico` mit den Stufen 16, 32, 48, 64, 128 und 256,
jede einzeln aus einem vierfachen Supersample per LANCZOS gerechnet.

`orpheus.svg` zeigt dieselbe Geometrie und dient der Dokumentation. Wird das
Skript geändert, ist die SVG mitzuziehen.
