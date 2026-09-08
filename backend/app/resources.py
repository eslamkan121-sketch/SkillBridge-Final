"""Learning resource retrieval for SkillBridge learning-path items.

A skill-gap learning item must surface real, current resources (videos, articles,
official docs, courses) ranked most-helpful-first — not the model inventing
plausible-looking links.

Two sources:
  1. Live retrieval via a search API when a key is configured
     (SKILLBRIDGE_YOUTUBE_API_KEY for videos via the YouTube Data API).
  2. A curated index of real, stable URLs per skill/category maintained here,
     so the demo works offline and the links are always genuine.

Curated links are validated with a cheap HTTP check when the network is
reachable; links that provably fail (4xx/5xx/connection refused) are dropped.
For YouTube, a thumbnail probe is used since the watch page returns 200 even
for removed/private videos.
"""
import ipaddress
import os
import re
from urllib.parse import urlparse, parse_qs

YOUTUBE_API_KEY = os.environ.get("SKILLBRIDGE_YOUTUBE_API_KEY", "")


def _res(res_type, title, url, source):
    return {"type": res_type, "title": title, "url": url, "source": source}


_TYPE_LABELS = {
    "doc": "Documentation",
    "documentation": "Documentation",
    "tutorial": "Tutorial",
    "article": "Article",
    "video": "Video",
    "course": "Course",
    "reference": "Reference",
    "hands_on_lab": "Hands-on Lab",
    "interactive_lab": "Interactive Lab",
    "lesson": "Lesson",
    "exercise": "Exercise",
    "coding_problem": "Coding Problem",
    "project": "Project",
    "simulation": "Simulation",
    "assessment": "Assessment",
    "official_guide": "Official Guide",
    "certification_training": "Certification Training",
    "other": "Other",
}

_TYPE_CTA = {
    "video": "Watch Video",
    "hands_on_lab": "Start Lab",
    "interactive_lab": "Start Lab",
    "documentation": "Open Documentation",
    "doc": "Open Documentation",
    "official_guide": "Read Official Guide",
    "reference": "Read Reference",
    "article": "Read Article",
    "tutorial": "Open Tutorial",
    "lesson": "Open Lesson",
    "course": "Enroll in Course",
    "exercise": "Start Exercise",
    "coding_problem": "Open Coding Challenge",
    "project": "Open Project",
    "simulation": "Run Simulation",
    "assessment": "Take Assessment",
    "certification_training": "Start Certification Training",
    "other": "Open Resource",
}

# Minutes a typical student should spend with each resource type. Used to make
# every surfaced resource honest about the effort it demands.
_TYPE_MINUTES = {
    "video": 20,
    "documentation": 20,
    "reference": 25,
    "article": 15,
    "tutorial": 40,
    "course": 45,
    "hands_on_lab": 45,
    "interactive_lab": 45,
    "exercise": 20,
    "coding_problem": 30,
    "project": 60,
    "simulation": 25,
    "assessment": 25,
    "official_guide": 25,
    "certification_training": 60,
    "lesson": 30,
    "other": 20,
}

_CANONICAL_TYPE = {
    "doc": "documentation",
}


_UNSAFE_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "0.0.0.0",
    "127.0.0.1",
    "::1",
    "metadata.google.internal",
}


_UNSAFE_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
)


