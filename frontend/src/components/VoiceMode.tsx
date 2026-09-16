import React, { useEffect } from 'react'
import { createPortal } from 'react-dom'
import type { TutorProfile } from '../lib/tutorProfiles'
import type { VoiceSessionApi } from '../hooks/useVoiceSession'
import type { LangStrings } from '../lib/tutorI18n'
import { MOCKUP_VOICE_SUB } from '../lib/voiceStates'
import { IconKeyboard, IconMic, IconStop, IconXClose } from './Icons'
import { MentorOrb } from './MentorOrb'
import type { MentorOrbState } from './MentorOrb'

const ARABIC_RE = /[\u0600-\u06FF]/

type AudioContextWindow = Window & typeof globalThis & {
  webkitAudioContext?: typeof AudioContext
}

/**
 * Browser autoplay policies can block the async `audio.play()` that happens
 * AFTER the /tutor + /tutor/tts round trip (no longer inside a user gesture).
 * VoiceMode mounts within the Live-button gesture, so unlock media playback
 * there once: a silent buffer source gets the page's media session started and
 * the subsequent speech blob plays without a console "play() failed" abort.
 */
function primeAutoplay(): void {
  try {
    const win = typeof window === 'undefined' ? null : (window as AudioContextWindow)
    if (!win) return
    const Ctor = win.AudioContext ?? win.webkitAudioContext
    if (!Ctor) return
    const ctx = new Ctor()
    const src = ctx.createBufferSource()
    src.buffer = ctx.createBuffer(1, 1, 22050)
    src.connect(ctx.destination)
    void src.start(0)
    void ctx.resume().then(() => window.setTimeout(() => void ctx.close().catch(() => { /* closed */ }), 0))
  } catch { /* audio unsupported — playback will surface its own error */ }
}

function messageDir(text: string): 'rtl' | 'ltr' {
  const ar = (text.match(ARABIC_RE) || []).length
  const en = (text.match(/[A-Za-z]/g) || []).length
  return ar > 0 && ar >= en ? 'rtl' : 'ltr'
}

