"""Real accounts: sign-up, admin approval, portals, Google sign-in, first-admin bootstrap, abuse limits."""
import json

import pytest

from app import bootstrap, google_auth, notify
from app.config import settings
from app.models import AuditLog, Session, User
from tests.conftest import PASSWORD

NEW = {"name": "Vera Viewer", "email": "vera@example.com", "password": "a-long-password-1", "role": "viewer"}


@pytest.fixture
def mails(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "send", lambda to, subject, body: sent.append((to, subject, body)))
    return sent


def register(client, **over):
    r = client.post("/auth/register", json={**NEW, **over})
    client.cookies.clear()                       # keep users separate; we use Bearer headers
    return r


def bearer(r):
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def admin(client, make_user, login):
    make_user("admin", "admin@example.com")
    return login("admin@example.com")


# ---------------- sign-up and the waiting room ----------------
def test_new_account_starts_pending_and_can_only_see_its_own_status(client, db):
    r = register(client)
    assert r.status_code == 201
    u = r.json()["user"]
    assert u["status"] == "pending" and u["role"] == "viewer" and u["email_verified"] is False
    h = bearer(r)
    assert client.get("/auth/me", headers=h).json()["status"] == "pending"
    for path in ("/documents", "/policy", "/admin/users", "/admin/audit"):
        r2 = client.get(path, headers=h)
        assert r2.status_code == 403 and "waiting for admin approval" in r2.json()["detail"], path
    assert client.post("/auth/logout", headers=h).status_code == 200


def test_pending_account_cannot_do_anything_else(client, make_user, login):
    make_user("owner", "o@example.com")
    owner = login("o@example.com")
    h = bearer(register(client, role="owner", email="pend-owner@example.com"))
    assert client.post("/documents", headers=h, files={"file": ("a.pdf", b"%PDF-1.4\n")}).status_code == 403
    assert client.post("/documents/compose", headers=h, json={"name": "x", "content": "y"}).status_code == 403
    assert client.post("/auth/change-password", headers=h, json={"current_password": "x", "new_password": "y" * 12}).status_code == 403
    d = client.post("/documents", headers=owner, files={"file": ("a.pdf", b"%PDF-1.4\n")}).json()["id"]
    assert client.get(f"/documents/{d}", headers=h).status_code == 403


def test_nobody_can_self_register_as_admin_and_input_is_validated(client):
    assert register(client, role="admin").status_code == 422
    assert register(client, password="short").status_code == 422
    assert register(client, password="vera@example.com").status_code == 422
    assert register(client, email="not-an-email").status_code == 422
    assert register(client, name="x").status_code == 422
    assert register(client, name="  Vera   V  ").json()["user"]["name"] == "Vera V"


def test_duplicate_email_is_refused_case_insensitively(client):
    assert register(client).status_code == 201
    assert register(client, email="VERA@Example.com").status_code == 409


def test_registration_is_audited_and_admins_are_emailed(client, admin, mails, db):
    register(client)
    assert any(a.action == "register" and a.outcome == "allowed" for a in db.query(AuditLog))
    assert any(to == "admin@example.com" and "waiting for approval" in subj for to, subj, _ in mails)


# ---------------- admin approval ----------------
def test_admin_sees_pending_details_others_cannot(client, admin, make_user, login):
    register(client)
    rows = client.get("/admin/users?status=pending", headers=admin).json()
    assert [r["email"] for r in rows] == ["vera@example.com"]
    assert rows[0]["email_verified"] is False and rows[0]["registered_ip"] and rows[0]["role"] == "viewer"
    make_user("owner", "o@example.com")
    assert client.get("/admin/users?status=pending", headers=login("o@example.com")).status_code == 403


def test_approval_takes_effect_immediately_on_the_same_session(client, admin, mails):
    r = register(client)
    h = bearer(r)
    uid = r.json()["user"]["id"]
    assert client.get("/documents", headers=h).status_code == 403
    assert client.patch(f"/admin/users/{uid}", headers=admin, json={"status": "active"}).status_code == 200
    assert client.get("/documents", headers=h).status_code == 200
    assert client.get("/auth/me", headers=h).json()["status"] == "active"
    assert any(to == "vera@example.com" and "approved" in subj for to, subj, _ in mails)


