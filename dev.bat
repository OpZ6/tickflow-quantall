@echo off
rem tickflow-stock-panel - double-click launcher (Windows)
rem Wraps dev.ps1: starts backend (http://localhost:3018) + frontend (http://localhost:3011).
rem Close this window or press Ctrl+C to stop both services.

cd /d "%~dp0"
title tickflow-stock-panel dev

echo ============================================================
echo   tickflow-stock-panel  dev launcher
echo   frontend:  http://localhost:3011
echo   backend:   http://localhost:3018
echo   target:    http://localhost:3011/quantx/20260828
echo   stop:      Ctrl+C in this window
echo ============================================================
echo.

rem Wait for the frontend to be ready, then open the target page.
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 180;$i++){try{$t=New-Object Net.Sockets.TcpClient('127.0.0.1',3011);$t.Close();Start-Process 'http://localhost:3011/quantx/20260828';break}catch{Start-Sleep -Milliseconds 500}}"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev.ps1"

echo.
echo Services stopped. Press any key to close.
pause >nul
