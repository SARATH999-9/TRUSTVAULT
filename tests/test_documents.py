"""The core promise: a user who was not granted a document cannot reach it, by any route."""
import io
import os
import zipfile
from datetime import timedelta

import pytest

from app import storage
from app.config import settings
from app.models import AuditLog, Document, DocumentVersion, Grant, now

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


def upload(client, headers, name="salary.pdf", content=PDF, **form):
    return client.post("/documents", headers=headers, files={"file": (name, content, "application/pdf")}, data=form)


def grant(db, doc_id, user, perm, by, expires=None):
    db.add(Grant(document_id=doc_id, user_id=user.id, permission=perm, granted_by=by.id, expires_at=expires))
    db.commit()


@pytest.fixture
def world(client, make_user, login):
    """alice (owner) has a document; bob (owner) and vic (viewer) have none; admin exists."""
    alice = make_user("owner", "alice@example.com")
    bob = make_user("owner", "bob@example.com")
    vic = make_user("viewer", "vic@example.com")
    adm = make_user("admin", "admin@example.com")
    h = {k: login(f"{k}@example.com") for k in ("alice", "bob", "vic", "admin")}
    r = upload(client, h["alice"], category="hr")
    assert r.status_code == 201, r.text
    return dict(alice=alice, bob=bob, vic=vic, adm=adm, h=h, doc=r.json()["id"])


def all_routes(client, doc, h):
    return {
        "view": client.get(f"/documents/{doc}", headers=h),
        "download": client.get(f"/documents/{doc}/download", headers=h),
        "patch": client.patch(f"/documents/{doc}", headers=h, json={"name": "hacked"}),
        "version": client.post(f"/documents/{doc}/versions", headers=h, files={"file": ("x.pdf", PDF)}),
        "delete": client.delete(f"/documents/{doc}", headers=h),
    }


# ---------- not granted == cannot reach, on EVERY route ----------
@pytest.mark.parametrize("who", ["bob", "vic"])
def test_ungranted_user_cannot_reach_document_by_any_route(client, world, who):
    res = all_routes(client, world["doc"], world["h"][who])
    assert {k: r.status_code for k, r in res.items()} == {k: 404 for k in res}


def test_refusal_is_identical_to_nonexistent_document(client, world):
    h = world["h"]["bob"]
    real = client.get(f"/documents/{world['doc']}", headers=h)
    fake = client.get("/documents/00000000-0000-4000-8000-000000000000", headers=h)
    junk = client.get("/documents/not-a-uuid", headers=h)
    assert real.status_code == fake.status_code == junk.status_code == 404
    assert real.json() == fake.json() == junk.json()


def test_document_unchanged_after_all_attacks(client, world, db):
    all_routes(client, world["doc"], world["h"]["bob"])
    all_routes(client, world["doc"], world["h"]["vic"])
    d = db.get(Document, world["doc"])
    assert d.name == "salary.pdf" and d.deleted_at is None
    assert db.query(DocumentVersion).filter_by(document_id=d.id).count() == 1


def test_refused_attempts_are_audited_with_actor_and_document(client, world, db):
    client.get(f"/documents/{world['doc']}/download", headers=world["h"]["bob"])
    row = (db.query(AuditLog).filter_by(action="download", outcome="denied").one())
    assert row.actor_email == "bob@example.com" and row.document_id == world["doc"]


def test_anonymous_cannot_reach_anything(client, world):
    d = world["doc"]
    assert client.get("/documents").status_code == 401
    assert client.get(f"/documents/{d}").status_code == 401
    assert client.get(f"/documents/{d}/download").status_code == 401
    assert client.delete(f"/documents/{d}").status_code == 401


def test_admin_can_not_read_content_but_sees_metadata(client, world):
    h = world["h"]["admin"]
    assert client.get(f"/documents/{world['doc']}", headers=h).status_code == 403
    assert client.get(f"/documents/{world['doc']}/download", headers=h).status_code == 403
    r = client.get("/admin/documents", headers=h)
    assert r.status_code == 200 and r.json()[0]["owner_email"] == "alice@example.com"
    assert "storage_key" not in r.text


def test_admin_with_a_grant_row_still_gets_nothing(client, world, db):
    grant(db, world["doc"], world["adm"], "read", world["alice"])
    assert client.get(f"/documents/{world['doc']}/download", headers=world["h"]["admin"]).status_code == 403


