@echo off
setlocal
if exist "%~dp0app\FanScope.exe" (
    start "" "%~dp0app\FanScope.exe"
    exit /b 0
)
echo Download the Windows ZIP from Releases and put FanScope.exe in the app folder.
start "" "https://github.com/JahsehXL/FanScope/releases/latest"
pause
exit /b 1
