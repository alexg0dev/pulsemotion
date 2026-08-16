@echo off
title PulseMotion Setup
cd /d "%~dp0"

echo ========================================
echo   PulseMotion - First-time setup
echo ========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found.
    echo Install Python 3.10+ from https://www.python.org/downloads/
    echo Check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

echo Installing dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Setup complete!
echo   Run start.bat to launch PulseMotion.
echo ========================================
echo.
pause
