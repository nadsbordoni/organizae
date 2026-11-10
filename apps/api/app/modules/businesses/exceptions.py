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


class BusinessNotPublishableError(BusinessError):
    def __init__(self, missing_fields: list[str]) -> None:
        self.missing_fields = missing_fields
        super().__init__(
            "Business page cannot be published. Missing: " + ", ".join(missing_fields)
        )