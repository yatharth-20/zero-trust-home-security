@echo off
title Zero-Trust Smart Home Security & Child Safety System
color 0B
chcp 65001 >nul

cd /d "%~dp0"

:: Check parent .venv or local .venv
set "PYTHON_EXE=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
)
if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=python"
)

:MENU
cls
echo ===============================================================================
echo     AI-BASED ZERO-TRUST SMART HOME SECURITY ^& CHILD SAFETY SYSTEM
echo     Graphic Era Deemed to be University, Dehradun
echo     Authors: Humera Tahzeeb, Megha Saxena, Yatharth Verma
echo ===============================================================================
echo.
echo   [1] Launch Guardian Dashboard ^& Demo Mode (Recommended)
echo   [2] Launch Live Webcam Surveillance
echo   [3] Enroll New Resident Face
echo   [4] Run Performance Evaluation (600 Scenarios)
echo   [5] Run Unit Test Suite
echo   [6] Create Clean Submission ZIP
echo   [0] Exit
echo.
echo ===============================================================================
set /p choice="Select an option [0-6] and press Enter: "

if "%choice%"=="1" goto RUN_DEMO
if "%choice%"=="2" goto RUN_LIVE
if "%choice%"=="3" goto RUN_ENROLL
if "%choice%"=="4" goto RUN_EVAL
if "%choice%"=="5" goto RUN_TESTS
if "%choice%"=="6" goto RUN_PACKAGE
if "%choice%"=="0" exit /b 0

echo.
echo [!] Invalid selection. Please choose 0 to 6.
ping 127.0.0.1 -n 3 >nul
goto MENU

:RUN_DEMO
cls
echo [*] Starting Guardian Dashboard...
start "" cmd /c "ping 127.0.0.1 -n 4 >nul & start http://localhost:8765"
"%PYTHON_EXE%" main.py demo --auto --port 8765
pause
goto MENU

:RUN_LIVE
cls
echo [*] Starting Live Webcam Surveillance on Camera 0...
start "" cmd /c "ping 127.0.0.1 -n 4 >nul & start http://localhost:8765"
"%PYTHON_EXE%" main.py live --camera 0 --port 8765
pause
goto MENU

:RUN_ENROLL
cls
set /p rname="Enter Resident Name: "
if "%rname%"=="" set "rname=Authorized_Resident"
"%PYTHON_EXE%" main.py enroll --name "%rname%" --samples 20
pause
goto MENU

:RUN_EVAL
cls
"%PYTHON_EXE%" main.py eval --samples 600
pause
goto MENU

:RUN_TESTS
cls
"%PYTHON_EXE%" -m pytest tests/test_limitations_mitigation.py -v
pause
goto MENU

:RUN_PACKAGE
cls
"%PYTHON_EXE%" package_for_submission.py
pause
goto MENU
