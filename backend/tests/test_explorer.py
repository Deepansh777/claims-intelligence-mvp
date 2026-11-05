"""Data Explorer metadata and preview endpoints, against the live database."""

import pytest

from app.services import explorer


def test_walks_schema_to_columns(http):
    schemas = http.get("/api/v1/explorer/schemas").json()
    names = {s["name"] for s in schemas}
    assert {"raw", "mart", "ref"} <= names
    assert not names & {"app", "llm_metrics", "pg_catalog", "information_schema"}

    tables = http.get("/api/v1/explorer/schemas/raw/tables").json()
    claims = next(t for t in tables if t["name"] == "claims")
    assert claims["kind"] == "table" and claims["estimated_rows"] > 0

    cols = http.get("/api/v1/explorer/schemas/raw/tables/claims/columns").json()
    assert cols and {"name", "type", "nullable"} == set(cols[0])


def test_preview_returns_five_rows(http):
    r = http.get("/api/v1/explorer/schemas/raw/tables/claims/preview").json()
    assert r["row_count"] == 5 and len(r["rows"]) == 5 and r["columns"]


@pytest.mark.parametrize(
    "path",
    [
        "/schemas/app/tables",
        "/schemas/nope/tables/claims/columns",
        "/schemas/raw/tables/nope/columns",
        '/schemas/raw/tables/claims"; DROP TABLE raw.claims; --/preview',
        "/schemas/app/tables/messages/preview",
    ],
)
def test_unknown_or_hidden_objects_are_404(http, path):
    assert http.get("/api/v1/explorer" + path).status_code == 404


def test_metadata_is_cached(http, monkeypatch):
    http.get("/api/v1/explorer/schemas/ref/tables")
    calls = []
    monkeypatch.setattr(explorer, "run_query", lambda *a: calls.append(a))
    assert http.get("/api/v1/explorer/schemas/ref/tables").status_code == 200
    assert calls == []


def test_ident_quotes():
    assert explorer._ident('a"b') == '"a""b"'
