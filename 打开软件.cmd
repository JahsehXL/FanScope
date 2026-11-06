@echo off
setlocal
if exist "%~dp0app\FanScope.exe" (
    start "" "%~dp0app\FanScope.exe"
    exit /b 0
)
echo Download FanScope.exe from Releases and put it in the app folder.
start "" "https://github.com/JahsehXL/FanScope/releases/latest/download/FanScope.exe"
pause
exit /b 1
