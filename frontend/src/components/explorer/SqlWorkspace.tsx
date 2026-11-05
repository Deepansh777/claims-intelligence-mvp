import { useEffect, useMemo, useRef, useState } from "react";
import CodeMirror, { EditorView, keymap, Prec } from "@uiw/react-codemirror";
import { PostgreSQL, sql as sqlLanguage } from "@codemirror/lang-sql";
import { useQueries, useQuery } from "@tanstack/react-query";
import { apiGet, apiSend, BASE_URL } from "../../lib/apiClient";
import { isNumericType } from "../../lib/format";
import { Icon } from "../Icon";

type QueryPage = {
  id: string;
  status: "running" | "succeeded" | "failed" | "cancelled";
  error: string | null;
  elapsed_ms: number;
  columns: string[];
  types: string[];
  rows: unknown[][];
  page: number;
  page_size: number;
  has_next: boolean;
  capped: boolean;
  row_cap: number;
};

const STALE_MS = 10 * 60_000;

/** Table names for autocomplete, from the same cached metadata the Database Map uses. */
function useCompletionSchema() {
  const schemas = useQuery({
    queryKey: ["explorer", "/schemas"],
    queryFn: () => apiGet<{ name: string }[]>("/explorer/schemas"),
    staleTime: STALE_MS,
  });
  const tables = useQueries({
    queries: (schemas.data ?? []).map((s) => {
      const path = `/schemas/${encodeURIComponent(s.name)}/tables`;
      return {
        queryKey: ["explorer", path],
        queryFn: () => apiGet<{ name: string }[]>(`/explorer${path}`),
        staleTime: STALE_MS,
      };
    }),
  });
  const ready = tables.filter((t) => t.data).length;
  return useMemo(() => {
    const out: Record<string, string[]> = {};
    (schemas.data ?? []).forEach((s, i) => tables[i]?.data?.forEach((t) => (out[`${s.name}.${t.name}`] = [])));
    return out;
  }, [schemas.data, ready]); // `tables` is a new array each render; `ready` changes when one loads
}

