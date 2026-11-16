from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.appointments.models import Appointment
from app.modules.clients.exceptions import (
    ClientConflictError,
    ClientNotFoundError,
    InvalidClientPaginationError,
)
from app.modules.clients.models import Client
from app.modules.clients.repository import ClientRepository
from app.modules.clients.schemas import ClientCreate, ClientUpdate


class ClientService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = ClientRepository(session)

    def create(self, client_data: ClientCreate, *, business_id: UUID) -> Client:
        with self._transaction():
            self._ensure_unique_phone(client_data.phone, business_id=business_id)
            client = self.repository.create(client_data, business_id=business_id)
            self.session.commit()
            self.session.refresh(client)
        return client

    def get_by_id(self, client_id: UUID, *, business_id: UUID) -> Client:
        client = self.repository.get_by_id(client_id, business_id=business_id)
        if client is None:
            raise ClientNotFoundError("Client not found")
        return client

    def list(
        self,
        *,
        business_id: UUID,
        search: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Client]:
        self._validate_pagination(offset, limit)
        return self.repository.list(
            business_id=business_id, search=search, offset=offset, limit=limit
        )

    def update(
        self, client_id: UUID, client_data: ClientUpdate, *, business_id: UUID
    ) -> Client:
        with self._transaction():
            client = self.get_by_id(client_id, business_id=business_id)
            if client_data.phone is not None and client_data.phone != client.phone:
                self._ensure_unique_phone(client_data.phone, business_id=business_id)
            client = self.repository.update(client, client_data)
            self.session.commit()
            self.session.refresh(client)
        return client

    def list_appointments(
        self,
        client_id: UUID,
        *,
        business_id: UUID,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Appointment]:
        self._validate_pagination(offset, limit)
        client = self.get_by_id(client_id, business_id=business_id)
        return self.repository.list_appointments(client, offset=offset, limit=limit)

    def _ensure_unique_phone(self, phone: str, *, business_id: UUID) -> None:
        if self.repository.get_by_phone(phone, business_id=business_id) is not None:
            raise ClientConflictError("A client with this phone already exists")

    def _validate_pagination(self, offset: int, limit: int) -> None:
        if offset < 0 or not 1 <= limit <= 100:
            raise InvalidClientPaginationError(
                "offset must be non-negative and limit must be between 1 and 100"
            )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            yield
        except IntegrityError as exc:
            self.session.rollback()
            raise ClientConflictError(
                "Operation conflicts with existing clients or related data"
            ) from exc
        except Exception:
            self.session.rollback()
            raise
