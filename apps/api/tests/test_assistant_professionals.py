from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from google.genai import types
from pydantic import SecretStr
from sqlalchemy import delete, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_assistant_tools import mock_conversation, sdk_reply
from test_clients import (
    auth_headers,
    business_a,
    business_b,
    client,
    database,
    inactive_user,
    owner_b,
    password_hash,
    professional_a,
    professional_b,
    service_a,
    service_b,
    unassigned_user,
)

from app.core.config import settings
from app.main import app
from app.modules.assistant.actions import action_repository
from app.modules.assistant.providers.base import ProviderReply, ToolCall
from app.modules.assistant.providers.gemini import GeminiProvider
from app.modules.assistant.router import get_assistant_provider
from app.modules.professionals.models import Professional
from app.modules.professionals.repository import ProfessionalRepository
from app.modules.services.associations import professional_services
from app.modules.services.models import Service

__all__ = ["client", "database", "password_hash"]
second_service_id = uuid4()


@pytest.fixture(autouse=True)
def assistant_setup(database, monkeypatch):
    action_repository.actions.clear()
    action_repository.requests.clear()
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "ASSISTANT_WRITES_ENABLED", True)
    with Session(database) as session:
        session.add(
            Service(
                id=second_service_id,
                business_id=business_a,
                name="Beard",
                price=15,
                duration_minutes=15,
            )
        )
        session.execute(
            insert(professional_services),
            [
                {
                    "business_id": business_a,
                    "professional_id": professional_a,
                    "service_id": service_a,
                },
                {
                    "business_id": business_b,
                    "professional_id": professional_b,
                    "service_id": service_b,
                },
            ],
        )
        session.commit()
    yield
    action_repository.actions.clear()
    action_repository.requests.clear()
    app.dependency_overrides.pop(get_assistant_provider, None)


def chat_tool(client, operation, arguments, headers=None):
    provider, conversation = mock_conversation(
        [
            ProviderReply(calls=[ToolCall(operation, arguments)]),
            ProviderReply(text="Consulta concluída."),
        ]
    )
    app.dependency_overrides[get_assistant_provider] = lambda: provider
    response = client.post(
        "/api/v1/assistant/chat",
        headers=headers or auth_headers(),
        json={"message": "Serviços dos profissionais"},
    )
    return response, conversation


def replacement(service_ids, record_id=professional_a):
    return {
        "record_id": str(record_id),
        "data": {"service_ids": [str(identifier) for identifier in service_ids]},
    }


def prepare(client, service_ids=None):
    response, _ = chat_tool(
        client,
        "replace_professional_services",
        replacement(
            [service_a, second_service_id] if service_ids is None else service_ids
        ),
    )
    assert response.status_code == 200, response.text
    return response.json()["pending_actions"][0]["id"]


def decide(client, action_id, decision="confirm", headers=None):
    return client.post(
        f"/api/v1/assistant/actions/{action_id}/{decision}",
        headers=headers or auth_headers(),
        **({"json": {"decision": "confirm"}} if decision == "confirm" else {}),
    )


def links(database, professional_id=professional_a):
    with Session(database) as session:
        return set(
            session.scalars(
                select(professional_services.c.service_id).where(
                    professional_services.c.professional_id == professional_id,
                )
            )
        )


def test_existing_create_contract_persists_services_only_after_confirmation(
    client, database
):
    response, _ = chat_tool(
        client,
        "create_professional",
        {
            "name": "New professional",
            "service_ids": [str(service_a), str(second_service_id)],
        },
    )
    pending = response.json()["pending_actions"][0]
    assert pending["preview"]["professional_name"] == "New professional"
    assert {item["name"] for item in pending["preview"]["services"]} == {
        "Haircut",
        "Beard",
    }
    with Session(database) as session:
        assert (
            session.scalar(
                select(Professional).where(Professional.name == "New professional")
            )
            is None
        )
    assert decide(client, pending["id"]).status_code == 200
    assert decide(client, pending["id"]).status_code == 409
    with Session(database) as session:
        professional = session.scalar(
            select(Professional).where(Professional.name == "New professional")
        )
        assert professional.business_id == business_a
        assert {item.id for item in professional.services} == {
            service_a,
            second_service_id,
        }
        rows = session.execute(
            select(professional_services).where(
                professional_services.c.professional_id == professional.id,
            )
        ).all()
        assert len(rows) == 2
        assert all(row.business_id == business_a for row in rows)