export function VoiceMode({ voice, tutor, lang, ui, onClose }: {
  voice: VoiceSessionApi
  tutor: TutorProfile
  lang: 'en' | 'ar'
  ui: LangStrings
  onClose: () => void
}) {
  const errorText =
    voice.errorKind === 'mic' ? ui.micDeclined
      : voice.errorKind === 'connection' ? ui.connectionLost
        : voice.error

  // Engine state remains the single source of truth. While an error is set the
  // orb shows the calm ERROR/… visual and the state line carries the error text
  // instead of "Ready"; otherwise the orb mirrors the engine state 1:1.
  const orbState: MentorOrbState = voice.error ? 'error' : voice.state

  const statusText =
    voice.error ? errorText
      : voice.state === 'listening' ? ui.listening
        : voice.state === 'processing' ? ui.thinking
          : voice.state === 'speaking' ? ui.voiceSpeaking.replace('{name}', tutor.name)
            : voice.state === 'interrupted' ? ui.voiceBargeIn
              : ui.voiceReady

  const onCenter = () => {
    if (voice.state === 'idle') voice.start()
    else if (voice.state === 'listening') voice.stop()
    else if (voice.state === 'processing' || voice.state === 'speaking') voice.interrupt()
  }

  const micLabel =
    voice.state === 'listening' || voice.state === 'processing' || voice.state === 'speaking'
      ? ui.voiceStop
      : ui.tapTheMic

  const stopActive =
    voice.state === 'listening' || voice.state === 'processing' || voice.state === 'speaking'

  // Fresh session each open; cleanup tears the engine + playback down.
  useEffect(() => {
    primeAutoplay()
    voice.open()
    return () => voice.close()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Dedicated fullscreen surface: the normal chat UI and the dashboard behind
  // it must not remain visible, so lock body scroll while the live session is up.
  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [])

  const lastUser = voice.transcript.filter((t) => t.role === 'user').pop()?.text ?? ''
  const lastAgent = voice.transcript.filter((t) => t.role === 'assistant').pop()?.text ?? ''
  const err = !voice.supported
    ? ui.voiceUnsupported
    : voice.error && errorText
      ? errorText
      : ''

  const reduceMotion =
    typeof window !== 'undefined' &&
    !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

  const surface = (
    <div
      className={`voice theme-${tutor.theme}`}
      data-state={voice.state}
      data-error={voice.error ? 'true' : undefined}
      role="dialog"
      aria-modal="true"
      aria-label={ui.voiceModeTitle}
      dir={voice.language === 'ar' ? 'rtl' : 'ltr'}
    >
      <header className="v-top">
        <button type="button" className="v-close" onClick={onClose} aria-label={ui.voiceClose}>
          <IconXClose size={17} />
        </button>

        <div className="v-live">
          <span className="v-live-avatar"><img src={tutor.avatar} alt="" /></span>
          <span className="v-live-name">{tutor.name}</span>
          <span className="v-live-dot" aria-hidden="true">·</span>
          <span className="v-live-tag">{ui.voiceLiveTag}</span>
        </div>

        <div className="v-lang" role="group" aria-label={ui.voiceLanguage}>
          <button
            type="button"
            className={`v-lang-btn${voice.language === 'en' ? ' is-active' : ''}`}
            onClick={() => voice.setLanguage('en')}
            aria-pressed={voice.language === 'en'}
          >
            EN
          </button>
          <span className="v-lang-sep" aria-hidden="true">|</span>
          <button
            type="button"
            className={`v-lang-btn${voice.language === 'ar' ? ' is-active' : ''}`}
            onClick={() => voice.setLanguage('ar')}
            aria-pressed={voice.language === 'ar'}
          >
            عربي
          </button>
        </div>
      </header>

      <div className="v-center">
        <div className="ml-orb-wrap">
          <MentorOrb
            mentorId={tutor.id}
            state={orbState}
            reducedMotion={reduceMotion}
            onTap={onCenter}
            ariaLabel={micLabel}
          />
        </div>

        <div className="v-state" aria-live="polite">
          <span className={`sv sv-${voice.state}`}>{statusText}</span>
        </div>

        <div className="v-sub">
          <span className={`sb sb-${voice.state}`}>{MOCKUP_VOICE_SUB[voice.state][lang]}</span>
        </div>

        <div className="eq" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></div>

        <div className={`vc vc-${voice.state}`} aria-live="polite">
          {voice.state === 'speaking' ? (
            <div className="vc-row vc-agent">
              <span className="vc-text" dir={messageDir(lastAgent)}>{lastAgent}</span>
              <span className="vc-fade" aria-hidden="true" />
            </div>
          ) : voice.state === 'processing' ? (
            <div className="vc-row vc-user">
              <span className="vc-text" dir={messageDir(lastUser)}>{lastUser}</span>
              <span className="dots"><i></i><i></i><i></i></span>
            </div>
          ) : voice.state === 'interrupted' ? (
            <div className="vc-row vc-user">
              <span className="vc-text" dir={messageDir(lastUser)}>{lastUser}<span className="caret" /></span>
            </div>
          ) : voice.state === 'listening' ? (
            <div className="vc-row vc-user">
              <span className="vc-text" dir={messageDir(lastUser)}>{lastUser ? lastUser : '—'}<span className="caret" /></span>
            </div>
          ) : (
            <div className="vc-row vc-idle">
              <span className="vc-text">—</span>
            </div>
          )}
        </div>

        {err && <div className="v-err">{err}</div>}
      </div>

      <footer className="v-bottom">
        <div className="v-dock">
          <button type="button" className="v-keyboard" onClick={onClose} aria-label={ui.voiceKeyboard}>
            <IconKeyboard size={20} />
            <span className="v-kbd-label">{ui.voiceTypeInstead}</span>
          </button>

          <button
            type="button"
            className="v-mic"
            onClick={onCenter}
            disabled={!voice.supported || !studentSafe(voice)}
            aria-label={micLabel}
          >
            {stopActive ? <span className="stop-sq"></span> : <IconMic size={28} />}
          </button>

          <button type="button" className="v-end" onClick={() => { voice.stop(); onClose() }} aria-label={ui.voiceEnd}>
            <IconStop size={15} />
            <span className="v-end-label">{ui.voiceEnd}</span>
          </button>
        </div>
      </footer>
    </div>
  )
  // Portal to <body> so the live surface truly fills the app viewport and the
  // Copilot chat / dashboard can never bleed through.
  return typeof document === 'undefined' ? surface : createPortal(surface, document.body)
}

// Guard-local helper: the mic/stop control stays usable when the engine has an
// error so the user can retry (starts a fresh session from idle), but is locked
// only when speech recognition cannot run at all.
function studentSafe(voice: VoiceSessionApi): boolean {
  return !voice.error || voice.state === 'idle'
}