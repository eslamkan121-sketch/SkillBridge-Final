// Phase L — Role Explorer UI — frontend source-contract guard.
// Covers: backend-mirroring types + API helpers (recents + role_data_version);
// the recently-viewed tab fetches ONLY via api.recentRoles and records views
// fire-and-forget inside openRoleDetails; the family facet is derived from real
// role data (Unclassified never invented); the search box is debounced and
// keyboard-navigable (highlight ring + sr-only live region, no focus theft);
// provenance + catalogue-data-version meta render only real data; the explorer
// hash state is read on mount + hashchange and written silently via replaceState.

import { readProject } from './path-helpers.mjs'

const read = readProject

const problems = []
const ok = (cond, msg) => { if (!cond) problems.push(msg) }

const types = read('frontend/src/lib/types.ts')
const api = read('frontend/src/lib/api.ts')
const page = read('frontend/src/pages/SkillsRolesPage.tsx')
const css = read('frontend/src/index.css')
const main = read('backend/app/main.py')
const models = read('backend/app/models.py')
const database = read('backend/app/database.py')

// ---- 1. Types mirror the backend payload.
ok(/family\?: string \| null/.test(types) && /source_version\?: string \| null/.test(types)
   && /canonical_status\?:/.test(types) && /role_key\?:/.test(types),
   'RoleRecord carries the additive canonical family/version/status/key fields')
ok(/role_data_version\?: string \| null/.test(types), 'RolesResponse carries role_data_version')
for (const t of ['RecentRole', 'RecentRolesResponse']) {
  ok(new RegExp(`export interface ${t} \\{`).test(types), `${t} declared in types`)
}
ok(/viewed_at: string/.test(types), 'RecentRole exposes the view timestamp')

// ---- 2. API helpers: exact backend paths.
ok(/recentRoles: \(studentId: number\)/.test(api) && /\/recent-roles\`/.test(api),
   'api.recentRoles -> GET /recent-roles')
ok(/recordRoleView: \(studentId: number, roleId: number\)/.test(api)
   && /\/recent-roles/.test(api) && /method: 'POST'/.test(api),
   'api.recordRoleView -> POST /recent-roles')

// ---- 3. Backend routes + version helper exist.
for (const route of ['/api/students/{student_id}/recent-roles']) {
  ok(main.includes(route), `backend route ${route} exists`)
}
ok(/def api_.*recent.roles/.test(main) && /record_role_view/.test(main),
   'backend records a view on the recents endpoint')
ok(models.includes('def roles_catalog_version'), 'backend roles_catalog_version exists')
ok(/MAX_ROLE_VIEW_EVENTS\s*=\s*30/.test(database), 'recents cap is fixed at 30 in database.py')

// ---- 4. Recently-viewed tab: fetch + record wiring only via the api helpers.
ok(/\[['"]recents['"],\s*['"]Recently Viewed['"]\]/.test(page), 'recents tab exists in the tablist')
ok(/api\.recentRoles\(student\.id\)/.test(page), 'recents list fetches via api.recentRoles only')
ok(/api\.recordRoleView\(student\.id, r\.id\)/.test(page)
   && /\.catch\(\(e\) => console\.error/.test(page),
   'openRoleDetails records the view fire-and-forget (never blocking / throwing)')
ok(/RecentRoleRow/.test(page), 'RecentRoleRow component renders per row')
ok(/!recentLoaded \?/.test(page) && /recentErr/.test(page) && /recentRoles\.length === 0 \?/.test(page),
   'recents tab has loading / error / honest-empty states')

// ---- 5. Family facet: derived from real role data only.
ok(/function roleFamily/.test(page) && /f \|\| 'Unclassified'/.test(page),
   'roleFamily groups missing families honestly as Unclassified')
ok(/family: \[\.\.\.new Set\(all\.map\(\(r\) => roleFamily\(r\)\)\)\]\.sort\(\)/.test(page)
   || /facetOptions\.family/.test(page), 'family facet options derive from the loaded roles')
ok(/toggleFilter\('family', f\)/.test(page), 'family facet toggles through the existing filter pipeline')
ok(/filters\.family\.map/.test(page), 'family active-filters chips render')
ok(/!facetOk\(roleFamily\(r\), filters\.family\)/.test(page), 'family filter gates the list')
ok(/roleFamily\(r\)/.test(page) && /\.join\(' '\)/.test(page), 'family label participates in search')

// ---- 6. Debounced search + keyboard navigation (no focus theft).
ok(/value=\{qDraft\}/.test(page) && /onChange=\{\(e\) => setQDraft\(e\.target\.value\)\}/.test(page),
   'search input is debounced via qDraft')
ok(/setTimeout\(\(\) => setQ\(qDraft\), 150\)/.test(page), 'debounce window is 150ms')
ok(/ArrowDown/.test(page) && /ArrowUp/.test(page) && /Escape/.test(page) && /Enter/.test(page),
   'keyboard nav handles Up, Down, Enter, Escape')
ok(/highlight ring/i.test(css) || /\.srb-card-wrap\.srb-hl/.test(css), 'srb-hl highlight ring styled')
ok(new RegExp("Highlighted \\$\\{paged\\[hlIndex\\].r.title\\}").test(page)
   || /role="status" aria-live="polite"/.test(page), 'sr-only live region announces the highlight')
ok(/onKeyDown=\{onSearchKeyDown\}/.test(page), 'search input wires the keyboard handler')

// ---- 7. Provenance + catalogue-data-version meta only from real data.
ok(/function sourceProvenance/.test(page) && /'ESCO import'/.test(page)
   && /'Canonical catalogue'/.test(page), 'provenance labels derive from real role source fields')
ok(/sourceProvenance\(r, dest\)|sourceVersionMeta\(r\)/.test(page), 'cards render provenance + version meta')
ok(/Catalogue data v\{roleDataVersion\}/.test(page)
   && /roleDataVersion ? <span className="srb-cat-version"/.test(page)
   || (page.includes('Catalogue data v{roleDataVersion}') && page.includes('srb-cat-version')),
   'catalogue-version meta shows only when the backend reports a real version')

// ---- 8. Deep-link hash state (L5): read + write, never a crash on bad input.
ok(/function parseExplorerHash/.test(page) && /function serializeExplorer/.test(page),
   'explorer hash parse/serialize helpers exist')
ok(/parseExplorerHash\(window\.location\.hash\)/.test(page), 'hash read once at mount')
ok(/addEventListener\('hashchange'/.test(page), 'back/forward hash changes re-apply state')
ok(/history\.replaceState\(null, '', hash\)/.test(page), 'hash written silently (no hashchange loop)')
ok(/malformed input is ignored, never a crash|Malformed.hash/i.test(page) || /if \(!hash \|\| !hash\.startsWith\('#explorer'\)\) return out/.test(page),
   'malformed hash is ignored, never a crash')

// ---- 9. Styles exist.
for (const cls of ['.srb-cat-version', '.srb-card-wrap.srb-hl', '.srb-recent-row', '.srb-recent-list',
                   '.srb-recent-title', '.srb-recent-when', '.srb-recent-actions', '.sr-only']) {
  ok(css.includes(cls), `style ${cls} exists`)
}

if (problems.length) {
  console.error('Phase L role-explorer contracts violated:')
  for (const p of problems) console.error('  - ' + p)
  process.exit(1)
}
console.log('Role Explorer (Phase L) contracts OK')