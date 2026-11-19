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
        signing_key=b"e" * 32, issuer="scms-test", audience="scms-api"
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


def test_event_routes_are_exposed_in_openapi() -> None:
    with TestClient(_app(_user())) as client:
        paths = client.get("/openapi.json").json()["paths"]
    expected = {
        "/api/v1/clubs/{club_id}/events",
        "/api/v1/events",
        "/api/v1/events/{event_id}",
        "/api/v1/events/{event_id}/publish",
        "/api/v1/events/{event_id}/cancel",
        "/api/v1/events/{event_id}/registrations",
        "/api/v1/events/{event_id}/registrations/me",
        "/api/v1/event-registrations/mine",
    }
    assert expected <= set(paths)


def test_event_endpoints_require_authentication_and_student_role() -> None:
    with TestClient(_app()) as client:
        assert client.get("/api/v1/events").status_code == 401
        assert client.post("/api/v1/events/1/registrations").status_code == 401
        assert client.delete("/api/v1/events/1/registrations/me").status_code == 401

    with TestClient(_app(_user("ADMIN"))) as admin_client:
        response = admin_client.post("/api/v1/events/1/registrations")
    assert response.status_code == 403
    assert response.json()["error_code"] == "STUDENT_ROLE_REQUIRED"


def test_event_list_endpoints_validate_pagination_bounds() -> None:
    with TestClient(_app(_user())) as client:
        assert client.get("/api/v1/events?page=0&page_size=20").status_code == 422
        assert client.get("/api/v1/events?page=1&page_size=101").status_code == 422
        assert client.get("/api/v1/event-registrations/mine?page=0").status_code == 422
        assert client.get("/api/v1/events/1/registrations?page_size=101").status_code == 422
        assert client.get("/api/v1/clubs/1/events?page_size=0").status_code == 422
