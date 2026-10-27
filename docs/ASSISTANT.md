# Assistente de IA do Organizaê

## Visão geral e tecnologias

A assistente responde a mensagens de texto em português brasileiro e orienta o usuário sobre o Organizaê. A integração utiliza Python 3.12+, FastAPI, Pydantic v2, pydantic-settings e o SDK oficial `google-genai`, com dependências gerenciadas pelo uv. Pytest e Ruff apoiam os testes e a qualidade do código.

## Configuração

Na raiz do repositório, crie um `.env` a partir de `.env.example` caso ainda não exista. Preserve as configurações existentes, incluindo `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` e `DB_PASSWORD`, necessárias à configuração da aplicação, mesmo que a assistente não acesse o banco.

Crie uma chave no [Google AI Studio](https://aistudio.google.com/apikey) e configure:

```dotenv
GEMINI_API_KEY=sua-chave
GEMINI_MODEL=gemini-3.1-flash-lite
```

`GEMINI_API_KEY` é obrigatória para usar a assistente. O modelo padrão, quando `GEMINI_MODEL` não é definida, é `gemini-3.1-flash-lite`; um valor vazio gera erro de configuração. Consulte a [disponibilidade e os preços do Google](https://ai.google.dev/gemini-api/docs/pricing) para escolher um modelo compatível com geração de texto e com as cotas do projeto.

As variáveis do processo têm prioridade sobre o `.env`, que prevalece sobre os valores padrão do código. Reinicie o servidor após alterar a configuração. Não versione o `.env` nem exponha a chave no frontend.

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

### Respostas de erro

Erros tratados da assistente retornam `{"detail": "causa e orientação", "code": "identificador_estavel"}`. Erros de validação do FastAPI retornam HTTP 422 com uma lista em `detail`, sem o campo `code` da assistente.

| HTTP | Código | Significado |
| --- | --- | --- |
| 429 | `gemini_rate_limit` | Cota ou limite de requisições do Google excedido. |
| 502 | `gemini_invalid_response` | Resposta sem texto utilizável, incompleta, bloqueada ou com chamada de ferramenta. |
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

O fluxo é `Router → Service → Provider → Gemini`, sem Repository ou sessão de banco. O módulo fica em `apps/api/app/modules/assistant/` e é registrado em `app/main.py`.

| Componente | Responsabilidade |
| --- | --- |
| `router.py` | Endpoint, injeção de dependências e tradução das exceções para HTTP. |
| `schemas.py` | Validação da mensagem e contrato da resposta. |
| `service.py` | Orquestração e validação do texto retornado, desacopladas do SDK pelo `AssistantProvider`. |
| `providers/gemini.py` | Comunicação com o Gemini, com timeout de 30 segundos, uma tentativa e fechamento do cliente por requisição. |
| `prompts/system.py` | Identidade, contexto do sistema e instruções para não inventar dados ou ações. |
| `exceptions.py` | Categorias de erro independentes do FastAPI. |

## Testes

Execute em `apps/api/`:

```bash
uv run pytest tests/test_assistant.py
uv run pytest
uv run ruff check .
```

Os testes da assistente simulam o provedor e o SDK, sem chamadas reais ao Gemini ou acesso ao PostgreSQL. Cobrem validação, resposta válida, falhas de integração, respostas inesperadas, contrato do endpoint e proteção de informações sensíveis. O teste manual pelo Swagger exige chave válida, acesso à rede e cota disponível.

## Limitações e evolução

A assistente não tem acesso aos dados de empresas, não consulta nem altera o banco, não executa SQL e não mantém histórico entre requisições. Apenas a mensagem recebida e o prompt do sistema são enviados ao Google. O endpoint atual não possui autenticação.

A separação entre serviço e provedor oferece um ponto de extensão para futuras funcionalidades: function calling, análise financeira, comandos por voz e extração de dados de imagens. **Nenhuma delas foi implementada.** Function calling automático está desabilitado, e respostas com chamadas de ferramentas são rejeitadas. Essas evoluções exigirão contratos e implementação próprios; acesso a dados e ações deverá passar por autenticação, isolamento entre empresas e Services do backend.
