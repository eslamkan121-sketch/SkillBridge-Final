$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot

Write-Host "==> SkillBridge startup" -ForegroundColor Cyan

# -----------------------------
# Locate Backend
# -----------------------------

$Backend = Join-Path $Root "backend"

if (-not (Test-Path (Join-Path $Backend "app\main.py"))) {
    $Backend = Get-ChildItem $Root -Recurse -Directory -Filter "backend" |
        Where-Object {
            Test-Path (Join-Path $_.FullName "app\main.py")
        } |
        Select-Object -First 1 -ExpandProperty FullName
}

if (-not $Backend) {
    Write-Host "ERROR: Could not find backend\app\main.py" -ForegroundColor Red
    exit 1
}

Write-Host "Backend: $Backend" -ForegroundColor Green


# -----------------------------
# Locate Frontend
# -----------------------------

$Frontend = Join-Path $Root "frontend"

if (-not (Test-Path (Join-Path $Frontend "package.json"))) {
    $Frontend = Get-ChildItem $Root -Recurse -Directory -Filter "frontend" |
        Where-Object {
            Test-Path (Join-Path $_.FullName "package.json")
        } |
        Select-Object -First 1 -ExpandProperty FullName
}

if (-not $Frontend) {
    Write-Host "ERROR: Could not find frontend\package.json" -ForegroundColor Red
    exit 1
}

Write-Host "Frontend: $Frontend" -ForegroundColor Green


# -----------------------------
# Python venv
# -----------------------------

$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Host "==> Creating Python virtual environment" -ForegroundColor Yellow
    py -3.12 -m venv (Join-Path $Root ".venv")
}

if (-not (Test-Path $Python)) {
    Write-Host "ERROR: Python virtual environment could not be created." -ForegroundColor Red
    exit 1
}


# -----------------------------
# Install backend dependencies
# -----------------------------

$Requirements = Join-Path $Backend "requirements.txt"

Write-Host "==> Installing backend dependencies" -ForegroundColor Cyan

& $Python -m pip install --quiet -r $Requirements

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Backend dependency installation failed." -ForegroundColor Red
    exit 1
}


# -----------------------------
# Install frontend dependencies
# -----------------------------

Write-Host "==> Installing frontend dependencies" -ForegroundColor Cyan

Push-Location $Frontend
npm.cmd install
if ($LASTEXITCODE -ne 0) {
    Pop-Location
    Write-Host "ERROR: Frontend dependency installation failed." -ForegroundColor Red
    exit 1
}
Pop-Location


# -----------------------------
# Start Backend
# -----------------------------

Write-Host "==> Starting backend on http://localhost:8000" -ForegroundColor Cyan

Start-Process powershell.exe -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$Backend'; & '$Python' -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
)


# -----------------------------
# Start Frontend
# -----------------------------

Write-Host "==> Starting frontend on http://localhost:5173" -ForegroundColor Cyan

Start-Process powershell.exe -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$Frontend'; npm.cmd run dev"
)


Write-Host ""
Write-Host "SkillBridge started." -ForegroundColor Green
Write-Host "Backend : http://localhost:8000"
Write-Host "Frontend: http://localhost:5173"