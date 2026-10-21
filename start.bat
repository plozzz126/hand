@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3.12 -c "pass" >nul 2>nul
    if not errorlevel 1 (
        py -3.12 run.py %*
    ) else (
        py -3 run.py %*
    )
) else (
    python run.py %*
)
set "result=%errorlevel%"
if not "%result%"=="0" (
    echo.
    echo Launch failed. Install 64-bit Python 3.12 and check README.md.
    pause
)
exit /b %result%
