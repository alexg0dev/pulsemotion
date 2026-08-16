@echo off
title PulseMotion
cd /d "%~dp0"

echo Starting PulseMotion...
python truly.py
if errorlevel 1 (
    echo.
    echo PulseMotion exited with an error.
    pause
)
