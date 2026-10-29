from collections.abc import Iterator
from copy import deepcopy
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from google.genai import errors, types
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

with patch.dict(
    "os.environ",
    {
        "DB_HOST": "localhost",
        "DB_NAME": "organizae_test",
        "DB_USER": "test",
        "DB_PASSWORD": "test",
    },
):
    from app.core.config import settings
    from app.db.session import get_db
    from app.main import app
    from app.modules.assistant.router import (
        get_assistant_provider,
        get_assistant_tools,
    )

from app.modules.assistant.exceptions import (
    AssistantBusinessNotFoundError,
    AssistantInvalidResponseError,
    AssistantToolCallError,
    AssistantToolDatabaseError,
    AssistantToolLimitError,
)
from app.modules.assistant.providers.base import (
    AssistantProvider,
    ProviderReply,
    ToolCall,
)
from app.modules.assistant.providers.gemini import GeminiProvider
from app.modules.assistant.schemas import ChatRequest
from app.modules.assistant.service import AssistantService
from app.modules.assistant.tools import AssistantTools
from app.modules.auth.dependencies import get_current_user
from app.modules.businesses.exceptions import BusinessNotFoundError
from app.modules.businesses.models import Business, ServiceMode
from app.modules.businesses.service import BusinessService
from app.modules.professionals.models import Professional
from app.modules.professionals.service import ProfessionalService
from app.modules.services.models import Service
from app.modules.services.service import ServiceService
from app.modules.users.models import User

pytestmark = pytest.mark.usefixtures("assistant_identity")

PATH = "/api/v1/assistant/chat"


@pytest.fixture
def assistant_identity() -> Iterator[User]:
    user = User(id=uuid4(), business_id=uuid4(), is_active=True)
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield user
    finally:
        app.dependency_overrides.pop(get_current_user)


@pytest.fixture
def tools(assistant_identity: User) -> AssistantTools:
    business_id = assistant_identity.business_id
    businesses = Mock(spec=BusinessService)
    businesses.get_by_id.return_value = Business(
        id=business_id,
        name="Demo",
        description="Empresa fictícia",
        service_mode=ServiceMode.PRESENCIAL,
        whatsapp="private-contact",
    )
    professionals = Mock(spec=ProfessionalService)
    professionals.list.return_value = [
        Professional(
            business_id=business_id,
            name="Ana",
            description="Cortes",
            is_active=True,
            phone="private-phone",
        )
    ]
    services = Mock(spec=ServiceService)
    services.list.return_value = [
        Service(
            business_id=business_id,
            name="Corte",
            description="Corte simples",
            price=Decimal("35.50"),
            duration_minutes=30,
            is_active=True,
        )
    ]
    return AssistantTools(
        business_id,
        businesses,
        professionals,
        services,
        user_id=assistant_identity.id,
    )


@pytest.mark.parametrize(
    "name, arguments, expected",
    [
        (
            "get_business_info",
            {},
            {
                "name": "Demo",
                "description": "Empresa fictícia",
                "service_mode": "PRESENCIAL",
            },
        ),
        (
            "list_professionals",
            {"is_active": True},
            {
                "items": [{"name": "Ana", "description": "Cortes", "is_active": True}],
                "offset": 0,
                "limit": 20,
            },
        ),
        (
            "list_services",
            {},
            {
                "items": [
                    {
                        "name": "Corte",
                        "description": "Corte simples",
                        "price": "35.50",
                        "duration_minutes": 30,
                        "is_active": True,
                    }
                ],
                "offset": 0,
                "limit": 20,
            },
        ),
    ],
)
def test_tool_uses_service_and_projects_only_allowed_fields(
    tools: AssistantTools,
    name: str,
    arguments: dict,
    expected: dict,
) -> None:
    result = tools.execute(ToolCall(name, arguments, id="call-1"))
    assert result.response == expected
    assert result.id == "call-1"
    if name == "get_business_info":
        tools.business_service.get_by_id.assert_called_once_with(tools.business_id)
        tools.professional_service.list.assert_not_called()
        tools.service_service.list.assert_not_called()
    elif name == "list_professionals":
        tools.professional_service.list.assert_called_once_with(
            business_id=tools.business_id,
            is_active=True,
            offset=0,
            limit=20,
        )
        tools.service_service.list.assert_not_called()
    else:
        tools.service_service.list.assert_called_once_with(
            business_id=tools.business_id,
            offset=0,
            limit=20,
        )
        tools.professional_service.list.assert_not_called()


