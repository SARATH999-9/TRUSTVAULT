"""Admin control over what is uploaded and who may see it: review, policy, owner supervision, writing documents."""
import json

import pytest

from app import notify
from app.config import settings
from app.models import AuditLog, DocumentVersion, Grant
from tests.test_documents import PDF


@pytest.fixture(autouse=True)
def approval_on(monkeypatch):
    monkeypatch.setattr(settings, "require_document_approval", True)


@pytest.fixture
def mails(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "send", lambda to, subject, body: sent.append((to, subject, body)))
    return sent


@pytest.fixture
def w(client, make_user, login):
    alice = make_user("owner", "alice@example.com")
    bob = make_user("owner", "bob@example.com")
    vic = make_user("viewer", "vic@example.com")
    adm = make_user("admin", "admin@example.com")
    h = {k: login(f"{k}@example.com") for k in ("alice", "bob", "vic", "admin")}
    return dict(h=h, alice=alice, bob=bob, vic=vic, adm=adm)


def up(client, w, who="alice", name="plan.pdf", content=PDF, **form):
    r = client.post("/documents", headers=w["h"][who], files={"file": (name, content)}, data=form)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def review(client, w, doc, decision, reason=None):
    return client.post(f"/admin/documents/{doc}/review", headers=w["h"]["admin"], json={"decision": decision, "reason": reason})


def share(client, w, doc, email="vic@example.com", who="alice"):
    return client.post(f"/documents/{doc}/grants", headers=w["h"][who], json={"email": email, "permission": "read"})


def vic_can_read(client, w, doc):
    return client.get(f"/documents/{doc}/download", headers=w["h"]["vic"]).status_code == 200


# ---------------- review workflow ----------------
def test_new_uploads_wait_for_review_and_nobody_else_can_reach_them(client, w, db):
    doc = up(client, w)
    assert client.get(f"/documents/{doc}", headers=w["h"]["alice"]).json()["review_status"] == "pending"
    assert client.get(f"/documents/{doc}/download", headers=w["h"]["alice"]).status_code == 200      # owner keeps their own file
    r = share(client, w, doc)
    assert r.status_code == 409 and "approve" in r.json()["detail"]
    db.add(Grant(document_id=doc, user_id=w["vic"].id, permission="read", granted_by=w["alice"].id))   # even a forced grant row
    db.commit()
    assert not vic_can_read(client, w, doc)
    assert client.get(f"/documents/{doc}", headers=w["h"]["vic"]).status_code == 404
    assert client.get("/documents", headers=w["h"]["vic"]).json()["total"] == 0


def test_approval_opens_the_document_and_is_audited_and_emailed(client, w, db, mails):
    doc = up(client, w)
    assert any(to == "admin@example.com" and "waiting for review" in s for to, s, _ in mails)
    assert review(client, w, doc, "approve").json()["review_status"] == "approved"
    assert share(client, w, doc).status_code == 201 and vic_can_read(client, w, doc)
    row = db.query(AuditLog).filter_by(action="document_review").one()
    d = json.loads(row.detail)
    assert row.actor_email == "admin@example.com" and d["from"] == "pending" and d["to"] == "approved"
    assert any(to == "alice@example.com" and "approved" in s for to, s, _ in mails)


def test_rejection_needs_a_reason_blocks_sharing_and_cuts_off_existing_readers_at_once(client, w):
    doc = up(client, w)
    review(client, w, doc, "approve")
    share(client, w, doc)
    assert vic_can_read(client, w, doc)
    assert review(client, w, doc, "reject").status_code == 422
    assert review(client, w, doc, "reject", "Contains personal data").status_code == 200
    assert not vic_can_read(client, w, doc)                                         # immediate
    mine = client.get(f"/documents/{doc}", headers=w["h"]["alice"]).json()
    assert mine["review_status"] == "rejected" and mine["review_reason"] == "Contains personal data"
    assert share(client, w, doc, "vic@example.com").status_code == 409
    assert review(client, w, doc, "approve").status_code == 200 and vic_can_read(client, w, doc)   # reconsidered


def test_a_new_version_voids_the_approval(client, w, db):
    doc = up(client, w)
    review(client, w, doc, "approve")
    share(client, w, doc)
    assert vic_can_read(client, w, doc)
    r = client.post(f"/documents/{doc}/versions", headers=w["h"]["alice"], files={"file": ("v2.pdf", PDF + b"changed")})
    assert r.status_code == 201
    assert client.get(f"/documents/{doc}", headers=w["h"]["alice"]).json()["review_status"] == "pending"
    assert not vic_can_read(client, w, doc)
    assert json.loads(db.query(AuditLog).filter_by(action="version_upload").one().detail)["review_reset_from"] == "approved"
    review(client, w, doc, "approve")
    assert vic_can_read(client, w, doc)


