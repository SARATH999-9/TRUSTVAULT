"""Owners can grant and take back access; nobody else can, and revocation bites immediately."""
import json
from datetime import timedelta

import pytest

from app.models import AuditLog, Grant, now
from tests.test_documents import PDF, all_routes, upload


def iso(delta):
    return (now() + delta).isoformat()


@pytest.fixture
def world(client, make_user, login):
    alice = make_user("owner", "alice@example.com")
    bob = make_user("owner", "bob@example.com")
    vic = make_user("viewer", "vic@example.com")
    adm = make_user("admin", "admin@example.com")
    carl = make_user("viewer", "carl@example.com")
    h = {k: login(f"{k}@example.com") for k in ("alice", "bob", "vic", "admin", "carl")}
    doc = upload(client, h["alice"]).json()["id"]
    return dict(alice=alice, bob=bob, vic=vic, adm=adm, carl=carl, h=h, doc=doc)


def give(client, w, who, email, perm="read", **extra):
    return client.post(f"/documents/{w['doc']}/grants", headers=w["h"][who],
                       json={"email": email, "permission": perm, **extra})


def test_owner_grant_gives_access(client, world):
    w = world
    assert client.get(f"/documents/{w['doc']}/download", headers=w["h"]["vic"]).status_code == 404
    r = give(client, w, "alice", "vic@example.com")
    assert r.status_code == 201 and r.json()["permission"] == "read"
    assert client.get(f"/documents/{w['doc']}/download", headers=w["h"]["vic"]).status_code == 200


def test_stranger_cannot_grant_anything_including_to_themselves(client, world, db):
    w = world
    r = give(client, w, "bob", "bob@example.com", "edit")
    assert r.status_code == 404
    assert give(client, w, "vic", "vic@example.com").status_code == 404
    assert db.query(Grant).count() == 0
    assert client.get(f"/documents/{w['doc']}/download", headers=w["h"]["bob"]).status_code == 404


def test_read_or_edit_grantee_cannot_hand_out_access(client, world, db):
    w = world
    give(client, w, "alice", "vic@example.com", "read")
    give(client, w, "alice", "bob@example.com", "edit")
    for who in ("vic", "bob"):
        assert give(client, w, who, "carl@example.com").status_code == 403
        assert client.get(f"/documents/{w['doc']}/grants", headers=w["h"][who]).status_code == 403
    assert db.query(Grant).count() == 2          # nothing new appeared
    assert client.get(f"/documents/{w['doc']}", headers=w["h"]["carl"]).status_code == 404


def test_grantee_cannot_revoke_or_downgrade_others(client, world, db):
    w = world
    give(client, w, "alice", "vic@example.com", "read")
    gid = give(client, w, "alice", "bob@example.com", "edit").json()["id"]
    r = client.delete(f"/documents/{w['doc']}/grants/{gid}", headers=w["h"]["vic"])
    assert r.status_code == 403 and db.query(Grant).count() == 2


def test_viewers_cannot_be_given_edit(client, world):
    w = world
    assert give(client, w, "alice", "vic@example.com", "edit").status_code == 422
    give(client, w, "alice", "vic@example.com", "read")
    assert give(client, w, "alice", "vic@example.com", "edit").status_code == 422  # also on update


def test_cannot_grant_to_admin_unknown_inactive_or_self_and_responses_match(client, world, db):
    w = world
    w["carl"].is_active = False
    db.commit()
    resps = [give(client, w, "alice", e) for e in
             ("admin@example.com", "nobody@example.com", "carl@example.com", "alice@example.com")]
    assert {r.status_code for r in resps} == {422}
    assert len({json.dumps(r.json()) for r in resps}) == 1       # indistinguishable
    assert db.query(Grant).count() == 0


def test_update_changes_level_and_is_audited_with_before_and_after(client, world, db):
    w = world
    give(client, w, "alice", "bob@example.com", "read")
    assert client.patch(f"/documents/{w['doc']}", headers=w["h"]["bob"], json={"name": "x"}).status_code == 403
    assert give(client, w, "alice", "bob@example.com", "edit").status_code == 201
    assert client.patch(f"/documents/{w['doc']}", headers=w["h"]["bob"], json={"name": "x"}).status_code == 200
    assert db.query(Grant).count() == 1
    row = db.query(AuditLog).filter_by(action="grant_update").one()
    d = json.loads(row.detail)
    assert d["from"]["permission"] == "read" and d["to"]["permission"] == "edit"
    assert row.actor_email == "alice@example.com" and row.target_user_id == w["bob"].id


