@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe tools\diag_coords.py > trial_output\diag_gaps.txt 2>&1