def test_admin_can_change_the_role_while_approving(client, admin):
    r = register(client, role="owner")
    uid = r.json()["user"]["id"]
    out = client.patch(f"/admin/users/{uid}", headers=admin, json={"status": "active", "role": "viewer"}).json()
    assert out["role"] == "viewer" and out["status"] == "active"
    assert client.post("/documents", headers=bearer(r), files={"file": ("a.pdf", b"%PDF-1.4\n")}).status_code == 403


def test_rejection_blocks_login_with_the_reason_and_kills_the_session(client, admin, mails):
    r = register(client)
    uid = r.json()["user"]["id"]
    client.patch(f"/admin/users/{uid}", headers=admin, json={"status": "rejected", "reason": "Not a known customer"})
    assert client.get("/auth/me", headers=bearer(r)).status_code == 401
    login_try = client.post("/auth/login", json={"email": "vera@example.com", "password": NEW["password"]})
    assert login_try.status_code == 403 and "Not a known customer" in login_try.json()["detail"]
    wrong = client.post("/auth/login", json={"email": "vera@example.com", "password": "wrong-password-1"})
    assert wrong.status_code == 401 and "declined" not in wrong.text          # no status leak without the password
    assert register(client).status_code == 409
    assert any("declined" in subj for _, subj, _ in mails)


def test_suspend_and_reactivate(client, admin):
    r = register(client)
    uid = r.json()["user"]["id"]
    client.patch(f"/admin/users/{uid}", headers=admin, json={"status": "active"})
    h = bearer(client.post("/auth/login", json={"email": "vera@example.com", "password": NEW["password"]}))
    client.cookies.clear()
    assert client.get("/documents", headers=h).status_code == 200
    client.patch(f"/admin/users/{uid}", headers=admin, json={"status": "suspended", "reason": "policy"})
    assert client.get("/documents", headers=h).status_code == 401
    assert client.post("/auth/login", json={"email": "vera@example.com", "password": NEW["password"]}).status_code == 403
    client.patch(f"/admin/users/{uid}", headers=admin, json={"status": "active"})
    assert client.post("/auth/login", json={"email": "vera@example.com", "password": NEW["password"]}).status_code == 200


def test_impossible_status_moves_are_refused(client, admin):
    uid = register(client).json()["user"]["id"]
    assert client.patch(f"/admin/users/{uid}", headers=admin, json={"status": "suspended"}).status_code == 409
    assert client.patch(f"/admin/users/{uid}", headers=admin, json={"status": "pending"}).status_code == 422


def test_decisions_are_audited_with_who_and_why(client, admin, db):
    uid = register(client).json()["user"]["id"]
    client.patch(f"/admin/users/{uid}", headers=admin, json={"status": "rejected", "reason": "duplicate request"})
    row = db.query(AuditLog).filter_by(action="user_update", target_user_id=uid).one()
    d = json.loads(row.detail)
    assert row.actor_email == "admin@example.com" and d["status"] == ["pending", "rejected"] and d["reason"] == "duplicate request"


def test_pending_users_cannot_be_given_access_to_documents(client, admin, make_user, login):
    make_user("owner", "o@example.com")
    ho = login("o@example.com")
    doc = client.post("/documents", headers=ho, files={"file": ("a.pdf", b"%PDF-1.4\n")}).json()["id"]
    register(client)
    r = client.post(f"/documents/{doc}/grants", headers=ho, json={"email": "vera@example.com", "permission": "read"})
    assert r.status_code == 422


def test_admin_created_users_are_active_immediately(client, admin):
    r = client.post("/admin/users", headers=admin, json={"email": "n@example.com", "name": "N", "password": "a-long-password-1", "role": "owner"})
    assert r.status_code == 201 and r.json()["status"] == "active"


# ---------------- portals ----------------
def test_portal_must_match_the_account_role(client, make_user):
    make_user("viewer", "v@example.com")
    ok = client.post("/auth/login", json={"email": "v@example.com", "password": PASSWORD, "portal": "viewer"})
    assert ok.status_code == 200
    client.cookies.clear()
    wrong = client.post("/auth/login", json={"email": "v@example.com", "password": PASSWORD, "portal": "admin"})
    assert wrong.status_code == 403 and "Viewer portal" in wrong.json()["detail"]
    bad_pw = client.post("/auth/login", json={"email": "v@example.com", "password": "nope-nope-nope", "portal": "admin"})
    assert bad_pw.status_code == 401                                 # no role leak without the password


