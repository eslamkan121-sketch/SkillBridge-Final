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

/** Last explicitly selected Live speech language, persisted locally so an Auto
 *  chat preference re-opens Live in the user's last choice. */
const LIVE_LANG_KEY = 'sb_live_lang'

/** Resolve the EXPLICIT Live speech language at the moment Live opens.
 *  An already-explicit chat preference (English / Arabic) decides directly; an
 *  Auto chat preference is never silently treated as English — the last
 *  explicitly selected Live language is reused when one is saved locally, else a
 *  clear deterministic default (English) with the visible EN | عربي control. */
export function resolveInitialLiveLang(pref: string): 'en' | 'ar' {
  if (pref === 'ar') return 'ar'
  if (pref === 'en') return 'en'
  try {
    if (typeof window !== 'undefined' && window.localStorage.getItem(LIVE_LANG_KEY) === 'ar') return 'ar'
  } catch { /* storage unavailable */ }
  return 'en'
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
        // The interrupt recognizer must NEVER self-trigger from a plain final
        // (room noise / speaker echo of the mentor): only a real VAD
        // onSpeechStart below may barge in. Secondary results stay inert.
        if (opts.mode !== 'primary') return
        let finalText = ''
        if (event && event.results) {
          for (let i = event.resultIndex || 0; i < event.results.length; i += 1) {
            const alt = event.results[i]?.[0]?.transcript
            if (event.results[i].isFinal && alt) finalText += alt
          }
        }
        const text = finalText.trim()
        if (!text) return
        opts.onFinal?.(text)
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
  /** The explicit Live speech language ('en' | 'ar'). Live Voice has NO Auto
   *  mode: the user picks English or Arabic, and this fixes the recognizer
   *  locale for the whole session. Mid-session switches go through
   *  `api.setLanguage` (never recreates the session). */
  language: 'en' | 'ar'
  recognitionSupported: boolean
  /** Abortable api.tutorSendAbortable wrapper; must resolve the reply text.
   *  `opts.language` = the explicit Live language to send ('en' | 'ar'). */
  send: (text: string, signal: AbortSignal, opts?: { language?: 'en' | 'ar' }) => Promise<string>
  onAssistantReply?: (text: string) => void
  onUserMessage?: (text: string) => void
  onTrace?: (stage: string, meta?: Record<string, unknown>) => void
  /** Persists the last chosen Live speech language locally (localStorage) so an
   *  Auto chat preference re-opens Live in the last-used language. */
  onLiveLanguageChange?: (lang: 'en' | 'ar') => void
}

export interface VoiceSessionApi {
  state: VoiceState
  error: string | null
  errorKind: VoiceErrorKind | null
  transcript: VoiceTranscriptItem[]
  supported: boolean
  replaying: boolean
  /** The explicit Live speech language ('en' | 'ar'). */
  language: 'en' | 'ar'
  /** Switch the Live speech language mid-session (EN | عربي). Safe: hushes the
   *  current recognizer, applies after playback when the mentor is speaking,
   *  and never recreates the session. */
  setLanguage(lang: 'en' | 'ar'): void
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
  const [detectedLang, setDetectedLang] = useState<'en' | 'ar'>(opts.language === 'ar' ? 'ar' : 'en')

  const sessionRef = useRef<VoiceSession | null>(null)
  const optsRef = useRef(opts)
  optsRef.current = opts
  const callbacksRef = useRef({ onAssistantReply: opts.onAssistantReply, onUserMessage: opts.onUserMessage, onTrace: opts.onTrace })
  callbacksRef.current = { onAssistantReply: opts.onAssistantReply, onUserMessage: opts.onUserMessage, onTrace: opts.onTrace }

  const player = useTTSPlayer(opts.studentId, opts.tutor)

  useEffect(() => {
    if (!opts.studentId || !opts.recognitionSupported) return
    const win = browserWindow()
    if (!win) return
    const adapters: VoiceSessionAdapters = {
      recognition: buildRecognitionAdapter(win, opts.recognitionSupported),
      tts: player.adapter,
      send: (text, signal, sessionOpts) => optsRef.current.send(text, signal, sessionOpts),
      schedule: (cb, ms) => window.setTimeout(cb, ms),
      cancelSchedule: (id) => window.clearTimeout(id),
    }
    const session = new VoiceSession(adapters, {
      language: opts.language,
      // Phase 4B.1 Live: after the mentor's reply finishes playing, return to
      // listening automatically — the user never restarts the mic per turn.
      resumeAfterPlaybackEnd: true,
      resumeDelayMs: 150,
      // Explicit Live language: surface every change (initial + switch) so
      // VoiceMode mirrors direction + captions live.
      onLanguageDetected: (lang) => setDetectedLang(lang),
      // Developer diagnostics: every Live-pipeline stage is logged with the
      // mentor + safe meta. NEVER logs transcripts or secrets.
      onTrace: (stage, meta) => {
        console.info('[voice-live]', stage, { mentor: opts.tutor, lang: opts.language, ...meta })
        callbacksRef.current.onTrace?.(stage, meta)
      },
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

  /** Switch the Live speech language mid-session. The engine applies it safely
   *  (immediately while listening/idle, after playback when speaking); the UI
   *  language updates right away either way, and the last choice is persisted
   *  locally so an Auto chat preference re-opens Live in this language. */
  const setLanguage = useCallback((lang: 'en' | 'ar') => {
    const next = lang === 'ar' ? 'ar' : 'en'
    setDetectedLang(next)
    sessionRef.current?.setLanguage(next)
    try {
      if (typeof window !== 'undefined') window.localStorage.setItem(LIVE_LANG_KEY, next)
    } catch { /* storage unavailable — in-memory state still works */ }
    optsRef.current.onLiveLanguageChange?.(next)
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
    language: detectedLang,
    setLanguage,
    open,
    close,
    start,
    stop,
    interrupt,
    replay,
    abort,
  }
}