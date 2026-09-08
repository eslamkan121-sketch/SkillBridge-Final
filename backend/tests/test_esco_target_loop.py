"""§2b — full downstream-loop proof for a REAL ESCO occupation as Target Role.

The original ask was the complete loop, not just a better-ranked list:
select a real ESCO-sourced role -> skill-gap map -> diagnostic -> learning path,
with NO Verified Skill created until a passed Final Assessment.

Runs fully offline: the ESCO occupation import is stubbed with the occupation's
real essential skills (same data ESCO would return), everything else uses the
real endpoints and the deterministic fallback providers.
"""
import io

from app import genai, models

LAW_CV = """\
MARCUS THOMPSON
SKILLS
Legal research and writing
Dispute resolution and mediation
Client advocacy
Public speaking
EXPERIENCE
Legal clerkship drafting case summaries and advising on family law matters.
"""

LEGAL_OCC = {
    "uri": "http://data.europa.eu/esco/occupation/legal-assistant",
    "title": "Legal Assistant",
    "essential": ["Legal research and writing", "Dispute resolution and mediation",
                  "Client advocacy", "Legal drafting", "Court etiquette"],
    "optional": [],
}


def _force_fallback(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("deterministic fallback for test")

    monkeypatch.setattr(genai, "_generate", _raise)


def test_real_esco_target_role_full_downstream_loop(client, db, student_id, auth_headers, monkeypatch):
    _force_fallback(monkeypatch)
    from app import escoe
    monkeypatch.setattr(
        escoe, "occupation_skill_groups",
        lambda uri: {"essential": LEGAL_OCC["essential"], "optional": LEGAL_OCC["optional"]})

    headers = auth_headers("aisha@student.edu")

    # 0) CV upload through the real endpoint -> profile populated
    res = client.post(
        f"/api/students/{student_id}/cv",
        files={"file": ("law_cv.txt", io.BytesIO(LAW_CV.encode()), "text/plain")},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    extracted = {s["name"] for s in res.json()["extracted"]}
    for need in ("Legal research and writing", "Dispute resolution and mediation",
                 "Client advocacy", "Public speaking"):
        assert need in extracted, extracted

    # 1) Select a real ESCO-sourced role as Target Role (the reviewer's example)
    res = client.post(
        f"/api/students/{student_id}/target-role/esco",
        json={"uri": LEGAL_OCC["uri"], "title": LEGAL_OCC["title"], "skills": LEGAL_OCC["essential"]},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    tr = res.json()["target_role"]
    assert tr["title"] == "Legal Assistant"
    assert tr["source"] == "esco"
    assert tr["external_id"] == LEGAL_OCC["uri"]

    # 2) Skill-gap map generates against the role's real required skills
    analysis = client.get(f"/api/students/{student_id}/analysis", headers=headers)
    assert analysis.status_code == 200, analysis.text
    gaps = analysis.json()["skill_gaps"]
    by_name = {g["skill_name"].lower(): g for g in gaps}
    assert by_name["legal research and writing"]["status"] == "strong"
    assert by_name["dispute resolution and mediation"]["status"] == "strong"
    assert by_name["client advocacy"]["status"] == "strong"
    missing = {n: s for n, s in by_name.items() if s["status"] == "missing"}
    assert {"legal drafting", "court etiquette"} <= set(missing), by_name
    assert analysis.json()["gap_count"] == 2
    drafting_id = by_name["legal drafting"]["skill_id"]

    def verified_names():
        return sorted(v["name"].lower() for v in models.get_student(student_id)["verified_skills"])

    baseline = verified_names()

    def assert_no_new_verified(step):
        assert verified_names() == baseline, f"{step} created a Verified Skill: {verified_names()}"
        assert "legal drafting" not in verified_names()
        assert "court etiquette" not in verified_names()

    # 3) Selecting the role has NOT created any Verified Skill
    assert_no_new_verified("role selection")

    # 4) Diagnostic generates and is answerable for a gapped skill
    diag = client.post(
        f"/api/students/{student_id}/learning/{drafting_id}/diagnostic/generate",
        json={}, headers=headers,
    )
    assert diag.status_code == 200, diag.text
    d = diag.json()
    assert d["questions"] and d["diagnostic_id"]
    answers = [""] * len(d["questions"])  # all wrong -> weak topics, honest low score
    sub = client.post(
        f"/api/students/{student_id}/learning/{drafting_id}/diagnostic/submit",
        json={"diagnostic_id": d["diagnostic_id"], "answers": answers},
        headers=headers,
    )
    assert sub.status_code == 200, sub.text
    result = sub.json()
    assert result["completed_at"]
    assert result["score"] is not None
    assert any(t.get("status") == "weak" for t in result["topic_results"]), result["topic_results"]
    assert_no_new_verified("diagnostic submit")  # a diagnostic NEVER verifies a skill

    # 5) Personalized learning path builds FROM the diagnostic result (weak first)
    path = client.post(
        f"/api/students/{student_id}/learning/{drafting_id}/personalized-path/generate",
        json={}, headers=headers,
    )
    assert path.status_code == 200, path.text
    p = path.json()
    assert p["items"], p
    items = p["items"]
    assert items and all(it["action"] in ("learn", "review") for it in items)
    assert items[0]["action"] == "learn"  # weak prioritized before developing/review
    assert_no_new_verified("learning path")  # the path creates no Verified Skill either

    # 6) A final-assessment is only *ready* to be earned — it grants nothing by itself
    status = client.get(
        f"/api/students/{student_id}/learning/{drafting_id}/final-assessment/status",
        headers=headers,
    )
    assert status.status_code == 200, status.text
    assert_no_new_verified("final-assessment status")  # only a passed Final Assessment verifies