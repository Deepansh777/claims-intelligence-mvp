# Architecture

This document describes the architecture, repository layout, and development workflow for the application. It is the reference for where code lives, how the pieces talk to each other, and how to run everything locally inside the dev container.

## 1. Overview

The application is a three-tier web app with an LLM integration:

| Layer        | Technology                                  | Responsibility                                          |
|--------------|---------------------------------------------|---------------------------------------------------------|
| Frontend     | React + TypeScript + Vite                   | UI, routing, client state, calling the backend API      |
| Backend      | Python 3.12 + FastAPI                       | REST API, business logic, auth, LLM orchestration       |
| LLM          | OpenAI API (via official `openai` SDK)      | Text generation / completions, called **only** from backend |
| Database     | PostgreSQL 16                               | Persistent storage                                      |
| Dev env      | Docker Compose + VS Code Dev Container      | Reproducible, one-command local environment             |

```
┌──────────────┐     HTTP/JSON      ┌──────────────────┐     SQL      ┌──────────────┐
│  React SPA   │ ─────────────────▶ │  FastAPI backend │ ───────────▶ │  PostgreSQL  │
│  (Vite dev)  │ ◀───────────────── │                  │ ◀─────────── │              │
└──────────────┘   /api/v1/...      └────────┬─────────┘              └──────────────┘
                                             │ HTTPS
                                             ▼
                                     ┌──────────────┐
                                     │  OpenAI API  │
                                     └──────────────┘
```

Key principle: **the OpenAI API key never reaches the browser.** The frontend only talks to our backend; the backend is the sole client of OpenAI.

## 2. Repository Layout

A monorepo with clear top-level boundaries. Each app (`frontend`, `backend`) is self-contained with its own dependencies, tests, and Dockerfile.

```
project-root/
├── .devcontainer/
│   ├── devcontainer.json          # VS Code dev container definition
│   └── Dockerfile                 # Dev workspace image (Python + Node + tools)
│
├── docker-compose.yml             # Services: workspace, db (and optional pgadmin)
├── docker-compose.prod.yml        # Production-like overrides (optional, later)
├── .env.example                   # Template for required env vars (committed)
├── .env                           # Real secrets (NOT committed)
├── .gitignore
├── Makefile                       # Shortcuts: make dev, make test, make migrate...
├── README.md                      # Quick start
├── ARCHITECTURE.md                # This document
│
├── demo-static-mvp/                           # Static HTML/CSS/JS prototypes — REFERENCE ONLY
│   ├── app/                   
│   ├── branding/
│   ├── data/
│   └── diagram/
│
├── frontend/                      # React app
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   ├── public/
│   └── src/
│       ├── main.tsx               # Entry point
│       ├── App.tsx                # Providers + router outlet
│       ├── routes/                # Route definitions / page-level components
│       ├── features/              # Feature modules (see §4.1)
│       │   └── <feature>/
│       │       ├── components/
│       │       ├── hooks/
│       │       ├── api.ts         # API calls for this feature
│       │       └── types.ts
│       ├── components/            # Shared, generic UI (Button, Modal, Layout)
│       ├── lib/
│       │   ├── apiClient.ts       # fetch/axios wrapper, base URL, error handling
│       │   └── utils.ts
│       ├── hooks/                 # Shared hooks
│       ├── styles/
│       │   ├── tokens.css         # Design tokens ported from mvp/css
│       │   └── global.css
│       └── types/                 # Shared types (ideally generated from OpenAPI)
│
├── backend/                       # FastAPI app
│   ├── Dockerfile
│   ├── pyproject.toml             # Dependencies + tool config (ruff, pytest, mypy)
│   ├── alembic.ini
│   ├── alembic/
│   │   └── versions/              # Migration scripts
│   ├── app/
│   │   ├── main.py                # FastAPI app factory, middleware, router mount
│   │   ├── core/
│   │   │   ├── config.py          # Pydantic Settings (reads env vars)
│   │   │   ├── security.py        # Auth helpers (JWT, password hashing)
│   │   │   └── logging.py
│   │   ├── db/
│   │   │   ├── base.py            # SQLAlchemy Base
│   │   │   └── session.py         # Engine + session dependency
│   │   ├── api/
│   │   │   ├── deps.py            # Shared dependencies (db session, current user)
│   │   │   └── v1/
│   │   │       ├── router.py      # Aggregates all v1 routers
│   │   │       └── routes/        # One module per resource (users.py, chat.py…)
│   │   ├── models/                # SQLAlchemy ORM models (DB shape)
│   │   ├── schemas/               # Pydantic models (API request/response shape)
│   │   ├── repositories/          # DB access — queries only, no business logic
│   │   ├── services/              # Business logic, orchestrates repos + LLM
│   │   └── llm/
│   │       ├── client.py          # OpenAI client wrapper (timeouts, retries)
│   │       ├── prompts/           # Prompt templates (versioned, in files)
│   │       └── schemas.py         # Structured output models for LLM responses
│   └── tests/
│       ├── conftest.py
│       ├── unit/
│       └── integration/
│
└── scripts/                       # One-off utilities: seed data, db reset, etc.
```

