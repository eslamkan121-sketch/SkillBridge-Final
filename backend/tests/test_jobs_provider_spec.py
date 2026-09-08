"""Provider-integration & Smart-Ranking spec tests.

Every test here is fully offline and mocked - no live provider quota is ever
spent (the API keys in the local .env are untouched: each test that needs a
configured provider sets a throwaway key with monkeypatch, and every test that
must run without a provider removes the key first).

Covers the 20 required cases from the Live Jobs Provider Integration &
Smart Ranking spec.
"""
import json

import httpx
import pytest

from app import jobs


def _reset_feed():
    jobs._cache.update({"at": 0.0, "key": "", "data": None})
    for p in jobs.PROVIDERS:
        jobs._provider_status[p] = {"status": "skipped", "count": 0, "reason": "", "error": ""}


def _provider(data, source):
    """Return the per-provider status report for ``source`` from a payload."""
    return next((p for p in data.get("providers", []) if p["source"] == source), {})


class _Resp:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


@pytest.fixture(autouse=True)
def _fresh_feed():
    _reset_feed()
    yield
    _reset_feed()


def test_jsearch_market_code_eg_maps_to_country_param(monkeypatch):
    """The relocation dropdown on the Dashboard sends the ISO market code (``eg``
    for Egypt, matching the backend alias map). That must resolve to the JSearch
    ``country=eg`` request parameter so Egypt job POSTINGS actually come back."""
    assert jobs._jsearch_country_param("Egypt") == "eg"
    assert jobs._jsearch_country_param("eg") == "eg"
    assert jobs._jsearch_country_param("") == ""

    captured = {}
    monkeypatch.setenv("JSEARCH_API_KEY", "rapid-key")

    def fake_get(url, **kwargs):
        captured["url"] = str(url)
        captured["params"] = kwargs.get("params") or {}
        return _Resp({"data": {"jobs": [], "cursor": None}})

    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    jobs._fetch_jsearch(5, ["legal assistant"], "eg")
    assert captured["params"].get("country") == "eg"
    assert ("Egypt" in str(captured["url"]) or "jsearch" in str(captured["url"]))


@pytest.fixture()
def sync_build():
    """Run a synchronous build for the labelled keys; reset cache each call."""
    def build(**kw):
        return jobs.recent_jobs(
            skills=kw.get("skills") or [("SQL", "Beginner")],
            role=kw.get("role") or "Data Analyst",
            country=kw.get("country") or "Egypt",
            location=kw.get("location") or "",
            limit=kw.get("limit") or 10,
            role_requisites=kw.get("requisites") or (),
            market_country=kw.get("market_country") or "",
            _sync=True,
        )
    return build


# --------------------------------------------------------------------------- 1-7
# Provider normalisation: canonical fields + never-fabricate behaviour


def test_jsearch_normalises_to_canonical_fields(monkeypatch):
    monkeypatch.setenv("JSEARCH_API_KEY", "rapid-key")
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)

    def fake_get(url, **kwargs):
        return _Resp({"data": {"jobs": [{
            "job_title": "Junior Data Analyst",
            "employer_name": "DataCorp",
            "job_apply_link": "https://apply.example.test/j1",
            "job_is_remote": True,
            "job_employment_types": ["FULLTIME"],
            "job_employment_type": "",
            "job_publisher": "GulfTalent",
            "job_posted_at_datetime_utc": "2026-08-21T10:00:00.000Z",
            "job_city": "Cairo", "job_state": "", "job_country": "Egypt",
            "job_description": "<p>Use Excel dashboards and SQL daily.</p>",
            "job_min_salary": 10000, "job_max_salary": 15000,
            "job_salary_currency": "EUR", "job_salary_period": "month",
        }]}})

    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    raw = jobs._fetch_jsearch(5, ["data", "analyst"], "Egypt")
    assert raw[0]["source"] == "JSearch"
    assert raw[0]["description"].startswith("<p>Use Excel dashboards")
    assert raw[0]["employment_type"] == "Fulltime"
    assert raw[0]["salary"] == "10,000 - 15,000 EUR/month"

    merged = jobs._merge(raw)[0]
    assert merged["description"].startswith("Use Excel dashboards")
    assert merged["id"] and len(merged["id"]) == 12
    assert merged["workplace_type"] == "remote"
    assert "SQL" in merged["required_skills"] or "Data Analysis" in merged["required_skills"]


def test_jsearch_legacy_list_without_description_noop(monkeypatch):
    monkeypatch.setenv("JSEARCH_API_KEY", "rapid-key")
    monkeypatch.setattr(jobs.httpx, "get", lambda *a, **k: _Resp({"data": []}))
    assert jobs._fetch_jsearch(5, ["data"]) == []


