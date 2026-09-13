// Phase N — Jobs Board source-contract guard.
import { readProject } from './path-helpers.mjs'

const problems = []
const ok = (condition, message) => { if (!condition) problems.push(message) }
const dash = readProject('frontend/src/pages/DashboardPage.tsx')
const api = readProject('frontend/src/lib/api.ts')
const types = readProject('frontend/src/lib/types.ts')
const main = readProject('backend/app/main.py')
const models = readProject('backend/app/models.py')
const database = readProject('backend/app/database.py')
const css = readProject('frontend/src/index.css')

for (const type of ['JobLinkReport', 'JobsHealthPayload']) {
  ok(types.includes(`export interface ${type}`), `${type} mirrors the API payload`)
}
ok(api.includes('jobsHealth:') && api.includes('/api/config/demo-mode'), 'provider health helper uses config status endpoint')
ok(api.includes('jobLinkReports:') && api.includes('/jobs/link-reports'), 'private link-report list helper exists')
ok(api.includes('reportDeadJobLink:') && api.includes('/report-dead-link'), 'link-report write helper exists')

ok(main.includes('/jobs/link-reports') && main.includes('/report-dead-link'), 'private report routes exist')
ok(models.includes('def report_job_link') && database.includes('UNIQUE(student_id, fingerprint)'), 'link reports are student-private and idempotent')
ok(dash.includes('jobn-filterbar') && dash.includes('pagedJobs') && dash.includes('pageCount'), 'search/filter/pagination UI exists')
ok(dash.includes('Provider status') && dash.includes('jobsHealth'), 'provider-status drawer exists')
ok(dash.includes('rel="noopener noreferrer"'), 'external application links are safely isolated')
ok(dash.includes('Report link') && dash.includes('reportDeadJobLink'), 'per-job link reporting is visible')
ok(dash.includes("onNavigate?.('skills')"), 'Prepare action moves to the real Skills hub')
for (const selector of ['.jobn-filterbar', '.jobn-pages', '.jobn-modal-backdrop', '.jobn-health']) {
  ok(css.includes(selector), `responsive style exists for ${selector}`)
}

if (problems.length) {
  console.error('Phase N jobs-board contracts violated:')
  for (const problem of problems) console.error(`  - ${problem}`)
  process.exit(1)
}
console.log('Phase N Jobs Board contracts OK')
