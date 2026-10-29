# Monitoramento e orçamento de tokens

O consumo real é obtido de `usage_metadata` retornado pelo Gemini. A contagem do SDK usada para ajustar o contexto e as estimativas locais são registradas separadamente: não representam tokens consumidos nem valores faturados.

## Configuração

Defina no `.env` da raiz e reinicie o servidor:

| Variável | Padrão | Escopo |
| --- | --- | --- |
| `ASSISTANT_HISTORY_TOKEN_BUDGET` | `4096` | Máximo de tokens do histórico anterior. |
| `GEMINI_MAX_OUTPUT_TOKENS` | `2048` | Máximo de saída por geração do modelo. |
| `ASSISTANT_CONTEXT_TOKEN_LIMIT` | `8192` | Limite já existente para o conteúdo completo enviado: histórico selecionado, mensagem atual e transcrições das ferramentas no turno. |

Todos os valores devem ser positivos. Esses limites são por contexto/geração, não um teto de consumo da requisição inteira: Function Calling e retries podem realizar várias gerações. O orçamento de conteúdo não inclui system prompt e declarações de ferramentas; o consumo real da API os inclui. Reduzir a saída pode causar uma resposta incompleta, tratada pelo fluxo existente como `gemini_invalid_response`.

## Seleção e integridade do contexto

O Service busca mensagens recentes em páginas de 100, sempre filtradas pelo usuário e pela empresa. A paginação é apenas de acesso ao banco; não há limite fixo de mensagens no contexto.

Para evitar carregar todo o histórico, uma heurística usa `ceil(bytes UTF-8 / 4)` mais oito tokens por mensagem e uma margem de duas vezes o orçamento para selecionar candidatos recentes. Essa etapa pode deixar alguma capacidade disponível: não promete encontrar todo o histórico que caberia segundo o tokenizer.

O Provider usa `models.count_tokens` e busca binária para manter o maior sufixo de turnos completos dentre esses candidatos. Isso evita uma chamada de contagem para cada par removido. Primeiro aplica o orçamento do histórico; depois verifica o conteúdo completo antes de cada geração. Mensagens atuais, Function Calls, respostas e assinaturas de pensamento do turno em andamento são preservadas integralmente. Se esse conteúdo sozinho exceder o limite, retorna `assistant_context_limit` (422), sem gerar resposta ou persistir um par parcial.

Quando o SDK não implementa a contagem ou o endpoint retorna 404/501, o Provider usa um fallback conservador: bytes UTF-8 da representação serializada mais 32 por mensagem. O log identifica esse número como estimativa. Falhas de autenticação, timeout e indisponibilidade da contagem mantêm o tratamento de erros existente; não são silenciosamente convertidas em estimativas.

Nenhuma mensagem salva é truncada ou removida por essa seleção. O histórico persistente, o isolamento, a confirmação de ações e a idempotência mantêm seus contratos públicos.

## Logs

Cada chamada de `/assistant/chat` que chega ao Service emite um resumo `Gemini usage` em nível INFO, inclusive falhas e reapresentações sem geração. As gerações também mantêm seus logs por tentativa. Configure o logger `app.modules.assistant` em INFO no pipeline da aplicação. Para inspecionar localmente, execute em `apps/api/` com a configuração padrão do Python:

```bash
uv run python -c "import logging, uvicorn; logging.basicConfig(level=logging.INFO); uvicorn.run('app.main:app')"
```

Campos principais do resumo:

| Campo | Significado |
| --- | --- |
| `request_id`, `model`, `duration_ms`, `succeeded` | Correlação aleatória do monitoramento, modelo utilizado, duração total e resultado. Esse ID é independente do `request_id` opcional enviado pelo cliente. |
| `generation_calls`, `generation_attempts`, `retries` | Gerações lógicas, tentativas incluindo retries e quantidade de retries. Incluem as gerações internas após ferramentas. |
| `count_calls`, `api_calls` | Tentativas de chamada ao contador do SDK e soma das tentativas de geração e contagem. |
| `input_tokens`, `output_tokens`, `total_tokens` | Soma dos valores disponíveis de entrada, candidatos de saída e total informados pela API. |
| `usage_complete`, `unknown_usage_attempts`, `incomplete_usage_reports` | Indicam se todas as tentativas de geração informaram os três valores principais. |
| `reported_thought_tokens`, `reported_cached_tokens`, `reported_tool_prompt_tokens` | Outros contadores disponíveis nos metadados. Não são somados novamente ao total. Nenhum cache novo foi implementado. |
| `counted_context_tokens` | Última contagem de contexto pelo SDK; previsão de entrada, não consumo. |
| `estimated_context_tokens`, `estimated_tool_tokens` | Fallback local do contexto e estimativa acumulada dos schemas enviados nas tentativas. Nunca entram nos totais de consumo real. |

