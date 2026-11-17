class CategoryError(Exception):
    """Base exception for product and service categories."""


class CategoryNotFoundError(CategoryError):
    pass


class CategoryConflictError(CategoryError):
    pass


class InvalidCategoryPaginationError(CategoryError):
    pass
