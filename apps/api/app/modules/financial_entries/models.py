from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    column,
    extract,
    func,
    text,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.modules.appointments.models import Appointment
from app.modules.financial_categories.models import FinancialCategory, FinancialType

if TYPE_CHECKING:
    from app.modules.recurring_entries.models import RecurringEntry


class FinancialEntryStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class FinancialEntry(Base):
    __tablename__ = "financial_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["recurring_entry_id", "business_id"],
            ["recurring_entries.id", "recurring_entries.business_id"],
            name="fk_financial_entries_recurrence_business",
        ),
        UniqueConstraint(
            "recurring_entry_id",
            "competence",
            name="uq_financial_entries_recurrence_competence",
        ),
        CheckConstraint(
            "(recurring_entry_id IS NULL AND competence IS NULL) OR "
            "(recurring_entry_id IS NOT NULL AND competence IS NOT NULL)",
            name="ck_financial_entries_recurrence_pair",
        ),
        CheckConstraint(
            extract("day", column("competence")) == 1,
            name="ck_financial_entries_competence_month",
        ),
        ForeignKeyConstraint(
            ["category_id", "business_id", "type"],
            [
                "financial_categories.id",
                "financial_categories.business_id",
                "financial_categories.type",
            ],
            name="fk_financial_entries_category_business_type",
        ),
        ForeignKeyConstraint(
            ["appointment_id", "business_id"],
            ["appointments.id", "appointments.business_id"],
            name="fk_financial_entries_appointment_business",
        ),
        CheckConstraint(
            "length(description) BETWEEN 1 AND 500 AND description = trim(description)",
            name="ck_financial_entries_description",
        ),
        CheckConstraint(
            "amount > 0 AND amount <= 9999999999.99", name="ck_financial_entries_amount"
        ),
        CheckConstraint(
            "(status = 'PAID' AND paid_at IS NOT NULL) OR (status IN ('PENDING', 'CANCELLED') AND paid_at IS NULL)",
            name="ck_financial_entries_payment",
        ),
        Index(
            "ix_financial_entries_business_due_date", "business_id", "due_date", "id"
        ),
        Index(
            "ix_financial_entries_business_category_type",
            "business_id",
            "category_id",
            "type",
        ),
        Index("ix_financial_entries_business_status", "business_id", "status"),
        Index(
            "ix_financial_entries_business_appointment", "business_id", "appointment_id"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id"), nullable=False
    )
    category_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    type: Mapped[FinancialType] = mapped_column(
        SqlEnum(
            FinancialType,
            native_enum=False,
            create_constraint=True,
            name="ck_financial_entries_type",
        ),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[FinancialEntryStatus] = mapped_column(
        SqlEnum(
            FinancialEntryStatus,
            native_enum=False,
            create_constraint=True,
            name="ck_financial_entries_status",
        ),
        nullable=False,
        default=FinancialEntryStatus.PENDING,
        server_default=text("'PENDING'"),
    )
    appointment_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    recurring_entry_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    competence: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    recurring_entry: Mapped["RecurringEntry | None"] = relationship(
        "RecurringEntry",
        back_populates="entries",
        primaryjoin="and_(FinancialEntry.recurring_entry_id == RecurringEntry.id, FinancialEntry.business_id == RecurringEntry.business_id)",
        foreign_keys=[recurring_entry_id],
    )
    category: Mapped[FinancialCategory] = relationship(
        FinancialCategory,
        back_populates="entries",
        primaryjoin="and_(FinancialEntry.category_id == FinancialCategory.id, FinancialEntry.business_id == FinancialCategory.business_id, FinancialEntry.type == FinancialCategory.type)",
        foreign_keys=[category_id],
    )
    appointment: Mapped[Appointment | None] = relationship(
        Appointment,
        primaryjoin="and_(FinancialEntry.appointment_id == Appointment.id, FinancialEntry.business_id == Appointment.business_id)",
        foreign_keys=[appointment_id],
    )
