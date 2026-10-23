from sqlalchemy import (
    Column,
    ForeignKeyConstraint,
    Table,
    Uuid,
)

from app.db.base import Base

professional_services = Table(
    "professional_services",
    Base.metadata,
    Column("professional_id", Uuid, primary_key=True),
    Column("service_id", Uuid, primary_key=True),
    Column("business_id", Uuid, nullable=False),
    ForeignKeyConstraint(
        ["professional_id", "business_id"],
        ["professionals.id", "professionals.business_id"],
        name="fk_professional_services_professional_business",
    ),
    ForeignKeyConstraint(
        ["service_id", "business_id"],
        ["services.id", "services.business_id"],
        name="fk_professional_services_service_business",
    ),
)
