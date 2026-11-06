import { useParams } from "react-router-dom";
import { Icon } from "../components/Icon";
import { BASE_URL } from "../lib/apiClient";

/** The exported file itself, isolated: no allow-same-origin, so it can't reach the app or API. */
export default function DashboardViewPage() {
  const { dashboardId } = useParams();
  const url = `${BASE_URL}/dashboards/${dashboardId}/dashboard.html`;
  return (
    <div className="dash-view">
      <div className="dash-view-bar">
        <span className="muted">Dashboard snapshot — the same file as the download.</span>
        <a className="btn btn-secondary" href={`${url}?download=true`} download>
          <Icon name="download" />
          Download HTML
        </a>
      </div>
      <iframe className="dash-view-frame" title="Dashboard" sandbox="allow-scripts" referrerPolicy="no-referrer" src={url} />
    </div>
  );
}
