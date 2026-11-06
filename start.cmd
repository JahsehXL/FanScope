@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    python -m venv .venv
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -c "import playwright.sync_api, openpyxl, customtkinter, PIL" >nul 2>&1
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto failed
)
start "" ".venv\Scripts\pythonw.exe" collector.py
exit /b 0
:failed
echo Setup failed. Python 3.12 and network access are required.
pause
exit /b 1