function Status({ running, elapsed, result, rejected }: { running: boolean; elapsed: number; result: QueryPage | null; rejected: boolean }) {
  const secs = (ms: number) => (ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)}s`);
  if (running)
    return (
      <span className="sw-status" role="status">
        <span className="spinner sm" />
        Running… {secs(elapsed)}
      </span>
    );
  if (rejected || result?.status === "failed")
    return (
      <span className="sw-status sw-status--error" role="status">
        <Icon name="warn" />
        Failed{result && ` after ${secs(result.elapsed_ms)}`}
      </span>
    );
  if (!result) return <span className="sw-status muted">Read-only. Only SELECT and WITH queries run.</span>;
  if (result.status === "cancelled")
    return (
      <span className="sw-status" role="status">
        <Icon name="stop" />
        Cancelled after {secs(result.elapsed_ms)}
      </span>
    );
  return (
    <span className="sw-status sw-status--ok" role="status">
      <Icon name="check" />
      Succeeded in {secs(result.elapsed_ms)}
    </span>
  );
}

function ResultsGrid({ result, loading, onPage }: { result: QueryPage; loading: boolean; onPage: (n: number) => void }) {
  const first = result.page * result.page_size;
  const rangeLabel =
    result.rows.length === 0 ? "No rows" : `Rows ${(first + 1).toLocaleString()}–${(first + result.rows.length).toLocaleString()}`;
  const lastCappedPage = result.capped && !result.has_next;
  return (
    <div className="card-raised table-card">
      {result.capped && (
        <div className="banner banner--warn sw-capped">
          <Icon name="warn" />
          <span>
            Results are capped at the first <strong>{result.row_cap.toLocaleString()} rows</strong>. The query returned more; add a filter
            or LIMIT to see specific rows.
          </span>
        </div>
      )}
      <div className={"table-wrap sw-grid" + (loading ? " is-loading" : "")}>
        <table className="table">
          <thead>
            <tr>
              <th className="sw-rownum" aria-label="Row number" />
              {result.columns.map((c, i) => (
                <th key={i} className={isNumericType(result.types[i]) ? "num" : ""}>
                  {c}
                  <span className="sw-type">{result.types[i]}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.rows.map((r, ri) => (
              <tr key={ri}>
                <td className="sw-rownum">{first + ri + 1}</td>
                {r.map((v, ci) => (
                  <td key={ci} className={isNumericType(result.types[ci]) ? "num" : ""} title={v == null ? undefined : String(v)}>
                    {v == null ? <span className="muted">NULL</span> : String(v)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="table-footer sw-footer">
        <span className="table-count">
          {rangeLabel}
          {result.has_next && " · more available"}
          {lastCappedPage && " · end of capped results"}
        </span>
        <span className="spacer" />
        <button className="btn btn-secondary" disabled={loading || result.page === 0} onClick={() => onPage(result.page - 1)}>
          Previous page
        </button>
        <button className="btn btn-secondary" disabled={loading || !result.has_next} onClick={() => onPage(result.page + 1)}>
          Next page
        </button>
        <a
          className="btn btn-secondary"
          href={`${BASE_URL}/explorer/queries/${result.id}/export.csv`}
          download
          title={result.capped ? `Exports the first ${result.row_cap.toLocaleString()} rows` : "Exports every row of this result"}
        >
          <Icon name="download" />
          Export Data
        </a>
      </div>
    </div>
  );
}

export function SqlWorkspace({ sql, onSqlChange }: { sql: string; onSqlChange: (sql: string) => void }) {
  const [runningId, setRunningId] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState(0);
  const [now, setNow] = useState(0);
  const [result, setResult] = useState<QueryPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pageLoading, setPageLoading] = useState(false);
  const completionSchema = useCompletionSchema();

  useEffect(() => {
    if (!runningId) return;
    const t = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(t);
  }, [runningId]);

  const run = async () => {
    if (runningId || !sql.trim()) return;
    const id = crypto.randomUUID();
    setRunningId(id);
    setStartedAt(Date.now());
    setNow(Date.now());
    setError(null);
    try {
      setResult(await apiSend<QueryPage>("POST", "/explorer/queries", { id, sql }));
    } catch (e) {
      setResult(null);
      setError((e as Error).message);
    } finally {
      setRunningId(null);
    }
  };

  const cancel = async () => {
    if (!runningId) return;
    try {
      await apiSend<void>("DELETE", `/explorer/queries/${runningId}`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const goToPage = async (n: number) => {
    if (!result) return;
    setPageLoading(true);
    try {
      setResult(await apiGet<QueryPage>(`/explorer/queries/${result.id}?page=${n}`));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPageLoading(false);
    }
  };

  // The keymap is built once, so it calls the latest run through a ref.
  const runRef = useRef(run);
  runRef.current = run;
  const extensions = useMemo(
    () => [
      sqlLanguage({ dialect: PostgreSQL, schema: completionSchema, upperCaseKeywords: true }),
      Prec.highest(keymap.of([{ key: "Mod-Enter", run: () => (runRef.current(), true) }])),
      EditorView.contentAttributes.of({ "aria-label": "SQL editor" }),
    ],
    [completionSchema],
  );

  const shownError = error ?? (result?.status === "failed" ? result.error : null);
  return (
    <div className="stack">
      <div className="card-raised sw-editor-card">
        <div className="sw-toolbar">
          <button className="btn btn-primary" onClick={run} disabled={!!runningId || !sql.trim()}>
            <Icon name="play" />
            Run
          </button>
          <button className="btn btn-secondary" onClick={cancel} disabled={!runningId}>
            <Icon name="stop" />
            Cancel
          </button>
          <Status running={!!runningId} elapsed={now - startedAt} result={result} rejected={!!error && !result} />
          <span className="spacer" />
          <span className="muted sw-hint">Ctrl/⌘ + Enter to run</span>
        </div>
        <CodeMirror
          value={sql}
          onChange={onSqlChange}
          extensions={extensions}
          height="240px"
          placeholder="SELECT * FROM mart.member_panel LIMIT 100"
          basicSetup={{ foldGutter: false }}
        />
      </div>
      {shownError && (
        <div className="banner banner--error sw-error" role="alert">
          <Icon name="warn" />
          <span>{shownError}</span>
        </div>
      )}
      {result?.status === "succeeded" && <ResultsGrid result={result} loading={pageLoading} onPage={goToPage} />}
    </div>
  );
}