### Why this structure

The top level separates things that deploy separately (`frontend`, `backend`) from things that support development (`.devcontainer`, `scripts`, `mvp`). Inside the backend, a layered structure (routes → services → repositories → models) keeps HTTP concerns, business logic, and data access apart, which makes each layer testable on its own. Inside the frontend, a feature-based structure keeps everything for one feature in one folder, which scales much better than grouping by file type once the app grows past a handful of screens.

## 3. Backend

### 3.1 Layers and responsibilities

| Layer           | Folder               | Knows about                  | Must NOT                                   |
|-----------------|----------------------|------------------------------|--------------------------------------------|
| Routes          | `api/v1/routes/`     | HTTP, schemas, services      | Contain business logic or raw SQL          |
| Schemas         | `schemas/`           | Pydantic only                | Import ORM models directly into responses  |
| Services        | `services/`          | Repositories, LLM client     | Know about `Request`/`Response` objects    |
| Repositories    | `repositories/`      | ORM models, DB session       | Call OpenAI or contain business rules      |
| Models          | `models/`            | SQLAlchemy                   | Contain API logic                          |
| LLM             | `llm/`               | OpenAI SDK, prompts          | Touch the database                         |

A request flows: **route** validates input via a schema → calls a **service** → service uses **repositories** and/or the **LLM client** → returns data → route serializes it with a response schema.

### 3.2 Key libraries

FastAPI, Uvicorn, Pydantic v2 + `pydantic-settings`, SQLAlchemy 2.x (async, with `asyncpg`), Alembic for migrations, `openai` SDK, `httpx`, pytest + `pytest-asyncio`, and Ruff for linting/formatting.

### 3.3 Configuration

All configuration comes from environment variables, loaded once in `core/config.py`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str
    openai_api_key: str
    openai_model: str = "gpt-4o-mini"
    openai_timeout_seconds: int = 30
    cors_origins: list[str] = ["http://localhost:5173"]

