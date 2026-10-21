"""The administrator's view: filterable audit, per-document timeline, and 'worth noticing' alerts."""
import uuid
from datetime import timedelta

from sqlalchemy import text

from app.models import AuditLog, now
from tests.test_documents import PDF
from tests.test_grants import give, world  # noqa: F401  (fixture)


def rules(client, w, hours=24):
    r = client.get(f"/admin/alerts?hours={hours}", headers=w["h"]["admin"])
    assert r.status_code == 200, r.text
    return {(a["rule"], a["actor_email"]) for a in r.json()["alerts"]}, r.json()["alerts"]


def test_only_admin_can_see_any_activity_view(client, world):
    d = world["doc"]
    urls = ["/admin/audit", "/admin/audit/verify", "/admin/alerts", "/admin/summary",
            "/admin/documents", f"/admin/documents/{d}/timeline"]
    for who in ("alice", "bob", "vic"):
        for u in urls:
            assert client.get(u, headers=world["h"][who]).status_code == 403, (who, u)
    for u in urls:
        assert client.get(u).status_code == 401


def test_audit_filters(client, world):
    w, ha = world, world["h"]["admin"]
    give(client, w, "alice", "vic@example.com")
    client.get(f"/documents/{w['doc']}/download", headers=w["h"]["vic"])
    client.get(f"/documents/{w['doc']}/download", headers=w["h"]["bob"])
    q = lambda **p: client.get("/admin/audit", headers=ha, params=p).json()   # noqa: E731
    assert {r["action"] for r in q(action="download")} == {"download"}
    assert {r["outcome"] for r in q(outcome="denied")} == {"denied"}
    assert all(r["actor_email"] == "bob@example.com" for r in q(actor="BOB", action="download"))
    assert len(q(document_id=w["doc"], action="download", outcome="allowed")) == 1
    assert q(document_id=str(uuid.uuid4())) == []
    assert q(since=(now() + timedelta(hours=1)).isoformat()) == []
    assert len(q(until=(now() + timedelta(hours=1)).isoformat())) > 0
    assert client.get("/admin/audit?outcome=maybe", headers=ha).status_code == 422
    assert q(actor="%") == []                       # wildcard is literal


def test_timeline_answers_who_opened_it_and_when_including_refused(client, world):
    w, ha = world, world["h"]["admin"]
    give(client, w, "alice", "vic@example.com")
    client.get(f"/documents/{w['doc']}/download", headers=w["h"]["vic"])
    client.get(f"/documents/{w['doc']}/download", headers=w["h"]["vic"])
    client.get(f"/documents/{w['doc']}/download", headers=w["h"]["bob"])      # refused
    r = client.get(f"/admin/documents/{w['doc']}/timeline", headers=ha)
    assert r.status_code == 200
    t = r.json()
    assert [x["email"] for x in t["readers"]] == ["vic@example.com"] and t["readers"][0]["reads"] == 2
    assert [(e["action"], e["outcome"], e["actor_email"]) for e in t["events"]] == [
        ("upload", "allowed", "alice@example.com"), ("grant_create", "allowed", "alice@example.com"),
        ("download", "allowed", "vic@example.com"), ("download", "allowed", "vic@example.com"),
        ("download", "denied", "bob@example.com")]
    assert t["current_grants"][0]["email"] == "vic@example.com"
    assert "storage_key" not in r.text and "%PDF" not in r.text          # metadata, never content


def test_timeline_survives_document_deletion_and_rejects_junk_ids(client, world):
    w, ha = world, world["h"]["admin"]
    client.delete(f"/documents/{w['doc']}", headers=w["h"]["alice"])
    t = client.get(f"/admin/documents/{w['doc']}/timeline", headers=ha).json()
    assert t["document"]["deleted"] is True and t["events"][-1]["action"] == "document_delete"
    assert client.get("/admin/documents/not-a-uuid/timeline", headers=ha).status_code == 404
    assert client.get(f"/admin/documents/{uuid.uuid4()}/timeline", headers=ha).status_code == 404


# ---------- alerts ----------
def test_quiet_system_raises_no_alerts(client, world):
    assert rules(client, world)[1] == []


def test_repeated_denials_alert(client, world):
    for _ in range(6):
        client.get(f"/documents/{world['doc']}", headers=world["h"]["bob"])
    found, alerts = rules(client, world)
    assert ("repeated_denials", "bob@example.com") in found
    assert next(a for a in alerts if a["rule"] == "repeated_denials")["count"] == 6


