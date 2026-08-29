# Implementation report — closing the audit-identified gaps

**Scope.** Two working sessions. The first covered `FIX-001` (Critical) and the High-priority
tasks of §11: `IMPL-004`, `CLARIFY-005`, `CLARIFY-006`, `IMPL-007`, `IMPL-008`, `VERIFY-009`,
`IMPL-010`, `VERIFY-011`, with `CLARIFY-002` and `CLARIFY-003` verified as compliant. The second
covered `IMPL-018` (blocked), `IMPL-019`, `IMPL-020`, `VERIFY-021`, `CONFIG-022`, `IMPL-023`,
`FIX-024`, and the `CONFIG-025`–`028` activation prerequisites. The third covered the five tasks
whose specifications had never actually arrived: `IMPL-013`, `IMPL-014`, `IMPL-016`, `IMPL-017` and
`IMPL-012`. Every task in the full specification now has a final status — see §9.

**How to read the dispositions.** *Implemented* means the code does the thing and a test proves it.
*Verified* means nothing needed changing and this report says how that was established. *Blocked*
means an external dependency prevents it. *Needs clarification* means the business question is
genuinely open and no amount of engineering resolves it — those are collected in the last section
and are the part of this document worth someone's attention.

---

## 1. Corrections to the Audit Findings Register

Three findings did not survive static verification. The register should be read with these
corrections rather than as originally written.

| ID | Original finding | What is actually true |
|---|---|---|
| **AF-08a** | "No Accordion exists; unconfirmed whether workspace sections render as a flat block." | **Wrong.** `collapsible-panel.tsx` already implements the PRD's pattern exactly — Extraction and Validation open by default, Matching and History collapsed — on a native button with correct `aria-expanded`/`aria-controls`. The behavioural requirement was already met. Only the underlying library differs from the one the PRD named, which is a far lower-stakes gap than "the UX pattern does not exist". No rebuild was done, deliberately. |
| **AF-08b** | "No Tabs component exists anywhere." | **Overstated.** `category-tabs.tsx` implements real tabs with `role="tablist"`, `role="tab"` and `aria-selected`, on natively focusable buttons. The genuine shortfall is narrower: no arrow-key roving tabindex, which is the WAI-ARIA authoring pattern's keyboard behaviour. |
| **AF-25** | "The default company code (`26`) does not reproduce the worked example `I7026-642`." | **Misdiagnosed.** `26` *does* match the example's 3rd–4th digits. What does not reproduce is the financial-year segment: the code computes `I` + FY + company, and no plausible year yields `70`. Under the reverse reading — company `70`, FY `26` — the example fits 2026 exactly, and `70` echoes the "Business Area 1070" named elsewhere in the same discovery material. **The open question is field order, not the company-code value.** No code was changed; see the clarifications section. |

Also worth recording, because it changes what the assumptions section of the specification claimed:

- **Assumption A4 was false in two ways.** The stated baseline of "571 backend and 25 frontend
  tests" understates the repository: the backend suite is ~854 tests and the frontend is 25 test
  *files* carrying 272 tests. More importantly, the backend suite did not run at all on a fresh
  checkout — see the pre-existing defect below.

---

## 2. A pre-existing defect found while establishing the baseline

`backend/app/core/config.py` — `TRACKER_COLUMN_MAP` was missing the `NoDecode` annotation that
`JWT_ALGORITHMS` and `CORS_ALLOWED_ORIGINS` both carry two lines above it. Without it,
pydantic-settings JSON-decodes the dotenv value *before* the field validator runs, so the blank
default shipped in `.env.example` raises `SettingsError` at import and the process never starts.

This affects anyone who runs `make setup`, which copies `.env.example` to `.env`. It is unrelated
to every task in this specification and was fixed because it blocked all of them. It is worth
treating as its own bug report: the shipped example environment could not boot the stack.

---

## 3. Dispositions

### FIX-001 — Segregation of duties on approval · **Implemented**

`approval_service.decide` refuses an **approval** by the account recorded as the transaction's
submitter, raising `ConflictError` with code `segregation_of_duties` before any state changes.

`ConflictError` rather than `AuthorizationError`, deliberately: the caller *does* hold the approver
role, so this is not an access failure, and the bulk endpoint already catches `ConflictError` per
row — which means a self-submitted transaction is refused *by name* while the rest of the batch
still goes through. `AuthorizationError` would have failed the whole batch.

Not barred, and each for a stated reason: a **rejection or change request** by the submitter
(returning a transaction to its own desk commits nothing), and a transaction with a **null
submitter** (no maker to check the checker against). No override mechanism was invented.

Six tests, asserting resulting state rather than call counts: task still pending, transaction still
`Approval Pending`, zero `IntegrationJob` rows, zero `APPROVAL_DECIDED` audit events.

### CLARIFY-002 — BR-05 quantity tolerance · **Verified, no action required**

5.0% is seeded, matching the BRD's stated value, and the Meeting Report's competing ~3.3% is
already documented both in the seed row's own `change_reason` and in `KNOWN-GAPS.md` §1. The
evaluator reads the value generically. Nothing to change. Which figure AGFZE actually wants remains
open and is listed below.

### CLARIFY-003 — BR-06 tolerance tiers · **Verified, no action required**

`amount_rounding = 1.00` and `amount_self_approval_limit = 10.00`, matching the Meeting Report's
$1 / $1–$10 / >$10 exactly. Nothing to change.

### IMPL-004 — Report distribution · **Implemented**

A new `ReportDistributionRule` table (empty on migration, by design), an admin screen at
`/admin/report-distribution` with the same mandatory-reason discipline every other configuration
screen carries, and distribution wired into the existing scheduled-report path.

Three properties worth stating because they were design decisions rather than mechanics:

- **It reaches nobody until configured.** No seed rows. A report type with no active rule generates
  and is readable exactly as before, and that is a quiet, correct outcome rather than an error.
- **The channel is a ceiling, never a floor.** `notify()` gained an `allow_email` parameter that can
  only *decline* an email, never impose one. A rule set to email cannot email somebody whose own
  notification preference is in-app. Both directions are tested.
