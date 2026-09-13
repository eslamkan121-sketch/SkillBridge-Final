"""Phase J — explainable role and job matching (guide lines 506-533).

Deterministic, fully offline. Target-role and role-match breakdowns run against
the seeded in-memory DB (the ``db`` conftest fixture) with the ESCO gateway
mocked via ``escoe.market_occupations_for_skills``; job-match breakdowns run
against deterministic normalized listings through a mocked ``jobs._fetch_all``.
No live provider is ever called and no real quota is ever spent.

Everything here locks the exact-total invariant: the components + labelled
adjustment lines a breakdown returns sum EXACTLY to the number the app already
displays, and a recomputation that disagrees is REFUSED (MatchExplainError 500)
instead of changing the displayed score. Honesty rules locked: verified >
self-reported evidence, missing data stays unknown/none (never 0/false),
self-reported evidence is never labelled verified, and job matches are only
keyword-level evidence.
"""
import datetime
import re

import pytest

from app import escoe, jobs, match_explain, matching, models, recommendations, role_intent


def _iso(date=None):
    return (date or datetime.date.today()).isoformat()


_CATALOG_OCC = {
    "uri": "http://data.europa.eu/esco/occupation/test-ml-engineer",
    "title": "Machine Learning Technician",
    "code": "2512.3",
    "description": "Builds and deploys ML systems.",
    "score": 0.9,
    "skills": ["Python", "Machine Learning", "Docker", "Cloud Platforms"],
    "essential": ["Python", "Machine Learning"],
    "optional": ["Docker", "Cloud Platforms"],
    # Discovery skills must NOT be the occupation's own required skills
    # (those are matched in the req loop); aisha's Git/SQL are exactly the
    # profile skills that give this occupation discovery-only credits.
    "discovery_skills": ["Git", "SQL"],
}


# ---------------------------------------------------------------------------
# shared job-feed harness (mock provider, deterministic listings)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fresh_job_state():
    jobs.clear_job_cache()
    jobs._bg_fetching.clear()
    jobs._PROVIDER_COOLDOWN.clear()
    for p in jobs.PROVIDERS:
        jobs._provider_status[p] = {"status": "skipped", "count": 0,
                                    "reason": "", "error": ""}
    jobs._stats.update({"cache_hits": 0, "cache_misses": 0,
                        "last_success_provider": "", "last_error_by_provider": {},
                        "fetch_times": []})
    yield
    jobs.clear_job_cache()


@pytest.fixture()
def feed(monkeypatch):
    """Mock jobs._fetch_all so builds are deterministic; ``feed.jobs`` holds the
    raw listings the next build serves, and ``feed.calls`` counts fetch runs."""
    holder = {"jobs": [], "calls": 0}

    def fake_fetch(limit_each, keywords=(), country="", adzuna_country="", report=None):
        holder["calls"] += 1
        if report is not None:
            report.update({"Remotive": {"status": "ok",
                                        "count": len(holder["jobs"]),
                                        "reason": "", "error": ""}})
        return list(holder["jobs"])

    monkeypatch.setattr(jobs, "_fetch_all", fake_fetch)
    return holder


def _data_student(**overrides):
    """Deterministic fake student whose target-role data pipeline mirrors the
    real seeded profile: SQL self-reported intermediate, Python verified
    advanced, target Data Analyst."""
    base = {
        "id": 999,
        "location": "Cairo",
        "country": "Egypt",
        "target_role_id": 900,
        "target_role": {"id": 900, "title": "Data Analyst", "source_version": None,
                        "required_skills": [{"name": "SQL"}, {"name": "Python"}]},
        "self_reported_skills": [{"skill_id": 1, "name": "SQL",
                                  "level": "Intermediate", "source": "self",
                                  "evidence": None}],
        "verified_skills": [{"skill_id": 2, "name": "Python",
                             "level": "Advanced", "source": "verified",
                             "verified_at": "2026-01-01"}],
    }
    base.update(overrides)
    return base


