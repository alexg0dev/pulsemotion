@echo off
title PulseMotion - Stop
cd /d "%~dp0"
echo Stopping all PulseMotion servers...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*truly.py*' } | ForEach-Object { Write-Host ('Stopping PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
if exist port.txt del /f port.txt
echo.
echo Done. Run start.bat to launch a fresh server on port 8000.
pause
