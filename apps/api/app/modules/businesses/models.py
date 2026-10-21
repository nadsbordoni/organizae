from enum import Enum

from sqlalchemy import String, Text, ForeignKey, Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

class ServiceMode(str, Enum):
    IN_PERSON = "in_person"
    ONLINE = "online"
    BOTH = "both"


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("business_categories.id"),
        nullable=False
    )
    whatsapp: Mapped[str] = mapped_column(String(20), nullable=False)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_link: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    service_mode: Mapped[ServiceMode] = mapped_column(
        SqlEnum(ServiceMode),
        nullable=False
    )

    category: Mapped["BusinessCategory"] = relationship(
        "BusinessCategory",
        back_populates="businesses"
    )

    professionals: Mapped[list["Professional"]] = relationship(
    "Professional",
    back_populates="business"
    )

    services: Mapped[list["Service"]] = relationship(
    "Service",
    back_populates="business"
    )