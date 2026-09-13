# Wired job providers — reference

All configuration lives in `backend/app/jobs.py`. Providers run in parallel with
short timeouts so a slow/unreachable feed never blocks the others; each one
reports an honest per-build outcome (`ok` / `failed` / `skipped` with a stable
`reason` code), and credentials are scrubbed from every log/status payload.

## Provider table

| Provider | Type | Base endpoint | Configured by | Notes |
|---|---|---|---|---|
| Remotive | keyless | `https://remotive.com/api/remote-jobs` | — | global remote board; always attempted |
| RemoteOK | keyless | `https://remoteok.com/api` | — | global remote/tech; always attempted |
| Jobicy | keyless | `https://jobicy.com/api/v2/remote-jobs` | — | global remote; always attempted |
| Arbeitnow | keyless | `https://www.arbeitnow.com/api/job-board-api` | — | global remote; always attempted |
| Himalayas | keyless | `https://himalayas.app/jobs/api` | — | remote-first; always attempted |
| Get on Board | keyless | `https://www.getonbrd.com/api/v0/categories/programming/jobs` | — | LATAM/remote; always attempted |
| Adzuna | keyed | `https://api.adzuna.com/v1/api/jobs` | `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | country-scoped (market); skipped when country unsupported, never remapped |
| Jooble | keyed | `https://api.jooble.org/api` | `JOOBLE_API_KEY` | optional; API may be regionally unreachable and degrades to a no-op |
| JSearch | keyed | `https://jsearch.p.rapidapi.com/search-v2` | `JSEARCH_API_KEY` or `RAPIDAPI_KEY` | MENA-capable; sends `language=en` |
| USAJobs | keyed | `https://data.usajobs.gov/api/search` | `USAJOBS_API_KEY` | US-only; skipped for non-US markets |
| LinkedIn | keyed + host-gated | RapidAPI app host | `LINKEDIN_JOBS_HOST`, `LINKEDIN_JOBS_PATH`, `RAPIDAPI_LINKEDIN_KEY` (falls back to `RAPIDAPI_KEY`) | endpoint host is never guessed; reports `host_not_configured` until set |
| Google Jobs | keyed + host-gated | RapidAPI app host | `GOOGLE_JOBS_HOST`, `GOOGLE_JOBS_PATH`, `RAPIDAPI_GOOGLE_JOBS_KEY` (falls back to `RAPIDAPI_KEY`) | endpoint host is never guessed; reports `host_not_configured` until set |

All listings are normalised to a shared internal shape, deduped by URL and by
normalised (title + company + location), then re-ranked against the student's
target role before being cached. No provider is ever substituted for an
unsupported market, and no curated/demo jobs are ever injected — the feed
reports `live`, `empty`, or `unavailable` honestly.

## Required fallbacks (order of preference)

1. **Keyless first.** Remotive / RemoteOK / Jobicy / Arbeitnow / Himalayas /
   Get on Board need no credentials and are always attempted.
2. **Keyed providers as configured.** JSearch, Adzuna, Jooble, USAJobs run only
   when their env vars are present.
3. **RapidAPI host-gated adapters** (LinkedIn, Google Jobs) run only when the
   exact subscribed host AND a key are configured.
4. **Global remote boards as the safety net.** If the keyed country-scoped feeds
   are absent or fail, the four keyless boards still provide a live feed so the
   student is never left with a silently-empty page.

A provider that hits a **429**, **403**, or times out enters a cooldown (see
below) instead of hammering the upstream; a provider in cooldown reports
`skipped: cooldown` and is not attempted again until the window expires.

## Cooldown + cache TTL (env knobs)

- `JOBS_CACHE_TTL_SECONDS` — in-memory result TTL (default **15 min**). Set to a
  positive number to override. On a cache hit the stored (already-rank/deduped)
  payload is returned instantly.
- `JOBS_COOLDOWN_SECONDS` — provider cooldown length after `rate_limited` /
  `forbidden` / `timeout` (default **15 min**). Configurable per deployment.

Set both in the target root `.env`; a backend restart is required to load them.

## Diagnostics

`GET /api/config/demo-mode` returns a secret-free `jobs` block via
`jobs.provider_status()`:

- `providers_total`, `providers_configured`, `providers_available`
- `last_success_provider` — most recent provider that answered with listings
- `last_error_by_provider` — stable failure reason codes per failed provider
- `cache: {hits, misses, avg_fetch_ms}` — rolling health counters

No API keys, hosts, or listing content ever appear in this payload.

## How to add a new provider (checklist)

1. Add the provider name to `PROVIDERS` (priority order) in `backend/app/jobs.py`.
2. Write a `_fetch_<name>(n, ...)` function following the existing contract:
   it must **never raise**, normalise listings to the shared internal shape
   (`title`, `company`, `url`, `location`, `date`, `tags`, `description`, …),
   set `source` on each job, and call `_record_status(...)` on every outcome.
3. On 429 / 403 / timeout: call `_set_provider_cooldown("<source>", reason)` and
   return `[]` — mirror the existing handlers exactly.
4. If the provider needs credentials, read them from `os.environ`, skip honestly
   via `_skip_status("<source>", "no_credentials")` when absent, and add the env
   var to the `_redact()` list so it can never leak.
5. Register the call in `_fetch_all(...)` inside the `calls` list.
6. If it is keyless, add it to `_provider_is_configured()`'s keyless set; if
   keyed/host-gated, add the matching branch.
7. Add deterministic (offline, monkeypatched) tests in
   `tests/test_jobs_*.py` covering payload normalisation, failure degrade, and
   dedup, then run `pytest -q` plus `tsc --noEmit` / `vite build`.