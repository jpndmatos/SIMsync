@echo off
setlocal

set "BUILD_MODE=%~1"
set "CREATE_SEND_PACKAGE=0"
if /I "%BUILD_MODE%"=="send" set "CREATE_SEND_PACKAGE=1"

set "RELEASE_DIR=release\3cket2brella"
set "INTERNAL_DIR=%RELEASE_DIR%\_internal"
set "SEND_DIR=release\3cket2brella-send"
set "SEND_ZIP=release\3cket2brella-send.zip"

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

".venv\Scripts\python.exe" -m PyInstaller ^
    --clean ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name 3cket2brella-gui ^
    gui.py

if errorlevel 1 (
    echo [ERROR] GUI build failed.
    exit /b 1
)

if exist "%RELEASE_DIR%" (
    rmdir /s /q "%RELEASE_DIR%"
)

mkdir "%RELEASE_DIR%"
mkdir "%INTERNAL_DIR%"

move /Y "dist\3cket2brella-gui.exe" "%RELEASE_DIR%\3cket2brella-gui.exe" >nul
move /Y "dist\3cket2brella.exe" "%INTERNAL_DIR%\3cket2brella.exe" >nul

copy /Y "build_exe.bat" "%RELEASE_DIR%\build_exe.bat" >nul

if exist "participants.csv" (
    copy /Y "participants.csv" "%INTERNAL_DIR%\participants.csv" >nul
)

if exist ".env" (
    copy /Y ".env" "%INTERNAL_DIR%\.env" >nul
)

attrib +h "%INTERNAL_DIR%"

echo [OK] Clean package created:
echo       %RELEASE_DIR%\build_exe.bat
echo       %RELEASE_DIR%\3cket2brella-gui.exe
echo [INFO] Hidden internal files at:
echo       %INTERNAL_DIR%

if "%CREATE_SEND_PACKAGE%"=="1" (
    if exist "%SEND_DIR%" (
        rmdir /s /q "%SEND_DIR%"
    )

    mkdir "%SEND_DIR%"

    copy /Y "%RELEASE_DIR%\3cket2brella-gui.exe" "%SEND_DIR%\3cket2brella-gui.exe" >nul

    if exist "participants.csv" (
        copy /Y "participants.csv" "%SEND_DIR%\participants.csv" >nul
    ) else if exist "participants_tester.csv" (
        copy /Y "participants_tester.csv" "%SEND_DIR%\participants.csv" >nul
    )

    > "%SEND_DIR%\.env.template" (
        echo BRELLA_API_KEY=
        echo BRELLA_ORG_ID=1218
        echo BRELLA_EVENT_ID=10672
        echo BRELLA_REQUEST_DELAY=0.1
        echo BRELLA_EXTERNAL_QR_COLUMN=0
        echo BRELLA_AUTH_HEADER_NAME=Brella-API-Access-Token
        echo BRELLA_AUTH_HEADER_PREFIX=
        echo BRELLA_PREFLIGHT_URL=https://api.brella.io/api/integration/organizations/{org_id}/events/{event_id}
        echo BRELLA_INVITES_URL=https://api.brella.io/api/integration/organizations/{org_id}/events/{event_id}/invites
        echo BRELLA_FIND_INVITE_URL=https://api.brella.io/api/integration/organizations/{org_id}/events/{event_id}/invites/find/
        echo BRELLA_UPDATE_INVITE_URL=https://api.brella.io/api/integration/organizations/{org_id}/events/{event_id}/invites/{invite_id}
        echo BRELLA_HTTP_USER_AGENT=Mozilla/5.0 ^(Windows NT 10.0; Win64; x64^) AppleWebKit/537.36 ^(KHTML, like Gecko^) Chrome/133.0.0.0 Safari/537.36
        echo THREECKET_COOKIE=
    )

    if exist "%SEND_ZIP%" del /f /q "%SEND_ZIP%" >nul 2>nul

    powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%SEND_DIR%\*' -DestinationPath '%SEND_ZIP%' -Force"
    if errorlevel 1 (
        echo [WARN] Could not create zip automatically. Folder is ready at %SEND_DIR%
    ) else (
        echo [OK] Send package created:
        echo       %SEND_ZIP%
    )
)