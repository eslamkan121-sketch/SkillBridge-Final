// Learning Phase 4 resource UX contract guard.
// Personalized lessons show concise curated resources without moving Practice
// or Mini Check into the resource system.

import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..')
const read = (p) => readFileSync(resolve(root, p), 'utf8')

const problems = []
const ok = (cond, msg) => { if (!cond) problems.push(msg) }

const types = read('frontend/src/lib/types.ts')
const learning = read('frontend/src/pages/LearningPage.tsx')
const css = read('frontend/src/index.css')

ok(/interface LearningResource/.test(types), 'types.ts: LearningResource exists')
ok(/reason\?: string/.test(types), 'types.ts: resources carry a reason')
ok(/available\?: boolean \| null/.test(types), 'types.ts: resources carry availability')
ok(/status\?: string/.test(types), 'types.ts: resources carry honest status text')
ok(/resources\?: LearningResource\[\] \| null/.test(types), 'types.ts: LessonContent can carry resources')

ok(/Recommended Resources/.test(learning), 'LearningPage: lesson resource section is rendered')
ok(/resourceStatus/.test(learning) && /Status unknown/.test(learning),
   'LearningPage: resource status is honest when unavailable')
ok(/Open resource/.test(learning) && /target="_blank"/.test(learning),
   'LearningPage: resources open as external links')
ok(/resource\.reason/.test(learning), 'LearningPage: resource relevance reason is shown')
ok(/content\.resources/.test(learning), 'LearningPage: lesson resources come from lesson content')
ok(/Submit Practice/.test(learning) && /Mini Check/.test(learning),
   'LearningPage: Practice and Mini Check remain present')

ok(/\.lesson-resource-panel/.test(css), 'index.css: lesson resource panel styling exists')
ok(/\.lesson-resource-card/.test(css), 'index.css: lesson resource cards are styled')
ok(/\.lesson-resource-status\.checked/.test(css)
   && /\.lesson-resource-status\.unavailable/.test(css),
   'index.css: checked and unavailable statuses are distinct')

if (problems.length) {
  console.error('Learning Phase 4 resource contract violations:')
  for (const problem of problems) console.error(`  - ${problem}`)
  process.exit(1)
}
console.log('Learning Phase 4 resource contracts OK')
