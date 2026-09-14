// Engine unit tests for the Copilot voice session (frontend/src/lib/voiceSession.ts).
//
// Runs on Node 24 with native TypeScript type-stripping (no runtime imports from
// the engine, which is deliberately React/DOM-free). Uses a fake recognition /
// fake timers / controllable /tutor + TTS adapters so the exact state machine,
// barge-in, interrupted-handoff, timeout and stop semantics are proven in a
// fast, offline, deterministic harness.
//
// Usage:  node frontend/scripts/check-copilot-voice-unit.mjs
// Exit code 0 = green. Any failed assertion prints and exits 1.

import { pathToFileURL } from 'node:url'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { readFileSync } from 'node:fs'

const __dirname = dirname(fileURLToPath(import.meta.url))
const engineUrl = pathToFileURL(resolve(__dirname, '../src/lib/voiceSession.ts')).href
const engine = await import(engineUrl)

const { VoiceSession, reduceVoice, recognitionLang } = engine

let passed = 0
let failed = 0
const failures = []

function assert(cond, label) {
  if (cond) { passed += 1; return }
  failed += 1
  failures.push(label)
  console.error(`  FAIL: ${label}`)
}

function ok() { passed += 1 }

function makeHarness() {
  const calls = { listen: [], hush: 0, send: [], synth: [], play: [], schedule: [], cancel: [] }
  const pendingTimers = new Map()
  let timerSeq = 1

  const recognition = {
    listen({ mode, lang, onFinal, onSpeechStart, onError }) {
      calls.listen.push({ mode, lang, onFinal, onSpeechStart, onError })
      return { mode, lang, onFinal, onSpeechStart, onError }
    },
    hush() { calls.hush += 1 },
  }

  const timers = {
    schedule(cb, ms) { const id = timerSeq++; pendingTimers.set(id, { cb, ms }); calls.schedule.push({ id, ms }); return id },
    cancelSchedule(id) { calls.cancel.push(id); pendingTimers.delete(id) },
    pending() { return [...pendingTimers.values()] },
    fireNext() {
      const first = pendingTimers.values().next().value
      if (!first) throw new Error('fireNext: no pending timers')
      pendingTimers.delete(Array.from(pendingTimers.keys()).find((k) => pendingTimers.get(k) === first))
      first.cb()
    },
    pendingCount() { return pendingTimers.size },
    cancel(id) { pendingTimers.delete(id) },
  }

  let listenId = 0
  const lastListen = () => calls.listen[calls.listen.length - 1] || null

  let sendImpl = null
  let synthImpl = null
  let playImpl = null

  const adapters = {
    recognition,
    tts: {
      synthesize(text, signal) {
        calls.synth.push({ text, aborted: signal.aborted })
        if (synthImpl) return synthImpl(text, signal)
        return Promise.resolve({ blob: {} })
      },
      play(payload) {
        let resolveDone = () => {}
        const done = new Promise((r) => { resolveDone = r })
        const handle = { stop: resolveDone, resolveDone, done }
        calls.play.push({ payload, handle })
        if (playImpl) return playImpl(payload)
        return handle
      },
    },
    send(text, signal) {
      calls.send.push({ text, aborted: signal?.aborted, signal })
      if (sendImpl) return sendImpl(text, signal)
      return Promise.resolve('Nice to meet you.')
    },
    schedule: timers.schedule,
    cancelSchedule: timers.cancelSchedule,
  }

  const events = { states: [], transcripts: [], errors: [], replies: [] }
  const session = new VoiceSession(adapters, {
    language: 'en',
    onState: (s) => events.states.push(s),
    onTranscript: (t) => events.transcripts.push(t),
    onError: (kind, message) => events.errors.push({ kind, message }),
    onAssistantReply: (reply) => events.replies.push(reply),
  })
  session._debug = () => ({ calls, timers, events, listenId: ++listenId })

  return {
    adapters, calls, timers, events, session,
    lastListen,
    setSend: (fn) => { sendImpl = fn },
    setSynth: (fn) => { synthImpl = fn },
    setPlay: (fn) => { playImpl = fn },
    fireFinal: (text) => {
      const l = lastListen()
      if (!l || typeof l.onFinal !== 'function') {
        console.error('DEBUG fireFinal: calls.listen =', JSON.stringify(calls.listen, (k, v) => (typeof v === 'function' ? `[fn ${k}]` : v), 1))
        throw new Error('fireFinal: no active listen with onFinal')
      }
      l.onFinal(text)
      return l
    },
    fireSpeechStart: () => {
      const l = lastListen()
      if (!l) throw new Error('fireSpeechStart: no active listen')
      l.onSpeechStart()
      return l
    },
    fireError: () => {
      const l = lastListen()
      if (!l) throw new Error('fireError: no active listen')
      l.onError()
      return l
    },
  }
}

