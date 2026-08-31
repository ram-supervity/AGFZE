# AGFZE Command Centre — 5 Real-World Test Scenarios (Mailbox + Manual Upload)

Yeh pack real metal-scrap trade jaise documents se bana hai. Har scenario mein:
- **ek email** hai (`.eml` — usme PDF attachments actually embedded hain, aur ek `_BODY.txt` jisme poora mail padhne ko milega),
- wahi documents **alag PDF/Excel files** ke roop mein hain jo aap **manual upload** kar sakte ho.

> **Real vs fake:** companies, numbers, B/L, container numbers fictional hain (real counterparty-confidential data use nahi karna hota), lekin **format, fields, terminology, document types aur values asli scrap-trade documents jaisi hi hain** — copper/aluminium, LME %, provisional/final, OBL, CIF/CAD, India/China doc sets, Loading Sheet yellow/blue coding. AI inhi real fields ko extract karega.

## Kaise test karein — dono tareeke

**Tareeka 1 — Mailbox se (email intake):**
- Project mein real Microsoft Graph mailbox tabhi connected hota hai jab `AZURE_AD_*` credentials bhare hon. Local testing mein:
  - MailHog (`http://localhost:8025`) sirf **outgoing** mail dikhata hai (jo platform bhejta hai) — usme incoming inject nahi hoti.
  - Real mailbox simulation ke liye `.eml` file ko apne connected shared mailbox (`trade.docs@...`) par **forward/send** karein, ya Graph se ingest karwayein. Har `.eml` ka subject platform ke keyword rules se match karta hai ("please find deal confirmation", "please share ... contract", "final invoice", "OBL/bill of lading", "proforma").
- Mailbox worker us mail ko poll karke Request banata hai → attachments classify+extract hote hain.

**Tareeka 2 — Manual upload (har scenario ke liye zaroor karein):**
1. Login: `purchase.user` / `Passw0rd!`
2. **Inbox → Upload** (`/inbox/upload`)
3. Neeche table mein us scenario ke **"Manual upload karne wale files"** drag karo (ek saath multiple).
4. **Stream = Scrap** (S6 ke liye **FA**), doc-type hint **Auto-detect**.
5. **Upload & classify** → phir `/inbox` mein naya request kholo → Document Review → confirm → aage.

---

## Master Excel (har scenario ke saath refer hoti hai)

| File | Kya hai |
|---|---|
| `00_Excel_Loading_Sheet_and_Cost_Sheet.xlsx` | **Loading Sheet** tab (master tracker — Batch I7020-642 etc., yellow=provisional, blue=fixed, columns Q/R/S/T = LME hedge low/high/final) + **Cost Sheet** tab. Real duniya mein yeh Excel hi "single source of truth" hoti hai. Matcher isi ke against batch match karta hai. **Manual upload mein ise bhi ek baar `Stream=Scrap` ke saath upload karke dekho — AI ise `tracker`/spreadsheet classify karega.** |

---

# SCENARIO 1 — Broker deal, Copper, PROVISIONAL (purchase, China)

- **Mail:** `S1_broker_deal_copper_provisional/01_email_scenario_S1.eml`
- **Kis se aata hai (From):** Meridian Metals Trading LLC `<docs@meridian-metals.ae>` → `trade.docs@agfze.com`
- **Subject:** `Please find deal confirmation & provisional documents - Batch I7020-642 (Copper Millberry, CIF Shanghai)`
- **Mail body mein kya hai:** broker ref, batch **I7020-642**, commodity Copper Millberry Cu 99.9%, 25.000 MT, container **MSKU7112045**, seal EM5523109, B/L **OOLU8821045**, price **provisional 97% of LME**, rate USD 8,125/MT, value USD 203,125 (80% advance = 162,500), POL Jebel Ali → POD Shanghai, vessel MV OCEAN PIONEER.
- **Email attachments (5):** Purchase Contract, Provisional Invoice, Packing List, Certificate of Origin, Mill/Quality Test Certificate.
- **Manual upload files:**
  - `02_Purchase_Contract_PC-2026-UAE-0118.pdf`
  - `03_Supplier_Provisional_Invoice_MMT-PI-2026-0847.pdf`  ← main document
  - `04_Packing_List_MMT-PL-2026-0847.pdf`
  - `05_Certificate_of_Origin_CO-11982.pdf`
  - `06_Mill_Test_Certificate_SAC-44718.pdf`
- **AI expected:** category **`purchase`**, stream **scrap**. Extract: invoice `MMT/PI/2026/0847`, batch `I7020-642`, supplier Meridian, qty **25.000**, rate **8125.00**, amount **203125.00**, container `MSKU7112045`, B/L `OOLU8821045`, **provisional** flag.
- **Matcher:** Loading Sheet mein batch **I7020-642** maujood hai → usse match hona chahiye.
- **Aage:** confirm → workspace → BR rules → provisional = 80% advance → submit → HOD approve.

