from sqlalchemy.orm import Session

from app.modules.clubs.exceptions import ClubManagerRequiredError
from app.modules.clubs.repository import (
    find_active_manager_membership,
    find_active_manager_membership_for_update,
)


def require_active_manager(
    session: Session, club_id: int, user_id: int, *, for_update: bool
) -> None:
    finder = (
        find_active_manager_membership_for_update if for_update else find_active_manager_membership
    )
    if finder(session, club_id, user_id) is None:
        raise ClubManagerRequiredError()
