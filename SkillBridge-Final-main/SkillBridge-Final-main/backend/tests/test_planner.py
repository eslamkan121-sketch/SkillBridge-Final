"""Req 2 — Learning roadmaps are genuinely AI-generated, blueprint-constrained,
and sufficient (every required competency is covered)."""
from app import genai, matching, models, skill_blueprint as sb


def test_blueprint_rejects_out_of_scope_competencies():
    """A module claiming a competency outside the closed blueprint must be detected."""
    modules = [
        {"competency": "Containers", "title": "What is a container"},
        {"competency": "Quantum teleportation", "title": "Made-up thing"},
    ]
    ok, allowed, offending = sb.validate_competencies(modules, "Docker", "Beginner", "Beginner")
    assert ok is False
    assert "Quantum teleportation" in offending


def test_blueprint_beyond_blueprint_modules_are_flagged_not_forced():
    """Bonus modules marked beyond-blueprint are allowed but never counted as coverage."""
    modules = [
        {"competency": "Containers", "beyond_blueprint": False},
        {"competency": "Images", "beyond_blueprint": False},
        {"competency": "Basic commands", "beyond_blueprint": False},
        {"competency": "Bonus Kubernetes primer", "beyond_blueprint": True},
    ]
    ok, allowed, offending = sb.validate_competencies(modules, "Docker", "Beginner", "Beginner")
    assert ok is True  # the bonus module is labelled and excluded from the check
    covered, missing = sb.modules_cover(modules, "Docker", "Beginner", "Beginner")
    assert covered is True and missing == []
    # A bonus module alone can never satisfy a required competency
    only_bonus = [{"competency": "Bonus Kubernetes primer", "beyond_blueprint": True}]
    covered2, missing2 = sb.modules_cover(only_bonus, "Docker", "Beginner", "Beginner")
    assert covered2 is False and set(missing2) == {"Containers", "Images", "Basic commands"}


def test_learning_plan_is_genuine_and_sufficient_for_docker():
    """The full planner output for Docker must cite the blueprint version, only use
    in-blueprint competencies, and cover every required competency (no gaps)."""
    plan = genai.plan_learning_path("Docker", "DevOps", "Beginner", "Intermediate",
                                    "Junior AI Engineer")
    required = sb.required_competencies("Docker", "Beginner", "Intermediate")
    assert required  # sanity: the blueprint knows Docker's competencies
    assert plan["blueprint_version"] == sb.BLUEPRINT_VERSION
    # genuineness: every module competency is from the closed list
    ok, allowed, offending = sb.validate_competencies(plan["modules"], "Docker", "Beginner", "Intermediate")
    assert ok, f"out-of-blueprint competencies: {offending}"
    # sufficiency: every required competency is covered
    covered, missing = sb.modules_cover(plan["modules"], "Docker", "Beginner", "Intermediate")
    assert covered, f"missing competencies: {missing}"
    # plan declares the exact required competency set it set out to cover
    assert set(plan["blueprint_competencies"]) == set(required)
    # each module carries the planned learning content
    for m in plan["modules"]:
        assert m.get("title") and m.get("objective")
        assert isinstance(m["estimated_minutes"], int) and m["estimated_minutes"] >= 20


def test_learning_plan_sufficient_for_second_blueprint_skill():
    """The genuineness/sufficiency guarantee holds for a second blueprint skill (SQL),
    so it isn't just special-cased for Docker."""
    plan = genai.plan_learning_path("SQL", "Data", "Beginner", "Intermediate", "Data Analyst")
    ok, allowed, offending = sb.validate_competencies(plan["modules"], "SQL", "Beginner", "Intermediate")
    assert ok, f"out-of-blueprint competencies: {offending}"
    covered, missing = sb.modules_cover(plan["modules"], "SQL", "Beginner", "Intermediate")
    assert covered, f"missing competencies: {missing}"


def test_generate_learning_item_sufficient(client, student_id, auth_headers):
    """The live learning-generate endpoint returns a sufficient, versioned plan."""
    headers = auth_headers("aisha@student.edu")
    student = models.get_student(student_id)
    gap = matching.gap_skills(student, student["target_role"])[0]
    r = client.post(f"/api/students/{student_id}/learning/generate",
                    json={"skill_id": gap["skill_id"]}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["skill_id"] == gap["skill_id"]
    assert body["blueprint_version"] == sb.BLUEPRINT_VERSION
    assert isinstance(body["plan_modules"], list) and body["plan_modules"]
    assert isinstance(body["blueprint_competencies"], list)
    if sb.has_blueprint(gap["skill_name"]):
        covered, missing = sb.modules_cover(body["plan_modules"], gap["skill_name"], "Beginner", "Advanced")
        assert covered, f"missing competencies: {missing}"
    # persisted
    items = models.list_learning_path(student_id)
    assert any(i["skill_id"] == gap["skill_id"] for i in items)
