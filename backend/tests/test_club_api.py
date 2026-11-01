from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.security.jwt import AccessTokenSettings
from app.db.session import get_db_session
from app.main import create_app
from app.modules.clubs.schemas import ClubRequestResponse
from app.modules.identity.auth_config import AuthenticationSettings
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.schemas import CurrentUserResponse


class FakeReadinessService:
    def dispose(self) -> None:
        pass

    def is_ready(self) -> bool:
        return True


AUTH_SETTINGS = AuthenticationSettings(
    access_tokens=AccessTokenSettings(
        signing_key=b"c" * 32, issuer="scms-test", audience="scms-api"
    ),
    allowed_origins=frozenset({"http://testserver"}),
    cookie_secure=False,
)


def _response() -> ClubRequestResponse:
    now = datetime(2026, 10, 30, tzinfo=UTC)
    return ClubRequestResponse(
        id=9,
        requested_by=1,
        proposed_name="Engineering Club",
        category="Academic",
        mission="Build",
        initial_plan="Meet",
        status="PENDING",
        reviewed_by=None,
        reviewed_at=None,
        rejection_reason=None,
        created_at=now,
        updated_at=now,
    )


def _app(user: CurrentUserResponse | None = None):
    app = create_app(lambda: FakeReadinessService(), lambda: None, lambda: AUTH_SETTINGS)
    app.dependency_overrides[get_db_session] = lambda: object()
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    return app


def test_unauthenticated_submission_is_rejected() -> None:
    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/club-requests",
            json={
                "proposed_name": "Club",
                "category": "Academic",
                "mission": "Mission",
                "initial_plan": "Plan",
            },
        )
    assert response.status_code == 401


def test_student_cannot_list_admin_queue() -> None:
    student = CurrentUserResponse(
        id=1,
        email="student@example.com",
        full_name="Student",
        global_role="STUDENT",
        status="ACTIVE",
    )
    with TestClient(_app(student)) as client:
        response = client.get("/api/v1/admin/club-requests/pending")
    assert response.status_code == 403
    assert response.json()["error_code"] == "ADMIN_ROLE_REQUIRED"


def test_frontend_uses_real_club_endpoints_and_status_containers() -> None:
    root = Path(__file__).parents[2]
    javascript = (root / "frontend/js/app.js").read_text(encoding="utf-8")
    html = (root / "frontend/index.html").read_text(encoding="utf-8")
    for endpoint in (
        "/api/v1/club-requests",
        "/api/v1/club-requests/mine",
        "/api/v1/clubs/mine",
        "/api/v1/admin/club-requests/pending",
    ):
        assert endpoint in javascript
    for state_id in ("student-message", "request-list", "club-list", "admin-list", "admin-message"):
        assert f'id="{state_id}"' in html
