from uuid import UUID

from app.modules.professionals.service import ProfessionalService


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
                "name": item.name,
                "description": item.description,
                "is_active": item.is_active,
            }
            for item in professionals
        ],
        "offset": offset,
        "limit": limit,
    }
