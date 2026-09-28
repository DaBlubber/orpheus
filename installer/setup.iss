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
; Icon of the installer itself. The shortcuts below inherit their icon from
; the EXE, into which PyInstaller embeds the same .ico.
SetupIconFile=..\assets\orpheus.ico
PrivilegesRequired=lowest
; Runs without administrator rights and installs per user.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\Orpheus.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Orpheus"; Filename: "{app}\Orpheus.exe"
Name: "{autodesktop}\Orpheus"; Filename: "{app}\Orpheus.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional options:"

[Run]
Filename: "{app}\Orpheus.exe"; Description: "Start Orpheus"; Flags: nowait postinstall skipifsilent
