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

function makeHarness(extraOpts = {}) {
  const calls = { listen: [], hush: 0, send: [], synth: [], play: [], schedule: [], cancel: [] }
  const pendingTimers = new Map()
  let timerSeq = 1

  const recognition = {
    listen({ mode, lang, onFinal, onSpeechStart, onError }) {
      // Deactivate any prior listener (a hush() in the engine is what the real
      // browser adapter uses to kill an in-flight recognizer; new listen()
      // supersedes old ones the same way).
      for (const l of calls.listen) l.active = false
      const entry = { mode, lang, onFinal, onSpeechStart, onError, active: true }
      calls.listen.push(entry)
      return entry
    },
    hush() {
      calls.hush += 1
      for (const l of calls.listen) l.active = false
    },
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
  const lastListen = () => {
    for (let i = calls.listen.length - 1; i >= 0; i -= 1) {
      if (calls.listen[i].active) return calls.listen[i]
    }
    return null
  }
  const activeListens = () => calls.listen.filter((l) => l.active).length

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
    send(text, signal, opts) {
      calls.send.push({ text, aborted: signal?.aborted, signal, opts })
      if (sendImpl) return sendImpl(text, signal, opts)
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
    ...extraOpts,
  })
  session._debug = () => ({ calls, timers, events, listenId: ++listenId })

  return {
    adapters, calls, timers, events, session,
    lastListen,
    activeListens,
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
// 3) Deliberate barge-in while speaking (mic/orb button). CRITICAL Live
//    invariant: the ENTIRE speaking state runs with NO active recognizer, so
//    the mentor's own speaker audio can never be mistaken for a user barge-in
//    (the echo loop). Only an explicit interrupt()/stop() cuts playback.
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
  assert(h.activeListens() === 0, 'bargein: NO recognizer is active while the mentor speaks (no echo loop)')

  // Explicit user interruption (the dedicated mic/orb button path).
  h.session.interrupt()
  assert(h.session.state === 'interrupted', 'bargein: deliberate interrupt during speaking -> interrupted')
  assert(playbackStopped === true, 'bargein: playback.stop() called')
  assert(h.calls.play.length === 1, 'bargein: no new playback started')
  assert(h.timers.pendingCount() === 1, 'bargein: exactly one handoff timer armed')
  assert(h.calls.listen.filter((l) => l.mode === 'interrupt' && l.active).length === 0,
    'bargein: no interrupt recognizer was left running during speaking')

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
//    (No recognizer runs while speaking, so an empty final can only arrive on a
//    stale hushed listener — it must be ignored.)
// ---------------------------------------------------------------------------
{
  const h = makeHarness()
  h.session.start()
  h.fireFinal('hello')
  await flush()
  assert(h.session.state === 'speaking', 'empty-stt: speaking')
  for (const l of h.calls.listen) {
    if (l.onFinal && !l.active) l.onFinal('')
  }
  assert(h.session.state === 'speaking', 'empty-stt: empty stale final leaves speaking untouched')
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
  for (const l of h.calls.listen) {
    if (l.onFinal && !l.active) l.onFinal('too late')
  }
  await flush()
  assert(h.calls.send.length === idBeforeClear, 'clear: post-clear stale recognizer event ignored')
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
// 15b) Hands-free Live loop: with resumeAfterPlaybackEnd=true a clean audio end
//      auto-returns to listening (fresh primary recognizer, no per-turn mic
//      tap), so the user can speak, hear the mentor, and speak again — with
//      exactly one tutor request and one TTS pass per user utterance.
// ---------------------------------------------------------------------------
{
  const h = makeHarness({ resumeAfterPlaybackEnd: true, resumeDelayMs: 150 })
  h.session.start()
  assert(h.session.state === 'listening', 'live-loop: opens listening automatically')

  h.fireFinal('first question')
  assert(h.session.state === 'processing', 'live-loop: first utterance -> processing')
  await flush()
  assert(h.session.state === 'speaking', 'live-loop: mentor reply -> speaking')
  assert(h.calls.send.length === 1 && h.calls.send[0].text === 'first question',
    'live-loop: first final utterance submitted exactly once')

  const handle = h.calls.play[0].handle
  handle.resolveDone()
  await flush()
  assert(h.session.state === 'idle', 'live-loop: audio end -> idle (transition flash)')
  assert(h.timers.pendingCount() === 1, 'live-loop: exactly one resume timer armed after audio end')
  h.timers.fireNext()
  assert(h.session.state === 'listening', 'live-loop: TTS end auto-resumed listening')
  assert(h.lastListen().mode === 'primary', 'live-loop: resume started a fresh PRIMARY recognizer')

  // Second turn with zero user action — no duplicate tutor requests / TTS.
  h.fireFinal('second question')
  assert(h.calls.send.length === 2, 'live-loop: second final utterance submitted exactly once (total 2)')
  await flush()
  assert(h.session.state === 'speaking', 'live-loop: second reply spoken automatically')
  assert(h.calls.synth.length === 2 && h.calls.play.length === 2, 'live-loop: no duplicate TTS')
}

// ---------------------------------------------------------------------------
// 15c) Hands-free must NEVER resume on an explicit stop or a TTS failure —
//      resumeAfterPlaybackEnd fires only for a clean natural audio end.
// ---------------------------------------------------------------------------
{
  const h = makeHarness({ resumeAfterPlaybackEnd: true })
  h.session.start()
  h.fireFinal('will you fail?')
  h.session.stop()
  await flush()
  assert(h.session.state === 'idle' && h.timers.pendingCount() === 0,
    'live-stop: explicit stop -> idle with NO resume timer armed')

  const h2 = makeHarness({ resumeAfterPlaybackEnd: true })
  h2.session.start()
  h2.fireFinal('no tts')
  h2.setSynth(() => Promise.reject(new Error('tts down')))
  await flush()
  assert(h2.events.errors.some((e) => e.kind === 'voice-unavailable'),
    'live-tts: TTS unavailable surfaces the honest error (no fake speaking)')
  assert(h2.session.state === 'idle', 'live-tts: TTS unavailable -> idle')
  assert(h2.timers.pendingCount() === 0, 'live-tts: no resume timer after TTS failure')
}

// ---------------------------------------------------------------------------
// 15d) No-microphone-while-speaking (the playback-cutoff root cause): from the
//      moment the mentor's reply is ready the recognizer is hushed and NO new
//      recognizer is started until a clean audio end auto-resumes listening.
//      Exactly one fresh primary recognizer after playback, no interrupt/listen
//      burst during TTS, and no duplicate turn after the resume.
// ---------------------------------------------------------------------------
{
  const h = makeHarness({ resumeAfterPlaybackEnd: true, resumeDelayMs: 150 })
  h.session.start()
  h.fireFinal('echo trap')
  const listensBeforeSpeaking = h.calls.listen.length
  await flush()
  assert(h.session.state === 'speaking', 'no-mic: speaking reached')
  assert(h.lastListen() === null, 'no-mic: NO active recognizer while speaking (last active is empty)')
  assert(h.calls.synth.length === 1, 'no-mic: TTS requested once')
  assert(h.calls.synth[0].aborted === false, 'no-mic: TTS request started cleanly (not pre-aborted by echo)')

  // Simulate a would-be echo final arriving on a stale recognizer callback:
  // because the recognizer is hushed, the engine MUST ignore it entirely.
  const nul = h.timers.pendingCount()
  for (const l of h.calls.listen) {
    if (l.onFinal && !l.active) l.onFinal('echoed mentor audio')
  }
  await flush()
  assert(h.session.state === 'speaking', 'no-mic: a stale final (echo) does NOT cut playback')
  assert(h.calls.listen.length === listensBeforeSpeaking,
    'no-mic: no recognizer was (re)opened by the echo at all')
  assert(h.timers.pendingCount() === nul, 'no-mic: no timers armed by echo')
  assert(h.calls.send.length === 1, 'no-mic: echo never submits a new tutor turn')

  const handle = h.calls.play[0].handle
  handle.resolveDone()
  await flush()
  assert(h.session.state === 'idle', 'no-mic: natural audio end -> idle')
  assert(h.timers.pendingCount() === 1, 'no-mic: exactly one resume timer')
  h.timers.fireNext()
  assert(h.session.state === 'listening', 'no-mic: listening resumed after playback completion')
  assert(h.lastListen() && h.lastListen().mode === 'primary', 'no-mic: fresh PRIMARY recognizer after playback')
  assert(h.calls.listen.length === listensBeforeSpeaking + 1,
    'no-mic: the ONLY new recognizer after playback is the fresh primary')

  h.fireFinal('second question')
  assert(h.calls.send.length === 2, 'no-mic: second turn submitted once (no duplicate after resume)')
  await flush()
  assert(h.session.state === 'speaking', 'no-mic: second reply spoken')
}

// ---------------------------------------------------------------------------
// 15e) Deliberate interruption during speaking still works (mic/orb button),
//      cuts playback cleanly, hands off to listening, and NEVER arms an
//      auto-resume for that turn (resume is only for a natural audio end).
// ---------------------------------------------------------------------------
{
  const h = makeHarness({ resumeAfterPlaybackEnd: true })
  let playbackStopped = false
  h.setPlay(() => {
    const doneBox = { done: null }
    const done = new Promise((r) => { doneBox.done = r })
    return { stop() { playbackStopped = true; doneBox.done() }, done }
  })
  h.session.start()
  h.fireFinal('cut me off')
  await flush()
  assert(h.session.state === 'speaking', 'explicit-bargein: speaking')
  h.session.interrupt()
  assert(playbackStopped === true, 'explicit-bargein: playback stopped')
  assert(h.session.state === 'interrupted', 'explicit-bargein: interrupted')
  assert(h.timers.pendingCount() === 1, 'explicit-bargein: handoff timer armed, no resume timer')
  h.timers.fireNext()
  assert(h.session.state === 'listening', 'explicit-bargein: 400ms handoff -> listening')
  assert(h.lastListen().mode === 'primary', 'explicit-bargein: fresh primary listen')
}

// ---------------------------------------------------------------------------
// 15f) EXPLICIT LIVE LANGUAGE — Live Voice has EXACTLY TWO speech modes (EN |
//      Arabic) and NO Auto inside the session. English forces en-US; the
//      recognizer never steers (no interim interface at all), and the /tutor
//      turn always carries the explicit language.
// ---------------------------------------------------------------------------
{
  const det = []
  const h = makeHarness({ language: 'en', onLanguageDetected: (l) => det.push(l) })
  h.session.start()
  assert(h.lastListen().lang === 'en-US', 'explicit-en: Live opens in en-US')
  assert(h.lastListen().onInterim === undefined, 'explicit-en: no interim-steering interface remains')
  h.fireFinal("What's your name?")
  assert(h.calls.listen.filter((l) => l.mode === 'primary').length === 1,
    'explicit-en: exactly one primary recognizer per utterance (no steering restart)')
  assert(h.calls.send.length === 1, 'explicit-en: one STT final -> one /tutor turn')
  assert(h.calls.send[0].opts.language === 'en', 'explicit-en: /tutor receives language=en')
  assert(det[0] === 'en', 'explicit-en: onLanguageDetected reports en')
  await flush()
  assert(h.session.state === 'speaking', 'explicit-en: English reply is spoken')
}

// ---------------------------------------------------------------------------
// 15g) EXPLICIT Arabic — ar-EG recognizer, real Arabic transcript end-to-end.
// ---------------------------------------------------------------------------
{
  const det = []
  const h = makeHarness({ language: 'ar', onLanguageDetected: (l) => det.push(l) })
  h.session.start()
  assert(h.lastListen().lang === 'ar-EG', 'explicit-ar: Live opens in ar-EG')
  h.fireFinal('اسمك ايه؟')
  assert(h.calls.send.length === 1, 'explicit-ar: one final -> one /tutor turn')
  assert(h.calls.send[0].opts.language === 'ar', 'explicit-ar: /tutor receives language=ar')
  assert(det[0] === 'ar', 'explicit-ar: onLanguageDetected reports ar')
  await flush()
  assert(h.session.state === 'speaking', 'explicit-ar: Arabic reply is spoken')
}

// ---------------------------------------------------------------------------
// 15h) MID-SESSION SWITCH EN -> AR while LISTENING — safe restart: hush the
//      current recognizer, invalidate its stale callbacks (recogId bump), start
//      a fresh primary listener in the new locale, and never commit a stale
//      final from the old recognizer. The hands-free loop then continues in
//      Arabic.
// ---------------------------------------------------------------------------
{
  const det = []
  const h = makeHarness({ language: 'en', resumeAfterPlaybackEnd: true, onLanguageDetected: (l) => det.push(l) })
  h.session.start()
  assert(h.lastListen().lang === 'en-US', 'switch-en-ar: starts en-US')
  const firstListen = h.lastListen()
  const hushBefore = h.calls.hush
  h.session.setLanguage('ar')
  assert(h.lastListen().lang === 'ar-EG', 'switch-en-ar: recognizer restarted in ar-EG')
  assert(h.lastListen() !== firstListen, 'switch-en-ar: a NEW primary recognizer was started')
  assert(h.calls.hush === hushBefore + 1, 'switch-en-ar: the old recognizer was hushed')
  assert(h.activeListens() === 1, 'switch-en-ar: exactly one recognizer active after the switch')
  assert(det[det.length - 1] === 'ar', 'switch-en-ar: onLanguageDetected reported ar immediately')
  // A stale final from the OLD en-US recognizer must never commit.
  firstListen.onFinal('Stale english final')
  await flush()
  assert(h.calls.send.length === 0, 'switch-en-ar: stale en-US final is discarded')
  assert(h.session.state === 'listening', 'switch-en-ar: still listening after discarding the stale final')
  h.fireFinal('ممكن تشرحلي Docker ببساطة؟')
  assert(h.calls.send.length === 1, 'switch-en-ar: the real Arabic final submits once')
  assert(h.calls.send[0].opts.language === 'ar', 'switch-en-ar: Arabic turn sends language=ar')
  await flush()
  assert(h.session.state === 'speaking', 'switch-en-ar: Arabic reply is spoken')
  // The hands-free loop continues in the switched language.
  h.calls.play[0].handle.resolveDone()
  await flush()
  assert(h.session.state === 'idle', 'switch-en-ar: audio end -> idle')
  h.timers.fireNext()
  assert(h.session.state === 'listening', 'switch-en-ar: loop auto-resumes to listening')
  assert(h.lastListen().lang === 'ar-EG', 'switch-en-ar: resumed recognizer stays ar-EG')
}

// ---------------------------------------------------------------------------
// 15i) MID-SESSION SWITCH AR -> EN while LISTENING (symmetric — no lingering
//      Arabic recognizer, no duplicate turn).
// ---------------------------------------------------------------------------
{
  const h = makeHarness({ language: 'ar' })
  h.session.start()
  assert(h.lastListen().lang === 'ar-EG', 'switch-ar-en: starts ar-EG')
  const firstListen = h.lastListen()
  h.session.setLanguage('en')
  assert(h.lastListen().lang === 'en-US', 'switch-ar-en: recognizer restarted in en-US')
  assert(h.lastListen() !== firstListen, 'switch-ar-en: fresh primary recognizer')
  assert(h.activeListens() === 1, 'switch-ar-en: exactly one active recognizer')
  firstListen.onFinal('عربى ملغى')
  await flush()
  assert(h.calls.send.length === 0, 'switch-ar-en: stale ar-EG final is discarded')
  h.fireFinal('Can you explain Docker simply?')
  assert(h.calls.send.length === 1, 'switch-ar-en: English final submits once')
  assert(h.calls.send[0].opts.language === 'en', 'switch-ar-en: English turn sends language=en')
}

// ---------------------------------------------------------------------------
// 15j) SWITCH WHILE THE MENTOR IS SPEAKING — the language change is applied
//      AFTER playback (never cut, never duplicated): in-flight TTS keeps
//      playing, and the auto-resume restarts Listening in the new locale.
// ---------------------------------------------------------------------------
{
  const det = []
  const h = makeHarness({ language: 'en', resumeAfterPlaybackEnd: true, onLanguageDetected: (l) => det.push(l) })
  h.session.start()
  h.fireFinal('Hello there')
  await flush()
  assert(h.session.state === 'speaking', 'switch-speaking: mentor is speaking')
  const playCount = h.calls.play.length
  const hushBefore = h.calls.hush
  h.session.setLanguage('ar')
  assert(h.session.state === 'speaking', 'switch-speaking: playback is NOT interrupted by a language switch')
  assert(h.calls.play.length === playCount, 'switch-speaking: no new playback / duplicate turn')
  assert(h.calls.hush === hushBefore, 'switch-speaking: no microphone restart during playback')
  assert(det[det.length - 1] === 'en', 'switch-speaking: language not applied mid-playback')
  h.calls.play[0].handle.resolveDone()
  await flush()
  assert(h.session.state === 'idle', 'switch-speaking: playback ends naturally -> idle')
  h.timers.fireNext()
  assert(h.session.state === 'listening', 'switch-speaking: loop resumes to listening')
  assert(h.lastListen().lang === 'ar-EG', 'switch-speaking: pending switch applied -> ar-EG')
  assert(det[det.length - 1] === 'ar', 'switch-speaking: onLanguageDetected reported ar after playback')
}

// ---------------------------------------------------------------------------
// 15k) SWITCH WHILE /tutor IS IN FLIGHT (processing) — the in-flight turn is
//      finished in the OLD language (never re-sent), and the switch applies to
//      the NEXT Listening session only.
// ---------------------------------------------------------------------------
{
  const det = []
  const h = makeHarness({ language: 'ar', resumeAfterPlaybackEnd: true, onLanguageDetected: (l) => det.push(l) })
  h.session.start()
  h.fireFinal('عندي سؤال')
  assert(h.session.state === 'processing', 'switch-processing: /tutor in flight')
  h.session.setLanguage('en')
  assert(h.calls.send.length === 1, 'switch-processing: the in-flight turn is never re-sent')
  assert(h.calls.send[0].opts.language === 'ar', 'switch-processing: in-flight turn stays in the old language (ar)')
  await flush()
  assert(h.session.state === 'speaking', 'switch-processing: old-language reply still spoken')
  h.calls.play[0].handle.resolveDone()
  await flush()
  h.timers.fireNext()
  assert(h.session.state === 'listening', 'switch-processing: loop resumes')
  assert(h.lastListen().lang === 'en-US', 'switch-processing: pending switch applied -> en-US')
  assert(det[det.length - 1] === 'en', 'switch-processing: onLanguageDetected reported en after the turn')
}

// ---------------------------------------------------------------------------
// 15l) LATENCY OBSERVABILITY (Phase 4C.1): every spoken-turn stage traces
//      elapsed_ms from the STT final, in order, plus audio-ready -> playback
//      delay. The turn also proves exactly ONE TTS request and ONE playback
//      handle (no duplicates) and that auto-resume is armed only AFTER the
//      playback reached its genuine `ended`.
// ---------------------------------------------------------------------------
{
  const traces = []
  const h = makeHarness({
    resumeAfterPlaybackEnd: true,
    resumeDelayMs: 150,
    onTrace: (stage, meta) => traces.push({ stage, meta }),
  })
  h.session.start()
  h.fireFinal('What\'s your name?')
  await flush()
  assert(h.session.state === 'speaking', '4c-latency: reached speaking')
  const order = ['stt.final', 'tutor.sent', 'tutor.ok', 'tts.sent', 'tts.ok', 'play.start']
  const idx = order.map((s) => traces.findIndex((t) => t.stage === s))
  assert(idx.every((i) => i !== -1), '4c-latency: every spoken-turn stage is traced')
  assert(idx.every((i, n) => n === 0 || idx[n - 1] < i),
    '4c-latency: stages trace in order (final -> tutor -> TTS -> playback)')
  const el = (s) => traces.find((t) => t.stage === s).meta.elapsedMs
  assert(el('stt.final') === 0, '4c-latency: STT final is the 0ms baseline')
  assert(order.every((s) => Number.isFinite(el(s)) && el(s) >= 0),
    '4c-latency: every stage carries elapsed_ms >= 0')
  assert(el('tutor.sent') <= el('tutor.ok') && el('tutor.ok') <= el('tts.sent') && el('tts.sent') <= el('play.start'),
    '4c-latency: elapsed_ms is monotonic across the turn')
  const play = traces.find((t) => t.stage === 'play.start')
  assert(play.meta.lang === 'en', '4c-latency: trace carries the spoken language')
  assert(typeof play.meta.playDelayMs === 'number' && play.meta.playDelayMs >= 0,
    '4c-latency: audio-ready -> playback-start delta traced')
  assert(traces.filter((t) => t.stage === 'tts.sent').length === 1,
    '4c-latency: exactly ONE TTS request per turn')
  assert(h.calls.synth.length === 1 && h.calls.play.length === 1,
    '4c-latency: one synth call + one playback, no duplicates')
  assert(h.timers.pendingCount() === 0, '4c-latency: no resume armed before the audio ended')
  h.calls.play[0].handle.resolveDone()
  await flush()
  assert(traces.some((t) => t.stage === 'play.end'), '4c-latency: playback reached genuine ended')
  assert(h.timers.pendingCount() === 1, '4c-latency: resume armed only AFTER playback ended')
}

// ---------------------------------------------------------------------------
// 15m) CLOSE/END CANCELS PENDING PLAYBACK/RESUME (Phase 4C.1): after a natural
//      audio end a resume is armed, but leaving the overlay cancels it — the
//      loop must NOT keep listening in the background after the user closes.
// ---------------------------------------------------------------------------
{
  const traces = []
  const h = makeHarness({
    resumeAfterPlaybackEnd: true,
    resumeDelayMs: 200,
    onTrace: (s) => traces.push(s),
  })
  h.session.start()
  h.fireFinal('hello')
  await flush()
  assert(h.session.state === 'speaking', '4c-close: speaking')
  h.calls.play[0].handle.resolveDone()
  await flush()
  assert(h.session.state === 'idle', '4c-close: natural audio end -> idle')
  assert(h.timers.pendingCount() === 1, '4c-close: resume armed after natural end')
  h.session.stop()
  assert(h.timers.pendingCount() === 0, '4c-close: close/end cancels the pending resume')
  assert(!traces.includes('resume.fired'), '4c-close: resume never fired after close')
  assert(h.session.state === 'idle', '4c-close: stays idle (no background listening)')
}

// ---------------------------------------------------------------------------
// 15n) TTS ERROR FALLBACK (Phase 4C.1): a failed synthesis must NOT fake
//      Speaking — it preserves the generated text, surfaces a localized
//      voice-unavailable error, never plays anything, and the user can simply
//      speak again (the loop continues).
// ---------------------------------------------------------------------------
{
  let lastErr = ''
  const h = makeHarness({ onError: (k) => { lastErr = k } })
  h.setSynth(() => Promise.reject(new Error('provider down')))
  h.session.start()
  h.fireFinal('can you help me?')
  await flush()
  assert(h.session.state === 'idle', '4c-fallback: TTS failure -> idle, NO fake Speaking')
  assert(lastErr === 'voice-unavailable', '4c-fallback: voice-unavailable error surfaced')
  assert(h.events.transcripts.some((t) => t.role === 'assistant' && t.text === 'Nice to meet you.'),
    '4c-fallback: generated reply text preserved in the transcript')
  assert(h.calls.play.length === 0, '4c-fallback: nothing was played')
  // Retry / continue: the next utterance is heard and spoken normally.
  h.setSynth(() => Promise.resolve({ blob: {} }))
  h.session.start()
  assert(h.session.state === 'listening', '4c-fallback: retry re-opens listening')
  h.fireFinal('back again')
  await flush()
  assert(h.calls.send.length === 2 && h.calls.send[1].text === 'back again',
    '4c-fallback: the loop continues with the next utterance')
  assert(h.session.state === 'speaking' && h.calls.synth.length === 2 && h.calls.play.length === 1,
    '4c-fallback: retry turn is synthesized and played normally')
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
  assert(/if \(opts\.mode !== 'primary'\) return/.test(hookSrc),
    'sr-guard: interrupt recognizer never self-triggers from a plain result (noise/echo)')
  assert(/rec\.onspeechstart = \(\) => \{ if \(!entry\.cancelled\) opts\.onSpeechStart\?\.\(\) \}/.test(hookSrc),
    'sr-guard: only a real VAD speech-start may barge in')
  const engineSrc = readFileSync(resolve(__dirname, '../src/lib/voiceSession.ts'), 'utf8')
  assert((engineSrc.match(/this\.listenInterrupt\(\)/g) || []).length === 1,
    'sr-guard: no microphone is opened while the mentor speaks (echo loop impossible)')
  const voiceSrc = readFileSync(resolve(__dirname, '../src/components/VoiceMode.tsx'), 'utf8')
  // Phase 4B.2 r2 — explicit Live speech languages: EN | Arabic only, no Auto.
  assert(!/steerAutoRecognition/.test(engineSrc),
    'explicit-live: NO Auto steering path remains (removed)')
  assert(!/steeringTarget|scriptDetectLang/.test(engineSrc),
    'explicit-live: NO script-detection steering helpers remain (removed)')
  assert(!/steerBudget|MAX_STEER_PER_UTTERANCE/.test(engineSrc),
    'explicit-live: NO steering budget remains (removed)')
  assert(!/onInterim/.test(engineSrc) && !/onInterim/.test(hookSrc),
    'explicit-live: NO interim-steering interface remains (engine + hook)')
  assert(!/prefLang/.test(engineSrc),
    'explicit-live: NO Auto preference field remains in the engine')
  assert(/language: 'en' \| 'ar'/.test(engineSrc),
    'explicit-live: the session language is EXPLICIT en|ar (no Auto inside Live)')
  assert(/recognitionLang\(this\.sessionLang\)/.test(engineSrc),
    'explicit-live: recognizer locale always follows the selected session language')
  assert(/setLanguage\(/.test(engineSrc),
    'explicit-live: engine exposes the mid-session language switch')
  assert(/onLanguageDetected\?\.\(this\.turnLang\)/.test(engineSrc),
    'explicit-live: the utterance language is reported before /tutor')
  assert(/language: sessionOpts\?\.language \?\? voiceLang/.test(panelSrc),
    'explicit-live: the voice /tutor turn sends the explicit/selected language, never an Auto fallback')
  assert(/resolveInitialLiveLang/.test(panelSrc),
    'explicit-live: Auto chat preference resolves to an explicit Live language at open')
  assert(/sb_live_lang/.test(hookSrc),
    'explicit-live: the last Live speech language is persisted locally (Auto re-open reuses it)')
  assert(/setLanguage\(/.test(hookSrc),
    'explicit-live: hook exposes the switch for the EN | Arabic selector')
  assert(/v-lang/.test(voiceSrc),
    'explicit-live: compact EN | Arabic selector present in the fullscreen surface')
  assert(/voice\.setLanguage\('en'\)/.test(voiceSrc) && /voice\.setLanguage\('ar'\)/.test(voiceSrc),
    'explicit-live: selector buttons switch the live session to en / ar')
  assert(/aria-pressed=\{voice\.language === 'en'\}/.test(voiceSrc),
    'explicit-live: selector exposes the active language to assistive tech')
  // Phase 4C.1 — latency observability plumbing (developer traces only).
  assert(/elapsedMs/.test(engineSrc),
    '4c-latency: engine traces elapsed_ms on every spoken-turn stage')
  assert(/playDelayMs/.test(engineSrc),
    '4c-latency: audio-ready -> playback-start delta is traced')
  assert(/console\.info\('\[voice-live\]'/.test(hookSrc),
    '4c-latency: stage traces appear ONLY in the developer console (never the UI)')
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