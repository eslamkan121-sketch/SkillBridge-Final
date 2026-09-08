import React, { useEffect, useState } from 'react'
import { useApp } from '../AppContext'
import { api } from '../lib/api'
import { RELOCATION_MARKETS } from '../lib/markets'
import type { Analysis, ActivitySummary, Student, RoleRecord, Candidate, RoleSkillCoverage, RecentJob, RecentJobsResponse } from '../lib/types'
import { GapPill, SkillTag, LevelBadge, ScoreRing } from '../components/widgets'
import { IconArrowRight, IconCheck, IconVerified, IconFlame, IconBolt, IconLeaderboard, IconTrophy, IconExternal, IconShield, IconUpload } from '../components/Icons'

function nextStep(analysis: Analysis | undefined): string {
  if (!analysis) return 'Select a target role'
  if (analysis.gap_count === 0) return 'All requirements met — you are career ready!'
  const missing = analysis.skill_gaps.find((g) => g.status === 'missing')
  const gap = analysis.skill_gaps.find((g) => g.status === 'gap')
  const target = missing || gap
  return target ? target.skill_name : 'Take the next assessment'
}

function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text)
  const ta = document.createElement('textarea')
  ta.value = text
  document.body.appendChild(ta)
  ta.select()
  document.execCommand('copy')
  document.body.removeChild(ta)
  return Promise.resolve()
}

