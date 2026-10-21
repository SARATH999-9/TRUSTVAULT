"""THE authorisation choke point. Every route that touches a document calls authorize(); nothing else
decides who may see a document. Rules (see docs/DESIGN.md):

  * admin role      -> never gets document content, even if it owns or was granted something.
  * approval        -> anyone but the owner needs the document to be 'approved' by an administrator,
                       and the owner's account to still be 'active' (suspending an owner freezes sharing).
  * owner           -> only if user.role == 'owner' and doc.owner_id == user.id.
  * grants          -> a row in `grants` that has not expired. 'edit' implies 'read'.
  * viewer role     -> capped at 'read' even if an 'edit' grant row somehow exists.
  * no access       -> 404 (document existence is not revealed). Insufficient level -> 403.
  * every refusal is written to the audit log before the error is raised.
"""
import uuid

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session as DBSession

from . import audit
from .deps import client_ip
from .models import Document, Grant, User, now
from .security import aware

RANK = {"read": 1, "edit": 2}


def effective_permission(db: DBSession, user: User, doc: Document) -> str | None:
    """Returns 'owner', 'edit', 'read' or None. Always read fresh from the database."""
    if user.role == "admin":
        return None
    if doc.owner_id == user.id and user.role == "owner":
        return "owner"
    if doc.review_status != "approved":
        return None
    owner = db.get(User, doc.owner_id)
    if owner is None or owner.status != "active":
        return None
    g = db.query(Grant).filter(Grant.document_id == doc.id, Grant.user_id == user.id).first()
    if not g or (g.expires_at is not None and aware(g.expires_at) <= now()):
        return None
    perm = g.permission if g.permission in RANK else None
    if perm and user.role == "viewer":
        perm = "read"
    return perm


def _valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def authorize(db: DBSession, user: User, doc_id: str, need: str, request: Request, action: str):
    """need: 'read' | 'edit' | 'owner'. Returns (document, permission) or raises 404/403 after auditing."""
    ip = client_ip(request)
    doc = db.get(Document, doc_id) if _valid_uuid(doc_id) else None
    doc_ref = doc_id if _valid_uuid(doc_id) else None

    def refuse(status: int, reason: str):
        audit.record(db, action=action, outcome="denied", actor=user, document_id=doc_ref, ip=ip,
                     detail={"reason": reason, "needed": need, "path": request.url.path[:200]})
        raise HTTPException(status, "Not found" if status == 404 else "Forbidden")

    if doc is None or doc.deleted_at is not None:
        refuse(404, "not_found")
    perm = effective_permission(db, user, doc)
    if perm is None:
        refuse(404, "no_access")
    if perm == "owner" or (need in RANK and RANK[perm] >= RANK[need]):
        return doc, perm
    refuse(403, "insufficient_permission")