# ---------------- Google ----------------
GOOGLE = {"sub": "google-sub-1", "email": "gina@gmail.com", "name": "Gina G"}


@pytest.fixture
def google(monkeypatch):
    state = {"info": dict(GOOGLE)}

    def fake(credential):
        if credential.startswith("BAD"):
            raise google_auth.GoogleAuthError("Google could not verify this sign-in")
        return dict(state["info"])
    monkeypatch.setattr(google_auth, "verify_google_token", fake)
    return state


def gsign(client, portal="viewer", credential="x" * 30):
    r = client.post("/auth/google", json={"credential": credential, "portal": portal})
    client.cookies.clear()
    return r


def test_google_signup_creates_a_verified_but_pending_account(client, google, mails, admin):
    r = gsign(client)
    assert r.status_code == 200
    u = r.json()["user"]
    assert (u["status"], u["role"], u["email_verified"], u["auth_provider"]) == ("pending", "viewer", True, "google")
    assert client.get("/documents", headers=bearer(r)).status_code == 403
    again = gsign(client)
    assert again.json()["user"]["id"] == u["id"]                      # same account, not a duplicate
    assert any("waiting for approval" in s for _, s, _ in mails)


def test_google_account_needs_the_same_admin_approval(client, google, admin):
    r = gsign(client, portal="owner")
    uid = r.json()["user"]["id"]
    client.patch(f"/admin/users/{uid}", headers=admin, json={"status": "active"})
    assert client.get("/documents", headers=bearer(r)).status_code == 200


def test_google_cannot_create_administrators_unless_allow_listed(client, google, monkeypatch, db):
    r = gsign(client, portal="admin")
    assert r.status_code == 403 and db.query(User).count() == 0
    monkeypatch.setattr(settings, "admin_emails", "gina@gmail.com")
    ok = gsign(client, portal="admin")
    assert ok.status_code == 200 and ok.json()["user"]["role"] == "admin" and ok.json()["user"]["status"] == "active"


def test_google_takes_over_an_unverified_password_account_with_the_same_email(client, google, db):
    r = register(client, email="gina@gmail.com", name="Fake Gina")                # attacker pre-registers the victim's email
    attacker = bearer(r)
    g = gsign(client)
    assert g.status_code == 200 and g.json()["user"]["id"] == r.json()["user"]["id"]
    assert g.json()["user"]["email_verified"] is True and g.json()["user"]["auth_provider"] == "google"
    assert client.get("/auth/me", headers=attacker).status_code == 401           # attacker's session is dead
    assert client.post("/auth/login", json={"email": "gina@gmail.com", "password": NEW["password"]}).status_code == 401
    assert db.query(AuditLog).filter_by(action="google_link").count() == 1


def test_bad_google_token_is_refused_and_audited(client, google, db):
    r = gsign(client, credential="BAD" + "x" * 30)
    assert r.status_code == 401 and db.query(User).count() == 0
    assert db.query(AuditLog).filter_by(action="google_login", outcome="denied").count() == 1


def test_google_respects_rejection_and_portal(client, google, admin):
    r = gsign(client, portal="viewer")
    uid = r.json()["user"]["id"]
    assert gsign(client, portal="owner").status_code == 403                      # wrong portal for this account
    client.patch(f"/admin/users/{uid}", headers=admin, json={"status": "rejected", "reason": "no"})
    assert gsign(client, portal="viewer").status_code == 403


def test_google_accounts_have_no_password_to_change_or_use(client, google, admin):
    r = gsign(client)
    uid = r.json()["user"]["id"]
    client.patch(f"/admin/users/{uid}", headers=admin, json={"status": "active"})
    h = bearer(r)
    assert client.post("/auth/change-password", headers=h, json={"current_password": "anything-123", "new_password": "another-long-pass"}).status_code == 400
    assert client.post("/auth/login", json={"email": "gina@gmail.com", "password": "anything-123"}).status_code == 401


