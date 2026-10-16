@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_windows.ps1"
if errorlevel 1 echo Installation failed. See the message above and RELEASE.md.
pause
