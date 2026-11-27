# Execução com Docker

Execute os comandos na raiz do repositório. É necessário Docker com suporte a
containers Linux e Docker Compose v2 ou superior. No Windows, inicie o Docker
Desktop antes de executar os comandos.

## Preparação

Copie `.env.example` para `.env` (PowerShell):

```powershell
Copy-Item .env.example .env
```

Se o `.env` já existir, preserve-o. Preencha `DB_NAME`, `DB_USER`, `DB_PASSWORD`
e `JWT_SECRET_KEY`. Gere uma chave JWT com pelo menos 32 bytes aleatórios; não
use os valores de exemplo como credenciais reais nem versione o `.env`.
`GEMINI_API_KEY` só é necessária para usar a assistente.

Dentro dos containers, o Compose define `DB_HOST=db` e `DB_PORT=5432`, mesmo
que o `.env` use `localhost`. O PostgreSQL fica acessível apenas na rede interna
do Compose. API e frontend ficam publicados apenas em localhost.

## Iniciar

```bash
docker compose config --quiet
docker compose up --build -d
docker compose ps -a
docker compose logs migrate api
```

O Compose espera o PostgreSQL ficar pronto e executa `alembic upgrade head` no
serviço `migrate`. A API só inicia se a migration terminar com sucesso; o serviço
`migrate` aparecer como `Exited (0)` é esperado.

- Frontend: http://localhost:4321
- Documentação da API: http://localhost:8000/docs
- Saúde da API: http://localhost:8000/health

As portas podem ser alteradas com `API_PORT` e `FRONTEND_PORT` no `.env`.
O frontend usa o Astro e seu adaptador Node standalone já existentes, incluindo
as rotas dinâmicas do painel. As telas continuam usando os dados de exemplo
existentes; a configuração Docker não implementa integração com a API.

## Dados de teste (seed)

Depois do `migrate`, o serviço `seed` executa `python -m scripts.seed --test-business`:

1. `scripts.seed_test_business` cria, se ainda não existir, a empresa fictícia
   **Barbearia Fictícia [SEED]** com o ID fixo `00000000-0000-4000-8000-000000000001`.
2. As seeds operacional e financeira (`docs/OPERATIONAL_SEED.md` e
   `docs/FINANCIAL_SEED.md`) populam essa empresa.

Para entrar no painel como dono dessa empresa, defina no `.env`:

```env
SEED_USER_EMAIL=dono.testes@example.com
SEED_USER_PASSWORD=uma-senha-local-de-8-ou-mais
```

O login é criado uma única vez, com a senha guardada como hash. Execuções seguintes
não alteram uma conta existente, nem a senha. Se o e-mail já pertencer a outra conta,
o seed recusa. Sem essas variáveis, só a empresa é criada.

Para popular outra empresa já cadastrada em vez da fictícia, preencha
`SEED_BUSINESS_ID` com o UUID dela.

```bash
docker compose run --rm seed
docker compose logs seed
```

O seed exige `APP_ENV=development` ou `test` e um `DB_NAME` aceito pela seed
financeira (`organizae`, `organizae_test[_...]` ou `organizae_dev[_...]`). Ele é
idempotente: a cada `up` só cria o que estiver faltando. A API não depende do
seed; se ele falhar, a API sobe normalmente e o erro aparece em
`docker compose logs seed`. Fora do Docker, em `apps/api/`:
`uv run python -m scripts.seed --test-business`.

## Alembic

Consulte a versão aplicada e o head disponível:

```bash
docker compose run --rm migrate alembic current
docker compose run --rm migrate alembic heads
```

Após atualizar a branch ou adicionar migrations, reconstrua a imagem e aplique
as migrations explicitamente antes de recriar a API:

```bash
docker compose build api
docker compose run --rm migrate
docker compose up -d --build
```

Se uma migration falhar, consulte `docker compose logs migrate`. Corrija a causa
antes de iniciar a API; não use `alembic stamp head` para pular migrations.

Para criar migrations, use o ambiente local em `apps/api`, apontando para um
PostgreSQL de desenvolvimento acessível por ele:

```bash
uv sync --locked
uv run alembic revision --autogenerate -m "describe_schema_change"
```

Revise o arquivo gerado, versione-o e reconstrua a imagem. Não edite migrations
já compartilhadas. A geração local evita perder o arquivo dentro de um container
temporário; o banco do Compose não publica uma porta no host por padrão.

## Persistência e verificações

O volume nomeado `postgres_data` armazena os dados do PostgreSQL. Parar ou recriar
os containers preserva esse volume:

```bash
docker compose down
docker compose up -d
```

Não use `docker compose down -v` para uma parada normal: essa opção remove o
volume e os dados. Alterar usuário, senha ou nome do banco no `.env` não
reconfigura automaticamente um volume já inicializado.

Para verificar o ambiente, confira `/health`, `/docs`, a página inicial e
`/painel` do frontend. Em um banco de desenvolvimento, crie um registro pela API,
execute os comandos de parada e subida acima e confirme que ele continua lá.

O build do frontend executa `npm run build`, que inclui a checagem de tipos e do
lockfile. Para testes de negócio e lint do backend, use o ambiente local em
`apps/api`; a imagem de execução não instala dependências de desenvolvimento:

```bash
uv run pytest
uv run ruff check .
```

Use banco de teste separado para testes que acessam PostgreSQL. Não aponte os
testes para dados de produção ou para o banco compartilhado da equipe.

O Dockerfile da API fixa a versão do uv e instala as dependências com
`uv sync --locked`, seguindo o [guia oficial de uv com Docker](https://docs.astral.sh/uv/guides/integration/docker/).
