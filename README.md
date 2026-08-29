# AGFZE Command Centre

Internal trade operations platform for AGFZE. This repository holds **Step 1: the foundation**,
**Step 2: email and document intake**, **Step 3: purchase transactions, matching and the validation
rule engine**, **Step 4: exceptions and approvals**, **Step 5: sales transactions and draft document
generation**, **Step 6: FA transactions and shipment tracking**, **Step 7: the tracker / SAP / DMS
integration hub**, **Step 8: dashboard, analytics and automated reporting**, **Step 9: admin
configuration, the audit explorer, settings and in-app notifications** and **Step 10: the installable
app, offline resilience, and email and push delivery** and **Step 11: security hardening, testing
and deployment** — a runnable application that
signs staff in, watches an approved shared mailbox, classifies what arrives, reads structured fields
off the attachments with a real multimodal model, matches the confirmed result to the batch it
belongs to, checks it against real configurable business rules, routes what fails to an owned queue,
puts what passes in front of an approver, follows the cargo to the port, posts the approved deal
downstream, measures the whole of it, and now lets real people change the configuration behind all
of that, read everything it has ever recorded, be told when something needs them — in the app, by
email and by a push to the phone in their pocket — and keep reading what they had open when the
connection drops — now hardened, tested end to end, and deployable.

## What Step 11 delivers

The last step before this platform could plausibly be put in front of staff handling real money. It
adds one small feature and otherwise adds nothing at all: it verifies, hardens, tests and ships
what the ten steps before it built.

### The one genuine feature gap, filled

**IV-01, invoice dating.** A requirement named in this platform's original discovery material that
belonged to none of the ten feature steps. An invoice dated more than a configured window in the
past — three months, seeded — is flagged, as is one dated in the future, and an India-territory
transaction carries an advisory note about local payment-term interest rules.

Three things about it are deliberate and are each enforced by a test:

- **It flags. It never blocks.** The discovery material proposes rejecting a future-dated invoice
  outright, and says in the same breath that the business has not confirmed the tolerance or the
  approval matrix behind it. A hard failure on an unconfirmed policy would stop real deals on a
  rule AGFZE never made. Both outcomes are `acknowledgeable`, so the preparing desk clears them on
  their own record with a stated reason — the same tier BR-06's invoice amount uses. Even the
  *unconfigured* branch is a flag, so an administrator switching the row off cannot stop a desk
  from working.
- **Its threshold is a row, not a literal.** `IV-01 / invoice_date_window`, editable on the
  `/admin/rules` screen Step 9 built, with no change to that screen.
- **It cost the engine nothing.** One evaluator module, one `@register`, one import at the foot of
  `evaluators.py`. No change to the orchestrator, the context, the persistence or the exception
  hook — which is the fourth time that claim has been made and the first time there is a test that
  would fail if it stopped being true.

The advisory computes no liability figure and never will on the data this platform holds: the
Indian rule turns on the counterparty's registration status and on a payment date that lives in
SAP. The note tells the desk to look; it does not pretend to have looked.

### Security hardening

- **A Content-Security-Policy, new in this step.** No prior step shipped one. Scripts are allowed
  from this origin with a per-request nonce and nothing else — no `unsafe-inline`, no
  `unsafe-eval` — and connections only to this origin, the API and the Keycloak issuer. Not one
  external provider appears in it, because every call to Graph, Gemini, SAP, DMS, a carrier or an
  SMTP relay is server-side and always has been. A test asserts each of those hosts is absent.
  The API serves its own, stricter policy: `default-src 'none'`, because it returns JSON.

  Two things about it were found by **serving the built application and reading the response**
  rather than by reasoning about the configuration, and both would have shipped a broken sign-in
  page otherwise. A statically prerendered page's HTML is written at build time and cannot carry a
  per-request nonce, so the root layout now forces dynamic rendering — `/signin` was static, and
  every one of its 23 script tags was being refused. And `withAuth` returns early, without calling
  the middleware it wraps, for the sign-in page and for any request it redirects, so the policy is
  applied by this platform's own middleware with `getToken` doing the session check `withAuth` was
  doing internally anyway. Both are now asserted by tests.
- **Rate limiting, finished rather than switched on.** `slowapi` has been a boolean with one
  default limit behind it since Step 1. This step gives real values to the four categories the
  specification names — authentication-adjacent, upload, every AI-calling endpoint, and bulk
  approval — plus the unauthenticated Graph webhook, matched on method and path and evaluated
  before the default ceiling. A test drives a category to its limit and asserts the refusal is a
  real 429 with a real envelope. The production profile now refuses to start if the switch has
  been turned back off or any limit is blank.
- **The RBAC matrix, run in full.** `tests/test_rbac_matrix.py` names every route the router tree
  carries and, for each one, signs in as all eight platform roles: every authorised role must get
  past the gate, and every unauthorised one must receive a real 403 from the dependency layer.
  Coverage is enforced rather than intended — the matrix is compared against the live application's
  routes in both directions, so an endpoint added later cannot escape the file by not being written
  into it. **One genuine hole was found and fixed**: `POST /transactions/{id}/acknowledge-tolerance`
  was the only preparing-user write on that router that did not check leg ownership, so a sales user
  could acknowledge a discrepancy on a purchase-only transaction. It now applies `_may_write` like
  its three siblings.
- **The absence checks.** Some of this platform's most important properties are things that must
  not exist, and each is now searched for in the real tree rather than assumed: no code path can
  send a generated sales document to a counterparty (the only module that can reach an SMTP relay
  is the notification service, and it cannot attach a file); nothing queues a mutating request for
  later replay; no request schema anywhere carries `decided_by`, `decided_at` or any other
  server-authoritative field; and no admin screen exists for the three configuration areas Step 9
  excluded on purpose.
- **Every credential audited.** All eleven, each declared with an empty default, none in the
  OpenAPI document, none reachable from a client component, none passed to a log call — the last
  checked by walking the AST of every module under `app/`. A test sets every one of them to a
  recognisable value and reads the endpoints most likely to leak it.
- **HSTS and the hardening headers** on every API response, including a 401 and a 429 — a refusal
  is a response like any other and must not be the one that arrives unhardened. HSTS is emitted
  only over HTTPS and only in production.

### Testing

- **The full cumulative suite passes in one pass**, backend and frontend. Five tests that had
  quietly broken were found and fixed, all of them dialect or interpreter artefacts on the
  documented SQLite fallback rather than defects in shipped code: two schedule assertions comparing
  a naive stored timestamp against an aware one, a test helper binding a UUID as a string, and a
  timestamp parsed with `fromisoformat` on an interpreter that predates its `Z` support. One real
  intake defect surfaced beside them: some libmagic builds report a `.docx` as
  `application/octet-stream`, and the container check now confirms the ZIP local-file signature in
  the bytes themselves rather than trusting which libmagic build a machine happens to have.
- **Nine end-to-end scenarios**, in `tests/test_end_to_end.py` and one in the frontend suite: a
  purchase deal from an email arriving to `Committed`; a sales deal on the same transaction through
  draft generation to `Committed`; an FA deal proving the engine is generic; a hard failure through
  exception, all three notification channels and resolution; reject-and-resubmit proving
  `Validation Pending` is genuinely re-enterable; shipment staleness opened by a direct call and
  closed by a person; an unconfigured SAP and DMS reaching `Committed` through
  `awaiting_manual_action`; a full audit reconstruction from a committed batch number back to the
  email it arrived on; and offline governance, where a mutating action is refused and never queued.
- **The three architectural promises, as tests that would fail if they stopped being true.** The
  orchestrator names no rule (checked against the executable source, docstrings stripped, so a
  prose explanation does not pass for a branch), and a rule registered at runtime is evaluated and
  persisted with no dispatch change at all. Step 4's `open_case` is called directly by the shipment
  sweep, and the case it opens carries no `rule_id` — nothing fabricates a `rule_evaluations` row to
  reuse the hard-fail hook. And each of Step 9's five trigger functions is read individually and
  must mention no channel, with `dispatch_deliveries` called from exactly one place in the codebase.

### CI/CD

`.github/workflows/ci.yml` — blocking, on every push and pull request. Backend: ruff check, ruff
format check, the full suite against real PostgreSQL, an Alembic dry-run that migrates a disposable
database up, all the way back down to base and up again (a downgrade nobody exercises is a
downgrade that does not work), then a multi-stage image build, then a check that the built image
genuinely refuses to start with an unsafe production configuration. Frontend: lint, format, types,
the full suite, a build, **verification of the service-worker precache manifest against that
build's own output**, then the image. A `gate` job with an explicit result test is the single
required check, so a skipped or cancelled job is a failure rather than a silent pass.

`release.yml` deploys both services **independently** on a tag, each behind its own no-traffic
revision that must answer its own probe before any request reaches it. `rollback.yml` reverts one
service's traffic split to its previous revision without touching the other — and says plainly that
it has not reverted the database schema, because that is a decision for a person.

### Production

`infra/production/` is Terraform, not a runbook: two Cloud Run services, a regional Cloud SQL
instance with **no public address**, customer-managed encryption keys, automated backups and
point-in-time recovery, Secret Manager holding every credential, Cloud Armor in front of both
services, TLS 1.2 at the edge with plain HTTP redirecting, and the Step 1 probes wired to the
platform's own health checking.

The backend keeps one instance warm and CPU enabled between requests, which is not a performance
setting: the integration retry sweep and the daily and monthly report schedules run in-process on
that loop, and a service scaling to zero would mean none of them ever runs.

`infra/production/verify-production.sh` reads all of it back out of the live project afterwards.
Terraform proves what was applied once; this proves what is true now — including that a backup has
actually completed, that the sweep has actually reported starting, and that the database password
is no longer the placeholder Terraform created the secret with. It exits non-zero on any failure,
and it is meant to be run before a go-live sign-off and on a schedule thereafter.

### The honest handoff

**[docs/KNOWN-GAPS.md](docs/KNOWN-GAPS.md)** — thirteen items, each one a place where this platform is
making a reasonable assumption on AGFZE's behalf because the business had not confirmed the real
answer. For each: what the platform does today, what happens if the default is wrong, and who has to
decide. It is a pre-go-live checklist, not a backlog.

## What Step 11 deliberately does not include

