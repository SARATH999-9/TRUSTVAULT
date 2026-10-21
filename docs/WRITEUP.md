# TrustVault: write-up

## What I built
A document-sharing website with three portals (Administrator, Owner, Viewer) where nobody gets in until an administrator approves them, uploads wait for review, access is decided by one server-side function, every access (including refusals)
is written to a hash-chained audit log, and revoking access takes effect on the next request.
Roles: admin / owner / viewer. Per-document grants (read, edit, optional expiry). Upload validation,
versions, soft delete, search limited to what you may read, admin activity view with alerts, and
propose-only AI sharing suggestions that a person must confirm.

## What I deliberately did not build
Folder inheritance, groups, external sharing, delegated sharing, email-link verification, password reset by email, MFA, encryption at rest.
Each is either an attack surface I chose not to open in a week or is listed as accepted in THREATS.md.

## Permission model
See README ("Permission model") and `app/authz.py`. In one sentence: a grant row existing and not expired
*is* the access; the viewer role caps it at read; admins never get content; refusals are 404.

## How the audit trail is protected
Hash chain (each row commits to the previous row), PostgreSQL triggers that reject UPDATE/DELETE/TRUNCATE,
an insert-only DB role in production, and an admin verify endpoint. Known gap: deleting rows from the very
end of the log is only detectable by comparing the head hash with a copy kept elsewhere.

## What "immediately" costs
One database read of the session and one of the grant per request. No caching, no signed links.
A download already streaming when access is revoked finishes.

## How I used AI, and where it was wrong
> **YOU must write this section from your real experience.** Do not paste anything you did not actually
> see happen. Copy the dated entries from PROMPTS.md (with commit links) and say, for each, what the tool
> got wrong and how you caught it. Judges score evidence of catching errors, not praise.

## What is unfinished
The UI is tested in a simulated browser only; PostgreSQL path not exercised against a real server during development; the real LLM call is untested;
see README "What is not built" and the "Accepted" rows in THREATS.md.
