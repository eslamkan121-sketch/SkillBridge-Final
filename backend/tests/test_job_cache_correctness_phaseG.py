"""Phase G — Multi-user job cache correctness — deterministic offline tests.

Covers the canonical cache key (every result-changing input incl. skill level,
verified flag and limit; config tag; secret/PII-free), the bounded multi-entry
LRU cache with TTL, the fresh/cached/stale_fallback/unavailable status
vocabulary, atomic concurrent-fetch dedup, request-safe per-build provider
health (one request's provider failure can never corrupt another's payload or
the health snapshot), and cross-user privacy (results are a pure function of
profile features — user identity never enters the key).

Every provider is mocked via ``jobs._fetch_all``/``_background_fetch``
substitution; no network and no real quota is ever spent.
"""
import re
import threading
import time

import pytest

from app import jobs


@pytest.fixture(autouse=True)
def _fresh_jobs_state():
    jobs.clear_job_cache()
    jobs._PROVIDER_COOLDOWN.clear()
    for p in jobs.PROVIDERS:
        jobs._provider_status[p] = {"status": "skipped", "count": 0, "reason": "", "error": ""}
    jobs._stats.update({
        "cache_hits": 0, "cache_misses": 0,
        "last_success_provider": "", "last_error_by_provider": {},
        "fetch_times": [],
    })
    yield
    jobs.clear_job_cache()


def _listing(title="Data Analyst", source="Remotive"):
    return {
        "title": title, "company": "Acme", "url": f"https://example.test/{title.replace(' ', '-')}",
        "location": "Cairo, Egypt", "tags": ["SQL"], "source": source, "date": "2026-09-01",
    }


def _fetch(monkeypatch, statuses=None, jobs_out=()):
    """Substitute ``_fetch_all`` with a deterministic builder. When ``statuses``
    is given, each named provider is recorded into the per-build ``report``
    (exercises the request-safe path)."""

    def fake_fetch(limit_each, keywords=(), country="", adzuna_country="", report=None):
        for name, (st, reason) in (statuses or {}).items():
            report[name] = {"status": st, "count": 1 if st == "ok" else 0,
                            "reason": reason, "error": ""}
        return list(jobs_out)

    monkeypatch.setattr(jobs, "_fetch_all", fake_fetch)


def _bg(monkeypatch, recorded):
    monkeypatch.setattr(jobs, "_background_fetch", lambda *a, **k: recorded.append(a[0]))


# ---------------------------------------------------------------------- 
# G1 — canonical key completeness (levels / verified / limit / market / tag)
# ---------------------------------------------------------------------- 

def test_key_differs_when_skill_levels_differ():
    a = jobs._cache_key([("SQL", "Beginner")], "Data Analyst", "Egypt", "Cairo", limit=5)
    b = jobs._cache_key([("SQL", "Advanced")], "Data Analyst", "Egypt", "Cairo", limit=5)
    assert a != b
    assert jobs._cache_key([("SQL", "Beginner")], "Data Analyst", "Egypt", "Cairo", limit=5) == a


def test_key_differs_on_verified_flag_limit_and_market():
    base = [("SQL", "Intermediate")]
    assert jobs._cache_key(base + [("Python", "Intermediate")], "Data Analyst", "Egypt", "Cairo", limit=5) != jobs._cache_key(
        base + [("Python", "Intermediate", True)], "Data Analyst", "Egypt", "Cairo", limit=5)
    assert jobs._cache_key(base, "Data Analyst", "Egypt", "Cairo", limit=3) != jobs._cache_key(
        base, "Data Analyst", "Egypt", "Cairo", limit=10)
    assert jobs._cache_key(base, "Data Analyst", "Egypt", "Cairo", market="ael") != jobs._cache_key(
        base, "Data Analyst", "Egypt", "Cairo", market="eg")
    assert jobs._CACHE_TAG in jobs._cache_key(base, "Data Analyst", "Egypt", "Cairo", limit=5)


