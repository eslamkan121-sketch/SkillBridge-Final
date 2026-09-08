import { useCallback, useEffect, useRef, useState } from 'react'

interface SpeechRecognitionEventLike {
  resultIndex: number
  results: {
    length: number
    [index: number]: {
      isFinal: boolean
      [index: number]: { transcript: string }
    }
  }
}

interface SpeechRecognitionLike {
  lang: string
  interimResults: boolean
  continuous: boolean
  onstart: (() => void) | null
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: ((event: { error?: string; message?: string }) => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike

type BrowserSpeechWindow = Window & typeof globalThis & {
  SpeechRecognition?: SpeechRecognitionConstructor
  webkitSpeechRecognition?: SpeechRecognitionConstructor
}

export interface BrowserSpeechState {
  listening: boolean
  speaking: boolean
  muted: boolean
  supported: boolean
  recognitionSupported: boolean
  synthesisSupported: boolean
  interimTranscript: string
  voices: SpeechSynthesisVoice[]
  voiceKey: string
  error: string | null
}

export interface BrowserSpeechControls extends BrowserSpeechState {
  selectVoice: (key: string) => void
  speak: (text: string) => void
  previewVoice: (text?: string) => void
  warmUpSpeech: () => void
  cancelSpeech: () => void
  startListening: (onFinalTranscript: (text: string) => void, lang?: 'en' | 'ar', onEnd?: () => void) => void
  stopListening: () => void
  setMuted: (muted: boolean) => void
  setVoiceMaybe: (overrides: { rate: number; pitch: number }) => void
}

const STORAGE_KEY = 'skillbridge-interviewer-voice'

function browserWindow(): BrowserSpeechWindow | null {
  return typeof window === 'undefined' ? null : window as BrowserSpeechWindow
}

function voiceSettings(voice?: SpeechSynthesisVoice) {
  if (!voice) return { rate: 1, pitch: 1, volume: 1 }
  const name = voice.name.toLowerCase()
  if (name.includes('google') || name.includes('natural')) return { rate: 1, pitch: 1.05, volume: 1 }
  if (name.includes('zira')) return { rate: 0.95, pitch: 1, volume: 1 }
  if (name.includes('samantha')) return { rate: 1, pitch: 1, volume: 1 }
  if (name.includes('david') || name.includes('mark') || name.includes('male')) return { rate: 1, pitch: 0.95, volume: 1 }
  return { rate: 1, pitch: 1, volume: 1 }
}

function voiceId(voice: SpeechSynthesisVoice) {
  return voice.voiceURI || `${voice.name} ${voice.lang}`
}

function orderVoices(list: SpeechSynthesisVoice[]) {
  const english = list.filter((voice) => voice.lang && voice.lang.toLowerCase().startsWith('en'))
  const ordered = [
    ...english.filter((voice) => /female|woman/i.test(voice.name)),
    ...english.filter((voice) => /male|man/i.test(voice.name)),
    ...english,
    ...list,
  ]
  return ordered.filter((voice, index, arr) =>
    arr.findIndex((item) => item.name === voice.name && item.lang === voice.lang) === index)
}

function canUseRecognition(win: BrowserSpeechWindow) {
  const secureEnough = win.location.protocol === 'https:' ||
    win.location.hostname === 'localhost' ||
    win.location.hostname === '127.0.0.1'
  return secureEnough
}

/** Arabic-script detection for Arabic synthesis/recognition (Step 4). */
export function hasArabicText(text: string) {
  return /[\u0600-\u06FF]/.test(text)
}

export function useBrowserSpeech(): BrowserSpeechControls {
  const win = browserWindow()
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const mutedRef = useRef(false)
  const voiceKeyRef = useRef('')
  const busyUtteranceRef = useRef<SpeechSynthesisUtterance | null>(null)
  const resumePollRef = useRef<number | null>(null)
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([])
  const [voiceKey, setVoiceKey] = useState('')
  const [listening, setListening] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  const [muted, setMutedState] = useState(false)
  const [interimTranscript, setInterimTranscript] = useState('')
  const [error, setError] = useState<string | null>(null)

  const synthesisSupported = !!win?.speechSynthesis
  const Recognition = win?.SpeechRecognition || win?.webkitSpeechRecognition
  const recognitionSupported = !!Recognition
  const supported = synthesisSupported || recognitionSupported

  const resolveVoice = useCallback((key: string) =>
    voices.find((voice) => voice.voiceURI === key) ||
    voices.find((voice) => `${voice.name} ${voice.lang}` === key),
  [voices])

  const preferredVoice = useCallback(() =>
    resolveVoice(voiceKeyRef.current) ||
    voices.find((voice) => voice.name.toLowerCase().includes('google')) ||
    voices.find((voice) => voice.name.toLowerCase().includes('natural')) ||
    voices.find((voice) => /microsoft.*zira|apple.*samantha/i.test(voice.name)) ||
    voices.find((voice) => /female|woman/i.test(voice.name)) ||
    voices[0],
  [resolveVoice, voices])

  // Prefer an installed Arabic-capable voice (ar-EG first); never crashes when
  // none exists — the existing English pick is used as a graceful fallback.
  const arabicVoice = useCallback(() => {
    const ar = voices.filter((voice) => voice.lang && voice.lang.toLowerCase().startsWith('ar'))
    return ar.find((voice) => voice.lang.toLowerCase().replace('_', '-') === 'ar-eg') || ar[0]
  }, [voices])

  useEffect(() => {
    if (!win?.speechSynthesis) return

    const loadVoices = () => {
      const list = win.speechSynthesis.getVoices()
      if (list.length) setVoices(orderVoices(list))
    }

    loadVoices()
    win.speechSynthesis.addEventListener?.('voiceschanged', loadVoices)
    win.speechSynthesis.onvoiceschanged = loadVoices
    return () => {
      win.speechSynthesis.removeEventListener?.('voiceschanged', loadVoices)
      if (win.speechSynthesis.onvoiceschanged === loadVoices) win.speechSynthesis.onvoiceschanged = null
    }
  }, [win])

  useEffect(() => {
    if (!voices.length || voiceKey) return
    let saved = ''
    try { saved = localStorage.getItem(STORAGE_KEY) || '' } catch { /* ignore storage */ }
    const selected = resolveVoice(saved) || preferredVoice()
    if (!selected) return
    const key = voiceId(selected)
    voiceKeyRef.current = key
    setVoiceKey(key)
  }, [preferredVoice, resolveVoice, voiceKey, voices])

  const selectVoice = useCallback((key: string) => {
    voiceKeyRef.current = key
    setVoiceKey(key)
    try { localStorage.setItem(STORAGE_KEY, key) } catch { /* ignore storage */ }
  }, [])

  const stopResumePoll = useCallback(() => {
    if (resumePollRef.current != null) {
      window.clearInterval(resumePollRef.current)
      resumePollRef.current = null
    }
  }, [])

  const startResumePoll = useCallback(() => {
    stopResumePoll()
    resumePollRef.current = window.setInterval(() => {
      win?.speechSynthesis?.resume()
    }, 10000)
  }, [stopResumePoll, win])

  const cancelSpeech = useCallback(() => {
    win?.speechSynthesis?.cancel()
    busyUtteranceRef.current = null
    stopResumePoll()
    setSpeaking(false)
  }, [win, stopResumePoll])

  useEffect(() => () => {
    recognitionRef.current?.stop()
    stopResumePoll()
    win?.speechSynthesis?.cancel()
  }, [win, stopResumePoll])

  const voiceOverridesRef = useRef<{ rate: number; pitch: number } | null>(null)

  const setVoiceMaybe = useCallback((overrides: { rate: number; pitch: number }) => {
    voiceOverridesRef.current = overrides
  }, [])

  const preferredVoiceRef = useRef<SpeechSynthesisVoice | undefined>(undefined)

  useEffect(() => {
    preferredVoiceRef.current = preferredVoice()
  }, [preferredVoice])

  const speak = useCallback((text: string) => {
    if (!win?.speechSynthesis || mutedRef.current || !text.trim()) return
    if (busyUtteranceRef.current) return
    console.debug('[speech] speak() at', Date.now(), text.slice(0, 40))
    win.speechSynthesis.cancel()
    const utterance = new SpeechSynthesisUtterance(text)
    const arabic = hasArabicText(text)
    const voice = arabic
      ? (arabicVoice() || preferredVoiceRef.current)
      : (preferredVoiceRef.current || voices[0])
    const settings = voiceSettings(voice)
    const overrides = voiceOverridesRef.current
    utterance.rate = overrides?.rate ?? settings.rate
    utterance.pitch = overrides?.pitch ?? settings.pitch
    utterance.volume = settings.volume
    utterance.lang = arabic ? 'ar-EG' : (voice?.lang || 'en-US')
    if (voice) utterance.voice = voice
    utterance.onstart = () => { busyUtteranceRef.current = utterance; setSpeaking(true); startResumePoll() }
    utterance.onend = () => {
      if (busyUtteranceRef.current === utterance) busyUtteranceRef.current = null
      voiceOverridesRef.current = null
      stopResumePoll()
      setSpeaking(false)
    }
    utterance.onerror = () => {
      if (busyUtteranceRef.current === utterance) busyUtteranceRef.current = null
      stopResumePoll()
      setSpeaking(false)
      console.debug('[speech] utterance error at', Date.now())
    }
    win.speechSynthesis.speak(utterance)
  }, [voices, win, startResumePoll, stopResumePoll, arabicVoice])

  const silenceUtterance = useRef<SpeechSynthesisUtterance | null>(null)

  const warmUpSpeech = useCallback(() => {
    if (!win?.speechSynthesis) return
    try {
      win.speechSynthesis.cancel()
      const u = silenceUtterance.current || new SpeechSynthesisUtterance('')
      silenceUtterance.current = u
      u.volume = 0
      u.rate = 10
      win.speechSynthesis.speak(u)
    } catch { /* best effort — some browsers reject empty utterances */ }
  }, [win])

  const previewVoice = useCallback((text?: string) => {
    speak(text || "Hi, I'm your SkillBridge interviewer. Let's get started.")
  }, [speak])

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop()
    setListening(false)
  }, [])

