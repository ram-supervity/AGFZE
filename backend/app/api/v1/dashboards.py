"""The two aggregate endpoints behind the Dashboard and the Analytics page.

Open to every signed-in account, and scoped for every one of them. The scope is derived from the
caller's roles and applied inside the queries themselves, so the constraint lives in the `WHERE`
clause rather than in which tile the browser chose to render. An account holding no recognised
role reaches an honest set of zeros rather than an unfiltered count.

Both endpoints are read-only in the strongest sense: nothing in this module, or anything it calls,
writes to a transaction, an exception, an approval or an integration job. The only rows this 
creates anywhere are its own reports and the audit and job rows behind them.

Results are cached in-process for a short, configurable TTL, keyed on the scope as well as the
parameters, so a cache hit can never hand one role a figure computed under another's visibility.
The age of what was served is returned in the payload rather than hidden.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query

from app.core.dependencies import CurrentUser, DbSession
from app.db.base import utcnow
from app.models.enums import BUSINESS_STREAMS
from app.schemas.analytics import DashboardSummary, KpiTrends
from app.schemas.common import ResponseEnvelope
from app.services.analytics import kpis
from app.services.analytics.cache import build_key, dashboard_cache
from app.services.analytics.scope import scope_for

router = APIRouter(prefix="/dashboards", tags=["dashboards"])

# A year is as far back as either screen will aggregate in one request. Not a permission - it is
# a bound on how much work one query may do, and the report builder is the way to ask for more.
MAX_RANGE_DAYS = 366


def _normalise_stream(stream: str | None) -> str | None:
    return stream if stream in BUSINESS_STREAMS else None


def _window(
    date_from: datetime | None, date_to: datetime | None, *, default_days: int
) -> kpis.Period:
    now = utcnow()
    end = date_to or now
    start = date_from or (end - timedelta(days=default_days))
    if end <= start:
        start = end - timedelta(days=default_days)
    if (end - start).days > MAX_RANGE_DAYS:
        start = end - timedelta(days=MAX_RANGE_DAYS)
    return kpis.Period(start=start, end=end)


def _age(stored_at: float) -> float:
    return max(0.0, time.monotonic() - stored_at)


def _served(payload: dict[str, Any], age: float) -> dict[str, Any]:
    return {
        **payload,
        "cache_age_seconds": round(age, 2),
        "cache_ttl_seconds": dashboard_cache().ttl_seconds,
    }


@router.get(
    "/summary",
    response_model=ResponseEnvelope[DashboardSummary],
    summary="Role-scoped aggregate counts for the dashboard",
)
async def read_summary(
    user: CurrentUser,
    session: DbSession,
    stream: str | None = Query(None),
) -> ResponseEnvelope[DashboardSummary]:
    scope = scope_for(user).narrowed_to(_normalise_stream(stream))
    cache = dashboard_cache()
    key = build_key("dashboard.summary", scope.cache_key(), _normalise_stream(stream))

    entry = cache.get(key)
    if entry is not None:
        return ResponseEnvelope[DashboardSummary](
            data=DashboardSummary.model_validate(_served(entry.value, _age(entry.stored_at)))
        )

    payload = await kpis.build_summary(session, scope)
    cache.set(key, payload)
    return ResponseEnvelope[DashboardSummary](
        data=DashboardSummary.model_validate(_served(payload, 0.0))
    )


@router.get(
    "/kpis",
    response_model=ResponseEnvelope[KpiTrends],
    summary="Trend-oriented KPI data over a chosen date range",
)
async def read_kpis(
    user: CurrentUser,
    session: DbSession,
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    stream: str | None = Query(None),
    interval: str = Query("day", pattern="^(day|week)$"),
) -> ResponseEnvelope[KpiTrends]:
    narrowed = _normalise_stream(stream)
    scope = scope_for(user).narrowed_to(narrowed)
    period = _window(date_from, date_to, default_days=90)

    cache = dashboard_cache()
    key = build_key(
        "dashboard.kpis",
        scope.cache_key(),
        narrowed,
        interval,
        period.start.isoformat(),
        period.end.isoformat(),
    )

    entry = cache.get(key)
    if entry is not None:
        return ResponseEnvelope[KpiTrends](
            data=KpiTrends.model_validate(_served(entry.value, _age(entry.stored_at)))
        )

    payload = await kpis.build_kpis(session, scope, period, interval=interval)
    cache.set(key, payload)
    return ResponseEnvelope[KpiTrends](data=KpiTrends.model_validate(_served(payload, 0.0)))
