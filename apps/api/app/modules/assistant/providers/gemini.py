import logging

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

logger = logging.getLogger(__name__)


class GeminiProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate(self, message: str, *, system_prompt: str) -> str:
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
                result = client.models.generate_content(
                    model=model,
                    contents=message,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        max_output_tokens=2048,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                    ),
                )
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

        candidates = result.candidates or []
        if not candidates or candidates[0].finish_reason != types.FinishReason.STOP:
            raise AssistantInvalidResponseError()
        content = candidates[0].content
        if not content or not content.parts:
            raise AssistantInvalidResponseError()
        if any(part.function_call for part in content.parts):
            raise AssistantInvalidResponseError()
        text = "".join(
            part.text for part in content.parts if part.text and not part.thought
        )
        if not text.strip():
            raise AssistantInvalidResponseError()
        return text.strip()
