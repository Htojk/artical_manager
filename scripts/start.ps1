# Start backend + frontend, wait for health, open the browser and stream logs.
param([switch]$NoBrowser, [switch]$NoPause)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$LogDir = Join-Path $Root "logs"
$BackendPort = if ($env:APP_PORT) { [int]$env:APP_PORT } else { 8000 }
$FrontendPort = if ($env:APP_FRONTEND_PORT) { [int]$env:APP_FRONTEND_PORT } else { 5173 }

if (-not (Test-Path $Python)) {
    throw "未找到 .venv，请先运行 scripts\setup.ps1。"
}
if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
    throw "未安装前端依赖，请先运行 scripts\setup.ps1。"
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Test-PortInUse([int]$Port) {
    try {
        $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
        return $null -ne $connection
    } catch {
        $client = New-Object System.Net.Sockets.TcpClient
        try {
            $client.Connect("127.0.0.1", $Port)
            return $true
        } catch {
            return $false
        } finally {
            $client.Dispose()
        }
    }
}

foreach ($pair in @(@{ Port = $BackendPort; Name = "后端" }, @{ Port = $FrontendPort; Name = "前端" })) {
    if (Test-PortInUse $pair.Port) {
        throw "$($pair.Name)端口 $($pair.Port) 已被占用，请先停止占用进程或修改 .env 中的端口。"
    }
}

$backendOut = Join-Path $LogDir "backend.out.log"
$backendErr = Join-Path $LogDir "backend.err.log"
$frontendOut = Join-Path $LogDir "frontend.out.log"
$frontendErr = Join-Path $LogDir "frontend.err.log"

Write-Host "启动后端 http://127.0.0.1:$BackendPort ..." -ForegroundColor Cyan
$backend = Start-Process -FilePath $Python `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$BackendPort") `
    -WorkingDirectory $Backend `
    -RedirectStandardOutput $backendOut `
    -RedirectStandardError $backendErr `
    -PassThru

Write-Host "启动前端 http://127.0.0.1:$FrontendPort ..." -ForegroundColor Cyan
$frontend = Start-Process -FilePath "npm.cmd" `
    -ArgumentList @("run", "dev", "--", "--port", "$FrontendPort", "--strictPort") `
    -WorkingDirectory $Frontend `
    -RedirectStandardOutput $frontendOut `
    -RedirectStandardError $frontendErr `
    -PassThru

try {
    $healthy = $false
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$BackendPort/api/health" -TimeoutSec 2
            if ($response.StatusCode -eq 200) { $healthy = $true; break }
        } catch { }
    }
    if (-not $healthy) {
        throw "后端健康检查超时，请查看 $backendErr"
    }
    if ($NoBrowser) {
        Write-Host "服务已就绪。日志目录：$LogDir" -ForegroundColor Green
    } else {
        Write-Host "服务已就绪，打开浏览器。日志目录：$LogDir" -ForegroundColor Green
        Start-Process "http://127.0.0.1:$FrontendPort"
    }
    if (-not $NoPause) {
        Write-Host "按 Enter 停止前后端..." -ForegroundColor Yellow
        [void](Read-Host)
    }
} finally {
    # Kill the whole process tree: npm.cmd spawns a separate node.exe that
    # would otherwise keep the frontend port open after the launcher exits.
    foreach ($process in @($frontend, $backend)) {
        if ($process -and -not $process.HasExited) {
            & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null
        }
    }
}
