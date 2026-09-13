from datetime import date, timedelta

import pytest

from app import jobs


def _reset_jobs_cache():
    jobs.clear_job_cache()


def _iso(days_ago):
    return (date.today() - timedelta(days=days_ago)).isoformat()


def test_parse_listing_date_supports_iso_epoch_and_datetime():
    assert jobs._parse_listing_date("2026-08-20") == date(2026, 8, 20)
    assert jobs._parse_listing_date("2026-08-20T09:30:00Z") == date(2026, 8, 20)
    assert jobs._parse_listing_date("2026-08-20 12:00:00") == date(2026, 8, 20)
    assert jobs._parse_listing_date(1700000000) == date(2023, 11, 14)
    assert jobs._parse_listing_date(1700000000.5) == date(2023, 11, 14)
    assert jobs._parse_listing_date("1700000000") == date(2023, 11, 14)
    assert jobs._parse_listing_date("") is None
    assert jobs._parse_listing_date(None) is None
    assert jobs._parse_listing_date("not-a-date") is None


def test_jsearch_expired_flag_marks_listing_expired():
    raw = [{
        "title": "Security Analyst", "company": "Aggregator",
        "url": "https://bebee.example/job/1", "date": _iso(2),
        "source": "JSearch", "expired": True,
    }]
    merged = jobs._merge(raw)
    assert len(merged) == 1
    assert merged[0]["is_expired"] is True
    assert merged[0]["expires_at"] is None


def test_arbeitnow_unavailable_marks_listing_expired():
    raw = [
        {
            "title": "DevOps Engineer", "company": "ATS Corp",
            "url": "https://arbeitnow.example/1", "date": _iso(1),
            "source": "Arbeitnow", "available": False,
        },
        {
            "title": "Junior Python Dev", "company": "ATS Corp",
            "url": "https://arbeitnow.example/2", "date": _iso(1),
            "source": "Arbeitnow", "available": True,
        },
        {
            "title": "SRE", "company": "ATS Corp",
            "url": "https://arbeitnow.example/3", "date": _iso(1),
            "source": "Arbeitnow",
        },
    ]
    merged = jobs._merge(raw)
    by_title = {m["title"]: m for m in merged}
    assert by_title["DevOps Engineer"]["is_expired"] is True
    assert by_title["Junior Python Dev"]["is_expired"] is False
    assert by_title["SRE"]["is_expired"] is False


def test_usajobs_close_date_governs_expiry():
    raw = [
        {
            "title": "IT Specialist", "company": "US Gov",
            "url": "https://usajobs.example/1",
            "date": _iso(40), "close_date": _iso(7),
            "source": "USAJobs",
        },
        {
            "title": "Sys Admin", "company": "US Gov",
            "url": "https://usajobs.example/2",
            "date": _iso(40), "close_date": _iso(-7),
            "source": "USAJobs",
        },
    ]
    merged = jobs._merge(raw)
    by_title = {m["title"]: m for m in merged}
    assert by_title["IT Specialist"]["is_expired"] is True
    assert by_title["IT Specialist"]["expires_at"] == _iso(7)
    assert by_title["Sys Admin"]["is_expired"] is False
    assert by_title["Sys Admin"]["expires_at"] == _iso(-7)


def test_large_listing_age_triggers_staleness_heuristic():
    raw_past = {
        "title": "Data Analyst", "company": "Old Board",
        "url": "https://board.example/old",
        "date": _iso(35), "source": "Adzuna",
    }
    raw_fresh = {
        "title": "Data Analyst II", "company": "Old Board",
        "url": "https://board.example/fresh",
        "date": _iso(10), "source": "Adzuna",
    }
    merged = jobs._merge([raw_past, raw_fresh])
    by_title = {m["title"]: m for m in merged}
    assert by_title["Data Analyst"]["is_expired"] is True
    assert by_title["Data Analyst II"]["is_expired"] is False
    assert by_title["Data Analyst II"]["listed_days_ago"] == 10


def test_remoteok_expires_field_is_respected():
    raw = [
        {
            "title": "Fullstack Dev", "company": "Remote Co",
            "url": "https://remoteok.example/1", "date": _iso(5),
            "expires": 1700000000, "source": "RemoteOK",
        },
        {
            "title": "Frontend Dev", "company": "Remote Co",
            "url": "https://remoteok.example/2", "date": _iso(5),
            "expires": 4925000000, "source": "RemoteOK",
        },
    ]
    merged = jobs._merge(raw)
    by_title = {m["title"]: m for m in merged}
    assert by_title["Fullstack Dev"]["is_expired"] is True
    assert by_title["Frontend Dev"]["is_expired"] is False
    assert by_title["Frontend Dev"]["expires_at"] == jobs._parse_listing_date(4925000000).isoformat()


def test_build_result_drops_expired_jobs(monkeypatch):
    _reset_jobs_cache()
    raw = [
        {
            "title": "Security Analyst", "company": "Recent Co",
            "url": "https://example.test/live", "location": "Remote",
            "tags": ["Security", "Linux"], "source": "Test",
            "date": _iso(3),
        },
        {
            "title": "Security Analyst (Stale)", "company": "Old Board",
            "url": "https://bebee.example/expired", "location": "Remote",
            "tags": ["Security", "Linux"], "source": "JSearch",
            "date": _iso(3), "expired": True,
        },
    ]
    monkeypatch.setattr(jobs, "_fetch_all", lambda *a, **k: raw)
    data = jobs.recent_jobs(
        skills=[("Linux", "Intermediate")],
        role="Security Analyst", country="United States", limit=5, _sync=True,
    )
    assert data["source"] == "live"
    titles = [j["title"] for j in data["jobs"]]
    assert "Security Analyst (Stale)" not in titles
    assert "Security Analyst" in titles
    assert all(not j.get("is_expired") for j in data["jobs"])


def test_all_expired_gives_honest_unavailable(monkeypatch):
    _reset_jobs_cache()
    raw = [{
        "title": "Junior Data Analyst", "company": "Dead Board",
        "url": "https://board.example/gone", "location": "Cairo, Egypt",
        "tags": ["SQL"], "source": "Test", "date": _iso(90),
    }]
    monkeypatch.setattr(jobs, "_fetch_all", lambda *a, **k: raw)
    data = jobs.recent_jobs(
        skills=[("SQL", "Intermediate")], role="Junior Data Analyst",
        country="Egypt", limit=5, _sync=True,
    )
    # Every fetched listing was expired/stale and no provider reported success —
    # the feed is honestly ``unavailable`` with zero jobs, never a curated list.
    assert data["source"] == "unavailable"
    assert data["jobs"] == []