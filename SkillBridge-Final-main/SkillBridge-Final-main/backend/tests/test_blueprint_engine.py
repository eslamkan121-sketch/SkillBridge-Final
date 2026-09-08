"""Phase C — Universal Competency Blueprint Engine.

Covers the shared, domain-agnostic derivation of required competencies for ANY
skill (trusted / GenAI-derived / honest fallback), plus its integration into the
diagnostic, coverage, personalized-path and learning-item pipelines.

All GenAI is mocked: `genai.complete` returns canned domain decompositions for
unit-level derivation tests, and endpoint-level tests substitute the GenAI
transport in `skill_blueprint._genai_derive_competencies` while keeping the
rest of the pipeline deterministic. No real API key is ever consumed.
"""
import json

import pytest

from app import coverage as cov
from app import diagnostics, genai, models
from app import path_builder as pb
from app import skill_blueprint as sb


# ------------------------------------------------------------------ fixtures

@pytest.fixture(autouse=True)
def _isolate_derived_cache():
    sb.clear_derived_cache()
    yield
    sb.clear_derived_cache()


# Realistic domain decompositions (the "ground truth" a mock LLM returns).
_DOMAIN_BLUEPRINTS = {
    "typography": [
        ("Visual Hierarchy", "Organize type to guide the reader's eye by importance", "high"),
        ("Readability", "Ensure body text is legible across sizes and media", "high"),
        ("Type Pairing", "Combine typefaces that contrast and complement", "medium"),
        ("Spacing", "Use tracking, leading, and margins for balanced composition", "medium"),
        ("Layout Application", "Apply type systems to real layouts and grids", "high"),
    ],
    "market research": [
        ("Research Objectives", "Define clear, actionable research goals", "high"),
        ("Research Design", "Choose methods and sampling that answer the question", "high"),
        ("Data Collection", "Gather primary and secondary data reliably", "medium"),
        ("Segmentation", "Group the market into meaningful customer segments", "medium"),
        ("Interpretation", "Translate findings into insights and recommendations", "high"),
        ("Reporting", "Present research findings to stakeholders effectively", "medium"),
    ],
    "clinical research": [
        ("Study Design & Protocols", "Design a sound clinical study and protocol", "high"),
        ("Patient Data Collection", "Collect and record patient data accurately and ethically", "high"),
        ("Regulatory & Compliance", "Follow research ethics, GCP, and regulatory requirements", "high"),
        ("Data Analysis & Reporting", "Analyze clinical data and report results transparently", "medium"),
        ("Informed Consent", "Ensure informed consent and participant welfare", "high"),
    ],
    "revit": [
        ("BIM Fundamentals", "Understand BIM principles and the Revit project environment", "high"),
        ("Modeling & Elements", "Create and edit building elements and components", "high"),
        ("Families & Parameters", "Build and manage families and parameter-driven content", "medium"),
        ("Views & Sheets", "Generate coordinated views, schedules, and sheets", "medium"),
        ("Documentation & Detailing", "Produce construction documentation and detail drawings", "medium"),
    ],
    "financial modeling": [
        ("Model Structure", "Organize a clear, auditable model layout", "high"),
        ("Assumptions & Drivers", "Link and document key business drivers and assumptions", "high"),
        ("Forecasting", "Project revenues, costs, and cash flows", "medium"),
        ("Financial Statements", "Model the three financial statements consistently", "high"),
        ("Scenario & Sensitivity Analysis", "Test scenarios and sensitivity on the model", "low"),
    ],
}


def _domain_for_user(user):
    """Turn a derivation prompt into the canned domain decomposition there."""
    text = (user or "").lower()
    for skill, comps in _DOMAIN_BLUEPRINTS.items():
        if skill in text:
            return [{"name": n, "objective": o, "importance": i} for n, o, i in comps]
    return None


