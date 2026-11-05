; QuantiSheet Server Setup (Inno Setup 6) - for IT departments.
; The machine data folder is C:\ProgramData\QuantiSheet. Installs go to
; C:\Program Files\QuantiSheet; an upgrade stays in the folder the
; previous install is in (DefaultAppDir below).
; Windows Server 2019 / 2022 / 2025 and Remote Desktop servers, or any PC
; deployed by Intune / SCCM / PDQ. Installs for ALL users (needs admin).
;
; Silent install (deployment tools):
;   "QuantiSheet-Beta-Server-Setup-<ver>.exe" /VERYSILENT /SUPPRESSMSGBOXES
;       /NORESTART /LOG="C:\Windows\Temp\quantisheet-setup.log"
;       [/TASKS="openwith,gpo,printer,relay"] [/LICENSEKEY=...] [/PRICEDB=\\server\share\prices.db]
;       [/RELAYURL=ws://host:8765] [/AIHOST=http://ai:11434] [/LOGDIR=...]
;       [/ACCEPTAGREEMENT=1] [/SKIPSIGNIN=1] [/OFFLINE=1] [/NOAI=1]
; /ACCEPTAGREEMENT is still accepted but does nothing (1.0.0 has no
; agreement). Values given here are written to
; HKLM\Software\Policies\QuantiSheet - the same place Group Policy
; writes (Group Policy wins if both).
; Uninstall: "{app}\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES
; Detection rule: HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\
;   {6A0E2C4B-9F31-4D2B-8C55-3B1D2E7F9A40}_is1, DisplayVersion = <ver>
; Built by tools/build_installer.py (same program files as the standalone
; setup), which passes /DAppVersion /DSourceDir /DOutputDir /DOutputBase.
#ifndef AppVersion
  #define AppVersion "0.12.17"
#endif
#ifndef AppPublisher
  #define AppPublisher "QuantiSheet"
#endif
#ifndef OutputBase
  #define OutputBase "QuantiSheet-Beta-Server-Setup-" + AppVersion
#endif

[Setup]
AppId={{6A0E2C4B-9F31-4D2B-8C55-3B1D2E7F9A40}
AppName=QuantiSheet (all users)
AppVersion={#AppVersion}
AppVerName=QuantiSheet {#AppVersion} (all users)
AppPublisher={#AppPublisher}
AppCopyright=Copyright (C) 2026 {#AppPublisher}.
VersionInfoVersion={#AppVersion}
VersionInfoDescription=QuantiSheet Server Setup
; {commonpf64}\QuantiSheet, or the folder an upgrade stays in (DefaultAppDir)
DefaultDirName={code:DefaultAppDir}
UsePreviousAppDir=no
DefaultGroupName=QuantiSheet
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Windows 10 / Server 2016 (build 14393) and later
MinVersion=10.0.14393
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\QuantiSheet.exe
UninstallDisplayName=QuantiSheet (all users)
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBase}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
WizardImageFile=wizard-side.bmp
WizardSmallImageFile=wizard-small.bmp
; Remote Desktop: other users may have it open - setup asks them to close
; it (Restart Manager) rather than failing; schedule updates out of hours
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
ChangesEnvironment=no

[Tasks]
Name: "desktopicon"; Description: "Desktop shortcut for every user"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "openwith"; Description: "Add QuantiSheet to ""Open with"" for PDF files"; GroupDescription: "Shortcuts:"
Name: "gpo"; Description: "Copy the Group Policy template (ADMX) to this computer's PolicyDefinitions"; GroupDescription: "IT:"
Name: "printer"; Description: "Add the ""QuantiSheet"" printer (print from any program to a new PDF)"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "relay"; Description: "Run the collaboration relay on this server (starts with Windows, TCP 8765/8766, firewall rule added)"; GroupDescription: "IT:"; Flags: unchecked

[Dirs]
; ProgramData\QuantiSheet: IT's policy.json, the relay's projects and the
; printer's spool folder
Name: "{commonappdata}\QuantiSheet"
Name: "{code:RelayDir}"; Tasks: relay

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*DEEP_DIVE*,*DEEP-DIVE*,FOR_CLAUDE_*,*XACTIMATE*,*SAGESURE*,*EAGLEVIEW*,*.esx,*_BRIEF.md,*_BRIEF.pdf"
Source: "policy\QuantiSheet.admx"; DestDir: "{app}\policy"; Flags: ignoreversion
Source: "policy\en-US\QuantiSheet.adml"; DestDir: "{app}\policy\en-US"; Flags: ignoreversion
Source: "policy\QuantiSheet.admx"; DestDir: "{win}\PolicyDefinitions"; Flags: ignoreversion; Tasks: gpo
Source: "policy\en-US\QuantiSheet.adml"; DestDir: "{win}\PolicyDefinitions\en-US"; Flags: ignoreversion; Tasks: gpo
Source: "..\docs\IT_DEPLOYMENT.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "it\Detect-QuantiSheet.ps1"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{commonprograms}\QuantiSheet"; Filename: "{app}\QuantiSheet.exe"; IconFilename: "{app}\QuantiSheet.exe"; Comment: "QuantiSheet"; AppUserModelID: "QuantiSheet.App"
Name: "{commonprograms}\QuantiSheet IT Deployment Guide"; Filename: "{app}\docs\IT_DEPLOYMENT.md"
Name: "{commondesktop}\QuantiSheet"; Filename: "{app}\QuantiSheet.exe"; IconFilename: "{app}\QuantiSheet.exe"; AppUserModelID: "QuantiSheet.App"; Tasks: desktopicon

[Registry]
; "Open with" for every user (never the default PDF app). Its own ProgID,
; QuantiSheet.Server.pdf, so uninstalling the standalone setup
; (QuantiSheet.pdf) can't take this one's Open-with entry, or the other
; way round. No Applications\QuantiSheet.exe key: that one is keyed by the
; exe name and belongs to the standalone setup; OpenWithProgids is enough
; here (the same for App Paths\QuantiSheet.exe). FriendlyAppName is what
; Open with shows.
Root: HKLM; Subkey: "Software\Classes\QuantiSheet.Server.pdf"; ValueType: string; ValueName: ""; ValueData: "PDF Document (QuantiSheet)"; Flags: uninsdeletekey; Tasks: openwith
Root: HKLM; Subkey: "Software\Classes\QuantiSheet.Server.pdf\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: openwith
Root: HKLM; Subkey: "Software\Classes\QuantiSheet.Server.pdf\shell\open"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "QuantiSheet"; Tasks: openwith
Root: HKLM; Subkey: "Software\Classes\QuantiSheet.Server.pdf\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" ""%1"""; Tasks: openwith
Root: HKLM; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: none; ValueName: "QuantiSheet.Server.pdf"; Flags: uninsdeletevalue; Tasks: openwith
; policy values from the command line (only those given), where Group
; Policy writes too
Root: HKLM; Subkey: "Software\Policies\QuantiSheet"; ValueType: string; ValueName: "LicenseKey"; ValueData: "{param:LICENSEKEY}"; Flags: uninsdeletevalue; Check: HasParam('LICENSEKEY')
Root: HKLM; Subkey: "Software\Policies\QuantiSheet"; ValueType: string; ValueName: "PriceDatabasePath"; ValueData: "{param:PRICEDB}"; Flags: uninsdeletevalue; Check: HasParam('PRICEDB')
Root: HKLM; Subkey: "Software\Policies\QuantiSheet"; ValueType: string; ValueName: "RelayURL"; ValueData: "{param:RELAYURL}"; Flags: uninsdeletevalue; Check: HasParam('RELAYURL')
Root: HKLM; Subkey: "Software\Policies\QuantiSheet"; ValueType: string; ValueName: "AIHost"; ValueData: "{param:AIHOST}"; Flags: uninsdeletevalue; Check: HasParam('AIHOST')
Root: HKLM; Subkey: "Software\Policies\QuantiSheet"; ValueType: string; ValueName: "LogDirectory"; ValueData: "{param:LOGDIR}"; Flags: uninsdeletevalue; Check: HasParam('LOGDIR')
Root: HKLM; Subkey: "Software\Policies\QuantiSheet"; ValueType: dword; ValueName: "AcceptAgreement"; ValueData: "1"; Flags: uninsdeletevalue; Check: HasParam('ACCEPTAGREEMENT')
Root: HKLM; Subkey: "Software\Policies\QuantiSheet"; ValueType: dword; ValueName: "SkipEmailSignIn"; ValueData: "1"; Flags: uninsdeletevalue; Check: HasParam('SKIPSIGNIN')
Root: HKLM; Subkey: "Software\Policies\QuantiSheet"; ValueType: dword; ValueName: "OfflineMode"; ValueData: "1"; Flags: uninsdeletevalue; Check: HasParam('OFFLINE')
Root: HKLM; Subkey: "Software\Policies\QuantiSheet"; ValueType: dword; ValueName: "DisableAI"; ValueData: "1"; Flags: uninsdeletevalue; Check: HasParam('NOAI')
Root: HKLM; Subkey: "Software\Policies\QuantiSheet"; Flags: uninsdeletekeyifempty
; every user's printer sign-in entry (printer --all-users): printer
; --remove deletes it on uninstall; this makes sure
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "QuantiSheet Printer"; Flags: dontcreatekey uninsdeletevalue

[Run]
; the relay: a scheduled task that starts with Windows as LocalService
; (low rights; no user needs to be signed in) - it may write only to
; ProgramData\QuantiSheet\relay (icacls, S-1-5-19 = LocalService) - and an
; inbound firewall rule
; ProgramData lets any user create files; this folder holds IT's
; policy.json, so only SYSTEM and Administrators may change it - users
; read (S-1-5-18 SYSTEM, -32-544 Administrators, -32-545 Users). The
; folder's owner is set too (a folder a user made before the setup ran is
; theirs) - the folder only: the print spool's job files must keep their
; owners (app/printhelper.py)
Filename: "{sys}\icacls.exe"; Parameters: """{commonappdata}\QuantiSheet"" /setowner *S-1-5-32-544"; Flags: runhidden waituntilterminated; Check: NewDataDirExists
Filename: "{sys}\icacls.exe"; Parameters: """{commonappdata}\QuantiSheet"" /inheritance:r /grant:r *S-1-5-18:(OI)(CI)F *S-1-5-32-544:(OI)(CI)F *S-1-5-32-545:(OI)(CI)RX"; Flags: runhidden waituntilterminated; Check: NewDataDirExists
; the relay's own folder (shared projects, signer tokens, its log): no
; access for users at all - only the relay (LocalService) and admins.
; Also when the relay task isn't chosen this time but its folder is there
Filename: "{sys}\icacls.exe"; Parameters: """{code:RelayDir}"" /inheritance:r /grant:r *S-1-5-18:(OI)(CI)F *S-1-5-32-544:(OI)(CI)F *S-1-5-19:(OI)(CI)M"; Flags: runhidden waituntilterminated; Check: RelayDirExists
; the relay token, made now (as admin) so it can be shared: users may
; read that one file - they need it to connect - and nothing else there
Filename: "{app}\QuantiSheet.exe"; Parameters: "relay --make-token --token-file ""{code:RelayDir}\relay-token.txt"""; Flags: runhidden waituntilterminated; Tasks: relay
Filename: "{sys}\icacls.exe"; Parameters: """{code:RelayDir}\relay-token.txt"" /grant *S-1-5-32-545:R"; Flags: runhidden waituntilterminated; Check: RelayTokenExists
; netsh adds a second rule of the same name, so the old one goes first
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""QuantiSheet Relay"""; Flags: runhidden waituntilterminated; Tasks: relay
Filename: "{sys}\schtasks.exe"; Parameters: "/Create /F /TN ""QuantiSheet Relay"" /SC ONSTART /RU ""NT AUTHORITY\LOCALSERVICE"" /TR ""\""{app}\QuantiSheet.exe\"" relay --host 0.0.0.0 --token-file \""{code:RelayDir}\relay-token.txt\"" --data-dir \""{code:RelayDir}\hub\"" --log \""{code:RelayDir}\relay.log\"""""; Flags: runhidden waituntilterminated; StatusMsg: "Setting up the collaboration relay..."; Tasks: relay
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""QuantiSheet Relay"" dir=in action=allow protocol=TCP localport=8765,8766 program=""{app}\QuantiSheet.exe"""; Flags: runhidden waituntilterminated; Tasks: relay
Filename: "{sys}\schtasks.exe"; Parameters: "/Run /TN ""QuantiSheet Relay"""; Flags: runhidden waituntilterminated; Tasks: relay

; the "QuantiSheet" printer (off unless the task is chosen): printer, port,
; spool folder, and each user's helper started at sign-in, as them
; (app/printer_setup.py)
Filename: "{app}\QuantiSheet.exe"; Parameters: "printer --install --all-users"; Flags: runhidden waituntilterminated; StatusMsg: "Adding the QuantiSheet printer..."; Tasks: printer

[UninstallRun]
Filename: "{app}\QuantiSheet.exe"; Parameters: "printer --remove"; Flags: runhidden waituntilterminated; RunOnceId: "DelPrinter"
Filename: "{sys}\schtasks.exe"; Parameters: "/End /TN ""QuantiSheet Relay"""; Flags: runhidden waituntilterminated; RunOnceId: "EndRelayQS"
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /F /TN ""QuantiSheet Relay"""; Flags: runhidden waituntilterminated; RunOnceId: "DelRelayQS"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""QuantiSheet Relay"""; Flags: runhidden waituntilterminated; RunOnceId: "DelFirewallQS"

[InstallDelete]
; 1.0.0 has no Beta Agreement: remove the copy an earlier version left
Type: files; Name: "{app}\BETA-AGREEMENT.txt"

[Code]
const
  NewExe = 'QuantiSheet.exe';
  NewDirName = 'QuantiSheet';
  NewDataName = 'QuantiSheet';
  // where Inno Setup records this AppId's install (all users: HKLM)
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{6A0E2C4B-9F31-4D2B-8C55-3B1D2E7F9A40}_is1';

var
  PrevDirRead: Boolean;
  PrevDirValue: String;

// the folder the previous install of this setup is in ('' = none)
function PreviousAppDir(): String;
begin
  if not PrevDirRead then
  begin
    PrevDirRead := True;
    if not RegQueryStringValue(HKA, UninstallKey, 'Inno Setup: App Path', PrevDirValue) then
      PrevDirValue := '';
    if PrevDirValue <> '' then
      PrevDirValue := RemoveBackslashUnlessRoot(PrevDirValue);
  end;
  Result := PrevDirValue;
end;

// DefaultDirName: a new install goes to ...\QuantiSheet; an upgrade stays
// where the previous install is
function DefaultAppDir(Param: String): String;
var
  Prev: String;
begin
  Prev := PreviousAppDir();
  if Prev = '' then
    Result := ExpandConstant('{commonpf64}\') + NewDirName
  else
    Result := Prev;
end;

// an upgrade doesn't ask where to install (as before)
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = wpSelectDir) and (PreviousAppDir() <> '');
end;

function HasParam(Name: String): Boolean;
begin
  Result := ExpandConstant('{param:' + Name + '|}') <> '';
end;

function NewDataDir(): String;
begin
  Result := ExpandConstant('{commonappdata}\') + NewDataName;
end;

function NewDataDirExists(): Boolean;
begin
  Result := DirExists(NewDataDir());
end;

// the relay's folder: ProgramData\QuantiSheet\relay
function RelayDir(Param: String): String;
begin
  Result := NewDataDir() + '\relay';
end;

function RelayDirExists(): Boolean;
begin
  Result := DirExists(RelayDir(''));
end;

function RelayTokenExists(): Boolean;
begin
  Result := FileExists(RelayDir('') + '\relay-token.txt');
end;

// the windowless print helpers ("QuantiSheet.exe print-helper", one per
// signed-in person) started from Dir: they hold the program folder open
// and have no window to close, so they are stopped here. Each starts
// again when that person opens QuantiSheet or signs in. QuantiSheet
// windows are closed by CloseApplications.
procedure StopHelpers(Dir: String);
var
  ResultCode: Integer;
  AppDir, PS: String;
begin
  // only helpers started from that folder (a PowerShell single-quoted
  // string: a quote in the path is doubled)
  AppDir := Dir + '\';
  StringChangeEx(AppDir, '''', '''''', True);
  PS := 'Get-CimInstance Win32_Process | Where-Object { $_.Name -eq ''' + NewExe +
        ''' -and $_.CommandLine -like ''*print-helper*''' +
        ' -and $_.ExecutablePath -and $_.ExecutablePath.StartsWith(''' + AppDir +
        ''', [StringComparison]::OrdinalIgnoreCase) }' +
        ' | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }';
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
       '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "' + PS + '"',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

// uninstall: stop the print helper first, or it keeps the program folder
// open and files are left behind (Chief's r45 review, item 7)
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    StopHelpers(ExpandConstant('{app}'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopHelpers(ExpandConstant('{app}'));
  Result := '';
end;
