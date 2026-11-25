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
call conda run -n cook python -s -c "import sys" >nul 2>&1
if errorlevel 1 (
  call conda create -n cook python=3.13.18 pip -y
  if errorlevel 1 goto failed
)
call conda run -n cook python -s -c "import sys; print(sys.version); sys.exit(0 if sys.version_info[:2] == (3, 13) else 1)"
if errorlevel 1 (
  echo The existing cook environment must use Python 3.13. It has not been changed.
  goto failed
)
call conda run -n cook python -s -m pip install -r requirements-dev.txt
if errorlevel 1 goto failed
call conda run -n cook python -s -m pip check

if errorlevel 1 goto failed
echo Done.
pause
exit /b 0
:failed
echo Failed. Please read the error above.
pause
exit /b 1
