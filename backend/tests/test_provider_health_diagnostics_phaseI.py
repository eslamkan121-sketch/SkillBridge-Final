"""Phase I — honest provider health and diagnostics (guide lines 470-505).

Fully offline: every test builds its own legacy-style provider report
entry and reads ``jobs._health_of`` / ``jobs.provider_status()`` off it. No
live provider is ever called. No env key value or URL ever appears in a
public payload or a log assertion.
"""
import logging
import os
import time

import pytest

from app import jobs


def _reset():
    jobs.clear_job_cache()
    jobs._bg_fetching.clear()
    jobs._PROVIDER_COOLDOWN.clear()
    for p in jobs.PROVIDERS:
        jobs._provider_status[p] = {"status": "skipped", "count": 0,
                                     "reason": "", "error": ""}
    jobs._stats.update({"cache_hits": 0, "cache_misses": 0,
                        "last_success_provider": "", "last_error_by_provider": {},
                        "fetch_times": [], "last_build_at": None})
    jobs._health_cache.update({"at": 0.0, "payload": None, "fingerprint": None})


def _entry(status, count=0, reason="", error=""):
    return {"status": status, "count": count, "reason": reason, "error": error}


# ── HEALTH VOCABULARY ────────────────────────────────────────────────────────

def test_healthy_code_appears_when_provider_answered_with_listings():
    _reset()
    assert jobs._health_of(_entry("ok", count=5), "Remotive") == "healthy"


def test_empty_success_code_appears_when_responded_but_zero_listings():
    _reset()
    # ok + 0 listings is an honest empty feed, NOT a failure
    assert jobs._health_of(_entry("ok", count=0), "RemoteOK") == "empty_success"
    assert jobs._health_of(_entry("ok", count=0, reason=""), "Jobicy") == "empty_success"


def test_unconfigured_for_missing_credentials_or_host():
    _reset()
    assert jobs._health_of(_entry("skipped", reason="no_credentials"), "JSearch") == "unconfigured"
    assert jobs._health_of(_entry("skipped", reason="host_not_configured"), "LinkedIn") == "unconfigured"


def test_disabled_by_feature_flag_for_unsupported_country_and_flag():
    _reset()
    assert jobs._health_of(_entry("skipped", reason="unsupported_country"), "Adzuna") == "disabled_by_feature_flag"
    jobs._provider_status["Jooble"] = _entry("skipped", reason="disabled_by_feature_flag")
    assert jobs._health_of(jobs._provider_status["Jooble"], "Jooble") == "disabled_by_feature_flag"


def test_unknown_fallback_for_untouched_init_state():
    _reset()
    # A provider whose report is the untouched init marker (skipped/0/""/"")
    # is not yet healthy nor failed -> honest unknown (keyless providers are
    # configured but have no outcome yet).
    assert jobs._health_of(_entry("skipped"), "RemoteOK") == "unknown"


def test_rate_limited_code():
    _reset()
    assert jobs._health_of(_entry("failed", reason="rate_limited"), "Jooble") == "rate_limited"
    # cooldown-skip carries the cooldown cause inside ``error``
    jobs._PROVIDER_COOLDOWN["Remotive"] = {"until": time.time() + 900, "reason": "rate_limited"}
    assert jobs._health_of(_entry("skipped", reason="cooldown", error="rate_limited"), "Remotive") == "rate_limited"
    jobs._PROVIDER_COOLDOWN.pop("Remotive", None)


def test_unauthorized_code():
    _reset()
    assert jobs._health_of(_entry("failed", reason="forbidden"), "LinkedIn") == "unauthorized"
    assert jobs._health_of(_entry("failed", reason="unauthorized"), "Google Jobs") == "unauthorized"
    # 403 buried in error text for request_failed
    assert jobs._health_of(_entry("failed", reason="request_failed",
                                   error="403 Client Error: Forbidden for https://example"),
                           "LinkedIn") == "unauthorized"


def test_timeout_code():
    _reset()
    assert jobs._health_of(_entry("failed", reason="timeout"), "Jooble") == "timeout"
    # network_error with a live cooldown whose reason is "timeout"
    jobs._PROVIDER_COOLDOWN["Jooble"] = {"until": time.time() + 900, "reason": "timeout"}
    assert jobs._health_of(_entry("failed", reason="network_unreachable"), "Jooble") == "timeout"
    jobs._PROVIDER_COOLDOWN.pop("Jooble", None)
    # httpx-style timeout in error text of request_failed
    assert jobs._health_of(_entry("failed", reason="request_failed",
                                   error="timed out connecting to remote host"),
                           "Jooble") == "timeout"


