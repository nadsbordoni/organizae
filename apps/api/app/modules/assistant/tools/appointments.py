from uuid import UUID

from app.modules.appointments.exceptions import InvalidBookingError
from app.modules.appointments.schemas import OnlineBookingRequest
from app.modules.appointments.service import AppointmentService
from app.modules.assistant.appointment_schemas import (
    AppointmentCreateArguments,
    AppointmentListArguments,
    AvailabilityArguments,
)
from app.modules.clients.service import ClientService


def list_appointments(
    service: AppointmentService, business_id: UUID, arguments: AppointmentListArguments
) -> dict[str, object]:
    appointments = service.list_appointments(
        business_id=business_id,
        **arguments.model_dump(exclude={"limit"}),
        limit=arguments.limit + 1,
    )
    return {
        "items": [
            {
                "id": str(item.id),
                "professional_id": str(item.professional_id)
                if item.professional_id
                else None,
                "service_id": str(item.service_id) if item.service_id else None,
                "customer_name": item.customer_name,
                "starts_at": item.starts_at.astimezone(service.tz).isoformat(),
                "ends_at": item.ends_at.astimezone(service.tz).isoformat(),
                "status": item.status.value,
                "source": item.source.value,
            }
            for item in appointments[: arguments.limit]
        ],
        "offset": arguments.offset,
        "limit": arguments.limit,
        "has_more": len(appointments) > arguments.limit,
    }


def check_availability(
    service: AppointmentService, business_id: UUID, arguments: AvailabilityArguments
) -> dict[str, object]:
    slots = service.get_availability(
        business_id=business_id,
        service_id=arguments.service_id,
        professional_id=arguments.professional_id,
        day=arguments.day,
    )
    return {
        "date": arguments.day.isoformat(),
        "service_id": str(arguments.service_id),
        "professional_id": str(arguments.professional_id),
        "total_slots": len(slots),
        "slots": [slot.isoformat() for slot in slots[: arguments.limit]],
        "timezone": str(service.tz),
        "limit": arguments.limit,
        "has_more": len(slots) > arguments.limit,
        "notice": "Consulta não reserva horário. A disponibilidade será revalidada ao confirmar.",
    }


def resolve_booking(
    arguments: AppointmentCreateArguments,
    clients: ClientService,
    *,
    business_id: UUID,
) -> OnlineBookingRequest:
    client = clients.get_by_id(arguments.client_id, business_id=business_id)
    return OnlineBookingRequest(
        service_id=arguments.service_id,
        professional_id=arguments.professional_id,
        starts_at=arguments.starts_at,
        customer_name=client.name,
        customer_phone=client.phone,
        customer_email=client.email,
        notes=arguments.notes,
    )


def prepare_appointment(
    arguments: AppointmentCreateArguments,
    service: AppointmentService,
    clients: ClientService,
    *,
    business_id: UUID,
) -> OnlineBookingRequest:
    booking = resolve_booking(arguments, clients, business_id=business_id)
    slots = service.get_availability(
        business_id=business_id,
        service_id=booking.service_id,
        professional_id=booking.professional_id,
        day=booking.starts_at.astimezone(service.tz).date(),
    )
    if booking.starts_at not in slots:
        raise InvalidBookingError("Time is not available")
    return booking
