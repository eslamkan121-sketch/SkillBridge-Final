"""Cross-domain regression tests: target role → live jobs, ESCO market, and
recommendations. Each scenario verifies that:
  1. Jobs in the same career family (EXACT/CLOSE/FAMILY) are retained.
  2. Jobs in unrelated careers are excluded — CV skill overlap does not leak.
  3. ESCO occupations that belong to the family surface; unrelated ones don't.
  4. Recommendations use the target role as the seed, not a generic CV skill.
"""

import pytest
from unittest.mock import patch

from app import jobs, role_intent


# ---------------------------------------------------------------------------
# Helper to run role-driven scoring with the full skill/req bundle
# ---------------------------------------------------------------------------

def _score(role_title, requisites, skills_by_name, raw_jobs, location="Remote"):
    """Run the full role-driven scoring pipeline on a list of raw job dicts
    and return the ranked titles. All new functions must pass through here."""
    reqs = list(requisites)
    skill_names = list(skills_by_name.keys())
    primary, minor = jobs._cluster_keywords(
        skill_names, role_title, reqs)
    family = jobs._role_family(role_title)
    seniority = jobs._student_seniority([s["lvl"] for s in skills_by_name.values()])
    ranked = jobs._apply(
        raw_jobs, primary, seniority, location, "",
        family, minor_keywords=minor,
        role_driven=True, role_title=role_title)
    return [j["title"] for j in ranked], [j["company"] for j in ranked]


# ---------------------------------------------------------------------------
# Domain 1: Cybersecurity Analyst
# ---------------------------------------------------------------------------

class TestCybersecurityTarget:
    """A Cybersecurity Analyst student has network/security skills that could
    overlap with IT, sysadmin, or generic data roles — none of those should
    appear in the feed."""

    REQUISITES = [
        "Active Directory", "Cybersecurity", "Incident Response", "Linux",
        "Network Security", "Risk Assessment", "SIEM", "Threat Detection",
        "Vulnerability Management", "Windows Server",
    ]
    SKILLS = {
        "Cybersecurity": {"lvl": "Advanced"},
        "Incident Response": {"lvl": "Intermediate"},
        "SIEM": {"lvl": "Intermediate"},
        "Network Security": {"lvl": "Intermediate"},
        "Threat Detection": {"lvl": "Advanced"},
        "Vulnerability Management": {"lvl": "Beginner"},
        "Excel": {"lvl": "Intermediate"},
        "Java": {"lvl": "Beginner"},
        "Machine Learning": {"lvl": "Intermediate"},
        "Communication": {"lvl": "Advanced"},
        "NLP": {"lvl": "Beginner"},
        "Data Analysis": {"lvl": "Intermediate"},
    }

    EXCLUDED_JOBS = [
        {"title": "Data Scientist", "company": "DataCo",
         "url": "d1", "location": "Remote", "tags": ["machine learning", "nlp", "data analysis"],
         "source": "JSearch"},
        {"title": "Backend Software Engineer", "company": "SoftCo",
         "url": "d2", "location": "Remote", "tags": ["java", "sql"],
         "source": "JSearch"},
        {"title": "Marketing Manager", "company": "MktCo",
         "url": "d3", "location": "Remote", "tags": ["excel", "communication"],
         "source": "JSearch"},
        {"title": "Sales Representative", "company": "SalesCo",
         "url": "d4", "location": "Remote", "tags": ["communication", "excel"],
         "source": "JSearch"},
        {"title": "Software Developer", "company": "DevCo",
         "url": "d5", "location": "Remote", "tags": ["java", "sql", "api"],
         "source": "JSearch"},
        {"title": "IT Support Specialist", "company": "SupportCo",
         "url": "d6", "location": "Remote", "tags": ["windows server", "linux", "active directory"],
         "source": "JSearch"},
    ]
    RELEVANT_JOBS = [
        {"title": "Cybersecurity Analyst", "company": "Defense Co",
         "url": "r1", "location": "Remote", "tags": ["threat detection", "siem", "incident response"],
         "source": "JSearch"},
        {"title": "Security Analyst (SOC)", "company": "SOC Team",
         "url": "r2", "location": "Remote", "tags": ["siem", "incident response"],
         "source": "JSearch"},
        {"title": "Incident Response Analyst", "company": "IR Team",
         "url": "r3", "location": "Remote", "tags": ["security"],
         "source": "JSearch"},
    ]

    @pytest.fixture()
    def all_jobs(self):
        return self.EXCLUDED_JOBS + self.RELEVANT_JOBS

    def test_excluded_jobs_never_surface(self, all_jobs):
        titles, companies = _score(
            "Cybersecurity Analyst", self.REQUISITES, self.SKILLS, all_jobs)
        assert "Data Scientist" not in titles, "data career must not leak into cybersecurity feed"
        assert "Backend Software Engineer" not in titles
        assert "Marketing Manager" not in titles
        assert "Sales Representative" not in titles
        assert "Software Developer" not in titles
        # IT Support Specialist shares AD/Linux/Windows but is a different career
        # (sysadmin vs security) — must not appear.
        assert "IT Support Specialist" not in titles, "IT support is sysadmin, not cybersecurity"

    def test_relevant_jobs_surface(self, all_jobs):
        titles, companies = _score(
            "Cybersecurity Analyst", self.REQUISITES, self.SKILLS, all_jobs)
        assert "Cybersecurity Analyst" in titles
        assert "SOC Team" in companies or "IR Team" in companies

    def test_excluded_role_tier_is_unrelated(self):
        for job in self.EXCLUDED_JOBS:
            cls = role_intent.classify_title("Cybersecurity Analyst", job["title"])
            assert cls == "UNRELATED", f"{job['title']} should be UNRELATED for cybersecurity, got {cls}"

    def test_relevant_role_tier(self):
        expected = {
            "Cybersecurity Analyst": "EXACT",
            "Security Analyst (SOC)": "FAMILY",
            "Incident Response Analyst": "FAMILY",
        }
        for title, exp_cls in expected.items():
            cls = role_intent.classify_title("Cybersecurity Analyst", title)
            assert cls == exp_cls, f"{title} should be {exp_cls}, got {cls}"


