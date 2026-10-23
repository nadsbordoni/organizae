from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.services.schemas import ServiceCreate, ServiceResponse, ServiceUpdate


@pytest.fixture
def service_payload() -> dict[str, object]:
    return {
        "business_id": str(uuid4()),
        "name": "Haircut",
        "price": "25.50",
        "duration_minutes": 30,
    }


def test_create_defaults_and_normalization(service_payload: dict[str, object]) -> None:
    service_payload["name"] = "  Haircut  "
    service = ServiceCreate(**service_payload)

    assert service.name == "Haircut"
    assert service.price == Decimal("25.50")
    assert service.business_id.version == 4
    assert service.description is None
    assert service.is_active is True


@pytest.mark.parametrize("price", ["0", "0.01", "99999999.99"])
def test_create_accepts_valid_price_limits(
    service_payload: dict[str, object], price: str
) -> None:
    service_payload["price"] = price
    assert ServiceCreate(**service_payload).price == Decimal(price)


@pytest.mark.parametrize(
    "field, value",
    [
        ("business_id", 1),
        ("business_id", "invalid"),
        ("business_id", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"),
        ("name", "  "),
        ("name", "a" * 151),
        ("price", "-0.01"),
        ("price", "100000000.00"),
        ("price", "1.001"),
        ("price", "NaN"),
        ("price", "Infinity"),
        ("duration_minutes", 0),
        ("duration_minutes", -1),
        ("duration_minutes", 1.5),
        ("is_active", None),
        ("id", str(uuid4())),
        ("professionals", []),
    ],
)
def test_create_rejects_invalid_fields(
    service_payload: dict[str, object], field: str, value: object
) -> None:
    service_payload[field] = value
    with pytest.raises(ValidationError):
        ServiceCreate(**service_payload)


@pytest.mark.parametrize("field", ["business_id", "name", "price", "duration_minutes"])
def test_create_requires_mandatory_fields(
    service_payload: dict[str, object], field: str
) -> None:
    service_payload.pop(field)
    with pytest.raises(ValidationError):
        ServiceCreate(**service_payload)


def test_update_preserves_omitted_fields_and_explicit_null() -> None:
    assert ServiceUpdate().model_dump(exclude_unset=True) == {}
    assert ServiceUpdate(description=None).model_dump(exclude_unset=True) == {
        "description": None
    }
    assert ServiceUpdate(is_active=False).model_dump(exclude_unset=True) == {
        "is_active": False
    }
    assert ServiceUpdate(price="0").model_dump(exclude_unset=True) == {
        "price": Decimal(0)
    }


@pytest.mark.parametrize("field", ["name", "price", "duration_minutes", "is_active"])
def test_update_rejects_null_for_required_fields(field: str) -> None:
    with pytest.raises(ValidationError, match=f"{field} cannot be null"):
        ServiceUpdate(**{field: None})


@pytest.mark.parametrize(
    "payload",
    [
        {"business_id": str(uuid4())},
        {"id": str(uuid4())},
        {"name": " "},
        {"price": "-1"},
        {"price": "1.001"},
        {"price": "100000000.00"},
        {"duration_minutes": 0},
    ],
)
def test_update_rejects_invalid_changes(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ServiceUpdate(**payload)


def test_response_reads_attributes_and_serializes_uuid_and_decimal(
    service_payload: dict[str, object],
) -> None:
    service_id = uuid4()
    attributes = ServiceCreate(**service_payload).model_dump()
    response = ServiceResponse.model_validate(
        SimpleNamespace(id=service_id, **attributes)
    )

    assert response.id == service_id
    assert response.price == Decimal("25.50")
    assert response.model_dump(mode="json") == {
        **service_payload,
        "id": str(service_id),
        "description": None,
        "is_active": True,
    }
