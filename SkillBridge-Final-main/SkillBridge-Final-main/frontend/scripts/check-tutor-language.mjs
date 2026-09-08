// Step 4 runtime-language guard — verifies the real frontend request path carries
// the selected tutor language on every tutor message (not just the interview).
//
// The live bug: the Copilot replied in English despite العربية being selected,
// because `api.tutorSend` never included `language` in the POST body, so the
// backend had to rely on whatever preference happened to be stored (which could
// be stale/absent). Run by `test_runtime_tutor_language.py` via pytest.
//
// Pre-fix this script exits non-zero. Post-fix it passes.

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const api = readFileSync(join(root, 'frontend', 'src', 'lib', 'api.ts'), 'utf8')
const panel = readFileSync(join(root, 'frontend', 'src', 'components', 'CopilotPanel.tsx'), 'utf8')

const failures = []

// 1. tutorSend must include `language` and `tutor_id` in the JSON POST body.
const bodyLine = 'language: opts.language ?? null'
if (!api.includes(bodyLine)) {
  failures.push(`api.ts tutorSend must include ${JSON.stringify(bodyLine)} in its request body`)
}
const tutorLine = 'tutor_id: opts.tutorId ?? null'
if (!api.includes(tutorLine)) {
  failures.push(`api.ts tutorSend must include ${JSON.stringify(tutorLine)} in its request body`)
}

// 2. CopilotPanel must pass the live selection into api.tutorSend(...).
const callStart = panel.indexOf('api.tutorSend(studentId, text, {')
if (callStart === -1) {
  failures.push('CopilotPanel.tsx no longer calls api.tutorSend(studentId, text, { ... })')
} else {
  const block = panel.slice(callStart, callStart + 400)
  if (!/\blanguage,/.test(block)) {
    failures.push('CopilotPanel.tsx must pass the selected language into api.tutorSend(...)')
  }
  if (!/\btutorId,/.test(block)) {
    failures.push('CopilotPanel.tsx must pass the selected tutorId into api.tutorSend(...)')
  }
}

// 3. The language selector must be wired to the same `language` state.
if (!panel.includes('onClick={() => setLanguage(l)}')) {
  failures.push('CopilotPanel.tsx must expose the Auto/EN/ع selector bound to setLanguage')
}

if (failures.length) {
  console.error('check-tutor-language: FAILED\n  ' + failures.join('\n  '))
  process.exit(1)
}
console.log('check-tutor-language: ok — every tutor request carries the selected language')
