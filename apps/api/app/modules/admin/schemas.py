from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.modules.subscriptions.models import SubscriptionStatus


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
