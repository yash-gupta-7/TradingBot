@echo off
title SENSEX Bot Launcher
echo.
echo  ============================================
echo   SENSEX Paper Trading Bot - Daily Launcher
echo  ============================================
echo.

:: Change to the bot directory
cd /d "C:\Users\Chetan\Desktop\tradingbot\shortTerm\TradingBot"

:: Activate virtualenv
call .venv\Scripts\activate.bat

echo [1/2] Starting Kite Login...
echo       Please complete the browser login when it opens.
echo.
python -m kite.login

if %errorlevel% neq 0 (
    echo ERROR: Kite login failed. Please check your API keys.
    pause
    exit /b 1
)

echo.
echo [2/2] Launching paper trading bot in background...
echo       Dashboard will be available at http://localhost:5050
echo.

:: Launch in a new detached window that stays alive even after this terminal is closed
start "SENSEX Bot" /MIN cmd /c "cd /d C:\Users\Chetan\Desktop\tradingbot\shortTerm\TradingBot && .venv\Scripts\activate.bat && python -m live.run_paper >> %USERPROFILE%\Desktop\bot_log.txt 2>&1"

:: Give it a moment to start
timeout /t 3 /nobreak > nul

echo  ============================================
echo   Bot is running in background window!
echo   Dashboard  : http://localhost:5050
echo   Log file   : %USERPROFILE%\Desktop\bot_log.txt
echo   Bot window : Minimised in taskbar (titled "SENSEX Bot")
echo  ============================================
echo.
echo   You can CLOSE THIS WINDOW safely.
echo   The bot will trade until 15:20 automatically.
echo   Do NOT close the "SENSEX Bot" window in the taskbar.
echo.
start http://localhost:5050
pause
