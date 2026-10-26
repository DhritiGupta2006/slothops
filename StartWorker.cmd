@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run StartSlothOps.cmd once to install the local environment.
    pause
    exit /b 1
)
echo Routines run while this window is open. Press Ctrl+C to stop.
echo File changes always require approval in SlothOps.
".venv\Scripts\python.exe" -m slothops.worker
pause
