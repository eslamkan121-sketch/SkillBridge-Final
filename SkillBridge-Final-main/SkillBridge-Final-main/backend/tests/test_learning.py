"""Phase 4 — Learning path generation returns structured, non-empty content."""
import json

from app import career_roadmap, genai, models, matching


def test_learning_item_generation_shape():
    item = genai.generate_learning_item("Docker", "DevOps", "Junior AI Engineer",
                                        "Studying at Aston University")
    assert set(item.keys()) == {"explanation", "practice_exercise", "mini_project",
                                "resources", "roadmap", "modules", "blueprint_version",
                                "blueprint_competencies", "coverage_check"}
    assert all(isinstance(v, str) and v.strip() for v in
               [item["explanation"], item["practice_exercise"], item["mini_project"]])
    # contextualized to the role
    assert "Junior AI Engineer" in item["explanation"]
    # resources are real links, ranked
    assert isinstance(item["resources"], list) and item["resources"]
    for r in item["resources"]:
        assert r["url"].startswith("http") and r["title"]
        assert not genai._is_generic_resource_url(r["url"]), f"generic resource in item: {r['url']}"
    # roadmap is a structured sequence
    assert isinstance(item["roadmap"], dict)
    assert item["roadmap"]["summary"] and len(item["roadmap"]["steps"]) >= 3
    for s in item["roadmap"]["steps"]:
        assert s["objective"] and s["practice"]
        # each step carries real, titled source links (not bare rank numbers)
        assert isinstance(s.get("resources"), list) and s["resources"]
        item_urls = {r["url"] for r in item["resources"]}
        for r in s["resources"]:
            assert r["url"].startswith("http") and r["title"]
            assert r["url"] in item_urls  # step sources come from the ranked list
            assert not genai._is_generic_resource_url(r["url"]), f"step cites generic {r['url']}"
        assert s["resource_ranks"] and len(s["resource_ranks"]) == len(s["resources"])
    assert item["roadmap"]["resource_version"] == genai.RESOURCE_VERSION
    # blueprint modules are genuine, sufficient, and version-stamped
    assert isinstance(item["modules"], list) and item["modules"]
    assert isinstance(item["blueprint_version"], str) and item["blueprint_version"]
    assert isinstance(item["blueprint_competencies"], list)
    assert item["coverage_check"]["covered"] is True
    for m in item["modules"]:
        assert m.get("competency") and m.get("title") and m.get("objective")
        assert isinstance(m.get("estimated_minutes"), int) and m["estimated_minutes"] >= 20


def test_roadmap_steps_source_from_spread_resources():
    """Steps draw from the ranked pool only, every cited link is direct and
    on-topic (never a search page / channel / category index), and consecutive
    steps prefer distinct sources where the pool allows it."""
    item = genai.generate_learning_item("SQL", "Data", "Data Analyst",
                                        "Studying at Aston University")
    per_step = {tuple(r["url"] for r in s["resources"]) for s in item["roadmap"]["steps"]}
    urls = [r["url"] for s in item["roadmap"]["steps"] for r in s["resources"]]
    item_urls = {r["url"] for r in item["resources"]}
    # every step cites real, titled, direct resources drawn from the ranked list
    assert urls, "no step cited any resource"
    assert all(r["title"] for s in item["roadmap"]["steps"] for r in s["resources"])
    for r_url in urls:
        assert r_url in item_urls, f"step cites unranked resource {r_url}"
        assert not genai._is_generic_resource_url(r_url), f"step cites generic {r_url}"
    # as resources allow, neighbouring steps never show the identical list
    for a, b in zip(item["roadmap"]["steps"], item["roadmap"]["steps"][1:]):
        a_set = {r["url"] for r in a["resources"]}
        b_set = {r["url"] for r in b["resources"]}
        assert a_set != b_set, f"consecutive steps identical: {a['title']} | {b['title']}"


