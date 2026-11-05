import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { ApiError, apiGet, apiSend, apiStream } from "../lib/apiClient";
import type { Answer, Conversation, Message, Meta } from "../lib/types";
import { Icon } from "../components/Icon";
import { Modal } from "../components/Overlay";
import { AnswerView, RetryButton } from "../components/answer/AnswerView";

const SUGGESTIONS = [
  { label: "PMPM", text: "How did NEXUS PMPM change over the last 12 months?" },
  { label: "Admissions", text: "Which PCPs have the highest admissions per 1,000 members?" },
  { label: "Chronic conditions", text: "How many diabetic members are there by age group?" },
  { label: "Risk vs spending", text: "Is member risk score associated with total allowed spending?" },
  { label: "Care gaps", text: "List members with overdue care gaps." },
  { label: "Definitions", text: "What does PMPM mean?" },
];

const NETWORK_INFO: Record<string, string> = {
  NEXUS: "NEXUS network members",
  PCN: "PCN network members",
  BOTH: "NEXUS and PCN combined",
};
const EFFORT_INFO: Record<string, string> = {
  low: "Fastest and cheapest; fine for simple lookups",
  medium: "Balanced; covers most questions",
  high: "Slower; for multi-step or tricky questions",
};
const STILL_WORKING_MS = 15000;

type Pending = { question: string; status: string; lastEventAt: number; answer?: Answer; error?: string; cancelled?: boolean };

function UserMsg({ text }: { text: string }) {
  return (
    <div className="msg msg-user">
      <div className="msg-avatar">LU</div>
      <div className="msg-body">
        <div className="bubble">{text}</div>
      </div>
    </div>
  );
}

function AssistantMsg({ children }: { children: ReactNode }) {
  return (
    <div className="msg msg-assistant">
      <div className="msg-avatar">AI</div>
      <div className="msg-body">{children}</div>
    </div>
  );
}

function Thinking({ status, lastEventAt }: { status: string; lastEventAt: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="thinking" role="status">
      <span className="spinner sm" />
      {status}
      {now - lastEventAt > STILL_WORKING_MS && " Still working…"}
    </div>
  );
}

