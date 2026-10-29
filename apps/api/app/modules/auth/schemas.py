from typing import Literal

from pydantic import (
    UUID4,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    model_validator,
)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: SecretStr = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str = Field(min_length=1, repr=False)
    token_type: Literal["bearer"] = "bearer"


class TokenPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sub: UUID4
    iat: int = Field(strict=True, ge=0)
    exp: int = Field(strict=True, gt=0)
    token_type: Literal["access"]

    @model_validator(mode="after")
    def validate_expiration(self) -> "TokenPayload":
        if self.exp <= self.iat:
            raise ValueError("exp must be greater than iat")
        return self
