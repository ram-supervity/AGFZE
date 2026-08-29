"""Align seven constraint names with what the models declare

Revision ID: 20260415_000021
Revises: 20260401_000020
Create Date: 2026-04-15 00:00:21.000000+00:00

Renames only. Not one predicate, column, type or index changes, and nothing about how any rule,
query or validation behaves is different afterwards - a check constraint's name is not its
condition.

This exists because `alembic check` could not pass. Three earlier migrations wrote constraint names
that differ from the ones their models declare:

* `containers` carries `uq_containers_transaction_id` for a constraint the model calls
  `uq_containers_transaction_number` - the old name also misdescribes it, since the constraint is
  over `(transaction_id, container_number)` rather than over the transaction alone;
* `reports` carries four `ck_reports_ck_reports_*` names, doubled because migration 8 passed
  `op.f()` a name that already began with `ck_`;
* `rule_exception_mappings` carries two names Alembic truncated and hashed
  (`..._owner_ad16`, `..._prior_1f1e`), because the names the model spelled out came to 66 and 64
  characters with the convention's prefix in front of them - past PostgreSQL's 63-character
  identifier limit. Those two model names are shortened alongside this migration, so what is
  declared can actually be stored; the constraints themselves are untouched.

Autogenerate therefore proposed dropping and recreating all seven on every run, which made
`alembic check` a permanently red gate: a step that can never pass gates nothing, and a pipeline
nobody can get green is a pipeline people learn to ignore.

PostgreSQL only. A SQLite database is built from these same migrations every time, from base, so it
carries the same names as the schema it was built with; nothing reads a constraint by name, and
SQLite cannot rename one without rebuilding the table, which is a far larger operation than this
warrants for a purely cosmetic difference on a disposable test database.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260415_000021"
down_revision: str | None = "20260401_000020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, name as applied, name the model declares)
RENAMES: tuple[tuple[str, str, str], ...] = (
    (
        "containers",
        "uq_containers_transaction_id",
        "uq_containers_transaction_number",
    ),
    (
        "reports",
        "ck_reports_ck_reports_report_type_valid",
        "ck_reports_report_type_valid",
    ),
    (
        "reports",
        "ck_reports_ck_reports_report_format_valid",
        "ck_reports_report_format_valid",
    ),
    (
        "reports",
        "ck_reports_ck_reports_report_stream_valid",
        "ck_reports_report_stream_valid",
    ),
    (
        "reports",
        "ck_reports_ck_reports_report_period_ordered",
        "ck_reports_report_period_ordered",
    ),
    (
        "rule_exception_mappings",
        "ck_rule_exception_mappings_rule_exception_mapping_owner_ad16",
        "ck_rule_exception_mappings_rule_exception_mapping_owner_valid",
    ),
    (
        "rule_exception_mappings",
        "ck_rule_exception_mappings_rule_exception_mapping_prior_1f1e",
        "ck_rule_exception_mappings_rule_exception_priority_valid",
    ),
)


def _rename(pairs: tuple[tuple[str, str, str], ...]) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, source, target in pairs:
        # Conditional on the source actually being there, so this is safe on a database built
        # after the fix as well as on one built before it.
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = '{source}'
                      AND conrelid = '{table}'::regclass
                ) THEN
                    ALTER TABLE {table} RENAME CONSTRAINT "{source}" TO "{target}";
                END IF;
            END $$;
            """
        )


def upgrade() -> None:
    _rename(RENAMES)


def downgrade() -> None:
    _rename(tuple((table, target, source) for table, source, target in RENAMES))
