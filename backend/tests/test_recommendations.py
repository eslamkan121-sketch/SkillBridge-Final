"""Phase B — Universal Target Role Recommendations (test /spec 21).

Deterministic, fully offline: every test pins a fake ESCO gateway through
`app.escoe`, so the normal suite never touches the live labour-market API. The
recommendations module imports `from . import escoe`, so patching attributes on
`app.escoe` is all that is needed.
"""
import pytest

from app import escoe, matching, models

ANCHOR_ROLES = {
    "Graphic Designer", "Marketing Analyst", "Clinical Research Assistant",
    "Architectural Designer", "Financial Analyst",
}


@pytest.fixture(autouse=True)
def offline_escoe(monkeypatch):
    """All tests default to an empty ESCO gateway (no network, no occupations)."""
    monkeypatch.setattr(escoe, "market_occupations_for_skills",
                        lambda skill_names, limit=8: [])
    monkeypatch.setattr(escoe, "occupation_skill_groups",
                        lambda uri: {"essential": [], "optional": []})


def install_escoe(monkeypatch, occupations=(), groups=None, fail_market=False):
    """Point the ESCO gateway at deterministic canned data for one test."""
    def fake_market(skill_names, limit=8):
        if fail_market:
            raise RuntimeError("esco offline")
        return list(occupations)
    def fake_groups(uri):
        if groups is None:
            return {"essential": [], "optional": []}
        return groups.get(uri, {"essential": [], "optional": []})
    monkeypatch.setattr(escoe, "market_occupations_for_skills", fake_market)
    monkeypatch.setattr(escoe, "occupation_skill_groups", fake_groups)


OCC_MLE = {
    "uri": "http://data.europa.eu/esco/occupation/test-ml-engineer",
    "title": "Machine Learning Engineer",
    "code": "2512.3",
    "description": "Builds and deploys ML systems.",
    "score": 0.95,
    "skills": ["Python", "Machine Learning", "Docker", "Cloud Platforms"],
    "essential": ["Python", "Machine Learning"],
    "optional": ["Docker", "Cloud Platforms"],
}

# ESCO describes the same competency as a verb phrase ("advocate for clients"),
# while the profile stores the grounded noun form ("Client advocacy"). There is
# zero exact-key overlap: the occupation only survives via the ESCO discovery
# tags recorded when the occupation was retrieved *because of* that skill.
OCC_LEGAL = {
    "uri": "http://data.europa.eu/esco/occupation/test-legal-assistant",
    "title": "Legal Assistant",
    "code": "3341.1",
    "description": "Supports lawyers with research, drafting and client work.",
    "score": 0.7,
    "skills": ["present legal arguments", "compile legal documents",
               "observe confidentiality", "answer telephone calls",
               "manage administrative support", "use office software",
               "comply with legal regulations", "arrange meetings",
               "maintain records", "organise the workplace",
               "safeguard the interest of the client", "draft legal correspondence"],
    "essential": ["present legal arguments", "compile legal documents",
                  "observe confidentiality", "comply with legal regulations",
                  "safeguard the interest of the client", "draft legal correspondence"],
    "optional": ["answer telephone calls", "manage administrative support",
                 "use office software", "arrange meetings", "maintain records",
                 "organise the workplace"],
    "discovery_skills": ["Client advocacy", "Legal research and writing"],
}


# ------------------------------------------------------------------ helpers

def _set_profile(db, student_id, skills, verified=()):
    """Fully deterministic profile: replaces self-reported, resets verified."""
    db.execute("DELETE FROM verified_skills WHERE student_id=?", (student_id,))
    models.replace_self_reported_skills(
        student_id, [{"name": n, "level": lvl} for (n, lvl) in skills])
    for name, level in verified:
        sk = models.get_or_create_skill(name, "General")
        models.update_verified_skill(student_id, sk["id"], level)


