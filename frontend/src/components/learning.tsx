import React from 'react'
import type { LearningItem, LearningResource, PersonalizedPath, SkillGap, TutorMode } from '../lib/types'
import { GapPill } from './widgets'
import { humanizeTopicLabel } from '../lib/topicLabels'
import { TUTOR_PROFILES, tutorProfileById } from '../lib/tutorProfiles'
import type { TutorId, TutorProfile } from '../lib/tutorProfiles'
import {
  IconArrowRight,
  IconAssessment,
  IconBook,
  IconChat,
  IconCheck,
  IconClipboard,
  IconExternal,
  IconLightbulb,
  IconRoadmap,
  IconSearch,
  IconSparkles,
  IconTarget,
  IconTutor,
} from './Icons'

export type { TutorId, TutorProfile } from '../lib/tutorProfiles'
export { TUTOR_PROFILES, tutorProfileById }
export type LearningTab = 'for-you' | 'my-skills' | 'continue' | 'completed'

/** Sanctioned working modes of the Global Copilot, in UI order. */
export const TUTOR_MODES: TutorMode[] = ['chat', 'practice', 'discuss', 'interview']

/** The mode each persona arrives in; students may switch at any time. Vex
 * arrives in chat like every tutor: 'interview' is a live Mock-Interview
 * session mode (started only by the dedicated Interview flow), never a
 * standing working mode — otherwise every fresh Vex chat becomes an interview.
 */
export const TUTOR_DEFAULT_MODES: Record<TutorId, TutorMode> = {
  nova: 'chat',
  axel: 'practice',
  sage: 'discuss',
  vex: 'chat',
}

export function isTutorMode(value: string): value is TutorMode {
  return value === 'chat' || value === 'practice' || value === 'discuss' || value === 'interview'
}

export function progressFor(item?: LearningItem, fallback = 0) {
  const total = item?.roadmap?.steps?.length || 0
  const done = item?.progress?.length || 0
  if (!total) return { done, total, pct: fallback, hasRoadmap: false, complete: false }
  const pct = Math.round((done / total) * 100)
  return { done, total, pct, hasRoadmap: true, complete: done >= total }
}

export function topicProgressFor(path?: PersonalizedPath | null, fallback = 0) {
  const total = path?.items?.length || 0
  const completedIds = new Set(path?.progress ?? [])
  const done = path?.items?.filter((item) => completedIds.has(item.id)).length || 0
  if (!total) return { done, total, pct: fallback, hasTopics: false, complete: fallback >= 100 }
  const pct = Math.round((done / total) * 100)
  return { done, total, pct, hasTopics: true, complete: done >= total }
}

export type TopicProgressSummary = ReturnType<typeof topicProgressFor>

export function SearchBar({ value, onChange, placeholder }: {
  value: string
  onChange: (value: string) => void
  placeholder: string
}) {
  return (
    <div className="learning-search">
      <IconSearch size={20} />
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
    </div>
  )
}

export function LearningTabs({ active, counts, onChange }: {
  active: LearningTab
  counts: Record<LearningTab, number>
  onChange: (tab: LearningTab) => void
}) {
  const tabs: { id: LearningTab; label: string }[] = [
    { id: 'for-you', label: 'For You' },
    { id: 'my-skills', label: 'My Skills' },
    { id: 'continue', label: 'Continue Learning' },
    { id: 'completed', label: 'Completed' },
  ]
  return (
    <div className="learning-tabs" role="tablist" aria-label="Learning views">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          className={active === tab.id ? 'active' : ''}
          onClick={() => onChange(tab.id)}
          role="tab"
          aria-selected={active === tab.id}
        >
          <span>{tab.label}</span>
          <small>{counts[tab.id]}</small>
        </button>
      ))}
    </div>
  )
}

export function LearningProgress({ done, total, label = 'Personalized topic progress' }: {
  done: number
  total: number
  label?: string
}) {
  const pct = total ? Math.round((done / total) * 100) : 0
  return (
    <div className="learning-progress">
      <div className="lp-copy">
        <span>{label}</span>
        <strong>{pct}%</strong>
      </div>
      <div className="lp-track"><span style={{ width: `${pct}%` }} /></div>
      <div className="lp-meta">{done}/{total || 0} topics completed</div>
    </div>
  )
}