def _install_genai_mock(monkeypatch, resolver=None, enabled=True):
    """Mock `genai.complete` + `genai.genai_enabled`. Returns a call counter."""
    state = {"calls": 0}
    if resolver is None:
        resolver = _domain_for_user

    def fake_complete(system, user, fallback=None, **kwargs):
        state["calls"] += 1
        payload = resolver(user)
        if payload is None:
            return fallback
        return json.dumps(payload)

    monkeypatch.setattr(genai, "genai_enabled", lambda: enabled)
    monkeypatch.setattr(genai, "complete", fake_complete)
    return state


def _install_fake_derivation(monkeypatch):
    """Endpoint-level substitute: derivation transport returns the domain
    blueprints, while the rest of the pipeline stays deterministic."""
    def fake_derive(skill_name, target_role=None, required_level=None, context=None):
        comps = _DOMAIN_BLUEPRINTS.get((skill_name or "").strip().lower())
        if not comps:
            return [], False
        return [{"name": n, "objective": o, "importance": i} for n, o, i in comps], True

    monkeypatch.setattr(sb, "_genai_derive_competencies", fake_derive)


def _skill_slugs(name):
    bp = sb.derive_competencies(name)
    return bp, {c["slug"] for c in bp["competencies"]}


def _skill(name, category):
    """Reuse a seeded skill if present, else create one (avoids UNIQUE clashes)."""
    return models.get_skill_by_name(name) or models.create_skill(name, category)


# ------------------------------------------------------------ 1-2 trusted, unchanged

def test_trusted_docker_blueprint_is_authoritative():
    bp = sb.derive_competencies("Docker")
    assert bp["source"] == "trusted"
    assert bp["blueprint_version"] == sb.BLUEPRINT_VERSION
    names = [c["name"] for c in bp["competencies"]]
    assert names == sb.BLUEPRINT["docker"]["Beginner"] + \
        sb.BLUEPRINT["docker"]["Intermediate"] + sb.BLUEPRINT["docker"]["Advanced"]


def test_trusted_sql_blueprint_is_authoritative():
    bp = sb.derive_competencies("SQL")
    assert bp["source"] == "trusted"
    names = [c["name"] for c in bp["competencies"]]
    assert "Queries & filtering" in names and "Window functions" in names
    assert sb.source_for("SQL") == "trusted"


# ------------------------------------------------------------ 3-8 meaningful derivation