def test_creation_without_services_preserves_existing_optional_contract(
    client, database
):
    api_response = client.post(
        "/api/v1/professionals",
        headers=auth_headers(),
        json={"name": "API without services"},
    )
    assert api_response.status_code == 201
    assert api_response.json()["services"] == []
    response, _ = chat_tool(
        client, "create_professional", {"name": "No services", "service_ids": []}
    )
    pending = response.json()["pending_actions"][0]
    assert pending["preview"]["services"] == []
    assert "sem serviços" in pending["preview"]["notice"]
    assert decide(client, pending["id"]).status_code == 200
    with Session(database) as session:
        professional = session.scalar(
            select(Professional).where(Professional.name == "No services")
        )
        assert professional.services == []
        assert links(database, professional.id) == set()


def test_replace_services_uses_full_set_and_never_writes_before_confirmation(
    client, database
):
    action_id = prepare(client)
    assert links(database) == {service_a}
    assert decide(client, action_id).status_code == 200
    assert links(database) == {service_a, second_service_id}
    assert links(database, professional_b) == {service_b}
    action_id = prepare(client, [second_service_id])
    assert links(database) == {service_a, second_service_id}
    assert decide(client, action_id).status_code == 200
    assert links(database) == {second_service_id}
    assert links(database, professional_b) == {service_b}


def test_replacing_same_set_twice_does_not_duplicate_associations(client, database):
    for _ in range(2):
        assert decide(client, prepare(client)).status_code == 200
    with Session(database) as session:
        rows = session.execute(
            select(professional_services).where(
                professional_services.c.professional_id == professional_a,
            )
        ).all()
        assert len(rows) == 2
        assert {row.service_id for row in rows} == {service_a, second_service_id}


def test_empty_list_clears_only_confirmed_professional_links(client, database):
    response, _ = chat_tool(client, "replace_professional_services", replacement([]))
    pending = response.json()["pending_actions"][0]
    assert pending["preview"]["services"] == []
    assert "todos" in pending["preview"]["notice"]
    assert links(database) == {service_a}
    assert decide(client, pending["id"]).status_code == 200
    assert links(database) == set()
    assert links(database, professional_b) == {service_b}
    with Session(database) as session:
        assert session.get(Professional, professional_a) is not None


@pytest.mark.parametrize(
    "operation", ["create_professional", "replace_professional_services"]
)
@pytest.mark.parametrize(
    "service_ids",
    [
        [service_a, service_a],
        [service_a, str(service_a).upper()],
        [service_a, service_b],
        [service_a, uuid4()],
        ["invalid"],
    ],
)
def test_invalid_service_ids_never_prepare_or_change_records(
    client, database, operation, service_ids
):
    arguments = (
        {
            "name": "Rejected",
            "service_ids": [str(identifier) for identifier in service_ids],
        }
        if operation == "create_professional"
        else replacement(service_ids)
    )
    response, conversation = chat_tool(client, operation, arguments)
    assert response.status_code == 200
    assert not response.json().get("pending_actions")
    assert "error" in conversation.generate.call_args.args[0][0].response
    assert not action_repository.actions
    assert links(database) == {service_a}
    with Session(database) as session:
        assert (
            session.scalar(select(Professional).where(Professional.name == "Rejected"))
            is None
        )


