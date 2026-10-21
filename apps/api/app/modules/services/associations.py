from sqlalchemy import Table, Column, Integer, ForeignKey

from app.db.base import Base

#Tabela associativa para o relacionamento N-N entre profissionais e serviços
professional_services = Table(
    "professional_services",
    Base.metadata,

    Column(
        "professional_id",
        Integer,
        ForeignKey("professionals.id"),
        primary_key=True
    ),

    Column(
        "service_id",
        Integer,
        ForeignKey("services.id"),
        primary_key=True
    )
)