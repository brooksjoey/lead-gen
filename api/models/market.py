# api/models/market.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

try:
    # Preferred shared base (define once in your repo).
    from api.models.base import Base  # type: ignore
except Exception as exc:  # pragma: no cover
    raise ImportError(
        "Missing shared SQLAlchemy Base. Create api/models/base.py with a DeclarativeBase named Base."
    ) from exc


class Market(Base):
    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
