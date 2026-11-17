from datetime import UTC, datetime
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest

from app.core.config import settings
from app.modules.assistant.actions import ActionDecision, action_repository
from app.modules.assistant.exceptions import (
    AssistantActionStateError,
    AssistantToolCallError,
    AssistantWriteBusinessError,
)
from app.modules.assistant.providers.base import ToolCall
from app.modules.assistant.service import AssistantService
from app.modules.assistant.tools import AssistantTools
from app.modules.clients.exceptions import ClientConflictError, ClientNotFoundError
from app.modules.clients.models import Client
from app.modules.clients.service import ClientService

pytest_plugins = ["test_assistant_tools"]


@pytest.fixture
def client_tools(tools: AssistantTools):
    tools.client_service = Mock(spec=ClientService)
    client = Client(
        id=uuid4(),
        business_id=tools.business_id,
        name="Ana",
        phone="81999999999",
        email=None,
        notes=None,
        created_at=datetime.now(UTC),
    )
    tools.client_service.list.return_value = [client]
    tools.client_service.get_by_id.return_value = client
    action_repository.actions.clear()
    with patch.multiple(settings, APP_ENV="development", ASSISTANT_WRITES_ENABLED=True):
        yield tools
    action_repository.actions.clear()


@pytest.mark.parametrize("search", [None, "Ana", "81999999999", "ana@example.com"])
def test_list_and_search(client_tools, search):
    tools = client_tools
    result = tools.execute(ToolCall("list_clients", {"search": search, "limit": 5}))
    assert result.response["items"][0]["name"] == "Ana"
    assert "business_id" not in result.response["items"][0]
    tools.client_service.list.assert_called_once_with(
        business_id=tools.business_id,
        search=search,
        offset=0,
        limit=5,
    )


def test_get_client_and_missing(client_tools):
    tools = client_tools
    record_id = uuid4()
    assert (
        tools.execute(ToolCall("get_client", {"record_id": str(record_id)})).response[
            "name"
        ]
        == "Ana"
    )
    tools.client_service.get_by_id.assert_called_once_with(
        record_id, business_id=tools.business_id
    )
    tools.client_service.get_by_id.side_effect = ClientNotFoundError("private")
    result = tools.execute(ToolCall("get_client", {"record_id": str(record_id)}))
    assert "error" in result.response
    assert "private" not in str(result.response)


@pytest.mark.parametrize(
    "name,args",
    [
        ("delete_client", {}),
        ("list_clients", {"business_id": str(uuid4())}),
        ("list_clients", {"limit": 101}),
        ("get_client", {"record_id": "invalid"}),
        ("get_client", {"record_id": str(uuid4()), "business_id": str(uuid4())}),
    ],
)
def test_rejects_unsafe_calls(client_tools, name, args):
    with pytest.raises(AssistantToolCallError):
        client_tools.execute(ToolCall(name, args))
    assert not client_tools.client_service.mock_calls


@pytest.mark.parametrize(
    "operation,args",
    [
        ("create_client", {"name": "Ana", "phone": "(81) 99999-9999"}),
        (
            "update_client",
            {"record_id": str(uuid4()), "data": {"email": None, "name": "Ana"}},
        ),
    ],
)
def test_confirmation_and_identity(client_tools, operation, args):
    tools = client_tools
    result = tools.execute(ToolCall(operation, args))
    action_id = UUID(result.response["pending_action"]["id"])
    assert not tools.client_service.mock_calls
    for business_id, user_id in [
        (uuid4(), tools.user_id),
        (tools.business_id, uuid4()),
    ]:
        with pytest.raises(AssistantActionStateError):
            action_repository.claim(action_id, business_id, "confirm", user_id=user_id)
    assistant = AssistantService(Mock(), tools)
    assert (
        assistant.decide_action(action_id, ActionDecision(decision="confirm"))["state"]
        == "confirmed"
    )
    method = (
        tools.client_service.create
        if operation == "create_client"
        else tools.client_service.update
    )
    assert method.call_args.kwargs == {"business_id": tools.business_id}
    if operation == "create_client":
        assert method.call_args.args[0].phone == "81999999999"
    else:
        assert method.call_args.args[0] == UUID(args["record_id"])
        assert method.call_args.args[1].model_dump(exclude_unset=True) == args["data"]
    with pytest.raises(AssistantActionStateError):
        assistant.decide_action(action_id, ActionDecision(decision="confirm"))
    method.assert_called_once()


@pytest.mark.parametrize(
    "operation,args",
    [
        ("create_client", {"name": "Ana"}),
        ("create_client", {"name": "Ana", "phone": "123"}),
        (
            "create_client",
            {"name": "Ana", "phone": "81999999999", "business_id": str(uuid4())},
        ),
        ("update_client", {"record_id": str(uuid4()), "data": {}}),
        ("update_client", {"record_id": str(uuid4()), "data": {"name": None}}),
        (
            "update_client",
            {"record_id": str(uuid4()), "data": {"business_id": str(uuid4())}},
        ),
    ],
)
def test_invalid_writes_do_not_prepare(client_tools, operation, args):
    assert "error" in client_tools.execute(ToolCall(operation, args)).response
    assert not action_repository.actions
    assert not client_tools.client_service.mock_calls


@pytest.mark.parametrize(
    "failure", [ClientConflictError("private"), ClientNotFoundError("private")]
)
def test_business_error_on_confirmation(client_tools, failure):
    tools = client_tools
    result = tools.execute(
        ToolCall("update_client", {"record_id": str(uuid4()), "data": {"name": "Ana"}})
    )
    action_id = UUID(result.response["pending_action"]["id"])
    tools.client_service.update.side_effect = failure
    with pytest.raises(AssistantWriteBusinessError):
        AssistantService(Mock(), tools).decide_action(
            action_id, ActionDecision(decision="confirm")
        )
    assert action_repository.actions[action_id].state == "failed"


def test_cancel_does_not_write(client_tools):
    result = client_tools.execute(
        ToolCall("create_client", {"name": "Ana", "phone": "81999999999"})
    )
    action_id = UUID(result.response["pending_action"]["id"])
    assert (
        AssistantService(Mock(), client_tools).decide_action(
            action_id, ActionDecision(decision="cancel")
        )["state"]
        == "cancelled"
    )
    assert not client_tools.client_service.mock_calls
