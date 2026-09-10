import React, { useEffect, useMemo, useState } from 'react'
import { useApp } from '../AppContext'
import { api } from '../lib/api'
import { SectionTitle } from '../components/learning'
import {
  IconArrowRight, IconBack, IconBolt, IconCheck, IconChat, IconClock, IconEye, IconLightbulb,
  IconShield, IconTrophy, IconUsers,
} from '../components/Icons'
import type {
  ScenarioCard, ScenarioDecisionRow, ScenarioEvidence, ScenarioLibrary, ScenarioPlayer, ScenarioResult,
  ScenarioStepView,
} from '../lib/types'

type View = 'library' | 'player' | 'results'

interface PlayerState {
  player: ScenarioPlayer
  viewed: Set<string>
  busy: boolean
}

export default function ScenariosPage({ onNavigate }: { onNavigate?: (section: string) => void }) {
  const { session, applyCopilot } = useApp()
  const studentId = session?.student?.id ?? 0

  useEffect(() => {
    applyCopilot({ page: 'scenarios', skillId: null, competency: null, jobTitle: null, jobUrl: null })
  }, [applyCopilot])

  const [view, setView] = useState<View>('library')
  const [category, setCategory] = useState('all')
  const [loadError, setLoadError] = useState('')
  const [library, setLibrary] = useState<ScenarioLibrary | null>(null)
  const [player, setPlayer] = useState<PlayerState | null>(null)
  const [result, setResult] = useState<ScenarioResult | null>(null)

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

  const backToLibrary = () => {
    loadLibrary(true)
    setView('library')
    setPlayer(null)
    setResult(null)
    setCategory('all')
  }

  if (!studentId) return <div className="empty">Log in as a student to practice real-world scenarios.</div>

  return (
    <div className="scn-page">
      {view === 'library' && (
        <LibraryView
          loadError={loadError}
          library={library}
          category={category}
          setCategory={setCategory}
          onStart={start}
          onNavigate={onNavigate}
        />
      )}
      {view === 'player' && player && (
        <PlayerView
          studentId={studentId}
          state={player}
          setState={setPlayer}
          onResult={(r) => { setResult(r); setView('results') }}
          onBack={backToLibrary}
        />
      )}
      {view === 'results' && result && (
        <ResultsView result={result} onReplay={() => start(result.scenario_id)} onBack={backToLibrary} onNavigate={onNavigate} />
      )}
    </div>
  )
}

// ------------------------------------------------------------------ Library

function LibraryView({
  loadError, library, category, setCategory, onStart, onNavigate,
}: {
  loadError: string
  library: ScenarioLibrary | null
  category: string
  setCategory: (c: string) => void
  onStart: (id: string) => void
  onNavigate?: (section: string) => void
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
    if (category === 'all') return byRecommended
    return byRecommended.filter((s) => s.category === category)
  }, [byRecommended, category])

  if (loadError) return <div className="error scn-error">{loadError}</div>
  if (!library) return <div className="empty scn-loading">Loading practice scenarios…</div>

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
        {hasTarget && (
          <button className="btn btn-primary btn-block scn-hero-cta" onClick={() => onNavigate?.('learning')}>
            <IconShield size={15} /> Back to your learning path <IconArrowRight size={14} />
          </button>
        )}
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

      <div className="scn-filters" role="group" aria-label="Filter scenarios by category">
        <button className={`chip-btn ${category === 'all' ? 'active' : ''}`} onClick={() => setCategory('all')}>All</button>
        {(library.categories || []).map((c: { key: string; label: string; icon: string }) => (
          <button key={c.key} className={`chip-btn ${category === c.key ? 'active' : ''}`} onClick={() => setCategory(c.key)}>
            {c.icon} {c.label}
          </button>
        ))}
      </div>

      {library.availability === 'none' ? (
        <div className="panel scn-empty-state">
          <div className="scn-empty-icon"><IconShield size={22} /></div>
          <h3 className="scn-empty-title">No practice scenarios for you yet</h3>
          <p className="scn-empty-reason">{library.availability_reason}</p>
          <button className="btn btn-primary btn-sm" onClick={() => onNavigate?.('skills_roles')}>
            Update my skills and target role <IconArrowRight size={14} />
          </button>
        </div>
      ) : filtered.length === 0 ? (
        <div className="empty">No scenarios in this category yet.</div>
      ) : (
        <div className="scn-grid">
          {filtered.map((scn) => (
            <ScenarioCardView key={scn.id} scn={scn} recommended={library.recommended.includes(scn.id)} onStart={() => onStart(scn.id)} hasTarget={hasTarget} />
          ))}
        </div>
      )}

      <div className="scn-note panel">
        <IconShield size={15} />
        <span>{library.note}</span>
      </div>
    </>
  )
}