@pytest.mark.parametrize("name", ["list_professionals", "list_services"])
def test_empty_page(tools: AssistantTools, name: str) -> None:
    tools.professional_service.list.return_value = []
    tools.service_service.list.return_value = []
    assert tools.execute(ToolCall(name, {})).response["items"] == []


@pytest.mark.parametrize(
    "name, arguments",
    [
        ("execute_sql", {"sql": "SELECT * FROM businesses"}),
        ("delete_service", {}),
        ("list_services", {"business_id": str(uuid4())}),
        ("get_business_info", {"business_id": str(uuid4())}),
        ("list_professionals", {"business_id": str(uuid4())}),
        ("list_services", {"offset": -1}),
        ("list_services", {"limit": 101}),
        ("list_services", {"limit": True}),
        ("list_professionals", {"is_active": "true"}),
        ("list_services", {"limit": "20"}),
        ("list_services", {"sql": "SELECT 1"}),
    ],
)
def test_rejects_unapproved_tools_and_arguments_before_accessing_services(
    tools: AssistantTools,
    name: str,
    arguments: dict,
) -> None:
    with pytest.raises(AssistantToolCallError):
        tools.execute(ToolCall(name, arguments))
    assert tools.business_service.mock_calls == []
    assert tools.professional_service.mock_calls == []
    assert tools.service_service.mock_calls == []


def mock_conversation(replies: list[ProviderReply]) -> tuple[Mock, Mock]:
    provider = Mock(spec=AssistantProvider)
    provider.conversation.return_value = MagicMock()
    conversation = provider.conversation.return_value.__enter__.return_value
    conversation.generate.side_effect = replies
    return provider, conversation


def test_service_orchestrates_multiple_tools_and_final_text(
    tools: AssistantTools,
) -> None:
    provider, conversation = mock_conversation(
        [
            ProviderReply(
                calls=[
                    ToolCall("get_business_info", {}, "1"),
                    ToolCall("list_professionals", {"is_active": False}, "2"),
                ]
            ),
            ProviderReply(calls=[ToolCall("list_services", {}, "3")]),
            ProviderReply(text=" A empresa Demo oferece Corte por 35,50. "),
        ]
    )
    result = AssistantService(provider, tools).chat(
        ChatRequest(message="Consulte a demo")
    )
    assert result.response == "A empresa Demo oferece Corte por 35,50."
    calls = conversation.generate.call_args_list
    assert calls[1].args[0][0].name == "get_business_info"
    assert calls[2].args[0][0].response["items"][0]["price"] == "35.50"
    assert (
        "dados não confiáveis"
        in provider.conversation.call_args.kwargs["system_prompt"]
    )
    names = {
        item["name"] for item in provider.conversation.call_args.kwargs["declarations"]
    }
    assert {"get_business_info", "list_professionals", "list_services"} <= names
    if settings.APP_ENV != "development" or not settings.ASSISTANT_WRITES_ENABLED:
        assert names == {"get_business_info", "list_professionals", "list_services"}
    assert "business_id" not in str(tools.declarations())
    tools.professional_service.list.assert_called_once_with(
        business_id=tools.business_id,
        is_active=False,
        offset=0,
        limit=20,
    )
    provider.generate.assert_not_called()
    provider.conversation.return_value.__exit__.assert_called_once()


def test_validates_entire_batch_before_executing(tools: AssistantTools) -> None:
    provider, _ = mock_conversation(
        [
            ProviderReply(
                calls=[
                    ToolCall("list_services", {}),
                    ToolCall("list_professionals", {"business_id": str(uuid4())}),
                ]
            )
        ]
    )
    with pytest.raises(AssistantToolCallError):
        AssistantService(provider, tools).chat(ChatRequest(message="oi"))
    tools.service_service.list.assert_not_called()
    tools.professional_service.list.assert_not_called()


@pytest.mark.parametrize("batch_size", [1, 6])
def test_limits_calls_including_parallel_batches(
    tools: AssistantTools, batch_size: int
) -> None:
    provider, conversation = mock_conversation(
        [ProviderReply(calls=[ToolCall("list_services", {})] * batch_size)] * 6
    )
    with pytest.raises(AssistantToolLimitError):
        AssistantService(provider, tools).chat(ChatRequest(message="oi"))
    assert tools.service_service.list.call_count == (5 if batch_size == 1 else 0)
    assert conversation.generate.call_count <= 6


