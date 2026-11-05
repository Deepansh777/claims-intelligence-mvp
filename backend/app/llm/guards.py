"""Check an AnswerSpec against executed query results and resolve it for the UI.

Displayed figures must come from query results: components bind to result columns, and
narrative figures are placeholders filled here. A bare number in model-written text is
accepted only if it matches a result value (as written or as a percentage) or appears in the
allowed text (question, interpretation); assumptions/limitations may also cite the docs.
"""

import re
from typing import Any

from app.llm.schemas import (
    AnswerSpec,
    Callout,
    Format,
    HBar,
    Kpi,
    QueryResult,
    Scatter,
    SeriesChart,
    Table,
)

NUMERIC_TYPES = {"int2", "int4", "int8", "float4", "float8", "numeric"}
FORMATS = set(Format.__args__)
PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\.(\w+)(?:\[(\w+)\])?(?:\|(\w+))?\s*\}\}")
ISO_DATE = re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b")
NUMBER = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s?(k|K|M|B|thousand|million|billion)?(?!\w)")
SCALE = {"k": 1e3, "K": 1e3, "thousand": 1e3, "M": 1e6, "million": 1e6, "B": 1e9, "billion": 1e9}
ALWAYS_OK = {12.0, 30.0, 100.0, 1000.0}  # policy units: months, 30-day windows, %, per 1,000
MAX_HBAR_ROWS = 25
FALLBACK_TEXT = "The results are shown below."
FALLBACK_NOTE = (
    "The written summary could not be checked against the query results, so it was omitted."
)


def numbers_in(text: str) -> set[float]:
    return {float(m.group(1).rstrip(",").replace(",", "")) for m in NUMBER.finditer(text)}


def format_value(v: Any, fmt: str) -> str:
    if v is None:
        return "not available"
    if fmt in ("text", "date") or isinstance(v, bool) or not isinstance(v, int | float):
        return str(v)
    if fmt == "usd":
        return f"${v:,.0f}"
    if fmt == "usd2":
        return f"${v:,.2f}"
    if fmt == "int":
        return f"{v:,.0f}"
    if fmt == "pct":
        return f"{v:,.1f}%"
    if fmt == "pct_ratio":
        return f"{v * 100:,.1f}%"
    if fmt == "rate":
        return f"{v:,.2f}"
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def _row_index(row: str, n: int) -> int | None:
    i = {"first": 0, "last": n - 1}.get(row, int(row) if row.isdigit() else -1)
    return i if 0 <= i < n else None


def _lookup(results: dict[str, QueryResult], query: str, column: str, row: str):
    """(value, error)."""
    r = results.get(query)
    if r is None:
        return None, f"unknown query {query!r}"
    if column not in r.columns:
        return None, f"column {column!r} not in {query}"
    i = _row_index(row, r.row_count)
    if i is None:
        return None, f"row {row!r} not in {query} ({r.row_count} rows)"
    return r.rows[i][r.columns.index(column)], None


def _result_numbers(results: dict[str, QueryResult]) -> list[float]:
    out = [float(r.row_count) for r in results.values()]
    for r in results.values():
        for row in r.rows:
            out += [abs(v) for v in row if isinstance(v, int | float) and not isinstance(v, bool)]
    return out


def _unverified(text: str, values: list[float], allowed: set[float]) -> list[str]:
    bad = []
    for m in NUMBER.finditer(ISO_DATE.sub(" ", PLACEHOLDER.sub(" ", text or ""))):
        token, suffix = m.group(1).rstrip(","), m.group(2)
        x = float(token.replace(",", ""))
        if suffix is None and (
            x in allowed or x in ALWAYS_OK or ("." not in token and 1900 <= x <= 2100)
        ):
            continue
        scale = SCALE.get(suffix, 1)
        decimals = len(token.split(".")[1]) if "." in token else 0
        target, tol = x * scale, 0.5 * 10**-decimals * scale
        if any(abs(v - target) <= tol or abs(v * 100 - target) <= tol for v in values):
            continue
        bad.append(m.group(0).strip())
    return bad


def _fill(text: str, results: dict[str, QueryResult]) -> tuple[str, list[str]]:
    errors = []

    def sub(m: re.Match) -> str:
        query, column, row, fmt = m.group(1), m.group(2), m.group(3) or "first", m.group(4)
        if fmt and fmt not in FORMATS:
            errors.append(f"unknown format {fmt!r} in {m.group(0)}")
        value, err = _lookup(results, query, column, row)
        if err:
            errors.append(f"placeholder {m.group(0)}: {err}")
        return format_value(value, fmt or "number")

    return PLACEHOLDER.sub(sub, text or ""), errors


def _bindings(c) -> tuple[str, list[str], list[str]]:
    """(query, columns that must exist, columns that must be numeric)."""
    if isinstance(c, Kpi):
        return c.value.query, [c.value.column], []
    if isinstance(c, SeriesChart):
        return c.query, [c.x, *c.y], c.y
    if isinstance(c, HBar):
        return c.query, [c.label, c.value], [c.value]
    if isinstance(c, Scatter):
        return c.query, [c.x, c.y, *([c.label] if c.label else []), *c.tooltip], [c.x, c.y]
    sort = [c.sort_column] if c.sort_column else []
    return c.query, [col.column for col in c.columns] + c.filter_columns + sort, []