function ScenarioCardView({ scn, recommended, onStart, hasTarget }: { scn: ScenarioCard; recommended: boolean; onStart: () => void; hasTarget: boolean }) {
  return (
    <article className="panel scn-card">
      <div className="scn-card-top">
        <span className="scn-cat">{scn.category_icon} {scn.category_label}</span>
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
        <button className="btn btn-primary btn-sm" onClick={onStart}>
          {scn.status === 'in_progress' ? 'Resume' : scn.status === 'completed' ? 'Practice again' : 'Start scenario'} <IconArrowRight size={14} />
        </button>
      </div>
    </article>
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
        <button className="btn btn-ghost" onClick={onBack}><IconBack size={14} /> Back to scenarios</button>
        <div className="empty">Loading scenario…</div>
      </div>
    )
  }

  const phaseIdx = progress.step_number - 1
  const phase = progress.phases[phaseIdx]

  return (
    <div className="scn-player">
      <div className="scn-player-head panel">
        <button className="btn btn-ghost btn-sm" onClick={onBack}><IconBack size={13} /> Exit</button>
        <div className="scn-player-title">
          <strong>{state.player.scenario_title || libraryTitle(state.player.scenario_id) || 'Scenario'}</strong>
          <span>{phase ? `${phase.icon} ${phase.label} · Step ${progress.step_number} of ${progress.total_steps}` : `Step ${progress.step_number} of ${progress.total_steps}`}</span>
        </div>
        <div className="scn-phase-strip" aria-label="Scenario progress">
          {progress.phases.map((p) => (
            <span key={p.key} className={`scn-phase-dot ${p.key === progress.current_phase ? 'active' : ''}`} title={p.label}>{p.icon}</span>
          ))}
        </div>
      </div>

      {state.busy ? (
        <div className="empty">Starting scenario…</div>
      ) : (
        <>
          <section className="scn-brief panel">
            <div className="scn-brief-eyebrow">{phase ? `${phase.icon} ${phase.label}` : 'You are on the scene'}</div>
            {step.intro && <p className="scn-intro">{step.intro}</p>}
            <h3>{step.title}</h3>
            <p className="scn-situation">{step.situation}</p>
          </section>

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
              <button className="btn btn-ghost btn-sm" onClick={askHint} disabled={decideBusy}>
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
                <span className="scn-hint-meta">Curated guidance · {hint.uses} hint{hint.uses === 1 ? '' : 's'} used</span>
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

function EvidencePane({ ev, viewed, onView }: { ev: ScenarioEvidence; viewed: boolean; onView: () => void }) {
  return (
    <div className={`scn-evidence-pane ${viewed ? 'viewed' : ''}`}>
      <div className="scn-evidence-head">
        <h4>{ev.icon} {ev.title}</h4>
        {viewed ? (
          <span className="scn-ev-status opened"><IconCheck size={12} /> Reviewing</span>
        ) : (
          <button className="btn btn-ghost btn-sm" onClick={onView}><IconEye size={13} /> Mark as reviewed</button>
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
  onNavigate?: (section: string) => void
}) {
  const toneClass = result.verdict_tone === 'great' || result.verdict_tone === 'good' ? 'good' : result.verdict_tone === 'fair' ? 'fair' : 'review'
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

        <section className="panel scn-result-section">
          <SectionTitle eyebrow="Career impact" title="Profile signals" />
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
      </div>

      <section className="panel scn-result-section">
        <SectionTitle eyebrow="Your choices" title="Decision review" meta={`${result.hints_used} hint${result.hints_used === 1 ? '' : 's'} used`} />
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
        <button className="btn btn-ghost" onClick={onBack}><IconBack size={14} /> All scenarios</button>
        <button className="btn btn-primary" onClick={() => onNavigate?.('assessments')}>
          Take the Assessment <IconShield size={14} />
        </button>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ helpers

const SCENARIO_TITLES: Record<string, string> = {}

function libraryTitle(id: string): string {
  return SCENARIO_TITLES[id] || ''
}