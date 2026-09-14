"""P1-2 regression — Skill Gap Map / Career Readiness must count name evidence.

Reproduction: live student "Khaled Mohamed" has 22 self-reported skills (ids
1-104) but his ESCO target role "ICT security manager" (role 27) requires 20
ESCO phrase skills (ids 105-124) with ZERO id overlap. The old engine matched
only by skill id, so every requirement was "missing" -> ring 0.0% and a gap map
of "0 strong · 0 gap · 20 missing" that ignored obvious self-reported overlap
(Cybersecurity Advanced, Network Security, Threat Detection, SIEM, ...).

The fix adds NAME evidence to ``matching``:
  - normalised-name equality             -> exact evidence (strong/gap by level)
  - token/containment overlap            -> adjacent evidence (always gap, half credit)
Exact-id semantics are unchanged so catalog roles and existing tests are intact.
"""
from collections import Counter

from app import matching, match_explain, models

# The exact 20 ESCO requirement rows of live role 27 (ids 105-124).
REQUIREMENTS_27 = [
    (105, "legal requirements of ICT products"),
    (106, "ICT project management"),
    (107, "ICT problem management techniques"),
    (108, "maintain ICT identity management"),
    (109, "solve ICT system problems"),
    (110, "manage IT security compliances"),
    (111, "internet governance"),
    (112, "ICT quality policy"),
    (113, "computer forensics"),
    (114, "lead disaster recovery exercises"),
    (115, "establish an ICT security prevention plan"),
    (116, "Internet of Things"),
    (117, "develop information security strategy"),
    (118, "ICT system user requirements"),
    (119, "manage disaster recovery plans"),
    (120, "implement ICT risk management"),
    (121, "internal risk management policy"),
    (122, "define security policies"),
    (123, "information security strategy"),
    (124, "ICT security standards"),
]

KHALED_SKILLS = [
    ("Python", "Beginner"), ("SQL", "Intermediate"), ("Excel", "Intermediate"),
    ("Communication", "Advanced"), ("Teamwork", "Intermediate"),
    ("Problem Solving", "Intermediate"), ("Data Analysis", "Intermediate"),
    ("Cybersecurity", "Advanced"), ("Network Security", "Intermediate"),
    ("Threat Detection", "Advanced"), ("Incident Response", "Intermediate"),
    ("Vulnerability Management", "Beginner"), ("Java", "Beginner"),
    ("SIEM", "Intermediate"), ("Cybersecurity Fundamentals", "Beginner"),
    ("Cybersecurity Analysis", "Beginner"), ("Penetration Testing", "Beginner"),
    ("Presentation Skills", "Beginner"), ("Security Monitoring", "Beginner"),
    ("PowerPoint", "Advanced"), ("NLP", "Beginner"),
    ("Explaining Complex Concepts Clearly", "Beginner"),
]


def _student(pairs):
    s = models.create_student("S", "s@test.edu", "U")
    models.replace_self_reported_skills(s["id"], [{"name": n, "level": lvl} for n, lvl in pairs])
    return models.get_student(s["id"])


def _db_role(reqs, title="ICT security manager"):
    comp = models.create_company("C", "I")
    return models.create_role(comp["id"], title, [
        {"name": name, "category": "Professional Skill", "level": "Intermediate"}
        for _sid, name in reqs
    ])


def _dict_role(reqs, title="ICT security manager"):
    return {
        "id": 1,
        "title": title,
        "company_name": None,
        "required_skills": [
            {"skill_id": sid, "name": name, "required_level": "Intermediate",
             "category": "Professional Skill"}
            for sid, name in reqs
        ],
    }


def test_khaled_profile_moves_off_zero(db):
    student = _student(KHALED_SKILLS)
    role = _db_role(REQUIREMENTS_27)
    models.update_student(student["id"], target_role_id=role["id"])
    a = matching.analyze_student(student["id"])
    assert a["match_score"] > 0.0
    counts = Counter(r["status"] for r in a["skill_gaps"])
    assert counts["missing"] == 14
    assert counts["gap"] == 6
    assert counts["strong"] == 0
    by_name = {r["skill_name"]: r for r in a["skill_gaps"]}
    for phrase in ("manage IT security compliances", "define security policies",
                   "ICT security standards", "develop information security strategy",
                   "information security strategy", "establish an ICT security prevention plan"):
        row = by_name[phrase]
        assert row["status"] == "gap"
        assert row["matched_by"] == "name_adjacent"
        assert row["student_level"] == "Advanced"
        assert row["verified"] is False
        assert row["matched_skill"] in ("Cybersecurity", "Network Security", "Security Monitoring")


