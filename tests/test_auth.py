from app.audit import verify_chain
from app.models import AuditLog, Session, User, now
from datetime import timedelta
from sqlalchemy import text

from tests.conftest import PASSWORD


def test_unauthenticated_is_rejected(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/admin/users").status_code == 401


def test_login_success_and_me(client, make_user, login):
    make_user("viewer", "v@example.com")
    h = login("v@example.com")
    r = client.get("/auth/me", headers=h)
    assert r.status_code == 200 and r.json()["email"] == "v@example.com"
    assert "password_hash" not in r.text and "$argon2" not in r.text


def test_wrong_password_and_unknown_user_look_identical(client, make_user):
    make_user("viewer", "v@example.com")
    a = client.post("/auth/login", json={"email": "v@example.com", "password": "nope-nope-nope"})
    b = client.post("/auth/login", json={"email": "ghost@example.com", "password": "nope-nope-nope"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_lockout_blocks_even_the_correct_password(client, make_user):
    make_user("viewer", "v@example.com")
    for _ in range(5):
        client.post("/auth/login", json={"email": "v@example.com", "password": "wrong-wrong-1"})
    r = client.post("/auth/login", json={"email": "v@example.com", "password": PASSWORD})
    assert r.status_code == 401


def test_passwords_and_tokens_are_not_stored_in_plaintext(client, make_user, db):
    make_user("viewer", "v@example.com")
    r = client.post("/auth/login", json={"email": "v@example.com", "password": PASSWORD})
    token = r.json()["token"]
    assert db.query(User).one().password_hash.startswith("$argon2")
    assert all(s.token_hash != token for s in db.query(Session).all())


def test_logout_kills_token_immediately(client, make_user, login):
    make_user("viewer", "v@example.com")
    h = login("v@example.com")
    assert client.post("/auth/logout", headers=h).status_code == 200
    assert client.get("/auth/me", headers=h).status_code == 401


def test_expired_session_rejected(client, make_user, login, db):
    make_user("viewer", "v@example.com")
    h = login("v@example.com")
    s = db.query(Session).one()
    s.expires_at = now() - timedelta(seconds=1)
    db.commit()
    assert client.get("/auth/me", headers=h).status_code == 401


def test_deactivating_user_kills_existing_session_immediately(client, make_user, login):
    make_user("admin", "a@example.com")
    v = make_user("viewer", "v@example.com")
    ha, hv = login("a@example.com"), login("v@example.com")
    assert client.get("/auth/me", headers=hv).status_code == 200
    assert client.patch(f"/admin/users/{v.id}", json={"is_active": False}, headers=ha).status_code == 200
    assert client.get("/auth/me", headers=hv).status_code == 401
    r = client.post("/auth/login", json={"email": "v@example.com", "password": PASSWORD})
    assert r.status_code == 403 and "suspended" in r.json()["detail"]     # right password: told why


def test_password_change_revokes_other_sessions(client, make_user):
    make_user("viewer", "v@example.com")
    t1 = client.post("/auth/login", json={"email": "v@example.com", "password": PASSWORD}).json()["token"]
    client.cookies.clear()  # stale cookie without an Origin header would (correctly) trip the CSRF check
    t2 = client.post("/auth/login", json={"email": "v@example.com", "password": PASSWORD}).json()["token"]
    client.cookies.clear()
    h1, h2 = {"Authorization": f"Bearer {t1}"}, {"Authorization": f"Bearer {t2}"}
    r = client.post("/auth/change-password", headers=h1,
                    json={"current_password": PASSWORD, "new_password": "another-long-password"})
    assert r.status_code == 200
    assert client.get("/auth/me", headers=h1).status_code == 200
    assert client.get("/auth/me", headers=h2).status_code == 401


def test_roles_are_enforced_on_admin_routes(client, make_user, login):
    make_user("owner", "o@example.com")
    make_user("viewer", "v@example.com")
    for email in ("o@example.com", "v@example.com"):
        h = login(email)
        assert client.get("/admin/users", headers=h).status_code == 403
        assert client.get("/admin/audit", headers=h).status_code == 403
        r = client.post("/admin/users", headers=h, json={
            "email": "x@example.com", "name": "X", "password": "long-enough-pass", "role": "admin"})
        assert r.status_code == 403


def test_admin_cannot_demote_or_deactivate_self(client, make_user, login):
    a = make_user("admin", "a@example.com")
    h = login("a@example.com")
    assert client.patch(f"/admin/users/{a.id}", json={"role": "viewer"}, headers=h).status_code == 400
    assert client.patch(f"/admin/users/{a.id}", json={"is_active": False}, headers=h).status_code == 400


def test_cookie_is_httponly_and_samesite_strict(client, make_user):
    make_user("viewer", "v@example.com")
    r = client.post("/auth/login", json={"email": "v@example.com", "password": PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_csrf_cross_origin_cookie_request_is_blocked(client, make_user):
    make_user("viewer", "v@example.com")
    client.post("/auth/login", json={"email": "v@example.com", "password": PASSWORD})  # cookie now in jar
    bad = client.post("/auth/logout", headers={"Origin": "http://evil.example"})
    assert bad.status_code == 403
    assert client.get("/auth/me").status_code == 200          # session survived the attack
    noorigin = client.post("/auth/logout")
    assert noorigin.status_code == 403
    good = client.post("/auth/logout", headers={"Origin": "http://testserver"})
    assert good.status_code == 200


# ---- audit trail ----
def test_failed_login_and_role_denial_are_audited(client, make_user, login, db):
    make_user("viewer", "v@example.com")
    client.post("/auth/login", json={"email": "v@example.com", "password": "wrong-wrong-1"})
    h = login("v@example.com")
    client.get("/admin/users", headers=h)
    rows = db.query(AuditLog).order_by(AuditLog.id).all()
    assert [(r.action, r.outcome) for r in rows] == [
        ("login", "denied"), ("login", "allowed"), ("role_denied", "denied")]


def test_audit_chain_verifies_and_detects_tampering(client, make_user, login, db):
    make_user("viewer", "v@example.com")
    client.post("/auth/login", json={"email": "v@example.com", "password": "wrong-wrong-1"})
    login("v@example.com")
    assert verify_chain(db)["ok"] is True
    # Simulate an attacker with raw DB access rewriting history (Postgres triggers would block this).
    db.execute(text("UPDATE audit_log SET outcome='allowed' WHERE id=1"))
    db.commit()
    result = verify_chain(db)
    assert result["ok"] is False and result["first_bad_id"] == 1


def test_audit_deletion_in_the_middle_is_detected(client, make_user, login, db):
    make_user("viewer", "v@example.com")
    for _ in range(3):
        client.post("/auth/login", json={"email": "v@example.com", "password": "wrong-wrong-1"})
    db.execute(text("DELETE FROM audit_log WHERE id=2"))
    db.commit()
    assert verify_chain(db)["ok"] is False
