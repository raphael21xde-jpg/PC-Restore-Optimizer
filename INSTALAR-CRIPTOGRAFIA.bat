@echo off
cd /d "%~dp0"
where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
  py -3 -m pip install cryptography
) else (
  python -m pip install cryptography
)
pause