- **No new roles, no new permission logic and no new screens.** The role boundaries are the ones
  Steps 1-10 established; this step verified them exhaustively and fixed the one place where the
  server was more permissive than the design.
- **No enforcement beyond IV-01's flag.** No India MSME interest calculation, no rejection of a
  future-dated invoice, no approval matrix for a backdated one. Each of those is a business rule
  nobody has confirmed, and each is written down in the known-gaps document instead.
- **Segregation of duties on approvals is now enforced**, which is the one item in this list that
  has changed. An account holding both a preparing role and the approver role can no longer approve
  a transaction it submitted itself: the decision is refused with a 409 (`segregation_of_duties`)
  before any state changes, and the transaction stays exactly where it was, with no integration job
  behind it. This implements BRD 9.1's maker-checker control. A rejection or a request for changes
  by the submitter is deliberately still allowed - returning a transaction to its own desk commits
  nothing - and a transaction with no recorded submitter is not caught, because there is no maker to
  check the checker against. The seeded realm still ships the dual-roled account; it is now what the
  refusal is tested against rather than what it permits. What remains a business decision, and is
  named in the gaps document, is what a desk does when its only eligible approver *is* the
  submitter: the platform ships no override for that, deliberately.
- **No admin screen for the three configuration areas Step 9 excluded.** The tracker/SAP/DMS
  endpoint targets, the rule-to-exception-category mapping and the report templates all stay
  deployment-driven, and a test now fails if a screen for any of them appears.
- **No second AI provider.** The Vertex extension point still fails honestly rather than pretending
  to be a fallback.
- **No shared rate-limit counter store by default.** The counters are in-process, which is honest
  and per-instance; pointing `RATE_LIMIT_STORAGE_URI` at Redis is one environment variable and one
  more managed service, and that is AGFZE's call rather than this step's.

## What Step 10 delivers

Step 9 built one notification service and wired it into five trigger points, and said plainly that
in-app was the only channel that existed. This step gives that same function two more delivery
channels and makes the application installable — and the architectural claim it rests on is worth
stating first.

- **Two new channels, added inside one function, with five call sites untouched.** Email and push
  reach every one of Step 9's triggers — an exception opened, an approval requested, an approval
  decided, an integration job needing a person, a scheduled report finishing — through the internals
  of `notification_service.notify` and through nothing else. Not one line changed in
  `governance/hooks.py`, `governance/approval_service.py`, `integration/integration_service.py` or
  `analytics/schedule.py`. A test reads all four and fails if any of them so much as mentions a
  channel, because five copies of "how is this delivered" is five answers that drift the first time
  one of them is edited.
- **Three channels, genuinely independent.** In-app is created for every notification and every
  user, always — it is the platform's durable record, not an option. Email is additional and is the
  one thing `users.notification_channel` governs. **Push is gated solely on whether the user has an
  active `PushSubscription`** — a browser permission, never a settings-page flag — so a user on the
  `in_app` default who granted permission receives push, and a user set to `email` who never granted
  it does not. A person can be on all three at once, and the settings page presents them as what
  they are: a statement, a toggle, and a browser-permission control.
- **Real email.** Jinja2 templates — one per notification type, each extending a shared layout
  carrying the wordmark, the ink-navy/copper palette and the platform's own AI disclaimer where the
  notification concerns AI-derived content — rendered into a genuine multipart message with an HTML
  part and a real plaintext part, and handed to an authenticated, STARTTLS relay. Three attempts with
  backoff; after that the failure is logged **and written to the audit trail**, so it is visible at
  `/admin/audit` rather than only in a log stream nobody on this platform can open.
- **A failed delivery cannot touch the business event.** The transaction, exception or approval has
  already happened and has already been recorded. Every dispatch path is wrapped, and a test proves
  it on a real approval decision: with the relay refusing every attempt and the push library raising
  something nobody anticipated, the decision still stands and the in-app notification still exists.
- **Real push.** VAPID keys, `pywebpush`, and a genuine subscription lifecycle: upsert on
  (user, endpoint) so a browser that re-subscribes updates its keys instead of collecting a second
  row and a second identical notification. A `410 Gone` or `404` from a push service means that
  browser is gone, so the row is **deleted rather than retried** — a test fires three notifications
  at a dead endpoint and asserts exactly one attempt was made.
- **Installable, with icons that are actually drawn.** A real manifest, and an icon set rasterised
  from the same brand mark the header has drawn since Step 1 — 192 and 512 for Chromium, a maskable
  512 for Android's adaptive icons, a 180 opaque one for an iOS home screen, a 72 badge for the
  Android status bar. `make icons` regenerates them from `scripts/generate-icons.mjs`; the tests read
  each PNG's own IHDR chunk rather than trusting its filename.
- **An install button that is honest on both platforms.** Chromium fires `beforeinstallprompt`, so
  the header button opens the browser's native prompt. iOS Safari never fires it and no API can
  install anything there, so the same button opens two-step Share-sheet instructions instead of
  pretending. Where neither applies — already installed, or a browser with no install concept — the
  button is absent rather than inert.
- **A service worker with the caching strategy written out.** Cache-first for the precached shell and
  static build output, stale-while-revalidate for lists and summaries, network-first for
  single-record detail with a cache fallback **only on a genuine network failure**, the precached
  `/offline` route for a navigation with neither, and **network-only for every mutating request**.
  Cached responses expire after fifteen minutes and every cache is keyed to the deployed build hash,
  so a release invalidates the last one by name.
- **Offline that never lies.** A persistent banner says what is on screen and how old it is —
  stamped by the worker, not estimated — and a mutating action attempted offline is refused before
  it is sent, with a message saying nothing was saved. `/offline` lists what is still readable and
  what needs a connection, and says outright that nothing is queued.
- **Sign-out that leaves nothing behind.** The existing flow now cancels the browser's push
  subscription (browser-side and server-side) and deletes **every** cache on the origin — not only
  the ones this build named — before the session closes. A cached screen can name a counterparty and
  quote a price, and on a shared or lost device the right amount of that left behind is none.

## What Step 10 deliberately does not include

**No client-side queue for a mutating request, under any framing.** Not background sync, not a
retry buffer, not a "draft" that submits itself later. This is a governance boundary this platform
has held since its first description, not an unfinished feature: an approval decision replayed from
somebody's pocket three hours later, against a record that has since moved on, is a failure of
governance rather than a convenience. The service worker contains no `sync` handler and no
IndexedDB, and a test asserts that against the shipped `public/sw.js`.

**No new notification trigger point.** This step adds channels to the five triggers Step 9
established and invents none. A missing mandatory document is already covered by the generic
exception trigger, because that condition opens an `ExceptionCase` in exactly that category.

**No service worker in development.** `npm run dev` never registers one, and the app actively
unregisters anything a previous production build left on the origin — see the section below.

**No in-app SMS, and no per-notification-type channel matrix.** Nothing in this platform's material
asks for either, and a preferences grid nobody asked for is a grid somebody has to maintain.

## What Step 9 delivers

Two things this platform has never had. Every tolerance, document checklist and role assignment has
only ever been set by editing a migration, and every meaningful event since the first day has been
recorded to a log nobody could look at. This step turns both into real capabilities, and gives the
platform its first voice.

- **Reason-required configuration editing, finally enforced.** `RuleConfiguration` and
  `DocumentTypeSchema` have carried a mandatory `change_reason` since the migrations that created
  them, in Steps 3 and 2. This is where that requirement gets an endpoint and a screen behind it,
  not where it is introduced. The reason is validated in the request schema, so a request without
  one is refused before a handler runs, and the audit event is written in the same database
  transaction as the change — the new value and the record of it land together or not at all.
- **One screen for rows seeded by three different steps, with no special-casing.** The purchase
  tolerances from Step 3, the sales module's own `SL-01` from Step 5 and the FA-scoped defaults
  from Step 6 all reach `/admin/rules` through one query and edit through one dialog. Invoice and
  contract schemas from Step 2, the bill of lading from Step 5 and `fa_document` from Step 6 do the
  same at `/admin/document-types`. That neither screen contains a branch on which step created a
  row is the concrete proof both tables were genuinely built generically.
- **A role override that cannot half-apply.** `PATCH /admin/users` calls the Keycloak Admin API
  synchronously and commits nothing locally until that call has come back confirmed. A refusal, a
  timeout or an unreachable provider leaves this platform's own record byte-for-byte as it was and
  returns a clear error — a local role Keycloak never granted is a claim the next sign-in would
  silently overwrite.
- **A third machine credential, kept separate on purpose.** The Admin REST API is reached with its
  own confidential client holding one grant, `realm-management: manage-users`. It is not the OIDC
  client staff sign in through and not the Graph app registration that reads the mailbox — three
  capabilities, three credentials, three blast radii, the same discipline Step 2 established. It is
  read from configuration only, never logged and never returned by any endpoint, and the local dev
  realm seeds a working one so the override is genuinely testable against a real Keycloak.
- **The audit trail, readable at last.** `/admin/audit` filters the whole accumulated history by
  date range, event type, actor and entity reference, open to Admin and Auditor. The event-type
  filter is a `SELECT DISTINCT` over what the data actually holds rather than a list written by
  hand — ten steps have contributed to that vocabulary and an eleventh will contribute more. The
  CSV export **streams**, row by row from a server-side cursor, because this table has been filling
  since the very first step and has no upper bound.
- **Metadata discipline verified, not assumed.** A test asserts across a representative sample of
  call sites from every prior step that no audit payload carries document text, an AI prompt or a
  completion, and the read layer redacts by key and truncates by length on the way out as a
  backstop. The explorer is a governance screen and never a viewer for a source document.
- **`PATCH /users/me/preferences`, completed.** Declared in Step 1 and deliberately left unbuilt
  until there was a page to pair it with. Self-only structurally: the row written is the one
  resolved from the verified token, and the schema has no field for an account id, a role, an email
  or an active flag, so there is nothing to ignore rather than something to filter out.
- **One notification service, and one only.** `notification_service.notify` is the single writer of
  a `Notification` row — analogous in spirit to the audit helper — and every trigger point calls it:
  a new exception (broadcast to every active holder of the case's owner role, because a case records
  a role and not a person), a new approval task (its named assignee, or the approving desk), an
  approval decision (the submitter, resolved from the audit trail, **one notification per
  transaction** including inside a bulk decision), an integration job that failed or is waiting on a
  person, and a scheduled report. A test reads every module in `app/` to prove nothing else
  constructs the model.
