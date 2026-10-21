@echo off
rem Validacao automatica no Windows (Agendador de Tarefas). Usuario NORMAL, sem "privilegios mais altos".
rem So atualiza a main desta pasta e roda scripts\validar_windows.py. Nao apaga nada.
setlocal
cd /d "%~dp0.."
set LOG=%LOCALAPPDATA%\pcro-validacao.log
echo.>>"%LOG%"
echo ===== %DATE% %TIME% =====>>"%LOG%"
git status --porcelain --untracked-files=no > "%TEMP%\pcro-status.txt"
for %%A in ("%TEMP%\pcro-status.txt") do if %%~zA GTR 0 (
  echo Alteracoes locais no repositorio de validacao; nada foi feito.>>"%LOG%"
  exit /b 1
)
git fetch origin --prune >>"%LOG%" 2>&1 || exit /b 1
git switch main >>"%LOG%" 2>&1 || exit /b 1
git pull --ff-only >>"%LOG%" 2>&1 || exit /b 1
py -3 scripts\validar_windows.py >>"%LOG%" 2>&1
exit /b %ERRORLEVEL%