export function CareerProgress({ completed, inProgress, notStarted }: {
  completed: number
  inProgress: number
  notStarted: number
}) {
  const total = Math.max(1, completed + inProgress + notStarted)
  return (
    <div className="career-progress">
      <div className="cp-head">
        <span>Learning status</span>
        <strong>{completed + inProgress + notStarted} skills</strong>
      </div>
      <div className="cp-track" aria-label="Learning status distribution">
        <span className="done" style={{ width: `${(completed / total) * 100}%` }} />
        <span className="active" style={{ width: `${(inProgress / total) * 100}%` }} />
        <span className="idle" style={{ width: `${(notStarted / total) * 100}%` }} />
      </div>
      <div className="cp-legend">
        <span><i className="done" /> Completed {completed}</span>
        <span><i className="active" /> In progress {inProgress}</span>
        <span><i className="idle" /> Not started {notStarted}</span>
      </div>
    </div>
  )
}

export function SkillCard({ gap, path, selected, onSelect, onStart }: {
  gap: SkillGap
  path?: PersonalizedPath | null
  selected?: boolean
  onSelect: () => void
  onStart: () => void
}) {
  const fallback = gap.status === 'strong' ? 100 : 0
  const progress = topicProgressFor(path, fallback)
  const canGenerate = gap.status !== 'strong'
  const progressLabel = progress.hasTopics
    ? `${progress.done}/${progress.total} topics`
    : gap.status === 'strong' ? 'Ready' : 'Diagnostic needed'
  const cta = path
    ? progress.complete ? 'Review Path' : 'Continue Learning'
    : 'Start Learning'
  return (
    <article className={`learning-skill-card ${selected ? 'selected' : ''}`} onClick={onSelect}>
      <div className="lsc-head">
        <div>
          <h3>{gap.skill_name}</h3>
          <span>{gap.category}</span>
        </div>
        <GapPill status={gap.status} />
      </div>
      <div className="lsc-progress">
        <div className="lsc-track"><span style={{ width: `${progress.pct}%` }} /></div>
        <strong>{progressLabel}</strong>
      </div>
      <div className="lsc-meta">
        <span>Required: {gap.required_level}</span>
        <span>{gap.student_level ? `You: ${gap.student_level}` : 'Missing evidence'}</span>
      </div>
      <div className="lsc-foot">
        <span className="priority-pill neutral">Current order</span>
        {canGenerate ? (
          <button className="btn btn-primary btn-sm" onClick={(e) => { e.stopPropagation(); onStart() }}>
            <IconArrowRight size={14} /> {cta}
          </button>
        ) : (
          <span className="verified-mini"><IconCheck size={13} /> Ready</span>
        )}
      </div>
    </article>
  )
}

export function ContinueLearningCard({ gap, path, onSelect }: {
  gap: SkillGap
  path: PersonalizedPath
  onSelect: () => void
}) {
  const progress = topicProgressFor(path)
  const completedIds = new Set(path.progress ?? [])
  const currentTopic = path.items.find((topic) => !completedIds.has(topic.id)) || path.items[0]
  return (
    <article className="continue-card">
      <div>
        <span className="cc-kicker">{gap.skill_name}</span>
        <h3>{humanizeTopicLabel(currentTopic?.title || 'Personalized path')}</h3>
        <p>{progress.done}/{progress.total || 0} topics complete</p>
      </div>
      <div className="cc-right">
        <strong>{progress.pct}%</strong>
        <div className="cc-track"><span style={{ width: `${progress.pct}%` }} /></div>
      </div>
      <div className="cc-actions">
        <button className="btn btn-primary btn-sm" onClick={onSelect}>
          <IconArrowRight size={14} /> Continue Learning
        </button>
        <button className="btn btn-sm" onClick={onSelect}>
          <IconAssessment size={14} /> Practice Now
        </button>
      </div>
    </article>
  )
}

