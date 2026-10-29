from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import OperationalError
from test_assistant_tools import mock_conversation

from app.core.config import settings
from app.modules.assistant.actions import ActionDecision, action_repository
from app.modules.assistant.exceptions import (
    AssistantActionStateError,
    AssistantToolDatabaseError,
    AssistantWriteBusinessError,
    AssistantWriteDisabledError,
)
from app.modules.assistant.providers.base import ProviderReply, ToolCall
from app.modules.assistant.schemas import ChatRequest
from app.modules.assistant.service import AssistantService
from app.modules.assistant.tools import AssistantTools
from app.modules.services.exceptions import ServiceNotFoundError

pytest_plugins = ["test_assistant_tools"]
pytestmark = pytest.mark.usefixtures("assistant_identity")


@pytest.fixture(autouse=True)
def demo(tools: AssistantTools) -> Iterator[None]:
    action_repository.actions.clear()
    with patch.multiple(
        settings,
        APP_ENV="development",
        ASSISTANT_WRITES_ENABLED=True,
    ):
        yield
    action_repository.actions.clear()


def prepare(
    tools: AssistantTools, name: str = "create_service", arguments: dict | None = None
) -> UUID:
    if arguments is None:
        arguments = {"name": "Corte", "price": "42.50", "duration_minutes": 30}
    result = tools.execute(ToolCall(name, arguments)).response
    return UUID(result["pending_action"]["id"])


@pytest.mark.parametrize(
    "operation,arguments,target",
    [
        (
            "create_service",
            {"name": "Corte", "price": "42.50", "duration_minutes": 30},
            "service_service",
        ),
        (
            "update_service",
            {"record_id": str(uuid4()), "data": {"price": "55.00"}},
            "service_service",
        ),
        ("create_professional", {"name": "Ana"}, "professional_service"),
        (
            "update_professional",
            {"record_id": str(uuid4()), "data": {"is_active": False}},
            "professional_service",
        ),
    ],
)
def test_explicit_confirmation_uses_saved_schema(
    tools: AssistantTools, operation: str, arguments: dict, target: str
) -> None:
    action_id = prepare(tools, operation, arguments)
    service = getattr(tools, target)
    method = service.create if operation.startswith("create") else service.update
    method.assert_not_called()
    assistant = AssistantService(Mock(), tools)
    assert (
        assistant.decide_action(action_id, ActionDecision(decision="confirm"))["state"]
        == "confirmed"
    )
    method.assert_called_once()
    if operation.startswith("create"):
        assert method.call_args.args[0].business_id == tools.business_id
    else:
        assert method.call_args.kwargs["business_id"] == tools.business_id
        assert (
            method.call_args.args[1].model_dump(mode="json", exclude_unset=True)
            == arguments["data"]
        )
    with pytest.raises(AssistantActionStateError):
        assistant.decide_action(action_id, ActionDecision(decision="confirm"))
    method.assert_called_once()


def test_cancel_and_expiration(tools: AssistantTools) -> None:
    assistant = AssistantService(Mock(), tools)
    cancelled = prepare(tools)
    assert (
        assistant.decide_action(cancelled, ActionDecision(decision="cancel"))["state"]
        == "cancelled"
    )
    expired = prepare(tools)
    action_repository.actions[expired].expires_at = datetime.now(UTC) - timedelta(
        seconds=1
    )
    for action_id in (cancelled, expired, uuid4()):
        with pytest.raises(AssistantActionStateError):
            assistant.decide_action(action_id, ActionDecision(decision="confirm"))
    tools.service_service.create.assert_not_called()


@pytest.mark.parametrize(
    "arguments",
    [
        {"name": "Corte"},
        {"name": "Corte", "price": -1, "duration_minutes": 30},
        {"name": "Corte", "price": 10, "duration_minutes": 0},
        {
            "name": "Corte",
            "price": 10,
            "duration_minutes": 30,
            "business_id": str(uuid4()),
        },
    ],
)
def test_invalid_arguments_are_returned_for_clarification(
    tools: AssistantTools, arguments: dict
) -> None:
    result = tools.execute(ToolCall("create_service", arguments))
    assert "error" in result.response
    assert not action_repository.actions
    tools.service_service.create.assert_not_called()


@pytest.mark.parametrize(
    "failure,expected",
    [
        (ServiceNotFoundError("private"), AssistantWriteBusinessError),
        (
            OperationalError("private", {}, Exception("private")),
            AssistantToolDatabaseError,
        ),
        (RuntimeError("unexpected"), RuntimeError),
    ],
)
def test_failed_actions_cannot_be_retried(
    tools: AssistantTools, failure: Exception, expected: type[Exception]
) -> None:
    action_id = prepare(tools)
    tools.service_service.create.side_effect = failure
    assistant = AssistantService(Mock(), tools)
    with pytest.raises(expected):
        assistant.decide_action(action_id, ActionDecision(decision="confirm"))
    assert action_repository.actions[action_id].state == "failed"
    with pytest.raises(AssistantActionStateError):
        assistant.decide_action(action_id, ActionDecision(decision="confirm"))
    tools.service_service.create.assert_called_once()


