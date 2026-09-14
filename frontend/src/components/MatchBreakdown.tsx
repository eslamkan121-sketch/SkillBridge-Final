// Phase J — explainable match breakdown disclosure.
//
// Pure presentational component: it renders the backend's breakdown payload
// inside a native <details>/<summary> (keyboard + aria-expanded for free). It
// NEVER recomputes the score and never fetches anything — the owner page passes
// `onRequest`, which is called once the first time the disclosure is opened,
// so the displayed number and every line shown come from the backend verbatim.
import { useRef, useState } from 'react'
import type {
  JobMatchBreakdown,
  MatchBreakdownPayload,
  RoleMatchBreakdown,
  TargetRoleMatchBreakdown,
} from '../lib/types'
import { humanizeTopicLabel } from '../lib/topicLabels'

export type MatchBreakdownKind = 'target-role' | 'role' | 'job'

interface MatchBreakdownProps {
  kind: MatchBreakdownKind
  pct: number
  onRequest: () => Promise<MatchBreakdownPayload> | MatchBreakdownPayload
}

interface LineProps {
  label: string
  points: number
  final?: boolean
}

function Pts({ label, points, final }: LineProps) {
  return (
    <div className={`mxb-pt ${final ? 'final' : ''}`}>
      <span className="mxb-pt-label">{label}</span>
      <span className="mxb-pt-num">{points > 0 ? `+${points}` : points}</span>
    </div>
  )
}

function EvidenceBadge({ value }: { value: string }) {
  const cls = value === 'verified' ? 'ev verified' : value === 'self_reported' ? 'ev self' : 'ev none'
  return <span className={`mxb-ev ${cls}`}>{value}</span>
}

