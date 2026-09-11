[CmdletBinding()]
param(
    [int]$BackendPort = 3018,
    [switch]$Force,
    [switch]$EnableMinuteK,
    [ValidateRange(1, 30)]
    [int]$MinuteDays = 5,
    [ValidateRange(0, 23)]
    [int]$ReadyHour = 16,
    [ValidateRange(0, 59)]
    [int]$ReadyMinute = 30,
    [ValidateRange(1, 30)]
    [int]$PollSeconds = 2,
    [ValidateRange(5, 240)]
    [int]$TimeoutMinutes = 90
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot 'backend'
$BackendPython = Join-Path $BackendDir '.venv\Scripts\python.exe'
$EnvFile = Join-Path $RepoRoot '.env'
$BaseUrl = "http://127.0.0.1:$BackendPort"

try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
    $OutputEncoding = New-Object System.Text.UTF8Encoding $false
} catch {}

function Write-Step([string]$Message) {
    Write-Host "[update-all] $Message" -ForegroundColor Cyan
}

function Test-Backend {
    try {
        $health = Invoke-RestMethod -Uri "$BaseUrl/health" -TimeoutSec 3
        return $health.status -eq 'ok'
    } catch {
        return $false
    }
}

function Start-BackendIfNeeded {
    if (Test-Backend) {
        Write-Step "Backend is running: $BaseUrl"
        return
    }
    if (-not (Test-Path -LiteralPath $BackendPython)) {
        throw "Backend Python not found at $BackendPython. Run .\dev.ps1 once first."
    }

    $arguments = @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$BackendPort")
    if (Test-Path -LiteralPath $EnvFile) {
        $arguments += @('--env-file', $EnvFile)
    }
    Write-Step 'Backend is not running; starting it in the background...'
    $process = Start-Process -FilePath $BackendPython -ArgumentList $arguments `
        -WorkingDirectory $BackendDir -WindowStyle Hidden -PassThru

    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline) {
        if ($process.HasExited) {
            throw "Backend exited during startup with code $($process.ExitCode)."
        }
        if (Test-Backend) {
            Write-Step 'Backend is ready.'
            return
        }
        Start-Sleep -Seconds 2
    }
    throw 'Backend did not become ready within 120 seconds. Check backend logs.'
}

function Get-ChinaNow {
    $zone = [TimeZoneInfo]::FindSystemTimeZoneById('China Standard Time')
    return [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $zone)
}

function Get-ExpectedDataDate([DateTime]$Now) {
    $candidate = $Now.Date
    $readyAt = $Now.Date.AddHours($ReadyHour).AddMinutes($ReadyMinute)
    if ($candidate.DayOfWeek -notin @('Saturday', 'Sunday') -and $Now -lt $readyAt) {
        $candidate = $candidate.AddDays(-1)
    }
    while ($candidate.DayOfWeek -in @('Saturday', 'Sunday')) {
        $candidate = $candidate.AddDays(-1)
    }
    return $candidate
}

function Invoke-JsonPut([string]$Path, [hashtable]$Body) {
    Invoke-RestMethod -Method Put -Uri "$BaseUrl$Path" -ContentType 'application/json' `
        -Body ($Body | ConvertTo-Json -Compress)
}

function Get-DataFreshnessGaps {
    param(
        [psobject]$DataStatus,
        [DateTime]$ExpectedDate,
        [psobject]$QuantxCatalog,
        [switch]$IncludeMinuteK
    )

    $required = [ordered]@{
        daily          = $DataStatus.daily.latest_date
        enriched       = $DataStatus.enriched.latest_date
        index_daily    = $DataStatus.index_daily.latest_date
        index_enriched = $DataStatus.index_enriched.latest_date
        etf_daily      = $DataStatus.etf_daily.latest_date
        etf_enriched   = $DataStatus.etf_enriched.latest_date
        adj_factor     = $DataStatus.adj_factor.latest_date
        instruments    = $DataStatus.instruments.latest_as_of
    }
    if ($IncludeMinuteK) {
        $required.minute = $DataStatus.minute.latest_date
    }

    $gaps = @()
    foreach ($entry in $required.GetEnumerator()) {
        if (-not $entry.Value) {
            $gaps += "$($entry.Key)=missing"
            continue
        }

        try {
            $actualDate = [DateTime]::ParseExact(
                [string]$entry.Value,
                'yyyy-MM-dd',
                [Globalization.CultureInfo]::InvariantCulture
            )
        } catch {
            $gaps += "$($entry.Key)=invalid:$($entry.Value)"
            continue
        }

        if ($actualDate.Date -lt $ExpectedDate.Date) {
            $gaps += "$($entry.Key)=$($actualDate.ToString('yyyy-MM-dd'))"
        }
    }

    $expectedQuantxDate = $ExpectedDate.ToString('yyyyMMdd')
    $published = if ($QuantxCatalog) {
        @($QuantxCatalog.records) | Where-Object {
            $_.trade_date -eq $expectedQuantxDate -and $_.stage -in @('complete', 'degraded')
        } | Select-Object -First 1
    } else {
        $null
    }
    if (-not $published) {
        $gaps += "quantx=$expectedQuantxDate missing_or_unpublished"
    }

    return $gaps
}

