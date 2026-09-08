// Learning Phase 3 Adaptive Remediation contract guard.
// Low Practice scores (<70) generate a Personalized Review with a new targeted
// example and follow-up task; the follow-up task is resolved server-side from
// the persisted source attempt, never accepted from the frontend.

import { readProject } from './path-helpers.mjs'

const read = readProject

const problems = []
const ok = (cond, msg) => { if (!cond) problems.push(msg) }

const api = read('frontend/src/lib/api.ts')
const types = read('frontend/src/lib/types.ts')
const learning = read('frontend/src/pages/LearningPage.tsx')
const evaluator = read('backend/app/practice.py')
const main = read('backend/app/main.py')
const models = read('backend/app/models.py')

ok(/interface RemediationReview/.test(types),
   'types.ts: RemediationReview shape exists')
ok(/focus_points: string\[\]/.test(types),
   'types.ts: remediation carries focus_points')
ok(/follow_up_task/.test(types) && /targeted_example/.test(types),
   'types.ts: follow_up_task and targeted_example are part of the remediation contract')
ok(/remediation\?: RemediationReview \| null/.test(types),
   'types.ts: PracticeAttempt carries the remediation review')
ok(/practice_task\?: PracticeTask \| null/.test(types) && /source_attempt_id: number \| null/.test(types),
   'types.ts: the answered practice task (lesson or remediation) is stored')

ok(/practice_task_source_attempt_id/.test(api),
   'api.ts: follow-up submission can reference a persisted source attempt (trusted task)')

ok(/Personalized Review/.test(learning) && /Focus on/.test(learning),
   'LearningPage: Personalized Review shows focus points')
ok(/Explanation/.test(learning) && /Targeted Example/.test(learning),
   'LearningPage: Personalized Review explains and gives a new example')
ok(/Try This Next/.test(learning) && /followUpAnswer/.test(learning),
   'LearningPage: follow-up task is presented and answered')
ok(/Ready for Mini Check/.test(learning),
   'LearningPage: ready Practice shows the Mini Check gate without a lock')
ok(/followUpSourceAttemptId/.test(learning),
   'LearningPage: follow-up answer is sent against the trusted source attempt')
ok(!/api\.personalizedPathProgress/.test(learning),
   'LearningPage: Student UI still has no manual personalized-path completion call')

ok(/generate_remediation/.test(evaluator) && /PRACTICE_READY_THRESHOLD/.test(evaluator),
   'practice.py: remediation is gated to low Practice scores')
ok(/fallback_remediation/.test(evaluator) && /REMEDIATION_FALLBACK_NOTICE/.test(evaluator),
   'practice.py: deterministic labelled remediation fallback exists')
ok(/remediation_practice_task/.test(evaluator) && /follow_up_task/.test(evaluator),
   'practice.py: new follow-up task is derived from the saved remediation')
ok(/"source": "fallback"/.test(evaluator) && /"source": "ai"/.test(evaluator),
   'practice.py: remediation source is explicit in both paths')

ok(/_practice_task_for_submission/.test(main) && /get_practice_attempt/.test(main),
   'main.py: follow-up task is resolved from trusted persisted data')
ok(/remediation_practice_task/.test(main),
   'main.py: server loads the saved follow-up task for evaluation')
ok(/remediation=remediation/.test(main),
   'main.py: generated remediation is persisted with the attempt')

ok(/remediation_json/.test(models) && /create_practice_attempt/.test(models),
   'models.py: remediation persists on the practice attempt')

if (problems.length) {
  console.error('Learning Phase 3 Adaptive Remediation contract violations:')
  for (const problem of problems) console.error(`  - ${problem}`)
  process.exit(1)
}
console.log('Learning Phase 3 Adaptive Remediation contracts OK')
