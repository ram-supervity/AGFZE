from fastapi import APIRouter

from app.api.v1 import (
    admin,
    approvals,
    audit,
    dashboards,
    documents,
    exceptions,
    graph_notifications,
    health,
    integrations,
    jobs,
    notifications,
    reports,
    requests,
    shipments,
    transactions,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(users.router)
api_router.include_router(notifications.router)
api_router.include_router(jobs.router)
api_router.include_router(dashboards.router)
api_router.include_router(reports.router)
api_router.include_router(requests.router)
api_router.include_router(documents.router)
api_router.include_router(transactions.router)
api_router.include_router(shipments.router)
api_router.include_router(exceptions.router)
api_router.include_router(approvals.router)
api_router.include_router(integrations.router)
api_router.include_router(admin.router)
api_router.include_router(audit.router)
api_router.include_router(graph_notifications.router)

__all__ = [
    "admin",
    "api_router",
    "approvals",
    "audit",
    "dashboards",
    "documents",
    "exceptions",
    "graph_notifications",
    "health",
    "integrations",
    "jobs",
    "notifications",
    "reports",
    "requests",
    "shipments",
    "transactions",
    "users",
]