def test_an_editor_grantee_also_cannot_slip_unreviewed_content_past_the_admin(client, w):
    doc = up(client, w)
    review(client, w, doc, "approve")
    client.post(f"/documents/{doc}/grants", headers=w["h"]["alice"], json={"email": "bob@example.com", "permission": "edit"})
    share(client, w, doc)
    client.post(f"/documents/{doc}/versions", headers=w["h"]["bob"], files={"file": ("sneaky.pdf", PDF + b"x")})
    assert not vic_can_read(client, w, doc)


def test_only_admins_review_and_junk_ids_are_404(client, w):
    doc = up(client, w)
    for who in ("alice", "bob", "vic"):
        r = client.post(f"/admin/documents/{doc}/review", headers=w["h"][who], json={"decision": "approve"})
        assert r.status_code == 403
    assert client.get(f"/documents/{doc}", headers=w["h"]["alice"]).json()["review_status"] == "pending"
    assert review(client, w, "not-a-uuid", "approve").status_code == 404
    client.delete(f"/documents/{doc}", headers=w["h"]["alice"])
    assert review(client, w, doc, "approve").status_code == 404


def test_admin_sees_who_uploaded_what_but_never_contents(client, w):
    up(client, w, name="secret-plan.pdf", description="Q4 numbers", category="finance")
    rows = client.get("/admin/documents?review_status=pending", headers=w["h"]["admin"]).json()
    assert len(rows) == 1
    d = rows[0]
    assert d["owner_email"] == "alice@example.com" and d["latest"]["uploaded_by"] == "alice@example.com"
    assert d["latest"]["filename"] == "secret-plan.pdf" and d["latest"]["size_bytes"] == len(PDF) and len(d["latest"]["sha256"]) == 64
    assert d["description"] == "Q4 numbers" and d["category"] == "finance"
    text = json.dumps(rows)
    assert "storage_key" not in text and "%PDF" not in text
    assert client.get("/admin/documents?review_status=approved", headers=w["h"]["admin"]).json() == []


def test_owner_can_filter_their_own_documents_by_review_state(client, w):
    a, b = up(client, w, name="a.pdf"), up(client, w, name="b.pdf")
    review(client, w, a, "approve")
    ids = lambda p: [x["id"] for x in client.get("/documents", headers=w["h"]["alice"], params=p).json()["items"]]  # noqa: E731
    assert ids({"review": "pending"}) == [b] and ids({"review": "approved"}) == [a]


# ---------------- admin supervision of owners ----------------
def test_suspending_an_owner_freezes_sharing_of_their_documents(client, w):
    doc = up(client, w)
    review(client, w, doc, "approve")
    share(client, w, doc)
    assert vic_can_read(client, w, doc)
    client.patch(f"/admin/users/{w['alice'].id}", headers=w["h"]["admin"], json={"status": "suspended", "reason": "investigation"})
    assert not vic_can_read(client, w, doc)
    assert client.get("/documents", headers=w["h"]["alice"]).status_code == 401           # owner is signed out too
    client.patch(f"/admin/users/{w['alice'].id}", headers=w["h"]["admin"], json={"status": "active"})
    assert vic_can_read(client, w, doc)


def test_owner_directory_shows_volume_and_pending_work(client, w):
    a, b = up(client, w, name="a.pdf"), up(client, w, name="b.pdf")
    review(client, w, a, "approve")
    rows = {r["email"]: r for r in client.get("/admin/owners", headers=w["h"]["admin"]).json()}
    assert rows["alice@example.com"]["documents"] == 2 and rows["alice@example.com"]["pending"] == 1 and rows["alice@example.com"]["approved"] == 1
    assert rows["bob@example.com"]["documents"] == 0
    assert client.get("/admin/owners", headers=w["h"]["alice"]).status_code == 403


def test_summary_counts_work_waiting_for_the_admin(client, w):
    up(client, w)
    s = client.get("/admin/summary", headers=w["h"]["admin"]).json()
    assert s["pending_documents"] == 1 and s["pending_users"] == 0


# ---------------- upload policy ----------------
def put_policy(client, w, **over):
    body = {"allowed_types": ["pdf", "txt"], "max_mb": 5, "categories": ["HR", "Legal"], **over}
    return client.put("/admin/policy", headers=w["h"]["admin"], json=body)


def test_policy_defaults_are_visible_to_owners(client, w):
    p = client.get("/policy", headers=w["h"]["alice"]).json()
    assert "pdf" in p["allowed_types"] and p["categories"] == [] and p["require_approval"] is True


