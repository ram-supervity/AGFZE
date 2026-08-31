"""Mark a job the platform raised for itself, so a desk can watch mailbox intake run

Revision ID: 20260515_000023
Revises: 20260501_000022
Create Date: 2026-05-15 00:00:23.000000+00:00

One column, one backfill.

`background_jobs.created_by_id` has always been nullable for two unrelated reasons: the platform
raises a job nobody asked for (mailbox intake does, once per captured message), and the column is
`ondelete="SET NULL"`, so a job outlives the account that started it. Reading "system job" off
that NULL therefore says two different things, and the second one is wrong in a way that widens
access: a removed user's private job would become everybody's.

The column records the fact at creation instead. The backfill marks the jobs that genuinely are
the platform's - the intake job type, with no creator - and leaves every other unowned row alone.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260515_000023"
down_revision: str | None = "20260501_000022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INTAKE_JOB_TYPE = "intake.request.process"


def upgrade() -> None:
    op.add_column(
        "background_jobs",
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    jobs = sa.table(
        "background_jobs",
        sa.column("job_type", sa.String),
        sa.column("created_by_id", sa.Uuid(as_uuid=True)),
        sa.column("is_system", sa.Boolean),
    )
    op.execute(
        jobs.update()
        .where(jobs.c.created_by_id.is_(None))
        .where(jobs.c.job_type == INTAKE_JOB_TYPE)
        .values(is_system=sa.true())
    )
    # The default was only ever needed to make the column NOT NULL over existing rows. Leaving it
    # in place would let an INSERT that forgets the flag succeed silently, so it goes.
    with op.batch_alter_table("background_jobs") as batch:
        batch.alter_column("is_system", server_default=None)


def downgrade() -> None:
    op.drop_column("background_jobs", "is_system")
