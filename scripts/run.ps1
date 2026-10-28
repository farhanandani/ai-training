# Demo launcher: venv + backend install (first run), frontend build (if stale), serve on 127.0.0.1:8000.
# Works from any CWD. First-time setup needs internet (pip/npm); afterwards the demo is fully offline.
param([switch]$NoBrowser)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$VenvPy = Join-Path $Backend ".venv\Scripts\python.exe"
$Url = "http://127.0.0.1:8000"

function Invoke-Checked([string]$what, [scriptblock]$cmd) {
    & $cmd
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)" }
}

# 1. backend venv + editable install on first run
if (-not (Test-Path $VenvPy)) {
    Write-Host "Creating backend venv and installing the backend (first run, needs internet)..."
    if (Get-Command py -ErrorAction SilentlyContinue) {
        Invoke-Checked "venv creation" { py -3 -m venv (Join-Path $Backend ".venv") }
    } else {
        Invoke-Checked "venv creation" { python -m venv (Join-Path $Backend ".venv") }
    }
    Invoke-Checked "pip install" { & $VenvPy -m pip install -e $Backend }
}

# 2. frontend build when dist is missing or older than the sources
$DistIndex = Join-Path $Frontend "dist\index.html"
$newest = Get-ChildItem -Path (Join-Path $Frontend "src"), (Join-Path $Frontend "index.html"), (Join-Path $Frontend "package-lock.json"), (Join-Path $Frontend "tailwind.config.js") -Recurse -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
$stale = (-not (Test-Path $DistIndex)) -or ($newest -and $newest.LastWriteTime -gt (Get-Item $DistIndex).LastWriteTime)
if ($stale) {
    Write-Host "Building the frontend..."
    Push-Location $Frontend
    try {
        if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
            Invoke-Checked "npm ci" { npm ci }
        }
        Invoke-Checked "npm run build" { npm run build }
    } finally { Pop-Location }
}

# 3. open the browser once the API answers (background), then 4. serve in the foreground
if (-not $NoBrowser) {
    Start-Job -ScriptBlock {
        param($u)
        for ($i = 0; $i -lt 120; $i++) {
            try { Invoke-WebRequest -UseBasicParsing "$u/api/context" -TimeoutSec 2 | Out-Null; Start-Process $u; break }
            catch { Start-Sleep -Milliseconds 500 }
        }
    } -ArgumentList $Url | Out-Null
}
Write-Host "Serving $Url  (Ctrl+C to stop)"
Push-Location $Backend
try {
    & $VenvPy -m uvicorn app.main:app --host 127.0.0.1 --port 8000
} finally { Pop-Location }
