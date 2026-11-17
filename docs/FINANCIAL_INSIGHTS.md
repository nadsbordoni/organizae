# US-029 — Insights financeiros automáticos

`GET /api/v1/financial/insights` analisa os dados mais recentes da empresa autenticada e retorna alertas estruturados, sem precisar enviar uma pergunta à assistente. Não exige migrations, novas dependências ou persistência de insights.

## Consulta

Exige JWT de usuário ativo vinculado à empresa. O escopo vem exclusivamente da autenticação; `business_id`, `user_id`, fuso ou data de referência não são aceitos como parâmetros do cliente.

| Parâmetro | Padrão | Uso |
| --- | --- | --- |
| `month` | Mês atual | Data ISO do primeiro dia do mês, por exemplo `2026-10-01`. Aceita o mês atual e meses anteriores. |
| `explain` | `true` | Gera explicações contextualizadas pelo Gemini quando configurado, reutilizando o cache para fatos idênticos. `false` usa as orientações padrão, sem chamar a IA. |

Exemplo: `GET /api/v1/financial/insights?month=2026-10-01&explain=false`.

A detecção e os valores são atualizados a cada consulta ao endpoint, sem precisar enviar uma pergunta à assistente. A interface deve consultar esse endpoint ao carregar ou atualizar seus indicadores; essa integração de frontend não faz parte deste módulo. Não há tarefas periódicas, notificações por e-mail ou WhatsApp nem execução automática de operações financeiras.

## Períodos e pagamentos

Meses passados são comparados integralmente com o mês anterior. Para o mês atual, o intervalo é do dia 1 até a data local de referência, inclusive; a comparação usa os mesmos dias do mês anterior, limitados ao último dia disponível. Em 13/11/2026, compara 01–13/11 com 01–13/10. Em 30/03/2026, compara 01–30/03 com 01–28/02. No último dia do mês, compara meses completos. As datas efetivas são devolvidas na resposta, sem normalizar valores por dia.

Usa `BUSINESS_TIMEZONE`, atualmente compartilhado pela aplicação. Receitas recebidas e despesas pagas consideram somente `PAID`, pela data local de `paid_at`. Pendentes não entram no resultado realizado e cancelados são excluídos. Templates de recorrência não são contabilizados como lançamentos adicionais.

Despesas vencidas são `EXPENSE` com status `PENDING` e `due_date` estritamente anterior à data local atual. A busca abrange **todas as datas**, inclusive quando o mês selecionado é histórico. O vencimento de hoje não é considerado atraso, e o período desse insight vai do vencimento pendente mais antigo até ontem.

## Alertas e resposta

| Tipo | Critério | Severidade |
| --- | --- | --- |
| `REVENUE_DROP` | Receita recebida atual positiva e inferior a 80% da anterior. | `WARNING` |
| `EXPENSE_INCREASE` | Despesas pagas superiores a 120% das anteriores, com base anterior positiva. | `WARNING` |
| `NEGATIVE_RESULT` | Despesas pagas superiores às receitas recebidas. | `CRITICAL` |
| `OVERDUE_EXPENSES` | Uma ou mais despesas pendentes vencidas, agrupadas em um único alerta. | `WARNING` |

Queda ou aumento exatamente de 20% não dispara alerta. A decisão usa valores `Decimal` antes do arredondamento; percentuais exibidos mantêm as duas casas e o ROUND_HALF_UP dos relatórios. Uma variação ligeiramente superior ao limite pode, portanto, ser exibida arredondada como 20,00%.

Sem recebimentos registrados no intervalo atual, não há evidência suficiente para classificar falta de registros como queda de faturamento. O alerta de queda exige recebimentos positivos em ambos os períodos. Base anterior zero também não gera comparação percentual de aumento de despesas. O resultado negativo e as pendências continuam sendo avaliados pelos fatos disponíveis. Sem condições detectadas, retorna `insights: []`.

A resposta contém `reference_date`, `timezone`, `period`, `comparison_period`, `is_partial` e `insights`. Cada insight possui:

- `id`: UUID determinístico por empresa, tipo e intervalo efetivo do alerta, estável quando apenas os valores são atualizados. Em análises parciais, uma nova data final representa um novo intervalo; alertas vencidos com o mesmo intervalo mantêm o ID independentemente do mês selecionado;
- `type`, `title` e `description`: classificação e fatos calculados pelo backend;
- `period` e, quando aplicável, `comparison_period`;
- `values`: valores envolvidos, como `paid_income`, `previous_paid_income`, `paid_expenses`, `financial_result`, `overdue_amount` e `overdue_count`;
- `variation_percentage`, quando calculável; `severity` (`INFO`, `WARNING` ou `CRITICAL`) e `reference_date`;
- `explanation`, `suggested_actions` e `explanation_source` (`deterministic` ou `gemini`).

