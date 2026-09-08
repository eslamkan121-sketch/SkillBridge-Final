from app import jobs


def _reset_jobs_cache():
    jobs._cache.update({"at": 0.0, "key": "", "data": None})


def test_city_country_hint_does_not_treat_remote_as_country():
    assert jobs._city_country_hint("Cairo, EG") == ("cairo", "Egypt")
    assert jobs._city_country_hint("Remote") == ("remote", "")
    assert jobs._normalise_country("UAE") == "United Arab Emirates"


def test_recent_jobs_ranks_local_before_global_remote(monkeypatch):
    _reset_jobs_cache()
    raw = [
        {
            "title": "Data Analyst (Entry)",
            "company": "Cairo Analytics",
            "url": "https://example.test/cairo",
            "location": "Cairo, Egypt",
            "tags": ["SQL", "Data"],
            "source": "TestFeed",
        },
        {
            "title": "Data Analyst (Entry)",
            "company": "Remote Analytics",
            "url": "https://example.test/remote",
            "location": "Remote",
            "tags": ["SQL", "Data"],
            "source": "TestFeed",
        },
        {
            "title": "Data Analyst (Entry)",
            "company": "London Analytics",
            "url": "https://example.test/london",
            "location": "London, United Kingdom",
            "tags": ["SQL", "Data"],
            "source": "TestFeed",
        },
    ]

    monkeypatch.setattr(jobs, "_fetch_all", lambda *a, **k: raw)
    data = jobs.recent_jobs(
        skills=[("SQL", "Beginner"), ("Data Analysis", "Beginner")],
        role="Data Analyst",
        country="Egypt",
        location="Cairo",
        limit=3,
        _sync=True,
    )

    assert data["jobs"][0]["company"] == "Cairo Analytics"
    assert data["jobs"][0]["location_tier"] == "city"
    assert data["jobs"][1]["location_tier"] == "global_remote"
    assert data["jobs"][2]["location_tier"] == "different"
    assert data["groups"] == {"local_count": 1, "broader_count": 1, "other_count": 1}


def test_country_specific_remote_is_local(monkeypatch):
    _reset_jobs_cache()
    raw = [{
        "title": "Junior Python Developer",
        "company": "Remote Cairo Team",
        "url": "https://example.test/egypt-remote",
        "location": "Remote - Egypt",
        "tags": ["Python", "Developer"],
        "source": "TestFeed",
    }]

    monkeypatch.setattr(jobs, "_fetch_all", lambda *a, **k: raw)
    data = jobs.recent_jobs(
        skills=[("Python", "Beginner")],
        role="Python Developer",
        country="Egypt",
        location="Cairo",
        limit=1,
        _sync=True,
    )

    assert data["jobs"][0]["location_tier"] == "country_remote"
    assert data["jobs"][0]["location_label"] == "Remote - Egypt"
    assert data["groups"]["local_count"] == 1


def test_fallback_jobs_removed_all_providers_down_is_unavailable(monkeypatch):
    _reset_jobs_cache()
    monkeypatch.setattr(jobs, "_fetch_all", lambda *a, **k: [])

    data = jobs.recent_jobs(
        skills=[("SQL", "Beginner"), ("Data Analysis", "Beginner")],
        role="Data Analyst",
        country="Egypt",
        location="Cairo",
        limit=5,
        _sync=True,
    )

    # No provider data and no recorded success — honest unavailable + zero jobs,
    # never a curated/demo fallback.
    assert data["source"] == "unavailable"
    assert data["jobs"] == []
    assert data["groups"] == {"local_count": 0, "broader_count": 0, "other_count": 0}


