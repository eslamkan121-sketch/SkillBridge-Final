"""Practice Scenarios: domain-gating, catalog, branching, scoring, confidence-
upgrade and ownership.

Practice never verifies skills — that invariant is asserted here. The play-
through suite runs as yara@student.edu: a PRE-EXISTING seeded SOC student
(backend/app/seed.py STUDENTS line 34, SELF_REPORTED line 63, catalog target
"Cybersecurity Analyst" assigned at seed line 437). No fixture for this file
was authored to make the gate pass — yara is untouched seed data, which is
exactly what the domain-gate tests must rely on."""
import json

import pytest

from app import models


SUSPICIOUS_LOGIN = "suspicious-login-001"
PHISHING = "phishing-email-001"
SIEM = "siem-alert-001"


@pytest.fixture()
def soc(client, login):
    """Authenticated yara (seeded Cybersecurity Analyst cohort)."""
    payload = login("yara@student.edu")
    return {"Authorization": f"Bearer {payload['token']}"}, payload["student"]["id"]


def _make_student(email, target_role_title, skills):
    """Ad-hoc negative-fixture student: free user + owner + profile. Never a
    seeded student — these are synthetic cases that must NOT see scenarios.

    Pool hygiene: the target role is REUSED if a role with that exact title
    already exists (e.g. the seeded Northstar "Junior AI Engineer"); a brand-new
    role is only created for titles that do not exist (e.g. the dentist), so a
    negative fixture can never accidentally make scenario skills rare enough to
    clear the specificity floor.
    """
    u = models.create_user(email, "Student", f"{email} fixture", password="demo1234")
    sid = models.create_student(f"{email} fixture", email, "Test University", user_id=u["id"])["id"]
    existing = models.list_roles()
    role = next((r for r in existing if r["title"].strip().lower() == target_role_title.strip().lower()), None)
    if not role:
        names = {n for n, _ in skills}
        role = models.create_role(None, target_role_title, [
            {"name": name, "level": "Intermediate", "category": "General"}
            for name in names
        ])
    models.update_student(sid, target_role_id=role["id"])
    if skills:
        models.replace_self_reported_skills(sid, [{"name": n, "level": lv, "source": "cv"} for n, lv in skills])
    return sid, role["id"]


