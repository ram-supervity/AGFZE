<div align="center">

# AGFZE Command Centre

### The operations platform for AGFZE's non-ferrous metal scrap trade - correspondence in, governed deals out.

<p>
  <em>Every document from the shared mailbox, classified and extracted by AI, checked against thirteen business rules, approved by a person, posted to SAP - with every step auditable and every figure traceable back to its source.</em>
</p>

<br/>

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-15.5-000000?logo=next.js&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-4169E1?logo=postgresql&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-5.7-3178C6?logo=typescript&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind-3.4-06B6D4?logo=tailwindcss&logoColor=white)

![Tests: backend](https://img.shields.io/badge/Backend_tests-721_pytest_cases-2ea44f)
![Tests: frontend](https://img.shields.io/badge/Frontend_tests-349_vitest_cases-2ea44f)
![Lint](https://img.shields.io/badge/Linting-Ruff_%2B_ESLint-f7b500)
![Migrations](https://img.shields.io/badge/Migrations-Alembic_21_revisions-844fba)
![Deployment](https://img.shields.io/badge/Deploy-GCP_Cloud_Run_%2B_Terraform-4285F4?logo=googlecloud&logoColor=white)
![Last commit](https://img.shields.io/badge/Last_commit-2026--08--29-3e3e3e)

<br/>

</div>

---

## Table of Contents

- [About the Project](#-about-the-project)
- [Key Features](#-key-features)
- [Tech Stack](#-tech-stack)
- [Project Structure](#-project-structure)
- [Getting Started](#-getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Environment Variables](#environment-variables)
  - [Running the Project](#running-the-project)
- [Usage](#-usage)
- [API Documentation](#-api-documentation)
- [Configuration](#-configuration)
- [Testing](#-testing)
- [Deployment](#-deployment)
- [Contributing](#-contributing)
- [Roadmap](#-roadmap)
- [License](#-license)
- [Acknowledgements](#-acknowledgements)
- [Contact / Author](#-contact--author)

---

## 📖 About the Project

AGFZE trades non-ferrous metal scrap between the UAE and Singapore, and like every trading house its days are governed by a shared mailbox, a spreadsheet tracker, and a lot of judgement about which documents are trustworthy. The Command Centre replaces the mailbox-as-process with a governed pipeline: a supplier's invoice lands in the approved shared mailbox, the platform classifies it, extracts the fields the document type demands, matches it to the batch and deal it belongs to, checks it against the thirteen business rules AGFZE's governing material defines, and stops at every step you would want it to stop at. AI never decides - it proposes, with a confidence score and evidence, and a person confirms.

This is an internal operations platform built for the desks that actually work the trade - purchase, sales, FA, logistics, finance, the HOD who approves, the auditor who watches. What makes it different is the discipline: nothing is guessed on the model's behalf, nothing is posted to SAP that was not approved, every number on a report links back to the query that produced it, and the append-only audit trail records who touched what, when, and why. The audit trail, the rule engine, and the exception queue are the real product; the AI is just a well-behaved clerk with schema validation.

---

## ✨ Key Features

- **Mailbox-first intake** - a dedicated Azure AD machine identity polls (and subscribes to) the approved shared mailbox via Microsoft Graph; the webhook and the delta poll converge on one deduplicated ingestion funnel, so one message can never become two requests.
- **AI classification with honesty built in** - every email and document is classified by Gemini against an explicit schema; anything below the confidence threshold, or any model failure, lands in a visible *needs human review* state rather than being guessed onward.
- **Schema-driven extraction** - field lists live in the `document_type_schemas` table, so adding a field or a document type is a row change, not a code change; multi-page conflicts are flagged for a person, never silently resolved.
- **Deterministic batch matching** - the `rapidfuzz` matcher answers "which deal is this?" reproducibly; it is deliberately not an AI call, and a batch link is verified against reference numbers, quantities and counterparty similarity.
- **Thirteen governing business rules, plus the sales rules** - BR-01…BR-13 (traceability, reference presence, container agreement, mandatory packs, quantity and invoice-value tolerance, OBL gating, duplication links…) are evaluator-registered and per-rule configurable, with `IV-01` (invoice dating), `SL-01` (cross-shipment contract coverage) and `LG-01` (invoiced weight vs. bill of lading) alongside.
- **Exceptions with owners, age and escalation** - a failing rule opens a case owned by the desk that works the leg; cases age visibly, can be escalated to the HOD, and resolve only through a genuine fix or an explicit person's decision.
- **Maker-checker approvals** - ranked approval queue (age, value or risk), AI-summarised one-time, self-approval refused outright, bulk approval capped by a configured ceiling, and every decision stamped with the verified token's identity.
- **Shipments from container to claim** - containers arrive as a side effect of matching; shipments track milestones, ETAs, bills of lading and post-delivery issues, with a staleness sweep that opens an owned exception when nobody has established where cargo is.
- **Honest downstream integrations** - SAP, DMS and the Excel tracker adapters prepare complete payloads and post them when configured; unconfigured, a job lands in `awaiting_manual_action` with everything a person needs, and *no* code path can report a posting that never happened.
- **Real reporting with drill-through** - scheduled daily and monthly reports (PDF + XLSX) are generated from the governed tables at generation time; every figure carries the filters that reproduce it, and every page states that the platform has not sent it to anybody.
- **Three notification channels, one seam** - in-app (always), email (Jinja2 templates over SMTP), and Web Push (VAPID) all flow through the single `notify()` function; each fails independently and honestly.
- **PWA with read-only offline** - a hand-written service worker precached at build time serves the shell and stale reads offline, but no mutating request is ever cached or queued: offline support is a governance boundary, not an unfinished feature.
- **Security posture that refuses bad configs** - the production settings profile fails start-up if credentials, rate limits, a shared Redis counter store, an exact-origin CORS list or a signed-URL secret are missing; HSTS, CSP and no-store headers ride every response.
- **Traceability graph (optional, derived)** - an opt-in Neo4j projection, rebuildable at any moment, answering "what is this transaction connected to?" to a bounded depth.

---

## 🧰 Tech Stack

### Frontend
| Technology | Version | Purpose |
|---|---|---|
| Next.js | 15.5.24 | App Router, React Server Components, `standalone` output |
| React / React DOM | 19.0.0 | UI runtime |
| TypeScript | 5.7.2 | Type safety across app, components and API client |
| Tailwind CSS | 3.4.17 | Styling, with CSS variables and `tailwindcss-animate` |
| shadcn/ui (new-york) + Radix UI | - | Accessible primitives: dialog, dropdown, tooltip, scroll-area, avatar, separator, slot |
| next-auth | 4.24.11 | Keycloak OIDC (authorization-code + PKCE) with silent refresh |
| framer-motion, lucide-react, cmdk | - | Charts-adjacent motion, icons, command palette |
| zod | 3.24.1 | Runtime validation of the server/client environment |
| vitest + Testing Library + jsdom | 2.1.8 / 16.1.0 / 25.0.1 | Unit and component tests (349 cases) |

### Backend
| Technology | Version | Purpose |
|---|---|---|
| Python | 3.12 | Runtime |
| FastAPI | 0.141.1 | Async API framework |
| uvicorn[standard] | 0.52.4 | ASGI server |
| SQLAlchemy 2 | 2.0.52 | Async ORM, typed, with JSONB/array variants |
| asyncpg | 0.31.0 | PostgreSQL async driver |
| Alembic | 1.19.1 | 21 revisions, upgraded *before* serving in every environment |
| pydantic / pydantic-settings | 2.13.4 | Schemas + the whole typed configuration layer |
| python-jose[cryptography] | - | JWKS-token verification (RS256, `azp` fallback) |
| google-genai | 2.20.0 | Gemini 2.5 Flash classification & extraction, JSON-mode with response schema |
| rapidfuzz | 3.14.5 | Deterministic fuzzy batch matching |
| PyMuPDF, python-docx, pandas, openpyxl, python-magic | - | Text-layer-first document reading, DOCX template rendering, report grids, magic-byte admission |
| slowapi | 0.1.10 | Rate limiting (per-route buckets + global default) |
| pywebpush + jinja2 | 2.4.0 / 3.1.6 | VAPID Web Push and multipart email templates |
| httpx, sentry-sdk | - | Outbound clients (Graph, SAP, DMS, JWKS) and error tracking |
| neo4j (driver) | - | Optional traceability projection, imported only when enabled |
| pytest + pytest-asyncio (+ aiosqlite) | 8.x | 721 async tests; SQLite fallback for container-less checkouts |

### Database & Identity
| Technology | Version | Purpose |
|---|---|---|
| PostgreSQL | 15 | System of record (~35 tables, check-constrained string enums, JSONB) |
| Keycloak | 26.0 | OIDC broker for Microsoft Entra ID, realm roles, service-account clients |
| Microsoft Entra ID + Graph API | v1.0 | Machine identity for mailbox read, tracker Excel writes, thread replies - three separate grants, deliberately |

### DevOps
| Technology | Purpose |
|---|---|
| Docker / docker compose | Local stack: postgres, keycloak, mailhog, backend, frontend |
| GitHub Actions (ci / release / rollback) | Blocking CI; tag-triggered Cloud Run deploys with no-traffic → probe → shift; per-service traffic rollback |
| Terraform (google ~> 6.0) | GCP production estate: Cloud Run ×2, Cloud SQL, Memorystore Redis, GCS, Secret Manager, KMS, Cloud Armor WAF, managed SSL, alerting |
| Makefile | Every day-to-day command under one `make` |
| Ruff | Backend lint + format (100-char line length, isort-aware) |
| ESLint (next/core-web-vitals) + `tsc --noEmit` | Frontend lint and type gate, format rules carried by ESLint |

---

## 🗂️ Project Structure

```
AGFZE/
├── docker-compose.yml          # Full local stack: postgres, keycloak, mailhog, backend, frontend
├── Makefile                    # The developer's surface: setup, dev, test, migrate, seed-demo, mail, vapid-keys…
├── .dockerignore / .gitignore
├── .github/
│   └── workflows/
│       ├── ci.yml              # Blocking CI: lint → format → tests → migration dry-run → image build, on PR & main
│       ├── release.yml         # Tag v* → deploy backend + frontend to Cloud Run, migrate first, no-traffic → probe → shift
│       └── rollback.yml        # One-command traffic rollback per service, never touching the schema
│
├── backend/
│   ├── Dockerfile              # Multi-stage, non-root appuser, healthcheck on /health, alembic upgrade then uvicorn
│   ├── pyproject.toml          # pytest + Ruff configuration
│   ├── requirements.in         # Top-level deps, compiled by pip-tools
│   ├── requirements.txt        # Pinned graph (generated)
│   ├── requirements.lock       # Hash-pinned graph (generated, used for reproducible installs)
│   ├── alembic.ini             # URL deliberately empty - env.py resolves it from app.core.config
│   ├── alembic/
│   │   ├── env.py              # Async engine, reads DATABASE_URL from settings
│   │   └── versions/           # 21 revisions: initial schema → intake → transactions → governance →
│   │                           #   sales → FA & shipment → integration → reporting → notifications →
│   │                           #   delivery → invoice-date rule → B2B purchase tag → OBL weight →
│   │                           #   performance & bank letter → hedging → onboarding flag → LME basis →
│   │                           #   report templates → email reply drafts → constraint alignment
│   ├── app/
│   │   ├── main.py             # create_app(): middleware order, lifespan, router mounting, worker startup
│   │   ├── api/
│   │   │   ├── internal/files.py        # Signed, expiring download route (not in the OpenAPI schema)
│   │   │   └── v1/                     # 16 routers - see the API Documentation section
│   │   ├── core/
│   │   │   ├── config.py       # Settings + development/testing/production profiles; production refuses
│   │   │   │                   #   to start without credentials, exact CORS, shared rate-limit store…
│   │   │   ├── security.py     # JWKS client (kid-cached), token decode, azp-audience fallback, subject
│   │   │   ├── errors.py       # AppError hierarchy + uniform {success:false, errors:[…]} envelope
│   │   │   ├── roles.py        # The eight platform roles, canonical ordering, desk-role-by-leg map
│   │   │   ├── rate_limit.py   # slowapi wiring - default ceiling + auth/upload/AI/bulk/webhook buckets
│   │   │   ├── observability.py / logging.py / dependencies.py / disclaimer.py
│   │   ├── db/                 # async engine & session, GUID/JSONB/array type variants, Base
│   │   ├── middleware/         # request logging (X-Request-ID) + security headers (strict CSP, no-store)
│   │   ├── models/             # SQLAlchemy models: identity, intake (requests/documents/fields/reply
│   │   │                       #   drafts), transactions (purchase/sales/FA legs, rule evaluations),
│   │   │                       #   governance (approvals, exceptions, mappings), logistics (shipments,
│   │   │                       #   containers, bills of lading, issues), integration (jobs, packs),
│   │   │                       #   configuration (document schemas, rule configs), reporting,
│   │   │                       #   notifications, push subscriptions, audit, jobs, enums
│   │   ├── schemas/            # Pydantic request/response models per module + the common envelope
│   │   └── services/
│   │       ├── gemini_service.py        # The ONLY module that talks to a model: schema-validated,
│   │       │                            #   delimited data block, prompt-injection guard, honest failures
│   │       ├── classification_service.py / extraction_service.py / text_extraction.py
│   │       ├── matching_service.py      # rapidfuzz batch matching, quantity spread, suggestion floors
│   │       ├── email_ingestion.py / email_reply_service.py / mailbox_worker.py / graph_service.py
│   │       ├── rules/                   # catalog (BR-01..13, IV-01, SL-01, LG-01), registry, engine,
│   │       │                            #   evaluators, invoice/sales/logistics evaluators, values, defaults
│   │       ├── governance/              # approval_service (maker-checker), exception_service,
│   │       │                            #   categories, thresholds (GOV-01..03), hooks
│   │       ├── analytics/               # kpis (honest definitions), scope (role-scoped WHERE clauses),
│   │       │                            #   report_service/render/templates, schedule, retention, cache
│   │       ├── integration/             # adapters (3-outcome protocol), sap, dms, tracker (row-level
│   │       │                            #   Graph Excel), document_packs (merged PDF + contents page), payloads
│   │       ├── logistics/               # shipment_service, tracking_service (adapter registry + sweep), adapters
│   │       ├── delivery/                # email_service (threaded SMTP, Jinja2), push_service (VAPID),
│   │       │   └── templates/           # base + approval/exception/report/integration HTML & plaintext
│   │       ├── templates/               # sales_templates + renderer + assets/*.docx (shipped templates)
│   │       ├── storage/                 # base / local (HMAC signed URLs) / cloud (GCS) behind one protocol
│   │       ├── transaction_service.py / sales_service.py / draft_service.py / request_service.py
│   │       ├── notification_service.py  # the one function that may create a Notification
│   │       ├── audit_service.py         # append-only audit writes, metadata-only payloads
│   │       ├── keycloak_admin.py        # the one admin-REST capability: role override on /admin/users
│   │       ├── integration_worker.py / shipment_worker.py / graph_sync_worker.py / job_service.py
│   │       ├── counterparty_codes.py    # derived three-letter codes - never stored, so never stale
│   │       └── schema_defaults.py / file_intake.py / document_service.py / transaction_fields.py
│   ├── scripts/
│   │   ├── seed_sales_demo.py   # local demo data: matched B/L pack, stale shipment, approval + 3 jobs
│   │   ├── generate_vapid_keys.py
│   │   └── rebuild_graph.py     # rebuild the Neo4j projection from PostgreSQL
│   └── tests/                   # 46 files, 721 async tests (SQLite fallback, PG on CI) - see Testing
│
├── frontend/
│   ├── Dockerfile              # node:22-alpine, standalone output, build args for NEXT_PUBLIC_*
│   ├── package.json / package-lock.json
│   ├── next.config.mjs         # output: "standalone", strict React, no powered-by header
│   ├── tailwind.config.ts / postcss.config.mjs / components.json
│   ├── vitest.config.ts / vitest.setup.ts / .eslintrc.json
│   ├── public/
│   │   ├── manifest.webmanifest  # PWA manifest with app shortcuts (Approvals, Exceptions)
│   │   └── icons/                # generated icon set (npm run icons)
│   ├── scripts/
│   │   ├── build-sw.mjs          # postbuild: inject the precache manifest into public/sw.js
│   │   ├── verify-sw-manifest.mjs# fail the build if the worker's manifest mismatches the build
│   │   └── generate-icons.mjs
│   └── src/
│       ├── middleware.ts       # nonce CSP + hardening headers on EVERY response, session gate for /protected
│       ├── app/
│       │   ├── layout.tsx      # force-dynamic (nonce policy), Inter, PWA registration
│       │   ├── (auth)/         # signin, signout (with flow), auth-error, unprovisioned
│       │   ├── (public)/       # disclaimer, privacy, terms
│       │   ├── (protected)/    # dashboard, inbox (+upload), transactions (new/fa/purchase/sales),
│       │   │                   #   documents, exceptions, approvals, shipments, analytics, reports
│       │   │                   #   (+builder), notifications, settings, admin (users, rules,
│       │   │                   #   document-types, integrations, audit, report-distribution,
│       │   │                   #   report-templates)
│       │   ├── api/auth/[...nextauth]/  # NextAuth route handler
│       │   └── offline/page.tsx         # the page the service worker serves when all else fails
│       ├── components/         # layout (app-shell, sidebar, command-palette, notification-bell…),
│       │   │                   #   intake, transactions, shipments, exceptions, approvals, analytics,
│       │   │                   #   reports, admin, charts (SVG line/bar/donut), pwa, ui (shadcn primitives)
│       ├── hooks/              # use-media-query, use-offline-state, use-session-refresh, use-element-width
│       ├── lib/                # api-client (typed envelope + ApiError), auth, env (zod-validated),
│       │   │                   #   csp, roles, navigation, pwa, offline-state, push, + per-module helpers
│       ├── service-worker/     # strategy.js (pure, tested) + runtime.js, inlined by build-sw.mjs
│       ├── types/next-auth.d.ts
│       └── __tests__/          # 34 files, 349 vitest cases - see Testing
│
└── infra/
    ├── keycloak/
    │   ├── realm-agfze.json    # realm, roles, two clients, 8 seeded dev logins, Entra ID broker scaffold
    │   └── README.md           # exactly what AGFZE IT must fill in to activate the broker
    ├── postgres/init-test-db.sh# idempotent creation of agfze_test inside the local postgres
    └── production/
        ├── main.tf             # VPC, Cloud SQL (CMEK, PITR), Memorystore, GCS, Secret Manager, WAF…
        ├── services.tf         # Cloud Run ×2 + migrate job, LB + Cloud Armor, alerting on sweeps
        ├── variables.tf / outputs.tf
        ├── verify-production.sh# reads the live estate back and fails on any broken promise
        └── restore-test.sh     # restores prod backup into a throwaway instance and proves the data
```

---

## 🚀 Getting Started

### Prerequisites

| Tool | Version | Install |
|---|---|---|
| Docker + Docker Compose | Docker 24+, Compose v2 | [docker.com](https://docs.docker.com/get-docker/) |
| Make | any recent | [gnu.org/software/make](https://www.gnu.org/software/make/) |
| Node.js | **22** | [nodejs.org](https://nodejs.org/) - needed for `test-frontend` and `verify-sw` |
| Git | any recent | [git-scm.com](https://git-scm.com/) |
| Python 3.12 | only for bare-metal backend runs | [python.org](https://www.python.org/downloads/) |

That is genuinely all. PostgreSQL, Keycloak and MailHog run in containers; the only things needed from the outside world are a Gemini API key (for AI classification/extraction) and optionally an Azure AD app registration (for real mailbox intake). Everything else runs blank and works.

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/ram-supervity/AGFZE.git
cd AGFZE

# 2. First run: env files, images, infrastructure, schema, seeded logins
make setup
```

`make setup` copies `backend/.env.example` → `backend/.env` and `frontend/.env.example` → `frontend/.env`, builds both images, starts PostgreSQL and Keycloak, waits for PostgreSQL to be healthy, and applies every Alembic migration.

You should end the run staring at the seeded Keycloak logins. All of them share the development password `Passw0rd!`:

| Username | Email | Roles |
|---|---|---|
| `hod.approver` | hod.approver@agfze.local | approver_hod |
| `purchase.user` | purchase.user@agfze.local | purchase_user |
| `sales.user` | sales.user@agfze.local | sales_user |
| `fa.user` | fa.user@agfze.local | fa_user |
| `logistics.user` | logistics.user@agfze.local | logistics_user |
| `finance.user` | finance.user@agfze.local | finance_user |
| `admin.user` | admin.user@agfze.local | admin |
| `auditor.user` | auditor.user@agfze.local | auditor |
| `dual.user` | dual.user@agfze.local | purchase_user, approver_hod |

### Environment Variables

**Backend** (`backend/.env`, copied from `.env.example` - every variable maps to a field on `app.core.config.Settings`; anything left out falls back to the default declared there). The most important ones:

| Variable | Description | Example |
|---|---|---|
| `ENV` | Selects the settings subclass: `development` \| `testing` \| `production` | `development` |
| `DATABASE_URL` | Async SQLAlchemy DSN (host is `postgres` inside compose) | `postgresql+asyncpg://agfze:agfze@localhost:5432/agfze` |
| `TEST_DATABASE_URL` | Used by the suite only; unset, tests fall back to a disposable SQLite file | `postgresql+asyncpg://agfze:agfze@localhost:5432/agfze_test` |
| `KEYCLOAK_ISSUER` | Issuer exactly as in the `iss` claim (browser-facing host) | `http://localhost:8080/realms/agfze` |
| `KEYCLOAK_JWKS_URL` | Signing-key endpoint (compose-internal host when containerised) | `http://keycloak:8080/realms/agfze/protocol/openid-connect/certs` |
| `KEYCLOAK_AUDIENCE` | Expected token audience | `agfze-command-centre` |
| `KEYCLOAK_SERVER_URL` / `KEYCLOAK_REALM` / `KEYCLOAK_ADMIN_CLIENT_ID` / `KEYCLOAK_ADMIN_CLIENT_SECRET` | The **third** machine credential - a service account holding one grant (`manage-users`), used only by the role override on `/admin/users` | `http://keycloak:8080` / `agfze` / `agfze-admin-api` / `agfze-local-admin-api-secret` |
| `GEMINI_API_KEY` | Google AI Studio key for classification/extraction | `replace-with-your-gemini-api-key` |
| `AI_PROVIDER` / `GEMINI_MODEL` | Provider (`gemini_flash` implemented, `vertex_ai` a declared extension point) and model | `gemini_flash` / `gemini-2.5-flash` |
| `CONFIDENCE_THRESHOLD_DEFAULT` | At/above → classification stands; below → flagged for review | `0.75` |
| `AZURE_AD_TENANT_ID` / `AZURE_AD_CLIENT_ID` / `AZURE_AD_CLIENT_SECRET` | The Graph machine identity (mailbox read, tracker writes, replies) - separate from the sign-in broker | `00000000-0000-0000-0000-000000000000` |
| `GRAPH_MAILBOX_ADDRESS` | The approved shared mailbox that is polled/subscribed | `trade.docs@example.com` |
| `GRAPH_WEBHOOK_ENABLED` / `GRAPH_WEBHOOK_NOTIFICATION_URL` / `GRAPH_WEBHOOK_CLIENT_STATE` | Change notifications need a public URL; state must be `openssl rand -hex 32` | `false` / `https://your-public-host/api/v1/graph/notifications` |
| `GRAPH_REPLY_ENABLED` | Whether a composed reply may actually leave the mailbox (requires Mail.Send grant); off = compose-only, and the screen says so | `false` |
| `STORAGE_BACKEND` / `STORAGE_LOCAL_ROOT` / `STORAGE_BUCKET` | `local` (signed URLs via the app) or `gcs` (bucket pre-signed URLs, bytes never pass through the API) | `local` / `./var/storage` |
| `STORAGE_SIGNED_URL_SECRET` | HMAC key for signed download URLs - replace before any shared deployment | `replace-with-a-random-32-byte-secret` |
| `RATE_LIMIT_ENABLED` | Off locally, **forced on** in production (which refuses to start if any limit is blank) | `false` |
| `RATE_LIMIT_STORAGE_URI` | `memory://` locally; production provisions Memorystore and points this at it | `memory://` |
| `RATE_LIMIT_DEFAULT` / `_AUTH` / `_UPLOAD` / `_AI` / `_BULK_APPROVAL` / `_WEBHOOK` | Per-category budgets | `120/minute`, `30/minute`, `20/minute`, `15/minute`, `5/minute`, `120/minute` |
| `CORS_ALLOWED_ORIGINS` | Exact origins only - `*` is rejected in production | `http://localhost:3000` |
| `SENTRY_DSN` | Empty = Sentry fully disabled | |
| `SAP_API_BASE_URL` / `SAP_POSTING_PATH` / `SAP_API_USERNAME` / `SAP_API_PASSWORD` / `SAP_API_KEY` / `SAP_COMPANY_CODE` / `SAP_BUSINESS_AREA` | Blank base URL = the normal state → honest `awaiting_manual_action` | `1070` (the discovery-named business area) |
| `DMS_API_BASE_URL` / `DMS_UPLOAD_PATH` / `DMS_API_KEY` / `DMS_REPOSITORY` | Same pattern: unconfigured → compiled pack + manual filing instructions | |
| `TRACKER_DRIVE_ID` / `TRACKER_WORKBOOK_ITEM_ID` / `TRACKER_WORKSHEET_NAME` / `TRACKER_TABLE_NAME` / `TRACKER_KEY_COLUMN` / `TRACKER_COLUMN_MAP` | The Excel tracker target; placeholders pending AGFZE naming the real workbook | `Tracker` / `Batch Number` / `{"batch_number":"Batch Number"}` |
| `INTEGRATION_SWEEP_ENABLED` / `_INTERVAL_SECONDS` / `_BATCH_SIZE` / `INTEGRATION_MAX_ATTEMPTS` / `INTEGRATION_RETRY_BASE_SECONDS` / `INTEGRATION_RETRY_MAX_SECONDS` | The retry sweep (60s cadence, 5 attempts, exponential backoff to 1h) | `true` / `60` / `50` / `5` / `60` / `3600` |
| `REPORT_SCHEDULE_ENABLED` / `REPORT_DAILY_HOUR_UTC` / `REPORT_MONTHLY_DAY` / `REPORT_MAX_DETAIL_ROWS` / `REPORT_AI_SUMMARY_ENABLED` | The scheduled daily (06:00 UTC, previous day) and monthly reports | `true` / `6` / `1` / `500` / `true` |
| `DASHBOARD_CACHE_TTL_SECONDS` / `_MAX_ENTRIES` | 45s on purpose; the API reports the age of what it served | `45` / `512` |
| `APP_BASE_URL` | Public origin - every email CTA is built from this, never from a request header; localhost refused in production | `http://localhost:3000` |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_STARTTLS` / `SMTP_FROM_ADDRESS` | The relay. Locally: MailHog (plain SMTP, STARTTLS off - and only off there) | `mailhog` / `1025` / `false` |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT` / `PUSH_TTL_SECONDS` | Web Push pair - generate **once** per environment (`make vapid-keys`); the public half must equal `NEXT_PUBLIC_VAPID_PUBLIC_KEY` | `mailto:command-centre@agfze.local` / `86400` |
| `NOTIFICATION_DELIVERY_ENABLED` | Master switch for email + push; in-app always works | `true` |
| `DOCUMENT_RETENTION_ENABLED` / `DOCUMENT_RETENTION_DAYS` / `DOCUMENT_RETENTION_DRY_RUN` | Retention mechanism, off and dry-run: 0 days means *unset*, not immediate, and the sweep refuses to run on it | `false` / `0` / `true` |
| `GRAPH_SYNC_ENABLED` / `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` / `GRAPH_SYNC_INTERVAL_SECONDS` | The optional Neo4j traceability projection | `false` / `300` |

**Frontend** (`frontend/.env`, copied from `.env.example` - validated at boot by zod in `src/lib/env.ts`, which refuses to start on a bad config):

| Variable | Description | Example |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | Inlined into the browser bundle - must be an address the user's machine can reach, and the origin the service worker may cache | `http://localhost:8000/api/v1` |
| `API_INTERNAL_BASE_URL` | Server-side API base (compose network); falls back to the public value | `http://backend:8000/api/v1` |
| `KEYCLOAK_CLIENT_ID` | Must match the client in `infra/keycloak/realm-agfze.json` | `agfze-command-centre` |
| `KEYCLOAK_CLIENT_SECRET` | Local realm ships a throwaway dev value; deployed environments inject theirs from a secret store | `replace-with-keycloak-client-secret` |
| `KEYCLOAK_ISSUER` | Browser-facing realm URL - must equal the `iss` Keycloak signs with, or sign-in is blocked (by the CSP, no less) | `http://localhost:8080/realms/agfze` |
| `KEYCLOAK_INTERNAL_ISSUER` | Server-side realm URL (token exchange, JWKS); defaults to `KEYCLOAK_ISSUER` | `http://keycloak:8080/realms/agfze` |
| `NEXTAUTH_URL` | Public origin; must match the redirect URIs on the client | `http://localhost:3000` |
| `NEXTAUTH_SECRET` | Session-cookie signing key - `openssl rand -base64 32`, never committed | |
| `NEXT_PUBLIC_VAPID_PUBLIC_KEY` | Public half of the VAPID pair; empty = the UI says honestly there is no push | |

### Running the Project

```bash
# Development - full stack in the foreground (frontend :3000, API :8000, docs /docs, Keycloak :8080)
make dev

# Or bring the whole stack up detached and follow the logs
docker compose up -d
make logs

# What was "sent" lands in MailHog - nothing leaves your machine
make mail          # then open http://localhost:8025

# Apply migrations (already done at container start, but explicit when you need it)
make migrate

# Load realistic local sample data (never runs in production) - a matched invoice/B/L pack,
# a deliberately stale shipment, and an approval-pending batch whose three integration
# jobs all wait honestly on a person
make seed-demo

# Generate the VAPID key pair once per environment and paste both lines into backend/.env
# (+ the public one into frontend/.env as NEXT_PUBLIC_VAPID_PUBLIC_KEY)
make vapid-keys

# Regenerate the PWA icon set / rebuild the Neo4j projection / rebuild the DOCX templates
make icons
make rebuild-graph
make templates

# Migrations: autogenerate one
make migration m="add shipments table"
```

When the stack is up:

| URL | What it is |
|---|---|
| http://localhost:3000 | The application (sign in with a seeded login) |
| http://localhost:8000/docs | Swagger UI (development only - the API hides its docs in production) |
| http://localhost:8000/health/ready | Readiness probe |
| http://localhost:8080 | Keycloak admin (`admin` / `admin`) |
| http://localhost:8025 | MailHog - read every notification email the platform "sent" |

---

## 🧭 Usage

Sign in as `purchase.user`, and follow a document through the whole pipeline:

1. **The email arrives.** With real Graph credentials, the mailbox worker picks it up (or the webhook does, and the delta poll covers the gap). Without them, use **Inbox → Upload** to drop a PDF in - the intake pipeline is identical from there on.
2. **Classification and extraction** - Gemini assigns a category (`purchase`, `sales`, `fa`, `logistics`, `approval`, `follow_up`, `informational`, `exception`), the business stream, and then extracts fields against the document type's configured schema. Every value carries a confidence score; below `CONFIDENCE_THRESHOLD_DEFAULT` the request needs a human.
3. **Confirm the extraction** - correct any field, then confirm. The moment the extraction is confirmed, the matcher runs: it finds the batch this document belongs to (batch number, fuzzy reference match, quantity proximity) or offers to open a new batch.
4. **Validation** - the rule engine evaluates every evaluator the transaction's legs make relevant. Failures of `BR-*` rules open owned exception cases; `acknowledgeable` severities can be acknowledged by the preparing user within limits.
5. **Submission & approval** - a fully validated transaction is submitted; the ranked approval queue (`rank_by=age|value|risk`) puts it in front of the HOD, who sees a one-time AI summary of the numbers. Decide, or bulk-approve the lowest-risk set within the configured ceiling. The same account that submitted cannot approve - the maker-checker control is enforced in the service, not the UI.
6. **Posting** - three integration jobs are created: SAP contract + price record, DMS document pack, tracker row. Configured endpoints get real HTTP postings (with `external_reference` recorded); unconfigured, each job rests at `awaiting_manual_action` carrying the complete payload and instructions for the person who finishes it. A job only reports success if an adapter genuinely succeeded - the outcome type makes anything else unrepresentable.
7. **Watch it leave** - the transaction moves to `integration_pending` then `committed`, the shipment board shows the container and milestones (pulled by a carrier adapter where one exists, kept honest by hand where one does not - the staleness sweep opens an exception when nobody has looked for 48 hours), and the daily/monthly reports now include this deal with the query behind every figure.

A few command-line examples of the API in action:

```bash
# Health
curl -s http://localhost:8000/health/ready
# {"success":true,"data":{"status":"ready","database":"ok"},"message":null,"errors":null}

# Sign in through Keycloak to get a token, then:
TOKEN=$(curl -s -X POST http://localhost:8080/realms/agfze/protocol/openid-connect/token \
  -d grant_type=password -d client_id=agfze-command-centre \
  -d client_secret=agfze-local-dev-secret \
  -d username=purchase.user -d password=Passw0rd! | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')

# Your profile
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/users/me

# The role-scoped dashboard summary
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/dashboards/summary

# Upload a document (multipart)
curl -s -H "Authorization: Bearer $TOKEN" -F "file=@invoice.pdf" \
  http://localhost:8000/api/v1/documents/upload

# Generate a report now, as a tracked background job
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"scope":{"stream":"scrap"},"range":"month","month":"2026-07"}' \
  http://localhost:8000/api/v1/reports
```

Every response arrives in one envelope - `{success, data, message, errors}` - and carries an `X-Request-ID` you can quote back when something looks wrong.

---

## 📡 API Documentation

Base URL: `/api/v1` (configurable via `API_V1_PREFIX`). **Authentication:** every route except `/health`, `/health/ready` and `/graph/notifications` requires `Authorization: Bearer <access_token>` - a Keycloak RS256 token verified against the JWKS endpoint (`aud` + `azp` fallback, 30s leeway). The Graph webhook is `X-Client-State`-checkable rather than token-checked, and rate-limited separately.

Swagger UI is served at `/docs` in development and testing, and not at all in production.

| Health | | |
|---|---|---|
| GET | `/health`, `/health/` | Liveness - process only, never touches the database |
| GET | `/health/ready` | Readiness - 503 until the database answers; body stays generic |
| GET | `/internal/files/{key:path}` | Signed, expiring download of a stored object (not in the schema) |

| Users | | |
|---|---|---|
| GET | `/users/me` | Profile of the authenticated user |
| PATCH | `/users/me/preferences` | Update the caller's own preferences (stream filter, channel) |
| POST | `/users/me/onboarding-complete` | Mark the first-login walkthrough as seen |

| Dashboard & Analytics | | |
|---|---|---|
| GET | `/dashboards/summary` | Role-scoped aggregate counts - scoped in the query, never painted out afterwards |
| GET | `/dashboards/kpis` | Trend KPIs over a date range (accuracy is a *non-override* rate - the API says so) |

| Intake (`/requests`, `/documents`) | | |
|---|---|---|
| GET | `/requests` | Paginated, filterable request queue |
| GET | `/requests/{request_id}` | Full detail with attachments |
| PATCH | `/requests/{request_id}/category` | Correct the AI-assigned category |
| GET | `/requests/{request_id}/replies` | Every composed reply on the thread, sent or not |
| POST | `/requests/{request_id}/replies` | Compose a reply - stored for review, sent to nobody |
| POST | `/requests/{request_id}/replies/{draft_id}/send` | Send it, recorded against your account |
| POST | `/requests/{request_id}/replies/{draft_id}/withdraw` | Abandon an unsent draft |
| POST | `/documents/upload` | Manual intake (magic-byte whitelist, streamed size limit) |
| GET | `/documents` | Searchable document index |
| GET | `/documents/{document_id}` | Full extraction detail + signed page images |
| PATCH | `/documents/{document_id}/fields` | Correct extracted values (each correction is an override with a reason) |
| POST | `/documents/{document_id}/reclassify` | Reclassify and re-extract against the new type's schema |
| POST | `/documents/{document_id}/confirm` | Confirm the extraction - the moment matching runs |
| GET/POST | `/documents/{document_id}/match` | Preview / resolve a suggested batch match |

| Transactions | | |
|---|---|---|
| GET | `/transactions/commodity-codes` | The trade grades a transaction may carry |
| GET | `/transactions/fa/schema` | The configured FA fields with no named column |
| GET | `/transactions` | Paginated, filterable transaction list |
| GET | `/transactions/{transaction_id}` | Legs, rules, documents, history in one read |
| POST | `/transactions` | Register a purchase transaction by hand |
| POST | `/transactions/fa` | Register an FA transaction by hand |
| POST | `/transactions/{transaction_id}/sales-leg` | Attach a sales leg |
| POST | `/transactions/{transaction_id}/generate-draft` | Generate a reviewable sales contract / invoice (DOCX from shipped templates; model picks clauses, validation decides) |
| PATCH | `/transactions/{transaction_id}/fields` | Correct fields and re-run validation |
| POST | `/transactions/{transaction_id}/acknowledge-tolerance` | Acknowledge a self-approvable tolerance breach |
| POST | `/transactions/{transaction_id}/submit` | Submit a fully validated transaction for approval |
| GET | `/transactions/{transaction_id}/graph` | Traceability neighbourhood, bounded depth |

| Shipments | | |
|---|---|---|
| GET | `/shipments` | Paginated shipment board |
| POST | `/shipments` | Open a shipment by hand |
| GET | `/shipments/{shipment_id}` | Milestone timeline, issues, linked transaction |
| POST | `/shipments/{shipment_id}/refresh` | Pull status through whatever carrier adapter handles it |
| PATCH | `/shipments/{shipment_id}` | Record/correct status by hand - through the same single update function, so plausibility checks and audit can't be bypassed |
| POST | `/shipments/{shipment_id}/issues` | Log a post-delivery issue |

| Governance | | |
|---|---|---|
| GET | `/exceptions` | Paginated exception queue, every category tab |
| GET | `/exceptions/{case_id}` | The rule, the field, the values, where it stands now |
| POST | `/exceptions/{case_id}/resolve` | Resolve with a genuine fix, and/or escalate to the HOD |
| GET | `/approvals` | The ranked queue (`rank_by: age \| value \| risk`) |
| GET | `/approvals/{approval_id}` | Full detail, AI summary generated once and cached |
| POST | `/approvals/{approval_id}/decide` | The approver's decision; self-approval refused |
| POST | `/approvals/bulk-decide` | Approve the lowest-risk set, each one individually, under the ceiling |

| Integrations, Jobs, Reports, Notifications, Audit | | |
|---|---|---|
| GET | `/integrations/jobs` · GET `/integrations/jobs/{job_id}` | Every integration job / one job with manual-completion details |
| POST | `/integrations/jobs/{job_id}/retry` | Re-queue a failed job now, outside its backoff schedule |
| POST | `/integrations/jobs/{job_id}/complete-manual` | Confirm a manually finished posting |
| GET | `/jobs/{job_id}/status` | Poll a background job (report generation) |
| GET | `/reports` · GET `/reports/{report_id}` | Generated reports; one report with drill-through filters on every figure |
| POST | `/reports` | Generate now, as a tracked job |
| GET | `/notifications` · POST `/notifications/mark-all-read` | The caller's own notifications |
| GET | `/notifications/vapid-public-key` | The application server key a browser subscribes with |
| POST/DELETE | `/notifications/push-subscribe` | Register/refresh/forget a browser subscription |
| GET | `/audit` · GET `/audit/export` | Filterable audit trail; CSV export streamed, not buffered |
| POST | `/graph/notifications` | Microsoft Graph change-notification receiver (secret-checked) |

| Admin (`admin`, `auditor` on read sides; changes require a recorded reason) | | |
|---|---|---|
| GET/PATCH | `/admin/rules[/{configuration_id}]` | Every threshold - change one and the reason is mandatory |
| GET/PATCH | `/admin/document-types[/{schema_id}]` | Field lists + mandatory-document checklists per type |
| GET/PATCH | `/admin/users` | Mirror of identity-provider accounts; role override written to Keycloak first, mirrored locally only on confirmation |
| GET/POST/PATCH | `/admin/report-distribution[/{rule_id}]` | Who receives which scheduled report, on which channel |
| GET/PATCH | `/admin/report-templates/{template_id}` | What a report carries: sections, order, figures |

---

## ⚙️ Configuration

Configuration lives in three places, by design.

**1. Environment (`backend/.env`, `frontend/.env`)** - typed, environment-switched settings. `ENV=development|testing|production` selects the subclass, and the **production** subclass refuses to start unless it can prove it is safe: identity credentials, Graph credentials, Gemini key, SMTP relay, VAPID pair, storage bucket, exact-origin CORS, non-localhost `APP_BASE_URL`, non-default signed-URL secret, rate limits populated, and a shared (non-`memory://`) counter store - unless a deployment explicitly accepts per-instance counting. `backend/.env.example` documents every variable, including the three machine identities and why keeping them separate matters.

**2. Governed tables** - thresholds the business owns are data, not code:
- `rule_configurations` holds the `BR-01…BR-13` per-rule, per-commodity thresholds (quantity tolerance, rate tolerance, match floors, self-approval limits, duplicate similarity…) **and** the `GOV-01…GOV-03` governance values (bulk-approval ceiling, approval-overdue hours, exception ageing, shipment staleness). The admin screens edit these with a mandatory recorded change reason, and every change is audited.
- `document_type_schemas` defines each document type's field list, types and tolerances - extract new fields without a code change or a deploy.
- `report_template_configurations` describes each report's sections and figures; renderers never learn a section's name.
- `report_distribution_rules` decides who gets a scheduled report and on which channel.

**3. Code-level seams** - adapters registered against a protocol: SAP/DMS/tracker postings through `integration/adapters.py` (three outcomes, nothing else expressible), carrier tracking through a registry that is legitimately empty today, storage through `base.py` (local or GCS behind one protocol), and the AI through the one `gemini_service.py` choke point.

**Important defaults to know:** retention ships *off, with no period, in dry run*; the graph projection ships *off*; webhooks ship *off* (they need a public URL); the tracker workbook is *unnamed* (placeholders - AGFZE must confirm which workbook is live); SAP and DMS endpoints are *unconfigured on purpose* until their contracts are confirmed; and every one of those states degrades to an honest, human-supervised path rather than a fake success.

---

## 🧪 Testing

Two suites, both runnable together:

```bash
make test            # both suites
make test-backend    # pytest against the agfze_test database (PostgreSQL)
make test-frontend   # vitest (needs Node 22 + frontend/node_modules)
```

**Backend - 721 test functions in 46 files**, async-first (`pytest-asyncio`, `asyncio_mode=auto`), wired through `conftest.py`. PostgreSQL is the real test target on CI (an async migration that only behaves on SQLite must not pass there); a container-less checkout falls back to a disposable SQLite file under `./var`. Coverage spans the intake pipeline, AI classification/extraction routing, matching, the rule engine (including the LME, invoice-date, OBL-weight and three-month-LME rules), FA and sales modules, approvals, exceptions, shipments, integrations and their payload mapping, reports and report distribution, retention, audit explorer, storage, delivery channels (SMTP + push), email ingestion/reply, RBAC matrix, security posture, architecture promises, and a full end-to-end journey.

**Frontend - 349 cases in 34 files** (vitest + Testing Library + jsdom): navigation gating, roles, the command palette, dashboard view, intake and category tabs, transaction and FA/sales panels, trace panel, approvals/reply panel, charts, admin tables, report viewer and templates, CSP builder, offline governance, PWA behaviour, service-worker strategy and runtime, and the manifest.

```bash
make lint            # Ruff (backend) + ESLint & tsc (frontend)
make format-check    # exactly what CI asserts: ruff format --check + eslint --max-warnings=0
make verify-sw       # the built service worker's precache manifest must match the build
```

CI additionally proves the migrations build the schema from nothing - `upgrade head`, `downgrade base`, `upgrade head`, `alembic check` against a disposable database - and that the production image refuses an unsafe configuration at start-up.

---

## ☁️ Deployment

The production shape is **two containers, one managed database, one secrets store, one WAF**, defined in `infra/production/` and proven by its own verification scripts. Target: Google Cloud (`me-central1` - Dubai), though nothing in the application is tied to it.

**What Terraform provisions** (`infra/production/*.tf`):

- a VPC with private-only connectivity; Cloud SQL PostgreSQL (regional HA, CMEK-encrypted, automated backups + point-in-time recovery, no public IP);
- Cloud Run for `agfze-backend` and `agfze-frontend` - separate identities, separate revisions, separate rollbacks, `INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER` only, `min_instance_count = 1` so the sweeps genuinely run, `cpu_idle = false` so they can;
- a migrate Cloud Run job (the release pipeline runs it to completion *before* the new revision serves - no startup races);
- a GCS bucket for documents (public-access prevention, served only through signed URLs), Memorystore Redis for the shared rate-limit counters, Secret Manager + KMS for every credential, Cloud Armor WAF + managed SSL on the load balancer;
- monitoring alert policies: backend unavailable, and **sweep stopped** (a deployment where the periodic sweeps quietly died cannot be mistaken for a healthy one);
- an optional Neo4j VM (`enable_graph_projection`, default **false**).

**The release pipeline** (`release.yml`, tag `v*`): re-runs the full CI suite against the tagged tree, then per service - record the serving revision, build and push to Artifact Registry, run migrations, deploy with **no traffic**, probe the tagged URL until healthy, shift traffic, and print the exact rollback command on the run summary. Backend and frontend deploy in parallel and roll back independently.

**The rollback pipeline** (`rollback.yml`): dispatch with a service and (optionally) a specific revision; traffic shifts to the previous revision - nothing rebuilt, nothing redeployed, and the database schema deliberately not reverted. A schema change that cannot be rolled forward past is a decision for a person, and the workflow says so.

**Verify it, don't assume it:**

```bash
# Apply the estate
cd infra/production
terraform init && terraform plan -var project_id=<gcp-project-id> && terraform apply

# Read the live estate back and fail on anything not actually configured:
# TLS floor, HTTPS-only, WAF in front, DB private + SSL + PITR, readiness probe,
# sweeps running, documents never public…
make verify-production project=<gcp-project-id>

# Prove the backup is a capability, not a setting: restore prod into a throwaway
# instance and assert the data (transactions, audit trail, approvals) came back.
./infra/production/restore-test.sh <gcp-project-id>
```

---

## 🤝 Contributing

This is a governed platform - the code says so on almost every module. Keep that spirit and you'll fit right in.

1. **Fork** the repository and clone your fork.
2. **Branch**: `git checkout -b feature/what-youre-building`.
3. **Code**:
   - Backend: Ruff (`make format`, `make lint-backend`), 100-char lines, `ruff`-select rules (`ASYNC, B, C4, E, F, I, SIM, UP, W, RUF`); isort treats `app` and `tests` as first-party.
   - Frontend: ESLint with `next/core-web-vitals`, `eqeqeq` smart, no `console.log` (warn/error allowed), and `npm run typecheck` clean.
   - New schema change → **new Alembic migration** (`make migration m="..."`), never an edit to an old one.
   - New rule → register an evaluator under its `RuleId` (`implemented=False` is an honest state - used by BR-01 and BR-08…BR-12 today); new threshold → a documented `*_configuration` row, not a constant.
   - New externally-visible behaviour → audit event via `record_audit_event`, notification via `notify()`, and nothing that can report a success it did not achieve.
4. **Test**: `make test` - then run the new test(s) against PostgreSQL, not just the SQLite fallback. CI will do the same.
5. **Commit** with a message that says what and why: `feat(approvals): bulk queue now ranks by risk, not age - GOV-01/02 thresholds`.
6. **Push and open a pull request** to `main`. Every PR runs the full blocking CI; nothing is advisory, nothing is `continue-on-error`.

**Reporting a bug** - open an issue with: what you did, what you expected, what happened, the request's `X-Request-ID`, the environment (`ENV`, deployment), and whether the audit trail shows the action. **Requesting a feature** - describe the desk process behind it first; this platform's habit is to implement the honest state even when the automation is not yet specified.

---

## 🙏 Acknowledgements

Built on the shoulders of a genuinely excellent ecosystem:

- **[FastAPI](https://fastapi.github.io/)** & **[SQLAlchemy 2](https://www.sqlalchemy.org/)** - the async stack this whole API is built on
- **[Next.js](https://nextjs.org/)**, **[React 19](https://react.dev/)**, **[Tailwind CSS](https://tailwindcss.com/)** and **[shadcn/ui](https://ui.shadcn.com/)** with **[Radix UI](https://www.radix-ui.com/)** - the frontend
- **[Keycloak](https://www.keycloak.org/)** - the OIDC broker that ties Entra ID to this platform's eight roles
- **[Google Gemini](https://ai.google.dev/)** - classification and extraction, wrapped behind one schema-validating module
- **[Microsoft Graph](https://learn.microsoft.com/graph/)** - the mailbox, the tracker workbooks, and the reply threads
- **[RapidFuzz](https://rapidfuzz.com/)** - matching that is reproducible, and deliberately not an AI call
- **[PyMuPDF](https://pymupdf.readthedocs.io/)**, **[python-docx](https://python-docx.readthedocs.io/)**, **[pandas](https://pandas.pydata.org/)** - deterministic document and report bytes
- **[MailHog](https://github.com/mailhog/MailHog)** - so no developer's machine ever talks to a real relay
- **[Terraform](https://www.terraform.io/)** & **[GitHub Actions](https://github.com/features/actions)** - an estate you can read back, and a pipeline that proves what it promises
- The **discovery and governing material** of AGFZE's trade operations - every business rule, every honest "not yet specified", and every deliberate refusal to invent a number traces back to it

---

## 📬 Contact / Author

Maintained by **[ram-supervity](https://github.com/ram-supervity)** - project home: [github.com/ram-supervity/AGFZE](https://github.com/ram-supervity/AGFZE).

Found a bug, or want to talk through where the platform goes next? Open an issue or a pull request - the issue template is in the contributing section above, and every `X-Request-ID` is welcome.

Thanks for reading this far. This project was built one honest decision at a time - read the module docstrings, they're the best part. *Happy trading.* 🪙