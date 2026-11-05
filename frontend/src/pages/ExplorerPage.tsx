import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Icon } from "../components/Icon";
import { BASE_URL } from "../lib/apiClient";
import { DatabaseMap } from "../components/explorer/DatabaseMap";
import { SqlWorkspace } from "../components/explorer/SqlWorkspace";

const TABS = { map: "Database Map", sql: "SQL Workspace" } as const;
const quote = (name: string) => `"${name.replace(/"/g, '""')}"`;

export default function ExplorerPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "sql" ? "sql" : "map";
  const [sql, setSql] = useState("");
  const show = (t: keyof typeof TABS) => setParams(t === "map" ? {} : { tab: t }, { replace: true });

  return (
    <section className="view" aria-label="Data Explorer">
      <div className="content-anim">
        <header className="topbar">
          <div>
            <h1 className="page-title">Data Explorer</h1>
            <p className="page-sub">Browse schemas, tables and columns, preview sample rows, and run read-only SQL.</p>
          </div>
          <div className="topbar-actions">
            <a className="btn btn-secondary" href={`${BASE_URL}/explorer/docs/schema.docx`} download>
              <Icon name="file" />
              Schema docs (Word)
            </a>
            <a className="btn btn-secondary" href={`${BASE_URL}/explorer/docs/schema.pdf`} download>
              <Icon name="download" />
              Schema docs (PDF)
            </a>
          </div>
        </header>
        <div className="content stack">
          <div className="subtabs" role="tablist">
            {(Object.keys(TABS) as (keyof typeof TABS)[]).map((t) => (
              <button
                key={t}
                id={`tab-${t}`}
                role="tab"
                aria-selected={tab === t}
                aria-controls={`panel-${t}`}
                className={"subtab" + (tab === t ? " active" : "")}
                onClick={() => show(t)}
              >
                {TABS[t]}
              </button>
            ))}
          </div>
          {/* Both panels stay mounted so the map's state and the editor's query survive tab switches. */}
          <div id="panel-map" role="tabpanel" aria-labelledby="tab-map" hidden={tab !== "map"}>
            <DatabaseMap
              onQuery={(schema, table) => {
                setSql(`SELECT *\nFROM ${quote(schema)}.${quote(table)}\nLIMIT 100`);
                show("sql");
              }}
            />
          </div>
          <div id="panel-sql" role="tabpanel" aria-labelledby="tab-sql" hidden={tab !== "sql"}>
            <SqlWorkspace sql={sql} onSqlChange={setSql} />
          </div>
        </div>
      </div>
    </section>
  );
}