- **The header bell, deferred explicitly since Step 1.** Real unread count, real quick-preview
  dropdown, real deep links, and a `/notifications` centre behind it — every read and write scoped
  to the caller in the query, never by which link the UI happened to draw.

## What Step 9 deliberately does not include

**No email and no push delivery** — that was Step 10, and it has since been built. Step 9 shipped
`Notification` with **no** `email_sent_at` and no `push_sent_at`, on the grounds that a nullable
timestamp for a delivery that could not happen would read as a channel merely switched off; both
columns arrived in Step 10's migration with the code that writes them, which is exactly how it was
meant to go. The settings page's "coming soon" email and push controls are likewise now real.

**No admin screen for the tracker, SAP or DMS endpoints.** Step 7 made those environment-variable
configuration deliberately. They are infrastructure: changing where an approved transaction is
posted should require a deployment and a review, not a form.

**No admin screen for the rule-to-exception-category mapping.** It decides which desk owns which
failure, has never been part of this platform's page catalog, and stays seed/migration-driven.

**No admin screen for report templates** — explicitly deferred by Step 8 itself, and this step does
not quietly pick it up.

**No global command-palette search.** It was never named in any step's scope, and the fact that
every module now exists does not retroactively authorise building one.

## What Step 8 delivers

Every step from the first onwards was told not to put a number on the dashboard, and every one of
them deferred to this one. This step honours all of those deferrals at once.

- **Real aggregates over the governed tables, and nothing else.** Every figure on the Dashboard,
  the Analytics page and every generated report is a grouped count or a duration computed from
  `trade_transactions`, `exception_cases`, `approval_tasks`, `extracted_fields`, `integration_jobs`
  and `shipments` at the moment it is asked for. There is no rollup table, no nightly total and no
  snapshot anywhere in this step — a stored aggregate is a figure that can disagree with the
  transaction of record.
- **Role scoping in the `WHERE` clause, not in the markup.** `DashboardScope` is derived from the
  stream-visibility map Step 3 established and the exception matrix Step 4 established, and it is
  applied before every `GROUP BY`. A Logistics User's exception tile is not a full-platform count
  with the Finance rows painted out; it is a count that never saw them. An account holding no
  recognised platform role reaches an honest set of zeros.
- **Two KPI definitions written out honestly, because the governing material names them without
  defining them.** *Extraction accuracy* is computed and labelled everywhere as a **non-override
  rate** — the share of extracted fields nobody corrected — because this platform holds no ground
  truth for what a document said and no verified-correctness measure is computable from it. The
  *automation percentage* is the share of approved transactions against which **no exception case
  was ever opened**, resolved or not.
- **The integration failure count and the awaiting-a-person count, still apart.** Two figures, two
  tiles, two drill-through destinations, in the payload and on every screen and report. Step 7 built
  that distinction; nothing here collapses it.
- **A dashboard where nothing is a dead end.** Every tile, every arc of the status ring, every bar
  and every legend row carries the filters that reproduce it and opens the queue behind it.
- **Real PDF and XLSX reports** rendered from live data by PyMuPDF and openpyxl, each carrying a
  unique generation reference printed on every page, resolvable back to the exact parameters and to
  the audit row that recorded the generation. Every generation writes a new `Report`; none is ever
  overwritten.
- **Report structure as configuration.** Which sections a report carries, in what order, and which
  figures go in each, are declared as data in `report_templates.py`. Neither renderer knows what a
  section means. The screen to edit that configuration arrives with the other admin screens; until
  then a template change is a seed-data change, exactly as `RuleConfiguration` already is.
- **Scheduled daily and monthly generation riding Step 7's existing sweep.** No second scheduler and
  no second job mechanism: the periodic loop is already awake every minute and is asked whether
  anything is due on the way past, and ad-hoc generation runs through the same `BackgroundJob`
  service and the same `GET /jobs/{job_id}/status` endpoint Step 1 established.
- **One AI paragraph, on the monthly report, that cannot break anything.** It is requested after
  every deterministic figure has been computed. A failure marks the section unavailable and the
  report still generates complete and correct — proved by a test, and visible in local development,
  where no Gemini key is configured and the monthly report generates anyway.

## What Step 8 deliberately does not include

**No distribution of any kind.** This platform cannot send an email or a push notification until
Step 10, so no report is sent to anybody, no `Report` row has a recipient column, and every
generated document, every audit entry and every API response says plainly that it was generated and
stored and nothing more.

**No admin screen for report templates or distribution rules** — that is Step 9. The report engine
is built against a configuration structure regardless, so that screen edits data rather than
requiring the renderers to change.

**No new business rule, exception category or lifecycle state.** This step is a read, aggregate and
report layer: nothing in `app/services/analytics/` writes to or alters a `TradeTransaction`, an
`ExceptionCase`, an `ApprovalTask`, a `Shipment` or an `IntegrationJob`. The only rows it creates
are the `Report` it produced, the `BackgroundJob` that tracked the request and the `AuditEvent`
that recorded it.

**No `closed` tile.** The status is declared in the vocabulary and no code path reaches it, so a
tile for it would be a permanent, meaningless zero rather than an informative one.

## What Step 6 delivers

Two halves, and they are deliberately unalike in weight.

**AGFZE's second business line, added almost entirely through configuration.**

- **`FaLeg`, attaching to `TradeTransaction` through its own one-to-one foreign key** — the third
  leg to do so, and the third time the parent table was not altered to make room for one.
- **A minimal `fa_document` schema**: seven fields, exactly the ones AGFZE's own material names,
  and not an eighth. AGFZE's material states that FA's fields, document types and tolerances are
  not finalised and instructs against inventing them, so nothing here fills in what looks like a
  gap. There is no FA document-type vocabulary, no FA mandatory-document list and no FA business
  rule anywhere in this codebase.
- **FA-scoped rule configurations**, seeded beside the unscoped platform defaults rather than
  replacing them. Each currently carries the same figure as the default it mirrors, because no FA
  figure has been agreed — but it is a separately addressable row, so agreeing one later is a row
  change rather than a release.
- **Not one FA-specific evaluator.** BR-02, BR-04, BR-05, BR-06 and BR-13 judge an FA transaction
  through the same registered functions they judge a purchase one with. What changed to make that
  work is *where they read from* — a leg is asked for a concept rather than a named column, and the
  commercial figures come from whichever document type the stream carries — not what they decide.
- **An `ExceptionCase` owner decided by the leg that is present**, so an FA failure routed through
  a mapping row that says `purchase_user` still lands on the FA desk. Nothing in that resolution
  names a stream; it inspects the legs.
- **An FA Transaction Workspace** reusing the Purchase workspace component for component, plus one
  genuinely new panel: **Additional FA Fields**, rendered entirely from the configured
  `DocumentTypeSchema`. There is not one FA field name in that component, and a test reads its
  source to keep it that way — because a panel with a hardcoded list would turn the openness AGFZE
  asked for into a release-blocking dependency the first time somebody agreed a new field.

**Container and shipment tracking, which is genuinely new territory.**

- **`Container`, `Shipment`, `BillOfLading` and `ShipmentIssue`.** Containers are created as a side
  effect of the matching that already happens, the moment a document quoting one is tied to a batch.
- **`BR-03`, real at last.** It hard-fails on one physical container appearing on two unrelated
  transactions, and deliberately says nothing at all about a batch loaded into several containers —
  which is ordinary loading, not a discrepancy.
- **`BR-07`, upgraded to the entity it always wanted.** Submission now waits on
  `BillOfLading.is_original_received` — a statement about a piece of paper on somebody's desk —
  rather than on the classified type of whatever file happens to be attached. The document-type
  distinction remains as the supporting signal for a transaction whose shipment has not been opened.
- **Real tracking orchestration, and an adapter registry that is honestly empty.** No carrier's
  tracking API is specified anywhere in this platform's material, so **no concrete carrier adapter
  ships** and none has been invented. What ships is the seam, orchestration that handles an empty
  registry correctly, and a scheduled sweep every six hours.
- **A manual path that is the primary path, not a fallback.** A shipment a person keeps current and
  one a carrier keeps current are the same row, with the same columns, written through the same
  function, subject to the same plausibility check and the same audit trail, and rendered by the
  same screen. The only difference recorded anywhere is a provenance caption.
- **A plausibility check that flags and never blocks.** An ETA that jumps further forward than a
  schedule realistically moves is saved, marked for review and audited as such — because the most
  likely reason an ETA jumps is that the earlier one was wrong, and refusing the correction would
  leave the wrong date in place.
- **Staleness into the queue that already exists.** A shipment nobody has established anything about
  for 48 configurable hours, or whose tracking has failed repeatedly, opens a real Logistics-owned
  `ExceptionCase` — by calling the standalone case-creation function directly, never by
  manufacturing a rule evaluation that never ran.
- **A Shipment Dashboard and Shipment Detail screen**, and real linked-shipment status on the
  Transactions List and on both the Purchase and Sales workspaces.
- **A milestone timeline derived from `AuditEvent`.** There is no shipment-history table and there
  is not going to be one: a second store of the same facts is a second thing to keep in step, with
  the certainty that one day the two would disagree and nobody could say which was right.

## What Step 6 deliberately does not include

**No concrete integration against any named shipping carrier.** Access is negotiated carrier by
carrier, none of those negotiations has concluded, and no carrier's API is specified anywhere in
this platform's material. A client written against a guess would fail on first contact with the
real thing and would meanwhile make the platform look as though it had an integration it does not
have. A test reads `adapters.py` and fails if a carrier is named in it.

**No FA business content of any kind.** No FA document type, no mandatory-document list, no FA
tolerance and no FA rule. Where an FA-scoped threshold was seeded it deliberately equals the
platform default and says so in its own change reason.

**No Excel or SharePoint shipping-tracker synchronisation** — that is Step 7, and `BR-09` still
reports itself unevaluable because there is no tracker to synchronise with.

**No new dashboard metric.** The Step 1 dashboard is untouched, even though real shipment data now
exists, for the same reason it was untouched in Steps 3, 4 and 5: a real number belongs on Step 8's
aggregation layer.

## What Step 3 delivers

