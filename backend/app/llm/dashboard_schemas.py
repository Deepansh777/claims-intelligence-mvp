"""Structured LLM outputs for the provider dashboard builder.

Each tab reuses the Ask query and component types and has its own q1-q3 result namespace, so
the Ask guards check a tab exactly like an answer. Counts and uniqueness that strict structured
output can't express are checked here.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.llm.schemas import Component, Interpretation, PlannedQuery

MAX_TABS = 3


class ProviderSearch(BaseModel):
    action: Literal["search", "clarify", "decline"]
    message: str | None = Field(description="Question (clarify) or polite decline; else null.")
    options: list[str] = Field(description="2-4 short clickable answers for clarify; else empty.")
    terms: list[str] = Field(
        description="For search: provider or group names, NPIs or TINs from the request."
    )


class DashboardScope(BaseModel):
    level: Literal["pcp", "pcp_group"]
    provider_name: str
    provider_npi: str | None = Field(description="10-digit NPI for a PCP; null for a PCP group.")
    provider_tin: str = Field(description="9-digit group TIN.")
    network: str
    population: str = Field(description="Population basis, e.g. members attributed to this PCP.")
    period: str = Field(description="Exact reporting dates.")


class TabOutline(BaseModel):
    id: str = Field(description="Short lowercase slug, e.g. 'overview'.")
    name: str
    question: str = Field(description="The business question this tab answers.")
    metrics: list[str]
    visuals: list[str]


class DashboardOutline(BaseModel):
    title: str
    filename: str = Field(description="Descriptive kebab-case name without member identifiers.")
    scope: DashboardScope
    tabs: list[TabOutline] = Field(description="1-3 tabs.")


class OutlineResult(BaseModel):
    action: Literal["outline", "clarify", "decline"]
    message: str | None = Field(description="Question (clarify) or polite decline; else null.")
    options: list[str] = Field(description="2-4 short clickable answers for clarify; else empty.")
    outline: DashboardOutline | None = Field(description="Required for outline; else null.")


class TabPlan(BaseModel):
    unsupported: str | None = Field(
        description="Why the data can't answer this tab, with a supported alternative; else null."
    )
    interpretation: Interpretation | None = Field(description="Null when unsupported.")
    queries: list[PlannedQuery] = Field(description="1-3 queries; empty when unsupported.")


class Widget(BaseModel):
    id: str = Field(description="'<tab id>-<slug>', unique in the dashboard; keep it across edits.")
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
    tabs: list[DashboardTab]


def outline_errors(outline: DashboardOutline) -> list[str]:
    errors = []
    if not 1 <= len(outline.tabs) <= MAX_TABS:
        errors.append(f"outline: needs 1-{MAX_TABS} tabs")
    ids = [t.id for t in outline.tabs]
    if len(set(ids)) != len(ids):
        errors.append("outline: tab ids must be unique")
    return errors


def tab_structure_errors(tab: DashboardTab, tab_id: str) -> list[str]:
    errors = [] if tab.id == tab_id else [f"tab id must be {tab_id!r}"]
    ids = [w.id for w in tab.widgets]
    errors += [
        f"widget id {i!r} must start with '{tab_id}-'"
        for i in ids
        if not i.startswith(f"{tab_id}-")
    ]
    if len(set(ids)) != len(ids):
        errors.append("widget ids must be unique")
    for f in tab.findings:
        if not f.evidence:
            errors.append("a finding cites no widget")
        errors += [f"finding cites unknown widget {i!r}" for i in f.evidence if i not in ids]
    return errors


def structure_errors(outline: DashboardOutline, spec: DashboardSpec) -> list[str]:
    errors = outline_errors(outline)
    outline_ids = [t.id for t in outline.tabs]
    if [t.id for t in spec.tabs] != outline_ids:
        errors.append(f"tabs must match the outline tab ids in order: {outline_ids}")
    for t in spec.tabs:
        errors += [f"{t.id}: {e}" for e in tab_structure_errors(t, t.id)]
    return errors
