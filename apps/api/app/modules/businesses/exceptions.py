class BusinessError(Exception):
    """Base exception for business operations."""


class BusinessNotFoundError(BusinessError):
    pass


class BusinessCategoryNotFoundError(BusinessError):
    pass


class BusinessConflictError(BusinessError):
    pass


class InvalidBusinessPaginationError(BusinessError):
    pass