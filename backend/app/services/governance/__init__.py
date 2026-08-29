"""Exceptions and approvals - the governance module added in Step 4.

Built once, for every desk. The Sales and FA workflows in Steps 5 and 6 route their failures
through the same mapping table and put their transactions into the same approval queue; neither
adds a table, an endpoint or a branch here.

Deliberately empty of imports: `hooks` is reached from inside the rule engine, and pulling the
whole package in from there would make the import order matter.
"""