def _listing(**overrides):
    title = overrides.get("title", "Data Analyst")
    company = overrides.get("company", "Acme Analytics")
    slug = re.sub(r"[^a-z0-9]+", "-", f"{title}-{company}".lower()).strip("-")
    base = {
        "title": title, "company": company,
        "url": f"https://example.test/jobs/{slug}",
        "location": "Cairo, Egypt",
        "tags": ["SQL", "Excel"], "source": "Remotive",
        "date": _iso(), "description": "Analyse business data with SQL and Excel.",
    }
    base.update(overrides)
    return base


def _warm_feed(student, location="Cairo", country="Egypt", market=""):
    """Warm the feed cache under the exact key the breakdown will rebuild and
    return (data, skills, role, requisites)."""
    skills, role, reqs = match_explain._student_feed_inputs(student)
    data = jobs.recent_jobs(skills=skills, role=role, country=country,
                            location=location, role_requisites=reqs,
                            market_country=market, limit=10, _sync=True)
    assert data["status"] == "fresh"
    return data, skills, role, reqs


def _first_job(data):
    assert data["jobs"], "expected the fixture listing to be surfaced"
    return data["jobs"][0]


def _breakdown(student, fingerprint, location="Cairo", country="Egypt", market=""):
    return match_explain.job_match_breakdown(
        student, fingerprint, location=location, country=country, market=market)


# ---------------------------------------------------------------------------
# exact-total, evidence, and honesty at the unit level
# ---------------------------------------------------------------------------

def test_role_adjustment_lines_round_and_cap_math():
    lines = match_explain._role_adjustment_lines(87.33, 87.3)
    assert [l["label"] for l in lines] == ["rounding"]
    assert sum(l["points"] for l in lines) == pytest.approx(87.3 - 87.33, abs=0.011)

    capped = match_explain._role_adjustment_lines(120.0, 100.0)
    assert [l["label"] for l in capped] == ["cap_at_100", "rounding"]
    assert capped[0]["points"] == pytest.approx(-20.0, abs=0.011)


def test_role_match_exact_total_from_crafted_discovery():
    """Concrete _score_candidate drill: a discovery credit added to earned but
    NOT to the denominator; the percent formula is round(min(100, e/t*100),1)."""
    weights = {"python": 1.5, "ml": 1.2, "docker": 0.9}
    spec = lambda code: weights[code]
    cand = {
        "req": [
            {"key": "python", "name": "Python", "essential": True,
             "required_level": 2},
            {"key": "ml", "name": "Machine Learning", "essential": True,
             "required_level": 2},
        ],
        "discovery": {"docker": "Docker"},
    }
    profile = {"python": {"label": "Advanced", "level": 3, "verified": True},
               "ml": {"label": "Intermediate", "level": 2, "verified": False},
               "docker": {"label": "Beginner", "level": 1, "verified": False}}
    pct, matched, missing, detail = recommendations._score_candidate(cand, profile, spec)
    total_w = 1.5 + 1.2
    earned = 1.5 * 1.05 + 1.0 * 1.2 + 0.9
    assert pct == round(min(100.0, earned / total_w * 100.0), 1)
    assert [d["name"] for d in detail if d["is_discovery"]] == ["Docker"]
    non_disc = [d for d in detail if not d["is_discovery"]]
    assert sum(d["weight"] for d in non_disc) == pytest.approx(total_w)
    assert sum(d["credit"] for d in detail) == pytest.approx(earned)
    assert matched and not missing
    by_name = {d["name"]: d for d in detail}
    assert by_name["Python"]["evidence"] == "verified"
    assert by_name["Machine Learning"]["evidence"] == "self_reported"


