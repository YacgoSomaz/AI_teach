"""User account model for email + password authentication."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class User(Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    normalized_email: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_users_normalized_email", "normalized_email"),
    )

    def __repr__(self) -> str:
        return f"<User {self.email}>"
