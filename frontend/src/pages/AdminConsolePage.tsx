import { useState } from "react";
import { Icon } from "../components/Icon";
import { Drawer } from "../components/Overlay";
import { LlmUsagePanel } from "../components/admin/LlmUsagePanel";

// shortcut: demo users and feedback from demo-static-mvp/app/js/store.js; replace with an API once Cognito users exist.
type AdminUser = { name: string; email: string; role: string; status: "Active" | "Disabled"; mfa: boolean; grants: string; last: string };
const USERS: AdminUser[] = [
  { name: "Justin Lietzen", email: "justin.lietzen@providrscare.net", role: "Administrator", status: "Active", mfa: true, grants: "All populations", last: "2m ago" },
  { name: "Priya Nair", email: "priya.nair@providrscare.net", role: "Analyst", status: "Active", mfa: true, grants: "Nexus, Summit", last: "1h ago" },
  { name: "Marco Diaz", email: "marco.diaz@providrscare.net", role: "Analyst", status: "Active", mfa: true, grants: "Nexus", last: "Yesterday" },
  { name: "Dana Cole", email: "dana.cole@providrscare.net", role: "Business user", status: "Active", mfa: false, grants: "Level 3 ABC Company", last: "3d ago" },
  { name: "Sam Okafor", email: "sam.okafor@providrscare.net", role: "Business user", status: "Disabled", mfa: false, grants: "Horizon", last: "27d ago" },
];
const FEEDBACK = [
  { q: "Admissions per 1,000 for ABC", note: "Number looked high vs. our internal report", status: "Open", by: "Dana Cole", age: "1d" },
  { q: "Referral volume by specialty", note: "Referral definition needs confirmation", status: "In review", by: "Priya Nair", age: "4d" },
  { q: "PMPM YoY comparison", note: "Reconciled — matches finance", status: "Resolved", by: "Justin Lietzen", age: "9d" },
];
const FEEDBACK_BADGE: Record<string, string> = { Open: "badge--warn", "In review": "badge--accent", Resolved: "badge--success" };

const TABS = [
  { id: "users", label: "Users", hint: "Click a user to view roles and access grants." },
  { id: "llm", label: "LLM usage", hint: "Token usage and spend from recorded model calls." },
  { id: "feedback", label: "Feedback", hint: "Feedback and flagged results routed for review." },
] as const;
type Tab = (typeof TABS)[number]["id"];

const StatusBadge = ({ u }: { u: AdminUser }) => (
  <span className={"badge " + (u.status === "Active" ? "badge--success" : "badge--danger")}>
    <span className="badge-dot" />
    {u.status}
  </span>
);
const MfaBadge = ({ on }: { on: boolean }) =>
  on ? <span className="badge badge--success">MFA on</span> : <span className="badge badge--warn">No MFA</span>;

function UsersPanel() {
  const [open, setOpen] = useState<AdminUser | null>(null);
  return (
    <div className="card" style={{ padding: 18 }}>
      <div className="card-header-row" style={{ marginBottom: 14 }}>
        <div>
          <div className="card-title" style={{ fontSize: "1.0625rem" }}>Users</div>
          <div className="card-subtitle" style={{ marginBottom: 0 }}>
            Roles and client/group/plan/population access grants. Sample users until sign-in is connected.
          </div>
        </div>
        <button className="btn btn-primary" disabled title="Available once sign-in is connected">
          <Icon name="plus" />
          Add user
        </button>
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>User</th>
              <th>Role</th>
              <th>Status</th>
              <th>MFA</th>
              <th>Grants</th>
              <th>Last active</th>
            </tr>
          </thead>
          <tbody>
            {USERS.map((u) => (
              <tr key={u.email} style={{ cursor: "pointer" }} onClick={() => setOpen(u)}>
                <td>
                  <div style={{ fontWeight: 500, color: "#123137" }}>{u.name}</div>
                  <div className="muted" style={{ fontSize: "0.78rem" }}>{u.email}</div>
                </td>
                <td><span className="badge badge--accent">{u.role}</span></td>
                <td><StatusBadge u={u} /></td>
                <td><MfaBadge on={u.mfa} /></td>
                <td>{u.grants}</td>
                <td className="muted">{u.last}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {open && <UserDrawer u={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function UserDrawer({ u, onClose }: { u: AdminUser; onClose: () => void }) {
  const business = u.role === "Business user";
  return (
    <Drawer title={u.name} sub={u.email} onClose={onClose}>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <span className="badge badge--accent">{u.role}</span>
        <StatusBadge u={u} />
        <MfaBadge on={u.mfa} />
      </div>
      <div>
        <div className="form-section-title">Role</div>
        <div className="field" style={{ marginBottom: 0 }}>
          <select defaultValue={u.role} aria-label="Role">
            <option>Administrator</option>
            <option>Analyst</option>
            <option>Business user</option>
          </select>
        </div>
      </div>
      <div>
        <div className="form-section-title">Access grants</div>
        <dl className="dl">
          <dt>Populations</dt>
          <dd>{u.grants}</dd>
          <dt>Member-level</dt>
          <dd>{business ? "Aggregate only" : "Permitted"}</dd>
          <dt>Export</dt>
          <dd>{business ? "CSV only" : "All formats"}</dd>
        </dl>
      </div>
      <div className="form-actions">
        <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={onClose}>Save changes</button>
      </div>
      <div style={{ borderTop: "1px solid var(--line)", paddingTop: 16 }}>
        <div className="form-section-title">Session &amp; credentials</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn btn-secondary">Resend invite</button>
          <button className="btn btn-secondary">Reset password</button>
          <button className="btn btn-danger">{u.status === "Active" ? "Disable account" : "Enable account"}</button>
        </div>
      </div>
    </Drawer>
  );
}

function FeedbackPanel() {
  return (
    <div className="card" style={{ padding: 18 }}>
      <div className="card-title" style={{ fontSize: "1.0625rem" }}>Feedback &amp; flagged results</div>
      <div className="card-subtitle">User feedback does not automatically change organization-wide calculation rules.</div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Question</th>
              <th>Note</th>
              <th>Status</th>
              <th>By</th>
              <th>Age</th>
            </tr>
          </thead>
          <tbody>
            {FEEDBACK.map((f) => (
              <tr key={f.q}>
                <td style={{ fontWeight: 500, color: "#123137" }}>{f.q}</td>
                <td className="muted">{f.note}</td>
                <td><span className={"badge " + FEEDBACK_BADGE[f.status]}>{f.status}</span></td>
                <td>{f.by}</td>
                <td className="muted">{f.age}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function AdminConsolePage() {
  const [tab, setTab] = useState<Tab>("users");
  return (
    <section className="view" aria-label="Admin Console">
      <div className="content-anim">
        <header className="topbar">
          <div>
            <h1 className="page-title">Admin Console</h1>
            <p className="page-sub">Manage users, roles and access, review LLM usage and spend, and review feedback.</p>
          </div>
        </header>
        <div className="content">
          <div className="subtabs" role="tablist">
            {TABS.map((t) => (
              <button
                key={t.id}
                role="tab"
                aria-selected={tab === t.id}
                className={"subtab" + (tab === t.id ? " active" : "")}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            ))}
            <span className="spacer" />
            <span className="muted" style={{ fontSize: "0.8125rem", alignSelf: "center" }}>
              {TABS.find((t) => t.id === tab)!.hint}
            </span>
          </div>
          {tab === "users" ? <UsersPanel /> : tab === "llm" ? <LlmUsagePanel /> : <FeedbackPanel />}
        </div>
      </div>
    </section>
  );
}
