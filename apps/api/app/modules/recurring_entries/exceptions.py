class RecurringEntryError(Exception):
    """Base exception for monthly income and expense recurrences."""


class RecurringEntryNotFoundError(RecurringEntryError):
    pass


class RecurringEntryConflictError(RecurringEntryError):
    pass


class InvalidRecurringEntryError(RecurringEntryError):
    pass
