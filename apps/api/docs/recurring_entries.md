# Financeiro — Etapa 2: recorrências mensais

Todas as rotas exigem JWT e usam a empresa do usuário autenticado. O cliente não envia `business_id`.

## Cadastro e suspensão

- `POST /api/v1/recurring-entries`: criar.
- `GET /api/v1/recurring-entries`: listar com `is_active`, `type`, `category_id`, `offset` e `limit` (máximo 100).
- `GET /api/v1/recurring-entries/{id}`: consultar.
- `PATCH /api/v1/recurring-entries/{id}`: editar os dados ou suspender/reativar por `is_active`.
- `DELETE /api/v1/recurring-entries/{id}`: somente desativar, sem apagar recorrência ou lançamentos.

Exemplo de criação:

```json
{
  "category_id": "<uuid da categoria financeira>",
  "type": "EXPENSE",
  "description": "Aluguel",
  "amount": "1500.00",
  "due_day": 31,
  "start_date": "2026-01-01",
  "end_date": null,
  "is_active": true
}
```

Categorias precisam pertencer à empresa e ter o mesmo tipo (`INCOME` ou `EXPENSE`). Categorias vinculadas a recorrências, mesmo inativas, não podem ser excluídas nem mudar de tipo.

Valores usam `Decimal`/`Numeric(12, 2)`, são positivos e têm até duas casas. `due_day` aceita inteiros de 1 a 31. `end_date`, se informado, deve ser maior ou igual a `start_date`; pode ser removido por PATCH com null.

As datas delimitam **vencimentos inclusivos**. Quando o dia não existe no mês, usa-se o último dia válido (31 de fevereiro vira 28 ou 29). Se o início for posterior ao vencimento daquele mês, o primeiro lançamento ocorre no próximo mês elegível.

Criar ou editar uma recorrência não gera lançamentos automaticamente. Edições afetam somente competências ainda não geradas: lançamentos pagos, pendentes e cancelados existentes são preservados.

## Geração explícita e idempotente

`POST /api/v1/recurring-entries/{id}/generate`

```json
{
  "start_month": "2026-01-01",
  "end_month": "2026-12-01"
}
```

As competências devem usar o primeiro dia do mês. São aceitos de 1 a 12 meses inclusivos por requisição, inclusive períodos passados. Para períodos maiores, faça chamadas consecutivas.

A resposta contém `created_entries` e `skipped_competences` (competências já geradas). Meses fora das datas da recorrência são ignorados. Os lançamentos nascem `PENDING`, sem pagamento e sem agendamento vinculado. Não há scheduler nesta etapa; o painel chama a geração explicitamente.

A geração bloqueia a recorrência na transação PostgreSQL, também usada por edição e suspensão. A constraint UNIQUE em `(recurring_entry_id, competence)` impede duplicações no banco. O lote inteiro é confirmado ou revertido.

Suspender impede novas gerações e não cancela nem remove lançamentos anteriores. Reativar permite gerar competências faltantes dentro do período solicitado. Não há controle de intervalos históricos de suspensão: para não cobrar um mês omitido, evite solicitá-lo ou gere e cancele explicitamente seu lançamento.

Os lançamentos gerados aparecem no CRUD financeiro com `recurring_entry_id` e `competence`. O CRUD manual não permite alterar esses identificadores. Lançamentos de recorrência podem ser editados/cancelados enquanto não pagos; não podem ser excluídos fisicamente, preservando a identificação da competência e evitando recriação acidental. Pagos mantêm o bloqueio de edição e exclusão da Etapa 1.

## Migration e testes

Migration `9b72e4f1a603`, após `8a41d2c6e930`: cria recorrências e adiciona duas colunas opcionais e constraints aos lançamentos. Lançamentos manuais existentes permanecem sem recorrência/competência, sem alteração de dados.

Aplicação manual em `apps/api`:

```bash
uv run alembic upgrade head
```

Testes:

```bash
uv run pytest tests/test_recurring_entries.py tests/test_recurring_integrity.py tests/test_recurring_migration.py tests/test_recurring_concurrency.py
```

Concorrência exige `TEST_POSTGRES_URL` apontando para PostgreSQL descartável `organizae_test*`, com `btree_gist`. Nenhuma migration é aplicada automaticamente.
