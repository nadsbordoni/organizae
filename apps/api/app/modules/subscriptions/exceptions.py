class SubscriptionError(Exception):
    pass


class SubscriptionNotFoundError(SubscriptionError):
    pass


class InvalidSubscriptionTransitionError(SubscriptionError):
    pass
