@echo off
title PowerWize + ngrok
setlocal
set "PGBIN=C:\laragon\bin\postgresql\postgresql-18.4-1-windows-x64\bin"
set "PGDATA=C:\laragon\data\mysql-8.4-fresh\postgresql-18"
set "ROOT=%~dp0"

where ngrok >nul 2>nul
if %errorlevel%==0 (
  set "NGROK=ngrok"
) else (
  set "NGROK=C:\Users\McZeal\AppData\Local\Microsoft\WinGet\Packages\Ngrok.Ngrok_Microsoft.Winget.Source_8wekyb3d8bbwe\ngrok.exe"
)

echo ============================================
echo   Starting PowerWize (with ngrok tunnel)
echo ============================================
echo.

REM --- 1. PostgreSQL: start only if not already running ---
"%PGBIN%\pg_isready" -q
if errorlevel 1 (
  echo [database] starting PostgreSQL...
  if not exist "%PGDATA%\log" mkdir "%PGDATA%\log"
  "%PGBIN%\pg_ctl" -D "%PGDATA%" -l "%PGDATA%\log\server.log" -w start
  if errorlevel 1 (
    echo.
    echo [database] FAILED to start. See %PGDATA%\log\server.log
    echo.
    pause
    exit /b 1
  )
) else (
  echo [database] already running
)

REM --- 2. Free port 5000 from any leftover app run ---
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5000 " ^| findstr LISTENING') do (
  echo [app] stopping old instance ^(PID %%a^)
  taskkill /F /PID %%a >nul 2>&1
)

REM --- 3. Start Flask in its own window ---
echo [app] starting on http://127.0.0.1:5000
start "PowerWize App" cmd /k ""%ROOT%venv\Scripts\python.exe" "%ROOT%src\app.py""

REM --- 4. Give Flask a moment to bind the port, then open the ngrok tunnel in its own window ---
timeout /t 3 /nobreak >nul
echo [ngrok] starting tunnel to port 5000...
start "PowerWize ngrok" cmd /k ""%NGROK%" http 5000"

echo.
echo Both windows are launching:
echo   - "PowerWize App" runs the Flask server
echo   - "PowerWize ngrok" prints your public https:// URL
echo Or check http://127.0.0.1:4040 for the ngrok inspector.
echo.
pause
