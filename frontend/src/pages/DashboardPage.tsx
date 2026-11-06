import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ApiError, apiGet, BASE_URL } from "../lib/apiClient";
import { formatDate } from "../lib/format";
import type { Meta, SavedDashboard } from "../lib/types";
import { Icon } from "../components/Icon";
import { scopeLine } from "./DashboardsPage";

export default function DashboardPage({ meta }: { meta?: Meta }) {
  const { dashboardId } = useParams();
  const dash = useQuery({
    queryKey: ["dashboard", dashboardId],
    queryFn: () => apiGet<SavedDashboard>(`/dashboards/${dashboardId}`),
    retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 2,
  });
  const url = `${BASE_URL}/dashboards/${dashboardId}/dashboard.html`;
  const d = dash.data;
  const missing = d?.spec.tabs.filter((t) => t.outcome !== "answered") ?? [];

  return (
    <section className="view" aria-label="Dashboard">
      <div className="content-anim">
        <header className="topbar">
          <div>
            <Link className="link-btn" to="/dashboards">
              ← All dashboards
            </Link>
            <h1 className="page-title">{d?.title ?? "Dashboard"}</h1>
            {d && (
              <p className="page-sub">
                {scopeLine(d.outline.scope)} · {d.outline.scope.period} · version {d.version}, built {formatDate(d.created_at)}
              </p>
            )}
          </div>
          {d && (
            <div className="topbar-actions">
              <a className="btn btn-secondary" href={`/dashboards/${dashboardId}/view`} target="_blank" rel="noopener">
                <Icon name="arrowRight" />
                View dashboard
              </a>
              <a className="btn btn-primary" href={`${url}?download=true`} download>
                <Icon name="download" />
                Download HTML
              </a>
            </div>
          )}
        </header>
        <div className="content stack">
          {dash.isLoading ? (
            <div className="thinking">
              <span className="spinner sm" />
              Loading dashboard…
            </div>
          ) : dash.error instanceof ApiError && dash.error.status === 404 ? (
            <div className="state-box">
              <div className="state-box-title">This dashboard is no longer available</div>
              It may have passed the {meta?.dashboard_retention_days ?? 30}-day retention period.
              <Link className="btn btn-primary" to="/dashboards">
                Back to dashboards
              </Link>
            </div>
          ) : dash.isError ? (
            <div className="banner banner--error">
              <Icon name="warn" />
              <span>The dashboard couldn't be loaded.</span>
            </div>
          ) : (
            <>
              <div className="muted dash-request">
                <strong>Request:</strong> {d!.request}
              </div>
              {missing.length > 0 && (
                <div className="banner banner--warn">
                  <Icon name="warn" />
                  <span>
                    {missing.map((t) => t.name).join(", ")} couldn't be answered from the available data. The tab explains why.
                  </span>
                </div>
              )}
              <iframe className="dash-preview" title="Dashboard preview" sandbox="allow-scripts allow-downloads" referrerPolicy="no-referrer" src={url} />
            </>
          )}
        </div>
      </div>
    </section>
  );
}
