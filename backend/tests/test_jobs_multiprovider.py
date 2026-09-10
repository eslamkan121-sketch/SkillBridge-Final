"""Offline tests for the multi-provider job architecture (no real keys/network).

Covers the two new RapidAPI adapters (LinkedIn, Google Jobs) plus the shared
config/security/dedup contract:
- configuration: host-gating (host_not_configured skip), key resolution
  (provider-specific override > shared RAPIDAPI_KEY), missing-key skip;
- provider behaviour: normalized success, empty result, auth-error body,
  timeout, HTTP 429 rate limit;
- security: every known key variable is redacted from logs/payloads;
- deduplication: the same vacancy surfaced by two providers collapses to one.

Credential hygiene: tests NEVER read real `.env` values — all config is set
per-test via monkeypatch, and the provider health payloads are asserted to be
redacted.
"""
import httpx
import pytest

from app import jobs


def _fake_resp(payload, status=200):
    class R:
        status_code = status

        def raise_for_status(self):
            if self.status_code >= 400:
                req = httpx.Request("GET", "https://provider.example.test/search")
                raise httpx.HTTPStatusError(
                    f"{self.status_code} error", request=req,
                    response=httpx.Response(self.status_code, request=req))

        def json(self):
            return payload

    return R()


def _config(monkeypatch, host, key, path="/search", key_var="RAPIDAPI_LINKEDIN_KEY"):
    monkeypatch.setenv("LINKEDIN_JOBS_HOST", host)
    monkeypatch.setenv("LINKEDIN_JOBS_PATH", path)
    monkeypatch.setenv("GOOGLE_JOBS_HOST", host)
    monkeypatch.setenv("GOOGLE_JOBS_PATH", path)
    monkeypatch.setenv(key_var, key)


def _clear_env(monkeypatch):
    for v in ("LINKEDIN_JOBS_HOST", "LINKEDIN_JOBS_PATH",
              "GOOGLE_JOBS_HOST", "GOOGLE_JOBS_PATH",
              "RAPIDAPI_LINKEDIN_KEY", "RAPIDAPI_GOOGLE_JOBS_KEY",
              "RAPIDAPI_KEY", "JSEARCH_API_KEY"):
        monkeypatch.delenv(v, raising=False)


def test_linkedin_google_skip_when_host_not_configured(monkeypatch):
    """Host-gating: never guess a RapidAPI host — skip honestly until configured."""
    _clear_env(monkeypatch)
    assert jobs._fetch_linkedin_jobs(5, ["dentist"], "Egypt") == []
    assert jobs._fetch_google_jobs(5, ["dentist"], "Egypt") == []
    assert jobs._provider_status["LinkedIn"]["reason"] == "host_not_configured"
    assert jobs._provider_status["Google Jobs"]["reason"] == "host_not_configured"


