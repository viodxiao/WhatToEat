@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
where conda >nul 2>&1
if errorlevel 1 (
  echo Conda was not found. Run this script from Anaconda Prompt or Miniconda Prompt.
  pause
  exit /b 1
)
call conda run -n cook --no-capture-output python -s -X utf8 -m unittest scripts.test_planner scripts.test_nl_query scripts.test_revision -v
if errorlevel 1 goto failed
call conda run -n cook --no-capture-output python -s -X utf8 -m scripts.stage3_eval --check-gold

if errorlevel 1 goto failed
echo Done.
pause
exit /b 0
:failed
echo Failed. Please read the error above.
pause
exit /b 1
