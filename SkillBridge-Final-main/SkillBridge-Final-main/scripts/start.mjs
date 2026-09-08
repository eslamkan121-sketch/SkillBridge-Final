#!/usr/bin/env node
// SkillBridge cross-platform startup.
//
// Works on Windows (PowerShell / cmd / Git Bash) and macOS / Linux with a
// single command because it runs on Node.js, which is already required for
// the frontend. The backend (uvicorn) runs as a foreground child process, so
// logs stream live and Ctrl+C stops it -- giving you full control.
//
//   npm start                 start the app (setup + build + run)
//   node scripts/start.mjs     same as above
//
// Options:
//   --reset        delete backend/skillbridge.db so it re-seeds
//   --port 8001    run the backend on a specific port (default 8000)
//   --no-build     skip the frontend install + build (if already built)
//   --dev          run the Vite dev server instead of the built frontend
//   --setup-only   install dependencies then exit (skips starting the server)
import { spawn, spawnSync } from 'node:child_process'
import { existsSync, readFileSync, rmSync } from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { ROOT, log, ensureVenv, npmCmd, run } from './lib.mjs'

const args = new Set(process.argv.slice(2))
const RESET = args.has('--reset')
const NO_BUILD = args.has('--no-build')
const DEV = args.has('--dev')
const SETUP_ONLY = args.has('--setup-only')

let PORT = parseInt(process.env.SKILLBRIDGE_PORT || '8000', 10)
const portIdx = process.argv.indexOf('--port')
if (portIdx !== -1 && process.argv[portIdx + 1]) {
  PORT = parseInt(process.argv[portIdx + 1], 10)
}

async function portInUse(port) {
  const net = await import('node:net')
  return await new Promise((resolve) => {
    const s = net.createConnection({ host: '127.0.0.1', port })
    s.on('connect', () => {
      s.destroy()
      resolve(true)
    })
    s.on('error', () => resolve(false))
  })
}

function isWsl() {
  if (os.platform() !== 'linux') return false
  if (/\bmicrosoft\b/i.test(os.release())) return true
  try {
    return /microsoft/i.test(readFileSync('/proc/version', 'utf8'))
  } catch {
    return false
  }
}

// On WSL, files under a Windows mount (/mnt/c) often lose their executable bit,
// which breaks `tsc` (and other .bin shims) during the frontend build with
// "Permission denied". Restore the executable bit on every CLI shim inside
// node_modules so the build works seamlessly regardless of where the repo lives.
function fixWslExecPermissions() {
  if (!isWsl()) return
  const binDir = path.join(ROOT, 'frontend', 'node_modules', '.bin')
  if (!existsSync(binDir)) return
  log('WSL detected: restoring executable permissions on frontend/node_modules/.bin')
  spawnSync('chmod', ['-R', '+x', binDir], { stdio: 'ignore' })
}

async function main() {
  fixWslExecPermissions()
  if (RESET) {
    const db = path.join(ROOT, 'backend', 'skillbridge.db')
    if (existsSync(db)) {
      rmSync(db)
      log('Deleted backend/skillbridge.db (will re-seed on next start)')
    }
  }

  const venvPy = ensureVenv()
  log('Installing backend dependencies')
  run(venvPy, ['-m', 'pip', 'install', '--quiet', '-r', path.join(ROOT, 'backend', 'requirements.txt')])

  if (!DEV) {
    const nodeModules = path.join(ROOT, 'frontend', 'node_modules')
    if (!existsSync(nodeModules)) {
      log('Installing frontend dependencies')
      run(npmCmd(), ['install', '--silent'], { cwd: path.join(ROOT, 'frontend') })
    }
    const dist = path.join(ROOT, 'frontend', 'dist')
    if (!existsSync(dist) || !NO_BUILD) {
      log('Building frontend')
      run(npmCmd(), ['run', 'build'], { cwd: path.join(ROOT, 'frontend') })
    }
  }

  if (SETUP_ONLY) {
    log('Setup complete. Run `npm start` to start the app.')
    return
  }

  if (!process.env.SKILLBRIDGE_PORT && !args.has('--port') && (await portInUse(PORT))) {
    for (const candidate of [8001, 8002, 8003, 8004, 8005, 9000]) {
      if (!(await portInUse(candidate))) {
        PORT = candidate
        log(`Port 8000 is in use; using http://localhost:${PORT} instead`)
        break
      }
    }
  }

  const backend = (port) =>
    spawn(venvPy, ['-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', String(port)], {
      cwd: path.join(ROOT, 'backend'),
      stdio: 'inherit',
    })

  if (DEV) {
    log('SkillBridge ready')
    log(`  Backend:  http://localhost:${PORT}`)
    log(`  Frontend: http://localhost:5173 (Vite dev server with live reload)`)
    backend(PORT)
    spawn(npmCmd(), ['run', 'dev'], { cwd: path.join(ROOT, 'frontend'), stdio: 'inherit' })
  } else {
    log('SkillBridge ready')
    log(`  Open: ${`http://localhost:${PORT}`}`)
    log('  Stop:  press Ctrl+C')
    backend(PORT)
  }
}

main().catch((err) => {
  process.stderr.write(`\nStartup failed: ${err && err.message ? err.message : err}\n`)
  process.exit(1)
})