@pytest.mark.parametrize(
    "failure, expected",
    [
        (BusinessNotFoundError("internal"), AssistantBusinessNotFoundError),
        (
            OperationalError("private-sql", {}, Exception("private-password")),
            AssistantToolDatabaseError,
        ),
    ],
)
def test_context_errors_before_contacting_gemini(
    tools: AssistantTools,
    failure: Exception,
    expected: type[Exception],
) -> None:
    tools.business_service.get_by_id.side_effect = failure
    provider = Mock(spec=AssistantProvider)
    with pytest.raises(expected):
        AssistantService(provider, tools).chat(ChatRequest(message="oi"))
    provider.conversation.assert_not_called()


@pytest.mark.parametrize(
    "environment, business_id",
    [
        ("production", uuid4()),
        ("development", None),
        ("test", None),
    ],
)
def test_demo_settings_cannot_override_authenticated_business(
    environment: str,
    business_id: object,
    assistant_identity: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSISTANT_DEMO_ENABLED", "true")
    monkeypatch.setenv("ASSISTANT_DEMO_BUSINESS_ID", str(business_id))
    with patch.object(settings, "APP_ENV", environment):
        tools = get_assistant_tools(
            Mock(spec=Session),
            assistant_identity,
            assistant_identity.business_id,
        )
    assert tools.business_id == assistant_identity.business_id
    assert tools.user_id == assistant_identity.id


def test_production_keeps_authenticated_read_tools(assistant_identity: User) -> None:
    with patch.object(settings, "APP_ENV", "production"):
        tools = get_assistant_tools(
            Mock(spec=Session),
            assistant_identity,
            assistant_identity.business_id,
        )
    assert tools.business_id == assistant_identity.business_id


def sdk_reply(*parts: types.Part) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                finish_reason=types.FinishReason.STOP,
                content=types.Content(role="model", parts=list(parts)),
            )
        ]
    )


@pytest.fixture
def tool_client(tools: AssistantTools) -> Iterator[tuple[TestClient, Mock]]:
    provider = GeminiProvider(
        settings.model_copy(
            update={
                "GEMINI_API_KEY": SecretStr("test-key"),
                "GEMINI_MODEL": "test-model",
            }
        )
    )
    session = Mock(spec=Session)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_assistant_provider] = lambda: provider
    app.dependency_overrides[get_assistant_tools] = lambda: tools
    try:
        with patch("app.modules.assistant.providers.gemini.genai.Client") as factory:
            sdk_client = factory.return_value.__enter__.return_value
            with TestClient(app) as client:
                yield client, sdk_client
    finally:
        for dependency in (get_db, get_assistant_provider, get_assistant_tools):
            app.dependency_overrides.pop(dependency)


def test_endpoint_round_trip_preserves_signatures_and_function_response(
    tool_client: tuple[TestClient, Mock],
    tools: AssistantTools,
) -> None:
    client, sdk_client = tool_client
    snapshots = []
    call_part = types.Part(
        function_call=types.FunctionCall(name="list_services", args={}, id="call-1"),
        thought_signature=b"opaque-signature",
    )
    replies = iter(
        [sdk_reply(call_part), sdk_reply(types.Part(text="Corte custa 35,50."))]
    )

    def respond(**kwargs: object) -> types.GenerateContentResponse:
        snapshots.append(deepcopy(kwargs))
        return next(replies)

    sdk_client.models.generate_content.side_effect = respond
    response = client.post(PATH, json={"message": "Quais serviços a demo oferece?"})
    assert response.status_code == 200
    assert response.json() == {"response": "Corte custa 35,50."}
    assert len(snapshots[0]["contents"]) == 1
    history = snapshots[1]["contents"]
    assert history[1].parts[0].thought_signature == b"opaque-signature"
    result = history[2].parts[0].function_response
    assert result.name == "list_services"
    assert result.id == "call-1"
    assert result.response["items"][0]["price"] == "35.50"
    assert "private-contact" not in str(history)
    assert "private-phone" not in str(history)
    assert snapshots[0]["config"].automatic_function_calling.disable is True