---

# SCENARIO 2 — Final FIXED invoice, Aluminium, India (purchase + weight slip)

- **Mail:** `S2_final_invoice_aluminium_fixed/01_email_scenario_S2.eml`
- **From:** Gulfstar Non-Ferrous FZCO `<invoicing@gulfstar-metals.ae>`
- **Subject:** `Final invoice - Aluminium Tense - Batch I7020-647 - price fixed USD 2,145/MT (GSF/FI/2026/0933)`
- **Body:** batch **I7020-647**, Aluminium Tense/Taint Tabor, net **24.000 MT**, container **TCLU4421890**, B/L **MEDU3309712**, price **fixed** USD 2,145/MT (LME fixed 28-Aug), final value USD 51,480; provisional already billed 48,720 → **balance 2,760**; POL Jebel Ali → Mundra.
- **Email attachments (2):** Final Invoice, Weight Slip / Draft Survey.
- **Manual upload files:**
  - `02_Final_Supplier_Invoice_GSF-FI-2026-0933.pdf`
  - `03_Weight_Slip_Draft_Survey_WS-22071.pdf`  ← net weight 24.000 certify karta hai
- **AI expected:** category **`purchase`/final**, stream scrap. Detect **fixed price** (provisional nahi). Weight slip qty ko invoice se match karega.
- **Matcher:** Loading Sheet batch **I7020-647** (blue/fixed) se match.
- **Test point:** final vs provisional detection, balance payment, weight = B/L = invoice cross-check (LG-01/BR-06).

---

# SCENARIO 3 — Logistics: Original Bill of Lading + Arrival Notice (China)

- **Mail:** `S3_logistics_bill_of_lading_china/01_email_scenario_S3.eml`
- **From:** Ocean Link Shipping Line `<docs@oceanlink-shipping.com>` (cc logistics)
- **Subject:** `OBL & arrival notice - B/L OOLU8821045 - MSKU7112045 - MV OCEAN PIONEER ETA Shanghai 12 Sep`
- **Body:** B/L **OOLU8821045** (original 3/3), container MSKU7112045, copper 25.000 MT net / 25.285 gross, shipper Meridian, consignee "to order of bank", notify Dongfang Shanghai, ETA Shanghai **12 Sep**, freight prepaid, free time 7 days.
- **Email attachments (2):** Ocean B/L, Arrival Notice.
- **Manual upload files:**
  - `02_Ocean_Bill_of_Lading_OOLU-8821045.pdf`
  - `03_Arrival_Notice_AN-44178.pdf`
- **AI expected:** category **`logistics`**. Extract B/L no, container, vessel, POL/POD, ETA, gross/net.
- **Test point:** yeh **Scenario 1 ke container (MSKU7112045 / B/L OOLU8821045)** se match hona chahiye → shipment milestone update + OBL gating (BR-07). Arrival notice se shipment ETA/staleness refresh. Logistics user (`logistics.user`) se board par dekho.

---

# SCENARIO 4 — Sales documents, Aluminium → India (CAD/DP) — sales side

- **Mail:** `S4_sales_india_documents/01_email_scenario_S4.eml`
- **From:** AGF Singapore - Sales Desk `<sales@agfze.com.sg>` (internal; cc logistics + accounts)
- **Subject:** `Please share sales documents - Aluminium to Mundra - Batch I7030-214 - B/L MEDU3309712 (CAD/DP)`
- **Body:** sales contract **SC-2026-SG-0307**, sales invoice **AGF/SI/2026/0934**, batch **I7030-214** (Singapore entity **3010**), customer Bharat Metal Recyclers (Mundra), 24.000 MT, rate USD 2,310/MT, value USD 55,440, broker commission USD 600 (25/MT), B/L MEDU3309712, payment **CAD/DP**. India ke liye doc list (Invoice, PL, COO, Freight Cert, Mill cert, Form 6/9).
- **Email attachments (4):** Sales Contract, Sales Invoice, Freight Certificate, Packing List.
- **Manual upload files:**
  - `02_Sales_Contract_SC-2026-SG-0307.pdf`
  - `03_Sales_Invoice_AGF-SI-2026-0934.pdf`
  - `04_Freight_Certificate_FCR-77120.pdf`  ← India-specific
  - `05_Packing_List_AGF-PL-2026-0934.pdf`
- **AI expected:** category **`sales`**, stream scrap. Extract customer, sales contract/invoice, batch, qty, rate 2310, amount 55440, B/L MEDU3309712.
- **Matcher:** Loading Sheet batch **I7030-214** (Singapore 3010) — purchase side (I7020-647) se purchase↔sales link. Sales workspace mein **Generate Draft** / price fixation test karo (`sales.user`).
- **Note:** India doc completeness (freight cert mandatory) BR-04 check karega.

---

