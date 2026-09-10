"""Seed the database with realistic sample data so the app looks alive on first launch.

Creates users for all three roles, several students, companies with defined roles,
a shared skill list, self-reported skill profiles, a curated reference "talent
catalog" of realistic roles, a few completed assessment attempts, and
pre-generated learning content.
"""
from . import models, genai, matching
from .database import init_db, get_cursor

USERS = [
    # (email, role, display_name, password)
    ("aisha@student.edu", "Student", "Aisha Rahman", "demo1234"),
    ("omar@student.edu", "Student", "Omar Haddad", "demo1234"),
    ("leila@student.edu", "Student", "Leila Chen", "demo1234"),
    ("marcus@student.edu", "Student", "Marcus Torres", "demo1234"),
    ("priya@student.edu", "Student", "Priya Nair", "demo1234"),
    ("sara@student.edu", "Student", "Sara Kovač", "demo1234"),
    ("tomas@student.edu", "Student", "Tomas Lindqvist", "demo1234"),
    ("yara@student.edu", "Student", "Yara El-Sayed", "demo1234"),
    ("hr@northstar.com", "Company", "Northstar Labs", "demo1234"),
    ("hr@signal.com", "Company", "Signal Works", "demo1234"),
    ("admin@univ.edu", "University Admin", "University Analytics", "demo1234"),
]

STUDENTS = [
    ("aisha@student.edu", "Aisha Rahman", "Aston University", "role-ai"),
    ("omar@student.edu", "Omar Haddad", "Aston University", "role-ai"),
    ("leila@student.edu", "Leila Chen", "Aston University", "role-data"),
    ("marcus@student.edu", "Marcus Torres", "Aston University", "role-ai"),
    ("priya@student.edu", "Priya Nair", "Aston University", "role-data"),
    ("sara@student.edu", "Sara Kovač", "Aston University", "role-ai"),
    ("tomas@student.edu", "Tomas Lindqvist", "Aston University", "role-data"),
    ("yara@student.edu", "Yara El-Sayed", "Nile University", "role-soc"),
]

EDUCATION_LEVELS = {
    "aisha@student.edu": "Undergraduate",
    "omar@student.edu": "Undergraduate",
    "leila@student.edu": "Graduate",
    "marcus@student.edu": "Undergraduate",
    "priya@student.edu": "Undergraduate",
    "sara@student.edu": "Graduate",
    "tomas@student.edu": "Bootcamp/Certificate",
    "yara@student.edu": "Undergraduate",
}

# Self-reported profile per student: list of (skill_name, level)
SELF_REPORTED = {
    "aisha@student.edu": [("Python", "Advanced"), ("Machine Learning", "Intermediate"),
                          ("Docker", "Beginner"), ("SQL", "Advanced"), ("Git", "Intermediate")],
    "omar@student.edu": [("Python", "Intermediate"), ("Machine Learning", "Beginner"),
                         ("Docker", "Beginner"), ("SQL", "Beginner")],
    "leila@student.edu": [("SQL", "Advanced"), ("Excel", "Advanced"), ("Python", "Intermediate"),
                          ("Tableau", "Intermediate")],
    "marcus@student.edu": [("Python", "Intermediate"), ("SQL", "Intermediate"),
                           ("Machine Learning", "Beginner"), ("Docker", "Beginner")],
    "priya@student.edu": [("SQL", "Intermediate"), ("Excel", "Intermediate"),
                          ("Python", "Beginner"), ("Tableau", "Beginner")],
    "sara@student.edu": [("Python", "Advanced"), ("Git", "Intermediate"), ("Docker", "Beginner"),
                         ("Machine Learning", "Intermediate"), ("SQL", "Intermediate")],
    "tomas@student.edu": [("SQL", "Beginner"), ("Excel", "Intermediate"), ("Python", "Beginner")],
    "yara@student.edu": [("SIEM", "Intermediate"), ("Cybersecurity", "Intermediate"),
                         ("Network Security", "Intermediate"), ("Linux", "Intermediate"),
                         ("Threat Detection", "Beginner"), ("Incident Response", "Beginner")],
}

