class UserError(Exception):
    """Base exception for user operations."""


class UserConflictError(UserError):
    pass


class InvalidUserDataError(UserError):
    pass
