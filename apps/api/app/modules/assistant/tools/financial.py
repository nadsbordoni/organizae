from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from app.modules.assistant.financial_schemas import (
    CashFlowArguments,
    CategoryReportArguments,
    FinancialCategoryArguments,
    FinancialPeriod,
    InvalidFinancialPeriodError,
    PendingEntriesArguments,
)
from app.modules.financial.exceptions import FinancialReportError
from app.modules.financial.service import FinancialReportService
from app.modules.financial_categories.exceptions import FinancialCategoryError
from app.modules.financial_categories.service import FinancialCategoryService
from app.modules.financial_entries.exceptions import FinancialEntryError
from app.modules.financial_entries.models import FinancialEntryStatus
from app.modules.financial_entries.service import FinancialEntryService


class FinancialTools:
    """Read adapters; financial calculations belong to the existing Services."""

    def __init__(
        self,
        reports: FinancialReportService,
        entries: FinancialEntryService,
        categories: FinancialCategoryService,
        tz: ZoneInfo,
    ) -> None:
        self.reports = reports
        self.entries = entries
        self.categories = categories
        self.tz = tz

    def execute(self, name: str, arguments: BaseModel, *, business_id: UUID) -> dict:
        try:
            return self._execute(name, arguments, business_id=business_id)
        except InvalidFinancialPeriodError:
            return {
                "code": "invalid_financial_period",
                "error": "Informe um período válido. Fluxo de caixa e rentabilidade exigem datas e intervalo máximo de 366 dias.",
            }
        except FinancialCategoryError:
            return {
                "code": "financial_category_unavailable",
                "error": "Categoria financeira não encontrada ou indisponível nesta empresa. Consulte as categorias antes de informar o ID.",
            }
        except (FinancialReportError, FinancialEntryError):
            return {
                "code": "financial_query_rejected",
                "error": "A consulta financeira foi recusada. Confira o período e os filtros; nenhum valor foi obtido.",
            }

    def _execute(self, name: str, arguments: BaseModel, *, business_id: UUID) -> dict:
        if isinstance(arguments, FinancialCategoryArguments):
            categories = self.categories.list(
                business_id=business_id,
                category_type=arguments.entry_type,
                offset=arguments.offset,
                limit=arguments.limit + 1,
            )
            return {
                "items": [
                    {"id": str(item.id), "name": item.name, "type": item.type.value}
                    for item in categories[: arguments.limit]
                ],
                "offset": arguments.offset,
                "limit": arguments.limit,
                "has_more": len(categories) > arguments.limit,
            }
        pending = isinstance(arguments, PendingEntriesArguments)
        period = arguments.period or FinancialPeriod(
            kind="all_time" if pending else "this_month"
        )
        start, end = period.resolve(self.tz)
        if name in ("get_cash_flow", "get_financial_profitability") and (
            start is None or end is None or (end - start).days >= 366
        ):
            raise InvalidFinancialPeriodError()
        category_id = getattr(arguments, "category_id", None)
        if category_id is not None:
            self.categories.get_by_id(category_id, business_id=business_id)
        filters = {"business_id": business_id, "start_date": start, "end_date": end}
        envelope = {
            "period": {
                "kind": period.kind,
                "start_date": start.isoformat() if start else None,
                "end_date": end.isoformat() if end else None,
                "inclusive": True,
            },
            "timezone": self.tz.key,
            "date_basis": "paid_at_local_for_paid_due_date_for_pending",
        }
        if pending:
            entries = self.entries.list(
                **filters,
                category_id=category_id,
                entry_type=arguments.entry_type,
                status=FinancialEntryStatus.PENDING,
                offset=arguments.offset,
                limit=arguments.limit + 1,
            )
            return {
                **envelope,
                "date_basis": "due_date",
                "status": "PENDING",
                "items": [
                    {
                        "id": str(item.id),
                        "category_id": str(item.category_id),
                        "description": item.description,
                        "type": item.type.value,
                        "amount": str(item.amount),
                        "due_date": item.due_date.isoformat(),
                        "status": item.status.value,
                    }
                    for item in entries[: arguments.limit]
                ],
                "has_data": bool(entries),
                "has_more": len(entries) > arguments.limit,
                "offset": arguments.offset,
                "limit": arguments.limit,
            }
        if name == "get_financial_summary":
            result = self.reports.summary(**filters, category_id=category_id)
            has_data = any(
                (
                    result.paid_income,
                    result.paid_expenses,
                    result.pending_income,
                    result.pending_expenses,
                )
            )
        elif isinstance(arguments, CashFlowArguments):
            result = self.reports.cash_flow(
                **filters, category_id=category_id, group_by=arguments.group_by
            )
            envelope["date_basis"] = "paid_at_local"
            has_data = bool(result.items)
        elif isinstance(arguments, CategoryReportArguments):
            result = self.reports.categories(
                **filters, category_id=category_id, entry_type=arguments.entry_type
            )
            has_data = bool(result.items)
        elif name == "get_financial_profitability":
            result = self.reports.profitability(**filters)
            envelope["date_basis"] = "paid_at_local"
            has_data = bool(
                result.current_period.paid_income or result.current_period.paid_expenses
            )
        else:
            raise ValueError("Unsupported financial read tool")
        return {
            **envelope,
            "has_data": has_data,
            "data": result.model_dump(mode="json"),
        }
