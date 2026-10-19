@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONDONTWRITEBYTECODE=1"
py -3.12 "%~dp0run.py" stop %*
set "CF_EXIT=%errorlevel%"
if not "%CF_EXIT%"=="0" pause
exit /b %CF_EXIT%
