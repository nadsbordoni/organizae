import logging
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import Mock, patch
from uuid import UUID

import httpx
import pytest
from google.genai import errors, types
from pydantic import ValidationError
from test_assistant_tools import sdk_reply

from app.core.config import settings
from app.modules.assistant.actions import ActionDecision, action_repository
from app.modules.assistant.exceptions import (
    AssistantInvalidKeyError,
    AssistantInvalidResponseError,
    AssistantPermissionError,
    AssistantRateLimitError,
    AssistantRequestRejectedError,
    AssistantTimeoutError,
    AssistantUnavailableError,
)
from app.modules.assistant.providers.base import ToolCall, ToolResult
from app.modules.assistant.providers.gemini import GeminiProvider
from app.modules.assistant.schemas import ChatRequest
from app.modules.assistant.service import AssistantService
from app.modules.assistant.tools import AssistantTools

pytest_plugins = ["test_assistant", "test_assistant_tools"]
MODULE = "app.modules.assistant.providers.gemini"


def api_failure(status: int, retry_after: str | None = None) -> errors.APIError:
    response = httpx.Response(
        status,
        headers={"Retry-After": retry_after} if retry_after is not None else {},
    )
    error_type = errors.ClientError if status < 500 else errors.ServerError
    return error_type(status, {"message": "private-key private-message"}, response)


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_transient_error_then_success(provider: GeminiProvider, status: int) -> None:
    with (
        patch(f"{MODULE}.genai.Client") as factory,
        patch(f"{MODULE}.time.sleep") as sleep,
        patch(f"{MODULE}.random.uniform", return_value=0.25),
    ):
        client = factory.return_value.__enter__.return_value
        client.models.generate_content.side_effect = [
            api_failure(status),
            api_failure(status),
            sdk_reply(types.Part(text="OK")),
        ]
        assert provider.generate("message", system_prompt="system") == "OK"
        assert client.models.generate_content.call_count == 3
        assert [call.args[0] for call in sleep.call_args_list] == [1.25, 2.25]
        assert all(
            call == client.models.generate_content.call_args_list[0]
            for call in client.models.generate_content.call_args_list
        )
        options = factory.call_args.kwargs["http_options"]
        assert options.retry_options.attempts == 1
        assert options.timeout == provider.settings.GEMINI_TIMEOUT_MS


@pytest.mark.parametrize(
    "status,expected",
    [
        (429, AssistantRateLimitError),
        (500, AssistantUnavailableError),
        (502, AssistantUnavailableError),
        (503, AssistantUnavailableError),
        (504, AssistantTimeoutError),
    ],
)
def test_persistent_failure_stops_at_three(
    provider: GeminiProvider,
    status: int,
    expected: type[Exception],
) -> None:
    with (
        patch(f"{MODULE}.genai.Client") as factory,
        patch(f"{MODULE}.time.sleep") as sleep,
    ):
        client = factory.return_value.__enter__.return_value
        client.models.generate_content.side_effect = api_failure(status)
        with pytest.raises(expected):
            provider.generate("message", system_prompt="system")
        assert client.models.generate_content.call_count == 3
        assert sleep.call_count == 2
        factory.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize(
    "status,expected",
    [
        (400, AssistantRequestRejectedError),
        (401, AssistantInvalidKeyError),
        (403, AssistantPermissionError),
    ],
)
def test_definitive_errors_are_not_retried(
    provider: GeminiProvider,
    status: int,
    expected: type[Exception],
) -> None:
    with (
        patch(f"{MODULE}.genai.Client") as factory,
        patch(f"{MODULE}.time.sleep") as sleep,
    ):
        client = factory.return_value.__enter__.return_value
        client.models.generate_content.side_effect = api_failure(status)
        with pytest.raises(expected):
            provider.generate("message", system_prompt="system")
        client.models.generate_content.assert_called_once()
        sleep.assert_not_called()


@pytest.mark.parametrize(
    "header,delay",
    [
        ("12", 12),
        ("0", 1.25),
        ("-1", 1.25),
        ("invalid", 1.25),
        ("NaN", 1.25),
        ("inf", 1.25),
        ("", 1.25),
    ],
)
def test_retry_after_seconds_and_invalid_values(
    provider: GeminiProvider,
    header: str,
    delay: float,
) -> None:
    with (
        patch(f"{MODULE}.genai.Client") as factory,
        patch(f"{MODULE}.time.sleep") as sleep,
        patch(f"{MODULE}.random.uniform", return_value=0.25),
    ):
        client = factory.return_value.__enter__.return_value
        client.models.generate_content.side_effect = [
            api_failure(503, header),
            sdk_reply(types.Part(text="OK")),
        ]
        provider.generate("message", system_prompt="system")
        sleep.assert_called_once_with(delay)


@pytest.mark.parametrize("offset,delay", [(20, 20), (-20, 1)])
def test_retry_after_http_date(
    provider: GeminiProvider,
    offset: int,
    delay: float,
) -> None:
    now = datetime(2026, 10, 27, 12, tzinfo=UTC)
    with (
        patch(f"{MODULE}.genai.Client") as factory,
        patch(f"{MODULE}.time.sleep") as sleep,
        patch(f"{MODULE}.random.uniform", return_value=0),
        patch(f"{MODULE}.datetime") as clock,
    ):
        clock.now.return_value = now
        client = factory.return_value.__enter__.return_value
        client.models.generate_content.side_effect = [
            api_failure(
                503, format_datetime(now + timedelta(seconds=offset), usegmt=True)
            ),
            sdk_reply(types.Part(text="OK")),
        ]
        provider.generate("message", system_prompt="system")
        sleep.assert_called_once_with(delay)


