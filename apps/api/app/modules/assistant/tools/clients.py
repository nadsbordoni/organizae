from uuid import UUID

from app.modules.clients.exceptions import ClientNotFoundError
from app.modules.clients.schemas import ClientResponse
from app.modules.clients.service import ClientService


def list_clients(
    service: ClientService,
    business_id: UUID,
    *,
    search: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> dict[str, object]:
    clients = service.list(
        business_id=business_id, search=search, offset=offset, limit=limit
    )
    return {
        "items": [
            ClientResponse.model_validate(client).model_dump(
                mode="json", exclude={"business_id"}
            )
            for client in clients
        ],
        "offset": offset,
        "limit": limit,
    }


def get_client(
    service: ClientService, business_id: UUID, *, record_id: UUID
) -> dict[str, object]:
    try:
        client = service.get_by_id(record_id, business_id=business_id)
    except ClientNotFoundError:
        return {"error": "Cliente não encontrado na empresa autenticada."}
    return ClientResponse.model_validate(client).model_dump(
        mode="json", exclude={"business_id"}
    )
