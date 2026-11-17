# Financeiro — Etapa 3: dashboard e relatórios

Implementação de leitura em Router → Service → Repository, sem tabelas de indicadores, novas entidades ou migrations. Os endpoints alimentam os cards, gráficos de caixa e distribuição por categorias do protótipo.

## Autenticação e filtros

Todas as rotas exigem JWT de usuário ativo vinculado a empresa. A empresa vem exclusivamente de `current_user.business_id`. Não há parâmetro de empresa no contrato.

Filtros comuns opcionais:

- `start_date` e `end_date`: datas ISO, inclusivas. Podem ser usadas isoladamente; sem ambas, considera todo o histórico. Intervalo invertido retorna 422.
- `category_id`: UUID v4 da categoria financeira. Categorias de outra empresa ou inexistentes retornam o mesmo resultado vazio.

Para valores pagos, filtra-se pela data local do pagamento (`paid_at`), no fuso `BUSINESS_TIMEZONE`, já utilizado no projeto (padrão `America/Sao_Paulo`). A sessão PostgreSQL pode estar em outro fuso sem alterar os relatórios. Para pendentes, usa-se `due_date`, sem conversão de fuso.

Cancelados são excluídos. Não há conversão de agendamentos em receitas, nem soma dos templates de recorrência: somente linhas de `FinancialEntry` são agregadas, inclusive as geradas por recorrência. Cada lançamento entra uma vez.

Valores monetários e percentuais usam `Decimal` e são serializados como strings decimais. As consultas fazem SUM/CASE/GROUP BY no banco, sem carregar os lançamentos em memória.

## Resumo financeiro

`GET /api/v1/financial/summary?start_date=2026-01-01&end_date=2026-01-31`

```json
{
  "paid_income": "170.30",
  "paid_expenses": "57.00",
  "pending_income": "30.50",
  "pending_expenses": "17.25",
  "balance": "113.30"
}
```

`balance = paid_income - paid_expenses`. É o resultado das movimentações realizadas no período; não representa saldo bancário acumulado com saldo inicial, lucro por competência ou rentabilidade de serviços. Pendências, inclusive vencidas, permanecem separadas.

## Fluxo de caixa realizado

`GET /api/v1/financial/reports/cash-flow?group_by=month&start_date=2026-01-01&end_date=2026-01-31`

`group_by` aceita `day` (padrão) ou `month`. Considera somente `PAID`, agrupado por `paid_at` local.

```json
{
  "group_by": "month",
  "items": [
    {
      "period": "2026-01-01",
      "income": "170.30",
      "expenses": "57.00",
      "balance": "113.30"
    }
  ],
  "total_income": "170.30",
  "total_expenses": "57.00",
  "balance": "113.30"
}
```

Os itens vêm em ordem cronológica. `period` representa o dia ou o primeiro dia do mês. Filtros são aplicados antes do agrupamento; um intervalo que cobre parte do mês totaliza somente essa parte.

Dias/meses sem pagamentos não são preenchidos artificialmente. O frontend pode preencher lacunas com zero. Sem movimentações, `items=[]` e totais `"0.00"`.

## Relatório por categorias

`GET /api/v1/financial/reports/categories?start_date=2026-01-01&end_date=2026-01-31&type=INCOME`

Além dos filtros comuns, `type` aceita `INCOME` ou `EXPENSE`. A resposta contém `paid_income`, `paid_expenses`, `pending_income`, `pending_expenses` e `items` com:

- `category_id`, `category_name`, `type`.
- `paid_total` e `pending_total`.
- `paid_percentage` e `pending_percentage`.

O percentual pago divide o valor pago da categoria pelo total pago **do mesmo tipo** no conjunto filtrado; o pendente usa apenas o total pendente do mesmo tipo. Não se mistura receita com despesa nem valor recebido com previsão. Se o denominador for zero, o percentual será `"0.00"`.

Percentuais são arredondados a duas casas com ROUND_HALF_UP. A soma exibida pode diferir de 100 por arredondamento (por exemplo, três categorias iguais resultam em 33,33% cada). Ao filtrar uma única categoria, sua participação dentro do resultado é 100% quando há valor no estado correspondente.

Somente categorias com lançamentos elegíveis aparecem. Sem movimentações, os totais são zero e `items=[]`. A ordenação é por tipo, nome e ID.

## Escopo e validação

Não inclui exportação de PDF/planilhas, comparativo com período anterior, saldo inicial de contas, cálculo de impostos, rentabilidade por serviço, IA ou frontend.

Testes:

```bash
uv run pytest tests/test_financial_reports.py tests/test_financial_reports_postgresql.py
```

Os testes PostgreSQL exigem `TEST_POSTGRES_URL` apontando para um banco descartável `organizae_test*`, com extensão `btree_gist`. Utilizam schema temporário, removido ao terminar, sem executar migrations.

## Análise de rentabilidade financeira

A Etapa 4 acrescenta o endpoint de rentabilidade, evolução mensal e comparação entre períodos, documentado em [financial_profitability.md](financial_profitability.md). Os três endpoints desta etapa mantêm seus contratos.
