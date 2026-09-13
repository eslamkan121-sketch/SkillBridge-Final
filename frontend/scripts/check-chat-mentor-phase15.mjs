// Phase 1.5 — Chat shows only the selected mentor — frontend source-contract guard.
// Covers the normal chat header + the change-mentor flow:
//   - Normal chat renders ONLY the currently selected mentor (avatar, name,
//     traits) and never embeds the four-mentor avatar strip (TutorSelector).
//   - Other mentors appear only in the dedicated change-mentor UI
//     (settings picker "Change your copilot" + onboarding choose grid), which
//     still render all four COPILOT_ARCHETYPE_KEYS.
//   - Selecting a mentor updates the ACTIVE tutor (context setTutorId) so the
//     chat header reflects the change without a reload, and persists via the
//     backend (/copilot PUT + tutor preference), which is restored on the next
//     load (AppContext api.tutorPreference).
//   - Vex never auto-enters Interview mode: default mode stays 'chat' and tutor
//     switches persist a chat-capable mode only.
//   - Conversations are preserved per mentor (chats keyed by TutorId; switching
//     back restores the thread; missing threads load the tutor history).

import { readProject } from './path-helpers.mjs'

const read = readProject

const problems = []
const ok = (cond, msg) => { if (!cond) problems.push(msg) }

const panel = read('frontend/src/components/CopilotPanel.tsx')
const settings = read('frontend/src/components/CopilotSettingsModal.tsx')
const onboarding = read('frontend/src/components/CopilotOnboarding.tsx')
const lib = read('frontend/src/lib/copilotArchetypes.ts')
const ctx = read('frontend/src/AppContext.tsx')
const learning = read('frontend/src/components/learning.tsx')

// ---- 1. Normal chat renders only the selected mentor avatar.
ok(!/<TutorSelector/.test(panel), 'chat panel no longer embeds the 4-avatar TutorSelector strip')
ok(!/TUTOR_PROFILES\.map/.test(panel), 'chat panel renders no per-mentor avatar loop')
ok(!/tutor-card/.test(panel), 'chat panel renders no tutor-card grid (the other mentors are hidden)')
ok(!/setTutorId/.test(panel), 'normal chat has no in-panel mentor-switch affordance')
ok(/copilot-current-avatar/.test(panel), 'chat header renders a single current-mentor avatar')
ok(/src=\{tutor\.avatar\}/.test(panel), 'current-mentor avatar binds the selected tutor')
ok(/tutor\.traits\.slice\(0, 3\)/.test(panel), 'chat header shows the selected mentor traits')
ok(/ui\.copilotBar/.test(panel), 'chat header names the selected mentor + copilot role')

// ---- 2. Change-mentor UI still shows all four.
ok(/COPILOT_ARCHETYPE_KEYS\.map\(\(key\)/.test(settings)
   && /COPILOT_ARCHETYPES\[key\]/.test(settings)
   && /csm-card/.test(settings),
   'settings picker renders all four mentor cards')
ok(/COPILOT_ARCHETYPE_KEYS\.map\(\(key\)/.test(onboarding)
   && /COPILOT_ARCHETYPES\[key\]/.test(onboarding),
   'onboarding choose grid renders all four mentors')
ok(/COPILOT_ARCHETYPE_KEYS\s*=\s*\['nova', 'axel', 'sage', 'vex'\]/.test(lib),
   'the single source defines exactly the four mentor keys')

// ---- 3. Selecting another mentor updates the chat header immediately.
ok(/const \{ setTutorId \} = useApp\(\)/.test(settings) && /setTutorId\(pick\)/.test(settings),
   'settings activates the picked mentor (setTutorId(pick))')
ok(/setTutorId\(key\)/.test(onboarding), 'a direct mentor choice activates the picked mentor')
ok(/setTutorId\(isArchetypeKey\(res\.assigned\) \? res\.assigned : winner\)/.test(onboarding),
   'quiz completion activates the server-assigned mentor')
ok(/const tutor = TUTOR_PROFILES\.find\(\(t\) => t\.id === tutorId\)/.test(panel),
   'the chat header binds the active tutor from tutorId')

// ---- 4. Selection persists and is restored after a refresh.
ok(/api\.setCopilot\(studentId, pick\)/.test(settings)
   && /api\.setCopilot\(studentId, key\)/.test(onboarding),
   'mentor selections persist via the backend /copilot PUT (server is the source of truth)')
ok(/api\.tutorPreference/.test(ctx), 'AppProvider restores the persisted tutor on login')
ok(/setTutorIdState\(resolvedTutor\)/.test(ctx), 'the restored preference drives the active tutorId')

// ---- 5. Vex never auto-enters Interview mode.
ok(/vex: 'chat'/.test(learning), "Vex's default working mode is chat (never auto-interview)")
ok(/natural === 'interview' \? 'chat' : natural/.test(ctx),
   'tutor switches persist a chat-capable mode — no standing interview mode')

// ---- 6. Conversations are preserved per mentor.
ok(/Partial<Record<TutorId, TutorMessage\[\]>>/.test(panel),
   'conversations are stored per mentor (switch preserves each thread)')
ok(/chats\[tutorId\]/.test(panel), 'switching back to a mentor restores their thread')
ok(/api\.tutorHistory\(studentId, tutorId\)/.test(panel),
   'a missing thread loads that mentor history from the backend')

if (problems.length) {
  console.error('Phase 1.5 chat-mentor contracts violated:')
  for (const p of problems) console.error('  - ' + p)
  process.exit(1)
}
console.log('Chat mentor (Phase 1.5) contracts OK')