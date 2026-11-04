@echo off
setlocal
cd /d "%~dp0"

if not exist ".env" (
  echo [langfuse] .env not found.
  echo [langfuse] Copy .env.example to .env, fill in the secrets, then run this again:
  echo              copy .env.example .env
  exit /b 1
)

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

echo [langfuse] starting Langfuse with "%COMPOSE%" ...
%COMPOSE% up -d
if errorlevel 1 (
  echo [langfuse] start failed. Make sure Docker Desktop is running.
  exit /b 1
)

echo [langfuse] waiting for the web container to become healthy ...
powershell -NoProfile -Command "$name='article-manager-langfuse-web'; for ($i=0; $i -lt 90; $i++) { $s=(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $name 2>$null); if ($s -eq 'healthy' -or $s -eq 'running') { exit 0 }; Start-Sleep -Seconds 2 }; exit 1"
if errorlevel 1 (
  echo [langfuse] web is not healthy yet. Inspect with: %COMPOSE% ps
  exit /b 1
)

set "PORT=3000"
for /f "tokens=1,* delims==" %%A in ('findstr /b "LANGFUSE_WEB_PORT=" .env') do set "PORT=%%B"
echo [langfuse] ready: http://localhost:%PORT%
echo [langfuse] Project keys: LANGFUSE_INIT_PROJECT_PUBLIC_KEY / LANGFUSE_INIT_PROJECT_SECRET_KEY in .env
echo [langfuse] Configure the backend with APP_LANGFUSE_ENABLED=true and the same keys.
endlocal
