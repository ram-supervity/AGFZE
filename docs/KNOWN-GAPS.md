# Known gaps - what AGFZE must confirm before go-live

**Status:** delivered with Step 11, the final build step.
**Audience:** whoever signs this platform off for use with real money.
**How to read it:** every item below is something the platform does *today*, by a default that was
chosen deliberately and is documented in the code that uses it. None of them is a bug, and none of
them is hidden. Each one exists because the business had not confirmed the real answer at the time
it was built, and each one names exactly what has to be confirmed before the default should be
trusted in production.

This is not a wish list and it is not a backlog. It is the set of places where the platform is
currently making a reasonable assumption on AGFZE's behalf, and where a wrong assumption would
show up as a wrong number, a missed obligation or an integration that quietly goes nowhere.

Nothing on this list prevents the platform from running. Several items would prevent it from being
*right*.

---

## Summary

| # | Item | What happens today | Risk if the default is wrong | Who confirms |
|---|---|---|---|---|
| 1 | Quantity tolerance | ±5% | Loads accepted or rejected wrongly | Trading / Finance |
| 2 | Invoice-date policy | Flagged past 3 months, never blocked | Backdated invoices pass with only a note | Finance |
| 3 | India payment-term advisory | An advisory note, no calculation | An interest liability nobody computed | Finance / Legal |
| 4 | Tracker workbook mapping | Unconfigured → prepared for a person | Approved deals never reach the tracker | Operations |
| 5 | SAP endpoint contract | Unconfigured → prepared for a person | Nothing posts to SAP automatically | Finance / IT |
| 6 | DMS endpoint contract | Unconfigured → prepared for a person | Nothing files automatically | IT |
| 7 | Report templates | Three seeded structures, editable with a reason | The reports nobody wanted, and none of the ones they did | Management |
| 8 | Vertex AI fallback | An extension point that fails honestly | No second provider if Gemini is unavailable | IT |
| 9 | Rate-limit counter store | Shared Memorystore; refuses in-process | Behaviour under a Redis outage unconfirmed | IT |
| 10 | Approval segregation of duties | Enforced; self-approval refused | A lone approver cannot approve their own work | Management |
| 11 | Carrier tracking adapters | None; everything tracked by hand | Nothing automatic about shipment status | Operations |
| 12 | `Closed` transaction state | Declared, unreachable | No deal is ever formally closed | Management |
| 13 | Document storage backend | Native GCS client available; mount still default | PRD names Azure; the estate is GCP | IT |
| 14 | B2B profit-sharing model | Tag and filter only; no arithmetic | A commercial model the platform cannot account for | AGFZE / Supervity |
| 15 | Amendments chatbot | Not built; existing flow covers the substance | A requested interface nobody confirmed or dropped | AGFZE / Supervity |
| 16 | Performa invoice approval tier | Routes through `approver_hod` | A document signed off below the tier it needs | Management |
| 17 | Unmapped SAP posting fields | Absent rather than guessed | Postings a person has to complete by hand | Finance / IT |
| 18 | Batch-number field order | `[FY][company]`; unchanged | Batch references that do not match the desk's convention | Finance / Operations |
| 19 | Document retention | Off, no period, dry run | Documents kept for ever, or a wrong period chosen | Legal / Finance |
| 20 | Counterparty short codes | Derived on read, not stored | Codes that change when a name is corrected | Operations |
| 21 | Graph projection | Built; off and unprovisioned | An infrastructure commitment nobody has agreed to | IT / Management |
| 22 | Outbound reply approval tier | The desk that writes it sends it | A message to a counterparty nobody senior reviewed | Management |

---

## 1. The quantity tolerance - ±5%

**What the platform does today.** BR-05 and BR-06 both compare an invoiced quantity against the
contracted figure and fail the transaction if it varies by more than **5%**. The value is a row in
`rule_configurations`, unscoped, and it is what every commodity and both business streams resolve
to. A breach is a hard failure: it opens an exception case owned by the buying desk and it cannot
be acknowledged away at any size, because a load outside tolerance is a commercial fact somebody
has to settle rather than a rounding artefact.

**Why it is 5%.** This platform's discovery material raised two figures and confirmed neither. 5%
was the one stated plainly; approximately **3.3%** was also mentioned as a possible industry
standard, explicitly unconfirmed. 5% is the more permissive of the two, which is the safer default
for a *hard* failure - a tolerance set too tight stops legitimate deals, and a queue of false
exceptions is a queue nobody reads.

