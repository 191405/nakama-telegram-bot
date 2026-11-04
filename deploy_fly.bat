@echo off
setlocal enabledelayedexpansion
title Deploy to Fly.io - Nakama Network
echo ======================================================
echo       Deploy Nakama Network Bot to Fly.io (24/7)
echo ======================================================
echo.

set PATH=%USERPROFILE%\.fly\bin;%PATH%

echo [1/5] Checking Fly.io CLI...
flyctl version
if %errorlevel% neq 0 (
    echo Fly CLI not detected in PATH.
    pause
    exit /b 1
)

echo.
echo [2/5] Checking Fly.io authentication...
flyctl auth whoami
if %errorlevel% neq 0 (
    echo Opening browser for quick login/signup...
    flyctl auth login
)

echo.
echo [3/5] Setting up persistent storage volume...
flyctl volumes create nakama_data --region iad --size 1 --yes 2>nul || echo Volume already exists or created.

echo.
echo [4/5] Setting secure production secrets...
echo Please ensure your secrets are configured using:
echo   flyctl secrets set BOT_TOKEN="your_token" ADMIN_IDS="your_admin_id"
echo.

echo.
echo [5/5] Deploying bot to Fly.io cloud servers...
flyctl deploy

echo.
echo ======================================================
echo Bot successfully deployed! Streaming live logs...
echo (Press Ctrl+C to stop streaming logs anytime)
echo ======================================================
flyctl logs
