from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = "sqlite+aiosqlite:///./aifood.db"

engine = create_async_engine(DATABASE_URL, echo=True)

AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

async def init_db():
    async with engine.begin() as conn:
        from database.models import MealPlan, User
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_user_schema(conn)
        await _delete_expired_unverified_users(conn)


async def _ensure_user_schema(conn):
    result = await conn.exec_driver_sql("PRAGMA table_info(users)")
    columns = {row[1] for row in result.fetchall()}
    had_email_verified = "is_email_verified" in columns

    migrations = {
        "is_email_verified": "BOOLEAN DEFAULT 0 NOT NULL",
        "created_at": "DATETIME",
        "updated_at": "DATETIME",
        "last_login_at": "DATETIME",
        "refresh_token_hash": "VARCHAR",
        "verification_code_hash": "VARCHAR",
        "verification_code_expires_at": "DATETIME",
        "verification_code_sent_at": "DATETIME",
        "verification_attempts": "INTEGER DEFAULT 0 NOT NULL",
        "password_reset_code_hash": "VARCHAR",
        "password_reset_code_expires_at": "DATETIME",
        "password_reset_code_sent_at": "DATETIME",
        "password_reset_attempts": "INTEGER DEFAULT 0 NOT NULL",
        "login_failed_attempts": "INTEGER DEFAULT 0 NOT NULL",
        "name": "VARCHAR DEFAULT ''",
        "activity_level": "VARCHAR DEFAULT 'moderate'",
        "meals_per_day": "INTEGER DEFAULT 3",
        "disliked_products": "VARCHAR DEFAULT ''",
    }

    for column, ddl in migrations.items():
        if column not in columns:
            await conn.exec_driver_sql(f"ALTER TABLE users ADD COLUMN {column} {ddl}")

    if not had_email_verified:
        await conn.exec_driver_sql("UPDATE users SET is_email_verified = 1")
    else:
        await conn.exec_driver_sql(
            "UPDATE users SET is_email_verified = 1 WHERE is_email_verified IS NULL"
        )
        await conn.exec_driver_sql(
            "UPDATE users SET is_email_verified = 1 "
            "WHERE is_email_verified = 0 "
            "AND created_at IS NULL "
            "AND verification_code_hash IS NULL"
        )


async def _delete_expired_unverified_users(conn):
    from config import settings

    ttl_hours = max(1, int(settings.UNVERIFIED_ACCOUNT_TTL_HOURS))
    await conn.exec_driver_sql(
        "DELETE FROM users "
        "WHERE is_email_verified = 0 "
        "AND created_at IS NOT NULL "
        "AND datetime(created_at) < datetime('now', ?)",
        (f"-{ttl_hours} hours",),
    )
