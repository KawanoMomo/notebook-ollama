<#
.SYNOPSIS
    Register Notebook Ollama as a Windows Scheduled Task that starts at user logon.

.PARAMETER Run
    Start the task immediately after registering it.

.EXAMPLE
    .\scripts\install-startup.ps1
    .\scripts\install-startup.ps1 -Run
#>
param(
    [switch]$Run
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$TaskName   = "NotebookOllama"
$ScriptPath = Join-Path (Split-Path -Parent $PSScriptRoot) "scripts\start.ps1"
$ScriptPath = (Resolve-Path $ScriptPath).Path   # absolute

Write-Host "[install] Notebook Ollama scheduled task installer" -ForegroundColor Cyan
Write-Host "[install] Script: $ScriptPath"
Write-Host "[install] Task name: $TaskName"

# ---------------------------------------------------------------------------
# Remove existing task gracefully (avoid Register-ScheduledTask errors)
# ---------------------------------------------------------------------------
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[install] Task '$TaskName' already exists - replacing it." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# ---------------------------------------------------------------------------
# Build task components
# ---------------------------------------------------------------------------
# Action: run start.ps1 -Background in a hidden window
$psExe  = (Get-Command powershell.exe).Source
$action = New-ScheduledTaskAction `
    -Execute $psExe `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`" -Background"

# Trigger: at current user logon
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# Settings
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

# Principal: run as current user (no elevation required for user-logon tasks)
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------
Register-ScheduledTask `
    -TaskName  $TaskName `
    -Action    $action `
    -Trigger   $trigger `
    -Settings  $settings `
    -Principal $principal `
    -Description "Start Notebook Ollama server at user logon (background mode)." |
    Out-Null

# Verify
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
Write-Host "[install] Task registered successfully." -ForegroundColor Green
Write-Host "          State : $($task.State)"
Write-Host "          Path  : $($task.TaskPath)$($task.TaskName)"

if ($Run) {
    Write-Host "[install] Starting task now..." -ForegroundColor Cyan
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 2
    $task = Get-ScheduledTask -TaskName $TaskName
    Write-Host "[install] Task state after start: $($task.State)" -ForegroundColor Green
}

Write-Host ""
Write-Host "[install] Done. The server will start automatically at next logon." -ForegroundColor Cyan
Write-Host "          To stop auto-launch: .\scripts\uninstall-startup.ps1"
Write-Host "          Logs: $env:USERPROFILE\.notebook-ollama\logs\server.log"
