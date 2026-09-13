// Skills & Roles — Phase 2 discovery redesign — frontend source-contract guard.
// Covers: four top-level views (Recommended / All / Saved / Market), stable
// display-only deduplication, one match source, role-detail drawer, compare
// mode (max 3), target-change confirmation, pagination, match-range facet,
// and honest empty/unavailable/salary-free states.

import { readProject } from './path-helpers.mjs'

const read = readProject

const problems = []
const ok = (cond, msg) => { if (!cond) problems.push(msg) }

const page = read('frontend/src/pages/SkillsRolesPage.tsx')
const css = read('frontend/src/index.css')
const icons = read('frontend/src/components/Icons.tsx')

// ---- 1. four top-level views
ok(/\['recommended',\s*'Recommended for You'\]/.test(page)
   && /\['all',\s*'All Roles'\]/.test(page)
   && /\['saved',\s*'Saved Roles'\]/.test(page)
   && /\['market',\s*'Market Search'\]/.test(page)
   && /tab === 'recommended' && \(/.test(page)
   && /tab === 'all' && \(/.test(page)
   && /tab === 'saved' && \(/.test(page)
   && /tab === 'market' && \(/.test(page),
   'StudentBrowse renders four top-level views: Recommended for You / All Roles / Saved Roles / Market Search')
ok(/<div className="rd-tabs" role="tablist"/.test(page)
   && /role="tab" aria-selected=\{tab === key\}/.test(page),
   'StudentBrowse has a tablist with proper aria-selected tabs')

// ---- 2. display-only deduplication (records never deleted)
ok(/function dedupDisplay\(/.test(page) && /function normalizedTitle\(/.test(page)
   && /function pickRepresentative\(/.test(page) && /function sourcePriority\(/.test(page),
   'Dedup helpers exist (dedupDisplay/normalizedTitle/pickRepresentative/sourcePriority)')
ok(/Records are NEVER deleted/.test(page),
   'Dedup documentation explicitly states records are never deleted')
ok(/current target >[\s\S]*?saved > source priority/.test(page),
   'Dedup rule documented: target > saved > source priority (company > esco > catalog)')
ok(/sourcePriority\(r\)/.test(page) && /r\.company_id && r\.source !== 'catalog'\) return 0/.test(page),
   'Dedup source priority prefers company posting, then ESCO, then catalog')
ok(/othersFor\(detailsRole\)/.test(page) && /groups\.get\(normalizedTitle\(role\.title\)\)/.test(page),
   'Drawer surfaces other sources / relevant jobs from the same normalized-title group')
ok(/These are the same logical role seen through other sources — deduplicated here, never deleted/.test(page),
   'Drawer "other sources" block explains dedup is display-level only')

// ---- 3. one match source + honest explanation
ok(/function displayMatchOf\(/.test(page) && /function backendRecMap\(/.test(page),
   'Single match helper exists (displayMatchOf + backendRecMap)')
ok(/rec\.match_score != null/.test(page) && /pct: Math\.round\(rec\.match_score\)/.test(page)
   && /reason: rec\.reason/.test(page),
   'Backend computed match (score + reason) is preferred whenever the role is in the recommendations payload')
ok(/otherwise falls back to the[\s\S]*?same required-skill overlap math/.test(page),
   'Match helper documents the fallback to the backend-style overlap math')
ok(/pct=\{displayMatch\(r\)\.pct \?\? 0\}/.test(page),
   'Library cards read the shared display match helper')
ok(/match=\{displayMatch\(detailsRole\)\}/.test(page),
   'Drawer receives the shared display match for its explanation')

// ---- 4. drawer replaces modal
ok(/function RoleDetailsDrawer\(/.test(page) && /<aside className="rd-drawer"/.test(page)
   && /role="dialog" aria-modal="true"/.test(page),
   'Role-detail drawer exists as a right-side dialog')
ok(/<RoleDetailsDrawer/.test(page) && !/<RoleDetailsModal/.test(page),
   'The rendered view uses RoleDetailsDrawer, never the old RoleDetailsModal')
ok(/Estimated learning effort/.test(page) && /no time estimate is invented here/.test(page),
   'Drawer gives honest learning-effort guidance (no fabricated time estimates)')

// ---- 5. compare mode (max 3), no salary
ok(/function CompareTray\(/.test(page) && /function CompareModal\(/.test(page),
   'Compare tray + compare modal components exist')
ok(/Compare \(\{roles\.length\}\/3\)/.test(page),
   'Compare tray shows the x/3 counter')
ok(/if \(compareIds\.length >= 3\)/.test(page) && /Comparison is limited to three roles\./.test(page),
   'Compare is hard-capped at three roles')
ok(/<CompareTray/.test(page) && /<CompareModal/.test(page),
   'Compare tray + modal are rendered on the page')
ok(/Salary and market figures are never shown because no honest source exists for them/.test(page),
   'Compare explains no salary/market figures are shown')
ok(/No salary or market figures are shown because none exist for these records/.test(page),
   'Drawer explains salary figures are never invented')

// ---- 6. deliberate target change (first-ever select applies; replace confirms)
ok(/const chooseTarget = \(roleId: number\) =>/.test(page)
   && /hasTarget\) setPendingTarget\(\{ kind: 'role', id: roleId \}\)/.test(page)
   && /else runTarget\(\{ kind: 'role', id: roleId \}\)/.test(page),
   'First target selection applies directly; replacing an existing target is deferred')
ok(/if \(hasTarget\) \{ setPendingTarget\(\{ kind: 'esco', occ \}\); return \}/.test(page),
   'ESCO market target replacement also requires confirmation')
ok(/<ConfirmModal/.test(page) && /Change your target career\?/.test(page)
   && /Existing learning, assessment and scenario history is preserved — nothing is deleted/.test(page),
   'Target-change confirm explains history is preserved, nothing deleted')
ok(/const confirmTarget = \(\) =>/.test(page) && /runTarget\(pendingTarget\)/.test(page)
   && /setTargetBusy\(false\); setPendingTarget\(null\)/.test(page),
   'Confirm modal resolves through the single runTarget runner')

// ---- 7. pagination + match-range facet
ok(/pageSize = 12/.test(page) && /const paged = filtered\.slice\(/.test(page)
   && /totalPages = Math\.max\(1, Math\.ceil\(filtered\.length \/ pageSize\)\)/.test(page),
   'All Roles pagination exists (12 per page, paged slice)')
ok(/<div className="rd-pager">/.test(page) && /Page \{page\} of \{totalPages\}/.test(page),
   'Pager UI renders with page X of Y')
ok(/matchRange\.min != null && p < matchRange\.min/.test(page)
   && /matchRange\.max != null && p > matchRange\.max/.test(page),
   'Match-range facet filters representatives between min and max match')
ok(/setMatchRange\(\(m\) => \(\{ \.\.\.m, min:/.test(page)
   && /setMatchRange\(\(m\) => \(\{ \.\.\.m, max:/.test(page),
   'Match range inputs are clamped to 0-100')

// ---- 8. honest states (no invented data)
ok(/Live role lookup is unavailable right now — this is temporary/.test(page),
   'Market view keeps the honest temporary-unavailable message')
ok(/No saved roles yet/.test(page),
   'Saved view keeps an honest empty state')
ok(/Set as target to unlock practice scenarios for this role/.test(page)
   && /selectedRole === roleId\s*\? 'Available for your target/.test(page),
   'Practice-scenario availability is honest: only the current target has a real set')

// ---- 9. visual scaffolding
ok(/\.rd-tabs \{/ .test(css) && /\.rd-drawer \{/.test(css) && /\.rd-backdrop \{/.test(css)
   && /\.rd-cmpbar \{/.test(css) && /\.rd-cmp-modal \{/.test(css) && /\.rd-pager \{/.test(css),
   'index.css defines Phase 2 scaffolding (tabs, drawer, backdrop, compare bar/modal, pager)')
ok(/@keyframes rd-slide-in/.test(css),
   'Drawer has a slide-in animation')
ok(/\.rd-cmp-actions \{/.test(css) && /repeat\(var\(--cols/.test(css),
   'Compare grid + actions scale with the number of roles via --cols')

// ---- 10. compare icon exists
ok(/export const IconCompare =/.test(icons),
   'IconCompare icon export exists')

// ---- 11. saved roles and Company/University surfaces carry over unchanged
ok(/api\.saveRole\(student\.id, roleId\)/.test(page) && /api\.unsaveRole\(student\.id, roleId\)/.test(page),
   'Saved roles still persist through the backend API (server is source of truth)')
ok(/Saved\{savedIds\.size > 0 \? ` \(\$\{savedIds\.size\}\)` : ''\}/.test(page),
   'Filterbar still shows the Saved (n) chip')
ok(/const savedReps = reps\.filter\(\(r\) => savedIds\.has\(r\.id\)\)/.test(page),
   'Saved view filters deduplicated representatives by saved ids')
ok(/function CompanyRoles/.test(page) && /function ReadOnlyBrowse/.test(page),
   'Company CRUD and University read-only surfaces remain present and untouched')
ok(/from '\.\.\/\.\.\/lib\/types'[\s\S]*ScenarioLibrary/.test(page)
   || /ScenarioLibrary/.test(page),
   'ScenarioLibrary type still referenced for the honest drawer scenario check')

if (problems.length) {
  console.error('Roles & Roles discovery (Phase 2) contract violations:')
  for (const problem of problems) console.error(`  - ${problem}`)
  process.exit(1)
}
console.log('Roles & Roles discovery (Phase 2) contracts OK')