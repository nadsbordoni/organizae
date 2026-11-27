"""Envia os lembretes de agendamentos confirmados que já entraram na janela.

Feito para rodar periodicamente (cron a cada poucos minutos), a partir de apps/api:

    uv run python -m scripts.send_reminders

A antecedência vem de REMINDER_LEAD_TIME_HOURS. Cada execução processa até 100
agendamentos; o que sobrar é enviado na próxima.
"""

from datetime import timedelta
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.db.session import SessionLocal
from app.modules.appointments.service import AppointmentService


def main() -> int:
    with SessionLocal() as session:
        service = AppointmentService(session, ZoneInfo(settings.BUSINESS_TIMEZONE))
        sent = service.send_due_reminders(
            lead_time=timedelta(hours=settings.REMINDER_LEAD_TIME_HOURS)
        )
    print(f"{sent} lembrete(s) enviado(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
