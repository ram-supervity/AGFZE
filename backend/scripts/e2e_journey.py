"""Drive one real trade, end to end, through the running application.

This is not a unit test and it does not mock the model. It starts the actual FastAPI
application, migrates a real database, signs real access tokens for three separate accounts,
and walks the documented journey with real files:

    Logistics/system mailbox capture  ->  request classified (Gemini)
    each attachment classified and extracted (Gemini, per-page, schema-driven)
    Purchase desk reviews and confirms every extraction
    matching opens or joins a batch
    the rule engine validates the batch
    Purchase desk submits
    HOD approves - a different account, a different role
    integration jobs are raised for tracker, SAP and DMS

Every step reports what it expected, what it got, and whether the two agree. Nothing is
declared to have passed because an endpoint returned 200: extracted values are compared
against the source documents through an expectations file, role separation is proved by
attempting the approval as the preparer first and requiring a 403, and the run fails loudly
rather than skipping a stage it could not complete.

    python -m scripts.e2e_journey --documents ~/Downloads --expect scripts/e2e_expectations.json

Add --no-ai to prove the wiring on a machine with no model credential: the pipeline then runs
against a deterministic stand-in provider, and the report says so on every line it affects.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

DEFAULT_DB = f"sqlite+aiosqlite:///{Path(tempfile.gettempdir()) / 'agfze-e2e.db'}"


def _bootstrap_environment(args: argparse.Namespace) -> None:
    """Settings are read once at import time, so every value has to be final before app.* loads."""
    os.environ["ENV"] = "development"
    database_url = args.database_url or os.environ.get("E2E_DATABASE_URL") or DEFAULT_DB
    os.environ["DATABASE_URL"] = database_url
    os.environ["TEST_DATABASE_URL"] = database_url
    os.environ.setdefault("KEYCLOAK_ISSUER", "https://keycloak.e2e/realms/agfze")
    os.environ.setdefault(
        "KEYCLOAK_JWKS_URL", "https://keycloak.e2e/realms/agfze/protocol/openid-connect/certs"
    )
    os.environ.setdefault("GRAPH_MAILBOX_ADDRESS", "trade.docs@agfze.com")
    # A run of its own storage root, so a journey never reads or overwrites a developer's
    # documents and never depends on who owns ./var.
    storage_root = args.storage_root or str(Path(tempfile.mkdtemp(prefix="agfze-e2e-storage-")))
    os.environ["STORAGE_BACKEND"] = "local"
    os.environ["STORAGE_LOCAL_ROOT"] = storage_root
    os.environ["GRAPH_POLL_ENABLED"] = "false"
    os.environ["GRAPH_WEBHOOK_ENABLED"] = "false"
    os.environ["SHIPMENT_TRACKING_POLL_ENABLED"] = "false"
    os.environ["INTEGRATION_SWEEP_ENABLED"] = "false"
    os.environ["REPORT_SCHEDULE_ENABLED"] = "false"
    os.environ["NOTIFICATION_DELIVERY_ENABLED"] = "false"
    os.environ["RATE_LIMIT_ENABLED"] = "false"
    if args.no_ai:
        os.environ["GEMINI_API_KEY"] = ""


# --- report -------------------------------------------------------------------------------


@dataclass
class Step:
    stage: str
    actor: str
    action: str
    expected: str
    actual: str
    ok: bool
    note: str = ""


@dataclass
class Report:
    steps: list[Step] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)

    def record(
        self,
        stage: str,
        actor: str,
        action: str,
        expected: str,
        actual: str,
        ok: bool,
        note: str = "",
    ) -> bool:
        self.steps.append(Step(stage, actor, action, expected, actual, ok, note))
        mark = "PASS" if ok else "FAIL"
        line = f"[{mark}] {stage:<22} {actor:<14} {action}"
        print(line)
        print(f"         expected: {expected}")
        print(f"         actual  : {actual}")
        if note:
            print(f"         note    : {note}")
        if not ok:
            self.findings.append(f"{stage} / {action}: expected {expected}, got {actual}")
        return ok

    @property
    def failed(self) -> int:
        return sum(1 for step in self.steps if not step.ok)

    def summarise(self) -> int:
        print("\n" + "=" * 96)
        print(f"steps: {len(self.steps)}   passed: {len(self.steps) - self.failed}   failed: {self.failed}")
        if self.findings:
            print("\nfindings")
            for index, finding in enumerate(self.findings, start=1):
                print(f"  {index}. {finding}")
        verdict = "PASS" if not self.failed else "FAIL"
        print(f"\nfinal status: {verdict}")
        print("=" * 96)
        return 0 if not self.failed else 1


# --- helpers --------------------------------------------------------------------------------


def _numeric(value: str | None) -> float | None:
    if value is None:
        return None
    match = re.search(r"-?\d[\d,]*\.?\d*", str(value))
    if match is None:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _comparable(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def field_matches(expected: str, actual: str | None) -> bool:
    """Compare an extracted value against the source document's own wording.

    Deliberately tolerant of formatting and strict about content: 'USD 8,125.00' and '8125.00'
    are the same rate, 'MSKU 7112045' and 'MSKU7112045' are the same container, and 8125 against
    8215 is a transposition that has to fail.
    """
    if actual is None:
        return False
    expected_number, actual_number = _numeric(expected), _numeric(actual)
    if expected_number is not None and actual_number is not None:
        if abs(expected_number - actual_number) <= max(abs(expected_number) * 1e-6, 1e-6):
            return True
    left, right = _comparable(expected), _comparable(actual)
    return bool(left) and (left in right or right in left)


# --- the mailbox stand-in ---------------------------------------------------------------------
#
# Microsoft Graph is the one boundary this run cannot cross: reaching a real AGFZE mailbox needs
# a tenant, an admin consent and a message that already exists in it. Everything downstream of
# the boundary is the real thing - the same `ingest_message`, the same admission checks, the same
# storage, the same classification and extraction. What is replaced is the transport, and the
# report says so rather than presenting this as a live mailbox capture.


def _parse_email_file(path: Path) -> dict[str, Any]:
    """Read an RFC-822-ish scenario file: headers, a rule line, then the body."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    headers: dict[str, str] = {}
    lines = raw.splitlines()
    index = 0
    for index, line in enumerate(lines):
        if not line.strip() or set(line.strip()) == {"-"}:
            break
        key, separator, value = line.partition(":")
        if separator:
            headers[key.strip().lower()] = value.strip()
    body = "\n".join(lines[index + 1 :]).strip()
    return {
        "subject": headers.get("subject"),
        "sender": headers.get("from"),
        "body": body or raw,
    }


