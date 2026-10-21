from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

#create_engine() configura o acesso ao PostgreSQL.
engine = create_engine(settings.database_url, pool_pre_ping=True)

#SessionLocal cria sessões para executar operações no banco.
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)