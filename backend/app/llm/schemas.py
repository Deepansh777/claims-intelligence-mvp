"""Structured LLM outputs for the Ask workflow, and the query results they are checked against.

No defaults on LLM-facing fields: OpenAI strict structured output requires every field.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

Format = Literal["usd", "usd2", "int", "number", "pct", "pct_ratio", "rate", "text", "date"]


class Interpretation(BaseModel):
    metric: str
    population: str = Field(description="Network/cohort, noting when the default network was used.")
    period: str = Field(description="Exact dates or months covered.")
    date_basis: str
    grain: str
    filters: str = Field(description="Filters applied, or 'None'.")
    denominator: str
    sources: str = Field(description="Tables used.")


class PlannedQuery(BaseModel):
    name: Literal["q1", "q2", "q3"]
    purpose: str
    sql: str = Field(description="One PostgreSQL SELECT/WITH statement.")


class SqlPlan(BaseModel):
    action: Literal["query", "explain", "clarify", "decline"]
    message: str | None = Field(
        description="Explanation (explain), question (clarify) or polite decline; null for query."
    )
    options: list[str] = Field(description="2-4 short clickable answers for clarify; else empty.")
    interpretation: Interpretation | None = Field(description="Required for query; else null.")
    queries: list[PlannedQuery] = Field(description="1-3 queries for query; else empty.")


class Ref(BaseModel):
    query: str
    column: str
    row: str = Field(description='"first", "last", or a 0-based row index such as "3".')


class Kpi(BaseModel):
    type: Literal["kpi"]
    label: str
    value: Ref
    format: Format
    sub: str | None


class SeriesChart(BaseModel):
    type: Literal["line", "bar"]
    title: str
    query: str
    x: str
    y: list[str] = Field(description="1-4 numeric columns, one series each.")
    format: Format


class HBar(BaseModel):
    type: Literal["hbar"]
    title: str
    query: str
    label: str
    value: str
    format: Format
    top_n: int | None = Field(description="Show only the first N rows (max 25); null for all.")


class Scatter(BaseModel):
    type: Literal["scatter"]
    title: str
    query: str
    x: str
    y: str
    label: str | None = Field(description="Column naming each point, shown on hover.")
    tooltip: list[str] = Field(description="Extra columns shown on hover.")
    x_format: Format
    y_format: Format


class TableColumn(BaseModel):
    column: str
    label: str
    format: Format


class Table(BaseModel):
    type: Literal["table"]
    title: str
    query: str
    columns: list[TableColumn]
    sort_column: str | None
    sort_desc: bool
    filter_columns: list[str] = Field(description="Columns the user can filter by (categorical).")


class Callout(BaseModel):
    type: Literal["callout"]
    tone: Literal["info", "warn"]
    text: str


# No discriminator: it emits "oneOf", which OpenAI structured output rejects; the type literals still pick the model.
Component = Kpi | SeriesChart | HBar | Scatter | Table | Callout


class AnswerSpec(BaseModel):
    outcome: Literal["answered", "no_results", "unsupported"]
    text: str = Field(description="1-3 sentences; figures only via {{q1.column[row]|format}}.")
    narrative: str = Field(
        description="2-4 sentences interpreting the result, or empty; figures only via placeholders."
    )
    components: list[Component]
    assumptions: list[str]
    limitations: list[str]
    followups: list[str] = Field(description="Up to 3 short follow-up questions.")


class QueryError(Exception):
    """SQL was rejected or failed; the message goes back to the model, never to the user."""


class QueryResult(BaseModel):
    columns: list[str]
    types: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