function flush() { return new Promise((r) => setImmediate(r)) }

// ---------------------------------------------------------------------------
// 1) The exact transition table (task spec lines 36-45).
// ---------------------------------------------------------------------------
{
  const T = {
    idle__start: reduceVoice('idle', 'start'),
    listening__speechFinal: reduceVoice('listening', 'speechFinal'),
    listening__stop: reduceVoice('listening', 'stop'),
    listening__error: reduceVoice('listening', 'error'),
    processing__replyReady: reduceVoice('processing', 'replyReady'),
    processing__stop: reduceVoice('processing', 'stop'),
    processing__error: reduceVoice('processing', 'error'),
    processing__speakDuringProcessing: reduceVoice('processing', 'speakDuringProcessing'),
    speaking__audioEnd: reduceVoice('speaking', 'audioEnd'),
    speaking__bargeIn: reduceVoice('speaking', 'bargeIn'),
    speaking__stop: reduceVoice('speaking', 'stop'),
    speaking__error: reduceVoice('speaking', 'error'),
    interrupted__interruptedTimeout: reduceVoice('interrupted', 'interruptedTimeout'),
    interrupted__stop: reduceVoice('interrupted', 'stop'),
    interrupted__error: reduceVoice('interrupted', 'error'),
    idle__speechFinal_noop: reduceVoice('idle', 'speechFinal'),
    speaking__empty_speech_noop: reduceVoice('speaking', 'speechFinal'),
    speaking__speakDuringProcessing_noop: reduceVoice('speaking', 'speakDuringProcessing'),
  }
  assert(T.idle__start === 'listening', 'table: idle.start -> listening')
  assert(T.listening__speechFinal === 'processing', 'table: listening.speechFinal -> processing')
  assert(T.listening__stop === 'idle', 'table: listening.stop -> idle')
  assert(T.listening__error === 'idle', 'table: listening.error -> idle')
  assert(T.processing__replyReady === 'speaking', 'table: processing.replyReady -> speaking')
  assert(T.processing__speakDuringProcessing === 'listening', 'table: processing.speakDuringProcessing -> listening')
  assert(T.processing__stop === 'idle', 'table: processing.stop -> idle')
  assert(T.processing__error === 'idle', 'table: processing.error -> idle')
  assert(T.speaking__audioEnd === 'idle', 'table: speaking.audioEnd -> idle')
  assert(T.speaking__bargeIn === 'interrupted', 'table: speaking.bargeIn -> interrupted')
  assert(T.speaking__stop === 'idle', 'table: speaking.stop -> idle')
  assert(T.speaking__error === 'idle', 'table: speaking.error -> idle')
  assert(T.interrupted__interruptedTimeout === 'listening', 'table: interrupted.interruptedTimeout -> listening')
  assert(T.interrupted__stop === 'idle', 'table: interrupted.stop -> idle')
  assert(T.interrupted__error === 'idle', 'table: interrupted.error -> idle')
  assert(T.idle__speechFinal_noop === 'idle', 'table: unlisted event is a no-op')
  assert(T.speaking__empty_speech_noop === 'speaking', 'table: empty STT while speaking -> stay speaking')
  assert(T.speaking__speakDuringProcessing_noop === 'speaking', 'table: speakDuringProcessing while speaking -> stay speaking')
}

// ---------------------------------------------------------------------------
// 2) Happy path: idle -> listening -> processing -> speaking -> audioEnd -> idle.
// ---------------------------------------------------------------------------
{
  const h = makeHarness()
  h.session.start()
  assert(h.session.state === 'listening', 'happy: start -> listening')
  assert(h.lastListen().mode === 'primary', 'happy: start uses primary recognition mode')

  h.fireFinal('hello copilot')
  assert(h.session.state === 'processing', 'happy: STT final -> processing')
  assert(h.calls.send.length === 1 && h.calls.send[0].text === 'hello copilot', 'happy: /tutor receives exactly the user transcript')

  await flush()
  assert(h.session.state === 'speaking', 'happy: reply ready -> speaking')
  assert(h.events.replies[0] === 'Nice to meet you.', 'happy: onAssistantReply fired with the reply')
  assert(h.calls.synth.length === 1 && h.calls.synth[0].text === 'Nice to meet you.', 'happy: TTS receives ONLY the assistant reply')

  const handle = h.calls.play[0].handle
  ok()
  handle.resolveDone()
  await flush()
  assert(h.session.state === 'idle', 'happy: audio end -> idle')
  assert(h.events.transcripts.length === 2, 'happy: user + assistant transcript items')
  assert(h.events.transcripts[0].role === 'user' && h.events.transcripts[1].role === 'assistant', 'happy: transcript ordering')
}

