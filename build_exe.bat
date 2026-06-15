@echo off
echo ── Server Deployer — Build EXE ─────────────────────────────────────────────
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install from https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Create venv
if not exist "%~dp0venv" (
    echo Creating virtual environment...
    python -m venv "%~dp0venv"
)

call "%~dp0venv\Scripts\activate.bat"

echo Installing dependencies...
pip install -q customtkinter paramiko pyinstaller

echo.
echo Building executable...
pyinstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "ServerDeployer" ^
    --collect-data customtkinter ^
    --collect-data paramiko ^
    --hidden-import paramiko ^
    --hidden-import paramiko.transport ^
    --hidden-import paramiko.auth_handler ^
    --hidden-import cryptography ^
    --hidden-import bcrypt ^
    "%~dp0app.py"

echo.
if exist "%~dp0dist\ServerDeployer.exe" (
    echo [SUCCESS] EXE created at:
    echo   %~dp0dist\ServerDeployer.exe
    echo.
    echo You can copy ServerDeployer.exe anywhere and run it — no Python needed.
) else (
    echo [ERROR] Build failed. See output above for details.
)

pause
