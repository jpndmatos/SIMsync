@echo off
setlocal

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Missing .venv\Scripts\python.exe
    exit /b 1
)

".venv\Scripts\python.exe" -m PyInstaller ^
    --clean ^
    --noconfirm ^
    --onefile ^
    --name 3cket2brella ^
    api.py

if errorlevel 1 (
    echo [ERROR] Build failed.
    exit /b 1
)

echo [OK] Executable created at dist\3cket2brella.exe