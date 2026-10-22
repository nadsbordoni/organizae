from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# Register all relationship targets before the ORM configures its mappers.
from app.modules.business_categories.models import BusinessCategory  # noqa: F401
from app.modules.businesses.models import Business  # noqa: F401
from app.modules.professionals.models import Professional  # noqa: F401
from app.modules.services.models import Service  # noqa: F401

# create_engine() configura o acesso ao PostgreSQL.
engine = create_engine(settings.database_url, pool_pre_ping=True)

# SessionLocal cria sessões para executar operações no banco.
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False,)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