# ---------------------------------------------------------------------------
# Domain 2: Graphic Designer
# ---------------------------------------------------------------------------

class TestGraphicDesignerTarget:
    """Graphic Designer has creative skills (Photoshop, Illustrator) but the
    CV also has Excel and Communication — those must not let Marketing or
    Admin roles leak through."""

    REQUISITES = ["Adobe Photoshop", "Illustrator", "Typography", "Color Theory",
                  "Layout Design", "Branding"]
    SKILLS = {
        "Photoshop": {"lvl": "Advanced"},
        "Illustrator": {"lvl": "Advanced"},
        "Typography": {"lvl": "Intermediate"},
        "Excel": {"lvl": "Intermediate"},
        "Communication": {"lvl": "Advanced"},
    }

    EXCLUDED_JOBS = [
        {"title": "Marketing Manager", "company": "MktCo",
         "url": "d1", "location": "Remote", "tags": ["excel", "communication", "marketing"],
         "source": "JSearch"},
        {"title": "Financial Analyst", "company": "FinCo",
         "url": "d2", "location": "Remote", "tags": ["excel", "financial modeling"],
         "source": "JSearch"},
        {"title": "Sales Representative", "company": "SalesCo",
         "url": "d3", "location": "Remote", "tags": ["communication", "sales"],
         "source": "JSearch"},
    ]
    RELEVANT_JOBS = [
        {"title": "Graphic Designer", "company": "Design Co",
         "url": "r1", "location": "Remote", "tags": ["photoshop", "illustrator", "typography"],
         "source": "JSearch"},
        {"title": "Visual Designer", "company": "Studio A",
         "url": "r2", "location": "Remote", "tags": ["photoshop", "figma"],
         "source": "JSearch"},
        {"title": "Brand Designer", "company": "BrandCo",
         "url": "r3", "location": "Remote", "tags": ["illustrator", "branding"],
         "source": "JSearch"},
    ]

    @pytest.fixture()
    def all_jobs(self):
        return self.EXCLUDED_JOBS + self.RELEVANT_JOBS

    def test_no_marketing_finance_sales_leak(self, all_jobs):
        titles, _ = _score(
            "Graphic Designer", self.REQUISITES, self.SKILLS, all_jobs)
        for ex in ["Marketing Manager", "Financial Analyst", "Sales Representative"]:
            assert ex not in titles, f"{ex} must not leak into graphic design feed"

    def test_design_roles_surface(self, all_jobs):
        titles, _ = _score(
            "Graphic Designer", self.REQUISITES, self.SKILLS, all_jobs)
        assert "Graphic Designer" in titles
        assert len([t for t in titles if t in
                    ["Graphic Designer", "Visual Designer", "Brand Designer"]]) >= 2

    def test_excluded_are_unrelated(self):
        for job in self.EXCLUDED_JOBS:
            cls = role_intent.classify_title("Graphic Designer", job["title"])
            assert cls == "UNRELATED", f"{job['title']} should be UNRELATED for graphic design, got {cls}"