- **Nothing is ever attached.** Recipients get a notification linking to the report's authenticated
  detail page. No second delivery mechanism was built; everything goes through `notify()`.

The in-document disclosure was reworded. It used to read "the platform has no outbound distribution
capability", which stopped being true; it now says what remains true and is more useful to a reader
holding a printed page — *this file* is never sent by the platform.

19 tests.

### CLARIFY-005 — B2B workflow · **Scaffolding implemented; business logic deliberately not**

`PurchaseLeg.is_b2b` and `b2b_partner_name`, a `deal_type` filter on the transaction list and its
API, and a B2B badge on the table. The tag is editable through the ordinary field-correction
endpoint, with its existing reason gate — which required adding a `boolean` field type to the
editor, since none existed.

**No profit split, expense sharing or loss allocation was built**, because no source document
specifies any of it beyond illustrative percentages. A test fails if a column matching those names
is added, so doing so later has to be deliberate.

One implementation note worth keeping: the `deal_type` filter uses an EXISTS over an *aliased*
`PurchaseLeg`. Against the bare mapped class SQLAlchemy auto-correlates the subquery to the
enclosing query's FROM, and once the `search` filter has joined `purchase_legs` the subquery loses
its own FROM and the statement fails at runtime. This was found by a test that combines both
filters, and that test is why it is now correct.

### CLARIFY-006 — Amendments chatbot · **Deliberately not built**

No chatbot code was introduced. The substance discovery asked for — capture what changed, draft it,
route it for approval with a summary — is what the existing field-correction path already does: a
mandatory reason, provenance against the AI's original value, synchronous re-validation, and
re-submission in front of an approver with the change visible. A chatbot would be a different
*interface* onto that path, not a new capability. Recorded as `KNOWN-GAPS.md` §15.

### IMPL-007 — Shared rate-limit counter store · **Implemented**

A `google_redis_instance` (1 GB, `BASIC`, private service access, AUTH and in-transit encryption)
in the production Terraform, with the API's `RATE_LIMIT_STORAGE_URI` built from it automatically.
No application code needed changing — the `slowapi` integration already passed the setting through,
which is what made this a provisioning gap rather than a code one.

Production now **refuses to start** on an in-process store rather than warning, because a warning on
a start-up line nobody reads is how a bulk-approval limit ends up five times more permissive than it
reads for a year. A genuinely single-instance deployment opts out with
`RATE_LIMIT_ALLOW_IN_PROCESS=true`, which has to be said out loud.

### IMPL-008 — Performa invoice and bank cover letter templates · **Implemented**

Both now exist as real, renderable `.docx` assets built from the same declaration the existing two
use, with new `DocumentType` values and a migration widening the check constraint.

The Performa invoice is exempt from BR-07's draft gate, and the exemption is narrow and documented:
BR-07 holds a draft *commercial* invoice back until shipment evidence exists because a commercial
invoice states what shipped. A Performa invoice is raised *before* the cargo is weighed — that is
what makes it a Performa invoice — so gating it the same way would make the platform unable to
produce one in the only circumstance it is ever produced in. A bank cover letter is exempt because
it lists an enclosed documentary set and asserts nothing about the cargo. Both still require a sales
leg, and a test proves the exemption does not extend that far.

The Performa template carries no `bl_reference` and no shipped weight, and says so in a required
clause, so a reader never has to infer from a blank field that the document is complete.

### VERIFY-009 — SAP payload field mapping · **Completed, with three fields flagged**

| Named in discovery | Disposition |
|---|---|
| Assignment = invoice number | **Added.** A stated mapping. |
| Header Text = batch number | **Added.** A stated mapping. |
| Business Area 1070 | **Added** as `SAP_BUSINESS_AREA`, configurable rather than a literal. |
| DMS document number | **Added**, opportunistically — see below. |
| MIRO (invoice verification) | **Added** as a posting-pattern marker, derived from a final invoice with an invoice number. Not named as a T-code, because a T-code is a screen somebody drives. |
| GRN (goods receipt) | **Not derived.** Posted against physical receipt into stock; the platform tracks shipment milestones, not receipt events. |
| F-53 / F-58 (payment clearing) | **Not derived.** Payment confirmation lives in SAP; the platform does not know a payment happened — the same reason the `Closed` state has no code path setting it. |
| Reference Key 1 & 2 | **Needs clarification.** Named, never mapped. |
| House Bank | **Needs clarification.** Named, never mapped. |
| Company code 2000 / 3010 | **Not routed.** Nothing on a transaction says which entity a deal belongs to. |

A test fails if Reference Key 1, Reference Key 2 or House Bank appears in the payload, so filling
one in later is a deliberate act rather than a quiet one.

**The DMS sequencing note, per A.5.** The DMS document number is read best-effort and never waited
on: present if the DMS filing has resolved when the SAP payload is built, omitted otherwise, with
nothing going back to add it. The three integration jobs stay independently dispatched. The
consequence — a SAP posting made before its DMS filing completes carries no DMS reference — is
stated in `KNOWN-GAPS.md` §17. If AGFZE's process requires that link on every posting, the two jobs
must be re-sequenced, which is materially larger than this task and should be scoped separately.

### IMPL-010 — OBL-vs-invoice weight discrepancy · **Implemented (detection only)**

A new `LG-01` rule under its own namespace, registered the same way every rule since Step 4 has
been: one evaluator, one threshold row, one exception-mapping row, and **no change to the
orchestrator or the exception hook**.

It is not a restatement of BR-05. BR-05 compares the invoice against the *contract* — what was
agreed. LG-01 compares it against the *bill of lading* — what actually shipped. A load can sit
inside its contractual tolerance and still be billed for a weight the vessel did not carry.

Severity is `acknowledgeable`, not `hard`: a genuine weight difference is a commercial fact a person
settles with a note, not a data error to correct before the transaction may proceed. The message is
directional, naming a debit note or a credit note, because the direction decides which document is
raised. A missing bill of lading is `informational` and not a failure — most of a transaction's life
has no bill of lading yet.

