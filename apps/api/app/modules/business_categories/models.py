from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

class BusinessCategory(Base):
    __tablename__ = "business_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    businesses: Mapped[list["Business"]] = relationship(
        "Business",
        back_populates="category"
    )