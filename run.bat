@echo off
cd /d "%~dp0"
where py >nul 2>nul && (powershell -NoProfile -Command "Start-Process pyw -ArgumentList 'app.pyw' -Verb RunAs" & exit /b)
echo ??? Python?????? GenshinLyre.exe
pause
