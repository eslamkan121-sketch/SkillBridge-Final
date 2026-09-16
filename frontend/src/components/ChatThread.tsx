import React from 'react'
import Markdown from 'react-markdown'
import type { TutorProfile } from '../lib/tutorProfiles'
import type { TutorMessage } from '../lib/types'
import type { LangStrings } from '../lib/tutorI18n'
import { ResponseActions, type ResponseRating } from './ResponseActions'

function SafeMarkdown({ children }: { children: React.ReactNode }) {
  return <Markdown>{String(children ?? '')}</Markdown>
}

const ARABIC_RE = /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]/
function messageDir(text: string): 'rtl' | 'ltr' {
  const ar = (text.match(ARABIC_RE) || []).length
  const en = (text.match(/[A-Za-z]/g) || []).length
  return ar > 0 && ar >= en ? 'rtl' : 'ltr'
}

export function ChatThread({ messages, busy, tutor, ui, speakingKey, copiedKey, speakDisabled, audioDisabled, onSpeak, onCopy, chips, onChip, ratings, retryingKey, shareDisabled, onRate, onShare, onRetry }: {
  messages: TutorMessage[]
  busy: boolean
  tutor: TutorProfile
  ui: LangStrings
  speakingKey: string | null
  copiedKey: string | null
  speakDisabled: boolean
  audioDisabled: boolean
  onSpeak: (message: TutorMessage) => void
  onCopy: (message: TutorMessage) => void
  chips: { label: string; prompt: string }[]
  onChip: (prompt: string) => void
  ratings: Record<string, ResponseRating | null | undefined>
  retryingKey: string | null
  shareDisabled: boolean
  onRate: (message: TutorMessage, rating: ResponseRating) => void
  onShare: (message: TutorMessage) => void
  onRetry: (message: TutorMessage) => void
}) {
return (
    <>
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
                  <ResponseActions
                    message={message}
                    ui={ui}
                    copied={copiedKey === `m-${message.id}`}
                    rating={ratings[`m-${message.id}`] ?? null}
                    disabled={busy || speakDisabled}
                    shareDisabled={shareDisabled}
                    retrying={retryingKey === `m-${message.id}`}
                    speaking={speakingKey === `m-${message.id}`}
                    audioDisabled={audioDisabled}
                    onCopy={() => onCopy(message)}
                    onRate={(rating) => onRate(message, rating)}
                    onShare={() => onShare(message)}
                    onRetry={() => onRetry(message)}
                    onToggleSpeak={() => onSpeak(message)}
                  />
                </div>
              </>
            )}
          </div>
        ))}
        {busy && !retryingKey && (
          <div className="msg" dir="ltr">
            <span className="assistant-avatar"><img src={tutor.avatar} alt={tutor.name} /></span>
            <div className="msg-col">
              <div className="assistant-bubble busy-ellipsis"><span className="dots"><i></i><i></i><i></i></span></div>
            </div>
          </div>
        )}
      </div>
      {chips.length > 0 && (
        <div className="quick-chips">
          {chips.map((chip) => (
            <button key={chip.label} type="button" className="qchip" disabled={speakDisabled} onClick={() => onChip(chip.prompt)}>
              {chip.label}
            </button>
          ))}
        </div>
      )}
    </>
  )
}
