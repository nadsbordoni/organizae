from uuid import UUID

from app.modules.professionals.exceptions import ProfessionalNotFoundError
from app.modules.professionals.service import ProfessionalService
from app.modules.services.service import ServiceService


def list_professionals(
    service: ProfessionalService,
    business_id: UUID,
    *,
    is_active: bool | None = None,
    offset: int = 0,
    limit: int = 20,
) -> dict[str, object]:
    professionals = service.list(
        business_id=business_id,
        is_active=is_active,
        offset=offset,
        limit=limit,
    )
    return {
        "items": [
            {
                **({"id": str(item.id)} if item.id is not None else {}),
                "name": item.name,
                "description": item.description,
                "is_active": item.is_active,
            }
            for item in professionals
        ],
        "offset": offset,
        "limit": limit,
    }


def get_professional_services(
    service: ProfessionalService,
    business_id: UUID,
    *,
    record_id: UUID,
    offset: int = 0,
    limit: int = 20,
) -> dict[str, object]:
    try:
        professional = service.get_by_id(record_id, business_id=business_id)
    except ProfessionalNotFoundError:
        return {"error": "Profissional não encontrado na empresa autenticada."}
    services = sorted(professional.services, key=lambda item: (item.name, item.id))
    return {
        "professional_id": str(professional.id),
        "professional_name": professional.name,
        "items": [
            {
                "id": str(item.id),
                "name": item.name,
                "price": str(item.price),
                "duration_minutes": item.duration_minutes,
                "is_active": item.is_active,
            }
            for item in services[offset : offset + limit]
        ],
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < len(services),
    }


def get_service_previews(
    service: ServiceService, business_id: UUID, service_ids: list[UUID]
) -> list[dict[str, str]]:
    services = [
        service.get_by_id(service_id, business_id=business_id)
        for service_id in service_ids
    ]
    return [{"id": str(item.id), "name": item.name} for item in services]
