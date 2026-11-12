# US-027 — Consultas financeiras pela assistente

A assistente consulta o módulo financeiro por Function Calling nativo. Não há Text-to-SQL, cálculos financeiros duplicados, escrita financeira ou insights automáticos. As ferramentas chamam os mesmos Services dos endpoints financeiros.

## Ferramentas de leitura

| Ferramenta | Service reutilizado | Resultado |
| --- | --- | --- |
| `get_financial_summary` | `FinancialReportService.summary` | Receitas recebidas, despesas pagas, saldo e receitas/despesas pendentes separadamente. |
| `get_cash_flow` | `FinancialReportService.cash_flow` | Fluxo realizado por dia ou mês, somente pagamentos. |
| `get_financial_category_report` | `FinancialReportService.categories` | Totais pagos e pendentes por categoria e tipo. |
| `list_financial_categories` | `FinancialCategoryService.list` | Categorias e IDs reais, inclusive categorias sem lançamentos. |
| `list_pending_financial_entries` | `FinancialEntryService.list` | Lançamentos PENDING, com filtro INCOME/EXPENSE e paginação. |
| `get_financial_profitability` | `FinancialReportService.profitability` | Resultado e margem financeira, comparação anterior e evolução já calculadas pelo módulo. |

As ferramentas não recalculam saldos, percentuais, rentabilidade ou totais. Valores Decimal são enviados como texto, sem conversão para float. Margem financeira não equivale a lucro contábil; quando o Service retorna margem null, a assistente deve informar que ela é indefinida por ausência de receita paga.

## Uso

Após login no Swagger e autorização com o JWT, use o endpoint existente `POST /api/v1/assistant/chat`:

```json
{"message": "Quanto recebi este mês?"}
```

Outros exemplos: “Quanto gastei em outubro?”, “Qual minha margem financeira?”, “Quais despesas estão pendentes?”, “Mostre o fluxo de caixa de 01/10/2026 a 31/10/2026” e “Quais categorias de despesas tenho?”.

O contrato HTTP continua igual. Para manter a conversa, reutilize `conversation_id`. O Gemini transforma a pergunta em argumentos estruturados, e o backend valida e resolve os períodos. Testes simulam as chamadas do Gemini; não fazem avaliação de linguagem natural contra uma API real.

## Períodos e fuso

O seletor opcional `period` aceita:

- `today`, `yesterday`, `this_month`, `last_month`, `this_year` e `last_year`;
- `last_7_days` e `last_30_days`, incluindo hoje;
- `month`, com `month` de 1 a 12 e `year` opcional;
- `custom`, com `start_date` e `end_date` ISO;
- `all_time`, sem datas, para resumo, categorias e pendências.

Exemplos de argumentos gerados pelo modelo:

```json
{"period": {"kind": "month", "month": 10, "year": 2026}}
```

```json
{"period": {"kind": "custom", "start_date": "2026-10-01", "end_date": "2026-10-31"}, "entry_type": "EXPENSE"}
```

Os argumentos acima pertencem às ferramentas, não ao corpo público do chat. Não se deve enviar esses campos diretamente ao endpoint HTTP.

O relógio usa `BUSINESS_TIMEZONE`, a mesma configuração utilizada pelos relatórios financeiros e pela agenda. No modelo atual esse fuso é compartilhado pela aplicação; não foi criado um novo cadastro de fuso por empresa. Datas retornadas são inclusivas. Mês/ano são intervalos completos, e mês sem ano usa sua ocorrência mais recente que não seja futura. Assim, em novembro de 2026, “outubro” corresponde a outubro de 2026; em janeiro de 2026, corresponde a outubro de 2025. Ano explícito prevalece.

Relatórios sem período usam o mês atual completo. Pendências sem período abrangem todas as datas, para não ocultar despesas vencidas de meses anteriores. Fluxo e rentabilidade exigem datas e têm limite de 366 dias por consulta, para limitar respostas agrupadas; intervalos maiores devem ser divididos. Resumo agregado e listagem paginada de pendências não recebem essa restrição.

Resultados informam `period`, `timezone` e `date_basis`:

- Pagos usam a data de `paid_at` convertida ao fuso configurado.
- Pendentes usam `due_date`; nunca entram como receita recebida ou despesa paga.
- Cancelados são excluídos conforme os Services existentes.

Catálogo de categorias é independente de período. Catálogo e pendências aceitam `offset` e `limit` (padrão 20, máximo 50) e retornam `has_more`. A assistente não deve apresentar o valor de uma página como total geral.

## Segurança e falhas

O router injeta os Services com a sessão existente e o `business_id` determinado pelo usuário autenticado. Nenhuma ferramenta aceita `business_id`, `user_id`, SQL ou fuso fornecido pelo modelo. IDs de categorias são validados pela empresa antes da consulta; categorias de outra empresa não são acessíveis.

As novas ferramentas só possuem métodos de leitura. O fluxo de confirmação das ferramentas anteriores continua funcionando, e não foram adicionadas operações financeiras ao registro de escrita. Histórico, contagem de tokens e limite de chamadas são preservados.

Sem dados, os relatórios retornam zeros ou listas vazias e `has_data=false`, sem inventar causas. Erros de período/filtros e categorias produzem erros estruturados na resposta da ferramenta, para que a assistente peça correção. Argumentos que violam o schema são recusados pelo tratamento existente `assistant_invalid_tool_call`. Falhas SQLAlchemy encerram a requisição com `assistant_database_unavailable` e rollback, sem expor SQL ou detalhes internos.

## Validação

Em `apps/api/`:

```bash
uv run pytest tests/test_assistant_financial.py tests/test_assistant_financial_integration.py
uv run pytest
uv run ruff check app/modules/assistant tests/test_assistant_financial.py tests/test_assistant_financial_integration.py
```

Os testes novos cobrem períodos relativos, meses/anos, ano bissexto, mudança de mês entre UTC e fuso da empresa, parâmetros inválidos, ausência de dados, paginação, falhas e isolamento por JWT/categoria. A integração usa os Services e Repositories reais com SQLite descartável e o mesmo adaptador de timezone dos testes financeiros existentes. O Gemini é simulado e nenhuma credencial ou dado de produção é usado.

Nesta entrega: 68 testes novos passaram. Na suíte completa, 1736 passaram e 21 testes PostgreSQL foram ignorados sem conexão de teste habilitada. Permanecem duas falhas preexistentes no benchmark de tokens (`test_prompt_and_schema_comparison_against_equivalent_static_baseline` e `test_reproducible_estimated_token_comparison`), reproduzidas na cópia original antes de aplicar a US-027. Elas comparam o prompt expandido por histórias anteriores com uma baseline antiga; não foram removidas nem alteradas.
