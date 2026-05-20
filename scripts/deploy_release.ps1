#Requires -Version 5.1
<#
.SYNOPSIS
    Clean release deploy script for ai_review_system.

.DESCRIPTION
    Creates a release archive from the current local git HEAD, uploads it to the
    server, backs up the previous server directory, rebuilds Docker images, and
    runs health checks. This script does not use docker cp hot patches.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\deploy_release.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\deploy_release.ps1 -DryRun
#>

param(
    [string]$HostName = "106.53.77.14",
    [string]$User = "ubuntu",
    [string]$RemotePath = "/home/ubuntu/ai_review_system",
    [string]$ApiBaseUrl = "http://106.53.77.14",
    [switch]$SkipTests,
    [switch]$AllowNonDev,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:PassCount = 0
$script:WarnCount = 0
$script:FailCount = 0
$script:StepIndex = 0

function Write-Step([string]$title) {
    $script:StepIndex += 1
    Write-Host ""
    Write-Host ("[{0}/8] {1}" -f $script:StepIndex, $title) -ForegroundColor Cyan
}

function Write-Pass([string]$msg) {
    Write-Host "  [PASS] $msg" -ForegroundColor Green
    $script:PassCount += 1
}

function Write-Warn([string]$msg) {
    Write-Host "  [WARN] $msg" -ForegroundColor Yellow
    $script:WarnCount += 1
}

function Write-Fail([string]$msg) {
    Write-Host "  [FAIL] $msg" -ForegroundColor Red
    $script:FailCount += 1
}

function Invoke-Local([string]$label, [scriptblock]$command) {
    Write-Host "  > $label" -ForegroundColor DarkGray
    if ($DryRun) {
        Write-Warn "DryRun: skipped local mutation"
        return
    }

    & $command
    if ($LASTEXITCODE -ne 0) {
        throw "Local command failed: $label"
    }
}

function Invoke-RemoteScript([string]$script, [string]$name) {
    $target = "${User}@${HostName}"
    $localScript = Join-Path $env:TEMP $name
    $remoteScript = "/tmp/$name"

    Write-Host "  > scp <script> ${target}:$remoteScript" -ForegroundColor DarkGray
    Write-Host "  > ssh $target bash $remoteScript" -ForegroundColor DarkGray

    if ($DryRun) {
        Write-Warn "DryRun: skipped remote mutation"
        Write-Host $script -ForegroundColor DarkGray
        return
    }

    # Write LF-only shell scripts. PowerShell 5.1 Set-Content writes CRLF,
    # which can make bash parse "then\r" and fail with "unexpected end of file".
    $scriptLf = $script -replace "`r`n", "`n"
    $scriptLf = $scriptLf -replace "`r", "`n"
    [System.IO.File]::WriteAllText(
        $localScript,
        $scriptLf + "`n",
        [System.Text.Encoding]::ASCII
    )

    & scp $localScript "${target}:$remoteScript"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to upload remote script"
    }

    & ssh $target "bash $remoteScript; rc=`$?; rm -f $remoteScript; exit `$rc"
    if ($LASTEXITCODE -ne 0) {
        throw "Remote script failed"
    }
}

function Test-Http200([string]$url, [string]$label) {
    try {
        $resp = Invoke-WebRequest -Uri $url -TimeoutSec 15 -UseBasicParsing -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            Write-Pass "$label -> 200"
            return $true
        }

        Write-Fail "$label -> $($resp.StatusCode)"
        return $false
    } catch {
        Write-Fail "$label -> $($_.Exception.Message)"
        return $false
    }
}

$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
Push-Location $projectRoot

