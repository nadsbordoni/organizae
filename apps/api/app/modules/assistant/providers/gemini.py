import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
from google import genai
from google.genai import errors, types

from app.core.config import Settings
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
from app.modules.assistant.providers.base import ProviderReply, ToolCall, ToolResult

logger = logging.getLogger(__name__)


class GeminiProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @contextmanager
    def _client(self) -> Iterator[genai.Client]:
        api_key = self.settings.GEMINI_API_KEY.get_secret_value().strip()
        model = self.settings.GEMINI_MODEL.strip()
        if not api_key:
            logger.warning("Gemini configuration missing: GEMINI_API_KEY")
            raise AssistantMissingKeyError()
        if not model:
            logger.warning("Gemini configuration missing: GEMINI_MODEL")
            raise AssistantMissingModelError()
        try:
            with genai.Client(
                api_key=api_key,
                vertexai=False,
                http_options=types.HttpOptions(
                    timeout=30000,
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            ) as client:
                yield client
        except (httpx.TimeoutException, TimeoutError) as exc:
            logger.warning("Gemini request timed out")
            raise AssistantTimeoutError() from exc
        except httpx.RequestError as exc:
            logger.warning("Gemini connection failed")
            raise AssistantConnectionError() from exc
        except errors.APIError as exc:
            logger.warning("Gemini API request failed: HTTP %s", exc.code)
            error_text = str(exc.message).lower()
            invalid_key = any(
                marker in error_text
                for marker in (
                    "api key not valid",
                    "api_key_invalid",
                    "api key expired",
                    "api key was reported as leaked",
                )
            )
            if exc.code == 401 or (exc.code in (400, 403) and invalid_key):
                raise AssistantInvalidKeyError() from exc
            if exc.code == 403:
                raise AssistantPermissionError() from exc
            if exc.code == 404:
                raise AssistantModelNotFoundError() from exc
            if exc.code == 400:
                raise AssistantRequestRejectedError() from exc
            if exc.code == 429:
                raise AssistantRateLimitError() from exc
            if exc.code == 504:
                raise AssistantTimeoutError() from exc
            raise AssistantUnavailableError() from exc

    def generate(self, message: str, *, system_prompt: str) -> str:
        with self._client() as client:
            result = client.models.generate_content(
                model=self.settings.GEMINI_MODEL.strip(),
                contents=message,
                config=_config(system_prompt),
            )
        reply = _parse_result(result)
        if reply.calls or not reply.text:
            raise AssistantInvalidResponseError()
        return reply.text

    @contextmanager
    def conversation(
        self,
        message: str,
        *,
        system_prompt: str,
        declarations: list[dict[str, Any]],
    ) -> Iterator["GeminiConversation"]:
        with self._client() as client:
            yield GeminiConversation(
                client,
                self.settings.GEMINI_MODEL.strip(),
                message,
                system_prompt,
                declarations,
            )


def _config(
    system_prompt: str,
    declarations: list[dict[str, Any]] | None = None,
) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=system_prompt,
        max_output_tokens=2048,
        tools=[
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(**declaration)
                    for declaration in declarations
                ]
            )
        ]
        if declarations
        else None,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )


def _parse_result(result: types.GenerateContentResponse) -> ProviderReply:
    candidates = result.candidates or []
    if not candidates or candidates[0].finish_reason != types.FinishReason.STOP:
        raise AssistantInvalidResponseError()
    content = candidates[0].content
    if not content or not content.parts:
        raise AssistantInvalidResponseError()
    calls = [
        ToolCall(
            name=part.function_call.name or "",
            arguments=part.function_call.args or {},
            id=part.function_call.id,
        )
        for part in content.parts
        if part.function_call is not None
    ]
    text = "".join(
        part.text for part in content.parts if part.text and not part.thought
    ).strip()
    if not text and not calls:
        raise AssistantInvalidResponseError()
    return ProviderReply(text=text or None, calls=calls)


class GeminiConversation:
    def __init__(
        self,
        client: genai.Client,
        model: str,
        message: str,
        system_prompt: str,
        declarations: list[dict[str, Any]],
    ) -> None:
        self.client = client
        self.model = model
        self.config = _config(system_prompt, declarations)
        self.contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=message)],
            )
        ]

    def generate(self, results: list[ToolResult] | None = None) -> ProviderReply:
        if results:
            self.contents.append(
                types.Content(
                    role="tool",
                    parts=[
                        types.Part(
                            function_response=types.FunctionResponse(
                                name=result.name,
                                response=result.response,
                                id=result.id,
                            )
                        )
                        for result in results
                    ],
                )
            )
        result = self.client.models.generate_content(
            model=self.model,
            contents=list(self.contents),
            config=self.config,
        )
        reply = _parse_result(result)
        # Preserve the full model content, including Gemini thought signatures.
        self.contents.append(result.candidates[0].content)
        return reply