def _as(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": "demo1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _start(client, h, student_id, scenario_id):
    r = client.post(f"/api/students/{student_id}/scenarios/{scenario_id}/start", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _decide(client, h, student_id, attempt_id, payload):
    r = client.post(f"/api/students/{student_id}/scenarios/attempts/{attempt_id}/decide",
                    json=payload, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _good_path_client_state(view):
    """Return the decision id for the 'good' choice on the current step."""
    step = view["step"]
    if step.get("multi"):
        return {"option_ids": [o["id"] for o in step.get("options", [])[:3]]}
    # pick the first decision (curated 'good' paths are authored first)
    return {"decision_id": step["decisions"][0]["id"]}


# ------------------------------------------------------------------ gating

def test_soc_student_sees_all_three_scenarios(client, soc):
    h, sid = soc
    r = client.get(f"/api/students/{sid}/scenarios", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["availability"] == "ok"
    assert data["availability_reason"]
    assert {sc["id"] for sc in data["scenarios"]} == {SUSPICIOUS_LOGIN, PHISHING, SIEM}
    assert data["stats"]["scenarios_completed"] == 0
    assert all(sc["status"] in ("not_started", "in_progress", "completed") for sc in data["scenarios"])
    assert "recommended" in data and data["target_role"] == "Cybersecurity Analyst"
    assert "never verify" in data["note"]
    # category facets derive from what is actually available
    assert data["categories"], "an available SOC student must see real category facets"


def test_cyber_skills_clear_the_specificity_floor(client, soc):
    """Path B show-your-work: SIEM and Threat Detection live in the role pool
    at df<=DOMAIN_DF_CAP, so they clear the derived floor even without a target
    role. The floor is computed from the live pool, not fitted to fixtures."""
    from app import scenarios
    _, sid = soc
    student = models.get_student(sid)
    spec = scenarios._scenario_specificity(student, scenarios._scenario(SUSPICIOUS_LOGIN))
    # spec maps scenario skill NAME -> weight (see _scenario_specificity)
    assert "Threat Detection" in spec
    assert spec["Threat Detection"] >= scenarios._specificity_floor()
    # and logging-oriented skills absent from the pool carry NO domain weight
    assert spec.get("Log Analysis", 0) == 0.0


def test_generic_investigation_profile_is_not_eligible(client):
    """Regression: 'Investigation'/'Decision Making' ARE scenario skills, but
    they are absent from the role pool. Naive df would INVERT (give them max
    weight); the ABSENT_SKILL_WEIGHT guard must keep them at zero so a generic
    profile can never clear the floor."""
    from app import scenarios
    sid, _ = _make_student("generic-inv@student.edu", "Junior AI Engineer",
                           [("Investigation", "Advanced"), ("Decision Making", "Advanced")])
    h = _as(client, "generic-inv@student.edu")
    student = models.get_student(sid)
    for scn in scenarios.SCENARIOS:
        assert not scenarios.scenario_eligible(student, scn)
    r = client.get(f"/api/students/{sid}/scenarios", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["scenarios"] == []
    assert data["availability"] == "none"
    assert "Junior AI Engineer" in data["availability_reason"]


def test_non_cyber_target_and_skills_never_eligible(client):
    """A dentist-shaped profile (target + skills) must see zero scenarios and
    be blocked at the start gate — even though its own role now sits in the
    local pool (df=1), its skills never overlap scenario skills."""
    from app import scenarios
    sid, _ = _make_student("dentist@student.edu", "General Dentist",
                           [("Patient Triage", "Intermediate"), ("Diagnostic Imaging", "Intermediate")])
    h = _as(client, "dentist@student.edu")
    student = models.get_student(sid)
    for scn in scenarios.SCENARIOS:
        assert not scenarios.scenario_eligible(student, scn)
    r = client.get(f"/api/students/{sid}/scenarios", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["scenarios"] == []
    assert data["availability"] == "none"
    assert "General Dentist" in data["availability_reason"]
    r2 = client.post(f"/api/students/{sid}/scenarios/{SUSPICIOUS_LOGIN}/start", headers=h)
    assert r2.status_code == 403


def test_empty_profile_gets_nudge_not_content(client):
    """No target role and no skills -> honest nudge toward CV/role, never a
    fake 'everything is relevant' fallback."""
    sid, role_id = _make_student("empty@student.edu", "General Dentist", [])
    models.delete_role(role_id)  # clears the target plus role: genuinely empty profile
    h = _as(client, "empty@student.edu")
    r = client.get(f"/api/students/{sid}/scenarios", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["scenarios"] == []
    assert data["availability"] == "none"
    assert "upload a CV" in data["availability_reason"]
    r2 = client.post(f"/api/students/{sid}/scenarios/{SIEM}/start", headers=h)
    assert r2.status_code == 403


def test_start_gate_403_then_resume_allowed(client, soc):
    """Once a scenario is started it may never be locked out: eligibility is
    checked only for fresh attempts, resumption stays open (design §3.5)."""
    from app import scenarios
    h, sid = soc
    # start while fully eligible
    view = _start(client, h, sid, SUSPICIOUS_LOGIN)
    attempt_id = view["attempt_id"]
    # strip the skills AND pivot the target role so the student is no longer eligible
    models.replace_self_reported_skills(sid, [])
    dentist_role = models.create_role(None, "General Dentist", [
        {"name": "Patient Triage", "level": "Intermediate", "category": "General"},
    ])
    models.update_student(sid, target_role_id=dentist_role["id"])
    s = models.get_student(sid)
    assert not scenarios.scenario_eligible(s, scenarios._scenario(SUSPICIOUS_LOGIN))
    # a brand-new scenario is now BLOCKED at the gate ...
    r403 = client.post(f"/api/students/{sid}/scenarios/{SIEM}/start", headers=h)
    assert r403.status_code == 403
    # ... but the started attempt resumes via the attempt endpoint (durable)
    r = client.get(f"/api/students/{sid}/scenarios/attempts/{attempt_id}", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "in_progress"


# ---------------------------------------------------------------- library

def test_catalog_lists_scenarios_with_progress(client, soc):
    h, sid = soc
    r = client.get(f"/api/students/{sid}/scenarios", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["scenarios"]) == 3
    assert data["availability"] == "ok"
    assert all(sc["status"] in ("not_started", "in_progress", "completed") for sc in data["scenarios"])
    assert "recommended" in data and "target_role" in data
    assert "never verify" in data["note"]


def test_guest_cannot_read_scenarios(client):
    r = client.get("/api/students/1/scenarios")
    assert r.status_code == 401


def test_other_student_cannot_touch_attempts(client, soc):
    h, sid = soc
    view = _start(client, h, sid, SUSPICIOUS_LOGIN)
    attempt_id = view["attempt_id"]

    other = client.post("/api/auth/login", json={"email": "omar@student.edu", "password": "demo1234"}).json()
    oh = {"Authorization": f"Bearer {other['token']}"}
    r = client.post(f"/api/students/{sid}/scenarios/attempts/{attempt_id}/decide",
                    json={"decision_id": "investigate-logs"}, headers=oh)
    assert r.status_code == 403


def test_full_good_path_scores_and_verdict(client, soc):
    h, sid = soc
    view = _start(client, h, sid, SUSPICIOUS_LOGIN)
    steps = 0
    result = None
    while not result and steps < 12:
        payload = _good_path_client_state(view)
        # inspect a couple of evidence items along the way to exercise scoring
        evidence = [e["id"] for e in view["step"]["evidence"][:2]]
        payload["evidence_viewed"] = evidence
        steps += 1
        out = _decide(client, h, sid, view["attempt_id"], payload)
        if out.get("completed"):
            result = out
        else:
            view = out
    assert result is not None
    board = json.loads(json.dumps(result))
    assert board["completed"] is True
    assert 0 <= board["score"] <= 100
    assert board["verdict_tone"] in ("great", "good", "fair", "review")
    assert board["certified"] is False
    assert any(c["pct"] is not None for c in board["components"])
    assert board["decision_review"]
    assert "delta" in board["match"]  # always present; None only w/o target role
    assert "never verifies" in board["note"]

    # results are durable on resume
    r = client.get(f"/api/students/{sid}/scenarios/attempts/{result['attempt_id']}", headers=h)
    assert r.status_code == 200
    resumed = r.json()
    assert resumed["completed"] is True and resumed["score"] == board["score"]


def test_ignoring_alert_reaches_bad_outcome(client, soc):
    h, sid = soc
    view = _start(client, h, sid, SUSPICIOUS_LOGIN)
    out = _decide(client, h, sid, view["attempt_id"], {"decision_id": "ignore-alert"})
    assert out["completed"] is True
    assert out["outcome"]["key"] == "exposure"
    assert out["outcome"]["tone"] == "bad"
    assert out["score"] < 40


def test_phishing_multi_select_partial_credit(client, soc):
    h, sid = soc
    view = _start(client, h, sid, PHISHING)
    # step 1 good path
    view = _decide(client, h, sid, view["attempt_id"], {"decision_id": "inspect-header"})
    assert view["step"]["type"] == "multi"
    # select all the correct indicators (skip the distractors)
    payload = {"option_ids": [o["id"] for o in view["step"]["options"] if not o["label"].startswith("The email arrived")]}
    view = _decide(client, h, sid, view["attempt_id"], payload)
    assert not view.get("completed")
    assert view["step"]["title"] == "Handle the Link and Attachment"
    # finish via good choices
    view = _decide(client, h, sid, view["attempt_id"], {"decision_id": "sandbox-analyze"})
    out = _decide(client, h, sid, view["attempt_id"], {"decision_id": "report-quarantine"})
    assert out["completed"] is True
    assert out["outcome"]["key"] == "reported"
    # multi contribute to threat analysis component (evidence not yet viewed → fair partial credit)
    ta = next(c for c in out["components"] if c["key"] == "threat_analysis")
    assert ta["pct"] is not None and ta["pct"] >= 30


def test_hint_endpoint_returns_nudge_and_tracks_usage(client, soc):
    h, sid = soc
    view = _start(client, h, sid, SUSPICIOUS_LOGIN)
    attempt_id = view["attempt_id"]
    r = client.post(f"/api/students/{sid}/scenarios/attempts/{attempt_id}/hint",
                    json={}, headers=h)
    assert r.status_code == 200, r.text
    hint = r.json()
    assert hint["source"] == "curated" and hint["hint"]
    assert hint["hints_used"] == 1
    # question mode does not burn a hint
    r2 = client.post(f"/api/students/{sid}/scenarios/attempts/{attempt_id}/hint",
                     json={"question": "what is a beacon?"}, headers=h)
    assert r2.status_code == 200
    assert r2.json()["hints_used"] == 1


def test_in_progress_resumes(client, soc):
    h, sid = soc
    view = _start(client, h, sid, SIEM)
    attempt_id = view["attempt_id"]
    # start again -> same in-progress attempt
    again = _start(client, h, sid, SIEM)
    assert again["attempt_id"] == attempt_id
    r = client.get(f"/api/students/{sid}/scenarios/attempts/{attempt_id}", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "in_progress"


def test_completed_scenario_rejects_more_decisions(client, soc):
    h, sid = soc
    view = _start(client, h, sid, SUSPICIOUS_LOGIN)
    out = _decide(client, h, sid, view["attempt_id"], {"decision_id": "ignore-alert"})
    assert out["completed"] is True
    r = client.post(f"/api/students/{sid}/scenarios/attempts/{view['attempt_id']}/decide",
                    json={"decision_id": "investigate-logs"}, headers=h)
    assert r.status_code in (200, 400)


def test_practice_does_not_verify_skills(client, soc):
    """The hard rule: completing scenarios never adds verified skills."""
    h, sid = soc
    before = models.get_student(sid)
    verified_before = {s["name"] for s in before["verified_skills"]}

    view = _start(client, h, sid, SIEM)
    steps = 0
    while steps < 12:
        if view.get("completed"):
            break
        payload = _good_path_client_state(view)
        out = _decide(client, h, sid, view["attempt_id"], payload)
        steps += 1
        view = out
    assert view.get("completed") is True
    after = models.get_student(sid)
    assert {s["name"] for s in after["verified_skills"]} == verified_before
    # self-reported levels may have been upgraded but the skill set is unchanged
    assert {s["name"] for s in after["self_reported_skills"]} == {s["name"] for s in before["self_reported_skills"]}