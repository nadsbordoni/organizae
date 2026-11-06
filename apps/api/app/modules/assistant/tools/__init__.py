import json
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.modules.appointments.exceptions import InvalidBookingError
from app.modules.appointments.service import AppointmentService
from app.modules.assistant.actions import (
    WRITE_SCHEMAS,
    PendingAction,
    action_repository,
    require_write_enabled,
)
from app.modules.assistant.appointment_schemas import (
    AppointmentCreateArguments,
    AppointmentListArguments,
    AvailabilityArguments,
)
from app.modules.assistant.exceptions import AssistantToolCallError
from app.modules.assistant.providers.base import ToolCall, ToolResult
from app.modules.assistant.tools.appointments import (
    check_availability,
    list_appointments,
    prepare_appointment,
)
from app.modules.assistant.tools.businesses import get_business_info
from app.modules.assistant.tools.clients import get_client, list_clients
from app.modules.assistant.tools.professionals import list_professionals
from app.modules.assistant.tools.services import list_services
from app.modules.businesses.service import BusinessService
from app.modules.clients.exceptions import ClientNotFoundError
from app.modules.clients.service import ClientService
from app.modules.professionals.exceptions import ProfessionalNotFoundError
from app.modules.professionals.schemas import ProfessionalCreate
from app.modules.professionals.service import ProfessionalService
from app.modules.services.exceptions import ServiceNotFoundError
from app.modules.services.schemas import ServiceCreate
from app.modules.services.service import ServiceService


class BusinessInfoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ListArguments(BusinessInfoArguments):
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class ProfessionalArguments(ListArguments):
    is_active: bool | None = None


class ClientListArguments(ListArguments):
    search: str | None = Field(default=None, max_length=255)


class ClientArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_id: UUID


# Only these names can be declared and dispatched; no dynamic function lookup.
TOOL_SCHEMAS: dict[str, tuple[type[BaseModel], str]] = {
    "list_appointments": (
        AppointmentListArguments,
        "Consulta agenda por período de até 31 dias; filtros opcionais e paginação.",
    ),
    "check_availability": (
        AvailabilityArguments,
        "Consulta horários reais de serviço/profissional em uma data; não reserva.",
    ),
    "list_clients": (
        ClientListArguments,
        "Lista ou busca clientes por nome, e-mail ou telefone.",
    ),
    "get_client": (ClientArguments, "Consulta detalhes do cliente por record_id."),
    "get_business_info": (
        BusinessInfoArguments,
        "Consulta informações da empresa do usuário autenticado.",
    ),
    "list_professionals": (
        ProfessionalArguments,
        "Lista profissionais da empresa do usuário, com filtro opcional is_active.",
    ),
    "list_services": (
        ListArguments,
        "Lista serviços e preços da empresa do usuário autenticado.",
    ),
}


