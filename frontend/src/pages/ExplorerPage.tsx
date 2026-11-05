import { DatabaseMap } from "../components/explorer/DatabaseMap";

export default function ExplorerPage() {
  return (
    <section className="view" aria-label="Data Explorer">
      <div className="content-anim">
        <header className="topbar">
          <div>
            <h1 className="page-title">Data Explorer</h1>
            <p className="page-sub">Browse schemas, tables and columns, and preview sample rows.</p>
          </div>
        </header>
        <div className="content stack">
          <DatabaseMap />
        </div>
      </div>
    </section>
  );
}
