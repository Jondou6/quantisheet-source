@echo off
rem Runs the QuantiSheet test suite and saves the results to test-results.txt
cd /d "%~dp0"
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider > test-results.txt 2>&1
type test-results.txt | findstr /R /C:"passed" /C:"failed" /C:"error"
echo.
echo Full results: test-results.txt