def _rec(client, student_id):
    token = client.post("/api/auth/login",
                        json={"email": "aisha@student.edu", "password": "demo1234"}).json()["token"]
    r = client.get(f"/api/students/{student_id}/role-recommendations",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()


def _by_title(data, title):
    return next((x for x in data["recommendations"] if x["title"] == title), None)


def test_ai_profile_recommends_ai_roles(client, student_id):
    data = _rec(client, student_id)  # aisha: Python/SQL verified Advanced + ML/Docker/Git
    assert data["recommendations"], "expected non-empty recommendations"
    ai = _by_title(data, "Junior AI Engineer")
    assert ai is not None, "AI profile must surface an AI role"
    assert ai["source"] in ("company", "catalog")
    assert ai["match_score"] >= 50.0
    assert ai["confidence"] == "Strong match"
    assert ai["selectable"] is True
    for r in data["recommendations"]:
        assert not (r["title"] in ANCHOR_ROLES and r["match_score"] > ai["match_score"])


def test_graphic_designer_recommended_for_design_profile(client, db, student_id):
    _set_profile(db, student_id, [
        ("Adobe Photoshop", "Advanced"), ("Illustrator", "Advanced"),
        ("Typography", "Intermediate"), ("Brand Identity", "Intermediate")])
    data = _rec(client, student_id)
    gd = _by_title(data, "Graphic Designer")
    assert gd is not None
    assert gd["source"] == "catalog"
    assert gd["match_score"] > 0
    assert gd["confidence"] in ("Good match", "Strong match")
    da = _by_title(data, "Data Analyst")
    assert da is None or gd["match_score"] > da["match_score"]


def test_marketing_analyst_recommended(client, db, student_id):
    _set_profile(db, student_id, [
        ("Market Research", "Advanced"), ("Google Analytics", "Intermediate"),
        ("SEO", "Intermediate"), ("Customer Segmentation", "Intermediate")])
    data = _rec(client, student_id)
    ma = _by_title(data, "Marketing Analyst")
    assert ma is not None and ma["match_score"] > 0


def test_clinical_research_assistant_recommended(client, db, student_id):
    _set_profile(db, student_id, [
        ("Clinical Research", "Intermediate"), ("Research Methods", "Intermediate"),
        ("Data Collection", "Intermediate"),
        ("Medical Documentation", "Intermediate"),
        ("Patient Communication", "Intermediate")])
    data = _rec(client, student_id)
    cr = _by_title(data, "Clinical Research Assistant")
    assert cr is not None and cr["match_score"] > 0
    assert cr["regulated_warning"] is True
    note = data["note"].lower()
    assert "medical licensure" in note
    assert "board certification" in note
    assert "authorization to practice" in note


def test_law_profile_has_reference_target_when_esco_unavailable(client, db, student_id, monkeypatch):
    _set_profile(db, student_id, [
        ("Client advocacy", "Intermediate"),
        ("Legal research and writing", "Intermediate"),
        ("Dispute resolution and mediation", "Intermediate"),
        ("Public speaking", "Intermediate"),
    ])
    install_escoe(monkeypatch, fail_market=True)

    data = _rec(client, student_id)
    legal = _by_title(data, "Legal Assistant")

    assert legal is not None
    assert legal["source"] == "catalog"
    assert legal["selectable"] is True
    assert legal["regulated_warning"] is True
    assert "legal licensure" in data["note"].lower()


def test_architecture_recommended_and_not_swapped_for_design(client, db, student_id):
    _set_profile(db, student_id, [
        ("AutoCAD", "Advanced"), ("Revit", "Intermediate"),
        ("Architectural Drawing", "Advanced"), ("Spatial Planning", "Intermediate"),
        ("3D Modeling", "Intermediate")])
    data = _rec(client, student_id)
    ad = _by_title(data, "Architectural Designer")
    assert ad is not None and ad["match_score"] >= 40.0
    assert _by_title(data, "Graphic Designer") is None, \
        "an architectural profile must not be pushed into graphic design"


def test_finance_domain_beats_data_analyst_for_finance_profile(client, db, student_id):
    _set_profile(db, student_id, [
        ("Financial Modeling", "Advanced"), ("Forecasting", "Advanced"),
        ("Budget Analysis", "Intermediate"), ("Excel", "Advanced"),
        ("Data Analysis", "Intermediate")])
    data = _rec(client, student_id)
    fa = _by_title(data, "Financial Analyst")
    assert fa is not None
    assert fa["confidence"] == "Strong match"
    da = _by_title(data, "Data Analyst")
    fda = _by_title(data, "Financial Data Analyst")
    if da:
        assert fa["match_score"] > da["match_score"]
    if fda:
        assert fa["match_score"] > fda["match_score"]


def test_communication_alone_never_strong(client, db, student_id):
    _set_profile(db, student_id, [("Communication", "Advanced")])
    data = _rec(client, student_id)
    assert data["recommendations"]
    assert not any(r["confidence"] in ("Strong match", "Good match")
                   for r in data["recommendations"]), \
        "a single soft skill must never look like a career"


def test_excel_alone_never_strong_financial_analyst(client, db, student_id):
    _set_profile(db, student_id, [("Excel", "Advanced")])
    data = _rec(client, student_id)
    fa = _by_title(data, "Financial Analyst")
    assert fa is not None and fa["confidence"] == "Possible match"
    assert fa["match_score"] < 55.0
    assert not any(r["confidence"] == "Strong match" for r in data["recommendations"])


def test_specific_skill_combo_beats_generic_overlap(client, db, student_id):
    _set_profile(db, student_id, [("Excel", "Advanced"), ("SQL", "Advanced")])
    generic = _by_title(_rec(client, student_id), "Financial Analyst")
    _set_profile(db, student_id, [
        ("Excel", "Advanced"), ("SQL", "Advanced"),
        ("Financial Modeling", "Advanced"), ("Forecasting", "Advanced")])
    data = _rec(client, student_id)
    specific = _by_title(data, "Financial Analyst")
    assert generic is not None and specific is not None
    assert specific["match_score"] > generic["match_score"]
    assert specific["match_score"] > _by_title(data, "Data Analyst")["match_score"]


def test_verified_boost_is_small_and_bounded(client, db, student_id):
    _set_profile(db, student_id, [("Python", "Advanced"), ("SQL", "Advanced")])
    plain = _rec(client, student_id)
    _set_profile(db, student_id, [("Python", "Advanced"), ("SQL", "Advanced")],
                 verified=[("Python", "Advanced"), ("SQL", "Advanced")])
    boosted = _rec(client, student_id)
    for title in ("Junior AI Engineer", "Data Engineer", "Data Analyst"):
        a = _by_title(plain, title)
        b = _by_title(boosted, title)
        if a and b:
            assert b["match_score"] > a["match_score"], "verified edge must help"
            assert b["match_score"] <= a["match_score"] * 1.6 + 1.0, \
                "verified boost must stay small and bounded"


def test_unrelated_verified_skill_has_zero_effect(client, db, student_id):
    _set_profile(db, student_id, [("Python", "Advanced")])
    before = _rec(client, student_id)
    _set_profile(db, student_id, [("Python", "Advanced")],
                 verified=[("Classical Guitar", "Advanced")])
    after = _rec(client, student_id)
    bmap = {r["title"]: r["match_score"] for r in before["recommendations"]}
    amap = {r["title"]: r["match_score"] for r in after["recommendations"]}
    assert bmap == amap, "an unrelated verified skill must not move any score"


def test_company_role_is_a_normal_candidate(client, student_id):
    data = _rec(client, student_id)
    jae = _by_title(data, "Junior AI Engineer")
    assert jae is not None and jae["source"] == "company"
    assert jae.get("company_name")


def test_esco_occupation_appears_with_markers(client, student_id, monkeypatch):
    install_escoe(monkeypatch, occupations=[OCC_MLE])
    data = _rec(client, student_id)
    esco = next((r for r in data["recommendations"] if r["source"] == "esco"), None)
    assert esco is not None
    assert esco["external_id"] == OCC_MLE["uri"]
    assert esco["match_score"] > 0
    assert esco["selectable"] is True
    assert data["esco_status"] == "ok"


def test_esco_discovery_profiles_surface_non_cs_roles(client, db, student_id, monkeypatch):
    """A legal profile has ZERO exact-skills overlap with ESCO's verb-phrase
    essential skills. Without discovery matching such occupations are dropped
    entirely (the reported bug: only ~% PS CS roles left). Discovery tags, set
    when an occupation is retrieved because of a student skill, must bridge it
    and the real skill names must be reported as matched evidence."""
    _set_profile(db, student_id, [
        ("Client advocacy", "Intermediate"), ("Legal research and writing", "Advanced"),
        ("Public speaking", "Intermediate")])
    install_escoe(monkeypatch, occupations=[OCC_LEGAL])
    data = _rec(client, student_id)
    legal = _by_title(data, "Legal Assistant")
    assert legal is not None, "ESCO legal occupation must surface for a legal profile"
    assert legal["source"] == "esco"
    assert legal["match_score"] > 0
    assert legal["confidence"] in ("Good match", "Possible match")
    matched = {m["name"] for m in legal["matched_skills"]}
    assert {"Client advocacy", "Legal research and writing"} <= matched
    # the generic-data role must never outrank the skill-evidence role here
    da = _by_title(data, "Data Analyst")
    if da:
        assert legal["match_score"] > da["match_score"]


def test_esco_discovery_never_matches_unrelated_profiles(client, db, student_id, monkeypatch):
    """Discovery tags are scoped to the occupations a skill actually retrieved:
    a profile without those skills gets no credit from someone else's tags."""
    _set_profile(db, student_id, [("Excel", "Advanced"), ("Data Analysis", "Intermediate")])
    install_escoe(monkeypatch, occupations=[OCC_LEGAL])
    data = _rec(client, student_id)
    legal = _by_title(data, "Legal Assistant")
    # no discovery key present in profile -> falls back to exact-key matching ->
    # zero overlap -> the legal occupation is honestly absent
    assert legal is None, "legal role must not surface for an unrelated profile"


def test_real_jobs_rank_before_catalog_reference_roles(client, db, student_id, monkeypatch):
    """Real labour-market roles (ESCO occupations + company postings) must lead
    the recommended list even when a catalog reference role has a higher raw
    match %: a student aiming at job-readiness is pointed at real occupations
    first, with catalog relegated to a labelled secondary section."""
    _set_profile(db, student_id, [
        ("Excel", "Advanced"), ("SQL", "Advanced"), ("Financial Modeling", "Advanced"),
        ("Forecasting", "Advanced"), ("Client advocacy", "Intermediate"),
        ("Legal research and writing", "Intermediate")])
    install_escoe(monkeypatch, occupations=[OCC_LEGAL])
    data = _rec(client, student_id)
    financial = _by_title(data, "Financial Analyst")          # local catalog, strong
    legal = _by_title(data, "Legal Assistant")                 # real ESCO occupation
    js_ai = _by_title(data, "Junior AI Engineer")              # real company posting
    assert financial is not None and legal is not None
    assert legal["match_score"] < financial["match_score"], \
        "set up a case where the catalog role out-scores the real job on raw match %"
    titles = [r["title"] for r in data["recommendations"]]
    assert titles.index("Legal Assistant") < titles.index("Financial Analyst"), \
        "a real ESCO occupation must come before a stronger-scoring catalog role"
    if js_ai is not None:
        assert titles.index("Junior AI Engineer") < titles.index("Financial Analyst"), \
            "a real company posting must come before a stronger-scoring catalog role"
    # every real role still carries its honest source marker
    assert any(r["source"] == "esco" for r in data["recommendations"])
    assert data["source_counts"]["catalog"] >= 1


def test_esco_failure_still_returns_honest_local_recs(client, student_id, monkeypatch):
    install_escoe(monkeypatch, fail_market=True)
    data = _rec(client, student_id)
    assert data["esco_status"] == "unavailable"
    assert data["recommendations"], "ESCO outage must still give local recommendations"
    assert "unavailable" in data["note"].lower()
    assert any(r["source"] in ("company", "catalog") for r in data["recommendations"])


def test_esco_role_selectable_as_target(client, db, student_id, auth_headers, monkeypatch):
    install_escoe(monkeypatch,
                  groups={OCC_MLE["uri"]: {"essential": OCC_MLE["essential"],
                                           "optional": OCC_MLE["optional"]}})
    r = client.post(f"/api/students/{student_id}/target-role/esco",
                    headers=auth_headers("aisha@student.edu"),
                    json={"uri": OCC_MLE["uri"], "title": OCC_MLE["title"],
                          "skills": OCC_MLE["skills"]})
    assert r.status_code == 200, r.text
    student = r.json()
    assert student["target_role"]["title"] == "Machine Learning Engineer"
    assert student["target_role"]["source"] == "esco"
    assert student["target_role"]["external_id"] == OCC_MLE["uri"]
    names = [s["name"] for s in student["target_role"]["required_skills"]]
    assert "Python" in names and "Machine Learning" in names


def test_esco_import_is_idempotent(client, db, student_id, auth_headers, monkeypatch):
    install_escoe(monkeypatch,
                  groups={OCC_MLE["uri"]: {"essential": OCC_MLE["essential"],
                                           "optional": OCC_MLE["optional"]}})
    headers = auth_headers("aisha@student.edu")
    body = {"uri": OCC_MLE["uri"], "title": OCC_MLE["title"], "skills": []}
    first = client.post(f"/api/students/{student_id}/target-role/esco",
                        headers=headers, json=body).json()
    second = client.post(f"/api/students/{student_id}/target-role/esco",
                         headers=headers, json=body).json()
    assert first["target_role"]["id"] == second["target_role"]["id"]
    row = db.execute("SELECT COUNT(*) AS n FROM roles WHERE source='esco' AND external_id=?",
                     (OCC_MLE["uri"],)).fetchone()
    assert row["n"] == 1


def test_esco_skills_survive_open_normalization(client, db, student_id, auth_headers, monkeypatch):
    install_escoe(monkeypatch,
                  groups={OCC_MLE["uri"]: {"essential": OCC_MLE["essential"],
                                           "optional": OCC_MLE["optional"]}})
    client.post(f"/api/students/{student_id}/target-role/esco",
                headers=auth_headers("aisha@student.edu"),
                json={"uri": OCC_MLE["uri"], "title": OCC_MLE["title"], "skills": []})
    role = models.get_role(models.get_student(student_id)["target_role_id"])
    names = {s["name"] for s in role["required_skills"]}
    assert {"Python", "Machine Learning", "Docker"} <= names
    kinds = {s["name"]: s["skill_kind"] for s in role["required_skills"]}
    assert kinds["Python"] == "essential" and kinds["Docker"] == "optional"
    # Phase A open universe: unknown/domain skills are normalised and kept
    # across profile replacement, and the imported role still drives analysis.
    _set_profile(db, student_id, [("Machine Learning", "Intermediate"),
                                  ("Data Wrangling", "Intermediate")])
    prof_names = {s["name"] for s in models.get_student(student_id)["self_reported_skills"]}
    assert "Data Wrangling" in prof_names and "Machine Learning" in prof_names
    analysis = matching.analyze_student(student_id)
    assert analysis is not None and analysis["gap_count"] >= 0


def test_sources_are_distinguishable(client, student_id, monkeypatch):
    install_escoe(monkeypatch, occupations=[OCC_MLE])
    data = _rec(client, student_id)
    assert {r["source"] for r in data["recommendations"]} >= {"company", "catalog", "esco"}
    assert data["source_counts"]["company"] >= 1
    assert data["source_counts"]["catalog"] >= 1
    assert data["source_counts"]["esco"] >= 1
    assert all(r["selectable"] for r in data["recommendations"])


def test_selected_role_drives_existing_gap_analysis(client, db, student_id, auth_headers, monkeypatch):
    install_escoe(monkeypatch,
                  groups={OCC_MLE["uri"]: {"essential": OCC_MLE["essential"],
                                           "optional": OCC_MLE["optional"]}})
    client.post(f"/api/students/{student_id}/target-role/esco",
                headers=auth_headers("aisha@student.edu"),
                json={"uri": OCC_MLE["uri"], "title": OCC_MLE["title"], "skills": []})
    analysis = matching.analyze_student(student_id)
    assert analysis is not None
    assert analysis["role_id"] > 0
    assert analysis["skill_gaps"] and analysis["gap_count"] >= 0


def test_no_verified_skill_created_by_recommend_or_select(client, db, student_id, auth_headers, monkeypatch):
    _set_profile(db, student_id, [("Python", "Advanced")])
    before = len(models.get_student(student_id)["verified_skills"])
    data = _rec(client, student_id)
    assert data["recommendations"]
    install_escoe(monkeypatch,
                  groups={OCC_MLE["uri"]: {"essential": OCC_MLE["essential"],
                                           "optional": OCC_MLE["optional"]}})
    client.post(f"/api/students/{student_id}/target-role/esco",
                headers=auth_headers("aisha@student.edu"),
                json={"uri": OCC_MLE["uri"], "title": OCC_MLE["title"], "skills": []})
    after = len(models.get_student(student_id)["verified_skills"])
    assert after == before == 0, "recommendations must never mint Verified Skills"


def test_no_verified_skill_created_by_recommend_or_select_keeps_student_choice_flow(client, db, student_id):
    """Choosing a normal (non-ESCO) target keeps the existing PUT flow intact."""
    _set_profile(db, student_id, [("Python", "Advanced"), ("SQL", "Advanced")])
    data = _rec(client, student_id)
    chosen = next(r for r in data["recommendations"] if r["source"] == "company")
    role = models.get_role(chosen["role_id"])
    models.update_student(student_id, target_role_id=role["id"])
    student = models.get_student(student_id)
    assert student["target_role"]["title"] == role["title"]
    assert student["target_role"]["source"] == "company"
