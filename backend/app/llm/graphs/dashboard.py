"""Dashboard workflow.

`outline`: extract provider search terms -> look them up in the roster -> propose an outline the
user can edit. `graph`: per tab, in parallel, plan SQL -> run it (up to 3 attempts) -> run any
planned Python analysis on the results -> compose the tab -> check it (up to 2 attempts). Like
Ask, nothing here touches the database or runs code: the caller injects `run_query`,
`run_python` and `find_providers` through config["configurable"].
"""

import json
import logging
from pathlib import Path
from typing import Annotated, TypedDict

from langchain_core.exceptions import ModelConnectionError
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.llm import client
from app.llm.dashboard_schemas import (
    DashboardOutline,
    DashboardScope,
    DashboardTab,
    OutlineResult,
    ProviderSearch,
    TabOutline,
    TabPlan,
    outline_errors,
    tab_structure_errors,
)
from app.llm.graphs.ask import DOC_NUMBERS, DOCS, MAX_COMPOSE_ATTEMPTS, MAX_SQL_ATTEMPTS, execute
from app.llm.graphs.ask import _describe as describe
from app.llm.guards import numbers_in, tab_errors

log = logging.getLogger(__name__)

SYSTEM = (
    (Path(__file__).resolve().parents[1] / "prompts" / "dashboard_system.md").read_text()
    + "\n\n"
    + DOCS
)
MAX_OUTLINE_ATTEMPTS = 2
MAX_SCRIPTS = 2
NO_PROVIDER = "Which PCP or PCP group should the dashboard cover? A name, NPI or TIN works."
OUTLINE_FAILED = (
    "I couldn't match that request to one NEXUS PCP. Which provider (name, NPI or TIN)?"
)
TAB_CONNECTION_FAILED = "Lost the connection to the model while building this tab."


def scope_errors(scope: DashboardScope, candidates: list[dict]) -> list[str]:
    """The scope must name a real roster PCP (NPI + TIN) or group (TIN); never trust the model."""
    if scope.network != "NEXUS":
        return ["scope: network must be NEXUS"]
    if scope.level == "pcp":
        ok = any(
            c["pcp_npi"] == scope.provider_npi and c["pcp_group_tin"] == scope.provider_tin
            for c in candidates
        )
    else:
        ok = scope.provider_npi is None and any(
            c["pcp_group_tin"] == scope.provider_tin for c in candidates
        )
    return [] if ok else ["scope: provider NPI/TIN must match a roster candidate exactly"]


async def outline(request: str, user_tabs: list[dict], config: RunnableConfig) -> OutlineResult:
    effort = config["configurable"].get("effort", "medium")
    ask = f"Request: {request}"
    if user_tabs:
        ask += "\nUser-defined tabs:" + "".join(
            f"\n- {t['name']}: {t['description']}" for t in user_tabs
        )
    search = await client.call_structured(
        ProviderSearch, SYSTEM, f"Step: search\n{ask}", effort, config
    )
    if search.action != "search" or not search.terms:
        return OutlineResult(
            action="decline" if search.action == "decline" else "clarify",
            message=search.message or NO_PROVIDER,
            options=search.options[:4],
            outline=None,
        )
    candidates = await config["configurable"]["find_providers"](search.terms)
    prompt = f"Step: outline\n{ask}\nRoster candidates: {json.dumps(candidates, default=str)}"
    for _ in range(MAX_OUTLINE_ATTEMPTS):
        result = await client.call_structured(OutlineResult, SYSTEM, prompt, effort, config)
        if result.action != "outline":
            return result.model_copy(update={"options": result.options[:4], "outline": None})
        errors = (
            ["outline: required for action outline"]
            if result.outline is None
            else outline_errors(result.outline) + scope_errors(result.outline.scope, candidates)
        )
        if not errors:
            return result
        prompt += "\n\nYour previous outline had problems; fix all of them:\n- " + "\n- ".join(
            errors
        )
    return OutlineResult(action="clarify", message=OUTLINE_FAILED, options=[], outline=None)


def _merge(a: dict, b: dict) -> dict:
    return {**(a or {}), **(b or {})}


class GenState(TypedDict, total=False):
    request: str
    outline: DashboardOutline
    tabs: Annotated[dict[str, dict], _merge]


class TabState(TypedDict):
    request: str
    outline: DashboardOutline
    tab: TabOutline


def tab_allowed(request: str, outline: DashboardOutline, plan: TabPlan | None) -> set[float]:
    """Numbers a tab may state outright: those the user wrote or the outline/interpretation hold."""
    text = request + outline.model_dump_json()
    if plan and plan.interpretation:
        text += plan.interpretation.model_dump_json()
    return numbers_in(text)


def _status(message: str, step: str) -> None:
    """`step` names the progress step (tab id and phase) that the message belongs to."""
    get_stream_writer()({"public": True, "message": message, "step": step})