def test_unknown_skill_gets_multiple_competencies(monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    bp = sb.derive_competencies("Exhibition Curation")
    assert bp["source"] == "fallback"
    assert len(bp["competencies"]) >= 3
    assert all(c["name"].lower() != "exhibition curation fundamentals"
               for c in bp["competencies"])


@pytest.mark.parametrize("skill,expected_slugs", [
    ("Typography", {"visual_hierarchy", "readability", "type_pairing",
                    "spacing", "layout_application"}),
    ("Market Research", {"research_objectives", "research_design",
                         "data_collection", "segmentation", "interpretation",
                         "reporting"}),
    ("Clinical Research", {"study_design_&_protocols", "patient_data_collection",
                           "regulatory_&_compliance", "data_analysis_&_reporting",
                           "informed_consent"}),
    ("Revit", {"bim_fundamentals", "modeling_&_elements", "families_&_parameters",
               "views_&_sheets", "documentation_&_detailing"}),
    ("Financial Modeling", {"model_structure", "assumptions_&_drivers",
                            "forecasting", "financial_statements",
                            "scenario_&_sensitivity_analysis"}),
], ids=["typography", "market_research", "clinical_research", "revit", "financial_modeling"])
def test_noncs_skill_derives_meaningful_blueprint(monkeypatch, skill, expected_slugs):
    _install_genai_mock(monkeypatch)
    bp, slugs = _skill_slugs(skill)
    assert bp["source"] == "derived"
    assert len(slugs) == len(_DOMAIN_BLUEPRINTS[skill.lower()])
    assert expected_slugs == slugs
    for c in bp["competencies"]:
        assert c["name"].lower() != f"{skill.lower()} fundamentals"


def test_derived_blueprint_includes_objectives_and_importance(monkeypatch):
    _install_genai_mock(monkeypatch)
    bp, _ = _skill_slugs("Revit")
    for c in bp["competencies"]:
        assert c["objective"]
        assert c["importance"] in ("high", "medium", "low")


# ------------------------------------------------------------ 9 role emphasis

def test_role_context_shifts_emphasis_without_breaking(monkeypatch):
    def resolver(user):
        if "marketing analyst" in (user or "").lower():
            return [
                {"name": "Customer Insight", "objective": "Analyze audience behavior for campaigns", "importance": "high"},
                {"name": "Segmentation Analysis", "objective": "Segment audiences by behavior", "importance": "high"},
                {"name": "Campaign Attribution", "objective": "Attribute outcomes to marketing channels", "importance": "medium"},
                {"name": "Data Storytelling", "objective": "Present insights persuasive for stakeholders", "importance": "medium"},
            ]
        return [
            {"name": "Data Fundamentals", "objective": "Understand core data concepts", "importance": "high"},
            {"name": "Analysis Techniques", "objective": "Apply analysis methods", "importance": "high"},
            {"name": "Insight Generation", "objective": "Extract actionable insights", "importance": "medium"},
            {"name": "Tools & Automation", "objective": "Use tooling efficiently", "importance": "low"},
        ]

    _install_genai_mock(monkeypatch, resolver=resolver)
    base, base_slugs = _skill_slugs("Data Analysis")
    role, role_slugs = _skill_slugs_ = None, None
    role_bp = sb.derive_competencies("Data Analysis", "Marketing Analyst")
    role_slugs = {c["slug"] for c in role_bp["competencies"]}
    assert base_slugs != role_slugs, "role context must shift emphasis"
    assert "customer_insight" in role_slugs and "campaign_attribution" in role_slugs
    assert "data_fundamentals" in base_slugs
    assert len(role_bp["competencies"]) >= 3  # still a valid blueprint
    assert sb.source_for("Data Analysis", "Marketing Analyst") == "derived"


# ------------------------------------------------------------ 10-13 validation

def test_derived_level_does_not_change_competency_ids(monkeypatch):
    _install_genai_mock(monkeypatch)
    a = sb.required_competencies("Revit", "Beginner", "Beginner")
    b = sb.required_competencies("Revit", "Beginner", "Intermediate")
    c = sb.required_competencies("Revit", "Beginner", "Advanced")
    sa = {sb.competency_slug(n) for n in a}
    sb_ = {sb.competency_slug(n) for n in b}
    sc = {sb.competency_slug(n) for n in c}
    assert sa == sb_ == sc, "derived blueprints are level-flat; IDs never vary by level"


def test_malformed_llm_json_rejected_with_fallback(monkeypatch):
    _install_genai_mock(monkeypatch, resolver=lambda user: "this is not json at all")
    bp = sb.derive_competencies("Event Production")
    assert bp["source"] == "fallback"
    assert 3 <= len(bp["competencies"]) <= 8


def test_duplicate_competencies_dropped(monkeypatch):
    def resolver(user):
        return [
            {"name": "Venue Logistics", "objective": "Manage venue operations", "importance": "high"},
            {"name": "Venue Logistics", "objective": "Manage venue operations", "importance": "high"},
            {"name": "Catering Coordination", "objective": "Coordinate catering", "importance": "medium"},
            {"name": "Catering Coordination", "objective": "Coordinate catering", "importance": "medium"},
            {"name": "Sponsor Liaison", "objective": "Manage sponsor relations", "importance": "medium"},
        ]

    _install_genai_mock(monkeypatch, resolver=resolver)
    bp = sb.derive_competencies("Event Production")
    slugs = [c["slug"] for c in bp["competencies"]]
    assert len(slugs) == len(set(slugs)), "duplicates must be dropped"
    assert bp["source"] == "derived"
    assert 3 <= len(slugs) < 5  # duplicates collapsed, still over the minimum


def test_excessive_derived_list_clamped(monkeypatch):
    def resolver(user):
        return [{"name": f"Competency {i}", "objective": "x", "importance": "medium"}
                for i in range(12)]

    _install_genai_mock(monkeypatch, resolver=resolver)
    bp = sb.derive_competencies("Event Production")
    assert bp["source"] == "derived"
    assert len(bp["competencies"]) == 8  # clamped at the maximum


# ------------------------------------------------------------ 14-15 honest provenance

def test_ai_unavailable_falls_back_honestly(monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    bp = sb.derive_competencies("Museum Curation")
    assert bp["source"] == "fallback"
    assert len(bp["competencies"]) >= 3
    names = [c["name"] for c in bp["competencies"]]
    assert "Museum Curation fundamentals" not in names


def test_source_is_labeled_honestly(monkeypatch):
    assert sb.source_for("Docker") == "trusted"
    _install_genai_mock(monkeypatch)
    assert sb.source_for("Typography") == "derived"
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    sb.clear_derived_cache("Typography")
    assert sb.source_for("Typography") == "fallback"


# ------------------------------------------------------------ 16-18 cache and determinism

def test_derived_blueprint_cached_no_repeat_generation(monkeypatch):
    state = _install_genai_mock(monkeypatch)
    sb.derive_competencies("Revit")
    sb.derive_competencies("Revit")
    sb.derive_competencies("Revit")
    assert state["calls"] == 1, "cache must prevent repeated LLM generation"


def test_blueprint_version_stable(monkeypatch):
    _install_genai_mock(monkeypatch)
    first = sb.derive_competencies("Typography")
    sb.clear_derived_cache("Typography")
    second = sb.derive_competencies("Typography")
    assert first["blueprint_version"] == second["blueprint_version"] == sb.DERIVED_VERSION


def test_competency_ids_deterministic_across_cache_clears(monkeypatch):
    _install_genai_mock(monkeypatch)
    _, slugs_a = _skill_slugs("Financial Modeling")
    sb.clear_derived_cache("Financial Modeling")
    _, slugs_b = _skill_slugs("Financial Modeling")
    _, slugs_c = _skill_slugs("Financial Modeling")
    assert slugs_a == slugs_b == slugs_c


# ------------------------------------------------------------ 19-20 diagnostic + coverage

def test_diagnostic_uses_derived_competencies(client, student_id, auth_headers, monkeypatch):
    _install_fake_derivation(monkeypatch)
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    skill = _skill("Typography", "Professional Skill")
    headers = auth_headers("aisha@student.edu")
    r = client.post(f"/api/students/{student_id}/learning/{skill['id']}/diagnostic/generate",
                    json={}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    derived = _DOMAIN_BLUEPRINTS["typography"]
    expected_topics = {n for n, _o, _i in derived}
    assert set(body["topics"]) == expected_topics
    expected_slugs = {sb.competency_slug(n) for n, _o, _i in derived}
    for q in body["questions"]:
        assert q["competency"] in expected_slugs
    assert {q["competency"] for q in body["questions"]} == expected_slugs


def test_coverage_non_vacuous_for_derived_skill(monkeypatch):
    _install_fake_derivation(monkeypatch)
    req = cov.required_slugs("Typography", "Intermediate")
    expected_slugs = {sb.competency_slug(n) for n, _o, _i in _DOMAIN_BLUEPRINTS["typography"]}
    assert set(req) == expected_slugs
    assert len(req) >= 3
    assert sb.required_competencies("Typography", "Beginner", "Advanced")
    covered, missing = cov.coverage_for_questions(
        [{"competency": s} for s in req], req)
    assert covered is True and missing == []


# ------------------------------------------------------------ 21-22 personalized path

def _fake_typography_diagnostic(results):
    return {
        "completed_at": "2026-01-01T00:00:00",
        "topic_results": results,
    }


def test_weak_derived_competency_prioritized_in_path(monkeypatch):
    _install_fake_derivation(monkeypatch)
    diag = _fake_typography_diagnostic([
        {"competency": "visual_hierarchy", "label": "Visual Hierarchy",
         "score": 35.0, "status": diagnostics.WEAK},
        {"competency": "type_pairing", "label": "Type Pairing",
         "score": 55.0, "status": diagnostics.DEVELOPING},
        {"competency": "spacing", "label": "Spacing",
         "score": 99.0, "status": diagnostics.MASTERED},
    ])
    built = pb.build_personalized_path({"name": "Typography", "category": "Professional Skill", "id": 1}, diag)
    assert built["path"], "path must not be empty"
    assert built["path"][0]["competency"] == "visual_hierarchy", "weak topic must come first"
    assert built["path"][1]["competency"] == "type_pairing"


def test_mastered_derived_competency_skipped_in_path(monkeypatch):
    _install_fake_derivation(monkeypatch)
    diag = _fake_typography_diagnostic([
        {"competency": "visual_hierarchy", "label": "Visual Hierarchy",
         "score": 82.0, "status": diagnostics.MASTERED},
        {"competency": "readability", "label": "Readability",
         "score": 45.0, "status": diagnostics.WEAK},
    ])
    built = pb.build_personalized_path({"name": "Typography", "category": "Professional Skill", "id": 1}, diag)
    comps = [i["competency"] for i in built["path"]]
    assert "readability" in comps
    assert "visual_hierarchy" not in comps, "mastered competency must be skipped"
    assert "visual_hierarchy" in built["skipped_mastered"]


# ------------------------------------------------------------ 23 learning item

def test_learning_item_receives_derived_competencies(client, student_id, auth_headers, monkeypatch):
    _install_fake_derivation(monkeypatch)
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    skill = _skill("Market Research", "Analytics")
    headers = auth_headers("aisha@student.edu")
    r = client.post(f"/api/students/{student_id}/learning/generate",
                    json={"skill_id": skill["id"]}, headers=headers)
    assert r.status_code == 200, r.text
    item = r.json()
    expected = [n for n, _o, _i in _DOMAIN_BLUEPRINTS["market research"]]
    assert item.get("blueprint_competencies") == expected
    modules = item.get("modules") or []
    assert modules, "derived skill must produce learning modules"
    comps = {m["competency"] for m in modules if not m.get("beyond_blueprint")}
    assert comps and comps <= set(expected)


# ------------------------------------------------------------ 24-25 verified-skill invariants

def test_selecting_target_role_creates_no_verified_skill(client, db):
    u = models.create_user("mel@student.edu", "Student", "Mel Survey", password="demo1234")
    student = models.create_student("Mel Survey", "mel@student.edu", "Aston University", user_id=u["id"])
    sid = student["id"]
    assert models.get_student(sid)["verified_skills"] == []
    role_row = db.execute(
        "SELECT id FROM roles WHERE title='Junior AI Engineer' AND source='company' LIMIT 1").fetchone()
    assert role_row, "seeded role must exist for this integration test"
    models.update_student(sid, target_role_id=role_row["id"])
    assert models.get_student(sid)["target_role"]["title"]
    assert models.get_student(sid)["verified_skills"] == [], \
        "selecting a target role must never create a Verified Skill"


def test_competency_completion_creates_no_verified_skill(client, student_id, auth_headers, monkeypatch):
    """Full flow: deriving competencies for an unknown skill, taking and passing
    its diagnostic (a Mini Check) must NEVER create a Verified Skill — only the
    real Final Assessment may do that."""
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    skill = _skill("Museum Curation", "Professional Skill")
    assert sb.has_blueprint("Museum Curation")
    before = [v["skill_id"] for v in models.get_student(student_id)["verified_skills"]]

    headers = auth_headers("aisha@student.edu")
    gen = client.post(f"/api/students/{student_id}/learning/{skill['id']}/diagnostic/generate",
                      json={}, headers=headers)
    assert gen.status_code == 200, gen.text
    body = gen.json()
    assert len(body["topics"]) >= 3, "derived blueprint must yield real topics"

    answers = [q["correct_answer"] for q in body["questions"]]
    sub = client.post(f"/api/students/{student_id}/learning/{skill['id']}/diagnostic/submit",
                      json={"diagnostic_id": body["diagnostic_id"], "answers": answers},
                      headers=headers)
    assert sub.status_code == 200, sub.text

    after = [v["skill_id"] for v in models.get_student(student_id)["verified_skills"]]
    assert after == before, "completing derived competencies must never create a Verified Skill"