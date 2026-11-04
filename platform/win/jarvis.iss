; Jarvis for Windows: Inno Setup script (built by build.ps1, which passes /DVERSION and /DSRC).
; Installs per user into %LOCALAPPDATA%\Jarvis (no admin rights). The bundled Python runs app\launch.py, which sets up
; packages and speech models on first launch (progress opens in the browser), then the window.
#ifndef VERSION
  #define VERSION "2.0.4"
#endif
#ifndef SRC
  #define SRC "..\..\dist\win"
#endif

[Setup]
AppId={{6C0F7E3A-6B1E-4C8E-9C7A-4A1D0B7E2F10}
AppName=Jarvis
AppVersion={#VERSION}
AppPublisher=GDDXX-Jarvis contributors
AppPublisherURL=https://github.com/shitoudaidi/GDDXX-Jarvis
DefaultDirName={localappdata}\Jarvis
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=Jarvis-Setup-{#VERSION}
SetupIconFile=jarvis.ico
UninstallDisplayIcon={app}\jarvis.ico
LicenseFile=..\..\LICENSE
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
; Inno Setup ships no Simplified Chinese text; build.ps1 fetches the community translation when it can
#if FileExists(AddBackslash(SourcePath) + "ChineseSimplified.isl")
Name: "zh"; MessagesFile: "ChineseSimplified.isl"
#endif
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SRC}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "jarvis.ico"; DestDir: "{app}"

[Icons]
Name: "{userprograms}\Jarvis"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\launch.py"""; WorkingDir: "{app}"; IconFilename: "{app}\jarvis.ico"
Name: "{userdesktop}\Jarvis"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\launch.py"""; WorkingDir: "{app}"; IconFilename: "{app}\jarvis.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\launch.py"""; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,Jarvis}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; packages and speech models fetched on first run (your conversations and settings in %USERPROFILE%\.jarvis stay)
Type: filesandordirs; Name: "{app}\venv"
Type: filesandordirs; Name: "{app}\models"
Type: files; Name: "{app}\installed"
Type: files; Name: "{app}\install.log"
