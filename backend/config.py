from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = ConfigDict(extra="ignore", env_file=("../.env", ".env"))

    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    VERIFICATION_CODE_EXPIRE_MINUTES: int = 10
    VERIFICATION_RESEND_COOLDOWN_SECONDS: int = 60
    PASSWORD_RESET_CODE_EXPIRE_MINUTES: int = 10
    PASSWORD_RESET_RESEND_COOLDOWN_SECONDS: int = 60
    EMAIL_DEV_MODE: bool = False
    UNVERIFIED_ACCOUNT_TTL_HOURS: int = 24

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False


settings = Settings()
