@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe tools\autotakeoff_demo.py trial\ShelterCove_A-sheets.pdf trial\autotakeoff_demo.pdf
start "" .venv\Scripts\pythonw.exe quantisheet.py trial\autotakeoff_demo.pdf
