from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.identity.models import RefreshToken, RefreshTokenFamily, User


def add_user(session: Session, user: User) -> None:
    session.add(user)
    session.flush()


def find_user_by_email(session: Session, email_normalized: str) -> User | None:
    return session.scalar(select(User).where(User.email_normalized == email_normalized))


def find_user_by_id(session: Session, user_id: int) -> User | None:
    return session.get(User, user_id)


def add_initial_session(
    session: Session,
    family: RefreshTokenFamily,
    token: RefreshToken,
) -> None:
    session.add(family)
    session.flush()
    session.add(token)
    session.flush()
