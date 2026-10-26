@echo off
setlocal
cd /d "%~dp0"
echo.
echo   SlothOps - Your chores. A slower pace.
echo.
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -c "import streamlit, requests, pypdf" >nul 2>&1
if errorlevel 1 (
    echo Installing local app dependencies...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto failed
)
echo Opening SlothOps at http://127.0.0.1:8501
echo Keep this window open while using the app. Press Ctrl+C to stop.
".venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1 --server.headless false
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo SlothOps could not start. Read the error above and the troubleshooting section in README.md.
pause
exit /b 1
