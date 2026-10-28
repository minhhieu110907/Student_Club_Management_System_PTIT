from sqlalchemy.orm import Session

from app.modules.identity.models import User


def add_user(session: Session, user: User) -> None:
    session.add(user)
    session.flush()
