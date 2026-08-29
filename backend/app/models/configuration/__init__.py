"""Tenant configuration models.

`DocumentTypeSchema` () drives extraction and `RuleConfiguration` () drives the
business-rule engine. Both are read at call time, so a threshold change is a row change; the
account and settings models arrive with the administration module in .
"""

from app.models.configuration.document_schema import DocumentTypeSchema
from app.models.configuration.rule_configuration import RuleConfiguration

__all__ = ["DocumentTypeSchema", "RuleConfiguration"]