# ---------- granted users ----------
def test_read_grant_allows_read_but_not_write_or_delete(client, world, db):
    grant(db, world["doc"], world["vic"], "read", world["alice"])
    h = world["h"]["vic"]
    assert client.get(f"/documents/{world['doc']}", headers=h).status_code == 200
    d = client.get(f"/documents/{world['doc']}/download", headers=h)
    assert d.status_code == 200 and d.content == PDF
    assert client.patch(f"/documents/{world['doc']}", headers=h, json={"name": "x"}).status_code == 403
    assert client.post(f"/documents/{world['doc']}/versions", headers=h, files={"file": ("x.pdf", PDF)}).status_code == 403
    assert client.delete(f"/documents/{world['doc']}", headers=h).status_code == 403


def test_edit_grant_allows_edit_but_not_delete(client, world, db):
    grant(db, world["doc"], world["bob"], "edit", world["alice"])
    h = world["h"]["bob"]
    assert client.patch(f"/documents/{world['doc']}", headers=h, json={"name": "Renamed"}).status_code == 200
    assert client.post(f"/documents/{world['doc']}/versions", headers=h, files={"file": ("v2.pdf", PDF)}).status_code == 201
    assert client.delete(f"/documents/{world['doc']}", headers=h).status_code == 403


def test_viewer_role_is_capped_at_read_even_with_edit_grant_row(client, world, db):
    grant(db, world["doc"], world["vic"], "edit", world["alice"])
    r = client.patch(f"/documents/{world['doc']}", headers=world["h"]["vic"], json={"name": "x"})
    assert r.status_code == 403


def test_expired_grant_gives_nothing(client, world, db):
    grant(db, world["doc"], world["vic"], "read", world["alice"], expires=now() - timedelta(seconds=1))
    assert client.get(f"/documents/{world['doc']}/download", headers=world["h"]["vic"]).status_code == 404


def test_revoking_a_grant_takes_effect_on_the_very_next_request(client, world, db):
    g = Grant(document_id=world["doc"], user_id=world["vic"].id, permission="read", granted_by=world["alice"].id)
    db.add(g); db.commit()
    h = world["h"]["vic"]
    assert client.get(f"/documents/{world['doc']}/download", headers=h).status_code == 200
    db.delete(g); db.commit()
    assert client.get(f"/documents/{world['doc']}/download", headers=h).status_code == 404
    assert client.get("/documents", headers=h).json()["total"] == 0


def test_owner_demoted_to_viewer_loses_ownership_powers(client, world, db):
    world["alice"].role = "viewer"
    db.commit()
    assert client.delete(f"/documents/{world['doc']}", headers=world["h"]["alice"]).status_code == 404


# ---------- listing / search leak nothing ----------
def test_list_and_search_never_include_other_peoples_documents(client, world, db):
    hb = world["h"]["bob"]
    assert client.get("/documents", headers=hb).json() == {"total": 0, "items": []}
    for params in ({"q": "salary"}, {"owner": "alice"}, {"category": "hr"}, {"q": "sal", "owner": "alice@example.com"}):
        assert client.get("/documents", headers=hb, params=params).json()["total"] == 0, params
    # and the owner does find it by name, owner, category and date
    ha = world["h"]["alice"]
    assert client.get("/documents", headers=ha, params={"q": "SALARY"}).json()["total"] == 1
    assert client.get("/documents", headers=ha, params={"owner": "alice"}).json()["total"] == 1
    assert client.get("/documents", headers=ha, params={"category": "hr"}).json()["total"] == 1
    assert client.get("/documents", headers=ha, params={"created_from": "2000-01-01T00:00:00"}).json()["total"] == 1
    assert client.get("/documents", headers=ha, params={"created_to": "2000-01-01T00:00:00"}).json()["total"] == 0


def test_search_wildcards_are_literal(client, world):
    ha = world["h"]["alice"]
    assert client.get("/documents", headers=ha, params={"q": "%"}).json()["total"] == 0


def test_granted_document_appears_in_viewers_list_with_access_level(client, world, db):
    grant(db, world["doc"], world["vic"], "read", world["alice"])
    items = client.get("/documents", headers=world["h"]["vic"]).json()["items"]
    assert [i["my_access"] for i in items] == ["read"]


def test_admin_cannot_use_the_user_document_list(client, world):
    assert client.get("/documents", headers=world["h"]["admin"]).status_code == 403


# ---------- IDOR on versions, deletion ----------
def test_cannot_download_another_documents_version_through_my_document(client, world):
    ha, hb = world["h"]["alice"], world["h"]["bob"]
    alice_version = client.get(f"/documents/{world['doc']}", headers=ha).json()["versions"][0]["id"]
    bob_doc = upload(client, hb, name="mine.pdf").json()["id"]
    r = client.get(f"/documents/{bob_doc}/download", headers=hb, params={"version": alice_version})
    assert r.status_code == 404