# SCENARIO 5 — EDGE CASE: Proforma invoice (no weight slip / no B/L) → approval/exception

- **Mail:** `S5_proforma_invoice_advance_edge/01_email_scenario_S5.eml`
- **From:** Gulfstar Non-Ferrous FZCO (cc HOD)
- **Subject:** `Proforma invoice for advance - Batch I7020-651 - Copper Berry (no weight slip / B/L yet) - GSF/PRO/2026/0941`
- **Body:** proforma **GSF/PRO/2026/0941**, batch I7020-651, Copper Berry, **estimated** 25 MT @ 8,210 = USD 205,250, advance maanga USD 164,200 (80%), **weight slip NAHI hai, B/L NAHI hai** (cargo load nahi hua).
- **Email attachments (1):** Proforma Invoice.
- **Manual upload files:**
  - `02_Proforma_Invoice_GSF-PRO-2026-0941.pdf`
- **AI expected:** category **`purchase`**, par system ko flag karna chahiye: **missing mandatory documents (weight slip / B/L)** + proforma bina weight-slip ke advance = **higher approval (CEO/HOD)** → exception/approval queue.
- **Test point:** yeh **negative/edge** scenario hai. BR-04 (mandatory docs) fail hona chahiye → exception open → escalate to HOD. Verify ki system isse "ready to post" nahi maan leta.

---

# SCENARIO 6 (BONUS) — FA stream: service invoice (non-cargo)

- **Mail:** `S6_fa_service_invoice/01_email_scenario_S6.eml`
- **From:** Summit Advisory & Finance Partners `<billing@summitadvisory.ae>`
- **Subject:** `Tax invoice for advisory services - August 2026 - SAF/INV/2026/0412`
- **Body:** FA/advisory services invoice **SAF/INV/2026/0412**, period Aug 2026, PO AGF-PO-FA-2026-077, subtotal 19,000 + VAT 5% 950 = **USD 19,950**, terms 30 days.
- **Email attachments (1):** FA Service Invoice.
- **Manual upload files:**
  - `02_FA_Service_Invoice_SAF-INV-2026-0412.pdf`  → upload par **Stream = FA**
- **AI expected:** category **`fa`** (alag business stream). FA workspace minimal fields ke saath khulega. Login `fa.user`.

---

# Ek nazar mein — kya upload karna hai aur kya expect karna hai

| # | Scenario | Stream | Manual upload files | Expected category | Main cheez test karne ko |
|---|---|---|---|---|---|
| 1 | Copper provisional broker deal | Scrap | 5 PDFs (contract, inv, PL, COO, mill) | `purchase` (provisional) | extraction, batch match I7020-642, 80% advance |
| 2 | Aluminium final fixed invoice | Scrap | 2 PDFs (final inv, weight slip) | `purchase` (final/fixed) | provisional vs final, weight cross-check, balance |
| 3 | OBL + arrival notice (China) | Scrap | 2 PDFs (B/L, arrival) | `logistics` | container match, shipment milestone, OBL gating |
| 4 | Sales pack to India (CAD/DP) | Scrap | 4 PDFs (sales contract, inv, freight, PL) | `sales` | purchase↔sales link, India docs, draft gen |
| 5 | Proforma bina weight-slip/B/L | Scrap | 1 PDF (proforma) | `purchase` → **exception** | missing docs, HOD/CEO approval gate |
| 6 | FA advisory service invoice | **FA** | 1 PDF (service invoice) | `fa` | FA stream, non-cargo fields |
| — | Master tracker (reference) | Scrap | 1 XLSX (Loading+Cost sheet) | `tracker`/spreadsheet | Excel ingestion, matcher source |

## Har test ke baad verify karo
1. **Inbox** mein request bana, sahi category + confidence badge.
2. **Document Review** (`/documents/{id}`): fields sahi extract hue (upar wale numbers), koi 🔴 field ho to reason ke saath fix → **Confirm Extraction**.
3. **Matcher** ne sahi batch Loading Sheet se match kiya (ya naya batch propose kiya).
4. **Workspace → Validation:** kaun se BR rules pass/fail. Scenario 5 mein exception **hona hi chahiye**.
5. **Submit → Approvals** (`hod.approver` se approve) → **Integrations** mein SAP/DMS/Tracker jobs (local par `awaiting_manual_action` — yeh expected hai).
6. **Shipments** (Scenario 3) par container/milestone update.
7. **Audit** (`auditor.user`) mein har action logged.

## Email ko mailbox mein kaise le jaana hai (optional, real intake ke liye)
- `.eml` file ko apne mail client (Outlook/Thunderbird) mein kholo ya us `.eml` ko apni connected shared mailbox par **forward** karo — platform ka Graph worker usse poll kar lega.
- Ya seedha `_BODY.txt` ka content + PDFs manual upload se bhejo (Tareeka 2) — pipeline intake ke baad se bilkul same hai.
