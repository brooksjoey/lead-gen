# C:\work-spaces\lead-gen\lead-gen\api\db\base.py
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Text, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func

# Use naming convention for constraints
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    
    metadata = MetaData(naming_convention=convention)
    
    # Common columns
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        index=True,
    )
    
    @declared_attr
    def __tablename__(cls) -> str:
        """Generate table name from class name."""
        # Convert CamelCase to snake_case
        import re
        name = cls.__name__
        name = re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()
        
        # Handle special cases
        if name.endswith("y"):
            name = name[:-1] + "ies"
        elif name.endswith("s"):
            name = name + "es"
        else:
            name = name + "s"
        
        return name
    
    def to_dict(self, exclude: list[str] = None) -> Dict[str, Any]:
        """Convert model instance to dictionary."""
        exclude = exclude or []
        result = {}
        
        for column in self.__table__.columns:
            if column.name in exclude:
                continue
            value = getattr(self, column.name)
            
            # Handle datetime serialization
            if hasattr(value, 'isoformat'):
                value = value.isoformat()
            
            result[column.name] = value
        
        return result
    
    def update(self, **kwargs) -> None:
        """Update model attributes."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
    
    def __repr__(self) -> str:
        """String representation of model."""
        attrs = []
        for column in self.__table__.columns:
            if column.primary_key or column.name in ["created_at", "updated_at"]:
                continue
            value = getattr(self, column.name)
            if value is not None:
                attrs.append(f"{column.name}={repr(value)}")
        
        return f"<{self.__class__.__name__}({', '.join(attrs)})>"


class UUIDMixin:
    """Mixin for UUID primary key."""
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )


class SoftDeleteMixin:
    """Mixin for soft delete functionality."""
    
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    deleted_by: Mapped[int] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )
    
    @property
    def is_deleted(self) -> bool:
        """Check if record is soft deleted."""
        return self.deleted_at is not None
    
    def soft_delete(self, user_id: int = None) -> None:
        """Soft delete the record."""
        self.deleted_at = datetime.utcnow()
        self.deleted_by = user_id


class AuditMixin:
    """Mixin for audit tracking."""
    
    created_by: Mapped[int] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )
    updated_by: Mapped[int] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )


# Event listeners for automatic timestamp updates
@event.listens_for(Base, "before_update", propagate=True)
def receive_before_update(mapper, connection, target):
    """Update updated_at timestamp before update."""
    target.updated_at = datetime.utcnow()


# Helper function for creating foreign key columns with consistent naming
def foreign_key(
    column_name: str,
    nullable: bool = False,
    index: bool = True,
    ondelete: str = "CASCADE",
    **kwargs,
) -> Column:
    """Create a foreign key column with consistent settings."""
    return Column(
        f"{column_name}_id",
        Integer,
        nullable=nullable,
        index=index,
        **kwargs,
    )


# Export common column types for convenience
__all__ = [
    "Base",
    "UUIDMixin",
    "SoftDeleteMixin",
    "AuditMixin",
    "foreign_key",
    "Column",
    "Integer",
    "String",
    "Text",
    "DateTime",
    "UUID",
]