def test_timeout_is_configurable_and_positive(provider: GeminiProvider) -> None:
    provider.settings.GEMINI_TIMEOUT_MS = 1250
    with patch(f"{MODULE}.genai.Client") as factory:
        client = factory.return_value.__enter__.return_value
        client.models.generate_content.return_value = sdk_reply(types.Part(text="OK"))
        provider.generate("message", system_prompt="system")
        assert factory.call_args.kwargs["http_options"].timeout == 1250
    with pytest.raises(ValidationError):
        type(provider.settings)(
            **{**provider.settings.model_dump(), "GEMINI_TIMEOUT_MS": 0}
        )


def test_logs_include_attempt_status_and_duration_without_secrets(
    provider: GeminiProvider,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        patch(f"{MODULE}.genai.Client") as factory,
        patch(f"{MODULE}.time.sleep"),
        caplog.at_level(logging.INFO, logger=MODULE),
    ):
        client = factory.return_value.__enter__.return_value
        client.models.generate_content.side_effect = [
            api_failure(504),
            sdk_reply(types.Part(text="private-response")),
        ]
        provider.generate("private-message", system_prompt="private-system")
    assert "HTTP 504" in caplog.text
    assert "HTTP 200" in caplog.text
    assert "attempt=1/3" in caplog.text and "attempt=2/3" in caplog.text
    assert "duration_ms=" in caplog.text
    for secret in (
        "private-key",
        "private-message",
        "private-system",
        "private-response",
        "test-key",
    ):
        assert secret not in caplog.text


def test_invalid_model_response_is_not_retried(provider: GeminiProvider) -> None:
    with (
        patch(f"{MODULE}.genai.Client") as factory,
        patch(f"{MODULE}.time.sleep") as sleep,
    ):
        client = factory.return_value.__enter__.return_value
        client.models.generate_content.return_value = types.GenerateContentResponse()
        with pytest.raises(AssistantInvalidResponseError):
            provider.generate("message", system_prompt="system")
        client.models.generate_content.assert_called_once()
        sleep.assert_not_called()


def test_conversation_retry_does_not_duplicate_tool_history(
    provider: GeminiProvider,
) -> None:
    with (
        patch(f"{MODULE}.genai.Client") as factory,
        patch(f"{MODULE}.time.sleep"),
    ):
        client = factory.return_value.__enter__.return_value
        snapshots = []
        replies = iter(
            [api_failure(503), api_failure(504), sdk_reply(types.Part(text="OK"))]
        )

        def respond(**kwargs: object) -> types.GenerateContentResponse:
            snapshots.append(deepcopy(kwargs))
            result = next(replies)
            if isinstance(result, Exception):
                raise result
            return result

        client.models.generate_content.side_effect = respond
        with provider.conversation(
            "message", system_prompt="system", declarations=[]
        ) as conversation:
            reply = conversation.generate([ToolResult("list_services", {"items": []})])
            assert reply.text == "OK"
            assert len(conversation.contents) == 3
        assert snapshots[0] == snapshots[1] == snapshots[2]
        assert len(snapshots[0]["contents"]) == 2


def test_retries_prepare_only_one_action_and_never_write(
    provider: GeminiProvider,
    tools: AssistantTools,
) -> None:
    with (
        patch.multiple(
            settings,
            APP_ENV="development",
            ASSISTANT_DEMO_ENABLED=True,
            ASSISTANT_DEMO_BUSINESS_ID=tools.business_id,
        ),
        patch(f"{MODULE}.genai.Client") as factory,
        patch(f"{MODULE}.time.sleep"),
        patch.object(action_repository, "add", wraps=action_repository.add) as add,
    ):
        client = factory.return_value.__enter__.return_value
        client.models.generate_content.side_effect = [
            api_failure(503),
            api_failure(504),
            sdk_reply(
                types.Part(
                    function_call=types.FunctionCall(
                        name="create_professional", args={"name": "Ana"}
                    )
                )
            ),
        ]
        try:
            result = AssistantService(provider, tools).chat(
                ChatRequest(message="Cadastre Ana")
            )
            assert len(result.pending_actions) == 1
            add.assert_called_once()
            tools.professional_service.create.assert_not_called()
            tools.service_service.create.assert_not_called()
            client.models.generate_content.assert_called()
            assert client.models.generate_content.call_count == 3
        finally:
            if add.call_args:
                action_repository.actions.pop(add.call_args.args[0].id, None)


def test_action_execution_is_never_retried(tools: AssistantTools) -> None:
    with (
        patch.multiple(
            settings,
            APP_ENV="development",
            ASSISTANT_DEMO_ENABLED=True,
            ASSISTANT_DEMO_BUSINESS_ID=tools.business_id,
        ),
        patch(f"{MODULE}.time.sleep") as sleep,
    ):
        result = tools.execute(ToolCall("create_professional", {"name": "Ana"}))
        action_id = UUID(result.response["pending_action"]["id"])
        tools.professional_service.create.side_effect = RuntimeError("private-error")
        try:
            with pytest.raises(RuntimeError):
                AssistantService(Mock(), tools).decide_action(
                    action_id, ActionDecision(decision="confirm")
                )
            tools.professional_service.create.assert_called_once()
            sleep.assert_not_called()
            assert action_repository.actions[action_id].state == "failed"
        finally:
            action_repository.actions.pop(action_id, None)