def test_probing_many_documents_alert(client, world):
    for _ in range(3):
        client.get(f"/documents/{uuid.uuid4()}", headers=world["h"]["bob"])
    assert ("document_probing", "bob@example.com") in rules(client, world)[0]


def test_failed_login_alert(client, world):
    for _ in range(5):
        client.post("/auth/login", json={"email": "vic@example.com", "password": "wrong-wrong-1"})
    assert ("login_failures", "vic@example.com") in rules(client, world)[0]


def test_mass_download_alert(client, world):
    give(client, world, "alice", "vic@example.com")
    for _ in range(10):
        client.get(f"/documents/{world['doc']}/download", headers=world["h"]["vic"])
    assert ("mass_download", "vic@example.com") in rules(client, world)[0]


def test_bulk_download_of_many_documents_alert(client, world):
    for i in range(5):
        d = client.post("/documents", headers=world["h"]["alice"],
                        files={"file": (f"f{i}.pdf", PDF)}).json()["id"]
        give_doc = client.post(f"/documents/{d}/grants", headers=world["h"]["alice"],
                               json={"email": "vic@example.com", "permission": "read"})
        assert give_doc.status_code == 201
        client.get(f"/documents/{d}/download", headers=world["h"]["vic"])
    assert ("bulk_download", "vic@example.com") in rules(client, world)[0]


def test_retrying_after_revoke_and_grant_download_revoke_patterns(client, world):
    w = world
    gid = give(client, w, "alice", "vic@example.com").json()["id"]
    client.get(f"/documents/{w['doc']}/download", headers=w["h"]["vic"])
    client.delete(f"/documents/{w['doc']}/grants/{gid}", headers=w["h"]["alice"])
    client.get(f"/documents/{w['doc']}/download", headers=w["h"]["vic"])        # refused retry
    found, alerts = rules(client, w)
    assert ("revoked_access_retry", "vic@example.com") in found
    assert any(a["rule"] == "grant_download_revoke" and a["document_id"] == w["doc"] for a in alerts)


def test_admin_endpoint_probing_alert(client, world):
    for _ in range(3):
        client.get("/admin/users", headers=world["h"]["bob"])
    assert ("admin_probing", "bob@example.com") in rules(client, world)[0]


def test_account_changes_are_reported_as_info(client, world):
    client.patch(f"/admin/users/{world['vic'].id}", json={"is_active": False}, headers=world["h"]["admin"])
    _, alerts = rules(client, world)
    assert any(a["rule"] == "account_change" and a["severity"] == "info" for a in alerts)


def test_tampered_audit_log_is_critical_and_sorted_first(client, world, db):
    for _ in range(6):
        client.get(f"/documents/{world['doc']}", headers=world["h"]["bob"])
    db.execute(text("UPDATE audit_log SET outcome='denied' WHERE id=1"))   # row 1 was a successful login
    db.commit()
    _, alerts = rules(client, world)
    assert alerts[0]["rule"] == "audit_chain_broken" and alerts[0]["severity"] == "critical"
    assert client.get("/admin/audit/verify", headers=world["h"]["admin"]).json()["ok"] is False


def test_alert_window_is_respected(client, world, db):
    for _ in range(6):
        client.get(f"/documents/{world['doc']}", headers=world["h"]["bob"])
    old = now() - timedelta(hours=48)
    db.execute(text("UPDATE audit_log SET ts=:t WHERE outcome='denied'"), {"t": old})
    db.commit()
    assert not any(a["rule"] == "repeated_denials" for a in rules(client, world, hours=24)[1])
    assert any(a["rule"] == "repeated_denials" for a in rules(client, world, hours=72)[1])
    assert client.get("/admin/alerts?hours=0", headers=world["h"]["admin"]).status_code == 422
    assert client.get("/admin/alerts?hours=9999", headers=world["h"]["admin"]).status_code == 422


def test_summary_counts(client, world):
    for _ in range(6):
        client.get(f"/documents/{world['doc']}", headers=world["h"]["bob"])
    s = client.get("/admin/summary", headers=world["h"]["admin"]).json()
    assert s["users_by_role"] == {"admin": 1, "owner": 2, "viewer": 2}
    assert s["documents"] == 1 and s["events"]["denied"] >= 6
    assert s["alerts_by_severity"].get("medium", 0) >= 1
