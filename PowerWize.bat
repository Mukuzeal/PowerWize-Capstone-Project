@echo off
title PowerWize
setlocal
set "PGBIN=%USERPROFILE%\scoop\apps\postgresql\current\bin"
set "PGDATA=%USERPROFILE%\scoop\apps\postgresql\current\data"
set "ROOT=%~dp0"

echo ============================================
echo   Starting PowerWize
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

REM --- 3. Run the app in THIS window; open the browser (refresh once if it loads early) ---
echo [app] starting on http://127.0.0.1:5000
start "" http://127.0.0.1:5000
cd /d "%ROOT%src"
"%ROOT%.venv\Scripts\python.exe" app.py

echo.
echo PowerWize stopped.
pause