def test_key_is_deterministic_across_input_order():
    a = jobs._cache_key([("SQL", "Beginner"), ("Python", "Advanced")], "Data Analyst", "Egypt", "Cairo")
    b = jobs._cache_key([("Python", "Advanced"), ("SQL", "Beginner")], "Data Analyst", "Egypt", "Cairo")
    assert a == b


# ---------------------------------------------------------------------- 
# G1/G4 — bounded LRU with TTL
# ---------------------------------------------------------------------- 

def test_bounded_lru_evicts_oldest_beyond_cap(monkeypatch):
    _fetch(monkeypatch)
    monkeypatch.setattr(jobs, "_get_max_entries", lambda: 3)

    for role in ("Data Analyst", "Security Analyst", "AI Engineer", "Dentist", "Lawyer"):
        jobs.recent_jobs(skills=[("SQL", "Beginner")], role=role, country="Egypt",
                         location="Cairo", limit=5, _sync=True)
    with jobs._lock:
        assert len(jobs._cache) == 3
        ks = [k.lower() for k in jobs._cache]
    assert "data analyst" not in (" ".join(ks))
    assert "security analyst" not in (" ".join(ks))
    assert "ai engineer" in (" ".join(ks))
    assert "dentist" in (" ".join(ks)) and "lawyer" in (" ".join(ks))


def test_ttl_expired_entry_is_lazily_replaced(monkeypatch):
    _fetch(monkeypatch)
    key = jobs._cache_key([("SQL", "Beginner")], "Data Analyst", "Egypt", "", limit=5)
    build = jobs.recent_jobs(skills=[("SQL", "Beginner")], role="Data Analyst",
                             country="Egypt", limit=5, _sync=True)
    assert build["status"] == "fresh"
    with jobs._lock:
        jobs._cache[key]["at"] = time.time() - jobs._get_ttl_seconds() - 60
    before = time.time()
    fresh = jobs.recent_jobs(skills=[("SQL", "Beginner")], role="Data Analyst",
                             country="Egypt", limit=5, _sync=True)
    assert fresh["status"] == "fresh"
    with jobs._lock:
        assert jobs._cache[key]["at"] >= before


# ----------------------------------------------------------------------
# G2 — fresh / cached / stale_fallback / unavailable
# ----------------------------------------------------------------------

def test_statuses_fresh_cached(monkeypatch):
    bg_calls = []
    _fetch(monkeypatch, jobs_out=[_listing()])
    _bg(monkeypatch, bg_calls)
    out1 = jobs.recent_jobs(skills=[("SQL", "Beginner")], role="Data Analyst",
                            country="Egypt", limit=5, _sync=True)
    assert out1["status"] == "fresh"
    assert out1["source"] == "live"
    out2 = jobs.recent_jobs(skills=[("SQL", "Beginner")], role="Data Analyst",
                            country="Egypt", limit=5, _sync=False)
    assert out2["status"] == "cached"
    assert out2["jobs"] == out1["jobs"]
    assert bg_calls == []                      # a fresh cached row is never refetched


def test_stale_fallback_serves_last_data_and_refreshes_once(monkeypatch):
    _fetch(monkeypatch, jobs_out=[_listing()])
    key = jobs._cache_key([("SQL", "Beginner")], "Data Analyst", "Egypt", "", limit=5)
    jobs.recent_jobs(skills=[("SQL", "Beginner")], role="Data Analyst",
                     country="Egypt", limit=5, _sync=True)
    with jobs._lock:
        jobs._cache[key]["at"] = time.time() - jobs._get_ttl_seconds() - 60

    refreshed = []
    _bg(monkeypatch, refreshed)
    out = jobs.recent_jobs(skills=[("SQL", "Beginner")], role="Data Analyst",
                           country="Egypt", limit=5, _sync=False)
    assert out["status"] == "stale_fallback"
    assert out["source"] == "live"             # original honest source preserved
    assert out["jobs"]                          # last good data served, never emptied
    with jobs._lock:
        assert key in jobs._bg_fetching         # one in-flight refresh, deduped
    jobs.recent_jobs(skills=[("SQL", "Beginner")], role="Data Analyst",
                     country="Egypt", limit=5, _sync=False)
    assert len(refreshed) == 1                  # a repeat stale read adds none


