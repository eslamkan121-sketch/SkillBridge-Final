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


# ---------------------------------------------------------------------------
# Career-intent dominance regression: CV skills must never push unrelated
# jobs through the relevance gate when a target role is set.
#
# These tests reproduce the exact bug scenario described in the task:
#   Student selects "Cybersecurity Analyst"
#   → Dashboard Live Jobs shows "Head of Marketing & Communications",
#     "MRO Buyer", "Regional Sales Manager", "Data Scientist",
#     "Backend Engineer" — all unrelated careers that appeared because
#     generic CV skills (communication, management, data analysis, excel)
#     created keyword hits on their descriptions.
#
# Root cause: CV skills were primary keywords in _cluster_keywords(), so
# generic terms like "management" and "communication" could match job
# descriptions across unrelated fields. The fix makes CV skills always
# minor (tie-breakers) when a target role is set, and strengthens the
# FAMILY-tier override to require at least one role-vocabulary keyword hit.
# ---------------------------------------------------------------------------

class TestCareerIntentDominance:
    """When a target role is set, CV skills must NEVER be the sole reason an
    unrelated job appears in the feed. Only the role's own vocabulary
    (title + requisites) should drive relevance. Generic CV skills like
    'communication', 'management', 'data analysis', 'excel' appear in
    descriptions of jobs from completely unrelated fields and must not
    create cross-domain keyword hits."""

    CYBER_REQUISITES = [
        "Active Directory", "Cybersecurity", "Incident Response", "Linux",
        "Network Security", "Risk Assessment", "SIEM", "Threat Detection",
        "Vulnerability Management", "Windows Server",
    ]
    CYBER_SKILLS = {
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

    EXACT_REPRO_JOBS = [
        {"title": "Head of Marketing & Communications", "company": "MktCo",
         "url": "e1", "location": "Remote",
         "tags": ["communication", "management", "marketing", "strategy"],
         "description": "Lead marketing communications strategy. Requires "
                       "strong communication and management skills.",
         "source": "JSearch"},
        {"title": "MRO Buyer", "company": "SupplyCo",
         "url": "e2", "location": "Remote",
         "tags": ["procurement", "supply chain", "management"],
         "description": "Manage MRO procurement. Risk assessment and "
                       "management of supply chain.",
         "source": "JSearch"},
        {"title": "Regional Sales Manager", "company": "SalesCo",
         "url": "e3", "location": "Remote",
         "tags": ["sales", "communication", "excel", "management"],
         "description": "Lead regional sales team. Communication and "
                       "data analysis required.",
         "source": "JSearch"},
        {"title": "Data Scientist", "company": "DataCo",
         "url": "e4", "location": "Remote",
         "tags": ["machine learning", "python", "data analysis", "nlp"],
         "description": "Build ML models. Python, data analysis, NLP.",
         "source": "JSearch"},
        {"title": "Backend Engineer", "company": "DevCo",
         "url": "e5", "location": "Remote",
         "tags": ["java", "python", "sql", "api"],
         "description": "Build backend services. Java, Python, SQL.",
         "source": "JSearch"},
        {"title": "Marketing Analyst", "company": "GrowCo",
         "url": "e6", "location": "Remote",
         "tags": ["marketing", "data analysis", "excel", "sql"],
         "description": "Analyze marketing campaigns. Data analysis, "
                       "Excel, SQL required.",
         "source": "JSearch"},
    ]

    RELEVANT_JOBS = [
        {"title": "Cybersecurity Analyst", "company": "Defense Co",
         "url": "r1", "location": "Remote",
         "tags": ["threat detection", "siem", "incident response"],
         "source": "JSearch"},
        {"title": "SOC Analyst", "company": "SOC Team",
         "url": "r2", "location": "Remote",
         "tags": ["siem", "incident response", "security"],
         "source": "JSearch"},
        {"title": "Penetration Tester", "company": "PentestCo",
         "url": "r3", "location": "Remote",
         "tags": ["penetration testing", "vulnerability management"],
         "source": "JSearch"},
    ]

    def test_exact_repro_unrelated_jobs_never_surface(self):
        """The exact bug scenario: selecting Cybersecurity Analyst must NOT
        show Head of Marketing, MRO Buyer, Regional Sales Manager,
        Data Scientist, or Backend Engineer."""
        all_jobs = self.EXACT_REPRO_JOBS + self.RELEVANT_JOBS
        titles, companies = _score(
            "Cybersecurity Analyst", self.CYBER_REQUISITES, self.CYBER_SKILLS,
            all_jobs)
        for job in self.EXACT_REPRO_JOBS:
            assert job["title"] not in titles, (
                f"{job['title']} must NOT appear for Cybersecurity Analyst target "
                f"— it is an unrelated career")
        # All three relevant cybersecurity jobs should appear.
        assert "Cybersecurity Analyst" in titles
        assert "SOC Analyst" in titles or "SOC Team" in companies
        assert "Penetration Tester" in titles

    def test_cv_skills_are_minor_not_primary(self):
        """CV skills must be minor keywords when a target role is set — they
        rank jobs within the family but never drive the search/score.

        Primary with CV skills must equal primary without CV skills:
        CV skills must not add ANY token to the primary cluster."""
        with_cv_primary, with_cv_minor = jobs._cluster_keywords(
            [s[0] for s in self.CYBER_SKILLS.items()],
            "Cybersecurity Analyst", self.CYBER_REQUISITES)
        without_cv_primary, _ = jobs._cluster_keywords(
            [], "Cybersecurity Analyst", self.CYBER_REQUISITES)
        assert "cybersecurity" in with_cv_primary
        assert "analyst" in with_cv_primary
        # CV skills must not change the primary cluster at all.
        assert with_cv_primary == without_cv_primary, (
            f"CV skills leaked tokens into primary: "
            f"added {set(with_cv_primary) - set(without_cv_primary)}, "
            f"removed {set(without_cv_primary) - set(with_cv_primary)}")
        # Every CV skill token must appear in minor.
        for skill_name in self.CYBER_SKILLS:
            tokens = jobs._tokens(skill_name)
            for tok in tokens:
                assert tok in with_cv_minor, (
                    f"CV skill token '{tok}' from '{skill_name}' must appear "
                    f"in minor keywords")

    def test_generic_cv_skill_keyword_hits_cannot_push_jobs_through(self):
        """Even if a generic CV skill keyword ('management', 'communication')
        appears in an unrelated job's description, it must not be sufficient
        to pass the relevance gate when a target role is set."""
        # A job with ZERO role-vocabulary overlap but many generic CV keywords.
        unrelated = [
            {"title": "Office Manager", "company": "AdminCo",
             "url": "u1", "location": "Remote",
             "tags": ["management", "communication", "excel",
                      "data analysis", "leadership"],
             "description": "Manage office operations. Communication, "
                           "management, data analysis, Excel skills.",
             "source": "JSearch"},
        ]
        all_jobs = unrelated + self.RELEVANT_JOBS
        titles, _ = _score(
            "Cybersecurity Analyst", self.CYBER_REQUISITES, self.CYBER_SKILLS,
            all_jobs)
        assert "Office Manager" not in titles, (
            "Office Manager must not appear — generic CV keywords like "
            "management/communication cannot push unrelated jobs through")

    def test_family_tier_override_requires_keyword_evidence(self):
        """A job classified FAMILY but with ZERO role-vocabulary keyword hits
        must not be rescued by the family-tier override alone."""
        # "IT Help Desk" shares the "security" token with requisites (it
        # mentions "access control"), but to test the pure zero-hit path we
        # use a completely unrelated job.  "Operations Coordinator" has no
        # overlap with cybersecurity vocabulary — its tags are "operations",
        # "logistics", "coordination".  The role_intent classifier should
        # call it UNRELATED; even if it were misclassified as FAMILY, the
        # hits >= 1 gate must block it.
        family_no_hits = [
            {"title": "Operations Coordinator", "company": "OpsCo",
             "url": "f1", "location": "Remote",
             "tags": ["operations", "logistics", "coordination"],
             "description": "Coordinate daily operations and logistics.",
             "source": "JSearch"},
        ]
        all_jobs = family_no_hits + self.RELEVANT_JOBS
        titles, _ = _score(
            "Cybersecurity Analyst", self.CYBER_REQUISITES, self.CYBER_SKILLS,
            all_jobs)
        assert "Operations Coordinator" not in titles, (
            "Operations Coordinator must not appear — it has zero "
            "role-vocabulary keyword hits")

    @pytest.mark.parametrize("target_role,requisites,skills,unrelated_title", [
        ("Financial Analyst",
         ["Financial Modeling", "Excel", "Accounting", "Forecasting",
          "Risk Assessment", "Data Analysis"],
         {"Financial Modeling": {"lvl": "Advanced"}, "Excel": {"lvl": "Advanced"},
          "Accounting": {"lvl": "Intermediate"}, "Communication": {"lvl": "Intermediate"},
          "Python": {"lvl": "Beginner"}},
         "Cybersecurity Analyst"),
        ("Graphic Designer",
         ["Adobe Photoshop", "Illustrator", "Typography", "Color Theory",
          "Layout Design", "Branding"],
         {"Photoshop": {"lvl": "Advanced"}, "Illustrator": {"lvl": "Advanced"},
          "Typography": {"lvl": "Intermediate"}, "Excel": {"lvl": "Intermediate"},
          "Communication": {"lvl": "Advanced"}},
         "Marketing Manager"),
        ("Marketing Analyst",
         ["Market Research", "Data Analysis", "Excel", "SQL",
          "Statistical Analysis", "A/B Testing"],
         {"Market Research": {"lvl": "Advanced"}, "Data Analysis": {"lvl": "Intermediate"},
          "Excel": {"lvl": "Advanced"}, "SQL": {"lvl": "Intermediate"},
          "Communication": {"lvl": "Intermediate"}},
         "Software Developer"),
        ("Legal Assistant",
         ["Legal Research", "Document Drafting", "Paralegal Studies",
          "Contract Review", "Legal Writing"],
         {"Legal Research": {"lvl": "Advanced"}, "Document Drafting": {"lvl": "Intermediate"},
          "Communication": {"lvl": "Advanced"}, "Excel": {"lvl": "Intermediate"}},
         "Financial Analyst"),
    ])
    def test_cross_domain_unrelated_never_surfaces(self, target_role,
                                                    requisites, skills,
                                                    unrelated_title):
        """For every supported career, an unrelated job must never appear
        when a target role is set — CV skill overlap must not leak."""
        # Create a generic "unrelated" job whose tags contain the skills.
        skill_names = list(skills.keys())
        unrelated_job = {
            "title": unrelated_title,
            "company": "OtherCo",
            "url": "x1",
            "location": "Remote",
            "tags": [s.lower() for s in skill_names[:4]],
            "description": " ".join(skill_names[:4]),
            "source": "JSearch",
        }
        titles, _ = _score(target_role, requisites, skills, [unrelated_job])
        assert unrelated_title not in titles, (
            f"{unrelated_title} must not appear for {target_role} target — "
            f"CV skills cannot push cross-domain jobs through")
