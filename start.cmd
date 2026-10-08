@echo off
if not exist "%~dp0.venvs\app\Scripts\python.exe" (
  echo Application environment missing. See RUNTIME.md.
  pause
  exit /b 1
)
"%~dp0.venvs\app\Scripts\python.exe" -u -X utf8 "%~dp0backend\launch.py" %*
if errorlevel 1 pause
