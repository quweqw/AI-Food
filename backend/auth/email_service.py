from __future__ import annotations

import smtplib
from email.message import EmailMessage

from config import settings


def _send_code_email(
    email: str,
    code: str,
    *,
    subject: str,
    body: str,
    dev_label: str,
) -> bool:
    """Send an email code without exposing it outside email in prod."""
    if settings.EMAIL_DEV_MODE:
        print(f"[AI Food DEV] {dev_label} for {email}: {code}")
        return False
    if not settings.SMTP_HOST:
        print("[AI Food email] SMTP_HOST is not configured")
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.SMTP_FROM or settings.SMTP_USERNAME
    message["To"] = email
    message.set_content(body)

    try:
        use_ssl = settings.SMTP_USE_SSL or int(settings.SMTP_PORT) == 465
        smtp_cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        with smtp_cls(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
            if settings.SMTP_USE_TLS and not use_ssl:
                smtp.starttls()
            if settings.SMTP_USERNAME:
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            smtp.send_message(message)
        return True
    except Exception as exc:
        print(f"[AI Food email] failed to send code: {type(exc).__name__}")
        return False


def send_verification_code(email: str, code: str) -> bool:
    return _send_code_email(
        email,
        code,
        subject="AI Food - код подтверждения",
        body=(
            f"Ваш код подтверждения: {code}. Код действует "
            f"{settings.VERIFICATION_CODE_EXPIRE_MINUTES} минут."
        ),
        dev_label="verification code",
    )


def send_password_reset_code(email: str, code: str) -> bool:
    return _send_code_email(
        email,
        code,
        subject="AI Food - код восстановления пароля",
        body=(
            f"Ваш код восстановления пароля: {code}. Код действует "
            f"{settings.PASSWORD_RESET_CODE_EXPIRE_MINUTES} минут. "
            "Если вы не запрашивали смену пароля, просто проигнорируйте письмо."
        ),
        dev_label="password reset code",
    )