**The platform never generates the note.** Raising one is correspondence committing AGFZE to a
financial claim, in a format nothing specifies. A test fails if `debit_note` or `credit_note`
becomes a generatable document type.

The seeded 1% threshold is this platform's own cautious starting point, **not confirmed by AGFZE** —
chosen to sit below the 5% BR-05 allows against the contract. The reason is written onto the row.

### VERIFY-011 — Backup restore test · **Script written, never executed**

`infra/production/restore-test.sh` restores the most recent successful backup into a throwaway
instance, checks the data genuinely came back — row counts, plus that every approved transaction
still has the approval row behind it, plus the migration revision — and deletes the instance on
every exit path including Ctrl-C.

**It has not been run against real infrastructure**, because that needs a real GCP project (A3).
Until somebody runs it, the restore remains a plan rather than a capability, and `KNOWN-GAPS.md`
says so in those words.

---

## 4. Needs clarification — the questions engineering cannot answer

Addressed to whoever manages the AGFZE relationship. Each is a business decision that was
deliberately not guessed at.

1. **The lone approver.** Self-approval is now refused outright, with no override — deliberately, as
   no requirement describes one. A desk whose only role-eligible approver is also its preparer
   cannot get a transaction approved at all. Operationally that means a second approver must exist.
   *(AF-14 / `KNOWN-GAPS.md` §10)*
2. **The quantity tolerance.** 5% (BRD) or ~3.3% (discovery)? Neither source resolves it. *(AF-22)*
3. **Is B2B in scope?** And if so: the confirmed profit splits and how one is chosen per deal, how
   shared expenses are captured and by whom, and what "loss borne by partner" means operationally.
   *(AF-02)*
4. **Is the amendments chatbot wanted** as an interface over the existing correction-and-resubmit
   flow, or is that flow sufficient? *(AF-03)*
5. **The batch-number field order.** Is it `I` + FY + company, or `I` + company + FY? The worked
   example `I7026-642` fits the second reading and not the first. *(AF-25, corrected)*
6. **Does a Performa invoice need an approval tier above HOD?** Discovery says CEO approval; the
   platform has no such role and one was not invented. *(`KNOWN-GAPS.md` §16)*
7. **The unmapped SAP fields** — Reference Key 1, Reference Key 2, House Bank — and the rule
   deciding company code 2000 versus 3010. *(`KNOWN-GAPS.md` §17)*
8. **Must a SAP posting wait for a completed DMS filing?** If yes, two independently dispatched jobs
   must be re-sequenced. *(`KNOWN-GAPS.md` §17)*
9. **The LG-01 weight tolerance.** 1% is a starting point, not a confirmed figure. *(AF-16)*
10. **Report distribution content.** Is a link sufficient, or does the business need figures *in* the
    message? The platform deliberately puts no commercial figures in an email body or attachment.
    *(`KNOWN-GAPS.md` §7)*
11. **Which carrier, and which API?** `IMPL-018` cannot proceed until AGFZE names one and confirms
    it has or can obtain access. No carrier was selected unilaterally. *(AF-09)*
12. **Azure Blob or GCS?** The PRD names Azure; the entire estate is GCP and the client is written
    against the bucket that exists. *(`KNOWN-GAPS.md` §13)*
13. **The retention period** — per document class if it differs — and whether anything should ever
    be deleted automatically at all, or only archived. Nothing ages out today.
    *(`KNOWN-GAPS.md` §19)*
14. **Is a second AI provider wanted?** Routing to human review when Gemini is unavailable is a
    working degradation; a fallback buys throughput, not correctness. *(`KNOWN-GAPS.md` §8)*
15. **Do the hedging low/high fields belong on the sales side too?** `SalesLeg.fixation_rate` is a
    single bilaterally-agreed price, not a range the market moved through, so the range was not
    duplicated onto it. *(AF-15)*
16. **Are counterparty short codes a display convenience or a downstream identifier?** They are
    derived on read today and change when a name is corrected. *(`KNOWN-GAPS.md` §20)*
17. **Is a graph store wanted at all?** `IMPL-012` is built and switched off. The traceability
    questions it answers are answerable — more slowly — from the relational data already held, and
    standing one up is an ongoing infrastructure commitment. If yes: self-hosted inside the existing
    VPC, which is what the Terraform provisions, or a managed AuraDB, which is a separate vendor and
    a separate data-processing agreement? *(`KNOWN-GAPS.md` §21)*
18. **Does the PRD's Recharts requirement stand?** The charts are purpose-built link-and-readout
    components, and converting them to Recharts would cost the documented drill-through promise and
    the accessible live readout. Recommendation is to update the specification. *(§9)*

## 5. Operational risks raised, not resolved

- **Redis outage behaviour.** Whether the `limits` library's Redis backend fails open (traffic
  passes unlimited) or closed (traffic refused) under a Memorystore outage has not been exercised
  against a real failure. Both are defensible and they are very different on a bad day. Worth a
  deliberate decision before go-live. *(`KNOWN-GAPS.md` §9)*
- **The restore has never been performed.** See `VERIFY-011`. `infra/production/restore-test.sh` is
  written and ready; nobody with real infrastructure access has run it.
- **Never run two pytest sessions against one database.** `conftest`'s session-scoped seed snapshot
  makes a concurrent run able to permanently empty the seeded configuration tables — see §6. It
  cost a full suite run to diagnose and a database rebuild to fix.

---

## 6. Second session

### A correction to the coverage table I was handed

The resume package's coverage table recorded `IMPL-013`, `IMPL-014`, `IMPL-015`, `IMPL-016` and
`IMPL-017` as "reported done in prior session", and instructed me to verify each against the
repository rather than assume. Verified, and the table was wrong: **none of the four buildable ones
is done.** `frontend/package.json` contains no `recharts`, no `framer-motion`, no `cmdk`, no
`@radix-ui/react-accordion` and no `@radix-ui/react-tabs`; there is no onboarding component
anywhere; and `category-tabs.tsx` still has no roving tabindex.