def _component_errors(c, results, values, allowed) -> list[str]:
    texts = (
        [c.text]
        if isinstance(c, Callout)
        else [c.label, c.sub or ""]
        if isinstance(c, Kpi)
        else [c.title]
    )
    errors = [
        f"{c.type}: number {n!r} is not in the results"
        for t in texts
        for n in _unverified(t, values, allowed)
    ]
    if isinstance(c, Callout):
        return errors
    query, needed, numeric = _bindings(c)
    r = results.get(query)
    if r is None:
        return errors + [f"{c.type}: unknown query {query!r}"]
    errors += [f"{c.type}: column {col!r} not in {query}" for col in needed if col not in r.columns]
    errors += [
        f"{c.type}: column {col!r} is not numeric"
        for col in numeric
        if col in r.columns and r.types[r.columns.index(col)] not in NUMERIC_TYPES
    ]
    if isinstance(c, SeriesChart) and not 1 <= len(c.y) <= 4:
        errors.append(f"{c.type}: needs 1-4 y columns")
    if isinstance(c, Table) and not c.columns:
        errors.append("table: no columns")
    if isinstance(c, Kpi) and not errors:
        errors += [
            f"kpi: {e}" for e in [_lookup(results, query, c.value.column, c.value.row)[1]] if e
        ]
    return errors


def _check(spec: AnswerSpec, results, allowed: set[float], note_allowed: set[float]):
    values = _result_numbers(results)
    allowed = allowed | {float(c.top_n) for c in spec.components if isinstance(c, HBar) and c.top_n}
    prose = {}
    for key in ("text", "narrative"):
        filled, errors = _fill(getattr(spec, key), results)
        errors += [
            f"{key}: number {n!r} is not in the results; use a placeholder"
            for n in _unverified(getattr(spec, key), values, allowed)
        ]
        prose[key] = (filled, errors)
    comp_errors = [_component_errors(c, results, values, allowed) for c in spec.components]
    notes = {
        key: [
            (item, _unverified(item, values, allowed | note_allowed)) for item in getattr(spec, key)
        ]
        for key in ("assumptions", "limitations")
    }
    return prose, comp_errors, notes


def answer_errors(
    spec: AnswerSpec, results, allowed: set[float], note_allowed: set[float]
) -> list[str]:
    prose, comp_errors, notes = _check(spec, results, allowed, note_allowed)
    errors = [e for _, errs in prose.values() for e in errs]
    errors += [e for errs in comp_errors for e in errs]
    for key, items in notes.items():
        errors += [f"{key}: number {n!r} is not in the results" for _, bad in items for n in bad]
    return errors


def _auto_column(col: str, t: str) -> dict:
    return {
        "column": col,
        "label": col.replace("_", " ").capitalize(),
        "format": "number" if t in NUMERIC_TYPES else "text",
    }


def resolve_answer(
    spec: AnswerSpec, results, allowed: set[float], note_allowed: set[float]
) -> dict:
    """UI payload: invalid parts are dropped, never shown with unchecked figures."""
    prose, comp_errors, notes = _check(spec, results, allowed, note_allowed)
    (filled, text_errors), (narrative, narrative_errors) = prose["text"], prose["narrative"]
    limitations = [item for item, bad in notes["limitations"] if not bad]
    outcome = spec.outcome
    components = []
    for c, errs in zip(spec.components, comp_errors):
        if errs:
            continue
        out = c.model_dump()
        if isinstance(c, Kpi):
            out["value"] = _lookup(results, c.value.query, c.value.column, c.value.row)[0]
            out["ref"] = c.value.model_dump()
        if isinstance(c, HBar) and results[c.query].row_count > MAX_HBAR_ROWS:
            out["top_n"] = min(c.top_n or MAX_HBAR_ROWS, MAX_HBAR_ROWS)
        if isinstance(c, Table):
            # The SQL selects only what the answer needs, so a table never hides a result column.
            r, shown = results[c.query], {col.column for col in c.columns}
            out["columns"] += [
                _auto_column(col, t) for col, t in zip(r.columns, r.types) if col not in shown
            ]
        components.append(out)

    if results and all(r.row_count == 0 for r in results.values()):
        outcome = "no_results"
        components = [c for c in components if c["type"] == "callout"]
    if text_errors:
        filled = FALLBACK_TEXT
        limitations.append(FALLBACK_NOTE)
    if (
        outcome == "answered"
        and not any(c["type"] != "callout" for c in components)
        and (first := next((n for n, r in results.items() if r.row_count), None))
    ):
        r = results[first]
        components.append(
            {
                "type": "table",
                "title": "Results",
                "query": first,
                "columns": [_auto_column(col, t) for col, t in zip(r.columns, r.types)],
                "sort_column": None,
                "sort_desc": False,
                "filter_columns": [],
            }
        )

    return {
        "outcome": outcome,
        "text": filled,
        "narrative": "" if narrative_errors or outcome == "no_results" else narrative,
        "components": components,
        "assumptions": [item for item, bad in notes["assumptions"] if not bad],
        "limitations": limitations,
        "followups": spec.followups[:3],
    }
