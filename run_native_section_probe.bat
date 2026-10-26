@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Drag a recNNNNN.tif file or the CT TIFF folder onto this BAT.
  echo Alternatively run: run_native_section_probe.bat "D:\CT\rec00001.tif"
  pause
  exit /b 1
)
set "PY=%LOCALAPPDATA%\LOUPE\shared-venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%~dp0.venv_build\Scripts\python.exe"
if exist "%PY%" goto run
where py >nul 2>&1
if errorlevel 1 (
  echo Python environment not found. Install dependencies before running.
  pause
  exit /b 1
)
set "PY=py"
:run
if "%PY%"=="py" (
  py -3 -u "tools\diagnose_native_section_crash.py" "%~1" %2
) else (
  "%PY%" -u "tools\diagnose_native_section_crash.py" "%~1" %2
)
set "EXITCODE=%ERRORLEVEL%"
echo.
if not "%EXITCODE%"=="0" echo Diagnostic did not complete successfully; check the result folder in TEMP.
echo Look for LOUPE_native_probe_* in %%TEMP%% and share probe_summary.json and probe_progress.jsonl only.
pause
exit /b %EXITCODE%
