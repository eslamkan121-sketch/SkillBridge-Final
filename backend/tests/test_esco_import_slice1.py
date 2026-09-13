"""Phase E Slice 1 — controlled ESCO adapter (offline).

These tests never touch the real ESCO API: the FixtureTransport resolves
recorded, sanitized payloads from backend/tests/fixtures/esco/. The
LiveTransport is exercised through an injected fake HTTP client only.
"""

import json
import os

import httpx
import pytest

from app import esco_import

FIXTURES = os.path.join(
    os.path.dirname(__file__), "fixtures", "esco")

OCC_1 = "174b1a5b-f93b-4d5e-b2b2-c6a2a5c9d001"
OCC_2 = "286c2b6c-a04c-5e6f-c3c3-d7b3b6dae112"
OCC_3 = "397d3c7d-b15d-6f70-d4d4-e8c4c7ebf223"
URI_1 = f"http://data.europa.eu/esco/occupation/{OCC_1}"


def _fixture():
    return esco_import.FixtureTransport(FIXTURES)


# --- Adapter contract: search -----------------------------------------------


def test_search_normalizes_preferred_alt_and_hidden_titles():
    occs = list(_fixture().iter_search("data engineer", language="en", version="1.2.0"))
    by_uri = {o.uri: o for o in occs}
    assert set(by_uri) == {URI_1,
                           f"http://data.europa.eu/esco/occupation/{OCC_2}",
                           f"http://data.europa.eu/esco/occupation/{OCC_3}"}
    occ = by_uri[URI_1]
    assert occ.title == "Data engineer"
    assert occ.alt_titles == ("Engineer (data)", "Data engineering consultant")
    assert occ.hidden_titles == ("LE data engineer",)
    assert occ.code == "2511"          # ISCO unit group, not full "2511.3"


def test_search_skips_rows_without_uri_or_title():
    occs = list(_fixture().iter_search("data engineer", language="en", version="1.2.0"))
    assert all(o.uri and o.title for o in occs)


# --- Adapter contract: resource ---------------------------------------------


def test_resource_normalizes_labels_skills_description_parent():
    occ = _fixture().fetch_occupation(URI_1, language="en", version="1.2.0")
    assert occ.uri == URI_1
    assert occ.title == "Data engineer"
    assert occ.alt_titles == ("Engineer (data)", "Data engineering consultant")
    assert occ.hidden_titles == ("LE data engineer",)
    assert occ.code == "2511"
    assert occ.description and "pipelines" in occ.description
    assert occ.essential == ("data pipeline design", "SQL", "data warehousing", "job scheduling")
    assert occ.optional == ("Apache Spark",)
    assert occ.parent_uri == "http://data.europa.eu/esco/occupation/a1b2c3d4-1111-4a2b-8f3c-5d6e7f8a9b0c"
    assert occ.language == "en"


# --- Multiple languages ------------------------------------------------------


def test_language_is_persisted_and_resolves_labels():
    occs = list(_fixture().iter_search("data engineer", language="fr", version="1.2.0"))
    fr = {o.uri: o for o in occs}[URI_1]
    assert fr.title == "Ingénieur de données"
    assert fr.alt_titles == ("Ingénieur(e) de données",)
    assert fr.language == "fr"

    fr_resource = _fixture().fetch_occupation(URI_1, language="fr", version="1.2.0")
    assert fr_resource.title == "Ingénieur de données"
    assert fr_resource.essential == (
        "conception de pipelines de données", "SQL", "entreposage de données")
    assert fr_resource.language == "fr"


# --- Pagination --------------------------------------------------------------


def test_pagination_walks_all_pages_and_dedups():
    occs = list(_fixture().iter_search("pagination probe", language="en", version="1.2.0"))
    assert len(occs) == 35
    assert len({o.uri for o in occs}) == 35
    assert occs[0].title == "Synthetic occupation 001"


def test_pagination_respects_page_size():
    occs = list(_fixture().iter_search("pagination probe", language="en", version="1.2.0",
                                       page_size=10))
    assert len(occs) == 35


def test_pagination_respects_max_pages_and_max_occupations():
    one_page = list(_fixture().iter_search("pagination probe", language="en", version="1.2.0",
                                           page_size=30, max_pages=1))
    assert len(one_page) == 30
    bounded = list(_fixture().iter_search("pagination probe", language="en", version="1.2.0",
                                          page_size=30, max_occupations=32))
    assert len(bounded) == 32