function JobsCard({ student }: { student?: Student }) {
  const { me, refreshStudent, applyCopilot } = useApp()
  const [data, setData] = useState<RecentJobsResponse | null>(null)
  const [tried, setTried] = useState(false)
  const [err, setErr] = useState('')
  const [uploading, setUploading] = useState(false)
  const [cvMsg, setCvMsg] = useState('')
  const [market, setMarket] = useState(() => localStorage.getItem('jobs.market') || '')

  const hasCvSkills = (student?.self_reported_skills?.length ?? 0) > 0
  const cvKey = (student?.self_reported_skills || []).map((s) => s.name).sort().join('|')

  useEffect(() => {
    if (!me?.student?.id || !hasCvSkills) return
    setData(null)
    setTried(false)
    setErr('')
    localStorage.setItem('jobs.market', market)
    const s = me.student as any
    const location = s?.location || (me as any)?.location || ''
    const country = s?.country || (me as any)?.country || ''
    api.recentJobs({ location, country, market })
      .then((d) => { setData(d); setTried(true) })
      .catch((e) => { console.error('[dashboard] recent jobs failed:', e); setErr(e.message || String(e)); setData(null); setTried(true) })
  }, [me?.student?.id, cvKey, market])

  const openJob = (j: RecentJob) => {
    applyCopilot({ page: 'jobs', skillId: null, competency: null, jobTitle: j.title, jobUrl: j.url || null })
  }

  const onUpload = async (file: File | undefined) => {
    if (!file || !student) return
    setUploading(true); setCvMsg('')
    try {
      const res = await api.uploadCv(student.id, file)
      setCvMsg(`Extracted ${res.extracted.length} skills — searching roles matched to your CV…`)
      await refreshStudent()
    } catch (e: any) {
      setErr(e.message || 'CV upload failed')
    } finally {
      setUploading(false)
    }
  }

  if (!hasCvSkills) {
    return (
      <div className="card mt" style={{ marginTop: 18 }}>
        <div className="flex between" style={{ flexWrap: 'wrap', gap: 8 }}>
          <h3 style={{ margin: 0 }}>Recent roles for you</h3>
        </div>
        <p className="card-sub" style={{ marginTop: 4 }}>
          Jobs are matched to your CV. Upload a CV so we can pull real openings that fit the skills you actually have.
        </p>
        <div className="onboard-cta" style={{ marginTop: 10 }}>
          <label className="btn btn-primary" style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <IconUpload size={14} /> {uploading ? 'Extracting and matching…' : 'Upload CV to see matched roles'}
            <input type="file" accept=".txt,.md,.pdf" style={{ display: 'none' }} onChange={(e) => onUpload(e.target.files?.[0])} />
          </label>
        </div>
        {cvMsg && <p className="small" style={{ color: 'var(--green)', marginTop: 8 }}>{cvMsg}</p>}
        {err && <div className="error" style={{ marginTop: 10 }}>{err}</div>}
      </div>
    )
  }

  return (
    <div className="card mt" style={{ marginTop: 18 }}>
      <div className="flex between" style={{ flexWrap: 'wrap', gap: 8 }}>
        <h3 style={{ margin: 0 }}>Recent roles for you</h3>
        <span className="small muted">
          {data?.source === 'live' ? 'Live feed'
            : data?.source === 'empty' ? 'No live matches right now'
            : data?.source === 'unavailable' ? 'Live feed temporarily unavailable'
            : '…'}
        </span>
      </div>
      <p className="card-sub" style={{ marginTop: 4 }}>
        Real, recent openings matched to your CV skills, ranked most fitting first. Senior roles are de-ranked for early-career profiles.
      </p>
      <div className="flex between" style={{ alignItems: 'center', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
        <span className="small muted">
          JSearch and other feeds cover many markets — add a remote/relocation search country (e.g. Egypt, UAE) to widen reach.
        </span>
        <select
          className="market-select"
          value={market}
          onChange={(e) => setMarket(e.target.value)}
          aria-label="Remote / relocation search country"
          style={{ maxWidth: 260 }}
        >
          {RELOCATION_MARKETS.map((m) => (
            <option key={m.code} value={m.code}>{m.label}</option>
          ))}
        </select>
      </div>
      {err && <div className="error" style={{ marginBottom: 10 }}>{err}</div>}
      {!tried ? (
        <div className="loading">Matching opening roles to your CV…</div>
      ) : data && data.jobs.length > 0 ? (
        <div className="stack">
          {data.jobs.map((j, i) => {
            const pct = j.match_pct ?? 0
            const isSeniorFit = pct <= 15
            const place = j.location_label || j.location || j.country
            const inner = (
              <>
                <div className="job-match-badge" style={{ background: pct >= 40 ? 'var(--green)' : pct >= 20 ? 'var(--amber)' : 'var(--slate-300)' }}>
                  {pct}
                </div>
                <div className="resource-main">
                  <span className="resource-title">{j.title}</span>
                  <span className="resource-meta">
                    {j.company}
                    {j.is_expired ? ' · Expired' : ''}
                    {!j.is_expired && j.listed_days_ago != null ? ` · Posted ${j.listed_days_ago}d ago` : ''}
                    {j.source ? ` · ${j.source}` : ''}
                    {j.seniority ? ` · ${j.seniority}` : ''}
                    {place ? ` · ${place}` : ''}
                  </span>
                  {j.match_reason && <span className="job-reason">{j.match_reason}</span>}
                </div>
                {j.tags && j.tags.length > 0 && (
                  <div style={{ marginLeft: 'auto', display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {j.tags.slice(0, 3).map((t) => <span className="chip" key={t} style={{ background: 'var(--slate-100)', color: 'var(--slate-500)' }}>{t}</span>)}
                  </div>
                )}
              </>
            )
            return j.is_expired ? (
              <div className={`resource ${isSeniorFit ? 'job-senior' : ''}`} key={`${j.title}-${i}`} title="Listing has expired — no direct link" style={{ cursor: 'pointer' }} onClick={() => openJob(j)}>
                {inner}
              </div>
            ) : (
              <a
                className={`resource ${isSeniorFit ? 'job-senior' : ''}`}
                key={`${j.title}-${i}`}
                href={j.url}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => openJob(j)}
              >
                {inner}
              </a>
            )
          })}
        </div>
      ) : data?.source === 'empty' ? (
        <div>
          <div className="empty">No live roles matched this search right now — nothing is invented to fill the list.</div>
          {data.providers && data.providers.some((p) => p.status === 'failed') ? (
            <p className="small muted" style={{ marginTop: 8 }}>
              Unavailable now: {data.providers.filter((p) => p.status === 'failed').map((f) => f.source).join(', ')}.
            </p>
          ) : null}
        </div>
      ) : data?.source === 'unavailable' ? (
        <div>
          <div className="empty">Live job providers are temporarily unavailable. Try again shortly.</div>
          {data.providers && data.providers.some((p) => p.status === 'failed') ? (
            <p className="small muted" style={{ marginTop: 8 }}>
              Unavailable now: {data.providers.filter((p) => p.status === 'failed').map((f) => f.source).join(', ')}.
            </p>
          ) : null}
        </div>
      ) : (
        <div className="empty">No recent roles available right now.</div>
      )}
    </div>
  )
}

export default function DashboardPage({ onNavigate }: { onNavigate?: (section: string) => void }) {
  const { me } = useApp()
  if (!me) return null
  if (me.entity_type === 'student') return <StudentDashboard student={me.student} analysis={me.analysis ?? undefined} onNavigate={onNavigate} />
  if (me.entity_type === 'company') return <CompanyDashboard />
  return <UniversityDashboard />
}

function StudentDashboard({ student, analysis, onNavigate }: { student?: Student; analysis?: Analysis; onNavigate?: (section: string) => void }) {
  const { refreshStudent, applyCopilot } = useApp()
  const [activity, setActivity] = useState<ActivitySummary | null>(null)
  const [shareOn, setShareOn] = useState(!!student?.share_public)
  const [copied, setCopied] = useState('')
  useEffect(() => {
    applyCopilot({ page: 'dashboard', skillId: null, competency: null, jobTitle: null, jobUrl: null })
  }, [])
  useEffect(() => {
    if (student) api.studentActivity(student.id)
      .then(setActivity)
      .catch((e) => { console.error('[dashboard] activity failed:', e) })
  }, [student?.id])
  useEffect(() => setShareOn(!!student?.share_public), [student?.share_public])
  if (!student) return <div className="empty">No student profile linked to this account.</div>

  const gaps = analysis?.skill_gaps || []
  const strong = gaps.filter((g) => g.status === 'strong').length
  const needsPractice = gaps.filter((g) => g.status === 'gap').length
  const missingCount = gaps.filter((g) => g.status === 'missing').length
  const gapCount = gaps.filter((g) => g.status !== 'strong').length
  const xpPct = activity ? Math.min(100, (activity.xp_into_level / activity.xp_per_level) * 100) : 0

  const hasSkills = student.self_reported_skills.length > 0 || student.verified_skills.length > 0

  // A skill belongs to exactly one row: verified evidence wins over self-reported.
  const merged = new Map<number, { name: string; level: string; verified: boolean }>()
  student.self_reported_skills.forEach((s) => merged.set(s.skill_id, { name: s.name, level: s.level, verified: false }))
  student.verified_skills.forEach((v) => merged.set(v.skill_id, { name: v.name, level: v.level, verified: true }))
  const skillRows = [...merged.values()].sort((a, b) => a.name.localeCompare(b.name))

  const publicUrl = `${window.location.origin}/p/${student.id}`
  const skillUrl = (skillId: number) => `${publicUrl}#skill-${skillId}`

  const go = (section: string) => onNavigate?.(section)

  const toggleShare = async (on: boolean) => {
    setShareOn(on)
    try {
      await api.updateStudent(student.id, { share_public: on ? 1 : 0 })
      refreshStudent()
    } catch {
      setShareOn(!on)
    }
  }

  const copy = (label: string, text: string) => {
    copyText(text).then(() => {
      setCopied(label)
      setTimeout(() => setCopied(''), 1600)
    })
  }

  if (!analysis) {
    return (
      <div>
        <div className="onboard">
          <div className="onboard-mark"><IconVerified size={30} /></div>
          {hasSkills ? (
            <h3>Pick a target career to unlock your gap map</h3>
          ) : (
            <h3>Choose your target career to get started</h3>
          )}
          <p>
            {hasSkills
              ? 'You have a skill profile. Choose a career you are aiming for and SkillBridge will map what you already have against what the job needs.'
              : 'Pick a career you are aiming for. SkillBridge matches it against your skills, then builds a verified learning + assessment loop to close the gaps.'}
          </p>
          <div className="onboard-cta">
            <button className="btn btn-primary" onClick={() => go('skills')}>
              <IconArrowRight size={16} /> Choose your target career
            </button>
          </div>
          {!hasSkills && (
            <p className="small muted" style={{ marginTop: 14 }}>
              Tip: uploading a CV on the Skills &amp; Roles page seeds your self-reported skill profile first.
            </p>
          )}
        </div>
        {activity && (
          <div className="activity-card card mt" style={{ marginTop: 18 }}>
            <div className="act-head">
              <h3 style={{ margin: 0 }}>My Learning Activity</h3>
              <span className="act-lb">
                Level {activity?.level ?? '–'}
                <span className="act-level-bar"><span style={{ width: `${xpPct}%` }} /></span>
                <span className="small muted">{activity ? `${activity.xp_into_level}/${activity.xp_per_level} XP` : ''}</span>
              </span>
            </div>
            <div className="act-grid">
              <div className="act-tile">
                <div className="act-ico coral"><IconFlame size={20} /></div>
                <div><strong>{activity?.streak_days ?? '–'}-day streak</strong><small className="muted">Keep a login streak going</small></div>
              </div>
              <div className="act-tile">
                <div className="act-ico amber"><IconBolt size={20} /></div>
                <div><strong>{activity?.xp ?? '–'} XP</strong><small className="muted">{activity?.active_days ?? 0} active days</small></div>
              </div>
              <div className="act-tile">
                <div className="act-ico green"><IconTrophy size={20} /></div>
                <div><strong>{activity?.verified_skills ?? 0} verified</strong><small className="muted">{activity?.assessments_taken ?? 0} assessments taken</small></div>
              </div>
            </div>
          </div>
        )}
        <JobsCard student={student} />
      </div>
    )
  }

  return (
    <div>
      <section className="dashboard-hero">
        <div className="dashboard-hero-copy">
          <p className="eyebrow">Career Readiness</p>
          <h1>{analysis.role_title}</h1>
          <p>
            SkillBridge compares your current evidence against the role requirements, then turns
            open gaps into learning and assessment actions.
          </p>
          <div className="dashboard-actions">
            <button className="btn btn-primary" onClick={() => go('learning')}>
              <IconArrowRight size={16} /> Continue learning
            </button>
            <button className="btn" onClick={() => go('assessments')}>
              <IconVerified size={16} /> Verify a skill
            </button>
          </div>
        </div>
        <ScoreRing value={analysis.match_score} />
      </section>

      <div className="insight-grid">
        <div className="insight-card">
          <span className="label">Verified Skills</span>
          <strong>{student.verified_skills.length}</strong>
          <small>Earned via passed assessments</small>
        </div>
        <div className="insight-card">
          <span className="label">Skill Gap Summary</span>
          <div className="gap-summary">
            <span><b>{strong}</b> strong</span>
            <span><b>{needsPractice}</b> gap</span>
            <span><b>{missingCount}</b> missing</span>
          </div>
        </div>
        <div className="insight-card">
          <span className="label">Recommended Next Step</span>
          <strong className="next-step-label">{nextStep(analysis)}</strong>
          <small>{gapCount === 0 ? 'Career ready' : `${gapCount} skill gap${gapCount === 1 ? '' : 's'} to close`}</small>
        </div>
      </div>

      <div className="grid grid-2">
        <div className="card">
          <h3>Skill Gap Map</h3>
          <p className="card-sub">{strong} covered · {gapCount} to improve — the single score above is the same number these rows add up to.</p>
          <div className="legend">
            <span className="item"><GapPill status="strong" /> Strong</span>
            <span className="item"><GapPill status="gap" /> Gap</span>
            <span className="item"><GapPill status="missing" /> Missing</span>
          </div>
          <div className="stack">
            {gaps.length === 0 ? (
              <div className="empty">Select a target role on the Skills &amp; Roles page to see your gap map.</div>
            ) : (
              gaps.map((g) => (
                <div className="skill-row" key={g.skill_id}>
                  <div>
                    <div className="sr-name">{g.skill_name}</div>
                    <div className="sr-cat">{g.category}</div>
                  </div>
                  <div className="sr-right">
                    {g.student_level ? <LevelBadge verified={g.verified} /> : null}
                    <GapPill status={g.status} />
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="card">
          <h3>My Skill Profile</h3>
          <p className="card-sub">One row per skill — verified status always reflects your best evidence.</p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {skillRows.map((s) => (
              <SkillTag key={`${s.name}-${s.verified}`} name={s.name} level={s.level} verified={s.verified} />
            ))}
            {skillRows.length === 0 && (
              <div className="stack" style={{ width: '100%', gap: 12 }}>
                <span className="muted small">Upload a CV to build your self-reported profile.</span>
                <button className="btn btn-sm" onClick={() => go('skills')}><IconArrowRight size={14} /> Go to Skills &amp; Roles</button>
              </div>
            )}
          </div>
          <div className="divider" />
          <div className="profile-share">
            <div className="share-head">
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontWeight: 600, fontSize: 13 }}>
                <IconShield size={14} style={{ color: 'var(--green)' }} /> Share verified skills
              </span>
              <label className="switch">
                <input
                  type="checkbox"
                  checked={shareOn}
                  onChange={(e) => toggleShare(e.target.checked)}
                  disabled={student.verified_skills.length === 0}
                />
                <span className="track" />
              </label>
            </div>
            <p className="small muted" style={{ margin: '6px 0 10px', lineHeight: 1.5 }}>
              {student.verified_skills.length === 0
                ? 'Pass an assessment first — only verified skills can be shared, never self-reported claims.'
                : shareOn
                  ? 'Anyone with the link can see your verified skills and their assessment-pass dates.'
                  : 'Your public profile is off. Turn it on to share proof of what you have verified.'}
            </p>
            {student.verified_skills.length > 0 && (
              <div className="share-row">
                <button className="btn btn-sm" onClick={() => copy('link', publicUrl)}>
                  {copied === 'link' ? <IconCheck size={14} /> : <IconExternal size={14} />}
                  {copied === 'link' ? 'Copied!' : 'Copy public link'}
                </button>
                {shareOn && (
                  <a className="btn btn-sm" href={publicUrl} target="_blank" rel="noopener noreferrer">
                    <IconExternal size={14} /> Open profile
                  </a>
                )}
              </div>
            )}
            {shareOn && (
              <div className="per-skill-share small muted" style={{ marginTop: 10 }}>
                Per-skill share:
                {student.verified_skills.map((v) => (
                  <button key={v.skill_id} className="chip-btn" onClick={() => copy(`skill-${v.skill_id}`, skillUrl(v.skill_id))}>
                    <span className="chip-share-dot" /> {v.name}
                    {copied === `skill-${v.skill_id}` ? ' ✓' : ''}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="activity-card card mt" style={{ marginTop: 18 }}>
        <div className="act-head">
          <h3 style={{ margin: 0 }}>My Learning Activity</h3>
          <span className="act-lb">
            Level {activity?.level ?? '–'}
            <span className="act-level-bar"><span style={{ width: `${xpPct}%` }} /></span>
            <span className="small muted">{activity ? `${activity.xp_into_level}/${activity.xp_per_level} XP` : ''}</span>
          </span>
        </div>
        <div className="act-grid">
          <div className="act-tile">
            <div className="act-ico coral"><IconFlame size={20} /></div>
            <div><strong>{activity?.streak_days ?? '–'}-day streak</strong><small className="muted">Keep a login streak going</small></div>
          </div>
          <div className="act-tile">
            <div className="act-ico amber"><IconBolt size={20} /></div>
            <div><strong>{activity?.xp ?? '–'} XP</strong><small className="muted">{activity?.active_days ?? 0} active days</small></div>
          </div>
          <div className="act-tile">
            <div className="act-ico green"><IconTrophy size={20} /></div>
            <div><strong>{activity?.verified_skills ?? 0} verified</strong><small className="muted">{activity?.assessments_taken ?? 0} assessments taken</small></div>
          </div>
        </div>
        <div className="act-badges">
          {(activity?.badges || []).filter((b) => b.earned).slice(0, 6).map((b) => (
            <span className="badge-chip earned" key={b.code} title={b.desc}>{b.name}</span>
          ))}
          {(activity?.badges || []).filter((b) => !b.earned).slice(0, 3).map((b) => (
            <span className="badge-chip locked" key={b.code} title={b.hint || b.desc}>{b.name}</span>
          ))}
        </div>
        <div className="act-note small muted">
          <IconLeaderboard size={13} /> {activity?.leaderboard?.message || 'Cohort leaderboard'}
        </div>
      </div>

      <JobsCard student={student} />
    </div>
  )
}

function CompanyDashboard() {
  const { me } = useApp()
  const [roles, setRoles] = useState<RoleRecord[]>([])
  const [candidates, setCandidates] = useState<Record<number, Candidate[]>>({})
  const [coverage, setCoverage] = useState<Record<number, RoleSkillCoverage>>({})

  useEffect(() => {
    api.roles()
      .then((res) => setRoles(res.roles))
      .catch((e) => { console.error('[dashboard] roles failed:', e) })
  }, [])

  useEffect(() => {
    roles.forEach((r) => {
      api.candidates(r.id)
        .then((c) => setCandidates((prev) => ({ ...prev, [r.id]: c })))
        .catch((e) => { console.error(`[dashboard] candidates for role ${r.id} failed:`, e) })
      api.roleSkillCoverage(r.id)
        .then((c) => setCoverage((prev) => ({ ...prev, [r.id]: c })))
        .catch((e) => { console.error(`[dashboard] coverage for role ${r.id} failed:`, e) })
    })
  }, [roles])

  const pool = Object.values(candidates).flat()
  const atLeast60 = pool.filter((c) => c.match_score >= 60).length

  return (
    <div>
      <div className="stats-grid">
        <div className="stat-card">
          <span className="label">Posted Roles</span>
          <strong>{roles.length || '–'}</strong>
          <small>Active openings</small>
        </div>
        <div className="stat-card">
          <span className="label">Candidate Pool</span>
          <strong>{pool.length}</strong>
          <small>{atLeast60} at ≥60% match</small>
        </div>
        <div className="stat-card">
          <span className="label">Verified Skills Earned</span>
          <strong>{pool.reduce((s, c) => s + c.verified_count, 0)}</strong>
          <small>Across matched candidates</small>
        </div>
      </div>
      <div className="card">
        <h3>Your roles &amp; matching candidates</h3>
        {roles.length === 0 && <div className="empty">Define a role on the Skills &amp; Roles page to start matching.</div>}
        {roles.map((r) => {
          const list = candidates[r.id] || []
          const cov = coverage[r.id]
          const weakest = (cov?.skills || []).filter((s) => s.coverage_pct < 100).sort((a, b) => a.coverage_pct - b.coverage_pct)
          return (
            <div className="role-card" key={r.id} style={{ marginBottom: 10 }}>
              <div className="rc-head">
                <div>
                  <div className="rc-title">{r.title}</div>
                  <div className="rc-company">{r.company_name}</div>
                </div>
                <span className="muted small" style={{ marginTop: 2 }}>
                  {list.length} candidate{list.length === 1 ? '' : 's'} matched
                </span>
              </div>
              {cov && (
                <div className="coverage-block">
                  <div className="coverage-head">
                    <span className="small muted">Applicant skill coverage</span>
                    <span className="small muted">{cov.candidate_count} candidate{cov.candidate_count === 1 ? '' : 's'} · {weakest.length} skill{weakest.length === 1 ? '' : 's'} short</span>
                  </div>
                  {cov.skills.map((s) => (
                    <div className="cov-row" key={s.skill_id}>
                      <div className="cov-label">{s.skill_name} <span className="lv">{s.required_level}</span></div>
                      <div className="cov-track">
                        <div className="cov-fill" style={{ width: `${s.coverage_pct}%`, background: s.coverage_pct >= 60 ? 'var(--green)' : s.coverage_pct >= 30 ? 'var(--amber)' : 'var(--red)' }} />
                      </div>
                      <div className="cov-pct">{Math.round(s.coverage_pct)}%</div>
                      <div className="cov-tally small muted">
                        {s.strong} strong · {s.gap} gap · {s.missing} missing
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {list.length > 0 && (
                <div className="cand-list">
                  {list.map((c) => (
                    <div className="cand" key={c.student_id}>
                      <div>
                        <div className="cand-name">{c.name}</div>
                        <div className="cand-mail">{c.university || 'Independent learner'}</div>
                      </div>
                      <div className="cand-right">
                        <span className="muted small">{c.verified_count} verified · {c.gap_count} gaps</span>
                        <ScoreInline value={c.match_score} />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ScoreInline({ value }: { value: number }) {
  return (
    <span className="score-chip" style={{ color: value >= 60 ? 'var(--green)' : value >= 40 ? 'var(--amber)' : 'var(--red)' }}>
      {Math.round(value)}%
    </span>
  )
}

function UniversityDashboard() {
  return (
    <div>
      <div className="stats-grid">
        <div className="stat-card">
          <span className="label">Students in Cohort</span>
          <strong>–</strong>
          <small>Aggregated across all programs</small>
        </div>
        <div className="stat-card">
          <span className="label">Average Match Score</span>
          <strong>–</strong>
          <small>vs. target roles</small>
        </div>
      </div>
      <div className="card">
        <h3>Cohort skill-gap overview</h3>
        <p className="card-sub">University admins see only anonymized, aggregated data.</p>
        <div className="empty">Select University Dashboard from the sidebar to load the full aggregated report.</div>
      </div>
    </div>
  )
}