@pytest.mark.parametrize("record_id", [professional_b, uuid4()])
def test_replacement_cannot_target_missing_or_foreign_professional(
    client, database, record_id
):
    response, conversation = chat_tool(
        client, "replace_professional_services", replacement([service_a], record_id)
    )
    assert response.status_code == 200
    assert "error" in conversation.generate.call_args.args[0][0].response
    assert not action_repository.actions
    assert links(database, professional_b) == {service_b}


def test_service_query_returns_only_professionals_actual_links_with_pagination(
    client, database
):
    assert decide(client, prepare(client)).status_code == 200
    response, conversation = chat_tool(
        client,
        "get_professional_services",
        {
            "record_id": str(professional_a),
            "limit": 1,
        },
    )
    assert response.status_code == 200
    result = conversation.generate.call_args.args[0][0].response
    assert result["professional_id"] == str(professional_a)
    assert result["professional_name"] == "Professional"
    assert result["items"] == [
        {
            "id": str(second_service_id),
            "name": "Beard",
            "price": "15.00",
            "duration_minutes": 15,
            "is_active": True,
        }
    ]
    assert result["has_more"] is True
    assert "business_id" not in str(result)
    assert str(service_b) not in str(result)
    _, conversation = chat_tool(
        client,
        "get_professional_services",
        {
            "record_id": str(professional_a),
            "offset": 1,
            "limit": 1,
        },
    )
    result = conversation.generate.call_args.args[0][0].response
    assert result["items"][0]["id"] == str(service_a)
    assert result["has_more"] is False


def test_read_without_links_returns_empty_list_and_performs_no_write(client, database):
    with Session(database) as session:
        session.execute(
            delete(professional_services).where(
                professional_services.c.professional_id == professional_a
            )
        )
        session.commit()
    with patch.object(
        Session, "commit", autospec=True, side_effect=Session.commit
    ) as commit:
        # Conversation persistence is the only commit during a read-only chat.
        _, conversation = chat_tool(
            client, "get_professional_services", {"record_id": str(professional_a)}
        )
    assert conversation.generate.call_args.args[0][0].response["items"] == []
    assert commit.call_count == 1
    assert links(database) == set()


@pytest.mark.parametrize("record_id", [professional_b, uuid4()])
def test_query_does_not_disclose_foreign_or_missing_professionals(client, record_id):
    response, conversation = chat_tool(
        client, "get_professional_services", {"record_id": str(record_id)}
    )
    assert response.status_code == 200
    assert conversation.generate.call_args.args[0][0].response == {
        "error": "Profissional não encontrado na empresa autenticada.",
    }


@pytest.mark.parametrize(
    "fields",
    [
        {"business_id": str(business_b)},
        {"limit": 101},
        {"limit": True},
        {"offset": -1},
        {"record_id": "invalid"},
    ],
)
def test_query_rejects_untrusted_tenant_and_invalid_pagination(client, fields):
    response, _ = chat_tool(
        client,
        "get_professional_services",
        {"record_id": str(professional_a), **fields},
    )
    assert response.status_code == 502


@pytest.mark.parametrize(
    "operation,fields",
    [
        ("create_professional", {"name": "Rejected", "business_id": str(business_b)}),
        (
            "replace_professional_services",
            {**replacement([]), "business_id": str(business_b)},
        ),
        (
            "replace_professional_services",
            {
                "record_id": str(professional_a),
                "data": {"service_ids": [], "business_id": str(business_b)},
            },
        ),
        (
            "replace_professional_services",
            {"record_id": str(professional_a), "data": {}},
        ),
    ],
)
def test_write_schema_rejects_tenant_injection_and_missing_full_set(
    client, database, operation, fields
):
    response, _ = chat_tool(client, operation, fields)
    assert not response.json().get("pending_actions")
    assert not action_repository.actions
    assert links(database) == {service_a}


