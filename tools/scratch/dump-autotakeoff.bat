@echo off
cd /d "%~dp0"
if not exist trial_output mkdir trial_output
.venv\Scripts\python.exe tools\autotakeoff_dump.py trial\ShelterCove_A-sheets.pdf 1 18 > trial_output\at_dump.txt 2>&1
.venv\Scripts\python.exe tools\autotakeoff_dump.py trial\ShelterCove_A-sheets.pdf 2 18 >> trial_output\at_dump.txt 2>&1
