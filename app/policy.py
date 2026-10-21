"""Administrator-controlled upload policy: which file types, how big, which categories."""
import json

from sqlalchemy.orm import Session as DBSession

from .config import settings
from .models import AppSetting, User, now
from .validation import ALLOWED

KEY = "upload_policy"


def get_policy(db: DBSession) -> dict:
    row = db.get(AppSetting, KEY)
    try:
        data = json.loads(row.value) if row else {}
    except ValueError:
        data = {}
    types = [t for t in data.get("allowed_types", sorted(ALLOWED)) if t in ALLOWED] or sorted(ALLOWED)
    max_mb = max(1, min(int(data.get("max_mb", settings.max_upload_mb)), settings.max_upload_mb))
    return {"allowed_types": types, "max_mb": max_mb, "categories": list(data.get("categories", [])),
            "require_approval": settings.require_document_approval, "server_max_mb": settings.max_upload_mb}


def save_policy(db: DBSession, admin: User, new: dict) -> tuple[dict, dict]:
    before = get_policy(db)
    row = db.get(AppSetting, KEY)
    value = json.dumps({"allowed_types": new["allowed_types"], "max_mb": new["max_mb"], "categories": new["categories"]})
    if row:
        row.value, row.updated_by, row.updated_at = value, admin.id, now()
    else:
        db.add(AppSetting(key=KEY, value=value, updated_by=admin.id))
    db.flush()
    return before, get_policy(db)
