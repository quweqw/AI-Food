from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import HTTPException
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.email_service import send_password_reset_code, send_verification_code
from config import settings
from database.models import User


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
WEAK_PASSWORDS = {"12345678", "password", "qwerty123", "password123", "пароль123"}


def auth_error(status_code: int, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message, "details": details or {}}},
    )


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def validate_password(password: str) -> Dict[str, bool]:
    details = {
        "min_length": len(password or "") >= 8,
        "has_letter": any(ch.isalpha() for ch in password or ""),
        "has_digit": any(ch.isdigit() for ch in password or ""),
        "has_uppercase": any(ch.isupper() for ch in password or ""),
        "has_lowercase": any(ch.islower() for ch in password or ""),
        "has_special": any(not ch.isalnum() for ch in password or ""),
        "not_common": (password or "").lower() not in WEAK_PASSWORDS,
    }
    return details


def ensure_strong_password(password: str) -> None:
    details = validate_password(password)
    required = ("min_length", "has_letter", "has_digit", "has_uppercase", "has_lowercase", "has_special", "not_common")
    if not all(details[key] for key in required):
        raise auth_error(400, "WEAK_PASSWORD", "Пароль недостаточно надёжный", details)


def _token_payload(email: str, token_type: str, expires_delta: timedelta) -> Dict[str, Any]:
    expire = datetime.utcnow() + expires_delta
    return {"sub": email, "type": token_type, "exp": expire}


def create_access_token(email: str) -> str:
    return jwt.encode(
        _token_payload(email, "access", timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)),
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def create_refresh_token(email: str) -> str:
    return jwt.encode(
        _token_payload(email, "refresh", timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)),
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def create_token(email: str) -> str:
    """Backward-compatible access token helper used by older routes."""
    return create_access_token(email)


def decode_token(token: str, expected_type: str = "access") -> str | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None
    if payload.get("type", "access") != expected_type:
        return None
    return payload.get("sub")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_code(length: int = 6) -> str:
    return f"{secrets.randbelow(10 ** length):0{length}d}"


def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def verify_code_hash(code: str, expected_hash: Optional[str]) -> bool:
    return bool(expected_hash) and secrets.compare_digest(hash_code(code), expected_hash)


def _email_delivery_ready() -> bool:
    return settings.EMAIL_DEV_MODE or bool(settings.SMTP_HOST)


async def get_user_by_email(email: str, db: AsyncSession) -> User | None:
    result = await db.execute(select(User).where(User.email == str(email).lower()))
    return result.scalar_one_or_none()