def test_real_verifier_checks_audience_issuer_and_email_verified(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "cid.apps.googleusercontent.com")
    good = {"iss": "https://accounts.google.com", "sub": "1", "email": "A@B.com", "email_verified": True, "name": "A"}
    seen = {}

    def fake_verify(token, request, audience):
        seen["aud"] = audience
        return dict(seen.get("payload", good))
    monkeypatch.setattr(google_auth.id_token, "verify_oauth2_token", fake_verify)
    assert google_auth.verify_google_token("t")["email"] == "a@b.com" and seen["aud"] == "cid.apps.googleusercontent.com"
    for bad in ({**good, "iss": "https://evil.example"}, {**good, "email_verified": False}, {**good, "email": ""}):
        seen["payload"] = bad
        with pytest.raises(google_auth.GoogleAuthError):
            google_auth.verify_google_token("t")
    monkeypatch.setattr(google_auth.id_token, "verify_oauth2_token", lambda *a, **k: (_ for _ in ()).throw(ValueError("expired")))
    with pytest.raises(google_auth.GoogleAuthError):
        google_auth.verify_google_token("t")
    monkeypatch.setattr(settings, "google_client_id", "")
    with pytest.raises(google_auth.GoogleAuthError):
        google_auth.verify_google_token("t")


def test_public_config_exposes_only_the_public_client_id(client, monkeypatch):
    assert client.get("/auth/config").json()["google_client_id"] is None
    monkeypatch.setattr(settings, "google_client_id", "cid.apps.googleusercontent.com")
    c = client.get("/auth/config").json()
    assert c["google_client_id"] == "cid.apps.googleusercontent.com" and c["self_registration_roles"] == ["owner", "viewer"]
    assert "secret" not in json.dumps(c).lower()


# ---------------- first administrator ----------------
def test_first_admin_is_created_from_the_environment_once(client, db, monkeypatch):
    monkeypatch.setattr(settings, "admin_email", "Boss@Example.com")
    monkeypatch.setattr(settings, "admin_password", "a-very-strong-password")
    u = bootstrap.ensure_admin(db)
    assert u.role == "admin" and u.status == "active" and u.email == "boss@example.com"
    assert bootstrap.ensure_admin(db) is None and db.query(User).count() == 1
    r = client.post("/auth/login", json={"email": "boss@example.com", "password": "a-very-strong-password", "portal": "admin"})
    assert r.status_code == 200


def test_bootstrap_refuses_weak_or_half_configured_credentials(db, monkeypatch):
    monkeypatch.setattr(settings, "admin_email", "boss@example.com")
    monkeypatch.setattr(settings, "admin_password", "short")
    with pytest.raises(RuntimeError):
        bootstrap.ensure_admin(db)
    monkeypatch.setattr(settings, "admin_email", "")
    monkeypatch.setattr(settings, "admin_password", "a-very-strong-password")
    with pytest.raises(RuntimeError):
        bootstrap.ensure_admin(db)
    monkeypatch.setattr(settings, "admin_password", "")
    assert bootstrap.ensure_admin(db) is None


def test_placeholder_admin_credentials_from_the_example_file_are_refused(db, monkeypatch):
    monkeypatch.setattr(settings, "admin_email", "you@example.com")
    monkeypatch.setattr(settings, "admin_password", "choose-a-strong-password-here")
    with pytest.raises(RuntimeError, match="placeholder"):
        bootstrap.ensure_admin(db)
    monkeypatch.setattr(settings, "admin_email", "real.person@company.com")          # real email, example password
    with pytest.raises(RuntimeError, match="placeholder"):
        bootstrap.ensure_admin(db)
    assert db.query(User).count() == 0


# ---------------- abuse limits and alerts ----------------
def test_registration_and_login_are_rate_limited_per_address(client, make_user, monkeypatch):
    monkeypatch.setattr(settings, "register_per_hour", 2)
    codes = [register(client, email=f"u{i}@example.com").status_code for i in range(3)]
    assert codes == [201, 201, 429]
    monkeypatch.setattr(settings, "login_per_5min", 3)
    make_user("viewer", "v@example.com")
    codes = [client.post("/auth/login", json={"email": "v@example.com", "password": "wrong-wrong-1"}).status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]


def test_signup_burst_raises_an_alert(client, admin):
    for i in range(5):
        register(client, email=f"bot{i}@example.com")
    alerts = client.get("/admin/alerts", headers=admin).json()["alerts"]
    assert any(a["rule"] == "signup_burst" and a["severity"] == "high" for a in alerts)


def test_session_rows_never_store_raw_tokens_after_register(client, db):
    r = register(client)
    assert all(s.token_hash != r.json()["token"] for s in db.query(Session).all())
