@echo off
rem Starts the background test runner used during remote work sessions.
rem It stops by itself after 10 hours (or create .run\STOP).
cd /d "%~dp0"
start "" .venv\Scripts\pythonw.exe tools\runner.py
