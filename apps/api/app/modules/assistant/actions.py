from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import Lock
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, create_model

from app.core.config import settings
from app.modules.assistant.exceptions import (
    AssistantActionStateError,
    AssistantRequestConflictError,
    AssistantWriteDisabledError,
)
from app.modules.professionals.schemas import ProfessionalCreate, ProfessionalUpdate
from app.modules.services.schemas import ServiceCreate, ServiceUpdate


def creation_arguments(schema: type[BaseModel]) -> type[BaseModel]:
    return create_model(
        f"{schema.__name__}Arguments",
        __config__=ConfigDict(extra="forbid"),
        **{
            name: (field.annotation, field)
            for name, field in schema.model_fields.items()
            if name != "business_id"
        },
    )


class ServiceUpdateArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_id: UUID
    data: ServiceUpdate


class ProfessionalUpdateArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_id: UUID
    data: ProfessionalUpdate


WRITE_SCHEMAS = {
    "create_service": creation_arguments(ServiceCreate),
    "update_service": ServiceUpdateArguments,
    "create_professional": creation_arguments(ProfessionalCreate),
    "update_professional": ProfessionalUpdateArguments,
}


class PendingAction(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    business_id: UUID
    user_id: UUID
    operation: str
    arguments: dict
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC) + timedelta(minutes=5)
    )
    state: Literal[
        "pending", "executing", "confirmed", "cancelled", "expired", "failed"
    ] = "pending"


class ActionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decision: Literal["confirm", "cancel"]


class ChatRequestRecord(BaseModel):
    message_hash: str
    response: dict | None = None
    state: Literal["processing", "completed", "failed"] = "processing"


class ActionRepository:
    """Process-local storage scoped to authenticated identity and business."""

    def __init__(self) -> None:
        self.lock = Lock()
        self.actions: dict[UUID, PendingAction] = {}
        self.requests: dict[tuple[UUID, UUID, UUID], ChatRequestRecord] = {}

    def add(self, action: PendingAction) -> PendingAction:
        with self.lock:
            now = datetime.now(UTC)
            for key, value in list(self.actions.items()):
                if value.state == "pending" and value.expires_at <= now:
                    value.state = "expired"
                if value.state == "expired":
                    del self.actions[key]
            self.actions[action.id] = action.model_copy(deep=True)
        return action.model_copy(deep=True)

    def claim(
        self,
        action_id: UUID,
        business_id: UUID,
        decision: str,
        *,
        user_id: UUID,
    ) -> PendingAction:
        with self.lock:
            action = self.actions.get(action_id)
            if (
                action is None
                or action.business_id != business_id
                or action.user_id != user_id
                or action.state != "pending"
            ):
                raise AssistantActionStateError()
            if action.expires_at <= datetime.now(UTC):
                action.state = "expired"
                raise AssistantActionStateError()
            action.state = "cancelled" if decision == "cancel" else "executing"
            return action.model_copy(deep=True)

    def finish(self, action_id: UUID, state: Literal["confirmed", "failed"]) -> None:
        with self.lock:
            action = self.actions.get(action_id)
            if action is None or action.state != "executing":
                raise AssistantActionStateError()
            action.state = state

    def begin_request(
        self,
        business_id: UUID,
        request_id: UUID,
        message: str,
        *,
        user_id: UUID,
    ) -> dict | None:
        key = (user_id, business_id, request_id)
        message_hash = sha256(message.encode()).hexdigest()
        with self.lock:
            record = self.requests.get(key)
            if record is not None:
                if record.message_hash != message_hash or record.state != "completed":
                    raise AssistantRequestConflictError()
                return record.model_copy(deep=True).response
            self.requests[key] = ChatRequestRecord(message_hash=message_hash)
            return None

    def complete_request(
        self,
        business_id: UUID,
        request_id: UUID,
        response: dict,
        *,
        user_id: UUID,
    ) -> None:
        key = (user_id, business_id, request_id)
        with self.lock:
            if not response.get("pending_actions"):
                # Read-only responses must keep consulting current business data.
                del self.requests[key]
                return
            record = self.requests[key]
            record.response = deepcopy(response)
            record.state = "completed"

    def fail_request(
        self, business_id: UUID, request_id: UUID, *, user_id: UUID
    ) -> None:
        with self.lock:
            # Never replay a partially processed batch after an uncertain failure.
            self.requests[(user_id, business_id, request_id)].state = "failed"


action_repository = ActionRepository()


def require_write_enabled() -> None:
    if settings.APP_ENV != "development" or not settings.ASSISTANT_WRITES_ENABLED:
        raise AssistantWriteDisabledError()
