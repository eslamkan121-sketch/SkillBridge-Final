import React, { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { PublicProfile } from '../lib/types'
import { LevelBadge } from '../components/widgets'
import { IconVerified, IconShield, IconUniversity, IconCompany } from '../components/Icons'

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
  } catch {
    return iso || ''
  }
}

export default function PublicProfilePage({ studentId }: { studentId: number }) {
  const [profile, setProfile] = useState<PublicProfile | null>(null)
  const [state, setState] = useState<'loading' | 'missing' | 'ready'>('loading')

  useEffect(() => {
    setState('loading')
    api.publicProfile(studentId)
      .then((p) => { setProfile(p); setState('ready') })
      .catch((e) => { console.error('[public-profile] load failed:', e); setState('missing') })
  }, [studentId])

  useEffect(() => {
    if (state === 'ready') {
      const id = window.location.hash.replace(/^#/, '')
      const el = id ? document.getElementById(id) : null
      if (el) setTimeout(() => el.scrollIntoView({ behavior: 'smooth', block: 'center' }), 150)
    }
  }, [state])

  return (
    <div className="public-page">
      <div className="public-hero">
        <div className="brand-mark">S</div>
        <div>
          <div className="eyebrow">SkillBridge · Verified Skill Card</div>
          <h1>{state === 'ready' ? profile?.name : 'SkillBridge'}</h1>
        </div>
      </div>

      {state === 'loading' && <div className="card"><div className="loading">Loading verified skill card…</div></div>}
      {state === 'missing' && (
        <div className="card empty-card">
          <div className="confirm-icon"><IconShield size={26} /></div>
          <h3>No public skill card here</h3>
          <p className="muted">
            This student has not shared a verified skill card, or this link is out of date.
          </p>
          <a className="btn btn-primary" href="/">Back to SkillBridge</a>
        </div>
      )}
      {state === 'ready' && profile && (
        <>
          <div className="public-meta">
            {profile.university && <span><IconUniversity size={15} /> {profile.university}</span>}
            {profile.target_role && (
              <span>
                <IconCompany size={15} /> Target: {profile.target_role.title}
                {profile.target_role.company ? ` at ${profile.target_role.company}` : ''}
              </span>
            )}
          </div>

          <div className="public-skill-card card">
            <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <IconVerified size={18} style={{ color: 'var(--green)' }} /> Verified skills
            </h3>
            <p className="card-sub">
              Every skill below was earned by passing a SkillBridge assessment — this card carries evidence, never self-reported claims.
            </p>
            {profile.verified_skills.length === 0 && (
              <div className="empty">No verified skills yet — the card is live but still empty.</div>
            )}
            <div className="public-list">
              {profile.verified_skills.map((s) => (
                <div className="prow" id={`skill-${s.skill_id}`} key={s.skill_id}>
                  <div className="prow-left">
                    <div className="prow-name">{s.name}</div>
                    {s.category && <div className="prow-cat">{s.category}</div>}
                  </div>
                  <div className="prow-right">
                    <LevelBadge verified />
                    {s.verified_at && <div className="prow-date">{fmtDate(s.verified_at)}</div>}
                  </div>
                </div>
              ))}
            </div>
            <div className="divider" />
            <div className="p-foot">
              <IconShield size={13} style={{ color: 'var(--coral)' }} />
              <span>Issued by SkillBridge · verified through the assessment loop · contact the student to learn more.</span>
            </div>
          </div>

          <div className="public-footer">
            <a className="muted small" href="/">Sign in to SkillBridge to create or manage your own skill card</a>
          </div>
        </>
      )}
    </div>
  )
}