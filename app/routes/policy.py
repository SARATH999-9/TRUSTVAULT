from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from .. import policy
from ..db import get_db
from ..deps import current_user
from ..models import User

router = APIRouter(prefix="/policy", tags=["policy"])


@router.get("")
def upload_policy(user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    """What the administrator currently allows to be uploaded (the upload form reads this)."""
    return policy.get_policy(db)
