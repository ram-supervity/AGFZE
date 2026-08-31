# AGFZE Command Centre — Complete Testing Playbook

**Project:** AGFZE Command Centre — operations platform for AGFZE's non-ferrous metal scrap trade
**Repository:** https://github.com/ram-supervity/AGFZE
**What this document is:** a real-world, step-by-step instruction manual for standing the platform up on your own machine/laptop and proving that it actually works — both the automated test suites (721 backend + 349 frontend tests) and a manual end-to-end user-acceptance walkthrough of the whole governed pipeline (intake → AI classification/extraction → matching → 13 business rules → maker-checker approval → SAP/DMS/tracker jobs → shipments → reports → notifications → audit).
**Audience:** a tester / engineer who has never run this project before. Every command, every URL, every field value, every expected result is written out. Nothing is skipped.

> **Read me first — three honest facts about this platform that shape how you test it:**
> 1. **AI never decides, it proposes.** Classification and extraction carry a confidence score. Anything below the threshold (default **0.75**) or any model failure lands in a visible **“needs human review”** state. So when you test, expect to *confirm/correct* fields — that is the designed behaviour, not a bug.
> 2. **Unconfigured integrations are honest, not fake.** With no SAP / DMS / Excel-tracker endpoints configured (the shipped default), jobs land in **`awaiting_manual_action`** carrying the full payload and instructions. The system will *never* report a posting that did not happen. In local testing this is the **expected, correct** outcome.
> 3. **A real Gemini API key is required for the AI steps.** Everything else (database, login, rules, approvals, shipments, reports, audit) runs fully offline in containers. The AI classification/extraction step needs one free key from Google AI Studio. Where a step needs the key, this guide says so explicitly and tells you what happens if you skip it.

---

## Table of Contents

