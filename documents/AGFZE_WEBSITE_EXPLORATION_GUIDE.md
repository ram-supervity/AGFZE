# AGFZE Command Centre — Visual Website Exploration Guide

**How to use this file:** every box below is a screen you can actually open. Every arrow is a click. Every table row tells you exactly what to type. Open the app at **http://localhost:3000**, keep this guide open beside it, and start at **Walkthrough A**. By the end you will have clicked every page, typed into every form, and seen every screen the system can show.

> **No theory. Only: open this → see this → type this → click that → land there.**

---

## 0. Legend (read once — used on every page)

**Wireframe symbols** (the ASCII boxes are drawn to mirror the real screen layout):

```
┌─────────────────────────────┐   a panel / card on the page
│  LABEL                      │
│  [ input box          ]     │   [ ] = a text field / dropdown you type into
│  ( Button )                  │   ( ) = a clickable button
└─────────────────────────────┘
▶  = click this / this is an action        ➜  = takes you to this page
🔒 = role-locked (you won't even see it without that role)
🟢🟠🔴 = green / amber / red badge         ⏳ = a background job runs (progress bar)
```

**Status badges you will see everywhere** (these are the spine of the whole app — a transaction moves left→right):

```
Received → Classified → Extracted → Matched → Validation Pending
   │                                              │
   │                                         ┌────┴─────┐
   │                                      pass         fail
   │                                         │          ▼
   │                                         ▼      🔴 Needs Review / Exception
   │                                   Approval Pending     │ (fix it)
   │                                         │             └─► back to Validation
   │                            ┌────────────┼────────────┐
   │                       Approve        Reject      Request Changes
   │                            ▼            └──────────────► back to desk
   │                       Approved
   │                            ▼
   │                   Integration Pending  (SAP + DMS + Tracker jobs)
   │                            ▼
   │                       Committed → Closed
   └─(duplicate)→ Cancelled / Duplicate
```

**Who logs in (local test accounts — password is always `Passw0rd!`):**

| Login username | Role badge | Use this person for |
|---|---|---|
| `purchase.user` | Purchase | Inbox, upload, extraction, matching, submit deals |
| `sales.user` | Sales | Sales contracts/invoices, price fixation, drafts |
| `fa.user` | FA | FA stream (same screens, different fields) |
| `logistics.user` | Logistics | Shipments, containers, milestones, issues |
| `finance.user` | Finance | Invoice-value / tolerance exceptions |
| `hod.approver` | Approver (HOD) | 🔒 Approvals queue — the checker |
| `admin.user` | Admin | 🔒 Admin: users, rules, document types, integrations, audit |
| `auditor.user` | Auditor | 🔒 Audit explorer (read-only) + export |
| `dual.user` | Purchase + Approver | Proves you still **cannot approve your own deal** |

> In production the login is a **“Sign in with Microsoft”** button. In the local test realm you get the Keycloak username/password box instead — same result.

---

## 1. The whole site at a glance

### 1.1 The sidebar (left, on every signed-in page)

This is your map. Items with a 🔒 only appear for that role. The little number badges on **Exceptions** and **Approvals** are live counts.

```
┌──────────────────────────────┐
│  ◆ AGFZE COMMAND CENTRE      │  ◄── wordmark + breadcrumb (top bar)
├──────────────────────────────┤
│  🔍  Search…   (Ctrl/⌘+K)    │  ◄── command palette: jump to anything
│                              │
│  ▸ Dashboard                 │  ➜ /dashboard
│  ▸ Inbox                ③    │  ➜ /inbox        (③ = new items)
│  ▸ Transactions              │  ➜ /transactions
│  ▸ Documents                 │  ➜ /documents
│  ▸ Exceptions           🔴5  │  ➜ /exceptions
│  ▸ Approvals 🔒         🟠2  │  ➜ /approvals     (Approver/HOD only)
│  ▸ Shipments                 │  ➜ /shipments
│  ▸ Analytics                 │  ➜ /analytics
│  ▸ Reports                   │  ➜ /reports
│  ▸ Admin 🔒                  │  ➜ /admin          (Admin only)
│                              │
│  🔔 bell   👤 avatar ▾        │  ◄── top-right of the top bar
└──────────────────────────────┘
```

**Top bar (fixed, every page):** left = wordmark + “you are here” breadcrumb · centre = global search · right = 🔔 bell (unread count, opens a preview popover) · role badge · 👤 avatar menu → **Profile / Settings / Sign out**.
**Footer** (on dashboard & lists, not inside workspaces): `© AGFZE Command Centre` + links to Disclaimer/Privacy/Terms + the reminder *“AI-extracted data must be verified before approval.”*

### 1.2 The complete page map (all 36 screens)

```
PUBLIC (no login)                     AUTH GATES
─────────────────────────             ─────────────────────────────
/ ............... landing            /signin ....... starts login
/disclaimer                           /signout ...... ends session
/privacy                              /offline ...... shown if network dies
/terms                                (auth-error) .. bad credentials
                                      (unprovisioned) no role → "contact IT"

SIGNED-IN (the app shell)
────────────────────────────────────────────────────────────────────
/dashboard ............... role home (KPI tiles + charts)
│
├─/inbox .................. classified email/document queue
│   └─/inbox/upload ....... drag-and-drop intake form
│
├─/transactions .......... every deal, filterable list
│   ├─/transactions/new ... multi-step manual deal form
│   ├─/transactions/purchase/[id] ... PURCHASE workspace (split view)
│   ├─/transactions/sales/[id] ...... SALES workspace (+ draft)
│   └─/transactions/fa/[id] ......... FA workspace
│
├─/documents ............. all documents, searchable
│   └─/documents/[id] ..... DOCUMENT REVIEW split view (confirm here)
│
├─/exceptions ............ queue by category/owner/age
│   └─/exceptions/[id] .... failing rule + resolve form
│
├─/approvals 🔒 .......... ranked queue (HOD)
│   └─/approvals/[id] ..... decision screen (approve/reject)
│
├─/shipments ............. container/B/L board
│   └─/shipments/[id] ..... milestone timeline + log-issue form
│
├─/analytics ............. KPI charts
│
├─/reports ............... scheduled + past reports
│   ├─/reports/builder .... ad-hoc report form
│   └─/reports/[id] ....... report viewer (click a number ➜ transactions)
│
├─/notifications ......... bell feed
├─/settings .............. profile + notification toggles
│
└─/admin 🔒
    ├─/admin/users ............... assign roles
    ├─/admin/rules ............... thresholds/tolerances
    ├─/admin/document-types ...... field schemas per doc/territory
    ├─/admin/integrations ........ SAP / DMS / Tracker job monitor
    ├─/admin/audit ............... full event log + CSV export
    ├─/admin/report-distribution . who gets which report
    └─/admin/report-templates .... what each report contains
```

