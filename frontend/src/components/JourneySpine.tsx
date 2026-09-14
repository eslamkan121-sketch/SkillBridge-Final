import React from 'react'
import { IconArrowRight, IconCheck, IconBolt, IconTarget, IconBookmark } from './Icons'

// Phase Q (D2/D3) — a pure presentational "unified journey" header for the
// student dashboard. Everything is derived from data the dashboard ALREADY
// has; the phase label is human copy over derived booleans and the match ring
// stays the only readiness number. Reuses existing counts verbatim.

export interface JourneySpineProps {
  analysis?: boolean
  roleTitle: string
  gapCount: number
  verifiedCount: number
  hasCv: boolean
  scenarioCount: number
  trackerCount: number
  interviewCount: number
  nextLabel: string
  // null action = career-ready (D3 hand-off)
  nextAction: 'skills' | 'learning' | 'scenarios' | 'assessments' | null
  onGo: (section: string, focus?: { skillId: number; roleTitle: string }) => void
  onFocus: (target: 'find' | 'track') => void
}

const STAGE_COPY: Record<'build' | 'close' | 'ready' | 'apply', { label: string; sub: string }> = {
  build: { label: '1 · Build evidence', sub: 'Choose a target role, then build real skill evidence through learning and assessments.' },
  close: { label: '2 · Close the gaps', sub: 'Your target role is set — the journey below points at the gaps that matter next.' },
  ready: { label: '3 · Ready for opportunities', sub: 'All required skills are covered and verified. The journey hands off to the live job board.' },
  apply: { label: '4 · Find, apply & track', sub: 'You have reached the interview stage on a tracked application — keep the feed moving.' },
}

function Chip({ tone, children }: { tone: 'idle' | 'active' | 'done'; children: React.ReactNode }) {
  return <span className={`jny-step-chip ${tone}`}>{children}</span>
}

export default function JourneySpine(props: JourneySpineProps) {
  const { analysis, gapCount, verifiedCount, hasCv, scenarioCount, trackerCount, interviewCount,
    nextLabel, nextAction, onGo, onFocus, roleTitle } = props

  // D2 phase derivation: no target -> build; gaps remain -> close; reached
  // interview on a tracked application -> apply; else opportunities -> ready.
  const stage: 'build' | 'close' | 'ready' | 'apply' =
    !analysis ? 'build'
      : gapCount > 0 ? 'close'
        : interviewCount > 0 ? 'apply'
          : 'ready'

  const copy = STAGE_COPY[stage]
  const anyScenario = scenarioCount > 0

  const steps: { key: string; label: string; icon: React.ReactNode; chip: React.ReactNode; cta: React.ReactNode | null }[] = [
    {
      key: 'learn',
      label: 'Learn',
      icon: <IconArrowRight size={14} />,
      chip: !analysis ? <Chip tone="idle">Start here</Chip>
        : gapCount > 0 ? <Chip tone="active">In progress</Chip>
          : <Chip tone="done">Covered</Chip>,
      cta: (
        <button type="button" className="btn btn-sm jny-cta" onClick={() => onGo(analysis ? 'learning' : 'skills')}>
          {analysis ? 'Continue learning' : 'Pick a target role'} <IconArrowRight size={12} />
        </button>
      ),
    },
    {
      key: 'verify',
      label: 'Verify',
      icon: <IconCheck size={14} />,
      chip: verifiedCount === 0
        ? <Chip tone="idle">Not started</Chip>
        : <Chip tone="done">{verifiedCount} verified</Chip>,
      cta: (
        <button type="button" className="btn btn-sm jny-cta" onClick={() => onGo('assessments')}>
          Verify a skill <IconArrowRight size={12} />
        </button>
      ),
    },
    {
      key: 'practice',
      label: 'Practice',
      icon: <IconBolt size={14} />,
      chip: !analysis ? <Chip tone="idle">Needs a target role</Chip>
        : anyScenario ? <Chip tone="active">Ready</Chip>
          : <Chip tone="idle">No scenarios yet</Chip>,
      cta: (
        <button type="button" className="btn btn-sm jny-cta" onClick={() => onGo('scenarios')}>
          Open practice <IconArrowRight size={12} />
        </button>
      ),
    },
    {
      key: 'find',
      label: 'Find',
      icon: <IconTarget size={14} />,
      chip: hasCv ? <Chip tone="active">Live match</Chip> : <Chip tone="idle">Attach a CV</Chip>,
      cta: hasCv ? (
        <button type="button" className="btn btn-sm jny-cta" onClick={() => onFocus('find')}>
          {stage === 'ready' ? 'Find your match & apply' : 'Browse matching jobs'} <IconArrowRight size={12} />
        </button>
      ) : (
        <button type="button" className="btn btn-sm jny-cta" onClick={() => onGo('skills')}>
          Upload a CV <IconArrowRight size={12} />
        </button>
      ),
    },
    {
      key: 'track',
      label: 'Track',
      icon: <IconBookmark size={14} />,
      chip: trackerCount === 0 ? <Chip tone="idle">Not started</Chip> : <Chip tone="active">{trackerCount} saved</Chip>,
      cta: (
        <button type="button" className="btn btn-sm jny-cta" onClick={() => onFocus('track')}>
          Open tracker <IconArrowRight size={12} />
        </button>
      ),
    },
  ]

  return (
    <section className="card jny" aria-label="Your unified journey">
      <div className="jny-head">
        <div className="jny-stage">
          <span className="jny-stage-label">{copy.label}</span>
          <span className="jny-stage-sub">{copy.sub}</span>
        </div>
        <div className="jny-actions">
          {stage === 'build' && (
            <button type="button" className="btn btn-primary btn-sm" onClick={() => onGo('skills')}>
              Choose your target role <IconArrowRight size={13} />
            </button>
          )}
          {stage === 'close' && nextAction && (
            <button type="button" className="btn btn-primary btn-sm" onClick={() => onGo(nextAction)}>
              {nextLabel} <IconArrowRight size={13} />
            </button>
          )}
          {stage === 'ready' && (
            <button type="button" className="btn btn-primary btn-sm" onClick={() => onFocus('find')}>
              Find your match &amp; apply <IconArrowRight size={13} />
            </button>
          )}
          {stage === 'apply' && (
            <button type="button" className="btn btn-primary btn-sm" onClick={() => onFocus('track')}>
              Open your tracker <IconArrowRight size={13} />
            </button>
          )}
        </div>
      </div>
      <div className="jny-steps">
        {steps.map((s, i) => (
          <div className="jny-step" key={s.key}>
            <span className="jny-step-num" aria-hidden="true">Step {i + 1}</span>
            <div className="jny-step-row">
              <span className="jny-step-label">{s.icon} {s.label}</span>
              {s.chip}
            </div>
            {s.cta}
          </div>
        ))}
      </div>
      <p className="jny-foot small muted">
        {stage === 'ready' ? `Career ready for ${roleTitle || 'your target role'}. The board below is your real, current feed — nothing here is invented.`
          : stage === 'close' ? 'The single score above is the match ring; these steps are only derived labels over data you already have.'
            : stage === 'apply' ? `You reached an interview stage on one of your tracked applications (${interviewCount}). The tracker is private to you.`
              : 'Choose a target career to unlock this journey.'}
      </p>
    </section>
  )
}