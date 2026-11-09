import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../../lib/apiClient";
import { formatValue } from "../../lib/format";
import type { Dataset, Kpi, LlmUsageReport, SeriesChart, UsageRow } from "../../lib/types";
import { HBarView, SeriesChartView } from "../answer/Charts";
import { KpiGrid } from "../answer/KpiGrid";
import { Icon } from "../Icon";

type Period = LlmUsageReport["period"];
const PERIODS: [Period, string][] = [["day", "Daily"], ["month", "Monthly"], ["year", "Yearly"]];
const PRIOR: Record<Period, string> = { day: "prior 30 days", month: "prior 12 months", year: "" };
const FEATURES: Record<string, string> = { ask: "Ask", dashboard: "Dashboard generation", dashboard_outline: "Dashboard outline" };

const usd = (v: number) => formatValue(v, "usd2");
const int = (v: number) => formatValue(v, "int");
const tokens = (r: UsageRow) => r.input_tokens + r.output_tokens;

function delta(cur: number, prev: number | undefined, label: string) {
  if (!prev) return "";
  const p = ((cur - prev) / prev) * 100;
  return ` · ${p >= 0 ? "▲" : "▼"} ${Math.abs(p).toFixed(1)}% vs ${label}`;
}

function bucketLabel(key: string, period: Period) {
  const d = new Date(key + "T00:00:00Z");
  if (period === "year") return String(d.getUTCFullYear());
  return d.toLocaleDateString("en-US", period === "day" ? { month: "short", day: "numeric", timeZone: "UTC" } : { month: "short", year: "numeric", timeZone: "UTC" });
}

const dataset = (columns: string[], rows: unknown[][]): Dataset => ({ columns, types: [], rows, row_count: rows.length, truncated: false });

