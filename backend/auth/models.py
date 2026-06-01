from typing import Any, Dict, Optional

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    confirm_password: Optional[str] = None


class RegisterResponse(BaseModel):
    user_id: str
    email: EmailStr
    is_email_verified: bool
    message: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class VerifyCodeRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: Optional[str] = None


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=8, max_length=8, pattern=r"^\d{8}$")
    new_password: str
    confirm_password: str


class PasswordResetStartResponse(BaseModel):
    message: str


class UserPublic(BaseModel):
    id: str
    email: EmailStr
    is_email_verified: bool
    profile: Dict[str, Any] = {}


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserPublic


class MessageResponse(BaseModel):
    message: str