try {
    Start-BackendIfNeeded

    $now = Get-ChinaNow
    $expectedDate = Get-ExpectedDataDate $now
    $dataStatus = Invoke-RestMethod -Uri "$BaseUrl/api/data/status" -TimeoutSec 30
    $latestText = $dataStatus.enriched.latest_date
    $freshnessGaps = @()
    if (-not $Force) {
        $quantxCatalog = $null
        try {
            $quantxCatalog = Invoke-RestMethod -Uri "$BaseUrl/api/quantx-data/catalog" -TimeoutSec 30
        } catch {
            Write-Step 'QuantX catalog unavailable; full update will run to repair freshness.'
        }
        $freshnessGaps = @(Get-DataFreshnessGaps `
            -DataStatus $dataStatus `
            -ExpectedDate $expectedDate `
            -QuantxCatalog $quantxCatalog `
            -IncludeMinuteK:$EnableMinuteK)
    }

    Write-Step "China time: $($now.ToString('yyyy-MM-dd HH:mm:ss'))"
    $gapText = if ($Force) { 'force requested' } elseif ($freshnessGaps.Count) { $freshnessGaps -join ', ' } else { 'none' }
    Write-Step "Expected data date: $($expectedDate.ToString('yyyy-MM-dd')); current enriched: $latestText; stale datasets: $gapText"
    if (-not $Force -and $freshnessGaps.Count -eq 0) {
        Write-Host '[update-all] Data is current. Use -Force to run again.' -ForegroundColor Green
        exit 0
    }

    Write-Step 'Enabling A-share, index, ETF, and market-regime updates...'
    Invoke-JsonPut '/api/settings/preferences/pipeline-pull-types' @{
        pipeline_pull_a_share = $true
        pipeline_pull_index = $true
        pipeline_pull_etf = $true
    } | Out-Null
    Invoke-JsonPut '/api/settings/preferences/pipeline-regime-enabled' @{
        pipeline_regime_enabled = $true
    } | Out-Null
    if ($EnableMinuteK) {
        Write-Step "Enabling minute bars for the latest $MinuteDays days..."
        Invoke-JsonPut '/api/settings/preferences/minute-sync' @{
            minute_sync_enabled = $true
            minute_sync_days = $MinuteDays
        } | Out-Null
    }

    $run = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/pipeline/run" -TimeoutSec 30
    $jobId = $run.job_id
    $reusedText = if ($run.reused) { ' (reusing active job)' } else { '' }
    Write-Step "Job started: $jobId$reusedText"

    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    do {
        if ((Get-Date) -ge $deadline) {
            throw "Timed out after $TimeoutMinutes minutes; job is still running: $jobId"
        }
        Start-Sleep -Seconds $PollSeconds
        $job = Invoke-RestMethod -Uri "$BaseUrl/api/pipeline/jobs/$jobId" -TimeoutSec 30
        $progress = if ($null -ne $job.progress) { $job.progress } else { 0 }
        $stageProgress = if ($null -ne $job.stage_pct) { $job.stage_pct } else { 0 }
        $message = if ($job.message) { $job.message } else { $job.stage }
        Write-Host "`r[update-all] $($job.status) total=$progress% stage=$message/$stageProgress%                    " -NoNewline
    } while ($job.status -in @('pending', 'running'))
    Write-Host ''

    if ($job.status -ne 'succeeded') {
        throw "Pipeline failed: $($job.error)"
    }

    $finalStatus = Invoke-RestMethod -Uri "$BaseUrl/api/data/status" -TimeoutSec 30
    $finalDate = $finalStatus.enriched.latest_date
    Write-Host "[update-all] Update succeeded. Latest enriched date: $finalDate" -ForegroundColor Green
    if ($job.result.quantx) {
        Write-Host "[update-all] QuantX: $($job.result.quantx.trade_date) / $($job.result.quantx.status)" -ForegroundColor Green
    }
    exit 0
} catch {
    Write-Host ''
    Write-Host "[update-all] Failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host '[update-all] If access authentication is enabled, sign in and use the Data page sync button.' -ForegroundColor Yellow
    exit 1
}