### 1.3 How one deal connects every page (the click-map to memorise)

A single batch number is the thread. From any one of these screens you can jump to the others — they all look at the **same transaction**:

```
        /inbox (email arrives)
           │ click row
           ▼
   /documents/[id]  ◄── confirm extraction HERE (matching unlocks)
           │ confirmed
           ▼
 /transactions/purchase/[id]  ◄── fix fields, see validation, submit
        │          │
   fail  │          │ pass → Submit
        ▼          ▼
 /exceptions/[id]   /approvals/[id] 🔒 (HOD)  ──reject──► back to workspace
        │ resolve       │ approve
        └──────►────────┤
                        ▼
            /admin/integrations (SAP·DMS·Tracker jobs)
                        │
                        ▼
                 /shipments/[id] (container milestones)
                        │
   every action above is written to ──► /admin/audit  (auditor)
                        │
                   /reports/[id] (figures click ➜ back to the deal)
```

---

## 2. FIRST 5 MINUTES — sign in and land

**Open http://localhost:3000.**

```
┌────────────────────────────────────────────┐
│        ◆ AGFZE COMMAND CENTRE              │
│   Your purchase, sales & logistics work    │
│   now starts here instead of Outlook+Excel │
│                                            │
│            (  Sign in with Microsoft  )    │   ➜ /signin → Keycloak
│                                            │
│   Disclaimer · Privacy · Terms             │
└────────────────────────────────────────────┘
```

- Click **Sign in**. You land on the Keycloak login (local realm).
  - **Username:** `purchase.user`  **Password:** `Passw0rd!`
