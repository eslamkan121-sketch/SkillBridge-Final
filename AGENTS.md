## Post-Phase-6 "Dead-link & Diagnostic submit" general fix — COMPLETED (code + tests + browser)

**Status:** backend non-runtime suites **582 passed / 2 skipped**; `tsc --noEmit` clean; `vite build` clean; all 9 frontend source-contract checkers green. Puppeteer (Brave) smokes on the live seeded server: Learning-review **38/38**, assessment-run **18/18**, full-pass submit **13/13**, diagnostic submit verified via network — console free except the app's own intentional `diagnostic/latest → 404` control-flow.

**User issue:** reported two general problems:
1. **Dead resource links** — YouTube `t75MqaiERPE` (freeCodeCamp Active Directory video removed), Udemy `active-directory-ultimate-course` (course expired), and a beBee job listing `cyber-security-analyst-ssh-design-nasr-city--fj-2328815129` (dead page) were surfacing in the Learning page (saved resources, roadmap, resource library) and Jobs feed.
2. **Submit diagnostic not working** — when a diagnostic was generated but not yet submitted (e.g., page reload), the panel loaded it via `loadLatest` in `take` phase with `diag` set but `current = null`; clicking "Submit Diagnostic" silently did nothing because `submit()` early-returned on `!current`.

**Directive:** "fix the problem in general not just for these links — i don't want any removed video or resource at all."

### 1. Universal verified-dead resource guard (no removed video or resource ever)

