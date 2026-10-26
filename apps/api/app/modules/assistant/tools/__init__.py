from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.modules.assistant.exceptions import AssistantToolCallError
from app.modules.assistant.providers.base import ToolCall, ToolResult
from app.modules.assistant.tools.businesses import get_business_info
from app.modules.assistant.tools.professionals import list_professionals
from app.modules.assistant.tools.services import list_services
from app.modules.businesses.service import BusinessService
from app.modules.professionals.service import ProfessionalService
from app.modules.services.service import ServiceService


class BusinessInfoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ListArguments(BusinessInfoArguments):
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class ProfessionalArguments(ListArguments):
    is_active: bool | None = None


# Only these names can be declared and dispatched; no dynamic function lookup.
TOOL_SCHEMAS: dict[str, tuple[type[BaseModel], str]] = {
    "get_business_info": (
        BusinessInfoArguments,
        "Consulta informações da empresa de demonstração.",
    ),
    "list_professionals": (
        ProfessionalArguments,
        "Lista profissionais da empresa de demonstração, com filtro opcional is_active.",
    ),
    "list_services": (
        ListArguments,
        "Lista serviços e preços da empresa de demonstração.",
    ),
}


class AssistantTools:
    def __init__(
        self,
        business_id: UUID,
        business_service: BusinessService,
        professional_service: ProfessionalService,
        service_service: ServiceService,
    ) -> None:
        self.business_id = business_id
        self.business_service = business_service
        self.professional_service = professional_service
        self.service_service = service_service

    def declarations(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "description": description,
                "parameters_json_schema": schema.model_json_schema(),
            }
            for name, (schema, description) in TOOL_SCHEMAS.items()
        ]

    def validate_calls(self, calls: list[ToolCall]) -> None:
        for call in calls:
            if call.name not in TOOL_SCHEMAS:
                raise AssistantToolCallError()
            try:
                TOOL_SCHEMAS[call.name][0].model_validate(call.arguments)
            except ValidationError as exc:
                raise AssistantToolCallError() from exc

    def execute(self, call: ToolCall) -> ToolResult:
        self.validate_calls([call])
        arguments = TOOL_SCHEMAS[call.name][0].model_validate(call.arguments)
        if call.name == "get_business_info":
            result = get_business_info(self.business_service, self.business_id)
        elif call.name == "list_professionals":
            result = list_professionals(
                self.professional_service,
                self.business_id,
                **arguments.model_dump(),
            )
        else:
            result = list_services(
                self.service_service,
                self.business_id,
                **arguments.model_dump(),
            )
        return ToolResult(name=call.name, response=result, id=call.id)