def _tokens(value):
    return set(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def canonical_resource_type(res_type):
    """Normalize a resource type id to one of the documented type values."""
    value = str(res_type or "article").strip().lower()
    value = _CANONICAL_TYPE.get(value, value)
    return value if value in _TYPE_LABELS else "other"


def is_safe_public_url(url):
    """Return True only for ordinary public http(s) resource URLs.

    The app never fetches student-supplied resource URLs, but this guard keeps
    both curated and retrieved links away from malformed, localhost, private-IP,
    and metadata-service targets before any server-side availability check runs.
    """
    try:
        parsed = urlparse(str(url or "").strip())
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    try:
        host = (parsed.hostname or "").strip().lower().rstrip(".")
    except ValueError:
        return False
    if not host or host in _UNSAFE_HOSTS:
        return False
    if any(ch.isspace() for ch in host):
        return False
    if any(host.endswith(suffix) for suffix in _UNSAFE_SUFFIXES):
        return False
    if parsed.username or parsed.password:
        return False
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return True
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


# ------------------------------------------------------------------ curated index

# Skill-level curated resources (keyed by lowercase skill name).
_CURATED = {
    "python": [
        _res("video", "Learn Python — Full Course for Beginners (freeCodeCamp)", "https://www.youtube.com/watch?v=rfscVS0vtbw", "freeCodeCamp"),
        _res("doc", "The Python Tutorial (official)", "https://docs.python.org/3/tutorial/", "Python.org"),
        _res("course", "Python for Everybody (Coursera)", "https://www.coursera.org/specializations/python", "Coursera"),
    ],
    "java": [
        _res("video", "Java Programming — Full Course (freeCodeCamp)", "https://www.youtube.com/watch?v=GoXwIVyNvX0", "freeCodeCamp"),
        _res("doc", "Java Language Tutorials (official)", "https://docs.oracle.com/javase/tutorial/", "Oracle"),
        _res("course", "Java Programming and Software Engineering (Coursera)", "https://www.coursera.org/specializations/java-programming", "Coursera"),
    ],
    "c++": [
        _res("video", "C++ Tutorial for Beginners — Full Course (freeCodeCamp)", "https://www.youtube.com/watch?v=vLnPwxZdW4Y", "freeCodeCamp"),
        _res("doc", "cppreference.com", "https://en.cppreference.com/w/", "cppreference"),
        _res("course", "C++ for C Programmers (Coursera)", "https://www.coursera.org/course/cplusplus4c", "Coursera"),
    ],
    "javascript": [
        _res("video", "Learn JavaScript — Full Course for Beginners (freeCodeCamp)", "https://www.youtube.com/watch?v=PkZNo7MFNFg", "freeCodeCamp"),
        _res("doc", "JavaScript Guide (MDN)", "https://developer.mozilla.org/en-US/docs/Web/JavaScript/guide", "MDN"),
        _res("course", "JavaScript Algorithms and Data Structures (freeCodeCamp)", "https://www.freecodecamp.org/learn/javascript-algorithms-and-data-structures/", "freeCodeCamp"),
    ],
    "typescript": [
        _res("video", "TypeScript Course for Beginners (freeCodeCamp)", "https://www.youtube.com/watch?v=BwuLxPH8IDs", "freeCodeCamp"),
        _res("doc", "TypeScript Documentation (official)", "https://www.typescriptlang.org/docs/", "TypeScript"),
        _res("course", "Understanding TypeScript (Udemy)", "https://www.udemy.com/course/understanding-typescript/", "Udemy"),
    ],
    "react": [
        _res("video", "React Course — Beginner's Tutorial (freeCodeCamp)", "https://www.youtube.com/watch?v=bMknfKXIFA8", "freeCodeCamp"),
        _res("doc", "React Docs — Learn (official)", "https://react.dev/learn", "React"),
        _res("course", "Meta Front-End Developer (Coursera)", "https://www.coursera.org/professional-certificates/meta-front-end-developer", "Coursera"),
    ],
    "sql": [
        _res("video", "SQL Tutorial — Full Database Course (freeCodeCamp)", "https://www.youtube.com/watch?v=HXV3zeQKqGY", "freeCodeCamp"),
        _res("doc", "PostgreSQL Tutorial", "https://www.postgresqltutorial.com/", "PostgreSQLTutorial"),
        _res("course", "SQL for Data Science (Coursera)", "https://www.coursera.org/learn/sql-for-data-science", "Coursera"),
    ],
    "excel": [
        _res("video", "Excel Full Course for Beginners (freeCodeCamp)", "https://www.youtube.com/watch?v=Vl0H-qTclOg", "freeCodeCamp"),
        _res("doc", "Excel Help & Learning (Microsoft)", "https://support.microsoft.com/en-us/excel", "Microsoft"),
        _res("course", "Excel Skills for Business (Coursera)", "https://www.coursera.org/specializations/excel", "Coursera"),
    ],
    "tableau": [
        _res("video", "Tableau for Beginners — Full Course (freeCodeCamp)", "https://www.youtube.com/watch?v=-zZJgpVxTAQ", "freeCodeCamp"),
        _res("doc", "Tableau Training & Tutorials", "https://www.tableau.com/learn/training", "Tableau"),
        _res("course", "Data Visualization with Tableau (Coursera)", "https://www.coursera.org/specializations/data-visualization", "Coursera"),
    ],
    "power bi": [
        _res("video", "Power BI Tutorial for Beginners (Simon Sez IT)", "https://www.youtube.com/watch?v=DtD9XJ99jG4", "Simon Sez IT"),
        _res("doc", "Power BI Documentation (Microsoft)", "https://learn.microsoft.com/en-us/power-bi/", "Microsoft Learn"),
        _res("course", "Microsoft Power BI Data Analyst (Coursera)", "https://www.coursera.org/professional-certificates/microsoft-power-bi-data-analyst", "Coursera"),
    ],
    "machine learning": [
        _res("video", "Machine Learning for Everybody (freeCodeCamp)", "https://www.youtube.com/watch?v=i_LwzRVP7bg", "freeCodeCamp"),
        _res("doc", "Google Machine Learning Crash Course", "https://developers.google.com/machine-learning/crash-course", "Google"),
        _res("course", "Machine Learning — Andrew Ng (Coursera)", "https://www.coursera.org/learn/machine-learning", "Coursera"),
    ],
    "deep learning": [
        _res("video", "Deep Learning Course for Beginners (freeCodeCamp)", "https://www.youtube.com/watch?v=ASN7S2K9Wgo", "freeCodeCamp"),
        _res("doc", "Deep Learning Specialization notes", "https://www.deeplearning.ai/courses/deep-learning-specialization/", "deeplearning.ai"),
        _res("course", "Deep Learning Specialization (Coursera)", "https://www.coursera.org/specializations/deep-learning", "Coursera"),
    ],
    "nlp": [
        _res("video", "Natural Language Processing NLP (freeCodeCamp)", "https://www.youtube.com/watch?v=fNxaJsNG3-s", "freeCodeCamp"),
        _res("doc", "Hugging Face NLP Course", "https://huggingface.co/learn/nlp-course", "Hugging Face"),
        _res("course", "Natural Language Processing (Coursera)", "https://www.coursera.org/specializations/natural-language-processing", "Coursera"),
    ],
    "pytorch": [
        _res("video", "PyTorch for Deep Learning (freeCodeCamp)", "https://www.youtube.com/watch?v=V_xro1bcAuA", "freeCodeCamp"),
        _res("doc", "PyTorch Tutorials (official)", "https://pytorch.org/tutorials/", "PyTorch"),
        _res("course", "Intro to Deep Learning with PyTorch (Udacity)", "https://www.udacity.com/course/deep-learning-pytorch--ud188", "Udacity"),
    ],
    "tensorflow": [
        _res("video", "TensorFlow 2.0 Full Course (freeCodeCamp)", "https://www.youtube.com/watch?v=tPYj3fFJGjk", "freeCodeCamp"),
        _res("doc", "TensorFlow Tutorials (official)", "https://www.tensorflow.org/tutorials", "TensorFlow"),
        _res("course", "Introduction to TensorFlow (Coursera)", "https://www.coursera.org/learn/introduction-tensorflow", "Coursera"),
    ],
    "docker": [
        _res("video", "Docker Tutorial for Beginners (Programming with Mosh)", "https://www.youtube.com/watch?v=pTFZFxd4hOI", "Mosh"),
        _res("doc", "Docker Get Started (official)", "https://docs.docker.com/get-started/", "Docker"),
        _res("course", "Docker Mastery (Udemy)", "https://www.udemy.com/course/docker-mastery/", "Udemy"),
    ],
    "kubernetes": [
        _res("video", "Kubernetes Tutorial for Beginners (freeCodeCamp)", "https://www.youtube.com/watch?v=X48VuDVv0do", "freeCodeCamp"),
        _res("doc", "Kubernetes Basics (official)", "https://kubernetes.io/docs/tutorials/kubernetes-basics/", "Kubernetes"),
        _res("course", "CKA Certificate Course (Udemy)", "https://www.udemy.com/course/certified-kubernetes-application-developer/", "Udemy"),
    ],
    "git": [
        _res("video", "Git and GitHub for Beginners (freeCodeCamp)", "https://www.youtube.com/watch?v=RGOj5yH7evk", "freeCodeCamp"),
        _res("doc", "git — the simple guide", "https://rogerdudler.github.io/git-guide/", "Git Guide"),
        _res("course", "Version Control with Git (Coursera)", "https://www.coursera.org/learn/version-control-with-git", "Coursera"),
    ],
    "aws": [
        _res("video", "AWS Certified Cloud Practitioner (freeCodeCamp)", "https://www.youtube.com/watch?v=3hLmDS179YE", "freeCodeCamp"),
        _res("doc", "AWS Training & Certification", "https://aws.amazon.com/training/", "AWS"),
        _res("course", "AWS Fundamentals (Coursera)", "https://www.coursera.org/learn/aws-cloud-technical-essentials", "Coursera"),
    ],
    "linux": [
        _res("video", "Linux for Beginners — Full Course (freeCodeCamp)", "https://www.youtube.com/watch?v=wBp0Rb-ZJak", "freeCodeCamp"),
        _res("doc", "Linux Journey", "https://linuxjourney.com/", "Linux Journey"),
        _res("course", "Linux Command Line Basics (Udacity)", "https://www.udacity.com/course/linux-command-line-basics--ud595", "Udacity"),
    ],
    "statistics": [
        _res("video", "Statistics and Probability — Full Course (freeCodeCamp)", "https://www.youtube.com/watch?v=sbbYntt5CJk", "freeCodeCamp"),
        _res("doc", "Khan Academy Statistics & Probability", "https://www.khanacademy.org/math/statistics-probability", "Khan Academy"),
        _res("course", "Introduction to Statistics (Coursera)", "https://www.coursera.org/learn/stanford-statistics", "Coursera"),
    ],
    "data visualization": [
        _res("video", "Data Visualization with Python (freeCodeCamp)", "https://www.youtube.com/watch?v=r-uOLxNrNk8", "freeCodeCamp"),
        _res("doc", "Matplotlib Documentation", "https://matplotlib.org/stable/tutorials/index.html", "Matplotlib"),
        _res("course", "Data Visualization with Tableau (Coursera)", "https://www.coursera.org/specializations/data-visualization", "Coursera"),
    ],
    "network security": [
        _res("video", "Network Security — Full Course (freeCodeCamp)", "https://www.youtube.com/watch?v=bVeL0zjhHkw", "freeCodeCamp"),
        _res("doc", "TryHackMe — Intro to Cyber Security room (hands-on)", "https://tryhackme.com/room/introtocyber", "TryHackMe"),
        _res("course", "IBM Cybersecurity Analyst (Coursera)", "https://www.coursera.org/professional-certificates/ibm-cybersecurity-analyst", "Coursera"),
    ],
    "cybersecurity": [
        _res("video", "IT Security — Defense Against the Digital Dark Arts (Coursera)", "https://www.coursera.org/learn/it-security", "Coursera"),
        _res("doc", "TryHackMe — Intro to Cyber Security room (hands-on)", "https://tryhackme.com/room/introtocyber", "TryHackMe"),
        _res("course", "IBM Cybersecurity Analyst Professional Certificate", "https://www.coursera.org/professional-certificates/ibm-cybersecurity-analyst", "Coursera"),
    ],
    "communication": [
        _res("video", "Improve Your Communication Skills (Alux)", "https://www.youtube.com/watch?v=5W2OZm6zPK4", "Alux"),
        _res("article", "What Is Effective Communication? (Indeed)", "https://www.indeed.com/career-advice/career-development/what-is-effective-communication", "Indeed"),
        _res("course", "Dynamic Public Speaking (Coursera)", "https://www.coursera.org/specializations/dynamic-public-speaking", "Coursera"),
    ],
    "teamwork": [
        _res("article", "Teamwork Skills: Being an Effective Group Member (SkillsYouNeed)", "https://www.skillsyouneed.com/ips/teamwork.html", "SkillsYouNeed"),
        _res("course", "Teamwork Skills: Communicating Effectively in Groups (Coursera)", "https://www.coursera.org/learn/teamwork-skills", "Coursera"),
        _res("video", "The Power of Teamwork (TED)", "https://www.youtube.com/watch?v=fUXdrl9ZQLE", "TED"),
    ],
    "leadership": [
        _res("video", "Leadership — How to Become a Better Leader (TED)", "https://www.youtube.com/watch?v=QpW7r8Q0u70", "TED"),
        _res("article", "What Is Leadership? (Indeed)", "https://www.indeed.com/career-advice/career-development/what-is-leadership", "Indeed"),
        _res("course", "Foundations of Everyday Leadership (Coursera)", "https://www.coursera.org/learn/leadership-foundations", "Coursera"),
    ],
    "pandas": [
        _res("video", "Pandas for Data Science (freeCodeCamp)", "https://www.youtube.com/watch?v=vmEHCJofslg", "freeCodeCamp"),
        _res("doc", "Pandas Getting Started (official)", "https://pandas.pydata.org/docs/getting_started/index.html", "Pandas"),
        _res("course", "Python for Data Science and Machine Learning Bootcamp (Udemy)", "https://www.udemy.com/course/python-for-data-science-and-machine-learning-bootcamp/", "Udemy"),
    ],
    "numpy": [
        _res("video", "NumPy Tutorial — Full Course (freeCodeCamp)", "https://www.youtube.com/watch?v=QUT1VHiLmmI", "freeCodeCamp"),
        _res("doc", "NumPy Quickstart (official)", "https://numpy.org/doc/stable/user/quickstart.html", "NumPy"),
        _res("course", "Data Analysis with Python (freeCodeCamp)", "https://www.freecodecamp.org/learn/data-analysis-with-python/", "freeCodeCamp"),
    ],
    "scikit-learn": [
        _res("video", "Machine Learning with scikit-learn (sentdex)", "https://www.youtube.com/playlist?list=PLQVvvaa0QuDfKTOs3Keq_kaG2P55YRn5v", "sentdex"),
        _res("doc", "scikit-learn User Guide (official)", "https://scikit-learn.org/stable/user_guide.html", "scikit-learn"),
        _res("course", "Applied Machine Learning in Python (Coursera)", "https://www.coursera.org/learn/python-machine-learning", "Coursera"),
    ],
    "rest apis": [
        _res("video", "REST API concepts and examples (WebConcepts)", "https://www.youtube.com/watch?v=npNqjR6iREQ", "WebConcepts"),
        _res("doc", "REST API Tutorial", "https://restfulapi.net/", "restfulapi.net"),
        _res("course", "Build REST APIs with Django REST Framework (Coursera)", "https://www.coursera.org/projects/django-rest-framework", "Coursera"),
    ],
    "flask": [
        _res("video", "Flask Python Web Framework (freeCodeCamp)", "https://www.youtube.com/watch?v=MwZwr5Tvyxo", "freeCodeCamp"),
        _res("doc", "Flask Quickstart (official)", "https://flask.palletsprojects.com/en/stable/quickstart/", "Flask"),
        _res("course", "REST APIs with Flask and Python (Udemy)", "https://www.udemy.com/course/rest-api-flask-and-python/", "Udemy"),
    ],
    "fastapi": [
        _res("video", "FastAPI Course for Beginners", "https://www.youtube.com/watch?v=tLKKmouUams", "freeCodeCamp"),
        _res("doc", "FastAPI Documentation (official)", "https://fastapi.tiangolo.com/", "FastAPI"),
        _res("course", "FastAPI — The Full Course (Udemy)", "https://www.udemy.com/course/python-api-development-in-depth/", "Udemy"),
    ],
    "sqlalchemy": [
        _res("doc", "SQLAlchemy Documentation (official)", "https://docs.sqlalchemy.org/en/20/", "SQLAlchemy"),
        _res("video", "SQLAlchemy Python Tutorial", "https://www.youtube.com/watch?v=AkMJXfWteLI", "TutorialEdge"),
        _res("course", "SQL and PostgreSQL (Udemy)", "https://www.udemy.com/course/sql-and-postgresql/", "Udemy"),
    ],
    "etl": [
        _res("video", "ETL Pipelines Explained", "https://www.youtube.com/watch?v=8dJ8NuEmwOM", "IBM Technology"),
        _res("doc", "What is ETL? (Hevo)", "https://hevodata.com/learn/what-is-etl/", "Hevo"),
        _res("course", "Data Engineering Foundations (Coursera)", "https://www.coursera.org/specializations/data-engineering-foundations", "Coursera"),
    ],
    "airflow": [
        _res("video", "Apache Airflow Tutorial (freeCodeCamp)", "https://www.youtube.com/watch?v=K9AnJ9_ZdnE", "freeCodeCamp"),
        _res("doc", "Airflow Documentation (official)", "https://airflow.apache.org/docs/", "Apache Airflow"),
        _res("course", "Data Pipelines with Airflow (Udemy)", "https://www.udemy.com/course/the-ultimate-handson-apache-airflow-course/", "Udemy"),
    ],
    "spark": [
        _res("video", "Apache Spark for Beginners (freeCodeCamp)", "https://www.youtube.com/watch?v=QaoJhWl0XQU", "freeCodeCamp"),
        _res("doc", "Apache Spark Quick Start (official)", "https://spark.apache.org/docs/latest/quick-start.html", "Apache Spark"),
        _res("course", "Big Data Essentials with Spark (Coursera)", "https://www.coursera.org/learn/big-data-essentials", "Coursera"),
    ],
    "hadoop": [
        _res("video", "Hadoop Ecosystem — Full Course (freeCodeCamp)", "https://www.youtube.com/watch?v=zcYLrc3JT8Y", "freeCodeCamp"),
        _res("doc", "Apache Hadoop Documentation", "https://hadoop.apache.org/docs/current/", "Apache Hadoop"),
        _res("course", "Big Data with Hadoop (Coursera)", "https://www.coursera.org/learn/hadoop", "Coursera"),
    ],
    "snowflake": [
        _res("video", "Snowflake Tutorial for Beginners", "https://www.youtube.com/watch?v=vEiHlEF76ww", "freeCodeCamp"),
        _res("doc", "Snowflake Documentation (official)", "https://docs.snowflake.com/", "Snowflake"),
        _res("course", "Snowflake Fundamentals (Coursera)", "https://www.coursera.org/learn/snowflake-fundamentals", "Coursera"),
    ],
    "bigquery": [
        _res("video", "Google BigQuery Tutorial (Simplilearn)", "https://www.youtube.com/watch?v=jvHhiuqJSV0", "Simplilearn"),
        _res("doc", "BigQuery Documentation (official)", "https://cloud.google.com/bigquery/docs", "Google Cloud"),
        _res("course", "From Data to Insights with Google Cloud (Coursera)", "https://www.coursera.org/learn/from-data-to-insights-google-cloud", "Coursera"),
    ],
    "dbt": [
        _res("video", "dbt Tutorial for Beginners", "https://www.youtube.com/watch?v=EOdL-Vq0Xco", "dbt Labs"),
        _res("doc", "dbt Documentation (official)", "https://docs.getdbt.com/", "dbt Labs"),
        _res("course", "Analytics Engineering with dbt (Coursera)", "https://www.coursera.org/projects/dbt-cloud-data-build-tool", "Coursera"),
    ],
    "data engineering": [
        _res("video", "Data Engineering Full Course (freeCodeCamp)", "https://www.youtube.com/watch?v=qHY6bjiVu8o", "freeCodeCamp"),
        _res("doc", "Data Engineering Roadmap", "https://awesomedataengineering.com/", "Awesome Data Engineering"),
        _res("course", "Data Engineering Foundations (Coursera)", "https://www.coursera.org/specializations/data-engineering-foundations", "Coursera"),
    ],
    "ci/cd": [
        _res("video", "CI/CD — What is Continuous Integration?", "https://www.youtube.com/watch?v=1er2cUjqksg", "IBM Technology"),
        _res("doc", "GitHub Actions Documentation", "https://docs.github.com/en/actions", "GitHub"),
        _res("course", "Build Continuous Integration (CI) Pipelines (Coursera)", "https://www.coursera.org/projects/github-actions-ci", "Coursera"),
    ],
    "testing": [
        _res("video", "Software Testing Tutorial (freeCodeCamp)", "https://www.youtube.com/watch?v=fwxtk9eMk6I", "freeCodeCamp"),
        _res("doc", "pytest Documentation", "https://docs.pytest.org/en/stable/", "pytest"),
        _res("course", "Automated Software Testing (Udacity)", "https://www.udacity.com/course/software-testing--cs258", "Udacity"),
    ],
    "azure": [
        _res("video", "Azure Fundamentals Certification (freeCodeCamp)", "https://www.youtube.com/watch?v=NKEFWyq5JXA", "freeCodeCamp"),
        _res("doc", "Azure Documentation (Microsoft)", "https://learn.microsoft.com/en-us/azure/", "Microsoft Learn"),
        _res("course", "AZ-900 Azure Fundamentals (Coursera)", "https://www.coursera.org/learn/microsoft-azure-az-900-essentials", "Coursera"),
    ],
    "gcp": [
        _res("video", "Google Cloud Associate Cloud Engineer (freeCodeCamp)", "https://www.youtube.com/watch?v=JPnoJKS4w1Y", "freeCodeCamp"),
        _res("doc", "Google Cloud Documentation", "https://cloud.google.com/docs", "Google Cloud"),
        _res("course", "Google Cloud Digital Leader (Coursera)", "https://www.coursera.org/learn/cloud-digital-leader-training", "Coursera"),
    ],
    "nosql": [
        _res("video", "NoSQL Database Concepts (IBM Technology)", "https://www.youtube.com/watch?v=bUZohWrUSKQ", "IBM Technology"),
        _res("doc", "MongoDB University", "https://learn.mongodb.com/", "MongoDB"),
        _res("course", "MongoDB — The Complete Developer's Guide (Udemy)", "https://www.udemy.com/course/mongodb-the-complete-developers-guide/", "Udemy"),
    ],
    "mongodb": [
        _res("doc", "MongoDB Manual (official)", "https://www.mongodb.com/docs/manual/", "MongoDB"),
        _res("video", "MongoDB Crash Course (Traversy Media)", "https://www.youtube.com/watch?v=OF55gHtRa5E", "Traversy Media"),
        _res("course", "MongoDB University", "https://learn.mongodb.com/", "MongoDB"),
    ],
    "postgresql": [
        _res("video", "PostgreSQL Tutorial for Beginners (freeCodeCamp)", "https://www.youtube.com/watch?v=qw--VYLpxG4", "freeCodeCamp"),
        _res("doc", "PostgreSQL Documentation (official)", "https://www.postgresql.org/docs/current/", "PostgreSQL"),
        _res("course", "SQL and PostgreSQL: The Complete Developer's Guide (Udemy)", "https://www.udemy.com/course/sql-and-postgresql/", "Udemy"),
    ],
    "data analysis": [
        _res("video", "Data Analysis with Python — Full Course (freeCodeCamp)", "https://www.youtube.com/watch?v=r-uOLxNrNk8", "freeCodeCamp"),
        _res("doc", "Pandas Getting Started", "https://pandas.pydata.org/docs/getting_started/index.html", "Pandas"),
        _res("course", "Google Data Analytics Certificate (Coursera)", "https://www.coursera.org/professional-certificates/google-data-analytics", "Coursera"),
    ],
    "business intelligence": [
        _res("video", "Business Intelligence — What it is and how it works", "https://www.youtube.com/watch?v=WAFBXUXBSPM", "ITLearn365"),
        _res("doc", "What is Business Intelligence? (Tableau)", "https://www.tableau.com/learn/articles/business-intelligence", "Tableau"),
        _res("course", "Google Business Intelligence Certificate (Coursera)", "https://www.coursera.org/professional-certificates/google-business-intelligence", "Coursera"),
    ],
    "data storytelling": [
        _res("video", "Storytelling with Data (Cole Nussbaumer Knaflic)", "https://www.youtube.com/watch?v=lVZkXDzR4D8", "Storytelling with Data"),
        _res("article", "Data Storytelling — The Essential Data Science Skill (Coursera)", "https://www.coursera.org/articles/data-storytelling", "Coursera"),
        _res("course", "Effective Business Presentations with Powerpoint (PwC, Coursera)", "https://www.coursera.org/learn/effective-business-presentations-powerpoint", "Coursera"),
    ],
    "incident response": [
        _res("video", "Incident Response — Blue Team (freeCodeCamp)", "https://www.youtube.com/watch?v=eSnaUK7nouc", "freeCodeCamp"),
        _res("doc", "NIST Incident Response (official)", "https://csrc.nist.gov/topics/security-and-privacy/incident-response", "NIST"),
        _res("course", "IBM Cybersecurity — Heads Up! Incident Response (Coursera)", "https://www.coursera.org/learn/incident-response", "Coursera"),
    ],
    "siem": [
        _res("video", "SIEM — Splunk vs ELK watch how it works", "https://www.youtube.com/watch?v=YOQCy0t_qkE", "infosectrain"),
        _res("doc", "Splunk Documentation", "https://docs.splunk.com/", "Splunk"),
        _res("course", "IBM Cybersecurity — SOC (Coursera)", "https://www.coursera.org/learn/siem-systems", "Coursera"),
    ],
    "risk assessment": [
        _res("video", "Risk Assessment Basics (SecurityMetrics)", "https://www.youtube.com/watch?v=nxACwdcECV4", "SecurityMetrics"),
        _res("doc", "NIST Risk Management Framework", "https://csrc.nist.gov/projects/risk-management", "NIST"),
        _res("course", "Security Governance & Compliance (Coursera)", "https://www.coursera.org/learn/governance-and-management-of-it-compliance", "Coursera"),
    ],
    "threat detection": [
        _res("video", "Threat Hunting — Cyber Threat Detection", "https://www.youtube.com/watch?v=E5WHnz15H4I", "ec-council"),
        _res("doc", "MITRE ATT&CK", "https://attack.mitre.org/", "MITRE"),
        _res("course", "IBM Cybersecurity — Threat Intelligence (Coursera)", "https://www.coursera.org/learn/threat-intelligence", "Coursera"),
    ],
    "cloud security": [
        _res("video", "Cloud Security — Full Course (freeCodeCamp)", "https://www.youtube.com/watch?v=JMashhrMln0", "freeCodeCamp"),
        _res("doc", "Shared Responsibility Model (AWS)", "https://aws.amazon.com/compliance/shared-responsibility-model/", "AWS"),
        _res("course", "IBM Cybersecurity — Cloud Security (Coursera)", "https://www.coursera.org/learn/cloud-security", "Coursera"),
    ],
    "penetration testing": [
        _res("video", "Ethical Hacking & Penetration Testing (freeCodeCamp)", "https://www.youtube.com/watch?v=3Kq1MIfTWCE", "freeCodeCamp"),
        _res("doc", "TryHackMe — Penetration Testing room (hands-on)", "https://tryhackme.com/room/pentestingfundamentals", "TryHackMe"),
        _res("doc", "OWASP Testing Guide", "https://owasp.org/www-project-web-security-testing-guide/", "OWASP"),
        _res("course", "Practical Ethical Hacking (TCM, Udemy)", "https://www.udemy.com/course/practical-ethical-hacking/", "Udemy"),
    ],
    "iso 27001": [
        _res("video", "What is ISO 27001? (Advisera)", "https://www.youtube.com/watch?v=LxqjBx9YkSo", "Advisera"),
        _res("doc", "ISO/IEC 27001 information security standards", "https://www.iso.org/isoiec-27001-information-security.html", "ISO"),
        _res("course", "ISO 27001 ISMS Lead Implementer (Udemy)", "https://www.udemy.com/course/iso-27001-isms-cyber-security/", "Udemy"),
    ],
    "security+": [
        _res("video", "CompTIA Security+ Full Course (freeCodeCamp)", "https://www.youtube.com/watch?v=9R2jIRM6LOk", "freeCodeCamp"),
        _res("doc", "CompTIA Security+ (SY0-701) — official", "https://www.comptia.org/certifications/security", "CompTIA"),
        _res("course", "CompTIA Security+ (SY0-701) Course (Udemy)", "https://www.udemy.com/course/securityplus/", "Udemy"),
    ],
    "digital forensics": [
        _res("video", "Digital Forensics — Course (freeCodeCamp)", "https://www.youtube.com/watch?v=kqQPhX9D0ag", "freeCodeCamp"),
        _res("doc", "SANS Digital Forensics & Incident Response", "https://www.sans.org/digital-forensics-incident-response/", "SANS"),
        _res("course", "IBM Cybersecurity — Digital Forensics (Coursera)", "https://www.coursera.org/learn/digital-forensics-concepts", "Coursera"),
    ],
    "windows server": [
        _res("video", "Windows Server Administration (Professor Messer)", "https://www.youtube.com/watch?v=MImO0Z2q1Q4", "Professor Messer"),
        _res("doc", "Windows Server documentation (Microsoft)", "https://learn.microsoft.com/en-us/windows-server/", "Microsoft Learn"),
        _res("course", "Windows Server 2022 Administration (Udemy)", "https://www.udemy.com/course/complete-guide-to-windows-server-2022-administration/", "Udemy"),
    ],
    "active directory": [
        _res("video", "Active Directory Tutorial for Beginners (Server Academy)", "https://www.youtube.com/watch?v=nKcrVtvZvpk", "Server Academy"),
        _res("doc", "Active Directory Domain Services (Microsoft)", "https://learn.microsoft.com/en-us/windows-server/identity/ad-ds/get-started/virtual-dc/active-directory-domain-services-overview", "Microsoft Learn"),
        _res("doc", "TryHackMe — Active Directory room (hands-on)", "https://tryhackme.com/room/activedirectorybasics", "TryHackMe"),
        _res("course", "Active Directory Domain Services — Microsoft Learn", "https://learn.microsoft.com/en-us/training/paths/active-directory-domain-services/", "Microsoft Learn"),
    ],
    "vulnerability management": [
        _res("video", "Vulnerability Management Overview (RSA)", "https://www.youtube.com/watch?v=3ZA0QRuwb4A", "RSA"),
        _res("doc", "CVE — Common Vulnerabilities and Exposures", "https://www.cve.org/", "CVE.org"),
        _res("course", "Vulnerability Management (Coursera)", "https://www.coursera.org/learn/vulnerability-management-identifying-and-responding-to-common-cyber-threats", "Coursera"),
    ],
}

# Category-level fallback for skills without a curated entry.
_CATEGORY_BASE = {
    "Programming": [
        _res("video", "Learn Python — Full Course for Beginners (freeCodeCamp)", "https://www.youtube.com/watch?v=rfscVS0vtbw", "freeCodeCamp"),
        _res("doc", "The Python Tutorial (official)", "https://docs.python.org/3/tutorial/", "Python.org"),
        _res("course", "Python for Everybody (Coursera)", "https://www.coursera.org/specializations/python", "Coursera"),
    ],
    "Data": [
        _res("video", "SQL Tutorial — Full Database Course (freeCodeCamp)", "https://www.youtube.com/watch?v=HXV3zeQKqGY", "freeCodeCamp"),
        _res("doc", "Pandas Getting Started", "https://pandas.pydata.org/docs/getting_started/index.html", "Pandas"),
        _res("course", "Excel Skills for Business (Coursera)", "https://www.coursera.org/specializations/excel", "Coursera"),
    ],
    "AI": [
        _res("video", "Machine Learning for Everybody (freeCodeCamp)", "https://www.youtube.com/watch?v=i_LwzRVP7bg", "freeCodeCamp"),
        _res("doc", "Google Machine Learning Crash Course", "https://developers.google.com/machine-learning/crash-course", "Google"),
        _res("course", "Machine Learning — Andrew Ng (Coursera)", "https://www.coursera.org/learn/machine-learning", "Coursera"),
    ],
    "DevOps": [
        _res("video", "Docker Tutorial for Beginners (Mosh)", "https://www.youtube.com/watch?v=pTFZFxd4hOI", "Mosh"),
        _res("doc", "Docker Get Started (official)", "https://docs.docker.com/get-started/", "Docker"),
        _res("course", "AWS Fundamentals (Coursera)", "https://www.coursera.org/learn/aws-cloud-technical-essentials", "Coursera"),
    ],
    "Visualization": [
        _res("video", "Data Visualization with Python (freeCodeCamp)", "https://www.youtube.com/watch?v=r-uOLxNrNk8", "freeCodeCamp"),
        _res("doc", "Tableau Training & Tutorials", "https://www.tableau.com/learn/training", "Tableau"),
        _res("course", "Data Visualization with Tableau (Coursera)", "https://www.coursera.org/specializations/data-visualization", "Coursera"),
    ],
    "Analytics": [
        _res("video", "Excel Full Course for Beginners (freeCodeCamp)", "https://www.youtube.com/watch?v=Vl0H-qTclOg", "freeCodeCamp"),
        _res("doc", "Power BI Documentation (Microsoft)", "https://learn.microsoft.com/en-us/power-bi/", "Microsoft Learn"),
        _res("course", "Google Data Analytics Certificate (Coursera)", "https://www.coursera.org/professional-certificates/google-data-analytics", "Coursera"),
    ],
    "Security": [
        _res("video", "Network Security — Full Course (freeCodeCamp)", "https://www.youtube.com/watch?v=bVeL0zjhHkw", "freeCodeCamp"),
        _res("doc", "TryHackMe — Intro to Cyber Security room (hands-on)", "https://tryhackme.com/room/introtocyber", "TryHackMe"),
        _res("course", "IBM Cybersecurity Analyst (Coursera)", "https://www.coursera.org/professional-certificates/ibm-cybersecurity-analyst", "Coursera"),
    ],
    "Soft Skills": [
        _res("article", "What Is Effective Communication? (Indeed)", "https://www.indeed.com/career-advice/career-development/what-is-effective-communication", "Indeed"),
        _res("course", "Dynamic Public Speaking (Coursera)", "https://www.coursera.org/specializations/dynamic-public-speaking", "Coursera"),
    ],
}


# ------------------------------------------------------------------ verified-dead guard
#
# Universal dead-link guard. Some URLs provably no longer resolve (a removed
# YouTube video, an expired course), while others are bot-blocked to a cheap
# HEAD probe (Udemy 403s) so a live check alone can't be trusted. Rather than
# ever surfacing a removed/expired resource, each verified-dead URL maps to a
# known-good replacement (every replacement below was probe-verified live
# before it was committed). `sanitize_resources()` is applied at every resource
# surface — curated pool, roadmap phases, recommended/lesson/step pickers, and
# stored items — so a dead link can never reach the UI, even offline.

# Canonical key = "yt:<video id>" for YouTube (so query params can't hide a
# removed video), else "url:<exact url>".
_VERIFIED_DEAD_RESOURCES = {
    "yt:t75MqaiERPE": [
        _res("video", "Active Directory Tutorial for Beginners (Server Academy)",
             "https://www.youtube.com/watch?v=nKcrVtvZvpk", "Server Academy"),
    ],
    "url:https://www.udemy.com/course/active-directory-ultimate-course/": [
        _res("course", "Active Directory Domain Services — Microsoft Learn",
             "https://learn.microsoft.com/en-us/training/paths/active-directory-domain-services/",
             "Microsoft Learn"),
    ],
}

_VERIFIED_DEAD_KEYS = frozenset(_VERIFIED_DEAD_RESOURCES)


def _dead_link_key(url):
    """Canonical lookup key for the verified-dead map."""
    raw = str(url or "").strip()
    if not raw or not is_safe_public_url(raw):
        return None
    video_id = _youtube_video_id(raw)
    if video_id:
        return "yt:" + video_id
    return "url:" + raw


def is_verified_dead_url(url):
    """True when a URL is on the verified-dead list (used by storage sweeps)."""
    key = _dead_link_key(url)
    return key in _VERIFIED_DEAD_KEYS


def sanitize_resources(resources):
    """Deterministic, offline dead-link guard for a resource list.

    Any resource whose URL is a verified-dead link is replaced by its curated
    known-good replacement (same type/skill); anything else passes through
    unchanged. Empty/unavailable markers survive untouched. Duplicates are
    removed. Idempotent — safe to run repeatedly and at every surface.
    """
    if not resources:
        return list(resources) if isinstance(resources, list) else []
    out, seen = [], set()
    for item in resources or []:
        if not isinstance(item, dict):
            continue
        if item.get("unavailable"):
            out.append(dict(item))
            continue
        raw = str(item.get("url") or "").strip()
        if not raw or not is_safe_public_url(raw):
            out.append(dict(item))
            continue
        repl = _VERIFIED_DEAD_RESOURCES.get(_dead_link_key(raw))
        if repl:
            for rep in repl:
                url = str(rep.get("url") or "").strip()
                if url and url not in seen:
                    seen.add(url)
                    entry = dict(rep)
                    entry.setdefault("source_kind", item.get("source_kind") or "curated")
                    entry["replaced_url"] = raw
                    out.append(entry)
            continue
        if raw not in seen:
            seen.add(raw)
            out.append(dict(item))
    return out


def _lesson_res(res_type, title, url, source, topics=(), levels=(),
                roles=(), reason=""):
    item = _res(res_type, title, url, source)
    item["_topics"] = tuple(t.lower() for t in (topics or ()))
    item["_levels"] = tuple(l.lower() for l in (levels or ()))
    item["_roles"] = tuple(r.lower() for r in (roles or ()))
    item["reason"] = reason
    item["source_kind"] = "curated"
    return item


_TOPIC_CURATED = {
    "pandas": [
        _lesson_res(
            "doc",
            "Pandas Getting Started",
            "https://pandas.pydata.org/docs/getting_started/index.html",
            "Pandas",
            topics=("fundamentals", "dataframe", "tabular data"),
            levels=("Beginner",),
            reason="Good first stop for DataFrame basics, reading data, filtering, and summaries.",
        ),
        _lesson_res(
            "tutorial",
            "10 minutes to pandas",
            "https://pandas.pydata.org/docs/user_guide/10min.html",
            "Pandas",
            topics=("fundamentals", "dataframe", "selection", "filtering", "summary"),
            levels=("Beginner", "Intermediate"),
            reason="Official quick tour covering DataFrame creation, selection, filtering, and summaries.",
        ),
        _lesson_res(
            "doc",
            "Intro to data structures",
            "https://pandas.pydata.org/docs/user_guide/dsintro.html",
            "Pandas",
            topics=("fundamentals", "series", "dataframe", "tabular data"),
            levels=("Beginner",),
            reason="Clarifies Series and DataFrame structures before deeper analysis tasks.",
        ),
        _lesson_res(
            "doc",
            "Indexing and selecting data",
            "https://pandas.pydata.org/docs/user_guide/indexing.html",
            "Pandas",
            topics=("filter", "filtering", "selection", "subset", "indexing", "loc"),
            levels=("Beginner", "Intermediate"),
            reason="Directly covers row and column selection, boolean masks, and filtering.",
        ),
        _lesson_res(
            "doc",
            "Group by: split-apply-combine",
            "https://pandas.pydata.org/docs/user_guide/groupby.html",
            "Pandas",
            topics=("aggregation", "groupby", "summary", "statistics"),
            levels=("Intermediate", "Advanced"),
            reason="Useful when the topic moves from simple filtering into grouped analysis.",
        ),
        _lesson_res(
            "reference",
            "MultiIndex and advanced indexing",
            "https://pandas.pydata.org/docs/user_guide/advanced.html",
            "Pandas",
            topics=("advanced", "indexing", "multiindex"),
            levels=("Advanced",),
            reason="A deeper reference for complex indexes and production analysis patterns.",
        ),
    ],
    "docker": [
        _lesson_res(
            "doc",
            "What is a container?",
            "https://docs.docker.com/get-started/docker-concepts/the-basics/what-is-a-container/",
            "Docker",
            topics=("container", "containers", "fundamentals", "basic commands"),
            levels=("Beginner",),
            reason="Official explanation of containers before practicing commands or images.",
        ),
        _lesson_res(
            "doc",
            "What is an image?",
            "https://docs.docker.com/get-started/docker-concepts/the-basics/what-is-an-image/",
            "Docker",
            topics=("image", "images", "container", "containers", "fundamentals", "build"),
            levels=("Beginner",),
            reason="Explains images as the blueprint behind containers and build workflows.",
        ),
        _lesson_res(
            "doc",
            "Publishing and exposing ports",
            "https://docs.docker.com/get-started/docker-concepts/running-containers/publishing-ports/",
            "Docker",
            topics=("ports", "publishing", "container", "containers", "networking", "fundamentals"),
            levels=("Beginner", "Intermediate"),
            reason="Shows the official path from a running container to reachable services.",
        ),
        _lesson_res(
            "reference",
            "Dockerfile reference",
            "https://docs.docker.com/reference/dockerfile/",
            "Docker",
            topics=("dockerfile", "images", "build", "copy", "run"),
            levels=("Intermediate", "Advanced"),
            reason="Authoritative syntax reference for writing and debugging Dockerfiles.",
        ),
        _lesson_res(
            "doc",
            "Docker volumes",
            "https://docs.docker.com/engine/storage/volumes/",
            "Docker",
            topics=("volume", "volumes", "storage", "mount", "persistence"),
            levels=("Intermediate",),
            reason="Focused guide for persistent data, named volumes, and mount behavior.",
        ),
        _lesson_res(
            "doc",
            "Docker networking overview",
            "https://docs.docker.com/engine/network/",
            "Docker",
            topics=("network", "networking", "ports", "bridge"),
            levels=("Intermediate",),
            reason="Explains how containers communicate and how ports map to host access.",
        ),
        _lesson_res(
            "tutorial",
            "Multi-stage builds",
            "https://docs.docker.com/build/building/multi-stage/",
            "Docker",
            topics=("multi-stage", "multi stage", "advanced", "build"),
            levels=("Advanced",),
            reason="Advanced build pattern for smaller, production-ready images.",
        ),
    ],
    "deep learning": [
        _lesson_res(
            "tutorial",
            "PyTorch: Learn the basics",
            "https://docs.pytorch.org/tutorials/beginner/basics/intro.html",
            "PyTorch",
            topics=("fundamentals", "tensor", "training", "model"),
            levels=("Beginner",),
            roles=("ai engineer", "machine learning engineer"),
            reason="A concise, official path from tensors to a first training loop.",
        ),
        _lesson_res(
            "tutorial",
            "Build the neural network",
            "https://docs.pytorch.org/tutorials/beginner/basics/buildmodel_tutorial.html",
            "PyTorch",
            topics=("model", "neural network", "architecture", "activation", "layers"),
            levels=("Beginner", "Intermediate"),
            roles=("ai engineer", "machine learning engineer"),
            reason="Shows model classes, layers, and activations in real PyTorch code.",
        ),
        _lesson_res(
            "tutorial",
            "Optimization loop",
            "https://docs.pytorch.org/tutorials/beginner/basics/optimization_tutorial.html",
            "PyTorch",
            topics=("training", "optimization", "loss", "gradient"),
            levels=("Intermediate",),
            roles=("ai engineer", "machine learning engineer"),
            reason="Connects loss, backpropagation, and optimizer steps for model training.",
        ),
    ],
    "pytorch": [
        _lesson_res(
            "tutorial",
            "PyTorch: Learn the basics",
            "https://docs.pytorch.org/tutorials/beginner/basics/intro.html",
            "PyTorch",
            topics=("fundamentals", "tensor", "training", "model"),
            levels=("Beginner",),
            roles=("ai engineer", "machine learning engineer"),
            reason="Official beginner sequence for PyTorch tensors, data, and training.",
        ),
        _lesson_res(
            "tutorial",
            "Build the neural network",
            "https://docs.pytorch.org/tutorials/beginner/basics/buildmodel_tutorial.html",
            "PyTorch",
            topics=("model", "neural network", "architecture", "activation", "layers"),
            levels=("Beginner", "Intermediate"),
            roles=("ai engineer", "machine learning engineer"),
            reason="Useful for understanding modules, layers, and forward passes.",
        ),
    ],
    "statistics": [
        _lesson_res(
            "tutorial",
            "Statistics and probability",
            "https://www.khanacademy.org/math/statistics-probability",
            "Khan Academy",
            topics=("fundamentals", "distribution", "variance", "confidence", "probability"),
            levels=("Beginner", "Intermediate"),
            reason="Plain-language foundation for distributions, variation, and inference.",
        ),
        _lesson_res(
            "reference",
            "Model evaluation metrics",
            "https://scikit-learn.org/stable/modules/model_evaluation.html",
            "scikit-learn",
            topics=("evaluation", "metrics", "variance", "confidence", "experimentation"),
            levels=("Intermediate", "Advanced"),
            roles=("ai engineer", "machine learning engineer", "data scientist"),
            reason="Role-relevant reference for choosing metrics and judging model quality.",
        ),
        _lesson_res(
            "tutorial",
            "Accuracy, precision, and recall",
            "https://developers.google.com/machine-learning/crash-course/classification/accuracy-precision-recall",
            "Google ML Crash Course",
            topics=("evaluation", "metrics", "confidence", "experimentation"),
            levels=("Beginner", "Intermediate"),
            roles=("ai engineer", "machine learning engineer", "data scientist"),
            reason="Connects statistical thinking to practical model evaluation decisions.",
        ),
    ],
}


# ------------------------------------------------------------------ directness

# Search engines and on-platform search/browse pages never describe a topic —
# they are portals that require a second click and are banned as step resources.
_SEARCH_HOSTS = {
    "google.com", "google.co.uk", "google.ca", "google.de", "google.fr",
    "bing.com", "duckduckgo.com", "yahoo.com", "yandex.com", "search.brave.com",
    "ecosia.org", "startpage.com",
}

# YouTube channel markers (handles, /channel/, /user/, /c/) and bare roots.
_YOUTUBE_GENERIC_MARKERS = ("/@", "/channel/", "/user/", "/c/")


def _netloc(url):
    try:
        parsed = urlparse(url)
    except Exception:
        return "", ""
    return (parsed.netloc or "").lower().replace("www.", ""), (parsed.path or "").lower()


def is_search_result_url(url):
    """True for a search-engine query or an on-platform search-result page.

    These are banned because they are a portal, not a concrete resource: the
    student still has to click through and nothing about the platform's search
    page teaches the skill itself.
    """
    if not url:
        return False
    host, path = _netloc(url)
    if not host:
        return False
    if host in _SEARCH_HOSTS:
        return True
    if "youtube." in host:
        return path == "/results" or path.startswith("/results/") or "/search" in path
    return path.startswith("/search") or "/search" in path


def is_platform_category_page(url):
    """True for platform index/category/browse pages (TryHackMe /paths,
    Coursera /search, Udemy /courses, ...) that list many courses rather than
    teach one topic. A room, module, or single-course page is a real resource;
    a category index is not."""
    if not url:
        return False
    host, path = _netloc(url)
    if not host:
        return False
    path = path.rstrip("/")
    if host == "tryhackme.com":
        return path in ("", "/paths")
    if host == "coursera.org":
        return path in ("", "/search") or path.startswith("/search")
    if host == "udemy.com":
        return path in ("", "/courses") or path.startswith("/courses/")
    if host == "github.com":
        return path in ("", "/topics") or path.startswith("/topics/")
    return False


def is_generic_resource_url(url):
    """Universal 'portal, not a topic page' detector.

    A resource URL is *direct* for a learning step only when it points at
    content about the skill itself: a specific video, a specific room/module, a
    specific course, a deep documentation page, or a tutorial-hub landing page.
    Portals and navigation pages are generic and are never offered to a step:

    - search-engine query pages and on-platform search-result pages
    - platform/category index pages (TryHackMe /paths, Coursera /search, a bare
      Coursera/Udemy/GitHub root, ...)
    - YouTube channel homepages (``/@handle``, ``/channel/``, ``/user/``, ``/c/``)
    - the bare root of video/course portals (a YouTube root is a search portal)

    A bare root of an ordinary learning site (``linuxjourney.com/``,
    ``postgresqltutorial.com/``, ``docs.python.org/3/tutorial/``) is a real
    topical landing page, not a portal, and stays acceptable.
    """
    if not url:
        return True
    if not is_safe_public_url(url):
        return True
    host, path = _netloc(url)
    if not host:
        return True
    path = path.rstrip("/")
    if is_search_result_url(url) or is_platform_category_page(url):
        return True
    if "youtube." in host or host == "youtu.be":
        if any(marker in str(url).lower().replace("www.", "") for marker in _YOUTUBE_GENERIC_MARKERS):
            return True
        return not path
    return False
    if host.split(".", 1)[0] in (
            "docs", "learn", "pages", "developers", "developer", "guides", "help"):
        return False
    return not path


def _resource_unavailable(skill_name, reason=""):
    """Honest, link-free placeholder for a step/skill with no validated direct
    resource yet. Never a fabricated URL, never a search deep-link."""
    topic = str(skill_name or "").strip() or "this topic"
    return {
        "type": "other",
        "title": f"Resource unavailable — no validated direct resource yet for {topic}",
        "url": "",
        "provider": "SkillBridge",
        "source": "SkillBridge",
        "unavailable": True,
        "reason": reason or (
            f"No resource that directly teaches this exact step for {topic} is in the "
            "verified catalog yet. It will appear as soon as one is curated or a live "
            "search API is connected."),
        "source_kind": "curated_fallback",
        "status": "Unavailable",
        "is_direct_resource": False,
        "verified": False,
    }


def _generic_fallback(skill_name):
    """Honest fallback for a skill with no curated entry.

    Deliberately returns a single link-free ``resource unavailable`` marker
    instead of search deep-links: a search-result page (YouTube results,
    DuckDuckGo, Coursera search) is a portal, never a concrete resource, and a
    fabricated URL would be worse than none.
    """
    return [_resource_unavailable(skill_name)]


def curated_resources(skill_name, category):
    key = (skill_name or "").strip().lower()
    pool = _CURATED.get(key)
    if pool:
        return sanitize_resources([dict(r) for r in pool])
    cat_pool = _CATEGORY_BASE.get(category)
    if cat_pool:
        return sanitize_resources([dict(r) for r in cat_pool])
    return _generic_fallback(skill_name)


# ---------------------------------------------------------------- live retrieval

def _search_youtube(skill_name, target_role, limit=3):
    """Real retrieval of current videos via the YouTube Data API."""
    if not YOUTUBE_API_KEY:
        return []
    query = f"{skill_name} tutorial for {target_role}".strip()
    try:
        import httpx
        r = httpx.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={"part": "snippet", "type": "video", "maxResults": min(limit, 8),
                    "q": query, "key": YOUTUBE_API_KEY},
            timeout=8,
        )
        r.raise_for_status()
        items = r.json().get("items", [])
        out = []
        for it in items:
            video_id = it.get("id", {}).get("videoId")
            sn = it.get("snippet", {})
            if video_id:
                out.append(_res("video", (sn.get("title") or "Video")[:120],
                                f"https://www.youtube.com/watch?v={video_id}",
                                sn.get("channelTitle", "YouTube")))
        return out
    except Exception:
        return []


