import json
from datetime import date

import httpx
import pytest

from app.modules.subscriptions.exceptions import GatewayError
from app.modules.subscriptions.gateway import AsaasGateway

KEY = "test-only-key-0123456789"
BASE = "https://sandbox.asaas.test/api/v3"


def gateway(handler) -> tuple[AsaasGateway, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(record))
    return AsaasGateway(KEY, BASE, client=client), seen


def ok(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


def test_create_customer_sends_the_key_header_and_returns_the_id() -> None:
    api, seen = gateway(lambda request: ok({"id": "cus_1"}))
    assert (
        api.create_customer(name="Maria", email="maria@example.com", external_id="b1")
        == "cus_1"
    )
    request = seen[0]
    assert request.method == "POST" and str(request.url) == f"{BASE}/customers"
    assert request.headers["access_token"] == KEY
    assert "authorization" not in request.headers
    assert json.loads(request.content) == {
        "name": "Maria",
        "email": "maria@example.com",
        "externalReference": "b1",
    }


def test_create_subscription_charges_monthly_in_reais_and_returns_the_pay_link() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return ok({"id": "sub_1"})
        return ok({"data": [{"invoiceUrl": "https://pay.test/i/1"}]})

    api, seen = gateway(handler)
    result = api.create_subscription(
        customer_id="cus_1",
        price_cents=4990,
        first_due=date(2026, 12, 4),
        external_id="b1",
    )
    assert result == ("sub_1", "https://pay.test/i/1")
    body = json.loads(seen[0].content)
    assert body["customer"] == "cus_1"
    assert body["value"] == 49.9
    assert body["nextDueDate"] == "2026-12-04"
    assert body["cycle"] == "MONTHLY"
    assert body["billingType"] == "UNDEFINED"  # the customer picks Pix, boleto or card
    assert body["externalReference"] == "b1"
    assert str(seen[1].url).startswith(f"{BASE}/subscriptions/sub_1/payments")


def test_payment_url_is_none_when_there_is_nothing_to_pay() -> None:
    api, _ = gateway(lambda request: ok({"data": []}))
    assert api.get_payment_url("sub_1") is None


def test_cancel_subscription_deletes_it() -> None:
    api, seen = gateway(lambda request: ok({"deleted": True}))
    api.cancel_subscription("sub_1")
    assert seen[0].method == "DELETE"
    assert str(seen[0].url) == f"{BASE}/subscriptions/sub_1"


def test_cancel_of_a_subscription_that_is_already_gone_is_not_an_error() -> None:
    api, _ = gateway(lambda request: ok({"errors": []}, status=404))
    api.cancel_subscription("sub_1")


@pytest.mark.parametrize("status", [400, 401, 429, 500])
def test_http_errors_become_gateway_errors_without_leaking_the_key(
    status: int,
) -> None:
    api, _ = gateway(lambda request: ok({"errors": [{"description": KEY}]}, status))
    with pytest.raises(GatewayError) as error:
        api.create_customer(name="M", email="m@example.com", external_id="b1")
    assert str(status) in str(error.value)
    assert KEY not in str(error.value) and KEY not in repr(error.value)


def test_network_failures_become_gateway_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    api, _ = gateway(handler)
    with pytest.raises(GatewayError):
        api.create_customer(name="M", email="m@example.com", external_id="b1")


def test_a_reply_without_an_id_is_a_gateway_error() -> None:
    api, _ = gateway(lambda request: ok({}))
    with pytest.raises(GatewayError):
        api.create_customer(name="M", email="m@example.com", external_id="b1")


def test_the_default_client_has_timeouts() -> None:
    api = AsaasGateway(KEY, BASE)
    assert api.client.timeout.read is not None and api.client.timeout.connect is not None
