@echo off
REM Лаунчер UPA для Windows: двойной клик или ярлык на рабочем столе.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
if errorlevel 1 pause
