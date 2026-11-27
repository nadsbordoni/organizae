"""Promote an existing user to platform admin.

    uv run python -m scripts.create_platform_admin pessoa@exemplo.com

It is the only way to become an admin: no API route sets the flag. The user must
already have signed up (that is how the password gets created).
"""

import argparse
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.users.models import User


def promote(session: Session, email: str) -> User:
    """Flags the user; the caller commits."""
    normalized = email.strip().lower()
    user = session.scalar(select(User).where(User.email == normalized))
    if user is None:
        raise LookupError(f"No user with the email {normalized}")
    if not user.is_active:
        raise ValueError(f"The user {normalized} is inactive")
    user.is_platform_admin = True
    session.flush()
    return user


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Torna um usuário já cadastrado administrador da plataforma."
    )
    parser.add_argument("email", help="E-mail do usuário.")
    args = parser.parse_args(argv)

    # Imported here so that importing promote() does not need the environment.
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        try:
            user = promote(session, args.email)
        except (LookupError, ValueError) as error:
            print(f"Erro: {error}", file=sys.stderr)
            return 1
        session.commit()
    print(f"{user.email} agora é administrador da plataforma.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
