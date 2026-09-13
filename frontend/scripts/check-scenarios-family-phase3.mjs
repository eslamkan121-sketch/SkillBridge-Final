// Practice Scenarios — Phase 3 family generalization — frontend + backend
// source-contract guard.
// Covers: per-family scenario isolation (never another domain's scenarios),
// deterministic role-blueprints for out-of-family roles, family-honest cards
// (family/version fields + pill), versioned attempts, and honest empty states.

import { readProject } from './path-helpers.mjs'

const read = readProject

const problems = []
const ok = (cond, msg) => { if (!cond) problems.push(msg) }

const types = read('frontend/src/lib/types.ts')
const page = read('frontend/src/pages/ScenariosPage.tsx')
const css = read('frontend/src/index.css')
const scenarios = read('backend/app/scenarios.py')
const catalog = read('backend/app/scenario_catalog.py')
const main = read('backend/app/main.py')
const models = read('backend/app/models.py')
const database = read('backend/app/database.py')
const roleIntent = read('backend/app/role_intent.py')

// ---- 1. frontend types carry the family + version contract
ok(/family: string \| null/m.test(types) && /family_label: string \| null/m.test(types)
   && /family_icon: string \| null/m.test(types) && /version: number/m.test(types),
   'ScenarioCard exposes family / family_label / family_icon / version')

// ---- 2. card renders a family pill only when a label exists
ok(/scn\.family_label && <span className="scn-fam">/.test(page),
   'ScenarioCard renders the family pill only when family_label is present')
ok(/\.scn-fam \{/.test(css),
   'index.css defines the .scn-fam pill')

// ---- 3. honest empty-state remains (availability 'none', no content fallback)
ok(/availability === 'none'/.test(page) || /data\.availability === 'none'/.test(page)
   || /lib\.availability === 'none'/.test(page) || /availability !== 'ok'/.test(page),
   'ScenariosPage still honors the availability empty state')

// ---- 4. backend: catalog merge + family gating
ok(/SCENARIOS = _CORE_SCENARIOS \+ list\(scenario_catalog\.FAMILY_SCENARIOS\)/.test(scenarios),
   'scenarios.py merges the family catalog after the core cyber trio')
ok(/FAMILY_SCENARIOS = \[/.test(catalog) && /^\s+"family": "(?:data|software|ai|cloud_devops|marketing|finance|design|project_ops)",$/m.test(catalog),
   'scenario_catalog.py defines flat FAMILY_SCENARIOS with explicit family keys')
ok(/def family_for_title\(/.test(catalog) && /ROLE_FAMILY_BLUEPRINT\.get\(/.test(catalog),
   'scenario_catalog.py provides the curated family_for_title resolver')
ok(/def family_for_role\(/.test(scenarios) && /_role_intent_family_alias\(/.test(scenarios),
   'scenarios.py resolves role -> family (curated > terms > role_intent alias)')
ok(/Strict per-family isolation/.test(scenarios) && /def scenario_eligible\(/.test(scenarios)
   && /scenario\.get\("family"\) == fam/.test(scenarios),
   'scenario_eligible enforces strict per-family isolation once a family resolves')

// ---- 5. role-blueprints (out-of-family practice, never another domain)
ok(/def _blueprints_for\(/.test(scenarios) && /build_blueprint_scenarios\(/.test(scenarios)
   && /_BLUEPRINT_REGISTRY\[/.test(scenarios),
   'scenarios.py clones deterministic role blueprints for no-family roles')
ok(/def build_blueprint_scenarios\(/.test(catalog)
   && /"family": "generic"/.test(catalog) && /"role_title": role_title,/.test(catalog),
   'catalog builds generic-family blueprints that carry the role title')
ok(/def lookup_scenario\(/.test(scenarios) && /_blueprints_for\(student\)/.test(scenarios),
   'lookup_scenario resolves blueprint ids for a student')

// ---- 6. versioning flows into cards, start, player, results + DB
ok(/scenario_version/.test(database) && /scenario_version/.test(models)
   && /scenario_version=scenario\.get\("version"\) or scenario_catalog\.SCENARIO_VERSION/.test(scenarios),
   'scenario_version is plumbed through DB, models, and start_scenario')
ok(/"version": scenario\.get\("version"\) or scenario_catalog\.SCENARIO_VERSION/.test(scenarios),
   'public_scenario_card emits the scenario version')

// ---- 7. start route goes through lookup_scenario
ok(/scenario = scenarios\.lookup_scenario\(student, scenario_id\)/.test(main),
   'api_start_scenario resolves through lookup_scenario so blueprints start after a pivot')
ok(/classify_title\(/.test(roleIntent),
   'role_intent classifier still powers the family-less fallback gate')

if (problems.length) {
  console.error('Practice Scenarios family generalization (Phase 3) contract violations:')
  for (const problem of problems) console.error(`  - ${problem}`)
  process.exit(1)
}
console.log('Practice Scenarios family generalization (Phase 3) contracts OK')