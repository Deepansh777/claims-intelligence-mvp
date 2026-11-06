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
    return "sandbox allow-scripts; " + CSP.format(_viewer()[2])


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
        plan = TabPlan.model_validate(stored["plan"]) if stored.get("plan") else None
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
