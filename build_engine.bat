@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run setup.bat first.
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r engine\requirements-build.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" tools\build_engine.py
exit /b %errorlevel%