settings = Settings()
```

No module reads `os.environ` directly; everything imports `settings`.

### 3.4 API conventions

All endpoints live under `/api/v1/`. Resources use plural nouns (`/api/v1/conversations`). Errors return a consistent JSON shape (`{"detail": "...", "code": "..."}`). FastAPI auto-generates OpenAPI docs at `/docs`, and that spec is the contract with the frontend.

## 4. Frontend

### 4.1 Feature-based organization

Each feature folder under `src/features/` owns its components, hooks, API calls, and types. Shared, reusable pieces graduate to `src/components/` or `src/hooks/` only once a second feature needs them.

### 4.2 Key libraries

Vite, React, TypeScript, React Router for routing, TanStack Query for server state (fetching, caching, loading/error states), and Vitest + React Testing Library for tests. Local UI state stays in React state; add a global store (e.g. Zustand) only if a real need appears.

### 4.3 Talking to the backend

All HTTP calls go through `lib/apiClient.ts`, which sets the base URL from `import.meta.env.VITE_API_BASE_URL` and normalizes errors. In development, Vite proxies `/api` to the backend so there are no CORS issues:

```ts
// vite.config.ts
server: {
  host: "0.0.0.0",
  port: 5173,
  proxy: { "/api": "http://localhost:8000" },
}
```

Types for API payloads should be generated from the backend's OpenAPI spec (e.g. `openapi-typescript`) into `src/types/api.ts`, so frontend and backend can't silently drift apart.

## 5. The `mvp/` Folder

The `mvp/` folder holds the static HTML/CSS/JS prototypes. It is **reference material, not source code**: nothing in `frontend/` imports from it, and it is not part of any build.

How to use it when building React screens:

1. **Extract design tokens first.** Pull colors, spacing, font sizes, radii, and shadows out of `mvp/css/` into CSS custom properties in `frontend/src/styles/tokens.css`. Every React component uses these tokens rather than hard-coded values.
2. **Map pages to routes.** Each `mvp/pages/*.html` corresponds to a route in `frontend/src/routes/`. Track the mapping and porting status in `mvp/README.md`.
3. **Map repeated markup to components.** Headers, cards, buttons, and form fields that repeat across prototypes become shared components in `src/components/`.
4. **Rewrite, don't copy, the JS.** Prototype JS (DOM manipulation, fake data) is replaced by React state and real API calls. Use it only to understand intended behavior.
5. **Freeze once ported.** When a screen is fully implemented in React, mark it as done in `mvp/README.md`; the React version becomes the source of truth from then on.

To view prototypes during development, open them directly or serve the folder with `python -m http.server 8080 --directory mvp` (port 8080 is forwarded by the dev container).

## 6. LLM Integration

All OpenAI access goes through `backend/app/llm/client.py`, a thin wrapper that adds timeouts, retries with backoff, logging of token usage, and a single place to swap models.

```python
from openai import AsyncOpenAI
from app.core.config import settings

_client = AsyncOpenAI(
    api_key=settings.openai_api_key,
    timeout=settings.openai_timeout_seconds,
    max_retries=2,
)

async def complete(messages: list[dict], model: str | None = None) -> str:
    response = await _client.chat.completions.create(
        model=model or settings.openai_model,
        messages=messages,
    )
    return response.choices[0].message.content or ""
```

Guidelines:

- **Prompts live in files** under `llm/prompts/`, not inline in services, so they can be reviewed and versioned.
- **Use structured outputs** (Pydantic models in `llm/schemas.py`) whenever the response feeds program logic rather than being shown as text.
- **Stream long responses** to the frontend via Server-Sent Events (`StreamingResponse`) for chat-like UX.
- **Mock the LLM in tests.** Unit and integration tests never call the real OpenAI API; the client is replaced via a FastAPI dependency override.
- **Protect cost and abuse:** add per-user rate limiting and input length limits on any endpoint that triggers an LLM call.

## 7. Database

PostgreSQL runs as its own container. The backend connects with SQLAlchemy 2.x async sessions, provided per-request through a dependency in `api/deps.py`.

Schema changes are made **only through Alembic migrations**:

```bash
cd backend
alembic revision --autogenerate -m "add conversations table"
alembic upgrade head
```

Conventions: snake_case table and column names, a UUID or bigint `id` primary key, and `created_at` / `updated_at` timestamps on every table. Data persists in a named Docker volume (`pgdata`) so it survives container rebuilds.

## 8. Development Environment

### 8.1 Approach

Docker Compose defines the services; the dev container attaches VS Code to a `workspace` service that has both Python and Node installed. The frontend and backend dev servers run inside that workspace with hot reload, while Postgres runs in its own container. This keeps a single editor session and terminal for the whole stack while still isolating the database.

### 8.2 `docker-compose.yml`

```yaml
services:
  workspace:
    build:
      context: .
      dockerfile: .devcontainer/Dockerfile
    volumes:
      - .:/workspace:cached
      - frontend_node_modules:/workspace/frontend/node_modules
    env_file: .env
    command: sleep infinity
    depends_on:
      db:
        condition: service_healthy

  db:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      retries: 10

volumes:
  pgdata:
  frontend_node_modules:
```

The named volume for `node_modules` avoids slow file syncing and OS-specific binary conflicts between host and container.

### 8.3 `.devcontainer/Dockerfile`

```dockerfile
FROM mcr.microsoft.com/devcontainers/python:3.12

# Node.js for the frontend
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
```

### 8.4 `.devcontainer/devcontainer.json`

```json
{
  "name": "fullstack-app",
  "dockerComposeFile": ["../docker-compose.yml"],
  "service": "workspace",
  "workspaceFolder": "/workspace",
  "shutdownAction": "stopCompose",

  "forwardPorts": [5173, 8000, 5432, 8080],
  "portsAttributes": {
    "5173": { "label": "Frontend (Vite)" },
    "8000": { "label": "Backend (FastAPI)" },
    "5432": { "label": "Postgres" },
    "8080": { "label": "MVP prototypes" }
  },

  "postCreateCommand": "cd backend && pip install -e '.[dev]' && cd ../frontend && npm install",

  "customizations": {
    "vscode": {
      "extensions": [
        "ms-python.python",
        "ms-python.vscode-pylance",
        "charliermarsh.ruff",
        "dbaeumer.vscode-eslint",
        "esbenp.prettier-vscode",
        "ckolkman.vscode-postgres"
      ],
      "settings": {
        "python.defaultInterpreterPath": "/usr/local/bin/python",
        "editor.formatOnSave": true,
        "[python]": { "editor.defaultFormatter": "charliermarsh.ruff" },
        "[typescript][typescriptreact]": { "editor.defaultFormatter": "esbenp.prettier-vscode" }
      }
    }
  }
}
```

### 8.5 Environment variables

`.env.example` is committed; `.env` is created from it and git-ignored.

```env
# Database
POSTGRES_USER=app
POSTGRES_PASSWORD=app
POSTGRES_DB=app
DATABASE_URL=postgresql+asyncpg://app:app@db:5432/app

# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

# App
ENVIRONMENT=development
CORS_ORIGINS=["http://localhost:5173"]
VITE_API_BASE_URL=/api/v1
```

Note that the backend reaches Postgres at host `db` (the Compose service name), not `localhost`.

### 8.6 Daily workflow

```bash
# Backend (terminal 1)
cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Frontend (terminal 2)
cd frontend && npm run dev

# Migrations
cd backend && alembic upgrade head
```

Wrap these in `Makefile` targets (`make backend`, `make frontend`, `make migrate`, `make test`) so nobody has to remember the flags.

## 9. Testing

| Scope                | Tooling                          | Location                     |
|----------------------|----------------------------------|------------------------------|
| Backend unit         | pytest, LLM client mocked        | `backend/tests/unit/`        |
| Backend integration  | pytest + test Postgres database  | `backend/tests/integration/` |
| Frontend unit        | Vitest + React Testing Library   | next to components (`*.test.tsx`) |
| End-to-end (later)   | Playwright                       | `e2e/` at repo root          |

Integration tests run against a separate database (e.g. `app_test`) and roll back each test inside a transaction.

## 10. Security Notes

Secrets live only in `.env` locally and in a secret manager in deployed environments; they are never committed or exposed via `VITE_*` variables (anything prefixed `VITE_` is bundled into the browser). CORS is restricted to known frontend origins. All user input is validated by Pydantic schemas before reaching services, and user-supplied text sent to the LLM is treated as untrusted (length-limited and kept separate from system prompts).

## 11. Path to Production (later)

Each app gets a production Dockerfile: the frontend builds static assets served by Nginx (or a CDN), and the backend runs Uvicorn/Gunicorn workers. Postgres moves to a managed service. A CI pipeline runs lint, type checks, tests, and migrations on every pull request. These are out of scope for the MVP but the structure above is designed so none of it requires reorganizing the repo.
