"""AI-assisted sharing. The machine proposes, a person decides, and both are audited.
Nothing in this file grants access by itself: grants only happen in decide(), on an explicit owner request."""
import json
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session as DBSession

from .. import audit, suggest
from ..authz import authorize
from ..config import settings
from ..db import get_db
from ..deps import client_ip, require_roles
from ..models import AiSuggestion, User, now
from ..security import aware
from .grants import apply_grant

router = APIRouter(prefix="/documents/{doc_id}/suggestions", tags=["ai-suggestions"])
any_user = require_roles("owner", "viewer")


class DecisionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(max_length=36)
    accept: bool
    permission: Literal["read", "edit"] | None = None
    expires_at: datetime | None = None


class DecisionsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")        # no hidden 'auto_accept' style switches
    decisions: list[DecisionItem] = Field(min_length=1, max_length=20)


def _view(s: AiSuggestion, db: DBSession) -> dict:
    cands = []
    for c in json.loads(s.candidates):
        u = db.get(User, c["user_id"])
        cands.append({**c, "email": u.email if u else None, "name": u.name if u else None,
                      "role": u.role if u else None})
    return {"id": s.id, "document_id": s.document_id, "source": s.source,
            "created_at": aware(s.created_at), "candidates": cands,
            "note": "Suggestions grant nothing. Confirm each person explicitly to share."}


def _load(db: DBSession, doc_id: str, sid: str, user: User) -> AiSuggestion:
    s = db.query(AiSuggestion).filter(AiSuggestion.id == sid, AiSuggestion.document_id == doc_id,
                                      AiSuggestion.requested_by == user.id).first()
    if not s:
        raise HTTPException(404, "Not found")
    return s


@router.post("", status_code=201)
def create_suggestion(doc_id: str, request: Request, user: User = Depends(any_user), db: DBSession = Depends(get_db)):
    doc, _ = authorize(db, user, doc_id, "owner", request, "ai_suggest")
    hour_ago = now() - timedelta(hours=1)
    if db.query(AiSuggestion).filter(AiSuggestion.requested_by == user.id,
                                     AiSuggestion.created_at >= hour_ago).count() >= settings.suggestions_per_hour:
        audit.record(db, action="ai_suggest", outcome="denied", actor=user, document_id=doc.id,
                     ip=client_ip(request), detail={"reason": "rate_limited"})
        raise HTTPException(429, "Too many suggestion requests, try again later")
    source, cands = suggest.generate(db, user, doc)
    s = AiSuggestion(document_id=doc.id, requested_by=user.id, source=source, candidates=json.dumps(cands))
    db.add(s)
    db.flush()
    audit.record(db, action="ai_suggestion", outcome="allowed", actor=user, document_id=doc.id,
                 ip=client_ip(request), commit=False,
                 detail={"suggestion_id": s.id, "source": source,
                         "candidates": [{"user_id": c["user_id"], "score": c["score"]} for c in cands]})
    db.commit()
    return _view(s, db)


@router.get("/{sid}")
def get_suggestion(doc_id: str, sid: str, request: Request, user: User = Depends(any_user),
                   db: DBSession = Depends(get_db)):
    authorize(db, user, doc_id, "owner", request, "ai_suggest")
    return _view(_load(db, doc_id, sid, user), db)


@router.post("/{sid}/decisions")
def decide(doc_id: str, sid: str, body: DecisionsIn, request: Request, user: User = Depends(any_user),
           db: DBSession = Depends(get_db)):
    """The human step. Only candidates that were in THIS suggestion can be decided, each once,
    and acceptance runs through the same apply_grant() validation as a hand-typed grant."""
    doc, _ = authorize(db, user, doc_id, "owner", request, "ai_suggest")
    s = _load(db, doc_id, sid, user)
    if aware(s.created_at) + timedelta(hours=settings.suggestion_ttl_hours) < now():
        raise HTTPException(410, "Suggestion expired; request a new one")
    ip = client_ip(request)
    cands = json.loads(s.candidates)
    by_id = {c["user_id"]: c for c in cands}
    via = {"via": "ai_suggestion", "suggestion_id": s.id, "source": s.source}
    results = []
    for d in body.decisions:
        c = by_id.get(d.user_id)
        if c is None:
            raise HTTPException(422, "That person was not part of this suggestion")
        if c["decision"] is not None:
            results.append({"user_id": d.user_id, "outcome": "error", "detail": "Already decided"})
            continue
        grantee = db.get(User, d.user_id)
        if not d.accept:
            c["decision"] = "rejected"
            audit.record(db, action="ai_suggestion_decision", outcome="allowed", actor=user, document_id=doc.id,
                         target_user_id=d.user_id, ip=ip, detail={**via, "decision": "rejected"}, commit=False)
            results.append({"user_id": d.user_id, "outcome": "rejected"})
            continue
        perm = d.permission or c["suggested_permission"]
        try:
            apply_grant(db, user, doc, grantee, grantee.email if grantee else "", perm, d.expires_at, ip, via=via)
        except HTTPException as e:
            audit.record(db, action="ai_suggestion_decision", outcome="denied", actor=user, document_id=doc.id,
                         target_user_id=d.user_id, ip=ip, detail={**via, "decision": "accept_failed", "permission": perm})
            results.append({"user_id": d.user_id, "outcome": "error", "detail": e.detail})
            continue
        c["decision"] = "accepted"
        audit.record(db, action="ai_suggestion_decision", outcome="allowed", actor=user, document_id=doc.id,
                     target_user_id=d.user_id, ip=ip, detail={**via, "decision": "accepted", "permission": perm},
                     commit=False)
        results.append({"user_id": d.user_id, "outcome": "accepted", "permission": perm})
    s.candidates = json.dumps(cands)
    db.commit()
    return {"results": results}
