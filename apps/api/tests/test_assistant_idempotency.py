from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from test_assistant_tools import mock_conversation

from app.core.config import settings
from app.modules.assistant.actions import ActionDecision, ActionRepository
from app.modules.assistant.exceptions import (
    AssistantActionStateError,
    AssistantRequestConflictError,
    AssistantToolCallError,
)
from app.modules.assistant.providers.base import ProviderReply, ToolCall
from app.modules.assistant.schemas import ChatRequest
from app.modules.assistant.service import AssistantService
from app.modules.assistant.tools import AssistantTools

pytest_plugins = ["test_assistant_tools"]
pytestmark = pytest.mark.usefixtures("assistant_identity")


@pytest.fixture
def repository(tools: AssistantTools) -> Iterator[ActionRepository]:
    repository = ActionRepository()
    with (
        patch.multiple(
            settings,
            APP_ENV="development",
            ASSISTANT_WRITES_ENABLED=True,
        ),
        patch("app.modules.assistant.tools.action_repository", repository),
        patch("app.modules.assistant.service.action_repository", repository),
    ):
        yield repository


def write_call(call_id: str | None = None, name: str = "Ana") -> ToolCall:
    return ToolCall("create_professional", {"name": name}, call_id)


def prepare(tools: AssistantTools) -> UUID:
    return UUID(tools.execute(write_call()).response["pending_action"]["id"])


@pytest.mark.parametrize("decision", ["confirm", "cancel"])
@pytest.mark.parametrize("succeeds", [True, False])
def test_execution_survives_expiration_and_cleanup(
    tools: AssistantTools,
    repository: ActionRepository,
    decision: str,
    succeeds: bool,
) -> None:
    action_id = prepare(tools)
    assistant = AssistantService(Mock(), tools)

    def execute(_: object) -> None:
        repository.actions[action_id].expires_at = datetime.now(UTC) - timedelta(
            seconds=1
        )
        with pytest.raises(AssistantActionStateError):
            assistant.decide_action(action_id, ActionDecision(decision=decision))
        assert repository.actions[action_id].state == "executing"
        prepare(tools)
        assert repository.actions[action_id].state == "executing"
        if not succeeds:
            raise RuntimeError("failure")

    tools.professional_service.create.side_effect = execute
    if succeeds:
        assert (
            assistant.decide_action(action_id, ActionDecision(decision="confirm"))[
                "state"
            ]
            == "confirmed"
        )
    else:
        with pytest.raises(RuntimeError):
            assistant.decide_action(action_id, ActionDecision(decision="confirm"))
    assert repository.actions[action_id].state == (
        "confirmed" if succeeds else "failed"
    )
    with pytest.raises(AssistantActionStateError):
        assistant.decide_action(action_id, ActionDecision(decision="confirm"))
    tools.professional_service.create.assert_called_once()


@pytest.mark.parametrize("state", ["confirmed", "cancelled", "failed"])
def test_terminal_states_do_not_expire(
    tools: AssistantTools,
    repository: ActionRepository,
    state: str,
) -> None:
    action_id = prepare(tools)
    repository.actions[action_id].state = state
    repository.actions[action_id].expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(AssistantActionStateError):
        repository.claim(action_id, tools.business_id, "confirm", user_id=tools.user_id)
    prepare(tools)
    assert repository.actions[action_id].state == state


def test_cleanup_removes_only_expired_pending_actions(
    tools: AssistantTools,
    repository: ActionRepository,
) -> None:
    action_id = prepare(tools)
    repository.actions[action_id].expires_at = datetime.now(UTC) - timedelta(seconds=1)
    prepare(tools)
    assert action_id not in repository.actions
    with pytest.raises(AssistantActionStateError):
        repository.finish(uuid4(), "confirmed")


@pytest.mark.parametrize("ids", [(None, None), ("same", "same"), ("one", "two")])
def test_duplicate_calls_prepare_one_action(
    tools: AssistantTools,
    repository: ActionRepository,
    ids: tuple,
) -> None:
    provider, _ = mock_conversation(
        [ProviderReply(calls=[write_call(ids[0]), write_call(ids[1])])]
    )
    response = AssistantService(provider, tools).chat(
        ChatRequest(message="Cadastre Ana")
    )
    assert len(response.pending_actions) == len(repository.actions) == 1
    tools.professional_service.create.assert_not_called()


def test_deduplication_uses_validated_arguments(
    tools: AssistantTools,
    repository: ActionRepository,
) -> None:
    calls = [
        ToolCall(
            "create_service",
            {"name": " Corte ", "price": "30.00", "duration_minutes": 20},
        ),
        ToolCall(
            "create_service",
            {"duration_minutes": 20, "price": 30, "name": "Corte", "is_active": True},
        ),
    ]
    results = tools.execute_batch(calls)
    assert len(repository.actions) == 1
    assert results[0].response == results[1].response


