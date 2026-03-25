@echo off
echo Cleaning old build...
rmdir /s /q build 2>nul
del /f /q dist\SIMsync.exe 2>nul

echo Building SIMsync.exe...
python -m PyInstaller SIMsync.spec

if %errorlevel% == 0 (
    echo.
    echo Build complete: dist\SIMsync.exe
) else (
    echo.
    echo Build failed.
    pause
)