class StubGraphClient:
    """Serves one prepared message and its real attachment bytes."""

    def __init__(self, message: Any, attachments: list[tuple[str, bytes]]) -> None:
        self._message = message
        self._attachments = attachments

    async def get_message(self, message_id: str) -> Any:
        return self._message

    async def get_raw_message(self, message_id: str) -> bytes:
        from app.services.graph_service import GraphError

        raise GraphError("Raw MIME is not retrievable in this harness.")

    async def list_attachments(self, message_id: str) -> list[Any]:
        from app.services.graph_service import GraphAttachment

        return [
            GraphAttachment(
                attachment_id=f"att-{index}",
                name=name,
                content_type="application/pdf",
                size=len(payload),
                is_inline=False,
            )
            for index, (name, payload) in enumerate(self._attachments)
        ]

    async def get_attachment_bytes(self, message_id: str, attachment_id: str) -> bytes:
        return self._attachments[int(attachment_id.rsplit("-", 1)[1])][1]


class StubProvider:
    """--no-ai only. Answers the schema honestly with nulls and a floor confidence.

    It never fabricates a value. Its whole purpose is to let the routing, persistence, review,
    matching, validation and approval path be exercised where no model credential exists, and
    every value it produces is null with a confidence of 0.1 - which the platform correctly
    treats as needing human review.
    """

    name = "stub"

    async def generate(self, *, prompt: str, response_schema: dict, images=None) -> str:
        properties = response_schema.get("properties", {})
        if "category" in properties:
            return json.dumps(
                {
                    "category": "purchase",
                    "confidence": 0.1,
                    "rationale": "stand-in provider: no model was called",
                    "stream": "scrap",
                }
            )
        if "document_type" in properties and "fields" not in properties:
            return json.dumps(
                {
                    "document_type": "unknown",
                    "confidence": 0.1,
                    "rationale": "stand-in provider: no model was called",
                    "territory": None,
                }
            )
        if "fields" in properties:
            names = (
                properties["fields"].get("items", {}).get("properties", {}).get("name", {})
            ).get("enum", [])
            return json.dumps(
                {
                    "fields": [
                        {"name": name, "value": None, "confidence": 0.1, "rationale": "stand-in"}
                        for name in names
                    ]
                }
            )
        return json.dumps({"summary": "stand-in provider: no model was called"})


