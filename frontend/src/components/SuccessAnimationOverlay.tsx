import React, { useEffect, useState } from 'react'
import {
  IconLightbulb, IconBook, IconClipboard, IconShield, IconStar, IconSparkles,
} from './Icons'
import type { JourneyNodeDef } from './SkillBridgeJourneyHero'

/**
 * Full-screen navy transition shown once a login/signup succeeds, then auto-routes.
 * Honours prefers-reduced-motion (skips immediately). Never shown on auth failure.
 */

interface Step { icon: 'light' | 'book' | 'clipboard' | 'shield' | 'star'; label: string; color: string }

function StepIcon({ name, size = 30 }: { name: Step['icon']; size?: number }) {
  switch (name) {
    case 'light': return <IconLightbulb size={size} />
    case 'book': return <IconBook size={size} />
    case 'clipboard': return <IconClipboard size={size} />
    case 'shield': return <IconShield size={size} />
    case 'star': return <IconStar size={size} />
  }
}

export default function SuccessAnimationOverlay({
  role,
  onDone,
  durationMs = 3000,
}: {
  role: 'Student' | 'Company' | 'University Admin'
  onDone: () => void
  durationMs?: number
}) {
  const reduce = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  const [line] = useState<Step[]>(() => {
    if (role === 'Company') {
      return [
        { icon: 'light', label: 'Skills', color: '#7C5CFC' },
        { icon: 'book', label: 'Role', color: '#3B82F6' },
        { icon: 'clipboard', label: 'Matching', color: '#14B8A6' },
        { icon: 'shield', label: 'Candidates', color: '#22C55E' },
        { icon: 'star', label: 'Career', color: '#FF6B2C' },
      ]
    }
    if (role === 'University Admin') {
      return [
        { icon: 'light', label: 'Students', color: '#7C5CFC' },
        { icon: 'book', label: 'Skills', color: '#3B82F6' },
        { icon: 'clipboard', label: 'Insights', color: '#14B8A6' },
        { icon: 'shield', label: 'University', color: '#22C55E' },
        { icon: 'star', label: 'Career', color: '#FF6B2C' },
      ]
    }
    return [
      { icon: 'light', label: 'Skills', color: '#7C5CFC' },
      { icon: 'book', label: 'Learning', color: '#3B82F6' },
      { icon: 'clipboard', label: 'Assessment', color: '#14B8A6' },
      { icon: 'shield', label: 'Verified', color: '#22C55E' },
      { icon: 'star', label: 'Career', color: '#FF6B2C' },
    ]
  })
  const copy = role === 'Company'
    ? 'Preparing your talent workspace...'
    : role === 'University Admin'
      ? 'Preparing your university insights...'
      : 'Connecting your learning journey...'
  const [stage, setStage] = useState<'logging' | 'role' | 'welcome'>('logging')
  const [progress, setProgress] = useState(0)

  useEffect(() => {
    if (reduce) { onDone(); return }
    const t1 = window.setTimeout(() => setStage('role'), 380)
    const t2 = window.setTimeout(() => setStage('welcome'), 850)
    const start = Date.now()
    const iv = window.setInterval(() => {
      const p = Math.min(100, ((Date.now() - start) / durationMs) * 100)
      setProgress(p)
      if (p >= 100) { window.clearInterval(iv) }
    }, 24)
    const done = window.setTimeout(onDone, durationMs)
    return () => { window.clearTimeout(t1); window.clearTimeout(t2); window.clearTimeout(done); window.clearInterval(iv) }
  }, [reduce, onDone, durationMs])

  const activeIndex = Math.floor((progress / 100) * line.length)

  return (
    <div className="auth-success-overlay" role="status" aria-live="polite">
      <div className="asv-grid" aria-hidden="true" />
      <div className="asv-logo">
        <div className="brand-mark asv-mark">S</div>
        <span className="wordmark">SkillBridge</span>
      </div>
      <div className="asv-body">
        <h2 className={`asv-stage ${stage === 'logging' ? 'show' : ''}`}>Logging you in...</h2>
        <h2 className={`asv-stage ${stage === 'role' ? 'show' : ''}`}>{copy}</h2>
        <h2 className={`asv-stage asv-welcome ${stage === 'welcome' ? 'show' : ''}`}>
          <IconSparkles size={22} /> Welcome back! Your opportunities are ready.
        </h2>
        <div className="asv-track-wrap">
          <div className="asv-track"><div className="asv-fill" style={{ width: `${progress}%` }} /></div>
        </div>
      </div>
      <div className="asv-journey">
        <svg className="asv-line" aria-hidden="true">
          <defs>
            <linearGradient id="asv-grad" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#7C5CFC" /><stop offset="30%" stopColor="#3B82F6" />
              <stop offset="55%" stopColor="#14B8A6" /><stop offset="78%" stopColor="#22C55E" />
              <stop offset="100%" stopColor="#FF6B2C" />
            </linearGradient>
          </defs>
          <line x1="0" y1="38" x2="100%" y2="38" stroke="url(#asv-grad)" strokeWidth="3" opacity="0.6" strokeLinecap="round" />
        </svg>
        <div className="asv-nodes">
          {line.map((n, i) => (
            <div className={`asv-node ${i < activeIndex ? 'done' : ''} ${i === activeIndex ? 'lit' : ''}`} key={n.label} style={{ ['--nc' as any]: n.color }}>
              <div className="asv-node-ring"><StepIcon name={n.icon} /></div>
              <div className="asv-node-label">{n.label}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
