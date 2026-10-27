from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.exceptions import AppException
from app.health.service import ReadinessService

router = APIRouter(prefix="/api/v1/health", tags=["health"])


@router.get("")
def legacy_health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/live")
def liveness() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/ready")
def readiness(request: Request) -> dict[str, str]:
    service: ReadinessService = request.app.state.readiness_service
    if not service.is_ready():
        raise AppException(
            "Service is not ready",
            status_code=503,
            error_code="NOT_READY",
        )
    return {"status": "ready"}