**What AGFZE has to confirm.**

- Is the correct figure 5%, 3.3%, or something else?
- Does it differ by commodity? Copper cathode and mixed scrap do not weigh the same way.
- Does it differ between the buying and the selling side?

**How to change it.** `/admin/rules`, one row, with a reason recorded. No release. A
commodity-specific figure is added as a *second* row scoped to that commodity, beside the default,
never by editing the default out from under the transactions it already governs.

---

## 2. The invoice-date policy - three months, and only a flag

**What the platform does today.** IV-01 compares an invoice's extracted date against the current
date. An invoice dated more than **three months** in the past is flagged; so is one dated in the
future. Both are `acknowledgeable`: the preparing desk sees the flag on the validation panel and
clears it on their own record with a stated reason. Neither opens an exception case, and neither
blocks submission outright.

**Why it is only a flag.** This is the most important entry on this list, because the platform is
deliberately doing *less* than the discovery material asked for. That material proposes rejecting a
future-dated invoice outright and flagging or rejecting a backdated one - and says, in the same
breath, that the business has not confirmed either the tolerance or the approval matrix for a
backdated invoice. A hard failure on a policy nobody has agreed would stop real deals on a rule
AGFZE never made, and would be this platform inventing a business rule rather than enforcing one.
So it flags, visibly, and the desk decides.

**What AGFZE has to confirm.**

- How far back may a supplier date an invoice before it is a problem? Three months, or something
  else?
- Should a future-dated invoice be **rejected** rather than flagged? The discovery material says
  reject; nobody has confirmed it.
- **Who approves a backdated invoice?** This is the approval matrix that does not exist. Today the
  preparing desk accepts it themselves. If it should be Finance, or the HOD, or nobody at all, that
  is a decision with no default the platform could sensibly have picked.

**How to change it.** The threshold is `IV-01 / invoice_date_window` on `/admin/rules`, in whole
calendar months. Changing the *severity* from a flag to a block is a one-word code change in
`app/services/rules/invoice_evaluators.py`, deliberately: turning a rule into something that stops
a shipment should be a release with a review, not a form somebody fills in.

---

## 3. The India payment-term advisory - a note, not a number

**What the platform does today.** An India-territory transaction carries an informational note on
its validation panel: Indian payment-term rules can make interest payable on a late settlement to a
registered small or micro supplier, counted from the invoice date, and somebody should check the
counterparty's registration and the agreed terms. That is all it does. It computes nothing.

**Why no calculation.** The liability turns on two facts this platform does not hold: whether the
counterparty is a registered small or micro enterprise, and when payment was actually made. A
computed figure built on neither would be a number that looks authoritative and is not, on a
compliance matter. This platform's governing material only ever asks for an advisory note.

**What AGFZE has to confirm.**

- Should the platform hold a counterparty registration status at all? If it should, that is a new
  field on a counterparty record this platform does not currently have.
- Should it hold a payment date? Payment confirmation lives in SAP today.
- Only if both are yes does a computed liability become a defensible feature.

---

## 4. The Tracker workbook - a complete client pointed at nothing

**What the platform does today.** The tracker sync is a **real Microsoft Graph Excel client**. It
matches a row by a key column, updates it in place, and appends only when it matches nothing. It is
finished. What it does not have is a target: `TRACKER_DRIVE_ID`, `TRACKER_WORKBOOK_ITEM_ID`,
`TRACKER_TABLE_NAME`, `TRACKER_KEY_COLUMN` and `TRACKER_COLUMN_MAP` are all unset.

With them unset, an approved transaction's tracker job reaches `awaiting_manual_action` - honestly
neither a success nor a failure - and an administrator is told it needs a person. The transaction
still reaches `Committed`, once somebody records that they updated the tracker themselves.

**What AGFZE has to confirm.**

- **Which workbook** is the live tracker, in which SharePoint drive?
- **Which sheet and which table** inside it?
- **Which column identifies a row** - the platform assumes a batch number.
- **Which transaction field goes in which column**, as an exact mapping. This is the one that
  cannot be guessed: a column mapping that is wrong writes correct data into the wrong place.

**How to change it.** Environment variables on the API service; `TRACKER_COLUMN_MAP` is JSON.
Deliberately *not* an admin screen - where an approved deal is written should require a deployment
and a review, not a form somebody fills in at four in the afternoon.