That matches what the first session's own status report said at the time — Part 2 arrived truncated
and I explicitly had not started any of §12. Their true statuses:

| Task | True status |
|---|---|
| `IMPL-013` Recharts | **NOT DONE.** Charts are hand-built SVG; the PRD names Recharts. |
| `IMPL-014` Onboarding walkthrough | **NOT DONE.** No walkthrough exists in any form. |
| `IMPL-015` Accordion | **DONE by scope.** Its revised spec says no action is required; `collapsible-panel.tsx` already implements the behaviour correctly. |
| `IMPL-016` Roving tabindex | **NOT DONE.** Tabs exist with correct ARIA; arrow-key navigation does not. |
| `IMPL-017` Command palette | **NOT DONE.** No ⌘K palette exists. |

None was in this package's §1–§4 task list, so none was built here. They remain outstanding.

### A test-environment fault I caused, and the trap behind it

The first session's final suite reported 117 failures. That was not a code regression: the
`agfze_test` database had been emptied of its seeded `rule_configurations` rows, so every rule
evaluation failed with "no active configuration".

The mechanism is worth recording because it is a trap anyone could fall into. `conftest`'s
`seeded_configuration` fixture snapshots the seeded rows **once per session**, and `clean_tables`
then restores rows in that snapshot and deletes rows outside it. Run two pytest sessions against
one database concurrently and the second can snapshot the table mid-truncation — after which it
deletes everything and, having an empty snapshot, can never restore it. The database is then
permanently broken for every later run.

Fixed by dropping and recreating `agfze_test`. **Never run two suites against the same database**;
the second session used a separate database for targeted runs and never overlapped the full one.

### Dispositions

#### IMPL-018 — First carrier-tracking adapter · **BLOCKED**

No carrier and no API has been confirmed by AGFZE, and the specification is explicit that one must
not be chosen unilaterally. Nothing was built. The existing guard test — which fails if a shipping
line is named in the adapter module — is untouched and still protects that.

The framework around it remains complete: the sweep runs, staleness detection opens real
exceptions, and manual entry is the fully-functional primary path. Registering an adapter is the
whole of the work once a carrier exists.

#### IMPL-019 — Object-storage client · **DONE**

`GoogleCloudStorage` fills in the second `StorageService` implementation behind the unchanged
protocol; `STORAGE_BACKEND=gcs` selects it and no caller anywhere changes. It issues the bucket's
own pre-signed URLs, so on a download the bytes never pass through the API process — something a
mounted bucket cannot do at all.

**GCP rather than the PRD's Azure Blob, flagged rather than silently chosen.** Every piece of
infrastructure this platform has is GCP, including the document bucket the backend's service
account already holds an IAM binding on. An Azure client would have had no bucket to talk to. The
discrepancy is recorded in `KNOWN-GAPS.md` §13; if Azure is confirmed as a hard requirement, this
module is the template and the factory already has the seam.

Production refuses to start with a non-local backend and no `STORAGE_BUCKET`. `google-cloud-storage`
is imported lazily, so a local deployment never constructs a client, and the test suite runs without
the package installed. 13 tests against a fake client — never a real bucket in CI. One of them
asserts the provider's own error message (which can carry a bucket name, project id and signature
fragment) never reaches an API response.

`build_storage_service()` was split out from the cached accessor so backend selection stays
testable — the suite replaces `get_storage_service` wholesale, which left the selection logic
unreachable from a test.

#### IMPL-020 — LME hedging range and LLME · **DONE**

`hedge_low_price` and `hedge_high_price` on `PurchaseLeg`, nullable, via a reversible migration.
Discovery's "LLME" — the lowest LME — is the low end of that same range rather than a third
quantity, so it is `hedge_low_price` and not a second column holding the same number twice.

Capture and display only, as scoped: **no rule fires off either value.** What counts as a tolerable
position inside a day's range is a commercial judgement nobody has stated, and a rule derived from
these would invent it.

**On the sales side: not added, and here is the reasoning rather than a shrug.** `SalesLeg` carries
`fixation_rate`/`fixation_date` — a single price the customer bilaterally agreed, not a range the
market moved through on a day. Those are different kinds of fact, so the range was not duplicated
onto a field that does not mean the same thing. Raised as a clarification rather than decided.

#### VERIFY-021 — Counterparty abbreviations · **DONE**

`counterparty_codes.py`: a customer's name to its first three letters ("DongA" → "DON", the worked
example, asserted directly), a supplier's to the first two letters of each word. Legal forms are
dropped first, including punctuated ones — without that, "Al-Noor Metals L.L.C." abbreviated to
`ALNOMELLC`, six characters of company and three of company form.

**Derived on read, not stored, and this was the design decision.** There is no counterparty
master-data table; a name is free text on a leg. A stored code would go stale the moment somebody
corrected a misspelt supplier, with nothing to notice. A test asserts the code follows a corrected
name. Where that answer stops being sufficient — a stable identifier something downstream keys on —
is raised in `KNOWN-GAPS.md` §20 as its own piece of work, not grown out of a display helper.

15 tests.

#### CONFIG-022 — Batch-number field order · **NEEDS CLARIFICATION, no code change**

The corrected question is documented in `KNOWN-GAPS.md` §18, along with a hazard worth confirming
before anything changes: a batch number is quoted on generated documents, synced to the tracker
workbook, and carried into SAP as the posting's Header Text. Renumbering existing transactions
would break traceability in three systems at once, two of them outside this platform. The safe
default — a corrected order applies to newly allocated numbers only — is stated there.

#### IMPL-023 — Document retention · **DONE (mechanism only, off by default)**

A retention sweep riding the existing periodic worker. Three switches, all defaulting safe:
disabled, no period (`0` means unset, and the sweep refuses to run on it however the flag is set),
and dry run.

Even fully switched on it writes an audit row saying a person should review an aged document. It
does **not** delete an object, delete a row, or move anything between storage classes — and a test
fails if a deletion path appears in the module. Archival to a colder class belongs in a bucket
lifecycle rule in Terraform, where it is reviewable, not in a job that could be misconfigured into
a delete. 9 tests, most of which assert that nothing happened.

