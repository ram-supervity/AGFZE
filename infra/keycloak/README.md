# Keycloak realm - `agfze`

`realm-agfze.json` is imported by the local Keycloak container on first start (`make setup`, or
`make realm-import` to force a fresh import). It carries the realm's roles, its two clients, the
seeded local development logins, and - since this revision - the **Microsoft Entra ID identity
provider**, imported disabled and populated entirely with placeholders.

## Why the broker exists

The governing material requires Keycloak to broker Entra ID rather than to hold a second password
store: staff sign in with the Microsoft 365 credentials and the MFA policy they already have, and
Keycloak maps their Entra ID group membership onto this platform's eight roles. Everything on the
application side of that arrangement is already built and tested - the NextAuth OIDC flow, the
backend's JWKS signature verification, and the role-claim mapping that turns a token into what a
user may do. What was missing, and what this file now scaffolds, is the realm-side configuration.

Nothing here is a working configuration and nothing here is guessed. Activation is a data fill by
AGFZE IT, not a schema or code change.

## What AGFZE IT must supply

Create a **new** Entra ID app registration for sign-in brokering. It must not be the machine
identity the mailbox poller uses (`AZURE_AD_CLIENT_ID` / `AZURE_AD_CLIENT_SECRET`): that one holds
`Mail.Read` on a shared mailbox and `Files.ReadWrite.Selected` on the tracker workbooks, and a
sign-in flow must never be able to borrow either. Two registrations, two blast radii, deliberately.

Then replace every `REPLACE-ME…` value in `realm-agfze.json`:

| Placeholder | What it is |
| --- | --- |
| `REPLACE-ME-TENANT-ID` | The AGFZE Entra ID tenant id (a GUID). It appears in six endpoint URLs; replace all of them. |
| `REPLACE-ME-BROKER-APP-CLIENT-ID` | The broker app registration's application (client) id. |
| `REPLACE-ME-BROKER-APP-CLIENT-SECRET` | Its client secret. Injected at import time from the deployment's secret store; never committed. |
| `REPLACE-ME-ENTRA-GROUP-OBJECT-ID-<ROLE>` | One Entra ID **group object id** per platform role, on each of the eight `identityProviderMappers`. |

Then, in the app registration itself:

- add the redirect URI Keycloak advertises for this broker,
  `https://<keycloak-host>/realms/agfze/broker/entra-id/endpoint`;
- switch the **`groups` claim on** in the token configuration. Every group mapper below reads the
  `groups` claim, so with it off each one matches nothing and a signed-in person lands on the
  "your account isn't provisioned" screen rather than on their dashboard.

Finally set `"enabled": true` on the identity provider and re-import.

## The eight roles, spelled exactly as the code spells them

A mapper that produces a role name the backend does not recognise grants nothing and reports
nothing, so these are copied verbatim from `backend/app/core/roles.py`:

`approver_hod`, `purchase_user`, `sales_user`, `fa_user`, `logistics_user`, `finance_user`,
`admin`, `auditor`.

Each mapper uses `syncMode: FORCE`, so group membership is re-evaluated on **every** sign-in: a
person removed from a group in Entra ID loses the role on their next token, with nobody editing
anything here. The `/admin/users` screen's manual override stays what it always was - the
documented exception to group-driven mapping, written to Keycloak first and mirrored locally only
once Keycloak confirms it.

## What stays true after activation

The seeded local logins in this file are development-only and are irrelevant in a deployment that
brokers Entra ID; they exist so `make setup` produces a usable stack on a laptop with no tenant.
Leaving the identity provider disabled - which is how it imports - keeps that behaviour exactly
as it is today.
