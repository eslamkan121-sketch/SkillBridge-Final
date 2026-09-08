import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import { useApp } from '../AppContext'
import { api } from '../lib/api'
import { humanizeTopicLabel } from '../lib/topicLabels'
import type { ActivitySummary, Analysis, CareerRoadmap, DiagnosticQuestion, DiagnosticResult, 
GeneratedDiagnostic, FinalAssessmentStatus, LearningItem, LearningResource, Lesson, LessonPractice, PersonalizedPath, PersonalizedPathItem, PersonalizedPathResponse, PracticeAttempt, SkillGap, 
TopicResult } from '../lib/types'
import {
  CareerProgress,
  ContinueLearningCard,
  EmptyLearningState,
  LearningProgress,
  LearningTabs,
  ResourceCard,
  RoadmapTimeline,
  SearchBar,
  SectionTitle,
  SkillCard,
  SkillDetailHeader,
  topicProgressFor,
  type LearningTab,
} from '../components/learning'
import { IconArrowRight, IconAssessment, IconBolt, IconBook, IconChat, IconCheck, IconChevron, IconClock, IconExternal, IconLock, IconRoadmap, IconShield, IconTarget } from '../components/Icons'

function SafeMarkdown({ children }: { children: React.ReactNode }) {
  return <Markdown>{String(children ?? '')}</Markdown>
}

function resourceTypeLabel(resource: LearningResource) {
  const label = resource.type_label || resource.type || 'Resource'
  if (label === 'doc') return 'Documentation'
  if (label === 'course') return 'Tutorial'
  return label.replace(/_/g, ' ').split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}

function resourceStatus(resource: LearningResource) {
  const label = resource.status
    || (resource.available === true
      ? 'Checked'
      : resource.available === false ? 'Unavailable' : 'Status unknown')
  const key = label.toLowerCase().includes('unavailable')
    ? 'unavailable'
    : label.toLowerCase().includes('checked') ? 'checked' : 'unknown'
  return { label, key }
}

function formatMinutes(mins: number) {
  if (mins < 60) return `${mins}m`
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return m ? `${h}h ${m}m` : `${h}h`
}

function sumPathMinutes(path: PersonalizedPath | null) {
  if (!path) return 0
  return path.items.reduce((sum, it) => sum + (it.estimated_minutes || 0), 0)
}

function categoryToneFor(category: string) {
  const c = (category || '').toLowerCase()
  if (c.includes('security') || c.includes('cyber')) return 'red'
  if (c.includes('devops') || c.includes('infrastruct') || c.includes('cloud') || c.includes('ml')) return 'sky'
  if (c.includes('soft') || c.includes('communi') || c.includes('data')) return 'blue'
  return 'slate'
}