---

## 5 and 6. The SAP and DMS endpoint contracts

**What the platform does today.** Both are adapters with a complete, reviewable manual fallback.
Unconfigured - which is how they ship - the job prepares the full payload (SAP) or compiles the
document pack (DMS), reaches `awaiting_manual_action`, and tells an administrator. Nothing is
invented, nothing is guessed at, and nothing anywhere reports a posting that did not happen.

**Why they are unconfigured.** No confirmed API, BAPI, OData service or upload contract for AGFZE's
SAP or DMS exists anywhere in this platform's material. Inventing an endpoint shape would produce
code that looks finished and fails on first contact with the real system.

**What AGFZE has to confirm.**

For SAP:
- The base URL and the exact service path a posting goes to.
- The authentication method - the adapter supports basic credentials and an API key.
- The company code, and whether postings route between company codes (2000 UAE, 3010 Singapore
  were both named; the platform currently carries one).
- The payload schema SAP actually expects.

For the DMS:
- The base URL and upload path.
- The authentication method.
- The repository or folder a pack is filed into.
- The metadata schema that accompanies an upload.

**Until then**, the manual path is the real path, and it is complete: the payload is prepared, the
pack is compiled and downloadable, and an administrator records the reference they got back. That
is an honest workflow, not a stub.

---

## 7. Report templates, and their distribution

**What the platform does today.** Two scheduled reports - a daily summary at 06:00 UTC and a
monthly management report on the 1st at 07:00 UTC - plus an ad-hoc builder. Every one of them
produces a real file, stored and downloadable through the same signed-URL mechanism every other
document uses.

**Distribution now exists, and reaches nobody until somebody configures it.** An administrator can
say, under `/admin/report-distribution` and with a mandatory recorded reason, which roles receive
the daily and/or monthly report and on which channel. Before a rule exists, a scheduled report is
generated, stored and readable and is sent to no one - which is the shipped state, not a fault.

**What is distributed is a link, never the file.** A recipient gets a notification pointing at the
report's authenticated detail page and reads it in the platform. Nothing attaches a report to an
email, and the channel setting on a rule is a *ceiling* on delivery rather than a floor: choosing
"email" permits an email to recipients whose own notification preference is email, and cannot
impose one on somebody who never asked to be emailed.

**Templates are configuration now, not seed data.** `/admin/report-templates` edits which
sections each report carries, in what order, and which figures go in each - with a mandatory
recorded reason and an audit row, exactly as a threshold does. The three structures were seeded
into `report_template_configurations` exactly as they shipped, so nothing about any report changed
at cutover; the first thing that changes is the first thing somebody deliberately changes.

Nothing on that screen can change a *figure*. Every number a report prints is still computed from
the governed transaction, exception, approval, shipment and posting tables at the moment it is
generated, and each one still carries the filtered query that reproduces it. The screen decides
what is asked for, never what the answer is.

**What AGFZE has to confirm.**

- Which reports does management actually want, and what is on them? The three seeded structures
  are a sensible starting point rather than a specification - and confirming them is now an edit
  rather than a release.
- Whether a link is sufficient, or whether the business genuinely needs the figures *in* the
  message. The platform deliberately does not put commercial figures in an email body or an
  attachment, and changing that is a decision about where those figures are allowed to travel -
  not a formatting preference.
- What retention applies to a generated report?

---

## 8. The Vertex AI fallback provider

**What the platform does today.** One AI provider: Gemini, through one dedicated service module.
A `VertexProvider` class exists as a structural extension point and raises an explicit, honest
"not available in this deployment" if anything selects it. It is a seam, not a second
implementation, and it has been that since the intake step.

**Why.** A second provider nobody has asked for is a second set of prompts, a second response
schema and a second failure mode to keep in agreement with the first - for a fallback that has
never been exercised.

**What AGFZE has to confirm - and this one is genuinely a decision, not a defect.**

- Is a fallback provider required at all? If Gemini is unavailable, the platform's behaviour today
  is that extraction fails and the document is routed to human review. That is a working
  degradation rather than an outage: the platform never *depended* on the model being right, so it
  does not stop working when the model is absent - it falls back to the thing it was already built
  to fall back to. A second provider buys throughput during a Gemini outage, not correctness.
