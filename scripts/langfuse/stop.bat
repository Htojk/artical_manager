@echo off
setlocal
cd /d "%~dp0"

set "COMPOSE=docker compose"
docker compose version >nul 2>&1
if errorlevel 1 (
  where docker-compose >nul 2>&1
  if errorlevel 1 (
    echo [langfuse] Neither "docker compose" nor "docker-compose" is available.
    exit /b 1
  )
  set "COMPOSE=docker-compose"
)

echo [langfuse] stopping Langfuse with "%COMPOSE%" ...
%COMPOSE% down
if errorlevel 1 (
  echo [langfuse] stop failed.
  exit /b 1
)
echo [langfuse] stopped. Named volumes are preserved.
echo [langfuse] To delete all trace data: %COMPOSE% down -v
endlocal
