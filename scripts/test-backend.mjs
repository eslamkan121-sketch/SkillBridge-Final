#!/usr/bin/env node
// Cross-platform backend test runner (Windows / macOS / Linux).
// Usage: npm run test:backend   or   node scripts/test-backend.mjs
import path from 'node:path'
import { ROOT, ensureVenv, run } from './lib.mjs'

const venvPy = ensureVenv()
run(venvPy, ['-m', 'pip', 'install', '--quiet', '-r', path.join(ROOT, 'backend', 'requirements.txt')])
run(venvPy, ['-m', 'pytest', 'tests', '-v'], { cwd: path.join(ROOT, 'backend') })
