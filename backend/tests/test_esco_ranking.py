"""Hermetic ranking tests for the ESCO market-occupation scorer.

The scorer is intentionally general-purpose: it must rank the occupation the
query *means* first for any career (cybersecurity, data science, nursing,
teaching, mechanical engineering, design, marketing, accounting, ...) while
excluding occupations that merely share a generic token ("securities analyst"
must not beat "ICT security consultant" for a "cybersecurity analyst" query,
and "security guard" / "social security administrator" must fall below the
relevance threshold).

These tests fake the two public ESCO REST endpoints (search + resource) with a
small but realistic occupation registry, so nothing depends on the network.
"""
import pytest

from app import escoe


def _reset_cache():
    escoe._cache.update({"at": 0.0, "query": "", "data": None})


class _Resp:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


# Realistic ESCO occupation registry: title, uri, ISCO-08 code, a short
# definition and essential skills. Mirrors the shapes observed from the live
# ESCO API (multiple "X analyst" occupations exist; the ICT security family
# lives under ISCO codes 2529/2519/3512; physical security is 5414; social
# welfare security is 1213/3353).
_REGISTRY = [
    # ---- ICT security family (ISCO 25) ----
    ("ICT security consultant", "occ/ict-security-consultant", "2529.1",
     "advise and implement solutions to control access to data and programs, and promote a safe exchange of information",
     ["cyber attack counter-measures", "information security strategy", "identify ICT security risks"]),
    ("ICT security manager", "occ/ict-security-manager", "2529.2",
     "propose and implement security updates and take direct action on a network or system",
     ["ICT security standards", "manage IT security compliances", "ICT identity management"]),
    ("ICT security administrator", "occ/ict-security-admin", "2529.3",
     "plan and carry out security measures to protect information and data from unauthorised access",
     ["cyber attack counter-measures", "ICT network security risks", "system backup best practice"]),
    ("Chief ICT security officer", "occ/chief-ict-sec", "2529.4",
     "protect company and employee information against unauthorized access and define the information system security policy",
     ["ICT security legislation", "manage IT security compliances", "ICT security standards"]),
    ("Ethical hacker", "occ/ethical-hacker", "2529.5",
     "perform security vulnerability assessments and penetration tests",
     ["cyber attack counter-measures", "computer forensics", "penetration testing tool"]),
    ("ICT resilience manager", "occ/ict-resilience", "2529.6",
     "enhance an organisation's cyber security, resilience and disaster recovery",
     ["identify ICT security risks", "develop information security strategy", "manage disaster recovery plans"]),
    ("ICT disaster recovery analyst", "occ/ict-dr-analyst", "2519.8",
     "develop and implement ICT continuity and disaster recovery strategies",
     ["ICT recovery techniques", "manage disaster recovery plans", "ICT problem management techniques"]),
    # ---- generic "analyst" tail occupations (unrelated to cybersecurity) ----
    ("Securities analyst", "occ/securities-analyst", "2413.1",
     "research financial and legal information about prices, stability and investment trends",
     ["investment analysis", "financial markets", "economic forecasting"]),
    ("Financial analyst", "occ/financial-analyst", "2413.2",
     "conduct economic research on profitability, liquidity and solvency",
     ["financial management", "budgeting"]),
    ("Call centre analyst", "occ/call-centre-analyst", "3341.1",
     "examine data regarding incoming and outgoing customer calls",
     ["customer service", "statistical analysis"]),
    ("Tax policy analyst", "occ/tax-policy-analyst", "2631.1",
     "research and develop taxation policies and legislation",
     ["tax law", "economic analysis"]),
    ("Logistics analyst", "occ/logistics-analyst", "2141.4",
     "streamline product manufacturing, transportation, storage and distribution",
     ["supply chain analysis", "transportation management"]),
    ("Data analyst", "occ/data-analyst", "2511.1",
     "import, inspect, clean and model collections of data with regard to business goals",
     ["data analysis", "SQL", "statistical analysis"]),
    # ---- physical / social welfare security (false friends) ----
    ("Security guard", "occ/security-guard", "5414.1",
     "protect people, buildings and assets, patrol designated property areas and control access at entrances",
     ["patrol areas", "surveillance methods", "identify security threats"]),
    ("Security consultant", "occ/security-consultant", "5414.2",
     "provide security services to prevent and mitigate threats such as terrorism and theft to buildings and employees",
     ["security risk management", "threat analysis", "assess risks of assets"]),
    ("Security manager", "occ/security-manager", "1219.1",
     "ensure security for people and company assets by enforcing security policies and supervising security staff",
     ["manage security teams", "emergency procedures", "security audits"]),
    ("Social security administrator", "occ/social-sec-admin", "1213.1",
     "direct government-provided social security programmes in order to aid public welfare",
     ["social security law", "government policy implementation"]),
    ("Securities underwriter", "occ/securities-underwriter", "3311.1",
     "administer the distribution of new securities for a business company and buys and sells them to investors",
     ["financial markets", "investment analysis"]),
    # ---- other careers (ISCO families) ----
    ("Data scientist", "occ/data-scientist", "2529.9",
     "develop statistical and machine learning models to extract insights from structured and unstructured data",
     ["machine learning", "statistics", "data science"]),
    ("Accountant", "occ/accountant", "2411.2",
     "prepare financial statements, ensure compliance with accounting standards and advise on taxation",
     ["accounting", "financial statements", "tax compliance"]),
    ("Registered nurse", "occ/registered-nurse", "2221.2",
     "provide care and treatment to patients in healthcare settings and plan care for individuals and communities",
     ["patient care", "clinical assessment", "care planning"]),
    ("Primary school teacher", "occ/primary-teacher", "2341.1",
     "teach children foundational subjects and support their social and emotional development",
     ["lesson planning", "classroom management", "child development"]),
    ("Mechanical engineer", "occ/mechanical-engineer", "2144.1",
     "design and develop mechanical systems and products and supervise their production",
     ["mechanical design", "CAD", "thermodynamics"]),
    ("Graphic designer", "occ/graphic-designer", "2161.1",
     "create visual concepts to communicate ideas that inspire, inform and captivate consumers",
     ["graphic design", "brand identity", "adobe illustrator"]),
    ("Marketing manager", "occ/marketing-manager", "1221.1",
     "plan and coordinate marketing campaigns, market research and product promotion",
     ["marketing strategy", "market research", "digital marketing"]),
    ("Network engineer", "occ/network-engineer", "2523.1",
     "design, implement and maintain computer networks and ensure their performance",
     ["network protocols", "routing and switching", "network security"]),
    ("Software developer", "occ/software-developer", "2512.1",
     "design and build software applications following user requirements",
     ["software development", "programming", "testing"]),
]

