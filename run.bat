@echo off
setlocal

if not "%~1"=="" (
  echo Error: this script does not accept command-line arguments. Run it as: run.bat 1>&2
  exit /b 2
)

cd /d "%~dp0"

set "python_cmd=python"
where py >nul 2>nul
if %errorlevel%==0 (
  set "python_cmd=py -3"
)

call %python_cmd% -m rpchelper.main
