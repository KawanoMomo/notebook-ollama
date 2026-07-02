<#
.SYNOPSIS
    Start the Notebook Ollama server.

.DESCRIPTION
    The single command to start the app. Safe to run repeatedly:
      * If the server is already running, it just opens the browser and exits.
      * If a previous or orphaned instance is holding the port or the Qdrant
        lock, it is cleaned up automatically before starting.
    You never need to find and kill processes by hand.

    To stop the server, run:  .\scripts\stop.ps1

.PARAMETER Port
    TCP port to listen on. Default: 8765.

.PARAMETER Background
    Run the server detached (hidden), logging to the data dir. Used by the
    logon task installed via install-startup.ps1.

.PARAMETER OpenBrowser
    Open the app in the default browser after startup.

.EXAMPLE
    .\scripts\start.ps1
    .\scripts\start.ps1 -OpenBrowser
    .\scripts\start.ps1 -Background

.NOTES
    Large models (GPT-OSS:20B etc.) may need longer Ollama timeouts than the
    600 s defaults. Either change them in Settings -> Models / Ollama, or set
    these env vars before starting:
      $env:NOTEBOOK_OLLAMA_OLLAMA__REQUEST_TIMEOUT_SECONDS = "1200"
      $env:NOTEBOOK_OLLAMA_OLLAMA__CHAT_READ_TIMEOUT_SECONDS = "1200"
#>
param(
    [int]   $Port = 8765,
    [switch]$Background,
    [switch]$OpenBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# NOTE: every message in this script is ASCII only. Windows PowerShell 5.1 reads
# .ps1 files in the system ANSI code page (cp932 on JP Windows) unless they carry
# a UTF-8 BOM, so non-ASCII characters (em dash, Japanese) would garble on screen.
# Staying ASCII makes the script robust no matter how an editor saves it.

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DataDir     = Join-Path $env:USERPROFILE ".notebook-ollama"
$LogDir      = Join-Path $DataDir "logs"
$LogFile     = Join-Path $LogDir  "server.log"
$ErrFile     = Join-Path $LogDir  "server-error.log"
$PidFile     = Join-Path $DataDir "server.pid"
$SettingsFile = Join-Path $DataDir "settings.json"
$WebDir      = Join-Path $ProjectRoot "apps\web"
$WebSrcDir   = Join-Path $WebDir "src"
$WebDistIdx  = Join-Path $WebDir "dist\index.html"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# nvm4w's npm.ps1 shim throws under Set-StrictMode (it reads $MyInvocation.Statement,
# which does not exist, raising PropertyNotFoundStrict). npm.cmd is a plain batch
# file and is immune, so call it directly. npm.cmd does not honor
# $ErrorActionPreference, so surface a non-zero exit as a terminating error.
function Invoke-Npm {
    param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $NpmArgs)
    & npm.cmd @NpmArgs
    if ($LASTEXITCODE -ne 0) { throw "npm $($NpmArgs -join ' ') failed (exit $LASTEXITCODE)" }
}

function Test-ServerHealthy {
    param([int]$ServerPort)
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$ServerPort/api/notebooks" `
                               -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
        return $r.StatusCode -eq 200
    } catch {
        return $false
    }
}

# Ollama reports model names as 'name:tag' (e.g. 'bge-m3:latest'). When the
# wanted name has no explicit tag, match on the base name so 'bge-m3' matches
# 'bge-m3:latest'. Otherwise require an exact match.
function Test-ModelPresent {
    param([string[]]$Tags, [string]$Wanted)
    if ($Tags -contains $Wanted) { return $true }
    if ($Wanted -notmatch ':') {
        foreach ($t in $Tags) {
            if (($t -split ':', 2)[0] -eq $Wanted) { return $true }
        }
    }
    return $false
}

