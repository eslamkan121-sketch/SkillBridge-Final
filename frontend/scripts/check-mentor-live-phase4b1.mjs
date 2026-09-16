// Phase 4B.1 — Mentor Live orb visual system, frontend source contract guard.
//
// Verifies the actual browser-side code keeps the Phase 4B.1 contracts:
//   - ONE reusable orb (MentorOrb.tsx); NO NovaOrb/AxelOrb/SageOrb/VexOrb and no
//     legacy VoiceOrb.tsx.
//   - Mentor identity flows into the orb from the canonical TutorId and inherits
//     the existing .copilot-panel.{purple,blue,gold,green} --mentor-accent tokens
//     (Nova purple / Axel blue / Sage gold / Vex green), plus per-mentor motion
//     tokens via CSS [data-mentor=…].
//   - Orb visuals map 1:1 onto the engine state machine (idle/listening/
//     processing/speaking/interrupted) + 'error' from voice.error — the engine
//     stays the single source of truth; the Live button and chat-mic dictation
//     wiring are unchanged.
//   - No 3D: package.json free of three/@react-three/*, no WebGL/canvas/3D assets.
//   - No provider labels (NVIDIA NIM / ElevenLabs / OpenAI) in the orb/UIs.
//
// Usage:  node frontend/scripts/check-mentor-live-phase4b1.mjs
// Exit code 0 = green. Any failing contract prints and exits 1. Driven by pytest
// like the other contract guards, so a regression fails the Phase 4B.1 gate.