// ---------------------------------------------------------------------------
// 3) Barge-in while speaking: hush, abort TTS, playback.stop, interrupted,
//    400 ms later -> listening (fresh primary listen).
// ---------------------------------------------------------------------------
{
  const h = makeHarness()
  let playbackStopped = false
  h.setPlay(() => {
    const doneBox = { done: null }
    const done = new Promise((r) => { doneBox.done = r })
    return {
      stop() { playbackStopped = true; doneBox.done() },
      done,
    }
  })
  const synthCalls = []
  h.setSynth((text, signal) => {
    synthCalls.push({ text, abortedAtCall: signal.aborted })
    return Promise.resolve({ blob: {} })
  })

  h.session.start()
  h.fireFinal('tell me about apis')
  await flush()
  assert(h.session.state === 'speaking', 'bargein: reached speaking')
  assert(h.calls.play.length === 1, 'bargein: playback started')
  assert(synthCalls.every((c) => !c.abortedAtCall), 'bargein: /tutor/tts not aborted before it played')

  // Speech starts while the tutor's audio plays.
  h.fireSpeechStart()
  assert(h.session.state === 'interrupted', 'bargein: speech during speaking -> interrupted')
  assert(playbackStopped === true, 'bargein: playback.stop() called')
  assert(h.calls.play.length === 1, 'bargein: no new playback started')
  assert(h.timers.pendingCount() === 1, 'bargein: exactly one handoff timer armed')

  h.timers.fireNext()
  assert(h.session.state === 'listening', 'bargein: 400ms later -> listening')
  assert(h.lastListen().mode === 'primary', 'bargein: handoff resumes PRIMARY recognition')
}

// ---------------------------------------------------------------------------
// 4) Barge-in while /tutor in flight: abort the fetch, keep transcript, listen.
// ---------------------------------------------------------------------------
{
  const h = makeHarness()
  let sendSignal = null
  h.setSend((text, signal) => { sendSignal = signal; return new Promise((res) => { h._resolveSend = res }) })
  h.session.start()
  h.fireFinal('question pending')
  assert(h.session.state === 'processing', 'proc-bargein: processing (send in flight)')

  h.fireSpeechStart()
  assert(h.session.state === 'listening', 'proc-bargein: speech while processing -> listening')
  assert(sendSignal && sendSignal.aborted === true, 'proc-bargein: in-flight /tutor aborted')

  // The stale send later settles — the engine must drop it entirely.
  h._resolveSend('stale reply that must never be spoken')
  await flush()
  await flush()
  assert(h.session.state === 'listening', 'proc-bargein: stale reply never pushed the state forward')
  assert(h.calls.synth.length === 0, 'proc-bargein: stale reply never reached TTS')
  assert(h.calls.play.length === 0, 'proc-bargein: stale reply never played')
  assert(h.events.replies.length === 0, 'proc-bargein: stale reply never raised onAssistantReply')
  assert(h.events.transcripts.length === 1, 'proc-bargein: only the user transcript kept, no assistant item')
}

// ---------------------------------------------------------------------------
// 5) Timeout during processing -> connection-lost error -> idle.
// ---------------------------------------------------------------------------
{
  const h = makeHarness()
  let sendSignal = null
  h.setSend((text, signal) => { sendSignal = signal; return new Promise(() => {}) })
  h.session.start()
  h.fireFinal('slow question')
  assert(h.timers.pendingCount() === 1, 'timeout: guard timer armed on send')

  h.timers.fireNext()
  assert(h.session.state === 'idle', 'timeout: -> idle')
  assert(sendSignal.aborted === true, 'timeout: in-flight /tutor aborted')
  const micErr = h.events.errors.find((e) => e.kind === 'connection')
  assert(Boolean(micErr), 'timeout: connection error raised')
}

