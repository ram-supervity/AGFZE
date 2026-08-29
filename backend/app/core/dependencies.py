from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
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
    result = await session.execute(select(User).where(User.subject_id == subject_id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            subject_id=subject_id,
            entra_object_id=entra_object_id,
            email=email,
            display_name=display_name,
            roles=roles,
            last_login_at=utcnow(),
        )
        session.add(user)
        await session.flush()
        await record_audit_event(
            session,
            event_type=AuditEventType.USER_PROVISIONED,
            entity_type="user",
            entity_id=user.id,
            actor_id=user.id,
            actor_type=ActorType.USER,
            metadata={"subject_id": subject_id, "roles": roles},
        )
    elif not user.is_active:
        raise AccountDisabledError()
    else:
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
