import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from google.genai import errors, types
from pydantic import SecretStr, ValidationError

with patch.dict(
    "os.environ",
    {
        "DB_HOST": "localhost",
        "DB_NAME": "organizae_test",
        "DB_USER": "test",
        "DB_PASSWORD": "test",
    },
):
    from app.core.config import settings

from app.modules.assistant.exceptions import (
    AssistantContextLimitError,
    AssistantUnavailableError,
)
from app.modules.assistant.history_service import ConversationService
from app.modules.assistant.prompts.system import SYSTEM_PROMPT, TOOLS_PROMPT
from app.modules.assistant.providers.base import ContextMessage, ToolResult
from app.modules.assistant.providers.gemini import GeminiConversation, GeminiProvider
from app.modules.assistant.tokens import estimate_text_tokens, history_candidates
from app.modules.assistant.tools import TOOL_SCHEMAS, compact_schema
from app.modules.assistant.usage import RequestUsage, current_usage, monitor_usage

MODULE = "app.modules.assistant.providers.gemini"
pytest_plugins = ["test_assistant_tools"]


def reply(
    text: str = "ok", *, usage: dict | None = None, call: bool = False
) -> types.GenerateContentResponse:
    part = (
        types.Part(
            function_call=types.FunctionCall(
                name="list_services", args={}, id="call-1"
            ),
            thought_signature=b"opaque",
        )
        if call
        else types.Part(text=text)
    )
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                finish_reason=types.FinishReason.STOP,
                content=types.Content(role="model", parts=[part]),
            )
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(**usage)
        if usage is not None
        else None,
    )


@pytest.fixture
def provider() -> GeminiProvider:
    return GeminiProvider(
        settings.model_copy(
            update={
                "GEMINI_API_KEY": SecretStr("private-key"),
                "GEMINI_MODEL": "test-model",
                "GEMINI_MAX_OUTPUT_TOKENS": 512,
            }
        )
    )


def test_real_usage_sums_internal_generations_and_never_recomputes_total(
    provider: GeminiProvider,
) -> None:
    with patch(f"{MODULE}.genai.Client") as factory, monitor_usage() as usage:
        client = factory.return_value.__enter__.return_value
        client.models.count_tokens.return_value = types.CountTokensResponse(
            total_tokens=1234
        )
        client.models.generate_content.side_effect = [
            reply(
                call=True,
                usage={
                    "prompt_token_count": 100,
                    "candidates_token_count": 10,
                    "thoughts_token_count": 30,
                    "total_token_count": 140,
                },
            ),
            reply(
                usage={
                    "prompt_token_count": 150,
                    "candidates_token_count": 20,
                    "total_token_count": 180,
                    "tool_use_prompt_token_count": 10,
                }
            ),
        ]
        with provider.conversation(
            "private-message",
            system_prompt="private-system",
            declarations=[],
            history=[],
        ) as conversation:
            assert conversation.generate().calls[0].name == "list_services"
            assert (
                conversation.generate(
                    [ToolResult("list_services", {"items": []}, "call-1")]
                ).text
                == "ok"
            )
        summary = usage.summary()
    assert summary["input_tokens"] == 250
    assert summary["output_tokens"] == 30
    assert summary["total_tokens"] == 320
    assert summary["reported_thought_tokens"] == 30
    assert summary["reported_tool_prompt_tokens"] == 10
    assert summary["generation_calls"] == summary["generation_attempts"] == 2
    assert summary["count_calls"] == 2
    assert summary["api_calls"] == 4
    assert summary["counted_context_tokens"] == 1234
    assert summary["usage_complete"] is True
    assert (
        client.models.generate_content.call_args.kwargs["config"].max_output_tokens
        == 512
    )


def test_retries_with_missing_usage_are_not_silently_treated_as_zero(
    provider: GeminiProvider,
) -> None:
    with (
        patch(f"{MODULE}.genai.Client") as factory,
        patch(f"{MODULE}.time.sleep"),
        monitor_usage() as usage,
    ):
        client = factory.return_value.__enter__.return_value
        client.models.generate_content.side_effect = [
            errors.ServerError(503, {"message": "private-error"}),
            reply(
                usage={
                    "prompt_token_count": 12,
                    "candidates_token_count": 3,
                    "total_token_count": 15,
                }
            ),
        ]
        assert (
            provider.generate("private-message", system_prompt="private-system") == "ok"
        )
    summary = usage.summary()
    assert summary["generation_attempts"] == 2 and summary["retries"] == 1
    assert summary["total_tokens"] == 15
    assert summary["unknown_usage_attempts"] == 1
    assert summary["usage_complete"] is False


