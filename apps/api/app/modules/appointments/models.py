from datetime import datetime, time
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    Time,
    Uuid,
    func,
    text,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AppointmentStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


class AppointmentSource(str, Enum):
    ONLINE = "ONLINE"
    PANEL = "PANEL"


class BusinessHour(Base):
    """One opening window; a lunch break is two windows on the same weekday."""

    __tablename__ = "business_hours"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_business_hours_weekday"),
        CheckConstraint("closes_at > opens_at", name="ck_business_hours_range"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    # 0 = Monday, same as date.weekday().
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    opens_at: Mapped[time] = mapped_column(Time, nullable=False)
    closes_at: Mapped[time] = mapped_column(Time, nullable=False)


class Appointment(Base):
    """Bookings and blocked periods. Overlaps per professional are rejected by
    an exclusion constraint created in the migration (PostgreSQL only)."""

    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_appointments_range"),
        CheckConstraint(
            "status = 'BLOCKED' OR (professional_id IS NOT NULL"
            " AND service_id IS NOT NULL AND customer_name IS NOT NULL"
            " AND customer_phone IS NOT NULL)",
            name="ck_appointments_customer",
        ),
        ForeignKeyConstraint(
            ["professional_id", "business_id"],
            ["professionals.id", "professionals.business_id"],
            name="fk_appointments_professional_business",
        ),
        ForeignKeyConstraint(
            ["service_id", "business_id"],
            ["services.id", "services.business_id"],
            name="fk_appointments_service_business",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id"), nullable=False
    )
    # A block without professional closes the whole business.
    professional_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    service_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    customer_phone: Mapped[str | None] = mapped_column(String(13), nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[AppointmentStatus] = mapped_column(
        SqlEnum(AppointmentStatus), nullable=False
    )
    source: Mapped[AppointmentSource] = mapped_column(
        SqlEnum(AppointmentSource), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
