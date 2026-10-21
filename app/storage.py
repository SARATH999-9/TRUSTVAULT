"""Files live OUTSIDE any web root under random 128-bit keys. The only way to read one is
app.routes.documents.download, which calls authorize() first. User-supplied names never touch the disk."""
import hashlib
import os
import re
import uuid
from pathlib import Path

from .config import settings

KEY_RE = re.compile(r"^[0-9a-f]{32}$")


class TooLarge(Exception):
    pass


def root() -> Path:
    p = Path(settings.storage_dir).resolve()
    (p / "tmp").mkdir(parents=True, exist_ok=True)
    return p


def save_temp(fileobj, max_bytes: int) -> tuple[Path, int, str]:
    """Stream to a temp file, enforcing the size cap on bytes actually read (never trusts headers)."""
    tmp = root() / "tmp" / uuid.uuid4().hex
    h, size = hashlib.sha256(), 0
    try:
        with open(tmp, "xb") as out:
            while True:
                chunk = fileobj.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise TooLarge()
                h.update(chunk)
                out.write(chunk)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp, size, h.hexdigest()


def commit(tmp: Path) -> str:
    key = uuid.uuid4().hex
    dest = path_for(key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp, dest)
    os.chmod(dest, 0o600)
    return key


def path_for(key: str) -> Path:
    if not KEY_RE.match(key):
        raise ValueError("bad storage key")
    p = (root() / key[:2] / key).resolve()
    if root() not in p.parents:
        raise ValueError("path escape")
    return p
