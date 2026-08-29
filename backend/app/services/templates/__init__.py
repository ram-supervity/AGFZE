"""The sales document templates, and the deterministic renderer that fills them in.

The binary a draft generation produces is always made here, by `python-docx`, out of a template
file that ships with the platform. The model is never asked for file bytes and never sees the
template's binary: it decides which clauses belong in this particular deal, and nothing else.
"""

from app.services.templates.renderer import (
    TemplateRenderError,
    render_template,
)
from app.services.templates.sales_templates import (
    SALES_CONTRACT_TEMPLATE,
    SALES_INVOICE_TEMPLATE,
    TEMPLATES_BY_TYPE,
    DocumentTemplate,
    TemplateClause,
    TemplateField,
    ensure_template_files,
    template_path,
    territory_reference,
)

__all__ = [
    "SALES_CONTRACT_TEMPLATE",
    "SALES_INVOICE_TEMPLATE",
    "TEMPLATES_BY_TYPE",
    "DocumentTemplate",
    "TemplateClause",
    "TemplateField",
    "TemplateRenderError",
    "ensure_template_files",
    "render_template",
    "template_path",
    "territory_reference",
]