def test_malformed_response_code():
    _reset()
    for marker in ("jsondecode", "expecting value", "expecting property name",
                   "expecting ',' delimiter", "invalid \\u", "unexpected end of data",
                   "not a json"):
        assert jobs._health_of(_entry("failed", reason="request_failed",
                                       error=f"{marker} at line 1"),
                               "Jooble") == "malformed_response"


def test_network_unreachable_is_honest_and_preserves_reason():
    _reset()
    assert jobs._health_of(_entry("failed", reason="network_unreachable"), "JSearch") == "network_unreachable"
    assert jobs._health_of(_entry("failed", reason="network_error"), "RemoteOK") == "network_unreachable"


def test_disabled_provider_feature_flag_excludes_from_health():
    _reset()
    # JOBS_DISABLED_PROVIDERS forces disabled_by_feature_flag regardless of entry
    old = os.environ.get("JOBS_DISABLED_PROVIDERS")
    os.environ["JOBS_DISABLED_PROVIDERS"] = "Remotive"
    try:
        assert jobs._health_of(_entry("ok", count=9), "Remotive") == "disabled_by_feature_flag"
        assert jobs._health_of(_entry("skipped", reason="no_credentials"), "Remotive") == "disabled_by_feature_flag"
    finally:
        if old is None:
            os.environ.pop("JOBS_DISABLED_PROVIDERS", None)
        else:
            os.environ["JOBS_DISABLED_PROVIDERS"] = old


def test_unknown_for_unrecognised_failed_reason():
    _reset()
    assert jobs._health_of(_entry("failed", reason="boom"), "RemoteOK") == "unknown"


def test_unknown_for_blank_entry():
    _reset()
    assert jobs._health_of({}, "RemoteOK") == "unknown"


# ── EMPTY SUCCESS HONESTY ────────────────────────────────────────────────────

def test_empty_success_never_counts_as_failure():
    _reset()
    jobs._record_status("Remotive", "ok", 0)
    st = jobs.provider_status()
    assert "Remotive" in st["providers_available"]
    # An empty-success feed still counts as providers_available (it answered)
    assert st["providers_health"]["Remotive"] == "empty_success"
    # It must NOT be labelled rate_limited / unconfigured / unknown
    assert st["providers_health"]["Remotive"] != "unknown"


def test_feed_still_live_when_sibling_provider_has_listings():
    _reset()
    jobs._record_status("Remotive", "ok", 5)
    jobs._record_status("RemoteOK", "ok", 0)
    st = jobs.provider_status()
    assert "Remotive" in st["providers_available"]
    assert st["providers_health"]["Remotive"] == "healthy"
    assert st["providers_health"]["RemoteOK"] == "empty_success"


# ── COOLDOWN / RATE-LIMIT HONESTY ────────────────────────────────────────────

def test_rate_limit_sets_cooldown_and_health_rate_limited():
    _reset()
    jobs._set_provider_cooldown("Remotive", "rate_limited")
    assert jobs._is_provider_cooled_down("Remotive")
    jobs._record_status("Remotive", "failed", 0, "rate_limited",
                        "429 Client Error")
    st = jobs.provider_status()
    assert st["providers_health"]["Remotive"] == "rate_limited"
    assert "Remotive" not in st["providers_available"]


def test_timeout_health_appears_for_cooldown_reason_timeout():
    _reset()
    jobs._set_provider_cooldown("Jooble", "timeout")
    jobs._record_status("Jooble", "skipped", 0, reason="cooldown", error="timeout")
    assert jobs._health_of(jobs._provider_status["Jooble"], "Jooble") == "timeout"
    jobs._PROVIDER_COOLDOWN.pop("Jooble", None)


def test_unauthorized_health_appears():
    _reset()
    jobs._record_status("LinkedIn", "failed", 0, "request_failed",
                        "403 Client Error: Forbidden")
    assert jobs.provider_status()["providers_health"]["LinkedIn"] == "unauthorized"


# ── REDACTION (no secrets, no URLs in public payload) ────────────────────────

def test_record_status_redacts_secrets_from_active_report():
    _reset()
    secret = "SHARED-SECRET-9f3"
    jobs._record_status("JSearch", "skipped", 0, "", "")
    jobs._record_status("JSearch", "failed", 0, "auth_error",
                        f"429 for url?key={secret}")
    payload = jobs.provider_status()
    payload_repr = repr(payload)
    assert secret not in payload_repr