// ---------------------------------------------------------------------------
// 6) /tutor rejection -> connection-lost -> idle (spec message).
// ---------------------------------------------------------------------------
{
  const h = makeHarness()
  h.setSend(() => Promise.reject(new Error('nvidia down')))
  h.session.start()
  h.fireFinal('will it reject')
  await flush()
  await flush()
  assert(h.session.state === 'idle', 'send-fail: -> idle')
  const err = h.events.errors.find((e) => e.kind === 'connection')
  assert(Boolean(err) && err.message === 'Connection lost — try again', 'send-fail: exact error message')
}

// ---------------------------------------------------------------------------
// 7) TTS synth failure -> reply stays in transcript + idle + voice-unavailable.
// ---------------------------------------------------------------------------
{
  const h = makeHarness()
  h.setSynth(() => Promise.reject(new Error('elevenlabs down')))
  h.session.start()
  h.fireFinal('answer me')
  await flush()
  await flush()
  assert(h.session.state === 'idle', 'synth-fail: -> idle')
  assert(h.events.transcripts.some((t) => t.role === 'assistant' && t.text === 'Nice to meet you.'), 'synth-fail: reply kept in transcript')
  assert(h.events.errors.some((e) => e.kind === 'voice-unavailable'), 'synth-fail: voice-unavailable error')
}

// ---------------------------------------------------------------------------
// 8) Empty STT while speaking stays speaking; stop from any active state -> idle.
// ---------------------------------------------------------------------------
{
  const h = makeHarness()
  h.session.start()
  h.fireFinal('hello')
  await flush()
  assert(h.session.state === 'speaking', 'empty-stt: speaking')
  h.fireFinal('')
  assert(h.session.state === 'speaking', 'empty-stt: empty final leaves speaking untouched')
  h.session.stop()
  assert(h.session.state === 'idle', 'empty-stt: stop -> idle')
  h.session.stop()
  assert(h.session.state === 'idle', 'stop while idle is a no-op')
}

// ---------------------------------------------------------------------------
// 9) Mic error during listening -> mic error + idle; start no-op while active.
// ---------------------------------------------------------------------------
{
  const h = makeHarness()
  h.session.start()
  h.session.start()
  assert(h.calls.listen.length === 1, 'mic: duplicate start is a no-op')
  h.fireError()
  assert(h.session.state === 'idle', 'mic: error -> idle')
  assert(h.events.errors.some((e) => e.kind === 'mic'), 'mic: mic error raised')
}

// ---------------------------------------------------------------------------
// 10) Language mapping + recognition.lang passed through.
// ---------------------------------------------------------------------------
{
  assert(recognitionLang('ar') === 'ar-EG', 'lang: ar -> ar-EG')
  assert(recognitionLang('en') === 'en-US', 'lang: en -> en-US')
  const h = makeHarness()
  h.session.start()
  assert(h.lastListen().lang === 'en-US', 'lang: recognizer wired with en-US')
}

// ---------------------------------------------------------------------------
// 11) Transcript never sent to TTS; user transcript sent verbatim to /tutor.
// ---------------------------------------------------------------------------
{
  const h = makeHarness()
  h.session.start()
  h.fireFinal('  user said this  ')
  assert(h.calls.send.length === 1 && h.calls.send[0].text === 'user said this', 'send: trimmed user transcript forwarded verbatim')
  await flush()
  assert(h.calls.synth.length === 1 && h.calls.synth[0].text === 'Nice to meet you.', 'cannot: TTS only ever receives the assistant reply')
  assert(h.calls.synth[0].text !== h.calls.send[0].text, 'cannot: user transcript is never spoken')
}

// ---------------------------------------------------------------------------
// 12) clear() resets transcript + error + state; stale session ignored.
// ---------------------------------------------------------------------------
{
  const h = makeHarness()
  h.session.start()
  h.fireFinal('bye')
  await flush()
  h.session.clear()
  assert(h.session.state === 'idle', 'clear: -> idle')
  assert(h.session.transcript.length === 0, 'clear: transcript emptied')
  const idBeforeClear = h.calls.send.length
  h.fireFinal('too late')
  assert(h.calls.send.length === idBeforeClear, 'clear: post-clear recognizer event ignored')
}

