# Dashboard Builder (LLM-Generated Static Dashboards)

Users describe a dashboard in plain language. An LLM agent generates a static HTML/CSS/JS dashboard, the app shows a live preview, and the user can download it as a zip. This document covers how to build that safely and reliably. It builds on `architecture.md`, `llm-best-practices.md` and `llm-usage-metrics.md`.

---

## 1. The Core Rule

> **Generated code is untrusted code.** Treat every file the LLM writes as if a stranger wrote it.

Users can ask for anything, and data or instructions in the prompt can steer the model through prompt injection. Any design decision below that seems strict exists because of this rule. The security boundary is **the sandbox and the CSP**, not the prompt and not the validator.

---

## 2. Choosing a Generation Approach

There are three ways to have the agent build a dashboard:

| Approach | How it works | Flexibility | Reliability | Risk | Verdict |
|---|---|---|---|---|---|
| **A. Direct files** | LLM returns `index.html`, `styles.css`, `app.js` as structured output | High | Medium | Low, as long as the output is sandboxed | ✅ **Recommended for MVP** |
| **B. Spec + templates** | LLM returns a JSON spec (layout, chart types, fields); our own code renders it | Low–medium | Very high | Very low | ✅ Good later for "standard" dashboards |
| **C. Code execution** | LLM writes a Python script; we run it to produce the files | High | Medium | **High** (arbitrary code on our server) | ❌ Avoid unless properly sandboxed |

### Why not have the LLM write a Python script?

It's possible, but running a Python script means **running LLM-written code on your backend**. That is remote code execution by design. The script could read environment variables (including your OpenAI key and database URL), reach the network, or fill up the disk. Making it safe requires a real sandbox: a separate container or microVM (gVisor, Firecracker, or a hosted sandbox service) with no network, no secrets, a read-only filesystem except an output directory, and CPU, memory and time limits. That's a lot of infrastructure, and it **gains nothing** here. The output is static HTML/CSS/JS either way, and the LLM can write those files directly.

Python *is* useful for the **data**: aggregating, filtering and shaping numbers for charts. Have the LLM call **predefined, server-written data tools** (§5) instead of writing that code itself.

Reconsider approach C only if you later need arbitrary computation, such as statistical modelling of user-uploaded files. Even then, run it in an isolated sandbox service, never in the API container.

---

## 3. Architecture

```
User prompt ─▶ POST /api/v1/dashboards/generate (SSE)
                     │
                     ▼
      ┌─────────────── LangGraph: dashboard_builder ───────────────┐
      │                                                            │
      │  plan ──▶ fetch_data ──▶ generate ──▶ validate ──┬─▶ save  │
      │   │         (tools,        (structured    │      │         │
      │   │         user-scoped)   files)         ▼      │         │
      │   │                                    repair ───┘ (max 2) │
      └───┼────────────────────────────────────────────────────────┘
          │ status events: "Planning layout…", "Loading sales data…",
          │ "Building charts…", "Checking output…", "Fixing 2 issues…"
          ▼
   Frontend ─▶ sandboxed <iframe srcDoc> preview ─▶ "Download .zip"
```

| Node | Responsibility | Streams tokens to user? |
|---|---|---|
| `plan` | Turn the request into a short layout plan: sections, charts, KPIs, filters | No (status only) |
| `fetch_data` | Call allowlisted data tools, build a data snapshot | No |
| `generate` | Produce the files as structured output | No |
| `validate` | Check the schema, paths, sizes, required structure and lint rules | No |
| `repair` | Send the validation errors back to the LLM and regenerate the affected files | No |
| `save` | Store a new version and return its ID | No |

None of these nodes go into `PUBLIC_TOKEN_NODES`. The user sees status messages only, and the preview appears when the run finishes.

---

## 4. The File Contract

The LLM produces a **fixed, small set of files**. Everything else is added by the server.

