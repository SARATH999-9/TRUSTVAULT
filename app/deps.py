from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session as DBSession

from . import audit
from .db import get_db
from .models import Session, User, now
from .security import aware, hash_token

COOKIE = "tv_session"


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _token(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    if h.lower().startswith("bearer "):
        return h[7:].strip()
    return request.cookies.get(COOKIE)


def session_user(request: Request, db: DBSession = Depends(get_db)) -> User:
    """Signed in, account either 'active' or 'pending'. ONLY /auth/me and /auth/logout use this, so a
    pending account can see its own status and sign out, and nothing else. Re-read from the DB every time."""
    token = _token(request)
    if not token:
        raise HTTPException(401, "Not authenticated")
    s = db.query(Session).filter(Session.token_hash == hash_token(token)).first()
    if not s or s.revoked_at is not None or aware(s.expires_at) <= now():
        raise HTTPException(401, "Not authenticated")
    user = db.get(User, s.user_id)
    if not user or user.status not in ("active", "pending"):
        raise HTTPException(401, "Not authenticated")
    request.state.session = s
    return user


def current_user(user: User = Depends(session_user)) -> User:
    """The default for every other route: only an APPROVED (active) account gets through."""
    if user.status != "active":
        raise HTTPException(403, "Your account is waiting for admin approval")
    return user


def require_roles(*roles: str):
    def dep(request: Request, user: User = Depends(current_user), db: DBSession = Depends(get_db)) -> User:
        if user.role not in roles:
            audit.record(db, action="role_denied", outcome="denied", actor=user, ip=client_ip(request),
                         detail={"path": request.url.path, "method": request.method, "needs": list(roles)})
            raise HTTPException(403, "Forbidden")
        return user
    return dep