_CHECK_CACHE = {}


def _live(url, timeout=1.5):
    """Cheap connectivity check for a URL; tolerant — unverifiable links are kept."""
    if not is_safe_public_url(url):
        _CHECK_CACHE[url] = False
        return False
    cached = _CHECK_CACHE.get(url)
    if cached is not None:
        return cached
    try:
        import httpx
        r = httpx.head(url, follow_redirects=True, timeout=timeout)
        ok = r.status_code < 400
    except Exception:
        ok = True  # network unavailable — assume curated link is fine
    # Cache failures too (per-URL) so repeated seeding does not re-scan.
    _CHECK_CACHE[url] = ok
    return ok


def _youtube_video_id(url):
    """Extract YouTube video ID from various URL formats."""
    try:
        parsed = urlparse(url)
        if "youtube.com" in parsed.netloc:
            if parsed.path == "/watch":
                qs = parse_qs(parsed.query)
                return qs.get("v", [None])[0]
            if parsed.path.startswith("/embed/"):
                return parsed.path.split("/")[2]
            if parsed.path.startswith("/v/"):
                return parsed.path.split("/")[2]
        if "youtu.be" in parsed.netloc:
            return parsed.path.lstrip("/")
    except Exception:
        pass
    return None


def _youtube_thumbnail_available(video_id, timeout=2.0):
    """Check YouTube video availability via thumbnail endpoint.
    
    The mqdefault.jpg thumbnail returns 404 for deleted/private/removed videos,
    unlike the watch page which returns 200 for most states.
    """
    if not video_id:
        return None
    thumb_url = f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"
    try:
        import httpx
        r = httpx.head(thumb_url, follow_redirects=True, timeout=timeout)
        if r.status_code == 404:
            return False
        if r.status_code < 400:
            # Additional check: default thumbnail is 120x90, real thumbnails are larger
            # but we'll trust the 404 signal
            return True
    except Exception:
        pass
    return None  # unknown/unverifiable


