from collections.abc import Iterator
from unittest.mock import Mock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from google.genai import errors, types
from pydantic import SecretStr

with patch.dict(
    "os.environ",
    {
        "DB_HOST": "localhost",
        "DB_NAME": "organizae_test",
        "DB_USER": "test",
        "DB_PASSWORD": "test",
    },
):
    from app.core.config import Settings
    from app.main import app
    from app.modules.assistant.router import get_assistant_provider, get_assistant_tools

from app.modules.assistant.exceptions import (
    AssistantConnectionError,
    AssistantInvalidKeyError,
    AssistantInvalidResponseError,
    AssistantMissingKeyError,
    AssistantMissingModelError,
    AssistantModelNotFoundError,
    AssistantPermissionError,
    AssistantRateLimitError,
    AssistantRequestRejectedError,
    AssistantTimeoutError,
    AssistantUnavailableError,
)
from app.modules.assistant.prompts.system import SYSTEM_PROMPT
from app.modules.assistant.providers.gemini import GeminiProvider
from app.modules.assistant.service import AssistantProvider

PATH = "/api/v1/assistant/chat"


@pytest.fixture
def api_client() -> Iterator[tuple[TestClient, Mock]]:
    provider = Mock(spec=AssistantProvider)
    provider.generate.return_value = "Olá! Sou a assistente do Organizaê."
    app.dependency_overrides[get_assistant_provider] = lambda: provider
    app.dependency_overrides[get_assistant_tools] = lambda: None
    try:
        with TestClient(app) as client:
            yield client, provider
    finally:
        app.dependency_overrides.pop(get_assistant_provider)
        app.dependency_overrides.pop(get_assistant_tools)


def test_chat(api_client: tuple[TestClient, Mock]) -> None:
    client, provider = api_client
    response = client.post(PATH, json={"message": " Olá! "})
    assert response.status_code == 200
    assert response.json() == {"response": provider.generate.return_value}
    provider.generate.assert_called_once_with("Olá!", system_prompt=SYSTEM_PROMPT)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"message": ""},
        {"message": " \n\t"},
        {"message": "x" * 4001},
        {"message": None},
        {"message": 123},
        {"message": "oi", "business_id": "1"},
    ],
)
def test_invalid_request(api_client: tuple[TestClient, Mock], payload: dict) -> None:
    client, provider = api_client
    assert client.post(PATH, json=payload).status_code == 422
    provider.generate.assert_not_called()


@pytest.mark.parametrize("value", [None, "", " \n", {"text": "oi"}])
def test_unexpected_provider_response(
    api_client: tuple[TestClient, Mock],
    value: object,
) -> None:
    client, provider = api_client
    provider.generate.return_value = value
    assert client.post(PATH, json={"message": "oi"}).status_code == 502


@pytest.mark.parametrize(
    "error, code",
    [
        (AssistantUnavailableError, 503),
        (AssistantTimeoutError, 504),
        (AssistantRateLimitError, 429),
        (AssistantInvalidResponseError, 502),
        (AssistantMissingKeyError, 503),
        (AssistantMissingModelError, 503),
        (AssistantInvalidKeyError, 503),
        (AssistantPermissionError, 503),
        (AssistantModelNotFoundError, 503),
        (AssistantRequestRejectedError, 503),
        (AssistantConnectionError, 503),
    ],
)
def test_safe_error_response(
    api_client: tuple[TestClient, Mock],
    error: type[Exception],
    code: int,
) -> None:
    client, provider = api_client
    provider.generate.side_effect = error("sensitive-provider-detail")
    response = client.post(PATH, json={"message": "oi"})
    assert response.status_code == code
    assert "sensitive-provider-detail" not in response.text
    assert response.json() == {"code": error.code, "detail": error.public_message}


def test_swagger_contract(api_client: tuple[TestClient, Mock]) -> None:
    client, _ = api_client
    assert "post" in client.get("/openapi.json").json()["paths"][PATH]
    assert client.get("/docs").status_code == 200


@pytest.fixture
def provider() -> GeminiProvider:
    return GeminiProvider(
        Settings(
            _env_file=None,
            DB_HOST="localhost",
            DB_NAME="test",
            DB_USER="test",
            DB_PASSWORD="test",
            GEMINI_API_KEY=SecretStr("test-key"),
            GEMINI_MODEL="test-model",
        )
    )


