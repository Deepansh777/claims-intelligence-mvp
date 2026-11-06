"""Dashboard outline and generation end to end, with a fake model and the live database."""

import json

from conftest import as_user, db

from app.llm.dashboard_schemas import (
    DashboardOutline,
    DashboardScope,
    DashboardTab,
    Finding,
    OutlineResult,
    ProviderSearch,
    TabOutline,
    TabPlan,
    Widget,
)
from app.llm.graphs.dashboard import scope_errors
from app.llm.guards import tab_errors
from app.llm.schemas import Interpretation, Kpi, PlannedQuery, QueryResult, Ref
from app.services import retention

PCP = db(
    "SELECT pcp_npi, pcp_group_tin, pcp_fullname FROM mart.nexus_pcp_roster "
    "ORDER BY member_months DESC LIMIT 1"
)[0]
SCOPE = DashboardScope(
    level="pcp",
    provider_name=PCP["pcp_fullname"],
    provider_npi=PCP["pcp_npi"],
    provider_tin=PCP["pcp_group_tin"],
    network="NEXUS",
    population=f"Members attributed to {PCP['pcp_fullname']}",
    period="2024-07-01 to 2026-06-30",
)
OUTLINE = DashboardOutline(
    title="Performance overview",
    filename="performance-overview",
    scope=SCOPE,
    tabs=[
        TabOutline(
            id="overview",
            name="Performance overview",
            question="How does PMPM compare with the attributed-PCP benchmark?",
            metrics=["PMPM"],
            visuals=["KPI"],
        )
    ],
)
PMPM_SQL = (
    "SELECT sum(total_allowed_amt) FILTER (WHERE pcp_npi = '{npi}') / NULLIF(sum(member_months) "
    "FILTER (WHERE pcp_npi = '{npi}'), 0) AS provider_pmpm, "
    "sum(total_allowed_amt) / NULLIF(sum(member_months), 0) AS benchmark_pmpm "
    "FROM mart.nexus_pcp_roster"
).format(npi=PCP["pcp_npi"])
INTERPRETATION = Interpretation(
    metric="PMPM",
    population="Attributed members",
    period="2024-07-01 to 2026-06-30",
    date_basis="Service month",
    grain="PCP",
    filters="None",
    denominator="Member months",
    sources="mart.nexus_pcp_roster",
)


def plan(sql=PMPM_SQL):
    return TabPlan(
        unsupported=None,
        interpretation=INTERPRETATION,
        queries=[PlannedQuery(name="q1", purpose="PMPM vs benchmark", sql=sql)],
    )


def tab(finding="Provider PMPM was {{q1.provider_pmpm|usd2}}."):
    kpi = Kpi(
        type="kpi",
        label="PMPM",
        value=Ref(query="q1", column="provider_pmpm", row="first"),
        format="usd2",
        sub=None,
    )
    return DashboardTab(
        id="overview",
        name="Performance overview",
        outcome="answered",
        takeaway="PMPM vs. benchmark {{q1.benchmark_pmpm|usd2}}.",
        findings=[
            Finding(
                finding=finding,
                evidence=["overview-pmpm"],
                clinical_context="",
                review_opportunity="",
                limitation="",
            )
        ],
        widgets=[Widget(id="overview-pmpm", component=kpi)],
        assumptions=[],
        limitations=[],
    )


def events(r):
    return [
        (
            block.split("\n")[0].removeprefix("event: "),
            json.loads(block.split("\n")[1].removeprefix("data: ")),
        )
        for block in r.text.strip().split("\n\n")
    ]


def generate(http, outline=OUTLINE):
    return http.post(
        "/api/v1/dashboards/stream",
        json={"request": "PMPM dashboard", "outline": outline.model_dump()},
    )


def test_outline_resolves_provider_and_rejects_invented_ids(http, llm):
    as_user()
    queue, prompts = llm
    invented = OUTLINE.model_copy(
        update={"scope": SCOPE.model_copy(update={"provider_npi": "0000000000"})}
    )
    queue += [
        ProviderSearch(action="search", message=None, options=[], terms=[PCP["pcp_fullname"]]),
        OutlineResult(action="outline", message=None, options=[], outline=invented),
        OutlineResult(action="outline", message=None, options=[], outline=OUTLINE),
    ]
    r = http.post(
        "/api/v1/dashboards/outline", json={"request": f"Dashboard for {PCP['pcp_fullname']}"}
    )

    assert r.status_code == 200 and r.json()["outline"]["scope"]["provider_npi"] == PCP["pcp_npi"]
    assert PCP["pcp_npi"] in prompts[1]  # roster candidates reached the model
    assert "must match a roster candidate" in prompts[2]