# Stop every Notebook Ollama server process: the one in the PID file, anything
# listening on the port, and any orphaned uvicorn/python running this app.
# Qdrant local mode holds an exclusive file lock, so a single leftover process
# blocks the next start; clearing them all means the user never kills processes
# by hand. Returns the list of PIDs that were stopped.
function Stop-Instances {
    param([int]$ServerPort)

    $targets = New-Object 'System.Collections.Generic.HashSet[int]'

    if (Test-Path $PidFile) {
        $fromFile = (Get-Content $PidFile -Raw -ErrorAction SilentlyContinue)
        if ($fromFile) {
            $fromFile = $fromFile.Trim()
            if ($fromFile -match '^\d+$') { [void]$targets.Add([int]$fromFile) }
        }
    }

    Get-NetTCPConnection -LocalPort $ServerPort -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { [void]$targets.Add([int]$_.OwningProcess) }

    Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'uvicorn.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -like '*apps.api.main*' } |
        ForEach-Object { [void]$targets.Add([int]$_.ProcessId) }

    $stopped = @()
    foreach ($procId in $targets) {
        if (Get-Process -Id $procId -ErrorAction SilentlyContinue) {
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            $stopped += $procId
        }
    }

    if (Test-Path $PidFile) { Remove-Item $PidFile -Force -ErrorAction SilentlyContinue }
    if ($stopped.Count -gt 0) { Start-Sleep -Milliseconds 700 }
    return $stopped
}

# ---------------------------------------------------------------------------
# 1. Check / start Ollama
# ---------------------------------------------------------------------------
function Test-OllamaReachable {
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:11434/api/version" `
                                  -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
        return $resp.StatusCode -eq 200
    } catch {
        return $false
    }
}

