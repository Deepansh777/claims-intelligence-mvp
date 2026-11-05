from app.llm.guards import FALLBACK_NOTE, FALLBACK_TEXT, answer_errors, resolve_answer
from app.llm.schemas import (
    AnswerSpec,
    Callout,
    HBar,
    Kpi,
    QueryResult,
    Ref,
    SeriesChart,
    Table,
    TableColumn,
)

RESULTS = {
    "q1": QueryResult(
        columns=["month_year", "pmpm", "pct_change", "total_allowed"],
        types=["text", "numeric", "numeric", "numeric"],
        rows=[["2025-06", 400.0, None, 1_100_000.0], ["2025-07", 418.4, 0.046, 1_234_567.0]],
        row_count=2,
        truncated=False,
    )
}


def kpi(row="last", column="pmpm"):
    return Kpi(
        type="kpi",
        label="PMPM",
        value=Ref(query="q1", column=column, row=row),
        format="usd2",
        sub=None,
    )


def line(y=("pmpm",)):
    return SeriesChart(
        type="line", title="PMPM by month", query="q1", x="month_year", y=list(y), format="usd2"
    )


def spec(text="", components=(), limitations=(), outcome="answered", narrative=""):
    return AnswerSpec(
        outcome=outcome,
        text=text,
        narrative=narrative,
        components=list(components),
        assumptions=[],
        limitations=list(limitations),
        followups=["a", "b", "c", "d"],
    )


def check(s, allowed=frozenset(), notes=frozenset()):
    return answer_errors(s, RESULTS, set(allowed), set(notes)), resolve_answer(
        s, RESULTS, set(allowed), set(notes)
    )


def test_valid_answer_resolves_placeholders_and_values():
    errors, out = check(
        spec(
            "PMPM was {{q1.pmpm[last]|usd2}}, up {{q1.pct_change[last]|pct_ratio}}.",
            [kpi(), line()],
        )
    )
    assert errors == []
    assert out["text"] == "PMPM was $418.40, up 4.6%."
    assert out["components"][0]["value"] == 418.4
    assert [c["type"] for c in out["components"]] == ["kpi", "line"]
    assert len(out["followups"]) == 3


def test_bare_numbers_must_match_results():
    ok = "PMPM was about $418, total allowed $1.2M, a 4.6% rise in 2025 (2025-07) per 1,000; HbA1c."
    assert check(spec(ok, [kpi()]))[0] == []
    errors, out = check(spec("PMPM was $431.20.", [kpi()]))
    assert errors and "431.20" in errors[0]
    assert out["text"] == FALLBACK_TEXT and FALLBACK_NOTE in out["limitations"]
    assert check(spec("Over the last 6 months.", [kpi()]), allowed={6.0})[0] == []


def test_invalid_components_are_reported_and_dropped():
    bad = [line(["cost"]), line(["month_year"]), kpi(row="5"), kpi(column="nope")]
    errors, out = check(spec("Results.", [kpi(), *bad]))
    assert len(errors) == 4
    assert [c["type"] for c in out["components"]] == ["kpi"]


def test_narrative_is_filled_or_dropped_alone():
    ok = "The rise to {{q1.pmpm[last]|usd2}} may suggest higher acuity."
    errors, out = check(spec("Results.", [kpi()], narrative=ok))
    assert errors == [] and out["narrative"] == "The rise to $418.40 may suggest higher acuity."
    errors, out = check(spec("Results.", [kpi()], narrative="Roughly 25% of members drove it."))
    assert errors and "narrative" in errors[0]
    assert out["narrative"] == "" and out["text"] == "Results."


def test_component_text_and_notes_are_checked():
    s = spec(
        "Ok.",
        [Callout(type="callout", tone="warn", text="Up 9.9% vs last year")],
        limitations=["36% null", "Allowed only"],
    )
    errors, out = check(s, notes={36.0})
    assert len(errors) == 1
    assert out["limitations"] == ["36% null", "Allowed only"]
    assert all(c["type"] != "callout" for c in out["components"])


def test_null_value_and_fallback_table():
    _errors, out = check(spec("First month change: {{q1.pct_change|pct}}.", [line(["cost"])]))
    assert out["text"] == "First month change: not available."
    assert [c["type"] for c in out["components"]] == ["table"]
    assert out["components"][0]["columns"][1] == {
        "column": "pmpm",
        "label": "Pmpm",
        "format": "number",
    }


def test_table_shows_every_result_column():
    table = Table(
        type="table",
        title="Months",
        query="q1",
        columns=[TableColumn(column="month_year", label="Month", format="text")],
        sort_column=None,
        sort_desc=False,
        filter_columns=[],
    )
    errors, out = check(spec("By month.", [table]))
    cols = out["components"][0]["columns"]
    assert errors == []
    assert [c["column"] for c in cols] == ["month_year", "pmpm", "pct_change", "total_allowed"]
    assert cols[0]["label"] == "Month" and cols[3]["label"] == "Total allowed"


def test_no_rows_becomes_no_results():
    empty = {"q1": RESULTS["q1"].model_copy(update={"rows": [], "row_count": 0})}
    out = resolve_answer(spec("No admissions matched.", [line()]), empty, set(), set())
    assert out["outcome"] == "no_results" and out["components"] == []


def test_hbar_is_capped_to_top_25():
    many = {
        "q1": QueryResult(
            columns=["pcp", "rate"],
            types=["text", "numeric"],
            rows=[[f"P{i}", float(i)] for i in range(40)],
            row_count=40,
            truncated=False,
        )
    }
    bar = HBar(
        type="hbar",
        title="Top PCPs",
        query="q1",
        label="pcp",
        value="rate",
        format="rate",
        top_n=None,
    )
    assert (
        resolve_answer(spec("Ranked.", [bar]), many, set(), set())["components"][0]["top_n"] == 25
    )
