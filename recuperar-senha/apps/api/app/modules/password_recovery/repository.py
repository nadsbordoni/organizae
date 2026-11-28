from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules.password_recovery.models import PasswordResetToken


class PasswordResetTokenRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, token: PasswordResetToken) -> PasswordResetToken:
        self.session.add(token)
        self.session.flush()
        return token

    def has_created_since(self, user_id: UUID, since: datetime) -> bool:
        statement = select(PasswordResetToken.id).where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.created_at >= since,
        )
        return self.session.scalar(statement.limit(1)) is not None

    def invalidate_unused(self, user_id: UUID, now: datetime) -> None:
        self.session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.used_at.is_(None),
            )
            .values(used_at=now)
        )
