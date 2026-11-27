"""Suspend what time has made overdue: trials and grace periods that ended, and
paid periods nobody renewed.

Run it once a day from a scheduler on the server (nothing schedules it today):

    uv run python -m scripts.process_subscriptions

It is safe to run more than once and to overlap with another run.
"""

import sys
from datetime import UTC, datetime

LABELS = {
    "trial_suspended": "teste(s) vencido(s) suspenso(s)",
    "period_lapsed": "período(s) pago(s) vencido(s) em carência",
    "grace_suspended": "carência(s) esgotada(s) suspensa(s)",
}


def main() -> int:
    # Imported here so that importing the module does not need the environment.
    from app.core.config import settings
    from app.db.session import SessionLocal
    from app.modules.subscriptions.service import SubscriptionService

    with SessionLocal() as session:
        service = SubscriptionService(
            session, trial_days=settings.TRIAL_DAYS, grace_days=settings.GRACE_DAYS
        )
        counts = service.process_due(now=datetime.now(UTC))
    for key, label in LABELS.items():
        print(f"{counts[key]} {label}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
