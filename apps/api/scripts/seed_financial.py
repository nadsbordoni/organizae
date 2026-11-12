"""Manual, deterministic financial fixtures. No database access on import."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.modules.businesses.models import Business
from app.modules.financial_categories.models import FinancialCategory, FinancialType
from app.modules.financial_categories.schemas import FinancialCategoryCreate
from app.modules.financial_entries.models import FinancialEntry, FinancialEntryStatus
from app.modules.financial_entries.schemas import FinancialEntryCreate
from app.modules.recurring_entries.models import RecurringEntry
from app.modules.recurring_entries.schemas import RecurringEntryCreate

MARKER = "[SEED-FIN-2026-V1]"
REFERENCE_DATE = date(2026, 11, 12)
START = date(2026, 5, 1)
END = date(2026, 11, 30)
INCOME = FinancialType.INCOME
EXPENSE = FinancialType.EXPENSE
PAID = FinancialEntryStatus.PAID
PENDING = FinancialEntryStatus.PENDING
CANCELLED = FinancialEntryStatus.CANCELLED

CATEGORIES = {
    "services": (INCOME, "Serviços"),
    "products": (INCOME, "Produtos"),
    "other": (INCOME, "Outras receitas"),
    "rent": (EXPENSE, "Aluguel"),
    "energy": (EXPENSE, "Energia"),
    "internet": (EXPENSE, "Internet"),
    "materials": (EXPENSE, "Materiais"),
    "maintenance": (EXPENSE, "Manutenção"),
    "software": (EXPENSE, "Software"),
}
# key, amount, due day: occurrences are included in the 182 entries, not added twice.
RECURRENCES = (
    ("rent", "1800.00", 5),
    ("energy", "320.00", 10),
    ("internet", "120.00", 12),
    ("materials", "450.00", 15),
    ("maintenance", "180.00", 20),
    ("software", "90.00", 8),
)
PENDING_OCCURRENCES = {
    (8, "energy"),
    (9, "internet"),
    (10, "energy"),
    (10, "maintenance"),
    (11, "energy"),
    (11, "internet"),
    (11, "materials"),
    (11, "maintenance"),
}


@dataclass(frozen=True)
class MonthPlan:
    month: int
    services: str
    products: str
    other: str
    materials: str
    maintenance: str
    pending_service: str
    pending_products: str


MONTHS = (
    MonthPlan(
        5, "4800.00", "1000.00", "200.00", "200.00", "100.00", "400.00", "200.00"
    ),
    MonthPlan(
        6, "6000.00", "1250.00", "250.00", "200.00", "100.00", "500.00", "250.00"
    ),
    MonthPlan(
        7, "7200.00", "1500.00", "300.00", "200.00", "100.00", "600.00", "300.00"
    ),
    MonthPlan(
        8, "5000.00", "1000.00", "300.00", "400.00", "300.00", "700.00", "350.00"
    ),
    MonthPlan(
        9, "2400.00", "450.00", "150.00", "200.00", "1300.00", "800.00", "400.00"
    ),
    MonthPlan(
        10, "3360.00", "700.00", "140.00", "600.00", "400.00", "900.00", "450.00"
    ),
    MonthPlan(
        11, "1400.00", "300.00", "100.00", "500.00", "250.00", "1200.00", "800.00"
    ),
)
EXPECTED_TOTALS = (
    ("2026-05", "6000.00", "3260.00", "2740.00", "600.00", "0.00"),
    ("2026-06", "7500.00", "3260.00", "4240.00", "750.00", "0.00"),
    ("2026-07", "9000.00", "3260.00", "5740.00", "900.00", "0.00"),
    ("2026-08", "6300.00", "3340.00", "2960.00", "1050.00", "320.00"),
    ("2026-09", "3000.00", "4340.00", "-1340.00", "1200.00", "120.00"),
    ("2026-10", "4200.00", "3460.00", "740.00", "1350.00", "500.00"),
    ("2026-11", "1800.00", "2640.00", "-840.00", "2000.00", "1070.00"),
)


class SeedError(ValueError):
    pass


@dataclass(frozen=True)
class EntryPlan:
    key: str
    category: str
    amount: Decimal
    due_date: date
    status: FinancialEntryStatus
    recurrence: str | None = None

    @property
    def competence(self) -> date | None:
        return self.due_date.replace(day=1) if self.recurrence else None

    @property
    def description(self) -> str:
        if self.recurrence:
            return f"{MARKER} Mensal | {CATEGORIES[self.category][1]}"
        return f"{MARKER} {self.due_date:%Y-%m} | {self.key}"

    def payment_time(self, tz: ZoneInfo) -> datetime | None:
        if self.status != PAID:
            return None
        paid_day = self.due_date + timedelta(days=1 if self.recurrence else 0)
        return datetime.combine(paid_day, time(17), tzinfo=tz).astimezone(UTC)


def split_amount(amount: str, count: int) -> list[Decimal]:
    cents, remainder = divmod(int(Decimal(amount) * 100), count)
    return [
        Decimal(cents + (remainder if index == count - 1 else 0)) / 100
        for index in range(count)
    ]


def build_plan() -> list[EntryPlan]:
    entries = []
    for month in MONTHS:

        def append(
            key: str,
            category: str,
            amount: str | Decimal,
            day: int,
            status: FinancialEntryStatus = PAID,
            recurrence: str | None = None,
            month_number: int = month.month,
        ) -> None:
            entries.append(
                EntryPlan(
                    key,
                    category,
                    Decimal(amount),
                    date(2026, month_number, day),
                    status,
                    recurrence,
                )
            )

        for index, amount in enumerate(split_amount(month.services, 10), 1):
            append(f"Serviços lote {index:02}", "services", amount, index)
        for index, amount in enumerate(split_amount(month.products, 3), 1):
            append(
                f"Produtos lote {index:02}", "products", amount, (3, 7, 10)[index - 1]
            )
        append("Outras entradas", "other", month.other, 11)
        append("Serviços a receber", "services", month.pending_service, 18, PENDING)
        append("Produtos a receber", "products", month.pending_products, 25, PENDING)
        append("Serviço cancelado", "services", "125.00", 22, CANCELLED)
        append("Materiais extras", "materials", month.materials, 10)
        append("Manutenção extra", "maintenance", month.maintenance, 11)
        append("Manutenção cancelada", "maintenance", "85.00", 23, CANCELLED)
        for key, amount, day in RECURRENCES:
            append(
                f"Mensal {key}",
                key,
                amount,
                day,
                PENDING if (month.month, key) in PENDING_OCCURRENCES else PAID,
                recurrence=key,
            )
    return entries


def fixture_id(business_id: UUID, key: str) -> UUID:
    # Hash-derived IDs retain v4 bits because public financial schemas require UUID4.
    digest = hashlib.sha256(
        f"organizae:financial-seed:v1:{business_id}:{key}".encode()
    ).digest()
    return UUID(bytes=digest[:16], version=4)


def safe_database_name(name: str | None) -> bool:
    normalized = (name or "").lower()
    return normalized == "organizae" or bool(
        re.fullmatch(r"organizae_(test|dev)(_[a-z0-9_]+)?", normalized)
    )


def guard_environment(app_env: str, database_name: str | None) -> None:
    if app_env not in ("development", "test"):
        raise SeedError("Seed bloqueado fora de development/test.")
    if not safe_database_name(database_name):
        raise SeedError(
            "Use organizae (desenvolvimento local), organizae_test[_...] ou organizae_dev[_...]."
        )


def guard_session(session: Session, app_env: str) -> None:
    bind = session.get_bind()
    if (
        app_env == "test"
        and bind.dialect.name == "sqlite"
        and bind.engine.url.database == ":memory:"
    ):
        return
    guard_environment(app_env, bind.engine.url.database)
    if bind.dialect.name != "postgresql":
        raise SeedError(
            "A execução manual exige PostgreSQL; SQLite só é aceito em testes em memória."
        )


def same_value(left: Any, right: Any) -> bool:
    if isinstance(left, datetime) and left.tzinfo is None:
        left = left.replace(tzinfo=UTC)
    return left == right


def ensure_record[SeedModel: (FinancialCategory, RecurringEntry, FinancialEntry)](
    session: Session,
    model: type[SeedModel],
    values: dict[str, Any],
    natural_key: ColumnElement[bool],
) -> tuple[SeedModel, bool]:
    matches = list(
        session.scalars(
            select(model)
            .where(
                model.business_id == values["business_id"],
                or_(model.id == values["id"], natural_key),
            )
            .limit(2)
        )
    )
    if len(matches) > 1:
        raise SeedError("Há mais de um registro com a identificação reservada do seed.")
    if matches:
        record = matches[0]
        if any(
            not same_value(getattr(record, field), value)
            for field, value in values.items()
            if field not in ("id", "created_at")
        ):
            raise SeedError(
                "Um registro identificado pelo seed foi alterado. Nada será sobrescrito; use outra empresa de testes."
            )
        return record, False
    record = model(**values)
    session.add(record)
    session.flush()
    return record, True


def preview() -> dict[str, Any]:
    keys = (
        "month",
        "paid_income",
        "paid_expenses",
        "balance",
        "pending_income",
        "pending_expenses",
    )
    return {
        "marker": MARKER,
        "reference_date": REFERENCE_DATE.isoformat(),
        "planned": {
            "categories": 9,
            "recurrences": 6,
            "entries": 182,
            "recurring_occurrences": 42,
        },
        "statuses": {"PAID": 146, "PENDING": 22, "CANCELLED": 14},
        "expected_monthly_totals": [
            dict(zip(keys, row, strict=True)) for row in EXPECTED_TOTALS
        ],
    }


def seed_financial(
    session: Session,
    business_id: UUID,
    *,
    app_env: str,
    tz: ZoneInfo,
    now: datetime | None = None,
) -> dict[str, Any]:
    guard_session(session, app_env)
    now = now or datetime.now(UTC)
    if now.tzinfo is None or now.astimezone(tz).date() < REFERENCE_DATE:
        raise SeedError(
            "O cenário exige relógio com fuso e data local a partir de 12/11/2026."
        )
    if session.in_transaction():
        raise SeedError(
            "Abra uma sessão nova, sem transação pendente, para executar o seed."
        )
    created = {"categories": 0, "recurrences": 0, "entries": 0}
    plan = build_plan()
    if any(
        item.payment_time(tz) is not None and item.payment_time(tz) > now
        for item in plan
    ):
        raise SeedError(
            "O cenário contém pagamento futuro em relação ao relógio informado."
        )
    try:
        with session.begin():
            business = session.scalar(
                select(Business).where(Business.id == business_id).with_for_update()
            )
            if business is None:
                raise SeedError("Empresa de testes não encontrada.")
            categories = {}
            for key, (entry_type, label) in CATEGORIES.items():
                data = FinancialCategoryCreate(
                    name=f"{MARKER} {label}", type=entry_type
                )
                values = {
                    "id": fixture_id(business_id, f"category:{key}"),
                    "business_id": business_id,
                    **data.model_dump(),
                }
                category, inserted = ensure_record(
                    session,
                    FinancialCategory,
                    values,
                    func.lower(FinancialCategory.name) == data.name.lower(),
                )
                categories[key] = category
                created["categories"] += inserted
            recurrences = {}
            for key, amount, day in RECURRENCES:
                data = RecurringEntryCreate(
                    category_id=categories[key].id,
                    type=EXPENSE,
                    description=f"{MARKER} Mensal | {CATEGORIES[key][1]}",
                    amount=amount,
                    due_day=day,
                    start_date=START,
                    end_date=END,
                )
                values = {
                    "id": fixture_id(business_id, f"recurrence:{key}"),
                    "business_id": business_id,
                    **data.model_dump(),
                }
                recurrence, inserted = ensure_record(
                    session,
                    RecurringEntry,
                    values,
                    RecurringEntry.description == data.description,
                )
                recurrences[key] = recurrence
                created["recurrences"] += inserted
            for item in plan:
                data = FinancialEntryCreate(
                    category_id=categories[item.category].id,
                    type=CATEGORIES[item.category][0],
                    description=item.description,
                    amount=item.amount,
                    due_date=item.due_date,
                )
                recurring_id = (
                    recurrences[item.recurrence].id if item.recurrence else None
                )
                natural = (
                    (FinancialEntry.recurring_entry_id == recurring_id)
                    & (FinancialEntry.competence == item.competence)
                    if recurring_id
                    else FinancialEntry.description == item.description
                )
                values = {
                    "id": fixture_id(
                        business_id, f"entry:{item.due_date:%Y-%m}:{item.key}"
                    ),
                    "business_id": business_id,
                    **data.model_dump(),
                    "status": item.status,
                    "paid_at": item.payment_time(tz),
                    "recurring_entry_id": recurring_id,
                    "competence": item.competence,
                    "created_at": datetime.combine(
                        item.due_date.replace(day=1), time(10), tzinfo=tz
                    ).astimezone(UTC),
                }
                _, inserted = ensure_record(session, FinancialEntry, values, natural)
                created["entries"] += inserted
    except IntegrityError:
        raise SeedError(
            "Conflito de integridade ou execução concorrente. A transação foi revertida; nenhum dado foi sobrescrito."
        ) from None
    totals = {"categories": 9, "recurrences": 6, "entries": 182}
    return {
        **preview(),
        "business_id": str(business_id),
        "created": created,
        "preserved": {key: totals[key] - value for key, value in created.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed financeiro fictício, manual e idempotente."
    )
    parser.add_argument(
        "--business-id", type=UUID, help="UUID da empresa de testes existente."
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Mostra o plano e os totais, sem acessar o banco.",
    )
    args = parser.parse_args(argv)
    if args.preview:
        print(json.dumps(preview(), ensure_ascii=False, indent=2))
        return 0
    if args.business_id is None:
        parser.error("--business-id é obrigatório para inserir dados.")
    from app.core.config import settings

    try:
        guard_environment(settings.APP_ENV, settings.DB_NAME)
        from app.db.session import SessionLocal

        with SessionLocal() as session:
            result = seed_financial(
                session,
                args.business_id,
                app_env=settings.APP_ENV,
                tz=ZoneInfo(settings.BUSINESS_TIMEZONE),
            )
    except SeedError as exc:
        parser.exit(2, f"Seed recusado: {exc}\n")
    except SQLAlchemyError:
        parser.exit(
            1,
            "Falha de banco. A transação foi revertida; confira conexão, migrations e permissões.\n",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
