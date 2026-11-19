import secrets
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.modules.auth.dependencies import get_current_user
from app.modules.subscriptions.exceptions import (
    GatewayError,
    InvalidSubscriptionTransitionError,
    SubscriptionError,
    SubscriptionNotFoundError,
)
from app.modules.subscriptions.gateway import AsaasGateway, PaymentGateway
from app.modules.subscriptions.guard import SubscriptionServiceDep
from app.modules.subscriptions.schemas import (
    AsaasWebhook,
    CheckoutResponse,
    SubscriptionOverview,
    WebhookResponse,
)
from app.modules.users.models import User

# The business's own subscription. Never guarded: a suspended business must be
# able to see its status and to pay.
router = APIRouter(prefix="/subscription", tags=["Subscription"])
webhook_router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def get_payment_gateway() -> PaymentGateway:
    api_key = settings.ASAAS_API_KEY.get_secret_value()
    if not api_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="Payments are not configured"
        )
    return AsaasGateway(api_key, settings.ASAAS_BASE_URL)


def get_optional_payment_gateway() -> PaymentGateway | None:
    """For flows that only need the gateway when the business has a charge there."""
    try:
        return get_payment_gateway()
    except HTTPException:
        return None


GatewayDep = Annotated[PaymentGateway, Depends(get_payment_gateway)]
OptionalGatewayDep = Annotated[
    PaymentGateway | None, Depends(get_optional_payment_gateway)
]


def verify_webhook_token(
    asaas_access_token: Annotated[str | None, Header()] = None,
) -> None:
    expected = settings.ASAAS_WEBHOOK_TOKEN.get_secret_value()
    if not expected:
        # Never accept webhooks that cannot be authenticated.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="Webhook is not configured"
        )
    if not asaas_access_token or not secrets.compare_digest(
        asaas_access_token.encode(), expected.encode()
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook token")


async def subscription_error_handler(
    request: Request, exc: SubscriptionError
) -> JSONResponse:
    if isinstance(exc, SubscriptionNotFoundError):
        code, detail = status.HTTP_404_NOT_FOUND, "Subscription not found"
    elif isinstance(exc, InvalidSubscriptionTransitionError):
        code = status.HTTP_409_CONFLICT
        detail = "This action is not allowed for the current subscription status"
    elif isinstance(exc, GatewayError):
        code, detail = status.HTTP_502_BAD_GATEWAY, "The payment gateway is unavailable"
    else:
        code, detail = status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal server error"
    return JSONResponse(status_code=code, content={"detail": detail})


def owned_business_id(user: User):
    if user.business_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="User does not have a business")
    return user.business_id


@router.get("", response_model=SubscriptionOverview)
def get_subscription(
    user: Annotated[User, Depends(get_current_user)], service: SubscriptionServiceDep
):
    return service.overview(owned_business_id(user), now=datetime.now(UTC))


@router.post("/checkout", response_model=CheckoutResponse)
def checkout(
    user: Annotated[User, Depends(get_current_user)],
    service: SubscriptionServiceDep,
    gateway: GatewayDep,
):
    url = service.start_checkout(
        owned_business_id(user),
        customer_name=user.name,
        customer_email=user.email,
        gateway=gateway,
        now=datetime.now(UTC),
    )
    return {"payment_url": url}


@webhook_router.post(
    "/asaas",
    response_model=WebhookResponse,
    dependencies=[Depends(verify_webhook_token)],
)
def asaas_webhook(payload: AsaasWebhook, service: SubscriptionServiceDep):
    payment = payload.payment
    result = service.handle_gateway_event(
        event_id=payload.id,
        event_type=payload.event,
        gateway_subscription_id=payment.subscription if payment else None,
        due_date=payment.due_date if payment else None,
        now=datetime.now(UTC),
    )
    return {"result": result.value}