def test_soft_deleted_document_is_unreachable_but_file_is_retained(client, world, db):
    ha = world["h"]["alice"]
    key = db.query(DocumentVersion).one().storage_key
    assert client.delete(f"/documents/{world['doc']}", headers=ha).status_code == 200
    assert client.get(f"/documents/{world['doc']}/download", headers=ha).status_code == 404
    assert client.get("/documents", headers=ha).json()["total"] == 0
    assert storage.path_for(key).exists()
    assert db.query(AuditLog).filter_by(action="document_delete", outcome="allowed").count() == 1


def test_logged_out_token_cannot_download(client, world):
    h = world["h"]["alice"]
    client.post("/auth/logout", headers=h)
    assert client.get(f"/documents/{world['doc']}/download", headers=h).status_code == 401


# ---------- download hardening and storage ----------
def test_download_headers_force_attachment_and_block_sniffing(client, world):
    r = client.get(f"/documents/{world['doc']}/download", headers=world["h"]["alice"])
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-type"].startswith("application/pdf")


def test_stored_filename_is_random_and_user_filename_never_touches_disk(client, make_user, login, db):
    make_user("owner", "alice@example.com")
    h = login("alice@example.com")
    r = upload(client, h, name="../../etc/passwd.pdf")
    assert r.status_code == 201 and r.json()["name"] == "passwd.pdf"
    key = db.query(DocumentVersion).one().storage_key
    assert len(key) == 32 and "passwd" not in key
    p = storage.path_for(key)
    assert storage.root() in p.parents
    for bad in ("../x", "a" * 31, "A" * 32, "../" + "a" * 32):
        with pytest.raises(ValueError):
            storage.path_for(bad)


def test_every_download_is_audited(client, world, db):
    client.get(f"/documents/{world['doc']}/download", headers=world["h"]["alice"])
    row = db.query(AuditLog).filter_by(action="download", outcome="allowed").one()
    assert row.actor_email == "alice@example.com" and row.document_id == world["doc"]


# ---------- upload validation ----------
def office(ext_dir="word/", extra=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<x/>")
        z.writestr(ext_dir + "document.xml", "<x/>")
        for n, c in (extra or {}).items():
            z.writestr(n, c)
    return buf.getvalue()


@pytest.mark.parametrize("name,content", [
    ("evil.exe", b"MZ\x90\x00"),
    ("page.html", b"<script>alert(1)</script>"),
    ("image.svg", b"<svg onload=alert(1)/>"),
    ("noext", PDF),
    ("fake.pdf", b"<html>not a pdf</html>"),
    ("fake.png", PDF),
    ("fake.docx", b"PK\x03\x04 but not really a zip"),
    ("wrong.docx", office("xl/")),
    ("empty.pdf", b""),
    ("bin.txt", b"hello\x00world"),
])
def test_bad_uploads_are_rejected(client, make_user, login, db, name, content):
    make_user("owner", "alice@example.com")
    r = upload(client, login("alice@example.com"), name=name, content=content)
    assert r.status_code == 415, (name, r.text)
    assert db.query(Document).count() == 0
    leftovers = [f for _, _, fs in os.walk(storage.root()) for f in fs]
    assert leftovers == []


def test_valid_office_file_is_accepted(client, make_user, login):
    make_user("owner", "alice@example.com")
    assert upload(client, login("alice@example.com"), name="a.docx", content=office()).status_code == 201


def test_zip_bomb_is_rejected(client, make_user, login):
    make_user("owner", "alice@example.com")
    bomb = office(extra={"word/big.bin": b"\0" * (30 * 1024 * 1024)})
    assert upload(client, login("alice@example.com"), name="b.docx", content=bomb).status_code == 415


def test_oversized_upload_is_rejected_both_early_and_by_bytes_read(client, make_user, login, monkeypatch):
    make_user("owner", "alice@example.com")
    h = login("alice@example.com")
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    mid = PDF + b"A" * int(1.2 * 1024 * 1024)       # passes the early guard, fails the streaming cap
    assert upload(client, h, content=mid).status_code == 413
    huge = PDF + b"A" * (3 * 1024 * 1024)            # rejected by the early Content-Length guard
    assert upload(client, h, content=huge).status_code == 413


def test_viewer_cannot_upload(client, make_user, login):
    make_user("viewer", "vic@example.com")
    assert upload(client, login("vic@example.com")).status_code == 403


def test_invalid_category_rejected(client, make_user, login):
    make_user("owner", "alice@example.com")
    assert upload(client, login("alice@example.com"), category="<script>").status_code == 422
