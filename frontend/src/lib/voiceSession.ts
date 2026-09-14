// Framework-free SkillBridge voice-session engine.
//
// This module has ZERO React/DOM/browser imports so the exact state machine and
// orchestration (incl. barge-in, timeout, stop) can be unit-tested in Node with
// mocked recognition / TTS / HTTP / timers. The React hooks in
// `../hooks/useVoiceSession.ts` and `../hooks/useTTSPlayer.ts` only provide the
// real browser adapters and subscribe to notifications.
//
// Voice pipeline (ChatGPT-style): browser speech recognition -> existing
// POST /tutor -> existing POST /tutor/tts.
// The transcript is NEVER sent to /tutor/tts and audio is NEVER sent to /tutor.
import type { TutorLanguage } from './types'

export type VoiceState = 'idle' | 'listening' | 'processing' | 'speaking' | 'interrupted'

export type VoiceErrorKind = 'connection' | 'voice-unavailable' | 'mic'

export interface VoiceTranscriptItem {
  id: number
  role: 'user' | 'assistant'
  text: string
}

export type VoiceEvent =
  | { type: 'start' }
  | { type: 'speechFinal'; transcript: string }
  | { type: 'replyReady' }
  | { type: 'audioStart' }
  | { type: 'audioEnd' }
  | { type: 'bargeIn' }
  | { type: 'speakDuringProcessing' }
  | { type: 'interruptedTimeout' }
  | { type: 'stop' }
  | { type: 'error' }

// Exact transition table (task spec):
//   idle -> listening            (user taps the mic)
//   listening -> processing      (STT final result)
//   processing -> speaking       (/tutor reply in; TTS plays)
//   speaking -> idle             (TTS audio finished)
//   speaking -> interrupted      (speech heard while speaking, OR mic while speaking)
//   interrupted -> listening     (400 ms later)
//   processing -> listening      (speech heard while /tutor in flight — keep partial; abort fetch)
//   * -> idle                    (stop / error). Unlisted events are no-ops
//                               (e.g. "empty STT while speaking -> stay").
const ALLOWED: Record<VoiceState, { [K in VoiceEvent['type']]?: VoiceState }> = {
  idle: { start: 'listening' },
  listening: { speechFinal: 'processing', stop: 'idle', error: 'idle' },
  processing: {
    replyReady: 'speaking',
    audioStart: 'speaking',
    speakDuringProcessing: 'listening',
    stop: 'idle',
    error: 'idle',
  },
  speaking: { audioEnd: 'idle', bargeIn: 'interrupted', stop: 'idle', error: 'idle' },
  interrupted: { interruptedTimeout: 'listening', stop: 'idle', error: 'idle' },
}

export function reduceVoice(state: VoiceState, event: VoiceEvent['type']): VoiceState {
  const next = ALLOWED[state]?.[event]
  return next ?? state
}

/** Language tokens required by the browser speech recognizer. */
export function recognitionLang(language: TutorLanguage): string {
  if (language === 'ar') return 'ar-EG'
  return 'en-US'
}

/** Recognizer adapter the engine drives (wraps `SpeechRecognition` in the hook). */
export interface SpeechRecognitionAdapter {
  hush(): void
  listen(opts: {
    mode: 'primary' | 'interrupt'
    lang: string
    onFinal?(transcript: string): void
    onSpeechStart?(): void
    onError?(): void
  }): void
}

/** Audio handle returned by the TTS adapter. `done` resolves on natural end. */
export interface PlaybackHandle {
  stop(): void
  done: Promise<void>
}

/** TTS adapter the engine drives (wraps api.tutorTts + `new Audio()` in the hook). */
export interface VoiceTtsAdapter {
  synthesize(text: string, signal: AbortSignal): Promise<unknown>
  play(payload: unknown): PlaybackHandle
}

export interface VoiceSessionAdapters {
  recognition: SpeechRecognitionAdapter
  tts?: VoiceTtsAdapter
  /** POST /tutor adapter. Returns the assistant reply text. */
  send(text: string, signal: AbortSignal): Promise<string>
  schedule(cb: () => void, ms: number): number
  cancelSchedule(id: number): void
}

export interface VoiceSessionOptions {
  /**
   * Hard guard on the /tutor reply. The backend bounds provider timeouts and
   * the UI spec adds a small buffer around the live backend default.
   */
  replyTimeoutMs?: number
  /** Interrupted -> listening handoff delay (spec: 400 ms). */
  interruptedDelayMs?: number
  language: TutorLanguage
  onState(state: VoiceState): void
  onTranscript(item: VoiceTranscriptItem): void
  onError(kind: VoiceErrorKind, message: string): void
  onAssistantReply?(reply: string): void
}

