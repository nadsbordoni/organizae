import hashlib
import logging
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from sqlalchemy.orm import Session

from app.modules.password_recovery.messages import recovery_message
from app.modules.password_recovery.models import PasswordResetToken
from app.modules.password_recovery.repository import PasswordResetTokenRepository
from app.modules.users.repository import UserRepository

logger = logging.getLogger(__name__)

TOKEN_TTL = timedelta(minutes=30)
# Against flooding someone's inbox: a new request inside this window is ignored.
REQUEST_COOLDOWN = timedelta(minutes=1)


class RecoveryEmail(NamedTuple):
    to: str
    subject: str
    body: str


def hash_token(token: str) -> str:
    # The token is random and long, so a fast hash is enough; it is not a password.
    return hashlib.sha256(token.encode()).hexdigest()


class PasswordRecoveryService:
    def __init__(self, session: Session, reset_url: str) -> None:
        self.session = session
        self.reset_url = reset_url
        self.user_repository = UserRepository(session)
        self.token_repository = PasswordResetTokenRepository(session)

    def request(
        self, email: str, *, now: datetime | None = None
    ) -> RecoveryEmail | None:
        """Prepares the instructions e-mail, or returns None when there is nothing to send.

        The caller must answer the client the same way in both cases, so the response
        never tells whether the e-mail is registered. Sending is left to the caller,
        after this commit, so a slow mail server neither holds the transaction nor
        makes the answer slower for registered e-mails."""
        if not self.reset_url:
            logger.warning("PASSWORD_RESET_URL is not set; password recovery is off")
            return None
        now = now or datetime.now(UTC)
        user = self.user_repository.get_by_email(email.strip().lower())
        if user is None or not user.is_active:
            return None
        to, name = user.email, user.name
        with self._transaction():
            if self.token_repository.has_created_since(user.id, now - REQUEST_COOLDOWN):
                return None
            # Only the newest link works.
            self.token_repository.invalidate_unused(user.id, now)
            token = secrets.token_urlsafe(32)
            self.token_repository.create(
                PasswordResetToken(
                    user_id=user.id,
                    token_hash=hash_token(token),
                    expires_at=now + TOKEN_TTL,
                    created_at=now,
                )
            )
            self.session.commit()
        subject, body = recovery_message(
            name=name, link=f"{self.reset_url}?token={token}", valid_for=TOKEN_TTL
        )
        return RecoveryEmail(to=to, subject=subject, body=body)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            yield
        except Exception:
            # Cleanup must also cover unexpected errors without hiding them.
            self.session.rollback()
            raise