def _resource_availability(url, timeout=2.0):
    """Determine resource availability with YouTube-specific logic.
    
    Returns: True (available), False (dead), None (unknown/unverifiable)
    """
    if not is_safe_public_url(url):
        _CHECK_CACHE[url] = False
        return False
    video_id = _youtube_video_id(url)
    if video_id:
        yt_result = _youtube_thumbnail_available(video_id, timeout)
        if yt_result is False:
            return False
        if yt_result is True:
            return True
        # YouTube video but thumbnail check inconclusive — fall through to HEAD
    
    # Fallback: generic HEAD check
    cached = _CHECK_CACHE.get(url)
    if cached is not None:
        return cached
    try:
        import httpx
        r = httpx.head(url, follow_redirects=True, timeout=timeout)
        ok = r.status_code < 400
    except Exception:
        ok = True  # network unavailable — assume curated link is fine
    _CHECK_CACHE[url] = ok
    return ok


def annotate_resources(resources):
    """Annotate each resource with availability status.
    
    Returns list of resources with added 'available' field:
      True  = confirmed available
      False = confirmed dead/removed
      None  = unknown (network down or inconclusive)
    """
    if not resources:
        return []
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=16) as ex:
        # Check availability for each resource
        avail_results = list(ex.map(lambda r: _resource_availability(r.get("url")), resources))
    
    annotated = []
    for r, avail in zip(resources, avail_results):
        nr = dict(r)
        nr["available"] = avail
        annotated.append(nr)
    return annotated


