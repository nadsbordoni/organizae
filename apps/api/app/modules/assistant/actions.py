from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, create_model

from app.core.config import settings
from app.modules.assistant.exceptions import (
    AssistantActionStateError,
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


class ActionRepository:
    """Process-local demo storage. Never stores sessions or ORM objects."""

    def __init__(self) -> None:
        self.lock = Lock()
        self.actions: dict[UUID, PendingAction] = {}

    def add(self, action: PendingAction) -> PendingAction:
        with self.lock:
            # Expired capabilities can be forgotten without permitting replay.
            now = datetime.now(UTC)
            self.actions = {
                key: value
                for key, value in self.actions.items()
                if value.expires_at > now or value.state == "executing"
            }
            self.actions[action.id] = action.model_copy(deep=True)
        return action.model_copy(deep=True)

    def claim(self, action_id: UUID, business_id: UUID, decision: str) -> PendingAction:
        with self.lock:
            action = self.actions.get(action_id)
            if action is None or action.business_id != business_id:
                raise AssistantActionStateError()
            if action.expires_at <= datetime.now(UTC):
                action.state = "expired"
            if action.state != "pending":
                raise AssistantActionStateError()
            action.state = "cancelled" if decision == "cancel" else "executing"
            return action.model_copy(deep=True)

    def finish(self, action_id: UUID, state: Literal["confirmed", "failed"]) -> None:
        with self.lock:
            self.actions[action_id].state = state


action_repository = ActionRepository()


def require_write_enabled(business_id: UUID) -> None:
    if (
        settings.APP_ENV != "development"
        or not settings.ASSISTANT_DEMO_ENABLED
        or settings.ASSISTANT_DEMO_BUSINESS_ID != business_id
    ):
        raise AssistantWriteDisabledError()
