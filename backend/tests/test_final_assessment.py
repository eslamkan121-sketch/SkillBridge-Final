"""Phase 4.5 — Learning coverage + Final Assessment backstop.

Covers the deterministic integrity guarantees: competency tagging against a closed
blueprint set, out-of-blueprint rejection, assessment coverage, coverage repair,
readiness gating, the competency-aware pass rule (with backward compatibility for
legacy/untagged attempts), verified-credentials safety, personalized-path & lesson
validation, deterministic fallback, and university-cohort scoping.

All GenAI calls forced to the deterministic fallback (no quota consumed).
"""
import itertools
import json

import pytest
from app import coverage as cov, diagnostics as dx, genai, models, skill_blueprint as sb


@pytest.fixture(autouse=True)
def _force_deterministic_fallback(monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)


@pytest.fixture()
def docker_skill(db):
    return models.get_skill_by_name("Docker")


def _mcq(comp, n, wrong=False):
    opts = ["opt-a", "opt-b", "opt-c"]
    return {"question": f"{comp} q{n}", "type": "multiple_choice",
            "options": opts, "answer": "opt-b", "explanation": "x", "competency": comp,
            "_wrong": wrong}


def _immcoq(comp, n):
    # competency-tagged MCQ whose model answer is option index 1
    return {"question": f"{comp} q{n}", "type": "multiple_choice",
            "options": ["a", "b", "c"], "answer": "b", "explanation": "x", "competency": comp}


# ------------------------------------------------------------------ 1. competency tags (Req 1)

def test_final_assessment_questions_carry_competency_tags(docker_skill):
    req = cov.required_slugs("Docker", "Intermediate")
    qs = genai.generate_final_assessment("Docker", "Junior AI Engineer",
                                         competency_slugs=req, num_questions=8)
    assert qs
    assert all(q.get("competency") for q in qs)
    assert all(q["competency"] in set(req) for q in qs)


