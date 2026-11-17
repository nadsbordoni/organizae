from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.modules.financial_categories.models import FinancialCategory, FinancialType

if TYPE_CHECKING:
    from app.modules.financial_entries.models import FinancialEntry


class RecurringEntry(Base):
    __tablename__ = "recurring_entries"
    __table_args__ = (
        UniqueConstraint("id", "business_id", name="uq_recurring_entries_id_business"),
        ForeignKeyConstraint(
            ["category_id", "business_id", "type"],
            [
                "financial_categories.id",
                "financial_categories.business_id",
                "financial_categories.type",
            ],
            name="fk_recurring_entries_category_business_type",
        ),
        CheckConstraint(
            "length(description) BETWEEN 1 AND 500 AND description = trim(description)",
            name="ck_recurring_entries_description",
        ),
        CheckConstraint(
            "amount > 0 AND amount <= 9999999999.99", name="ck_recurring_entries_amount"
        ),
        CheckConstraint(
            "due_day BETWEEN 1 AND 31", name="ck_recurring_entries_due_day"
        ),
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_recurring_entries_dates",
        ),
        Index("ix_recurring_entries_business_active", "business_id", "is_active", "id"),
        Index(
            "ix_recurring_entries_business_category_type",
            "business_id",
            "category_id",
            "type",
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
            name="ck_recurring_entries_type",
        ),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    due_day: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    category: Mapped[FinancialCategory] = relationship(
        FinancialCategory,
        primaryjoin="and_(RecurringEntry.category_id == FinancialCategory.id, RecurringEntry.business_id == FinancialCategory.business_id, RecurringEntry.type == FinancialCategory.type)",
        foreign_keys=[category_id],
    )
    entries: Mapped[list["FinancialEntry"]] = relationship(
        "FinancialEntry",
        back_populates="recurring_entry",
        primaryjoin="and_(RecurringEntry.id == FinancialEntry.recurring_entry_id, RecurringEntry.business_id == FinancialEntry.business_id)",
        foreign_keys="FinancialEntry.recurring_entry_id",
        passive_deletes="all",
    )