def test_admin_controls_which_file_types_categories_and_sizes_may_be_uploaded(client, w, db, monkeypatch):
    assert put_policy(client, w, allowed_types=["pdf"], max_mb=1, categories=["HR", "Legal"]).status_code == 200
    h = w["h"]["alice"]
    assert client.post("/documents", headers=h, files={"file": ("n.txt", b"hello")}, data={"category": "HR"}).status_code == 415   # type not allowed
    assert client.post("/documents", headers=h, files={"file": ("a.pdf", PDF)}, data={"category": "finance"}).status_code == 422
    assert client.post("/documents", headers=h, files={"file": ("a.pdf", PDF)}, data={"category": "hr"}).status_code == 201   # case-insensitive
    big = PDF + b"A" * int(1.2 * 1024 * 1024)
    assert client.post("/documents", headers=h, files={"file": ("big.pdf", big)}, data={"category": "HR"}).status_code == 413
    assert client.post("/documents/compose", headers=h, json={"name": "n", "category": "HR", "content": "x"}).status_code == 415
    row = db.query(AuditLog).filter_by(action="policy_update").one()
    d = json.loads(row.detail)
    assert d["to"]["allowed_types"] == ["pdf"] and d["to"]["max_mb"] == 1 and d["from"]["max_mb"] == settings.max_upload_mb
    assert client.get("/policy", headers=h).json()["categories"] == ["HR", "Legal"]                 # persisted


def test_policy_changes_are_admin_only_and_validated(client, w):
    assert client.put("/admin/policy", headers=w["h"]["alice"], json={"allowed_types": ["pdf"], "max_mb": 1, "categories": []}).status_code == 403
    assert client.get("/admin/policy", headers=w["h"]["vic"]).status_code == 403
    assert put_policy(client, w, allowed_types=["exe"]).status_code == 422
    assert put_policy(client, w, allowed_types=[]).status_code == 422
    assert put_policy(client, w, max_mb=settings.max_upload_mb + 1).status_code == 422
    assert put_policy(client, w, max_mb=0).status_code == 422
    assert put_policy(client, w, categories=["<script>"]).status_code == 422
    assert client.get("/admin/policy", headers=w["h"]["admin"]).json()["all_types"]


def test_category_rule_also_applies_when_renaming(client, w):
    doc = up(client, w, category="general")
    put_policy(client, w, categories=["HR"])
    assert client.patch(f"/documents/{doc}", headers=w["h"]["alice"], json={"category": "finance"}).status_code == 422
    assert client.patch(f"/documents/{doc}", headers=w["h"]["alice"], json={"category": "hr"}).status_code == 200


# ---------------- writing documents in the browser ----------------
def test_owner_can_write_a_document_which_then_follows_the_normal_rules(client, w):
    r = client.post("/documents/compose", headers=w["h"]["alice"],
                    json={"name": "Meeting notes", "category": "general", "description": "weekly", "content": "Line one\nLine two <b>x</b>"})
    assert r.status_code == 201
    d = r.json()
    assert d["review_status"] == "pending" and d["latest_version"]["original_filename"] == "Meeting notes.txt"
    got = client.get(f"/documents/{d['id']}/download", headers=w["h"]["alice"])
    assert got.content == b"Line one\nLine two <b>x</b>" and got.headers["content-disposition"].startswith("attachment")
    assert not vic_can_read(client, w, d["id"])


def test_compose_validation_and_permissions(client, w):
    h = w["h"]["alice"]
    assert client.post("/documents/compose", headers=h, json={"name": "x", "content": ""}).status_code == 422
    assert client.post("/documents/compose", headers=h, json={"name": "", "content": "x"}).status_code == 422
    assert client.post("/documents/compose", headers=h, json={"name": "x", "content": "y" * 200_001}).status_code == 422
    assert client.post("/documents/compose", headers=w["h"]["vic"], json={"name": "x", "content": "y"}).status_code == 403
    assert client.post("/documents/compose", headers=w["h"]["admin"], json={"name": "x", "content": "y"}).status_code == 403
    assert client.post("/documents/compose", json={"name": "x", "content": "y"}).status_code == 401
    r = client.post("/documents/compose", headers=h, json={"name": "../../etc/passwd", "content": "y"})
    assert r.status_code == 201 and r.json()["latest_version"]["original_filename"] == "passwd.txt"


def test_text_documents_can_be_edited_as_new_versions(client, w, db):
    doc = client.post("/documents/compose", headers=w["h"]["alice"], json={"name": "Notes", "content": "v1 text"}).json()["id"]
    review(client, w, doc, "approve")
    share(client, w, doc)
    assert client.post(f"/documents/{doc}/versions/text", headers=w["h"]["vic"], json={"content": "hax"}).status_code == 403
    r = client.post(f"/documents/{doc}/versions/text", headers=w["h"]["alice"], json={"content": "v2 text"})
    assert r.status_code == 201 and r.json()["version_no"] == 2
    assert client.get(f"/documents/{doc}/download", headers=w["h"]["alice"]).content == b"v2 text"
    assert db.query(DocumentVersion).filter_by(document_id=doc).count() == 2                 # history kept
    assert not vic_can_read(client, w, doc)                                                   # re-review required
    pdf = up(client, w, name="a.pdf")
    assert client.post(f"/documents/{pdf}/versions/text", headers=w["h"]["alice"], json={"content": "x"}).status_code == 415
    assert client.post(f"/documents/{doc}/versions/text", headers=w["h"]["bob"], json={"content": "x"}).status_code == 404
