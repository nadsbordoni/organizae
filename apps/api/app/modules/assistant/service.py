from typing import Protocol

from app.modules.assistant.exceptions import AssistantInvalidResponseError
from app.modules.assistant.prompts.system import SYSTEM_PROMPT
from app.modules.assistant.schemas import ChatRequest, ChatResponse


class AssistantProvider(Protocol):
    def generate(self, message: str, *, system_prompt: str) -> str: ...


class AssistantService:
    def __init__(self, provider: AssistantProvider) -> None:
        self.provider = provider

    def chat(self, data: ChatRequest) -> ChatResponse:
        response = self.provider.generate(data.message, system_prompt=SYSTEM_PROMPT)
        if not isinstance(response, str) or not response.strip():
            raise AssistantInvalidResponseError()
        return ChatResponse(response=response.strip())
