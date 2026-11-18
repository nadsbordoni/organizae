from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.modules.businesses.models import Business


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("professional_id", name="uq_users_professional_id"),
        # An account is either the business owner or a professional, never both.
        CheckConstraint(
            "business_id IS NULL OR professional_id IS NULL",
            name="ck_users_single_role",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    business_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("businesses.id"),
        unique=True,
        nullable=True,
    )

    # Login of a professional: sees only their own agenda, never the business data.
    professional_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("professionals.id"),
        nullable=True,
    )

    business: Mapped[Business | None] = relationship(
        "Business",
        back_populates="user",
    )