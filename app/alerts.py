"""'Worth noticing' rules for the admin. Each rule is a plain function of the audit rows in a time window,
so it can be read, tested and explained. These are heuristics: they point a human at something,
they never block anyone or change access by themselves."""
import json
from collections import defaultdict
from datetime import timedelta

from sqlalchemy.orm import Session as DBSession

from . import audit
from .models import AuditLog, now
from .security import aware

# Thresholds (per window). Deliberately simple and documented in THREATS.md.
DENIALS_MEDIUM, DENIALS_HIGH = 5, 10
PROBE_DISTINCT_DOCS = 3
LOGIN_FAIL_EMAIL, LOGIN_FAIL_IP = 5, 10
MASS_DOWNLOADS, BULK_DISTINCT_DOCS = 10, 5
ADMIN_PROBE = 3
SIGNUP_BURST = 5
SHORT_LIVED_MINUTES = 60
MAX_ROWS = 50000
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "info": 3}


def _detail(r: AuditLog) -> dict:
    try:
        d = json.loads(r.detail or "{}")
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def _alert(rule, severity, rows, message, actor=None, document_id=None):
    return {"rule": rule, "severity": severity, "actor_email": actor, "document_id": document_id,
            "count": len(rows), "first_seen": aware(rows[0].ts), "last_seen": aware(rows[-1].ts),
            "audit_ids": [r.id for r in rows][:20], "message": message}


def compute_alerts(db: DBSession, hours: int = 24) -> list[dict]:
    since = now() - timedelta(hours=hours)
    rows = (db.query(AuditLog).filter(AuditLog.ts >= since).order_by(AuditLog.id).limit(MAX_ROWS).all())
    out: list[dict] = []

    # 1. Tampering with the evidence itself.
    chain = audit.verify_chain(db)
    if not chain["ok"]:
        bad = db.get(AuditLog, chain["first_bad_id"])
        out.append({"rule": "audit_chain_broken", "severity": "critical", "actor_email": None,
                    "document_id": None, "count": 1, "first_seen": aware(bad.ts), "last_seen": aware(bad.ts),
                    "audit_ids": [bad.id],
                    "message": f"Audit log hash chain breaks at row {bad.id}: history was altered or removed."})

    # 2. Repeated refusals, and probing many different documents.
    by_actor = defaultdict(list)
    for r in rows:
        if r.outcome == "denied" and r.action not in ("login", "password_change", "role_denied"):
            by_actor[r.actor_email].append(r)
    for actor, rs in by_actor.items():
        if len(rs) >= DENIALS_MEDIUM:
            out.append(_alert("repeated_denials", "high" if len(rs) >= DENIALS_HIGH else "medium", rs,
                              f"{actor} was refused {len(rs)} times on documents.", actor))
        docs = {r.document_id for r in rs if r.document_id}
        if len(docs) >= PROBE_DISTINCT_DOCS:
            out.append(_alert("document_probing", "high", rs,
                              f"{actor} was refused access to {len(docs)} different documents.", actor))

    # 3. Failed logins by account and by address; lockouts.
    by_email, by_ip = defaultdict(list), defaultdict(list)
    for r in rows:
        if r.action == "login" and r.outcome == "denied":
            by_email[r.actor_email].append(r)
            if r.ip:
                by_ip[r.ip].append(r)
    for email, rs in by_email.items():
        if len(rs) >= LOGIN_FAIL_EMAIL:
            out.append(_alert("login_failures", "medium", rs, f"{len(rs)} failed logins for {email}.", email))
    for ip, rs in by_ip.items():
        if len(rs) >= LOGIN_FAIL_IP:
            out.append(_alert("login_failures_ip", "high", rs, f"{len(rs)} failed logins from {ip}."))

    # 4. Unusual volume of downloads.
    dl = defaultdict(list)
    for r in rows:
        if r.action == "download" and r.outcome == "allowed":
            dl[r.actor_email].append(r)
    for actor, rs in dl.items():
        docs = {r.document_id for r in rs}
        if len(docs) >= BULK_DISTINCT_DOCS:
            out.append(_alert("bulk_download", "high", rs, f"{actor} downloaded {len(docs)} different documents.", actor))
        elif len(rs) >= MASS_DOWNLOADS:
            out.append(_alert("mass_download", "medium", rs, f"{actor} downloaded {len(rs)} times.", actor))

    # 5. Poking at a document after access was taken away; grant -> download -> revoke in a short time.
    for rev in (r for r in rows if r.action == "grant_revoke" and r.outcome == "allowed"):
        retries = [r for r in rows if r.id > rev.id and r.outcome == "denied" and r.actor_id == rev.target_user_id
                   and r.document_id == rev.document_id]
        if retries:
            out.append(_alert("revoked_access_retry", "high", retries,
                              f"{retries[0].actor_email} kept trying to reach a document after access was revoked.",
                              retries[0].actor_email, rev.document_id))
        started = aware(rev.ts) - timedelta(minutes=SHORT_LIVED_MINUTES)
        made = [r for r in rows if r.action in ("grant_create", "grant_update") and r.outcome == "allowed"
                and r.id < rev.id and r.document_id == rev.document_id and r.target_user_id == rev.target_user_id
                and aware(r.ts) >= started]
        got = [r for r in rows if r.action == "download" and r.outcome == "allowed" and made
               and r.actor_id == rev.target_user_id and r.document_id == rev.document_id
               and made[0].id < r.id < rev.id]
        if made and got:
            out.append(_alert("grant_download_revoke", "medium", [made[0], *got, rev],
                              "Access was granted, used to download, then revoked within an hour.",
                              None, rev.document_id))

    # 6. Probing the admin area.
    probe = defaultdict(list)
    for r in rows:
        if r.action == "role_denied" and str(_detail(r).get("path", "")).startswith("/admin"):
            probe[r.actor_email].append(r)
    for actor, rs in probe.items():
        if len(rs) >= ADMIN_PROBE:
            out.append(_alert("admin_probing", "high", rs, f"{actor} repeatedly tried admin endpoints.", actor))

    # 6b. Many sign-ups from one address in a short time (spam / farming accounts).
    reg = defaultdict(list)
    for r in rows:
        if r.action == "register" and r.ip:
            reg[r.ip].append(r)
    for ip, rs in reg.items():
        if len(rs) >= SIGNUP_BURST:
            out.append(_alert("signup_burst", "high", rs, f"{len(rs)} accounts were requested from {ip}."))

    # 7. Account changes (informational).
    for r in rows:
        if r.action == "user_update" and r.outcome == "allowed" and _detail(r):
            out.append(_alert("account_change", "info", [r],
                              f"{r.actor_email} changed a user account: {json.dumps(_detail(r))}", r.actor_email))

    out.sort(key=lambda a: (SEVERITY_ORDER[a["severity"]], -a["last_seen"].timestamp()))
    return out
