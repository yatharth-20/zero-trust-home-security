@echo off
title Zero-Trust Smart Home Security & Child Safety System
color 0B
chcp 65001 >nul

:: Navigate to script directory
cd /d "%~dp0"

:: Detect Python from .venv or system
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=python"
)

:MENU
cls
echo ===============================================================================
echo     AI-BASED ZERO-TRUST SMART HOME SECURITY ^& CHILD SAFETY SYSTEM
echo     Graphic Era Deemed to be University, Dehradun
echo     Authors: Humera Tahzeeb, Megha Saxena, Yatharth Verma
echo     Guide: Dr. Neha Tripathi
echo ===============================================================================
echo.
echo   [1] Launch Guardian Dashboard ^& Demo Mode (Recommended)
echo       - Auto-opens web browser (http://localhost:8765)
echo       - Shows live biometric camera feed, face landmarks, and scenarios
echo.
echo   [2] Launch Live Webcam Security Monitoring
echo       - Connects to your real USB/PC webcam
echo       - Real-time face detection, liveness check, and alarm monitoring
echo.
echo   [3] Enroll New Resident Face
echo       - Captures facial embeddings using camera for authorized residents
echo.
echo   [4] Run Performance Evaluation (600 Scenarios)
echo       - Evaluates accuracy, precision, latency, and false alarm rate
echo.
echo   [5] Run Unit Test Suite (6 Mitigations)
echo       - Verifies all 6 architectural limitation fixes
echo.
echo   [6] Generate Clean Submission Archive (ZIP)
echo       - Creates submission package with 0%% .venv plagiarism footprint
echo.
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
if "%choice%"=="0" goto EXIT_SCRIPT

echo.
echo [!] Invalid selection. Please choose 0 to 6.
ping 127.0.0.1 -n 3 >nul
goto MENU

:RUN_DEMO
cls
echo ===============================================================================
echo   Starting Guardian Dashboard ^& Interactive Simulation...
echo ===============================================================================
echo.
echo [*] Server starting on http://localhost:8765
echo [*] Opening your default web browser in 3 seconds...
echo.
start "" cmd /c "ping 127.0.0.1 -n 4 >nul & start http://localhost:8765"
cd /d "%~dp0zero-trust-home-security"
"%PYTHON_EXE%" main.py demo --auto --port 8765
echo.
pause
goto MENU

:RUN_LIVE
cls
echo ===============================================================================
echo   Starting Live Webcam Surveillance...
echo ===============================================================================
echo.
echo [*] Starting webcam feed on index 0...
echo [*] Web dashboard also accessible at http://localhost:8765
echo [*] Press 'q' in camera window or Ctrl+C in terminal to stop.
echo.
start "" cmd /c "ping 127.0.0.1 -n 4 >nul & start http://localhost:8765"
cd /d "%~dp0zero-trust-home-security"
"%PYTHON_EXE%" main.py live --camera 0 --port 8765
echo.
pause
goto MENU

:RUN_ENROLL
cls
echo ===============================================================================
echo   Enroll Authorized Resident Face
echo ===============================================================================
echo.
set /p rname="Enter Resident Name (e.g., Yatharth, Humera, Parent): "
if "%rname%"=="" set "rname=Authorized_Resident"
echo [*] Enrolling face for: %rname%
echo [*] Look at the webcam while it captures biometric embeddings...
cd /d "%~dp0zero-trust-home-security"
"%PYTHON_EXE%" main.py enroll --name "%rname%" --samples 20
echo.
pause
goto MENU

:RUN_EVAL
cls
echo ===============================================================================
echo   Running Scenario Benchmark Evaluation...
echo ===============================================================================
echo.
cd /d "%~dp0zero-trust-home-security"
"%PYTHON_EXE%" main.py eval --samples 600
echo.
echo [*] Results updated in results/evaluation.md and results/per_scenario.csv
echo.
pause
goto MENU

:RUN_TESTS
cls
echo ===============================================================================
echo   Running Automated Test Suite (6 Limitations Mitigation)...
echo ===============================================================================
echo.
cd /d "%~dp0zero-trust-home-security"
"%PYTHON_EXE%" -m pytest tests/test_limitations_mitigation.py -v
echo.
pause
goto MENU

:RUN_PACKAGE
cls
echo ===============================================================================
echo   Generating Submission Archive (ZIP)...
echo ===============================================================================
echo.
cd /d "%~dp0zero-trust-home-security"
"%PYTHON_EXE%" package_for_submission.py
echo.
pause
goto MENU

:EXIT_SCRIPT
cls
echo.
echo Exiting Zero-Trust Security System. Have a great day!
ping 127.0.0.1 -n 2 >nul
exit /b 0
