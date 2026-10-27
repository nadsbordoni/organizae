from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ]


class ChatResponse(BaseModel):
    response: str
    pending_actions: list[dict] | None = None
