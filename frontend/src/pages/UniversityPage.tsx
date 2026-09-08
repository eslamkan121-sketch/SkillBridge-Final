import React, { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useApp } from '../AppContext'
import type { UniversityStatsResponse, CohortResponse } from '../lib/types'
import { IconUniversity, IconAlert, IconCheck, IconVerified, IconShield } from '../components/Icons'

export default function UniversityPage() {
  const { me } = useApp()
  const [data, setData] = useState<UniversityStatsResponse | null>(null)
  const [cohort, setCohort] = useState<CohortResponse | null>(null)
  const [error, setError] = useState('')
  const [confirming, setConfirming] = useState(false)

  const load = () => {
    api.universityStats().then(setData).catch((e) => setError(e.message))
    api.universityCohort().then(setCohort).catch((e) => { console.error('[university] cohort failed:', e); setError((p) => p || (e.message || 'Failed to load cohort')) })
  }
  useEffect(load, [])

  const confirm = async () => {
    setConfirming(true)
    try {
      const r = await api.universityConfirm()
      setCohort(r)
      load()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setConfirming(false)
    }
  }

  if (error) return <div className="card"><div className="error">{error}</div></div>
  if (!data || !cohort) return <div className="card"><div className="loading">Loading aggregated statistics…</div></div>

  const rule = data.rule
  const ruleSatisfied = rule?.satisfied
  const institution = me?.university || ''

  return (
    <div>
      {institution && (
        <div className="institution-banner">
          <IconUniversity size={16} />
          <span><strong>{institution}</strong>{me?.country ? ` · ${me.country}` : ''}</span>
        </div>
      )}
      <div className={`rule-banner ${ruleSatisfied ? '' : 'blocking'}`}>
        <IconAlert size={17} style={{ color: ruleSatisfied ? 'var(--coral)' : 'var(--amber)' }} />
        <div>
          <strong>Privacy &amp; minimum-cohort rule.</strong> University admins see only anonymized,
          aggregated statistics — there is no path to an individual student's data. Statistics are
          only computed once at least <strong>{rule?.min_cohort_size} students</strong> have consented
          to join the cohort. Consented now: {rule?.confirmed_count ?? cohort.confirmed_count} of {rule?.student_count ?? cohort.student_count}.
        </div>
      </div>

      {!ruleSatisfied ? (
        <div className="card confirm-card">
          <div className="confirm-icon"><IconUniversity size={26} /></div>
          <h3>Cohort consent not yet reached</h3>
          <p>
            SkillBridge aggregates skill-gap statistics across each student cohort. To keep every
            number trustworthy and anonymous, at least <strong>{rule?.min_cohort_size} students</strong> must
            have consented before the dashboard unlocks.
          </p>
          <p className="muted small">
            {cohort.confirmed_count} of {cohort.student_count} students have consented&nbsp;·
            &nbsp;<code>MIN_COHORT_SIZE = {rule?.min_cohort_size}</code> — this rule is enforced in the backend
            endpoint, not just hidden in the UI.
          </p>
          <button className="btn btn-primary" onClick={confirm} disabled={confirming}>
            <IconCheck size={15} /> {confirming ? 'Confirming…' : 'Consent the cohort — unlock stats'}
          </button>
        </div>
      ) : (
        <div>
          <div className="stats-grid">
            <div className="stat-card">
              <span className="label">Students in Cohort</span>
              <strong>{data.student_count ?? rule?.student_count ?? '–'}</strong>
              <small>{data.with_target_role ?? 0} with a target role</small>
            </div>
            <div className="stat-card">
              <span className="label">Average Match Score</span>
              <strong>{data.average_match_score != null ? Math.round(data.average_match_score) : '–'}%</strong>
              <small>Across the cohort</small>
            </div>
            <div className="stat-card">
              <span className="label">Verified Skills Earned</span>
              <strong>{data.verified_skills_total ?? 0}</strong>
              <small>{data.assessments_total ?? 0} assessment attempts logged</small>
            </div>
          </div>

          <div className="card">
            <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <IconUniversity size={18} /> Recommended skill gaps across the cohort
            </h3>
            <p className="card-sub">Share of students in each bucket for every required skill (percent of cohort).</p>
            <div className="u-legend">
              <span className="u-leg"><span className="seg-strong" /> Strong</span>
              <span className="u-leg"><span className="seg-gap" /> Gap</span>
              <span className="u-leg"><span className="seg-missing" /> Missing</span>
              <span className="u-leg pushed"><span className="u-need" /> % need improvement</span>
            </div>
            <div className="u-bars">
              {(data.skill_stats || []).map((s) => {
                const total = Math.max(1, s.strong + s.gap + s.missing)
                return (
                  <div className="u-bar-row" key={s.skill_name}>
                    <div className="u-bar-label">
                      <div className="u-bar-name">{s.skill_name}</div>
                      <div className="u-bar-cat">{s.category}</div>
                    </div>
                    <div className="u-bar-track">
                      <div className="u-bar-seg seg-strong" style={{ width: `${(s.strong / total) * 100}%` }} title={`Strong: ${s.strong}`} />
                      <div className="u-bar-seg seg-gap" style={{ width: `${(s.gap / total) * 100}%` }} title={`Gap: ${s.gap}`} />
                      <div className="u-bar-seg seg-missing" style={{ width: `${(s.missing / total) * 100}%` }} title={`Missing: ${s.missing}`} />
                    </div>
                    <div className={`u-bar-need ${s.need_improvement_pct >= 60 ? 'high' : s.need_improvement_pct >= 40 ? 'med' : ''}`}>
                      {s.need_improvement_pct}%
                    </div>
                  </div>
                )
              })}
            </div>
            <div className="divider" />
            <div className="flex" style={{ gap: 18, color: 'var(--slate-500)', fontSize: 12.5, flexWrap: 'wrap' }}>
              <span><IconVerified size={14} style={{ color: 'var(--green)' }} /> Verified skills are counted from passed assessments only.</span>
              <span><IconShield size={14} style={{ color: 'var(--coral)' }} /> No individual student records are revealed at any point.</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}