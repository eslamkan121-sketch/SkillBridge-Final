"""Regression guard for the relocation-market feed bug.

Reported: a student picking "United Arab Emirates" (or any relocation market)
in the Dashboard feed saw the same results for every market, and the local
feed was empty. Root cause: every country-scoped provider (JSearch, Jooble,
Adzuna) was skipped with ``no_credentials`` because no key was configured, so
the market selection never reached any provider that could honour it — the
only responding feeds were global remote/tech boards.

These tests pin the two halves of the fix:
1. Offline + deterministic: when a JSearch key IS present the chosen market
   flows into JSearch's ``country`` parameter (the exact path that was dead,
   because the provider was silently skipped) and Egypt vs UAE get different
   ISO country codes with the SAME query.
2. Live + key-gated: with a real key exported in the SHELL environment the
   Egypt and UAE feeds genuinely return distinct, on-topic listings. This is
   the "prove the provider before paying" check for the free/trial tier.

Credential hygiene: the suite NEVER reads ``.env`` (main._load_env is a no-op
under pytest), so the live check runs only when JSEARCH_API_KEY (or
RAPIDAPI_KEY) is exported explicitly for the test run:
    set JSEARCH_API_KEY=...  (PowerShell)   or   export JSEARCH_API_KEY=...
    python -m pytest tests/test_jobs_market_divergence.py -k live -s
"""
import pytest

from app import jobs

TEST_KEY = jobs.os.environ.get("JSEARCH_API_KEY") or jobs.os.environ.get("RAPIDAPI_KEY")


def _fake_jsearch_response():
    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": {"jobs": [
                {"job_title": "Dentist (General Practice)",
                 "employer_name": "Al Noor Clinic",
                 "job_apply_link": "https://example.test/dentist-1",
                 "job_city": "Dubai",
                 "job_country": "United Arab Emirates",
                 "job_location": "Dubai, United Arab Emirates",
                 "job_is_remote": False,
                 "job_posted_at_datetime_utc": "2026-01-05T00:00:00Z",
                 "job_employment_type": "full_time",
                 "job_expired_flag": "not_expired",
                 "job_description": "Provide dental care to patients.",
                 "job_salary_currency": "AED",
                 "job_min_salary": 10000,
                 "job_max_salary": 20000,
                 "job_salary_period": "monthly",
                 "job_publisher": "Bayt",
                 "job_employment_types": ["full_time"],
                 }]}}

    return R()


def test_market_reaches_jsearch_country_param(monkeypatch):
    """The dead path: without this, picking a market never reached the provider."""
    monkeypatch.setenv("JSEARCH_API_KEY", "fake-key")
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    captured = {}

    def fake_get(url, params=None, timeout=None, headers=None, **kwargs):
        captured["params"] = params
        return _fake_jsearch_response()

    monkeypatch.setattr(jobs.httpx, "get", fake_get)

    ae = jobs._fetch_jsearch(5, ["dentist"], "United Arab Emirates")
    p_ae = captured["params"]
    captured.clear()
    eg = jobs._fetch_jsearch(5, ["dentist"], "Egypt")
    p_eg = captured["params"]

    # The selected market must change the provider's country scope (ae/eg),
    # never the search query.
    assert p_ae.get("country") == "ae"
    assert p_eg.get("country") == "eg"
    assert p_ae.get("query") == p_eg.get("query")
    assert [j["country"] for j in ae] == ["United Arab Emirates"]


def test_market_iso_only_when_known(monkeypatch):
    """Unknown/free-text markets fall back to the location param, never break."""
    monkeypatch.setenv("JSEARCH_API_KEY", "fake-key")
    captured = {}

    def fake_get(url, params=None, timeout=None, headers=None, **kwargs):
        captured["params"] = params
        return _fake_jsearch_response()

    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    jobs._fetch_jsearch(5, ["dentist"], "Somewhere Else")
    assert "country" not in captured["params"]
    assert captured["params"].get("location") == "Somewhere Else"


@pytest.mark.skipif(not TEST_KEY, reason="no JSEARCH_API_KEY/RAPIDAPI_KEY exported (suite never reads .env)")
def test_live_market_divergence_ae_vs_eg():
    """Live end-to-end check — the outputs the UI must differ on.

    Runs the exact pipeline the Dashboard uses (recent_jobs with the student's
    skills/role and the selected relocation market) against the real providers.
    With a working (e.g. free/trial) key, the UAE market must return real
    dentist-relevant listings and Egypt must NOT return the same set — otherwise
    the original bug (same results for every market) is unconfirmed against
    real data.
    """
    profile = [("Dentistry", "Intermediate", False), ("Orthodontics", "Intermediate", False)]
    role = "Specialist Dentist"

    ae = jobs.recent_jobs(skills=profile, role=role, country="Egypt", location="Cairo",
                          limit=10, market_country="ae", _sync=True)
    eg = jobs.recent_jobs(skills=profile, role=role, country="Egypt", location="Cairo",
                          limit=10, market_country="eg", _sync=True)

    # "unavailable" means every provider errored — with a key present that is a
    # credential/provider failure worth failing the check on.
    assert ae.get("source") != "unavailable", f"UAE feed unavailable: {ae.get('providers')}"
    assert eg.get("source") != "unavailable", f"Egypt feed unavailable: {eg.get('providers')}"

    ae_jobs = ae.get("jobs", [])
    eg_jobs = eg.get("jobs", [])
    # At least one market must actually serve regional listings, and the two
    # markets must never return byte-identical result sets.
    assert ae_jobs or eg_jobs, "neither UAE nor Egypt returned any live listing"
    assert {j["url"] for j in ae_jobs} != {j["url"] for j in eg_jobs}, (
        "UAE and Egypt markets returned identical listings — market scoping is not reaching the provider"
    )

    def on_topic(items):
        return any("dentist" in ((j.get("title") or "") + " " + (j.get("description") or "")).lower() for j in items)

    if ae_jobs:
        assert on_topic(ae_jobs), f"UAE listings are not dentist-relevant: {[j['title'] for j in ae_jobs[:5]]}"
    if eg_jobs:
        assert on_topic(eg_jobs), f"Egypt listings are not dentist-relevant: {[j['title'] for j in eg_jobs[:5]]}"