Write-Host "[start] Checking Ollama..." -ForegroundColor Cyan
if (-not (Test-OllamaReachable)) {
    Write-Host "[start] Ollama not responding. Attempting to start..." -ForegroundColor Yellow
    if (Get-Command "ollama" -ErrorAction SilentlyContinue) {
        Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    } else {
        Write-Error "[start] 'ollama' not found on PATH. Install from https://ollama.com/download"
        exit 1
    }
    $waited = 0
    while ($waited -lt 10) {
        Start-Sleep -Seconds 1
        $waited++
        if (Test-OllamaReachable) { break }
    }
    if (-not (Test-OllamaReachable)) {
        Write-Error "[start] Ollama did not come up within 10 seconds. Aborting."
        exit 1
    }
    Write-Host "[start] Ollama started." -ForegroundColor Green
} else {
    Write-Host "[start] Ollama is reachable." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# 2. Verify required models (warning only; never blocks startup)
# ---------------------------------------------------------------------------
Write-Host "[start] Checking required models..." -ForegroundColor Cyan

$DefaultModel   = "qwen2.5:14b"
$EmbeddingModel = "bge-m3"
# The app persists user-selected models to settings.json under the "ollama"
# section (default_model / embedding_model). settings.json is sparse, so guard
# every member access - under StrictMode a missing property would throw. When a
# value is absent we keep the defaults above.
if (Test-Path $SettingsFile) {
    try {
        $cfg = Get-Content $SettingsFile -Raw | ConvertFrom-Json
        if ($cfg.PSObject.Properties['ollama']) {
            $ollamaCfg = $cfg.ollama
            if ($ollamaCfg.PSObject.Properties['default_model'] -and $ollamaCfg.default_model) {
                $DefaultModel = $ollamaCfg.default_model
            }
            if ($ollamaCfg.PSObject.Properties['embedding_model'] -and $ollamaCfg.embedding_model) {
                $EmbeddingModel = $ollamaCfg.embedding_model
            }
        }
    } catch {
        # ignore parse errors; fall back to the hard-coded defaults
    }
}

try {
    $tagsResp = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" `
                                  -TimeoutSec 10 -UseBasicParsing -ErrorAction Stop
    # Guard the shape: a non-Ollama service or a future API change could omit
    # "models"; without the guard .models would throw under StrictMode and the
    # catch would mask a reachable-but-malformed response as "Ollama down".
    $parsed = $tagsResp.Content | ConvertFrom-Json
    $modelList = if ($parsed.PSObject.Properties['models']) { $parsed.models } else { @() }
    $tags = @($modelList | Where-Object { $_ -and $_.PSObject.Properties['name'] } | ForEach-Object { $_.name })

    if (Test-ModelPresent -Tags $tags -Wanted $EmbeddingModel) {
        Write-Host "[start] Embedding model '$EmbeddingModel' OK." -ForegroundColor Green
    } else {
        Write-Warning "[start] Embedding model '$EmbeddingModel' not found. Run: ollama pull $EmbeddingModel"
    }

    if ((Test-ModelPresent -Tags $tags -Wanted $DefaultModel) -or
        (Test-ModelPresent -Tags $tags -Wanted "qwen2.5:14b")) {
        Write-Host "[start] LLM model check OK." -ForegroundColor Green
    } else {
        Write-Warning "[start] LLM model '$DefaultModel' (or qwen2.5:14b) not found. Run: ollama pull $DefaultModel"
    }
} catch {
    Write-Warning "[start] Could not query Ollama model list: $_"
}

# ---------------------------------------------------------------------------
# 3. Build the frontend if the bundle is missing or stale
# ---------------------------------------------------------------------------
Write-Host "[start] Checking frontend build..." -ForegroundColor Cyan

$needsBuild = $false
if (-not (Test-Path $WebDistIdx)) {
    Write-Host "[start] dist/index.html not found - will build." -ForegroundColor Yellow
    $needsBuild = $true
} else {
    $distTime = (Get-Item $WebDistIdx).LastWriteTime
    $newerSrc = Get-ChildItem -Path $WebSrcDir -Recurse -File |
                Where-Object { $_.LastWriteTime -gt $distTime }
    if ($newerSrc) {
        Write-Host "[start] Source files are newer than the bundle - will rebuild." -ForegroundColor Yellow
        $needsBuild = $true
    }
}

if ($needsBuild) {
    if (-not (Test-Path (Join-Path $WebDir "node_modules"))) {
        Write-Host "[start] node_modules missing - running npm install..." -ForegroundColor Yellow
        Push-Location $WebDir
        try { Invoke-Npm install } finally { Pop-Location }
    }
    Write-Host "[start] Running npm run build..." -ForegroundColor Yellow
    Push-Location $WebDir
    try { Invoke-Npm run build } finally { Pop-Location }
    Write-Host "[start] Frontend build complete." -ForegroundColor Green
} else {
    Write-Host "[start] Frontend build is up to date." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# 4. Make sure the port is free (self-heal), then start uvicorn
# ---------------------------------------------------------------------------
if (Test-ServerHealthy -ServerPort $Port) {
    Write-Host "[start] Server is already running at http://localhost:$Port/" -ForegroundColor Green
    if ($OpenBrowser) { Start-Process "http://localhost:$Port/" }
    Write-Host "[start] Nothing to do. To stop it, run: .\scripts\stop.ps1" -ForegroundColor Cyan
    exit 0
}

$cleaned = @(Stop-Instances -ServerPort $Port)
if ($cleaned.Count -gt 0) {
    Write-Host "[start] Cleaned up a previous/stale instance (PID $($cleaned -join ', '))." -ForegroundColor Yellow
}

$env:NOTEBOOK_OLLAMA_DATA_DIR = $DataDir

# Single process on purpose: Qdrant local mode keeps an exclusive lock, so
# multiple uvicorn workers cannot share the storage. Do NOT add --workers.
$uvicornArgs = @(
    "run", "uvicorn",
    "apps.api.main:app",
    "--host", "127.0.0.1",
    "--port", "$Port"
)

if ($Background) {
    Write-Host "[start] Starting server in background (log -> $LogFile)..." -ForegroundColor Cyan
    # stdout and stderr must go to DIFFERENT files; Start-Process rejects the same
    # path for both.
    $proc = Start-Process -FilePath "uv" `
                          -ArgumentList $uvicornArgs `
                          -WorkingDirectory $ProjectRoot `
                          -RedirectStandardOutput $LogFile `
                          -RedirectStandardError  $ErrFile `
                          -WindowStyle Hidden `
                          -PassThru
    $proc.Id | Set-Content -Path $PidFile -Encoding ASCII
    Write-Host "[start] Server PID $($proc.Id) (logs: $LogFile)" -ForegroundColor Green

    if ($OpenBrowser) {
        Start-Sleep -Seconds 2
        Start-Process "http://localhost:$Port/"
    }
} else {
    Write-Host "[start] Starting server on http://127.0.0.1:$Port/ (foreground - Ctrl+C to stop)..." -ForegroundColor Cyan

    if ($OpenBrowser) {
        Start-Job -ScriptBlock {
            param($u) Start-Sleep -Seconds 2; Start-Process $u
        } -ArgumentList "http://localhost:$Port/" | Out-Null
    }

    # Run uvicorn directly (not via Start-Process) so Ctrl+C is delivered to it
    # and it shuts down cleanly, releasing the Qdrant lock. Nothing is left
    # orphaned. stop.ps1 can also stop it from another terminal (by port).
    Push-Location $ProjectRoot
    $exitCode = 0
    try {
        & uv @uvicornArgs
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    # Propagate uvicorn's exit code so a failed start is not reported as success.
    exit $exitCode
}
