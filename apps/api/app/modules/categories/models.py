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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.modules.services.models import Service


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("id", "business_id", name="uq_categories_id_business"),
        CheckConstraint(
            "length(name) BETWEEN 1 AND 150 AND name = trim(name)",
            name="ck_categories_name",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)

    services: Mapped[list["Service"]] = relationship(
        "Service",
        back_populates="category",
        primaryjoin="and_(Category.id == Service.category_id, Category.business_id == Service.business_id)",
        foreign_keys="Service.category_id",
        passive_deletes="all",
    )


Index(
    "uq_categories_business_name",
    Category.business_id,
    func.lower(Category.name),
    unique=True,
)
