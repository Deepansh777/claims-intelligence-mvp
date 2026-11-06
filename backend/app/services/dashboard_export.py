"""Render a stored dashboard version as one self-contained, offline HTML file.

The page is our own pinned viewer bundle (frontend `npm run build:dashboard`) plus a checked,
resolved data snapshot. No model-written code reaches it: model text is rendered as text.
"""

import base64
import hashlib
import html
import json
import re
from functools import cache
from pathlib import Path

from app.llm.dashboard_schemas import DashboardOutline, DashboardSpec, TabPlan
from app.llm.graphs.ask import DOC_NUMBERS
from app.llm.graphs.dashboard import tab_allowed
from app.llm.guards import _bindings, resolve_tab
from app.llm.schemas import Kpi, QueryResult, Table

VIEWER_DIR = Path(__file__).resolve().parents[1] / "assets" / "dashboard-viewer"
CSP = (
    "default-src 'none'; script-src 'sha256-{}'; style-src 'unsafe-inline'; img-src data:; "
    "font-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'"
)


@cache
def _viewer() -> tuple[str, str, str]:
    # Neither may appear raw in inline script: both can stop the parser ending it at </script>.
    js = (
        (VIEWER_DIR / "dashboard.js")
        .read_text()
        .replace("</script", "<\\/script")
        .replace("<!--", "<\\!--")
    )
    css = (VIEWER_DIR / "dashboard.css").read_text().replace("</style", "<\\/style")
    digest = base64.b64encode(hashlib.sha256(js.encode()).digest()).decode()
    return js, css, digest


def response_csp() -> str:
    """Header for the served file: an opaque origin even when opened straight from the API."""
    return "sandbox allow-scripts allow-downloads; " + CSP.format(_viewer()[2])


def _json_for_html(data: dict) -> str:
    """JSON that can't close its <script> element or be read as markup."""
    text = json.dumps(data, default=str, ensure_ascii=False)
    for ch, esc in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e")):
        text = text.replace(ch, esc)
    return text.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def filename(raw: str) -> str:
    """Kebab-case `.html` name; long digit runs (NPIs, TINs, member ids) are removed."""
    stem = re.sub(r"\.html?$", "", raw.strip(), flags=re.IGNORECASE).lower()
    stem = re.sub(r"\d{5,}", "", stem)
    stem = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")[:80].strip("-")
    return f"{stem or 'provider-dashboard'}.html"


def _project(result: QueryResult, components: list) -> dict:
    """Only the columns the visuals show; a table shows every column of its query."""
    if any(isinstance(c, Table) for c in components):
        return result.model_dump()
    keep = [
        i for i, col in enumerate(result.columns) if any(col in _bindings(c)[1] for c in components)
    ]
    return {
        **result.model_dump(),
        "columns": [result.columns[i] for i in keep],
        "types": [result.types[i] for i in keep],
        "rows": [[row[i] for i in keep] for row in result.rows],
    }


def payload(v: dict) -> dict:
    """Display payload for a version row: resolved tabs and only the data they display."""
    outline = DashboardOutline.model_validate(v["outline"])
    spec = DashboardSpec.model_validate(v["spec"])
    questions = {t.id: t.question for t in outline.tabs}
    tabs, datasets = [], {}
    for t in spec.tabs:
        stored = v["queries"].get(t.id) or {}
        # Plans saved before Python analysis existed have no `analysis`.
        plan = (
            TabPlan.model_validate({"analysis": [], **stored["plan"]})
            if stored.get("plan")
            else None
        )
        results = {n: QueryResult.model_validate(r) for n, r in v["results"].get(t.id, {}).items()}
        tab = resolve_tab(t, results, tab_allowed(v["request"], outline, plan), DOC_NUMBERS)
        kept = {w["id"] for w in tab["widgets"]}
        by_query: dict[str, list] = {}
        for w in t.widgets:
            if w.id in kept and not isinstance(w.component, Kpi) and hasattr(w.component, "query"):
                by_query.setdefault(w.component.query, []).append(w.component)
        datasets[t.id] = {n: _project(results[n], cs) for n, cs in by_query.items()}
        tab["question"] = questions.get(t.id, "")
        tab["methodology"] = {
            "interpretation": plan.interpretation.model_dump()
            if plan and plan.interpretation
            else None,
            "queries": [q.model_dump() for q in plan.queries[:3]] if plan else [],
        }
        tabs.append(tab)
    return {
        "title": spec.title,
        "scope": outline.scope.model_dump(),
        "version": v["version"],
        "generated_at": v["created_at"],
        "dataset_loaded_at": v.get("dataset_loaded_at"),
        "tabs": tabs,
        "datasets": datasets,
    }


