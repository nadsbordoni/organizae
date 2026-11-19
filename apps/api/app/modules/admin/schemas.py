from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.subscriptions.models import SubscriptionStatus

MAX_GRANTED_DAYS = 90


class AdminBusinessSummary(BaseModel):
    business_id: UUID
    name: str
    owner_email: str | None
    # None for a business that has no subscription row.
    status: SubscriptionStatus | None
    trial_ends_at: datetime | None
    current_period_end: datetime | None


class AdminBusinessDetail(AdminBusinessSummary):
    owner_name: str | None
    plan_code: str | None
    price_cents: int | None
    grace_ends_at: datetime | None
    canceled_at: datetime | None


class ExtendTrialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(ge=1, le=MAX_GRANTED_DAYS)


class ReactivateRequest(BaseModel):
    """Courtesy period: how long the business stays active without paying."""

    model_config = ConfigDict(extra="forbid")

    days: int = Field(default=30, ge=1, le=MAX_GRANTED_DAYS)


class PlatformMetrics(BaseModel):
    counts_by_status: dict[SubscriptionStatus, int]
    # Monthly recurring revenue in centavos: ACTIVE and PAST_DUE pay their plan price.
    mrr_cents: int