```
dashboard-name/
├── index.html            ← LLM
├── styles.css            ← LLM
├── app.js                ← LLM
├── data.js               ← SERVER (window.DASHBOARD_DATA = {...})
└── vendor/
    └── chart.umd.min.js  ← SERVER (pinned copy we ship, never LLM-written)
```

Some of these choices are deliberate:

- **`data.js` instead of `data.json`.** `fetch("data.json")` fails when someone opens the downloaded `index.html` from disk, because browsers block `fetch` on `file://`. A script tag that sets `window.DASHBOARD_DATA` works everywhere.
- **Vendor libraries come from the server.** We keep a vetted, version-pinned copy of each allowed library such as Chart.js. The zip works offline, there's no CDN dependency, and the model can't pull in arbitrary scripts.
- **The LLM never writes `data.js`.** It only sees the data **schema and a few sample rows** (§5).

### Pydantic schema

```python
import re
from pydantic import BaseModel, Field, field_validator, model_validator

LLM_PATHS = {"index.html", "styles.css", "app.js"}
MAX_FILE_CHARS = 150_000

class GeneratedFile(BaseModel):
    path: str
    content: str = Field(max_length=MAX_FILE_CHARS)

    @field_validator("path")
    @classmethod
    def allowed_path(cls, v: str) -> str:
        if v not in LLM_PATHS:
            raise ValueError(f"path not allowed: {v}")
        return v

class DashboardFiles(BaseModel):
    title: str = Field(max_length=120)
    files: list[GeneratedFile] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def all_required_files(self):
        if {f.path for f in self.files} != LLM_PATHS:
            raise ValueError(f"must contain exactly {sorted(LLM_PATHS)}")
        return self
```

Generate with `model.with_structured_output(DashboardFiles)` and give the call a generous `max_tokens` budget, because full files are large.

---

## 5. Data: Snapshot, Not Access

The dashboard **never calls our API**. Data reaches it like this:

1. **`fetch_data`** lets the LLM pick from **predefined data tools** that we write, for example `get_sales_by_month(start, end, region)` or `get_top_products(limit)`. Each tool:
   - runs with the **server-side user's** permissions (it never trusts IDs supplied by the model);
   - uses parameterized queries we wrote ourselves, never SQL from the LLM;
   - caps the number of rows returned.
2. The server builds the snapshot `{ "sales_by_month": [...], "top_products": [...] }`.
3. The `generate` prompt receives only the **shape** of that snapshot: field names, types and 3–5 sample rows. It does **not** receive the full data.
4. The server writes the full snapshot into `data.js` when it bundles the dashboard.

This has three benefits. Fewer tokens means lower cost and faster generation. Less user data is sent to OpenAI. And the generated code works with any data of the same shape, so a "refresh data" action can regenerate `data.js` without calling the LLM again.

> Avoid free-form natural language → SQL for the MVP. If you add it later, use a read-only DB role, row-level security, a statement timeout, a row limit and a read replica.

---

## 6. Validation

Validation keeps the **quality** high. It is not the security boundary (the sandbox and CSP are), but it catches broken or suspicious output early and feeds the repair loop.

| Check | Rule |
|---|---|
| Schema | Pydantic `DashboardFiles` passes |
| Structure | `index.html` has `<!DOCTYPE html>`, `<head>`, `<body>`, and references `styles.css`, `data.js`, `app.js` |
| Scripts | `<script src>` only points to `app.js`, `data.js` or `vendor/*` from the allowlist; no inline `<script>` blocks |
| Links | No external `<link>`, `<img src="http…">`, `@import url(http…)` or web fonts from remote URLs |
| JS lint (heuristic) | Flag `fetch(`, `XMLHttpRequest`, `WebSocket`, `sendBeacon`, `eval(`, `new Function`, `document.cookie`, `localStorage`, `window.parent`, `window.top`, `postMessage`, dynamic `import(` |
| Data usage | `app.js` references `window.DASHBOARD_DATA` |
| Size | Each file ≤ 150k chars; the total bundle stays within the configured limit |

