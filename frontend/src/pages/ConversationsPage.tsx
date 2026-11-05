import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { apiGet, apiSend } from "../lib/apiClient";
import type { ConversationSummary, Meta } from "../lib/types";
import { Icon } from "../components/Icon";
import { Modal } from "../components/Overlay";

const DAY_MS = 86_400_000;

function ageLabel(iso: string) {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / DAY_MS);
  return days <= 0 ? "Today" : days === 1 ? "Yesterday" : `${days} days ago`;
}

function RetentionBadge({ expiresAt }: { expiresAt: string }) {
  const left = Math.max(0, Math.ceil((new Date(expiresAt).getTime() - Date.now()) / DAY_MS));
  return <span className={"badge " + (left <= 3 ? "badge--warn" : "badge--neutral")}>{left}d left</span>;
}

export default function ConversationsPage({ meta }: { meta?: Meta }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState<ConversationSummary | null>(null);
  const list = useQuery({ queryKey: ["conversations"], queryFn: () => apiGet<ConversationSummary[]>("/conversations") });
  const remove = useMutation({
    mutationFn: (id: string) => apiSend<void>("DELETE", `/conversations/${id}`),
    onSuccess: (_, id) => {
      qc.removeQueries({ queryKey: ["conversation", id] });
      qc.invalidateQueries({ queryKey: ["conversations"] });
      setConfirm(null);
    },
  });
  const days = meta?.retention_days ?? 15;
  const rows = list.data ?? [];

  return (
    <section className="view" aria-label="Conversations">
      <div className="content-anim">
        <header className="topbar">
          <div>
            <h1 className="page-title">Conversations</h1>
            <p className="page-sub">Your recent analytical conversations. Reopen one to continue where you left off.</p>
          </div>
        </header>
        <div className="content stack">
          <div className="banner banner--info">
            <Icon name="info" />
            <span>
              Chat history is retained for a rolling <strong>{days} days</strong> from each message's creation time. Continuing a
              conversation does not reset earlier messages' retention.
            </span>
          </div>
          <div className="card-raised table-card">
            <div className="table-card-head">
              <div>
                <div className="card-title">Your conversations</div>
                <div className="card-subtitle">
                  Reopen a conversation and its analysis runs. Expired messages are excluded from access and model context.
                </div>
              </div>
              <span className="table-count">{rows.length} conversations</span>
            </div>
            {list.isLoading ? (
              <div className="thinking" style={{ padding: 24 }}>
                <span className="spinner sm" />
                Loading conversations…
              </div>
            ) : list.isError ? (
              <div className="banner banner--error" style={{ margin: 24 }}>
                <Icon name="warn" />
                <span>Conversations couldn't be loaded.</span>
              </div>
            ) : rows.length === 0 ? (
              <div className="state-box" style={{ margin: 24 }}>
                <div className="state-box-title">No conversations yet</div>
                Questions you ask are saved here for {days} days.
                <button className="btn btn-primary" onClick={() => navigate("/ask")}>
                  Ask a question
                </button>
              </div>
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Conversation</th>
                      <th>Scope</th>
                      <th>Last activity</th>
                      <th>Retention</th>
                      <th aria-label="Actions" />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((c) => (
                      <tr key={c.id} className="conv-row" onClick={() => navigate(`/ask/${c.id}`)}>
                        <td>
                          <Link className="conv-title" to={`/ask/${c.id}`} onClick={(e) => e.stopPropagation()}>
                            {c.title}
                          </Link>
                          {c.stale && (
                            <span className="badge badge--neutral" style={{ marginLeft: 8 }} title="Some answers use an earlier data load">
                              Earlier data
                            </span>
                          )}
                          {c.preview && <div className="muted conv-preview">{c.preview}</div>}
                        </td>
                        <td>{c.network ?? "—"}</td>
                        <td>{ageLabel(c.last_activity)}</td>
                        <td>
                          <RetentionBadge expiresAt={c.expires_at} />
                        </td>
                        <td className="conv-actions">
                          <button
                            className="icon-btn"
                            aria-label={`Delete conversation: ${c.title}`}
                            title="Delete"
                            onClick={(e) => {
                              e.stopPropagation();
                              setConfirm(c);
                            }}
                          >
                            <Icon name="trash" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
      {confirm && (
        <Modal onClose={() => setConfirm(null)}>
          <h2>Delete this conversation?</h2>
          <p>
            “{confirm.title}” and its analysis runs will be removed permanently. This can't be undone.
          </p>
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