function UsageTable({ title, subtitle, head, rows, name }: { title: string; subtitle: string; head: string; rows: UsageRow[]; name: (k: string | null) => string }) {
  const total = rows.reduce((s, r) => s + r.cost_usd, 0) || 1;
  return (
    <div className="card-raised table-card">
      <div className="table-card-head">
        <div>
          <div className="card-title">{title}</div>
          <div className="card-subtitle">{subtitle}</div>
        </div>
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>{head}</th>
              <th className="num">Requests</th>
              <th className="num">Input tok.</th>
              <th className="num">Output tok.</th>
              <th className="num">Cost</th>
              <th className="num">Share</th>
              <th className="num">Cost / request</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="muted">No usage in this period.</td>
              </tr>
            )}
            {rows.map((r) => (
              <tr key={r.key ?? ""}>
                <td style={{ fontWeight: 500, color: "#123137" }}>
                  {name(r.key)}
                  {r.unpriced_calls > 0 && (
                    <span className="badge badge--warn" style={{ marginLeft: 8 }} title="No price on file for these calls; their cost is not included">
                      {r.unpriced_calls} unpriced
                    </span>
                  )}
                </td>
                <td className="num">{int(r.requests)}</td>
                <td className="num">{int(r.input_tokens)}</td>
                <td className="num">{int(r.output_tokens)}</td>
                <td className="num">{usd(r.cost_usd)}</td>
                <td className="num">{((r.cost_usd / total) * 100).toFixed(1)}%</td>
                <td className="num">{r.requests ? usd(r.cost_usd / r.requests) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function LlmUsagePanel() {
  const [period, setPeriod] = useState<Period>("day");
  const [mode, setMode] = useState<"cost" | "tokens">("cost");
  const q = useQuery({
    queryKey: ["admin", "llm-usage", period],
    queryFn: () => apiGet<LlmUsageReport>(`/admin/llm-usage?period=${period}`),
  });

  const toolbar = (
    <div className="llm-toolbar">
      <div>
        <div className="card-title" style={{ fontSize: "1.0625rem" }}>LLM usage &amp; cost</div>
        <div className="card-subtitle" style={{ marginBottom: 0 }}>
          Token consumption and spend across Ask and Dashboards, from recorded model calls. Times are UTC.
        </div>
      </div>
      <div className="seg" role="tablist">
        {PERIODS.map(([id, label]) => (
          <button key={id} className={"seg-btn" + (period === id ? " active" : "")} onClick={() => setPeriod(id)}>
            {label}
          </button>
        ))}
      </div>
    </div>
  );

  if (q.isLoading)
    return (
      <>
        {toolbar}
        <div className="thinking" style={{ padding: 24 }}>
          <span className="spinner sm" />
          Loading usage…
        </div>
      </>
    );
  if (q.isError || !q.data)
    return (
      <>
        {toolbar}
        <div className="banner banner--error">
          <Icon name="warn" />
          <span>LLM usage couldn't be loaded: {q.error?.message}</span>
        </div>
      </>
    );

  const r = q.data, t = r.total, p = r.previous ?? undefined, prior = PRIOR[period];
  const kpi = (label: string, value: number, format: Kpi["format"], sub: string): Kpi => ({ type: "kpi", label, value, format, sub });
  const kpis = [
    kpi("Total cost", t.cost_usd, "usd2", r.label + delta(t.cost_usd, p?.cost_usd, prior)),
    kpi("Total tokens", tokens(t), "int", `${int(t.input_tokens)} in · ${int(t.output_tokens)} out` + delta(tokens(t), p && tokens(p), prior)),
    kpi("Requests", t.requests, "int", `Avg ${int(tokens(t) / (t.requests || 1))} tokens each` + delta(t.requests, p?.requests, prior)),
    kpi("Avg cost / request", t.cost_usd / (t.requests || 1), "usd2", `${usd(t.cost_usd / ((tokens(t) || 1) / 1e6))} per 1M tokens`),
    kpi("Cost per active day", t.cost_usd / (t.active_days || 1), "usd2", `${t.active_days} days with usage`),
  ];
  const labels = r.series.map((s) => bucketLabel(s.key!, period));
  const y = mode === "cost" ? ["Cost"] : ["Input tokens", "Output tokens"];
  const chartSpec: SeriesChart = {
    type: period === "year" ? "bar" : "line",
    title: mode === "cost" ? "Cost over time" : "Tokens over time",
    query: "",
    x: "Period",
    y,
    format: mode === "cost" ? "usd2" : "int",
  };
  const chartData = dataset(
    ["Period", ...y],
    r.series.map((s, i) => (mode === "cost" ? [labels[i], s.cost_usd] : [labels[i], s.input_tokens, s.output_tokens])),
  );
  const featureName = (k: string | null) => FEATURES[k ?? ""] ?? k ?? "—";

  return (
    <>
      {toolbar}
      <div className="llm-stack">
        {t.unpriced_calls > 0 && (
          <div className="banner banner--warn">
            <Icon name="warn" />
            <span>
              {t.unpriced_calls} model {t.unpriced_calls === 1 ? "call has" : "calls have"} no price on file, so the cost shown is
              lower than actual. Add the model to <code>llm_metrics.model_pricing</code>.
            </span>
          </div>
        )}
        <KpiGrid kpis={kpis} />
        <div className="llm-charts">
          <div className="llm-chart-main">
            <div className="llm-chart-toggle">
              <div className="seg seg--sm">
                <button className={"seg-btn" + (mode === "cost" ? " active" : "")} onClick={() => setMode("cost")}>Cost</button>
                <button className={"seg-btn" + (mode === "tokens" ? " active" : "")} onClick={() => setMode("tokens")}>Tokens</button>
              </div>
            </div>
            <SeriesChartView spec={chartSpec} data={chartData} />
          </div>
          <HBarView
            spec={{ type: "hbar", title: "Cost by feature", query: "", label: "Feature", value: "Cost", format: "usd2", top_n: 10 }}
            data={dataset(["Feature", "Cost"], r.by_feature.map((f) => [featureName(f.key), f.cost_usd]))}
          />
        </div>
        <div className="llm-two">
          <UsageTable title="Usage by model" subtitle={r.label} head="Model" rows={r.by_model} name={(k) => k ?? "—"} />
          <UsageTable title="Usage by user" subtitle={`Ranked by cost · ${r.label}`} head="User" rows={r.by_user} name={(k) => k ?? "—"} />
        </div>
        <UsageTable title="Usage by feature" subtitle={r.label} head="Feature" rows={r.by_feature} name={featureName} />
      </div>
    </>
  );
}
