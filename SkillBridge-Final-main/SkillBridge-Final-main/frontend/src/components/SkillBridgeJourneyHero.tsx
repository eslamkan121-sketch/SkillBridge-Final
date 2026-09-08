import React from 'react'
import { IconLightbulb, IconBook, IconClipboard, IconShield, IconStar } from './Icons'

/**
 * The shared "Skills → Learning → Assessment → Verified → Career" journey visual.
 * Used on the login hero (PART 1) and the post-login success animation (PART 2).
 *
 * `data` lets the success animation reorder/label the nodes per role while keeping
 * the same node colors (node 1 = purple, 2 = blue, 3 = teal, 4 = green, 5 = orange).
 */

export interface JourneyNodeDef {
  label: string
  caption: string
  color: string
  icon: string // keyword for which icon to render
}

export const STUDENT_JOURNEY: JourneyNodeDef[] = [
  { label: 'Skills', caption: 'Discover your unique strengths', color: '#7C5CFC', icon: 'bulb' },
  { label: 'Learning', caption: 'Personalized learning paths', color: '#3B82F6', icon: 'book' },
  { label: 'Assessment', caption: 'Measure and track progress', color: '#14B8A6', icon: 'clipboard' },
  { label: 'Verified', caption: 'Prove your skills with integrity', color: '#22C55E', icon: 'shield' },
  { label: 'Career', caption: 'Unlock real-world opportunities', color: '#FF6B2C', icon: 'star' },
]

export const COMPANY_JOURNEY: JourneyNodeDef[] = [
  { label: 'Skills', caption: 'Define the real skills you need', color: '#7C5CFC', icon: 'bulb' },
  { label: 'Job Role', caption: 'Create a role with requirements', color: '#3B82F6', icon: 'target' },
  { label: 'Matching', caption: 'Rank candidates by verified fit', color: '#14B8A6', icon: 'clipboard' },
  { label: 'Candidates', caption: 'Review matched talent profiles', color: '#22C55E', icon: 'shield' },
  { label: 'Career', caption: 'Hire with confidence', color: '#FF6B2C', icon: 'star' },
]

export const UNIVERSITY_JOURNEY: JourneyNodeDef[] = [
  { label: 'Students', caption: 'See the whole cohort at a glance', color: '#7C5CFC', icon: 'bulb' },
  { label: 'Skills', caption: 'Aggregated verified skill data', color: '#3B82F6', icon: 'book' },
  { label: 'Insights', caption: 'Anonymized gap analysis', color: '#14B8A6', icon: 'clipboard' },
  { label: 'University', caption: 'Track readiness over time', color: '#22C55E', icon: 'shield' },
  { label: 'Career', caption: 'Inform curriculum decisions', color: '#FF6B2C', icon: 'star' },
]

function NodeIcon({ name, size = 30 }: { name: string; size?: number }) {
  switch (name) {
    case 'bulb': return <IconLightbulb size={size} />
    case 'book': return <IconBook size={size} />
    case 'clipboard': return <IconClipboard size={size} />
    case 'shield': return <IconShield size={size} />
    case 'target': return <IconStar size={size} />
    case 'star':
    default: return <IconStar size={size} />
  }
}

