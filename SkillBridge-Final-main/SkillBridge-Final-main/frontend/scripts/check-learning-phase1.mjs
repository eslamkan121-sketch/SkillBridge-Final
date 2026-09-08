// Learning Phase 1 frontend contract guard. This keeps the Student Learning
// entrypoint canonical: Diagnostic -> Personalized Path -> Lesson -> Mini Check.

import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..')
const read = (p) => readFileSync(resolve(root, p), 'utf8')

const problems = []
const ok = (cond, msg) => { if (!cond) problems.push(msg) }

const api = read('frontend/src/lib/api.ts')
const learning = read('frontend/src/pages/LearningPage.tsx')
const components = read('frontend/src/components/learning.tsx')
const assessments = read('frontend/src/pages/AssessmentsPage.tsx')
const css = read('frontend/src/index.css')

// Start Learning must route to the diagnostic/personalized-path flow, not the
// legacy generated learning item endpoint.
ok(/const startLearning = \(skillId: number\)/.test(learning),
   'LearningPage: startLearning entrypoint exists')
ok(/setLearningStart/.test(learning),
   'LearningPage: Start Learning emits a flow signal')
ok(!/api\.generateLearning/.test(learning),
   'LearningPage: Start Learning no longer calls the legacy generateLearning endpoint')
ok(/startSignal=\{startSignal\}/.test(learning),
   'LearningPage: startSignal reaches the personalized path panel')
ok(/function DiagnosticPanel\([^)]*startSignal/.test(learning),
   'LearningPage: DiagnosticPanel accepts the Start Learning signal')
ok(/phase !== 'browse'/.test(learning) && /api\.generateDiagnostic/.test(learning),
   'LearningPage: fresh Start Learning enters diagnostic generation')
ok(/function PersonalizedPathPanel\([^)]*startSignal/.test(learning),
   'LearningPage: PersonalizedPathPanel accepts the Start Learning signal')
ok(/openCurrentTopic/.test(learning),
   'LearningPage: existing personalized paths resume a current topic')
ok(/create\(true\)/.test(learning) && /api\.generatePersonalizedPath/.test(learning),
   'LearningPage: completed diagnostics can create and open a personalized path')

// Personalized topic completion must be Mini Check driven in the Student UI.
ok(!/api\.personalizedPathProgress/.test(learning),
   'LearningPage: Student UI does not call manual personalized path progress updates')
ok(!/pp-check/.test(learning) && !/\.pp-check/.test(css),
   'LearningPage/CSS: manual personalized path checkbox UI is absent')
ok(/api\.lessonStart/.test(learning),
   'LearningPage: opening a lesson marks the topic in progress through the existing lesson API')
ok(/api\.lessonMiniCheck/.test(learning),
   'LearningPage: Mini Check remains the topic completion path')
ok(/Topics complete only after a Mini Check pass/.test(learning),
   'LearningPage: progress copy states the Mini Check completion rule')
ok(/This does not create a Verified Skill/.test(learning),
   'LearningPage: progress copy preserves Assessment-only verification')

// Visible progress and states should be path-topic based, not old roadmap based.
ok(/topicProgressFor/.test(components),
   'learning components: topicProgressFor exists')
ok(/topics completed/.test(components),
   'learning components: primary LearningProgress says topics completed')
ok(!/roadmap steps completed/.test(components),
   'learning components: primary progress no longer says roadmap steps completed')
for (const label of ['Not started', 'In progress', 'Completed', 'Skipped / Already mastered']) {
  ok(learning.includes(label), `LearningPage: visible topic state "${label}" exists`)
}
ok(/pp-status-developing/.test(css) && /pp-status-mastered/.test(css),
   'index.css: developing and mastered/skipped topics have distinct styles')

// Keep backend compatibility and the Assessment rule unchanged.
ok(/generateLearning:/.test(api),
   'api.ts: legacy generateLearning remains available for compatibility')
ok(/personalizedPathProgress:/.test(api),
   'api.ts: manual progress API wrapper remains available for compatibility')
ok(!/final-assessment\/status/.test(assessments),
   'AssessmentsPage: Final Assessment remains ungated by Learning readiness')
ok(/always\s+available from the Assessments page/.test(learning),
   'LearningPage: readiness is informational and assessment remains available')

if (problems.length) {
  console.error('Learning Phase 1 frontend contract violations:')
  for (const problem of problems) console.error(`  - ${problem}`)
  process.exit(1)
}
console.log('Learning Phase 1 frontend contracts OK')
