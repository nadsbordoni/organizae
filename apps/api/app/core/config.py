#Esse arquivo será responsável por ler as variáveis de ambiente.
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


#BaseSettings lê as configurações do .env, enquanto URL.create() monta a conexão sem problemas com caracteres especiais na senha.
ROOT_DIR = Path(__file__).resolve().parents[4]

class Settings(BaseSettings):
    DB_HOST: str
    DB_PORT: int = 5432
    DB_NAME: str
    DB_USER: str
    DB_PASSWORD: str

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        extra="ignore"
    )

    @property
    def database_url(self) -> str:
        from sqlalchemy.engine import URL

        return URL.create(
            drivername="postgresql+psycopg",
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME
        )

settings = Settings()