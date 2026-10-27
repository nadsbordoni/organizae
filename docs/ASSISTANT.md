# Assistente de IA do Organizaê

## Visão geral e tecnologias

A assistente responde em português brasileiro e consulta dados de uma empresa de demonstração por Function Calling nativo do Gemini. A integração utiliza Python 3.12+, FastAPI, SQLAlchemy, PostgreSQL, Pydantic v2 e o SDK oficial `google-genai`, com dependências gerenciadas pelo uv. Não utiliza LangChain ou LangGraph.

## Configuração

Na raiz do repositório, crie um `.env` a partir de `.env.example` caso ainda não exista. Preserve as configurações existentes, incluindo `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` e `DB_PASSWORD`. Para usar as ferramentas, o PostgreSQL local deve estar disponível e atualizado pelas migrations do Alembic.

Crie uma chave no [Google AI Studio](https://aistudio.google.com/apikey) e configure:

```dotenv
GEMINI_API_KEY=sua-chave
GEMINI_MODEL=gemini-3.1-flash-lite
```

`GEMINI_API_KEY` é obrigatória para usar a assistente. O modelo padrão, quando `GEMINI_MODEL` não é definida, é `gemini-3.1-flash-lite`; um valor vazio gera erro de configuração. Consulte a [disponibilidade e os preços do Google](https://ai.google.dev/gemini-api/docs/pricing) para escolher um modelo compatível com geração de texto e com as cotas do projeto.

As variáveis do processo têm prioridade sobre o `.env`, que prevalece sobre os valores padrão do código. Reinicie o servidor após alterar a configuração. Não versione o `.env` nem exponha a chave no frontend.

### Empresa de demonstração

As ferramentas ficam desabilitadas por padrão, preservando o chat de texto sem consultas ao banco. Para habilitá-las **somente em ambiente local com dados fictícios**, configure:

```dotenv
APP_ENV=development
ASSISTANT_DEMO_ENABLED=true
ASSISTANT_DEMO_BUSINESS_ID=uuid-da-empresa-ficticia
```

Substitua o valor de `ASSISTANT_DEMO_BUSINESS_ID` por um UUID existente. `APP_ENV` aceita `development`, `test` e `production`; o padrão é `production`. Com a demonstração habilitada, ambiente de produção ou empresa não configurada resultam em erro controlado antes de enviar mensagens ao Gemini. A existência da empresa é verificada antes da conversa.

O UUID é escolhido pelo operador do backend, nunca pelo modelo ou pelo corpo da requisição. **Isso não é autenticação:** não publique a demonstração nem configure dados reais. Em produção, mantenha `ASSISTANT_DEMO_ENABLED=false` e `APP_ENV=production`. Futuramente, o contexto deverá vir do usuário autenticado, com autorização e isolamento entre empresas.

## Execução e endpoint

Execute em `apps/api/`:

```bash
uv sync --locked
uv run uvicorn app.main:app --reload
```

Abra o [Swagger local](http://127.0.0.1:8000/docs). Em **Assistant**, selecione `POST /api/v1/assistant/chat` e use **Try it out**:

```json
{"message": "Olá, o que você consegue fazer?"}
```

A resposta HTTP 200 segue o formato `{"response": "texto da assistente"}`. A mensagem deve conter de 1 a 4000 caracteres após remover espaços nas extremidades. Campos adicionais são rejeitados.

Com a demonstração habilitada, experimente mensagens como “Descreva a empresa de demonstração”, “Quais profissionais estão ativos?” e “Quais serviços e preços estão cadastrados?”. Não envie `business_id` na requisição.

### Respostas de erro

Erros tratados da assistente retornam `{"detail": "causa e orientação", "code": "identificador_estavel"}`. Erros de validação do FastAPI retornam HTTP 422 com uma lista em `detail`, sem o campo `code` da assistente.

| HTTP | Código | Significado |
| --- | --- | --- |
| 429 | `gemini_rate_limit` | Cota ou limite de requisições do Google excedido. |
| 502 | `gemini_invalid_response` | Resposta sem texto utilizável, incompleta ou bloqueada; chamadas de ferramentas também são rejeitadas quando a demonstração está desabilitada. |
| 404 | `assistant_demo_business_not_found` | Empresa de demonstração inexistente. |
| 502 | `assistant_invalid_tool_call` / `assistant_tool_limit` | Nome/argumentos não autorizados ou limite de ferramentas excedido. |
| 503 | `assistant_demo_not_configured` | Demonstração habilitada em produção ou sem UUID configurado. |
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
3. As ferramentas chamam os Services com o UUID fixado pelo backend. Os Repositories fazem consultas parametrizadas.
4. O Provider envia os resultados como `function_response`, preservando o conteúdo original do modelo e suas assinaturas de pensamento.
5. O processo continua até obter texto final, com no máximo cinco chamadas de ferramentas por mensagem, incluindo chamadas em lote.

| Componente | Responsabilidade |
| --- | --- |
| `router.py` | Endpoint, injeção de dependências e tradução das exceções para HTTP. |
| `schemas.py` | Validação da mensagem e contrato da resposta. |
| `service.py` | Orquestração do ciclo de ferramentas e limite de chamadas, sem detalhes do SDK. |
| `providers/base.py` | Contratos de conversa, chamadas e resultados independentes do Gemini. |
| `providers/gemini.py` | Comunicação nativa com o Gemini, histórico apenas na requisição e timeout de 30 segundos por chamada, sem tentativas automáticas. |
| `tools/` | Lista explícita de funções, validação estrita dos argumentos e projeção dos campos autorizados. |
| `prompts/system.py` | Identidade, contexto do sistema e instruções para não inventar dados ou ações. |
| `exceptions.py` | Categorias de erro independentes do FastAPI. |

| Ferramenta | Service | Dados enviados ao Gemini |
| --- | --- | --- |
| `get_business_info` | `BusinessService.get_by_id` | Nome, descrição e modalidade de atendimento. |
| `list_professionals` | `ProfessionalService.list` | Nome, descrição e situação ativa; filtro opcional `is_active`. |
| `list_services` | `ServiceService.list` | Nome, descrição, preço decimal em texto, duração e situação ativa. |

Listagens aceitam `offset` (padrão 0) e `limit` (padrão 20, máximo 100). Nenhuma função aceita `business_id`, SQL ou nomes de funções arbitrários. Telefones, endereço e identificadores internos não são enviados nos resultados. O prompt instrui o modelo a tratar esses resultados como dados, não como instruções.

As ferramentas reutilizam `BusinessService`, `ProfessionalService` e `ServiceService`. Os Services compartilham a sessão recebida por `get_db`; seu context manager fecha a sessão ao terminar a requisição, inclusive em falhas. As ferramentas de escrita apenas preparam pendências. Após confirmação explícita pela API, o `AssistantService` chama os Services existentes, que mantêm suas regras e limites de transação. O cliente Gemini também é fechado ao terminar a conversa.

## Dados fictícios para teste local

Em um banco **exclusivo de desenvolvimento**, aplique as migrations existentes com `uv run alembic upgrade head`. Empresas, serviços e profissionais podem ser cadastrados pelos POSTs disponíveis no Swagger. Como alternativa, este exemplo opcional prepara um conjunto completo: execute `uv run python` em `apps/api/` e cole o código abaixo. Ele cria dados somente quando executado manualmente; cada execução cria uma nova empresa.

```python
from decimal import Decimal
from sqlalchemy import select
from app.db.session import SessionLocal
from app.modules.business_categories.models import BusinessCategory
from app.modules.businesses.models import Business, ServiceMode
from app.modules.professionals.models import Professional
from app.modules.services.models import Service

with SessionLocal.begin() as session:
    category = session.scalar(select(BusinessCategory).where(BusinessCategory.name == "Demo IA"))
    if category is None:
        category = BusinessCategory(name="Demo IA")
        session.add(category)
        session.flush()
    business = Business(name="Salão Demo", category_id=category.id,
                        whatsapp="00000000000", service_mode=ServiceMode.PRESENCIAL)
    session.add(business)
    session.flush()
    session.add_all([
        Professional(business_id=business.id, name="Ana Demo", is_active=True),
        Professional(business_id=business.id, name="Bruno Demo", is_active=False),
        Service(business_id=business.id, name="Corte Demo", price=Decimal("35.50"),
                duration_minutes=30, is_active=True),
    ])

print(business.id)
```

Copie o UUID exibido para `ASSISTANT_DEMO_BUSINESS_ID`, habilite a demonstração e reinicie o servidor. Não há necessidade de associar profissionais a serviços para testar as três ferramentas.

## Testes

Execute em `apps/api/`:

```bash
uv run pytest tests/test_assistant.py
uv run pytest tests/test_assistant_tools.py tests/test_professional_read.py
uv run pytest
uv run ruff check .
```

Os testes da assistente simulam Services e SDK, sem consumir a API Gemini ou acessar PostgreSQL. Cobrem seleção e execução das três ferramentas, validação, bloqueio de acesso a outra empresa, empresa ausente/inexistente, produção bloqueada, listas vazias, limite de chamadas, falhas após a execução e fechamento da sessão. O Repository de profissionais também é verificado em SQLite isolado em memória, para validar filtro e paginação por empresa. O teste manual pelo Swagger exige chave válida, rede, cota e PostgreSQL local.

## Limitações e evolução

A assistente acessa somente a empresa de demonstração quando habilitada. Escritas exigem confirmação explícita pela API, conforme a seção abaixo. Não executa SQL e não mantém histórico de conversa entre requisições. O Google recebe o prompt, a mensagem e os campos permitidos retornados pelas ferramentas. Não há autenticação; o mecanismo temporário não deve ser publicado ou usado para dados reais.

Function Calling nativo está implementado, mas a execução automática de funções Python pelo SDK permanece desabilitada: somente o backend despacha as funções permitidas. Análise financeira, comandos por voz, extração de dados de imagens e Text-to-SQL não foram implementados. A evolução deverá substituir o contexto de demonstração pela autenticação e preservar a autorização nos Services.


## Escrita com confirmação explícita (demonstração local)

As ferramentas `create_service`, `update_service`, `create_professional` e
`update_professional` usam o SDK nativo do Gemini e apenas preparam ações.
A escrita exige `APP_ENV=development`, `ASSISTANT_DEMO_ENABLED=true` e
`ASSISTANT_DEMO_BUSINESS_ID` configurado no backend. Em `test` as consultas
continuam disponíveis, mas escrita é bloqueada. Não há autenticação: utilize
somente dados fictícios e não exponha esta demonstração publicamente.

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
Content-Type: application/json

{"decision": "confirm"}
```

Para cancelar, envie `POST /api/v1/assistant/actions/{id}/cancel`, sem corpo.
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
processo. Reiniciar o servidor invalida pendências. Execute a demonstração com
um único worker; múltiplos workers precisam de armazenamento compartilhado e
consumo atômico persistente antes de serem suportados. O ID funciona como uma
capacidade temporária, sem vínculo a usuário autenticado. Antes de produção,
é necessário implementar autenticação, autorização e vínculo das ações ao usuário.
Não foram adicionadas dependências ou migrations.

Testes de escrita: `uv run pytest tests/test_assistant_writes.py` (mocks, sem
chamadas externas ao Gemini ou banco real).
