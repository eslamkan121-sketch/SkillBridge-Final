import React, { useEffect, useState } from 'react'
import { useApp } from '../AppContext'
import { api } from '../lib/api'
import { JOB_STAGES } from '../lib/types'
import type { Student, TrackedJob, TrackerResponse, JobStage } from '../lib/types'
import { IconBookmark, IconTrash, IconLock, IconShield, IconBolt } from './Icons'

const STAGE_LABEL: Record<JobStage, string> = {
  saved: 'Saved',
  preparing: 'Preparing',
  applied: 'Applied',
  screening: 'Screening',
  interview: 'Interview',
  offer: 'Offer',
  hired: 'Hired',
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
  archived_or_expired: 'Archived / expired',
}

const ACTIVE: JobStage[] = ['saved', 'preparing', 'applied', 'screening', 'interview', 'offer']
const DONE: JobStage[] = ['hired', 'rejected', 'withdrawn']

function stageTone(stage: JobStage): string {
  if (stage === 'saved') return 'tracked-saved'
  if (stage === 'hired') return 'tracked-hired'
  if (stage === 'rejected' || stage === 'withdrawn') return 'tracked-down'
  if (stage === 'archived_or_expired') return 'tracked-arch'
  return 'tracked-active'
}

function groupItems(items: TrackedJob[]): Record<'active' | 'done' | 'archived', TrackedJob[]> {
  const out: Record<'active' | 'done' | 'archived', TrackedJob[]> = { active: [], done: [], archived: [] }
  for (const it of items) {
    if (it.stage === 'archived_or_expired') out.archived.push(it)
    else if (ACTIVE.includes(it.stage)) out.active.push(it)
    else if (DONE.includes(it.stage)) out.done.push(it)
  }
  return out
}

