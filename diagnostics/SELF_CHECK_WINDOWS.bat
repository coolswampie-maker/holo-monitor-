@echo off
rem HOLOCYT self-check. Works both on the built application and from source.
chcp 65001 > nul
cd /d "%~dp0\.."
set PYTHONUTF8=1
title HOLOCYT - self check

set PY=
if exist ".venv-build\Scripts\python.exe" set PY=.venv-build\Scripts\python.exe
if "%PY%"=="" if exist ".venv-run\Scripts\python.exe" set PY=.venv-run\Scripts\python.exe
if "%PY%"=="" ( where py >nul 2>&1 && set PY=py -3.11 )
if "%PY%"=="" ( where python >nul 2>&1 && set PY=python )
if "%PY%"=="" (
  echo.
  echo   [!] Python not found and no build environment present.
  echo       Run BUILD_WINDOWS.bat or RUN_WINDOWS_SOURCE.bat first.
  echo.
  pause & exit /b 1
)

%PY% diagnostics\self_check.py
set RC=%ERRORLEVEL%
echo.
if exist "dist" (
  echo Built application folder found in: dist
  echo Start the application from there and check it opens in a browser.
  echo.
)
pause
exit /b %RC%
