import io
import re
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from .. import audit, notify, policy, storage, validation
from ..authz import authorize
from ..config import settings
from ..db import get_db
from ..deps import client_ip, require_roles
from ..models import Document, DocumentVersion, Grant, User, now
from ..security import aware

router = APIRouter(prefix="/documents", tags=["documents"])
any_user = require_roles("owner", "viewer")   # admins never touch document content
owner_only = require_roles("owner")
CATEGORY_RE = re.compile(r"^[\w .&-]{1,60}$")
MAX_TEXT_CHARS = 200_000


def _clean_text(v: str, limit: int) -> str:
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", v).strip()[:limit]


def _category(v: str, pol: dict) -> str:
    v = (v or "").strip() or "general"
    if not CATEGORY_RE.match(v):
        raise HTTPException(422, "Invalid category")
    if pol["categories"] and v.lower() not in [c.lower() for c in pol["categories"]]:
        raise HTTPException(422, f"Category must be one of: {', '.join(pol['categories'])}")
    return v


class DocumentUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    category: str | None = Field(default=None, max_length=60)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("category")
    @classmethod
    def cat(cls, v):
        if v is not None and not CATEGORY_RE.match(v.strip()):
            raise ValueError("Invalid category")
        return v.strip() if v else v


class ComposeIn(BaseModel):
    """Write a text document in the browser instead of uploading a file."""
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(default="general", max_length=60)
    description: str = Field(default="", max_length=2000)
    content: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)


class TextVersionIn(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)


def _ingest(fileobj, filename: str | None, pol: dict) -> dict:
    """Validate and store one file against the administrator's policy. Returns the data for a DocumentVersion."""
    filename = validation.clean_filename(filename)
    ext = validation.extension(filename)
    if ext not in pol["allowed_types"]:
        raise HTTPException(415, f"File type .{ext or '?'} is not allowed. Allowed: {', '.join(pol['allowed_types'])}")
    try:
        tmp, size, sha = storage.save_temp(fileobj, pol["max_mb"] * 1024 * 1024)
    except storage.TooLarge:
        raise HTTPException(413, f"File exceeds the {pol['max_mb']} MB limit")
    try:
        mime = validation.validate(tmp, filename, size)
    except validation.Rejected as e:
        tmp.unlink(missing_ok=True)
        raise HTTPException(415, str(e))
    key = storage.commit(tmp)
    return dict(storage_key=key, original_filename=filename, mime_type=mime, size_bytes=size, sha256=sha)


def _initial_review() -> str:
    return "pending" if settings.require_document_approval else "approved"


def _notify_admins_of_upload(db: DBSession, doc: Document, owner: User, what: str) -> None:
    if doc.review_status != "pending":
        return
    for a in db.query(User).filter(User.role == "admin", User.status == "active"):
        notify.send(a.email, "A document is waiting for review",
                    f"{owner.name} <{owner.email}> {what} “{doc.name}” ({doc.category}). Review it under Documents.")


def _version_out(v: DocumentVersion, db: DBSession) -> dict:
    up = db.get(User, v.uploaded_by)
    return {"id": v.id, "version_no": v.version_no, "original_filename": v.original_filename,
            "mime_type": v.mime_type, "size_bytes": v.size_bytes, "sha256": v.sha256,
            "uploaded_by": up.email if up else None, "created_at": v.created_at}


def _doc_out(doc: Document, owner: User, access: str, latest: DocumentVersion | None) -> dict:
    return {"id": doc.id, "name": doc.name, "category": doc.category, "description": doc.description,
            "owner": {"id": owner.id, "email": owner.email, "name": owner.name},
            "created_at": doc.created_at, "my_access": access,
            "review_status": doc.review_status, "review_reason": doc.review_reason,
            "latest_version": None if latest is None else
            {"version_no": latest.version_no, "size_bytes": latest.size_bytes, "mime_type": latest.mime_type,
             "original_filename": latest.original_filename}}


def _latest(db: DBSession, doc_id: str) -> DocumentVersion | None:
    return (db.query(DocumentVersion).filter_by(document_id=doc_id)
            .order_by(DocumentVersion.version_no.desc()).first())


def _create_document(db, request, user, info, name, category, description) -> Document:
    doc = Document(owner_id=user.id, category=category, name=name, description=description,
                   review_status=_initial_review())
    try:
        db.add(doc)
        db.flush()
        db.add(DocumentVersion(document_id=doc.id, version_no=1, uploaded_by=user.id, **info))
        audit.record(db, action="upload", outcome="allowed", actor=user, document_id=doc.id, ip=client_ip(request),
                     detail={"filename": info["original_filename"], "size": info["size_bytes"],
                             "sha256": info["sha256"], "review": doc.review_status}, commit=False)
        db.commit()
    except Exception:
        db.rollback()
        storage.path_for(info["storage_key"]).unlink(missing_ok=True)
        raise
    _notify_admins_of_upload(db, doc, user, "uploaded")
    return doc


