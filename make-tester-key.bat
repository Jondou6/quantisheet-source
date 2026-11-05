@echo off
rem Make a QuantiSheet beta license key for one tester.
setlocal
cd /d "%~dp0"
set VPY=.venv\Scripts\python.exe
if not exist "%VPY%" set VPY=python
title QuantiSheet - tester key

echo.
echo === New beta tester key ===
echo.
set /p NAME=Tester's full name:
if "%NAME%"=="" goto :eof
set /p COMPANY=Company (optional):
set /p EMAIL=Email (optional):
set /p DAYS=Days the key lasts [60]:
if "%DAYS%"=="" set DAYS=60

"%VPY%" tools\beta_keys.py issue "%NAME%" --company "%COMPANY%" --email "%EMAIL%" --days %DAYS%
echo.
echo The key is also saved in the "QuantiSheet Keys" folder in your user folder,
echo ready to email. Opening that folder...
start "" "%USERPROFILE%\QuantiSheet Keys"
pause
