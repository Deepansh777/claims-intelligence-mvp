import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiGet } from "../../lib/apiClient";
import type { Dataset } from "../../lib/types";
import { Icon } from "../Icon";
import { Modal } from "../Overlay";

type SchemaMeta = { name: string; table_count: number };
type TableMeta = { name: string; kind: string; estimated_rows: number | null };
type ColumnMeta = { name: string; type: string; nullable: boolean };
type Open = { has: (key: string) => boolean; toggle: (key: string) => void };
type TableAction = (schema: string, table: string) => void;
type Actions = { onPreview: TableAction; onQuery: TableAction };

const STALE_MS = 10 * 60_000; // matches the backend metadata cache
const HOME = { x: 24, y: 24, k: 1 };
const MIN_ZOOM = 0.1; // low enough for Fit to show a fully expanded schema as an overview
const MAX_ZOOM = 2.5;
const compact = new Intl.NumberFormat(undefined, { notation: "compact" });
const enc = encodeURIComponent;

function useExplorer<T>(path: string, enabled = true) {
  return useQuery({
    queryKey: ["explorer", path],
    queryFn: () => apiGet<T>(`/explorer${path}`),
    enabled,
    staleTime: STALE_MS,
  });
}

function usePanZoom() {
  const ref = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number } | null>(null);
  const [view, setView] = useState(HOME);

  // (px, py) is the viewport point that stays fixed while zooming.
  const zoomAt = useCallback((factor: number, px?: number, py?: number) => {
    const r = ref.current!.getBoundingClientRect();
    const cx = px ?? r.width / 2;
    const cy = py ?? r.height / 2;
    setView((v) => {
      const k = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v.k * factor));
      return { k, x: cx - ((cx - v.x) * k) / v.k, y: cy - ((cy - v.y) * k) / v.k };
    });
  }, []);

  // React's onWheel is passive, so preventDefault (stop page scroll) needs a native listener.
  useEffect(() => {
    const el = ref.current!;
    const onWheel = (e: WheelEvent) => {
      if ((e.target as Element).closest(".dm-cols")) return; // long column lists scroll instead
      e.preventDefault();
      const r = el.getBoundingClientRect();
      zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [zoomAt]);

  // Whole tree visible and centred; never enlarged past 100% so a small tree stays readable.
  const canvasRef = useRef<HTMLDivElement>(null);
  const fit = useCallback(() => {
    const vp = ref.current!.getBoundingClientRect();
    const { offsetWidth: w, offsetHeight: h } = canvasRef.current!; // layout size, unaffected by scale
    const k = Math.max(MIN_ZOOM, Math.min(1, (vp.width - 48) / w, (vp.height - 48) / h));
    setView({ k, x: (vp.width - w * k) / 2, y: Math.max(24, (vp.height - h * k) / 2) });
  }, []);

  const pan = (dx: number, dy: number) => setView((v) => ({ ...v, x: v.x + dx, y: v.y + dy }));
  const handlers = {
    onPointerDown: (e: PointerEvent<HTMLDivElement>) => {
      if ((e.target as Element).closest("button")) return;
      drag.current = { x: e.clientX, y: e.clientY };
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    onPointerMove: (e: PointerEvent<HTMLDivElement>) => {
      const d = drag.current;
      if (!d) return;
      pan(e.clientX - d.x, e.clientY - d.y);
      drag.current = { x: e.clientX, y: e.clientY };
    },
    onPointerUp: () => (drag.current = null),
    onKeyDown: (e: KeyboardEvent<HTMLDivElement>) => {
      if (e.target !== e.currentTarget) return;
      const step = { ArrowLeft: [60, 0], ArrowRight: [-60, 0], ArrowUp: [0, 60], ArrowDown: [0, -60] }[e.key];
      if (step) {
        e.preventDefault();
        pan(step[0], step[1]);
      } else if (e.key === "+" || e.key === "=") zoomAt(1.2);
      else if (e.key === "-") zoomAt(1 / 1.2);
    },
  };
  return { ref, canvasRef, view, handlers, zoomAt, fit, reset: () => setView(HOME) };
}

/** A node with its children stacked to the right; CSS draws the connectors. */
function Branch({ node, children }: { node: ReactNode; children?: ReactNode }) {
  return (
    <div className="dm-branch">
      {node}
      {children && <div className="dm-children">{children}</div>}
    </div>
  );
}

function Pending({ q }: { q: UseQueryResult<unknown> }) {
  return q.isError ? (
    <div className="dm-status dm-status--error">
      <Icon name="warn" />
      Couldn't load.
      <button className="link-btn" onClick={() => q.refetch()}>
        Retry
      </button>
    </div>
  ) : (
    <div className="dm-status">
      <span className="spinner sm" />
      Loading…
    </div>
  );
}

function Toggle({ open, onClick, children }: { open: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button className="dm-toggle" aria-expanded={open} onClick={onClick}>
      <Icon name="chevronRight" />
      {children}
    </button>
  );
}

function TableBranch({ schema, table, open, actions }: { schema: string; table: TableMeta; open: Open; actions: Actions }) {
  const key = `t:${schema}.${table.name}`;
  const isOpen = open.has(key);
  const cols = useExplorer<ColumnMeta[]>(`/schemas/${enc(schema)}/tables/${enc(table.name)}/columns`, isOpen);
  return (
    <Branch
      node={
        <div className="dm-node dm-table">
          <div className="dm-node-head">
            <Toggle open={isOpen} onClick={() => open.toggle(key)}>
              <span className="dm-name" title={`${schema}.${table.name}`}>
                {table.name}
              </span>
            </Toggle>
            <span className="dm-meta">
              {table.kind !== "table" && `${table.kind} · `}
              {table.estimated_rows == null ? "rows unknown" : `~${compact.format(table.estimated_rows)} rows`}
            </span>
          </div>
          {isOpen &&
            (cols.data ? (
              <ul className="dm-cols" aria-label={`Columns of ${schema}.${table.name}`}>
                {cols.data.map((c) => (
                  <li key={c.name}>
                    <span className="dm-col-name">{c.name}</span>
                    <span className="dm-col-type">
                      {c.type}
                      {!c.nullable && " · not null"}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <Pending q={cols} />
            ))}
          <div className="dm-actions">
            <button className="btn btn-text" onClick={() => actions.onPreview(schema, table.name)}>
              Preview 5 Rows
            </button>
            <button className="btn btn-text" onClick={() => actions.onQuery(schema, table.name)}>
              Query
            </button>
          </div>
        </div>
      }
    />
  );
}

function SchemaBranch({ schema, open, actions }: { schema: SchemaMeta; open: Open; actions: Actions }) {
  const key = `s:${schema.name}`;
  const isOpen = open.has(key);
  const tables = useExplorer<TableMeta[]>(`/schemas/${enc(schema.name)}/tables`, isOpen);
  return (
    <Branch
      node={
        <div className="dm-node dm-schema">
          <Toggle open={isOpen} onClick={() => open.toggle(key)}>
            <span className="dm-name">{schema.name}</span>
          </Toggle>
          <span className="dm-meta">{schema.table_count} tables</span>
        </div>
      }
    >
      {isOpen &&
        (tables.data ? (
          tables.data.map((t) => <TableBranch key={t.name} schema={schema.name} table={t} open={open} actions={actions} />)
        ) : (
          <Branch node={<Pending q={tables} />} />
        ))}
    </Branch>
  );
}

function PreviewModal({ schema, table, onClose }: { schema: string; table: string; onClose: () => void }) {
  const q = useExplorer<Dataset>(`/schemas/${enc(schema)}/tables/${enc(table)}/preview`);
  return (
    <Modal onClose={onClose} wide>
      <h2>
        {schema}.{table}
      </h2>
      <p>Five sample rows, in no particular order.</p>
      {q.data ? (
        <div className="table-wrap dm-preview-table">
          <table className="table">
            <thead>
              <tr>
                {q.data.columns.map((c, i) => (
                  <th key={c} title={q.data.types[i]}>
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {q.data.rows.map((r, ri) => (
                <tr key={ri}>
                  {r.map((v, ci) => (
                    <td key={ci} title={v == null ? undefined : String(v)}>
                      {v == null ? <span className="muted">—</span> : String(v)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {q.data.rows.length === 0 && <div className="state-box">This table is empty.</div>}
        </div>
      ) : q.isError ? (
        <div className="banner banner--error">
          <Icon name="warn" />
          <span>{q.error.message}</span>
        </div>
      ) : (
        <div className="thinking">
          <span className="spinner sm" />
          Loading sample rows…
        </div>
      )}
      <div className="modal-actions">
        <button className="btn btn-secondary" onClick={onClose}>
          Close
        </button>
      </div>
    </Modal>
  );
}

export function DatabaseMap({ onQuery }: { onQuery: TableAction }) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(["db"]));
  const [preview, setPreview] = useState<{ schema: string; table: string } | null>(null);
  const schemas = useExplorer<SchemaMeta[]>("/schemas");
  const { ref, canvasRef, view, handlers, zoomAt, fit, reset } = usePanZoom();
  const open: Open = {
    has: (k) => expanded.has(k),
    toggle: (k) =>
      setExpanded((s) => {
        const next = new Set(s);
        if (!next.delete(k)) next.add(k);
        return next;
      }),
  };
  const dbOpen = expanded.has("db");
  const actions: Actions = { onPreview: (schema, table) => setPreview({ schema, table }), onQuery };

  return (
    <div className="card-raised dm-card">
      <div className="dm-toolbar">
        <button className="btn btn-text" onClick={fit}>
          <Icon name="fit" />
          Fit to screen
        </button>
        <button className="icon-btn" onClick={() => zoomAt(1 / 1.2)} aria-label="Zoom out" title="Zoom out">
          <Icon name="minus" />
        </button>
        <span className="dm-zoom" aria-live="polite">
          {Math.round(view.k * 100)}%
        </span>
        <button className="icon-btn" onClick={() => zoomAt(1.2)} aria-label="Zoom in" title="Zoom in">
          <Icon name="plus" />
        </button>
        <button className="btn btn-text" onClick={reset}>
          Reset view
        </button>
        <button className="btn btn-text" onClick={() => setExpanded(new Set(["db"]))}>
          Collapse all
        </button>
        <span className="spacer" />
        <span className="muted dm-hint">Drag or use arrow keys to pan · scroll to zoom</span>
      </div>
      <div
        className="dm-viewport"
        ref={ref}
        tabIndex={0}
        role="group"
        aria-label="Database map. Use arrow keys to pan, plus and minus to zoom."
        {...handlers}
      >
        <div className="dm-canvas" ref={canvasRef} style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})` }}>
          <Branch
            node={
              <div className="dm-node dm-db">
                <Toggle open={dbOpen} onClick={() => open.toggle("db")}>
                  <Icon name="database" />
                  <span className="dm-name">Claims database</span>
                </Toggle>
              </div>
            }
          >
            {dbOpen &&
              (schemas.data ? (
                schemas.data.map((s) => (
                  <SchemaBranch key={s.name} schema={s} open={open} actions={actions} />
                ))
              ) : (
                <Branch node={<Pending q={schemas} />} />
              ))}
          </Branch>
        </div>
      </div>
      {preview && <PreviewModal {...preview} onClose={() => setPreview(null)} />}
    </div>
  );
}