def test_target_role_precedence_and_exact_total_verified_over_reported():
    student = {
        "self_reported_skills": [{"skill_id": 7, "name": "SQL",
                                  "level": "Beginner", "source": "self",
                                  "evidence": None}],
        "verified_skills": [{"skill_id": 7, "name": "SQL",
                             "level": "Advanced", "source": "verified",
                             "verified_at": "2026-01-01"}],
        "target_role": {"id": 77, "title": "Data Analyst",
                        "required_skills": [
                            {"skill_id": 7, "name": "SQL",
                             "required_level": "Intermediate"},
                            {"skill_id": 8, "name": "Excel",
                             "required_level": "Advanced"}]},
        "target_role_id": 77,
    }
    b = match_explain.target_role_match_breakdown(student)
    assert b["displayed_percent"] == matching.job_match_score(student, student["target_role"]) == 50.0
    assert b["raw_percent"] == 50.0
    assert b["role_data_version"] == "local"
    assert b["requirements"][0]["evidence"] == "verified"
    assert b["requirements"][0]["student_level"] == "Advanced"
    assert b["requirements"][0]["contribution_points"] == 1.0
    assert b["requirements"][1]["evidence"] == "none"
    assert b["requirements"][1]["student_level"] is None
    assert b["requirements"][1]["contribution_points"] == 0.0
    assert b["missing_data"] == ["Excel"]
    assert "Excel" in b["next_action"]
    assert sum(d["contribution_points"] for d in b["requirements"]) == 1.0
    assert b["adjustment_lines"][0]["label"] == "rounding"
    assert b["adjustment_lines"][0]["points"] == 0.0
    assert b["formula"] == match_explain.TARGET_ROLE_MATCH_FORMULA
    assert b["version"] == match_explain.TARGET_ROLE_MATCH_VERSION


def test_target_role_gap_and_partial_credit_accounting():
    student = {
        "self_reported_skills": [{"skill_id": 9, "name": "Linux",
                                  "level": "Beginner", "source": "self",
                                  "evidence": None}],
        "verified_skills": [],
        "target_role": {"id": 78, "title": "Security Analyst",
                        "source_version": "esco:v1.2.0",
                        "required_skills": [
                            {"skill_id": 9, "name": "Linux",
                             "required_level": "Intermediate"}]},
        "target_role_id": 78,
    }
    b = match_explain.target_role_match_breakdown(student)
    assert b["role_data_version"] == "esco:v1.2.0"
    assert b["requirements"][0]["status"] == "gap"
    assert b["requirements"][0]["evidence"] == "self_reported"
    assert b["requirements"][0]["contribution_points"] == pytest.approx(0.5)
    assert b["displayed_percent"] == matching.job_match_score(student, student["target_role"])


def test_target_role_missing_target_is_honest_404():
    with pytest.raises(match_explain.MatchExplainError) as ei:
        match_explain.target_role_match_breakdown({"id": 1})
    assert ei.value.status_code == 404
    with pytest.raises(match_explain.MatchExplainError) as ei:
        match_explain.target_role_match_breakdown({
            "id": 1,
            "target_role": {"id": 9, "title": "X", "required_skills": []}})
    assert ei.value.status_code == 404
    assert "no required skills" in ei.value.message.lower()


# ---------------------------------------------------------------------------
# role-match breakdown (seeded DB, ESCO gateway offline)
# ---------------------------------------------------------------------------

def _seeded_student(db, email):
    user = models.get_user_by_email(email)
    assert user, email
    return models.get_student_by_user(user["id"])


@pytest.fixture()
def _offline_esco(monkeypatch):
    monkeypatch.setattr(escoe, "market_occupations_for_skills",
                        lambda skill_names, limit=8, **kwargs: [])
    monkeypatch.setattr(escoe, "occupation_skill_groups",
                        lambda uri: {"essential": [], "optional": []})


def _role_recommendations(student):
    return recommendations.recommend(student, _include_detail=True)


