import json
import logging
import math
import random
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from google import genai
from google.genai import errors, types

from app.core.config import Settings
from app.modules.assistant.exceptions import (
    AssistantConnectionError,
    AssistantContextLimitError,
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
from app.modules.assistant.providers.base import (
    ContextMessage,
    ProviderReply,
    ToolCall,
    ToolResult,
)
from app.modules.assistant.tokens import estimate_text_tokens
from app.modules.assistant.usage import RequestUsage, current_usage, monitor_usage

logger = logging.getLogger(__name__)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3


def _retry_after_seconds(exc: errors.APIError) -> float:
    if exc.response is None:
        return 0.0
    value = exc.response.headers.get("Retry-After")
    if not value:
        return 0.0
    try:
        seconds = float(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            seconds = (retry_at - datetime.now(UTC)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return 0.0
    return max(0.0, seconds) if math.isfinite(seconds) else 0.0


def _generate_content(
    client: genai.Client,
    *,
    model: str,
    contents: Any,
    config: types.GenerateContentConfig,
) -> types.GenerateContentResponse:
    usage = current_usage() or RequestUsage(model=model)
    usage.generation_calls += 1
    # Retry only the model request, never tool dispatch or action execution.
    for attempt in range(1, MAX_ATTEMPTS + 1):
        usage.generation_attempts += 1
        usage.retries += attempt > 1
        usage.estimated_tool_tokens += (
            estimate_text_tokens(
                json.dumps(
                    [
                        tool.model_dump(mode="json", exclude_none=True)
                        for tool in (config.tools or [])
                    ],
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            if config.tools
            else 0
        )
        started_at = time.monotonic()
        try:
            result = client.models.generate_content(
                model=model, contents=contents, config=config
            )
        except errors.APIError as exc:
            body = getattr(exc, "response_json", None)
            usage.record_usage(
                (body.get("usageMetadata") or body.get("usage_metadata"))
                if isinstance(body, dict)
                else None
            )
            logger.warning(
                "Gemini request: HTTP %s duration_ms=%.1f attempt=%d/%d model=%s usage_request_id=%s",
                exc.code,
                (time.monotonic() - started_at) * 1000,
                attempt,
                MAX_ATTEMPTS,
                model,
                usage.request_id,
            )
            if exc.code not in RETRYABLE_STATUS_CODES or attempt == MAX_ATTEMPTS:
                raise
            backoff = 2 ** (attempt - 1)
            delay = max(
                backoff + random.uniform(0, backoff / 2),
                _retry_after_seconds(exc),
            )
            time.sleep(delay)
        except (httpx.RequestError, TimeoutError):
            usage.record_usage(None)
            logger.warning(
                "Gemini request: HTTP unavailable duration_ms=%.1f attempt=%d/%d model=%s usage_request_id=%s",
                (time.monotonic() - started_at) * 1000,
                attempt,
                MAX_ATTEMPTS,
                model,
                usage.request_id,
            )
            raise
        else:
            tokens = usage.record_usage(result.usage_metadata)
            logger.info(
                "Gemini request: HTTP 200 duration_ms=%.1f attempt=%d/%d model=%s input_tokens=%s output_tokens=%s total_tokens=%s usage_source=api_metadata usage_request_id=%s",
                (time.monotonic() - started_at) * 1000,
                attempt,
                MAX_ATTEMPTS,
                model,
                tokens["input_tokens"],
                tokens["output_tokens"],
                tokens["total_tokens"],
                usage.request_id,
            )
            return result
    raise AssertionError("Unreachable retry state")


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
                    timeout=self.settings.GEMINI_TIMEOUT_MS,
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
        with (
            monitor_usage(self.settings.GEMINI_MODEL.strip()),
            self._client() as client,
        ):
            result = _generate_content(
                client,
                model=self.settings.GEMINI_MODEL.strip(),
                contents=message,
                config=_config(
                    system_prompt, output_limit=self.settings.GEMINI_MAX_OUTPUT_TOKENS
                ),
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
        history: list[ContextMessage] | None = None,
    ) -> Iterator["GeminiConversation"]:
        with (
            monitor_usage(self.settings.GEMINI_MODEL.strip()),
            self._client() as client,
        ):
            yield GeminiConversation(
                client,
                self.settings.GEMINI_MODEL.strip(),
                message,
                system_prompt,
                declarations,
                history=history,
                token_limit=self.settings.ASSISTANT_CONTEXT_TOKEN_LIMIT,
                history_token_budget=self.settings.ASSISTANT_HISTORY_TOKEN_BUDGET,
                output_limit=self.settings.GEMINI_MAX_OUTPUT_TOKENS,
            )


def _config(
    system_prompt: str,
    declarations: list[dict[str, Any]] | None = None,
    *,
    output_limit: int = 2048,
) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=system_prompt,
        max_output_tokens=output_limit,
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
        *,
        history: list[ContextMessage] | None = None,
        token_limit: int = 8192,
        history_token_budget: int | None = None,
        output_limit: int = 2048,
    ) -> None:
        self.client = client
        self.model = model
        self.config = _config(system_prompt, declarations, output_limit=output_limit)
        self.token_limit = token_limit if history is not None else None
        self.history_token_budget = history_token_budget
        self.history_fitted = False
        self.history_count = len(history or [])
        self.contents = [
            *[
                types.Content(
                    role="model" if item.role == "assistant" else "user",
                    parts=[types.Part.from_text(text=item.content)],
                )
                for item in (history or [])
            ],
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=message)],
            ),
        ]

    def _fit_context(self) -> None:
        if self.token_limit is None:
            return
        if not self.history_fitted and self.history_token_budget is not None:
            self._trim_to_budget(self.history_token_budget, history_only=True)
            self.history_fitted = True
        self._trim_to_budget(self.token_limit, history_only=False)

    def _count_tokens(self, contents: list[types.Content]) -> int:
        if not contents:
            return 0
        usage = current_usage()
        if usage is not None:
            usage.count_calls += 1
        try:
            result = self.client.models.count_tokens(
                model=self.model, contents=contents
            )
            counted = result.total_tokens
        except (AttributeError, NotImplementedError):
            counted = None
        except errors.APIError as exc:
            if exc.code not in (404, 501):
                raise
            counted = None
        else:
            if not isinstance(counted, int) or isinstance(counted, bool) or counted < 0:
                raise AssistantInvalidResponseError()
        if counted is None:
            # Conservative byte bound when this SDK/model cannot count tokens.
            counted = sum(
                len(item.model_dump_json(exclude_none=True).encode("utf-8")) + 32
                for item in contents
            )
            if usage is not None:
                usage.estimated_context_tokens = counted
                usage.counted_context_tokens = None
        elif usage is not None:
            usage.counted_context_tokens = counted
            usage.estimated_context_tokens = None
        return counted

    def _trim_to_budget(self, budget: int, *, history_only: bool) -> None:
        fixed = [] if history_only else self.contents[self.history_count :]
        history = self.contents[: self.history_count]
        if self._count_tokens(history + fixed) <= budget:
            return
        starts = [index for index, item in enumerate(history) if item.role == "user"]
        # Find the largest suffix of complete turns that fits, without one API
        # request for every removed pair. Current tool transcripts remain intact.
        low, high = 0, len(starts) - 1
        selected: int | None = None
        selected_count = 0
        selected_estimated = False
        while low <= high:
            keep = (low + high) // 2
            start = starts[-keep] if keep else len(history)
            count = self._count_tokens(history[start:] + fixed)
            if count <= budget:
                selected = start
                selected_count = count
                usage = current_usage()
                selected_estimated = (
                    usage is not None and usage.estimated_context_tokens is not None
                )
                low = keep + 1
            else:
                high = keep - 1
        if selected is None:
            raise AssistantContextLimitError()
        self.contents = history[selected:] + self.contents[self.history_count :]
        self.history_count = len(history) - selected
        usage = current_usage()
        if usage is not None:
            usage.estimated_context_tokens = (
                selected_count if selected_estimated else None
            )
            usage.counted_context_tokens = (
                None if selected_estimated else selected_count
            )

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
        self._fit_context()
        result = _generate_content(
            self.client,
            model=self.model,
            contents=list(self.contents),
            config=self.config,
        )
        reply = _parse_result(result)
        # Preserve the full model content, including Gemini thought signatures.
        self.contents.append(result.candidates[0].content)
        return reply
