from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from google.genai import types
from sqlalchemy import Engine, func, inspect, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from test_assistant_auth import (
    BUSINESS_A,
    BUSINESS_B,
    USER_A,
    USER_B,
    headers,
    request_tool,
)

from app.modules.assistant.exceptions import (
    AssistantContextLimitError,
    AssistantUnavailableError,
)
from app.modules.assistant.history_service import ConversationService
from app.modules.assistant.models import AssistantConversation, AssistantMessage
from app.modules.assistant.providers.base import ContextMessage, ProviderReply
from app.modules.assistant.providers.gemini import GeminiConversation
from app.modules.assistant.repository import ConversationRepository
from app.modules.users.models import User

ROOT = "/api/v1/assistant/conversations"
CHAT = "/api/v1/assistant/chat"
pytest_plugins = ["test_assistant_auth"]


def chat(
    api: tuple[TestClient, Mock],
    message: str = "Olá",
    conversation_id: str | None = None,
) -> dict:
    client, provider = api
    conversation = provider.conversation.return_value.__enter__.return_value
    conversation.generate.side_effect = [ProviderReply(text=f"Resposta: {message}")]
    payload = {"message": message}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    response = client.post(CHAT, headers=headers(USER_A), json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_conversation_crud_and_paginated_messages(
    api: tuple[TestClient, Mock], database: Engine
) -> None:
    client, _ = api
    authentication = headers(USER_A)
    created = client.post(
        ROOT, headers=authentication, json={"title": " Planejamento "}
    )
    assert created.status_code == 201
    identifier = created.json()["id"]
    assert created.json()["title"] == "Planejamento"
    assert created.json()["message_count"] == 0
    assert (
        client.get(f"{ROOT}/{identifier}/messages", headers=authentication).json() == []
    )
    for message in ("Meu nome é Ana", "Qual meu nome?"):
        assert chat(api, message, identifier)["conversation_id"] == identifier
    found = client.get(f"{ROOT}/{identifier}", headers=authentication)
    assert found.status_code == 200 and found.json()["message_count"] == 4
    listed = client.get(ROOT, headers=authentication).json()
    assert [item["id"] for item in listed] == [identifier]
    messages = client.get(
        f"{ROOT}/{identifier}/messages", headers=authentication
    ).json()
    assert [item["role"] for item in messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert [item["position"] for item in messages] == [1, 2, 3, 4]
    assert messages[0]["content"] == "Meu nome é Ana"
    page = client.get(
        f"{ROOT}/{identifier}/messages",
        headers=authentication,
        params={"offset": 1, "limit": 2},
    ).json()
    assert [item["position"] for item in page] == [2, 3]
    assert (
        client.delete(f"{ROOT}/{identifier}", headers=authentication).status_code == 204
    )
    assert client.get(f"{ROOT}/{identifier}", headers=authentication).status_code == 404
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(AssistantMessage)) == 0


def test_chat_creates_conversation_and_persists_atomic_turn(
    api: tuple[TestClient, Mock], database: Engine
) -> None:
    result = chat(api)
    with Session(database) as session:
        conversation = session.get(
            AssistantConversation, UUID(result["conversation_id"])
        )
        assert conversation.user_id == USER_A and conversation.business_id == BUSINESS_A
        assert conversation.message_count == 2
        assert [item.content for item in conversation.messages] == [
            "Olá",
            "Resposta: Olá",
        ]
        assert all(
            item.user_id == USER_A and item.business_id == BUSINESS_A
            for item in conversation.messages
        )


def test_context_is_last_fourteen_stored_messages_plus_current(
    api: tuple[TestClient, Mock],
) -> None:
    _, provider = api
    identifier = chat(api, "Message 0")["conversation_id"]
    for index in range(1, 10):
        chat(api, f"Message {index}", identifier)
    history = provider.conversation.call_args.kwargs["history"]
    assert len(history) == 14
    assert history[0].content == "Message 2"
    assert history[-1].content == "Resposta: Message 8"
    assert provider.conversation.call_args.args == ("Message 9",)
    assert history[0].role == "user" and history[-1].role == "assistant"


@pytest.mark.parametrize("operation", ["get", "messages", "delete", "chat"])
def test_other_user_and_tenant_cannot_access_history(
    api: tuple[TestClient, Mock],
    database: Engine,
    operation: str,
) -> None:
    client, provider = api
    identifier = chat(api)["conversation_id"]
    before = provider.conversation.call_count

    def attempt() -> int:
        if operation == "chat":
            return client.post(
                CHAT,
                headers=headers(USER_B),
                json={"message": "Access", "conversation_id": identifier},
            ).status_code
        path = f"{ROOT}/{identifier}" + ("/messages" if operation == "messages" else "")
        return client.request(
            "DELETE" if operation == "delete" else "GET", path, headers=headers(USER_B)
        ).status_code

    assert attempt() == 404
    # Ownership of the same business still does not transfer another user's history.
    with Session(database) as session:
        session.get(User, USER_A).business_id = None
        session.flush()
        session.get(User, USER_B).business_id = BUSINESS_A
        session.commit()
    assert attempt() == 404
    assert client.get(ROOT, headers=headers(USER_B)).json() == []
    assert provider.conversation.call_count == before


@pytest.mark.parametrize(
    "path, method, payload",
    [
        (ROOT, "POST", {}),
        (ROOT, "GET", None),
        (f"{ROOT}/{uuid4()}", "GET", None),
        (f"{ROOT}/{uuid4()}/messages", "GET", None),
        (f"{ROOT}/{uuid4()}", "DELETE", None),
    ],
)
def test_history_routes_require_authentication(
    api: tuple[TestClient, Mock], path: str, method: str, payload: dict | None
) -> None:
    client, _ = api
    assert client.request(method, path, json=payload).status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        {"title": " "},
        {"title": "x" * 129},
        {"business_id": str(BUSINESS_B)},
        {"user_id": str(USER_B)},
    ],
)
def test_create_rejects_invalid_or_client_owned_context(
    api: tuple[TestClient, Mock], payload: dict
) -> None:
    client, _ = api
    assert client.post(ROOT, headers=headers(USER_A), json=payload).status_code == 422


