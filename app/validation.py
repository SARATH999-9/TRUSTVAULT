"""Upload validation. The client's filename, extension and Content-Type are all untrusted:
the type is decided by extension allowlist AND the file's real signature, and the stored
mime type is chosen by us, never by the client."""
import os
import re
import unicodedata
import zipfile
from pathlib import Path

ALLOWED = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "txt": "text/plain",
    "csv": "text/csv",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
OFFICE_PREFIX = {"docx": "word/", "xlsx": "xl/", "pptx": "ppt/"}
MAX_UNZIPPED = 200 * 1024 * 1024
MAX_RATIO = 200


class Rejected(Exception):
    pass


def clean_filename(raw: str | None) -> str:
    name = (raw or "").replace("\\", "/").split("/")[-1]
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"[\x00-\x1f\x7f<>:\"|?*]", "", name).strip(" .")
    root, ext = os.path.splitext(name)
    return (root[:120] or "document") + ext.lower()


def extension(name: str) -> str:
    return os.path.splitext(name)[1].lstrip(".").lower()


def validate(path: Path, filename: str, size: int) -> str:
    ext = extension(filename)
    if ext not in ALLOWED:
        raise Rejected(f"File type not allowed. Allowed: {', '.join(sorted(ALLOWED))}")
    if size == 0:
        raise Rejected("Empty file")
    with open(path, "rb") as f:
        head = f.read(16)
    if ext == "pdf" and not head.startswith(b"%PDF-"):
        raise Rejected("Content is not a PDF")
    if ext == "png" and not head.startswith(b"\x89PNG\r\n\x1a\n"):
        raise Rejected("Content is not a PNG")
    if ext in ("jpg", "jpeg") and not head.startswith(b"\xff\xd8\xff"):
        raise Rejected("Content is not a JPEG")
    if ext in ("txt", "csv"):
        data = path.read_bytes()
        if b"\x00" in data:
            raise Rejected("Binary content in a text file")
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise Rejected("Text files must be UTF-8")
    if ext in OFFICE_PREFIX:
        _check_office_zip(path, size, OFFICE_PREFIX[ext])
    return ALLOWED[ext]


def _check_office_zip(path: Path, size: int, prefix: str) -> None:
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            names = [i.filename for i in infos]
            if "[Content_Types].xml" not in names or not any(n.startswith(prefix) for n in names):
                raise Rejected("Not a valid Office document")
            if any(n.startswith("/") or ".." in n.split("/") for n in names):
                raise Rejected("Unsafe paths inside archive")
            total = sum(i.file_size for i in infos)
            if total > MAX_UNZIPPED or total / max(size, 1) > MAX_RATIO:
                raise Rejected("Archive expands suspiciously (possible zip bomb)")
    except zipfile.BadZipFile:
        raise Rejected("Not a valid Office document")
