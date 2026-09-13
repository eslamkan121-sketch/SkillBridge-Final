// Vex chat-mode guard. The live FAIL: selecting Vex and typing a normal chat
// message produced interview framing ("Acceptable start. Now go deeper...",
// "Explain DNS to me..." reversed). Root cause was the frontend: Vex's chat
// default was the interviewing 'interview' mode, and every tutor-select
// persisted that mode, so every fresh Vex chat sent mode:'interview' on /tutor
// where the backend (correctly) routed it to the interview engine. This checker
// inspects the real frontend sources and fails whenever the contract regresses.

import { readProject } from './path-helpers.mjs'

const read = readProject

const problems = []
const ok = (cond, msg) => { if (!cond) problems.push(msg) }

const learning = read('frontend/src/components/learning.tsx')
const appContext = read('frontend/src/AppContext.tsx')
const panel = read('frontend/src/components/CopilotPanel.tsx')
const api = read('frontend/src/lib/api.ts')

// 1. TUTOR_DEFAULT_MODES: Vex is a chat tutor by default, exactly like Nova.
const vexLine = learning.match(/vex:\s*'(chat|interview|practice|discuss)'/)
ok(vexLine && vexLine[1] === 'chat',
   'Vex: TUTOR_DEFAULT_MODES.vex must be \'chat\' (was the \'interview\' that broke fresh Vex chat)')
ok(/(nova|axel|sage|vex):\s*'chat'|,(?:\n|\s|\/\*|\/\/|\{)*\s*vex:\s*'chat'/.test(learning),
   'Vex: default mode is defined in TUTOR_DEFAULT_MODES')

// 2. setTutorId never persists 'interview' as a standing preference; it saves
// a chat-capable mode instead.
ok(/mode:\s*natural === 'interview' \? 'chat' : natural/.test(appContext),
   'AppContext: setTutorId must persist natural==="interview" as \'chat\', never a standing interview mode')
ok(/tutor_id: id, mode:/.test(appContext),
   'AppContext: setTutorId persists { tutor_id, mode }')

// 3. setMode still refuses to persist an interview mode.
ok(/mode !== 'interview'/.test(appContext) || /natural !== 'interview'/.test(appContext) ||
   /m !== 'interview'/.test(appContext),
   'AppContext: setMode must keep refusing to persist the live session mode')

// 4. Ending an interview restores the tutor\'s working mode (finished AND the
// Return-to-Chat path), so the next composer message is a normal chat.
const restoreCount = (panel.match(/setMode\(prevModeRef\.current === 'interview' \? 'chat' : prevModeRef\.current\)/g) || []).length
ok(restoreCount >= 2, `CopilotPanel: finishInterview + leaveInterview restore the working mode (found ${restoreCount})`)

// 5. The normal composer computes the payload from AppContext state — the mode
// seen by /tutor is mode, never a hardcoded interview literal inside send().
ok(/api\.tutorSend\(studentId, text, \{[\s\S]{0,400}?\btutorId,[\s\S]{0,200}?\bmode,[\s\S]{0,200}?\blanguage,/ .test(panel),
   'CopilotPanel: send() passes { ..., tutorId, mode, language } to api.tutorSend')
ok(/mode: opts\.mode \?\? null/.test(api) && /tutor_id: opts\.tutorId \?\? null/.test(api),
   'api.tutorSend: body carries mode + tutor_id from the caller, not a hardcoded interview')

if (problems.length) {
  console.error('Vex chat-mode contract violations:')
  for (const p of problems) console.error(`  - ${p}`)
  process.exit(1)
}

console.log('Copilot Vex chat-mode contracts OK')