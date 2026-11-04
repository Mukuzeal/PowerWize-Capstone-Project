@echo off
title PowerWize + ngrok
setlocal
set "PGBIN=C:\laragon\bin\postgresql\postgresql-18.4-1-windows-x64\bin"
set "PGDATA=C:\laragon\data\mysql-8.4-fresh\postgresql-18"
set "ROOT=%~dp0"
set "LMSTUDIO_EXE=C:\Program Files\LM Studio\LM Studio.exe"
set "LMS=%USERPROFILE%\.lmstudio\bin\lms.exe"

where ngrok >nul 2>nul
if %errorlevel%==0 (
  set "NGROK=ngrok"
) else (
  set "NGROK=C:\Users\McZeal\AppData\Local\Microsoft\WinGet\Packages\Ngrok.Ngrok_Microsoft.Winget.Source_8wekyb3d8bbwe\ngrok.exe"
)

REM Model to preload, read from .env so this never drifts from what the app asks for.
set "LM_MODEL=qwen/qwen3-vl-4b"
for /f "usebackq tokens=1,* delims==" %%a in (`findstr /b /c:"LM_STUDIO_TEXT_MODEL=" "%ROOT%.env" 2^>nul`) do set "LM_MODEL=%%b"

echo ============================================
echo   Starting PowerWize (with ngrok tunnel)
echo ============================================
echo.

REM --- 0. Which optional services to start ---
REM Flags skip the prompt, so a shortcut or another script can stay non-interactive:
REM   PowerWize-Ngrok.bat -lmstudio -no-ngrok
set "WANT_LMS="
set "WANT_NGROK="
set "HAS_FLAGS=0"
:parse_args
if "%~1"=="" goto :args_done
set "HAS_FLAGS=1"
if /i "%~1"=="-lmstudio"    set "WANT_LMS=1"
if /i "%~1"=="-no-lmstudio" set "WANT_LMS=0"
if /i "%~1"=="-ngrok"       set "WANT_NGROK=1"
if /i "%~1"=="-no-ngrok"    set "WANT_NGROK=0"
shift
goto :parse_args
:args_done
if "%HAS_FLAGS%"=="1" goto :choice_defaults

echo What should start alongside PostgreSQL and the app?
echo   [1] LM Studio and ngrok   ^(default^)
echo   [2] LM Studio only        - local AI, no public URL
echo   [3] ngrok only            - public URL, AI calls go to Groq
echo   [4] neither
echo.
REM set /p, not choice - both read stdin, but an empty/redirected stdin
REM leaves PICK unset here and falls through to the default.
set "PICK="
set /p "PICK=Choice [1-4]: "
if "%PICK%"=="2" set "WANT_NGROK=0"
if "%PICK%"=="3" set "WANT_LMS=0"
if "%PICK%"=="4" set "WANT_LMS=0"
if "%PICK%"=="4" set "WANT_NGROK=0"
echo.
:choice_defaults
REM anything not turned off above runs
if not defined WANT_LMS set "WANT_LMS=1"
if not defined WANT_NGROK set "WANT_NGROK=1"

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

REM --- 2. LM Studio: the local server must be up before the app makes an AI call ---
if "%WANT_LMS%"=="0" echo [lmstudio] skipped - not starting it
if "%WANT_LMS%"=="0" goto :lms_done
netstat -aon | findstr ":1234 " | findstr LISTENING >nul
if not errorlevel 1 (
  echo [lmstudio] server already running
  goto :lms_done
)
if not exist "%LMSTUDIO_EXE%" (
  echo [lmstudio] NOT FOUND at %LMSTUDIO_EXE% - skipping ^(AI features will fail^)
  goto :lms_done
)
echo [lmstudio] starting LM Studio...
start "" /min "%LMSTUDIO_EXE%"

REM The server auto-starts with the app (autoStartOnLaunch), so just wait for port 1234.
REM ping, not timeout /t - timeout aborts when stdin is redirected (VS Code Code Runner).
set "LMS_TRIES=0"
:lms_wait
ping -n 3 127.0.0.1 >nul
netstat -aon | findstr ":1234 " | findstr LISTENING >nul
if not errorlevel 1 goto :lms_done
set /a LMS_TRIES+=1
if %LMS_TRIES% lss 45 goto :lms_wait
echo [lmstudio] WARNING: no server on port 1234 after 90s - AI features will fail
:lms_done

REM --- 3. Free port 5000 from any leftover app run ---
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5000 " ^| findstr LISTENING') do (
  echo [app] stopping old instance ^(PID %%a^)
  taskkill /F /PID %%a >nul 2>&1
)

REM --- 4. Start Flask in its own window ---
REM app.py warms the fastembed/ONNX embedder at import, and OpenBLAS sizes its
REM scratch buffers per thread - uncapped on 12 cores that allocation fails once
REM LM Studio has a model resident. Start Flask first, then preload the model.
set "OPENBLAS_NUM_THREADS=4"
echo [app] starting on http://127.0.0.1:5000
start "PowerWize App" cmd /k ""%ROOT%venv\Scripts\python.exe" "%ROOT%src\app.py""

REM --- 5. Wait for Flask to bind before anything else competes for memory ---
set "APP_TRIES=0"
:app_wait
ping -n 3 127.0.0.1 >nul
netstat -aon | findstr ":5000 " | findstr LISTENING >nul
if not errorlevel 1 goto :app_up
set /a APP_TRIES+=1
if %APP_TRIES% lss 30 goto :app_wait
echo [app] WARNING: not listening on port 5000 after 60s - see the app window
:app_up

REM --- 6. Preload the model now that the app has taken the memory it needs ---
if "%WANT_LMS%"=="0" goto :preload_done
if not exist "%LMS%" goto :preload_done
netstat -aon | findstr ":1234 " | findstr LISTENING >nul
if errorlevel 1 goto :preload_done
"%LMS%" ps 2>nul | findstr /i /c:"%LM_MODEL%" >nul
if not errorlevel 1 (
  echo [lmstudio] model %LM_MODEL% already loaded
  goto :preload_done
)
echo [lmstudio] loading model %LM_MODEL% ...
"%LMS%" load "%LM_MODEL%" -y
if errorlevel 1 echo [lmstudio] load failed - LM Studio will load it on first request instead
:preload_done

REM --- 7. Open the ngrok tunnel in its own window ---
if "%WANT_NGROK%"=="0" echo [ngrok] skipped - local only, no public URL
if "%WANT_NGROK%"=="0" goto :ngrok_done
echo [ngrok] starting tunnel to port 5000...
start "PowerWize ngrok" cmd /k ""%NGROK%" http 5000"
:ngrok_done

echo.
echo Launched:
echo   - "PowerWize App" runs the Flask server on http://127.0.0.1:5000
if "%WANT_NGROK%"=="1" echo   - "PowerWize ngrok" prints your public https:// URL
if "%WANT_NGROK%"=="1" echo     Or check http://127.0.0.1:4040 for the ngrok inspector.
echo.
pause