# Some students already have verified skills from prior assessments.
VERIFIED = {
    "aisha@student.edu": [("Python", "Advanced"), ("SQL", "Advanced")],
    "leila@student.edu": [("SQL", "Advanced"), ("Excel", "Advanced")],
}

# Internal company-defined roles (companies manage these themselves).
INTERNAL_ROLES = [
    ("hr@northstar.com", "Junior AI Engineer",
     "Build and deploy ML models and pipelines for real product features.",
     [("Python", "Advanced", "Programming"), ("Machine Learning", "Intermediate", "AI"),
      ("Docker", "Intermediate", "DevOps"), ("SQL", "Advanced", "Data")],
     "role-ai"),
    ("hr@northstar.com", "Data Engineer",
     "Own the data pipelines and infrastructure that power analytics.",
     [("Python", "Advanced", "Programming"), ("SQL", "Advanced", "Data"),
      ("Docker", "Intermediate", "DevOps"), ("Git", "Intermediate", "DevOps")],
     "role-dataeng"),
    ("hr@signal.com", "Data Analyst",
     "Turn raw data into insight and dashboards that drive decisions.",
     [("SQL", "Advanced", "Data"), ("Excel", "Advanced", "Analytics"),
      ("Python", "Intermediate", "Programming"), ("Tableau", "Intermediate", "Visualization")],
     "role-data"),
]

# Reference catalog roles (read-only baseline from the SkillBridge Talent Catalog).
# Complete 8-14 skill lists per track so students get realistic, substantial gaps.
CATALOG_COMPANY_NAME = "SkillBridge Talent Catalog"

