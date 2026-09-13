// Phase M — Role details, comparison & career transitions — frontend source guard.
// Locks: backend-mirroring types + api.roleProvenance route; the drawer federates
// ONLY sourced data (essential/optional via real skill_kind, verified/self/none
// from the student payload, aliases never hidden-invented, honest deprecation
// banner), related roles come ONLY from api.roleProvenance and render as a
// list/table (no graph, no salary/probability/timing), available jobs come ONLY
// from the once-per-mount api.recentJobs feed (provider + freshness chips), and
// the compare modal adds shared/unique skills, an evidence-based covered split,
// and a live-jobs row without recomputing scores.

import { readProject } from './path-helpers.mjs'

const read = readProject

const problems = []
const ok = (cond, msg) => { if (!cond) problems.push(msg) }

const types = read('frontend/src/lib/types.ts')
const api = read('frontend/src/lib/api.ts')
const page = read('frontend/src/pages/SkillsRolesPage.tsx')
const css = read('frontend/src/index.css')
const models = read('backend/app/models.py')

const drawerStart = page.indexOf('function RoleDetailsDrawer')
const drawerEnd = page.indexOf('// Fixed bottom tray listing the roles queued')
const drawer = page.slice(drawerStart, drawerEnd < 0 ? page.length : drawerEnd)
const cmpStart = page.indexOf('function CompareModal')
const cmpNextFunc = page.indexOf('\n// -', cmpStart)
const compare = page.slice(cmpStart, cmpNextFunc < 0 ? page.length : cmpNextFunc)

// ---- 1. Types + api mirror the backend payload.
for (const t of ['RoleProvenance', 'RoleRelated', 'RoleAlias', 'RoleIscoCode', 'RoleSkillSource']) {
  ok(new RegExp(`export interface ${t} \\{`).test(types), `${t} declared in types`)
}
ok(/roleProvenance: \(roleId: number\)/.test(api) && /\/api\/roles\/\$\{roleId\}\/provenance/.test(api),
   'api.roleProvenance hits GET /api/roles/{id}/provenance')

// ---- 2. Backend related-role graph rides along additively on provenance.
ok(models.includes('def related_roles('), 'backend related_roles exists')
ok(/"related": related_roles\(role\["id"\]\)/.test(models), 'provenance payload carries additive related')

// ---- 3. Drawer federates only sourced data.
ok(/api\.roleProvenance\(detailsRole\.id\)/.test(page), 'drawer fetches provenance when a role opens')
ok(/for \(const s of student\?\.verified_skills \?\? \[\]\) verified\.add/.test(page),
   'verified evidence set built ONLY from student.verified_skills')
ok(/for \(const s of student\?\.self_reported_skills \?\? \[\]\) self\.add/.test(page),
   'self-reported evidence set built ONLY from student.self_reported_skills')
ok(/s\.skill_kind === 'essential'/.test(drawer) && /s\.skill_kind === 'optional'/.test(drawer),
   'essential/optional grouping driven by the real skill_kind column')
ok(/a\.alias_type !== 'hidden'/.test(drawer), 'hidden aliases never shown in "Also known as"')
ok(/role\.canonical_status !== 'active'/.test(drawer) && /never appear among career-transition suggestions/i.test(drawer),
   'deprecation banner is honest and sourced')
ok(/No salaries, probabilities, or timing are ever invented/.test(drawer),
   'careers section explicitly refuses invented numbers')
ok(/api\.recentJobs\(/.test(page) && /jobsFeedFired\.current/.test(page),
   'available-jobs section uses api.recentJobs once per mount (no per-open provider storms)')
ok(/'listing_status'/.test(drawer) || /j\.listing_status/.test(drawer), 'jobs row uses real listing_status')
ok(/j\.provider/.test(drawer) && /j\.listed_days_ago/.test(drawer), 'jobs row shows provider + freshness')
ok(/onOpenRole\(r\)/.test(drawer) && /rd-related-row/.test(drawer), 'related roles render as buttons in a table, no graph')
ok(/"related": provenance\?\.related \?\? \{/.test(drawer) || /provenance\?\.related\?\.parent/.test(drawer),
   'related groups read from provenance.related only')
ok(/target="_blank" rel="noopener noreferrer"/.test(drawer), 'job links open safely, never auto-opened')

// --- 4. Compare modal: shared/unique, evidence split, live jobs — never a score re-compute.
ok(/Shared skills/.test(compare), 'compare has a Shared skills row')
ok(/Unique to/.test(compare), 'compare has per-role Unique rows')
ok(/evidence\.verified\.has/.test(compare) && /verified · \{self\}/.test(compare),
   'covered-skill row splits verified vs self-reported evidence')
ok(/Live jobs/.test(compare) && /jobCountFor\(r\.id\)/.test(compare), 'compare has a Live jobs row via jobCountFor')
ok(/Comparison is limited to three roles/.test(page), 'compare cap stays at 3')

// ---- 5. No score recomputation and no mutation in the new surfaces.
ok(!/Math\.round\(/.test(drawer), 'drawer never recomputes/rounds a match percentage itself')
ok(!/Math\.round\(/.test(compare), 'compare modal never recomputes/rounds a match percentage itself')
ok(!/api\.updateStudent\(/.test(drawer) && !/api\.updateStudent\(/.test(compare), 'drawer/compare never mutate the student')
ok(!/api\.createRole\(/.test(drawer) && !/api\.updateRole\(/.test(drawer), 'drawer never mutates roles')
ok(!/d3/.test(page) && !/from 'graph/.test(page), 'no graph library is pulled in')

// ---- 6. Styles exist.
for (const cls of ['.rd-ev.verified', '.rd-ev.self', '.rd-ev.none', '.rd-deprecated', '.rd-aliases',
                   '.rd-related-row', '.rd-related-label', '.rd-jobs', '.rd-job-title', '.rd-ls-live', '.rd-ls-expired']) {
  ok(css.includes(cls), `style ${cls} exists`)
}

if (problems.length) {
  console.error('Phase M role-details contracts violated:')
  for (const p of problems) console.error('  - ' + p)
  process.exit(1)
}
console.log('Role Details & Comparison (Phase M) contracts OK')