def test_outline_passes_through_decline(http, llm):
    as_user()
    llm[0].append(
        ProviderSearch(
            action="decline", message="Employer dashboards aren't supported.", options=[], terms=[]
        )
    )
    r = http.post("/api/v1/dashboards/outline", json={"request": "Dashboard for City of Derby"})
    assert r.json()["action"] == "decline" and r.json()["outline"] is None


def test_generate_builds_checks_and_saves_version(http, llm):
    as_user()
    llm[0].extend([plan(), tab()])
    r = generate(http)

    kinds = [k for k, _ in events(r)]
    result = events(r)[-1][1]
    assert set(kinds) == {"status", "result"} and result["outcome"] == "built"
    saved = http.get(f"/api/v1/dashboards/{result['dashboard_id']}").json()
    assert saved["version"] == 1 and saved["validation"]["overview"] == {
        "status": "ok",
        "errors": [],
    }
    assert saved["results"]["overview"]["q1"]["columns"] == ["provider_pmpm", "benchmark_pmpm"]
    assert saved["queries"]["overview"]["plan"]["queries"][0]["sql"] == PMPM_SQL
    assert saved["spec"]["tabs"][0]["widgets"][0]["id"] == "overview-pmpm"


def test_generate_repairs_unverified_figures(http, llm):
    as_user()
    queue, prompts = llm
    queue += [plan(), tab("Provider PMPM was $123,456.78."), tab()]
    result = events(generate(http))[-1][1]
    assert result["outcome"] == "built"
    assert "is not in the results; use a placeholder" in prompts[-1]


def test_failed_sql_saves_nothing(http, llm):
    as_user()
    llm[0].extend([plan("SELECT nope FROM mart.nexus_pcp_roster")] * 3)
    result = events(generate(http))[-1][1]
    assert result["outcome"] == "failed"


def test_generate_rejects_unknown_provider(http, llm):
    as_user()
    outline = OUTLINE.model_copy(
        update={"scope": SCOPE.model_copy(update={"provider_tin": "000000000"})}
    )
    r = generate(http, outline)
    assert r.status_code == 422 and r.json()["code"] == "invalid_outline"


def test_expired_dashboards_are_purged(http, llm):
    user = as_user()
    llm[0].extend([plan(), tab()])
    dashboard_id = events(generate(http))[-1][1]["dashboard_id"]
    db(
        "UPDATE app.dashboards SET updated_at = now() - interval '31 days' WHERE id = $1::uuid",
        dashboard_id,
    )

    assert http.get(f"/api/v1/dashboards/{dashboard_id}").status_code == 404
    http.portal.call(retention.purge_expired)
    assert (
        db("SELECT 1 FROM app.dashboard_versions WHERE dashboard_id = $1::uuid", dashboard_id) == []
    )
    assert user.startswith("test-")


def test_scope_errors():
    row = {"pcp_npi": "1", "pcp_group_tin": "9"}
    group = SCOPE.model_copy(
        update={"level": "pcp_group", "provider_npi": None, "provider_tin": "9"}
    )
    assert (
        scope_errors(SCOPE.model_copy(update={"provider_npi": "1", "provider_tin": "9"}), [row])
        == []
    )
    assert scope_errors(group, [row]) == []
    assert scope_errors(SCOPE.model_copy(update={"provider_npi": "1", "provider_tin": "8"}), [row])
    assert scope_errors(group.model_copy(update={"network": "PCN"}), [row])


def test_tab_errors_check_findings_and_widgets():
    results = {
        "q1": QueryResult(
            columns=["provider_pmpm", "benchmark_pmpm"],
            types=["numeric", "numeric"],
            rows=[[113.94, 175.85]],
            row_count=1,
            truncated=False,
        )
    }
    assert tab_errors(tab(), results, set(), set()) == []
    assert tab_errors(tab("PMPM was 113.94."), results, set(), set()) == []
    assert tab_errors(tab("PMPM was 999."), results, set(), set()) == [
        "finding 1 finding: number '999' is not in the results; use a placeholder"
    ]
    assert tab_errors(tab("{{q1.nope}}"), results, set(), set()) == [
        "finding 1 finding: placeholder {{q1.nope}}: column 'nope' not in q1"
    ]
    noted = tab().model_copy(update={"limitations": ["Benchmark {{q1.nope|usd2}}."]})
    assert tab_errors(noted, results, set(), set()) == [
        "limitations: placeholder {{q1.nope|usd2}}: column 'nope' not in q1"
    ]