O `total_tokens` é o total fornecido pela API, sem recalcular `entrada + saída`: raciocínio e outros componentes podem fazer esses números diferirem. Metadados de tentativas que falharam também são aproveitados quando disponibilizados. Se uma tentativa não retorna uso, o consumo dela fica desconhecido; os totais registrados são apenas a parcela conhecida e `usage_complete=false`. Campo sem qualquer medição aparece como `null`, não zero. Sem geração, o resumo informa zero e `usage_source=no_generation`.

Os logs não incluem prompts, mensagens, argumentos/resultados de ferramentas, tokens JWT, dados da conta ou API keys. A duração inclui contagem, backoff, gerações e processamento do Service, sem abranger autenticação prévia ou serialização HTTP. Não há armazenamento adicional de métricas no banco nem mudanças no JSON público da API.

## Redução de prompt e schemas

As instruções foram condensadas mantendo isolamento, dados não confiáveis, proibição de SQL/exclusão, consultas atuais, dados ausentes, confirmação explícita pela API e rejeição de confirmação por texto. Os schemas enviados omitem apenas `title` e `default` redundantes; propriedades, obrigatoriedade, referências, tipos e limites continuam presentes. A validação Pydantic do backend não mudou.

Somente ferramentas autorizadas são declaradas: três de leitura, acrescidas das quatro de preparação de escrita quando o ambiente e a flag permitem. Não há filtro por palavras-chave da mensagem, pois ele poderia ocultar uma ferramenta necessária e prejudicar pedidos ambíguos. Todas as funções continuam disponíveis dentro de sua autorização.

## Comparação reproduzível

Execute em `apps/api/`:

```bash
uv run pytest tests/test_assistant_tokens.py::test_reproducible_estimated_token_comparison -q -s
```

A baseline está em `tests/fixtures/assistant_tokens_before.json`, com os prompts e schemas anteriores, sem dados reais. Os cenários usam a mesma mensagem atual, histórico fictício e permissões antes e depois. A comparação emula os padrões anteriores (14 mensagens, limite de contexto 8192) e novos (histórico 4096, contexto 8192). A saída máxima continua em 2048 nos dois casos.

**Todos os números abaixo são estimativas de entrada**, usando bytes UTF-8 divididos por quatro, arredondados para cima, mais oito por mensagem. O contador do SDK é simulado com essa mesma heurística no teste; não foram feitas gerações ou chamadas reais ao Google. A representação textual dos schemas não equivale exatamente ao formato/tokenização internos do modelo.

| Cenário | Antes | Depois | Variação | Mensagens anteriores preservadas |
| --- | ---: | ---: | ---: | --- |
| Leitura sem histórico | 861 | 573 | −33,4% | 0 → 0 |
| Escrita habilitada, sem histórico | 1701 | 1210 | −28,9% | 0 → 0 |
| Leitura com 30 turnos curtos | 1057 | 1413 | +33,7% | 14 → 60 |
| Leitura com 30 turnos longos | 7933 | 4109 | −48,2% | 8 → 4 |

O caso curto preserva mais contexto e pode aumentar a entrada; o caso longo reduz histórico para respeitar o novo orçamento. Não há promessa de economia uniforme. A parcela fixa estimada de prompt e schemas caiu de 845 para 557 em leitura e de 1685 para 1194 com escrita habilitada. A comparação não mede qualidade da resposta, saída, raciocínio ou faturamento; esses valores dependem de gerações reais e devem ser avaliados pelos metadados registrados em uso.

Os testes cobrem consumo reportado, tentativas sem metadados, retries, chamadas internas, isolamento dos contadores, sigilo dos logs, contagem e fallback, preservação de turnos e Function Calling, configurações e disponibilidade das ferramentas. Não consomem créditos da API.
