import sys
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def subscription_guard_off(request: pytest.FixtureRequest) -> Iterator[None]:
    """Most tests exercise routes with mocked services and no subscription data.

    The subscription guard needs a database, so it is switched off unless the
    test module opts in with ``pytestmark = pytest.mark.real_subscription_guard``.

    The app is looked up in ``sys.modules`` instead of imported: importing it
    needs the database settings, which some test modules only provide for
    themselves while they are being imported.
    """
    main = sys.modules.get("app.main")
    guard = sys.modules.get("app.modules.subscriptions.guard")
    if main is None or guard is None or request.node.get_closest_marker(
        "real_subscription_guard"
    ):
        yield
        return
    overrides = main.app.dependency_overrides
    guards = (guard.require_write_access, guard.require_public_booking_open)
    for item in guards:
        overrides[item] = lambda: None
    try:
        yield
    finally:
        for item in guards:
            overrides.pop(item, None)