Valores monetários e percentuais são strings decimais; contagens são inteiros. Campos não aplicáveis são omitidos. Há no máximo um alerta por tipo na resposta. `INFO` está disponível no contrato; as regras desta etapa usam `WARNING` e `CRITICAL`.

## Reutilização e Gemini

O serviço reutiliza `FinancialReportService.profitability`, incluindo os cálculos de resultado e variações. O Service passou a aceitar internamente um intervalo de comparação explícito para a análise parcial; o endpoint e o comportamento padrão do relatório de rentabilidade continuam iguais.

São três consultas agregadas por análise: fluxo realizado atual, anterior e despesas vencidas. A agregação de vencidas usa os filtros e somatórios do Repository financeiro existente. Nenhuma lista completa de lançamentos é carregada e nenhuma escrita financeira é executada.

A integração reutiliza o `GeminiProvider`, incluindo timeout, retries e monitoramento de tokens. Com `explain=true` (padrão), o Gemini **gera explicações e sugestões contextualizadas**, em vez de selecionar textos de um catálogo. Recebe somente os fatos agregados dos alertas da empresa autenticada: tipo, severidade, valores já calculados, períodos, variação, referência, fuso e indicação de mês parcial. Identificadores de usuário/empresa, nomes, descrições de lançamentos e mensagens do usuário não são enviados.

O backend continua responsável pela detecção e por todos os cálculos. O Gemini recebe instruções para explicar fatos e implicações, distinguir receitas recebidas de pendentes e resultado realizado de lucro contábil, não atribuir causas sem evidência e formular sugestões de investigação de maneira condicional. Não há ferramentas de escrita nessa geração.

Para citar valores, percentuais, contagens e datas, o modelo deve usar marcadores, como `{{paid_income}}` e `{{period}}`, que o backend substitui pelos fatos corretos. A validação rejeita números literais, marcadores desconhecidos ou de outro alerta, HTML, URLs, campos extras, identificadores desconhecidos, respostas incompletas, ações repetidas e textos fora dos limites. A explicação precisa referenciar um fato financeiro e uma data/período. O lote inteiro é validado antes de alterar a resposta.

Fatos permanecem em `description` e `values`; somente `explanation`, `suggested_actions` e `explanation_source` podem ser enriquecidos. A validação estrutural e de marcadores reduz o risco de valores inventados, mas não comprova semanticamente toda frase gerada. As sugestões devem ser avaliadas pelo empreendedor e nenhuma ação é executada.

Sem chave Gemini, com `explain=false`, sem alertas ou em falhas/respostas inválidas da IA, a consulta mantém os insights e as orientações determinísticas do catálogo existente. Indisponibilidade do Gemini não transforma a resposta em erro HTTP.

## Consumo e limitações

Os textos gerados com marcadores são armazenados no cache de memória existente: até 256 entradas por processo, válidas por uma hora, com espera de 60 segundos antes de tentar novamente após uma falha. A chave separa empresa, modelo e versão da geração, e inclui um hash de todos os fatos enviados: valores, períodos, referência, tipo, severidade, fuso e indicação de mês parcial.

Consultas com os mesmos fatos reutilizam a explicação, sem nova chamada ao Gemini. Uma mudança nos fatos invalida a reutilização e solicita nova explicação, mesmo que o identificador do alerta seja igual. Se essa geração falhar, retorna a orientação padrão com os dados financeiros atuais, sem reaproveitar uma explicação de valores anteriores. Solicitações simultâneas iguais não duplicam a geração; enquanto ela está em andamento, outra consulta recebe a orientação determinística.

Os dados financeiros e a presença dos alertas são consultados novamente a cada requisição. O cache não é compartilhado entre workers e desaparece ao reiniciar. A primeira explicação não armazenada é síncrona e segue os limites do provider; uma resposta truncada ou fora do formato exigido aciona o fallback. Não há memória de longo prazo, RAG, notificações ou armazenamento persistente de insights.

Erros: `401` para autenticação ausente/inválida ou usuário inativo; `403` para usuário sem empresa; `422` para mês/parâmetros inválidos; `503` com código `financial_insights_unavailable` para falha de consulta financeira, sem expor SQL ou credenciais.

## Validação

Em `apps/api/`:

```powershell
uv run pytest tests/test_financial_insights.py tests/test_insight_explanations.py tests/test_financial_reports.py tests/test_financial_profitability.py -p no:cacheprovider
uv run ruff check app/modules/financial_insights tests/test_financial_insights.py tests/test_insight_explanations.py
```

Os testes exercitam os Services e Repositories reais com SQLite descartável e o adaptador de fuso já utilizado pelo financeiro; o Gemini é simulado. Cobrem limites, ausência de dados, pagamentos, períodos, isolamento, atualização, IDs, ausência de duplicatas, fallback, validação das orientações, cache limitado e chamadas simultâneas. Não utilizam o banco configurado nem a API real do Gemini.