export function TutorSelector({ selected, onSelect, compact, disabled }: {
  selected: TutorId
  onSelect: (id: TutorId) => void
  compact?: boolean
  disabled?: boolean
}) {
  if (compact) {
    return (
      <div className="tutor-selector tutor-selector-compact">
        <div className="tutor-card-grid tutor-card-grid-compact">
          {TUTOR_PROFILES.map((tutor) => (
            <button
              key={tutor.id}
              className={`tutor-card ${tutor.theme} ${selected === tutor.id ? 'selected' : ''}`}
              onClick={() => onSelect(tutor.id)}
              aria-pressed={selected === tutor.id}
              disabled={disabled}
              title={`${tutor.name} — ${tutor.specialty}`}
            >
              <img src={tutor.avatar} alt={tutor.name} />
            </button>
          ))}
        </div>
      </div>
    )
  }
  return (
    <div className="tutor-selector">
      <div className="section-title-row">
        <div>
          <p className="eyebrow">Choose your AI Tutor</p>
          <h3>Pick the coaching style</h3>
        </div>
      </div>
      <div className="tutor-card-grid">
        {TUTOR_PROFILES.map((tutor) => (
          <button
            key={tutor.id}
            className={`tutor-card ${tutor.theme} ${selected === tutor.id ? 'selected' : ''}`}
            onClick={() => onSelect(tutor.id)}
            aria-pressed={selected === tutor.id}
            disabled={disabled}
          >
            <img src={tutor.avatar} alt={`${tutor.name}, ${tutor.gender.toLowerCase()} ${tutor.focus.toLowerCase()} tutor`} />
            <span className="tc-copy">
              <strong>{tutor.name}</strong>
              <span>{tutor.specialty}</span>
              <em>{tutor.role}</em>
              <small>{tutor.origin} — {tutor.traits.slice(0, 3).join(' · ')}</small>
            </span>
            {selected === tutor.id && (
              <span className="tc-selected"><IconCheck size={12} /> Selected</span>
            )}
          </button>
        ))}
      </div>
    </div>
  )
}

export function TutorIdentity({ tutor }: { tutor: TutorProfile }) {
  return (
    <div className={`tutor-identity ${tutor.theme}`}>
      <img src={tutor.avatar} alt={`${tutor.name}, ${tutor.gender.toLowerCase()} ${tutor.focus.toLowerCase()} tutor`} />
      <div>
        <span>{tutor.name}</span>
        <strong>{tutor.role}</strong>
        <small>{tutor.purpose}</small>
      </div>
    </div>
  )
}

/** Expanded identity card: avatar, origin, specialty, traits, best-for, languages. */
export function TutorAbout({ tutor }: { tutor: TutorProfile }) {
  return (
    <div className={`tutor-about ${tutor.theme}`}>
      <div className="tutor-about-head">
        <img src={tutor.avatar} alt={tutor.name} />
        <div>
          <span>{tutor.name}</span>
          <small>{tutor.role}</small>
        </div>
      </div>
      <div className="tutor-about-row">
        <strong>Origin</strong>
        <span>{tutor.origin}</span>
      </div>
      <div className="tutor-about-row">
        <strong>Specialty</strong>
        <span>{tutor.specialty}</span>
      </div>
      <div className="tutor-about-row">
        <strong>Traits</strong>
        <span className="tutor-about-chips">
          {tutor.traits.map((trait) => <em key={trait}>{trait}</em>)}
        </span>
      </div>
      <div className="tutor-about-row">
        <strong>Best for</strong>
        <span className="tutor-about-chips">
          {tutor.bestFor.map((item) => <em key={item}>{item}</em>)}
        </span>
      </div>
      <div className="tutor-about-row">
        <strong>Languages</strong>
        <span className="tutor-about-chips">
          {tutor.languages.map((lang) => <em key={lang}>{lang}</em>)}
        </span>
      </div>
    </div>
  )
}

export function QuickActionButton({ children, onClick, disabled }: {
  children: React.ReactNode
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button className="quick-action" onClick={onClick} disabled={disabled}>
      <IconSparkles size={13} /> {children}
    </button>
  )
}

export function ResourceCard({ resource, fallbackRank, skillName }: {
  resource: LearningResource & { times?: number; skills?: Set<string> }
  fallbackRank?: number
  skillName?: string
}) {
  const type = String(resource.type || 'Resource')
  const unavailable = resource.unavailable || (!resource.url && resource.status === 'Unavailable')
  const cta = resource.cta || 'Open Resource'
  const provider = resource.provider || resource.source
  const minutes = resource.estimated_minutes

  if (unavailable) {
    return (
      <div className="resource-card resource-unavailable">
        <span className="resource-type">{type}</span>
        <strong>{resource.title}</strong>
        <small className="resource-card-foot">
          {provider && <span>{provider}</span>}
          <span>Resource unavailable</span>
        </small>
      </div>
    )
  }

  return (
    <a className="resource-card" href={resource.url} target="_blank" rel="noopener noreferrer">
      <span className="resource-type">{type}</span>
      <strong>{resource.title}</strong>
      <small>
        {provider || 'Source'}
        {skillName ? ` - ${skillName}` : ''}
        {resource.helpfulness ? ` - ${resource.helpfulness}` : ''}
        {minutes ? ` · ${minutes} min` : ''}
      </small>
      <span className="resource-card-foot">
        <span>{resource.rank ?? fallbackRank ?? resource.times ?? 1}</span>
        {cta ? <span>{cta}</span> : <IconExternal size={14} />}
      </span>
    </a>
  )
}

