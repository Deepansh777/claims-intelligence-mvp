import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/apiClient";
import { downloadText, fileStem } from "../lib/download";
import { formatMs } from "../lib/format";
import { parseMarkdown } from "../lib/markdown";
import type { DashboardMethodology } from "../lib/types";
import { Icon } from "./Icon";
import { CodeBlock, Modal } from "./Overlay";

export type DetailKind = "methodology" | "sql" | "python";

/** Text-only rendering: nothing from the document reaches the page as HTML. */
function Markdown({ text }: { text: string }) {
  const blocks = parseMarkdown(text);
  // The dialog heading already names the dashboard.
  const body = blocks[0]?.type === "heading" && blocks[0].level === 1 ? blocks.slice(1) : blocks;
  return (
    <div className="md">
      {body.map((b, i) =>
        b.type === "heading" ? (
          b.level <= 2 ? <h3 key={i}>{b.text}</h3> : <h4 key={i}>{b.text}</h4>
        ) : b.type === "paragraph" ? (
          <p key={i}>{b.text}</p>
        ) : b.type === "list" ? (
          <ul key={i}>{b.items.map((item, j) => <li key={j}>{item}</li>)}</ul>
        ) : (
          <table key={i} className="table">
            <thead>
              <tr>{b.head.map((h, j) => <th key={j}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {b.rows.map((r, j) => (
                <tr key={j}>{r.map((c, k) => <td key={k}>{c}</td>)}</tr>
              ))}
            </tbody>
          </table>
        ),
      )}
    </div>
  );
}

/** Methodology or executed SQL of a saved dashboard, as stored with its current version. */
export function DashboardDetails({ id, title, kind, onClose }: { id: string; title: string; kind: DetailKind; onClose: () => void }) {
  const q = useQuery({
    queryKey: ["dashboard-methodology", id],
    queryFn: () => apiGet<DashboardMethodology>(`/dashboards/${id}/methodology`),
  });
  const stem = fileStem(title);
  return (
    <Modal onClose={onClose} large>
      <div className="card-header-row">
        <h2>{kind === "methodology" ? title : `${kind === "sql" ? "SQL queries" : "Python scripts"} · ${title}`}</h2>
        {kind === "methodology" && q.data && (
          <button className="btn btn-secondary" onClick={() => downloadText(`${stem}-methodology.md`, q.data.markdown, "text/markdown")}>
            <Icon name="download" />
            Download .md
          </button>
        )}
      </div>
      <div className="details-body">
        {q.isLoading ? (
          <div className="thinking">
            <span className="spinner sm" />
            Loading…
          </div>
        ) : q.isError ? (
          <div className="banner banner--error">
            <Icon name="warn" />
            <span>{q.error.message}</span>
          </div>
        ) : kind === "methodology" ? (
          <Markdown text={q.data!.markdown} />
        ) : kind === "python" ? (
          q.data!.scripts.map((s, i) => (
            <section key={i} className="stack details-query">
              <div className="card-header-row">
                <div>
                  <h3>{s.purpose}</h3>
                  <p>
                    {s.tab} tab: {s.status === "succeeded" ? "ran" : "failed"} in {formatMs(s.duration_ms)}.
                  </p>
                </div>
                <button
                  className="btn btn-secondary"
                  onClick={() => downloadText(`${stem}-${fileStem(s.tab)}-analysis-${i + 1}.py`, s.code + "\n", "text/x-python")}
                >
                  <Icon name="download" />
                  Download .py
                </button>
              </div>
              <CodeBlock code={s.code} language="python" />
              {s.output && <CodeBlock code={s.output} language="plaintext" />}
            </section>
          ))
        ) : q.data!.queries.length === 0 ? (
          <p>No query ran for this dashboard.</p>
        ) : (
          q.data!.queries.map((x) => (
            <section key={`${x.tab}-${x.name}`} className="stack details-query">
              <div className="card-header-row">
                <div>
                  <h3>{x.purpose}</h3>
                  <p>
                    {x.tab} tab, {x.name}: returned {x.row_count == null ? "no stored" : x.row_count.toLocaleString()}{" "}
                    {x.row_count === 1 ? "row" : "rows"} in {formatMs(x.duration_ms)}.
                  </p>
                </div>
                <button
                  className="btn btn-secondary"
                  onClick={() => downloadText(`${stem}-${fileStem(x.tab)}-${x.name}.sql`, x.sql + "\n", "application/sql")}
                >
                  <Icon name="download" />
                  Download .sql
                </button>
              </div>
              <CodeBlock code={x.sql} language="sql" />
            </section>
          ))
        )}
      </div>
      <div className="modal-actions">
        <button className="btn btn-secondary" onClick={onClose}>
          Close
        </button>
      </div>
    </Modal>
  );
}
