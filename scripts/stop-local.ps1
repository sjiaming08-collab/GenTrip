param(
    [switch]$AppsOnly,
    [switch]$RemoveContainers,
    [switch]$Force,
    [ValidateRange(0, 60)]
    [int]$TimeoutSeconds = 5
)

<#
.SYNOPSIS
Stops the local GenTrip stack without deleting persistent data.

.EXAMPLE
.\scripts\stop-local.ps1

.EXAMPLE
.\scripts\stop-local.ps1 -AppsOnly

.EXAMPLE
.\scripts\stop-local.ps1 -RemoveContainers
#>

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root ".runtime_logs\frontend.pid"

if ($AppsOnly -and $RemoveContainers) {
    throw "AppsOnly and RemoveContainers cannot be used together."
}
if ($Force -and $RemoveContainers) {
    throw "Force and RemoveContainers cannot be used together. Stop first, then remove containers normally."
}

function Stop-Frontend {
    if (-not (Test-Path -LiteralPath $pidFile)) {
        Write-Host "Frontend: no managed process found."
        return
    }

    $rawPid = (Get-Content -Raw -LiteralPath $pidFile).Trim()
    $frontendPid = 0
    if (-not [int]::TryParse($rawPid, [ref]$frontendPid)) {
        Remove-Item -LiteralPath $pidFile -Force
        Write-Warning "Frontend PID file was invalid and has been removed."
        return
    }

    if (Get-Process -Id $frontendPid -ErrorAction SilentlyContinue) {
        taskkill.exe /PID $frontendPid /T /F | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to stop the managed frontend process $frontendPid."
        }
        Write-Host "Frontend: stopped."
    } else {
        Write-Host "Frontend: process $frontendPid is no longer running."
    }
    Remove-Item -LiteralPath $pidFile -Force
}

Stop-Frontend
Set-Location $root

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "docker was not found. The managed frontend was stopped, but Compose services were not changed."
}

$services = if ($AppsOnly) { @("api", "worker") } else { @() }

if ($Force) {
    Write-Warning "Force-stopping containers. Use this only when graceful stopping is stuck."
    & docker compose kill @services
} elseif ($RemoveContainers) {
    & docker compose down --timeout $TimeoutSeconds
} else {
    & docker compose stop --timeout $TimeoutSeconds @services
}

if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose stop failed."
}

if ($AppsOnly) {
    Write-Host "GenTrip application stopped. PostgreSQL, Redis, and observability services are still running."
} elseif ($RemoveContainers) {
    Write-Host "GenTrip stopped and containers removed. Docker volumes and local data were preserved."
} else {
    Write-Host "GenTrip stopped. Containers, Docker volumes, and local data were preserved for a fast restart."
}