export default function SkillBridgeJourneyHero({ data = STUDENT_JOURNEY, showCopy = true }: { data?: JourneyNodeDef[]; showCopy?: boolean }) {
  return (
    <>
      <div className="hero-illustration" aria-hidden="true">
        <svg viewBox="0 0 1000 520" preserveAspectRatio="xMidYMid slice">
          <defs>
            <radialGradient id="sbglow1" cx="50%" cy="40%" r="70%">
              <stop offset="0%" stopColor="#1E3A5F" />
              <stop offset="100%" stopColor="#0D1B2A" />
            </radialGradient>
            <filter id="sbglow" x="-60%" y="-60%" width="220%" height="220%">
              <feGaussianBlur stdDeviation="3" result="b" />
              <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>
          <rect width="1000" height="520" fill="url(#sbglow1)" />
          {/* water reflection */}
          <rect y="380" width="1000" height="140" fill="#0A1624" />
          {/* city skyline */}
          <g fill="#12243B">
            <rect x="60" y="300" width="42" height="120" /><rect x="120" y="330" width="34" height="90" />
            <rect x="170" y="280" width="50" height="140" /><rect x="240" y="340" width="30" height="80" />
            <rect x="700" y="290" width="48" height="130" /><rect x="770" y="330" width="36" height="90" />
            <rect x="830" y="300" width="52" height="120" /><rect x="900" y="350" width="40" height="70" />
            <rect x="300" y="320" width="40" height="100" /><rect x="360" y="350" width="30" height="70" />
          </g>
          {/* lit windows */}
          <g fill="#FF9D5C" opacity="0.5">
            <rect x="72" y="312" width="4" height="5" /><rect x="84" y="326" width="4" height="5" />
            <rect x="182" y="292" width="4" height="5" /><rect x="194" y="318" width="4" height="5" />
            <rect x="712" y="302" width="4" height="5" /><rect x="842" y="312" width="4" height="5" />
            <rect x="854" y="344" width="4" height="5" />
          </g>
          {/* bridge towers */}
          <g stroke="#FF9D5C" strokeWidth="2.5" filter="url(#sbglow)" fill="none" opacity="0.9">
            <path d="M160 250V150M840 250V150" strokeWidth="3.5" />
            <path d="M180 250c0-40-10-60-20-80M820 250c0-40 10-60 20-80" />
          </g>
          {/* cables (warm glow) */}
          <path d="M160 150C260 250 400 210 500 215S740 250 840 150" stroke="#FF6B2C" strokeWidth="2" fill="none" filter="url(#sbglow)" opacity="0.95" />
          <path d="M160 150C300 200 420 185 500 190S700 200 840 150" stroke="#FF9D5C" strokeWidth="1.4" fill="none" filter="url(#sbglow)" opacity="0.6" />
          {/* vertical hangers */}
          {Array.from({ length: 11 }).map((_, i) => {
            const x = 170 + i * 33
            return <path key={i} d={`M${x} ${190 + Math.abs(500 - x) * 0.35} v40`} stroke="#FF9D5C" strokeWidth="1" fill="none" opacity="0.5" filter="url(#sbglow)" />
          })}
          {/* road deck */}
          <path d="M140 252H860" stroke="#3B82F6" strokeWidth="5" opacity="0.7" filter="url(#sbglow)" />
          {/* water reflection (cool blue) */}
          <path d="M140 420C300 400 700 400 860 420" stroke="#3B82F6" strokeWidth="2.5" fill="none" opacity="0.35" filter="url(#sbglow)" />
          <path d="M200 460C360 445 640 445 800 460" stroke="#3B82F6" strokeWidth="2" fill="none" opacity="0.25" filter="url(#sbglow)" />
          {/* particles clustered bottom right */}
          {[
            [880, 470, 3, 0.4], [910, 450, 2.5, 0.35], [940, 480, 3.5, 0.45], [960, 440, 2, 0.3],
            [900, 420, 2, 0.3], [860, 490, 2.5, 0.4], [930, 415, 2.5, 0.35], [975, 460, 3, 0.4],
            [890, 435, 1.8, 0.3], [920, 492, 2, 0.35], [850, 455, 1.8, 0.25], [950, 495, 3, 0.4],
          ].map(([x, y, r, o], i) => (
            <circle key={i} cx={x} cy={y} r={r} fill={i % 3 === 0 ? '#FF9D5C' : '#7EC8FF'} opacity={o} />
          ))}
        </svg>
      </div>

      <div className="journey-row">
        <svg className="login-journey-line" aria-hidden="true">
          <defs>
            <linearGradient id="journey-grad" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#7C5CFC" />
              <stop offset="25%" stopColor="#3B82F6" />
              <stop offset="50%" stopColor="#14B8A6" />
              <stop offset="75%" stopColor="#22C55E" />
              <stop offset="100%" stopColor="#FF6B2C" />
            </linearGradient>
          </defs>
          <line x1="0" y1="46" x2="100%" y2="46" stroke="url(#journey-grad)" strokeWidth="2" opacity="0.7" />
          {[0.1, 0.32, 0.54, 0.76, 0.95].map((p, i) => (
            <circle key={i} cx={`${p * 100}%`} cy="46" r="2.4" fill={['#7C5CFC', '#3B82F6', '#14B8A6', '#22C55E', '#FF6B2C'][i]} />
          ))}
        </svg>
        {data.map((n, i) => (
          <div className="journey-node" key={n.label} style={{ ['--nc' as any]: n.color }}>
            <div className="node-ring"><NodeIcon name={n.icon} /></div>
            <div className="node-label">{n.label}</div>
            <div className="node-cap">{n.caption}</div>
          </div>
        ))}
      </div>
    </>
  )
}
