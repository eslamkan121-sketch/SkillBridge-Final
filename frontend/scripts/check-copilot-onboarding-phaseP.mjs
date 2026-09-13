// Phase P — Copilot onboarding + settings picker — frontend source-contract guard.
// Covers: onboarding modal + settings picker read archetype/quiz data ONLY from
// lib/copilotArchetypes.ts; each component calls ONLY its own api.* pair (no
// provider/tutor/learning/jobs calls, no localStorage); the four mentors
// (Nova / Axel / Sage / Vex) are the ONLY outcomes — old archetype names
// (navigator/strategist/confidant) never surface in the UI; the welcome screen
// offers "Get matched" (quiz) or "Choose my mentor" (direct pick via
// api.setCopilot); the result preview tallies deterministically (mirror of the
// backend recompute); finish submits the answer set (authority stays
// server-side); forceOpen lets settings re-open the quiz after completion;
// App wires both modals gated to Students, with the "Change your copilot"
// menu entry and the retake-quiz bridge.

import { readProject } from './path-helpers.mjs'

const read = readProject

const problems = []
const ok = (cond, msg) => { if (!cond) problems.push(msg) }

const QUESTION_COUNT = 4
const KEYS = ['nova', 'axel', 'sage', 'vex']

const modulePath = 'frontend/src/lib/copilotArchetypes.ts'
const lib = read(modulePath)
const types = read('frontend/src/lib/types.ts')
const api = read('frontend/src/lib/api.ts')
const onboarding = read('frontend/src/components/CopilotOnboarding.tsx')
const settings = read('frontend/src/components/CopilotSettingsModal.tsx')
const app = read('frontend/src/App.tsx')
const css = read('frontend/src/index.css')

// ---- 0. Old archetype names never surface in the UI layer.
for (const [name, src] of [['lib', lib], ['onboarding', onboarding], ['settings', settings]]) {
  ok(!/navigator|strategist|confidant/.test(src), `${name} contains no old archetype names`)
}
ok(!/Navigator|Strategist|Confidant/.test(onboarding) && !/Navigator|Strategist|Confidant/.test(settings),
   'onboarding+settings never show the old archetype names')

// ---- 1. lib/copilotArchetypes.ts is the single archetype/quiz source.
for (const sym of ['COPILOT_ARCHETYPE_KEYS', 'COPILOT_ARCHETYPES', 'COPILOT_QUESTIONS',
  'DEFAULT_COPILOT_ARCHETYPE', 'tallyAnswers', 'buildRecommendationReason']) {
  ok(new RegExp(`export (const|function) ${sym}`).test(lib), `${sym} exported from copilotArchetypes.ts`)
}
ok(new RegExp(`COPILOT_ARCHETYPE_KEYS\\s*=\\s*\\['${KEYS.join("', '")}'\\]`).test(lib),
   'exactly the four mentor keys, in order')
ok(/export const COPILOT_ARCHETYPES: Record<CopilotArchetypeKey, CopilotArchetype>/.test(lib),
   'archetype metadata is keyed by the canonical key union')