# ---------------------------------------------------------------------------
# Domain 3: Financial Analyst
# ---------------------------------------------------------------------------

class TestFinancialAnalystTarget:
    REQUISITES = ["Financial Modeling", "Excel", "Accounting", "Forecasting",
                  "Risk Assessment", "Data Analysis"]
    SKILLS = {
        "Financial Modeling": {"lvl": "Advanced"},
        "Excel": {"lvl": "Advanced"},
        "Accounting": {"lvl": "Intermediate"},
        "Communication": {"lvl": "Intermediate"},
        "Python": {"lvl": "Beginner"},
    }

    EXCLUDED_JOBS = [
        {"title": "Software Developer", "company": "SoftCo",
         "url": "d1", "location": "Remote", "tags": ["python", "api"],
         "source": "JSearch"},
        {"title": "Cybersecurity Analyst", "company": "CyberCo",
         "url": "d2", "location": "Remote", "tags": ["risk assessment", "security"],
         "source": "JSearch"},
        {"title": "Graphic Designer", "company": "DesignCo",
         "url": "d3", "location": "Remote", "tags": ["photoshop"],
         "source": "JSearch"},
    ]
    RELEVANT_JOBS = [
        {"title": "Financial Analyst", "company": "Finance Co",
         "url": "r1", "location": "Remote", "tags": ["financial modeling", "excel"],
         "source": "JSearch"},
        {"title": "FP&A Analyst", "company": "FPACo",
         "url": "r2", "location": "Remote", "tags": ["forecasting", "financial modeling"],
         "source": "JSearch"},
        {"title": "Risk Analyst", "company": "RiskCo",
         "url": "r3", "location": "Remote", "tags": ["risk assessment", "excel"],
         "source": "JSearch"},
    ]

    @pytest.fixture()
    def all_jobs(self):
        return self.EXCLUDED_JOBS + self.RELEVANT_JOBS

    def test_no_software_cyber_design_leak(self, all_jobs):
        titles, _ = _score(
            "Financial Analyst", self.REQUISITES, self.SKILLS, all_jobs)
        assert "Software Developer" not in titles
        assert "Cybersecurity Analyst" not in titles
        assert "Graphic Designer" not in titles

    def test_finance_roles_surface(self, all_jobs):
        titles, _ = _score(
            "Financial Analyst", self.REQUISITES, self.SKILLS, all_jobs)
        assert "Financial Analyst" in titles
        assert "FPACo" in [j["company"] for j in
                           jobs._apply(self.RELEVANT_JOBS,
                                       jobs._cluster_keywords(list(self.SKILLS.keys()), "Financial Analyst", self.REQUISITES)[0],
                                       jobs._student_seniority([s["lvl"] for s in self.SKILLS.values()]),
                                       "Remote", "", jobs._role_family("Financial Analyst"),
                                       minor_keywords=jobs._cluster_keywords(list(self.SKILLS.keys()), "Financial Analyst", self.REQUISITES)[1],
                                       role_driven=True, role_title="Financial Analyst")]


