from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from app.modules.assistant.actions import (
    ActionDecision,
    PendingAction,
    action_repository,
    require_write_enabled,
)
from app.modules.assistant.exceptions import (
    AssistantBusinessNotFoundError,
    AssistantInvalidResponseError,
    AssistantToolDatabaseError,
    AssistantToolLimitError,
    AssistantWriteBusinessError,
    AssistantWriteDisabledError,
)
from app.modules.assistant.prompts.system import SYSTEM_PROMPT, TOOLS_PROMPT
from app.modules.assistant.providers.base import AssistantProvider
from app.modules.assistant.schemas import ChatRequest, ChatResponse
from app.modules.assistant.tools import AssistantTools
from app.modules.businesses.exceptions import BusinessNotFoundError
from app.modules.professionals.exceptions import ProfessionalError
from app.modules.professionals.schemas import ProfessionalCreate, ProfessionalUpdate
from app.modules.services.exceptions import ServiceError
from app.modules.services.schemas import ServiceCreate, ServiceUpdate


class AssistantService:
    def __init__(
        self,
        provider: AssistantProvider,
        tools: AssistantTools | None = None,
    ) -> None:
        self.provider = provider
        self.tools = tools

    def chat(self, data: ChatRequest) -> ChatResponse:
        if self.tools is None or data.request_id is None:
            return self._chat(data)
        business_id = self.tools.business_id
        cached = action_repository.begin_request(
            business_id,
            data.request_id,
            data.message,
            user_id=self.tools.user_id,
        )
        if cached is not None:
            if cached.get("pending_actions"):
                require_write_enabled()
            return ChatResponse.model_validate(cached)
        completed = False
        try:
            result = self._chat(data)
            action_repository.complete_request(
                business_id,
                data.request_id,
                result.model_dump(mode="json"),
                user_id=self.tools.user_id,
            )
            completed = True
            return result
        finally:
            if not completed:
                action_repository.fail_request(
                    business_id,
                    data.request_id,
                    user_id=self.tools.user_id,
                )

    def _chat(self, data: ChatRequest) -> ChatResponse:
        if self.tools is None:
            response = self.provider.generate(data.message, system_prompt=SYSTEM_PROMPT)
        else:
            try:
                response = self._chat_with_tools(data.message)
            except BusinessNotFoundError as exc:
                raise AssistantBusinessNotFoundError() from exc
            except SQLAlchemyError as exc:
                raise AssistantToolDatabaseError() from exc
        if isinstance(response, ChatResponse):
            return response
        if not isinstance(response, str) or not response.strip():
            raise AssistantInvalidResponseError()
        return ChatResponse(response=response.strip())

    def _chat_with_tools(self, message: str) -> str | ChatResponse | None:
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
                results = tools.execute_batch(reply.calls)
                pending = {
                    result.response["pending_action"]["id"]: result.response[
                        "pending_action"
                    ]
                    for result in results
                    if "pending_action" in result.response
                }
                if pending:
                    return ChatResponse(
                        response="Revise os parâmetros e confirme ou cancele cada ação pelo identificador. Nenhuma alteração foi executada.",
                        pending_actions=list(pending.values()),
                    )
                call_count += len(reply.calls)
                reply = conversation.generate(results)
            return reply.text

    def decide_action(self, action_id: UUID, data: ActionDecision) -> dict:
        tools = self.tools
        if tools is None:
            raise AssistantWriteDisabledError()
        require_write_enabled()
        action = action_repository.claim(
            action_id,
            tools.business_id,
            data.decision,
            user_id=tools.user_id,
        )
        if data.decision == "cancel":
            return action.model_dump(mode="json", exclude={"business_id", "user_id"})
        succeeded = False
        try:
            self._execute_action(action, tools)
            succeeded = True
        except (ServiceError, ProfessionalError, BusinessNotFoundError) as exc:
            raise AssistantWriteBusinessError() from exc
        except SQLAlchemyError as exc:
            raise AssistantToolDatabaseError() from exc
        finally:
            # A commit may have succeeded before a refresh failed. Never retry.
            action_repository.finish(action.id, "confirmed" if succeeded else "failed")
        action.state = "confirmed"
        return action.model_dump(mode="json", exclude={"business_id", "user_id"})

    def _execute_action(self, action: PendingAction, tools: AssistantTools) -> None:
        arguments = action.arguments
        if action.operation == "create_service":
            tools.service_service.create(
                ServiceCreate.model_validate(
                    {**arguments, "business_id": tools.business_id}
                )
            )
        elif action.operation == "create_professional":
            tools.professional_service.create(
                ProfessionalCreate.model_validate(
                    {**arguments, "business_id": tools.business_id}
                )
            )
        elif action.operation == "update_service":
            tools.service_service.update(
                UUID(arguments["record_id"]),
                ServiceUpdate.model_validate(arguments["data"]),
                business_id=tools.business_id,
            )
        elif action.operation == "update_professional":
            tools.professional_service.update(
                UUID(arguments["record_id"]),
                ProfessionalUpdate.model_validate(arguments["data"]),
                business_id=tools.business_id,
            )