def test_usage_on_failed_attempt_is_included_when_reported(
    provider: GeminiProvider,
) -> None:
    failure = errors.ServerError(503, {"message": "private-error"})
    failure.response_json = {
        "usageMetadata": {
            "promptTokenCount": 8,
            "candidatesTokenCount": 0,
            "totalTokenCount": 8,
        }
    }
    with (
        patch(f"{MODULE}.genai.Client") as factory,
        patch(f"{MODULE}.time.sleep"),
        monitor_usage() as usage,
    ):
        factory.return_value.__enter__.return_value.models.generate_content.side_effect = [
            failure,
            reply(
                usage={
                    "prompt_token_count": 9,
                    "candidates_token_count": 2,
                    "total_token_count": 11,
                }
            ),
        ]
        provider.generate("message", system_prompt="system")
    assert usage.summary()["total_tokens"] == 19
    assert usage.summary()["usage_complete"] is True


def test_missing_metadata_stays_unknown(provider: GeminiProvider) -> None:
    with patch(f"{MODULE}.genai.Client") as factory, monitor_usage() as usage:
        factory.return_value.__enter__.return_value.models.generate_content.return_value = reply()
        provider.generate("message", system_prompt="system")
    assert usage.summary()["total_tokens"] is None
    assert usage.summary()["usage_complete"] is False
    partial = RequestUsage(generation_attempts=1)
    partial.record_usage({"prompt_token_count": 8})
    assert partial.summary()["output_tokens"] is None
    assert partial.summary()["usage_complete"] is False


def test_failure_and_success_summaries_do_not_expose_content(
    provider: GeminiProvider, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        caplog.at_level(logging.INFO),
        patch(f"{MODULE}.genai.Client") as factory,
        patch(f"{MODULE}.time.sleep"),
    ):
        factory.return_value.__enter__.return_value.models.generate_content.side_effect = errors.ServerError(
            503, {"message": "private-error"}
        )
        with pytest.raises(AssistantUnavailableError):
            provider.generate("private-message", system_prompt="private-system")
    summaries = [
        json.loads(record.getMessage().split("Gemini usage: ")[1])
        for record in caplog.records
        if record.getMessage().startswith("Gemini usage: ")
    ]
    assert len(summaries) == 1
    assert summaries[0]["succeeded"] is False
    assert summaries[0]["generation_attempts"] == 3
    assert summaries[0]["unknown_usage_attempts"] == 3
    assert summaries[0]["model"] == "test-model"
    assert summaries[0]["duration_ms"] >= 0
    for secret in ("private-message", "private-system", "private-error", "private-key"):
        assert secret not in caplog.text


def test_request_context_is_isolated_and_resets_after_errors() -> None:
    def run(tokens: int) -> int:
        with monitor_usage() as usage:
            usage.generation_attempts = 1
            usage.record_usage(
                {
                    "prompt_token_count": tokens,
                    "candidates_token_count": 0,
                    "total_token_count": tokens,
                }
            )
            assert current_usage() is usage
            return usage.summary()["total_tokens"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(run, (7, 11))) == [7, 11]
    assert current_usage() is None
    with pytest.raises(RuntimeError), monitor_usage():
        raise RuntimeError("test")
    assert current_usage() is None
    with monitor_usage() as usage:
        assert usage.summary()["total_tokens"] == 0
        assert usage.summary()["generation_attempts"] == 0


def context_turns(count: int, size: int = 20) -> list[ContextMessage]:
    return [
        message
        for index in range(count)
        for message in (
            ContextMessage("user", f"{index}:" + "u" * size),
            ContextMessage("assistant", f"{index}:" + "a" * size),
        )
    ]


def content_cost(contents: list[types.Content]) -> types.CountTokensResponse:
    return types.CountTokensResponse(total_tokens=len(contents) * 10)


def test_sdk_history_budget_preserves_recent_complete_turns_with_binary_search() -> (
    None
):
    client = Mock()
    client.models.count_tokens.side_effect = lambda **kwargs: content_cost(
        kwargs["contents"]
    )
    client.models.generate_content.return_value = reply()
    history = context_turns(32)
    with monitor_usage() as usage:
        conversation = GeminiConversation(
            client,
            "model",
            "current",
            "system",
            [],
            history=history,
            token_limit=1000,
            history_token_budget=60,
        )
        conversation.generate()
    contents = client.models.generate_content.call_args.kwargs["contents"]
    assert len(contents) == 7
    assert contents[0].parts[0].text.startswith("29:")
    assert [item.role for item in contents] == ["user", "model"] * 3 + ["user"]
    assert contents[-1].parts[0].text == "current"
    assert len(history) == 64
    assert usage.count_calls < 12


