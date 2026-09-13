// Practice Scenarios — Phase 4 UX upgrade — frontend + backend
// source-contract guard.
// Covers: per-decision consequences (never revealed pre-submission), hint
// penalty clarity, results -> learning follow-up, save-and-resume, per-attempt
// history (date/version/score/role), status groups + difficulty filter +
// Recommended Next library, and 390px-safe styling.

import { readProject } from './path-helpers.mjs'

const read = readProject

const problems = []
const ok = (cond, msg) => { if (!cond) problems.push(msg) }

const types = read('frontend/src/lib/types.ts')
const api = read('frontend/src/lib/api.ts')
const page = read('frontend/src/pages/ScenariosPage.tsx')
const css = read('frontend/src/index.css')
const scenarios = read('backend/app/scenarios.py')
const main = read('backend/app/main.py')

// ---- 1. frontend types carry Phase 4 shapes
ok(/interface ScenarioHintPolicy \{[^}]*penalty: number[^}]*cap: number[^}]*used: number[^}]*deduction: number/s.test(types),
   'types.ts defines ScenarioHintPolicy { penalty, cap, used, deduction }')
ok(/interface ScenarioLastDecision /.test(types)
   && /verdict: 'good' \| 'neutral' \| 'bad'/.test(types)
   && /feedback: string/.test(types) && /consequence: string/.test(types),
   'types.ts defines ScenarioLastDecision with verdict/feedback/consequence')
ok(/interface ScenarioFollowUp /.test(types)
   && /skill_id: number \| null/.test(types)
   && /action: 'lesson' \| 'practice' \| 'review'/.test(types),
   'types.ts defines ScenarioFollowUp with a learning/practice action')
ok(/target_role: string \| null/.test(types)
   && /last_decision: ScenarioLastDecision \| null/.test(types)
   && /hint_policy: ScenarioHintPolicy/.test(types),
   'ScenarioPlayer carries target_role, last_decision and hint_policy')
ok(/follow_up: ScenarioFollowUp/.test(types) && /hint_policy: ScenarioHintPolicy/.test(types),
   'ScenarioResult carries follow_up and hint_policy')
ok(/interface ScenarioHistoryEntry /.test(types)
   && /interface ScenarioHistory \{[^}]*attempts: ScenarioHistoryEntry\[\]/s.test(types),
   'types.ts defines ScenarioHistoryEntry + ScenarioHistory')

// ---- 2. api surface
ok(/scenarioHistory: \(studentId: number\) => req<ScenarioHistory>/.test(api),
   'api.ts exposes scenarioHistory')

// ---- 3. library: status groups, difficulty filter, Recommended Next, history
ok(/<ScenarioGroup /.test(page), 'ScenariosPage renders status groups (Not started / In progress / Completed)')
ok(/setDifficulty/.test(page) && /DifficultyFilter/.test(page),
   'ScenariosPage has an explicit difficulty filter')
ok(/Recommended next/.test(page) && /scn-next/.test(page),
   'ScenariosPage renders a Recommended Next panel')
ok(/scn-modal-backdrop/.test(page) && /onDetails=\{setDetail\}/.test(page),
   'ScenariosPage offers a scenario-detail preview before starting')
ok(/HistoryView/.test(page) && /api\.scenarioHistory/.test(page),
   'ScenariosPage has a history view backed by the history endpoint')

// ---- 4. player: no best answer before submission + consequence feedback
ok(/selectedOptions/.test(page) && !/selectedOptions\.includes\(o\.id\).*good/.test(page),
   'decision UI relies on selection state, never on correctness props')
ok(/<span className="scn-decision-icon">\{d\.icon\}<\/span>/.test(page),
   'decision buttons show only labels/icons (no verdict before submission)')
ok(/FeedbackPanel/.test(page) && /Decision explained/.test(page)
   && (/feedback\.consequence/.test(page) || /What happens next/.test(page)),
   'player explains consequence + reasoning after a decision (interstitial)')
ok(/Save &amp; exit/.test(page),
   'player offers Save & exit that never completes the attempt')
ok((/each hint reduces your score by \{state\.player\.hint_policy\.penalty\}/.test(page))
   || (/each hint costs \{state\.player\.hint_policy\.penalty\}/.test(page)),
   'hint area states the scoring effect of hints')
ok(/hint_policy\.deduction > 0/.test(page),
   'player surfaces the running hint deduction')

// ---- 5. results: follow-up ties weak competencies to learning
ok(/Recommended follow-up/.test(page) && /fu\.message/.test(page),
   'results render a recommended follow-up tied to the weakest competency')
ok(/Review \{fu\.skill\} in Learning/.test(page)
   && /onNavigate\?\.\('learning', \{ skillId: fu\.skill_id/.test(page),
   'results can open the matching skill in Learning')

// ---- 6. backend: per-decision consequences + hint policy + follow_up + history
ok(/last_decision/.test(scenarios) && /"verdict": last\.get\("verdict"/.test(scenarios)
   && /"consequence": last\.get\("consequence"/.test(scenarios),
   'player_view exposes the last_decision consequence + reasoning')
ok(/def _hint_policy\(/.test(scenarios) && /"penalty": HINT_PENALTY/.test(scenarios)
   && /"cap": HINT_PENALTY_CAP/.test(scenarios),
   'scenarios.py defines an explicit hint penalty policy')
ok(/def _follow_up\(/.test(scenarios) && /action = "lesson"/.test(scenarios)
   && /models\.get_skill_by_name/.test(scenarios),
   'scenarios.py connects weak competencies to skill-based learning content')
ok(/def scenario_history\(/.test(scenarios)
   && /"scenario_version": a\.get\("scenario_version"/.test(scenarios)
   && /"started_at": a\.get\("started_at"/.test(scenarios),
   'scenarios.py provides per-attempt history (version, dates, score, role)')
ok(/@app\.get\("\/api\/students\/\{student_id\}\/scenarios\/history"\)/.test(main)
   && /scenarios\.scenario_history\(student\)/.test(main),
   'main.py exposes GET /scenarios/history')

// ---- 7. 390px mobile safety
ok(/@media \(max-width: 480px\)/.test(css),
   'index.css adds ScenarioPage styles for 390px viewports')

if (problems.length) {
  console.error('Practice Scenarios UX upgrade (Phase 4) contract violations:')
  for (const problem of problems) console.error(`  - ${problem}`)
  process.exit(1)
}
console.log('Practice Scenarios UX upgrade (Phase 4) contracts OK')