def test_revoke_is_immediate_on_every_route(client, world, db):
    w = world
    gid = give(client, w, "alice", "bob@example.com", "edit").json()["id"]
    hb = w["h"]["bob"]
    assert client.get(f"/documents/{w['doc']}/download", headers=hb).status_code == 200
    assert client.delete(f"/documents/{w['doc']}/grants/{gid}", headers=w["h"]["alice"]).status_code == 200
    res = all_routes(client, w["doc"], hb)
    assert {k: r.status_code for k, r in res.items()} == {k: 404 for k in res}
    assert client.get("/documents", headers=hb).json()["total"] == 0
    assert client.get("/documents", headers=hb, params={"q": "salary"}).json()["total"] == 0
    row = db.query(AuditLog).filter_by(action="grant_revoke").one()
    assert row.outcome == "allowed" and row.target_user_id == w["bob"].id


def test_regrant_after_revoke_creates_a_fresh_grant(client, world):
    w = world
    g1 = give(client, w, "alice", "vic@example.com").json()["id"]
    client.delete(f"/documents/{w['doc']}/grants/{g1}", headers=w["h"]["alice"])
    g2 = give(client, w, "alice", "vic@example.com").json()["id"]
    assert g1 != g2
    assert client.delete(f"/documents/{w['doc']}/grants/{g1}", headers=w["h"]["alice"]).status_code == 404


def test_revoke_cannot_target_a_grant_on_someone_elses_document(client, world, db):
    w = world
    bob_doc = upload(client, w["h"]["bob"], name="bobs.pdf").json()["id"]
    gid = client.post(f"/documents/{bob_doc}/grants", headers=w["h"]["bob"],
                      json={"email": "vic@example.com", "permission": "read"}).json()["id"]
    # alice owns her own doc, so she passes authorize() there, but must not reach bob's grant row
    r = client.delete(f"/documents/{w['doc']}/grants/{gid}", headers=w["h"]["alice"])
    assert r.status_code == 404
    assert db.get(Grant, gid) is not None
    assert client.get(f"/documents/{bob_doc}", headers=w["h"]["vic"]).status_code == 200


def test_only_owner_sees_the_grant_list(client, world):
    w = world
    give(client, w, "alice", "vic@example.com")
    assert len(client.get(f"/documents/{w['doc']}/grants", headers=w["h"]["alice"]).json()) == 1
    assert client.get(f"/documents/{w['doc']}/grants", headers=w["h"]["bob"]).status_code == 404
    assert client.get(f"/documents/{w['doc']}/grants", headers=w["h"]["admin"]).status_code == 403


def test_expiry_rules(client, world, db):
    w = world
    assert give(client, w, "alice", "vic@example.com", expires_at=iso(-timedelta(hours=1))).status_code == 422
    assert give(client, w, "alice", "vic@example.com", expires_at=iso(timedelta(days=400))).status_code == 422
    assert db.query(Grant).count() == 0
    assert give(client, w, "alice", "vic@example.com", expires_at=iso(timedelta(days=1))).status_code == 201
    g = db.query(Grant).one()
    g.expires_at = now() - timedelta(seconds=1)       # time passes
    db.commit()
    assert client.get(f"/documents/{w['doc']}/download", headers=w["h"]["vic"]).status_code == 404


def test_deleted_document_has_no_grant_endpoints(client, world):
    w = world
    client.delete(f"/documents/{w['doc']}", headers=w["h"]["alice"])
    assert give(client, w, "alice", "vic@example.com").status_code == 404
    assert client.get(f"/documents/{w['doc']}/grants", headers=w["h"]["alice"]).status_code == 404


def test_anonymous_cannot_touch_grants(client, world):
    d = world["doc"]
    assert client.post(f"/documents/{d}/grants", json={"email": "a@b.co", "permission": "read"}).status_code == 401
    assert client.get(f"/documents/{d}/grants").status_code == 401


def test_permission_changes_are_visible_to_admin_and_refusals_are_logged(client, world, db):
    w = world
    give(client, w, "alice", "vic@example.com")
    give(client, w, "bob", "bob@example.com", "edit")          # refused
    log = client.get("/admin/audit?limit=100", headers=w["h"]["admin"]).json()
    pairs = {(r["action"], r["outcome"]) for r in log}
    assert ("grant_create", "allowed") in pairs and ("grant_change", "denied") in pairs