CATALOG_ROLES = [
    ("Junior AI Engineer",
     "Build, deploy, and maintain machine-learning features end to end.",
     [("Python", "Advanced", "Programming"), ("Machine Learning", "Intermediate", "AI"),
      ("Deep Learning", "Beginner", "AI"), ("SQL", "Advanced", "Data"),
      ("Statistics", "Intermediate", "Data"), ("Pandas", "Intermediate", "Data"),
      ("scikit-learn", "Intermediate", "AI"), ("Docker", "Intermediate", "DevOps"),
      ("Git", "Intermediate", "DevOps"), ("REST APIs", "Intermediate", "DevOps"),
      ("Communication", "Beginner", "Soft Skills"), ("Teamwork", "Beginner", "Soft Skills")]),
    ("Data Engineer",
     "Design and operate the pipelines, storage, and infrastructure behind analytics.",
     [("Python", "Advanced", "Programming"), ("SQL", "Advanced", "Data"),
      ("Docker", "Intermediate", "DevOps"), ("Data Engineering", "Intermediate", "Data"),
      ("ETL", "Intermediate", "Data"), ("Airflow", "Beginner", "Data"),
      ("Spark", "Beginner", "Data"), ("Cloud Security", "Beginner", "Security"),
      ("Git", "Intermediate", "DevOps"), ("CI/CD", "Intermediate", "DevOps"),
      ("Communication", "Beginner", "Soft Skills"), ("Problem Solving", "Intermediate", "Soft Skills")]),
    ("Data Analyst",
     "Transform raw data into decisions, dashboards, and stories for stakeholders.",
     [("SQL", "Advanced", "Data"), ("Excel", "Advanced", "Analytics"),
      ("Python", "Intermediate", "Programming"), ("Pandas", "Intermediate", "Data"),
      ("Tableau", "Intermediate", "Visualization"), ("Data Visualization", "Intermediate", "Visualization"),
      ("Statistics", "Intermediate", "Data"), ("Data Analysis", "Intermediate", "Data"),
      ("Data Storytelling", "Beginner", "Analytics"), ("Business Intelligence", "Beginner", "Analytics"),
      ("Communication", "Intermediate", "Soft Skills"), ("Critical Thinking", "Intermediate", "Soft Skills")]),
    ("Cloud Security Engineer",
     "Secure cloud workloads and respond to threats across the infrastructure.",
     [("Cybersecurity", "Intermediate", "Security"), ("Cloud Security", "Intermediate", "Security"),
      ("AWS", "Intermediate", "DevOps"), ("Linux", "Intermediate", "DevOps"),
      ("Network Security", "Intermediate", "Security"), ("Threat Detection", "Beginner", "Security"),
      ("Incident Response", "Beginner", "Security"), ("Vulnerability Management", "Intermediate", "Security"),
      ("Risk Assessment", "Intermediate", "Security"), ("Python", "Beginner", "Programming"),
      ("Communication", "Intermediate", "Soft Skills"), ("Critical Thinking", "Advanced", "Soft Skills")]),
    ("Financial Data Analyst",
     "Analyze financial data and build models that inform investment decisions.",
     [("Excel", "Advanced", "Analytics"), ("SQL", "Advanced", "Data"),
      ("Statistics", "Advanced", "Data"), ("Python", "Intermediate", "Programming"),
      ("Pandas", "Intermediate", "Data"), ("Data Visualization", "Intermediate", "Visualization"),
      ("Power BI", "Intermediate", "Visualization"), ("Business Intelligence", "Intermediate", "Analytics"),
      ("Risk Assessment", "Intermediate", "Security"), ("A/B Testing", "Intermediate", "Analytics"),
      ("Communication", "Intermediate", "Soft Skills"), ("Time Management", "Beginner", "Soft Skills")]),
    ("Backend Engineer",
     "Design and build the server-side services and APIs that power products at scale.",
     [("Python", "Advanced", "Programming"), ("Java", "Intermediate", "Programming"),
      ("FastAPI", "Intermediate", "Programming"), ("SQL", "Advanced", "Data"),
      ("REST APIs", "Advanced", "DevOps"), ("Docker", "Intermediate", "DevOps"),
      ("Git", "Intermediate", "DevOps"), ("Kubernetes", "Beginner", "DevOps"),
      ("SQLAlchemy", "Intermediate", "DevOps"), ("AWS", "Beginner", "DevOps"),
      ("Problem Solving", "Intermediate", "Soft Skills"), ("Communication", "Beginner", "Soft Skills")]),
    ("Frontend Developer",
     "Build polished, accessible interfaces that turn product vision into working screens.",
     [("JavaScript", "Advanced", "Programming"), ("TypeScript", "Advanced", "Programming"),
      ("React", "Advanced", "Programming"), ("HTML/CSS", "Advanced", "Programming"),
      ("REST APIs", "Intermediate", "DevOps"), ("Git", "Intermediate", "DevOps"),
      ("Node.js", "Intermediate", "Programming"), ("Data Visualization", "Beginner", "Visualization"),
      ("Communication", "Intermediate", "Soft Skills"), ("Problem Solving", "Intermediate", "Soft Skills"),
      ("Teamwork", "Beginner", "Soft Skills")]),
    ("DevOps / Platform Engineer",
     "Own the infrastructure, automation, and reliability behind software delivery.",
     [("Docker", "Advanced", "DevOps"), ("Kubernetes", "Intermediate", "DevOps"),
      ("CI/CD", "Intermediate", "DevOps"), ("Terraform", "Intermediate", "DevOps"),
      ("AWS", "Intermediate", "DevOps"), ("Linux", "Advanced", "DevOps"),
      ("Git", "Intermediate", "DevOps"), ("Python", "Intermediate", "Programming"),
      ("Cloud Security", "Beginner", "Security"), ("Problem Solving", "Intermediate", "Soft Skills")]),
    ("Machine Learning Engineer",
     "Take models from experiments to production, with monitoring and serving at scale.",
     [("Python", "Advanced", "Programming"), ("Machine Learning", "Advanced", "AI"),
      ("Deep Learning", "Intermediate", "AI"), ("PyTorch", "Intermediate", "AI"),
      ("TensorFlow", "Beginner", "AI"), ("Statistics", "Advanced", "Data"),
      ("Pandas", "Intermediate", "Data"), ("scikit-learn", "Intermediate", "AI"),
      ("Docker", "Intermediate", "DevOps"), ("REST APIs", "Intermediate", "DevOps"),
      ("Kubernetes", "Beginner", "DevOps"), ("AWS", "Beginner", "DevOps")]),
    ("Data Scientist",
     "Apply statistics and machine learning to model problems and drive decisions.",
     [("Python", "Advanced", "Programming"), ("Statistics", "Advanced", "Data"),
      ("Machine Learning", "Advanced", "AI"), ("SQL", "Advanced", "Data"),
      ("Pandas", "Advanced", "Data"), ("NumPy", "Advanced", "Data"),
      ("Data Visualization", "Intermediate", "Visualization"), ("scikit-learn", "Intermediate", "AI"),
      ("Deep Learning", "Beginner", "AI"), ("A/B Testing", "Intermediate", "Analytics"),
      ("Communication", "Intermediate", "Soft Skills"), ("Critical Thinking", "Advanced", "Soft Skills")]),
    ("Cybersecurity Analyst",
     "Monitor, investigate, and respond to security threats across the enterprise.",
     [("Cybersecurity", "Advanced", "Security"), ("Network Security", "Intermediate", "Security"),
      ("Threat Detection", "Intermediate", "Security"), ("Incident Response", "Intermediate", "Security"),
      ("Vulnerability Management", "Intermediate", "Security"), ("SIEM", "Intermediate", "Security"),
      ("Risk Assessment", "Intermediate", "Security"), ("Linux", "Beginner", "DevOps"),
      ("Windows Server", "Beginner", "Security"), ("Active Directory", "Beginner", "Security"),
      ("Communication", "Intermediate", "Soft Skills"), ("Critical Thinking", "Advanced", "Soft Skills")]),
    ("Cloud Engineer",
     "Architect and operate cloud infrastructure, ideally on AWS and Azure.",
     [("AWS", "Advanced", "DevOps"), ("Azure", "Intermediate", "DevOps"),
      ("Linux", "Advanced", "DevOps"), ("Docker", "Intermediate", "DevOps"),
      ("Kubernetes", "Intermediate", "DevOps"), ("Terraform", "Intermediate", "DevOps"),
      ("Cloud Security", "Intermediate", "Security"), ("CI/CD", "Intermediate", "DevOps"),
      ("Python", "Beginner", "Programming"), ("Problem Solving", "Intermediate", "Soft Skills")]),
    ("Business Intelligence Analyst",
     "Turn operational metrics into dashboards that guide strategy and growth.",
     [("SQL", "Advanced", "Data"), ("Excel", "Advanced", "Analytics"),
      ("Power BI", "Advanced", "Visualization"), ("Tableau", "Intermediate", "Visualization"),
      ("Business Intelligence", "Advanced", "Analytics"), ("Data Visualization", "Advanced", "Visualization"),
      ("Pandas", "Intermediate", "Data"), ("Python", "Intermediate", "Programming"),
      ("Data Storytelling", "Intermediate", "Analytics"), ("A/B Testing", "Beginner", "Analytics"),
      ("Communication", "Advanced", "Soft Skills")]),
    ("Product Analyst",
     "Analyze user behavior to prioritize what the product team builds next.",
     [("SQL", "Advanced", "Data"), ("Excel", "Advanced", "Analytics"),
      ("A/B Testing", "Intermediate", "Analytics"), ("Statistics", "Intermediate", "Data"),
      ("Data Analysis", "Advanced", "Data"), ("Data Storytelling", "Intermediate", "Analytics"),
      ("Python", "Beginner", "Programming"), ("Pandas", "Beginner", "Data"),
      ("Communication", "Advanced", "Soft Skills"), ("Critical Thinking", "Advanced", "Soft Skills")]),
    # --- Phase B: small representative set of non-CS roles (anchor/demo).
    # These let offline/demo flows recommend real careers for the Phase A
    # non-CS profiles without turning the catalog into a huge occupation DB.
    ("Graphic Designer",
     "Create visual identities, layouts, and print/digital assets for brands.",
     [("Adobe Photoshop", "Advanced", "Design"), ("Illustrator", "Advanced", "Design"),
      ("Typography", "Intermediate", "Design"), ("Brand Identity", "Intermediate", "Design"),
      ("Color Theory", "Intermediate", "Design")]),
    ("Marketing Analyst",
     "Turn market and campaign data into segmentation, positioning, and acquisition decisions.",
     [("Market Research", "Advanced", "Marketing"), ("Google Analytics", "Intermediate", "Marketing"),
      ("SEO", "Intermediate", "Marketing"), ("Customer Segmentation", "Intermediate", "Marketing"),
      ("Campaign Planning", "Intermediate", "Marketing")]),
    ("Clinical Research Assistant",
     "Support clinical studies with documentation, data collection, and patient-facing coordination.",
     [("Clinical Research", "Intermediate", "Clinical"), ("Research Methods", "Intermediate", "Clinical"),
      ("Data Collection", "Intermediate", "Clinical"),
      ("Medical Documentation", "Intermediate", "Clinical"),
      ("Patient Communication", "Intermediate", "Clinical")]),
    ("Architectural Designer",
     "Develop architectural drawings and models that turn design intent into buildable space.",
     [("AutoCAD", "Advanced", "Architecture"), ("Revit", "Intermediate", "Architecture"),
      ("Architectural Drawing", "Advanced", "Architecture"),
      ("Spatial Planning", "Intermediate", "Architecture"),
      ("3D Modeling", "Intermediate", "Architecture")]),
    ("Financial Analyst",
     "Build models and forecasts that inform planning, budgeting, and investment decisions.",
     [("Financial Modeling", "Advanced", "Finance"), ("Forecasting", "Advanced", "Finance"),
      ("Budget Analysis", "Intermediate", "Finance"), ("Excel", "Advanced", "Finance"),
      ("Data Analysis", "Intermediate", "Finance")]),
    ("Legal Assistant",
     "Support legal teams with research, drafting, client communication, and case-file organization.",
     [("Legal research and writing", "Intermediate", "Legal"),
      ("Dispute resolution and mediation", "Intermediate", "Legal"),
      ("Client advocacy", "Intermediate", "Legal"),
      ("Legal drafting", "Intermediate", "Legal"),
      ("Court etiquette", "Beginner", "Legal")]),
    # --- Additional clinical reference roles: give healthcare CVs (e.g. a
    # dentist profile) an honest local target even when the live ESCO lookup is
    # unreachable. Licensed titles automatically carry the professional-boundary
    # note in recommendations; these are study anchors, not credentials.
    ("Dentist (General Practice)",
     "Diagnose, treat, and prevent dental conditions across routine and complex care.",
     [("Dentistry", "Advanced", "Clinical"), ("Treatment Planning", "Advanced", "Clinical"),
      ("Dental Radiography", "Intermediate", "Clinical"), ("Sterilization", "Advanced", "Clinical"),
      ("Anatomy", "Intermediate", "Clinical"), ("Orthodontics", "Beginner", "Clinical"),
      ("Patient Communication", "Intermediate", "Clinical"),
      ("Clinical Documentation", "Intermediate", "Clinical")]),
    ("Dental Assistant",
     "Support dentists chairside with patient preparation, imaging, and instrument sterilization.",
     [("Sterilization", "Advanced", "Clinical"), ("Dental Radiography", "Intermediate", "Clinical"),
      ("Patient Communication", "Intermediate", "Clinical"),
      ("Dental Instrumentation", "Intermediate", "Clinical"),
      ("Medical Documentation", "Intermediate", "Clinical"),
      ("Infection Control", "Advanced", "Clinical"),
      ("Communication", "Intermediate", "Soft Skills"),
      ("Equipment Maintenance", "Beginner", "Clinical")]),
    ("Dental Hygienist",
     "Deliver preventive oral care: cleanings, scaling, fluoride, and oral-health education.",
     [("Dental Hygiene", "Advanced", "Clinical"), ("Periodontal Care", "Intermediate", "Clinical"),
      ("Oral Health Education", "Intermediate", "Clinical"),
      ("Sterilization", "Intermediate", "Clinical"),
      ("Dental Radiography", "Intermediate", "Clinical"),
      ("Preventive Dentistry", "Beginner", "Clinical"),
      ("Patient Communication", "Intermediate", "Clinical"),
      ("Communication", "Intermediate", "Soft Skills")]),
]

