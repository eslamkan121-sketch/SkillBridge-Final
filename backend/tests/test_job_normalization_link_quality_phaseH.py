"""Phase H — Job normalization, deduplication, and link quality.

Covers the additive normalized record shape (`normalise_listing`): provider/
provider_job_id/fingerprint, original_* fields, work_type/seniority,
description_excerpt, apply_url/published/fetched timestamps, listing_status,
link_state/link_reason and the `observed_*` conflict-preserving lists plus
provenance. Dedup priority is conservative: (provider, provider_job_id), then
canonical apply URL, then title+company+location identity — two uncertain
vacancies never merge on title alone. Link quality is offline-only: explicit
unsafe schemes and private/internal hosts are rejected, scheme-less values stay
honest `unverified`, verified-dead URLs are kept as link-unavailable records
(never silently deleted) and excluded from the surfaced feed, and no network
probe ever runs.

Every provider is mocked; no network and no real quota is ever spent.
"""
import time

import pytest

from app import jobs


@pytest.fixture(autouse=True)
def _fresh_jobs_state():
    jobs.clear_job_cache()
    jobs._PROVIDER_COOLDOWN.clear()
    for p in jobs.PROVIDERS:
        jobs._provider_status[p] = {"status": "skipped", "count": 0, "reason": "", "error": ""}
    jobs._stats.update({
        "cache_hits": 0, "cache_misses": 0,
        "last_success_provider": "", "last_error_by_provider": {},
        "fetch_times": [],
    })
    yield
    jobs.clear_job_cache()


