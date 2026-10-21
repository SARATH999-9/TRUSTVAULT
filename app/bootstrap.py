"""Creates the first administrator from ADMIN_EMAIL / ADMIN_PASSWORD (idempotent). There is no public
way to become an administrator: not by registering, and not by Google unless the email is allow-listed."""
import logging

from sqlalchemy.orm import Session as DBSession

from . import audit
from .config import settings
from .models import User
from .security import hash_password

log = logging.getLogger("trustvault.bootstrap")
# Values shipped in .env.example. Using them unchanged would create an administrator whose password is public.
PLACEHOLDERS = {"you@example.com", "choose-a-strong-password-here", "change-me", "password", "admin"}


def admin_emails() -> set[str]:
    out = {e.strip().lower() for e in settings.admin_emails.split(",") if e.strip()}
    if settings.admin_email.strip():
        out.add(settings.admin_email.strip().lower())
    return out


def ensure_admin(db: DBSession) -> User | None:
    email, pw = settings.admin_email.strip().lower(), settings.admin_password
    if not email and not pw:
        return None
    if email in PLACEHOLDERS or pw.lower() in PLACEHOLDERS:
        raise RuntimeError("ADMIN_EMAIL / ADMIN_PASSWORD still hold the placeholder values from .env.example. "
                           "Edit .env and set your own email and a strong password before starting.")
    if not email or len(pw) < 10:
        raise RuntimeError("ADMIN_EMAIL and an ADMIN_PASSWORD of at least 10 characters must be set together")
    if db.query(User).filter(User.email == email).first():
        return None
    u = User(email=email, name=settings.admin_name, role="admin", status="active", email_verified=True,
             auth_provider="password", password_hash=hash_password(pw))
    db.add(u)
    db.flush()
    audit.record(db, action="bootstrap_admin", outcome="allowed", actor=u, commit=False, detail={"source": "environment"})
    db.commit()
    log.info("created first administrator %s", email)
    return u


def warn_if_no_admin(db: DBSession) -> None:
    if not db.query(User).filter(User.role == "admin", User.status == "active").count():
        log.warning("No active administrator exists. Set ADMIN_EMAIL and ADMIN_PASSWORD in .env, then restart.")
