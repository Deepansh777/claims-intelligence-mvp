import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import { apiGet } from "./lib/apiClient";
import { formatDate } from "./lib/format";
import type { Meta } from "./lib/types";
import { BuildToasts } from "./components/BuildToasts";
import { CellTooltip } from "./components/CellTooltip";
import { Icon } from "./components/Icon";
import AskPage from "./pages/AskPage";
import ConversationsPage from "./pages/ConversationsPage";
import DashboardPage from "./pages/DashboardPage";
import DashboardsPage from "./pages/DashboardsPage";
import DashboardViewPage from "./pages/DashboardViewPage";
import ExplorerPage from "./pages/ExplorerPage";
import logoUrl from "./assets/logo.png";

// shortcut: single fixed user until Cognito sign-in exists (backend: settings.app_user_id).
const USER = { name: "Local user", initials: "LU" };

function Sidebar({ meta, collapsed, onCollapse }: { meta?: Meta; collapsed: boolean; onCollapse: () => void }) {
  const loaded = meta?.dataset_version;
  return (
    <aside className="sidebar">
      <div className="brand">
        <img className="brand-logo" src={logoUrl} alt="ProviDRs Care" />
        <span className="brand-mark">PC</span>
      </div>
      <div className="period-pill">
        <div className="period-pill-label">Data loaded</div>
        <div className="period-pill-value">{loaded ? formatDate(loaded.created_at) : "No data loaded"}</div>
      </div>
      <div className="nav-section-label">Workspace</div>
      <nav className="nav">
        <NavLink
          to="/ask"
          className={({ isActive }) => "nav-item" + (isActive ? " active" : "")}
          title={collapsed ? "Ask" : undefined}
        >
          <Icon name="ask" />
          <span className="nav-label">Ask</span>
        </NavLink>
        <NavLink
          to="/conversations"
          className={({ isActive }) => "nav-item" + (isActive ? " active" : "")}
          title={collapsed ? "Conversations" : undefined}
        >
          <Icon name="conversations" />
          <span className="nav-label">Conversations</span>
        </NavLink>
        <NavLink
          to="/dashboards"
          className={({ isActive }) => "nav-item" + (isActive ? " active" : "")}
          title={collapsed ? "Dashboards" : undefined}
        >
          <Icon name="dashboard" />
          <span className="nav-label">Dashboards</span>
        </NavLink>
        <NavLink
          to="/explorer"
          className={({ isActive }) => "nav-item" + (isActive ? " active" : "")}
          title={collapsed ? "Data Explorer" : undefined}
        >
          <Icon name="database" />
          <span className="nav-label">Data Explorer</span>
        </NavLink>
      </nav>
      <div className="sidebar-footer">
        <div className="user-chip">
          <span className="user-avatar">{USER.initials}</span>
          <span className="user-meta">
            <div className="user-name">{USER.name}</div>
            <div className="user-role">{meta?.is_admin ? "Administrator" : "Analyst"}</div>
          </span>
        </div>
        <button
          className="footer-btn collapse-btn"
          onClick={onCollapse}
          aria-expanded={!collapsed}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <Icon name="collapse" />
          <span className="footer-btn-label">Collapse</span>
        </button>
      </div>
    </aside>
  );
}

export default function App() {
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => apiGet<Meta>("/meta") });
  const [collapsed, setCollapsed] = useState(false);
  return (
    <div className={"app" + (collapsed ? " collapsed" : "")}>
      <Sidebar meta={meta.data} collapsed={collapsed} onCollapse={() => setCollapsed((c) => !c)} />
      <main className="main">
        {meta.isError && (
          <div className="status-banner">
            <Icon name="warn" />
            <span>
              <strong>Backend unreachable.</strong> Answers can't be loaded until the API is running.
            </span>
          </div>
        )}
        <Routes>
          <Route path="/ask/:conversationId?" element={<AskPage meta={meta.data} />} />
          <Route path="/conversations" element={<ConversationsPage meta={meta.data} />} />
          <Route path="/explorer" element={<ExplorerPage />} />
          <Route path="/dashboards" element={<DashboardsPage meta={meta.data} />} />
          <Route path="/dashboards/:dashboardId" element={<DashboardPage meta={meta.data} />} />
          <Route path="/dashboards/:dashboardId/view" element={<DashboardViewPage />} />
          <Route path="*" element={<Navigate to="/ask" replace />} />
        </Routes>
      </main>
      <BuildToasts />
      <CellTooltip />
    </div>
  );
}
