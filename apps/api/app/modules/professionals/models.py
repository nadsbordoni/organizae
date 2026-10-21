from sqlalchemy import String, Text, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.modules.services.associations import professional_services
from app.modules.services.models import Service


class Professional(Base):
    __table_args__ = (
        UniqueConstraint("id", "business_id", name="uq_professionals_id_business"),
    )
    __tablename__ = "professionals"

    id: Mapped[int] = mapped_column(primary_key=True)

    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id"),
        nullable=False
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)

    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False
    )

    business: Mapped["Business"] = relationship(
        "Business",
        back_populates="professionals"
    )

    services: Mapped[list["Service"]] = relationship(
        "Service",
        secondary=professional_services,
        back_populates="professionals"
    )