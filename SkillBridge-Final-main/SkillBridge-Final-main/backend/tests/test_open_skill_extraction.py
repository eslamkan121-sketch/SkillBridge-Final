"""Phase A — open-universe CV skill extraction + open skill normalization.

Six deterministic non-tech profiles must extract correctly, unknown-but-grounded
skills must survive verbatim, no forced-Python behavior may remain, and every
model-invented or garbage name must be rejected by the evidence gate.

All profile tests force the deterministic fallback provider (no LLM calls) so
the expected sets are exact and provider-independent.
"""
import io

import pytest

from app import genai, jobs, models, skill_registry


def _force_fallback(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("deterministic fallback for test")

    monkeypatch.setattr(genai, "_generate", _raise)


def _model_output(monkeypatch, text):
    monkeypatch.setattr(genai, "_generate", lambda *a, **k: text)


# --------------------------------------------------------------- six profiles

AI_ENGINEER_CV = """\
Adam Bader
AI Engineer

SKILLS
Python (Advanced), Machine Learning (Intermediate), Docker (Beginner), SQL (Advanced)
"""

GRAPHIC_CV = """\
Nora Salem
Visual Designer

SKILLS
Adobe Photoshop, Illustrator, Typography, Brand Identity, Color Theory

PROJECTS
Designed a brand identity system for a cosmetics startup.
"""

MARKETING_CV = """\
Omar Hassan
Digital Marketing Analyst

SKILLS
Market Research, Google Analytics, SEO, Customer Segmentation, Campaign Planning
"""

CLINICAL_CV = """\
Layla Farid
Clinical Research Assistant

SKILLS
Clinical Research, Research Methods, Data Collection, Medical Documentation, Patient Communication

EXPERIENCE
Coordinated study visits and drafted patient communication materials.
"""

ARCHITECTURAL_CV = """\
Tariq Ahmed
Architectural Designer

SKILLS
AutoCAD, Revit, Architectural Drawing, Spatial Planning, 3D Modeling
"""

FINANCIAL_CV = """\
Fatima Noor
Financial Analyst

SKILLS
Financial Modeling, Forecasting, Budget Analysis, Data Analysis, Excel
"""

KHALED_CV = """\
Khaled Mohamed
Cybersecurity Engineer

PROFILE
Cybersecurity student with strong foundations in Python, Java, and network security.
Seeking an instructor role to help students develop strong programming and cybersecurity fundamentals.

Teaching & Leadership Experience
Explained programming and cybersecurity concepts to peers in a simple and structured manner.
Assisted classmates in debugging code and understanding problem-solving approaches.

EMPLOYMENT HISTORY
Cybersecurity Intern
Uneeq Interns
Developed advanced tools for threat detection, web vulnerability analysis, and log simulation in real-world environments.
SQL Injection Detector: Created an automated Python tool to identify vulnerable login endpoints using SQLi payloads.
Security Log Generator: Simulated real-time event logs for SIEM systems like ELK and Splunk to aid in anomaly detection.

Skills
Technical Skills
Python Programming
Java Programming
Cybersecurity Fundamentals
Penetration Testing
Networking BasicsTeaching & Soft Skills
Communication Skills
Explaining Complex Concepts Clearly
Presentation Skills
Problem-Solving Guidance
Team Collaboration

CERTIFICATES
CompTIA CySA+ Cybersecurity Analyst - RAK
ICT
Completed training covering cybersecurity analysis, threat detection, vulnerability management, incident response, and security monitoring.
Microsoft Office Specialist: PowerPoint Associate (Office 2019)
Demonstrated ability to create professional presentations using advanced design, animation, and communication techniques.
Sprints x Microsoft Summer Camp - Cybersecurity
Completed project-based cybersecurity training, applying technical skills and problem-solving in real-world scenarios and teamwork environments.
Microsoft Office Specialist: Excel Associate (Office 2019)
Validated proficiency in Excel, including data analysis, formulas, functions, and visualization tools for business and academic use.
Cybersecurity Internship Certificate, UneeQ Interns (July 2025)
Successful completion of cybersecurity internship program, recognizing ability to apply advanced security concepts and practices to protect systems, networks, and data from evolving threats.

LANGUAGES
English B2
Arabic
"""

KHALED_REJECTED = {
    "CERTIFICATES",
    "Completed project-based cybersecurity training",
    "Completed training covering cybersecurity analysis",
    "Successful completion of cybersecurity internship",
    "Validated proficiency in Excel",
    "and data from evolving threats",
    "and security monitoring",
    "and visualization tools for",
    "business and academic use",
    "practices to protect systems",
    "presentations using advanced design",
    "program",
    "animation",
    "UneeQ",
    "Office 2019",
    "Sprints x Microsoft Summer Camp",
    "Sprints x Microsoft Summer Camp - Cybersecurity",
    "CompTIA CySA+ Cybersecurity Analyst - RAK",
    "Cybersecurity Internship Certificate",
    "ICT",
    "Python Programming",
    "Java Programming",
    "Communication Skills",
    "Problem-Solving Guidance",
    "Networking BasicsTeaching",
    "Soft Skills",
}


@pytest.mark.parametrize("cv,expected", [
    (AI_ENGINEER_CV, {"Python", "Machine Learning", "Docker", "SQL"}),
    (GRAPHIC_CV, {"Adobe Photoshop", "Illustrator", "Typography", "Brand Identity", "Color Theory"}),
    (MARKETING_CV, {"Market Research", "Google Analytics", "SEO", "Customer Segmentation", "Campaign Planning"}),
    (CLINICAL_CV, {"Clinical Research", "Research Methods", "Data Collection", "Medical Documentation", "Patient Communication"}),
    (ARCHITECTURAL_CV, {"AutoCAD", "Revit", "Architectural Drawing", "Spatial Planning", "3D Modeling"}),
    (FINANCIAL_CV, {"Financial Modeling", "Forecasting", "Budget Analysis", "Data Analysis", "Excel"}),
])
def test_six_deterministic_profiles(monkeypatch, cv, expected):
    _force_fallback(monkeypatch)
    names = {r["name"] for r in genai.extract_skills_from_cv(cv)}
    assert names == expected, f"expected {expected}, got {names}"


def test_graphic_profile_has_no_python_injection(monkeypatch):
    _force_fallback(monkeypatch)
    result = genai.extract_skills_from_cv(GRAPHIC_CV)
    names = {r["name"].lower() for r in result}
    assert "python" not in names


def test_ai_profile_levels_preserved(monkeypatch):
    _force_fallback(monkeypatch)
    by_name = {r["name"]: r["level"] for r in genai.extract_skills_from_cv(AI_ENGINEER_CV)}
    assert by_name["Python"] == "Advanced"
    assert by_name["Machine Learning"] == "Intermediate"
    assert by_name["Docker"] == "Beginner"
    assert by_name["SQL"] == "Advanced"


def test_clinical_patient_communication_not_collapsed(monkeypatch):
    _force_fallback(monkeypatch)
    names = {r["name"] for r in genai.extract_skills_from_cv(CLINICAL_CV)}
    assert "Patient Communication" in names
    assert "Communication" not in names  # never collapsed, never re-derived


# --------------------------------------------------------------- regression set

def test_empty_cv_returns_empty_list():
    assert genai.extract_skills_from_cv("") == []


def test_cv_with_no_skills_returns_empty_list(monkeypatch):
    _force_fallback(monkeypatch)
    no_skills = """\
PROFILE
Seeking opportunities in the retail and hospitality sectors.
EDUCATION
BSc Economics, University of East London.
"""
    assert genai.extract_skills_from_cv(no_skills) == []


def test_unknown_grounded_skills_survive_verbatim(monkeypatch):
    _force_fallback(monkeypatch)
    cv = "SKILLS\nZbrush, Substance Painter, Digital Sculpting"
    result = genai.extract_skills_from_cv(cv)
    names = {r["name"] for r in result}
    assert names == {"Zbrush", "Substance Painter", "Digital Sculpting"}
    for r in result:
        assert r["category"] == skill_registry.NEUTRAL_CATEGORY


def test_unknown_grounded_survives_llm_path(monkeypatch):
    _model_output(monkeypatch, json_dumps([{"name": "Zbrush", "level": "Advanced",
                                            "category": "", "evidence": "Zbrush"}]))
    result = genai.extract_skills_from_cv("SKILLS\nZbrush")
    assert {r["name"] for r in result} == {"Zbrush"}
    assert result[0]["category"] == skill_registry.NEUTRAL_CATEGORY


def test_unknown_ungrounded_model_output_rejected(monkeypatch):
    _model_output(monkeypatch, json_dumps([{"name": "Quantum Cryptography", "level": "Expert", "category": "",
                                            "evidence": "study notes"}]))
    result = genai.extract_skills_from_cv("SKILLS\nPython")
    names = {r["name"] for r in result}
    assert "Quantum Cryptography" not in names
    assert "Python" in names


def test_explicit_synonym_canonicalizes(monkeypatch):
    _model_output(monkeypatch, json_dumps([{"name": "Postgres", "level": "Advanced",
                                            "category": "", "evidence": "PostgreSQL"}]))
    result = genai.extract_skills_from_cv("SKILLS\nPostgreSQL")
    assert {r["name"] for r in result} == {"PostgreSQL"}


def test_synonym_canonicalizes_in_fallback(monkeypatch):
    _force_fallback(monkeypatch)
    result = genai.extract_skills_from_cv("SKILLS\nML, Postgres")
    names = {r["name"] for r in result}
    assert "Machine Learning" in names and "PostgreSQL" in names


def test_exact_canonical_stays_canonical(monkeypatch):
    _model_output(monkeypatch, json_dumps([{"name": "Machine Learning", "level": "Intermediate",
                                            "category": "", "evidence": "Machine Learning"}]))
    result = genai.extract_skills_from_cv("SKILLS\nMachine Learning")
    assert {r["name"] for r in result} == {"Machine Learning"}
    assert result[0]["category"] == "AI"


def test_patient_communication_normalises_without_collapse():
    name, cat = genai._normalise_skill("Patient Communication")
    assert (name, cat) == ("Patient Communication", skill_registry.NEUTRAL_CATEGORY)


def test_sentence_email_url_date_degree_rejected(monkeypatch):
    _model_output(monkeypatch, json_dumps([
        {"name": "Managed a team of six engineers", "level": "Advanced", "category": "", "evidence": "Managed"},
        {"name": "contact@corp.io", "level": "Advanced", "category": "", "evidence": "contact"},
        {"name": "https://www.example.com", "level": "Advanced", "category": "", "evidence": "https"},
        {"name": "2023-2024", "level": "Advanced", "category": "", "evidence": "2023"},
        {"name": "BSc Management, University of London", "level": "Advanced", "category": "", "evidence": "BSc"},
        {"name": "Python", "level": "Beginner", "category": "", "evidence": "Python"},
    ]))
    result = genai.extract_skills_from_cv("SKILLS\nPython")
    assert {r["name"] for r in result} == {"Python"}


def test_cpp_csharp_dotnet_nodejs_uiux_all_survive(monkeypatch):
    _force_fallback(monkeypatch)
    cv = "SKILLS\nC++, C#, .NET, Node.js, UI/UX"
    names = {r["name"] for r in genai.extract_skills_from_cv(cv)}
    assert {"C++", "C#", ".NET", "Node.js", "UI/UX"} <= names


def test_duplicate_case_whitespace_variants_collapse(monkeypatch):
    _force_fallback(monkeypatch)
    cv = "SKILLS\nPython, PYTHON,  python , A/B Testing, a/b testing"
    names = {r["name"] for r in genai.extract_skills_from_cv(cv)}
    assert names == {"Python", "A/B Testing"}


def test_khaled_cv_fixture_extracts_clean_professional_skills(monkeypatch):
    _force_fallback(monkeypatch)
    result = genai.extract_skills_from_cv(KHALED_CV)
    names = {r["name"] for r in result}
    expected = {
        "Python", "Java", "Cybersecurity Fundamentals", "Penetration Testing",
        "Network Security", "Communication", "Presentation Skills", "Problem Solving",
        "Teamwork", "Threat Detection", "Vulnerability Management",
        "Cybersecurity Analysis", "Incident Response", "Security Monitoring",
        "SIEM", "SQL", "Data Analysis", "Excel", "PowerPoint",
    }
    assert expected <= names, f"missing clean skills: {expected - names}"
    assert not (names & KHALED_REJECTED), f"noise leaked into Khaled profile: {names & KHALED_REJECTED}"
    assert len([n for n in names if n in {"Python", "Python Programming"}]) == 1
    assert len([n for n in names if n in {"Java", "Java Programming"}]) == 1


def test_khaled_noisy_model_output_is_filtered_and_keeps_evidence(monkeypatch):
    sentence = (
        "Completed training covering cybersecurity analysis, threat detection, "
        "vulnerability management, incident response, and security monitoring."
    )
    _model_output(monkeypatch, json_dumps([
        {"name": "Completed training covering cybersecurity analysis", "level": "Intermediate",
         "category": "", "evidence": sentence},
        {"name": "Threat Detection", "level": "Intermediate", "category": "", "evidence": sentence},
        {"name": "and security monitoring", "level": "Intermediate", "category": "", "evidence": sentence},
        {"name": "CompTIA CySA+ Cybersecurity Analyst - RAK", "level": "Intermediate",
         "category": "", "evidence": "CompTIA CySA+ Cybersecurity Analyst - RAK"},
        {"name": "Cybersecurity Internship Certificate", "level": "Intermediate",
         "category": "", "evidence": "Cybersecurity Internship Certificate, UneeQ Interns (July 2025)"},
        {"name": "Validated proficiency in Excel", "level": "Intermediate",
         "category": "", "evidence": "Validated proficiency in Excel"},
        {"name": "business and academic use", "level": "Intermediate",
         "category": "", "evidence": "business and academic use"},
        {"name": "animation", "level": "Intermediate", "category": "", "evidence": "animation"},
        {"name": "UneeQ", "level": "Intermediate", "category": "", "evidence": "UneeQ"},
        {"name": "Python Programming", "level": "Beginner", "category": "", "evidence": "Python Programming"},
        {"name": "Java Programming", "level": "Beginner", "category": "", "evidence": "Java Programming"},
        {"name": "Communication Skills", "level": "Beginner", "category": "", "evidence": "Communication Skills"},
    ]))
    result = genai.extract_skills_from_cv(KHALED_CV)
    by_name = {r["name"]: r for r in result}
    names = set(by_name)
    assert "Threat Detection" in names
    assert by_name["Threat Detection"]["evidence"] == sentence
    assert {"Python", "Java", "Communication"} <= names
    assert not (names & KHALED_REJECTED), f"model noise leaked into Khaled profile: {names & KHALED_REJECTED}"


def test_all_fallback_items_have_grounded_evidence(monkeypatch):
    _force_fallback(monkeypatch)
    cv = AI_ENGINEER_CV.lower()
    for r in genai.extract_skills_from_cv(AI_ENGINEER_CV):
        assert (r.get("evidence") or "").strip()
        assert r["evidence"].lower() in cv


def test_explicit_skills_section_with_tools_and_unknown(monkeypatch):
    _force_fallback(monkeypatch)
    cv = """\
SKILLS
Adobe Photoshop, Illustrator, Typography, Brand Identity

TOOLS & TECHNOLOGIES
Figma, Zbrush
"""
    names = {r["name"] for r in genai.extract_skills_from_cv(cv)}
    assert {"Adobe Photoshop", "Illustrator", "Typography", "Brand Identity", "Figma", "Zbrush"} <= names


def test_two_column_skills_layout_preserves_compounds(monkeypatch):
    """PDF/column CV grids (2+ space gaps, no commas) must parse each cell as a
    grounded phrase -- e.g. the real Law-student CV. Compound names that contain
    ``and`` survive intact; cells never bleed into each other."""
    _force_fallback(monkeypatch)
    cv = """\
SKILLS
Legal research and writing  Dispute resolution and mediation
Case analysis and interpretation  Client advocacy
Proficiency with LexisNexis  Public speaking
"""
    names = {r["name"] for r in genai.extract_skills_from_cv(cv)}
    expected = {
        "Legal research and writing", "Dispute resolution and mediation",
        "Case analysis and interpretation", "Client advocacy",
        "Proficiency with LexisNexis", "Public speaking",
    }
    assert names == expected, f"expected {expected}, got {names}"


def test_one_per_line_compound_names_preserved(monkeypatch):
    """Single-line entries keep ``and``-based compound competency names whole
    (no comma/bullet on the line means ``and`` is a phrase part, not a list)."""
    _force_fallback(monkeypatch)
    cv = """\
SKILLS
Project management and stakeholder engagement
Public policy analysis
Legal research and writing
"""
    names = {r["name"] for r in genai.extract_skills_from_cv(cv)}
    assert names == {
        "Project management and stakeholder engagement",
        "Public policy analysis",
        "Legal research and writing",
    }


def test_comma_list_keeps_and_as_separator(monkeypatch):
    """Explicit list delimiters restore the legacy ``and``-join behaviour, so
    comma-separated enumerations still split correctly."""
    _force_fallback(monkeypatch)
    cv = "SKILLS\nPython, SQL and Docker, Tableau"
    names = {r["name"] for r in genai.extract_skills_from_cv(cv)}
    assert {"Python", "SQL", "Docker", "Tableau"} <= names


def test_skills_section_stops_at_references_grid(monkeypatch):
    """The real Law CV (Graduate-Resume-Example-Law.pdf) has a two-column SKILLS
    grid followed by a two-column REFEREES grid ("William Turner  Candice
    Palmer", "WGC Lawyers  Lander & Rogers") plus recruiter TIP boilerplate.
    Without a section boundary the referees grid, person names, employer names,
    job titles and TIP fragments are all parsed as skills. The skills content
    region must terminate at the REFEREES heading, and TIP lines must never be
    list-split into "phone"/"title"/"organisation" style skills."""
    _force_fallback(monkeypatch)
    cv = """\
MARCUS THOMPSON

SKILLS
Legal research and writing  Dispute resolution and mediation
Case analysis and interpretation  Client advocacy
Proficiency with LexisNexis  Public speaking

     TIP: List specific skills that you have gained that are relevant to the jobs you're applying for.

REFEREES
William Turner    Candice Palmer
Partner - Family Law    Clerkship Coordinator
WGC Lawyers    Lander & Rogers
(07) 4055 6505    (03) 8566 8000
william.turner@wgclawyers.com.au    c.palmer@landers.com.au

     TIP: List their name, title, organisation and phone, or write "Available on request."
"""
    names = {r["name"] for r in genai.extract_skills_from_cv(cv)}
    assert names == {
        "Legal research and writing", "Dispute resolution and mediation",
        "Case analysis and interpretation", "Client advocacy",
        "Proficiency with LexisNexis", "Public speaking",
    }
    assert not names & {
        "William Turner", "Candice Palmer", "WGC Lawyers", "Lander & Rogers",
        "Clerkship Coordinator", "REFEREES", "Partner - Family Law",
        "phone", "title", "organisation",
    }, f"non-skill noise leaked into profile: {names & {'William Turner', 'Candice Palmer', 'WGC Lawyers', 'Lander & Rogers', 'Clerkship Coordinator', 'REFEREES', 'Partner - Family Law', 'phone', 'title', 'organisation'}}"


def test_other_non_skill_headings_bound_skills_region(monkeypatch):
    """Any classic non-skill heading ends the skills content region so a
    following section can never leak in regardless of layout."""
    _force_fallback(monkeypatch)
    cv = """\
SKILLS
Python, SQL, Docker

CONTACT
Jane Doe, Acme Ltd, London, jane@acme.com

ADDITIONAL SKILLS
Project Management
"""
    names = {r["name"] for r in genai.extract_skills_from_cv(cv)}
    assert {"Python", "SQL", "Docker", "Project Management"} <= names
    assert not any("Jane Doe" in n or "Acme" in n for n in names)


def test_inline_skill_heading_parses(monkeypatch):
    _force_fallback(monkeypatch)
    cv = "Nora Salem\nKey Skills: Adobe Photoshop, Illustrator, Typography"
    names = {r["name"] for r in genai.extract_skills_from_cv(cv)}
    assert {"Adobe Photoshop", "Illustrator", "Typography"} <= names


def test_cv_upload_persists_skills_with_evidence(client, db, student_id, auth_headers, monkeypatch):
    _force_fallback(monkeypatch)
    before = models.get_student(student_id)
    col_names = [r["name"] for r in db.execute("PRAGMA table_info(self_reported_skills)")]
    assert "evidence" in col_names  # additive migration made the column real

    headers = auth_headers("aisha@student.edu")
    res = client.post(
        f"/api/students/{student_id}/cv",
        files={"file": ("graphic_cv.txt", io.BytesIO(GRAPHIC_CV.encode()), "text/plain")},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    extracted = res.json()["extracted"]
    assert len(extracted) == 5
    assert all(r.get("evidence") for r in extracted)  # evidence never silently dropped

    student = models.get_student(student_id)
    sr = student["self_reported_skills"]
    assert {s["name"] for s in sr} == {
        "Adobe Photoshop", "Illustrator", "Typography", "Brand Identity", "Color Theory"}
    # evidence persisted and survives a profile refresh
    assert all(s.get("evidence") for s in sr)
    # manual/other records are untouched: verified set identical, source stays cv
    assert student["verified_skills"] == before["verified_skills"]
    assert all(s["source"] == "cv" for s in sr)
    assert student["cv_filename"] == "graphic_cv.txt"


def test_no_jobs_regression_and_backcompat_alias():
    hits = jobs._extract_required_skills(
        {"title": "Junior Data Engineer", "tags": ["SQL", "Docker"], "description": "Build data pipelines"})
    assert {"SQL", "Docker"} <= set(hits)
    assert genai.FALLBACK_SKILL_CATEGORIES["Python"] == "Programming"
    assert genai.FALLBACK_SKILL_CATEGORIES is skill_registry.CANONICAL_CATEGORIES


def test_real_law_pdf_upload_pipeline(client, student_id, auth_headers):
    """The noise-filter features must hold for the REAL Graduate-Resume-Example
    Law CV uploaded through the actual production endpoint (same multipart path
    a browser uses), not just a hand-built fixture string."""
    import os
    law_pdf = os.path.join(os.path.expanduser("~"), "Downloads", "Graduate-Resume-Example-Law.pdf")
    if not os.path.exists(law_pdf):
        pytest.skip("real Law PDF not on this machine")
    with open(law_pdf, "rb") as f:
        pdf_bytes = f.read()
    headers = auth_headers("aisha@student.edu")
    res = client.post(
        f"/api/students/{student_id}/cv",
        files={"file": ("Graduate-Resume-Example-Law.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    extracted = res.json()["extracted"]
    names = {r["name"] for r in extracted}
    expected = {
        "Legal research and writing", "Dispute resolution and mediation",
        "Case analysis and interpretation", "Client advocacy",
        "Proficiency with LexisNexis", "Public speaking",
        "Communication", "Time Management",
    }
    assert expected <= names, f"missing skills: {expected - names}"
    assert not names & {
        "William Turner", "Candice Palmer", "WGC Lawyers", "Lander & Rogers",
        "Clerkship Coordinator", "Partner - Family Law", "phone", "title",
        "organisation", "instructions from the employer", "REFEREES",
    }, f"noise leaked through the real upload path: {names}"
    # profile persisted through the same real endpoint
    student = models.get_student(student_id)
    assert {s["name"] for s in student["self_reported_skills"]} == names


def test_real_khaled_pdf_upload_pipeline(client, student_id, auth_headers, monkeypatch):
    """Optional local smoke for the real Khaled CV. CI uses KHALED_CV above so
    the regression remains deterministic when the personal PDF is unavailable."""
    import os
    _force_fallback(monkeypatch)
    candidates = [
        os.path.join(os.path.expanduser("~"), "Downloads", "Khaled's_CV(1).pdf"),
        os.path.join(os.path.expanduser("~"), "Downloads", "Khaled's_CV.pdf"),
        os.path.join(os.path.expanduser("~"), "Downloads", "cv pdf", "Khaled's_CV(1).pdf"),
        os.path.join(os.path.expanduser("~"), "Downloads", "cv pdf", "Khaled's_CV.pdf"),
    ]
    khaled_pdf = next((p for p in candidates if os.path.exists(p)), None)
    if not khaled_pdf:
        pytest.skip("real Khaled PDF not on this machine")
    with open(khaled_pdf, "rb") as f:
        pdf_bytes = f.read()
    headers = auth_headers("aisha@student.edu")
    res = client.post(
        f"/api/students/{student_id}/cv",
        files={"file": (os.path.basename(khaled_pdf), io.BytesIO(pdf_bytes), "application/pdf")},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    extracted = res.json()["extracted"]
    names = {r["name"] for r in extracted}
    expected = {
        "Python", "Java", "Cybersecurity Fundamentals", "Penetration Testing",
        "Network Security", "Communication", "Presentation Skills", "Problem Solving",
        "Teamwork", "Threat Detection", "Vulnerability Management",
        "Cybersecurity Analysis", "Incident Response", "Security Monitoring",
        "SIEM", "SQL", "Data Analysis", "Excel", "PowerPoint",
    }
    assert expected <= names, f"missing clean skills from real Khaled PDF: {expected - names}"
    assert not (names & KHALED_REJECTED), f"noise leaked through real Khaled upload: {names & KHALED_REJECTED}"
    student = models.get_student(student_id)
    assert {s["name"] for s in student["self_reported_skills"]} == names


def json_dumps(payload):
    import json
    return json.dumps(payload)
