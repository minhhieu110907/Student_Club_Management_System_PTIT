from fastapi.testclient import TestClient

from app.core.security.jwt import AccessTokenSettings
from app.db.session import get_db_session
from app.main import create_app
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
        signing_key=b"m" * 32, issuer="scms-test", audience="scms-api"
    ),
    allowed_origins=frozenset({"http://testserver"}),
    cookie_secure=False,
)


def _user(role: str = "STUDENT") -> CurrentUserResponse:
    return CurrentUserResponse(
        id=1,
        email="student@example.com",
        full_name="Student",
        global_role=role,
        status="ACTIVE",
    )


def _app(user: CurrentUserResponse | None = None):
    app = create_app(lambda: FakeReadinessService(), lambda: None, lambda: AUTH_SETTINGS)
    app.dependency_overrides[get_db_session] = lambda: object()
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    return app


def test_membership_endpoints_require_authentication() -> None:
    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/clubs/1/membership-applications",
            json={"motivation": "Learn"},
        )
    assert response.status_code == 401


def test_admin_cannot_use_student_membership_workflow() -> None:
    with TestClient(_app(_user("ADMIN"))) as client:
        response = client.post(
            "/api/v1/clubs/1/membership-applications",
            json={"motivation": "Bypass"},
        )
    assert response.status_code == 403
    assert response.json()["error_code"] == "STUDENT_ROLE_REQUIRED"


def test_membership_routes_are_exposed_in_openapi() -> None:
    with TestClient(_app(_user())) as client:
        paths = client.get("/openapi.json").json()["paths"]
    expected = {
        "/api/v1/clubs",
        "/api/v1/clubs/{club_id}/members",
        "/api/v1/clubs/{club_id}/membership-applications",
        "/api/v1/membership-applications/mine",
        "/api/v1/memberships/mine",
        "/api/v1/clubs/{club_id}/membership-applications/pending",
        "/api/v1/membership-applications/{application_id}/approve",
        "/api/v1/membership-applications/{application_id}/reject",
        "/api/v1/memberships/{membership_id}/leave",
    }
    assert expected <= set(paths)


def test_membership_reject_validates_reason_before_service_access() -> None:
    with TestClient(_app(_user())) as client:
        response = client.post(
            "/api/v1/membership-applications/9/reject",
            json={"rejection_reason": "   "},
        )
    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"


def test_club_members_endpoint_validates_pagination_and_requires_auth() -> None:
    with TestClient(_app()) as unauth_client:
        unauth_response = unauth_client.get("/api/v1/clubs/1/members")
    assert unauth_response.status_code == 401

    with TestClient(_app(_user("ADMIN"))) as admin_client:
        admin_response = admin_client.get("/api/v1/clubs/1/members")
    assert admin_response.status_code == 403
    assert admin_response.json()["error_code"] == "STUDENT_ROLE_REQUIRED"

    with TestClient(_app(_user())) as client:
        bad_page = client.get("/api/v1/clubs/1/members?page=0&page_size=20")
        bad_size = client.get("/api/v1/clubs/1/members?page=1&page_size=101")
    assert bad_page.status_code == 422
    assert bad_size.status_code == 422
