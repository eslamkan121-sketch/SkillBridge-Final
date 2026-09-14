// Step 4.5 / Phase 4A — frontend source contract guard (driven by pytest, like
// check-tutor-language.mjs). Verifies the actual browser-side code keeps the
// Step 4.5 FINAL CORRECTION contracts plus Phase 4A conversation UX:
// conversation-id chat history, nondestructive New Chat,
// interview isolation, profile Back to Chat, expand/collapse overlay, chat
// voice (tutor TTS), microphone input, composer Mock Interview, and the
// dedicated assessment exam flow (no readiness gate, Copilot hidden while the
// assessment runs, exit finalization). Fails the run if any contract regresses.

import { readProject } from './path-helpers.mjs'

const read = readProject

const problems = []
const ok = (cond, msg) => { if (!cond) problems.push(msg) }

const api = read('frontend/src/lib/api.ts')
const panel = read('frontend/src/components/CopilotPanel.tsx')
const assessments = read('frontend/src/pages/AssessmentsPage.tsx')
const learning = read('frontend/src/pages/LearningPage.tsx')
const app = read('frontend/src/App.tsx')
const types = read('frontend/src/lib/types.ts')
const css = read('frontend/src/index.css')
const i18n = read('frontend/src/lib/tutorI18n.ts')

