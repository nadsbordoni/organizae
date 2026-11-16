from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.modules.services.associations import professional_services
from app.modules.services.models import Service

if TYPE_CHECKING:
    from app.modules.businesses.models import Business


class Professional(Base):
    __table_args__ = (
        UniqueConstraint("id", "business_id", name="uq_professionals_id_business"),
    )
    __tablename__ = "professionals"

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )

    business_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)

    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    business: Mapped["Business"] = relationship(
        "Business", back_populates="professionals"
    )

    services: Mapped[list["Service"]] = relationship(
        "Service", secondary=professional_services, back_populates="professionals"
    )