- **`TradeTransaction`, the shared parent record for one physical batch**, with `PurchaseLeg`
  hanging off it one-to-one. The sales and FA legs that Steps 5 and 6 introduce attach the same
  way; this table never has to be altered to accommodate them.
- **Real matching at the seam Step 2 left open.** Confirming an extraction hands the document to
  the matching service, which checks for a duplicate on the stored content hash and then on
  extracted-content similarity, matches on a quoted batch number where there is one, and otherwise
  scores open transactions on contract reference, supplier name, commodity and quantity through
  rapidfuzz. At or above the configured thresholds it links; in the suggestion band it puts the
  candidate to a person **before anything is created**; below the floor it opens a new batch.
- **Supersession rather than duplication**: a final invoice arriving against a batch whose leg is
  still provisional updates that leg in place. The provisional document and everything extracted
  from it stay exactly where they are, so both states remain inspectable, and the audit entry is
  what records that a supersession happened.
- **A generically-architected rule engine.** One orchestrator, one registry keyed by rule id, and
  no knowledge of any individual rule: it loads the transaction, reads which legs it actually has,
  calls the evaluators those legs make relevant, and writes a fresh `RuleEvaluation` row per
  outcome. All thirteen rules are registered. BR-02, BR-04, BR-05, BR-06 and BR-13 are implemented
  for real; the rest are clean placeholders that report themselves unevaluated and write nothing.
- **Not one threshold in application code.** Every tolerance, limit and match threshold is a row in
  `rule_configurations`, seeded by migration with a mandatory change reason, resolved per
  transaction with the narrowest matching scope winning. A rule with no active configuration fails
  loudly rather than passing quietly.
- **BR-06 as three different checks, not one tolerance**: the invoice amount on a three-tier
  rounding check (auto-pass, self-approvable with a logged reason, hard failure), quantity on a
  plain percentage tolerance with no self-approval path at all, and price on an exact match,
  because a price difference is a different deal rather than rounding noise.
- **An append-only evaluation history.** Re-validating never updates or deletes a row; it inserts
  new ones. The most recent row per (transaction, rule, check) is the current result, and an
  acknowledgement is carried forward only while the figures behind it have not moved.
- **Concurrency-safe batch numbering** (`I` + financial-year suffix + company code + sequence),
  allocated by an atomic counter increment rather than a read-max-then-add-one, and stepped past
  any number a supplier's own reference already holds.
- **The transactions list, the manual registration flow and the purchase workspace**: a filterable,
  sortable, paginated table; a focused multi-step registration for a deal with no email trigger;
  and a two-column workspace pairing the Step 2 page viewer with collapsible Extraction, Matching,
  Validation and History panels, a sticky save-and-submit bar, and a submit action disabled with
  the specific rule still standing in its way.
- **Both deferred foreign keys promoted.** `background_jobs.transaction_id` and
  `documents.transaction_id` are real constraints from this step's migration onwards.

## What Step 2 delivers

- **Mailbox capture through Microsoft Graph**, on two paths that converge on one idempotent
  ingestion function: a change-notification subscription renewed ahead of its ~3 day expiry, and a
  delta-query poll every two minutes as the fallback. Deduplication is on the provider's own
  message id, so a message delivered by both paths becomes exactly one request.
- **Manual portal upload** with the same admission rules as a mailbox attachment: a magic-byte
  whitelist (PDF, DOCX, XLSX/XLS, CSV, JPEG, PNG) and a 25 MB ceiling applied while the body is
  still streaming.
- **Request classification**: one Gemini call per inbound request assigns one of eight business
  categories with a confidence score, a rationale and, where the mail makes it clear, the business
  stream. Anything below the configured threshold is flagged for a person and is correctable with
  a recorded reason.
- **Document classification and schema-driven extraction**: a digital PDF goes through PyMuPDF's
  text layer, a scan or a photograph is rasterised and read multimodally, Word is parsed for
  paragraphs and tables, and a spreadsheet tracker is parsed through a header-detecting reader that
  tolerates a title banner above the real header. Multi-page documents are read a window at a time
  and consolidated, preferring the highest-confidence reading and flagging a genuine disagreement
  rather than silently picking one.
- **`DocumentTypeSchema`**, the configuration table that decides what gets extracted. No field list
  is written in application code: adding a field or a document type is a row change. Seeded with
  real invoice and contract schemas and with the India and China document-pack checklists.
- **A real review surface**: an inbox queue with confidence-tinted category badges, a request
  detail view with the original message and its attachments, a drag-and-drop upload page with
  per-file progress, a searchable document index, and a two-column document review screen showing
  each extracted field beside the page it was read from, bordered in its confidence colour.
- **Override retention everywhere**: correcting a category, a field value or a document type never
  discards what the model originally said. The original value, its original confidence, the reason
  given, who gave it and when all stay on the record, and every one of those actions writes to the
  Step 1 audit trail.

## What Step 1 delivers

- A four-service local stack (`docker compose`): PostgreSQL 15, Keycloak 26, the FastAPI backend and
  the Next.js frontend, on one bridge network, with the database schema applied automatically when
  the backend container starts.
- A Keycloak realm (`agfze`) imported on first boot: the eight platform roles, one confidential
  client, and nine seeded users covering every role plus one multi-role account.
- Backend: FastAPI with async SQLAlchemy 2 and Alembic, RS256 access-token verification against
  Keycloak's JWKS, just-in-time user provisioning on first authenticated request, an append-only
  audit table, a background-job status model and polling endpoint, a storage abstraction with a
  local filesystem implementation, structured JSON request logging with request correlation ids,
  and a single error envelope for every response.
- Frontend: Next.js App Router with NextAuth brokered through Keycloak, a role-aware shell
  (sidebar, header, user menu), a dashboard that displays only data the session and the profile
  endpoint actually provide, and three substantive legal pages.
- Tests: pytest for the backend (health, auth, jobs, storage), vitest for the frontend
  (roles, navigation, module cards).
- Fully pinned Python dependencies and a pinned frontend dependency set.

## What Step 3 deliberately does not include

A transaction reaches **`Approval Pending` and stops there**. There is no `ApprovalTask`, no
approval decision screen and no code path in this step that can move a transaction past that
state — the decision that would belongs to Step 4. Nothing is posted to SAP, written to a tracker
or filed in a document store, and no screen claims otherwise.

There is **no `ExceptionCase` table, no exception queue and no ownership, ageing or routing
logic** (Step 4). Failures are detected in full and presented with the specific rule, field,
expected value and actual value directly in the workspace, which is BR-08's detection half; the
queue a failure is routed *to* is what does not exist yet.

There is **no merge operation**, deliberately and permanently: an ambiguous match is resolved
before a transaction is created, never afterwards as a reconciliation of two separate records.

`SalesLeg`, `FaLeg`, `Container` and `Shipment` did not exist when Step 3 shipped. The transaction
detail response simply omitted the legs that had not been built, and the transactions list carried
a "linked shipment status" column that was honestly empty on every row. All four arrived in Steps 5
and 6, each through its own foreign key, and that column now carries real data — the response shape
did not change to accommodate any of them.

The `rule_configurations` table and its seeded defaults are in scope now; the admin screen that
edits those rows is Step 9. Editing a threshold today means editing a row, which is exactly what
the design intends.

**No dashboard metric, chart or counter has been added** — the dashboard is exactly as Step 1 left
it, even though real transaction data now exists, because a real number belongs on Step 8's cached
aggregation layer rather than in an ad-hoc query bolted on here.

## What Step 2 deliberately does not include

Step 2 stopped at a confirmed extraction: it shipped no matching, no validation rule, no tolerance
check, no duplicate-detection enforcement and no transaction record. Two things it stored were
stored specifically for Step 3 and are acted on from there: a document's SHA-256 content hash
(BR-13's duplicate key) and each territory's mandatory-document checklist (BR-04's completeness
check). `POST /documents/{id}/confirm` called a named, empty `on_extraction_confirmed` seam, which
Step 3 wires to the matching service.

`documents.transaction_id` and `background_jobs.transaction_id` were nullable UUIDs with no
foreign key, because the transactions table did not exist yet. Step 3's migration promotes both to
real constraints, and the Documents list's "Linked transaction" column now links into the
workspace for a document that has actually been matched.

The `DocumentTypeSchema` table and its seed data were in scope from Step 2; the admin screen that
edits those rows is Step 9, as are the audit explorer and the settings page. The header still
carries no working command palette and no notification bell — there is still nothing real to
notify about.

## What Step 1 deliberately does not include

Step 1 shipped **no business data, no dashboard metric, no chart, no counter and no external
integration** at all. Step 2 adds the first two external integrations (Microsoft Graph and Gemini)
and the first real business data; everything else in that list still holds. The user interface
marks every module that has not been built as unavailable ("Coming soon", with the step it arrives
in) instead of rendering a placeholder screen or fabricated figures.

The navigation contract names the module surfaces each step introduces. Inbox and Documents became
real, working links in Step 2 and Transactions in Step 3; the rest are still marked unavailable:

| Step | Introduces |
|---|---|
| 2 | Inbox and Documents |
| 3 | Transactions |
| 4 | Exceptions and Approvals |
| 5 | No new navigation surface; scope defined in that step's own contract |
| 6 | Shipments |
| 7 | No new navigation surface; scope defined in that step's own contract |
| 8 | Analytics and Reports |
| 9 | Admin |
| 10 | No new navigation surface; scope defined in that step's own contract |
| 11 | No new navigation surface; scope defined in that step's own contract |

Steps 5, 7, 10 and 11 add no navigation entry, so this step's contract does not fix their content;
nothing in Step 1 depends on them.

## Prerequisites

- Docker Engine 24 or newer with the Compose v2 plugin (`docker compose`, not `docker-compose`).
- GNU Make.
- Node.js 22 and npm — only needed for `make test-frontend` and `make lint-frontend`, which run on
  the host. Everything else runs inside containers.
- Ports 1025, 3000, 5432, 8000, 8025 and 8080 free on the host (1025 and 8025 are the local
  mail catcher).

## Quick start

```
make setup
make dev
```

`make setup` copies `backend/.env.example` and `frontend/.env.example` to `.env` when those files do
not exist yet, builds both images, starts PostgreSQL and Keycloak, waits for the database to report
healthy, applies the Alembic migrations, and prints the seeded logins.

`make dev` then runs all four services in the foreground. Open <http://localhost:3000> and sign in
with any seeded account below. `make help` lists every target.

## Ports

| Service | Address | Container | Notes |
|---|---|---|---|
| Frontend | http://localhost:3000 | `agfze-frontend` | Next.js application |
| Backend | http://localhost:8000 | `agfze-backend` | OpenAPI docs at `/docs` outside production |
| Keycloak | http://localhost:8080 | `agfze-keycloak` | Admin console, bootstrap admin `admin` / `admin` |
| PostgreSQL | localhost:5432 | `agfze-postgres` | User `agfze`, password `agfze`, databases `agfze` and `agfze_test` |
| MailHog | http://localhost:8025 | `agfze-mailhog` | Every notification email sent locally, HTML and plaintext. SMTP on 1025 |

Keycloak's management port (9000) carries the health endpoints and is deliberately not published;
the container health check probes it from inside the container.

## Seeded accounts

Created by the realm import. **Local development only.** The password is the same for every account
and is committed to this repository on purpose, so none of these credentials may ever exist in a
shared or production realm.

Password for all accounts: `Passw0rd!`

| Username | Email | Name | Roles |
|---|---|---|---|
| `hod.approver` | hod.approver@agfze.local | Rania Haddad | `approver_hod` |
| `purchase.user` | purchase.user@agfze.local | Marco Bellini | `purchase_user` |
| `sales.user` | sales.user@agfze.local | Aisha Rahman | `sales_user` |
| `fa.user` | fa.user@agfze.local | Daniel Okafor | `fa_user` |
| `logistics.user` | logistics.user@agfze.local | Priya Nair | `logistics_user` |
| `finance.user` | finance.user@agfze.local | Tomas Ceballos | `finance_user` |
| `admin.user` | admin.user@agfze.local | Sofia Lindqvist | `admin` |
| `auditor.user` | auditor.user@agfze.local | Kenji Watanabe | `auditor` |
| `dual.user` | dual.user@agfze.local | Nadia Farouk | `purchase_user`, `approver_hod` |

Every account also carries the realm's `default-roles-agfze` composite (`offline_access`,
`uma_authorization`). Those are Keycloak's own roles, not platform roles: both the backend and the
frontend filter the token's role list down to the eight platform roles before using it.

