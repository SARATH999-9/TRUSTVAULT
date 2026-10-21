"""DEVELOPMENT ONLY: fills a local database with sample accounts and documents so you can click around.
Never run this in production. Real deployments create their first administrator from ADMIN_EMAIL /
ADMIN_PASSWORD and everyone else signs up (or uses Google) and is approved by that administrator.

    python scripts/seed.py --demo            # password comes from SEED_PASSWORD, or is generated and printed
"""
import io
import pathlib
import secrets
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import audit, storage  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Document, DocumentVersion, Grant, User, now  # noqa: E402
from app.security import hash_password  # noqa: E402

USERS = [("admin@trustvault.test", "Ada Admin", "admin"), ("owner@trustvault.test", "Olivia Owner", "owner"),
         ("owner2@trustvault.test", "Omar Owner", "owner"), ("viewer@trustvault.test", "Vera Viewer", "viewer"),
         ("viewer2@trustvault.test", "Victor Viewer", "viewer")]
PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
DOCS = [("Salary letter - Vera.pdf", "hr", PDF), ("Customer contract - Acme.pdf", "contracts", PDF),
        ("Audit notes Q3.txt", "audit", b"Quarterly audit notes (sample data).\n")]


def main():
    if "--demo" not in sys.argv and not settings.seed_demo:
        print("Refusing to seed: pass --demo (development only).")
        return
    password = settings.seed_password or secrets.token_urlsafe(12)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email.like("%@trustvault.test")).count():
            print("Sample data already present.")
            return
        users = {}
        for email, name, role in USERS:
            u = User(email=email, name=name, role=role, status="active", email_verified=True,
                     password_hash=hash_password(password), decided_at=now())
            db.add(u)
            users[email] = u
        db.flush()
        owner = users["owner@trustvault.test"]
        docs = []
        for name, cat, content in DOCS:
            tmp, size, sha = storage.save_temp(io.BytesIO(content), 5 * 1024 * 1024)
            key = storage.commit(tmp)
            d = Document(owner_id=owner.id, name=name, category=cat, description="Sample document", review_status="approved")
            db.add(d)
            db.flush()
            db.add(DocumentVersion(document_id=d.id, version_no=1, storage_key=key, original_filename=name,
                                   mime_type="application/pdf" if name.endswith(".pdf") else "text/plain",
                                   size_bytes=size, sha256=sha, uploaded_by=owner.id))
            audit.record(db, action="upload", outcome="allowed", actor=owner, document_id=d.id,
                         detail={"sample": True, "filename": name}, commit=False)
            docs.append(d)
        viewer = users["viewer@trustvault.test"]
        db.add(Grant(document_id=docs[0].id, user_id=viewer.id, permission="read", granted_by=owner.id))
        audit.record(db, action="grant_create", outcome="allowed", actor=owner, document_id=docs[0].id,
                     target_user_id=viewer.id, detail={"sample": True, "permission": "read"}, commit=False)
        db.commit()
        print(f"Sample data created: {len(USERS)} users (@trustvault.test), {len(DOCS)} documents.\nPassword for all: {password}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
