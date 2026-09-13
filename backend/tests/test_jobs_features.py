"""Deterministic (offline) tests for the job-quality features.

Covers the dedup-by-identity merge, the weighted reranker (title/skill boost,
cross-family penalty, recency), 429-cooldown skipping inside ``_fetch_all``,
cache-hit identity, and the secret-free ``provider_status`` diagnostics.
No live provider quota is ever spent and no real API keys are read.
"""
import time

from app import jobs


def _reset_feed():
    jobs.clear_job_cache()
    jobs._bg_fetching.clear()
    jobs._PROVIDER_COOLDOWN.clear()
    for p in jobs.PROVIDERS:
        jobs._provider_status[p] = {"status": "skipped", "count": 0, "reason": "", "error": ""}
    jobs._stats.update({
        "cache_hits": 0, "cache_misses": 0,
        "last_success_provider": "", "last_error_by_provider": {},
        "fetch_times": [],
    })


def _cache_key(skills, role, country, location, requisites=(), market="", limit=10):
    """Replicate the canonical cache key built by ``jobs._cache_key``."""
    return jobs._cache_key(skills, role, country, location, requisites, market, limit)


def test_merge_dedupes_same_listing_across_providers():
    """The same vacancy surfaced by two providers (identical title + company +
    location) collapses into one job rather than appearing twice."""
    _reset_feed()
    raw = [
        {"title": "Junior Data Analyst", "company": "Acme Analytics",
         "url": "https://example.test/a1", "location": "Cairo, Egypt",
         "tags": ["SQL"], "source": "JSearch", "date": "2026-09-01",
         "description": "SQL analyst position"},
        {"title": "Junior Data Analyst", "company": "Acme Analytics",
         "url": "https://example.test/a2", "location": "Cairo, Egypt",
         "tags": ["SQL", "Excel"], "source": "Remotive", "date": "2026-09-01",
         "description": "SQL analyst position"},
    ]
    merged = jobs._merge(raw)
    assert len(merged) == 1
    # richer tags survive the merge
    assert merged[0]["tags"] == ["SQL", "Excel"]


def test_merge_keeps_distinct_vacancies_with_similar_titles():
    """Different vacancies with similar but distinct titles are never merged —
    the title + company + location identity must agree."""
    _reset_feed()
    raw = [
        {"title": "Data Analyst Jr", "company": "Acme", "url": "https://example.test/b1",
         "location": "Cairo, Egypt", "source": "JSearch", "date": "2026-09-01"},
        {"title": "Data Analyst Sr", "company": "Acme", "url": "https://example.test/b2",
         "location": "Cairo, Egypt", "source": "Remotive", "date": "2026-09-01"},
    ]
    merged = jobs._merge(raw)
    assert len(merged) == 2


def test_rerank_title_match_and_skill_overlap_boost():
    """A listing whose title matches the target role plus overlaps the student's
    verified skills and gaps scores substantially higher than a weak one."""
    _reset_feed()
    strong = jobs._rerank_score(
        {"title": "Cybersecurity Analyst", "company": "SecCo",
         "description": "incident response SIEM threat detection",
         "tags": ["SIEM", "Threat Detection"], "location": "Remote",
         "remote": True, "country": "Egypt", "listed_days_ago": 2},
        "Cybersecurity Analyst",
        ["SIEM", "Threat Detection"], ["Threat Detection"], "Egypt", "")
    weak = jobs._rerank_score(
        {"title": "Customer Service Associate", "company": "CallsCo",
         "description": "answer tickets", "tags": [], "location": "Remote",
         "remote": True, "country": "US", "listed_days_ago": 30},
        "Cybersecurity Analyst", [], ["Threat Detection"], "Egypt", "")
    assert strong > jobs.W_TITLE_MATCH  # full title match dominates the score
    assert strong > weak


def test_rerank_cross_family_penalty_suppresses_score():
    """A marketing job must be heavily penalized for a cybersecurity target — the
    cross-family penalty outweighs location/recency so unrelated careers never
    outrank a same-family match."""
    _reset_feed()
    assert jobs._role_family("Cybersecurity Analyst") == "security"
    assert jobs._role_family("Marketing Manager") == "marketing"
    on_family = jobs._rerank_score(
        {"title": "Cybersecurity Analyst", "company": "SecCo",
         "description": "SIEM", "tags": ["SIEM"], "location": "Remote",
         "remote": True, "country": "Egypt", "listed_days_ago": 1},
        "Cybersecurity Analyst", [], [], "Egypt", "")
    off_family = jobs._rerank_score(
        {"title": "Marketing Manager", "company": "AdsCo",
         "description": "brand strategy", "tags": ["marketing"],
         "location": "Remote", "remote": True, "country": "Egypt",
         "listed_days_ago": 1},
        "Cybersecurity Analyst", [], [], "Egypt", "")
    assert off_family < on_family
    # location + recency alone cannot rescue a cross-family job past zero
    assert off_family < (jobs.W_LOCATION_MATCH + jobs.W_RECENCY)