ok(/export const COPILOT_QUESTIONS: CopilotQuestion\[\]/.test(lib)
   && (lib.match(/^\s+question: '/gm) || []).length === QUESTION_COUNT,
   'exactly four quiz questions are declared')
ok((lib.match(/vote: '/g) || []).length === QUESTION_COUNT * 4,
   'each question carries four options that vote for a mentor key')

// ---- 2. Components import archetype data ONLY from the module (never options/tutor).
ok(/from '\.\.\/lib\/copilotArchetypes'/.test(onboarding), 'onboarding reads from copilotArchetypes')
ok(/from '\.\.\/lib\/copilotArchetypes'/.test(settings), 'settings reads from copilotArchetypes')
for (const [name, src] of [['onboarding', onboarding], ['settings', settings]]) {
  ok(/import \{ api \} from '\.\.\/lib\/api'/.test(src),
     `${name} uses the api helper module (never a raw fetch)`)
  ok(!/fetch\(/.test(src), `${name} performs no raw fetch`)
  ok(!/localStorage/.test(src), `${name} never touches browser-side persistent storage`)
  ok(!/window\.open/.test(src), `${name} never window.open`)
  ok(!/tutorProfiles|TUTOR_PROFILES|learning'/.test(src), `${name} never reads tutor/learning providers`)
}

// ---- 3. Each component only calls its own api.* helpers.
ok(/api\.copilotOnboardingState\(studentId\)/.test(onboarding)
   && /api\.submitCopilotOnboarding\(studentId, \{ answers \}\)/.test(onboarding)
   && /api\.setCopilot\(studentId, key\)/.test(onboarding),
   'onboarding calls only its state + submit + direct-choice helpers')
ok(!/api\.(copilotConfig|tutor|learning|recentJobs|updateStudent|createRole|updateRole|submitDiagnostic)/.test(onboarding),
   'onboarding never calls config/tutor/learning/jobs/student-write helpers (except the direct setCopilot choice)')
ok(/api\s*\.copilotConfig\(studentId\)/.test(settings) && /api\s*\.setCopilot\(studentId, pick\)/.test(settings),
   'settings calls only its config + set helpers')
ok(!/api\.(copilotOnboardingState|submitCopilotOnboarding|tutor|learning|recentJobs|updateStudent)/.test(settings),
   'settings never calls onboarding/tutor/learning/jobs/student-write helpers')

// ---- 4. Welcome screen contract: "Get matched" quiz vs "Choose my mentor".
ok(/Find your SkillBridge mentor/.test(onboarding), 'welcome titles the mentor flow')
ok(/Get matched/.test(onboarding), 'primary welcome action is Get matched')
ok(/Choose my mentor/.test(onboarding), 'welcome offers the direct Choose my mentor path')
ok(!/Skip for now/.test(onboarding), 'there is no "Skip for now" fallback')

// ---- 5. Finish submits the answer set; the result preview tallies the mirror.
ok(/submitCopilotOnboarding\(studentId, \{ answers \}\)/.test(onboarding),
   'finish submits the answer set to the submit helper')
ok(/tallyAnswers\(answers\)/.test(onboarding), 'result preview tallies deterministically')
ok(/Start with \{result\.name\}/.test(onboarding), 'primary result action starts with the recommended mentor')
ok(/See all mentors/.test(onboarding), 'result offers See all mentors (override the recommendation)')
ok(/You can switch mentors anytime/.test(onboarding), 'result reminds that switching is always allowed')
ok(/strong match for you/.test(onboarding), 'result states the strong-match line')

// ---- 6. Direct choice calls api.setCopilot (backend marks it manual).
ok(/api\.setCopilot\(studentId, key\)/.test(onboarding),
   'a direct mentor choice goes through setCopilot (manual), never a quiz POST')
ok(/COPILOT_ARCHETYPE_KEYS\.map\(\(key\)/.test(onboarding)
   && /COPILOT_ARCHETYPES\[key\]/.test(onboarding)
   && /shortTraits/.test(onboarding),
   'the choose grid renders all four mentors with their traits')

// ---- 7. forceOpen + props contract.
ok(/forceOpen\?: boolean/.test(onboarding), 'onboarding exposes forceOpen for settings re-run')
ok(/studentId: number/.test(onboarding) && /studentId: number/.test(settings), 'components take studentId')

// ---- 8. Accessibility signals.
ok(/role="dialog"/.test(onboarding) && /aria-modal="true"/.test(onboarding), 'onboarding is a dialog')
ok(/aria-pressed/.test(onboarding), 'onboarding options expose aria-pressed')
ok(/aria-live="polite"/.test(onboarding) && /role="status"/.test(onboarding), 'onboarding announces progress')
ok(/Question \$\{progress\} of \$\{COPILOT_QUESTIONS\.length\}/.test(onboarding), 'progress label announces the count')
ok(/aria-live="polite"/.test(settings) || /role="status"/.test(settings), 'settings announces loading')
ok(/aria-label=.Find your SkillBridge mentor|aria-label="Find your SkillBridge mentor"/.test(onboarding),
   'onboarding dialog has a label')

// ---- 9. App wiring: gated mounts, menu entry, retake bridge.
ok(/import CopilotOnboarding from '\.\/components\/CopilotOnboarding'/.test(app)
   && /import CopilotSettingsModal from '\.\/components\/CopilotSettingsModal'/.test(app),
   'App imports both components')
ok(/<CopilotOnboarding\b/.test(app) && /<CopilotSettingsModal\b/.test(app), 'App mounts both components')
ok(/role === 'Student' && !assessmentActive/.test(app) && /!authBanner/.test(app),
   'mounts are gated to a Student who is not mid-assessment and past the auth success overlay')
ok(/Change your copilot/.test(app), 'user menu exposes "Change your copilot"')
ok(/onRetakeQuiz=\{\(\) => \{ setCopilotSettingsOpen\(false\); setCopilotOnboardingForce\(true\) \}\}/.test(app),
   'Retake the quiz bridges to the onboarding forceOpen')
ok(/const studentId = role === 'Student' \? \(session\.student\?\.id \?\? 0\) : 0/.test(app),
   'studentId resolves from session.student (creates no new plumbing)')

// ---- 10. Styles exist.
for (const cls of ['.cob-backdrop', '.cob-shell', '.cob-progress', '.cob-seg', '.cob-option',
  '.cob-portrait', '.cob-avatar', '.cob-match-line', '.cob-reason', '.cob-mentor-grid',
  '.cob-mentor-card', '.csm-backdrop', '.csm-shell', '.csm-card', '.csm-avatar']) {
  ok(css.includes(cls), `style ${cls} exists`)
}

function COPILOT_QUESTION_COUNT() {
  return QUESTION_COUNT
}

if (problems.length) {
  console.error('Phase P copilot-onboarding contracts violated:')
  for (const p of problems) console.error('  - ' + p)
  process.exit(1)
}
console.log('Copilot onboarding + settings (Phase P) contracts OK')