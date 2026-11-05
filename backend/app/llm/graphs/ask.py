"""Ask workflow: plan SQL -> run it (up to 3 attempts) -> compose an AnswerSpec -> check it.

Ported from experimental/question_to_sql.py. The graph never touches the database: the
caller injects `run_query` (and `effort`) through config["configurable"].
"""

import json
import time
from pathlib import Path
from typing import TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from app.llm import client
from app.llm.guards import NUMERIC_TYPES, answer_errors, numbers_in
from app.llm.schemas import AnswerSpec, PlannedQuery, QueryError, QueryResult, SqlPlan

LLM_DIR = Path(__file__).resolve().parents[1]
DOCS = "\n\n".join(
    p.read_text() for p in sorted(LLM_DIR.glob("*.md")) if not p.stem.endswith("-notes")
)
# One stable prefix for both steps so the provider's prompt cache is reused.
SYSTEM = (LLM_DIR / "prompts" / "ask_system.md").read_text() + "\n\n" + DOCS
DOC_NUMBERS = numbers_in(DOCS)
MAX_SQL_ATTEMPTS = 3
MAX_COMPOSE_ATTEMPTS = 2
SAMPLE_ROWS = 50


class AskState(TypedDict, total=False):
    question: str
    network: str
    context: str
    plan: SqlPlan
    sql_attempts: int
    sql_error: str | None
    executions: list[dict]
    results: dict[str, QueryResult]
    spec: AnswerSpec
    spec_errors: list[str]
    compose_attempts: int


def _status(message: str) -> None:
    get_stream_writer()({"public": True, "message": message})


def allowed_numbers(state: AskState) -> set[float]:
    interpretation = state["plan"].interpretation
    return numbers_in(
        state["question"] + (interpretation.model_dump_json() if interpretation else "")
    )


def _describe(q: PlannedQuery, r: QueryResult) -> str:
    stats = {}
    for i, (col, typ) in enumerate(zip(r.columns, r.types)):
        values = [row[i] for row in r.rows if row[i] is not None]
        if typ in NUMERIC_TYPES and values:
            stats[col] = {
                "min": min(values),
                "max": max(values),
                "nulls": r.row_count - len(values),
            }
    truncated = f" (truncated at {r.row_count})" if r.truncated else ""
    return (
        f"Query {q.name} — {q.purpose}\nSQL:\n{q.sql}\n"
        f"Columns: {', '.join(f'{c} ({t})' for c, t in zip(r.columns, r.types))}\n"
        f"Rows: {r.row_count}{truncated}\n"
        f"First {min(SAMPLE_ROWS, r.row_count)} rows: {json.dumps(r.rows[:SAMPLE_ROWS], default=str)}\n"
        f"Numeric stats: {json.dumps(stats, default=str)}"
    )


async def plan(state: AskState, config: RunnableConfig) -> AskState:
    attempt = state.get("sql_attempts", 0) + 1
    _status(
        "Interpreting your question…"
        if attempt == 1
        else f"Fixing the query (attempt {attempt} of {MAX_SQL_ATTEMPTS})…"
    )
    prompt = f"Step: plan\nDefault network: {state['network']}\n"
    if state.get("context"):
        prompt += f"Previous analysis context (oldest first):\n{state['context']}\n\n"
    prompt += f"Question: {state['question']}"
    if state.get("sql_error"):
        failed = "\n\n".join(f"{q.name}:\n{q.sql}" for q in state["plan"].queries)
        prompt += f"\n\nYour previous SQL failed; fix it.\n{failed}\nError: {state['sql_error']}"
    effort = config["configurable"].get("effort", "medium")
    result = await client.call_structured(SqlPlan, SYSTEM, prompt, effort, config)
    return {"plan": result, "sql_attempts": attempt, "sql_error": None}


async def execute(
    queries: list[PlannedQuery], run_query, attempt: int, status=lambda message: None
) -> tuple[list[dict], dict[str, QueryResult], str | None]:
    """Run queries in order, stopping at the first failure. Returns executions, results, error."""
    executions, results = [], {}
    for i, q in enumerate(queries, 1):
        status(
            f"Running query {i} of {len(queries)}…" if len(queries) > 1 else "Running the query…"
        )
        started = time.monotonic()
        record = {
            "name": q.name,
            "purpose": q.purpose,
            "attempt": attempt,
            "sql": q.sql,
        }
        try:
            result = await run_query(q.sql)
        except QueryError as e:
            ms = round((time.monotonic() - started) * 1000)
            executions.append(
                {**record, "status": "failed", "error": str(e), "duration_ms": ms, "result": None}
            )
            return executions, results, f"{q.name}: {e}"
        ms = round((time.monotonic() - started) * 1000)
        executions.append(
            {**record, "status": "succeeded", "error": None, "duration_ms": ms, "result": result}
        )
        results[q.name] = result
    return executions, results, None


async def run_sql(state: AskState, config: RunnableConfig) -> AskState:
    new, results, error = await execute(
        state["plan"].queries[:3],
        config["configurable"]["run_query"],
        state["sql_attempts"],
        _status,
    )
    executions = state.get("executions", []) + new
    if error:
        return {"executions": executions, "sql_error": error}
    return {"executions": executions, "results": results}


async def compose(state: AskState, config: RunnableConfig) -> AskState:
    attempt = state.get("compose_attempts", 0) + 1
    _status("Preparing the answer…" if attempt == 1 else "Checking the figures…")
    p = state["plan"]
    parts = [f"Step: compose\nQuestion: {state['question']}"]
    if p.interpretation:
        parts.append(f"Interpretation: {p.interpretation.model_dump_json()}")
    parts += [_describe(q, state["results"][q.name]) for q in p.queries[:3]]
    if state.get("spec_errors"):
        parts.append(
            "Your previous answer had these problems; fix all of them:\n- "
            + "\n- ".join(state["spec_errors"])
            + f"\nPrevious answer:\n{state['spec'].model_dump_json()}"
        )
    effort = config["configurable"].get("effort", "medium")
    spec = await client.call_structured(AnswerSpec, SYSTEM, "\n\n".join(parts), effort, config)
    errors = answer_errors(spec, state["results"], allowed_numbers(state), DOC_NUMBERS)
    return {"spec": spec, "spec_errors": errors, "compose_attempts": attempt}


def _after_plan(s: AskState) -> str:
    return "run_sql" if s["plan"].action == "query" and s["plan"].queries else END


def _after_sql(s: AskState) -> str:
    if not s.get("sql_error"):
        return "compose"
    return "plan" if s["sql_attempts"] < MAX_SQL_ATTEMPTS else END


def _after_compose(s: AskState) -> str:
    return "compose" if s["spec_errors"] and s["compose_attempts"] < MAX_COMPOSE_ATTEMPTS else END


def build_graph():
    g = StateGraph(AskState)
    g.add_node("plan", plan)
    g.add_node("run_sql", run_sql)
    g.add_node("compose", compose)
    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", _after_plan)
    g.add_conditional_edges("run_sql", _after_sql)
    g.add_conditional_edges("compose", _after_compose)
    return g.compile()


graph = build_graph()
