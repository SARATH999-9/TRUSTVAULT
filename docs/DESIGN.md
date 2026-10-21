# TrustVault design decisions (living document)

- Roles: admin (users, audit, metadata; NO file content), owner, viewer.
- Permission model: per-document grants (read/edit) + optional expiry. Owner implicit. No folder inheritance (deliberate).
- Single choke point: `app/authz.py::authorize(user, doc, action)` called by every route that touches a document.
- Unauthorised document access returns 404 (existence not revealed) and is audited as `denied`.
- Sessions: opaque random token, SHA-256 stored, checked in DB on every request => instant revocation.
- Files: random UUID storage key outside web root, served only via authenticated endpoint.
- Audit: append-only hash chain + DB triggers + insert-only DB role.
- Revoking a grant deletes the row; history lives in the audit log.