SOC_ROLE_KEY = "role-soc"
SOC_ROLE_TITLE = "Cybersecurity Analyst"

# Completed assessment attempts for richer seed data.
ATTEMPTS = [
    ("aisha@student.edu", "Python", 92, True, "Advanced", "Advanced", 0),
    ("aisha@student.edu", "SQL", 88, True, "Advanced", "Advanced", 0),
    ("leila@student.edu", "SQL", 90, True, "Advanced", "Advanced", 0),
    ("leila@student.edu", "Excel", 84, True, "Advanced", "Advanced", 0),
    ("sara@student.edu", "Python", 95, True, "Advanced", "Advanced", 1),
    ("omar@student.edu", "Python", 45, False, "Intermediate", "Intermediate", 1),
]


UNIVERSITIES = [
    # ("Country", ["universities", ...])
    ("United Kingdom", ["Aston University", "University of Birmingham", "Imperial College London",
                        "University of Oxford", "University of Cambridge", "University of Manchester",
                        "King's College London", "University of Edinburgh"]),
    ("United States", ["Arizona State University", "Georgia Institute of Technology", "MIT",
                       "Stanford University", "University of California, Berkeley", "Carnegie Mellon University",
                       "University of Texas at Austin", "University of Washington"]),
    ("United Arab Emirates", ["Khalifa University", "American University of Sharjah", "United Arab Emirates University",
                             "University of Sharjah", "Zayed University", "Abu Dhabi University"]),
    ("Saudi Arabia", ["King Fahd University of Petroleum and Minerals", "King Abdulaziz University",
                      "King Saud University", "KAUST", "Prince Sultan University", "Effat University"]),
    ("Egypt", ["Cairo University", "Ain Shams University", "Alexandria University", "Nile University",
               "American University in Cairo", "German University in Cairo", "Future University in Egypt",
               "Helwan University", "Misr International University"]),
    ("India", ["Indian Institute of Technology (IIT), Bombay", "Indian Institute of Technology (IIT), Delhi",
               "Birla Institute of Technology and Science (BITS) Pilani", "VIT Vellore",
               "National Institute of Technology (NIT) Trichy", "Delhi University"]),
    ("Germany", ["Technical University of Munich", "RWTH Aachen", "University of Stuttgart",
                 "KIT Karlsruhe", "LMU Munich", "Humboldt University of Berlin"]),
    ("Canada", ["University of Toronto", "University of Waterloo", "University of British Columbia",
                "McGill University", "University of Alberta", "Simon Fraser University"]),
]