def choose_live(resources, min_keep=1):
    """Filter resources to only available ones, but keep at least min_keep per skill.
    
    Strategy:
    - First, keep all confirmed available (True)
    - If fewer than min_keep, add back unknown (None) resources
    - Dead (False) resources are always dropped
    - This ensures the UI always shows at least something, but prefers live links.
    """
    if not resources:
        return []
    
    available = [r for r in resources if r.get("available") is True]
    unknown = [r for r in resources if r.get("available") is None]
    # Dead resources are always excluded
    
    if len(available) >= min_keep:
        return available
    
    # Need to pad with unknown to reach min_keep
    needed = min_keep - len(available)
    return available + unknown[:needed]


def validate_live(resources):
    """Legacy wrapper: drop links that provably fail; keep unverifiable.
    
    Kept for backward compatibility with existing calls.
    """
    if not resources:
        return []
    annotated = annotate_resources(resources)
    return [r for r in annotated if r.get("available") is not False]


# ---------------------------------------------------------------- public API

_HELPFULNESS = {
    "video": "Quick, visual introduction to get oriented",
    "article": "Conceptual walkthrough to deepen understanding",
    "doc": "Authoritative reference for real-world use",
    "course": "Structured, in-depth curriculum to reach mastery",
    "documentation": "Authoritative reference for real-world use",
    "reference": "Authoritative reference for exact behavior and edge cases",
    "tutorial": "Guided walkthrough for hands-on practice",
}


