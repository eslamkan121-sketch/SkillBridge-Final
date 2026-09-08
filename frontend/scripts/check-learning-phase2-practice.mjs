// Learning Phase 2 Practice contract guard.
// Practice evaluates and persists feedback, but Mini Check remains completion.

import { readProject } from './path-helpers.mjs'

const read = readProject

const problems = []
const ok = (cond, msg) => { if (!cond) problems.push(msg) }

const api = read('frontend/src/lib/api.ts')
const types = read('frontend/src/lib/types.ts')
const learning = read('frontend/src/pages/LearningPage.tsx')
const css = read('frontend/src/index.css')
const main = read('backend/app/main.py')
const database = read('backend/app/database.py')
const models = read('backend/app/models.py')
const evaluator = read('backend/app/practice.py')
const lessons = read('backend/app/lessons.py')

ok(/interface PracticeAttempt/.test(types),
   'types.ts: PracticeAttempt response shape exists')
ok(/source:\s+PracticeSource/.test(types) && /PracticeSource = 'ai' \| 'fallback'/.test(types),
   'types.ts: practice evaluation source is typed as ai or fallback')
ok(/interface LessonPractice/.test(types) && /task\?:/.test(types),
   'types.ts: lesson practice is exposed as a single practical task')
ok(/lessonPracticeAttempts:/.test(api) && /\/practice`/.test(api),
   'api.ts: practice attempt history endpoint is wired')
ok(/lessonSubmitPractice:/.test(api) && /JSON\.stringify/.test(api) && /\{ answer \}/.test(api),
   'api.ts: practice submission always sends the answer body (plus an optional trusted source attempt id in Phase 3)')

ok(/api\.lessonPracticeAttempts/.test(learning),
   'LearningPage: latest practice attempt is loaded from the backend')
ok(/api\.lessonSubmitPractice/.test(learning),
   'LearningPage: Practice tab submits to the evaluated backend endpoint')
ok(/Submit Practice/.test(learning) && /Evaluating\.\.\./.test(learning),
   'LearningPage: Practice submit button has request loading state')
ok(/Practice Review/.test(learning) && /Strengths/.test(learning) && /Needs improvement/.test(learning),
   'LearningPage: evaluated practice result is visible')
ok(/Try Again/.test(learning) && /previous practice/.test(learning),
   'LearningPage: retry and previous-attempt count are visible')
ok(/Basic automated review/.test(learning),
   'LearningPage: fallback result source is visibly labelled')
ok(/miniAnswers/.test(learning),
   'LearningPage: Mini Check answers are separate from Practice response state')
ok(/practiceData\.task/.test(learning) && /practiceTaskText/.test(learning),
   'LearningPage: practice renders one practical task from lesson content')
ok(/practice-primary-task/.test(learning) && /practice-task-title/.test(learning),
   'LearningPage: Practice is a single applied task card, not a quiz list')
ok(/Apply this concept/.test(learning),
   'LearningPage: legacy practice questions derive an open-ended task')
ok(!/Task \$\{index \+ 1\}/.test(learning) && !/practice-options/.test(learning),
   'LearningPage: numbered MCQ task cards and option lists are gone')
ok(!/api\.personalizedPathProgress/.test(learning),
   'LearningPage: Student UI still has no manual personalized-path completion call')

ok(/learning_practice_attempts/.test(database),
   'database.py: practice attempts table exists')
ok(/create_practice_attempt/.test(models) && /list_practice_attempts/.test(models),
   'models.py: practice attempts persist and read back')
ok(/api_submit_practice/.test(main) && /Practice feedback is informational/.test(main),
   'main.py: dedicated Learning Practice endpoint exists')
ok(/@app\.post\("\/api\/students\/\{student_id\}\/learning\/\{skill_id\}\/lessons\/\{competency\}\/practice"\)/.test(main),
   'main.py: Practice POST route is registered (no 405)')
ok(/@app\.get\("\/api\/students\/\{student_id\}\/learning\/\{skill_id\}\/lessons\/\{competency\}\/practice"\)/.test(main),
   'main.py: Practice attempt-history GET route is registered')
ok(/lessonSubmitPractice:[\s\S]*\{ method: 'POST'/m.test(api)
   && /lessons\/\$\{encodeURIComponent\(competency\)\}\/practice/.test(api)
   && /\{ answer \}/.test(api),
   'api.ts+main.py: frontend POST path/method/body match the backend practice route')
ok(/evaluate_practice/.test(evaluator) && /FALLBACK_NOTICE/.test(evaluator),
   'practice.py: evaluator and labelled fallback exist')
ok(/source": "fallback"/.test(evaluator) && /source": "ai"/.test(evaluator),
   'practice.py: AI and fallback sources are explicit')
ok(/def canonical_practice/.test(lessons) && /"type": "practical"/.test(lessons),
   'lessons.py: practice is normalized to one practical task')
ok(/def _practical_task_fallback/.test(lessons) && /response_type/.test(lessons),
   'lessons.py: deterministic fallback produces a skills-aware practical task')
ok(/def normalize_lesson_practice/.test(lessons) && /normalize_lesson\(/.test(main) && /def normalize_lesson/.test(lessons),
   'lessons+main: legacy lesson practice is normalized on the response path')

if (problems.length) {
  console.error('Learning Phase 2 Practice contract violations:')
  for (const problem of problems) console.error(`  - ${problem}`)
  process.exit(1)
}
console.log('Learning Phase 2 Practice contracts OK')