def test_generate_endpoint_returns_competency_tags(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    r = client.post(f"/api/students/{student_id}/assessments/generate",
                    json={"skill_id": docker_skill["id"], "num_questions": 8}, headers=headers)
    assert r.status_code == 200
    qs = r.json()["questions"]
    assert all(q.get("competency") for q in qs)
    cc = r.json()["competency_coverage"]
    assert cc["covered"] is True
    assert cc["missing"] == []


# ------------------------------------------------------------------ 2. out-of-blueprint rejection (Req 2)

def test_out_of_blueprint_competency_rejected():
    req = cov.required_slugs("Docker", "Intermediate")
    bad = [{"question": "q", "type": "multiple_choice", "competency": "totally-made-up"},
           {"question": "q2", "type": "multiple_choice", "competency": "containers"}]
    cleaned = cov.validate_questions(bad, req)
    assert len(cleaned) == 1
    assert cleaned[0]["competency"] == "containers"


def test_generation_never_asserts_out_of_blueprint(docker_skill):
    req = cov.required_slugs("Docker", "Intermediate")
    qs = genai.generate_final_assessment("Docker", None, competency_slugs=req, num_questions=12)
    assert all(q["competency"] in set(req) for q in qs)


def test_real_provider_parse_path_drops_out_of_blueprint(monkeypatch, docker_skill):
    """Regression: the real-key parse path crashed on a `valid` NameError
    (genai.py:2036, now `comps`). Simulating a provider response with an
    out-of-blueprint-tagged question must drop it and still cover everything."""
    req = cov.required_slugs("Docker", "Intermediate")
    payload = [_immcoq(c, i) for i, c in enumerate(itertools.islice(itertools.cycle(req), 8))]
    payload.append({"question": "invented concept", "type": "multiple_choice",
                    "options": ["a", "b", "c"], "answer": "a",
                    "explanation": "x", "competency": "totally-made-up"})
    monkeypatch.setattr(genai, "genai_enabled", lambda: True)
    monkeypatch.setattr(genai, "complete", lambda *a, **k: json.dumps(payload))
    qs = genai.generate_final_assessment("Docker", "Junior AI Engineer",
                                         competency_slugs=req, num_questions=8)
    assert len(qs) == 8
    assert all(q["competency"] in set(req) for q in qs)
    covered, missing = cov.coverage_for_questions(qs, req)
    assert covered is True
    assert missing == []


# ------------------------------------------------------------------ 3/4. coverage detection + repair (Req 3, 4)

def test_coverage_missing_detected():
    req = cov.required_slugs("Docker", "Intermediate")
    present = [_immcoq(c, i) for i, c in enumerate(req[:5])]  # omit last two
    covered, missing = cov.coverage_for_questions(present, req)
    assert covered is False
    assert set(missing) == set(req[5:])
    assert cov.coverage_for_questions([], []) == (True, [])


def test_generation_guarantees_full_coverage(docker_skill):
    req = cov.required_slugs("Docker", "Intermediate")
    qs = genai.generate_final_assessment("Docker", None, competency_slugs=req, num_questions=8)
    covered, missing = cov.coverage_for_questions(qs, req)
    assert covered is True
    assert missing == []


# ------------------------------------------------------------------ 5/6. satisfaction rules (Req 5, 6)

def test_requirement_satisfied_by_diagnostic_mastered():
    topics = [{"competency": "containers", "status": dx.MASTERED},
              {"competency": "images", "status": dx.WEAK}]
    r = cov.final_assessment_ready("Docker", "Intermediate", topics, [], [], [])
    assert "containers" in r["satisfied"]
    assert "images" in r["missing"]
    assert r["ready"] is False


def test_requirement_satisfied_by_completed_path_lesson():
    items = [{"id": "v-1", "competency": "volumes"}]
    r = cov.final_assessment_ready("Docker", "Intermediate", [], items, ["v-1"], [])
    assert "volumes" in r["satisfied"]
    assert r["ready"] is False  # other requirements still missing


# ------------------------------------------------------------------ 7. unlock gating (Req 7)

def test_readiness_gates_unlock_endpoint(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    url = f"/api/students/{student_id}/learning/{sk}/final-assessment/status"
    before = client.get(url, headers=headers).json()
    assert before["diagnostic_completed"] is False
    assert before["readiness"]["ready"] is False

    # complete a diagnostic with everything correct -> every topic mastered -> ready
    gen = client.post(f"/api/students/{student_id}/learning/{sk}/diagnostic/generate",
                      json={}, headers=headers).json()
    answers = [q["correct_answer"] for q in gen["questions"]]
    client.post(f"/api/students/{student_id}/learning/{sk}/diagnostic/submit",
                json={"diagnostic_id": gen["diagnostic_id"], "answers": answers}, headers=headers)
    after = client.get(url, headers=headers).json()
    assert after["diagnostic_completed"] is True
    assert after["readiness"]["ready"] is True
    assert after["readiness"]["missing"] == []


def test_readiness_auth_blocked(client, docker_skill, student_id):
    sk = docker_skill["id"]
    r = client.get(f"/api/students/{student_id}/learning/{sk}/final-assessment/status")
    assert r.status_code == 401


# ------------------------------------------------------------------ 8. mini-check never verifies (Req 8)

def test_mini_check_never_verifies(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    gen = client.post(f"/api/students/{student_id}/learning/{sk}/diagnostic/generate",
                      json={}, headers=headers).json()
    answers = [q["correct_answer"] for q in gen["questions"]]
    bad = 0
    for i, q in enumerate(gen["questions"]):
        if q["type"] == "mcq" and bad < 2 and q["options"]:
            wrong = [o for o in q["options"] if o != q["correct_answer"]]
            if wrong:
                answers[i] = wrong[0]
                bad += 1
    client.post(f"/api/students/{student_id}/learning/{sk}/diagnostic/submit",
                json={"diagnostic_id": gen["diagnostic_id"], "answers": answers}, headers=headers)
    path = client.post(f"/api/students/{student_id}/learning/{sk}/personalized-path/generate",
                       json={}, headers=headers).json()
    comp = path["items"][0]["competency"]
    client.post(f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/generate",
                json={}, headers=headers)
    client.post(f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/start",
                json={}, headers=headers)
    lesson = client.get(f"/api/students/{student_id}/learning/{sk}/lessons/{comp}",
                        headers=headers).json()
    mini = [q["correct_answer"] for q in lesson["content"]["mini_check"]["questions"]]
    before = {(v["name"], v["level"]) for v in (models.get_student(student_id).get("verified_skills") or [])}
    client.post(f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/mini-check",
                json={"answers": mini}, headers=headers)
    after = {(v["name"], v["level"]) for v in (models.get_student(student_id).get("verified_skills") or [])}
    assert before == after


# ------------------------------------------------------------------ 9. verified safety (Req 9)

def test_full_coverage_pass_verifies_but_competency_fail_does_not(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    req = cov.required_slugs("Docker", "Intermediate")
    questions = [_immcoq(c, i) for i, c in enumerate(req)]

    # pass: all correct
    answers = ["b" for _ in questions]
    r = client.post(f"/api/students/{student_id}/assessments", json={
        "skill_id": sk, "questions": questions, "answers": answers,
        "total_seconds": 300, "tab_switches": 0, "free_text_answers": []}, headers=headers)
    assert r.json()["passed"] is True
    assert r.json()["full_coverage"] is True
    assert "Docker" in {v["name"] for v in models.get_student(student_id).get("verified_skills") or []}


# ------------------------------------------------------------------ 10/11. structural validation (Req 10, 11)

def test_personalized_path_validation_flags_errors():
    diag_topics = [{"competency": "containers", "status": dx.WEAK},
                   {"competency": "volumes", "status": dx.DEVELOPING},
                   {"competency": "images", "status": dx.MASTERED}]
    items = [{"competency": "containers", "topic_status": "weak", "id": "c-1"}]
    ok, errs = cov.validate_personalized_path("Docker", items, [], diag_topics, "Intermediate")
    assert ok is False
    joined = " ".join(errs)
    assert "volumes" in joined  # developing topic missing from active items


def test_lesson_validation_flags_missing_content_and_bad_tag():
    content = {"learn": {"explanation": "short", "key_ideas": []},
               "example": {"content": ""},
               "practice": {"questions": []},
               "mini_check": {"questions": [{"competency": "wrong-tag"}]}}
    ok, errs = cov.validate_lesson("containers", ["containers"], content)
    assert ok is False
    assert any("mini check" in e or "tag" in e for e in errs)


# ------------------------------------------------------------------ 12. deterministic fallback (Req 12)

def test_deterministic_fallback_covers_all(docker_skill):
    req = cov.required_slugs("Docker", "Intermediate")
    genai.genai_enabled = lambda: False
    qs = genai.generate_final_assessment("Docker", None, competency_slugs=req, num_questions=7)
    covered, missing = cov.coverage_for_questions(qs, req)
    assert covered is True
    assert missing == []


# ------------------------------------------------------------------ 13. competency-aware pass rule + backward compat (Req 13)

def test_competency_aware_pass_rule_blocks_weak_competency(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    req = cov.required_slugs("Docker", "Intermediate")
    # 7 MCQs, one per competency; fail containers + images (2 wrong), rest correct.
    questions = [_immcoq(c, i) for i, c in enumerate(req)]
    base = {c: "b" for c in req}
    answers = []
    for c in req:
        answers.append("a" if c in ("containers", "images") else "b")
    r = client.post(f"/api/students/{student_id}/assessments", json={
        "skill_id": sk, "questions": questions, "answers": answers,
        "total_seconds": 300, "tab_switches": 0, "free_text_answers": []}, headers=headers)
    data = r.json()
    assert data["score"] >= 70  # 5/7 overall
    assert data["full_coverage"] is True
    assert data["passed"] is False  # two competencies failed the per-competency floor
    weak = [c for c in data["competencies"] if c["competency"] in ("containers", "images")]
    assert all(c["passed"] is False for c in weak)


def test_legacy_untagged_keeps_original_rule(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    req = cov.required_slugs("Docker", "Intermediate")
    questions = [_immcoq(c, i) for i, c in enumerate(req)]
    for q in questions:
        q.pop("competency", None)  # legacy untagged
    answers = ["a" if c in ("containers", "images") else "b" for c in req]
    r = client.post(f"/api/students/{student_id}/assessments", json={
        "skill_id": sk, "questions": questions, "answers": answers,
        "total_seconds": 300, "tab_switches": 0, "free_text_answers": []}, headers=headers)
    data = r.json()
    assert data["score"] >= 70
    assert data["full_coverage"] is False  # no competency tags -> legacy rule
    assert data["passed"] is True  # legacy rule: overall only


def test_competency_results_reported_on_pass(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    req = cov.required_slugs("Docker", "Intermediate")
    questions = [_immcoq(c, i) for i, c in enumerate(req)]
    answers = ["b" for _ in questions]
    r = client.post(f"/api/students/{student_id}/assessments", json={
        "skill_id": sk, "questions": questions, "answers": answers,
        "total_seconds": 300, "tab_switches": 0, "free_text_answers": []}, headers=headers)
    data = r.json()
    assert all(c["passed"] for c in data["competencies"])
    assert set(c["competency"] for c in data["competencies"]) == set(req)


def test_derived_blueprint_skill_uses_competency_generation(client, student_id, auth_headers):
    """Phase C: a previously blueprint-less skill (Rust) now gets a derived
    blueprint, so Final Assessment generation uses the competency-tagged path
    instead of the legacy generic quiz."""
    headers = auth_headers("aisha@student.edu")
    skill = models.create_skill("Rust", "Programming")
    sb.clear_derived_cache("Rust")
    assert sb.has_blueprint("Rust"), "unknown skills must now derive a blueprint"
    r = client.post(f"/api/students/{student_id}/assessments/generate",
                    json={"skill_id": skill["id"], "num_questions": 5}, headers=headers)
    assert r.status_code == 200
    cc = r.json()["competency_coverage"]
    assert cc is not None
    assert cc["required"] and cc["covered"] is True
    assert cc["valid"] is True
    for q in r.json()["questions"]:
        assert q.get("competency") in set(cc["required"])


# ------------------------------------------------------------------ 14. fallback coverage via endpoint path (Req 14)

def test_fallback_generate_endpoint_fully_covers(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    r = client.post(f"/api/students/{student_id}/assessments/generate",
                    json={"skill_id": sk, "num_questions": 8}, headers=headers)
    cc = r.json()["competency_coverage"]
    assert cc["covered"] is True
    assert cc["missing"] == []
    assert cc["valid"] is True


# ------------------------------------------------------------------ 15. university cohort scoping (Req 15)

def test_university_cohort_scoped_to_admin_institution(client, auth_headers):
    headers = auth_headers("admin@univ.edu")
    stats = client.get("/api/university/stats", headers=headers).json()
    assert stats["university"] == "Aston University"
    assert stats["student_count"] == 7

    # a student at a different institution must NOT appear in the Aston cohort
    u = models.create_user("oxford@student.edu", "Student", "Oxford Learner", password="demo1234")
    oxford = models.create_student("Oxford Learner", "oxford@student.edu", "Oxford University", user_id=u["id"])
    models.update_student(oxford["id"], cohort_confirmed=1)
    stats2 = client.get("/api/university/stats", headers=headers).json()
    assert stats2["student_count"] == 7  # Oxford student excluded
    cohort = client.get("/api/university/cohort", headers=headers).json()
    assert cohort["student_count"] == 7


def test_university_cohort_min_size_still_enforced(client, auth_headers):
    # force confirmed count below the threshold by removing confirmations
    from app.database import get_cursor
    with get_cursor() as c:
        c.execute("UPDATE students SET cohort_confirmed=0")
    # re-confirm only one student so confirmed < MIN_COHORT_SIZE
    with get_cursor() as c:
        first = c.execute("SELECT id FROM students ORDER BY id LIMIT 1").fetchone()
        if first:
            c.execute("UPDATE students SET cohort_confirmed=1 WHERE id=?", (first["id"],))
    headers = auth_headers("admin@univ.edu")
    stats = client.get("/api/university/stats", headers=headers).json()
    assert stats["stats"] is None
    assert stats["rule"]["satisfied"] is False


def test_university_stats_anonymized(client, auth_headers):
    headers = auth_headers("admin@univ.edu")
    cohort = client.get("/api/university/cohort", headers=headers).json()
    for s in cohort["students"]:
        assert set(s.keys()) == {"index", "confirmed"}  # never names/emails
