@echo off
rem Checks auto takeoff against the room tags on the Shelter Cove sheets
cd /d "%~dp0"
(echo A-101 & .venv\Scripts\python.exe tools\autotakeoff_check.py trial\ShelterCove_A-sheets.pdf 1 18 & echo. & echo A-102 & .venv\Scripts\python.exe tools\autotakeoff_check.py trial\ShelterCove_A-sheets.pdf 2 18) > autotakeoff-results.txt 2>&1
type autotakeoff-results.txt