def test_gemini_request(provider: GeminiProvider) -> None:
    with patch("app.modules.assistant.providers.gemini.genai.Client") as factory:
        client = factory.return_value.__enter__.return_value
        client.models.generate_content.return_value = types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    finish_reason=types.FinishReason.STOP,
                    content=types.Content(parts=[types.Part(text=" Olá! ")]),
                )
            ],
        )
        assert provider.generate("oi", system_prompt=SYSTEM_PROMPT) == "Olá!"
        kwargs = client.models.generate_content.call_args.kwargs
        assert kwargs["model"] == "test-model"
        assert kwargs["contents"] == "oi"
        assert kwargs["config"].system_instruction == SYSTEM_PROMPT
        assert kwargs["config"].automatic_function_calling.disable is True
        assert kwargs["config"].tools is None
        factory.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize(
    "failure, expected",
    [
        (httpx.ReadTimeout("secret"), AssistantTimeoutError),
        (httpx.ConnectError("secret"), AssistantConnectionError),
        (errors.ClientError(429, {"message": "secret"}), AssistantRateLimitError),
        (errors.ClientError(403, {"message": "secret"}), AssistantPermissionError),
        (errors.ClientError(404, {"message": "secret"}), AssistantModelNotFoundError),
        (errors.ClientError(401, {"message": "secret"}), AssistantInvalidKeyError),
        (errors.ClientError(400, {"message": "secret"}), AssistantRequestRejectedError),
        (
            errors.ClientError(400, {"message": "API key not valid. secret"}),
            AssistantInvalidKeyError,
        ),
        (
            errors.ClientError(
                403, {"message": "Your API key was reported as leaked. secret"}
            ),
            AssistantInvalidKeyError,
        ),
        (errors.ServerError(503, {"message": "secret"}), AssistantUnavailableError),
        (errors.ServerError(504, {"message": "secret"}), AssistantTimeoutError),
    ],
)
def test_gemini_errors(
    provider: GeminiProvider,
    failure: Exception,
    expected: type[Exception],
) -> None:
    with patch("app.modules.assistant.providers.gemini.genai.Client") as factory:
        client = factory.return_value.__enter__.return_value
        client.models.generate_content.side_effect = failure
        with pytest.raises(expected) as caught:
            provider.generate("oi", system_prompt=SYSTEM_PROMPT)
        assert type(caught.value) is expected


@pytest.mark.parametrize(
    "candidate",
    [
        None,
        types.Candidate(finish_reason=types.FinishReason.SAFETY),
        types.Candidate(finish_reason=types.FinishReason.MAX_TOKENS),
        types.Candidate(finish_reason=types.FinishReason.STOP),
        types.Candidate(
            finish_reason=types.FinishReason.STOP,
            content=types.Content(parts=[types.Part(text=" ")]),
        ),
        types.Candidate(
            finish_reason=types.FinishReason.STOP,
            content=types.Content(
                parts=[
                    types.Part(
                        function_call=types.FunctionCall(name="write_data"),
                    )
                ]
            ),
        ),
    ],
)
def test_invalid_gemini_response(
    provider: GeminiProvider,
    candidate: types.Candidate | None,
) -> None:
    with patch("app.modules.assistant.providers.gemini.genai.Client") as factory:
        client = factory.return_value.__enter__.return_value
        client.models.generate_content.return_value = types.GenerateContentResponse(
            candidates=[candidate] if candidate else [],
        )
        with pytest.raises(AssistantInvalidResponseError):
            provider.generate("oi", system_prompt=SYSTEM_PROMPT)


def test_missing_key_does_not_create_client(provider: GeminiProvider) -> None:
    provider.settings.GEMINI_API_KEY = SecretStr("")
    with patch("app.modules.assistant.providers.gemini.genai.Client") as factory:
        with pytest.raises(AssistantMissingKeyError):
            provider.generate("oi", system_prompt=SYSTEM_PROMPT)
        factory.assert_not_called()


def test_missing_model_does_not_create_client(provider: GeminiProvider) -> None:
    provider.settings.GEMINI_MODEL = " "
    with patch("app.modules.assistant.providers.gemini.genai.Client") as factory:
        with pytest.raises(AssistantMissingModelError):
            provider.generate("oi", system_prompt=SYSTEM_PROMPT)
        factory.assert_not_called()


def test_google_error_does_not_leak_in_response_or_logs(
    api_client: tuple[TestClient, Mock],
    provider: GeminiProvider,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _ = api_client
    app.dependency_overrides[get_assistant_provider] = lambda: provider
    with patch("app.modules.assistant.providers.gemini.genai.Client") as factory:
        sdk_client = factory.return_value.__enter__.return_value
        sdk_client.models.generate_content.side_effect = errors.ClientError(
            404,
            {"message": "sensitive-provider-detail test-key"},
        )
        response = client.post(PATH, json={"message": "private-user-message"})
    assert response.status_code == 503
    assert response.json()["code"] == "gemini_model_not_found"
    assert "HTTP 404" in caplog.text
    for secret in ("sensitive-provider-detail", "test-key", "private-user-message"):
        assert secret not in response.text
        assert secret not in caplog.text
