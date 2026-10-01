@echo off
setlocal
title Northstar AI - App and ngrok
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
set "START_EXIT_CODE=%ERRORLEVEL%"
endlocal & exit /b %START_EXIT_CODE%
