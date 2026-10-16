"""Read-only library endpoints; business logic stays in library_service."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from api.security import _session, _current_user, _now
from api.library_service import _library_payload, _collections_payload

router = APIRouter()

@router.get("/api/export")
def export_user_data(request: Request) -> JSONResponse:
    """Account-scoped portable backup; no credentials or session tokens."""
    with _session() as session:
        user = _current_user(request, session)
        payload = {
            "format": "rateapp-export",
            "schemaVersion": 1,
            "exportedAt": _now().isoformat(),
            "nickname": user.nickname,
            "collections": _collections_payload(session, user),
            "library": _library_payload(session, user),
        }
    return JSONResponse(payload, headers={
        "Content-Disposition": 'attachment; filename="rateapp-export.json"',
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })


@router.get("/api/library")
def library(request: Request) -> list[dict[str, object]]:
    with _session() as session:
        user = _current_user(request, session)
        return _library_payload(session, user)
