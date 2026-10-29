# Assistente de IA do Organizaê

## Visão geral e tecnologias

A assistente responde em português brasileiro e consulta exclusivamente a empresa do usuário autenticado por Function Calling nativo do Gemini. A integração utiliza Python 3.12+, FastAPI, SQLAlchemy, PostgreSQL, Pydantic v2 e o SDK oficial `google-genai`, com dependências gerenciadas pelo uv. Não utiliza LangChain ou LangGraph.

## Configuração

Na raiz do repositório, crie um `.env` a partir de `.env.example` caso ainda não exista. Preserve as configurações existentes, incluindo `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` e `DB_PASSWORD`. Para usar as ferramentas, o PostgreSQL local deve estar disponível e atualizado pelas migrations do Alembic.

Crie uma chave no [Google AI Studio](https://aistudio.google.com/apikey) e configure:

```dotenv
GEMINI_API_KEY=sua-chave
GEMINI_MODEL=gemini-3.1-flash-lite
```

`GEMINI_API_KEY` é obrigatória para usar a assistente. O modelo padrão, quando `GEMINI_MODEL` não é definida, é `gemini-3.1-flash-lite`; um valor vazio gera erro de configuração. Consulte a [disponibilidade e os preços do Google](https://ai.google.dev/gemini-api/docs/pricing) para escolher um modelo compatível com geração de texto e com as cotas do projeto.

As variáveis do processo têm prioridade sobre o `.env`, que prevalece sobre os valores padrão do código. Reinicie o servidor após alterar a configuração. Não versione o `.env` nem exponha a chave no frontend.

### Autenticação e isolamento por empresa

Todas as rotas `/api/v1/assistant/*`, incluindo chat, confirmação e cancelamento, exigem `Authorization: Bearer <access_token>`. Não há fallback anônimo ou para empresa configurada no `.env`. As antigas variáveis `ASSISTANT_DEMO_ENABLED` e `ASSISTANT_DEMO_BUSINESS_ID` foram removidas das configurações e são ignoradas se ainda estiverem no arquivo.

O login existente usa Argon2 para verificar a senha e emite um JWT HS256 com `sub`, `iat`, `exp` e `token_type=access`. Configure `JWT_SECRET_KEY` com uma chave aleatória de pelo menos 32 bytes. O tempo padrão é `JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30`. A assistente reutiliza a validação existente, sem implementar um segundo mecanismo de autenticação:

1. Valida assinatura, algoritmo, expiração e finalidade do token.
2. Busca o usuário indicado pelo `sub` e verifica se ele ainda existe e está ativo.
3. Obtém `business_id` do cadastro atual do usuário no banco, nunca do cliente ou do Gemini.
4. Usa essa empresa em todas as ferramentas e revalida a identidade em cada requisição, inclusive decisões sobre ações pendentes.

O JWT, a senha, o e-mail e o hash de senha não são enviados ao Gemini. Alterar o vínculo do usuário ou desativá-lo afeta as próximas requisições mesmo com um token emitido anteriormente. As ações pendentes e as chaves de idempotência são isoladas por usuário e empresa.

Leituras autenticadas funcionam também em produção. Escritas continuam opcionais e restritas ao desenvolvimento:

```dotenv
APP_ENV=development
ASSISTANT_WRITES_ENABLED=true
```

`APP_ENV` aceita `development`, `test` e `production`; o padrão é `production`. `ASSISTANT_WRITES_ENABLED` tem padrão `false`. Em `test` e `production`, a preparação e a execução de escritas são bloqueadas mesmo com a flag habilitada, pois o armazenamento de pendências ainda é em memória e suporta apenas um processo. Não habilite escritas locais com dados de produção.

## Execução e endpoint

Execute em `apps/api/`:

```bash
uv sync --locked
uv run uvicorn app.main:app --reload
```

Abra o [Swagger local](http://127.0.0.1:8000/docs). Faça login em `POST /api/v1/auth/login` com `email` e `password`. Copie o `access_token` retornado e cole somente o token em **Authorize → HTTPBearer**. O Swagger enviará o prefixo `Bearer` automaticamente. O usuário precisa ter uma empresa vinculada.

Em **Assistant**, selecione `POST /api/v1/assistant/chat` e use **Try it out**:

```json
{"message": "Olá, o que você consegue fazer?"}
```

A resposta HTTP 200 segue o formato `{"response": "texto da assistente"}`. A mensagem deve conter de 1 a 4000 caracteres após remover espaços nas extremidades. Campos adicionais são rejeitados.

Experimente mensagens como “Descreva minha empresa”, “Quais profissionais estão ativos?” e “Quais serviços e preços estão cadastrados?”. Não envie `business_id` ou `user_id` na requisição; campos extras no corpo são rejeitados e parâmetros na URL não alteram o contexto autenticado.

### Respostas de erro

Erros tratados da assistente retornam `{"detail": "causa e orientação", "code": "identificador_estavel"}`. Erros de validação do FastAPI retornam HTTP 422 com uma lista em `detail`, sem o campo `code` da assistente.

| HTTP | Código | Significado |
| --- | --- | --- |
| 401 | Sem `code` da assistente | Token ausente, inválido ou expirado; usuário removido ou inativo. Retorna `WWW-Authenticate: Bearer`. |
| 403 | Sem `code` da assistente | Usuário autenticado sem empresa vinculada. |
| 403 | `assistant_write_disabled` | Preparação ou decisão de escrita bloqueada pela configuração. |
| 409 | `assistant_action_unavailable` | Ação não pertence ao usuário/empresa atual, não existe, expirou ou foi consumida. |
| 409 | `assistant_request_conflict` | Chave de idempotência em processamento, falha ou reutilizada com outra mensagem. |
| 422 | `assistant_write_rejected` | Registro ausente na empresa atual ou outra regra de negócio impediu a escrita. |
| 429 | `gemini_rate_limit` | Cota ou limite de requisições do Google excedido. |
| 502 | `gemini_invalid_response` | Resposta sem texto utilizável, incompleta ou bloqueada. |
| 404 | `assistant_business_not_found` | Empresa vinculada ao usuário não encontrada. |
| 502 | `assistant_invalid_tool_call` / `assistant_tool_limit` | Nome/argumentos não autorizados ou limite de ferramentas excedido. |
| 503 | `assistant_database_unavailable` | Falha ao consultar os dados pelo SQLAlchemy. |
| 503 | `gemini_api_key_missing` / `gemini_model_missing` | Chave ou modelo vazio na configuração. |
| 503 | `gemini_api_key_invalid` | Chave rejeitada pelo Google. |
| 503 | `gemini_permission_denied` | Acesso negado pelo Google. |
| 503 | `gemini_model_not_found` | Recurso solicitado não encontrado; conferir o modelo e sua disponibilidade. |
| 503 | `gemini_request_rejected` | Parâmetros rejeitados pelo Google. |
| 503 | `gemini_connection_error` | Falha de conexão com o provedor. |
| 503 | `gemini_unavailable` | Demais falhas da API do Gemini. |
| 504 | `gemini_timeout` | Timeout local ou HTTP 504 do Google. |
| 500 | `assistant_internal_error` | Outra exceção da família `AssistantError`. |

Os códigos HTTP acima pertencem à API do Organizaê e podem diferir dos retornados pelo Google. As mensagens públicas e os logs do módulo não expõem credenciais nem o conteúdo bruto dos erros do provedor.

## Arquitetura

O módulo fica em `apps/api/app/modules/assistant/` e é registrado em `app/main.py`. O fluxo usa declarações de funções e respostas de ferramentas do [SDK oficial](https://googleapis.github.io/python-genai/#manually-declare-and-invoke-a-function-for-function-calling):

1. O Service envia a mensagem e as declarações de ferramentas ao Gemini pelo Provider.
2. O Gemini pode solicitar uma ou mais funções; o backend valida todo o lote antes de executá-lo.
3. As ferramentas chamam os Services com o UUID obtido do usuário autenticado. Os Repositories fazem consultas parametrizadas e filtram por empresa.
4. O Provider envia os resultados como `function_response`, preservando o conteúdo original do modelo e suas assinaturas de pensamento.
5. O processo continua até obter texto final, com no máximo cinco chamadas de ferramentas por mensagem, incluindo chamadas em lote.

| Componente | Responsabilidade |
| --- | --- |
| `router.py` | Endpoints protegidos pelas dependências de autenticação, injeção dos Services e tradução de exceções. |
| `schemas.py` | Validação da mensagem e contrato da resposta. |
| `service.py` | Orquestração do ciclo de ferramentas e limite de chamadas, sem detalhes do SDK. |
| `providers/base.py` | Contratos de conversa, chamadas e resultados independentes do Gemini. |
| `providers/gemini.py` | Comunicação com o Gemini, histórico apenas na requisição e retries HTTP limitados conforme a seção de falhas transitórias. |
| `tools/` | Lista explícita de funções, validação estrita dos argumentos e projeção dos campos autorizados. |
| `prompts/system.py` | Identidade, contexto do sistema e instruções para não inventar dados ou ações. |
| `exceptions.py` | Categorias de erro independentes do FastAPI. |

| Ferramenta | Service | Dados enviados ao Gemini |
| --- | --- | --- |
| `get_business_info` | `BusinessService.get_by_id` | Nome, descrição e modalidade de atendimento. |
| `list_professionals` | `ProfessionalService.list` | Nome, descrição e situação ativa; filtro opcional `is_active`. |
| `list_services` | `ServiceService.list` | Nome, descrição, preço decimal em texto, duração e situação ativa. |

Listagens aceitam `offset` (padrão 0) e `limit` (padrão 20, máximo 100). Nenhuma função aceita `business_id`, SQL ou nomes de funções arbitrários. As listagens incluem IDs de serviços e profissionais da própria empresa para preparar atualizações, mas não enviam telefones, endereço ou dados da conta. O prompt instrui o modelo a tratar os resultados como dados, não como instruções.

As ferramentas reutilizam `BusinessService`, `ProfessionalService` e `ServiceService`. Os Services compartilham a sessão recebida por `get_db`; seu context manager fecha a sessão ao terminar a requisição, inclusive em falhas. As ferramentas de escrita apenas preparam pendências. Após confirmação explícita pela API, o `AssistantService` chama os Services existentes, que mantêm suas regras e limites de transação. O cliente Gemini também é fechado ao terminar a conversa.

## Dados fictícios para teste local

Em um banco **exclusivo de desenvolvimento**, aplique as migrations existentes com `uv run alembic upgrade head`. Crie um usuário fictício em `POST /api/v1/users`, faça login e cadastre sua empresa em `POST /api/v1/businesses`, com uma `category_id` existente. O onboarding vincula a empresa à conta autenticada; não é necessário reemitir o JWT após criar a empresa.

Com o mesmo token, cadastre serviços e profissionais pelos POSTs do Swagger e consulte-os pela assistente. Nenhum desses fluxos exige um UUID de empresa no `.env`. Para verificar o isolamento, use duas contas com empresas diferentes e confirme que cada token acessa apenas os próprios registros. Não há necessidade de associar profissionais a serviços para testar as três ferramentas de leitura.

## Testes

Execute em `apps/api/`:

```bash
uv run pytest tests/test_assistant.py
uv run pytest tests/test_assistant_tools.py tests/test_professional_read.py
uv run pytest tests/test_assistant_auth.py
uv run pytest
uv run ruff check .
```

Os testes usam mocks do Gemini, sem chamadas externas ou acesso a PostgreSQL. A integração JWT usa login e validação reais com SQLite isolado em memória e duas empresas. Cobre tokens inválidos/expirados, contas inativas/sem empresa, consulta pelo vínculo atual, rejeição de empresa fornecida pelo cliente/modelo, proteção de ações e idempotência por usuário e empresa, além da confirmação de escrita. Os testes existentes cobrem as ferramentas, validação, listas vazias, limites, falhas e fechamento da sessão. O teste manual pelo Swagger exige chave válida, rede, cota, PostgreSQL local e login.

## Limitações e evolução

### Falhas transitórias do Gemini

O provider repete exclusivamente a chamada `generate_content` para HTTP 429,
500, 502, 503 e 504, com no máximo **três tentativas no total por chamada**.
Os retries internos do SDK permanecem desativados para evitar multiplicar esse
limite. Erros definitivos, como 400, 401 e 403, respostas inválidas do modelo,
falhas de conexão e timeouts locais não são repetidos; mantêm o tratamento de
erros existente. Ao esgotar as tentativas, os códigos públicos da API permanecem
os mesmos, incluindo `gemini_timeout` para HTTP 504.

O backoff espera um segundo antes da segunda tentativa e dois segundos antes
da terceira, acrescidos de jitter aleatório de até 50% de cada intervalo.
`Retry-After`, quando válido, define a espera mínima, tanto em segundos quanto
em data HTTP. Valores inválidos são ignorados; datas passadas não acrescentam
espera ao backoff.

Configure `GEMINI_TIMEOUT_MS=30000` no `.env` para definir o timeout HTTP em
milissegundos **por tentativa**, com valor positivo. Esse timeout não é um prazo
global: o tempo total inclui até três chamadas e as esperas entre elas, que podem
ser maiores quando o servidor informa `Retry-After`.

Cada tentativa registra status HTTP, duração em milissegundos e número da
tentativa. Sucessos usam nível INFO e falhas usam WARNING. Os logs do provider
não incluem API keys, prompts, argumentos de ferramentas ou corpos de resposta.

Os retries não envolvem o `AssistantService`: não repetem consultas aos Services,
criação de pendências nem execução de ações confirmadas. O histórico de respostas
de ferramentas é incluído uma única vez e reutilizado nas tentativas HTTP.
Testes com mocks: `uv run pytest tests/test_gemini_retries.py`.

A assistente acessa somente a empresa vinculada ao usuário autenticado. Escritas exigem configuração de desenvolvimento e confirmação explícita pela API, conforme a seção abaixo. Não executa SQL e não mantém histórico de conversa entre requisições. O Google recebe apenas o prompt, a mensagem e os campos permitidos retornados pelas ferramentas, sem token ou dados de autenticação.

Function Calling nativo está implementado, mas a execução automática de funções Python pelo SDK permanece desabilitada: somente o backend despacha as funções permitidas. Análise financeira, comandos por voz, extração de dados de imagens e Text-to-SQL não foram implementados. O JWT atual não tem logout com revogação individual nem refresh token; a expiração e a situação atual da conta são verificadas em cada requisição.


## Escrita com confirmação explícita (desenvolvimento)

As ferramentas `create_service`, `update_service`, `create_professional` e
`update_professional` usam o SDK nativo do Gemini e apenas preparam ações.
A escrita exige JWT válido, empresa vinculada, `APP_ENV=development` e
`ASSISTANT_WRITES_ENABLED=true`. Em `test` e `production` as consultas
continuam disponíveis, mas escrita é bloqueada. Utilize dados fictícios para
validar esse fluxo localmente. Os antigos parâmetros de demonstração não habilitam escrita.

Envie `POST /api/v1/assistant/chat` com, por exemplo:

```json
{"message": "Cadastre o serviço Corte, por R$ 45,00, com duração de 30 minutos"}
```

Outros exemplos: "Altere o preço do Corte para R$ 50,00", "Cadastre a profissional
Ana" e "Desative a profissional Ana". As listagens retornam IDs para identificar
registros; em caso de ambiguidade a assistente deve perguntar. O backend valida
os argumentos com os schemas existentes e devolve erros de campos ao modelo
para solicitar correções. Não existe SQL arbitrário ou acesso do Gemini ao banco.

A resposta inclui `response` e `pending_actions`, com `id`, `operation`,
`arguments`, `expires_at` e `state=pending`. Exiba os parâmetros para revisão do
usuário. Para atualizações, a ferramenta recebe `record_id` e `data`, como
`{"record_id": "UUID", "data": {"price": "50.00"}}` ou
`{"record_id": "UUID", "data": {"is_active": false}}`.

Após o usuário confirmar explicitamente, envie:

```http
POST /api/v1/assistant/actions/{id}/confirm
Authorization: Bearer <access_token>
Content-Type: application/json

{"decision": "confirm"}
```

Para cancelar, envie `POST /api/v1/assistant/actions/{id}/cancel`, sem corpo e com o JWT.
Responder "sim" no chat não confirma ações. Os endpoints não recebem novos
parâmetros de negócio: executam exclusivamente os parâmetros já validados e
armazenados. Qualquer alteração requer preparar outra ação e cancelar a anterior.

As pendências expiram em cinco minutos. Estados possíveis: `pending`, `executing`,
`confirmed`, `cancelled`, `expired`, `failed`. Ações inexistentes, expiradas ou já
consumidas retornam 409. Falhas de negócio retornam 422, indisponibilidade do
banco 503 e bloqueio de ambiente 403. Uma falha de execução também consome a
ação, pois um commit pode ter ocorrido antes de uma falha no refresh; consulte
os registros antes de preparar outra ação.

O armazenamento é em memória, protegido por lock para consumo único dentro do
processo. Reiniciar o servidor invalida pendências. Execute o fluxo de escrita com
um único worker; múltiplos workers precisam de armazenamento compartilhado e
consumo atômico persistente antes de serem suportados. Cada ação é vinculada
ao usuário e à empresa que a prepararam. Conhecer o ID não permite decidir
ações de outro usuário ou empresa. Mudanças no vínculo da conta são verificadas
novamente antes da confirmação ou cancelamento.
Não foram adicionadas dependências ou migrations.

Testes de escrita: `uv run pytest tests/test_assistant_writes.py` (mocks, sem
chamadas externas ao Gemini ou banco real).

### Concorrência e idempotência das escritas

Para habilitar idempotência em `POST /api/v1/assistant/chat`, o cliente deve
gerar um UUID em `request_id` para cada nova solicitação e reutilizá-lo nos
reenvios dessa mesma solicitação:

```json
{
  "message": "Cadastre a profissional Ana",
  "request_id": "a924d8d3-cbeb-4d8e-bd95-76304d222d2b"
}
```

O mesmo usuário, empresa, chave e mensagem reutilizam a resposta original e os mesmos
IDs de ações, sem chamar novamente o Gemini. Uma solicitação legítima adicional,
mesmo com mensagem e parâmetros iguais, deve usar outro UUID. O campo é opcional
para manter compatibilidade: sem ele, cada envio continua sendo uma nova
solicitação. O ID não é enviado ao Gemini.

Reutilizar a chave com outra mensagem, durante seu processamento ou depois de
uma falha retorna HTTP 409 (`assistant_request_conflict`). Após o primeiro envio
concluir com sucesso, o cliente pode reenviar a mesma chave para recuperar sua
resposta. Chaves de lotes que falharam ficam consumidas, pois podem ter criado
pendências antes da falha. A resposta reapresentada é um retrato da preparação;
as rotas de decisão verificam o estado atual e recusam ações já consumidas ou
expiradas. Uma chave nunca recria pendências por terem expirado.

Os registros de idempotência de escrita e os estados finais ficam na memória
até o processo terminar. Reinícios invalidam essa garantia e múltiplos workers
continuam sem suporte. Respostas sem ações de escrita não são armazenadas para
reuso; consultas continuam obtendo dados atuais.

Dentro de um lote, chamadas de escrita com operação e parâmetros validados
iguais compartilham uma única pendência, mesmo com IDs diferentes ou ausentes.
Reutilizar o mesmo `ToolCall.id` com conteúdos diferentes invalida o lote antes
de criar ações. Chamadas de leitura não são deduplicadas.

Somente ações `pending` expiram. Ações `executing` permanecem disponíveis para
finalização mesmo após cinco minutos e não podem ser confirmadas ou canceladas
novamente. O lock protege a disputa entre confirmar e cancelar, permitindo
apenas uma decisão vencedora. A mesma ação executa no máximo uma vez no processo.

Testes: `uv run pytest tests/test_assistant_idempotency.py`.
