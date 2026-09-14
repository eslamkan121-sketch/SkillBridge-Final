import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useApp } from '../AppContext'
import { api } from '../lib/api'
import { RELOCATION_MARKETS, marketLabel } from '../lib/markets'
import type { RoleRecord, Student, Skill, RolesResponse, EscoOccupation, Analysis, RoleRecommendation, RoleRecommendationsResponse, SavedRolesResponse, ScenarioLibrary, RoleMappingMatch, RoleMappingTarget, RoleMappingEvent, RecentRole, RoleProvenance, RecentJob, RecentJobsResponse } from '../lib/types'
import { IconPlus, IconEdit, IconTrash, IconUpload, IconSearch, IconCheck, IconTarget, IconBookmark, IconCompare, IconBack, IconShield, IconBolt, IconArrowRight } from '../components/Icons'
import { SkillTag, GapPill } from '../components/widgets'
import { IconRoles } from '../components/Icons'
import { ConfirmModal, ToastRegion, useToast } from '../components/ui'
import MatchBreakdown from '../components/MatchBreakdown'
import { humanizeTopicLabel } from '../lib/topicLabels'

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

export default function SkillsRolesPage({ onNavigate, backTo }: { onNavigate?: Navigate; backTo?: { key: string; label: string } | null }) {
  const { me, applyCopilot } = useApp()
  useEffect(() => {
    applyCopilot({ page: 'skills_roles', skillId: null, competency: null, jobTitle: null, jobUrl: null })
  }, [])
  if (!me) return null
  if (me.entity_type === 'student') return <StudentBrowse student={me.student} analysis={me.analysis ?? undefined} onNavigate={onNavigate} backTo={backTo} />
  if (me.entity_type === 'company') return <CompanyRoles company={me.company} />
  return <ReadOnlyBrowse />
}

