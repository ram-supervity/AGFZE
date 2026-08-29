"""The one piece of governance copy that has to read identically everywhere it appears.

The platform states, on every surface carrying AI-derived content, that the extraction may be
wrong and must be checked against the source before anybody approves anything. That sentence is
worth exactly as much as its consistency: a disclaimer that says one thing on a screen, a slightly
different thing in an email and a third thing under a reply to a supplier is three disclaimers, and
a reader who noticed would be right to trust none of them.

So it lives here, in `core`, imported by every channel that prints it rather than restated by each
one. `core` specifically, and not inside the delivery package, because the reply composer needs it
too - and a composer importing the SMTP module for a string would look, to anybody reading the
import graph, exactly like a second route to a mail relay. It is not one, and the structure should
not suggest otherwise.

The canonical copy is `frontend/src/components/shared/ai-disclaimer.tsx`. If that text is ever
revised, this constant is revised with it.
"""

from __future__ import annotations

AI_DISCLAIMER_TEXT = (
    "AI-extracted information may contain errors and must be verified against the source document "
    "before approval. This platform does not replace the designated approver's review. For "
    "transactions above configured value or risk thresholds, or where source documents conflict, "
    "escalate to the approver before proceeding."
)