export function LessonFlow() {
  const steps = [
    { icon: <IconBook size={16} />, label: 'Learn' },
    { icon: <IconLightbulb size={16} />, label: 'Example' },
    { icon: <IconClipboard size={16} />, label: 'Practice' },
    { icon: <IconChat size={16} />, label: 'Discuss with AI' },
    { icon: <IconAssessment size={16} />, label: 'Mini Check' },
    { icon: <IconArrowRight size={16} />, label: 'Next Lesson' },
  ]
  return (
    <div className="lesson-flow" aria-label="Future lesson flow">
      {steps.map((step) => (
        <span key={step.label}>
          {step.icon}
          {step.label}
        </span>
      ))}
    </div>
  )
}

export function SkillDetailHeader({ gap, item, roleTitle, topicProgress }: {
  gap: SkillGap
  item?: LearningItem
  roleTitle?: string
  topicProgress?: TopicProgressSummary
}) {
  const progress = topicProgress ?? topicProgressFor(null, gap.status === 'strong' ? 100 : 0)
  const progressText = progress.hasTopics
    ? `${progress.done}/${progress.total} topics complete`
    : gap.status === 'strong' ? 'No Learning needed' : 'Diagnostic first'
  return (
    <div className="skill-detail-header">
      <div>
        <p className="eyebrow">Skill Learning View</p>
        <h2>{gap.skill_name}</h2>
        <div className="sd-meta">
          <span>{gap.student_level || 'Beginner'}</span>
          <span>{progressText}</span>
          <span>{gap.category}</span>
          {item && <span>Saved resources available</span>}
        </div>
      </div>
      <div className="why-box">
        <IconTarget size={18} />
        <div>
          <strong>Why this matters</strong>
          <span>Relevant to {roleTitle || 'your selected target role'}</span>
        </div>
      </div>
    </div>
  )
}

export function RoadmapTimeline({ item, onToggleStep }: {
  item: LearningItem
  onToggleStep: (step: number) => void
}) {
  if (!item.roadmap?.steps?.length) return null
  return (
    <div className="path-timeline">
      {item.roadmap.steps.map((step, i) => {
        const n = step.step ?? i + 1
        const done = (item.progress || []).includes(n)
        return (
          <div className={`path-step ${done ? 'done' : ''}`} key={i}>
            <button
              className={`path-step-dot ${done ? 'checked' : ''}`}
              onClick={() => onToggleStep(n)}
              title={done ? 'Mark as not done' : 'Mark as done'}
              aria-label={`Toggle step ${n}`}
            >
              {done ? <IconCheck size={14} /> : n}
            </button>
            <div>
              <strong>{step.title}</strong>
              <p>{step.objective}</p>
              {step.practice && <span className="path-step-task">Task: {step.practice}</span>}
              <small>Checkpoint: {step.checkpoint}</small>
              {step.resource_unavailable ? (
                <span className="path-step-note">Resource unavailable — no validated direct resource yet for this step</span>
              ) : step.resources && step.resources.length > 0 && (
                <ul className="path-step-resources">
                  {step.resources.map((r, ri) => (
                    <li key={`${r.url}-${ri}`}>
                      {r.unavailable ? (
                        <span className="muted">{r.title || 'Resource unavailable'}</span>
                      ) : r.url && /^https?:\/\//.test(r.url) ? (
                        <a href={r.url} target="_blank" rel="noreferrer">{r.title || r.url}</a>
                      ) : (
                        <span className="muted">{r.title || r.type || 'Source'}</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function EmptyLearningState({ title, body }: { title: string; body: string }) {
  return (
    <div className="learning-empty">
      <IconTutor size={24} />
      <strong>{title}</strong>
      <span>{body}</span>
    </div>
  )
}

export function SectionTitle({ eyebrow, title, meta }: { eyebrow?: string; title: string; meta?: string }) {
  return (
    <div className="section-title-row">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h3>{title}</h3>
      </div>
      {meta && <span>{meta}</span>}
    </div>
  )
}