def test_role_match_exact_total_catalog_and_company(db, _offline_esco):
    student = _seeded_student(db, "aisha@student.edu")
    bundle = _role_recommendations(student)
    recs = bundle["recommendations"]
    assert recs, "seeded profile must produce recommendations (offline ESCO)"
    sources = {r["source"] for r in recs}
    seen = set()
    for rec in recs:
        if rec.get("role_id") is None:
            continue
        b = match_explain.role_match_breakdown(student, str(rec["role_id"]))
        assert b["role_id"] == rec["role_id"]
        assert b["displayed_percent"] == rec["match_score"]
        non_disc = [r for r in b["requirements"] if not r["is_discovery"]]
        assert b["total_weight"] == pytest.approx(sum(r["weight"] for r in non_disc), abs=0.021)
        assert b["earned_weight"] == pytest.approx(sum(r["credit"] for r in b["requirements"]), abs=0.021)
        for line in b["adjustment_lines"]:
            assert line["label"] in ("rounding", "cap_at_100")
        assert b["version"] == match_explain.ROLE_MATCH_VERSION
        assert b["formula"] == match_explain.ROLE_MATCH_FORMULA
        assert b["role_data_version"] == (rec.get("source_version") or "local")
        for r in b["requirements"]:
            assert r["evidence"] in ("verified", "self_reported", "none")
            if r["evidence"] == "verified":
                assert r["verified"] is True
        seen.add(rec["source"])
        if len(seen) >= 2 and {"catalog", "company"} <= seen:
            break
    assert {"catalog", "company"} <= sources


def test_role_match_discovery_credit_denominator_rule(db, monkeypatch):
    """Lock the Phase J denominator bugfix end-to-end: an ESCO occupation's
    discovery credit adds to earned but never to total_weight, and the
    breakdown still sums exactly to the displayed ring."""
    monkeypatch.setattr(escoe, "market_occupations_for_skills",
                        lambda skill_names, limit=8, **kwargs: [_CATALOG_OCC])
    monkeypatch.setattr(escoe, "occupation_skill_groups",
                        lambda uri: {"essential": [], "optional": []})
    student = _seeded_student(db, "aisha@student.edu")
    bundle = _role_recommendations(student)
    occ = None
    for r in bundle["recommendations"]:
        if r.get("external_id") == _CATALOG_OCC["uri"]:
            occ = r
            break
    assert occ is not None, "expected the ESCO occupation in aisha's recommendations"
    b = match_explain.role_match_breakdown(student, occ["external_id"])
    assert b["external_id"] == _CATALOG_OCC["uri"]
    discovery = [r for r in b["requirements"] if r["is_discovery"]]
    assert {r["name"] for r in discovery} == {"Git", "SQL"}
    non_disc = [r for r in b["requirements"] if not r["is_discovery"]]
    assert b["total_weight"] == pytest.approx(sum(r["weight"] for r in non_disc), abs=0.021)
    assert b["earned_weight"] == pytest.approx(sum(r["credit"] for r in b["requirements"]), abs=0.021)
    for d in discovery:
        # level_factor 1.0; the verified boost accounts for verified discovery.
        # weight/credit are 2dp-rounded in the payload, so tolerance is per-row.
        assert d["credit"] == pytest.approx(d["weight"] * (1.05 if d["verified"] else 1.0), abs=0.011)
    assert b["title"] == occ["title"]


def test_role_match_missing_data_honest(db, _offline_esco):
    student = _seeded_student(db, "omar@student.edu")
    bundle = _role_recommendations(student)
    with_missing = [r for r in bundle["recommendations"] if r.get("missing_key_skills")]
    assert with_missing, "expected at least one recommendation with missing skills"
    rec = with_missing[0]
    b = match_explain.role_match_breakdown(student, str(rec["role_id"]))
    assert b["missing_key_skills"] == rec["missing_key_skills"]
    assert b["missing_data"] == rec["missing_key_skills"]
    missing_rows = [r for r in b["requirements"]
                    if r["student_level"] is None and r["credit"] == 0.0]
    assert missing_rows
    assert all(r["evidence"] == "none" for r in missing_rows)


