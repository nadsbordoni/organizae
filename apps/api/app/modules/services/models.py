from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.modules.services.associations import professional_services

if TYPE_CHECKING:
    from app.modules.businesses.models import Business
    from app.modules.professionals.models import Professional


class Service(Base):
    __tablename__ = "services"

    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_services_price"),
        CheckConstraint("duration_minutes > 0", name="ck_services_duration"),
        UniqueConstraint("id", "business_id", name="uq_services_id_business"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )

    business_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )

    business: Mapped["Business"] = relationship("Business", back_populates="services")

    professionals: Mapped[list["Professional"]] = relationship(
        "Professional", secondary=professional_services, back_populates="services"
    )
