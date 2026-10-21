from sqlalchemy import (
    Table,
    Column,
    Integer,
    ForeignKeyConstraint,
)

from app.db.base import Base


professional_services = Table(
    "professional_services",
    Base.metadata,

    Column("professional_id", Integer, primary_key=True),
    Column("service_id", Integer, primary_key=True),
    Column("business_id", Integer, nullable=False),

    ForeignKeyConstraint(
        ["professional_id", "business_id"],
        ["professionals.id", "professionals.business_id"],
        name="fk_professional_services_professional_business"
    ),

    ForeignKeyConstraint(
        ["service_id", "business_id"],
        ["services.id", "services.business_id"],
        name="fk_professional_services_service_business"
    ),
)