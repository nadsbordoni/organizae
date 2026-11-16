from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.modules.financial_entries.models import FinancialEntry


class FinancialType(str, Enum):
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


class FinancialCategory(Base):
    __tablename__ = "financial_categories"
    __table_args__ = (
        UniqueConstraint(
            "id", "business_id", "type", name="uq_financial_categories_id_business_type"
        ),
        CheckConstraint(
            "length(name) BETWEEN 1 AND 150 AND name = trim(name)",
            name="ck_financial_categories_name",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    type: Mapped[FinancialType] = mapped_column(
        SqlEnum(
            FinancialType,
            native_enum=False,
            create_constraint=True,
            name="ck_financial_categories_type",
        ),
        nullable=False,
    )
    entries: Mapped[list["FinancialEntry"]] = relationship(
        "FinancialEntry",
        back_populates="category",
        primaryjoin="and_(FinancialCategory.id == FinancialEntry.category_id, FinancialCategory.business_id == FinancialEntry.business_id, FinancialCategory.type == FinancialEntry.type)",
        foreign_keys="FinancialEntry.category_id",
        passive_deletes="all",
    )


Index(
    "uq_financial_categories_business_name_type",
    FinancialCategory.business_id,
    func.lower(FinancialCategory.name),
    FinancialCategory.type,
    unique=True,
)