def test_trimming_never_splits_current_function_call_and_response() -> None:
    client = Mock()
    client.models.count_tokens.side_effect = lambda **kwargs: content_cost(
        kwargs["contents"]
    )
    client.models.generate_content.side_effect = [reply(call=True), reply()]
    conversation = GeminiConversation(
        client,
        "model",
        "current",
        "system",
        [],
        history=context_turns(3),
        token_limit=70,
    )
    conversation.generate()
    conversation.generate([ToolResult("list_services", {"items": []}, "call-1")])
    contents = client.models.generate_content.call_args.kwargs["contents"]
    assert len(contents) == 7
    assert contents[-2].parts[0].function_call.id == "call-1"
    assert contents[-2].parts[0].thought_signature == b"opaque"
    assert contents[-1].parts[0].function_response.id == "call-1"
    assert contents[-3].parts[0].text == "current"
    assert contents[0].role == "user"


@pytest.mark.parametrize(
    "unavailable",
    [NotImplementedError(), errors.ClientError(404, {"message": "unsupported"})],
)
def test_count_fallback_is_explicitly_estimated(unavailable: Exception) -> None:
    client = Mock()
    client.models.count_tokens.side_effect = unavailable
    client.models.generate_content.return_value = reply()
    with monitor_usage() as usage:
        conversation = GeminiConversation(
            client, "model", "current", "system", [], history=[], token_limit=1000
        )
        conversation.generate()
    assert usage.estimated_context_tokens is not None
    assert usage.counted_context_tokens is None
    assert usage.summary()["total_tokens"] is None


def test_oversized_current_tool_result_is_not_cut_or_generated() -> None:
    client = Mock()
    client.models.count_tokens.return_value = types.CountTokensResponse(
        total_tokens=101
    )
    conversation = GeminiConversation(
        client, "model", "full message", "system", [], history=[], token_limit=100
    )
    with pytest.raises(AssistantContextLimitError):
        conversation.generate(
            [ToolResult("list_services", {"items": ["full result"]}, "call-1")]
        )
    assert conversation.contents[0].parts[0].text == "full message"
    assert conversation.contents[1].parts[0].function_response.response == {
        "items": ["full result"]
    }
    client.models.generate_content.assert_not_called()


def test_history_candidate_prefilter_uses_tokens_not_message_count() -> None:
    short = context_turns(30)
    assert len(history_candidates(short, 4096)) == 60
    long = context_turns(10, size=4000)
    candidates = history_candidates(long, 1024)
    assert len(candidates) == 2
    assert candidates[0].content.startswith("9:")
    assert candidates[0].role == "user" and candidates[1].role == "assistant"


def test_history_retrieval_pages_past_one_hundred_messages_without_a_count_cap() -> (
    None
):
    history = context_turns(70, size=1)
    newest_first = list(reversed(history))
    service = ConversationService(Mock(), user_id=uuid4(), business_id=uuid4())
    service.repository = Mock()
    service.repository.messages.side_effect = [newest_first[:100], newest_first[100:]]
    with patch.object(settings, "ASSISTANT_HISTORY_TOKEN_BUDGET", 4096):
        assert service.recent_context(uuid4()) == history
    assert service.repository.messages.call_count == 2


@pytest.mark.parametrize(
    "field", ["ASSISTANT_HISTORY_TOKEN_BUDGET", "GEMINI_MAX_OUTPUT_TOKENS"]
)
def test_token_settings_require_positive_values(field: str) -> None:
    with pytest.raises(ValidationError):
        type(settings)(**{**settings.model_dump(), field: 0})


def test_compact_schemas_preserve_validation_and_available_tools(tools) -> None:
    with patch.multiple(settings, APP_ENV="production", ASSISTANT_WRITES_ENABLED=True):
        declarations = tools.declarations()
    assert {item["name"] for item in declarations} == set(TOOL_SCHEMAS)
    for declaration in declarations:
        schema = declaration["parameters_json_schema"]
        assert schema["additionalProperties"] is False
        assert "title" not in schema
    original = {
        "properties": {"title": {"title": "Title", "type": "string", "maxLength": 10}},
        "required": ["title"],
    }
    assert compact_schema(original) == {
        "properties": {"title": {"type": "string", "maxLength": 10}},
        "required": ["title"],
    }
    with patch.multiple(settings, APP_ENV="development", ASSISTANT_WRITES_ENABLED=True):
        assert len(tools.declarations()) == 7


