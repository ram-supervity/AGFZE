"""The integration hub - added in .

Split the same way the logistics package is, and for the same reason. `adapters` is the seam and
carries no implementation; `tracker`, `sap` and `dms` are the three targets, and only one of them
is a real client because only one of them has a specified contract; `integration_service` is the
orchestration that treats all three identically regardless.

Deliberately empty of imports: the orchestration reaches the adapters, and the adapters reach
storage and Graph, so pulling the whole package in from any of them would make import order
matter.
"""
