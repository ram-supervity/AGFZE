from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.core.errors import AccountDisabledError, AuthenticationError, AuthorizationError
from app.core.roles import normalise_roles
from app.core.security import TokenError, decode_access_token, extract_identity, extract_roles
from app.db.base import utcnow
from app.db.session import get_session
from app.models.identity import User
from app.services.audit_service import ActorType, AuditEventType, record_audit_event

DbSession = Annotated[AsyncSession, Depends(get_session)]
bearer_scheme = HTTPBearer(auto_error=False)

BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


async def _find_user(
    session: AsyncSession,
    subject_id: str,
    entra_object_id: str | None,
    email: str,
) -> User | None:
    """The account this token belongs to, matched in descending order of authority: the subject
    the provider signed it with, then the directory object id, then the address. The last two are
    what carry an account across a re-issued subject."""
    result = await session.execute(select(User).where(User.subject_id == subject_id))
    user = result.scalar_one_or_none()
    if user is not None:
        return user

    if entra_object_id:
        result = await session.execute(select(User).where(User.entra_object_id == entra_object_id))
        user = result.scalar_one_or_none()
        if user is not None:
            return user

    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def _provision_user(
    session: AsyncSession,
    subject_id: str,
    entra_object_id: str | None,
    email: str,
    display_name: str,
    roles: list[str],
) -> User:
    user = User(
        subject_id=subject_id,
        entra_object_id=entra_object_id,
        email=email,
        display_name=display_name,
        roles=roles,
        last_login_at=utcnow(),
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError:
        # Two first requests from the same new account raced and the other one won. Its row is
        # the account; this request adopts it rather than failing a sign-in on a tie.
        await session.rollback()
        existing = await _find_user(session, subject_id, entra_object_id, email)
        if existing is None:
            raise
        existing.last_login_at = utcnow()
        return existing

    await record_audit_event(
        session,
        event_type=AuditEventType.USER_PROVISIONED,
        entity_type="user",
        entity_id=user.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        metadata={"subject_id": subject_id, "roles": roles},
    )
    return user


async def get_current_user(
    request: Request,
    session: DbSession,
    credentials: BearerCredentials,
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise AuthenticationError("Provide a bearer access token.")

    try:
        claims = await decode_access_token(credentials.credentials)
        subject_id, email, display_name, entra_object_id = extract_identity(claims)
    except TokenError as exc:
        raise AuthenticationError("The access token could not be verified.") from exc

    roles = extract_roles(claims)
    user = await _find_user(session, subject_id, entra_object_id, email)

    if user is None:
        user = await _provision_user(
            session, subject_id, entra_object_id, email, display_name, roles
        )
    else:
        if not user.is_active:
            raise AccountDisabledError()
        if user.subject_id != subject_id:
            # The same person, reached through a subject the provider has re-issued - a realm
            # re-import, a tenant migration, a move from Keycloak to Entra ID. The account is the
            # one the email and object id already name, so it is re-bound rather than duplicated;
            # inserting would collide with the unique email and lock the person out entirely.
            await record_audit_event(
                session,
                event_type=AuditEventType.USER_IDENTITY_REBOUND,
                entity_type="user",
                entity_id=user.id,
                actor_id=user.id,
                actor_type=ActorType.USER,
                metadata={"previous_subject_id": user.subject_id, "subject_id": subject_id},
            )
            user.subject_id = subject_id
        # Keycloak owns identity and role mapping, so the token wins on every request.
        user.email = email
        user.display_name = display_name
        user.roles = roles
        if entra_object_id:
            user.entra_object_id = entra_object_id
        user.last_login_at = utcnow()

    await session.commit()
    request.state.user_id = str(user.id)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: str, require_all: bool = False) -> Callable[..., Awaitable[User]]:
    required = set(normalise_roles(roles))
    if not required:
        raise ValueError("require_roles needs at least one known platform role")

    async def dependency(user: CurrentUser) -> User:
        held = set(user.roles or ())
        granted = required <= held if require_all else bool(required & held)
        if not granted:
            raise AuthorizationError("Your role does not grant access to this resource.")
        return user

    return dependency