  const startListening = useCallback((onFinalTranscript: (text: string) => void, lang?: 'en' | 'ar', onEnd?: () => void) => {
    if (!win || !Recognition) {
      setError('Voice input is not supported in this browser.')
      return
    }
    if (!canUseRecognition(win)) {
      setError('Voice input requires HTTPS or localhost.')
      return
    }
    cancelSpeech()
    const recognition = new Recognition()
    recognition.lang = lang === 'ar' ? 'ar-EG' : 'en-US'
    recognition.interimResults = true
    recognition.continuous = false
    recognition.onstart = () => {
      setError(null)
      setListening(true)
      setInterimTranscript('')
    }
    recognition.onresult = (event: SpeechRecognitionEventLike) => {
      let finalText = ''
      let interimText = ''
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const text = event.results[i][0].transcript
        if (event.results[i].isFinal) finalText += text
        else interimText += text
      }
      setInterimTranscript(interimText.trim())
      if (finalText.trim()) onFinalTranscript(finalText.trim())
    }
    recognition.onerror = (event) => {
      setListening(false)
      const denied = event?.error === 'not-allowed' || event?.error === 'service-not-allowed'
      setError(denied
        ? 'Microphone permission was denied. You can type your answer instead.'
        : 'Voice input stopped. You can type your answer instead.')
      onEnd?.()
    }
    recognition.onend = () => {
      setListening(false)
      setInterimTranscript('')
      onEnd?.()
    }
    recognitionRef.current = recognition
    recognition.start()
  }, [Recognition, cancelSpeech, win])

  const setMuted = useCallback((nextMuted: boolean) => {
    mutedRef.current = nextMuted
    setMutedState(nextMuted)
    if (nextMuted) cancelSpeech()
  }, [cancelSpeech])

  return {
    listening,
    speaking,
    muted,
    supported,
    recognitionSupported,
    synthesisSupported,
    interimTranscript,
    voices,
    voiceKey,
    error,
    selectVoice,
    speak,
    previewVoice,
    warmUpSpeech,
    cancelSpeech,
    startListening,
    stopListening,
    setMuted,
    setVoiceMaybe,
  }
}
