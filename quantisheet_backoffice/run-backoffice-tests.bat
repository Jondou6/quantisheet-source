@echo off
rem Back Office's own suite. Run from anywhere; it works out the QuantiSheet
rem folder from where this file is (no fixed Desktop path). Uses a throwaway
rem home folder so nothing touches your real settings or ~/.quantisheet.
setlocal
set "BO=%~dp0"
pushd "%BO%.."
set "T=%TEMP%\qsbo-test-%RANDOM%"
mkdir "%T%"
set "QS_BACKOFFICE_HOME=%T%\bo"
set "HOME=%T%"
set "USERPROFILE=%T%"
set "APPDATA=%T%\AppData\Roaming"
set "LOCALAPPDATA=%T%\AppData\Local"
set QT_QPA_PLATFORM=offscreen
python -m pytest quantisheet_backoffice\tests -q %*
set RC=%ERRORLEVEL%
echo.
echo QuantiSheet's side of the hook (needs QuantiSheet's tests folder):
python -m pytest quantisheet_backoffice\host_tests -q -p no:cacheprovider
popd
rmdir /s /q "%T%" 2>nul
exit /b %RC%
