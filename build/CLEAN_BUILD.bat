@echo off
chcp 65001 > nul
cd /d "%~dp0\.."
echo Removing build artifacts...
if exist "build\build" rmdir /s /q "build\build"
if exist "dist" rmdir /s /q "dist"
echo.
echo Remove build environments as well? [y/N]
set /p ANS=
if /i "%ANS%"=="y" (
  if exist ".venv-build" rmdir /s /q ".venv-build"
  if exist ".venv-run" rmdir /s /q ".venv-run"
)
echo Done.
pause
