from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.assistant.models import AssistantConversation, AssistantMessage


class ConversationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(
        self,
        conversation_id: UUID,
        *,
        user_id: UUID,
        business_id: UUID,
        lock: bool = False,
    ) -> AssistantConversation | None:
        query = select(AssistantConversation).where(
            AssistantConversation.id == conversation_id,
            AssistantConversation.user_id == user_id,
            AssistantConversation.business_id == business_id,
        )
        if lock:
            query = query.with_for_update()
        return self.session.scalar(query.execution_options(populate_existing=True))

    def list(
        self,
        *,
        user_id: UUID,
        business_id: UUID,
        offset: int,
        limit: int,
    ) -> list[AssistantConversation]:
        query = (
            select(AssistantConversation)
            .where(
                AssistantConversation.user_id == user_id,
                AssistantConversation.business_id == business_id,
            )
            .order_by(
                AssistantConversation.updated_at.desc(), AssistantConversation.id.desc()
            )
        )
        return list(self.session.scalars(query.offset(offset).limit(limit)).all())

    def create(
        self, *, user_id: UUID, business_id: UUID, title: str
    ) -> AssistantConversation:
        conversation = AssistantConversation(
            user_id=user_id, business_id=business_id, title=title
        )
        self.session.add(conversation)
        self.session.flush()
        return conversation

    def messages(
        self,
        conversation_id: UUID,
        *,
        user_id: UUID,
        business_id: UUID,
        offset: int = 0,
        limit: int = 100,
        newest_first: bool = False,
    ) -> list[AssistantMessage]:
        query = (
            select(AssistantMessage)
            .where(
                AssistantMessage.conversation_id == conversation_id,
                AssistantMessage.user_id == user_id,
                AssistantMessage.business_id == business_id,
            )
            .order_by(
                AssistantMessage.position.desc()
                if newest_first
                else AssistantMessage.position
            )
        )
        return list(self.session.scalars(query.offset(offset).limit(limit)).all())

    def add_message(self, message: AssistantMessage) -> None:
        self.session.add(message)
        self.session.flush()

    def delete(self, conversation: AssistantConversation) -> None:
        self.session.delete(conversation)
        self.session.flush()
