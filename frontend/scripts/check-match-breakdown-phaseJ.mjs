// Phase J — explainable match breakdowns — frontend source-contract guard.
// Covers: backend-mirroring types + API helpers; MatchBreakdown is a pure
// disclosures renderer (details/summary, no api import, no DOM by-id, no
// client-side score recompute); the three mounts wire each displayed match
// number to exactly one backend call; no breakdown helper leaks into App /
// AppContext wiring; job rows pass j.fingerprint.

import { readProject } from './path-helpers.mjs'

const read = readProject

const problems = []
const ok = (cond, msg) => { if (!cond) problems.push(msg) }

const types = read('frontend/src/lib/types.ts')
const api = read('frontend/src/lib/api.ts')
const comp = read('frontend/src/components/MatchBreakdown.tsx')
const dash = read('frontend/src/pages/DashboardPage.tsx')
const skills = read('frontend/src/pages/SkillsRolesPage.tsx')
const app = read('frontend/src/App.tsx')
const appCtx = read('frontend/src/AppContext.tsx')
const css = read('frontend/src/index.css')

// ---- 1. Types: payload shapes mirror match_explain.py.
for (const t of ['TargetRoleMatchBreakdown', 'RoleMatchBreakdown', 'JobMatchBreakdown',
  'MatchAdjustmentLine', 'MatchBreakdownPayload']) {
  ok(new RegExp(`export interface ${t} \\{`).test(types) || new RegExp(`export type ${t} =`).test(types),
    `${t} declared in types`)
}
ok(/contribution_points: number/.test(types) && /displayed_percent: number/.test(types),
   'requirement rows + displayed_percent mirror the backend payload')
ok(/is_discovery: boolean/.test(types) && /level_factor: number \| null/.test(types),
   'role-match requirement rows carry discovery + level factor')
ok(/location: \{ tier: string; label: string; supported: boolean \}/.test(types)
   && /work_type/.test(types) && /seniority/.test(types),
   'job constraints block exists')
ok(/fingerprint\?: string/.test(types), 'RecentJob carries fingerprint (Phase H field)')

// ---- 2. API: one helper per backend endpoint, exact paths.
ok(/targetRoleMatchBreakdown: \(studentId: number\)/.test(api)
   && /\/target-role-match\/breakdown/.test(api),
   'api.targetRoleMatchBreakdown -> GET /target-role-match/breakdown')
ok(/roleMatchBreakdown: \(studentId: number, roleId\?: number \| null, externalId\?: string \| null\)/.test(api)
   && /\/role-match\/breakdown\?/.test(api)
   && /role_id/.test(api) && /external_id/.test(api),
   'api.roleMatchBreakdown supports role_id OR external_id')
ok(/jobMatchBreakdown: \(studentId: number, fingerprint: string/.test(api)
   && /jobs\/recent\/\$\{encodeURIComponent\(fingerprint\)\}\/breakdown/.test(api),
   'api.jobMatchBreakdown -> GET /jobs/recent/{fingerprint}/breakdown')

// ---- 3. MatchBreakdown: native disclosure, pure render, never recomputes.
ok(/return\s*\(\s*<details/.test(comp)
   && /className="mxb"/.test(comp), 'renders a native disclosure element')
ok(/<summary/.test(comp), 'has a <summary> trigger')
ok(!/from '\.\.\/lib\/api'/.test(comp) && !/require\(/.test(comp),
   'component imports no api (fetching stays in the pages)')
ok(!/getElementById/.test(comp), 'no DOM by-id lookups in the component')
ok(!/Math\.round\(/.test(comp), 'no client-side score recompute in the component')
ok(/onRequest: \(\) => Promise<MatchBreakdownPayload> \| MatchBreakdownPayload/.test(comp),
   'component is driven by the page-provided payload request')
for (const cls of ['ev verified', 'ev self', 'ev none']) {
  ok(comp.includes(`'${cls}'`), `evidence badge renders ${cls}`)
}

// ---- 4. Mounts: every displayed match number has exactly one backend source.
ok(/<MatchBreakdown kind="target-role"/.test(dash)
   && /api\.targetRoleMatchBreakdown\(student\.id\)/.test(dash),
   'Dashboard target-role ring opens the target-role breakdown')
ok(/<MatchBreakdown kind="job"/.test(dash)
   && /api\.jobMatchBreakdown\(student\.id, j\.fingerprint/.test(dash),
   'JobsCard rows pass j.fingerprint into the job breakdown')
ok(/<MatchBreakdown kind="role"/.test(skills)
   && /api\.roleMatchBreakdown\(studentId, rec\.role_id, rec\.external_id\)/.test(skills),
   'rec deck cards open the role breakdown via role_id/external_id')

// ---- 5. Negative guard: breakdown helpers never leak into app wiring.
for (const [name, src] of [['App.tsx', app], ['AppContext.tsx', appCtx]]) {
  ok(!/targetRoleMatchBreakdown|roleMatchBreakdown|jobMatchBreakdown/.test(src),
     `${name} never calls a breakdown helper`)
}

// ---- 6. Styles exist.
for (const cls of ['.mxb summary', '.mxb-table', '.mxb-lines', '.mxb-pt', '.mxb-ev', '.mxb-chip', '.job-row']) {
  ok(css.includes(cls), `style ${cls} exists`)
}

if (problems.length) {
  console.error('Phase J match-breakdown contracts violated:')
  for (const p of problems) console.error('  - ' + p)
  process.exit(1)
}
console.log('Match breakdown (Phase J) contracts OK')