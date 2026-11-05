@echo off
rem Timed trial of QuantiSheet features on trial\spec.pdf
cd /d "%~dp0"
.venv\Scripts\python.exe tools\trial_run.py trial\spec.pdf trial\trial-report.txt > trial\trial-console.txt 2>&1
