
"""Securely verify Google Identity Services ID tokens."""

import logging

from google.auth.exceptions import GoogleAuthError as GoogleLibraryAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from .config import settings

logger = logging.getLogger("trustvault.google_auth")

ISSUERS = {
    "accounts.google.com",
    "https://accounts.google.com",
}


class GoogleAuthError(Exception):
    """Raised when Google sign-in cannot be verified."""


def verify_google_token(credential: str) -> dict:
    """
    Verify a Google ID token on the server.

    Returns:
        {
            "sub": Google account's unique ID,
            "email": verified email in lowercase,
            "name": display name
        }
    """
    client_id = settings.google_client_id.strip()

    if not client_id:
        raise GoogleAuthError(
            "Google sign-in is not configured on this server."
        )

    if not isinstance(credential, str) or not credential.strip():
        raise GoogleAuthError("Google credential is missing.")

    try:
        info = id_token.verify_oauth2_token(
            credential.strip(),
            google_requests.Request(),
            audience=client_id,
        )
    except (ValueError, GoogleLibraryAuthError) as exc:
        logger.warning("Google ID token verification failed.")
        raise GoogleAuthError(
            "Google could not verify this sign-in. Please try again."
        ) from exc
    except Exception as exc:
        # Do not log the credential or the token itself.
        logger.exception("Unexpected error during Google token verification.")
        raise GoogleAuthError(
            "Google sign-in is temporarily unavailable."
        ) from exc

    # Verify issuer explicitly.
    if info.get("iss") not in ISSUERS:
        raise GoogleAuthError("Unexpected Google token issuer.")

    # Confirm the token has the required identity fields.
    subject = info.get("sub")
    email = info.get("email")
    email_verified = info.get("email_verified")

    if not isinstance(subject, str) or not subject.strip():
        raise GoogleAuthError("Google account ID is missing.")

    if not isinstance(email, str) or not email.strip():
        raise GoogleAuthError("Google email address is missing.")

    # Google normally returns a boolean here.
    if email_verified is not True:
        raise GoogleAuthError(
            "Please use a Google account with a verified email address."
        )

    email = email.strip().lower()

    name = info.get("name")
    if not isinstance(name, str) or not name.strip():
        name = email.split("@", 1)[0]

    return {
        "sub": subject,
        "email": email,
        "name": name.strip()[:120],
    }
