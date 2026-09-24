# Orpheus

*[Deutsche Version](README.de.md)*

A Windows GUI for **safe, selective restores from restic backups** stored on a NAS.
Built with Python and Tkinter/ttk. The user interface is in German.

Expected repository layout (one restic repository per host):

```text
<backup base path>\<HOSTNAME>
```

The base path can be a mapped drive (`Z:\Backup\Restic`) or a UNC path
(`\\nas\Backup\Restic`). NAS authentication is left to Windows – Orpheus never
stores NAS credentials.

## Safety principle

Orpheus **never lets restic write directly into the original or target folder**.
Every restore is split into separate, visible steps:

1. Pick host and snapshot, optionally a single file or folder in the lazy-loading browser.
2. **Restore to staging** creates a new, marked subfolder per run. Restoring a whole
   snapshot requires an explicit confirmation.
3. **Open in Explorer** for a visual check. Cancelled or failed runs can be inspected
   or discarded, but never applied.
4. **Apply to target** inventories the staging content, lists every existing file that
   would be replaced and only replaces them atomically after a second confirmation.

Staging is not cleaned up automatically, and database dumps are never imported
automatically.

## Features

- snapshot and file browser with lazy loading and a persistent directory cache
- text, metadata and optional image preview
- visible restic/copy progress, cancel with `Esc`
- clear messages for wrong password, repository lock, disconnected drive,
  permission errors and low disk space
- exact `--include` filters, even for file names containing glob characters
- UNC, drive-letter, Unicode and long Windows paths
- collision overview, free-space check and atomic single-file apply

## Password handling

Repository passwords are stored encrypted with Windows **DPAPI** in
`%APPDATA%\Orpheus\secrets.bin`, bound to the current Windows user. The password
never appears on a command line or in a log; restic receives it only through a
private copy of the child process environment. No plaintext password file is written.

## Development

Requirements: Windows 10/11, Python 3.10+, `restic.exe` in `bin\restic.exe`
([restic releases](https://github.com/restic/restic/releases)), optionally Pillow
for image previews.

```powershell
python main.py
```

Tests never call a real restic binary or NAS:

```powershell
pip install -r requirements-dev.txt
python -m pytest
```

## Build

```powershell
pyinstaller Orpheus.spec
```

The spec bundles `bin\restic.exe` into a single-file executable.
`installer\setup.iss` then builds a per-user installer with Inno Setup.

## License

[MIT](LICENSE). restic itself is licensed under BSD-2-Clause.
