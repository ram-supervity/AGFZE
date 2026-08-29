"""Aggregates, analytics and report generation - the module added in .

Split five ways, and the split is the argument. `scope` decides what one account's queries may
count; `kpis` computes every figure, from the governed tables and nothing else; `report_templates`
holds report structure as configuration rather than layout code; `report_render` turns assembled
content into PDF and XLSX bytes without knowing what any section means; and `report_service` is
the orchestration between them.

The whole package is read-only over the transaction record. Nothing here writes to, or alters, a
`TradeTransaction`, an `ExceptionCase`, an `ApprovalTask`, a `Shipment` or an `IntegrationJob` -
the only rows it creates are the `Report` it produced, the `BackgroundJob` that tracked the
request, and the `AuditEvent` that recorded it.

Deliberately empty of imports, in the same discipline the governance, logistics and integration
packages already follow: `schedule` reaches `report_service`, which reaches `kpis`, so pulling the
whole package in from any of them would make import order matter.
"""
