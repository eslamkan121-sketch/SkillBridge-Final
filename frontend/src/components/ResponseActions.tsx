import React from 'react'
import type { TutorMessage } from '../lib/types'
import type { LangStrings } from '../lib/tutorI18n'
import { IconCheck, IconCopy, IconRefresh, IconShare, IconSpeaker, IconThumbsDown, IconThumbsUp } from './Icons'

export type ResponseRating = 'up' | 'down'

/** Compact per-message action row shown only under AI/assistant replies. */
export function ResponseActions({ message, ui, copied, rating, disabled, shareDisabled, retrying, speaking, audioDisabled, onCopy, onRate, onShare, onRetry, onToggleSpeak }: {
  message: TutorMessage
  ui: LangStrings
  copied: boolean
  rating: ResponseRating | null
  disabled: boolean
  shareDisabled: boolean
  retrying: boolean
  speaking: boolean
  audioDisabled: boolean
  onCopy: () => void
  onRate: (value: ResponseRating) => void
  onShare: () => void
  onRetry: () => void
  onToggleSpeak: () => void
}) {
  return (
    <div className="response-actions" role="group" aria-label={ui.responseActions}>
      <button
        type="button"
        className="ra-btn"
        onClick={onCopy}
        disabled={disabled}
        aria-label={ui.copyResponse}
        title={copied ? ui.copied : ui.copy}
      >
        {copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
      </button>
      <button
        type="button"
        className={`ra-btn ${rating === 'up' ? 'active' : ''}`}
        onClick={() => onRate('up')}
        disabled={disabled}
        aria-label={ui.rateHelpful}
        aria-pressed={rating === 'up'}
        title={ui.tipHelpful}
      >
        <IconThumbsUp size={14} />
      </button>
      <button
        type="button"
        className={`ra-btn ${rating === 'down' ? 'active' : ''}`}
        onClick={() => onRate('down')}
        disabled={disabled}
        aria-label={ui.rateNotHelpful}
        aria-pressed={rating === 'down'}
        title={ui.tipNotHelpful}
      >
        <IconThumbsDown size={14} />
      </button>
      <button
        type="button"
        className={`ra-btn ra-audio ${speaking ? 'playing' : ''}`}
        onClick={onToggleSpeak}
        disabled={audioDisabled}
        aria-label={speaking ? ui.stopPlayback : ui.readAloud}
        aria-pressed={speaking}
        title={speaking ? ui.tipStopAudio : ui.tipReadAloud}
      >
        {speaking ? (
          <span className="ra-stop" aria-hidden="true"><span className="ra-stop-sq" /></span>
        ) : (
          <IconSpeaker size={17} />
        )}
      </button>
      <span className={`ra-eq ${speaking ? 'on' : ''}`} aria-hidden="true"><i></i><i></i><i></i></span>
      <span className="ra-divider" aria-hidden="true" />
      <button
        type="button"
        className="ra-btn"
        onClick={onShare}
        disabled={disabled || shareDisabled}
        aria-label={ui.shareResponse}
        title={ui.tipShare}
      >
        <IconShare size={14} />
      </button>
      <button
        type="button"
        className={`ra-btn ${retrying ? 'retrying' : ''}`}
        onClick={onRetry}
        disabled={disabled || retrying}
        aria-label={ui.tryAgain}
        title={retrying ? ui.retrying : ui.tipRetry}
      >
        <IconRefresh size={14} />
      </button>
    </div>
  )
}