@pytest.mark.parametrize("change", ["delete", "move"])
@pytest.mark.parametrize(
    "operation", ["create_professional", "replace_professional_services"]
)
def test_confirmation_revalidates_services_after_preparation(
    client, database, change, operation
):
    arguments = (
        {"name": "Rejected", "service_ids": [str(second_service_id)]}
        if operation == "create_professional"
        else replacement([second_service_id])
    )
    response, _ = chat_tool(client, operation, arguments)
    action_id = response.json()["pending_actions"][0]["id"]
    with Session(database) as session:
        service = session.get(Service, second_service_id)
        if change == "delete":
            session.delete(service)
        else:
            service.business_id = business_b
        session.commit()
    assert decide(client, action_id).status_code == 422
    assert action_repository.actions[UUID(action_id)].state == "failed"
    assert decide(client, action_id).status_code == 409
    assert links(database) == {service_a}
    with Session(database) as session:
        assert (
            session.scalar(select(Professional).where(Professional.name == "Rejected"))
            is None
        )


@pytest.mark.parametrize("state", ["cancelled", "expired"])
def test_cancelled_or_expired_action_never_changes_links(client, database, state):
    action_id = prepare(client)
    if state == "cancelled":
        assert decide(client, action_id, "cancel").json()["state"] == state
    else:
        action_repository.actions[UUID(action_id)].expires_at = datetime.now(
            UTC
        ) - timedelta(seconds=1)
    assert decide(client, action_id).status_code == 409
    assert links(database) == {service_a}


def test_other_company_cannot_confirm_saved_action(client, database):
    action_id = prepare(client)
    assert decide(client, action_id, headers=auth_headers(owner_b)).status_code == 409
    assert links(database) == {service_a}
    assert action_repository.actions[UUID(action_id)].state == "pending"
    assert decide(client, action_id).status_code == 200


def test_confirm_body_cannot_replace_the_reviewed_service_ids(client, database):
    action_id = prepare(client)
    response = client.post(
        f"/api/v1/assistant/actions/{action_id}/confirm",
        headers=auth_headers(),
        json={"decision": "confirm", "data": {"service_ids": [str(service_b)]}},
    )
    assert response.status_code == 422
    assert links(database) == {service_a}
    assert decide(client, action_id).status_code == 200


@pytest.mark.parametrize(
    "operation", ["get_professional_services", "replace_professional_services"]
)
@pytest.mark.parametrize(
    "user_id,status", [(None, 401), (inactive_user, 401), (unassigned_user, 403)]
)
def test_tools_require_active_authenticated_user_with_business(
    client, operation, user_id, status
):
    provider, _ = mock_conversation(
        [ProviderReply(calls=[ToolCall(operation, replacement([]))])]
    )
    app.dependency_overrides[get_assistant_provider] = lambda: provider
    response = client.post(
        "/api/v1/assistant/chat",
        headers=auth_headers(user_id) if user_id else {},
        json={"message": "Vínculos"},
    )
    assert response.status_code == status
    assert not action_repository.actions


@pytest.mark.parametrize(
    "operation", ["create_professional", "replace_professional_services"]
)
@pytest.mark.parametrize(
    "failure,status",
    [
        (IntegrityError("private SQL", {}, Exception("private")), 422),
        (RuntimeError("private"), 500),
    ],
)
def test_transaction_failure_rolls_back_all_associations(
    client, database, operation, failure, status
):
    arguments = (
        {"name": "Rejected", "service_ids": [str(second_service_id)]}
        if operation == "create_professional"
        else replacement([second_service_id])
    )
    response, _ = chat_tool(client, operation, arguments)
    action_id = response.json()["pending_actions"][0]["id"]
    original_rollback = Session.rollback
    with (
        patch.object(Session, "commit", side_effect=failure),
        patch.object(
            Session, "rollback", autospec=True, side_effect=original_rollback
        ) as rollback,
    ):
        response = decide(client, action_id)
    assert response.status_code == status
    rollback.assert_called_once()
    assert "private" not in response.text
    assert links(database) == {service_a}
    assert links(database, professional_b) == {service_b}
    with Session(database) as session:
        assert (
            session.scalar(select(Professional).where(Professional.name == "Rejected"))
            is None
        )
    assert decide(client, action_id).status_code == 409


