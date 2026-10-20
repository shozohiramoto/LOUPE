@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Drag rec00000.tif onto this BAT, or run:
  echo benchmark_orthogonal_preview.bat "D:\CT\rec\rec00000.tif"
  pause
  exit /b 1
)
py tools\benchmark_orthogonal_preview.py "%~1"
if errorlevel 1 pause