@pytest.mark.parametrize("existing", [False, True])
def test_gemini_failure_rolls_back_user_message_and_implicit_conversation(
    api: tuple[TestClient, Mock],
    database: Engine,
    existing: bool,
) -> None:
    client, provider = api
    identifier = chat(api)["conversation_id"] if existing else None
    provider.conversation.return_value.__enter__.return_value.generate.side_effect = (
        AssistantUnavailableError()
    )
    body = {"message": "Failure"}
    if identifier:
        body["conversation_id"] = identifier
    response = client.post(CHAT, headers=headers(USER_A), json=body)
    assert response.status_code == 503
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(AssistantMessage)) == (
            2 if existing else 0
        )
        assert session.scalar(
            select(func.count()).select_from(AssistantConversation)
        ) == (1 if existing else 0)


def test_database_failure_rolls_back_whole_turn(
    api: tuple[TestClient, Mock], database: Engine
) -> None:
    client, provider = api
    provider.conversation.return_value.__enter__.return_value.generate.side_effect = [
        ProviderReply(text="ok")
    ]
    original = ConversationRepository.add_message

    def fail_second(
        repository: ConversationRepository, message: AssistantMessage
    ) -> None:
        if message.role == "assistant":
            raise OperationalError("private sql", {}, Exception("private credential"))
        original(repository, message)

    with patch.object(ConversationRepository, "add_message", fail_second):
        response = client.post(CHAT, headers=headers(USER_A), json={"message": "Hi"})
    assert response.status_code == 503
    assert "private" not in response.text
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(AssistantMessage)) == 0
        assert (
            session.scalar(select(func.count()).select_from(AssistantConversation)) == 0
        )