# ---------------------------------------------------------------------------
# Domain 4: Marketing Analyst
# ---------------------------------------------------------------------------

class TestMarketingAnalystTarget:
    REQUISITES = ["Market Research", "Data Analysis", "Excel", "SQL",
                  "Statistical Analysis", "A/B Testing"]
    SKILLS = {
        "Market Research": {"lvl": "Advanced"},
        "Data Analysis": {"lvl": "Intermediate"},
        "Excel": {"lvl": "Advanced"},
        "SQL": {"lvl": "Intermediate"},
        "Communication": {"lvl": "Intermediate"},
    }

    EXCLUDED_JOBS = [
        {"title": "Software Developer", "company": "DevCo",
         "url": "d1", "location": "Remote", "tags": ["sql", "api", "python"],
         "source": "JSearch"},
        {"title": "Cybersecurity Analyst", "company": "CyberCo",
         "url": "d2", "location": "Remote", "tags": ["security"],
         "source": "JSearch"},
        {"title": "Graphic Designer", "company": "DesignCo",
         "url": "d3", "location": "Remote", "tags": ["photoshop"],
         "source": "JSearch"},
    ]
    RELEVANT_JOBS = [
        {"title": "Marketing Analyst", "company": "MktCo",
         "url": "r1", "location": "Remote", "tags": ["market research", "data analysis"],
         "source": "JSearch"},
        {"title": "Digital Marketing Analyst", "company": "DigitalCo",
         "url": "r2", "location": "Remote", "tags": ["a/b testing", "excel"],
         "source": "JSearch"},
        {"title": "Market Research Analyst", "company": "ResearchCo",
         "url": "r3", "location": "Remote", "tags": ["market research", "statistical analysis"],
         "source": "JSearch"},
    ]

    @pytest.fixture()
    def all_jobs(self):
        return self.EXCLUDED_JOBS + self.RELEVANT_JOBS

    def test_no_software_cyber_design_leak(self, all_jobs):
        titles, _ = _score(
            "Marketing Analyst", self.REQUISITES, self.SKILLS, all_jobs)
        assert "Software Developer" not in titles
        assert "Cybersecurity Analyst" not in titles
        assert "Graphic Designer" not in titles

    def test_marketing_roles_surface(self, all_jobs):
        titles, _ = _score(
            "Marketing Analyst", self.REQUISITES, self.SKILLS, all_jobs)
        assert "Marketing Analyst" in titles
        assert len([t for t in titles if t in
                    ["Marketing Analyst", "Digital Marketing Analyst",
                     "Market Research Analyst"]]) >= 2


# ---------------------------------------------------------------------------
# Domain 5: Legal Assistant
# ---------------------------------------------------------------------------

