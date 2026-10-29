from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ]
    request_id: UUID | None = None
    conversation_id: UUID | None = None


class ChatResponse(BaseModel):
    response: str
    pending_actions: list[dict] | None = None
    conversation_id: UUID | None = None


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
    ] = "Nova conversa"


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    position: int
    pending_actions: list[dict] | None = None
    created_at: datetime
