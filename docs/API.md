# API reference: who may call what

Authentication: sign in at `POST /auth/login` (or `/auth/register`, `/auth/google`). You get a session token, also set as an
HttpOnly, SameSite=Strict cookie. Send it as `Authorization: Bearer <token>` for scripts. Interactive docs: `/docs`.

Account states: **pending** (just signed up) → **active** (approved) | **rejected**; active ⇄ **suspended**.
Only `/auth/me` and `/auth/logout` work for a *pending* account; **everything else answers 403 until an administrator approves it**.
"Document owner" below means: role `owner` AND the owner of that specific document.
Anything a caller is not allowed to see answers **404** (not 403) so existence is not revealed; 403 means the document is visible
but the level is too low. Documents also require **admin approval** (and an active owner) before anyone but the owner can reach them.
Every refusal is audited.

| Method | Path | Who may call | Notes |
|---|---|---|---|
| `GET` | `/` | anyone | serves the web app (static files under `/static`) |
| `GET` | `/health` | anyone | liveness |
| `GET` | `/auth/config` | anyone | public sign-in settings (Google client id is public by design) |
| `POST` | `/auth/register` | anyone | request an **owner** or **viewer** account (never admin); starts *pending*; 10 per hour per IP |
| `POST` | `/auth/login` | anyone | optional `portal` must match the account's role; lockout after 5 failures; per-IP limit |
| `POST` | `/auth/google` | anyone | Google ID token verified on the server; new owner/viewer accounts start *pending*; admins only if allow-listed |
| `POST` | `/auth/logout` | any signed-in user (even pending) | revokes this session |
| `GET` | `/auth/me` | any signed-in user (even pending) | how the waiting screen learns it was approved |
| `POST` | `/auth/change-password` | active users with a password | revokes all other sessions; Google accounts have none |
| `GET` | `/policy` | active users | what the administrator allows to be uploaded |
| `POST` | `/admin/users` | admin | create an already-approved user |
| `GET` | `/admin/users` | admin | filters: status, role, q |
| `PATCH` | `/admin/users/{user_id}` | admin | approve / reject / suspend / reactivate and/or change role; reason recorded; sessions revoked on reject/suspend; cannot target self |
| `GET` | `/admin/owners` | admin | owner directory: status, document counts, shares, last upload |
| `GET` | `/admin/pending-counts` | admin | sidebar badges |
| `GET` | `/admin/audit` | admin | filters: action, outcome, actor, document_id, target_user_id, since, until |
| `GET` | `/admin/audit/verify` | admin | verifies the hash chain; returns head hash |
| `GET` | `/admin/documents` | admin | metadata only (uploader, type, size, checksum, review state); filters review_status, q, owner |
| `POST` | `/admin/documents/{doc_id}/review` | admin | approve / reject (reason required to reject) |
| `GET` | `/admin/documents/{doc_id}/timeline` | admin | who did what, readers summary, refused attempts |
| `GET` | `/admin/policy` | admin | allowed types, max size, categories |
| `PUT` | `/admin/policy` | admin | change the upload policy (audited with before/after) |
| `GET` | `/admin/alerts` | admin | "worth noticing" rules over a time window |
| `GET` | `/admin/summary` | admin | counts incl. pending accounts and documents |
| `POST` | `/documents` | owner role | upload (multipart); checked against the admin's policy; starts *pending review* |
| `POST` | `/documents/compose` | owner role | write a text document in the browser; same rules as an upload |
| `GET` | `/documents` | owner, viewer roles | list + search; only documents you may read (shared ones must be approved and their owner active) |
| `GET` | `/documents/{doc_id}` | read access (owner or grant) | metadata + versions + review status |
| `GET` | `/documents/{doc_id}/download` | read access | `?version=` must belong to this document; audited; also used by in-browser preview |
| `PATCH` | `/documents/{doc_id}` | edit access | name / category / description |
| `POST` | `/documents/{doc_id}/versions` | edit access | new version; voids any earlier approval |
| `POST` | `/documents/{doc_id}/versions/text` | edit access | edit a `.txt` document as a new version; voids any earlier approval |
| `DELETE` | `/documents/{doc_id}` | document owner | soft delete |
| `POST` | `/documents/{doc_id}/grants` | document owner | share (read / edit, optional expiry); only approved documents; only active non-admin accounts |
| `GET` | `/documents/{doc_id}/grants` | document owner | |
| `DELETE` | `/documents/{doc_id}/grants/{grant_id}` | document owner | immediate revocation |
| `POST` | `/documents/{doc_id}/suggestions` | document owner | AI/rule-based sharing suggestion; grants nothing |
| `GET` | `/documents/{doc_id}/suggestions/{sid}` | document owner | |
| `POST` | `/documents/{doc_id}/suggestions/{sid}/decisions` | document owner | human accept/reject; the only way a suggestion becomes a grant |

Admins never receive document contents, even for documents they own or were granted. Viewers are capped at read access no matter what a grant row says.
