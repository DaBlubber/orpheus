[Setup]
AppName=Orpheus
AppVersion=2.0
AppPublisher=DaBlubber
AppPublisherURL=https://github.com/DaBlubber/orpheus
DefaultDirName={autopf}\Orpheus
DefaultGroupName=Orpheus
OutputDir=..\dist
OutputBaseFilename=Orpheus_Setup_v2.0
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\Orpheus.exe
; Symbol des Installers selbst. Die Verknuepfungen unten erben ihr Symbol aus
; der EXE, in die PyInstaller dieselbe .ico einbettet.
SetupIconFile=..\assets\orpheus.ico
PrivilegesRequired=lowest
; Läuft ohne Administratorrechte und installiert pro Benutzer.

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\Orpheus.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Orpheus"; Filename: "{app}\Orpheus.exe"
Name: "{autodesktop}\Orpheus"; Filename: "{app}\Orpheus.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; GroupDescription: "Zusätzliche Optionen:"

[Run]
Filename: "{app}\Orpheus.exe"; Description: "Orpheus starten"; Flags: nowait postinstall skipifsilent
