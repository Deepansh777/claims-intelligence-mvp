"""Structured LLM outputs for the provider dashboard builder.

Each tab reuses the Ask query and component types and has its own q1-q3 result namespace, so
the Ask guards check a tab exactly like an answer. Counts and uniqueness that strict structured
output can't express are checked by `structure_errors`.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.llm.schemas import Component, Interpretation, PlannedQuery

MAX_TABS = 3


class DashboardScope(BaseModel):
    level: Literal["pcp", "pcp_group"]
    provider_name: str
    provider_npi: str | None = Field(description="10-digit NPI for a PCP; null for a PCP group.")
    provider_tin: str = Field(description="9-digit group TIN.")
    network: str
    population: str = Field(description="Population basis, e.g. members attributed to this PCP.")
    period: str = Field(description="Exact reporting dates.")


class TabOutline(BaseModel):
    id: str = Field(description="Short stable slug, e.g. 'overview'.")
    name: str
    question: str = Field(description="The business question this tab answers.")
    metrics: list[str]
    visuals: list[str]


class DashboardOutline(BaseModel):
    title: str
    scope: DashboardScope
    tabs: list[TabOutline] = Field(description="1-3 tabs.")


class TabPlan(BaseModel):
    interpretation: Interpretation
    queries: list[PlannedQuery] = Field(description="1-3 queries.")


class Widget(BaseModel):
    id: str = Field(description="Stable slug, unique in the dashboard; keep it across edits.")
    component: Component


class Finding(BaseModel):
    finding: str = Field(
        description="Measure, period and population; figures only via placeholders."
    )
    evidence: list[str] = Field(description="Ids of this tab's widgets that support the finding.")
    clinical_context: str
    review_opportunity: str = Field(description="A question to review, or empty.")
    limitation: str = Field(description="What could change the interpretation, or empty.")


class DashboardTab(BaseModel):
    id: str = Field(description="The outline tab id.")
    name: str
    outcome: Literal["answered", "no_results", "unsupported"]
    takeaway: str = Field(description="1-2 sentences; figures only via {{q1.column[row]|format}}.")
    findings: list[Finding] = Field(description="0-4 material findings, most important first.")
    widgets: list[Widget]
    assumptions: list[str]
    limitations: list[str]


class DashboardSpec(BaseModel):
    title: str
    filename: str = Field(description="Descriptive kebab-case name without member identifiers.")
    tabs: list[DashboardTab] = Field(description="One per outline tab, in outline order.")


def structure_errors(outline: DashboardOutline, spec: DashboardSpec) -> list[str]:
    errors = []
    if not 1 <= len(outline.tabs) <= MAX_TABS:
        errors.append(f"outline: needs 1-{MAX_TABS} tabs")
    outline_ids = [t.id for t in outline.tabs]
    if len(set(outline_ids)) != len(outline_ids):
        errors.append("outline: tab ids must be unique")
    if [t.id for t in spec.tabs] != outline_ids:
        errors.append(f"tabs must match the outline tab ids in order: {outline_ids}")
    widget_ids = [w.id for t in spec.tabs for w in t.widgets]
    if dupes := sorted({i for i in widget_ids if widget_ids.count(i) > 1}):
        errors.append(f"widget ids must be unique: {dupes}")
    for t in spec.tabs:
        own = {w.id for w in t.widgets}
        for f in t.findings:
            if not f.evidence:
                errors.append(f"{t.id}: a finding cites no widget")
            errors += [
                f"{t.id}: finding cites unknown widget {i!r}" for i in f.evidence if i not in own
            ]
    return errors
