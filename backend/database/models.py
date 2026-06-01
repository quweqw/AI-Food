from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text

from database.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)

    is_email_verified = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)
    refresh_token_hash = Column(String, nullable=True)
    verification_code_hash = Column(String, nullable=True)
    verification_code_expires_at = Column(DateTime, nullable=True)
    verification_code_sent_at = Column(DateTime, nullable=True)
    verification_attempts = Column(Integer, default=0, nullable=False)
    password_reset_code_hash = Column(String, nullable=True)
    password_reset_code_expires_at = Column(DateTime, nullable=True)
    password_reset_code_sent_at = Column(DateTime, nullable=True)
    password_reset_attempts = Column(Integer, default=0, nullable=False)
    login_failed_attempts = Column(Integer, default=0, nullable=False)

    name = Column(String, default="")
    age = Column(Integer, default=25)
    gender = Column(String, default="male")
    height = Column(Integer, default=175)
    weight = Column(Float, default=70.0)
    activity_level = Column(String, default="moderate")

    daily_calories = Column(Integer, default=2000)
    diet_type = Column(String, default="normal")
    meals_per_day = Column(Integer, default=3)

    allergens = Column(String, default="")
    favorite_products = Column(String, default="")
    disliked_products = Column(String, default="")
    excluded_products = Column(String, default="")

    push_notifications = Column(Boolean, default=True)


class MealPlan(Base):
    __tablename__ = "meal_plans"

    id = Column(String, primary_key=True, index=True)
    user_email = Column(String, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    request_json = Column(Text, nullable=False, default="{}")
    response_json = Column(Text, nullable=False, default="{}")
    progress_json = Column(Text, nullable=False, default="{}")
