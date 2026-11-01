@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -X utf8 -B tools\project.py ui
) else (
  python -X utf8 -B tools\project.py ui
)
if errorlevel 1 pause
