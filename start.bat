@echo off
setlocal EnableDelayedExpansion
title PulseMotion
cd /d "%~dp0"

echo Stopping any old PulseMotion servers (fixes wrong port / broken page)...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*truly.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul

if not exist "truly.py" (
    echo ERROR: truly.py not found.
    pause
    exit /b 1
)

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not installed. Get it from https://www.python.org/downloads/
    echo Check "Add Python to PATH" during install.
    pause
    exit /b 1
)

echo Installing/updating dependencies...
python -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo ERROR: pip install failed. Run: python -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo.
echo Starting server — browser will open automatically...
echo USE THE URL SHOWN BELOW (usually http://localhost:8000)
echo DO NOT CLOSE THIS WINDOW.
echo.
python truly.py
if exist port.txt (
    echo.
    echo If the browser did not open, go to:
    set /p PORT=<port.txt
    echo   http://localhost:!PORT!
)
echo.
echo Server stopped.
pause