def test_adzuna_normalises_salary_and_metadata(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "test-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "test-key")

    def fake_get(url, **kwargs):
        return _Resp({"results": [{
            "title": "Data Analyst (Entry)", "company": {"display_name": "Adzuna Co"},
            "redirect_url": "https://www.adzuna.co.uk/jobs/1",
            "location": {"display_name": "Cairo, Egypt"},
            "description": "Aggregate <b>data</b> and report insights.",
            "salary_min": 10000, "salary_max": 12000,
            "contract_time": "full_time", "contract_type": "permanent",
            "category": {"label": "Information Technology"},
            "created": "2026-08-21T09:00:00",
        }]})

    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    raw = jobs._fetch_adzuna(5, ["data"], "United Kingdom")
    assert raw[0]["source"] == "Adzuna"
    assert raw[0]["salary"] == "10,000 - 12,000"
    assert raw[0]["employment_type"] == "full time"
    assert raw[0]["description"] == "Aggregate <b>data</b> and report insights."
    assert "Unknown" not in raw[0]["company"]

    merged = jobs._merge(raw)[0]
    assert merged["description"] == "Aggregate data and report insights."

    merged = jobs._merge(raw)[0]
    assert len(merged["id"]) == 12
    assert merged["workplace_type"] == ""  # unknown is never invented


def test_usajobs_extracts_nested_description(monkeypatch):
    monkeypatch.setenv("USAJOBS_API_KEY", "secret-key")

    def fake_get(url, **kwargs):
        return _Resp({"SearchResult": {"SearchResultItems": [{
            "MatchedObjectDescriptor": {
                "PositionTitle": "Data Analyst",
                "OrganizationName": "Federal Agency",
                "PositionURI": "https://www.usajobs.gov/job/1",
                "UserArea": {"Details": {"JobSummary": "Analyze workforce data sets."}},
                "PositionLocation": [{"LocationName": "Washington, DC"}],
                "JobCategory": [{"Name": "Data Analysis"}],
            },
        }]}})

    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    raw = jobs._fetch_usajobs(5, ["data"], "United States")
    assert raw[0]["source"] == "USAJobs"
    assert raw[0]["description"] == "Analyze workforce data sets."


def test_remotive_normalises_and_keeps_salary(monkeypatch):
    def fake_get(url, **kwargs):
        return _Resp({"jobs": [{
            "title": "Data Analyst (Entry)", "company_name": "Remote Data Co",
            "url": "https://remotive.com/remote-jobs/1", "publication_date": "2026-08-21",
            "candidate_required_location": "Remote", "tags": ["SQL", "Data"],
            "job_type": "full_time", "salary": "45000",
        }]})

    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    raw = jobs._fetch_remotive(5)
    assert raw[0]["source"] == "Remotive"
    assert raw[0]["salary"] == "45000"
    assert raw[0]["employment_type"] == "full_time"
    merged = jobs._merge(raw)[0]
    assert len(merged["id"]) == 12


def test_jobicy_uses_description_over_excerpt(monkeypatch):
    def fake_get(url, **kwargs):
        return _Resp({"jobs": [{
            "jobTitle": "Marketing Assistant", "companyName": "Acme Data",
            "url": "https://jobicy.com/jobs/1", "pubDate": "2026-09-02T10:00:00+00:00",
            "jobGeo": "Remote", "jobIndustry": ["Marketing"], "jobType": ["Full-Time"],
            "jobLevel": "Junior", "jobDescription": "Run campaign reports.",
            "jobExcerpt": "truncated…",
        }]})

    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    raw = jobs._fetch_jobicy(5)
    assert raw[0]["source"] == "Jobicy"
    assert raw[0]["description"] == "Run campaign reports."
    assert raw[0]["employment_type"] == "Full-Time"


def test_arbeitnow_preserves_date_and_description(monkeypatch):
    def fake_get(url, **kwargs):
        return _Resp({"data": [{
            "title": "Data Engineer (Junior)", "company_name": "Glow ATS",
            "url": "https://www.arbeitnow.com/jobs/glow/1", "location": "Berlin",
            "remote": False, "tags": ["Golang"], "job_types": ["Full-time"],
            "description": "Maintain pipelines in Go.", "created_at": 1788630907,
        }]})

    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    raw = jobs._fetch_arbeitnow(5)
    assert raw[0]["source"] == "Arbeitnow"
    assert raw[0]["description"] == "Maintain pipelines in Go."
    assert raw[0]["date"] == 1788630907


def test_remoteok_keeps_description_and_expires(monkeypatch):
    def fake_get(url, **kwargs):
        return _Resp([{
            "position": "Junior Data Analyst", "company": "RemoteOK Data",
            "url": "https://remoteok.com/job/1", "date": "2026-08-22",
            "location": "Remote", "tags": ["SQL"], "description": "Query dashboards.",
            "expires": "2026-09-22",
        }])

    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    raw = jobs._fetch_remoteok(5)
    assert raw[0]["source"] == "RemoteOK"
    assert raw[0]["description"] == "Query dashboards."
    assert raw[0]["expires"] == "2026-09-22"


# ------------------------------------------------------------------ 8-9
# Provider failures never break the feed


def test_jooble_failure_never_breaks_the_feed(monkeypatch, sync_build):
    _reset_feed()
    for var in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "JSEARCH_API_KEY",
                "RAPIDAPI_KEY", "USAJOBS_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("JOOBLE_API_KEY", "test-key")

    def fake_get(url, **kwargs):
        u = str(url)
        if "jobicy.com" in u:
            return _Resp({"jobs": [{
                "jobTitle": "Data Analyst", "companyName": "Acme",
                "url": "https://jobicy.com/jobs/1", "jobGeo": "Cairo, Egypt",
                "jobIndustry": ["Analytics"], "jobType": ["Full-Time"], "jobLevel": "Junior",
            }]})
        if "arbeitnow.com" in u:
            return _Resp({"data": [{
                "title": "Data Analyst", "company_name": "Glow ATS",
                "url": "https://www.arbeitnow.com/jobs/glow/1", "location": "Berlin",
                "remote": False, "tags": ["data"], "job_types": ["Full-time"],
            }]})
        return _Resp({"jobs": [{
            "title": "Data Analyst", "company_name": "Remote Data Co",
            "url": "https://remotive.com/remote-jobs/1", "publication_date": "2026-08-21",
            "candidate_required_location": "Remote", "tags": ["Data", "SQL"],
        }]})

    def boom_post(*args, **kwargs):
        raise httpx.ConnectError("jooble unreachable")

    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    monkeypatch.setattr(jobs.httpx, "post", boom_post)

    data = sync_build()
    assert data["source"] == "live"
    assert len(data["jobs"]) > 0
    # Jooble attempted (credential configured) but its API unreachable → failed.
    assert _provider(data, "Jooble").get("status") == "failed"
    assert _provider(data, "Remotive").get("status") == "ok"


def test_single_provider_failure_does_not_break_the_feed(monkeypatch, sync_build):
    _reset_feed()
    monkeypatch.setenv("ADZUNA_APP_ID", "test-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "test-key")
    for var in ("JSEARCH_API_KEY", "RAPIDAPI_KEY", "USAJOBS_API_KEY", "JOOBLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    def fake_get(url, **kwargs):
        u = str(url)
        if "adzuna.com" in u:
            raise httpx.HTTPStatusError("403 from adzuna", request=httpx.Request("GET", u), response=None)
        if "jobicy.com" in u:
            return _Resp({"jobs": [{
                "jobTitle": "Data Analyst", "companyName": "Acme",
                "url": "https://jobicy.com/jobs/2", "jobGeo": "Cairo, Egypt",
                "jobIndustry": ["Analytics"], "jobType": ["Full-Time"], "jobLevel": "Junior",
            }]})
        return _Resp({"jobs": [{
            "title": "Data Analyst", "company_name": "Remote Data Co",
            "url": "https://remotive.com/remote-jobs/2", "publication_date": "2026-08-21",
            "candidate_required_location": "Remote", "tags": ["Data", "SQL"],
        }]})

    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    data = sync_build(country="United Kingdom")
    assert data["source"] == "live"
    assert len(data["jobs"]) > 0
    assert _provider(data, "Adzuna").get("status") == "failed"
    assert _provider(data, "Remotive").get("status") == "ok"


# ------------------------------------------------------------------ 10-11
# Aggregation and deduplication


def test_multiple_providers_aggregate_and_dedupe(monkeypatch, sync_build):
    _reset_feed()
    monkeypatch.setenv("ADZUNA_APP_ID", "test-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "test-key")
    for var in ("JSEARCH_API_KEY", "RAPIDAPI_KEY", "USAJOBS_API_KEY", "JOOBLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    def fake_get(url, **kwargs):
        u = str(url)
        if "jobicy.com" in u:
            return _Resp({"jobs": [{
                "jobTitle": "Data Analyst", "companyName": "Acme",
                "url": "https://jobicy.com/jobs/3", "jobGeo": "Cairo, Egypt",
                "jobIndustry": ["Analytics"], "jobType": ["Full-Time"], "jobLevel": "Junior",
            }]})
        if "arbeitnow.com" in u:
            return _Resp({"data": [{
                "title": "Data Analyst", "company_name": "Glow ATS",
                "url": "https://www.arbeitnow.com/jobs/glow/3", "location": "Berlin",
                "remote": False, "tags": ["Excel"], "job_types": ["Full-time"],
            }]})
        if "adzuna.com" in u:
            return _Resp({"results": [{
                "title": "Data Analyst (Entry)", "company": {"display_name": "Gulf Data"},
                "redirect_url": "https://www.example.test/adzuna/3",
                "location": {"display_name": "Cairo, Egypt"},
                "description": "Aggregate data and report insights.",
                "salary_min": 8000, "salary_max": 10000,
                "category": {"label": "Information Technology"},
                "created": "2026-08-21T09:00:00",
            }]})
        return _Resp({"jobs": [{
            "title": "Data Analyst", "company_name": "JC Remotive",
            "url": "https://remotive.com/remote-jobs/3", "publication_date": "2026-08-21",
            "candidate_required_location": "Remote", "tags": ["Data", "SQL"],
        }]})

    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    # RemoteOK serves the SAME listing (title/company/location) as Remotive, but
    # a different URL - it must merge into one job, never duplicate.
    monkeypatch.setattr(jobs, "_fetch_remoteok", lambda n: [{
        "title": "Data Analyst", "company": "JC Remotive",
        "url": "https://remoteok.com/dup/3", "date": "2026-08-22",
        "location": "Remote", "tags": ["SQL"], "description": "Same role, two boards.",
        "source": "RemoteOK",
    }])

    data = sync_build(country="United Kingdom")
    assert data["source"] == "live"
    assert len(data["jobs"]) == 4
    assert len({j["url"] for j in data["jobs"]}) == 4
    assert len([j for j in data["jobs"] if j["company"] == "JC Remotive"]) == 1
    sources = {j["source"] for j in data["jobs"]}
    # the Remotive/RemoteOK duplicate must survive as exactly one listing,
    # carrying the richer record's metadata (RemoteOK in this case)
    assert sources == {"RemoteOK", "Jobicy", "Arbeitnow", "Adzuna"}
    merged = [j for j in data["jobs"] if j["company"] == "JC Remotive"][0]
    assert merged["description"] == "Same role, two boards."
    adzuna = [j for j in data["jobs"] if j["source"] == "Adzuna"][0]
    assert adzuna["salary"] == "8,000 - 10,000"


def test_duplicate_apply_urls_across_providers_merge(monkeypatch, sync_build):
    monkeypatch.setattr(jobs, "_fetch_all", lambda *a, **k: [
        {"title": "Data Analyst", "company": "X", "url": "https://x/dup",
         "location": "Remote", "tags": ["data", "sql"], "source": "Remotive"},
        {"title": "Data Analyst", "company": "X", "url": "https://x/dup",
         "location": "Remote", "tags": ["sql", "excel"], "salary": "30,000",
         "source": "RemoteOK"},
    ])
    data = sync_build()
    assert len(data["jobs"]) == 1
    assert data["jobs"][0]["salary"] == "30,000"
    assert data["jobs"][0]["tags"] == ["data", "sql", "excel"]


# ------------------------------------------------------------------ 12-15
# Expiry, target-role-driven search, non-CS domains


def test_expired_listings_are_dropped_before_ranking(monkeypatch, sync_build):
    monkeypatch.setattr(jobs, "_fetch_all", lambda *a, **k: [
        {"title": "Data Analyst", "company": "Live Co", "url": "https://l/1",
         "location": "Cairo, Egypt", "tags": ["data"], "source": "JSearch"},
        {"title": "Data Analyst", "company": "Dead Co", "url": "https://d/1",
         "location": "Cairo, Egypt", "tags": ["data"], "source": "Jobicy",
         "expired": "expired"},
    ])
    data = sync_build()
    assert "Dead Co" not in {j["company"] for j in data["jobs"]}
    assert "Live Co" in {j["company"] for j in data["jobs"]}


def test_target_role_leads_fetch_keywords_and_skills_follow(monkeypatch, sync_build):
    captured = {}

    def fake_fetch(limit_each, keywords=(), country="", adzuna_country=""):
        captured["keywords"] = list(keywords)
        return []

    monkeypatch.setattr(jobs, "_fetch_all", fake_fetch)
    sync_build(role="Graphic Designer", requisites=["Adobe Photoshop", "Illustrator"],
               skills=[("Photoshop", "Intermediate"), ("Excel", "Beginner")])

    primary, minor = jobs._cluster_keywords(
        ["Photoshop", "Excel"], "Graphic Designer", ["Adobe Photoshop", "Illustrator"])
    assert primary[0] == "graphic", primary
    assert primary[1] == "designer", primary
    assert "photoshop" in primary
    assert captured["keywords"][0] == "graphic", captured
    assert captured["keywords"][1] == "designer", captured
    assert "excel" in minor and "excel" not in captured["keywords"][:3], captured


def test_non_cs_target_role_ranks_over_cs_noise(monkeypatch, sync_build):
    monkeypatch.setattr(jobs, "_fetch_all", lambda *a, **k: [
        {"title": "Junior Graphic Designer", "company": "Studio A",
         "url": "https://s/a1", "location": "Cairo, Egypt", "tags": ["design"], "source": "JSearch"},
        {"title": "Java Developer", "company": "Software Co",
         "url": "https://s/a2", "location": "Cairo, Egypt", "tags": ["java"], "source": "Remotive"},
        {"title": "Graphic Designer", "company": "Brand Co",
         "url": "https://s/a3", "location": "Remote", "tags": ["photoshop", "illustrator"],
         "source": "RemoteOK"},
    ])
    data = sync_build(role="Graphic Designer",
                      requisites=["Adobe Photoshop", "Illustrator"],
                      skills=[("Photoshop", "Intermediate"), ("Illustrator", "Intermediate")])
    companies = {j["company"] for j in data["jobs"]}
    assert "Studio A" in companies and "Brand Co" in companies
    assert "Software Co" not in companies


def test_non_cs_skills_survive_and_unknown_tags_preserved(monkeypatch):
    raw = [{
        "title": "Graphic Designer", "company": "D", "url": "https://d/t1",
        "location": "Cairo", "tags": ["design", "ZBrush", "Brand Identity"],
        "description": "Working on digital branding assets.", "source": "Jobicy",
    }]
    merged = jobs._merge(raw)[0]
    assert "ZBrush" in merged["tags"]
    assert "Photoshop" not in merged["required_skills"]
    assert "Brand Identity" in merged["required_skills"]
    assert "Git" not in merged["required_skills"]  # "git" inside "digital" must not match


# ------------------------------------------------------------------ 16-18
# Verified-skills and recency ranking


def test_verified_skill_earns_small_boost(monkeypatch):
    job = {"title": "Junior Graphic Designer", "company": "D", "url": "https://d/r1",
           "location": "Remote", "tags": ["photoshop", "illustrator", "design"],
           "description": "", "source": "T"}
    kw, minor = jobs._cluster_keywords(["Photoshop", "Illustrator"], "Graphic Designer",
                                       ["Adobe Photoshop"])
    base = jobs._apply([job], kw, 1, "Egypt", "", jobs._role_family("Graphic Designer"),
                       minor_keywords=minor, role_driven=True)[0]
    boosted = jobs._apply([job], kw, 1, "Egypt", "", jobs._role_family("Graphic Designer"),
                          minor_keywords=minor, role_driven=True,
                          verified_skills=["Photoshop"])[0]
    assert boosted["match_pct"] == base["match_pct"] + 3
    assert "1 matched skill verified." in boosted["match_reason"]


def test_verified_skill_cannot_overstep_target_role(monkeypatch):
    devops = {"title": "DevOps Engineer", "company": "Ops", "url": "https://d/o1",
              "location": "Remote", "tags": ["docker", "kubernetes"],
              "description": "Docker daily.", "source": "T"}
    design = {"title": "Junior Graphic Designer", "company": "Studio", "url": "https://d/o2",
              "location": "Remote", "tags": ["photoshop", "illustrator"],
              "description": "", "source": "T"}
    kw, minor = jobs._cluster_keywords(["Photoshop", "Illustrator"], "Graphic Designer",
                                       ["Adobe Photoshop"])
    ranked = jobs._apply([devops, design], kw, 1, "Egypt", "",
                         jobs._role_family("Graphic Designer"), minor_keywords=minor,
                         role_driven=True, verified_skills=["Docker"])
    assert [j["company"] for j in ranked] == ["Studio"]


def test_recent_listing_gets_small_recency_edge(monkeypatch):
    job = {"title": "Junior Graphic Designer", "company": "D", "url": "https://d/f1",
           "location": "Remote", "tags": ["photoshop", "illustrator"],
           "description": "", "source": "T"}
    kw, minor = jobs._cluster_keywords(["Photoshop", "Illustrator"], "Graphic Designer",
                                       ["Adobe Photoshop"])
    fresh = dict(job, listed_days_ago=1)
    old = dict(job, listed_days_ago=20)
    params = dict(keywords=kw, student_seniority=1, country="Egypt", city="",
                  role_family=jobs._role_family("Graphic Designer"),
                  minor_keywords=minor, role_driven=True)
    a = jobs._apply([fresh], **params)[0]
    b = jobs._apply([old], **params)[0]
    assert a["match_pct"] == b["match_pct"] + 3
    assert "Posted 1d ago." in a["match_reason"]


# ------------------------------------------------------------------ 19-20
# Honest empty state + controlled offline fallback + secret protection


def test_providers_answered_but_no_jobs_is_honest_empty(monkeypatch, sync_build):
    _reset_feed()
    for var in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "JSEARCH_API_KEY",
                "RAPIDAPI_KEY", "USAJOBS_API_KEY", "JOOBLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    def fake_get(url, **kwargs):
        return _Resp({})

    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    data = sync_build()
    assert data["source"] == "empty"
    assert data["jobs"] == []
    assert _provider(data, "Remotive").get("status") == "ok"
    assert all(p["status"] != "failed"
               for p in data["providers"]
               if p["source"] not in ("JSearch", "Adzuna", "USAJobs", "Jooble"))


def test_all_providers_down_is_empty_unavailable_not_fallback(monkeypatch, sync_build):
    _reset_feed()
    # keyed providers stay skipped (no throwaway key configured), so exactly the
    # four keyless feeds attempt and fail: Remotive, RemoteOK, Jobicy, Arbeitnow.
    # With every provider unreachable the result is an honest ``unavailable``
    # empty state — curated/demo jobs are never injected.

    def boom(*a, **k):
        raise OSError("no network")

    monkeypatch.delenv("JOOBLE_API_KEY", raising=False)
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    monkeypatch.delenv("JSEARCH_API_KEY", raising=False)
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    monkeypatch.delenv("USAJOBS_API_KEY", raising=False)
    monkeypatch.setattr(jobs.httpx, "get", boom)
    monkeypatch.setattr(jobs.httpx, "post", boom)
    data = sync_build()
    assert data["source"] == "unavailable"
    assert data["jobs"] == []
    assert len([p for p in data["providers"] if p["status"] == "failed"]) == 4


def test_secrets_never_reach_response_or_status(monkeypatch, sync_build):
    _reset_feed()
    monkeypatch.setenv("JSEARCH_API_KEY", "OMG_SECRET_JSH_7")
    monkeypatch.setenv("ADZUNA_APP_ID", "OMG_SECRET_AID_9")
    monkeypatch.setenv("ADZUNA_APP_KEY", "OMG_SECRET_AKEY_X")
    monkeypatch.setenv("JOOBLE_API_KEY", "OMG_SECRET_JBL_8")
    secrets = ("OMG_SECRET_JSH_7", "OMG_SECRET_AID_9", "OMG_SECRET_AKEY_X", "OMG_SECRET_JBL_8")

    def fake_get(url, **kwargs):
        u = str(url)
        if "adzuna.com" in u:
            raise httpx.HTTPStatusError(
                f"403 for url '{u}?app_id={secrets[1]}&app_key={secrets[2]}'",
                request=httpx.Request("GET", u), response=None)
        raise OSError(f"down: {u}")

    def fake_post(url, **kwargs):
        raise OSError(f"down: {url}")

    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    monkeypatch.setattr(jobs.httpx, "post", fake_post)
    data = sync_build()
    # 1) structured status is redacted
    for report in data["providers"]:
        assert not any(s in (report.get("error") or "") for s in secrets)
        assert not any(s in (report.get("reason") or "") for s in secrets)
    # 2) a zero-secret guarantee over the entire serialisable payload
    serialized = json.dumps(data)
    for s in secrets:
        assert s not in serialized
    # 3) direct redaction of a message embedding an Adzuna-style query string
    red = jobs._redact(f"503 for url 'https://api.adzuna.com/v1/api/jobs/gb/search/1?app_id={secrets[1]}&app_key={secrets[2]}'")
    assert secrets[1] not in red and secrets[2] not in red and "***" in red


# ======================================================================
# Jobs "Final Hardening" regression suite (fully mocked, zero live quota)
#
# 13 cases: Adzuna unsupported-country behaviour, live-feed honesty, target-role
# ranking dominance, seniority compatibility, explainability, provider status
# distinctions, and secret protection.
# ======================================================================


def test_adzuna_unsupported_country_skipped_with_reason(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "test-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "test-key")

    def boom_get(*a, **k):
        raise AssertionError("Adzuna must never be called for Egypt")

    monkeypatch.setattr(jobs.httpx, "get", boom_get)
    result = jobs._fetch_adzuna(5, ["data", "analyst"], "Egypt")
    assert result == []
    st = jobs._provider_status["Adzuna"]
    assert st["status"] == "skipped"
    assert st["reason"] == "unsupported_country"


def test_egypt_never_reaches_gb_adzuna_endpoint(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "test-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "test-key")
    calls = []

    def spy_get(url, **kw):
        calls.append(str(url))
        raise AssertionError("should not be reached")

    monkeypatch.setattr(jobs.httpx, "get", spy_get)
    assert jobs._fetch_adzuna(5, ["data"], "Egypt") == []
    assert not any("adzuna.com" in c for c in calls), "no gb fallback may be invoked"
    assert jobs._provider_status["Adzuna"]["reason"] == "unsupported_country"


def test_all_providers_fail_is_unavailable_with_no_curated_jobs(monkeypatch, sync_build):
    _reset_feed()
    for var in ("JOOBLE_API_KEY", "ADZUNA_APP_ID", "ADZUNA_APP_KEY",
                "JSEARCH_API_KEY", "RAPIDAPI_KEY", "USAJOBS_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    def boom(*a, **k):
        raise OSError("no network")

    monkeypatch.setattr(jobs.httpx, "get", boom)
    monkeypatch.setattr(jobs.httpx, "post", boom)
    data = sync_build()
    assert data["source"] == "unavailable"
    assert data["jobs"] == []
    # Live Jobs never surfaces a curated/demo listing.
    assert all("google.com/search" not in (j.get("url") or "") for j in data["jobs"])


def test_providers_ok_but_zero_listings_is_empty_not_unavailable(monkeypatch, sync_build):
    _reset_feed()
    for var in ("JOOBLE_API_KEY", "ADZUNA_APP_ID", "ADZUNA_APP_KEY",
                "JSEARCH_API_KEY", "RAPIDAPI_KEY", "USAJOBS_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    def fake_get(url, **kwargs):
        return _Resp({})

    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    data = sync_build()
    # Providers responded (Remotive/RemoteOK/Jobicy/Arbeitnow all ok, zero jobs):
    # an honest EMPTY state, clearly distinct from ``unavailable``.
    assert data["source"] == "empty"
    assert data["jobs"] == []
    assert _provider(data, "Remotive").get("status") == "ok"
    assert any(p["status"] == "ok" for p in data["providers"])


def test_live_feed_never_injects_curated_jobs(monkeypatch, sync_build):
    _reset_feed()
    monkeypatch.setattr(jobs, "_fetch_all", lambda *a, **k: [
        {"title": "Data Analyst", "company": "Real Co", "url": "https://real/a",
         "location": "Cairo, Egypt", "tags": ["data", "sql"], "source": "JSearch"},
    ])
    data = sync_build(role="Data Analyst", country="Egypt",
                      skills=[("SQL", "Intermediate")])
    assert data["source"] == "live"
    assert data["jobs"]
    assert all(j["source"] in jobs.PROVIDERS for j in data["jobs"])
    assert all("google.com/search" not in (j.get("url") or "") for j in data["jobs"])


def test_ai_engineer_ranks_ai_ml_before_python_backend(monkeypatch, sync_build):
    _reset_feed()
    monkeypatch.setattr(jobs, "_fetch_all", lambda *a, **k: [
        {"title": "AI Engineer", "company": "AI Co", "url": "https://x/a",
         "location": "Remote", "tags": ["python", "machine learning"], "source": "JSearch"},
        {"title": "ML Engineer", "company": "ML Co", "url": "https://x/b",
         "location": "Remote", "tags": ["machine learning"], "source": "Remotive"},
        {"title": "Python Backend Engineer", "company": "Backend Co", "url": "https://x/c",
         "location": "Remote", "tags": ["python", "sql"], "source": "Remotive"},
        {"title": "Data Entry Clerk", "company": "Clerk Co", "url": "https://x/d",
         "location": "Remote", "tags": [], "source": "Remotive"},
    ])
    data = sync_build(role="AI Engineer",
                      requisites=["Python", "Machine Learning"],
                      skills=[("Python", "Beginner"), ("Machine Learning", "Beginner")])
    companies = [j["company"] for j in data["jobs"]]
    assert companies[0] == "AI Co"
    assert companies.index("ML Co") < companies.index("Backend Co")
    assert "Clerk Co" not in companies


def test_marketing_analyst_outranks_head_of_marketing(monkeypatch, sync_build):
    _reset_feed()
    monkeypatch.setattr(jobs, "_fetch_all", lambda *a, **k: [
        {"title": "Marketing Analyst", "company": "Mkt Co", "url": "https://m/1",
         "location": "Remote", "tags": ["marketing"], "source": "JSearch"},
        {"title": "Head of Marketing", "company": "Lead Co", "url": "https://m/2",
         "location": "Remote", "tags": ["marketing"], "source": "Remotive"},
        {"title": "Software Engineer", "company": "Dev Co", "url": "https://m/3",
         "location": "Remote", "tags": [], "source": "Remotive"},
    ])
    data = sync_build(role="Marketing Analyst",
                      requisites=["Digital Marketing"],
                      skills=[("Marketing", "Beginner"), ("Excel", "Beginner")])
    companies = [j["company"] for j in data["jobs"]]
    assert companies[0] == "Mkt Co"
    assert "Lead Co" in companies and "Dev Co" not in companies
    lead = next(j for j in data["jobs"] if j["company"] == "Lead Co")
    assert lead["match_pct"] <= 15, "leadership role must be penalized for entry-level profile"


def test_graphic_designer_ranks_visual_designer_above_adobe_role(monkeypatch, sync_build):
    _reset_feed()
    monkeypatch.setattr(jobs, "_fetch_all", lambda *a, **k: [
        {"title": "Visual Designer", "company": "Viz Co", "url": "https://g/1",
         "location": "Remote", "tags": ["photoshop", "illustrator"], "source": "JSearch"},
        {"title": "Adobe Photoshop Specialist", "company": "Adobe Co", "url": "https://g/2",
         "location": "Remote", "tags": ["photoshop", "illustrator"],
         "description": "Photoshop Illustrator daily.", "source": "Remotive"},
        {"title": "Java Developer", "company": "Dev Co", "url": "https://g/3",
         "location": "Remote", "tags": ["java"], "source": "Remotive"},
    ])
    data = sync_build(role="Graphic Designer",
                      requisites=["Adobe Photoshop", "Illustrator"],
                      skills=[("Photoshop", "Intermediate"), ("Illustrator", "Intermediate")])
    companies = [j["company"] for j in data["jobs"]]
    assert companies[0] == "Viz Co", "Visual Designer must lead an Adobe-mentioning role"
    assert companies.index("Viz Co") < companies.index("Adobe Co")
    assert "Dev Co" not in companies


def test_verified_unrelated_skill_cannot_dethrone_target_role(monkeypatch, sync_build):
    _reset_feed()
    monkeypatch.setattr(jobs, "_fetch_all", lambda *a, **k: [
        {"title": "Junior Graphic Designer", "company": "Studio", "url": "https://v/1",
         "location": "Remote", "tags": ["photoshop", "illustrator"], "source": "JSearch"},
        {"title": "Java Developer", "company": "Java Shop", "url": "https://v/2",
         "location": "Remote", "tags": ["java", "docker"],
         "description": "Java Spring Docker Kubernetes.", "source": "Remotive"},
    ])
    data = sync_build(role="Graphic Designer",
                      requisites=["Adobe Photoshop"],
                      skills=[("Photoshop", "Intermediate"),
                              ("Java", "Intermediate", True)])
    companies = [j["company"] for j in data["jobs"]]
    assert companies == ["Studio"]
    assert "Java Shop" not in companies


def test_seniority_penalty_for_entry_level_targets():
    kw, minor = jobs._cluster_keywords(["Marketing"], "Marketing Analyst",
                                       ["Digital Marketing"])
    head = {"title": "Head of Marketing", "company": "Lead Co", "url": "https://s/1",
            "location": "Remote", "tags": ["marketing"], "source": "T"}
    coord = {"title": "Marketing Coordinator", "company": "Coord Co", "url": "https://s/2",
             "location": "Remote", "tags": ["marketing"], "source": "T"}
    ranked = jobs._apply([head, coord], kw, 0, "Egypt", "",
                         jobs._role_family("Marketing Analyst"),
                         minor_keywords=minor, role_driven=True,
                         role_title="Marketing Analyst")
    companies = [j["company"] for j in ranked]
    assert companies == ["Coord Co", "Lead Co"]
    lead = next(j for j in ranked if j["company"] == "Lead Co")
    assert lead["match_pct"] <= 15
    assert "senior" in lead["match_reason"].lower()


def test_ranking_reasons_reflect_actual_signals():
    kw, minor = jobs._cluster_keywords(["Python", "Machine Learning"],
                                       "AI Engineer",
                                       ["Python", "Machine Learning"])
    exact = {"title": "AI Engineer", "company": "A", "url": "https://r/1",
             "location": "Remote", "tags": ["python", "machine learning"], "source": "T"}
    close = {"title": "ML Engineer", "company": "B", "url": "https://r/2",
             "location": "Remote", "tags": ["machine learning"], "source": "T"}
    low = {"title": "Data Entry Clerk", "company": "C", "url": "https://r/3",
           "location": "Remote", "tags": [], "source": "T"}
    ranked = jobs._apply([exact, close, low], kw, 1, "Egypt", "",
                         jobs._role_family("AI Engineer"), minor_keywords=minor,
                         role_driven=True, role_title="AI Engineer")
    by_company = {j["company"]: j for j in ranked}
    assert "Target role closely matches" in by_company["A"]["match_reason"]
    assert "Closely aligned" in by_company["B"]["match_reason"]
    assert "Uses skills" not in by_company["A"]["match_reason"]
    assert "C" not in by_company, "no-hit job is dropped, not labelled as a match"


def test_provider_statuses_distinguish_ok_failed_skipped(monkeypatch, sync_build):
    _reset_feed()
    monkeypatch.setenv("JSEARCH_API_KEY", "rapid-key")
    for var in ("RAPIDAPI_KEY", "ADZUNA_APP_ID", "ADZUNA_APP_KEY",
                "JOOBLE_API_KEY", "USAJOBS_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    def fake_get(url, **kwargs):
        if "jsearch" in str(url):
            return _Resp({"data": {"jobs": [{
                "job_title": "Junior Data Analyst",
                "employer_name": "DataCorp",
                "job_apply_link": "https://apply.example.test/j1",
                "job_is_remote": True,
                "job_employment_types": ["FULLTIME"],
                "job_employment_type": "",
                "job_publisher": "GulfTalent",
                "job_posted_at_datetime_utc": "2026-08-21T10:00:00.000Z",
                "job_city": "Cairo", "job_state": "", "job_country": "Egypt",
                "job_description": "Use Excel dashboards and SQL daily.",
            }]}})
        raise OSError("down")

    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    data = sync_build(role="Data Analyst", country="United States")
    assert data["source"] == "live"
    assert _provider(data, "JSearch").get("status") == "ok"
    assert _provider(data, "Adzuna").get("status") == "skipped"
    assert _provider(data, "Adzuna").get("reason") == "no_credentials"
    assert _provider(data, "USAJobs").get("status") == "skipped"
    assert _provider(data, "Remotive").get("status") == "failed"
    assert _provider(data, "RemoteOK").get("status") == "failed"


def test_failed_provider_error_is_truncated_and_redacted(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "SECRET_AID_1")
    monkeypatch.setenv("ADZUNA_APP_KEY", "SECRET_AKEY_2")

    def boom(*a, **k):
        raise httpx.ConnectError(
            "https://api.adzuna.com/v1/api/jobs/gb/search/1?app_id=SECRET_AID_1"
            "&app_key=SECRET_AKEY_2 - connection refused")

    monkeypatch.setattr(jobs.httpx, "get", boom)
    assert jobs._fetch_adzuna(5, ["data"], "United Kingdom") == []
    st = jobs._provider_status["Adzuna"]
    assert st["status"] == "failed"
    assert st["reason"] == "request_failed"
    assert "SECRET_AID_1" not in st["error"]
    assert "SECRET_AKEY_2" not in st["error"]
    assert len(st["error"]) <= 120