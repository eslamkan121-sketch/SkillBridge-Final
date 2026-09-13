// Phase F — Company Role -> Canonical Role mapping — frontend source-contract
// guard.
// Covers: API helpers + types present; role-level mapping panel wired into the
// company role manager; suggestions are never auto-linked and confirmation is
// always a human click; unmapping posts null; the local role's title and skills
// are never touched from the panel.

import { readProject } from './path-helpers.mjs'

const read = readProject

const problems = []
const ok = (cond, msg) => { if (!cond) problems.push(msg) }

const types = read('frontend/src/lib/types.ts')
const api = read('frontend/src/lib/api.ts')
const skills = read('frontend/src/pages/SkillsRolesPage.tsx')
const css = read('frontend/src/index.css')

// ---- 1. Types: mapping contracts mirror the backend payloads.
for (const t of ['RoleMappingTarget', 'RoleMappingMatch', 'RoleMappingEvent']) {
  ok(new RegExp(`export interface ${t} \\{`).test(types), `${t} type exists`)
}
ok(/canonical_role_id\?: number \| null/.test(types)
   && /canonical_mapping_updated_at\?: string \| null/.test(types),
   'RoleRecord carries the additive canonical fields')
ok(/confidence_label: 'High' \| 'Medium' \| 'Low'/.test(types),
   'Match carries the same confidence tiers as the engine')

// ---- 2. API: the three routes are reachable and named exactly as the backend.
ok(/canonicalMatches: \(roleId: number\)/.test(api)
   && /\/api\/company\/roles\/\$\{roleId\}\/canonical-matches/.test(api),
   'api.canonicalMatches hits GET /canonical-matches')
ok(/setCanonicalMapping: \(roleId: number, canonicalRoleId: number \| null\)/.test(api)
   && /canonical-mapping/.test(api)
   && /method: 'POST'/.test(api),
   'api.setCanonicalMapping POSTs to /canonical-mapping')
ok(/mappingHistory: \(roleId: number\)/.test(api)
   && /mapping-history/.test(api),
   'api.mappingHistory hits GET /mapping-history')

// ---- 3. UI: a human-confirmed mapping panel wired into every company role row.
ok(/function RoleMappingPanel/.test(skills)
   && /aria-label=\{`Canonical role mapping for /.test(skills),
   'RoleMappingPanel exists and is accessible')
ok(/<RoleMappingPanel role=\{r\} onChanged=\{refresh\} \/>/.test(skills)
   && /roles\.map\(\(r\) =>/.test(skills),
   'Panel is mounted per company role and refreshes the role list on change')
ok(/Find canonical match/.test(skills)
   && /Nothing is auto-linked/.test(skills),
   'Unmapped roles offer suggestions with an honest no-match state')
ok(/Mapped/.test(skills) && /Unmap/.test(skills) && /Change/.test(skills),
   'Mapped roles show status plus Change/Unmap actions')
ok(/Confirm/.test(skills) && /setCanonicalMapping\(role\.id, canonicalRoleId\)/.test(skills)
   && /setCanonicalMapping\(role\.id, null\)/.test(skills),
   'Confirmation and unmap both flow through the single write API (target or null)')

// ---- 4. Honesty: the panel never mutates the local role.
const panelStart = skills.indexOf('function RoleMappingPanel')
const panel = panelStart >= 0 ? skills.slice(panelStart, skills.indexOf('function CompanyRoles')) : ''
ok(panel.length > 0 && !/updateRole/.test(panel) && !/createRole/.test(panel)
   && !/updateStudent/.test(panel),
   'RoleMappingPanel never edits the local role, its skills, or student targets')
ok(panel.length > 0 && !/api\.roles\(\)\.then/.test(panel),
   'Panel does not silently persist anything on load (suggestions are ephemeral)')

// ---- 5. Contract + styles exist.
for (const cls of ['.rm-panel', '.rm-match', '.rm-bar-fill', '.rm-history', '.rm-conf-high']) {
  ok(css.includes(cls), `style ${cls} exists`)
}

if (problems.length) {
  console.error('Phase F company-role mapping contracts violated:')
  for (const p of problems) console.error('  - ' + p)
  process.exit(1)
}
console.log('Company role -> canonical role mapping (Phase F) contracts OK')