def test_rapidapi_key_priority_override_then_shared(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("RAPIDAPI_KEY", "shared-key")
    assert jobs._rapidapi_key("RAPIDAPI_LINKEDIN_KEY") == "shared-key"
    monkeypatch.setenv("RAPIDAPI_LINKEDIN_KEY", "specific-key")
    assert jobs._rapidapi_key("RAPIDAPI_LINKEDIN_KEY") == "specific-key"


def test_linkedin_normalises_payload(monkeypatch):
    _clear_env(monkeypatch)
    _config(monkeypatch, "linkedin.example.p.rapidapi.com", "li-key")
    captured = {}

    def fake_get(url, params=None, timeout=None, headers=None, **kwargs):
        captured["headers"] = headers
        captured["params"] = params
        assert headers.get("X-RapidAPI-Key") == "li-key"
        assert headers.get("X-RapidAPI-Host") == "linkedin.example.p.rapidapi.com"
        return _fake_resp({"data": {"jobs": [
            {"job_title": "Specialist Dentist", "company_name": "Al Noor Clinic",
             "url": "https://linkedin.example.test/jobs/spec-dentist",
             "job_city": "Dubai", "job_country": "United Arab Emirates",
             "job_description": "Provide dental care.",
             "job_posted_at_datetime_utc": "2026-02-01T00:00:00Z",
             "job_type": "full_time", "salary_min": 1500},
        ]}})

    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    items = jobs._fetch_linkedin_jobs(5, ["dentist"], "Egypt")

    assert captured["params"]["location"] == "Egypt"
    assert captured["params"]["query"] == "dentist"
    assert len(items) == 1
    j = items[0]
    assert j["source"] == "LinkedIn"
    assert j["title"] == "Specialist Dentist"
    assert j["company"] == "Al Noor Clinic"
    assert j["url"].startswith("https://linkedin.example.test")
    assert "Dubai" in j["location"]
    assert j["country"] == "United Arab Emirates"
    assert j["date"] == "2026-02-01"
    assert j["employment_type"] == "full_time"
    assert "dental" in j["description"]
    assert jobs._provider_status["LinkedIn"]["status"] == "ok"
    assert jobs._provider_status["LinkedIn"]["count"] == 1


def test_google_normalises_results_payload(monkeypatch):
    _clear_env(monkeypatch)
    _config(monkeypatch, "google.example.p.rapidapi.com", "gg-key",
            key_var="RAPIDAPI_GOOGLE_JOBS_KEY")

    def fake_get(url, params=None, timeout=None, headers=None, **kwargs):
        assert headers.get("X-RapidAPI-Key") == "gg-key"
        return _fake_resp({"results": [
            {"title": "Software Developer", "company": "TechHub",
             "external_url": "https://google.example.test/roles/sw-dev",
             "location": "Cairo, Egypt", "snippet": "Build web services.",
             "posted_date": "2026-01-10", "work_type": "hybrid"},
        ]})

    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    items = jobs._fetch_google_jobs(5, ["software developer"], "Egypt")

    assert len(items) == 1
    j = items[0]
    assert j["source"] == "Google Jobs"
    assert j["title"] == "Software Developer"
    assert "Cairo" in j["location"]
    assert j["date"] == "2026-01-10"
    assert j["employment_type"] == "hybrid"
    assert jobs._provider_status["Google Jobs"]["status"] == "ok"


def test_rapidapi_provider_empty_result_is_ok(monkeypatch):
    _clear_env(monkeypatch)
    _config(monkeypatch, "linkedin.example.p.rapidapi.com", "li-key")

    def fake_get(url, params=None, timeout=None, headers=None, **kwargs):
        return _fake_resp({"data": {"jobs": []}})

    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    assert jobs._fetch_linkedin_jobs(5, ["dentist"], "Egypt") == []
    assert jobs._provider_status["LinkedIn"]["status"] == "ok"
    assert jobs._provider_status["LinkedIn"]["count"] == 0


def test_rapidapi_provider_timeout_degrades(monkeypatch):
    _clear_env(monkeypatch)
    _config(monkeypatch, "linkedin.example.p.rapidapi.com", "li-key")

    def fake_get(url, params=None, timeout=None, headers=None, **kwargs):
        raise httpx.ConnectTimeout("connection timed out",
                                   request=httpx.Request("GET", str(url)))

    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    assert jobs._fetch_linkedin_jobs(5, ["dentist"], "Egypt") == []
    assert jobs._provider_status["LinkedIn"]["status"] == "failed"
    assert jobs._provider_status["LinkedIn"]["reason"] == "network_unreachable"


def test_rapidapi_provider_rate_limit_degrades(monkeypatch):
    _clear_env(monkeypatch)
    _config(monkeypatch, "google.example.p.rapidapi.com", "gg-key",
            key_var="RAPIDAPI_GOOGLE_JOBS_KEY")

    def fake_get(url, params=None, timeout=None, headers=None, **kwargs):
        return _fake_resp({"message": "rate limit"}, status=429)

    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    assert jobs._fetch_google_jobs(5, ["dentist"], "Egypt") == []
    assert jobs._provider_status["Google Jobs"]["status"] == "failed"
    assert jobs._provider_status["Google Jobs"]["reason"] == "rate_limited"


def test_rapidapi_provider_auth_error_in_200_body(monkeypatch):
    """A 200 body with only an error/message and no jobs is a failure, not empty."""
    _clear_env(monkeypatch)
    _config(monkeypatch, "linkedin.example.p.rapidapi.com", "li-key")

    def fake_get(url, params=None, timeout=None, headers=None, **kwargs):
        return _fake_resp({"message": "You are not subscribed to this API."})

    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    assert jobs._fetch_linkedin_jobs(5, ["dentist"], "Egypt") == []
    assert jobs._provider_status["LinkedIn"]["status"] == "failed"
    assert any(s in jobs._provider_status["LinkedIn"]["error"]
               for s in ("not subscribed", "You are not subscribed"))


def test_redact_covers_all_rapidapi_key_vars(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("RAPIDAPI_KEY", "rapid-shared-secret")
    monkeypatch.setenv("RAPIDAPI_LINKEDIN_KEY", "linkedin-secret")
    monkeypatch.setenv("RAPIDAPI_GOOGLE_JOBS_KEY", "google-secret")
    monkeypatch.setenv("JOOBLE_API_KEY", "jooble-secret")
    msg = ("key=rapid-shared-secret a=linkedin-secret b=google-secret "
           "c=jooble-secret JSEARCH=fake-jsearch-key")
    monkeypatch.setenv("JSEARCH_API_KEY", "fake-jsearch-key")
    out = jobs._redact(msg)
    assert "rapid-shared-secret" not in out
    assert "linkedin-secret" not in out
    assert "google-secret" not in out
    assert "jooble-secret" not in out
    assert "fake-jsearch-key" not in out
    assert out.count("***") >= 5


def test_merge_dedupes_same_listing_across_providers():
    """One vacancy surfaced by two providers must collapse to a single job."""
    base = {
        "title": "Senior Dentist", "company": "Prime Clinic",
        "url": "https://apply.example.test/senior-dentist?utm_source=career",
        "location": "Dubai, United Arab Emirates",
    }
    raw = [
        dict(base, source="JSearch", description="Dental practice"),
        dict(base, url="https://apply.example.test/senior-dentist?utm_source=linkedin",
             source="LinkedIn", description="Dental practice"),
    ]
    merged = jobs._merge(raw)
    assert len(merged) == 1
    assert merged[0]["source"] in ("JSearch", "LinkedIn")