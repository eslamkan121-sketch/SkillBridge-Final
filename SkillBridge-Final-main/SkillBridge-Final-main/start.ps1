# SkillBridge startup for Windows PowerShell (VS Code integrated terminal).
# Runs the same cross-platform Node runner as `npm start`.
#
#   .\start.ps1            start the app (setup + build + run) on http://localhost:8000
#   .\start.ps1 --dev      run the Vite dev server for live frontend reload
#   .\start.ps1 --reset    delete the database so it re-seeds
#   .\start.ps1 --setup-only  install dependencies then exit
#
# If this is the first run and your policy blocks scripts, run once:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$node = (Get-Command node -ErrorAction SilentlyContinue).Source
if (-not $node) {
    Write-Host "Node.js is required to run SkillBridge. Install Node.js 18+ and try again." -ForegroundColor Red
    exit 1
}
Push-Location $root
try {
    & node scripts/start.mjs @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
