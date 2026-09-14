"""P1-1 regression: relevant roles must outrank irrelevant ones (Post-Phase Q).

Live reproduction before the fix (ICT security manager profile, Cairo/Egypt):
  - Junior Crypto Analyst & Trader           72%  (classifier FAMILY, zero title evidence)
  - Work From Home Bilingual Client Services 66%  (classifier FAMILY, zero title evidence)
  - Head of Security Engineering             40%  (CLOSE, genuinely on-target)
  - Manager Cyber Compliance Deloitte        36%  (FAMILY, cyber family word in title)

Root causes fixed:
  1. role_intent.family_of() let one loose substring ("crypto" inside
     "cryptography", "services" inside a support term) commit a title to a
     career family, so genuinely unrelated listings were classified FAMILY for
     an ICT security target and ranked high purely on description keyword
     overlap. family_of now requires an EXACT family-term membership, so those
     titles resolve UNRELATED and never reach the feed.
  2. _build_result re-bucketed by location (local -> broader -> other) BEFORE
     surfacing, so a genuinely relevant title in another country sank below a
     same-family remote/unknown-location listing. Selection now follows the
     dominance contract order (tier -> title evidence -> location -> score).
"""

import pytest

from app import jobs, role_intent

# ICT security manager profile (mirrors the live reproduction profile):
# required-skill phrases driven by the role, plus CV skills with levels.
_ROLE = "ICT security manager"
_REQUISITES = [
    "ICT Security Standards", "Define Security Policies",
    "Information Security Strategy", "Risk Assessment", "Compliance",
    "Vulnerability Management", "Incident Response", "Network Security",
    "Cyber Security",
]
_SKILLS = [
    ("Security", "Advanced"),
    ("Network Security", "Intermediate"),
    ("Incident Response", "Intermediate"),
    ("Vulnerability Management", "Advanced"),
    ("Risk Assessment", "Intermediate"),
    ("Excel", "Intermediate"),
    ("Bilingual", "Beginner"),
]


def _rank(raw_jobs, role=_ROLE, requisites=_REQUISITES, skills=_SKILLS,
          country="Egypt", city="Cairo"):
    primary, minor = jobs._cluster_keywords(
        [s[0] for s in skills], role, requisites)
    return jobs._apply(
        raw_jobs, primary,
        jobs._student_seniority([s[1] for s in skills]),
        country, city,
        jobs._role_family(role),
        minor_keywords=minor, role_driven=True, role_title=role)


# The four live listings from the reproduction feed.
def _four_jobs():
    return [
        {"title": "Junior Crypto Analyst & Trader", "company": "Tradedesk",
         "url": "crypto1", "location": "Remote",
         "tags": ["crypto", "trading", "analysis"], "source": "T",
         "listed_days_ago": 10},
        {"title": "Work From Home Bilingual Client Services Representative",
         "company": "ContactCo", "url": "wfh1", "location": "Evanston, Wyoming",
         "tags": ["bilingual", "customer service"], "source": "T",
         "listed_days_ago": 28},
        {"title": "Head of Security Engineering", "company": "SecureCo",
         "url": "head1", "location": "United States",
         "tags": ["security", "leadership"], "source": "T",
         "listed_days_ago": 1},
        {"title": "Manager Cyber Compliance Deloitte", "company": "Deloitte",
         "url": "del1", "location": "United States",
         "tags": ["compliance", "cyber"], "source": "T",
         "listed_days_ago": 2},
    ]


