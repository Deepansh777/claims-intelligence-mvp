"""Resolving tabs for display and packaging a version as one offline HTML file."""

import base64
import hashlib
import json
import re

from conftest import as_user
from test_dashboard_stream import OUTLINE, generate, plan, tab

from app.llm.dashboard_schemas import DashboardSpec, Widget
from app.llm.guards import resolve_tab
from app.llm.schemas import HBar, Kpi, QueryResult, Ref
from app.services import dashboard_export

RESULTS = {
    "q1": QueryResult(
        columns=["provider_pmpm", "benchmark_pmpm"],
        types=["numeric", "numeric"],
        rows=[[113.94, 175.85]],
        row_count=1,
        truncated=False,
    ),
    "q2": QueryResult(
        columns=["category", "admissions", "member_sk"],
        types=["text", "int8", "text"],
        rows=[["Cardiac", 3, "536507"]],
        row_count=1,
        truncated=False,
    ),
}


def kpi(sub):
    return Kpi(
        type="kpi",
        label="PMPM",
        value=Ref(query="q1", column="provider_pmpm", row="first"),
        format="usd2",
        sub=sub,
    )


def test_resolve_fills_placeholders_everywhere():
    t = tab().model_copy(
        update={
            "widgets": [Widget(id="overview-pmpm", component=kpi("vs {{q1.benchmark_pmpm|usd2}}"))],
            "limitations": ["Benchmark {{q1.benchmark_pmpm|usd2}}."],
        }
    )
    out = resolve_tab(t, RESULTS, set(), set())
    assert out["narrative"].startswith("PMPM vs. benchmark $175.85.")
    assert out["insights"][0]["finding"] == "Provider PMPM was $113.94."
    assert out["insights"][0]["status"] == "favorable" and out["grid"] == [["overview-gap"]]
    assert out["widgets"][0]["component"]["value"] == 113.94
    assert out["widgets"][0]["component"]["sub"] == "vs $175.85"
    assert out["limitations"] == ["Benchmark $175.85."]


def test_resolve_drops_unchecked_parts_and_insights_left_without_evidence():
    t = tab().model_copy(
        update={
            "narrative": "PMPM was 999.",
            "widgets": [Widget(id="overview-pmpm", component=kpi("vs {{q1.nope}}"))],
        }
    )
    out = resolve_tab(t, RESULTS, set(), set())
    assert out["widgets"] == [] and out["insights"] == [] and out["grid"] == []
    assert out["narrative"] == "The results are shown above."


def test_resolve_grid_drops_bad_ids_and_appends_unplaced_items():
    bar = HBar(
        type="hbar",
        title="Admissions",
        query="q2",
        label="category",
        value="admissions",
        format="int",
        top_n=None,
    )
    widgets = tab().widgets + [Widget(id=f"overview-b{i}", component=bar) for i in range(4)]
    t = tab().model_copy(
        update={"widgets": widgets, "grid": [["overview-b0", "nope", "overview-b0"], []]}
    )
    out = resolve_tab(t, RESULTS, set(), set())
    assert out["grid"] == [
        ["overview-b0"],
        ["overview-b1", "overview-b2", "overview-b3"],
        ["overview-gap"],
    ]


def test_legacy_tabs_still_resolve():
    legacy = {
        "id": "overview",
        "name": "Performance overview",
        "outcome": "answered",
        "takeaway": "PMPM vs. benchmark {{q1.benchmark_pmpm|usd2}}.",
        "findings": [
            {
                "finding": "Provider PMPM was {{q1.provider_pmpm|usd2}}.",
                "evidence": ["overview-pmpm"],
                "clinical_context": "",
                "review_opportunity": "",
                "limitation": "",
            }
        ],
        "widgets": [{"id": "overview-pmpm", "component": kpi(None).model_dump()}],
        "assumptions": [],
        "limitations": [],
    }
    t = DashboardSpec.model_validate({"title": "t", "tabs": [legacy]}).tabs[0]
    out = resolve_tab(t, RESULTS, set(), set())
    assert out["takeaway"] == "PMPM vs. benchmark $175.85." and "grid" not in out
    assert out["findings"] == [
        {
            "finding": "Provider PMPM was $113.94.",
            "evidence": ["overview-pmpm"],
            "clinical_context": "",
            "review_opportunity": "",
            "limitation": "",
        }
    ]