_LEVEL_RANK = {"beginner": 0, "intermediate": 1, "advanced": 2}


def _strip_internal(resource):
    return {k: v for k, v in dict(resource).items() if not str(k).startswith("_")}


def _availability_status(value):
    if value is True:
        return "Checked"
    if value is False:
        return "Unavailable"
    return "Status unknown"


# ------------------------------------------------------- resource metadata

_PROVIDER_BY_HOST = {
    "youtube.com": "YouTube",
    "coursera.org": "Coursera",
    "udemy.com": "Udemy",
    "udacity.com": "Udacity",
    "freecodecamp.org": "freeCodeCamp",
    "tryhackme.com": "TryHackMe",
    "github.com": "GitHub",
    "docs.docker.com": "Docker",
    "pandas.pydata.org": "Pandas",
    "numpy.org": "NumPy",
    "docs.python.org": "Python.org",
    "learn.microsoft.com": "Microsoft Learn",
    "support.microsoft.com": "Microsoft",
    "docs.snowflake.com": "Snowflake",
    "docs.getdbt.com": "dbt Labs",
    "scikit-learn.org": "scikit-learn",
    "khanacademy.org": "Khan Academy",
    "developers.google.com": "Google",
    "huggingface.co": "Hugging Face",
}


def _provider_from_url(url):
    try:
        host = (urlparse(str(url or "")).netloc or "").replace("www.", "").lower()
    except Exception:
        host = ""
    known = _PROVIDER_BY_HOST.get(host)
    if known:
        return known
    for suffix in (".org", ".com", ".io", ".edu", ".net"):
        if host.endswith(suffix):
            base = host[: -len(suffix)]
            return base.split(".")[-1].title() or "Source"
    return "Source"


