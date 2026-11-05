from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.appointments.models import Appointment, AppointmentStatus
from app.modules.clients.models import Client
from app.modules.clients.schemas import ClientCreate, ClientUpdate


class ClientRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, client_data: ClientCreate, *, business_id: UUID) -> Client:
        client = Client(business_id=business_id, **client_data.model_dump())
        self.session.add(client)
        self.session.flush()
        return client

    def get_by_id(self, client_id: UUID, *, business_id: UUID) -> Client | None:
        statement = select(Client).where(
            Client.id == client_id, Client.business_id == business_id
        )
        return self.session.scalar(statement)

    def get_by_phone(self, phone: str, *, business_id: UUID) -> Client | None:
        statement = select(Client).where(
            Client.phone == phone, Client.business_id == business_id
        )
        return self.session.scalar(statement)

    def list(
        self,
        *,
        business_id: UUID,
        search: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Client]:
        statement = select(Client).where(Client.business_id == business_id)
        if search and (term := search.strip()):
            filters = [
                Client.name.icontains(term, autoescape=True),
                Client.email.icontains(term, autoescape=True),
            ]
            if digits := re.sub(r"[^0-9]", "", term):
                filters.append(Client.phone.contains(digits, autoescape=True))
            statement = statement.where(or_(*filters))
        statement = (
            statement.order_by(Client.name, Client.id).offset(offset).limit(limit)
        )
        return list(self.session.scalars(statement).all())

    def update(self, client: Client, client_data: ClientUpdate) -> Client:
        for field_name, field_value in client_data.model_dump(
            exclude_unset=True
        ).items():
            setattr(client, field_name, field_value)
        self.session.flush()
        return client

    def list_appointments(
        self, client: Client, *, offset: int = 0, limit: int = 100
    ) -> list[Appointment]:
        # Bookings store a phone snapshot; the appointments schema stays unchanged.
        statement = (
            select(Appointment)
            .where(
                Appointment.business_id == client.business_id,
                Appointment.customer_phone == client.phone,
                Appointment.status != AppointmentStatus.BLOCKED,
            )
            .order_by(Appointment.starts_at.desc(), Appointment.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement).all())
