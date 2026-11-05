@echo off
rem Runs the ClaimIT test suite (separate from QuantiSheet's tests)
cd /d "%~dp0"
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider quantisheet_claims\tests > claims-test-results.txt 2>&1
type claims-test-results.txt | findstr /R /C:"passed" /C:"failed" /C:"error"
echo.
echo Full results: claims-test-results.txt
