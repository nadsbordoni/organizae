from uuid import UUID

from app.modules.businesses.service import BusinessService


def get_business_info(service: BusinessService, business_id: UUID) -> dict[str, object]:
    business = service.get_by_id(business_id)
    return {
        "name": business.name,
        "description": business.description,
        "service_mode": business.service_mode.value,
    }
