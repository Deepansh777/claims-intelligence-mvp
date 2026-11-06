import { useState, type ReactNode } from "react";
import { HBarView, ScatterView, SeriesChartView } from "../components/answer/Charts";
import { DataTable } from "../components/answer/DataTable";
import { KpiGrid } from "../components/answer/KpiGrid";
import { Icon } from "../components/Icon";
import { formatDate } from "../lib/format";
import type {
  Component,
  Dataset,
  DashboardInsight,
  DashboardPayload,
  DashboardTab,
  DashboardWidget,
  GridDashboardTab,
  Kpi,
  LegacyDashboardTab,
} from "../lib/types";
import logoUrl from "../assets/logo.png";

const INTERPRETATION_LABELS: Record<string, string> = {
  metric: "Metric",
  population: "Population",
  period: "Period",
  date_basis: "Date basis",
  grain: "Grain",
  filters: "Filters",
  denominator: "Denominator",
  sources: "Sources",
};

function widgetBody(c: Exclude<Component, Kpi>, data: Record<string, Dataset>): ReactNode {
  if (c.type === "callout")
    return (
      <div className={`banner banner--${c.tone}`}>
        <Icon name={c.tone === "info" ? "info" : "warn"} />
        <span>{c.text}</span>
      </div>
    );
  const d = data[c.query];
  if (!d) return null;
  return c.type === "table" ? <DataTable spec={c} data={d} /> :
    c.type === "hbar" ? <HBarView spec={c} data={d} /> :
    c.type === "scatter" ? <ScatterView spec={c} data={d} /> :
    <SeriesChartView spec={c} data={d} />;
}

function kpiGrid(kpis: DashboardWidget[]) {
  return <KpiGrid key={kpis[0].id} kpis={kpis.map((w) => w.component as Kpi)} ids={kpis.map((w) => `w-${w.id}`)} />;
}

/** Consecutive KPIs share one grid; everything else renders in order. */
function Widgets({ widgets, data }: { widgets: DashboardWidget[]; data: Record<string, Dataset> }) {
  const out: ReactNode[] = [];
  let kpis: DashboardWidget[] = [];
  const flush = () => {
    if (kpis.length) out.push(kpiGrid(kpis));
    kpis = [];
  };
  widgets.forEach((w) => {
    const c = w.component;
    if (c.type === "kpi") return void kpis.push(w);
    flush();
    const body = widgetBody(c, data);
    if (body) out.push(<div key={w.id} id={`w-${w.id}`} data-widget-id={w.id}>{body}</div>);
  });
  flush();
  return <>{out}</>;
}

const INSIGHT_STATUS = {
  adverse: { icon: "warn", label: "Needs attention" },
  favorable: { icon: "check", label: "Favorable" },
  neutral: { icon: "info", label: "Note" },
} as const;

function InsightCard({ insight }: { insight: DashboardInsight }) {
  const s = INSIGHT_STATUS[insight.status];
  return (
    <article className={`dash-insight dash-insight--${insight.status}`}>
      <div className="dash-insight-status">
        <Icon name={s.icon} />
        {insight.label || s.label}
      </div>
      <p className="dash-insight-finding">{insight.finding}</p>
      {insight.next_step && (
        <p><span className="dash-label">Next step</span>{insight.next_step}</p>
      )}
    </article>
  );
}

/** KPI row, then up to 3 rows of up to 3 visuals or insights, then the full-width narrative. */
function GridLayout({ tab, data }: { tab: GridDashboardTab; data: Record<string, Dataset> }) {
  const items = new Map<string, ReactNode>();
  tab.widgets.forEach((w) => w.component.type !== "kpi" && items.set(w.id, widgetBody(w.component, data)));
  tab.insights.forEach((i) => items.set(i.id, <InsightCard insight={i} />));
  const kpis = tab.widgets.filter((w) => w.component.type === "kpi");
  return (
    <>
      {kpis.length > 0 && kpiGrid(kpis)}
      {tab.grid.map((row, r) => (
        <div key={r} className={`dash-row dash-row--${row.length}`}>
          {row.map((id) => items.get(id) && (
            <div key={id} id={`w-${id}`} data-widget-id={id}>{items.get(id)}</div>
          ))}
        </div>
      ))}
      <section className="card dash-narrative" aria-label="Summary">
        <h2 className="dash-label">Summary</h2>
        <p className={tab.outcome !== "answered" ? "dash-takeaway--muted" : ""}>{tab.narrative}</p>
      </section>
    </>
  );
}

function widgetTitle(w: DashboardWidget | undefined) {
  if (!w) return "";
  const c = w.component;
  return c.type === "kpi" ? c.label : c.type === "callout" ? "Note" : c.title;
}