# Country → city reference for the cascading signup dropdown. Also merged with
# distinct locations already stored on users/companies so new real entries appear.
CITIES = {
    "United Kingdom": ["London", "Birmingham", "Manchester", "Edinburgh", "Leeds", "Glasgow",
                       "Liverpool", "Bristol", "Sheffield", "Newcastle", "Nottingham", "Cardiff",
                       "Belfast", "Southampton"],
    "United States": ["New York", "San Francisco", "Seattle", "Austin", "Boston", "Chicago",
                      "Los Angeles", "Denver", "Atlanta", "Washington DC", "Houston", "Portland"],
    "United Arab Emirates": ["Dubai", "Abu Dhabi", "Sharjah", "Ajman", "Ras Al Khaimah"],
    "Saudi Arabia": ["Riyadh", "Jeddah", "Dammam", "Khobar", "Mecca", "Medina"],
    "Egypt": ["Cairo", "Alexandria", "Giza", "Mansoura", "Tanta", "Ismailia"],
    "India": ["Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Pune", "Kolkata", "Ahmedabad"],
    "Germany": ["Berlin", "Munich", "Frankfurt", "Hamburg", "Stuttgart", "Cologne", "Dresden"],
    "Canada": ["Toronto", "Vancouver", "Montreal", "Ottawa", "Calgary", "Edmonton", "Waterloo"],
}


