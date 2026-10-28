from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.modules.users.exceptions import InvalidUserDataError, UserConflictError
from app.modules.users.models import User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate


class UserService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = UserRepository(session)

    def create(self, user_data: UserCreate) -> User:
        try:
            email = str(user_data.email).strip().lower()
            if len(email) > 255:
                raise InvalidUserDataError("Email must contain at most 255 characters")
            if self.repository.get_by_email(email) is not None:
                raise UserConflictError("Email is already registered")

            user = self.repository.create(
                name=user_data.name,
                email=email,
                password_hash=hash_password(user_data.password),
            )
            self.session.commit()
            self.session.refresh(user)
            return user
        except IntegrityError as exc:
            self.session.rollback()
            raise UserConflictError(
                "Unable to create user because the data conflicts with an existing record"
            ) from exc
        except Exception:
            # Clean up failed writes and validations without hiding unexpected errors.
            self.session.rollback()
            raise