class TestP11DominanceRegression:
    """The classifier must refuse junk titles before the feed pipeline ever
    sees them; on-target titles keep their bands."""

    def test_family_of_requires_exact_membership(self):
        # Loose substrings alone never commit a title to a family; a title with
        # a genuine exact family term resolves normally.
        assert role_intent.family_of("Database Administrator") == "data"
        assert role_intent.family_of("Head of Security Engineering") == "security"
        assert role_intent.family_of("Manager Cyber Compliance Deloitte") == "security"
        assert role_intent.family_of("Junior Crypto Analyst & Trader") == ""
        assert role_intent.family_of(
            "Work From Home Bilingual Client Services Representative") == ""

    def test_irrelevant_titles_classify_unrelated(self):
        labels = {
            "Junior Crypto Analyst & Trader": "UNRELATED",
            "Work From Home Bilingual Client Services Representative": "UNRELATED",
            "Head of Security Engineering": "CLOSE",
            "Manager Cyber Compliance Deloitte": "FAMILY",
        }
        for title, expected in labels.items():
            assert role_intent.classify_title(_ROLE, title) == expected, \
                f"{title!r} expected {expected} — tightening family_of to exact " \
                "membership is what keeps unrelated careers out of the feed"

    def test_irrelevant_titles_never_surface(self):
        ranked = _rank(_four_jobs())
        titles = [j["title"] for j in ranked]
        for bad in (
                "Junior Crypto Analyst & Trader",
                "Work From Home Bilingual Client Services Representative"):
            assert bad not in titles, \
                f"{bad!r} must not rank for an ICT security manager target"

    def test_relevant_titles_outrank_within_the_feed(self):
        ranked = _rank(_four_jobs())
        titles = [j["title"] for j in ranked]
        assert "Head of Security Engineering" in titles
        assert "Manager Cyber Compliance Deloitte" in titles
        assert titles.index("Head of Security Engineering") < titles.index(
            "Manager Cyber Compliance Deloitte"), \
            "a CLOSE target-title match must rank above a FAMILY one"

    def test_family_title_evidence_kept_same_career_specialization(self):
        # A FAMILY job whose TITLE carries the target's family vocabulary stays.
        ranked = _rank(_four_jobs() + [
            {"title": "Cyber Security Consultant", "company": "InfoSecCo",
             "url": "fam1", "location": "Remote",
             "tags": ["security"], "source": "T"},
        ])
        titles = [j["title"] for j in ranked]
        assert "Cyber Security Consultant" in titles, \
            "FAMILY with real family words in the title must survive the gate"

    def test_exact_target_title_ranks_first_regardless_of_location(self):
        ranked = _rank(_four_jobs() + [
            {"title": "ICT Security Manager", "company": "TargetExact",
             "url": "exact1", "location": "Dubai, UAE",
             "tags": ["ict security"], "source": "T"},
        ])
        titles = [j["title"] for j in ranked]
        assert titles[0] == "ICT Security Manager", \
            "an exact target-title match must lead the feed even when the " \
            "junk-free relevant rows are 'different'-location"

    def test_match_pct_of_irrelevant_jobs_must_not_inflate_above_relevant(self):
        ranked = _rank(_four_jobs())
        by_title = {j["title"]: j["match_pct"] for j in ranked}
        if "Head of Security Engineering" in by_title:
            head = by_title["Head of Security Engineering"]
            # Nothing absent from the feed can outscore the real match; and if
            # any of the junk rows were ever re-admitted, they must stay below.
            for bad in ("Junior Crypto Analyst & Trader",
                        "Work From Home Bilingual Client Services Representative"):
                assert bad not in by_title or by_title[bad] <= head, \
                    "a junk description-overlap job must never outscore an " \
                    "on-target title match"


class TestP11FeedAssemblyDominance:
    """recent_jobs: selection follows global dominance order, not location
    bucket order."""

    def _reset(self):
        jobs.clear_job_cache()

    def test_feed_selects_dominance_order_across_location_bands(self, monkeypatch):
        self._reset()
        raw = [
            {"title": "Junior Crypto Analyst & Trader", "company": "Tradedesk",
             "url": "fc1", "location": "Remote",
             "tags": ["crypto", "trading"], "source": "T"},
            {"title": "Head of Security Engineering", "company": "SecureCo",
             "url": "fc2", "location": "United States",
             "tags": ["security"], "source": "T"},
            {"title": "ICT Security Manager", "company": "CairoSec",
             "url": "fc3", "location": "Cairo, Egypt",
             "tags": ["ict security"], "source": "T"},
        ]
        monkeypatch.setattr(jobs, "_fetch_all", lambda *a, **k: raw)
        data = jobs.recent_jobs(
            skills=[("Security", "Advanced"), ("Network Security", "Intermediate")],
            role=_ROLE,
            country="Egypt",
            location="Cairo",
            role_requisites=_REQUISITES,
            limit=3,
            _sync=True,
        )
        titles = [j["title"] for j in data["jobs"]]
        # Local exact title first, then the on-target senior role in another
        # country — never the description-overlap crypto trader in between.
        assert titles[:2] == ["ICT Security Manager", "Head of Security Engineering"], titles
        assert "Junior Crypto Analyst & Trader" not in titles
        # The remote crypto trader was the only "broader"-band row and it is
        # gated out, so broader_count is honestly 0.
        assert data["groups"] == {"local_count": 1, "broader_count": 0, "other_count": 1}

    def test_feed_selection_preserves_local_remote_other_within_a_band(self, monkeypatch):
        """Within the same tier the legacy local -> global remote -> other order
        must be preserved (location is the third sort key)."""
        self._reset()
        raw = [
            {"title": "ICT Security Manager", "company": "LondonSec",
             "url": "fl1", "location": "London, United Kingdom",
             "tags": ["ict security"], "source": "T"},
            {"title": "ICT Security Manager", "company": "CairoSec",
             "url": "fl2", "location": "Cairo, Egypt",
             "tags": ["ict security"], "source": "T"},
            {"title": "ICT Security Manager", "company": "RemoteSec",
             "url": "fl3", "location": "Remote",
             "tags": ["ict security"], "source": "T"},
        ]
        monkeypatch.setattr(jobs, "_fetch_all", lambda *a, **k: raw)
        data = jobs.recent_jobs(
            skills=[("Security", "Advanced")],
            role=_ROLE,
            country="Egypt",
            location="Cairo",
            role_requisites=_REQUISITES,
            limit=3,
            _sync=True,
        )
        assert [j["company"] for j in data["jobs"]] == ["CairoSec", "RemoteSec", "LondonSec"]
        assert data["groups"] == {"local_count": 1, "broader_count": 1, "other_count": 1}