def test_read_tool_is_available_when_writes_are_disabled(client, monkeypatch, database):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    response, conversation = chat_tool(
        client, "get_professional_services", {"record_id": str(professional_a)}
    )
    assert response.status_code == 200
    assert conversation.generate.call_args.args[0][0].response["items"][0]["id"] == str(
        service_a
    )
    response, _ = chat_tool(client, "replace_professional_services", replacement([]))
    assert response.status_code == 403
    assert links(database) == {service_a}


def test_missing_service_selection_requests_clarification_without_preparing_or_writing(
    client, database
):
    response, conversation = chat_tool(
        client, "create_professional", {"name": "Needs services"}
    )
    assert response.status_code == 200
    assert not response.json().get("pending_actions")
    result = conversation.generate.call_args.args[0][0].response
    assert "error" in result
    assert {"field": "service_ids", "type": "missing"} in result["fields"]
    assert not action_repository.actions
    with Session(database) as session:
        assert (
            session.scalar(
                select(Professional).where(Professional.name == "Needs services")
            )
            is None
        )
    assert links(database) == {service_a}


@pytest.mark.parametrize("service_ids", [[], [second_service_id, service_a]])
def test_administrative_api_and_gemini_function_call_create_equivalent_records(
    client, database, service_ids
):
    payload = {
        "name": "  Equivalent professional  ",
        "phone": "85988887777",
        "description": "Same request through both entry points",
        "is_active": False,
        "service_ids": [str(identifier).upper() for identifier in service_ids],
    }
    response = client.post(
        "/api/v1/professionals", headers=auth_headers(), json=payload
    )
    assert response.status_code == 201, response.text
    api_id = UUID(response.json()["id"])
    assert {UUID(item["id"]) for item in response.json()["services"]} == set(
        service_ids
    )

    provider = GeminiProvider(
        settings.model_copy(
            update={
                "GEMINI_API_KEY": SecretStr("test-key"),
                "GEMINI_MODEL": "test-model",
            }
        )
    )
    app.dependency_overrides[get_assistant_provider] = lambda: provider
    with patch("app.modules.assistant.providers.gemini.genai.Client") as factory:
        sdk_client = factory.return_value.__enter__.return_value
        sdk_client.models.count_tokens.return_value = types.CountTokensResponse(
            total_tokens=100
        )
        sdk_client.models.generate_content.side_effect = [
            sdk_reply(
                types.Part(
                    function_call=types.FunctionCall(
                        name="list_services",
                        args={},
                        id="services-call",
                    )
                )
            ),
            sdk_reply(
                types.Part(
                    function_call=types.FunctionCall(
                        name="create_professional",
                        args=payload,
                        id="professional-call",
                    )
                )
            ),
        ]
        response = client.post(
            "/api/v1/assistant/chat",
            headers=auth_headers(),
            json={"message": "Cadastre o profissional com os serviços escolhidos"},
        )
        assert response.status_code == 200, response.text
        declarations = (
            sdk_client.models.generate_content.call_args.kwargs["config"]
            .tools[0]
            .function_declarations
        )
        declaration = next(
            item for item in declarations if item.name == "create_professional"
        )
        assert "service_ids" in declaration.parameters_json_schema["properties"]
        assert "service_ids" in declaration.parameters_json_schema["required"]
        assert "business_id" not in declaration.parameters_json_schema["properties"]
        assert sdk_client.models.generate_content.call_count == 2
        contents = sdk_client.models.generate_content.call_args.kwargs["contents"]
        function_response = contents[-1].parts[0].function_response
        assert function_response.name == "list_services"
        assert {UUID(item["id"]) for item in function_response.response["items"]} == {
            service_a,
            second_service_id,
        }

    pending = response.json()["pending_actions"][0]
    canonical_ids = [str(identifier) for identifier in service_ids]
    assert pending["arguments"]["service_ids"] == canonical_ids
    action = action_repository.actions[UUID(pending["id"])]
    assert action.arguments["service_ids"] == canonical_ids
    with Session(database) as session:
        assert set(
            session.scalars(
                select(Professional.id).where(
                    Professional.name == "Equivalent professional"
                )
            )
        ) == {api_id}

    # Changing the returned preview cannot change the server's saved arguments.
    pending["arguments"]["service_ids"].clear()
    assert action.arguments["service_ids"] == canonical_ids
    confirmed = decide(client, pending["id"])
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["arguments"]["service_ids"] == canonical_ids
    with Session(database) as session:
        professionals = session.scalars(
            select(Professional).where(Professional.name == "Equivalent professional")
        ).all()
        assert len(professionals) == 2
        assert api_id in {item.id for item in professionals}
        records = [
            (item.business_id, item.name, item.phone, item.description, item.is_active)
            for item in professionals
        ]
        assert (
            records[0]
            == records[1]
            == (
                business_a,
                "Equivalent professional",
                payload["phone"],
                payload["description"],
                False,
            )
        )
        for professional in professionals:
            rows = session.execute(
                select(professional_services).where(
                    professional_services.c.professional_id == professional.id,
                )
            ).all()
            assert len(rows) == len(service_ids)
            assert {(row.service_id, row.business_id) for row in rows} == {
                (identifier, business_a) for identifier in service_ids
            }


