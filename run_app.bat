@echo off
rem Double-click to start the AEGIS control centre. Pass --install to install requirements first.
setlocal
cd /d "%~dp0"
set "PY="
rem Find the full path of python.exe on PATH (quoted bare names are not searched on PATH).
for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
if not defined PY if exist "%LOCALAPPDATA%\Python\bin\python.exe" set "PY=%LOCALAPPDATA%\Python\bin\python.exe"
if not defined PY (
    echo Python was not found. Install Python 3 from python.org or add it to PATH.
    pause
    exit /b 1
)
"%PY%" run_app.py %*
if errorlevel 1 pause
