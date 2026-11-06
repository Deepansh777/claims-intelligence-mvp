import { useState, type ReactNode } from "react";
import { HBarView, ScatterView, SeriesChartView } from "../components/answer/Charts";
import { DataTable } from "../components/answer/DataTable";
import { KpiGrid } from "../components/answer/KpiGrid";
import { Icon } from "../components/Icon";
import { formatDate } from "../lib/format";
import type { Dataset, DashboardPayload, DashboardTab, DashboardWidget, Kpi } from "../lib/types";
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

/** Consecutive KPIs share one grid; everything else renders in order. */
function Widgets({ widgets, data }: { widgets: DashboardWidget[]; data: Record<string, Dataset> }) {
  const out: ReactNode[] = [];
  let kpis: DashboardWidget[] = [];
  const flush = () => {
    if (kpis.length)
      out.push(<KpiGrid key={kpis[0].id} kpis={kpis.map((w) => w.component as Kpi)} ids={kpis.map((w) => `w-${w.id}`)} />);
    kpis = [];
  };
  widgets.forEach((w) => {
    const c = w.component;
    if (c.type === "kpi") return void kpis.push(w);
    flush();
    let body: ReactNode = null;
    if (c.type === "callout") {
      body = (
        <div className={`banner banner--${c.tone}`}>
          <Icon name={c.tone === "info" ? "info" : "warn"} />
          <span>{c.text}</span>
        </div>
      );
    } else if (data[c.query]) {
      const d = data[c.query];
      body =
        c.type === "table" ? <DataTable spec={c} data={d} /> :
        c.type === "hbar" ? <HBarView spec={c} data={d} /> :
        c.type === "scatter" ? <ScatterView spec={c} data={d} /> :
        <SeriesChartView spec={c} data={d} />;
    }
    if (body) out.push(<div key={w.id} id={`w-${w.id}`} data-widget-id={w.id}>{body}</div>);
  });
  flush();
  return <>{out}</>;
}

function widgetTitle(w: DashboardWidget | undefined) {
  if (!w) return "";
  const c = w.component;
  return c.type === "kpi" ? c.label : c.type === "callout" ? "Note" : c.title;
}

function Findings({ tab }: { tab: DashboardTab }) {
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
      <p className={"dash-takeaway" + (tab.outcome !== "answered" ? " dash-takeaway--muted" : "")}>{tab.takeaway}</p>
      <Findings tab={tab} />
      <Widgets widgets={tab.widgets} data={data} />
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
            <span>Reporting period: {s.period}</span>
          </div>
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
