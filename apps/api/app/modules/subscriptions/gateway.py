import logging
from datetime import date
from typing import Protocol

import httpx

from app.modules.subscriptions.exceptions import GatewayError, GatewayNotFoundError

logger = logging.getLogger(__name__)


class PaymentGateway(Protocol):
    def create_customer(self, *, name: str, email: str, external_id: str) -> str: ...

    def create_subscription(
        self, *, customer_id: str, price_cents: int, first_due: date, external_id: str
    ) -> tuple[str, str]:
        """Returns (subscription id, link where the customer pays)."""
        ...

    def get_payment_url(self, subscription_id: str) -> str | None: ...

    def cancel_subscription(self, subscription_id: str) -> None: ...


class AsaasGateway:
    """Asaas API v3. The key goes in the `access_token` header, not as a Bearer."""

    def __init__(
        self, api_key: str, base_url: str, *, client: httpx.Client | None = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(10.0, connect=5.0)
        )
        self.headers = {"access_token": api_key}

    def create_customer(self, *, name: str, email: str, external_id: str) -> str:
        body = {"name": name, "email": email, "externalReference": external_id}
        return self._id(self._request("POST", "/customers", json=body))

    def create_subscription(
        self, *, customer_id: str, price_cents: int, first_due: date, external_id: str
    ) -> tuple[str, str]:
        body = {
            "customer": customer_id,
            # UNDEFINED lets the customer choose Pix, boleto or card on the invoice.
            "billingType": "UNDEFINED",
            "value": round(price_cents / 100, 2),
            "nextDueDate": first_due.isoformat(),
            "cycle": "MONTHLY",
            "externalReference": external_id,
        }
        subscription_id = self._id(self._request("POST", "/subscriptions", json=body))
        url = self.get_payment_url(subscription_id)
        if url is None:
            raise GatewayError("The gateway returned no payment link")
        return subscription_id, url

    def get_payment_url(self, subscription_id: str) -> str | None:
        reply = self._request(
            "GET", f"/subscriptions/{subscription_id}/payments", params={"limit": 1}
        )
        payments = reply.get("data") or []
        return payments[0].get("invoiceUrl") if payments else None

    def cancel_subscription(self, subscription_id: str) -> None:
        try:
            self._request("DELETE", f"/subscriptions/{subscription_id}")
        except GatewayNotFoundError:
            # Already gone at the gateway: the goal is reached.
            return

    def _request(self, method: str, path: str, **kwargs: object) -> dict:
        try:
            response = self.client.request(
                method, f"{self.base_url}{path}", headers=self.headers, **kwargs
            )
        except httpx.HTTPError as error:
            logger.warning("Asaas request failed: %s", type(error).__name__)
            raise GatewayError("The payment gateway could not be reached") from None
        if response.status_code == 404:
            raise GatewayNotFoundError("The gateway answered 404")
        if not response.is_success:
            logger.warning("Asaas answered %s for %s %s", response.status_code, method, path)
            raise GatewayError(f"The gateway answered {response.status_code}")
        try:
            return response.json()
        except ValueError:
            raise GatewayError("The gateway sent an unreadable answer") from None

    @staticmethod
    def _id(reply: dict) -> str:
        identifier = reply.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise GatewayError("The gateway answer has no id")
        return identifier