- If it is required, Vertex is a drop-in: implement `generate` against the Vertex endpoint, matching
  `GeminiProvider`'s signature and error contract, and set `AI_PROVIDER`. The seam exists precisely
  so that is the whole of the work.

**Nothing was built here, deliberately.** Implementing a second provider on the assumption that one
is wanted would double the prompt surface, the response schema and the failure modes that have to
be kept in agreement - for a path nobody has asked to exercise. The question is put rather than
answered.

---

## 9. Where the rate-limit counters live

**Status: closed.** Production now provisions a shared counter store and refuses to start without
one.

**What changed.** `infra/production` provisions a Memorystore (Redis) instance - 1 GB, `BASIC`
tier, private service access only, AUTH and in-transit encryption on - and wires the API's
`RATE_LIMIT_STORAGE_URI` at it automatically. The application code needed no change at all: the
`slowapi` integration already read that setting and passed it through, which is what made this a
provisioning gap rather than a code one.

**The refusal is the part worth knowing about.** A production process configured with an in-process
store now fails to start, rather than logging a warning. A warning on a start-up line nobody reads
is how a bulk-approval limit ends up five times more permissive than it reads for a year. A
genuinely single-instance deployment can still opt in to per-instance counting by setting
`RATE_LIMIT_ALLOW_IN_PROCESS=true`, which has to be said out loud rather than fallen into.

**Sizing, stated so nobody revisits it as a saving.** The instance holds short-lived integer
counters keyed by user and route - no sessions, no cache, no queue - so the smallest tier is the
correct size rather than a starting point. `BASIC` (no replica) is deliberate too: losing the
counters resets every in-flight window, which is a moment of over-permissiveness rather than a data
loss.

**One operational risk to confirm.** If Memorystore becomes unreachable, the behaviour of the
`limits` library's Redis backend under that failure - whether it fails open (traffic passes
unlimited) or closed (traffic is refused) - has not been exercised against a real outage here. Both
are defensible and they are very different on a bad day. Worth a deliberate decision before
go-live.

---

## 10. Segregation of duties on approvals

**Status: enforced.** This item previously read "not enforced" and described the change as
deferred. It is no longer deferred. `approval_service.decide` now refuses an **approval** by the
account recorded as the transaction's submitter, with a 409 carrying the code
`segregation_of_duties`, and the refusal is reached before any state changes, so a blocked
attempt leaves the task pending, the transaction in `Approval Pending`, and no integration job
behind it. BRD §9.1's maker-checker control is the requirement it implements.

**What is deliberately *not* barred.**

- **A rejection or a request for changes by the submitter.** Sending a transaction back is a
  return to the preparing desk, not a commitment of anything: no posting is authorised and no job
  is raised. Refusing it would only strand work nobody else has picked up.
- **A transaction with no recorded submitter.** `submitted_by_id` is nullable, and a row that
  never went through the submit endpoint has no maker to check the checker against. Barring it
  would refuse an approval on no evidence at all.

The bar reaches the bulk path too, and refuses one row rather than the whole request - the
submitter's own transaction is skipped by name and the rest of the batch still goes through,
which is that endpoint's existing promise about a row the client should have filtered out.

**What AGFZE still has to confirm - one question, and it is an operational one, not a technical
one.** What happens when the only role-eligible approver *is* the submitter, which is a real
situation on a small desk. The platform currently refuses, full stop: it does **not** ship an
override, an admin force-approve, or an escalation path, because no requirement in any of this
platform's material describes one and inventing an override would reopen exactly the control this
item closes. Until AGFZE answers, the operational answer is that a second approver must exist.
The seeded local realm still ships the dual-roled `dual.user` account, which is now what the
refusal is exercised against rather than what it permits.

---

## 11. Carrier tracking adapters

**What the platform does today.** Every shipment is tracked by hand, and that is the fully
functional primary path: recording a position manually is an authenticated, role-gated, audited
write held to exactly the same standard an automated one would be. The sweep still runs, and its
most valuable half needs no carrier at all - it notices a shipment nobody has looked at for longer
than the configured threshold and opens a real, owned exception against it.

**No concrete carrier adapter ships, and a test enforces that.** The registry is empty on a fresh
import and the test suite fails if a shipping line is named in the adapter module.

**What AGFZE has to confirm.** Which carriers, and which of their APIs. `SHIPMENT_CARRIER_ADAPTERS_ENABLED`
is a convenience flag, not a promise: turning it on does nothing until an adapter is registered.

