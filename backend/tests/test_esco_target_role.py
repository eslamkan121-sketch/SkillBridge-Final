"""§2b/§3/§4 — final acceptance proofs for the ESCO Target-Role path.

The Skills & Roles → Live Market Roles surface calls
``GET /api/roles/esco-market?target_role=<title>`` (see api.ts), which routes
through ``escoe.market_occupations_for_role`` (NOT the free-text
``market_occupations`` path). That role-title path had zero hermetic coverage:
every existing ESCO test exercised the free-text route only.

These tests reuse the same realistic mocked ESCO registry as
``test_esco_ranking.py`` and lock in the acceptance contract:

  1. Selected Target Role → Live Market Roles returns RELEVANT official
     occupations for Cybersecurity Analyst / Graphic Designer / Financial
     Analyst / Legal Assistant (with no requirement that the exact user-facing
     role wording equal an ESCO preferred label).
  2. Unrelated occupations (analyst-tail offenders, other ISCO families) are
     never returned.
  3. The endpoint honors the ``target_role`` query param and uses the
     role-title resolution path.
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


# Realistic ESCO occupation registry (same spirit as test_esco_ranking.py):
# title, uri, ISCO-08 unit group, definition, essential skills.
_REGISTRY = [
    # ---- ICT security family (ISCO 25) ----
    ("ICT security consultant", "occ/ict-security-consultant", "2529",
     "advise and implement solutions to control access to data and programs",
     ["cyber attack counter-measures", "information security strategy"]),
    ("ICT security manager", "occ/ict-security-manager", "2529",
     "propose and implement security updates and take direct action",
     ["ICT security standards", "manage IT security compliances"]),
    ("ICT security administrator", "occ/ict-security-admin", "2529",
     "plan and carry out security measures to protect information and data",
     ["cyber attack counter-measures", "system backup best practice"]),
    ("Chief ICT security officer", "occ/chief-ict-sec", "2529",
     "protect company and employee information against unauthorized access",
     ["ICT security legislation", "ICT security standards"]),
    ("ICS security technician", "occ/ics-security-technician", "3512",
     "protect industrial control systems from cyber threats",
     ["industrial control system security", "cyber attack counter-measures"]),
    # ---- generic "analyst" tail occupations (unrelated to cybersecurity) ----
    ("Securities analyst", "occ/securities-analyst", "2413",
     "research financial and legal information about prices and investment trends",
     ["investment analysis", "financial markets"]),
    ("Financial analyst", "occ/financial-analyst", "2413",
     "conduct economic research on profitability, liquidity and solvency",
     ["financial management", "budgeting"]),
    ("Call centre analyst", "occ/call-centre-analyst", "3341",
     "examine data regarding incoming and outgoing customer calls",
     ["customer service", "statistical analysis"]),
    ("Tax policy analyst", "occ/tax-policy-analyst", "2631",
     "research and develop taxation policies and legislation",
     ["tax law", "economic analysis"]),
    # ---- financial family ----
    ("Financial risk analyst", "occ/financial-risk-analyst", "2413",
     "identify and assess risks that might threaten the assets of an organisation",
     ["risk management", "financial analysis"]),
    ("Financial auditor", "occ/financial-auditor", "2411",
     "verify the correctness of financial statements",
     ["accounting", "financial auditing"]),
    # ---- legal family ----
    ("Legal assistant", "occ/legal-assistant", "3411",
     "support legal professionals with case preparation and documentation",
     ["legal research", "document drafting"]),
    ("Paralegal", "occ/paralegal", "3411",
     "assist lawyers with legal research and case management",
     ["legal research", "case management"]),
    ("Legal secretary", "occ/legal-secretary", "3342",
     "provide administrative support within a legal environment",
     ["legal terminology", "secretarial skills"]),
    # ---- design family ----
    ("Graphic designer", "occ/graphic-designer", "2166",
     "create visual concepts to communicate ideas that inspire and inform",
     ["graphic design", "adobe illustrator"]),
    ("Brand designer", "occ/brand-designer", "2166",
     "develop visual identities for brands",
     ["brand identity", "typography"]),
    ("Multimedia designer", "occ/multimedia-designer", "2166",
     "create multimedia content for digital media",
     ["multimedia production", "graphic design"]),
    ("Visual merchandiser", "occ/visual-merchandiser", "3432",
     "design and set up displays in shops to promote sales",
     ["display design", "customer engagement"]),
    # ---- other careers (must never leak) ----
    ("Registered nurse", "occ/registered-nurse", "2221",
     "provide care and treatment to patients",
     ["patient care", "clinical assessment"]),
    ("Mechanical engineer", "occ/mechanical-engineer", "2144",
     "design and develop mechanical systems",
     ["mechanical design", "CAD"]),
    ("Primary school teacher", "occ/primary-teacher", "2341",
     "teach children foundational subjects",
     ["lesson planning", "classroom management"]),
]

_BY_URI = {uri: (title, code, desc, skills) for title, uri, code, desc, skills in _REGISTRY}


def _matches(q_text, title, desc="", skills=()):
    """Fake ESCO's own lexical search: a query token matches when it equals,
    contains or is contained in any token of title/definition/skills."""
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


# ---------------------------------------------------------------------------
# Acceptance §3 / §4: the target-role ESCO path returns relevant occupations
# for each accepted career, and never drifts to unrelated careers.
# ---------------------------------------------------------------------------

class TestEscoTargetRoleAcceptance:
    """Selected Target Role → Live Market Roles must surface the target's own
    official ESCO occupation family. The exact user-facing wording need not
    equal an ESCO preferred label (e.g. "Cybersecurity Analyst" → "ICT
    security manager"), and unrelated careers must never leak."""

    def test_cybersecurity_analyst_returns_security_family(self):
        out = escoe.market_occupations_for_role("Cybersecurity Analyst", limit=8)
        titles = _titles(out)
        assert out, "Cybersecurity Analyst must return ESCO occupations"
        # The ICT security family must lead (ISCO 25), not physical/other.
        assert any(t.startswith("ICT security") or t == "Chief ICT security officer"
                   for t in titles[:3]), titles[:3]
        assert any(str(o.get("code", "")).startswith("25")
                   for o in out), [o.get("code") for o in out]
        # Generic analyst-tail offenders and unrelated careers must be absent.
        for banned in ("Securities analyst", "Financial analyst",
                       "Call centre analyst", "Tax policy analyst",
                       "Registered nurse", "Primary school teacher",
                       "Mechanical engineer"):
            assert banned not in titles, f"{banned} leaked into cybersecurity ESCO results"
        # Occupations must be classified as relevant (never UNRELATED).
        assert all(o["relevant"] != "UNRELATED" for o in out), [
            (o["title"], o["relevant"]) for o in out]

    def test_graphic_designer_returns_design_family(self):
        out = escoe.market_occupations_for_role("Graphic Designer", limit=8)
        titles = _titles(out)
        assert out, "Graphic Designer must return ESCO occupations"
        assert "Graphic designer" in titles
        # Design-era official occupations surface; non-design never leaks.
        assert any("design" in t.lower() or "brand" in t.lower()
                   for t in titles[:3]), titles[:3]
        for banned in ("Registered nurse", "Mechanical engineer",
                       "Financial analyst", "Securities analyst",
                       "Legal assistant"):
            assert banned not in titles, f"{banned} leaked into design ESCO results"
        assert all(o["relevant"] != "UNRELATED" for o in out)

    def test_financial_analyst_returns_finance_family(self):
        out = escoe.market_occupations_for_role("Financial Analyst", limit=8)
        titles = _titles(out)
        assert out, "Financial Analyst must return ESCO occupations"
        assert any(t.lower() == "financial analyst" or t.lower() == "financial risk analyst"
                   for t in titles), titles
        # Genuinely finance-family siblings (e.g. tax policy analyst) are
        # allowed as FAMILY; truly unrelated careers must never leak.
        for banned in ("Call centre analyst", "Registered nurse",
                       "Graphic designer", "Primary school teacher",
                       "Securities analyst"):
            assert banned not in titles, f"{banned} leaked into finance ESCO results"
        assert out[0]["relevant"] == "EXACT", out[0]
        # Everything surfaced must be finance-relevant (never UNRELATED).
        assert all(o["relevant"] != "UNRELATED" for o in out), [o for o in out]

    def test_legal_assistant_returns_legal_family(self):
        out = escoe.market_occupations_for_role("Legal Assistant", limit=8)
        titles = _titles(out)
        assert out, "Legal Assistant must return ESCO occupations"
        assert "Legal assistant" in titles
        assert any("legal" in t.lower() for t in titles), titles
        for banned in ("Registered nurse", "Mechanical engineer",
                       "Financial analyst", "Graphic designer",
                       "Securities analyst"):
            assert banned not in titles, f"{banned} leaked into legal ESCO results"
        assert out[0]["relevant"] == "EXACT", out[0]

    def test_exact_preferred_label_not_required(self):
        """'Cybersecurity Analyst' is NOT an ESCO preferred label — yet the
        role-title path still resolves the ICT security family via trusted
        aliases + synonym-aware classification. This is the acceptance-criteria
        requirement in code."""
        out = escoe.market_occupations_for_role("Cybersecurity Analyst", limit=4)
        titles = _titles(out)
        # None of the surfaced titles need the literal word "cybersecurity".
        assert any("security" in t.lower() for t in titles), titles
        assert any(t.startswith("ICT security") for t in titles), titles

    def test_alias_queries_are_bounded_and_never_broad(self):
        """provider_queries must stay on the target's own vocabulary (title +
        trusted aliases), never broad generic skill words."""
        from app import role_intent
        qs = role_intent.provider_queries("Cybersecurity Analyst", max_queries=5)
        assert qs[0] == "Cybersecurity Analyst"
        for q in qs:
            assert "communication" not in q.lower()
            assert "management" not in q.lower()
            assert "excel" not in q.lower()


# ---------------------------------------------------------------------------
# Acceptance §3: the public endpoint honors the target_role query param and
# routes through the role-title path.
# ---------------------------------------------------------------------------

class TestEscoTargetRoleEndpoint:
    def test_endpoint_with_target_role_returns_occupations(self, client, auth_headers):
        from app import main
        captured = {}

        def fake_for_role(title, limit=8):
            captured["title"] = title
            return [{"title": "ICT security manager", "uri": "x",
                     "skills": ["ICT security standards"], "skill_count": 1}]

        monkeypatch_target = _fake_for_role_patch(main, fake_for_role)
        with monkeypatch_target:
            headers = auth_headers("aisha@student.edu")
            r = client.get("/api/roles/esco-market",
                           params={"q": "anything", "target_role": "Cybersecurity Analyst",
                                   "limit": 5},
                           headers=headers)
        assert r.status_code == 200
        payload = r.json()
        assert captured["title"] == "Cybersecurity Analyst"
        assert payload["status"] == "ok"
        assert payload["occupations"][0]["title"] == "ICT security manager"

    def test_endpoint_without_target_role_uses_free_text(self, client, auth_headers):
        """No target role → free-text ESCO search (general box), unchanged."""
        from app import main

        original = main.escoe.market_occupations
        try:
            main.escoe.market_occupations = lambda text, limit=10: [
                {"title": "Graphic designer", "uri": "occ-gd",
                 "skills": ["graphic design"], "skill_count": 1}]
            headers = auth_headers("aisha@student.edu")
            r = client.get("/api/roles/esco-market",
                           params={"q": "designer", "limit": 5},
                           headers=headers)
            assert r.status_code == 200
            payload = r.json()
            assert payload["status"] == "ok"
            assert payload["occupations"][0]["title"] == "Graphic designer"
        finally:
            main.escoe.market_occupations = original


def _fake_for_role_patch(main_mod, fake):
    """Context manager swapping main.escoe.market_occupations_for_role."""
    import contextlib

    @contextlib.contextmanager
    def _cm():
        original = main_mod.escoe.market_occupations_for_role
        main_mod.escoe.market_occupations_for_role = fake
        try:
            yield
        finally:
            main_mod.escoe.market_occupations_for_role = original
    return _cm()