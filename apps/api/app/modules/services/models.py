from decimal import Decimal

from sqlalchemy import String, Text, Numeric, Integer, Boolean, ForeignKey, CheckConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

from app.modules.services.associations import professional_services


class Service(Base):
    __tablename__ = "services"

    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_services_price"),
        CheckConstraint("duration_minutes > 0", name="ck_services_duration"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id"),
        nullable=False
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=text("true"),
        nullable=False
    )

    business: Mapped["Business"] = relationship(
        "Business",
        back_populates="services"
    )
    
    professionals: Mapped[list["Professional"]] = relationship(
        "Professional",
        secondary=professional_services,
        back_populates="services"
    )