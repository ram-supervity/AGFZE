"""Downstream integration models - added in Step 7.

`IntegrationJob` is the record of what genuinely happened to one posting, and `DocumentPack` is
the merged file the DMS job carries. Neither table alters anything built earlier: the jobs attach
to `trade_transactions` through their own foreign key, exactly as every module since Step 5 has.
"""

from app.models.integration.jobs import IntegrationJob
from app.models.integration.packs import DocumentPack

__all__ = ["DocumentPack", "IntegrationJob"]
