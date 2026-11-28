@echo off
rem Starts the background test runner used during remote work sessions.
rem It restarts itself every 24 hours; create .run\STOP to stop it.
cd /d "%~dp0"
start "" .venv\Scripts\pythonw.exe tools\runner.py
