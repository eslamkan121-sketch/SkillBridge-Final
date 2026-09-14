// Learning Polish pass — frontend source-contract guard.
// Covers: human-readable topic labels (one reusable helper), fenced multi-line
// example code rendering, practice loading UX + action hierarchy, and the Final
// Assessment milestone wording (available anytime, independent of progress).

import { readProject } from './path-helpers.mjs'

const read = readProject

const problems = []
const ok = (cond, msg) => { if (!cond) problems.push(msg) }

const learning = read('frontend/src/pages/LearningPage.tsx')
const topicLabels = read('frontend/src/lib/topicLabels.ts')
const learnComp = read('frontend/src/components/learning.tsx')
const css = read('frontend/src/index.css')
const lessons = read('backend/app/lessons.py')
const main = read('backend/app/main.py')

// ---- 1. one reusable human-readable topic label helper
ok(/export function humanizeTopicLabel/.test(topicLabels) && /SMALL_WORDS/.test(topicLabels),
   'topicLabels.ts: exports a single reusable humanizeTopicLabel helper with small-word handling')
ok(/import \{ humanizeTopicLabel \} from '\.\.\/lib\/topicLabels'/.test(learning),
   'LearningPage: imports the shared label helper (no ad-hoc per-site replacements)')
ok(/import \{ humanizeTopicLabel \} from '\.\.\/lib\/topicLabels'/.test(learnComp),
   'learning.tsx: ContinueLearningCard uses the shared label helper')
ok((learning.match(/humanizeTopicLabel\(/g) || []).length >= 7,
   'LearningPage: helper applied at breadcrumb, discuss, path items, stages, coverage, mastered chips')
ok(/lesson-breadcrumb">\{skillName\} &gt; \{humanizeTopicLabel\(competency\)\}/.test(learning),
   'LearningPage: breadcrumb renders the humanized competency label')
ok(/plan-comp-name">\{humanizeTopicLabel\(slug\)\}/.test(learning),
   'LearningPage: final-assessment coverage list humanizes slugs')
ok(/pp-status-mastered[\s\S]*\{humanizeTopicLabel\(comp\)\}/.test(learning),
   'LearningPage: mastered/skipped chips humanize competencies')
ok(!/cap\(slug\.replace\(_\/g/.test(learning),
   'LearningPage: the old ad-hoc slug-cap replacement in coverage is gone')

// ---- 2. example code preserves real line breaks (fenced, never collapsed)
ok(/def humanize_competency/.test(lessons) && /def _fence_code_content/.test(lessons)
   && /def normalize_lesson/.test(lessons) && /def _looks_like_code/.test(lessons),
   'lessons.py: backend presentation normalization (humanize + code fencing) exists')
ok(/normalize_lesson\(/.test(main) && !/normalize_lesson_practice\(/.test(main),
   'main.py: lesson API responses run through normalize_lesson')
ok(/def normalize_lesson_practice/.test(lessons) && /= normalize_lesson_practice\(lesson, competency\)/.test(lessons),
   'lessons.py: normalize_lesson extends the existing practice normalization')
ok(/\.lesson-example-content pre \{/.test(css) && /white-space: pre-wrap/.test(css),
   'index.css: fenced example code keeps its line breaks (white-space preserved)')
ok(/background: var\(--sb-midnight-ink\); color/.test(css),
   'index.css: example code blocks have their own readable dark style')

// ---- 3. practice loading UX (real evaluation runs ~10-30s)
ok(/Evaluating your practice\.\.\./.test(learning),
   'LearningPage: evaluation in-flight shows "Evaluating your practice..." status')
ok(/practice-spinner/.test(learning) && /role="status"/.test(learning),
   'LearningPage: in-flight status is a spinner + status text, no fake percentage')
ok(/\{practiceSubmitting \|\| !activePracticeAnswer\.trim\(\) \|\| isCompleted\}/.test(learning),
   'LearningPage: duplicate practice submission is disabled while evaluating')
ok(/value=\{activePracticeAnswer\}/.test(learning)
   && /disabled=\{practiceSubmitting \|\| isCompleted\}/.test(learning),
   'LearningPage: the student\'s answer stays visible during evaluation')
ok(/setPracticeError\(/.test(learning) && /practice-status error/.test(learning)
   && /role="alert"/.test(learning),
   'LearningPage: practice failures render inline (lesson stays open, controls restored)')
ok(/setPracticeSubmitting\(false\)/.test(learning),
   'LearningPage: evaluation finally-block restores the controls')

// ---- 4. practice action hierarchy
ok(/className="btn btn-primary"[\s\S]{0,500}Submit Practice/.test(learning),
   'LearningPage: Submit Practice stays the primary action before submission')
ok(/className="btn btn-primary" onClick=\{retryPractice\}/.test(learning),
   'LearningPage: Try Again is emphasized when review is needed (score below threshold)')
ok(/practiceAttempt\?\.status === 'ready'/.test(learning)
   && /Continue to Mini Check/.test(learning),
   'LearningPage: a ready attempt promotes "Continue to Mini Check" to primary')
ok(/practice-ready-banner/.test(learning) && /Ready for Mini Check/.test(learning),
   'LearningPage: ready practice still shows the "Ready for Mini Check" banner')
ok(/<button className="btn" onClick=\{nextTab\}>Continue<\/button>/.test(learning),
   'LearningPage: Continue is secondary (plain btn) until the practice is ready')
ok(/practiceAttempt &&/.test(learning),
   'LearningPage: practice remains optional (review panel renders only after an attempt)')

// ---- 5. final assessment milestone wording
ok(/isFinalAssess/.test(learning) && /Available anytime/.test(learning)
   && /pp-action-\$\{isDone \? 'done' : 'available'\}/.test(learning) && /pp-action-available/.test(css),
   'LearningPage: Final Assessment milestone chip says "Available anytime" (not UNLOCKED/LOCKED)')
ok(/Independent from learning progress — start it from the Assessments page whenever you are ready\./.test(learning),
   'LearningPage: Final Assessment sub-line explains it is independent of learning progress')
ok(/pp-action-available \{/.test(css) && /\.pp-stage-final/.test(css),
   'index.css: final-assessment "available" chip + stage styling exist')
ok(/lockState = isDone \? 'done' : 'locked'/.test(learning) && /pp-action-locked/.test(css),
   'LearningPage: only the (non-final) Practical Challenge stage stays LOCKED')

if (problems.length) {
  console.error('Learning Polish contract violations:')
  for (const problem of problems) console.error(`  - ${problem}`)
  process.exit(1)
}
console.log('Learning Polish contracts OK')
