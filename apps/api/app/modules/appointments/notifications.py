import logging
import smtplib
from datetime import datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

WEEKDAYS = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)


def send_email(to: str, subject: str, body: str) -> bool:
    """Hands the message to the SMTP server. Never raises: a notification
    failure must not undo the booking that triggered it."""
    # Imported here so that importing the service does not require the environment.
    from app.core.config import settings

    if not settings.SMTP_HOST:
        logger.warning("SMTP is not configured; email %r was not sent", subject)
        return False
    message = EmailMessage()
    message["From"] = settings.EMAIL_FROM or settings.SMTP_USER
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=5) as smtp:
            smtp.starttls()
            if settings.SMTP_USER:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD.get_secret_value())
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        logger.exception("Failed to send email %r", subject)
        return False
    return True


def booking_details(
    *,
    service_name: str,
    professional_name: str,
    starts_at: datetime,
    tz: ZoneInfo,
) -> str:
    local = starts_at.astimezone(tz)
    return (
        f"Serviço: {service_name}\n"
        f"Profissional: {professional_name}\n"
        f"Data: {WEEKDAYS[local.weekday()]}, {local:%d/%m/%Y}\n"
        f"Horário: {local:%H:%M}"
    )


def confirmation_message(
    *,
    customer_name: str,
    business_name: str,
    details: str,
) -> tuple[str, str]:
    first_name = customer_name.split()[0]
    body = (
        f"Olá, {first_name}!\n\n"
        f"Seu agendamento em {business_name} está confirmado.\n\n"
        f"{details}\n"
    )
    return f"Agendamento confirmado - {business_name}", body