def test_read_only_context_does_not_disable_function_calling(
    api: tuple[TestClient, Mock],
) -> None:
    client, provider = api
    identifier = chat(api)["conversation_id"]
    conversation = request_tool(provider, "list_services")
    response = client.post(
        CHAT,
        headers=headers(USER_A),
        json={"message": "Liste", "conversation_id": identifier},
    )
    assert response.status_code == 200
    assert (
        conversation.generate.call_args.args[0][0].response["items"][0]["name"]
        == "Service A"
    )
    assert len(provider.conversation.call_args.kwargs["history"]) == 2


def test_pending_actions_and_idempotent_replay_keep_one_history_turn(
    api: tuple[TestClient, Mock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    client, provider = api
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "ASSISTANT_WRITES_ENABLED", True)
    request_tool(
        provider,
        "create_service",
        {"name": "New", "price": "25.00", "duration_minutes": 20},
    )
    payload = {"message": "Crie New", "request_id": str(uuid4())}
    first = client.post(CHAT, headers=headers(USER_A), json=payload)
    assert first.status_code == 200
    result = first.json()
    identifier = result["conversation_id"]
    assert client.post(CHAT, headers=headers(USER_A), json=payload).json() == result
    messages = client.get(
        f"{ROOT}/{identifier}/messages", headers=headers(USER_A)
    ).json()
    assert len(messages) == 2
    assert messages[1]["pending_actions"] == result["pending_actions"]
    action_id = result["pending_actions"][0]["id"]
    assert (
        client.post(
            f"/api/v1/assistant/actions/{action_id}/confirm",
            headers=headers(USER_A),
            json={"decision": "confirm"},
        ).status_code
        == 200
    )
    assert (
        client.delete(f"{ROOT}/{identifier}", headers=headers(USER_A)).status_code
        == 204
    )
    assert client.post(CHAT, headers=headers(USER_A), json=payload).status_code == 404
    assert provider.conversation.call_count == 1


def test_request_id_cannot_be_replayed_into_another_conversation(
    api: tuple[TestClient, Mock], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    client, provider = api
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "ASSISTANT_WRITES_ENABLED", True)
    first = client.post(ROOT, headers=headers(USER_A), json={}).json()["id"]
    second = client.post(ROOT, headers=headers(USER_A), json={}).json()["id"]
    request_tool(provider, "create_professional", {"name": "Ana"})
    body = {
        "message": "Cadastre Ana",
        "request_id": str(uuid4()),
        "conversation_id": first,
    }
    assert client.post(CHAT, headers=headers(USER_A), json=body).status_code == 200
    assert (
        client.post(
            CHAT, headers=headers(USER_A), json={**body, "conversation_id": second}
        ).status_code
        == 409
    )


def model_reply() -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                finish_reason=types.FinishReason.STOP,
                content=types.Content(role="model", parts=[types.Part(text="ok")]),
            )
        ]
    )


def test_provider_counts_tokens_and_trims_oldest_messages_without_changing_db_history() -> (
    None
):
    client = Mock()
    client.models.count_tokens.side_effect = [
        types.CountTokensResponse(total_tokens=count) for count in (110, 100)
    ]
    client.models.generate_content.return_value = model_reply()
    history = [ContextMessage("user", "older"), ContextMessage("assistant", "prior")]
    conversation = GeminiConversation(
        client, "model", "current", "system", [], history=history, token_limit=100
    )
    assert conversation.generate().text == "ok"
    supplied = client.models.generate_content.call_args.kwargs["contents"]
    assert [part.parts[0].text for part in supplied] == ["current"]
    assert supplied[0].role == "user"
    assert client.models.count_tokens.call_count == 2
    assert len(history) == 2


def test_oversized_current_message_or_tool_result_is_not_sent_to_generation() -> None:
    from app.modules.assistant.providers.base import ToolResult

    client = Mock()
    client.models.count_tokens.return_value = types.CountTokensResponse(
        total_tokens=101
    )
    conversation = GeminiConversation(
        client, "model", "current", "system", [], history=[], token_limit=100
    )
    with pytest.raises(AssistantContextLimitError):
        conversation.generate()
    client.models.generate_content.assert_not_called()
    with pytest.raises(AssistantContextLimitError):
        conversation.generate([ToolResult("list_services", {"items": []})])
    client.models.generate_content.assert_not_called()


