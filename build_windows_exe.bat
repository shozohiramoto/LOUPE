@echo off
REM Build from a Windows environment with the project's Python dependencies.
REM pip install pyinstaller (only required in build environment).
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean --onedir --windowed --name LOUPE --hidden-import PySide6.QtNetwork --icon assets\loupe.ico --add-data "assets\loupe.png;assets" --add-data "assets\loupe.ico;assets" --add-data "fiji;fiji" --add-data "bl09w_ui\theme.json;bl09w_ui" --add-data "bl09w_ui\qt_theme.qss;bl09w_ui" main.py
if errorlevel 1 (echo EXE build failed & exit /b 1)
echo Test dist\LOUPE\LOUPE.exe on a clean Windows machine.
