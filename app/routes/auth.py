import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session as DBSession

from .. import audit, google_auth, notify, ratelimit
from ..bootstrap import admin_emails
from ..config import settings
from ..db import get_db
from ..deps import COOKIE, client_ip, current_user, session_user
from ..models import Session, User, now
from ..schemas import GoogleIn, LoginIn, PasswordChangeIn, RegisterIn, UserOut
from ..security import DUMMY_HASH, aware, hash_password, hash_token, new_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
GENERIC = "Invalid email or password"


@router.get("/config")
def public_config():
    """What the sign-in page needs. The Google client id is public by design (it is not a secret)."""
    return {"google_client_id": settings.google_client_id or None, "require_document_approval": settings.require_document_approval,
            "self_registration_roles": ["owner", "viewer"]}


def _start_session(db: DBSession, user: User, request: Request, response: Response, action: str, detail: dict) -> dict:
    token = new_token()
    ip = client_ip(request)
    db.add(Session(token_hash=hash_token(token), user_id=user.id,
                   expires_at=now() + timedelta(minutes=settings.session_ttl_minutes),
                   ip=ip, user_agent=(request.headers.get("user-agent") or "")[:255]))
    user.failed_logins, user.locked_until, user.last_login_at = 0, None, now()
    audit.record(db, action=action, outcome="allowed", actor=user, ip=ip, detail=detail, commit=False)
    db.commit()
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=settings.cookie_secure,
                        max_age=settings.session_ttl_minutes * 60, path="/")
    return {"token": token, "user": UserOut.model_validate(user)}


def _refuse_by_status(db: DBSession, user: User, request: Request, how: str) -> None:
    """Rejected and suspended accounts never get a session. (Pending ones do, but can only see their status.)"""
    if user.status in ("rejected", "suspended"):
        audit.record(db, action=how, outcome="denied", actor=user, ip=client_ip(request), detail={"reason": user.status})
        why = f" Reason: {user.decision_reason}" if user.decision_reason else ""
        msg = "Your registration was declined by an administrator." if user.status == "rejected" else "Your account has been suspended."
        raise HTTPException(403, msg + why)


def _refuse_wrong_portal(db: DBSession, user: User, portal: str | None, request: Request, how: str) -> None:
    if portal and portal != user.role:
        audit.record(db, action=how, outcome="denied", actor=user, ip=client_ip(request),
                     detail={"reason": "wrong_portal", "portal": portal})
        raise HTTPException(403, f"This is a {user.role} account. Please use the {user.role.title()} portal.")


@router.post("/register", status_code=201)
def register(body: RegisterIn, request: Request, response: Response, db: DBSession = Depends(get_db)):
    ip = client_ip(request)
    ratelimit.enforce("register", ip, settings.register_per_hour, 3600)
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(409, "An account with this email already exists. Try signing in.")
    user = User(email=body.email, name=body.name, role=body.role, status="pending", email_verified=False,
                auth_provider="password", password_hash=hash_password(body.password), registered_ip=ip)
    db.add(user)
    db.flush()
    audit.record(db, action="register", outcome="allowed", actor=user, target_user_id=user.id, ip=ip,
                 detail={"role": body.role, "method": "password"}, commit=False)
    out = _start_session(db, user, request, response, "login", {"after": "register"})
    _notify_admins(db, user)
    return out


def _notify_admins(db: DBSession, user: User) -> None:
    for a in db.query(User).filter(User.role == "admin", User.status == "active"):
        notify.send(a.email, f"New {user.role} account waiting for approval",
                    f"{user.name} <{user.email}> asked for a {user.role} account. Review it under Approvals.")


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: DBSession = Depends(get_db)):
    ip = client_ip(request)
    ratelimit.enforce("login", ip, settings.login_per_5min, 300)
    user = db.query(User).filter(User.email == body.email).first()

    if user and user.locked_until and aware(user.locked_until) > now():
        verify_password(DUMMY_HASH, body.password)
        audit.record(db, action="login", outcome="denied", actor=user, ip=ip, detail={"reason": "locked"})
        raise HTTPException(401, GENERIC)

    ok = verify_password(user.password_hash if user else DUMMY_HASH, body.password)
    if not (user and ok):
        reason = "unknown_user" if not user else "bad_password"
        if user:
            user.failed_logins += 1
            if user.failed_logins >= settings.max_failed_logins:
                user.locked_until = now() + timedelta(minutes=settings.lockout_minutes)
                user.failed_logins = 0
                reason += "+lockout_started"
            db.commit()
        audit.record(db, action="login", outcome="denied", actor=user, actor_email=body.email[:254], ip=ip, detail={"reason": reason})
        raise HTTPException(401, GENERIC)

    # The password was right, so it is now safe to say why access is refused.
    _refuse_by_status(db, user, request, "login")
    _refuse_wrong_portal(db, user, body.portal, request, "login")
    return _start_session(db, user, request, response, "login", {"method": "password"})


