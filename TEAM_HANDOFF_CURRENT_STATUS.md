# SkillBridge — Current Team Handoff

**Updated:** 13 September 2026  
**Current boundary:** Phases A–N complete. Phase O (Build Your Copilot) complete — code + tests + frontend build + in-memory E2E smoke; live deploy/restart still pending. **Phase P (Copilot onboarding quiz + settings picker) complete** — code + tests + build + checker + in-memory E2E smoke; live deploy/restart still pending.

## What is complete

### Foundation and data integrity (A–H)

- Baseline/audit, ordered SQLite migrations, request IDs, and compatibility safeguards.
- Session/auth hardening: hashed session tokens, expiry, revocation, password-reset invalidation, and rate limits.
- Canonical role/skill model, controlled ESCO import workflow, and company-to-canonical-role mapping.
- Provider-aware jobs cache, job normalization/deduplication, safe application-link handling, and honest cache/failure states.

### Student journey and jobs experience (I–N)

- Provider health diagnostics and redacted status reporting.
- Explainable target-role and job-match breakdowns.
- Private saved-jobs/application tracker with auditable stage history.
- Role Explorer with recently viewed roles, search/family filters, and role provenance.
- Role details, comparison, related roles, and career-transition views.
- Jobs Board: client-side search/filtering/pagination, mobile filter drawer, tracker-state filters, safe external application links, link-report audit records, cached/stale banners, and a secret-free provider-health dialog.

### Phase O — Build Your Copilot

- Per-student `copilot_config` (single-row, personal choice + personality + capabilities), Migration `0009_copilot_config`.
- Exactly three copilot starting points (Navigator→nova, Strategist→axel, Confidant→sage); Vex excluded; all four capabilities enabled; personality snapshotted at creation.
- `GET/PUT/DELETE /api/students/{student_id}/copilot`; PUT syncs the tutor preference so the SPA tutor + voice follow the copilot; chat composes "You are The Navigator" etc. from the config.
- Wired `frontend/public/build-your-copilot.html` (also in `dist/`): cards rendered from the backend options, live preview, create/update/remove, status banner, honest unauthorized/done states.
- Discoverable in-app: the student sidebar now shows "AI Copilot" (`App.tsx` nav link → `/build-your-copilot.html`); rest of the SPA untouched.

### Phase P — Copilot onboarding quiz + settings picker

- First-run onboarding: a student with `copilot_onboarding.state == 'not_started'` gets a one-time quiz (3 questions, exactly 3 outcomes) that assigns their starting copilot; can be skipped/persisted as the navigator default, or dismissed session-only (state stays `not_started` and re-asks next session). Migration `0010_copilot_onboarding`.
- Onboarding state lives in a SEPARATE table (`copilot_onboarding`, PK student_id → `students` CASCADE) so `DELETE copilot` never resets only-ask-once. `state` CHECK `not_started|completed|skipped`, `source` CHECK `quiz|skip|manual_change`, `quiz_answers_json` DEFAULT `'[]'`, `answered_at` TEXT.
- Student-scoped endpoints (ownership-gated, guest 401 / cross-student + company + university 403): `GET /api/students/{id}/copilot/onboarding-state` (never returns 404 — synthetic `not_started` row when absent) and `POST /api/students/{id}/copilot/onboarding` (`{answers: [3 keys]}` → complete + assign, `{skipped:true}` → navigator + `skip`, optional `choice` validated but recomputed-over). Server ALWAYS recomputes the winner from the submitted 3-answer tally (ties/`choice`-mismatch → default `navigator`); answers persisted, preference tutor id pinned to the winner's voice agent (navigator→nova, strategist→axel, confidant→sage).
- `PUT /api/students/{id}/copilot` now calls `mark_copilot_manual`: source `manual_change`; a manually built copilot also marks the onboarding row completed so the first-run modal never appears after the student chose in settings.
- Frontend single source of truth `frontend/src/lib/copilotArchetypes.ts` (SPA mirror of `copilot.ONBOARDING_QUESTIONS`/`score_archetype`): exactly three keys, `COPILOT_ARCHETYPES` (name/personality/desc/voice), `COPILOT_QUESTIONS` (3×3 options voting a key), `tallyAnswers` + `forcedAnswers` (result screen "Choose this instead" substitutes the picked key into the submitted set — honest by construction, the server never trusts a raw `choice`).
- `CopilotOnboarding.tsx` auto-shows for `not_started` students (non-blocking overlay, dismissible session-only); welcome → Q1–Q3 (aria-pressed options, "Question X of 3" live region, progress segments) → result (preview from the local tally, compare-all-three grid, "Choose this instead", Continue). Skip and in-flow "Skip for now" are ONE action → `{skipped:true}`; finish POSTs the answer set. `forceOpen` prop supports Settings' "Retake the quiz" even after completion. No browser-side persistent storage, no provider/voice calls.
- `CopilotSettingsModal.tsx` ("Change your copilot" in the student account menu): 3-card picker from `COPILOT_ARCHETYPES`, pre-selects the stored config, Save → `api.setCopilot` (persists + marks manual), "Retake the quiz" → reopens the onboarding flow. Mounted with CopilotOnboarding in `App.tsx` gated `role === 'Student' && !assessmentActive && !authBanner` (waits for the auth success animation).
- Set-up copy follows the owner-approved demo text; questions/options now match the demo exactly (`copilot.ONBOARDING_QUESTIONS` is the canonical copy, the SPA module mirrors it; a runtime checker enforces the sync).

