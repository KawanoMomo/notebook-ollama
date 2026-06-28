<#
.SYNOPSIS
    Remove the NotebookOllama Windows Scheduled Task.

.DESCRIPTION
    Unregisters the task registered by install-startup.ps1.
    Exits cleanly (exit 0) if the task does not exist.
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = "SilentlyContinue"

$TaskName = "NotebookOllama"

Write-Host "[uninstall] Notebook Ollama scheduled task uninstaller" -ForegroundColor Cyan
Write-Host "[uninstall] Task name: $TaskName"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "[uninstall] Task '$TaskName' not found - nothing to remove." -ForegroundColor Yellow
    exit 0
}

# Stop the task if it is currently running
if ($existing.State -eq "Running") {
    Write-Host "[uninstall] Stopping running task..." -ForegroundColor Yellow
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
Write-Host "[uninstall] Task '$TaskName' removed successfully." -ForegroundColor Green

# Verify removal
$check = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($check) {
    Write-Warning "[uninstall] Task still appears to exist. Check Task Scheduler manually."
} else {
    Write-Host "[uninstall] Confirmed: task no longer exists." -ForegroundColor Green
}
