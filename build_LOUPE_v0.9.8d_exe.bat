@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM Place this BAT beside main.py in the extracted LOUPE v0.9.8d folder.
if not exist "main.py" (
  echo [ERROR] main.py not found. Copy this BAT into the extracted loupe_work folder.
  pause
  exit /b 1
)
if not exist "requirements.txt" (
  echo [ERROR] requirements.txt not found.
  pause
  exit /b 1
)
if not exist "assets\loupe.ico" (
  echo [ERROR] assets\loupe.ico not found.
  pause
  exit /b 1
)

set "VENV=%CD%\.venv_build"
if not exist "%VENV%\Scripts\python.exe" (
  echo [1/3] Creating reusable EXE build environment...
  where py >nul 2>&1
  if not errorlevel 1 (
    py -3 -m venv "%VENV%"
  ) else (
    python -m venv "%VENV%"
  )
  if errorlevel 1 goto :fail
)
set "PY=%VENV%\Scripts\python.exe"
"%PY%" -c "import PyInstaller, PySide6, pyqtgraph, numpy, tifffile" >nul 2>&1
if errorlevel 1 (
  echo [2/3] Installing dependencies once...
  "%PY%" -m pip install -r requirements.txt pyinstaller
  if errorlevel 1 goto :fail
) else (
  echo [2/3] Reusing installed dependencies.
)

echo [3/3] Building LOUPE.exe (Windows, onedir)...
"%PY%" -m PyInstaller --noconfirm --clean --onedir --windowed --name LOUPE --hidden-import PySide6.QtNetwork --icon "assets\loupe.ico" --add-data "assets\loupe.png;assets" --add-data "assets\loupe.ico;assets" --add-data "fiji;fiji" --add-data "tools\java;tools\java" --add-data "bl09w_ui\theme.json;bl09w_ui" --add-data "bl09w_ui\qt_theme.qss;bl09w_ui" main.py
if errorlevel 1 goto :fail
if not exist "dist\LOUPE\LOUPE.exe" goto :fail

echo.
echo [SUCCESS] dist\LOUPE\LOUPE.exe
 echo Distribute the WHOLE dist\LOUPE folder, not only the EXE.
echo IMPORTANT: Verify GUI, Native Section and pixel calibration on Windows.
pause
exit /b 0

:fail
echo.
echo [ERROR] Build failed. Check the messages above.
pause
exit /b 1
