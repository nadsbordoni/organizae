class ServiceError(Exception):
    """Base exception for service operations."""


class ServiceNotFoundError(ServiceError):
    pass


class ServiceConflictError(ServiceError):
    pass


class InvalidServicePaginationError(ServiceError):
    pass
