@echo off
rem QuantiSheet PDF thumbnails: turn them off for this user (nothing else is
rem touched). File Explorer goes back to the plain PDF icon.
reg delete "HKCU\Software\Classes\.pdf\ShellEx\{e357fccd-a995-4576-b01f-234630154e96}" /f >nul 2>&1
reg delete "HKCU\Software\Classes\CLSID\{6E1B2C3A-9D47-4F0B-8A51-2C7D0E4B9F16}" /f >nul 2>&1
echo QuantiSheet PDF thumbnails are off. Restart File Explorer (or sign out and in) if a picture is still shown.
pause