export default function JobTrackerPanel({ student, refreshKey }: { student?: Student; refreshKey?: number }) {
  const { applyCopilot, startInterview, setMode } = useApp()
  const [data, setData] = useState<TrackerResponse | null>(null)
  const [err, setErr] = useState('')
  const [drafts, setDrafts] = useState<Record<number, { note: string; interview_date: string; application_deadline: string }>>({})
  const [busy, setBusy] = useState<number | null>(null)
  const [rowErr, setRowErr] = useState<Record<number, string>>({})
  const [deleting, setDeleting] = useState<number | null>(null)

  const reload = (sid: number) => {
    api.jobTracker(sid)
      .then(setData)
      .catch((e) => setErr(e.message || String(e)))
  }

  useEffect(() => {
    if (!student) return
    reload(student.id)
  }, [student?.id, refreshKey])

  if (!student) return null

  const patch = async (trackerId: number, update: Partial<Pick<TrackedJob, 'stage' | 'note' | 'interview_date' | 'application_deadline'>>) => {
    setBusy(trackerId)
    setRowErr((r) => ({ ...r, [trackerId]: '' }))
    try {
      await api.updateTrackerItem(student.id, trackerId, update)
      reload(student.id)
    } catch (e: any) {
      setRowErr((r) => ({ ...r, [trackerId]: e.message || String(e) }))
    } finally {
      setBusy(null)
    }
  }

  const archive = async (trackerId: number) => {
    await patch(trackerId, { stage: 'archived_or_expired' })
  }

  const remove = async (trackerId: number) => {
    if (!window.confirm('This job is still just saved. Remove it from your tracker?')) return
    setDeleting(trackerId)
    setRowErr((r) => ({ ...r, [trackerId]: '' }))
    try {
      await api.deleteTrackerItem(student.id, trackerId)
      reload(student.id)
    } catch (e: any) {
      setRowErr((r) => ({ ...r, [trackerId]: e.message || String(e) }))
    } finally {
      setDeleting(null)
    }
  }

  // Phase Q (D5): interview-stage rows bridge to the EXISTING Mock Interview
  // session (practice only — never auto-starts a real process, never sends
  // data outside the app). Reuses AppContext.startInterview; mode goes to the
  // live session 'interview' state, never a persisted preference.
  const interviewPrep = async (it: TrackedJob) => {
    setRowErr((r) => ({ ...r, [it.id]: '' }))
    try {
      applyCopilot({ page: 'mock_interview', skillId: null, competency: null, jobTitle: it.title, jobUrl: it.apply_url || it.url || null })
      setMode('interview')
      await startInterview(null)
    } catch (e: any) {
      setRowErr((r) => ({ ...r, [it.id]: e.message || String(e) }))
    }
  }

  const groups = groupItems(data?.items || [])

  const renderItem = (it: TrackedJob) => {
    const draft = drafts[it.id] || { note: it.note, interview_date: it.interview_date || '', application_deadline: it.application_deadline || '' }
    const dirty = draft.note !== it.note || draft.interview_date !== (it.interview_date || '') || draft.application_deadline !== (it.application_deadline || '')
    const busyRow = busy === it.id || deleting === it.id
    return (
      <div className="tracked-item" key={it.id}>
        <div className="tracked-head">
          <div className={`tracked-badge ${stageTone(it.stage)}`}>
            {STAGE_LABEL[it.stage]}
          </div>
          <div className="tracked-title">
            <span className="resource-title">{it.title}</span>
            <span className="resource-meta">
              {it.company}
              {it.is_expired ? ' · Expired listing' : ''}
              {it.listing_status === 'link-unavailable' ? ' · Link unavailable' : ''}
              {it.location ? ` · ${it.location}` : ''}
              {it.match_pct != null ? ` · ${Math.round(it.match_pct)}% match` : ''}
            </span>
          </div>
          <label className="tracked-stage">
            Stage
            <select
              value={it.stage}
              disabled={busyRow}
              aria-label={`Move ${it.title} to a different stage`}
              onChange={(e) => patch(it.id, { stage: e.target.value as JobStage })}
            >
              {JOB_STAGES.map((s) => (
                <option key={s} value={s}>{STAGE_LABEL[s]}</option>
              ))}
            </select>
          </label>
        </div>

        <div className="tracked-form">
          <label className="tracked-note">
            Private note
            <textarea
              rows={2}
              value={draft.note}
              placeholder="Notes are private to you (interviews, links, contact…)"
              onChange={(e) => setDrafts((d) => ({ ...d, [it.id]: { ...draft, note: e.target.value } }))}
            />
          </label>
          <label className="tracked-date">
            Interview date
            <input
              type="date"
              value={draft.interview_date}
              onChange={(e) => setDrafts((d) => ({ ...d, [it.id]: { ...draft, interview_date: e.target.value } }))}
            />
          </label>
          <label className="tracked-date">
            Application deadline
            <input
              type="date"
              value={draft.application_deadline}
              onChange={(e) => setDrafts((d) => ({ ...d, [it.id]: { ...draft, application_deadline: e.target.value } }))}
            />
          </label>
          <div className="tracked-actions">
            <button
              type="button"
              className="btn btn-sm"
              disabled={busyRow || !dirty}
              onClick={() => patch(it.id, {
                note: draft.note,
                interview_date: draft.interview_date || it.interview_date,
                application_deadline: draft.application_deadline || it.application_deadline,
              })}
            >
              Save details
            </button>
            {it.stage !== 'archived_or_expired' ? (
              <button
              type="button"
              className="btn btn-sm btn-ghost"
              disabled={busyRow}
              onClick={() => archive(it.id)}
            >
              Archive
            </button>
            ) : null}
            {it.stage === 'interview' ? (
              <button
                type="button"
                className="btn btn-sm jt-prep"
                disabled={busyRow}
                onClick={() => void interviewPrep(it)}
              >
                <IconBolt size={13} /> Prepare with a mock interview
              </button>
            ) : null}
            {it.stage === 'saved' ? (
              <button
                type="button"
                className="btn btn-sm btn-danger-ghost"
                disabled={busyRow}
                onClick={() => remove(it.id)}
              >
                <IconTrash size={13} /> Remove saved
              </button>
            ) : null}
            {/* Phase Q (D6): shareable-evidence chip — only links the student's
                OWN public profile when sharing is enabled; never auto-publishes. */}
            {!!student?.share_public && student.verified_skills.length > 0 && (
              <a
                className="btn btn-sm jt-share"
                href={`${window.location.origin}/p/${student.id}`}
                target="_blank"
                rel="noopener noreferrer"
                title="Only verified skills are shown on your public profile — never self-reported claims."
              >
                <IconShield size={13} /> Share your verified profile
              </a>
            )}
          </div>
        </div>

        {rowErr[it.id] ? <div className="error small" style={{ marginTop: 6 }}>{rowErr[it.id]}</div> : null}

        {it.history.length > 0 ? (
          <details className="tracked-history">
            <summary>History ({it.history.length})</summary>
            <ul>
              {it.history.map((h) => (
                <li key={h.id}>
                  <span className="tracked-h-stage">{STAGE_LABEL[h.stage]}</span>
                  {h.changed_from ? ` (from ${STAGE_LABEL[h.changed_from]})` : ''}
                  {h.note ? ` — ${h.note}` : ''}
                  <span className="muted"> · {h.created_at}</span>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>
    )
  }

  return (
    <div className="card mt tracked-panel">
      <div className="flex between" style={{ flexWrap: 'wrap', gap: 8 }}>
        <h3 style={{ margin: 0 }}>Applications tracker</h3>
        <span className="small muted tracked-privacy">
          <IconLock size={13} /> Private to you — companies and universities never see this
        </span>
      </div>
      <p className="card-sub" style={{ marginTop: 4 }}>
        Move saved roles through your real application process and keep private notes. Nothing here is shared, emailed, or synced anywhere.
      </p>

      {err && <div className="error" style={{ marginBottom: 10 }}>{err}</div>}

      {!data ? (
        <div className="stack" role="status" aria-label="Loading your application tracker">
          {Array.from({ length: 2 }).map((_, i) => (
            <div className="skeleton" key={i} style={{ height: 44, borderRadius: 10 }} />
          ))}
        </div>
      ) : data.items.length === 0 ? (
        <div className="empty tracked-empty">
          <IconBookmark size={20} />
          <span>No saved roles yet — hit <strong>Save</strong> on a role row above (Recent roles for you) to start tracking applications.</span>
        </div>
      ) : (
        <div className="stack">
          {groups.archived.length > 0 && (
            <div className="tracked-group">
              <div className="tracked-group-label">Archived / expired ({groups.archived.length})</div>
              {groups.archived.map(renderItem)}
            </div>
          )}
          {groups.done.length > 0 && (
            <div className="tracked-group">
              <div className="tracked-group-label">Closed ({groups.done.length})</div>
              {groups.done.map(renderItem)}
            </div>
          )}
          {groups.active.length > 0 && (
            <div className="tracked-group">
              <div className="tracked-group-label">Active ({groups.active.length})</div>
              {groups.active.map(renderItem)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}