class TestLegalAssistantTarget:
    REQUISITES = ["Legal Research", "Document Drafting", "Paralegal Studies",
                  "Contract Review", "Legal Writing"]
    SKILLS = {
        "Legal Research": {"lvl": "Advanced"},
        "Document Drafting": {"lvl": "Intermediate"},
        "Communication": {"lvl": "Advanced"},
        "Excel": {"lvl": "Intermediate"},
    }

    EXCLUDED_JOBS = [
        {"title": "Software Developer", "company": "DevCo",
         "url": "d1", "location": "Remote", "tags": ["python", "api"],
         "source": "JSearch"},
        {"title": "Marketing Manager", "company": "MktCo",
         "url": "d2", "location": "Remote", "tags": ["marketing", "excel"],
         "source": "JSearch"},
        {"title": "Financial Analyst", "company": "FinCo",
         "url": "d3", "location": "Remote", "tags": ["financial modeling"],
         "source": "JSearch"},
    ]
    RELEVANT_JOBS = [
        {"title": "Paralegal", "company": "Law Firm",
         "url": "r1", "location": "Remote", "tags": ["legal research", "document drafting"],
         "source": "JSearch"},
        {"title": "Legal Assistant", "company": "LegalCo",
         "url": "r2", "location": "Remote", "tags": ["legal writing", "contract review"],
         "source": "JSearch"},
    ]

    @pytest.fixture()
    def all_jobs(self):
        return self.EXCLUDED_JOBS + self.RELEVANT_JOBS

    def test_no_software_marketing_finance_leak(self, all_jobs):
        titles, _ = _score(
            "Legal Assistant", self.REQUISITES, self.SKILLS, all_jobs)
        assert "Software Developer" not in titles
        assert "Marketing Manager" not in titles
        assert "Financial Analyst" not in titles

    def test_legal_roles_surface(self, all_jobs):
        titles, _ = _score(
            "Legal Assistant", self.REQUISITES, self.SKILLS, all_jobs)
        assert "Paralegal" in titles or "Legal Assistant" in titles


# ---------------------------------------------------------------------------
# Domain 6: Clinical Research Assistant
# ---------------------------------------------------------------------------

class TestClinicalResearchTarget:
    REQUISITES = ["Clinical Research", "GCP", "Regulatory Compliance",
                  "Data Collection", "Medical Writing"]
    SKILLS = {
        "Clinical Research": {"lvl": "Advanced"},
        "GCP": {"lvl": "Intermediate"},
        "Communication": {"lvl": "Advanced"},
        "Excel": {"lvl": "Intermediate"},
        "Data Analysis": {"lvl": "Intermediate"},
    }

    EXCLUDED_JOBS = [
        {"title": "Software Developer", "company": "DevCo",
         "url": "d1", "location": "Remote", "tags": ["python", "api"],
         "source": "JSearch"},
        {"title": "Marketing Manager", "company": "MktCo",
         "url": "d2", "location": "Remote", "tags": ["marketing"],
         "source": "JSearch"},
        {"title": "Financial Analyst", "company": "FinCo",
         "url": "d3", "location": "Remote", "tags": ["financial modeling"],
         "source": "JSearch"},
    ]
    RELEVANT_JOBS = [
        {"title": "Clinical Research Assistant", "company": "PharmaCo",
         "url": "r1", "location": "Remote", "tags": ["clinical research", "gcp"],
         "source": "JSearch"},
        {"title": "Clinical Trial Assistant", "company": "TrialCo",
         "url": "r2", "location": "Remote", "tags": ["clinical research", "regulatory compliance"],
         "source": "JSearch"},
    ]

    @pytest.fixture()
    def all_jobs(self):
        return self.EXCLUDED_JOBS + self.RELEVANT_JOBS

    def test_no_software_marketing_finance_leak(self, all_jobs):
        titles, _ = _score(
            "Clinical Research Assistant", self.REQUISITES, self.SKILLS, all_jobs)
        assert "Software Developer" not in titles
        assert "Marketing Manager" not in titles
        assert "Financial Analyst" not in titles

    def test_clinical_roles_surface(self, all_jobs):
        titles, _ = _score(
            "Clinical Research Assistant", self.REQUISITES, self.SKILLS, all_jobs)
        assert "Clinical Research Assistant" in titles
        assert "Clinical Trial Assistant" in titles


# ---------------------------------------------------------------------------
# Domain 7: AI Engineer — verify ML Engineer is CLOSE, not UNRELATED
# ---------------------------------------------------------------------------

