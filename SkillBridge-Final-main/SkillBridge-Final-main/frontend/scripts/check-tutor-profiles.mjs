#!/usr/bin/env node
// Phase 5.5 Step 3 — checks the SINGLE canonical tutor profile source
// (frontend/src/lib/tutorProfiles.ts) directly, since there is no JS test
// runner in this repo. Runs as part of backend/tests/test_tutor_profiles.py.
//
// Exit 0 on success, 1 with a message on failure. No paid APIs, no network.

import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ts = require(path.join(__dirname, '..', 'node_modules', 'typescript'))
const srcPath = path.join(__dirname, '..', 'src', 'lib', 'tutorProfiles.ts')

const source = readFileSync(srcPath, 'utf8')
const js = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText

let exportsHolder = {}
const module = { exports: exportsHolder }
new Function('exports', 'module', 'require', js)(module.exports, module, (id) => {
  throw new Error(`unexpected require(${id}) in canonical profile module`)
})
const { TUTOR_PROFILES: profiles } = module.exports

const ok = (cond, msg) => {
  if (!cond) {
    console.error(`FAIL: ${msg}`)
    process.exitCode = 1
  }
}

// 1. all four Tutor profiles exist
const ids = profiles.map((p) => p.id)
const EXPECTED = [
  ['nova', 'Nova', 'London, United Kingdom', 'Learn & Explain'],
  ['axel', 'Axel', 'California, United States', 'Practice & Build'],
  ['sage', 'Sage', 'Alexandria, Egypt', 'Discuss & Think'],
  ['vex', 'Vex', 'Paris, France', 'Test & Interview'],
]
ok(ids.length === 4, `expected 4 profiles, got ${ids.length}`)
for (const [id, name, origin, specialty] of EXPECTED) {
  // 2. each Tutor ID maps to exactly one profile (array has no duplicates)
  ok(ids.filter((x) => x === id).length === 1, `profile ${id} must be unique`)
  const p = profiles.find((x) => x.id === id) || {}
  ok(p.name === name, `${id}: name should be ${name}, got ${p.name}`)
  // 3. correct origin
  ok(p.origin === origin, `${id}: origin should be ${origin}, got ${p.origin}`)
  // 4. correct specialty
  ok(p.specialty === specialty, `${id}: specialty should be ${specialty}, got ${p.specialty}`)
  // 5. traits are non-empty
  ok(Array.isArray(p.traits) && p.traits.length > 0, `${id}: traits must be non-empty`)
  // 6. bestFor is non-empty
  ok(Array.isArray(p.bestFor) && p.bestFor.length > 0, `${id}: bestFor must be non-empty`)
  // 7. languages contains English and Arabic
  ok(Array.isArray(p.languages) && p.languages.includes('English'), `${id}: languages must include English`)
  ok(Array.isArray(p.languages) && p.languages.includes('Arabic'), `${id}: languages must include Arabic`)
  // 8. avatar mapping still works (a real asset path per tutor)
  ok(typeof p.avatar === 'string' && p.avatar.startsWith('/assets/tutors/') && p.avatar.endsWith('.png'),
    `${id}: avatar should point at /assets/tutors/{id}.png, got ${p.avatar}`)
  // voice metadata survives (used by TTS; ids must not change)
  ok(typeof p.voiceId === 'string' && p.voiceId.length > 0, `${id}: voiceId must be present`)
}

const unique = new Set(ids)
ok(unique.size === ids.length, 'all Tutor IDs must be distinct')

if (process.exitCode) {
  process.exit(1)
}
console.log(`OK: ${profiles.length} tutor profiles verified against ${path.relative(process.cwd(), srcPath)}`)