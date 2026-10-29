# Esse arquivo será responsável por ler as variáveis de ambiente.
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# BaseSettings lê as configurações do .env, enquanto URL.create() monta a conexão sem problemas com caracteres especiais na senha.
ROOT_DIR = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    DB_HOST: str
    DB_PORT: int = 5432
    DB_NAME: str
    DB_USER: str
    DB_PASSWORD: str
    JWT_SECRET_KEY: SecretStr = SecretStr("")
    JWT_ALGORITHM: Literal["HS256"] = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, gt=0)
    GEMINI_API_KEY: SecretStr = SecretStr("")
    GEMINI_MODEL: str = "gemini-3.1-flash-lite"
    GEMINI_TIMEOUT_MS: int = Field(default=30000, gt=0)
    ASSISTANT_CONTEXT_TOKEN_LIMIT: int = Field(default=8192, gt=0)
    APP_ENV: Literal["development", "test", "production"] = "production"
    ASSISTANT_WRITES_ENABLED: bool = False

    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    @property
    def database_url(self) -> str:
        from sqlalchemy.engine import URL

        return URL.create(
            drivername="postgresql+psycopg",
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME,
        )


settings = Settings()