@pytest.mark.parametrize("entry_point", ["api", "assistant"])
def test_both_entry_points_roll_back_professional_and_links_after_insert_failure(
    client, database, entry_point
):
    payload = {
        "name": "Atomic creation",
        "service_ids": [str(service_a), str(second_service_id)],
    }
    if entry_point == "assistant":
        response, _ = chat_tool(client, "create_professional", payload)
        action_id = response.json()["pending_actions"][0]["id"]
    original_insert = ProfessionalRepository._insert_services

    def fail_after_insert(repository, professional, service_ids):
        original_insert(repository, professional, service_ids)
        raise IntegrityError("insert", {}, Exception("private failure"))

    with patch.object(
        ProfessionalRepository,
        "_insert_services",
        autospec=True,
        side_effect=fail_after_insert,
    ):
        if entry_point == "api":
            response = client.post(
                "/api/v1/professionals", headers=auth_headers(), json=payload
            )
        else:
            response = decide(client, action_id)
    assert response.status_code == (409 if entry_point == "api" else 422)
    assert "private" not in response.text
    with Session(database) as session:
        assert set(session.scalars(select(Professional.id))) == {
            professional_a,
            professional_b,
        }
        assert {
            (row.professional_id, row.service_id, row.business_id)
            for row in session.execute(select(professional_services))
        } == {
            (professional_a, service_a, business_a),
            (professional_b, service_b, business_b),
        }


def test_confirmation_rejects_action_whose_service_selection_was_lost(client, database):
    response, _ = chat_tool(
        client,
        "create_professional",
        {
            "name": "Missing saved selection",
            "service_ids": [str(service_a)],
        },
    )
    action_id = response.json()["pending_actions"][0]["id"]
    action_repository.actions[UUID(action_id)].arguments.pop("service_ids")
    response = decide(client, action_id)
    assert response.status_code == 422
    assert response.json()["code"] == "assistant_write_rejected"
    assert action_repository.actions[UUID(action_id)].state == "failed"
    with Session(database) as session:
        assert (
            session.scalar(
                select(Professional).where(
                    Professional.name == "Missing saved selection"
                )
            )
            is None
        )
    assert links(database) == {service_a}
