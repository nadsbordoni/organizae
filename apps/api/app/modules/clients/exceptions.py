class ClientError(Exception):
    pass


class ClientNotFoundError(ClientError):
    pass


class ClientConflictError(ClientError):
    pass


class InvalidClientPaginationError(ClientError):
    pass