The repair loop works like this. If validation fails, send the **specific errors** back with the previous files and ask for corrected versions of only the failing files. Allow at most **2 repair attempts**, then fail with a friendly message.

As an optional upgrade, render the bundle in headless Chromium (Playwright) inside a worker, capture console errors and blank-chart detection, and feed those into the repair loop as well. That catches runtime bugs the static checks can't see.

---

## 7. Preview (Sandbox + CSP)

### Bundling for preview

A `srcDoc` iframe can't resolve relative files, so the server inlines everything into one HTML string for the preview. The zip keeps the separate files.

```python
import re

PREVIEW_CSP = (
    "default-src 'none'; "
    "script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; "
    "img-src data: blob:; "
    "font-src data:; "
    "connect-src 'none'; "
    "form-action 'none'; "
    "base-uri 'none'"
)

def _safe_inline_js(js: str) -> str:
    return js.replace("</script", "<\\/script")

def bundle_for_preview(files: dict[str, str]) -> str:
    """files: path → content, including server-provided data.js and vendor/*."""
    html = files["index.html"]

    def inline_script(m: re.Match) -> str:
        src = m.group("src")
        return f"<script>{_safe_inline_js(files[src])}</script>" if src in files else ""

    html = re.sub(r'<script[^>]*\bsrc="(?P<src>[^"]+)"[^>]*>\s*</script>', inline_script, html)
    html = re.sub(r'<link[^>]*\bhref="styles\.css"[^>]*>',
                  lambda _: f"<style>{files['styles.css']}</style>", html)
    csp = f'<meta http-equiv="Content-Security-Policy" content="{PREVIEW_CSP}">'
    return re.sub(r"<head[^>]*>", lambda m: m.group(0) + csp, html, count=1)
```

### Rendering

```tsx
export function DashboardPreview({ html }: { html: string }) {
  return (
    <iframe
      title="Dashboard preview"
      sandbox="allow-scripts"   // never add allow-same-origin
      srcDoc={html}
      referrerPolicy="no-referrer"
      className="h-full w-full border-0"
    />
  );
}
```

Leaving out `allow-same-origin` gives the iframe an **opaque origin**. Code inside can't read our cookies, storage or DOM, and can't make authenticated requests to our API. The CSP's `connect-src 'none'` additionally blocks any network calls. Together these mean even malicious generated JS has nothing to steal and nowhere to send it.

**Later:** serve previews from a separate domain (for example `usercontent.yourapp.com`) via an endpoint instead of `srcDoc`. This adds isolation at the browser-process and cookie level, and it's what large platforms do.

---

## 8. Storage and Versioning

Every generation or edit creates a **new version**. Nothing is ever overwritten.

```
dashboards
  id (UUID PK), user_id, title, current_version, created_at, updated_at

dashboard_versions
  id (UUID PK), dashboard_id (FK), version (int), UNIQUE(dashboard_id, version)
  files          JSONB   -- {"index.html": "...", "styles.css": "...", "app.js": "..."}
  data_snapshot  JSONB   -- source for data.js
  vendor_libs    JSONB   -- e.g. ["chart.js@4.4.1"]
  validation     JSONB   -- warnings, repair attempts
  llm_run_id     UUID    -- → llm_metrics.llm_runs.id (cost per version!)
  created_at
```

Move `files` to object storage (S3/MinIO) if versions get large. For the MVP, JSONB in Postgres is fine.

**Editing** ("make the revenue chart a bar chart") works like this: send the current files, the plan and the change request, and ask for **only the changed files**. The server merges them, validates, and saves the result as version N+1. Returning only changed files is cheaper and stops the model from rewriting parts the user liked.

---

## 9. Zip Download

