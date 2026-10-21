"""Granting and revoking access. Owner-only, enforced by authorize(need='owner') on every route."""
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from .. import audit
from ..authz import authorize
from ..db import get_db
from ..deps import client_ip, require_roles
from ..models import Grant, User, now
from ..security import aware

router = APIRouter(prefix="/documents/{doc_id}/grants", tags=["grants"])
any_user = require_roles("owner", "viewer")
MAX_GRANT_DAYS = 365
# One message for every reason a grantee is unacceptable, so an owner cannot use this endpoint
# to discover which emails exist, who is an admin, or who is deactivated.
CANNOT_GRANT = "Cannot grant access to that user"


class GrantIn(BaseModel):
    email: str = Field(max_length=254)
    permission: Literal["read", "edit"]
    expires_at: datetime | None = None

    @field_validator("email")
    @classmethod
    def norm(cls, v):
        return v.strip().lower()


def _out(g: Grant, db: DBSession) -> dict:
    u, by = db.get(User, g.user_id), db.get(User, g.granted_by)
    return {"id": g.id, "user": {"id": u.id, "email": u.email, "name": u.name, "role": u.role},
            "permission": g.permission, "expires_at": g.expires_at, "created_at": g.created_at,
            "granted_by": by.email if by else None}


def apply_grant(db: DBSession, owner: User, doc, grantee: User | None, email: str, permission: str,
                expires_at: datetime | None, ip: str | None, via: dict | None = None) -> Grant:
    """The ONE place a grant is created or changed, whether the owner typed it or confirmed an AI suggestion.
    Caller must already have authorised `owner` for `doc` with need='owner'."""
    def refuse(status: int, msg: str, reason: str):
        audit.record(db, action="grant_change", outcome="denied", actor=owner, document_id=doc.id, ip=ip,
                     detail={"reason": reason, "email": email[:254], **(via or {})})
        raise HTTPException(status, msg)

    if doc.review_status != "approved":
        refuse(409, "An administrator must approve this document before it can be shared.", "not_approved")
    if grantee is None or not grantee.is_active or grantee.role == "admin" or grantee.id == owner.id:
        refuse(422, CANNOT_GRANT, "invalid_grantee")
    if grantee.role == "viewer" and permission == "edit":
        refuse(422, "Viewers can only be given read access", "viewer_edit")
    exp = None
    if expires_at is not None:
        exp = aware(expires_at)
        if exp <= now() or exp > now() + timedelta(days=MAX_GRANT_DAYS):
            refuse(422, f"expires_at must be in the future and within {MAX_GRANT_DAYS} days", "bad_expiry")

    g = db.query(Grant).filter_by(document_id=doc.id, user_id=grantee.id).first()
    try:
        if g:
            before = {"permission": g.permission, "expires_at": g.expires_at}
            g.permission, g.expires_at, g.granted_by = permission, exp, owner.id
            audit.record(db, action="grant_update", outcome="allowed", actor=owner, document_id=doc.id,
                         target_user_id=grantee.id, ip=ip, commit=False,
                         detail={"from": before, "to": {"permission": permission, "expires_at": exp}, **(via or {})})
        else:
            g = Grant(document_id=doc.id, user_id=grantee.id, permission=permission,
                      granted_by=owner.id, expires_at=exp)
            db.add(g)
            db.flush()
            audit.record(db, action="grant_create", outcome="allowed", actor=owner, document_id=doc.id,
                         target_user_id=grantee.id, ip=ip, commit=False,
                         detail={"grant_id": g.id, "permission": permission, "expires_at": exp, **(via or {})})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Concurrent change, please retry")
    return g


@router.post("", status_code=201)
def grant_access(doc_id: str, body: GrantIn, request: Request, user: User = Depends(any_user),
                 db: DBSession = Depends(get_db)):
    doc, _ = authorize(db, user, doc_id, "owner", request, "grant_change")
    grantee = db.query(User).filter(User.email == body.email).first()
    g = apply_grant(db, user, doc, grantee, body.email, body.permission, body.expires_at, client_ip(request))
    return _out(g, db)


@router.get("")
def list_grants(doc_id: str, request: Request, user: User = Depends(any_user), db: DBSession = Depends(get_db)):
    doc, _ = authorize(db, user, doc_id, "owner", request, "grant_list")
    return [_out(g, db) for g in db.query(Grant).filter_by(document_id=doc.id).order_by(Grant.created_at)]


@router.delete("/{grant_id}")
def revoke_access(doc_id: str, grant_id: str, request: Request, user: User = Depends(any_user),
                  db: DBSession = Depends(get_db)):
    """Deletes the row. The grantee's very next request to any document route is refused."""
    doc, _ = authorize(db, user, doc_id, "owner", request, "grant_change")
    g = db.query(Grant).filter(Grant.id == grant_id, Grant.document_id == doc.id).first()  # bound to THIS doc
    if not g:
        audit.record(db, action="grant_change", outcome="denied", actor=user, document_id=doc.id,
                     ip=client_ip(request), detail={"reason": "grant_not_found"})
        raise HTTPException(404, "Not found")
    detail = {"grant_id": g.id, "permission": g.permission}
    target = g.user_id
    db.delete(g)
    audit.record(db, action="grant_revoke", outcome="allowed", actor=user, document_id=doc.id,
                 target_user_id=target, ip=client_ip(request), detail=detail, commit=False)
    db.commit()
    return {"ok": True}