The realm also seeds one non-human client, added in Step 9: **`agfze-admin-api`**, a confidential
client with no interactive flow at all (standard flow, implicit flow and direct grants are all off)
whose service account holds the `realm-management: manage-users` client role and nothing else. It is
the credential behind the manual role override on `/admin/users`, and it is deliberately not the
`agfze-command-centre` client staff sign in through. Its local secret is
`agfze-local-admin-api-secret`, wired into the backend service in `docker-compose.yml`, so signing in
as `admin.user` and changing somebody's roles genuinely writes to the local Keycloak — the override
is testable end to end without a tenant.

Because `--import-realm` only imports a realm that does not already exist, an existing local stack
needs `make realm-import` once for the new client to appear.

## Roles

The same eight slugs are used by Keycloak, the backend and the frontend, in this order:

| Slug | Label | Governs, once the modules ship |
|---|---|---|
| `approver_hod` | Approver / HOD | Approval decisions and the approval queue |
| `purchase_user` | Purchase User | Purchase-side correspondence, documents and transactions |
| `sales_user` | Sales User | Sales-side correspondence, documents and shipments |
| `fa_user` | FA User | Front-office administration across purchase and sales work |
| `logistics_user` | Logistics User | Shipment and document handling |
| `finance_user` | Finance User | Financial views, analytics and reporting |
| `admin` | Admin | Platform configuration and user administration |
| `auditor` | Auditor | Read-only access across modules, including the audit trail |

Role assignment lives in Keycloak. The access token is the source of truth on every request: the
backend refreshes the stored role list from the token each time a user calls the API, so revoking a
role in Keycloak takes effect on that user's next request.

## The Keycloak issuer split

The one genuine trap in the local stack. The browser reaches Keycloak at `http://localhost:8080`,
but the Next.js server container and the backend container reach it at `http://keycloak:8080`.
Keycloak signs tokens with the issuer it was addressed by, so without care the `iss` claim depends
on which hostname produced the token, and validation fails on one side or the other.

The stack resolves it by pinning the issuer and separating the two hostnames explicitly:

- `keycloak` runs with `KC_HOSTNAME=http://localhost:8080` and `KC_HOSTNAME_STRICT=false`, so every
  token it issues carries `iss = http://localhost:8080/realms/agfze` regardless of the host used to
  request it.
- `frontend` receives both `KEYCLOAK_ISSUER=http://localhost:8080/realms/agfze` (browser-facing:
  the authorize redirect, the RP-initiated logout, and the issuer NextAuth checks) and
  `KEYCLOAK_INTERNAL_ISSUER=http://keycloak:8080/realms/agfze` (server-side: the token, userinfo,
  JWKS and refresh calls made from inside the container). Outside Docker,
  `KEYCLOAK_INTERNAL_ISSUER` is unset and falls back to `KEYCLOAK_ISSUER`, which is correct there.
- `backend` receives `KEYCLOAK_ISSUER=http://localhost:8080/realms/agfze` — the value it must
  compare the `iss` claim against — and
  `KEYCLOAK_JWKS_URL=http://keycloak:8080/realms/agfze/protocol/openid-connect/certs`, because it
  fetches the signing keys over the compose network rather than through the published port.

The API base URL is split the same way, for the same reason: `NEXT_PUBLIC_API_BASE_URL` is inlined
into the browser bundle at build time and must be an address your machine can reach
(`http://localhost:8000/api/v1`), while `API_INTERNAL_BASE_URL=http://backend:8000/api/v1` is what
the Next.js server itself uses when it renders a page. Outside Docker `API_INTERNAL_BASE_URL` can be
left unset and falls back to the public value.

If you change either hostname, change it in all three places at once.

## Getting an access token for API testing

The realm client has the direct access grant enabled so a token can be obtained without a browser.
This exists for local API testing only and must not be enabled on a real realm.

```
TOKEN=$(curl -s -X POST http://localhost:8080/realms/agfze/protocol/openid-connect/token \
  -d grant_type=password \
  -d client_id=agfze-command-centre \
  -d client_secret=agfze-local-dev-secret \
  -d username=admin.user \
  --data-urlencode 'password=Passw0rd!' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -s http://localhost:8000/api/v1/users/me -H "Authorization: Bearer $TOKEN"
```

The first authenticated call for a given account creates its row in `users` and writes one
`user.provisioned` audit event; later calls only update `last_login_at`. Do not paste a token into a
ticket, a chat message or a log file — it is a bearer credential until it expires.

## Running tests

```
make test            # backend then frontend
make test-backend    # pytest, inside the backend container
make test-frontend   # vitest, on the host
```

`make test-backend` starts PostgreSQL and runs pytest with `ENV=testing` against the separate
`agfze_test` database, so a test run never touches development data. The suite creates its schema by
running the Alembic migrations, which means a broken migration fails the tests rather than hiding
behind a metadata-created schema.

**The suite requires no Azure tenant, no mailbox and no Gemini key, and passes with none of them
present.** Microsoft Graph is exercised through `httpx.MockTransport`, so token acquisition and
caching, the 401-and-retry path, delta paging and attachment decoding all run against responses the
tests write themselves. Gemini is exercised by replacing the one provider call inside
`app/services/gemini_service.py` with a synthetic model response, which is what lets the routing,
the schema validation, the confidence handling and the failure paths be asserted deterministically
— the model's actual wording could never be. What is proved without any live credential:

- a message seen by both the webhook and the poll produces one `EmailMessage` and one `Request`;
- a valid model response parses into the expected schema, and a malformed one becomes a
  "needs human review" state rather than a crash or a coerced value;
- a text-layer PDF takes the PyMuPDF path and a scanned one takes the multimodal path;
- an oversized file and a file whose bytes contradict its extension are both refused server-side;
- a field below the threshold is flagged, and correcting it without a reason is refused;
- overriding a field always keeps the original AI value;
- the seeded invoice and contract schemas round-trip through the extraction service's selection.

**Step 9's administration, audit and notification suite needs no Keycloak either.** The Admin REST
API is driven through a fake installed at `keycloak_admin.set_keycloak_admin_client`, which is the
module's own swap point rather than a monkeypatched method, so the endpoint's real ordering is what
is under test. What is proved:

- a `RuleConfiguration` or `DocumentTypeSchema` edit with no reason, a whitespace reason or a
  token-length one is refused, and the row is unchanged afterwards;
- a valid edit is persisted, stamps the acting user, and writes its before/after onto the trail;
- the rules and document-type screens surface rows seeded in Steps 3, 5 and 6 alike — the FA-scoped
  threshold and `SL-01` reach and edit through exactly the same path as a Step 3 purchase tolerance;
- a role override calls Keycloak before any local write, and a Keycloak that fails every call
  leaves `users.roles` byte-for-byte unchanged;
- the CSV export streams against a two-thousand-row fixture: the header arrives before any row is
  read out of the cursor, the body arrives in many chunks rather than one, and every row is present;
- no audit payload from any prior step's call sites carries document text, a prompt or a credential;
- `PATCH /users/me/preferences` updates only the caller's own row, and a payload naming another
  account changes nothing on it;
- every trigger point in the notification table fires — including the exception broadcast to every
  active holder of the owning role, and a bulk decision producing one notification per transaction
  rather than one for the batch;
- a user can neither read nor mark-as-read another user's notifications;
- no module outside `notification_service` constructs a `Notification` — checked by reading the
  source of every module under `app/`.

**Step 10's delivery, PWA and offline suite needs no SMTP relay, no VAPID pair and no browser.**
Email is exercised by replacing `email_service._smtp_send` — the one synchronous call the service
makes to the outside world — so rendering, the multipart assembly, the retry schedule and the
failure paths all run for real. Push is exercised the same way at `push_service._send_webpush`, with
a fake that can answer with whatever status code a push service would. The service worker is
executed as the generated `public/sw.js`, in a sandbox with a fake Cache API. What is proved:

- each of Step 9's five trigger points dispatches email and/or push according to the recipient's
  actual channel state — **and a test reads the source of all four modules holding those five call
  sites and fails if any of them mentions a delivery channel at all**;
