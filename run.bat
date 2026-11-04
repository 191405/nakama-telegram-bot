@echo off
title Nakama Network Telegram Bot
echo ==============================================
echo       Nakama Network Telegram Bot
echo ==============================================
echo.

:loop
echo [%date% %time%] Starting bot...
.venv\Scripts\python.exe -m bot
echo.
echo [%date% %time%] Bot process ended or network disconnected!
echo Restarting automatically in 5 seconds... (Press Ctrl+C to stop)
timeout /t 5 /nobreak >nul
goto loop
