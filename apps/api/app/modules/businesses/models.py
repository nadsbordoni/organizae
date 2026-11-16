from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.modules.business_categories.models import BusinessCategory
    from app.modules.professionals.models import Professional
    from app.modules.services.models import Service
    from app.modules.users.models import User


class ServiceMode(str, Enum):
    PRESENCIAL = "PRESENCIAL"
    ONLINE = "ONLINE"
    HIBRIDO = "HIBRIDO"


class Business(Base):
    __tablename__ = "businesses"
    __table_args__ = (
        # The slug format check (regex) lives only in the migration, because the
        # SQLite used by the tests has no "~" operator.
        UniqueConstraint("slug", name="uq_businesses_slug"),
        # A published page must always be reachable by its slug.
        CheckConstraint(
            "NOT is_published OR (slug IS NOT NULL AND published_at IS NOT NULL)",
            name="ck_businesses_published_page",
        ),
    )

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
    instagram: Mapped[str | None] = mapped_column(String(30), nullable=True)
    slug: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_published: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
    
    user: Mapped["User | None"] = relationship(
    "User",
    back_populates="business",
    uselist=False,
)