def _effective_resource_type(entry):
    """Resource type corrected from the URL *shape* (not just the catalog tag):
    a TryHackMe room is a hands-on lab, a YouTube watch page is a video. This
    is what makes the 'type must match the learning activity' rule enforceable."""
    res_type = canonical_resource_type(entry.get("type"))
    url = str(entry.get("url") or "").lower()
    host, path = _netloc(url)
    if "youtube." in host or host == "youtu.be":
        return "video"
    if host == "tryhackme.com" and path.startswith(("/room", "/module")):
        return "hands_on_lab"
    return res_type


def _enrich_resource(resource, skill_name="", learning_objective="", target_role=""):
    """Surface the metadata a resource object must carry so the UI can show a
    truthful provider, effort, directness and verification state."""
    item = dict(resource or {})
    res_type = _effective_resource_type(item)
    item["type"] = res_type
    item["type_label"] = _TYPE_LABELS.get(res_type, res_type.title())
    item["cta"] = item.get("cta") or _TYPE_CTA.get(res_type, _TYPE_CTA["other"])
    item["provider"] = item.get("provider") or item.get("source") or _provider_from_url(item.get("url"))
    item["estimated_minutes"] = int(item.get("estimated_minutes") or _TYPE_MINUTES.get(res_type, 20))
    item["is_direct_resource"] = bool(item.get("is_direct_resource", item.get("url") and not is_generic_resource_url(item.get("url"))))
    item["verified"] = bool(item.get("verified", True))
    if skill_name is not None:
        item["skill"] = item.get("skill") or str(skill_name)
    if learning_objective is not None:
        item["learning_objective"] = item.get("learning_objective") or str(learning_objective)
    if target_role:
        item["role"] = item.get("role") or str(target_role)
    item["source_kind"] = item.get("source_kind") or "curated"
    item["helpfulness"] = item.get("helpfulness") or _HELPFULNESS.get(res_type, "Curated learning resource")
    item["reason"] = item.get("reason") or item["helpfulness"]
    return item


# ------------------------------------------------------- step-aware matching

# Keyword families used to infer what kind of activity a roadmap step describes.
_STEP_KIND_KEYWORDS = {
    "hands_on_lab": ("lab", "hands-on", "hands on", "configure", "configured", "install",
                     "deploy", "deployment", "set up", "setup", "practice", "exercise"),
    "video": ("watch", "video", "lecture", "webinar", "listen"),
    "coding_problem": ("leetcode", "hackerrank", "kata", "coding challenge", "coding problem"),
    "assessment": ("assessment", "quiz", "exam", "self-test", "self test", "practice test",
                   "test your", "checkpoint", "mock interview", "interview", "evaluate", "revise"),
    "project": ("project", "mini-project", "mini project", "portfolio", "deliverable",
                "build a", "create a", "produce a", "repository", "repo"),
}

# How strongly each step type prefers each resource type (canonical ids).
_TYPE_BONUS = {
    "hands_on_lab": {"hands_on_lab": 40, "interactive_lab": 40, "tutorial": 14, "lesson": 12, "course": 6, "video": 0},
    "interactive_lab": {"hands_on_lab": 40, "interactive_lab": 40, "tutorial": 14, "lesson": 12, "course": 6, "video": 0},
    "video": {"video": 28, "article": 4, "lesson": 4},
    "documentation": {"documentation": 24, "reference": 12, "official_guide": 20, "article": 8, "tutorial": 6},
    "article": {"article": 16, "documentation": 8, "reference": 6},
    "assessment": {"assessment": 30, "exercise": 18, "course": 6, "coding_problem": 10, "tutorial": 4},
    "coding_problem": {"coding_problem": 30, "exercise": 16, "interactive_lab": 10},
    "project": {"project": 26, "course": 10, "tutorial": 12, "lesson": 8},
    "exercise": {"exercise": 24, "coding_problem": 14, "hands_on_lab": 10, "interactive_lab": 10, "tutorial": 6},
    "lesson": {"lesson": 14, "tutorial": 8, "article": 4, "documentation": 4},
    "tutorial": {"tutorial": 12, "video": 6, "course": 6, "documentation": 4},
    "course": {"course": 10, "tutorial": 8, "video": 4},
}


def infer_step_resource_type(title, objective, practice=""):
    """Classify the learning activity a roadmap step asks for."""
    text = f"{title or ''} {objective or ''} {practice or ''}".lower()
    # Order matters: 'hands-on ... project' and 'assessment ... project' must
    # classify by the leading activity, not the trailing generic nouns.
    for kind, keywords in _STEP_KIND_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return kind
    return "tutorial"


def _step_resource_score(entry, skill_name, step_title, step_objective,
                         step_practice, step_type, target_role):
    """Relevance of one catalog resource to one roadmap step: concept overlap
    with the step's objective, skill overlap, activity/type match, and role."""
    haystack = " ".join(str(entry.get(k) or "") for k in (
        "title", "source", "url", "reason", "helpfulness"))
    hay_low = haystack.lower().replace("_", " ")
    step_text = f"{step_title} {step_objective} {step_practice}"
    score = 0
    score += 6 * len(_tokens(step_text).intersection(_tokens(hay_low)))
    score += 2 * len(_tokens(skill_name).intersection(_tokens(hay_low)))
    score += _TYPE_BONUS.get(step_type, {}).get(_effective_resource_type(entry), 0)
    score += _role_score(entry, target_role)
    if entry.get("source_kind") == "curated_fallback":
        score -= 40
    return score


def recommend_step_resources(skill_name, skill_category, step_title, step_objective="",
                             step_practice="", target_role=None, pool=None,
                             step_no=0, exclude=(), max_items=2, live_check=False):
    """Pick the best real resources for ONE roadmap step.

    Candidates come only from the validated catalog pool — never the model and
    never search deep-links. Every returned resource is a direct, non-generic
    URL whose type fits the step's activity. When nothing qualifies the return
    is [] and the caller flags the step 'resource unavailable'; we never fake
    a link, and we never surface a platform/channel/category/search page.
    """
    step_type = infer_step_resource_type(step_title, step_objective, step_practice)
    if pool is not None:
        candidates = [dict(r) for r in pool if isinstance(r, dict)]
    else:
        candidates = _topic_resource_entries(
            skill_name or "", f"{step_title} {step_objective}", target_role)
        candidates += curated_resources(skill_name or "", skill_category or "")
    candidates = [
        dict(r) for r in candidates
        if isinstance(r, dict) and r.get("url")
        and is_safe_public_url(r["url"])
        and not is_generic_resource_url(r["url"])
    ]
    candidates = sanitize_resources(candidates)
    if not candidates:
        return []
    scored = [
        (_step_resource_score(c, skill_name, step_title, step_objective, step_practice,
                              step_type, target_role), c)
        for c in candidates
    ]

    def _recency_penalty(url):
        """Freshly-used sources are demoted so neighbouring steps rotate to
        other on-topic links instead of repeating the same pair; older sources
        decay back toward their real score."""
        history = used_history
        last = -1
        for idx, used_url in enumerate(history):
            if used_url == url:
                last = idx
        if last < 0 or not history:
            return 0
        recency = (len(history) - 1) - last
        if recency <= 0:
            return 22
        if recency == 1:
            return 14
        if recency == 2:
            return 6
        return 2

    used_history = list(exclude or ())
    adjusted = sorted(
        ((score - _recency_penalty(c["url"]), score, c) for score, c in scored),
        key=lambda pair: (pair[0], pair[1]),
        reverse=True,
    )
    # A one- or two-item pool cannot sustain distinct pairs, so drop to a
    # single best-match per step rather than duplicating the same two links.
    limit = max(1, min(int(max_items or 2), 3))
    if len(adjusted) < 2:
        limit = 1
    chosen, seen = [], set()
    for _adjusted_score, _orig_score, cand in adjusted:
        if cand["url"] in seen:
            continue
        seen.add(cand["url"])
        chosen.append(_enrich_resource(cand, skill_name, step_objective, target_role))
        if len(chosen) >= limit:
            break
    return chosen


