@echo off
title GeoForge 3D Viewer
color 0B

echo.
echo  ============================================
echo   GeoForge 3D Viewer
echo   Starting server...
echo  ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found.
    pause & exit /b 1
)

pip install flask pyyaml -q 2>nul

echo  Opening browser at http://localhost:5000
echo  (close this window to stop the server)
echo.

start /b cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:5000"
python server.py

pause
