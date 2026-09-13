// Phase K — saved jobs + private application tracker — frontend source-contract guard.
// Covers: backend-mirroring types + API helpers; the save control lives next to
// each feed row and passes the row's own fingerprint + feed coordinates; the
// tracker panel is student-only UI calling ONLY tracker helpers (no
// updateStudent / no email / no external sync); delete is confirm-guarded and
// the panel can never see another student; archive is a stage transition, never
// a destroy.

import { readProject } from './path-helpers.mjs'

const read = readProject

const problems = []
const ok = (cond, msg) => { if (!cond) problems.push(msg) }

const types = read('frontend/src/lib/types.ts')
const api = read('frontend/src/lib/api.ts')
const dash = read('frontend/src/pages/DashboardPage.tsx')
const panel = read('frontend/src/components/JobTrackerPanel.tsx')
const css = read('frontend/src/index.css')
const main = read('backend/app/main.py')

// ---- 1. Types mirror the backend payload.
ok(/export type JobStage = 'saved' \| 'preparing' \| 'applied' \| 'screening' \| 'interview' \| 'offer' \| 'hired' \| 'rejected' \| 'withdrawn' \| 'archived_or_expired'/.test(types),
   'JobStage union = exactly the ten guide stages')
ok(/export const JOB_STAGES: JobStage\[\]/.test(types), 'JOB_STAGES constant exists')
for (const t of ['TrackedJob', 'TrackerResponse', 'TrackerStageHistory', 'SaveJobRequest']) {
  ok(new RegExp(`export interface ${t} \\{`).test(types), `${t} declared in types`)
}
ok(/stage: JobStage/.test(types) && /note: string/.test(types)
   && /interview_date\?: string/.test(types) && /history: TrackerStageHistory\[\]/.test(types),
   'tracked row carries stage/note/optional dates/history')

// ---- 2. API helpers: one per backend route, exact paths.
ok(/saveTrackedJob: \(studentId: number, payload: SaveJobRequest\)/.test(api)
   && /\/jobs\/saved/.test(api), 'api.saveTrackedJob -> POST /jobs/saved')
ok(/jobTracker: \(studentId: number\)/.test(api)
   && /\/jobs\/tracker\`/.test(api), 'api.jobTracker -> GET /jobs/tracker')
ok(/updateTrackerItem: \(studentId: number, trackerId: number, patch/.test(api)
   && /method: 'PATCH'/.test(api), 'api.updateTrackerItem -> PATCH /jobs/tracker/{id}')
ok(/deleteTrackerItem: \(studentId: number, trackerId: number\)/.test(api)
   && /method: 'DELETE'/.test(api), 'api.deleteTrackerItem -> DELETE /jobs/tracker/{id}')

// ---- 3. Backend routes exist (additive; own-student gating in main.py).
for (const route of ['/api/students/{student_id}/jobs/tracker',
                     '/api/students/{student_id}/jobs/saved']) {
  ok(main.includes(route), `backend route ${route} exists`)
}
ok(/def _tracker_or_http/.test(main), 'tracker errors map to HTTP codes')

// ---- 4. Dashboard: the save control passes the row's own fingerprint + coords.
ok(/api\.jobTracker\(me\.student\.id\)/.test(dash), 'JobsCard loads saved fingerprints via jobTracker')
ok(/saveTrackedJob\(me\.student\.id, \{ fingerprint: j\.fingerprint/.test(dash)
   && /location/.test(dash) && /country/.test(dash) && /market/.test(dash),
   'save button sends the feed row fingerprint + the current feed coordinates')
ok(/className=\{`job-save-btn\$\{savedFps\.has\(j\.fingerprint\) \? ' on' : ''\}`\}/.test(dash),
   'save button reflects tracked state per row')
ok(/<JobTrackerPanel student=\{student\}(?: refreshKey=\{\w+\})? \/>/.test(dash), 'tracker panel mounts on the dashboard')
ok(/refreshKey=\{trackerTick\}/.test(dash) && /setTrackerTick\(/.test(dash)
   && /setTrackerTick\(\(n\) => n \+ 1\)/.test(dash),
   'successful save bumps the tracker refresh counter so the panel re-fetches')

// ---- 5. Tracker panel: student-only helpers, no writes outside the tracker.
for (const call of ['api.jobTracker', 'api.updateTrackerItem', 'api.deleteTrackerItem']) {
  ok(panel.includes(call), `panel calls ${call}`)
}
ok(/useEffect\(\(\) => \{[\s\S]*?reload\(student\.id\)[\s\S]*?\}, \[student\?\.id, refreshKey\]\)/.test(panel),
   'panel re-fetches when the save counter changes')
ok(!/updateStudent|createRole|saveRole|unsaveRole/.test(panel),
   'panel never touches student/role write helpers')
ok(!/mailto:|nodemailer|sendEmail|smtp|cal\.|googleapis|outlook/.test(panel)
   && !/window\.open/.test(panel) && !/localStorage/.test(panel),
   'no email, calendar, external sync, or browser external escape in the panel')
ok(/window\.confirm/.test(panel), 'delete is confirm-guarded')
ok(!/getElementById/.test(panel) && !/document\./.test(panel), 'no imperative DOM in the panel')
ok(/companies and universities never see this/.test(panel)
   || /student_id: number/.test(panel), 'privacy guard present')
ok(panel.includes('archived_or_expired'), 'archive handled as a stage transition, never a destroy')

// ---- 6. Styles exist.
for (const cls of ['.job-save-btn', '.job-row-actions', '.tracked-panel', '.tracked-item',
                   '.tracked-badge', '.tracked-form', '.tracked-history']) {
  ok(css.includes(cls), `style ${cls} exists`)
}

if (problems.length) {
  console.error('Phase K job-tracker contracts violated:')
  for (const p of problems) console.error('  - ' + p)
  process.exit(1)
}
console.log('Job tracker (Phase K) contracts OK')