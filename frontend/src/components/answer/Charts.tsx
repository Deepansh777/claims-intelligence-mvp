import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter as ScatterSeries,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatTick, formatValue } from "../../lib/format";
import type { Dataset, HBar, Scatter, SeriesChart } from "../../lib/types";

// Chart tokens from demo-static-mvp/app/js/charts.js.
const GRID = "#dbe5e3";
const TICK = "#68787b";
const COLORS = ["#2f9d90", "#123137", "#d69e2e", "#c14c43"];
const tick = { fontSize: 11, fill: TICK };

const col = (d: Dataset, name: string) => d.columns.indexOf(name);

function TipBox({ label, lines, note }: { label: string; lines: [string, string, string][]; note?: { text: string; tone: string } }) {
  return (
    <div className="chart-tip" style={{ position: "static" }}>
      <div className="chart-tip-label">{label}</div>
      {lines.map(([name, value, color]) => (
        <div className="chart-tip-val" key={name}>
          <span className="chart-tip-dot" style={{ background: color }} />
          {name}: <strong>{value}</strong>
        </div>
      ))}
      {note && <div className={`chart-tip-delta ${note.tone}`}>{note.text}</div>}
    </div>
  );
}

function Legend({ names }: { names: string[] }) {
  return (
    <div className="chart-legend">
      {names.map((n, i) => (
        <span className="legend-item" key={n}>
          <span className="legend-swatch" style={{ background: COLORS[i % COLORS.length] }} />
          {n}
        </span>
      ))}
    </div>
  );
}

export function SeriesChartView({ spec, data }: { spec: SeriesChart; data: Dataset }) {
  const xi = col(data, spec.x);
  const points = data.rows.map((r, i) => ({
    __i: i,
    x: r[xi],
    ...Object.fromEntries(spec.y.map((y) => [y, r[col(data, y)]])),
  })) as Record<string, any>[];
  const Chart = spec.type === "line" ? LineChart : BarChart;
  return (
    <div className="card chart-card">
      <div className="card-title">{spec.title}</div>
      <div className="card-subtitle">
        {spec.type === "line" ? "Hover a point for the change from the previous one." : "Hover a bar for the change from the previous one."}
      </div>
      <div className="chart-wrap">
        <ResponsiveContainer width="100%" height={260}>
          <Chart data={points} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="x" tick={{ ...tick, fontSize: 10 }} stroke={GRID} tickLine={false} />
            <YAxis
              tick={tick}
              stroke={GRID}
              tickLine={false}
              axisLine={false}
              width={56}
              domain={spec.type === "line" ? ["auto", "auto"] : [0, "auto"]}
              tickFormatter={(v: number) => formatTick(v, spec.format)}
            />
            <Tooltip
              cursor={spec.type === "bar" ? { fill: "rgba(69, 194, 178, 0.08)" } : { stroke: GRID }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const p = payload[0].payload;
                const prev = p.__i > 0 ? points[p.__i - 1] : null;
                const first = spec.y[0];
                const delta =
                  prev && typeof p[first] === "number" && typeof prev[first] === "number" && prev[first] !== 0
                    ? ((p[first] - prev[first]) / Math.abs(prev[first])) * 100
                    : null;
                return (
                  <TipBox
                    label={String(p.x)}
                    lines={spec.y.map((y, i) => [y, formatValue(p[y], spec.format), COLORS[i % COLORS.length]])}
                    note={
                      delta == null
                        ? { text: prev ? "No comparable previous value" : "First point", tone: "flat" }
                        : {
                            text: `${delta >= 0 ? "▲" : "▼"} ${Math.abs(delta).toFixed(1)}% vs previous${spec.y.length > 1 ? ` (${first})` : ""}`,
                            tone: delta >= 0 ? "up" : "down",
                          }
                    }
                  />
                );
              }}
            />
            {spec.y.map((y, i) =>
              spec.type === "line" ? (
                <Line key={y} dataKey={y} type="linear" stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={{ r: 3, strokeWidth: 1, stroke: "#fff", fill: COLORS[i % COLORS.length] }} isAnimationActive={false} />
              ) : (
                <Bar key={y} dataKey={y} fill={COLORS[i % COLORS.length]} radius={[3, 3, 0, 0]} maxBarSize={36} isAnimationActive={false} />
              ),
            )}
          </Chart>
        </ResponsiveContainer>
        <Legend names={spec.y} />
      </div>
    </div>
  );
}

