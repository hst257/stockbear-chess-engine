@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Set up ChessLab first by running setup.bat.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m app.main %*
if errorlevel 1 (
    echo ChessLab exited with an error. Run setup.bat if dependencies are missing.
    pause
    exit /b 1
)
