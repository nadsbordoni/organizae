class ProfessionalError(Exception):
    """Base exception for professional operations."""


class ProfessionalNotFoundError(ProfessionalError):
    pass


class ProfessionalConflictError(ProfessionalError):
    pass


class InvalidProfessionalServicesError(ProfessionalError):
    pass


class InvalidProfessionalPaginationError(ProfessionalError):
    pass
