from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints


UserName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=150),
]


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: UserName
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: UserName | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: EmailStr
    is_active: bool
    business_id: UUID | None