def test_ai_resources_are_validated_and_curated_padding_added(monkeypatch):
    """AI-invented links that provably 404 must be dropped; unverifiable ones
    kept; genuine curated links appended (deduped) so roadmap ranks resolve."""
    from app import resources as resources_mod
    ai = [
        {"title": "Live link", "url": "https://example.com/live", "type": "article"},
        {"title": "Dead link", "url": "https://example.com/dead", "type": "article"},
        {"title": "Unknown link", "url": "https://example.com/unknown", "type": "video"},
    ]
    curated = [
        {"title": "Curated One", "url": "https://curated.example/1", "type": "doc"},
        {"title": "Live link dup", "url": "https://example.com/live", "type": "article"},
        {"title": "Curated Two", "url": "https://curated.example/2", "type": "course"},
    ]
    avail = {
        "https://example.com/live": True,
        "https://example.com/dead": False,
        "https://example.com/unknown": None,
    }

    def fake_annotate(res):
        return [dict(r, available=avail.get(r["url"])) for r in res]

    monkeypatch.setattr(resources_mod, "annotate_resources", fake_annotate)
    merged = genai._merge_ai_and_curated_resources(ai, curated)
    urls = [r["url"] for r in merged]
    # dead dropped; live+unknown keep AI head order; curated appended; no dup URL
    assert urls == ["https://example.com/live", "https://example.com/unknown",
                    "https://curated.example/1", "https://curated.example/2"]
    assert all("available" not in r for r in merged)
    assert all(set(r) == {"title", "url", "type"} for r in merged[:2])


def test_ai_resources_all_dead_fall_back_to_curated(monkeypatch):
    from app import resources as resources_mod
    ai = [{"title": "Ghost", "url": "https://example.com/ghost", "type": "article"}]
    curated = [{"title": "Curated", "url": "https://curated.example/1", "type": "doc"}]
    monkeypatch.setattr(
        resources_mod, "annotate_resources",
        lambda res: [dict(r, available=False) for r in res])
    merged = genai._merge_ai_and_curated_resources(ai, curated)
    assert [r["url"] for r in merged] == ["https://curated.example/1"]


def test_ai_cybrary_resources_are_replaced_with_tryhackme(monkeypatch):
    """Cybrary links suggested by the model must never survive; they are
    rewritten to a real TryHackMe link for security skills."""
    from app import resources as resources_mod
    ai = [
        {"title": "Cybrary: Active Directory Security",
         "url": "https://www.cybrary.it/course/active-directory-security/",
         "type": "course"},
        {"title": "Live official doc", "url": "https://learn.microsoft.com/en-us/windows-server/identity/", "type": "doc"},
    ]
    curated = [
        {"title": "TryHackMe — Active Directory room", "url": "https://tryhackme.com/room/activedirectorybasics", "type": "doc"},
    ]
    monkeypatch.setattr(
        resources_mod, "annotate_resources",
        lambda res: [dict(r, available=True) for r in res])
    merged = genai._merge_ai_and_curated_resources(ai, curated, skill_name="Active Directory")
    urls = [r["url"] for r in merged]
    assert not any("cybrary" in u.lower() for u in urls)
    assert "https://tryhackme.com/room/activedirectorybasics" in urls
    assert "https://learn.microsoft.com/en-us/windows-server/identity/" in urls
    # the replacement keeps a genuine hands-on link without grossly expanding the list
    assert len(urls) <= 3


def test_generate_learning_item_resources_never_contain_cybrary(monkeypatch):
    """End-to-end: generated learning items' resources/roadmap never contain
    Cybrary even when the model returns one."""
    from app import resources as resources_mod

    ai_item = {
        "explanation": "explanation text",
        "practice_exercise": "practice text",
        "mini_project": "project text",
        "resources": [
            {"title": "Cybrary course", "url": "https://www.cybrary.it/course/x/", "type": "course"},
        ],
        "roadmap": {
            "summary": "summary",
            "steps": [
                {"step": 1, "title": "Learn fundamentals", "objective": "obj",
                 "practice": "prac", "checkpoint": "check", "resource_ranks": [1]},
            ],
        },
    }

    def fake_complete(system, user, fallback=None, max_tokens=None, timeout=None):
        import json as _json
        return _json.dumps(ai_item)

    def fake_annotate(res):
        return [dict(r, available=True) for r in res]

    def fake_retrieve_resources(*a, **kw):
        return [
            {"title": "TryHackMe — Active Directory room", "url": "https://tryhackme.com/room/activedirectorybasics", "type": "doc"},
            {"title": "Microsoft Learn", "url": "https://learn.microsoft.com/en-us/windows-server/", "type": "doc"},
        ]

    monkeypatch.setattr(genai, "complete", fake_complete)
    monkeypatch.setattr(resources_mod, "annotate_resources", fake_annotate)
    monkeypatch.setattr(resources_mod, "retrieve_resources", fake_retrieve_resources)
    item = genai.generate_learning_item("Active Directory", "Security", "Cybersecurity Analyst")
    blob = str(item)
    assert "ybrary" not in blob.lower()
    assert "tryhackme.com" in blob.lower()


