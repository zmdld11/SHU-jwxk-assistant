@echo off
cd /d "%~dp0"
echo ========================================
echo     ShangDa Course Monitor - Starting...
echo ========================================
start http://127.0.0.1:5000
".venv\Scripts\python.exe" app.py
if %errorlevel% neq 0 (
    echo.
    echo FAILED! Please check:
    echo 1. Run: .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo 2. Cookies in .env are valid
    pause
)
