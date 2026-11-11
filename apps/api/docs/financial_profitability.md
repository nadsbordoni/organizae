# Financeiro — Etapa 4: rentabilidade financeira

`GET /api/v1/financial/reports/profitability?start_date=2026-01-01&end_date=2026-01-31`

Exige JWT de usuário ativo com empresa. Usa exclusivamente `current_user.business_id`, inclusive no período anterior e na série mensal. `start_date` e `end_date` são obrigatórias e inclusivas. Datas inválidas, intervalo invertido ou período anterior impossível de representar retornam 422.

## Base de cálculo

Reutiliza o fluxo de caixa mensal da Etapa 3 (`FinancialReportService.cash_flow` → `FinancialReportRepository.cash_flow`). São feitas duas consultas agregadas, uma por período, sem carregar os lançamentos individualmente e sem executar commit ou escrever dados.

Considera apenas `FinancialEntry.status=PAID`, pela data efetiva `paid_at` no fuso `BUSINESS_TIMEZONE`. Ignora pendentes e cancelados, independentemente do vencimento. Lançamentos gerados por recorrência entram uma vez quando pagos; o template da recorrência não entra nos cálculos.

- `paid_income`: receitas recebidas.
- `paid_expenses`: despesas pagas.
- `financial_result`: receitas recebidas menos despesas pagas.
- `financial_margin_percentage`: resultado financeiro dividido pelas receitas recebidas, multiplicado por 100.

Todos os valores e percentuais usam `Decimal`, com percentuais arredondados a duas casas (ROUND_HALF_UP) e serializados como strings. Resultado e margem podem ser negativos. A margem será `null` se não houver receita, mesmo que existam despesas; sem base de receita, o percentual não é definido. Quando há receita e resultado zero, a margem é `"0.00"`.

A margem total usa os totais do período, sem fazer a média das margens mensais.

## Período anterior equivalente

Conforme a regra definida para esta etapa:

- Quando o intervalo cobre meses completos, compara com a mesma quantidade de meses completos imediatamente anteriores. Exemplo: 01–30/04 compara com 01–31/03. Janeiro a março compara com outubro a dezembro.
- Nos demais casos, compara com os dias imediatamente anteriores, em igual quantidade inclusiva. Exemplo: 05–06/01 compara com 03–04/01.

Os intervalos efetivos são devolvidos em `current_period` e `previous_period`, evitando ambiguidade no frontend.

## Resposta

```json
{
  "current_period": {
    "start_date": "2026-01-01",
    "end_date": "2026-01-31",
    "paid_income": "170.30",
    "paid_expenses": "57.00",
    "financial_result": "113.30",
    "financial_margin_percentage": "66.53"
  },
  "previous_period": {
    "start_date": "2025-12-01",
    "end_date": "2025-12-31",
    "paid_income": "10.00",
    "paid_expenses": "0.00",
    "financial_result": "10.00",
    "financial_margin_percentage": "100.00"
  },
  "comparison": {
    "paid_income_change": "160.30",
    "paid_income_change_percentage": "1603.00",
    "paid_expenses_change": "57.00",
    "paid_expenses_change_percentage": null,
    "financial_result_change": "103.30",
    "financial_result_change_percentage": "1033.00",
    "financial_margin_change_percentage_points": "-33.47"
  },
  "monthly_evolution": [
    {
      "period": "2026-01-01",
      "paid_income": "170.30",
      "paid_expenses": "57.00",
      "financial_result": "113.30",
      "financial_margin_percentage": "66.53"
    }
  ]
}
```

As variações monetárias são atual menos anterior. A variação percentual é `(atual - anterior) / abs(anterior) × 100`, com `null` quando o valor anterior é zero. Usar o valor absoluto como base mantém o sentido de melhora/piora para resultados anteriores negativos: passar de −100 para −50 resulta em +50%.

A variação da margem é a diferença entre as margens exibidas, em **pontos percentuais**, e será `null` se qualquer margem for indefinida. Aumento de despesas aparece como variação positiva de despesas; a API não atribui rótulos de melhora/piora a esse indicador.

`monthly_evolution` contém todos os meses do período selecionado, em ordem cronológica. `period` é o primeiro dia do mês. Meses sem pagamentos têm valores zerados e margem `null`. Em meses parcialmente selecionados, os valores abrangem somente os dias dentro do filtro.

Sem movimentações, receitas, despesas e resultado são `"0.00"`, a margem e variações percentuais sem base são `null`. A série mensal permanece disponível com os meses zerados.

## Escopo e testes

Este relatório representa rentabilidade **financeira em regime de caixa**. Não calcula lucro contábil, rentabilidade por serviço, custo por atendimento, ponto de equilíbrio ou impostos estimados. Não cria tabelas, migrations, alterações no frontend ou IA. Os contratos da Etapa 3 permanecem inalterados.

```bash
uv run pytest tests/test_financial_profitability.py tests/test_financial_profitability_postgresql.py
```

Os testes PostgreSQL usam `TEST_POSTGRES_URL` em um banco descartável `organizae_test*`, com `btree_gist` e schemas temporários removidos ao concluir. Não aplicam migrations.