def test_learning_route_persists_item(client, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    student = models.get_student(student_id)
    gap = matching.gap_skills(student, student["target_role"])[0]
    r = client.post(f"/api/students/{student_id}/learning/generate",
                    json={"skill_id": gap["skill_id"]}, headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["skill_id"] == gap["skill_id"]
    assert all([data["explanation"], data["practice_exercise"], data["mini_project"]])
    assert len(data.get("resources") or []) > 0
    assert isinstance(data.get("roadmap") or {}, dict)
    # persisted
    items = models.list_learning_path(student_id)
    assert any(i["skill_id"] == gap["skill_id"] for i in items)


def test_tutor_reply_is_personalized():
    reply = genai.tutor_reply(
        "How should I approach Docker?",
        "Studying at Aston University; current profile: Python (Advanced), SQL (Advanced)",
        "Docker",
        "Junior AI Engineer",
    )
    assert isinstance(reply, str) and reply.strip()
    assert len(reply) > 40


def test_tutor_route_round_trip(client, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    r = client.post(f"/api/students/{student_id}/tutor",
                    json={"message": "Help me with Docker"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["role"] == "assistant"
    assert r.json()["content"].strip()
    history = client.get(f"/api/students/{student_id}/tutor", headers=headers).json()
    assert len(history) == 2  # user + assistant


def test_roadmap_steps_always_renumbered_sequentially():
    """A 6-step path whose AI steps are 4..9 must come out numbered 1..6, and
    every step must resolve real titled sources from its ranks."""
    resources = [{"title": f"R{i}", "url": f"https://example.com/{i}", "type": "doc"}
                 for i in range(1, 4)]
    roadmap = {"summary": "custom", "steps": [
        {"step": 4, "title": "A", "objective": "o", "practice": "p", "checkpoint": "c", "resource_ranks": [1]},
        {"step": 6, "title": "B", "objective": "o", "practice": "p", "checkpoint": "c", "resource_ranks": [2]},
        {"step": 8, "title": "C", "objective": "o", "practice": "p", "checkpoint": "c", "resource_ranks": [3]},
        {"step": 9, "title": "D", "objective": "o", "practice": "p", "checkpoint": "c", "resource_ranks": [1]},
    ]}
    default = {"roadmap": {"summary": "d", "steps": []}}
    norm = genai._normalize_roadmap(roadmap, resources, default)
    assert [s["step"] for s in norm["steps"]] == [1, 2, 3, 4]
    assert [s["title"] for s in norm["steps"]] == ["A", "B", "C", "D"]
    for s in norm["steps"]:
        assert s["resources"]
        assert len(s["resource_ranks"]) == len(s["resources"])
        assert all(r["url"] in {x["url"] for x in resources} for r in s["resources"])


def test_ai_generic_index_links_demoted_below_topical(monkeypatch):
    """Channel homepages and bare site roots in AI output are demoted BELOW the
    curated/topical links, so resource ranks and steps cite specific content."""
    from app import resources as resources_mod
    ai = [
        {"title": "Specific video", "url": "https://www.youtube.com/watch?v=abc123", "type": "video"},
        {"title": "Channel homepage", "url": "https://www.youtube.com/@somechannel", "type": "video"},
        {"title": "Bare root", "url": "https://example.com/", "type": "doc"},
    ]
    curated = [{"title": "Curated One", "url": "https://curated.example/1", "type": "doc"}]
    monkeypatch.setattr(resources_mod, "annotate_resources",
                        lambda res: [dict(r, available=True) for r in res])
    merged = genai._merge_ai_and_curated_resources(ai, curated, skill_name="X")
    urls = [r["url"] for r in merged]
    # topical AI first, then curated, then demoted generic index links
    assert urls.index("https://www.youtube.com/watch?v=abc123") < \
        urls.index("https://curated.example/1")
    assert urls.index("https://curated.example/1") < \
        urls.index("https://www.youtube.com/@somechannel")
    assert "https://example.com/" in urls  # kept, just demoted


def test_learning_item_renumbers_steps_and_never_cites_channel(monkeypatch):
    """End-to-end: steps are renumbered 1..N and NO channel homepage survives
    anywhere (not in step resources, not in the item's top-level list), even
    when the model supplies bogus step numbers and a channel."""
    from app import resources as resources_mod
    ai_item = {
        "explanation": "e", "practice_exercise": "p", "mini_project": "m",
        "resources": [
            {"title": "Official docs", "url": "https://learn.microsoft.com/en-us/windows-server/security/", "type": "doc"},
            {"title": "Channel home", "url": "https://www.youtube.com/@microsoftsecurity", "type": "video"},
        ],
        "roadmap": {"summary": "s", "steps": [
            {"step": 4, "title": "S1", "objective": "o", "practice": "p", "checkpoint": "c", "resource_ranks": [1]},
            {"step": 6, "title": "S2", "objective": "o", "practice": "p", "checkpoint": "c", "resource_ranks": [1]},
            {"step": 9, "title": "S3", "objective": "o", "practice": "p", "checkpoint": "c", "resource_ranks": [1]},
        ]},
    }
    monkeypatch.setattr(genai, "complete", lambda *a, **k: json.dumps(ai_item))
    monkeypatch.setattr(resources_mod, "annotate_resources",
                        lambda res: [dict(r, available=True) for r in res])
    monkeypatch.setattr(resources_mod, "retrieve_resources",
                        lambda *a, **k: [{"title": "Curated", "url": "https://curated.example/1", "type": "doc"}])
    item = genai.generate_learning_item("Windows Server", "Security", "Cybersecurity Analyst")
    steps = item["roadmap"]["steps"]
    assert [s["step"] for s in steps] == [1, 2, 3]
    step_urls = [r["url"] for s in steps for r in s["resources"]]
    assert step_urls, "no step cited a resource"
    # the channel is gone from the whole item — steps and top-level list alike
    blob = json.dumps(item)
    assert "@microsoftsecurity" not in blob
    assert "youtube.com/@microsoftsecurity".lower() not in blob.lower()
    # every step cites only direct, on-topic sources from the retained pool
    for s in steps:
        assert s["resources"]
        assert all(not genai._is_generic_resource_url(r["url"]) for r in s["resources"])
        assert all(r["url"] in {x["url"] for x in item["resources"]} for r in s["resources"])


def test_generic_fallback_is_skill_scoped():
    """Unknown skills get an honest, skill-scoped 'resource unavailable' marker
    — never a fabricated URL, never a search/category deep-link for the bare
    skill name, never a bare channel/index homepage."""
    from app import resources as resources_mod
    out = resources_mod.curated_resources("Quantum Knitting", "Other")
    assert out, "expected the fallback marker"
    for r in out:
        assert r["unavailable"] is True
        assert not r["url"], f"no fake link expected: {r['url']!r}"
        assert r["title"] and "Quantum Knitting" in r["title"]
        assert r.get("status") == "Unavailable"
        assert "Quantum Knitting" in r.get("reason", "")
        assert resources_mod.is_generic_resource_url(r["url"])  # marker: never a direct link


def test_career_roadmap_phases_have_on_topic_resources():
    """Every career-roadmap phase carries real, topic-bearing resources for any
    target career — never a bare platform homepage, never an empty list."""
    def student():
        return {"self_reported_skills": [], "verified_skills": []}

    def role(title, required):
        return {"title": title, "required_skills": [
            {"skill_id": i + 1, "name": n, "category": c, "level": "Beginner"}
            for i, (n, c) in enumerate(required)]}

    roles = [
        role("Cybersecurity Analyst", [
            ("Windows Server Administration", "Security"),
            ("Vulnerability Assessment", "Security"),
            ("Network Security", "Security"),
            ("Active Directory", "Security"),
            ("SIEM", "Security"),
            ("Linux", "Programming"),
        ]),
        role("Data Analyst", [
            ("SQL", "Data"), ("Data Analysis", "Analytics"),
            ("Excel", "Data"), ("Python", "Programming"),
            ("Tableau", "Visualization"),
        ]),
        role("Junior AI Engineer", [
            ("Python", "Programming"), ("Machine Learning", "AI"),
            ("Deep Learning", "AI"), ("Docker", "DevOps"), ("SQL", "Data"),
        ]),
    ]
    for r in roles:
        roadmap = career_roadmap.build_career_roadmap(student(), r)
        assert roadmap["resources_version"] >= 2
        assert len(roadmap["phases"]) == 11
        for ph in roadmap["phases"]:
            assert ph["resources"], f"{r['title']}: {ph['title']} has no resources"
            for res in ph["resources"]:
                assert res["url"].startswith("http") and res["title"]
                assert not genai._is_generic_resource_url(res["url"]), res["url"]


def test_career_roadmap_every_phase_has_real_deliverables():
    """No phase may lean on the old "choose a target role" placeholder — every
    phase must carry concrete, actionable deliverables for the student's role."""
    student = {"self_reported_skills": [], "verified_skills": []}

    def role(title, required):
        return {"title": title, "required_skills": [
            {"skill_id": i + 1, "name": n, "category": c, "level": "Beginner"}
            for i, (n, c) in enumerate(required)]}

    roles = [
        role("Cybersecurity Analyst", [
            ("Active Directory", "Security"), ("SIEM", "Security"),
            ("Network Security", "Security"), ("Incident Response", "Security"),
            ("Linux", "Programming"),
        ]),
        role("Data Analyst", [
            ("SQL", "Data"), ("Data Analysis", "Analytics"),
            ("Tableau", "Visualization"), ("Python", "Programming"),
        ]),
        role("Junior AI Engineer", [
            ("Python", "Programming"), ("Machine Learning", "AI"),
            ("Docker", "DevOps"), ("SQL", "Data"),
        ]),
    ]
    for r in roles:
        roadmap = career_roadmap.build_career_roadmap(student, r)
        for ph in roadmap["phases"]:
            assert ph["deliverables"], f"{r['title']} phase {ph['phase']} empty deliverables"
            for d in ph["deliverables"]:
                assert "Choose a target role" not in d, (
                    f"{r['title']} phase {ph['phase']} '{ph['title']}' still uses placeholder")


def test_non_software_career_roadmap_stays_domain_specific():
    """A non-CS target role must not inherit software-roadmap copy in the
    browser-visible master career journey."""
    student = {"self_reported_skills": [], "verified_skills": []}
    role = {"title": "Graphic Designer", "required_skills": [
        {"skill_id": 1, "name": "Adobe Photoshop", "category": "Design", "level": "Advanced"},
        {"skill_id": 2, "name": "Illustrator", "category": "Design", "level": "Advanced"},
        {"skill_id": 3, "name": "Typography", "category": "Design", "level": "Intermediate"},
        {"skill_id": 4, "name": "Brand Identity", "category": "Design", "level": "Intermediate"},
        {"skill_id": 5, "name": "Color Theory", "category": "Design", "level": "Intermediate"},
    ]}

    roadmap = career_roadmap.build_career_roadmap(student, role)
    visible_text = " ".join(
        " ".join([
            ph["title"],
            ph["goal"],
            ph["checkpoint"],
            " ".join(ph["deliverables"]),
        ])
        for ph in roadmap["phases"]
    ).lower()

    banned = (
        "programming", "writing and reading code", "code review",
        "dev environment", "git repository", "containerise",
        "technical interview",
    )
    assert not any(term in visible_text for term in banned), visible_text
    assert any(ph["skills"] for ph in roadmap["phases"][:6])
    assert any(
        s["name"] == "Typography"
        for ph in roadmap["phases"]
        for s in ph["skills"]
    )


def test_career_roadmap_skills_distributed_across_phases():
    """A role whose skills all live in one category (e.g. Security) must still
    spread its skills across the technical phases rather than stacking all of
    them into a single phase."""
    student = {"self_reported_skills": [], "verified_skills": []}
    role = {"title": "Cybersecurity Analyst", "required_skills": [
        {"skill_id": i + 1, "name": n, "category": "Security", "level": "Beginner"}
        for i, n in enumerate(["Active Directory", "SIEM", "Network Security",
                               "Incident Response", "Vulnerability Assessment",
                               "Threat Detection", "Risk Assessment", "Windows Server"])
    ]}
    roadmap = career_roadmap.build_career_roadmap(student, role)
    technical = [ph for ph in roadmap["phases"] if ph["phase"] <= 5]
    phases_with_skills = [ph for ph in technical if ph["skills"]]
    assert len(phases_with_skills) >= 3, (
        "skills all stacked in one phase: "
        + ", ".join(f"#{ph['phase']}={len(ph['skills'])}" for ph in technical))


def test_generic_url_detector_contract():
    """The directness detector must ban every portal/navigation shape that made
    learning steps useless and pass every genuinely topical shape."""
    from app import resources as resources_mod
    banned = [
        "https://www.youtube.com/c/MicrosoftLearn",
        "https://www.youtube.com/@freecodecamp",
        "https://www.youtube.com/channel/UCXManufacturer",
        "https://www.youtube.com/results?search_query=docker+tutorial",
        "https://duckduckgo.com/?q=docker+documentation",
        "https://www.coursera.org/search?query=sql",
        "https://tryhackme.com/paths",
        "https://udemy.com/courses/development/",
        "https://github.com/topics/docker",
    ]
    allowed = [
        "https://www.youtube.com/watch?v=pTFZFxd4hOI",
        "https://tryhackme.com/room/introtocyber",
        "https://docs.docker.com/get-started/",
        "https://learn.microsoft.com/en-us/training/",
        "https://pandas.pydata.org/docs/user_guide/indexing.html",
        "https://pages.github.com/",
        "https://linuxjourney.com/",
        "https://www.postgresqltutorial.com/",
        "https://www.coursera.org/learn/sql-for-data-science",
        "https://www.udemy.com/course/docker-mastery/",
        "https://support.microsoft.com/en-us/excel",
    ]
    for u in banned:
        assert resources_mod.is_generic_resource_url(u), f"should be generic: {u}"
    for u in allowed:
        assert not resources_mod.is_generic_resource_url(u), f"should be direct: {u}"


def test_stored_learning_item_refreshes_to_direct_resources():
    """Legacy stored items citing channel homepages / platform category indexes
    are deterministically re-attached to direct, on-topic resources on read."""
    legacy = {
        "student_id": 1, "skill_id": 3, "skill_name": "Active Directory",
        "category": "Security", "explanation": "e", "practice_exercise": "p",
        "mini_project": "m",
        "resources": [
            {"title": "Channel", "url": "https://www.youtube.com/c/MicrosoftLearn", "type": "video"},
        ],
        "roadmap": {"summary": "s", "resource_version": 1, "steps": [
            {"step": 1, "title": "Foundations", "objective": "Understand core AD concepts",
             "practice": "Summarise the sources", "checkpoint": "Explain the domain",
             "resource_ranks": [1], "resources": [
                 {"title": "Channel", "url": "https://www.youtube.com/c/MicrosoftLearn", "type": "video"}]},
        ]},
    }
    refreshed = genai.refresh_learning_item_resources(legacy, "Cybersecurity Analyst")
    assert refreshed is not None
    assert refreshed["roadmap"]["resource_version"] == genai.RESOURCE_VERSION
    blob = json.dumps(refreshed).lower()
    assert "youtube.com/c/microsoftlearn" not in blob and "tryhackme.com/paths" not in blob
    step = refreshed["roadmap"]["steps"][0]
    assert not step.get("resource_unavailable"), "curated skill must yield real resources"
    assert step["resources"]
    for rr in step["resources"]:
        assert not genai._is_generic_resource_url(rr["url"]), rr["url"]
        assert rr["url"] in {x["url"] for x in refreshed["resources"]}
    # unknown skills refresh to an honest, link-free state — never fabricated links
    unknown = genai.refresh_learning_item_resources({
        "skill_name": "Quantum Knitting", "category": "Other", "resources": [],
        "roadmap": {"summary": "s", "resource_version": 1, "steps": [
            {"step": 1, "title": "T", "objective": "o", "practice": "p", "checkpoint": "c",
             "resource_ranks": [], "resources": []}]},
    }, "")
    assert unknown is not None
    assert unknown["resources"] == []
    assert all(s.get("resource_unavailable") and not s["resources"]
               for s in unknown["roadmap"]["steps"])
    # already-current items are a no-op
    current = dict(legacy)
    current["roadmap"]["resource_version"] = genai.RESOURCE_VERSION
    assert genai.refresh_learning_item_resources(current, "") is None


def test_skill_roadmap_steps_spread_distinct_on_topic_resources():
    """Per-skill roadmap steps must not collapse to 1-2 rotating generic handles:
    across steps, cite distinct topic-specific direct resources, all from the
    ranked item list, verified against several skills (addendum regression)."""
    cases = [
        ("Active Directory", "Security", "Cybersecurity Analyst"),
        ("SQL", "Data", "Data Analyst"),
        ("Docker", "DevOps", "Junior AI Engineer"),
    ]
    for skill, cat, role in cases:
        item = genai.generate_learning_item(skill, cat, role)
        steps = item["roadmap"]["steps"]
        assert len(steps) >= 3
        step_urls = [r["url"] for s in steps for r in s["resources"]]
        distinct = len(set(step_urls))
        # together the steps use more than a single resource, and every cited
        # link is a direct, on-topic resource from the ranked item list
        assert distinct >= 2, f"{skill}: all steps point at the same resource"
        item_urls = {r["url"] for r in item["resources"]}
        for r_url in step_urls:
            assert r_url in item_urls, f"{skill}: step cites unranked resource {r_url}"
            assert not genai._is_generic_resource_url(r_url), f"{skill}: step cites generic {r_url}"