def test_fetch_all_skips_provider_on_429_cooldown(monkeypatch):
    """A provider that hit a rate limit is not attempted again until its
    cooldown window expires — it reports ``skipped`` / ``cooldown`` instead."""
    _reset_feed()
    jobs._set_provider_cooldown("Remotive", "rate_limited")
    called = []

    def recorder(name):
        def fn(*a, **k):
            called.append(name)
            return []
        return fn

    keyless = {
        "Remotive": jobs._fetch_remotive,
        "RemoteOK": jobs._fetch_remoteok,
        "Jobicy": jobs._fetch_jobicy,
        "Arbeitnow": jobs._fetch_arbeitnow,
        "Himalayas": jobs._fetch_himalayas,
        "Get on Board": jobs._fetch_getonboard,
    }
    for _name, fn in keyless.items():
        monkeypatch.setattr(jobs, fn.__name__, recorder(_name))
    for var in ("JSEARCH_API_KEY", "RAPIDAPI_KEY", "RAPIDAPI_LINKEDIN_KEY",
                "RAPIDAPI_GOOGLE_JOBS_KEY", "LINKEDIN_JOBS_HOST", "GOOGLE_JOBS_HOST",
                "ADZUNA_APP_ID", "ADZUNA_APP_KEY", "JOOBLE_API_KEY", "USAJOBS_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    raw = jobs._fetch_all(5, ["data analyst"], "Egypt")
    assert raw == []
    assert "Remotive" not in called            # cooldown → never re-invoked
    assert jobs._is_provider_cooled_down("Remotive")
    assert jobs._provider_status["Remotive"]["status"] == "skipped"
    assert jobs._provider_status["Remotive"]["reason"] == "cooldown"


def test_cache_hit_returns_identical_payload_without_refetch(monkeypatch):
    """The second identical query returns the exact cached payload and never
    re-fetches — this is what prevents hammering upstream feeds."""
    _reset_feed()
    monkeypatch.setattr(jobs, "_background_fetch",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("must not background fetch on cache hit")))
    payload = {"source": "live", "jobs": [], "groups": {}, "providers": [],
               "status": "fresh", "cache_probe": "identical"}
    key = _cache_key([("SQL", "Beginner")], "Data Analyst", "Egypt", "Cairo", limit=5)
    now = time.time()
    with jobs._lock:
        jobs._cache[key] = {"at": now, "data": payload}
        hits_before = jobs._stats["cache_hits"]

    out = jobs.recent_jobs(skills=[("SQL", "Beginner")], role="Data Analyst",
                           country="Egypt", location="Cairo", limit=5, _sync=False)
    assert out["cache_probe"] == "identical"
    assert out["status"] == "cached"
    with jobs._lock:
        assert jobs._stats["cache_hits"] == hits_before + 1


def test_provider_status_is_secret_free_and_tracks_outcomes(monkeypatch):
    """Diagnostics expose which providers are configured/available plus safe
    failure codes — never credentials or listing content."""
    _reset_feed()
    monkeypatch.setenv("JSEARCH_API_KEY", "SUPER_SECRET_JSH_99")
    jobs._record_status("Remotive", "ok", 5)
    jobs._record_status("JSearch", "failed", 0, "rate_limited",
                        "429 for url?key=SUPER_SECRET_JSH_99")
    st = jobs.provider_status()
    assert "SUPER_SECRET_JSH_99" not in repr(st)
    assert st["last_success_provider"] == "Remotive"
    assert st["last_error_by_provider"]["JSearch"] == "rate_limited"
    assert "Remotive" in st["providers_configured"]
    assert "Remotive" in st["providers_available"]
    assert "JSearch" in st["providers_configured"]
    assert st["providers_total"] == len(jobs.PROVIDERS)
    assert st["cache"]["hits"] >= 0 and st["cache"]["misses"] >= 0