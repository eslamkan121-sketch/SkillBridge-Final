import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useApp } from '../AppContext'
import { api } from '../lib/api'
import { RELOCATION_MARKETS, marketLabel } from '../lib/markets'
import type { RoleRecord, Student, Skill, RolesResponse, EscoOccupation, Analysis, RoleRecommendation, RoleRecommendationsResponse, SavedRolesResponse } from '../lib/types'
import { IconPlus, IconEdit, IconTrash, IconUpload, IconSearch, IconCheck, IconTarget, IconBookmark } from '../components/Icons'
import { SkillTag, GapPill } from '../components/widgets'
import { IconRoles } from '../components/Icons'
import { ConfirmModal, ToastRegion, useToast } from '../components/ui'

const LEVELS = ['Beginner', 'Intermediate', 'Advanced']

// Generic transferable skills make terrible ESCO search seeds ("Time
// Management" surfaces nothing career-specific). The live-role search must seed
// from a distinctive, domain-bearing skill from the CV instead.
const GENERIC_SKILLS = new Set([
  'communication', 'teamwork', 'leadership', 'problem solving', 'critical thinking',
  'time management', 'adaptability', 'creativity', 'organisation', 'organization',
  'interpersonal skills', 'attention to detail', 'flexibility', 'collaboration',
  'project management', 'research', 'writing',
])

function mergeRoles(roles: RoleRecord[], catalog: RoleRecord[]): RoleRecord[] {
  const byId = new Map<number, RoleRecord>()
  for (const r of [...roles, ...catalog]) if (!byId.has(r.id)) byId.set(r.id, r)
  return [...byId.values()]
}

// Pick the most *discriminative* profile skill as the live-role search seed,
// mirroring `recommendations._informative_skills`: a skill is a good seed when
// it is rare across the local role+catalog pool (IDF-like specificity), which
// filters the generic soft-skills out without a brittle "list the generics"
// ladder. Falls back to the target role / first skill only when the profile
// has no domain-bearing skill at all.
function pickSeedSkill(profile: { name: string }[], roles: RoleRecord[], catalog: RoleRecord[]): string {
  const candidates = (profile || [])
    .map((s) => s.name.trim())
    .filter((n) => n && !GENERIC_SKILLS.has(n.toLowerCase()))
  if (candidates.length === 0) return ''
  const pool = [...roles, ...catalog]
  const corpus = Math.max(pool.length, 1)
  const df = new Map<string, number>()
  for (const r of pool) {
    for (const s of r.required_skills) {
      const k = s.name.toLowerCase().trim()
      df.set(k, (df.get(k) ?? 0) + 1)
    }
  }
  const specificity = (name: string) => Math.log(1 + corpus / (1 + (df.get(name.toLowerCase()) ?? 0)))
  let best = candidates[0]
  for (const c of candidates) if (specificity(c) > specificity(best)) best = c
  return best.slice(0, 80)
}

export default function SkillsRolesPage({ onNavigate }: { onNavigate?: Navigate }) {
  const { me, applyCopilot } = useApp()
  useEffect(() => {
    applyCopilot({ page: 'skills_roles', skillId: null, competency: null, jobTitle: null, jobUrl: null })
  }, [])
  if (!me) return null
  if (me.entity_type === 'student') return <StudentBrowse student={me.student} analysis={me.analysis ?? undefined} onNavigate={onNavigate} />
  if (me.entity_type === 'company') return <CompanyRoles company={me.company} />
  return <ReadOnlyBrowse />
}

function useRoles() {
  const [roles, setRoles] = useState<RoleRecord[]>([])
  const [catalog, setCatalog] = useState<RoleRecord[]>([])
  const [skills, setSkills] = useState<Skill[]>([])
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState('')
  useEffect(() => {
    Promise.all([api.roles(), api.skills()])
      .then(([res, skillsRes]: [RolesResponse, Skill[]]) => {
        setRoles(res.roles || [])
        setCatalog(res.catalog || [])
        setSkills(skillsRes || [])
        setLoaded(true)
      })
      .catch((e) => { console.error('[roles] load failed:', e); setLoadError(e.message || String(e)) })
  }, [])
  return { roles, setRoles, catalog, skills, loaded, loadError }
}

type SkillChip = { name: string; level: string; matched: boolean }

function formatMatch(pct: number): string {
  if (pct >= 40) return 'match'
  if (pct >= 20) return 'warming'
  return 'unmatched'
}

type NavigateFocus = { skillId: number; roleTitle: string }
type Navigate = (section: string, focus?: NavigateFocus) => void

const LEVEL_RANK: Record<string, number> = { beginner: 1, intermediate: 2, advanced: 3 }

function levelRankOf(level?: string): number {
  if (!level) return 0
  return LEVEL_RANK[String(level).trim().toLowerCase()] || 0
}

function roleExperience(r: RoleRecord): string {
  if (r.required_skills.some((s) => levelRankOf(s.required_level) >= 3)) return 'Senior'
  if (r.required_skills.some((s) => levelRankOf(s.required_level) >= 2)) return 'Mid'
  return 'Entry'
}

function roleCategory(r: RoleRecord): string {
  const counts = new Map<string, number>()
  for (const s of r.required_skills) {
    const c = (s.category || '').trim()
    if (!c) continue
    counts.set(c, (counts.get(c) ?? 0) + 1)
  }
  let best = 'General'
  let bestN = 0
  for (const [c, n] of counts) {
    if (n > bestN || (n === bestN && c < best)) { best = c; bestN = n }
  }
  return best
}

function roleLocation(r: RoleRecord): string {
  const loc = r.company_location
  return typeof loc === 'string' && loc.trim() ? loc.trim() : ''
}

function matchPctOf(r: RoleRecord, cvSkillNames: string[]): number {
  if (r.required_skills.length === 0) return 0
  const present = r.required_skills.reduce((n, s) => n + (cvSkillNames.includes(s.name.toLowerCase().trim()) ? 1 : 0), 0)
  return Math.round((present / r.required_skills.length) * 100)
}

type SkillStatus = 'have' | 'developing' | 'missing'

function statusOfSkill(s: { name: string; required_level: string }, profileByName: Map<string, string>): SkillStatus {
  const level = profileByName.get(s.name.toLowerCase().trim())
  if (!level) return 'missing'
  return levelRankOf(level) >= levelRankOf(s.required_level) ? 'have' : 'developing'
}