---

## 12. The `Closed` transaction state

**What the platform does today.** `Closed` is a declared status with **no code path that sets it**.
A transaction's lifecycle ends at `Committed`.

**Why.** Closing a deal turns on payment confirmation, full documentation and shipment completeness
- none of which is concretely specified for this platform, and payment confirmation lives in SAP.
The state is declared so the vocabulary is honest about it existing, not so something can quietly
move a transaction into it.

**What AGFZE has to confirm.** What "closed" means operationally, and which of the three conditions
this platform is expected to know about.

---

## 13. The document storage backend

**What the platform does today.** One storage implementation: the local-filesystem one Step 1 built
behind its storage abstraction. No step ever added an object-store client. In production the
document bucket is **mounted** into the API container rather than called through an SDK, so the
same code writes to the same paths and what is behind those paths is durable, versioned and
encrypted with AGFZE's own key.

**Status: a native client now exists.** `STORAGE_BACKEND=gcs` selects a real Cloud Storage backend
behind the unchanged `StorageService` protocol - and it issues the bucket's own pre-signed URLs, so
document bytes no longer pass through the API process at all on a download. The mounted-bucket
arrangement still works and remains the default; switching is one environment variable and no code
change anywhere.

**One documented departure from the PRD.** The PRD specifies **Azure Blob Storage**. Every piece of
infrastructure this platform actually has is GCP - the Terraform stack provisions the bucket, and
the backend's service account already holds an IAM binding on it. A client written against Azure
would have had no bucket to talk to while the one that exists stayed behind a mount, so the client
is written against the store that is there. If AGFZE confirms Azure is a hard requirement, the
existing module is the template and the factory already has the seam; it is a new implementation,
not a redesign.

**What was true before, and is why this was worth doing.** A mounted bucket is not a native client.
Writes are slower than an SDK would be, particularly the page images extraction produces for a
large scanned pack; the consistency model is the mount's rather than the object store's; and a
mount cannot issue a signed URL at all, so every download had to be proxied.

**What AGFZE has to confirm.** Whether that matters at their document volume. If it does, a native
client is a drop-in behind the same abstraction - `STORAGE_BACKEND` already selects between
implementations, and the factory raises rather than guessing for a value it does not have. It is
listed here rather than built now because inventing a second storage backend at the hardening step,
with no measurement saying the first one is too slow, would be exactly the scope creep this step is
told to avoid.

---

## 14. The B2B / profit-sharing purchase model

**What the platform does today.** A purchase can be tagged as a joint B2B deal and carry the
partner's name, and the transaction list can be filtered to B2B or standard deals. That is the
whole of it.

**What it deliberately does not do.** There is no profit-split percentage, no expense-sharing
calculation and no loss-allocation rule anywhere in the data model, the rule engine or the UI - and
a test in `test_b2b_scaffolding.py` fails if a column matching any of those names is added, so
putting one in has to be a deliberate act rather than a quiet one.

**Why.** Discovery described the model in real detail - full advance against a provisional invoice,
a negotiated split, shared expenses, a loss borne by one side - but the only figures anywhere are
illustrative examples (50/50, 60/40, 65/35). Nothing says how a split is chosen for a given deal,
how a shared expense is captured or by whom, or what a borne loss means operationally. Columns for
those would be a guess with a schema around it, and would have to be migrated a second time on the
day somebody confirms the real shape.

**What AGFZE has to confirm.**

- Is B2B still in scope for this delivery, or was it descoped? It appears in the discovery material
  and in neither the BRD nor the PRD, and nothing anywhere says it was dropped.
- If in scope: the complete set of split arrangements, and how one is selected per deal.
- How shared expenses are captured, and by which desk.
- What "loss borne by the partner" means operationally - who records it, and against what.

---

## 15. The amendments chatbot

**What the platform does today.** Nothing by that name, and deliberately no new code.

**Why.** The substance the discovery material asked for - capture what changed, draft it, route it
for approval with a summary - is already what the platform does: a field correction through
`PATCH /transactions/{id}/fields` carries a mandatory reason, records provenance against the AI's
original value, re-runs validation synchronously, and re-submission puts it in front of an approver
with the change visible. A chatbot would be a different *interface* onto that same path, not a new
capability, and building a conversational UI on an unconfirmed requirement is how a platform grows
a surface nobody asked to maintain.

