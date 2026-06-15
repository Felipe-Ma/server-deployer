@echo off
echo ── Server Deployer Setup ───────────────────────────────────────────────────
echo.

REM Check Python (tries both py launcher and python command)
py --version >nul 2>&1
if errorlevel 1 (
    python --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python not found. Install from https://www.python.org/downloads/
        pause
        exit /b 1
    )
    set PYTHON=python
) else (
    set PYTHON=py
)

REM Create venv if it doesn't exist
if not exist "%~dp0venv" (
    echo Creating virtual environment...
    %PYTHON% -m venv "%~dp0venv"
)

REM Activate and install deps
call "%~dp0venv\Scripts\activate.bat"
echo Installing dependencies...
pip install -q -r "%~dp0requirements.txt"

REM Launch app
echo.
echo Starting Server Deployer...
python "%~dp0app.py"
