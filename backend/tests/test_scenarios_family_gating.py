"""Phase 3 family gating: per-family scenario isolation, deterministic
role-blueprints for out-of-family roles, versioning, and library swaps.

Designed so ANY target role receives relevant professional practice and never
another domain's scenarios (guide §"Target roles must not see security
scenarios"). Uses the PRE-EXISTING seeded students only when it doesn't matter
which cohort they belong to; synthetic students are used for the strict
cross-family assertions."""
import pytest

from app import models, scenario_catalog, scenarios


def _make_student(email, target_role_title, skills=()):
    u = models.create_user(email, "Student", f"{email} fixture", password="demo1234")
    sid = models.create_student(f"{email} fixture", email, "Test University", user_id=u["id"])["id"]
    existing = models.list_roles()
    role = next((r for r in existing if r["title"].strip().lower() == target_role_title.strip().lower()), None)
    if not role:
        # The seeded CATALOG roles are not in list_roles(), so a fresh role is
        # created carrying the fixture's skills — that is what makes blueprints
        # non-empty for out-of-family targets.
        role = models.create_role(None, target_role_title, [
            {"name": name, "level": "Intermediate", "category": "General"}
            for name in {n for n, _ in skills}
        ])
    models.update_student(sid, target_role_id=role["id"])
    return sid


