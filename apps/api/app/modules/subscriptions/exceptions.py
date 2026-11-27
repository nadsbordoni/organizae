class SubscriptionError(Exception):
    pass


class SubscriptionNotFoundError(SubscriptionError):
    pass


class InvalidSubscriptionTransitionError(SubscriptionError):
    pass


class GatewayError(SubscriptionError):
    """The payment gateway refused or could not be reached.

    The message never carries the API key or the gateway's own error text.
    """


class GatewayNotFoundError(GatewayError):
    pass
