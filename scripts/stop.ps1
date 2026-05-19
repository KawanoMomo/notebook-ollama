<#
.SYNOPSIS
    Stop the Notebook Ollama server that was started with start.ps1.

.DESCRIPTION
    Reads the PID from $env:USERPROFILE\.notebook-ollama\server.pid and stops
    the process. Cleans up the PID file afterwards.
    Exits cleanly (exit 0) if no PID file is found.
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = "SilentlyContinue"

$DataDir = Join-Path $env:USERPROFILE ".notebook-ollama"
$PidFile = Join-Path $DataDir "server.pid"

if (-not (Test-Path $PidFile)) {
    Write-Host "[stop] No PID file found at $PidFile — server may not be running." -ForegroundColor Yellow
    exit 0
}

$pidStr = (Get-Content $PidFile -Raw).Trim()
if (-not $pidStr) {
    Write-Host "[stop] PID file is empty. Removing it." -ForegroundColor Yellow
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    exit 0
}

$serverId = [int]$pidStr
$proc = Get-Process -Id $serverId -ErrorAction SilentlyContinue

if (-not $proc) {
    Write-Host "[stop] Process $serverId not found (already stopped)." -ForegroundColor Yellow
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    exit 0
}

Write-Host "[stop] Stopping process $serverId ($($proc.Name))..." -ForegroundColor Cyan
Stop-Process -Id $serverId -Force -ErrorAction SilentlyContinue

# Give it a moment then verify
Start-Sleep -Milliseconds 500
$still = Get-Process -Id $serverId -ErrorAction SilentlyContinue
if ($still) {
    Write-Warning "[stop] Process $serverId did not stop cleanly. You may need to kill it manually."
} else {
    Write-Host "[stop] Server stopped." -ForegroundColor Green
}

Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
Write-Host "[stop] PID file removed." -ForegroundColor Green