function TargetRoleView({ data }: { data: TargetRoleMatchBreakdown }) {
  return (
    <>
      <table className="mxb-table">
        <thead>
          <tr>
            <th scope="col">Required skill</th>
            <th scope="col">Required</th>
            <th scope="col">Your level</th>
            <th scope="col">Evidence</th>
            <th scope="col" className="num">Points</th>
          </tr>
        </thead>
        <tbody>
          {data.requirements.map((r, i) => (
            <tr key={r.skill_id || i}>
              <td>{humanizeTopicLabel(r.skill_name)}</td>
              <td>{r.required_level || '—'}</td>
              <td>{r.student_level || '—'}</td>
              <td><EvidenceBadge value={r.evidence} /></td>
              <td className="num">{r.contribution_points}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mxb-lines">
        <Pts label="Possible points" points={data.total_points} />
        <Pts label="Raw percent" points={data.raw_percent} />
        {data.adjustment_lines.map((l) => (
          <Pts key={`${l.label}-${l.points}`} label={l.label_long || l.label} points={l.points} />
        ))}
        <Pts label="Displayed match" points={data.displayed_percent} final />
      </div>
      {data.missing_data.length > 0 && (
        <p className="mxb-note">Missing skills: {data.missing_data.map((m) => humanizeTopicLabel(m)).join(', ')}.</p>
      )}
      <p className="mxb-next">{data.next_action}</p>
    </>
  )
}

function RoleView({ data }: { data: RoleMatchBreakdown }) {
  return (
    <>
      <table className="mxb-table">
        <thead>
          <tr>
            <th scope="col">Skill</th>
            <th scope="col">Required</th>
            <th scope="col">Your level</th>
            <th scope="col">Evidence</th>
            <th scope="col" className="num">Weight</th>
            <th scope="col" className="num">Credit</th>
          </tr>
        </thead>
        <tbody>
          {data.requirements.map((r, i) => (
            <tr key={`${r.name}-${i}`}>
              <td>
{humanizeTopicLabel(r.name)}
                {r.is_discovery && <span className="mxb-disc">discovery</span>}
              </td>
              <td>{r.essential ? (r.required_level || 'required') : 'optional'}</td>
              <td>{r.student_level || '—'}</td>
              <td><EvidenceBadge value={r.evidence} /></td>
              <td className="num">{r.weight}</td>
              <td className="num">{r.credit}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mxb-lines">
        <Pts label="Required-skill weight" points={data.total_weight} />
        <Pts label="Earned credit" points={data.earned_weight} />
        <Pts label="Raw percent" points={data.raw_percent} />
        {data.adjustment_lines.map((l) => (
          <Pts key={`${l.label}-${l.points}`} label={l.label_long || l.label} points={l.points} />
        ))}
        <Pts label="Displayed match" points={data.displayed_percent} final />
      </div>
      {data.verified_matches.length > 0 && (
        <p className="mxb-note">Verified matches: {data.verified_matches.map((m) => humanizeTopicLabel(m)).join(', ')}.</p>
      )}
      {data.missing_key_skills.length > 0 && (
        <p className="mxb-note">Skill gap: {data.missing_key_skills.map((m) => humanizeTopicLabel(m)).join(' · ')}</p>
      )}
      <p className="mxb-next">{data.next_action}</p>
    </>
  )
}

function JobView({ data }: { data: JobMatchBreakdown }) {
  const c = data.components
  const loc = data.constraints.location
  const wt = data.constraints.work_type
  const se = data.constraints.seniority
  return (
    <>
      <div className="mxb-comp">
        <div><span className="label">Relevance</span><strong>{c.relevance.final}</strong>
          <small>base {c.relevance.base_points}{c.relevance.family_bonus ? ` · family +${c.relevance.family_bonus}` : ''}{c.relevance.minor_bonus ? ` · minor +${c.relevance.minor_bonus}` : ''}{c.relevance.verified_bonus ? ` · verified +${c.relevance.verified_bonus}` : ''}{c.relevance.fresh_bonus ? ` · fresh +${c.relevance.fresh_bonus}` : ''}</small>
        </div>
        <div><span className="label">Experience</span><strong>{c.experience.points}</strong>
          <small>{c.experience.label}</small>
        </div>
        <div><span className="label">Location</span><strong>{c.location.points}</strong>
          <small>{c.location.label}</small>
        </div>
      </div>
      <div className="mxb-lines">
        {data.lines.map((l) => (
          <Pts key={`${l.label}-${l.points}`} label={l.label_long || l.label} points={l.points} />
        ))}
        <Pts label="Displayed match" points={data.displayed_percent} final />
      </div>
      <div className="mxb-constraints">
        <span className={`mxb-chip ${loc.supported ? '' : 'unsupported'}`}>Location: {loc.label}</span>
        <span className={`mxb-chip ${wt.supported ? '' : 'unsupported'}`}>Work type: {wt.value}</span>
        <span className={`mxb-chip ${se.supported ? '' : 'unsupported'}`}>
          Seniority: job {se.job} vs you {se.student}
        </span>
      </div>
      {data.verified_skill_hits.length > 0 && (
        <p className="mxb-note">Verified skill hits: {data.verified_skill_hits.map((m) => humanizeTopicLabel(m)).join(', ')}.</p>
      )}
      <p className="mxb-note">{data.evidence_note}</p>
      <p className="mxb-next">{data.next_action}</p>
    </>
  )
}

export default function MatchBreakdown({ kind, pct, onRequest }: MatchBreakdownProps) {
  const [data, setData] = useState<MatchBreakdownPayload | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fired = useRef(false)

  const askSummary = pct >= 40 ? 'How is this score built?' : 'Why this score?'

  const open = () => {
    if (fired.current || loading) return
    fired.current = true
    setLoading(true)
    setError(null)
    Promise.resolve(onRequest())
      .then(setData)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }

  return (
    <details className="mxb" aria-label={`Match breakdown for ${pct}%`}>
      <summary onClick={open}>
        {loading && !data ? 'Loading…' : askSummary}
      </summary>
      <div className="mxb-body">
        {data && (
          <p className="mxb-meta">
            {data.formula} · {data.version} · data {data.role_data_version} · {new Date(data.as_of).toLocaleString()}
          </p>
        )}
        {error && <div className="error mxb-err">Could not explain this match: {error}</div>}
        {!data && !error && loading && <div className="mxb-loading">Building the exact breakdown…</div>}
        {data && kind === 'target-role' && <TargetRoleView data={data as TargetRoleMatchBreakdown} />}
        {data && kind === 'role' && <RoleView data={data as RoleMatchBreakdown} />}
        {data && kind === 'job' && <JobView data={data as JobMatchBreakdown} />}
      </div>
    </details>
  )
}