// ---------------------------------------------------------------------------
// 13) No TTS adapter -> reply kept as transcript, idle, voice-unavailable.
// ---------------------------------------------------------------------------
{
  const h2 = makeHarness()
  const noTts = new VoiceSession({
    recognition: h2.adapters.recognition,
    send: () => Promise.resolve('offline answer'),
    schedule: h2.timers.schedule,
    cancelSchedule: h2.timers.cancelSchedule,
  }, {
    language: 'en',
    onState: (s) => h2.events.states.push(s),
    onTranscript: (t) => h2.events.transcripts.push(t),
    onError: (k, m) => h2.events.errors.push({ kind: k, message: m }),
  })
  noTts.start()
  h2.fireFinal('hi')
  await flush()
  await flush()
  assert(h2.events.transcripts.length === 2, 'no-tts: user + assistant transcript kept')
  assert(noTts.state === 'idle', 'no-tts: -> idle')
  assert(h2.events.errors.some((e) => e.kind === 'voice-unavailable'), 'no-tts: voice-unavailable error')
}

// ---------------------------------------------------------------------------
// 14) abort() (user closes overlay) kills pending TTS + playback like stop.
// ---------------------------------------------------------------------------
{
  const h = makeHarness()
  let ended = null
  h.setPlay(() => {
    const done = new Promise((r) => { ended = r })
    return { stop() { ended() }, done }
  })
  h.session.start()
  h.fireFinal('wave')
  await flush()
  assert(h.session.state === 'speaking', 'abort: speaking')
  h.session.stop()
  assert(h.session.state === 'idle', 'abort: stop -> idle')
}

// ---------------------------------------------------------------------------
// 15) stop() while /tutor is in flight: abort the fetch, drop the stale reply,
//     keep the user transcript, return to idle with the timeout disarmed.
// ---------------------------------------------------------------------------
{
  const h = makeHarness()
  let sendSignal = null
  let resolveSend = null
  h.setSend((text, signal) => { sendSignal = signal; return new Promise((res) => { resolveSend = res }) })
  h.session.start()
  h.fireFinal('stop me now')
  assert(h.session.state === 'processing', 'stop-proc: /tutor in flight')
  assert(h.timers.pendingCount() === 1, 'stop-proc: reply timeout armed')

  h.session.stop()
  assert(h.session.state === 'idle', 'stop-proc: stop -> idle')
  assert(sendSignal && sendSignal.aborted === true, 'stop-proc: in-flight /tutor aborted')
  assert(h.timers.pendingCount() === 0, 'stop-proc: reply timeout disarmed')

  resolveSend('stale reply that must never be spoken')
  await flush()
  await flush()
  assert(h.session.state === 'idle', 'stop-proc: stale reply never leaves idle')
  assert(h.calls.synth.length === 0, 'stop-proc: stale reply never reached TTS')
  assert(h.calls.play.length === 0, 'stop-proc: stale reply never played')
  assert(h.events.replies.length === 0, 'stop-proc: stale reply never raised onAssistantReply')
  assert(h.events.transcripts.length === 1, 'stop-proc: only the user transcript kept')
}

// ---------------------------------------------------------------------------
// 16) SR-unsupported source guards (offline, read-only): the hook refuses to
//     build a session when recognition is unsupported or there is no student,
//     exposes `supported`, and the panel gates the chat mic on busy / active
//     assessment / missing student id and never opens the overlay for an
//     unsupported browser — it surfaces the honest note instead.
// ---------------------------------------------------------------------------
{
  const hookSrc = readFileSync(resolve(__dirname, '../src/hooks/useVoiceSession.ts'), 'utf8')
  const panelSrc = readFileSync(resolve(__dirname, '../src/components/CopilotPanel.tsx'), 'utf8')
  assert(/if \(!opts\.studentId \|\| !opts\.recognitionSupported\) return/.test(hookSrc),
    'sr-guard: hook refuses to build a session without studentId or SR support')
  assert(/supported:\s*opts\.recognitionSupported/.test(hookSrc),
    'sr-guard: hook exposes `supported` = recognitionSupported')
  assert(/recognitionSupported:\s*speech\.recognitionSupported/.test(panelSrc),
    'sr-guard: panel passes speech.recognitionSupported into the session')
  assert(/if \(!speech\.recognitionSupported\) \{ setVoiceNote\(ui\.voiceUnsupported\); return \}/.test(panelSrc),
    'sr-guard: unsupported browser shows the honest note, never opens the overlay')
  assert(/disabled=\{assessmentActive \|\| busy \|\| !studentId\}/.test(panelSrc),
    'sr-guard: composer mic disabled while busy / assessment / no student')
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\ncheck-copilot-voice-unit.mjs: ${passed} passed, ${failed} failed`)
if (failed > 0) {
  console.error('\nFailures:')
  for (const f of failures) console.error(`  - ${f}`)
  process.exit(1)
}