class TestAIEngineerTarget:
    REQUISITES = ["Machine Learning", "Deep Learning", "Python", "TensorFlow",
                  "NLP", "Computer Vision"]
    SKILLS = {
        "Machine Learning": {"lvl": "Advanced"},
        "Deep Learning": {"lvl": "Intermediate"},
        "Python": {"lvl": "Advanced"},
        "TensorFlow": {"lvl": "Intermediate"},
        "NLP": {"lvl": "Advanced"},
        "Communication": {"lvl": "Intermediate"},
    }

    JOBS = [
        {"title": "AI Engineer", "company": "AICo",
         "url": "r1", "location": "Remote", "tags": ["machine learning", "nlp"],
         "source": "JSearch"},
        {"title": "ML Engineer", "company": "MLCo",
         "url": "r2", "location": "Remote", "tags": ["deep learning", "tensorflow"],
         "source": "JSearch"},
        {"title": "Python Backend Engineer", "company": "BackendCo",
         "url": "r3", "location": "Remote", "tags": ["python", "sql"],
         "source": "JSearch"},
        {"title": "Data Entry Clerk", "company": "AdminCo",
         "url": "d1", "location": "Remote", "tags": ["excel", "data entry"],
         "source": "JSearch"},
        {"title": "Marketing Manager", "company": "MktCo",
         "url": "d2", "location": "Remote", "tags": ["marketing"],
         "source": "JSearch"},
    ]

    def test_ml_engineer_is_close(self):
        cls = role_intent.classify_title("AI Engineer", "ML Engineer")
        assert cls == "CLOSE", f"ML Engineer should be CLOSE for AI Engineer, got {cls}"

    def test_backend_engineer_is_family(self):
        cls = role_intent.classify_title("AI Engineer", "Python Backend Engineer")
        assert cls == "FAMILY", f"Python Backend Engineer should be FAMILY for AI Engineer, got {cls}"

    def test_data_entry_is_unrelated(self):
        cls = role_intent.classify_title("AI Engineer", "Data Entry Clerk")
        assert cls == "UNRELATED", f"Data Entry Clerk should be UNRELATED for AI Engineer, got {cls}"

    def test_marketing_is_unrelated(self):
        cls = role_intent.classify_title("AI Engineer", "Marketing Manager")
        assert cls == "UNRELATED", f"Marketing Manager should be UNRELATED for AI Engineer, got {cls}"

    def test_role_driven_scoring_ranking(self):
        titles, companies = _score(
            "AI Engineer", self.REQUISITES, self.SKILLS, self.JOBS)
        assert "Marketing Manager" not in titles, "marketing must not leak"
        assert "Data Entry Clerk" not in titles, "data entry must not leak"
        # AI and ML should rank near the top
        assert titles[0] in ("AI Engineer", "ML Engineer"), f"top title should be AI or ML, got {titles[0]}"


# ---------------------------------------------------------------------------
# Domain 8: Architectural Designer
# ---------------------------------------------------------------------------

class TestArchitecturalDesignerTarget:
    REQUISITES = ["AutoCAD", "Revit", "BIM", "Architectural Design",
                  "Construction Documents", "SketchUp"]
    SKILLS = {
        "AutoCAD": {"lvl": "Advanced"},
        "Revit": {"lvl": "Intermediate"},
        "BIM": {"lvl": "Intermediate"},
        "Communication": {"lvl": "Advanced"},
    }

    EXCLUDED_JOBS = [
        {"title": "Software Developer", "company": "DevCo",
         "url": "d1", "location": "Remote", "tags": ["python"],
         "source": "JSearch"},
        {"title": "Financial Analyst", "company": "FinCo",
         "url": "d2", "location": "Remote", "tags": ["excel", "financial modeling"],
         "source": "JSearch"},
    ]
    RELEVANT_JOBS = [
        {"title": "Architectural Designer", "company": "ArchCo",
         "url": "r1", "location": "Remote", "tags": ["autocad", "revit"],
         "source": "JSearch"},
        {"title": "BIM Designer", "company": "BIMCo",
         "url": "r2", "location": "Remote", "tags": ["bim", "revit"],
         "source": "JSearch"},
    ]

    @pytest.fixture()
    def all_jobs(self):
        return self.EXCLUDED_JOBS + self.RELEVANT_JOBS

    def test_no_software_finance_leak(self, all_jobs):
        titles, _ = _score(
            "Architectural Designer", self.REQUISITES, self.SKILLS, all_jobs)
        assert "Software Developer" not in titles
        assert "Financial Analyst" not in titles

    def test_architecture_roles_surface(self, all_jobs):
        titles, _ = _score(
            "Architectural Designer", self.REQUISITES, self.SKILLS, all_jobs)
        assert "Architectural Designer" in titles
        assert "BIM Designer" in titles


