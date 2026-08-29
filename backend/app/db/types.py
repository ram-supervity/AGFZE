from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# PostgreSQL keeps its native types; the generic JSON fallback lets the suite run on a
# disposable SQLite database when no container stack is available.
GUID = sa.Uuid(as_uuid=True)
JSONBType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
StringArrayType = sa.JSON().with_variant(postgresql.ARRAY(sa.String(64)), "postgresql")