const DEFAULT_REPLY_TIMEOUT_MS = 65_000
const DEFAULT_INTERRUPTED_DELAY_MS = 400

export class VoiceSession {
  state: VoiceState = 'idle'
  transcript: VoiceTranscriptItem[] = []

  private readonly adapters: VoiceSessionAdapters
  private readonly opts: VoiceSessionOptions
  private readonly replyTimeoutMs: number
  private readonly interruptedDelayMs: number
private itemId = 1
  /** Guards the async /tutor -> TTS reply pipeline (stop/clear/barge-in abort it). */
  private sessionId = 0
  /** Per-listen recognition generation snapshots callbacks that went stale
   *  (superseded by interrupt, barge-in, stop or clear). Independent of
   *  `sessionId`, which guards the async /tutor->TTS reply pipeline -- starting
   *  the interrupt recognizer must NOT cancel the in-flight reply. */
  private recogId = 0
  private sendAbort: AbortController | null = null
  private ttsAbort: AbortController | null = null
  private playback: PlaybackHandle | null = null
  private timeoutId: number | null = null
  private interruptId: number | null = null

  constructor(adapters: VoiceSessionAdapters, opts: VoiceSessionOptions) {
    this.adapters = adapters
    this.opts = opts
    this.replyTimeoutMs = opts.replyTimeoutMs ?? DEFAULT_REPLY_TIMEOUT_MS
    this.interruptedDelayMs = opts.interruptedDelayMs ?? DEFAULT_INTERRUPTED_DELAY_MS
  }

  get error(): string | null {
    return this.currentError
  }

  private currentError: string | null = null

  clear(): void {
    this.voidPending()
    this.transcript = []
    this.currentError = null
    this.transition('stop')
  }

  start(): void {
    if (this.state !== 'idle') return
    this.currentError = null
    this.transition('start')
    this.listenPrimary()
  }

  /** Orbig keyboard/stop: behaves exactly like the spec's barge-in when speaking. */
  stop(): void {
    this.voidPending()
    this.transition('stop')
  }

  private listenPrimary(): void {
    const recogId = ++this.recogId
    this.adapters.recognition.listen({
      mode: 'primary',
      lang: recognitionLang(this.opts.language),
      onFinal: (text) => {
        if (this.recogId !== recogId) return
        this.handlePrimaryFinal(text)
      },
      onSpeechStart: () => {
        if (this.recogId !== recogId) return
        this.bargeIn()
      },
      onError: () => {
        if (this.recogId !== recogId) return
        if (this.state === 'listening') {
          this.currentError = 'Microphone permission required'
          this.transition('error')
          this.transition('stop')
          this.opts.onError('mic', this.currentError)
        }
      },
    })
  }

  private listenInterrupt(): void {
    const recogId = ++this.recogId
    this.adapters.recognition.listen({
      mode: 'interrupt',
      lang: recognitionLang(this.opts.language),
      // STT while the tutor is speaking: any final (incl. empty) leaves the
      // speaking state untouched — only *starting* to speak triggers the
      // barge-in (see onSpeechStart). No transcript event here.
      onFinal: () => {},
      onSpeechStart: () => {
        if (this.recogId !== recogId) return
        this.bargeIn()
      },
    })
  }

  private handlePrimaryFinal(text: string): void {
    if (this.state !== 'listening') return
    const userText = text.trim()
    if (!userText) return
    this.currentError = null
    this.adapters.recognition.hush()
    this.appendTranscript('user', userText)
    this.transition('speechFinal')
    // Keep listening while /tutor is in flight so the user can barge in
    // (speech-start -> bargeIn()'s processing branch aborts the fetch).
    this.listenInterrupt()
    this.reply(userText)
  }

  /** Wait for /tutor (with the hard timeout) then synth + play /tutor/tts. */
  private async reply(userText: string): Promise<void> {
    const session = this.sessionId
    this.sendAbort = new AbortController()
    this.armTimeout()
    let reply: string
    try {
      reply = await this.adapters.send(userText, this.sendAbort.signal)
    } catch {
      if (this.sessionId !== session) return
      if (this.sendAbort?.signal.aborted) return
      this.disarmTimeout()
      if (this.state === 'idle') return
      this.currentError = 'Connection lost — try again'
      this.transition('error')
      this.transition('stop')
      this.opts.onError('connection', this.currentError)
      return
    }
    if (this.sessionId !== session) return
    this.disarmTimeout()
    this.currentError = null
    this.transition('replyReady')
    this.opts.onAssistantReply?.(reply)
    await this.speakReply(reply, session)
  }