def test_miss_returns_unavailable_and_schedules_one_fetch(monkeypatch):
    calls = []
    _bg(monkeypatch, calls)
    out = jobs.recent_jobs(skills=[("SQL", "Beginner")], role="Data Analyst",
                           country="Egypt", limit=5, _sync=False)
    assert out["status"] == "unavailable"
    assert out["jobs"] == []
    key = jobs._cache_key([("SQL", "Beginner")], "Data Analyst", "Egypt", "", limit=5)
    assert calls == [key]
    with jobs._lock:
        assert key in jobs._bg_fetching


# ----------------------------------------------------------------------
# G3 — concurrency / dedup / provider-failure isolation
# ----------------------------------------------------------------------

def test_concurrent_same_key_misses_dedup_to_one_fetch(monkeypatch):
    recorded = []

    def fake_bg(key, *a, **k):
        recorded.append(key)
        time.sleep(0.05)

    monkeypatch.setattr(jobs, "_background_fetch", fake_bg)
    barrier = threading.Barrier(8)
    results = [None] * 8

    def worker(i):
        barrier.wait()
        results[i] = jobs.recent_jobs(skills=[("SQL", "Beginner")], role="Data Analyst",
                                      country="Egypt", limit=5, _sync=False)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    key = jobs._cache_key([("SQL", "Beginner")], "Data Analyst", "Egypt", "", limit=5)
    assert len(recorded) == 1 and recorded[0] == key
    assert all(r["status"] == "unavailable" for r in results)


def test_concurrent_distinct_keys_stay_isolated(monkeypatch):
    recorded = []
    _bg(monkeypatch, recorded)
    barrier = threading.Barrier(4)
    results = [None] * 4

    def worker(i):
        role = "Data Analyst" if i % 2 == 0 else "Security Analyst"
        barrier.wait()
        results[i] = jobs.recent_jobs(skills=[("SQL", "Beginner")], role=role,
                                      country="Egypt", limit=5, _sync=False)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(recorded) == 2                   # one fetch per distinct key
    assert len(set(recorded)) == 2


def test_level_distinct_profiles_never_reuse_rows(monkeypatch):
    _fetch(monkeypatch, jobs_out=[_listing("Data Analyst Beginner")])
    jobs.recent_jobs(skills=[("SQL", "Beginner")], role="Data Analyst",
                     country="Egypt", limit=5, _sync=True)
    jobs.recent_jobs(skills=[("SQL", "Advanced")], role="Data Analyst",
                     country="Egypt", limit=5, _sync=True)
    kb = jobs._cache_key([("SQL", "Beginner")], "Data Analyst", "Egypt", "", limit=5)
    ka = jobs._cache_key([("SQL", "Advanced")], "Data Analyst", "Egypt", "", limit=5)
    with jobs._lock:
        assert kb in jobs._cache and ka in jobs._cache
        assert jobs._cache[kb]["data"] is not jobs._cache[ka]["data"]
        assert jobs._cache[kb]["data"]["jobs"][0]["title"] == "Data Analyst Beginner"


