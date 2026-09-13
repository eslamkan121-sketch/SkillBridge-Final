// Phase 2 persona-specific conversation memory — frontend source-contract guard.
//
// The backend now gives each mentor (nova/axel/sage/vex) its OWN bounded
// conversation memory. For that to be visible and controllable, the real
// frontend request path must be strictly per-tutor:
//
//   1. history is loaded per tutor (tutor_id query param),
//   2. every send carries the ACTIVE tutor_id so the thread lands on that
//      mentor's memory (never a different one),
//   3. New Chat / Clear Chat deletes by the current tutor_id ONLY — which is
//      exactly what lets the backend clear *that mentor's* memory row.
//
// Negative guards: the SPA never keeps a second conversation store in
// localStorage for tutor chat (the backend is the source of truth), and the
// send/clear never reference another tutor id than the active one.
//
// Run by `test_runtime_tutor_memory_phase2_frontend.py` via pytest.

import { readProject } from './path-helpers.mjs'

const api = readProject('frontend/src/lib/api.ts')
const panel = readProject('frontend/src/components/CopilotPanel.tsx')

const failures = []

// 1. Per-tutor history: the query scopes by tutor_id.
if (!api.includes('`/api/students/${studentId}/tutor${tutorId ? `?tutor_id=${encodeURIComponent(tutorId)}` : \'\'}`')) {
  failures.push('api.tutorHistory must scope the request by tutor_id')
}

// 2. Per-tutor clear: DELETE with the explicit tutor_id body (the backend clears
//    only that mentor's messages AND conversation memory).
if (!api.includes('clearTutorChat: (studentId: number, tutorId: string)') ||
    !api.includes('DELETE') ||
    !api.includes('tutor_id: tutorId')) {
  failures.push('api.clearTutorChat must DELETE with a per-tutor { tutor_id } body')
}

// 3. Per-tutor send: the POST body carries the active tutor id.
if (!api.includes("tutor_id: opts.tutorId ?? null")) {
  failures.push('api.tutorSend must send tutor_id from opts.tutorId')
}

// 4. CopilotPanel holds a per-tutor cache and loads it only for the ACTIVE tutor.
if (!panel.includes('if (chats[tutorId]) return')) {
  failures.push('CopilotPanel must cache per tutor (chats[tutorId]) so switch-back restores the same thread')
}
if (!panel.includes('api.tutorHistory(studentId, tutorId)')) {
  failures.push('CopilotPanel must load history for the active tutorId')
}

// 5. New Chat / Clear Chat clears the CURRENT tutor only.
const clearCall = 'await api.clearTutorChat(studentId, tutorId)'
if (!panel.includes(clearCall)) {
  failures.push(`CopilotPanel Clear Chat must call ${JSON.stringify(clearCall)}`)
}
const clearRegion = panel.slice(panel.indexOf(clearCall) - 60, panel.indexOf(clearCall) + 260)
if (/\btutorId\s*!==\s*'?/.test(clearRegion) && /newClearToggle|switchTutor|setTutorId|activeTutorAgent/.test(clearRegion)) {
  failures.push('Clear Chat must not switch the tutor agent while clearing (single-mentor panel invariant)')
}

// 6. Negative guard: the SPA never stores the tutor conversation in
//    localStorage (memory lives server-side in the DB).
if (panel.includes('localStorage') && /chat|thread|tutor_conversation|messages/.test(panel)) {
  failures.push('CopilotPanel must NOT persist tutor conversations to localStorage (backend is source of truth)')
}

// 7. Negative guard: the send call passes the same active `tutorId` variable
//    into api.tutorSend — there is no other tutor selection at the send site.
const sendStart = panel.indexOf('api.tutorSend(studentId, text, {')
if (sendStart === -1) {
  failures.push('CopilotPanel no longer calls api.tutorSend(studentId, text, { ... })')
} else {
  const sendBlock = panel.slice(sendStart, sendStart + 420)
  if (!/\btutorId\b/.test(sendBlock) || /tutorId: ['"]/.test(sendBlock) && !/tutorId\b.*(?!['"])\s*\n/.test(sendBlock)) {
    failures.push('CopilotPanel send must pass the active tutorId variable (not a hard-coded mentor id)')
  }
}

if (failures.length) {
  console.error('check-tutor-memory-phase2: FAILED\n  ' + failures.join('\n  '))
  process.exit(1)
}
console.log('check-tutor-memory-phase2: ok — per-tutor history / send / clear stays wired to the backend memory')