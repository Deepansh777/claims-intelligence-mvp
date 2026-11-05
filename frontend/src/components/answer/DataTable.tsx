import { useMemo, useState } from "react";
import { BASE_URL } from "../../lib/apiClient";
import { formatValue, isNumericType } from "../../lib/format";
import type { Dataset, Table } from "../../lib/types";
import { Icon } from "../Icon";

const PAGE = 50;
const MAX_FILTER_OPTIONS = 200;

function compare(a: unknown, b: unknown): number {
  if (a == null) return b == null ? 0 : 1; // nulls last in both directions is handled by caller
  if (b == null) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true });
}

/** Sorting, filtering and paging all run on the rows already loaded; nothing is re-queried. */
export function DataTable({ spec, data, runId }: { spec: Table; data: Dataset; runId: string }) {
  const cols = spec.columns
    .map((c) => ({ ...c, i: data.columns.indexOf(c.column) }))
    .filter((c) => c.i >= 0);
  const [sort, setSort] = useState({ column: spec.sort_column, desc: spec.sort_desc });
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [limit, setLimit] = useState(PAGE);

  const filterOptions = useMemo(
    () =>
      spec.filter_columns
        .map((name) => {
          const i = data.columns.indexOf(name);
          const values = [...new Set(data.rows.map((r) => String(r[i] ?? "—")))].sort();
          return { name, i, values };
        })
        .filter((f) => f.i >= 0 && f.values.length > 1 && f.values.length <= MAX_FILTER_OPTIONS),
    [spec.filter_columns, data],
  );

  const rows = useMemo(() => {
    let out = data.rows.filter((r) =>
      filterOptions.every((f) => !filters[f.name] || String(r[f.i] ?? "—") === filters[f.name]),
    );
    const si = sort.column ? data.columns.indexOf(sort.column) : -1;
    if (si >= 0) {
      out = [...out].sort((a, b) => {
        if (a[si] == null || b[si] == null) return compare(a[si], b[si]);
        return sort.desc ? compare(b[si], a[si]) : compare(a[si], b[si]);
      });
    }
    return out;
  }, [data, filters, filterOptions, sort]);

  const toggleSort = (column: string) =>
    setSort((s) => (s.column === column ? { column, desc: !s.desc } : { column, desc: false }));
  const filtered = rows.length !== data.rows.length;

  return (
    <div className="card-raised table-card">
      <div className="table-card-head">
        <div>
          <div className="card-title">{spec.title}</div>
          {data.truncated && (
            <div className="card-subtitle">
              Only the first {data.row_count.toLocaleString()} rows were returned. Narrow the question to see the rest.
            </div>
          )}
        </div>
        <span className="table-count">
          {filtered ? `${rows.length.toLocaleString()} of ` : ""}
          {data.row_count.toLocaleString()} {data.row_count === 1 ? "row" : "rows"}
        </span>
      </div>
      {filterOptions.length > 0 && (
        <div className="table-filters">
          {filterOptions.map((f) => (
            <label key={f.name} className="table-filter">
              <span>{spec.columns.find((c) => c.column === f.name)?.label ?? f.name}</span>
              <select
                value={filters[f.name] ?? ""}
                onChange={(e) => {
                  setFilters({ ...filters, [f.name]: e.target.value });
                  setLimit(PAGE);
                }}
              >
                <option value="">All</option>
                {f.values.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
          ))}
          {filtered && (
            <button className="link-btn" onClick={() => setFilters({})}>
              Clear filters
            </button>
          )}
        </div>
      )}
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              {cols.map((c) => {
                const num = isNumericType(data.types[c.i]);
                const active = sort.column === c.column;
                return (
                  <th
                    key={c.column}
                    className={num ? "num" : ""}
                    aria-sort={active ? (sort.desc ? "descending" : "ascending") : "none"}
                  >
                    <button className="th-sort" onClick={() => toggleSort(c.column)} title={`Sort by ${c.label}`}>
                      {c.label}
                      <span className="th-arrow">{active ? (sort.desc ? "▼" : "▲") : ""}</span>
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, limit).map((r, ri) => (
              <tr key={ri}>
                {cols.map((c) => (
                  <td key={c.column} className={isNumericType(data.types[c.i]) ? "num" : ""}>
                    {r[c.i] == null ? <span className="muted">—</span> : formatValue(r[c.i], c.format)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="table-footer">
        {rows.length > limit && (
          <button className="btn btn-text" onClick={() => setLimit(limit + PAGE * 4)}>
            Show more ({(rows.length - limit).toLocaleString()} hidden)
          </button>
        )}
        <span className="spacer" />
        <a className="btn btn-secondary" href={`${BASE_URL}/runs/${runId}/export.csv?query=${spec.query}`} download>
          <Icon name="download" />
          Export Data
        </a>
      </div>
    </div>
  );
}