def _sample_cv(name, email, university, skills):
    lines = [
        f"{name}\n{email} | {university}",
        "EDUCATION", f"BSc Computer Science, {university}, expected 2027",
        "KEY SKILLS",
    ]
    lines.append(", ".join(f"{s} ({lvl})" for s, lvl in skills))
    lines += ["PROJECTS",
              "Built a data analysis dashboard for a coursework project.",
              "Worked on a team project applying machine learning methods to a real dataset.",
              "EXPERIENCE", "Internship contributing to software and data workflows."]
    return "\n".join(lines)


def _category(name):
    return genai.FALLBACK_SKILL_CATEGORIES.get(name, "General")


def seed():
    init_db()
    with get_cursor() as c:
        c.executescript("""
            DELETE FROM google_registrations; DELETE FROM password_resets;
            DELETE FROM email_verifications;
            DELETE FROM sessions; DELETE FROM assessment_attempts; DELETE FROM tutor_messages;
            DELETE FROM learning_practice_attempts; DELETE FROM scenario_attempts; DELETE FROM saved_roles;
            DELETE FROM personalized_paths; DELETE FROM learning_lessons;
            DELETE FROM learning_diagnostics; DELETE FROM learning_path_items; DELETE FROM verified_skills;
            DELETE FROM self_reported_skills; DELETE FROM role_skills;
            DELETE FROM roles; DELETE FROM students; DELETE FROM companies;
            DELETE FROM skills; DELETE FROM users;
        """)

    # users (password hashed via the new create_user signature).
    # Seed/demo accounts are pre-verified so the app works on first launch.
    # Every account carries a location so the live roles feed is demoable.
    USER_META = {
        "aisha@student.edu": ("United Kingdom", "Birmingham"),
        "omar@student.edu": ("United Kingdom", "Birmingham"),
        "leila@student.edu": ("United Kingdom", "Birmingham"),
        "marcus@student.edu": ("United Kingdom", "Birmingham"),
        "priya@student.edu": ("United Kingdom", "Birmingham"),
        "sara@student.edu": ("United Kingdom", "Birmingham"),
        "tomas@student.edu": ("United Kingdom", "Birmingham"),
        "hr@northstar.com": ("United Kingdom", "Birmingham"),
        "hr@signal.com": ("United Kingdom", "London"),
        "admin@univ.edu": ("United Kingdom", "Birmingham"),
    }
    # University Admins belong to an institution: their cohort is scoped to the
    # students at that university (independent learners / other institutions excluded).
    ADMIN_UNIVERSITY = {
        "admin@univ.edu": "Aston University",
    }
    for email, role, display, password in USERS:
        country, location = USER_META.get(email, ("", ""))
        university = ADMIN_UNIVERSITY.get(email)
        models.create_user(email, role, display, password=password, verified=1,
                           country=country, location=location, university=university)

    # reference country + university list (used by the cascading signup dropdown)
    with get_cursor() as c:
        c.execute("DELETE FROM universities")
        c.execute("DELETE FROM cities")
    for country, unis in UNIVERSITIES:
        for uni in unis:
            models.add_university(country, uni)
    for country, cities in CITIES.items():
        for city in cities:
            models.add_city(country, city)

    # companies
    company_ids = {}
    companies = [
        ("hr@northstar.com", "Northstar Labs", "AI / Software", "Birmingham"),
        ("hr@signal.com", "Signal Works", "Data & Analytics", "London"),
        ("catalog@skillbridge.io", CATALOG_COMPANY_NAME, "Reference", ""),
    ]
    for email, name, industry, location in companies:
        u = (models.get_user_by_email(email) if not email.startswith("catalog")
             else {"id": None})
        comp = models.create_company(name, industry, user_id=u["id"], location=location)
        company_ids[email] = comp["id"]

    # internal roles
    role_ids = {}
    for email, title, desc, skills, key in INTERNAL_ROLES:
        role = models.create_role(company_ids[email], title, [
            {"name": n, "level": lvl, "category": cat} for (n, lvl, cat) in skills
        ], description=desc, source="company")
        role_ids[key] = role["id"]

    # reference catalog roles
    catalog_company_id = company_ids["catalog@skillbridge.io"]
    for title, desc, skills in CATALOG_ROLES:
        role = models.create_role(catalog_company_id, title, [
            {"name": n, "level": lvl, "category": cat} for (n, lvl, cat) in skills
        ], description=desc, is_reference=1, source="catalog")
        if title == SOC_ROLE_TITLE:
            role_ids[SOC_ROLE_KEY] = role["id"]

    # students (with cohort confirmed for the university view)
    student_ids = {}
    for email, name, uni, role_key in STUDENTS:
        u = models.get_user_by_email(email)
        el = EDUCATION_LEVELS.get(email)
        sid = models.create_student(name, email, uni, user_id=u["id"], education_level=el)["id"]
        models.update_student(sid, target_role_id=role_ids[role_key], cohort_confirmed=1)
        student_ids[email] = sid

    # ensure education_level on students (explicit, in case create_student path differed)
    for email, level in EDUCATION_LEVELS.items():
        models.update_student(student_ids[email], education_level=level)

    # self-reported + verified skills
    for email, skills in SELF_REPORTED.items():
        models.replace_self_reported_skills(student_ids[email], [
            {"name": n, "level": lvl, "category": _category(n)}
            for (n, lvl) in skills
        ])
    for email, skills in VERIFIED.items():
        for (n, lvl) in skills:
            sk = models.get_skill_by_name(n)
            models.update_verified_skill(student_ids[email], sk["id"], lvl)

    # pre-generate learning content for each student's current gaps (uses real GenAI if available)
    for email, sid in student_ids.items():
        _pregen_learning(sid)

    # completed assessment attempts
    for email, skill_name, score, passed, before, after, nflags in ATTEMPTS:
        sk = models.get_skill_by_name(skill_name)
        questions = genai.generate_quiz(skill_name, "seed", num_questions=3)
        flags = []
        for i in range(nflags):
            flags.append({"code": "tab_switch", "label": "Tab switch detected", "severity": "warning",
                          "detail": "Assessment window lost focus.", "seed": True})
        models.create_assessment_attempt(
            student_ids[email], sk["id"], question_json(questions), "[]",
            score, int(passed), flag_json(flags), before, after)
        # ensure verified profile consistent with passed attempts
        if passed and score >= 70:
            models.update_verified_skill(student_ids[email], sk["id"], after)