def _add_version(db, request, user, doc, info) -> DocumentVersion:
    try:
        last = db.query(func.max(DocumentVersion.version_no)).filter_by(document_id=doc.id).scalar() or 0
        v = DocumentVersion(document_id=doc.id, version_no=last + 1, uploaded_by=user.id, **info)
        db.add(v)
        detail = {"version_no": last + 1, "size": info["size_bytes"], "sha256": info["sha256"]}
        if settings.require_document_approval and doc.review_status != "pending":
            # What was approved is no longer what is stored, so approval no longer applies.
            detail["review_reset_from"] = doc.review_status
            doc.review_status, doc.reviewed_by, doc.reviewed_at, doc.review_reason = "pending", None, None, None
        audit.record(db, action="version_upload", outcome="allowed", actor=user, document_id=doc.id,
                     ip=client_ip(request), detail=detail, commit=False)
        db.commit()
    except IntegrityError:
        db.rollback()
        storage.path_for(info["storage_key"]).unlink(missing_ok=True)
        raise HTTPException(409, "Concurrent upload, please retry")
    except Exception:
        db.rollback()
        storage.path_for(info["storage_key"]).unlink(missing_ok=True)
        raise
    _notify_admins_of_upload(db, doc, user, "uploaded a new version of")
    return v


@router.post("", status_code=201)
def upload_document(request: Request, file: UploadFile = File(...), name: str | None = Form(None),
                    category: str = Form("general"), description: str = Form(""),
                    user: User = Depends(owner_only), db: DBSession = Depends(get_db)):
    pol = policy.get_policy(db)
    category = _category(category, pol)
    info = _ingest(file.file, file.filename, pol)
    doc = _create_document(db, request, user, info,
                           _clean_text(name, 255) if name and name.strip() else info["original_filename"],
                           category, _clean_text(description, 2000))
    return _doc_out(doc, user, "owner", _latest(db, doc.id))


@router.post("/compose", status_code=201)
def compose_document(body: ComposeIn, request: Request, user: User = Depends(owner_only),
                     db: DBSession = Depends(get_db)):
    pol = policy.get_policy(db)
    category = _category(body.category, pol)
    title = _clean_text(body.name, 200)
    if not title:
        raise HTTPException(422, "A title is required")
    info = _ingest(io.BytesIO(body.content.encode("utf-8")), f"{title}.txt", pol)
    doc = _create_document(db, request, user, info, title, category, _clean_text(body.description, 2000))
    return _doc_out(doc, user, "owner", _latest(db, doc.id))


@router.get("")
def list_documents(q: str | None = Query(None, max_length=100), owner: str | None = Query(None, max_length=100),
                   category: str | None = Query(None, max_length=60),
                   review: str | None = Query(None, pattern="^(pending|approved|rejected)$"),
                   created_from: datetime | None = None, created_to: datetime | None = None,
                   limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                   user: User = Depends(any_user), db: DBSession = Depends(get_db)):
    """Search runs INSIDE the set of documents this user may already read. Nothing is searched
    and then filtered afterwards, so counts and results cannot leak other people's documents.
    Shared documents appear only while approved and while their owner is still active."""
    t = now()
    granted = db.query(Grant.document_id).filter(
        Grant.user_id == user.id, or_(Grant.expires_at.is_(None), Grant.expires_at > t))
    own = (Document.owner_id == user.id) if user.role == "owner" else (Document.id == None)  # noqa: E711
    shared = (Document.id.in_(granted)) & (Document.review_status == "approved") & (User.status == "active")
    query = (db.query(Document, User).join(User, User.id == Document.owner_id)
             .filter(Document.deleted_at.is_(None), or_(own, shared)))
    if q:
        query = query.filter(func.lower(Document.name).contains(q.lower(), autoescape=True))
    if owner:
        o = owner.lower()
        query = query.filter(or_(func.lower(User.email).contains(o, autoescape=True),
                                 func.lower(User.name).contains(o, autoescape=True)))
    if category:
        query = query.filter(Document.category == category)
    if review:
        query = query.filter(Document.review_status == review)
    if created_from:
        query = query.filter(Document.created_at >= aware(created_from))
    if created_to:
        query = query.filter(Document.created_at <= aware(created_to))
    total = query.count()
    rows = query.order_by(Document.created_at.desc()).offset(offset).limit(limit).all()
    out = []
    for doc, owner_user in rows:
        access = "owner"
        if doc.owner_id != user.id or user.role != "owner":
            g = db.query(Grant).filter_by(document_id=doc.id, user_id=user.id).first()
            access = "read" if (user.role == "viewer" or not g) else g.permission
        out.append(_doc_out(doc, owner_user, access, _latest(db, doc.id)))
    return {"total": total, "items": out}