def test_adzuna_missing_credentials_and_failures_are_noop(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    assert jobs._fetch_adzuna(5, ["python"], "Egypt") == []
    assert jobs._provider_status["Adzuna"]["status"] == "skipped"
    assert jobs._provider_status["Adzuna"]["reason"] == "no_credentials"

    def fail_get(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setenv("ADZUNA_APP_ID", "app")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    monkeypatch.setattr(jobs.httpx, "get", fail_get)
    assert jobs._fetch_adzuna(5, ["python"], "United Kingdom") == []
    assert jobs._provider_status["Adzuna"]["status"] == "failed"


def test_adzuna_unsupported_country_is_skipped_not_remapped(monkeypatch):
    """Egypt has no Adzuna endpoint; it must be skipped (unsupported_country),
    never silently remapped to gb (the old behavior 404'd on every request)."""
    _reset_jobs_cache()
    monkeypatch.setenv("ADZUNA_APP_ID", "test-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "test-key")
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [{
                "title": "Junior Data Analyst",
                "redirect_url": "https://example.test/adzuna",
                "created": "2026-08-20",
                "location": {"display_name": "London, United Kingdom"},
                "company": {"display_name": "Acme Analytics"},
                "category": {"label": "Data"},
            }]}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["params"] = kwargs.get("params") or {}
        return Response()

    monkeypatch.setattr(jobs, "_fetch_remotive", lambda *a, **k: [])
    monkeypatch.setattr(jobs, "_fetch_remoteok", lambda *a, **k: [])
    monkeypatch.setattr(jobs, "_fetch_jobicy", lambda *a, **k: [])
    monkeypatch.setattr(jobs, "_fetch_arbeitnow", lambda *a, **k: [])
    monkeypatch.setattr(jobs, "_fetch_jooble", lambda *a, **k: [])
    monkeypatch.setattr(jobs, "_fetch_usajobs", lambda *a, **k: [])
    monkeypatch.setattr(jobs, "_fetch_jsearch", lambda *a, **k: [])
    monkeypatch.setattr(jobs.httpx, "get", fake_get)

    data = jobs.recent_jobs(
        skills=[("SQL", "Beginner"), ("Data Analysis", "Beginner")],
        role="Data Analyst",
        country="Egypt",
        location="Cairo",
        limit=5,
        _sync=True,
    )

    # Egypt is unsupported: Adzuna reports skipped / unsupported_country and no
    # gb URL was ever hit.
    assert "url" not in captured or "adzuna" not in str(captured.get("url", ""))
    assert jobs._provider_status["Adzuna"]["status"] == "skipped"
    assert jobs._provider_status["Adzuna"]["reason"] == "unsupported_country"
    assert "Adzuna" not in {j["source"] for j in data["jobs"]}


def test_adzuna_explicit_uk_market_uses_gb_endpoint(monkeypatch):
    """gb is only used when the requested country really is the UK (or a UK
    market search is explicitly requested), never fabricated for Egypt."""
    _reset_jobs_cache()
    monkeypatch.setenv("ADZUNA_APP_ID", "test-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "test-key")
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [{
                "title": "Junior Data Analyst",
                "redirect_url": "https://example.test/adzuna",
                "created": "2026-08-20",
                "location": {"display_name": "London, United Kingdom"},
                "company": {"display_name": "Acme Analytics"},
                "category": {"label": "Data"},
            }]}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["params"] = kwargs.get("params") or {}
        return Response()

    monkeypatch.setattr(jobs, "_fetch_remotive", lambda *a, **k: [])
    monkeypatch.setattr(jobs, "_fetch_remoteok", lambda *a, **k: [])
    monkeypatch.setattr(jobs, "_fetch_jobicy", lambda *a, **k: [])
    monkeypatch.setattr(jobs, "_fetch_arbeitnow", lambda *a, **k: [])
    monkeypatch.setattr(jobs, "_fetch_jooble", lambda *a, **k: [])
    monkeypatch.setattr(jobs, "_fetch_usajobs", lambda *a, **k: [])
    monkeypatch.setattr(jobs, "_fetch_jsearch", lambda *a, **k: [])
    monkeypatch.setattr(jobs.httpx, "get", fake_get)

    data = jobs.recent_jobs(
        skills=[("SQL", "Beginner"), ("Data Analysis", "Beginner")],
        role="Data Analyst",
        country="Egypt",
        location="Cairo",
        limit=5,
        _sync=True,
        market_country="United Kingdom",
    )

    assert captured["url"].startswith("https://api.adzuna.com/v1/api/jobs/gb/search/1")
    assert captured["params"]["app_id"] == "test-id"
    assert data["source"] == "live"
    assert data["jobs"][0]["source"] == "Adzuna"
    adzuna = jobs._provider_status["Adzuna"]
    assert adzuna["status"] == "ok"


def test_existing_job_providers_still_work_when_adzuna_fails(monkeypatch):
    _reset_jobs_cache()
    monkeypatch.setenv("ADZUNA_APP_ID", "test-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "test-key")

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, **kwargs):
        url_text = str(url)
        if "adzuna.com" in url_text:
            raise RuntimeError("adzuna down")
        if url_text == jobs.REMOTIVE_URL:
            return Response({"jobs": [{
                "title": "Data Analyst (Entry)",
                "company_name": "Remote Data Co",
                "url": "https://example.test/remotive",
                "publication_date": "2026-08-21",
                "candidate_required_location": "Remote",
                "tags": ["SQL", "Data"],
            }]})
        return Response([{
            "position": "Junior Data Analyst",
            "company": "RemoteOK Data",
            "url": "https://example.test/remoteok",
            "date": "2026-08-22",
            "location": "Remote",
            "tags": ["SQL"],
        }])

    monkeypatch.setattr(jobs.httpx, "get", fake_get)

    data = jobs.recent_jobs(
        skills=[("SQL", "Beginner")],
        role="Data Analyst",
        country="Egypt",
        location="Cairo",
        limit=2,
        _sync=True,
    )

    assert data["source"] == "live"
    assert {item["source"] for item in data["jobs"]} == {"RemoteOK", "Remotive"}


class _Resp:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_jobicy_and_arbeitnow_hydrate_jobs(monkeypatch):
    def fake_get(url, **kwargs):
        if "jobicy.com" in str(url):
            return _Resp({"jobs": [{
                "jobTitle": "Junior Data Analyst", "companyName": "Acme Data",
                "url": "https://jobicy.com/jobs/1", "pubDate": "2026-09-02T10:00:00+00:00",
                "jobGeo": "Remote", "jobIndustry": ["Analytics"], "jobType": ["Full-Time"],
                "jobLevel": "Junior", "jobExcerpt": "…", "id": 1,
            }]})
        return _Resp({"data": [{
            "title": "Data Engineer (Junior)", "company_name": "Glow ATS",
            "url": "https://www.arbeitnow.com/jobs/glow/1", "location": "Berlin",
            "remote": False, "tags": ["Golang"], "job_types": ["Full-time"], "created_at": 1788630907,
        }]})

    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    assert jobs._fetch_jobicy(5)[0]["source"] == "Jobicy"
    assert jobs._fetch_jobicy(5)[0]["title"] == "Junior Data Analyst"
    job = jobs._fetch_arbeitnow(5)[0]
    assert job["source"] == "Arbeitnow"
    assert job["date"] == 1788630907
    assert job["location"] == "Berlin"


def test_jobicy_arbeitnow_noop_on_malformed_payload(monkeypatch):
    monkeypatch.setattr(jobs.httpx, "get", lambda *a, **k: _Resp([{"not": "a dict"}]))
    assert jobs._fetch_jobicy(5) == []
    assert jobs._fetch_arbeitnow(5) == []


def test_jooble_missing_key_and_failures_are_noop(monkeypatch):
    monkeypatch.delenv("JOOBLE_API_KEY", raising=False)
    assert jobs._fetch_jooble(5, ["python"], "Egypt") == []

    def fail_post(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setenv("JOOBLE_API_KEY", "key")
    monkeypatch.setattr(jobs.httpx, "post", fail_post)
    assert jobs._fetch_jooble(5, ["python"], "Egypt") == []


def test_jooble_results_can_be_included(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["body"] = kwargs.get("json") or {}
        return _Resp({"totalCount": 1, "jobs": [{
            "title": "Junior Data Analyst", "company": "Jooble Co",
            "link": "https://jooble.org/job/1", "location": "Cairo",
            "snippet": "…", "salary": "EGP 20k", "source": "Wuzzuf-agg",
            "type": "Full-time", "pubdate": "2026-09-01",
        }]})

    monkeypatch.setenv("JOOBLE_API_KEY", "test-key")
    monkeypatch.setattr(jobs.httpx, "post", fake_post)
    out = jobs._fetch_jooble(5, ["data", "analyst"], "Egypt")
    assert captured["url"] == "https://api.jooble.org/api/test-key"
    assert captured["body"]["keywords"] == "data analyst"
    assert captured["body"]["location"] == "Egypt"
    assert out[0]["source"] == "Jooble"
    assert out[0]["company"] == "Jooble Co"


def test_usajobs_key_missing_or_non_us_is_noop(monkeypatch):
    monkeypatch.delenv("USAJOBS_API_KEY", raising=False)
    assert jobs._fetch_usajobs(5, ["data"], "United States") == []
    monkeypatch.setenv("USAJOBS_API_KEY", "secret-key")
    assert jobs._fetch_usajobs(5, ["data"], "Egypt") == []


def test_usajobs_results_can_be_included(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured["headers"] = kwargs.get("headers") or {}
        return _Resp({"SearchResult": {"SearchResultItems": [{
            "MatchedObjectDescriptor": {
                "PositionTitle": "Data Scientist",
                "OrganizationName": "Federal Agency",
                "PositionURI": "https://www.usajobs.gov/job/1",
                "PositionStartDate": "2026-09-01",
                "PositionLocation": [{"LocationName": "Washington, DC"}],
                "JobCategory": [{"Name": "Data Analysis"}],
            },
        }]}})

    monkeypatch.setenv("USAJOBS_API_KEY", "secret-key")
    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    out = jobs._fetch_usajobs(5, ["data"], "United States")
    assert captured["headers"]["Authorization-Key"] == "secret-key"
    assert out[0]["source"] == "USAJobs"
    assert out[0]["title"] == "Data Scientist"
    assert "Washington" in out[0]["location"]


def test_jsearch_v5_missing_key_is_noop(monkeypatch):
    monkeypatch.delenv("JSEARCH_API_KEY", raising=False)
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    assert jobs._fetch_jsearch(5, ["cybersecurity"]) == []


def test_jsearch_v5_result_normalisation(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = str(url)
        captured["params"] = kwargs.get("params") or {}
        # v5 response shape: data is a dict keyed by jobs/cursor.
        return _Resp({"parameters": {}, "data": {
            "cursor": "abc",
            "jobs": [{
                "job_title": "Cyber Security Incident Response Engineer",
                "employer_name": "Deloitte & Touche (M.E.)",
                "job_apply_link": "https://apply.example.test/v5",
                "job_google_link": "https://google.example.test/v5",
                "job_is_remote": True,
                "job_employment_types": ["FULLTIME"],
                "job_employment_type": "دوام كامل",
                "job_publisher": "GulfTalent",
                "job_posted_at_datetime_utc": "2026-08-21T10:00:00.000Z",
                "job_city": "Cairo",
                "job_state": "",
                "job_country": "Egypt",
            }],
        }})

    monkeypatch.setenv("JSEARCH_API_KEY", "rapid-key")
    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    out = jobs._fetch_jsearch(5, ["cybersecurity"], "Egypt")
    assert captured["params"]["country"] == "eg", captured["params"]
    assert captured["params"]["query"] == "cybersecurity"
    assert "location" not in captured["params"]
    assert out[0]["source"] == "JSearch"
    assert out[0]["title"] == "Cyber Security Incident Response Engineer"
    assert out[0]["company"] == "Deloitte & Touche (M.E.)"
    assert out[0]["url"] == "https://apply.example.test/v5"
    assert out[0]["remote"] is True
    assert out[0]["country"] == "Egypt"
    assert "Cairo" in out[0]["location"]
    assert out[0]["date"] == "2026-08-21"
    assert out[0]["tags"][0] == "Fulltime"
    assert out[0]["tags"][-1] == "GulfTalent"


def test_jsearch_v5_country_iso2_without_location_fallback(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured["params"] = kwargs.get("params") or {}
        return _Resp({"data": {"jobs": [], "cursor": ""}})

    monkeypatch.setenv("JSEARCH_API_KEY", "rapid-key")
    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    jobs._fetch_jsearch(5, ["security"], "Saudi Arabia")
    assert captured["params"]["country"] == "sa"
    assert "location" not in captured["params"]
    # a country with no ISO map falls back to the free-text location param
    jobs._fetch_jsearch(5, ["security"], "Atlantis")
    assert "country" not in captured["params"]
    assert captured["params"]["location"] == "Atlantis"


def test_jsearch_v5_legacy_list_data_still_parses(monkeypatch):
    def fake_get(url, **kwargs):
        return _Resp({"data": [{
            "job_title": "Junior SOC Analyst",
            "employer_name": "MSSP",
            "url": "https://example.test/legacy",
            "job_is_remote": False,
            "job_employment_type": "Full Time",
            "job_city": "Riyadh",
            "job_state": "",
            "job_country": "Saudi Arabia",
        }]})

    monkeypatch.setenv("JSEARCH_API_KEY", "rapid-key")
    monkeypatch.setattr(jobs.httpx, "get", fake_get)
    out = jobs._fetch_jsearch(5, ["soc"], "Saudi Arabia")
    assert out[0]["source"] == "JSearch"
    assert out[0]["title"] == "Junior SOC Analyst"
    assert "Riyadh" in out[0]["location"]


def test_jsearch_v5_malformed_payload_is_noop(monkeypatch):
    monkeypatch.setenv("JSEARCH_API_KEY", "rapid-key")
    monkeypatch.setattr(jobs.httpx, "get", lambda *a, **k: _Resp({"data": None}))
    assert jobs._fetch_jsearch(5, ["security"]) == []

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(jobs.httpx, "get", boom)
    assert jobs._fetch_jsearch(5, ["security"]) == []


# --------------------------------------------------------------------------- endpoint guard
# Students may only search the role feed AFTER uploading a CV (skills exist).
# Without skills we return source="no-cv" with no fetch; Companies keep their
# general market feed; Students WITH a skill profile fetch normally.


def test_student_without_skills_gets_no_cv_and_never_fetches(client, auth_headers, student_id, monkeypatch):
    from app import main, models

    models.replace_self_reported_skills(student_id, [])

    called = []
    monkeypatch.setattr(main.jobs, "recent_jobs", lambda **kw: called.append(kw) or {"source": "live", "jobs": []})
    r = client.get("/api/jobs/recent", headers=auth_headers("aisha@student.edu"))
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "no-cv"
    assert body["jobs"] == []
    assert called == [], "job fetch must not run before a student has uploaded a CV"


def test_student_with_skills_fetches_matched_jobs(client, auth_headers, student_id, monkeypatch):
    from app import main, models

    assert models.get_student(student_id)["self_reported_skills"], "seed should give skills"

    called = {}
    monkeypatch.setattr(main.jobs, "recent_jobs", lambda **kw: called.update(kw) or {"source": "live", "jobs": []})
    r = client.get("/api/jobs/recent", headers=auth_headers("aisha@student.edu"))
    assert r.status_code == 200
    assert r.json()["source"] == "live"
    assert called["skills"], "matched search should run once CV skills exist"


def test_company_still_gets_general_market_feed(client, auth_headers, monkeypatch):
    from app import main

    called = {}
    monkeypatch.setattr(main.jobs, "recent_jobs", lambda **kw: called.update(kw) or {"source": "live", "jobs": []})
    r = client.get("/api/jobs/recent", headers=auth_headers("hr@northstar.com"))
    assert r.status_code == 200
    assert r.json()["source"] == "live"
    assert called.get("skills") in ((), []), "companies see the general feed, not a CV-gated one"


# --------------------------------------------------------------------------- P2 role-driven relevance
# Generalized (not tuned to one CV): skills are clustered into a role-relevant
# primary set vs an incidental minor set using the target role's own vocabulary
# (title + required skills). Only role-relevant signals qualify a job when a
# target career is set; incidental skills (excel, java, ML, communication… on a
# cybersecurity profile) are capped tie-breakers that never surface off-target
# jobs above genuinely relevant ones. Same mechanism for any career.

_CYBER_SKILLS = [
    ("Cybersecurity", "Advanced"), ("Incident Response", "Intermediate"),
    ("SIEM", "Intermediate"), ("Network Security", "Intermediate"),
    ("Threat Detection", "Advanced"), ("Vulnerability Management", "Beginner"),
    ("Excel", "Intermediate"), ("Java", "Beginner"), ("Machine Learning", "Intermediate"),
    ("Communication", "Advanced"), ("NLP", "Beginner"), ("Data Analysis", "Intermediate"),
]
_CYBER_REQS = ["Active Directory", "Cybersecurity", "Incident Response", "Linux",
               "Network Security", "Risk Assessment", "SIEM", "Threat Detection",
               "Vulnerability Management", "Windows Server"]


def test_role_driven_clustering_keeps_noise_out_of_primary():
    primary, minor = jobs._cluster_keywords([s[0] for s in _CYBER_SKILLS], "Cybersecurity Analyst", _CYBER_REQS)
    assert "cybersecurity" in primary and "analyst" in primary
    for noise in ("excel", "java", "machine", "communication", "nlp"):
        assert noise not in primary
        assert noise in minor
    # ...yet they are still available as capped tie-breakers.
    assert "excel" in minor and "java" in minor


def test_role_driven_scoring_drops_off_target_jobs():
    raw = [
        {"title": "Freelance Copywriter", "company": "Copy Co", "url": "c1", "location": "Remote",
         "tags": ["accounting", "excel", "research"], "source": "T"},
        {"title": "Remote Office Assistant", "company": "Admin Co", "url": "c2", "location": "Remote",
         "tags": ["css", "excel", "frontend"], "source": "T"},
        {"title": "Security Analyst (SOC)", "company": "SOC Team", "url": "c3", "location": "Remote",
         "tags": ["SIEM", "incident response"], "source": "T"},
        {"title": "Cybersecurity Analyst", "company": "Defense Co", "url": "c4", "location": "Remote",
         "tags": ["threat detection"], "source": "T"},
        {"title": "Incident Response Analyst", "company": "IR Team", "url": "c5", "location": "Remote",
         "tags": ["security"], "source": "T"},
    ]
    primary, minor = jobs._cluster_keywords([s[0] for s in _CYBER_SKILLS], "Cybersecurity Analyst", _CYBER_REQS)
    ranked = jobs._apply(raw, primary, jobs._student_seniority([s[1] for s in _CYBER_SKILLS]),
                         "Egypt", "", jobs._role_family("Cybersecurity Analyst"),
                         minor_keywords=minor, role_driven=True,
                         role_title="Cybersecurity Analyst")

    companies = [j["company"] for j in ranked]
    assert "Copy Co" not in companies, "copywriter must not rank for a cybersecurity target"
    assert "Admin Co" not in companies
    # Target-role title dominance: exact title match first, then close
    # (Incident Response Analyst), then the broader-field Security Analyst role.
    assert companies[:3] == ["Defense Co", "IR Team", "SOC Team"]
    assert all(j["match_pct"] >= 78 for j in ranked), "role-relevant remote roles should rank high"


def test_role_driven_relevance_generalizes_to_marketing_and_data():
    # Marketing profile: copywriter job tagged only "marketing" needs a second
    # role signal to qualify; a Java developer role must never rank.
    mk_skills = [("Digital Marketing", "Advanced"), ("SEO", "Intermediate"),
                 ("Copywriting", "Intermediate"), ("Java", "Beginner"), ("Data Analysis", "Intermediate")]
    mk_reqs = ["Digital Marketing", "Search Engine Optimization", "Social Media Marketing"]
    primary, minor = jobs._cluster_keywords([s[0] for s in mk_skills], "Marketing Specialist", mk_reqs)
    assert "marketing" in primary
    assert "java" in minor
    raw = [
        {"title": "Java Developer", "company": "Dev Shop", "url": "m1", "location": "Remote",
         "tags": ["java", "backend"], "source": "T"},
        {"title": "Freelance Copywriter", "company": "Copy Co", "url": "m2", "location": "Remote",
         "tags": ["marketing"], "source": "T"},
        {"title": "Digital Marketing Specialist", "company": "Grow Co", "url": "m3", "location": "Remote",
         "tags": ["seo"], "source": "T"},
    ]
    ranked = jobs._apply(raw, primary, jobs._student_seniority([s[1] for s in mk_skills]),
                         "Egypt", "", jobs._role_family("Marketing Specialist"),
                         minor_keywords=minor, role_driven=True)
    assert [j["company"] for j in ranked] == ["Grow Co"]


def test_no_target_role_keeps_legacy_full_skill_search():
    # Without a target career everything is primary and matches the pre-P2
    # behaviour: multi-skill signals qualify, a lone tag hit is still unreliable.
    primary, minor = jobs._cluster_keywords(["Excel", "Data Analysis"], "", ())
    assert primary == ["excel", "analysis", "data"]
    assert minor == []
    ranked = jobs._apply(
        [
            {"title": "Spreadsheet Specialist", "company": "Sheet Co", "url": "s1", "location": "Remote",
             "tags": ["excel"], "source": "T"},
            {"title": "Excel Data Analyst", "company": "Sheet Data Co", "url": "s2", "location": "Remote",
             "tags": ["excel", "data"], "source": "T"},
        ],
        primary, 1, "Egypt", "", "",
        minor_keywords=minor, role_driven=False)
    assert [j["company"] for j in ranked] == ["Sheet Data Co"]


def test_relocation_market_ranked_with_local_not_as_own_country(monkeypatch):
    _reset_jobs_cache()
    raw = [
        {"title": "Security Analyst", "company": "Cairo Sec", "url": "l1", "location": "Cairo, Egypt",
         "tags": ["security", "SIEM"], "source": "T"},
        {"title": "Security Analyst", "company": "London Sec", "url": "l2", "location": "London, United Kingdom",
         "tags": ["security", "SIEM"], "source": "T"},
        {"title": "Security Analyst", "company": "Tokyo Sec", "url": "l3", "location": "Tokyo, Japan",
         "tags": ["security", "SIEM"], "source": "T"},
    ]
    monkeypatch.setattr(jobs, "_fetch_all", lambda *a, **k: raw)
    data = jobs.recent_jobs(
        skills=[("Cybersecurity", "Advanced")],
        role="Security Analyst",
        country="Egypt",
        location="Cairo",
        limit=3,
        _sync=True,
        role_requisites=["SIEM"],
        market_country="gb",
    )

    tiers = [j["location_tier"] for j in data["jobs"]]
    assert tiers == ["city", "market", "different"], tiers
    london = data["jobs"][1]
    assert "Relocation search" in london["location_label"]
    assert london["location_label"].startswith("Relocation search ·")
    assert london["company"] == "London Sec"


def test_relocation_market_forwards_adzuna_country(monkeypatch):
    _reset_jobs_cache()
    captured = {}

    def fake_fetch_all(limit_each, keywords=(), country="", adzuna_country=""):
        captured.update(keywords=list(keywords), adzuna_country=adzuna_country)
        return []

    monkeypatch.setattr(jobs, "_fetch_all", fake_fetch_all)
    jobs.recent_jobs(
        skills=[("Cybersecurity", "Advanced")],
        role="Security Analyst",
        country="Egypt",
        location="Cairo",
        limit=5,
        _sync=True,
        market_country="gb",
    )
    assert captured["adzuna_country"] == "gb"
    # Lead term is the role title's own vocabulary, not alphabetical noise.
    assert captured["keywords"][0] in ("security", "analyst")
