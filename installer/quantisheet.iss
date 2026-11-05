; QuantiSheet beta installer (Inno Setup 6).
; Installs go to ...\QuantiSheet; an upgrade stays in the folder the
; previous install is in (DefaultAppDir below).
; Built by tools/build_installer.py, which passes:
;   /DAppVersion=0.12.3  /DSourceDir=<PyInstaller dist\QuantiSheet>  /DOutputDir=<release>
#ifndef AppVersion
  #define AppVersion "0.12.3"
#endif
#ifndef AppPublisher
  #define AppPublisher "QuantiSheet"
#endif
#ifndef OutputBase
  #define OutputBase "QuantiSheet-Beta-Setup-" + AppVersion
#endif

[Setup]
; never change the AppId: it is how this setup finds and upgrades an
; earlier install
AppId={{375F90B3-3B41-4FE9-B790-B29C6D30C75E}
AppName=QuantiSheet
AppVersion={#AppVersion}
AppVerName=QuantiSheet {#AppVersion}
AppPublisher={#AppPublisher}
AppCopyright=Copyright (C) 2026 {#AppPublisher}.
VersionInfoVersion={#AppVersion}
VersionInfoDescription=QuantiSheet Setup
; {autopf}\QuantiSheet, or the folder an upgrade stays in (DefaultAppDir)
DefaultDirName={code:DefaultAppDir}
UsePreviousAppDir=no
DefaultGroupName=QuantiSheet
DisableProgramGroupPage=yes
; installs for the current user without admin rights; the user can choose
; "all users" on the first page (that asks for admin)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\QuantiSheet.exe
UninstallDisplayName=QuantiSheet
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBase}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Canva / company branding (v34): left panel + top-right badge
WizardImageFile=wizard-side.bmp
WizardSmallImageFile=wizard-small.bmp
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Put a QuantiSheet shortcut on the Desktop"; GroupDescription: "Shortcuts:"
Name: "openwith"; Description: "Add QuantiSheet to ""Open with"" for PDF files"; GroupDescription: "Shortcuts:"
Name: "shellverbs"; Description: "Add QuantiSheet actions to the right-click menu (combine, reduce size, convert to PDF)"; GroupDescription: "Shortcuts:"
Name: "ocr"; Description: "Install Tesseract OCR (makes scanned drawings searchable)"; GroupDescription: "Optional extras (downloaded during setup):"; Flags: unchecked
Name: "ai"; Description: "Install local AI - Ollama and its model, about 2 GB (AI review, RFI finder)"; GroupDescription: "Optional extras (downloaded during setup):"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*DEEP_DIVE*,*DEEP-DIVE*,FOR_CLAUDE_*,*XACTIMATE*,*SAGESURE*,*EAGLEVIEW*,*.esx,*_BRIEF.md,*_BRIEF.pdf"
Source: "..\tools\install_deps.ps1"; DestDir: "{app}\extras"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\QuantiSheet"; Filename: "{app}\QuantiSheet.exe"; IconFilename: "{app}\QuantiSheet.exe"; Comment: "QuantiSheet"; AppUserModelID: "QuantiSheet.App"
Name: "{autodesktop}\QuantiSheet"; Filename: "{app}\QuantiSheet.exe"; IconFilename: "{app}\QuantiSheet.exe"; AppUserModelID: "QuantiSheet.App"; Tasks: desktopicon

[Registry]
; "Open with" only - QuantiSheet does not take over as the default PDF app.
; ProgID QuantiSheet.pdf is this setup's own: the server setup and the MSI
; use QuantiSheet.Server.pdf, so uninstalling one leaves the other's entry.
; FriendlyAppName is the name the Open-with list shows
Root: HKA; Subkey: "Software\Classes\QuantiSheet.pdf"; ValueType: string; ValueName: ""; ValueData: "PDF Document (QuantiSheet)"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\QuantiSheet.pdf\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\QuantiSheet.pdf\shell\open"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "QuantiSheet"; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\QuantiSheet.pdf\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" ""%1"""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: none; ValueName: "QuantiSheet.pdf"; Flags: uninsdeletevalue; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\QuantiSheet.exe\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" ""%1"""; Flags: uninsdeletekey; Tasks: openwith
; QuantiSheet tool set files (Tool Chest > Save Sets as a File): this is
; the program's own file type, so double-clicking one opens it in
; QuantiSheet and adds the sets to the Tool Chest (Nov 2)
; Nov 3: right-click actions in File Explorer (app/shellverbs.py)
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\QuantiSheet.Open"; ValueType: string; ValueName: ""; ValueData: "Open in QuantiSheet"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\QuantiSheet.Open"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\QuantiSheet.Open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\QuantiSheet.Reduce"; ValueType: string; ValueName: ""; ValueData: "Reduce size (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\QuantiSheet.Reduce"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\QuantiSheet.Reduce\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-reduce ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.doc\shell\QuantiSheet.Convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.doc\shell\QuantiSheet.Convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.doc\shell\QuantiSheet.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-convert ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.docx\shell\QuantiSheet.Convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.docx\shell\QuantiSheet.Convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.docx\shell\QuantiSheet.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-convert ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.rtf\shell\QuantiSheet.Convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.rtf\shell\QuantiSheet.Convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.rtf\shell\QuantiSheet.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-convert ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odt\shell\QuantiSheet.Convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odt\shell\QuantiSheet.Convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odt\shell\QuantiSheet.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-convert ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xls\shell\QuantiSheet.Convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xls\shell\QuantiSheet.Convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xls\shell\QuantiSheet.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-convert ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xlsx\shell\QuantiSheet.Convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xlsx\shell\QuantiSheet.Convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xlsx\shell\QuantiSheet.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-convert ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xlsm\shell\QuantiSheet.Convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xlsm\shell\QuantiSheet.Convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xlsm\shell\QuantiSheet.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-convert ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.csv\shell\QuantiSheet.Convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.csv\shell\QuantiSheet.Convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.csv\shell\QuantiSheet.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-convert ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ods\shell\QuantiSheet.Convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ods\shell\QuantiSheet.Convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ods\shell\QuantiSheet.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-convert ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ppt\shell\QuantiSheet.Convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ppt\shell\QuantiSheet.Convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ppt\shell\QuantiSheet.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-convert ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pptx\shell\QuantiSheet.Convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pptx\shell\QuantiSheet.Convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pptx\shell\QuantiSheet.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-convert ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odp\shell\QuantiSheet.Convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odp\shell\QuantiSheet.Convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odp\shell\QuantiSheet.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-convert ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.txt\shell\QuantiSheet.Convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.txt\shell\QuantiSheet.Convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.txt\shell\QuantiSheet.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-convert ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.md\shell\QuantiSheet.Convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.md\shell\QuantiSheet.Convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.md\shell\QuantiSheet.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-convert ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.html\shell\QuantiSheet.Convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.html\shell\QuantiSheet.Convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.html\shell\QuantiSheet.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-convert ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.htm\shell\QuantiSheet.Convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.htm\shell\QuantiSheet.Convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.htm\shell\QuantiSheet.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-convert ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.png\shell\QuantiSheet.Convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.png\shell\QuantiSheet.Convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.png\shell\QuantiSheet.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-convert ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.jpg\shell\QuantiSheet.Convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.jpg\shell\QuantiSheet.Convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.jpg\shell\QuantiSheet.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-convert ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.jpeg\shell\QuantiSheet.Convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.jpeg\shell\QuantiSheet.Convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.jpeg\shell\QuantiSheet.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-convert ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tif\shell\QuantiSheet.Convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tif\shell\QuantiSheet.Convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tif\shell\QuantiSheet.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-convert ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tiff\shell\QuantiSheet.Convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tiff\shell\QuantiSheet.Convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tiff\shell\QuantiSheet.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-convert ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.bmp\shell\QuantiSheet.Convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.bmp\shell\QuantiSheet.Convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.bmp\shell\QuantiSheet.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-convert ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.gif\shell\QuantiSheet.Convert"; ValueType: string; ValueName: ""; ValueData: "Convert to PDF (QuantiSheet)"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.gif\shell\QuantiSheet.Convert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.gif\shell\QuantiSheet.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-convert ""%1"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\Directory\shell\QuantiSheet.Combine"; ValueType: string; ValueName: ""; ValueData: "Combine PDFs in QuantiSheet"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\Directory\shell\QuantiSheet.Combine"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\Directory\shell\QuantiSheet.Combine\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-combine-folder ""%V"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\QuantiSheet.Combine"; ValueType: string; ValueName: ""; ValueData: "Combine PDFs in QuantiSheet"; Flags: uninsdeletekey; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\QuantiSheet.Combine"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\QuantiSheet.exe,0"; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\QuantiSheet.Combine\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" --qs-combine-folder ""%V"""; Tasks: shellverbs
Root: HKA; Subkey: "Software\Classes\.qstools"; ValueType: string; ValueName: ""; ValueData: "QuantiSheet.qstools"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\QuantiSheet.qstools"; ValueType: string; ValueName: ""; ValueData: "QuantiSheet Tool Set"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\QuantiSheet.qstools\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\QuantiSheet.exe,0"
Root: HKA; Subkey: "Software\Classes\QuantiSheet.qstools\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\QuantiSheet.exe"" ""%1"""
; the "Open with" entry 0.13.14 and earlier registered under the program's
; old name: removed on upgrade (QuantiSheet.pdf above replaces it)
Root: HKA; Subkey: "Software\Classes\PDFStudio.pdf"; ValueType: none; Flags: deletekey
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: none; ValueName: "PDFStudio.pdf"; Flags: deletevalue
; App Paths: Win+R / Start "QuantiSheet" finds the program (this setup's
; own - keyed by the exe name like Applications\, so the server setup and
; the MSI don't make one)
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\QuantiSheet.exe"; ValueType: string; ValueName: ""; ValueData: "{app}\QuantiSheet.exe"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\QuantiSheet.exe"; ValueType: string; ValueName: "Path"; ValueData: "{app}"
; the printer's sign-in entry, if Help > Add the QuantiSheet Printer made
; one (app/printhelper.py RUN_NAME): removed on uninstall
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "QuantiSheet Printer"; Flags: dontcreatekey uninsdeletevalue

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\extras\install_deps.ps1"" -NoPython -NoLibreOffice -NoAIModel"; StatusMsg: "Installing Tesseract OCR..."; Flags: waituntilterminated; Tasks: ocr and not ai
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\extras\install_deps.ps1"" -NoPython -NoLibreOffice"; StatusMsg: "Installing OCR and local AI (this can take a while)..."; Flags: waituntilterminated; Tasks: ai
Filename: "{app}\QuantiSheet.exe"; Description: "Start QuantiSheet now"; Flags: nowait postinstall skipifsilent
; an update started from inside QuantiSheet (Update now) installs quietly
; and starts it again when done (app/updatecheck.py QUIET_SWITCHES)
Filename: "{app}\QuantiSheet.exe"; Flags: nowait; Check: WantRelaunch

[InstallDelete]
; 1.0.0 has no Beta Agreement (Jon, Oct 30): remove the copy and the
; Start menu shortcut an earlier version left
Type: files; Name: "{app}\BETA-AGREEMENT.txt"
Type: files; Name: "{autoprograms}\QuantiSheet Beta Agreement.lnk"

[Code]
function WantRelaunch: Boolean;
begin
  { /QSRELAUNCH: started by QuantiSheet's own Update now }
  Result := Pos('/QSRELAUNCH', UpperCase(GetCmdTail)) > 0;
end;

const
  NewExe = 'QuantiSheet.exe';
  NewDirName = 'QuantiSheet';
  // where Inno Setup records this AppId's install (per user: HKCU, all
  // users: HKLM - HKA picks the one for this install mode)
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{375F90B3-3B41-4FE9-B790-B29C6D30C75E}_is1';

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
    Result := ExpandConstant('{autopf}\') + NewDirName
  else
    Result := Prev;
end;

// an upgrade doesn't ask where to install (as before)
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = wpSelectDir) and (PreviousAppDir() <> '');
end;

// the windowless print helper ("QuantiSheet.exe print-helper") started
// from Dir: it holds the program folder open and has no window to close,
// so it is stopped here. QuantiSheet starts it again when it opens (and
// at sign-in). QuantiSheet windows are closed by CloseApplications.
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
var
  Data, Msg: String;
begin
  if CurUninstallStep = usUninstall then
    StopHelpers(ExpandConstant('{app}'));
  // "delete my data" (Chief's Store review): QuantiSheet's own settings,
  // recovery copies and price database, and its sign-in memory - never
  // the user's drawings or job folders. Asked; No is the default, and a
  // silent uninstall keeps everything.
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
  begin
    Data := ExpandConstant('{%USERPROFILE}\.quantisheet');
    // (no line may start with "#": the preprocessor reads it)
    Msg := 'Also delete your QuantiSheet settings, recovery copies and ' +
           'price database?' + #13#10#13#10 + Data + #13#10#13#10 +
           'Your drawings and job folders are not touched. This cannot ' +
           'be undone.';
    if DirExists(Data) and (MsgBox(Msg, mbConfirmation,
        MB_YESNO or MB_DEFBUTTON2) = IDYES) then
    begin
      DelTree(Data, True, True, True);
      RegDeleteKeyIncludingSubkeys(HKCU, 'Software\QuantiSheet\Cache');
      RegDeleteKeyIfEmpty(HKCU, 'Software\QuantiSheet');
    end;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopHelpers(ExpandConstant('{app}'));
  Result := '';
end;
