from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.modules.assistant.actions import (
    WRITE_SCHEMAS,
    PendingAction,
    action_repository,
    require_write_enabled,
)
from app.modules.assistant.exceptions import AssistantToolCallError
from app.modules.assistant.providers.base import ToolCall, ToolResult
from app.modules.assistant.tools.businesses import get_business_info
from app.modules.assistant.tools.professionals import list_professionals
from app.modules.assistant.tools.services import list_services
from app.modules.businesses.service import BusinessService
from app.modules.professionals.schemas import ProfessionalCreate
from app.modules.professionals.service import ProfessionalService
from app.modules.services.schemas import ServiceCreate
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
        schemas = dict(TOOL_SCHEMAS)
        from app.core.config import settings

        if settings.APP_ENV == "development" and settings.ASSISTANT_DEMO_ENABLED:
            schemas.update(
                {
                    name: (
                        schema,
                        "Prepara ação pendente; exige confirmação explícita pela API.",
                    )
                    for name, schema in WRITE_SCHEMAS.items()
                }
            )
        return [
            {
                "name": name,
                "description": description,
                "parameters_json_schema": schema.model_json_schema(),
            }
            for name, (schema, description) in schemas.items()
        ]

    def validate_calls(self, calls: list[ToolCall]) -> None:
        for call in calls:
            if call.name in WRITE_SCHEMAS:
                require_write_enabled(self.business_id)
                continue
            if call.name not in TOOL_SCHEMAS:
                raise AssistantToolCallError()
            try:
                TOOL_SCHEMAS[call.name][0].model_validate(call.arguments)
            except ValidationError as exc:
                raise AssistantToolCallError() from exc

    def execute(self, call: ToolCall) -> ToolResult:
        self.validate_calls([call])
        if call.name in WRITE_SCHEMAS:
            return self.prepare_write(call)
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

    def prepare_write(self, call: ToolCall) -> ToolResult:
        require_write_enabled(self.business_id)
        try:
            arguments = WRITE_SCHEMAS[call.name].model_validate(call.arguments)
            if call.name.startswith("create_"):
                schema = (
                    ServiceCreate
                    if call.name == "create_service"
                    else ProfessionalCreate
                )
                schema.model_validate(
                    {**arguments.model_dump(), "business_id": self.business_id}
                )
            elif not arguments.data.model_fields_set:
                return ToolResult(
                    call.name, {"error": "Informe os campos a atualizar."}, call.id
                )
        except ValidationError as exc:
            return ToolResult(
                call.name,
                {
                    "error": "Solicite os dados ausentes ou corrija os argumentos. Não invente valores.",
                    "fields": [
                        {
                            "field": ".".join(map(str, error["loc"])),
                            "type": error["type"],
                        }
                        for error in exc.errors()
                    ],
                },
                call.id,
            )
        action = action_repository.add(
            PendingAction(
                business_id=self.business_id,
                operation=call.name,
                arguments=arguments.model_dump(
                    mode="json", exclude_unset=call.name.startswith("update_")
                ),
            )
        )
        return ToolResult(
            call.name,
            {"pending_action": action.model_dump(mode="json", exclude={"business_id"})},
            call.id,
        )
