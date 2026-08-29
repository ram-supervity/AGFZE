"""Answering a broker or a supplier on the thread their message arrived on.

Discovery asks for two things here that pull in opposite directions, and both are kept.

It asks the platform to *reply* - on the same thread, with the standing disclaimer, so a
counterparty's next message lands back on the same request rather than starting a second one. And
it asks that a reply go out "initially via human-approved draft", alongside the rule that runs
through the whole platform: nothing irreversible leaves without a person's name on it.

So the composition and the sending are two separate acts, in two separate requests, and nothing
here bridges them:

* `compose` writes a draft into `email_reply_drafts`. It calls nothing outward, changes nothing in
  the mailbox, and produces a body a person can read and rewrite before anybody sees it.
* `send` is reached only from an endpoint a signed-in person called. It creates the Graph draft on
  the original conversation, sends it, and records who did so.

There is no scheduler, no worker, no retry and no event subscription with a route to `send`. That
is not an oversight to be tidied up later: an email leaving AGFZE's mailbox is a statement to a
counterparty, and a statement needs somebody who made it.

Two further constraints worth stating plainly.

**The disclaimer is not separable.** `compose_body` appends it, and there is no path that produces
a body without it. It is the same wording the screens and the notification emails already carry,
imported from `core.disclaimer` rather than retyped, so the three cannot drift apart - and imported
from *there* rather than from the mail module, so this composer has no import edge to anything that
can reach an SMTP relay.

**Nothing about the body is inferred.** No model is called here. A reply is assembled from the
request's own fields and the desk's own words; a sentence this platform could not substantiate is
a sentence it does not write.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.disclaimer import AI_DISCLAIMER_TEXT
from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models.identity import User
from app.models.intake import EmailMessage, EmailReplyDraft, Request
from app.services import graph_service
from app.services.audit_service import ActorType, record_audit_event

logger = get_logger(__name__)


class ReplyStatus:
    DRAFT = "draft"
    SENT = "sent"
    FAILED = "failed"
    WITHDRAWN = "withdrawn"


class AuditEvent:
    REPLY_COMPOSED = "request.reply.composed"
    REPLY_SENT = "request.reply.sent"
    REPLY_SEND_FAILED = "request.reply.send_failed"
    REPLY_WITHDRAWN = "request.reply.withdrawn"


# Printed under every reply, above the disclaimer. Says two things a recipient needs: that the
# message came out of a system, and that answering it reaches the desk rather than a machine -
# which is why it is a "do not reply to this address" line and not a "do not reply" line. The
# thread has to stay usable; discovery's whole reason for replying in-thread is that the next
# message comes back to the same request.
SYSTEM_FOOTER = (
    "This message was sent from the AGFZE Command Centre on behalf of the AGFZE trade desk. "
    "Replying on this thread reaches the desk and is captured against the same reference."
)


def compose_body(*, reference: str, message: str) -> str:
    """The desk's words, the reference they are about, and the two standing notices.

    Assembled in one place so every reply this platform has ever sent has the same shape, and so
    the disclaimer cannot be dropped by a caller that forgot it - there is no argument to drop it
    with.
    """
    body = message.strip()
    if not body:
        raise BadRequestError("A reply needs something to say.")
    return "\n\n".join([body, f"Our reference: {reference}", SYSTEM_FOOTER, AI_DISCLAIMER_TEXT])


async def _request_with_message(
    session: AsyncSession, request_id: UUID
) -> tuple[Request, EmailMessage]:
    request = await session.scalar(select(Request).where(Request.id == request_id))
    if request is None:
        raise NotFoundError("Request not found.")
    if request.email_message_id is None:
        raise BadRequestError(
            "This request was created from a portal upload, so there is no thread to reply on.",
            code="no_thread",
        )
    message = await session.get(EmailMessage, request.email_message_id)
    if message is None:  # pragma: no cover - the FK makes this unreachable
        raise BadRequestError("The original message for this request is no longer stored.")
    return request, message


async def list_for_request(session: AsyncSession, request_id: UUID) -> list[EmailReplyDraft]:
    return list(
        (
            await session.scalars(
                select(EmailReplyDraft)
                .where(EmailReplyDraft.request_id == request_id)
                .order_by(EmailReplyDraft.composed_at.desc())
            )
        ).all()
    )


async def compose(
    session: AsyncSession, request_id: UUID, *, message: str, composed_by: User
) -> EmailReplyDraft:
    """Write the draft. Reaches no mailbox and sends nothing."""
    request, email = await _request_with_message(session, request_id)

    draft = EmailReplyDraft(
        request_id=request.id,
        email_message_id=email.id,
        status=ReplyStatus.DRAFT,
        # Graph writes the real subject when it threads the reply. This is what the desk sees on
        # the platform's own screen, and it is recorded so a sent reply reads the same here as it
        # does in the mailbox.
        subject=f"RE: {email.subject}" if email.subject else None,
        body_text=compose_body(reference=request.request_code, message=message),
        composed_by_id=composed_by.id,
        composed_at=utcnow(),
    )
    session.add(draft)
    await session.flush()

    await record_audit_event(
        session,
        event_type=AuditEvent.REPLY_COMPOSED,
        entity_type="email_reply_draft",
        entity_id=draft.id,
        actor_id=composed_by.id,
        actor_type=ActorType.USER,
        # Character count rather than the body: the trail records that a reply was drafted and how
        # long it was, and the body itself lives on its own access-controlled row one hop away.
        metadata={
            "request_code": request.request_code,
            "recipient": email.sender_address,
            "body_characters": len(draft.body_text),
            "sent": False,
            "outbound_enabled": settings.reply_configured,
        },
    )
    return draft


async def get_draft(session: AsyncSession, draft_id: UUID) -> EmailReplyDraft:
    draft = await session.get(EmailReplyDraft, draft_id)
    if draft is None:
        raise NotFoundError("That reply does not exist.")
    return draft


async def send(session: AsyncSession, draft_id: UUID, *, sent_by: User) -> EmailReplyDraft:
    """Put the composed reply on the original thread. Called only from a person's own request.

    A failure is recorded on the row and re-raised. It is never swallowed into a success, and the
    row is never left saying "sent" for a message the provider did not accept.
    """
    draft = await get_draft(session, draft_id)
    if draft.status == ReplyStatus.SENT:
        raise ConflictError("That reply has already been sent.")
    if draft.status == ReplyStatus.WITHDRAWN:
        raise ConflictError("That reply was withdrawn. Compose a new one to answer this thread.")

    email = await session.get(EmailMessage, draft.email_message_id)
    if email is None:  # pragma: no cover - the FK makes this unreachable
        raise BadRequestError("The original message for this reply is no longer stored.")

    client = graph_service.get_graph_client()
    try:
        provider_draft_id = draft.provider_draft_id or await client.create_reply_draft(
            email.provider_message_id, draft.body_text
        )
        draft.provider_draft_id = provider_draft_id
        await client.send_draft(provider_draft_id)
    except graph_service.GraphError as exc:
        # The refusal is itself worth keeping, and it is written on a session rolled back to the
        # state it was in before the attempt - so the only rows this path commits are the failed
        # status and the record of why. The same ordering the role override already uses, and for
        # the same reason: raising through an un-committed session would leave the desk with a
        # draft that says nothing about the attempt that just failed.
        provider_draft_id = draft.provider_draft_id
        draft_id_value = draft.id
        recipient = email.sender_address
        await session.rollback()

        failed = await session.get(EmailReplyDraft, draft_id_value)
        if failed is not None:
            failed.status = ReplyStatus.FAILED
            failed.failure_reason = exc.reason
            # Kept where one was made, so a retry re-sends the draft the counterparty would have
            # received rather than creating a second one on the same thread.
            failed.provider_draft_id = provider_draft_id
            failed.updated_at = utcnow()
            await session.flush()
        await record_audit_event(
            session,
            event_type=AuditEvent.REPLY_SEND_FAILED,
            entity_type="email_reply_draft",
            entity_id=draft_id_value,
            actor_id=sent_by.id,
            actor_type=ActorType.USER,
            metadata={"recipient": recipient, "reason": exc.reason, "sent": False},
        )
        await session.commit()
        raise

    draft.status = ReplyStatus.SENT
    draft.failure_reason = None
    draft.sent_by_id = sent_by.id
    draft.sent_at = utcnow()
    draft.updated_at = draft.sent_at
    await session.flush()

    await record_audit_event(
        session,
        event_type=AuditEvent.REPLY_SENT,
        entity_type="email_reply_draft",
        entity_id=draft.id,
        actor_id=sent_by.id,
        actor_type=ActorType.USER,
        metadata={
            "recipient": email.sender_address,
            "provider_draft_id": draft.provider_draft_id,
            "body_characters": len(draft.body_text),
            "sent": True,
        },
    )
    logger.info(
        "request_reply_sent",
        extra={"draft_id": str(draft.id), "request_id": str(draft.request_id)},
    )
    return draft


async def withdraw(session: AsyncSession, draft_id: UUID, *, withdrawn_by: User) -> EmailReplyDraft:
    """Abandon a composed reply, and discard the provider draft if one was ever made."""
    draft = await get_draft(session, draft_id)
    if draft.status == ReplyStatus.SENT:
        raise ConflictError("That reply has already been sent and cannot be withdrawn.")

    if draft.provider_draft_id and settings.reply_configured:
        try:
            await graph_service.get_graph_client().delete_draft(draft.provider_draft_id)
        except graph_service.GraphError as exc:
            # The platform's own record is what governs, and a stranded draft in the mailbox is a
            # tidiness problem rather than a correctness one. It is logged and not raised, because
            # refusing to withdraw locally would leave the desk unable to move on.
            logger.warning(
                "request_reply_provider_draft_not_deleted",
                extra={"draft_id": str(draft.id), "reason": exc.reason},
            )

    draft.status = ReplyStatus.WITHDRAWN
    draft.updated_at = utcnow()
    await session.flush()

    await record_audit_event(
        session,
        event_type=AuditEvent.REPLY_WITHDRAWN,
        entity_type="email_reply_draft",
        entity_id=draft.id,
        actor_id=withdrawn_by.id,
        actor_type=ActorType.USER,
        metadata={"sent": False},
    )
    return draft