def _listing(**overrides):
    base = {
        "title": "Junior Data Analyst", "company": "Acme Analytics",
        "url": "https://example.test/jobs/1", "location": "Cairo, Egypt",
        "tags": ["SQL", "Excel"], "source": "Remotive",
        "date": "2026-09-01", "description": "Analyse business data with SQL and Excel.",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------- normalization

def test_normalised_record_carries_required_additive_fields():
    item = jobs.normalise_listing(_listing())
    assert item["provider"] == "Remotive"
    assert item["provider_job_id"] is None
    assert isinstance(item["fingerprint"], str) and len(item["fingerprint"]) == 16
    assert item["apply_url"] == "https://example.test/jobs/1"
    assert item["original_title"] == "Junior Data Analyst"
    assert item["original_company"] == "Acme Analytics"
    assert item["original_location"] == "Cairo, Egypt"
    assert item["description_excerpt"] == item["description"]
    assert "fetched_at" in item and item["fetched_at"].endswith("+00:00")
    assert item["published_date"] == "2026-09-01"
    assert item["listing_status"] in ("live", "expired")
    assert item["link_state"] == "unverified"
    assert item["link_checked"] is False
    assert item["dedupe_basis"] == ""
    assert item["provenance"]["title"]["value"] == "Junior Data Analyst"
    assert item["provenance"]["title"]["basis"] == "provider_field"
    assert len(item["observed_salary"]) == 0
    assert "Cairo, Egypt" in item["observed_location"]


def test_normalised_record_keeps_legacy_fields_intact():
    item = jobs.normalise_listing(_listing())
    for key in ("title", "company", "location", "country", "url", "date",
                "tags", "source", "description", "salary", "work_type",
                "seniority", "is_expired", "listed_days_ago", "id"):
        assert key in item


def test_normalised_record_provider_job_id_and_fingerprint():
    raw = _listing(id="j55")
    item = jobs.normalise_listing(raw)
    assert item["provider_job_id"] == "j55"
    assert jobs._fingerprint("Remotive", "j55", raw["url"]) == item["fingerprint"]


def test_fingerprint_stable_offline_and_sensitive_to_inputs():
    fp1 = jobs._fingerprint("JSearch", "j1", "https://example.test/a")
    assert fp1 == jobs._fingerprint("JSearch", "j1", "https://example.test/a")
    assert fp1 != jobs._fingerprint("Remotive", "j1", "https://example.test/a")
    assert fp1 != jobs._fingerprint("JSearch", "j2", "https://example.test/a")
    assert fp1 == jobs._fingerprint("JSearch", "j1", "https://example.test/b")
    assert jobs._fingerprint("Remotive", None, "https://example.test/a") != \
        jobs._fingerprint("Remotive", None, "https://example.test/b")


def test_description_excerpt_is_trimmed():
    long_desc = "x" * 1000
    item = jobs.normalise_listing(_listing(description=long_desc))
    assert len(item["description_excerpt"]) == jobs._DESCRIPTION_EXCERPT_LEN
    assert item["description_excerpt"] == item["description"][:jobs._DESCRIPTION_EXCERPT_LEN]


def test_conflicting_observed_fields_are_preserved():
    a = jobs.normalise_listing(_listing(url="https://example.test/same",
                                        salary="$50k", work_type="remote"))
    b = jobs.normalise_listing(_listing(url="https://example.test/same",
                                        salary="$60k", work_type="onsite"))
    merged = jobs._merge([a, b])
    assert len(merged) == 1
    final = merged[0]
    assert "$50k" in final["observed_salary"] and "$60k" in final["observed_salary"]
    assert "remote" in final["observed_work_type"] and "onsite" in final["observed_work_type"]


# -------------------------------------------------------------------- dedupe

def test_dedup_by_provider_id_collapses_reposts():
    raw = [_listing(id="abc", title="Data Analyst", url="https://example.test/orig"),
           _listing(id="abc", title="Data Analyst (urgent)", url="https://example.test/repost")]
    merged = jobs._merge(raw)
    assert len(merged) == 1
    assert merged[0]["dedupe_basis"] == "provider_id"
    seen_titles = [t for t in merged[0].get("observed_titles", []) if t]
    assert set(seen_titles) == {"Data Analyst", "Data Analyst (urgent)"}


def test_dedup_by_apply_url_collapses_same_listing_across_providers():
    raw = [
        _listing(url="https://example.test/shared", source="Remotive"),
        _listing(url="https://example.test/shared", source="JSearch"),
    ]
    merged = jobs._merge(raw)
    assert len(merged) == 1
    assert merged[0]["dedupe_basis"] == "apply_url"


def test_dedup_by_identity_only_when_no_ids_or_urls():
    raw = [
        _listing(url="https://example.test/a1", company="Acme Analytics"),
        _listing(url="https://example.test/a2", company="Acme Analytics"),
    ]
    merged = jobs._merge(raw)
    assert len(merged) == 1
    assert merged[0]["dedupe_basis"] == "identity"


def test_near_duplicates_never_merge_on_title_alone():
    raw = [
        _listing(url="https://example.test/b1", company="Acme Analytics"),
        _listing(url="https://example.test/b2", company="Other Co"),
    ]
    assert len(jobs._merge(raw)) == 2
    raw2 = [
        _listing(url="https://example.test/c1", company="Acme Analytics"),
        _listing(url="https://example.test/c2", company="Acme Analytics",
                 location="London, United Kingdom"),
    ]
    assert len(jobs._merge(raw2)) == 2


def test_tags_union_and_content_preserved_on_dedup():
    raw = [
        _listing(url="https://example.test/same", tags=["SQL"]),
        _listing(url="https://example.test/same", tags=["Excel"]),
    ]
    merged = jobs._merge(raw)
    assert len(merged) == 1
    assert set(merged[0]["tags"]) == {"SQL", "Excel"}


# --------------------------------------------------------------- expiry flags

@pytest.mark.parametrize("flag", ["expired", "true", "1", "yes", True])
def test_expiry_flag_truthy_strings_and_bool_mark_expired(flag):
    raw = _listing(expired=flag)
    merged = jobs._merge([raw])
    assert merged[0]["is_expired"] is True
    assert merged[0]["listing_status"] == "expired"


@pytest.mark.parametrize("flag", ["not_expired", "false", "0", "no", None, False])
def test_expiry_flag_falsy_stays_live(flag):
    raw = _listing(expired=flag)
    merged = jobs._merge([raw])
    assert merged[0]["is_expired"] is False
    assert merged[0]["listing_status"] == "live"


def test_expired_always_beats_live_across_sources():
    raw = [
        _listing(url="https://example.test/same", source="Remotive", expired=True),
        _listing(url="https://example.test/same", source="JSearch"),
    ]
    merged = jobs._merge(raw)
    assert len(merged) == 1
    assert merged[0]["is_expired"] is True
    assert merged[0]["listing_status"] == "expired"


def test_close_date_or_expires_mark_expired():
    raw = _listing(close_date="2020-01-01")
    assert jobs._merge([raw])[0]["listing_status"] == "expired"
    raw2 = _listing(expires="2020-01-01")
    assert jobs._merge([raw2])[0]["listing_status"] == "expired"


def test_malformed_dates_do_not_crash():
    raw = _listing(date="not-a-date", close_date="gibberish")
    merged = jobs._merge([raw])
    assert len(merged) == 1
    assert merged[0].get("listed_days_ago") is None


# ----------------------------------------------------------------- link quality

@pytest.mark.parametrize("bad", [
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "file:///etc/passwd",
    "ftp://files.example.com/job",
    "mailto:someone@example.com",
])
def test_unsafe_schemes_are_rejected(bad):
    ok, state, reason = jobs._link_quality(bad)
    assert ok is False
    assert state == "rejected"
    assert reason == "unsafe_scheme"


@pytest.mark.parametrize("host", [
    "127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1", "169.254.10.10",
    "localhost", "foo.local", "bar.internal", "intranet", "site.onion",
])
def test_private_and_internal_network_hosts_are_rejected(host):
    ok, state, reason = jobs._link_quality(f"https://{host}/job")
    assert ok is False
    assert state == "rejected"
    assert reason == "private_network"


def test_ipv6_loopback_and_bracket_forms_are_rejected():
    ok, _, reason = jobs._link_quality("http://[::1]/job")
    assert ok is False and reason == "private_network"
    ok, _, reason = jobs._link_quality("http://[::1]:8080/job")
    assert ok is False and reason == "private_network"
    ok, _, reason = jobs._link_quality("http://127.0.0.1:8000/job")
    assert ok is False and reason == "private_network"


def test_scheme_less_values_stay_honestly_unverified():
    ok, state, reason = jobs._link_quality("l1")
    assert ok is True
    assert state == "unverified"
    assert reason == ""


def test_missing_and_empty_urls_are_rejected():
    ok, state, reason = jobs._link_quality("")
    assert ok is False and state == "rejected" and reason == "missing_url"
    item = jobs.normalise_listing(_listing(url=""))
    assert item["link_state"] == "rejected"


def test_verified_dead_url_kept_in_pipeline_not_silently_deleted():
    dead = list(jobs._VERIFIED_DEAD_JOB_URLS)[0]
    raw = [_listing(url=dead)]
    merged = jobs._merge(raw)
    assert len(merged) == 1
    assert merged[0]["link_state"] == "dead"
    assert merged[0]["listing_status"] == "link-unavailable"
    assert merged[0]["url"] == dead


def test_probe_is_never_invoked_during_merge(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("link probe must never run in tests")
    monkeypatch.setattr(jobs, "_probe_listing_link", boom)
    raw = [
        _listing(url="https://example.test/safe", source="Remotive"),
        _listing(url="javascript:alert(1)"),
    ]
    merged = jobs._merge(raw)
    assert len(merged) == 1
    # the SAFEST source wins the surfaced link; the unsafe one stays preserved
    assert merged[0]["url"] == "https://example.test/safe"
    assert merged[0]["link_state"] == "unverified"
    assert merged[0]["listing_status"] == "live"
    assert "javascript:alert(1)" in merged[0]["observed_urls"]


def test_rejected_and_dead_records_are_excluded_from_surfaced_feed(monkeypatch):
    dead = list(jobs._VERIFIED_DEAD_JOB_URLS)[0]
    raw = [
        _listing(title="Data Analyst", tags=["SQL", "Excel"]),
        _listing(title="Data Analyst (dead)", url=dead, tags=["SQL"]),
        _listing(title="Data Analyst (malicious)", url="javascript:alert(1)", tags=["SQL"]),
    ]
    monkeypatch.setattr(jobs, "_fetch_all", lambda *a, **k: raw)
    data = jobs.recent_jobs(
        skills=[("Data Analysis", "Intermediate")],
        role="Data Analyst", country="Egypt", location="Cairo",
        limit=10, _sync=True,
    )
    assert data["jobs"], "the relevant good listing must surface"
    assert [j["title"] for j in data["jobs"]] == ["Data Analyst"]
    assert all("dead" not in j["title"] and "malicious" not in j["title"]
               for j in data["jobs"])


# ------------------------------------------------------------ missing attributes

def test_missing_title_or_url_skipped_and_company_falls_back():
    merged = jobs._merge([
        _listing(title=""),
        _listing(url=""),
        _listing(company=""),
    ])
    assert len(merged) == 1
    assert merged[0]["company"] == "Unknown company"


def test_missing_location_gives_no_fabricated_country_city():
    item = jobs.normalise_listing(_listing(location=""))
    assert item["country"] == ""
    assert item["city"] == ""