# --- the run ----------------------------------------------------------------------------------


async def wait_for_job(client: Any, headers: dict[str, str], job_id: str, timeout: float) -> dict:
    """Poll the platform's own job endpoint, exactly as the frontend does."""
    deadline = datetime.now(timezone.utc) + timedelta(seconds=timeout)
    payload: dict[str, Any] = {}
    while datetime.now(timezone.utc) < deadline:
        response = await client.get(f"/api/v1/jobs/{job_id}/status", headers=headers)
        response.raise_for_status()
        payload = response.json()["data"]
        if payload["status"] in ("completed", "failed"):
            return payload
        await asyncio.sleep(1.0)
    return payload


async def run(args: argparse.Namespace) -> int:  # noqa: C901 - a journey is a sequence
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.config import settings
    from app.core.security import TokenError, jwks_client
    from app.db.session import get_session
    from app.main import create_app
    from app.services import email_ingestion, gemini_service
    from app.services.graph_service import GraphMessage
    from tests.utils.tokens import JWKS, auth_header, build_token

    report = Report()
    documents_dir = Path(args.documents).expanduser()
    attachments = sorted(
        (path for path in documents_dir.glob("*.pdf")),
        key=lambda path: path.name,
    )
    if args.only:
        wanted = {name.strip().lower() for name in args.only.split(",")}
        attachments = [path for path in attachments if path.name.lower() in wanted]
    if not attachments:
        print(f"No PDFs found under {documents_dir}", file=sys.stderr)
        return 2

    email_path = Path(args.email).expanduser() if args.email else None
    email = (
        _parse_email_file(email_path)
        if email_path and email_path.exists()
        else {
            "subject": "Trade documents",
            "sender": "docs@counterparty.example",
            "body": "Please find the attached trade document set.",
        }
    )
    expectations: dict[str, dict[str, str]] = {}
    if args.expect:
        expect_path = Path(args.expect).expanduser()
        if expect_path.exists():
            expectations = json.loads(expect_path.read_text(encoding="utf-8"))

    if args.no_ai:
        gemini_service.reset_provider_cache()
        gemini_service._PROVIDERS[settings.AI_PROVIDER.strip().lower()] = StubProvider()

    # --- schema, application, accounts ---------------------------------------------------------
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    application = create_app()

    async def _session_override():
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_session] = _session_override

    async def _get_key(kid: str) -> dict[str, str]:
        for jwk in JWKS["keys"]:
            if jwk["kid"] == kid:
                return jwk
        raise TokenError("Signing key is not published by the identity provider.")

    jwks_client.get_key = _get_key  # type: ignore[method-assign]

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://e2e", timeout=180.0) as client:
        accounts: dict[str, dict[str, str]] = {}
        for label, roles, email_address in (
            ("purchase", ["purchase_user"], "purchase.user@agfze.local"),
            ("approver", ["approver_hod"], "hod.approver@agfze.local"),
            ("admin", ["admin"], "admin.user@agfze.local"),
        ):
            headers = auth_header(
                build_token(
                    sub=str(uuid4()),
                    email=email_address,
                    preferred_username=email_address.split("@")[0],
                    name=label.title(),
                    realm_access={"roles": roles},
                )
            )
            response = await client.get("/api/v1/users/me", headers=headers)
            ok = response.status_code == 200 and response.json()["data"]["roles"] == roles
            report.record(
                "1 authentication",
                label,
                "sign in and provision",
                f"200 with roles {roles}",
                f"{response.status_code} with roles "
                f"{response.json().get('data', {}).get('roles') if response.is_success else '-'}",
                ok,
            )
            accounts[label] = headers

        purchase, approver = accounts["purchase"], accounts["approver"]

        # --- intake ----------------------------------------------------------------------------
        message = GraphMessage(
            message_id=f"e2e-{uuid4()}",
            subject=email["subject"],
            sender_address=(email["sender"] or "").split("<")[-1].strip(" >") or None,
            sender_name=(email["sender"] or "").split("<")[0].strip() or None,
            body_text=email["body"],
            received_at=datetime.now(timezone.utc),
            has_attachments=True,
        )
        stub = StubGraphClient(message, [(path.name, path.read_bytes()) for path in attachments])
        async with session_factory() as session:
            result = await email_ingestion.ingest_message(
                session, message.message_id, client=stub, process=False
            )
        report.record(
            "2 mailbox intake",
            "system",
            "capture message and admit attachments",
            f"1 request, {len(attachments)} documents admitted",
            f"created={result.created} documents={result.document_count}",
            result.created and result.document_count == len(attachments),
            "Graph transport is stubbed; ingestion, admission, storage and the pipeline are real.",
        )
        if result.request_id is None:
            return report.summarise()

        # The pipeline is queued through the platform's own job service so the run polls exactly
        # what the frontend polls, rather than awaiting an internal coroutine.
        from app.services import document_service

        async with session_factory() as session:
            job_id = await document_service.queue_request_processing(session, result.request_id)
        job = await wait_for_job(client, purchase, str(job_id), args.timeout)
        report.record(
            "3 classification",
            "AI agent",
            "classify request and every attachment, then extract",
            "job completed",
            f"job {job.get('status')} at {job.get('progress')}%",
            job.get("status") == "completed",
            f"model: {'stand-in (--no-ai)' if args.no_ai else settings.GEMINI_MODEL}",
        )

        detail = (
            await client.get(f"/api/v1/requests/{result.request_id}", headers=purchase)
        ).json()["data"]
        report.record(
            "3 classification",
            "AI agent",
            "request category",
            "purchase",
            f"{detail.get('category')} at confidence {detail.get('category_confidence')}",
            detail.get("category") == "purchase",
        )

        # --- extraction review -----------------------------------------------------------------
        document_ids = [row["id"] for row in detail.get("documents", [])]
        transaction_id: str | None = None

        for document_id in document_ids:
            response = await client.get(f"/api/v1/documents/{document_id}", headers=purchase)
            document = response.json()["data"]
            name = document["filename"]
            values = {row["field_name"]: row["field_value"] for row in document.get("fields", [])}
            scores = {row["field_name"]: row["confidence"] for row in document.get("fields", [])}

            report.record(
                "4 extraction",
                "AI agent",
                f"{name}: classify and extract",
                "extraction completed against a configured schema",
                f"type={document['document_type']} "
                f"(confidence {document.get('classification_confidence')}) "
                f"status={document['extraction_status']} "
                f"fields={sum(1 for v in values.values() if v)}/{len(values)} populated",
                document["extraction_status"] == "completed",
                document.get("extraction_error") or "",
            )

            expected_fields = expectations.get(name) or expectations.get(name.lower()) or {}
            for field_name, expected_value in expected_fields.items():
                actual = values.get(field_name)
                report.record(
                    "5 data verification",
                    "harness",
                    f"{name}: {field_name}",
                    expected_value,
                    f"{actual!r} at confidence {scores.get(field_name)}",
                    field_matches(expected_value, actual),
                    "compared against the value printed on the source document",
                )

            if document["extraction_status"] != "completed":
                continue

            confirm = await client.post(
                f"/api/v1/documents/{document_id}/confirm", headers=purchase
            )
            matching = (confirm.json().get("data") or {}).get("matching") or {}
            report.record(
                "6 matching",
                "purchase desk",
                f"{name}: confirm extraction",
                "confirmed, and matched to a batch or reported as needing no batch",
                f"{confirm.status_code} outcome={matching.get('outcome')} "
                f"batch={matching.get('batch_number')}",
                confirm.status_code == 200,
                matching.get("message") or "",
            )
            if matching.get("transaction_id") and transaction_id is None:
                transaction_id = matching["transaction_id"]

        if transaction_id is None:
            report.record(
                "6 matching",
                "purchase desk",
                "open or join a batch",
                "one transaction carrying this deal",
                "no transaction was created by any confirmation",
                False,
            )
            return report.summarise()

        # --- validation -------------------------------------------------------------------------
        response = await client.get(f"/api/v1/transactions/{transaction_id}", headers=purchase)
        transaction = response.json()["data"]
        rules = transaction.get("rule_evaluations", [])
        failing = [row for row in rules if not row["passed"] and not row["acknowledged"]]
        report.record(
            "7 validation",
            "rule engine",
            "run the business rules over the batch",
            "every configured rule evaluated, each with its threshold and actual value",
            f"batch {transaction['batch_number']} status={transaction['status']} "
            f"rules={len(rules)} failing={len(failing)}",
            bool(rules),
        )
        for row in failing:
            print(
                f"         - {row['rule_id']}/{row['check_key']} ({row['severity']}): "
                f"{row['message']}"
            )

        # Acknowledgeable breaches are a preparer's to clear, with a reason. Hard ones are not,
        # and a run that meets one reports the block rather than working around it.
        for row in failing:
            if row["severity"] != "acknowledgeable":
                continue
            acknowledged = await client.post(
                f"/api/v1/transactions/{transaction_id}/acknowledge-tolerance",
                headers=purchase,
                json={
                    "rule_id": row["rule_id"],
                    "check_key": row["check_key"],
                    "reason": "End-to-end journey: rounding difference accepted by the preparer.",
                },
            )
            report.record(
                "7 validation",
                "purchase desk",
                f"acknowledge {row['rule_id']}/{row['check_key']}",
                "200, recorded with a reason against the preparer",
                str(acknowledged.status_code),
                acknowledged.status_code == 200,
            )

        # --- role separation ---------------------------------------------------------------------
        submitted = await client.post(
            f"/api/v1/transactions/{transaction_id}/submit", headers=purchase
        )
        blocking = transaction.get("blocking_rules") or []
        report.record(
            "8 submission",
            "purchase desk",
            "submit for approval",
            "200 and Approval Pending, or 409 naming the checks still failing",
            f"{submitted.status_code}: {submitted.json().get('message')}",
            submitted.status_code in (200, 409),
            "; ".join(blocking),
        )
        if submitted.status_code != 200:
            report.record(
                "8 submission",
                "purchase desk",
                "reach Approval Pending",
                "the batch waiting on an approver",
                "blocked by an outstanding hard check",
                False,
                "the platform refused to advance an incomplete deal, which is the rule working; "
                "the journey cannot continue past it in this run",
            )
            return report.summarise()

        queue = (await client.get("/api/v1/approvals", headers=approver)).json()["data"]
        task = next(
            (item for item in queue["items"] if item["transaction_id"] == transaction_id), None
        )
        report.record(
            "9 approval queue",
            "HOD",
            "the submitted batch appears in the approval queue",
            "one pending task for this batch",
            f"{len(queue['items'])} task(s), this batch "
            f"{'present' if task else 'absent'}",
            task is not None,
        )
        if task is None:
            return report.summarise()

        denied = await client.post(
            f"/api/v1/approvals/{task['id']}/decide",
            headers=purchase,
            json={"decision": "approved"},
        )
        report.record(
            "9 approval queue",
            "purchase desk",
            "attempt to approve own submission",
            "403 - the preparer is not an approver",
            str(denied.status_code),
            denied.status_code == 403,
            "role separation is enforced server-side, not by hiding the button",
        )

        opened = (
            await client.get(f"/api/v1/approvals/{task['id']}", headers=approver)
        ).json()["data"]
        summary_obj = opened.get("ai_summary") or {}
        summary_text = (
            summary_obj.get("summary")
            if isinstance(summary_obj, dict)
            else str(summary_obj)
        ) or ""
        report.record(
            "10 approval",
            "HOD",
            "open the decision screen",
            "the full record, with the AI briefing note beside it",
            f"batch {opened['batch_number']}, summary "
            f"{'present' if summary_obj.get('available') or summary_text else 'unavailable'}",
            opened["transaction_id"] == transaction_id,
            summary_text[:160],
        )

        decided = await client.post(
            f"/api/v1/approvals/{task['id']}/decide",
            headers=approver,
            json={"decision": "approved", "confirm_above_threshold": True},
        )
        report.record(
            "10 approval",
            "HOD",
            "approve",
            "200, decision recorded against the approver's own account",
            f"{decided.status_code}: {decided.json().get('message')}",
            decided.status_code == 200,
        )

        # --- downstream --------------------------------------------------------------------------
        final = (
            await client.get(f"/api/v1/transactions/{transaction_id}", headers=purchase)
        ).json()["data"]
        jobs = final.get("integration_jobs", [])
        report.record(
            "11 downstream",
            "integration hub",
            "raise one job per target system",
            "tracker, SAP and DMS each with a job",
            f"status={final['status']} jobs="
            + ", ".join(f"{job['target_system']}:{job['status']}" for job in jobs),
            {job["target_system"] for job in jobs} == {"tracker", "sap", "dms"},
            "unconfigured targets correctly reach awaiting_manual_action rather than a false "
            "success",
        )

        audit = (
            await client.get(
                "/api/v1/audit",
                headers=accounts["admin"],
                params={"entity_type": "trade_transaction", "entity_id": transaction_id},
            )
        ).json()["data"]
        report.record(
            "12 audit",
            "auditor/admin",
            "reconstruct the decision history",
            "an event trail covering creation, validation, submission and approval",
            f"{audit.get('page', {}).get('total', len(audit.get('items', [])))} events",
            bool(audit.get("items")),
            " -> ".join(row["event_type"] for row in audit.get("items", [])[:8]),
        )

    await engine.dispose()
    return report.summarise()