function Menu({
  id,
  open,
  setOpen,
  title,
  button,
  items,
  value,
  onPick,
}: {
  id: string;
  open: string | null;
  setOpen: (m: string | null) => void;
  title: string;
  button: ReactNode;
  items: { id: string; name: string; desc: string }[];
  value: string;
  onPick: (v: string) => void;
}) {
  return (
    <div className="tool-wrap" onClick={(e) => e.stopPropagation()}>
      <button className="tool-btn" aria-haspopup="listbox" aria-expanded={open === id} onClick={() => setOpen(open === id ? null : id)}>
        {button}
        <Icon name="chevronDown" />
      </button>
      {open === id && (
        <div className="menu" role="listbox">
          <div className="menu-title">{title}</div>
          {items.map((it) => (
            <button
              key={it.id}
              className={"menu-item" + (it.id === value ? " selected" : "")}
              role="option"
              aria-selected={it.id === value}
              onClick={() => {
                onPick(it.id);
                setOpen(null);
              }}
            >
              <span className="mi-main">
                <span className="mi-name">{it.name}</span>
                <span className="mi-desc">{it.desc}</span>
              </span>
              <span className="mi-check">{it.id === value && <Icon name="check" />}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function TipsModal({ onClose }: { onClose: () => void }) {
  const cards = [
    ["Be specific", "Name the metric, population, period and date basis.", "Good: “Total PMPM for NEXUS, Jan–Dec 2025, by service month.”"],
    ["One topic per chat", "Start a new chat when the subject changes so old context doesn’t bleed in.", "Use New chat above."],
    ["Pick the network", "Questions that don’t name a network use the one chosen under the question box.", "NEXUS is the default; choose PCN or both."],
    ["Keep effort low unless needed", "Low or Medium covers most questions. Use High for tricky cohorts and reconciliations.", "Higher effort costs more and takes longer."],
    ["Refine with follow-ups", "Build on a result: “Now break that out by PCP.” Ask one thing at a time.", "Avoid stacking many requests in one message."],
    ["Verify before you share", "Open View analysis to check the interpretation, SQL and provenance.", "Results are only as good as the definitions used."],
  ];
  return (
    <Modal onClose={onClose} large>
      <h2>Getting better results from Ask</h2>
      <p>Six habits that give faster, cheaper and more accurate answers.</p>
      <div className="guide-grid">
        {cards.map(([title, text, tip], i) => (
          <div className="guide-card" key={title}>
            <div className="guide-num">{i + 1}</div>
            <div>
              <div className="guide-title">{title}</div>
              <div className="guide-text">{text}</div>
              <div className="guide-tip">{tip}</div>
            </div>
          </div>
        ))}
      </div>
      <div className="guide-compare">
        <div className="gc gc--bad">
          <span>Vague</span>“Show me costs.”
        </div>
        <div className="gc gc--good">
          <span>Clear</span>“Admission PMPM by month for PCN in 2025.”
        </div>
      </div>
      <div className="modal-actions">
        <button className="btn btn-primary" onClick={onClose}>
          Got it
        </button>
      </div>
    </Modal>
  );
}

export default function AskPage({ meta }: { meta?: Meta }) {
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [pending, setPending] = useState<Pending | null>(null);
  const [network, setNetwork] = useState<string>();
  const [effort, setEffort] = useState<string>();
  const [menu, setMenu] = useState<string | null>(null);
  const [tips, setTips] = useState(false);
  const [draft, setDraft] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Paused while a question is in flight so the stored copy of it doesn't appear twice.
  const conversation = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () => apiGet<Conversation>(`/conversations/${conversationId}`),
    enabled: !!conversationId && !pending,
  });
  const messages: Message[] = conversation.data?.messages ?? [];
  const busy = !!pending && !pending.answer && !pending.error && !pending.cancelled;
  const net = network ?? meta?.default_network ?? "NEXUS";
  const eff = effort ?? meta?.default_effort ?? "medium";
  const isAdmin = !!meta?.is_admin;

  useEffect(() => () => abortRef.current?.abort(), []);
  useEffect(() => {
    const close = () => setMenu(null);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, []);
  useEffect(() => {
    window.scrollTo(0, document.body.scrollHeight);
  }, [messages.length, pending?.status, pending?.answer]);

  const refresh = (id: string) => {
    qc.invalidateQueries({ queryKey: ["conversations"] });
    return qc.fetchQuery({ queryKey: ["conversation", id], queryFn: () => apiGet<Conversation>(`/conversations/${id}`) });
  };

  async function ask(question: string) {
    question = question.trim();
    if (!question || busy) return;
    // A stopped or failed exchange is only shown locally; load its stored copy before replacing it.
    if (pending && conversationId) await refresh(conversationId).catch(() => undefined);
    const controller = new AbortController();
    abortRef.current = controller;
    setPending({ question, status: "Sending your question…", lastEventAt: Date.now() });
    const update = (patch: Partial<Pending>) => setPending((p) => p && { ...p, ...patch, lastEventAt: Date.now() });
    try {
      let id = conversationId;
      if (!id) {
        id = (await apiSend<{ id: string }>("POST", "/conversations")).id;
        navigate(`/ask/${id}`);
      }
      await apiStream(
        `/conversations/${id}/messages/stream`,
        { question, network: net, effort: eff, client_request_id: crypto.randomUUID() },
        (event, data) => {
          if (event === "status") update({ status: data.message });
          else if (event === "result") update({ answer: data });
          else if (event === "error") update({ error: data.message });
        },
        controller.signal,
      );
      // The stored copy, including any error, replaces the streamed one.
      await refresh(id);
      setPending(null);
    } catch (e) {
      if (controller.signal.aborted) return;
      update({ error: e instanceof ApiError ? e.message : "Something went wrong. Please try again." });
    }
  }

  // Closing the stream makes the server stop the run and save it as cancelled.
  function stop() {
    abortRef.current?.abort();
    setPending((p) => p && { ...p, cancelled: true });
  }

  async function rerun(runId: string) {
    await apiSend("POST", `/runs/${runId}/rerun`);
    await refresh(conversationId!);
  }

  function newChat() {
    abortRef.current?.abort();
    setPending(null);
    navigate("/ask");
    textareaRef.current?.focus();
  }

  const send = () => {
    if (busy || !draft.trim()) return;
    ask(draft);
    setDraft("");
  };
  const empty = !conversationId && !pending;
  const missing = conversation.error instanceof ApiError && conversation.error.status === 404;

  return (
    <section className="view" aria-label="Ask">
      <div className="content-anim">
        <header className="topbar">
          <div>
            <h1 className="page-title">Ask</h1>
            <p className="page-sub">
              Conversational analysis over eligibility and claims. Every answer shows its interpretation, SQL and provenance.
            </p>
          </div>
          <div className="topbar-actions">
            <button className="btn btn-secondary" onClick={() => setTips(true)}>
              <Icon name="info" />
              Tips for better results
            </button>
            <button className="btn btn-secondary" onClick={newChat} disabled={empty}>
              <Icon name="plus" />
              New chat
            </button>
          </div>
        </header>
        <div className="content">
          <div className="ask-layout">
            <div className="transcript">
              {empty && (
                <div className="ask-welcome">
                  <h2>Ask a question about eligibility and claims</h2>
                  <p className="muted">
                    Describe an analysis in plain language. The platform interprets it, applies approved definitions, runs read-only
                    SQL, checks every figure against the results, and shows its work.
                  </p>
                  <div className="suggest-grid">
                    {SUGGESTIONS.map((s) => (
                      <button key={s.text} className="suggest-chip" onClick={() => ask(s.text)}>
                        <span className="sc-label">{s.label}</span>
                        {s.text}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {missing && (
                <div className="state-box">
                  <div className="state-box-title">This conversation is no longer available</div>
                  It may have been deleted or passed the {meta?.retention_days ?? 15}-day retention period.
                  <button className="btn btn-primary" onClick={newChat}>
                    Start a new chat
                  </button>
                </div>
              )}
              {conversation.isLoading && !pending && (
                <div className="thinking">
                  <span className="spinner sm" />
                  Loading conversation…
                </div>
              )}
              {messages.map((m, i) => {
                if (m.role === "user") return <UserMsg key={m.id} text={m.content} />;
                const question = messages[i - 1]?.role === "user" ? messages[i - 1].content : null;
                const retry = question ? () => ask(question) : undefined;
                return (
                  <AssistantMsg key={m.id}>
                    {m.answer ? (
                      <AnswerView
                        answer={m.answer}
                        onAsk={ask}
                        onRetry={retry}
                        onRerun={() => rerun(m.answer!.run_id)}
                        busy={busy}
                        isAdmin={isAdmin}
                      />
                    ) : m.status === "running" ? (
                      <div className="thinking">
                        <span className="spinner sm" />
                        This answer was still in progress when the page loaded.
                      </div>
                    ) : (
                      <div className="banner banner--error">
                        <Icon name="warn" />
                        <span>{m.content || "This answer could not be completed."}</span>
                        {retry && <RetryButton onRetry={retry} disabled={busy} />}
                      </div>
                    )}
                  </AssistantMsg>
                );
              })}
              {pending && (
                <>
                  <UserMsg text={pending.question} />
                  <AssistantMsg>
                    {pending.answer ? (
                      <AnswerView answer={pending.answer} onAsk={ask} busy={busy} isAdmin={isAdmin} />
                    ) : pending.error || pending.cancelled ? (
                      <div className={`banner banner--${pending.error ? "error" : "warn"}`}>
                        <Icon name="warn" />
                        <span>{pending.error ?? "Stopped before an answer was ready."}</span>
                        <RetryButton onRetry={() => ask(pending.question)} disabled={false} />
                      </div>
                    ) : (
                      <Thinking status={pending.status} lastEventAt={pending.lastEventAt} />
                    )}
                  </AssistantMsg>
                </>
              )}
            </div>
            <div className="composer-wrap">
              {!empty && (
                <div className="newchat-note">
                  <Icon name="info" />
                  <span>
                    <strong>Changing topic?</strong> Start a new chat. Long threads carry earlier context, which can blur answers
                    and use more tokens.
                  </span>
                  <button className="link-btn" onClick={newChat}>
                    Start new chat
                  </button>
                </div>
              )}
              <div className="composer">
                <textarea
                  ref={textareaRef}
                  rows={1}
                  value={draft}
                  maxLength={2000}
                  aria-label="Your question"
                  placeholder="Ask about PMPM, admissions, ER, eligibility, care gaps…"
                  onChange={(e) => {
                    setDraft(e.target.value);
                    e.target.style.height = "auto";
                    e.target.style.height = `${Math.min(160, e.target.scrollHeight)}px`;
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      send();
                    }
                  }}
                />
                <div className="composer-bar">
                  <div className="composer-tools">
                    <span className="tool-btn tool-static" title="Configured model">
                      <Icon name="sparkles" />
                      <span>{meta?.model ?? "Model"}</span>
                    </span>
                    <Menu
                      id="effort"
                      open={menu}
                      setOpen={setMenu}
                      title="Effort level"
                      button={
                        <>
                          <span className="tool-label">Effort</span>
                          <span>{eff[0].toUpperCase() + eff.slice(1)}</span>
                        </>
                      }
                      items={(meta?.efforts ?? ["low", "medium", "high"]).map((e) => ({
                        id: e,
                        name: e[0].toUpperCase() + e.slice(1),
                        desc: EFFORT_INFO[e] ?? "",
                      }))}
                      value={eff}
                      onPick={setEffort}
                    />
                    <Menu
                      id="network"
                      open={menu}
                      setOpen={setMenu}
                      title="Default network"
                      button={
                        <>
                          <span className="tool-label">Network</span>
                          <span>{net}</span>
                        </>
                      }
                      items={(meta?.networks ?? ["NEXUS", "PCN", "BOTH"]).map((n) => ({
                        id: n,
                        name: n === "BOTH" ? "Both" : n,
                        desc: NETWORK_INFO[n] ?? "",
                      }))}
                      value={net}
                      onPick={setNetwork}
                    />
                  </div>
                  {busy ? (
                    <button className="composer-send is-stop" onClick={stop} aria-label="Stop" title="Stop this answer">
                      <Icon name="stop" />
                    </button>
                  ) : (
                    <button className="composer-send" onClick={send} disabled={!draft.trim()} aria-label="Send">
                      <Icon name="send" />
                    </button>
                  )}
                </div>
              </div>
              <div className="composer-scope">
                <span className="dot" />
                Questions that don’t name a network use <strong style={{ margin: "0 3px" }}>{net === "BOTH" ? "NEXUS + PCN" : net}</strong>·
                conversations are kept {meta?.retention_days ?? 15} days
              </div>
            </div>
          </div>
        </div>
      </div>
      {tips && <TipsModal onClose={() => setTips(false)} />}
    </section>
  );
}
