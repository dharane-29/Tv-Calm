@echo off
setlocal
cd /d "%~dp0"
title TV Calm

rem Opens the step-by-step menu. Double-click this file.
rem Any arguments you pass are handed to tvcalm.py, for example: TV-Calm.bat scan 192.168.1.23

py -3 -c "import sys" >nul 2>nul
if %errorlevel%==0 (
    py -3 tvcalm.py %*
    goto :finish
)
python -c "import sys" >nul 2>nul
if %errorlevel%==0 (
    python tvcalm.py %*
    goto :finish
)
echo Python was not found on this computer.
echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".

:finish
echo.
pause