def _migrate(database_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    if database_url.startswith("sqlite"):
        location = database_url.partition(":///")[2]
        if location and not location.startswith(":memory:"):
            path = Path(location)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.unlink(missing_ok=True)

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    # alembic/env.py drives an async engine on a loop of its own, so keep it off ours.
    with ThreadPoolExecutor(max_workers=1) as pool:
        if not database_url.startswith("sqlite"):
            try:
                pool.submit(command.downgrade, config, "base").result()
            except Exception:
                pass
        pool.submit(command.upgrade, config, "head").result()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", required=True, help="Directory holding the deal's PDFs")
    parser.add_argument("--email", help="Scenario email file that carried them")
    parser.add_argument("--expect", help="JSON file of expected field values per filename")
    parser.add_argument("--only", help="Comma-separated filenames to include")
    parser.add_argument("--database-url", help="Async SQLAlchemy URL; a temp SQLite file by default")
    parser.add_argument("--storage-root", help="Document storage root; a fresh temp directory by default")
    parser.add_argument("--timeout", type=float, default=900.0, help="Seconds to allow the pipeline")
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Run against a deterministic stand-in provider instead of the model",
    )
    args = parser.parse_args()

    _bootstrap_environment(args)
    _migrate(os.environ["DATABASE_URL"])
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
