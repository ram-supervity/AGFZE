"""Generated reports: the list, the ad-hoc request, and one report's full detail.

Reading a report is open to every signed-in account, on the same transparency principle the
exception and approval queues already follow: a report that only its author can open is a report
that ends up being emailed around as an attachment, which is the habit this platform exists to
break. Asking for a new one is narrower - Admin and Approver/HOD - and is enforced here, on the
server, rather than by which button the browser drew.

Generation runs as a tracked background job through the exact `job_service` and
`GET /jobs/{job_id}/status` endpoint  established and every  since has reused. There is
no second job mechanism here.

The file itself is never handed out as a path. `download_url` is minted per request as a
short-lived signed URL through the same authenticated route every document in this platform is
served through, so a link that leaks is a link that expires.

Nothing in this module sends a report anywhere, and no response from it claims that anything was
sent. Distribution arrives with the notification ; until it does, every report says plainly
that it was generated and stored and nothing more.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.dependencies import CurrentUser, DbSession, require_roles
from app.core.roles import PlatformRole
from app.models.identity import User
from app.models.reporting import REPORT_FORMATS, REPORT_STREAMS, REPORT_TYPES, Report
from app.schemas.analytics import (
    ReportCreate,
    ReportDetail,
    ReportGenerationAccepted,
    ReportList,
    ReportListItem,
)
from app.schemas.common import ResponseEnvelope
from app.schemas.intake import Page
from app.services.analytics import report_service
from app.services.analytics.kpis import Period

router = APIRouter(prefix="/reports", tags=["reports"])

# Who may ask for a report to be produced. Reading one is open to every signed-in account.
ReportRequester = Annotated[
    User,
    Depends(require_roles(PlatformRole.ADMIN.value, PlatformRole.APPROVER_HOD.value)),
]


def _item(report: Report) -> ReportListItem:
    item = ReportListItem.model_validate(report)
    item.generated_by_name = report.generated_by.display_name if report.generated_by else None
    item.scheduled = report.generated_by_id is None
    return item


@router.get(
    "",
    response_model=ResponseEnvelope[ReportList],
    summary="Every report generated so far, scheduled and ad-hoc alike",
)
async def list_reports(
    user: CurrentUser,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    report_type: str | None = Query(None),
    output_format: str | None = Query(None),
    stream: str | None = Query(None),
) -> ResponseEnvelope[ReportList]:
    statement = report_service.list_query(
        report_type=report_type if report_type in REPORT_TYPES else None,
        output_format=output_format if output_format in REPORT_FORMATS else None,
        stream=stream if stream in REPORT_STREAMS else None,
    )
    total = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = list(
        (
            await session.scalars(
                statement.options(selectinload(Report.generated_by))
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )

    return ResponseEnvelope[ReportList](
        data=ReportList(
            items=[_item(row) for row in rows],
            page=Page(
                page=page,
                page_size=page_size,
                total=total,
                total_pages=max(1, -(-total // page_size)),
            ),
            can_generate=report_service.may_generate(user),
        )
    )


@router.post(
    "",
    response_model=ResponseEnvelope[ReportGenerationAccepted],
    status_code=202,
    summary="Generate a report now, as a tracked background job",
)
async def create_report(
    payload: ReportCreate,
    user: ReportRequester,
    session: DbSession,
) -> ResponseEnvelope[ReportGenerationAccepted]:
    """Queue one generation. Every call produces a new report; nothing is ever overwritten.

    Two requests with byte-for-byte identical parameters produce two distinct rows with two
    distinct generation references, exactly as regenerating a sales draft produces a second draft
    beside the first. A report is a statement about the moment it was produced, and rewriting one
    would silently change a document somebody may already be holding.
    """
    request = report_service.validate_request(
        report_type=payload.report_type,
        output_format=payload.output_format,
        period=Period(start=payload.date_from, end=payload.date_to),
        stream=payload.stream,
        status_filter=payload.status,
    )
    job_id = await report_service.queue_generation(session, request, requested_by=user)
    return ResponseEnvelope[ReportGenerationAccepted](
        data=ReportGenerationAccepted(
            job_id=job_id,
            poll_url=f"/api/v1/jobs/{job_id}/status",
            message=(
                "The report is being generated. It will be stored in the platform and listed "
                "here when it is ready; it is not sent to anybody."
            ),
        ),
        message="Report generation started.",
    )


@router.get(
    "/{report_id}",
    response_model=ResponseEnvelope[ReportDetail],
    summary="One report in full, with every figure's drill-through filters",
)
async def read_report(
    report_id: UUID, user: CurrentUser, session: DbSession
) -> ResponseEnvelope[ReportDetail]:
    report = await report_service.get_report(session, report_id)
    detail = ReportDetail(
        **_item(report).model_dump(),
        parameters=report.parameters,
        content=report.content,
        audit_event_id=report.audit_event_id,
        # Minted per request, short-lived and signed, through the same authenticated route every
        # other stored file in this platform is served by.
        download_url=await report_service.download_url(report),
    )
    return ResponseEnvelope[ReportDetail](data=detail)
