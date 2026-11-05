@echo off
rem QuantiSheet installer for Windows: double-click this file.
rem Installs the programs QuantiSheet uses (Python, Tesseract OCR, Ollama and
rem its AI model, LibreOffice) if they're missing, sets up a private Python
rem environment in this folder, installs the libraries, runs the tests, and
rem puts a "QuantiSheet" shortcut on the Desktop.
rem
rem   install.bat /minimal   skip the big optional pieces (AI model, LibreOffice)
rem   install.bat /noai      skip only the AI model
setlocal
cd /d "%~dp0"
title QuantiSheet setup

echo.
echo === QuantiSheet setup ===
echo.

rem ---- programs QuantiSheet uses ----
set DEPS_ARGS=
if /i "%~1"=="/minimal" set DEPS_ARGS=-NoAIModel -NoLibreOffice
if /i "%~1"=="/noai" set DEPS_ARGS=-NoAIModel
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install_deps.ps1" %DEPS_ARGS%

rem ---- find Python (3.10 - 3.13 preferred) ----
set PY=
for %%V in (3.12 3.13 3.11 3.10) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set PY=py -%%V
    )
)
if not defined PY (
    py -3 -c "import sys" >nul 2>&1 && set PY=py -3
)
if not defined PY (
    python -c "import sys" >nul 2>&1 && set PY=python
)
rem just installed: not on this window's PATH yet
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PY (
    echo Python was not found.
    echo Install Python 3.12 from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during setup, then run this again.
    goto :fail
)
echo Using: %PY%
%PY% --version

rem ---- private environment ----
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo Creating environment...
    %PY% -m venv .venv || goto :fail
)
set VPY=.venv\Scripts\python.exe

echo.
echo Installing libraries (first time takes a few minutes)...
"%VPY%" -m pip install --upgrade pip wheel || goto :fail
"%VPY%" -m pip install -r requirements.txt pytest || goto :fail

rem ---- check it works ----
echo.
echo Running tests...
set QT_QPA_PLATFORM=offscreen
"%VPY%" -m pytest -q > install-test-results.txt 2>&1
set TESTS=%ERRORLEVEL%
set QT_QPA_PLATFORM=
type install-test-results.txt | findstr /R /C:"passed" /C:"failed" /C:"error"
if not "%TESTS%"=="0" (
    echo.
    echo Some tests failed. Details are in install-test-results.txt
    echo ^(send that file to Claude^). Continuing with the install.
)

if not exist sample.pdf "%VPY%" make_sample.py sample.pdf

rem ---- Desktop shortcut ----
echo.
echo Creating Desktop shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d=[Environment]::GetFolderPath('Desktop');" ^
  "Remove-Item -LiteralPath (Join-Path $d 'QuantiSheet.lnk') -ErrorAction SilentlyContinue;" ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'QuantiSheet.lnk'));" ^
  "$s.TargetPath='%~dp0.venv\Scripts\pythonw.exe';" ^
  "$s.Arguments='\"%~dp0quantisheet.py\"';" ^
  "$s.WorkingDirectory='%~dp0';" ^
  "$s.IconLocation='%~dp0icon.ico';" ^
  "$s.Description='QuantiSheet';" ^
  "$s.Save()"

rem ---- optional extras ----
echo.
echo What was installed is listed in install-deps-log.txt.

echo.
echo === Done ===
echo Opening QuantiSheet with sample.pdf...
start "" ".venv\Scripts\pythonw.exe" quantisheet.py sample.pdf
echo.
pause
exit /b 0

:fail
echo.
echo SETUP FAILED - see the message above.
pause
exit /b 1