- ✅ Correct ➜ you land on **/dashboard**, and a 3–4 step tooltip walkthrough pops up: *“this is your inbox”* → *“this replaces the Loading Sheet”* → *“this is where the HOD signs.”* Click through/skip it (it calls onboarding-complete).
- ❌ Wrong password ➜ **auth-error** screen, inline message, back to sign-in.
- ⚠️ Account with no role ➜ **unprovisioned** screen: *“Your account isn’t provisioned for the Command Centre — contact IT.”* (You won't hit this with seeded logins.)
- Session expires later ➜ silent refresh; only if that fails do you see the login again.

**First-login profile blip (Stage 4):** name/email are shown read-only (they come from the identity provider); you can set your **notification channel** and a **default queue filter** (“Scrap only” vs “Scrap + FA”) — done properly on **/settings** (Page 31).

---

# PAGES

---

## Page 1 — Dashboard   `/dashboard`

**Who:** everyone (numbers are role-scoped). **Arrives from:** login, sidebar, logo click, “Back to dashboard”.

```
┌─ Dashboard ──────────────────────── [Scrap|FA] [Last 30 days ▾] ┐
│ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐                       │
│ │ Open   │ │Excep-  │ │Pending │ │Ship-   │   ◄── KPI tiles        │
 │ │ deals 5│ │tions 5 │ │approv 2│ │ments 4 │     (click ➜ filtered │
 │ └────────┘ └────────┘ └────────┘ └────────┘      queue)          │
│ ┌─────────────── donut: status mix ──────────────┐                 │
│ ├─────────────── bar: exceptions by category ────┤                 │
│ └─────────────── line: turnaround trend ─────────┘                 │
│ [View all] per widget          (data age: served 12s ago)          │
└────────────────────────────────────────────────────────────────────┘
```

**What you do here:** you don't type anything — it's the launchpad.
- **Click any tile or chart slice** ➜ jumps to that filtered queue:
  - “Open deals” ➜ `/transactions` · “Exceptions” ➜ `/exceptions` · “Pending approvals” ➜ `/approvals` 🔒 · “Shipments” ➜ `/shipments`.
- Stream toggle **Scrap | FA** and date picker re-filter everything.

> 💡 Log in as `hod.approver` vs `purchase.user` and reload — the numbers differ, because scoping is applied per role.

---

## Page 2 — Inbox / Request Queue   `/inbox`

**Who:** everyone; intake actions for Purchase/Sales/FA. **This is where work arrives.**

```
┌─ Inbox ────────────────────────────────────────────────┐
│ [Category ▾] [Stream ▾] [Date range] [☑ below-threshold] │  ◄─ filter bar
│                                  ( Upload documents )  ➜ /inbox/upload
├──┬────────┬───────────────┬──────────┬──────┬──────┬─────┤
│  │ Sender │ Subject       │ Category │ Conf.│ Att. │State│
│  │ Emirates│ Deal confirm… │🟢purchase│ 96%  │  3   │Extr.│ ◄─ click row
│  │ Maersk │ B/L for DEMU… │🟠logistics│ 71% │  1   │Review│
└──┴────────┴───────────────┴──────────┴──────┴──────┴─────┘
```

**Fields/filters you set:**

| Control | What to pick / example |
|---|---|
| Category dropdown | `purchase` / `sales` / `fa` / `logistics` / `approval` / `follow_up` / `informational` / `exception` |
| Stream dropdown | `scrap` or `fa` |
| Date range | e.g. `01 Aug 2026 – 29 Aug 2026` |
| ☑ below-threshold | tick to see only low-confidence items needing a human |

**Click a row** ➜ opens **either** the Transaction Workspace **or** **/documents/[id]** (Document Review), depending on the row type.

**“Correct category” inline action** (the AI mis-classified something):
1. Click the category badge / “Correct”.
2. Pick the right category.
3. **Reason box appears — required**, e.g. type: `This is a bill of lading, not a purchase invoice`.
4. Save ➜ category updates, reason is audit-logged, and it re-routes to the right workspace.

**( Upload documents )** button ➜ **Page 3**.

---

## Page 3 — Manual Intake / Upload   `/inbox/upload`

**Who:** 🔒 Purchase/Sales/FA. Use this instead of the mailbox (deals with no email, or backfilling files). This is the fastest way to test the whole pipeline.

```
┌─ Upload documents ─────────────────────────────────────┐
│   ╔══════════════════════════════════════╗             │
│   ║   📄  Drop files here or click browse ║  ◄─ drag zone│
│   ║   PDF · DOCX · XLSX · CSV · JPG · PNG ║             │
│   ╚══════════════════════════════════════╝             │
│   Stream *      [ Scrap (scrap)        ▾ ]              │
│   Doc type hint [ Auto-detect (AI)     ▾ ]  (optional)  │
│                                                        │
│   sample-supplier-invoice.docx   ████████ 100%  ( × )   │
│                                                        │
│              ( Upload & classify )     ( Cancel )       │
└────────────────────────────────────────────────────────┘
```

**Fields & exactly what to enter:**

| Field | Enter | Notes |
|---|---|---|
| File(s) | drag `sample-supplier-invoice.docx` (or a real PDF) | max **25 MB** each; wrong type is refused with a red banner |
| **Stream \*** | `Scrap` | required |
| Doc type hint | leave `Auto-detect` (AI overrides if confident), or choose `Supplier Invoice` | optional |

**Click ( Upload & classify )** ➜ ⏳ progress bars, then the **same pipeline as email intake** runs: magic-byte type check → store → classify → extract. You get a link to the **new Request**.

**After it finishes:**
- ✅ accepted ➜ a row appears in **/inbox** (and a notification for the desk).
- 🚫 `.exe`/spoofed file ➜ **415** red banner “file type not accepted.”
- 🚫 > 25 MB ➜ **413** “file too large.”
- 🚫 empty file ➜ **400** “file is empty.”

Use the two ready files in `test-fixtures/`: **sample-supplier-invoice.docx** (classifies `purchase`) and **sample-bill-of-lading.docx** (classifies `logistics`).

---

## Page 4 — Transactions List   `/transactions`

**Who:** everyone. Every deal across all streams.

```
┌─ Transactions ──────────────────────────────────────────────┐
│ [Search batch/party] [Stream▾] [Status▾] [Date]   ( + New ) ➜ /transactions/new
├──┬────────────┬─────────────┬──────┬───────────┬──────┬─────┤
│  │ Batch      │ Counterparty│Stream│ Status    │Value │ Ship│
│  │ TEST-I2626-01│ Emirates… │scrap │🟠Validatn │199k  │ —   │  ◄ click
│  │ DEMO-I2626-4 │ Sample…   │scrap │🔵Approval │225k  │ 🟢  │
└──┴────────────┴─────────────┴──────┴───────────┴──────┴─────┘
                                  ◂ 1 – 20 of 34 ▸
```

| Control | Example |
|---|---|
| Search | type `I2626` or a party name |
| Stream | `scrap` / `fa` |
| Status | `Extracted` / `Matched` / `Validation Pending` / `Approval Pending` / `Integration Pending` / `Committed` / `Exception` |

**Click a row** ➜ the stream-specific workspace:
`/transactions/purchase/{id}` · `/transactions/sales/{id}` · `/transactions/fa/{id}`.

**( + New )** ➜ **Page 5**.

---

## Page 5 — New Transaction (manual)   `/transactions/new`

**Who:** any desk — for a deal with **no inbound email** (e.g. an FA deal agreed by phone). Multi-step form with a progress stepper.

```
┌─ New transaction            ●Step 1 ─ ○Step 2 ─ ○Step 3 ──────┐
│ STEP 1 — Stream                                                │
│   Stream *   ( Scrap )  ( FA )                                 │
│                                              ( Next )          │
│ STEP 2 — Basics                                                │
│   Counterparty name * [ Emirates Copper Trading LLC          ] │
│   Contract reference  [ SC-2026-UAE-118                      ] │
│   Batch number        [            ]  ← blank = system proposes│
│                                              ( Next )( Back )  │
│ STEP 3 — Documents (optional now)                              │
│   [ drop files ]                                               │
│                  ( Create draft transaction )   ( Cancel )     │
└────────────────────────────────────────────────────────────────┘
```

**Fields & examples:**

| Step | Field | Enter |
|---|---|---|
| 1 | Stream | `Scrap` (or `FA`) |
| 2 | Counterparty name \* | `Emirates Copper Trading LLC` |
| 2 | Contract reference | `SC-2026-UAE-118` (optional but realistic) |
| 2 | Batch number | **leave blank** ➜ system proposes next sequential (format `I` + FY digits + company code + seq, e.g. `I7026-642`); or type `TEST-I2626-01` |
| 3 | Documents | optional — you can attach later |

**Click ( Create draft transaction )** ➜ a Request ID is created and you are **redirected straight into the new deal's workspace** (Page 6/7/8 depending on stream). No AI runs yet — it starts once documents are attached.

---

## Page 6 — PURCHASE Transaction Workspace   `/transactions/purchase/{id}`

**Who:** 🔒 Purchase (others read-only per RBAC). **The main workhorse screen.** Two columns: **document on the left, fields on the right.**

```
┌─ Purchase · TEST-I2626-01 ────────────────────────────────────────┐
│ ┌─── LEFT: source document ───┐  ┌─── RIGHT: editable panels ────┐│
│ │  [pdf/docx page]   [−] [+]   │  │ ▼ EXTRACTION                  ││
│ │   page 1 of 2        ◂ ▸     │  │  Invoice no  [ECT/INV/2026/..]🟢│
│ │                              │  │  Batch       [TEST-I2626-01]  🟢│
│ │  (every value links to the   │  │  Quantity MT [24.500       ]  🟢│
│ │   exact spot it was read)    │  │  Rate USD/MT [8125.00      ]  🟠│
│ │                              │  │  Amount USD  [199062.50    ]  🟢│
│ │                              │  │  Container   [DEMU7781234]   🟢│
│ │                              │  │  B/L number  [MAEU7712345]   🟢│
│ └──────────────────────────────┘  │ ▷ MATCHING  (94% → batch #…)  ││
│                                   │ ▼ VALIDATION                  ││
│                                   │   🟢 BR-04 document pack      ││
│                                   │   🟢 BR-05 quantity tol (±5%) ││
│                                   │   🔴 BR-06 invoice value      ││
│                                   │ ▷ HISTORY                     ││
│                                   └────────────────────────────────┘
│ ── sticky bottom bar ─────────────────────────────────────────────│
│   ( Send to Exception Queue )      ( Save changes )  ( Submit for Approval )🔒-disabled until all 🟢
└───────────────────────────────────────────────────────────────────┘
```

**Field colour = AI confidence:** 🟢 high · 🟠 borderline · 🔴 low. Common purchase fields to verify/enter:

| Field | Example value | Commodity/format cheats |
|---|---|---|
| Supplier invoice no | `ECT/INV/2026/0847` | |
| Invoice date | `28/08/2026` | future-dated ➜ rejected; >3 months old ➜ HOD/exception |
| Purchase contract no | `SC-2026-UAE-118` | |
| Batch number | `TEST-I2626-01` | `I`+FY+company(2000 UAE / 3010 Singapore)+seq |
| Commodity code | `CU` | CU=copper · AL=aluminium · CUZNS=brass · MIX · HMS · TIP |
| Quantity (net, MT) | `24.500` | net = gross − tare; ~25 MT per 20-ft copper |
| Rate (USD/MT) | `8125.00` | LME-based; e.g. 97% of LME = 3% discount |
| Amount | `199062.50` | must equal qty × rate (within $1) |
| Currency | `USD` | |
| Container no | `DEMU7781234` | ISO 6346 format (BR-03 checks it) |
| B/L number | `MAEU7712345` | |
| Incoterms | `CIF Singapore` | CIF / CNF / FOB / X-yard |
| Payment terms | `L/C at sight` | or `CAD/DP`, `TT/Telex` |
| Price basis | `Provisional` / `Fixed` | provisional = 80% advance |

**Editing a low-confidence (🔴/🟠) field** ➜ a **reason box opens (min 10 characters)** — type e.g. `Rate confirmed against printed unit price on invoice`. You cannot save until you give the reason.

**Buttons — what each does:**

| Button | Fires | Takes you / result |
|---|---|---|
| **Save changes** | re-validation ⏳ | stays on page; validation panel refreshes; toast “Saved” |
| **Submit for Approval** | `submit` | enabled only when validation is all 🟢; deal ➜ **Approval Pending**, appears in HOD queue, HOD is notified |
| **Send to Exception Queue** | opens case | pre-fills the failing rule as reason ➜ lands in **/exceptions** |

**The MATCHING panel** (opens automatically after extraction is confirmed): shows either
`🟢 Matched to Loading Sheet batch #…, 94%` → click to accept, or
`⚪ No match — open new batch` → click to create a new deal. It compares batch/reference/counterparty similarity and quantity spread.

**Validation panel meaning:** every BR rule is a row. 🔴 row has a **Resolve** link ➜ jumps to **/exceptions/{id}**. Tooltip on the disabled Submit tells you exactly which rule is still red (e.g. *“BR-06: amount 250,000 is outside tolerance”*).

**Try this:** set Quantity to `27.000` (vs contracted 24.5) → Save → BR-05 goes 🔴, an exception opens. Set it back to `24.500` → Save → 🟢 again.

---

## Page 7 — SALES Transaction Workspace   `/transactions/sales/{id}`

**Who:** 🔒 Sales. Same split layout as Purchase, plus **price fixation** and **draft generation**.

```
┌─ Sales · batch ──────────────────────────────────────────────────┐
│ LEFT: source (OBL / draft B/L)   RIGHT: EXTRACTION/MATCH/VALIDATE│
│   Customer      [ DongA Industrial        ]  (abbr auto: DON)    │
│   Sales contract[ …                        ]                     │
│   Quantity MT   [ 24.500 ]   Rate basis [ LME % ▾ ]  % [ 97 ]    │
│   Price status  ○ Provisional  ● Fixed  ──( Record price fixation)│
│ ▼ DRAFT                                                          │
│   [ inline preview of generated sales contract/invoice .pdf ]    │
│   ( Generate Draft )  ( Request Changes )                        │
│   ( Save changes )                       ( Submit for Approval )  │
└──────────────────────────────────────────────────────────────────┘
```

| Field | Example |
|---|---|
| Customer name | `DongA Industrial` (system derives 3-letter code `DON`) |
| Territory | `China` or `India` (changes the mandatory-doc checklist) |
| Quantity / rate / % | `24.500`, basis `LME %`, `97` |
| Advance % | `10` standard for sales; deviating ➜ flag; >80% ➜ HOD |
| Price status | Provisional → **Record price fixation** when customer fixes |

**Buttons:**

| Button | Result |
|---|---|
| **Record price fixation** | locks the fixed LME-based price; moves deal to fixed-price state |
| **Generate Draft** | ⏳ background job renders a sales contract/invoice **DOCX/PDF from approved templates**; appears in the inline preview. **Never auto-sent.** |
| **Request Changes** | opens a note box; re-generates the draft with your edits |
| **Submit for Approval** | ➜ Approval Pending (HOD) once validation is green |

> Rule reminder you'll see act: a draft sales doc can be prepared from an **approved draft B/L**, but final posting stays blocked until the **final OBL/B-L** is present (BR-07). Missing docs = 🔴 validation.

---

## Page 8 — FA Transaction Workspace   `/transactions/fa/{id}`

**Who:** 🔒 FA. Structurally identical to Purchase; the only difference is an **“Additional FA Fields”** panel that renders whatever fields discovery configured (from the `extra_fields` schema — no code change to add one). Same buttons: **Save changes / Submit for Approval / Send to Exception Queue.**

---

## Page 9 — Documents List   `/documents`

**Who:** everyone. A searchable index of every file across every deal (independent of which transaction owns it).

```
│ [Search filename/reference] [Type▾] [Date range]                  │
├──┬──────────────────────────┬────────┬────────────┬──────┬────────┤
│  │ File                     │ Type   │ Transaction│ Date │ Status │
│  │ ECT-INV-0847.pdf         │ Invoice│ TEST-I2626  │28Aug│🟢Extr. │  ◄ click
│  │ MAEU7712345.pdf          │ B/L    │ TEST-I2626  │27Aug│🟠Review│
└──┴──────────────────────────┴────────┴────────────┴──────┴────────┘
   (empty state offers: “Upload a document” ➜ /inbox/upload)
```
- **Click a row** ➜ **/documents/{id}** (Page 10).
- Hover a row ➜ thumbnail preview.

---

## Page 10 — Document Review (extraction split-view)   `/documents/{id}`

**Who:** everyone. **This is where you confirm the AI's work** — the single most important “human gate” screen.

```
┌─ Document · ECT-INV-0847 ────────────────────────────────────────┐
│ LEFT: page viewer (zoom, full-page dialog)                        │
│ RIGHT: fields grouped by schema section, each a confidence chip   │
│   Invoice number  [ECT/INV/2026/0847] 🟢  source: page 1 ¶2       │
│   Quantity MT     [24.500          ] 🟢  source: page 1 ¶6       │
│   Rate USD/MT     [8125.00        ] 🔴  ← click to fix            │
│   ┌─ Reason (required, ≥10 chars) ─────────────────────┐          │
│   │ Corrected to match the printed unit price on invoice│         │
│   └────────────────────────────────────────────────────┘          │
│   Override history: 08:41 you changed Rate 8100 → 8125            │
│                                                                   │
│   ( Reclassify document type )      ( Confirm Extraction )        │
└───────────────────────────────────────────────────────────────────┘
```

**Fields:** same purchase/sales list as the workspace (Page 6/7). Every value shows its **confidence chip** and a **source page/paragraph** link.

| Button | Result |
|---|---|
| type into a 🔴/🟠 field | **reason box appears** — must fill (≥10 chars) before saving; override is stamped with your name + reason |
| **Confirm Extraction** | ➜ **unlocks matching**; the matcher runs ⏳; you're offered the matched batch / new-batch choice, then land in the transaction workspace |
| **Reclassify document type** | pick correct type ➜ ⏳ re-extraction runs against that type's field schema |

**After Confirm:** deal moves `Extracted → Matched → Validation Pending`. This is the moment the pipeline “hands off” to validation.

---

## Page 11 — Exceptions Queue   `/exceptions`

**Who:** everyone sees the ones owned by their desk; admins can reassign.

```
┌─ Exceptions ─────────────────────────────────────────────────────┐
│ [Low confidence][Missing doc][Value tol][Quantity][Shipment][…]  ◄─ category tabs
│ [Owner role ▾] [Age range ▾]                  ( Reassign )🔒admin │
├──┬───────────────┬──────────────┬─────────┬────────┬─────────────┤
│  │ Rule / issue  │ Transaction  │ Owner   │ Age    │ Priority    │
│  │ BR-06 value   │ TEST-I2626-01│ finance │ 🔴100h │ High        │ ◄ click
│  │ Low confidence│ DEMO-…-3     │purchase │ 🟢6h   │ Low         │
│  │ Shipment stale│ DEMU778…     │logistics│🟠30h   │ Medium      │
└──┴───────────────┴──────────────┴─────────┴────────┴─────────────┘
```
- Tabs = exception category. Age badge ramps 🟢→🟠→🔴 past thresholds.
- **Click a row** ➜ **/exceptions/{id}** (Page 12).
- Admins: tick rows → **Reassign owner**.

---

## Page 12 — Exception Detail   `/exceptions/{id}`

**Who:** the owning desk (or approver for escalation).

```
┌─ Exception · BR-06 invoice value ────────────────────────────────┐
│ Rule: BR-06  Field: Amount USD                                   │
│   Expected (qty×rate / source):  199,062.50                      │
│   Actual on invoice:             250,000.00   🔴                  │
│ Linked docs: [ECT-INV-0847.pdf]  [open transaction ▸]            │
│                                                                   │
│ Correct value (if fix is a value): [ 199062.50 ]                 │
│ Resolution note *  [ Amount corrected to qty × rate per invoice ] │
│                                                                   │
│   ( Escalate to HOD )        ( Resolve & re-run validation )      │
└───────────────────────────────────────────────────────────────────┘
```

| Field | Enter |
|---|---|
| Correct value | only if the fix is a data correction (e.g. `199062.50`) — otherwise fix it on the workspace/document |
| Resolution note \* | required, e.g. `Supplier reissued invoice with correct total` |

| Button | Result |
|---|---|
| **Resolve & re-run validation** | ⏳ re-validation runs; if green the case closes and the deal returns to Validation Pending / can be submitted |
| **Escalate to HOD** | moves the case up to the approver queue with your note |

Links at top open the **source document** and the **transaction**. This screen is the “missing document / mismatch / out-of-tolerance / low-confidence / stale shipment” workbench for all ten exception types in the BRD matrix.

---

## Page 13 — Approvals Queue   `/approvals`  🔒 Approver/HOD

**Who:** `hod.approver` (and `dual.user` for its approver half). The replacement for the HOD signing every paper.

```
┌─ Approvals ──────────────────────────────────────────────────────┐
│ Rank by: ( Age )( Value )( Risk )    [Stream ▾]                   │
│ ☐ Batch        Party         Value    Age   AI summary            │
│ ☐ TEST-I2626-01 Emirates    $199,062  🟠26h  “Copper 24.5MT, all…│ ◄click
│ ☐ DEMO-I2626-4  Sample      $225,500  🟢2h   “Clean pack, low rk”│
│                                              ( Approve selected ) │  ◄ low-risk only, under ceiling
└───────────────────────────────────────────────────────────────────┘
```
- **Rank by** re-orders: oldest first / biggest deal first / riskiest first.
- The **AI summary** is a one-line plain-language note — generated **once** when you open a deal, cached; it never decides.
- **Click a row** ➜ **/approvals/{id}** (Page 14).
- **Approve selected** ➜ bulk-approves only the genuinely low-risk subset, up to the configured ceiling (GOV-01); anything over the cap stays queued.
- Empty state: *“Nothing pending your approval.”*

---

## Page 14 — Approval Decision   `/approvals/{id}`  🔒 Approver/HOD

**The most safety-critical page.** Everything to decide without leaving.

```
┌─ Approve · TEST-I2626-01 ────────────────────────────────────────┐
│ ⚠ AI-drafted summary — verify before approving (disclaimer banner)│
│ Deal summary: copper scrap, 24.500 MT @ 8125 = $199,062.50 CIF   │
│ Validation: 🟢 all rules passed   Documents: [inv][B/L][pack] 🔗  │
│ Exception history: none                                          │
│ Reason (required for Reject / Request Changes):                  │
│ ┌──────────────────────────────────────────────────────────────┐ │
│ │                                                              │ │
│ └──────────────────────────────────────────────────────────────┘ │
│   ( Request Changes )   ( Reject )        ( Approve )            │
└───────────────────────────────────────────────────────────────────┘
```

| Action | What to enter | Result |
|---|---|---|
| **Approve** | nothing (above a value threshold a confirm dialog appears) | deal ➜ **Approved → Integration Pending**; unlocks the SAP/DMS/Tracker jobs; maker is notified |
| **Reject** | reason **required**, e.g. `B/L weight does not match invoice` | deal goes back; reason recorded |
| **Request Changes** | reason required | returns to the desk to correct, then resubmit |

🔒 **Self-approval is refused in the service:** log in as `dual.user`, submit a deal, then try to approve it while still logged in as `dual.user` → blocked with “you cannot approve a transaction you submitted,” even though you hold both roles.

**After Approve:** you're returned to the queue; the deal now shows on **/admin/integrations** with three jobs.

---

## Page 15 — Shipments Board   `/shipments`

**Who:** everyone (logistics owns it).

```
┌─ Shipments ───────── [Card|Table] [Status▾][Carrier▾][POD▾] ──────┐
│ ▣ DEMU7781234  B/L MAEU7712345  Maersk  Jebel Ali→Singapore       │
│   ETA 11 Sep   milestone: In transit   🟢 on schedule   ⟳ refresh │
│ ▣ DEMU7781235  …                                                  │
│   ETA 09 Sep   last checked 72h ago     🔴 STALE (exception open) ⟳│
└───────────────────────────────────────────────────────────────────┘
```
- Status badges: 🟢 on schedule · 🟠 delayed · 🔵 arrived · 🔴 exception.
- **⟳ refresh** on a row ➜ on-demand carrier pull ⏳ (where no carrier adapter exists, the system keeps it honest-by-hand and says so).
- A container not checked for >48h ➜ 🔴 staleness indicator + an auto-opened logistics exception.
- **Click a card/row** ➜ **/shipments/{id}** (Page 16).

---

## Page 16 — Shipment Detail   `/shipments/{id}`

**Who:** everyone.

```
┌─ Shipment · DEMU7781234 ─────────────────────────────────────────┐
│ Linked transaction: TEST-I2626-01  [open ▸]                       │
│ Milestone timeline:                                               │
│   ● Booked → ● Loaded → ● Departed Jebel Ali → ○ Arrived SG → …  │
│ Tabs/fields: carrier, vessel, POL=AEJEA, POD=SGSIN, ETA/ETD       │
│                                                                   │
│ Log post-delivery issue:                                          │
│   Type [ Quality / Damage / Detention ▾]                          │
│   Description [ Receiver reports 0.3 MT moisture loss ]           │
│   Supporting doc [optional upload]                                │
│   ( Log issue )      ( Refresh status )                           │
└───────────────────────────────────────────────────────────────────┘
```
| Field | Example |
|---|---|
| Status / milestone | update e.g. `Arrived / Discharged` with a note (`Vessel berthed, discharge commenced`) — goes through the single audited update path |
| Issue type | `quality` / `damage` / `detention` |
| Description | `0.3 MT moisture loss on discharge` |

**Log issue** ➜ issue recorded on the timeline and can feed an exception. **Refresh status** ➜ carrier pull. Linked-transaction card jumps back to the deal.

---

## Page 17 — Analytics   `/analytics`

**Who:** everyone. KPI charts (no data entry except filters).

```
│ [Date range] [Stream ▾]                                           │
│ ── line: turnaround trend ──  ── bar: extraction accuracy by doc type ──
│ ── donut: automation vs manual share ──                          │
│                                  ( Export chart data )  ➜ CSV/image
```
Charts are read-only; the “accuracy” figure is explicitly labelled as a non-override rate.

---

## Page 18 — Reports List   `/reports`

**Who:** everyone.

```
│ [Type▾ daily/monthly/adhoc] [Date]          ( New ad-hoc report ) ➜ /reports/builder
│ Daily ops 2026-08-28   daily   PDF  ⬇      │
│ Monthly summary Jul    monthly XLSX ⬇      │  ◄ click row ➜ /reports/{id}
└────────────────────────────────────────────
```
- **⬇ Download** ➜ file streams via a signed, expiring link (toast on success; Retry on failure).
- **Row click** ➜ **/reports/{id}**.
- **New ad-hoc report** ➜ Page 19.

---

## Page 19 — Ad-hoc Report Builder   `/reports/builder`

**Who:** authorised reporting users.

```
┌─ Build a report ─────────────────────────────────────────────────┐
│ Date from * [ 01/08/2026 ]   Date to * [ 29/08/2026 ]            │
│ Business stream [ Scrap ▾ ]   Status filter [ All statuses ▾ ]   │
│ Format  ( PDF )  ( XLSX )                                        │
│            ( Generate Report )                                   │
│   ████████░░ generating… (you can leave; toast when done)        │
└───────────────────────────────────────────────────────────────────┘
```
| Field | Enter |
|---|---|
| Date from/to \* | required, e.g. `01/08/2026` → `29/08/2026` |
| Stream | `Scrap` / `FA` |
| Status | or filter to e.g. `Committed` |
| Format | PDF or XLSX |

**Generate Report** ➜ ⏳ background job (progress bar polled). On completion ➜ **/reports/{id}**. Optional executive-summary paragraph is AI-generated; the page states the report is **not emailed to anyone** automatically.

---

## Page 20 — Report Viewer   `/reports/{id}`

**Who:** everyone.

```
│ Inline PDF report · generated 29 Aug by system · filters used: … │
│   Total committed value  $1,240,000   [ view transactions ↗ ]     │
│   Exceptions open              5       [ view transactions ↗ ]     │
│   ( Download )   ( Re-generate with same filters )               │
└───────────────────────────────────────────────────────────────────┘
```
- **Click any figure** (“view transactions”) ➜ jumps to **/transactions pre-filtered to exactly that number** — every total is reproducible.
- Shows the query filters, who/when generated.

---

## Page 21 — Notifications   `/notifications`  (also the 🔔 bell)

```
│ 🔵 Approval requested — TEST-I2626-01 assigned to you        2m  │ ◄ click ➜ /approvals/{id}
│ 🔴 Exception assigned — BR-06 on TEST-I2626-01              1h   │ ◄ click ➜ /exceptions/{id}
│ 🟢 Report ready — Daily ops 2026-08-29                       3h   │ ◄ click ➜ /reports/{id}
│                                  ( Mark all as read )            │
```
- Bell in the top bar shows a popover preview of this.
- **Click a notification** ➜ deep-links to the exact transaction/exception/approval/report.
- **Mark all as read** clears the badge. (Delivery channels are chosen in Settings; emails are captured in MailHog at http://localhost:8025.)

---

## Page 22 — Settings   `/settings`

```
┌─ Settings ───────────────────────────────────────────────────────┐
│ PROFILE (read-only, from identity provider)                      │
│   Name [ Fatima Hussain ]   Email [ purchase.user@agfze.local ]  │
│ PREFERENCES                                                      │
│   Notifications:  [x] In-app    [ ] Email    [ ] Push (if set)   │
│   Default queue filter:  ( Scrap only )  ( Scrap + FA )          │
│                      ( Save preferences )                        │
└───────────────────────────────────────────────────────────────────┘
```
- Name/email are not editable here. Toggle channels, pick default filter, **Save preferences**.
- Avatar menu (top-right) also gives **Profile** and **Sign out**.

---

# ADMIN PAGES  🔒 (log in as `admin.user`; audit also for `auditor.user`)

Every admin edit opens a **dialog** (not a new page) and **requires a “reason for this change”** before Save — the reason is audit-logged.

## Page 23 — Admin landing   `/admin`
System health + config summary (integrations status, storage, scheduler/sweeps). Links into the six admin sub-pages.

## Page 24 — Users   `/admin/users`
Table of accounts. **Edit dialog:** assign role(s). **Reason \*** e.g. `Granting approver_hod to second HOD`. Save ➜ written to Keycloak first, mirrored locally on confirmation. ➜ audit.

## Page 25 — Rules   `/admin/rules`
Every threshold (quantity tolerance ±5%, invoice-value/rounding $1/$10, confidence 0.75, match floors, bulk-approval ceiling GOV-01, approval-overdue hours, exception ageing, shipment staleness 48h).
- Edit a value dialog → **Reason \*** e.g. `Widen quantity tolerance to 5% per trading memo` → Save. Saving without a reason is blocked.

## Page 26 — Document Types   `/admin/document-types`
Field list + mandatory-document checklist **per document type and per territory** (China vs India packs differ). JSON-schema-aware field editor; confirmation dialog if it affects live validation; reason required. Add a field here = no code deploy.

## Page 27 — Integrations Monitor   `/admin/integrations`
Tabs: **Tracker · SAP · DMS**.

```
│ [Tracker][SAP][DMS]  [Status▾]                                   │
│ Job: SAP posting for TEST-I2626-01                               │
│   Status: ⚪ awaiting_manual_action   attempts 0                  │
│   Payload ready + manual instructions (no endpoint configured)   │
│   ( Retry )   ( Trigger approved manual fallback )  reason*      │
│ Job: DMS pack for TEST-I2626-01 → 🟢 success, ref DMS-88421      │
```
- Unconfigured endpoints (the local default) ➜ job rests at **awaiting_manual_action** with the full payload — it never fakes success.
- **Retry** ➜ re-queues the job. **Manual fallback** ➜ logs a reason. On real success the external reference (e.g. SAP/DMS number) is recorded and shown.

## Page 28 — Audit Explorer   `/admin/audit`  (Admin + Auditor)
```
│ [Date range][Event type▾][Actor▾][Search entity ref]  ( Export CSV )
│ 08:41 purchase.user  FieldOverrode  Rate 8100→8125  TEST-I2626-01 │
│ 08:47 hod.approver   ApprovalGranted                 TEST-I2626-01 │
│ 08:48 system         IntegrationJobQueued (SAP)      TEST-I2626-01 │
```
Filters + **Export CSV** (streams, doesn't buffer). Rows link to the referenced entity. Metadata only — never full document/AI text. This is where you prove every action in Walkthrough A was recorded.

## Page 29 — Report Distribution   `/admin/report-distribution`
Who receives which scheduled report (daily 06:00 UTC / monthly day 1) and on which channel (in-app/email). Edit dialog + reason.

## Page 30 — Report Templates   `/admin/report-templates`
What sections/figures each report carries. Renderers read this — they never hardcode a section name.

---

# PUBLIC / SYSTEM PAGES

## Page 31 — Disclaimer / Privacy / Terms   `/disclaimer` `/privacy` `/terms`
Static legal pages, footer-linked from every screen. The disclaimer states AI proposes, a person confirms.

## Page 32 — Sign out   `/signout`
Confirmation ➜ clears the session cookie, redirects through Keycloak logout, back to `/`. Also **clears cached screens** and push subscriptions on that browser.

## Page 33 — Offline   `/offline`
If the network drops with no cached copy: *“You're offline”* + what's still readable from cache. Read screens may show stale cached data; **no action (submit/approve/upload) is ever queued offline**. Auto-retries when back online.

## Page 34 — 404 / Error
- Unknown URL ➜ friendly 404 + **Back to dashboard**.
- A route crashes ➜ error boundary: calm message, **Try again**, **Report this issue** (pre-filled with the event ID).

---

# 3. THE TWO GUIDED JOURNEYS (do these in order)

## Walkthrough A — “Purchase officer books a deal, HOD approves it” (happy path)

```
1. Sign in as purchase.user .................................... /dashboard
2. ( Upload documents ) ........ drag sample-supplier-invoice.docx
   Stream=Scrap → (Upload & classify) ................... ⏳ /inbox row appears
3. Click the new row → Document Review ................... /documents/{id}
   • fix any 🔴 field, give the Reason, then
   • ( Confirm Extraction ) ............................. matcher runs
   • accept “Matched batch” OR “open new batch”
4. You're in the Purchase Workspace ........ /transactions/purchase/{id}
   • verify Quantity 24.500, Rate 8125.00, Amount 199062.50,
     Container DEMU7781234, B/L MAEU7712345
   • (Save changes) → wait for VALIDATION all 🟢
5. ( Submit for Approval ) ........................ deal = Approval Pending
   ── sign out, sign in as hod.approver ──
6. /approvals → rank by Age/Value/Risk → click the deal ... /approvals/{id}
   read the AI summary, open a source doc, then
   ( Approve )  [confirm dialog] .................... deal = Approved
7. Open /admin/integrations (sign in admin to see) ... 3 jobs created:
   SAP + DMS + Tracker → ⚪ awaiting_manual_action (expected locally)
8. /shipments → open DEMU7781234 → update milestone / (Refresh)
9. 🔔 bell → notifications for each step; /reports → generate a monthly
   report → click a figure → lands back on /transactions filtered
10. Sign in auditor.user → /admin/audit → see steps 2–8 recorded → Export CSV
```

## Walkthrough B — “Something goes wrong: exception → fix → resubmit”

```
1. purchase.user → open the deal → set Quantity to 27.000 → Save
   BR-05 turns 🔴 → an exception opens ............ /exceptions gets a row
2. Open /exceptions → click it ..................... /exceptions/{id}
   shows Expected 24.5 (±5%) vs Actual 27.0
   Option (a): fix back on the workspace to 24.500 → Save → 🟢
   Option (b): here, enter Correct value + Resolution note
            → ( Resolve & re-run validation ) ⏳
3. Or ( Escalate to HOD ) to push the decision upward.
4. Once 🟢 → (Submit for Approval) → continue from Walkthrough A step 6.
```

**Other role quick-trips:**
- **Sales (`sales.user`):** /transactions → open a sales deal → set Customer `DongA`, basis LME% = 97 → **Record price fixation** → **Generate Draft** (preview PDF) → Submit.
- **Logistics (`logistics.user`):** /shipments → open the stale 🔴 demo container → set status Arrived + note → staleness clears.
- **Finance (`finance.user`):** /exceptions → “Invoice amount outside tolerance” tab → resolve value cases.
- **Admin (`admin.user`):** /admin/rules → change a threshold (reason required) → then /admin/audit to see it logged.
- **Maker-checker proof (`dual.user`):** submit a deal → try to approve it same session → blocked.

---

# 4. “I want to do X” — instant recipe index

| I want to… | Go to / click | Then |
|---|---|---|
| Get a document into the system | **/inbox/upload** (or wait for email) | drop file, Stream=Scrap, Upload & classify |
| Check/fix what the AI read | **/documents/{id}** | fix 🔴 fields + reason → Confirm Extraction |
| See/finish a deal | **/transactions** → row | fix fields, Save, Submit when all 🟢 |
| Register a deal with no email | **/transactions/new** | stream → party → create → workspace |
| Find what's blocking a deal | workspace **VALIDATION** panel / **/exceptions** | click the 🔴 Resolve link |
| Fix an exception | **/exceptions/{id}** | correct value + note → Resolve & re-run |
| Approve/reject (HOD) | **/approvals/{id}** | Approve (or Reject/Changes with reason) |
| See SAP/DMS/tracker status | **/admin/integrations** | Retry / manual fallback |
| Track a container | **/shipments/{id}** | refresh, set milestone, log issue |
| Generate a report | **/reports/builder** | dates + format → Generate → viewer |
| See KPIs/charts | **/analytics** or **/dashboard** | date range, stream filter |
| Change a tolerance/rule | **/admin/rules** | edit + reason (audited) |
| Add a field to a doc type | **/admin/document-types** | edit schema + reason |
| Give someone a role | **/admin/users** | edit role + reason |
| Prove who did what | **/admin/audit** | filter → Export CSV |
| Change my alerts | **/settings** | toggle in-app/email → Save |
| Read an email the system “sent” | MailHog **http://localhost:8025** | open the inbox |
| Find anything fast | **Ctrl/⌘K** | type batch/party/document |

---

## 5. Navigation cheat-sheet (button ➜ destination)

```
[Upload documents]      ➜ /inbox/upload
[+ New] (transactions)  ➜ /transactions/new
[Create draft txn]      ➜ /transactions/{stream}/{id}
inbox row               ➜ /documents/{id}  or  /transactions/{stream}/{id}
[Correct category]      ➜ stays (reason dialog)
[Confirm Extraction]    ➜ matching ➜ /transactions/{stream}/{id}
[Reclassify]            ➜ re-extract (same page)
[Save changes]          ➜ re-validate (same page)
[Submit for Approval]   ➜ /approvals (HOD sees it)
[Send to Exception]     ➜ /exceptions/{id}
[Resolve & re-run]      ➜ back to workspace validation
[Escalate to HOD]       ➜ approver queue
[Approve]/[Reject]      ➜ integrations (approve) / back to desk (reject)
[Approve selected]      ➜ bulk under ceiling
shipment [⟳]            ➜ carrier pull (same page)
[Log issue]             ➜ shipment timeline
[Generate Report]       ➜ /reports/{id}
report figure           ➜ /transactions (filtered)
[Download]              ➜ signed file
[Export CSV]/[Export chart] ➜ file download
notification            ➜ its transaction/exception/approval/report
avatar ▾ Settings       ➜ /settings · Sign out ➜ /
```

You now have a click-path for every screen, every form, and every outcome. Start with **Walkthrough A** and click end-to-end.
