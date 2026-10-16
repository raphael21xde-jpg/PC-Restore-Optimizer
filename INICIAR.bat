@echo off
cd /d "%~dp0"
where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
  py -3 app.py
) else (
  python app.py
)
if ERRORLEVEL 1 pause
