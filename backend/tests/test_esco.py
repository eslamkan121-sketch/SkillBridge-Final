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


_SKILLS = {
    "http://data.europa.eu/esco/occupation/occ-1": ["computer programming", "analyse software specifications", "debugging"],
    "http://data.europa.eu/esco/occupation/occ-2": ["query databases", "data analysis"],
}


def _fake_get_factory():
    calls = []

    def fake_get(url, **kwargs):
        calls.append(str(url))
        if "resource/occupation" in str(url):
            uri = (kwargs.get("params") or {}).get("uri")
            return _Resp({"_links": {"hasEssentialSkill": [{"title": s} for s in _SKILLS.get(uri, [])]}})
        return _Resp({
            "_embedded": {"results": [
                {"title": "software developer", "uri": "http://data.europa.eu/esco/occupation/occ-1"},
                {"title": "software tester", "uri": "http://data.europa.eu/esco/occupation/occ-2"},
            ]},
        })

    return fake_get, calls


def test_market_occupations_shape(monkeypatch):
    _reset_cache()
    fake_get, _ = _fake_get_factory()
    monkeypatch.setattr(escoe.httpx, "get", fake_get)
    out = escoe.market_occupations("software", limit=2)
    assert len(out) == 2
    assert out[0]["title"] == "software developer"
    assert out[0]["skills"] == ["computer programming", "analyse software specifications", "debugging"]
    assert out[0]["skill_count"] == 3


def test_market_occupations_cached_per_query(monkeypatch):
    _reset_cache()
    fake_get, calls = _fake_get_factory()
    monkeypatch.setattr(escoe.httpx, "get", fake_get)
    escoe.market_occupations("software", limit=2)
    escoe.market_occupations("software", limit=2)
    assert len([c for c in calls if "resource/occupation" in c]) == 2


def test_market_occupations_empty_text_and_failure(monkeypatch):
    _reset_cache()
    assert escoe.market_occupations("  ") == []

    def fail_get(*args, **kwargs):
        raise RuntimeError("esco down")

    monkeypatch.setattr(escoe.httpx, "get", fail_get)
    assert escoe.market_occupations("software") == []


def test_esco_market_endpoint(client, auth_headers, monkeypatch):
    from app import main
    monkeypatch.setattr(
        main.escoe, "market_occupations",
        lambda text, limit=10: [{"title": "data scientist", "uri": "x", "skills": ["statistics"], "skill_count": 1}])
    headers = auth_headers("aisha@student.edu")
    r = client.get("/api/roles/esco-market", params={"q": "data scientist", "limit": 5}, headers=headers)
    assert r.status_code == 200
    payload = r.json()
    assert payload["source"] == "ESCO"
    assert payload["occupations"][0]["title"] == "data scientist"
    assert payload["occupations"][0]["skills"] == ["statistics"]


def test_esco_market_endpoint_requires_auth(client):
    r = client.get("/api/roles/esco-market", params={"q": "data"})
    assert r.status_code == 401


def test_enrich_pool_runs_concurrently(monkeypatch):
    """Bounded parallel enrichment must collapse the worst-case sequential
    latency: 20 candidates over a 6-worker pool complete in well under the
    ~160s a serial loop could hit on degraded network, and every candidate is
    still enriched exactly once."""
    import time
    pool = [{"uri": f"occ-{i}"} for i in range(20)]

    def slow_enrich(entry):
        time.sleep(0.05)
        entry["_essential"] = ["skill"] * 3
        entry["skills"] = ["skill"]

    monkeypatch.setattr(escoe, "_enrich", slow_enrich)
    start = time.monotonic()
    escoe._enrich_pool(pool)
    elapsed = time.monotonic() - start
    # 20 * 0.05s = 1.0s serial; with 6 workers it must finish far sooner.
    assert elapsed < 0.6, f"enrich pool took {elapsed:.2f}s, expected sub-second"
    assert all(e.get("skills") == ["skill"] for e in pool)


def test_esco_market_endpoint_degrades_to_honest_unavailable(client, auth_headers, monkeypatch):
    """A live-API failure must never surface to the browser as a dropped
    request ("Failed to fetch"): the endpoint returns 200 with an honest
    unavailable status instead of raising a 500."""
    from app import main

    def boom(text, limit=10):
        raise RuntimeError("esco down")

    monkeypatch.setattr(main.escoe, "market_occupations", boom)
    headers = auth_headers("aisha@student.edu")
    r = client.get("/api/roles/esco-market", params={"q": "lawyer", "limit": 5}, headers=headers)
    assert r.status_code == 200
    payload = r.json()
    assert payload["source"] == "ESCO"
    assert payload["occupations"] == []
    assert payload["status"] == "unavailable"
    assert payload["message"]