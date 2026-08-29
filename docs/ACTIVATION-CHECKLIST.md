# Activation checklist — what is still needed from outside this repository

Four integrations are code-complete and configuration-blocked. None of them needs a code change to
go live: each reads its endpoint and credentials from configuration, and each behaves honestly
while unconfigured — preparing the data and asking a person to finish, rather than failing or
pretending to have succeeded.

This document is the list of what has to be obtained, from whom, and how to verify it once it
arrives. It is deliberately separate from `KNOWN-GAPS.md`, which records decisions AGFZE has to
*make*; everything here is information AGFZE has to *supply*.

---

## CONFIG-025 — SAP live posting

**Depends on:** `VERIFY-009`, which is complete. Three payload fields remain unmapped and are
listed in `KNOWN-GAPS.md` §17; posting can be activated without them, and those fields will simply
be absent until somebody maps them.

**Needed from Finance / IT:**

| Setting | What it is |
|---|---|
| `SAP_API_BASE_URL` | The service host. Its absence is what currently routes every posting to the manual path. |
| `SAP_POSTING_PATH` | The service path, relative to the base URL. The object name is exactly the thing nobody has specified. |
| `SAP_API_USERNAME` / `SAP_API_PASSWORD` or `SAP_API_KEY` | Whichever auth the endpoint actually uses. |
| `SAP_COMPANY_CODE` | One value. The 2000/3010 routing rule is an open question — see `KNOWN-GAPS.md` §17. |
| `SAP_BUSINESS_AREA` | Defaults to `1070`, which discovery named. Change only if that is wrong. |

**Also needed:** confirmation that the payload this platform sends can be consumed. The keys are
this platform's own field names, deliberately, because no SAP object or BAPI was ever specified —
mapping them onto SAP's schema is a configuration exercise on the SAP side.

**Verify by:** posting one real transaction against a sandbox, then checking the job reached
`succeeded` with an `external_reference` — not `awaiting_manual_action`.

---

## CONFIG-026 — DMS live upload

**Needed from IT:** `DMS_API_BASE_URL`, `DMS_UPLOAD_PATH`, `DMS_API_KEY` (or username/password),
and `DMS_REPOSITORY` — the target repository or folder. Also the metadata schema the DMS expects,
for the same reason as SAP: the index values this platform sends carry its own field names.

**Verify by:** uploading one real document pack and confirming the job reached `succeeded` with the
DMS document number recorded.

**One sequencing note.** Once DMS uploads succeed, the DMS document number starts appearing on SAP
payloads — opportunistically, and only when the DMS job resolved first. See `KNOWN-GAPS.md` §17.

---

## CONFIG-027 — Excel / SharePoint tracker

The Microsoft Graph Excel client is complete and row-level safe: it matches an existing row on a
key column and updates in place, so a concurrent human edit elsewhere in the row is not clobbered.

**Needed from Operations:**

| Setting | What it is |
|---|---|
| `TRACKER_DRIVE_ID` | The SharePoint drive holding the live workbook. |
| `TRACKER_WORKBOOK_ITEM_ID` | The workbook itself. |
| `TRACKER_WORKSHEET_NAME` / `TRACKER_TABLE_NAME` | Which sheet and table. |
| `TRACKER_KEY_COLUMN` | The column identifying a batch's row. Defaults to `Batch Number`. |
| `TRACKER_COLUMN_MAP` | **The one thing that cannot be guessed.** JSON, `{platform_field: "Column Header"}`. |

The column map has to be written by somebody looking at the actual workbook, because it is the
mapping between this platform's field names and whatever the headings happen to say. The available
field names are whatever `payloads.tracker_fields` produces.

**Verify by:** running against a **copy** of the workbook first. A wrong column map writes real
values into the wrong columns of a live operational spreadsheet.

---

## CONFIG-028 — Keycloak ↔ Microsoft Entra ID brokering

The shipped realm export configures **zero** identity providers, so sign-in today is against
Keycloak's own local accounts. JWT verification, the NextAuth integration and the role mapping are
all complete and correct.

**Needed from AGFZE IT:** an Entra ID application registration for **identity brokering**.

> This is a **different registration** from the machine-identity one the mailbox poller uses
> (`AZURE_AD_CLIENT_ID` / `AZURE_AD_CLIENT_SECRET`, which hold Graph application permissions for
> reading the shared mailbox). Conflating the two would give the sign-in flow mailbox permissions
> it has no business holding. Ask for a separate registration.

Then, in the realm: add an OIDC identity provider pointing at the tenant, and map Entra ID group
claims onto the platform roles **exactly** as `PlatformRole` names them — `approver_hod`,
`purchase_user`, `sales_user`, `fa_user`, `logistics_user`, `finance_user`, `admin`, `auditor`. A
group that maps to no role produces an account that can sign in and see nothing, which is confusing
rather than dangerous; a group mapped to the wrong role is the opposite.

**Verify by:** a real sign-in through the full Authorization Code Flow with PKCE, checking the
issued token's `realm_access.roles` matches what the person should hold — and, specifically, that
somebody in no mapped group does *not* arrive holding a desk role.
