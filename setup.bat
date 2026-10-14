@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install Python 3.11 or newer and enable Add Python to PATH.
    exit /b 1
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
    echo ChessLab requires Python 3.11 or newer.
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Installation failed. Check your internet connection and try setup.bat again.
    exit /b 1
)
echo ChessLab is ready. Run launch.bat to play.
