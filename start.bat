@echo off
title PulseMotion
cd /d "%~dp0"

if not exist "truly.py" (
    echo ERROR: truly.py not found. Run this from the pulsemotion folder.
    pause
    exit /b 1
)

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Run setup.bat first or install Python 3.10+
    pause
    exit /b 1
)

echo Starting PulseMotion...
echo Keep this window open while using the app.
echo.
python truly.py
if errorlevel 1 (
    echo.
    echo PulseMotion exited with an error.
    echo Try running setup.bat if dependencies are missing.
    pause
)
