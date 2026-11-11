class FinancialReportError(Exception):
    """Base exception for financial dashboard and report operations."""


class InvalidFinancialReportError(FinancialReportError):
    pass