@pytest.mark.parametrize(
    "name, args, expected_code",
    [
        ("list_services", {"business_id": str(uuid4())}, "assistant_invalid_tool_call"),
        ("execute_sql", {}, "assistant_invalid_tool_call"),
    ],
)
def test_endpoint_rejects_unsafe_function_calls(
    tool_client: tuple[TestClient, Mock],
    tools: AssistantTools,
    name: str,
    args: dict,
    expected_code: str,
) -> None:
    client, sdk_client = tool_client
    sdk_client.models.generate_content.return_value = sdk_reply(
        types.Part(
            function_call=types.FunctionCall(name=name, args=args),
        )
    )
    response = client.post(PATH, json={"message": "oi"})
    assert response.status_code == 502
    assert response.json()["code"] == expected_code
    tools.service_service.list.assert_not_called()


@pytest.mark.parametrize(
    "failure, code",
    [
        (httpx.ConnectError("sensitive-provider-detail"), "gemini_connection_error"),
        (
            errors.ServerError(503, {"message": "sensitive-provider-detail"}),
            "gemini_unavailable",
        ),
    ],
)
def test_endpoint_failure_after_tool_result(
    tool_client: tuple[TestClient, Mock],
    failure: Exception,
    code: str,
) -> None:
    client, sdk_client = tool_client
    sdk_client.models.generate_content.side_effect = [
        sdk_reply(
            types.Part(function_call=types.FunctionCall(name="list_services", args={}))
        ),
        failure,
        failure,
        failure,
    ]
    with patch("app.modules.assistant.providers.gemini.time.sleep"):
        response = client.post(PATH, json={"message": "oi"})
    assert response.status_code == 503
    assert response.json()["code"] == code
    assert "sensitive-provider-detail" not in response.text


def test_demo_cannot_bypass_authentication(
    assistant_identity: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSISTANT_DEMO_ENABLED", "true")
    session = Mock(spec=Session)
    app.dependency_overrides[get_db] = lambda: session
    identity_override = app.dependency_overrides.pop(get_current_user)
    try:
        with (
            patch.object(settings, "APP_ENV", "production"),
            TestClient(app) as client,
        ):
            response = client.post(PATH, json={"message": "oi"})
        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(get_db)
        app.dependency_overrides[get_current_user] = identity_override


def test_nontext_final_reply_is_rejected(tools: AssistantTools) -> None:
    provider, _ = mock_conversation([ProviderReply()])
    with pytest.raises(AssistantInvalidResponseError):
        AssistantService(provider, tools).chat(ChatRequest(message="oi"))


@pytest.mark.parametrize("environment", ["development", "test"])
def test_dependencies_bind_all_services_to_same_session(environment: str) -> None:
    session = Mock(spec=Session)
    business_id = uuid4()
    with patch.object(settings, "APP_ENV", environment):
        user = User(id=uuid4(), business_id=business_id, is_active=True)
        tools = get_assistant_tools(session, user, business_id)
    assert tools.business_id == business_id
    assert tools.business_service.repository.session is session
    assert tools.professional_service.repository.session is session
    assert tools.service_service.repository.session is session
    session.commit.assert_not_called()


@pytest.mark.parametrize(
    "failure, expected_status, code",
    [
        (BusinessNotFoundError("private"), 404, "assistant_business_not_found"),
        (
            OperationalError("private-sql", {}, Exception("private-password")),
            503,
            "assistant_database_unavailable",
        ),
        (None, 200, None),
    ],
)
def test_request_session_is_released_on_success_and_failure(
    tools: AssistantTools,
    failure: Exception | None,
    expected_status: int,
    code: str | None,
) -> None:
    provider, _ = mock_conversation([ProviderReply(text="Empresa Demo")])
    session_factory = MagicMock()
    session = session_factory.return_value.__enter__.return_value
    business_service = tools.business_service
    business_service.get_by_id.side_effect = failure
    app.dependency_overrides[get_assistant_provider] = lambda: provider
    try:
        with (
            patch.multiple(
                settings,
                APP_ENV="test",
            ),
            patch("app.db.session.SessionLocal", session_factory),
            patch(
                "app.modules.assistant.router.BusinessService",
                return_value=business_service,
            ),
            TestClient(app) as client,
        ):
            response = client.post(PATH, json={"message": "oi"})
        assert response.status_code == expected_status
        if code:
            assert response.json()["code"] == code
            assert "private" not in response.text
        session_factory.return_value.__exit__.assert_called_once()
        session.commit.assert_not_called()
    finally:
        app.dependency_overrides.pop(get_assistant_provider)