def test_conflicting_call_id_is_rejected_before_creating_actions(
    tools: AssistantTools,
    repository: ActionRepository,
) -> None:
    with pytest.raises(AssistantToolCallError):
        tools.execute_batch([write_call("same", "Ana"), write_call("same", "Bia")])
    assert not repository.actions


def test_read_calls_are_not_deduplicated(
    tools: AssistantTools,
    repository: ActionRepository,
) -> None:
    calls = [ToolCall("list_services", {}, "same")] * 2
    assert len(tools.execute_batch(calls)) == 2
    assert tools.service_service.list.call_count == 2


def test_repeated_request_replays_ids_without_contacting_model(
    tools: AssistantTools,
    repository: ActionRepository,
) -> None:
    provider, conversation = mock_conversation([ProviderReply(calls=[write_call()])])
    request = ChatRequest(message="Cadastre Ana", request_id=uuid4())
    first = AssistantService(provider, tools).chat(request)
    replay = AssistantService(provider, tools).chat(request)
    assert first == replay
    assert len(repository.actions) == 1
    conversation.generate.assert_called_once()
    first.pending_actions.clear()
    assert len(AssistantService(provider, tools).chat(request).pending_actions) == 1


@pytest.mark.parametrize("decision", ["confirm", "cancel"])
def test_replay_does_not_recreate_consumed_or_expired_actions(
    tools: AssistantTools,
    repository: ActionRepository,
    decision: str,
) -> None:
    provider, conversation = mock_conversation([ProviderReply(calls=[write_call()])])
    assistant = AssistantService(provider, tools)
    request = ChatRequest(message="Cadastre Ana", request_id=uuid4())
    first = assistant.chat(request)
    action_id = UUID(first.pending_actions[0]["id"])
    assistant.decide_action(action_id, ActionDecision(decision=decision))
    repository.actions[action_id].expires_at = datetime.now(UTC) - timedelta(seconds=1)
    replay = assistant.chat(request)
    assert replay.pending_actions[0]["id"] == str(action_id)
    assert len(repository.actions) == 1
    with pytest.raises(AssistantActionStateError):
        assistant.decide_action(action_id, ActionDecision(decision="confirm"))
    conversation.generate.assert_called_once()


def test_request_id_contract_and_http_conflicts(
    tools: AssistantTools,
    repository: ActionRepository,
) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.modules.assistant.router import get_assistant_service

    provider, _ = mock_conversation([ProviderReply(calls=[write_call()])] * 2)
    app.dependency_overrides[get_assistant_service] = lambda: AssistantService(
        provider, tools
    )
    body = {"message": "Cadastre Ana", "request_id": str(uuid4())}
    try:
        with TestClient(app) as client:
            path = "/api/v1/assistant/chat"
            assert (
                client.post(path, json={**body, "request_id": "invalid"}).status_code
                == 422
            )
            first = client.post(path, json=body)
            replay = client.post(path, json=body)
            assert first.status_code == replay.status_code == 200
            assert first.json() == replay.json()
            conflict = client.post(path, json={**body, "message": "Outra mensagem"})
            assert conflict.status_code == 409
            assert conflict.json()["code"] == "assistant_request_conflict"
            independent = client.post(path, json={**body, "request_id": str(uuid4())})
            assert independent.status_code == 200
            assert (
                independent.json()["pending_actions"][0]["id"]
                != first.json()["pending_actions"][0]["id"]
            )
    finally:
        app.dependency_overrides.pop(get_assistant_service)


def test_replay_after_pending_expiration_does_not_prepare_again(
    tools: AssistantTools,
    repository: ActionRepository,
) -> None:
    provider, conversation = mock_conversation([ProviderReply(calls=[write_call()])])
    assistant = AssistantService(provider, tools)
    request = ChatRequest(message="Cadastre Ana", request_id=uuid4())
    first = assistant.chat(request)
    action_id = UUID(first.pending_actions[0]["id"])
    repository.actions[action_id].expires_at = datetime.now(UTC) - timedelta(seconds=1)
    prepare(tools)
    assert action_id not in repository.actions
    assert assistant.chat(request).pending_actions[0]["id"] == str(action_id)
    conversation.generate.assert_called_once()
    with pytest.raises(AssistantActionStateError):
        assistant.decide_action(action_id, ActionDecision(decision="confirm"))


@pytest.mark.parametrize("use_keys", [True, False])
def test_independent_requests_can_have_identical_parameters(
    tools: AssistantTools,
    repository: ActionRepository,
    use_keys: bool,
) -> None:
    provider, _ = mock_conversation([ProviderReply(calls=[write_call()])] * 2)
    assistant = AssistantService(provider, tools)
    for _ in range(2):
        assistant.chat(
            ChatRequest(
                message="Cadastre Ana", request_id=uuid4() if use_keys else None
            )
        )
    assert len(repository.actions) == 2


