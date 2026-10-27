from uuid import UUID

from app.modules.services.service import ServiceService


def list_services(
    service: ServiceService,
    business_id: UUID,
    *,
    offset: int = 0,
    limit: int = 20,
) -> dict[str, object]:
    services = service.list(business_id=business_id, offset=offset, limit=limit)
    return {
        "items": [
            {
                "name": item.name,
                "description": item.description,
                "price": str(item.price),
                "duration_minutes": item.duration_minutes,
                "is_active": item.is_active,
            }
            for item in services
        ],
        "offset": offset,
        "limit": limit,
    }
