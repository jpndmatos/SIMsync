@echo off
echo Cleaning old build...
rmdir /s /q build 2>nul
del /f /q SIMsync.exe 2>nul

echo Building SIMsync.exe...
python -m PyInstaller --distpath . SIMsync.spec

if %errorlevel% == 0 (
    echo.
    echo Build complete: SIMsync.exe
) else (
    echo.
    echo Build failed.
    pause
)