def test_provider_failure_isolation_between_requests(monkeypatch):
    fake_ok = {"Remotive": ("ok", "")}
    fake_bad = {"Remotive": ("failed", "rate_limited")}

    def fetch_with(statuses, jobs_out):
        def inner(limit_each, keywords=(), country="", adzuna_country="", report=None):
            for name, (st, reason) in statuses.items():
                report[name] = {"status": st, "count": 1 if st == "ok" else 0,
                                "reason": reason, "error": ""}
            return list(jobs_out)
        return inner

    monkeypatch.setattr(jobs, "_fetch_all", fetch_with(fake_ok, [_listing()]))
    a = jobs.recent_jobs(skills=[("SQL", "Beginner")], role="Data Analyst",
                         country="Egypt", limit=5, _sync=True)

    monkeypatch.setattr(jobs, "_fetch_all", fetch_with(fake_bad, []))
    b = jobs.recent_jobs(skills=[("Python", "Advanced")], role="AI Engineer",
                         country="Egypt", limit=5, _sync=True)

    pa = {p["source"]: p for p in a["providers"]}
    pb = {p["source"]: p for p in b["providers"]}
    assert pa["Remotive"]["status"] == "ok"
    assert pb["Remotive"]["status"] == "failed"
    assert pb["Remotive"]["reason"] == "rate_limited"
    assert a["source"] == "live"
    assert b["source"] == "unavailable"
    # Health = the LAST COMPLETED build, never a mid-fetch peek.
    health = jobs.provider_status()
    assert "Remotive" not in health["providers_available"]
    assert health["last_error_by_provider"]["Remotive"] == "rate_limited"


# ----------------------------------------------------------------------
# G4 — privacy: keys and payloads are identity- and secret-free
# ----------------------------------------------------------------------

def test_cross_user_identical_profile_shares_payload_but_key_has_no_user(monkeypatch):
    _fetch(monkeypatch, jobs_out=[_listing("Shared Analyst")])
    alice = jobs.recent_jobs(skills=[("SQL", "Beginner")], role="Data Analyst",
                             country="Egypt", location="Cairo", limit=5, _sync=True)
    bob = jobs.recent_jobs(skills=[("SQL", "Beginner")], role="Data Analyst",
                           country="Egypt", location="Cairo", limit=5, _sync=False)
    assert bob["status"] == "cached"
    assert bob["jobs"] == alice["jobs"]
    key = jobs._cache_key([("SQL", "Beginner")], "Data Analyst", "Egypt", "Cairo", limit=5)
    assert "alice" not in key and "bob" not in key


def test_email_and_cv_blob_are_scrubbed_from_key():
    cv_blob = ("Curriculum vitae alice@example.com http://private.invalid/resume "
               "packed with free-form narrative text of a personal document "
               "that must never become a cache key component")
    key = jobs._cache_key([(cv_blob, "Beginner")], "Data Analyst", "Egypt", "Cairo", limit=5)
    assert "alice@example.com" not in key
    assert "private.invalid" not in key
    assert "<email>" in key and "<url>" in key
    assert re.search(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", key) is None


def test_api_key_secret_never_enters_cache_key(monkeypatch):
    monkeypatch.setenv("JSEARCH_API_KEY", "SHARED-SECRET-9f3")
    key = jobs._cache_key([("resume-data SHARED-SECRET-9f3", "Beginner")],
                          "Data Analyst", "Egypt", "", limit=5)
    assert "SHARED-SECRET-9f3" not in key
    assert "resume-data" in key
    assert re.search(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", key) is None


def test_record_status_redacts_secrets_from_active_report(monkeypatch):
    monkeypatch.setenv("JSEARCH_API_KEY", "SHARED-SECRET-9f3")
    report = {"JSearch": {"status": "skipped", "count": 0, "reason": "", "error": ""}}
    jobs._thread_local.report = report
    try:
        jobs._record_status("JSearch", "failed", 0, "auth_error",
                            "401 JSEARCH_API_KEY=SHARED-SECRET-9f3")
    finally:
        del jobs._thread_local.report
    assert report["JSearch"]["error"] == "401 JSEARCH_API_KEY=***"
    assert "SHARED-SECRET-9f3" not in repr(report)
    assert "SHARED-SECRET-9f3" not in repr(jobs.provider_status())
    assert report["JSearch"]["reason"] == "auth_error"      # stable reason survives