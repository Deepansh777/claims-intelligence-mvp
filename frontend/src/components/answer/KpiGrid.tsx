import { formatValue } from "../../lib/format";
import type { Kpi } from "../../lib/types";
import { Icon } from "../Icon";

const kpiIcon = (k: Kpi) =>
  k.format === "usd" || k.format === "usd2" ? "spending" : k.format.startsWith("pct") || k.format === "rate" ? "er" : "cohort";

export function KpiGrid({ kpis, ids }: { kpis: Kpi[]; ids?: string[] }) {
  return (
    <div className="kpi-grid">
      {kpis.map((k, i) => (
        <div className="card-raised kpi-card" key={i} id={ids?.[i]}>
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