def test_role_match_unknown_role_is_honest_404(db, _offline_esco):
    student = _seeded_student(db, "omar@student.edu")
    with pytest.raises(match_explain.MatchExplainError) as ei:
        match_explain.role_match_breakdown(student, "999999")
    assert ei.value.status_code == 404


def test_regression_golden_recommend_pct_chain(db, _offline_esco):
    """Regression anchor: for every candidate in several seeded students' lists,
    re-derive the displayed match_score from the per-requirement weights the
    scoring pipeline itself emitted. If the extracted weighted chain ever drifts
    from the displayed number, the anchor fails loudly."""
    for email in ("aisha@student.edu", "omar@student.edu", "leila@student.edu"):
        student = _seeded_student(db, email)
        bundle = _role_recommendations(student)
        assert bundle["recommendations"]
        for rec in bundle["recommendations"]:
            detail = rec.get("match_detail") or []
            assert detail, "match_detail must be attached when requested"
            total_w = sum((d.get("weight") or 0.0) for d in detail
                          if not d.get("is_discovery"))
            earned = sum((d.get("credit") or 0.0) for d in detail)
            expected = round(min(100.0, (earned / total_w if total_w else 0.0) * 100.0), 1)
            assert rec["match_score"] == expected, email + " " + rec["title"]


# ---------------------------------------------------------------------------
# job-match breakdown battery (deterministic feed)
# ---------------------------------------------------------------------------

def _assert_exact_total(b):
    c = b["components"]
    deltas = {l["label"]: l["points"] for l in b["lines"]}
    parts = (c["relevance"]["final"] + c["experience"]["points"]
             + c["location"]["points"]
             + deltas["rounding"] + deltas["clamp_0_100"]
             + deltas.get("seniority_cap", 0) + deltas.get("relocation_cap", 0))
    # The step lines (components + labelled adjustments) sum EXACTLY to the
    # displayed match_pct.
    assert parts == pytest.approx(b["displayed_percent"], abs=0.011)
    # Cap lines appear only when their arithmetic condition is actually true.
    if "seniority_cap" in deltas:
        assert c["experience"]["student_seniority"] == 0
        assert c["experience"]["job_seniority"] > 1
    else:
        assert not (c["experience"]["student_seniority"] == 0
                    and c["experience"]["job_seniority"] > 1)
    if "relocation_cap" in deltas:
        assert c["location"]["tier"] == "different"
    else:
        assert c["location"]["tier"] != "different"
    assert set(b["verified_skill_hits"]) <= set(b["matches"]["matched"])
    assert not (set(b["other_matched_keywords"]) & set(b["verified_skill_hits"]))
    assert b["formula"] == match_explain.JOB_MATCH_FORMULA
    assert b["version"] == match_explain.JOB_MATCH_VERSION


def test_job_exact_total_baseline(feed):
    feed["jobs"] = [_listing()]
    student = _data_student()
    data, *_ = _warm_feed(student)
    j = _first_job(data)
    b = _breakdown(student, j["fingerprint"])
    assert b["displayed_percent"] == j["match_pct"]
    _assert_exact_total(b)
    assert b["job"]["title"] == "Data Analyst"
    assert b["constraints"]["location"]["tier"] == "city"
    assert b["constraints"]["location"]["supported"] is True
    assert b["constraints"]["work_type"]["value"] == "unknown"
    assert b["constraints"]["work_type"]["supported"] is False
    assert b["role_data_version"] == "local"


def test_job_relocation_cap_different_market(feed):
    feed["jobs"] = [_listing(title="Data Analyst", location="London, UK",
                             company="UK Analytics")]
    student = _data_student()
    data, *_ = _warm_feed(student)
    j = _first_job(data)
    b = _breakdown(student, j["fingerprint"])
    assert b["constraints"]["location"]["tier"] == "different"
    assert b["constraints"]["location"]["supported"] is False
    labels = [l["label"] for l in b["lines"]]
    assert "relocation_cap" in labels
    _assert_exact_total(b)