def question_json(questions):
    import json
    return json.dumps(questions)


def flag_json(flags):
    import json
    return json.dumps(flags)


def _pregen_learning(sid):
    student = models.get_student(sid)
    role = student.get("target_role")
    if not role:
        return
    gaps = matching.gap_skills(student, role)
    studying = f"Studying at {student['university']}" if student.get("university") else "Independent learner"
    ctx = f"{studying}; focused on becoming a {role['title']}."
    for g in gaps:
        item = genai.generate_learning_item(g["skill_name"], g.get("category"), role["title"], ctx)
        models.upsert_learning_item(sid, g["skill_id"], item["explanation"],
                                    item["practice_exercise"], item["mini_project"],
                                    item.get("resources") or [], item.get("roadmap") or None,
                                    modules=item.get("modules"),
                                    blueprint_version=item.get("blueprint_version"),
                                    blueprint_competencies=item.get("blueprint_competencies"))


def ensure_catalog_roles():
    """Backfill new catalog reference roles into existing demo databases.

    Startup migrations add columns, but seed data is created only for a fresh DB.
    Keep this idempotent so transferred demo databases gain newly added reference
    roles without resetting or deleting any user work.
    """
    init_db()
    with get_cursor() as c:
        row = c.execute("SELECT id FROM companies WHERE name=?", (CATALOG_COMPANY_NAME,)).fetchone()
        if row:
            catalog_company_id = row["id"]
        else:
            cur = c.execute(
                "INSERT INTO companies (name, industry, location, user_id) VALUES (?,?,?,?)",
                (CATALOG_COMPANY_NAME, "Reference", "", None),
            )
            catalog_company_id = cur.lastrowid
        existing = {
            (r["title"] or "").strip().lower()
            for r in c.execute(
                "SELECT title FROM roles WHERE is_reference=1 AND source='catalog'"
            ).fetchall()
        }
    for title, desc, skills in CATALOG_ROLES:
        if title.strip().lower() in existing:
            continue
        models.create_role(catalog_company_id, title, [
            {"name": n, "level": lvl, "category": cat} for (n, lvl, cat) in skills
        ], description=desc, is_reference=1, source="catalog")


if __name__ == "__main__":
    seed()
    print("Seed complete.")
