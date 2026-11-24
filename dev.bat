@echo off
setlocal
rem tickflow-stock-panel - double-click launcher (Windows)
rem Wraps dev.ps1: backend :3018 + frontend :3011, then opens QuantX.
rem
rem Usage:
rem   dev.bat                      reuse healthy services, open default date
rem   dev.bat 20261104             open a specific trade date
rem   dev.bat -Force               stop existing instances and take ownership
rem   dev.bat 20261104 -Force      both

cd /d "%~dp0"
title tickflow-stock-panel dev

rem dev.ps1 writes UTF-8; cmd defaults to codepage 936 and garbles Chinese logs.
chcp 65001 >nul 2>&1

set "TRADE_DATE=20260828"
set "FORCE_ARG="
:parse
if "%~1"=="" goto parsed
if /i "%~1"=="-Force" (set "FORCE_ARG=-Force") else (set "TRADE_DATE=%~1")
shift
goto parse
:parsed

rem QuantX dates are passed as ?date=YYYYMMDD; /quantx/:date is a legacy path.
set "TARGET_URL=http://localhost:3011/quantx?date=%TRADE_DATE%"

echo ============================================================
echo   tickflow-stock-panel  dev launcher
echo   frontend:  http://localhost:3011
echo   backend:   http://localhost:3018
echo   target:    %TARGET_URL%
echo   stop:      Ctrl+C in this window
echo ============================================================
echo(

rem ---------- reuse path ----------
rem If both ports already answer, do NOT start a second stack. dev.ps1 would
rem refuse anyway (single-instance guard) and exit 1, leaving this window with
rem a misleading "Services stopped" line.
if defined FORCE_ARG goto launch
echo [dev] Checking existing services ...
powershell -NoProfile -Command "try{$r=[Net.HttpWebRequest]::Create('http://127.0.0.1:3011/');$r.Timeout=3000;$r.KeepAlive=$false;$x=$r.GetResponse();$ok1=([int]$x.StatusCode -eq 200);$x.Close();$r2=[Net.HttpWebRequest]::Create('http://127.0.0.1:3018/api/health');$r2.Timeout=3000;$r2.KeepAlive=$false;$x2=$r2.GetResponse();$ok2=([int]$x2.StatusCode -eq 200);$x2.Close();if($ok1 -and $ok2){exit 0}}catch{};exit 1"
if not errorlevel 1 goto reuse

rem ---------- launch path ----------
:launch
echo [dev] Starting backend + frontend (this window owns them) ...
rem Open the target only once the frontend actually answers.
if not defined DEV_NO_OPEN start "" /b powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 180;$i++){try{$r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:3011/' -TimeoutSec 2;if($r.StatusCode -eq 200){Start-Process '%TARGET_URL%';break}}catch{};Start-Sleep -Milliseconds 500}"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev.ps1" %FORCE_ARG%
set "DEV_RC=%ERRORLEVEL%"
echo(
if "%DEV_RC%"=="0" (
  echo [dev] Services stopped. Press any key to close.
) else (
  echo [dev] dev.ps1 exited with code %DEV_RC%.
  echo [dev] If it reports an existing instance, run:  dev.bat -Force
  echo [dev] Press any key to close.
)
if not defined DEV_NO_PAUSE pause >nul
exit /b %DEV_RC%

:reuse
echo [dev] Both services are already healthy (3011 + 3018).
echo [dev] Skipping a second start, opening %TARGET_URL%
if not defined DEV_NO_OPEN start "" "%TARGET_URL%"
echo(
echo [dev] NOTE: these processes were started outside this launcher,
echo [dev] so Ctrl+C here will NOT stop them.
echo [dev] To restart under this window's control, run:  dev.bat -Force
echo [dev] Press any key to close.
if not defined DEV_NO_PAUSE pause >nul
exit /b 0
