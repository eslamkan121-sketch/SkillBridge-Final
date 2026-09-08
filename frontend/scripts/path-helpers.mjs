import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, resolve, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptDir = dirname(fileURLToPath(import.meta.url))

function ancestors(start) {
  const out = []
  let current = resolve(start)
  while (true) {
    out.push(current)
    const parent = dirname(current)
    if (parent === current) break
    current = parent
  }
  return out
}

function isFrontendRoot(path) {
  return existsSync(join(path, 'package.json')) &&
    existsSync(join(path, 'src')) &&
    existsSync(join(path, 'scripts'))
}

function isBackendRoot(path) {
  return existsSync(join(path, 'app', 'main.py')) &&
    existsSync(join(path, 'tests'))
}

function findNestedBackend(base, maxDepth = 4) {
  const queue = [{ path: base, depth: 0 }]
  const skip = new Set(['.git', '.venv', 'node_modules', 'dist', '.pytest_cache', '__pycache__'])
  while (queue.length) {
    const item = queue.shift()
    if (!item || item.depth > maxDepth) continue
    const candidate = join(item.path, 'backend')
    if (isBackendRoot(candidate)) return candidate
    if (item.depth === maxDepth) continue
    let entries = []
    try {
      entries = readdirSync(item.path, { withFileTypes: true })
    } catch {
      continue
    }
    for (const entry of entries) {
      if (!entry.isDirectory() || skip.has(entry.name)) continue
      const next = join(item.path, entry.name)
      try {
        if (!statSync(next).isDirectory()) continue
      } catch {
        continue
      }
      queue.push({ path: next, depth: item.depth + 1 })
    }
  }
  return null
}

function findFrontendRoot(start = scriptDir) {
  const fromEnv = process.env.SKILLBRIDGE_FRONTEND_ROOT
  if (fromEnv && isFrontendRoot(fromEnv)) return resolve(fromEnv)
  for (const base of ancestors(start)) {
    if (isFrontendRoot(base)) return base
    const candidate = join(base, 'frontend')
    if (isFrontendRoot(candidate)) return candidate
  }
  throw new Error('Could not locate frontend root containing package.json, src, and scripts')
}

function findBackendRoot(start = scriptDir) {
  const fromEnv = process.env.SKILLBRIDGE_BACKEND_ROOT
  if (fromEnv && isBackendRoot(fromEnv)) return resolve(fromEnv)
  for (const base of ancestors(start)) {
    if (isBackendRoot(base)) return base
    const candidate = join(base, 'backend')
    if (isBackendRoot(candidate)) return candidate
    const nested = findNestedBackend(base)
    if (nested) return nested
  }
  throw new Error('Could not locate backend root containing app/main.py and tests')
}

export const frontendRoot = findFrontendRoot()
export const backendRoot = findBackendRoot()

export function readFrontend(path) {
  return readFileSync(resolve(frontendRoot, path), 'utf8')
}

export function readBackend(path) {
  return readFileSync(resolve(backendRoot, path), 'utf8')
}

export function readProject(path) {
  if (path.startsWith('frontend/')) return readFrontend(path.slice('frontend/'.length))
  if (path.startsWith('backend/')) return readBackend(path.slice('backend/'.length))
  return readFileSync(resolve(path), 'utf8')
}
