from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from auth import service
from auth.models import (
    ChangePasswordRequest,
    LoginRequest,
    MessageResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    PasswordResetStartResponse,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    ResendVerificationRequest,
    TokenResponse,
    UserPublic,
    VerifyCodeRequest,
)
from database.db import get_db
from database.models import User


router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()


async def current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    email = service.decode_token(credentials.credentials)
    if not email:
        raise service.auth_error(401, "INVALID_TOKEN", "Невалидный токен")
    user = await service.get_user_by_email(email, db)
    if not user:
        raise service.auth_error(401, "INVALID_TOKEN", "Пользователь не найден")
    return user


def _public_user(user: User) -> UserPublic:
    return UserPublic(
        id=str(user.id),
        email=user.email,
        is_email_verified=bool(user.is_email_verified),
        profile={
            "name": user.name or "",
            "age": user.age,
            "sex": user.gender,
            "height_cm": user.height,
            "weight_kg": user.weight,
            "activity_level": user.activity_level or "moderate",
            "goal": _goal_from_diet_type(user.diet_type),
            "target_calories": user.daily_calories,
            "meals_per_day": user.meals_per_day or 3,
        },
    )


def _goal_from_diet_type(value: str | None) -> str:
    raw = str(value or "normal").lower()
    if raw in {"cut", "weight_loss"}:
        return "weight_loss"
    if raw in {"bulk", "muscle_gain"}:
        return "muscle_gain"
    return "balanced"


async def _token_response(user: User, db: AsyncSession) -> TokenResponse:
    access_token, refresh_token = await service.issue_tokens(user, db)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=_public_user(user),
    )


@router.post("/register", response_model=RegisterResponse)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    if data.confirm_password is not None and data.password != data.confirm_password:
        raise service.auth_error(400, "PASSWORD_MISMATCH", "Пароли не совпадают")
    service.ensure_strong_password(data.password)

    existing = await service.get_user_by_email(data.email, db)
    if existing and await service.delete_unverified_account_if_expired(existing, db):
        existing = None
    if existing:
        if not existing.is_email_verified:
            raise service.auth_error(
                409,
                "EMAIL_NOT_VERIFIED",
                "Email уже зарегистрирован, подтвердите код",
                {"email": existing.email},
            )
        raise service.auth_error(409, "EMAIL_ALREADY_EXISTS", "Email уже зарегистрирован")

    user, _ = await service.create_user(data.email, data.password, db)
    return RegisterResponse(
        user_id=str(user.id),
        email=user.email,
        is_email_verified=bool(user.is_email_verified),
        message="Код подтверждения отправлен на email",
    )


@router.post("/verify-email", response_model=TokenResponse)
async def verify_email(data: VerifyCodeRequest, db: AsyncSession = Depends(get_db)):
    user = await service.get_user_by_email(data.email, db)
    if not user:
        raise service.auth_error(404, "USER_NOT_FOUND", "Пользователь не найден")
    await service.ensure_unverified_account_active(user, db)
    await service.verify_email_code(user, data.code, db)
    await db.refresh(user)
    return await _token_response(user, db)


@router.post("/verify", response_model=TokenResponse)
async def verify_email_legacy(data: VerifyCodeRequest, db: AsyncSession = Depends(get_db)):
    return await verify_email(data, db)


@router.post("/resend-verification-code", response_model=MessageResponse)
async def resend_verification_code(data: ResendVerificationRequest, db: AsyncSession = Depends(get_db)):
    user = await service.get_user_by_email(data.email, db)
    if not user:
        raise service.auth_error(404, "USER_NOT_FOUND", "Пользователь не найден")
    if user.is_email_verified:
        return MessageResponse(message="Email уже подтверждён")
    await service.ensure_unverified_account_active(user, db)
    await service.reset_verification_code(user, db)
    return MessageResponse(message="Код подтверждения отправлен повторно")


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await service.get_user_by_email(data.email, db)
    if not user or not service.verify_password(data.password, user.hashed_password):
        if user:
            user.login_failed_attempts = int(user.login_failed_attempts or 0) + 1
            await db.commit()
        raise service.auth_error(401, "INVALID_CREDENTIALS", "Неверный email или пароль")
    if not user.is_email_verified:
        await service.ensure_unverified_account_active(user, db)
        raise service.auth_error(
            403,
            "EMAIL_NOT_VERIFIED",
            "Подтвердите email перед входом",
            {"email": user.email},
        )
    return await _token_response(user, db)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    email = service.decode_token(data.refresh_token, expected_type="refresh")
    if not email:
        raise service.auth_error(401, "INVALID_REFRESH_TOKEN", "Невалидный refresh token")
    user = await service.get_user_by_email(email, db)
    if not user or user.refresh_token_hash != service.token_hash(data.refresh_token):
        raise service.auth_error(401, "INVALID_REFRESH_TOKEN", "Невалидный refresh token")
    return await _token_response(user, db)


@router.post("/logout", response_model=MessageResponse)
async def logout(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await service.clear_refresh_token(user, db)
    return MessageResponse(message="Вы вышли из аккаунта")


@router.get("/me", response_model=UserPublic)
async def me(user: User = Depends(current_user)):
    return _public_user(user)


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    data: ChangePasswordRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    if not service.verify_password(data.current_password, user.hashed_password):
        raise service.auth_error(401, "INVALID_CREDENTIALS", "Текущий пароль неверный")
    if data.confirm_password is not None and data.new_password != data.confirm_password:
        raise service.auth_error(400, "PASSWORD_MISMATCH", "Пароли не совпадают")
    service.ensure_strong_password(data.new_password)
    user.hashed_password = service.hash_password(data.new_password)
    await service.clear_refresh_token(user, db)
    return MessageResponse(message="Пароль обновлён")


@router.put("/password", response_model=MessageResponse)
async def change_password_alias(
    data: ChangePasswordRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    return await change_password(data, user, db)


@router.post("/password-reset/request", response_model=PasswordResetStartResponse)
async def request_password_reset(
    data: PasswordResetRequest,
    db: AsyncSession = Depends(get_db),
):
    user = await service.get_user_by_email(data.email, db)
    if not user:
        return PasswordResetStartResponse(
            message="Если email зарегистрирован, код восстановления отправлен",
        )
    if not user.is_email_verified:
        await service.ensure_unverified_account_active(user, db)

    await service.request_password_reset(user, db)
    return PasswordResetStartResponse(
        message="Код восстановления отправлен на email",
    )


@router.post("/password-reset/confirm", response_model=MessageResponse)
async def confirm_password_reset(
    data: PasswordResetConfirmRequest,
    db: AsyncSession = Depends(get_db),
):
    if data.new_password != data.confirm_password:
        raise service.auth_error(400, "PASSWORD_MISMATCH", "Пароли не совпадают")

    user = await service.get_user_by_email(data.email, db)
    if not user:
        raise service.auth_error(404, "USER_NOT_FOUND", "Пользователь не найден")

    await service.reset_password_with_code(user, data.code, data.new_password, db)
    return MessageResponse(message="Пароль обновлён. Теперь можно войти.")
