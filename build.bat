@echo off
rem Build a single-file QuantiSheet executable into dist\ (Windows).
setlocal
cd /d "%~dp0"
if "%PY%"=="" set PY=python

echo == creating venv ==
%PY% -m venv .venv || goto :fail
call .venv\Scripts\activate.bat || goto :fail

echo == installing ==
python -m pip install --upgrade pip wheel || goto :fail
pip install -r requirements.txt || goto :fail
pip install "pyinstaller>=6.3,<7" pytest || goto :fail

echo == testing ==
set QT_QPA_PLATFORM=offscreen
python -m pytest -q || goto :fail

echo == building ==
pyinstaller --clean --noconfirm quantisheet.spec || goto :fail

echo == done ==
dir dist
exit /b 0

:fail
echo.
echo BUILD FAILED - see the error above.
exit /b 1