**What AGFZE has to confirm.** Whether a chatbot-style interface is genuinely wanted as a layer on
top of the existing flow, or whether the existing correction-and-resubmit path is sufficient. Like
the B2B model above, this appears in the discovery material and in neither the BRD nor the PRD,
with nothing anywhere saying it was dropped.

---

## 16. The Performa invoice's approval tier

**What the platform does today.** A Performa invoice can be generated as a reviewed draft, and it
routes for approval through the existing `approver_hod` tier exactly as every other draft does.

**Why that is an assumption, not a decision.** Discovery says a Performa invoice "requires CEO
approval". This platform has no `ceo` role - its approving tier is `approver_hod`, with `admin`
alongside - and inventing one would change who can sign off what on the day the platform goes
live. That is not a decision a template file should make on AGFZE's behalf, so the existing tier is
used as an explicit interim default and the question is recorded here instead.

**What AGFZE has to confirm.** Whether a Performa invoice genuinely needs an approval tier above
the HOD. If it does, that is a new role in Keycloak, a new value in `PlatformRole`, and a
value-or-document-type-dependent approval route - a real piece of work, and one worth scoping
deliberately rather than discovering late.

---

## 17. The SAP posting fields nobody mapped

**What the platform does today.** The SAP payload carries the three posting fields discovery
mapped outright - Assignment (the invoice number), Header Text (the batch number) and Business Area
(1070, configurable) - plus the DMS document number where the filing has already resolved, and a
posting-pattern marker for an invoice-verification posting.

**What it deliberately leaves out.** **Reference Key 1**, **Reference Key 2** and **House Bank**.
All three were named in discovery as fields the posting carries, and none was mapped to a value -
no source document anywhere says what belongs in them. A plausible-looking guess in an accounting
document is worse than a gap: the gap is visible to whoever completes the posting, and the guess is
not. A test fails if any of the three appears in the payload.

Also absent: a **goods-receipt** or **payment-clearing** posting pattern. A goods receipt is posted
against physical receipt into stock, which this platform tracks as shipment milestones rather than
as a receipt event; F-53/F-58 clear a payment, and payment confirmation lives in SAP. Deriving
either would be an accounting judgement dressed as a data transformation.

**The company-code split is still unrouted.** AGFZE routes between 2000 (UAE) and 3010 (Singapore);
nothing on a transaction says which one a deal belongs to, so the platform never picks one and
`SAP_COMPANY_CODE` stays a single configured value.

**One sequencing question worth a deliberate answer.** The DMS document number is read
*opportunistically*: if the DMS filing has resolved by the time the SAP payload is built, it is
included; if not, it is omitted and nothing goes back to add it later. That is deliberate - the
three integration jobs are dispatched independently and no target system waits on another, which is
load-bearing. But it means a SAP posting made before its DMS filing completes carries no DMS
reference. **If AGFZE's accounting or audit process requires that link on every posting, the two
jobs have to be re-sequenced** - a materially larger change than this field, and one to scope on
its own rather than fold in.

**What AGFZE has to confirm.** The mapping for Reference Key 1 and 2 and the House Bank; whether a
SAP posting must wait for a completed DMS filing; and the rule that decides company code 2000
versus 3010.

---

## 18. The batch-number field order

**What the platform does today.** `batch_prefix()` assembles `I` + the financial year's last two
digits + the two-digit company code, giving `I2626-…` for a deal opened in the 2026 financial year
with the default company code `26`.

**Why that is in question.** Discovery's own worked example is `I7026-642`. Read against the format
above, that is financial year `70` and company `26` - and no plausible year yields `70`. Read the
other way round - company `70`, financial year `26` - it fits a 2026 deal exactly, and `70` echoes
the "Business Area 1070" named elsewhere in the same discovery material. The company-code *value*
is not the problem; an earlier audit note said it was, and that was wrong. The open question is
**field order**.

**What AGFZE has to confirm.** Which order is correct: `[FY][company]` or `[company][FY]`.

**And, separately, a hazard worth confirming before anything changes.** If the order does need
reversing, the code change is small and contained - one line in `batch_prefix()`. What is *not*
small is what happens to batch numbers already issued. A batch number is quoted on generated
documents, synced to the tracker workbook, and carried into SAP as the posting's Header Text.
Renumbering existing transactions would break traceability in three systems at once, and two of
them are outside this platform. **Do not renumber anything without an explicit, separate
confirmation that doing so is both safe and wanted**; the safe default is that a corrected order
applies to newly allocated numbers only, and that existing ones stand.

