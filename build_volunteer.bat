@echo off
setlocal

set DIST_DIR=volunteer_tool\standalone

echo Cleaning old volunteer build...
rmdir /s /q build 2>nul
rmdir /s /q "%DIST_DIR%" 2>nul

echo Building VolunteerTool.exe...
python -m PyInstaller --distpath "%DIST_DIR%" VolunteerTool.spec
if %errorlevel% neq 0 (
    echo.
    echo Build failed.
    pause
    exit /b 1
)

echo Copying runtime files...
if exist .env copy /Y .env "%DIST_DIR%\.env" >nul
if exist config.json copy /Y config.json "%DIST_DIR%\config.json" >nul
if not exist "%DIST_DIR%\data" mkdir "%DIST_DIR%\data"
if exist data\participants.csv copy /Y data\participants.csv "%DIST_DIR%\data\participants.csv" >nul

echo.
echo Build complete: %DIST_DIR%\VolunteerTool.exe
endlocal
