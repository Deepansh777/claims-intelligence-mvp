import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ApiError, apiGet, apiSend } from "../lib/apiClient";
import { AUTO_DISMISS_MS, autoDismisses, clock, stepLabel } from "../lib/builds";
import type { BuildStatus, DashboardBuild } from "../lib/types";
import { Icon } from "./Icon";
import { Modal } from "./Overlay";

const POLL_MS = 1500;
const TICK_MS = 1000;
const ERROR_TEXT = "Something went wrong. Please try again.";
const APP_TITLE = document.title;
const ENDED: Record<BuildStatus, string> = { running: "", built: "Built in", failed: "Failed after", cancelled: "Cancelled after" };

const time = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });

function BuildToast({
  build: b,
  fetchedAt,
  onHide,
  onCancel,
  onDismiss,
  onOpen,
  onRetry,
}: {
  build: DashboardBuild;
  fetchedAt: number;
  onHide: () => void;
  onCancel: () => void;
  onDismiss: () => void;
  onOpen: () => void;
  onRetry: () => Promise<void>;
}) {
  const [expanded, setExpanded] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [left, setLeft] = useState(AUTO_DISMISS_MS);
  const [now, setNow] = useState(Date.now());
  const [retryError, setRetryError] = useState<string | null>(null);
  const running = b.status === "running";
  const timed = autoDismisses(b.status);
  const paused = hovered || focused || expanded;

  useEffect(() => {
    if (!running && !timed) return;
    const id = setInterval(() => {
      setNow(Date.now());
      if (timed && !paused) setLeft((l) => l - TICK_MS);
    }, TICK_MS);
    return () => clearInterval(id);
  }, [running, timed, paused]);

  useEffect(() => {
    if (timed && left <= 0) onDismiss();
  }, [timed, left, onDismiss]);

  const latest = b.events[b.events.length - 1]?.message ?? "Starting the build…";
  const elapsed = clock(b.elapsed_ms + (running ? now - fetchedAt : 0));
  const outcome = {
    running: latest,
    built: "Saved to Your Dashboards.",
    cancelled: "Build cancelled. Nothing was saved.",
    failed: `${b.error ?? ERROR_TEXT}${b.failed_step ? ` Stopped at: ${b.failed_step}` : ""}`,
  }[b.status];

  async function retry() {
    setRetryError(null);
    try {
      await onRetry();
    } catch (e) {
      setRetryError(e instanceof ApiError ? e.message : ERROR_TEXT);
    }
  }

  return (
    <div
      className={`build-toast build-toast--${b.status}`}
      role="group"
      aria-label={`Dashboard build: ${b.title}`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setFocused(true)}
      onBlur={(e) => !e.currentTarget.contains(e.relatedTarget) && setFocused(false)}
    >
      <div className="build-toast-head">
        {running ? <span className="spinner sm" /> : <Icon name={b.status === "built" ? "check" : b.status === "failed" ? "warn" : "stop"} />}
        <div className="build-toast-text">
          <div className="build-toast-title">{b.title}</div>
          <div className="build-toast-meta">
            {running
              ? `${stepLabel(b.steps_done, b.steps_total)} · ${elapsed}`
              : `${ENDED[b.status]} ${elapsed}`}
          </div>
          <div className="build-toast-message" aria-live="polite">
            {outcome}
          </div>
        </div>
        <button
          className="icon-btn"
          aria-expanded={expanded}
          aria-label={expanded ? "Hide activity" : "Show activity"}
          title={expanded ? "Hide activity" : "Show activity"}
          onClick={() => setExpanded((x) => !x)}
        >
          <Icon name={expanded ? "chevronDown" : "chevronRight"} />
        </button>
      </div>
      {expanded && (
        <ol className="build-toast-events" aria-label="Build activity">
          {b.events.map((e, i) => (
            <li key={i}>
              <time dateTime={e.at}>{time(e.at)}</time>
              <span>{e.message}</span>
            </li>
          ))}
          {b.events.length === 0 && <li className="muted">No activity yet.</li>}
        </ol>
      )}
      {retryError && (
        <div className="banner banner--error">
          <Icon name="warn" />
          <span>{retryError}</span>
        </div>
      )}
      <div className="build-toast-actions">
        {running ? (
          <>
            <button className="btn btn-text" onClick={onHide}>
              Hide
            </button>
            <button className="btn btn-secondary" onClick={onCancel}>
              Cancel
            </button>
          </>
        ) : (
          <>
            <button className="btn btn-text" onClick={onDismiss}>
              Dismiss
            </button>
            {b.status === "built" && (
              <button className="btn btn-primary" onClick={onOpen}>
                Open dashboard
              </button>
            )}
            {b.status === "failed" && (
              <button className="btn btn-primary" onClick={retry}>
                <Icon name="refresh" />
                Retry
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/** The user's running builds and undismissed outcomes, polled while any build runs. */
export const useBuilds = () =>
  useQuery({
    queryKey: ["builds"],
    queryFn: () => apiGet<DashboardBuild[]>("/dashboards/builds"),
    refetchInterval: (q) => (q.state.data?.some((b) => b.status === "running") ? POLL_MS : false),
    // Keep polling in a background tab so the finished build can retitle the tab and notify.
    refetchIntervalInBackground: true,
  });

function announce(b: DashboardBuild) {
  const text = b.status === "built" ? "Dashboard ready" : "Dashboard build failed";
  document.title = `${text} · ${APP_TITLE}`;
  if ("Notification" in window && Notification.permission === "granted") new Notification(text, { body: b.title });
}

/** Progress and outcome of the user's dashboard builds, on every tab. */
export function BuildToasts() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const builds = useBuilds();
  const lastStatus = useRef(new Map<string, BuildStatus>());
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [confirm, setConfirm] = useState<DashboardBuild | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const list = (builds.data ?? []).filter((b) => !dismissed.has(b.id));
  const isHidden = (b: DashboardBuild) => b.status === "running" && hidden.has(b.id);
  const hiddenCount = list.filter(isHidden).length;
  const builtKey = list.filter((b) => b.status === "built").map((b) => b.id).join();

  useEffect(() => {
    if (builtKey) qc.invalidateQueries({ queryKey: ["dashboards"] });
  }, [builtKey, qc]);

  useEffect(() => {
    for (const b of builds.data ?? []) {
      const finished = lastStatus.current.get(b.id) === "running" && (b.status === "built" || b.status === "failed");
      if (finished && document.hidden) announce(b);
      lastStatus.current.set(b.id, b.status);
    }
  }, [builds.data]);

  useEffect(() => {
    const restore = () => !document.hidden && (document.title = APP_TITLE);
    document.addEventListener("visibilitychange", restore);
    return () => document.removeEventListener("visibilitychange", restore);
  }, []);

  const dismiss = (b: DashboardBuild) => {
    setDismissed((s) => new Set(s).add(b.id));
    apiSend("POST", `/dashboards/builds/${b.id}/seen`).catch(() => {});
  };

  const closeConfirm = () => {
    setConfirm(null);
    setCancelError(null);
  };

  async function cancel(b: DashboardBuild) {
    setCancelling(true);
    setCancelError(null);
    try {
      await apiSend("POST", `/dashboards/builds/${b.id}/cancel`);
      closeConfirm();
    } catch (e) {
      // 409: it finished first, and the refetch below shows that outcome instead.
      if (e instanceof ApiError && e.status === 409) closeConfirm();
      else setCancelError(e instanceof ApiError ? e.message : ERROR_TEXT);
    } finally {
      setCancelling(false);
      qc.invalidateQueries({ queryKey: ["builds"] });
    }
  }

  async function retry(b: DashboardBuild) {
    await apiSend("POST", "/dashboards/builds", { request: b.request, outline: b.outline, effort: b.effort });
    dismiss(b);
    qc.invalidateQueries({ queryKey: ["builds"] });
  }

  if (list.length === 0) return null;
  return (
    <>
      <div className="build-toasts">
        {list
          .filter((b) => !isHidden(b))
          .map((b) => (
            <BuildToast
              key={b.id}
              build={b}
              fetchedAt={builds.dataUpdatedAt}
              onHide={() => setHidden((s) => new Set(s).add(b.id))}
              onCancel={() => setConfirm(b)}
              onDismiss={() => dismiss(b)}
              onOpen={() => {
                dismiss(b);
                navigate(`/dashboards/${b.dashboard_id}`);
              }}
              onRetry={() => retry(b)}
            />
          ))}
        {hiddenCount > 0 && (
          <button className="build-chip" onClick={() => setHidden(new Set())} aria-label="Show running dashboard builds">
            <span className="spinner sm" />
            {hiddenCount === 1 ? "1 build running" : `${hiddenCount} builds running`}
          </button>
        )}
      </div>
      {confirm && (
        <Modal onClose={closeConfirm}>
          <h2>Cancel this build?</h2>
          <p>Building “{confirm.title}” will stop and nothing will be saved. Progress so far will be lost.</p>
          {cancelError && (
            <div className="banner banner--error">
              <Icon name="warn" />
              <span>{cancelError}</span>
            </div>
          )}
          <div className="modal-actions">
            <button className="btn btn-secondary" onClick={closeConfirm}>
              Keep building
            </button>
            <button className="btn btn-danger" onClick={() => cancel(confirm)} disabled={cancelling}>
              <Icon name="stop" />
              {cancelling ? "Cancelling…" : "Cancel build"}
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
