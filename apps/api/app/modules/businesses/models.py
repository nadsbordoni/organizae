from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.modules.business_categories.models import BusinessCategory
    from app.modules.professionals.models import Professional
    from app.modules.services.models import Service


class ServiceMode(str, Enum):
    PRESENCIAL = "PRESENCIAL"
    ONLINE = "ONLINE"
    HIBRIDO = "HIBRIDO"


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("business_categories.id"), nullable=False
    )
    whatsapp: Mapped[str] = mapped_column(String(20), nullable=False)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_link: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    service_mode: Mapped[ServiceMode] = mapped_column(
        SqlEnum(ServiceMode), nullable=False
    )

    category: Mapped["BusinessCategory"] = relationship(
        "BusinessCategory", back_populates="businesses"
    )

    professionals: Mapped[list["Professional"]] = relationship(
        "Professional", back_populates="business"
    )

    services: Mapped[list["Service"]] = relationship(
        "Service", back_populates="business"
    )
