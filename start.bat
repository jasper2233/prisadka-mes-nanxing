@echo off
chcp 65001 >nul
cd /d "%~dp0"
title PRISADKA MES

python start.py %*
if errorlevel 1 (
  echo.
  echo Xato yuz berdi. Python o'rnatilganini tekshiring:  python --version
  pause
)