function RoleCard({ r, selected, onSelect, selectable, dest, chips }: {
  r: RoleRecord; selected?: boolean; onSelect?: () => void; selectable?: boolean; dest?: string; chips?: SkillChip[]
}) {
  const matchedCount = chips?.filter((c) => c.matched).length ?? 0
  return (
    <div className={`sro3-role ${selected ? 'sro3-role-selected' : ''}`}>
      <div className="sro3-role-top">
        <div className="sro3-role-head">
          <div className="sro3-role-title">
            {r.title}
            {dest === 'catalog' && <span className="chip chip-catalog">Catalog</span>}
          </div>
          <div className="sro3-role-company">
            {r.company_name}
            {r.company_location ? ` · ${r.company_location}` : ''}
          </div>
        </div>
        {chips && (
          <div className={`sro3-match-badge ${formatMatch(Math.round((matchedCount / Math.max(chips.length, 1)) * 100))}`}>
            <strong>{Math.round((matchedCount / Math.max(chips.length, 1)) * 100)}%</strong>
            <span>match</span>
          </div>
        )}
      </div>
      <p className="sro3-role-desc">{r.description}</p>
      <div className="sro3-skill-row">
        {chips && chips.length > 0 && chips.map((c) => (
          <span key={c.name} className={`sro3-skill ${c.matched ? 'on' : 'off'}`}>
            {c.matched ? <IconCheck size={11} /> : <span className="sro3-dot" />}
            {c.name} <span className="lv">{c.level}</span>
          </span>
        ))}
        {!chips && r.required_skills.map((s) => (
          <span className="skill-tag" key={s.skill_id}>{s.name} <span className="lv">{s.required_level}</span></span>
        ))}
      </div>
      {(chips || selectable) && (
        <div className="sro3-role-foot">
          {chips ? (
            <span className="sro3-foot-note">
              {matchedCount} of {chips.length} skills in your profile{matchedCount < chips.length ? ` · ${chips.length - matchedCount} to develop` : ''}
            </span>
          ) : <span />}
          {selectable && (
            <button className={`btn btn-sm ${selected ? '' : 'btn-primary'}`} onClick={onSelect} disabled={selected}>
              {selected ? '✓ Target Career' : 'Select as target'}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ Recommended target role card
function RecommendationCard({ rec, selected, onSelect, busy, saved, onToggleSave }: {
  rec: RoleRecommendation; selected: boolean; onSelect: () => void; busy: boolean; saved: boolean; onToggleSave: () => void
}) {
  const srcLabel = rec.source === 'company' ? 'Company role' : rec.source === 'catalog' ? 'Catalog' : 'ESCO'
  return (
    <div className={`sro3-role ${selected ? 'sro3-role-selected' : ''}`}>
      <div className="sro3-role-top">
        <div className="sro3-role-head">
          <div className="sro3-role-title">
            {rec.title}
            <span className={`chip ${rec.source === 'catalog' ? 'chip-catalog' : rec.source === 'esco' ? 'chip-esco' : ''}`}>
              {srcLabel}
            </span>
          </div>
          <div className="sro3-role-company">
            {rec.company_name || (rec.source === 'esco' ? 'Labour-market occupation' : 'SkillBridge')}
          </div>
        </div>
        <div className="sro3-match-badge match">
          <strong>{Math.round(rec.match_score)}%</strong>
          <span>{rec.confidence}</span>
        </div>
      </div>
      <p className="sro3-role-desc">{rec.reason}</p>
      <div className="sro3-skill-row">
        {(rec.matched_skills || []).slice(0, 12).map((m) => (
          <span key={m.name} className="sro3-skill on">
            <IconCheck size={11} />
            {m.name}
            {m.verified ? <span className="lv">✓ verified</span> : <span className="lv">{m.student_level || ''}</span>}
          </span>
        ))}
      </div>
      {rec.missing_key_skills.length > 0 && (
        <p className="sro3-recs-missing">Skill gap: {rec.missing_key_skills.join(' · ')}</p>
      )}
      {rec.regulated_warning && (
        <p className="sro3-recs-regnote">May be a licensed profession in your region — always verify local requirements.</p>
      )}
      <div className="sro3-role-foot">
        <span className="sro3-foot-note">
          {rec.verified_matches.length > 0 ? `${rec.verified_matches.length} matched skill${rec.verified_matches.length > 1 ? 's' : ''} verified` : 'Based on your self-reported CV profile'}
        </span>
        {rec.role_id != null && (
          <button type="button" className={`srb-save-btn ${saved ? 'on' : ''}`} onClick={onToggleSave}
            aria-pressed={saved} title={saved ? 'Remove from saved roles' : 'Save role'}>
            <IconBookmark size={15} /> <span>{saved ? 'Saved' : 'Save'}</span>
          </button>
        )}
        <button className={`btn btn-sm ${selected ? '' : 'btn-primary'}`} onClick={onSelect} disabled={selected || busy}>
          {busy ? 'Selecting…' : selected ? '✓ Target Career' : 'Select as target'}
        </button>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ New design primitives (redesigned Skills & Roles)
function MatchRing({ pct, size = 88, label }: { pct: number | null; size?: number; label?: string }) {
  const safe = pct == null ? 0 : Math.max(0, Math.min(100, Math.round(pct)))
  return (
    <div
      className="srb-match-ring"
      style={{ '--pct': safe, width: size, height: size } as React.CSSProperties}
      role="img"
      aria-label={pct == null ? 'Match not computed yet' : `${safe}% skill match`}
    >
      <div className="srb-match-inner">
        {pct == null ? <span className="srb-match-none">—</span> : <strong>{safe}%</strong>}
        {label && <span className="srb-match-label">{label}</span>}
      </div>
    </div>
  )
}

function RoleLibraryCard({ r, pct, selected, dest, chips, statusCounts, noCvSkills, saved, onSelect, onDetails, onToggleSave }: {
  r: RoleRecord
  pct: number
  selected: boolean
  dest?: string
  chips?: SkillChip[]
  statusCounts: { have: number; developing: number; missing: number }
  noCvSkills: boolean
  saved: boolean
  onSelect: () => void
  onDetails: () => void
  onToggleSave: () => void
}) {
  const loc = roleLocation(r)
  const shown = (chips ?? []).slice(0, 5)
  return (
    <article className="srb-role">
      <header className="srb-role-head">
        <div className="srb-role-heading">
          <span className={`chip ${dest === 'catalog' ? 'chip-catalog' : 'chip-company'}`}>{dest === 'catalog' ? 'Catalog' : 'Company'}</span>
          <button type="button" className="srb-role-title" onClick={onDetails}>{r.title}</button>
          <p className="srb-role-meta">
            {dest === 'catalog' ? 'Reference profile' : r.company_name || 'Company role'}
            {loc ? ` · ${loc}` : noCvSkills ? ' · Remote' : ' · Not specified'}
            {` · ${roleExperience(r)}`}
          </p>
        </div>
        <MatchRing pct={noCvSkills ? null : pct} size={72} />
      </header>
      {r.description && <p className="srb-role-desc">{r.description.length > 140 ? `${r.description.slice(0, 137)}…` : r.description}</p>}
      {noCvSkills ? (
        <div className="srb-chiprow">
          {r.required_skills.slice(0, 5).map((s) => <span className="skill-tag" key={s.name}>{s.name}</span>)}
          {r.required_skills.length > 5 && <span className="muted small">+{r.required_skills.length - 5} more</span>}
        </div>
      ) : (
        <>
          <div className="srb-chiprow">
            {shown.map((c) => <span className={`srb-schip ${c.matched ? 'have' : ''}`} key={c.name}>{c.name}{c.matched ? ' ✓' : ''}</span>)}
            {(chips?.length ?? 0) > shown.length && <span className="muted small">+{(chips?.length ?? 0) - shown.length} more</span>}
          </div>
          <div className="srb-pills">
            <span className="srb-pill have">{statusCounts.have} strong</span>
            <span className="srb-pill gap">{statusCounts.developing} gap</span>
            <span className="srb-pill missing">{statusCounts.missing} missing</span>
          </div>
        </>
      )}
      <footer className="srb-role-foot">
        <button type="button" className={`srb-save-btn ${saved ? 'on' : ''}`} onClick={onToggleSave}
          aria-pressed={saved} title={saved ? 'Remove from saved roles' : 'Save role'}>
          <IconBookmark size={15} /> <span>{saved ? 'Saved' : 'Save'}</span>
        </button>
        <button type="button" className="btn btn-sm srb-btn-outline" onClick={onDetails}>View details</button>
        <button type="button" className="btn btn-sm btn-primary" onClick={onSelect} disabled={selected}>
          {selected ? '✓ Target' : 'Select as target'}
        </button>
      </footer>
    </article>
  )
}

function RoleDetailsModal({ role, noCvSkills, profileByName, cvSkillNames, selected, busy, saved, onClose, onSelect, onToggleSave, onLearn }: {
  role: RoleRecord
  noCvSkills: boolean
  profileByName: Map<string, string>
  cvSkillNames: string[]
  selected: boolean
  busy: boolean
  saved: boolean
  onClose: () => void
  onSelect: () => void
  onToggleSave: () => void
  onLearn: (skillId: number) => void
}) {
  const pct = matchPctOf(role, cvSkillNames)
  const rows = role.required_skills.map((s) => ({ s, status: statusOfSkill(s, profileByName) }))
  const loc = roleLocation(role)
  const closeRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeRef.current?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => { document.body.style.overflow = prev; window.removeEventListener('keydown', onKey) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const learningGaps = rows.filter((x) => x.status !== 'have')
  return (
    <div className="srb-overlay" onClick={onClose}>
      <div className="srb-modal" role="dialog" aria-modal="true" aria-label={role.title} onClick={(e) => e.stopPropagation()}>
        <header className="srb-modal-head">
          <div>
            <span className={`chip ${role.company_name ? 'chip-company' : 'chip-catalog'}`}>{role.company_name ? 'Company' : 'Catalog'}</span>
            <h3>{role.title}</h3>
            <p className="srb-role-meta">
              {role.company_name || 'Reference profile'}
              {loc ? ` · ${loc}` : ''}
              {` · ${roleExperience(role)}`}
              {` · ${roleCategory(role)}`}
            </p>
          </div>
          <button type="button" className="srb-close" aria-label="Close details" ref={closeRef} onClick={onClose}>✕</button>
        </header>
        {role.description && <p className="srb-modal-desc">{role.description}</p>}
        <div className="srb-modal-match">
          <MatchRing pct={noCvSkills ? null : pct} size={92} />
          <div>
            <p className="srb-eyebrow">Skill match</p>
            {noCvSkills
              ? <p className="small muted">Upload a CV to measure your match against this role.</p>
              : <p className="small muted">{(rows.length - learningGaps.length)} of {rows.length} required skills are on your profile. Verified skills outrank self-reported ones.</p>}
          </div>
        </div>
        <div className="srb-modal-section">
          <h4>Required skills</h4>
          <ul className="srb-skill-list">
            {rows.map(({ s, status }) => (
              <li key={s.name} className={`srb-skill ${status}`}>
                <span className="srb-dot" aria-hidden="true" />
                <span className="srb-skill-name">{s.name} <small>{s.required_level}</small></span>
                <span className="srb-skill-state">
                  {status === 'have' ? '✓ you have this' : status === 'developing' ? '⚠ leveling up' : '○ missing'}
                </span>
              </li>
            ))}
          </ul>
        </div>
        {!noCvSkills && learningGaps.length > 0 && (
          <div className="srb-modal-section">
            <h4>Close your gaps</h4>
            <div className="srb-learn-row">
              {learningGaps.slice(0, 6).map(({ s }) => (
                <button type="button" className="btn btn-sm srb-btn-outline" key={s.name}
                  onClick={() => s.skill_id ? onLearn(s.skill_id) : undefined}
                  disabled={!s.skill_id}>
                  Learn {s.name}
                </button>
              ))}
            </div>
            {learningGaps.length > 6 && <p className="small muted">Set this role as your target to map all remaining gaps below.</p>}
          </div>
        )}
        <footer className="srb-modal-foot">
          <button type="button" className={`srb-save-btn ${saved ? 'on' : ''}`} onClick={onToggleSave}
            aria-pressed={saved}>
            <IconBookmark size={15} /> <span>{saved ? 'Saved' : 'Save role'}</span>
          </button>
          <button type="button" className="btn btn-sm srb-btn-outline" onClick={onClose}>Close</button>
          <button type="button" className="btn btn-sm btn-primary" onClick={onSelect} disabled={selected || busy}>
            {selected ? '✓ Target Career' : busy ? 'Selecting…' : 'Select as target'}
          </button>
        </footer>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ Student browse
function StudentBrowse({ student, analysis, onNavigate }: { student?: Student; analysis?: Analysis; onNavigate?: Navigate }) {
  const { refreshStudent } = useApp()
  const { roles, catalog, loaded, loadError } = useRoles()
  const [q, setQ] = useState('')
  const [selectedRole, setSelectedRole] = useState<number | null>(student?.target_role_id ?? null)
  const [uploading, setUploading] = useState(false)
  const [cvMsg, setCvMsg] = useState('')
  const [cvErr, setCvErr] = useState('')
  const [cvWarn, setCvWarn] = useState(false)
  const [showAll, setShowAll] = useState(false)
  const [srcCompany, setSrcCompany] = useState(true)
  const [srcCatalog, setSrcCatalog] = useState(true)
  const [mq, setMq] = useState('')
  const [market, setMarket] = useState<EscoOccupation[]>([])
  const [marketLoading, setMarketLoading] = useState(false)
  const [marketErr, setMarketErr] = useState('')
  const [marketStatus, setMarketStatus] = useState<'ok' | 'unavailable'>('ok')
  const [marketSelecting, setMarketSelecting] = useState<string | null>(null)
  // Shared relocation-market preference: picking Egypt here also focuses the
  // Dashboard's live jobs feed on Egypt postings (JSearch country=eg).
  const [marketCountry, setMarketCountry] = useState(() => localStorage.getItem('jobs.market') || '')
  const changeMarketCountry = (code: string) => {
    setMarketCountry(code)
    localStorage.setItem('jobs.market', code)
  }
  const [recs, setRecs] = useState<RoleRecommendationsResponse | null>(null)
  const [recsErr, setRecsErr] = useState('')
  const [recSelectingKey, setRecSelectingKey] = useState<string | null>(null)
  const [filters, setFilters] = useState<{ location: string[]; level: string[]; category: string[]; skill: string[] }>({
    location: [],
    level: [],
    category: [],
    skill: [],
  })
  const [detailsRole, setDetailsRole] = useState<RoleRecord | null>(null)
  const [detailsBusy, setDetailsBusy] = useState(false)
  const [savedIds, setSavedIds] = useState<Set<number>>(new Set())
  const [savedOnly, setSavedOnly] = useState(false)
  const toast = useToast()

  useEffect(() => {
    if (!student) return
    api.savedRoles(student.id)
      .then((res: SavedRolesResponse) => setSavedIds(new Set(res.role_ids || [])))
      .catch((e) => console.error('[roles] saved roles failed:', e))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [student?.id])

  const toggleSaveRole = async (roleId: number) => {
    if (!student) return
    const isSaved = savedIds.has(roleId)
    try {
      const res = isSaved
        ? await api.unsaveRole(student.id, roleId)
        : await api.saveRole(student.id, roleId)
      setSavedIds(new Set(res.role_ids || []))
      if (isSaved) toast.push('Role removed from saved.')
      else toast.push('Role saved. Find it under the Saved filter.', 'success')
    } catch (e: any) {
      toast.push(e.message || 'Failed to update saved roles', 'error')
    }
  }

  const all = mergeRoles(roles, catalog)
  const currentTarget = all.find((r) => r.id === selectedRole) || student?.target_role
  const cvSkillNames = (student?.self_reported_skills || [])
    .map((s) => s.name.toLowerCase().trim())
    .filter(Boolean)

  // Rank roles by overlap with the student's CV-extracted skills.
  const ranked = all.map((r) => {
    const score = r.required_skills.reduce((n, s) => n + (cvSkillNames.includes(s.name.toLowerCase().trim()) ? 1 : 0), 0)
    return { r, score }
  }).sort((a, b) => (b.score - a.score) || (a.r.title.localeCompare(b.r.title)))

  const noCvSkills = cvSkillNames.length === 0

  // Reference roles must relate to the user's actual qualifications: only show
  // catalog roles that share at least one skill with the profile, ranked by
  // match. With no CV skills there is nothing to relate to, so nothing shows.
  const refRoles = (() => {
    if (noCvSkills) return []
    return catalog
      .map((r) => ({ r, pct: matchPctOf(r, cvSkillNames) }))
      .filter(({ pct }) => pct > 0)
      .sort((a, b) => (b.pct - a.pct) || a.r.title.localeCompare(b.r.title))
      .map(({ r }) => r)
  })()

  // Verified skills outrank self-reported ones when both name a skill.
  const profileByName = new Map<string, string>()
  for (const s of student?.verified_skills ?? []) profileByName.set(s.name.toLowerCase().trim(), s.level)
  for (const s of student?.self_reported_skills ?? []) {
    if (!profileByName.has(s.name.toLowerCase().trim())) profileByName.set(s.name.toLowerCase().trim(), s.level)
  }

  const facetOptions = useMemo(() => ({
    location: [...new Set(all.map((r) => roleLocation(r)).filter(Boolean))].sort(),
    level: ['Entry', 'Mid', 'Senior'],
    category: [...new Set(all.map((r) => roleCategory(r)))].sort(),
    skill: [...new Set(all.flatMap((r) => r.required_skills.map((s) => s.name).filter(Boolean)))].sort(),
  }), [all])

  const hasNoLocation = all.some((r) => !roleLocation(r))

  const activeFilters: { group: keyof typeof filters; label: string; value: string }[] = [
    ...filters.location.map((v) => ({ group: 'location' as const, label: 'Location', value: v })),
    ...filters.category.map((v) => ({ group: 'category' as const, label: 'Category', value: v })),
    ...filters.level.map((v) => ({ group: 'level' as const, label: 'Experience', value: v })),
    ...filters.skill.map((v) => ({ group: 'skill' as const, label: 'Skill', value: v })),
  ]
  const toggleFilter = (group: keyof typeof filters, value: string) => {
    setFilters((f) => ({ ...f, [group]: f[group].includes(value) ? f[group].filter((x) => x !== value) : [...f[group], value] }))
  }
  const clearFilters = () => setFilters({ location: [], level: [], category: [], skill: [] })

  // Real jobs (ESCO occupations + company postings) lead; SkillBridge catalog
  // reference roles are demoted to their own labelled secondary section.
  const realRecs = (recs?.recommendations || []).filter((r) => r.source !== 'catalog')

  const targetPct = cvSkillNames.length > 0 && (currentTarget?.required_skills.length ?? 0) > 0
    ? Math.round((currentTarget!.required_skills.reduce((n, s) => n + (cvSkillNames.includes(s.name.toLowerCase().trim()) ? 1 : 0), 0) / currentTarget!.required_skills.length) * 100)
    : null

  const filtered = ranked.filter(({ r, score }) => {
    if (savedOnly && !savedIds.has(r.id)) return false
    const haystack = [r.title, r.company_name, roleLocation(r), roleCategory(r), roleExperience(r), r.description, ...r.required_skills.map((s) => s.name)]
      .map((x) => (x ? String(x) : '').toLowerCase())
      .filter(Boolean)
      .join(' ')
    const needle = q.trim().toLowerCase()
    if (needle && !haystack.includes(needle)) return false
    const isCat = catalog.some((c) => c.id === r.id)
    if (isCat ? !srcCatalog : !srcCompany) return false
    const facetOk = (value: string, list: string[]) => list.length === 0 || list.includes(value)
    if (!facetOk(roleLocation(r) || 'Not specified', filters.location)) return false
    if (!facetOk(roleExperience(r), filters.level)) return false
    if (!facetOk(roleCategory(r), filters.category)) return false
    if (filters.skill.length) {
      const names = r.required_skills.map((s) => s.name.toLowerCase().trim())
      if (!filters.skill.some((s) => names.includes(s.toLowerCase().trim()))) return false
    }
    // Without a CV we have nothing to match against, so show everything.
    if (noCvSkills) return true
    // With a CV, surface the best-fitting roles first, but let the user see all.
    return showAll || score > 0
  })

  const chooseTarget = async (roleId: number) => {
    if (!student) return
    await api.updateStudent(student.id, { target_role_id: roleId })
    setSelectedRole(roleId)
    await refreshStudent()
    toast.push('Target career updated.', 'success')
  }

  // Backend-ranked universal recommendations (company + catalog + ESCO).
  // Refetch whenever the *profile* changes, not just on student id: a fresh CV
  // upload (or verified skill / target change) must immediately recompute the
  // recommendations server-side, otherwise the section keeps showing the
  // previous profile's roles.
  const recsKey = [
    student?.id,
    student?.target_role_id,
    (student?.self_reported_skills || []).map((s) => `${s.name}:${s.level}`).join('|'),
    (student?.verified_skills || []).map((v) => `${v.name}:${v.level}`).join('|'),
  ].join('::')
  useEffect(() => {
    if (!student) return
    api.roleRecommendations(student.id)
      .then(setRecs)
      .catch((e) => { console.error('[roles] recommendations failed:', e); setRecsErr(e.message || 'Recommendations unavailable') })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recsKey])

  const selectRecommendation = async (rec: RoleRecommendation) => {
    if (!student) return
    const key = rec.role_id != null ? String(rec.role_id) : rec.external_id || rec.title
    setRecSelectingKey(key)
    try {
      if (rec.source === 'esco' && rec.external_id) {
        await api.selectEscoTarget(student.id, rec.external_id, rec.title, rec.skills)
        setSelectedRole(null)
      } else if (rec.role_id != null) {
        await api.updateStudent(student.id, { target_role_id: rec.role_id })
        setSelectedRole(rec.role_id)
      } else {
        return
      }
      toast.push('Target career updated.', 'success')
      await refreshStudent()
    } catch (e: any) {
      toast.push(e.message || 'Failed to select target role', 'error')
    } finally {
      setRecSelectingKey(null)
    }
  }

  const recSelected = (rec: RoleRecommendation): boolean => {
    if (rec.role_id != null) return selectedRole === rec.role_id
    if (rec.external_id) return student?.target_role?.external_id === rec.external_id
    return false
  }

  const runMarketSearch = async (q?: string) => {
    const query = (q ?? mq).trim()
    if (!query) return
    setMarketLoading(true)
    setMarketErr('')
    try {
      const res = await api.escoMarket(query, 8, student?.target_role?.title || undefined)
      setMarket(res.occupations || [])
      setMarketStatus(res.status === 'unavailable' ? 'unavailable' : 'ok')
      if (res.status === 'unavailable') setMarketErr(res.message || 'Live role lookup is unavailable right now.')
      setMq(query)
    } catch (e: any) {
      const raw = String(e?.message || e || '')
      setMarketErr(
        raw.includes('Failed to fetch')
          ? 'Live role lookup is unavailable right now (network issue). Check your connection and try again.'
          : (e?.message || 'Live occupation lookup failed'))
      setMarketStatus('unavailable')
      setMarket([])
    } finally {
      setMarketLoading(false)
    }
  }

  const selectMarketTarget = async (occ: EscoOccupation) => {
    if (!student) return
    setMarketSelecting(occ.uri)
    try {
      await api.selectEscoTarget(student.id, occ.uri, occ.title, occ.skills)
      toast.push('Target career updated to a real job role.')
      await refreshStudent()
    } catch (e: any) {
      toast.push(e?.message || 'Failed to select target role', 'error')
    } finally {
      setMarketSelecting(null)
    }
  }

  // Seed the live-role search once, once the role pool is loaded, with the most
  // discriminative profile skill (IDF-like rarity), not the stale target title.
  const seededRef = useRef(false)
  useEffect(() => {
    if (seededRef.current || !loaded) return
    seededRef.current = true
    const profile = student?.self_reported_skills || []
    // Target Role is the primary seed for ESCO market discovery.
    // CV skill is only used when no target role is selected.
    const seed = student?.target_role?.title
      || pickSeedSkill(profile, roles, catalog)
      || profile[0]?.name || ''
    const trimmed = seed.trim().slice(0, 80)
    if (trimmed) { setMq(trimmed); runMarketSearch(trimmed) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded])

  const onUpload = async (file: File | undefined) => {
    if (!file || !student) return
    setUploading(true)
    setCvMsg(''); setCvErr(''); setCvWarn(false)
    try {
      const res = await api.uploadCv(student.id, file)
      if (res.warning) {
        setCvMsg(res.warning)
        setCvWarn(true)
        toast.push(res.warning)
      } else {
        setCvMsg(`Extracted ${res.extracted.length} skills from "${file.name}". These are shown as self-reported until verified by an assessment.`)
        toast.push(`Extracted ${res.extracted.length} skills from your CV.`)
      }
      await refreshStudent()
    } catch (e: any) {
      setCvErr(e.message || 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  const initials = (student?.name || 'S').split(' ').map((w) => w[0]).slice(0, 2).join('').toUpperCase()

  const openRoleDetails = (r: RoleRecord) => setDetailsRole(r)
  const closeRoleDetails = () => { if (!detailsBusy) setDetailsRole(null) }
  const selectFromDetails = async (r: RoleRecord) => {
    setDetailsBusy(true)
    try { await chooseTarget(r.id); setDetailsRole(null) }
    finally { setDetailsBusy(false) }
  }
  const learnSkill = (skillId: number) => {
    const role = detailsRole
    setDetailsRole(null)
    onNavigate?.('learning', { skillId, roleTitle: role?.title ?? '' })
  }

  return (
    <div className="skills-page sro3-page">
      <section className="sro3-hero">
        <div className="sro3-hero-copy">
          <p className="sro3-eyebrow">Find your next role</p>
          <h1 className="sro3-hero-title">Choose the role your learning path should serve.</h1>
          <p className="sro3-hero-sub">Your CV profile, verified skills, and target role stay separate so the match score remains explainable. Search the library, filter by where you want to work, and compare roles before committing.</p>
        </div>
      </section>

      <section className="srb-summary" aria-label="Career summary">
        <div className="srb-card srb-target-card">
          <div className="srb-card-head">
            <span className="srb-eyebrow">Your target career</span>
            <MatchRing pct={targetPct} size={96} label="match" />
          </div>
          <h3 className="srb-target-title">{currentTarget?.title || 'Not selected yet'}</h3>
          <p className="srb-target-meta">
            {currentTarget
              ? `${currentTarget.company_name || 'Reference profile'}${roleExperience(currentTarget) ? ` · ${roleExperience(currentTarget)}` : ''}`
              : 'Select a role to unlock your gap map'}
          </p>
          {targetPct === null && !noCvSkills && <p className="small muted">Upload a CV to see your match score against this role.</p>}
          <button type="button" className="btn btn-sm btn-primary" onClick={() => document.getElementById('role-library')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}>
            Browse roles
          </button>
        </div>
        <div className="srb-card srb-profile-card">
          <div className="srb-card-head">
            <span className="srb-eyebrow">Profile &amp; CV</span>
            <label className="btn btn-sm srb-btn-outline" style={{ cursor: 'pointer' }}>
              <IconUpload size={14} /> {uploading ? 'Extracting…' : 'Upload CV'}
              <input type="file" accept=".txt,.md,.pdf" style={{ display: 'none' }} onChange={(e) => onUpload(e.target.files?.[0])} />
            </label>
          </div>
          <div className="srb-profile-line">
            <span className="avatar srb-avatar">{initials}</span>
            <span className="srb-profile-file">{student?.cv_filename || 'No CV uploaded'}</span>
          </div>
          <div className="srb-stat-row">
            <div className="srb-stat">
              <strong>{(student?.self_reported_skills || []).length}</strong>
              <span>skills detected</span>
            </div>
            <div className="srb-stat">
              <strong className="srb-green">{(student?.verified_skills || []).length}</strong>
              <span>verified</span>
            </div>
            <div className="srb-stat">
              <strong>{targetPct !== null ? `${targetPct}%` : '—'}</strong>
              <span>target match</span>
            </div>
          </div>
          {cvMsg && <p className="small" style={{ color: cvWarn ? 'var(--amber)' : 'var(--green)' }}>{cvMsg}</p>}
          {cvErr && <p className="small" style={{ color: 'var(--red)' }}>{cvErr}</p>}
        </div>
      </section>

      {recs && realRecs.length > 0 && (
        <div className="sro3-recs-card">
          <div className="sro3-roles-head">
            <h3 className="sro3-roles-title">Real jobs matching your skills</h3>
            <span className="sro3-count">{realRecs.length} real job role{realRecs.length > 1 ? 's' : ''}</span>
          </div>
          <p className="card-sub">{recs.note}</p>
          <div className="stack sro3-list">
            {realRecs.map((rec) => (
              <RecommendationCard
                key={rec.role_id ?? rec.external_id ?? rec.title}
                rec={rec}
                selected={recSelected(rec)}
                busy={recSelectingKey === (rec.role_id != null ? String(rec.role_id) : rec.external_id || rec.title)}
                onSelect={() => selectRecommendation(rec)}
                saved={rec.role_id != null && savedIds.has(rec.role_id)}
                onToggleSave={() => rec.role_id != null && toggleSaveRole(rec.role_id)}
              />
            ))}
          </div>
        </div>
      )}
      {recs && recs.recommendations.length === 0 && !recsErr && (
        <div className="card">
          <div className="empty">{recs.note}</div>
        </div>
      )}

      {loaded && catalog.length > 0 && (
        <section className="srb-ref-section" aria-label="Reference roles">
          <div className="srb-section-head">
            <div>
              <p className="srb-eyebrow">Reference roles — local catalogue</p>
              <h3>Careers you can aim at</h3>
              <p className="card-sub">SkillBridge reference skill profiles — not live job postings. Only roles that share skills with your profile are shown, so nothing irrelevant gets in the way.</p>
            </div>
            <span className="srb-count">{refRoles.length} role{refRoles.length === 1 ? '' : 's'}</span>
          </div>
          {refRoles.length === 0 ? (
            <div className="empty">
              No reference roles relate to your skills yet.{noCvSkills ? ' Upload a CV above to surface roles that match your qualifications.' : ' Add more skills to your profile to discover careers you can aim at.'}
            </div>
          ) : (
          <div className="srb-ref-row">
            {refRoles.map((r) => {
              const present = r.required_skills.reduce((n, s) => n + (cvSkillNames.includes(s.name.toLowerCase().trim()) ? 1 : 0), 0)
              const gapNames = r.required_skills.filter((s) => !cvSkillNames.includes(s.name.toLowerCase().trim())).slice(0, 3).map((s) => s.name)
              const isTarget = selectedRole === r.id || student?.target_role_id === r.id
              return (
                <article className="srb-ref-card" key={r.id}>
                  <div className="srb-ref-top">
                    <span className="chip chip-catalog">Catalog</span>
                    <MatchRing pct={matchPctOf(r, cvSkillNames)} size={70} />
                  </div>
                  <h4 className="srb-ref-title">{r.title}</h4>
                  <p className="srb-ref-gap">
                    {`${present} of ${r.required_skills.length} key skills already in your profile.`}
                  </p>
                  {gapNames.length > 0 && (
                    <p className="srb-ref-gap-names">Gap: {gapNames.join(' · ')}{gapNames.length < r.required_skills.length - present ? '…' : ''}</p>
                  )}
                  <div className="srb-ref-actions">
                    <button
                      type="button"
                      className={`srb-save-btn ${savedIds.has(r.id) ? 'on' : ''}`}
                      aria-pressed={savedIds.has(r.id)}
                      title={savedIds.has(r.id) ? 'Remove from saved roles' : 'Save role'}
                      onClick={() => toggleSaveRole(r.id)}
                    >
                      <IconBookmark size={15} /> <span>{savedIds.has(r.id) ? 'Saved' : 'Save'}</span>
                    </button>
                    <button
                      type="button"
                      className={`btn btn-sm ${isTarget ? '' : 'btn-primary'}`}
                      disabled={isTarget}
                      onClick={() => chooseTarget(r.id)}
                    >
                      {isTarget ? '✓ Target Career' : 'Select as target'}
                    </button>
                  </div>
                </article>
              )
            })}
          </div>
          )}
        </section>
      )}

      <section className="sro3-roles-card" id="role-library" aria-label="Role library">
        <div className="sro3-roles-head">
          <h3 className="sro3-roles-title">Role library</h3>
          <span className="sro3-count">{loaded ? `${filtered.length} matching roles` : '…'}</span>
        </div>
        <p className="card-sub">Search roles, filter by where and what you want, and read each role's requirements before committing to a target.</p>
        <div className="searchbar mb">
          <IconSearch size={16} />
          <input placeholder="Search roles, companies, skills, categories…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search roles" />
        </div>

        {!loaded && !loadError && (
          <div className="srb-skel-grid" aria-label="Loading roles">
            {Array.from({ length: 6 }).map((_, i) => <div className="srb-skeleton" key={i} />)}
          </div>
        )}
        {loadError && <div className="error" style={{ marginBottom: 12 }}>{loadError}</div>}

        {loaded && (
          <>
            <div className="srb-filterbar">
              <label className="srb-switch">
                <input
                  type="checkbox"
                  checked={showAll}
                  onChange={() => setShowAll((s) => !s)}
                  disabled={noCvSkills}
                />
                <span className="srb-switch-track" aria-hidden="true" />
                <span className="srb-switch-label">Show every role</span>
              </label>
              <div className="srb-segmented" role="group" aria-label="Role source">
                <button type="button" className={srcCompany ? 'on' : ''} onClick={() => setSrcCompany((s) => !s)} aria-pressed={srcCompany}>Company roles</button>
                <button type="button" className={srcCatalog ? 'on' : ''} onClick={() => setSrcCatalog((s) => !s)} aria-pressed={srcCatalog}>Catalog roles</button>
              </div>
              <button type="button" className={`srb-chip saved ${savedOnly ? 'on' : ''}`}
                onClick={() => { setSavedOnly((s) => !s); setShowAll(true) }}
                aria-pressed={savedOnly} title={`${savedIds.size} saved role${savedIds.size === 1 ? '' : 's'}`}>
                <IconBookmark size={14} /> Saved{savedIds.size > 0 ? ` (${savedIds.size})` : ''}
              </button>
              <details className="srb-facet">
                <summary>Location{filters.location.length ? ` (${filters.location.length})` : ''}</summary>
                <div className="srb-facet-opts">
                  {hasNoLocation && (
                    <label><input type="checkbox" checked={filters.location.includes('Not specified')} onChange={() => toggleFilter('location', 'Not specified')} /> Remote / not specified</label>
                  )}
                  {facetOptions.location.map((l) => (
                    <label key={l}><input type="checkbox" checked={filters.location.includes(l)} onChange={() => toggleFilter('location', l)} /> {l}</label>
                  ))}
                </div>
              </details>
              <details className="srb-facet">
                <summary>Experience{filters.level.length ? ` (${filters.level.length})` : ''}</summary>
                <div className="srb-facet-opts">
                  {facetOptions.level.map((l) => (
                    <label key={l}><input type="checkbox" checked={filters.level.includes(l)} onChange={() => toggleFilter('level', l)} /> {l}</label>
                  ))}
                </div>
              </details>
              <details className="srb-facet">
                <summary>Category{filters.category.length ? ` (${filters.category.length})` : ''}</summary>
                <div className="srb-facet-opts">
                  {facetOptions.category.map((c) => (
                    <label key={c}><input type="checkbox" checked={filters.category.includes(c)} onChange={() => toggleFilter('category', c)} /> {c}</label>
                  ))}
                </div>
              </details>
              <details className="srb-facet">
                <summary>Skill{filters.skill.length ? ` (${filters.skill.length})` : ''}</summary>
                <div className="srb-facet-opts srb-facet-scroll">
                  {facetOptions.skill.map((s) => (
                    <label key={s}><input type="checkbox" checked={filters.skill.includes(s)} onChange={() => toggleFilter('skill', s)} /> {s}</label>
                  ))}
                </div>
              </details>
            </div>

            {activeFilters.length > 0 && (
              <div className="srb-active">
                {activeFilters.map(({ group, value }) => (
                  <button key={`${group}:${value}`} type="button" className="srb-chip" onClick={() => toggleFilter(group, value)}>
                    {value} <span className="srb-chip-x" aria-hidden="true">✕</span>
                  </button>
                ))}
                <button type="button" className="srb-clear" onClick={clearFilters}>Clear all</button>
              </div>
            )}
            {noCvSkills && <p className="small muted" style={{ margin: '10px 0 14px' }}>No CV skills yet — showing the full catalog. Upload a CV above to rank roles against your profile.</p>}

            {filtered.length === 0 ? (
              <div className="empty">
                No roles match the current search.
                {(activeFilters.length > 0 || q.trim()) ? (
                  <button type="button" className="btn btn-sm srb-btn-outline" style={{ marginTop: 10, display: 'block', marginInline: 'auto' }} onClick={() => { setQ(''); clearFilters() }}>Clear search &amp; filters</button>
                ) : null}
              </div>
            ) : (
              <div className="srb-grid">
                {filtered.map(({ r }) => {
                  const statusBySkill = r.required_skills.map((s) => ({ s, status: statusOfSkill(s, profileByName) }))
                  return (
                    <RoleLibraryCard
                      key={r.id}
                      r={r}
                      pct={matchPctOf(r, cvSkillNames)}
                      selected={selectedRole === r.id}
                      dest={catalog.some((c) => c.id === r.id) ? 'catalog' : undefined}
                      chips={noCvSkills ? undefined : statusBySkill.map(({ s, status }) => ({ name: s.name, level: s.required_level, matched: status !== 'missing' }))}
                      statusCounts={{
                        have: statusBySkill.filter((x) => x.status === 'have').length,
                        developing: statusBySkill.filter((x) => x.status === 'developing').length,
                        missing: statusBySkill.filter((x) => x.status === 'missing').length,
                      }}
                      noCvSkills={noCvSkills}
                      saved={savedIds.has(r.id)}
                      onSelect={() => chooseTarget(r.id)}
                      onDetails={() => openRoleDetails(r)}
                      onToggleSave={() => toggleSaveRole(r.id)}
                    />
                  )
                })}
              </div>
            )}
          </>
        )}
      </section>

      {detailsRole && (
        <RoleDetailsModal
          role={detailsRole}
          noCvSkills={noCvSkills}
          profileByName={profileByName}
          cvSkillNames={cvSkillNames}
          selected={selectedRole === detailsRole.id}
          busy={detailsBusy}
          saved={savedIds.has(detailsRole.id)}
          onClose={closeRoleDetails}
          onSelect={() => selectFromDetails(detailsRole)}
          onToggleSave={() => toggleSaveRole(detailsRole.id)}
          onLearn={learnSkill}
        />
      )}

      <div className="card">
        <div className="flex between" style={{ flexWrap: 'wrap', gap: 10 }}>
          <h3>My profile &amp; CV</h3>
          <label className="btn btn-sm" style={{ cursor: 'pointer' }}>
            <IconUpload size={14} /> {uploading ? 'Extracting…' : 'Upload CV'}
            <input type="file" accept=".txt,.md,.pdf" style={{ display: 'none' }} onChange={(e) => onUpload(e.target.files?.[0])} />
          </label>
        </div>
        {cvMsg && <p className="small" style={{ color: cvWarn ? 'var(--amber)' : 'var(--green)' }}>{cvMsg}</p>}
        {cvErr && <p className="small" style={{ color: 'var(--red)' }}>{cvErr}</p>}
        <div className="divider" />
        <p className="small muted mb">Self-reported profile (extracted from CV by GenAI, unverified)</p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {(student?.self_reported_skills || []).map((s) => (
            <SkillTag key={s.skill_id} name={s.name} level={s.level} verified={false} />
          ))}
          {(student?.self_reported_skills || []).length === 0 && <span className="muted small">Upload a CV or transcript to build this.</span>}
        </div>
        <div style={{ marginTop: 14 }}>
          <span className="small muted mb" style={{ display: 'block' }}>Verified skills (earned via assessments)</span>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {(student?.verified_skills || []).map((s) => (
              <SkillTag key={s.skill_id} name={s.name} level={s.level} verified={true} />
            ))}
            {(student?.verified_skills || []).length === 0 && <span className="muted small">No verified skills yet.</span>}
          </div>
        </div>
      </div>

      <section className="sro3-gap">
        <div className="sro3-gap-head">
          <div className="sro3-gap-icon"><IconTarget size={16} /></div>
          <div>
            <p className="sro3-eyebrow">Career readiness</p>
            <h3>Your {currentTarget?.title || 'target'} skill gap</h3>
            {targetPct !== null && <p className="sro3-gap-sub">You already match {targetPct}% of this role's requirements.</p>}
            {targetPct === null && <p className="sro3-gap-sub">{noCvSkills ? 'Upload a CV so matching can begin.' : 'Pick a target career to see your gap map.'}</p>}
          </div>
        </div>
        {analysis && analysis.skill_gaps && analysis.skill_gaps.length > 0 ? (
          <div className="sro3-gap-list">
            {analysis.skill_gaps.map((g) => (
              <div className="sro3-gap-row" key={g.skill_id}>
                <span className="sro3-gap-name">
                  {g.skill_name}
                  <small>Required {g.required_level}{g.student_level && g.student_level !== 'None' ? ` · you: ${g.student_level}` : ''}</small>
                </span>
                <span className="sro3-gap-status"><GapPill status={g.status} /></span>
              </div>
            ))}
          </div>
        ) : (
          <p className="sro3-gap-empty">
            {noCvSkills
              ? 'There is no gap map yet because there are no skills on your profile.'
              : 'Select a role as your target career to generate the skill gap map here.'}
          </p>
        )}
      </section>

      <section className="sro3-market">
        <div className="sro3-market-head">
          <div>
            <p className="sro3-eyebrow">Live market roles</p>
            <h3>Roles that actually exist in the labour market</h3>
            <p className="card-sub">Titles from the official ESCO catalog, with the essential skills real employers expect. Try your target career, or a skill from your CV.</p>
          </div>
          <span className="chip chip-catalog">Official EU occupation catalog</span>
        </div>
        <div className="flex between" style={{ alignItems: 'center', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
          <span className="small muted">Choose a market (Egypt, UAE, UK, US&hellip;) for context. Select what you need as your target and build toward it.</span>
          <select
            className="market-select"
            value={marketCountry}
            onChange={(e) => changeMarketCountry(e.target.value)}
            aria-label="Market country"
            style={{ maxWidth: 260 }}
          >
            <option value="">Global / all markets</option>
            {RELOCATION_MARKETS.filter((m) => m.code).map((m) => (
              <option key={m.code} value={m.code}>{m.label}</option>
            ))}
          </select>
        </div>
        {marketCountry && (
          <p className="card-sub" style={{ marginTop: 0 }}>
            ESCO is the official EU-wide occupation catalog, so these are real occupations that also exist in&nbsp;{marketLabel(marketCountry)}'s labour market. For {marketLabel(marketCountry)}-specific job postings, use the relocation search on your Dashboard's jobs feed.
          </p>
        )}
        <div className="searchbar mb">
          <IconSearch size={16} />
          <input placeholder="e.g. data scientist, software developer…" value={mq} onChange={(e) => setMq(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') runMarketSearch() }} />
          <button className="btn btn-sm btn-primary" onClick={() => runMarketSearch()} disabled={marketLoading}>
            <IconSearch size={13} /> {marketLoading ? 'Looking up…' : 'Search'}
          </button>
        </div>
        {marketErr && <div className="error" style={{ marginBottom: 12 }}>{marketErr}</div>}
        {market.length > 0 && (
          <div className="sro3-market-list">
            {market.map((o) => (
              <div className="sro3-market-row" key={o.uri}>
                <div className="sro3-market-main">
                  <strong>{o.title}</strong>
                  <span className="sro3-market-count">{o.skill_count} essential skills</span>
                </div>
                <div className="sro3-market-skills">
                  {o.skills.slice(0, 5).map((s) => <span className="skill-tag" key={s}>{s}</span>)}
                  {o.skills.length > 5 && <span className="muted small">+{o.skills.length - 5} more</span>}
                </div>
                <button
                  className={`btn btn-sm ${student?.target_role?.external_id === o.uri ? '' : 'btn-primary'}`}
                  style={{ alignSelf: 'flex-end', whiteSpace: 'nowrap' }}
                  disabled={student?.target_role?.external_id === o.uri || marketSelecting === o.uri}
                  onClick={() => selectMarketTarget(o)}
                >
                  {marketSelecting === o.uri ? 'Selecting…' : student?.target_role?.external_id === o.uri ? '✓ Target Career' : 'Select as target'}
                </button>
              </div>
            ))}
          </div>
        )}
        {!marketLoading && market.length === 0 && marketStatus === 'ok' && !marketErr && (
          <div className="empty">No occupations found for that search. Try a role title, or a distinctive skill from your CV.</div>
        )}
        {marketStatus === 'unavailable' && !marketLoading && market.length === 0 && (
          <div className="error" style={{ marginBottom: 12 }}>Live role lookup is unavailable right now — this is temporary. Your profile and local role matching still work.</div>
        )}
      </section>
      <ToastRegion toasts={toast.toasts} dismiss={toast.dismiss} />
    </div>
  )
}

// ------------------------------------------------------------------ Company roles
function CompanyRoles({ company }: { company?: any }) {
  const { roles, setRoles, skills, loaded, loadError } = useRoles()
  const [editing, setEditing] = useState<any>(null)
  const [showForm, setShowForm] = useState(false)
  const [confirmRole, setConfirmRole] = useState<RoleRecord | null>(null)
  const [deleting, setDeleting] = useState(false)
  const toast = useToast()

  const refresh = () => api.roles().then((res) => setRoles(res.roles))
  useEffect(() => { if (!loaded) refresh() }, [loaded])

  const openNew = () => {
    setEditing({ id: null, title: '', description: '', skillRows: [{ name: '', level: 'Intermediate', category: 'General' }] })
    setShowForm(true)
  }
  const openEdit = (r: RoleRecord) => {
    setEditing({
      id: r.id, title: r.title, description: r.description || '',
      skillRows: r.required_skills.map((s) => ({ name: s.name, level: s.required_level, category: s.category || 'General' })),
    })
    setShowForm(true)
  }

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!company) return
    const body = {
      company_id: company.id,
      title: editing.title,
      description: editing.description,
      required_skills: editing.skillRows
        .filter((s: any) => s.name.trim())
        .map((s: any) => ({ name: s.name.trim(), level: s.level, category: s.category || 'General' })),
    }
    if (!body.required_skills.length) return
    try {
      await api.createRole(body)
      setShowForm(false)
      refresh()
      toast.push('Role saved successfully.')
    } catch (err: any) {
      toast.push(err.message || 'Failed to save role', 'error')
    }
  }

  const askRemove = (r: RoleRecord) => setConfirmRole(r)

  const removeRole = async () => {
    if (!confirmRole) return
    setDeleting(true)
    try {
      await api.deleteRole(confirmRole.id)
      setConfirmRole(null)
      refresh()
      toast.push('Role deleted.')
    } catch (err: any) {
      toast.push(err.message || 'Failed to delete role', 'error')
    } finally {
      setDeleting(false)
    }
  }

  const changeRow = (i: number, patch: any) => {
    setEditing((prev: any) => ({
      ...prev, skillRows: prev.skillRows.map((r: any, idx: number) => (idx === i ? { ...r, ...patch } : r)),
    }))
  }

  return (
    <div className="skills-page sro3-page">
      {loadError && <div className="error" style={{ marginBottom: 12 }}>{loadError}</div>}
      <section className="sro3-hero">
        <div className="sro3-hero-copy">
          <p className="sro3-eyebrow">Company Workspace</p>
          <h1 className="sro3-hero-title">Define the skills your roles require.</h1>
          <p className="sro3-hero-sub">Students are matched against these requirements without changing the underlying scoring logic.</p>
        </div>
        <button className="btn sro3-hero-cta" onClick={openNew}><IconPlus size={15} /> Define role</button>
      </section>

      {showForm && editing && (
        <div className="card mb">
          <h3>{editing.id ? 'Edit role' : 'Define a new role'}</h3>
          <form onSubmit={save}>
            <div className="field"><label>Job title</label>
              <input value={editing.title} onChange={(e) => setEditing({ ...editing, title: e.target.value })} required /></div>
            <div className="field"><label>Description</label>
              <input value={editing.description} onChange={(e) => setEditing({ ...editing, description: e.target.value })} /></div>
            <p className="small muted mb">Required skills &amp; proficiency levels</p>
            {editing.skillRows.map((row: any, i: number) => (
              <div className="flex" key={i} style={{ marginBottom: 8 }}>
                <input placeholder="Skill name" value={row.name} onChange={(e) => changeRow(i, { name: e.target.value })}
                  list="skill-options" style={{ flex: 1, padding: '8px 12px', border: '1px solid var(--slate-300)', borderRadius: 6 }} />
                <select value={row.level} onChange={(e) => changeRow(i, { level: e.target.value })}
                  style={{ padding: '8px 10px', border: '1px solid var(--slate-300)', borderRadius: 6 }}>
                  {LEVELS.map((l) => <option key={l}>{l}</option>)}
                </select>
                <input placeholder="Category" value={row.category} onChange={(e) => changeRow(i, { category: e.target.value })}
                  style={{ width: 140, padding: '8px 12px', border: '1px solid var(--slate-300)', borderRadius: 6 }} />
                {editing.skillRows.length > 1 && (
                  <button type="button" className="btn btn-sm btn-danger" onClick={() =>
                    setEditing((p: any) => ({ ...p, skillRows: p.skillRows.filter((_: any, idx: number) => idx !== i) }))}>
                    <IconTrash size={13} /></button>
                )}
              </div>
            ))}
            <datalist id="skill-options">{skills.map((s) => <option key={s.id} value={s.name} />)}</datalist>
            <button type="button" className="btn btn-sm" onClick={() =>
              setEditing((p: any) => ({ ...p, skillRows: [...p.skillRows, { name: '', level: 'Intermediate', category: 'General' }] }))}>
              <IconPlus size={13} /> Add skill</button>
            <div className="flex mt" style={{ justifyContent: 'flex-end' }}>
              <button type="button" className="btn" onClick={() => setShowForm(false)}>Cancel</button>
              <button type="submit" className="btn btn-primary"><IconCheck /> Save role</button>
            </div>
          </form>
        </div>
      )}

      <div className="card">
        <div className="flex between" style={{ flexWrap: 'wrap', gap: 10 }}>
          <h3>Roles you have defined</h3>
          <span className="sro3-count">{roles.length} roles</span>
        </div>
        {roles.length === 0 && <div className="empty">No roles defined yet. Create one above.</div>}
        <div className="stack">
          {roles.map((r) => (
            <div className="sro3-role" key={r.id}>
              <div className="sro3-role-top">
                <div className="sro3-role-head">
                  <div className="sro3-role-title">{r.title}</div>
                  <div className="sro3-role-company">{r.company_name}</div>
                </div>
                <div className="rc-actions">
                  <button className="btn btn-sm" onClick={() => openEdit(r)}><IconEdit size={14} /> Edit</button>
                  <button className="btn btn-sm btn-danger" onClick={() => askRemove(r)}><IconTrash size={14} /></button>
                </div>
              </div>
              <div className="sro3-skill-row">
                {r.required_skills.map((s) => (
                  <span className="skill-tag" key={s.skill_id}>{s.name} <span className="lv">{s.required_level}</span></span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      <ConfirmModal
        open={!!confirmRole}
        title="Delete this role?"
        body={<>Delete <span className="modal-name">{confirmRole?.title}</span>? Students currently targeting this role will lose their target. This can't be undone.</>}
        confirmLabel="Delete role"
        busy={deleting}
        onCancel={() => setConfirmRole(null)}
        onConfirm={removeRole}
      />
      <ToastRegion toasts={toast.toasts} dismiss={toast.dismiss} />
    </div>
  )
}

// ------------------------------------------------------------------ Read-only (university)
function ReadOnlyBrowse() {
  const { roles, catalog, loadError } = useRoles()
  const all = mergeRoles(roles, catalog)
  return (
    <div className="skills-page sro3-page">
      <section className="sro3-hero">
        <div className="sro3-hero-copy">
          <p className="sro3-eyebrow">University Cohort</p>
          <h1 className="sro3-hero-title">Roles across the cohort &amp; catalog.</h1>
          <p className="sro3-hero-sub">Company-defined roles and reference skill profiles students can aim at.</p>
        </div>
        <span className="chip chip-big"><IconRoles size={13} /> Catalog references included</span>
      </section>
      <div className="card">
        {loadError && <div className="error" style={{ marginBottom: 12 }}>{loadError}</div>}
        <div className="flex between" style={{ flexWrap: 'wrap', gap: 10 }}>
          <h3>All roles</h3>
          <span className="sro3-count">{all.length} roles</span>
        </div>
        <div className="stack mt">
          {all.map((r) => (
            <RoleCard key={r.id} r={r} dest={catalog.some((c) => c.id === r.id) ? 'catalog' : undefined} />
          ))}
          {all.length === 0 && <div className="empty">No roles available.</div>}
        </div>
      </div>
    </div>
  )
}