async def create_user(email: str, password: str, db: AsyncSession) -> tuple[User, str]:
    if not _email_delivery_ready():
        raise auth_error(
            500,
            "EMAIL_NOT_CONFIGURED",
            "Отправка email не настроена",
        )

    normalized_email = str(email).lower()
    code = generate_code()
    now = datetime.utcnow()
    user = User(
        email=normalized_email,
        hashed_password=hash_password(password),
        is_email_verified=False,
        verification_code_hash=hash_code(code),
        verification_code_expires_at=now + timedelta(minutes=settings.VERIFICATION_CODE_EXPIRE_MINUTES),
        verification_code_sent_at=now,
        verification_attempts=0,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    sent = send_verification_code(normalized_email, code)
    if not sent and not settings.EMAIL_DEV_MODE:
        await db.delete(user)
        await db.commit()
        raise auth_error(
            500,
            "EMAIL_SEND_FAILED",
            "Не удалось отправить код подтверждения на email",
        )
    return user, code


async def reset_verification_code(user: User, db: AsyncSession) -> str:
    now = datetime.utcnow()
    if user.verification_code_sent_at:
        elapsed = (now - user.verification_code_sent_at).total_seconds()
        if elapsed < settings.VERIFICATION_RESEND_COOLDOWN_SECONDS:
            raise auth_error(
                429,
                "VERIFICATION_RESEND_COOLDOWN",
                "Код уже отправлен. Подождите перед повторной отправкой.",
                {"retry_after_seconds": int(settings.VERIFICATION_RESEND_COOLDOWN_SECONDS - elapsed)},
            )

    code = generate_code()
    user.verification_code_hash = hash_code(code)
    user.verification_code_expires_at = now + timedelta(minutes=settings.VERIFICATION_CODE_EXPIRE_MINUTES)
    user.verification_code_sent_at = now
    user.verification_attempts = 0
    user.updated_at = now
    await db.commit()
    sent = send_verification_code(user.email, code)
    if not sent and not settings.EMAIL_DEV_MODE:
        raise auth_error(
            500,
            "EMAIL_SEND_FAILED",
            "Не удалось отправить код подтверждения на email",
        )
    return code


async def delete_unverified_account_if_expired(user: User, db: AsyncSession) -> bool:
    if user.is_email_verified:
        return False

    created_at = user.created_at
    if created_at and datetime.utcnow() - created_at > timedelta(
        hours=settings.UNVERIFIED_ACCOUNT_TTL_HOURS,
    ):
        await db.delete(user)
        await db.commit()
        return True
    return False


async def ensure_unverified_account_active(user: User, db: AsyncSession) -> None:
    if await delete_unverified_account_if_expired(user, db):
        raise auth_error(
            410,
            "EMAIL_VERIFICATION_EXPIRED",
            "Срок подтверждения email истёк. Зарегистрируйтесь заново.",
        )


async def verify_email_code(user: User, code: str, db: AsyncSession) -> None:
    await ensure_unverified_account_active(user, db)
    now = datetime.utcnow()
    if not user.verification_code_expires_at or now > user.verification_code_expires_at:
        raise auth_error(400, "VERIFICATION_CODE_EXPIRED", "Код подтверждения истёк")

    if user.verification_attempts >= 5:
        raise auth_error(429, "TOO_MANY_VERIFICATION_ATTEMPTS", "Слишком много попыток ввода кода")

    if not verify_code_hash(code, user.verification_code_hash):
        user.verification_attempts = int(user.verification_attempts or 0) + 1
        await db.commit()
        raise auth_error(400, "INVALID_VERIFICATION_CODE", "Неверный код подтверждения")

    user.is_email_verified = True
    user.verification_code_hash = None
    user.verification_code_expires_at = None
    user.verification_attempts = 0
    user.updated_at = now
    await db.commit()


async def request_password_reset(user: User, db: AsyncSession) -> str:
    if not _email_delivery_ready():
        raise auth_error(
            500,
            "EMAIL_NOT_CONFIGURED",
            "Отправка email не настроена",
        )

    now = datetime.utcnow()
    if user.password_reset_code_sent_at:
        elapsed = (now - user.password_reset_code_sent_at).total_seconds()
        if elapsed < settings.PASSWORD_RESET_RESEND_COOLDOWN_SECONDS:
            raise auth_error(
                429,
                "PASSWORD_RESET_RESEND_COOLDOWN",
                "Код уже отправлен. Подождите перед повторной отправкой.",
                {"retry_after_seconds": int(settings.PASSWORD_RESET_RESEND_COOLDOWN_SECONDS - elapsed)},
            )

    code = generate_code(8)
    user.password_reset_code_hash = hash_code(code)
    user.password_reset_code_expires_at = now + timedelta(minutes=settings.PASSWORD_RESET_CODE_EXPIRE_MINUTES)
    user.password_reset_code_sent_at = now
    user.password_reset_attempts = 0
    user.updated_at = now
    await db.commit()
    sent = send_password_reset_code(user.email, code)
    if not sent and not settings.EMAIL_DEV_MODE:
        raise auth_error(
            500,
            "EMAIL_SEND_FAILED",
            "Не удалось отправить код восстановления на email",
        )
    return code


async def reset_password_with_code(
    user: User,
    code: str,
    new_password: str,
    db: AsyncSession,
) -> None:
    if not user.is_email_verified:
        await ensure_unverified_account_active(user, db)

    now = datetime.utcnow()
    if not user.password_reset_code_expires_at or now > user.password_reset_code_expires_at:
        raise auth_error(400, "PASSWORD_RESET_CODE_EXPIRED", "Код восстановления истёк")

    if user.password_reset_attempts >= 5:
        raise auth_error(429, "TOO_MANY_PASSWORD_RESET_ATTEMPTS", "Слишком много попыток ввода кода")

    if not verify_code_hash(code, user.password_reset_code_hash):
        user.password_reset_attempts = int(user.password_reset_attempts or 0) + 1
        await db.commit()
        raise auth_error(400, "INVALID_PASSWORD_RESET_CODE", "Неверный код восстановления")

    ensure_strong_password(new_password)
    user.hashed_password = hash_password(new_password)
    user.is_email_verified = True
    user.password_reset_code_hash = None
    user.password_reset_code_expires_at = None
    user.password_reset_code_sent_at = None
    user.password_reset_attempts = 0
    user.refresh_token_hash = None
    user.updated_at = now
    await db.commit()


async def issue_tokens(user: User, db: AsyncSession) -> tuple[str, str]:
    access_token = create_access_token(user.email)
    refresh_token = create_refresh_token(user.email)
    user.refresh_token_hash = token_hash(refresh_token)
    user.last_login_at = datetime.utcnow()
    user.login_failed_attempts = 0
    user.updated_at = datetime.utcnow()
    await db.commit()
    return access_token, refresh_token


async def clear_refresh_token(user: User, db: AsyncSession) -> None:
    user.refresh_token_hash = None
    user.updated_at = datetime.utcnow()
    await db.commit()
