"""Phase 3 — Job Match Score and Skill Gap analysis."""
from app import models, matching


def _make_role(student_db, title="Role", skills=None):
    comp = models.create_company("C", "I")
    role = models.create_role(comp["id"], title, skills or [
        {"name": "Python", "category": "Programming", "level": "Advanced"},
        {"name": "Docker", "category": "DevOps", "level": "Intermediate"},
        {"name": "SQL", "category": "Data", "level": "Advanced"},
    ])
    return role


def test_categorize_strong_gap_missing(db):
    student = models.create_student("S", "s@test.edu", "U")
    models.replace_self_reported_skills(student["id"], [
        {"name": "Python", "level": "Advanced"},
        {"name": "Docker", "level": "Beginner"},
    ])
    role = _make_role(student)
    student = models.get_student(student["id"])
    model = matching.categorize(student, role)
    by = {r["skill_name"]: r["status"] for r in model}
    assert by["Python"] == "strong"      # Advanced meets Advanced
    assert by["Docker"] == "gap"          # Beginner below Intermediate
    assert by["SQL"] == "missing"         # absent


def test_match_score_full_partial_zero(db):
    student = models.create_student("S", "s@test.edu", "U")
    # No skills
    role = _make_role(student, skills=[
        {"name": "Python", "category": "P", "level": "Advanced"},
        {"name": "Docker", "category": "D", "level": "Intermediate"},
    ])
    student = models.get_student(student["id"])
    assert matching.job_match_score(student, role) == 0.0

    # Fully satisfies every requirement -> 100
    models.replace_self_reported_skills(student["id"], [
        {"name": "Python", "level": "Advanced"},
        {"name": "Docker", "level": "Advanced"},
    ])
    student = models.get_student(student["id"])
    assert matching.job_match_score(student, role) == 100.0

    # Partial: Python at Intermediate (2/3), Docker at Beginner (1/2) -> (2/3 + 1/2)/2 = 0.5833.. *100
    models.replace_self_reported_skills(student["id"], [
        {"name": "Python", "level": "Intermediate"},
        {"name": "Docker", "level": "Beginner"},
    ])
    student = models.get_student(student["id"])
    expected = round(((2 / 3) + (1 / 2)) / 2 * 100, 1)
    assert matching.job_match_score(student, role) == expected


def test_verified_level_overrides_self_reported(db):
    student = models.create_student("S", "s@test.edu", "U")
    # Self-reported says Advanced, but verified says Beginner -> verified wins (lower)
    models.replace_self_reported_skills(student["id"], [{"name": "Python", "level": "Advanced"}])
    py = models.get_skill_by_name("Python")
    models.update_verified_skill(student["id"], py["id"], "Beginner")
    role = _make_role(student, skills=[{"name": "Python", "category": "P", "level": "Advanced"}])
    student = models.get_student(student["id"])
    level, verified = matching.effective_skill_level(student, py["id"])
    assert level == "Beginner" and verified is True
    assert matching.job_match_score(student, role) == round((1 / 3) * 100, 1)


def test_recalc_after_verified_update(db):
    # Aisha's analysis by hand against seed data to validate the engine end to end.
    from app import seed
    seed_already = db  # db fixture seeds
    aisha = next(s for s in models.list_students() if s["email"] == "aisha@student.edu")
    analysis = matching.analyze_student(aisha["id"])
    assert analysis is not None
    role_id = analysis["role_id"]
    # Python and SQL verified at Advanced; ML intermediate; Docker beginner;
    # required: Python Adv, ML Int, Docker Int, SQL Adv
    # coverage: Python full, ML full (Int=Int), SQL full, Docker partial (Beg 1/2)
    expected = round(((1 + 1 + 0.5 + 1) / 4) * 100, 1)
    assert analysis["match_score"] == expected
    # Simulate verifying Docker at Intermediate -> all covered -> 100
    docker = models.get_skill_by_name("Docker")
    models.update_verified_skill(aisha["id"], docker["id"], "Intermediate")
    new_analysis = matching.analyze_student(aisha["id"])
    assert new_analysis["match_score"] == 100.0
    assert new_analysis["role_id"] == role_id
