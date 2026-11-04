# One-time local setup: Python venv, backend deps, database migration and seed.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "未找到 $Name，请先安装并加入 PATH。"
    }
}

Write-Host "[1/6] 检查运行环境..." -ForegroundColor Cyan
Require-Command "python"
Require-Command "node"
Require-Command "npm"

$pyVersion = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$nodeVersion = (& node --version).TrimStart("v").Split(".")[0]
if ([version]$pyVersion -lt [version]"3.11") {
    throw "需要 Python 3.11+，当前为 $pyVersion"
}
if ([int]$nodeVersion -lt 18) {
    throw "需要 Node.js 18+，当前主版本为 $nodeVersion"
}
Write-Host "Python $pyVersion / Node $nodeVersion" -ForegroundColor Green

Write-Host "[2/6] 创建虚拟环境..." -ForegroundColor Cyan
if (-not (Test-Path $Python)) {
    & python -m venv $Venv
}

Write-Host "[3/6] 安装后端依赖..." -ForegroundColor Cyan
& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $Backend "requirements.txt")

Write-Host "[4/6] 安装前端依赖..." -ForegroundColor Cyan
Push-Location $Frontend
try {
    if (Test-Path (Join-Path $Frontend "package-lock.json")) {
        & npm.cmd ci
    } else {
        & npm.cmd install
    }
} finally {
    Pop-Location
}

Write-Host "[5/6] 初始化数据库（Alembic upgrade head）..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path (Join-Path $Root "data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Root "logs") | Out-Null
$DbPath = Join-Path $Root "data\app.sqlite"
Push-Location $Backend
try {
    # An existing app.sqlite may have been created by the app's create_all path
    # before Alembic ran. Stamp it as the current revision instead of failing.
    $stampLegacy = $false
    if (Test-Path $DbPath) {
        $dbState = & $Python (Join-Path $Backend "scripts\legacy_db.py") $DbPath
        $stampLegacy = "$dbState".Trim() -eq "stamp"
    }
    if ($stampLegacy) {
        Write-Host "检测到未纳入 Alembic 的既有数据库，标记为当前版本..." -ForegroundColor Yellow
        & $Python -m alembic stamp head
        if ($LASTEXITCODE -ne 0) { throw "数据库版本标记失败。" }
    }
    & $Python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "数据库迁移失败。" }

    Write-Host "[6/6] 播种默认数据（模型、设置、技能）..." -ForegroundColor Cyan
    & $Python -c "from app.core.config import get_settings; from app.core.db import configure_engine, get_session_factory; from app.seed import seed_defaults; s=get_settings(); configure_engine(settings=s); session=get_session_factory()(); seed_defaults(session, settings=s); session.close(); print('seed ok')"
    if ($LASTEXITCODE -ne 0) { throw "播种失败。" }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "安装完成。复制 .env.example 为 .env 并填写 APP_LLM_API_KEY 后，双击 start.bat 启动。" -ForegroundColor Green
