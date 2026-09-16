import React from 'react'
import type { CSSProperties } from 'react'
import type { TutorId } from '../lib/tutorProfiles'
import type { VoiceState } from '../lib/voiceSession'
import { IconChat, IconMic, IconRefresh, IconVolume } from './Icons'

// ONE reusable mentor-aware orb (Phase 4B.1 — Mentor Live).
//
// There is deliberately NO NovaOrb / AxelOrb / SageOrb / VexOrb: every mentor
// renders through this single component. The mentor identity reaches the orb as
// `mentorId` (the canonical TutorId from tutorProfiles.ts); CSS picks up the
// mentor accent via the inherited `--mentor-accent` tokens that the existing
// .copilot-panel.{purple,blue,gold,green} theme classes already declare, and
// the per-mentor motion personality via `[data-mentor]` duration/easing tokens.
//
// Visual state maps 1:1 onto the existing voice state machine (lib/voiceSession)
// — no competing source of truth — plus `'error'` for the engine-reported
// error/connection-lost condition surfaced through `voice.error`.
//
// The orb is pure CSS/native DOM: no WebGL, no Three.js, no canvas, no asset
// loading. `level` (optional 0..1 mic/audio level, when a later phase provides
// one) modulates the listening/speaking glow through `--orb-level`; without it
// the orb falls back to tasteful state-driven animation. `prefers-reduced-motion`
// is honoured in CSS and also accepted as an explicit prop.

export type MentorOrbState = VoiceState | 'error'

export interface MentorOrbProps {
  /** Canonical tutor id — drives the accent and the per-mentor motion. */
  mentorId: TutorId | string
  /** Engine voice state, or 'error' while `voice.error` is set. */
  state: MentorOrbState
  /** Optional microphone/audio level in 0..1 (absent → state-driven visuals). */
  level?: number
  /** Explicit reduced-motion preference (CSS media query also applies). */
  reducedMotion?: boolean
  /** Tap action: start / stop / interrupt depending on the engine state. */
  onTap: () => void
  /** Accessible label for the interactive core. */
  ariaLabel?: string
}

const GLYPH: Record<MentorOrbState, React.ReactNode> = {
  idle: <IconMic size={30} />,
  listening: <IconMic size={30} />,
  processing: <IconChat size={26} />,
  speaking: <IconVolume size={30} />,
  interrupted: <IconMic size={30} />,
  error: <IconRefresh size={28} />,
}

export function MentorOrb({ mentorId, state, level, reducedMotion, onTap, ariaLabel }: MentorOrbProps) {
  const style = level == null ? undefined : ({ '--orb-level': String(level) } as CSSProperties)
  return (
    <div
      className="ml-orb"
      data-mentor={mentorId}
      data-state={state}
      data-reduced={reducedMotion ? 'true' : undefined}
      style={style}
      aria-hidden="true"
    >
      <span className="ml-halo" aria-hidden="true" />
      <span className="ml-ring r1" aria-hidden="true" />
      <span className="ml-ring r2" aria-hidden="true" />
      <span className="ml-spin" aria-hidden="true" />
      <button type="button" className="ml-core" onClick={onTap} aria-label={ariaLabel ?? 'Live voice'}>
        <span className="ml-glyph" aria-hidden="true">{GLYPH[state]}</span>
      </button>
    </div>
  )
}