// ---- api.ts
ok(/tutorConversations: \(studentId: number/.test(api),
   'api.ts: tutorConversations lists saved chat history')
ok(/newTutorConversation: \(studentId: number, tutorId: string\)/.test(api),
   'api.ts: newTutorConversation creates a nondestructive chat')
ok(/tutorHistory: \(studentId: number, tutorId\?: string, conversationId\?: number \| null\)/.test(api),
   'api.ts: tutorHistory accepts tutorId plus conversationId')
ok(/qs\.set\('conversation_id', String\(conversationId\)\)/.test(api),
   'api.ts: tutorHistory sends the conversation_id query param')
ok(/clearTutorChat: \(studentId: number, tutorId: string, conversationId\?: number \| null\)/.test(api),
   'api.ts: clearTutorChat exists')
ok(/method: 'DELETE'/.test(api), 'api.ts: clearTutorChat uses DELETE')
ok(/tutorTts: \(studentId: number, tutor: string, text: string\) =>/.test(api),
   'api.ts: tutorTts exists')
ok(/tutor\/tts/.test(api), 'api.ts: tutorTts targets /tutor/tts')
ok(/tutorId\?: string \| null/.test(api),
   'api.ts: tutorSend accepts the selected tutorId')
ok(/tutor_id: opts\.tutorId \?\? null/.test(api),
   'api.ts: tutorSend sends tutor_id with each message')
ok(/conversation_id: opts\.conversationId \?\? null/.test(api),
   'api.ts: tutorSend sends conversation_id with each message')
ok(/finalizeAssessment: \(studentId: number, body: any\) =>/.test(api),
   'api.ts: finalizeAssessment exists')
ok(/assessments\/finalize/.test(api), 'api.ts: finalizeAssessment targets /assessments/finalize')

// ---- types.ts
ok(/tutor_id\?: string \| null/.test(types),
   'types.ts: TutorMessage carries an optional tutor_id')
ok(/conversation_id\?: number \| null/.test(types),
   'types.ts: TutorMessage carries an optional conversation_id')
ok(/interface TutorConversation/.test(types),
   'types.ts: TutorConversation is defined')

// ---- CopilotPanel
ok(/Record<number, TutorMessage\[\]>/.test(panel),
   'CopilotPanel: normal chat messages are stored per conversation')
ok(/activeConversationId/.test(panel),
   'CopilotPanel: active conversation id is tracked')
ok(/history-drawer/.test(panel),
   'CopilotPanel: conversation history drawer is rendered')
ok(/interviewThreads/.test(panel), 'CopilotPanel: interview threads are stored per tutor')
ok(/interviewLocked = .*starting.*active/.test(panel),
   'CopilotPanel: interview pin state derives from starting/active phases')
ok(!/TutorSelector/.test(panel) && /interviewLocked/.test(panel),
   'CopilotPanel: no avatar-strip tutor switch exists, and the interview tutor is pinned')
ok(/api\.clearTutorChat/.test(panel), 'CopilotPanel: conversation reset calls clearTutorChat')
ok(/api\.newTutorConversation/.test(panel), 'CopilotPanel: New Chat creates a new conversation instead of clearing')
ok(/copilot-expanded/.test(panel), 'CopilotPanel: expand/collapse toggles the overlay class')
ok(/api\.tutorTts/.test(panel), 'CopilotPanel: reply voice uses api.tutorTts')
ok(/tutorId,/.test(panel), 'CopilotPanel: selected tutorId is sent with tutor messages')
ok(/IconBack/.test(panel), 'CopilotPanel: profile view exposes a Back-to-Chat action')
ok(/backToChat/.test(panel), 'CopilotPanel: Back-to-Chat uses the localized label')
ok(!/speechSynthesis/.test(panel),
   'CopilotPanel: no generic browser speechSynthesis fallback (ElevenLabs-only voice)')
ok(!/copilot-modes/.test(panel), 'CopilotPanel: chat/practice/discuss mode tabs removed')
ok(/copilot-mic/.test(panel), 'CopilotPanel: microphone control is rendered in the chat input')
ok(/toggleMic\('chat'\)/.test(panel), 'CopilotPanel: chat mic routes through toggleMic')
ok(/startListening/.test(panel), 'CopilotPanel: mic input uses startListening')
ok(/toggleMic\('interview'\)/.test(panel),
   'CopilotPanel: the Mock Interview input also has a microphone')
ok(/micTarget === 'interview'/.test(panel),
   'CopilotPanel: interview mic notes/listening state are tracked separately')
ok(/interviewLang/.test(panel),
   'CopilotPanel: interview recognition uses the pinned interview language')
ok(/selectedInterviewLang/.test(panel),
   'CopilotPanel: interview start records the selected language without stale state')
ok(/voiceNote/.test(panel),
   'CopilotPanel: voice failures surface a visible "Voice unavailable" note')
ok(/ui\.voiceUnavailable/.test(panel),
   'CopilotPanel: voice failure note is localized')
ok(/audio\.muted = false/.test(panel),
   'CopilotPanel: TTS audio is unmuted and playable')
ok(/aria-label=\{ui\.voiceAria\}/.test(panel),
   'CopilotPanel: icon-only voice buttons keep a localized aria-label')
ok(!/<span>\{speakingKey === `i-\$\{item\.id\}` \? ui\.stopSpeak : ui\.speak\}<\/span>/.test(panel),
   'CopilotPanel: interview voice button is icon-only — no visible Speak/Stop text')
ok(!/<span>\{speakingKey === `m-\$\{message\.id\}` \? ui\.stopSpeak : ui\.speak\}<\/span>/.test(panel),
   'CopilotPanel: reply voice button is icon-only — no visible Speak/Stop text')

// ---- Mock Interview lives in the composer tools menu
ok(/toolActions/.test(panel) && /ui\.mockInterviewAction/.test(panel),
   'CopilotPanel: Mock Interview is exposed from the composer tools menu')
ok(/startInterview/.test(panel), 'CopilotPanel: interview starts from the panel')
ok(!/copilot-interview-hero/.test(panel),
   'CopilotPanel: Mock Interview is not a persistent chat card')
ok(!/Use Vex|Vex \(recommended\)|\(recommended\)/.test(panel),
   'CopilotPanel: no Vex-only recommendation is shown for other avatars')

// ---- Learning: standalone Mock Interview removed; no MockInterviewPanel wiring
ok(!/MockInterviewPanel/.test(learning), 'LearningPage: standalone MockInterviewPanel removed')
ok(!/onClearInterview/.test(learning), 'LearningPage: no onClearInterview wiring')
ok(!/interviewRequest/.test(learning), 'LearningPage: no interviewRequest state remains')

// ---- App: CopilotPanel hidden while a Verified assessment runs
ok(/!assessmentActive && <CopilotPanel \/>/.test(app),
   'App: CopilotPanel is hidden while an assessment is active')
ok(/assessmentActive/.test(app), 'App: the shell reads assessmentActive from context')

// ---- AssessmentsPage: no readiness gate, dedicated exam flow with exit finalization
ok(!/final-assessment\/status/.test(assessments),
   'AssessmentsPage: readiness gate no longer loads final-assessment/status')
ok(!/readiness/.test(assessments), 'AssessmentsPage: no readiness payload logic remains')
ok(/assessment-run-fullscreen/.test(assessments),
   'AssessmentsPage: quiz renders in a dedicated full-screen overlay')
ok(/assessment-run-fullscreen/.test(css),
   'index.css: full-screen assessment overlay styles exist')
ok(/finalizeAssessment\(/.test(assessments),
   'AssessmentsPage: ending the exam calls finalizeAssessment')
ok(/sendBeacon/.test(assessments),
   'AssessmentsPage: route-leave/pagehide finalizes via sendBeacon')
ok(/pagehide/.test(assessments),
   'AssessmentsPage: pagehide event finalizes the attempt')
ok(/external_token/.test(assessments),
   'AssessmentsPage: attempt idempotency token is sent to finalize')
ok(/startAssessmentSession/.test(assessments),
   'AssessmentsPage: the assessment lock is acquired at quiz start')
ok(/setAssessmentActive\(true\)/.test(assessments),
   'AssessmentsPage: the quiz activates the assessment lock immediately')

// ---- CSS + i18n
ok(/copilot-expanded/.test(css), 'index.css: expanded overlay styles exist')
ok(/copilot-msg-voice/.test(css), 'index.css: chat voice button styles exist')
ok(/copilot-pin-note/.test(css), 'index.css: interview pinned-note styles exist')
ok(/copilot-mic/.test(css), 'index.css: microphone control styles exist')
ok(/history-drawer/.test(css), 'index.css: conversation history drawer styles exist')
ok(/composer-tools-menu/.test(css), 'index.css: composer tools menu styles exist')
ok(/chat-clear-modal/.test(css), 'index.css: clear-chat modal styles exist')
ok(/copilot-open \{ max-height/.test(css),
   'index.css: the open panel is height-bounded so controls are never clipped')
ok(/\.copilot-body \{ .*overflow-y: auto/.test(css),
   'index.css: the panel body scrolls internally')
for (const key of ['newChat', 'newChatConfirm', 'history', 'chatHistory', 'changeMentor', 'clearChat', 'clearChatTitle', 'clearChatConfirm', 'cancel', 'clear', 'expand', 'collapse', 'backToChat', 'speak', 'stopSpeak', 'interviewPinned', 'micAria', 'micListeningAria', 'voiceUnavailable', 'toolsAria', 'toolsMenu', 'mockInterviewAction']) {
  ok(new RegExp(`\\b${key}:`).test(i18n), `tutorI18n: "${key}" string defined`)
}

if (problems.length) {
  console.error('Step 4.5 frontend contract violations:')
  for (const p of problems) console.error(`  - ${p}`)
  process.exit(1)
}
console.log('Step 4.5 frontend contracts OK')
