class FinancialEntryError(Exception):
    """Base exception for manual income and expense operations."""


class FinancialEntryNotFoundError(FinancialEntryError):
    pass


class FinancialEntryConflictError(FinancialEntryError):
    pass


class InvalidFinancialEntryError(FinancialEntryError):
    pass
