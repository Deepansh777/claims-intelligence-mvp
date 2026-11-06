import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, apiGet, apiSend } from "../lib/apiClient";
import type { DashboardOutline, DashboardScope, DashboardSummary, Meta, OutlineResult } from "../lib/types";
import { useBuilds } from "../components/BuildToasts";
import { DashboardDetails, type DetailKind } from "../components/DashboardDetails";
import { Icon } from "../components/Icon";
import { Modal } from "../components/Overlay";
import { stepLabel } from "../lib/builds";
import { formatDate } from "../lib/format";
import { RetentionBadge } from "./ConversationsPage";

const MAX_TABS = 3;
const DAY_MS = 86_400_000;
const ERROR_TEXT = "Something went wrong. Please try again.";

type UserTab = { name: string; description: string };

export function scopeLine(s: DashboardScope) {
  const ids = s.provider_npi ? `NPI ${s.provider_npi} · TIN ${s.provider_tin}` : `TIN ${s.provider_tin}`;
  return `${s.provider_name} · ${ids} · ${s.network}`;
}

const count = (n: number | null) => (n == null ? "—" : n.toLocaleString());

/** As in Ask's execution details; a dash when the dashboard predates usage capture. */
function costLabel(d: DashboardSummary) {
  if (d.cost_usd != null) return `$${Number(d.cost_usd).toFixed(4)}`;
  return d.input_tokens == null ? "—" : "Not priced";
}

function errorText(e: unknown) {
  return e instanceof ApiError ? e.message : ERROR_TEXT;
}