## Current database migrations

`0001` through `0010_copilot_onboarding` are present in this working copy. Migration `0009` adds only the private per-student `copilot_config` table; `0010` adds only the private per-student `copilot_onboarding` table; neither removes or rewrites existing data.

## Latest verification

- Phase O focused backend/copilot contracts: **25 passed** (`test_copilot_build_phaseO.py`).
- Phase O migration-assertion bumps across 8 legacy files: **118 passed** — this also fixed the **4 pre-existing failures** Phase N left behind.
- Phase O tutor/persona regression suites (personas v2, modes, language, conversations, profiles): **152 passed**, zero regressions.
- TypeScript and Vite production build: **passed** (Phase P additions included; same non-failing large-bundle warning).
- In-memory E2E smoke: student login → `/api/auth/me` → copilot CRUD → tutor preference shows copilot + nova/axel/sage → POST tutor 200 → served `build-your-copilot.html` wired → company scoped 403. **Green.**
- Phase P suite: `test_copilot_onboarding_phaseP.py` **44 passed**; combined migration/legacy run (10 files incl. phaseO + all bumped suites): **187 passed**, zero regressions.
- Phase P checker `check-copilot-onboarding-phaseP.mjs` + runtime wrapper `test_runtime_copilot_onboarding_phaseP_frontend.py`: **green** (1 passed).
- Phase P in-memory E2E smoke: aisha `not_started` → POST quiz → `completed` + assigned navigator → tutor preference `tutor_id nova` == copilot voice → home page serves. **Green.**
- Accepted edge case: deterministic/offline identity fallbacks still answer as the voice agent (e.g. Nova), not the copilot name — only reachable when the provider is down.
- The Vite build still emits a non-failing large-bundle warning; performance/code splitting is Phase S work.

## What remains

- ~~O: genuinely role-specific dashboards~~ — **completed as "Build Your Copilot"** per the planning handoff; role-specific dashboards may return as a follow-up candidate.
- ~~**P:** profession-aware scenario expansion~~ — **completed as Copilot onboarding quiz + settings picker** (first-run quiz wiring + archetype-consistent config); the phase letter now maps to this feature. Profession-aware scenario expansion may return as a later candidate.
- **Q:** unified learning-to-application journey.
- **R:** accessibility, Arabic RTL, responsive/visual consistency.
- **S:** performance and safe observability.
- **T:** independent fresh-session review, no edits.
- **U:** complete offline and live verification.
- **V:** final reports and private delivery package.

## Current product limitation: high-volume Egypt jobs

The existing board is a reliable normalized feed, but it is not yet a high-volume Egypt-first search engine. The next jobs initiative should add an approved Egypt/MENA provider such as Careerjet Egypt and, if available by agreement, WUZZUF/Forasna; import results in scheduled background jobs; store/deduplicate them in a searchable database; then use 10-second client updates only to report newly-imported records. Do not scrape protected job boards or call providers every 10 seconds.

## Security and packaging rule

- The GitHub repository is **source only**: no `.env`, database, uploads, virtual environments, dependencies, or generated build files.
- The private environment file is transferred separately and must never be committed or pasted into chat/issues.
- Rotate any credential that has previously been shared or committed.

## Start here

1. Read `AGENTS.md` and this file.
2. Review `JOB_BOARD_PHASEN_PLAN.txt` for the completed board contract; `COPILOT_ONBOARDING_WIRING_PLAN.txt` for Phase P.
3. Phases O + P (Build Your Copilot + onboarding wiring) are complete — `AGENTS.md`'s Phase O/P sections and this file are the source of truth; live restart is the only pending deploy step. Next frontier: Q (unified learning-to-application journey) or the Egypt-first job-search platform — agree which before starting.
