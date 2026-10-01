; Windows-Installer für Caitation (Inno Setup 6). Gebaut von der CI:
;   iscc /DAppVersion=0.1.1 installer\caitation.iss  ->  dist\Caitation-Setup-0.1.1.exe
; Der Installer kopiert nur die App-Dateien (wenige hundert KB). Python 3.11 und die
; Pakete richtet start.bat beim ersten Start im Installationsordner ein.

#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif

[Setup]
AppId={{6C1E2F0B-6F1D-4E0A-9C53-CA17A7104E01}
AppName=Caitation
AppVersion={#AppVersion}
AppVerName=Caitation {#AppVersion}
AppPublisher=Tobias Schmidt
AppPublisherURL=https://github.com/Piece-Of-Schmidt/caitation
AppSupportURL=https://github.com/Piece-Of-Schmidt/caitation/issues
; Pro Benutzer, ohne Administratorrechte. Der Ordner ist frei wählbar (Index und
; Modelle brauchen mehrere GB, z.B. lieber auf ein Datenlaufwerk).
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\Caitation
DisableDirPage=no
DefaultGroupName=Caitation
DisableProgramGroupPage=yes
; Platz für Python, Pakete, Modelle und einen Index für ~1.000 Paper
ExtraDiskSpaceRequired=6000000000
LicenseFile=..\LICENSE
SetupIconFile=caitation.ico
UninstallDisplayIcon={app}\caitation.ico
UninstallDisplayName=Caitation
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
OutputDir=..\dist
OutputBaseFilename=Caitation-Setup-{#AppVersion}

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
de.StartNow=Caitation jetzt starten (der erste Start richtet Python und die Pakete ein, ca. 2 Minuten)
en.StartNow=Start Caitation now (the first start sets up Python and its packages, about 2 minutes)
de.Settings=Caitation-Einstellungen (API-Key)
en.Settings=Caitation settings (API key)
de.CloseFirst=Caitation läuft noch. Bitte das Caitation-Fenster schließen und dann „Wiederholen“ wählen.
en.CloseFirst=Caitation is still running. Please close the Caitation window, then choose "Retry".

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Updates: Programmdateien der alten Version entfernen (Index, Modelle, .env bleiben)
Type: filesandordirs; Name: "{app}\backend"
Type: filesandordirs; Name: "{app}\frontend"

[Files]
Source: "..\backend\*"; DestDir: "{app}\backend"; Excludes: "__pycache__,*.pyc"; Flags: recursesubdirs ignoreversion
Source: "..\frontend\*"; DestDir: "{app}\frontend"; Flags: recursesubdirs ignoreversion
Source: "..\start.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\.env.example"; DestDir: "{app}"; Flags: ignoreversion
; Einstellungsdatei nur beim ersten Installieren anlegen, nie überschreiben
Source: "..\.env.example"; DestDir: "{app}"; DestName: ".env"; Flags: onlyifdoesntexist
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "caitation.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Caitation"; Filename: "{app}\start.bat"; WorkingDir: "{app}"; IconFilename: "{app}\caitation.ico"
Name: "{group}\{cm:Settings}"; Filename: "{sys}\notepad.exe"; Parameters: """{app}\.env"""; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,Caitation}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Caitation"; Filename: "{app}\start.bat"; WorkingDir: "{app}"; IconFilename: "{app}\caitation.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\start.bat"; WorkingDir: "{app}"; Description: "{cm:StartNow}"; Flags: postinstall nowait shellexec skipifsilent

[UninstallDelete]
; Alles, was beim Betrieb entsteht: Python, Pakete, Modelle, Index, Protokoll, Einstellungen
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\.tools"
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\backend"
Type: files; Name: "{app}\.env"
Type: dirifempty; Name: "{app}"

[Code]
function CaitationRunning(): Boolean;
var
  Http: Variant;
begin
  Result := False;
  try
    Http := CreateOleObject('WinHttp.WinHttpRequest.5.1');
    Http.SetTimeouts(1000, 1000, 1000, 1000);
    Http.Open('GET', 'http://127.0.0.1:8000/api/reindex/status', False);
    Http.Send('');
    Result := Http.Status = 200;
  except
  end;
end;

{ Running server = locked files that the uninstaller could not remove }
function InitializeUninstall(): Boolean;
begin
  Result := True;
  while Result and CaitationRunning() do
    { silent uninstall (/SUPPRESSMSGBOXES): cancel instead of retrying forever }
    Result := SuppressibleMsgBox(ExpandConstant('{cm:CloseFirst}'), mbError, MB_RETRYCANCEL, IDCANCEL) = IDRETRY;
end;