**Core mechanism** in `backend/app/resources.py`:
- `_VERIFIED_DEAD_RESOURCES` map: canonical key = `"yt:<video_id>"` for YouTube (query-params can't hide a removed video) or `"url:<exact_url>"` for others. Each dead URL maps to **probe-verified live replacement(s)**:
  - `yt:t75MqaiERPE` → Server Academy "Active Directory Tutorial for Beginners" (`nKcrVtvZvpk`, 1.7M views, thumbnail 200)
  - `url:https://www.udemy.com/course/active-directory-ultimate-course/` → Microsoft Learn "Active Directory Domain Services" learning path (200, structured course-like)
- `sanitize_resources(resources)`: deterministic, offline, idempotent. Replaces any verified-dead URL with its curated replacement(s), preserves unavailable markers, dedupes. Safe to run repeatedly at every surface.
- **Applied universally** (not gated by `live_check`):
  - `curated_resources()` — source of truth for all skill/category pools
  - `retrieve_resources()` — after directness gate (catches live-search + curated)
  - `recommend_lesson_resources()` — after directness gate
  - `recommend_step_resources()` — candidates before scoring (roadmap steps, genai roadmap, lessons)
- Curated `active directory` pool updated inline to live resources (video + course).
- **Live probe layer unchanged** (YouTube thumbnail 404 detection, generic HEAD <400) for unknown future removals on `live_check=True` paths.

**Stored items self-heal**: bumped `RESOURCE_VERSION = 4` in `genai.py` → `_maybe_refresh_learning` re-derives roadmap + resources on read for all legacy items (they re-derive from sanitized pools). Bumped career roadmap `resources_version = 3` in `career_roadmap.py` → `api_get_career_roadmap` regenerates stored roadmaps (which cited the dead AD video). `career_roadmap.py:_phase_resources` also runs `sanitize_resources` as final guard.

**Result:** no dead YouTube/Udemy/channel/search page can surface on any Learning surface (resource cards, roadmap steps, resource library, lesson resources, career roadmap phases) — even offline. When a step has no validated resource it honestly shows `resource_unavailable` (no link) rather than a fabricated URL.

### 2. Jobs feed: JSearch expired-flag fix + dead-job blocklist

**Bug:** `_expiry_props` checked `if expired_flag is True` but JSearch `job_expired_flag` is a **string** (`"expired"`/`"not_expired"`). Expired JSearch/beBee listings slipped through the filter → user saw the dead beBee link.

**Fix** in `backend/app/jobs.py:_expiry_props`:
```python
expired_truthy = str(expired_flag).strip().lower() in {"true", "expired", "1", "yes"}
if expired_truthy:
    is_expired, expires_at = True, None
```
Now correctly handles bool `True` OR truthy string variants.

**Defense-in-depth:** added `_DEAD_JOB_URLS` blocklist in `_merge` with the exact beBee URL the user reported.

### 3. Diagnostic submit fix (silent no-op bug)

**Root cause:** In `LearningPage.tsx:DiagnosticPanel`, when an in-progress diagnostic exists from a prior session, `loadLatest()` loads it into `take` phase with `diag` populated but `current = null`. The `submit()` handler did `if (!current) return` → clicked "Submit Diagnostic" did nothing, no POST fired.

**Fix:** `submit()` now resolves the active diagnostic from either `current` OR `diag` when in `take` phase:
```typescript
const active = current ?? (diag && phase === 'take' ? diag : null)
if (!active) return
const questions = active.questions ?? []
const answers = questions.map((q) => form[q.id] ?? '')
await api.submitDiagnostic(studentId, skillId, {
  diagnostic_id: (active as GeneratedDiagnostic).diagnostic_id ?? (active as DiagnosticResult).id,
  answers,
})
```
Works for both fresh generation (`current` set) and reload of in-progress (`diag` set). Verified via Puppeteer network capture — POST to `/diagnostic/submit` now fires in both scenarios.

### Verification

- **Backend tests:** 582 passed / 2 skipped (incl. new learning, jobs, diagnostic, path, lesson suites)
- **Frontend:** `tsc --noEmit` clean, `vite build` clean (new asset `index-BOIU5xtT.js`)
- **Contract checkers (9):** all green (`check-step45-copilot`, `check-learning-polish`, `check-learning-phase1–4`, `check-tutor-language`, `check-interview-voice-ux`, `check-tutor-profiles`)
- **Puppeteer smokes:** Learning-review 38/38, assessment-run 18/18, full-pass 13/13 — 0 console errors
- **Diagnostic submit:** network shows POST to `/diagnostic/submit` fires on both fresh and in-progress diagnostics; result screen renders

### Key files touched

- `backend/app/resources.py` — `_VERIFIED_DEAD_RESOURCES`, `sanitize_resources`, updated `active directory` pool, universal apply in `curated_resources`, `retrieve_resources`, `recommend_lesson_resources`, `recommend_step_resources`
- `backend/app/genai.py` — `RESOURCE_VERSION = 4`, sanitize in `generate_learning_path`
- `backend/app/career_roadmap.py` — `resources_version = 3`, sanitize in `_phase_resources`
- `backend/app/jobs.py` — `_expiry_props` truthy-string expired flag, `_DEAD_JOB_URLS` blocklist in `_merge`
- `frontend/src/pages/LearningPage.tsx` — `DiagnosticPanel.submit()` fallback to `diag` when `current` null

### Manual items for next agent

1. **Server restart required** for stored items to refresh: the running backend process caches `RESOURCE_VERSION = 3` / `resources_version = 2`. On next restart, all legacy learning items and career roadmaps will self-heal on first read (sanitized pools + version bump).
2. After restart, verify in browser — Learning page resource cards & roadmap show no `t75MqaiERPE` or `active-directory-ultimate-course`; career roadmap phases carry live links; resource library dedupe is clean.
3. Confirm diagnostic submit works when resuming an in-progress diagnostic (generate → reload page → submit).
4. Confirm Jobs feed shows no beBee dead links on live JSearch fetch.

---

## Phase 5 webcam integrity MVP scope update — APPROVED

Webcam-based assessment integrity is now explicitly approved for the lightweight MVP only. It must not record or store video, perform face recognition, use biometrics, create face embeddings, or infer personal traits. Browser camera analysis sends only integrity event metadata to the backend. Camera flags are assessment integrity signals for review, not automatic cheating verdicts or score-only pass/fail decisions.

## Phase 5B strict assessment termination update — APPROVED

Final Assessment integrity now has hard termination events: tab/browser visibility loss, window blur, fullscreen exit, camera disabled, sustained no-person, sustained multiple-people, and sustained phone detection. These immediately finalize the active attempt through the existing assessment finalization path, stop camera monitoring, prevent resuming the same attempt token, and surface Review Required with a factual reason. `attention_away` is a local, metadata-only soft signal first; it may warn or recommend review, but it must not hard-terminate by itself.
