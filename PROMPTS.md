# PROMPTS.md

## Reusable context / instructions

**Project:** TrustVault — a secure document storage and sharing application.

**Reusable instructions:**
- Review the existing code before suggesting changes.
- Preserve the existing project structure, database models, and API routes where possible.
- Never expose passwords, API keys, OAuth tokens, session cookies, or other secrets in source code or logs.
- Validate all authentication and authorization on the backend; never trust frontend-only checks.
- Add appropriate error handling and audit logging for security-sensitive actions.
- Test changes before committing and document any remaining limitations.

## Entries

### 2026-10-18 — Environment setup and application startup
- **Asked:** Help resolve TrustVault setup errors involving environment variables and application startup.
- **Produced:** Instructions for configuring `.env`, activating the virtual environment, and running the FastAPI application.
- **Wrong:** The `.env.example` file was not present at the assumed path, so the suggested copy command could not run.
- **Fixed (commit):** [Add actual GitHub commit link]

### 2026-10-19 — Authentication and session handling
- **Asked:** Explain and troubleshoot `/auth/me`, `/auth/register`, and `/auth/logout` responses.
- **Produced:** An explanation of HTTP 401, 409, 201, and 200 responses and how they relate to authentication and registration.
- **Wrong:** Access logs alone could not confirm that session handling was secure or that email notifications were delivered.
- **Fixed (commit):** [Add actual GitHub commit link]

### 2026-10-20 — Google ID token verification
- **Asked:** Improve the Google Identity Services token verification module.
- **Produced:** Python code to validate the token's audience, issuer, expiry through Google's verification library, and verified email before returning identity details.
- **Wrong:** Token verification alone does not create a TrustVault session, enforce administrator permissions, or connect the identity to the correct application user.
- **Fixed (commit):** [Add actual GitHub commit link]

### 2026-10-20 — Authorization and administrator access control
- **Asked:** Review how Google sign-in and administrator access should work in TrustVault.
- **Produced:** Guidance to enforce administrator authorization on the backend rather than relying on frontend visibility or a Google sign-in button.
- **Wrong:** A verified Google identity does not automatically prove that the account is authorized to access administrator functionality.
- **Fixed (commit):** [Add actual GitHub commit link]

### 2026-10-21 — Document approval and access control
- **Asked:** Ensure document approval requirements are respected before documents become visible to other users.
- **Produced:** Guidance to enforce approval and sharing permissions in backend routes before returning protected documents.
- **Wrong:** Hiding an unapproved document in the frontend would not prevent a user from accessing it directly through an API endpoint.
- **Fixed (commit):** [Add actual GitHub commit link]

### 2026-10-22 — Email notifications and auditability
- **Asked:** Configure SMTP notifications for registration, login, and administrator decisions.
- **Produced:** Guidance for asynchronous email delivery, notification helpers, and logging delivery failures without exposing credentials.
- **Wrong:** Defining notification helper functions does not send emails unless the relevant route handlers call them; ordinary HTTP access logs do not prove delivery.
- **Fixed (commit):** [Add actual GitHub commit link]