_BY_URI = {uri: (title, code, desc, skills) for title, uri, code, desc, skills in _REGISTRY}


def _matches(q_text, title, desc="", skills=()):
    """Fake the lexical behaviour of ESCO's own search: an occupation is a
    search result when any query token equals, is contained in or contains
    any token of the occupation's title, definition or skills (real ESCO
    indexes all three fields, which is why e.g. "ethical hacker" surfaces for
    a "cybersecurity analyst" query while "graphic designer" does not)."""
    qt = set(escoe._words(q_text))
    tt = set(escoe._words(title))
    tt.update(escoe._words(desc))
    for s in skills:
        tt.update(escoe._words(s))
    for w in qt:
        for t2 in tt:
            if w == t2 or (min(len(w), len(t2)) >= 4 and (w in t2 or t2 in w)):
                return True
    return False


def _fake_get_factory():
    calls = []

    def fake_get(url, **kwargs):
        calls.append(str(url))
        if "search" in str(url):
            text = (kwargs.get("params") or {}).get("text") or ""
            results = [
                {"title": title, "uri": uri, "code": code}
                for title, uri, code, desc, skills in _REGISTRY
                if _matches(text, title, desc, skills)
            ]
            return _Resp({"_embedded": {"results": results}})
        uri = (kwargs.get("params") or {}).get("uri")
        title, code, desc, skills = _BY_URI[uri]
        return _Resp({
            "code": code,
            "description": {"literal": desc},
            "_links": {"hasEssentialSkill": [{"title": s} for s in skills]},
        })

    return fake_get, calls


@pytest.fixture(autouse=True)
def _esco_fake(monkeypatch):
    _reset_cache()
    fake_get, _ = _fake_get_factory()
    monkeypatch.setattr(escoe.httpx, "get", fake_get)


