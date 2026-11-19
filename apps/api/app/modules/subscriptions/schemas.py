from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.subscriptions.models import SubscriptionStatus


class SubscriptionOverview(BaseModel):
    status: SubscriptionStatus
    trial_ends_at: datetime | None
    current_period_end: datetime | None
    grace_ends_at: datetime | None
    # Days until the deadline that applies to the status; None when none does.
    days_left: int | None
    price_cents: int


class CheckoutResponse(BaseModel):
    payment_url: str


class AsaasPayment(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str | None = None
    subscription: str | None = None
    due_date: date | None = Field(default=None, alias="dueDate")


class AsaasWebhook(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=100)
    event: str = Field(min_length=1, max_length=100)
    payment: AsaasPayment | None = None


class WebhookResponse(BaseModel):
    result: str
