@echo off
title PulseMotion
cd /d "%~dp0"

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
echo DO NOT CLOSE THIS WINDOW.
echo.
python truly.py
echo.
echo Server stopped.
pause
