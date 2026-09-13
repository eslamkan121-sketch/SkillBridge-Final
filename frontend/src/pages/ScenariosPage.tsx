import React, { useEffect, useMemo, useState } from 'react'
import { useApp } from '../AppContext'
import { api } from '../lib/api'
import { SectionTitle } from '../components/learning'
import {
  IconArrowRight, IconBack, IconBolt, IconCheck, IconChat, IconClock, IconEye, IconLightbulb,
  IconShield, IconTrophy, IconUsers,
} from '../components/Icons'
import type {
  ScenarioCard, ScenarioDecisionRow, ScenarioEvidence, ScenarioHistory,
  ScenarioHistoryEntry, ScenarioLastDecision, ScenarioLibrary, ScenarioPlayer, ScenarioResult,
  ScenarioStepView,
} from '../lib/types'

type View = 'library' | 'player' | 'results' | 'history'
type DifficultyFilter = 'all' | 'beginner' | 'intermediate' | 'advanced'
type NavFocus = { skillId: number; roleTitle: string }

interface PlayerState {
  player: ScenarioPlayer
  viewed: Set<string>
  busy: boolean
}

const DIFFICULTY_OPTIONS: { key: DifficultyFilter; label: string; icon: string }[] = [
  { key: 'all', label: 'All levels', icon: '' },
  { key: 'beginner', label: 'Beginner', icon: '🟢' },
  { key: 'intermediate', label: 'Intermediate', icon: '🟡' },
  { key: 'advanced', label: 'Advanced', icon: '🔴' },
]

