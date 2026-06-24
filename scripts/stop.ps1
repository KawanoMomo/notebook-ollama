<#
.SYNOPSIS
    Stop the Notebook Ollama server.

.DESCRIPTION
    Stops every Notebook Ollama server process reliably, whether it was started
    in the foreground, in the background, or left orphaned by an interrupted
    start. It looks in three places:
      1. the PID file written by start.ps1 -Background,
      2. whatever is listening on the port,
      3. any uvicorn/python process running apps.api.main.
    Qdrant local mode holds an exclusive lock, so this clears it completely.
    Exits 0 even if nothing was running.

.PARAMETER Port
    Port the server listens on. Default: 8765.

.EXAMPLE
    .\scripts\stop.ps1
    .\scripts\stop.ps1 -Port 9000
#>
param(
    [int]$Port = 8765
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "SilentlyContinue"

# ASCII-only output (see the note in start.ps1 about PowerShell 5.1 + cp932).

$DataDir = Join-Path $env:USERPROFILE ".notebook-ollama"
$PidFile = Join-Path $DataDir "server.pid"

$targets = New-Object 'System.Collections.Generic.HashSet[int]'

# 1. PID file
if (Test-Path $PidFile) {
    $fromFile = (Get-Content $PidFile -Raw)
    if ($fromFile) {
        $fromFile = $fromFile.Trim()
        if ($fromFile -match '^\d+$') { [void]$targets.Add([int]$fromFile) }
    }
}

# 2. Whatever is listening on the port
Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { [void]$targets.Add([int]$_.OwningProcess) }

# 3. Any orphaned uvicorn/python running this app
Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'uvicorn.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like '*apps.api.main*' } |
    ForEach-Object { [void]$targets.Add([int]$_.ProcessId) }

if ($targets.Count -eq 0) {
    Write-Host "[stop] No Notebook Ollama server is running." -ForegroundColor Yellow
    if (Test-Path $PidFile) { Remove-Item $PidFile -Force -ErrorAction SilentlyContinue }
    exit 0
}

$stopped = @()
foreach ($procId in $targets) {
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($p) {
        Write-Host "[stop] Stopping PID $procId ($($p.Name))..." -ForegroundColor Cyan
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        $stopped += $procId
    }
}

Start-Sleep -Milliseconds 700

# Verify
$alive = @()
foreach ($procId in $stopped) {
    if (Get-Process -Id $procId -ErrorAction SilentlyContinue) { $alive += $procId }
}

if (Test-Path $PidFile) { Remove-Item $PidFile -Force -ErrorAction SilentlyContinue }

if ($alive.Count -gt 0) {
    Write-Warning "[stop] These PIDs did not stop: $($alive -join ', '). Try again or end them in Task Manager."
    exit 1
}

Write-Host "[stop] Server stopped ($($stopped.Count) process(es))." -ForegroundColor Green
exit 0