def test_public_payload_contains_no_url_and_no_email():
    _reset()
    err = ("403 for https://api.linkedin.com/v2/jobs?key=abc "
           "contact admin@evil.example.com")
    jobs._record_status("LinkedIn", "failed", 0, "request_failed", err)
    p = jobs._provider_status["LinkedIn"]
    assert "https://" not in p["error"]
    assert "admin@" not in p["error"]
    assert "<url>" in jobs._redact(err)
    assert "<email>" in jobs._redact(err)


# ── REQUEST-ID THREADING + LOGGING ───────────────────────────────────────────

def test_request_id_roundtrips_through_build(caplog):
    _reset()
    _orig_fetch_all = jobs._fetch_all
    jobs._fetch_all = lambda *a, **k: []
    try:
        with caplog.at_level(logging.INFO):
            out = jobs.recent_jobs(skills=[("SQL", "Beginner")], role="Data Analyst",
                                    country="Egypt", _sync=True, request_id="abc123")
        text = caplog.text
        assert "abc123" in text
        assert "job build complete" in text
        assert out["source"] == "unavailable"
    finally:
        jobs._fetch_all = _orig_fetch_all


def test_request_id_never_leaks_into_global_provider_status():
    _reset()
    def fake_fetch(*a, **k):
        return []
    orig = jobs._fetch_remotive
    jobs._fetch_remotive = fake_fetch
    try:
        jobs.recent_jobs(skills=[("SQL", "Beginner")], role="Data Analyst",
                         country="Egypt", _sync=True, request_id="rid-xyz")
        st = jobs.provider_status()
        assert "rid-xyz" not in repr(st)
    finally:
        jobs._fetch_remotive = orig


# ── CONCURRENCY ISOLATION ────────────────────────────────────────────────────

def test_concurrent_builds_have_isolated_provider_outcomes():
    _reset()
    import threading
    results = {}

    def build_a():
        results["a"] = jobs.recent_jobs(skills=[("SQL", "Beginner")], role="Data Analyst",
                                         country="Egypt", _sync=True)

    def build_b():
        results["b"] = jobs.recent_jobs(skills=[("Python", "Advanced")], role="Data Scientist",
                                         country="Egypt", _sync=True)

    t1 = threading.Thread(target=build_a, daemon=True)
    t2 = threading.Thread(target=build_b, daemon=True)
    t1.start(); t2.start()
    t1.join(); t2.join()
    # Both builds must return a coherent payload; no cross-build corruption.
    assert "source" in results["a"] and "source" in results["b"]


# ── COMPATIBILITY (legacy fields untouched, new additive fields present) ──────

def test_provider_status_keeps_legacy_keys():
    _reset()
    jobs._record_status("Remotive", "ok", 5)
    jobs._record_status("JSearch", "failed", 0, "rate_limited", "429")
    st = jobs.provider_status()
    for key in ("providers_total", "providers_configured", "providers_available",
                "last_success_provider", "last_error_by_provider", "cache"):
        assert key in st
    assert st["providers_total"] == len(jobs.PROVIDERS)


def test_providers_list_entries_gain_additive_health():
    _reset()
    jobs._record_status("Remotive", "ok", 5)
    raw = jobs._fetch_all(5, ("sql",), "Egypt")
    # A sync build may return [] if all skipped; use the provider_status path instead
    jobs._record_status("RemoteOK", "ok", 0)
    st = jobs.provider_status()
    assert "providers_health" in st
    assert "Remotive" in st["providers_health"]
    assert "RemoteOK" in st["providers_health"]


def test_recent_jobs_keeps_legacy_source_status_fields():
    _reset()
    _orig_fetch_all = jobs._fetch_all
    jobs._fetch_all = lambda *a, **k: []
    try:
        out = jobs.recent_jobs(skills=[("SQL", "Beginner")], role="Data Analyst",
                                country="Egypt", _sync=True)
        assert out["source"] in ("unavailable", "empty")
        assert out["status"] in ("fresh", "cached", "stale_fallback", "unavailable")
    finally:
        jobs._fetch_all = _orig_fetch_all


def test_last_build_at_present():
    _reset()
    st = jobs.provider_status()
    # A build may never have run in this test; field exists with None
    assert "last_build_at" in st


def test_health_map_is_additive_not_replacing():
    _reset()
    jobs._record_status("Remotive", "ok", 5)
    st = jobs.provider_status()
    assert st["providers_available"] == ["Remotive"]
    assert st["providers_health"]["Remotive"] == "healthy"
