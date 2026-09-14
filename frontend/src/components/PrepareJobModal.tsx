import React, { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { JobPreparePayload, RecentJob, Student } from '../lib/types'
import { IconExternal, IconShield, IconArrowRight } from './Icons'

// Phase Q (D4) — grounded "Prepare for this job" dialog. Reads the CURRENT
// feed row through the backend prepare endpoint (peek_feed_job, cache-only),
// renders per-skill evidence from that payload ONLY, and deep-links a skill
// ONLY when it resolves to a real DB skill_id. Never fabricates a skill, a
// skill_id, or a readiness number.

const STATUS_LABEL: Record<string, string> = {
  verified: 'Verified',
  self_reported: 'Self-reported',
  gap: 'Learning path',
  no_path: 'No path yet',
}

function prepareLinkStatus(status: string): string {
  if (status === 'verified') return 'Review in Learning'
  if (status === 'self_reported') return 'Verify'
  if (status === 'gap') return 'Practice'
  return ''
}

export default function PrepareJobModal({ student, job, onClose, onNavigate }: {
  student: Student
  job: RecentJob
  onClose: () => void
  onNavigate?: (section: string, focus?: { skillId: number; roleTitle: string }) => void
}) {
  const [data, setData] = useState<JobPreparePayload | null>(null)
  const [err, setErr] = useState('')
  const fired = useRef(false)
  const dialogRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (fired.current || !student.id || !job.fingerprint) return
    fired.current = true
    const s = student as any
    api.prepareJob(student.id, job.fingerprint, {
      location: s?.location || '',
      country: s?.country || '',
    })
      .then(setData)
      .catch((e: any) => setErr(e.message || String(e)))
  }, [student.id, job.fingerprint])

  useEffect(() => {
    dialogRef.current?.focus()
  }, [])

  const go = (section: string, skillId: number | null) => {
    onNavigate?.(section, skillId != null ? { skillId, roleTitle: job.title || '' } : undefined)
  }

  const pjob = data?.job
  const applyLink = pjob && pjob.apply_url &&
    pjob.listing_status !== 'expired' && pjob.listing_status !== 'link-unavailable'
      ? pjob.apply_url
      : null

  return (
    <div className="jprep-backdrop" onMouseDown={onClose}>
      <div
        ref={dialogRef}
        className="jprep-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`Prepare for ${job.title}`}
        tabIndex={-1}
        onKeyDown={(e) => { if (e.key === 'Escape') onClose() }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="jprep-head">
          <div>
            <h3 style={{ margin: 0 }}>Prepare for this role</h3>
            <div className="jprep-job-title">{pjob?.title || job.title}</div>
            <div className="jprep-job-meta">
              {pjob?.company || job.company}
              {(pjob?.location_label || job.location_label || job.location) ? ` · ${pjob?.location_label || job.location_label || job.location}` : ''}
              {pjob?.match_pct != null ? ` · ${Math.round(pjob.match_pct)}% match` : ''}
              {pjob?.provider ? ` · ${pjob.provider}` : ''}
              {pjob?.listing_status ? ` · ${pjob.listing_status}` : ''}
            </div>
          </div>
          <button type="button" className="btn btn-sm btn-secondary" autoFocus onClick={onClose}>Close</button>
        </div>

        <p className="card-sub jprep-sub">
          Skill-by-skill readiness for this opening, straight from the job feed row you are looking at.
          Deep links open real SkillBridge learning or verification — never a fabricated path.
        </p>

        {!data && !err && (
          <div className="stack" role="status" aria-label="Loading readiness skills for this job">
            {Array.from({ length: 3 }).map((_, i) => (
              <div className="skeleton" key={i} style={{ height: 44, borderRadius: 10 }} />
            ))}
          </div>
        )}
        {err && <div className="error" style={{ marginBottom: 10 }}>{err}</div>}

        {data && (
          <ul className="jprep-skills">
            {data.skills.length === 0 ? (
              <li className="jprep-empty">This opening lists no required skills — nothing is invented to fill the list.</li>
            ) : data.skills.map((s) => (
              <li className="jprep-skill" key={s.name}>
                <div className="jprep-skill-main">
                  <span className="jprep-skill-name">{s.name}</span>
                  <span className={`jprep-badge ${s.status}`}>{STATUS_LABEL[s.status] || s.status}</span>
                  {s.verified_at ? <span className="jprep-verified-at">Verified {s.verified_at.split('T')[0]}</span> : null}
                </div>
                <div className="jprep-skill-actions">
                  {s.status === 'no_path' ? (
                    <>
                      <span className="jprep-nopath">No SkillBridge path for this exact skill yet.</span>
                      <button type="button" className="btn btn-sm btn-secondary" onClick={() => go('skills', null)}>
                        Explore the skills hub <IconArrowRight size={12} />
                      </button>
                    </>
                  ) : s.skill_id != null ? (
                    <button type="button" className="btn btn-sm" onClick={() => go(s.status === 'verified' ? 'learning' : s.status === 'self_reported' ? 'assessments' : 'scenarios', s.skill_id)}>
                      {prepareLinkStatus(s.status)} <IconArrowRight size={12} />
                    </button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}

        <div className="jprep-foot">
          {applyLink ? (
            <a className="btn btn-primary" href={applyLink} target="_blank" rel="noopener noreferrer">
              Apply on this listing <IconExternal size={14} />
            </a>
          ) : (
            <span className="small muted">
              {pjob?.listing_status === 'link-unavailable' ? 'This listing link is unavailable right now.'
                : 'This listing is not live — application happens on the employer page.'}
            </span>
          )}
          {!!student.share_public && student.verified_skills.length > 0 && (
            <a
              className="jprep-share"
              href={`${window.location.origin}/p/${student.id}`}
              target="_blank"
              rel="noopener noreferrer"
            >
              <IconShield size={13} /> Share your verified-skill profile
            </a>
          )}
        </div>
      </div>
    </div>
  )
}