def _ranks_for(chosen, pool):
    """1-based indexes of the chosen step resources into the ranked pool."""
    if not pool or not chosen:
        return []
    index = {str(r.get("url")): i + 1 for i, r in enumerate(pool)}
    return [index[r["url"]] for r in chosen if r.get("url") in index]


def _public_resource(resource, rank=None, fallback=False):
    clean = _strip_internal(resource)
    if clean.get("unavailable"):
        # Honest 'no validated direct resource yet' marker — passes through the
        # pipeline as a real state, not a fabricated link.
        clean["type"] = "other"
        clean["type_label"] = _TYPE_LABELS.get("other", "Other")
        clean["cta"] = _TYPE_CTA.get("other", "Open Resource")
        clean["url"] = ""
        clean["provider"] = clean.get("provider") or clean.get("source") or "SkillBridge"
        clean["source_kind"] = clean.get("source_kind") or ("curated_fallback" if fallback else "curated")
        clean["status"] = clean.get("status") or "Unavailable"
        clean["is_direct_resource"] = False
        clean["verified"] = False
        clean["estimated_minutes"] = 0
        clean["reason"] = clean.get("reason") or "No validated direct resource available yet."
        if rank is not None:
            clean["rank"] = rank
        return clean
    if not clean.get("url") or not is_safe_public_url(clean.get("url")):
        return None
    res_type = canonical_resource_type(clean.get("type"))
    clean["type"] = res_type
    clean["type_label"] = _TYPE_LABELS.get(res_type, res_type.title())
    clean["cta"] = clean.get("cta") or _TYPE_CTA.get(res_type, _TYPE_CTA["other"])
    clean["provider"] = clean.get("provider") or clean.get("source") or _provider_from_url(clean.get("url"))
    clean["is_direct_resource"] = bool(clean.get(
        "is_direct_resource", not is_generic_resource_url(clean.get("url"))))
    clean["verified"] = bool(clean.get("verified", True))
    clean["estimated_minutes"] = int(clean.get("estimated_minutes") or _TYPE_MINUTES.get(res_type, 20))
    if rank is not None:
        clean["rank"] = rank
    clean["helpfulness"] = clean.get("helpfulness") or _HELPFULNESS.get(
        res_type, "Curated learning resource")
    if not clean.get("reason"):
        clean["reason"] = clean["helpfulness"]
    clean["source_kind"] = clean.get("source_kind") or (
        "curated_fallback" if fallback else "curated")
    clean["status"] = clean.get("status") or _availability_status(clean.get("available"))
    return clean


def _topic_resource_entries(skill_name, competency, target_role=None):
    skill_low = str(skill_name or "").lower()
    topic_low = str(competency or "").lower().replace("_", " ")
    role_low = str(target_role or "").lower()
    entries = []
    for key, pool in _TOPIC_CURATED.items():
        if key not in skill_low and key not in topic_low:
            continue
        for entry in pool:
            topic_terms = entry.get("_topics") or ()
            role_terms = entry.get("_roles") or ()
            topic_match = (
                not topic_terms
                or any(term in topic_low for term in topic_terms)
                or any(tok in _tokens(topic_low) for tok in _tokens(" ".join(topic_terms)))
            )
            role_match = role_low and role_terms and any(term in role_low for term in role_terms)
            if topic_match or role_match:
                entries.append(dict(entry))
    return entries


def _level_score(entry, required_level):
    target = _LEVEL_RANK.get(str(required_level or "").lower())
    levels = entry.get("_levels") or ()
    if target is None or not levels:
        return 0
    distances = [
        abs(target - _LEVEL_RANK[level])
        for level in levels
        if level in _LEVEL_RANK
    ]
    if not distances:
        return 0
    return max(0, 18 - (min(distances) * 8))


def _role_score(entry, target_role):
    role_low = str(target_role or "").lower()
    role_terms = entry.get("_roles") or ()
    if not role_low or not role_terms:
        return 0
    return 10 if any(term in role_low for term in role_terms) else 0


def _lesson_resource_score(entry, skill_name, competency, required_level,
                           target_role, order):
    haystack = " ".join(str(entry.get(k) or "") for k in (
        "title", "source", "url", "reason", "helpfulness"))
    hay = haystack.lower().replace("_", " ")
    topic_tokens = _tokens(str(competency or "").replace("_", " "))
    skill_tokens = _tokens(skill_name)
    score = 100 - order
    score += 8 * len((topic_tokens - {"fundamentals", "basics"}).intersection(_tokens(hay)))
    score += 3 * len(skill_tokens.intersection(_tokens(hay)))
    score += _level_score(entry, required_level)
    score += _role_score(entry, target_role)
    if entry.get("source_kind") == "curated_fallback":
        score -= 25
    source = str(entry.get("source") or "").lower()
    if source in ("pandas", "docker", "pytorch", "python.org", "scikit-learn"):
        score += 8
    return score


def _dedupe_resources(resources):
    seen = set()
    out = []
    for item in resources or []:
        if not isinstance(item, dict):
            continue
        if item.get("unavailable"):
            out.append(dict(item))
            continue
        url = str(item.get("url") or "").strip()
        if not url or url in seen or not is_safe_public_url(url):
            continue
        seen.add(url)
        clean = dict(item)
        clean["url"] = url
        out.append(clean)
    return out


def _annotate_or_unknown(resources):
    try:
        return annotate_resources(resources)
    except Exception:
        return [dict(r, available=None) for r in resources]


def recommend_lesson_resources(skill_name, category, competency,
                               required_level=None, target_role=None,
                               live_check=True, max_items=4):
    """Concise topic-level resources for the personalized lesson view.

    URLs come only from the curated catalog and skill-scoped deterministic
    fallback links. The model is deliberately not allowed to supply lesson
    resource URLs.
    """
    skill_key = (skill_name or "").strip().lower()
    topic_entries = _topic_resource_entries(skill_name, competency, target_role)
    skill_entries = curated_resources(skill_name, category)
    fallback = skill_key not in _CURATED and category not in _CATEGORY_BASE
    if not topic_entries and not skill_entries:
        skill_entries = _generic_fallback(skill_name)
        fallback = True

    topic_safe = _dedupe_resources(topic_entries)
    candidates = [dict(entry) for entry in topic_safe]
    if len(topic_safe) < 2:
        for entry in skill_entries:
            item = dict(entry)
            item.setdefault("reason", f"Curated support for {skill_name}.")
            item.setdefault("source_kind", "curated_fallback" if fallback else "curated")
            candidates.append(item)
    if not candidates:
        candidates = _generic_fallback(skill_name)
        fallback = True

    safe = _dedupe_resources(candidates)
    # Directness gate: platform/channel/category/search pages are never shown
    # as lesson resources. When everything got filtered, fall through to the
    # honest 'resource unavailable' marker instead of a deeper fake link.
    safe = [r for r in safe
            if not r.get("unavailable") and not is_generic_resource_url(r.get("url"))]
    safe = sanitize_resources(safe)
    if not safe:
        safe = _dedupe_resources(_generic_fallback(skill_name))
        for item in safe:
            item["source_kind"] = "curated_fallback"
            item.setdefault("reason", f"No validated direct resource is available yet for {skill_name}.")
    scored = [
        (_lesson_resource_score(r, skill_name, competency, required_level, target_role, i), r)
        for i, r in enumerate(safe)
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    safe = [r for _, r in scored]

    if live_check:
        annotated = _annotate_or_unknown(safe)
        available = [r for r in annotated if r.get("available") is True]
        unknown = [r for r in annotated if r.get("available") is None]
        selected = available + unknown
        if not selected:
            selected = [dict(r, available=None) for r in safe]
    else:
        selected = [dict(r, available=None) for r in safe]

    public = []
    for i, item in enumerate(selected, start=1):
        res = _public_resource(item, rank=len(public) + 1,
                               fallback=item.get("source_kind") == "curated_fallback")
        if res:
            public.append(res)
        if len(public) >= max(2, min(4, int(max_items or 4))):
            break
    return public


def retrieve_resources(skill_name, category, target_role=None, live_check=True, max_items=8):
    """Ranked, real resource list for a skill — most helpful first.

    Videos first (fast context), then articles/docs, then full courses. When a
    live search key is set, current videos from the YouTube API merge in at the
    top; the curated index always provides genuine article/doc/course links.
    
    Resources are annotated with 'available' field (True/False/None) so the UI
    can show dead-link badges. Dead links are dropped; at least 1 resource
    per skill is kept (fallback to unknown-status links).
    """
    resources = curated_resources(skill_name, category)
    if YOUTUBE_API_KEY:
        live_videos = _search_youtube(skill_name, target_role or "")
        if live_videos:
            resources = live_videos + resources

    seen, merged = set(), []
    for r in resources:
        url = str(r.get("url") or "").strip()
        if not url or url in seen or not is_safe_public_url(url):
            continue
        seen.add(url)
        item = dict(r)
        item["url"] = url
        merged.append(item)
    # Directness gate: search pages, platform category indexes, channel
    # homepages and bare vendor/doc roots never rank as resources.
    merged = [item for item in merged if not is_generic_resource_url(item["url"])]
    merged = sanitize_resources(merged)

    if live_check:
        # Annotate with availability, then filter to live links (keep at least 1)
        merged = _annotate_or_unknown(merged)
        merged = choose_live(merged, min_keep=1)

    public = []
    for r in merged[:max_items]:
        item = _public_resource(r, rank=len(public) + 1)
        if item:
            public.append(item)
    return public
