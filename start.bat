@echo off
setlocal
cd /d "%~dp0"

where node >nul 2>&1
if errorlevel 1 (
  echo Node.js is required to run SkillBridge. Install Node.js 18+ and try again.
  pause
  exit /b 1
)

echo Starting SkillBridge... (press Ctrl+C to stop)
node scripts/start.mjs %*
pause
