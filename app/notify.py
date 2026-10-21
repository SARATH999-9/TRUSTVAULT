
"""Optional TrustVault email notifications."""
import logging
import smtplib
import threading
from email.message import EmailMessage

from .config import settings

log = logging.getLogger("trustvault.notify")


def configured() -> bool:
    """Return whether the minimum SMTP settings are present."""
    return bool(settings.smtp_host and settings.smtp_from)


def _deliver(msg: EmailMessage) -> None:
    """Deliver one message. Never print credentials."""
    try:
        with smtplib.SMTP(
            settings.smtp_host,
            settings.smtp_port,
            timeout=20,
        ) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()

            if settings.smtp_user:
                server.login(
                    settings.smtp_user,
                    settings.smtp_password,
                )

            server.send_message(msg)

        log.info("Email accepted by SMTP server: %s", msg["To"])

    except Exception:
        log.exception("TrustVault email delivery failed")


def send(to: str | None, subject: str, body: str) -> bool:
    """Queue an email without blocking the request."""
    if not to:
        log.warning("Email skipped: recipient is missing")
        return False

    if not configured():
        log.warning("Email skipped: SMTP is not configured")
        return False

    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(
        f"{body}\n\nTrustVault\n{settings.public_url}"
    )

    thread = threading.Thread(
        target=_deliver,
        args=(msg,),
        daemon=True,
    )
    thread.start()
    return True


def registration_notice(admin_email: str, user_email: str) -> bool:
    return send(
        admin_email,
        "TrustVault: New user registration",
        f"A new user has registered: {user_email}",
    )


def login_notice(user_email: str) -> bool:
    return send(
        user_email,
        "TrustVault: Successful sign-in",
        "A successful sign-in to your TrustVault account occurred. "
        "If this wasn't you, secure your account.",
    )


def decision_notice(
    user_email: str,
    decision: str,
    details: str = "",
) -> bool:
    return send(
        user_email,
        "TrustVault: Decision update",
        f"Your request has a new decision: {decision}\n{details}",
    )
