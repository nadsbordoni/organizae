from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.users.models import User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        name: str,
        email: str,
        password_hash: str,
    ) -> User:
        user = User(
            name=name,
            email=email,
            password_hash=password_hash,
        )

        self.session.add(user)
        self.session.flush()

        return user

    def get_by_id(self, user_id: UUID) -> User | None:
        return self.session.get(User, user_id)

    def get_by_id_for_update(self, user_id: UUID) -> User | None:
        statement = (
            select(User)
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return self.session.scalar(statement)

    def get_by_email(self, email: str) -> User | None:
        statement = select(User).where(User.email == email)
        return self.session.scalar(statement)

    def update(self, user: User, **fields: object) -> User:
        for field_name, value in fields.items():
            setattr(user, field_name, value)

        self.session.flush()
        return user
