param(
    [string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot),
    [int]$QuietSeconds = 3,
    [switch]$Push
)

$ErrorActionPreference = 'Stop'

function Invoke-Git {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & git @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed"
    }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'Git is not available on PATH.'
}

$rootPath = (Resolve-Path $RepositoryRoot).Path
Set-Location $rootPath

Write-Host "Watching $rootPath for changes. Press Ctrl+C to stop."

$script:rootPath = $rootPath
$script:pushEnabled = $Push.IsPresent
$script:timer = New-Object System.Timers.Timer
$script:timer.Interval = $QuietSeconds * 1000
$script:timer.AutoReset = $false
$script:dirty = $false

$watcher = New-Object System.IO.FileSystemWatcher
$watcher.Path = $rootPath
$watcher.Filter = '*'
$watcher.IncludeSubdirectories = $true
$watcher.NotifyFilter = [System.IO.NotifyFilters]'FileName, DirectoryName, LastWrite, CreationTime, Size'
$watcher.EnableRaisingEvents = $true

$debounceAction = {
    $script:dirty = $true
    $script:timer.Stop()
    $script:timer.Start()
}

$commitAction = {
    if (-not $script:dirty) {
        return
    }

    $script:dirty = $false
    Set-Location $script:rootPath

    $statusBefore = & git status --porcelain
    if (-not $statusBefore) {
        return
    }

    & git add -A
    if ($LASTEXITCODE -ne 0) {
        return
    }

    $statusAfterAdd = & git status --porcelain
    if (-not $statusAfterAdd) {
        return
    }

    $message = "Auto-sync: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    & git commit -m $message

    if ($LASTEXITCODE -eq 0 -and $script:pushEnabled) {
        & git push
    }
}

Register-ObjectEvent -InputObject $watcher -EventName Changed -Action $debounceAction | Out-Null
Register-ObjectEvent -InputObject $watcher -EventName Created -Action $debounceAction | Out-Null
Register-ObjectEvent -InputObject $watcher -EventName Deleted -Action $debounceAction | Out-Null
Register-ObjectEvent -InputObject $watcher -EventName Renamed -Action $debounceAction | Out-Null
Register-ObjectEvent -InputObject $script:timer -EventName Elapsed -Action $commitAction | Out-Null

while ($true) {
    Wait-Event -Timeout 1 | Out-Null
}