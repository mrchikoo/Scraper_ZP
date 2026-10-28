; Inno Setup 6 script for Lead Outreach -> LeadOutreachSetup.exe
;
; Build (from the repository root, after PyInstaller and make_icon.py):
;   iscc /DAppVersion=1.2.3 packaging\installer.iss
; Output: dist\installer\LeadOutreachSetup.exe
;
; Per-user install (no administrator rights needed) into
;   %LOCALAPPDATA%\Programs\Lead Outreach
; User data lives in %APPDATA%\LeadOutreach and is only removed on uninstall
; if the user explicitly says so.

#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif
#define AppName "Lead Outreach"
#define AppExeName "Lead Outreach.exe"
#define DataFolderName "LeadOutreach"

[Setup]
; Never change AppId once released: it is how upgrades find the old install.
AppId={{6F2B7C1E-4A9D-4E38-9B61-2C7D5A0E8F43}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=LeadOutreachSetup
SetupIconFile=build\app.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Close a running copy before upgrading/uninstalling.
CloseApplications=force
RestartApplications=no
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Put a Lead Outreach icon on my Desktop"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Remove the previous program files first so stale DLLs never linger after an update.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Open my Lead Outreach data folder"; Filename: "{userappdata}\{#DataFolderName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Dirs]
Name: "{userappdata}\{#DataFolderName}"; Flags: uninsneveruninstall

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Start Lead Outreach now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /F /IM ""{#AppExeName}"" /T"; Flags: runhidden; RunOnceId: "KillLeadOutreach"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{userappdata}\{#DataFolderName}');
    if DirExists(DataDir) and (not UninstallSilent) then
    begin
      if MsgBox('Do you also want to delete your saved settings, Gmail connection, ' +
                'business list, sent-email history and attached PDFs?' + #13#10#13#10 +
                'Choose "No" to keep them (recommended if you plan to install Lead Outreach again).' + #13#10#13#10 +
                'Folder: ' + DataDir,
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      begin
        DelTree(DataDir, True, True, True);
      end;
    end;
  end;
end;