#### FIX-024 — Vertex AI fallback · **NEEDS CLARIFICATION, nothing built**

`KNOWN-GAPS.md` §8 now states the decision that has to be made and what turns on it: when Gemini is
unavailable the platform routes to human review, which is a working degradation rather than an
outage — the platform never depended on the model being right, so it does not stop working when the
model is absent. A second provider buys throughput during an outage, not correctness. Building one
on the assumption it is wanted would double the prompt surface, response schema and failure modes
for a path nobody has asked to exercise.

#### CONFIG-025–028 — Activation prerequisites · **DOCUMENTED, externally blocked**

`docs/ACTIVATION-CHECKLIST.md` lists, per integration, exactly what has to be obtained and from
whom, and how to verify it once it arrives. All four need no code change.

Two things in it are worth surfacing here because getting them wrong is expensive:

- **The tracker column map cannot be guessed.** It has to be written by somebody looking at the
  live workbook. Verify against a **copy** first: a wrong map writes real values into the wrong
  columns of a live operational spreadsheet.
- **Entra ID brokering needs a *different* app registration** from the machine-identity one the
  mailbox poller already uses. Conflating them would give the sign-in flow mailbox permissions it
  has no business holding.

---

## 7. Requirement coverage — every task, final status

| Task / finding | Status | Evidence |
|---|---|---|
| Baseline `config.py` fix | **DONE** | Stack could not boot from `.env.example` |
| `FIX-001` segregation of duties | **DONE** | 6 tests |
| `CLARIFY-002` BR-05 tolerance | **DONE — verified, no change** | 5.0% seeded, conflict documented |
| `CLARIFY-003` BR-06 tiers | **DONE — verified, no change** | $1 / $10 match discovery exactly |
| `IMPL-004` report distribution | **DONE** | 19 tests |
| `CLARIFY-005` B2B | **DONE — scaffolding only, as scoped** | 11 tests |
| `CLARIFY-006` amendments chatbot | **DONE — deliberately not built** | `KNOWN-GAPS.md` §15 |
| `IMPL-007` shared rate-limit store | **DONE** | Memorystore; production refuses in-process |
| `IMPL-008` Performa + bank letter | **DONE** | Both real assets; 5 tests |
| `VERIFY-009` SAP payload | **DONE** | 14 tests; 3 fields flagged not guessed |
| `IMPL-010` OBL weight (`LG-01`) | **DONE — detection only, as scoped** | 10 tests |
| `VERIFY-011` restore test | **DONE — script written, never executed** | Needs real infra access |
| `IMPL-012` Neo4j projection | **DONE — built, switched off pending confirmation** | 17 backend + 4 frontend tests |
| `IMPL-013` Recharts | **NOT RECONCILED — spec-update recommendation** | 10 tests added; reasoning in §9 |
| `IMPL-014` onboarding walkthrough | **DONE** | 10 frontend + 5 backend tests |
| `IMPL-015` accordion | **DONE by scope** | Revised spec: no action required |
| `IMPL-016` roving tabindex | **DONE** | 8 tests |
| `IMPL-017` command palette | **DONE** | 9 tests |
| `IMPL-018` carrier adapter | **BLOCKED** | No carrier confirmed; must not be chosen unilaterally |
| `IMPL-019` object storage | **DONE** | 13 tests; Azure-vs-GCP flagged |
| `IMPL-020` hedging range / LLME | **DONE** | Capture and display; no invented rule |
| `VERIFY-021` counterparty codes | **DONE** | 15 tests incl. the worked example |
| `CONFIG-022` batch field order | **NEEDS CLARIFICATION** | No code change; renumbering hazard documented |
| `IMPL-023` retention | **DONE — off by default** | 9 tests; no deletion path exists |
| `FIX-024` Vertex fallback | **NEEDS CLARIFICATION** | Decision documented, nothing built |
| `CONFIG-025`–`028` | **BLOCKED — externally** | `docs/ACTIVATION-CHECKLIST.md` |

**Honest count.** 29 rows. **20 done** — of which two are "verified, no change needed", one is done
by its own revised scope, one (`IMPL-012`) is built but deliberately not switched on, and one
(`VERIFY-011`) is a script nobody has executed. **1 not reconciled** with a written recommendation
rather than a silent deviation (`IMPL-013`). **2 needing a business decision.** **1 blocked** on
AGFZE naming a carrier. **4 externally blocked** on configuration, with the prerequisites written
down. Nothing is silently skipped.

## 8. Verification actually observed

Run at the end of the third session, on a rebuilt `agfze_test`, with no other suite running
against it.

| Check | Result |
|---|---|
| Backend `pytest` | **964 passed, 38 skipped, 0 failed** (`PYTEST_EXIT=0`), 1002 collected |
| Frontend `vitest` | **319 passed**, 29 files |
| `ruff check` | clean |
| `ruff format --check` | clean |
| `tsc --noEmit` | clean |
| `eslint` | clean |
| Migrations `20251201_000012` … `20260215_000017` | each verified `upgrade` → `downgrade` → `upgrade` against real PostgreSQL |

The backend figure is 964 passing against a baseline the original specification described as 571.
Most of that gap is the specification's own undercount — the suite was already ~854 before any of
this work started — and the rest is the ~110 tests added across the three sessions.

**Three defects were caught by tooling rather than by review**, which is worth recording because
each would have been easy to miss reading a diff: the `graph_configured` name collision with
Microsoft Graph, two wrong watermark columns on the sync worker, and `NEO4J_PASSWORD` reaching
`Settings` without being added to the audited credential list — the last by a guard test whose
entire purpose is to fail until somebody has decided how a new secret is held.

**Not verified, and not claimable:** `restore-test.sh` has never been executed against real
infrastructure; none of the four `CONFIG-025`–`028` integrations has been exercised against a real
endpoint; and the Neo4j projection has never run against a real Neo4j — its tests use a fake driver,
which is the right test for this code but is not the same as having stood the store up. All three
are externally blocked rather than overlooked.

