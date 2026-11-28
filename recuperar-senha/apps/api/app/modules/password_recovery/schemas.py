from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


class PasswordRecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr

    @field_validator("email")
    @classmethod
    def validate_length(cls, value: str) -> str:
        if len(value) > 255:
            raise ValueError("email must contain at most 255 characters")
        return value


class PasswordRecoveryResponse(BaseModel):
    # The same text whether or not the e-mail is registered.
    detail: str = (
        "If the e-mail is registered, we sent the instructions to reset the password"
    )