@router.get("/{doc_id}")
def get_document(doc_id: str, request: Request, user: User = Depends(any_user), db: DBSession = Depends(get_db)):
    doc, perm = authorize(db, user, doc_id, "read", request, "view")
    owner = db.get(User, doc.owner_id)
    versions = db.query(DocumentVersion).filter_by(document_id=doc.id).order_by(DocumentVersion.version_no).all()
    out = _doc_out(doc, owner, perm, versions[-1] if versions else None)
    out["versions"] = [_version_out(v, db) for v in versions]
    return out


@router.get("/{doc_id}/download")
def download(doc_id: str, request: Request, version: str | None = None,
             user: User = Depends(any_user), db: DBSession = Depends(get_db)):
    doc, perm = authorize(db, user, doc_id, "read", request, "download")
    vq = db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id)  # version must belong to THIS doc
    v = vq.filter(DocumentVersion.id == version).first() if version else vq.order_by(
        DocumentVersion.version_no.desc()).first()
    if not v:
        audit.record(db, action="download", outcome="denied", actor=user, document_id=doc.id,
                     ip=client_ip(request), detail={"reason": "bad_version"})
        raise HTTPException(404, "Not found")
    path = storage.path_for(v.storage_key)
    if not path.exists():
        raise HTTPException(404, "Not found")
    audit.record(db, action="download", outcome="allowed", actor=user, document_id=doc.id,
                 ip=client_ip(request), detail={"version_no": v.version_no, "sha256": v.sha256})
    return FileResponse(path, media_type=v.mime_type, filename=v.original_filename,
                        content_disposition_type="attachment",
                        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})


@router.patch("/{doc_id}")
def update_document(doc_id: str, body: DocumentUpdateIn, request: Request,
                    user: User = Depends(any_user), db: DBSession = Depends(get_db)):
    doc, perm = authorize(db, user, doc_id, "edit", request, "document_update")
    pol = policy.get_policy(db)
    if body.category is not None:
        body.category = _category(body.category, pol)
    changes = {}
    for field in ("name", "category", "description"):
        new = getattr(body, field)
        if new is not None and new != getattr(doc, field):
            new = _clean_text(new, 2000 if field == "description" else 255)
            changes[field] = [getattr(doc, field), new]
            setattr(doc, field, new)
    audit.record(db, action="document_update", outcome="allowed", actor=user, document_id=doc.id,
                 ip=client_ip(request), detail=changes, commit=False)
    db.commit()
    return _doc_out(doc, db.get(User, doc.owner_id), perm, _latest(db, doc.id))


@router.post("/{doc_id}/versions", status_code=201)
def upload_version(doc_id: str, request: Request, file: UploadFile = File(...),
                   user: User = Depends(any_user), db: DBSession = Depends(get_db)):
    doc, perm = authorize(db, user, doc_id, "edit", request, "version_upload")
    info = _ingest(file.file, file.filename, policy.get_policy(db))
    return _version_out(_add_version(db, request, user, doc, info), db)


@router.post("/{doc_id}/versions/text", status_code=201)
def upload_text_version(doc_id: str, body: TextVersionIn, request: Request,
                        user: User = Depends(any_user), db: DBSession = Depends(get_db)):
    """Edit a text document in the browser: stores the new text as a new version."""
    doc, perm = authorize(db, user, doc_id, "edit", request, "version_upload")
    last = _latest(db, doc.id)
    if not last or validation.extension(last.original_filename) != "txt":
        raise HTTPException(415, "Only text (.txt) documents can be edited in the browser")
    info = _ingest(io.BytesIO(body.content.encode("utf-8")), last.original_filename, policy.get_policy(db))
    return _version_out(_add_version(db, request, user, doc, info), db)


@router.delete("/{doc_id}")
def delete_document(doc_id: str, request: Request, user: User = Depends(any_user),
                    db: DBSession = Depends(get_db)):
    """Soft delete, owner only. Files and history are kept for recovery by an operator."""
    doc, perm = authorize(db, user, doc_id, "owner", request, "document_delete")
    doc.deleted_at = now()
    audit.record(db, action="document_delete", outcome="allowed", actor=user, document_id=doc.id,
                 ip=client_ip(request), commit=False)
    db.commit()
    return {"ok": True}
