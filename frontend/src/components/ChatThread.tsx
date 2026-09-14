import React from 'react'
import Markdown from 'react-markdown'
import type { TutorProfile } from '../lib/tutorProfiles'
import type { TutorMessage } from '../lib/types'
import type { LangStrings } from '../lib/tutorI18n'
import { IconCheck, IconCopy, IconStop, IconVolume } from './Icons'

function SafeMarkdown({ children }: { children: React.ReactNode }) {
  return <Markdown>{String(children ?? '')}</Markdown>
}

const ARABIC_RE = /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]/
function messageDir(text: string): 'rtl' | 'ltr' {
  const ar = (text.match(ARABIC_RE) || []).length
  const en = (text.match(/[A-Za-z]/g) || []).length
  return ar > 0 && ar >= en ? 'rtl' : 'ltr'
}

export function ChatThread({ messages, busy, tutor, ui, speakingKey, copiedKey, speakDisabled, onSpeak, onCopy, chips, onChip }: {
  messages: TutorMessage[]
  busy: boolean
  tutor: TutorProfile
  ui: LangStrings
  speakingKey: string | null
  copiedKey: string | null
  speakDisabled: boolean
  onSpeak: (message: TutorMessage) => void
  onCopy: (message: TutorMessage) => void
  chips: { label: string; prompt: string }[]
  onChip: (prompt: string) => void
}) {
  return (
    <div className="thread">
      {messages.map((message) => (
        <div key={message.id} className={`msg ${message.role}`} dir={messageDir(message.content)}>
          {message.role === 'user' ? (
            <div className="user-bubble">{message.content}</div>
          ) : (
            <>
              <span className="assistant-avatar"><img src={tutor.avatar} alt={tutor.name} /></span>
              <div className="msg-col">
                <div className="assistant-bubble">
                  <SafeMarkdown>{message.content}</SafeMarkdown>
                </div>
                <div className="msg-meta">
                  <button
                    type="button"
                    className="btn-speak"
                    onClick={() => onSpeak(message)}
                    disabled={speakDisabled}
                    aria-label={ui.voiceAria}
                    title={speakingKey === `m-${message.id}` ? ui.stopSpeak : ui.speak}
                  >
                    {speakingKey === `m-${message.id}` ? <IconStop size={13} /> : <IconVolume size={13} />}
                  </button>
                  <button
                    type="button"
                    className="btn-copy"
                    onClick={() => onCopy(message)}
                    disabled={speakDisabled}
                    aria-label={ui.copyAria}
                    title={ui.copyAria}
                  >
                    {copiedKey === `m-${message.id}` ? <IconCheck size={13} /> : <IconCopy size={13} />}
                    {ui.copy}
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      ))}
      {busy && (
        <div className="msg" dir="ltr">
          <span className="assistant-avatar"><img src={tutor.avatar} alt={tutor.name} /></span>
          <div className="msg-col">
            <div className="assistant-bubble busy-ellipsis"><span className="dots"><i></i><i></i><i></i></span></div>
          </div>
        </div>
      )}
      {chips.length > 0 && (
        <div className="quick-chips">
          {chips.map((chip) => (
            <button key={chip.label} type="button" className="qchip" disabled={speakDisabled} onClick={() => onChip(chip.prompt)}>
              {chip.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
