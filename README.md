<<<<<<< HEAD
# TrustVault: secure document sharing with approved accounts and a provable audit trail

One website with **three portals** (Administrator, Owner, Viewer). Nobody gets in, and no document is shared, until an
administrator approves it. Everything the screens show is enforced again on the server.

```
        sign up / Continue with Google                admin approves                    owner uploads or writes
 Viewer ───────────────────────────────▶ "Waiting for admin approval" ───▶ Viewer panel ◀─── owner shares ◀─── admin reviews the upload
 Owner  ───────────────────────────────▶ "Waiting for admin approval" ───▶ Owner panel ──▶ upload / write ──▶ "awaiting review" ──┘
 Admin  (created at deploy time from ADMIN_EMAIL / ADMIN_PASSWORD, or an allow-listed Google account)
```

| Portal | What they can do |
|---|---|
| **Administrator** | Approve or reject new accounts (with the person's details), review every uploaded document (metadata only, never contents), set the upload policy (file types, size, categories), supervise and suspend owners, see who opened what and when, alerts, and a tamper-evident audit log |
| **Owner** | Upload or write documents, see their review status, share with approved viewers (read or edit, optional expiry), revoke at any time, AI/rule-based "who should see this?" suggestions that only a person can confirm |
| **Viewer** | After approval: see, preview and download only the documents shared with them |

The first page is an animated TrustVault intro (click to skip; skipped for people who prefer reduced motion), then the portal chooser.

## What you need (accounts and APIs)

| Need | Required? | What for | Where to get it |
|---|---|---|---|
| **First administrator** (`ADMIN_EMAIL`, `ADMIN_PASSWORD`) | **Yes** | Nobody can self-register as an admin, so this is how you get in | You choose them in `.env` / Render |
| **Google OAuth Client ID** (`GOOGLE_CLIENT_ID`) | For "Continue with Google" | Sign-in with Google for the Owner and Viewer portals (and allow-listed admins) | Steps below. Free |
| **SMTP email account** (`SMTP_*`) | Recommended | Emails admins about new sign-ups/uploads and tells people when they are approved or declined | Any provider: Gmail app password, Brevo, Resend, SendGrid, Mailgun (SMTP). Free tiers exist |
| **PostgreSQL** (`DATABASE_URL`) | Yes in production | Real database | Render creates one from `render.yaml` |
| **Anthropic API key** (`ANTHROPIC_API_KEY`, `AI_PROVIDER=anthropic`) | Optional | Re-words the sharing suggestions. Works without it (rule-based) | console.anthropic.com |
| HTTPS / domain | Yes in production | Secure cookies | Render provides HTTPS |

### Set up "Continue with Google" (about 5 minutes)
1. Open <https://console.cloud.google.com/> → create or choose a project.
2. **APIs & Services → OAuth consent screen**: choose *External*, fill the app name (TrustVault) and your email, save.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID** → application type **Web application**.
4. Under **Authorised JavaScript origins** add `http://localhost:8000` and your deployed address (for example `https://trustvault.onrender.com`). No redirect URI is needed.
5. Copy the **Client ID** (looks like `1234-abc.apps.googleusercontent.com`) into `GOOGLE_CLIENT_ID`. There is no client secret to store.
6. While the consent screen is in *Testing*, only the test users you list there can sign in; click **Publish app** to let anyone.
Until `GOOGLE_CLIENT_ID` is set, the Google button is shown disabled with an explanation.

How Google accounts are treated: Google proves the email is real, but the person still needs administrator approval like everyone else.
Admins can only enter through Google if their email equals `ADMIN_EMAIL` or is in `ADMIN_EMAILS`.

### Set up email notifications (optional)
Set `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` and `PUBLIC_URL`. For Gmail use `smtp.gmail.com` with an
[app password](https://myaccount.google.com/apppasswords). Email failures never break the app.

## Run it on your computer
Needs Python 3.12 or newer. From the project root (the folder containing `requirements.txt`):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1          # Mac/Linux:  source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env              # Mac/Linux:  cp .env.example .env
```
Edit `.env`: set **`ADMIN_EMAIL`** and a strong **`ADMIN_PASSWORD`** (10+ characters), and optionally `GOOGLE_CLIENT_ID`. The example file holds placeholder values on purpose: **the app refuses to start until you replace them**, so a public example password can never become a real administrator. Then:
```powershell
uvicorn app.main:app --reload
```
Open <http://localhost:8000/>, pick **Administrator**, and sign in with those details. Open the site in a second browser window to sign up as an
Owner or Viewer, then approve yourself from the admin window.

> Upgrading from an older copy? The database layout changed. Stop the server, **delete `trustvault.db`** (and the `storage` folder's contents), and start again. The app tells you this if it detects an old database.

## Deploy (Render)
1. Push the repo to GitHub. 2. Render → **New → Blueprint** → choose the repo (`render.yaml` creates the web service and a PostgreSQL database).
3. When asked, fill `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `PUBLIC_URL` and (optionally) `GOOGLE_CLIENT_ID` and the `SMTP_*` values.
4. Add your Render URL to the Google client's *Authorised JavaScript origins*.
5. First start applies `schema.sql` (tables and audit-log immutability triggers) and creates the administrator.
6. Production hardening: create the restricted DB role described at the bottom of `schema.sql` so the app account can only INSERT into `audit_log`.

Any host with Docker works: `docker build -t trustvault . && docker run -p 8000:8000 --env-file .env trustvault`.

## Permission model
- **Roles** set the ceiling; **grants** set what you can do to one document. Admin never receives file contents.
- **Account state**: `pending` → `active` | `rejected`; `active` ⇄ `suspended`. Only an `active` account can do anything; a pending one can see its own status and sign out.
- **Document state**: every upload and every new version starts `pending review`. Only the owner can open it until an administrator approves it; a new version cancels the earlier approval.
- A **grant** is one row: *(document, person, read|edit, optional expiry)*. Viewers are capped at read. No folder inheritance (deliberate).
- Anyone but the owner reaches a document only if: it is approved, its owner is active, and a live grant exists. Revoking, rejecting, suspending or deleting takes effect on the very next request.
- Unauthorised access answers **404** (identical to "does not exist"); insufficient level answers 403. Every refusal is audited.

## Tests
```powershell
pytest -q                 # ~3 minutes: accounts, approvals, Google, policy, review, authorisation, audit, web security
sh tests/ui/run.sh        # optional (needs Node 18+): drives the real screens as every role in a simulated browser
```
`docs/API.md` lists every endpoint and who may call it (a test keeps it in sync). `THREATS.md` lists what could go wrong, what stops it, and what is knowingly accepted.

## Where things are
| Path | What |
|---|---|
| `app/authz.py` | the single document-authorisation choke point |
| `app/deps.py` | sign-in checks: default-deny for anything not `active` |
| `app/routes/auth.py`, `app/google_auth.py` | sign-up, sign-in, Google verification |
| `app/routes/admin.py`, `app/policy.py` | approvals, review, owners, upload policy, audit, alerts |
| `app/routes/documents.py`, `grants.py`, `suggestions.py` | documents, sharing, suggestions |
| `app/audit.py` | hash-chained, append-only audit log |
| `static/` | the web app (one module per screen group, no build step, no CDN) |
| `schema.sql` | PostgreSQL schema + immutability triggers + least-privilege role |
| `scripts/seed.py` | development-only sample data (`--demo`); never used in deployment |

## Not built / limits (honest list)
- Email addresses of password sign-ups are not verified (no confirmation link); admins see "Email not verified" and decide. Google sign-ups are verified by Google.
- No password reset by email, no MFA/step-up authentication, no per-document encryption at rest.
- Administrators approve on metadata only (they cannot see contents by design); there is no malware or content scanning.
- Rate limits are per server process; use a CDN/proxy limiter if you run several instances.
- The PostgreSQL path (`schema.sql`, triggers) was written but not run against a real PostgreSQL server while building; tests run on SQLite. Check the first deploy.
- Google sign-in, SMTP delivery and the live AI call were tested with fakes only (they need your credentials); the screens were tested in a simulated browser (jsdom), not real Chrome/Firefox/Safari.
- No ownership transfer, restore-from-deleted, or retention job (soft delete only).
=======
>>>>>>> a4a0107bca9f76c8a9976efcbddc9d1de80b7ce4
