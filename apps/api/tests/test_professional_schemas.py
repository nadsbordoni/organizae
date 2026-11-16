from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.modules.business_categories.models import BusinessCategory  # noqa: F401
from app.modules.businesses.models import Business  # noqa: F401
from app.modules.professionals.models import Professional
from app.modules.professionals.schemas import (
    ProfessionalCreate,
    ProfessionalResponse,
    ProfessionalServicesUpdate,
    ProfessionalUpdate,
)
from app.modules.services.models import Service


@pytest.fixture
def professional_payload() -> dict[str, object]:
    return {"business_id": str(uuid4()), "name": "Professional"}


def test_create_defaults_and_normalization(
    professional_payload: dict[str, object],
) -> None:
    professional_payload.update(name="  Professional  ", phone="  85999999999  ")
    professional = ProfessionalCreate(**professional_payload)
    assert professional.name == "Professional"
    assert professional.phone == "85999999999"
    assert professional.business_id.version == 4
    assert professional.description is None
    assert professional.is_active is True
    assert professional.service_ids == []


def test_create_lists_are_independent(professional_payload: dict[str, object]) -> None:
    first = ProfessionalCreate(**professional_payload)
    second = ProfessionalCreate(**professional_payload)
    first.service_ids.append(uuid4())
    assert second.service_ids == []


@pytest.mark.parametrize("field", ["business_id", "name"])
def test_create_requires_mandatory_fields(
    professional_payload: dict[str, object], field: str
) -> None:
    professional_payload.pop(field)
    with pytest.raises(ValidationError):
        ProfessionalCreate(**professional_payload)


@pytest.mark.parametrize(
    "field, value",
    [
        ("business_id", "invalid"),
        ("business_id", 1),
        ("business_id", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"),
        ("name", " "),
        ("name", "a" * 151),
        ("phone", " "),
        ("phone", "1" * 21),
        ("is_active", None),
        ("service_ids", None),
        ("service_ids", ["invalid"]),
        ("service_ids", ["6ba7b810-9dad-11d1-80b4-00c04fd430c8"]),
        ("id", str(uuid4())),
    ],
)
def test_create_rejects_invalid_fields(
    professional_payload: dict[str, object], field: str, value: object
) -> None:
    professional_payload[field] = value
    with pytest.raises(ValidationError):
        ProfessionalCreate(**professional_payload)


def test_create_accepts_distinct_service_ids(
    professional_payload: dict[str, object],
) -> None:
    service_ids = [uuid4(), uuid4()]
    professional_payload["service_ids"] = [
        str(identifier) for identifier in service_ids
    ]
    assert ProfessionalCreate(**professional_payload).service_ids == service_ids


@pytest.mark.parametrize("mixed_representation", [False, True])
def test_create_rejects_duplicate_service_ids(
    professional_payload: dict[str, object], mixed_representation: bool
) -> None:
    identifier = uuid4()
    professional_payload["service_ids"] = [
        identifier,
        str(identifier).upper() if mixed_representation else identifier,
    ]
    with pytest.raises(ValidationError, match="duplicates"):
        ProfessionalCreate(**professional_payload)


def test_update_preserves_omitted_fields_and_allows_clearing_optional_fields() -> None:
    assert ProfessionalUpdate().model_dump(exclude_unset=True) == {}
    assert ProfessionalUpdate(phone=None, description=None).model_dump(
        exclude_unset=True
    ) == {"phone": None, "description": None}
    assert ProfessionalUpdate(is_active=False).model_dump(exclude_unset=True) == {
        "is_active": False
    }


@pytest.mark.parametrize("field", ["name", "is_active"])
def test_update_rejects_null_for_required_fields(field: str) -> None:
    with pytest.raises(ValidationError, match=f"{field} cannot be null"):
        ProfessionalUpdate(**{field: None})


@pytest.mark.parametrize(
    "payload",
    [
        {"name": " "},
        {"name": "a" * 151},
        {"phone": "1" * 21},
        {"business_id": str(uuid4())},
        {"id": str(uuid4())},
        {"service_ids": []},
    ],
)
def test_profile_update_rejects_invalid_fields_and_relationship_changes(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ProfessionalUpdate(**payload)


def test_services_update_replaces_entire_set_and_accepts_empty_list() -> None:
    service_ids = [uuid4(), uuid4()]
    assert ProfessionalServicesUpdate(service_ids=service_ids).model_dump() == {
        "service_ids": service_ids
    }
    assert ProfessionalServicesUpdate(service_ids=[]).model_dump(
        exclude_unset=True
    ) == {"service_ids": []}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"service_ids": None},
        {"service_ids": ["invalid"]},
        {"service_ids": [], "business_id": str(uuid4())},
    ],
)
def test_services_update_requires_a_valid_complete_list(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ProfessionalServicesUpdate(**payload)


def test_services_update_rejects_duplicate_ids_after_uuid_normalization() -> None:
    identifier = uuid4()
    with pytest.raises(ValidationError, match="duplicates"):
        ProfessionalServicesUpdate(service_ids=[identifier, str(identifier).upper()])


@pytest.mark.parametrize("with_services", [False, True])
def test_response_serializes_orm_attributes_and_related_services(
    with_services: bool,
) -> None:
    business_id = uuid4()
    service = Service(
        id=uuid4(),
        business_id=business_id,
        name="Haircut",
        price=Decimal("25.50"),
        duration_minutes=30,
        description=None,
        is_active=True,
    )
    professional = Professional(
        id=uuid4(),
        business_id=business_id,
        name="Professional",
        phone=None,
        description=None,
        is_active=True,
        services=[service] if with_services else [],
    )

    response = ProfessionalResponse.model_validate(professional)

    assert isinstance(response.id, UUID)
    assert response.id == professional.id
    assert response.business_id == business_id
    assert response.phone is None
    serialized = response.model_dump(mode="json")
    assert serialized["id"] == str(professional.id)
    assert serialized["business_id"] == str(business_id)
    if with_services:
        assert serialized["services"][0]["id"] == str(service.id)
        assert serialized["services"][0]["price"] == "25.50"
    else:
        assert serialized["services"] == []