## 9. Third session — the last five tasks

Committed first, as recommended: the previous two sessions' work is now six reviewable commits on
`close-audit-gaps` rather than 78 loose files. The repository had one commit and no convention to
follow, so the messages state what changed and why the judgement calls went the way they did.

### IMPL-016 — Roving tabindex · **DONE**

`useRovingTabs` applied to `category-tabs.tsx`: one tab in the page's tab order at a time,
Left/Right to move, Home/End to jump, selection following focus. Horizontal only, because the strip
is a `flex` row — a hook that guessed orientation would be wrong for a stacked one.

**Checked before extending it, as instructed:** the Dashboard's Scrap/FA control is a native
`<select>`, not tabs, so it already has full keyboard support and is out of scope. Two *other*
tablists do share the gap — `new-transaction-tabs.tsx` and `integration-monitor.tsx` — and were
left alone because the task scoped this to `category-tabs.tsx` only. The hook is reusable; applying
it to those two is a small follow-up.

8 tests, driving real arrow/Home/End key events.

### IMPL-013 — Recharts · **NOT RECONCILED — formal specification-update recommendation**

This is the task's documented ALTERNATIVE PATH, taken deliberately rather than as a shortcut.

**These components are not plots.** `bar-chart.tsx` renders a `<ul>` of `<li>`s where each bar is a
full-width Next.js `<Link>` into the filtered queue behind it. `donut-chart.tsx` draws SVG arcs
beside a legend of the same drill-through links. `line-chart.tsx` is a real SVG plot, but its
hovered values are announced through an `aria-live="polite"` region — a text readout, not a visual
tooltip.

**What conversion would cost.** Recharts renders an SVG canvas. It cannot produce list semantics,
cannot make each bar a routable link with a real hit target, and its tooltip tells a sighted mouse
user the value and tells nobody else. The drill-through is not decoration: "every figure links
through to a live, filtered query that reproduces it" is a documented promise of this platform,
written into `reporting.py`'s own model docstring. Converting these would trade a working,
accessible, keyboard-navigable drill-through for conformance to a named library.

**Recommendation:** update the PRD to record that the Dashboard and Analytics charts are
purpose-built link-and-readout components rather than Recharts, and why. If Recharts is genuinely
required, the drill-through and the live readout have to be specified as separate requirements,
because a straight swap loses both.

10 render tests added regardless, as the task asks — covering each chart type with representative
data, the drill-through links, the `role="img"`/`aria-labelledby` labelling, and the live readout.

### IMPL-014 — Onboarding walkthrough · **DONE**

`framer-motion`, a `has_completed_onboarding` flag on `User` with a reversible migration, and a
`POST /users/me/onboarding-complete` endpoint that is idempotent and self-only by construction —
it takes no body at all, so there is nothing a crafted request could point elsewhere.

Three callouts, 240ms eases and no bounce, per the PRD's "unhurried and settled". The approval step
is filtered out for accounts without approval rights rather than shown and explained away.
Dismissing and finishing are the same fact, and both are recorded — showing the tour again to
somebody who skipped it would be the platform arguing with them. The flag is server-owned, so it
cannot reappear on a second device or vanish with a cleared cache.

10 frontend tests, 5 backend tests.

### IMPL-017 — Command palette · **DONE**

`cmdk` behind a `components/ui/command.tsx` wrapper in the same shape as the Radix wrappers beside
it, mounted in the header so ⌘/Ctrl+K works on every authenticated page. It searches transactions,
documents and shipments through their existing list endpoints' `search` parameter — no new search
backend — debounced, in parallel, grouped and labelled by type.

Two details worth recording: server-side filtering only (`shouldFilter={false}`), because cmdk's
fuzzy filter would silently drop rows the API matched on a field the label does not contain; and
one endpoint failing does not empty the palette, which a test covers. Each endpoint applies its own
role and stream scoping, so the palette can only surface what the person could already reach.

9 tests. `ResizeObserver` and `scrollIntoView` are now stubbed in `vitest.setup.ts` — jsdom omits
both and cmdk uses them; stubbing the harness is better than writing a worse component to suit it.

### IMPL-012 — Neo4j graph projection · **BUILT, AND DELIBERATELY SWITCHED OFF**

The task required re-confirming the technology before committing to the infrastructure, and called
that out as distinct from the code-level judgement calls I have been making throughout. So the code
is complete and the commitment is not made: `GRAPH_SYNC_ENABLED` is false, no store is configured,
and the Terraform resource sits behind `enable_graph_projection = false`. Applying the stack today
provisions nothing new. Turning it on is configuration.

What exists: `neo4j_service.py` (client wrapper), `graph_sync_worker.py` (watermark sync over nine
tables, started from `lifespan()` alongside the three existing workers), `GET
/api/v1/transactions/{id}/graph`, a Trace panel on the purchase workspace, and
`make rebuild-graph`.

Four properties are enforced rather than intended, each with a test:

- **No general query function.** The client exposes exactly five methods and a test asserts that
  set, because an internal read model acquires an arbitrary-query surface exactly once — when
  somebody adds a convenient parameter to the one endpoint that reads it.
- **Labels and relationship types are checked against a declared set** before any statement is
  built. They cannot be bound parameters in Cypher, so they are interpolated — and interpolating an
  unchecked string is the one way this module could become an injection surface.
- **Never authoritative.** Nodes carry identifiers and labels only; a test fails if a property named
  `amount`, `rate`, `value`, `price` or `quantity` appears on one.
- **Access is decided against PostgreSQL.** The transaction is loaded through the detail endpoint's
  own visibility check and a caller who cannot see it gets a 404 before the graph is consulted.

The Trace panel renders a grouped list rather than a node-link canvas — the question is "what is
attached to this deal", which reads better as text and is usable by keyboard and screen reader. It
says plainly when the projection is unavailable, because an empty diagram would claim the deal is
connected to nothing.

17 backend tests, 4 frontend tests.

