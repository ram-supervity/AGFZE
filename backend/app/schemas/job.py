from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class JobStatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_type: str
    status: str
    progress: int
    result_ref: str | None
    error_message: str | None
    transaction_id: UUID | None
    created_at: datetime
    updated_at: datetime
