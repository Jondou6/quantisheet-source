@echo off
rem Runs QuantiSheet from this folder (the newest changes, before an installer is built)
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" "quantisheet.py"
