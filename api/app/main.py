import logging

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mangum import Mangum
from pydantic import BaseModel

logger = logging.getLogger("fmaj")

from app.auth import AuthUser, require_user
from app.searches import (
    MonthlyCapReached,
    NotStoppable,
    QuotaExhausted,
    SearchInProgress,
    SearchRequest,
    create_search,
    get_search,
    list_searches,
    stop_search,
)
from app.settings import settings
from app.users import ensure_user

app = FastAPI(title="Find-Me-A-Job AI API", version="0.1.0")


def api_error(status: int, code: str, message: str) -> HTTPException:
    """A failure the frontend can branch on without parsing prose.

    `message` is shown to the user as-is; `code` is the stable name. The two are
    separate so copy can be reworded without breaking a client that keys off it —
    and so the client can decide, say, that a monthly cap deserves a different
    treatment from a spent personal quota, which reads identically otherwise.
    """
    return HTTPException(
        status_code=status, detail={"code": code, "message": message}
    )

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
    return JSONResponse(
        status_code=500,
        content={
            "detail": {
                "code": "internal_error",
                # The exception type, not its message: the type is enough to
                # find the log line, and messages can carry table names, ARNs or
                # user data we don't want in a browser.
                "message": f"Something went wrong on our side ({type(exc).__name__}).",
            }
        },
    )


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
    except SearchInProgress:
        # 409, not 429: nothing is being rate-limited, they simply already have
        # one running and the honest fix is to wait for it or stop it.
        raise api_error(
            409,
            "search_in_progress",
            "You already have a search running. Wait for it to finish, or stop it first.",
        ) from None
    except MonthlyCapReached:
        raise api_error(
            429,
            "monthly_cap",
            "We've hit this month's search limit while the app is in preview. "
            "Please try again next month.",
        ) from None
    except QuotaExhausted:
        raise api_error(
            402,
            "quota_exhausted",
            "Your free search has been used. Subscriptions are coming soon!",
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
        raise api_error(404, "not_found", "We couldn't find that search.")
    return found


@app.post("/searches/{search_id}/stop")
def stop_search_route(search_id: str, user: AuthUser = Depends(require_user)) -> dict:
    """Stop a running search. No quota is refunded — the work was done."""
    try:
        stopped = stop_search(user.sub, search_id)
    except NotStoppable as exc:
        raise api_error(
            409, "not_stoppable", f"This search is already {exc}."
        ) from None
    if stopped is None:
        raise api_error(404, "not_found", "We couldn't find that search.")
    return stopped


# TODO(Phase 4): GET /searches/{search_id}/report — presigned PDF URL.

# Lambda entrypoint
handler = Mangum(app)
