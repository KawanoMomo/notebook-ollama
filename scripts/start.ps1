<#
.SYNOPSIS
    Start the Notebook Ollama server (production mode).

.PARAMETER Port
    TCP port to listen on. Default: 8765.

.PARAMETER Background
    Run uvicorn in the background, redirecting output to the log file.

.PARAMETER OpenBrowser
    Open http://localhost:<Port>/ in the default browser after a 2-second delay.

.EXAMPLE
    .\scripts\start.ps1
    .\scripts\start.ps1 -OpenBrowser
    .\scripts\start.ps1 -Background
    .\scripts\start.ps1 -Port 9000 -Background -OpenBrowser
#>
param(
    [int]   $Port         = 8765,
    [switch]$Background,
    [switch]$OpenBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# 0. Paths
# ---------------------------------------------------------------------------
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DataDir     = Join-Path $env:USERPROFILE ".notebook-ollama"
$LogDir      = Join-Path $DataDir "logs"
$LogFile     = Join-Path $LogDir  "server.log"
$PidFile     = Join-Path $DataDir "server.pid"
$WebSrcDir   = Join-Path $ProjectRoot "apps\web\src"
$WebDistIdx  = Join-Path $ProjectRoot "apps\web\dist\index.html"
$WebDir      = Join-Path $ProjectRoot "apps\web"
$ConfigFile  = Join-Path $DataDir "config.json"

# Ensure data + log dirs exist
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

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

    # Try to launch ollama serve if it is on PATH
    $ollamaCmd = Get-Command "ollama" -ErrorAction SilentlyContinue
    if ($ollamaCmd) {
        Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    } else {
        Write-Error "[start] 'ollama' not found on PATH. Install from https://ollama.com/download"
        exit 1
    }

    # Wait up to 10 seconds
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
    Write-Host "[start] Ollama started successfully." -ForegroundColor Green
} else {
    Write-Host "[start] Ollama is reachable." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# 2. Verify required models
# ---------------------------------------------------------------------------
Write-Host "[start] Checking required models..." -ForegroundColor Cyan

# Determine configured default_model
$DefaultModel = "qwen2.5:14b"
if (Test-Path $ConfigFile) {
    try {
        $cfg = Get-Content $ConfigFile -Raw | ConvertFrom-Json
        if ($cfg.ollama -and $cfg.ollama.default_model) {
            $DefaultModel = $cfg.ollama.default_model
        }
    } catch {
        # ignore parse errors; fall back to hard-coded default
    }
}

$EmbeddingModel = "bge-m3"

try {
    $tagsResp = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" `
                                  -TimeoutSec 10 -UseBasicParsing -ErrorAction Stop
    $tags     = ($tagsResp.Content | ConvertFrom-Json).models | ForEach-Object { $_.name }

    # Check embedding model
    if ($tags -notcontains $EmbeddingModel) {
        Write-Warning "[start] Embedding model '$EmbeddingModel' not found."
        Write-Warning "        Run: ollama pull $EmbeddingModel"
    } else {
        Write-Host "[start] Embedding model '$EmbeddingModel' OK." -ForegroundColor Green
    }

    # Check LLM: accept the configured default or any qwen2.5:14b variant
    $llmCandidates = @($DefaultModel, "qwen2.5:14b")
    $llmFound = $false
    foreach ($candidate in $llmCandidates) {
        if ($tags -contains $candidate) { $llmFound = $true; break }
    }
    if (-not $llmFound) {
        Write-Warning "[start] LLM model '$DefaultModel' (or qwen2.5:14b) not found."
        Write-Warning "        Run: ollama pull $DefaultModel"
        Write-Warning "        (Continuing — you may have configured a different model.)"
    } else {
        Write-Host "[start] LLM model check OK." -ForegroundColor Green
    }
} catch {
    Write-Warning "[start] Could not query Ollama model list: $_"
}

# ---------------------------------------------------------------------------
# 3. Build frontend if needed
# ---------------------------------------------------------------------------
Write-Host "[start] Checking frontend build..." -ForegroundColor Cyan

$needsBuild = $false
if (-not (Test-Path $WebDistIdx)) {
    Write-Host "[start] dist/index.html not found — will build." -ForegroundColor Yellow
    $needsBuild = $true
} else {
    $distTime = (Get-Item $WebDistIdx).LastWriteTime
    $newerSrc = Get-ChildItem -Path $WebSrcDir -Recurse -File |
                Where-Object { $_.LastWriteTime -gt $distTime }
    if ($newerSrc) {
        Write-Host "[start] Source files newer than dist — will rebuild." -ForegroundColor Yellow
        $needsBuild = $true
    }
}

if ($needsBuild) {
    $nodeModules = Join-Path $WebDir "node_modules"
    if (-not (Test-Path $nodeModules)) {
        Write-Host "[start] node_modules missing — running npm install..." -ForegroundColor Yellow
        Push-Location $WebDir
        try { npm install } finally { Pop-Location }
    }
    Write-Host "[start] Running npm run build..." -ForegroundColor Yellow
    Push-Location $WebDir
    try { npm run build } finally { Pop-Location }
    Write-Host "[start] Frontend build complete." -ForegroundColor Green
} else {
    Write-Host "[start] Frontend build is up to date." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# 4. Start uvicorn
# ---------------------------------------------------------------------------
$env:NOTEBOOK_OLLAMA_DATA_DIR = $DataDir

$uvicornArgs = @(
    "run", "uvicorn",
    "apps.api.main:app",
    "--host", "127.0.0.1",
    "--port", "$Port",
    "--workers", "1"
)

if ($Background) {
    Write-Host "[start] Starting server in background (log -> $LogFile)..." -ForegroundColor Cyan

    $proc = Start-Process -FilePath "uv" `
                          -ArgumentList $uvicornArgs `
                          -WorkingDirectory $ProjectRoot `
                          -RedirectStandardOutput $LogFile `
                          -RedirectStandardError  $LogFile `
                          -WindowStyle Hidden `
                          -PassThru

    # Write PID file
    $proc.Id | Set-Content -Path $PidFile -Encoding ASCII
    Write-Host "[start] Server PID $($proc.Id) written to $PidFile" -ForegroundColor Green
    Write-Host "[start] Logs: $LogFile" -ForegroundColor Green

    if ($OpenBrowser) {
        Start-Sleep -Seconds 2
        Start-Process "http://localhost:$Port/"
    }
} else {
    Write-Host "[start] Starting server on http://127.0.0.1:$Port/ (foreground — Ctrl+C to stop)..." -ForegroundColor Cyan

    if ($OpenBrowser) {
        # Launch browser after a delay in a background job
        $url = "http://localhost:$Port/"
        Start-Job -ScriptBlock {
            param($u) Start-Sleep -Seconds 2; Start-Process $u
        } -ArgumentList $url | Out-Null
    }

    Push-Location $ProjectRoot
    try {
        # Run uvicorn; capture PID then clean up on exit
        $proc = Start-Process -FilePath "uv" `
                              -ArgumentList $uvicornArgs `
                              -WorkingDirectory $ProjectRoot `
                              -PassThru -NoNewWindow

        $proc.Id | Set-Content -Path $PidFile -Encoding ASCII

        # Wait for the process (Ctrl+C will interrupt Wait-Process)
        try {
            $proc | Wait-Process
        } catch [System.OperationCanceledException] {
            # Ctrl+C
        } finally {
            if (Test-Path $PidFile) { Remove-Item $PidFile -Force -ErrorAction SilentlyContinue }
        }
    } finally {
        Pop-Location
    }
}