export default function LearningPage({ onNavigate }: {
  onNavigate?: (section: string) => void
}) {
  const { me, applyCopilot } = useApp()
  const studentId = me?.student?.id ?? 0
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [items, setItems] = useState<LearningItem[]>([])
  const [selectedSkillId, setSelectedSkillId] = useState<number | null>(null)
  const [pathsBySkill, setPathsBySkill] = useState<Record<number, PersonalizedPath | null>>({})
  const [learningStart, setLearningStart] = useState<{ skillId: number; signal: number } | null>(null)
  const [lessonFocus, setLessonFocus] = useState<{ skillId: number; competency: string; signal: number } | null>(null)
  const [query, setQuery] = useState('')
  const [topicFilter, setTopicFilter] = useState('all')
  const [activeTab, setActiveTab] = useState<LearningTab>('for-you')
  const [showTop, setShowTop] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [activity, setActivity] = useState<ActivitySummary | null>(null)

  useEffect(() => {
    const onScroll = () => setShowTop(window.scrollY > 600)
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('load', onScroll)
    return () => { window.removeEventListener('scroll', onScroll); window.removeEventListener('load', onScroll) }
  }, [])

  const load = async () => {
    setLoadError('')
    const [aResult, lResult] = await Promise.allSettled([api.analysis(studentId), api.learning(studentId)])
    if (aResult.status === 'fulfilled') setAnalysis(aResult.value)
    else {
      setAnalysis(null)
      setLoadError(aResult.reason?.message || 'Learning analysis is not available yet.')
    }
    if (lResult.status === 'fulfilled') setItems(lResult.value)
    else {
      setItems([])
      setLoadError((prev) => prev || lResult.reason?.message || 'Learning content is not available yet.')
    }
  }

  useEffect(() => { if (studentId) void load() }, [studentId])

  useEffect(() => {
    if (!studentId) return
    let alive = true
    api.studentActivity(studentId)
      .then((a) => { if (alive) setActivity(a) })
      .catch(() => { if (alive) setActivity(null) })
    return () => { alive = false }
  }, [studentId])

  const itemBySkill = useMemo(() => new Map(items.map((item) => [item.skill_id, item])), [items])
  const allGaps = analysis?.skill_gaps || []
  const openGaps = allGaps.filter((gap) => gap.status !== 'strong')
  const openGapSkillKey = openGaps.map((gap) => gap.skill_id).join(',')
  const knownPaths = Object.values(pathsBySkill).filter((path): path is PersonalizedPath => !!path)
  const doneTopics = knownPaths.reduce((sum, path) => sum + topicProgressFor(path).done, 0)
  const totalTopics = knownPaths.reduce((sum, path) => sum + topicProgressFor(path).total, 0)

  useEffect(() => {
    let alive = true
    const ids = openGaps.map((gap) => gap.skill_id)
    if (!studentId || !ids.length) {
      setPathsBySkill({})
      return () => { alive = false }
    }
    Promise.all(ids.map(async (skillId) => {
      try {
        const res = await api.personalizedPath(studentId, skillId)
        return [skillId, 'diagnostic_required' in res ? null : res] as const
      } catch {
        return [skillId, null] as const
      }
    })).then((entries) => {
      if (!alive) return
      setPathsBySkill(Object.fromEntries(entries))
    })
    return () => { alive = false }
  }, [studentId, openGapSkillKey])

  const continueGaps = openGaps.filter((gap) => {
    const path = pathsBySkill[gap.skill_id]
    const progress = topicProgressFor(path)
    return !!path && progress.hasTopics && !progress.complete
  })
  const completedLearningCount = openGaps.filter((gap) => {
    const path = pathsBySkill[gap.skill_id]
    const progress = topicProgressFor(path)
    return !!path && progress.hasTopics && progress.complete
  }).length
  const inProgressCount = openGaps.filter((gap) => {
    const path = pathsBySkill[gap.skill_id]
    const progress = topicProgressFor(path)
    return !!path && progress.hasTopics && progress.done > 0 && !progress.complete
  }).length
  const completedCount = allGaps.filter((gap) => gap.status === 'strong').length + completedLearningCount
  const notStartedCount = openGaps.length - inProgressCount - completedLearningCount

  const tabCounts: Record<LearningTab, number> = {
    'for-you': openGaps.length,
    'my-skills': allGaps.length,
    continue: continueGaps.length,
    completed: completedCount,
  }

  const skillsForTab = useMemo(() => {
    if (activeTab === 'my-skills') return allGaps
    if (activeTab === 'continue') {
      const ids = new Set(continueGaps.map((gap) => gap.skill_id))
      return openGaps.filter((gap) => ids.has(gap.skill_id))
    }
    if (activeTab === 'completed') {
      return allGaps.filter((gap) => {
        const progress = topicProgressFor(pathsBySkill[gap.skill_id])
        return gap.status === 'strong' || (!!pathsBySkill[gap.skill_id] && progress.complete)
      })
    }
    return openGaps
  }, [activeTab, allGaps, openGaps, continueGaps, pathsBySkill])

  const filteredSkills = skillsForTab.filter((gap) => {
    const q = query.trim().toLowerCase()
    if (!q) return true
    return (
      gap.skill_name.toLowerCase().includes(q) ||
      gap.category.toLowerCase().includes(q) ||
      gap.required_level.toLowerCase().includes(q) ||
      (gap.student_level || '').toLowerCase().includes(q)
    )
  })

  useEffect(() => {
    const preferred = openGaps[0] || allGaps[0]
    if (!preferred) return
    if (!selectedSkillId || !allGaps.some((gap) => gap.skill_id === selectedSkillId)) {
      setSelectedSkillId(preferred.skill_id)
    }
  }, [analysis?.role_id, allGaps.length, openGaps.length, selectedSkillId])

  const selectedGap = allGaps.find((gap) => gap.skill_id === selectedSkillId) || filteredSkills[0] || openGaps[0] || allGaps[0]

  const setCopilotCompetency = useCallback((competency: string | null) => {
    applyCopilot({ competency })
  }, [applyCopilot])

  useEffect(() => {
    applyCopilot({ page: 'learning', skillId: selectedGap?.skill_id ?? null, competency: null })
  }, [selectedGap?.skill_id])

  const startLearning = (skillId: number) => {
    setSelectedSkillId(skillId)
    setLearningStart((prev) => ({ skillId, signal: (prev?.signal ?? 0) + 1 }))
    requestAnimationFrame(() => {
      document.getElementById('skill-detail')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }

  const toggleStep = async (item: LearningItem, n: number) => {
    const cur = new Set(item.progress ?? [])
    if (cur.has(n)) cur.delete(n)
    else cur.add(n)
    const steps = [...cur].sort((a, b) => a - b)
    try {
      const updated = await api.learningProgress(studentId, item.skill_id, steps)
      setItems((prev) => prev.map((i) => (i.skill_id === updated.skill_id ? updated : i)))
    } catch {
      /* keep local state unchanged if the save fails */
    }
  }

  const verifiedRequiredSet = new Set(
    (me?.student?.verified_skills ?? [])
      .filter((v) => openGaps.some((g) => g.skill_id === v.skill_id))
      .map((v) => v.skill_id)
  )
  const verifiedRequired = {
    verified: verifiedRequiredSet.size,
    total: openGaps.length,
    pct: openGaps.length ? Math.round((verifiedRequiredSet.size / openGaps.length) * 100) : 0,
  }

  const matchPct = allGaps.length ? Math.round((allGaps.filter((g) => g.status === 'strong').length / allGaps.length) * 100) : null
  const requiredSkillCount = allGaps.length
  const plannedMinutes = knownPaths.reduce((sum, path) => sum + sumPathMinutes(path), 0)

  // Stat-card progress bars need honest denominators: the study-time card is a
  // planned-minutes share of a 7-hour focused-learning goal, the streak card a
  // 30-day-goal share (some of these are illustrative targets, clearly noted in
  // the sub-labels), and skill improvement is the real verified-share %.
  const STUDY_GOAL_MINUTES = 7 * 60
  const STREAK_GOAL_DAYS = 30
  const studyGoalPct = plannedMinutes > 0 ? Math.min(100, Math.round((plannedMinutes / STUDY_GOAL_MINUTES) * 100)) : 0
  const streakGoalPct = activity ? Math.min(100, Math.round((activity.streak_days / STREAK_GOAL_DAYS) * 100)) : 0

  const stepperRows = openGaps.map((gap) => {
    const path = pathsBySkill[gap.skill_id]
    const progress = topicProgressFor(path)
    const doneSet = new Set(path?.progress ?? [])
    const items = path?.items ?? []
    const nextCompetency = items.find((it) => !doneSet.has(it.id))?.competency ?? items[0]?.competency ?? null
    return {
      gap,
      path,
      progress,
      nextCompetency,
      minutes: sumPathMinutes(path),
      status: !path ? 'diagnostic' as const : progress.complete ? 'done' as const : progress.done > 0 ? 'in-progress' as const : 'not-started' as const,
    }
  })
  const currentSkillId = stepperRows.find((r) => r.status !== 'done')?.gap.skill_id ?? null

  const topicCategories = [...new Set(openGaps.map((g) => g.category).filter(Boolean))]
  const visibleStepperRows = topicFilter === 'all' ? stepperRows : stepperRows.filter((r) => r.gap.category === topicFilter)
  const shownStepperRows = visibleStepperRows.slice(0, 8)
  const moreModulesCount = visibleStepperRows.length - shownStepperRows.length

  const openLessonTopic = (skillId: number, competency: string) => {
    if (!competency) return
    setSelectedSkillId(skillId)
    setLessonFocus((prev) => ({ skillId, competency, signal: (prev?.signal ?? 0) + 1 }))
    requestAnimationFrame(() => {
      document.getElementById('skill-detail')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }

  const openChat = () => window.dispatchEvent(new CustomEvent('copilot:focus'))

  const quickDiagnose = () => {
    const first = openGaps[0]
    if (first) startLearning(first.skill_id)
  }
  const quickPractice = () => {
    const row = stepperRows.find((r) => r.status !== 'done')
    if (row) openLessonTopic(row.gap.skill_id, row.nextCompetency ?? '')
  }
  const goAssessments = () => onNavigate?.('assessments')
  const viewAllModules = () => {
    setActiveTab('for-you')
    document.getElementById('learning-home')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  if (!studentId) return <div className="empty">Log in as a student to view your learning path.</div>

  const targetTitle = analysis?.role_title || me?.student?.target_role?.title || ''
  const targetMeta =
    analysis?.company ||
    me?.student?.target_role?.company_name ||
    (targetTitle ? 'Current target from your profile' : 'Choose one from Skills & Roles')

  return (
    <div className="learning-page">
      <section className="learning-hero">
      <div className="hero-art" aria-hidden="true">
        <svg viewBox="0 0 220 220" fill="none" width="220" height="220">
          <circle cx="110" cy="110" r="96" stroke="rgba(148, 197, 231, 0.28)" strokeWidth="1" />
          <circle cx="110" cy="110" r="70" stroke="rgba(148, 197, 231, 0.35)" strokeWidth="1.5" strokeDasharray="3 7" strokeLinecap="round" />
          <path d="M110 36l13 24-5 3-8-6v20h0v-20l-8 6-5-3z" fill="rgba(94, 234, 212, 0.85)" />
          <path d="M96 138l14-14 14 14" stroke="rgba(255, 255, 255, 0.6)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
          <circle cx="110" cy="110" r="30" fill="rgba(255, 107, 44, 0.14)" stroke="rgba(255, 107, 44, 0.55)" strokeWidth="1.5" />
          <circle cx="110" cy="110" r="9" fill="rgba(255, 255, 255, 0.85)" />
          <circle cx="110" cy="110" r="4" fill="var(--sb-coral)" />
          <circle cx="176" cy="56" r="5" fill="rgba(94, 234, 212, 0.6)" />
          <circle cx="52" cy="168" r="4" fill="rgba(255, 107, 44, 0.5)" />
        </svg>
      </div>
        <div className="learning-hero-copy">
          <p className="learning-hero-eyebrow">Learning</p>
          <h1>Build the skills your target role expects.</h1>
          <p>
            Start with a topic diagnostic, follow the personalized path, and complete each topic
            through its Mini Check. The AI Tutor is there when you need a different angle.
          </p>
        </div>
        <div className="hero-target-card">
          <div className="hero-target-card-head"><IconRoadmap size={15} /> Target role</div>
          <div className="hero-target-role">{targetTitle || 'No target selected'}</div>
          {matchPct !== null && (
            <>
              <p className="hero-progress-label">Current skill match <strong>{matchPct}%</strong></p>
              <div className="progress-track"><div className="progress-fill" style={{ width: `${matchPct}%` }} /></div>
            </>
          )}
          <div className="htc-foot">
            <span className="htc-chip">{requiredSkillCount} required</span>
            <span className="htc-chip"><IconCheck size={12} /> {verifiedRequired.verified} verified</span>
          </div>
        </div>
        <SearchBar
          value={query}
          onChange={setQuery}
          placeholder="Search a skill, topic, or ask AI Tutor..."
        />
        <LearningTabs active={activeTab} counts={tabCounts} onChange={setActiveTab} />
      </section>

      <section className="lp-stat-grid" aria-label="Learning stats">
        <article className="lp-stat-card">
          <div className="lp-stat-top">
            <span className="lp-stat-icon blue"><IconAssessment size={18} /></span>
            <div>
              <p className="lp-stat-label">Learning progress</p>
              <p className="lp-stat-value">{totalTopics > 0 ? <>{doneTopics} <small>/ {totalTopics}</small></> : '\u2014'}</p>
            </div>
          </div>
          {totalTopics > 0 ? (
            <>
              <div className="progress-track on-light"><div className="progress-fill" style={{ width: `${Math.round((doneTopics / totalTopics) * 100)}%` }} /></div>
              <p className="lp-stat-sub">topics completed across your personalized path</p>
            </>
          ) : (
            <p className="lp-stat-sub">No path yet — take a topic diagnostic to unlock your plan.</p>
          )}
        </article>

        <article className="lp-stat-card">
          <div className="lp-stat-top">
            <span className="lp-stat-icon teal"><IconClock size={18} /></span>
            <div>
              <p className="lp-stat-label">Total study time</p>
              <p className="lp-stat-value">{plannedMinutes > 0 ? formatMinutes(plannedMinutes) : '\u2014'}</p>
            </div>
          </div>
          <div className="progress-track on-light"><div className="progress-fill" style={{ width: `${studyGoalPct}%`, background: 'var(--sb-teal-dark)' }} /></div>
          <p className="lp-stat-sub">planned across your learning path · vs a 7h goal</p>
        </article>

        <article className="lp-stat-card">
          <div className="lp-stat-top">
            <span className="lp-stat-icon coral"><IconBolt size={18} /></span>
            <div>
              <p className="lp-stat-label">Current streak</p>
              <p className="lp-stat-value">{activity ? <>{activity.streak_days} <small>days</small></> : '\u2014'}</p>
            </div>
          </div>
          <div className="progress-track on-light"><div className="progress-fill" style={{ width: `${streakGoalPct}%`, background: 'var(--sb-coral)' }} /></div>
          <p className="lp-stat-sub">{activity && activity.active_days > 0 ? `${activity.active_days} active days · 30-day goal` : 'from your activity · 30-day goal'}</p>
        </article>

        <article className="lp-stat-card">
          <div className="lp-stat-top">
            <span className="lp-stat-icon green"><IconCheck size={18} /></span>
            <div>
              <p className="lp-stat-label">Skill improvement</p>
              <p className="lp-stat-value">{verifiedRequired.total > 0 ? `${verifiedRequired.pct}%` : '\u2014'}</p>
            </div>
          </div>
          <div className="progress-track on-light"><div className="progress-fill" style={{ width: `${verifiedRequired.total > 0 ? verifiedRequired.pct : 0}%`, background: 'var(--sb-green)' }} /></div>
          <p className="lp-stat-sub">{verifiedRequired.total > 0 ? `${verifiedRequired.verified} of ${verifiedRequired.total} target skills verified` : 'verified via assessments'}</p>
        </article>
      </section>

      <div className="learning-layout">
        <main className="panel path-panel">
          <div className="panel-head">
            <div>
              <div className="panel-title-row">
                <span className="panel-title-icon"><IconTarget size={15} /></span>
                <h3 className="panel-title">Your skill gaps</h3>
              </div>
              <p className="panel-subtitle">One row per skill gap. Start a diagnostic on a gap to build its personalized path, then complete every Mini Check to finish it.</p>
            </div>
            <select className="lp-filter" value={topicFilter} onChange={(e) => setTopicFilter(e.target.value)} aria-label="Filter path by topic category">
              <option value="all">All topics</option>
              {topicCategories.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>

          {visibleStepperRows.length === 0 ? (
            <EmptyLearningState title="No skill gaps yet" body="Select a target role on Skills & Roles to see your gaps and their personalized paths." />
          ) : (
            <>
              <ol className="path-list">
                {shownStepperRows.map((row) => {
                  const n = stepperRows.indexOf(row) + 1
                  return (
                    <li
                      key={row.gap.skill_id}
                      className={`path-item ${row.status === 'done' ? 'is-done' : ''}`}
                      data-current={row.gap.skill_id === currentSkillId}
                    >
                      <span className="path-marker">{row.status === 'done' ? <IconCheck size={13} /> : n}</span>
                      <div className="path-item-body">
                        <span className={`path-icon ${categoryToneFor(row.gap.category)}`}>
                          <IconAssessment size={17} />
                        </span>
                        <div className="path-text">
                          <h3>{row.gap.skill_name}</h3>
                          <p>{row.gap.category} · {row.gap.required_level}{row.gap.verified ? ' · Verified' : ''}</p>
                        </div>
                        <div className="path-progress">
                          <div className="progress-track on-light">
                            <div className="progress-fill" style={{ width: `${row.progress.total ? Math.round((row.progress.done / row.progress.total) * 100) : 0}%` }} />
                          </div>
                          <div className="path-progress-pct">{row.progress.done}/{row.progress.total}</div>
                        </div>
                        {row.status === 'done' ? (
                          <span className="status-pill passed">Completed</span>
                        ) : row.status === 'diagnostic' ? (
                          <button className="btn btn-primary" onClick={() => startLearning(row.gap.skill_id)}>
                            Start <IconArrowRight size={14} />
                          </button>
                        ) : (
                          <button className="btn" onClick={() => openLessonTopic(row.gap.skill_id, row.nextCompetency ?? '')}>
                            {row.status === 'in-progress' ? 'Continue' : 'Start'} <IconArrowRight size={14} />
                          </button>
                        )}
                      </div>
                    </li>
                  )
                })}
              </ol>
              {moreModulesCount > 0 && (
                <button className="btn btn-ghost view-all-modules" onClick={viewAllModules}>
                  +{moreModulesCount} more module{moreModulesCount === 1 ? '' : 's'} <IconArrowRight size={14} />
                </button>
              )}
            </>
          )}
        </main>

        <aside className="right-col">
          <div className="panel lp-tutor-panel">
            <div className="lp-tutor-avatar"><IconChat size={22} /></div>
            <h3 className="panel-title">AI Tutor</h3>
            <p>Chat with our assistant about any topic on your path — it knows your background, current skills, and target role.</p>
            <button className="btn btn-primary btn-block" onClick={openChat}>
              Chat with AI <IconArrowRight size={15} />
            </button>
          </div>

          <div className="panel quick-panel">
            <div className="panel-head" style={{ marginBottom: 12 }}>
              <div className="panel-title-row">
                <span className="panel-title-icon"><IconTarget size={15} /></span>
                <h3 className="panel-title">Quick access</h3>
              </div>
            </div>
            <nav className="quick-list">
              <button className="quick-item" onClick={quickDiagnose}>
                <span className="quick-icon"><IconAssessment size={15} /></span> Take a diagnostic
                <IconArrowRight className="chev" size={14} />
              </button>
              <button className="quick-item" onClick={quickPractice}>
                <span className="quick-icon"><IconBolt size={15} /></span> Practice scenarios
                <IconArrowRight className="chev" size={14} />
              </button>
              <button className="quick-item" onClick={viewAllModules}>
                <span className="quick-icon"><IconBook size={15} /></span> View all learning modules
                <IconArrowRight className="chev" size={14} />
              </button>
              <button className="quick-item" onClick={openChat}>
                <span className="quick-icon"><IconChat size={15} /></span> Join a discussion
                <IconArrowRight className="chev" size={14} />
              </button>
              <button className="quick-item" onClick={goAssessments}>
                <span className="quick-icon"><IconCheck size={15} /></span> Go to Assessment
                <IconArrowRight className="chev" size={14} />
              </button>
            </nav>
            <button className="quick-item tip" onClick={goAssessments}>
              <span className="quick-icon"><IconShield size={15} /></span>
              <span>
                <strong>Tip: Finish assessments to verify your skills</strong>
                <span>Verified skills unlock higher matches — take the next one from the Assessments page.</span>
              </span>
              <IconArrowRight className="chev" size={14} />
            </button>
          </div>
        </aside>
      </div>

      {continueGaps.length > 0 && (
        <section className="learning-section">
          <SectionTitle eyebrow="Continue Learning" title="Pick up where you left off" meta={`${continueGaps.length} active path${continueGaps.length === 1 ? '' : 's'}`} />
          <div className="continue-grid">
            {continueGaps.slice(0, 3).map((gap) => (
              <ContinueLearningCard
                key={gap.skill_id}
                gap={gap}
                path={pathsBySkill[gap.skill_id] as PersonalizedPath}
                onSelect={() => startLearning(gap.skill_id)}
              />
            ))}
          </div>
        </section>
      )}

      <div className="learning-home-grid" id="learning-home">
        <section className="learning-section">
          <SectionTitle
            eyebrow="Recommended Skills"
            title={activeTab === 'my-skills' ? 'Skill map' : activeTab === 'continue' ? 'In-progress paths' : activeTab === 'completed' ? 'Completed skills' : 'Recommended for you'}
            meta={`${filteredSkills.length} shown`}
          />
          {loadError && <div className="error learning-error">{loadError}</div>}
          <div className="learning-skill-grid">
            {filteredSkills.map((gap) => (
              <SkillCard
                key={gap.skill_id}
                gap={gap}
                path={pathsBySkill[gap.skill_id]}
                selected={selectedGap?.skill_id === gap.skill_id}
                onSelect={() => setSelectedSkillId(gap.skill_id)}
                onStart={() => startLearning(gap.skill_id)}
              />
            ))}
          </div>
          {filteredSkills.length === 0 && (
            <EmptyLearningState
              title={query ? 'No skills match that search' : 'No learning items here yet'}
              body={query ? 'Try another skill, category, or topic.' : 'Select a target role on Skills & Roles to unlock dynamic learning recommendations.'}
            />
          )}
        </section>

        <aside className="learning-side">
          <LearningProgress done={doneTopics} total={totalTopics} />
          <CareerProgress
            completed={completedCount}
            inProgress={inProgressCount}
            notStarted={Math.max(0, notStartedCount)}
          />
        </aside>
      </div>

      {selectedGap && (
        <SkillDetailPanel
          studentId={studentId}
          gap={selectedGap}
          item={itemBySkill.get(selectedGap.skill_id)}
          path={pathsBySkill[selectedGap.skill_id]}
          roleTitle={analysis?.role_title}
          startSignal={learningStart?.skillId === selectedGap.skill_id ? learningStart.signal : 0}
          focusSignal={lessonFocus?.skillId === selectedGap.skill_id ? lessonFocus : null}
          onPathChange={(path) => setPathsBySkill((prev) => ({ ...prev, [selectedGap.skill_id]: path }))}
          onToggleStep={(n) => {
            const item = itemBySkill.get(selectedGap.skill_id)
            if (item) void toggleStep(item, n)
          }}
          onCompetencyChange={setCopilotCompetency}
        />
      )}

      <ResourceCenter items={items} />
      <CareerRoadmapCard studentId={studentId} roleTitle={analysis?.role_title} />

      {showTop && (
        <button className="btn back-top" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })} aria-label="Back to top">
          Back to top
        </button>
      )}
    </div>
  )
}

function SkillDetailPanel({ studentId, gap, item, path, roleTitle, startSignal, focusSignal, onPathChange, onToggleStep, onCompetencyChange }: {
  studentId: number
  gap: SkillGap
  item?: LearningItem
  path?: PersonalizedPath | null
  roleTitle?: string
  startSignal?: number
  focusSignal?: { skillId?: number; competency: string; signal: number } | null
  onPathChange?: (path: PersonalizedPath | null) => void
  onToggleStep: (step: number) => void
  onCompetencyChange: (competency: string | null) => void
}) {
  const [diagRefreshKey, setDiagRefreshKey] = useState(0)
  return (
    <section className="skill-detail-panel" id="skill-detail">
      <SkillDetailHeader
        gap={gap}
        item={item}
        roleTitle={roleTitle}
        topicProgress={topicProgressFor(path, gap.status === 'strong' ? 100 : 0)}
      />

      <DiagnosticPanel studentId={studentId} skillId={gap.skill_id} skillName={gap.skill_name} startSignal={startSignal} onComplete={() => setDiagRefreshKey(k => k + 1)} />

      <PersonalizedPathPanel
        studentId={studentId}
        skillId={gap.skill_id}
        skillName={gap.skill_name}
        refreshKey={diagRefreshKey}
        startSignal={startSignal}
        focusSignal={focusSignal}
        onPathChange={onPathChange}
        onCompetencyChange={onCompetencyChange}
      />

      {item && (
        <>
          <section className="learning-section compact legacy-learning-pack">
            <SectionTitle eyebrow="Saved Resources" title="Generated resource pack" meta="Compatibility view" />
            <p className="muted small section-copy">
              These saved materials remain available, but your active Learning progress comes from the diagnostic path and Mini Checks above.
            </p>
          </section>
          <div className="skill-detail-grid">
            <article className="learning-copy-card">
              <span>Learn</span>
              <h3>Explanation</h3>
              <div className="md-body"><SafeMarkdown>{item.explanation}</SafeMarkdown></div>
            </article>
            <article className="learning-copy-card">
              <span>Practice</span>
              <h3>Practice exercise</h3>
              <div className="md-body"><SafeMarkdown>{item.practice_exercise}</SafeMarkdown></div>
            </article>
            <article className="learning-copy-card">
              <span>Build</span>
              <h3>Mini-project</h3>
              <div className="md-body"><SafeMarkdown>{item.mini_project}</SafeMarkdown></div>
            </article>
          </div>

          {item.modules && item.modules.length > 0 && (
            <section className="learning-section compact">
              <SectionTitle eyebrow="Coverage" title="This path covers" meta={item.blueprint_version ? `Blueprint: ${item.blueprint_version}` : undefined} />
              <div className="plan-coverage">
                {item.modules.map((module, i) => (
                  <div className={`plan-coverage-item ${module.beyond_blueprint ? 'bonus' : ''}`} key={`${module.competency}-${i}`}>
                    <span className="plan-comp-check">{module.beyond_blueprint ? '+' : <IconCheck size={13} />}</span>
                    <span className="plan-comp-name">{module.competency}</span>
                    {module.beyond_blueprint && <span className="pc-bonus-tag">bonus</span>}
                    <span className="plan-comp-time">{module.estimated_minutes} min</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {item.resources && item.resources.length > 0 && (
            <section className="learning-section compact">
              <SectionTitle eyebrow="Learning Resources" title="Recommended resources" meta={`${item.resources.length} source${item.resources.length === 1 ? '' : 's'}`} />
              <div className="resource-card-row">
                {item.resources.map((resource, i) => (
                  <ResourceCard key={`${resource.url}-${i}`} resource={resource} fallbackRank={i + 1} skillName={item.skill_name} />
                ))}
              </div>
            </section>
          )}

          {item.roadmap?.steps?.length ? (
            <section className="learning-section compact">
              <SectionTitle eyebrow="Saved Roadmap" title={`${item.roadmap.steps.length}-step resource plan`} meta={item.roadmap.summary} />
              <RoadmapTimeline item={item} onToggleStep={onToggleStep} />
            </section>
          ) : (
            <EmptyLearningState
              title="Detailed path data is not available"
              body="The path timeline component is ready; it will render backend roadmap steps as soon as they exist for this skill."
            />
          )}
        </>
      )}
    </section>
  )
}

function DiagnosticPanel({ studentId, skillId, skillName, startSignal = 0, onComplete }: {
  studentId: number
  skillId: number
  skillName: string
  startSignal?: number
  onComplete?: () => void
}) {
  const [phase, setPhase] = useState<'browse' | 'take' | 'result' | 'loading'>('loading')
  const [diag, setDiag] = useState<DiagnosticResult | null>(null)
  const [current, setCurrent] = useState<GeneratedDiagnostic | null>(null)
  const [form, setForm] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const handledStartSignal = useRef(0)

  const loadLatest = async () => {
    setError('')
    try {
      const latest = await api.latestDiagnostic(studentId, skillId)
      setDiag(latest)
      setPhase(latest.completed_at ? 'result' : 'take')
    } catch {
      setDiag(null)
      setPhase('browse')
    }
  }

  useEffect(() => { if (studentId && skillId) void loadLatest() }, [studentId, skillId])

  const start = async () => {
    setBusy(true)
    setError('')
    try {
      const gen = await api.generateDiagnostic(studentId, skillId)
      setCurrent(gen)
      setForm({})
      setPhase('take')
    } catch (e: unknown) {
      setError((e as Error)?.message || 'Could not start the diagnostic')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (!startSignal || phase !== 'browse' || busy || handledStartSignal.current === startSignal) return
    handledStartSignal.current = startSignal
    void start()
  }, [startSignal, phase, busy])

  const submit = async () => {
    // A diagnostic can be in the "take" phase either because it was just
    // generated this session (current is set) or because an earlier,
    // generated-but-unsubmitted diagnostic was reloaded on open (only diag is
    // set). Resolve whichever is active so Submit always has a diagnostic to
    // score instead of silently no-oping.
    const active = current ?? (diag && phase === 'take' ? diag : null)
    if (!active) return
    setBusy(true)
    setError('')
    const questions = active.questions ?? []
    const answers = questions.map((q) => form[q.id] ?? '')
    try {
      const result = await api.submitDiagnostic(studentId, skillId, {
        diagnostic_id: (active as GeneratedDiagnostic).diagnostic_id ?? (active as DiagnosticResult).id,
        answers,
      })
      setDiag(result)
      setCurrent(null)
      setPhase('result')
      onComplete?.()
    } catch (e: unknown) {
      setError((e as Error)?.message || 'Could not submit the diagnostic')
    } finally {
      setBusy(false)
    }
  }

  if (phase === 'loading') return null

  const questions = current?.questions ?? diag?.questions ?? []

  return (
    <section className="diagnostic-panel">
      <div className="diagnostic-head">
        <div>
          <span className="eyebrow">Diagnostic</span>
          <h3>{skillName} — topic check</h3>
        </div>
        {phase === 'browse' && (
          <button className="btn btn-primary" onClick={start} disabled={busy}>Start Diagnostic</button>
        )}
        {phase === 'result' && (
          <button className="btn" onClick={start} disabled={busy}>Retake Diagnostic</button>
        )}
      </div>

      {error && <div className="error learning-error">{error}</div>}

      {phase === 'browse' && (
        <p className="section-copy">
          Start a short diagnostic to see which topics inside {skillName} you have down and which
          need practice. It never verifies the skill — it only shapes your learning.
        </p>
      )}

      {phase === 'take' && (
        <>
          <div className="diagnostic-questions">
            {questions.map((q) => (
              <div className="diag-question" key={q.id}>
                <div className="diag-q-meta">
                  <span className="chip-btn diag-comp-chip">{q.competency}</span>
                  <span className="diag-diff">{q.difficulty}</span>
                </div>
                <div className="diag-q-text">{q.question}</div>
                {q.type === 'mcq' ? (
                  <div className="diag-options">
                    {q.options.map((option) => (
                      <label className={`diag-option ${form[q.id] === option ? 'active' : ''}`} key={option}>
                        <input type="radio" name={q.id} value={option}
                               checked={form[q.id] === option}
                               onChange={() => setForm((f) => ({ ...f, [q.id]: option }))} />
                        <span>{option}</span>
                      </label>
                    ))}
                  </div>
                ) : (
                  <textarea className="diag-text" rows={3}
                            placeholder="Your answer (short is fine)..."
                            value={form[q.id] ?? ''}
                            onChange={(e) => setForm((f) => ({ ...f, [q.id]: e.target.value }))} />
                )}
              </div>
            ))}
          </div>
          <button className="btn btn-primary" onClick={submit} disabled={busy}>
            {busy ? 'Scoring...' : 'Submit Diagnostic'}
          </button>
        </>
      )}

      {phase === 'result' && diag && (
        <div className="diagnostic-result">
          <div className="diag-result-score">
            <strong>{diag.score ?? '–'}%</strong>
            <span>overall</span>
          </div>
          <div className="diag-result-groups">
            <div className="diag-group strong"><h4>Strong Topics</h4>{topicList(diag.topic_results, 'mastered')}</div>
            <div className="diag-group developing"><h4>Needs Practice</h4>{topicList(diag.topic_results, 'developing')}</div>
            <div className="diag-group weak"><h4>Weak Topics</h4>{topicList(diag.topic_results, 'weak')}</div>
          </div>
        </div>
      )}
    </section>
  )
}

function topicList(topics: TopicResult[], status: TopicResult['status']) {
  const rows = topics.filter((t) => t.status === status)
  if (!rows.length) return <p className="muted small">None</p>
  return (
    <div className="diag-topic-list">
      {rows.map((t) => (
        <span className="chip-btn diag-topic-chip" key={t.competency}>{t.label} · {Math.round(t.score)}%</span>
      ))}
    </div>
  )
}

function LessonView({ studentId, skillId, skillName, competency, pathItem, pathId, onClose, onComplete, onStateChange, hasNext, onNext }: {
  studentId: number; skillId: number; skillName: string; competency: string;
  pathItem: PersonalizedPathItem; pathId: number; onClose: () => void; onComplete: () => void;
  onStateChange?: (state: Lesson['state']) => void;
  hasNext?: boolean; onNext?: () => void;
}) {
  const [lesson, setLesson] = useState<Lesson | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<'learn' | 'example' | 'practice' | 'discuss' | 'mini_check'>('learn')
  const [miniAnswers, setMiniAnswers] = useState<Record<string, string>>({})
  const [result, setResult] = useState<{ score: number; passed: boolean; correct: number; total: number } | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [practiceAnswer, setPracticeAnswer] = useState('')
  const [followUpAnswer, setFollowUpAnswer] = useState('')
  const [practiceAttempt, setPracticeAttempt] = useState<PracticeAttempt | null>(null)
  const [practiceAttemptCount, setPracticeAttemptCount] = useState(0)
  const [practiceSubmitting, setPracticeSubmitting] = useState(false)
  const [practiceError, setPracticeError] = useState('')
  const practiceInputRef = useRef<HTMLTextAreaElement | null>(null)

  useEffect(() => {
    let alive = true
    setLoading(true)
    api.lessonGenerate(studentId, skillId, competency)
      .then(async (l) => {
        if (!alive) return
        if (l.state === 'not_started') {
          const startedLesson = await api.lessonStart(studentId, skillId, competency)
          if (!alive) return
          setLesson(startedLesson)
          onStateChange?.(startedLesson.state)
          return
        }
        setLesson(l)
        onStateChange?.(l.state)
      })
      .catch((e) => { if (alive) setError(e?.message || 'Could not load lesson') })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [studentId, skillId, competency])

  useEffect(() => {
    if (tab === 'discuss') window.dispatchEvent(new CustomEvent('copilot:focus'))
  }, [tab])

  useEffect(() => {
    if (!lesson) return
    let alive = true
    api.lessonPracticeAttempts(studentId, skillId, competency)
      .then((res) => {
        if (!alive) return
        setPracticeAttempt(res.latest)
        setPracticeAttemptCount(res.count)
      })
      .catch(() => {
        if (!alive) return
        setPracticeAttempt(null)
        setPracticeAttemptCount(0)
      })
    return () => { alive = false }
  }, [lesson?.id, studentId, skillId, competency])

  const submitPractice = async (sourceAttemptId?: number | null) => {
    const answer = (sourceAttemptId ? followUpAnswer : practiceAnswer).trim()
    if (!lesson || !answer) return
    setPracticeSubmitting(true)
    setPracticeError('')
    try {
      const res = await api.lessonSubmitPractice(studentId, skillId, competency, answer, sourceAttemptId ?? null)
      setPracticeAttempt(res.attempt)
      setPracticeAttemptCount(res.attempts_count)
      if (sourceAttemptId) setFollowUpAnswer('')
      else setPracticeAnswer('')
    } catch (e: unknown) {
      setPracticeError((e as Error)?.message || 'Practice evaluation failed')
    } finally {
      setPracticeSubmitting(false)
    }
  }

  const retryPractice = () => {
    setPracticeAnswer('')
    setFollowUpAnswer('')
    setPracticeError('')
    window.setTimeout(() => practiceInputRef.current?.focus(), 0)
  }

  const submitMiniCheck = async () => {
    if (!lesson) return
    const questions = lesson.content.mini_check.questions
    const orderedAnswers = questions.map((q) => miniAnswers[q.id] || '')
    setSubmitting(true)
    try {
      const res = await api.lessonMiniCheck(studentId, skillId, competency, orderedAnswers)
      setResult(res.lesson.mini_check_result || { score: 0, passed: false, correct: 0, total: questions.length })
      setLesson(res.lesson)
      onStateChange?.(res.lesson.state)
      if (res.lesson.mini_check_result?.passed) onComplete()
    } catch (e: unknown) {
      setError((e as Error)?.message || 'Submission failed')
    } finally {
      setSubmitting(false)
    }
  }

  const isCompleted = lesson?.state === 'completed'
  const diagnosticPct = Math.round(pathItem.diagnostic_score)
  const reasonForLearning = pathItem.action === 'review'
    ? `You understand the basics, but your diagnostic identified gaps to close (${pathItem.topic_status}, ${diagnosticPct}%).`
    : `Your diagnostic showed this topic needs improvement (${pathItem.topic_status}, ${diagnosticPct}%).`

  const tabs = ['learn', 'example', 'practice', 'discuss', 'mini_check'] as const
  const tabLabels: Record<string, string> = { learn: 'Learn', example: 'Example', practice: 'Practice', discuss: 'Discuss with AI', mini_check: 'Mini Check' }

  if (loading) return <div className="lesson-loading">Generating lesson...</div>
  if (error) return <div className="error learning-error">{error}<button className="btn-link" onClick={onClose}>Back to path</button></div>
  if (!lesson) return null

  const content = lesson.content
  const recommendedResources = content.resources || []
  const nextTab = () => { const idx = tabs.indexOf(tab); if (idx < tabs.length - 1) setTab(tabs[idx + 1]) }
  const practiceData = (content.practice ?? {}) as LessonPractice
  const practiceTitle = typeof practiceData.title === 'string' && practiceData.title.trim()
    ? practiceData.title
    : 'Practice task'
  const practiceFirstFreeText = (practiceData.questions ?? []).find((q) => q.type === 'free_text')
  const practiceTaskText =
    typeof practiceData.task === 'string' && practiceData.task.trim()
      ? practiceData.task
      : (practiceFirstFreeText?.question?.trim()
          || (practiceData.questions?.[0]?.question?.trim()
              ? `Apply this concept: ${practiceData.questions[0].question.trim()}. Explain the concrete steps, commands, or code you would use, and justify your choices.`
              : `Explain how you would apply ${practiceData.competency || competency} to a realistic task, including the concrete steps, tools, commands, or code you would use.`))
  const practiceResponseType = typeof practiceData.response_type === 'string'
    ? practiceData.response_type
    : ''
  const latestPracticeLabel = practiceAttemptCount <= 1
    ? 'Latest attempt'
    : `Latest of ${practiceAttemptCount} attempts`
  const previousPracticeCount = Math.max(0, practiceAttemptCount - 1)
  const latestRemediation = practiceAttempt?.remediation ?? null
  const followUpSourceAttemptId = latestRemediation?.practice_attempt_id ?? null
  const answeringFollowUp = !!latestRemediation
  const activePracticeAnswer = answeringFollowUp ? followUpAnswer : practiceAnswer

  return (
    <div className="lesson-view">
      <div className="lesson-header">
        <button className="btn-link lesson-back" onClick={onClose}>&larr; Back to path</button>
        <div className="lesson-title-row">
          <span className="lesson-breadcrumb">{skillName} &gt; {humanizeTopicLabel(competency)}</span>
          <span className={`chip-btn lesson-mode-chip lesson-mode-${lesson.action}`}>{lesson.action}</span>
        </div>
        <div className="lesson-reason">
          <span className="muted small">{reasonForLearning}</span>
        </div>
        {isCompleted && <div className="lesson-completed-banner"><IconCheck size={16} /> Topic completed</div>}
      </div>

      <div className="lesson-nav">
        {tabs.map((t) => (
          <button key={t} className={`lesson-tab ${tab === t ? 'active' : ''}`}
            onClick={() => { if (!isCompleted || t === tab) setTab(t) }}
            disabled={isCompleted && t !== tab}>
            {tabLabels[t]}
          </button>
        ))}
      </div>

      <div className="lesson-content">
        {tab === 'learn' && (
          <div className="lesson-learn">
            <h3>{content.learn.title}</h3>
            <div className="lesson-explanation"><SafeMarkdown>{content.learn.explanation}</SafeMarkdown></div>
            {content.learn.key_ideas && content.learn.key_ideas.length > 0 && (
              <div className="lesson-key-ideas">
                <h4>Key Ideas</h4>
                <ul>{content.learn.key_ideas.map((idea, i) => <li key={i}>{idea}</li>)}</ul>
              </div>
            )}
            {content.learn.key_terms && Object.keys(content.learn.key_terms).length > 0 && (
              <div className="lesson-key-terms">
                <h4>Key Terms</h4>
                {Object.entries(content.learn.key_terms).map(([term, def]) => (
                  <div className="lesson-term" key={term}><strong>{term}</strong>: {def}</div>
                ))}
              </div>
            )}
            {content.learn.job_relevance && (
              <div className="lesson-quality-section">
                <div className="lesson-quality-label">Why this matters for your role</div>
                <p>{content.learn.job_relevance}</p>
              </div>
            )}
            {content.learn.common_mistake && (
              <div className="lesson-quality-section">
                <div className="lesson-quality-label">Common mistake</div>
                <p>{content.learn.common_mistake}</p>
              </div>
            )}
            {content.learn.worked_example && (
              <div className="lesson-quality-section">
                <div className="lesson-quality-label">Worked example</div>
                <p>{content.learn.worked_example}</p>
              </div>
            )}
            {content.learn.depth_note && (
              <div className="lesson-quality-section">
                <p style={{ fontStyle: 'italic' }}>{content.learn.depth_note}</p>
              </div>
            )}
            {content.learn.version_note && (
              <div className="lesson-version-note">{content.learn.version_note}</div>
            )}
            {content.learn.grounding_sources && content.learn.grounding_sources.length > 0 && (
              <div className="lesson-grounding-sources">
                Sources: {content.learn.grounding_sources.map((s, i) => (
                  <span key={i}>{i > 0 && ' · '}<a href={s.url} target="_blank" rel="noopener noreferrer">{s.title || s.source || 'Source'}</a></span>
                ))}
              </div>
            )}
            {recommendedResources.length > 0 && (
              <section className="lesson-resource-panel" aria-label="Recommended Resources">
                <div className="lesson-resource-head">
                  <div>
                    <span>Recommended Resources</span>
                    <strong>{recommendedResources.length} curated source{recommendedResources.length === 1 ? '' : 's'}</strong>
                  </div>
                </div>
                <div className="lesson-resource-list">
                  {recommendedResources.map((resource, i) => {
                    const status = resourceStatus(resource)
                    return (
                      <a className="lesson-resource-card" href={resource.url} target="_blank" rel="noopener noreferrer" key={`${resource.url}-${i}`}>
                        <div className="lesson-resource-card-head">
                          <span className="resource-type">{resourceTypeLabel(resource)}</span>
                          <span className={`lesson-resource-status ${status.key}`}>{status.label}</span>
                        </div>
                        <strong>{resource.title}</strong>
                        <small>{resource.source || 'Curated source'}</small>
                        {resource.reason && <p>{resource.reason}</p>}
                        <span className="lesson-resource-open">Open resource <IconExternal size={13} /></span>
                      </a>
                    )
                  })}
                </div>
              </section>
            )}
            {!isCompleted && <button className="btn btn-primary" onClick={nextTab}>Continue</button>}
          </div>
        )}
        {tab === 'example' && (
          <div className="lesson-example">
            <h3>{content.example.title}</h3>
            <div className="lesson-example-type"><span className="chip-btn">{content.example.type}</span></div>
            <div className="lesson-example-content"><SafeMarkdown>{content.example.content}</SafeMarkdown></div>
            <div className="lesson-explanation"><SafeMarkdown>{content.example.explanation}</SafeMarkdown></div>
            {!isCompleted && <button className="btn btn-primary" onClick={nextTab}>Continue</button>}
          </div>
        )}
        {tab === 'practice' && (
          <div className="lesson-practice">
            <h3>Practice</h3>
            {latestRemediation ? (
              <div className="remediation-panel">
                <div className="remediation-head">
                  <span className="practice-task-label">Personalized Review</span>
                  <div className="practice-source">
                    {latestRemediation.source === 'ai' ? 'AI personalized review' : 'Adaptive review (fallback)'}
                  </div>
                </div>
                <div className="remediation-section">
                  <h5>Focus on</h5>
                  <div className="remediation-focus-list">
                    {latestRemediation.focus_points.map((point, i) => <span className="chip-btn" key={i}>{point}</span>)}
                  </div>
                </div>
                <div className="remediation-section">
                  <h5>Explanation</h5>
                  <div className="remediation-text"><SafeMarkdown>{latestRemediation.explanation}</SafeMarkdown></div>
                </div>
                <div className="remediation-section">
                  <h5>Targeted Example</h5>
                  <div className="lesson-example-content"><SafeMarkdown>{latestRemediation.targeted_example}</SafeMarkdown></div>
                </div>
                <div className="remediation-section remediation-followup">
                  <h5>Try This Next</h5>
                  <p className="lesson-q-text">{latestRemediation.follow_up_task}</p>
                </div>
              </div>
            ) : (
              <div className="practice-primary-task">
                <div className="practice-task-head">
                  <span className="practice-task-label">Practice</span>
                  {practiceResponseType && <span className="chip-btn practice-response-type">{practiceResponseType}</span>}
                </div>
                {practiceTitle && <h4 className="practice-task-title">{practiceTitle}</h4>}
                <p className="lesson-q-text practice-task-text">{practiceTaskText}</p>
              </div>
            )}
            <label className="practice-response-label" htmlFor={`practice-${lesson.id}`}>
              Your {answeringFollowUp ? 'follow-up' : 'practice'} response
            </label>
            <textarea
              id={`practice-${lesson.id}`}
              ref={practiceInputRef}
              className="practice-response"
              value={activePracticeAnswer}
              onChange={(e) => { if (answeringFollowUp) setFollowUpAnswer(e.target.value); else setPracticeAnswer(e.target.value) }}
              placeholder={answeringFollowUp ? 'Write your follow-up response to the targeted task.' : 'Write your explanation, steps, commands, or troubleshooting plan.'}
              disabled={practiceSubmitting || isCompleted}
            />
            <div className="practice-actions">
              <button
                className="btn btn-primary"
                onClick={() => submitPractice(followUpSourceAttemptId)}
                disabled={practiceSubmitting || !activePracticeAnswer.trim() || isCompleted}
                type="button"
              >
                {practiceSubmitting ? 'Evaluating...' : 'Submit Practice'}
              </button>
              {previousPracticeCount > 0 && (
                <span className="muted small">{previousPracticeCount} previous practice {previousPracticeCount === 1 ? 'attempt' : 'attempts'}</span>
              )}
            </div>
            {practiceSubmitting && (
              <div className="practice-status evaluating" role="status">
                <span className="practice-spinner" aria-hidden="true" />
                <span>Evaluating your practice...</span>
              </div>
            )}
            {practiceError && (
              <div className="practice-status error" role="alert">{practiceError}</div>
            )}
            {practiceAttempt && (
              <div className={`practice-review ${practiceAttempt.status}`}>
                <div className="practice-review-head">
                  <div>
                    <span className="practice-task-label">{latestPracticeLabel}</span>
                    <h4>Practice Review</h4>
                  </div>
                  <div className="practice-score">
                    <strong>{Math.round(practiceAttempt.score)}%</strong>
                    <span>{practiceAttempt.status === 'ready' ? 'Ready' : 'Needs review'}</span>
                  </div>
                </div>
                <div className="practice-source">
                  {practiceAttempt.source === 'ai' ? 'AI practice evaluation' : 'Basic automated review'}
                </div>
                <p className="practice-feedback">{practiceAttempt.feedback}</p>
                {practiceAttempt.status === 'ready' && (
                  <div className="practice-ready-banner"><IconCheck size={16} /> Ready for Mini Check</div>
                )}
                <div className="practice-review-grid">
                  <div>
                    <h5>Strengths</h5>
                    <ul>
                      {practiceAttempt.strengths.map((item, i) => <li key={i}>{item}</li>)}
                    </ul>
                  </div>
                  <div>
                    <h5>Needs improvement</h5>
                    <ul>
                      {practiceAttempt.missing_points.map((item, i) => <li key={i}>{item}</li>)}
                    </ul>
                  </div>
                </div>
                <div className="practice-next-action">
                  <strong>Next action</strong>
                  <span>{practiceAttempt.next_action}</span>
                </div>
                {!isCompleted && (
                  <button className="btn btn-primary" onClick={retryPractice} type="button">
                    Try Again
                  </button>
                )}
              </div>
            )}
            {!isCompleted && practiceAttempt?.status === 'ready' ? (
              <button className="btn btn-primary" onClick={nextTab}>Continue to Mini Check</button>
            ) : !isCompleted ? (
              <button className="btn" onClick={nextTab}>Continue</button>
            ) : null}
          </div>
        )}
        {tab === 'discuss' && (
          <div className="lesson-discuss">
            <div className="lesson-discuss-head">
              <h3>Discuss with AI</h3>
              <p className="muted small">Ask the tutor anything about {humanizeTopicLabel(competency)} — your background, skill, and this exact step are already in the tutor's context.</p>
            </div>
            <div className="lesson-discuss-goto">
              <p className="muted small">
                The AI Tutor lives in the panel at the bottom-right of every page. Open it — it already knows
                you're learning <strong>{humanizeTopicLabel(competency)}</strong> on <strong>{skillName}</strong>.
              </p>
              <button
                className="btn btn-primary"
                onClick={() => window.dispatchEvent(new CustomEvent('copilot:focus'))}
                type="button"
              >
                <IconChat size={15} /> Open AI Tutor
              </button>
            </div>
            {!isCompleted && <button className="btn btn-primary" onClick={nextTab} style={{ marginTop: 12 }}>Continue to Mini Check</button>}
          </div>
        )}
        {tab === 'mini_check' && (
          <div className="lesson-mini-check">
            <h3>Mini Check</h3>
            {result ? (
              <div className={`lesson-result ${result.passed ? 'passed' : 'failed'}`}>
                <div className="lesson-result-score">{Math.round(result.score * 100)}%</div>
                <div className="lesson-result-detail">{result.correct}/{result.total} correct</div>
                {result.passed ? (
                  <div className="lesson-result-msg passed-msg"><IconCheck size={16} /> Passed — topic completed!</div>
                ) : (
                  <div className="lesson-result-msg failed-msg">Needs another attempt — review the lesson and try again.</div>
                )}
                <div className="lesson-result-actions">
                  {!result.passed && <button className="btn" onClick={() => { setResult(null); setMiniAnswers({}); setTab('learn') }}>Review Lesson</button>}
                  {result.passed && hasNext && onNext && <button className="btn btn-primary" onClick={onNext}>Next Lesson <IconArrowRight size={15} /></button>}
                  {result.passed && <button className="btn" onClick={onClose}>Back to Path</button>}
                </div>
              </div>
            ) : (
              <>
                {content.mini_check.questions.map((q) => (
                  <div className="lesson-question" key={q.id}>
                    <p className="lesson-q-text">{q.question}</p>
                    {q.type === 'mcq' && q.options && (
                      <div className="lesson-options">
                        {q.options.map((opt, i) => (
                          <button key={i} className={`lesson-option ${miniAnswers[q.id] === opt ? 'selected' : ''}`}
                            onClick={() => setMiniAnswers({ ...miniAnswers, [q.id]: opt })}>
                            {opt}
                          </button>
                        ))}
                      </div>
                    )}
                    {q.type === 'free_text' && (
                      <textarea className="lesson-free-text" value={miniAnswers[q.id] || ''}
                        onChange={(e) => setMiniAnswers({ ...miniAnswers, [q.id]: e.target.value })}
                        placeholder="Type your answer..." />
                    )}
                  </div>
                ))}
                <button className="btn btn-primary" onClick={submitMiniCheck} disabled={submitting}>
                  {submitting ? 'Scoring...' : 'Submit Mini Check'}
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function PersonalizedPathPanel({ studentId, skillId, skillName, refreshKey = 0, startSignal = 0, focusSignal, onPathChange, onCompetencyChange }: {
  studentId: number
  skillId: number
  skillName: string
  refreshKey?: number
  startSignal?: number
  focusSignal?: { competency: string; signal: number } | null
  onPathChange?: (path: PersonalizedPath | null) => void
  onCompetencyChange?: (competency: string | null) => void
}) {
  const [path, setPath] = useState<PersonalizedPath | null>(null)
  const [ready, setReady] = useState(false)
  const [diagnosticDone, setDiagnosticDone] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [showMastered, setShowMastered] = useState(false)
  const [done, setDone] = useState<string[]>([])
  const [lessonStates, setLessonStates] = useState<Record<string, Lesson['state']>>({})
  const [openCompetency, setOpenCompetency] = useState<string | null>(null)
  const [finalStatus, setFinalStatus] = useState<FinalAssessmentStatus | null>(null)
  const handledStartSignal = useRef(0)
  const handledFocusSignal = useRef(0)

  const compRef = useRef(onCompetencyChange)
  compRef.current = onCompetencyChange
  useEffect(() => () => { compRef.current?.(null) }, [])

  const loadFinalStatus = async () => {
    if (!studentId || !skillId) return
    try {
      const s = await api.finalAssessmentStatus(studentId, skillId)
      setFinalStatus(s)
    } catch {
      setFinalStatus(null)
    }
  }

  const syncLessonStates = async (nextPath: PersonalizedPath | null) => {
    if (!nextPath) {
      setLessonStates({})
      return {}
    }
    const entries = await Promise.all(nextPath.items.map(async (item) => {
      try {
        const lesson = await api.lessonGet(studentId, skillId, item.competency)
        return [item.competency, lesson.state] as const
      } catch {
        return [item.competency, 'not_started' as Lesson['state']] as const
      }
    }))
    const states = Object.fromEntries(entries) as Record<string, Lesson['state']>
    setLessonStates(states)
    return states
  }

  const openCurrentTopic = (nextPath: PersonalizedPath, states: Record<string, Lesson['state']> = lessonStates) => {
    const completed = new Set(nextPath.progress ?? [])
    const current =
      nextPath.items.find((item) => states[item.competency] === 'in_progress' && !completed.has(item.id)) ||
      nextPath.items.find((item) => !completed.has(item.id)) ||
      nextPath.items[0]
    if (!current) return
    setOpenCompetency(current.competency)
    compRef.current?.(current.competency)
  }

  const loadPath = async () => {
    setError('')
    try {
      const res = await api.personalizedPath(studentId, skillId)
      if ('diagnostic_required' in res) {
        setPath(null)
        setDone([])
        setLessonStates({})
        onPathChange?.(null)
        const latest = await api.latestDiagnostic(studentId, skillId).catch(() => null)
        setDiagnosticDone(!!latest?.completed_at)
      } else {
        setPath(res)
        setDone([...res.progress])
        await syncLessonStates(res)
        setDiagnosticDone(true)
        onPathChange?.(res)
      }
    } catch {
      setPath(null)
      setDone([])
      setLessonStates({})
      setDiagnosticDone(false)
      onPathChange?.(null)
    } finally {
      setReady(true)
    }
  }

  useEffect(() => {
    if (studentId && skillId) {
      setReady(false)
      setOpenCompetency(null)
      compRef.current?.(null)
      void loadPath()
      void loadFinalStatus()
    }
  }, [studentId, skillId, refreshKey])

  const create = async (autoOpen = false) => {
    setBusy(true)
    setError('')
    try {
      const res = await api.generatePersonalizedPath(studentId, skillId)
      if ('diagnostic_required' in res) {
        setPath(null)
        setDone([])
        setLessonStates({})
        onPathChange?.(null)
      } else {
        setPath(res)
        setDone([...res.progress])
        const states = await syncLessonStates(res)
        setDiagnosticDone(true)
        onPathChange?.(res)
        if (autoOpen) openCurrentTopic(res, states)
      }
    } catch (e: unknown) {
      setError((e as Error)?.message || 'Could not create your learning path')
    } finally {
      setBusy(false)
    }
  }

  const openLesson = async (competency: string) => {
    setOpenCompetency(competency)
    compRef.current?.(competency)
  }

  const lessonItem = openCompetency && path ? path.items.find((it) => it.competency === openCompetency) : null
  const lessonIndex = lessonItem && path ? path.items.findIndex((it) => it.competency === openCompetency) : -1
  const nextLesson = lessonIndex >= 0 && path ? path.items[lessonIndex + 1] : undefined

  useEffect(() => {
    if (!ready || !startSignal || handledStartSignal.current === startSignal) return
    if (path) {
      handledStartSignal.current = startSignal
      openCurrentTopic(path)
      return
    }
    if (diagnosticDone) {
      handledStartSignal.current = startSignal
      void create(true)
    }
  }, [startSignal, ready, path, diagnosticDone])

  useEffect(() => {
    if (!ready || !path || !focusSignal || handledFocusSignal.current === focusSignal.signal) return
    const found = path.items.find((it) => it.competency === focusSignal.competency)
    if (!found) return
    handledFocusSignal.current = focusSignal.signal
    setOpenCompetency(focusSignal.competency)
    compRef.current?.(focusSignal.competency)
  }, [focusSignal, ready, path])

  if (!ready) return null

  if (openCompetency && lessonItem && path) {
    return (
      <LessonView
        key={openCompetency}
        studentId={studentId} skillId={skillId} skillName={skillName}
        competency={openCompetency} pathItem={lessonItem} pathId={path.id}
        onClose={() => { setOpenCompetency(null); compRef.current?.(null) }}
        onComplete={async () => { await loadPath(); void loadFinalStatus() }}
        onStateChange={(state) => setLessonStates((prev) => ({ ...prev, [openCompetency]: state }))}
        hasNext={!!nextLesson}
        onNext={nextLesson ? () => {
          setOpenCompetency(nextLesson.competency)
          compRef.current?.(nextLesson.competency)
          requestAnimationFrame(() => document.getElementById('skill-detail')?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
        } : undefined}
      />
    )
  }

  const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : '')
  const completedIds = new Set(done)
  const progress = topicProgressFor(path)
  const stateFor = (item: PersonalizedPathItem) => {
    if (completedIds.has(item.id) || lessonStates[item.competency] === 'completed') return 'Completed'
    if (lessonStates[item.competency] === 'in_progress') return 'In progress'
    return 'Not started'
  }
  const stateClass = (state: string) => state.toLowerCase().replace(/\s+/g, '-')

  return (
    <section className="personalized-path-panel">
      <div className="diagnostic-head">
        <div>
          <span className="eyebrow">My Learning Path</span>
          <h3>{skillName} — personalized plan</h3>
          {path && <p className="muted small">Based on your latest diagnostic · target level {path.required_level}</p>}
        </div>
        {path && (
          <span className="chip-btn pp-required-level">{path.required_level}</span>
        )}
      </div>

      {error && <div className="error learning-error">{error}</div>}

      {!path && diagnosticDone && (
        <div className="pp-create-call">
          <p className="section-copy">
            Your diagnostic is complete. Build a topic-by-topic learning path ordered from your
            weakest topics, so you know exactly what to tackle next.
          </p>
          <button className="btn btn-primary" onClick={() => void create(false)} disabled={busy}>
            <IconBolt size={16} /> {busy ? 'Building...' : 'Create My Learning Path'}
          </button>
        </div>
      )}

      {!path && !diagnosticDone && ready && (
        <p className="muted small section-copy">
          Complete a diagnostic first — it shapes which topics belong on your personalized path.
        </p>
      )}

      {path && (
        <>
          <div className="pp-progress-summary">
            <div>
              <strong>{progress.done} / {progress.total} topics complete</strong>
              <span>{progress.pct}%</span>
            </div>
            <div className="lp-track"><span style={{ width: `${progress.pct}%` }} /></div>
            <p className="muted small">
              Topics complete only after a Mini Check pass. This does not create a Verified Skill.
            </p>
          </div>

          <div className="pp-timeline">
            {path.items.map((item) => {
              const isDone = done.includes(item.id)
              const topicState = stateFor(item)
              return (
                <div className={`pp-item ${isDone ? 'is-done' : ''}`} key={item.id}>
                  <div className={`pp-state-dot pp-state-${stateClass(topicState)}`}>
                    {isDone ? <IconCheck size={15} /> : <span />}
                  </div>
                  <div className="pp-item-body" onClick={() => openLesson(item.competency)} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') openLesson(item.competency) }}>
                    <div className="pp-item-top">
                      <span className="pp-order">{String(item.order).padStart(2, '0')}</span>
                      <span className={`chip-btn pp-status-chip pp-status-${item.topic_status}`}>{cap(item.topic_status)}</span>
                      <span className={`chip-btn pp-action-chip pp-action-${item.action}`}>{item.action}</span>
                      <span className={`chip-btn pp-topic-state pp-topic-state-${stateClass(topicState)}`}>{topicState}</span>
                    </div>
                    <h4>{humanizeTopicLabel(item.title)}</h4>
                    <p className="muted small">
                      Added because your diagnostic score was <strong>{Math.round(item.diagnostic_score)}%</strong>.
                      {' '}<span className="pp-est"><IconClock size={13} /> ~{item.estimated_minutes} min</span>
                    </p>
                  </div>
                </div>
              )
            })}

            {path.stages.map((stage) => {
              const isDone = done.includes(stage.id)
              const isFinalAssess = stage.id === 'final-assessment'
              if (isFinalAssess) {
                return (
                  <div className={`pp-stage pp-stage-final ${isDone ? 'is-done' : ''}`} key={stage.id}>
                    <div className="pp-stage-lock">
                      {isDone ? <IconCheck size={15} /> : <span className="fa-dot" />}
                    </div>
                    <div className="pp-item-body">
                      <div className="pp-item-top">
                        <span className="chip-btn pp-status-chip pp-status-milestone">milestone</span>
                        <span className={`chip-btn pp-action-chip pp-action-${isDone ? 'done' : 'available'}`}>
                          {isDone ? 'completed' : 'Available anytime'}
                        </span>
                      </div>
                      <h4>{humanizeTopicLabel(stage.stage)}</h4>
                      <p className="muted small">
                        Independent from learning progress — start it from the Assessments page whenever you are ready.
                      </p>
                    </div>
                  </div>
                )
              }
              const unlocked = isDone
              const lockState = isDone ? 'done' : 'locked'
              return (
                <div className={`pp-stage ${isDone ? 'is-done' : ''}`} key={stage.id}>
                  <div className="pp-stage-lock">
                    {unlocked ? <IconCheck size={15} /> : <IconLock size={14} />}
                  </div>
                  <div className="pp-item-body">
                    <div className="pp-item-top">
                      <span className="chip-btn pp-status-chip pp-status-milestone">milestone</span>
                      <span className={`chip-btn pp-action-chip pp-action-${lockState}`}>{lockState}</span>
                    </div>
                    <h4>{humanizeTopicLabel(stage.stage)}</h4>
                    <p className="muted small">
                      Completes the {cap(stage.action)} stage of this path.
                    </p>
                  </div>
                </div>
              )
            })}
          </div>

          {path.skipped_mastered.length > 0 && (
            <div className="pp-mastered">
              <button className="pp-mastered-toggle" onClick={() => setShowMastered((s) => !s)}>
                <span className={`pp-mastered-chev ${showMastered ? 'open' : ''}`}><IconChevron size={14} /></span>
                Skipped / Already mastered — {path.skipped_mastered.length} topics excluded
              </button>
              {showMastered && (
                <div className="pp-mastered-chips">
                  {path.skipped_mastered.map((comp) => (
                    <span className="chip-btn pp-status-chip pp-status-mastered" key={comp}>{humanizeTopicLabel(comp)}</span>
                  ))}
                </div>
              )}
            </div>
          )}

          {finalStatus && finalStatus.has_blueprint && (
            <section className="pp-coverage">
              <div className="fa-head">
                <span className="eyebrow">Final Assessment</span>
                <span className="chip-btn fa-status fa-ready">Full coverage required to pass</span>
              </div>
              <p className="muted small">
                Target level {finalStatus.required_level}. The proctored Final Assessment is always
                available from the Assessments page; every required competency below must score 70%
                or higher for the attempt to pass.
              </p>
              <div className="plan-coverage">
                {finalStatus.readiness.required.map((slug) => {
                  const covered = finalStatus.readiness.satisfied.includes(slug)
                  return (
                    <div className={`plan-coverage-item ${covered ? '' : 'missing'}`} key={slug}>
                      <span className="plan-comp-check">{covered ? <IconCheck size={13} /> : <span className="fa-dot" />}</span>
                      <span className="plan-comp-name">{humanizeTopicLabel(slug)}</span>
                      {covered && <span className="fa-covered-tag">covered</span>}
                      {!covered && <span className="fa-missing-tag">missing</span>}
                    </div>
                  )
                })}
              </div>
            </section>
          )}
        </>
      )}
    </section>
  )
}

function CareerRoadmapCard({ studentId, roleTitle }: { studentId: number; roleTitle?: string }) {
  const { applyCopilot } = useApp()
  const [map, setMap] = useState<CareerRoadmap | null>(null)
  const [openPhase, setOpenPhase] = useState<number | null>(1)

  const openRoadmapPhase = (next: number | null) => {
    setOpenPhase(next)
    if (next !== null) applyCopilot({ page: 'career_roadmap', skillId: null, competency: null, jobTitle: null, jobUrl: null })
  }

  useEffect(() => {
    let alive = true
    if (!studentId) return
    api.careerRoadmap(studentId)
      .then((r) => { if (alive) setMap(r) })
      .catch((e) => { if (alive) { setMap(null); console.error('[learning] career roadmap failed:', e) } })
    return () => { alive = false }
  }, [studentId])

  if (!map || !Array.isArray(map.phases) || !map.phases.length) return null

  return (
    <section className="learning-section career-roadmap-section">
      <SectionTitle
        eyebrow="Career Roadmap"
        title="High-level career journey"
        meta={`${map.phase_count ?? map.phases.length} phases - ${map.role_title || roleTitle || 'your target role'}`}
      />
      <p className="section-copy">{map.summary}</p>
      <div className="cr-phases">
        {map.phases.map((phase) => {
          const open = openPhase === phase?.phase
          const skillNames = [...new Set((phase?.skills || []).map((skill) => skill?.name).filter(Boolean))]
          return (
            <div className={`cr-phase ${open ? 'open' : ''}`} key={phase?.phase ?? 0}>
              <button className="cr-phase-head" onClick={() => openRoadmapPhase(open ? null : phase.phase)}>
                <span className="cr-phase-num">{phase?.phase ?? ''}</span>
                <span className="cr-phase-title">{phase?.title ?? ''}</span>
                <IconChevron size={15} className={open ? 'chev open' : 'chev'} />
              </button>
              {open && phase && (
                <div className="cr-phase-body">
                  <p className="cr-goal">{phase.goal}</p>
                  {skillNames.length > 0 && (
                    <div className="cr-skills">
                      <span className="small muted">Develops:</span>
                      {skillNames.map((name) => (
                        <span className="chip-btn cr-chip" key={name}>{name}</span>
                      ))}
                    </div>
                  )}
                  <div className="cr-deliverables">
                    <div className="cr-deliverable-title">Deliverables</div>
                    {(Array.isArray(phase.deliverables)
                      ? phase.deliverables
                      : typeof phase.deliverables === 'string'
                        ? [phase.deliverables]
                        : []
                    ).map((deliverable, i) => (
                      <div className="cr-deliverable" key={i}>
                        <span className="rm-checkbox" style={{ background: 'var(--navy)', borderColor: 'var(--navy)' }}>{i + 1}</span>
                        <div className="md-body"><SafeMarkdown>{deliverable}</SafeMarkdown></div>
                      </div>
                    ))}
                  </div>
                  <div className="cr-check"><strong>Checkpoint:</strong> {phase.checkpoint}</div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}

function ResourceCenter({ items }: { items: LearningItem[] }) {
  const [mode, setMode] = useState<'combined' | 'per-skill'>('combined')
  const all = items.flatMap((item) =>
    (item.resources || []).map((resource) => ({
      ...resource,
      skillId: item.skill_id,
      skillName: item.skill_name,
    })),
  )
  if (!all.length) return null

  const byUrl = new Map<string, (typeof all)[number] & { skills: Set<string>; times: number }>()
  all.forEach((resource) => {
    const hit = byUrl.get(resource.url)
    if (hit) {
      hit.skills.add(resource.skillName)
      hit.times += 1
      if (resource.helpfulness && !hit.helpfulness) hit.helpfulness = resource.helpfulness
    } else {
      byUrl.set(resource.url, { ...resource, skills: new Set([resource.skillName]), times: 1 })
    }
  })
  const unique = [...byUrl.values()].sort((a, b) => b.times - a.times || (a.title || '').localeCompare(b.title || ''))
  const skillCount = new Set(all.map((resource) => resource.skillName)).size

  const perSkill = new Map<string, typeof unique>()
  unique.forEach((resource) => {
    const key = [...resource.skills][0]
    perSkill.set(key, [...(perSkill.get(key) || []), resource])
  })

  return (
    <section className="learning-section resource-center-section">
      <div className="resource-center-head">
        <SectionTitle eyebrow="Learning Resources" title="Resource library" meta={`${unique.length} unique links across ${skillCount} skills`} />
        <div className="rc-toggle">
          <button className={`rc-tab ${mode === 'combined' ? 'active' : ''}`} onClick={() => setMode('combined')}>Combined</button>
          <button className={`rc-tab ${mode === 'per-skill' ? 'active' : ''}`} onClick={() => setMode('per-skill')}>By skill</button>
        </div>
      </div>
      {mode === 'combined' ? (
        <div className="resource-card-row">
          {unique.map((resource, i) => (
            <ResourceCard key={resource.url} resource={resource} fallbackRank={i + 1} />
          ))}
        </div>
      ) : (
        [...perSkill.entries()].map(([name, rows]) => (
          <div className="rc-skill" key={name}>
            <div className="rc-skill-name">{name}</div>
            <div className="resource-card-row">
              {rows.map((resource, i) => (
                <ResourceCard key={resource.url} resource={resource} fallbackRank={i + 1} skillName={name} />
              ))}
            </div>
          </div>
        ))
      )}
    </section>
  )
}