- a user on `email` with two subscribed browsers receives all three channels at once, one email and
  two pushes; a user on the `in_app` default with a subscription receives push and no email; a user
  on `email` with no subscription receives email and no push;
- a `410` or `404` from a push service deletes that subscription, and the next two notifications do
  not attempt it again, while the user's other browser is attempted every time;
- email retries exactly three times with 2s and 4s backoff, and a final failure leaves
  `email_sent_at` null and writes `notification.email_failed` to the audit trail;
- with the relay refusing everything and the push library raising, a real approval decision through
  the API still stands, and its notification still exists;
- an email's call-to-action is always built from `APP_BASE_URL`, and a link that is not a relative
  path can never send a reader off the platform;
- the push endpoints are self-only: quoting another account's endpoint on the DELETE removes
  nothing, and re-subscribing the same browser updates one row rather than creating a second;
- the service worker applies the correct strategy per request class, and **no mutating request is
  intercepted at all** — for four methods across ten paths, on both origins;
- the shipped `public/sw.js` contains no `sync` handler, no `SyncManager` and no IndexedDB;
- what the worker caches is keyed by a URL string, so no `Authorization` header enters storage;
- the manifest is valid and each icon is a real PNG at the size it claims, read out of its own
  IHDR chunk;
- the push prompt is not rendered on initial page load and does not so much as read the
  notification list until work has actually reached the user;
- signing out deletes every cache on the origin — including one an older build named — and removes
  the browser's subscription both sides.

Reference data written by a migration is preserved between tests rather than wiped, because a
database with no document schemas and no configured thresholds is a state no real deployment can be
in. Since Step 9 makes two of those tables genuinely editable, `clean_tables` now also restores
their editable columns from a snapshot taken once before the first test — so an admin test's
threshold edit cannot silently become every later test's configuration.

The suite also runs on a disposable SQLite file when `TEST_DATABASE_URL` is unset, so a checkout
with no container stack can still run it. PostgreSQL is the real target and is what CI uses.

**Step 11's own suites are the ones to run first when something looks wrong**, because each of them
fails for a reason that is easy to state:

```
pytest tests/test_rbac_matrix.py          # every endpoint x every role, both directions
pytest tests/test_security_posture.py     # secrets, headers, limits, and the absences
pytest tests/test_architecture_promises.py# the three claims, as tests that can fail
pytest tests/test_end_to_end.py           # eight scenarios, mail to Committed and back
pytest tests/test_invoice_date_rule.py    # IV-01, including that it can never block
npx vitest run src/__tests__/csp.test.ts src/__tests__/offline-governance.test.ts
```

`test_rbac_matrix.py` fails if a route exists that the matrix does not name, *and* if the matrix
names one that no longer exists — so adding an endpoint without deciding who may reach it breaks
the build rather than shipping.

Linting and formatting:

```
make lint            # ruff, then eslint and tsc
make lint-backend
make lint-frontend
make format          # ruff format and ruff --fix
make format-check    # fail if anything is unformatted, exactly as CI does
```

Deployment checks:

```
make verify-sw                              # the worker's manifest against the current build
make verify-production project=<gcp-project># the live estate against what Step 11 promised
```

## Notification delivery, the PWA and the service worker

### Reading the mail this platform sends, without sending any

Local development never talks to a real relay. The compose stack ships MailHog, and
`backend/.env.example` already points `SMTP_HOST`/`SMTP_PORT` at it:

```
make mail                        # starts the catcher
open http://localhost:8025       # everything the platform "sent", HTML part and plaintext part
```

Set a user's notification channel to email in **Settings**, then do anything that raises a
notification — submit a transaction for approval, or let a rule open an exception — and the message
appears in MailHog with its call-to-action pointing back at `APP_BASE_URL`. Nothing leaves your
machine. **Never point `SMTP_HOST` at a real mail server in development**: every trigger point in
this platform is reachable from a developer's own test data, and the addresses in that data are
real people's.

With no relay configured at all the platform still works and says so: the in-app notification is
created exactly as before, the email attempt is skipped and logged as skipped, and
`notifications.email_sent_at` stays null — which is honest, because nothing was sent.

### Generating a VAPID key pair

```
make vapid-keys
```

prints two lines to paste into `backend/.env`, and the public one also into `frontend/.env` as
`NEXT_PUBLIC_VAPID_PUBLIC_KEY`. The public half is public by the Web Push standard's own design —
the browser is handed it to bind a subscription with — and is served by
`GET /api/v1/notifications/vapid-public-key`. The private half signs deliveries, lives in
backend configuration only, and is never returned by any endpoint, logged, or sent to the frontend.

**Generate the pair once per environment and keep it.** Regenerating invalidates every subscription
every browser has ever taken, and each of those users has to grant permission again.

### The service worker is a production-only artefact — and this is not a bug

`npm run dev` **never registers a service worker**, and the app actively unregisters any that a
previous production build left on the origin. If you are trying offline mode locally and nothing is
being cached, this is why, and it is deliberate: a worker holding onto assets while Next.js is hot
-reloading them produces an environment that lies to you, and the hour lost to "why has my edit not
appeared" is worse than not having offline support on localhost.

To exercise it for real:

```
cd frontend
npm run build      # `postbuild` writes public/sw.js
npm start
```

then open the app, and use the browser's Application → Service Workers panel with **Offline**
ticked. `public/sw.js` is generated, not committed: `scripts/build-sw.mjs` injects the precache
manifest, the deployed build hash and the API origin into the two hand-written modules in
`src/service-worker/`. Edit those, never the output.

### What the worker caches, and what it will never cache

| Request class | Strategy |
|---|---|
| Precached shell, `/offline`, `/_next/static/*`, icons, the manifest | Cache-first |
| List and summary reads — transactions, exceptions, approvals, shipments, documents, dashboard summary, KPIs | Stale-while-revalidate |
| Single-record detail reads | Network-first; a cached copy **only** on a genuine network failure, never on a 404 or a 500 |
| **Every** mutating request — `submit`, `decide`, `generate-draft`, `confirm`, `resolve` and all the rest | **Network-only. Never cached, never queued, never replayed.** |
| A navigation with no network and nothing cached | The precached `/offline` route |

Cached responses expire after fifteen minutes, and both caches are named after the deployed build
hash, so a release invalidates the previous one rather than needing a manual clear. Cache scope is
this application's own origin plus its API origin and nothing else, and every write is keyed by a
URL string rather than by a `Request` — which is what guarantees no `Authorization` header can end
up in storage.

The last row is a governance boundary rather than a caching decision, and it is permanent. There is
no background sync, no replay queue and no IndexedDB in the worker at all.

### Installing the app

The install button appears in the header when the browser offers an install. On Chromium — Android,
Windows, macOS — it opens the browser's own prompt. On iOS Safari, which never fires
`beforeinstallprompt` and exposes no install API, it opens Share-sheet instructions instead. The
icon set is generated from the header's own brand mark:

```
make icons        # or: cd frontend && npm run icons
```

### Signing out clears the device

The sign-out flow cancels this browser's push subscription (browser-side and through
`DELETE /api/v1/notifications/push-subscribe`) and deletes **every** cache on the origin before the
session closes — including caches an older build wrote under a name this one has never heard of. A
cached screen can name a counterparty and quote a price; on a shared or lost device the correct
amount of that left behind is none. All of it is best effort and none of it can fail the sign-out:
a device left signed in because a cache would not clear would be the worse outcome.

## Adding a migration

```
make migration m="add shipments table"
make migrate
```

`make migration` runs Alembic autogenerate inside the backend container against the running
database; `make migrate` applies pending revisions. Always read the generated file in
`backend/alembic/versions/` before committing it — autogenerate does not reliably detect server
defaults, constraint renames or data migrations, and it will happily emit an empty revision.

The backend container also runs `alembic upgrade head` before starting uvicorn, so `make dev` on a
fresh checkout produces a fully migrated database without a manual step.

## Dependency management

Backend dependencies are pinned in three files:

| File | Contents |
|---|---|
| `backend/requirements.in` | Direct dependencies only, no versions. Edit this one. |
| `backend/requirements.txt` | Every direct and transitive package pinned with `==`. Generated. Installed by the Docker image. |
| `backend/requirements.lock` | The same resolution with `--generate-hashes`, for hash-checking installs. Generated. |

```
make lock
```

regenerates both compiled files inside the backend container, so the resolution matches the
Python 3.12 runtime rather than whatever interpreter happens to be on your host. Never hand-edit the
generated files: add or bump the package in `requirements.in` and re-run `make lock`.

Frontend dependencies are pinned to exact versions in `frontend/package.json`; `npm ci` installs
from `package-lock.json`.

Step 2 adds `google-genai`, `pymupdf`, `python-docx`, `pandas`, `openpyxl`, `python-magic` and
`python-multipart` to `requirements.in`. `python-magic` is a binding, not an implementation: the
backend image installs `libmagic1` (and `libgomp1`, which numpy needs) so file-type detection reads
real bytes rather than guessing from a filename.

Step 10 adds `pywebpush` (which brings `py-vapid` and `http-ece`, both used directly by the key
generator and the payload encryption) and `jinja2`. Jinja2 already arrived transitively; it is
declared explicitly because this platform now imports it, and a package you import is a package you
depend on whether or not something else happens to install it. Nothing in this step needs a new
system library in the image.

## Supplying Graph and Gemini credentials locally

Both integrations are real HTTP APIs reached over the network, so neither adds a compose service.
Every setting they need is in `backend/.env.example`; copy it to `backend/.env` (`make setup` does
this) and fill in your own values. `docker-compose.yml` deliberately does not declare these
variables — `./backend` is bind-mounted to the container's working directory, so the backend reads
`backend/.env` directly, and a compose entry would only shadow it with an empty string.

**Microsoft Graph.** Register a dedicated application in your Azure AD test tenant — this is a
machine identity with no interactive login, entirely separate from the Keycloak/Entra broker staff
sign in through. Grant it the **application** permission `Mail.Read`, then narrow it to the one
approved mailbox with an application access policy so it cannot read the whole tenant:

```
New-ApplicationAccessPolicy -AppId <client-id> -PolicyScopeGroupId <mailbox-or-group>   -AccessRight RestrictAccess -Description "AGFZE Command Centre intake"
```