INTERPRETATION_LABELS = {
    "metric": "Metric",
    "population": "Population",
    "period": "Period",
    "date_basis": "Date basis",
    "grain": "Grain",
    "filters": "Filters",
    "denominator": "Denominator",
    "sources": "Data sources",
}


def _md(text) -> str:
    """One line of model or user text, safe inside a list item or table cell."""
    return " ".join(str(text).split()).replace("|", "\\|")


def _md_table(rows: list[tuple[str, str]]) -> list[str]:
    return ["| Item | Detail |", "| --- | --- |"] + [f"| {k} | {_md(v)} |" for k, v in rows if v]


def _md_list(title: str, items: list[str]) -> list[str]:
    return [f"### {title}", "", *[f"- {_md(i)}" for i in items], ""] if items else []


def _executed(v: dict, tab: dict) -> list[dict]:
    """The final attempt's successful queries for a tab: the SQL behind what it shows."""
    runs = (v["queries"].get(tab["id"]) or {}).get("executions") or []
    last = max((e["attempt"] for e in runs), default=0)
    results = v["results"].get(tab["id"], {})
    return [
        {
            "tab": tab["name"],
            "name": e["name"],
            "purpose": e["purpose"],
            "sql": e["sql"],
            "row_count": results.get(e["name"], {}).get("row_count"),
            "duration_ms": e["duration_ms"],
        }
        for e in runs
        if e["attempt"] == last and e["status"] == "succeeded"
    ]


def methodology(v: dict) -> dict:
    """Markdown methodology and executed SQL, built from what the version stores."""
    p = payload(v)
    s = p["scope"]
    ids = f"TIN {s['provider_tin']}"
    if s["provider_npi"]:
        ids = f"NPI {s['provider_npi']}, {ids}"
    # Dates arrive as datetimes from the database and as ISO strings in tests.
    loaded = (
        f" from data loaded {str(p['dataset_loaded_at'])[:10]}" if p["dataset_loaded_at"] else ""
    )
    lines = [
        f"# {_md(p['title'])}",
        "",
        f"Generated {str(p['generated_at'])[:10]}{loaded}, version {p['version']}.",
        "",
        "## Scope",
        "",
        *_md_table(
            [
                ("Provider", f"{s['provider_name']} ({ids})"),
                ("Network", s["network"]),
                ("Population", s["population"]),
                ("Reporting period", s["period"]),
                ("Request", v["request"]),
            ]
        ),
        "",
    ]
    queries, scripts = [], []
    for tab in p["tabs"]:
        executed = _executed(v, tab)
        queries += executed
        ran = [
            {"tab": tab["name"], **s}
            for s in (v["queries"].get(tab["id"]) or {}).get("scripts", [])
        ]
        scripts += ran
        interp = tab["methodology"]["interpretation"] or {}
        lines += [
            f"## {_md(tab['name'])}",
            "",
            *_md_table(
                [("Question", tab["question"])]
                + (
                    [("Outcome", tab.get("narrative", tab.get("takeaway")))]
                    if tab["outcome"] != "answered"
                    else []
                )
                + [(label, interp.get(k)) for k, label in INTERPRETATION_LABELS.items()]
            ),
            "",
            *_md_list("Assumptions", tab["assumptions"]),
            *_md_list("Limitations", tab["limitations"]),
            *_md_list(
                "Queries",
                [f"{q['name']}: {q['purpose']} ({q['row_count']} rows)" for q in executed],
            ),
            *_md_list(
                "Python analysis",
                [
                    f"{s['purpose']} ({'ran' if s['status'] == 'succeeded' else 'failed'})"
                    for s in ran
                ],
            ),
        ]
    return {"markdown": "\n".join(lines).rstrip() + "\n", "queries": queries, "scripts": scripts}


def render_html(p: dict) -> str:
    js, css, digest = _viewer()
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{CSP.format(digest)}">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(p['title'])}</title>\n<style>{css}</style>\n</head>\n<body>\n"
        '<div id="root"></div>\n'
        f'<script type="application/json" id="dashboard-data">{_json_for_html(p)}</script>\n'
        f"<script>{js}</script>\n</body>\n</html>\n"
    )
