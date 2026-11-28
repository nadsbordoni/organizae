from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Uuid,
    func,
    text,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NotificationKind(str, Enum):
    BOOKING_CREATED = "BOOKING_CREATED"


class Notification(Base):
    """Something that happened in the agenda that the business owner should see.

    It points to the appointment instead of copying its data, so the panel always
    shows the current time and status of the booking."""

    __tablename__ = "notifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["appointment_id", "business_id"],
            ["appointments.id", "appointments.business_id"],
            ondelete="CASCADE",
            name="fk_notifications_appointment_business",
        ),
        Index("ix_notifications_business_created", "business_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id"), nullable=False
    )
    appointment_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    kind: Mapped[NotificationKind] = mapped_column(
        SqlEnum(NotificationKind), nullable=False
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