def test_job_seniority_cap_for_beginner_student(feed):
    feed["jobs"] = [_listing(title="Senior Data Analyst", location="Cairo, Egypt")]
    student = _data_student(
        self_reported_skills=[{"skill_id": 1, "name": "SQL",
                               "level": "Beginner", "source": "self", "evidence": None}],
        verified_skills=[])
    data, *_ = _warm_feed(student)
    j = _first_job(data)
    b = _breakdown(student, j["fingerprint"])
    labels = [l["label"] for l in b["lines"]]
    assert "seniority_cap" in labels
    assert b["constraints"]["seniority"]["supported"] is False
    _assert_exact_total(b)


def test_job_unknown_location_stays_honest(feed):
    feed["jobs"] = [_listing(title="Data Analyst", location="")]
    student = _data_student()
    data, *_ = _warm_feed(student)
    assert data["jobs"], "unknown-location row should still surface (broader tier)"
    j = _first_job(data)
    b = _breakdown(student, j["fingerprint"])
    assert b["constraints"]["location"]["tier"] == "unknown"
    assert b["constraints"]["location"]["supported"] is True
    assert b["components"]["location"]["points"] == 0
    _assert_exact_total(b)


def test_job_verified_hits_are_evidence_level_only(feed):
    feed["jobs"] = [_listing(title="Data Analyst", tags=["SQL", "Python"],
                             description="Python, SQL, Excel and reporting.")]
    student = _data_student()
    data, *_ = _warm_feed(student)
    j = _first_job(data)
    b = _breakdown(student, j["fingerprint"])
    assert b["verified_skill_hits"], "python is verified and matched"
    assert all(k not in b["verified_skill_hits"]
               for k in b["other_matched_keywords"])
    assert "evidence-level claim" in b["evidence_note"]
    _assert_exact_total(b)


def test_job_family_tier_surfaces_and_explains(feed):
    feed["jobs"] = [_listing(title="Database Administrator", location="Cairo, Egypt")]
    student = _data_student()
    rel = role_intent.classify_title("Data Analyst", "Database Administrator")
    assert rel == "FAMILY"
    data, *_ = _warm_feed(student)
    assert data["jobs"], "family-tier role must survive the relevance gate"
    j = _first_job(data)
    b = _breakdown(student, j["fingerprint"])
    _assert_exact_total(b)


def test_job_unrelated_title_never_surfaces(feed):
    feed["jobs"] = [_listing(title="Barista", location="Cairo, Egypt",
                             tags=["Espresso"])]
    student = _data_student()
    data, *_ = _warm_feed(student)
    assert data["jobs"] == []
    with pytest.raises(match_explain.MatchExplainError) as ei:
        # A fingerprint never surfaced -> honest 404.
        match_explain.job_match_breakdown(student, "deadbeefdeadbeef")
    assert ei.value.status_code == 404


def test_job_battery_mixed_feed_all_rows_exact(feed):
    feed["jobs"] = [
        _listing(title="Data Analyst", location="Cairo, Egypt"),
        _listing(title="Junior Data Analyst", location="Cairo, Egypt",
                 company="B", tags=["SQL", "Python"]),
        _listing(title="Data Scientist", location="Cairo, Egypt",
                 company="C", tags=["Python", "Machine Learning"]),
        _listing(title="Data Analyst", location="London, UK", company="D",
                 tags=["SQL"]),
    ]
    student = _data_student()
    data, *_ = _warm_feed(student)
    assert len(data["jobs"]) == 4
    for j in data["jobs"]:
        b = _breakdown(student, j["fingerprint"])
        assert b["displayed_percent"] == j["match_pct"]
        _assert_exact_total(b)


def test_job_breakdown_readonly_and_deterministic(feed):
    feed["jobs"] = [_listing()]
    student = _data_student()
    data, *_ = _warm_feed(student)
    calls_after_warm = feed["calls"]
    j = _first_job(data)
    for _ in range(2):
        b = _breakdown(student, j["fingerprint"])
        assert b["displayed_percent"] == j["match_pct"]
