@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m generador_rfd gui
) else (
  where py >nul 2>nul
  if errorlevel 1 (
    python -m generador_rfd gui
  ) else (
    py -3 -m generador_rfd gui
  )
)
if errorlevel 1 pause