Grant admin consent, then set `AZURE_AD_TENANT_ID`, `AZURE_AD_CLIENT_ID`, `AZURE_AD_CLIENT_SECRET`
and `GRAPH_MAILBOX_ADDRESS`. Do not add any Excel or SharePoint write scope — those arrive with
Step 7.

The delta poll works immediately and needs nothing else. Change notifications additionally need a
URL Microsoft can reach from the public internet, which a developer machine does not have; tunnel
one in (`cloudflared tunnel --url http://localhost:8000` or equivalent), then set
`GRAPH_WEBHOOK_ENABLED=true`, `GRAPH_WEBHOOK_NOTIFICATION_URL=https://<tunnel>/api/v1/graph/notifications`
and a random `GRAPH_WEBHOOK_CLIENT_STATE` (`openssl rand -hex 32`). The subscription is created and
renewed by the backend on its own; the webhook is only a latency improvement, so leaving it off
loses no mail.

**Gemini.** Create an API key in Google AI Studio and set `GEMINI_API_KEY`. `GEMINI_MODEL` defaults
to `gemini-2.5-flash`.

With any of these missing the backend still starts in development and logs
`mailbox_worker_not_started`; a request that needs the model then fails visibly and lands in the
review queue rather than silently succeeding. In production the settings validator refuses to start
at all until every one of them is present.

## Repository layout

```
.
├── docker-compose.yml            Five services, one bridge network
├── Makefile                      Developer entry points (make help)
├── docs/
│   └── KNOWN-GAPS.md             What AGFZE must confirm before go-live
├── .github/workflows/
│   ├── ci.yml                    Blocking: lint, format, tests, migration dry-run, images
│   ├── release.yml               Tagged release; both services deploy independently
│   └── rollback.yml              One service's traffic split, reverted on its own
├── infra/
│   ├── keycloak/realm-agfze.json Realm, roles, the login client, the Admin API
│   │                             service-account client, and seeded users
│   ├── postgres/init-test-db.sh  Creates the agfze_test database
│   └── production/               Terraform: Cloud Run x2, private Cloud SQL with CMEK,
│                                 backups and PITR, Secret Manager, Cloud Armor, TLS -
│                                 plus verify-production.sh, which reads it all back
├── backend/
│   ├── Dockerfile                Multi-stage, non-root runtime
│   ├── alembic/                  Migration environment and versions
│   ├── app/
│   │   ├── api/
│   │   │   ├── internal/files.py Resolves the signed URLs the document API mints
│   │   │   └── v1/               health, users, notifications, jobs, requests,
│   │   │                         documents, transactions, shipments, exceptions,
│   │   │                         approvals, integrations, admin, audit, dashboards,
│   │   │                         reports, graph notification receiver
│   │   ├── core/                 config, logging, errors, roles, security,
│   │   │                         dependencies, rate limiting (a default ceiling
│   │   │                         plus five named categories), observability
│   │   ├── db/                   declarative base, session, cross-dialect types
│   │   ├── middleware/           request logging and correlation ids,
│   │   │                         security headers (the API's own CSP, HSTS, nosniff)
│   │   ├── models/               identity, audit, notifications, push subscriptions,
│   │   │                         jobs, intake
│   │   │                         (email, request, document, extracted field),
│   │   │                         enums, configuration/ (document_schema,
│   │   │                         rule_configuration), governance/, transactions/,
│   │   │                         logistics/, integration/, reporting
│   │   ├── schemas/              response envelope and read models
│   │   └── services/             audit, audit_query (explorer and streamed export),
│   │                             notification_service (the single writer of a
│   │                             Notification row, and the single place email and
│   │                             push dispatch from), delivery/ (email_service,
│   │                             push_service, Jinja2 email templates),
│   │                             keycloak_admin, jobs, storage,
│   │                             graph, gemini, classification, extraction,
│   │                             document orchestration, email ingestion, mailbox
│   │                             worker, file admission, text extraction, schema
│   │                             defaults, rules/ (the registry, the evaluators, and
│   │                             the sales, logistics and invoice-dating modules
│   │                             that register against it), governance/,
│   │                             logistics/, integration/, analytics/
│   ├── scripts/                  seed_sales_demo, generate_vapid_keys
│   ├── tests/                    pytest suite, including the Step 11 additions:
│   │                             test_rbac_matrix (every endpoint x every role),
│   │                             test_security_posture (secrets, headers, limits,
│   │                             absences), test_architecture_promises,
│   │                             test_end_to_end, test_invoice_date_rule
│   └── requirements.{in,txt,lock}
└── frontend/
    ├── Dockerfile                Multi-stage, standalone Next.js output
    ├── public/                   Web app manifest and the generated icon set.
    │                             public/sw.js is written by the build, not committed
    ├── scripts/                  generate-icons.mjs (brand mark to PNG set),
    │                             build-sw.mjs (precache-manifest injection, run as
    │                             postbuild and therefore never by `npm run dev`),
    │                             verify-sw-manifest.mjs (CI gate: the worker against
    │                             the build it claims to be from)
    └── src/
        ├── app/                  App Router: public, auth and protected groups
        │                         (inbox, documents, transactions and its purchase,
        │                         sales and fa workspaces, exceptions, approvals,
        │                         shipments, analytics, reports, notifications,
        │                         settings, offline, and admin with users, rules,
        │                         document-types, audit and integrations)
        ├── components/           ui primitives, layout shell (with the header
        │                         notification bell and install button), pwa/ (service
        │                         worker registrar, install button, contextual push
        │                         prompt, push settings, offline banner and page),
        │                         shared pieces, intake/ (queue,
        │                         filters, upload, review, viewer), transactions/,
        │                         exceptions/, approvals/, shipments/, integrations/,
        │                         dashboard/, analytics/, charts/, reports/,
        │                         admin/ (rules and document-type tables, their
        │                         reason-gated edit dialogs, users table, role
        │                         override dialog, audit explorer), settings/,
        │                         notifications/
        ├── hooks/
        ├── middleware.ts         Session enforcement on the governed routes, and the
        │                         Content-Security-Policy on every response
        ├── lib/                  auth, env validation, roles, navigation,
        │                         api client, intake, transaction, shipment,
        │                         governance, integration and analytics
        │                         vocabularies, admin, audit and notification
        │                         helpers, pwa, push and offline state, csp (the
        │                         policy built in one pure function, so the rules the
        │                         browser enforces are the object the tests assert on)
        ├── service-worker/       strategy.js (the caching rules, imported by the
        │                         tests and inlined into sw.js) and runtime.js
        └── __tests__/            vitest suite
```

## Local infrastructure notes

- `infra/postgres/init-test-db.sh` is mounted read-only into `/docker-entrypoint-initdb.d/`. The
  PostgreSQL entrypoint sources `.sh` files it finds there, so the file works from a fresh clone
  even if the executable bit did not survive checkout — the `.sh` extension is what matters. It runs
  only when the data directory is empty, so if `agfze_test` is missing, remove the
  `agfze-postgres-data` volume (`make clean`) and start again.
- Keycloak runs in development mode and keeps the realm in an H2 file inside the container.
  `--import-realm` only imports a realm that does not already exist, so edits to
  `realm-agfze.json` need `make realm-import`, which discards and recreates the container.
- The backend bind-mounts `./backend` into `/app` for edit-and-reload, with a named volume on
  `/app/var` so the local storage root stays out of your working tree. That volume is owned by the
  image's unprivileged `appuser`, so the Make targets that write generated files or tool caches back
  into the bind mount (`migration`, `format`, `lint-backend`, `test-backend`, `lock`) run as your
  host user instead.
- When `TEST_DATABASE_URL` is unset, the backend suite falls back to a throwaway SQLite file in the
  system temp directory, so a checkout with no containers running can still execute it. PostgreSQL
  is the real target and is what `make test-backend` uses; either way the schema is built by
  Alembic, never from model metadata.
- `make clean` removes the containers, the named volumes (including all database contents) and the
  local build artefacts.

## Security notes

- The only credentials in this repository are local development values: the Keycloak client secret
  `agfze-local-dev-secret`, the PostgreSQL account `agfze` / `agfze`, the Keycloak bootstrap admin
  `admin` / `admin`, and the seeded user password. Every one of them must be replaced before any
  deployment that is not a developer laptop. Real `.env` files are ignored by git; only
  `.env.example` files are committed.
- Access tokens are never persisted to browser storage. NextAuth keeps the session in an HTTP-only,
  SameSite cookie; the access token is surfaced to the page only through the in-memory NextAuth
  session, and every backend call in this step is made server-side.
- The backend verifies the RS256 signature, issuer and audience of every access token against
  Keycloak's JWKS on every request, and takes the user's roles from that token rather than from the
  database row.
- `audit_events` is append-only: no route updates or deletes it at any role, and its metadata column
  holds metadata only — never document text and never a model prompt or response.
- Clients receive a generic error envelope. Database errors, connection strings and driver text are
  logged server-side with a request id and never returned. Tokens, secrets and passwords are never
  logged.
- Rate limiting is disabled in development and enabled in the production settings profile, which
  also refuses to start when the issuer or JWKS URL is empty, when the storage signing secret is
  still the default, or when CORS is configured with a wildcard origin.
- The local realm sets `sslRequired: "none"` because the whole stack is plain HTTP on localhost. A
  real realm must require SSL, use a rotated client secret, and take its users from Microsoft
  Entra ID rather than from this file.

### Added in Step 2

- **File types are decided by magic bytes, never by a filename or a client-supplied content type.**
  The same check runs on the portal upload path and on every attachment fetched from Graph; a file
  named `.pdf` whose bytes are an executable is refused on both. The 25 MB limit is applied to the
  running total while the body streams, so an oversized upload is rejected before it is buffered.
- **No raw path and no permanent public URL is ever exposed for a document or a page image.** Files
  are stored under opaque, UUID-derived keys, and the frontend reaches them only through
  short-lived HMAC-signed URLs minted by an authenticated endpoint. An invalid signature, an expired
  link and a missing object all answer 404, so a stale link cannot be used to probe which keys exist.
- **Untrusted document content is fenced in the prompt.** Email bodies and document text are handed
  to the model inside a delimited block with an explicit instruction that its contents are data to
  read and never instructions to follow, so a malicious or malformed email cannot redirect the
  classifier or the extractor.
