from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str | None = None


@dataclass(frozen=True)
class ToolResult:
    name: str
    response: dict[str, Any]
    id: str | None = None


@dataclass(frozen=True)
class ProviderReply:
    text: str | None = None
    calls: list[ToolCall] = field(default_factory=list)


class AssistantConversation(Protocol):
    def generate(self, results: list[ToolResult] | None = None) -> ProviderReply: ...


class AssistantProvider(Protocol):
    def generate(self, message: str, *, system_prompt: str) -> str: ...

    def conversation(
        self,
        message: str,
        *,
        system_prompt: str,
        declarations: list[dict[str, Any]],
    ) -> AbstractContextManager[AssistantConversation]: ...
