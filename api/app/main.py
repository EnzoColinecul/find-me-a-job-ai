import logging

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mangum import Mangum
from pydantic import BaseModel

logger = logging.getLogger("fmaj")

from app.auth import AuthUser, require_user
from app.searches import (
    QuotaExhausted,
    SearchRequest,
    create_search,
    get_search,
    list_searches,
)
from app.settings import settings
from app.users import ensure_user

app = FastAPI(title="Find-Me-A-Job AI API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return JSON 500s through the middleware stack so CORS headers are applied.

    Without this, unhandled exceptions bypass CORSMiddleware and the browser reports
    an opaque 'Failed to fetch' instead of the real error.
    """
    logger.exception("Unhandled error on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=500, content={"detail": f"Internal error: {type(exc).__name__}"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "stage": settings.stage}


@app.get("/config")
def get_config() -> dict:
    """Client-visible limits. The frontend reads these instead of hardcoding them,
    so raising max_roles (e.g. with subscriptions) needs no frontend change."""
    return {
        "max_roles": settings.max_roles,
        "max_radius_km": settings.max_radius_km,
        "radius_options_km": [1, 5, 10],
    }


class InterpretRequest(BaseModel):
    text: str


@app.post("/roles/interpret")
def interpret(req: InterpretRequest, user: AuthUser = Depends(require_user)) -> dict:
    """Turn the user's free-text description into role suggestions to confirm.

    Does NOT consume the free-search quota — users can rephrase as often as they like.
    """
    from fmaj_agent.interpret import interpret_roles

    result = interpret_roles(req.text)
    return {
        "roles": [s.model_dump() for s in result.roles],
        "ok": result.ok,
        "message": result.message,
        "max_roles": settings.max_roles,
    }


@app.get("/me")
def me(user: AuthUser = Depends(require_user)) -> dict:
    """Return the signed-in user's profile, creating it on first sign-in."""
    profile = ensure_user(user.sub, user.email, user.name)
    return {
        "sub": user.sub,
        "email": profile["email"],
        "name": profile.get("name") or None,
        "free_search_used": profile["free_search_used"],
    }


@app.post("/searches", status_code=201)
def post_search(req: SearchRequest, user: AuthUser = Depends(require_user)) -> dict:
    try:
        meta = create_search(user.sub, req)
    except QuotaExhausted:
        raise HTTPException(
            status_code=402,
            detail="Your free search has been used. Subscriptions are coming soon!",
        ) from None
    return {"search_id": meta["search_id"], "status": meta["status"]}


@app.get("/searches")
def list_searches_route(
    limit: int = Query(default=10, ge=1, le=50),
    user: AuthUser = Depends(require_user),
) -> dict:
    """The signed-in user's recent searches, newest first (workspace left rail).

    Descriptive only — no status. The rail links through to /searches/{id}, which
    polls the live status, so nothing here can go stale.
    """
    return {"searches": list_searches(user.sub, limit)}


@app.get("/searches/{search_id}")
def get_search_route(search_id: str, user: AuthUser = Depends(require_user)) -> dict:
    found = get_search(user.sub, search_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Search not found")
    return found


# TODO(Phase 4): GET /searches/{search_id}/report — presigned PDF URL.

# Lambda entrypoint
handler = Mangum(app)