---

## 19. Document retention

**What the platform does today.** Nothing ages out. A retention sweep exists, rides the periodic
worker that already runs, and is **off, with no period, in dry run** - three separate switches, all
defaulting to the safe side.

**Why nothing was chosen.** The BRD asks for a retention policy and says in its own words that the
period is AGFZE's to confirm. A default invented here would be a number nobody agreed to, quietly
ageing out trade documents - and unlike a wrong threshold, that is not a decision anybody can
reverse afterwards. `DOCUMENT_RETENTION_DAYS=0` means *unset*, not "immediately", and the sweep
refuses to run on it however the enable flag is set.

**What it does even when fully switched on.** It writes an audit row per aged document saying a
person should review it. It does not delete an object, does not delete a row, and does not move
anything between storage classes - a test fails if a deletion path appears in the module. Archival
to a colder storage class belongs in a bucket lifecycle rule in Terraform, where it is reviewable,
rather than in a job that could be misconfigured into a delete.

**What AGFZE has to confirm.** The retention period, per document class if it differs; whether
anything should ever be deleted automatically at all, or only ever archived; and who reviews what
the sweep flags.

---

## 20. Counterparty short codes, and the master-data question behind them

**What the platform does today.** A customer's name abbreviates to its first three letters
("DongA" gives "DON") and a supplier's to the first two letters of each word, dropping the legal
form ("Emirates Metal Trading LLC" gives "EMMETR"). Both are computed on read and shown beside the
name on the transaction list.

**Derived rather than stored, deliberately.** There is no `Customer` or `Supplier` table on this
platform; a counterparty is a free-text name on a leg. Storing a generated code in a column beside
the name would create a second source of truth that goes stale the moment somebody corrects a
misspelt supplier, with nothing to notice it had. Computing it on read cannot drift.

**Where that answer stops being good enough.** A derived abbreviation is fine for display. It is
**not** a stable counterparty identifier: correct the name and the code changes, which is exactly
what a downstream system keying on it would not tolerate. If AGFZE needs codes that survive a name
correction - or one counterparty recognised across the deals it appears on - that is a counterparty
master-data table, which is a real piece of work worth scoping on its own rather than growing out
of a display helper.

**What AGFZE has to confirm.** Whether the codes are a display convenience or an identifier
anything downstream depends on.

---

## 21. The graph projection - built, and switched off

**What the platform does today.** A Neo4j traceability projection exists in full: a sync worker
that keeps it current from the relational store, one bounded read endpoint
(`GET /api/v1/transactions/{id}/graph`), a Trace panel on the purchase workspace, and
`make rebuild-graph` to rebuild it from scratch. **All of it is off.** `GRAPH_SYNC_ENABLED` is
false, no store is configured, and the Terraform resource is behind
`enable_graph_projection = false`.

**Why it is off rather than running.** Standing up a graph database is an ongoing infrastructure
commitment - a machine, a backup story, a patching story - and that is AGFZE's decision rather than
a default to inherit. The code was written so switching it on is configuration, not a project.

**What it is, and what it must never become.** A derived, rebuildable read model. Every value it
holds is read from PostgreSQL first; nothing anywhere makes a decision from it; and a test asserts
its client exposes no general query function, because an internal read model acquires an
arbitrary-query surface exactly once - when somebody adds a convenient parameter to the one
endpoint that reads it. If the two stores disagree, the relational one is right and the projection
is stale, which is a rebuild rather than an incident.

**One known wrinkle if it is enabled.** Supplier and Customer nodes are keyed by the counterparty
*name*, because there is no counterparty table to key them by. Correct a misspelt supplier and the
projection gains a second node until the next rebuild. That is the same gap as item 20, seen from a
different angle, and it resolves the same way.

**What AGFZE has to confirm.** Whether a graph store is wanted at all, given that the traceability
questions it answers are answerable - more slowly - from the relational data the platform already
holds; and if so, whether self-hosted inside the existing VPC (what the Terraform provisions) or a
managed AuraDB, which is a separate vendor and a separate data-processing agreement.

---

## Also worth knowing, though not gaps

These are deliberate design decisions rather than unconfirmed defaults. They are listed because
somebody reading the list above will reasonably ask about them.

