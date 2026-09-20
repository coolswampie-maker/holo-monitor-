@echo off
rem Run HOLOCYT from source without building a standalone application.
rem Diagnostic value: if source works but the built application does not,
rem the problem is in packaging, not in the program itself.
chcp 65001 > nul
cd /d "%~dp0\.."
set PYTHONUTF8=1
set PYTHONDONTWRITEBYTECODE=1
title HOLOCYT - from source

set PY=
where py >nul 2>&1 && set PY=py -3.11
if "%PY%"=="" ( where python >nul 2>&1 && set PY=python )
if "%PY%"=="" (
  echo.
  echo   [!] Python not found. Install Python 3.11 x64 from python.org.
  echo.
  pause & exit /b 1
)

if not exist ".venv-run" (
  echo Creating environment .venv-run - happens once, takes a few minutes...
  %PY% -m venv .venv-run || ( pause & exit /b 1 )
  .venv-run\Scripts\python.exe -m pip install --quiet --upgrade pip
  .venv-run\Scripts\python.exe -m pip install -r requirements\requirements-lock.txt || ( pause & exit /b 1 )
)

set APP=app
if not exist "app\run.py" set APP=.
.venv-run\Scripts\python.exe "%APP%\run.py"
if errorlevel 1 pause