def test_khaled_profile_exact_ring_value(db):
    student = _student(KHALED_SKILLS)
    # 6 adjacent gaps at Advanced (3) vs Intermediate (2): 0.5 credit each.
    assert matching.job_match_score(student, _dict_role(REQUIREMENTS_27)) == 15.0


def test_generic_frame_tokens_never_match(db):
    # A profile with only "Vulnerability Management" + "Communication" must NOT
    # gain credit against unrelated ESCO phrase requirements just because both
    # mention management/project/legal/internet words.
    student = _student([("Vulnerability Management", "Beginner"), ("Communication", "Advanced")])
    role = _db_role(REQUIREMENTS_27)
    models.update_student(student["id"], target_role_id=role["id"])
    a = matching.analyze_student(student["id"])
    by_name = {r["skill_name"]: r for r in a["skill_gaps"]}
    for phrase in ("ICT problem management techniques", "legal requirements of ICT products",
                   "Internet of Things", "computer forensics", "ICT project management"):
        assert by_name[phrase]["status"] == "missing"
        assert by_name[phrase]["matched_by"] is None
    assert a["match_score"] == 0.0


def test_adjacent_evidence_never_strong(db):
    student = _student([("Cybersecurity", "Advanced")])
    role = _dict_role([(500, "define security policies")])
    rows = matching.categorize(student, role)
    assert rows[0]["status"] == "gap"
    assert rows[0]["matched_by"] == "name_adjacent"
    assert matching.job_match_score(student, role) == 50.0


def test_adjacent_credit_scales_with_level(db):
    student = _student([("Security Monitoring", "Beginner")])
    role = _dict_role([(501, "define security policies")])
    # Beginner (1) vs required Intermediate (2): ratio 1/2, halved = 0.25.
    assert matching.job_match_score(student, role) == 25.0


def test_adjacent_does_not_apply_without_meaning_token(db):
    # "lead disaster recovery exercises" has no overlap with the Khaled profile
    # once frame tokens (lead/exercises) are stripped.
    student = _student(KHALED_SKILLS)
    role = _dict_role([(114, "lead disaster recovery exercises"), (119, "manage disaster recovery plans")])
    rows = matching.categorize(student, role)
    assert [r["status"] for r in rows] == ["missing", "missing"]


def test_name_exact_evidence_with_different_id(db):
    # Same normalised name on a different row is exact evidence at the student
    # level (never adjacent-reduced), matching the id path semantics.
    student = _student([("Data Analysis", "Intermediate")])
    role = _dict_role([(1_000_000, "Data Analysis")])
    rows = matching.categorize(student, role)
    assert rows[0]["status"] == "strong"
    assert rows[0]["matched_by"] == "name_exact"
    assert rows[0]["verified"] is False
    assert matching.job_match_score(student, role) == 100.0


def test_exact_id_semantics_unchanged(db):
    py = models.get_skill_by_name("Python")
    student = _student([("Python", "Intermediate")])
    role = _dict_role([(py["id"], "Python")])
    role["required_skills"][0]["required_level"] = "Advanced"
    rows = matching.categorize(student, role)
    assert rows[0]["status"] == "gap"
    assert rows[0]["matched_by"] == "id"
    assert matching.job_match_score(student, role) == round(200 / 3, 1)


def test_phaseJ_breakdown_parity_esco_profile(db):
    student = _student(KHALED_SKILLS)
    role = _db_role(REQUIREMENTS_27)
    models.update_student(student["id"], target_role_id=role["id"])
    student = models.get_student(student["id"])
    b = match_explain.target_role_match_breakdown(student)
    assert b["displayed_percent"] == matching.job_match_score(student, student["target_role"])
    assert round(float(b["raw_percent"]), 1) == b["displayed_percent"]
    gap_rows = [d for d in b["requirements"] if d["status"] == "gap"]
    assert len(gap_rows) == 6
    for d in gap_rows:
        assert d["matched_by"] == "name_adjacent"
        assert d["matched_skill"]
        assert str(d["evidence"]) == "self_reported"