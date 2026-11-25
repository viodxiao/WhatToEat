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
echo Open http://127.0.0.1:8000/ after startup. Press Ctrl+C to stop.
call conda run -n cook --no-capture-output python -s -X utf8 -m uvicorn scripts.main:app --host 127.0.0.1 --port 8000

if errorlevel 1 goto failed
echo Done.
pause
exit /b 0
:failed
echo Failed. Please read the error above.
pause
exit /b 1
