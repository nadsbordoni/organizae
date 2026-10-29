from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.assistant.exceptions import (
    AssistantConversationNotFoundError,
    AssistantToolDatabaseError,
)
from app.modules.assistant.models import AssistantConversation, AssistantMessage
from app.modules.assistant.providers.base import ContextMessage
from app.modules.assistant.repository import ConversationRepository
from app.modules.assistant.schemas import ChatResponse


class ConversationService:
    def __init__(self, session: Session, *, user_id: UUID, business_id: UUID) -> None:
        self.session = session
        self.user_id = user_id
        self.business_id = business_id
        self.repository = ConversationRepository(session)

    def get(
        self, conversation_id: UUID, *, lock: bool = False
    ) -> AssistantConversation:
        with self.transaction(commit=False):
            conversation = self.repository.get(
                conversation_id,
                user_id=self.user_id,
                business_id=self.business_id,
                lock=lock,
            )
            if conversation is None:
                raise AssistantConversationNotFoundError()
        return conversation

    def list(self, *, offset: int, limit: int) -> list[AssistantConversation]:
        with self.transaction(commit=False):
            return self.repository.list(
                user_id=self.user_id,
                business_id=self.business_id,
                offset=offset,
                limit=limit,
            )

    def create(self, title: str) -> AssistantConversation:
        with self.transaction():
            conversation = self.repository.create(
                user_id=self.user_id,
                business_id=self.business_id,
                title=title,
            )
        return conversation

    def open_turn(
        self, conversation_id: UUID | None, message: str
    ) -> AssistantConversation:
        if conversation_id is not None:
            return self.get(conversation_id, lock=True)
        return self.repository.create(
            user_id=self.user_id,
            business_id=self.business_id,
            title=message[:80],
        )

    def delete(self, conversation_id: UUID) -> None:
        with self.transaction():
            self.repository.delete(self.get(conversation_id, lock=True))

    def messages(
        self, conversation_id: UUID, *, offset: int, limit: int
    ) -> list[AssistantMessage]:
        with self.transaction(commit=False):
            self.get(conversation_id)
            return self.repository.messages(
                conversation_id,
                user_id=self.user_id,
                business_id=self.business_id,
                offset=offset,
                limit=limit,
            )

    def recent_context(self, conversation_id: UUID) -> list[ContextMessage]:
        messages = self.repository.messages(
            conversation_id,
            user_id=self.user_id,
            business_id=self.business_id,
            limit=14,
            newest_first=True,
        )
        return [
            ContextMessage(role=item.role, content=item.content)
            for item in reversed(messages)
        ]

    def save_turn(
        self, conversation: AssistantConversation, message: str, response: ChatResponse
    ) -> None:
        for role, content, pending in (
            ("user", message, None),
            ("assistant", response.response, response.pending_actions),
        ):
            conversation.message_count += 1
            self.repository.add_message(
                AssistantMessage(
                    conversation_id=conversation.id,
                    user_id=self.user_id,
                    business_id=self.business_id,
                    position=conversation.message_count,
                    role=role,
                    content=content,
                    pending_actions=pending,
                )
            )
        conversation.updated_at = datetime.now(UTC)

    @contextmanager
    def transaction(self, *, commit: bool = True) -> Iterator[None]:
        completed = False
        try:
            yield
            if commit:
                self.session.commit()
            completed = True
        except SQLAlchemyError as exc:
            raise AssistantToolDatabaseError() from exc
        finally:
            if not completed:
                self.session.rollback()
