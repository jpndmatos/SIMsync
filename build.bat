@echo off
echo Cleaning old build...
rmdir /s /q build 2>nul
del /f /q SIMsync.exe 2>nul

echo Building SIMsync.exe...
set PYTHONNOUSERSITE=1
set PYTHONUSERBASE=%cd%\.pyuser
python -m PyInstaller --distpath . SIMsync.spec
rmdir /s /q build 2>nul
rmdir /s /q .pyuser 2>nul

if %errorlevel% == 0 (
    echo.
    echo Build complete: SIMsync.exe
) else (
    echo.
    echo Build failed.
    pause
)