function useRoles() {
  const [roles, setRoles] = useState<RoleRecord[]>([])
  const [catalog, setCatalog] = useState<RoleRecord[]>([])
  const [skills, setSkills] = useState<Skill[]>([])
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [roleDataVersion, setRoleDataVersion] = useState<string | null>(null)
  useEffect(() => {
    Promise.all([api.roles(), api.skills()])
      .then(([res, skillsRes]: [RolesResponse, Skill[]]) => {
        setRoles(res.roles || [])
        setCatalog(res.catalog || [])
        setSkills(skillsRes || [])
        setRoleDataVersion(res.role_data_version || null)
        setLoaded(true)
      })
      .catch((e) => { console.error('[roles] load failed:', e); setLoadError(e.message || String(e)) })
  }, [])
  return { roles, setRoles, catalog, skills, loaded, loadError, roleDataVersion }
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

// ---- Phase L role-explorer helpers ----

// Family is an additive real column on roles (Phase D). A role without one is
// honestly grouped under "Unclassified" — never invented.
function roleFamily(r: RoleRecord): string {
  const f = r.family?.trim()
  return f || 'Unclassified'
}

// Provenance label for a role's meta line, derived only from real role data.
// ESCO rows are obvious from `source`; catalogue reference rows from
// `is_reference`; anything else is a company-authored opening.
function sourceProvenance(r: { source?: string; is_reference?: number | boolean; company_name?: string | null }, dest?: string): string {
  if (r.source === 'esco') return 'ESCO import'
  if (r.is_reference || dest === 'catalog') return r.source === 'catalog' ? 'Canonical catalogue' : 'Reference profile'
  return r.company_name || 'Company role'
}

function sourceVersionMeta(r: { source_version?: string | null }): string {
  const v = r.source_version?.trim()
  return v ? ` · v${v}` : ''
}

// Human time-ago for "viewed X minutes ago" honesty (approximate, newest => "just now").
function timeAgo(iso: string): string {
  if (!iso) return 'recently'
  const t = new Date(iso).getTime()
  if (!Number.isFinite(t)) return 'recently'
  const ms = Date.now() - t
  if (ms < 60 * 1000) return 'just now'
  const mins = Math.floor(ms / 60000)
  if (mins < 60) return `${mins} min${mins === 1 ? '' : 's'} ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs} hr${hrs === 1 ? '' : 's'} ago`
  const days = Math.floor(hrs / 24)
  if (days < 30) return `${days} day${days === 1 ? '' : 's'} ago`
  const months = Math.floor(days / 30)
  return `${months} month${months === 1 ? '' : 's'} ago`
}

type ExplorerTab = 'recommended' | 'all' | 'saved' | 'market' | 'recents'

const EXPLORER_KEYS: Record<string, ExplorerTab> = {
  recommended: 'recommended', all: 'all', saved: 'saved', market: 'market', recents: 'recents',
}

// Phase L recently-viewed row: an honest, compact view record joined to the
// role's current title/company. Actions resolve the full RoleRecord from the
// already-loaded library; the row alone never pretends to be a live role.
function RecentRoleRow({ rr, role, saved, cmp, onDetails, onToggleSave, onSelect, onCompare }: {
  rr: RecentRole
  role?: RoleRecord
  saved: boolean
  cmp: boolean
  onDetails: () => void
  onToggleSave: () => void
  onSelect: () => void
  onCompare: () => void
}) {
  const enabled = role !== undefined
  return (
    <div className="srb-recent-row">
      <div className="srb-recent-main">
        <button type="button" className="srb-recent-title" onClick={onDetails}>{rr.title}</button>
        <p className="srb-role-meta">
          {sourceProvenance(rr, role && role.is_reference ? 'catalog' : undefined)}{sourceVersionMeta(rr)}
          {rr.company_name ? ` · ${rr.company_name}` : ''}
          {rr.family ? ` · ${rr.family}` : ''}
        </p>
      </div>
      <span className="srb-recent-when">{timeAgo(rr.viewed_at)}</span>
      <div className="srb-recent-actions">
        <button type="button" className={`srb-recent-act srb-save-btn ${saved ? 'on' : ''}`} disabled={!enabled} onClick={onToggleSave}>{saved ? 'Saved' : 'Save'}</button>
        <button type="button" className={`srb-recent-act ${cmp ? 'on' : ''}`} disabled={!enabled} onClick={onCompare}>{cmp ? 'In compare' : 'Compare'}</button>
        <button type="button" className="srb-recent-act" disabled={!enabled} onClick={onSelect}>Set target</button>
        <button type="button" className="srb-recent-act" onClick={onDetails}>Details</button>
      </div>
    </div>
  )
}

// URL/deep-link state for the explorer (Phase L): an additive, hash-based
// query the page reads on mount and re-applies on back/forward. Only strings
// that are correct today carry weight; malformed input is ignored, never a crash.
function parseExplorerHash(hash: string): { tab?: ExplorerTab; q?: string; fam?: string[] } {
  const out: { tab?: ExplorerTab; q?: string; fam?: string[] } = {}
  if (!hash || !hash.startsWith('#explorer')) return out
  const params = new URLSearchParams(hash.slice('#explorer'.length))
  const t = params.get('t')
  if (t && EXPLORER_KEYS[t]) out.tab = EXPLORER_KEYS[t]
  const q = params.get('q')
  if (q != null) out.q = q
  const fam = params.get('fam')
  if (fam) out.fam = fam.split(',').map((s) => s.trim()).filter(Boolean)
  return out
}

function serializeExplorer(tab: ExplorerTab, q: string, fam: string[]): string {
  const p = new URLSearchParams()
  if (tab !== 'recommended') p.set('t', tab)
  if (q) p.set('q', q)
  if (fam.length) p.set('fam', fam.join(','))
  const s = p.toString()
  return s ? `#explorer?${s}` : '#explorer'
}

type ExplorerFilters = { location: string[]; level: string[]; category: string[]; skill: string[]; family: string[] }

function matchPctOf(r: RoleRecord, cvSkillNames: string[]): number {
  if (r.required_skills.length === 0) return 0
  const present = r.required_skills.reduce((n, s) => n + (cvSkillNames.includes(s.name.toLowerCase().trim()) ? 1 : 0), 0)
  return Math.round((present / r.required_skills.length) * 100)
}

// ---- Phase 2 discovery helpers ----

// Single source of truth for "how well does this student match this role?".
// Prefers the backend recommendations payload (a real computed match score +
// reason text) whenever the role appears there; otherwise falls back to the
// same required-skill overlap math the backend uses. Every surface (cards,
// drawer and compare) reads this helper so a role always shows one match.
export interface RoleMatchInfo { pct: number | null; reason?: string; confidence?: string }

function backendRecMap(recs: RoleRecommendationsResponse | null): Map<number, RoleRecommendation> {
  const m = new Map<number, RoleRecommendation>()
  if (!recs) return m
  for (const r of recs.recommendations) if (r.role_id != null) m.set(r.role_id, r)
  return m
}

function displayMatchOf(role: RoleRecord, cvSkillNames: string[], recByRole: Map<number, RoleRecommendation>): RoleMatchInfo {
  const rec = recByRole.get(role.id)
  if (rec && rec.match_score != null) {
    return { pct: Math.round(rec.match_score), reason: rec.reason, confidence: rec.confidence }
  }
  return { pct: cvSkillNames.length > 0 ? matchPctOf(role, cvSkillNames) : null }
}

function roleSourceLabel(r: RoleRecord): string {
  if (r.company_id && r.source !== 'catalog') return 'Company'
  if (r.source === 'esco') return 'ESCO'
  return 'Catalog'
}

// Stable display deduplication rule (Phase 2): the same logical role can come
// from several sources (company posting, ESCO occupation, catalog reference).
// Records are NEVER deleted. Within any single list we render ONE
// representative per normalized-title group, chosen by: current target >
// saved > source priority (company > esco > catalog) > richer description.
// The other group members stay reachable in the role-detail drawer as "other
// sources / relevant jobs".
function normalizedTitle(title: string): string {
  return String(title || '').toLowerCase().replace(/\s+/g, ' ').trim()
}

function sourcePriority(r: RoleRecord): number {
  if (r.company_id && r.source !== 'catalog') return 0 // real company posting
  if (r.source === 'esco') return 1                      // ESCO occupation
  return 2                                                // catalog reference
}

function pickRepresentative(members: RoleRecord[], targetId: number | null, savedIds: Set<number>): RoleRecord {
  const scored = members.map((r) => ({
    r,
    score:
      (targetId != null && r.id === targetId ? 0 : 4) +  // current target wins
      (savedIds.has(r.id) ? 0 : 2) +                     // then saved
      sourcePriority(r) +                                // then source priority
      (r.description ? 0 : 0.5),                         // then richer description
  }))
  scored.sort((a, b) => (a.score - b.score) || a.r.title.localeCompare(b.r.title))
  return scored[0].r
}

function dedupDisplay(roles: RoleRecord[], targetId: number | null, savedIds: Set<number>): { groups: Map<string, RoleRecord[]>; reps: RoleRecord[] } {
  const groups = new Map<string, RoleRecord[]>()
  for (const r of roles) {
    const k = normalizedTitle(r.title)
    if (!groups.has(k)) groups.set(k, [])
    groups.get(k)!.push(r)
  }
  const reps = [...groups.values()].map((members) => pickRepresentative(members, targetId, savedIds))
  return { groups, reps }
}

// A target job is only applied after the user confirms a replacement; the
// actual API call lives in a single runner so every entry point (library card,
// drawer, recommendation, ESCO market row) behaves identically.
type PendingTarget =
  | { kind: 'role'; id: number }
  | { kind: 'esco'; occ: EscoOccupation }
  | { kind: 'rec'; rec: RoleRecommendation }

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
            {humanizeTopicLabel(c.name)} <span className="lv">{c.level}</span>
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
function RecommendationCard({ rec, selected, onSelect, busy, saved, onToggleSave, studentId }: {
  rec: RoleRecommendation; selected: boolean; onSelect: () => void; busy: boolean; saved: boolean; onToggleSave: () => void; studentId?: number
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
{humanizeTopicLabel(m.name)}
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
      {studentId != null && (
        <MatchBreakdown kind="role" pct={rec.match_score}
          onRequest={() => api.roleMatchBreakdown(studentId, rec.role_id, rec.external_id)} />
      )}
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

function RoleLibraryCard({ r, pct, selected, dest, chips, statusCounts, noCvSkills, saved, cmp, onCompare, onSelect, onDetails, onToggleSave }: {
  r: RoleRecord
  pct: number
  selected: boolean
  dest?: string
  chips?: SkillChip[]
  statusCounts: { have: number; developing: number; missing: number }
  noCvSkills: boolean
  saved: boolean
  cmp?: boolean
  onCompare?: () => void
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
            {sourceProvenance(r, dest)}{sourceVersionMeta(r)}
            {loc ? ` · ${loc}` : noCvSkills ? ' · Remote' : ' · Not specified'}
            {` · ${roleExperience(r)}`}
          </p>
        </div>
        <MatchRing pct={noCvSkills ? null : pct} size={72} />
      </header>
      {r.description && <p className="srb-role-desc">{r.description.length > 140 ? `${r.description.slice(0, 137)}…` : r.description}</p>}
      {noCvSkills ? (
        <div className="srb-chiprow">
          {r.required_skills.slice(0, 5).map((s) => <span className="skill-tag" key={s.name}>{humanizeTopicLabel(s.name)}</span>)}
          {r.required_skills.length > 5 && <span className="muted small">+{r.required_skills.length - 5} more</span>}
        </div>
      ) : (
        <>
          <div className="srb-chiprow">
            {shown.map((c) => <span className={`srb-schip ${c.matched ? 'have' : ''}`} key={c.name}>{humanizeTopicLabel(c.name)}{c.matched ? ' ✓' : ''}</span>)}
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
        {cmp != null && onCompare && (
          <button type="button" className={`srb-save-btn rd-cmp-toggle ${cmp ? 'on' : ''}`} onClick={onCompare}
            aria-pressed={cmp} title={cmp ? 'Remove from compare' : 'Add to compare'}>
            <IconCompare size={13} /> <span>{cmp ? 'In compare' : 'Compare'}</span>
          </button>
        )}
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
                <span className="srb-skill-name">{humanizeTopicLabel(s.name)} <small>{s.required_level}</small></span>
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
                  Learn {humanizeTopicLabel(s.name)}
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

// ------------------------------------------------------------------ Role detail drawer (Phase 2)
// Replaces the old modal: a right-side drawer with source, match explanation,
// covered/missing skills, honest effort + scenario + relevant-jobs blocks.
function RoleDetailsDrawer({ role, others, match, noCvSkills, profileByName, evidence, selected, busy, saved, inCompare, scenarioNote, provenance, provenanceState, onOpenRole, jobsFeed, jobsFeedState, onClose, onSelect, onToggleSave, onCompare, onLearn, onVerifySkill, onPracticeRole, practiceEnabled, recommendedSkillId, recommendedSkillName }: {
  role: RoleRecord
  others: RoleRecord[]
  match: RoleMatchInfo
  noCvSkills: boolean
  profileByName: Map<string, string>
  evidence: { verified: Set<string>; self: Set<string> }
  selected: boolean
  busy: boolean
  saved: boolean
  inCompare: boolean
  scenarioNote: string | null
  provenance: RoleProvenance | null
  provenanceState: 'idle' | 'loading' | 'ready' | 'error'
  onOpenRole: (role: RoleRecord) => void
  jobsFeed: RecentJobsResponse | null
  jobsFeedState: 'idle' | 'loading' | 'ready' | 'nocv'
  onClose: () => void
  onSelect: () => void
  onToggleSave: () => void
  onCompare: () => void
  onLearn: (skillId: number) => void
  onVerifySkill: (skillId: number) => void
  onPracticeRole: () => void
  practiceEnabled: boolean
  recommendedSkillId: number | null
  recommendedSkillName: string | null
}) {
  const evidenceOf = (name: string) => {
    const n = (name || '').toLowerCase().trim()
    if (evidence.verified.has(n)) return 'verified'
    if (evidence.self.has(n)) return 'self'
    return 'none'
  }
  const rows = role.required_skills.map((s) => ({ s, status: statusOfSkill(s, profileByName), ev: evidenceOf(s.name) }))
  const learningGaps = rows.filter((x) => x.status !== 'have')
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
  const srcLabel = roleSourceLabel(role)
  const srcChip = srcLabel === 'Company' ? 'chip-company' : srcLabel === 'ESCO' ? 'chip-esco' : 'chip-catalog'
  const otherSrcLabel = (r: RoleRecord) =>
    r.company_id && r.source !== 'catalog' ? `Company posting · ${r.company_name || 'company'}`
      : r.source === 'esco' ? 'Labour-market occupation (ESCO)'
      : 'Reference profile'
  const ver = (r: RoleRecord) => sourceVersionMeta(r) ? ` · v${r.source_version}` : ''
  const hasKinds = role.required_skills.some((s) => s.skill_kind === 'essential' || s.skill_kind === 'optional')
  const essRows = rows.filter((x) => x.s.skill_kind === 'essential')
  const optRows = rows.filter((x) => x.s.skill_kind === 'optional')
  const skillList = (title: string, items: typeof rows) => (
    <div className="srb-modal-section">
      <h4>{title}</h4>
      <ul className="srb-skill-list">
        {items.map(({ s, status, ev }) => (
          <li key={s.name} className={`srb-skill ${status}`}>
            <span className="srb-dot" aria-hidden="true" />
            <span className="srb-skill-name">{humanizeTopicLabel(s.name)} <small>{s.required_level}</small>{s.skill_kind === 'optional' && <small className="rd-kind">optional</small>}</span>
            <span className={`rd-ev ${ev}`}>{ev === 'verified' ? 'verified' : ev === 'self' ? 'self-report' : 'no evidence'}</span>
            <span className="srb-skill-state">
              {status === 'have' ? '✓ you have this' : status === 'developing' ? '⚠ leveling up' : '○ missing'}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
  const coveredVerified = rows.filter((x) => x.status === 'have' && x.ev === 'verified').length
  const coveredSelf = rows.filter((x) => x.status === 'have' && x.ev === 'self').length
  const missingCount = rows.filter((x) => x.status === 'missing').length
  const developingCount = rows.filter((x) => x.status === 'developing').length
  const relGroups: [string, RoleRecord[]][] = [
    ['Parent career', provenance?.related?.parent ? [provenance.related.parent] : []],
    ['Specialisations', provenance?.related?.children ?? []],
    ['Family peers', provenance?.related?.siblings ?? []],
    ['Replaces', provenance?.related?.supersedes ?? []],
    ['Replaced by', provenance?.related?.superseded_by ? [provenance.related.superseded_by] : []],
  ]
  const relHasAny = relGroups.some(([, list]) => list.length > 0)
  const relevantJobs = (jobsFeed?.jobs ?? []).filter((j) => {
    const unique = new Set<string>(
      [role.title, role.family || '', ...role.required_skills.map((s) => s.name)]
        .map((x) => String(x || '').toLowerCase().split(/[^a-z0-9]+/))
        .flat()
        .filter(Boolean),
    )
    return String(j.title || '').toLowerCase().split(/[^a-z0-9]+/).some((t) => unique.has(t))
  })
  const deprecated = role.canonical_status && role.canonical_status !== 'active'
  const aliases = (provenance?.aliases ?? []).filter((a) => a.alias_type !== 'hidden').map((a) => a.alias)
  return (
    <div className="rd-backdrop" onClick={onClose}>
      <aside className="rd-drawer" role="dialog" aria-modal="true" aria-label={role.title} onClick={(e) => e.stopPropagation()}>
        <header className="rd-drawer-head">
          <div>
            <span className={`chip ${srcChip}`}>{srcLabel}</span>
            <h3>{role.title}</h3>
            <p className="srb-role-meta">
              {role.company_name || (role.source === 'esco' ? 'Labour-market occupation' : 'Reference profile')}
              {loc ? ` · ${loc}` : ''}
              {` · ${roleExperience(role)}`}
              {` · ${roleCategory(role)}`}
              {sourceVersionMeta(role) ? ` · v${role.source_version}` : ''}
            </p>
            {aliases.length > 0 && <p className="srb-role-meta rd-aliases">Also known as: {aliases.join(' · ')}</p>}
          </div>
          <button type="button" className="srb-close" aria-label="Close details" ref={closeRef} onClick={onClose}>✕</button>
        </header>
        {deprecated && (
          <p className="rd-deprecated" role="note">
            This role is {role.canonical_status}
            {provenance?.related?.superseded_by ? ` — superseded by "${provenance.related.superseded_by.title}".` : '.'}
            {' '}Deprecated roles never appear among career-transition suggestions.
          </p>
        )}
        {role.description && <p className="rd-drawer-desc">{role.description}</p>}
        <div className="srb-modal-match">
          <MatchRing pct={noCvSkills ? null : (match.pct ?? null)} size={92} />
          <div>
            <p className="srb-eyebrow">Skill match</p>
            {noCvSkills
              ? <p className="small muted">Upload a CV to measure your match against this role.</p>
              : <>
                  <p className="small muted">{match.reason || `${rows.length - learningGaps.length} of ${rows.length} required skills are on your profile. Verified skills outrank self-reported ones.`}</p>
                  <p className="small muted rd-ev-legend">Verified-covered {coveredVerified} · self-reported-covered {coveredSelf} · missing {missingCount}{developingCount > 0 ? ` · leveling up ${developingCount}` : ''}</p>
                </>}
          </div>
        </div>
        {hasKinds ? skillList('Essential skills', essRows) : skillList('Required skills', rows)}
        {hasKinds && optRows.length > 0 && skillList('Optional skills', optRows)}
        {!noCvSkills && learningGaps.length > 0 && (
          <div className="srb-modal-section">
            <h4>Estimated learning effort</h4>
            <p className="small muted">{learningGaps.length} skill{learningGaps.length > 1 ? 's' : ''} stand between your profile and this role. Start with the most relevant one on your Learning page — no time estimate is invented here.</p>
            <div className="srb-learn-row">
              {learningGaps.slice(0, 6).map(({ s }) => (
                <button type="button" className="btn btn-sm srb-btn-outline" key={s.name}
                  onClick={() => s.skill_id ? onLearn(s.skill_id) : undefined}
                  disabled={!s.skill_id}>
                  Learn {humanizeTopicLabel(s.name)}
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="srb-modal-section">
          <h4>Practice scenarios</h4>
          <p className="small muted">{scenarioNote || 'No practice scenarios are shown for a role that is not your target career. Set this role as your target to unlock the scenarios written for it.'}</p>
        </div>
        <div className="srb-modal-section">
          <h4>Related roles &amp; career moves</h4>
          {provenanceState === 'loading' && <p className="small muted">Loading maintained relationships…</p>}
          {provenanceState === 'error' && <p className="small muted">Related roles are unavailable right now.</p>}
          {provenanceState === 'ready' && provenance && !relHasAny && (
            <p className="small muted rd-related-none">No maintained relationships exist for this role yet.</p>
          )}
          {provenanceState === 'ready' && provenance && relHasAny && (
            <>
              <div className="rd-related">
                {relGroups.map(([label, list]) => list.length === 0 ? null : (
                  <div className="rd-related-group" key={label}>
                    <span className="rd-related-label">{label}</span>
                    <div className="rd-related-rows">
                      {list.map((r) => (
                        <button type="button" className="rd-related-row" key={r.id} onClick={() => onOpenRole(r)}>
                          <span className="rd-related-title">{r.title}{ver(r)}</span>
                          <span className={`chip ${roleSourceLabel(r) === 'Company' ? 'chip-company' : roleSourceLabel(r) === 'ESCO' ? 'chip-esco' : 'chip-catalog'}`}>{roleSourceLabel(r)}</span>
                          {r.canonical_status && r.canonical_status !== 'active' && <span className="rd-rel-dep">deprecated</span>}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              <p className="small muted">Shown only where a maintained relationship exists between roles. Deprecated roles never appear among the suggestions. No salaries, probabilities, or timing are ever invented.</p>
            </>
          )}
        </div>
        <div className="srb-modal-section">
          <h4>Available jobs for this role</h4>
          {jobsFeedState === 'loading' && <p className="small muted">Checking your live job feed…</p>}
          {jobsFeedState === 'nocv' && <p className="small muted">Upload a CV to see live listings relevant to this role.</p>}
          {jobsFeedState === 'ready' && jobsFeed && relevantJobs.length === 0 && (
            <p className="small muted">No current listings overlap this role.</p>
          )}
          {jobsFeedState === 'ready' && jobsFeed && relevantJobs.length > 0 && (
            <>
              <ul className="rd-jobs">
                {relevantJobs.slice(0, 6).map((j) => (
                  <li className="rd-job" key={j.fingerprint ?? `${j.title}-${j.company}`}>
                    <div className="rd-job-head">
                      <span className="rd-job-title">{j.title}</span>
                      <span className="rd-job-co">{j.company}{j.location ? ` · ${j.location}` : ''}</span>
                    </div>
                    <div className="rd-job-meta">
                      <span className={`rd-ls ${j.listing_status === 'expired' ? 'rd-ls-expired' : 'rd-ls-live'}`}>{j.listing_status || 'live'}</span>
                      {j.provider && <span className="rd-provider">{j.provider}</span>}
                      {j.listed_days_ago != null && <span className="muted small">{j.listed_days_ago === 0 ? 'listed today' : `${j.listed_days_ago} day${j.listed_days_ago === 1 ? '' : 's'} ago`}</span>}
                      {j.match_pct != null && <span className="muted small">match {j.match_pct}%</span>}
                    </div>
                    {j.url && <a className="rd-job-link" href={j.url} target="_blank" rel="noopener noreferrer">View listing</a>}
                  </li>
                ))}
              </ul>
              <p className="small muted">Sourced from your student job feed with each listing's real provider and freshness state — never fabricated. Open the Dashboard to refresh it.</p>
            </>
          )}
        </div>
        {others.length > 0 && (
          <div className="srb-modal-section">
            <h4>Other sources &amp; relevant jobs for this role</h4>
            <ul className="rd-others">
              {others.map((o) => (
                <li key={o.id}>
                  <span className="srb-skill-name">{o.title} <small>{otherSrcLabel(o)}</small></span>
                  <span className="muted small">{o.company_location ? `${o.company_location} · ` : ''}{roleExperience(o)}</span>
                </li>
              ))}
            </ul>
            <p className="small muted">These are the same logical role seen through other sources — deduplicated here, never deleted. No salary or market figures are shown because none exist for these records.</p>
          </div>
        )}
        <div className="rd-actions-row">
          <button type="button" className="btn btn-sm btn-primary"
            disabled={!recommendedSkillId}
            title={recommendedSkillId ? undefined : 'No learnable skill identified for this role yet'}
            onClick={() => recommendedSkillId && onLearn(recommendedSkillId)}>
            Start learning <IconArrowRight size={13} />
          </button>
          <button type="button" className="btn btn-sm"
            disabled={!recommendedSkillId}
            title={recommendedSkillId ? undefined : 'No assessable skill identified for this role yet'}
            onClick={() => recommendedSkillId && onVerifySkill(recommendedSkillId)}>
            <IconShield size={13} /> Verify a Skill
          </button>
          <button type="button" className="btn btn-sm"
            disabled={!practiceEnabled}
            title={practiceEnabled ? undefined : 'Set this role as your target to unlock the scenarios written for it.'}
            onClick={onPracticeRole}>
            <IconBolt size={13} /> Practice this role
          </button>
        </div>
        <footer className="srb-modal-foot">
          <button type="button" className={`srb-save-btn ${saved ? 'on' : ''}`} onClick={onToggleSave}
            aria-pressed={saved}>
            <IconBookmark size={15} /> <span>{saved ? 'Saved' : 'Save role'}</span>
          </button>
          <button type="button" className={`srb-save-btn rd-cmp-toggle ${inCompare ? 'on' : ''}`} onClick={onCompare}
            aria-pressed={inCompare}>
            <IconCompare size={15} /> <span>{inCompare ? 'In compare' : 'Compare'}</span>
          </button>
          <button type="button" className="btn btn-sm srb-btn-outline" onClick={onClose}>Close</button>
          <button type="button" className="btn btn-sm btn-primary" onClick={onSelect} disabled={selected || busy}>
            {selected ? '✓ Target Career' : busy ? 'Selecting…' : 'Select as target'}
          </button>
        </footer>
      </aside>
    </div>
  )
}

// Fixed bottom tray listing the roles queued for comparison (max 3).
function CompareTray({ roles, open, onRemove, onClear }: {
  roles: { id: number; title: string; sourceLabel: string }[]
  open: () => void
  onRemove: (id: number) => void
  onClear: () => void
}) {
  if (roles.length === 0) return null
  return (
    <div className="rd-cmpbar" role="region" aria-label="Roles queued for comparison">
      <div className="rd-cmpbar-count"><IconCompare size={15} /> Compare ({roles.length}/3)</div>
      <div className="rd-cmpbar-items">
        {roles.map((r) => (
          <span className="rd-cmpbar-chip" key={r.id}>
            {r.title} <span className="rd-cmpbar-src">{r.sourceLabel}</span>
            <button type="button" aria-label={`Remove ${r.title} from compare`} onClick={() => onRemove(r.id)}>✕</button>
          </span>
        ))}
      </div>
      <div className="rd-cmpbar-actions">
        <button type="button" className="btn btn-sm srb-btn-outline" onClick={onClear}>Clear</button>
        <button type="button" className="btn btn-sm btn-primary" onClick={open}>Compare now</button>
      </div>
    </div>
  )
}

// Side-by-side comparison of up to three roles. Compares match, covered skills,
// gaps, difficulty, scenario availability, shared/unique skills and live-job
// coverage only — salary/market figures are never invented or shown.
function CompareModal({ roles, matches, profileByName, evidence, scenarioNoteFor, jobCountFor, savedFor, busy, onClose, onRemove, onSelect, onSave, onLearn }: {
  roles: RoleRecord[]
  matches: RoleMatchInfo[]
  profileByName: Map<string, string>
  evidence: { verified: Set<string>; self: Set<string> }
  scenarioNoteFor: (roleId: number) => string
  jobCountFor: (roleId: number) => number | null
  savedFor: (id: number) => boolean
  busy: boolean
  onClose: () => void
  onRemove: (id: number) => void
  onSelect: (r: RoleRecord) => void
  onSave: (id: number) => void
  onLearn: (skillId: number) => void
}) {
  const nameSets = roles.map((r) => new Set(r.required_skills.map((s) => s.name.toLowerCase().trim())))
  const shared = roles.length > 0 ? [...nameSets[0]!].filter((n) => nameSets.every((s) => s.has(n))) : []
  const uniquePer = roles.map((r, i) =>
    [...nameSets[i]!].filter((n) => nameSets.some((s, j) => j !== i && s.has(n)) === false))
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
  return (
    <div className="rd-backdrop" onClick={onClose}>
      <div className="rd-cmp-modal" role="dialog" aria-modal="true" aria-label="Compare roles"
        style={{ '--cols': roles.length } as React.CSSProperties} onClick={(e) => e.stopPropagation()}>
        <header className="rd-drawer-head">
          <div>
            <p className="srb-eyebrow">Compare mode</p>
            <h3>{roles.length} roles, side by side</h3>
          </div>
          <button type="button" className="srb-close" aria-label="Close compare" ref={closeRef} onClick={onClose}>✕</button>
        </header>
        <p className="small muted rd-cmp-note">Skill match, covered skills, gaps, difficulty and practice-scenario availability. Salary and market figures are never shown because no honest source exists for them.</p>
        <div className="rd-cmp-grid">
          <div className="rd-cmp-row rd-cmp-head">
            <span className="rd-cmp-label" />
            {roles.map((r) => (
              <span className="rd-cmp-cell rd-cmp-rtitle" key={r.id}>
                <span className={`chip ${roleSourceLabel(r) === 'Company' ? 'chip-company' : roleSourceLabel(r) === 'ESCO' ? 'chip-esco' : 'chip-catalog'}`}>{roleSourceLabel(r)}</span>
                {r.title}
                <button type="button" className="rd-cmp-x" aria-label={`Remove ${r.title} from compare`} onClick={() => onRemove(r.id)}>✕</button>
              </span>
            ))}
          </div>
          <div className="rd-cmp-row">
            <span className="rd-cmp-label">Skill match</span>
            {roles.map((r, i) => (
              <span className="rd-cmp-cell rd-cmp-match" key={r.id}>
                <strong>{matches[i]?.pct != null ? `${matches[i]!.pct}%` : '—'}</strong>
                {matches[i]?.confidence && <span className="rd-cmp-names">{matches[i]!.confidence}</span>}
              </span>
            ))}
          </div>
          <div className="rd-cmp-row">
            <span className="rd-cmp-label">Difficulty</span>
            {roles.map((r) => (
              <span className="rd-cmp-cell" key={r.id}>{roleExperience(r)}</span>
            ))}
          </div>
          <div className="rd-cmp-row">
            <span className="rd-cmp-label">Covered skills</span>
            {roles.map((r) => {
              const have = r.required_skills.filter((s) => statusOfSkill(s, profileByName) === 'have')
              const verified = have.filter((s) => evidence.verified.has(s.name.toLowerCase().trim())).length
              const self = have.length - verified
              return (
                <span className="rd-cmp-cell" key={r.id}>
                  <strong>{have.length} of {r.required_skills.length}</strong>
                  <span className="rd-cmp-names">{verified} verified · {self} self-reported</span>
                  {have.length > 0 && <span className="rd-cmp-names">{have.slice(0, 6).map((s) => humanizeTopicLabel(s.name)).join(' · ')}{have.length > 6 ? '…' : ''}</span>}
                </span>
              )
            })}
          </div>
          <div className="rd-cmp-row">
            <span className="rd-cmp-label">Shared skills</span>
            {roles.map((r) => (
              <span className="rd-cmp-cell" key={r.id}>
                {shared.length === 0 ? <span className="rd-cmp-names">None</span>
                  : <><strong>{shared.length} core</strong><span className="rd-cmp-names">{shared.slice(0, 8).join(' · ')}{shared.length > 8 ? '…' : ''}</span></>}
              </span>
            ))}
          </div>
          {roles.map((r, i) => (
            <div className="rd-cmp-row" key={`uniq-${r.id}`}>
              <span className="rd-cmp-label">Unique to {r.title}</span>
              {roles.map((c) => (
                <span className="rd-cmp-cell" key={c.id}>
                  {c.id === r.id
                    ? (uniquePer[i]?.length === 0 ? <span className="rd-cmp-names">None</span>
                        : <><strong>{uniquePer[i]!.length}</strong><span className="rd-cmp-names">{uniquePer[i]!.slice(0, 6).join(' · ')}{uniquePer[i]!.length > 6 ? '…' : ''}</span></>)
                    : <span className="rd-cmp-names">—</span>}
                </span>
              ))}
            </div>
          ))}
          <div className="rd-cmp-row">
            <span className="rd-cmp-label">Skill gaps</span>
            {roles.map((r) => {
              const gaps = r.required_skills.filter((s) => statusOfSkill(s, profileByName) !== 'have')
              return (
                <span className="rd-cmp-cell" key={r.id}>
                  {gaps.length === 0 ? <span className="rd-cmp-names">None</span>
                    : <><strong>{gaps.length} to develop</strong><span className="rd-cmp-names">{gaps.slice(0, 5).map((s) => humanizeTopicLabel(s.name)).join(' · ')}{gaps.length > 5 ? '…' : ''}</span></>}
                </span>
              )
            })}
          </div>
          <div className="rd-cmp-row">
            <span className="rd-cmp-label">Practice scenarios</span>
            {roles.map((r) => (
              <span className="rd-cmp-cell" key={r.id}>{scenarioNoteFor(r.id)}</span>
            ))}
          </div>
          <div className="rd-cmp-row">
            <span className="rd-cmp-label">Live jobs</span>
            {roles.map((r) => {
              const n = jobCountFor(r.id)
              return (
                <span className="rd-cmp-cell" key={r.id}>
                  {n === null ? <span className="rd-cmp-names">—</span>
                    : n === 0 ? <span className="rd-cmp-names">None in your feed</span>
                    : <><strong>{n}</strong><span className="rd-cmp-names">in your feed</span></>}
                </span>
              )
            })}
          </div>
        </div>
        <div className="rd-cmp-actions">
          {roles.map((r) => {
            const firstGap = r.required_skills.find((s) => statusOfSkill(s, profileByName) !== 'have' && s.skill_id)
            return (
              <div className="rd-cmp-actions-col" key={r.id}>
                <strong>{r.title}</strong>
                <button type="button" className={`srb-save-btn ${savedFor(r.id) ? 'on' : ''}`} onClick={() => onSave(r.id)}
                  aria-pressed={savedFor(r.id)}>
                  <IconBookmark size={14} /> {savedFor(r.id) ? 'Saved' : 'Save'}
                </button>
                <button type="button" className="btn btn-sm srb-btn-outline"
                  onClick={() => firstGap?.skill_id && onLearn(firstGap.skill_id)} disabled={!firstGap?.skill_id}>
                  Start learning
                </button>
                <button type="button" className="btn btn-sm btn-primary" onClick={() => onSelect(r)} disabled={busy}>
                  Select as target
                </button>
              </div>
            )
          })}
        </div>
        <footer className="srb-modal-foot">
          <button type="button" className="btn btn-sm" onClick={onClose}>Close</button>
        </footer>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ Student browse
function StudentBrowse({ student, analysis, onNavigate, backTo }: { student?: Student; analysis?: Analysis; onNavigate?: Navigate; backTo?: { key: string; label: string } | null }) {
  const { refreshStudent, me } = useApp()
  const { roles, catalog, loaded, loadError, roleDataVersion } = useRoles()
  // Phase L deep-link: read #explorer once at mount, apply back/forward on hashchange.
  const initialExplorer = useMemo(() => parseExplorerHash(window.location.hash), [])
  const [q, setQ] = useState(initialExplorer.q ?? '')
  const [qDraft, setQDraft] = useState(initialExplorer.q ?? '')
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
  const [filters, setFilters] = useState<ExplorerFilters>({
    location: [],
    level: [],
    category: [],
    skill: [],
    family: initialExplorer.fam ?? [],
  })
  const [detailsRole, setDetailsRole] = useState<RoleRecord | null>(null)
  const [detailsBusy, setDetailsBusy] = useState(false)
  const [savedIds, setSavedIds] = useState<Set<number>>(new Set())
  const [savedOnly, setSavedOnly] = useState(false)
  // Phase 2 discovery state: top-level views, pagination, compare, target confirm.
  const [tab, setTab] = useState<ExplorerTab>(initialExplorer.tab ?? 'recommended')
  const [page, setPage] = useState(1)
  const pageSize = 12
  const [compareIds, setCompareIds] = useState<number[]>([])
  const [showCompare, setShowCompare] = useState(false)
  const [matchRange, setMatchRange] = useState<{ min: number | null; max: number | null }>({ min: null, max: null })
  const [pendingTarget, setPendingTarget] = useState<PendingTarget | null>(null)
  const [targetBusy, setTargetBusy] = useState(false)
  const [drawerScenarios, setDrawerScenarios] = useState<string | null>(null)
  // Phase L recently-viewed state (fetched when the recents tab is active).
  const [recentRoles, setRecentRoles] = useState<RecentRole[]>([])
  const [recentErr, setRecentErr] = useState('')
  const [recentLoaded, setRecentLoaded] = useState(false)
  // Phase L keyboard highlight index over the All Roles grid (arrow keys).
  const [hlIndex, setHlIndex] = useState(-1)
  const toast = useToast()

  // Phase L debounce: the input reflects keystrokes immediately (qDraft), the
  // applied filter (q) follows 150 ms later so typing never lags the UI.
  useEffect(() => {
    const t = window.setTimeout(() => setQ(qDraft), 150)
    return () => window.clearTimeout(t)
  }, [qDraft])

  // Phase L deep-link: keep the hash in sync silently (replaceState fires no
  // hashchange, so this cannot loop with the back/forward listener below).
  useEffect(() => {
    const hash = serializeExplorer(tab, q, filters.family)
    if (window.location.hash !== hash) window.history.replaceState(null, '', hash)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, q, filters.family])

  useEffect(() => {
    const onHash = () => {
      const h = parseExplorerHash(window.location.hash)
      if (h.tab) setTab(h.tab)
      if (h.q != null) { setQ(h.q); setQDraft(h.q) }
      if (h.fam) setFilters((f) => ({ ...f, family: h.fam! }))
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    if (!student) return
    api.savedRoles(student.id)
      .then((res: SavedRolesResponse) => setSavedIds(new Set(res.role_ids || [])))
      .catch((e) => console.error('[roles] saved roles failed:', e))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [student?.id])

  // Phase L recently-viewed: fetched when the recents tab is active (guard so
  // the student id is never used unset during the async profile load).
  const loadRecents = useCallback(() => {
    if (!student) return
    setRecentLoaded(false)
    api.recentRoles(student.id)
      .then((res) => { setRecentRoles(res.roles || []); setRecentErr(''); setRecentLoaded(true) })
      .catch((e) => { setRecentErr(e.message || String(e)); setRecentLoaded(true) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [student?.id])
  useEffect(() => { if (tab === 'recents') loadRecents() }, [tab, loadRecents])

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

  // Phase M: evidence separation stays data-driven — verified and self-reported
  // name sets come only from the student profile payload, never invented.
  const evidence = useMemo(() => {
    const verified = new Set<string>()
    for (const s of student?.verified_skills ?? []) verified.add(s.name.toLowerCase().trim())
    const self = new Set<string>()
    for (const s of student?.self_reported_skills ?? []) self.add(s.name.toLowerCase().trim())
    return { verified, self }
  }, [student])

  // Phase M: related role graph for the OPEN role (read-only provenance fetch).
  const [provenance, setProvenance] = useState<RoleProvenance | null>(null)
  const [provState, setProvState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')
  useEffect(() => {
    if (!detailsRole) { setProvenance(null); setProvState('idle'); return }
    let live = true
    setProvState('loading')
    setProvenance(null)
    api.roleProvenance(detailsRole.id)
      .then((p: RoleProvenance) => { if (live) { setProvenance(p); setProvState('ready') } })
      .catch(() => { if (live) setProvState('error') })
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detailsRole?.id])

  // Phase M: available-jobs section surfaces the student's existing profile-keyed
  // job feed (the same cache the Dashboard builds), fetched ONCE per view so no
  // repeated drawer opens can re-trigger a provider build.
  const [jobsFeed, setJobsFeed] = useState<RecentJobsResponse | null>(null)
  const [jobsFeedState, setJobsFeedState] = useState<'idle' | 'loading' | 'ready' | 'nocv'>('idle')
  const jobsFeedFired = useRef(false)
  useEffect(() => {
    if (jobsFeedFired.current || !student || !me) return
    jobsFeedFired.current = true
    if (noCvSkills) { setJobsFeedState('nocv'); return }
    setJobsFeedState('loading')
    const st = student as unknown as Record<string, unknown>
    api.recentJobs({
      location: (st.location as string) || (me.location as string | undefined) || '',
      country: (st.country as string) || (me.country as string | undefined) || '',
      market: marketCountry,
    })
      .then((r: RecentJobsResponse) => { setJobsFeed(r); setJobsFeedState('ready') })
      .catch(() => { setJobsFeedState('ready') })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [student, me, noCvSkills])

  // Count of relevant feed listings per role for the compare "Live jobs" row
  // (null while the feed is idle/loading/unavailable — never a fabricated 0).
  const jobCountFor = useCallback((roleId: number): number | null => {
    if (jobsFeedState !== 'ready' || !jobsFeed) return null
    const role = all.find((r) => r.id === roleId)
    if (!role) return null
    const unique = new Set<string>(
      [role.title, role.family || '', ...role.required_skills.map((s) => s.name)]
        .map((x) => String(x || '').toLowerCase().split(/[^a-z0-9]+/)).flat().filter(Boolean),
    )
    return jobsFeed.jobs.filter((j) => String(j.title || '').toLowerCase().split(/[^a-z0-9]+/).some((t) => unique.has(t))).length
  }, [jobsFeed, jobsFeedState, all])

  // Phase 5: resolve a real skill id (never fabricated) for the ROLE BEING
  // VIEWED so Learn/Verify deep-link into the journey:
  //  - target role -> first non-strong gap from the level-aware analysis;
  //  - other roles -> first required skill the student is missing, matched by
  //    numeric id on the payload or (catalog roles) by name against the
  //    analysis gap ids.
  const gapSkillIdByName = useMemo(() => {
    const m = new Map<string, number>()
    for (const g of analysis?.skill_gaps ?? []) {
      if (g.skill_id) m.set(g.skill_name.toLowerCase().trim(), g.skill_id)
    }
    return (name: string) => m.get((name || '').toLowerCase().trim())
  }, [analysis])

  const drawerRecommended = useMemo(() => {
    if (!detailsRole) return null
    if (detailsRole.id === selectedRole) {
      const g = (analysis?.skill_gaps || []).find((x) => x.status !== 'strong')
      return g && g.skill_id ? { skillId: g.skill_id, name: g.skill_name } : null
    }
    const miss = detailsRole.required_skills.filter((s) => statusOfSkill(s, profileByName) !== 'have')
    const direct = miss.find((s) => s.skill_id)
    if (direct) return { skillId: direct.skill_id!, name: direct.name }
    const byName = miss.find((s) => gapSkillIdByName(s.name))
    return byName ? { skillId: gapSkillIdByName(byName.name)!, name: byName.name } : null
  }, [detailsRole, selectedRole, analysis, profileByName, gapSkillIdByName])

  const facetOptions = useMemo(() => ({
    location: [...new Set(all.map((r) => roleLocation(r)).filter(Boolean))].sort(),
    level: ['Entry', 'Mid', 'Senior'],
    category: [...new Set(all.map((r) => roleCategory(r)))].sort(),
    skill: [...new Set(all.flatMap((r) => r.required_skills.map((s) => s.name).filter(Boolean)))].sort(),
    family: [...new Set(all.map((r) => roleFamily(r)))].sort(),
  }), [all])

  const hasNoLocation = all.some((r) => !roleLocation(r))

  const activeFilters: { group: keyof typeof filters | 'match'; label: string; value: string }[] = [
    ...filters.location.map((v) => ({ group: 'location' as const, label: 'Location', value: v })),
    ...filters.category.map((v) => ({ group: 'category' as const, label: 'Category', value: v })),
    ...filters.level.map((v) => ({ group: 'level' as const, label: 'Experience', value: v })),
    ...filters.skill.map((v) => ({ group: 'skill' as const, label: 'Skill', value: v })),
    ...filters.family.map((v) => ({ group: 'family' as const, label: 'Role family', value: v })),
    ...(matchRange.min != null ? [{ group: 'match' as const, label: 'Match', value: `≥ ${matchRange.min}%` }] : []),
    ...(matchRange.max != null ? [{ group: 'match' as const, label: 'Match', value: `≤ ${matchRange.max}%` }] : []),
  ]
  const toggleFilter = (group: keyof typeof filters, value: string) => {
    setFilters((f) => ({ ...f, [group]: f[group].includes(value) ? f[group].filter((x) => x !== value) : [...f[group], value] }))
  }
  const dismissFilter = (f: { group: keyof typeof filters | 'match'; value: string }) => {
    if (f.group === 'match') setMatchRange({ min: null, max: null })
    else toggleFilter(f.group, f.value)
  }
  const clearFilters = () => { setFilters({ location: [], level: [], category: [], skill: [], family: [] }); setMatchRange({ min: null, max: null }) }

  // Real jobs (ESCO occupations + company postings) lead; SkillBridge catalog
  // reference roles are demoted to their own labelled secondary section.
  const realRecs = (recs?.recommendations || []).filter((r) => r.source !== 'catalog')

  const targetPct = cvSkillNames.length > 0 && (currentTarget?.required_skills.length ?? 0) > 0
    ? Math.round((currentTarget!.required_skills.reduce((n, s) => n + (cvSkillNames.includes(s.name.toLowerCase().trim()) ? 1 : 0), 0) / currentTarget!.required_skills.length) * 100)
    : null

  // Phase 2: a single match source (backend recomputation whenever available)
  // and display-level deduplication across sources — records are never deleted.
  const recByRole = useMemo(() => backendRecMap(recs), [recs])
  const displayMatch = useMemo(
    () => (r: RoleRecord): RoleMatchInfo => displayMatchOf(r, cvSkillNames, recByRole),
    [cvSkillNames, recByRole],
  )
  const { groups, reps } = dedupDisplay(all, selectedRole, savedIds)
  const hasTarget = !!currentTarget

  // Rank deduplicated representatives by profile overlap, mirroring the old list.
  const rankedReps = [...reps]
    .map((r) => {
      const score = r.required_skills.reduce((n, s) => n + (cvSkillNames.includes(s.name.toLowerCase().trim()) ? 1 : 0), 0)
      return { r, score }
    })
    .sort((a, b) => (b.score - a.score) || a.r.title.localeCompare(b.r.title))

  // "Other sources" (and same-title company postings) for a role's drawer are
  // the rest of its normalized-title group minus the shown representative.
  const othersFor = (role: RoleRecord): RoleRecord[] =>
    (groups.get(normalizedTitle(role.title)) ?? [role]).filter((g) => g.id !== role.id)

  // Honest per-role scenario note for compare: only the current target role has
  // a scenario set to look at; anything else gets a nudge, never a fake count.
  const scenarioNoteFor = (roleId: number): string =>
    selectedRole === roleId
      ? 'Available for your target — open it on your Practice page.'
      : 'Set as target to unlock practice scenarios for this role.'

  const filtered = rankedReps.filter(({ r, score }) => {
    if (savedOnly && !savedIds.has(r.id)) return false
    const haystack = [r.title, r.company_name, roleLocation(r), roleCategory(r), roleExperience(r), roleFamily(r), r.description, ...r.required_skills.map((s) => s.name)]
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
    if (!facetOk(roleFamily(r), filters.family)) return false
    if (filters.skill.length) {
      const names = r.required_skills.map((s) => s.name.toLowerCase().trim())
      if (!filters.skill.some((s) => names.includes(s.toLowerCase().trim()))) return false
    }
    if (!noCvSkills) {
      const p = displayMatch(r).pct ?? 0
      if (matchRange.min != null && p < matchRange.min) return false
      if (matchRange.max != null && p > matchRange.max) return false
    }
    // Without a CV we have nothing to match against, so show everything.
    if (noCvSkills) return true
    // With a CV, surface the best-fitting roles first, but let the user see all.
    return showAll || score > 0
  })

  const savedReps = reps.filter((r) => savedIds.has(r.id))
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const paged = filtered.slice((page - 1) * pageSize, page * pageSize)

  // Pagination always restarts when the underlying list changes.
  useEffect(() => { setPage(1) }, [
    q, showAll, srcCompany, srcCatalog, savedOnly, tab,
    matchRange.min, matchRange.max,
    filters.location.join('|'), filters.level.join('|'), filters.category.join('|'), filters.skill.join('|'), filters.family.join('|'),
    savedIds.size,
  ])

  // Phase L keyboard navigation: the highlight ring resets whenever the paged
  // grid changes identity (page, query, filters, source split, saved-only).
  const hlResetKey = [
    page, filtered.length, q.trim(), savedOnly, srcCompany, srcCatalog, tab,
    filters.location.join('|'), filters.level.join('|'), filters.category.join('|'),
    filters.skill.join('|'), filters.family.join('|'), matchRange.min, matchRange.max,
  ].join(':')
  useEffect(() => { setHlIndex(-1) }, [hlResetKey])
  const cardRefs = useRef<(HTMLDivElement | null)[]>([])
  useEffect(() => {
    const el = cardRefs.current[Math.max(0, hlIndex)]
    if (el) el.scrollIntoView({ block: 'nearest' })
  }, [hlIndex])
  const setCardRef = (i: number) => (el: HTMLDivElement | null) => { cardRefs.current[i] = el }
  const onSearchKeyDown = (e: React.KeyboardEvent) => {
    if (paged.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHlIndex((i) => (i < 0 ? 0 : (i + 1) % paged.length))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHlIndex((i) => (i < 0 ? paged.length - 1 : (i - 1 + paged.length) % paged.length))
    } else if (e.key === 'Enter') {
      if (hlIndex >= 0 && paged[hlIndex]) { e.preventDefault(); openRoleDetails(paged[hlIndex].r) }
    } else if (e.key === 'Escape') {
      e.preventDefault(); setHlIndex(-1)
    }
  }

  // Target selection is deliberate: replacing an existing target asks the user
  // to confirm, explaining that learning paths and practice scenarios will
  // re-shape while existing learning/assessment/scenario history is preserved.
  // First-ever selection (or no current target) applies immediately.
  const runTarget = async (p: PendingTarget) => {
    if (!student) return
    try {
      if (p.kind === 'role') {
        await api.updateStudent(student.id, { target_role_id: p.id })
        setSelectedRole(p.id)
        toast.push('Target career updated.', 'success')
      } else if (p.kind === 'esco') {
        await api.selectEscoTarget(student.id, p.occ.uri, p.occ.title, p.occ.skills)
        setSelectedRole(null)
        toast.push('Target career updated to a real job role.', 'success')
      } else {
        const rec = p.rec
        if (rec.source === 'esco' && rec.external_id) {
          await api.selectEscoTarget(student.id, rec.external_id, rec.title, rec.skills)
          setSelectedRole(null)
          toast.push('Target career updated.', 'success')
        } else if (rec.role_id != null) {
          await api.updateStudent(student.id, { target_role_id: rec.role_id })
          setSelectedRole(rec.role_id)
          toast.push('Target career updated.', 'success')
        } else {
          return
        }
      }
      setDetailsRole(null)
      await refreshStudent()
    } catch (e: any) {
      toast.push(e.message || 'Failed to select target role', 'error')
    }
  }

  const chooseTarget = (roleId: number) => {
    if (hasTarget) setPendingTarget({ kind: 'role', id: roleId })
    else runTarget({ kind: 'role', id: roleId })
  }

  const confirmTarget = () => {
    if (!pendingTarget) return
    setTargetBusy(true)
    runTarget(pendingTarget).finally(() => { setTargetBusy(false); setPendingTarget(null) })
  }

  const pendingTargetLabel = pendingTarget?.kind === 'role'
    ? (all.find((r) => r.id === pendingTarget.id)?.title ?? 'this role')
    : pendingTarget?.kind === 'esco'
      ? pendingTarget.occ.title
      : (pendingTarget?.rec?.title ?? 'this role')

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

  const selectRecommendation = (rec: RoleRecommendation) => {
    if (!student) return
    if (hasTarget) { setPendingTarget({ kind: 'rec', rec }); return }
    const key = rec.role_id != null ? String(rec.role_id) : rec.external_id || rec.title
    setRecSelectingKey(key)
    runTarget({ kind: 'rec', rec }).finally(() => setRecSelectingKey(null))
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

  const selectMarketTarget = (occ: EscoOccupation) => {
    if (!student) return
    if (hasTarget) { setPendingTarget({ kind: 'esco', occ }); return }
    setMarketSelecting(occ.uri)
    runTarget({ kind: 'esco', occ }).finally(() => setMarketSelecting(null))
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

  const openRoleDetails = (r: RoleRecord) => {
    setDetailsRole(r); setDetailsBusy(false)
    // Phase L recently-viewed: opening a local role's details records the view
    // (fire-and-forget; a failure must never block the drawer). On the recents
    // tab the list refreshes immediately so the row reflects the latest view.
    if (student && r?.id) {
      api.recordRoleView(student.id, r.id).catch((e) => console.error('[roles] record view failed:', e))
      if (tab === 'recents') loadRecents()
    }
  }
  const closeRoleDetails = () => { if (!detailsBusy) setDetailsRole(null) }
  const selectFromDetails = (r: RoleRecord) => chooseTarget(r.id)
  const learnSkill = (skillId: number) => {
    const role = detailsRole
    setDetailsRole(null)
    onNavigate?.('learning', { skillId, roleTitle: role?.title ?? '' })
  }
  // Phase 5: Role Detail routes into the rest of the journey. "Verify a Skill"
  // focuses Assessments on the role's most important missing skill; "Practice
  // this role" opens the scenario library (only the actual target role has
  // scenarios written for it, so non-target roles get the honest unlock nudge).
  const verifySkill = (skillId: number) => {
    const role = detailsRole
    setDetailsRole(null)
    onNavigate?.('assessments', { skillId, roleTitle: role?.title ?? '' })
  }
  const practiceRole = () => {
    const role = detailsRole
    setDetailsRole(null)
    onNavigate?.('scenarios', { skillId: 0, roleTitle: role?.title ?? '' })
  }
  const detailsAreTarget = detailsRole != null && selectedRole === detailsRole.id

  // Phase 2 compare queue (max 3) + the roles currently queued.
  const toggleCompare = (id: number) => {
    const has = compareIds.includes(id)
    if (has) { setCompareIds(compareIds.filter((x) => x !== id)); return }
    if (compareIds.length >= 3) { toast.push('Comparison is limited to three roles.', 'error'); return }
    setCompareIds([...compareIds, id])
  }
  const compared = all.filter((r) => compareIds.includes(r.id))

  // Honest practice-scenario note in the drawer: only the current target role
  // has real scenario data to surface; anything else gets a nudge.
  const drawerIsTarget = detailsRole != null && selectedRole === detailsRole.id
  useEffect(() => {
    if (!student || !drawerIsTarget) { setDrawerScenarios(null); return }
    let live = true
    setDrawerScenarios('Checking practice scenarios for your target career…')
    api.scenarios(student.id)
      .then((lib: ScenarioLibrary) => {
        if (!live) return
        setDrawerScenarios(
          lib.availability === 'none'
            ? (lib.availability_reason || 'No practice scenarios are available for this target career yet.')
            : `${lib.scenarios.length} practice scenario${lib.scenarios.length === 1 ? '' : 's'} ready for your target career.`)
      })
      .catch(() => { if (live) setDrawerScenarios('Practice scenarios are temporarily unavailable.') })
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detailsRole?.id, drawerIsTarget])

  return (
    <div className="skills-page sro3-page">
      {backTo && (
        <nav className="crumbs" aria-label="Breadcrumbs">
          <button type="button" className="crumb-back" onClick={() => onNavigate?.(backTo.key)}>
            <IconBack size={14} /> Back to {backTo.label}
          </button>
        </nav>
      )}
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

      <div className="rd-tabs" role="tablist" aria-label="Role discovery views">
        {([
          ['recommended', 'Recommended for You'],
          ['all', 'All Roles'],
          ['recents', 'Recently Viewed'],
          ['saved', 'Saved Roles'],
          ['market', 'Market Search'],
        ] as const).map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key}
            className={`rd-tab ${tab === key ? 'on' : ''}`} onClick={() => setTab(key)}>
            {label}
            {key === 'all' && <span className="rd-tab-count">{reps.length}</span>}
            {key === 'recents' && recentLoaded && recentRoles.length > 0 && <span className="rd-tab-count">{recentRoles.length}</span>}
            {key === 'saved' && savedIds.size > 0 && <span className="rd-tab-count">{savedIds.size}</span>}
          </button>
        ))}
      </div>

      {tab === 'recommended' && (
      <>
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
                studentId={student?.id}
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
      </>
      )}

      {tab === 'all' && (
      <>
      <section className="sro3-roles-card" id="role-library" aria-label="Role library">
        <div className="sro3-roles-head">
          <h3 className="sro3-roles-title">Role library</h3>
          <span className="sro3-count">{loaded ? `${filtered.length} matching roles` : '…'}</span>
          {roleDataVersion ? <span className="srb-cat-version">Catalogue data v{roleDataVersion}</span> : null}
        </div>
        <p className="card-sub">Search roles, filter by where and what you want, and read each role's requirements before committing to a target.</p>
        <div className="searchbar mb">
          <IconSearch size={16} />
          <input placeholder="Search roles, companies, skills, families, categories…" value={qDraft} onChange={(e) => setQDraft(e.target.value)} onKeyDown={onSearchKeyDown} aria-label="Search roles" />
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
              <details className="srb-facet">
                <summary>Role family{filters.family.length ? ` (${filters.family.length})` : ''}</summary>
                <div className="srb-facet-opts srb-facet-scroll">
                  {facetOptions.family.map((f) => (
                    <label key={f}><input type="checkbox" checked={filters.family.includes(f)} onChange={() => toggleFilter('family', f)} /> {f}</label>
                  ))}
                </div>
              </details>
              <details className="srb-facet">
                <summary>Match{(matchRange.min != null || matchRange.max != null) ? ' ✓' : ''}</summary>
                <div className="srb-facet-opts srb-facet-scroll">
                  <label className="rd-range-row">Min % <input type="number" min={0} max={100} value={matchRange.min ?? ''} placeholder="0"
                      onChange={(e) => setMatchRange((m) => ({ ...m, min: e.target.value === '' ? null : Math.max(0, Math.min(100, Number(e.target.value))) }))} /></label>
                  <label className="rd-range-row">Max % <input type="number" min={0} max={100} value={matchRange.max ?? ''} placeholder="100"
                      onChange={(e) => setMatchRange((m) => ({ ...m, max: e.target.value === '' ? null : Math.max(0, Math.min(100, Number(e.target.value))) }))} /></label>
                </div>
              </details>
            </div>

            {activeFilters.length > 0 && (
              <div className="srb-active">
                {activeFilters.map(({ group, value }) => (
                  <button key={`${group}:${value}`} type="button" className="srb-chip" onClick={() => dismissFilter({ group, value })}>
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
                  <button type="button" className="btn btn-sm srb-btn-outline" style={{ marginTop: 10, display: 'block', marginInline: 'auto' }} onClick={() => { setQ(''); setQDraft(''); clearFilters() }}>Clear search &amp; filters</button>
                ) : null}
              </div>
            ) : (
              <>
              <span className="sr-only" role="status" aria-live="polite">
                {hlIndex >= 0 && paged[hlIndex] ? `Highlighted ${paged[hlIndex].r.title}, ${hlIndex + 1} of ${paged.length}` : ''}
              </span>
              <div className="srb-grid" role="list" aria-label="Matching roles — use arrow keys to highlight a card, Enter to open it">
                {paged.map(({ r }, idx) => {
                  const statusBySkill = r.required_skills.map((s) => ({ s, status: statusOfSkill(s, profileByName) }))
                  return (
                    <div key={r.id} role="listitem" className={`srb-card-wrap ${hlIndex === idx ? 'srb-hl' : ''}`}
                      ref={setCardRef(idx)} data-hl={hlIndex === idx ? 'true' : undefined}>
                    <RoleLibraryCard
                      r={r}
                      pct={displayMatch(r).pct ?? 0}
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
                      cmp={compareIds.includes(r.id)}
                      onCompare={() => toggleCompare(r.id)}
                      onSelect={() => chooseTarget(r.id)}
                      onDetails={() => openRoleDetails(r)}
                      onToggleSave={() => toggleSaveRole(r.id)}
                    />
                    </div>
                  )
                })}
              </div>
              </>
            )}
          </>
        )}
      </section>

      {tab === 'all' && filtered.length > 0 && totalPages > 1 && (
        <div className="rd-pager">
          <button type="button" className="btn btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>‹ Prev</button>
          <span className="rd-pager-info">Page {page} of {totalPages} · {filtered.length} roles</span>
          <button type="button" className="btn btn-sm" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>Next ›</button>
        </div>
      )}
      </>
      )}

      {tab === 'saved' && (
      <>
        <section className="sro3-roles-card" id="saved-roles" aria-label="Saved roles">
          <div className="sro3-roles-head">
            <h3 className="sro3-roles-title">Saved roles</h3>
            <span className="sro3-count">{savedReps.length} saved role{savedReps.length === 1 ? '' : 's'}</span>
          </div>
          <p className="card-sub">Roles you bookmarked stay here. Saved roles are independent of your selected target career, so you can weigh options before committing.</p>
          {savedReps.length === 0 ? (
            <div className="empty">
              No saved roles yet. Open any role, press Save, then come back here to compare your shortlist.
            </div>
          ) : (
            <div className="srb-grid">
              {savedReps.map((r) => {
                const statusBySkill = r.required_skills.map((s) => ({ s, status: statusOfSkill(s, profileByName) }))
                return (
                  <RoleLibraryCard
                    key={r.id}
                    r={r}
                    pct={displayMatch(r).pct ?? 0}
                    selected={selectedRole === r.id}
                    dest={catalog.some((c) => c.id === r.id) ? 'catalog' : undefined}
                    chips={noCvSkills ? undefined : statusBySkill.map(({ s, status }) => ({ name: s.name, level: s.required_level, matched: status !== 'missing' }))}
                    statusCounts={{
                      have: statusBySkill.filter((x) => x.status === 'have').length,
                      developing: statusBySkill.filter((x) => x.status === 'developing').length,
                      missing: statusBySkill.filter((x) => x.status === 'missing').length,
                    }}
                    noCvSkills={noCvSkills}
                    saved={true}
                    cmp={compareIds.includes(r.id)}
                    onCompare={() => toggleCompare(r.id)}
                    onSelect={() => chooseTarget(r.id)}
                    onDetails={() => openRoleDetails(r)}
                    onToggleSave={() => toggleSaveRole(r.id)}
                  />
                )
              })}
            </div>
          )}
        </section>
      </>
      )}

      {tab === 'recents' && (
      <>
        <section className="sro3-roles-card" id="recent-roles" aria-label="Recently viewed roles">
          <div className="sro3-roles-head">
            <h3 className="sro3-roles-title">Recently viewed</h3>
            <span className="sro3-count">{recentLoaded ? `${recentRoles.length} recent role${recentRoles.length === 1 ? '' : 's'}` : '…'}</span>
          </div>
          <p className="card-sub">Roles you opened most recently from the role library, newest first. Opening a role's details records the view here automatically (up to 30 views are kept).</p>
          {!recentLoaded ? (
            <div className="empty">Loading recently viewed roles…</div>
          ) : recentErr ? (
            <div className="empty">
              Couldn't load your recently viewed roles. Please try again.
            </div>
          ) : recentRoles.length === 0 ? (
            <div className="empty">
              Nothing here yet. Open any role's details in the role library and it will appear here, so you can quickly pick up where you left off.
            </div>
          ) : (
            <div className="srb-recent-list">
              {recentRoles.map((rr) => {
                const role = all.find((x) => x.id === rr.id)
                return (
                  <RecentRoleRow
                    key={rr.id}
                    rr={rr}
                    role={role}
                    saved={role ? savedIds.has(role.id) : false}
                    cmp={role ? compareIds.includes(role.id) : false}
                    onDetails={() => role && openRoleDetails(role)}
                    onToggleSave={() => role && toggleSaveRole(role.id)}
                    onSelect={() => role && chooseTarget(role.id)}
                    onCompare={() => role && toggleCompare(role.id)}
                  />
                )
              })}
            </div>
          )}
        </section>
      </>
      )}

      {tab === 'market' && (
      <>
        <section className="sro3-market" id="market-search" aria-label="Market search">
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
      </>
      )}

      {detailsRole && (
        <RoleDetailsDrawer
          role={detailsRole}
          others={othersFor(detailsRole)}
          match={displayMatch(detailsRole)}
          noCvSkills={noCvSkills}
          profileByName={profileByName}
          evidence={evidence}
          selected={selectedRole === detailsRole.id}
          busy={detailsBusy}
          saved={savedIds.has(detailsRole.id)}
          inCompare={compareIds.includes(detailsRole.id)}
          scenarioNote={drawerScenarios}
          provenance={provenance}
          provenanceState={provState}
          onOpenRole={(r) => r.id !== detailsRole.id && setDetailsRole(r)}
          jobsFeed={jobsFeed}
          jobsFeedState={jobsFeedState}
          onClose={closeRoleDetails}
          onSelect={() => selectFromDetails(detailsRole)}
          onToggleSave={() => toggleSaveRole(detailsRole.id)}
          onCompare={() => toggleCompare(detailsRole.id)}
          onLearn={learnSkill}
          onVerifySkill={verifySkill}
          onPracticeRole={practiceRole}
          practiceEnabled={detailsAreTarget}
          recommendedSkillId={drawerRecommended?.skillId ?? null}
          recommendedSkillName={drawerRecommended?.name ?? null}
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

      <CompareTray
        roles={compared.map((r) => ({ id: r.id, title: r.title, sourceLabel: roleSourceLabel(r) }))}
        open={() => setShowCompare(true)}
        onRemove={(id) => toggleCompare(id)}
        onClear={() => setCompareIds([])}
      />

      {showCompare && compared.length > 0 && (
        <CompareModal
          roles={compared}
          matches={compared.map((r) => displayMatch(r))}
          profileByName={profileByName}
          evidence={evidence}
          scenarioNoteFor={scenarioNoteFor}
          jobCountFor={jobCountFor}
          savedFor={(id) => savedIds.has(id)}
          busy={targetBusy}
          onClose={() => setShowCompare(false)}
          onRemove={(id) => toggleCompare(id)}
          onSelect={(r) => { setShowCompare(false); chooseTarget(r.id) }}
          onSave={(id) => toggleSaveRole(id)}
          onLearn={(skillId) => { setShowCompare(false); learnSkill(skillId) }}
        />
      )}

      <ConfirmModal
        open={!!pendingTarget}
        title="Change your target career?"
        body={<>Switch your target to <span className="modal-name">{pendingTargetLabel}</span>? Your learning path and available practice scenarios will re-shape around this role. Existing learning, assessment and scenario history is preserved — nothing is deleted.</>}
        confirmLabel="Set as target"
        danger={false}
        busy={targetBusy}
        onCancel={() => setPendingTarget(null)}
        onConfirm={confirmTarget}
      />

      <ToastRegion toasts={toast.toasts} dismiss={toast.dismiss} />
    </div>
  )
}

// ------------------------------------------------------------------ Company roles

// Human-confirmed mapping between a company's local role and a canonical
// reference role. Suggestions are computed server-side, never auto-linked;
// confirming (or unmapping) is the only write, and the local role's title and
// skills are never touched.
function RoleMappingPanel({ role, onChanged }: { role: RoleRecord; onChanged: () => void }) {
  const toast = useToast()
  const panelRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [matches, setMatches] = useState<RoleMappingMatch[]>([])
  const [mapped, setMapped] = useState<RoleMappingTarget | null>(null)
  const [history, setHistory] = useState<RoleMappingEvent[]>([])
  const [busy, setBusy] = useState(false)
  const [loadErr, setLoadErr] = useState('')

  const refreshState = async () => {
    try {
      const s = await api.canonicalMatches(role.id)
      setMapped(s.mapped)
      setHistory(await api.mappingHistory(role.id))
    } catch {
      /* keep current state */
    }
  }

  const load = async () => {
    setBusy(true)
    setLoadErr('')
    try {
      const [s, h] = await Promise.all([api.canonicalMatches(role.id), api.mappingHistory(role.id)])
      setMatches(s.matches)
      setMapped(s.mapped)
      setHistory(h)
      setOpen(true)
    } catch (err: any) {
      setLoadErr(err.message || 'Could not load canonical matches')
    } finally {
      setBusy(false)
    }
  }

  // An already-mapped role shows its match without an extra click.
  useEffect(() => {
    if (role.canonical_role_id) load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role.id])

  useEffect(() => {
    if (open) panelRef.current?.focus()
  }, [open])

  const confirm = async (canonicalRoleId: number) => {
    setBusy(true)
    try {
      await api.setCanonicalMapping(role.id, canonicalRoleId)
      onChanged()
      await refreshState()
      toast.push('Role mapped to canonical role.')
    } catch (err: any) {
      toast.push(err.message || 'Failed to map role', 'error')
    } finally {
      setBusy(false)
    }
  }

  const unmap = async () => {
    setBusy(true)
    try {
      await api.setCanonicalMapping(role.id, null)
      onChanged()
      setMatches([])
      await refreshState()
      toast.push('Canonical mapping removed — your role is unchanged.')
    } catch (err: any) {
      toast.push(err.message || 'Failed to remove mapping', 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section
      className="rm-panel"
      aria-label={`Canonical role mapping for ${role.title}`}
      ref={panelRef}
      tabIndex={-1}
    >
      <div className="rm-head">
        <span className="rm-label">Canonical role</span>
        {mapped ? (
          <>
            <span className="chip rm-chip"><IconCheck size={12} /> Mapped</span>
            <span className="rm-mapped">{mapped.mapped_title} <span className="rm-source">{mapped.source}</span></span>
            <span className="rm-actions">
              <button type="button" className="btn btn-sm" disabled={busy} onClick={load}
                aria-label="Change canonical role mapping">
                <IconEdit size={13} /> Change
              </button>
              <button type="button" className="btn btn-sm" disabled={busy} onClick={unmap}
                aria-label="Unmap canonical role">
                <IconTrash size={13} /> Unmap
              </button>
            </span>
          </>
        ) : (
          <button type="button" className="btn btn-sm" disabled={busy} onClick={load}
            aria-label={`Suggest canonical role for ${role.title}`}>
            <IconTarget size={13} /> Find canonical match
          </button>
        )}
      </div>

      {loadErr && <p className="small error">{loadErr}</p>}

      {open && !mapped && !busy && matches.length === 0 && (
        <p className="rm-empty small muted">
          No close canonical match — this role stays as-is. Nothing is auto-linked.
        </p>
      )}

      {open && !mapped && matches.length > 0 && (
        <div className="rm-matches">
          {matches.map((m) => (
            <div className="rm-match" key={m.role_id}>
              <div className="rm-match-top">
                <span className="rm-match-title">{m.title} <span className="rm-source">{m.source}</span></span>
                <span className={`rm-conf rm-conf-${m.confidence_label.toLowerCase()}`}>
                  {m.confidence_label} · {Math.round(m.confidence * 100)}% match
                </span>
              </div>
              <p className="rm-exp small muted">{m.explanation}</p>
              <div className="rm-bar">
                <span className={`rm-bar-fill rm-bar-${m.confidence_label.toLowerCase()}`}
                  style={{ width: `${Math.round(m.confidence * 100)}%` }}
                  aria-hidden="true" />
              </div>
              <button type="button" className="btn btn-sm btn-primary" disabled={busy}
                onClick={() => confirm(m.role_id)} aria-label={`Confirm mapping to ${m.title}`}>
                <IconCheck size={13} /> Confirm
              </button>
            </div>
          ))}
        </div>
      )}

      {history.length > 0 && (
        <div className="rm-history">
          <div className="rm-history-title">Mapping history</div>
          {history.slice(0, 5).map((e) => (
            <div className="rm-history-row" key={e.event_id}>
              <span className={`rm-action rm-action-${e.action}`}>{e.action}</span>
              <span className="small">
                {e.action === 'mapped' && <>→ {e.to_title ?? ''}</>}
                {e.action === 'unmapped' && <>removed {e.from_title ? `(${e.from_title})` : ''}</>}
                {e.action === 'changed' && <>from {e.from_title ?? '—'} → {e.to_title ?? ''}</>}
              </span>
              <span className="small muted">{e.actor_role} · {e.created_at}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

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
<span className="skill-tag" key={s.skill_id}>{humanizeTopicLabel(s.name)} <span className="lv">{s.required_level}</span></span>
                ))}
              </div>
              <RoleMappingPanel role={r} onChanged={refresh} />
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