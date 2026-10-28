# # Dev mode: uvicorn --reload on :8000 (CORS for localhost:5173) and `npm run dev` (Vite, /api proxied) in two windows.
# Dev mode: uvicorn --reload on :$env:CASHFC_PORT (default 8000; CORS for localhost:5173) and `npm run dev`
# (Vite, /api proxied to the same port) in two windows.
# Works from any CWD. Requires backend\.venv and frontend\node_modules (run scripts\run.ps1 once first).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$VenvPy = Join-Path $Backend ".venv\Scripts\python.exe"
$Port = if ($env:CASHFC_PORT) { $env:CASHFC_PORT } else { "8000" }

if (-not (Test-Path $VenvPy)) { throw "backend\.venv not found; run scripts\run.ps1 once first" }
if (-not (Test-Path (Join-Path $Frontend "node_modules"))) { Push-Location $Frontend; try { npm ci } finally { Pop-Location } }

# $api = "`$env:CASHFC_DEV='1'; Set-Location '$Backend'; & '$VenvPy' -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
# $web = "Set-Location '$Frontend'; npm run dev"
$api = "`$env:CASHFC_DEV='1'; Set-Location '$Backend'; & '$VenvPy' -m uvicorn app.main:app --host 127.0.0.1 --port $Port --reload"
$web = "`$env:CASHFC_PORT='$Port'; Set-Location '$Frontend'; npm run dev"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $api
Start-Process powershell -ArgumentList "-NoExit", "-Command", $web
# Write-Host "API: http://127.0.0.1:8000   UI: http://localhost:5173"
Write-Host "API: http://127.0.0.1:$Port   UI: http://localhost:5173"
