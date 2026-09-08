"""Phase 2 — CV skill-extraction pipeline using a fixture CV."""
import io

from app import genai, models


FIXTURE_CV = """\
Aisha Rahman
BSc Computer Science, Aston University

KEY SKILLS
Python (Advanced), Machine Learning (Intermediate), Docker (Beginner), SQL (Advanced)

PROJECTS
Built a machine learning dashboard and deployed a Docker container.
EXPERIENCE
Worked with SQL databases and Python scripting during an internship.
"""


def test_extract_skills_returns_structured_list():
    result = genai.extract_skills_from_cv(FIXTURE_CV)
    assert isinstance(result, list) and len(result) > 0
    for item in result:
        assert "name" in item and "level" in item and "category" in item
        assert item["level"] in ("Beginner", "Intermediate", "Advanced")
        assert item["name"].strip()


def test_extract_picks_up_known_skills():
    result = genai.extract_skills_from_cv(FIXTURE_CV)
    names = {r["name"].lower() for r in result}
    assert "python" in names and "sql" in names


def test_cv_upload_via_api_populates_self_reported(client, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    res = client.post(
        f"/api/students/{student_id}/cv",
        files={"file": ("aisha_cv.txt", io.BytesIO(FIXTURE_CV.encode()), "text/plain")},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert len(data["extracted"]) > 0
    # persisted to the student profile
    student = models.get_student(student_id)
    assert len(student["self_reported_skills"]) > 0
    # uploaded filename persisted
    assert student["cv_filename"] == "aisha_cv.txt"


def test_cv_upload_rejects_other_students(client, student_id, auth_headers):
    """RBAC: one student cannot overwrite another student's skills via the CV route."""
    headers = auth_headers("omar@student.edu")
    omar = models.get_student_by_user(models.get_user_by_email("omar@student.edu")["id"])
    other = omar["id"]
    res = client.post(
        f"/api/students/{other}/cv",
        files={"file": ("omar_cv.txt", io.BytesIO(FIXTURE_CV.encode()), "text/plain")},
        headers=headers,
    )
    assert res.status_code == 200  # owns their own record
    res = client.post(
        f"/api/students/{student_id}/cv",
        files={"file": ("evil.txt", io.BytesIO(FIXTURE_CV.encode()), "text/plain")},
        headers=headers,
    )
    assert res.status_code == 403  # cannot touch aisha's record
    assert models.get_student(student_id)["cv_filename"] is None


def test_empty_cv_returns_no_invented_skills():
    # An empty/garbage CV must never invent skills (no forced-Python fallback,
    # no hallucination) — the honest result is an empty list.
    result = genai.extract_skills_from_cv("")
    assert result == []


def test_extraction_captures_skills_across_all_sections():
    # Phase 3: skills mentioned only in PROJECTS / COURSEWORK / EXPERIENCE
    # (not in a KEY SKILLS list) must still all appear in the extracted profile.
    scattered = """\
Jordan Lee
COURSEWORK
Machine Learning, SQL, and Git version control were core to the module.
PROJECTS
Deployed a FastAPI app with Docker containers; wrote Spark ETL jobs; used
Tableau for visualization and pandas for analysis.
EXPERIENCE
Worked with Kubernetes orchestration and CI/CD pipelines in an internship.
"""
    result = genai.extract_skills_from_cv(scattered)
    names = {r["name"].lower() for r in result}
    # these appear nowhere in a "KEY SKILLS" block, only inside body sections
    for expected in ["docker", "spark", "tableau", "pandas", "kubernetes", "git"]:
        assert expected in names, f"missing {expected} from full set {sorted(names)}"
