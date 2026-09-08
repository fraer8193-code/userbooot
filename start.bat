@echo off
setlocal enabledelayedexpansion
title Telegram Modular Femboy

set "PY_EXE=python"

if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    goto :found_py
)

if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    goto :found_py
)

if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
    set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    goto :found_py
)

where python >nul 2>nul
if %errorlevel% equ 0 (
    set "PY_EXE=python"
    goto :found_py
)

echo [!] Python is not found. Please install Python 3.10+
pause
exit /b 1

:found_py
"%PY_EXE%" main.py
if %errorlevel% neq 0 (
    echo.
    echo Femboy stopped with an error or exited.
    pause
)