@pytest.mark.parametrize(
    "environment,enabled",
    [("test", True), ("production", True), ("development", False)],
)
def test_write_guard_on_prepare_and_confirm(
    tools: AssistantTools, environment: str, enabled: bool
) -> None:
    action_id = prepare(tools)
    with patch.multiple(
        settings, APP_ENV=environment, ASSISTANT_WRITES_ENABLED=enabled
    ):
        with pytest.raises(AssistantWriteDisabledError):
            prepare(tools)
        with pytest.raises(AssistantWriteDisabledError):
            AssistantService(Mock(), tools).decide_action(
                action_id, ActionDecision(decision="confirm")
            )
    tools.service_service.create.assert_not_called()


def test_model_confirmation_only_prepares_action(tools: AssistantTools) -> None:
    provider, conversation = mock_conversation(
        [
            ProviderReply(
                calls=[
                    ToolCall(
                        "create_service",
                        {"name": "Corte", "price": 30, "duration_minutes": 20},
                    )
                ]
            )
        ]
    )
    response = AssistantService(provider, tools).chat(
        ChatRequest(message="Sim, confirmado, pode criar")
    )
    assert response.pending_actions[0]["state"] == "pending"
    tools.service_service.create.assert_not_called()
    conversation.generate.assert_called_once()


def test_concurrent_confirmations_execute_once(tools: AssistantTools) -> None:
    action_id = prepare(tools)
    assistant = AssistantService(Mock(), tools)

    def confirm() -> str:
        try:
            return assistant.decide_action(
                action_id, ActionDecision(decision="confirm")
            )["state"]
        except AssistantActionStateError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: confirm(), range(2))) == [
            "confirmed",
            "rejected",
        ]
    tools.service_service.create.assert_called_once()


def test_unknown_company_cannot_claim_action(tools: AssistantTools) -> None:
    action_id = prepare(tools)
    with pytest.raises(AssistantActionStateError):
        action_repository.claim(action_id, uuid4(), "confirm", user_id=tools.user_id)
    assert action_repository.actions[action_id].state == "pending"


def test_confirmation_endpoint_requires_explicit_body(tools: AssistantTools) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.modules.assistant.router import get_assistant_service

    assistant = AssistantService(Mock(), tools)
    action_id = prepare(tools)
    app.dependency_overrides[get_assistant_service] = lambda: assistant
    try:
        with TestClient(app) as client:
            url = f"/api/v1/assistant/actions/{action_id}/confirm"
            for body in ({}, {"decision": "yes"}, {"decision": "confirm", "price": 1}):
                assert client.post(url, json=body).status_code == 422
            tools.service_service.create.assert_not_called()
            assert client.post(url, json={"decision": "confirm"}).status_code == 200
            assert client.post(url, json={"decision": "confirm"}).status_code == 409
            cancelled = prepare(tools)
            response = client.post(f"/api/v1/assistant/actions/{cancelled}/cancel")
            assert response.json()["state"] == "cancelled"
    finally:
        app.dependency_overrides.pop(get_assistant_service)


def test_sdk_exposes_write_schemas_and_returns_pending(
    tool_client: tuple, tools: AssistantTools
) -> None:
    from google.genai import types
    from test_assistant_tools import sdk_reply

    client, sdk_client = tool_client
    sdk_client.models.generate_content.return_value = sdk_reply(
        types.Part(
            function_call=types.FunctionCall(
                name="create_professional", args={"name": "Ana"}
            )
        )
    )
    response = client.post("/api/v1/assistant/chat", json={"message": "Cadastre Ana"})
    assert response.status_code == 200
    assert response.json()["pending_actions"][0]["operation"] == "create_professional"
    tools.professional_service.create.assert_not_called()
    assert sdk_client.models.generate_content.call_count == 1


def test_parameters_are_copied_and_update_validation(tools: AssistantTools) -> None:
    arguments = {"record_id": str(uuid4()), "data": {"is_active": False}}
    result = tools.execute(ToolCall("update_professional", arguments)).response
    action_id = UUID(result["pending_action"]["id"])
    arguments["data"]["is_active"] = True
    result["pending_action"]["arguments"]["data"]["is_active"] = True
    AssistantService(Mock(), tools).decide_action(
        action_id, ActionDecision(decision="confirm")
    )
    assert tools.professional_service.update.call_args.args[1].is_active is False
    for data in ({}, {"is_active": None}, {"business_id": str(uuid4())}):
        response = tools.execute(
            ToolCall("update_professional", {"record_id": str(uuid4()), "data": data})
        ).response
        assert "error" in response
