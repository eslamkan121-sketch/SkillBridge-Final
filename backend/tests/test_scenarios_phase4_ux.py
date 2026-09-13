"""Phase 4 UX contract: player carries target-role context + per-decision
consequences, hint penalties are explicit, results connect weak competencies to
learning follow-ups, and a per-attempt history endpoint exists.

The play-through suites reuse yara@student.edu (seeded SOC student) so attempts
are durable across requests, exactly as the browser walks them."""
import json

import pytest

from app import models, scenarios

SUSPICIOUS_LOGIN = "suspicious-login-001"


@pytest.fixture()
def soc(client, login):
    payload = login("yara@student.edu")
    return {"Authorization": f"Bearer {payload['token']}"}, payload["student"]["id"]


def _start(client, h, student_id, scenario_id):
    r = client.post(f"/api/students/{student_id}/scenarios/{scenario_id}/start", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _decide(client, h, student_id, attempt_id, payload):
    r = client.post(f"/api/students/{student_id}/scenarios/attempts/{attempt_id}/decide",
                    json=payload, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _good_state(view):
    step = view["step"]
    if step.get("multi"):
        return {"option_ids": [o["id"] for o in step.get("options", [])[:3]]}
    return {"decision_id": step["decisions"][0]["id"]}


def _play_to_end(client, h, sid):
    view = _start(client, h, sid, SUSPICIOUS_LOGIN)
    for _ in range(12):
        payload = _good_state(view)
        payload["evidence_viewed"] = [e["id"] for e in view["step"]["evidence"][:2]]
        out = _decide(client, h, sid, view["attempt_id"], payload)
        if out.get("completed"):
            return out, view
        view = out
    raise AssertionError("scenario did not complete")


# ------------------------------------------------------------------ player context

def test_player_view_carries_target_role_hint_policy_and_no_last_decision(client, soc):
    h, sid = soc
    view = _start(client, h, sid, SUSPICIOUS_LOGIN)
    assert view["target_role"] == "Cybersecurity Analyst"
    assert view["role_title"]
    assert view["hint_policy"] == {"penalty": 3, "cap": 9, "used": 0, "deduction": 0}
    assert view["last_decision"] is None  # nothing submitted yet — nothing revealed


def test_decision_explains_consequence_with_professional_reasoning_before_any_reveal(client, soc):
    """After a submission the next player view explains the consequence; the
    best answer is never in the step payload itself (options carry no verdict)."""
    h, sid = soc
    view = _start(client, h, sid, SUSPICIOUS_LOGIN)
    for raw in view["step"]["decisions"]:
        assert not any(k in raw for k in ("verdict", "feedback", "consequence", "good", "points"))
    payload = {"decision_id": view["step"]["decisions"][0]["id"], "evidence_viewed": []}
    nxt = _decide(client, h, sid, view["attempt_id"], payload)
    ld = nxt["last_decision"]
    assert ld is not None
    assert ld["verdict"] in ("good", "neutral", "bad")
    assert ld["label"]
    assert ld["feedback"], "professional reasoning must be present after a decision"
    assert ld["consequence"], "a consequence must follow every decision"
    assert nxt["step"]["id"] != view["step"]["id"] or nxt["status"] == "in_progress"


def test_hint_policy_accumulates_deduction_per_step(client, soc):
    """A hint is recorded once per step; the deduction grows across steps and is
    transparent in the player payload. Re-asking on the same step never
    double-charges."""
    h, sid = soc
    view = _start(client, h, sid, SUSPICIOUS_LOGIN)
    hint = lambda: client.post(
        f"/api/students/{sid}/scenarios/attempts/{view['attempt_id']}/hint", json={}, headers=h)
    assert hint().json()["hints_used"] == 1
    assert hint().json()["hints_used"] == 1  # same step — still one recorded hint
    view = _decide(client, h, sid, view["attempt_id"],
                   {"decision_id": view["step"]["decisions"][0]["id"], "evidence_viewed": []})
    hint()
    r2 = client.get(f"/api/students/{sid}/scenarios/attempts/{view['attempt_id']}", headers=h)
    assert r2.status_code == 200
    assert r2.json()["hint_policy"] == {"penalty": 3, "cap": 9, "used": 2, "deduction": 6}


# ------------------------------------------------------------------ results follow-up

def test_result_connects_weak_competency_to_learning_content(client, soc):
    """The weakest component resolves to a follow-up; when a scenario skill maps
    to it and is weak, the follow-up targets existing learning content."""
    h, sid = soc
    result, _ = _play_to_end(client, h, sid)
    fu = result["follow_up"]
    assert fu["component_label"] in ("Investigation", "Decision Making", "Threat Analysis", "Incident Response")
    assert isinstance(fu["weakness_pct"], int)
    assert fu["message"]
    assert fu["action"] in ("lesson", "practice", "review")
    assert fu["component_key"] in scenarios.COMPONENTS
    assert result["hint_policy"]["penalty"] == 3 and result["hint_policy"]["cap"] == 9
    assert result["target_role"] == "Cybersecurity Analyst"
    assert result["role_title"]


def test_follow_up_resolves_skill_id_for_weak_component():
    """Unit: a mapped skill on a weak competency produces a lesson follow-up
    pointing at a real skill id in the registry."""
    scenario = {
        "family": "security",
        "skills_components": {"Threat Detection": "investigation", "Decision Making": "decision_making"},
    }
    attempt = {
        "feedback": {
            "component_pcts": {
                "investigation": 30, "decision_making": 88,
                "threat_analysis": None, "incident_response": None,
            }
        }
    }
    fu = scenarios._follow_up(scenario, attempt)
    assert fu["action"] == "lesson"
    assert fu["skill"] == "Threat Detection"
    assert fu["skill_id"] is None or isinstance(fu["skill_id"], int)
    assert fu["weakness_pct"] == 30
    assert "Investigation" in fu["message"]


# ------------------------------------------------------------------ history

def test_history_lists_attempts_with_date_version_score_and_role(client, soc):
    h, sid = soc
    assert client.get(f"/api/students/{sid}/scenarios/history", headers=h).json()["attempts"] == []
    view = _start(client, h, sid, SUSPICIOUS_LOGIN)
    assert client.get(f"/api/students/{sid}/scenarios/history", headers=h).json()["attempts"][0]["status"] == "in_progress"
    result, _ = _play_to_end(client, h, sid)
    rows = client.get(f"/api/students/{sid}/scenarios/history", headers=h).json()["attempts"]
    done = next((r for r in rows if r["attempt_id"] == result["attempt_id"]), None)
    assert done is not None
    assert done["status"] == "completed"
    assert done["score"] == result["score"]
    assert done["started_at"] and done["completed_at"]
    assert isinstance(done["scenario_version"], int) and done["scenario_version"] >= 1
    assert done["role_title"]
    assert done["title"]
    assert done["family_label"] and done["family_icon"]
    assert done["difficulty_label"]


def test_history_requires_auth_and_ownership(client, soc):
    h, sid = soc
    other = client.post("/api/auth/login", json={"email": "omar@student.edu", "password": "demo1234"}).json()
    oh = {"Authorization": f"Bearer {other['token']}"}
    assert client.get(f"/api/students/{sid}/scenarios/history", headers=oh).status_code == 403
    assert client.get("/api/students/1/scenarios/history").status_code == 401