def test_payload_embeds_only_displayed_columns():
    bar = HBar(
        type="hbar",
        title="Admissions",
        query="q2",
        label="category",
        value="admissions",
        format="int",
        top_n=None,
    )
    t = tab().model_copy(
        update={"widgets": tab().widgets + [Widget(id="overview-cats", component=bar)]}
    )
    old_plan = plan().model_dump(exclude={"analysis"})  # saved before Python analysis existed
    version = {
        "request": "r",
        "outline": OUTLINE.model_dump(),
        "spec": DashboardSpec(title="t", tabs=[t]).model_dump(),
        "queries": {"overview": {"plan": old_plan}},
        "results": {"overview": {n: r.model_dump() for n, r in RESULTS.items()}},
        "version": 1,
        "created_at": "2026-11-05T00:00:00Z",
    }
    p = dashboard_export.payload(version)
    assert p["datasets"]["overview"] == {
        "q2": {
            "columns": ["category", "admissions"],
            "types": ["text", "int8"],
            "rows": [["Cardiac", 3]],
            "row_count": 1,
            "truncated": False,
        }
    }


def test_methodology_lists_final_queries_and_keeps_text_inert():
    t = tab().model_copy(update={"limitations": ["Pipes | and\nnewlines stay in one cell."]})
    run = {"name": "q1", "purpose": "PMPM vs benchmark", "duration_ms": 12}
    version = {
        "request": "# not a heading | cell",
        "outline": OUTLINE.model_dump(),
        "spec": DashboardSpec(title="t", tabs=[t]).model_dump(),
        "queries": {
            "overview": {
                "plan": plan().model_dump(),
                "executions": [
                    {**run, "attempt": 1, "sql": "SELECT bad", "status": "failed"},
                    {**run, "attempt": 2, "sql": "SELECT 1", "status": "succeeded"},
                ],
            }
        },
        "results": {"overview": {n: r.model_dump() for n, r in RESULTS.items()}},
        "version": 1,
        "created_at": "2026-11-05T00:00:00Z",
        "dataset_loaded_at": None,
    }
    m = dashboard_export.methodology(version)
    assert [q["sql"] for q in m["queries"]] == ["SELECT 1"] and m["queries"][0]["row_count"] == 1
    md = m["markdown"]
    assert "| Request | # not a heading \\| cell |" in md
    assert "- Pipes \\| and newlines stay in one cell." in md
    assert "| Metric | PMPM |" in md and "- q1: PMPM vs benchmark (1 rows)" in md


def test_html_is_self_contained_and_script_safe():
    p = {
        "title": "</title><script>x()</script>",
        "note": "</script><script>alert(1)</script>\u2028",
    }
    page = dashboard_export.render_html(p)
    assert "<script>alert" not in page and "<script>x()" not in page
    data = re.search(r'id="dashboard-data">(.*?)</script>', page, re.DOTALL).group(1)
    assert json.loads(data) == p
    script = page.rsplit("\n<script>", 1)[1].rsplit("</script>", 1)[0]
    assert "</script" not in script and "<!--" not in script
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    assert f"script-src 'sha256-{digest}'" in page and "connect-src 'none'" in page
    # The bundled CSS-in-JS runtime names "@import" as a string; only a real external one fails.
    external = r"""(src|href)=["']?https?:|url\(\s*["']?https?:|@import\s+["']?(url\()?\s*["']?(https?:|//)"""
    assert not re.search(external, page)


def test_filename_is_sanitized():
    f = dashboard_export.filename
    assert (
        f("Provider A: Clinical Performance 2025-2026.HTML")
        == "provider-a-clinical-performance-2025-2026.html"
    )
    assert f("../../etc/passwd") == "etc-passwd.html"
    assert f("dr-a-npi-8000007172-member-536507") == "dr-a-npi-member.html"
    assert f("!!!") == "provider-dashboard.html"


def test_export_endpoint_serves_the_same_sandboxed_file(http, llm):
    as_user()
    llm[0].extend([plan(), tab()])
    dashboard_id = generate(http)["dashboard_id"]
    url = f"/api/v1/dashboards/{dashboard_id}/dashboard.html"

    view, download = http.get(url), http.get(f"{url}?download=true")
    assert view.status_code == 200 and view.text == download.text
    assert view.headers["content-security-policy"].startswith(
        "sandbox allow-scripts allow-downloads;"
    )
    assert "content-disposition" not in view.headers
    assert (
        download.headers["content-disposition"]
        == 'attachment; filename="performance-overview.html"'
    )
    data = json.loads(
        re.search(r'id="dashboard-data">(.*?)</script>', view.text, re.DOTALL).group(1)
    )
    assert data["tabs"][0]["insights"][0]["finding"].startswith("Provider PMPM was $")
    assert "{{" not in json.dumps(data["tabs"])