try {
    Write-Host ""
    Write-Host "AI Review System - Clean Release Deploy" -ForegroundColor White
    Write-Host "Project: $projectRoot" -ForegroundColor DarkGray
    Write-Host "Target : ${User}@${HostName}:$RemotePath" -ForegroundColor DarkGray
    Write-Host "API    : $ApiBaseUrl" -ForegroundColor DarkGray
    if ($DryRun) {
        Write-Warn "DryRun mode enabled"
    }

    Write-Step "Check local git state"
    $branch = (git rev-parse --abbrev-ref HEAD).Trim()
    $commit = (git rev-parse --short HEAD).Trim()
    $fullCommit = (git rev-parse HEAD).Trim()
    $dirty = (git status --porcelain)

    if ($branch -eq "dev" -or $AllowNonDev) {
        Write-Pass "branch=$branch"
    } else {
        Write-Fail "branch=$branch, expected dev. Use -AllowNonDev only if intentional."
        exit 1
    }

    if ([string]::IsNullOrWhiteSpace($dirty)) {
        Write-Pass "working tree is clean"
    } else {
        Write-Fail "working tree is dirty; deploy refused"
        Write-Host $dirty -ForegroundColor Yellow
        exit 1
    }

    Write-Pass "commit=$fullCommit"

    Write-Step "Run local smoke tests"
    if ($SkipTests) {
        Write-Warn "tests skipped by -SkipTests"
    } else {
        $tests = @(
            "tests/test_frontend.py",
            "test_upload_flow.py",
            "tests/api/test_health.py",
            "tests/api/test_rate_limit.py",
            "tests/integration/test_report_flow.py",
            "tests/integration/test_services_integration.py",
            "-q"
        )
        Write-Host ("  > python -m pytest {0}" -f ($tests -join " ")) -ForegroundColor DarkGray
        if (-not $DryRun) {
            & python -m pytest @tests
            if ($LASTEXITCODE -ne 0) {
                Write-Fail "local smoke tests failed"
                exit 1
            }
        }
        Write-Pass "local smoke tests passed"
    }

    Write-Step "Create release archive"
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $archiveName = "ai_review_system_${commit}_${timestamp}.tar"
    $archivePath = Join-Path $env:TEMP $archiveName
    $remoteArchive = "/tmp/$archiveName"
    $backupPath = "/home/$User/backups/ai_review_system_${commit}_${timestamp}"

    if (Test-Path $archivePath) {
        Remove-Item $archivePath -Force
    }

    Invoke-Local "git archive --format=tar --output=$archivePath HEAD" {
        git archive --format=tar --output=$archivePath HEAD
    }

    if (-not $DryRun -and -not (Test-Path $archivePath)) {
        Write-Fail "archive was not created"
        exit 1
    }
    Write-Pass "archive=$archivePath"

    Write-Step "Check server connection"
    $precheckScript = @(
        "set -e",
        'echo "host=$(hostname)"',
        'echo "pwd=$(pwd)"',
        "docker --version",
        "docker compose version",
        "if [ -d `"$RemotePath`" ]; then",
        '  echo "remote_path_exists=yes"',
        "else",
        '  echo "remote_path_exists=no"',
        "fi"
    ) -join "`n"
    Invoke-RemoteScript $precheckScript "ai_review_precheck_$timestamp.sh"
    Write-Pass "server precheck completed"

    Write-Step "Upload release archive"
    $scpTarget = "${User}@${HostName}:$remoteArchive"
    Write-Host "  > scp $archivePath $scpTarget" -ForegroundColor DarkGray
    if ($DryRun) {
        Write-Warn "DryRun: skipped archive upload"
    } else {
        & scp $archivePath $scpTarget
        if ($LASTEXITCODE -ne 0) {
            Write-Fail "archive upload failed"
            exit 1
        }
    }
    Write-Pass "uploaded=$remoteArchive"

    Write-Step "Backup old code and extract release"
    $deployScript = @(
        "set -euo pipefail",
        "REMOTE_PATH=`"$RemotePath`"",
        "REMOTE_ARCHIVE=`"$remoteArchive`"",
        "BACKUP_PATH=`"$backupPath`"",
        'TMP_PATH="${REMOTE_PATH}.release_' + $timestamp + '"',
        'mkdir -p "$(dirname "$BACKUP_PATH")"',
        'rm -rf "$TMP_PATH"',
        'mkdir -p "$TMP_PATH"',
        'echo "[remote] extracting release to $TMP_PATH"',
        'tar -xf "$REMOTE_ARCHIVE" -C "$TMP_PATH"',
        'if [ -d "$REMOTE_PATH" ]; then',
        '  echo "[remote] backing up $REMOTE_PATH -> $BACKUP_PATH"',
        '  rm -rf "$BACKUP_PATH"',
        '  mv "$REMOTE_PATH" "$BACKUP_PATH"',
        '  if [ -f "$BACKUP_PATH/.env" ]; then',
        '    cp "$BACKUP_PATH/.env" "$TMP_PATH/.env"',
        '  fi',
        "fi",
        'if [ ! -f "$TMP_PATH/.env" ]; then',
        '  echo "[remote][FAIL] .env missing; restore from backup or create it before deploy." >&2',
        "  exit 10",
        "fi",
        'mv "$TMP_PATH" "$REMOTE_PATH"',
        'rm -f "$REMOTE_ARCHIVE"',
        'cd "$REMOTE_PATH"',
        "echo `"$fullCommit`" > .deployed_commit",
        "docker compose config --quiet"
    ) -join "`n"
    Invoke-RemoteScript $deployScript "ai_review_deploy_$timestamp.sh"
    Write-Pass "code deployed; backup=$backupPath"

    Write-Step "Rebuild Docker and restart services"
    $dockerScript = @(
        "set -euo pipefail",
        "cd `"$RemotePath`"",
        "docker compose up -d --build",
        "docker compose ps"
    ) -join "`n"
    Invoke-RemoteScript $dockerScript "ai_review_docker_$timestamp.sh"
    Write-Pass "docker compose up completed"

    Write-Step "Run HTTP health checks"
    if ($DryRun) {
        Write-Warn "DryRun: skipped HTTP health checks"
    } else {
        Start-Sleep -Seconds 8
        $okHealth = Test-Http200 "$ApiBaseUrl/health" "/health"
        $okReady = Test-Http200 "$ApiBaseUrl/health/ready" "/health/ready"
        $okHome = Test-Http200 "$ApiBaseUrl/" "home page"

        if (-not ($okHealth -and $okReady -and $okHome)) {
            Write-Fail "post-deploy health checks failed"
            Write-Host ""
            Write-Host "Rollback command:" -ForegroundColor Yellow
            Write-Host "  ssh ${User}@${HostName}" -ForegroundColor Yellow
            Write-Host "  rm -rf $RemotePath; mv $backupPath $RemotePath; cd $RemotePath; docker compose up -d --build" -ForegroundColor Yellow
            exit 1
        }
    }

    Write-Host ""
    Write-Host "==================================================" -ForegroundColor DarkGray
    Write-Host "Deploy completed" -ForegroundColor Green
    Write-Host "  commit : $fullCommit" -ForegroundColor White
    Write-Host "  backup : $backupPath" -ForegroundColor White
    Write-Host "  api    : $ApiBaseUrl" -ForegroundColor White
    Write-Host "  result : PASS=$($script:PassCount) WARN=$($script:WarnCount) FAIL=$($script:FailCount)" -ForegroundColor White
} finally {
    Pop-Location
}
