param(
    [int]$Users = 1,
    [int]$Loops = -1,
    [int]$RampSeconds = 10,
    [int]$DurationSeconds = 600,
    [int]$PollMilliseconds = 500,
    [int]$MaxPolls = 900,
    [string]$BaseUrl = "http://127.0.0.1:8080",
    [string]$JMeterHome = $env:JMETER_HOME,
    [string]$Queries = "loadtest/jmeter/queries.csv",
    [string]$TenantPrefix = "jmeter",
    [string]$Scenario = "custom",
    [ValidateRange(0, 100)]
    [int]$ExpectedWorkers = 0
)

$ErrorActionPreference = "Stop"

if (-not $JMeterHome) {
    throw "JMETER_HOME is not set. Point it to the extracted Apache JMeter directory."
}

$jmeter = Join-Path $JMeterHome "bin/jmeter.bat"
if (-not (Test-Path -LiteralPath $jmeter)) {
    throw "JMeter launcher not found: $jmeter"
}

$root = Split-Path -Parent $PSScriptRoot
$plan = Join-Path $root "loadtest/jmeter/gentrip-async-plan.jmx"
$queryFile = if ([IO.Path]::IsPathRooted($Queries)) { $Queries } else { Join-Path $root $Queries }
$uri = [Uri]$BaseUrl
$port = if ($uri.IsDefaultPort) { if ($uri.Scheme -eq "https") { 443 } else { 80 } } else { $uri.Port }
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$safeScenario = ($Scenario -replace '[^a-zA-Z0-9_-]', '-').Trim('-')
if (-not $safeScenario) { $safeScenario = "custom" }
$runDir = Join-Path $root "loadtest/results/$stamp-$safeScenario"
$reportDir = Join-Path $runDir "html"
$jtl = Join-Path $runDir "results.jtl"
$log = Join-Path $runDir "jmeter.log"
$manifestPath = Join-Path $runDir "run-manifest.json"
$summaryPath = Join-Path $runDir "summary.json"
$resourcePath = Join-Path $runDir "docker-stats.csv"

New-Item -ItemType Directory -Path $runDir -Force | Out-Null

$startedAt = Get-Date
$gitCommit = (& git -C $root rev-parse HEAD 2>$null).Trim()
$gitDirty = @(& git -C $root status --porcelain 2>$null).Count -gt 0
$composeRows = @()
try {
    $composeRows = @(& docker compose --project-directory $root ps --format json 2>$null | ForEach-Object {
        if ($_ -and $_.Trim()) { $_ | ConvertFrom-Json }
    })
} catch {
    $composeRows = @()
}
$actualWorkers = @($composeRows | Where-Object { $_.Service -eq "worker" -and $_.State -eq "running" }).Count
if ($ExpectedWorkers -gt 0 -and $actualWorkers -ne $ExpectedWorkers) {
    throw "Expected $ExpectedWorkers running workers, but Docker Compose reports $actualWorkers."
}

$hostCpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$hostSystem = Get-CimInstance Win32_ComputerSystem
$dockerParts = @(& docker info --format '{{.NCPU}}|{{.MemTotal}}|{{.OSType}}|{{.Architecture}}' 2>$null) -split '\|'
$manifest = [ordered]@{
    scenario = $Scenario
    started_at = $startedAt.ToUniversalTime().ToString("o")
    git_commit = $gitCommit
    git_dirty = $gitDirty
    target = $BaseUrl
    parameters = [ordered]@{
        users = $Users
        loops = $Loops
        ramp_seconds = $RampSeconds
        duration_seconds = $DurationSeconds
        poll_milliseconds = $PollMilliseconds
        max_polls = $MaxPolls
        tenant_prefix = $TenantPrefix
        query_file = $queryFile
    }
    runtime = [ordered]@{
        running_worker_replicas = $actualWorkers
        compose_services = @($composeRows | ForEach-Object { [ordered]@{ service = $_.Service; state = $_.State; status = $_.Status; image = $_.Image } })
    }
    host = [ordered]@{
        cpu = $hostCpu.Name
        physical_cores = $hostCpu.NumberOfCores
        logical_processors = $hostCpu.NumberOfLogicalProcessors
        memory_gb = [Math]::Round($hostSystem.TotalPhysicalMemory / 1GB, 1)
        docker_cpus = if ($dockerParts.Count -ge 1) { [int]$dockerParts[0] } else { $null }
        docker_memory_gb = if ($dockerParts.Count -ge 2) { [Math]::Round([double]$dockerParts[1] / 1GB, 1) } else { $null }
        docker_os = if ($dockerParts.Count -ge 3) { $dockerParts[2] } else { $null }
        docker_architecture = if ($dockerParts.Count -ge 4) { $dockerParts[3] } else { $null }
    }
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Write-Host "Running GenTrip JMeter test: users=$Users ramp=${RampSeconds}s duration=${DurationSeconds}s"
Write-Host "Scenario: $Scenario workers=$actualWorkers"
Write-Host "Target: $BaseUrl"
Write-Host "Results: $runDir"

$statsJob = Start-Job -ScriptBlock {
    param($OutputPath)
    while ($true) {
        $capturedAt = (Get-Date).ToUniversalTime().ToString("o")
        try {
            $rows = @(& docker stats --no-stream --format '{{json .}}' 2>$null | ForEach-Object {
                if ($_ -and $_.Trim()) { $_ | ConvertFrom-Json }
            })
            foreach ($row in $rows) {
                [pscustomobject]@{
                    captured_at = $capturedAt
                    container = $row.Name
                    cpu_percent = $row.CPUPerc
                    memory_usage = $row.MemUsage
                    memory_percent = $row.MemPerc
                    network_io = $row.NetIO
                    block_io = $row.BlockIO
                    pids = $row.PIDs
                } | Export-Csv -LiteralPath $OutputPath -Append -NoTypeInformation -Encoding UTF8
            }
        } catch {
            # Resource sampling must not abort the load test itself.
        }
        Start-Sleep -Seconds 2
    }
} -ArgumentList $resourcePath

try {
    & $jmeter `
        -n `
        -t $plan `
        "-Jprotocol=$($uri.Scheme)" `
        "-Jhost=$($uri.Host)" `
        "-Jport=$port" `
        "-Jusers=$Users" `
        "-Jloops=$Loops" `
        "-Jramp=$RampSeconds" `
        "-Jduration=$DurationSeconds" `
        "-Jpoll_ms=$PollMilliseconds" `
        "-Jmax_polls=$MaxPolls" `
        "-Jqueries=$queryFile" `
        "-Jtenant_prefix=$TenantPrefix" `
        -l $jtl `
        -j $log `
        -e `
        -o $reportDir
    $jmeterExitCode = $LASTEXITCODE
} finally {
    Stop-Job -Job $statsJob -ErrorAction SilentlyContinue | Out-Null
    Receive-Job -Job $statsJob -ErrorAction SilentlyContinue | Out-Null
    Remove-Job -Job $statsJob -Force -ErrorAction SilentlyContinue
}

if ($jmeterExitCode -ne 0 -or -not (Test-Path -LiteralPath $jtl) -or (Get-Item -LiteralPath $jtl).Length -eq 0) {
    throw "JMeter did not produce test samples. Inspect $log."
}
$samples = @(Import-Csv -LiteralPath $jtl)
if ($samples.Count -eq 0) {
    throw "JMeter produced a result header but no samples. Inspect $log."
}
if (-not (Test-Path -LiteralPath (Join-Path $reportDir "index.html"))) {
    throw "JMeter did not generate the HTML report. Inspect $log."
}

$metricRows = @()
foreach ($label in @("Submit plan - acceptance", "E2E plan completion", "Assert successful terminal status")) {
    $labelSamples = @($samples | Where-Object { $_.label -eq $label })
    if ($labelSamples.Count -eq 0) {
        continue
    }
    $elapsed = @($labelSamples | ForEach-Object { [double]$_.elapsed } | Sort-Object)
    $p95Index = [Math]::Min($elapsed.Count - 1, [Math]::Ceiling($elapsed.Count * 0.95) - 1)
    $errors = @($labelSamples | Where-Object { $_.success -ne "true" }).Count
    $average = [Math]::Round(($elapsed | Measure-Object -Average).Average, 1)
    $p99Index = [Math]::Min($elapsed.Count - 1, [Math]::Ceiling($elapsed.Count * 0.99) - 1)
    $metricRows += [ordered]@{
        label = $label
        count = $elapsed.Count
        errors = $errors
        error_percent = [Math]::Round(($errors / $elapsed.Count) * 100, 3)
        average_ms = $average
        p95_ms = $elapsed[$p95Index]
        p99_ms = $elapsed[$p99Index]
        max_ms = $elapsed[-1]
    }
    Write-Host "$label count=$($elapsed.Count) errors=$errors avg_ms=$average p95_ms=$($elapsed[$p95Index]) max_ms=$($elapsed[-1])"
}

$firstTimestamp = ($samples | Measure-Object -Property timeStamp -Minimum).Minimum
$lastTimestamp = ($samples | ForEach-Object { [long]$_.timeStamp + [long]$_.elapsed } | Measure-Object -Maximum).Maximum
$finishedAt = Get-Date
$acceptedCount = @($samples | Where-Object { $_.label -eq "Submit plan - acceptance" -and $_.success -eq "true" }).Count
$terminalAssertionCount = @($samples | Where-Object { $_.label -eq "Assert successful terminal status" }).Count
$successfulTerminalCount = @($samples | Where-Object { $_.label -eq "Assert successful terminal status" -and $_.success -eq "true" }).Count
$endComposeRows = @()
try {
    $endComposeRows = @(& docker compose --project-directory $root ps --format json 2>$null | ForEach-Object {
        if ($_ -and $_.Trim()) { $_ | ConvertFrom-Json }
    })
} catch {
    $endComposeRows = @()
}
$workersAtEnd = @($endComposeRows | Where-Object { $_.Service -eq "worker" -and $_.State -eq "running" }).Count
$workerLossDetected = $ExpectedWorkers -gt 0 -and $workersAtEnd -ne $ExpectedWorkers
$summary = [ordered]@{
    scenario = $Scenario
    started_at = $startedAt.ToUniversalTime().ToString("o")
    finished_at = $finishedAt.ToUniversalTime().ToString("o")
    wall_duration_seconds = [Math]::Round(([long]$lastTimestamp - [long]$firstTimestamp) / 1000, 3)
    total_jmeter_samples = $samples.Count
    accepted_runs = $acceptedCount
    terminal_assertions = $terminalAssertionCount
    successful_terminal_assertions = $successfulTerminalCount
    in_flight_at_jmeter_cutoff = [Math]::Max(0, $acceptedCount - $terminalAssertionCount)
    worker_replicas_at_start = $actualWorkers
    worker_replicas_at_end = $workersAtEnd
    worker_loss_detected = $workerLossDetected
    metrics = $metricRows
}
$summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
$manifest["finished_at"] = $finishedAt.ToUniversalTime().ToString("o")
$manifest["outcome"] = "completed"
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Write-Host "JMeter report: $reportDir/index.html"
Write-Host "Machine-readable summary: $summaryPath"
if ($workerLossDetected) {
    throw "Worker replica loss detected: expected=$ExpectedWorkers running_at_end=$workersAtEnd. Inspect container logs."
}