export default function ScenariosPage({ onNavigate, initialFocus, onFocusConsumed, backTo }: {
  onNavigate?: (section: string, focus?: NavFocus) => void
  initialFocus?: NavFocus | null
  onFocusConsumed?: () => void
  backTo?: { key: string; label: string } | null
}) {
  const { session, applyCopilot } = useApp()
  const studentId = session?.student?.id ?? 0

  useEffect(() => {
    applyCopilot({ page: 'scenarios', skillId: null, competency: null, jobTitle: null, jobUrl: null })
  }, [applyCopilot])

  // Phase 5: consume any deep-linked focus (role that motivated this visit) so
  // the next navigation starts from a clean slate — no state loops.
  const [focusRole, setFocusRole] = useState('')
  useEffect(() => {
    if (initialFocus) {
      setFocusRole(initialFocus.roleTitle || '')
      onFocusConsumed?.()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const [view, setView] = useState<View>('library')
  const [category, setCategory] = useState('all')
  const [difficulty, setDifficulty] = useState<DifficultyFilter>('all')
  const [loadError, setLoadError] = useState('')
  const [library, setLibrary] = useState<ScenarioLibrary | null>(null)
  const [player, setPlayer] = useState<PlayerState | null>(null)
  const [result, setResult] = useState<ScenarioResult | null>(null)
  const [detail, setDetail] = useState<ScenarioCard | null>(null)
  const [history, setHistory] = useState<ScenarioHistory | null>(null)

  const loadLibrary = (silent = false) => {
    if (!studentId) return
    if (!silent) setLoadError('')
    api.scenarios(studentId)
      .then((data) => setLibrary(data))
      .catch((e) => { if (!silent) setLoadError((e as Error)?.message || 'Failed to load practice scenarios') })
  }

  useEffect(() => { loadLibrary() }, [studentId])

  const start = async (scenarioId: string) => {
    if (!studentId) return
    setView('player')
    setResult(null)
    setPlayer({ player: null as any, viewed: new Set(), busy: true })
    try {
      const p = await api.startScenario(studentId, scenarioId)
      setPlayer({ player: p, viewed: new Set(), busy: false })
    } catch (e) {
      setPlayer(null)
      setLoadError((e as Error)?.message || 'Failed to start the scenario')
      setView('library')
    }
  }

  const showHistory = () => {
    setView('history')
    setLoadError('')
    setHistory(null)
    if (!studentId) return
    api.scenarioHistory(studentId)
      .then(setHistory)
      .catch((e) => setLoadError((e as Error)?.message || 'Failed to load scenario history'))
  }

  const backToLibrary = () => {
    loadLibrary(true)
    setView('library')
    setPlayer(null)
    setResult(null)
    setDetail(null)
    setCategory('all')
    setDifficulty('all')
  }

  const openAttempt = async (attemptId: number) => {
    if (!studentId) return
    try {
      const res = await api.scenarioAttempt(studentId, attemptId)
      const completed = 'completed' in res
      if (completed) {
        setResult(res as ScenarioResult)
        setView('results')
      } else {
        setView('player')
        setPlayer({ player: res as ScenarioPlayer, viewed: new Set(), busy: false })
      }
    } catch (e) {
      setLoadError((e as Error)?.message || 'Could not open that attempt')
    }
  }

  if (!studentId) return <div className="empty">Log in as a student to practice real-world scenarios.</div>

  return (
    <div className="scn-page">
      <nav className="crumbs" aria-label="Breadcrumbs">
        {backTo && (
          <button type="button" className="crumb-back" onClick={() => onNavigate?.(backTo.key)}>
            <IconBack size={14} /> Back to {backTo.label}
          </button>
        )}
        {focusRole && <span className="crumb-context">Practice for <b>{focusRole}</b></span>}
      </nav>
      {view === 'library' && (
        <LibraryView
          loadError={loadError}
          library={library}
          category={category}
          setCategory={setCategory}
          difficulty={difficulty}
          setDifficulty={setDifficulty}
          onStart={start}
          onDetails={setDetail}
          onHistory={showHistory}
          onNavigate={onNavigate}
          onRetry={() => loadLibrary()}
        />
      )}
      {view === 'player' && player && (
        <PlayerView
          studentId={studentId}
          state={player}
          setState={setPlayer}
          onResult={(r) => { setResult(r); setView('results') }}
          onBack={() => { backToLibrary(); loadLibrary(true) }}
        />
      )}
      {view === 'results' && result && (
        <ResultsView result={result} onReplay={() => start(result.scenario_id)} onBack={backToLibrary} onNavigate={onNavigate} />
      )}
      {view === 'history' && (
        <HistoryView
          loadError={loadError}
          history={history}
          onRetry={showHistory}
          onOpenAttempt={openAttempt}
          onBack={() => { setView('library'); loadLibrary(true) }}
        />
      )}
      {detail && (
        <ScenarioDetail
          scn={detail}
          hasTarget={!!library?.target_role}
          onClose={() => setDetail(null)}
          onStart={() => { const id = detail.id; setDetail(null); start(id) }}
        />
      )}
    </div>
  )
}

// ------------------------------------------------------------------ Library

function LibraryView({
  loadError, library, category, setCategory, difficulty, setDifficulty,
  onStart, onDetails, onHistory, onNavigate, onRetry,
}: {
  loadError: string
  library: ScenarioLibrary | null
  category: string
  setCategory: (c: string) => void
  difficulty: DifficultyFilter
  setDifficulty: (d: DifficultyFilter) => void
  onStart: (id: string) => void
  onDetails: (scn: ScenarioCard) => void
  onHistory: () => void
  onNavigate?: (section: string, focus?: NavFocus) => void
  onRetry: () => void
}) {
  const byRecommended = useMemo(() => {
    if (!library) return [] as ScenarioCard[]
    const order: Map<string, number> = new Map(library.recommended.map((id, i): [string, number] => [id, i]))
    return [...(library.scenarios as ScenarioCard[])].sort((a, b) => {
      const ai = order.get(a.id) ?? 99
      const bi = order.get(b.id) ?? 99
      return ai - bi || a.title.localeCompare(b.title)
    })
  }, [library])

  const filtered = useMemo(() => {
    return byRecommended.filter((s) =>
      (category === 'all' || s.category === category) &&
      (difficulty === 'all' || s.difficulty === difficulty)
    )
  }, [byRecommended, category, difficulty])

  const groups = useMemo(() => {
    const g = { not_started: [] as ScenarioCard[], in_progress: [] as ScenarioCard[], completed: [] as ScenarioCard[] }
    for (const s of filtered) g[s.status].push(s)
    return g
  }, [filtered])

  const recommendedNext = useMemo(() => {
    return byRecommended.find((s) => s.status !== 'completed') ?? null
  }, [byRecommended])

  if (loadError) {
    return (
      <div className="error scn-error">
        <span>{loadError}</span>
        <button className="btn btn-sm" onClick={onRetry}>Retry</button>
      </div>
    )
  }
  if (!library) return <ScenariosSkeleton />

  const stats = library.stats
  const hasTarget = !!library.target_role

  return (
    <>
      <div className="scn-hero panel">
        <div>
          <p className="eyebrow">Practice Scenarios</p>
          <h2 className="scn-hero-title">
            {hasTarget ? `Practice for ${library.target_role}` : 'Practice for real situations'}
          </h2>
          <p className="scn-hero-sub">
            {hasTarget
              ? `Step through realistic, branching situations for the ${library.target_role} role. Make the calls an actual professional would make — every decision changes what happens next.`
              : 'Step through realistic, branching situations for the role you are building toward. Make the calls an actual professional would make — every decision changes what happens next.'}
          </p>
        </div>
        <div className="scn-hero-actions">
          <button className="btn btn-ghost btn-block" onClick={onHistory} aria-label="View scenario history">
            <IconClock size={15} /> History
          </button>
          {hasTarget && (
            <button className="btn btn-primary btn-block scn-hero-cta" onClick={() => onNavigate?.('learning')}>
              <IconShield size={15} /> Back to your learning path <IconArrowRight size={14} />
            </button>
          )}
        </div>
      </div>

      <div className="scn-stats">
        <div className="scn-stat panel">
          <span className="scn-stat-icon"><IconClock size={15} /></span>
          <div><strong>{stats.practice_time_minutes} min</strong><span>Practice time</span></div>
        </div>
        <div className="scn-stat panel">
          <span className="scn-stat-icon"><IconUsers size={15} /></span>
          <div><strong>{stats.scenarios_completed}/{library.scenarios.length}</strong><span>Scenarios completed</span></div>
        </div>
        <div className="scn-stat panel">
          <span className="scn-stat-icon"><IconTrophy size={15} /></span>
          <div><strong>{stats.average_score != null ? `${stats.average_score}%` : '—'}</strong><span>Average score</span></div>
        </div>
        <div className="scn-stat panel">
          <span className="scn-stat-icon"><IconBolt size={15} /></span>
          <div><strong>{stats.skills_practiced}</strong><span>Skills practiced</span></div>
        </div>
      </div>

      {hasTarget && recommendedNext && (
        <section className="panel scn-next" aria-label="Recommended next scenario">
          <div className="scn-next-label"><IconBolt size={14} /> Recommended next</div>
          <div className="scn-next-body">
            <div className="scn-next-info">
              <div className="scn-next-chips">
                {recommendedNext.family_label && (
                  <span className="scn-fam">{recommendedNext.family_icon} {recommendedNext.family_label}</span>
                )}
                <span className="scn-pill">{recommendedNext.difficulty_icon} {recommendedNext.difficulty_label}</span>
                <span className="scn-pill"><IconClock size={12} /> {recommendedNext.estimated_time_label}</span>
                <span className="scn-pill">{recommendedNext.steps_count} steps</span>
              </div>
              <h3 className="scn-next-title">{recommendedNext.title}</h3>
              <p className="scn-card-desc">{recommendedNext.description}</p>
              <div className="scn-skills">
                {recommendedNext.skills.slice(0, 3).map((s) => <span key={s} className="skill-tag">{s}</span>)}
              </div>
            </div>
            <button className="btn btn-primary btn-sm" onClick={() => onStart(recommendedNext.id)}>
              {recommendedNext.status === 'in_progress' ? 'Resume this scenario' : 'Start this scenario'} <IconArrowRight size={14} />
            </button>
          </div>
        </section>
      )}

      <div className="scn-filterbar">
        <div className="scn-filters" role="group" aria-label="Filter scenarios by category">
          <button className={`chip-btn ${category === 'all' ? 'active' : ''}`} onClick={() => setCategory('all')}>All</button>
          {(library.categories || []).map((c: { key: string; label: string; icon: string }) => (
            <button key={c.key} className={`chip-btn ${category === c.key ? 'active' : ''}`} onClick={() => setCategory(c.key)}>
              {c.icon} {c.label}
            </button>
          ))}
        </div>
        <div className="scn-filters scn-filters-diff" role="group" aria-label="Filter scenarios by difficulty">
          {DIFFICULTY_OPTIONS.map((d) => (
            <button key={d.key} className={`chip-btn ${difficulty === d.key ? 'active' : ''}`} onClick={() => setDifficulty(d.key)}>
              {d.icon} {d.label}
            </button>
          ))}
        </div>
      </div>

      {library.availability === 'none' ? (
        <div className="panel scn-empty-state">
          <div className="scn-empty-icon"><IconShield size={22} /></div>
          <h3 className="scn-empty-title">No practice scenarios for you yet</h3>
          <p className="scn-empty-reason">{library.availability_reason}</p>
          <button className="btn btn-primary btn-sm" onClick={() => onNavigate?.('skills')}>
            Update my skills and target role <IconArrowRight size={14} />
          </button>
        </div>
      ) : filtered.length === 0 ? (
        <div className="empty">No scenarios match those filters yet.</div>
      ) : (
        <>
          {(groups.not_started.length > 0) && (
            <ScenarioGroup title="Not started" count={groups.not_started.length} scns={groups.not_started} hasTarget={hasTarget} recommended={library.recommended} onStart={onStart} onDetails={onDetails} />
          )}
          {(groups.in_progress.length > 0) && (
            <ScenarioGroup title="In progress" count={groups.in_progress.length} scns={groups.in_progress} hasTarget={hasTarget} recommended={library.recommended} onStart={onStart} onDetails={onDetails} />
          )}
          {(groups.completed.length > 0) && (
            <ScenarioGroup title="Completed" count={groups.completed.length} scns={groups.completed} hasTarget={hasTarget} recommended={library.recommended} onStart={onStart} onDetails={onDetails} />
          )}
        </>
      )}

      <div className="scn-note panel">
        <IconShield size={15} />
        <span>{library.note}</span>
      </div>
    </>
  )
}

function ScenarioGroup({ title, count, scns, hasTarget, recommended, onStart, onDetails }: {
  title: string
  count: number
  scns: ScenarioCard[]
  hasTarget: boolean
  recommended: string[]
  onStart: (id: string) => void
  onDetails: (scn: ScenarioCard) => void
}) {
  return (
    <section className="scn-group" aria-label={`${title} scenarios`}>
      <h3 className="scn-group-title">{title} <span className="scn-group-count">{count}</span></h3>
      <div className="scn-grid">
        {scns.map((scn) => (
          <ScenarioCardView key={scn.id} scn={scn} recommended={recommended.includes(scn.id)} hasTarget={hasTarget} onStart={() => onStart(scn.id)} onDetails={() => onDetails(scn)} />
        ))}
      </div>
    </section>
  )
}

function ScenariosSkeleton() {
  return (
    <div className="scn-page" role="status" aria-label="Loading practice scenarios">
      <div className="scn-skel-hero skeleton" />
      <div className="scn-stats">
        {Array.from({ length: 4 }).map((_, i) => <div className="scn-skel-stat skeleton" key={i} />)}
      </div>
      <div className="scn-filters">
        {Array.from({ length: 4 }).map((_, i) => <div className="scn-skel-chip skeleton" key={i} />)}
      </div>
      <div className="scn-grid">
        {Array.from({ length: 6 }).map((_, i) => <div className="scn-skel-card skeleton" key={i} />)}
      </div>
      <div className="scn-skel-note skeleton" />
    </div>
  )
}

function ScenarioCardView({ scn, recommended, hasTarget, onStart, onDetails }: {
  scn: ScenarioCard
  recommended: boolean
  hasTarget: boolean
  onStart: () => void
  onDetails: () => void
}) {
  return (
    <article className="panel scn-card">
      <div className="scn-card-top">
        <span className="scn-cat">{scn.category_icon} {scn.category_label}</span>
        {scn.family_label && <span className="scn-fam">{scn.family_icon} {scn.family_label}</span>}
        {recommended && <span className="scn-badge">Recommended</span>}
      </div>
      <h3 className="scn-card-title">{scn.title}</h3>
      <p className="scn-card-desc">{scn.description}</p>
      <div className="scn-card-meta">
        <span className="scn-pill">{scn.difficulty_icon} {scn.difficulty_label}</span>
        <span className="scn-pill"><IconClock size={12} /> {scn.estimated_time_label}</span>
        <span className="scn-pill">{scn.steps_count} steps</span>
        <span className="scn-pill">{scn.skills.length} skills</span>
      </div>
      {scn.skills.length > 0 && (
        <div className="scn-skills">
          {scn.skills.slice(0, 4).map((s) => <span key={s} className="skill-tag">{s}</span>)}
          {scn.skills.length > 4 && <span className="skill-tag">+{scn.skills.length - 4}</span>}
        </div>
      )}
      <div className="scn-card-foot">
        {scn.status === 'in_progress' && <span className="scn-status in-progress">In progress</span>}
        {scn.status === 'completed' && scn.best_score != null && (
          <span className="scn-score"><IconTrophy size={13} /> Best {scn.best_score}%</span>
        )}
        {scn.status === 'completed' && scn.attempts_count > 1 && <span className="scn-attempts">{scn.attempts_count} attempts</span>}
        <div className="scn-card-actions">
          <button className="btn btn-ghost btn-sm" onClick={onDetails} aria-label={`See details for ${scn.title}`}>
            <IconEye size={13} /> Details
          </button>
          <button className="btn btn-primary btn-sm" onClick={onStart}>
            {scn.status === 'in_progress' ? 'Resume' : scn.status === 'completed' ? 'Practice again' : 'Start scenario'} <IconArrowRight size={14} />
          </button>
        </div>
      </div>
    </article>
  )
}

function ScenarioDetail({ scn, hasTarget, onClose, onStart }: {
  scn: ScenarioCard
  hasTarget: boolean
  onClose: () => void
  onStart: () => void
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="scn-modal-backdrop" onClick={onClose}>
      <div className="scn-modal panel" role="dialog" aria-modal="true" aria-label={`Scenario details: ${scn.title}`} onClick={(e) => e.stopPropagation()}>
        <div className="scn-modal-top">
          <span className="scn-cat">{scn.category_icon} {scn.category_label}</span>
          {scn.family_label && <span className="scn-fam">{scn.family_icon} {scn.family_label}</span>}
          <span className="scn-pill">{scn.difficulty_icon} {scn.difficulty_label}</span>
          <span className="scn-pill"><IconClock size={12} /> {scn.estimated_time_label}</span>
          <button className="btn btn-ghost btn-sm scn-modal-close" onClick={onClose} aria-label="Close details">✕</button>
        </div>
        <h3 className="scn-card-title">{scn.title}</h3>
        <p className="scn-card-desc">{scn.description}</p>
        <div className="scn-modal-meta">
          <span><strong>{scn.steps_count}</strong> steps</span>
          <span><strong>{scn.skills.length}</strong> skills practiced</span>
          {scn.status === 'in_progress' && <span className="scn-status in-progress">In progress</span>}
          {scn.status === 'completed' && scn.best_score != null && <span className="scn-score"><IconTrophy size={13} /> Best {scn.best_score}%</span>}
        </div>
        <p className="scn-modal-sub">Skills you will practice</p>
        <div className="scn-skills scn-modal-skills">
          {scn.skills.map((s) => <span key={s} className="skill-tag">{s}</span>)}
        </div>
        {scn.role_title && <p className="scn-modal-role">Framed for the {scn.role_title} role.</p>}
        <div className="scn-modal-actions">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={onStart}>
            {scn.status === 'in_progress' ? 'Resume scenario' : scn.status === 'completed' ? 'Practice again' : 'Start scenario'} <IconArrowRight size={14} />
          </button>
        </div>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ Player

function PlayerView({
  studentId, state, setState, onResult, onBack,
}: {
  studentId: number
  state: PlayerState
  setState: (s: PlayerState) => void
  onResult: (r: ScenarioResult) => void
  onBack: () => void
}) {
  const step: ScenarioStepView | undefined = state.player?.step
  const progress = state.player?.progress
  const [activeTab, setActiveTab] = useState<string | null>(null)
  const [pendingFeedback, setPendingFeedback] = useState<ScenarioLastDecision | null>(null)
  const [selectedOptions, setSelectedOptions] = useState<string[]>([])
  const [hint, setHint] = useState<{ text: string; explanation: string; uses: number } | null>(null)
  const [hintQuestion, setHintQuestion] = useState('')
  const [decideBusy, setDecideBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    setActiveTab(step ? step.evidence[0]?.id ?? null : null)
    setSelectedOptions([])
    setHint(null)
    setHintQuestion('')
    setError('')
  }, [step?.id])

  const markViewed = (id: string) => {
    setState({ ...state, viewed: new Set(state.viewed).add(id) })
  }

  const askHint = async () => {
    if (!step || decideBusy) return
    setError('')
    try {
      const h = await api.scenarioHint(studentId, state.player!.attempt_id, hintQuestion.trim() || undefined)
      setHint({ text: h.hint, explanation: h.explanation || '', uses: h.hints_used })
      setHintQuestion('')
      if (h.hint_policy) {
        setState({ ...state, player: { ...state.player, hint_policy: h.hint_policy } })
      }
    } catch (e) {
      setError((e as Error)?.message || 'Hint unavailable right now')
    }
  }

  const decide = async (payload: { decision_id?: string; option_ids?: string[] }) => {
    if (!step || decideBusy) return
    setDecideBusy(true)
    setError('')
    try {
      const res = await api.decideScenario(studentId, state.player!.attempt_id, {
        ...payload,
        evidence_viewed: Array.from(state.viewed),
      })
      if ('completed' in res) {
        onResult(res)
      } else {
        // Explain this decision's consequence before revealing the next step.
        setPendingFeedback(res.last_decision ?? null)
        setState({ player: res, viewed: new Set(), busy: false })
        setDecideBusy(false)
      }
    } catch (e) {
      setError((e as Error)?.message || 'Something went wrong recording your decision')
      setDecideBusy(false)
    }
  }

  const toggleOption = (id: string) => {
    setSelectedOptions((prev) => (prev.includes(id) ? prev.filter((o) => o !== id) : [...prev, id]))
  }

  if (!state.player || !step || !progress) {
    return (
      <div className="scn-player-empty panel">
        <button className="btn btn-ghost" onClick={onBack} aria-label="Back to scenarios"><IconBack size={14} /> Back to scenarios</button>
        <div className="empty">Loading scenario…</div>
      </div>
    )
  }

  const phaseIdx = progress.step_number - 1
  const phase = progress.phases[phaseIdx]
  const stepPct = Math.round(((progress.step_number - 1) / Math.max(1, progress.total_steps)) * 100)

  return (
    <div className="scn-player">
      <div className="scn-player-head panel">
        <button className="btn btn-ghost btn-sm" onClick={onBack} aria-label="Save progress and exit scenario"><IconBack size={13} /> Save &amp; exit</button>
        <div className="scn-player-title">
          <strong>{state.player.scenario_title || 'Scenario'}</strong>
          <span>{phase ? `${phase.icon} ${phase.label} · Step ${progress.step_number} of ${progress.total_steps}` : `Step ${progress.step_number} of ${progress.total_steps}`}</span>
          <span
            className="scn-player-role" title={state.player.target_role || state.player.role_title || ''}
            aria-label={state.player.target_role ? `Target role: ${state.player.target_role}` : undefined}
          >
            <IconShield size={12} /> {state.player.target_role || state.player.role_title || ''}
          </span>
        </div>
        <div className="scn-phase-strip" aria-label="Scenario progress">
          {progress.phases.map((p) => (
            <span key={p.key} className={`scn-phase-dot ${p.key === progress.current_phase ? 'active' : ''}`} title={p.label}>{p.icon}</span>
          ))}
        </div>
      </div>
      <div className="scn-step-track" aria-hidden="true">
        <span style={{ width: `${stepPct}%` }} />
      </div>

      {state.busy ? (
        <div className="empty">Starting scenario…</div>
      ) : pendingFeedback ? (
        <FeedbackPanel feedback={pendingFeedback} onContinue={() => setPendingFeedback(null)} />
      ) : (
        <>
          <section className="scn-brief panel">
            <div className="scn-brief-eyebrow">{phase ? `${phase.icon} ${phase.label}` : 'You are on the scene'}</div>
            {step.intro && <p className="scn-intro">{step.intro}</p>}
            <h3>{step.title}</h3>
            <p className="scn-situation">{step.situation}</p>
          </section>

          {state.player.hint_policy.deduction > 0 && (
            <div className="scn-hint-score-note">
              <IconLightbulb size={13} /> Hints used so far: {state.player.hint_policy.used} · −{state.player.hint_policy.deduction} points off your score (each hint costs {state.player.hint_policy.penalty}, capped at {state.player.hint_policy.cap} total).
            </div>
          )}

          {step.evidence.length > 0 && (
            <section className="scn-evidence panel">
              <div className="scn-evidence-tabs" role="tablist" aria-label="Evidence tabs">
                {step.evidence.map((e) => (
                  <button
                    key={e.id}
                    role="tab"
                    aria-selected={activeTab === e.id}
                    className={`scn-ev-tab ${activeTab === e.id ? 'active' : ''}`}
                    onClick={() => { setActiveTab(e.id); markViewed(e.id) }}
                  >
                    {e.icon} {e.tab}
                  </button>
                ))}
              </div>
              <div className="scn-evidence-body">
                {(() => {
                  const ev = step.evidence.find((x) => x.id === activeTab) || step.evidence[0]
                  return ev ? <EvidencePane ev={ev} viewed={state.viewed.has(ev.id)} onView={() => markViewed(ev.id)} /> : <div className="empty">No evidence here.</div>
                })()}
              </div>
            </section>
          )}

          <section className="scn-decision panel">
            <div className="scn-decision-head">
              <h3>{step.multi ? 'Identify the indicators' : 'What do you do next?'}</h3>
              <button className="btn btn-ghost btn-sm" onClick={askHint} disabled={decideBusy} aria-label="Ask the AI for a hint">
                <IconLightbulb size={14} /> Ask the AI for a hint
              </button>
            </div>

            {hint && (
              <div className="scn-hint">
                <p className="scn-hint-text">{hint.text}</p>
                {hint.explanation && <p className="scn-hint-more">{hint.explanation}</p>}
                <div className="scn-hint-ask">
                  <input
                    aria-label="Ask a specific question about this step"
                    value={hintQuestion}
                    onChange={(e) => setHintQuestion(e.target.value)}
                    placeholder="Ask a specific question (doesn't count as a hint)"
                  />
                  <button className="btn btn-sm" onClick={askHint} disabled={decideBusy}><IconChat size={13} /> Ask</button>
                </div>
                <span className="scn-hint-meta">
                  Curated guidance · {hint.uses} hint{hint.uses === 1 ? '' : 's'} used · each hint reduces your score by {state.player.hint_policy.penalty} points (capped at {state.player.hint_policy.cap} total)
                </span>
              </div>
            )}

            {step.multi && step.options ? (
              <>
                <p className="scn-instructions">Select every sign that should raise concern. Look at the evidence above before you choose.</p>
                <div className="scn-options" role="group" aria-label="Indicators to select">
                  {step.options.map((o) => (
                    <label key={o.id} className={`scn-option ${selectedOptions.includes(o.id) ? 'selected' : ''}`}>
                      <input type="checkbox" checked={selectedOptions.includes(o.id)} onChange={() => toggleOption(o.id)} />
                      <span>{o.label}</span>
                    </label>
                  ))}
                </div>
                <button className="btn btn-primary" disabled={!selectedOptions.length || decideBusy} onClick={() => decide({ option_ids: selectedOptions })}>
                  Confirm what you found <IconArrowRight size={14} />
                </button>
              </>
            ) : (
              <div className="scn-decisions" role="group" aria-label="Actions">
                {(step.decisions || []).map((d) => (
                  <button key={d.id} className="scn-decision-btn" disabled={decideBusy} onClick={() => decide({ decision_id: d.id })}>
                    <span className="scn-decision-icon">{d.icon}</span>
                    <span>{d.label}</span>
                    <IconArrowRight size={16} className="scn-decision-chev" />
                  </button>
                ))}
              </div>
            )}

            {error && <div className="error scn-error">{error}</div>}
          </section>
        </>
      )}
    </div>
  )
}

function FeedbackPanel({ feedback, onContinue }: { feedback: ScenarioLastDecision; onContinue: () => void }) {
  const verdict = feedback.good ? 'good' : feedback.verdict === 'neutral' ? 'neutral' : 'bad'
  const verdictLabel = feedback.good ? 'Good call' : feedback.verdict === 'neutral' ? 'Watch out' : 'Risky call'
  return (
    <section className={`panel scn-feedback ${verdict}`} aria-live="polite">
      <div className="scn-feedback-eyebrow">Decision explained</div>
      <div className="scn-feedback-head">
        <span className={`scn-feedback-verdict ${verdict}`}>{verdictLabel}{feedback.points ? <span className="scn-feedback-pts"> +{feedback.points} pts</span> : null}</span>
        <span className="scn-feedback-choice">{feedback.icon} {feedback.label}</span>
      </div>
      <p className="scn-feedback-reason"><strong>Why:</strong> {feedback.feedback}</p>
      {feedback.consequence && <p className="scn-feedback-consequence"><strong>What happens next:</strong> {feedback.consequence}</p>}
      <button className="btn btn-primary" onClick={onContinue}>
        Continue to the next step <IconArrowRight size={14} />
      </button>
    </section>
  )
}

function EvidencePane({ ev, viewed, onView }: { ev: ScenarioEvidence; viewed: boolean; onView: () => void }) {
  return (
    <div className={`scn-evidence-pane ${viewed ? 'viewed' : ''}`}>
      <div className="scn-evidence-head">
        <h4>{ev.icon} {ev.title}</h4>
        {viewed ? (
          <span className="scn-ev-status opened"><IconCheck size={12} /> Reviewing</span>
        ) : (
          <button className="btn btn-ghost btn-sm" onClick={onView} aria-label="Mark evidence as reviewed"><IconEye size={13} /> Mark as reviewed</button>
        )}
      </div>
      {ev.has_data ? (
        <table className="scn-ev-table">
          <tbody>
            {ev.content.map((row, i) => (
              <tr key={i}><th>{row.label}</th><td>{row.value}</td></tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="scn-ev-empty">This channel has no data to inspect right now.</p>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ Results

function ResultsView({ result, onReplay, onBack, onNavigate }: {
  result: ScenarioResult
  onReplay: () => void
  onBack: () => void
  onNavigate?: (section: string, focus?: NavFocus) => void
}) {
  const toneClass = result.verdict_tone === 'great' || result.verdict_tone === 'good' ? 'good' : result.verdict_tone === 'fair' ? 'fair' : 'review'
  const fu = result.follow_up
  const hintMeta = result.hints_used > 0
    ? `${result.hints_used} hint${result.hints_used === 1 ? '' : 's'} used · −${result.hint_policy.deduction} points`
    : 'No hints used'
  return (
    <div className="scn-results">
      <div className={`panel scn-result-hero ${toneClass}`}>
        <div className="scn-result-outcome">{result.outcome.icon}</div>
        <div className="scn-result-main">
          <p className="eyebrow">Scenario complete · {result.title}</p>
          <h2>{result.outcome.title}</h2>
          <p className="scn-result-summary">{result.outcome.summary}</p>
          <div className="scn-result-note"><IconShield size={13} /> {result.note}</div>
        </div>
        <div className="scn-score-wrap">
          <div className={`scn-score-ring ${toneClass}`}>
            <strong>{result.score}%</strong>
            <span>score</span>
          </div>
          <span className="scn-verdict">{result.verdict_label}</span>
        </div>
      </div>

      <div className="scn-results-grid">
        <section className="panel scn-result-section">
          <SectionTitle eyebrow="How you performed" title="Competency breakdown" />
          <div className="scn-bars">
            {result.components.map((c) => (
              <div key={c.key} className="scn-bar-row">
                <span className="scn-bar-label">{c.label}</span>
                <div className="scn-bar"><span style={{ width: `${c.pct ?? 0}%` }} /></div>
                <span className="scn-bar-val">{c.pct != null ? `${c.pct}%` : '—'}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="panel scn-result-section">
          <SectionTitle eyebrow="What's next" title="Recommended follow-up" />
          <p className="scn-fu-message">{fu.message}</p>
          {fu.component_label && (
            <p className="scn-fu-comp">Weakest competency: <strong>{fu.component_label}</strong>{fu.weakness_pct != null ? ` at ${fu.weakness_pct}%` : ''}</p>
          )}
          <div className="scn-fu-actions">
            {fu.action === 'lesson' && fu.skill_id != null && (
              <button
                className="btn btn-primary btn-sm"
                onClick={() => onNavigate?.('learning', { skillId: fu.skill_id as number, roleTitle: result.target_role || result.role_title })}
              >
                Review {fu.skill} in Learning <IconArrowRight size={14} />
              </button>
            )}
            <button className="btn btn-sm" onClick={onReplay}><IconBolt size={14} /> Practice again</button>
          </div>
          {result.strengths.length > 0 && (
            <div className="scn-strengths">
              <strong>Strengths</strong>
              <ul>{result.strengths.map((s, i) => <li key={i}>{s}</li>)}</ul>
            </div>
          )}
          {result.improvements.length > 0 && (
            <div className="scn-improvements">
              <strong>To improve</strong>
              <ul>{result.improvements.map((s, i) => <li key={i}>{s}</li>)}</ul>
            </div>
          )}
        </section>
      </div>

      <section className="panel scn-result-section">
        <SectionTitle eyebrow="Overview" title="Profile signals" />
        {result.match.before != null ? (
          <div className="scn-match">
            <div className="scn-match-score">
              <span className="scn-match-val">{result.match.before}%</span>
              <span>Match before</span>
            </div>
            <IconArrowRight size={14} />
            <div className="scn-match-score">
              <span className="scn-match-val">{result.match.after ?? result.match.before}%</span>
              <span>Match after</span>
            </div>
            {result.match.delta != null && result.match.delta !== 0 && (
              <span className={`scn-delta ${result.match.delta > 0 ? 'up' : ''}`}>
                {result.match.delta > 0 ? '+' : ''}{result.match.delta}%
              </span>
            )}
          </div>
        ) : (
          <p className="scn-muted">Set a target role on Skills & Roles to see how scenario practice moves your match score.</p>
        )}

        {result.skills.length > 0 && (
          <div className="scn-skills-list">
            <strong>Skills strengthened</strong>
            {result.skills.map((s) => (
              <div key={s.name} className="scn-skill-row">
                <span>{s.name}</span>
                <div className="scn-bar"><span style={{ width: `${s.pct ?? 0}%` }} /></div>
                <span className="scn-bar-val">{s.pct != null ? `${s.pct}%` : '—'}</span>
              </div>
            ))}
            {result.skills_updated.length > 0 && (
              <p className="scn-practice-lift">
                Practice confidence lifted for {result.skills_updated.map((d) => d.skill).join(', ')} —
                verification still requires the Assessment.
              </p>
            )}
          </div>
        )}
      </section>

      <section className="panel scn-result-section">
        <SectionTitle eyebrow="Your choices" title="Decision review" meta={hintMeta} />
        <div className="scn-review-list">
          {result.decision_review.map((row: ScenarioDecisionRow, i: number) => (
            <div key={i} className={`scn-review-row ${row.good ? 'good' : row.verdict === 'neutral' ? 'neutral' : 'bad'}`}>
              <div className="scn-review-head">
                <span className="scn-review-verdict">{row.good ? 'Good call' : row.verdict === 'neutral' ? 'Watch out' : 'Risky call'}</span>
                <span className="scn-review-step">{row.step_title}</span>
              </div>
              <p><span className="scn-review-decision">{row.icon} {row.decision}</span></p>
              <p className="scn-review-feedback">{row.feedback}</p>
              {row.consequence && <p className="scn-review-consequence">{row.consequence}</p>}
            </div>
          ))}
        </div>
      </section>

      <div className="scn-results-actions">
        <button className="btn" onClick={onReplay}><IconBolt size={14} /> Practice again</button>
        <button className="btn btn-ghost" onClick={onBack} aria-label="Back to all scenarios"><IconBack size={14} /> All scenarios</button>
        {fu && fu.skill_id != null && (
          <button className="btn btn-primary" onClick={() => onNavigate?.('assessments', { skillId: fu.skill_id as number, roleTitle: result.target_role || result.role_title })}>
            Take the Assessment <IconShield size={14} />
          </button>
        )}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ History

function HistoryView({ loadError, history, onRetry, onOpenAttempt, onBack }: {
  loadError: string
  history: ScenarioHistory | null
  onRetry: () => void
  onOpenAttempt: (attemptId: number) => void
  onBack: () => void
}) {
  return (
    <div className="scn-history">
      <div className="panel scn-history-head">
        <div>
          <p className="eyebrow">Scenario History</p>
          <h2>Your practice attempts</h2>
          <p className="scn-hero-sub">Every attempt with the scenario version, your score, and the role it was framed for.</p>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={onBack} aria-label="Back to scenarios"><IconBack size={13} /> All scenarios</button>
      </div>

      {loadError ? (
        <div className="error scn-error">
          <span>{loadError}</span>
          <button className="btn btn-sm" onClick={onRetry}>Retry</button>
        </div>
      ) : !history ? (
        <div className="panel scn-history-empty" role="status">Loading your history…</div>
      ) : history.attempts.length === 0 ? (
        <div className="panel scn-history-empty">
          <div className="scn-empty-icon"><IconClock size={22} /></div>
          <h3 className="scn-empty-title">No practice attempts yet</h3>
          <p className="scn-empty-reason">Start a scenario from the Practice library — every attempt shows up here with its version and score.</p>
          <button className="btn btn-primary btn-sm" onClick={onBack}>Browse scenarios <IconArrowRight size={14} /></button>
        </div>
      ) : (
        <div className="scn-history-list">
          {history.attempts.map((a) => (
            <HistoryRow key={a.attempt_id} a={a} onOpen={() => onOpenAttempt(a.attempt_id)} />
          ))}
        </div>
      )}
    </div>
  )
}

function HistoryRow({ a, onOpen }: { a: ScenarioHistoryEntry; onOpen: () => void }) {
  const isInProgress = a.status === 'in_progress'
  return (
    <article className={`panel scn-history-row ${isInProgress ? 'in-progress' : ''}`}>
      <div className="scn-history-main">
        <span className="scn-history-diff">{a.difficulty_icon}</span>
        <div>
          <h3 className="scn-history-title">{a.title}</h3>
          <p className="scn-history-meta">
            {a.role_title && <span className="scn-pill">{a.role_title}</span>}
            {a.family_label && <span className="scn-fam">{a.family_icon} {a.family_label}</span>}
            <span className="scn-pill">v{a.scenario_version}</span>
            {a.hints_used > 0 && <span className="scn-pill">{a.hints_used} hint{a.hints_used === 1 ? '' : 's'}</span>}
          </p>
        </div>
      </div>
      <div className="scn-history-score">
        {isInProgress ? (
          <span className="scn-status in-progress">In progress</span>
        ) : (
          <strong className="scn-history-score-val">{a.score != null ? `${a.score}%` : '—'}</strong>
        )}
        <span className="scn-history-date">{formatDate(a.completed_at ?? a.started_at)}</span>
      </div>
      <button className="btn btn-sm" onClick={onOpen}>
        {isInProgress ? 'Resume' : 'View results'} <IconArrowRight size={13} />
      </button>
    </article>
  )
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  const d = new Date(value.replace(' ', 'T') + 'Z')
  if (isNaN(d.getTime())) return value
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) +
    ' · ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}