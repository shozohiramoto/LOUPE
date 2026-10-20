@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0loupe_launcher.ps1" (
  echo [ERROR] Missing loupe_launcher.ps1. Extract the complete ZIP first.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0loupe_launcher.ps1" -Mode run
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%
