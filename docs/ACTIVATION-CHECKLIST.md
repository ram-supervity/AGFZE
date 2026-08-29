# Activation checklist - what is still needed from outside this repository

Five integrations are code-complete and configuration-blocked. None of them needs a code change to
go live: each reads its endpoint and credentials from configuration, and each behaves honestly
while unconfigured - preparing the data and asking a person to finish, rather than failing or
pretending to have succeeded.

This document is the list of what has to be obtained, from whom, and how to verify it once it
arrives. It is deliberately separate from `KNOWN-GAPS.md`, which records decisions AGFZE has to
*make*; everything here is information AGFZE has to *supply*.

---

## CONFIG-025 - SAP live posting

**Depends on:** `VERIFY-009`, which is complete. Three payload fields remain unmapped and are
listed in `KNOWN-GAPS.md` §17; posting can be activated without them, and those fields will simply
be absent until somebody maps them.

**Needed from Finance / IT:**

| Setting | What it is |
|---|---|
| `SAP_API_BASE_URL` | The service host. Its absence is what currently routes every posting to the manual path. |
| `SAP_POSTING_PATH` | The service path, relative to the base URL. The object name is exactly the thing nobody has specified. |
| `SAP_API_USERNAME` / `SAP_API_PASSWORD` or `SAP_API_KEY` | Whichever auth the endpoint actually uses. |
| `SAP_COMPANY_CODE` | One value. The 2000/3010 routing rule is an open question - see `KNOWN-GAPS.md` §17. |
| `SAP_BUSINESS_AREA` | Defaults to `1070`, which discovery named. Change only if that is wrong. |

**Also needed:** confirmation that the payload this platform sends can be consumed. The keys are
this platform's own field names, deliberately, because no SAP object or BAPI was ever specified -
mapping them onto SAP's schema is a configuration exercise on the SAP side.

**Verify by:** posting one real transaction against a sandbox, then checking the job reached
`succeeded` with an `external_reference` - not `awaiting_manual_action`.

---

## CONFIG-026 - DMS live upload

**Needed from IT:** `DMS_API_BASE_URL`, `DMS_UPLOAD_PATH`, `DMS_API_KEY` (or username/password),
and `DMS_REPOSITORY` - the target repository or folder. Also the metadata schema the DMS expects,
for the same reason as SAP: the index values this platform sends carry its own field names.

**Verify by:** uploading one real document pack and confirming the job reached `succeeded` with the
DMS document number recorded.

**One sequencing note.** Once DMS uploads succeed, the DMS document number starts appearing on SAP
payloads - opportunistically, and only when the DMS job resolved first. See `KNOWN-GAPS.md` §17.

---

## CONFIG-027 - Excel / SharePoint tracker

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

## CONFIG-028 - Keycloak ↔ Microsoft Entra ID brokering

The shipped realm export now carries the broker, imported **disabled** and populated entirely
with `REPLACE-ME…` placeholders - one OIDC identity provider (`entra-id`) and eight group-to-role
mappers, one per platform role. Sign-in today is still against Keycloak's own local accounts,
because a disabled provider changes nothing; JWT verification, the NextAuth integration and the
role mapping have been complete and correct throughout. Activation is a data fill, not a code or
schema change. `infra/keycloak/README.md` is the step-by-step.

**Needed from AGFZE IT:** an Entra ID application registration for **identity brokering**.

> This is a **different registration** from the machine-identity one the mailbox poller uses
> (`AZURE_AD_CLIENT_ID` / `AZURE_AD_CLIENT_SECRET`, which hold Graph application permissions for
> reading the shared mailbox). Conflating the two would give the sign-in flow mailbox permissions
> it has no business holding. Ask for a separate registration.

Then replace every placeholder in `infra/keycloak/realm-agfze.json`:

| Placeholder | What it is |
|---|---|
| `REPLACE-ME-TENANT-ID` | The tenant id, in six endpoint URLs. |
| `REPLACE-ME-BROKER-APP-CLIENT-ID` | The broker registration's application (client) id. |
| `REPLACE-ME-BROKER-APP-CLIENT-SECRET` | Its secret, injected at import from the secret store. |
| `REPLACE-ME-ENTRA-GROUP-OBJECT-ID-<ROLE>` | One group object id per role, on each of the eight mappers. |

The mappers already name the platform roles **exactly** as `PlatformRole` names them -
`approver_hod`, `purchase_user`, `sales_user`, `fa_user`, `logistics_user`, `finance_user`,
`admin`, `auditor` - so the only thing to supply is which Entra ID group is which. A group that
maps to no role produces an account that can sign in and see nothing, which is confusing rather
than dangerous; a group mapped to the wrong role is the opposite.

Two things in the app registration itself, and a sign-in fails without either: the redirect URI
`https://<keycloak-host>/realms/agfze/broker/entra-id/endpoint`, and the **`groups` claim switched
on** in the token configuration. Every mapper reads that claim; with it off, each one matches
nothing. Finally set `"enabled": true` on the provider and re-import.

**Verify by:** a real sign-in through the full Authorization Code Flow with PKCE, checking the
issued token's `realm_access.roles` matches what the person should hold - and, specifically, that
somebody in no mapped group does *not* arrive holding a desk role.


---

## CONFIG-029 - Outbound replies on an inbound thread

The platform can answer a broker or a supplier on the thread their message arrived on: composing
writes a draft that is readable and rewritable, and sending it is a separate, explicit call a
signed-in person makes, recorded against their account. There is no worker, scheduler or event
handler anywhere with a route to the send path.

It ships **switched off**, and deliberately as its own switch rather than as a consequence of the
Graph credentials existing. Reading a shared mailbox and putting a message into a supplier's inbox
from AGFZE's own address are different decisions.

**Needed from AGFZE IT:**

| Setting / grant | What it is |
|---|---|
| `Mail.ReadWrite` (application) | Creating the reply draft on the original conversation. Narrow it to the same shared mailbox, with the same application access policy the existing `Mail.Read` grant uses. |
| `Mail.Send` (application) | Sending that draft. Same narrowing. |
| `GRAPH_REPLY_ENABLED=true` | The platform's own switch. Until it is set, a reply can be drafted and read here and cannot leave - and the screen says exactly that rather than offering a button that could only fail. |

**Also needed, from the business rather than from IT:** confirmation that a reply going out over
AGFZE's address needs no approval tier above the desk that writes it. The platform currently treats
the explicit send as the human approval, and records who made it; no separate approver role was
invented, because no source document names one.

**Verify by:** drafting a reply on a test thread, reading the stored body back - it carries the
request reference and the standing disclaimer, added by the server rather than by the form - then
sending it and confirming it arrives **in the original conversation** rather than as a new message.
