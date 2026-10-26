class AssistantError(Exception):
    """Base exception for assistant integration failures."""

    code = "assistant_internal_error"
    public_message = "Erro interno da assistente."


class AssistantUnavailableError(AssistantError):
    code = "gemini_unavailable"
    public_message = (
        "O Google Gemini retornou indisponibilidade. Tente novamente mais tarde."
    )


class AssistantMissingKeyError(AssistantUnavailableError):
    code = "gemini_api_key_missing"
    public_message = (
        "GEMINI_API_KEY está vazia. Configure a chave no .env da raiz "
        "e reinicie o servidor."
    )


class AssistantMissingModelError(AssistantUnavailableError):
    code = "gemini_model_missing"
    public_message = (
        "GEMINI_MODEL está vazio. Configure um modelo no .env da raiz "
        "e reinicie o servidor."
    )


class AssistantInvalidKeyError(AssistantUnavailableError):
    code = "gemini_api_key_invalid"
    public_message = (
        "O Google rejeitou a chave da API. Verifique ou gere uma nova chave "
        "no Google AI Studio, atualize GEMINI_API_KEY e reinicie o servidor."
    )


class AssistantPermissionError(AssistantUnavailableError):
    code = "gemini_permission_denied"
    public_message = (
        "O Google negou acesso à API (403). Confira as permissões e restrições "
        "da chave e se a API está habilitada no projeto Google."
    )


class AssistantModelNotFoundError(AssistantUnavailableError):
    code = "gemini_model_not_found"
    public_message = (
        "O Google não encontrou o recurso solicitado (404). Confira GEMINI_MODEL "
        "no .env e se o modelo suporta generateContent para seu projeto. "
        "Reinicie o servidor após alterar a configuração."
    )


class AssistantRequestRejectedError(AssistantUnavailableError):
    code = "gemini_request_rejected"
    public_message = (
        "O Google rejeitou os parâmetros da integração (400). Confira se o "
        "modelo configurado aceita geração de texto e as opções enviadas."
    )


class AssistantConnectionError(AssistantUnavailableError):
    code = "gemini_connection_error"
    public_message = (
        "Não foi possível conectar ao Google Gemini. Verifique a conexão, "
        "DNS, proxy, firewall e certificados TLS do servidor."
    )


class AssistantTimeoutError(AssistantError):
    code = "gemini_timeout"
    public_message = (
        "A chamada ao Gemini excedeu o tempo limite ou o Google retornou "
        "504. Tente novamente ou configure um modelo mais rápido."
    )


class AssistantRateLimitError(AssistantError):
    code = "gemini_rate_limit"
    public_message = (
        "O Google retornou 429: limite de requisições ou cota excedida. "
        "Confira a cota do projeto no Google AI Studio e tente mais tarde."
    )


class AssistantInvalidResponseError(AssistantError):
    code = "gemini_invalid_response"
    public_message = (
        "O Gemini não retornou uma resposta de texto completa e utilizável. "
        "A resposta pode ter sido bloqueada ou atingido o limite de saída."
    )


class AssistantDemoConfigurationError(AssistantUnavailableError):
    code = "assistant_demo_not_configured"
    public_message = (
        "As ferramentas de demonstração exigem APP_ENV=development ou test e "
        "ASSISTANT_DEMO_BUSINESS_ID configurado no backend. Não habilite em produção."
    )


class AssistantDemoBusinessNotFoundError(AssistantError):
    code = "assistant_demo_business_not_found"
    public_message = "A empresa de demonstração configurada no backend não existe."


class AssistantToolCallError(AssistantError):
    code = "assistant_invalid_tool_call"
    public_message = (
        "O modelo solicitou uma ferramenta não autorizada ou argumentos inválidos. "
        "A consulta foi interrompida."
    )


class AssistantToolLimitError(AssistantError):
    code = "assistant_tool_limit"
    public_message = "Limite de cinco chamadas de ferramentas por mensagem atingido."


class AssistantToolDatabaseError(AssistantUnavailableError):
    code = "assistant_database_unavailable"
    public_message = "Não foi possível consultar os dados da empresa de demonstração."