def _titles(out):
    return [o["title"] for o in out]


def _assert_first(out, expected, note=""):
    assert out, f"no occupations returned {note}"
    assert out[0]["title"] == expected, (
        f"expected first {expected!r}, got {[o['title'] for o in out]} {note}")


def test_cybersecurity_analyst_ranks_ict_security_first():
    out = escoe.market_occupations("cybersecurity analyst", limit=8)
    first_title = out[0]["title"]
    assert first_title.startswith("ICT security") or first_title == "Chief ICT security officer", [
        o["title"] for o in out]
    assert out[0]["code"] and str(out[0]["code"]).startswith("25"), [o["code"] for o in out[:3]]
    titles = _titles(out)
    assert titles.index("ICT security consultant") < titles.index("Ethical hacker") if "Ethical hacker" in titles else True
    assert not any(o["code"] and str(o["code"]).startswith("54") for o in out), (
        "physical-security occupations must not beat the ICT security family")


def test_cybersecurity_analyst_excludes_analyst_tail_offenders():
    out = escoe.market_occupations("cybersecurity analyst", limit=8)
    titles = _titles(out)
    assert "Securities analyst" not in titles
    assert "Financial analyst" not in titles
    assert "Call centre analyst" not in titles
    assert "Tax policy analyst" not in titles


def test_cybersecurity_excludes_physical_and_social_security():
    out = escoe.market_occupations("cybersecurity", limit=10)
    titles = _titles(out)
    assert "Security guard" not in titles
    assert "Security manager" not in titles
    assert "Social security administrator" not in titles
    assert "Securities underwriter" not in titles
    assert any(t.startswith("ICT security") for t in titles[:3]), titles[:3]


def test_ict_security_beats_security_guard_lexically():
    """The containment trap: 'security' lives in both cybersecurity and
    security guard titles. ISCO-08 domain evidence (25 vs 54) must decide."""
    out = escoe.market_occupations("cybersecurity analyst", limit=10)
    scores = {o["title"]: o["score"] for o in out}
    assert scores.get("ICT security manager", 0.0) > scores.get("Security guard", 0.0)


def test_distant_but_meaningful_roles_still_surface():
    out = escoe.market_occupations("cybersecurity analyst", limit=10)
    titles = _titles(out)
    assert "Ethical hacker" in titles or "ICT resilience manager" in titles


@pytest.mark.parametrize("query,expected_first,allowed_prefixes", [
    ("data scientist", "Data scientist", []),
    ("accountant", "Accountant", []),
    ("registered nurse", "Registered nurse", ["2221"]),
    ("primary school teacher", "Primary school teacher", ["2341"]),
    ("mechanical engineer", "Mechanical engineer", []),
    ("graphic designer", "Graphic designer", []),
    ("marketing manager", "Marketing manager", []),
    ("network engineer", "Network engineer", []),
    ("software developer", "Software developer", []),
])
def test_unrelated_careers_rank_their_own_first(query, expected_first, allowed_prefixes):
    out = escoe.market_occupations(query, limit=4)
    assert out, f"no occupations for {query!r}"
    assert out[0]["title"] == expected_first, [
        o["title"] for o in out]
    if allowed_prefixes:
        assert str(out[0]["code"]).startswith(allowed_prefixes[0]), out[0]


def test_unrelated_careers_do_not_return_off_field_occupations():
    out_me = escoe.market_occupations("mechanical engineer", limit=4)
    me_titles = _titles(out_me)
    # generic analysts / nurses must not appear for a mechanical-engineering query
    for banned in ("Accountant", "Registered nurse", "Financial analyst", "Security guard"):
        assert banned not in me_titles
    out_nurse = escoe.market_occupations("nurse", limit=4)
    assert all("engineer" not in t.lower() for t in _titles(out_nurse))


def test_empty_and_blank_queries():
    assert escoe.market_occupations("   ") == []
    assert escoe.market_occupations("") == []


def test_never_raises_on_network_failure(monkeypatch):
    _reset_cache()

    def fail_get(*args, **kwargs):
        raise RuntimeError("esco down")

    monkeypatch.setattr(escoe.httpx, "get", fail_get)
    assert escoe.market_occupations("data scientist") == []