@echo off
cd /d "%~dp0"
where py >nul 2>nul && (start "" pyw app.pyw & exit /b)
where pythonw >nul 2>nul && (start "" pythonw app.pyw & exit /b)
echo ??? Python?????? GenshinLyre.exe
pause