export function HBarView({ spec, data }: { spec: HBar; data: Dataset }) {
  const li = col(data, spec.label);
  const vi = col(data, spec.value);
  const rows = data.rows.slice(0, spec.top_n).map((r) => ({ label: String(r[li] ?? "—"), value: Number(r[vi] ?? 0) }));
  const VW = 480, LBL = 150, RPAD = 74, ROW = 34, TOP = 6;
  const VH = TOP + rows.length * ROW + 6;
  const max = Math.max(0, ...rows.map((r) => r.value));
  const span = VW - LBL - RPAD;
  const bx = (v: number) => LBL + (Math.max(0, v) / (max || 1)) * span;
  return (
    <div className="card chart-card">
      <div className="card-title">{spec.title}</div>
      <div className="card-subtitle">
        {data.row_count > rows.length ? `Top ${rows.length} of ${data.row_count.toLocaleString()} rows` : `${rows.length} rows`}
      </div>
      <div className="chart-wrap">
        <svg className="chart-area hbar-svg" viewBox={`0 0 ${VW} ${VH}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label={spec.title}>
          {rows.map((r, i) => {
            const by = TOP + i * ROW + (ROW - 18) / 2;
            return (
              <g key={i}>
                <title>{`${r.label}: ${formatValue(r.value, spec.format)}`}</title>
                <text x={LBL - 10} y={by + 13} textAnchor="end" fontSize="12" fill="#142225">
                  {r.label.length > 22 ? r.label.slice(0, 21) + "…" : r.label}
                </text>
                <rect x={LBL} y={by} width={span} height={18} rx={4} fill="#f0f4f3" />
                <rect x={LBL} y={by} width={Math.max(2, bx(r.value) - LBL)} height={18} rx={4} fill={COLORS[0]} />
                <text x={VW - 2} y={by + 13} textAnchor="end" fontSize="11.5" fontWeight="600" fill="#123137">
                  {formatValue(r.value, spec.format)}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

export function ScatterView({ spec, data }: { spec: Scatter; data: Dataset }) {
  const xi = col(data, spec.x), yi = col(data, spec.y);
  const li = spec.label ? col(data, spec.label) : -1;
  const extra = spec.tooltip.map((c) => [c, col(data, c)] as const).filter(([, i]) => i >= 0);
  const points = data.rows
    .filter((r) => typeof r[xi] === "number" && typeof r[yi] === "number")
    .map((r) => ({ x: r[xi] as number, y: r[yi] as number, row: r }));
  const fmtExtra = (v: unknown) => (typeof v === "number" ? formatValue(v, "number") : String(v ?? "—"));
  return (
    <div className="card chart-card">
      <div className="card-title">{spec.title}</div>
      <div className="card-subtitle">
        {points.length.toLocaleString()} points · {spec.y} against {spec.x}
      </div>
      <div className="chart-wrap">
        <ResponsiveContainer width="100%" height={300}>
          <ScatterChart margin={{ top: 8, right: 16, bottom: 16, left: 4 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
            <XAxis type="number" dataKey="x" name={spec.x} tick={tick} stroke={GRID} tickLine={false} tickFormatter={(v: number) => formatTick(v, spec.x_format)}
              label={{ value: spec.x, position: "insideBottom", offset: -10, fontSize: 11, fill: TICK }} />
            <YAxis type="number" dataKey="y" name={spec.y} tick={tick} stroke={GRID} tickLine={false} axisLine={false} width={56} tickFormatter={(v: number) => formatTick(v, spec.y_format)} />
            <Tooltip
              cursor={{ strokeDasharray: "3 3", stroke: GRID }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const p = payload[0].payload as (typeof points)[number];
                return (
                  <TipBox
                    label={li >= 0 ? String(p.row[li]) : "Point"}
                    lines={[
                      [spec.x, formatValue(p.x, spec.x_format), COLORS[1]],
                      [spec.y, formatValue(p.y, spec.y_format), COLORS[0]],
                      ...extra.map(([c, i]) => [c, fmtExtra(p.row[i]), "transparent"] as [string, string, string]),
                    ]}
                  />
                );
              }}
            />
            <ScatterSeries data={points} fill={COLORS[0]} fillOpacity={0.55} isAnimationActive={false} />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}