function Findings({ tab }: { tab: LegacyDashboardTab }) {
  if (!tab.findings.length) return null;
  const byId = Object.fromEntries(tab.widgets.map((w) => [w.id, w]));
  return (
    <section className="dash-findings" aria-label="Findings">
      {tab.findings.map((f, i) => (
        <article className="card dash-finding" key={i}>
          <p className="dash-finding-text">{f.finding}</p>
          {f.clinical_context && (
            <p><span className="dash-label">Clinical context</span>{f.clinical_context}</p>
          )}
          {f.review_opportunity && (
            <p><span className="dash-label">Review opportunity</span>{f.review_opportunity}</p>
          )}
          {f.limitation && (
            <p className="muted"><span className="dash-label">Limitation</span>{f.limitation}</p>
          )}
          <div className="dash-evidence">
            Evidence:{" "}
            {f.evidence.map((id) => (
              <a key={id} href={`#w-${id}`} className="pill">
                {widgetTitle(byId[id])}
              </a>
            ))}
          </div>
        </article>
      ))}
    </section>
  );
}

function Methodology({ tab }: { tab: DashboardTab }) {
  const m = tab.methodology;
  return (
    <details className="card dash-methodology">
      <summary>Methodology and data details</summary>
      {m.interpretation && (
        <dl className="dl">
          {Object.entries(INTERPRETATION_LABELS)
            .filter(([k]) => m.interpretation![k])
            .map(([k, label]) => (
              <div key={k} style={{ display: "contents" }}>
                <dt>{label}</dt>
                <dd>{m.interpretation![k]}</dd>
              </div>
            ))}
        </dl>
      )}
      {tab.assumptions.length > 0 && (
        <>
          <div className="va-section-title">Assumptions</div>
          <ul className="va-list">{tab.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
        </>
      )}
      {m.queries.map((q) => (
        <div key={q.name}>
          <div className="va-section-title">{q.name} · {q.purpose}</div>
          <pre className="dash-sql">{q.sql}</pre>
        </div>
      ))}
    </details>
  );
}

function TabPanel({ tab, data }: { tab: DashboardTab; data: Record<string, Dataset> }) {
  return (
    <div className="dash-panel">
      <p className="dash-question">{tab.question}</p>
      {"grid" in tab ? (
        <GridLayout tab={tab} data={data} />
      ) : (
        <>
          <p className={"dash-takeaway" + (tab.outcome !== "answered" ? " dash-takeaway--muted" : "")}>{tab.takeaway}</p>
          <Findings tab={tab} />
          <Widgets widgets={tab.widgets} data={data} />
        </>
      )}
      {tab.limitations.length > 0 && (
        <div className="banner banner--warn">
          <Icon name="warn" />
          <ul className="dash-notes">{tab.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
        </div>
      )}
      <Methodology tab={tab} />
    </div>
  );
}

export function DashboardDocument({ dashboard }: { dashboard: DashboardPayload }) {
  const [active, setActive] = useState(0);
  const s = dashboard.scope;
  const tab = dashboard.tabs[active];
  const identity = s.level === "pcp" ? `NPI ${s.provider_npi} · TIN ${s.provider_tin}` : `PCP group · TIN ${s.provider_tin}`;
  return (
    <div className="dash">
      <header className="dash-header">
        <img className="dash-logo" src={logoUrl} alt="ProviDRs Care" />
        <div>
          <h1 className="dash-title">{dashboard.title}</h1>
          <div className="dash-meta">
            <span><strong>{s.provider_name}</strong> · {identity} · {s.network}</span>
            <span>{s.population}</span>
          </div>
        </div>
        <div className="dash-period">
          <span className="dash-label">Reporting period</span>
          {s.period}
        </div>
      </header>
      {dashboard.tabs.length > 1 && (
        <div className="subtabs dash-tabs" role="tablist">
          {dashboard.tabs.map((t, i) => (
            <button
              key={t.id}
              role="tab"
              id={`tab-${t.id}`}
              aria-selected={i === active}
              aria-controls={`panel-${t.id}`}
              className={"subtab" + (i === active ? " active" : "")}
              onClick={() => setActive(i)}
            >
              {t.name}
            </button>
          ))}
        </div>
      )}
      <main role="tabpanel" id={`panel-${tab.id}`} aria-labelledby={`tab-${tab.id}`}>
        <TabPanel key={tab.id} tab={tab} data={dashboard.datasets[tab.id] ?? {}} />
      </main>
      <footer className="dash-footer">
        Snapshot generated {formatDate(dashboard.generated_at)}
        {dashboard.dataset_loaded_at ? ` from data loaded ${formatDate(dashboard.dataset_loaded_at)}` : ""} · version{" "}
        {dashboard.version}. Figures are fixed at generation time; this file does not connect to live data.
      </footer>
    </div>
  );
}
