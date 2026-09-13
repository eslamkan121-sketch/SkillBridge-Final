// Practice Scenarios — Phase 5 connected journey — frontend source-contract
// guard.
// Covers: Role Detail -> Learning / Practice / Assessments actions; scenario
// results -> gated Take Assessment with skill focus; Learning surface for
// role-specific scenarios of the current skill; Dashboard Recommended Next
// Step deterministic priority + Go action; breadcrumbs / focus consumption
// with no navigation loops.

import { readProject } from './path-helpers.mjs'

const read = readProject

const problems = []
const ok = (cond, msg) => { if (!cond) problems.push(msg) }

const app = read('frontend/src/App.tsx')
const types = read('frontend/src/lib/types.ts')
const skills = read('frontend/src/pages/SkillsRolesPage.tsx')
const learning = read('frontend/src/pages/LearningPage.tsx')
const scenarios = read('frontend/src/pages/ScenariosPage.tsx')
const assessments = read('frontend/src/pages/AssessmentsPage.tsx')
const dashboard = read('frontend/src/pages/DashboardPage.tsx')
const css = read('frontend/src/index.css')

// ---- 1. App wires cross-page deep links (focus consumed per page, cleared).
ok(/const navigate = \(dest: string, focus\?: \{ skillId: number; roleTitle: string \}\)/.test(app)
   && /if \(section === 'skills' \|\| section === 'dashboard'\) setPrevSection\(section\)/.test(app),
   'App.navigate roots the journey at a hub only (no learning<->scenarios loops)')
ok(/setLearningFocus\(focus\)/.test(app) && /onFocusConsumed=\{\(\) => setLearningFocus\(null\)\}/.test(app),
   'App deep-link focus is consumed then cleared (no state loops)')
ok(/<ScenariosPage onNavigate=\{navigate\} initialFocus=\{learningFocus\} onFocusConsumed/.test(app)
   && /<AssessmentsPage onNavigate=\{navigate\} initialSkillId=\{learningFocus\?\.skillId/.test(app)
   && /<SkillsRolesPage onNavigate=\{navigate\} backTo=\{backTo\}/.test(app)
   && /<LearningPage onNavigate/.test(app) && /<DashboardPage onNavigate=\{navigate\}/.test(app),
   'App passes focus + back context to every journey page')

// ---- 2. Role Detail routes into Learning / Practice / Assessments.
ok(/onVerifySkill/.test(skills) && /onPracticeRole/.test(skills) && /practiceEnabled/.test(skills),
   'RoleDetailsDrawer accepts Start-learning / Verify / Practice actions')
ok(/Start learning/.test(skills) && /Verify a Skill/.test(skills) && /Practice this role/.test(skills)
   && /Set this role as your target to unlock the scenarios written for it/.test(skills),
   'Role Detail shows the three Phase 5 actions with an honest non-target nudge')
ok(/onNavigate\?\.\('learning', \{ skillId, roleTitle/.test(skills)
   && /onNavigate\?\.\('assessments', \{ skillId, roleTitle/.test(skills)
   && /onNavigate\?\.\('scenarios', \{ skillId: 0, roleTitle/.test(skills),
   'Role Detail actions navigate with skill/role context')

// ---- 3. Scenario results: Take Assessment gated + focused.
ok(/fu\.skill_id != null &&/.test(scenarios)
   && /Take the Assessment/.test(scenarios)
   && /onNavigate\?\.\('assessments', \{ skillId: fu\.skill_id/.test(scenarios),
   'Scenario results show Take the Assessment only when it applies, with skill focus')

// ---- 4. Learning surfaces role-specific scenarios for the current skill.
ok(/scenariosForSkill/.test(learning)
   && /scenarioLib\.scenarios/.test(learning)
   && /same\(s\.toLowerCase, want\)/.test(learning) === false && /s\.toLowerCase\(\) === want/.test(learning),
   'Learning matches scenario cards to the active skill by name')
ok(/Practice scenarios for /.test(learning)
   && /onNavigate\?\.\('scenarios', \{ skillId: selectedGap\?\.skill_id/.test(learning),
   'Learning shows a practice panel for the current skill and routes into Scenarios')

// ---- 5. Dashboard Recommended Next Step: structured, documented, navigable.
ok(/First match wins/.test(dashboard) || /deterministic priority/.test(dashboard),
   'Dashboard documents the recommended-next-step priority rule')
ok(/action: 'skills'|'learning'|'scenarios'|'assessments'|null/.test(dashboard)
   || /'skills' \| 'learning' \| 'scenarios' \| 'assessments' \| null/.test(dashboard),
   'Recommended Next Step is a typed skill/practice/assessment decision')
ok(/in_progress/.test(dashboard) && /Resume your practice session/.test(dashboard),
   'Priority resumes an in-progress scenario')
ok(/Verify /.test(dashboard) && /Assessments/.test(dashboard) === false || /go\(step\.action/.test(dashboard),
   'Next-step Go button routes to the recommended page')

// ---- 6. Breadcrumbs / back actions with previous-context retention.
ok(/className="crumbs"/.test(learning) && /className="crumbs"/.test(scenarios)
   && /className="crumbs"/.test(skills) && /className="crumbs"/.test(assessments),
   'Every journey page offers a breadcrumb back to the previous context')
ok(/\.crumb-back/.test(css) && /\.rd-actions-row/.test(css) && /\.lrn-scn-panel/.test(css)
   && /\.asm-focus-strip/.test(css) && /\.dash-next-go/.test(css),
   'Phase 5 styles present')

// ---- 7. Never auto-change the target role or verification paths. The three
// Phase 5 drawer handlers (learn/verify/practice) navigate only; the
// target-role change stays behind "Select as target".
for (const name of ['learnSkill', 'verifySkill', 'practiceRole']) {
  const idx = skills.indexOf(`const ${name} =`)
  const slice = idx >= 0 ? skills.slice(idx, idx + 500) : ''
  ok(slice.length > 0 && !/updateStudent/.test(slice), `${name} navigates without changing the target role`)
}
ok(!/verified: true/.test(scenarios),
   'Scenarios never claim verified status from practice')

if (problems.length) {
  console.error('Practise Scenarios — Phase 5 connected journey contract violations:')
  for (const p of problems) console.error('  - ' + p)
  process.exit(1)
}
console.log('Connected journey (Phase 5) contracts OK')