@router.post("/google")
def google_login(body: GoogleIn, request: Request, response: Response, db: DBSession = Depends(get_db)):
    """Continue with Google. The ID token is verified on the server. New Owner/Viewer accounts start as
    'pending' like any other sign-up; administrators only via the ADMIN_EMAIL / ADMIN_EMAILS allow-list."""
    ip = client_ip(request)
    ratelimit.enforce("login", ip, settings.login_per_5min, 300)
    try:
        info = google_auth.verify_google_token(body.credential)
    except google_auth.GoogleAuthError as e:
        audit.record(db, action="google_login", outcome="denied", ip=ip, detail={"reason": str(e)[:120]})
        raise HTTPException(401, str(e))

    email, sub = info["email"], info["sub"]
    user = db.query(User).filter(User.google_sub == sub).first()
    if user is None:
        user = db.query(User).filter(User.email == email).first()
        if user is not None:
            # Same email already registered with a password. Google has verified the email, the password
            # sign-up never was, so Google takes over the account: link it, kill the old password and sessions.
            user.google_sub, user.auth_provider, user.email_verified = sub, "google", True
            user.password_hash = hash_password(secrets.token_urlsafe(32))
            for s in db.query(Session).filter(Session.user_id == user.id, Session.revoked_at.is_(None)):
                s.revoked_at = now()
            audit.record(db, action="google_link", outcome="allowed", actor=user, ip=ip, commit=False,
                         detail={"note": "existing password account taken over by verified Google identity"})
        else:
            if body.portal == "admin":
                if email not in admin_emails():
                    audit.record(db, action="google_login", outcome="denied", actor_email=email, ip=ip,
                                 detail={"reason": "not_an_authorised_administrator"})
                    raise HTTPException(403, "This Google account is not authorised for the Administrator portal.")
                user = User(email=email, name=info["name"], role="admin", status="active")
            else:
                user = User(email=email, name=info["name"], role=body.portal, status="pending", registered_ip=ip)
            user.email_verified, user.auth_provider, user.google_sub = True, "google", sub
            user.password_hash = hash_password(secrets.token_urlsafe(32))     # unusable: Google is the credential
            db.add(user)
            db.flush()
            audit.record(db, action="register", outcome="allowed", actor=user, target_user_id=user.id, ip=ip, commit=False,
                         detail={"role": user.role, "method": "google"})
            if user.status == "pending":
                _notify_admins(db, user)
    elif user.email != email:
        user.email = email                                  # Google is the source of truth for its own account

    _refuse_by_status(db, user, request, "google_login")
    _refuse_wrong_portal(db, user, body.portal, request, "google_login")
    return _start_session(db, user, request, response, "login", {"method": "google"})


@router.post("/logout")
def logout(request: Request, response: Response, user: User = Depends(session_user), db: DBSession = Depends(get_db)):
    request.state.session.revoked_at = now()
    audit.record(db, action="logout", outcome="allowed", actor=user, ip=client_ip(request), commit=False)
    db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(session_user)):
    """Works for pending accounts too: this is how the 'waiting for approval' screen learns it was approved."""
    return user


@router.post("/change-password")
def change_password(body: PasswordChangeIn, request: Request, user: User = Depends(current_user),
                    db: DBSession = Depends(get_db)):
    if user.auth_provider == "google":
        raise HTTPException(400, "This account signs in with Google and has no password to change.")
    if not verify_password(user.password_hash, body.current_password):
        audit.record(db, action="password_change", outcome="denied", actor=user, ip=client_ip(request))
        raise HTTPException(400, "Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    for s in db.query(Session).filter(Session.user_id == user.id, Session.id != request.state.session.id,
                                      Session.revoked_at.is_(None)):
        s.revoked_at = now()
    audit.record(db, action="password_change", outcome="allowed", actor=user, ip=client_ip(request), commit=False)
    db.commit()
    return {"ok": True}
