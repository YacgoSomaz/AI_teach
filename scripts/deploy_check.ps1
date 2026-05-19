#Requires -Version 5.1
<#
.SYNOPSIS
    AI 复习导航系统 — 部署前自检脚本（Windows PowerShell）

.DESCRIPTION
    依次检查 Docker 环境、.env 配置、compose 语法，以及（可选）已运行服务的健康状态。
    脚本不会打印 .env 中的任何敏感值。

.EXAMPLE
    # 在项目根目录执行
    powershell -ExecutionPolicy Bypass -File scripts\deploy_check.ps1

.EXAMPLE
    # 跳过健康检查（服务尚未启动时）
    powershell -ExecutionPolicy Bypass -File scripts\deploy_check.ps1 -SkipHealth
#>

param(
    [switch]$SkipHealth,          # 跳过 /health / /health/ready 检查
    [string]$ApiBaseUrl = "http://localhost:8000"  # API 地址
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── 输出工具 ──────────────────────────────────────────────────────────────────
$script:PassCount = 0
$script:FailCount = 0
$script:WarnCount = 0

function Write-Pass([string]$msg) {
    Write-Host "  [PASS] $msg" -ForegroundColor Green
    $script:PassCount++
}

function Write-Fail([string]$msg) {
    Write-Host "  [FAIL] $msg" -ForegroundColor Red
    $script:FailCount++
}

function Write-Warn([string]$msg) {
    Write-Host "  [WARN] $msg" -ForegroundColor Yellow
    $script:WarnCount++
}

function Write-Section([string]$title) {
    Write-Host ""
    Write-Host "── $title" -ForegroundColor Cyan
}

# ── 1. docker 是否可用 ────────────────────────────────────────────────────────
Write-Section "Docker 可用性"

try {
    $dockerVersion = (docker --version 2>&1)
    if ($LASTEXITCODE -eq 0) {
        Write-Pass "docker 已安装：$dockerVersion"
    } else {
        Write-Fail "docker 命令执行失败（exit $LASTEXITCODE）"
    }
} catch {
    Write-Fail "docker 未安装或不在 PATH 中"
}

try {
    docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Pass "Docker daemon 正在运行"
    } else {
        Write-Fail "Docker daemon 未启动（请打开 Docker Desktop）"
    }
} catch {
    Write-Fail "无法连接 Docker daemon"
}

# ── 2. docker compose 是否可用 ───────────────────────────────────────────────
Write-Section "Docker Compose 可用性"

try {
    $composeVersion = (docker compose version 2>&1)
    if ($LASTEXITCODE -eq 0) {
        Write-Pass "docker compose 已安装：$composeVersion"
    } else {
        Write-Fail "docker compose 不可用（需要 Docker Compose v2）"
    }
} catch {
    Write-Fail "docker compose 命令失败"
}

# ── 3. .env 文件是否存在 ──────────────────────────────────────────────────────
Write-Section ".env 配置"

$envFile = Join-Path $PSScriptRoot ".." ".env"
$envFile = [System.IO.Path]::GetFullPath($envFile)

if (Test-Path $envFile) {
    Write-Pass ".env 文件存在：$envFile"

    # 检查必填 key 是否存在（只检查 key，不打印 value）
    $requiredKeys = @(
        "POSTGRES_PASSWORD",
        "PADDLEOCR_TOKEN",
        "DOUBAO_SEED_API_KEY",
        "DOUBAO_SEED_MODEL"
    )
    $envContent = Get-Content $envFile

    foreach ($key in $requiredKeys) {
        $line = $envContent | Where-Object { $_ -match "^$key\s*=\s*.+" }
        if ($line) {
            Write-Pass "  必填项已设置：$key"
        } else {
            Write-Fail "  必填项缺失或为空：$key"
        }
    }
} else {
    Write-Fail ".env 文件不存在（请执行：cp .env.example .env 并填写必填项）"
}

# ── 4. docker compose config 语法验证 ────────────────────────────────────────
Write-Section "docker-compose.yml 语法验证"

$projectRoot = Join-Path $PSScriptRoot ".."
Push-Location ([System.IO.Path]::GetFullPath($projectRoot))
try {
    $configOutput = docker compose config --quiet 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Pass "docker compose config 语法正确"
    } else {
        Write-Fail "docker compose config 报错：`n$configOutput"
    }
} finally {
    Pop-Location
}

# ── 5. docker compose ps（列出服务状态，不启动）────────────────────────────────
Write-Section "服务状态（docker compose ps）"

Push-Location ([System.IO.Path]::GetFullPath($projectRoot))
try {
    $psOutput = docker compose ps --format "table {{.Name}}\t{{.Status}}" 2>&1
    if ($LASTEXITCODE -eq 0) {
        if ($psOutput -match "No such") {
            Write-Warn "服务尚未启动（执行 docker compose up -d --build 启动）"
        } else {
            Write-Pass "docker compose ps 执行成功"
            Write-Host $psOutput -ForegroundColor Gray
        }
    } else {
        Write-Fail "docker compose ps 失败：`n$psOutput"
    }
} finally {
    Pop-Location
}

# ── 6. 健康检查（可选，服务已启动时才执行）────────────────────────────────────
if (-not $SkipHealth) {
    Write-Section "健康检查（$ApiBaseUrl）"

    # /health — liveness
    try {
        $resp = Invoke-WebRequest -Uri "$ApiBaseUrl/health" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            Write-Pass "/health → $($resp.StatusCode)  $($resp.Content)"
        } else {
            Write-Fail "/health → 非预期状态码 $($resp.StatusCode)"
        }
    } catch {
        Write-Warn "/health 无响应（服务未启动？）跳过。使用 -SkipHealth 参数可静默此警告。"
    }

    # /health/ready — readiness
    try {
        $resp = Invoke-WebRequest -Uri "$ApiBaseUrl/health/ready" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            Write-Pass "/health/ready → $($resp.StatusCode)  $($resp.Content)"
        } elseif ($resp.StatusCode -eq 503) {
            Write-Fail "/health/ready → 503 degraded（DB 或 Redis 不可达）：$($resp.Content)"
        } else {
            Write-Fail "/health/ready → 非预期状态码 $($resp.StatusCode)"
        }
    } catch {
        Write-Warn "/health/ready 无响应（服务未启动？）跳过。"
    }
} else {
    Write-Host ""
    Write-Host "  [跳过] 健康检查（-SkipHealth 已设置）" -ForegroundColor DarkGray
}

# ── 汇总 ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkGray
Write-Host "  结果汇总：PASS=$($script:PassCount)  FAIL=$($script:FailCount)  WARN=$($script:WarnCount)" -ForegroundColor White

if ($script:FailCount -gt 0) {
    Write-Host "  ✗ 自检未通过，请修复上述 FAIL 项后再部署。" -ForegroundColor Red
    exit 1
} elseif ($script:WarnCount -gt 0) {
    Write-Host "  ⚠ 自检通过（有警告），确认后可部署。" -ForegroundColor Yellow
    exit 0
} else {
    Write-Host "  ✓ 所有检查通过，可以部署。" -ForegroundColor Green
    exit 0
}