import { readdirSync, existsSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { readProject, frontendRoot } from './path-helpers.mjs'

const read = readProject
const readRaw = (rel) => readFileSync(resolve(fileURLToPath(import.meta.url), '..', rel), 'utf8')

const problems = []
const ok = (cond, msg) => { if (!cond) problems.push(msg) }

const orb = read('frontend/src/components/MentorOrb.tsx')
const voice = read('frontend/src/components/VoiceMode.tsx')
const panel = read('frontend/src/components/CopilotPanel.tsx')
const hook = read('frontend/src/hooks/useVoiceSession.ts')
const css = read('frontend/src/index.css')
const i18n = read('frontend/src/lib/tutorI18n.ts')
const states = read('frontend/src/lib/voiceStates.ts')
const session = read('frontend/src/lib/voiceSession.ts')
const profiles = read('frontend/src/lib/tutorProfiles.ts')
const pkg = read('frontend/package.json')

// ---- 1. ONE reusable orb, no per-mentor or legacy orb files.
ok(existsSync(join(frontendRoot, 'src/components/MentorOrb.tsx')),
   'components/MentorOrb.tsx exists')
ok(!existsSync(join(frontendRoot, 'src/components/VoiceOrb.tsx')),
   'legacy VoiceOrb.tsx is removed')
const componentFiles = readdirSync(join(frontendRoot, 'src/components'))
ok(!componentFiles.some((f) => /^(Nova|Axel|Sage|Vex)Orb\.(tsx|ts)$/.test(f)),
   'no per-mentor orb components (Nova/Axel/Sage/VexOrb) exist')

// ---- 2. Orb component shape.
ok(/export type MentorOrbState = VoiceState \| 'error'/.test(orb),
   'MentorOrb: state type is the engine VoiceState plus error')
ok(/mentorId: TutorId \| string/.test(orb),
   'MentorOrb: accepts the canonical TutorId')
ok(/data-mentor=\{mentorId\}/.test(orb),
   'MentorOrb: renders data-mentor with the mentor id')
ok(/data-state=\{state\}/.test(orb),
   'MentorOrb: renders data-state')
ok(/className="ml-orb"/.test(orb),
   'MentorOrb: single component (ml-orb) reused for every mentor')
ok(/ml-core/.test(orb) && /onClick=\{onTap\}/.test(orb),
   'MentorOrb: interactive core maps tap to the engine action')
ok(!/document\.createElement\(['"]canvas|getContext\(|<\s*canvas\b|<mesh|useFrame|from ['"]three['"]|react-three/i.test(orb),
   'MentorOrb: pure DOM/CSS — no canvas/WebGL/three usage (only the doc comment guarantees it)')

// ---- 3. Mentor theme → orb accent mapping (tokens + per-mentor motion).
for (const mentor of ['nova', 'axel', 'sage', 'vex']) {
  ok(new RegExp(`\\[data-mentor="${mentor}"\\]`).test(css),
     `css: [data-mentor="${mentor}"] motion personality token present`)
}
for (const theme of ['purple', 'blue', 'gold', 'green']) {
  ok(new RegExp(`\\.copilot-panel\\.${theme}\\b`).test(css),
     `css: .copilot-panel.${theme} accent class present (canonical tutor identity)`)
}
ok(/--mentor-accent/.test(css), 'css: --mentor-accent token used across the panel')
ok(/var\(--mentor-accent, var\(--sb-teal\)\)/.test(css),
   'css: orb accent inherits --mentor-accent with teal fallback')
ok(/--ml-glow/.test(css) || /--ml-accent-glow/.test(css),
   'css: orb glow is derived from the mentor accent')

// ---- 4. Voice state visuals — engine states stay the single source of truth.
for (const s of ['idle', 'listening', 'processing', 'speaking', 'interrupted']) {
  ok(new RegExp(`\\.voice\\[data-state="${s}"\\]`).test(css),
     `css: overlay data-state="${s}" rules present`)
  ok(new RegExp(`\\.ml-orb\\[data-state="${s}"\\]`).test(css),
     `css: orb data-state="${s}" rules present`)
  ok(new RegExp(`sv-${s}\\b`).test(css) && new RegExp(`sb-${s}\\b`).test(css) && new RegExp(`vc-${s}\\b`).test(css),
     `css: status/sub/caption visible rules for "${s}"`)
}
ok(new RegExp(`\\.voice\\[data-error="true"\\]`).test(css),
   'css: error overlay dim rule (data-error=true) present')
ok(new RegExp(`\\.ml-orb\\[data-state="error"\\]`).test(css),
   'css: orb error state (stopped/calm) present')
ok(/VoiceState = '(idle|listening|processing|speaking|interrupted)'/.test(session),
   'voiceSession.ts: engine states unchanged (idle/listening/processing/speaking/interrupted)')

// ---- 5. VoiceMode redesign wired to the orb + the engine, errors surfaced.
ok(/<MentorOrb/.test(voice), 'VoiceMode: renders the shared MentorOrb')
ok(/mentorId=\{tutor\.id\}/.test(voice), 'VoiceMode: passes the selected tutor id to the orb')
ok(/state=\{orbState\}/.test(voice), 'VoiceMode: passes the orbState prop')
ok(/voice\.error \? 'error' : voice\.state/.test(voice),
   'VoiceMode: orb error state driven by engine voice.error — no competing state')
ok(/data-state=\{voice\.state\}/.test(voice),
   'VoiceMode: overlay data-state mirrors the engine state 1:1')
ok(/voice\.open\(\)/.test(voice) && /voice\.close\(\)/.test(voice),
   'VoiceMode: fresh session per open + teardown on close (unchanged behavior)')
ok(/v-live/.test(voice), 'VoiceMode: new mentor live header (v-live) present')
ok(/v-keyboard/.test(voice) && /v-kbd-label/.test(voice),
   'VoiceMode: keyboard fallback control present')
ok(/className="v-mic"/.test(voice), 'VoiceMode: recording/stop control present')
ok(/MOCKUP_VOICE_SUB\[voice\.state\]\[lang\]/.test(voice),
   'VoiceMode: localized sub copy intact (voiceStates.ts)')
// Phase 4B.2 polish: the debug-like pipeline hint labels (VOICE READY /
// VOICE REPLY …) are removed; state is carried by Ready/Listening/Thinking/
// Speaking only.
ok(!/MOCKUP_VOICE_HINT/.test(voice) && !/v-hint/.test(voice) && !/vh-/.test(voice),
   'VoiceMode: no debug pipeline hint labels (VOICE READY / VOICE REPLY removed)')
ok(!/MOCKUP_VOICE_HINT/.test(readRaw('../src/lib/voiceStates.ts')),
   'voiceStates.ts: MOCKUP_VOICE_HINT constant removed')
ok(/vc-/.test(voice) && /className=\{`vc vc-\$\{voice\.state\}`\}|`vc vc-\$\{voice\.state\}`/.test(voice),
   'VoiceMode: compact caption container (vc) mirrors engine state')
ok(/v-dock/.test(voice) && /v-end/.test(voice),
   'VoiceMode: bottom dock with a keyboard / mic / End controls present')

// ---- 5b. Phase 4B.2 r2 — EXPLICIT Live speech language (EN | Arabic) with a
// compact top-right selector; NO Auto mode / steering inside Live Voice.
ok(/dir=\{voice\.language === 'ar' \? 'rtl' : 'ltr'\}/.test(voice),
   'VoiceMode: surface direction follows the SELECTED explicit Live language')
ok(/v-lang/.test(voice),
   'VoiceMode: compact Live language selector (EN | عربي) present in the top bar')
ok(/voice\.setLanguage\('en'\)/.test(voice) && /voice\.setLanguage\('ar'\)/.test(voice),
   'VoiceMode: selector switches the live session between EN and Arabic')
ok(/aria-pressed=\{voice\.language === 'en'\}/.test(voice),
   'VoiceMode: selector exposes the active language to assistive tech')
ok(/\.voice \.v-lang\b/.test(css) && /\.v-lang-btn\b/.test(css),
   'css: compact language selector styles present')
ok(/\[dir=rtl\] \.v-lang/.test(css) || /\.voice\[dir="rtl"\] \.v-lang/.test(css),
   'css: RTL mirror rules keep the selector on the mirrored side')
ok(/v-end/.test(css) && /\.voice \.v-dock/.test(css),
   'css: bottom dock + End control styles present')
ok(/-webkit-line-clamp: 2/.test(css) || /max-height:.+2/.test(css),
   'css: compact captions clamp to ~2 visible lines')
// The human-acceptance return: remove unreliable Live Auto language detection.
ok(!/steerAutoRecognition|steeringTarget|scriptDetectLang/.test(voice),
   'VoiceMode: no Auto steering references remain (removed)')
ok(!/onInterim/.test(session),
   'voiceSession.ts: no interim-steering interface remains (removed)')
ok(!/steerBudget|MAX_STEER|prefLang/.test(session),
   'voiceSession.ts: no Auto steering budget / preference field remains (removed)')
ok(/setLanguage\(/.test(panel) || /voiceLang/.test(panel),
   'CopilotPanel: Live language is resolved explicitly at open (no Auto inside Live)')

// ---- 6. Existing voice behavior preserved.
ok(/setVoiceOpen\(true\)/.test(panel),
   'CopilotPanel: Live/waveform button still opens VoiceMode')
ok(/IconWaveform/.test(panel),
   'CopilotPanel: Live/waveform button icon unchanged')
ok(/micTarget === 'chat'/.test(panel),
   'CopilotPanel: chat mic stays dictation-only (unchanged path)')
ok(!/VoiceOrb/.test(panel) && !/NovaOrb|AxelOrb|SageOrb|VexOrb/.test(panel),
   'CopilotPanel: references the shared orb only (no per-mentor or legacy orbs)')

// ---- 7. No provider labels in the new UI.
// (case-sensitive NIM; NVIDIA matches with /i — "animation" must never trip.)
for (const [label, flags] of [['NVIDIA', 'i'], ['NIM\\b', ''], ['ElevenLabs', 'i'], ['OpenAI', 'i']]) {
  ok(!(new RegExp(label, flags)).test(orb) && !(new RegExp(label, flags)).test(voice),
     `no provider label "${label}" in MentorOrb.tsx / VoiceMode.tsx`)
}

// ---- 8. No 3D dependencies.
for (const dep of ['three', '@react-three/fiber', '@react-three/drei']) {
  ok(!new RegExp(`"${dep.replace('/', '\\/')}"`).test(pkg),
     `package.json: "${dep}" is not a dependency`)
}
ok(!/mentor3d|MentorStage|mentorVisuals/.test(panel),
   'CopilotPanel: no 3D mentor stage/visual references remain')

// ---- 9. CSS detail: responsive + reduced motion + old-keyframe cleanup.
ok(/--orb-size: clamp\(/.test(css),
   'css: orb size uses clamp() for responsive scaling')
ok(/clamp\(132px, 28vw, 186px\)/.test(css),
   'css: desktop orb reduced ~12% vs the 212px Phase 4B.1 size (Phase 4B.2)')
ok(!/212px/.test(css),
   'css: the old 212px orb cap is gone (smaller, calmer focus)')
ok(/prefers-reduced-motion: reduce/.test(css),
   'css: prefers-reduced-motion handling present')
ok(!/c2VoiceIn|@keyframes c2RingPulse|@keyframes c2OrbBreath|@keyframes c2Spin|@keyframes c2EqBar|@keyframes c2CaretBlink|@keyframes c2OrbJolt|@keyframes c2RingCollapse/.test(css),
   'css: retired c2 voice keyframes removed')
ok(/@keyframes c2FadeUp/.test(css) && /@keyframes c2FloatY/.test(css) && /@keyframes c2DotBounce/.test(css),
   'css: shared interview keyframes (c2FadeUp/c2FloatY/c2DotBounce) preserved')
ok(/@keyframes mlBreathe/.test(css) && /@keyframes mlRingPulse/.test(css) && /@keyframes mlSpin/.test(css),
   'css: new ml* orb keyframes present')

// ---- 10. i18n keys the new UI depends on.
for (const key of ['voiceModeTitle', 'voiceClose', 'voiceLiveTag', 'voiceTypeInstead', 'tapTheMic', 'voiceStop', 'voiceEnd', 'voiceLanguage', 'youTag']) {
  ok(new RegExp(`${key}:`).test(i18n), `i18n: ${key} key present`)
}

// ---- 11. Dedicated FULLSCREEN surface (human acceptance return).
// The live surface must cover the whole app viewport with NO normal chat
// chrome visible, so VoiceMode portals itself to <body>.
ok(/createPortal\(surface, document\.body\)/.test(voice),
   'VoiceMode: portaled to document.body — dedicated viewport surface')
ok(/theme-\$\{tutor\.theme\}/.test(voice),
   'VoiceMode: theme class derived from the canonical tutor theme')
ok(/\.voice \{[\s\S]*?position: fixed;/m.test(css) && /z-index: 2147483000/.test(css),
   'css: .voice is a fixed viewport surface with a top z-index (over dashboard)')
ok(/height: 100dvh/.test(css) && /min-height: 100svh/.test(css),
   'css: .voice uses viewport-safe fullscreen heights')
ok(/document\.body\.style\.overflow = 'hidden'/.test(voice),
   'VoiceMode: body scroll is locked while the live surface is up')
const chatFrags = ['composer', 'welcome', 'suggestion-grid', 'quick-chips', 'chat-thread']
for (const frag of chatFrags) {
  ok(!voice.includes(frag), `VoiceMode: no "${frag}" chat chrome inside the live surface`)
}
ok(!/<ChatThread/.test(voice), 'VoiceMode: normal chat message bubbles are not rendered inside it')
for (const theme of ['purple', 'blue', 'gold', 'green']) {
  ok(new RegExp(`\\.voice\\.theme-${theme}\\s*\\{ --mentor-accent: var\\(--sb-`).test(css) ||
     new RegExp(`\\.voice\\.theme-${theme}\\s*\\{ --mentor-accent: var\\(--green\\)`).test(css),
     `css: .voice.theme-${theme} maps the mentor accent (${theme})`)
}

// ---- 12. Natural hands-free loop (state machine stays the single truth).
ok(/sessionRef\.current\?\.clear\(\)[\s\S]{0,80}sessionRef\.current\?\.start\(\)/.test(hook),
   'hook: open() starts a fresh session and auto-listens immediately')
ok(/resumeAfterPlaybackEnd: true/.test(hook),
   'hook: hands-free auto-resume after TTS is enabled in Live mode')
ok(/resumeAfterPlaybackEnd/.test(session) && /scheduleResume\(\)/.test(session),
   'engine: resume-after-natural-end wiring present')
ok(/if \(this\.state !== 'listening'\) \{[\s\S]{0,80}this\.trace\('submit\.guard'/.test(session) ||
   /if \(this\.state !== 'listening'\) return/.test(session),
   'engine: a final user utterance is submitted only from listening — once per turn')
ok(/interruptedTimeout: 'listening'/.test(session),
   'engine: barge-in/interrupt hands off automatically to listening')
ok(/if \(this\.state === 'idle' && !this\.currentError\)/.test(session),
   'engine: auto-resume is guarded — only a clean audio end returns to listening')

// ---- 13. Playback-stability hardening (echo/self-barge-in root cause).
ok((session.match(/this\.listenInterrupt\(\)/g) || []).length === 1,
   'engine: the interrupt recognizer runs ONLY while /tutor is in flight — NEVER while the mentor speaks')
ok(/No recognizer while the mentor speaks/.test(session),
   'engine: speakReply hushes the microphone before playback (comment contract)')
ok(/this\.adapters\.recognition\.hush\(\)/.test(session),
   'engine: recognition is hushed the moment the reply becomes speaking')
ok(/onTrace\?: \(stage: string, meta\?: Record<string, unknown>\) => void/.test(session),
   'engine: structured developer diagnostics hook (stage + mentor + safe meta)')
ok(/if \(opts\.mode !== 'primary'\) return/.test(hook),
   'hook: the interrupt recognizer never self-triggers from a plain result (noise/echo)')
ok(/rec\.onspeechstart = \(\) => \{ if \(!entry\.cancelled\) opts\.onSpeechStart\?\.\(\) \}/.test(hook),
   'hook: only a real VAD speech-start can barge in')
ok(/onTrace: \(stage, meta\) => \{\s*console\.info\('\[voice-live\]'/.test(hook),
   'hook: [-voice-live-] stage logger includes the mentor id')
ok(/spoken: true/.test(panel),
   'panel: the Live voice request uses the concise spoken-reply style directive')
ok(/primeAutoplay\(\)/.test(voice),
   'VoiceMode: media playback is unblocked inside the Live-button gesture')
ok(/function primeAutoplay/.test(voice),
   'VoiceMode: primeAutoplay unlocks async TTS playback (no silent-mentor abort)')

if (problems.length) {
  console.error(`\ncheck-mentor-live-phase4b1: ${problems.length} contract(s) FAILED`)
  for (const p of problems) console.error(`  - ${p}`)
  process.exit(1)
}

console.log('check-mentor-live-phase4b1: all Phase 4B.1 orb contracts OK')