def test_row_lock_and_owner_filters_are_part_of_postgresql_query() -> None:
    from sqlalchemy.dialects import postgresql

    session = Mock(spec=Session)
    ConversationRepository(session).get(
        uuid4(), user_id=USER_A, business_id=BUSINESS_A, lock=True
    )
    query = str(session.scalar.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in query
    assert (
        "assistant_conversations.user_id =" in query
        and "assistant_conversations.business_id =" in query
    )


def test_message_foreign_key_prevents_owner_mismatch(database: Engine) -> None:
    with database.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    with Session(database) as session:
        service = ConversationService(session, user_id=USER_A, business_id=BUSINESS_A)
        conversation = service.create("Private")
        session.add(
            AssistantMessage(
                conversation_id=conversation.id,
                user_id=USER_B,
                business_id=BUSINESS_B,
                position=1,
                role="user",
                content="Forbidden",
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_history_migration_is_additive_and_postgresql_sql_is_valid() -> None:
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision("e6f8a2c93104")
    assert script.get_current_head() == revision.revision
    assert revision.down_revision == "c2e74a9b8106"
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        revision.module.upgrade()
    sql = output.getvalue()
    assert "CREATE TABLE assistant_conversations" in sql
    assert "CREATE TABLE assistant_messages" in sql
    assert "ON DELETE CASCADE" in sql and "TIMESTAMP WITH TIME ZONE" in sql
    assert "fk_assistant_message_conversation_owner" in sql
    assert "DROP" not in sql and "ALTER TABLE users" not in sql


def test_history_migration_upgrade_and_downgrade_in_isolated_database() -> None:
    from sqlalchemy import create_engine

    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    revision = ScriptDirectory.from_config(config).get_revision("e6f8a2c93104")
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                revision.module.upgrade()
                assert set(inspect(connection).get_table_names()) == {
                    "assistant_conversations",
                    "assistant_messages",
                }
                revision.module.downgrade()
                assert inspect(connection).get_table_names() == []
    finally:
        engine.dispose()


def test_gemini_wire_history_preserves_user_and_model_roles() -> None:
    client = Mock()
    client.models.count_tokens.return_value = types.CountTokensResponse(
        total_tokens=100
    )
    client.models.generate_content.return_value = model_reply()
    history = [
        ContextMessage("user", "Meu nome é Ana"),
        ContextMessage("assistant", "Olá, Ana"),
    ]
    conversation = GeminiConversation(
        client, "model", "Qual meu nome?", "system", [], history=history
    )
    assert conversation.generate().text == "ok"
    supplied = client.models.generate_content.call_args.kwargs["contents"]
    assert [item.role for item in supplied] == ["user", "model", "user"]
    assert supplied[0].parts[0].text == "Meu nome é Ana"
    assert "config" not in client.models.count_tokens.call_args.kwargs


def test_conversation_listing_is_ordered_paginated_and_scoped(
    api: tuple[TestClient, Mock],
) -> None:
    client, _ = api
    first = client.post(ROOT, headers=headers(USER_A), json={"title": "First"}).json()[
        "id"
    ]
    second = client.post(
        ROOT, headers=headers(USER_A), json={"title": "Second"}
    ).json()["id"]
    client.post(ROOT, headers=headers(USER_B), json={"title": "Other tenant"})
    page = client.get(ROOT, headers=headers(USER_A), params={"limit": 1}).json()
    assert [item["id"] for item in page] == [second]
    chat(api, conversation_id=first)
    assert (
        client.get(ROOT, headers=headers(USER_A), params={"limit": 1}).json()[0]["id"]
        == first
    )
    assert (
        client.get(
            ROOT, headers=headers(USER_A), params={"offset": 1, "limit": 1}
        ).json()[0]["id"]
        == second
    )
    assert (
        client.get(ROOT, headers=headers(USER_A), params={"limit": 101}).status_code
        == 422
    )