# --- Version pinning / configuration ----------------------------------------


def test_default_configuration_is_pinned():
    assert esco_import.DEFAULT_ESCO_VERSION == "1.2.0"
    assert esco_import.DEFAULT_ESCO_LANGUAGE == "en"
    assert esco_import.configured_version() == "1.2.0"
    assert esco_import.configured_language() == "en"


def test_live_transport_sends_selected_version_and_language(monkeypatch):
    seen = []

    class _Client:
        def get(self, url, params=None, **kwargs):
            seen.append((url, dict(params or {})))
            return _JsonResp(_search_payload("software"))

    monkeypatch.setattr(esco_import, "ESCO_RETRIES", 0)
    mon = esco_import.LiveTransport(client=_Client())
    occs = list(mon.iter_search("software", language="fr", version="1.1.0", page_size=5))

    search_url, params = seen[0]
    assert "api/search" in search_url
    assert params["selectedVersion"] == "1.1.0"
    assert params["language"] == "fr"
    assert params["type"] == "occupation"
    assert params["offset"] == 0
    assert params["limit"] == 5
    assert occs and occs[0].title == "software"


def test_live_transport_resource_pins_version_too(monkeypatch):
    seen = []

    class _Client:
        def get(self, url, params=None, **kwargs):
            seen.append((url, dict(params or {})))
            return _JsonResp({"uri": URI_1, "title": "Data engineer"})

    monkeypatch.setattr(esco_import, "ESCO_RETRIES", 0)
    mon = esco_import.LiveTransport(client=_Client())
    occ = mon.fetch_occupation(URI_1, language="en", version="1.2.0")
    url, params = seen[0]
    assert "resource/occupation" in url
    assert params["selectedVersion"] == "1.2.0"
    assert params["uri"] == URI_1
    assert occ.title == "Data engineer"


# --- Network failure / malformed payload -------------------------------------


class _JsonResp:
    def __init__(self, payload):
        self._payload = payload

    @property
    def status_code(self):
        return 200

    def json(self):
        return self._payload


def _search_payload(title="software developer"):
    return {"_embedded": {"results": [
        {"uri": "http://data.europa.eu/esco/occupation/live-1", "title": title,
         "code": "2512.9"}]}}


def test_live_transport_raises_unavailable_on_network_failure(monkeypatch):
    class _Down:
        def get(self, url, params=None, **kwargs):
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(esco_import, "ESCO_RETRIES", 0)
    mon = esco_import.LiveTransport(client=_Down())
    with pytest.raises(esco_import.EscoUnavailableError):
        list(mon.iter_search("software"))


def test_live_transport_raises_unavailable_on_server_error(monkeypatch):
    class _Err:
        def get(self, url, params=None, **kwargs):
            class _R:
                status_code = 503

                def json(self):
                    raise AssertionError("should not parse")

            return _R()

    monkeypatch.setattr(esco_import, "ESCO_RETRIES", 0)
    mon = esco_import.LiveTransport(client=_Err())
    with pytest.raises(esco_import.EscoUnavailableError):
        list(mon.iter_search("software"))


def test_live_transport_raises_malformed_on_non_json(monkeypatch):
    class _Bad:
        def get(self, url, params=None, **kwargs):
            class _R:
                status_code = 200

                def json(self):
                    raise ValueError("not json")

            return _R()

    monkeypatch.setattr(esco_import, "ESCO_RETRIES", 0)
    mon = esco_import.LiveTransport(client=_Bad())
    with pytest.raises(esco_import.EscoMalformedError):
        list(mon.iter_search("software"))


def test_fixture_transport_raises_malformed_on_broken_payload():
    with pytest.raises(esco_import.EscoMalformedError):
        list(_fixture().iter_search("broken", language="en", version="1.2.0"))
    with pytest.raises(esco_import.EscoMalformedError):
        _fixture()._load("1.2.0_en_resource_malformed.json")


def test_fixture_transport_raises_unavailable_on_missing_fixture():
    with pytest.raises(esco_import.EscoUnavailableError):
        list(_fixture().iter_search("not a real query", language="en", version="1.2.0"))


def test_fixtures_are_rankable_json_files():
    """Guard: every recorded fixture must parse as JSON (no hand-edited broken core
    set) so the offline suite is deterministic."""
    for name in os.listdir(FIXTURES):
        if "broken" in name or "_malformed" in name:
            continue
        with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
            json.load(fh)