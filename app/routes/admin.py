import json
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from .. import alerts as alert_rules, audit, notify, policy
from ..authz import _valid_uuid
from ..config import settings
from ..db import get_db
from ..deps import client_ip, require_roles
from ..models import AuditLog, Document, DocumentVersion, Grant, Session, User, now
from ..schemas import AdminUserOut, UserCreateIn, UserUpdateIn
from ..security import aware, hash_password
from ..validation import ALLOWED

router = APIRouter(prefix="/admin", tags=["admin"])
admin_only = require_roles("admin")
CATEGORY_OK = r"^[\w .&-]{1,60}$"


# ------------------------------------------------------------------ users & approvals
@router.post("/users", response_model=AdminUserOut, status_code=201)
def create_user(body: UserCreateIn, request: Request, admin: User = Depends(admin_only),
                db: DBSession = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(409, "Email already registered")
    u = User(email=body.email, name=body.name, role=body.role, password_hash=hash_password(body.password),
             status="active", email_verified=False, auth_provider="password", decided_by=admin.id, decided_at=now())
    db.add(u)
    db.flush()
    audit.record(db, action="user_create", outcome="allowed", actor=admin, target_user_id=u.id,
                 ip=client_ip(request), detail={"role": u.role}, commit=False)
    db.commit()
    return u


@router.get("/users", response_model=list[AdminUserOut])
def list_users(status: str | None = Query(None, pattern="^(pending|active|rejected|suspended)$"),
               role: str | None = Query(None, pattern="^(admin|owner|viewer)$"),
               q: str | None = Query(None, max_length=100), limit: int = Query(200, ge=1, le=500),
               admin: User = Depends(admin_only), db: DBSession = Depends(get_db)):
    query = db.query(User)
    if status:
        query = query.filter(User.status == status)
    if role:
        query = query.filter(User.role == role)
    if q:
        needle = q.lower()
        query = query.filter(func.lower(User.email).contains(needle, autoescape=True)
                             | func.lower(User.name).contains(needle, autoescape=True))
    return query.order_by(User.created_at.desc()).limit(limit).all()


ALLOWED_MOVES = {"pending": {"active", "rejected"}, "active": {"suspended", "rejected"},
                 "suspended": {"active", "rejected"}, "rejected": {"active"}}


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def update_user(user_id: str, body: UserUpdateIn, request: Request, admin: User = Depends(admin_only),
                db: DBSession = Depends(get_db)):
    """Approve / reject / suspend / reactivate an account and/or change its role. Every change is audited,
    suspension and rejection end all of the person's sessions immediately, and the person is emailed if SMTP is set."""
    u = db.get(User, user_id) if _valid_uuid(user_id) else None
    if not u:
        raise HTTPException(404, "Not found")
    new_status = body.status
    if new_status is None and body.is_active is not None:
        new_status = "active" if body.is_active else "suspended"
    if u.id == admin.id and (new_status in ("rejected", "suspended") or (body.role and body.role != "admin")):
        raise HTTPException(400, "Admins cannot demote or deactivate themselves")
    if new_status and new_status != u.status and new_status not in ALLOWED_MOVES[u.status]:
        raise HTTPException(409, f"An account that is {u.status} cannot become {new_status}")
    changes = {}
    if body.role and body.role != u.role:
        changes["role"] = [u.role, body.role]
        u.role = body.role
    old_status = u.status
    if new_status and new_status != u.status:
        changes["status"] = [u.status, new_status]
        u.status, u.decided_by, u.decided_at = new_status, admin.id, now()
        u.decision_reason = (body.reason or "").strip() or None
        if new_status in ("rejected", "suspended"):
            for s in db.query(Session).filter(Session.user_id == u.id, Session.revoked_at.is_(None)):
                s.revoked_at = now()
        if u.decision_reason:
            changes["reason"] = u.decision_reason
    audit.record(db, action="user_update", outcome="allowed", actor=admin, target_user_id=u.id,
                 ip=client_ip(request), detail=changes, commit=False)
    db.commit()
    if "status" in changes:
        if old_status == "pending" and u.status == "active":
            notify.send(u.email, "Your TrustVault account was approved", f"Hello {u.name}, you can now sign in as {u.role}.")
        elif u.status == "rejected":
            notify.send(u.email, "Your TrustVault registration was declined", f"Hello {u.name}. Reason: {u.decision_reason or 'not given'}.")
        elif u.status == "suspended":
            notify.send(u.email, "Your TrustVault account was suspended", f"Reason: {u.decision_reason or 'not given'}.")
    return u


@router.get("/owners")
def list_owners(admin: User = Depends(admin_only), db: DBSession = Depends(get_db)):
    """Everything an administrator needs to supervise owners: status, volume and what is awaiting review."""
    out = []
    for o in db.query(User).filter(User.role == "owner").order_by(User.created_at.desc()).all():
        docs = db.query(Document).filter(Document.owner_id == o.id, Document.deleted_at.is_(None))
        by = dict(docs.with_entities(Document.review_status, func.count()).group_by(Document.review_status).all())
        last = docs.with_entities(func.max(Document.created_at)).scalar()
        out.append({"id": o.id, "name": o.name, "email": o.email, "status": o.status, "email_verified": o.email_verified,
                    "auth_provider": o.auth_provider, "documents": sum(by.values()), "pending": by.get("pending", 0),
                    "approved": by.get("approved", 0), "rejected": by.get("rejected", 0),
                    "shares": db.query(Grant).join(Document, Document.id == Grant.document_id)
                    .filter(Document.owner_id == o.id, Document.deleted_at.is_(None)).count(),
                    "last_upload": aware(last) if last else None})
    return out


# ------------------------------------------------------------------ audit
def _row(r: AuditLog) -> dict:
    return {"id": r.id, "ts": aware(r.ts), "actor_email": r.actor_email, "action": r.action,
            "outcome": r.outcome, "document_id": r.document_id, "target_user_id": r.target_user_id,
            "ip": r.ip, "detail": r.detail, "row_hash": r.row_hash}


@router.get("/audit")
def list_audit(action: str | None = Query(None, max_length=40), outcome: str | None = Query(None, pattern="^(allowed|denied)$"),
               actor: str | None = Query(None, max_length=100), document_id: str | None = Query(None, max_length=36),
               target_user_id: str | None = Query(None, max_length=36),
               since: datetime | None = None, until: datetime | None = None,
               limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
               admin: User = Depends(admin_only), db: DBSession = Depends(get_db)):
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    if outcome:
        q = q.filter(AuditLog.outcome == outcome)
    if actor:
        q = q.filter(func.lower(AuditLog.actor_email).contains(actor.lower(), autoescape=True))
    if document_id:
        q = q.filter(AuditLog.document_id == document_id)
    if target_user_id:
        q = q.filter(AuditLog.target_user_id == target_user_id)
    if since:
        q = q.filter(AuditLog.ts >= aware(since))
    if until:
        q = q.filter(AuditLog.ts <= aware(until))
    return [_row(r) for r in q.order_by(AuditLog.id.desc()).offset(offset).limit(limit).all()]


@router.get("/audit/verify")
def verify_audit(admin: User = Depends(admin_only), db: DBSession = Depends(get_db)):
    """head_hash should be copied somewhere outside this system; it is what exposes tail truncation."""
    return audit.verify_chain(db)


# ------------------------------------------------------------------ documents: oversight & review
def _doc_admin_out(db: DBSession, d: Document, o: User) -> dict:
    last = (db.query(DocumentVersion).filter_by(document_id=d.id).order_by(DocumentVersion.version_no.desc()).first())
    up = db.get(User, last.uploaded_by) if last else None
    return {"id": d.id, "name": d.name, "category": d.category, "description": d.description,
            "owner_email": o.email, "owner_name": o.name, "owner_status": o.status,
            "created_at": d.created_at, "deleted": d.deleted_at is not None,
            "review_status": d.review_status, "review_reason": d.review_reason, "reviewed_at": d.reviewed_at,
            "versions": db.query(DocumentVersion).filter_by(document_id=d.id).count(),
            "grants": db.query(Grant).filter_by(document_id=d.id).count(),
            "latest": None if not last else {"version_no": last.version_no, "filename": last.original_filename,
                                             "mime_type": last.mime_type, "size_bytes": last.size_bytes,
                                             "sha256": last.sha256, "uploaded_by": up.email if up else None,
                                             "uploaded_at": last.created_at}}


@router.get("/documents")
def list_documents_metadata(review_status: str | None = Query(None, pattern="^(pending|approved|rejected)$"),
                            q: str | None = Query(None, max_length=100), owner: str | None = Query(None, max_length=100),
                            limit: int = 100, offset: int = 0,
                            admin: User = Depends(admin_only), db: DBSession = Depends(get_db)):
    """Metadata only. Admins can see THAT a document exists, who uploaded it and its type/size/hash,
    never its contents."""
    limit = max(1, min(limit, 500))
    query = db.query(Document, User).join(User, User.id == Document.owner_id)
    if review_status:
        query = query.filter(Document.review_status == review_status)
    if q:
        query = query.filter(func.lower(Document.name).contains(q.lower(), autoescape=True))
    if owner:
        query = query.filter(func.lower(User.email).contains(owner.lower(), autoescape=True))
    rows = query.order_by(Document.created_at.desc()).offset(max(offset, 0)).limit(limit).all()
    return [_doc_admin_out(db, d, o) for d, o in rows]


class ReviewIn(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=500)


@router.post("/documents/{doc_id}/review")
def review_document(doc_id: str, body: ReviewIn, request: Request, admin: User = Depends(admin_only),
                    db: DBSession = Depends(get_db)):
    doc = db.get(Document, doc_id) if _valid_uuid(doc_id) else None
    if not doc or doc.deleted_at is not None:
        raise HTTPException(404, "Not found")
    reason = (body.reason or "").strip() or None
    if body.decision == "reject" and not reason:
        raise HTTPException(422, "Please give the owner a reason for rejecting")
    before = doc.review_status
    doc.review_status = "approved" if body.decision == "approve" else "rejected"
    doc.reviewed_by, doc.reviewed_at, doc.review_reason = admin.id, now(), reason
    audit.record(db, action="document_review", outcome="allowed", actor=admin, document_id=doc.id, ip=client_ip(request),
                 detail={"from": before, "to": doc.review_status, "reason": reason}, commit=False)
    db.commit()
    owner = db.get(User, doc.owner_id)
    notify.send(owner.email if owner else None, f"Your document was {doc.review_status}",
                f"“{doc.name}” was {doc.review_status} by an administrator." + (f" Reason: {reason}" if reason else ""))
    return _doc_admin_out(db, doc, owner)


@router.get("/documents/{doc_id}/timeline")
def document_timeline(doc_id: str, admin: User = Depends(admin_only), db: DBSession = Depends(get_db)):
    """Who did what to one document, oldest first, including refused attempts. Metadata only."""
    if not _valid_uuid(doc_id):
        raise HTTPException(404, "Not found")
    doc = db.get(Document, doc_id)
    rows = db.query(AuditLog).filter(AuditLog.document_id == doc_id).order_by(AuditLog.id.asc()).all()
    if doc is None and not rows:
        raise HTTPException(404, "Not found")
    readers: dict[str, dict] = {}
    for r in rows:
        if r.outcome == "allowed" and r.action in ("download", "view"):
            e = readers.setdefault(r.actor_email, {"email": r.actor_email, "reads": 0,
                                                   "first": aware(r.ts), "last": aware(r.ts)})
            e["reads"] += 1
            e["last"] = aware(r.ts)
    owner = db.get(User, doc.owner_id) if doc else None
    grants = db.query(Grant).filter_by(document_id=doc_id).all() if doc else []
    return {"document": None if not doc else {"id": doc.id, "name": doc.name, "owner_email": owner.email,
                                             "deleted": doc.deleted_at is not None, "review_status": doc.review_status},
            "current_grants": [{"email": db.get(User, g.user_id).email, "permission": g.permission,
                                "expires_at": g.expires_at} for g in grants],
            "readers": list(readers.values()),
            "events": [_row(r) for r in rows]}


# ------------------------------------------------------------------ upload policy
class PolicyIn(BaseModel):
    allowed_types: list[str] = Field(min_length=1, max_length=20)
    max_mb: int = Field(ge=1)
    categories: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("allowed_types")
    @classmethod
    def types_ok(cls, v):
        v = sorted({t.strip().lower().lstrip(".") for t in v})
        bad = [t for t in v if t not in ALLOWED]
        if bad or not v:
            raise ValueError(f"Unsupported file type(s): {', '.join(bad) or 'none selected'}")
        return v

    @field_validator("categories")
    @classmethod
    def cats_ok(cls, v):
        import re
        out = []
        for c in v:
            c = " ".join(c.split())
            if not re.match(CATEGORY_OK, c):
                raise ValueError(f"Invalid category: {c[:30]}")
            if c.lower() not in [x.lower() for x in out]:
                out.append(c)
        return out


@router.get("/policy")
def get_policy(admin: User = Depends(admin_only), db: DBSession = Depends(get_db)):
    return {**policy.get_policy(db), "all_types": sorted(ALLOWED)}


@router.put("/policy")
def put_policy(body: PolicyIn, request: Request, admin: User = Depends(admin_only), db: DBSession = Depends(get_db)):
    if body.max_mb > settings.max_upload_mb:
        raise HTTPException(422, f"max_mb cannot exceed the server limit of {settings.max_upload_mb} MB")
    before, after = policy.save_policy(db, admin, body.model_dump())
    audit.record(db, action="policy_update", outcome="allowed", actor=admin, ip=client_ip(request),
                 detail={"from": before, "to": after}, commit=False)
    db.commit()
    return {**after, "all_types": sorted(ALLOWED)}


@router.get("/pending-counts")
def pending_counts(admin: User = Depends(admin_only), db: DBSession = Depends(get_db)):
    """Cheap numbers for the sidebar badges: how much is waiting for an administrator."""
    return {"users": db.query(User).filter(User.status == "pending").count(),
            "documents": db.query(Document).filter(Document.deleted_at.is_(None), Document.review_status == "pending").count()}


# ------------------------------------------------------------------ alerts & summary
@router.get("/alerts")
def alerts(hours: int = Query(24, ge=1, le=720), admin: User = Depends(admin_only),
           db: DBSession = Depends(get_db)):
    return {"window_hours": hours, "alerts": alert_rules.compute_alerts(db, hours)}


@router.get("/summary")
def summary(hours: int = Query(24, ge=1, le=720), admin: User = Depends(admin_only),
            db: DBSession = Depends(get_db)):
    since = now() - timedelta(hours=hours)
    by_role = dict(db.query(User.role, func.count()).group_by(User.role).all())
    by_status = dict(db.query(User.status, func.count()).group_by(User.status).all())
    events = db.query(AuditLog.outcome, func.count()).filter(AuditLog.ts >= since).group_by(AuditLog.outcome).all()
    top = (db.query(AuditLog.action, func.count()).filter(AuditLog.ts >= since)
           .group_by(AuditLog.action).order_by(func.count().desc()).limit(10).all())
    live = Document.deleted_at.is_(None)
    return {"window_hours": hours, "users_by_role": by_role, "users_by_status": by_status,
            "pending_users": by_status.get("pending", 0),
            "pending_documents": db.query(Document).filter(live, Document.review_status == "pending").count(),
            "documents": db.query(Document).filter(live).count(),
            "documents_deleted": db.query(Document).filter(Document.deleted_at.is_not(None)).count(),
            "grants": db.query(Grant).count(),
            "events": dict(events), "top_actions": dict(top),
            "alerts_by_severity": _count_sev(alert_rules.compute_alerts(db, hours))}


def _count_sev(items):
    out: dict[str, int] = {}
    for a in items:
        out[a["severity"]] = out.get(a["severity"], 0) + 1
    return out
