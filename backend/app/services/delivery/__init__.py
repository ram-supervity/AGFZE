"""The two delivery channels  adds behind `notification_service.notify`.

Nothing in this package decides *who* is told about something - that has one answer and it lives
in `notify`. These modules only carry a sentence somebody has already been judged to need onto a
wire, and report honestly whether it arrived.

Neither of them may ever raise into a caller. The transaction, exception or approval a
notification is about has already happened and has already been recorded; a relay that refuses a
connection is a courtesy that failed, not a business event that should be undone.
"""

from app.services.delivery import email_service, push_service

__all__ = ["email_service", "push_service"]