- **A model response that fails schema validation is never coerced into shape.** It is treated as a
  failed call and routed to human review, as are quota failures, timeouts and malformed JSON.
- **Provider error detail never reaches a client.** Graph and Gemini failures are logged by type and
  status only — a key fragment or an internal URL cannot travel out in an error body — and the
  caller receives a clean, generic failure state.
- **The Graph and Gemini credentials live only in environment configuration.** They are never
  logged, never returned by any endpoint, and never present in frontend code; the browser never
  talks to either service.
- **The webhook endpoint is authenticated by Graph's own `clientState` secret**, compared in
  constant time, and it performs no work inline — a notification without the configured secret is
  discarded.
- **Every new endpoint enforces its role at the dependency layer.** Reading the queue, a request and
  a document is open to any authenticated account; correcting a category, correcting a field,
  reclassifying, confirming and uploading are restricted to the purchase, sales, FA, logistics and
  admin desks. The approver and the auditor are refused server-side, not merely shown fewer buttons.
- **Extracted and AI-generated content is rendered as text, never as markup.** Email bodies go into
  a `<pre>`; no component in this step uses `dangerouslySetInnerHTML`.

### Added in Step 6

- **The manual shipment path is held to exactly the same standard as the automated one.** Recording
  where cargo is by hand is an authenticated, role-gated, audited write that moves `last_checked_at`
  and passes through the same plausibility check an adapter's result does. It is not treated as
  lower-scrutiny because no external system was involved — for almost every shipment on this
  platform it is the only way a status is ever established.
- **`fa_legs.extra_fields` is a validated field, never a place to post arbitrary JSON.** A key the
  configured FA schema does not carry is refused at the endpoint and at the correction path alike,
  so the structured column can only ever hold fields somebody configured.
- **No carrier adapter ships, and a test enforces that.** The adapter registry is empty on a fresh
  import, and `tests/test_shipments.py` reads the adapter module and fails if a shipping line is
  named in it. An integration nobody has agreed cannot appear by accident.
- **Every shipment endpoint enforces its role server-side.** Reading the board is open to any
  authenticated account, on the same transparency principle the transaction list and the exception
  queue follow. Refreshing, correcting by hand and logging an issue are Logistics or Admin, checked
  at the dependency layer rather than by hiding a control.
- **The staleness exception is created by calling the exception service directly.** It does not
  synthesise a rule evaluation to reuse the hard-fail hook, because a fabricated row in
  `rule_evaluations` would be a fabrication in the table auditors read as a record of real checks.

### Added in Step 9

- **A third machine credential, and deliberately a third one.** The Keycloak Admin REST API is
  reached with its own confidential client whose service account holds exactly one grant,
  `realm-management: manage-users`. It is not the OIDC client staff sign in through — that one has
  no administrative grant at all — and not the Azure AD app registration that reads the mailbox and
  writes the tracker workbook. Three capabilities, three credentials, three blast radii. The secret
  lives only in environment configuration, is never logged (only the HTTP status of a rejected call
  reaches a log line), is never returned by any endpoint, and never reaches frontend code.
- **A role change is never committed locally before the identity provider has confirmed it.**
  `PATCH /admin/users` calls Keycloak synchronously and writes nothing to `users.roles` until that
  call returns successfully. A transport error, a refusal or an unconfigured deployment leaves the
  local record byte-for-byte unchanged and returns a clear error, and the refused attempt is itself
  recorded on the audit trail with `local_state_changed: false`. A test drives a Keycloak that
  fails every call and asserts the local row is untouched.
- **A configuration change without a valid reason is refused server-side.** The reason is a
  required, minimum-length field on the request schema for both `RuleConfiguration` and
  `DocumentTypeSchema`, so a request missing it is rejected with a 422 before any handler runs. The
  dialog's disabled Save button is a courtesy on top of a refusal that happens either way.
- **A document schema is validated rather than trusted.** A malformed field list does not fail
  loudly at extraction time — it quietly extracts nothing — so the update endpoint refuses an empty
  field list, a field with no name or no type, and duplicate field names.
- **Settings and notifications are self-only in the query, not in the routing.** Every statement
  filters on the user id resolved from the verified token. There is no path parameter naming an
  account, no query parameter that could widen the scope, and the preferences schema carries no
  `roles`, `email` or `is_active` field — so a crafted request has nothing to reach rather than
  something to be filtered out. Tests assert that a payload naming another account changes only the
  caller's own row.
- **The audit trail stays append-only and stays metadata-only.** No route updates or deletes it at
  any role — a test asserts every write method on `/audit` answers 405. A test also reads a
  representative sample of payloads from every prior step and fails if any carries document text, a
  prompt, a completion or a credential, and the read layer redacts by key and truncates by length on
  the way out as a backstop rather than as the primary defence.
- **The export streams and is itself audited.** The CSV is produced row by row from a server-side
  cursor with `yield_per`, so memory is a function of the chunk size rather than of how many events
  the platform has recorded since Step 1. Taking a copy of the trail is recorded as an event on the
  trail, with the filters and row count that produced it.
- **Every admin endpoint enforces its role at the dependency layer.** `/admin/*` is Admin; the audit
  explorer is Admin or Auditor. An Auditor is refused the rules, document-type and user screens
  server-side, not merely shown fewer links.

### Added in Step 10

- The VAPID **private** key and the SMTP credentials exist only in backend configuration. Neither is
  returned by any endpoint, written to a log, or reachable from the browser bundle. The VAPID
  **public** key is the single deliberate exception: the Web Push standard hands it to the browser
  to bind a subscription with, so it is served by its own endpoint and inlined as
  `NEXT_PUBLIC_VAPID_PUBLIC_KEY`.
- Every push endpoint is self-only server-side. `user_id` comes from the verified token on all
  three, no body carries an account identifier, and the DELETE's ownership predicate is part of the
  statement rather than a check performed before it — so quoting another account's endpoint deletes
  nothing rather than deleting theirs.
- The service worker's cache scope is this origin plus the configured API origin. Any other origin
  is passed through untouched and never enters storage. Every cache write is keyed by a URL string
  rather than by a `Request`, which is what makes it structurally impossible for an `Authorization`
  header or a token to be stored.
- A notification email carries the event's one-line summary and a link, and no commercial detail
  beyond it. A push payload travels through a third-party push service and carries the same summary
  and a path — never a counterparty, never a figure, never a token.
- Signing out deletes every cache on the origin and cancels the browser's push subscription on both
  sides, so a shared or lost device retains no cached counterparty name, no commercial figure, and
  no subscription that would keep telling it an approval is waiting.

### Added in Step 11

- **A Content-Security-Policy, for the first time.** No prior step shipped one. Set in the frontend
  middleware on every response, including the sign-in page and the legal pages, with a per-request
  nonce that Next.js stamps onto its own bootstrap scripts — so `script-src` carries no
  `'unsafe-inline'` and no `'unsafe-eval'`. `connect-src` allows this origin, the API and the
  Keycloak issuer, and nothing else: every external system this platform integrates with is reached
  by the backend, so none of them belongs in a browser-facing policy and a test asserts that none
  of them is named in it. The API serves its own, stricter policy — `default-src 'none'` — because
  it returns JSON and needs to load nothing at all.
- **Rate limits with real values, enforced in running code.** Five named categories matched on
  method and path — authentication-adjacent, upload, every AI-calling endpoint (including opening
  an approval, whose summary is generated on first view and therefore costs a model call), bulk
  approval, and the unauthenticated Graph webhook — each evaluated before the default ceiling. A
  test drives one to its limit and asserts a genuine 429. The refusal names the category and never
  the remaining budget: telling a legitimate integration which bucket it is in helps it back off,
  telling somebody probing how fast they may probe does not. Health probes are exempt from both
  layers, because a readiness probe answering 429 takes a healthy instance out of rotation.
- **The forwarded client address is trusted only where a proxy sets it.** `RATE_LIMIT_TRUST_FORWARDED_FOR`
  is off by default and on in production. On a directly-reachable process `X-Forwarded-For` is
  client-supplied, and honouring it would let one caller present a fresh identity per request.
- **Every endpoint's roles verified, in both directions, against the live route tree.** Not a spot
  check: the matrix is compared with the application's own routes and fails if either side has an
  entry the other does not. The four non-negotiable items are each specifically covered — a
  client-supplied `decided_by`/`decided_at` is ignored in favour of the token subject and the server
  clock (asserted adversarially), every `/admin/*` write refuses a missing or token-length reason at
  the schema before any handler runs, the role override writes nothing locally until Keycloak has
  confirmed, and settings, notifications and push subscriptions are self-only in the query rather
  than in the routing.
- **One real authorisation hole, found and closed.** `POST /transactions/{id}/acknowledge-tolerance`
  did not check leg ownership, unlike the three sibling writes on the same router, so a desk user
  could accept a discrepancy on a transaction carrying only another desk's leg. It now applies the
  same `_may_write` check.
- **A magic-byte check that no longer depends on which libmagic build a machine has.** Some builds
  report a valid `.docx` as `application/octet-stream`. The container branch now confirms the ZIP
  local-file signature in the bytes themselves before the extension is allowed to choose between the
  two admitted OOXML types — so a genuine Word document is accepted everywhere, and an
  octet-stream that is not actually a zip is refused exactly as it was before.
- **HSTS, `nosniff`, `DENY` framing, a no-referrer policy and `no-store`** on every API response,
  applied outside the rate limiter so a 429 carries them too. HSTS only over HTTPS and only in
  production: pinning a browser to a scheme the local stack does not serve would make that stack
  unreachable in the same browser afterwards.
- **The absences, searched for rather than assumed.** No path can send a generated document to a
  counterparty; nothing queues a mutating request for replay; no request schema carries a
  server-authoritative audit field; and no admin screen exists for the endpoint targets, the
  rule-to-category mapping or the report templates.
- **Encryption at rest, private connectivity, backups and point-in-time recovery are configured in
  Terraform and then read back by a script.** `infra/production/verify-production.sh` fails if the
  database has a public address, if PITR is off, if no backup has actually completed, if the WAF is
  not attached to both services, if the API is allowed to scale to zero (which would stop the
  sweeps), or if the database password is still the placeholder the secret was created with.
