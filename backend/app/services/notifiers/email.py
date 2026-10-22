import logging
import smtplib
from email.message import EmailMessage

from ...config import settings
from .errors import DeliveryError

log = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> None:
    if settings.email_backend == "console":
        # dev mode: nothing leaves the machine, the email is just printed in the worker log
        log.warning("EMAIL (console backend) to=%s subject=%r\n%s", to, subject, body)
        return

    if not settings.smtp_host:
        raise DeliveryError("EMAIL_BACKEND=smtp but SMTP_HOST is not set")

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise DeliveryError(f"SMTP error: {exc.__class__.__name__}") from exc