def _login(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": "demo1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _library(client, h, sid):
    r = client.get(f"/api/students/{sid}/scenarios", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------- resolution

def test_family_resolutions_for_curated_and_catalog_titles():
    assert scenarios.family_for_role("Cybersecurity Analyst") == "security"
    assert scenarios.family_for_role("Data Analyst") == "data"
    assert scenarios.family_for_role("Junior AI Engineer") == "ai"
    assert scenarios.family_for_role("DevOps / Platform Engineer") == "cloud_devops"
    assert scenarios.family_for_role("Financial Data Analyst") == "finance"
    assert scenarios.family_for_role("Product Analyst") == "data"
    assert scenarios.family_for_role("UI/UX Designer") == "design"
    assert scenarios.family_for_role("General Dentist") is None
    assert scenarios.family_for_role("Legal Assistant") is None
    assert scenarios.family_for_role("Clinical Research Assistant") is None
    assert scenarios.family_for_role("Architectural Designer") is None


def test_catalog_is_flat_list_of_24_family_scenarios():
    assert isinstance(scenario_catalog.FAMILY_SCENARIOS, list)
    assert len(scenario_catalog.FAMILY_SCENARIOS) == 24
    by_family = {}
    for scn in scenario_catalog.FAMILY_SCENARIOS:
        by_family.setdefault(scn["family"], []).append(scn["id"])
    assert set(by_family) == {"data", "software", "ai", "cloud_devops",
                              "marketing", "finance", "design", "project_ops"}
    assert all(len(v) == 3 for v in by_family.values())


# ------------------------------------------------------------ isolation

def test_seeded_data_student_sees_only_data_scenarios(client):
    h = _login(client, "leila@student.edu")
    data = _library(client, h, models.get_student_by_user(
        models.get_session_user(_token(h)["token"])["id"])["id"])
    families = {sc["family"] for sc in data["scenarios"]}
    assert families == {"data"}
    assert not any(sc["family"] == "security" for sc in data["scenarios"])
    assert data["availability"] == "ok"


def test_seeded_ai_student_sees_only_ai_scenarios(client):
    h = _login(client, "aisha@student.edu")
    user = models.get_session_user(_token(h)["token"])
    sid = models.get_student_by_user(user["id"])["id"]
    data = _library(client, h, sid)
    families = {sc["family"] for sc in data["scenarios"]}
    assert families == {"ai"}
    assert not any(sc["family"] == "security" for sc in data["scenarios"])


def test_product_analyst_never_sees_security_even_with_cyber_skills(client):
    sid = _make_student("crossfam@student.edu", "Product Analyst",
                        [("Threat Detection", "Advanced"), ("SIEM Log Analysis", "Intermediate")])
    h = _login(client, "crossfam@student.edu")
    data = _library(client, h, sid)
    assert {sc["family"] for sc in data["scenarios"]} == {"data"}
    r = client.post(f"/api/students/{sid}/scenarios/siem-alert-001/start", headers=h)
    assert r.status_code == 403


def test_no_family_role_gets_blueprints_never_security(client):
    for email, title, skills in [
        ("gat-dentist@student.edu", "General Dentist",
         [("Patient Triage", "Intermediate"), ("Diagnostic Imaging", "Intermediate")]),
        ("gat-legal@student.edu", "Legal Assistant",
         [("Legal Research", "Intermediate"), ("Contract Analysis", "Intermediate")]),
    ]:
        sid = _make_student(email, title, skills)
        h = _login(client, email)
        data = _library(client, h, sid)
        assert data["scenarios"], title
        assert {sc["family"] for sc in data["scenarios"]} == {"generic"}
        assert not any(sc["family"] == "security" for sc in data["scenarios"])
        r = client.post(f"/api/students/{sid}/scenarios/suspicious-login-001/start", headers=h)
        assert r.status_code == 403, email


def test_blueprint_content_is_deterministic_and_role_scoped(client):
    skills = [("Patient Triage", "Intermediate"), ("Diagnostic Imaging", "Intermediate")]
    sid_a = _make_student("dent-a@student.edu", "General Dentist", skills)
    sid_b = _make_student("dent-b@student.edu", "General Dentist", skills)
    ha = _login(client, "dent-a@student.edu")
    hb = _login(client, "dent-b@student.edu")
    a = _library(client, ha, sid_a)["scenarios"]
    b = _library(client, hb, sid_b)["scenarios"]
    assert [sc["id"] for sc in a] == [sc["id"] for sc in b]
    card = a[0]
    assert card["role_title"] == "General Dentist"
    assert card["skills"], "blueprints embed the role's own required skills"


def test_target_change_swaps_library_but_keeps_progress(client):
    sid = _make_student("switcher@student.edu", "Data Analyst")
    h = _login(client, "switcher@student.edu")
    data = _library(client, h, sid)
    assert {sc["family"] for sc in data["scenarios"]} == {"data"}
    data_id = data["scenarios"][0]["id"]
    r = client.post(f"/api/students/{sid}/scenarios/{data_id}/start", headers=h)
    assert r.status_code == 200, r.text
    attempt_id = r.json()["attempt_id"]

    security = next((r for r in models.list_catalog_roles() if r["title"].strip().lower() == "cybersecurity analyst"), None)
    assert security, "seeded catalog SOC role must exist"
    models.update_student(sid, target_role_id=security["id"])

    data = _library(client, h, sid)
    assert {sc["family"] for sc in data["scenarios"]} == {"security"}
    assert not any(sc["id"] == data_id for sc in data["scenarios"])
    r = client.get(f"/api/students/{sid}/scenarios/attempts/{attempt_id}", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "in_progress"


# ------------------------------------------------------------- versioning

def test_cards_carry_family_fields_and_version(client):
    from app import scenarios as scn_mod
    h = _login(client, "yara@student.edu")
    user = models.get_session_user(_token(h)["token"])
    sid = models.get_student_by_user(user["id"])["id"]
    data = _library(client, h, sid)
    assert data["scenarios"]
    for card in data["scenarios"]:
        assert card["family"] == "security"
        assert card["family_label"] == scenario_catalog.FAMILY_LABEL_OF["security"]
        assert card["family_icon"] == scenario_catalog.FAMILY_ICON_OF["security"]
        assert card["version"] == scenario_catalog.SCENARIO_VERSION
    clone = scenario_catalog.build_blueprint_scenarios("R", ["Skill A"])[0]
    bp_card = scn_mod.public_scenario_card(
        clone,
        {"status": "not_started", "best_score": None, "attempts_count": 0, "last_outcome_title": None, "last_outcome_tone": None},
    )
    assert bp_card["family"] == "generic"
    assert bp_card["family_label"] == scenario_catalog.FAMILY_LABEL_OF["generic"]


# ------------------------------------------------------------ playability

@pytest.mark.parametrize("family,role_title,email", [
    ("ai", "Junior AI Engineer", "aisha@student.edu"),
    ("data", "Data Analyst", "leila@student.edu"),
    ("finance", "Financial Data Analyst", None),
])
def test_family_smoke_start_playable(client, family, role_title, email):
    if email:
        h = _login(client, email)
        user = models.get_session_user(_token(h)["token"])
        sid = models.get_student_by_user(user["id"])["id"]
    else:
        sid = _make_student(f"smoke-{family}@student.edu", role_title)
        h = _login(client, f"smoke-{family}@student.edu")
    data = _library(client, h, sid)
    fam_cards = [sc for sc in data["scenarios"] if sc["family"] == family]
    assert fam_cards
    r = client.post(f"/api/students/{sid}/scenarios/{fam_cards[0]['id']}/start", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "in_progress"


def _token(h):
    return {"token": h["Authorization"].split(" ", 1)[1]}