function OutlineEditor({
  outline,
  onChange,
}: {
  outline: DashboardOutline;
  onChange: (o: DashboardOutline) => void;
}) {
  const s = outline.scope;
  const setTab = (i: number, patch: Partial<DashboardOutline["tabs"][number]>) =>
    onChange({ ...outline, tabs: outline.tabs.map((t, j) => (j === i ? { ...t, ...patch } : t)) });
  return (
    <div className="stack">
      <div className="dash-scope">
        <div>
          <div className="overline">{s.level === "pcp" ? "PCP" : "PCP group"}</div>
          <div className="dash-scope-main">{scopeLine(s)}</div>
        </div>
        <div>
          <div className="overline">Population</div>
          {s.population}
        </div>
        <div>
          <div className="overline">Period</div>
          {s.period}
        </div>
      </div>
      <div className="field">
        <label htmlFor="dash-title">Dashboard title</label>
        <input id="dash-title" value={outline.title} maxLength={120} onChange={(e) => onChange({ ...outline, title: e.target.value })} />
      </div>
      {outline.tabs.map((t, i) => (
        <div className="dash-tab-edit" key={t.id}>
          <div className="dash-tab-edit-head">
            <span className="overline">Tab {i + 1}</span>
            {outline.tabs.length > 1 && (
              <button
                className="icon-btn"
                aria-label={`Remove tab: ${t.name}`}
                title="Remove tab"
                onClick={() => onChange({ ...outline, tabs: outline.tabs.filter((_, j) => j !== i) })}
              >
                <Icon name="trash" />
              </button>
            )}
          </div>
          <div className="field">
            <label htmlFor={`tab-name-${t.id}`}>Name</label>
            <input id={`tab-name-${t.id}`} value={t.name} maxLength={60} onChange={(e) => setTab(i, { name: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor={`tab-q-${t.id}`}>Question this tab answers</label>
            <textarea id={`tab-q-${t.id}`} rows={2} value={t.question} maxLength={500} onChange={(e) => setTab(i, { question: e.target.value })} />
          </div>
          <div className="muted dash-tab-plan">
            <strong>Metrics:</strong> {t.metrics.join(", ")}
            <br />
            <strong>Visuals:</strong> {t.visuals.join(", ")}
          </div>
        </div>
      ))}
      <p className="field-hint">To change the provider, network or period, edit your request and propose the outline again.</p>
    </div>
  );
}

export default function DashboardsPage({ meta }: { meta?: Meta }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [mode, setMode] = useState<"ai" | "tabs">("ai");
  const [request, setRequest] = useState("");
  const [userTabs, setUserTabs] = useState<UserTab[]>([{ name: "", description: "" }]);
  const [proposing, setProposing] = useState(false);
  const [proposal, setProposal] = useState<OutlineResult | null>(null);
  const [outline, setOutline] = useState<DashboardOutline | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [buildError, setBuildError] = useState<string | null>(null);
  const [details, setDetails] = useState<{ d: DashboardSummary; kind: DetailKind } | null>(null);
  const [confirm, setConfirm] = useState<DashboardSummary | null>(null);
  const remove = useMutation({
    mutationFn: (id: string) => apiSend<void>("DELETE", `/dashboards/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dashboards"] });
      setConfirm(null);
    },
  });
  const list = useQuery({ queryKey: ["dashboards"], queryFn: () => apiGet<DashboardSummary[]>("/dashboards") });
  const days = meta?.dashboard_retention_days ?? 30;
  const effort = meta?.default_effort ?? "medium";
  const rows = list.data ?? [];
  const building = (useBuilds().data ?? []).filter((b) => b.status === "running");

  const tabsReady = mode === "ai" || userTabs.every((t) => t.name.trim() && t.description.trim());
  const outlineReady = !!outline?.title.trim() && outline.tabs.every((t) => t.name.trim() && t.question.trim());

  async function propose(text = request) {
    if (!text.trim() || proposing) return;
    setProposing(true);
    setError(null);
    setProposal(null);
    setOutline(null);
    try {
      const r = await apiSend<OutlineResult>("POST", "/dashboards/outline", {
        request: text,
        tabs: mode === "tabs" ? userTabs : [],
        effort,
      });
      setProposal(r);
      setOutline(r.outline);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setProposing(false);
    }
  }

  function answer(option: string) {
    const text = `${request.trim()}\n${option}`;
    setRequest(text);
    propose(text);
  }

  // The build runs on the server; its progress and outcome show in the build toast.
  async function generate() {
    if (!outline || starting) return;
    setStarting(true);
    setBuildError(null);
    if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
    try {
      await apiSend("POST", "/dashboards/builds", { request, outline, effort });
      qc.invalidateQueries({ queryKey: ["builds"] });
      startOver();
      setRequest("");
    } catch (e) {
      setBuildError(errorText(e));
    } finally {
      setStarting(false);
    }
  }

  function startOver() {
    setProposal(null);
    setOutline(null);
    setBuildError(null);
    setError(null);
  }

  return (
    <section className="view" aria-label="Dashboards">
      <div className="content-anim">
        <header className="topbar">
          <div>
            <h1 className="page-title">Dashboards</h1>
            <p className="page-sub">
              Narrative provider dashboards for a PCP or PCP group, with up to {MAX_TABS} tabs. Every figure is checked against
              the query results, and the result downloads as one offline HTML file.
            </p>
          </div>
        </header>
        <div className="content stack">
          <div className="card-raised dash-create">
            {!outline ? (
              <>
                <div className="card-header-row">
                  <div>
                    <div className="card-title">New dashboard</div>
                    <div className="card-subtitle">
                      Name the provider or PCP group and what you want to understand. You'll review an outline before anything
                      is built.
                    </div>
                  </div>
                  <div className="seg" role="tablist" aria-label="How to create">
                    <button role="tab" aria-selected={mode === "ai"} className={"seg-btn" + (mode === "ai" ? " active" : "")} onClick={() => setMode("ai")}>
                      Create with AI
                    </button>
                    <button role="tab" aria-selected={mode === "tabs"} className={"seg-btn" + (mode === "tabs" ? " active" : "")} onClick={() => setMode("tabs")}>
                      Define my tabs
                    </button>
                  </div>
                </div>
                <div className="field">
                  <label htmlFor="dash-request">{mode === "ai" ? "Provider and objective" : "Provider"}</label>
                  <textarea
                    id="dash-request"
                    rows={3}
                    maxLength={2000}
                    value={request}
                    placeholder={
                      mode === "ai"
                        ? "e.g. Dashboard for Dr. Sanjay Rahman: how does his attributed population's cost and utilization compare with other NEXUS PCPs, and what's driving it clinically?"
                        : "e.g. Sedgwick County Medical Group 91, last 12 months"
                    }
                    onChange={(e) => setRequest(e.target.value)}
                  />
                </div>
                {mode === "tabs" && (
                  <div className="stack">
                    {userTabs.map((t, i) => (
                      <div className="dash-tab-edit" key={i}>
                        <div className="dash-tab-edit-head">
                          <span className="overline">Tab {i + 1}</span>
                          {userTabs.length > 1 && (
                            <button
                              className="icon-btn"
                              aria-label={`Remove tab ${i + 1}`}
                              title="Remove tab"
                              onClick={() => setUserTabs(userTabs.filter((_, j) => j !== i))}
                            >
                              <Icon name="trash" />
                            </button>
                          )}
                        </div>
                        <div className="field">
                          <label htmlFor={`ut-name-${i}`}>Name</label>
                          <input
                            id={`ut-name-${i}`}
                            maxLength={60}
                            value={t.name}
                            placeholder="e.g. Clinical drivers"
                            onChange={(e) => setUserTabs(userTabs.map((u, j) => (j === i ? { ...u, name: e.target.value } : u)))}
                          />
                        </div>
                        <div className="field">
                          <label htmlFor={`ut-desc-${i}`}>What do you want to learn?</label>
                          <textarea
                            id={`ut-desc-${i}`}
                            rows={2}
                            maxLength={500}
                            value={t.description}
                            placeholder="e.g. Which diagnoses, admission categories and services drive the results. Chart preferences optional."
                            onChange={(e) =>
                              setUserTabs(userTabs.map((u, j) => (j === i ? { ...u, description: e.target.value } : u)))
                            }
                          />
                        </div>
                      </div>
                    ))}
                    {userTabs.length < MAX_TABS && (
                      <button className="btn btn-secondary dash-add-tab" onClick={() => setUserTabs([...userTabs, { name: "", description: "" }])}>
                        <Icon name="plus" />
                        Add tab
                      </button>
                    )}
                  </div>
                )}
                {proposal?.action === "clarify" && (
                  <div className="banner banner--info">
                    <Icon name="info" />
                    <span>
                      {proposal.message}
                      {proposal.options.length > 0 && (
                        <span className="dash-options">
                          {proposal.options.map((o) => (
                            <button key={o} className="pill" onClick={() => answer(o)} disabled={proposing}>
                              {o}
                            </button>
                          ))}
                        </span>
                      )}
                    </span>
                  </div>
                )}
                {proposal?.action === "decline" && (
                  <div className="banner banner--warn">
                    <Icon name="warn" />
                    <span>{proposal.message}</span>
                  </div>
                )}
                {error && (
                  <div className="banner banner--error">
                    <Icon name="warn" />
                    <span>{error}</span>
                  </div>
                )}
                <div className="form-actions">
                  {proposing && (
                    <span className="thinking" role="status">
                      <span className="spinner sm" />
                      Finding the provider and drafting an outline…
                    </span>
                  )}
                  <button className="btn btn-primary" onClick={() => propose()} disabled={proposing || !request.trim() || !tabsReady}>
                    <Icon name="sparkles" />
                    Propose outline
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="card-header-row">
                  <div>
                    <div className="card-title">Review the outline</div>
                    <div className="card-subtitle">Adjust tab names and questions, or remove a tab, then build the dashboard.</div>
                  </div>
                </div>
                <fieldset className="dash-fieldset" disabled={starting}>
                  <OutlineEditor outline={outline} onChange={setOutline} />
                </fieldset>
                {buildError && (
                  <div className="banner banner--error">
                    <Icon name="warn" />
                    <span>{buildError}</span>
                  </div>
                )}
                <div className="form-actions">
                  <button className="btn btn-secondary" onClick={startOver} disabled={starting}>
                    Start over
                  </button>
                  <button className="btn btn-primary" onClick={generate} disabled={!outlineReady || starting}>
                    <Icon name="play" />
                    {starting ? "Starting…" : buildError ? "Try again" : "Build dashboard"}
                  </button>
                </div>
                <p className="field-hint">
                  Building usually takes one to two minutes. It keeps going if you leave this page, and its progress shows in the
                  bottom-right corner.
                </p>
              </>
            )}
          </div>

          <div className="card-raised table-card">
            <div className="table-card-head">
              <div>
                <div className="card-title">Your dashboards</div>
                <div className="card-subtitle">Kept for {days} days after the last change.</div>
              </div>
              <span className="table-count">{rows.length} dashboards</span>
            </div>
            {list.isLoading ? (
              <div className="thinking" style={{ padding: 24 }}>
                <span className="spinner sm" />
                Loading dashboards…
              </div>
            ) : list.isError ? (
              <div className="banner banner--error" style={{ margin: 24 }}>
                <Icon name="warn" />
                <span>Dashboards couldn't be loaded.</span>
              </div>
            ) : rows.length === 0 && building.length === 0 ? (
              <div className="state-box" style={{ margin: 24 }}>
                <div className="state-box-title">No dashboards yet</div>
                Dashboards you build are saved here for {days} days.
              </div>
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Dashboard</th>
                      <th>Provider</th>
                      <th>Tabs</th>
                      <th>Created on</th>
                      <th>Created by</th>
                      <th>Model used</th>
                      <th className="num">Input tokens</th>
                      <th className="num">Cached tokens</th>
                      <th className="num">Output tokens</th>
                      <th className="num">Cost</th>
                      <th>Retention</th>
                      <th aria-label="Actions" />
                    </tr>
                  </thead>
                  <tbody>
                    {building.map((b) => (
                      <tr key={b.id} aria-busy="true">
                        <td>
                          <span className="conv-title">{b.title}</span>
                          <span className="badge badge--accent" style={{ marginLeft: 8 }}>
                            <span className="spinner sm" />
                            Building…
                          </span>
                        </td>
                        <td>{scopeLine(b.outline.scope)}</td>
                        <td>{b.outline.tabs.length}</td>
                        <td>{stepLabel(b.steps_done, b.steps_total)}</td>
                        <td colSpan={8} />
                      </tr>
                    ))}
                    {rows.map((d) => {
                      const missing = d.tabs.filter((t) => t.outcome !== "answered").length;
                      return (
                        <tr key={d.id} className="conv-row" onClick={() => navigate(`/dashboards/${d.id}`)}>
                          <td>
                            <Link className="conv-title" to={`/dashboards/${d.id}`} onClick={(e) => e.stopPropagation()}>
                              {d.title}
                            </Link>
                          </td>
                          <td>{scopeLine(d.scope)}</td>
                          <td>
                            {d.tabs.length}
                            {missing > 0 && (
                              <span className="badge badge--warn" style={{ marginLeft: 8 }}>
                                {missing} not answered
                              </span>
                            )}
                          </td>
                          <td>{formatDate(d.created_at)}</td>
                          <td>{d.created_by}</td>
                          <td>{d.model ? `${d.model}${d.effort ? ` (${d.effort})` : ""}` : "—"}</td>
                          <td className="num">{count(d.input_tokens)}</td>
                          <td className="num">{count(d.cached_input_tokens)}</td>
                          <td className="num">{count(d.output_tokens)}</td>
                          <td className="num">{costLabel(d)}</td>
                          <td>
                            <RetentionBadge expiresAt={new Date(new Date(d.updated_at).getTime() + days * DAY_MS).toISOString()} />
                          </td>
                          <td className="conv-actions" onClick={(e) => e.stopPropagation()}>
                            <button className="icon-btn" aria-label={`Show methodology: ${d.title}`} title="Show methodology" onClick={() => setDetails({ d, kind: "methodology" })}>
                              <Icon name="methodology" />
                            </button>
                            <button className="icon-btn" aria-label={`SQL queries: ${d.title}`} title="SQL queries" onClick={() => setDetails({ d, kind: "sql" })}>
                              <Icon name="database" />
                            </button>
                            <button className="icon-btn" aria-label={`Delete dashboard: ${d.title}`} title="Delete dashboard" onClick={() => setConfirm(d)}>
                              <Icon name="trash" />
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
      {details && (
        <DashboardDetails id={details.d.id} title={details.d.title} kind={details.kind} onClose={() => setDetails(null)} />
      )}
      {confirm && (
        <Modal onClose={() => setConfirm(null)}>
          <h2>Delete this dashboard?</h2>
          <p>“{confirm.title}” and its saved versions will be removed permanently. This can't be undone.</p>
          {remove.isError && (
            <div className="banner banner--error">
              <Icon name="warn" />
              <span>{remove.error.message}</span>
            </div>
          )}
          <div className="modal-actions">
            <button className="btn btn-secondary" onClick={() => setConfirm(null)}>
              Cancel
            </button>
            <button className="btn btn-danger" onClick={() => remove.mutate(confirm.id)} disabled={remove.isPending}>
              <Icon name="trash" />
              {remove.isPending ? "Deleting…" : "Delete"}
            </button>
          </div>
        </Modal>
      )}
    </section>
  );
}