def test_prompt_and_schema_comparison_against_equivalent_static_baseline(tools) -> None:
    baseline = json.loads(
        (Path(__file__).parent / "fixtures/assistant_tokens_before.json").read_text(
            encoding="utf-8"
        )
    )
    before_prompt = baseline["system_prompt"] + "\n\n" + baseline["tools_prompt"]
    after_prompt = SYSTEM_PROMPT + "\n\n" + TOOLS_PROMPT
    assert estimate_text_tokens(after_prompt) < estimate_text_tokens(before_prompt)
    for key, enabled in (("read_tools", False), ("write_tools", True)):
        with patch.multiple(
            settings, APP_ENV="development", ASSISTANT_WRITES_ENABLED=enabled
        ):
            declarations = tools.declarations()
        assert {item["name"] for item in declarations} == {
            item["name"] for item in baseline[key]
        }
        serialize = lambda value: json.dumps(
            value, ensure_ascii=False, separators=(",", ":")
        )
        assert estimate_text_tokens(serialize(declarations)) < estimate_text_tokens(
            serialize(baseline[key])
        )


def test_reproducible_estimated_token_comparison(tools) -> None:
    """Offline comparison with identical inputs; never invokes the Google API."""
    baseline = json.loads(
        (Path(__file__).parent / "fixtures/assistant_tokens_before.json").read_text(
            encoding="utf-8"
        )
    )
    before_prompt = baseline["system_prompt"] + "\n\n" + baseline["tools_prompt"]
    after_prompt = SYSTEM_PROMPT + "\n\n" + TOOLS_PROMPT

    def estimate_schema(declarations: list[dict]) -> int:
        return estimate_text_tokens(
            json.dumps(declarations, ensure_ascii=False, separators=(",", ":"))
        )

    def estimate_contents(contents: list[types.Content]) -> int:
        return sum(
            estimate_text_tokens(part.text or "") + 8
            for item in contents
            for part in item.parts
        )

    report = []
    for scenario, writes, history in (
        ("read_no_history", False, []),
        ("write_no_history", True, []),
        ("read_short_history", False, context_turns(30)),
        ("read_long_history", False, context_turns(30, size=3500)),
    ):
        with patch.multiple(
            settings, APP_ENV="development", ASSISTANT_WRITES_ENABLED=writes
        ):
            declarations = tools.declarations()
        old_history = history[-14:]
        before = [
            types.Content(
                role="user" if item.role == "user" else "model",
                parts=[types.Part(text=item.content)],
            )
            for item in old_history
        ]
        current = types.Content(
            role="user", parts=[types.Part(text="Liste os serviços cadastrados.")]
        )
        while before and estimate_contents(before + [current]) > 8192:
            del before[:2]
        client = Mock()
        client.models.count_tokens.side_effect = lambda **kwargs: (
            types.CountTokensResponse(
                total_tokens=estimate_contents(kwargs["contents"])
            )
        )
        client.models.generate_content.return_value = reply()
        conversation = GeminiConversation(
            client,
            "offline-model",
            current.parts[0].text,
            after_prompt,
            declarations,
            history=history_candidates(history, 4096),
            token_limit=8192,
            history_token_budget=4096,
        )
        conversation.generate()
        after = client.models.generate_content.call_args.kwargs["contents"]
        key = "write_tools" if writes else "read_tools"
        before_fixed = estimate_text_tokens(before_prompt) + estimate_schema(
            baseline[key]
        )
        after_fixed = estimate_text_tokens(after_prompt) + estimate_schema(declarations)
        before_total = before_fixed + estimate_contents(before + [current])
        after_total = after_fixed + estimate_contents(after)
        report.append(
            {
                "scenario": scenario,
                "before_input_estimate": before_total,
                "after_input_estimate": after_total,
                "change_percent": round(
                    (after_total - before_total) / before_total * 100, 1
                ),
                "before_history_messages": len(before),
                "after_history_messages": len(after) - 1,
                "before_fixed_estimate": before_fixed,
                "after_fixed_estimate": after_fixed,
            }
        )
    assert all(
        item["after_input_estimate"] < item["before_input_estimate"]
        for item in report
        if item["scenario"] != "read_short_history"
    )
    print(
        json.dumps(
            {
                "method": "estimate_utf8_bytes_div_4_plus_8_per_message",
                "real_api_usage": None,
                "scenarios": report,
            },
            indent=2,
        )
    )
