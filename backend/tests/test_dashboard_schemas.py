from app.llm.dashboard_schemas import (
    DashboardOutline,
    DashboardScope,
    DashboardSpec,
    DashboardTab,
    Insight,
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
    return DashboardOutline(title="t", filename="t", scope=SCOPE, tabs=tabs)


def widget(wid):
    return Widget(id=wid, component=Callout(type="callout", tone="info", text="x"))


def tab(tid, widgets=(), evidence=None, grid=None, narrative="One. Two. Three. Four."):
    insights = (
        []
        if evidence is None
        else [
            Insight(
                id=f"{tid}-note",
                status="neutral",
                label="l",
                finding="f",
                next_step="",
                evidence=list(evidence),
            )
        ]
    )
    placeable = [*widgets, *(c.id for c in insights)]
    return DashboardTab(
        id=tid,
        name=tid,
        outcome="answered",
        widgets=[widget(w) for w in widgets],
        insights=insights,
        grid=[[i] for i in placeable] if grid is None else grid,
        narrative=narrative,
        assumptions=[],
        limitations=[],
    )


def spec(*tabs):
    return DashboardSpec(title="t", tabs=list(tabs))


def test_valid_dashboard_has_no_errors():
    s = spec(
        tab("overview", ["overview-kpi", "overview-trend"], evidence=["overview-trend"]),
        tab("drivers", ["drivers-cats"]),
    )
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


def test_widget_ids_are_prefixed_by_tab_and_unique():
    s = spec(tab("a", ["a-kpi", "a-kpi"], grid=[["a-kpi"]]), tab("b", ["kpi"]))
    assert structure_errors(outline("a", "b"), s) == [
        "a: widget and insight ids must be unique",
        "b: widget id 'kpi' must start with 'b-'",
    ]


def test_insights_must_cite_their_own_tab_widgets():
    s = spec(tab("a", ["a-x"], evidence=["b-y"]), tab("b", ["b-y"], evidence=[]))
    assert structure_errors(outline("a", "b"), s) == [
        "a: insight cites unknown widget 'b-y'",
        "b: an insight cites no widget",
    ]


def test_grid_has_up_to_three_rows_of_three_and_places_each_item_once():
    ids = [f"a-{i}" for i in range(5)]
    assert structure_errors(outline("a"), spec(tab("a", ids, grid=[ids[:3], ids[3:]]))) == []
    errors = structure_errors(outline("a"), spec(tab("a", ids, grid=[ids[:4], [], ["a-0"]])))
    assert errors == [
        "a: grid: each row needs 1-3 ids",
        "a: grid: place 'a-0' exactly once",
        "a: grid: place 'a-4' exactly once",
    ]
    rows = [[i] for i in ids[:4]]
    assert "a: grid: at most 3 rows" in structure_errors(
        outline("a"), spec(tab("a", ids, grid=rows))
    )
    assert structure_errors(outline("a"), spec(tab("a", grid=[["a-x"]]))) == [
        "a: grid: 'a-x' is not a non-KPI widget or insight"
    ]


def test_narrative_needs_four_to_eight_sentences():
    four = "PMPM vs. benchmark was {{q1.gap|usd2}}. B. C. D."
    assert structure_errors(outline("a"), spec(tab("a", narrative=four))) == []
    for text in ("A. B. C.", " ".join("S." for _ in range(9))):
        assert structure_errors(outline("a"), spec(tab("a", narrative=text))) == [
            "a: narrative: write 4-8 sentences"
        ]