- **Nothing is ever sent to a customer or counterparty automatically.** A generated sales document
  is stored and opened by a person. There is no code path that emails one, and a test asserts that
  the only module able to reach an SMTP relay is the notification service - which sends a one-line
  summary and a link, and cannot attach a file.
- **Offline support is read-only, permanently.** A mutating action taken with no connection is
  refused and told to the user plainly. It is never queued for later replay, because a queued
  approval arriving hours later against a record that has moved on is worse than a refused one.
- **Two configuration areas deliberately have no admin screen**: the tracker/SAP/DMS endpoint
  targets (infrastructure - a deployment and a review) and the rule-to-exception-category mapping
  (seed data deciding which desk owns which failure). Each is reachable, by a deployment, by
  somebody who meant to.
- **Replying to a counterparty is possible, and is never automatic.** The platform can answer a
  broker or a supplier on the thread their message arrived on. Composing a reply reaches no mailbox
  at all; sending it is a separate call a signed-in person makes, recorded against their account.
  There is no worker, scheduler or event handler with a route to the send path, and the capability
  ships switched off (`GRAPH_REPLY_ENABLED=false`) because reading a shared mailbox and writing
  from AGFZE's address are different decisions - see **#22** below.
- **Every threshold in the platform is a database row**, not a literal. A rule with no active
  configuration reports itself unconfigured and blocks - with the single, documented exception of
  IV-01 above, which flags instead, because an unconfirmed policy must not be able to stop a desk
  from working.

---

## 22. Who approves a reply going out over AGFZE's address

**What the platform does today.** A desk user - Purchase, Sales, FA, Logistics or Admin, the same
set that may correct a request's category - composes a reply and sends it. Composing writes a draft
and reaches no mailbox; sending is a separate, explicit call, and the account that made it is on
the audit trail against the message. The approver is deliberately *not* in that set, for the same
reason they are not in the correction set: they review and sign off, and are not the corresponding
party.

**The reference and the standing disclaimer are appended by the server**, not by the form, so there
is no path that produces a reply without them and the desk reads exactly what will go out before it
goes.

**Why there is no separate approval tier.** Discovery asks for a reply to go out "initially via
human-approved draft" and does not say who approves it. The platform treats the explicit send as
the human approval - which is what "never automatic" actually requires - rather than inventing an
approver role no source document names. Inventing one would have been a business rule this platform
made up about who may speak to a counterparty.

**What AGFZE has to confirm.**

- Is the desk's own send sufficient, or does a reply over AGFZE's address need a second person -
  and if so, which? If the answer is the HOD, it is a small change: the send endpoint's role gate,
  and the existing approval queue it would route through.
- Whether the standing disclaimer, written for AI-derived content on screen, is the right thing to
  print under a reply a person wrote themselves. It is there today because every reply is composed
  inside a workspace built on extracted data; a separate outbound wording would be a content
  decision, not an engineering one.

**Until either is confirmed**, `GRAPH_REPLY_ENABLED` stays false and nothing leaves at all.

---

## Before go-live: the short version

1. Confirm the quantity tolerance (**#1**) - it is the one that changes whether real loads pass.
2. Confirm the invoice-date policy and its approval matrix (**#2**) - the platform is currently
   doing less than was asked, on purpose, and says so.
3. Point the tracker at a real workbook, with a real column map (**#4**) - otherwise every approved
   deal needs a person.
4. Decide whether SAP and DMS are automated for go-live or worked by hand (**#5**, **#6**). Either
   answer is workable; the platform behaves honestly under both.
5. Rotate every credential off its placeholder and run `infra/production/verify-production.sh` -
   it fails the sign-off if the database password is still the value Terraform created.
6. Confirm there is a second role-eligible approver for every desk (**#10**). Self-approval is
   now refused outright, so a desk whose only approver is also its preparer cannot get a
   transaction approved at all - and there is deliberately no override.
7. Run `./infra/production/restore-test.sh <project-id>` once, before go-live. It restores the most
   recent backup into a throwaway instance, checks the data genuinely came back - row counts, plus
   that every approved transaction still has the approval row behind it - and deletes the instance
   afterwards. **It has never been executed against real infrastructure**, because doing so needs a
   real GCP project; the script exists and is ready, and until somebody runs it the restore is
   still a plan rather than a capability. Record the date of the run: a restore that worked six
   months ago is evidence about six months ago.
