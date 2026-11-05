import { useState, type ReactNode } from "react";
import { formatDate, formatMs, formatValue } from "../../lib/format";
import type { Answer, Component, Kpi } from "../../lib/types";
import { Icon } from "../Icon";
import { CodeBlock, Drawer } from "../Overlay";
import { HBarView, ScatterView, SeriesChartView } from "./Charts";
import { DataTable } from "./DataTable";

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

const kpiIcon = (k: Kpi) =>
  k.format === "usd" || k.format === "usd2" ? "spending" : k.format.startsWith("pct") || k.format === "rate" ? "er" : "cohort";

function KpiGrid({ kpis }: { kpis: Kpi[] }) {
  return (
    <div className="kpi-grid">
      {kpis.map((k, i) => (
        <div className="card-raised kpi-card" key={i}>
          <div className="kpi-body">
            <div className="kpi-header">
              <span className="kpi-icon">
                <Icon name={kpiIcon(k)} />
              </span>
              <span className="kpi-title">{k.label}</span>
            </div>
            <div className="kpi-value">{formatValue(k.value, k.format)}</div>
            <div className="kpi-subtitle">{k.sub ?? ""}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

function Interpretation({ data }: { data: Record<string, string> }) {
  return (
    <div className="interpret">
      <div className="interpret-head">
        <Icon name="sparkles" />
        Interpreted request
      </div>
      <div className="interpret-grid">
        {Object.entries(INTERPRETATION_LABELS)
          .filter(([k]) => data[k])
          .map(([k, label]) => (
            <div className="interpret-item" key={k}>
              <div className="il">{label}</div>
              <div className="iv">{data[k]}</div>
            </div>
          ))}
      </div>
    </div>
  );
}

/** Consecutive KPIs share one grid; everything else renders in order. */
function Components({ answer }: { answer: Answer }) {
  const out: ReactNode[] = [];
  let kpis: Kpi[] = [];
  const flush = () => {
    if (kpis.length) out.push(<KpiGrid key={`k${out.length}`} kpis={kpis} />);
    kpis = [];
  };
  answer.components.forEach((c: Component, i) => {
    if (c.type === "kpi") return void kpis.push(c);
    flush();
    if (c.type === "callout") {
      out.push(
        <div key={i} className={`banner banner--${c.tone}`}>
          <Icon name={c.tone === "info" ? "info" : "warn"} />
          <span>{c.text}</span>
        </div>,
      );
      return;
    }
    const data = answer.datasets[c.query];
    if (!data) return;
    if (c.type === "table") out.push(<DataTable key={i} spec={c} data={data} runId={answer.run_id} />);
    else if (c.type === "hbar") out.push(<HBarView key={i} spec={c} data={data} />);
    else if (c.type === "scatter") out.push(<ScatterView key={i} spec={c} data={data} />);
    else out.push(<SeriesChartView key={i} spec={c} data={data} />);
  });
  flush();
  return <>{out}</>;
}

/** Buttons that send a new question (unlike table sort/filter, which stay local). */
function AskButtons({ label, items, onAsk, disabled }: { label: string; items: string[]; onAsk: (q: string) => void; disabled: boolean }) {
  if (!items.length) return null;
  return (
    <div className="ask-next">
      <span className="pill-label">{label}</span>
      {items.map((q) => (
        <button key={q} className="pill ask-pill" onClick={() => onAsk(q)} disabled={disabled} title="Runs a new analysis">
          {q}
          <Icon name="arrowRight" />
        </button>
      ))}
    </div>
  );
}

function AnalysisDrawer({ answer, isAdmin, onClose }: { answer: Answer; isAdmin: boolean; onClose: () => void }) {
  const tabs = ["Methodology", "SQL", "Provenance", ...(isAdmin ? ["Execution"] : [])];
  const [tab, setTab] = useState(tabs[0]);
  const u = answer.usage;
  const dl = (rows: [string, ReactNode][]) => (
    <dl className="dl">
      {rows.map(([k, v]) => (
        <div key={k} style={{ display: "contents" }}>
          <dt>{k}</dt>
          <dd>{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
  const list = (title: string, items: string[]) =>
    items.length > 0 && (
      <div>
        <div className="va-section-title">{title}</div>
        <ul className="va-list">
          {items.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      </div>
    );
  return (
    <Drawer title="View analysis" sub="How this result was produced — retrieved from the execution record, not regenerated." onClose={onClose}>
      <div className="subtabs">
        {tabs.map((t) => (
          <button key={t} className={"subtab" + (t === tab ? " active" : "")} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>
      {tab === "Methodology" && (
        <>
          {answer.interpretation && (
            <div>
              <div className="va-section-title">Interpretation</div>
              {dl(Object.entries(INTERPRETATION_LABELS).map(([k, label]) => [label, answer.interpretation![k]]))}
            </div>
          )}
          {list("Assumptions", answer.assumptions)}
          {list("Limitations", answer.limitations)}
          <p className="field-hint">
            Every figure in the answer comes from the executed queries; derived values such as changes and ratios are computed in the SQL.
          </p>
        </>
      )}
      {tab === "SQL" &&
        (answer.queries.length ? (
          answer.queries.map((q, i) => (
            <div key={i} className="stack">
              <div className="va-section-title">
                {q.name} · {q.purpose} · attempt {q.attempt} ·{" "}
                {q.status === "succeeded" ? `${(q.row_count ?? 0).toLocaleString()} rows in ${formatMs(q.duration_ms)}` : "failed, then corrected"}
              </div>
              <CodeBlock code={q.sql} />
            </div>
          ))
        ) : (
          <p className="muted">No query was needed for this answer.</p>
        ))}
      {tab === "Provenance" &&
        dl([
          ["Run ID", answer.run_id],
          ["Dataset version", answer.dataset_version_id == null ? null : `#${answer.dataset_version_id}${answer.dataset_loaded_at ? `, loaded ${formatDate(answer.dataset_loaded_at)}` : ""}`],
          ["Network default", answer.network],
          ["Model", answer.model],
          ["Effort", answer.effort],
          ["Re-run of", answer.rerun_of],
        ])}
      {tab === "Execution" &&
        (u
          ? dl([
              ["Model latency", formatMs(u.latency_ms)],
              ["Cost", u.cost_usd == null ? "Not priced" : `$${Number(u.cost_usd).toFixed(4)}`],
              ["Input tokens", u.input_tokens?.toLocaleString()],
              ["Cached input tokens", u.cached_input_tokens?.toLocaleString()],
              ["Cache write tokens", u.cache_write_tokens?.toLocaleString()],
              ["Output tokens", u.output_tokens?.toLocaleString()],
              ["Reasoning tokens", u.reasoning_tokens?.toLocaleString()],
              ["Query time", formatMs(answer.queries.reduce((s, q) => s + (q.duration_ms ?? 0), 0))],
            ])
          : <p className="muted">Usage appears once the answer has been saved.</p>)}
    </Drawer>
  );
}

export function AnswerView({
  answer,
  onAsk,
  busy,
  isAdmin,
}: {
  answer: Answer;
  onAsk: (q: string) => void;
  busy: boolean;
  isAdmin: boolean;
}) {
  const [drawer, setDrawer] = useState(false);
  const o = answer.outcome;
  let body: ReactNode;
  if (o === "clarify") {
    body = (
      <div className="clarify">
        <div className="clarify-q">{answer.text}</div>
        <AskButtons label="Choose:" items={answer.options} onAsk={onAsk} disabled={busy} />
      </div>
    );
  } else if (o === "declined" || o === "failed" || o === "cancelled") {
    const tone = o === "failed" ? "error" : o === "declined" ? "info" : "warn";
    body = (
      <div className={`banner banner--${tone}`}>
        <Icon name={tone === "info" ? "info" : "warn"} />
        <span>{o === "cancelled" ? "Stopped before an answer was ready." : answer.text}</span>
      </div>
    );
  } else {
    body = (
      <>
        <div className={"answer-text" + (o === "unsupported" ? " answer-unsupported" : "")}>{answer.text}</div>
        {answer.interpretation && <Interpretation data={answer.interpretation} />}
        <Components answer={answer} />
        {answer.limitations.length > 0 && (
          <div className="banner banner--warn">
            <Icon name="warn" />
            <span>{answer.limitations.join(" ")}</span>
          </div>
        )}
      </>
    );
  }
  const shortRun = answer.run_id.slice(0, 8);
  return (
    <div className="answer">
      {body}
      {o !== "clarify" && (
        <div className="answer-actions">
          {(answer.queries.length > 0 || answer.interpretation) && (
            <button className="btn btn-secondary" onClick={() => setDrawer(true)}>
              <Icon name="methodology" />
              View analysis
            </button>
          )}
          <span className="answer-meta">
            <Icon name="provenance" />
            {answer.dataset_loaded_at ? `Data loaded ${formatDate(answer.dataset_loaded_at)} · ` : ""}Run {shortRun}
            {answer.model ? ` · ${answer.model} (${answer.effort})` : ""}
          </span>
        </div>
      )}
      <AskButtons label="Ask next:" items={answer.followups} onAsk={onAsk} disabled={busy} />
      {drawer && <AnalysisDrawer answer={answer} isAdmin={isAdmin} onClose={() => setDrawer(false)} />}
    </div>
  );
}
