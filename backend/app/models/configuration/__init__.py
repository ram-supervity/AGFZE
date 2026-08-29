"""Tenant configuration models.

`DocumentTypeSchema` (Step 2) drives extraction and `RuleConfiguration` (Step 3) drives the
business-rule engine. Both are read at call time, so a threshold change is a row change; the
account and settings models arrive with the administration module in Step 9.
"""

from app.models.configuration.document_schema import DocumentTypeSchema
from app.models.configuration.rule_configuration import RuleConfiguration

__all__ = ["DocumentTypeSchema", "RuleConfiguration"]
