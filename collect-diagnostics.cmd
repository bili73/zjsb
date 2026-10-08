@echo off
if exist "%~dp0.venvs\app\Scripts\python.exe" (
  "%~dp0.venvs\app\Scripts\python.exe" -B -X utf8 "%~dp0scripts\collect_diagnostics.py" %*
) else (
  if exist "%~dp0.venvs\paddleocr-vl\Scripts\python.exe" (
    "%~dp0.venvs\paddleocr-vl\Scripts\python.exe" -B -X utf8 "%~dp0scripts\collect_diagnostics.py" %*
  ) else (
    py -3 -B -X utf8 "%~dp0scripts\collect_diagnostics.py" %*
  )
)
if errorlevel 1 pause
