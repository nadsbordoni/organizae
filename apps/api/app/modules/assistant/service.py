from sqlalchemy.exc import SQLAlchemyError

from app.modules.assistant.exceptions import (
    AssistantDemoBusinessNotFoundError,
    AssistantInvalidResponseError,
    AssistantToolDatabaseError,
    AssistantToolLimitError,
)
from app.modules.assistant.prompts.system import SYSTEM_PROMPT, TOOLS_PROMPT
from app.modules.assistant.providers.base import AssistantProvider
from app.modules.assistant.schemas import ChatRequest, ChatResponse
from app.modules.assistant.tools import AssistantTools
from app.modules.businesses.exceptions import BusinessNotFoundError


class AssistantService:
    def __init__(
        self,
        provider: AssistantProvider,
        tools: AssistantTools | None = None,
    ) -> None:
        self.provider = provider
        self.tools = tools

    def chat(self, data: ChatRequest) -> ChatResponse:
        if self.tools is None:
            response = self.provider.generate(data.message, system_prompt=SYSTEM_PROMPT)
        else:
            try:
                response = self._chat_with_tools(data.message)
            except BusinessNotFoundError as exc:
                raise AssistantDemoBusinessNotFoundError() from exc
            except SQLAlchemyError as exc:
                raise AssistantToolDatabaseError() from exc
        if not isinstance(response, str) or not response.strip():
            raise AssistantInvalidResponseError()
        return ChatResponse(response=response.strip())

    def _chat_with_tools(self, message: str) -> str | None:
        tools = self.tools
        assert tools is not None
        tools.business_service.get_by_id(tools.business_id)
        with self.provider.conversation(
            message,
            system_prompt=f"{SYSTEM_PROMPT}\n\n{TOOLS_PROMPT}",
            declarations=tools.declarations(),
        ) as conversation:
            reply = conversation.generate()
            call_count = 0
            while reply.calls:
                if call_count + len(reply.calls) > 5:
                    raise AssistantToolLimitError()
                # Validate the entire batch before executing any requested tool.
                tools.validate_calls(reply.calls)
                results = [tools.execute(call) for call in reply.calls]
                call_count += len(reply.calls)
                reply = conversation.generate(results)
            return reply.text
