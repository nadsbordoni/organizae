class AuthError(Exception):
    """Base exception for authentication operations."""


class AuthConfigurationError(AuthError):
    pass


class InvalidAccessTokenError(AuthError):
    pass


class InvalidCredentialsError(AuthError):
    pass
