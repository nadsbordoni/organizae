from unittest.mock import patch
from uuid import UUID

import pytest
from sqlalchemy.orm import Session
from test_assistant_tools import mock_conversation
from test_clients import (
    auth_headers,
    business_a,
    client,
    client_a,
    database,
    other_client,
    owner_b,
    password_hash,
)

from app.core.config import settings
from app.main import app
from app.modules.assistant.actions import action_repository
from app.modules.assistant.providers.base import ProviderReply, ToolCall
from app.modules.assistant.router import get_assistant_provider
from app.modules.clients.models import Client

# Reuse the disposable clients database and real authentication dependencies.
__all__ = ["client", "database", "password_hash"]


@pytest.fixture(autouse=True)
def assistant_setup():
    action_repository.actions.clear()
    with patch.multiple(settings, APP_ENV="development", ASSISTANT_WRITES_ENABLED=True):
        yield
    action_repository.actions.clear()
    app.dependency_overrides.pop(get_assistant_provider, None)


def chat_tool(client, call):
    provider, conversation = mock_conversation(
        [
            ProviderReply(calls=[call]),
            ProviderReply(text="Consulta concluída."),
        ]
    )
    app.dependency_overrides[get_assistant_provider] = lambda: provider
    response = client.post(
        "/api/v1/assistant/chat", headers=auth_headers(), json={"message": "Clientes"}
    )
    return response, conversation


def test_reads_are_scoped_to_authenticated_business(client):
    response, conversation = chat_tool(client, ToolCall("list_clients", {}))
    assert response.status_code == 200
    items = conversation.generate.call_args.args[0][0].response["items"]
    assert {item["id"] for item in items} >= {str(client_a)}
    assert str(other_client) not in {item["id"] for item in items}
    response, conversation = chat_tool(
        client, ToolCall("get_client", {"record_id": str(other_client)})
    )
    assert response.status_code == 200
    assert "error" in conversation.generate.call_args.args[0][0].response


@pytest.mark.parametrize(
    "operation,args",
    [
        ("create_client", {"name": "New", "phone": "81988887777"}),
        ("update_client", {"record_id": str(client_a), "data": {"name": "Updated"}}),
    ],
)
def test_confirm_writes_and_rejects_other_owner(client, database, operation, args):
    response, _ = chat_tool(client, ToolCall(operation, args))
    assert response.status_code == 200
    action_id = response.json()["pending_actions"][0]["id"]
    url = f"/api/v1/assistant/actions/{action_id}/confirm"
    with Session(database) as session:
        assert session.get(Client, client_a).name == "Alice"
    assert (
        client.post(
            url, headers=auth_headers(owner_b), json={"decision": "confirm"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            url, headers=auth_headers(), json={"decision": "confirm"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            url, headers=auth_headers(), json={"decision": "confirm"}
        ).status_code
        == 409
    )
    with Session(database) as session:
        if operation == "update_client":
            assert session.get(Client, client_a).name == "Updated"
        else:
            from sqlalchemy import select

            stored = session.scalar(select(Client).where(Client.phone == "81988887777"))
            assert stored.business_id == business_a


def test_update_cannot_access_other_business(client, database):
    response, _ = chat_tool(
        client,
        ToolCall(
            "update_client",
            {"record_id": str(other_client), "data": {"name": "Changed"}},
        ),
    )
    action_id = response.json()["pending_actions"][0]["id"]
    response = client.post(
        f"/api/v1/assistant/actions/{action_id}/confirm",
        headers=auth_headers(),
        json={"decision": "confirm"},
    )
    assert response.status_code == 422
    with Session(database) as session:
        assert session.get(Client, other_client).name == "Foreign"


def test_unauthenticated_cannot_confirm(client):
    response = client.post(
        f"/api/v1/assistant/actions/{UUID(int=0)}/confirm", json={"decision": "confirm"}
    )
    assert response.status_code == 401
