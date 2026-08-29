from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated, Any

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_DATABASE_URL = "postgresql+asyncpg://agfze:agfze@localhost:5432/agfze"
DEFAULT_SIGNED_URL_SECRET = "dev-signing-secret-not-for-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    ENV: str = "development"
    PROJECT_NAME: str = "AGFZE Command Centre"
    API_V1_PREFIX: str = "/api/v1"
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str = DEFAULT_DATABASE_URL
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    DATABASE_ECHO: bool = False

    KEYCLOAK_ISSUER: str = ""
    KEYCLOAK_JWKS_URL: str = ""
    KEYCLOAK_AUDIENCE: str = "agfze-command-centre"
    # NoDecode: list settings arrive from the environment as "a,b", not as JSON, so the
    # before-validator below owns the parsing instead of pydantic-settings' json.loads.
    JWT_ALGORITHMS: Annotated[list[str], NoDecode] = ["RS256"]
    JWT_LEEWAY_SECONDS: int = 30

    # --- Keycloak Admin REST API () -------------------------------------------------------
    # A third machine credential, and deliberately a third one. The OIDC client above is what
    # staff sign in through and holds no administrative grant; the Graph app registration reads
    # one mailbox and writes one workbook. This one is a service account on its own confidential
    # client, granted `realm-management: manage-users` and nothing more, and it is used by exactly
    # one code path: the rare manual role override on /admin/users. Three separate credentials
    # means a leak of any one of them costs the blast radius of that one capability.
    KEYCLOAK_SERVER_URL: str = ""
    KEYCLOAK_REALM: str = "agfze"
    KEYCLOAK_ADMIN_CLIENT_ID: str = ""
    KEYCLOAK_ADMIN_CLIENT_SECRET: str = ""
    KEYCLOAK_ADMIN_TIMEOUT_SECONDS: float = 15.0

    # "local" or "gcs". Local is the default and is what development and the test suite use; a
    # deployment with a bucket sets "gcs" and STORAGE_BUCKET, and no caller anywhere changes.
    STORAGE_BACKEND: str = "local"
    STORAGE_LOCAL_ROOT: str = "./var/storage"
    # The object store's bucket, read only when STORAGE_BACKEND is an object store. Empty is the
    # correct value for a local deployment rather than an oversight.
    STORAGE_BUCKET: str = ""
    STORAGE_SIGNED_URL_SECRET: str = DEFAULT_SIGNED_URL_SECRET
    STORAGE_SIGNED_URL_TTL_SECONDS: int = 900
    STORAGE_PUBLIC_BASE_URL: str = "http://localhost:8000/internal/files"

    RATE_LIMIT_ENABLED: bool = False
    RATE_LIMIT_DEFAULT: str = "120/minute"
    # Where the counters live. In-process by default, which is correct for one instance and
    # honest about what it is: with several instances behind a load balancer each one counts its
    # own share, so a production deployment that runs more than one pods this at a shared store
    # ("redis://host:6379/0") to make a limit mean what it says across the fleet.
    RATE_LIMIT_STORAGE_URI: str = "memory://"
    # Accepts per-instance rate-limit counting in production. Off, because the honest default is
    # to refuse: a deployment that scales past one instance and does not notice has every limit
    # multiplied by its instance count. Turning this on is a statement that the deployment is
    # genuinely single-instance, not a way to quieten the start-up check.
    RATE_LIMIT_ALLOW_IN_PROCESS: bool = False
    # Whether the left-most X-Forwarded-For entry is trusted as the client address. False by
    # default, because on a directly-reachable process that header is client-supplied and a
    # per-request forgery would defeat every limit below. True only where a WAF or load balancer
    # this deployment controls sets it, which is what the production profile assumes.
    RATE_LIMIT_TRUST_FORWARDED_FOR: bool = False

    # The four categories this platform's specification names as the ones most exposed to abuse
    # or accidental overload. Each is a real, specific value rather than a boolean, and each is
    # deliberately tighter than the default ceiling above.
    #
    # Authentication-adjacent: every request carries a bearer token, but these are the endpoints
    # a client hits to establish or refresh a session, and the ones that provision an account on
    # first sight. Generous enough for a page that polls its own profile, tight enough that token
    # grinding is not free.
    RATE_LIMIT_AUTH: str = "30/minute"
    # File upload. Twenty files per request at 25 MB each is already the endpoint's own ceiling;
    # this bounds how often that ceiling can be reached.
    RATE_LIMIT_UPLOAD: str = "20/minute"
    # Every endpoint that can reach the model. These cost real money per call and are the only
    # place in the platform where a loop in somebody's script bills AGFZE.
    RATE_LIMIT_AI: str = "15/minute"
    # Bulk approval. A legitimate approver clears a queue in a handful of calls; anything past
    # that is either a mistake or somebody trying to push a list through before it is read.
    RATE_LIMIT_BULK_APPROVAL: str = "5/minute"
    # The unauthenticated Graph webhook. It is secret-checked rather than token-checked, so a
    # ceiling on how often it can be shouted at is the only other thing protecting it.
    RATE_LIMIT_WEBHOOK: str = "120/minute"

    CORS_ALLOWED_ORIGINS: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    # HTTP Strict Transport Security, in seconds. Emitted only over HTTPS and only in production,
    # so a local plain-HTTP stack is never pinned to a scheme it does not serve. Two years, which
    # is the preload-list minimum.
    HSTS_MAX_AGE_SECONDS: int = 63072000

    SENTRY_DSN: str | None = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0

    # --- Microsoft Graph mailbox intake (machine identity, no interactive login) ---------------
    AZURE_AD_TENANT_ID: str = ""
    AZURE_AD_CLIENT_ID: str = ""
    AZURE_AD_CLIENT_SECRET: str = ""
    GRAPH_MAILBOX_ADDRESS: str = ""
    GRAPH_BASE_URL: str = "https://graph.microsoft.com/v1.0"
    GRAPH_LOGIN_BASE_URL: str = "https://login.microsoftonline.com"
    GRAPH_SCOPE: str = "https://graph.microsoft.com/.default"
    GRAPH_TIMEOUT_SECONDS: float = 30.0
    GRAPH_POLL_ENABLED: bool = True
    GRAPH_POLL_INTERVAL_SECONDS: int = 120
    # Change notifications are optional: the delta poll alone is a complete capture path, the
    # webhook only shortens the latency. It stays off until a publicly reachable URL exists.
    GRAPH_WEBHOOK_ENABLED: bool = False
    GRAPH_WEBHOOK_NOTIFICATION_URL: str = ""
    GRAPH_WEBHOOK_CLIENT_STATE: str = ""
    GRAPH_SUBSCRIPTION_TTL_MINUTES: int = 4230
    GRAPH_MAX_ATTACHMENTS_PER_MESSAGE: int = 25
    # Outbound replies on an inbound thread. Off by default and deliberately its own switch rather
    # than a consequence of the Graph credentials existing: reading a shared mailbox and putting a
    # message into a supplier's inbox from AGFZE's address are different decisions, and the second
    # one needs `Mail.ReadWrite` and `Mail.Send` granted on top of the read scope. With this off, a
    # reply can still be composed and reviewed here; it simply cannot leave.
    GRAPH_REPLY_ENABLED: bool = False

    # --- AI extraction --------------------------------------------------------------------------
    AI_PROVIDER: str = "gemini_flash"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_TIMEOUT_SECONDS: float = 90.0
    GEMINI_MAX_OUTPUT_TOKENS: int = 8192
    CONFIDENCE_THRESHOLD_DEFAULT: float = 0.75

    # --- Transactions ---------------------------------------------------------------------------
    # The two-digit company-code segment of a batch number. One value, deliberately: routing
    # between SAP company codes (2000 UAE, 3010 Singapore) is only a real decision once there is
    # an SAP posting to route, which belongs to the integration . Every tolerance and rule
    # threshold lives in `rule_configurations` instead, so it stays editable without a redeploy.
    BATCH_COMPANY_CODE: str = "26"

    # --- Shipment tracking ---------------------------------------------------------------------
    # Whether the tracking sweep runs at all. It does more than call adapters: it is also what
    # notices a shipment nobody has looked at for two days, so it stays on even where no carrier
    # is reachable.
    SHIPMENT_TRACKING_POLL_ENABLED: bool = True
    # Six hours, which is roughly how often a carrier's own tracking page moves. Seconds rather
    # than hours so a deployment can shorten it without a code change.
    SHIPMENT_TRACKING_INTERVAL_SECONDS: int = 6 * 60 * 60
    # A convenience flag, not a promise. No carrier's API is specified anywhere in this
    # platform's material, so no concrete adapter ships and the default is - correctly - that
    # every shipment is tracked by hand. Turning this on does nothing until an adapter is
    # actually registered; it exists so a deployment can say "we have one" in one place.
    SHIPMENT_CARRIER_ADAPTERS_ENABLED: bool = False
    # How many shipments one sweep will attempt, so a large backlog cannot monopolise the worker.
    SHIPMENT_TRACKING_BATCH_SIZE: int = 100

    # --- Downstream integration: tracker, SAP, DMS () ---------------------------------
    # The tracker workbook this platform writes an approved deal into, addressed the way Graph
    # addresses a file: the drive that holds it and the item id of the workbook inside it.
    #
    # Every value in this block is a PLACEHOLDER pending AGFZE's confirmation of which workbook,
    # which sheet and which columns are the live tracker. The Excel client behind them is real,
    # complete and row-level; only its target is unknown. Left unset, the tracker job reaches
    # `awaiting_manual_action` exactly as an unconfigured SAP or DMS job does - it never guesses
    # a workbook and never silently skips.
    TRACKER_DRIVE_ID: str = ""
    TRACKER_WORKBOOK_ITEM_ID: str = ""
    TRACKER_WORKSHEET_NAME: str = "Tracker"
    TRACKER_TABLE_NAME: str = ""
    # The column whose value identifies the row for a batch. Rows are matched on it, updated in
    # place through it, and appended only when it matches nothing.
    TRACKER_KEY_COLUMN: str = "Batch Number"
    # Which transaction field goes in which tracker column, as {field: column header}. JSON in
    # the environment. Empty means unconfigured, which is the shipped default.
    # NoDecode for the same reason JWT_ALGORITHMS carries it: without it pydantic-settings
    # JSON-decodes the dotenv value before any field validator runs, so the shipped blank default
    # in .env.example raises a SettingsError at import and the process never starts. The parsing
    # this field actually wants - blank means unconfigured, otherwise a JSON object - lives in
    # _parse_column_map below.
    TRACKER_COLUMN_MAP: Annotated[dict[str, str], NoDecode] = {}

    # SAP. Null base URL is the normal, expected state and the trigger for the manual-preparation
    # path - not an error. No confirmed API/BAPI/OData endpoint for AGFZE's SAP exists anywhere in
    # this platform's material, so none is guessed at here; the adapter calls what a deployment
    # configures and prepares a reviewable payload for a person when nothing is configured.
    SAP_API_BASE_URL: str = ""
    # The service path the posting is sent to, relative to the base URL. Configurable because the
    # object name is exactly the thing that is unknown; it is never used unless a base URL is set.
    SAP_POSTING_PATH: str = ""
    SAP_API_USERNAME: str = ""
    SAP_API_PASSWORD: str = ""
    SAP_API_KEY: str = ""
    SAP_COMPANY_CODE: str = ""
    # The Business Area a posting is booked under. Discovery named 1070 for AGFZE specifically, so
    # unlike the endpoint above this one has a real value behind it rather than a placeholder -
    # but it stays configuration rather than a literal for the same reason every other SAP value
    # does: a second entity, or a reorganisation, changes it without changing this code.
    SAP_BUSINESS_AREA: str = "1070"
    SAP_TIMEOUT_SECONDS: float = 30.0

    # The document-management system. Same pattern, same reasoning: a REST upload is what it
    # exposes, but its endpoint contract and metadata schema are not specified, so nothing is
    # invented and an unconfigured deployment prepares the pack for a person instead.
    DMS_API_BASE_URL: str = ""
    DMS_UPLOAD_PATH: str = ""
    DMS_API_KEY: str = ""
    DMS_API_USERNAME: str = ""
    DMS_API_PASSWORD: str = ""
    DMS_REPOSITORY: str = ""
    DMS_TIMEOUT_SECONDS: float = 60.0

    # Retry and backoff. The first genuinely time-driven sweep in this build: an attempt that
    # failed for a transient reason has a real next attempt due at a real time, which is what a
    # periodic job is for. Earlier  declined to add one because nothing consumed it.
    INTEGRATION_SWEEP_ENABLED: bool = True
    INTEGRATION_SWEEP_INTERVAL_SECONDS: int = 60
    INTEGRATION_SWEEP_BATCH_SIZE: int = 50
    INTEGRATION_MAX_ATTEMPTS: int = 5
    # 60s, 120s, 240s, 480s, capped. Short enough that a blip resolves itself within the hour,
    # long enough that a system which is genuinely down is not hammered.
    INTEGRATION_RETRY_BASE_SECONDS: int = 60
    INTEGRATION_RETRY_MAX_SECONDS: int = 3600

    # --- Dashboard, analytics and reporting () --------------------------------------------
    # Every aggregate is computed from the governed tables on every miss. The cache exists so a
    # room full of people opening the same dashboard at nine in the morning does not run the same
    # eight grouped counts eight hundred times, and it is deliberately short: a figure forty-five
    # seconds old is still a true statement about the platform, and one ten minutes old is not.
    # In-process by design - this platform's user base is bounded, and a cache server would be a
    # new piece of infrastructure to run for no measurable gain.
    DASHBOARD_CACHE_TTL_SECONDS: int = 45
    DASHBOARD_CACHE_MAX_ENTRIES: int = 512

    # Scheduled report generation. It rides the periodic sweep  introduced rather than a
    # scheduler of its own: that loop is already awake every minute, and all this needs from it is
    # to be asked "is anything due?" on the way past.
    REPORT_SCHEDULE_ENABLED: bool = True
    # UTC, because the platform stores and reasons in UTC everywhere else. 06:00 puts the daily
    # summary in place before the Dubai desk opens.
    REPORT_DAILY_HOUR_UTC: int = 6
    REPORT_DAILY_MINUTE_UTC: int = 0
    # The 1st of the month, covering the month that has just ended.
    REPORT_MONTHLY_DAY: int = 1
    REPORT_MONTHLY_HOUR_UTC: int = 7
    REPORT_MONTHLY_MINUTE_UTC: int = 0
    # Storage key prefix for generated report files. Served only through the existing signed-URL
    # download route; there is no permanent public path to any of them.
    REPORT_STORAGE_PREFIX: str = "reports"

    # --- Graph projection ------------------------------------------------------------------------
    # A derived, rebuildable read model of the relational data, for traceability questions that are
    # expensive as recursive SQL. Off and unconfigured by default: it is a real infrastructure
    # commitment, and nothing on the platform depends on it - every value it holds is read from
    # PostgreSQL first.
    GRAPH_SYNC_ENABLED: bool = False
    NEO4J_URI: str = ""
    NEO4J_USER: str = ""
    NEO4J_PASSWORD: str = ""
    NEO4J_DATABASE: str = "neo4j"
    # How often the projection catches up with the relational store, in seconds.
    GRAPH_SYNC_INTERVAL_SECONDS: int = 300
    GRAPH_SYNC_BATCH_SIZE: int = 500

    # --- Document retention ----------------------------------------------------------------------
    # Off, with no period, in dry run. All three are deliberate: the BRD asks for a retention
    # policy and says in its own words that the period is AGFZE's to confirm, so shipping a default
    # would be inventing a number that silently ages out trade documents nobody agreed to lose.
    # See app/services/analytics/retention.py.
    DOCUMENT_RETENTION_ENABLED: bool = False
    # 0 means unset, not "immediately". The sweep refuses to run on it whatever the flag says.
    DOCUMENT_RETENTION_DAYS: int = 0
    # Even fully configured, the job reports what it would flag and touches nothing until this is
    # false. And what it does then is write an audit row for a person to review - never a deletion.
    DOCUMENT_RETENTION_DRY_RUN: bool = True
    # Rows one generated report will render into a detail table, so a report over a year of
    # trading stays a document somebody can open rather than a thousand-page export.
    REPORT_MAX_DETAIL_ROWS: int = 500
    # Whether the monthly management report asks the model for its one-paragraph summary. The
    # report generates identically without it; the paragraph is simply marked unavailable.
    REPORT_AI_SUMMARY_ENABLED: bool = True

    # --- Delivery channels: email and push () --------------------------------------------
    # Where a notification's call-to-action points. Every link a `Notification` carries is a
    # relative in-app path, so this is the only place an absolute URL is ever assembled - and it
    # is assembled from configuration rather than from a request header, which is what keeps a
    # forged Host from rewriting the button in an email nobody can un-send.
    APP_BASE_URL: str = "http://localhost:3000"

    # The outbound relay. An unset host means email delivery is not configured on this
    # deployment, which is the shipped default and an honest state: the in-app row is still
    # written for every recipient, and nothing pretends a message left the building.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_ADDRESS: str = "command-centre@agfze.ae"
    SMTP_FROM_NAME: str = "AGFZE Command Centre"
    # STARTTLS on the standard submission port. Turned off only for a local catcher (MailHog),
    # which speaks plain SMTP on 1025 and has no certificate to present.
    SMTP_STARTTLS: bool = True
    SMTP_TIMEOUT_SECONDS: float = 20.0
    # Three attempts, per this 's specification. 2s, then 4s.
    EMAIL_MAX_ATTEMPTS: int = 3
    EMAIL_RETRY_BASE_SECONDS: float = 2.0

    # Web Push. The public half is meant to be public - the standard hands it to the browser to
    # subscribe with - and is exposed through its own endpoint and to the frontend build. The
    # private half signs the delivery and never leaves this process. Regenerating the pair
    # invalidates every subscription ever taken, so it is generated once per environment.
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    # The `sub` claim on the signed JWT. A mailto: the push service can reach a human on.
    VAPID_SUBJECT: str = "mailto:command-centre@agfze.ae"
    # How long a push service holds an undelivered message for. A day: a decision that has been
    # waiting longer than that is not news the browser should surface on wake.
    PUSH_TTL_SECONDS: int = 86400

    # The master switch for both channels. Off, `notify` writes the in-app row exactly as 
    # did and dispatches nothing - which is what the test suite runs with unless a test opts in.
    NOTIFICATION_DELIVERY_ENABLED: bool = True

    # --- Document intake ------------------------------------------------------------------------
    MAX_UPLOAD_BYTES: int = 25 * 1024 * 1024
    UPLOAD_CHUNK_BYTES: int = 1024 * 1024
    PAGE_RASTER_DPI: int = 150
    # Pages handed to the multimodal model in one call. Small windows keep a page's evidence
    # attributable to that page and keep a single failure from losing the whole document.
    EXTRACTION_PAGE_WINDOW: int = 2
    EXTRACTION_MAX_PAGES: int = 40

    @property
    def keycloak_admin_configured(self) -> bool:
        """Whether the role-override path has a real credential to call Keycloak with.

        False is a legitimate state on a developer machine that has not seeded the admin client.
        The endpoint says so plainly and changes nothing, rather than half-applying a role change
        locally that Keycloak has never heard of.
        """
        return bool(
            self.KEYCLOAK_SERVER_URL.strip()
            and self.KEYCLOAK_REALM.strip()
            and self.KEYCLOAK_ADMIN_CLIENT_ID.strip()
            and self.KEYCLOAK_ADMIN_CLIENT_SECRET.strip()
        )

    @property
    def email_configured(self) -> bool:
        """Whether there is a relay to hand a message to.

        False is a legitimate state, and the only thing it costs is the email copy: the in-app
        notification - the platform's durable record - is written either way.
        """
        return bool(self.SMTP_HOST.strip() and self.SMTP_FROM_ADDRESS.strip())

    @property
    def push_configured(self) -> bool:
        """Both halves of the VAPID pair. One without the other cannot sign a delivery."""
        return bool(self.VAPID_PUBLIC_KEY.strip() and self.VAPID_PRIVATE_KEY.strip())

    @property
    def graph_configured(self) -> bool:
        return bool(
            self.AZURE_AD_TENANT_ID.strip()
            and self.AZURE_AD_CLIENT_ID.strip()
            and self.AZURE_AD_CLIENT_SECRET.strip()
            and self.GRAPH_MAILBOX_ADDRESS.strip()
        )

    @property
    def reply_configured(self) -> bool:
        """Whether this deployment can actually send a reply, rather than only compose one."""
        return bool(self.graph_configured and self.GRAPH_REPLY_ENABLED)

    @property
    def ai_configured(self) -> bool:
        return bool(self.GEMINI_API_KEY.strip())

    @property
    def tracker_configured(self) -> bool:
        """Whether a real workbook, table and column mapping have been confirmed and set.

        The Graph credentials are part of the answer because the tracker is written through the
        same app registration the mailbox is read with. Anything missing means the tracker job
        prepares itself for a person instead of writing a row into a workbook nobody named.
        """
        return bool(
            self.graph_configured
            and self.TRACKER_DRIVE_ID.strip()
            and self.TRACKER_WORKBOOK_ITEM_ID.strip()
            and self.TRACKER_TABLE_NAME.strip()
            and self.TRACKER_KEY_COLUMN.strip()
            and self.TRACKER_COLUMN_MAP
        )

    @property
    def neo4j_configured(self) -> bool:
        """Whether a graph *store* has been named.

        Deliberately not called `graph_configured`: that name is already taken by Microsoft Graph,
        the mailbox API, and two properties a letter apart meaning entirely different integrations
        is how somebody eventually gates the mailbox poller on Neo4j being reachable.
        """
        return bool(
            self.NEO4J_URI.strip() and self.NEO4J_USER.strip() and self.NEO4J_PASSWORD.strip()
        )

    @property
    def sap_configured(self) -> bool:
        return bool(self.SAP_API_BASE_URL.strip())

    @property
    def dms_configured(self) -> bool:
        return bool(self.DMS_API_BASE_URL.strip())

    @field_validator("TRACKER_COLUMN_MAP", mode="before")
    @classmethod
    def _parse_column_map(cls, value: Any) -> Any:
        """Accept the mapping as JSON from the environment, and treat blank as unconfigured."""
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return {}
            import json

            try:
                parsed = json.loads(text)
            except ValueError as exc:
                raise ValueError(
                    "TRACKER_COLUMN_MAP must be a JSON object of {field: column header}."
                ) from exc
            if not isinstance(parsed, dict):
                raise ValueError("TRACKER_COLUMN_MAP must be a JSON object, not a list or scalar.")
            return {str(key): str(item) for key, item in parsed.items()}
        return value

    @field_validator("JWT_ALGORITHMS", "CORS_ALLOWED_ORIGINS", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.ENV.strip().lower() == "production"

    @property
    def is_development(self) -> bool:
        return self.ENV.strip().lower() == "development"

    @property
    def is_testing(self) -> bool:
        return self.ENV.strip().lower() == "testing"


class DevelopmentSettings(Settings):
    ENV: str = "development"


class TestingSettings(Settings):
    ENV: str = "testing"
    RATE_LIMIT_ENABLED: bool = False


class ProductionSettings(Settings):
    ENV: str = "production"
    # Not a toggle somebody has to remember: the production profile *is* the enabled profile, and
    # the validator below refuses to start if an environment variable has turned it back off.
    RATE_LIMIT_ENABLED: bool = True
    # Both services sit behind the WAF and load balancer described in infra/production, so the
    # forwarded client address is set by infrastructure this deployment owns.
    RATE_LIMIT_TRUST_FORWARDED_FOR: bool = True
    DATABASE_ECHO: bool = False

    @model_validator(mode="after")
    def _require_production_values(self) -> ProductionSettings:
        problems: list[str] = []
        if not self.KEYCLOAK_ISSUER.strip():
            problems.append("KEYCLOAK_ISSUER is required")
        if not self.KEYCLOAK_JWKS_URL.strip():
            problems.append("KEYCLOAK_JWKS_URL is required")
        if not self.DATABASE_URL.strip() or self.DATABASE_URL == DEFAULT_DATABASE_URL:
            problems.append(
                "DATABASE_URL must point at the production database, not the local default"
            )
        if "*" in self.CORS_ALLOWED_ORIGINS:
            problems.append('CORS_ALLOWED_ORIGINS must list exact origins and must not contain "*"')
        # A backend that names no bucket cannot store anything, and would fail on the first
        # document rather than at start-up - which is the wrong end of the deployment to find out.
        if self.STORAGE_BACKEND.strip().lower() != "local" and not self.STORAGE_BUCKET.strip():
            problems.append("STORAGE_BUCKET is required whenever STORAGE_BACKEND is not 'local'")
        if self.STORAGE_SIGNED_URL_SECRET == DEFAULT_SIGNED_URL_SECRET:
            problems.append(
                "STORAGE_SIGNED_URL_SECRET must be changed from the development default"
            )
        # Intake is the whole point of the deployment: a missing credential must stop the process
        # here rather than surface later as a silent mailbox that never delivers anything.
        # Role assignment is normally group-mapped from Entra ID, but the manual override is a
        # shipped, named capability of the admin module - a screen that cannot work because its
        # credential was never set is worse than a deployment that refuses to start.
        for name in (
            "KEYCLOAK_SERVER_URL",
            "KEYCLOAK_ADMIN_CLIENT_ID",
            "KEYCLOAK_ADMIN_CLIENT_SECRET",
        ):
            if not str(getattr(self, name, "")).strip():
                problems.append(f"{name} is required")
        for name in (
            "AZURE_AD_TENANT_ID",
            "AZURE_AD_CLIENT_ID",
            "AZURE_AD_CLIENT_SECRET",
            "GRAPH_MAILBOX_ADDRESS",
            "GEMINI_API_KEY",
        ):
            if not str(getattr(self, name, "")).strip():
                problems.append(f"{name} is required")
        if not self.AI_PROVIDER.strip():
            problems.append("AI_PROVIDER is required")
        if not 0.0 < self.CONFIDENCE_THRESHOLD_DEFAULT <= 1.0:
            problems.append("CONFIDENCE_THRESHOLD_DEFAULT must be between 0 and 1")
        # 's two delivery channels. A production deployment that cannot email an approver
        # and cannot push to their phone is the exact failure this  exists to remove, so a
        # missing relay or an ungenerated VAPID pair stops the process here rather than being
        # discovered the first time a deal stalls.
        for name in ("SMTP_HOST", "VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY"):
            if not str(getattr(self, name, "")).strip():
                problems.append(f"{name} is required")
        if not self.APP_BASE_URL.strip() or "localhost" in self.APP_BASE_URL:
            problems.append(
                "APP_BASE_URL must be this deployment's own public origin - every email "
                "call-to-action is built from it"
            )
        if self.GRAPH_WEBHOOK_ENABLED and not self.GRAPH_WEBHOOK_CLIENT_STATE.strip():
            problems.append(
                "GRAPH_WEBHOOK_CLIENT_STATE is required whenever GRAPH_WEBHOOK_ENABLED is on"
            )
        # Rate limiting is not optional in production, and the boolean is not the whole of it:
        # a profile that is enabled but configured with an empty or unparseable limit would pass
        # a naive check and enforce nothing.
        if not self.RATE_LIMIT_ENABLED:
            problems.append("RATE_LIMIT_ENABLED must stay on in production")
        for name in (
            "RATE_LIMIT_DEFAULT",
            "RATE_LIMIT_AUTH",
            "RATE_LIMIT_UPLOAD",
            "RATE_LIMIT_AI",
            "RATE_LIMIT_BULK_APPROVAL",
            "RATE_LIMIT_WEBHOOK",
        ):
            value = str(getattr(self, name, "")).strip()
            if not value:
                problems.append(f"{name} is required")
        # Where the counters live is part of whether a limit means anything. In-process counting
        # is per-instance, so with N instances serving, every limit above is silently N times more
        # permissive than it reads - and the bulk-approval limit is one of them.
        #
        # Refused rather than warned about, because a warning on a start-up line nobody reads is
        # how a limit ends up multiplied in production for a year. The escape hatch exists for a
        # genuinely single-instance deployment, and requires saying so explicitly.
        storage = self.RATE_LIMIT_STORAGE_URI.strip()
        if not storage:
            problems.append("RATE_LIMIT_STORAGE_URI is required")
        elif storage.startswith("memory://") and not self.RATE_LIMIT_ALLOW_IN_PROCESS:
            problems.append(
                "RATE_LIMIT_STORAGE_URI is in-process, which counts every limit per instance "
                "rather than across the fleet. Point it at the shared store this deployment "
                "provisions, or set RATE_LIMIT_ALLOW_IN_PROCESS=true to accept per-instance "
                "counting on a deliberately single-instance deployment"
            )
        if problems:
            raise ValueError(
                "Refusing to start with an unsafe production configuration: " + "; ".join(problems)
            )
        return self


_SETTINGS_BY_ENV: dict[str, type[Settings]] = {
    "development": DevelopmentSettings,
    "testing": TestingSettings,
    "production": ProductionSettings,
}


@lru_cache
def get_settings() -> Settings:
    env = os.getenv("ENV", "development").strip().lower()
    return _SETTINGS_BY_ENV.get(env, DevelopmentSettings)()


settings = get_settings()
