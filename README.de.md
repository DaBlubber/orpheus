# Orpheus

*[English version](README.md)*

Orpheus ist ein Windows-GUI-Werkzeug zur selektiven Wiederherstellung von
restic-Backups auf einem NAS. Es bleibt bewusst bei Python und Tkinter/ttk.

Die Repository-Struktur lautet:

```text
<Backup-Basispfad>\<HOSTNAME>
```

Der Basispfad kann ein gemapptes Windows-Netzlaufwerk wie
`Z:\Backup\Restic` oder ein UNC-Pfad wie `\\nas\Backup\Restic` sein. Die
NAS-Anmeldung erfolgt über Windows; Orpheus speichert keine NAS-Zugangsdaten.

## Unantastbares Sicherheitsprinzip

Orpheus schreibt **niemals direkt aus restic in Original- oder Zielordner**.
Jeder Restore besteht aus getrennten, sichtbaren Schritten:

1. Host und Snapshot auswählen; optional im Lazy-Loading-Dateibrowser genau
   eine Datei oder einen Ordner auswählen.
2. **In Staging wiederherstellen** erzeugt pro Lauf einen neuen, markierten
   Unterordner. Ohne Dateiauswahl wird nach ausdrücklicher Bestätigung der
   gesamte Snapshot ins Staging geschrieben.
3. **Im Explorer öffnen** ermöglicht die Sichtprüfung. Ein abgebrochener oder
   fehlgeschlagener Lauf kann geprüft oder sicher verworfen, aber nicht
   übernommen werden.
4. Erst **Auf Zielordner übernehmen** inventarisiert den Staging-Inhalt. Bereits
   vorhandene Ziele werden aufgelistet und nur nach einer weiteren expliziten
   Freigabe atomar ersetzt.

Staging wird nach einer Übernahme nicht automatisch gelöscht. Ebenso führt
Orpheus niemals einen automatischen Datenbankimport aus. Datenbank-Dumps werden
manuell geprüft und anschließend mit dem passenden Datenbankwerkzeug importiert.

## Bestehende und verbesserte Funktionen

- Snapshot-Browser und Datei-Browser mit Lazy Loading
- persistenter, nun Windows-pfadsicher gehashter Verzeichnis-Cache
- Text-, Metadaten- und optionale Bildvorschau
- Worker-Threads für NAS-, Restic-, Staging- und Kopieroperationen
- sichtbarer Restic-/Kopierfortschritt und Abbruch mit `Esc`
- verständliche deutsche Hinweise für falsches Passwort, Repository-Lock,
  getrenntes Netzlaufwerk, Rechtefehler und zu wenig Speicherplatz
- exakte `--include`-Filter auch bei Globzeichen in Dateinamen
- UNC-, Laufwerks-, Leerzeichen-, Unicode- und lokale Windows-Langpfade
- Kollisionsübersicht, Platzprüfung und atomare Einzeldateiübernahme

Tastaturkürzel: `F5` lädt Hosts, `Strg+L` lädt Snapshots, `Enter` im
Passwortfeld lädt Snapshots und `Esc` fordert den Abbruch der laufenden
exklusiven Aktion an.

## Passwortschutz und Migration

Repository-Passwörter liegen DPAPI-verschlüsselt unter:

```text
%APPDATA%\Orpheus\secrets.bin
```

DPAPI bindet sie an den aktuellen Windows-Benutzer. Das Passwort erscheint nie
in der Kommandozeile oder in einem Orpheus-Log. Für Restic wird es ausschließlich
in einer privaten Kopie der Kindprozessumgebung bereitgestellt; es wird keine
temporäre Klartext-Passwortdatei erzeugt.

Beim ersten Zugriff kopiert Orpheus fehlende Inhalte verlustfrei von
`%APPDATA%\ResticRestoreTool` nach `%APPDATA%\Orpheus`. Dazu gehören
`config.json`, der DPAPI-Blob `secrets.bin` und vorhandene Cache-Dateien.
Bestehende neue Dateien werden nicht überschrieben und der alte Ordner wird
niemals gelöscht. Unter demselben Windows-Benutzer bleiben die kopierten
DPAPI-Secrets deshalb entschlüsselbar.

Der empfohlene Staging-Standard liegt unter
`%LOCALAPPDATA%\Orpheus\Staging` und erbt dessen benutzerbezogene Windows-ACLs.
Bei einem benutzerdefinierten UNC-Stagingpfad weist Orpheus darauf hin, dass die
Freigaberechte separat geprüft werden müssen.

## Entwicklung

Voraussetzungen:

- Windows 10/11
- Python 3.10 oder neuer
- `restic.exe` unter `bin\restic.exe`
- optional Pillow für Bildvorschauen: `pip install Pillow`

Start:

```powershell
python main.py
```

Tests (rufen niemals echtes restic oder ein NAS auf):

```powershell
pip install -r requirements-dev.txt
python -m pytest
```

## Build und Installer

```powershell
pyinstaller Orpheus.spec
```

Die Spec bindet `bin\restic.exe` in die Onefile-Anwendung ein. Danach kann
`installer\setup.iss` mit Inno Setup kompiliert werden; Ausgabe ist
`dist\Orpheus_Setup_v2.0.exe`.

## Programmsymbol

Das Symbol (Pfeil, der aus einem geöffneten Speicher aufsteigt, Türkis/Smaragd)
liegt als `assets/orpheus.ico` bei. Es wird in die EXE eingebettet, zur Laufzeit
als Fenstersymbol gesetzt und vom Inno-Setup-Installer verwendet. Neu erzeugen:

```powershell
py -3 -m pip install Pillow
py -3 assets\make_icon.py
```

Motiv, Farbwerte und die Begründung der Proportionen stehen in
[assets/README.md](assets/README.md).