```python
import io, re, zipfile
from fastapi.responses import StreamingResponse

def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "dashboard"

@router.get("/dashboards/{dashboard_id}/versions/{version}/download")
async def download_dashboard(dashboard_id: UUID, version: int,
                             user=Depends(current_user), svc=Depends(get_dashboard_service)):
    v = await svc.get_version_for_user(user, dashboard_id, version)   # 404 if not owner
    files = svc.build_download_files(v)   # LLM files + data.js + vendor/*, paths from allowlist
    slug = _slug(v.title)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(f"{slug}/{path}", content)
        zf.writestr(f"{slug}/README.txt",
                    "Open index.html in a browser. Data snapshot generated at "
                    f"{v.created_at.isoformat()}.\n")
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{slug}.zip"'},
    )
```

Paths inside the zip only ever come from our allowlist, never from user or LLM input. That rules out path traversal (`../`) attacks, often called "zip slip", for anyone who unzips the file.

---

## 10. Prompting Tips

- **State the contract exactly:** the three file names, that `index.html` must load `vendor/chart.umd.min.js`, `data.js`, `styles.css` and `app.js` in that order, and that there must be no other external resources.
- **Describe the data shape**, not the data: field names, types, units and sample rows from §5.
- **Give the design tokens** from `frontend/src/styles/tokens.css` (which came from the `mvp/` prototypes) so dashboards match the app's look. Include colors, fonts, spacing and radius.
- **List the available libraries with exact versions**, for example "Chart.js 4.x is available as global `Chart`". Without this the model invents APIs from other versions.
- **Require quality basics:** responsive layout (CSS grid), readable labels, number formatting, empty-state handling, accessible contrast, and no console errors.
- **Use the `plan` node** to agree on sections before writing code. Generation is more consistent when the model writes code against a short plan.
- **Keep prompts in `llm/prompts/dashboard_*.md`**, versioned like code.

---

## 11. Things to Avoid

- ❌ Rendering generated HTML in the main app DOM (`dangerouslySetInnerHTML`), or in an iframe with `allow-same-origin`.
- ❌ Executing LLM-written Python, SQL or shell commands on the API server.
- ❌ Letting the dashboard call your API, or putting tokens or API keys anywhere in generated files.
- ❌ Loading scripts, fonts or images from arbitrary CDNs. Ship pinned vendor copies instead.
- ❌ Sending full datasets to the LLM. Send the schema and samples only.
- ❌ Relying on the validator, or on prompt instructions like "don't use fetch", as the security boundary.
- ❌ Overwriting versions in place. You lose undo, auditing and cost history.
- ❌ Unbounded repair loops or unlimited generations per user, which make costs explode.
- ❌ Streaming the raw JSON tokens from `generate` to the user. It's useless to them, and it bypasses validation.
- ❌ Building zip paths from LLM- or user-supplied file names.

---

## 12. Limits and Cost

| Limit | Suggested starting value |
|---|---|
| Max output tokens (`generate`) | ~16k |
| Repair attempts | 2 |
| Rows per data tool | 5,000 |
| Total `data.js` size | 2 MB |
| Generations per user per day | e.g. 20 (tune using `llm_metrics`) |
| Total run timeout | 120 s |

Tag runs with `feature="dashboard_builder"` in `UsageTracker`, and store `llm_run_id` on each version so you can see the cost of every dashboard and every edit.

---

## 13. Checklist

- [ ] Preview iframe uses `sandbox="allow-scripts"` **without** `allow-same-origin`
- [ ] Preview bundle injects a CSP with `connect-src 'none'`
- [ ] LLM output validated by `DashboardFiles`; only allowlisted paths accepted
- [ ] `data.js` and `vendor/*` produced by the server, never by the LLM
- [ ] Data tools are server-written, user-scoped and row-limited
- [ ] LLM receives the data schema and samples, not full data
- [ ] Repair loop capped; run timeout set
- [ ] Each edit creates a new version linked to `llm_run_id`
- [ ] Download endpoint checks ownership; zip paths come from the allowlist
- [ ] `generate` / `repair` are not in `PUBLIC_TOKEN_NODES`; status events cover every node