  private async speakReply(reply: string, session: number): Promise<void> {
    const tts = this.adapters.tts
    if (!tts) {
      this.appendTranscript('assistant', reply)
      this.transition('stop')
      this.currentError = 'Voice unavailable'
      this.opts.onError('voice-unavailable', this.currentError)
      return
    }
    this.appendTranscript('assistant', reply)
    this.ttsAbort = new AbortController()
    this.listenInterrupt()
    let payload: unknown
    try {
      payload = await tts.synthesize(reply, this.ttsAbort.signal)
    } catch {
      if (this.sessionId !== session) return
      this.transition('stop')
      this.currentError = 'Voice unavailable'
      this.opts.onError('voice-unavailable', this.currentError)
      return
    }
    if (this.sessionId !== session || this.state !== 'speaking') return
    let handle: PlaybackHandle
    try {
      handle = tts.play(payload)
    } catch {
      this.transition('stop')
      this.currentError = 'Voice unavailable'
      this.opts.onError('voice-unavailable', this.currentError)
      return
    }
    this.playback = handle
    this.transition('audioStart')
    handle.done.then(() => {
      if (this.sessionId !== session) return
      this.transition('audioEnd')
    })
  }

  private bargeIn(): void {
    if (this.state === 'speaking') {
      this.recogId += 1
      this.adapters.recognition.hush()
      this.ttsAbort?.abort()
      this.playback?.stop()
      this.playback = null
      // Keep the partial transcript; never send audio/transcript anywhere.
      this.transition('bargeIn')
      this.scheduleInterruptedHandoff()
    } else if (this.state === 'processing') {
      // Speech heard while /tutor is in flight: abort the fetch, keep the
      // partial transcript, and go straight back to listening.
      this.sessionId += 1
      this.recogId += 1
      this.adapters.recognition.hush()
      this.sendAbort?.abort()
      this.sendAbort = null
      this.disarmTimeout()
      this.transition('speakDuringProcessing')
      this.listenPrimary()
    }
  }

  /** User action equivalent of hearing speech (mic tap while speaking). */
  interrupt(): void {
    this.bargeIn()
  }

  private armTimeout(): void {
    this.disarmTimeout()
    this.timeoutId = this.adapters.schedule(() => {
      if (this.state === 'processing') {
        this.sendAbort?.abort()
        this.disarmTimeout()
        this.currentError = 'Connection lost — try again'
        this.transition('error')
        this.transition('stop')
        this.opts.onError('connection', this.currentError)
      }
    }, this.replyTimeoutMs)
  }

  private disarmTimeout(): void {
    if (this.timeoutId != null) {
      this.adapters.cancelSchedule(this.timeoutId)
      this.timeoutId = null
    }
  }

  private appendTranscript(role: 'user' | 'assistant', text: string): void {
    const item: VoiceTranscriptItem = { id: this.itemId++, role, text }
    this.transcript = [...this.transcript, item]
    this.opts.onTranscript(item)
  }

  private voidPending(): void {
    this.sessionId += 1
    this.recogId += 1
    this.adapters.recognition.hush()
    this.sendAbort?.abort()
    this.sendAbort = null
    this.ttsAbort?.abort()
    this.ttsAbort = null
    this.playback?.stop()
    this.playback = null
    this.disarmTimeout()
    this.disarmInterrupt()
  }

  private transition(event: VoiceEvent['type']): void {
    const next = reduceVoice(this.state, event)
    if (next !== this.state) {
      this.state = next
      this.opts.onState(next)
    }
    if (event === 'start' || event === 'interruptedTimeout') {
      // handled by the caller (listenPrimary / listenPrimary after the delay)
    }
  }

  private interruptedHandoff(): void {
    if (this.state !== 'interrupted') return
    this.transition('interruptedTimeout')
    this.listenPrimary()
  }

  private disarmInterrupt(): void {
    if (this.interruptId != null) {
      this.adapters.cancelSchedule(this.interruptId)
      this.interruptId = null
    }
  }

  // The interrupted -> 400 ms -> listening handoff.
  private scheduleInterruptedHandoff(): void {
    this.disarmInterrupt()
    this.interruptId = this.adapters.schedule(() => {
      this.interruptId = null
      this.interruptedHandoff()
    }, this.interruptedDelayMs)
  }
}
