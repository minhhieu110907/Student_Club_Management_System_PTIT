from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.core.security.jwt import AccessTokenSettings
from app.db.session import get_db_session
from app.main import create_app
from app.modules.events import service as events_service
from app.modules.events.models import Event
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


def test_managed_club_events_endpoint_returns_200_for_non_empty_and_empty(monkeypatch) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    sample_event = Event(
        id=42,
        club_id=1,
        created_by=1,
        title="Club Tech Night",
        description="Annual showcase",
        location="Main Hall",
        status="DRAFT",
        visibility="PUBLIC_STUDENTS",
        starts_at=now + timedelta(days=5),
        ends_at=now + timedelta(days=5, hours=2),
        registration_opens_at=now,
        registration_closes_at=now + timedelta(days=4),
        cancellation_deadline_at=now + timedelta(days=3),
        capacity=50,
        registration_count=0,
        version=0,
        published_at=None,
        cancelled_at=None,
        cancellation_reason=None,
        created_at=now,
        updated_at=now,
    )
    monkeypatch.setattr(events_service, "require_active_manager", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        events_service,
        "list_club_events",
        lambda *_a, **_kw: ([(sample_event, "Robotics Club")], 1),
    )

    with TestClient(_app(_user())) as client:
        non_empty = client.get("/api/v1/clubs/1/events?page=1&page_size=20")
    assert non_empty.status_code == 200
    body = non_empty.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == 42
    assert body["items"][0]["club_name"] == "Robotics Club"
    assert body["items"][0]["is_registered"] is False

    monkeypatch.setattr(events_service, "list_club_events", lambda *_a, **_kw: ([], 0))
    with TestClient(_app(_user())) as client:
        empty = client.get("/api/v1/clubs/1/events?page=1&page_size=20")
    assert empty.status_code == 200
    assert empty.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}
