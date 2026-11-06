from app.llm.dashboard_schemas import (
    DashboardOutline,
    DashboardScope,
    DashboardSpec,
    DashboardTab,
    Finding,
    TabOutline,
    Widget,
    structure_errors,
)
from app.llm.schemas import Callout

SCOPE = DashboardScope(
    level="pcp",
    provider_name="Dr. A",
    provider_npi="1234567890",
    provider_tin="123456789",
    network="NEXUS",
    population="Members attributed to Dr. A",
    period="2024-07-01 to 2026-06-30",
)


def outline(*ids):
    tabs = [TabOutline(id=i, name=i, question="?", metrics=[], visuals=[]) for i in ids]
    return DashboardOutline(title="t", scope=SCOPE, tabs=tabs)


def widget(wid):
    return Widget(id=wid, component=Callout(type="callout", tone="info", text="x"))


def tab(tid, widgets=(), evidence=None):
    findings = (
        []
        if evidence is None
        else [
            Finding(
                finding="f",
                evidence=list(evidence),
                clinical_context="",
                review_opportunity="",
                limitation="",
            )
        ]
    )
    return DashboardTab(
        id=tid,
        name=tid,
        outcome="answered",
        takeaway="t",
        findings=findings,
        widgets=[widget(w) for w in widgets],
        assumptions=[],
        limitations=[],
    )


def spec(*tabs):
    return DashboardSpec(title="t", filename="t", tabs=list(tabs))


def test_valid_dashboard_has_no_errors():
    s = spec(tab("overview", ["kpi1", "trend"], evidence=["trend"]), tab("drivers", ["cats"]))
    assert structure_errors(outline("overview", "drivers"), s) == []


def test_tab_count_limits():
    assert structure_errors(outline(), spec()) == ["outline: needs 1-3 tabs"]
    ids = ("a", "b", "c", "d")
    assert "outline: needs 1-3 tabs" in structure_errors(outline(*ids), spec(*map(tab, ids)))


def test_tabs_must_match_outline_order_and_be_unique():
    assert structure_errors(outline("a", "b"), spec(tab("b"), tab("a"))) == [
        "tabs must match the outline tab ids in order: ['a', 'b']"
    ]
    assert "outline: tab ids must be unique" in structure_errors(
        outline("a", "a"), spec(tab("a"), tab("a"))
    )


def test_widget_ids_unique_across_tabs():
    s = spec(tab("a", ["kpi"]), tab("b", ["kpi"]))
    assert structure_errors(outline("a", "b"), s) == ["widget ids must be unique: ['kpi']"]


def test_findings_must_cite_their_own_tab_widgets():
    s = spec(tab("a", ["x"], evidence=["y"]), tab("b", ["y"], evidence=[]))
    assert structure_errors(outline("a", "b"), s) == [
        "a: finding cites unknown widget 'y'",
        "b: a finding cites no widget",
    ]
