// Phase 2 / Phase 4A persona-specific conversation memory — frontend source-contract guard.
//
// The backend still supports Phase 2 per-mentor memory for legacy callers, and
// Phase 4A adds first-class conversation rows. The real frontend request path
// must therefore carry both the active tutor id and the active conversation id:
//
//   1. history is loaded by conversation_id (with tutor_id for validation),
//   2. every send carries the ACTIVE tutor_id and conversation_id,
//   3. New Chat creates a new conversation and does not delete the old one,
//   4. Clear Chat deletes the current conversation's messages and memory only.
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

// 1. Conversation history: the query scopes by conversation_id.
if (!api.includes("qs.set('conversation_id', String(conversationId))")) {
  failures.push('api.tutorHistory must scope the request by conversation_id')
}

// 2. Conversation clear: DELETE with explicit tutor_id and conversation_id.
if (!api.includes('clearTutorChat: (studentId: number, tutorId: string, conversationId?: number | null)') ||
    !api.includes('DELETE') ||
    !api.includes('tutor_id: tutorId') ||
    !api.includes('conversation_id: conversationId ?? null')) {
  failures.push('api.clearTutorChat must DELETE with { tutor_id, conversation_id }')
}

// 3. Conversation send: the POST body carries the active tutor id and chat id.
if (!api.includes("tutor_id: opts.tutorId ?? null") ||
    !api.includes("conversation_id: opts.conversationId ?? null")) {
  failures.push('api.tutorSend must send tutor_id and conversation_id')
}

// 4. CopilotPanel holds a conversation cache and restores the ACTIVE chat.
if (!panel.includes('activeConversationId')) {
  failures.push('CopilotPanel must track activeConversationId')
}
if (!panel.includes('Record<number, TutorMessage[]>')) {
  failures.push('CopilotPanel must cache messages by conversation id')
}
if (!/api\.tutorHistory\(studentId, .*activeConversationId/.test(panel)) {
  failures.push('CopilotPanel must load history for the active conversation id')
}
if (!panel.includes('api.newTutorConversation')) {
  failures.push('CopilotPanel New Chat must create a fresh conversation')
}

// 5. Clear Chat clears the CURRENT conversation only.
const clearCall = 'await api.clearTutorChat(studentId, tutorId, conversationId)'
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

// 7. Negative guard: the send call passes the active `tutorId` variable and
//    the active conversation id into api.tutorSend.
const sendStart = panel.indexOf('api.tutorSend(studentId, text, {')
if (sendStart === -1) {
  failures.push('CopilotPanel no longer calls api.tutorSend(studentId, text, { ... })')
} else {
  const sendBlock = panel.slice(sendStart, sendStart + 520)
  if (!/\btutorId\b/.test(sendBlock) || /tutorId: ['"]/.test(sendBlock) && !/tutorId\b.*(?!['"])\s*\n/.test(sendBlock)) {
    failures.push('CopilotPanel send must pass the active tutorId variable (not a hard-coded mentor id)')
  }
  if (!/\bconversationId\b/.test(sendBlock)) {
    failures.push('CopilotPanel send must pass the active conversation id')
  }
}

if (failures.length) {
  console.error('check-tutor-memory-phase2: FAILED\n  ' + failures.join('\n  '))
  process.exit(1)
}
console.log('check-tutor-memory-phase2: ok - tutor + conversation history / send / clear stays wired to backend memory')
