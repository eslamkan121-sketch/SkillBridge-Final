import React, { useEffect } from 'react'
import type { TutorProfile } from '../lib/tutorProfiles'
import type { VoiceSessionApi } from '../hooks/useVoiceSession'
import type { LangStrings } from '../lib/tutorI18n'
import { MOCKUP_VOICE_SUB, MOCKUP_VOICE_HINT } from '../lib/voiceStates'
import { IconKeyboard, IconXClose } from './Icons'
import { VoiceOrb } from './VoiceOrb'

const ARABIC_RE = /[\u0600-\u06FF]/

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
  const statusText =
    voice.state === 'listening' ? ui.listening
      : voice.state === 'processing' ? ui.thinking
        : voice.state === 'speaking' ? ui.voiceSpeaking.replace('{name}', tutor.name)
          : voice.state === 'interrupted' ? ui.voiceBargeIn
            : ui.voiceReady

  const errorText =
    voice.errorKind === 'mic' ? ui.micDeclined
      : voice.errorKind === 'connection' ? ui.connectionLost
        : voice.error

  const onCenter = () => {
    if (voice.state === 'idle') voice.start()
    else if (voice.state === 'listening') voice.stop()
    else if (voice.state === 'processing' || voice.state === 'speaking') voice.interrupt()
  }

  // Fresh session each open; cleanup tears the engine + playback down.
  useEffect(() => {
    voice.open()
    return () => voice.close()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const lastUser = voice.transcript.filter((t) => t.role === 'user').pop()?.text ?? ''
  const lastAgent = voice.transcript.filter((t) => t.role === 'assistant').pop()?.text ?? ''
  const err = !voice.supported
    ? ui.voiceUnsupported
    : voice.error && errorText
      ? errorText
      : ''

  return (
    <div
      className="voice"
      data-state={voice.state}
      role="dialog"
      aria-modal="true"
      aria-label={ui.voiceModeTitle}
      dir={lang === 'ar' ? 'rtl' : 'ltr'}
    >
      <button type="button" className="v-close" onClick={onClose} aria-label={ui.voiceClose}>
        <IconXClose size={17} />
      </button>

      <div className="v-pill">
        <span className="v-pill-avatar"><img src={tutor.avatar} alt={tutor.name} /></span>
        {tutor.name} <em>·</em> {tutor.specialty}
      </div>

      <div className="v-center">
        <VoiceOrb state={voice.state} onTap={onCenter} />

        <div className="v-state" aria-live="polite">
          <span className="sv sv-idle">{statusText}</span>
          <span className="sv sv-listening">{ui.listening}</span>
          <span className="sv sv-processing">{ui.thinking}</span>
          <span className="sv sv-speaking">{ui.voiceSpeaking.replace('{name}', tutor.name)}</span>
          <span className="sv sv-interrupted">{ui.voiceBargeIn}</span>
        </div>

        <div className="v-sub">
          <span className="sb sb-idle">{MOCKUP_VOICE_SUB.idle[lang]}</span>
          <span className="sb sb-listening">{MOCKUP_VOICE_SUB.listening[lang]}</span>
          <span className="sb sb-processing">{MOCKUP_VOICE_SUB.processing[lang]}</span>
          <span className="sb sb-speaking">{MOCKUP_VOICE_SUB.speaking[lang]}</span>
          <span className="sb sb-interrupted">{MOCKUP_VOICE_SUB.interrupted[lang]}</span>
        </div>

        <div className="eq" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></div>

        <div className="vt vt-idle">
          <div className="tr-row dim"><span className="tr-who tr-who-user">{ui.youTag}</span><span className="tr-text">—</span></div>
          <div className="tr-row dim"><span className="tr-who tr-who-agent">{tutor.name}</span><span className="tr-text">—</span></div>
        </div>

        <div className="vt vt-listening">
          <div className="tr-row live"><span className="tr-who tr-who-user">{ui.youTag}</span><span className="tr-text">{lastUser}<span className="caret"></span></span></div>
          <div className="tr-row dim"><span className="tr-who tr-who-agent">{tutor.name}</span><span className="tr-text">—</span></div>
        </div>

        <div className="vt vt-processing">
          <div className="tr-row"><span className="tr-who tr-who-user">{ui.youTag}</span><span className="tr-text">{lastUser}</span></div>
          <div className="tr-row live"><span className="tr-who tr-who-agent">{tutor.name}</span><span className="tr-text"><span className="dots"><i></i><i></i><i></i></span></span></div>
        </div>

        <div className="vt vt-speaking">
          <div className="tr-row dim"><span className="tr-who tr-who-user">{ui.youTag}</span><span className="tr-text">{lastUser}</span></div>
          <div className="tr-row live"><span className="tr-who tr-who-agent">{tutor.name}</span><span className="tr-text" dir={messageDir(lastAgent)}>{lastAgent}</span></div>
        </div>

        <div className="vt vt-interrupted">
          <div className="tr-row dim"><span className="tr-who tr-who-user">{ui.youTag}</span><span className="tr-text">{lastUser}</span></div>
          <div className="tr-row dim"><span className="tr-who tr-who-agent">{tutor.name}</span><span className="tr-text">{lastAgent ? lastAgent.slice(0, -1) : '—'}<span className="cut">—</span></span></div>
          <div className="tr-row live"><span className="tr-who tr-who-user">{ui.youTag}</span><span className="tr-text"><span className="caret"></span></span></div>
        </div>

        {err && <div className="v-err">{err}</div>}
      </div>

      <div className="v-bottom">
        <button type="button" className="v-keyboard" onClick={onClose} aria-label={ui.voiceKeyboard}>
          <IconKeyboard size={22} />
        </button>
        <button
          type="button"
          className="v-stop"
          onClick={() => voice.stop()}
          disabled={!voice.supported || voice.state === 'idle'}
          aria-label={ui.voiceStop}
        >
          <span className="stop-sq"></span>
        </button>
        <span className="v-hint">
          <span className="vh vh-idle">{MOCKUP_VOICE_HINT.idle[lang]}</span>
          <span className="vh vh-listening">{MOCKUP_VOICE_HINT.listening[lang]}</span>
          <span className="vh vh-processing">{MOCKUP_VOICE_HINT.processing[lang]}</span>
          <span className="vh vh-speaking">{MOCKUP_VOICE_HINT.speaking[lang]}</span>
          <span className="vh vh-interrupted">{MOCKUP_VOICE_HINT.interrupted[lang]}</span>
        </span>
      </div>
    </div>
  )
}