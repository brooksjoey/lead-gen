# api/models/source.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

try:
    from api.models.base import Base  # type: ignore
except Exception as exc:  # pragma: no cover
    raise ImportError(
        "Missing shared SQLAlchemy Base. Create api/models/base.py with a DeclarativeBase named Base."
    ) from exc


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint("kind IN ('landing_page','partner_api','embed_form')", name="sources_kind_valid"),
        CheckConstraint("path_prefix IS NULL OR path_prefix ~ '^/'", name="sources_path_prefix_format"),
        CheckConstraint(
            "(path_prefix IS NULL AND hostname IS NULL) OR (hostname IS NOT NULL)",
            name="sources_http_mapping_requires_hostname",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id", ondelete="RESTRICT"), nullable=False, index=True)

    source_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    path_prefix: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_key_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
