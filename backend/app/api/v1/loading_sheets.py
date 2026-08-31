"""The Loading Sheet: every batch that has been confirmed, in the columns the workbook carries.

Read-only, and deliberately. A row here is written by the confirmation of a purchase transaction
and drained into AGFZE's workbook by the integration worker; there is no endpoint that lets a
person type one in, because a Loading Sheet row that did not come from a confirmed transaction
would be a figure with no deal behind it.

Scoped exactly as the transaction list is, by the same `visible_streams` the transaction service
already computes: a row is a view onto a transaction, so whoever may see the transaction may see
the row and nobody else may.
"""

from __future__ import annotations

from datetime import timezone

from fastapi import APIRouter, Query

from app.core.dependencies import CurrentUser, DbSession
from app.core.errors import NotFoundError
from app.db.base import utcnow
from app.models.enums import LOADING_SHEET_SYNC_STATUSES
from app.schemas.common import ResponseEnvelope
from app.schemas.intake import Page
from app.schemas.loading_sheet import LoadingSheetList, LoadingSheetRowRead
from app.services import transaction_service
from app.services.integration import loading_sheet

router = APIRouter(prefix="/loading-sheets", tags=["loading-sheets"])


def _read(row) -> LoadingSheetRowRead:
    read = LoadingSheetRowRead.model_validate(row)
    created = row.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    read.age_days = max(0, (utcnow() - created).days)
    return read


@router.get(
    "",
    response_model=ResponseEnvelope[LoadingSheetList],
    summary="Paginated, filterable Loading Sheet",
)
async def list_loading_sheet_rows(
    user: CurrentUser,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: str | None = Query(None, max_length=200),
    sync_status: str | None = Query(None),
    supplier: str | None = Query(None, max_length=255),
    commodity_code: str | None = Query(None, max_length=32),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
) -> ResponseEnvelope[LoadingSheetList]:
    if sync_status and sync_status not in LOADING_SHEET_SYNC_STATUSES:
        sync_status = None

    statement = loading_sheet.apply_visibility(
        loading_sheet.list_query(
            search=search,
            sync_status=sync_status,
            supplier=supplier,
            commodity_code=commodity_code,
        ),
        transaction_service.visible_streams(user),
    )
    total = await loading_sheet.count(session, statement)

    order = (
        loading_sheet.LoadingSheetRow.created_at.asc()
        if sort_dir == "asc"
        else loading_sheet.LoadingSheetRow.created_at.desc()
    )
    rows = (
        await session.scalars(
            statement.order_by(order).offset((page - 1) * page_size).limit(page_size)
        )
    ).all()

    return ResponseEnvelope[LoadingSheetList](
        data=LoadingSheetList(
            items=[_read(row) for row in rows],
            page=Page(
                page=page,
                page_size=page_size,
                total=total,
                total_pages=max(1, -(-total // page_size)),
            ),
            workbook_configured=loading_sheet.workbook_configured(),
        )
    )


@router.get(
    "/{batch_number}",
    response_model=ResponseEnvelope[LoadingSheetRowRead],
    summary="One batch's Loading Sheet row",
)
async def read_loading_sheet_row(
    batch_number: str, user: CurrentUser, session: DbSession
) -> ResponseEnvelope[LoadingSheetRowRead]:
    statement = loading_sheet.apply_visibility(
        loading_sheet.list_query(), transaction_service.visible_streams(user)
    ).where(loading_sheet.LoadingSheetRow.batch_number == batch_number)
    row = await session.scalar(statement)
    if row is None:
        raise NotFoundError("No Loading Sheet row exists for that batch.")
    return ResponseEnvelope[LoadingSheetRowRead](data=_read(row))
