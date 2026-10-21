"""Append-only, hash-chained audit trail.

Each row stores prev_hash (the previous row's row_hash) and row_hash = SHA-256(prev_hash || canonical row).
Altering or deleting any row in the middle breaks every hash after it, and verify_chain() finds it.
Honest limit: deleting rows from the END of the log is only detectable by comparing the head hash
against a copy kept elsewhere (see /admin/audit/verify). Postgres triggers + an insert-only DB role
make tampering through the app's own DB account impossible in the first place (schema.sql).
"""
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from .models import AuditLog, User, now

GENESIS = "0" * 64


def _ts(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _digest(prev_hash: str, e: AuditLog) -> str:
    body = {
        "ts": _ts(e.ts), "actor_id": e.actor_id, "actor_email": e.actor_email, "action": e.action,
        "outcome": e.outcome, "document_id": e.document_id, "target_user_id": e.target_user_id,
        "ip": e.ip, "detail": e.detail,
    }
    payload = prev_hash + json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def record(
    db: DBSession, *, action: str, outcome: str, actor: User | None = None, actor_email: str | None = None,
    document_id: str | None = None, target_user_id: str | None = None, ip: str | None = None,
    detail: dict | None = None, commit: bool = True,
) -> AuditLog:
    """Write one audit row. Use commit=False to make it atomic with the action being audited
    (the caller then commits once). Denied/failed attempts must use commit=True: they are
    followed by an exception, and the audit row must survive it."""
    assert outcome in ("allowed", "denied")
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(727274)"))  # serialise chain writers
    last = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
    prev = last.row_hash if last else GENESIS
    entry = AuditLog(
        ts=now(), actor_id=actor.id if actor else None,
        actor_email=(actor.email if actor else actor_email),
        action=action, outcome=outcome, document_id=document_id, target_user_id=target_user_id,
        ip=ip, detail=json.dumps(detail or {}, sort_keys=True, default=str), prev_hash=prev, row_hash="",
    )
    entry.row_hash = _digest(prev, entry)
    db.add(entry)
    db.flush()
    if commit:
        db.commit()
    return entry


def verify_chain(db: DBSession) -> dict:
    prev = GENESIS
    count = 0
    for e in db.query(AuditLog).order_by(AuditLog.id.asc()).yield_per(500):
        if e.prev_hash != prev or _digest(prev, e) != e.row_hash:
            return {"ok": False, "first_bad_id": e.id, "rows_checked": count, "head_hash": None}
        prev = e.row_hash
        count += 1
    return {"ok": True, "first_bad_id": None, "rows_checked": count, "head_hash": prev}
