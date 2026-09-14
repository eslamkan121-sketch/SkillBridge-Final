import { useCallback, useEffect, useRef, useState } from 'react'
import { VoiceSession } from '../lib/voiceSession'
import type { SpeechRecognitionAdapter, VoiceErrorKind, VoiceSessionAdapters, VoiceState, VoiceTranscriptItem } from '../lib/voiceSession'
import { useTTSPlayer } from './useTTSPlayer'

// React wrapper around the framework-free voice engine
// (frontend/src/lib/voiceSession.ts). Supplies the real browser adapters:
//   - recognition: window.(webkit)SpeechRecognition, mirroring
//     useBrowserSpeech's secure-context rules and lang selection;
//   - tts:          api /tutor/tts blob + <audio> (via useTTSPlayer → the
//     refactored speak/stop mechanics);
//   - send:         caller-supplied abortable api.tutorSendAbortable wrapper
//     (CopilotPanel owns the copilot context payload).
// The engine owns the state machine, barge-in, timeout and stop semantics, so
// all of that is unit-tested in Node with mocked adapters.

type BrowserSpeechWindow = Window & typeof globalThis & {
  SpeechRecognition?: new () => any
  webkitSpeechRecognition?: new () => any
}

function browserWindow(): BrowserSpeechWindow | null {
  return typeof window === 'undefined' ? null : (window as BrowserSpeechWindow)
}

function buildRecognitionAdapter(win: BrowserSpeechWindow, supported: boolean): SpeechRecognitionAdapter {
  const Recognition = win.SpeechRecognition || win.webkitSpeechRecognition
  const secureEnough = () =>
    win.location.protocol === 'https:' ||
    win.location.hostname === 'localhost' ||
    win.location.hostname === '127.0.0.1'

  let current: { rec: any; cancelled: boolean } | null = null

  return {
    hush() {
      if (current) {
        current.cancelled = true
        try { current.rec.stop() } catch { /* not started */ }
      }
      current = null
    },
    listen(opts) {
      if (!Recognition || !supported || !secureEnough()) {
        opts.onError?.()
        return
      }
      const rec = new Recognition()
      const entry = { rec, cancelled: false }
      current = entry
      rec.lang = opts.lang
      rec.interimResults = true
      rec.continuous = false
      rec.onstart = () => { entry.cancelled = false }
      rec.onresult = (event: any) => {
        if (entry.cancelled) return
        let finalText = ''
        if (event && event.results) {
          for (let i = event.resultIndex || 0; i < event.results.length; i += 1) {
            const alt = event.results[i]?.[0]?.transcript
            if (event.results[i].isFinal && alt) finalText += alt
          }
        }
        const text = finalText.trim()
        if (!text) return
        if (opts.mode === 'primary') opts.onFinal?.(text)
        else opts.onSpeechStart?.()
      }
      rec.onspeechstart = () => { if (!entry.cancelled) opts.onSpeechStart?.() }
      rec.onerror = () => { if (!entry.cancelled) opts.onError?.() }
      rec.onend = () => { if (current === entry) current = null }
      try { rec.start() } catch { opts.onError?.() }
    },
  }
}

export interface UseVoiceSessionOptions {
  studentId: number
  tutor: string
  /** Resolved conversation language ('en' | 'ar') — selects the recognizer lang. */
  language: 'en' | 'ar'
  recognitionSupported: boolean
  /** Abortable api.tutorSendAbortable wrapper; must resolve the reply text. */
  send: (text: string, signal: AbortSignal) => Promise<string>
  onAssistantReply?: (text: string) => void
  onUserMessage?: (text: string) => void
}

export interface VoiceSessionApi {
  state: VoiceState
  error: string | null
  errorKind: VoiceErrorKind | null
  transcript: VoiceTranscriptItem[]
  supported: boolean
  replaying: boolean
  open(): void
  close(): void
  start(): void
  stop(): void
  interrupt(): void
  replay(text: string): Promise<'ok' | 'voice-unavailable'>
  abort(): void
}

export function useVoiceSession(opts: UseVoiceSessionOptions): VoiceSessionApi {
  const [state, setState] = useState<VoiceState>('idle')
  const [errorState, setErrorState] = useState<{ kind: VoiceErrorKind; message: string } | null>(null)
  const [transcript, setTranscript] = useState<VoiceTranscriptItem[]>([])

  const sessionRef = useRef<VoiceSession | null>(null)
  const optsRef = useRef(opts)
  optsRef.current = opts
  const callbacksRef = useRef({ onAssistantReply: opts.onAssistantReply, onUserMessage: opts.onUserMessage })
  callbacksRef.current = { onAssistantReply: opts.onAssistantReply, onUserMessage: opts.onUserMessage }

  const player = useTTSPlayer(opts.studentId, opts.tutor)

  useEffect(() => {
    if (!opts.studentId || !opts.recognitionSupported) return
    const win = browserWindow()
    if (!win) return
    const adapters: VoiceSessionAdapters = {
      recognition: buildRecognitionAdapter(win, opts.recognitionSupported),
      tts: player.adapter,
      send: (text, signal) => optsRef.current.send(text, signal),
      schedule: (cb, ms) => window.setTimeout(cb, ms),
      cancelSchedule: (id) => window.clearTimeout(id),
    }
    const session = new VoiceSession(adapters, {
      language: opts.language,
      onState: (s) => setState(s),
      onTranscript: (item) => {
        setTranscript((prev) => [...prev, item])
        if (item.role === 'user') callbacksRef.current.onUserMessage?.(item.text)
      },
      onError: (kind, message) => setErrorState({ kind, message }),
      onAssistantReply: (text) => callbacksRef.current.onAssistantReply?.(text),
    })
    sessionRef.current = session
    return () => {
      session.clear()
      sessionRef.current = null
    }
    // language + player.adapter are deliberately re-created per (student, tutor)
    // change so the recognizer language and TTS voice stay in sync.
  }, [opts.studentId, opts.tutor, opts.language, opts.recognitionSupported, player.adapter])

  // Fire-and-forget: the overlay calls open() on mount to start a fresh session.
  const open = useCallback(() => {
    setErrorState(null)
    setTranscript([])
    sessionRef.current?.clear()
    sessionRef.current?.start()
  }, [])

  const close = useCallback(() => {
    player.abort()
    sessionRef.current?.stop()
  }, [player])

  const start = useCallback(() => {
    setErrorState(null)
    sessionRef.current?.start()
  }, [])

  const stop = useCallback(() => {
    player.abort()
    sessionRef.current?.stop()
  }, [player])

  const interrupt = useCallback(() => {
    sessionRef.current?.interrupt()
  }, [])

  const replay = useCallback(
    (text: string) => player.replay(text),
    [player],
  )

  const abort = useCallback(() => {
    player.abort()
  }, [player])

  return {
    state,
    error: errorState?.message ?? null,
    errorKind: errorState?.kind ?? null,
    transcript,
    supported: opts.recognitionSupported,
    replaying: player.replaying,
    open,
    close,
    start,
    stop,
    interrupt,
    replay,
    abort,
  }
}