def _empty_tab() -> dict:
    return {
        "plan": None,
        "executions": [],
        "scripts": [],
        "results": {},
        "spec": None,
        "errors": [],
    }


async def build_tab(s: TabState, config: RunnableConfig) -> GenState:
    """Contains a dropped model connection: tabs fan out in parallel and one raise kills them all."""
    try:
        return await _build_tab(s, config)
    except ModelConnectionError:
        log.exception("Tab build lost the model connection", extra={"tab": s["tab"].id})
        return {"tabs": {s["tab"].id: {**_empty_tab(), "errors": [TAB_CONNECTION_FAILED]}}}


async def _build_tab(s: TabState, config: RunnableConfig) -> GenState:
    """Returns {"tabs": {id: {...}}}; `spec` is None when every SQL attempt failed."""
    t, effort = s["tab"], config["configurable"].get("effort", "medium")
    others = "".join(f"\n- {o.name}: {o.question}" for o in s["outline"].tabs if o.id != t.id)
    head = (
        f"Scope: {s['outline'].scope.model_dump_json()}\nTab: {t.model_dump_json()}\n"
        f"Dashboard request: {s['request']}"
        + (f"\nOther tabs cover (leave their topics to them):{others}" if others else "")
    )
    executions, results, error, plan = [], {}, None, None
    for attempt in range(1, MAX_SQL_ATTEMPTS + 1):
        _status(
            f"{t.name}: planning the analysis…"
            if attempt == 1
            else f"{t.name}: fixing the query (attempt {attempt} of {MAX_SQL_ATTEMPTS})…",
            f"{t.id}:plan",
        )
        prompt = f"Step: plan\n{head}"
        if error:
            failed = "\n\n".join(f"{q.name}:\n{q.sql}" for q in plan.queries)
            prompt += f"\n\nYour previous SQL failed; fix it.\n{failed}\nError: {error}"
        plan = await client.call_structured(TabPlan, SYSTEM, prompt, effort, config)
        if plan.unsupported or not plan.queries:
            break
        new, results, error = await execute(
            plan.queries[:3],
            config["configurable"]["run_query"],
            attempt,
            lambda m: _status(f"{t.name}: {m[0].lower()}{m[1:]}", f"{t.id}:query"),
        )
        executions += new
        if not error:
            break
    out = {**_empty_tab(), "plan": plan, "executions": executions}
    allowed = tab_allowed(s["request"], s["outline"], plan)

    if plan.unsupported or not plan.queries:
        spec = DashboardTab(
            id=t.id,
            name=t.name,
            outcome="unsupported",
            widgets=[],
            insights=[],
            grid=[],
            narrative=plan.unsupported or "The available data can't answer this tab's question.",
            assumptions=[],
            limitations=[],
        )
        return {
            "tabs": {t.id: {**out, "spec": spec, "errors": tab_errors(spec, {}, allowed, set())}}
        }
    if error:
        return {"tabs": {t.id: {**out, "errors": [error]}}}

    for script in plan.analysis[:MAX_SCRIPTS]:
        _status(f"{t.name}: running the Python analysis…", f"{t.id}:query")
        ran = await config["configurable"]["run_python"](script.code, results)
        out["scripts"].append({"purpose": script.purpose, "code": script.code, **ran})

    errors, spec = [], None
    for attempt in range(1, MAX_COMPOSE_ATTEMPTS + 1):
        _status(
            f"{t.name}: writing the findings…"
            if attempt == 1
            else f"{t.name}: checking the figures…",
            f"{t.id}:compose",
        )
        parts = [f"Step: compose\n{head}"]
        if plan.interpretation:
            parts.append(f"Interpretation: {plan.interpretation.model_dump_json()}")
        parts += [describe(q, results[q.name]) for q in plan.queries[:3]]
        parts += [
            f"Python analysis ({s['status']}): {s['purpose']}\nOutput:\n{s['output']}"
            for s in out["scripts"]
        ]
        if errors:
            parts.append(
                "Your previous tab had these problems; fix all of them:\n- "
                + "\n- ".join(errors)
                + f"\nPrevious tab:\n{spec.model_dump_json()}"
            )
        spec = await client.call_structured(
            DashboardTab, SYSTEM, "\n\n".join(parts), effort, config
        )
        spec = spec.model_copy(update={"id": t.id, "name": t.name})
        errors = tab_structure_errors(spec, t.id) + tab_errors(spec, results, allowed, DOC_NUMBERS)
        if not errors:
            break
    return {"tabs": {t.id: {**out, "results": results, "spec": spec, "errors": errors}}}


def _fan_out(s: GenState) -> list[Send]:
    return [
        Send("tab", {"request": s["request"], "outline": s["outline"], "tab": t})
        for t in s["outline"].tabs
    ]


def build_graph():
    g = StateGraph(GenState)
    g.add_node("tab", build_tab)
    g.add_conditional_edges(START, _fan_out, ["tab"])
    g.add_edge("tab", END)
    return g.compile()


graph = build_graph()
