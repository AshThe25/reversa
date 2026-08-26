"""FastAPI dependencies: session extraction and scope enforcement."""

from __future__ import annotations

import logging

from fastapi import Depends, Header, HTTPException, status

from reversa.config import Settings, get_settings
from reversa.security.auth import AuthError, Scope, Session, verify

log = logging.getLogger(__name__)


def current_session(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> Session:
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
    try:
        return verify(token, settings.session_secret)
    except AuthError as exc:
        # the specific reason goes to the log, never to the caller - telling them
        # whether the signature or the expiry failed hands them an oracle
        log.info("auth rejected: %s", exc.reason)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthenticated"},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def _scoped(scope: str):
    def dependency(session: Session = Depends(current_session)) -> Session:
        if not session.has(scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "insufficient_scope", "required": scope},
            )
        return session
    return dependency


requires_read = _scoped(Scope.READ)
requires_simulate = _scoped(Scope.SIMULATE)
requires_execute = _scoped(Scope.EXECUTE)
