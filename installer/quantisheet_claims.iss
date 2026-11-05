; ClaimIT installer (Inno Setup 6) - a separate, optional program.
; Installs ClaimIT.exe to a ClaimIT\ folder BESIDE QuantiSheet's install
; folder (where app/claims_hook.launcher() looks). Writes nothing into QuantiSheet's
; folder or settings; uninstalling just removes the menu item on
; QuantiSheet's next start.
;   iscc /DAppVersion=0.1.0 /DSourceDir=..\dist\ClaimIT /DOutputDir=..\release quantisheet_claims.iss
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\ClaimIT"
#endif
#ifndef OutputDir
  #define OutputDir "..\release"
#endif

[Setup]
AppId={{B97431D7-084F-43E0-9326-C1A93CFFE28F}
AppName=ClaimIT
AppVersion={#AppVersion}
; the setup .exe's own FileVersion (review 0.13.9 #9)
VersionInfoVersion={#AppVersion}
AppPublisher=QuantiSheet
DefaultDirName={autopf}\ClaimIT
; always ClaimIT\ (no folder page)
UsePreviousAppDir=no
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
UninstallDisplayIcon={app}\ClaimIT.exe
OutputDir={#OutputDir}
OutputBaseFilename=ClaimIT-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion; Excludes: "*DEEP_DIVE*,*DEEP-DIVE*,FOR_CLAUDE_*,*XACTIMATE*,*SAGESURE*,*EAGLEVIEW*,*.esx,*_BRIEF.md,*_BRIEF.pdf"

[Icons]
Name: "{autoprograms}\ClaimIT"; Filename: "{app}\ClaimIT.exe"
