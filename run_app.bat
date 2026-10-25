@echo off
title HP DeskJet 2130 - Device Assistant
echo Starting HP DeskJet 2130 Device Assistant & Spooler Manager...
python "%~dp0app.py"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with error code %ERRORLEVEL%.
    pause
)
