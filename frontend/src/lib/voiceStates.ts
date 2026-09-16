// Voice-overlay vocabulary ported from the authoritative Copilot V2 mockup
// (skillbridge-ai-copilot-v2.html). The overlay's ONE element renders all five
// state variants (.sv/.sb/.vt/.vh) and CSS toggles them via `data-state` on
// `.voice`, mirroring the mockup's hidden-radio switching.

export type MockupVoiceState = 'idle' | 'listening' | 'processing' | 'speaking' | 'interrupted'

export const MOCKUP_VOICE_STATES: MockupVoiceState[] = ['idle', 'listening', 'processing', 'speaking', 'interrupted']

/** Accent palette per state — matches the mockup (slate/teal/violet/mixed/coral). */
export const MOCKUP_VOICE_ACCENTS: Record<MockupVoiceState, 'slate' | 'teal' | 'violet' | 'mixed' | 'coral'> = {
  idle: 'slate',
  listening: 'teal',
  processing: 'violet',
  speaking: 'mixed',
  interrupted: 'coral',
}

/** Sub-status line under the main state title (bilingual, ported copy). */
export const MOCKUP_VOICE_SUB: Record<MockupVoiceState, { en: string; ar: string }> = {
  idle: { en: 'Tap the orb — or the mic in chat — to start', ar: 'اضغط على الكرة — أو المايك في المحادثة — للبدء' },
  listening: { en: 'Speak naturally — your words appear below', ar: 'تكلّم بشكل طبيعي — كلماتك بتظهر تحت' },
  processing: { en: 'Thinking through your request...', ar: 'بيفكر في طلبك...' },
  speaking: { en: 'Speak anytime — the tutor will stop and listen', ar: 'تكلّم في أي وقت — المُعلّم هيوقف ويسمعك' },
  interrupted: { en: 'Audio stopped · handing back to you…', ar: 'الصوت اتوقف · بيرجّع الكلام ليك…' },
}

// Phase 4B.2: the technical pipeline hint line (VOICE READY / VOICE REPLY …
// "voice ready / listening / preparing reply / voice reply / audio stopped")
// was REMOVED from the Live surface as debug-like labels. The state is already
// carried by the title + sub lines (Ready / Listening / Thinking / Speaking /
// Reconnecting). The hint constant is intentionally gone.