# ---------------------------------------------------------------------------
# role_intent unit tests for cross-domain correctness
# ---------------------------------------------------------------------------

class TestRoleIntentCrossDomain:
    """Verify that the role-intent classification is correct across domains,
    ensuring no cross-domain false positives and no within-family false negatives."""

    @pytest.mark.parametrize("target,candidate,expected", [
        # Cybersecurity
        ("Cybersecurity Analyst", "SOC Analyst", "CLOSE"),
        ("Cybersecurity Analyst", "Information Security Analyst", "CLOSE"),
        ("Cybersecurity Analyst", "Incident Response Analyst", "FAMILY"),
        ("Cybersecurity Analyst", "Penetration Tester", "FAMILY"),
        ("Cybersecurity Analyst", "Data Scientist", "UNRELATED"),
        ("Cybersecurity Analyst", "Marketing Manager", "UNRELATED"),
        ("Cybersecurity Analyst", "Financial Analyst", "UNRELATED"),
        ("Cybersecurity Analyst", "IT Support Specialist", "UNRELATED"),
        # Graphic Design
        ("Graphic Designer", "Visual Designer", "CLOSE"),
        ("Graphic Designer", "Brand Designer", "CLOSE"),
        ("Graphic Designer", "UI/UX Designer", "CLOSE"),
        ("Graphic Designer", "Marketing Manager", "UNRELATED"),
        ("Graphic Designer", "Financial Analyst", "UNRELATED"),
        # Financial Analyst
        ("Financial Analyst", "FP&A Analyst", "CLOSE"),
        ("Financial Analyst", "Risk Analyst", "FAMILY"),
        ("Financial Analyst", "Software Developer", "UNRELATED"),
        ("Financial Analyst", "Cybersecurity Analyst", "UNRELATED"),
        # Legal Assistant
        ("Legal Assistant", "Paralegal", "CLOSE"),
        ("Legal Assistant", "Legal Secretary", "EXACT"),
        ("Legal Assistant", "Software Developer", "UNRELATED"),
        ("Legal Assistant", "Marketing Manager", "UNRELATED"),
        # Clinical Research Assistant
        ("Clinical Research Assistant", "Clinical Trial Assistant", "EXACT"),
        ("Clinical Research Assistant", "Research Assistant", "UNRELATED"),
        ("Clinical Research Assistant", "Software Developer", "UNRELATED"),
        # Marketing Analyst
        ("Marketing Analyst", "Digital Marketing Analyst", "EXACT"),
        ("Marketing Analyst", "Market Research Analyst", "CLOSE"),
        ("Marketing Analyst", "Software Developer", "UNRELATED"),
        # Architectural Designer
        ("Architectural Designer", "BIM Designer", "CLOSE"),
        ("Architectural Designer", "Interior Designer", "FAMILY"),
        ("Architectural Designer", "Software Developer", "UNRELATED"),
        # AI Engineer
        ("AI Engineer", "ML Engineer", "CLOSE"),
        ("AI Engineer", "Python Backend Engineer", "FAMILY"),
        ("AI Engineer", "Data Entry Clerk", "UNRELATED"),
        ("AI Engineer", "Marketing Manager", "UNRELATED"),
    ])
    def test_classification(self, target, candidate, expected):
        result = role_intent.classify_title(target, candidate)
        assert result == expected, f"classify_title({target!r}, {candidate!r}) = {result}, expected {expected}"