**Two things caught by tooling rather than by review**, both worth recording: `graph_configured`
already meant *Microsoft* Graph, so the Neo4j property is `neo4j_configured` — two properties a
letter apart meaning different integrations is how somebody eventually gates the mailbox poller on
Neo4j being reachable. And two watermark columns were wrong (`EmailMessage.ingested_at`,
`DocumentPack.generated_at`), which an import check surfaced immediately.

### One test deliberately not written

`trace-panel.test.tsx` covers the unavailable, populated, stale-notice and nothing-linked states but
not the rejected-fetch branch: vitest attributes a rejected promise to the test that created it even
after the component has caught it, so that test fails for a reason unrelated to the component. The
branch is three lines and the states that differ in *meaning* are covered. Recorded here rather than
worked around with a mock that would have made the suite green while hiding the gap.

---

## 10. Fourth session — the remaining register

Five items were implementable, seven were business questions engineering cannot answer, and one was
externally blocked. What follows is what each one turned out to be on inspection, which in three
cases is not what the register expected.

### IMPL-001 — CI/CD pipeline · **VERIFIED PRESENT; one step could never have passed**

`.github/workflows/` already carries `ci.yml`, `release.yml` and `rollback.yml`, and they match
what was asked for rather than approximating it: a backend job running ruff, the pytest suite
against a real PostgreSQL service container, a full `upgrade head → downgrade base → upgrade head`
migration cycle on a database created and dropped inside the step, a multi-stage image build and a
check that the built image genuinely *refuses* an unsafe production configuration; a frontend job
running ESLint, a formatting check, `tsc --noEmit`, Vitest, a production build and the
service-worker precache verification against that build's own output; and a `gate` job that uses
`if: always()` plus an explicit result test, so a skipped or cancelled dependency fails the required
check rather than passing silently. Release deploys the two Cloud Run services independently, each
behind a no-traffic revision that must answer its own health probe before traffic shifts. Rollback
reverts one named service's traffic split and states, in the run summary, that it did not and will
not reverse a migration.

Nothing in the workflows was changed. Every command they invoke was confirmed to exist as a
Makefile target or an installed tool before this was concluded.

**But `alembic check` could never pass**, and that is a second pre-existing defect worth its own
entry alongside the `TRACKER_COLUMN_MAP` one from the first session. Three earlier migrations wrote
constraint names their models do not declare, so autogenerate proposed dropping and recreating
seven constraints on every run:

- `containers` carried `uq_containers_transaction_id` for a constraint over
  `(transaction_id, container_number)` — a name that also misdescribed it;
- `reports` carried four doubled `ck_reports_ck_reports_*` names, because migration 8 passed
  `op.f()` a name that already began with `ck_`;
- `rule_exception_mappings` carried two names PostgreSQL had truncated and Alembic had hashed,
  because the model's declared names came to **66 and 64 characters** with the naming convention's
  prefix in front of them, past PostgreSQL's 63-character identifier limit. What the database held
  could never have matched what the model asked for.

Migration 21 renames the first five to what the models declare, and the last two model names are
shortened so that what is declared can actually be stored. **Renames only** — not one predicate,
column, type or index changes, and no rule, query or validation behaves differently: a check
constraint's name is not its condition. `alembic check` reports "No new upgrade operations
detected" for the first time.

This was fixed rather than only reported because the task's own acceptance criterion is that a PR
with a migration failure cannot merge — which requires the gate to be able to pass a good one. A
step that can never go green gates nothing, and a pipeline nobody can get green is a pipeline
people learn to ignore.

### IMPL-002 — Report template configuration · **DONE**

The register described two hardcoded templates. There are three — `daily_operations`,
`monthly_management` and `adhoc_transactions` — and all three moved.

`report_template_configurations` holds a report's structure: which sections it carries, in what
order, which figures go in each, its title, its description and its standing disclosures. The
migration seeds it by serialising the shipped dataclasses rather than by retyping them, so the seed
cannot drift from what the module declares, and `resolve()` hydrates a row back into the same
`ReportTemplate` the renderers already take. At cutover nothing about any report changed; the first
thing that changes is the first thing somebody deliberately changes.

`/admin/report-templates` edits it under the same discipline as every other configuration on this
platform — a mandatory `change_reason` validated in the schema before any handler runs, an
attributed editor, an audit row written in the same transaction. `template_key` and `report_type`
have no field on the update schema at all, because a generated report records which template
produced it and re-pointing one would leave those records claiming a structure the document was
never built to.

**Two refusals worth stating.** A section naming a data block the service does not produce is
rejected at the *edit* rather than at render time — the build does raise on an unknown source,
correctly and far too late, when the report is already scheduled and the failure lands on a worker
instead of on the person who caused it. And a figure the platform does not compute is rejected by
name. Neither is a formatting nicety: they are what stops this screen becoming a way to schedule a
report that cannot be produced.

**What the screen cannot do, by construction:** change a figure. Every number is still computed from
the governed transaction, exception, approval, shipment and posting tables at generation time, and
each still carries the filtered query that reproduces it. 12 backend tests, 7 frontend tests.

### IMPL-003 — Roving tabindex on the remaining two strips · **DONE**

`new-transaction-tabs.tsx` and `integration-monitor.tsx` now use the same `useRovingTabs` hook
`category-tabs.tsx` has used since the third session, with the same integration pattern: one tab in
the page's tab order, Left/Right to move, Home/End to jump, selection following focus, horizontal
only. Both needed their tab element converted to a `forwardRef` component so the hook can hold a
ref to it — the only structural change, and it leaves the rendered markup identical, which matters
because what a screen reader announces was already correct. 14 tests across the two, driving real
key events, mirroring the pattern already proven on the exception queue.

### IMPL-017 — Keycloak ↔ Entra ID scaffolding · **DONE, activation is a data fill**

**Verified against a real Keycloak, not only against the file.** `make realm-import` was run and
the realm was read back through the Admin API: the provider imports as `entra-id`, `enabled=false`,
with all eight role mappers present. That run also surfaced a third pre-existing defect — the
`agfze-admin-api` client's description was **279 characters** against Keycloak's 255-character
column, so a full import failed outright and the container refused to start. It was shortened to
249 characters with the same meaning. Anyone who had run `make realm-import` or `make setup`
against a fresh Keycloak volume would have hit this; nobody had.