1. [What you are about to test (the big picture)](#1-what-you-are-about-to-test-the-big-picture)
2. [Phase 0 — Prerequisites: install the tools](#2-phase-0--prerequisites-install-the-tools)
3. [Phase 1 — Get the code](#3-phase-1--get-the-code)
4. [Phase 2 — First-time setup (`make setup`)](#4-phase-2--first-time-setup-make-setup)
5. [Phase 3 — Add your Gemini API key (for the AI steps)](#5-phase-3--add-your-gemini-api-key-for-the-ai-steps)
6. [Phase 4 — (Optional) VAPID keys for Web Push](#6-phase-4--optional-vapid-keys-for-web-push)
7. [Phase 5 — Start the full stack](#7-phase-5--start-the-full-stack)
8. [Phase 6 — Smoke test: prove all five services are alive](#8-phase-6--smoke-test-prove-all-five-services-are-alive)
9. [Phase 7 — Run the automated test suites](#9-phase-7--run-the-automated-test-suites)
10. [Phase 8 — Seed realistic demo data](#10-phase-8--seed-realistic-demo-data)
11. [Phase 9 — Manual end-to-end business walkthrough (the core UAT)](#11-phase-9--manual-end-to-end-business-walkthrough-the-core-uat)
12. [Phase 10 — API-level testing with curl](#12-phase-10--api-level-testing-with-curl)
13. [Phase 11 — Security / negative / boundary testing](#13-phase-11--security--negative--boundary-testing)
14. [Phase 12 — Notifications & email (MailHog)](#14-phase-12--notifications--email-mailhog)
15. [Phase 13 — Reports & audit trail verification](#15-phase-13--reports--audit-trail-verification)
16. [Phase 14 — Lint / format / service-worker gates (what CI enforces)](#16-phase-14--lint--format--service-worker-gates-what-ci-enforces)
17. [Test data reference (logins, codes, payloads)](#17-test-data-reference-logins-codes-payloads)
18. [Troubleshooting — symptoms, causes, fixes](#18-troubleshooting--symptoms-causes-fixes)
19. [Definition of Done — your sign-off checklist](#19-definition-of-done--your-sign-off-checklist)
20. [Appendix A — Ready-made test fixtures included with this guide](#20-appendix-a--ready-made-test-fixtures-included-with-this-guide)

---

## 1. What you are about to test (the big picture)

AGFZE trades non-ferrous metal scrap (copper, aluminium, etc.) between the UAE and Singapore. A supplier’s document (invoice, bill of lading, packing list…) normally arrives in a shared mailbox. The Command Centre replaces “mailbox + spreadsheet” with a governed pipeline:

```
  Document arrives
      │  (shared mailbox via Microsoft Graph  —OR—  Inbox → Upload in the UI)
      ▼
  AI classification  →  category (purchase/sales/fa/logistics/…) + business stream
      ▼
  Schema-driven extraction  →  fields per document type, each with a confidence score
      ▼                          (below 0.75 or model failure → “needs human review”)
  Human confirms / corrects fields
      ▼
  Deterministic batch matching (rapidfuzz — NOT AI)  →  which deal/batch is this?
      ▼
  Rule engine: BR-01…BR-13 + IV-01 + SL-01 + LG-01
      ▼                          (failures open owned exception cases)
  Submission for approval
      ▼
  Maker-checker approval (HOD; self-approval refused; bulk capped)
      ▼
  Posting: SAP job + DMS job + Excel-tracker job
      ▼                          (unconfigured → awaiting_manual_action, honestly)
  Committed deal → shipment board / milestones → daily & monthly reports
      ▼
  Append-only audit trail records who touched what, when, and why
```

Your job as tester is to prove each box in that diagram works. This guide does it in two ways:

- **Automated (Phase 7):** run the project's own pytest + vitest suites. This is the fastest, broadest proof — 1,070 test cases covering the rule engine, approvals, exceptions, matching, security posture, RBAC, and a full end-to-end journey.
- **Manual (Phase 9):** click through the real UI as the different roles (purchase desk, HOD approver, admin, auditor) and drive one document from intake to committed. This is what a business user experiences.

Do both. The automated suite proves the code; the manual walkthrough proves the *process*.

---

## 2. Phase 0 — Prerequisites: install the tools

The stack runs almost entirely in Docker. You need Docker, Make, Git, and Node.js (Node only for the frontend test suite).

### 2.1 Check what you already have

Open a terminal (macOS/Linux: Terminal; Windows: use **PowerShell** or **Git Bash** — Docker Desktop's WSL2 backend works fine) and run:

```bash
docker --version
docker compose version
make --version
git --version
node --version
```

**Expected (minimum) versions:**

| Tool | Required | Example of a good result |
|---|---|---|
| Docker Engine | 24 or newer | `Docker version 27.x.x` |
| Docker Compose | v2 (note: `docker compose`, with a space) | `Docker Compose version v2.x.x` |
| Make | any recent | `GNU Make 4.x` |
| Git | any recent | `git version 2.x` |
| Node.js | **22.x** (only needed for `make test-frontend`) | `v22.x.x` |

### 2.2 Install anything missing

- **Docker Desktop** (includes Docker Engine + Compose v2): https://docs.docker.com/get-docker/ — install, launch it, and wait until the whale icon says “Engine running”. On Linux you can install Docker Engine + the compose plugin separately.
- **Make:**
  - Windows: it ships with **Git for Windows** (https://git-scm.com/) inside Git Bash, or use Chocolatey: `choco install make`.
  - macOS: `xcode-select --install` (provides make), or `brew install make`.
  - Ubuntu/Debian: `sudo apt update && sudo apt install -y build-essential`.
- **Node.js 22:** https://nodejs.org/ (pick the **22 LTS** installer), or use `nvm install 22`.
- **Git:** https://git-scm.com/downloads.

### 2.3 Verify Docker can actually run a container

```bash
docker run --rm hello-world
```

**Expected:** a “Hello from Docker!” message. If this fails, Docker Desktop isn't running or your user isn't in the `docker` group (Linux: `sudo usermod -aG docker $USER`, then log out/in).

### 2.4 Reserve enough resources for Docker Desktop

Open Docker Desktop → **Settings → Resources** and give it at least:
- **CPUs:** 4
- **Memory:** 6 GB (8 GB is comfortable — the stack runs postgres + keycloak + mailhog + backend + frontend)
- **Disk:** 15 GB free

Then **Apply & Restart**.

### 2.5 Know the ports that must be free

The stack binds these host ports. Make sure nothing else is using them (stop other local postgres/keycloak/node apps if needed):

| Port | Service | How to check it's free |
|---|---|---|
| `3000` | Frontend (Next.js) | `lsof -i :3000` (macOS/Linux) or `netstat -ano | findstr :3000` (Windows) |
| `8000` | Backend (FastAPI) | `lsof -i :8000` |
| `8080` | Keycloak | `lsof -i :8080` |
| `8025` | MailHog web UI | `lsof -i :8025` |
| `1025` | MailHog SMTP | `lsof -i :1025` |
| `5432` | PostgreSQL | `lsof -i :5432` |

If a port is busy, stop the conflicting app (e.g. a local Postgres service) before continuing.

---

## 3. Phase 1 — Get the code

### 3.1 Clone the repository

```bash
git clone https://github.com/ram-supervity/AGFZE.git
cd AGFZE
```

**Expected:** the repo downloads and your prompt is now inside the `AGFZE` folder.

### 3.2 Look at what you have (sanity check)

```bash
ls
```

**Expected output** includes: `Makefile`, `docker-compose.yml`, `backend/`, `frontend/`, `infra/`, `.github/`, `README.md`.

> **Tip:** every day-to-day command is wrapped by the `Makefile`. You can see all available targets at any time with:
>
> ```bash
> make help
> ```
>
> It prints `setup`, `dev`, `down`, `migrate`, `seed-demo`, `test`, `test-backend`, `test-frontend`, `lint`, `format-check`, `mail`, `vapid-keys`, `verify-sw`, `clean`, and more, each with a one-line description.

---

## 4. Phase 2 — First-time setup (`make setup`)

`make setup` does all of the following in one go:
1. Copies `backend/.env.example` → `backend/.env` and `frontend/.env.example` → `frontend/.env` (only if they don't already exist).
2. Builds the backend and frontend Docker images.
3. Starts **PostgreSQL** and **Keycloak**.
4. Waits until Postgres reports `healthy`.
5. Applies **every Alembic migration** (21 revisions) to build the schema.
6. Prints the seeded Keycloak test logins.

### 4.1 Run it

```bash
make setup
```

This is the longest step on a fresh machine — it pulls `postgres:15-alpine`, `quay.io/keycloak/keycloak:26.0`, `mailhog/mailhog`, and builds the two app images. **Expect 5–20 minutes** depending on your connection. Do not interrupt it.

### 4.2 What “success” looks like

Near the end you will see something like:

```
Seeded Keycloak logins - local development only, password Passw0rd!

  username        email                         roles
  --------------  ----------------------------  ---------------------------
  hod.approver    hod.approver@agfze.local      approver_hod
  purchase.user   purchase.user@agfze.local     purchase_user
  sales.user      sales.user@agfze.local        sales_user
  fa.user         fa.user@agfze.local           fa_user
  logistics.user  logistics.user@agfze.local    logistics_user
  finance.user    finance.user@agfze.local      finance_user
  admin.user      admin.user@agfze.local        admin
  auditor.user    auditor.user@agfze.local      auditor
  dual.user       dual.user@agfze.local         purchase_user, approver_hod

The realm also seeds the agfze-admin-api service-account client ...
Next: make dev
```

If you reach the “Next: make dev” line, setup succeeded.

### 4.3 The seeded logins (write these down — you will use them constantly)

**Every seeded account uses the same development password: `Passw0rd!`** (capital P, `assw`, zero, `rd`, exclamation mark).

| Sign-in username | Email | Role | Use this account for… |
|---|---|---|---|
| `hod.approver` | hod.approver@agfze.local | `approver_hod` | Approving submitted deals (the **checker** in maker-checker) |
| `purchase.user` | purchase.user@agfze.local | `purchase_user` | Intake, extraction, matching, submitting purchase deals (the **maker**) |
| `sales.user` | sales.user@agfze.local | `sales_user` | Sales legs, sales contract/invoice drafts |
| `fa.user` | fa.user@agfze.local | `fa_user` | FA (second business line) transactions |
| `logistics.user` | logistics.user@agfze.local | `logistics_user` | Shipments, containers, bills of lading, milestones |
| `finance.user` | finance.user@agfze.local | `finance_user` | Finance view, invoice/tolerance exceptions |
| `admin.user` | admin.user@agfze.local | `admin` | Admin screens: rule thresholds, document schemas, users, integrations, audit |
| `auditor.user` | auditor.user@agfze.local | `auditor` | Read-only audit trail explorer & CSV export |
| `dual.user` | dual.user@agfze.local | `purchase_user` + `approver_hod` | Convenience account (note: it still **cannot self-approve**) |

> **Key test point:** the maker-checker control is enforced in the *service*, not the UI. Even `dual.user` (who holds both roles) **cannot approve a transaction they themselves submitted**. You will prove this in Phase 11.

---

## 5. Phase 3 — Add your Gemini API key (for the AI steps)

Classification and extraction call **Google Gemini 2.5 Flash**. You need a free API key.

### 5.1 Get a key (free, ~2 minutes)

1. Go to **Google AI Studio**: https://aistudio.google.com/apikey
2. Sign in with a Google account.
3. Click **Create API key** → choose **Create API key in new project** (or an existing project).
4. Copy the key — it looks like `AIzaSyA...` (about 39 characters). Keep that tab open for a moment.

### 5.2 Put it in the backend environment file

Open `backend/.env` (created by `make setup`) in any text editor. Find this line:

```env
GEMINI_API_KEY=replace-with-your-gemini-api-key
```

Replace the placeholder with your real key:

```env
GEMINI_API_KEY=AIzaSyA-your-actual-key-here
```

Confirm the surrounding lines are present (they should already have these defaults):

```env
ENV=development
AI_PROVIDER=gemini_flash
GEMINI_MODEL=gemini-2.5-flash
CONFIDENCE_THRESHOLD_DEFAULT=0.75
```

Save the file.

### 5.3 What if I skip the key?

Everything except the AI calls works. When you upload a document, classification/extraction will **fail honestly** and the request will sit in the **needs human review / failed** state rather than being guessed onward — which is itself a valid test of the “AI never silently invents” promise (see Phase 11). But to walk the *happy path* you want the key.

> **Note on restart:** the backend reads `.env` at container start. If the stack is already running when you add the key, restart the backend so it picks it up:
>
> ```bash
> docker compose restart backend
> ```
>
> (If you haven't started the stack yet, Phase 5 will pick it up automatically.)

---

## 6. Phase 4 — (Optional) VAPID keys for Web Push

In-app notifications always work. **Email** works locally via MailHog. **Web Push** (browser push notifications) needs a VAPID key pair. This is optional for a functional test — if you skip it, the push control in Settings honestly says “this deployment has no push key” rather than offering a broken button. If you want to test push:

```bash
make vapid-keys
```

It prints two lines, e.g.:

```
VAPID_PUBLIC_KEY=BKx...long...
VAPID_PRIVATE_KEY=4kZ...long...
```

- Paste **both** lines into `backend/.env`.
- Paste the **public** line's value into `frontend/.env` as `NEXT_PUBLIC_VAPID_PUBLIC_KEY=BKx...` (the private key must **never** go in the frontend file).
- Regenerate the key pair only once per environment — regenerating invalidates every browser subscription.

Then restart the stack so the values are read (`docker compose up -d` or `make dev` again).

> For most testers: **skip this on the first pass** and come back after the end-to-end walkthrough.

---

## 7. Phase 5 — Start the full stack

### 7.1 Start everything (foreground, recommended for first run)

```bash
make dev
```

This runs `docker compose up` in the foreground so you see all logs streaming. The backend container runs `alembic upgrade head` (migrations) **before** `uvicorn` starts, so the schema is always current.

**Detached alternative** (if you want your terminal back):

```bash
docker compose up -d
make logs        # follow logs of every service; Ctrl+C stops following but not the containers
```

### 7.2 What “up and healthy” looks like in the logs

- **postgres:** `database system is ready to accept connections`
- **keycloak:** `Running the server in development mode` and `Admin console listening` / `Keycloak 26.0.x on JVM`
- **mailhog:** `[SMTP] Binding to address: 0.0.0.0:1025` and `[HTTP] Binding to address: 0.0.0.0:8025`
- **backend:** `INFO:     Uvicorn running on http://0.0.0.0:8000` and `Application startup complete`
- **frontend:** `▲ Next.js 15.5.x` and `Ready in ...` / `✓ Ready`

First start of the Next.js container compiles the app; give it ~30–60 seconds before opening the browser.

### 7.3 The five URLs you will use

| URL | What it is | Opens to |
|---|---|---|
| http://localhost:3000 | **The application** (the thing business users use) | Sign-in page |
| http://localhost:8000/docs | Swagger UI (development only) | Interactive API docs |
| http://localhost:8000/health/ready | Readiness probe | JSON health body |
| http://localhost:8080 | Keycloak admin console | Login `admin` / `admin` |
| http://localhost:8025 | MailHog — every notification email the platform “sends” | Inbox (nothing leaves your machine) |

To stop the stack later: press `Ctrl+C` in the foreground terminal, or `docker compose down` (add `-v` to also wipe data — see `make clean`).

---

## 8. Phase 6 — Smoke test: prove all five services are alive

Before testing features, prove the plumbing. In a **new terminal** (leave `make dev` running):

### 8.1 Backend liveness (process only, never touches the DB)

```bash
curl -s http://localhost:8000/health
```

**Expected:** a JSON body with `status: ok` (HTTP 200).

### 8.2 Backend readiness (must reach the database)

```bash
curl -s http://localhost:8000/health/ready
```

**Expected:**

```json
{"success":true,"data":{"status":"ready","database":"ok"},"message":null,"errors":null}
```

If you instead get HTTP 503, the database isn't reachable — check `docker compose ps` and the postgres logs.

### 8.3 The standard response envelope

Note the shape: every API response uses one envelope — `{ "success": ..., "data": ..., "message": ..., "errors": ... }`. Every response also carries an `X-Request-ID` header — quote that ID when reporting a bug.

Check the header:

```bash
curl -si http://localhost:8000/health/ready | grep -i x-request-id
```

**Expected:** a line like `x-request-id: 7f3c...`.

### 8.4 Confirm containers are up

```bash
docker compose ps
```

**Expected:** five services (`agfze-postgres`, `agfze-keycloak`, `agfze-mailhog`, `agfze-backend`, `agfze-frontend`) all listed as `running` / `healthy`.

### 8.5 Open the frontend

In a browser go to **http://localhost:3000**. You should be redirected to the sign-in page (or straight to Keycloak). If the page loads, the frontend container is serving.

### 8.6 Open the other two consoles

- **http://localhost:8080** → Keycloak login page appears (sign in `admin`/`admin` if you want to explore the realm; you normally won't need to).
- **http://localhost:8025** → MailHog shows an empty inbox (“No messages” until the platform sends a notification).

> **Smoke test pass criteria:** readiness returns `database: ok`, `docker compose ps` shows five healthy/running services, and http://localhost:3000 loads. If any of these fail, fix it here (see Troubleshooting) before going further — there is no point testing features on a broken stack.

---

## 9. Phase 7 — Run the automated test suites

This is the broadest proof that the platform works. There are two suites: backend (pytest, 721 async tests) and frontend (vitest, 349 cases).

### 9.1 Backend tests

```bash
make test-backend
```

What it does: ensures Postgres is up, then runs `pytest -q` inside the backend container with `ENV=testing`, pointed at the `agfze_test` database (the `infra/postgres/init-test-db.sh` script creates that database idempotently). The suite can also fall back to a disposable SQLite file under `./var` for a container-less checkout — but with Docker up it uses real PostgreSQL, which is what CI does.

**Coverage includes:** intake pipeline, AI classification/extraction routing, deterministic matching, the full rule engine (BR-01…BR-13 plus the LME, invoice-date `IV-01`, cross-shipment `SL-01`, and OBL-weight `LG-01` rules), FA and sales modules, approvals (incl. self-approval refusal and bulk ceiling), exceptions & escalation, shipments & staleness sweep, integration jobs & payload mapping, reports & distribution, retention, audit explorer, storage, SMTP + push delivery, email ingestion/reply, the RBAC matrix, security posture, architecture promises, and a full end-to-end journey.

**Expected result (success):**

```
............................................................................ [......]
............................................................................ [......]
...
721 passed in ...s
```

You want to see **all tests passed** (the exact count is pinned in the README at 721; it may differ slightly if the tree has changed — what matters is `passed` with **0 failed**).

> If you want the verbose list of test names, run pytest verbosely:
>
> ```bash
> docker compose run --rm -e ENV=testing -e TEST_DATABASE_URL=postgresql+asyncpg://agfze:agfze@postgres:5432/agfze_test backend pytest -v
> ```

### 9.2 Frontend tests

These need Node 22 and the frontend dependencies installed.

```bash
make test-frontend
```

This runs `cd frontend && npm run test` (vitest + Testing Library + jsdom). The first time, if `frontend/node_modules` isn't present, install deps first:

```bash
cd frontend
npm install
cd ..
make test-frontend
```

**Coverage includes:** navigation gating, roles, the command palette, dashboard view, intake and category tabs, transaction and FA/sales panels, trace panel, approvals/reply panel, charts, admin tables, report viewer and templates, the CSP builder, offline governance, PWA behaviour, service-worker strategy and runtime, and the manifest.

**Expected result (success):**

```
 ✓ src/... (some test file)
 ...
 Test Files  34 passed (34)
      Tests  349 passed (349)
```

You want **all files and tests passed, 0 failed**.

### 9.3 Run both together

```bash
make test
```

This is exactly `test-backend` followed by `test-frontend`.

### 9.4 Recording your result

Write down:
- Backend: number passed / failed (e.g. “721 passed, 0 failed”).
- Frontend: files passed, tests passed / failed (e.g. “34 files, 349 passed, 0 failed”).
- Any failure: capture the failing test name, the assertion, and the output — and quote the `X-Request-ID` if it involved the API.

> **Interpretation:** a green `make test` means the code's logic — every business rule, every security control, the maker-checker rule, the honest-integration outcomes — is verified by the project's own tests. This is the single strongest signal that the platform is working.

---

## 10. Phase 8 — Seed realistic demo data

The freshly migrated database has the configuration (document schemas, rule configurations) but no deals. The seed script loads obviously-synthetic sample data so you can see every screen populated immediately — including states you'd otherwise wait days to observe (a stale shipment, aged exceptions, an approval waiting on a decision).

```bash
make seed-demo
```

What it creates (all names end in “(demo)” and batch numbers use the `DEMO-` prefix, so sample data is never mistaken for a real deal):

- **One purchase transaction with a supplier pack** ready to match against a bill of lading.
- **Four batches** on/around sales contract `DEMO-SC-2026-441`:
  - `DEMO-I2626-1` (24.500 MT) — has a sales leg
  - `DEMO-I2626-2` (31.250 MT) — has a sales leg
  - `DEMO-I2626-3` (18.000 MT) — **no sales leg yet** — this is the batch a *sales-side* test document is meant to match
  - `DEMO-I2626-4` (27.750 MT) — **sitting in Approval Pending** with a real approval task, so you can approve it and watch its three integration jobs land in “awaiting manual action”
- **One FA transaction** (`DEMO-FA2626-1`) carrying the minimal seeded FA fields.
- **Two shipments** — one checked 30 minutes ago (fresh), one last checked **72 hours ago** (deliberately past the 48-hour staleness threshold so the staleness indicator and the auto-opened exception are visible immediately).
- **Three open exception cases**, one in each ageing band (low-confidence owned by purchase, invoice-amount-outside-tolerance owned by finance, shipment-status-unavailable owned by logistics, aged ~6h / ~30h / ~100h).
- **14 finished deals across the last 45 days**, deliberately varied (some clean, some with exceptions, some with corrected fields) so the dashboard's automation %, non-override rate and turnaround chart show real spread rather than 0%/100%.

The script **refuses to run against a production environment** (it checks `ENV`).

**Expected output:** log lines ending with a summary of what was written, and no traceback. Refresh the app and the dashboard, transactions, shipments, exceptions and approvals screens will now be populated.

> **You can run the walkthrough in Phase 9 with or without seed data.** With seed data you can also test the *approval → integration* leg immediately (Step 9.6) using `DEMO-I2626-4` without preparing a deal by hand.

---

## 11. Phase 9 — Manual end-to-end business walkthrough (the core UAT)

This is the heart of testing. You will drive a supplier invoice from intake all the way to a committed deal, switching roles like a real office would. Use the two ready-made documents in **`test-fixtures/`** (see [Appendix A](#20-appendix-a--ready-made-test-fixtures-included-with-this-guide)):

- `sample-supplier-invoice.docx` — a Copper Scrap Millberry commercial invoice, batch **`TEST-I2626-01`**, 24.500 MT net, USD 8,125/MT, total **USD 199,062.50**, container `DEMU7781234`, B/L `MAEU7712345`.
- `sample-bill-of-lading.docx` — the matching Maersk bill of lading for the same batch/container.

> These are `.docx` files. The intake pipeline reads DOCX via its text layer (PDF, DOCX, XLSX, XLS, CSV, JPG, PNG are all admitted by magic-byte inspection), so they upload and extract exactly like a PDF. If you prefer a PDF, open either in Word/LibreOffice and “Save as PDF”.

---

### Step 9.1 — Sign in as the purchase desk (the maker)

1. Go to **http://localhost:3000**.
2. You'll be redirected to Keycloak. Enter:
   - **Username:** `purchase.user`
   - **Password:** `Passw0rd!`
3. Click **Sign in**.

**Expected:** you land on the **Dashboard**. If it's the first login you may see a short onboarding walkthrough; click through it (there's a “Got it / Skip” control; completing it calls `/users/me/onboarding-complete`).

**Inputs to try / verify:**
- The dashboard shows role-scoped counts for the purchase desk (intake queue, my transactions, open exceptions, pending approvals where relevant).
- Open the **command palette** (usually `Ctrl/Cmd + K`) and confirm you can search/jump to screens.
- Click the **notification bell** — it opens the notifications panel (in-app notifications always work).

**Negative check — wrong password:** sign out, then sign in as `purchase.user` with password `wrongpassword`. Keycloak rejects it and you stay on the login page with an error. That's correct.

---

### Step 9.2 — Intake: upload the supplier invoice

With real Azure/Graph credentials the mailbox worker would pull the email automatically. Locally we use the **manual upload**, which feeds the *identical* intake pipeline from that point on.

1. In the left nav, open **Inbox** (this is the requests queue).
2. Click the **Upload** button (top-right of the inbox).
3. In the file picker, choose **`test-fixtures/sample-supplier-invoice.docx`**.
4. Confirm/upload.

**Under the hood (what you're verifying):** the file is streamed to `POST /api/v1/documents/upload`. The server inspects the **leading bytes with libmagic** (it never trusts the extension), enforces the **25 MB** limit while streaming, computes a SHA-256 content hash, and stores the bytes under an opaque UUID key (the original filename is never part of the path).

**Expected:**
- A new **request** appears in the inbox. The AI pipeline runs: it **classifies** the document (expected category **`purchase`**, business stream **`scrap`**) and then **extracts** fields against the purchase-invoice document schema.
- The request may briefly show a processing state, then land in one of two states:
  - **Extracted / ready to review** (confidence ≥ 0.75) — good.
  - **Needs human review** (any field below threshold, or no/—invalid Gemini key) — also a correct, designed state; you'll handle it in 9.3.

**Input values you should see extracted (verify against the fixture):**

| Field on screen | Expected value from the invoice |
|---|---|
| Category | `purchase` |
| Business stream | `scrap` |
| Invoice number | `ECT/INV/2026/0847` |
| Invoice date | `2026-08-28` |
| Contract number | `SC-2026-UAE-118` |
| Batch / lot number | `TEST-I2626-01` |
| Supplier (counterparty) | `Emirates Copper Trading LLC` |
| Commodity / grade | Copper Scrap – Millberry (Cu 99.9%) |
| Net weight / quantity | `24.500` MT |
| Gross weight | `24.780` MT |
| Unit price / rate | `8125.00` USD/MT |
| Invoice value / amount | `199062.50` USD |
| Container number | `DEMU7781234` |
| Bill of lading number | `MAEU7712345` |
| Incoterms | `CIF Singapore` |

> Field names on screen follow the configured `document_type_schemas` rows; you may see slightly different labels (e.g. “Invoice value” vs “Total amount”). What matters is that the **numbers match the document**.

---

### Step 9.3 — Review and correct the extraction (the human gate)

1. Click the new request to open its detail view (extracted fields + the stored document; page images are served via signed, expiring URLs).
2. **Deliberately test a correction:** find the **rate/unit price** field. Suppose it read slightly wrong — set it to exactly `8125.00`. Find **net weight** and confirm/set `24.500`.
3. For each correction, the UI asks for a **reason** (every override is recorded with why). Enter e.g.:
   - Reason for rate: `Corrected to match printed unit price on invoice`
   - Reason for weight: `Confirmed against packing list figure`
4. If the AI put it in “needs human review”, confirm the category is `purchase` (use the **Reclassify** action only if the category is wrong — try it: you can change category and it re-extracts against the new type's schema via `/documents/{id}/reclassify`).
5. When the fields look right, click **Confirm extraction** (`POST /documents/{id}/confirm`).

**Expected / verify:**
- Each field shows a confidence score and an indicator of whether it was AI-extracted or human-overridden.
- Your corrections are stamped with your identity and reason (you'll see them in the audit trail later).
- **The moment you confirm, the matcher runs.**

> **Test the “honest AI” behaviour:** if you didn't set a Gemini key (Phase 3), the document lands in needs-review and you *manually* fill the fields. Prove you can still complete the flow — the platform never blocks you waiting on a model, and never invents a value.

---

### Step 9.4 — Batch matching (deterministic, not AI)

After confirm, the **matching service** (rapidfuzz fuzzy match on batch number / references / counterparty + quantity proximity) suggests which deal this document belongs to.

- Because the invoice uses batch **`TEST-I2626-01`** (a brand-new batch), the matcher will likely either **offer to open a new batch** or suggest the closest existing batch with a similarity score and a confidence floor.
- **Two valid test paths — pick based on what the UI offers:**
  - **Path A (new batch):** choose **“Open new batch / create new transaction”**. A purchase transaction is created for batch `TEST-I2626-01`.
  - **Path B (match to a suggestion):** open the **Match** preview (`GET /documents/{id}/match`), review the suggested batch's reference numbers, quantities and counterparty similarity, then **Resolve/confirm** the match (`POST /documents/{id}/match`).

**Expected/verify:**
- The match is explained (which references matched, the quantity spread, the similarity score) — it's reproducible and deterministic, not an AI guess.
- The container `DEMU7781234` is recorded; matching a bill of lading later links a shipment.

**Try this to see a confident match:** if you also upload **`sample-bill-of-lading.docx`** (same batch `TEST-I2626-01`, same container `DEMU7781234`), it should match the same batch/transaction and, because it's a logistics document, contribute the bill-of-lading that gates shipment. Walk it through upload → classify (expect category **`logistics`**) → confirm → match the same batch.

---

### Step 9.5 — Validation: the rule engine and exceptions

When the transaction has its legs (purchase, and any sales/FA legs), the **rule engine** evaluates every relevant evaluator: **BR-01…BR-13** (traceability, reference presence, container agreement, mandatory document packs, quantity & invoice-value tolerance, OBL gating, duplication links…) plus **IV-01** (invoice dating), **SL-01** (cross-shipment contract coverage) and **LG-01** (invoiced weight vs bill of lading).

1. Open the **transaction** you just created (navigate via Transactions → Purchase, or click through from the request).
2. Review the **rules/validations** panel. Each rule shows pass/fail.
3. **Deliberately trigger a rule failure to test the exception path:**
   - Edit a field to break a tolerance — e.g. open **Fields** (`PATCH /transactions/{id}/fields`) and set the **invoiced quantity** to `27.000` MT while the bill of lading / contracted quantity is `24.500` MT (outside tolerance), or change the invoice value to `250000.00`. Validation re-runs.
   - **Expected:** a failing `BR-*` rule opens an **exception case**, owned by the desk that works that leg (e.g. finance for an invoice-value tolerance breach, logistics for a weight/OBL issue).
4. Open the **Exceptions** queue. You'll see the new case plus the seeded ones (the three aged demo cases). It shows the **rule, the field, the expected vs actual values, the owner, the age, and the priority**.
5. **Resolve it properly:**
   - Put the quantity back to `24.500` (a genuine fix) — the rule re-evaluates and the case can be **resolved** (`POST /exceptions/{case_id}/resolve`).
   - Or, for a breach that's genuinely acceptable, if it's an `acknowledgeable` severity you can **acknowledge the tolerance** within the self-approval limits (`POST /transactions/{id}/acknowledge-tolerance`) — note this is bounded; not every breach is self-acknowledgable.
   - Or **escalate to the HOD** from the exception (you'll see the escalation move it up).

**Expected/verify:**
- Exceptions have an **owner**, an **age** that visibly grows, and an **escalation** path.
- A case only resolves through a genuine fix or an explicit person's decision — never silently.
- The seeded stale shipment (`DEMO-…` last checked 72h ago) already demonstrates the **staleness sweep**: logistics should see a shipment-status-unavailable exception auto-opened because nobody established where the cargo is for >48h.

---

### Step 9.6 — Submit for approval, then approve as the HOD (maker-checker)

A fully validated transaction (no blocking rule failures) can be **submitted for approval**.

**As `purchase.user` (maker):**
1. On the transaction, click **Submit for approval** (`POST /transactions/{id}/submit`).
   - If it won't submit, the UI tells you which rule/exception is still blocking — fix those first.
2. The transaction moves to **Approval Pending** and lands in the ranked approval queue.

**Now switch to the approver (checker).** Sign out and sign in as:
- **Username:** `hod.approver`
- **Password:** `Passw0rd!`

3. Open **Approvals**. The queue is **ranked** — use the `rank_by` toggle: **age** (oldest first), **value** (largest deal first), or **risk** (highest risk first).
4. Open your submitted transaction's approval (`GET /approvals/{id}`).
   - The first time you open it, an **AI summary of the numbers is generated once and cached** (it doesn't regenerate and rack up model calls). Read it.
5. Click **Approve** (or **Reject** with a reason) — `POST /approvals/{id}/decide`.
   - Test rejection too on a throwaway: reject with reason `Docs incomplete - B/L weight mismatch` and confirm it returns to the preparer.

**Expected/verify after approval:**
- The transaction moves to **Integration Pending**, then the posting step runs.
- **Three integration jobs are created**: a **SAP** contract/price posting, a **DMS** document pack, and an **Excel-tracker** row.
- Because SAP/DMS/tracker endpoints are **unconfigured by default**, each job lands at **`awaiting_manual_action`** carrying the **complete payload plus manual-filing instructions**. Open **Integrations / Jobs** to see them. This is the **correct, honest** result locally — the job does **not** claim success.
- After the jobs are actioned (or, when configured for real, posted successfully with an `external_reference` recorded), the transaction reaches **`committed`**.

**Bulk approval test:** select multiple low-risk pending approvals and use **Bulk approve** (`POST /approvals/bulk-decide`). It approves only the lowest-risk set **under the configured ceiling** (`GOV-01`); anything over the cap stays queued. If you seeded demo data, there may be several pending items; otherwise create a couple more cheap deals.

---

### Step 9.7 — Test the maker-checker control itself (critical security step)

Sign in as **`dual.user`** (password `Passw0rd!`) — this account holds *both* `purchase_user` and `approver_hod`.

1. Prepare and **submit** a transaction as this account.
2. Stay signed in as the same account and try to **approve** it.

**Expected:** the approve action is **refused** (the service enforces that the submitter cannot be the approver — not merely hidden in the UI). You should get an error like “self-approval is not permitted.” This proves maker-checker separation of duties holds even when one person has both roles.

---

### Step 9.8 — Shipments, containers and the board

Sign in as **`logistics.user`** (`Passw0rd!`).

1. Open **Shipments** (the shipment board).
2. **Verify the seeded data:** one shipment fresh (checked ~30 min ago) and one **stale** (72h) with an open staleness exception.
3. Open a shipment linked to your deal (or a demo one). You'll see the **milestone timeline**, the **container(s)**, the **bill of lading**, ETA, and any **post-delivery issues**.
4. **Record a milestone by hand:** click **Update status** (`PATCH /shipments/{id}`) and set e.g. status to “Arrived / Discharged” with a date and note:
   - Note: `Vessel berthed Singapore, discharge commenced`
   - The update goes through the single update path, so plausibility checks and audit can't be bypassed.
5. **Try a carrier refresh:** click **Refresh** (`POST /shipments/{id}/refresh`). With no carrier adapter configured for that carrier, the system keeps the status honest by hand (the carrier adapter registry is deliberately empty today) — it won't fabricate a tracking result.
6. **Log a post-delivery issue** (`POST /shipments/{id}/issues`), e.g.:
   - Type: weight/quality discrepancy; note: `Receiver reports 0.3 MT moisture loss on discharge`
   - **Expected:** an issue is recorded and can open/feed an exception.

**Verify the staleness sweep:** leave the stale demo shipment untouched; the sweep (running while `min_instance` logic keeps workers alive) opened an owned exception because no one had checked location for >48h. After you update its status, the staleness clears.

---

### Step 9.9 — Sales and FA legs (optional but recommended)

- **Sales (`sales.user`):** open a purchase transaction and **attach a sales leg** (`POST /transactions/{id}/sales-leg`) — e.g. sell the 24.500 MT onward to a Singapore customer. Then **generate a draft** (`POST /transactions/{id}/generate-draft`): the platform renders a sales contract/invoice **DOCX from the shipped templates**; the model picks clauses but **validation decides**. Review the draft. With seed data, the batch **`DEMO-I2626-3`** (no sales leg) is the intended target for a sales-side test document.
- **FA (`fa.user`):** open **FA transactions**, view the seeded FA deal `DEMO-FA2626-1`. Note FA fields like `rate`/`amount` live in `extra_fields` because no named column has been agreed — the module stores nothing it wasn't configured to store. Register a new FA transaction by hand (`POST /transactions/fa`) to confirm the minimal field set.

---

### 9.10 — End-to-end acceptance summary

By the end of Phase 9 you should have personally observed:

- ✅ Sign-in per role works; wrong password rejected.
- ✅ A document uploads, is type-admitted by magic bytes, classified, and extracted.
- ✅ Low-confidence / model-failure → human review (no silent guessing).
- ✅ Fields can be corrected with a mandatory reason; overrides are stamped.
- ✅ Matching is deterministic and explained; new batch can be opened.
- ✅ Rule failures open **owned, aged, escalatable** exceptions; fixes resolve them.
- ✅ Submission → ranked approval queue → HOD decision; AI summary generated once.
- ✅ **Self-approval refused** even for a dual-role account.
- ✅ Bulk approval respects the ceiling.
- ✅ Three integration jobs created; unconfigured → **awaiting_manual_action** (honest), never fake success.
- ✅ Shipment board, milestones, hand updates, issues, staleness sweep.
- ✅ Sales draft generation and FA minimal-field behaviour.

---

## 12. Phase 10 — API-level testing with curl

The UI talks to the FastAPI backend. You can test the API directly, which is faster for some checks and gives you the raw envelope.

### 12.1 Health (no auth)

```bash
curl -s http://localhost:8000/health/ready
```

### 12.2 Get an access token from Keycloak (password grant)

```bash
TOKEN=$(curl -s -X POST http://localhost:8080/realms/agfze/protocol/openid-connect/token \
  -d grant_type=password \
  -d client_id=agfze-command-centre \
  -d client_secret=agfze-local-dev-secret \
  -d username=purchase.user \
  -d password=Passw0rd! | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')

echo "${TOKEN:0:20}..."   # just confirm you got a token (prints first 20 chars)
```

**Expected:** `TOKEN` is a long JWT beginning with `eyJ...`. If it's empty, the realm isn't ready or credentials are wrong — wait a few seconds for Keycloak and retry.

### 12.3 Your profile (auth required)

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/users/me
```

**Expected:** `{"success":true,"data":{"username":"purchase.user", ... roles ...},...}`.

### 12.4 Role-scoped dashboard

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/dashboards/summary
```

**Expected:** aggregate counts scoped to the purchase role. (Log in as `hod.approver` and repeat — the numbers differ by role; scoping happens in the query, not by hiding data afterwards.)

### 12.5 Upload a document via the API (multipart)

From the repo root (so the relative path resolves), or use the absolute path to the fixtures:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  -F "file=@test-fixtures/sample-supplier-invoice.docx" \
  http://localhost:8000/api/v1/documents/upload
```

**Expected:** a `success:true` envelope describing the new document/request with an ID. Use that ID in the next calls.

### 12.6 List requests and fetch one

```bash
curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:8000/api/v1/requests?limit=20"
```

Copy a `request_id` from the response, then:

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/requests/<REQUEST_ID>
```

### 12.7 Confirm extraction and preview a match

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/documents/<DOCUMENT_ID>/confirm

curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/documents/<DOCUMENT_ID>/match
```

### 12.8 Generate a report now (background job)

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"scope":{"stream":"scrap"},"range":"month","month":"2026-08"}' \
  http://localhost:8000/api/v1/reports
```

**Expected:** a job is created; poll it:

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/jobs/<JOB_ID>/status
```

Then fetch the report:

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/reports
```

### 12.9 Explore the full interactive API docs

Open **http://localhost:8000/docs** (Swagger UI). You can click **Authorize**, enter the token (or use the “lock” with the client credentials), and fire any of the 16 routers' endpoints from the browser. This is the fastest way to poke at `/approvals`, `/exceptions`, `/shipments`, `/integrations/jobs`, `/audit`, etc.

> **Note:** Swagger is served only in development/testing. In production `/docs` is not exposed at all — that itself is a security control.

---

## 13. Phase 11 — Security / negative / boundary testing

These prove the platform fails *safely*. Work through each.

### 13.1 Authentication is enforced on every protected route

```bash
curl -s http://localhost:8000/api/v1/users/me
```

**Expected:** `401 Unauthorized` (no token). Only `/health`, `/health/ready`, and the Graph webhook are reachable without auth.

### 13.2 Forged / tampered token is rejected

```bash
curl -s -H "Authorization: Bearer eyJ.forged.signature" http://localhost:8000/api/v1/users/me
```

**Expected:** `401`. The backend verifies the RS256 signature against Keycloak's JWKS endpoint (with `aud`/`azp` fallback and 30s clock-skew leeway).

### 13.3 RBAC — a desk cannot reach admin functions

Sign in (or fetch a token) as `purchase.user` and attempt an admin read:

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/admin/rules
```

**Expected:** `403 Forbidden`. Admin screens require `admin` (auditor gets read-side). Changes to rule thresholds also require a **recorded reason**.

### 13.4 File-type admission is by magic bytes, not extension

Test that a disallowed type is refused. The whitelist admits **only** PDF, Word (.docx), Excel (.xlsx/.xls), CSV, JPEG, PNG, and the **25 MB** streaming limit applies.

- **Negative:** create a file that is *not* an allowed type and try to upload it — e.g. a script renamed `.pdf`:
  ```bash
  echo 'print("hi")' > fake.pdf
  curl -s -H "Authorization: Bearer $TOKEN" -F "file=@fake.pdf" \
    http://localhost:8000/api/v1/documents/upload
  ```
  **Expected:** `415 Unsupported File Type` — the leading bytes are plain text, not a PDF.
- **Negative — oversized:** uploading a >25 MB file returns **`413 file_too_large`** (refused while streaming, before full buffering).
- **Negative — empty:** a 0-byte file returns **`400 empty_file`**.
- **Positive control:** uploading the real `.docx` fixtures succeeds (proves the whitelist allows what it should).

### 13.5 Maker-checker: self-approval refused

Already covered in 9.7 — the same identity cannot approve what it submitted, even with both roles. Confirm you get an explicit refusal.

### 13.6 Rule threshold changes require a reason and are audited

As `admin.user`, open **Admin → Rules**, change a threshold (e.g. the quantity tolerance for a commodity) and try to save **without** a reason.

**Expected:** the save is rejected until you provide a change reason. With a reason (e.g. `Tolerance widened per trading desk memo 2026-08`) it saves and the change appears in the **audit trail**. Restore the original value afterward with another reasoned change.

### 13.7 Security headers are present on every response

```bash
curl -si http://localhost:3000 | grep -iE 'strict-transport|content-security-policy|x-frame|x-content-type|cache-control'
```

**Expected (development; HSTS/CSP/no-store ride every response):** CSP header present, `X-Content-Type-Options: nosniff`, frame protection, and no-store on sensitive responses. The Next.js middleware adds a **nonce-based CSP** on every response and gates `/protected` behind a session.

### 13.8 Offline behaviour is a governance boundary, not a bug

With the app loaded in the browser, open DevTools → Network → set **Offline**, then navigate. The PWA service worker serves the app shell and **stale reads** offline (you'll see the `offline` page fallback if needed), but **no mutating request (submit/approve/upload) is ever cached or queued**. Verify that while offline you can view cached read screens but cannot perform an action — and when back online everything works.

### 13.9 Production settings refuse to start unsafe

CI proves this, but conceptually verify the config: with `ENV=production`, the backend **refuses to start** unless credentials, rate limits, a shared (non-`memory://`) rate-limit store, exact-origin CORS (no `*`), a signed-URL secret, non-localhost `APP_BASE_URL`, SMTP, VAPID, and storage bucket are all present. You don't run production locally — just confirm via `/docs` that docs are hidden in prod and via `backend/app/core/config.py` that the checks exist (the automated suite covers this).

---

## 14. Phase 12 — Notifications & email (MailHog)

In-app notifications always work; email is captured locally by **MailHog** so nothing ever leaves your machine.

### 14.1 Open MailHog

Go to **http://localhost:8025**. Initially empty.

### 14.2 Trigger a notification email

Events that notify include: an exception opened/assigned, an approval awaiting a decision, an integration job needing manual action, a report generated (per distribution rules).

The quickest trigger: in Phase 9, when the HOD has a pending approval, or when an exception is opened/assigned to a desk, the platform sends an email via the single `notify()` seam (in-app + email + push each fail independently and honestly).

**Expected:** within a few seconds a new message appears in MailHog. Open it — you see the **HTML part, the plaintext part, and the headers**. The email's call-to-action link is built from `APP_BASE_URL` (`http://localhost:3000`), not from a request header.

### 14.3 In-app notifications

Click the **bell** in the app header. Your notifications list matches the events that happened to your role. Use **Mark all read** (`POST /notifications/mark-all-read`) and confirm the count clears.

### 14.4 (If VAPID configured) Web Push

In **Settings**, enable push notifications; the browser subscribes using the server's VAPID public key (`GET /notifications/vapid-public-key`). With no VAPID key configured, the UI honestly states push is unavailable rather than showing a dead button.

---

## 15. Phase 13 — Reports & audit trail verification

### 15.1 Generate and read a report

1. As any business user (or admin), open **Reports**.
2. Generate a report now (or use the API in 12.8): scope `stream = scrap`, range **month**, month **2026-08**.
3. When the background job finishes, open the report. Reports render to **PDF + XLSX** from the governed tables at generation time.

**Verify the “honest reporting” promises:**
- Every figure carries the **filters that reproduce it** (drill-through) — click a number and see the underlying query/rows.
- Every page states that the **platform has not sent the report to anybody** (distribution is governed separately).
- The dashboard reports the **age of the data it served** (cache TTL is 45s on purpose).

### 15.2 Scheduled reports & distribution (admin)

As `admin.user`, open **Admin → Report distribution** and **Report templates**.
- Distribution rules decide **who receives which scheduled report on which channel** (daily at 06:00 UTC for the previous day; monthly on day 1).
- Templates define what sections/figures a report carries — renderers never hardcode a section name.
- Confirm you can view these; editing requires the same governed/reasoned approach.

### 15.3 The audit trail (auditor role)

Sign in as **`auditor.user`** (`Passw0rd!`) and open **Admin → Audit** (or the Audit screen).

**Verify:**
- You can filter the append-only trail by actor, action, time, entity.
- You can see **your own actions from Phase 9**: the upload, each field correction **with its reason**, the category confirm, the match, the rule failure/exception, the submission, the HOD's approval decision, the integration jobs, the shipment update.
- Each row records **who, what, when, and why** (metadata only — payloads aren't dumped).
- **Export CSV** (`GET /audit/export`) streams the filtered trail (it streams, doesn't buffer). Download it and open it — your test actions are in there.

> This is the traceability promise made visible: every figure and every decision links back to the action and, ultimately, to the source document.

---

## 16. Phase 14 — Lint / format / service-worker gates (what CI enforces)

CI is blocking and nothing is advisory. Run the same gates locally:

### 16.1 Lint both apps

```bash
make lint
```

- Backend: **Ruff** check (`ASYNC, B, C4, E, F, I, SIM, UP, W, RUF` rules, 100-char lines, isort-aware with `app`/`tests` as first-party).
- Frontend: **ESLint** (`next/core-web-vitals`) + **`tsc --noEmit`** type check.

**Expected:** no errors.

### 16.2 Format check (exactly what CI asserts)

```bash
make format-check
```

Runs `ruff format --check .` (backend) and `eslint . --max-warnings=0` (frontend). **Expected:** passes with no diff. (If it complains, run `make format` to autofix the backend.)

### 16.3 Service-worker manifest verification

```bash
make verify-sw
```

Fails the build if the precache manifest baked into the service worker doesn't match the current build (the worker precaches the app shell at build time; it's hand-written and tested). **Expected:** passes.

### 16.4 (CI-only, conceptual) Migration & production-startup proofs

CI additionally proves the schema builds from nothing (`alembic upgrade head` → `downgrade base` → `upgrade head` → `alembic check`) and that the production image refuses an unsafe configuration. You don't run these locally day-to-day, but `make test` + the gates above cover everything you'd commit against.

---

## 17. Test data reference (logins, codes, payloads)

### 17.1 Logins (all passwords `Passw0rd!`)

| Username | Role |
|---|---|
| `hod.approver` | approver_hod (checker) |
| `purchase.user` | purchase_user (maker) |
| `sales.user` | sales_user |
| `fa.user` | fa_user |
| `logistics.user` | logistics_user |
| `finance.user` | finance_user |
| `admin.user` | admin |
| `auditor.user` | auditor (read + audit export) |
| `dual.user` | purchase_user + approver_hod (cannot self-approve) |

Keycloak admin console (http://localhost:8080): `admin` / `admin`.

### 17.2 Client / machine credentials (local dev realm)

| Item | Value |
|---|---|
| OIDC login client id | `agfze-command-centre` |
| OIDC login client secret (token grant) | `agfze-local-dev-secret` |
| Admin-API service-account client id | `agfze-admin-api` |
| Admin-API client secret | `agfze-local-admin-api-secret` |
| Realm | `agfze` |
| Token endpoint | `http://localhost:8080/realms/agfze/protocol/openid-connect/token` |
| JWKS (backend uses internal host) | `http://keycloak:8080/realms/agfze/protocol/openid-connect/certs` |

### 17.3 Document categories the classifier assigns

`purchase`, `sales`, `fa`, `logistics`, `approval`, `follow_up`, `informational`, `exception` — with business stream `scrap` (and the FA line).

### 17.4 Rules to expect on the validation panel

`BR-01`…`BR-13` (traceability, reference presence, container agreement, mandatory packs, quantity tolerance, invoice-value tolerance, OBL gating, duplication links, …) plus `IV-01` (invoice dating), `SL-01` (cross-shipment contract coverage), `LG-01` (invoiced weight vs bill of lading). Governance thresholds `GOV-01` (bulk-approval ceiling), `GOV-02` (approval-overdue hours), `GOV-03` (exception ageing / shipment staleness).

### 17.5 Sample invoice key figures (for assertion)

| Field | Value |
|---|---|
| Batch | `TEST-I2626-01` |
| Invoice no | `ECT/INV/2026/0847` |
| Invoice date | 2026-08-28 |
| Net weight | 24.500 MT |
| Rate | 8,125.00 USD/MT |
| Invoice value | 199,062.50 USD |
| Container | `DEMU7781234` (ISO 6346 valid) |
| B/L | `MAEU7712345` |
| POL / POD | Jebel Ali (AEJEA) → Singapore (SGSIN) |

### 17.6 Seeded demo identifiers

Purchase/sales contract `DEMO-CT-2026-118` / `DEMO-SC-2026-441`; batches `DEMO-I2626-1` (24.500 MT), `DEMO-I2626-2` (31.250), `DEMO-I2626-3` (18.000, **no sales leg**), `DEMO-I2626-4` (27.750, **awaiting approval**); FA batch `DEMO-FA2626-1`; containers `DEMU7781234`/`DEMU7781235`; rate 8,125.00.

### 17.7 Example JSON payloads

**Generate a monthly report:**
```json
{ "scope": { "stream": "scrap" }, "range": "month", "month": "2026-08" }
```

**Approval decision (approve):**
```json
{ "decision": "approve", "reason": "Docs complete, weights and value verified against B/L and invoice." }
```

**Reject:**
```json
{ "decision": "reject", "reason": "B/L weight does not match invoiced weight; return to preparer." }
```

**Exception resolution (genuine fix):**
```json
{ "resolution": "corrected_quantity_to_match_bl", "note": "Invoiced weight corrected to 24.500 MT per B/L MAEU7712345." }
```

**Shipment status update:**
```json
{ "status": "arrived", "milestone": "discharged", "note": "Vessel berthed Singapore, discharge commenced", "occurred_on": "2026-09-11" }
```

**Post-delivery issue:**
```json
{ "type": "weight_discrepancy", "note": "Receiver reports 0.3 MT moisture loss on discharge." }
```

---

## 18. Troubleshooting — symptoms, causes, fixes

| Symptom | Likely cause | Fix |
|---|---|---|
| `make setup` fails pulling images | Docker not running / no network | Start Docker Desktop; `docker run hello-world`; retry |
| `docker compose` not found | Compose v2 missing | Install Docker Desktop (bundles Compose v2) |
| `make: command not found` (Windows) | Make not installed | Use Git Bash (ships make) or `choco install make` |
| Port already allocated (3000/8000/8080/5432/8025) | Another service on the port | Stop it (`lsof -i :PORT`), or stop local postgres/keycloak |
| `/health/ready` returns 503 | DB not ready yet / migrations running | Wait 30–60s; check `docker compose logs backend`; `make migrate` |
| Frontend can't reach API | Browser can't reach `localhost:8000` | Confirm `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1` in `frontend/.env`; rebuild frontend if changed |
| Sign-in redirect error / “issuer mismatch” | `KEYCLOAK_ISSUER` doesn't match token `iss` | Ensure issuer is `http://localhost:8080/realms/agfze` (browser-facing), not the `keycloak` host |
| Token request returns empty | Realm still importing / wrong secret | Wait ~30s after Keycloak start; use client secret `agfze-local-dev-secret` |
| Classification/extraction stuck in review / fails | No/invalid `GEMINI_API_KEY` | Add key to `backend/.env`, then `docker compose restart backend`. Manual entry still works. |
| Upload returns 415 | File type not in whitelist or spoofed extension | Use real PDF/DOCX/XLSX/CSV/JPG/PNG; the `.docx` fixtures are valid |
| Upload returns 413 | File > 25 MB | Use a smaller file (limit is enforced while streaming) |
| Approval button does nothing / error | You submitted it (maker-checker) | Approve with a **different** account, e.g. `hod.approver` |
| Jobs show “awaiting_manual_action” | SAP/DMS/tracker not configured | **Expected locally.** Open the job for the payload + manual instructions |
| Seeded logins missing | Realm didn't import fresh | Run `make realm-import` (recreates Keycloak so `realm-agfze.json` imports), then `make dev` |
| Want a completely clean slate | Volumes hold old data | `make clean` (removes containers, volumes, build artefacts), then `make setup` |
| Frontend tests can't find modules | `node_modules` missing | `cd frontend && npm install`, then `make test-frontend` |
| Keycloak changes not reflected | start-dev keeps H2 in container | `make realm-import` |

**Reporting a bug (the project's own template):** include what you did, what you expected, what happened, the request's **`X-Request-ID`**, the environment (`ENV=development`, local Docker), and whether the **audit trail** shows the action.

---

## 19. Definition of Done — your sign-off checklist

Tick each box. The platform is “working on your platform” when all are true.

**Environment**
- [ ] `docker --version`, `docker compose version`, `make --version`, `node --version` (v22) all OK
- [ ] `docker run hello-world` succeeds
- [ ] Ports 3000/8000/8080/8025/1025/5432 free

**Setup & startup**
- [ ] `make setup` completes and prints the seeded logins
- [ ] `make dev` brings up 5 services; `docker compose ps` shows them running/healthy
- [ ] http://localhost:3000 loads; http://localhost:8080 and http://localhost:8025 reachable

**Smoke**
- [ ] `GET /health` → 200; `GET /health/ready` → `{"database":"ok"}`
- [ ] Every response carries an `X-Request-ID`

**Automated tests**
- [ ] `make test-backend` → **721 passed, 0 failed** (or current count, 0 failed)
- [ ] `make test-frontend` → **349 passed across 34 files, 0 failed**
- [ ] `make lint`, `make format-check`, `make verify-sw` all pass

**End-to-end business flow (manual)**
- [ ] Sign in per role works; wrong password rejected
- [ ] Supplier invoice uploads → classified `purchase/scrap` → fields extracted with confidence scores
- [ ] Low-confidence / no-key path lands in human review and can be completed manually
- [ ] Field corrections require a reason and are stamped to the actor
- [ ] Reclassify works and re-extracts
- [ ] Confirm triggers deterministic batch matching (explained scores); new batch can be opened
- [ ] Rule failures open owned/aged/escalatable exceptions; genuine fixes resolve them
- [ ] Submit → ranked approval queue (age/value/risk) → HOD approves; AI summary shown once
- [ ] Reject with reason returns the deal to the preparer
- [ ] **Self-approval refused** even for `dual.user`
- [ ] Bulk approve respects the GOV-01 ceiling
- [ ] Three integration jobs created; unconfigured → `awaiting_manual_action` with payload (honest, no fake success)
- [ ] Shipment board: milestones, hand update, refresh, post-delivery issue, staleness sweep/exception
- [ ] Sales leg + DOCX draft generation; FA minimal-field behaviour

**Security / negative**
- [ ] Protected route without token → 401; forged token → 401
- [ ] Desk hitting admin route → 403
- [ ] Spoofed `.pdf` (plain text) → 415; >25 MB → 413; empty → 400
- [ ] Rule-threshold change without reason rejected; with reason audited
- [ ] Security headers present; offline = read-only (no mutations cached/queued)

**Notifications, reports, audit**
- [ ] Triggered email appears in MailHog (HTML + plaintext); in-app bell lists it; mark-all-read works
- [ ] Report generates (PDF/XLSX), figures are drill-through/reproducible, page states “not sent to anyone”
- [ ] Audit trail shows your full action history with reasons; CSV export downloads

When every box is ticked, the AGFZE Command Centre is verified working end-to-end on your platform.

---

## 20. Appendix A — Ready-made test fixtures included with this guide

Alongside this file you have a `test-fixtures/` folder with two valid, upload-ready documents (generated by `make_fixtures.py`, also included):

| File | Type | Purpose in the test |
|---|---|---|
| `test-fixtures/sample-supplier-invoice.docx` | Commercial invoice | Positive intake test; classifies as **purchase/scrap**; batch `TEST-I2626-01`; 24.500 MT; USD 199,062.50; container `DEMU7781234`; B/L `MAEU7712345` |
| `test-fixtures/sample-bill-of-lading.docx` | Bill of lading | Logistics intake; classifies as **logistics**; matches the same batch/container; supplies the B/L that gates shipment and feeds the `LG-01` weight rule |

**How to use them:** in Phase 9 (Step 9.2) choose `sample-supplier-invoice.docx` in the Inbox → Upload dialog; optionally upload `sample-bill-of-lading.docx` next and match it to the same batch.

**To regenerate them** (e.g. to change figures):

```bash
python3 make_fixtures.py
```

**Tip:** to test the PDF path specifically, open either `.docx` in Microsoft Word or LibreOffice Writer and **File → Save As → PDF**, then upload the PDF — the pipeline reads PDFs text-layer-first via PyMuPDF.

---

*Prepared as a testing playbook for the AGFZE Command Centre (github.com/ram-supervity/AGFZE). Every command, credential, and figure above is the local-development value shipped by the repository; local secrets are throwaway and must never be used in a deployed environment.*
