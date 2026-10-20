@echo off
REM Compatibility shortcut: normal startup auto-prepares environment only if needed.
call "%~dp0run.bat"
exit /b %ERRORLEVEL%