def test_request_key_cannot_be_reused_for_different_message(
    tools: AssistantTools,
    repository: ActionRepository,
) -> None:
    provider, _ = mock_conversation([ProviderReply(calls=[write_call()])])
    assistant = AssistantService(provider, tools)
    key = uuid4()
    assistant.chat(ChatRequest(message="Cadastre Ana", request_id=key))
    with pytest.raises(AssistantRequestConflictError):
        assistant.chat(ChatRequest(message="Cadastre Bia", request_id=key))
    assert len(repository.actions) == 1


def test_request_keys_are_scoped_to_business(
    repository: ActionRepository,
    tools: AssistantTools,
) -> None:
    key = uuid4()
    assert (
        repository.begin_request(uuid4(), key, "message", user_id=tools.user_id) is None
    )
    assert (
        repository.begin_request(uuid4(), key, "message", user_id=tools.user_id) is None
    )
    assert len(repository.requests) == 2


def test_concurrent_requests_prepare_once(
    tools: AssistantTools,
    repository: ActionRepository,
) -> None:
    started, release = Event(), Event()
    provider, conversation = mock_conversation([])

    def respond() -> ProviderReply:
        started.set()
        assert release.wait(5)
        return ProviderReply(calls=[write_call()])

    conversation.generate.side_effect = respond
    request = ChatRequest(message="Cadastre Ana", request_id=uuid4())
    assistant = AssistantService(provider, tools)
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(assistant.chat, request)
        try:
            assert started.wait(5)
            competing = pool.submit(assistant.chat, request)
            with pytest.raises(AssistantRequestConflictError):
                competing.result(timeout=5)
        finally:
            release.set()
        first = running.result(timeout=5)
    assert assistant.chat(request) == first
    assert len(repository.actions) == 1
    conversation.generate.assert_called_once()


def test_failed_batch_is_not_replayed(
    tools: AssistantTools,
    repository: ActionRepository,
) -> None:
    tools.service_service.list.side_effect = RuntimeError("failure")
    provider, conversation = mock_conversation(
        [ProviderReply(calls=[write_call(), ToolCall("list_services", {})])]
    )
    request = ChatRequest(message="Cadastre e liste", request_id=uuid4())
    assistant = AssistantService(provider, tools)
    with pytest.raises(RuntimeError):
        assistant.chat(request)
    with pytest.raises(AssistantRequestConflictError):
        assistant.chat(request)
    assert len(repository.actions) == 1
    conversation.generate.assert_called_once()


def test_read_responses_are_not_cached(
    tools: AssistantTools,
    repository: ActionRepository,
) -> None:
    provider, conversation = mock_conversation(
        [ProviderReply(text="first"), ProviderReply(text="second")]
    )
    request = ChatRequest(message="Consulte", request_id=uuid4())
    assistant = AssistantService(provider, tools)
    assert assistant.chat(request).response == "first"
    assert assistant.chat(request).response == "second"
    assert conversation.generate.call_count == 2
    assert not repository.requests


def test_confirmation_is_consumed_even_while_service_is_running(
    tools: AssistantTools,
    repository: ActionRepository,
) -> None:
    action_id = prepare(tools)
    started, release = Event(), Event()
    assistant = AssistantService(Mock(), tools)

    def execute(_: object) -> None:
        started.set()
        assert release.wait(5)

    tools.professional_service.create.side_effect = execute
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(
            assistant.decide_action, action_id, ActionDecision(decision="confirm")
        )
        try:
            assert started.wait(5)
            for decision in ("confirm", "cancel"):
                with pytest.raises(AssistantActionStateError):
                    pool.submit(
                        assistant.decide_action,
                        action_id,
                        ActionDecision(decision=decision),
                    ).result(timeout=5)
        finally:
            release.set()
        assert running.result(timeout=5)["state"] == "confirmed"
    tools.professional_service.create.assert_called_once()


def test_confirm_cancel_race_has_one_winner(
    tools: AssistantTools,
    repository: ActionRepository,
) -> None:
    action_id = prepare(tools)
    barrier = Barrier(2)
    assistant = AssistantService(Mock(), tools)

    def decide(decision: str) -> str:
        barrier.wait(timeout=5)
        try:
            return assistant.decide_action(
                action_id, ActionDecision(decision=decision)
            )["state"]
        except AssistantActionStateError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(decide, ["confirm", "cancel"]))
    assert results.count("rejected") == 1
    assert tools.professional_service.create.call_count == (
        1 if "confirmed" in results else 0
    )
