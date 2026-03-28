@echo off
setlocal

if not "%~1"=="" (
  echo Error: this script does not accept command-line arguments. Run it as: run.bat 1>&2
  exit /b 2
)

cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
  call ".venv\Scripts\activate.bat"
)

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m rpchelper.main
) else (
  python -m rpchelper.main
)
