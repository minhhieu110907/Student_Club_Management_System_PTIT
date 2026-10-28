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


def find_refresh_token_by_digest(session: Session, token_hash: bytes) -> RefreshToken | None:
    return session.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))


def lock_refresh_token_family(session: Session, family_id: bytes) -> RefreshTokenFamily | None:
    return session.scalar(
        select(RefreshTokenFamily).where(RefreshTokenFamily.id == family_id).with_for_update()
    )


def lock_refresh_token(session: Session, token_id: int, token_hash: bytes) -> RefreshToken | None:
    return session.scalar(
        select(RefreshToken)
        .where(RefreshToken.id == token_id, RefreshToken.token_hash == token_hash)
        .with_for_update()
    )


def add_initial_session(
    session: Session,
    family: RefreshTokenFamily,
    token: RefreshToken,
) -> None:
    session.add(family)
    session.flush()
    session.add(token)
    session.flush()


def rotate_refresh_token(
    session: Session,
    predecessor: RefreshToken,
    successor: RefreshToken,
) -> None:
    session.flush([predecessor])
    session.add(successor)
    session.flush([successor])
    predecessor.replaced_by_id = successor.id
    session.flush([predecessor])
