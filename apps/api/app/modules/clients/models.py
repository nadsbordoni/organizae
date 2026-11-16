from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (
        UniqueConstraint("business_id", "phone", name="uq_clients_business_phone"),
        CheckConstraint(
            "length(phone) BETWEEN 10 AND 13", name="ck_clients_phone_length"
        ),
        Index("ix_clients_business_name_id", "business_id", "name", "id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(13), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
