@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul
cd /d "%~dp0\.."
set PYTHONUTF8=1
set ROOT=%CD%

echo.
echo ============================================================
echo   HOLOCYT - build standalone application for Windows
echo ============================================================
echo.

echo [1/10] Checking Python 3.11 x64...
set PY=
where py >nul 2>&1 && set PY=py -3.11
if "%PY%"=="" ( where python >nul 2>&1 && set PY=python )
if "%PY%"=="" goto :nopython
%PY% -c "import sys;sys.exit(0 if sys.version_info[:2]==(3,11) else 1)" >nul 2>&1
if errorlevel 1 goto :wrongpython
echo        OK

echo [2/10] Creating build environment .venv-build...
if not exist ".venv-build" ( %PY% -m venv .venv-build || goto :fail )
set VPY=%ROOT%\.venv-build\Scripts\python.exe
"%VPY%" -m pip install --quiet --upgrade pip || goto :fail

echo [3/10] Installing runtime dependencies (pinned versions)...
"%VPY%" -m pip install --quiet -r requirements\requirements-lock.txt || goto :fail

echo [4/10] Installing build dependencies (PyInstaller)...
"%VPY%" -m pip install --quiet -r requirements\requirements-build.txt || goto :fail

echo [5/10] Cleaning previous build...
if exist "build\build" rmdir /s /q "build\build"
if exist "dist" rmdir /s /q "dist"

echo [6/10] Checking the program imports from source...
set APP=%ROOT%\app
if not exist "%APP%\run.py" set APP=%ROOT%
"%VPY%" -c "import sys;sys.path.insert(0,r'%APP%');import holocyt.webui,holocyt.report,holocyt.export;print('        OK')" || goto :fail

echo [7/10] Running PyInstaller (several minutes)...
"%VPY%" -m PyInstaller --noconfirm --clean --distpath "%ROOT%\dist" --workpath "%ROOT%\build\build" "%ROOT%\build\holocyt.spec" || goto :fail

echo [8/10] Finalizing (Russian application name, docs)...
"%VPY%" "%ROOT%\build\finalize.py" || goto :fail

echo [9/10] Smoke test of the built application...
"%VPY%" "%ROOT%\build\smoke_built.py" || goto :fail

echo [10/10] Done.
echo.
echo ============================================================
echo   BUILD SUCCESSFUL
echo.
echo   Result : %ROOT%\dist
echo   Verify : diagnostics\SELF_CHECK_WINDOWS.bat
echo ============================================================
echo.
pause
exit /b 0

:nopython
echo.
echo   [!] Python was not found on this computer.
echo       Install Python 3.11 x64 from
echo       https://www.python.org/downloads/release/python-3119/
echo       During setup tick "Add python.exe to PATH".
echo.
goto :fail

:wrongpython
echo.
echo   [!] Python 3.11 x64 is required; a different version was found.
echo       Install 3.11 alongside - the "py -3.11" launcher will pick it.
echo.
:fail
echo.
echo   Build failed. Nothing was installed into the system.
echo   You can still run from source: RUN_WINDOWS_SOURCE.bat
echo   Log: logs\holocyt.log
echo.
pause
exit /b 1
