@echo off
cd /d "%~dp0"
where python >nul 2>nul && (python -m myflownet %*) || (py -3 -m myflownet %*)
if errorlevel 1 pause
