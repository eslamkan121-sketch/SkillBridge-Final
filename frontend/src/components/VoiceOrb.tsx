import React from 'react'
import type { VoiceState } from '../lib/voiceSession'
import { IconChat, IconMic, IconStop, IconVolume } from './Icons'

export function VoiceOrb({ state, onTap }: { state: VoiceState; onTap: () => void }) {
  const glyph =
    state === 'speaking' ? <IconVolume size={26} />
      : state === 'processing' ? <IconChat size={24} />
        : state === 'interrupted' ? <IconStop size={24} />
          : <IconMic size={26} />
  return (
    <div className="orb-wrap">
      <span className="spin-ring" aria-hidden="true" />
      <span className="pulse-ring r1" aria-hidden="true" />
      <span className="pulse-ring r2" aria-hidden="true" />
      <button type="button" className="orb" onClick={onTap} aria-label="Voice session">
        <span className="orb-core">{glyph}</span>
      </button>
    </div>
  )
}