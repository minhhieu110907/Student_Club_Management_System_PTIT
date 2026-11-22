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
        signing_key=b"t" * 32, issuer="scms-test", audience="scms-api"
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


def test_task_routes_are_exposed_in_openapi() -> None:
    with TestClient(_app(_user())) as client:
        paths = client.get("/openapi.json").json()["paths"]
    expected = {
        "/api/v1/events/{event_id}/tasks",
        "/api/v1/event-tasks/mine",
        "/api/v1/event-tasks/{task_id}",
        "/api/v1/event-tasks/{task_id}/status",
        "/api/v1/events/{event_id}/task-progress",
    }
    assert expected <= set(paths)


def test_task_endpoints_require_auth_and_student_role() -> None:
    with TestClient(_app()) as client:
        assert client.get("/api/v1/event-tasks/mine").status_code == 401
        assert client.post("/api/v1/events/1/tasks", json={"title": "Setup"}).status_code == 401
        assert (
            client.patch("/api/v1/event-tasks/1/status", json={"status": "DONE"}).status_code == 401
        )

    with TestClient(_app(_user("ADMIN"))) as admin_client:
        response = admin_client.get("/api/v1/event-tasks/mine")
    assert response.status_code == 403
    assert response.json()["error_code"] == "STUDENT_ROLE_REQUIRED"


def test_task_list_endpoints_validate_pagination_bounds() -> None:
    with TestClient(_app(_user())) as client:
        assert client.get("/api/v1/events/1/tasks?page=0&page_size=20").status_code == 422
        assert client.get("/api/v1/events/1/tasks?page=1&page_size=101").status_code == 422
        assert client.get("/api/v1/event-tasks/mine?page=0").status_code == 422
        assert client.get("/api/v1/event-tasks/mine?page_size=101").status_code == 422
