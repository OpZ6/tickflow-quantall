@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\update_all.ps1" %*
set "UPDATE_EXIT_CODE=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %UPDATE_EXIT_CODE%
