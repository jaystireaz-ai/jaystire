@echo off
echo ================================================
echo Jay's Tire Shop - Starting Servers
echo ================================================
echo.

echo Starting the database API server...
start "JTS-API" python "%~dp0database\api.py"

echo Waiting for API to start...
timeout /t 2 /nobreak > nul

echo Starting frontend file server on port 8080...
cd /d "%~dp0"
start "JTS-Frontend" cmd /c "python -m http.server 8080"

echo Waiting for file server to start...
timeout /t 2 /nobreak > nul

echo Opening Reports...
start "" "http://localhost:8080/reports.html"

echo.
echo ================================================
echo Servers are running:
echo   API:      http://localhost:5000
echo   Frontend: http://localhost:8080
echo Close this window or press Ctrl+C to stop.
echo ================================================
pause
