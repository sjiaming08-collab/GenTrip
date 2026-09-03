param(
    [int]$WorkerReplicas = 1,
    [switch]$Build,
    [switch]$SkipFrontend,
    [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $root ".runtime_logs"
$frontendDir = Join-Path $root "frontend"
$frontendPidFile = Join-Path $runtimeDir "frontend.pid"
$frontendOut = Join-Path $runtimeDir "frontend.stdout.log"
$frontendErr = Join-Path $runtimeDir "frontend.stderr.log"

function Test-Http([string]$Url) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    } catch {
        return $false
    }
}

if ($WorkerReplicas -lt 1) {
    throw "WorkerReplicas must be at least 1."
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "docker was not found. Start Docker Desktop and open a new PowerShell terminal."
}
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue) -and -not $SkipFrontend) {
    throw "npm.cmd was not found. Install Node.js 22+ and open a new PowerShell terminal."
}

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
Set-Location $root

if (-not (Test-Path -LiteralPath (Join-Path $root ".env"))) {
    Copy-Item -LiteralPath (Join-Path $root ".env.example") -Destination (Join-Path $root ".env")
    Write-Host "Created .env from .env.example"
}

docker info --format "Docker server {{.ServerVersion}}" | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "Docker daemon is unavailable. Wait until Docker Desktop reports Running."
}
docker compose config --quiet
if ($LASTEXITCODE -ne 0) {
    throw "docker compose configuration is invalid."
}

$composeArgs = @("compose", "up", "-d", "--scale", "worker=$WorkerReplicas")
if ($Build) {
    $composeArgs += "--build"
}
& docker @composeArgs
if ($LASTEXITCODE -ne 0) {
    throw "docker compose up failed."
}

$healthUrl = "http://127.0.0.1:8080/api/v1/health"
$deadline = (Get-Date).AddMinutes(3)
$health = $null
do {
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3
    } catch {
        $health = $null
    }
} until (
    ($health -and $health.status -eq "ok" -and $health.dependencies.database -and $health.dependencies.redis) -or
    (Get-Date) -gt $deadline
)

if (-not $health -or -not $health.dependencies.database -or -not $health.dependencies.redis) {
    docker compose logs --tail 80 api worker postgres redis | Out-Host
    throw "GenTrip API did not become healthy within 3 minutes."
}

if (-not $SkipFrontend) {
    $frontendUrl = "http://127.0.0.1:5173"
    if (-not (Test-Http $frontendUrl)) {
        if (-not (Test-Path -LiteralPath (Join-Path $frontendDir "node_modules"))) {
            Push-Location $frontendDir
            try {
                npm.cmd ci
                if ($LASTEXITCODE -ne 0) { throw "npm ci failed." }
            } finally {
                Pop-Location
            }
        }

        $npm = (Get-Command npm.cmd).Source
        $process = Start-Process `
            -FilePath $npm `
            -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1") `
            -WorkingDirectory $frontendDir `
            -WindowStyle Hidden `
            -RedirectStandardOutput $frontendOut `
            -RedirectStandardError $frontendErr `
            -PassThru
        Set-Content -LiteralPath $frontendPidFile -Value $process.Id -Encoding ASCII

        $deadline = (Get-Date).AddMinutes(1)
        while (-not (Test-Http $frontendUrl) -and (Get-Date) -lt $deadline) {
            if ($process.HasExited) {
                if (Test-Path -LiteralPath $frontendErr) {
                    Get-Content -Tail 40 -LiteralPath $frontendErr | Out-Host
                }
                throw "Frontend process exited before becoming ready."
            }
            Start-Sleep -Seconds 1
        }
        if (-not (Test-Http $frontendUrl)) {
            throw "Frontend did not become ready within 1 minute. Inspect $frontendErr."
        }
    } else {
        Write-Host "Frontend is already running on port 5173."
    }
}

Write-Host ""
Write-Host "GenTrip is ready"
Write-Host "Frontend:  http://127.0.0.1:5173"
Write-Host "API docs:  http://127.0.0.1:8080/docs"
Write-Host "Grafana:   http://127.0.0.1:3000"
Write-Host "Prometheus:http://127.0.0.1:9090"
Write-Host "Frontend logs: $frontendOut and $frontendErr"
Write-Host "Stop with: .\scripts\stop-local.cmd"

if ($OpenBrowser -and -not $SkipFrontend) {
    Start-Process "http://127.0.0.1:5173"
}
