import React, { useEffect, useRef, useState } from 'react'
import { useApp } from '../AppContext'
import { api } from '../lib/api'
import { RELOCATION_MARKETS, marketLabel } from '../lib/markets'
import type { RoleRecord, Student, Skill, RolesResponse, EscoOccupation, Analysis, RoleRecommendation, RoleRecommendationsResponse } from '../lib/types'
import { IconPlus, IconEdit, IconTrash, IconUpload, IconSearch, IconCheck, IconTarget } from '../components/Icons'
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

export default function SkillsRolesPage() {
  const { me, applyCopilot } = useApp()
  useEffect(() => {
    applyCopilot({ page: 'skills_roles', skillId: null, competency: null, jobTitle: null, jobUrl: null })
  }, [])
  if (!me) return null
  if (me.entity_type === 'student') return <StudentBrowse student={me.student} analysis={me.analysis ?? undefined} />
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

function structureSkillChips(r: RoleRecord, cvSkillNames: string[]): SkillChip[] {
  return r.required_skills.map((s) => ({
    name: s.name,
    level: s.required_level,
    matched: cvSkillNames.includes(s.name.toLowerCase().trim()),
  }))
}

function formatMatch(pct: number): string {
  if (pct >= 40) return 'match'
  if (pct >= 20) return 'warming'
  return 'unmatched'
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
function RecommendationCard({ rec, selected, onSelect, busy }: {
  rec: RoleRecommendation; selected: boolean; onSelect: () => void; busy: boolean
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
        <button className={`btn btn-sm ${selected ? '' : 'btn-primary'}`} onClick={onSelect} disabled={selected || busy}>
          {busy ? 'Selecting…' : selected ? '✓ Target Career' : 'Select as target'}
        </button>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ Student browse
function StudentBrowse({ student, analysis }: { student?: Student; analysis?: Analysis }) {
  const { refreshStudent } = useApp()
  const { roles, catalog, loaded, loadError } = useRoles()
  const [q, setQ] = useState('')
  const [selectedRole, setSelectedRole] = useState<number | null>(student?.target_role_id ?? null)
  const [uploading, setUploading] = useState(false)
  const [cvMsg, setCvMsg] = useState('')
  const [cvErr, setCvErr] = useState('')
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
  const toast = useToast()

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

  // Real jobs (ESCO occupations + company postings) lead; SkillBridge catalog
  // reference roles are demoted to their own labelled secondary section.
  const realRecs = (recs?.recommendations || []).filter((r) => r.source !== 'catalog')
  const catalogRecs = (recs?.recommendations || []).filter((r) => r.source === 'catalog')

  const targetPct = cvSkillNames.length > 0 && (currentTarget?.required_skills.length ?? 0) > 0
    ? Math.round((currentTarget!.required_skills.reduce((n, s) => n + (cvSkillNames.includes(s.name.toLowerCase().trim()) ? 1 : 0), 0) / currentTarget!.required_skills.length) * 100)
    : null

  const levelBreakdown = (student?.self_reported_skills || []).reduce((acc, s) => {
    acc[s.level] = (acc[s.level] || 0) + 1
    return acc
  }, {} as Record<string, number>)

  const filtered = ranked.filter(({ r, score }) => {
    const matchSearch =
      r.title.toLowerCase().includes(q.toLowerCase()) ||
      (r.company_name || '').toLowerCase().includes(q.toLowerCase())
    if (!matchSearch) return false
    const isCat = catalog.some((c) => c.id === r.id)
    if (isCat ? !srcCatalog : !srcCompany) return false
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
  useEffect(() => {
    if (!student) return
    api.roleRecommendations(student.id)
      .then(setRecs)
      .catch((e) => { console.error('[roles] recommendations failed:', e); setRecsErr(e.message || 'Recommendations unavailable') })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [student?.id])

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
      const res = await api.escoMarket(query)
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
    const seed = pickSeedSkill(profile, roles, catalog)
      || student?.target_role?.title || profile[0]?.name || ''
    const trimmed = seed.trim().slice(0, 80)
    if (trimmed) { setMq(trimmed); runMarketSearch(trimmed) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded])

  const onUpload = async (file: File | undefined) => {
    if (!file || !student) return
    setUploading(true)
    setCvMsg(''); setCvErr('')
    try {
      const res = await api.uploadCv(student.id, file)
      setCvMsg(`Extracted ${res.extracted.length} skills from "${file.name}". These are shown as self-reported until verified by an assessment.`)
      toast.push(`Extracted ${res.extracted.length} skills from your CV.`)
      await refreshStudent()
    } catch (e: any) {
      setCvErr(e.message || 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  const initials = (student?.name || 'S').split(' ').map((w) => w[0]).slice(0, 2).join('').toUpperCase()

  return (
    <div className="skills-page sro3-page">
      <section className="sro3-hero">
        <div className="sro3-hero-copy">
          <p className="sro3-eyebrow">Find your next role</p>
          <h1 className="sro3-hero-title">Choose the role your learning path should serve.</h1>
          <p className="sro3-hero-sub">Your CV profile, verified skills, and target role stay separate so the match score remains explainable.</p>
        </div>
        <div className="sro3-target-box">
          <span className="sro3-target-label">Your target career</span>
          <strong className="sro3-target-title">{currentTarget?.title || 'Not selected yet'}</strong>
          <span className="sro3-target-meta">{currentTarget?.company_name || 'Select a role to unlock your gap map'}</span>
          {targetPct !== null ? (
            <div className="sro3-target-score">
              <b className={targetPct >= 40 ? 'g' : targetPct >= 20 ? 'a' : ''}>{targetPct}%</b>
              <span>skill match</span>
            </div>
          ) : (
            <span className="sro3-target-hint">Upload a CV to see your match score against this role.</span>
          )}
        </div>
      </section>

      <section className="sro3-strip">
        <div className="sro3-stat sro3-stat-profile">
          <div className="avatar sro3-avatar">{initials}</div>
          <div className="sro3-stat-body">
            <span className="sro3-stat-label">Profile &amp; CV</span>
            <strong className="sro3-stat-value sro3-stat-file">{student?.cv_filename || 'No CV uploaded'}</strong>
            <span className="sro3-stat-note">Extraction is live via GenAI</span>
          </div>
        </div>
        <div className="sro3-stat">
          <span className="sro3-stat-label">Skills detected</span>
          <strong className="sro3-stat-value">{(student?.self_reported_skills || []).length}</strong>
          <span className="sro3-stat-note">
            {['Advanced', 'Intermediate', 'Beginner'].filter((l) => levelBreakdown[l]).map((l) => `${levelBreakdown[l]} ${l.toLowerCase()}`).join(' · ') || 'self-reported'}
          </span>
        </div>
        <div className="sro3-stat">
          <span className="sro3-stat-label">Verified skills</span>
          <strong className="sro3-stat-value sro3-stat-green">{(student?.verified_skills || []).length}</strong>
          <span className="sro3-stat-note">Earned via assessments</span>
        </div>
        <div className="sro3-stat">
          <span className="sro3-stat-label">Target match</span>
          <strong className="sro3-stat-value">{targetPct !== null ? `${targetPct}%` : '—'}</strong>
          <span className="sro3-stat-note">{currentTarget?.title || 'Pick a target career'}</span>
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
              />
            ))}
          </div>
        </div>
      )}
      {recs && catalogRecs.length > 0 && (
        <div className="sro3-recs-card">
          <div className="sro3-roles-head">
            <h3 className="sro3-roles-title">Reference roles — local catalogue</h3>
            <span className="sro3-count">{catalogRecs.length} reference role{catalogRecs.length > 1 ? 's' : ''}</span>
          </div>
          <p className="card-sub">SkillBridge reference skill profiles — not live job postings. Useful when live labour-market matching is limited in your area.</p>
          <div className="stack sro3-list">
            {catalogRecs.map((rec) => (
              <RecommendationCard
                key={rec.role_id ?? rec.external_id ?? rec.title}
                rec={rec}
                selected={recSelected(rec)}
                busy={recSelectingKey === (rec.role_id != null ? String(rec.role_id) : rec.external_id || rec.title)}
                onSelect={() => selectRecommendation(rec)}
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

      <div className="sro3-roles-card">
        <div className="sro3-roles-head">
          <h3 className="sro3-roles-title">Role library</h3>
          <span className="sro3-count">{filtered.length} matching roles</span>
        </div>
        <p className="card-sub">Select one as your Target Career to see your gap map and match score. Catalog roles are reference skill profiles you can aim at.</p>
        <div className="searchbar mb">
          <IconSearch size={16} />
          <input placeholder="Search roles or companies…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="sro3-layout">
          <aside className="sro3-rail">
            <span className="sro3-rail-title">Filters</span>
            <label className="sro3-check">
              <input type="checkbox" checked={showAll} onChange={() => setShowAll((s) => !s)} disabled={noCvSkills} />
              <span>
                <b>Show every role</b>
                <small>{noCvSkills ? 'Upload a CV to unlock best matches' : 'Overrides best-match ranking'}</small>
              </span>
            </label>
            <div className="sro3-rail-divider" />
            <span className="sro3-rail-title">Source</span>
            <label className="sro3-check">
              <input type="checkbox" checked={srcCompany} onChange={() => setSrcCompany((s) => !s)} />
              <span>
                <b>Company roles</b>
                <small>Posted by hiring companies</small>
              </span>
            </label>
            <label className="sro3-check">
              <input type="checkbox" checked={srcCatalog} onChange={() => setSrcCatalog((s) => !s)} />
              <span>
                <b>Catalog roles</b>
                <small>Reference skill profiles</small>
              </span>
            </label>
            <div className="sro3-rail-divider" />
            <p className="sro3-rail-note">Match % is the share of this role's required skills found in your CV-extracted profile.</p>
          </aside>
          <div className="stack sro3-list">
            {loadError && <div className="error" style={{ marginBottom: 12 }}>{loadError}</div>}
            {filtered.map(({ r, score }) => (
              <RoleCard
                key={r.id}
                r={r}
                selected={selectedRole === r.id}
                selectable
                dest={catalog.some((c) => c.id === r.id) ? 'catalog' : undefined}
                chips={noCvSkills ? undefined : structureSkillChips(r, cvSkillNames)}
                onSelect={() => chooseTarget(r.id)}
              />
            ))}
            {filtered.length === 0 && <div className="empty">{noCvSkills ? 'No roles match your search.' : 'No roles match your current CV skills. Try "Show every role" to browse the full catalog.'}</div>}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="flex between" style={{ flexWrap: 'wrap', gap: 10 }}>
          <h3>My profile &amp; CV</h3>
          <label className="btn btn-sm" style={{ cursor: 'pointer' }}>
            <IconUpload size={14} /> {uploading ? 'Extracting…' : 'Upload CV'}
            <input type="file" accept=".txt,.md,.pdf" style={{ display: 'none' }} onChange={(e) => onUpload(e.target.files?.[0])} />
          </label>
        </div>
        {cvMsg && <p className="small" style={{ color: 'var(--green)' }}>{cvMsg}</p>}
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