# Cache stays warm -> no rebuild; the mirror must be read-only.
        assert feed["calls"] == calls_after_warm
        first = _breakdown(student, j["fingerprint"])
        second = _breakdown(student, j["fingerprint"])
        first.pop("as_of")
        second.pop("as_of")
        assert first == second


def test_job_breakdown_warms_cold_cache_and_404s_fresh(feed):
    feed["jobs"] = [_listing()]
    student = _data_student()
    data, *_ = _warm_feed(student)
    j = _first_job(data)
    jobs.clear_job_cache()
    before = feed["calls"]
    b = _breakdown(student, j["fingerprint"])
    assert feed["calls"] == before + 1, "cold cache must rebuild synchronously"
    _assert_exact_total(b)


def test_job_no_cv_profile_is_honest_404():
    student = _data_student(self_reported_skills=[])
    with pytest.raises(match_explain.MatchExplainError) as ei:
        match_explain.job_match_breakdown(student, "somefingerprint")
    assert ei.value.status_code == 404
    assert "no cv profile" in ei.value.message.lower()


# ---------------------------------------------------------------------------
# endpoints (auth, ownership, shapes)
# ---------------------------------------------------------------------------

def _login_token(client, email):
    r = client.post("/api/auth/login",
                    json={"email": email, "password": "demo1234"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth_h(token):
    return {"Authorization": f"Bearer {token}"}


def test_endpoint_target_role_breakdown(client, db, _offline_esco):
    payload = client.post("/api/auth/login",
                          json={"email": "aisha@student.edu", "password": "demo1234"}).json()
    token = payload["token"]
    aisha_id = payload["student"]["id"]
    r = client.get(f"/api/students/{aisha_id}/target-role-match/breakdown",
                   headers=_auth_h(token))
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["formula"] == match_explain.TARGET_ROLE_MATCH_FORMULA
    assert b["version"] == match_explain.TARGET_ROLE_MATCH_VERSION
    student = models.get_student(aisha_id)
    assert b["displayed_percent"] == matching.job_match_score(student, student["target_role"])
    # per-row contribution is the level ratio (0..1); totals are the counts.
    contributions = sum(d["contribution_points"] for d in b["requirements"])
    total = b["total_points"]
    assert total == len(b["requirements"])
    assert contributions <= total
    expected_raw = round(contributions / total * 100.0, 1)
    assert abs(b["displayed_percent"] - expected_raw) <= 0.05
    assert b["raw_percent"] == pytest.approx(contributions / total * 100.0, abs=0.011)
    assert sum(d["max_points"] for d in b["requirements"]) == b["max_points"]
    assert b["adjustment_lines"][0]["label"] == "rounding"
    ev = {d["evidence"] for d in b["requirements"]}
    assert ev <= {"verified", "self_reported", "none"}
    assert "missing" in {d["status"] for d in b["requirements"]} or \
        not any(d["evidence"] == "none" for d in b["requirements"])


def test_endpoint_auth_matrix(db, client, _offline_esco):
    omar = client.post("/api/auth/login",
                       json={"email": "omar@student.edu", "password": "demo1234"}).json()
    aisha = client.post("/api/auth/login",
                        json={"email": "aisha@student.edu", "password": "demo1234"}).json()
    omar_id, aisha_id = omar["student"]["id"], aisha["student"]["id"]
    # guest -> 401
    assert client.get(f"/api/students/{aisha_id}/target-role-match/breakdown").status_code == 401
    # cross-student -> 403
    r = client.get(f"/api/students/{aisha_id}/target-role-match/breakdown",
                   headers=_auth_h(omar["token"]))
    assert r.status_code == 403
    # unknown student -> 403 (owner-mismatch guard, same as every student-scoped
    # endpoint; the app never leaks whether a student id exists)
    r = client.get("/api/students/999999/target-role-match/breakdown",
                   headers=_auth_h(aisha["token"]))
    assert r.status_code == 403


def test_endpoint_target_role_no_target_404(client, db):
    aisha = client.post("/api/auth/login",
                        json={"email": "aisha@student.edu", "password": "demo1234"}).json()
    aisha_id = aisha["student"]["id"]
    # update_student ignores None, so clear target_role_id directly on the
    # fixture's shared connection.
    db.execute("UPDATE students SET target_role_id = NULL WHERE id = ?", (aisha_id,))
    db.commit()
    assert models.get_student(aisha_id)["target_role_id"] is None
    r = client.get(f"/api/students/{aisha_id}/target-role-match/breakdown",
                   headers=_auth_h(aisha["token"]))
    assert r.status_code == 404


def test_endpoint_role_match_breakdown(client, db, _offline_esco):
    aisha = client.post("/api/auth/login",
                        json={"email": "aisha@student.edu", "password": "demo1234"}).json()
    aisha_id = aisha["student"]["id"]
    h = _auth_h(aisha["token"])
    recs = client.get(f"/api/students/{aisha_id}/role-recommendations", headers=h)
    assert recs.status_code == 200, recs.text
    recs = recs.json()["recommendations"]
    target = next(r for r in recs if r.get("role_id") is not None)
    r = client.get(f"/api/students/{aisha_id}/role-match/breakdown?role_id={target['role_id']}",
                   headers=h)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["role_id"] == target["role_id"]
    assert b["displayed_percent"] == target["match_score"]
    assert b["formula"] == match_explain.ROLE_MATCH_FORMULA
    assert b["version"] == match_explain.ROLE_MATCH_VERSION
    # no role_id/external_id -> 400
    assert client.get(f"/api/students/{aisha_id}/role-match/breakdown",
                      headers=h).status_code == 400
    # unknown role -> 404
    assert client.get(f"/api/students/{aisha_id}/role-match/breakdown?role_id=999999",
                      headers=h).status_code == 404


def test_endpoint_job_match_breakdown(client, db, _offline_esco, feed):
    feed["jobs"] = [_listing(title="Machine Learning Engineer", location="Cairo, Egypt",
                             tags=["Python", "Machine Learning"])]
    aisha = client.post("/api/auth/login",
                        json={"email": "aisha@student.edu", "password": "demo1234"}).json()
    aisha_id = aisha["student"]["id"]
    h = _auth_h(aisha["token"])
    student = models.get_student(aisha_id)
    skills, role, reqs = match_explain._student_feed_inputs(student)
    data = jobs.recent_jobs(skills=skills, role=role, country="Egypt",
                            location="Cairo", role_requisites=reqs,
                            limit=10, _sync=True)
    assert data["jobs"]
    fp = data["jobs"][0]["fingerprint"]
    r = client.get(f"/api/students/{aisha_id}/jobs/recent/{fp}/breakdown"
                   "?location=Cairo&country=Egypt", headers=h)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["displayed_percent"] == data["jobs"][0]["match_pct"]
    assert b["formula"] == match_explain.JOB_MATCH_FORMULA
    assert b["version"] == match_explain.JOB_MATCH_VERSION
    assert b["constraints"]["location"]["tier"] == "city"
    # unknown fingerprint -> 404
    r = client.get(f"/api/students/{aisha_id}/jobs/recent/deadbeef/breakdown"
                   "?location=Cairo&country=Egypt", headers=h)
    assert r.status_code == 404
    # cross-student -> 403 (omar's token)
    omar = client.post("/api/auth/login",
                       json={"email": "omar@student.edu", "password": "demo1234"}).json()
    r = client.get(f"/api/students/{aisha_id}/jobs/recent/{fp}/breakdown"
                   "?location=Cairo&country=Egypt", headers=_auth_h(omar["token"]))
    assert r.status_code == 403