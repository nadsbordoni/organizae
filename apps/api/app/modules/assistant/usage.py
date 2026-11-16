import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


def token_value(value: Any) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else None
    )


@dataclass
class RequestUsage:
    request_id: str = field(default_factory=lambda: str(uuid4()))
    model: str | None = None
    generation_calls: int = 0
    generation_attempts: int = 0
    retries: int = 0
    count_calls: int = 0
    unknown_usage_attempts: int = 0
    reported_input_tokens: int = 0
    reported_output_tokens: int = 0
    reported_total_tokens: int = 0
    reported_thought_tokens: int = 0
    reported_cached_tokens: int = 0
    reported_tool_prompt_tokens: int = 0
    usage_reports: int = 0
    input_reports: int = 0
    output_reports: int = 0
    total_reports: int = 0
    incomplete_usage_reports: int = 0
    counted_context_tokens: int | None = None
    estimated_context_tokens: int | None = None
    estimated_tool_tokens: int = 0

    def record_usage(self, metadata: Any) -> dict[str, int | None]:
        fields = {
            "input_tokens": "prompt_token_count",
            "output_tokens": "candidates_token_count",
            "total_tokens": "total_token_count",
            "thought_tokens": "thoughts_token_count",
            "cached_tokens": "cached_content_token_count",
            "tool_prompt_tokens": "tool_use_prompt_token_count",
        }
        values = {
            name: token_value(
                metadata.get(
                    source,
                    metadata.get(
                        source.split("_")[0]
                        + "".join(part.title() for part in source.split("_")[1:])
                    ),
                )
                if isinstance(metadata, dict)
                else getattr(metadata, source, None)
            )
            for name, source in fields.items()
        }
        if all(
            values[name] is None
            for name in ("input_tokens", "output_tokens", "total_tokens")
        ):
            self.unknown_usage_attempts += 1
        else:
            self.usage_reports += 1
            if any(
                values[name] is None
                for name in ("input_tokens", "output_tokens", "total_tokens")
            ):
                self.incomplete_usage_reports += 1
            self.reported_input_tokens += values["input_tokens"] or 0
            self.input_reports += values["input_tokens"] is not None
            self.reported_output_tokens += values["output_tokens"] or 0
            self.output_reports += values["output_tokens"] is not None
            self.reported_total_tokens += values["total_tokens"] or 0
            self.total_reports += values["total_tokens"] is not None
            self.reported_thought_tokens += values["thought_tokens"] or 0
            self.reported_cached_tokens += values["cached_tokens"] or 0
            self.reported_tool_prompt_tokens += values["tool_prompt_tokens"] or 0
        return values

    def summary(self) -> dict[str, Any]:
        return {
            **vars(self),
            "api_calls": self.generation_attempts + self.count_calls,
            "usage_source": "api_metadata"
            if self.generation_attempts
            else "no_generation",
            "usage_complete": self.unknown_usage_attempts == 0
            and self.incomplete_usage_reports == 0,
            "input_tokens": self.reported_input_tokens
            if self.input_reports or not self.generation_attempts
            else None,
            "output_tokens": self.reported_output_tokens
            if self.output_reports or not self.generation_attempts
            else None,
            "total_tokens": self.reported_total_tokens
            if self.total_reports or not self.generation_attempts
            else None,
        }


_current_usage: ContextVar[RequestUsage | None] = ContextVar(
    "assistant_usage", default=None
)


def current_usage() -> RequestUsage | None:
    return _current_usage.get()


@contextmanager
def monitor_usage(model: str | None = None) -> Iterator[RequestUsage]:
    current = current_usage()
    if current is not None:
        if model is not None:
            current.model = model
        yield current
        return
    usage = RequestUsage(model=model)
    token = _current_usage.set(usage)
    started_at = time.monotonic()
    succeeded = False
    try:
        yield usage
        succeeded = True
    finally:
        payload = {
            **usage.summary(),
            "duration_ms": round((time.monotonic() - started_at) * 1000, 1),
            "succeeded": succeeded,
        }
        logger.info(
            "Gemini usage: %s", json.dumps(payload, ensure_ascii=True, sort_keys=True)
        )
        _current_usage.reset(token)