def compact_schema(schema: Any) -> Any:
    if isinstance(schema, list):
        return [compact_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    return {
        key: (
            {name: compact_schema(value) for name, value in item.items()}
            if key in ("properties", "$defs")
            else compact_schema(item)
        )
        for key, item in schema.items()
        if key not in ("title", "default")
    }


class AssistantTools:
    def __init__(
        self,
        business_id: UUID,
        business_service: BusinessService,
        professional_service: ProfessionalService,
        service_service: ServiceService,
        *,
        user_id: UUID,
        client_service: ClientService | None = None,
        appointment_service: AppointmentService | None = None,
    ) -> None:
        self.appointment_service = appointment_service
        self.client_service = client_service
        self.business_id = business_id
        self.user_id = user_id
        self.business_service = business_service
        self.professional_service = professional_service
        self.service_service = service_service

    def declarations(self) -> list[dict[str, Any]]:
        schemas = dict(TOOL_SCHEMAS)
        from app.core.config import settings

        if settings.APP_ENV == "development" and settings.ASSISTANT_WRITES_ENABLED:
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
                "parameters_json_schema": compact_schema(schema.model_json_schema()),
            }
            for name, (schema, description) in schemas.items()
        ]

    def validate_calls(self, calls: list[ToolCall]) -> None:
        for call in calls:
            if call.name in WRITE_SCHEMAS:
                require_write_enabled()
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
        elif call.name in ("list_clients", "get_client"):
            if self.client_service is None:
                raise AssistantToolCallError()
            handler = list_clients if call.name == "list_clients" else get_client
            result = handler(
                self.client_service, self.business_id, **arguments.model_dump()
            )
        elif call.name in ("list_appointments", "check_availability"):
            if self.appointment_service is None:
                raise AssistantToolCallError()
            try:
                if isinstance(arguments, AppointmentListArguments):
                    result = list_appointments(
                        self.appointment_service, self.business_id, arguments
                    )
                else:
                    result = check_availability(
                        self.appointment_service, self.business_id, arguments
                    )
            except InvalidBookingError:
                result = {
                    "error": "Serviço ou profissional indisponível na empresa autenticada. Confira os IDs e o período."
                }
        else:
            result = list_services(
                self.service_service,
                self.business_id,
                **arguments.model_dump(),
            )
        return ToolResult(name=call.name, response=result, id=call.id)

    def execute_batch(self, calls: list[ToolCall]) -> list[ToolResult]:
        self.validate_calls(calls)
        keys: list[tuple[str, str] | None] = []
        call_ids: dict[str, tuple[str, str]] = {}
        for call in calls:
            if call.name not in WRITE_SCHEMAS:
                keys.append(None)
                continue
            try:
                arguments = WRITE_SCHEMAS[call.name].model_validate(call.arguments)
                payload = arguments.model_dump(
                    mode="python", exclude_unset=call.name.startswith("update_")
                )
            except ValidationError:
                payload = call.arguments
            key = (
                call.name,
                json.dumps(
                    payload,
                    sort_keys=True,
                    default=lambda value: (
                        str(value.normalize())
                        if isinstance(value, Decimal)
                        else str(value)
                    ),
                ),
            )
            if call.id is not None:
                if call.id in call_ids and call_ids[call.id] != key:
                    raise AssistantToolCallError()
                call_ids[call.id] = key
            keys.append(key)
        results: list[ToolResult] = []
        writes: dict[tuple[str, str], ToolResult] = {}
        for call, key in zip(calls, keys, strict=True):
            if key is not None and key in writes:
                result = writes[key]
                results.append(ToolResult(call.name, result.response, call.id))
            else:
                result = self.execute(call)
                results.append(result)
                if key is not None:
                    writes[key] = result
        return results

    def prepare_write(self, call: ToolCall) -> ToolResult:
        require_write_enabled()
        preview = None
        try:
            arguments = WRITE_SCHEMAS[call.name].model_validate(call.arguments)
            if call.name == "create_appointment":
                if self.appointment_service is None or self.client_service is None:
                    raise AssistantToolCallError()
                assert isinstance(arguments, AppointmentCreateArguments)
                booking = prepare_appointment(
                    arguments,
                    self.appointment_service,
                    self.client_service,
                    business_id=self.business_id,
                )
                service = self.service_service.get_by_id(
                    booking.service_id, business_id=self.business_id
                )
                professional = self.professional_service.get_by_id(
                    booking.professional_id, business_id=self.business_id
                )
                preview = {
                    "customer_name": booking.customer_name,
                    "service_name": service.name,
                    "professional_name": professional.name,
                    "starts_at": booking.starts_at.astimezone(
                        self.appointment_service.tz
                    ).isoformat(),
                    "notice": "A confirmação revalida as regras e pode recusar um horário ocupado.",
                }
            elif call.name.startswith("create_") and call.name != "create_client":
                schema = (
                    ServiceCreate
                    if call.name == "create_service"
                    else ProfessionalCreate
                )
                schema.model_validate(
                    {**arguments.model_dump(), "business_id": self.business_id}
                )
            elif (
                call.name.startswith("update_") and not arguments.data.model_fields_set
            ):
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
        except ClientNotFoundError:
            return ToolResult(
                call.name,
                {
                    "error": "Cliente não encontrado nesta empresa. Busque o cadastro e esclareça ambiguidades antes de prosseguir."
                },
                call.id,
            )
        except (InvalidBookingError, ServiceNotFoundError, ProfessionalNotFoundError):
            return ToolResult(
                call.name,
                {
                    "error": "Horário, serviço ou profissional indisponível. Consulte novamente a disponibilidade e peça outra opção."
                },
                call.id,
            )
        action = action_repository.add(
            PendingAction(
                business_id=self.business_id,
                user_id=self.user_id,
                operation=call.name,
                arguments=arguments.model_dump(
                    mode="json", exclude_unset=call.name.startswith("update_")
                ),
            )
        )
        return ToolResult(
            call.name,
            {
                "pending_action": action.model_dump(
                    mode="json", exclude={"business_id", "user_id"}
                )
                | ({"preview": preview} if preview is not None else {})
            },
            call.id,
        )
