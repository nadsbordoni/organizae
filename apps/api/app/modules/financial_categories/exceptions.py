class FinancialCategoryError(Exception):
    """Base exception for financial category operations."""


class FinancialCategoryNotFoundError(FinancialCategoryError):
    pass


class FinancialCategoryConflictError(FinancialCategoryError):
    pass


class InvalidFinancialCategoryPaginationError(FinancialCategoryError):
    pass