The realm export carried **zero** identity providers. It now carries one OIDC provider (`entra-id`)
and eight `oidc-role-idp-mapper` entries, one per platform role, spelled exactly as
`app/core/roles.py` spells them — a mapper producing a name the backend does not recognise grants
nothing and reports nothing, so this is the one place the strings genuinely have to match.

It imports **disabled** and every credential-shaped value is a visible `REPLACE-ME…` placeholder.
That combination is the point: importing this realm changes nothing about how anybody signs in
today, and activating it is a data fill rather than a schema or code change. `infra/keycloak/README.md`
is the step-by-step, including the two things in the app registration itself that a sign-in fails
without — the broker redirect URI, and the `groups` claim switched on in the token configuration,
because every mapper reads that claim and with it off each one matches nothing.

The README states, at length and deliberately, that this must be a **separate** registration from
the machine identity the mailbox poller uses. Conflating them would hand the interactive sign-in
flow `Mail.Read` on a shared mailbox.

### VERIFY-015 — Replying on the inbound thread · **IMPLEMENTED (it did not exist)**

Searched first, as instructed: no reply capability existed anywhere. `graph_service` held
`Mail.Read` and the tracker's Excel writes and had no outbound path, dormant or otherwise.

It exists now, and the shape is the requirement rather than a convenience:

- **Composing reaches no mailbox at all**, on any deployment. It writes a row.
- **Sending is a separate endpoint**, reached only from a request a signed-in person made, with
  their account on the audit trail against the message. There is no worker, scheduler, background
  task or event handler with a route to it — which is why `send` is its own function with its own
  name rather than a flag on `compose`.
- **The disclaimer is not separable.** `compose_body` appends the request reference, the system
  footer and the standing disclaimer, and takes no argument that could omit any of them. The exact
  wording is imported from the notification service rather than retyped, so the three channels
  cannot drift apart.
- **Nothing about the body is inferred.** No model is called. A reply is the desk's own words plus
  facts already on the request.
- **A refused send is recorded as refused.** The row says `failed`, carries the provider's own
  reason, and the endpoint raises — on a session rolled back to its pre-attempt state, so the only
  rows that path commits are the failure and the record of why, in the same ordering the Keycloak
  role override already uses.

The write schema has exactly one field, `message`. There is no recipient, subject or attachment
field, so a reply cannot be redirected to an address nobody on this platform received anything
from: the recipient and the thread come from the captured message, and Graph's `createReply` does
the threading, so the headers that put it in the right conversation are the provider's work rather
than this platform's guess at them.

It ships **off** (`GRAPH_REPLY_ENABLED=false`), as its own switch rather than as a consequence of
the Graph credentials existing — reading a shared mailbox and writing from AGFZE's address are
different decisions, and the second needs `Mail.ReadWrite` and `Mail.Send` on top of the read
scope. With it off a reply is still composed and readable, and the screen says exactly that instead
of offering a button that could only fail. 12 backend tests, 10 frontend tests.

One thing was **not** invented: an approval tier. Discovery asks for "human-approved draft" and does
not say who approves. The explicit send *is* the human approval, and it is recorded; a separate
approver role would have been a business rule this platform made up about who may speak to a
counterparty. Recorded as `KNOWN-GAPS.md` §22 for AGFZE to settle.

### VERIFY-016 — The 3-month LME price basis · **IMPLEMENTED, and deliberately without an average**

`PriceBasis` held `fixed` and `lme_percent` only, so a deal struck against the three-month
quotation was recorded as whichever of the two it most resembled and the distinction was lost at
the point of writing. `three_month_lme` is now a basis in its own right, `infer_price_basis`
recognises it however the phrase is written, and the generated contract states which quotation the
price is struck against.

**No average is computed, and that is the finding rather than a shortfall.** The register asks for
"the average of the daily LME price over the 3 months preceding ETD/ETA". Discovery is explicit
that the exchange has no usable feed and that the three-month price is *entered by hand for the
day* — so this platform holds no daily series to average, and an average of data it does not have
would be an invented price. It records the basis and the percentage struck against it; the price
itself lands in the rate and fixation columns that already exist, entered by the person who read it
off the source. A test asserts the absence, because the absence is the requirement.

**One regression avoided.** `infer_price_basis` now classifies "3-month LME less 6%" as a
three-month deal rather than as a plain percentage, which would have dropped it out of BR-06's
contracted-percentage comparison. Both LME-linked bases are grouped in `LME_LINKED_PRICE_BASES` and
the evaluator tests membership, so a deal subject to that check before is subject to it after.

### The seven clarifications, and the one blocker

`CLARIFY-004` (quantity tolerance), `CLARIFY-005` (invoice-date severity), `CLARIFY-006` (B2B
profit-sharing), `CLARIFY-007` (amendments chatbot), `CLARIFY-008` (Performa approval tier),
`CLARIFY-009` (unmapped SAP fields and company-code routing), `CLARIFY-010` (batch-number field
order), `CLARIFY-012` (Vertex fallback), `CLARIFY-013` (Azure vs GCS) and `CLARIFY-014` (a
reachable `Closed`) were investigated and **nothing was changed for any of them**. Each is a
business decision, each is already recorded in `KNOWN-GAPS.md`, and guessing at one is the failure
mode this whole document exists to avoid. `BLOCKED-011` (a carrier adapter) stays blocked: no
source document names a carrier, and writing a client against an interface nobody has published
would fail on first contact while making the platform look as though it had an integration it does
not have.

One permitted cleanup was taken. BR-08's placeholder said the exception queue "arrives in Step 4",
which stopped being true a long time ago. The behaviour is unchanged — it still reports itself
not-applicable — and the message now says what is actually true: every hard failure is routed to
the queue generically by the governance hook, whichever rule produced it, so a rule of its own here
would be a second and narrower implementation of routing that already happens for all of them.
