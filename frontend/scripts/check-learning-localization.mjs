// Curated-learning locale guard: Arabic changes copy direction only, never the
// Learning shell or persisted Mini Check answer values.
import { readProject } from './path-helpers.mjs'

const learning = readProject('frontend/src/pages/LearningPage.tsx')
const css = readProject('frontend/src/index.css')
const problems = []
const ok = (condition, message) => { if (!condition) problems.push(message) }

ok(!/<div className="lesson-view" dir=/.test(learning),
  'lesson shell must not receive RTL direction')
ok(/className="lesson-content" dir=\{ar \? 'rtl' : 'ltr'\}/.test(learning),
  'only lesson text content receives locale direction')
ok(/lesson-content\[dir="rtl"\] pre/.test(css),
  'code blocks stay LTR inside Arabic lesson content')
ok(/localStorage\.getItem\('sb_learning_language'\)/.test(learning)
  && /localStorage\.setItem\('sb_learning_language', learningLanguage\)/.test(learning),
  'selected learning language persists across refresh')
ok(/displayOptions/.test(learning) && /q\.options!\[i\]/.test(learning),
  'translated Mini Check options map by index to canonical answer values')
ok(/revealedMiniHints/.test(learning) && /Need a hint\?/.test(learning),
  'Mini Check hints remain opt-in')

if (problems.length) {
  console.error('Learning localization contract violations:')
  for (const problem of problems) console.error(`  - ${problem}`)
  process.exit(1)
}
console.log('Learning localization contracts OK')
