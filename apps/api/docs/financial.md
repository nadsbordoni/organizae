# Financeiro — Etapa 1

Backend de categorias financeiras e lançamentos manuais, separado das categorias de produtos/serviços.

## Categorias

Todos os endpoints exigem JWT e usam a empresa do usuário autenticado.

- `POST /api/v1/financial-categories`: criar com `name` e `type` (`INCOME` ou `EXPENSE`).
- `GET /api/v1/financial-categories`: listar, com `type`, `offset` e `limit` opcionais.
- `GET /api/v1/financial-categories/{id}`: consultar.
- `PATCH /api/v1/financial-categories/{id}`: alterar nome ou tipo.
- `DELETE /api/v1/financial-categories/{id}`: excluir categoria sem lançamentos.

Nomes são únicos por empresa e tipo, sem diferenciar maiúsculas/minúsculas ou espaços nas extremidades. Uma categoria referenciada não pode ser excluída nem mudar de tipo; pode ser renomeada.

## Lançamentos

- `POST /api/v1/financial-entries`: criar com `category_id`, `type`, `description`, `amount`, `due_date` e `appointment_id` opcional.
- `GET /api/v1/financial-entries`: listar com `start_date`, `end_date`, `type`, `category_id`, `status`, `offset` e `limit`.
- `GET /api/v1/financial-entries/{id}`: consultar.
- `PATCH /api/v1/financial-entries/{id}`: editar lançamento não pago.
- `DELETE /api/v1/financial-entries/{id}`: excluir lançamento não pago.
- `POST /api/v1/financial-entries/{id}/pay`: registrar pagamento/recebimento.

O período filtra **vencimento** (`due_date`), com limites inclusivos. A listagem retorna vencimentos mais recentes primeiro. A paginação padrão é `offset=0`, `limit=100`, com limite máximo 100.

Valores são positivos para receitas e despesas; o tipo determina o sentido do lançamento. Use valores decimais, por exemplo `"123.45"`, com até duas casas e limite `9999999999.99`. O banco utiliza `Numeric(12, 2)`; a API retorna valores monetários como strings.

A categoria precisa pertencer à mesma empresa e ter o mesmo tipo do lançamento. O agendamento, se informado, deve pertencer à empresa. Chaves estrangeiras compostas também protegem essas relações no banco.

## Estados e pagamento

Um lançamento nasce como `PENDING`, com `paid_at=null`. Criar ou confirmar um agendamento não cria lançamento e não registra recebimento.

O `PATCH` permite `status=PENDING` ou `status=CANCELLED`; `PAID` e `paid_at` só são definidos pela operação de pagamento. Um cancelado pode voltar a pendente por edição explícita.

Para registrar pagamento/recebimento:

```http
POST /api/v1/financial-entries/{id}/pay
Authorization: Bearer <token>
Content-Type: application/json

{}
```

Opcionalmente, envie `{"paid_at": "2026-11-01T10:00:00-03:00"}`. O horário deve conter fuso e não pode estar no futuro. Se omitido, usa o horário atual em UTC.

Somente pendentes podem ser pagos. Registros pagos não podem ser editados, cancelados, excluídos ou pagos novamente; essas tentativas retornam `409`. Alterações concorrentes usam trava na linha do lançamento no PostgreSQL. A operação registra o valor integral; pagamentos parciais, estornos e recorrências não fazem parte desta etapa.

## Migration e testes

Migration: `8a41d2c6e930_create_financial_categories_and_entries.py`, após `7c3e9a1f5b28`. Cria apenas as duas tabelas financeiras e uma constraint única em `appointments(id, business_id)` para a referência multiempresa. Nenhum dado existente é convertido em receita.

Aplicação manual, a partir de `apps/api/`:

```bash
uv run alembic upgrade head
```

Testes específicos:

```bash
uv run pytest tests/test_financial_categories.py tests/test_financial_entries.py tests/test_financial_integrity.py tests/test_financial_migration.py
```

Os testes de concorrência em `tests/test_financial_concurrency.py` exigem `TEST_POSTGRES_URL` apontando para um banco descartável chamado `organizae_test*`, com a extensão `btree_gist`. Usam schemas temporários, removidos ao concluir. Nunca aponte esse parâmetro para um banco de produção.

## Recorrências mensais

A Etapa 2 está documentada em [recurring_entries.md](recurring_entries.md). As respostas de lançamentos incluem também `recurring_entry_id` e `competence`, ambos null para lançamentos manuais.
