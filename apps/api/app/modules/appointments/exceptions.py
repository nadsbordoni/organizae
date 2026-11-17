class AppointmentError(Exception):
    """Base exception for appointment operations."""


class AppointmentNotFoundError(AppointmentError):
    pass


class AppointmentConflictError(AppointmentError):
    pass


class InvalidBookingError(AppointmentError):
    pass
