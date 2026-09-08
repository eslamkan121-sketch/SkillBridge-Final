import React from 'react'
import type { SkillGap } from '../lib/types'
import { IconCheck, IconVerified } from './Icons'

export function SkillTag({ name, level, verified }: { name: string; level: string; verified?: boolean }) {
  if (verified) {
    return (
      <span className="skill-tag verified" title="Verified by passing an assessment">
        <IconVerified size={14} />
        {name}
        {level && <span className="lv">{level}</span>}
      </span>
    )
  }
  return (
    <span className="skill-tag" title="Self-reported (from CV, not yet verified)">
      <span className="u-dot" />
      {name}
      {level && <span className="lv">{level}</span>}
    </span>
  )
}

export function ScoreRing({ value }: { value: number }) {
  const r = 62
  const c = 2 * Math.PI * r
  const pct = Math.max(0, Math.min(100, value))
  const offset = c - (pct / 100) * c
  return (
    <div className="score-ring-view">
      <div className="score-ring">
        <svg width="150" height="150">
          <circle cx="75" cy="75" r={r} fill="none" stroke="var(--slate-100)" strokeWidth="12" />
          <circle
            cx="75" cy="75" r={r} fill="none"
            stroke="var(--coral)" strokeWidth="12" strokeLinecap="round"
            strokeDasharray={c} strokeDashoffset={offset}
          />
        </svg>
        <div className="ring-label">
          <strong>{Math.round(value)}%</strong>
          <small>Match</small>
        </div>
      </div>
    </div>
  )
}

export function GapPill({ status }: { status: SkillGap['status'] }) {
  const map: Record<SkillGap['status'], string> = {
    strong: 'Strong',
    gap: 'Gap',
    missing: 'Missing',
  }
  const labels: Record<SkillGap['status'], string> = {
    strong: 'You meet this requirement',
    gap: 'Present but below required level',
    missing: 'Not present yet',
  }
  return <span className={`pill ${status}`} title={labels[status]}>{map[status]}</span>
}

export function LevelBadge({ verified }: { verified: boolean }) {
  return verified ? (
    <span className="badge verified-badge"><IconCheck size={13} /> Verified</span>
  ) : (
    <span className="badge unverified-badge">Self-reported</span>
  )
}
